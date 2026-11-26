"""Disgaea 5's own Magichange attack set: read it, clone it, attach it to a character.

D5 ships the Magichange *mode* (a monster becomes a weapon for an ally) and the mode is entirely
data-driven.  Four char.dat / magic.dat facts make one character's Magichange attacks:

  char.dat  magichange_weapon (item.dat id, offset 244)  the weapon the unit becomes; 0 = cannot
  char.dat  magichange_type   (weapon type, offset 378)   first digit of the weapon id
  magic.dat skill_group = 10                             the Magichange skill list (schema: magic.json)
  magic.dat user1                                        char id / class family the set belongs to

One set is two or three magic.dat rows that point at each other:

  single   motion_type 9,  icon 8,  8 SP,  dual_skill -> the Dual Magichange row
  pair     motion_type 8,  icon 8,  64 SP  (the two-attack version, no back-pointer)
  dual     motion_type 10, icon 10, 8 SP,  base_skill -> the single

Not every family has the third row: Imp 2020 ships all three (22021/22022/22023), Shroom 2100 ships
two (22101/22102).  The set is learned like any other skill -- the ids sit in the character's
char.dat learnset (Desco 610 learns 20611 at 30 and 20612 at 70), which is how the battle skill list
finds them (`list_skills` 0x1402d0820 walks the unit's own skill slots and accepts the groups 8-10).

Nothing in this module touches the exe: a character whose char.dat row already carries
magichange_weapon/magichange_type only needs its set in the learnset, and the game's own Magichange
command picks it up.  `trio` reads a set, `plan` clones one onto new ids (donor numbers, source
names), `attach` writes the learn slots, `check` audits every set in a table.
"""
from __future__ import annotations

GROUP = 10
ROLE_SINGLE = "single"
ROLE_PAIR = "pair"
ROLE_DUAL = "dual"
MAGICHANGE_WEAPON = "magichange_weapon"
MAGICHANGE_TYPE = "magichange_type"
DESC_PREFIX = "Magichange:%s"
DUAL_DESC_PREFIX = "Dual Magichange:%s"
DUAL_NAME_PREFIX = "Twin "


def _rows(table):
    return list(table.rows)


def is_magichange(row):
    return int(row.get("skill_group") or 0) == GROUP


def sets(table):
    """{user1: {'single': row, 'pair': row|None, 'dual': row|None}} for every Magichange set."""
    out = {}
    loose = {}
    for row in _rows(table):
        if not is_magichange(row):
            continue
        user = int(row.get("user1") or 0)
        by_user = out.setdefault(user, {})
        if row.get("base_skill"):
            by_user[ROLE_DUAL] = row
        elif row.get("dual_skill"):
            by_user[ROLE_SINGLE] = row
        else:
            # no back-pointer either way: the 8-SP row is the single and the 64-SP row the pair, which is
            # D5's own contract (a family with no Dual Magichange ships exactly these two: Shroom 22101/22102)
            loose.setdefault(user, []).append(row)
    for user, rows in loose.items():
        by_user = out[user]
        rows.sort(key=lambda r: (int(r.get("sp_cost") or 0), int(r["id"])))
        if ROLE_SINGLE not in by_user:
            by_user[ROLE_SINGLE] = rows.pop(0)
        for row in rows:
            by_user.setdefault(ROLE_PAIR, row)
    for by_user in out.values():
        for role in (ROLE_SINGLE, ROLE_PAIR, ROLE_DUAL):
            by_user.setdefault(role, None)
    return out


