"""Re-derive the colour variants (the extra colours of the Strategy Assembly) of the mods' own sprites with part info
(outfits, new characters and their outfits) by the part-following method (d5lib.recolor): every colour follows the
part of the character it lies over in the same poses.  The default look and the drawings are not changed.

    python tools/rederive_colors.py [MOD ...] [--only SPRITE,...] [--dry] [--skin]

--skin: check her skin again (d5lib.recolor.refine_skin: skin texels of shades shared with other parts get their
own entries; done once per sprite otherwise).  Every variant is repaired against blotches (recolor.repair).

Without MOD: every mod with part info.  The base of a sprite: the character an outfit belongs to (its own game
sprite), else -- a new character and its outfits -- the game character whose animation set the sprite plays (the
template it was drawn on)."""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, KIT)
from d5lib import anm, colorvariants, database, drpgmap, modsys, outfits, paths, sprites   # noqa: E402
from d5lib.gamefs import GameFS                                                          # noqa: E402

PART_FILE = "parts_"


def sprites_with_parts(mod):
    d = os.path.join(mod.patches_dir, "outfits")
    if not os.path.isdir(d):
        return []
    out = []
    for f in os.listdir(d):
        if f.startswith(PART_FILE) and f.endswith(".json") and f[len(PART_FILE):-5].isdigit():
            out.append(int(f[len(PART_FILE):-5]))
    return sorted(out)


_sigs = {}


def anim_sigs(fs, num, mod=None):
    """{animation id: its key times} of a sprite file's own animations"""
    if num not in _sigs:
        vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"
        a = anm.load(mod.read_file(vp)) if mod is not None and mod.has_file(vp) else             anm.parse(fs.read(sprites.sprite_vpath(fs, num, "EN")))
        _sigs[num] = {x["id"]: tuple(anm.frame_times(a, x["index"])) for x in anm.list_animations(a)}
    return _sigs[num]


def template_of(fs, mod, num, van):
    """the game character sprite whose animation set sprite `num` plays: among the characters whose own poses the
    DRPG builder knows (drpgmap.own_map_path), the one whose own animations (idle loops, specials) appear in the
    sprite with the same timing"""
    cands = []
    for f in os.listdir(os.path.dirname(drpgmap.own_map_path(0))):
        if f.startswith("drpg_ownmap_") and f.endswith(".json"):
            cands.append(int(f[len("drpg_ownmap_"):-5]))
    mine = anim_sigs(fs, num, mod)
    best = None
    for c in cands:
        try:
            theirs = anim_sigs(fs, c)
        except Exception:
            continue
        if not theirs:
            continue
        same = sum(1 for aid, ts in theirs.items() if mine.get(aid) == ts)
        score = (same / len(theirs), same)
        if best is None or score > best[0]:
            best = (score, c)
    return best[1] if best and best[0][0] > 0.5 else None


def base_sprite_of(fs, mod, num, van):
    """(base game sprite, how it was found)"""
    _, ed = outfits._char_tables(fs, mod)
    rows = {r["id"]: r for r in ed.rows}
    for base, slot in outfits.load(mod):
        r = rows.get(int(slot))
        if r is not None and int(r["sprite_id"]) == num:
            b = van.get(int(base))
            if b is not None and int(b["sprite_id"]) < 9000:
                return int(b["sprite_id"]), f"outfit of {b['name_EN']}"
            break
    t = template_of(fs, mod, num, van)
    return t, "drawn on the animations of sprite %s" % t


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    recheck = "--skin" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
        args = [a for a in args if not all(c.isdigit() or c == "," for c in a)]
    g = paths.require_game_dir()
    fs = GameFS(g, backup_resolver=modsys.Installer(g, KIT, log=lambda *a: None).backup_resolver)
    mm = modsys.ModManager(KIT)
    mods = [mm.get(a) for a in args] if args else mm.all_mods()
    van = {r["id"]: r for r in database.load_table("char.dat", fs.read(outfits.CHAR)).rows}
    done = 0
    for mod in mods:
        if mod is None:
            continue
        for num in sprites_with_parts(mod):
            if only and num not in only:
                continue
            vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"
            if not mod.has_file(vp):
                continue
            base_num, why = base_sprite_of(fs, mod, num, van)
            if base_num is None:
                print(f"{mod.id} anm{num:05d}: no base character found, skipped")
                continue
            a = anm.load(mod.read_file(vp))
            base = anm.parse(fs.read(sprites.sprite_vpath(fs, base_num, "EN")))
            info = outfits._load_parts(mod, num)
            if recheck:
                info.pop("skin_checked", None)
            lines = []
            colorvariants.derive_parts(a, base, info, fs=fs, log=lines.append)
            print(f"{mod.id} anm{num:05d} ({why}): " + " ".join(x.strip() for x in lines))
            if dry:
                continue
            mod.write_file(vp, a.to_bytes())
            outfits._save_parts(mod, num, info)
            cvp = f"Anime/ANM_HI_JP.dat/anm{num + 1:05d}.lzs"
            if num % 10 == 0 and mod.has_file(cvp):              # the companion shares the palettes
                c = anm.load(mod.read_file(cvp))
                if len(c.palettes) == len(a.palettes):
                    c0, a0 = anm.get_palette(c, 0), anm.get_palette(a, 0)
                    twins = (c0[:, 3] == 0) & (a0[:, 3] > 0)          # skin twins of its shades
                    c0[twins] = a0[twins]
                    anm.set_palette(c, 0, c0)
                    for p in range(1, len(a.palettes)):
                        anm.set_palette(c, p, anm.get_palette(a, p))
                    mod.write_file(cvp, c.to_bytes())
            done += 1
    print(f"{done} sprite(s) re-derived" + (" (dry run: nothing written)" if dry else ""))


if __name__ == "__main__":
    main()
