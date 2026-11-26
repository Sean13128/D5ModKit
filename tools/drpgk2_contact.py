#!/usr/bin/env python3
"""Contact sheet for a built DRPG costume look, through the Kit's own renderer (card K2).

    python tools/drpgk2_contact.py --mod <built mod folder> --art 14940 --base-art 14930 \
        --out Builds/DRPGK2-<date>/Zed-costume-contact.png

Renders with `d5lib.anm.render_frame` / `render_items` -- the evaluator the Kit's Sprites & Colors live preview
(`d5gui/pages/sprites.py`) draws with -- so the sheet shows the same pixels the preview shows.  It reads only the
built mod folder (anm files, the face picture the build painted into resident block 9017) and never the game, the
installed kit or a save.  Prior art: `d5gui/pages/characters.py:1319` (anm.render_frame + palette + scale),
`tools/qa_sprite.py`, CORERPG1's contact sheets.

Layout contract (K2B): every picture is drawn inside its own declared box, anchored top-left of its row band,
scaled down if it does not fit.  Nothing may be composited outside its box -- the standing picture is 256x512
(2 cells tall), and K2's sheet placed it with cell-sized maths, so it was drawn 100 px *above* its row and
over the costume body cell (it looked like three Zed figures).  `layout()` raises instead of overflowing now.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import anm  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

ANIME = Path("files/Anime/ANM_HI_JP.dat")
CELL = 200
PAD = 8
HEAD = 18


def pick(paths, wanted):
    """[(label, anm file, animation id)] for the animation ids in `wanted` the file has."""
    a = anm.load(str(paths))
    have = {x["id"]: x["index"] for x in anm.list_animations(a)}
    return [(label, a, have[wid]) for wid, label in wanted if wid in have]


def pick_nonblank(paths):
    """the first animation of a file whose first frame has pixels (a portrait's leading key is empty)."""
    a = anm.load(str(paths))
    for x in anm.list_animations(a):
        img = anm.render_frame(a, x["index"], 0)
        if img.getextrema()[3][1] > 0:
            return a, x["index"]
    return None


def render_texture(a, size):
    img = anm.texture_to_image(a, 0, 0).convert("RGBA")
    img.thumbnail((size, size * 2), Image.LANCZOS)
    return img


def render(a, index, size):
    img = anm.render_frame(a, index, 0)
    img.thumbnail((size, size), Image.LANCZOS)
    return img


def layout(rows, cells, cell=CELL, pad=PAD, head=HEAD):
    """Geometry for the sheet: one band per row plus one for the single pictures.

    Returns (width, height, bands) where each band is
    ``{"label": str, "y": int, "height": int, "boxes": [(x, y, w, h)]}``.
    A band is as tall as its tallest picture, never less than `cell`; the pictures band is
    2 cells tall because the standing picture is a 256x512 texture.
    """
    cols = max([len(v) for _, v in rows] + [1])
    pictures_h = max([img.height for _, img in cells] + [cell])
    bands = []
    y = 26
    for label, items in rows:
        bands.append({"label": label, "y": y + head, "height": cell,
                      "boxes": [(pad + i * (cell + pad), y + head, cell, cell) for i in range(len(items))]})
        y += head + cell + pad
    if cells:
        bands.append({"label": "", "y": y + head, "height": pictures_h,
                      "boxes": [(pad + i * (cell + pad), y + head, cell, pictures_h) for i in range(len(cells))]})
        y += head + pictures_h + pad
    width = pad + max(cols, len(cells)) * (cell + pad)
    return width, y + 4, bands


def place(sheet, img, box):
    """Fit `img` inside `box`, centred, and refuse to draw outside it."""
    x, y, w, h = box
    if w <= 0 or h <= 0 or img.width <= 0 or img.height <= 0:
        raise ValueError(f"cannot place picture {img.size} in cell {box}")
    if img.width > w or img.height > h:  # scale down; never overflow the box
        img = img.copy()
        img.thumbnail((w, h), Image.LANCZOS)
    px = x + (w - img.width) // 2
    py = y + (h - img.height) // 2
    if not (x <= px and y <= py and px + img.width <= x + w and py + img.height <= y + h):
        raise ValueError(f"picture {img.size} does not fit its cell {box}")
    sheet.alpha_composite(img, (px, py))


def verify_rows(sheet, bands):
    """Read the composed sheet back and prove no picture left its band.

    Every picture is placed inside its band by `place()`; this reads the pixels to prove it,
    because K2's sheet looked plausible while the standing picture was drawn a whole row too
    high.  Returns per-band non-background pixel counts; raises if a band is empty or if any
    padding row between bands carries picture pixels.
    """
    import numpy as np
    a = np.asarray(sheet.convert("RGB"), dtype=np.int16)
    bg = np.array([24, 24, 28], dtype=np.int16)
    ink = np.abs(a - bg).sum(2) > 18
    counts = []
    for band in bands:
        y0, y1 = band["y"] - HEAD, band["y"] + band["height"]
        counts.append(int(ink[y0:y1].sum()))
    gaps = []
    for prev, nxt in zip(bands, bands[1:]):
        gap = ink[prev["y"] + prev["height"]:nxt["y"] - HEAD]
        gaps.append(int(gap.sum()))
    for band, count in zip(bands, counts):
        if band["boxes"]:
            boxes = band["boxes"]
            region = ink[band["y"]:band["y"] + band["height"]]
            cols = region.any(0)
            filled = [i for i, ok in enumerate(cols) if ok]
            if filled and (min(filled) < boxes[0][0] or max(filled) > boxes[-1][0] + boxes[-1][2]):
                raise ValueError("a picture was drawn outside its band's columns")
            if count == 0:
                raise ValueError(f"band at y={band['y']} is empty")
    if any(gaps):
        raise ValueError(f"picture pixels in the padding rows between bands: {gaps}")
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mod", type=Path, required=True)
    ap.add_argument("--base-art", type=int, required=True, help="the base character's sprite number (its anm)")
    ap.add_argument("--art", type=int, required=True, help="the costume's leased art number N")
    ap.add_argument("--slot", type=int, help="the costume's class id (for the face picture; default: read outfits.json)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default="")
    args = ap.parse_args(argv)
    anime = args.mod / ANIME
    n = args.art
    slot = args.slot
    if slot is None:
        import json
        pairs = json.loads((args.mod / "patches/outfits/outfits.json").read_text()).get("pairs") or []
        colours = json.loads((args.mod / "patches/outfits/outfits.json").read_text()).get("colours") or {}
        slot = next((int(b) for a, b in pairs if int(colours.get(str(b), -1)) == n), None)
    rows = []
    for label, art in (("base", args.base_art), ("costume", n)):
        f = anime / f"anm{art:05d}.lzs"
        if not f.is_file():
            rows.append((label, [("missing", None)]))
            continue
        got = pick(f, [(1, "stand front"), (7, "stand back"), (11, "walk front"), (17, "attack")])
        rows.append((f"body anm{art} ({label})", got))
    cells = []
    stand = anime / f"anm{n + 2:05d}.lzs"
    if stand.is_file():
        # N+2 is a 256x512 front/back picture painted into its texture (block cell 0x0, no animation):
        # render the texture the way the build painted it.
        a = anm.load(str(stand))
        cells.append((f"standing anm{n + 2} (texture)", render_texture(a, CELL)))
    port = anime / f"anm{n + 10000:05d}.lzs"
    if port.is_file():
        got = pick_nonblank(port)
        if got:
            a, index = got
            cells.append((f"portrait / cut-in anm{n + 10000}", render(a, index, CELL)))
    face = args.mod / "patches/outfits" / f"face_{slot or 0}.png"
    if face.is_file():
        img = Image.open(face).convert("RGBA")
        img.thumbnail((CELL, CELL), Image.LANCZOS)
        cells.append((f"face (resident 9017, painted from this)", img))
    rows = [(label, [g for g in got if g[1] is not None]) for label, got in rows]
    width, height, bands = layout(rows, cells)
    sheet = Image.new("RGBA", (width, height), (24, 24, 28, 255))
    d = ImageDraw.Draw(sheet)
    if args.title:
        d.text((PAD, 4), args.title, fill=(235, 235, 235, 255))
    for band, (label, items) in zip(bands, rows):
        d.text((PAD, band["y"] - HEAD), label, fill=(200, 200, 210, 255))
        for (name, a, index), box in zip(items, band["boxes"]):
            place(sheet, render(a, index, CELL), box)
            d.text((box[0] + 2, box[1] + box[3] - 12), name, fill=(160, 160, 170, 255))
    if cells:
        band = bands[len(rows)]
        for (name, img), box in zip(cells, band["boxes"]):
            place(sheet, img, box)
            d.text((box[0] + 2, box[1] + box[3] - 12), name, fill=(160, 160, 170, 255))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    verify_rows(sheet, bands)  # refuses a sheet whose cells overlap, before it is written
    sheet.convert("RGB").save(args.out)
    print(f"{args.out} ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
