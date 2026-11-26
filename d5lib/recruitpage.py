"""RECRUITPAGE1: the model behind the Recruiter list page -- which characters a mod lets the player recruit at the
Dark Assembly, and the mod data that says so.  No widgets, no game: d5gui/pages/recruitpage.py is the page.

A "bill" here is one Dark Assembly (Strategy Assembly) bill that creates one character or a pack of them
(d5lib/wishrecruit.py: RECRUIT1 the hooks, RECRUIT2 the packs; the hook design is Cryswar's Overlord recruit wish,
The Unlicense).  Saving a list writes exactly the two files that module reads, nothing else:

  patches/db/WishDataBase.dat.json    {"table": "WishDataBase.dat", "added": [one row per bill]}   the bill itself
  patches/wishes/recruit_wishes.json  {"recruits": {"<bill id>": member | [member, ...]}}           who joins

A member is {"character": char.dat id, "level": 1..9999, "duplicates": bool}.  The bill row carries the name, the
text, the mana cost, the difficulty and an optional unlock flag (req_flag1; the game's own predicate applies it).
Rows and entries this page did not make (other WishDataBase rows, other mods' bills) are never touched: only the
bill ids the mod already lists in recruit_wishes.json, or the ones saved now, are rewritten.

Everything is validated by wishrecruit.normalise (ids >= 2000, level range, a class twice, pack <= 128) plus the
page's own checks (a bill id may not be one of the game's WishDataBase ids, a character must exist).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import wishrecruit

DB_FOLDER, DB_FILE = "db", "WishDataBase.dat.json"
LANGS = ("JP", "EN", "FR", "CHN", "KOR")
DEFAULT_MANA, DEFAULT_DIFFICULTY = 10, 3
ROSTER_MAX = wishrecruit.ROSTER_MAX
FLAG_FIELDS = ("req_flag1",)


@dataclass
class Member:
    character: int
    level: int = 1
    duplicates: bool = False

    def to_json(self):
        d = {"character": int(self.character), "level": int(self.level)}
        if self.duplicates:
            d["duplicates"] = True
        return d


@dataclass
class Bill:
    id: int
    name: str
    text: str = ""
    members: list = field(default_factory=list)
    mana_cost: int = DEFAULT_MANA
    difficulty: int = DEFAULT_DIFFICULTY
    req_flag: int = 0                 # the game's unlock flag the bill waits for (0 = always listed)
    extra: dict = field(default_factory=dict)   # other fields of an existing row (block/set/clear flags ...), kept


def row_for(bill: Bill) -> dict:
    """the WishDataBase.dat row of a bill: the kept fields of an earlier row, then what the page owns"""
    row = dict(bill.extra)
    row["id"] = int(bill.id)
    for lg in LANGS:
        row[f"name_{lg}"] = bill.name
        row[f"desc_{lg}"] = bill.text
    row["mana_cost"] = int(bill.mana_cost)
    row["difficulty"] = int(bill.difficulty)
    row["req_flag1"] = int(bill.req_flag)
    return row


def recruits_json(bills) -> dict:
    out = {}
    for b in bills:
        ms = [m.to_json() for m in b.members]
        out[str(int(b.id))] = ms[0] if len(ms) == 1 else ms
    return out


# ------------------------------------------------------------------------------------------------ load
def _members(v):
    return [Member(int(m["character"]), int(m.get("level", 1)), bool(m.get("duplicates")))
            for m in (v if isinstance(v, list) else [v])]


def load_bills(mod) -> list:
    """the bills a mod already has, joined from its two files (a recruit entry without a row is still listed, with
    its id as the name, so the page can show and repair it)"""
    rec = (mod.load_patch(wishrecruit.FOLDER, wishrecruit.DATA_FILE) or {}).get("recruits") or {}
    rows = {int(r["id"]): r for r in (mod.load_patch(DB_FOLDER, DB_FILE) or {}).get("added") or [] if "id" in r}
    bills = []
    for k in sorted(rec, key=int):
        bid = int(k)
        row = rows.get(bid)
        if row is None:
            bills.append(Bill(bid, f"bill {bid}", members=_members(rec[k])))
            continue
        owned = {"id", "mana_cost", "difficulty", "req_flag1"} | {f"{p}_{lg}" for p in ("name", "desc") for lg in LANGS}
        bills.append(Bill(bid, row.get("name_EN") or f"bill {bid}", row.get("desc_EN") or "", _members(rec[k]),
                          int(row.get("mana_cost", DEFAULT_MANA)), int(row.get("difficulty", DEFAULT_DIFFICULTY)),
                          int(row.get("req_flag1", 0)),
                          {a: v for a, v in row.items() if a not in owned}))
    return bills


def installed_characters(mod, vanilla_char=None) -> dict:
    """{char.dat id: name} of what the mod adds that a save can hold (savegame.mod_characters)"""
    from . import savegame
    return dict(savegame.mod_characters(mod, vanilla_char)["classes"])


# ------------------------------------------------------------------------------------------------ edit
def next_bill_id(bills, taken=()) -> int:
    """the lowest free id >= 2000 (not one of `bills`, not in `taken`: the game's / other mods' WishDataBase ids)"""
    used = {int(b.id) for b in bills} | {int(t) for t in taken}
    i = wishrecruit.MIN_ID
    while i in used:
        i += 1
    return i


def new_bill(bills, name, members, taken=(), **kw) -> Bill:
    b = Bill(next_bill_id(bills, taken), name, members=list(members), **kw)
    bills.append(b)
    return b


def single(character, name, level=1, **kw):
    """one bill for one character: ("Recruit Stella", level 10)"""
    return Bill(0, name, members=[Member(int(character), int(level))], **kw)


# ------------------------------------------------------------------------------------------------ check
def check(bills, taken=(), characters=None) -> list:
    """plain-sentence problems that would make the install refuse (or the bill never show); [] = fine.
    taken: WishDataBase ids that are not these bills' (the game's, other mods'); characters: {id: name} that exist"""
    problems, seen, taken = [], set(), {int(t) for t in taken}
    for b in bills:
        label = f"bill {b.id} ({b.name})"
        if b.id in seen:
            problems.append(f"{label}: the id is used twice")
        seen.add(b.id)
        if b.id in taken:
            problems.append(f"{label}: {b.id} is already a WishDataBase row of the game or another mod")
        if not b.name.strip():
            problems.append(f"{label}: needs a name")
        if not b.members:
            problems.append(f"{label}: lists no character")
        for f_, lo in (("mana_cost", 0), ("difficulty", 0), ("req_flag", 0)):
            if int(getattr(b, f_)) < lo:
                problems.append(f"{label}: {f_} can't be negative")
        try:
            wishrecruit.normalise(recruits_json([b]))
        except ValueError as e:
            problems.append(str(e))
        if characters is not None:
            for m in b.members:
                if m.character not in characters:
                    problems.append(f"{label}: no character {m.character} in this mod or the game")
    return problems


