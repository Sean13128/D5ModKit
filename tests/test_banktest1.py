"""BANKTEST1: bugs found by testing the character bank on save copies (each test fails without its fix)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
sys.path.insert(0, HERE)

import unit_bank  # noqa: E402


class LiveFolder(unittest.TestCase):
    def test_live_folder_is_recognised_without_appdata(self):
        old = os.environ.pop("APPDATA", None)         # a Mac session: no %APPDATA%
        try:
            wine = ("/Games/steamapps/compatdata/803600/pfx/drive_c/users/steamuser/AppData/Roaming/"
                    "Nippon Ichi Software, Inc/Disgaea 5 Complete/27885847/SaveData/Save_001.sav")
            self.assertTrue(unit_bank.under_live(wine))
            self.assertFalse(unit_bank.under_live("/tmp/save-copies/Save_001.sav"))
        finally:
            if old is not None:
                os.environ["APPDATA"] = old


class BankFile(unittest.TestCase):
    """doctored or damaged bank files must be refused with a sentence, before the save is touched"""

    def setUp(self):
        import json
        import tempfile
        from test_unit_bank_cli import INSTALLED, VANILLA, write_save
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.save = write_save(os.path.join(d, "a.sav"), army=2, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7))])
        unit_bank.export(self.save, 1, os.path.join(d, "b"), VANILLA)
        self.good = json.load(open(os.path.join(d, "b", os.listdir(os.path.join(d, "b"))[0])))
        self.INSTALLED, self.VANILLA, self.json, self.d = INSTALLED, VANILLA, json, d

    def tearDown(self):
        self.tmp.cleanup()

    def refuse(self, doc, want):
        import hashlib
        p = os.path.join(self.d, "x.d5unit.json")
        open(p, "w").write(self.json.dumps(doc))
        tgt = os.path.join(self.d, "t.sav")
        open(tgt, "wb").write(open(self.save, "rb").read())
        h = hashlib.sha256(open(tgt, "rb").read()).hexdigest()
        with self.assertRaisesRegex(unit_bank.Refused, want):
            unit_bank.import_(p, tgt, self.INSTALLED, self.VANILLA)
        self.assertEqual(h, hashlib.sha256(open(tgt, "rb").read()).hexdigest())

    def doc(self, **top):
        d = self.json.loads(self.json.dumps(self.good))
        d.update(top)
        return d

    def test_record_class_must_match_the_listing(self):
        import struct
        from d5lib import savegame
        for cls in (99999, 10):                      # not installed / Killia: the listing says Keke's class
            d = self.doc()
            r = bytearray(bytes.fromhex(d["units"][0]["record"]))
            struct.pack_into("<I", r, savegame.U_CLASS, cls)
            d["units"][0]["record"] = r.hex()
            self.refuse(d, "inconsistent")

    def test_missing_keys_and_wrong_shapes(self):
        for key in ("record", "class", "name"):
            d = self.doc()
            d["units"][0].pop(key)
            self.refuse(d, "damaged")
        self.refuse(self.doc(units=5), "one-unit")
        self.refuse(self.doc(kind="x"), "not a character bank")

    def test_other_format_version(self):
        self.refuse(self.doc(schema=2), "format 2")
        d = self.doc()
        d.pop("schema")
        self.refuse(d, "format None")


# opt-in, on your own files (never shipped): a save COPY, the installed Database_0.dat and a clean Database_0.dat
REAL = os.environ.get("D5_BANK_REAL_SAVE", "")
INSTALLED_DB = os.environ.get("D5_INSTALLED_DB", "")


class RoundTripRealSave(unittest.TestCase):
    """every movable unit of a real save copy: move out, move back, the record differs only where it must"""

    def test_every_unit_round_trips(self):
        import shutil
        import tempfile
        from d5lib import savegame, unitbank
        if not (os.path.isfile(REAL) and os.path.isfile(INSTALLED_DB) and os.path.isfile(unit_bank.VANILLA_DB or "")):
            self.skipTest("set D5_BANK_REAL_SAVE, D5_INSTALLED_DB and D5_VANILLA_DB to run this on your own save copy")
        installed, vanilla = unit_bank.char_names(INSTALLED_DB), unit_bank.char_names(unit_bank.VANILLA_DB)
        allowed = {savegame.U_SERIAL, savegame.U_INDEX, savegame.U_ROW, savegame.U_SQUAD, savegame.U_GROUP}

        def rec(save, slot):
            b = savegame.ROSTER + slot * savegame.UNIT
            return bytes(save.state[b:b + savegame.UNIT])

        def others(save, skip):                       # records by serial, the index byte masked
            return {u.serial: rec(save, u.slot)[:savegame.U_INDEX] + b"\0" + rec(save, u.slot)[savegame.U_INDEX + 1:]
                    for u in save.units() if u.serial != skip}

        with tempfile.TemporaryDirectory() as d:
            src = savegame.Save(REAL)
            moved = 0
            for u in src.army():
                if unit_bank.story_locked(u.cls, vanilla, u.reserve):
                    continue
                work = os.path.join(d, "w.sav")
                shutil.copy(REAL, work)
                r0, rest = rec(src, u.slot), others(src, u.serial)
                out, _ = unit_bank.export(work, u.slot, os.path.join(d, "b"), vanilla, move=True)
                gone = savegame.Save(work)
                self.assertEqual((gone.army_count, unitbank.verify(gone)), (src.army_count - 1, []))
                self.assertEqual(others(gone, None), rest)
                res, _ = unit_bank.import_(str(out), work, installed, vanilla)
                back = savegame.Save(work)
                self.assertEqual(unitbank.verify(back), [])
                r1 = rec(back, res["slot"])
                changed = {i for i in range(len(r0)) if r0[i] != r1[i]}
                self.assertTrue(all(any(a <= i < a + 8 for a in allowed) for i in changed), (u.name, sorted(changed)[:5]))
                self.assertEqual(others(back, res["serial"]), rest)
                moved += 1
            self.assertGreater(moved, 60)


class MoveOutLeavesNoReference(unittest.TestCase):
    """squad / group / follower / base walker / serial list entries of a moved unit are cleaned (the game's Dismiss)"""

    def test_references_are_removed(self):
        import struct
        import tempfile
        from test_unit_bank_cli import VANILLA, write_save
        from d5lib import savegame
        with tempfile.TemporaryDirectory() as d:
            p = write_save(os.path.join(d, "a.sav"), army=3, uid=600, slots=[
                (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=500)),
                (2, dict(name="Zed", cls=190, serial=501))])
            s = savegame.Save(p)
            q = lambda o, v: struct.pack_into("<Q", s.state, o, v)   # noqa: E731
            b = savegame.SQUADS + 3 * savegame.SQUAD_SIZE
            q(b, 500), q(b + 8, 501)
            struct.pack_into("<I", s.state, b + savegame.SQUAD_COUNT, 2)
            struct.pack_into("<h", s.state, savegame.ROSTER + 1 * savegame.UNIT + savegame.U_SQUAD, 3)
            g = savegame.GROUPS + 5 * savegame.GROUP_SIZE
            q(g, 500), q(g + 8, 501)
            s.state[g + savegame.GROUP_SLOTS] = 2
            q(g + savegame.GROUP_LEADER, 500)
            s.state[savegame.ROSTER + 1 * savegame.UNIT + savegame.U_GROUP] = 5
            q(savegame.FOLLOWERS, 500), q(savegame.BASE_WALKER, 500)
            struct.pack_into("<I", s.state, savegame.FOLLOWER_COUNT, 1)
            q(savegame.SERIAL_LISTS + savegame.LIST_LEN * 8 + 8 * 7, 500)
            s.write()
            unit_bank.export(p, "Keke", os.path.join(d, "b"), VANILLA, move=True)
            t = savegame.Save(p)
            u64 = lambda o: struct.unpack_from("<Q", t.state, o)[0]  # noqa: E731
            hits = [o for o in [savegame.BASE_WALKER, savegame.FOLLOWERS, g, g + savegame.GROUP_LEADER, b,
                                savegame.SERIAL_LISTS + savegame.LIST_LEN * 8 + 8 * 7] if u64(o) == 500]
            self.assertEqual(hits, [])
            self.assertEqual(u64(g + savegame.GROUP_LEADER), 501)           # the next member leads


if __name__ == "__main__":
    unittest.main()
