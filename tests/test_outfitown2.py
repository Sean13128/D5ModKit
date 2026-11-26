"""OUTFITOWN2: an outfit's own values reach the unit when it switches outfit -- proved offline in Unicorn.

The real patched exe (exepatch.build_outfit_patch with own masks) runs under the STATORACLE1 rig (tools/stat_oracle.Emu:
the clean Steam exe, the game's tables in its globals).  The unit is a REAL record: Killia (Lv 9999) from a read-only
copy of Save1, or, when that copy is absent, a unit the game itself makes (unit_init_stats + unit_recalc).  The
switch is the one outfit_pick does: new class id to +0x2E04, the game's own FUN_14015F930 (row index, graphics id),
then outfit_apply(unit, old class, old row) -- whose last step is the game's unit_recalc.

Read-only: nothing is written but tmp_path.
"""
import os
import struct
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
STEAM = Path(os.environ.get("D5_CLEAN_GAME",
                            "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)"))
EXE = STEAM / "disgaea5.exe"
SAVE1 = Path(os.environ.get("D5_SAVE1_COPY", "/Volumes/Data/ai-tmp/claude/outfitown1/hook/Save1_copy.sav"))

pytestmark = pytest.mark.skipif(not EXE.exists(), reason="needs the clean Disgaea 5 exe")

SET_CLASS = 0x14015F930          # Steam: row index (+0x2E0A) and graphics id (+0x2E36) for the class at +0x2E04
KILLIA, OUTFIT, OUTFIT2 = 10, 470, 480
ROW = 0x38C
STATS = ("HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD")
WEAPONS = ("fist", "sword", "spear", "bow", "gun", "axe", "staff", "monster_phys", "monster_mag")
MOVE_FIELDS = (("MOV", 0x2E1C), ("JMP", 0x2E1A), ("counter", 0x2E1E), ("throw", 0x2E20), ("crit", 0x2E22))

# what unit_recalc rebuilds from the fields outfit_apply moves (Sorrow data__data-unitstats.md §4, decomp 0x14021BFB0):
# working stats +0x2CD8, HP/SP +0x2CC8, potency words +0x3068, effective weapon aptitude +0x2DAD+8k, final
# movement bytes +0x2E1B/1D/1F/21/23, final resistances +0x2E16..19, the evility list +0x2F30..+0x3033, the
# evility point sums +0xC40..+0xCC0, the skill list +0xCC0.. (5.11) and the class kind byte +0x2E2A
RECALC_OWNED = [(0x2CC8, 0x2D18), (0x3068, 0x3078), (0x2E16, 0x2E1A), (0x2F30, 0x3034), (0xC40, 0x2CC8),
                (0x2E1B, 0x2E1C), (0x2E1D, 0x2E1E), (0x2E1F, 0x2E20), (0x2E21, 0x2E22), (0x2E23, 0x2E24),
                (0x2E2A, 0x2E2B)] + [(0x2DAD + 8 * k, 0x2DAE + 8 * k) for k in range(10)]


def _owned(off):
    return any(a <= off < b for a, b in RECALC_OWNED)


