"""TEST29FIX1: repair table 9 in a TEST29 bank (aux TRIPLE alignment).

Table 9 is an array of 3-i32 aux records (motion, start tick, duration):
`anm_actor_spawn_attachment` reads `*param_3` as the motion id, `param_3[1]` as the start tick
(Q16) and `param_3[2]` as the duration, and `anm_node_seek_attachments` passes
`params + key.param * 4`.  Every nested key in TEST28 (1823 of 1823 in a class bank) points at an
index that is a multiple of 3 whose triple is `(id, 0, -1)`.

D1CMOTION3's `d1cmotion2_splice.py` appended ONE i32 per re-pointed alias
(`x.params.append(ALIAS[target])`), which shifts the table out of alignment: in the two class banks
42 keys end up with start tick 65003 (65004) and duration 65003 instead of 0 and -1, two of them
point at index len(params)-1 so `param_3[1]`/`[2]` read past the table.

This tool rewrites only those keys:

  * truncate the appended tail (the bare ids),
  * append one canonical triple per preserved id: (id, 0, -1),
  * point every affected key at the first element of its triple.

Everything else — every other table, every image, every pixel — is left byte-identical.

usage: test29fix1_params.py <TEST29 bank in> <out> [--expect-ids 65003 65004]
"""
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
from d5lib import anm  # noqa


def for_each_nested_key(b):
    for ai, a in enumerate(b.animations):
        for ni, _d, _p in b.walk(a.root):
            for k in b.node_keys(b.nodes[ni]):
                if anm.is_nested(k) and 0 <= k.param < len(b.params):
                    yield a.id, k


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    expect = {65003, 65004}
    if '--expect-ids' in sys.argv:
        i = sys.argv.index('--expect-ids')
        expect = set()
        for tok in sys.argv[i + 1:]:
            if tok.startswith('--'):
                break
            expect.add(int(tok))
    f = anm.load(src)
    b = f.block
    ids = {a.id for a in b.animations}
    missing = expect - ids
    if missing:
        raise SystemExit(f'{src}: expected preserved ids {sorted(missing)} are absent; not a TEST29 bank')

    affected = []
    for aid, k in for_each_nested_key(b):
        i = k.param
        trip = tuple(b.params[i + j] if i + j < len(b.params) else None for j in range(3))
        if b.params[i] in expect and trip != (b.params[i], 0, -1):
            affected.append((aid, k, i, trip))
    if not affected:
        raise SystemExit(f'{src}: no misaligned preserved-id triple; nothing to repair')

    first = min(i for _a, _k, i, _t in affected)
    # nothing else may reference the tail we are about to cut
    refs = {k.param for _aid, k in for_each_nested_key(b) if k.param >= first}
    stray = refs - {i for _a, _k, i, _t in affected}
    if stray:
        raise SystemExit(f'{src}: {len(stray)} other keys reference the appended tail; refusing')
    if first % 3:
        raise SystemExit(f'{src}: tail starts at {first}, not a multiple of 3; refusing')

    pids = sorted({t[0] for *_x, t in affected})
    del b.params[first:]
    canon = {}
    for pid in pids:
        canon[pid] = len(b.params)
        b.params.extend([pid, 0, -1])
    for aid, k, i, trip in affected:
        k.param = canon[trip[0]]
    # verify
    bad = 0
    for aid, k in for_each_nested_key(b):
        i = k.param
        if b.params[i] in expect and tuple(b.params[i + j] for j in range(3)) != (b.params[i], 0, -1):
            bad += 1
    if bad or len(b.params) % 3:
        raise SystemExit(f'{src}: repair did not settle ({bad} bad, {len(b.params)} params)')

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(anm.lzs_compress(f.to_bytes()))
    print(f'WROTE {out}  repaired {len(affected)} keys, truncated tail at {first} '
          f'({first} -> {len(b.params)} params), canon {canon}')


if __name__ == '__main__':
    main()
