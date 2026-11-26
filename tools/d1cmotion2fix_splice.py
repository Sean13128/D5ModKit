"""TEST29FIX1 splice: the D1CMOTION3 art-only splice with a correct aux TRIPLE for each alias.

`d1cmotion2_splice.py` re-points the stub aliases by appending ONE i32 per key
(`x.params.append(ALIAS[target])`).  Table 9 is an array of 3-i32 aux records
(motion, start tick, duration) — `anm_actor_spawn_attachment` reads `param_3[1]` as the start tick
and `param_3[2]` as the duration — so that append left 42 keys per class bank with
start tick 65003 and duration 65003 instead of (0, -1), and two of them pointing at the last
element of the table (index+1/+2 past the end).  This version appends `(id, 0, -1)` and points the
key at its first element, which is the shape every TEST28 nested key has.

usage: d1cmotion2fix_splice.py <preserved .lzs> <rebuilt .lzs> <out .lzs>
           --base-sha256 <TEST28 sha256> [--hurt-only]

--hurt-only grafts 21/27 and nothing else: no preserved ids, no alias re-point, so the stub
aliases keep nesting 21/27 (TEST29c).
"""
import copy
import hashlib
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
from d5lib import anm  # noqa: E402

HURT = (21, 27)
PRESERVED = {21: 65003, 27: 65004}

hurt_only = '--hurt-only' in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith('--')]
old, new, out = map(Path, args[:3])
if '--base-sha256' in sys.argv:
    want = sys.argv[sys.argv.index('--base-sha256') + 1]
    got = hashlib.sha256(old.read_bytes()).hexdigest()
    if got != want:
        raise SystemExit(f'refusing base {old}: sha256 {got} is not the expected TEST28 bank {want}')

GRAFT = HURT if hurt_only else HURT + tuple(PRESERVED.values())
ALIAS = {} if hurt_only else PRESERVED

a = anm.load(old)
b = anm.load(new)
assert len(a.blocks) == len(b.blocks) == 1, 'single-block banks expected'
x, y = a.block, b.block

nodebase = len(x.nodes)
keybase = len(x.keys)
cellbase = len(x.cells)
xfbase = len(x.transforms)
pivotbase = len(x.pivots)
colorbase = len(x.colors)
parambase = len(x.params)
texbase = len(x.texture_infos)
palbase = len(x.palette_infos)

for n in y.nodes:
    n = copy.copy(n)
    n.first_key = n.first_key + keybase if n.first_key >= 0 else -1
    n.child = n.child + nodebase if n.child >= 0 else -1
    n.next = n.next + nodebase if n.next >= 0 else -1
    x.nodes.append(n)
for k in y.keys:
    k = copy.copy(k)
    k.cell = k.cell + cellbase if k.cell else 0
    k.xform += xfbase
    k.color += colorbase
    k.param += parambase
    x.keys.append(k)
for c in y.cells:
    c = copy.copy(c)
    c.tex += texbase
    c.pal += palbase
    x.cells.append(c)
for t in y.transforms:
    t = copy.copy(t)
    t.pivot += pivotbase
    x.transforms.append(t)
x.pivots.extend(copy.deepcopy(y.pivots))
x.colors.extend(copy.deepcopy(y.colors))
x.params.extend(y.params)
x.texture_infos.extend(copy.deepcopy(y.texture_infos))
x.palette_infos.extend(copy.deepcopy(y.palette_infos))
a.textures.extend(copy.deepcopy(b.textures))
a.palettes.extend(copy.deepcopy(b.palettes))

grafted = {v.id: v for v in y.animations if v.id in GRAFT}
missing = [i for i in GRAFT if i not in grafted]
if missing:
    raise SystemExit(f'rebuilt pack lacks {missing}')
have = {v.id for v in x.animations}
for aid, anim in grafted.items():
    root = anim.root + nodebase if anim.root >= 0 else -1
    if aid in have:
        next(t for t in x.animations if t.id == aid).root = root
    else:
        x.animations.append(anm.Animation(aid, root))

repointed = []
if ALIAS:
    for ai, anim in enumerate(list(x.animations)):
        if anim.id in ALIAS or anim.id in ALIAS.values():
            continue
        if not anm.is_stub(a, 0, ai):
            continue
        for ni, _d, _p in x.walk(x.animations[ai].root):
            for key in x.node_keys(x.nodes[ni]):
                if not anm.is_nested(key) or not 0 <= key.param < len(x.params):
                    continue
                target = x.params[key.param]
                if target in ALIAS:
                    # table 9 is (motion, start tick, duration) triples: append a whole record
                    x.params.extend([ALIAS[target], 0, -1])
                    key.param = len(x.params) - 3
                    repointed.append((anim.id, target, ALIAS[target]))
    if len(x.params) % 3:
        raise SystemExit('params table is not a whole number of 3-i32 records')

out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(anm.lzs_compress(a.to_bytes()))
print(f'WROTE {out}')
print('grafted', sorted(grafted), 'aliases repointed', len(repointed),
      'params', len(x.params), 'mod3', len(x.params) % 3)
