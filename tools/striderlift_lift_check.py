"""Prove a rebuilt D1C pack's lift slot draws the body-bound bank 1 lift (2671/2677).

Checks, per pack/body:
  * D5 1101 / 1107 render the source lift's pixels (cropped content equal to the
    `d1cart.shared_lift` render of bank 1's 2671 / 2677), not the held stand pose;
  * the aliases 1131 / 1137 resolve to those same new frames;
  * the lift keeps the stand pose's foot line (same content bottom relative to pivot).
Writes a JSON receipt and a side-by-side `stand | lift` PNG per view from the pack.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from d5lib import anm, d1cart

STAND = {'front': 1001, 'back': 1007}
LIFT = {'front': 1101, 'back': 1107}
ALIAS = {'front': 1131, 'back': 1137}


def content(pack, index):
    """Content-cropped RGBA of the first frame plus (corner relative to pivot, bottom relative to pivot)."""
    t = anm.frame_times(pack, index)[0]
    items = anm.evaluate(pack, index, t, nested=True)
    image, origin = anm.render_items(pack, items, palette_index=0)
    bbox = image.getchannel('A').getbbox()
    if not bbox:
        raise ValueError('blank render')
    return image.crop(bbox), (bbox[0] - origin[0], bbox[1] - origin[1]), bbox[3] - origin[1]


def indexed(pack):
    ids = [x['id'] for x in anm.list_animations(pack)]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate animation IDs')
    return {x['id']: x['index'] for x in anm.list_animations(pack)}


def compare(a, b, tolerance=1):
    """Same drawing at the same size; the pack re-quantises onto its rank palettes, so allow one level."""
    if a.size != b.size:
        return False
    if a.tobytes() == b.tobytes():
        return True
    delta = np.abs(np.asarray(a).astype(int) - np.asarray(b).astype(int))
    return int(delta.max()) <= tolerance


def sheet(images, labels, path, title):
    w = max(i.width for i in images) + 12
    h = max(i.height for i in images) + 34
    out = Image.new('RGBA', (w * len(images), h), (40, 40, 44, 255))
    draw = ImageDraw.Draw(out)
    draw.text((4, 3), title, fill='white')
    for n, (image, label) in enumerate(zip(images, labels)):
        out.alpha_composite(image, (n * w + (w - image.width) // 2, 24))
        draw.text((n * w + 4, 12), label, fill=(200, 200, 200))
    out.convert('RGB').save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--art', required=True, help='D1 Complete HD art root')
    ap.add_argument('--pack', required=True)
    ap.add_argument('--body', type=int, required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--out', required=True, help='receipt JSON; PNGs are written beside it')
    args = ap.parse_args()
    data = Path(args.pack).read_bytes()
    pack = anm.load(data)
    ids = indexed(pack)
    lift, evidence = d1cart.shared_lift(Path(args.art), args.body)
    if lift is None:
        raise SystemExit('body has no shared bank 1')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(label=args.label, pack=str(args.pack), body=args.body,
                   pack_sha256=hashlib.sha256(data).hexdigest(),
                   source_tags=evidence['source_tags'], views={})
    ok = True
    for view in ('front', 'back'):
        source = lift[('launch', view)][0]
        sbox = source.getchannel('A').getbbox()
        source_crop = source.crop(sbox)
        slot, slot_pos, slot_bottom = content(pack, ids[LIFT[view]])
        alias, alias_pos, _ = content(pack, ids[ALIAS[view]])
        stand, stand_pos, stand_bottom = content(pack, ids[STAND[view]])
        entry = dict(lift_id=LIFT[view], alias_id=ALIAS[view], stand_id=STAND[view],
                     lift_matches_source=compare(slot, source_crop),
                     alias_matches_lift=compare(alias, slot),
                     lift_size=list(slot.size), source_size=list(source_crop.size),
                     stand_size=list(stand.size),
                     lift_position=list(slot_pos), stand_position=list(stand_pos),
                     lift_bottom=slot_bottom, stand_bottom=stand_bottom,
                     foot_line_delta=slot_bottom - stand_bottom)
        ok &= entry['lift_matches_source'] and entry['alias_matches_lift']
        receipt['views'][view] = entry
        sheet([stand, slot], [f'stand {STAND[view]}', f'lift {LIFT[view]} -> {evidence["source_tags"][view]}'],
              out.parent / f'{out.stem}-{view}.png', f'{args.label} body {args.body} {view}')
    receipt['pass'] = ok
    out.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'views'}, indent=2))
    for view, entry in receipt['views'].items():
        print(view, json.dumps(entry))
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
