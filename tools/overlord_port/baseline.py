"""Vanilla ``Database_0.dat`` members, read-only, from a live install.

The kit patches NISPACK archives *in place by appending* and keeps the vanilla directory table
in ``<kit>/state/games/<game>/backups/Database__Database_0.dat.hdr`` (see ``d5lib/modsys.py``).
That header names the original extent of every member, and the original bytes are still where
they were, so ``d5lib.gamefs.GameFS`` with a backup resolver returns vanilla members without
extracting, copying or writing anything.

Offline only: this module opens files for reading. It never writes the game folder, the
installed kit, a profile or a save.

    fs = baseline.open_database()                      # default install on this machine
    raw = baseline.read(fs, "char.dat")                # vanilla char.dat bytes
    names = baseline.members(fs)
"""
import os

from d5lib import gamefs

DEFAULT_GAME = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete"
GAME_STATE = "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"
ARCHIVE = "Database/Database_0.dat"


def backup_dir(game_dir=DEFAULT_GAME):
    return os.path.join(game_dir, GAME_STATE, "backups")


def header_path(game_dir=DEFAULT_GAME, archive=ARCHIVE):
    """The append-mode header backup, or None when this install has never patched the archive."""
    p = os.path.join(backup_dir(game_dir), archive.replace("/", "__") + ".hdr")
    return p if os.path.exists(p) else None


def resolver(game_dir=DEFAULT_GAME):
    """``GameFS(backup_resolver=...)``: vanilla header bytes for a currently modified archive."""
    hdr = header_path(game_dir)

    def _resolve(archive):
        if archive != ARCHIVE or hdr is None:
            return None, None
        with open(hdr, "rb") as fh:
            return fh.read(), None
    return _resolve


def open_database(game_dir=DEFAULT_GAME):
    """A read-only GameFS whose Database archive reads as *vanilla*."""
    return gamefs.GameFS(game_dir, backup_resolver=resolver(game_dir))


def members(fs, archive=ARCHIVE):
    return sorted(fs.list_members(archive))


def read(fs, member, archive=ARCHIVE):
    """Vanilla bytes of one member (raw, as stored: Database members are not compressed)."""
    return fs.read_raw(f"{archive}/{member}")


def is_vanilla_available(game_dir=DEFAULT_GAME):
    """True when the install backup lets us rebuild vanilla members without the original game."""
    return header_path(game_dir) is not None