def set_of(table, single_id):
    """The set led by `single_id`, validated, as {'single','pair','dual'} (a missing role is None).

    A complete D5 set is three rows (Imp 2020: 22021 single / 22022 pair / 22023 dual); some families ship
    two (Shroom 2100: 22101 / 22102, no Dual Magichange).  Raises when the rows are not one consistent set:
    the single must be group 10, every row must share its user1, the dual must point back at it, and there
    may be at most one 64-SP pair.
    """
    rows = {int(r["id"]): r for r in _rows(table)}
    single = rows.get(int(single_id))
    if single is None or not is_magichange(single):
        raise ValueError(f"{single_id} is not a Magichange row (skill_group {GROUP})")
    user = int(single.get("user1") or 0)
    if user == 0:
        raise ValueError(f"{single_id}: user1 is 0, so no character owns the set")
    if int(single.get("motion_type") or 0) not in (8, 9):
        raise ValueError(f"{single_id}: a single is motion 9 (or 8 in a family with no dual), "
                         f"has {single.get('motion_type')}")
    if int(single.get("icon") or 0) != 8:
        raise ValueError(f"{single_id}: a single is icon 8, has {single.get('icon')}")
    dual_id = int(single.get("dual_skill") or 0)
    dual = rows.get(dual_id) if dual_id else None
    if dual_id and dual is None:
        raise ValueError(f"{single_id}: dual_skill {dual_id} is not a row")
    if dual is not None:
        if int(dual.get("base_skill") or 0) != int(single_id):
            raise ValueError(f"{single_id}: dual {dual['id']} does not point back")
        if int(dual.get("motion_type") or 0) != 10 or int(dual.get("icon") or 0) != 10:
            raise ValueError(f"{dual['id']}: a dual is motion 10 / icon 10")
    pair = None
    for row in _rows(table):
        if (is_magichange(row) and not row.get("dual_skill") and not row.get("base_skill")
                and int(row.get("user1") or 0) == user and int(row["id"]) != int(single_id)
                and int(row.get("motion_type") or 0) == 8):
            if pair is not None:
                raise ValueError(f"user {user}: more than one 64-SP pair row")
            pair = row
    for row in (single, pair, dual):
        if row is not None and int(row.get("user1") or 0) != user:
            raise ValueError(f"{row['id']}: user1 {row.get('user1')} != {user}")
    return {ROLE_SINGLE: single, ROLE_PAIR: pair, ROLE_DUAL: dual}


def trio(table, single_id):
    """`set_of` plus D5's full three-row shape (single + 64-SP pair + dual)."""
    found = set_of(table, single_id)
    if found[ROLE_PAIR] is None:
        raise ValueError(f"{single_id}: no 64-SP pair row for user {found[ROLE_SINGLE].get('user1')}")
    if found[ROLE_DUAL] is None:
        raise ValueError(f"{single_id}: no Dual Magichange row")
    if int(found[ROLE_SINGLE].get("motion_type") or 0) != 9:
        raise ValueError(f"{single_id}: single must be motion 9")
    return found


def shape(table, user1):
    """How many rows this family ships: 3 with a dual, 2 without, 0 if it cannot Magichange."""
    found = sets(table).get(int(user1)) or {}
    return sum(1 for role in (ROLE_SINGLE, ROLE_PAIR, ROLE_DUAL) if found.get(role))


def insert_index(table, row_id):
    """Where magic.dat must put `row_id` so the game's binary search (`unit_stats_skills_magic_row`) finds it.

    The writer does not sort: it writes the rows in list order, so an inserted id has to land in order.
    """
    ids = [int(r["id"]) for r in _rows(table)]
    if row_id in ids:
        raise ValueError(f"magic.dat already has row {row_id}")
    lo, hi = 0, len(ids)
    while lo < hi:
        mid = (lo + hi) // 2
        if ids[mid] < row_id:
            lo = mid + 1
        else:
            hi = mid
    return lo


