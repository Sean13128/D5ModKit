"""ANIMALL2: rebuild the D4 packs ANIMALL skipped on D4's own tracks, and re-root the wheel stubs.

Offline only.  Two jobs:

* NEW packs -- merge the D4 source bank the way ANIMALL did, fill the donor-only motion ids from the
  documented table below (or a held pose from the class's own body when D4 has no such motion), prove
  every source-authored motion pixel-identical in the kit evaluator, then write the two banks.
* FIX packs -- take a bank ANIMALL already built and re-root motions 1001/1007 on the class's own
  idle (6001/6007) when they are the donor's one-key 0x100 stub (PT1029 W2's Battle Suit pattern).

Nothing here writes outside --out.  See playtest/ANIMALL2-REPORT.md for every rule and its evidence.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np

from d5lib import anm, d4source, ownanim

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from tools.animall2_tracks import build as human_merge, build_monster  # noqa: E402

R = Path('/Volumes/Data/Projects/D5')
D4ROOT = '/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+'

# ---------------------------------------------------------------- the documented donor-only table
# Humanoid extras, D5 ids the D4 shared block (anm00001 block 0) does not carry.
HUMAN = {
    41: 21, 47: 27,                       # dash pair -> D4 walk pair (DEFAULT_MAP: 41 dash, 21 walk)
    1561: 1, 1567: 7, 1571: 1, 1577: 7,   # D5 stand placeholders (single-frame, 0x100 -> 70xx)
    1581: 1, 1587: 7, 1591: 1, 1597: 7,
    1601: 1, 1607: 7,
    7001: 1, 7007: 7,                     # stance pair (DEFAULT_MAP 7001 = wait)
    7011: 1051, 7021: 2001,               # ANIMALL's documented special stand-ins
    7031: 11,                             # held combat stance (single frame, waits on part 11)
    7041: 1,                              # held pose
    7051: 1, 7061: 1, 7071: 1, 7081: 1,   # held poses
    1592: 1, 8000: 0,
}
# Monster extras: the 1500 band here is a set of whole-body idle variants, not parts.
MONSTER = {
    1011: 1001, 1017: 1007,               # wait pair (MONSTER_ROWS 1011/1001 = wait)
    1507: 1501,                           # variant of 1501
    1511: 1, 1517: 7, 1521: 1, 1527: 7,
    1531: 1, 1537: 7, 1541: 1, 1547: 7,
    1551: 1, 1557: 7, 1561: 1, 1567: 7,
    1571: 1, 1577: 7, 1581: 1, 1587: 7,
    1591: 1501, 1597: 7, 1601: 1501, 1607: 7,   # 2190's two are 0x100 attachments -> blank 1501
    1592: 1, 8000: 0,
}

NEW = {
    'class': [1020, 1040, 1060, 1080, 1120, 1150, 1160, 2010, 2040, 2050, 2080, 2100, 2140, 2150, 2170, 2180, 2190],
    'unique': [180, 190, 210, 230, 300, 340, 350, 360, 40, 490, 500, 60],
}
# D4_Unique_240 (Toro) and D4_Unique_250 (Kuro) are NOT converted: D4's own file for each holds seven
# motions only (0,1,3,7,11,17,21), so 58 of the donor's 65 ids have no D4 source at all.  Converting
# would replace a working donor-track walk/attack with one held pose; they keep their TEST14 pack.
NO_SOURCE = {'unique': [240, 250]}
# ANIMALL's 32 packs: only the wheel-stub repair is applied.
FIX = {
    'class': [1010, 1030, 1050, 1070, 1090, 1100, 1110, 1130, 1140, 1170, 1180, 1190, 1200, 1210, 1220, 1230,
              1240, 1250, 2060, 2070, 2090, 2120, 2130, 2160, 2200],
    'unique': [10, 170, 20, 30, 310, 320, 50, 80],
}
BOUNDS = (-240, -360, 240, 120)


def pack_name(kind, sid):
    return f'D4_Class_{sid}' if kind == 'class' else f'D4_Unique_{sid}'


def pack_meta(src: Path, kind: str, sid: int, d4: d4source.D4Data):
    if kind == 'unique':
        meta = json.loads((src / 'patches/characters/unique.json').read_text())
        return meta['physical'], meta['kind']
    # SOURCEPREP4-D4: the class's sprite family and kind are the kit's recorded allocation (the values the importer
    # itself hands the class builder), not the October build-command file under Research/.
    from d5lib.importers import _d4_source
    from d5lib.importers.d4 import SPRITE_FAMILY_OVERRIDE      # D4GAP1: a family moved off vanilla ground
    row = next(f for f in _d4_source.allocation()['families'] if int(f['source_family']) == int(sid))
    return int(SPRITE_FAMILY_OVERRIDE.get(sid, row['sprite_family'])), row['kind']


def shapes(block, ids):
    out = {}
    for aid in ids:
        a = next((x for x in block.animations if x.id == aid), None)
        if a is None:
            continue
        info = anm.animation_info(block, a)
        nested, drawings, nkeys = [], 0, 0
        for ni, _, _ in block.walk(a.root):
            for k in block.node_keys(block.nodes[ni]):
                nkeys += 1
                if k.flags & 0xFF00 == anm.NESTED and 0 <= k.param < len(block.params):
                    nested.append((k.time, block.params[k.param]))
                elif k.cell and 0 < k.cell < len(block.cells):
                    cell = block.cells[k.cell]
                    if cell.w or cell.h:
                        drawings += 1
        out[aid] = dict(length=info.get('length'), loop=info.get('loop'), nkeys=nkeys,
                        drawings=drawings, nested=nested)
    return out


def wheel_stub(block, aid):
    """True for the donor's one-key 0x100 stand-in: <=2 keys, no picture, and a 0x100 key naming the
    character's own idle (6001 front / 6007 back).  PT1029 W2's Battle Suit shape."""
    sh = shapes(block, [aid]).get(aid)
    if not sh or sh['drawings'] or sh['nkeys'] > 2:
        return False
    return any(t in (6001, 6007) for _, t in sh['nested'])


def reroot_wheel(block, log):
    """Re-root a stub 1001/1007 on a deep copy of the class's own 6001/6007 animation."""
    changed = []
    for aid, idle in ((1001, 6001), (1007, 6007)):
        if not wheel_stub(block, aid):
            continue
        src = next((a for a in block.animations if a.id == idle), None)
        if src is None:
            log.append(dict(action='reroot-skipped', animation=aid, reason=f'{idle} absent'))
            continue
        target = next(a for a in block.animations if a.id == aid)
        target.root = src.root
        changed.append(dict(animation=aid, rerooted_on=idle, keys=shapes(block, [idle])[idle]['nkeys'],
                            drawings=shapes(block, [idle])[idle]['drawings']))
    return changed


