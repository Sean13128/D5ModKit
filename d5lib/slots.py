"""Unused unique char.dat rows ('Unique Dummy' 470-490, 'Void Dark?' 950/960?, 'DLC Dummy' 970-990) are shared by
outfits (d5lib.outfits) and new unique characters (Characters page): a row is taken as soon as any mod edits it or
adds that id."""
import os

from . import database

CHAR = "Database/Database_0.dat/char.dat"


def _mods(mod):
    from .modsys import Mod
    root = os.path.dirname(mod.folder)
    return [Mod(os.path.join(root, d)) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]


def used_dummy_ids(mod, vanilla=None):
    """class ids of char.dat rows edited or added by any mod next to `mod`"""
    if vanilla is None:
        from .gamefs import GameFS
        from .modsys import KIT_DIR
        from .paths import game_dir
        game = game_dir() or os.path.abspath(os.path.join(KIT_DIR, ".."))
        try:
            from .modsys import Installer
            fs = GameFS(game, backup_resolver=Installer(game).backup_resolver)
        except Exception:
            fs = GameFS(game)
        vanilla = database.load_table("char.dat", fs.read(CHAR))
    ids = [r["id"] for r in vanilla.rows]
    used = set()
    for m in _mods(mod):
        patch = m.load_patch("db", "char.dat.json") or {}
        for k in (patch.get("rows") or {}):
            if int(k) < len(ids):
                used.add(ids[int(k)])
        for r in patch.get("added") or []:
            if "id" in r:
                used.add(int(r["id"]))
    return used


# ------------------------------------------------------------------------------------------ unique id pool
# Outfits of unique characters and new unique characters need a char.dat id below 1000 (the game treats every id
# from 1000 up as a generic class).  Usable: the unused dummy rows (edited in place) and every id the game has no
# row for whose colour-keyed graphics files are free -- anm <id> + 2 (small standing picture) and 10000 + <id>
# (portrait / cut-in), the two copies the kit writes for the id (its sprite has numbers of its own: SPRITE_NUMBERS).
# 706 ids (542 when anm <id>, +1 and 10001 + <id> were required free as well: nothing reads those for a unique id).
# The dummy families come first (nothing of the game's sits next to them), then every other free id.
DUMMY_ROWS = (470, 480, 490, 950, 960, 970, 980, 990)


def unique_pool(fs, vanilla=None):
    """every usable id below 1000, in the order they are handed out"""
    from . import sprites
    if vanilla is None:
        vanilla = database.load_table("char.dat", fs.read(CHAR))
    rows = {r["id"] for r in vanilla.rows}
    used_anm = sprites.used_sprite_numbers(fs)
    free = [i for i in range(10, 1000) if i not in rows and not {i + 2, i + 10000} & used_anm]
    dummy = [i for d in DUMMY_ROWS for i in range(d, d + 10) if i in DUMMY_ROWS or i in free]
    return dummy + [i for i in free if i not in dummy]


def free_unique_ids(fs, mod, vanilla=None, extra_taken=()):
    """unique_pool minus every id a mod already uses (char.dat rows edited / added, outfit slots)"""
    taken = used_dummy_ids(mod, vanilla) | set(extra_taken)
    for m in _mods(mod):
        o = m.load_patch("outfits", "outfits.json") or {}
        for a, b in o.get("pairs", []):
            taken.update((int(a), int(b)))
    return [i for i in unique_pool(fs, vanilla) if i not in taken]
