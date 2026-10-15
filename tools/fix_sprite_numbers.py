"""Move the mods' own sprites off the numbers the game keys to characters.

A character's portrait is anm 10000 + its id, so the sprite numbers 10000 .. 12999 belong to the portraits of
character ids 0 .. 2999 (unique characters, outfit slots, class families).  Kit versions before 1.5 could give an
outfit or a new character a sprite number there; when a character with that id exists (or is made later: a new class
in family 1290 needs 11290 .. 11299) one file is drawn as the other.  This moves every such sprite to a free number
(outfits.renumber_sprite: the files, the character rows, colour parts, source, painted parts, grips, event sheets).
Saves are not touched: they refer to characters by id.

    python tools/fix_sprite_numbers.py [MOD ...] [--dry]

Without MOD: every mod.  A sprite whose files are also an outfit slot's own files (two outfits sharing a number) can't
be moved: it is reported, rebuild that outfit (tools/drpg_outfits.py build --rebuild --only UNIT).
"""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, KIT)
from d5lib import modsys, outfits, paths                    # noqa: E402
from d5lib.gamefs import GameFS                             # noqa: E402


def in_portrait_range(N):
    return any(N + k in outfits.PORTRAITS_OF_IDS for k in (0, 1, 2, 10000, 10001))


def own_sprites(mod):
    """the mod's own sprite numbers N (groups of 10): outfit sprites and character / class sprites it ships"""
    out = {int(x) for x in outfits.load_own(mod) if int(x) % 10 == 0}
    rec = mod.load_patch("outfits", "drpg_character.json")
    if rec and rec.get("sprite"):
        out.add(int(rec["sprite"]))
    return sorted(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    g = paths.require_game_dir()
    fs = GameFS(g, backup_resolver=modsys.Installer(g, KIT, log=lambda *a: None).backup_resolver)
    mm = modsys.ModManager(KIT)
    every = mm.all_mods()
    mods = [mm.get(a) for a in args] if args else every
    moved, stuck = 0, []
    reserved = set()                                 # numbers handed out in a dry run
    for mod in mods:
        if mod is None:
            continue
        for N in own_sprites(mod):
            if not in_portrait_range(N) or N not in outfits.sprite_group(mod, N):
                continue
            new = outfits._free_sprite(fs, mod)
            while dry and new in reserved:
                outfits.SPRITE_NUMBERS.remove(new)
                new = outfits._free_sprite(fs, mod)
            reserved.add(new)
            if dry:
                print(f"{mod.id}: anm{N:05d} -> anm{new:05d}")
                moved += 1
                continue
            try:
                outfits.renumber_sprite(fs, mod, N, new, all_mods=every)
                moved += 1
            except ValueError as e:
                stuck.append((mod.id, N, str(e)))
                print(f"{mod.id}: anm{N:05d} NOT moved: {e}")
    print(f"{moved} sprite(s) {'to move' if dry else 'moved'}" + (f", {len(stuck)} left (see above)" if stuck else ""))


if __name__ == "__main__":
    main()