def room(bill: Bill, owned_classes, roster_total) -> tuple:
    """(listed, why not) as the game would show the bill right now: the wishrecruit predicate's two rules
    (roster_total = army + reserve; owned_classes = class ids in the army).  The game's own req/block flags are
    applied after these by the game and are not known here."""
    n = len(bill.members)
    if roster_total + n > ROSTER_MAX:
        return False, f"the roster has {roster_total} of {ROSTER_MAX}; this bill adds {n}"
    owned = set(owned_classes)
    for m in bill.members:
        if not m.duplicates and m.character in owned:
            return False, f"character {m.character} is already in the army (allow a second copy to list it)"
    return True, ""


# ------------------------------------------------------------------------------------------------ save
def save_bills(mod, bills, taken=(), characters=None, previous=None) -> dict:
    """check, then write the mod's two files.  previous = the ids this page managed before (default: the ids in the
    mod's recruit_wishes.json): their rows/entries are replaced or removed; every other row and entry is kept.
    Raises ValueError listing every problem and writes nothing.  -> {"bills": n, "removed": [ids]}"""
    old = {int(k) for k in ((mod.load_patch(wishrecruit.FOLDER, wishrecruit.DATA_FILE) or {}).get("recruits") or {})}
    managed = old if previous is None else {int(p) for p in previous}
    bad = check(bills, taken, characters)
    if bad:
        raise ValueError("; ".join(bad))
    keep_ids = {int(b.id) for b in bills}
    removed = sorted(managed - keep_ids)

    rec_doc = copy.deepcopy(mod.load_patch(wishrecruit.FOLDER, wishrecruit.DATA_FILE) or {})
    rec = {k: v for k, v in (rec_doc.get("recruits") or {}).items() if int(k) not in managed | keep_ids}
    rec.update(recruits_json(bills))
    rec_doc["recruits"] = dict(sorted(rec.items(), key=lambda kv: int(kv[0])))
    wishrecruit.normalise(rec_doc["recruits"])          # the whole file, as the installer will read it

    db_doc = copy.deepcopy(mod.load_patch(DB_FOLDER, DB_FILE) or {"table": "WishDataBase.dat"})
    db_doc.setdefault("table", "WishDataBase.dat")
    rows = [r for r in db_doc.get("added") or [] if int(r.get("id", -1)) not in managed | keep_ids]
    rows += [row_for(b) for b in sorted(bills, key=lambda b: b.id)]
    db_doc["added"] = rows

    mod.save_patch(DB_FOLDER, DB_FILE, db_doc if (rows or len(db_doc) > 2) else None)
    mod.save_patch(wishrecruit.FOLDER, wishrecruit.DATA_FILE, rec_doc if (rec_doc["recruits"] or len(rec_doc) > 1) else None)
    return {"bills": len(bills), "removed": removed}
