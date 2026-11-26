"""WHEELBISECT1: four SLIM29-derived variants that bisect the D1C Hire-wheel freeze.

Only the two class folders differ from TEST28 in SLIM29, so every variant moves nothing but the
class banks; the 17 unique folders stay TEST28.

  BS-S       Strider 11390 = SLIM29, EDF 11400 = TEST28
  BS-E       EDF 11400 = SLIM29, Strider 11390 = TEST28
  BS-NOSTUB  both = SLIM29, but the four stand/pose stubs 1011/1017/5001/5021 show TEST28's
             held picture instead of the worked 21/27 (a preserved copy of TEST28's 21/27 is
             appended and the stubs' nested records are re-pointed at it)
  BS-DARK    both = SLIM29 data present, but the worked 21/27 are moved to unused ids and 21/27
             are TEST28's again -- no motion can reach the worked art

usage: python tools/wheelbisect1_build.py [out dir]
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
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
LIVE_PROFILE = ROOT / 'Local/Installed D5ModKit/profiles/LIVE5_TEST28'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Builds/WHEELBISECT1-20261102'
REL = base.REL
NESTED = 0x100
CLASS_MODS = ('D1C_Class_11390', 'D1C_Class_11400')
HURT = (21, 27)
STUBS = (1011, 1017, 5001, 5021)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def bank_path(mods, mod, bank):
    return mods / mod / REL / bank


def load(mods, mod, bank):
    return anm.load(bank_path(mods, mod, bank).read_bytes())


def tree_keys(b, root):
    """{(node_index, key_index)} reachable from an animation root."""
    out, seen, todo = set(), set(), [root]
    while todo:
        ni = todo.pop()
        if ni in seen or not 0 <= ni < len(b.nodes):
            continue
        seen.add(ni)
        n = b.nodes[ni]
        todo.extend((n.child, n.next))
        if n.first_key < 0 or n.num_keys <= 0:
            continue
        for ki in range(n.first_key, n.first_key + n.num_keys):
            out.add((ni, ki))
    return out


def animation(b, aid):
    found = [a for a in b.animations if a.id == aid]
    assert len(found) == 1, aid
    return found[0]


def assert_base_untouched(t28, slim, aid):
    """SLIM29 must keep TEST28's records for the animation it re-roots."""
    a, s = animation(t28, aid), animation(slim, aid)
    assert a.root != s.root, aid
    for ni, ki in tree_keys(t28, a.root):
        assert t28.nodes[ni] == slim.nodes[ni], (aid, 'node', ni)
        assert t28.keys[ki] == slim.keys[ki], (aid, 'key', ki)
        k = t28.keys[ki]
        assert t28.cells[k.cell] == slim.cells[k.cell]
        assert t28.transforms[k.xform] == slim.transforms[k.xform]
        assert t28.colors[k.color] == slim.colors[k.color]


def referenced_ids(b):
    """every animation id any nested (0x100) key names, plus every animation id in the table."""
    ids = {a.id for a in b.animations}
    refs = set()
    for k in b.keys:
        if k.flags & NESTED and 0 <= k.param < len(b.params):
            refs.add(abs(b.params[k.param]))
    return ids, refs


def pick_unused(b, wanted):
    ids, refs = referenced_ids(b)
    out = []
    for start in wanted:
        i = start
        while i in ids or i in refs or i > 0xffff:
            i += 1
        out.append(i)
    assert len(set(out)) == len(out)
    return out


def patched(slim_file):
    assert len(slim_file.blocks) == 1
    return anm.AnmFile([slim_file.block], slim_file.textures, slim_file.palettes,
                       slim_file.hdr_unk, slim_file.trailing)


def build_dark(t28, slim):
    """worked 21/27 -> unused ids; 21/27 = TEST28."""
    b = slim.block
    for aid in HURT:
        assert_base_untouched(t28.block, b, aid)
    u21, u27 = pick_unused(b, (64001, 64011))
    moved = []
    for aid, new_id in ((21, u21), (27, u27)):
        s, t = animation(b, aid), animation(t28.block, aid)
        moved.append({'from': aid, 'to': new_id, 'slim_root': s.root, 'test28_root': t.root})
        b.animations.append(anm.Animation(id=new_id, root=s.root))
        s.root = t.root
    # prove the new ids are in the table and referenced by nothing
    ids, refs = referenced_ids(b)
    for u in (u21, u27):
        assert u in ids and u not in refs, u
    return patched(slim), {'moved': moved, 'held_ids': [u21, u27]}


