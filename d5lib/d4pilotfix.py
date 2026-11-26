"""Repair rules for D4 pilots: one innate evility per unit, commons stay common.

D5's own model, read off vanilla data (char.dat 1010/1150 rank rows, Skill.dat owner rows):

* a class rank row carries exactly ONE innate evility -- the class's own evility row
  (``kind`` 1, ``slot_cost`` 0, one row per class, shared by all six ranks);
* every other class evility is an ordinary learnable: ``kind`` 0, ``source`` 4 with
  ``owner`` = the class (the shop checks ``unit id / 10 == owner / 10``), a positive
  ``slot_cost`` and a mana price;
* a character row's innate evilities are all ``kind`` 1 rows.

``unlockpatch`` turns every innate evility of a modded character into one unique slot
(``max(game slots, evility_count)``), so a rank row that carries four innate evilities
shows four UNIQUE slots -- owner playtest 2, Ben's Aegis/Last Fortress/Advance Guard/
Spear Defense.  Nothing here is native: these are patch-tree rewrites plus validators.
"""
import copy
import json
from pathlib import Path

from . import textfmt

# D5's own class/shop commons, by their mana tier: (upper mana bound, slot cost).  Read
# off the vanilla source-3/-4 owner rows (100 -> 2-3, 250 -> 2-3, 1000 -> 3-4,
# 2500 -> 3-4, 5000 -> 4-5, 30000 -> 5).  This is a shape rule, not a D4 field.
SLOT_BY_MANA = ((100, 2), (250, 2), (1000, 3), (2500, 4), (5000, 4))


def slot_cost_for_mana(mana):
    """The slot cost a D5 common evility of this mana price carries (minimum 2)."""
    mana = int(mana or 0)
    for bound, cost in SLOT_BY_MANA:
        if mana <= bound:
            return cost
    return 5


def _rows(patch):
    yield from patch.get("added", [])
    yield from (patch.get("rows") or {}).values()


def _evilities(row):
    # char.dat patches are field diffs: a row may not carry every evility field
    return [int(row.get(f"evility{n}") or 0) for n in range(1, 5) if int(row.get(f"evility{n}") or 0)]


def enforce_innates(mod_root, allowed_unique, *, require_one=False):
    """Drop innate evility ids that are not unique (``kind`` 1) rows of this mod/vanilla.

    ``allowed_unique`` is the set of evility ids that may legally fill a unique slot (the
    mod's own ``kind`` 1 rows plus the vanilla ``kind`` 1 rows, so editing a stock
    character keeps its own innate).  A common evility sitting in ``evility1..4`` is a
    build error: the engine shows it as the unit's UNIQUE evility.  Gaps are closed and
    ``evility_count`` rewritten.  Returns one receipt entry per changed row.
    """
    root = Path(mod_root)
    char_path = root / "patches/db/char.dat.json"
    if not char_path.exists():
        return []
    patch = json.loads(char_path.read_text())
    allowed = {int(i) for i in allowed_unique}
    receipt = []
    for row in _rows(patch):
        have = _evilities(row)
        keep = [e for e in have if e in allowed]
        dropped = [e for e in have if e not in allowed]
        if require_one and len(keep) > 1:
            raise ValueError(f"char {row.get('id')}: {len(keep)} unique evilities: {keep}")
        if require_one and have and not keep:
            raise ValueError(f"char {row.get('id')}: no unique evility among {have}")
        if dropped:
            if len(keep) > 1:
                raise ValueError(f"char {row.get('id')}: still {len(keep)} unique evilities")
            for n in range(1, 5):
                row[f"evility{n}"] = keep[n - 1] if n <= len(keep) else 0
            row["evility_count"] = len(keep)
            receipt.append(dict(char_id=int(row.get("id", 0)), kept=keep, dropped=dropped))
    if receipt:
        char_path.write_text(json.dumps(patch, indent=1, ensure_ascii=False) + "\n")
    return receipt


