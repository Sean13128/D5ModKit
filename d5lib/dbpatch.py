"""Row-level database patches (composable between mods).

Stored in a mod as  patches/db/<member name>.json :
{
  "table": "char.dat",
  "rows":   {"12": {"name_EN": "Killer", "base_HP": 50}},     # edits to existing rows (by index)
  "added":  [{...all fields...}, ...],                        # rows appended at the end
  "sections": {"<section>": {same structure}}                 # sub-tables, if the table has any
}
Values: ints/floats/strings as-is; `bytes` fields as hex strings.
"""
import json

from . import database
from .modsys import register_finalizer, register_patch_handler

DB_ARCHIVE = "Database/Database_0.dat"


def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return v


def _row_values(row):
    return {k: _jsonable(v) for k, v in row.to_dict().items()}


def diff_table(vanilla, edited) -> dict:
    out = {"table": vanilla.name}
    rows = {}
    n = min(len(vanilla.rows), len(edited.rows))
    for i in range(n):
        a, b = vanilla.rows[i], edited.rows[i]
        if bytes(a.raw) == bytes(b.raw) and a.strs == b.strs:
            continue
        ch = {}
        for f in vanilla.schema.fields:
            va, vb = a._get(f), b._get(f)
            if va != vb:
                ch[f.name] = _jsonable(vb)
        if ch:
            rows[str(i)] = ch
    if rows:
        out["rows"] = rows
    if len(edited.rows) > len(vanilla.rows):
        out["added"] = [_row_values(r) for r in edited.rows[len(vanilla.rows):]]
    if len(edited.rows) < len(vanilla.rows):
        out["truncate"] = len(edited.rows)
    secs = {}
    for k, sub in vanilla.sections.items():
        if k in edited.sections:
            d = diff_table(sub, edited.sections[k])
            if len(d) > 1:
                secs[k] = d
    if secs:
        out["sections"] = secs
    return out


def is_empty(patch) -> bool:
    return not patch or all(k == "table" for k in patch)


def apply_patch(table, patch: dict, strict=False, placed=None):
    """Apply a patch dict to a Table in place. Returns list of warnings.  placed: a list that gets the row index of
    each added row, in order (an added row can fill one of the game's reserved rows, _reserved_row)."""
    warn = []
    for idx, fields in (patch.get("rows") or {}).items():
        i = int(idx)
        if i >= len(table.rows):
            warn.append(f"{table.name}: row {i} does not exist")
            continue
        row = table.rows[i]
        for name, v in fields.items():
            _set(row, name, v, warn, table.name)
    if "truncate" in patch:
        del table.rows[int(patch["truncate"]):]
    first = None                                     # char.dat: id -> index of its first row (_reserved_row)
    for vals in patch.get("added") or []:
        row = table.new_row()
        for name, v in vals.items():
            _set(row, name, v, warn, table.name)
        if first is None and str(getattr(table, "name", "")).startswith("char.dat"):
            first = {}
            for i, r in enumerate(table.rows):
                first.setdefault(r["id"], i)
        si = _reserved_row(table, row, first)
        if si is not None:
            table.rows[si] = row
        else:
            table.rows.append(row)
            if first is not None and "id" in row:
                first.setdefault(row["id"], len(table.rows) - 1)
        if placed is not None:
            placed.append(si if si is not None else len(table.rows) - 1)
    for k, sp in (patch.get("sections") or {}).items():
        if k in table.sections:
            warn += apply_patch(table.sections[k], sp, strict)
        else:
            warn.append(f"{table.name}: unknown section {k}")
    if strict and warn:
        raise ValueError("\n".join(warn))
    return warn


RESERVED_NAMES = {"Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy"}   # the game's empty char.dat rows


def _reserved_row(table, row, first=None):
    """char.dat: an added row with the id of one of the game's empty reserved rows ('DLC Dummy' 970 ...) fills that
    row -> its index (None: append).  Kit versions before 1.4 appended new characters with such an id, and the game
    reads the first row of an id: the dummy's name, stats and description with the new character's sprites.
    first: {id: index of its first row} (apply_patch keeps one: a scan of the table per added row was slow)."""
    if not str(getattr(table, "name", "")).startswith("char.dat") or "id" not in row or "name_EN" not in row:
        return None
    rid = row["id"]
    if first is not None:
        i = first.get(rid)
        idx = [] if i is None else [i]
    else:
        idx = [next((i for i, r in enumerate(table.rows) if r["id"] == rid), None)]
        idx = [i for i in idx if i is not None]
    for i in idx:
        r = table.rows[i]
        return i if r["name_EN"] in RESERVED_NAMES and row["name_EN"] not in RESERVED_NAMES else None
    return None


RENAMED = {"story_flag": "evility_count"}       # old field name in saved patches -> current name


def _set(row, name, v, warn, tname):
    if name not in row and RENAMED.get(name) in row:
        name = RENAMED[name]
    if name not in row:
        warn.append(f"{tname}: unknown field {name}")
        return
    try:
        if row.field(name).type == "str":
            row.set(name, v, truncate=True)
        else:
            row.set(name, v)
    except Exception as e:
        warn.append(f"{tname}.{name}: {e}")


