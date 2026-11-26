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
# Every number keyed to the id must be free in the game (anm <id>, +1, +2, 10000 + <id>, +1): ~540 ids.
# The dummy families come first (nothing of the game's sits next to them), then every other free id.
DUMMY_ROWS = (470, 480, 490, 950, 960, 970, 980, 990)


def unique_pool(fs, vanilla=None):
    """every usable id below 1000, in the order they are handed out"""
    from . import sprites
    if vanilla is None:
        vanilla = database.load_table("char.dat", fs.read(CHAR))
    rows = {r["id"] for r in vanilla.rows}
    used_anm = sprites.used_sprite_numbers(fs)
    # none of the game's files may sit at the numbers keyed to the id: anm <id> / <id> + 1 are a character's sprite
    # and its copy (id 11 is Killia's copy: a character there showed the wrong pictures and no status portrait)
    free = [i for i in range(10, 1000) if i not in rows and not {i, i + 1, i + 2, i + 10000, i + 10001} & used_anm]
    dummy = [i for d in DUMMY_ROWS for i in range(d, d + 10) if i in DUMMY_ROWS or i in free]
    return dummy + [i for i in free if i not in dummy]


def free_unique_ids(fs, mod, vanilla=None, extra_taken=()):
    """unique_pool minus every id a mod already uses (char.dat rows edited / added, outfit slots) and every id whose
    keyed files (anm <id> + 2, 10000 + <id>, ...) a mod's own files already sit on"""
    taken = used_dummy_ids(mod, vanilla) | set(extra_taken)
    files = set()
    for m in _mods(mod):
        o = m.load_patch("outfits", "outfits.json") or {}
        for a, b in o.get("pairs", []):
            taken.update((int(a), int(b)))
        for f in m.list_files():
            n = f.split("/")[-1]
            if n.startswith("anm") and n[3:8].isdigit():
                files.add(int(n[3:8]))
    return [i for i in unique_pool(fs, vanilla) if i not in taken
            and not {i + 2, i + 10000, i + 10001} & files]


# --------------------------------------------------------------------------------- unique sprite leases
# A unique on a registry identity does not need a free low char.dat row: its class id is the identity and
# only its *art* is keyed to a low number ("physical row"): sprite n, +1 companion, +2 standing picture and
# the cut-in / status portraits 10000 + n / +1 (d5lib/d4unique.py:479).  The free runs measured on the pinned
# char.dat and every installed mod file are 853..999, 223..403 and -- for the windows only, see below --
# 404..852: no file sits at n, n+1, n+2, 10000+n or 10001+n for any n handed out.  Two leases need 3 apart
# (their key windows must not overlap); the manifest reserves every run for the kit.
#
# 223..403 is the second run: the band the superseded low-row D4 unique generation stopped using when uniques
# moved to registry identities (DECISIONS 2026-10-27, D4UNIQ-REPORT).  404..852 is the third run (DECISIONS
# 2026-10-29 [taste, coordinator], D1C2): unlike the first two, that band is *not* empty -- it holds 45
# vanilla character rows at stride 10 and 220 used picture numbers -- so only the individual windows that
# measure free are handed out, and each one has to be carved out of the vanilla band in the ownership
# manifest (d5lib/data/unique_art_leases.json) before a build may claim it.  Runs are handed out in this
# order, so every lease recorded before a change keeps its number.
SPRITE_LEASE_FIRST, SPRITE_LEASE_LAST = 853, 999
# (lo, hi) of *lease* ids whose three sprite keys p, p+1, p+2 stay inside a kit-reserved art band:
# 853..997 keeps p+2 <= 999, 223..401 keeps p+2 <= 403, 404..852 keeps p+2 <= 854.
SPRITE_LEASE_RUNS = ((853, 999), (223, 401), (404, 852))
SPRITE_LEASE_SPACING = 3


def unique_sprite_pool(fs, taken=(), first=None, last=None):
    """Every low id a registry unique's art can be keyed to, in the order they are handed out.

    `taken` = physical ids already leased (this batch, another pack, a recorded lease); an id within
    SPRITE_LEASE_SPACING of one of them would share a keyed file with it.  `first`/`last` restrict the
    measurement to one run (a caller measuring a single band); by default every measured run is used.
    """
    from . import sprites
    used = sprites.used_sprite_numbers(fs)
    taken = {int(x) for x in taken}
    if first is None and last is None:
        runs = SPRITE_LEASE_RUNS
    else:
        runs = ((SPRITE_LEASE_FIRST if first is None else first,
                 SPRITE_LEASE_LAST if last is None else last),)
    out = []
    for lo, hi in runs:
        for i in range(lo, hi + 1):
            if {i, i + 1, i + 2, 10000 + i, 10001 + i} & used:
                continue
            if any(abs(i - t) < SPRITE_LEASE_SPACING for t in taken):
                continue
            if any(abs(i - t) < SPRITE_LEASE_SPACING for t in out):
                continue
            out.append(i)
    return out
