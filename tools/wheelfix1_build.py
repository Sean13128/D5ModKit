"""WHEELFIX1: BS-WHEELFIX -- SLIM29's hurt 21/27 kept for battle, the D1C Hire wheel fed TEST28's
held picture instead.

Base: SLIM29 class banks (Builds/WHEELMEM1-20261102/slim29/mods), the 17 unique packs from TEST28.
Change, per class bank only:

  1. copy TEST28's 21/27 closure to unused ids -- the same construction BS-NOSTUB used
     (WHEELBISECT1 `copy_tree`): the closure {1, 7, 11, 21, 27} is copied from TEST28 with private
     node/key/param records, every internal edge of the copy re-pointed inside the copy, ids
     64031/64041/64051/64061/64071 (proven absent from the table and from every nested record);
  2. re-point **only** the nested (0x100) keys that the wheel's three motions reach and that name
     21/27, at those copies. TEST28's edge set into 21/27 from the wheel closure
     {1, 7, 11, 21, 101, 1001, 6001} is 11 keys per bank: 1 x5, 101 x5, 6001 x1 (6001 -> 21 on
     Strider/anm01540*, 6001 -> 27 on EDF/anm01530*). 6007 is **not** wheel-reachable (measured)
     and is left alone;
  3. ids 21/27 themselves stay SLIM29's: their animation rows are asserted untouched and the
     worked art stays reachable whenever the game selects motion 21/27 directly (battle hurt);
  4. the four stand/pose stubs 1011/1017/5001/5021 stay SLIM29's (unlike BS-NOSTUB).

usage: python tools/wheelfix1_build.py [out dir]
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
import wheelbisect1_build as wb  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
LIVE_PROFILE = ROOT / 'Local/Installed D5ModKit/profiles/LIVE5_TEST28'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Builds/WHEELFIX1-20261102'
HURT = (21, 27)
WHEEL = (1, 101, 1001)
COPY_START = 64031
PROFILE = 'LIVE5_BS_WHEELFIX'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def edges(b):
    """{animation id: [(node, key, target id)]} for every nested key that names another animation."""
    ids = {a.id for a in b.animations}
    out = {}
    for a in b.animations:
        seen, todo, rows = set(), [a.root], []
        while todo:
            ni = todo.pop()
            if ni in seen or not 0 <= ni < len(b.nodes):
                continue
            seen.add(ni)
            n = b.nodes[ni]
            todo.extend((n.child, n.next))
            if n.first_key < 0:
                continue
            for ki in range(n.first_key, n.first_key + n.num_keys):
                k = b.keys[ki]
                if not k.flags & wb.NESTED or not 0 <= k.param < len(b.params):
                    continue
                t = abs(b.params[k.param])
                if t in ids and t != a.id:
                    rows.append((ni, ki, t))
        out[a.id] = rows
    return out


def closure(e, roots):
    seen, todo = set(), list(roots)
    while todo:
        a = todo.pop()
        if a in seen:
            continue
        seen.add(a)
        todo.extend(t for _, _, t in e.get(a, []))
    return seen


def build_wheelfix(t28, slim):
    b = slim.block
    for aid in HURT:
        wb.assert_base_untouched(t28.block, b, aid)
    t = t28.block

    # 1. TEST28's closure of the hurt ids the wheel actually reaches (both of them on EDF, only 21
    #    on Strider: 6001 -> 27 exists in anm01530/01531 only), copied under fresh ids
    wheel_reach = closure(edges(b), WHEEL)
    targets = sorted(wheel_reach & set(HURT))
    assert targets, 'the wheel reaches neither 21 nor 27'
    closure_ids, todo = set(), list(targets)
    while todo:
        a = todo.pop()
        if a in closure_ids:
            continue
        closure_ids.add(a)
        todo.extend(x[2] for x in wb.nested_targets(t, wb.animation(t, a).root))
    ordered = sorted(closure_ids)
    ids_before, refs_before = wb.referenced_ids(b)
    fresh = wb.pick_unused(b, [COPY_START + 10 * i for i in range(len(ordered))])
    for u in fresh:
        assert u not in ids_before and u not in refs_before, u
    idmap = dict(zip(ordered, fresh))
    for aid in ordered:
        root = wb.copy_tree(b, t, wb.animation(t, aid).root, idmap)
        b.animations.append(anm.Animation(id=idmap[aid], root=root))

    # 2. re-point only the wheel-reachable spawn edges into 21/27
    e_after_copy = edges(b)
    owners = sorted(closure(e_after_copy, WHEEL) - set(idmap.values()))
    repointed = []
    for owner in owners:
        for ni, ki, target in e_after_copy.get(owner, []):
            if target not in HURT:
                continue
            k = b.keys[ki]
            rec = b.params[k.param:k.param + 3]
            assert len(rec) == 3 and abs(rec[0]) == target, (owner, ni, ki, rec)
            assert len(b.params) % 3 == 0, len(b.params)
            b.params.extend([idmap[target]] + rec[1:])
            b.keys[ki] = dataclasses.replace(k, param=len(b.params) - 3)
            repointed.append({'owner': owner, 'node': ni, 'key': ki, 'from': target,
                              'to': idmap[target], 'record': [idmap[target]] + rec[1:]})

    # 3. ids 21/27 are still SLIM29's own rows
    roots = {a.id: a.root for a in b.animations}
    assert roots[21] == wb.animation(slim.block, 21).root
    assert roots[27] == wb.animation(slim.block, 27).root

    # 4. the copies are in the table and referenced only from inside the copy/our re-points
    ids, refs = wb.referenced_ids(b)
    for u in idmap.values():
        assert u in ids and u in refs, u
    return wb.patched(slim), {'idmap': {str(k): v for k, v in idmap.items()},
                              'owners': owners, 'repointed': repointed}


def main():
    n = base.require_base_set()
    print(f'TEST28 base asserted: {n} pinned banks', flush=True)
    order = json.loads((LIVE_PROFILE / 'load_order.json').read_text())
    assert len(order) == 188, len(order)
    profile_doc = json.loads((LIVE_PROFILE / 'profile.json').read_text())
    t28_root = {m: base.base_dir(m) for m in base.manifest()['banks']}

    dest = OUT
    class_source = {m: SLIM / m for m in wb.CLASS_MODS}
    mods = wb.copy_bundle(dest, class_source)
    row = {'profile': PROFILE, 'patched': {}}
    for mod in wb.CLASS_MODS:
        for bank in base.manifest()['banks'][mod]:
            slim = anm.load(wb.bank_path(SLIM, mod, bank).read_bytes())
            ref = anm.load(wb.bank_path(t28_root[mod], mod, bank).read_bytes())
            before = {'raw': len(slim.to_bytes()), 'animations': len(slim.block.animations),
                      'nodes': len(slim.block.nodes), 'keys': len(slim.block.keys),
                      'params': len(slim.block.params)}
            patched_file, info = build_wheelfix(ref, slim)
            raw = patched_file.to_bytes()
            d = mods / mod / base.REL / bank
            d.write_bytes(anm.lzs_compress(raw))
            assert anm.load(d.read_bytes()).to_bytes() == raw, (mod, bank, 'roundtrip')
            after = {'raw': len(raw), 'animations': len(patched_file.block.animations),
                     'nodes': len(patched_file.block.nodes), 'keys': len(patched_file.block.keys),
                     'params': len(patched_file.block.params)}
            row['patched'][f'{mod}/{bank}'] = {
                'slim_before': before, 'after': after,
                'test28_raw': len(ref.to_bytes()),
                **info}
            print(f"  BS-WHEELFIX {mod}/{bank}: raw {before['raw']:,} -> {after['raw']:,} "
                  f"(+{after['raw'] - before['raw']:,}; nodes {before['nodes']} -> {after['nodes']}, "
                  f"keys {before['keys']} -> {after['keys']}, params {before['params']} -> "
                  f"{after['params']}), {len(info['repointed'])} wheel edges re-pointed", flush=True)

    pdir = dest / 'profile' / PROFILE
    pdir.mkdir(parents=True)
    (pdir / 'load_order.json').write_text(json.dumps(order, indent=1) + '\n')
    doc = dict(profile_doc)
    doc['name'] = PROFILE
    (pdir / 'profile.json').write_text(json.dumps(doc, indent=1) + '\n')

    changed, identical = [], 0
    for mod in base.manifest()['banks']:
        src, dst = t28_root[mod] / mod, mods / mod
        rels = {p.relative_to(src) for p in src.rglob('*') if p.is_file()}
        assert rels == {p.relative_to(dst) for p in dst.rglob('*') if p.is_file()}, mod
        for rel in sorted(rels):
            if (src / rel).read_bytes() == (dst / rel).read_bytes():
                identical += 1
            else:
                changed.append(f'{mod}/{rel.relative_to(base.REL)}')
    row.update({'files': identical + len(changed), 'identical': identical,
                'changed_banks': changed, 'load_order_len': len(order)})
    (OUT / 'evidence').mkdir(parents=True, exist_ok=True)
    (OUT / 'evidence' / 'build.json').write_text(json.dumps(row, indent=1) + '\n')
    print(f'{len(changed)} banks changed vs TEST28 ({sorted(changed)}), '
          f'{identical} files identical, profile {PROFILE} ({len(order)} entries)', flush=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