def plan(table, donor_single_id, *, ids, names, descs, user1, levels=(1, 1, 1)):
    """Clone the donor set onto `ids` with the source names.

    `ids` is (single, pair, dual) or (single, pair) -- the length must equal the donor's own shape, so a
    character never grows a Dual Magichange its body family does not have.  Numbers, animation ids,
    areas, heights, effects and the element stay the donor's (disclosed as adapted); only the id, the
    name, the description, user1 and the cross-links are new.  Returns [(role, row_dict)].

    Doing this against a live Table mutates it; `rows_from_table` is the read-only variant the writer
    uses so the bundle and the proof see the same bytes.
    """
    donor = set_of(table, donor_single_id)
    roles = [ROLE_SINGLE, ROLE_PAIR, ROLE_DUAL] if donor[ROLE_PAIR] is not None and donor[ROLE_DUAL] else \
            [ROLE_SINGLE, ROLE_PAIR]
    ids = tuple(int(i) for i in ids)
    if len(ids) != len(roles):
        raise ValueError(f"donor {donor_single_id} has {len(roles)} rows, {len(ids)} ids given")
    if len(set(ids)) != len(ids):
        raise ValueError("ids must be distinct")
    out = []
    for role, new_id, level in zip(roles, ids, levels):
        row = donor[role]
        fields = row.to_dict()
        fields["id"] = new_id
        fields["user1"] = int(user1)
        fields["user_count"] = 1
        name, desc = names[role], descs[role]
        for loc in ("JP", "EN", "FR", "CHN", "KOR"):
            fields[f"name_{loc}"] = name
            fields[f"desc_{loc}"] = desc
        if role == ROLE_SINGLE:
            fields["dual_skill"] = ids[-1] if len(ids) == 3 else 0
        elif role == ROLE_DUAL:
            fields["base_skill"] = ids[0]
        else:
            fields["dual_skill"] = 0
            fields["base_skill"] = 0
        out.append((role, fields))
    return out


def names_for(source_names, dual_name=None):
    """The three names/descriptions from the source game's two Magichange attacks.

    D5's own pattern (Imp): single keeps the attack's name, the 64-SP pair keeps the second attack's
    name, and the Dual Magichange row is "Twin <single>".  Descriptions carry D5's own prefixes so the
    game's Magichange list reads like the rest of the band.
    """
    single, pair = source_names
    dual = dual_name or (DUAL_NAME_PREFIX + single)
    return (
        {ROLE_SINGLE: single, ROLE_PAIR: pair, ROLE_DUAL: dual},
        {ROLE_SINGLE: DESC_PREFIX, ROLE_PAIR: DESC_PREFIX, ROLE_DUAL: DUAL_DESC_PREFIX},
    )


def attach(char_row, learned):
    """Give (id, level) pairs to a char.dat row -> the slots used.  Refuses a 17th skill."""
    from . import charstudio
    return [charstudio.give_skill(char_row, int(sid), int(level)) for sid, level in learned]


def check(table, user_ids=None):
    """Audit every set (or the given user1s): returns a list of problem strings, [] when clean."""
    problems = []
    found = sets(table)
    wanted = found.keys() if user_ids is None else [int(u) for u in user_ids]
    for user in wanted:
        got = found.get(user) or {}
        if not got:
            problems.append(f"user {user}: no Magichange row")
            continue
        single = got.get(ROLE_SINGLE)
        if single is None:
            problems.append(f"user {user}: no single row (only {sorted(r['id'] for r in got.values())})")
            continue
        try:
            set_of(table, single["id"])
        except ValueError as exc:
            problems.append(str(exc))
            continue
        pair = got.get(ROLE_PAIR)
        if pair is None:
            problems.append(f"user {user}: single {single['id']} has no 64-SP pair row")
        for role, row in got.items():
            if row is None:
                continue
            if int(row.get("user1") or 0) != user:
                problems.append(f"{row['id']}: user1 {row.get('user1')} != {user}")
            if role != ROLE_PAIR and int(row.get("sp_cost") or 0) != 8:
                problems.append(f"{row['id']}: {role} must cost 8 SP, has {row.get('sp_cost')}")
            if role == ROLE_PAIR and int(row.get("sp_cost") or 0) != 64:
                problems.append(f"{row['id']}: pair must cost 64 SP, has {row.get('sp_cost')}")
    return problems


def learned_ids(char_row):
    return [int(char_row[f"learn{k}_skill"]) for k in range(1, 17) if char_row[f"learn{k}_skill"]]
