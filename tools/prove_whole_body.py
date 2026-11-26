"""Converter-level proof for PTSPRITE S1: rebuild one class sprite in memory with and without the whole-body
pass, from the same prepared D4 art the installed pack was built from, and compare the stand picture.

    python tools/prove_whole_body.py [--out DIR]

Requires the prepared art tree (D4 export) and the game (read-only).  Writes a two-panel PNG per class:
"before" = ownanim.build(whole_body=False) -- what the installed packs were produced with -- and "after" =
ownanim.build(whole_body=True) -- what the current D4 importer does, i.e. the conversion a rebuild performs.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, frameconvert, ownanim, sourceimports, sprites, standground  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

GAME = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete"
PREP = "/Volumes/Data/Projects/D5/Research/d4-expansion-20261018/mvp-breadth/prepared-art"
LIB = "/Volumes/Data/CharForge-Backup/2026-10-16-211736/Art library/Disgaea 4 Complete+"
EDITION = "Disgaea 4 Complete+ PC EN"
BOUNDS = (-320, -440, 320, 140)


def build(fs, cid, family, template, monster, whole_body, normalize=False):
    prepared = sourceimports.read_prepared(os.path.join(PREP, str(cid)), LIB, edition=EDITION)
    resident = anm.parse(fs.read("Anime/ANM_HI_JP.dat/anm_resident.lzs"))
    motion = None if monster else next(b for b in resident.blocks if b.id == 1)
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, template, "EN")))
    while len(base.palettes) < 10:
        anm.set_palette(base, len(base.palettes), anm.get_palette(base, 0))
    sprite = ownanim.build(prepared["sequences"], base, motion, family, variants=[(0, 0, 0)],
                           prefer=frameconvert.MONSTER_ROWS if monster else None,
                           source_fallbacks=False, whole_body=whole_body)
    if normalize:                      # what the D4 importer now does after the build
        standground.normalize_stand_ground(sprite, base, log=print)
    return sprite


def stand(a):
    """(RGBA array of animation id 1 frame 0, number of body-sized draw items)"""
    if 1 not in [x["id"] for x in anm.list_animations(a)]:
        return None, 0
    items = anm.evaluate(a, ("id", 1), 0)
    img, _ = anm.render_items(a, items, 0, bounds=BOUNDS)
    areas = []
    for it in items:
        one, _ = anm.render_items(a, [it], 0, bounds=BOUNDS)
        areas.append(int((np.asarray(one)[..., 3] >= 128).sum()))
    big = max(areas) if areas else 0
    return np.asarray(img), sum(1 for v in areas if big and v >= 0.4 * big and v >= 3000)


def panel(arr, label, scale=2):
    im = Image.fromarray(arr).resize((arr.shape[1] * scale, arr.shape[0] * scale), Image.NEAREST)
    bg = Image.new("RGBA", (im.width, im.height + 18), (255, 255, 255, 255))
    bg.alpha_composite(im, (0, 18))
    d = ImageDraw.Draw(bg)
    d.text((3, 3), label, fill=(0, 0, 0, 255))
    return bg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/playtest/ptsprite-renders")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    fs = GameFS(GAME)
    for cid, family, template, monster, tag in [(1230, 1500, 1250, False, "kunoichi"),
                                                (2020, 2230, 2030, True, "orc")]:
        panels = []
        donor = anm.parse(fs.read(sprites.sprite_vpath(fs, template, "EN")))
        donor_ground = standground._ground(donor, 1)
        if donor_ground is None:
            donor_ground = next((g for g in (standground._ground(donor, i) for i in (6001, 1001, 1007))
                                 if g is not None), 0)
        for whole, normalize, label in ((False, False, "installed-pack conversion (whole_body=False)"),
                                        (True, False, "current converter, whole_body only"),
                                        (True, True, "current converter + stand-ground fix (what a rebuild now emits)")):
            sprite = build(fs, cid, family, template, monster, whole, normalize)
            arr, bodies = stand(sprite)
            if arr is None:
                print(tag, "no stand picture"); continue
            built_ground = standground._ground(sprite, 1)
            panels.append(panel(arr, "%s: %d body drawing(s), stand ground %s (donor %s)"
                                % (label, bodies, built_ground, donor_ground)))
            print("%s whole_body=%-5s normalize=%-5s stand bodies=%d ground=%s (donor %s)"
                  % (tag, whole, normalize, bodies, built_ground, donor_ground))
        w = sum(p.width for p in panels) + 8
        h = max(p.height for p in panels) + 16
        out = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        ImageDraw.Draw(out).text((3, 2), "S1 %s: stand picture from the prepared D4 art, converter output" % tag,
                                 fill=(0, 0, 0, 255))
        x = 0
        for p in panels:
            out.alpha_composite(p, (x, 16))
            x += p.width + 8
        path = os.path.join(a.out, "s1-converter-%s.png" % tag)
        out.convert("RGB").save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
