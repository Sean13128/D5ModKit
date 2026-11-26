"""WHEELBISECT1 step 1b: the same reachability trace on the *installed* (replayed) members.

INSTALLGATE1's replay puts the installer's real transforms on TEST28/SLIM29 members:
/Volumes/Data/ai-tmp/codex/installgate1/members/<BUILD>/<MOD>/<bank>.lzs (decoded member bytes).
This checks whether the grips pass (0x100 -> 0x200 on 12 reachable keys of 21/27) changes the
answer for the wheel's own motions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from d5lib import anm  # noqa: E402

MEMBERS = Path('/Volumes/Data/ai-tmp/codex/installgate1/members')
NESTED = 0x100
BANKS = {'D1C_Class_11390': ('anm01540.lzs', 'anm01541.lzs'),
         'D1C_Class_11400': ('anm01530.lzs', 'anm01531.lzs')}
WHEEL_MOTIONS = [1, 101, 1001]


def edges(block):
    ids = {a.id for a in block.animations}
    out = {}
    for animation in block.animations:
        seen, todo, targets = set(), [animation.root], set()
        while todo:
            ni = todo.pop()
            if ni in seen or not 0 <= ni < len(block.nodes):
                continue
            seen.add(ni)
            node = block.nodes[ni]
            todo.extend((node.child, node.next))
            if node.first_key < 0:
                continue
            for ki in range(node.first_key, min(node.first_key + node.num_keys, len(block.keys))):
                key = block.keys[ki]
                if key.flags & NESTED and 0 <= key.param < len(block.params):
                    t = abs(block.params[key.param])
                    if t in ids and t != animation.id:
                        targets.add(t)
        if targets:
            out[animation.id] = sorted(targets)
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
    for build in ('TEST28', 'SLIM29'):
        for mod, banks in BANKS.items():
            for bank in banks:
                p = MEMBERS / build / mod / bank
                f = anm.load(p.read_bytes())
                b = f.block
                e = edges(b)
                reach = {str(m): sorted(closure(e, [m])) for m in WHEEL_MOTIONS}
                # flags on 21/27 keys: which nested bits were cleared
                flags = {}
                for aid in (21, 27):
                    a = [x for x in b.animations if x.id == aid]
                    if not a:
                        continue
                    seen, todo = set(), [a[0].root]
                    counts = {'0x100': 0, '0x200': 0, 'none': 0}
                    while todo:
                        ni = todo.pop()
                        if ni in seen or not 0 <= ni < len(b.nodes):
                            continue
                        seen.add(ni)
                        n = b.nodes[ni]
                        todo.extend((n.child, n.next))
                        if n.first_key < 0:
                            continue
                        for ki in range(n.first_key, min(n.first_key + n.num_keys, len(b.keys))):
                            fl = b.keys[ki].flags
                            if fl & 0x100:
                                counts['0x100'] += 1
                            elif fl & 0x200:
                                counts['0x200'] += 1
                            else:
                                counts['none'] += 1
                    flags[str(aid)] = counts
                res[f'{build}/{mod}/{bank}'] = {
                    'bytes': len(p.read_bytes()),
                    'reachable': reach,
                    'hurt_reachable_from': {str(t): sorted(m for m, c in reach.items() if t in c)
                                            for t in (21, 27)},
                    'stubs_reachable_from': {str(s): sorted(m for m, c in reach.items() if s in c)
                                             for s in (1011, 1017, 5001, 5021)},
                    'nested_flag_counts_21_27': flags,
                    'nesters_of_21': sorted(a for a, ts in e.items() if 21 in ts),
                }
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
