"""WHEELBISECT1 step 1: which animations the D1C Hire page actually plays, and what each one
nests, in TEST28 vs SLIM29.

Reads the bank with d5lib.anm only (no game). Nested edges are keys with flag 0x100 whose
table-9 record names another animation id (abs, as the native selector does).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
TEST28 = ROOT / 'Builds/LIFTSLOT1-20261101/mods'
SLIM29 = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
REL = Path('files/Anime/ANM_HI_JP.dat')
NESTED = 0x100

PAGES = {
    'Strider front anm01540': ('D1C_Class_11390', 'anm01540.lzs'),
    'Strider back  anm01541': ('D1C_Class_11390', 'anm01541.lzs'),
    'EDF     front anm01530': ('D1C_Class_11400', 'anm01530.lzs'),
    'EDF     back  anm01531': ('D1C_Class_11400', 'anm01531.lzs'),
}
# FUN_140666920: ring slots request 0x65 (101) or 1 when +0x4f2 == 1;
# centre requests 0x3e9 (1001) or 1 when +0x2f92 == 1.
WHEEL_MOTIONS = [1, 101, 1001]


def nested_edges(block):
    ids = {a.id for a in block.animations}
    edges = {}
    for animation in block.animations:
        seen, todo = set(), [animation.root]
        targets = set()
        while todo:
            ni = todo.pop()
            if ni in seen or not 0 <= ni < len(block.nodes):
                continue
            seen.add(ni)
            node = block.nodes[ni]
            todo.extend((node.child, node.next))
            if node.first_key < 0 or node.num_keys < 0:
                continue
            for ki in range(node.first_key, min(node.first_key + node.num_keys, len(block.keys))):
                key = block.keys[ki]
                if not key.flags & NESTED:
                    continue
                p = key.param
                if not 0 <= p < len(block.params):
                    continue
                target = abs(block.params[p])
                if target in ids and target != animation.id:
                    targets.add(target)
        if targets:
            edges[animation.id] = sorted(targets)
    return edges


def closure(edges, roots):
    seen = set()
    todo = [r for r in roots]
    while todo:
        a = todo.pop()
        if a in seen:
            continue
        seen.add(a)
        todo.extend(edges.get(a, ()))
    return seen


def main():
    out = {}
    for name, (mod, bank) in PAGES.items():
        row = {}
        for label, root in (('TEST28', TEST28), ('SLIM29', SLIM29)):
            f = anm.load((root / mod / REL / bank).read_bytes())
            rec = {'bytes': (root / mod / REL / bank).stat().st_size,
                   'animations': len(f.block.animations),
                   'ids': sorted(a.id for a in f.block.animations)}
            edges = nested_edges(f.block)
            rec['edges_from_wheel_motions'] = {str(m): edges.get(m, []) for m in WHEEL_MOTIONS}
            reach = {}
            for m in WHEEL_MOTIONS:
                c = closure(edges, [m])
                reach[str(m)] = sorted(c)
            rec['reachable_from_wheel_motions'] = reach
            rec['ids_21_27_present'] = [i for i in (21, 27) if i in rec['ids']]
            rec['stubs_reachable'] = {str(s): sorted(m for m, c in reach.items() if s in c)
                                      for s in (1011, 1017, 5001, 5021)}
            rec['hurt_reachable'] = {str(s): sorted(m for m, c in reach.items() if s in c)
                                     for s in (21, 27)}
            # which animations nest 21/27 at all
            rec['nesters_of_21_27'] = {str(t): sorted(a for a, ts in edges.items() if t in ts)
                                       for t in (21, 27)}
            row[label] = rec
        out[name] = row
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
