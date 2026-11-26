"""WHEELBISECT1 verify: what each built variant's wheel actually reaches.

For every variant and class bank: the motion ids FUN_140666920 requests (101 ring, 1001 centre,
1 flagged slot), the closure of nested spawn keys, and which *root* each reached 21/27 has
(TEST28's held picture or SLIM29's worked art), plus what the four stubs now name.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
OUT = ROOT / 'Builds/WHEELBISECT1-20261102'
T28 = {m: base.base_dir(m) / m for m in ('D1C_Class_11390', 'D1C_Class_11400')}
T28_HELD_ROOT = {21: 74, 27: 92}
NESTED = 0x100
WHEEL = (1, 101, 1001)
STUBS = (1011, 1017, 5001, 5021)


def edges(b):
    ids = {a.id for a in b.animations}
    out = {}
    for a in b.animations:
        seen, todo, tg = set(), [a.root], set()
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
                        tg.add(t)
        if tg:
            out[a.id] = sorted(tg)
    return out


def closure(e, roots):
    seen, todo = set(), list(roots)
    while todo:
        a = todo.pop()
        if a in seen:
            continue
        seen.add(a)
        todo.extend(e.get(a, ()))
    return seen


def main():
    res = {}
    variants = ['bs_s', 'bs_e', 'bs_nostub', 'bs_dark']
    for v in variants:
        res[v] = {}
        for mod in T28:
            banks = base.manifest()['banks'][mod]
            for bank in banks:
                p = OUT / v / 'mods' / mod / base.REL / bank
                b = anm.load(p.read_bytes()).block
                e = edges(b)
                reach = {str(m): sorted(closure(e, [m])) for m in WHEEL}
                roots = {str(a.id): a.root for a in b.animations}
                reach_hurt = {}
                for m in WHEEL:
                    c = closure(e, [m])
                    for h in (21, 27):
                        if h in c:
                            reach_hurt[f'{m}->{h}'] = ('TEST28-held'
                                                       if roots[str(h)] == T28_HELD_ROOT[h]
                                                       else f'SLIM29-worked(root {roots[str(h)]})')
                stubs = {}
                for s in STUBS:
                    tg = set()
                    c = closure(e, [s])
                    for t in sorted(c & {21, 27}):
                        tg.add(t)
                    stubs[str(s)] = {'reaches_21_27': sorted(tg),
                                     'names': [abs(b.params[b.keys[ki].param])
                                               for ni, ki in _tree_keys(b, roots[str(s)])
                                               if b.keys[ki].flags & NESTED]}
                extra = sorted(set(roots) - {str(a.id) for a in anm.load(
                    (T28[mod] / base.REL / bank).read_bytes()).block.animations})
                res[v][f'{mod}/{bank}'] = {'reach': reach, 'hurt_reached': reach_hurt,
                                          'stubs': stubs, 'animation_ids_added': extra,
                                          'roots_21_27': [roots['21'], roots['27']]}
    (OUT / 'evidence').mkdir(parents=True, exist_ok=True)
    (OUT / 'evidence' / 'reach.json').write_text(json.dumps(res, indent=1) + '\n')
    for v in variants:
        print('==', v)
        for bank, r in res[v].items():
            print(' ', bank, 'hurt:', r['hurt_reached'], 'added:', r['animation_ids_added'])
            print('   stubs:', {k: (x['reaches_21_27'], x['names']) for k, x in r['stubs'].items()})


def _tree_keys(b, root):
    out, seen, todo = [], set(), [root]
    while todo:
        ni = todo.pop()
        if ni in seen or not 0 <= ni < len(b.nodes):
            continue
        seen.add(ni)
        n = b.nodes[ni]
        todo.extend((n.child, n.next))
        if n.first_key < 0:
            continue
        out.extend((ni, ki) for ki in range(n.first_key, n.first_key + n.num_keys))
    return out


if __name__ == '__main__':
    main()
