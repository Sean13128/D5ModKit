"""Render a class's wheel (Recruiter / idle) animations to PNG straight from a mod folder -- no game.

    python tools/render_wheel_idle.py MODFOLDER [--template N] [--out DIR] [--tag NAME]
    python tools/render_wheel_idle.py --sprite 1250 [--out DIR] [--tag vanilla-1250]

MODFOLDER   a built class mod (reads patches/classes/class_*.json for `sprite_family`/`template` and the
            built sprite from files/Anime/ANM_HI_JP.dat/anm<sprite_family>.lzs, falling back to the game's
            own file when the mod does not carry one)
--sprite N  render a sprite number straight from the game (a vanilla class, for comparison)
--game PATH the game folder (default: the path the kit's finder guesses, see d5lib.paths)

What it writes, per animation: a horizontal strip of every key frame at --scale, on a white background
(no transparency added -- Sean's 2026-10-27 preference), and a JSON dump of every draw item (layer node,
source cell rect, screen quad, texture) so duplicated or misplaced layers can be read as numbers, not only
looked at.  It also prints, per frame: drawn layers, the two largest layers' areas and screen boxes, and the
silhouette's ground line (bottom y) -- the numbers the PT1027 S1/S2 findings are about.

Read-only: it never writes into the mod, the game or the installed kit; PNG/JSON go to --out
(default playtest/ptsprite-renders/ next to this repo).
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, paths  # noqa: E402
from d5lib import sprites  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

# the idle animations a class shows on the Recruiter wheel / in the creation screens
IDLES = (1, 7, 1001, 1007, 6001, 6007)
BOUNDS = (-320, -440, 320, 140)


def game_fs(game=None):
    return GameFS(game or paths.require_game_dir())


def load_sprite(fs, number):
    return anm.parse(fs.read(sprites.sprite_vpath(fs, number, "EN")))


def mod_sprite(fs, mod):
    """(AnmFile, origin) for the mod's built class sprite, or None when the mod carries no sprite file"""
    files = os.path.join(mod, "files", "Anime", "ANM_HI_JP.dat")
    if not os.path.isdir(files):
        return None, None
    names = sorted(n for n in os.listdir(files) if n.startswith("anm") and n.endswith(".lzs"))
    # the built sprite is the lowest number in the pack (anm01500 for family 1500; anm11250+ are own animations)
    nums = sorted(int(n[3:8]) for n in names if n[3:8].isdigit())
    if not nums:
        return None, None
    num = nums[0]
    path = os.path.join(files, "anm%05d.lzs" % num)
    with open(path, "rb") as f:
        return anm.load(f.read()), path


def view_of(fs, a, humanoid):
    if humanoid or sprites.needs_motion_set(a):
        motion = anm.bind_motion_set(anm.AnmFile([sprites.motion_block(fs, 1)], [], []), 0, a)
        return [a, motion]
    return [a]


class View:
    def __init__(self, files):
        self.at = {}
        for f in files:
            for x in anm.list_animations(f):
                self.at.setdefault(x["id"], (f, x))

    def ids(self):
        return sorted(self.at)

    def render(self, aid, t):
        a, x = self.at[aid]
        items = anm.evaluate(a, x["index"], t)
        img, origin = anm.render_items(a, items, 0, bounds=BOUNDS)
        return np.asarray(img), items

    def times(self, aid):
        a, x = self.at[aid]
        return anm.frame_times(a, x["index"])


def describe(items, img):
    m = img[..., 3] >= 128
    out = []
    for it in items:
        q = it.quad
        area = abs((q[1][0] - q[0][0]) * (q[3][1] - q[0][1]) - (q[1][1] - q[0][1]) * (q[3][0] - q[0][0]))
        out.append(dict(node=it.node, depth=it.depth, cell=[it.cell.x, it.cell.y, it.cell.w, it.cell.h],
                        tex=it.tex_global, bbox=[round(float(v), 1) for v in
                                                  (q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max())],
                        area=round(float(area), 1)))
    ground = int(np.nonzero(m)[0].max()) + BOUNDS[1] if m.any() else None
    return dict(layers=out, drawn=len(out), px=int(m.sum()), ground_y=ground)


