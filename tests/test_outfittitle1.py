"""OUTFITTITLE1: a unit saved in an outfit keeps its character's story title on load -- proved offline in Unicorn.

Every save load (lifecycle_flows_load_apply -> data_lifecycle_refresh_class_titles, Steam 0x1401C3800) re-copies each
roster unit's title (+0xBFC) from its char.dat row, then the story title override (0x1401C3A90) replaces it by class
id: Killia (10) -> "Cryo Blood Overlord" once her story flag (0x144FCCB65 & 0x20) is set.  An outfit class (473) had
no case there, so she came back as the row's "Wanderer".  identitypatch now maps the override's class argument
through the outfit table.

The game's own refresh runs on the clean Steam exe (STATORACLE1 rig, tools/stat_oracle.Emu) with and without the
identity stubs.  The unit is Killia's real record (outfitown2-live/killia_awakened.bin, read-only) or, when that is
absent, Save1's Killia.  Read-only: nothing is written but tmp_path.
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
LIVE = Path(os.environ.get("D5_OUTFITOWN2_LIVE",
                           "/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/outfitown2-live"))
SAVE1 = Path(os.environ.get("D5_SAVE1_COPY", "/Volumes/Data/ai-tmp/claude/outfitown1/hook/Save1_copy.sav"))

pytestmark = pytest.mark.skipif(not EXE.exists(), reason="needs the clean Disgaea 5 exe")

REFRESH = 0x1401C3800          # data_lifecycle_refresh_class_titles (called by lifecycle_flows_load_apply)
OVERRIDE_SITE = 0x1401C3A9F    # "mov r8, rdx; cmp ecx, 0xdc" in the title override (Steam)
LANG = 0x140BD7B30             # -> settings; +4 text language (1 English)
STORY = 0x144FCCB65            # bit 0x20: Killia's late-story title
ROSTER_N = 0x145574A9C
STRINGS = 0x140A04DE0          # StringListDataBase holder: +8 count, +0x10 records, +0x18 keys, +0x20 records
KILLIA, OUTFIT, WARRIOR = 10, 473, 1010
REC = 0x4750


def _unit():
    p = LIVE / "killia_awakened.bin"
    if p.exists():
        return bytearray(p.read_bytes()[:REC])
    if SAVE1.exists():
        from d5lib import savegame
        s = savegame.Save(str(SAVE1))
        u = next((u for u in s.units() if u.cls == KILLIA), None)
        if u:
            return bytearray(s.state[u.base:u.base + REC])
    pytest.skip("needs Killia's record (outfitown2-live/killia_awakened.bin or a Save1 copy)")


class Rig:
    def __init__(self, exe_path):
        sys.path.insert(0, str(KIT / "tools"))
        import stat_oracle as so
        from d5lib import database
        self.so = so
        db = so.vanilla_db()
        self.emu = e = so.Emu(exe_path=exe_path, db=db)
        t = database.load_table("char.dat", db.raw["char.dat"])
        base = next(r for r in t.rows if r["id"] == KILLIA)
        if not any(r["id"] == OUTFIT for r in t.rows):
            t.add_row(copy_from=t.rows.index(base)).set("id", OUTFIT)      # the outfit row: Killia's, title "Wanderer"
        raws = sorted((bytes(r.raw) for r in t.rows), key=lambda b: struct.unpack_from('<I', b, 0xD0)[0])
        self.index = {struct.unpack_from('<I', b, 0xD0)[0]: i for i, b in enumerate(raws)}
        e.set_chars(struct.pack('<I', len(raws)) + b''.join(raws))
        b = db.raw["StringListDataBase.dat"]
        cnt = struct.unpack_from('<H', b, 0)[0]
        recs = e.alloc(b[4:])
        keys = e.alloc(b''.join(b[4 + 44 * i:8 + 44 * i] for i in range(cnt)))
        e.mu.mem_write(STRINGS + 8, struct.pack('<H', cnt))
        e.put(STRINGS + 0x10, recs)
        e.put(STRINGS + 0x18, keys)
        e.put(STRINGS + 0x20, recs)
        settings = e.alloc(bytes(0x40))
        e.put(settings + 4, 1, '<I')
        e.put(LANG, settings)
        e.put(ROSTER_N, 1, '<i')

    def load_title(self, unit, cls, story=True):
        """the refresh the load runs, on one roster unit of class `cls` -> its title text"""
        e, so = self.emu, self.so
        u = bytearray(unit)
        struct.pack_into('<I', u, 0x2E04, cls)
        struct.pack_into('<h', u, 0x2E0A, self.index[cls])
        e.mu.mem_write(so.ROSTER, bytes(u))
        flag = e.read(STORY, 1)[0]
        e.mu.mem_write(STORY, bytes([(flag | 0x20) if story else (flag & ~0x20)]))
        e.call(REFRESH, [])
        return e.read(so.ROSTER + 0xBFC, 0x44).split(b"\0")[0].decode()


@pytest.fixture(scope="module")
def rigs(tmp_path_factory):
    from d5lib import exemap, identitypatch
    data = EXE.read_bytes()
    old = exemap.ACTIVE
    try:
        exemap.use(exemap.translator_for(data))
        exemap.reset_ledger()
        assert identitypatch.title_site(data) == OVERRIDE_SITE
        patched = identitypatch.patch(data, {OUTFIT: KILLIA}, log=lambda *a: None)
        claimed = [e for e in exemap.LEDGER if e["start"] <= OVERRIDE_SITE < e["end"]]
    finally:
        exemap.reset_ledger()
        exemap.use(old)
    assert claimed, "the title site is not in the site ledger"
    d = tmp_path_factory.mktemp("ot1")
    (d / "patched.exe").write_bytes(patched)
    return {"vanilla": Rig(EXE), "patched": Rig(d / "patched.exe")}


def test_vanilla_reproduces_the_bug(rigs):
    unit = _unit()
    assert unit[0xBFC:0xBFC + 19] == b"Cryo Blood Overlord"     # the record before the load
    v = rigs["vanilla"]
    assert v.load_title(unit, KILLIA) == "Cryo Blood Overlord"
    assert v.load_title(unit, OUTFIT) == "Wanderer"


def test_outfit_keeps_the_story_title(rigs):
    p = rigs["patched"]
    assert p.load_title(_unit(), OUTFIT) == "Cryo Blood Overlord"


def test_normal_class_and_generic_unchanged(rigs):
    unit = _unit()
    for story in (True, False):
        for cls in (KILLIA, WARRIOR):
            assert rigs["patched"].load_title(unit, cls, story) == rigs["vanilla"].load_title(unit, cls, story)
    assert rigs["patched"].load_title(unit, KILLIA, False) == "Wanderer"      # before the story flag: her row title
    assert rigs["patched"].load_title(unit, OUTFIT, False) == "Wanderer"
