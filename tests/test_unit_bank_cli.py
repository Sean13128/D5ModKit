"""BANK1: tools/unit_bank.py on synthetic save files (real container, no game data): a round trip and one
test per refusal."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
sys.path.insert(0, HERE)

from d5lib import savegame  # noqa: E402
import unit_bank  # noqa: E402
from test_unitbank import FakeSave  # noqa: E402

VANILLA = {10: "Killia", 40: "Seraphina", 190: "Unique Dummy", 570: "Valvatorez"}
INSTALLED = {**VANILLA, 190: "Keke", 150: "Imported", 1010: "Warrior"}
# FakeSave's char.dat is ids 1..199 + 570, so the units below use ids from that set


def write_save(path, **kw):
    fake = FakeSave(**kw)
    s = savegame.Save.__new__(savegame.Save)
    s.path = path
    s.header = bytearray(savegame.MAGIC.ljust(savegame.HEADER, b"\0"))
    s.state = fake.state
    s.write()
    return path


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = unit_bank.main(list(argv), installed=INSTALLED, vanilla=VANILLA)
    return code, out.getvalue()


class UnitBankCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.a = write_save(os.path.join(self.d, "a.sav"), army=3, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7)),
            (2, dict(name="Ghost", cls=77, serial=9))])
        self.b = write_save(os.path.join(self.d, "b.sav"), army=1, uid=40,
                            slots=[(0, dict(name="Killia", cls=10, serial=1))])
        self.bank = os.path.join(self.d, "bank")

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, unit="Keke"):
        code, text = run("export", self.a, unit, self.bank)
        self.assertEqual(code, 0, text)
        return os.path.join(self.bank, os.listdir(self.bank)[0])

    def test_round_trip(self):
        before_a = open(self.a, "rb").read()
        f = self.export()
        self.assertEqual(open(self.a, "rb").read(), before_a)             # export never writes the save
        code, text = run("list", self.bank)
        self.assertIn("Keke", text)
        code, text = run("import", f, self.b)
        self.assertEqual(code, 0, text)
        b, a = savegame.Save(self.b), savegame.Save(self.a)
        self.assertEqual(b.army_count, 2)
        u, src = b.army()[1], a.army()[1]
        self.assertEqual((u.name, u.cls, u.level, u.serial), ("Keke", 190, 7, 41))   # ++counter, as the game
        ra = bytearray(a.state[src.base:src.base + savegame.UNIT])
        rb = bytearray(b.state[u.base:u.base + savegame.UNIT])
        for off, n in ((savegame.U_SERIAL, 8), (savegame.U_ROW, 2)):       # re-addressed: serial, char.dat row
            ra[off:off + n] = rb[off:off + n] = bytes(n)
        self.assertEqual(ra, rb)                                           # the rest byte for byte

    def test_refuses_class_not_installed(self):
        f = self.export("Ghost")                                           # class 77: no installed row
        before = open(self.b, "rb").read()
        code, text = run("import", f, self.b)
        self.assertEqual(code, 2)
        self.assertIn("not in the installed char.dat", text)
        self.assertEqual(open(self.b, "rb").read(), before)

    def test_refuses_full_roster(self):
        f = self.export()
        full = write_save(os.path.join(self.d, "full.sav"), army=127, reserve=1, uid=500,
                          slots=[(i, dict(cls=150, serial=i + 1)) for i in range(128)])
        before = open(full, "rb").read()
        code, text = run("import", f, full)
        self.assertEqual(code, 2)
        self.assertIn("128 limit", text)
        self.assertEqual(open(full, "rb").read(), before)

    def test_refuses_story_locked(self):
        code, text = run("export", self.a, "Killia", self.bank)            # leaving a save
        self.assertEqual(code, 2)
        self.assertIn("story-locked", text)
        f = self.export()
        d = json.load(open(f))                                             # a bank file naming Seraphina: listing AND record
        struct.pack_into("<I", rec := bytearray(bytes.fromhex(d["units"][0]["record"])), savegame.U_CLASS, 40)
        d["units"][0].update({"class": 40, "record": rec.hex()})
        open(f, "w").write(json.dumps(d))
        before = open(self.b, "rb").read()
        code, text = run("import", f, self.b)                              # entering a save
        self.assertEqual(code, 2)
        self.assertIn("story-locked", text)
        self.assertEqual(open(self.b, "rb").read(), before)

    def test_game_dismiss_rule(self):
        import unit_bank as B
        v = {40: "Seraphina", 510: "Laharl", 940: "X", 2460: "Y", 150: "Dummy"}
        self.assertTrue(B.story_locked(40, v))
        self.assertTrue(B.story_locked(2460, v))
        self.assertIsNone(B.story_locked(510, v))      # DLC character: the game lists it in Dismiss
        self.assertIsNone(B.story_locked(940, v))
        self.assertIsNone(B.story_locked(1500, v))
        self.assertEqual(len(B.DISMISSABLE), 36)

    def test_refuses_reserve_unit_and_live_folder(self):
        r = write_save(os.path.join(self.d, "r.sav"), army=0, reserve=1, uid=3,
                       slots=[(127, dict(name="Guest", cls=150, serial=3))])
        code, text = run("export", r, "127", self.bank)
        self.assertEqual(code, 2)
        self.assertIn("reserve", text)
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self.d
        try:
            live = os.path.join(savegame.save_root(), "1", "SaveData", "Save_001.sav")
            code, text = run("export", live, "0", self.bank)
        finally:
            if old is None:
                del os.environ["APPDATA"]
            else:
                os.environ["APPDATA"] = old
        self.assertEqual(code, 2)
        self.assertIn("live save folder", text)


if __name__ == "__main__":
    unittest.main()
