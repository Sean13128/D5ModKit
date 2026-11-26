"""Compare every sampled ANM pose and rank against a baseline using the kit renderer.

Sample times are the union of both files' renderer frame_times for each animation. `--exempt` names
the animation IDs whose samples may differ (default: the four lift IDs; D1CWALK1 passes 11 17 and
leaves the lift inside the equality check). Outputs a JSON receipt and a side-by-side PNG for every
differing non-exempt sample.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from d5lib import anm

# Immutable ANM files: cache decoded atlas/palette images across pose samples.
# The upstream renderer does not mutate these images.
_texture_to_image = anm.texture_to_image
_texture_cache = {}
def _cached_texture(file, tex_index, palette_index=0):
    key = (id(file), tex_index, palette_index)
    if key not in _texture_cache:
        _texture_cache[key] = _texture_to_image(file, tex_index, palette_index)
    return _texture_cache[key]
anm.texture_to_image = _cached_texture

LIFT = {1061, 1067, 1141, 1147}


def read(path):
    data = Path(path).read_bytes()
    return anm.load(data), hashlib.sha256(data).hexdigest()


def pose(a, idx, t, rank):
    items = anm.evaluate(a, idx, t, nested=True)
    image, origin = anm.render_items(a, items, palette_index=rank)
    bbox = image.getchannel('A').getbbox()
    if not bbox:
        return Image.new('RGBA', (1, 1)), None
    # Position of the alpha-content corner in the coordinate system of the pivot.
    position = (bbox[0] - origin[0], bbox[1] - origin[1])
    return image.crop(bbox), position


def save_pair(left, right, path, label, left_label):
    w = max(left.width, right.width, 150)
    h = max(left.height, right.height, 20)
    out = Image.new('RGBA', (2 * w, h + 30), (48, 48, 48, 255))
    out.alpha_composite(left, (0, 30))
    out.alpha_composite(right, (w, 30))
    draw = ImageDraw.Draw(out)
    draw.text((2, 2), f'{left_label} {label}', fill='white')
    draw.text((w + 2, 2), 'REBUILT', fill='white')
    out.convert('RGB').save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('baseline')
    ap.add_argument('rebuilt')
    ap.add_argument('output', help='receipt JSON path; mismatch PNGs are written beside it')
    ap.add_argument('--ranks', type=int, default=6)
    ap.add_argument('--exempt', type=int, nargs='*', default=sorted(LIFT),
                    help='animation IDs allowed to differ (default: the four lift IDs)')
    ap.add_argument('--baseline-label', default='BASELINE')
    args = ap.parse_args()
    exempt = set(args.exempt)
    old, old_hash = read(args.baseline)
    new, new_hash = read(args.rebuilt)

    def indexes(a):
        infos = anm.list_animations(a)
        ids = [x['id'] for x in infos]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate animation IDs require disambiguation')
        return {x['id']: x['index'] for x in infos}

    oi, ni = indexes(old), indexes(new)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(baseline=str(args.baseline), rebuilt=str(args.rebuilt),
                   baseline_sha256=old_hash, rebuilt_sha256=new_hash,
                   rank_palettes=list(range(args.ranks)),
                   method='kit renderer, nested=True; union of frame_times; exact RGBA and alpha-bounds position relative to origin',
                   exempt_ids=sorted(exempt), lift_ids=sorted(LIFT),
                   missing_ids=sorted(oi.keys() - ni.keys()),
                   extra_ids=sorted(ni.keys() - oi.keys()), animation_samples={},
                   samples_compared=0, exempt_samples=0, differences=[])
    # Rank variants can share a render only when every palette potentially read by
    # either animation file is byte-identical for both ranks.
    def palette_signature(a, rank):
        parts = []
        for block in a.blocks:
            for pal in sorted({c.pal for c in block.cells if c.w and c.h}):
                ix = block.pal_base + min(pal + rank, max(0,len(block.palette_infos)-1))
                parts.append(hashlib.sha256(a.palettes[min(ix,len(a.palettes)-1)].data).hexdigest())
        return tuple(parts)
    groups = {}
    for rank in range(args.ranks):
        key=(palette_signature(old,rank),palette_signature(new,rank))
        groups.setdefault(key,[]).append(rank)
    receipt['rank_equivalence'] = list(groups.values())
    for aid in sorted(oi.keys() & ni.keys()):
        times = sorted(set(anm.frame_times(old, oi[aid])) | set(anm.frame_times(new, ni[aid])))
        receipt['animation_samples'][str(aid)] = times
        for t in times:
            for group in groups.values():
                rank = group[0]
                a, apos = pose(old, oi[aid], t, rank)
                b, bpos = pose(new, ni[aid], t, rank)
                receipt['samples_compared'] += len(group)
                if aid in exempt:
                    receipt['exempt_samples'] += len(group)
                    continue
                if a.size != b.size or a.tobytes() != b.tobytes() or apos != bpos:
                    name = f'{output.stem}-id{aid}-t{t}-rank{rank}.png'
                    save_pair(a, b, output.parent / name, f'{aid} t{t} rank{rank}', args.baseline_label)
                    for represented_rank in group:
                        receipt['differences'].append(dict(id=aid, time=t, rank=represented_rank,
                            rendered_as_rank=rank, baseline_position=apos, rebuilt_position=bpos, baseline_size=a.size,
                            rebuilt_size=b.size, png=name))
        print(f'{aid}: {len(times)} times', flush=True)
    receipt['pass'] = not (receipt['missing_ids'] or receipt['extra_ids'] or receipt['differences'])
    output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(f"{'PASS' if receipt['pass'] else 'FAIL'}: {receipt['samples_compared']} samples, "
          f"{receipt['exempt_samples']} exempt, {len(receipt['differences'])} differences")
    return 0 if receipt['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
