"""Prove a rebuilt D1C pack's walk slot draws the body-bound bank 1 walk (11 / 17).

Checks, per pack/body:
  * D5 11 / 17 render the source walk's frames, in order, at the source's key times;
  * the walk keeps the stand pose's foot line (lowest content bottom within 1 px);
  * the aliases that nested 11/17 (1011/1017, 5001) still draw the held stand picture (21/27).
Writes a JSON receipt and a source-versus-pack strip per view.
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

WALK = {'front': 11, 'back': 17}
STAND = {'front': 1001, 'back': 1007}
HELD = {'front': 21, 'back': 27}
ALIAS = {'front': 1011, 'back': 1017}


def frames(pack, index):
    out = []
    for t in anm.frame_times(pack, index):
        items = anm.evaluate(pack, index, t, nested=True)
        image, origin = anm.render_items(pack, items, palette_index=0)
        bbox = image.getchannel('A').getbbox()
        if not bbox:
            raise ValueError('blank render')
        out.append((t, image.crop(bbox), bbox[3] - origin[1]))
    return out


def same(a, b, tolerance=1):
    if a.size != b.size:
        return False
    if a.tobytes() == b.tobytes():
        return True
    delta = np.abs(np.asarray(a).astype(int) - np.asarray(b).astype(int))
    return int(delta.max()) <= tolerance


def strip(source, pack_frames_, path, title):
    ims = list(source) + list(pack_frames_)
    w = max(i.width for i in ims) + 8
    h = max(i.height for i in ims) + 18
    n = max(len(source), len(pack_frames_))
    out = Image.new('RGB', (w * n, h * 2 + 20), (34, 34, 38))
    d = ImageDraw.Draw(out)
    d.text((4, 3), title, fill='white')
    for r, row in enumerate((source, pack_frames_)):
        d.text((4, 20 + r * h), 'D1C source' if r == 0 else 'final pack', fill=(200, 200, 200))
        for c, im in enumerate(row):
            out.paste(im, (c * w + 4, 20 + r * h + 12), im)
    out.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--art', required=True, help='D1 Complete HD art root')
    ap.add_argument('--pack', required=True)
    ap.add_argument('--body', type=int, required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--out', required=True, help='receipt JSON; strips are written beside it')
    args = ap.parse_args()
    data = Path(args.pack).read_bytes()
    pack = anm.load(data)
    ids = {x['id']: x['index'] for x in anm.list_animations(pack)}
    walk, evidence = d1cart.shared_walk(Path(args.art), args.body)
    if walk is None:
        raise SystemExit('body has no shared bank 1')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(label=args.label, pack=str(args.pack), body=args.body,
                   pack_sha256=hashlib.sha256(data).hexdigest(),
                   source_tags=evidence['source_tags'], views={})
    ok = True
    for view in ('front', 'back'):
        source = [im.crop(im.getchannel('A').getbbox()) for im in walk[('walk', view)]]
        drawn = frames(pack, ids[WALK[view]])
        stand_bottom = frames(pack, ids[STAND[view]])[0][2]
        planted = max(b for _t, _i, b in drawn)
        alias = frames(pack, ids[ALIAS[view]])[0][1]
        held = frames(pack, ids[HELD[view]])[0][1]
        entry = dict(walk_id=WALK[view], stand_id=STAND[view], alias_id=ALIAS[view], held_id=HELD[view],
                     frames=len(drawn), source_frames=len(source),
                     key_times=[t for t, _, _ in drawn], source_times=evidence['row_times'][view],
                     frames_match_source=[same(a, b) for (_t, a, _b), b in zip(drawn, source)],
                     sizes=[[i.width, i.height] for _t, i, _b in drawn],
                     source_sizes=[[i.width, i.height] for i in source],
                     foot_line=dict(planted=planted, stand=stand_bottom, delta=planted - stand_bottom),
                     alias_matches_held=same(alias, held))
        entry['pass'] = (entry['frames'] == entry['source_frames'] and all(entry['frames_match_source'])
                         and abs(entry['foot_line']['delta']) <= 1 and entry['alias_matches_held'])
        ok &= entry['pass']
        receipt['views'][view] = entry
        strip(source, [i for _t, i, _b in drawn], out.parent / f'{out.stem}-{view}.png',
              f'{args.label} body {args.body} {view}: D1C {evidence["source_tags"][view]} vs pack {WALK[view]}')
    receipt['pass'] = ok
    out.write_text(json.dumps(receipt, indent=2) + '\n')
    for view, entry in receipt['views'].items():
        print(view, json.dumps({k: v for k, v in entry.items() if k not in ('sizes', 'source_sizes',
                                                                          'key_times', 'source_times',
                                                                          'frames_match_source')}))
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
