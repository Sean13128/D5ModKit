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
from .modsys import register_patch_handler

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


def apply_patch(table, patch: dict, strict=False):
    """Apply a patch dict to a Table in place. Returns list of warnings."""
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
    for vals in patch.get("added") or []:
        row = table.new_row()
        for name, v in vals.items():
            _set(row, name, v, warn, table.name)
        si = _reserved_row(table, row)
        if si is not None:
            table.rows[si] = row
        else:
            table.rows.append(row)
    for k, sp in (patch.get("sections") or {}).items():
        if k in table.sections:
            warn += apply_patch(table.sections[k], sp, strict)
        else:
            warn.append(f"{table.name}: unknown section {k}")
    if strict and warn:
        raise ValueError("\n".join(warn))
    return warn


RESERVED_NAMES = {"Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy"}   # the game's empty char.dat rows


def _reserved_row(table, row):
    """char.dat: an added row with the id of one of the game's empty reserved rows ('DLC Dummy' 970 ...) fills that
    row -> its index (None: append).  Kit versions before 1.4 appended new characters with such an id, and the game
    reads the first row of an id: the dummy's name, stats and description with the new character's sprites."""
    if not str(getattr(table, "name", "")).startswith("char.dat") or "id" not in row or "name_EN" not in row:
        return None
    rid = row["id"]
    for i, r in enumerate(table.rows):
        if r["id"] == rid:
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


def free_quest_slot(table, exclude=None):
    """Smallest Quest.dat sort_order no other row uses. Always below the row count, which the quest board requires."""
    used = {r["sort_order"] for r in table.rows if r is not exclude}
    n = 0
    while n in used:
        n += 1
    return n


def check_quest_slots(table):
    """Quest.dat sort_order is the quest's progress slot in the save (completed / accepted / seen bytes, 0x400 each),
    and the Quest-shop board (ids < 2000) only scans slots 0 .. row count - 1 (0x1407f3300); request quests are listed
    by another routine (vanilla 9501/9502 sit at 517/518). A shop quest outside that range never shows, two rows on one
    slot share progress. Moves such rows to free slots (earlier rows keep theirs, so vanilla rows never move)."""
    warn = []
    limit = min(len(table.rows), 0x400)
    seen = set()
    bad = []
    for r in table.rows:
        s = r["sort_order"]
        if s >= 0x400 or s in seen or (r["id"] < 2000 and s >= limit):
            bad.append(r)
        else:
            seen.add(s)
    for r in bad:
        old = r["sort_order"]
        n = 0
        while n in seen:
            n += 1
        r.set("sort_order", n)
        seen.add(n)
        why = "is taken by another quest" if old < limit else f"is not below the number of quests ({len(table.rows)})"
        warn.append(f"Quest.dat: quest {r['id']} sort_order {old} {why}, so the quest board would skip it; using {n}. "
                    f"Set sort_order to {n} in your mod to keep it")
    return warn


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
            warns += check_quest_slots(table)
        if member.lower() == "char.dat":
            for r in _patched_rows(table, patch):
                if fix_evilities(r):
                    ctx.log(f"  {r['name_EN']} ({r['id']}): {r['evility_count']} innate evilities")
        for w in warns:
            ctx.log("  warning: " + w)
        ctx.put(vpath, table.to_bytes())
        ctx.log(f"  database: {member} ({len(patch.get('rows', {}))} edited, {len(patch.get('added', []))} added rows)")


register_patch_handler("db", _handler, order=10)
