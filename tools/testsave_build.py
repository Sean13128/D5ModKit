"""TESTSAVE1: test saves holding imported characters as ordinary army units, made by the game's own code.

Why: recruiting every imported character through its quest costs ~5 min each on the live game.  A test save that
already holds them lets a live lane load once and run battles.

How a unit is made (no hand-built bytes):
  the INSTALLED exe (kit hooks included) runs under Unicorn with the INSTALLED Database_0.dat tables in its globals
  (tools/stat_oracle.py's rig) and the save's whole game state at its address (0x144FCCB00).  We call the game's
  own `roster_create_unit 0x1402ea3e0(class, 0, level 1)` (Steam build; the kit's hooks name it 0x1402ea890) = what a recruit quest calls ('join' event command; the
  quest reward then moves the unit reserve -> army with 0x1402ea200, which only renumbers slots and recalcs).
  It runs unit_construct (row lookup, stats roll from the game LCG, innate evilities gated by the save's flag
  bytes, mastery, title, ANM id incl. the kit's anm_id_for_variant hook), bumps the save's serial counter, appends
  the record at the end of the army and recalcs.  Only one routine is stubbed besides HUD/achievement logging:
  unit_random_name 0x14021b2a0 (generic classes draw a random name from name.dat, which the rig does not load); the
  stub writes the class row's own name so every test unit is named after its class.

What the save keeps: the 12 highest-level army units (Killia included), the reserve, every story/progress byte.
Everything else in the army is taken out with savegame.remove_units (the game's Dismiss).  For a unique character
its recruit quest is marked done (what the real recruit leaves behind, so the Quest Shop does not offer it again).

Run (kit venv; copies only, never the live save folder):
    .venv-macos/bin/python tools/testsave_build.py --src <copy of Save_001.sav> --exe <installed disgaea5.exe copy>
        --db <installed Database_0.dat copy> --scope scope.json --mods <installed mods> --out <dir>
    .venv-macos/bin/python tools/testsave_build.py --validate ...   (field diff vs the save's own level-1 units)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

from d5lib import database, savegame, unitbank   # noqa: E402

CREATE = 0x1402EA3E0           # roster_create_unit(class, 0, level) -> record ptr, 0 when the roster is full
                               # (Steam-build address: this tool runs the installed exe; known build 0x1402EA890)
RANDOM_NAME = 0x14021B2A0      # unit_random_name(bank, out)
LANG = 0x140BD7B30             # -> struct, +4 = text language (1 = English)
KEEP = 12
SLOT_PLAN = {"A": 11, "B": 12, "C": 13}     # Save_011.sav .. Save_013.sav; never 1, 2, 4

# what each byte range of a unit record is (Sorrow states/data.md 3.2, savegame/unitbank docstrings)
FIELDS = [
    (0x0, 0x4, "in use"), (0x8, 0x10, "experience"), (0x10, 0xBC8, "equipment (5 items)"),
    (0xBC8, 0xBFC, "name"), (0xBFC, 0xC40, "class title"),
    (0xC40, 0x2CC8, "reserved (zero)"),
    (0x2CC8, 0x2CD8, "current HP/SP"), (0x2CD8, 0x2D18, "max stats"), (0x2D18, 0x2D58, "base stats"),
    (0x2D58, 0x2DA8, "growth remainder/rate"), (0x2DA8, 0x2DF8, "weapon mastery"),
    (0x2DF8, 0x2DFC, "+11768 (mana?)"), (0x2DFC, 0x2E00, "level"), (0x2E00, 0x2E04, "levels over 9999"),
    (0x2E04, 0x2E08, "class id"), (0x2E08, 0x2E0A, "variant"), (0x2E0A, 0x2E0C, "char.dat row"),
    (0x2E0C, 0x2E30, "char.dat copies"), (0x2E30, 0x2E31, "+11824"), (0x2E31, 0x2E32, "roster index"),
    (0x2E32, 0x2E36, "guest flag / misc"), (0x2E36, 0x2E38, "ANM id"), (0x2E38, 0x2E70, "misc"),
    (0x2E70, 0x2EEE, "learned-evility bitmap"), (0x2EEE, 0x2EFC, "innate evilities + counts"),
    (0x2EFC, 0x2F30, "evility slots/capacity"), (0x2F30, 0x3034, "active evility list (rebuilt)"),
    (0x3034, 0x3058, "evility misc"), (0x3058, 0x305A, "squad"), (0x305A, 0x3060, "level max/misc"),
    (0x3060, 0x3068, "serial"), (0x3068, 0x3078, "misc"), (0x3078, 0x3088, "stat percentages"),
    (0x3088, 0x30A0, "misc"), (0x30A0, 0x30A1, "group"), (0x30A1, 0x30A4, "misc"),
    (0x30A4, 0x30A4 + 47 * 24, "class mastery"), (0x30A4 + 47 * 24, 0x35AC, "misc"),
    (0x35AC, 0x35BC, "+13740 id / misc"), (0x35BC, 0x35C4, "feature pick (rng)"), (0x35C4, 0x4750, "tail"),
]


def field_of(off):
    for a, b, name in FIELDS:
        if a <= off < b:
            return name
    return "?"


def diff_fields(a, b):
    """{field: [offsets]} where two records differ"""
    out = {}
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            out.setdefault(field_of(i), []).append(i)
    return out


class Creator:
    """the installed exe + installed tables under Unicorn, holding one save state"""

    def __init__(self, exe, db_path, lcg=0x5EED_D5_7E57):
        import stat_oracle as so
        from unicorn import UC_HOOK_CODE
        self.so = so
        self.db = database.load_database(str(db_path))
        self.e = so.Emu(exe_path=exe, db=self.db, rng_stub=False)
        self.names = {r["id"]: r["name_EN"] for r in self.db["char.dat"].rows}
        # the installed char.dat has mod rows appended; the game binary-searches it by id (+0xD0), so it must be
        # sorted the way the game holds it (savegame: "the game sorts the table by id"; row = sorted position)
        self.e._plain("char.dat", 0x140A03880, 0x140A03888, 908, 0xD0)
        lang = self.e.alloc(bytes(0x100))
        self.e.mu.mem_write(lang + 4, struct.pack("<I", 1))
        self.e.put(LANG, lang)
        self.cls = None
        self.e.stubs[RANDOM_NAME] = self._name
        self.e.mu.hook_add(UC_HOOK_CODE, self.e._stub, begin=RANDOM_NAME, end=RANDOM_NAME)
        self.e.put(so.LCG, lcg)

    def _name(self):
        from unicorn import x86_const as X
        buf = self.e.mu.reg_read(X.UC_X86_REG_RDX)
        self.e.mu.mem_write(buf, self.names.get(self.cls, "Unit").encode()[:0x33] + b"\0")
        return 0

    def load(self, state):
        self.e.mu.mem_write(self.so.BLOCK, bytes(state))

    def state(self):
        return bytearray(self.e.mu.mem_read(self.so.BLOCK, savegame.STATE_SIZE))

    def create(self, cls, level=1):
        """the game's roster_create_unit on the loaded state -> roster slot"""
        if cls not in self.names:
            raise ValueError(f"class {cls} is not in the installed char.dat")
        self.cls = cls
        rec = self.e.call(CREATE, [int(cls), 0, int(level)])
        if not rec:
            raise ValueError("roster_create_unit refused: roster full (army + reserve = 128)")
        return (rec - (self.so.BLOCK + savegame.ROSTER)) // savegame.UNIT


