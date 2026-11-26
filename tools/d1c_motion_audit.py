#!/usr/bin/env python3
"""Source-versus-built motion audit for Disgaea 1 Complete packs (D1CRIG1, 2026-11-23).  No game, read-only.

    python tools/d1c_motion_audit.py MODS_DIR [--only D1C_Class_11390,...] [--out DIR] [--gate]
                                     [--max-diff 1.0] [--max-feet 1] [--body-cache DIR]

For every D1C pack in MODS_DIR (``mod.json`` ``source_import.identity.source == 'd1c'``) and every animation of its
battle bank (``anm<sprite>.lzs``), the D1C source playback of the same motion is rendered at each of the source's
key times and compared with the built bank at the same time:

  source     the D1C motion that plays in that slot: for a block-1 humanoid (D1C ``FUN_7100046000``) the shared
             block-1 motion that is the same as D5's id (``d1crig.D5_TO_D1C``) on the body's art, or the body's own
             animation (6001/6007/7001...); for a monster the body's own animation with the same id
  diff       percent of drawn pixels that differ (RGB max > 24 or alpha in one only) at the worst key time
  feet       the built picture's bottom row minus the source's (y down, px), worst key; dx the same for the centre
  cycle      the last key time (loop end) built vs source
  origin     source       every key equals the source (diff <= --max-diff, |feet| <= --max-feet)
             offset       the pictures equal the source's after a shift: the drawing is right, the ground is not
             held         one picture at every key while the source moves
             stand        only the stand / idle pictures (a still drawing slid by another motion's tracks)
             differs      something else
             no-source    D5 has the id, D1C does not (D5 logic plays it; nothing to compare against)
             missing      the source has the motion, the bank does not
             blank        the bank draws nothing at any key

Writes ``audit.json`` and ``REPORT.md`` into --out (default ``<MODS_DIR>/../d1c-motion-audit``).
``--gate`` exits 1 when a pack built with the source rig (``source_import.d1c_rig``) has a motion with a source
twin that is not ``source``, or any pack fails ``--require`` (a comma list of origin classes every comparable
motion must be in; default: ``source`` for rig packs, nothing for others).  ``gate(pack)`` is the same check for
the importer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

from d5lib import anm, d1crig  # noqa: E402

BOUNDS = (-280, -340, 280, 140)
PIXEL = 24
STILL = {1, 7, 101, 107, 1001, 1007, 6001, 6007, 7001, 7007}
BANK_DIR = Path('files/Anime/ANM_HI_JP.dat')


# ------------------------------------------------------------------------------------------------ source side
class Source:
    """The D1C source bodies (through the kit's prepared-source reader, or a folder of extracted body files)."""

    def __init__(self, cache=None):
        self.cache = Path(cache) if cache else None
        self._files = {}

    def body(self, body):
        body = int(body)
        if body not in self._files:
            path = self.cache / f'{body}.anm' if self.cache else None
            if path is not None and path.is_file():
                self._files[body] = anm.load(path)
            else:
                from d5lib.importers import _d1c_source
                self._files[body] = anm.parse(_d1c_source.body_bytes(body))
                if path is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(self._files[body].to_bytes())
        return self._files[body]

    def view(self, body):
        """(render view, humanoid on block 1): the shared block 1 + the body block over the body's images."""
        b = self.body(body)
        if len(b.blocks[0].animations) > d1crig.MAX_OWN_ANIMATIONS:
            return b, False
        return combined(self.body(1), b), True


def combined(motion, body):
    import copy
    mb = copy.copy(motion.blocks[0])
    mb.tex_base = mb.pal_base = 0
    mb.palette_infos = list(body.blocks[0].palette_infos)
    bb = copy.copy(body.blocks[0])
    bb.tex_base = bb.pal_base = 0
    return anm.AnmFile([mb, bb], body.textures, body.palettes)


# ------------------------------------------------------------------------------------------------ rendering
def picture(f, aid, t, palette):
    items = anm.evaluate(f, ('id', aid), t, nested=True, game=True)
    if not items:
        return None
    img, _ = anm.render_items(f, items, palette, bounds=BOUNDS)
    a = np.asarray(img).astype(np.int16)
    if not (a[..., 3] > 16).any():
        return None
    return a


def bbox(a):
    ys, xs = np.where(a[..., 3] > 16)
    return xs.min() + BOUNDS[0], ys.min() + BOUNDS[1], xs.max() + 1 + BOUNDS[0], ys.max() + 1 + BOUNDS[1]


def diff_pct(a, b):
    if a is None and b is None:
        return 0.0
    if a is None or b is None:
        return 100.0
    ma, mb = a[..., 3] > 16, b[..., 3] > 16
    union = ma | mb
    if not union.any():
        return 0.0
    bad = (ma != mb) | (ma & mb & (np.abs(a[..., :3] - b[..., :3]).max(-1) > PIXEL))
    return float(100.0 * bad[union].sum() / union.sum())


def shifted(a, dx, dy):
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = a[ys, xs]
    return out


def thumb(a):
    """the picture without its position: bbox crop, 24x48, premultiplied (for 'same drawing' tests)"""
    from PIL import Image
    ys, xs = np.where(a[..., 3] > 16)
    c = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    c[..., :3] *= c[..., 3:4] / 255.0
    im = Image.fromarray(np.clip(c, 0, 255).astype(np.uint8), 'RGBA').resize((24, 48), Image.BILINEAR)
    return np.asarray(im).astype(np.float32), (xs.max() - xs.min(), ys.max() - ys.min())


def same_drawing(x, y, tol=10.0):
    (ta, sa), (tb, sb) = x, y
    if abs(sa[0] - sb[0]) > 3 or abs(sa[1] - sb[1]) > 3:
        return False
    return float(np.abs(ta - tb).mean()) < tol


def last_key(f, aid):
    bi, ai = anm._resolve_anim(f, ('id', aid))
    info = anm.animation_info(f.blocks[bi], f.blocks[bi].animations[ai])
    ts = anm.frame_times(f, ('id', aid))
    return int(info['loop'][1]) if info.get('loop') else int(ts[-1])


# ------------------------------------------------------------------------------------------------ packs
def d1c_packs(mods):
    out = []
    for mod in sorted(Path(mods).iterdir()):
        mj = mod / 'mod.json'
        if not mj.is_file():
            continue
        try:
            si = json.loads(mj.read_text()).get('source_import') or {}
        except ValueError:
            continue
        ident = si.get('identity') or {}
        if ident.get('source') != 'd1c':
            continue
        cj = mod / 'patches/db/char.dat.json'
        sprites = []
        if cj.is_file():
            sprites = sorted({int(r['sprite_id']) for r in json.loads(cj.read_text()).get('added') or []
                              if r.get('sprite_id')})
        uj = mod / 'patches/characters/unique.json'
        classes = list((mod / 'patches/classes').glob('*.json')) if (mod / 'patches/classes').is_dir() else []
        sprite = None
        if uj.is_file():
            sprite = int(json.loads(uj.read_text()).get('physical'))
        elif classes:
            spec = json.loads(classes[0].read_text())
            spec = spec[0] if isinstance(spec, list) else spec
            sprite = int(spec.get('sprite_family') or spec.get('family'))
        elif sprites:
            sprite = sprites[0] - sprites[0] % 10
        bank = mod / BANK_DIR / f'anm{sprite:05d}.lzs' if sprite is not None else None
        if bank is None or not bank.is_file():
            continue
        unique = uj.is_file()
        palette = int(ident.get('palette') or 0) if unique else 0
        palette = {3060: 2}.get(int(ident.get('character_id') or 0), palette) if unique else 0
        out.append(dict(folder=mod.name, path=mod, bank=bank, sprite=sprite, body=int(ident['body']),
                        character_id=int(ident['character_id']), palette=palette,
                        rig=bool(si.get('d1c_rig'))))
    return out


def audit_pack(src, pack, max_diff=1.0, max_feet=1):
    """{animation id: row} for one pack (see the module docstring)."""
    view, humanoid = src.view(pack['body'])
    body = src.body(pack['body'])
    spal = min(pack['palette'], len(body.palettes) - 1)
    built = anm.load(pack['bank'])
    built_ids = [a.id for a in built.blocks[0].animations]
    own = {a.id for a in body.blocks[0].animations}
    rows = {}
    stills = {}
    for aid in sorted(set(built_ids) | (set(own) if not humanoid else set())):
        if aid == 0:
            continue
        if humanoid:
            # D1C plays a humanoid's motions from block 1 and only the idle/special ids (6001.., 7001..) from the
            # body; a body's own 5000/5001 (Dark Flonne 30) is never what D1C shows for that id
            twin = aid if aid in own and aid >= 6000 else d1crig.D5_TO_D1C.get(aid)
            if aid in (7001, 7007, 7011, 7021, 7031) and aid not in own:
                twin = None
        else:
            twin = aid if aid in own else None
        if aid not in built_ids:
            rows[aid] = dict(origin='missing', source=twin)
            continue
        bt = anm.frame_times(built, ('id', aid))
        bpics = [picture(built, aid, t, 0) for t in bt]
        if not any(p is not None for p in bpics):
            src_blank = twin is not None and not any(
                picture(view, twin, t, spal) is not None for t in anm.frame_times(view, ('id', twin)))
            rows[aid] = dict(origin='source' if src_blank else 'blank', source=twin,
                             **(dict(note='draws nothing, as the source') if src_blank else {}))
            continue
        if twin is None:
            first = next(p for p in bpics if p is not None)
            rows[aid] = dict(origin='no-source', feet_built=int(bbox(first)[3]), cycle=[last_key(built, aid), None])
            continue
        st = anm.frame_times(view, ('id', twin))
        worst = dict(diff=0.0, feet=0, dx=0.0, aligned=0.0, t=st[0])
        distinct = []
        for t in st:
            s = picture(view, twin, t, spal)
            p = picture(built, aid, t, 0)
            d = diff_pct(p, s)
            feet = dx = 0
            aligned = d
            if p is not None and s is not None:
                pb, sb = bbox(p), bbox(s)
                feet = int(pb[3] - sb[3])
                dx = round((pb[0] + pb[2] - sb[0] - sb[2]) / 2, 1)
                if d > max_diff:
                    aligned = diff_pct(shifted(p, -int(round(dx)), -feet), s)
                th = thumb(p)
                if not any(same_drawing(th, o) for o in distinct):
                    distinct.append(th)
            if d > worst['diff'] or abs(feet) > abs(worst['feet']):
                worst = dict(diff=round(d, 2), feet=feet, dx=dx, aligned=round(aligned, 2), t=int(t))
        cycle = [last_key(built, aid), last_key(view, twin)]
        if worst['diff'] <= max_diff and abs(worst['feet']) <= max_feet:
            origin = 'source'
        elif worst['aligned'] <= max_diff:
            origin = 'offset'
        elif len(distinct) <= 1 and len(st) > 1:
            origin = 'held'
        else:
            origin = 'differs'
        rows[aid] = dict(origin=origin, source=twin, cycle=cycle, keys=[len(bt), len(st)], **worst)
        stills[aid] = distinct
    # "stand": every built picture is one of the stand / idle pictures while the source motion moves
    still_set = [th for a in STILL for th in stills.get(a, [])]
    for aid, r in rows.items():
        if r['origin'] in ('differs', 'held') and aid not in STILL and stills.get(aid) and \
                all(any(same_drawing(th, o) for o in still_set) for th in stills[aid]):
            r['origin'] = 'stand'
    return rows


def summary(rows):
    out = {}
    for r in rows.values():
        out[r['origin']] = out.get(r['origin'], 0) + 1
    return out


def gate(pack, rows=None, src=None, require=None, max_diff=1.0, max_feet=1):
    """(ok, why) for one pack: rig packs need every motion with a source twin to be 'source'."""
    if rows is None:
        rows = audit_pack(src or Source(), pack, max_diff, max_feet)
    need = set(require or (('source',) if pack.get('rig') else ()))
    if not need:
        return True, 'report only (not a rig pack)'
    bad = sorted(a for a, r in rows.items() if r['origin'] not in need | {'no-source', 'blank'} or
                 (r['origin'] == 'blank' and r.get('source') is not None))
    if bad:
        return False, f"{len(bad)} motion(s) not {'/'.join(sorted(need))}: " + ', '.join(
            f"{a} {rows[a]['origin']}" for a in bad[:8])
    return True, f"{sum(1 for r in rows.values() if r['origin'] == 'source')} motions equal the D1C source"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mods', type=Path)
    ap.add_argument('--only')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--gate', action='store_true')
    ap.add_argument('--require', help='origin classes every comparable motion must be in (all packs)')
    ap.add_argument('--max-diff', type=float, default=1.0)
    ap.add_argument('--max-feet', type=int, default=1)
    ap.add_argument('--body-cache', type=Path, help='folder of extracted D1C body files (<body>.anm), read/write')
    args = ap.parse_args(argv)
    packs = d1c_packs(args.mods)
    if args.only:
        keep = set(args.only.split(','))
        packs = [p for p in packs if p['folder'] in keep]
    src = Source(args.body_cache)
    out = args.out or args.mods.parent / 'd1c-motion-audit'
    out.mkdir(parents=True, exist_ok=True)
    results, failed = {}, []
    require = args.require.split(',') if args.require else None
    for p in packs:
        rows = audit_pack(src, p, args.max_diff, args.max_feet)
        ok, why = gate(p, rows, require=require, max_diff=args.max_diff, max_feet=args.max_feet)
        cmp_ = [r for r in rows.values() if r.get('source') is not None and r['origin'] != 'missing']
        results[p['folder']] = dict(body=p['body'], character_id=p['character_id'], sprite=p['sprite'], rig=p['rig'],
                                    counts=summary(rows), gate=ok, why=why,
                                    feet_worst=max((abs(r.get('feet', 0)) for r in cmp_), default=0),
                                    cycle_mismatch=sorted(a for a, r in rows.items()
                                                          if r.get('cycle') and r['cycle'][1] is not None
                                                          and r['cycle'][0] != r['cycle'][1]),
                                    motions={str(a): r for a, r in rows.items()})
        if not ok:
            failed.append(p['folder'])
        print(f"{p['folder']}: {summary(rows)} gate={'PASS' if ok else 'FAIL'} {why}", flush=True)
    (out / 'audit.json').write_text(json.dumps(dict(mods=str(args.mods), max_diff=args.max_diff,
                                                    max_feet=args.max_feet, packs=results), indent=1))
    lines = [f"# D1C motion audit\n\nPacks: `{args.mods}`. A motion is `source` when every source key time differs by "
             f"<= {args.max_diff}% of drawn pixels and the feet line by <= {args.max_feet} px.\n",
             "| Pack | Body | Rig | source | offset | held | stand | differs | no-source | missing | blank | worst feet | "
             "cycle != source | Gate |", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for k, v in results.items():
        c = v['counts']
        lines.append(f"| {k} | {v['body']} | {'yes' if v['rig'] else 'no'} | " + ' | '.join(
            str(c.get(x, 0)) for x in ('source', 'offset', 'held', 'stand', 'differs', 'no-source', 'missing', 'blank'))
            + f" | {v['feet_worst']} | {len(v['cycle_mismatch'])} | {'PASS' if v['gate'] else 'FAIL'} |")
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(f'wrote {out}/audit.json and REPORT.md')
    return 1 if (args.gate and failed) else 0


if __name__ == '__main__':
    sys.exit(main())
