"""WHEELFIX1 verify: the three structural claims about BS-WHEELFIX, per class bank.

  * ids 21/27 are untouched: their animation rows and every node/key/cell/transform/colour record of
    their trees are equal to SLIM29's (so battle hurt is exactly SLIM29's);
  * the nested reachability walk from the wheel's three motions (1, 101, 1001) never reaches 21/27
    and never reaches a node that SLIM29 added (node index >= TEST28's node count);
  * the copies 64031.. are self-contained: every nested edge inside the copy points at another copy
    (never at SLIM29's live 21/27), every copy is referenced, and none of the ids existed or was
    referenced before the build.

Writes Builds/WHEELFIX1-20261102/evidence/verify.json.
"""
from __future__ import annotations

import hashlib
import json
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
OUT = ROOT / 'Builds/WHEELFIX1-20261102'
HURT = (21, 27)
WHEEL = (1, 101, 1001)
NESTED = wb.NESTED


def tree_keys(b, root):
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


def edges(b):
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
                if k.flags & NESTED and 0 <= k.param < len(b.params):
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


def main():
    rows = {}
    ok = True
    build_doc = json.loads((OUT / 'evidence/build.json').read_text())
    for mod in wb.CLASS_MODS:
        for bank in base.manifest()['banks'][mod]:
            built = anm.load((OUT / 'mods' / mod / base.REL / bank).read_bytes())
            slim = anm.load((SLIM / mod / base.REL / bank).read_bytes())
            t28 = anm.load((base.base_dir(mod) / mod / base.REL / bank).read_bytes())
            b, s, t = built.block, slim.block, t28.block
            new_node_start = len(t.nodes)
            assert all(t.nodes[i] == s.nodes[i] for i in range(len(t.nodes))), \
                'SLIM29 does not keep TEST28 as a node prefix'

            # 1. ids 21/27 untouched: rows and every record of their trees equal SLIM29's
            for aid in HURT:
                a_s, a_b = wb.animation(s, aid), wb.animation(b, aid)
                assert a_b.root == a_s.root, (aid, 'root moved')
                for ni, ki in tree_keys(s, a_s.root):
                    assert s.nodes[ni] == b.nodes[ni], (aid, 'node', ni)
                    assert s.keys[ki] == b.keys[ki], (aid, 'key', ki)
                    k = s.keys[ki]
                    assert s.cells[k.cell] == b.cells[k.cell]
                n_keys = len(tree_keys(s, a_s.root))
                rows.setdefault(f'{mod}/{bank}', {})[f'hurt_{aid}_records_equal_slim29'] = n_keys

            # 2. the wheel's walk never reaches 21/27 nor a node SLIM29 added
            e = edges(b)
            reach = {str(m): sorted(closure(e, [m])) for m in WHEEL}
            reached_nodes, reached_ids = set(), set()
            for m in WHEEL:
                for aid in closure(e, [m]):
                    reached_ids.add(aid)
                    reached_nodes |= {ni for ni, _ in tree_keys(b, wb.animation(b, aid).root)}
            hits_hurt = sorted(reached_ids & set(HURT))
            # SLIM29 appended its worked tree after TEST28's nodes (asserted prefix above), so
            # SLIM29's new nodes are exactly [len(t.nodes), len(s.nodes)); the copies' nodes were
            # appended after those and are the copy's own.
            slim_new_range = range(new_node_start, len(s.nodes))
            hits_new = sorted(ni for ni in reached_nodes if ni in slim_new_range)
            rows[f'{mod}/{bank}'].update({
                'wheel_reach': reach,
                'wheel_reach_reaches_21_27': hits_hurt,
                'wheel_reach_nodes_at_or_after_slim29_first_new_node': hits_new,
                'slim29_new_node_start': new_node_start,
                'slim29_new_nodes': len(s.nodes) - new_node_start,
                'wheel_reach_copy_nodes': sorted(ni for ni in reached_nodes
                                                 if ni >= len(s.nodes)),
                'built_nodes': len(b.nodes),
            })
            ok &= not hits_hurt and not hits_new

            # 3. the copies are self-contained and were unused before the build
            copies = sorted(i for i in {a.id for a in b.animations}
                            - {a.id for a in s.animations})
            copy_edges = [(aid, ni, ki, tg) for aid in copies for (ni, ki, tg) in e.get(aid, [])]
            outside = [x for x in copy_edges if x[3] not in copies]
            referenced = {tg for v in e.values() for _, _, tg in v}
            unreferenced = [c for c in copies if c not in referenced]
            s_ids, s_refs = wb.referenced_ids(s)
            ids_before = [c for c in copies if c in s_ids or c in s_refs]
            rows[f'{mod}/{bank}'].update({
                'copies': copies,
                'copies_existed_in_slim29': ids_before,
                'copies_unreferenced': unreferenced,
                'copy_edges_outside_the_copy': outside,
                'copy_edge_count': len(copy_edges),
                'root_of_each_copy': {str(c): next(a.root for a in b.animations if a.id == c)
                                     for c in copies},
                'test28_root_of_each_copy': {
                    str(k): v for k, v in build_doc['patched'][
                        f'{mod}/{bank}']['idmap'].items()}})
            ok &= not outside and not unreferenced and not ids_before
            print(f'{mod}/{bank}: reach {reach}; 21/27 hit {hits_hurt}; new-node hit {hits_new}; '
                  f'copies {copies}; outside edges {outside}', flush=True)

    (OUT / 'evidence' / 'verify.json').write_text(json.dumps(rows, indent=1) + '\n')
    print('VERIFY', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
