"""D1CMOTION2 art-only splice: graft the source hurt reaction into a preserved pack.

The rebuilt pack's palette/atlas is recomputed for every animation, so overlaying its files
changes pixels far outside the hurt slot (measured: 330 samples differ, including 11/17 and 6001).
This splice instead keeps the preserved TEST28 bank byte-for-byte and appends only what the hurt
slot needs:

  * animation 21 / 27 (the hurt slot) and 65003 / 65004 (a preserved copy of the donor's held
    21/27 picture, so stub aliases do not start flinching);
  * every node / key / cell / transform / param / texture / palette those trees use.

Then the existing stubs that nested 21/27 are re-pointed at 65003/65004 with their own transform
untouched, so their pictures and placement are unchanged.

usage: splice.py <preserved .lzs> <rebuilt .lzs> <out .lzs> --base-sha256 <TEST28 sha256>

The preserved bank must be a TEST28 base bank from `tools/test28-base.json`; `--base-sha256`
makes the splice refuse anything else (D1CMOTION2 grafted into TEST26 backup banks because the
path default was a kit backup).
"""
import copy
import hashlib
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
from d5lib import anm  # noqa: E402

GRAFT = (21, 27, 65003, 65004)
ALIAS = {21: 65003, 27: 65004}

old, new, out = map(Path, sys.argv[1:4])
if '--base-sha256' in sys.argv[4:] or '--base-sha256' in sys.argv:
    i = sys.argv.index('--base-sha256')
    want = sys.argv[i + 1]
    got = hashlib.sha256(old.read_bytes()).hexdigest()
    if got != want:
        raise SystemExit(f'refusing base {old}: sha256 {got} is not the expected TEST28 bank {want}')
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

# Alias stubs: keep drawing the held picture they had, now under its preserved id.
repointed = []
for ai, anim in enumerate(list(x.animations)):
    if anim.id in ALIAS or anim.id in ALIAS.values():
        continue
    if not anm.is_stub(a, 0, ai):
        continue
    for ni, _, _ in x.walk(x.animations[ai].root):
        for key in x.node_keys(x.nodes[ni]):
            if not anm.is_nested(key) or not 0 <= key.param < len(x.params):
                continue
            target = x.params[key.param]
            if target in ALIAS:
                x.params.append(ALIAS[target])
                key.param = len(x.params) - 1
                repointed.append((anim.id, target, ALIAS[target]))

out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(anm.lzs_compress(a.to_bytes()))
print(f'WROTE {out}')
print('grafted', sorted(grafted), 'aliases repointed', len(repointed))
