#!/usr/bin/env python3
"""D4GAP1: one idle frame (anim id 1 front, 7 back) per built bank, as a labelled contact sheet.

    python tools/d4gap1_contact.py OUT.png LABEL=PATH/anmNNNNN.lzs [...]

Renders with `d5lib.anm.render_frame` (the Sprites & Colors preview evaluator); reads only the built files.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw  # noqa: E402

from d5lib import anm  # noqa: E402

CELL = 220


def idle(path, anim):
    a = anm.load(str(path))
    img = anm.render_frame(a, ("id", anim), 0)
    img.thumbnail((CELL - 8, CELL - 30), Image.LANCZOS)
    return img


def main(argv):
    out, items = Path(argv[1]), [x.split("=", 1) for x in argv[2:]]
    cols = 4
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * 2 * CELL, rows * CELL), (60, 90, 60, 255))
    draw = ImageDraw.Draw(sheet)
    for n, (label, path) in enumerate(items):
        x0, y0 = (n % cols) * 2 * CELL, (n // cols) * CELL
        draw.text((x0 + 4, y0 + 2), label, fill=(255, 255, 255, 255))
        for k, anim in enumerate((1, 7)):
            try:
                img = idle(path.replace("anmN", "anm"), anim)
                sheet.alpha_composite(img, (x0 + k * CELL + 4, y0 + 24))
            except Exception as exc:                      # noqa: BLE001
                draw.text((x0 + k * CELL + 4, y0 + 40), f"anim {anim}: {type(exc).__name__}", fill=(255, 200, 200, 255))
    sheet.save(out)
    print(out, sheet.size)


if __name__ == "__main__":
    main(sys.argv)
