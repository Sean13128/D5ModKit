"""Render the PTSPRITE before/after evidence frames (offline, no game) into the project playtest folder.

    python tools/render_ptsprite.py OUTDIR

Each sheet is one row per source (built pack, vanilla template, predicted fix) for one class and one animation,
on a white background, with the sprite origin (y = 0, the tile the game stands the character on) drawn as a
line, so float/sink and duplicate copies are readable without the game.  "Predicted" panels are *not* built
files: they show what the identified fix leaves -- the whole-body pass keeping only the main body track, and
the ground line moved onto the template's -- as an illustration of the intended result.

The output contains game art: write it only under the project's private playtest folder, never into the repo.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, sprites  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

BOUNDS = (-320, -440, 320, 140)
MODS = "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods"
SCALE = 2
PAD_TOP = 18


def load(p):
    with open(p, "rb") as f:
        return anm.load(f.read())


def view_of(fs, a, motion=True):
    if motion and sprites.needs_motion_set(a):
        a = anm.bind_motion_set(anm.AnmFile([sprites.motion_block(fs, 1)], [], []), 0, a)
    return a


def render(a, aid, t):
    items = anm.evaluate(a, ("id", aid), t)
    img, _ = anm.render_items(a, items, 0, bounds=BOUNDS)
    return np.asarray(img), items


def panel(arr, label, ground=None):
    im = Image.fromarray(arr).resize((arr.shape[1] * SCALE, arr.shape[0] * SCALE), Image.NEAREST)
    bg = Image.new("RGBA", (im.width, im.height + PAD_TOP), (255, 255, 255, 255))
    bg.alpha_composite(im, (0, PAD_TOP))
    d = ImageDraw.Draw(bg)
    d.text((3, 3), label, fill=(0, 0, 0, 255))
    y0 = PAD_TOP + (-BOUNDS[1]) * SCALE
    d.line([(0, y0), (bg.width, y0)], fill=(0, 0, 200, 255))          # the sprite origin the game stands on
    if ground is not None:
        yg = PAD_TOP + (ground - BOUNDS[1]) * SCALE
        d.line([(0, yg), (bg.width, yg)], fill=(200, 0, 0, 255))      # the silhouette's own bottom
    return bg


def sheet(rows, path, title):
    """panels side by side (built | vanilla | predicted), one title line on top"""
    w = sum(r.width for r in rows) + 8 * (len(rows) - 1)
    h = max(r.height for r in rows) + 16
    out = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(out)
    draw.text((3, 2), title, fill=(0, 0, 0, 255))
    x = 0
    for r in rows:
        out.alpha_composite(r, (x, 16))
        x += r.width + 8
    out.convert("RGB").save(path)
    print("wrote", path)


def bottom(arr):
    m = np.asarray(arr)[..., 3] >= 128
    return int(np.nonzero(m)[0].max()) + BOUNDS[1] if m.any() else None


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/playtest/ptsprite-renders"
    os.makedirs(out, exist_ok=True)
    fs = GameFS("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
    for mod, fam, tpl, anims, tag, title in [
            ("D4_Class_1230", 1500, 1250, (1, 6001), "kunoichi", "S1 Kunoichi: stand picture (id 1) and idle (6001)"),
            ("D4_Class_2190", 2620, 2130, (1, 1001), "rifledemon", "S1 Rifle Demon: stand picture (id 1) and idle (1001)"),
            ("D4_Class_2020", 2230, 2030, (1, 1001), "orc", "S2 Orc: stand and idle"),
            ("D4_Class_2030", 2240, 2080, (1, 1001), "wingedwarrior", "S2 Winged Warrior: stand and idle"),
            ("D4_Class_2130", 2340, 2190, (1, 1001), "mysticbeast", "S2 Mystic Beast: stand and idle"),
            ("D4_Class_2120", 2330, 2210, (1, 1001), "death", "S2 Death: stand and idle"),
            ("D4_Class_2110", 2320, 2080, (1, 1001), "roc", "S2 Roc: stand and idle"),
            ("D4_Class_2010", 2220, 2060, (1, 1001), "sludge", "S2 Sludge (control, healthy): stand and idle")]:
        built = load(os.path.join(MODS, mod, "files/Anime/ANM_HI_JP.dat/anm%05d.lzs" % fam))
        templ = view_of(fs, anm.parse(fs.read(sprites.sprite_vpath(fs, tpl, "EN"))), motion=False)
        for aid in anims:
            if aid not in [x["id"] for x in anm.list_animations(built)]:
                continue
            arr, items = render(built, aid, 0)
            rows = [panel(arr, "%s anm%d  built: %d draw item(s), bottom y=%s" % (mod, aid, len(items), bottom(arr)),
                          bottom(arr))]
            tids = [x["id"] for x in anm.list_animations(templ)]
            taid = aid if aid in tids else (6001 if 6001 in tids else (1001 if 1001 in tids else None))
            tarr = None
            if taid is not None:
                tarr, titems = render(templ, taid, 0)
                rows.append(panel(tarr, "vanilla %d anm%d  template: %d item(s), bottom y=%s"
                                  % (tpl, taid, len(titems), bottom(tarr)), bottom(tarr)))
            if len(items) > 1 and bottom(arr) is not None and tarr is not None and bottom(tarr) is not None:
                if True:
                    # predicted fix: keep only the largest drawing (whole-body pass) and stand it on the
                    # template's ground line
                    areas = []
                    for it in items:
                        one, _ = anm.render_items(built, [it], 0, bounds=BOUNDS)
                        areas.append(int((np.asarray(one)[..., 3] >= 128).sum()))
                    main = items[int(np.argmax(areas))]
                    one, _ = anm.render_items(built, [main], 0, bounds=BOUNDS)
                    pred = np.asarray(one)
                    shift = int(bottom(tarr) - bottom(pred)) if bottom(pred) is not None else 0
                    if shift:
                        pred = np.roll(pred, shift, axis=0)
                    rows.append(panel(pred, "predicted fix: main body track only, ground on the template's (y=%s)"
                                      % bottom(tarr), bottom(tarr)))
            sheet(rows, os.path.join(out, "s-%s-anm%d.png" % (tag, aid)), title)
    print("done")


if __name__ == "__main__":
    main()
