"""Row-level database patches (composable between mods).

Stored in a mod as  patches/db/<member name>.json :
{
  "table": "char.dat",
  "rows":   {"12": {"name_EN": "Killer", "base_HP": 50}},     # edits to existing rows (by index)
  "insert": [{"before": 2121, "rows": [{...}, ...]}],         # rows put *inside* the table, at a key
  "added":  [{...all fields...}, ...],                        # rows appended at the end
  "sections": {"<section>": {same structure}}                 # sub-tables, if the table has any
}
Values: ints/floats/strings as-is; `bytes` fields as hex strings.

`insert` exists because some tables are not id-sorted (item.dat) and because a row's *position* can
carry meaning: Overlord's build puts three item rows between 2115 and 2121 instead of appending them.
An anchor is a **key value**, never an index, so two mods' patches compose: `{"before": 2121}` means
"in front of the row whose id is 2121, wherever that row is by then". Anchors must resolve to exactly
one row -- a key that repeats (`charhelp.dat`) or an anchor that is absent is refused rather than
guessed; `occurrence` (1-based) picks one row when a table is known to repeat a key.

Order of application, so that two kinds of address mean what they say: `rows` edits (base indices),
then `truncate`, then `insert`, then `added`. A positional edit therefore never moves because of an
insertion in the same patch.

`rows` keys are **row indices**, and that is the only address an index-keyed patch has. A patch that
came from diffing a whole table (the converted Overlord packs) may say which row it *means* with
`expect`, so an index that no longer carries that row is refused instead of written:

  "expect": {"by": "id", "rows": {"14": 50, "30": 310}}     # row 14 must be the row whose id is 50

`by` is a column name, or `<column>#ord` for a table whose identity column repeats (`charhelp.dat`
has 334 rows and 330 ids; `"id#ord"` names the 3rd row with a given id as `"7#3"`). The values are
compared before anything is written: a mismatch refuses **that row** with a warning (and raises in
`strict` mode) and the rest of the patch still applies. A table that is not ordered the way the patch
was written sees its edits refused, not moved onto its neighbours.

A patch may instead declare `"key": "id"`, which makes the `rows` keys *values of that column*; that
is for a pack that is authored by id rather than converted from a whole table.
"""
import json

from . import database
from . import ordercheck
from .modsys import register_finalizer, register_patch_handler

DB_ARCHIVE = "Database/Database_0.dat"

# Members with no identity column at all: the row is named by this column instead.  SugorokuMapSetting.dat
# is four difficulty rows with no `id` (unk_000 is 0..3); its name is what a person means by "the Overlord tier".
IDENTITY_COLUMN = {"SugorokuMapSetting.dat": "name_EN"}


def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return v


def _row_values(row):
    return {k: _jsonable(v) for k, v in row.to_dict().items()}


def diff_table(vanilla, edited) -> dict:
    out = {"table": vanilla.name}
    key = _identity_key(vanilla, edited)
    if key is not None:
        try:
            inserted = _diff_inserts(vanilla, edited, key, out)
        except _NotInsertOnly:
            inserted = False
        if inserted:
            _add_expect(vanilla, out)
            _diff_sections(vanilla, edited, out)
            return out
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
    _add_expect(vanilla, out)
    _diff_sections(vanilla, edited, out)
    return out


def _expect_column(table):
    """the column that names every row of a table once, for an `expect` map: `id`, or `<schema key>#ord` when the
    column repeats (`charhelp.dat`, `charPersonal.dat`). None when no column names the rows."""
    for cand in (getattr(table.schema, "key", None), "id", IDENTITY_COLUMN.get(table.name)):
        if not cand:
            continue
        try:
            vals = [r[cand] for r in table.rows]
        except (KeyError, IndexError, TypeError):
            continue
        return cand if len(set(vals)) == len(vals) else f"{cand}#ord"
    return None


def _add_expect(vanilla, out):
    """record, for every row an index-keyed patch edits, the identity that row had when the patch was made.

    A patch that names its rows by index is only meaningful against the table it was diffed from; this is what
    lets `apply_patch` refuse an edit (rather than write it onto a neighbour) once another mod has moved rows."""
    rows = out.get("rows") or {}
    if not rows:
        return
    by = _expect_column(vanilla)
    if not by:
        return
    ident = row_identities(vanilla, by) or {}
    named = {str(i): ident[int(i)] for i in rows if int(i) in ident}
    if named:
        out["expect"] = {"by": by, "rows": named}