QUEST_LINE = 36          # characters per quest description line (the game's own lines: 33 median, 36 at most)


def quest_lines(text, width=QUEST_LINE, lines=5):
    """a quest description -> its 5 lines (desc1..desc5), word-wrapped like the game's own; an explicit line break
    in `text` starts a new line.  Text that doesn't fit in 5 lines is cut."""
    import textwrap
    out = []
    for para in str(text or "").replace("\r", "").split("\n"):
        out += textwrap.wrap(para, width) or [""]
    while out and not out[-1]:
        out.pop()
    return (out + [""] * lines)[:lines]


HELP_LINE = 42           # characters per character-help line (the game's own: 42 at most)


def help_lines(lines, width=HELP_LINE, count=3):
    """a character's help text (one string or its lines) -> the 3 lines of charhelp.dat, word-wrapped to the game's
    width; text that doesn't fit is cut with "..." (a line's byte limit is checked when it is set)"""
    import textwrap
    if isinstance(lines, str):
        lines = [lines]
    out = []
    for para in "\n".join(str(x or "") for x in lines).replace("\r", "").split("\n"):
        out += textwrap.wrap(para, width) or ([""] if para.strip() == "" and out else [])
    while out and not out[-1]:
        out.pop()
    if len(out) > count:
        last = " ".join(out[count - 1:])
        cut = last[:width - 3]
        if " " in cut and last[width - 3:width - 2] not in ("", " "):
            cut = cut.rsplit(" ", 1)[0]                  # end on a whole word
        out = out[:count - 1] + [cut.rstrip(" ,;:") + "..."]
    return (out + [""] * count)[:count]


def default_help(name, title=None):
    """the description a new character gets when none was typed: its own help row, never the copied character's or
    a reserved dummy's ('DLC Dummy Description Row 1')"""
    return [f"{name}, {title}." if title and title != name else f"{name}.", "", ""]


QUEST_SLOTS = 0x400                 # progress bytes per quest state in a save
PLACEHOLDER_IDS = range(1999, 1899, -1)   # check_quest_slots' hidden rows; new quests take ids below them
PLACEHOLDER_FIRST = 1900


def is_placeholder_quest(row):
    return row["id"] in PLACEHOLDER_IDS


def free_quest_slot(table, exclude=None, reserved=()):
    """Smallest Quest.dat sort_order no row uses (nor `reserved`: the slots of every mod's quests, switched on or not,
    so a slot stays one quest's for good).  The board needs it below the row count; the install keeps it so with
    hidden rows (check_quest_slots)."""
    used = {r["sort_order"] for r in table.rows if r is not exclude and not is_placeholder_quest(r)} | set(reserved)
    n = 0
    while n in used:
        n += 1
    return n


def check_quest_slots(table, reserved=()):
    """Quest.dat sort_order is the quest's progress slot in the save (completed / accepted / seen bytes, 0x400 each,
    d5lib.savegame), and the Quest-shop board (ids < 2000) only scans slots 0 .. row count - 1 (0x1407f3300); request
    quests are listed by another routine (vanilla 9501/9502 sit at 517/518).  A slot must therefore stay the same
    whichever mods are installed, or saves show one quest's progress on another (a recruit quest done, its character
    missing).  Run once on the finished table (every mod's rows in):
      * two rows on one slot: the later one moves to a slot no other row and no mod (`reserved`) uses, with a warning
        (vanilla rows come first and never move; mods made with the kit never share a slot);
      * a shop quest on a slot >= the row count (mods with lower slots are switched off): it keeps its slot and hidden
        rows are added until the board scans it.  They have ids PLACEHOLDER_IDS, slots above the row count (never
        scanned) and themselves as prerequisite (never offered)."""
    warn = []
    seen = set()
    bad = []
    rows = [r for r in table.rows if not is_placeholder_quest(r)]
    for r in rows:
        s = r["sort_order"]
        if s >= QUEST_SLOTS or s in seen:
            bad.append(r)
        else:
            seen.add(s)
    for r in bad:
        old = r["sort_order"]
        n = 0
        while n in seen or n in reserved:
            n += 1
        r.set("sort_order", n)
        seen.add(n)
        why = "is taken by another quest" if old < QUEST_SLOTS else "is not a progress slot (0-1023)"
        warn.append(f"Quest.dat: quest {r['id']} sort_order {old} {why}; using {n}. Set sort_order to {n} in your mod "
                    f"to keep it")
    table.rows[:] = rows
    need = max([r["sort_order"] + 1 for r in rows if r["id"] < 2000] + [0])
    if need > len(rows):
        ids = {r["id"] for r in rows}
        free_ids = [i for i in PLACEHOLDER_IDS if i not in ids]
        free_slots = (s for s in range(need, QUEST_SLOTS) if s not in seen)
        for k in range(need - len(rows)):
            if not free_ids:
                warn.append("Quest.dat: no ids left for the hidden rows that keep quest slots; the board may skip "
                            "quests on the highest slots")
                break
            qid, slot = free_ids.pop(0), next(free_slots, None)
            if slot is None:
                break
            row = table.add_row(copy_from=0)
            for f, v in (("id", qid), ("sort_order", slot), ("prereq_quest1", qid), ("prereq_quest2", 0),
                         ("prereq_quest3", 0), ("prereq_quest4", 0), ("prereq_quest_count", 1), ("important", 0),
                         ("reward_type", 1), ("reward_value", 0), ("reward_count", 0), ("unlock_stage", 0),
                         ("unlock_stage2", 0)):
                row.set(f, v)
            for lang in ("JP", "EN", "FR", "CHN", "KOR"):
                for f in [f"name_{lang}", f"client_{lang}"] + [f"desc{i}_{lang}" for i in range(1, 6)]:
                    if f in row.keys():
                        row.set(f, "")
            seen.add(slot)
    return warn


