"""Still contact sheet for the D1CMOTION3 overlay: the lift and walk must have survived.

One row per pack (Strider, EDF Soldier, three unique packs) and one column per slot:
stand 1001, walk 11 (first key above the stand, t=16), lift 1101, lift alias 1131, hurt 21 — all
from the **built TEST29** pack, on rank 0. Compare against
`Builds/LIFTSLOT1-20261101/review/lift-check-*-front.png` (lift) and
`Builds/UNIQWALK1-20261101/review/contact-all.png` (walk/lift per unique).

  python tools/d1cmotion2_contact.py [--out PNG]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import d1cmotion2_base as base  # noqa: E402
from striderlift_render_diff import pose, read  # noqa: E402
from d5lib import anm  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

MODS = base.ROOT / 'Builds/D1CMOTION2-20261101/mods'
ROWS = [('D1C_Class_11390', 'anm01540.lzs', 'Strider'),
        ('D1C_Class_11400', 'anm01530.lzs', 'EDF Soldier'),
        ('D1C_Unique_2300', 'anm00533.lzs', 'Unique 2300'),
        ('D1C_Unique_2910', 'anm00886.lzs', 'Unique 2910'),
        ('D1C_Unique_5590', 'anm00603.lzs', 'Unique 5590')]
COLS = [(1001, 0, 'stand 1001'), (11, 16, 'walk 11 t16'), (1101, 0, 'lift 1101'),
        (1131, 0, 'lift alias 1131'), (21, 0, 'hurt 21')]
W, H, LEFT, TOP = 130, 200, 170, 34


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(base.ROOT / 'Builds/D1CMOTION2-20261101/review/contact-test29.png'))
    args = ap.parse_args()
    sheet = Image.new('RGB', (LEFT + len(COLS) * W + 6, TOP + len(ROWS) * H), (40, 40, 44))
    draw = ImageDraw.Draw(sheet)
    for col, (_, _, title) in enumerate(COLS):
        draw.text((LEFT + col * W + 3, 6), title, fill='white')
    for row, (mod, bank, label) in enumerate(ROWS):
        path = MODS / mod / base.REL / bank
        draw.text((4, TOP + row * H + 10), label, fill='white')
        doc, sha = read(path)
        ids = {x['id']: x['index'] for x in anm.list_animations(doc)}
        for col, (aid, t, _) in enumerate(COLS):
            if aid not in ids:
                draw.text((LEFT + col * W + 3, TOP + row * H + 10), 'MISSING', fill='red')
                continue
            still, _ = pose(doc, ids[aid], t, 0)
            still.thumbnail((W - 8, H - 12))
            x = LEFT + col * W + (W - still.width) // 2
            y = TOP + row * H + H - 5 - still.height
            sheet.paste(still, (x, y), still)
        for col in range(len(COLS) + 1):
            draw.line((LEFT + col * W, TOP + row * H, LEFT + col * W, TOP + (row + 1) * H),
                      fill=(65, 65, 70))
        draw.line((0, TOP + (row + 1) * H - 1, sheet.width, TOP + (row + 1) * H - 1), fill=(70, 70, 75))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(out)


if __name__ == '__main__':
    main()