def _diff_sections(vanilla, edited, out):
    secs = {}
    for k, sub in vanilla.sections.items():
        if k in edited.sections:
            d = diff_table(sub, edited.sections[k])
            if len(d) > 1:
                secs[k] = d
    if secs:
        out["sections"] = secs


class _NotInsertOnly(ValueError):
    """the edit is not `baseline + inserted rows`; the positional diff has to describe it"""


def _identity_key(base, target):
    """the column that names a row, when it names every row on both sides exactly once."""
    if not base.rows or not target.rows:
        return None
    rows = list(base.rows) + list(target.rows)
    for key in (getattr(base.schema, "key", None), "id"):
        if not key:
            continue
        try:
            vals = [r[key] for r in rows]
        except (KeyError, IndexError, TypeError):
            continue
        if not all(isinstance(v, int) for v in vals):
            continue
        n = len(base.rows)
        if len(set(vals[:n])) == n and len(set(vals[n:])) == len(vals) - n:
            return key
    return None


def _row_changes(a, b, schema):
    ch = {}
    for f in schema.fields:
        va, vb = a._get(f), b._get(f)
        if va != vb:
            ch[f.name] = _jsonable(vb)
    return ch


def _diff_inserts(vanilla, edited, key, out) -> bool:
    """``vanilla`` rows are all present, in order, in ``edited``: express the rest as `insert`.

    Returns False when the difference is only a tail append (the plain `added` form already says
    exactly that), True when at least one batch of rows has to go *inside* the table.  Raises
    `_NotInsertOnly` for a reordering or a changed key, which insertion cannot express.
    """
    import difflib
    base_keys = [r[key] for r in vanilla.rows]
    tgt_keys = [r[key] for r in edited.rows]
    rows, inserts, added = {}, [], None
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base_keys, tgt_keys,
                                                        autojunk=False).get_opcodes():
        if tag == "equal":
            for bi, ti in zip(range(i1, i2), range(j1, j2)):
                ch = _row_changes(vanilla.rows[bi], edited.rows[ti], vanilla.schema)
                if ch:
                    rows[str(bi)] = ch
        elif tag == "insert" and j2 == len(tgt_keys) and i2 == len(base_keys):
            added = [_row_values(r) for r in edited.rows[j1:j2]]
        elif tag == "insert":
            inserts.append({"before": tgt_keys[j2], "rows": [_row_values(r) for r in edited.rows[j1:j2]]})
        else:
            raise _NotInsertOnly(f"{tag} at base {i1}..{i2} / target {j1}..{j2}")
    if not inserts:
        return False
    if rows:
        out["rows"] = rows
    out["insert"] = inserts
    if added:
        out["added"] = added
    return True



def is_empty(patch) -> bool:
    return not patch or all(k == "table" for k in patch)


def row_identities(table, by):
    """{row index: identity} for an `expect` spec's `by`: a column name, or `<column>#ord` when the column
    repeats (`charhelp.dat`). Returns None when the table has no such column, so a caller can refuse rather
    than check nothing."""
    col, sep, kind = str(by).partition("#")
    out, seen = {}, {}
    for i, row in enumerate(table.rows):
        try:
            v = row[col]
        except KeyError:
            return None
        if sep and kind == "ord":
            n = seen.get(v, 0) + 1
            seen[v] = n
            out[i] = f"{v}#{n}"
        else:
            out[i] = v
    return out


