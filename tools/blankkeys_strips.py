#!/usr/bin/env python3
"""BLANKKEYS1: before / after key-by-key strips of changed motions (installed pack bank above, staged below).

    D5Modkit/.venv-macos/bin/python tools/blankkeys_strips.py --staged DIR/mods --out DIR [UNIT=BANK:ID,ID ...]
"""
import argparse
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
sys.dont_write_bytecode = True
from PIL import Image, ImageDraw  # noqa: E402

import bank_compare as bc  # noqa: E402
import roster_sheets as rs  # noqa: E402
from d5lib import anm  # noqa: E402

ANIME = rs.ANIME


def strip(fl, aid, bounds, cw=96):
    ts = anm.frame_times(fl, ("id", aid))
    out = []
    for t in ts:
        its = [i for i in anm.evaluate(fl, ("id", aid), t, nested=True) if i.cell.w > 0 and i.cell.h > 0]
        img = anm.render_items(fl, its, 0, bounds=bounds)[0] if its else Image.new("RGBA", (cw, cw), (0, 0, 0, 0))
        out.append((t, img, bool(its)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mods", type=Path, default=rs.GAME / "D5ModKit" / "mods")
    ap.add_argument("specs", nargs="+")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for spec in a.specs:
        pack, rest = spec.split("=")
        bank, ids = rest.split(":")
        p = f"files/{ANIME}/anm{int(bank):05d}.lzs"
        before, after = bc.load(a.mods / pack / p), bc.load(a.staged / pack / p)
        for aid in map(int, ids.split(",")):
            items = []
            for fl in (before, after):
                for t in anm.frame_times(fl, ("id", aid)):
                    items += anm.evaluate(fl, ("id", aid), t, nested=True)
            bounds = anm.item_bounds([i for i in items if i.cell.w > 0 and i.cell.h > 0])
            rows = [strip(fl, aid, bounds) for fl in (before, after)]
            w, h = rows[0][0][1].size if rows[0] else (96, 96)
            n = max(len(r) for r in rows)
            sheet = Image.new("RGBA", (n * w, 2 * (h + 14)), (60, 60, 70, 255))
            d = ImageDraw.Draw(sheet)
            for ri, row in enumerate(rows):
                for ci, (t, img, drawn) in enumerate(row):
                    x, y = ci * w, ri * (h + 14)
                    sheet.alpha_composite(img.resize((w, h)) if img.size != (w, h) else img, (x, y + 14))
                    d.text((x + 2, y + 1), f"{'before' if ri == 0 else 'after'} t={t}{'' if drawn else ' BLANK'}", fill=(255, 255, 255, 255))
            f = a.out / f"{pack}_{aid}.png"
            sheet.convert("RGB").save(f)
            print(f)


if __name__ == "__main__":
    main()