def nested_targets(b, root):
    """[(node, key, target)] for every nested (0x100) key of one animation tree."""
    out = []
    for ni, ki in sorted(tree_keys(b, root)):
        k = b.keys[ki]
        if k.flags & NESTED and 0 <= k.param < len(b.params):
            out.append((ni, ki, abs(b.params[k.param])))
    return out


def copy_tree(b, t, root, idmap):
    """append a private copy of TEST28's node/key subtree `root` to bank b; remap nested targets
    that are in idmap; return the new root node index. Cells/transforms/colours are shared."""
    nodes = sorted(tree_keys(t, root))
    order, seen, todo = [], set(), [root]
    while todo:                       # parent-before-child is not required, only a stable set
        ni = todo.pop()
        if ni in seen or not 0 <= ni < len(t.nodes):
            continue
        seen.add(ni)
        order.append(ni)
        n = t.nodes[ni]
        todo.extend((n.child, n.next))
    idx = {ni: len(b.nodes) + i for i, ni in enumerate(order)}
    for ni in order:
        n = t.nodes[ni]
        nodes_out = dataclasses.replace(n)
        nodes_out.child = idx.get(n.child, -1)
        nodes_out.next = idx.get(n.next, -1)
        keys = []
        if n.first_key >= 0 and n.num_keys > 0:
            for ki in range(n.first_key, n.first_key + n.num_keys):
                k = dataclasses.replace(t.keys[ki])
                if k.flags & NESTED and 0 <= k.param < len(t.params):
                    rec = t.params[k.param:k.param + 3]
                    target = abs(rec[0]) if rec else None
                    if len(rec) == 3 and target in idmap:
                        rec = [idmap[target]] + rec[1:]
                    if len(rec) == 3:
                        assert len(b.params) % 3 == 0
                        b.params.extend(rec)
                        k.param = len(b.params) - 3
                keys.append(k)
            nodes_out.first_key = len(b.keys)
            nodes_out.num_keys = len(keys)
            b.keys.extend(keys)
        b.nodes.append(nodes_out)
    return idx[root]


def build_nostub(t28, slim):
    """the four stubs show TEST28's held picture.

    TEST28's 21 does not stand alone: its tree spawns 1, which spawns 21 again (closure
    {1, 7, 11, 21}, plus 27 for 27). So the whole closure is copied from TEST28 under fresh ids,
    every internal edge of the copy is re-pointed at the copy, and the four stubs are re-pointed
    at the 21/27 copies. The result has no path from a stub to SLIM29's worked 21/27.
    """
    b = slim.block
    for aid in HURT:
        assert_base_untouched(t28.block, b, aid)
    t = t28.block
    closure, todo = set(), list(HURT)
    while todo:
        a = todo.pop()
        if a in closure:
            continue
        closure.add(a)
        todo.extend(x[2] for x in nested_targets(t, animation(t, a).root))
    ordered = sorted(closure)
    fresh = pick_unused(b, [64031 + 10 * i for i in range(len(ordered))])
    idmap = dict(zip(ordered, fresh))
    # copy each animation's node/key records (the node table is shared, so a copy that only
    # appended an Animation record would re-point the live animation's keys)
    for aid in ordered:
        root = copy_tree(b, t, animation(t, aid).root, idmap)
        b.animations.append(anm.Animation(id=idmap[aid], root=root))
    u21, u27 = idmap[21], idmap[27]
    repointed = []
    for stub in STUBS:
        for ni, ki in sorted(tree_keys(b, animation(b, stub).root)):
            k = b.keys[ki]
            if not k.flags & NESTED or not 0 <= k.param < len(b.params):
                continue
            target = abs(b.params[k.param])
            if target not in HURT:
                continue
            rec = b.params[k.param:k.param + 3]
            assert len(rec) == 3 and rec[0] == target, (stub, ni, ki, rec)
            assert len(b.params) % 3 == 0, len(b.params)
            new_rec = [u21 if target == 21 else u27] + rec[1:]
            b.params.extend(new_rec)
            b.keys[ki] = dataclasses.replace(k, param=len(b.params) - 3)
            repointed.append({'stub': stub, 'node': ni, 'key': ki, 'from': target,
                              'to': new_rec[0], 'record': new_rec})
    # the copies are in the table; no stub reaches SLIM29's worked 21/27, not even through the
    # copies' own internal edges
    ids, refs = referenced_ids(b)
    for u in idmap.values():
        assert u in ids and u in refs, u
    for stub in STUBS:
        seen, todo = set(), [animation(b, stub).root]
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
                if not k.flags & NESTED or not 0 <= k.param < len(b.params):
                    continue
                target = abs(b.params[k.param])
                assert target not in HURT, (stub, ni, ki, target)
                if target in ids:
                    todo.append(animation(b, target).root)
    return patched(slim), {'idmap': {str(k): v for k, v in idmap.items()},
                           'repointed': repointed}