# ------------------------------------------------------------------------------------------------- the rig
class Rig:
    def __init__(self, tmp, masks, rows):
        sys.path.insert(0, str(KIT / "tools"))
        import stat_oracle as so
        from d5lib import database, exemap, exepatch, outfitapply
        self.so, self.outfitapply = so, outfitapply
        data = EXE.read_bytes()
        old = exemap.ACTIVE
        try:
            exemap.use(exemap.translator_for(data))
            recs = [(0, KILLIA, 1001)] + [(0, cid, 1002 + i) for i, cid in enumerate(sorted(rows))]
            patched = exepatch.build_outfit_patch(data, recs, 40001, 40002, own_masks=masks)
        finally:
            exemap.use(old)
        path = Path(tmp) / "disgaea5.exe"
        path.write_bytes(patched)
        self.apply = outfitapply.apply_va(patched)
        assert self.apply, "outfit_apply not found in the patched exe"
        db = so.vanilla_db()
        self.emu = so.Emu(exe_path=path, db=db)
        t = database.load_table("char.dat", db.raw["char.dat"])
        base = next(r for r in t.rows if r["id"] == KILLIA)
        self.killia = base
        for cid, values in rows.items():
            nr = t.add_row(copy_from=t.rows.index(base))
            nr.set("id", cid)
            for k, v in values.items():
                nr.set(k, v)
        raws = sorted((bytes(r.raw) for r in t.rows), key=lambda b: struct.unpack_from('<I', b, 0xD0)[0])
        self.rows = {struct.unpack_from('<I', b, 0xD0)[0]: b for b in raws}
        self.index = {struct.unpack_from('<I', b, 0xD0)[0]: i for i, b in enumerate(raws)}
        self.emu.set_chars(struct.pack('<I', len(raws)) + b''.join(raws))
        self.recalcs = 0
        from unicorn import UC_HOOK_CODE
        self.emu.mu.hook_add(UC_HOOK_CODE, self._count, begin=so.RECALC, end=so.RECALC)

    def _count(self, *a):
        self.recalcs += 1

    def put_unit(self, rec):
        self.emu.mu.mem_write(self.so.ROSTER, bytes(rec))

    def unit(self):
        return bytearray(self.emu.read(self.so.ROSTER, self.so.REC))

    def recalc(self):
        self.emu.call(self.so.RECALC, [self.so.ROSTER, 0, 0])

    def switch(self, cls):
        """outfit_pick's own sequence: keep old class / row, set the class, FUN_14015F930, outfit_apply"""
        u = self.unit()
        old_cls = struct.unpack_from('<I', u, 0x2E04)[0]
        old_row = struct.unpack_from('<h', u, 0x2E0A)[0]
        self.emu.put(self.so.ROSTER + 0x2E04, cls, '<I')
        self.emu.call(SET_CLASS, [self.so.ROSTER])
        assert struct.unpack_from('<h', self.unit(), 0x2E0A)[0] == self.index[cls]
        self.emu.call(self.apply, [self.so.ROSTER, old_cls, old_row & 0xFFFFFFFF])
        return self.unit()


def save1_killia():
    if not SAVE1.exists():
        return None
    from d5lib import savegame
    s = savegame.Save(str(SAVE1))
    u = next((u for u in s.units() if u.cls == KILLIA), None)
    return bytearray(s.state[u.base:u.base + 0x4750]) if u else None


def made_killia(rig, level=500):
    """a Killia the game makes itself (STATORACLE1's fresh(): unit_init_stats + unit_recalc), innate slots filled
    as unit_construct does (evility1..count of her row)"""
    e = rig.emu
    row = rig.rows[KILLIA]
    e.fresh(row, rig.index[KILLIA], level, 12345)
    u = rig.unit()
    n = row[0xC8]
    for i in range(n):
        struct.pack_into('<H', u, 0x2EEE + 2 * i, struct.unpack_from('<I', row, 0xB8 + 4 * i)[0])
    struct.pack_into('<h', u, 0x2EF8, n)
    struct.pack_into('<I', u, 0x3034, 3)    # two extra-slot bits: recalc keeps 1 + 2 = 3 innate slots (+0x2EFA)
    struct.pack_into('<I', u, 0x2E04, KILLIA)
    for k in range(9):
        u[0x2DAE + 8 * k] = row[0x358 + 2 * k]
    rig.put_unit(u)
    e.call(SET_CLASS, [rig.so.ROSTER])      # graphics id +0x2E36, as the game has it
    return rig.unit()


def start_unit(rig):
    u = save1_killia() or made_killia(rig)
    struct.pack_into('<h', u, 0x2E0A, rig.index[KILLIA])     # this rig's row order
    rig.put_unit(u)
    rig.recalc()                     # the record as the game would have it after any recalc on this table
    return rig.unit()