def check_expect(table, patch: dict):
    """(refused indices, warnings) for a patch's `expect` map: the rows it edits whose identity is not the one
    the patch names. An empty warning list with no refused indices means every edited row is the row meant.

    `expect` names the identity of the rows an index-keyed patch was written against.  Nothing is checked
    when the patch does not carry one (an authored-by-index patch), and a table that cannot be keyed by the
    named column refuses every edit rather than checking none of them."""
    spec = patch.get("expect")
    rows = patch.get("rows") or {}
    if not spec or not rows:
        return set(), []
    by = spec.get("by") if isinstance(spec, dict) else None
    want = (spec.get("rows") if isinstance(spec, dict) else None) or {}
    if not by:
        return {int(i) for i in rows}, [f"{table.name}: `expect` needs a `by` column; every positional edit refused"]
    have = row_identities(table, by)
    if have is None:
        return {int(i) for i in rows}, [f"{table.name}: cannot key this table by {by!r}; every positional edit refused"]
    bad, warn = set(), []
    for idx in rows:
        i = int(idx)
        if str(i) not in want:
            bad.add(i)
            warn.append(f"{table.name}: row {i} has no identity in `expect`; edit refused")
            continue
        expected = want[str(i)]
        got = have.get(i)
        if str(got) != str(expected):
            bad.add(i)
            warn.append(f"{table.name}: row {i} is {by} {got!r}, patch expects {expected!r}; edit refused")
    return bad, warn


def apply_patch(table, patch: dict, strict=False, placed=None, inserted=None):
    """Apply a patch dict to a Table in place. Returns list of warnings.  placed: a list that gets the row index of
    each added row, in order (an added row can fill one of the game's reserved rows, _reserved_row).  inserted: a
    list that gets each row created by an `insert` entry, in order.

    `expect` (see the module docstring) is checked before a single field is written: an index whose row is not
    the row the patch names is refused, so a table shifted by another mod loses the edit instead of writing it
    onto a neighbour."""
    warn = []
    key = patch.get("key")
    by_key = None
    key_dead = False
    if key and not patch.get("expect"):
        by_key = {}
        for i, r in enumerate(table.rows):
            try:
                by_key.setdefault(int(r[key]), i)
            except (KeyError, TypeError, ValueError):
                by_key = None
                key_dead = True
                warn.append(f"{table.name}: cannot key this table by {key!r}; every edit refused")
                break
    refused, expect_warn = check_expect(table, patch)
    warn += expect_warn
    if refused and strict:
        raise ValueError("; ".join(expect_warn))
    for idx, fields in (patch.get("rows") or {}).items():
        if key_dead:
            continue
        if by_key is not None:
            i = by_key.get(int(idx))
            if i is None:
                warn.append(f"{table.name}: no row with {key} {idx}")
                continue
        else:
            i = int(idx)
        if i in refused:
            continue
        if i >= len(table.rows):
            warn.append(f"{table.name}: row {i} does not exist")
            continue
        row = table.rows[i]
        for name, v in fields.items():
            _set(row, name, v, warn, table.name)
    if "truncate" in patch:
        del table.rows[int(patch["truncate"]):]
    for spec in patch.get("insert") or []:
        warn += _insert(table, spec, patch, inserted)
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
    for _row in table.rows:            # EVCAP5: every row this patch touched, added or inserted
        fix_evility_category(_row, table.name)
    if strict and warn:
        raise ValueError("\n".join(warn))
    return warn


RESERVED_NAMES = {"Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy"}   # the game's empty char.dat rows

# A learnable evility's `category` is which tab of the evility list it appears under (the screen filters with
# `category == tab || subcategory == tab`, tab 0 = no filter).  Not one of the game's own 587 learnable rows has
# category 0; a row with 0 is only reachable on the unfiltered tab, so an imported evility would vanish from the
# list as soon as a player picks any category tab (and would never appear in a category-tabbed pick list).
# These are the categories the game's own learnable rows of each effect group use most often (measured on the
# vanilla table); 1 is the fallback for a group the game does not use.
EVILITY_CATEGORY = {0: 9, 1: 9, 2: 1, 3: 2, 4: 1, 5: 1, 6: 1, 7: 4, 8: 11, 9: 5, 10: 1, 11: 5, 12: 12,
                    13: 12, 14: 2, 15: 5, 16: 12, 17: 1, 18: 1, 19: 1, 20: 1, 21: 2, 22: 1, 24: 18,
                    25: 1, 26: 1, 27: 18, 28: 14, 29: 2, 30: 1}