def new_quest_id(table, mods=()):
    """an id for a new shop quest: above every id the table and these mods (all of them, switched on or not) use, below
    the hidden rows' PLACEHOLDER_IDS"""
    used = {r["id"] for r in table.rows}
    for m in mods:
        patch = m.load_patch("db", "Quest.dat.json") or {}
        used |= {int(r["id"]) for r in patch.get("added") or [] if "id" in r}
    return max(i for i in used | {0} if i < PLACEHOLDER_FIRST) + 1


def mod_quest_slots(mods):
    """{slot: [(mod id, quest id)]} of the quests these mods add (their Quest.dat patches as written)"""
    out = {}
    for m in mods:
        patch = m.load_patch("db", "Quest.dat.json") or {}
        for r in patch.get("added") or []:
            if "sort_order" in r:
                out.setdefault(int(r["sort_order"]), []).append((m.id, r.get("id")))
        for r in (patch.get("rows") or {}).values():
            if "sort_order" in r:
                out.setdefault(int(r["sort_order"]), []).append((m.id, r.get("id")))
    return out


EVILITIES = [f"evility{k}" for k in range(1, 5)]


def fix_evilities(row):
    """Innate evilities: the engine uses evility1..evility<evility_count> (0x1402c0040), so gaps are closed and the
    count is set to the number of evilities.  -> True if the row changed"""
    ev = [row[f] for f in EVILITIES if row[f]]
    want = ev + [0] * (len(EVILITIES) - len(ev))
    changed = [row[f] for f in EVILITIES] != want or row["evility_count"] != len(ev)
    if changed:
        for f, v in zip(EVILITIES, want):
            row.set(f, v)
        row.set("evility_count", len(ev))
    return changed


def _patched_rows(table, patch):
    rows = [table.rows[int(i)] for i in (patch.get("rows") or {}) if int(i) < len(table.rows)]
    n = len(patch.get("added") or [])
    return rows + (table.rows[-n:] if n else [])


def _handler(ctx, mod, patch_dir):
    for fname in mod.list_patches("db"):
        patch = mod.load_patch("db", fname)
        member = patch.get("table") or fname[:-5]
        vpath = f"{DB_ARCHIVE}/{member}"
        table = database.load_table(member, ctx.get(vpath))
        warns = apply_patch(table, patch)
        if member.lower() == "quest.dat":
            ctx.quest_slots_check = True              # once every mod is in: _finalize_quests
        if member.lower() == "char.dat":
            for r in _patched_rows(table, patch):
                if fix_evilities(r):
                    ctx.log(f"  {r['name_EN']} ({r['id']}): {r['evility_count']} innate evilities")
        for w in warns:
            ctx.log("  warning: " + w)
        ctx.put(vpath, table.to_bytes())
        ctx.log(f"  database: {member} ({len(patch.get('rows', {}))} edited, {len(patch.get('added', []))} added rows)")


register_patch_handler("db", _handler, order=10)


def _finalize_quests(ctx):
    """check_quest_slots once on the finished Quest.dat.  Run after each mod it moved a quest whose slot only becomes
    valid with a later mod's rows in (Thunderlady's 519 went to Henna's 396 and Henna to 519, 2026-10-14)."""
    if not getattr(ctx, "quest_slots_check", False):
        return
    import os
    from .modsys import Mod
    vpath = f"{DB_ARCHIVE}/Quest.dat"
    table = database.load_table("Quest.dat", ctx.get(vpath))
    on = set(getattr(ctx, "mod_folders", []) or [])
    others = []
    for parent in {os.path.dirname(f) for f in on}:
        for d in sorted(os.listdir(parent)):
            full = os.path.join(parent, d)
            if full not in on and os.path.isfile(os.path.join(full, "mod.json")):
                others.append(Mod(full))
    reserved = set(mod_quest_slots(others))           # switched-off mods' slots: a moved quest never takes them
    n = len(table.rows)
    for w in check_quest_slots(table, reserved):
        ctx.log("  warning: " + w)
    if len(table.rows) > n:
        ctx.log(f"  quests: {len(table.rows) - n} hidden rows keep every quest on its own progress slot")
    ctx.put(vpath, table.to_bytes())


register_finalizer(_finalize_quests)