def copy_bundle(dest, class_source):
    """19 folders: TEST28 for the 17 unique packs, the variant's source for the two class packs."""
    if dest.exists():
        shutil.rmtree(dest)
    (dest / 'mods').mkdir(parents=True)
    for mod in base.manifest()['banks']:
        src = class_source[mod] if mod in CLASS_MODS else base.base_dir(mod) / mod
        shutil.copytree(src, dest / 'mods' / mod)
    return dest / 'mods'


def main():
    n = base.require_base_set()
    print(f'TEST28 base asserted: {n} pinned banks', flush=True)
    order = json.loads((LIVE_PROFILE / 'load_order.json').read_text())
    assert len(order) == 188, len(order)
    profile_doc = json.loads((LIVE_PROFILE / 'profile.json').read_text())

    t28_root = {m: base.base_dir(m) for m in base.manifest()['banks']}

    variants = {
        'bs_s': {'name': 'LIVE5_BS_S', 'override': ['D1C_Class_11400']},
        'bs_e': {'name': 'LIVE5_BS_E', 'override': ['D1C_Class_11390']},
        'bs_nostub': {'name': 'LIVE5_BS_NOSTUB', 'patch': 'nostub'},
        'bs_dark': {'name': 'LIVE5_BS_DARK', 'patch': 'dark'},
    }
    # class_source: which folder each class pack is copied from; the rest is TEST28
    report = {}
    for key, spec in variants.items():
        dest = OUT / key
        class_source = {m: SLIM / m for m in CLASS_MODS}
        for m in spec.get('override', []):
            class_source[m] = t28_root[m] / m
        mods = copy_bundle(dest, class_source)
        row = {'profile': spec['name'],
               'class_source': {m: ('TEST28' if m in spec.get('override', []) else 'SLIM29')
                                for m in CLASS_MODS},
               'patched': {}}
        if spec.get('patch'):
            for mod in CLASS_MODS:
                for bank in base.manifest()['banks'][mod]:
                    slim = load(SLIM, mod, bank)
                    ref = anm.load(bank_path(t28_root[mod], mod, bank).read_bytes())
                    slim_raw = len(slim.to_bytes())
                    test28_raw = len(ref.to_bytes())
                    if spec['patch'] == 'dark':
                        patched_file, info = build_dark(ref, slim)
                    else:
                        patched_file, info = build_nostub(ref, slim)
                    raw = patched_file.to_bytes()
                    dst = mods / mod / REL / bank
                    dst.write_bytes(anm.lzs_compress(raw))
                    assert anm.load(dst.read_bytes()).to_bytes() == raw, (mod, bank, 'roundtrip')
                    row['patched'][f'{mod}/{bank}'] = {
                        'slim_raw': slim_raw, 'raw': len(raw),
                        'test28_raw': test28_raw, **info}
                    print(f"  {key} {mod}/{bank}: raw {len(raw):,} "
                          f"(slim {len(slim.to_bytes()):,})", flush=True)
        # profile: TEST28's 188-entry order
        pdir = dest / 'profile' / spec['name']
        pdir.mkdir(parents=True)
        (pdir / 'load_order.json').write_text(json.dumps(order, indent=1) + '\n')
        doc = dict(profile_doc)
        doc['name'] = spec['name']
        (pdir / 'profile.json').write_text(json.dumps(doc, indent=1) + '\n')
        # folder/file delta vs TEST28
        changed, identical = [], 0
        for mod in base.manifest()['banks']:
            src = t28_root[mod] / mod
            dst = mods / mod
            rels = {p.relative_to(src) for p in src.rglob('*') if p.is_file()}
            assert rels == {p.relative_to(dst) for p in dst.rglob('*') if p.is_file()}, mod
            for rel in sorted(rels):
                if (src / rel).read_bytes() == (dst / rel).read_bytes():
                    identical += 1
                else:
                    changed.append(f'{mod}/{rel.relative_to(REL)}')
        row.update({'files': identical + len(changed), 'identical': identical,
                    'changed_banks': changed, 'load_order_len': len(order)})
        report[key] = row
        print(f"{key}: {len(changed)} banks changed, {identical} files identical", flush=True)

    (OUT / 'evidence').mkdir(parents=True, exist_ok=True)
    (OUT / 'evidence' / 'build.json').write_text(json.dumps(report, indent=1) + '\n')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
