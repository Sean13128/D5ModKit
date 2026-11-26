"""Tables the game looks rows up in by id, and the order they must keep.

Some of the game's tables are read through a *binary search over the row ids* (the loop in
`FUN_14015e630` at 0x14015e630 for Skill.dat: it searches the id array `DAT_140a04e48`, count
`DAT_140a04e38`, and uses the index it finds to address per-unit state).  The search assumes the
table is in ascending id order, which vanilla's own tables are.  A mod's added rows are appended,
so one mod's block is sorted but the merged table is not: every id that sits behind an inversion
can no longer be found, and a screen that resolves a highlighted row by id gets "not found".

This is the same failure the kit already fixed for other tables, and it was seen in game once:
the stage list resolves a highlighted stage in DemoCheckDataBase.dat by binary search, and a
stage without a row made the game read address 0 and close the moment the cursor reached the new
stage (2026-10-16, `dbpatch._finalize_stages`).

`ORDER_CRITICAL` lists the tables this module sorts on the finished build (every mod's rows in).
A table is only listed when vanilla itself ships it in id order -- a table vanilla ships unsorted
is read some other way, so its order is left alone.

`BITSET_CAP` is a second, independent limit found in the same function: the per-unit "known
evility" bitset (`unit+0x2E70`) is addressed by row *index*, and the code refuses an index >= 1000
(`uVar3 < 1000` in 0x14015e630 and 0x1407c0a00).  A Skill.dat with 1000 or more rows silently loses
the units' learned marks for the tail rows, so the count is a build gate, not a warning.
"""
from __future__ import annotations

from . import database

ORDER_CRITICAL = ("Skill.dat",)
BITSET_CAP = 1000


def _ids(table):
    key = getattr(table.schema, "key", None)
    if not key:
        return None
    try:
        ids = [r[key] for r in table.rows]
    except Exception:
        return None
    if not all(isinstance(i, int) for i in ids):
        return None
    return ids


def vanilla_ships_sorted(vanilla_bytes, member: str) -> bool:
    """True when the pristine member is in ascending key order (so the game's search expects that)."""
    table = database.load_table(member, vanilla_bytes)
    ids = _ids(table)
    return bool(ids) and ids == sorted(ids)


def sort_keyed(member: str, logical: bytes, *, vanilla=None, log=None):
    """Sort `logical` (a whole member's bytes) by its key when the game searches it by id.

    Returns (bytes, moved).  `moved` is how many rows changed position (0 = unchanged).
    """
    if member not in ORDER_CRITICAL:
        return logical, 0
    table = database.load_table(member, logical)
    ids = _ids(table)
    if ids is None or ids == sorted(ids):
        return logical, 0
    if vanilla is not None:
        try:
            if not vanilla_ships_sorted(vanilla, member):
                return logical, 0
        except Exception:
            pass
    order = sorted(range(len(table.rows)), key=lambda i: ids[i])
    table.rows[:] = [table.rows[i] for i in order]
    moved = sum(1 for a, b in enumerate(order) if a != b)
    if log:
        log(f"  {member}: {moved} rows re-ordered into id order (the game searches this table by id)")
    return table.to_bytes(), moved


def findings(member: str, logical: bytes, *, vanilla=None) -> list:
    """Validator: the reasons this finished member must not ship, as short strings (empty = fine)."""
    out = []
    try:
        table = database.load_table(member, logical)
    except Exception as e:                     # unreadable member: not this check's business
        return out
    ids = _ids(table)
    if ids is None:
        return out
    if member in ORDER_CRITICAL:
        if vanilla is not None:
            try:
                if not vanilla_ships_sorted(vanilla, member):
                    return out
            except Exception:
                pass
        if ids != sorted(ids):
            bad = [i for i in range(len(ids) - 1) if ids[i] > ids[i + 1]]
            sample = ", ".join(f"{ids[i]}>{ids[i + 1]}" for i in bad[:4])
            out.append(f"{member}: not in id order ({len(bad)} inversion(s): {sample}); "
                       f"ids behind an inversion cannot be found by the game's binary search")
        if member == "Skill.dat" and len(ids) > BITSET_CAP:
            # Not a blocker since EVCAP: rows past the bitmap live in the extension's per-unit store
            # (d5lib.learned).  What still blocks is a row *inserted below* a saved bit -- that is
            # `positional_errors`, and it is checked against the vanilla table wherever it is known.
            out.append(f"{member}: {len(ids)} rows; positions {BITSET_CAP}.. are held by the learned-evility "
                       f"store, not by the native bitmap")
    return out


