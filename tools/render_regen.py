#!/usr/bin/env python3
"""Before/after renders for the REGEN rebuild: LIVE5_TEST3 pack vs the rebuilt pack vs the donor template.

    python tools/render_regen.py --before <bundle>/mods --after <bundle>/mods --out <playtest>/regen-renders

One sheet per class and animation, panels side by side on white, the sprite origin (y = 0, the tile the
game stands the unit on) as a blue line and each silhouette's own bottom as a red line, so "two bodies",
"floats" and "sinks" are readable without the game.  Output is game art: keep it in the private playtest
folder, never in the repo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, sprites       # noqa: E402
from d5lib.gamefs import GameFS      # noqa: E402

BOUNDS = (-320, -440, 320, 140)
SCALE = 2
PAD_TOP = 18
GAME = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete"


def load(path):
    with open(path, "rb") as f:
        return anm.load(f.read())


def view_of(fs, a, motion=True):
    if motion and sprites.needs_motion_set(a):
        a = anm.bind_motion_set(anm.AnmFile([sprites.motion_block(fs, 1)], [], []), 0, a)
    return a


def render(a, aid, t=0):
    items = anm.evaluate(a, ("id", aid), t)
    img, _ = anm.render_items(a, items, 0, bounds=BOUNDS)
    return np.asarray(img), items


def bottom(arr):
    m = np.asarray(arr)[..., 3] >= 128
    return int(np.nonzero(m)[0].max()) + BOUNDS[1] if m.any() else None


def panel(arr, label, ground=None):
    im = Image.fromarray(arr).resize((arr.shape[1] * SCALE, arr.shape[0] * SCALE), Image.NEAREST)
    bg = Image.new("RGBA", (im.width, im.height + PAD_TOP), (255, 255, 255, 255))
    bg.alpha_composite(im, (0, PAD_TOP))
    d = ImageDraw.Draw(bg)
    d.text((3, 3), label, fill=(0, 0, 0, 255))
    y0 = PAD_TOP + (-BOUNDS[1]) * SCALE
    d.line([(0, y0), (bg.width, y0)], fill=(0, 0, 200, 255))
    if ground is not None:
        yg = PAD_TOP + (ground - BOUNDS[1]) * SCALE
        d.line([(0, yg), (bg.width, yg)], fill=(200, 0, 0, 255))
    return bg


def sheet(rows, path, title):
    w = sum(r.width for r in rows) + 8 * (len(rows) - 1)
    h = max(r.height for r in rows) + 16
    out = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    ImageDraw.Draw(out).text((3, 2), title, fill=(0, 0, 0, 255))
    x = 0
    for r in rows:
        out.alpha_composite(r, (x, 16))
        x += r.width + 8
    out.convert("RGB").save(path)
    return path


def class_meta(mod_dir):
    cdir = os.path.join(mod_dir, "patches", "classes")
    for name in sorted(os.listdir(cdir)):
        if name.startswith("class_") and name.endswith(".json"):
            data = json.loads(open(os.path.join(cdir, name)).read())
            return int(data["sprite_family"]), int(data["template"])
    raise RuntimeError(f"no class json in {mod_dir}")


def anm_path(mod_dir, family):
    return os.path.join(mod_dir, "files", "Anime", "ANM_HI_JP.dat", "anm%05d.lzs" % family)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, help="mods dir of the shipped bundle (LIVE5_TEST3)")
    ap.add_argument("--after", required=True, help="mods dir of the rebuilt pack(s)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="+", default=["D4_Class_1230", "D4_Class_2190", "D4_Class_2020",
                                                  "D4_Class_2030", "D4_Class_2120", "D4_Class_2110",
                                                  "D4_Class_2130", "D4_Class_2010"])
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    fs = GameFS(GAME)
    written = []
    for mod in args.only:
        bdir, adir = os.path.join(args.before, mod), os.path.join(args.after, mod)
        fam, tpl = class_meta(adir)
        before, after = load(anm_path(bdir, fam)), load(anm_path(adir, fam))
        templ = view_of(fs, anm.parse(fs.read(sprites.sprite_vpath(fs, tpl, "EN"))), motion=False)
        tids = [x["id"] for x in anm.list_animations(templ)]
        for aid in (1, 101, 1001, 1007, 6001):
            if aid not in [x["id"] for x in anm.list_animations(after)]:
                continue
            barr, bitems = render(before, aid)
            aarr, aitems = render(after, aid)
            rows = [panel(barr, f"{mod} anm{aid} BEFORE: {len(bitems)} item(s), bottom y={bottom(barr)}", bottom(barr)),
                    panel(aarr, f"{mod} anm{aid} AFTER: {len(aitems)} item(s), bottom y={bottom(aarr)}", bottom(aarr))]
            taid = aid if aid in tids else (6001 if 6001 in tids else (1001 if 1001 in tids else None))
            if taid is not None:
                tarr, titems = render(templ, taid)
                rows.append(panel(tarr, f"vanilla {tpl} anm{taid} donor: {len(titems)} item(s), bottom y={bottom(tarr)}",
                                  bottom(tarr)))
            path = os.path.join(args.out, f"r-{mod}-anm{aid}.png")
            sheet(rows, path, f"{mod} animation {aid}: before | after | donor {tpl}")
            written.append(path)
            print("wrote", path, flush=True)
    print(f"{len(written)} sheet(s) in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
