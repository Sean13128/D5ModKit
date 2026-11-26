#!/usr/bin/env python3
"""Source-versus-built motion audit for Disgaea 4 packs (D4IDLE1, 2026-11-24).  No game, read-only.

    python tools/d4_motion_audit.py MODS_DIR [--only D4_Class_2120,...] [--out DIR] [--gate]
                                    [--max-diff 1.0] [--max-feet 1] [--source-root GAME_DIR] [--jobs N]

Turns SRCFID2-D4B's comparator (Research/import-checklist/d4-survey/scripts-b/motion_audit_b.py) into a kit tool, in
the shape of tools/d1c_motion_audit.py.  For every D4 pack in MODS_DIR (``mod.json`` ``source_import``: a class has
``identity``, a unique ``source_game == 'd4'``) and every animation of its battle bank, the D4 playback of the same
motion is rendered at every key time of BOTH sides and compared.  The D4 side follows the engine (docs: Research
``D4-RENDER-PIPELINE.md``):

  humanoid (D4 char +0x298 == 0)  the body block FIRST, then shared block 1 (anm00001) bound to the body's pages and
                                  palettes; the body is reached through the stubs 1001/1007 (key 1 attachment)
  monster  (+0x298 == 1)          the body's own animations
  nodes with id 21/31 draw nothing on either side (D4 never binds key 31, disables key 21; D5 disables both)

Per motion ``origin``:
  source      every key (of both sides) differs by <= --max-diff % of drawn pixels, feet <= --max-feet px, and the
              key times and loop end are the same
  offset      the pictures equal the source's after a shift (right drawing, wrong ground)
  held        one picture where the source moves
  stand       only the stand / idle pictures
  differs     something else
  blank       the bank draws nothing where D4 draws
  missing     D4 has the motion, the bank does not
  no-source   D5-only id (nothing to compare against); ``no-source-blank`` when it also draws nothing

Labels.  A donor-body pack (Toro, Kuro, Politan: D4's file holds 3-7 motions) carries D4's own motions and HOLDS the
source stand picture for the states D4 never drew; the importer labels those ids in ``mod.json``
``source_import.motion_origin`` (``held`` = {id: source motion it plays}, ``d5_only`` = empty attachments).  The audit
compares every labelled held id with the picture of the source motion it names, on the source's ground line.

Gate (``--gate`` exits 1 on any failed pack; it is enforced on EVERY D4 pack, not only some):
  * every motion with a D4 twin is ``source`` with equal timing, except
      - ids labelled held whose picture equals the named source motion (diff <= --max-diff, feet <= --max-feet),
      - ids 14/24/34 on a humanoid when the bank draws nothing (D4's 8-facing whole-frame ids: on those bodies the
        data draws cape strips from page 9, not a figure; documented harmless in SRCFID2-D4B), reported as ``allowed``
  * the pack must have at least ``--min-comparable`` motions with a D4 twin (so a pack that compares nothing cannot pass)
  * a pack the audit cannot read (no source row, no bank) FAILS; it is never skipped.
``gate(rows, pack)`` is the same check for the importer; ``audit_pack(src, pack)`` returns the rows.
Writes ``audit.json`` and ``REPORT.md`` into --out (default ``<MODS_DIR>/../d4-motion-audit``).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

from d5lib import anm, d4source, gamefs  # noqa: E402

BOUNDS = (-280, -340, 280, 140)
PIXEL = 24
STILL = {1, 7, 101, 107, 1001, 1007, 6001, 6007, 7001, 7007}
BANK_DIR = Path('files/Anime/ANM_HI_JP.dat')
SOURCE_ROOT = Path('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+')
ALLOW_BLANK = {14, 24, 34}            # humanoid 8-facing ids, documented harmless (SRCFID2-D4B verdict 2)
MIN_COMPARABLE = 2


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


def times(f, aid):
    try:
        return [int(t) for t in anm.frame_times(f, ('id', aid))]
    except Exception:                                    # noqa: BLE001
        return []


def last_key(f, aid):
    try:
        bi, ai = anm._resolve_anim(f, ('id', aid))
        info = anm.animation_info(f.blocks[bi], f.blocks[bi].animations[ai])
        ts = anm.frame_times(f, ('id', aid))
        return int(info['loop'][1]) if info.get('loop') else int(ts[-1])
    except Exception:                                    # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------------------ source side
class Source:
    """The D4 Complete+ tables and body banks, read from the original game copy."""

    def __init__(self, root=SOURCE_ROOT):
        root = Path(root)
        self.root = root
        self.data = d4source.D4Data(root, locate=lambda rel: root / rel)
        self._anm = {}

    def anm(self, n):
        if n not in self._anm:
            # D4MESH1: the source side is what the game draws, so D4's mesh nodes keep their stored vertices
            # (D4-ANM-08); a pack that places them as pivoted rectangles then fails the audit.
            self._anm[n] = self.data.anm(n, mesh_nodes=True)
        return self._anm[n]

    def char(self, sid):
        return self.data.chars[int(sid)]


def disabled(a):
    a = copy.deepcopy(a)
    for b in a.blocks:
        for node in b.nodes:
            if node.id in (21, 31):
                for k in b.node_keys(node):
                    k.cell = 0
    return a


def source_view(src, info):
    body = src.anm(info['body'])
    if info['humanoid'] is False:
        return body
    s = anm.bind_motion_set(src.anm(1), 0, body)
    bb = copy.copy(body.blocks[0])
    bb.tex_base = bb.pal_base = 0
    return disabled(anm.AnmFile([bb] + s.blocks, body.textures, body.palettes))


def built_view(info, bank):
    return disabled(bank) if info['humanoid'] else bank


# ------------------------------------------------------------------------------------------------ packs
def d4_packs(mods):
    """[{folder, path, kind, sid, sprite, bank, labels}] for every D4 pack folder (a folder that is not readable is
    returned with ``error`` so the gate can fail it)."""
    out = []
    for mod in sorted(Path(mods).iterdir()):
        mj = mod / 'mod.json'
        if not mj.is_file() or not mod.name.startswith('D4_'):
            continue
        row = dict(folder=mod.name, path=mod)
        try:
            doc = json.loads(mj.read_text())
            si = doc.get('source_import') or {}
            cls = 'Class' in mod.name
            sid = int((si.get('identity') or {})['character_id']) if cls else int(si['source_id'])
            ch = json.loads((mod / 'patches/db/char.dat.json').read_text())['added'][0]
            row.update(kind='class' if cls else 'unique', sid=sid, sprite=int(ch['sprite_id']),
                       labels=(si.get('motion_origin') or {}))
            row['bank'] = mod / BANK_DIR / f"anm{row['sprite']:05d}.lzs"
            if not row['bank'].is_file():
                row['error'] = f"bank {row['bank'].name} missing"
        except Exception as exc:                                 # noqa: BLE001
            row['error'] = f'{type(exc).__name__}: {exc}'
        out.append(row)
    return out


def pack_info(src, pack):
    ch = src.char(pack['sid'])
    return dict(sid=pack['sid'], body=int(ch['sprite']), humanoid=int(ch['body_type']) == 0)


# ------------------------------------------------------------------------------------------------ audit
def audit_pack(src, pack, max_diff=1.0, max_feet=1):
    """({animation id: row}, info) for one pack (see the module docstring)."""
    info = pack_info(src, pack)
    bank = anm.load(pack['bank'])
    view = source_view(src, info)
    bl = built_view(info, bank)
    body = src.anm(info['body'])
    own = {a.id for a in body.blocks[0].animations}
    hum = info['humanoid']
    src_ids = ({a.id for a in src.anm(1).blocks[0].animations} | own) if hum else own
    built_ids = [a.id for a in bl.blocks[0].animations]
    labels = pack.get('labels') or {}
    held = {int(k): int(v) for k, v in (labels.get('held') or {}).items()}
    probe = 1 if 1 in built_ids else built_ids[1]
    bp = picture(bl, probe, 0, 0)
    best = (1e9, 0)
    for k in range(len(body.palettes)):
        d = diff_pct(bp, _try(lambda: picture(view, probe, 0, k)))
        if d < best[0]:
            best = (d, k)
    spal = best[1]
    rows, stills = {}, {}
    for aid in sorted(set(built_ids) | src_ids):
        if aid == 0:
            continue
        twin = aid if aid in src_ids else None
        if aid not in built_ids:
            rows[aid] = dict(origin='missing', source=twin)
            continue
        bt = times(bl, aid)
        bpics = [picture(bl, aid, t, 0) for t in bt]
        if aid in held and twin is None:
            rows[aid] = _held_row(view, bl, aid, held[aid], bt, bpics, spal, max_diff)
            continue
        if not any(p is not None for p in bpics):
            sblank = twin is not None and not any(picture(view, twin, t, spal) is not None for t in times(view, twin))
            rows[aid] = dict(origin='source' if sblank else ('blank' if twin is not None else 'no-source-blank'),
                             source=twin, both_blank=sblank)
            continue
        if twin is None:
            first = next(p for p in bpics if p is not None)
            rows[aid] = dict(origin='no-source', feet_built=int(bbox(first)[3]), cycle=[last_key(bl, aid), None])
            continue
        st = times(view, twin)
        worst = dict(diff=0.0, feet=0, dx=0.0, aligned=0.0, t=st[0] if st else 0)
        distinct = []
        for t in sorted(set(st) | set(bt)):
            s = picture(view, twin, t, spal)
            p = picture(bl, aid, t, 0)
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
        cyc = [last_key(bl, aid), last_key(view, twin)]
        timing_equal = (bt == st and cyc[0] == cyc[1])
        if worst['diff'] <= max_diff and abs(worst['feet']) <= max_feet:
            origin = 'source'
        elif worst['aligned'] <= max_diff:
            origin = 'offset'
        elif len(distinct) <= 1 and len(st) > 1:
            origin = 'held'
        else:
            origin = 'differs'
        rows[aid] = dict(origin=origin, source=twin, cycle=cyc, keys=[len(bt), len(st)], timing_equal=timing_equal, **worst)
        stills[aid] = distinct
    still_set = [th for a in STILL for th in stills.get(a, [])]
    for aid, r in rows.items():
        if r['origin'] in ('differs', 'held') and aid not in STILL and stills.get(aid) and \
                all(any(same_drawing(th, o) for o in still_set) for th in stills[aid]):
            r['origin'] = 'stand'
    return rows, info


def _try(fn):
    try:
        return fn()
    except Exception:                                    # noqa: BLE001
        return None


def _held_row(view, bl, aid, twin, bt, bpics, spal, max_diff):
    """A labelled held id: every built key must draw the first picture of the source motion it names, on its ground line."""
    st = times(view, twin)
    s = picture(view, twin, st[0] if st else 0, spal)
    worst = dict(diff=0.0, feet=0)
    for p in bpics:
        d = diff_pct(p, s)
        feet = int(bbox(p)[3] - bbox(s)[3]) if p is not None and s is not None else 0
        if d > worst['diff'] or abs(feet) > abs(worst['feet']):
            worst = dict(diff=round(d, 2), feet=feet)
    return dict(origin='held', source=None, held_from=twin, labelled=True, **worst)


# ------------------------------------------------------------------------------------------------ gate
def gate(rows, pack=None, info=None, max_diff=1.0, max_feet=1, min_comparable=MIN_COMPARABLE):
    """(ok, why, counts) -- see the module docstring."""
    hum = bool((info or {}).get('humanoid'))
    bad, allowed, comparable = [], [], 0
    for aid, r in sorted(rows.items()):
        o = r['origin']
        if o in ('no-source', 'no-source-blank'):
            continue
        if r.get('labelled'):
            if abs(r['feet']) > max_feet or r['diff'] > max_diff:
                bad.append(f"{aid} held (diff {r['diff']}%, feet {r['feet']})")
            continue
        comparable += 1
        if o == 'source' and r.get('timing_equal', True):
            continue
        if o == 'blank' and hum and aid in ALLOW_BLANK:
            allowed.append(aid)
            continue
        bad.append(f"{aid} {o}" + ('' if o != 'source' else ' (key times differ)')
                   + (f" (feet {r.get('feet')}, dx {r.get('dx')})" if o == 'offset' else ''))
    if comparable < min_comparable:
        bad.append(f'only {comparable} motion(s) compared (need {min_comparable})')
    ok = not bad
    why = (f"{comparable} motions equal D4" + (f", {len(allowed)} documented blank {allowed}" if allowed else '')) if ok \
        else f"{len(bad)} not equal: " + ', '.join(bad[:8]) + (' ...' if len(bad) > 8 else '')
    return ok, why, dict(comparable=comparable, allowed=allowed)


def summary(rows):
    out = {}
    for r in rows.values():
        out[r['origin']] = out.get(r['origin'], 0) + 1
    return out


def run_pack(args):
    pack, max_diff, max_feet, source_root = args
    folder = pack['folder']
    if pack.get('error'):
        return folder, dict(gate=False, why='unreadable: ' + pack['error'], counts={}, motions={})
    try:
        rows, info = audit_pack(Source(source_root), pack, max_diff, max_feet)
    except Exception as exc:                                     # noqa: BLE001
        return folder, dict(gate=False, why=f'audit failed: {type(exc).__name__}: {exc}', counts={}, motions={})
    ok, why, extra = gate(rows, pack, info, max_diff, max_feet)
    cmp_ = [r for r in rows.values() if r.get('source') is not None and r['origin'] != 'missing']
    return folder, dict(sid=pack['sid'], body=info['body'], humanoid=info['humanoid'], counts=summary(rows), gate=ok, why=why,
                        comparable=extra['comparable'], allowed=extra['allowed'],
                        labelled_held=len((pack.get('labels') or {}).get('held') or {}),
                        feet_worst=max((abs(r.get('feet', 0)) for r in cmp_), default=0),
                        timing_differs=sorted(a for a, r in rows.items() if r.get('timing_equal') is False),
                        motions={str(a): r for a, r in rows.items()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mods', type=Path)
    ap.add_argument('--only')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--gate', action='store_true')
    ap.add_argument('--max-diff', type=float, default=1.0)
    ap.add_argument('--max-feet', type=int, default=1)
    ap.add_argument('--source-root', type=Path, default=SOURCE_ROOT, help='the original Disgaea 4 Complete+ game folder')
    ap.add_argument('--jobs', type=int, default=1)
    args = ap.parse_args(argv)
    packs = d4_packs(args.mods)
    if args.only:
        keep = set(args.only.split(','))
        packs = [p for p in packs if p['folder'] in keep]
    if not packs:
        print('no D4 packs found in', args.mods)
        return 1
    out = args.out or args.mods.parent / 'd4-motion-audit'
    out.mkdir(parents=True, exist_ok=True)
    work = [(p, args.max_diff, args.max_feet, args.source_root) for p in packs]
    results = {}
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.get_context('spawn').Pool(args.jobs) as pool:
            for folder, res in pool.imap_unordered(run_pack, work):
                results[folder] = res
                print(f"{folder}: {res['counts']} gate={'PASS' if res['gate'] else 'FAIL'} {res['why']}", flush=True)
    else:
        for w in work:
            folder, res = run_pack(w)
            results[folder] = res
            print(f"{folder}: {res['counts']} gate={'PASS' if res['gate'] else 'FAIL'} {res['why']}", flush=True)
    results = dict(sorted(results.items()))
    failed = [k for k, v in results.items() if not v['gate']]
    strict = [k for k, v in results.items() if v['gate'] and not v.get('allowed')]
    (out / 'audit.json').write_text(json.dumps(dict(mods=str(args.mods), max_diff=args.max_diff, max_feet=args.max_feet,
                                                    packs=results), indent=1))
    lines = [f"# D4 motion audit\n\nPacks: `{args.mods}`. A motion is `source` when every key time of both sides differs by "
             f"<= {args.max_diff}% of drawn pixels, the feet line by <= {args.max_feet} px and the key times are equal.\n",
             f"Gate: {len(results) - len(failed)} of {len(results)} packs pass; {len(strict)} equal D4 with no exception.\n",
             "| Pack | source | offset | held | stand | differs | blank | missing | no-source | labelled held | worst feet | "
             "key times differ | Gate | Why |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for k, v in results.items():
        c = v['counts']
        lines.append(f"| {k} | " + ' | '.join(str(c.get(x, 0)) for x in
                     ('source', 'offset', 'held', 'stand', 'differs', 'blank', 'missing', 'no-source'))
                     + f" | {v.get('labelled_held', 0)} | {v.get('feet_worst', 0)} | {len(v.get('timing_differs', []))} | "
                     f"{'PASS' if v['gate'] else 'FAIL'} | {v['why'][:120]} |")
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print(f'{len(results) - len(failed)}/{len(results)} packs pass the gate ({len(strict)} with no exception); '
          f'wrote {out}/audit.json and REPORT.md')
    return 1 if (args.gate and failed) else 0


if __name__ == '__main__':
    sys.exit(main())