def resolve(aid, merged_ids, kind, attached):
    """The D4 source animation a donor-only id takes.  Returns (target, rule)."""
    if aid in attached:
        for cand in (1501, 1511, 1551):
            if cand in merged_ids:
                return cand, 'blank-attachment'
        blanks = [i for i in sorted(merged_ids) if 1500 <= i < 2000]
        if blanks:
            return blanks[0], 'blank-attachment'
    table = HUMAN if kind == 'humanoid' else MONSTER
    if aid in table and table[aid] in merged_ids:
        return table[aid], 'documented'
    cands = []
    if 1000 <= aid < 1300:
        cands = [1001, 1007, 1, 7, 11]
    elif 1500 <= aid < 2000:
        cands = [1, 7, 11, 1501]
    elif 2000 <= aid < 5000:
        cands = [2001, 2007, 1, 7, 11]
    elif 7000 <= aid < 8000:
        cands = [1, 7, 11]
    cands += [1, 6001, 7, 2, 4, 8, 3, 11, 17, 0]
    for c in cands:
        if c in merged_ids:
            return c, 'held-pose' if aid not in table else 'documented-fallback'
    return None, 'none'


def alias_root(block, target, rule):
    """(root, rule) for a donor-only id aliased to `target`.

    ANIMALL's rule (Death 2120, where D4 authors and draws 1501): a 'blank-attachment' stand-in that
    draws is not blank, so the donor-only attachment gets an empty animation of its own (one keyless
    node) instead of painting the source part a second time (D4-FIX2)."""
    root = next(a for a in block.animations if a.id == target).root
    if rule == 'blank-attachment' and shapes(block, [target])[target]['drawings']:
        block.nodes.append(anm.Node(id=0, flags=0, unk2=0, unk3=0, mesh=0, unk5=0,
                                    first_key=-1, num_keys=0, child=-1, next=-1))
        return len(block.nodes) - 1, 'empty-attachment'
    return root, rule


