"""WHEELFIX1 analysis: the wheel's motions, their nested edges into 21/27, and two censuses.

  1. per class bank, for TEST28 / SLIM29 / BS-WHEELFIX: the ids FUN_140666920 requests (1, 101,
     1001), the nested-spawn closure of each, and the exact (owner, node, key, target) list of
     every edge into 21/27 that the wheel can reach;
  2. TEST29FIX1's TEST29b alias census: which animation owns each of the 42 keys its alias re-point
     moved to 65003/65004, and whether any of them is a wheel edge (1/101/1001 -> 6001 -> 21/27);
  3. per unique bank (SLIM29): does the wheel chain reach 21/27 there too.

usage: python tools/wheelfix1_analyze.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
FIX = ROOT / 'Builds/WHEELFIX1-20261102/mods'
T29B = ROOT / 'Builds/TEST29FIX1-20261101/mods'
NESTED = 0x100
WHEEL = (1, 101, 1001)
HURT = (21, 27)
CLASS = ('D1C_Class_11390', 'D1C_Class_11400')


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
    out = {'wheel': {}, 'test29b_alias': {}, 'uniques': {}}
    for mod in CLASS:
        for bank in base.manifest()['banks'][mod]:
            key = f'{mod}/{bank}'
            out['wheel'][key] = {}
            for label, root in (('TEST28', base.base_dir(mod) / mod), ('SLIM29', SLIM / mod),
                                ('BS-WHEELFIX', FIX / mod)):
                b = anm.load((root / base.REL / bank).read_bytes()).block
                e = edges(b)
                reach = {m: sorted(closure(e, [m])) for m in WHEEL}
                into = [(aid, ni, ki, t) for aid in sorted(set().union(*map(set, reach.values())))
                        for (ni, ki, t) in e.get(aid, []) if t in HURT]
                out['wheel'][key][label] = {
                    'edges_from_wheel_motions': {str(m): sorted({t for _, _, t in e.get(m, [])})
                                                 for m in WHEEL},
                    'reachable': {str(m): reach[m] for m in WHEEL},
                    'edges_into_21_27_reachable_from_the_wheel': [
                        {'owner': a, 'node': ni, 'key': ki, 'target': t} for a, ni, ki, t in into],
                    'nesters_of_21': sorted(a for a, rows in e.items()
                                            if any(t == 21 for _, _, t in rows)),
                    'nesters_of_27': sorted(a for a, rows in e.items()
                                            if any(t == 27 for _, _, t in rows)),
                }
                print(f'{label} {key}: reach ' +
                      ', '.join(f'{m}->{reach[m]}' for m in WHEEL) +
                      f'; edges into 21/27: {len(into)}', flush=True)

    # TEST29b: which animation owns the 42 keys whose record names 65003/65004
    for mod in CLASS:
        for bank in base.manifest()['banks'][mod]:
            b = anm.load((T29B / mod / base.REL / bank).read_bytes()).block
            rows = []
            for a in b.animations:
                seen, todo = set(), [a.root]
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
                            if t in (65003, 65004):
                                rows.append({'animation': a.id, 'node': ni, 'key': ki,
                                             'target': t,
                                             'record': list(b.params[k.param:k.param + 3])})
            wheel_edges = out['wheel'][f'{mod}/{bank}']['SLIM29'][
                'edges_into_21_27_reachable_from_the_wheel']
            wheel_targets = {w['target'] for w in wheel_edges}
            out['test29b_alias'][f'{mod}/{bank}'] = {
                'keys': len(rows),
                'by_animation': dict(Counter(r['animation'] for r in rows)),
                'by_record': {str(k): v for k, v in
                              Counter(tuple(r['record']) for r in rows).items()},
                'an_alias_key_is_a_wheel_edge': sorted(
                    {r['animation'] for r in rows} & {w['owner'] for w in wheel_edges}),
                'alias_targets': sorted({r['target'] for r in rows}),
                'wheel_edge_targets': sorted(wheel_targets),
                'wheel_edges_repointed_by_the_alias_pass': [
                    w for w in wheel_edges if w['target'] in {r['target'] for r in rows}],
            }
            print(f'TEST29b {mod}/{bank}: {len(rows)} alias keys '
                  f'{dict(Counter(r["animation"] for r in rows))}', flush=True)

    # uniques: does the wheel chain reach 21/27 there too
    for mod in sorted(m for m in base.manifest()['banks'] if m.startswith('D1C_Unique_')):
        for bank in base.manifest()['banks'][mod]:
            b = anm.load((SLIM / mod / base.REL / bank).read_bytes()).block
            e = edges(b)
            reach = {m: sorted(closure(e, [m])) for m in WHEEL}
            allr = set().union(*reach.values())
            out['uniques'][f'{mod}/{bank}'] = {
                'reachable': {str(m): reach[m] for m in WHEEL},
                'hurt_reached': sorted(allr & set(HURT)),
                'edges_into_hurt': [{'owner': a, 'node': ni, 'key': ki, 'target': t}
                                    for a in sorted(allr) for (ni, ki, t) in e.get(a, [])
                                    if t in HURT]}
    reached = Counter(str(v['hurt_reached']) for v in out['uniques'].values())
    (ROOT / 'Builds/WHEELFIX1-20261102/evidence').mkdir(parents=True, exist_ok=True)
    (ROOT / 'Builds/WHEELFIX1-20261102/evidence/analyze.json').write_text(
        json.dumps(out, indent=1) + '\n')
    print('unique banks: hurt reached ->', dict(reached), flush=True)
    print('wrote evidence/analyze.json')


if __name__ == '__main__':
    main()
