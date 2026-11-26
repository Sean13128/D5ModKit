"""Offline D4 monster bank round-trip audit and review GIFs, not native proof.

Writes private game-derived output to --output; never run against the installed kit.
The source and converted banks use the same evaluator, so agreement verifies the
serialization path, not the fidelity of that evaluator or D5 engine behavior.
"""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from d5lib import anm, d4source
from source_tracks import build

SOURCE = '/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+'
CLASSES = (2020, 2030, 2110)
ACTIONS = {'wheel-1': 1, 'stand-1001': 1001, 'walk': 11,
           'attack': 2071, 'damage': 1021, 'special': 4001}
BOUNDS = (-240, -360, 240, 120)


def inventory(b, a, nt, npal):
    bad_tex, bad_pal, bad_cell = set(), set(), set()
    for ni, _, _ in b.walk(a.root):
        for key in b.node_keys(b.nodes[ni]):
            if not key.cell:
                continue
            if key.cell >= len(b.cells):
                bad_cell.add(key.cell)
                continue
            c = b.cells[key.cell]
            if b.tex_base + c.tex >= nt:
                bad_tex.add(c.tex)
            if c.pal >= len(b.palette_infos) or b.pal_base + c.pal >= npal:
                bad_pal.add(c.pal)
    return {'invalid_cells': sorted(bad_cell), 'out_of_range_textures': sorted(bad_tex),
            'out_of_range_palettes': sorted(bad_pal)}


def image(bank, aid, tick, variant=0):
    items = anm.evaluate(bank, ('id', aid), tick, nested=True)
    return anm.render_items(bank, items, variant, bounds=BOUNDS)[0], len(items)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = d4source.D4Data(SOURCE)
    result = {'limitations': 'Same software evaluator for both formats; fixed canvas may clip; 60 Hz assumed, GIF delays rounded. No native behavior proven.', 'classes': {}}
    for cls in CLASSES:
        source = data.anm(cls)
        out = build(source, bank_id=cls)
        b, ob = source.blocks[0], out.blocks[0]
        # Equality includes all animation nodes, keys, durations, controls, offsets,
        # pivots, scales, colors, palette and texture metadata, not just samples.
        normalized = copy.deepcopy(b)
        normalized.fix_virtual_offsets()
        table_equal = [x == y for x, y in zip(normalized.tables(), ob.tables())]
        report = {'tables_equal': table_equal, 'texture_count': len(source.textures),
                  'palette_count': len(source.palettes), 'palette_infos': len(b.palette_infos),
                  'source_motion_count': len(b.animations), 'motions': {}}
        if not all(table_equal):
            raise AssertionError(f'{cls}: table mismatch {table_equal}')
        # Duplicate IDs are ambiguous to the evaluator and must be disclosed.
        ids = [a.id for a in b.animations]
        report['duplicate_ids'] = sorted({i for i in ids if ids.count(i) > 1})
        for index, a in enumerate(b.animations):
            info = anm.animation_info(b, a)
            other_info = anm.animation_info(ob, ob.animations[index])
            if info != other_info:
                raise AssertionError(f'{cls}/{a.id}: controls differ')
            report['motions'][str(index)] = {'id': a.id, 'controls': info,
                **inventory(b, a, len(source.textures), len(source.palettes))}
        for label, aid in ACTIONS.items():
            matches = [a for a in b.animations if a.id == aid]
            if len(matches) != 1:
                report.setdefault('render', {})[label] = {'id': aid, 'error': 'missing or ambiguous ID'}
                continue
            info = anm.animation_info(b, matches[0])
            end = int((info['loop'][1] if info['loop'] else info['length']) or 1)
            # All integer ticks for review actions, including loop endpoint.
            frames, drew = [], False
            for tick in range(end + 1):
                left, count = image(source, aid, tick)
                right, count2 = image(out, aid, tick)
                if count != count2 or not np.array_equal(np.asarray(left), np.asarray(right)):
                    raise AssertionError(f'{cls}/{aid} tick {tick}: render mismatch')
                drew |= bool(count)
                if tick < end and tick % 2 == 0:
                    bg = Image.new('RGBA', left.size, 'white')
                    bg.alpha_composite(right)
                    ImageDraw.Draw(bg).line((0, -BOUNDS[1], bg.width, -BOUNDS[1]), fill='#7f91a6')
                    frames.append(bg.convert('RGB'))
            # Check every supplied palette variant at a representative key time.
            palette_checks = 0
            for variant in range(len(b.palette_infos)):
                left, _ = image(source, aid, 0, variant)
                right, _ = image(out, aid, 0, variant)
                if not np.array_equal(np.asarray(left), np.asarray(right)):
                    raise AssertionError(f'{cls}/{aid} palette {variant}: mismatch')
                palette_checks += 1
            if drew and frames:
                frames[0].save(args.output / f'{cls}-{label}-prototype.gif', save_all=True,
                               append_images=frames[1:], duration=[40 if i % 3 == 0 else 30 for i in range(len(frames))],
                               loop=0, optimize=True, disposal=2)
            report.setdefault('render', {})[label] = {'id': aid, 'length': info['length'], 'loop': info['loop'],
                'ticks_compared': end + 1, 'samples': len(frames), 'palette_variants_compared_at_zero': palette_checks,
                'drawable': drew}
        result['classes'][str(cls)] = report
        print(cls, 'motions', len(ids), 'tables', table_equal, flush=True)
    (args.output / 'monster-proof.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