# an outfit that changes every covered group
OWN = {
    "base_HP": 60, "base_ATK": 10, "base_INT": 40, "base_SPD": 30,
    "apt_ATK": 90, "apt_INT": 140, "apt_HIT": 110,
    "mastery_sword": 4, "mastery_staff": 20, "mastery_gun": 12,
    "MOV": 7, "JMP": 40, "counter": 0, "throw": 2, "crit": 15,
    "res_fire": 50, "res_ice": -50, "res_star": 25,
    "evility1": 1010, "evility2": 11, "evility_count": 2,       # Wild Cry instead of War Demon; Hero (11) kept
}
ALL = 63


def _u(b, fmt, off):
    return struct.unpack_from(fmt, b, off)[0]


def _expected(rig, before, old, new, level):
    """the delta rule, written out independently of the assembly"""
    exp = {}
    for k, s in enumerate(STATS):
        d = _u(new, '<h', 4 + 2 * k) - _u(old, '<h', 4 + 2 * k)
        g = max(1, min(255, before[0x2DA0 + k] + d))
        exp[f"growth_{s}"] = (0x2DA0 + k, '<B', g)
        q = d * (level + 1)
        q = -((-q) // 2) if q < 0 else q // 2
        exp[f"base_{s}"] = (0x2D18 + 8 * k, '<q', max(1, _u(before, '<q', 0x2D18 + 8 * k) + q))
        exp[f"apt_{s}"] = (0x3078 + 2 * k, '<H', max(0, min(0xFFFF, _u(before, '<H', 0x3078 + 2 * k)
                                                           + new[0x350 + k] - old[0x350 + k])))
    for k, w in enumerate(WEAPONS):
        d = _u(new, '<h', 0x358 + 2 * k) - _u(old, '<h', 0x358 + 2 * k)
        exp[f"mastery_{w}"] = (0x2DAE + 8 * k, '<b', max(0, min(127, _u(before, '<b', 0x2DAE + 8 * k) + d)))
    for roff, uoff in rig.outfitapply.MOVEMENT:
        exp[f"move_{uoff:#x}"] = (uoff, '<B', max(0, min(255, before[uoff] + new[roff] - old[roff])))
    for k in range(4):
        d = _u(new, '<b', 0x36C + k) - _u(old, '<b', 0x36C + k)
        exp[f"res_{k}"] = (0x2E12 + k, '<b', max(-128, min(127, _u(before, '<b', 0x2E12 + k) + d)))
    return exp


def _diff(a, b):
    return [i for i in range(len(a)) if a[i] != b[i]]


# ------------------------------------------------------------------------------------------------- tests
@pytest.fixture(scope="module")
def rig(tmp_path_factory):
    return Rig(tmp_path_factory.mktemp("oo2"), {OUTFIT: ALL}, {OUTFIT: OWN})


def test_round_trip_every_group(rig):
    start = start_unit(rig)
    level = _u(start, '<h', 0x2DFC)
    old, new = rig.rows[KILLIA], rig.rows[OUTFIT]
    exp = _expected(rig, start, old, new, level)
    n0 = rig.recalcs
    worn = rig.switch(OUTFIT)
    assert rig.recalcs == n0 + 1
    bad = {k: (_u(worn, f, o), v) for k, (o, f, v) in exp.items() if _u(worn, f, o) != v}
    assert not bad, bad
    # something visible moved: Killia's ATK aptitude and her INT base stat
    assert _u(worn, '<H', 0x3078 + 4) != _u(start, '<H', 0x3078 + 4)
    assert _u(worn, '<q', 0x2D18 + 32) != _u(start, '<q', 0x2D18 + 32)
    # evilities: War Demon (10) gave its slot to Wild Cry (1010); Hero (11) stays where it was
    slots = struct.unpack_from('<5H', worn, 0x2EEE)
    assert slots[:2] == (1010, 11) and _u(worn, '<h', 0x2EF8) == 2, slots
    # ... and the recalc rebuilt the active list from them
    lst = sorted(struct.unpack_from(f'<{_u(worn, "<i", 0x3030)}i', worn, 0x2F30))
    assert 1010 in lst and 11 in lst and 10 not in lst, lst
    # nothing outside the covered fields and what recalc owns changed
    covered = {o + i for (o, f, _) in exp.values() for i in range(struct.calcsize(f))}
    covered |= set(range(0x2EEE, 0x2EFA)) | set(range(0x2E04, 0x2E08)) | {0x2E0A, 0x2E0B, 0x2E36, 0x2E37}
    stray = [hex(i) for i in _diff(start, worn) if i not in covered and not _owned(i)]
    assert not stray, stray
    back = rig.switch(KILLIA)
    assert _diff(start, back) == [], [hex(i) for i in _diff(start, back)][:40]


def test_equal_rows_change_nothing(tmp_path):
    """an outfit that keeps own values equal to its character's: byte-identical, no recalc"""
    r = Rig(tmp_path, {OUTFIT: ALL}, {OUTFIT: {}})
    start = start_unit(r)
    n0 = r.recalcs
    worn = r.switch(OUTFIT)
    assert r.recalcs == n0
    assert [i for i in _diff(start, worn) if i not in (0x2E04, 0x2E05, 0x2E06, 0x2E07, 0x2E0A, 0x2E0B,
                                                        0x2E36, 0x2E37)] == []


def test_groups_not_owned_are_left_alone(tmp_path):
    """a row that differs (a body-kind outfit's mastery, an imported row's stats) but whose pack declares no own
    values for those groups: the switch moves nothing"""
    r = Rig(tmp_path, {OUTFIT: 4}, {OUTFIT: {"mastery_staff": 20, "base_ATK": 99, "MOV": 9, "apt_ATK": 80}})
    start = start_unit(r)
    worn = r.switch(OUTFIT)
    # only aptitudes (bit 4) follow; mastery, base stats and MOV stay
    assert _u(worn, '<H', 0x3078 + 4) == _u(start, '<H', 0x3078 + 4) + 80 - r.rows[KILLIA][0x352]
    assert worn[0x2DAE + 6 * 8] == start[0x2DAE + 6 * 8]
    assert _u(worn, '<q', 0x2D18 + 16) == _u(start, '<q', 0x2D18 + 16)
    assert worn[0x2E1C] == start[0x2E1C]


def test_no_masks_builds_the_same_exe():
    from d5lib import exemap, exepatch
    data = EXE.read_bytes()
    old = exemap.ACTIVE
    try:
        exemap.use(exemap.translator_for(data))
        a = exepatch.build_outfit_patch(data, [(0, KILLIA, 1001), (0, OUTFIT, 1002)], 40001, 40002)
        b = exepatch.build_outfit_patch(data, [(0, KILLIA, 1001), (0, OUTFIT, 1002)], 40001, 40002, own_masks={})
    finally:
        exemap.use(old)
    assert a == b


def test_clamps(tmp_path):
    """rank-up's clamp on the growth bytes (1..255), mastery 0..127, movement 0..255, resistance -128..127"""
    own = {"base_HP": 2000, "base_SP": 0, "mastery_fist": 0, "JMP": 255, "res_wind": 127, "res_ice": -128}
    r = Rig(tmp_path, {OUTFIT: ALL}, {OUTFIT: own})
    start = start_unit(r)
    worn = r.switch(OUTFIT)
    assert worn[0x2DA0] == 255                      # HP growth clamps high
    assert worn[0x2DA1] == max(1, start[0x2DA1] - _u(r.rows[KILLIA], '<h', 6))
    assert worn[0x2DA1] >= 1
    assert worn[0x2E1A] == min(255, start[0x2E1A] + 255 - r.rows[KILLIA][0x37C])
    assert -128 <= _u(worn, '<b', 0x2E14) and _u(worn, '<b', 0x2E13) <= 127
    assert _u(worn, '<b', 0x2DAE) >= 0


def test_evility_in_both_rows_and_surplus(tmp_path):
    """outfit [11, 1010, 2010]: Hero (11) is in both rows and stays put; War Demon's slot goes to Wild Cry; Explosive
    Body is a surplus new one and goes in right after Wild Cry (its predecessor in the outfit's row) while a slot is
    free; switching back restores the slots"""
    r = Rig(tmp_path, {OUTFIT: 1}, {OUTFIT: {"evility1": 11, "evility2": 1010, "evility3": 2010,
                                             "evility_count": 3}})
    start = start_unit(r)
    struct.pack_into('<h', start, 0x2EFA, 3)                   # three innate slots (Killia in Save1 has 3)
    r.put_unit(start)
    worn = r.switch(OUTFIT)
    assert struct.unpack_from('<5H', worn, 0x2EEE)[:3] == (1010, 2010, 11), struct.unpack_from('<5H', worn, 0x2EEE)
    assert _u(worn, '<h', 0x2EF8) == 3
    back = r.switch(KILLIA)
    assert struct.unpack_from('<5H', back, 0x2EEE) == struct.unpack_from('<5H', start, 0x2EEE)
    assert _u(back, '<h', 0x2EF8) == _u(start, '<h', 0x2EF8)


def test_fewer_evilities_and_back(tmp_path):
    """outfit [1010] only: both of Killia's go, Wild Cry takes the first slot; back: War Demon, then Hero after it"""
    r = Rig(tmp_path, {OUTFIT: 1}, {OUTFIT: {"evility1": 1010, "evility2": 0, "evility_count": 1}})
    start = start_unit(r)
    worn = r.switch(OUTFIT)
    assert struct.unpack_from('<5H', worn, 0x2EEE) == (1010, 9999, 9999, 9999, 9999)
    assert _u(worn, '<h', 0x2EF8) == 1
    back = r.switch(KILLIA)
    assert struct.unpack_from('<5H', back, 0x2EEE) == struct.unpack_from('<5H', start, 0x2EEE)


def test_story_gated_evility_not_held(tmp_path):
    """a unit missing one of its row's evilities (story-gated Hero, 11): the outfit's replacement for it is not
    given either, and switching back does not hand the gated one out"""
    r = Rig(tmp_path, {OUTFIT: 1}, {OUTFIT: {"evility1": 1010, "evility2": 2010, "evility_count": 2}})
    start = start_unit(r)
    struct.pack_into('<5H', start, 0x2EEE, 10, 9999, 9999, 9999, 9999)
    struct.pack_into('<h', start, 0x2EF8, 1)
    r.put_unit(start)
    r.recalc()
    start = r.unit()
    worn = r.switch(OUTFIT)
    assert struct.unpack_from('<5H', worn, 0x2EEE)[:2] == (1010, 9999)
    back = r.switch(KILLIA)
    assert _diff(start, back) == []


def test_outfit_evility_already_learned(tmp_path):
    """the unit already has the outfit's evility equipped as a learned one: the innate slot still takes it (the
    record round-trips); the active list then holds it twice while the outfit is worn"""
    r = Rig(tmp_path, {OUTFIT: 1}, {OUTFIT: {"evility1": 1010, "evility2": 11, "evility_count": 2}})
    start = start_unit(r)
    n = _u(start, '<h', 0x2F24)                                  # learned list 1 (+0x2EFC, count +0x2F24)
    assert n < 10
    struct.pack_into('<H', start, 0x2EFC + 2 * n, 1010)         # Wild Cry equipped as a learned evility
    struct.pack_into('<h', start, 0x2F24, n + 1)
    r.put_unit(start)
    r.recalc()
    start = r.unit()
    worn = r.switch(OUTFIT)
    assert struct.unpack_from('<2H', worn, 0x2EEE) == (1010, 11)
    lst = list(struct.unpack_from(f'<{_u(worn, "<i", 0x3030)}i', worn, 0x2F30))
    assert lst.count(1010) == 2, lst
    back = r.switch(KILLIA)
    assert _diff(start, back) == []


def test_outfit_to_outfit(tmp_path):
    """outfit A (own stats) -> outfit B (own evilities) -> base: the record ends where it started"""
    r = Rig(tmp_path, {OUTFIT: 2 | 4, OUTFIT2: 1},
            {OUTFIT: {"base_ATK": 10, "apt_ATK": 90}, OUTFIT2: {"evility1": 1010, "evility2": 11,
                                                                 "evility_count": 2}})
    start = start_unit(r)
    a = r.switch(OUTFIT)
    b = r.switch(OUTFIT2)
    # B follows Killia's stats: leaving A for B takes A's stat difference back off
    for k in range(8):
        assert _u(b, '<q', 0x2D18 + 8 * k) == _u(start, '<q', 0x2D18 + 8 * k)
        assert _u(b, '<H', 0x3078 + 2 * k) == _u(start, '<H', 0x3078 + 2 * k)
    assert struct.unpack_from('<2H', b, 0x2EEE) == (1010, 11)
    assert a != b
    back = r.switch(KILLIA)
    assert _diff(start, back) == []


def test_body_kind_outfit_without_own_values(tmp_path):
    """DRPG-K4 bodies: a monster-body look of a humanoid character keeps its body fields and monster mastery
    (outfits._follow_base); with no own values declared the switch moves nothing and recalc is not called"""
    r = Rig(tmp_path, {OUTFIT2: 1}, {OUTFIT: {"body_type": 1, "mastery_monster_phys": 15, "mastery_sword": 0},
                                     OUTFIT2: {}})
    start = start_unit(r)
    n0 = r.recalcs
    worn = r.switch(OUTFIT)
    assert r.recalcs == n0
    assert [i for i in _diff(start, worn) if i not in (0x2E04, 0x2E05, 0x2E06, 0x2E07, 0x2E0A, 0x2E0B,
                                                        0x2E36, 0x2E37)] == []


def test_masks_from_own_fields():
    from d5lib import outfitapply
    m = outfitapply.masks({470: {"evilities": {"evility1": 1}, "weapon_resistances": {"wres_fist": 5}},
                           480: {"weapon_resistances": {"wres_fist": 5}}, 490: {"movement": {"MOV": 6},
                                                                                "resistances": {"res_fire": 1}}})
    assert m == {470: 1, 490: 16 | 32}


@pytest.mark.parametrize("own", [{}, {OUTFIT: {"base_stats": {"base_ATK": 50}, "weapon_resistances": {"wres_fist": 9}}}])
def test_finalizer_emits_apply_only_for_own_values(own):
    """the installer's own outfit finalizer on the clean game files (Killia + one outfit row): the switch routine is
    in the exe exactly when an outfit keeps own values for a covered group"""
    from d5lib import database, exemap, gamefs, modsys, outfitapply, outfits
    old = exemap.ACTIVE
    try:
        fs = gamefs.GameFS(str(STEAM))
        exemap.use(exemap.translator_for(fs.read(outfits.EXE_FILE)))
        ctx = modsys.BuildContext(fs, log=lambda *a: None)
        t = database.load_table("char.dat", fs.read(outfits.CHAR))
        base = next(r for r in t.rows if r["id"] == KILLIA)
        t.add_row(copy_from=t.rows.index(base)).set("id", OUTFIT)
        ctx.put(outfits.CHAR, t.to_bytes())
        ctx._outfit_system = "Outfit_System"
        ctx._outfit_pairs = [[KILLIA, OUTFIT]]
        ctx._outfit_own_fields = own
        outfits._finalize(ctx)
        va = outfitapply.apply_va(ctx.get(outfits.EXE_FILE))
        assert (va is not None) == bool(own)
        rows = {r["id"]: r for r in database.load_table("char.dat", ctx.get(outfits.CHAR)).rows}
        if own:
            assert rows[OUTFIT]["base_ATK"] == 50 and rows[KILLIA]["base_ATK"] != 50
    finally:
        exemap.use(old)
