"""DRPG-K4 contact sheet: the 8 mixed identities, base body vs the kind-changing costume's body (kit renderer).

    python tools/drpgk4_contact.py Builds/DRPGK4-20261106 --out OUT.png

Reads each built pack's outfits.json (pairs / colours / bodies) and renders, per identity, the base body's attack
animation and the costume's attack animation with d5lib.anm.render_frame -- the same evaluator the kit's Sprites &
Colors preview draws with -- plus the costume's standing picture.  verify_rows() re-reads the sheet and refuses one
whose bands overlap or whose cells are empty.
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PIL import Image, ImageDraw  # noqa: E402

import drpgk2_contact as k2  # noqa: E402
from d5lib import anm  # noqa: E402

CELL = 200


def row_info(mod):
    d = json.loads((mod / "patches/outfits/outfits.json").read_text())
    bodies = {int(k): int(v) for k, v in (d.get("bodies") or {}).items()}
    colours = {int(k): int(v) for k, v in (d.get("colours") or {}).items()}
    pairs = [tuple(map(int, p)) for p in d.get("pairs") or []]
    slot = next((b for a, b in pairs if b in bodies), None)
    base = next((a for a, b in pairs if b == slot), None)
    return dict(slot=slot, base=base, art=colours.get(slot), body=bodies.get(slot))


def art_row(anime, n, label):
    f = anime / f"anm{n:05d}.lzs"
    if not f.is_file():
        raise SystemExit(f"missing {f}")
    a = anm.load(str(f))
    have = {x["id"]: x["index"] for x in anm.list_animations(a)}
    got = [(name, a, have[wid]) for wid, name in ((17, "attack"), (11, "walk f"), (1, "stand f")) if wid in have]
    return label, got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="the import output dir (contains drpg/mods)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    mods = sorted((args.root / "drpg/mods").iterdir())
    rows, cells = [], []
    for mod in mods:
        info = row_info(mod)
        if info["slot"] is None:
            continue
        anime = mod / "files/Anime/ANM_HI_JP.dat"
        base_art = None
        ch = json.loads((mod / "patches/db/char.dat.json").read_text())
        for r in ch.get("added", []):
            if int(r["id"]) == int(info["base"]):
                base_art = int(r["sprite_id"])
        if base_art is None:
            base_art = int(json.loads((mod / "patches/outfits/outfits.json").read_text())["own_sprites"][0])
        label = f"{mod.name}  look {info['art']} on row {info['base']}"
        rows.append(art_row(anime, base_art, f"{label}  base anm{base_art}"))
        rows.append(art_row(anime, info["art"],
                            f"{label}  costume anm{info['art']} (body {'monster' if 2000 <= info['body'] < 3000 else 'humanoid'} {info['body']})"))
        stand = anime / f"anm{info['art'] + 2:05d}.lzs"
        if stand.is_file():
            cells.append((f"anm{info['art'] + 2} standing", k2.render_texture(anm.load(str(stand)), CELL)))
    width, height, bands = k2.layout(rows, cells)
    sheet = Image.new("RGBA", (width, height), (24, 24, 28, 255))
    d = ImageDraw.Draw(sheet)
    d.text((k2.PAD, 6), "DRPG-K4: the 8 mixed identities, base body vs the costume that changes body kind",
           fill=(235, 235, 235, 255))
    for band, (label, items) in zip(bands, rows):
        d.text((k2.PAD, band["y"] - k2.HEAD), label, fill=(200, 200, 210, 255))
        for (name, a, index), box in zip(items, band["boxes"]):
            k2.place(sheet, k2.render(a, index, CELL), box)
            d.text((box[0] + 2, box[1] + box[3] - 12), name, fill=(160, 160, 170, 255))
    if cells:
        band = bands[len(rows)]
        for (name, img), box in zip(cells, band["boxes"]):
            k2.place(sheet, img, box)
            d.text((box[0] + 2, box[1] + box[3] - 12), "standing", fill=(160, 160, 170, 255))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    k2.verify_rows(sheet, bands)
    sheet.save(args.out)
    print(f"{args.out}  {sheet.width}x{sheet.height}  {len(rows)} bands")


if __name__ == "__main__":
    main()
