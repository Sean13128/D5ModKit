"""Independent verification of the PT1030ANIM bundle, read only from the bundle + TEST18B."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, '/Volumes/Data/Projects/D5/Local/Worktrees/pt1030anim')
from d5lib import anm  # noqa: E402

BUNDLE = Path('/Volumes/Data/Projects/D5/Builds/PT1030ANIM-20261030')
BASE = Path('/Volumes/Data/Projects/D5/Builds/LIVE5_TEST18B-20261030/mods')


def load(p):
    return anm.load(p.read_bytes())


def drawn(a, aid):
    return sum(1 for t in anm.frame_times(a, ('id', aid))
               if any(it.key.cell for it in anm.evaluate(a, ('id', aid), t)))


def rot_keys(a):
    b = a.blocks[0]
    n = 0
    for ai in b.animations:
        for ni, _, _ in b.walk(ai.root):
            if b.nodes[ni].id not in (0, 1):
                continue
            for k in b.node_keys(b.nodes[ni]):
                if k.cell and b.transforms[k.xform].rot % 360:
                    n += 1
    return n


def compare_d1c(pack, rel):
    old = load(BASE / pack / rel)
    new = load(BUNDLE / 'mods' / pack / rel)
    ob, nb = old.blocks[0], new.blocks[0]
    res = dict(animations=[len(ob.animations), len(nb.animations)],
               nodes=[len(ob.nodes), len(nb.nodes)], keys=[len(ob.keys), len(nb.keys)],
               cells=[len(ob.cells), len(nb.cells)], textures=[len(old.textures), len(new.textures)],
               same_ids=sorted(a.id for a in ob.animations) == sorted(a.id for a in nb.animations))
    changed_times = sum(1 for x, y in zip(ob.keys, nb.keys) if x.time != y.time)
    res['keys_retimed'] = changed_times
    res['rotated_body_keys'] = [rot_keys(old), rot_keys(new)]
    res['drawn_equal'] = {a.id: [drawn(old, a.id), drawn(new, a.id)]
                          for a in ob.animations if drawn(old, a.id) != drawn(new, a.id)}
    return res


def compare_wheel(pack, rel):
    old = load(BASE / pack / rel)
    new = load(BUNDLE / 'mods' / pack / rel)
    ob, nb = old.blocks[0], new.blocks[0]
    res = {}
    for aid in (1001, 1007):
        if not anm.has_animation(new, aid):
            continue
        ai = next(x for x in nb.animations if x.id == aid)
        keys = [k for ni, _, _ in nb.walk(ai.root) for k in nb.node_keys(nb.nodes[ni])]
        info = anm.animation_info(nb, ai)
        nested = [nb.params[k.param] for k in keys
                  if (k.flags & 0xFF00) == anm.NESTED and 0 <= k.param < len(nb.params)]
        res[aid] = dict(keys=len(keys), length=info.get('length'), nested=nested)
    # every other animation keeps its key times and cells
    ids = [a.id for a in ob.animations if a.id not in (1001, 1007)]
    same = all([(k.time, k.cell) for ni, _, _ in ob.walk(next(x for x in ob.animations if x.id == i).root)
                for k in ob.node_keys(ob.nodes[ni])] ==
               [(k.time, k.cell) for ni, _, _ in nb.walk(next(x for x in nb.animations if x.id == i).root)
                for k in nb.node_keys(nb.nodes[ni])] for i in ids)
    res['other_animations_unchanged'] = same
    return res


def compare_order(pack, rel):
    old = load(BASE / pack / rel)
    new = load(BUNDLE / 'mods' / pack / rel)
    ob, nb = old.blocks[0], new.blocks[0]
    ai = next(x for x in nb.animations if x.id == 1001)
    chain = [ni for ni, _, _ in nb.walk(ai.root)]
    ao = next(x for x in ob.animations if x.id == 1001)
    chain_old = [ni for ni, _, _ in ob.walk(ao.root)]
    areas = [(nb.cells[nb.keys[k].cell].w * nb.cells[nb.keys[k].cell].h)
             if (k := nb.nodes[i].first_key) >= 0 and nb.keys[k].cell else 0 for i in chain]
    return dict(order_old=chain_old, order_new=chain, areas=areas)


inv = json.loads((BUNDLE / 'INVENTORY.json').read_text())
out = {'base': inv['base'], 'packs': {}, 'problems': []}
for pack, entries in sorted(inv['mods'].items()):
    for e in entries:
        rel = e['path']
        if pack.startswith('D1C_Class_'):
            r = compare_d1c(pack, rel)
            if not r['same_ids']:
                out['problems'].append('%s %s: animation id set changed' % (pack, rel))
            if r['drawn_equal']:
                out['problems'].append('%s %s: drawn frames changed %s' % (pack, rel, r['drawn_equal']))
            if r['rotated_body_keys'][1]:
                out['problems'].append('%s %s: rotated whole-pose keys remain' % (pack, rel))
            out['packs'].setdefault(pack, []).append(dict(file=rel.split('/')[-1], kind='d1c', **r))
        elif pack in ('D4_Class_2120', 'D4_Unique_170'):
            r = compare_order(pack, rel)
            out['packs'].setdefault(pack, []).append(dict(file=rel.split('/')[-1], kind='order', **r))
        else:
            r = compare_wheel(pack, rel)
            bad = [a for a, v in r.items() if isinstance(v, dict) and v['keys'] > 2]
            if bad:
                out['problems'].append('%s %s: wheel motion still long %s' % (pack, rel, bad))
            if r.get('other_animations_unchanged') is False:
                out['problems'].append('%s %s: another animation changed' % (pack, rel))
            entry = dict(r)
            entry.update(file=rel.split('/')[-1], kind='wheel')
            out['packs'].setdefault(pack, []).append(entry)

(BUNDLE / 'VERIFY.json').write_text(json.dumps(out, indent=2) + '\n')
print('problems:', len(out['problems']))
for p in out['problems'][:10]:
    print(' ', p)
