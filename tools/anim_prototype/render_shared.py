"""Render the initial-binding-state Kunoichi experiment for offline review."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
from d5lib import anm, d4source
from prove_shared import disabled_view
from shared_tracks import build

OUT = Path('/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/playtest/anim-renders')
BOUNDS = (-240, -360, 240, 120)
data = d4source.D4Data('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+')
bank = disabled_view(build(data.anm(1230), data.anm(1), bank_id=1500))
metadata = {}
for label, aid in {'wheel-1': 1, 'stand-1001': 1001, 'walk': 21, 'attack': 2001,
                   'damage': 1021, 'special': 4001, 'idle': 6001}.items():
    info = next(x for x in anm.list_animations(bank) if x['id'] == aid)
    end = (info['loop'][1] if info['loop'] else info['length']) or 1
    if aid == 1001 and end == 1:
        nested = next(x for x in anm.list_animations(bank) if x['id'] == 6001)
        end = (nested['loop'][1] if nested['loop'] else nested['length']) or 1
    frames, visible = [], False
    for tick in range(0, min(int(end) + 1, 180), 2):
        items = anm.evaluate(bank, ('id', aid), tick, nested=True)
        visible |= bool(items)
        im = anm.render_items(bank, items, 0, bounds=BOUNDS)[0]
        bg = Image.new('RGBA', im.size, 'white')
        bg.alpha_composite(im)
        ImageDraw.Draw(bg).line((0, -BOUNDS[1], bg.width, -BOUNDS[1]), fill='#7f91a6')
        frames.append(bg.convert('RGB'))
    name = f'1230-{label}-prototype.gif'
    if visible:
        frames[0].save(OUT / name, save_all=True, append_images=frames[1:],
                       duration=[40 if i % 3 == 0 else 30 for i in range(len(frames))],
                       loop=0, optimize=True, disposal=2)
    metadata[label] = {'id': aid, 'length': info['length'], 'loop': info['loop'],
                       'samples': len(frames), 'drawable': visible}
(OUT / 'kunoichi-prototype-metadata.json').write_text(json.dumps(metadata, indent=2))