def set_common_slot_costs(mod_root):
    """Give every kind 0 evility row this mod adds a D5-shaped slot cost (never 0/free)."""
    root = Path(mod_root)
    path = root / "patches/db/Skill.dat.json"
    if not path.exists():
        return []
    patch = json.loads(path.read_text())
    receipt = []
    for row in patch.get("added", []):
        if int(row.get("kind", 0)) == 1:
            if int(row.get("slot_cost", 0)) != 0:
                row["slot_cost"] = 0
                receipt.append(dict(id=int(row["id"]), slot_cost=0, note="unique"))
            continue
        want = slot_cost_for_mana(row.get("mana_cost"))
        if int(row.get("slot_cost", 0)) != want:
            row["slot_cost"] = want
            receipt.append(dict(id=int(row["id"]), slot_cost=want))
    if receipt:
        path.write_text(json.dumps(patch, indent=1, ensure_ascii=False) + "\n")
    return receipt


def check_patches(char_patch, skill_patch, magic_patch, *, vanilla_unique, vanilla_magic,
                  family=None, exactly_one=False):
    """Offline problems in one staged mod.  ``None`` = no char/magic patch of that kind."""
    problems = []
    unique = {int(i) for i in vanilla_unique}
    rows = []
    if skill_patch is not None:
        unique |= {int(r["id"]) for r in skill_patch.get("added", []) if int(r.get("kind", 0)) == 1}
        for r in skill_patch.get("added", []):
            rid, kind = int(r["id"]), int(r.get("kind", 0))
            if kind not in (0, 1):
                problems.append(f"evility {rid}: kind {kind}")
            if kind == 0 and int(r.get("slot_cost", 0)) <= 0:
                problems.append(f"evility {rid}: common evility with slot_cost 0")
            if kind == 1 and int(r.get("slot_cost", 0)) != 0:
                problems.append(f"evility {rid}: unique evility with slot_cost {r.get('slot_cost')}")
            if int(r.get("source", 0)) == 3 and family is not None:
                # source 3 asks the shop for the owner class's mastery (crash on an
                # imported class, see sourceimports.build_d4_pilot); imported rows use 4.
                problems.append(f"evility {rid}: source 3 class evility on imported class")
            if family is not None and int(r.get("owner", 0)) != int(family):
                problems.append(f"evility {rid}: owner {r.get('owner')} != family {family}")
            # the desc is the game's printf FORMAT (0x1407D22B0): a bare '%' is an invalid directive and
            # kills the screen that draws it (PTFIX C1, see d5lib/textfmt)
            for lang in ("JP", "EN", "FR", "CHN", "KOR"):
                text = r.get("desc_" + lang) or ""
                if textfmt.bad_format(text):
                    problems.append(f"evility {rid}: desc_{lang} has an unsafe ASCII % (use %d or ％)")
    magic_ids = set(int(i) for i in vanilla_magic)
    if magic_patch is not None:
        magic_ids |= {int(r["id"]) for r in magic_patch.get("added", [])}
    if char_patch is not None:
        rows = [*char_patch.get("added", []), *(char_patch.get("rows") or {}).values()]
    for row in rows:
        have = _evilities(row)
        # a field-diff row that does not touch the innate fields says nothing about them
        carries = any(f"evility{n}" in row for n in range(1, 5))
        bad = [e for e in have if e not in unique]
        if bad:
            problems.append(f"char {row.get('id')}: non-unique evility in an innate slot: {bad}")
        if exactly_one and carries and len(have) != 1:
            problems.append(f"char {row.get('id')}: {len(have)} innate evilities, expected 1")
        for n in range(1, int(row.get("learn_count", 0)) + 1):
            sid = int(row.get(f"learn{n}_skill", 0) or 0)
            if sid and magic_ids and sid not in magic_ids:
                problems.append(f"char {row.get('id')}: learned skill {sid} absent from magic.dat")
    return problems