def strip(view, aid, scale, label):
    times = view.times(aid)
    frames, rows = [], []
    for t in times:
        img, items = view.render(aid, t)
        frames.append(Image.fromarray(img))
        rows.append(dict(t=t, **describe(items, img)))
    w = max(f.width for f in frames)
    h = max(f.height for f in frames)
    pad = 34
    out = Image.new("RGBA", (w * len(frames), h + pad), (255, 255, 255, 255))
    d = ImageDraw.Draw(out)
    d.text((4, 4), "%s  anm %s  frames %s" % (label, aid, [r["t"] for r in rows]), fill=(0, 0, 0, 255))
    for i, f in enumerate(frames):
        out.alpha_composite(f, (i * w, pad))
        d.rectangle([i * w, pad, i * w + w - 1, pad + h - 1], outline=(200, 200, 200, 255))
    return out, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mod", nargs="?")
    ap.add_argument("--sprite", type=int)
    ap.add_argument("--template", type=int)
    ap.add_argument("--game")
    # renders are game art: the project playtest folder, never the repo
    ap.add_argument("--out", default="/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/playtest/ptsprite-renders")
    ap.add_argument("--tag")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--anims", default="")
    a = ap.parse_args()
    fs = game_fs(a.game)
    os.makedirs(a.out, exist_ok=True)

    humanoid = True
    label = a.tag or ""
    if a.mod:
        mod = os.path.abspath(a.mod)
        cls = None
        cdir = os.path.join(mod, "patches", "classes")
        if os.path.isdir(cdir):
            for n in sorted(os.listdir(cdir)):
                if n.startswith("class_") and n.endswith(".json"):
                    cls = json.load(open(os.path.join(cdir, n), encoding="utf-8"))
                    break
        if cls is None:
            raise SystemExit("no patches/classes/class_*.json in %s" % mod)
        sprite, origin = mod_sprite(fs, mod)
        if sprite is None:
            sprite, origin = load_sprite(fs, cls.get("sprite_family", cls.get("template")))
        humanoid = cls.get("kind", "humanoid") != "monster"
        label = label or os.path.basename(mod)
        a.template = a.template or cls.get("template")
        print("mod %s: family %s template %s kind %s -- sprite from %s"
              % (mod, cls.get("sprite_family"), cls.get("template"), cls.get("kind"), origin))
    else:
        if a.sprite is None:
            raise SystemExit("pass a mod folder or --sprite N")
        sprite = load_sprite(fs, a.sprite)
        origin = sprites.sprite_vpath(fs, a.sprite, "EN")
        label = label or "vanilla-%d" % a.sprite
        print("vanilla sprite %d from %s" % (a.sprite, origin))

    view = View(view_of(fs, sprite, humanoid))
    want = [int(x) for x in a.anims.split(",") if x.strip()] or [i for i in IDLES if i in view.at]
    if a.template and a.template != a.sprite:
        tv = View(view_of(fs, load_sprite(fs, a.template), humanoid))
    else:
        tv = None

    report = dict(label=label, sprite=getattr(a, "sprite", None), template=a.template,
                  animations={}, template_animations={})
    for aid in want:
        img, rows = strip(view, aid, a.scale, label)
        name = "%s-anm%d.png" % (label, aid)
        img.save(os.path.join(a.out, name))
        report["animations"][str(aid)] = rows
        print("%-28s frames=%-3d layers/frame=%s ground=%s -> %s"
              % ("anm%d" % aid, len(rows), [r["drawn"] for r in rows], [r["ground_y"] for r in rows], name))
        if tv and aid in tv.at:
            timg, trows = strip(tv, aid, a.scale, "vanilla-%s" % a.template)
            timg.save(os.path.join(a.out, "%s-anm%d.png" % ("vanilla-%s" % a.template, aid)))
            report["template_animations"][str(aid)] = trows
            print("%-28s frames=%-3d layers/frame=%s ground=%s (+ vanilla render)"
                  % ("  template anm%d" % aid, len(trows), [r["drawn"] for r in trows],
                     [r["ground_y"] for r in trows]))
    with open(os.path.join(a.out, "%s.json" % label), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("wrote %s/%s.json" % (a.out, label))


if __name__ == "__main__":
    main()