def keep_slots(save, n=KEEP, avoid=()):
    """the n highest-level army units (Killia always), skipping names an added unit will carry (dispatch is by name)"""
    army = sorted((u for u in save.army() if u.cls == savegame.KILLIA or u.name.strip() not in avoid),
                  key=lambda u: (-(u.cls == savegame.KILLIA), -u.level, u.slot))
    return {u.slot for u in army[:n]}


def quest_slots(mods, pack, cls):
    """recruit quest sort_order(s) of this pack for this class"""
    p = Path(mods) / pack / "patches/db/Quest.dat.json"
    if not p.exists():
        return []
    rows = json.loads(p.read_text()).get("added") or []
    return [int(r["sort_order"]) for r in rows
            if int(r.get("reward_type", 0)) == 5 and int(r.get("reward_value", -1)) == cls and "sort_order" in r]


def build_one(creator, src, entries, mods, out_path, tag, level=1):
    save = savegame.Save(str(src))
    keep = keep_slots(save, avoid={creator.names.get(e["cls"], "").strip() for e in entries})
    removed = save.remove_units([u.slot for u in save.army() if u.slot not in keep])
    creator.load(save.state)
    made = []
    for ent in entries:
        slot = creator.create(ent["cls"], level)
        made.append(dict(ent, slot=slot))
    save.state[:] = creator.state()
    for m in made:
        u = savegame.Unit(save, m["slot"])
        m.update(serial=u.serial, name=u.name, title=u.title, level=u.level,
                 row=struct.unpack_from("<h", save.state, u.base + savegame.U_ROW)[0],
                 anm=struct.unpack_from("<H", save.state, u.base + 0x2E36)[0],
                 innate=[x for x in struct.unpack_from("<5H", save.state, u.base + 0x2EEE) if x != 9999],
                 skills=skill_ids(save.state, u.base))
        m["quests_marked_done"] = quest_slots(mods, m["pack"], m["cls"])
        for q in m["quests_marked_done"]:
            save.finish_quest(q)
    problems = check(save, made, level)
    save.path = str(out_path)
    save.write(str(out_path))
    back = savegame.Save(str(out_path))                       # round trip through the kit's own reader
    if back.state != save.state:
        problems.append("read-back differs")
    problems += check(back, made, level)
    names = [u.name for u in back.army()]
    dup = sorted({n for n in names if names.count(n) > 1})
    return dict(save=os.path.basename(out_path), tag=tag, sha256=hashlib.sha256(Path(out_path).read_bytes()).hexdigest(),
                army=back.army_count, reserve=back.reserve_count, kept=[(u.slot, u.name, u.cls, u.level)
                for u in back.army() if u.slot < len(keep)], removed=len(removed), units=made,
                duplicate_names=dup, problems=problems)