def validate_mod(fs, mod_root, *, family=None, exactly_one=False):
    """``check_patches`` against the original tables read through the game filesystem."""
    from . import database
    root = Path(mod_root)
    if not (root / "patches/db/char.dat.json").exists():
        raise ValueError(f"not a staged mod (no char.dat patch): {root}")

    def patch(name, folder):
        path = root / "patches" / folder / name
        return json.loads(path.read_text()) if path.exists() else None

    try:
        skill = database.load_table("Skill.dat", fs.read("Database/Database_0.dat/Skill.dat"))
        magic = database.load_table("magic.dat", fs.read("Database/Database_0.dat/magic.dat"))
        chars = database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat"))
    finally:
        fs.reset()
    char = patch("char.dat.json", "db") or {}
    # edited rows are keyed by table index; give them their id so problems name the row
    for key, row in (char.get("rows") or {}).items():
        row.setdefault("id", chars.rows[int(key)]["id"])
    vanilla_unique = {int(r["id"]) for r in skill.rows if int(r["kind"]) == 1}
    return check_patches(char, patch("Skill.dat.json", "db"), patch("magic.dat.json", "db"),
                         vanilla_unique=vanilla_unique,
                         vanilla_magic={int(r["id"]) for r in magic.rows},
                         family=family, exactly_one=exactly_one)


def apply_valvatorez_pilot(fs, mod, *, char_id, unique, skills=(),
                           learn_levels=()):
    """Innate evility + own skill ids for a D4 unique-character pilot.

    ``unique`` = (new id, D5 donor id, name): the D4 innate evility becomes an alias row
    (kind 1, slot_cost 0, owned by the character) and the character row's one innate slot.
    ``skills`` = ((new id, D5 donor id, name), ...) copied with the donor's choreography:
    D5 filters its own unique-skill ids to their character in the battle command menu
    (``cmdmenu_env_stat_row_skill_slots`` 0x1401D68A0: ids 10571-10573 only for char 570),
    so the pilot must learn its own ids, not the donor's.
    """
    from . import newclasses
    root = Path(mod.folder)
    alias_path = root / "patches/evilities/aliases.json"
    aliases = json.loads(alias_path.read_text()) if alias_path.exists() else {}
    new_id, donor, name = unique
    newclasses.add_evility(fs, mod, new_id, donor, name, None, owner=char_id, order=0,
                           kind=1, slot_cost=0, source=4, shop_rank=0, mana_cost=0)
    aliases[str(int(new_id))] = int(donor)
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.write_text(json.dumps(aliases, indent=1, ensure_ascii=False) + "\n")
    copies = []
    for (sid, copy_of, sname) in skills:
        newclasses.add_skill(fs, mod, sid, copy_of, sname, None, users=[char_id])
        copies.append(dict(new_id=int(sid), copy_of=int(copy_of)))
    char_path = root / "patches/db/char.dat.json"
    patch = json.loads(char_path.read_text())
    row = next(r for r in _rows(patch) if int(r.get("id", -1)) == int(char_id))
    levels = list(learn_levels) or [int(row.get(f"learn{n}_level", 0)) for n in range(1, 4)]
    for n, copy in enumerate(copies, 1):
        row[f"learn{n}_skill"] = copy["new_id"]
        row[f"learn{n}_level"] = levels[n - 1]
    row["learn_count"] = max(int(row.get("learn_count", 0)), len(copies))
    for n in range(1, int(row["learn_count"]) + 1):
        if not int(row.get(f"learn{n}_skill", 0) or 0):
            row[f"learn{n}_level"] = 0
    row["evility1"], row["evility2"], row["evility3"], row["evility4"] = int(new_id), 0, 0, 0
    row["evility_count"] = 1
    char_path.write_text(json.dumps(patch, indent=1, ensure_ascii=False) + "\n")
    return dict(char_id=int(char_id), innate=int(new_id), innate_donor=int(donor),
                skills=copies, learn_levels=levels)
