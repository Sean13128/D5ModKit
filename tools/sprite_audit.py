"""Audit every built class/monster sprite in a mods folder against its donor template -- no game.

    python tools/sprite_audit.py MODS_DIR [--out FILE.json] [--only D4_Class_1230,...]

For each pack that ships a built sprite (patches/classes/class_*.json: `sprite_family`, `template`):

  stand      animation id 1 (the picture the creation/class-change screens draw): number of draw items and
             how many of them are body-sized (>=40% of the largest, >=3000 px).  >1 body = the S1 finding:
             the same complete source pose on two donor tracks.
  idle       animations 1001/1007/6001/6007: distinct drawings, layers per frame.
  ground     per idle frame the silhouette's bottom y in sprite coordinates (0 = the sprite origin, the point
             the game stands on the tile).  Compared with the donor template's own value: a delta that does not
             drift with the pose is an anchor offset (the import sits high or low); a delta that swings frame to
             frame is a per-frame ground point error.
  height     silhouette height of the widest idle frame vs the template's (D4 art is drawn at its own scale).

It reads the mod folder for the built file and asks GameFS for the *template* file.  The template numbers are
donor sprites the packs do not overwrite (12xx class screens, 2xxx monsters), so those reads are the game's own
art.  Writes nothing except --out.  Read-only on the game and the installed kit.
"""
import argparse
import json
import os
import sys

import numpy as np

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

from d5lib import anm, sprites  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

BOUNDS = (-320, -440, 320, 140)
ALPHA = 128
STAND, IDLE = 1, (1001, 1007, 6001, 6007)


def mask_stats(img):
    m = np.asarray(img)[..., 3] >= ALPHA
    if not m.any():
        return dict(px=0)
    ys, xs = np.nonzero(m)
    return dict(px=int(m.sum()), bottom=int(ys.max()) + BOUNDS[1], top=int(ys.min()) + BOUNDS[1],
                height=int(ys.max() - ys.min()))


class View:
    def __init__(self, files):
        self.at = {}
        for a in files:
            for x in anm.list_animations(a):
                self.at.setdefault(x["id"], (a, x))

    def has(self, aid):
        return aid in self.at

    def frame(self, aid, t):
        a, x = self.at[aid]
        items = anm.evaluate(a, x["index"], t)
        img, _ = anm.render_items(a, items, 0, bounds=BOUNDS)
        areas = []
        for it in items:
            one, _ = anm.render_items(a, [it], 0, bounds=BOUNDS)
            areas.append(int((np.asarray(one)[..., 3] >= ALPHA).sum()))
        big = max(areas) if areas else 0
        return dict(items=len(items), body_layers=sum(1 for v in areas if big and v >= 0.4 * big and v >= 3000),
                    areas=areas, **mask_stats(img))

    def times(self, aid):
        a, x = self.at[aid]
        return anm.frame_times(a, x["index"])


def load(path):
    with open(path, "rb") as f:
        return anm.load(f.read())


def view_of(fs, a, humanoid, motion=None):
    files = [a]
    if motion or sprites.needs_motion_set(a):
        blocks = motion if motion is not None else [sprites.motion_block(fs, 1)]
        files.append(anm.bind_motion_set(anm.AnmFile(list(blocks), [], []), 0, a))
    return View(files)


def audit_pack(fs, root, mod, motion):
    base = os.path.join(root, mod)
    cdir = os.path.join(base, "patches", "classes")
    cls = None
    if os.path.isdir(cdir):
        for n in sorted(os.listdir(cdir)):
            if n.startswith("class_") and n.endswith(".json"):
                cls = json.load(open(os.path.join(cdir, n), encoding="utf-8"))
                break
    if not cls:
        return None
    fam, tpl = cls.get("sprite_family"), cls.get("template")
    anime = os.path.join(base, "files", "Anime", "ANM_HI_JP.dat")
    path = os.path.join(anime, "anm%05d.lzs" % fam) if fam else None
    if not path or not os.path.exists(path):
        return dict(mod=mod, name=cls.get("name"), sprite_family=fam, template=tpl, error="no built sprite file")
    built = view_of(fs, load(path), cls.get("kind") != "monster", motion)
    try:
        templ = view_of(fs, anm.parse(fs.read(sprites.sprite_vpath(fs, tpl, "EN"))),
                        cls.get("kind") != "monster", motion)
    except Exception as e:                                  # template file absent: compare nothing
        templ = None
    out = dict(mod=mod, name=cls.get("name"), kind=cls.get("kind"), sprite_family=fam, template=tpl,
               stand=None, idle={}, template_idle={}, ground_delta=None, height=None)
    if built.has(STAND):
        out["stand"] = built.frame(STAND, 0)
    for aid in IDLE:
        if not built.has(aid):
            continue
        rows = [dict(t=t, **built.frame(aid, t)) for t in built.times(aid)[:8]]
        out["idle"][str(aid)] = rows
        if templ and templ.has(aid):
            trows = [dict(t=t, **templ.frame(aid, t)) for t in templ.times(aid)[:8]]
            out["template_idle"][str(aid)] = trows
            deltas = [b["bottom"] - s["bottom"] for b, s in zip(rows, trows) if b.get("px") and s.get("px")]
            out["ground_delta"] = dict(min=min(deltas), max=max(deltas), n=len(deltas)) if deltas else None
            bh = max((r.get("height") or 0) for r in rows)
            th = max((r.get("height") or 0) for r in trows)
            out["height"] = dict(built=bh, template=th, ratio=round(bh / th, 3) if th else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mods")
    # renders are game art: the project playtest folder, never the repo
    ap.add_argument("--out", default=os.path.join("/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/playtest/ptsprite-renders", "audit.json"))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    fs = GameFS(os.environ.get("D5_GAME") or None)
    motion = [sprites.motion_block(fs, 1)]
    only = [s for s in a.only.split(",") if s]
    mods = only or sorted(d for d in os.listdir(a.mods) if d.startswith("D4_Class_"))
    rows = []
    for mod in mods:
        r = audit_pack(fs, a.mods, mod, motion)
        if r is None:
            continue
        rows.append(r)
        stand = r.get("stand") or {}
        gd = r.get("ground_delta") or {}
        print("%-18s %-20s fam=%-5s tpl=%-5s stand_items=%-2s body=%-2s ground_delta=%s height=%s"
              % (mod, r.get("name", "")[:20], r.get("sprite_family"), r.get("template"), stand.get("items"),
                 stand.get("body_layers"), gd and "%s..%s" % (gd["min"], gd["max"]), r.get("height") and r["height"]["ratio"]))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
