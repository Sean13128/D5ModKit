"""Offline help and recruitment leases shared by the whole DRPG build.

Prior art: outfits._free_help_id/_free_quest and dbpatch's quest slot rules.
Reserve against every installed definition, including disabled mods, without
applying their competing patches to one table or writing installer state.
"""
import json
from pathlib import Path

from .. import database, dbpatch

# Engineering ids used by the existing Kit sample builder, not source-game data.
_SAMPLE_EVILITIES = {"drpg:55": (7120, 7121), "drpg:106": (7100,),
                     "drpg:311": (7110,)}


def _rows(table, patch):
    """Read each patch's claims in its own vanilla index/key namespace."""
    for key, updates in (patch.get("rows") or {}).items():
        if patch.get("key"):
            field = patch["key"]
            original = next((r for r in table.rows if str(r[field]) == str(key)), None)
        else:
            index = int(key)
            original = table.rows[index] if 0 <= index < len(table.rows) else None
        row = dict(original) if original is not None else {}
        row.update(updates)
        if row:
            yield row
    yield from patch.get("added") or []
    for insertion in patch.get("insert") or []:
        yield from insertion.get("rows") or []


def taken_namespaces(fs, installed_root, extra_roots=()):
    """(help ids, quest ids, quest progress slots) already owned by the vanilla tables, the installed mods and every
    extra root (candidate builds)."""
    help_table = database.load_table("charhelp.dat", fs.read("Database/Database_0.dat/charhelp.dat"))
    quest_table = database.load_table("Quest.dat", fs.read("Database/Database_0.dat/Quest.dat"))
    help_ids, quest_ids, progress = set(), set(), set()

    def take_help(row):
        help_ids.update(int(row[k]) for k in ("id", "char_id") if k in row)

    def take_quest(row):
        if "id" in row:
            quest_ids.add(int(row["id"]))
            if dbpatch.is_placeholder_quest(row):
                return
        if "sort_order" in row:
            progress.add(int(row["sort_order"]))

    for row in help_table.rows:
        take_help(row)
    for row in quest_table.rows:
        take_quest(row)
    roots = ([Path(installed_root)] if installed_root else []) + [Path(r) for r in extra_roots]
    for folder in sorted(f for r in roots if r.is_dir() for f in r.iterdir()):
        if not folder.is_dir() or not (folder / "mod.json").is_file():
            continue
        for filename, table, take in (("charhelp.dat", help_table, take_help),
                                       ("Quest.dat", quest_table, take_quest)):
            path = folder / "patches/db" / (filename + ".json")
            if path.is_file():
                for row in _rows(table, json.loads(path.read_text())):
                    take(row)

    return help_ids, quest_ids, progress


def reserve(roster_allocations, fs, installed_root, extra_roots=(), pinned=None, dirty_slots=()):
    """Return entry -> help_id, quest_id, quest_slot; fail before any emission.

    Recruitment shop ids stay below the Kit's hidden quest rows (1490), and
    progress slots stay below the native save's 1024 bytes. Placeholder rows do
    not own progress slots. Help ids are >=4000, following the Kit's rule.

    extra_roots: further `<...>/mods` folders (candidate builds about to be installed) whose help/quest rows count
    as taken, exactly like installed ones.  pinned: {entry id: {help_id, quest_id, quest_slot}} read from the lease
    manifest; those values are honoured as given (and counted as taken for everyone else), only unpinned entries
    are allocated.  Without a pin an id depends on the run's entry set and on what was installed that day, so a
    partial or later run hands out ids another pack already holds.
    """
    help_ids, quest_ids, progress = taken_namespaces(fs, installed_root, extra_roots)
    progress |= {int(x) for x in dirty_slots}     # DRPG-SAVESLOT1: a slot a save already marks is taken
    pinned = pinned or {}

    def unused(used, start, stop, label):
        value = next((n for n in range(start, stop) if n not in used), None)
        if value is None:
            raise ValueError(f"DRPG {label} exhausted: need {len(roster_allocations)} distinct leases against vanilla and every installed mod; reduce the roster or retire definitions explicitly")
        used.add(value)
        return value

    for pin in pinned.values():
        help_ids.add(int(pin["help_id"]))
        quest_ids.add(int(pin["quest_id"]))
        progress.add(int(pin["quest_slot"]))
    reserved = {}
    for entry_id in roster_allocations:
        if entry_id in pinned:
            reserved[entry_id] = {k: int(pinned[entry_id][k]) for k in ("help_id", "quest_id", "quest_slot")}
            continue
        reserved[entry_id] = dict(
            help_id=unused(help_ids, 4000, 65536, "help ids"),
            quest_id=unused(quest_ids, 1, dbpatch.PLACEHOLDER_FIRST, "recruitment quest ids below 1490"),
            quest_slot=unused(progress, 0, dbpatch.QUEST_SLOTS, "quest progress slots below 1024"))
    return reserved


def reserve_evilities(allocations, fs, installed_root, pinned=None):
    """Lease the samples' own evilities in the Kit's 7000..7999 band.

    Prior art: charstudio.free_evility_id/all_mod_evility_ids. The full vanilla
    Skill table and every installed mod own their ids, including disabled mods
    and runtime-only evility definitions. Returns old sample -> new id per base.
    """
    wanted = {key: _SAMPLE_EVILITIES[key] for key in allocations if key in _SAMPLE_EVILITIES}
    if not wanted:
        return {}
    # D4GAP1: a manifest base may pin its evility rows ({"7120": 7130}); a pin is read, never recomputed (the first
    # free id against the installed folder alone took 7000-7005, rows the D4 reviewed overlay holds for classes 2050-2150)
    reserved = {key: {int(old): int(new) for old, new in pinned[key].items()}
                for key in wanted if (pinned or {}).get(key) and set(map(int, pinned[key])) == set(wanted[key])}
    wanted = {key: v for key, v in wanted.items() if key not in reserved}
    if not wanted:
        return reserved
    table = database.load_table("Skill.dat", fs.read("Database/Database_0.dat/Skill.dat"))
    used = {int(row["id"]) for row in table.rows}
    for folder in sorted(Path(installed_root).iterdir() if installed_root else ()):
        if not folder.is_dir() or not (folder / "mod.json").is_file():
            continue
        path = folder / "patches/db/Skill.dat.json"
        if path.is_file():
            for row in _rows(table, json.loads(path.read_text())):
                if "id" in row:
                    used.add(int(row["id"]))
        runtime = folder / "patches/evilities/evilities.json"
        if runtime.is_file():
            doc = json.loads(runtime.read_text())
            used.update(int(key) for key in (doc.get("evilities") or {}))
        aliases = folder / "patches/evilities/aliases.json"
        if aliases.is_file():
            used.update(int(key) for key in json.loads(aliases.read_text()))
    used |= {i for key in reserved for i in reserved[key].values()}
    free = iter(n for n in range(7000, 8000) if n not in used)
    for entry_id, old_ids in wanted.items():
        remap = {}
        for old in old_ids:
            new = next(free, None)
            if new is None:
                raise ValueError("DRPG own evility ids 7000..7999 exhausted against vanilla and every installed mod; reduce the roster or retire definitions explicitly")
            remap[old] = new
        reserved[entry_id] = remap
    return reserved