def skill_ids(state, base):
    """ids of the unit's skill list (record +0xCC0, 16 bytes each, count at +0x2CC0; id = dword at +4)"""
    n = min(struct.unpack_from("<h", state, base + 0x2CC0)[0], 512)
    return [struct.unpack_from("<I", state, base + 0xCC0 + i * 16 + 4)[0] for i in range(n)]


def check(save, made, level=1):
    bad = list(unitbank.verify(save))
    if save.army_count + save.reserve_count > savegame.SLOTS:
        bad.append("roster over 128")
    for m in made:
        u = savegame.Unit(save, m["slot"])
        if u.cls != m["cls"] or u.level != level or u.squad != -1 or u.group != 0xFF:
            bad.append(f"slot {m['slot']}: class {u.cls} level {u.level} squad {u.squad} group {u.group}")
    return bad


def plan(scope):
    """TEST-A = D4 + D1C + DD2, TEST-B/C = DRPG halves (sorted by pack)"""
    by = {g: sorted((e for e in scope if e["game"] == g), key=lambda e: e["pack"]) for g in ("D4", "D1C", "DD2", "DRPG")}
    half = (len(by["DRPG"]) + 1) // 2
    return {"A": by["D4"] + by["D1C"] + by["DD2"], "B": by["DRPG"][:half], "C": by["DRPG"][half:]}


def validate(creator, src, slots=None):
    """create the class of each of the save's level-1 army units and list which fields differ, and why"""
    save = savegame.Save(str(src))
    rows = []
    for u in save.army():
        if u.level != 1 or (slots and u.slot not in slots):
            continue
        creator.load(save.state)
        slot = creator.create(u.cls)
        got = bytes(creator.state()[savegame.ROSTER + slot * savegame.UNIT:][:savegame.UNIT])
        rec = bytes(save.state[u.base:u.base + savegame.UNIT])
        d = diff_fields(rec, got)
        base_game = list(struct.unpack_from("<8q", rec, 0x2D18))
        base_made = list(struct.unpack_from("<8q", got, 0x2D18))
        row = next(r for r in creator.db["char.dat"].rows if r["id"] == u.cls)
        rolls = creator.so.rolls_consistent([row["base_" + s] for s in creator.so.STATS], 1, base_game)
        rows.append(dict(slot=u.slot, name=u.name, cls=u.cls, serial_game=u.serial,
                         serial_made=struct.unpack_from("<Q", got, savegame.U_SERIAL)[0],
                         name_made=got[0xBC8:0xBFC].split(b"\0")[0].decode("utf-8", "replace"),
                         base_stats_game=base_game, base_stats_made=base_made,
                         game_stats_are_a_creation_roll=all(rolls), rolls=rolls,
                         fields={k: [hex(v[0]), len(v)] for k, v in d.items()}))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--scope")
    ap.add_argument("--mods")
    ap.add_argument("--out")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--level", default="1", help="level of every created unit: a number, or 'killia' = Killia's level in --src")
    a = ap.parse_args(argv)
    root = os.path.abspath(savegame.save_root() or "/nonexistent")
    for p in (a.src, a.out or ""):
        if p and os.path.abspath(p).startswith(root + os.sep):
            raise SystemExit(f"refused: {p} is under the live save folder")
    cr = Creator(a.exe, a.db)
    if a.validate:
        print(json.dumps(validate(cr, a.src), indent=1, ensure_ascii=False))
        return 0
    level = next(u.level for u in savegame.Save(a.src).army() if u.cls == savegame.KILLIA) if a.level == "killia" else int(a.level)
    scope = json.loads(Path(a.scope).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for tag, entries in plan(scope).items():
        n = SLOT_PLAN[tag]
        r = build_one(cr, a.src, entries, a.mods, out / f"Save_{n:03d}.sav", f"TEST-{tag}", level)
        r["slot"] = n; r["level"] = level
        (out / f"Save_{n:03d}.manifest.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
        report.append({k: r[k] for k in ("save", "tag", "army", "reserve", "removed", "duplicate_names", "problems")}
                      | {"added": len(r["units"])})
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0 if all(not r["problems"] for r in report) else 1


if __name__ == "__main__":
    sys.exit(main())
