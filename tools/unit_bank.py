"""The character bank on the command line (d5lib/unitbank.py), for save copies (the real save with --live).

    unit_bank.py export <save copy> <unit> <bank dir>      unit = roster slot number, or the unit's name
    unit_bank.py import <bank file> <save copy> --db <installed Database_0.dat>
    unit_bank.py list   <bank dir>

A bank file is one unit: its 0x4750-byte roster record plus what the listing shows (`unitbank.bank_doc`).
Import puts the record at the end of the army with a fresh serial (`unitbank.import_unit`) and rewrites the
save copy in place; it refuses, changing nothing, when

  * the unit's class is not in the installed char.dat (its class/character mod is not installed),
  * the save is at the 128 limit (army + reserve; the game's own guard in roster_create_unit 0x1402ea3e0),
  * the unit is a story-locked character.  This is the game's own Dismiss rule (0x140654f20, the list filter
    in 0x140655030; text 10650 "unique characters cannot be dismissed"): character id 2460 or below 1000 is
    locked unless it is one of the 36 DLC characters in the exe table 0x140A0D968 (DISMISSABLE below), which
    the game lets you dismiss like a generic.  Dummy rows below 1000 that a mod fills are not locked here (the
    game itself would refuse to dismiss them, but they are not story characters).  A unit of the guest tail /
    reserve is also refused: that rule is the kit's own, not the game's (the default roster pushes later story
    characters there).  Export refuses the same units.

A path under the game's live save folder is refused unless --live is given.  With --live (or for a save in a kit
profile's saves) the save and its .d5learn.json companion are first copied to <kit>/state/save_backups
(savegame.backup, as the save cleaner does); it refuses while disgaea5.exe runs, and puts the backup back when the
written save does not verify.  Nothing here starts the game or reads the install except the --db file you name.
The editor page "Character Bank" (d5gui/pages/charbank.py) calls the same functions.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

from d5lib import savegame, unitbank   # noqa: E402
try:                                   # the learned-evility companion (evilities past the game's 1000-bit bitmap) is an
    from d5lib import learned          # optional kit part: without it the bank carries the record alone
except ImportError:                    # pragma: no cover - depends on the kit build
    learned = None
SIDECAR_SUFFIX = learned.SIDECAR_SUFFIX if learned else ".d5learn.json"

# the unmodded game's Database_0.dat, for the story lock (default: read from the game folder through the installer's
# vanilla backups, `--game`); set D5_VANILLA_DB to point at a clean copy instead
VANILLA_DB = os.environ.get("D5_VANILLA_DB")
EXT = ".d5unit.json"
UNIQUE_BELOW = 1000
UNIQUE_ALSO = 2460
# column 0 of the 39-row, 10-word table at 0x140A0D968 (rows 1240/1250/1260 are >= 1000, never looked up)
DISMISSABLE = frozenset([*range(510, 770, 10), 800, *range(860, 950, 10)])


class Refused(Exception):
    pass


GAME_SAVE_DIRS = ("Nippon Ichi Software, Inc", "Disgaea 5 Complete")


def under_live(path):
    """True for a path inside the game's save folder.  save_root() needs %APPDATA%, which a Mac session does not set
    (the Wine prefix is not in the environment), so the folder is also recognised by its own name in the path."""
    root = os.path.abspath(savegame.save_root() or "/nonexistent")
    full = os.path.abspath(os.path.realpath(path))
    parts = full.split(os.sep)
    named = any(parts[i:i + 2] == list(GAME_SAVE_DIRS) for i in range(len(parts) - 1))
    return named or full.startswith(root + os.sep) or os.path.abspath(path).startswith(root + os.sep)


def game_running():
    """is disgaea5.exe running?  (the kit's own check, d5gui/workspace.py; imported late because it needs PyQt6)"""
    from d5gui.workspace import game_running as running
    return running()


def _inside(path, folder):
    full, root = os.path.realpath(path), os.path.realpath(folder)
    return full.startswith(root + os.sep)


def _put_back(backup, paths):
    """restore `paths` from the backup folder; a file the backup lacks (a companion made since) is removed"""
    for p in paths:
        saved = next((os.path.join(d, os.path.basename(p)) for d, _, fs in os.walk(backup) if os.path.basename(p) in fs), None)
        if saved is None:
            if os.path.exists(p):
                os.remove(p)
        elif not os.path.exists(p) or Path(p).read_bytes() != Path(saved).read_bytes():
            tmp = p + ".restore"
            shutil.copy2(saved, tmp)
            os.replace(tmp, p)


@contextlib.contextmanager
def protected(save_path, live=False, kit_dir=None, write=True):
    """Wrap a write to a save.  A save in the game's folder needs live=True (--live / the page) and a closed game; it
    and a save in a kit profile's saves are copied (with the .d5learn.json companion) to <kit>/state/save_backups
    first (the same savegame.backup the save cleaner uses).  If the backup fails nothing is written; if the code inside
    fails, or the written save does not verify, the backup is put back.  Any other path: no change.  Yields the backup
    folder or None."""
    game = under_live(save_path)
    if game and not live:
        raise Refused(f"{save_path} is under the live save folder; work on a copy (or pass --live to work on the real save "
                      "with a backup)")
    if not write:
        yield None
        return
    from d5lib import modsys
    kit_dir = kit_dir or str(modsys.KIT_DIR)
    stores = [f for _, f in savegame.save_roots(kit_dir)[1:]]
    if not (game or any(_inside(save_path, f) for f in stores)):
        yield None
        return
    if game:
        try:
            if game_running():
                raise Refused("Disgaea 5 is running: close it first (the game keeps its saves in memory and would write "
                              "over this change). Nothing was changed.")
        except RuntimeError as ex:
            raise Refused(f"{ex} Nothing was changed.")
    files = [p for p in (str(save_path), str(save_path) + SIDECAR_SUFFIX) if os.path.exists(p)]
    try:
        backup = savegame.backup(files, kit_dir, "bank")
    except OSError as ex:
        raise Refused(f"could not make the backup first ({ex}); nothing was written")
    try:
        yield backup
        bad = unitbank.verify(savegame.Save(str(save_path)))
        if bad:
            raise Refused("the written save does not verify: " + "; ".join(bad))
    except BaseException as ex:
        _put_back(backup, [str(save_path), str(save_path) + SIDECAR_SUFFIX])
        if isinstance(ex, Refused) and "does not verify" in str(ex):
            raise Refused(f"{ex}. The backup was put back; the save is as it was.")
        raise


def char_names(db_path):
    """{class id: English name} of a Database_0.dat's char.dat"""
    from d5lib import database
    return {r["id"]: r["name_EN"] for r in database.load_database(str(db_path))["char.dat"].rows}


def need_vanilla(vanilla):
    """the story lock reads the unmodded char.dat; with no table every story character would pass, so refuse instead"""
    if not vanilla:
        raise Refused("the unmodded char.dat could not be read, so story characters cannot be told apart: "
                      "set the game folder (or --vanilla-db / --game on the command line). Nothing was changed.")


def story_locked(cls, vanilla, in_reserve=False):
    """why this unit may not move between saves, or None.  vanilla: {id: name} of the game's own char.dat"""
    if in_reserve:
        return "it sits in the reserve (a character the story hands over)"
    if ((cls < UNIQUE_BELOW or cls == UNIQUE_ALSO) and cls not in DISMISSABLE
            and cls in vanilla and vanilla[cls] not in savegame.RESERVED_NAMES):
        return f"{vanilla[cls]} (class {cls}) is a Disgaea 5 story character the game does not let you dismiss"
    return None


def find_unit(save, want):
    """roster slot of `want` (a slot number or a name that exactly one unit has)"""
    if re.fullmatch(r"\d+", str(want)):
        slot = int(want)
        if not any(u.slot == slot for u in save.units()):
            raise Refused(f"roster slot {slot} holds no unit")
        return slot
    hits = [u for u in save.units() if u.name == want]
    if len(hits) != 1:
        raise Refused(f"{len(hits)} units are named {want!r}; give the roster slot "
                      f"({', '.join(str(u.slot) for u in hits) or 'see the save list'})")
    return hits[0].slot


def skill_ids(db_path):
    """the ordered Skill.dat id list of a Database_0.dat (what the learned companion's generation is made from), or
    None when this kit has no companion support"""
    try:
        from d5lib import ordercheck
    except ImportError:
        return None
    from d5lib import database
    return ordercheck._ids(database.load_database(str(db_path))["Skill.dat"])


def game_char_names(game_dir, kit_dir=None):
    """{class id: English name} of the UNMODDED char.dat of an installed game: GameFS reads the vanilla member through
    the kit installer's backups (as the editor does)"""
    from d5lib import database, modsys
    from d5lib.gamefs import GameFS
    inst = modsys.Installer(game_dir, kit_dir or modsys.KIT_DIR, log=lambda *a: None)
    fs = GameFS(game_dir, backup_resolver=inst.backup_resolver)
    return {r["id"]: r["name_EN"] for r in database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat")).rows}


def companion(save_path):
    """(doc, why): the save's learned companion (`<save>.d5learn.json`) when it is bound to these exact save bytes.
    doc None + why None = no companion; doc None + why = one exists but is stale/unreadable (the game would refuse it too)"""
    path = str(save_path) + SIDECAR_SUFFIX
    if not os.path.exists(path):
        return None, None
    if learned is None:
        return None, "this kit has no learned-evility support"
    try:
        doc = learned.sidecar_read(path)
        raw = Path(save_path).read_bytes()
        want = doc["save"]
        if doc["kind"] != "d5modkit.learned" or want["size"] != len(raw) or want["sha256"] != hashlib.sha256(raw).hexdigest():
            return None, "it does not match the save bytes"
        return doc, None
    except (OSError, ValueError, KeyError, TypeError) as ex:
        return None, f"it is unreadable ({ex})"


def write_companion(save_path, doc):
    """re-bind a companion to the save as it is now on disk (size + sha256) and write it"""
    raw = Path(save_path).read_bytes()
    doc["save"] = {"name": os.path.basename(str(save_path)), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    learned.sidecar_write(str(save_path) + SIDECAR_SUFFIX, doc)


def export(save_path, want, bank_dir, vanilla, move=False, live=False, kit_dir=None, serial=None):
    """the unit -> a bank file.  move: then take it out of the save copy, as the game's Dismiss does (the bank file
    is written first, so a failed removal never loses the unit; when the removal fails and the save still holds the
    unit, the bank file is taken back so the unit is not in both).
    The bank file never carries items (no duplicated gear): with move the unit's equipped items go into the source
    save's bag (refused when the bag has no room); without move the source keeps them.  serial: refuse unless the unit at `want` has this serial (a stale page card)"""
    need_vanilla(vanilla)
    written = []
    try:
        with protected(save_path, live, kit_dir, write=move) as backup:
            return _export(save_path, want, bank_dir, vanilla, move, backup, serial, written)
    except BaseException:
        if move and written and _holds(save_path, written[1]):
            os.remove(written[0])
        raise


def _holds(save_path, record):
    """does the save on disk still hold this unit (same serial and class)?"""
    try:
        save = savegame.Save(str(save_path))
    except (OSError, ValueError):
        return False
    want = (struct.unpack_from("<Q", record, savegame.U_SERIAL)[0], struct.unpack_from("<I", record, savegame.U_CLASS)[0])
    return any((u.serial, u.cls) == want for u in save.units())


def _write_new(folder, stem, text):
    """write text to <folder>/<stem>.d5unit.json without ever replacing a file (-1, -2 on a clash) -> path"""
    os.makedirs(folder, exist_ok=True)
    out, n = Path(folder) / f"{stem}{EXT}", 1
    while out.exists():
        out = Path(folder) / f"{stem}-{n}{EXT}"
        n += 1
    f = open(out, "x", encoding="utf-8")              # "x": never replaces a banked unit, even one that just appeared
    try:
        with f:
            f.write(text)
    except BaseException:
        out.unlink()                                     # our own partial file (disk full): no damaged unit left behind
        raise
    return out


def _export(save_path, want, bank_dir, vanilla, move, backup, serial=None, written=None):
    save = savegame.Save(str(save_path))
    slot = find_unit(save, want)
    unit = savegame.Unit(save, slot)
    if serial is not None and unit.serial != int(serial):
        raise Refused(f"roster slot {slot} now holds another unit ({unit.name}); reload the save")
    why = story_locked(unit.cls, vanilla, unit.reserve)
    if why:
        raise Refused(f"story-locked: {why}")
    comp, _ = companion(save_path)
    key = f"{unit.serial:016x}"
    extra = {unit.serial: ((comp or {}).get("units", {}).get(key) or {}).get("learned") or []}
    gear = 0
    if move:
        try:
            gear = unitbank.unequip_to_bag(save, slot)
        except ValueError as ex:
            raise Refused(str(ex))
    entry = unitbank.export_unit(save, slot, extra_learned=extra, sha=unitbank.sha256(str(save_path)))
    record = bytes.fromhex(entry["record"])
    gear = gear or len(unitbank.equipped(record))
    entry["record"] = unitbank.strip_items(record).hex()
    entry["unequipped"] = gear
    safe = re.sub(r"[^A-Za-z0-9]+", "_", entry["name"]).strip("_") or "unit"
    out = _write_new(bank_dir, f"{safe}-{entry['class']}-{entry['serial']}", json.dumps(unitbank.bank_doc([entry]), ensure_ascii=False))
    if written is not None:
        written[:] = [out, bytes.fromhex(entry["record"])]
    if move:
        save.remove_units([slot])                          # also clears a DLC guest's flag, as Dismiss does
        bad = unitbank.verify(save)
        if bad:
            raise Refused(f"the save would not verify without the unit, so it stays in the save: " + "; ".join(bad))
        save.write()
        if comp is not None:         # the unit's learning left with it; the companion must name the save as it is now
            comp["units"].pop(key, None)
            comp["quarantine"] = [q for q in comp.get("quarantine") or [] if int(q["serial"]) != entry["serial"]]
            write_companion(save_path, comp)
    if backup:
        entry["backup"] = backup
    return out, entry


def check_doc(doc, name="the bank file"):
    """the one entry of a bank document, or Refused with a plain sentence (a doctored or damaged file never reaches the save)"""
    if not isinstance(doc, dict) or doc.get("kind") != unitbank.KIND:
        raise Refused(f"{name} is not a character bank file")
    if doc.get("schema") != unitbank.SCHEMA:
        raise Refused(f"{name} is bank format {doc.get('schema')!r}; this kit reads format {unitbank.SCHEMA}")
    units = doc.get("units")
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
        raise Refused(f"{name} is not a one-unit bank file")
    entry = units[0]
    for key in ("name", "class", "record"):
        if key not in entry:
            raise Refused(f"{name} is damaged: the unit has no {key!r}")
    try:
        cls = int(entry["class"])
        raw = unitbank.entry_record(entry)
    except (TypeError, ValueError) as ex:
        raise Refused(f"{name} is damaged: {ex}")
    actual = struct.unpack_from("<I", raw, savegame.U_CLASS)[0]
    if actual != cls:
        raise Refused(f"{name} is inconsistent: it lists class {cls} but the unit record is class {actual}")
    return entry


def read_entry(bank_file):
    try:
        doc = json.loads(Path(bank_file).read_text())
    except ValueError as ex:
        raise Refused(f"{Path(bank_file).name} is not a readable bank file: {ex}")
    return check_doc(doc, Path(bank_file).name)


IMPORTED_DIR = "imported"


def move_imported(bank_file):
    """move a bank file into the `imported/` subfolder of its folder (never deletes, never overwrites) -> new path"""
    bank_file = Path(bank_file)
    dest_dir = bank_file.parent / IMPORTED_DIR
    dest_dir.mkdir(exist_ok=True)
    dest, n = dest_dir / bank_file.name, 1
    while dest.exists():
        dest = dest_dir / f"{bank_file.name[:-len(EXT)]}-{n}{EXT}"
        n += 1
    os.replace(bank_file, dest)
    return dest


def import_(bank_file, save_path, installed, vanilla, move=False, skill_ids=None, live=False, kit_dir=None,
            allow_duplicate=False):
    """installed: {id: name} of the installed char.dat.  -> (result of unitbank.import_unit, entry).
    move: after the save is written and verified, the bank file goes to `imported/` so it cannot be imported twice
    (res["moved_to"]); a refusal or a failed write leaves it where it is.
    skill_ids: the installed Skill.dat ids, needed only to START a companion for a unit that brings extra evilities
    into a save that has none; an existing valid companion is extended and re-bound to the written save either way.
    live / kit_dir: see `protected` (a real save is backed up first and put back if it does not verify)
    allow_duplicate: import even when the save already holds this very unit (a bank file imported twice)"""
    need_vanilla(vanilla)
    entry = read_entry(bank_file)
    cls = int(entry["class"])
    if cls not in installed:
        raise Refused(f"class {cls} ({entry['name']}) is not in the installed char.dat: "
                      f"install its class/character mod first")
    why = story_locked(cls, vanilla)
    if why:
        raise Refused(f"story-locked: {why}")
    with protected(save_path, live, kit_dir) as backup:
        save = savegame.Save(str(save_path))
        if save.army_count + save.reserve_count >= savegame.SLOTS:
            raise Refused(f"the save is at the {savegame.SLOTS} limit "
                          f"({save.army_count} army + {save.reserve_count} reserve)")
        twin = None if allow_duplicate else unitbank.same_unit_in(save, entry)
        if twin is not None:
            raise Refused(f"this save already holds this unit (roster slot {twin}): the bank file was imported "
                          "before; importing it again would make a copy")
        res = unitbank.import_unit(save, entry, rows=sorted(installed))
        unitbank.clear_guest_flag(save, cls, on=True)         # a DLC character in the army has its guest flag set
        bad = unitbank.verify(save)
        if bad:
            raise Refused("the save would not verify, nothing written: " + "; ".join(bad))
        comp, why = companion(save_path)
        save.write()                     # reads its own bytes back before replacing the file
        extra = res["learned_extra"].get(res["serial"]) or []
        if comp is None and extra and why is None and skill_ids:
            comp = learned.sidecar_doc(str(save_path), skill_ids, {})        # no companion yet: start one
        if comp is not None:
            if extra:
                comp["units"][f"{res['serial']:016x}"] = dict(learned=sorted(set(extra)), name=entry["name"])
            write_companion(save_path, comp)
            res["companion"] = len(extra)
        elif extra or why:
            res["warnings"].append("the unit's evilities past the game's bitmap were not carried: " + (
                f"the save's .d5learn.json companion is not usable ({why})" if why else "the save has no companion and no Skill.dat was given"))
    if backup:
        res["backup"] = backup
    if move:
        try:
            res["moved_to"] = str(move_imported(bank_file))
        except OSError as ex:        # the unit IS in the save now: say the file stayed, do not fail the import
            res["warnings"].append(f"the bank file could not be moved to {IMPORTED_DIR}/ ({ex}); it is still in the bank")
    return res, entry


def listing(bank_dir):
    out = []
    for p in sorted(Path(bank_dir).glob("*" + EXT)):
        for e in json.loads(p.read_text()).get("units") or []:
            out.append((p.name, e["name"], e.get("title", ""), e["class"], e["level"]))
    return out


def main(argv=None, installed=None, vanilla=None):
    """installed / vanilla: {class id: name}, given by tests instead of reading the two databases"""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("save"), e.add_argument("unit"), e.add_argument("bank_dir")
    e.add_argument("--move", action="store_true", help="also take the unit out of the save copy")
    i = sub.add_parser("import")
    i.add_argument("bank_file"), i.add_argument("save")
    i.add_argument("--move", action="store_true", help="also move the bank file into the bank folder's imported/ subfolder")
    i.add_argument("--allow-duplicate", action="store_true", help="import even if the save already holds this unit")
    i.add_argument("--db", help="the INSTALLED game's Data/Database/Database_0.dat (which classes exist)")
    li = sub.add_parser("list")
    li.add_argument("bank_dir")
    for p in (e, i):
        p.add_argument("--live", action="store_true", help="the save is the game's real one: back it up first (state/save_backups), "
                       "refuse while the game runs")
        p.add_argument("--kit-dir", help=argparse.SUPPRESS)
        p.add_argument("--vanilla-db", default=VANILLA_DB, help="a clean copy of the game's Database_0.dat (default: "
                       "read the unmodded tables from --game)")
        p.add_argument("--game", help="the game folder: the unmodded char.dat comes from the kit's install backups; "
                       "import also reads the installed Database_0.dat there unless --db is given")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            for row in listing(a.bank_dir):
                print("{}: {} ({}), class {}, Lv{}".format(*row))
            return 0
        if vanilla is None:
            if a.vanilla_db:
                vanilla = char_names(a.vanilla_db)
            elif a.game:
                vanilla = game_char_names(a.game, a.kit_dir)
            else:
                raise Refused("--game (or --vanilla-db) is needed: the unmodded char.dat decides who is story-locked")
        if a.cmd == "import" and not a.db and a.game:
            a.db = os.path.join(a.game, "Data", "Database", "Database_0.dat")
        if a.cmd == "export":
            out, entry = export(a.save, a.unit, a.bank_dir, vanilla, move=a.move, live=a.live, kit_dir=a.kit_dir)
            print(f"{'moved' if a.move else 'exported'} {entry['name']} (class {entry['class']}, Lv{entry['level']}) -> {out}")
            if entry.get("unequipped"):
                print(f"  {entry['unequipped']} equipped items " + ("went into the save's item bag" if a.move else
                      "stay in the save; the bank file carries none"))
            if entry.get("backup"):
                print(f"  save backed up first: {entry['backup']}")
            return 0
        if installed is None:
            if not a.db:
                raise Refused("--db is needed: the installed Database_0.dat decides which classes exist")
            installed = char_names(a.db)
        res, entry = import_(a.bank_file, a.save, installed, vanilla, move=a.move,
                             skill_ids=skill_ids(a.db) if a.db else None, live=a.live, kit_dir=a.kit_dir,
                             allow_duplicate=a.allow_duplicate)
        print(f"imported {entry['name']} into roster slot {res['slot']} with serial {res['serial']}")
        if res.get("backup"):
            print(f"  save backed up first: {res['backup']}")
        for w in res["warnings"]:
            print("  note:", w)
        if res.get("moved_to"):
            print(f"  bank file moved to {res['moved_to']}")
        if res.get("companion"):
            print(f"  {res['companion']} evilities past the game's bitmap written to the save's .d5learn.json companion")
        return 0
    except (Refused, ValueError, OSError) as ex:
        print(f"refused: {ex}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
