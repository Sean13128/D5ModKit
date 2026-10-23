"""Checks of a database table before it goes into the game: what would crash it, what looks wrong.

    issues = check(member, table, valid_keys=lambda ref: {keys} or None)
    -> [Issue(severity, row index or None, text)], severity CRASH ("crash risk"), WARN, NOTE

Every table: rows with the same key, references to rows that don't exist (with valid_keys), texts longer than their
field, rows of tables the game binary-searches out of order.  Some tables have rules of their own (Skill.dat: the
evility kinds the Skill Shop / evility list expect; magic.dat: area shapes that exist).  The Skill.dat rules follow
what the Disgaea 5 "Overlord Edition" editors found (a source-3 = generic class evility owned by a character crashes
the Skill Shop) and the game's own rows (Skill.dat: 796 rows, all of them follow these rules).
"""
from collections import namedtuple

Issue = namedtuple("Issue", "severity row text")
CRASH, WARN, NOTE = "crash risk", "warning", "note"
ORDER = {CRASH: 0, WARN: 1, NOTE: 2}

# tables the game looks rows up in by binary search: keys must stay in ascending order
SORTED = {
    "DemoCheckDataBase.dat": "the stage list binary-searches it (a missing or misplaced stage closes the game)",
    "MakaiSkillDataBase.dat": "the Netherworld skills are binary-searched by id (0x14008d380)",
}
# tables whose keys the game's own files keep in ascending order (not known to be required)
USUALLY_SORTED = {"Skill.dat"}

SOURCE_GENERIC, SOURCE_CHARACTER = 3, 4      # Skill.dat source: the generic-class / the character evility system


def is_class_id(cid):
    """a class family id (generic human / monster classes and the kit's new ones: 1000+, a multiple of 10)"""
    return int(cid) >= 1000 and int(cid) % 10 == 0


def check(member, table, valid_keys=None, vanilla=None):
    """vanilla: the game's own table -- references are only checked where a row differs from it (the game's own
    rows point at things that aren't in the tables, e.g. char.dat's learned skills of other tables)"""
    sch = table.schema

    def changed(i, f):
        if vanilla is None or i >= len(vanilla.rows):
            return True
        return vanilla.rows[i][f] != table.rows[i][f]
    out = []
    key = sch.key
    if key and any(f.name == key for f in sch.fields):
        seen = {}
        for i, r in enumerate(table.rows):
            k = r[key]
            if k in seen:
                out.append(Issue(WARN, i, f"{key} {k} is used by row {seen[k]} too: the game finds only one of them"))
            else:
                seen[k] = i
        keys = [r[key] for r in table.rows]
        if member in SORTED and keys != sorted(keys):
            i = next(i for i in range(1, len(keys)) if keys[i] < keys[i - 1])
            out.append(Issue(CRASH, i, f"{key}s out of order from row {i}: {SORTED[member]}"))
        elif member in USUALLY_SORTED and keys != sorted(keys):
            i = next(i for i in range(1, len(keys)) if keys[i] < keys[i - 1])
            out.append(Issue(NOTE, i, f"{key}s out of order from row {i} (the game's own table keeps them in order)"))
    for f in sch.fields:
        if f.type == "str" and f.size:
            for i, r in enumerate(table.rows):
                v = r.get(f.name) if hasattr(r, "get") else r[f.name]
                if isinstance(v, str) and len(v.encode("utf-8")) > f.size - 1:
                    out.append(Issue(WARN, i, f"{f.name} is {len(v.encode('utf-8'))} bytes, the field holds "
                                              f"{f.size - 1}: it will be cut"))
        if f.ref and valid_keys is not None:
            keys = valid_keys(f.ref)
            if not keys:
                continue
            for i, r in enumerate(table.rows):
                v = r[f.name]
                if isinstance(v, int) and v > 0 and v not in keys and changed(i, f.name):
                    out.append(Issue(WARN, i, f"{f.name} = {v}: no such row in {f.ref}"))
    rule = RULES.get(member)
    if rule:
        out += rule(table, valid_keys)
    out.sort(key=lambda x: (ORDER.get(x.severity, 9), x.row if x.row is not None else -1))
    return out