def render(a, aid, t):
    # the stub cache lives on the AnmFile object itself (INTEG15: it used to be a module dict keyed by
    # id(anm), which leaked a freed file's answer into a later comparison and made pixel checks flaky)
    return np.asarray(anm.render_items(a, anm.evaluate(a, ('id', aid), t, nested=True), 0, bounds=BOUNDS)[0])


def convert_new(name, kind, sid, base, out_dir, d4, receipts, reroot=True, pad_palettes=None, mesh_nodes=False):
    src = base / name
    n, pk = pack_meta(src, kind, sid, d4)
    path = Path('files/Anime/ANM_HI_JP.dat')
    old = anm.load(src / path / f'anm{n:05}.lzs')
    # D4MESH1: mesh_nodes=True carries D4's mesh flag (node +4) into D5's node mesh word (D4-ANM-08)
    body = d4.anm(d4.chars[sid]['sprite'], mesh_nodes=mesh_nodes)
    merged = human_merge(body, d4.anm(1, mesh_nodes=mesh_nodes), bank_id=n) if pk == 'humanoid' else build_monster(body, bank_id=n)
    block = merged.blocks[0]
    have = {a.id for a in block.animations}
    attached = ownanim.donor_attachments(old.blocks[0])
    missing = sorted({a.id for a in old.blocks[0].animations} - have)
    log = []
    aliases = {}
    for aid in missing:
        target, rule = resolve(aid, have, pk, attached)
        if target is None:
            raise ValueError(f'{name}: no D4 source for donor motion {aid}')
        root, rule = alias_root(block, target, rule)
        block.animations.append(anm.Animation(aid, root))
        aliases[aid] = dict(source=target, rule=rule)
        log.append(dict(action='alias', animation=aid, source=target, rule=rule))
    block.animations.sort(key=lambda a: a.id)

    # pixel proof of every source-authored motion, against the D4 source
    target_file = anm.parse(merged.to_bytes())
    tb = target_file.blocks[0]
    source = body
    if pk == 'humanoid':
        from tools.animall2_tracks import blank_off_page, disabled_view
        source = anm.bind_motion_set(d4.anm(1, mesh_nodes=mesh_nodes), 0, body)
        source.blocks = body.blocks + source.blocks
        source = disabled_view(source)
        # D4CELL1: the merge zeroes the shared cells this body has no page for (or that run off a short
        # page: 360/450's 128-high page 9 cropped into two cape strips in motion 14); prove the rest
        blank_off_page(source.blocks[-1].cells, source.textures)
        target_file = disabled_view(target_file)
        tb = target_file.blocks[0]
    checks = 0
    for aid in sorted({a.id for a in block.animations} - set(aliases)):
        ta = next(x for x in tb.animations if x.id == aid)
        info = anm.animation_info(tb, ta)
        end = int((info['loop'][1] if info['loop'] else info['length']) or 1)
        for tick in sorted({0, max(0, min(end // 2, 90)), max(0, min(end - 1, 179))}):
            if not np.array_equal(render(source, aid, tick), render(target_file, aid, tick)):
                raise ValueError(f'{name}: pixel mismatch motion {aid} tick {tick}')
            checks += 1

    rebuilt = anm.parse(merged.to_bytes())
    # D4IDLE1: D4's own stub 1001/1007 already names the body idle 6001/6007 and carries a placement
    # (transform -3,-9); reroot=False keeps it as D4 authored it (the bank fix then only gives it the
    # game's render-root layout).  The default keeps the ANIMALL2 behaviour.
    wheel = reroot_wheel(rebuilt.blocks[0], log) if reroot else []
    if pad_palettes:
        # D4IDLE1: a donor-track pack keeps its palette HEADER count (bank shape): copies of D4's own palette 0
        want = len(old.blocks[0].palette_infos) if pad_palettes is True else int(pad_palettes)
        while len(rebuilt.blocks[0].palette_infos) < want:
            anm.add_palette(rebuilt, copy_from=0, block_index=0)
    dst = out_dir / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for off in (0, 1):
        (dst / path / f'anm{n + off:05}.lzs').write_bytes(ownanim.with_id(rebuilt, n + off).to_bytes())
        assert anm.load(dst / path / f'anm{n + off:05}.lzs').blocks[0].id == n + off
    diffs = sorted(str(p.relative_to(src)) for p in src.rglob('*') if p.is_file()
                   and p.read_bytes() != (dst / p.relative_to(src)).read_bytes())
    expect = sorted([str(path / f'anm{n:05}.lzs'), str(path / f'anm{n + 1:05}.lzs')])
    if diffs != expect:
        raise AssertionError(f'{name}: diffs {diffs}')
    receipts[name] = dict(kind=pk, bank=n, source_anm=f'anm{d4.chars[sid]["sprite"]:05d}',
                          source_motions=len(block.animations) - len(aliases), aliases=aliases,
                          pixel_checks=checks, wheel=wheel, changed=diffs, log=log)
    return receipts[name]


def convert_fix(name, kind, sid, base, out_dir, d4, receipts):
    src = base / name
    n, pk = pack_meta(src, kind, sid, d4)
    path = Path('files/Anime/ANM_HI_JP.dat')
    bank = anm.load(src / path / f'anm{n:05}.lzs')
    log = []
    wheel = reroot_wheel(bank.blocks[0], log)
    dst = out_dir / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    if wheel:
        for off in (0, 1):
            (dst / path / f'anm{n + off:05}.lzs').write_bytes(ownanim.with_id(bank, n + off).to_bytes())
        diffs = sorted(str(p.relative_to(src)) for p in src.rglob('*') if p.is_file()
                       and p.read_bytes() != (dst / p.relative_to(src)).read_bytes())
    else:
        diffs = []
    receipts[name] = dict(kind=pk, bank=n, wheel=wheel, changed=diffs, log=log)
    return receipts[name]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=str(R / 'Builds/PT1029-20261029/mods'))
    ap.add_argument('--fallback', default=str(R / 'Builds/LIVE5_TEST14-20261029/mods'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--jobs', default='new,fix')
    ap.add_argument('--only', default='', help='comma-separated pack names, for a trial run')
    args = ap.parse_args()
    base, fallback, out = Path(args.base), Path(args.fallback), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    d4 = d4source.D4Data(D4ROOT)
    receipts = {}
    plan = []
    if 'new' in args.jobs:
        plan += [('new', k, s) for k, v in NEW.items() for s in v]
    if 'fix' in args.jobs:
        plan += [('fix', k, s) for k, v in FIX.items() for s in v]
    for job, kind, sid in plan:
        name = pack_name(kind, sid)
        if args.only and name not in args.only.split(','):
            continue
        root = base if (base / name).exists() else fallback
        try:
            r = (convert_new if job == 'new' else convert_fix)(name, kind, sid, root, out, d4, receipts)
            print(job, name, r.get('bank'), 'aliases', len(r.get('aliases', {})),
                  'wheel', len(r.get('wheel', [])), 'changed', len(r.get('changed', [])), flush=True)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the batch
            receipts[name] = dict(job=job, error=f'{type(exc).__name__}: {exc}')
            print('FAIL', job, name, receipts[name]['error'], flush=True)
    (out.parent / 'receipts.json').write_text(json.dumps(receipts, indent=1, default=str))
    bad = [k for k, v in receipts.items() if 'error' in v]
    print(f'{len(receipts) - len(bad)}/{len(receipts)} packs built; failures: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
