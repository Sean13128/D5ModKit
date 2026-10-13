"""Weapon grips from the command line (the GUI page is Weapon Grips).  Docs: docs/WEAPON_GRIPS.md.

  python tools/grips.py anims SPRITE                         animations with weapon nodes
  python tools/grips.py sheet SPRITE ANIM [WEAPON] [OUT.png] every frame with the weapon (sword spear bow gun axe staff)
  python tools/grips.py show SPRITE                          the grip edits of every mod for the sprite
  python tools/grips.py set MOD SPRITE ANIM TARGET KEY DX DY [ROT [FLIP]]
        TARGET A / B (that hand, every weapon type) or a node id (16 = staff only); KEY = frame or * (every frame)
  python tools/grips.py show-weapon MOD SPRITE ANIM TARGET on|off
  python tools/grips.py clear MOD SPRITE [ANIM]
  python tools/grips.py rest-weapon MOD SPRITE on|off|default   hold the weapon when not attacking (outfits, new
        characters and classes; default: off, unless the sprite has grip edits)

The sheet uses the sprite as installed would see it: the owning mod's file (or the game's) with every enabled mod's
grip edits applied.
"""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import anm, grips, modsys, sprites       # noqa: E402
from d5lib.gamefs import GameFS                     # noqa: E402

NAMES = {v[0].lower(): k for k, v in grips.WEAPONS.items()}


def open_kit():
    game = paths.require_game_dir()
    fs = GameFS(game, backup_resolver=modsys.Installer(game, KIT, log=lambda *a: None).backup_resolver)
    return fs, modsys.ModManager(KIT)


def sprite_file(fs, mm, num):
    """(AnmFile, owner mod or None): the enabled mod's copy (last in load order wins) or the game's"""
    vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"
    for mod in reversed(mm.enabled_mods()):
        if mod.has_file(vp):
            return anm.load(mod.read_file(vp)), mod
    return anm.load(fs.read(sprites.sprite_vpath(fs, num, "EN"))), None


def all_edits(mm, num):
    out = {}
    for mod in mm.enabled_mods():
        out = grips.merge(out, grips.load(mod, num))
    return out


def sheet(fs, mm, num, aid, wname="staff", out=None, groups=("A",)):
    from PIL import Image, ImageDraw
    a, owner = sprite_file(fs, mm, num)
    a = grips.edited_copy(a, all_edits(mm, num))
    wtype = NAMES.get(wname.lower(), 16)
    w = grips.weapon_sprite(fs, wtype)
    bi, ai = anm._resolve_anim(a, ("id", aid))
    b = a.blocks[bi]
    times = grips.key_times(b, b.animations[ai]) or anm.frame_times(a, ("id", aid))
    box = grips.anim_bounds(a, aid, w, wtype)
    tiles = []
    for t in times:
        g = []
        im = grips.render(grips.evaluate(a, aid, t, w, wtype, groups, grips=g), box, 2, background=(70, 90, 70, 255), char=a)
        d = ImageDraw.Draw(im)
        for nid, grp, (x, y), shown, m in g:
            px, py = (x - box[0]) * 2, (y - box[1]) * 2
            col = (255, 255, 0, 255) if grp == "A" else (0, 255, 255, 255)
            d.ellipse((px - 4, py - 4, px + 4, py + 4), outline=col if shown else (128, 128, 128, 255))
        d.text((3, 2), f"{aid} f{t}", fill=(255, 255, 255, 255))
        tiles.append(im)
    cols = min(6, len(tiles))
    W, H = tiles[0].size
    rows = -(-len(tiles) // cols)
    s = Image.new("RGBA", (cols * (W + 2), rows * (H + 2)), (255, 255, 255, 255))
    for i, im in enumerate(tiles):
        s.paste(im, ((i % cols) * (W + 2), (i // cols) * (H + 2)))
    out = out or os.path.join(KIT, "cache", f"grips_{num}_{aid}_{wname}.png")
    s.save(out)
    print(f"{len(tiles)} frames -> {out}  (yellow = hand A, cyan = hand B, grey = hidden)")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    fs, mm = open_kit()
    cmd = argv[0]
    if cmd == "anims":
        a, owner = sprite_file(fs, mm, int(argv[1]))
        for aid, bi in grips.weapon_anims(a):
            b = a.blocks[bi]
            an = next(x for x in b.animations if x.id == aid)
            print(aid, "frames", grips.key_times(b, an))
    elif cmd == "sheet":
        sheet(fs, mm, int(argv[1]), int(argv[2]), argv[3] if len(argv) > 3 else "staff",
              argv[4] if len(argv) > 4 and argv[4] not in ("A", "B", "AB") else None,
              tuple(argv[-1]) if argv[-1] in ("A", "B", "AB") else ("A",))
    elif cmd == "show":
        for mod in mm.all_mods():
            e = grips.load(mod, int(argv[1]))
            if e:
                print(mod.id, e)
    elif cmd == "rest-weapon":
        mod = mm.get(argv[1])
        if mod is None:
            sys.exit(f"no mod {argv[1]}")
        num = int(argv[2])
        grips.save(mod, num, grips.load(mod, num), idle={"on": True, "off": False}.get(argv[3]))
        print(mod.id, num, "idle_weapon", grips.idle_weapon(mod, num))
    elif cmd in ("set", "show-weapon", "clear"):
        mod = mm.get(argv[1])
        if mod is None:
            sys.exit(f"no mod {argv[1]}")
        num = int(argv[2])
        e = grips.load(mod, num)
        if cmd == "set":
            aid, target, key = argv[3], argv[4], argv[5]
            v = [float(x) for x in argv[6:9]] + ([int(argv[9])] if len(argv) > 9 else [])
            v = [int(x) if float(x).is_integer() else x for x in v]
            e.setdefault(aid, {}).setdefault(target, {})[key] = v
        elif cmd == "show-weapon":
            e.setdefault(argv[3], {}).setdefault(argv[4], {})["show"] = argv[5] == "on"
        else:
            if len(argv) > 3:
                e.pop(argv[3], None)
            else:
                e = {}
        grips.save(mod, num, e)
        print(mod.id, num, grips.load(mod, num))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
