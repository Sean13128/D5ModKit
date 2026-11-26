"""WHEELFIX1 equivalence: the copies are TEST28's spawned child, field for field.

The kit renderer cannot show this build's change (its `nested=True` model only follows a 0x100 spawn
when the animation is a stub, and 1, 101 and 6001 are not), and a naive "follow every spawn" model
explodes the 1 <-> 21 cycle into thousands of extra items, because the copies carry fresh ids and so
no longer collapse the cycle by name. Neither is evidence about the engine, so this gate does not
compare pictures: it proves the *data* the engine reads at the spawn site is the same.

For every nested key the wheel reaches and that names 21/27, the engine (`anm_actor_spawn_attachment`
0x1402f4890 -> `anm_actor_init`) reads: the target animation's node tree, each node's keys (time,
flags, cell, transform, colour), the cell rectangles and their texels, and the palette window. So for
each re-pointed key this tool compares, record for record and texel for texel,

    TEST28's target animation   vs   the copy the key now names,

with TEST28's internal nested ids renamed through the build's id map (21->64061, 1->64031, ...), and
asserts they are equal. Whatever the engine composes from TEST28's 21/27, it composes the same from
64061/64071.

usage: python tools/wheelfix1_equivalence.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
OUT = ROOT / 'Builds/WHEELFIX1-20261102'
EV = OUT / 'evidence'
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
T28 = {m: base.base_dir(m) / m for m in ('D1C_Class_11390', 'D1C_Class_11400')}
NESTED = 0x100


def cell_sig(f, c):
    b = f.blocks[0]
    idx = anm.texture_indices(f, c.tex)[c.y:c.y + c.h, c.x:c.x + c.w]
    pal = (anm.get_palette(f, c.pal).tobytes() if 0 <= c.pal < len(f.palettes) else b'')
    return {'rect': [c.x, c.y, c.w, c.h], 'tex_shape': list(idx.shape),
            'texel_sha256': hashlib.sha256(np.ascontiguousarray(idx).tobytes()).hexdigest(),
            'pal_local': c.pal, 'palette_sha256': hashlib.sha256(pal).hexdigest()}


def node_sig(f, ni, seen, rename, depth=0):
    b = f.blocks[0]
    if not 0 <= ni < len(b.nodes):
        return None
    if ni in seen or depth > 64:
        return {'cycle': ni}
    seen = seen | {ni}
    n = b.nodes[ni]
    keys = []
    for k in b.node_keys(n):
        rec = None
        if k.flags & 0xFF00 and 0 <= k.param < len(b.params):
            t = abs(b.params[k.param])
            rec = rename.get(t, t)
        keys.append({'time': k.time, 'flags': k.flags, 'cell': cell_sig(f, b.cells[k.cell])
                     if 0 <= k.cell < len(b.cells) else None,
                     'xform': _xform(b, k.xform), 'color': _color(b, k.color),
                     'nested_target': rec})
    return {'node': {'mesh': n.mesh}, 'keys': keys,
            'child': node_sig(f, n.child, seen, rename, depth + 1),
            'next': node_sig(f, n.next, seen, rename, depth + 1)}


def _xform(b, i):
    if not 0 <= i < len(b.transforms):
        return None
    x = b.transforms[i]
    return [x.x, x.y, x.sx, x.sy, x.rot, x.pivot]


def _color(b, i):
    if not 0 <= i < len(b.colors):
        return None
    return list(b.colors[i].rgba)


def animation_sig(f, aid, rename):
    # the root index itself is meaningless (a copy gets a fresh node index); the tree is compared.
    a = next(x for x in f.blocks[0].animations if x.id == aid)
    return node_sig(f, a.root, frozenset(), rename)


def canonical(sig):
    return hashlib.sha256(json.dumps(sig, sort_keys=True).encode()).hexdigest()


def main():
    build = json.loads((EV / 'build.json').read_text())
    rows, ok = [], True
    for mod in T28:
        for bank in base.manifest()['banks'][mod]:
            key = f'{mod}/{bank}'
            t28 = anm.load((T28[mod] / base.REL / bank).read_bytes())
            fix = anm.load((OUT / 'mods' / mod / base.REL / bank).read_bytes())
            idmap = {int(k): v for k, v in build['patched'][key]['idmap'].items()}
            targets = sorted({r['from'] for r in build['patched'][key]['repointed']})
            row = {'bank': key, 'idmap': idmap, 'targets': targets, 'checks': []}
            for target in targets:
                copy = idmap[target]
                # TEST28's internal ids are renamed through the build's map; the copy already
                # names the copies, so it is compared as it stands.
                a = canonical(animation_sig(t28, target, idmap))
                c = canonical(animation_sig(fix, copy, {}))
                same = a == c
                keys = sum(1 for r in build['patched'][key]['repointed'] if r['from'] == target)
                row['checks'].append({'test28_id': target, 'copy_id': copy,
                                      'test28_signature': a, 'copy_signature': c,
                                      'equal': same, 'repointed_keys_naming_it': keys})
                print(f'{key}: TEST28 {target} == copy {copy}: {same} '
                      f'({keys} of the re-pointed keys name it)', flush=True)
                ok &= same
            # the copies are distinct animations with distinct roots
            roots = {t: next(x.root for x in fix.blocks[0].animations if x.id == idmap[t])
                     for t in targets}
            row['copy_roots'] = {str(k): v for k, v in roots.items()}
            row['copy_roots_distinct'] = len(set(roots.values())) == len(roots)
            ok &= row['copy_roots_distinct']
            rows.append(row)

    (EV / 'equivalence.json').write_text(json.dumps({'pass': bool(ok), 'banks': rows},
                                                    indent=1) + '\n')
    print('EQUIVALENCE', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