def fix_evility_category(row, tname):
    """Give a learnable evility row a display category if it has none.  -> True if the row changed.

    Only rows the game would offer to equip are touched (kind 0 = normal, and a Mana cost to learn); an
    innate/unique/rank row and a system row keep whatever they have.  A patch that names a category is never
    overridden: this only fills a 0 that no learnable row of the game's own table has.
    """
    if str(tname).lower() != "skill.dat":
        return False
    if "category" not in row or row["category"]:
        return False
    if row.get("kind") != 0 or not row.get("mana_cost"):
        return False
    row.set("category", EVILITY_CATEGORY.get(row.get("effect_group"), 1))
    return True


def row_key(table, patch=None):
    """the column an `insert` anchor names: the patch's `key`, else the schema's, else `id` if every row has one."""
    explicit = (patch or {}).get("key")
    if explicit:
        return explicit
    key = getattr(table.schema, "key", None)
    if key and all(key in r for r in table.rows):
        return key
    if table.rows and all("id" in r for r in table.rows):
        return "id"
    return None


def anchor_index(table, anchor, patch=None, occurrence=None):
    """index of the row an insert entry names, or raise ValueError (absent / ambiguous / no key column).

    `occurrence` is 1-based and only for tables that repeat a key: without it a repeated key is refused,
    because "before id 12" would silently pick one of several rows.
    """
    key = row_key(table, patch)
    if key is None:
        raise ValueError(f"{table.name}: no key column to anchor an insert on")
    hits = [i for i, r in enumerate(table.rows) if r.get(key) == anchor]
    if not hits:
        raise ValueError(f"{table.name}: no row with {key} == {anchor!r} to insert at")
    if len(hits) > 1 and occurrence is None:
        raise ValueError(f"{table.name}: {len(hits)} rows have {key} == {anchor!r}; an insert needs `occurrence`")
    n = int(occurrence or 1)
    if n < 1 or n > len(hits):
        raise ValueError(f"{table.name}: occurrence {n} of {key} == {anchor!r} does not exist ({len(hits)} rows)")
    return hits[n - 1]


def _insert(table, spec, patch, inserted=None):
    """one `insert` entry: {"before"|"after": <key>, "rows": [...], "occurrence": n}"""
    if not isinstance(spec, dict):
        return [f"{table.name}: an insert entry must be an object"]
    where = "before" if "before" in spec else "after" if "after" in spec else None
    if where is None:
        return [f"{table.name}: an insert entry needs 'before' or 'after'"]
    vals_list = spec.get("rows") or []
    if not vals_list:
        return [f"{table.name}: insert before/after {spec[where]!r} has no rows"]
    try:
        i = anchor_index(table, spec[where], patch, spec.get("occurrence"))
    except (ValueError, TypeError) as e:
        return [str(e)]
    warn, new = [], []
    for vals in vals_list:
        row = table.new_row()
        for name, v in vals.items():
            _set(row, name, v, warn, table.name)
        new.append(row)
    at = i if where == "before" else i + 1
    table.rows[at:at] = new
    if inserted is not None:
        inserted.extend(new)
    if not warn and "id" in (new[0] if new else {}) and spec.get("unique", True):
        ids = [r["id"] for r in new]
        if len(set(ids)) != len(ids):
            warn.append(f"{table.name}: inserted rows repeat an id {ids}")
    return warn



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
PLACEHOLDER_IDS = range(1999, 1489, -1)   # check_quest_slots' hidden rows; new quests take ids below them.  510 ids: the most
                                          # the board can ever need (1024 slots - 516 vanilla rows = 508).  QBOARD1: with
                                          # 100 the board skipped every quest on a slot >= row count (FUN_1407ec450)
PLACEHOLDER_FIRST = 1490


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
    d5lib.savegame), and the Quest-shop board (ids < 2000) only scans slots 0 .. row count - 1 (board builder FUN_1407ec450); request
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
            # no unscanned slot left: share the highest real quest's slot.  The board takes the first row (lowest id)
            # on a slot, and that is the real quest, so the hidden row is never looked at (QBOARD1, FUN_1407ec450).
            qid, slot = free_ids.pop(0), next(free_slots, need - 1)
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


def _patched_rows(table, patch, inserted=()):
    rows = [table.rows[int(i)] for i in (patch.get("rows") or {}) if int(i) < len(table.rows)]
    n = len(patch.get("added") or [])
    return rows + list(inserted) + (table.rows[-n:] if n else [])