def _skill(table, valid_keys):
    """evilities: the kinds the Skill Shop and the evility lists expect"""
    out = []
    chars = valid_keys("char.dat") if valid_keys else None
    for i, r in enumerate(table.rows):
        rid, src, owner = int(r["id"]), int(r["source"]), int(r["owner"])
        kind, slots, mana = int(r["kind"]), int(r["slot_cost"]), int(r["mana_cost"])
        lab = f"evility {rid} ({r['name_EN'] or 'no name'})"
        if src == SOURCE_GENERIC and owner and not is_class_id(owner):
            out.append(Issue(CRASH, i, f"{lab}: source 3 (a generic class's evility) owned by {owner}, not a class: "
                                       "the Skill Shop crashes on it. A character's evility uses source 4."))
        if src == SOURCE_GENERIC and owner and chars and owner not in chars:
            out.append(Issue(WARN, i, f"{lab}: owner class {owner} isn't in char.dat"))
        if src == SOURCE_CHARACTER and owner and is_class_id(owner):
            out.append(Issue(WARN, i, f"{lab}: source 4 (a character's evility) owned by the class {owner}"))
        if kind == 1 and slots:
            out.append(Issue(WARN, i, f"{lab}: a unique evility with slot cost {slots} (the game's uniques: 0)"))
        if src == SOURCE_CHARACTER and kind == 0 and slots == 0:
            out.append(Issue(WARN, i, f"{lab}: a common character evility with slot cost 0 shows oddly in the list "
                                      "(give it 1 or more)"))
        if src == SOURCE_CHARACTER and kind == 1 and mana:
            out.append(Issue(NOTE, i, f"{lab}: a character's unique evility with Mana cost {mana} (the game's: 0)"))
        if src == SOURCE_GENERIC and is_class_id(owner) and int(r["class_order"]) not in range(0, 7):
            out.append(Issue(WARN, i, f"{lab}: class_order {r['class_order']} (1-5 learned, 6 the unique)"))
    return out


def _magic(table, valid_keys):
    out = []
    shapes = valid_keys("AttackMap.dat") if valid_keys else None
    for i, r in enumerate(table.rows):
        sid = int(r["attack_map"] or 0)
        if shapes and sid and sid not in shapes:
            out.append(Issue(WARN, i, f"skill {r['id']} ({r['name_EN']}): area shape {sid} doesn't exist (the game "
                                      "falls back to one panel or misbehaves)"))
    return out


RULES = {"Skill.dat": _skill, "magic.dat": _magic}

# ---- presets (one click sets the fields a kind of row needs)
SKILL_PRESETS = {
    "character_unique": ("A character's unique evility",
                         dict(kind=1, slot_cost=0, source=SOURCE_CHARACTER, mana_cost=0, class_order=0)),
    "character_learnable": ("A character's learnable evility",
                            dict(kind=0, source=SOURCE_CHARACTER, class_order=0)),
    "class_unique": ("A generic class's unique evility (class_order 6)",
                     dict(kind=1, slot_cost=0, source=SOURCE_GENERIC, class_order=6)),
    "class_learnable": ("A generic class's learned evility (class_order 1-5)",
                        dict(kind=0, source=SOURCE_GENERIC)),
}


def apply_preset(row, preset, owner=None, order=None):
    """set a Skill.dat row's fields for a kind of evility (SKILL_PRESETS); -> {field: (old, new)} changed"""
    _, fields = SKILL_PRESETS[preset]
    fields = dict(fields)
    if owner is not None:
        fields["owner"] = int(owner)
    if order is not None and preset == "class_learnable":
        fields["class_order"] = max(1, min(5, int(order)))
    if preset == "class_learnable" and "class_order" not in fields:
        fields["class_order"] = int(row["class_order"]) if 1 <= int(row["class_order"]) <= 5 else 1
    if preset == "character_learnable" and int(row["slot_cost"]) == 0:
        fields["slot_cost"] = 1
    changed = {}
    for k, v in fields.items():
        if int(row[k]) != int(v):
            changed[k] = (int(row[k]), int(v))
            row.set(k, int(v))
    return changed