# --------------------------------------------------------------------------- positional references
# What a row's *position* means, per member.  Adding a row to one of these tables is not the same as
# adding a row to a keyed one: something already saved points at positions, not ids.
POSITIONAL = {
    "Skill.dat": {
        "consumer": "learned evilities",
        "where": "unit record +0x2E70, 125 bytes = 1000 bits",
        "keyed_by": "position in the id-sorted table",
        "cap": BITSET_CAP,
        "beyond": "d5lib.learned's per-unit store (ids at positions >= cap) + the *.d5learn.json companion",
    },
    "char.dat": {
        "consumer": "the unit's class row",
        "where": "unit record +0x2E0A (s16 char.dat row of the class)",
        "keyed_by": "row index of the class id's first row",
        "cap": None,
        "beyond": "d5lib/native/d5rows.inc.c re-points it at run time; a save import remaps it",
    },
}


def position_map(old_ids, new_ids):
    """How positions moved between two versions of the same table.

    -> (mapping: {old_position: new_position}, unmapped: [ids the new table lacks],
        inserted: [ids the old table lacked], shifted: [ids whose position changed])
    """
    new_pos = {i: p for p, i in enumerate(new_ids)}
    old = {i: p for p, i in enumerate(old_ids)}
    mapping = {p: new_pos[i] for i, p in old.items() if i in new_pos}
    unmapped = [i for i in old_ids if i not in new_pos]
    inserted = [i for i in new_ids if i not in old]
    shifted = [i for i in old_ids if i in new_pos and new_pos[i] != old[i]]
    return mapping, unmapped, inserted, shifted


def bitmap_findings(old_ids, new_ids, cap=BITSET_CAP):
    """Bits of an existing save that would mean a different evility after this table change.

    A row inserted *below* the cap moves every later row's bit, so a save written against `old_ids`
    would silently decode to the wrong evilities.  Rows appended past every existing position (the
    normal case: our ids, and Overlord's 20000+, sort last) cost nothing.
    """
    new_pos = {i: p for p, i in enumerate(new_ids)}
    out = []
    for p, i in enumerate(old_ids[:cap]):
        q = new_pos.get(i)
        if q is None:
            out.append({"id": i, "old_position": p, "new_position": None, "why": "row removed"})
        elif q != p:
            out.append({"id": i, "old_position": p, "new_position": q, "why": "row moved"})
    return out


def positional_errors(member, old_ids, new_ids, cap=None):
    """The reasons this change must not ship without a save migration (empty = safe to install)."""
    decl = POSITIONAL.get(member)
    if not decl:
        return []
    cap = decl["cap"] if cap is None else cap
    if cap is None:
        return []
    moved = bitmap_findings(old_ids, new_ids, cap)
    if not moved:
        return []
    first = moved[0]
    return [f"{member}: {len(moved)} saved bit(s) would change meaning "
            f"({decl['consumer']}: id {first['id']} {first['old_position']} -> {first['new_position']}); "
            f"a row was inserted or re-ordered inside position {cap}. Install the save migration with it, "
            f"or keep new rows above every existing id."]


def remap_bitmap(bitmap, old_ids, new_ids, cap=BITSET_CAP):
    """Re-address one unit's learned bitset from `old_ids` to `new_ids`.

    -> (new_bitmap, overflow_ids, unknown_ids, moved).  `overflow_ids` are ids whose new position is
    at or past `cap`: the native bitmap cannot hold them, so they belong to the learned-evility store
    (`d5lib.learned`).  `unknown_ids` are ones the new table does not have at all (quarantine).
    """
    limit = min(cap, len(bitmap) * 8)
    new = bytearray(len(bitmap))
    new_pos = {i: p for p, i in enumerate(new_ids)}
    overflow, unknown, moved = [], [], 0
    for bit in range(limit):
        if not bitmap[bit >> 3] & (1 << (bit & 7)):
            continue
        if bit >= len(old_ids):
            raise ValueError(f"bit {bit} is set but the table it was written against has {len(old_ids)} rows")
        ident = old_ids[bit]
        pos = new_pos.get(ident)
        if pos is None:
            unknown.append(ident)
        elif pos >= cap:
            overflow.append(ident)
        else:
            new[pos >> 3] |= 1 << (pos & 7)
            if pos != bit:
                moved += 1
    return bytes(new), overflow, unknown, moved