def _handler(ctx, mod, patch_dir):
    for fname in mod.list_patches("db"):
        patch = mod.load_patch("db", fname)
        member = patch.get("table") or fname[:-5]
        vpath = f"{DB_ARCHIVE}/{member}"
        table = database.load_table(member, ctx.get(vpath))
        inserted = []
        warns = apply_patch(table, patch, inserted=inserted)
        if member.lower() == "quest.dat":
            ctx.quest_slots_check = True              # once every mod is in: _finalize_quests
        if member.lower() == "dungeon.dat":
            ctx.stage_check = True                    # once every mod is in: _finalize_stages
        if member in ordercheck.ORDER_CRITICAL:
            ctx.order_check = True                    # once every mod is in: _finalize_order
        if member.lower() == "char.dat":
            for r in _patched_rows(table, patch, inserted):
                if fix_evilities(r):
                    ctx.log(f"  {r['name_EN']} ({r['id']}): {r['evility_count']} innate evilities")
        for w in warns:
            ctx.log("  warning: " + w)
        ctx.put(vpath, table.to_bytes())
        ins = len(patch.get("insert") or [])
        ctx.log(f"  database: {member} ({len(patch.get('rows', {}))} edited, "
                + (f"{ins} insert point(s), " if ins else "")
                + f"{len(patch.get('added', []))} added rows)")


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


def _finalize_stages(ctx):
    """Every stage the stage list can show needs a row in DemoCheckDataBase.dat (map id, has a story scene, its
    flag): the list's stage panel looks the highlighted stage up there by binary search (Steam build 0x14063ca4b) and
    reads the row it finds -- for a stage with no row it read address 0 and the game closed the moment the cursor
    reached the new stage (2026-10-16, in game).  Mods' stages get (map id, 0, 0): no scene; the table stays
    sorted."""
    if not getattr(ctx, "stage_check", False):
        return
    import struct
    dvp = f"{DB_ARCHIVE}/dungeon.dat"
    cvp = f"{DB_ARCHIVE}/DemoCheckDataBase.dat"
    stages = ctx.get(dvp)
    n = struct.unpack_from("<I", stages, 0)[0]
    listed = sorted({struct.unpack_from("<I", stages, 4 + 336 * i + 4)[0] for i in range(n)
                     if struct.unpack_from("<H", stages, 4 + 336 * i + 0x16)[0]})
    raw = ctx.get(cvp)
    m = struct.unpack_from("<I", raw, 0)[0]
    rows = [struct.unpack_from("<3I", raw, 4 + 12 * i) for i in range(m)]
    have = {r[0] for r in rows}
    new = [(mid, 0, 0) for mid in listed if mid not in have]
    if not new:
        return
    rows = sorted(rows + new, key=lambda r: r[0])
    ctx.put(cvp, struct.pack("<I", len(rows)) + b"".join(struct.pack("<3I", *r) for r in rows))
    ctx.log(f"  stages: {len(new)} new stage(s) in the stage list's check table "
            f"({', '.join(f'map{r[0]:05d}' for r in new)})")


register_finalizer(_finalize_stages)


def _finalize_order(ctx):
    """Id order, once every mod's rows are in.

    Skill.dat is searched by id (0x14015e630: a binary search over the id array, the index it finds
    addresses the unit's known-evility bitset).  Each mod appends its own block, so one mod's rows
    are in order but the merged table is not: ids behind an inversion cannot be found, and a screen
    that resolves the highlighted row by id gets "not found".  Vanilla ships this table in id order;
    a mod install can break that, so the finished table is put back in order (row order carries no
    meaning for a keyed table -- every reference is by id).  `d5lib.ordercheck` owns the rule.
    """
    if not getattr(ctx, "order_check", False):
        return
    for member in ordercheck.ORDER_CRITICAL:
        vpath = f"{DB_ARCHIVE}/{member}"
        try:
            logical = ctx.get(vpath)
        except KeyError:
            continue
        fixed, moved = ordercheck.sort_keyed(member, logical, log=ctx.log)
        if moved:
            ctx.put(vpath, fixed)
        for f in ordercheck.findings(member, fixed):
            ctx.log("  warning: " + f)


register_finalizer(_finalize_order)
