"""RECRUITPAGE1: the Recruiter list page's model (d5lib/recruitpage.py) and one offscreen page smoke test.
Synthetic mods only: no game data, no install, no save."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from d5lib import recruitpage as R, wishrecruit as W   # noqa: E402


class FakeMod:
    """the three Mod calls the model uses, over a temp folder (same file layout as d5lib.modsys.Mod)"""
    def __init__(self, d, name="m"):
        self.d, self.name, self.id = d, name, name

    def _p(self, h, n):
        return os.path.join(self.d, h, n)

    def load_patch(self, h, n, default=None):
        p = self._p(h, n)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default

    def save_patch(self, h, n, obj):
        p = self._p(h, n)
        if obj in (None, {}, []):
            if os.path.exists(p):
                os.remove(p)
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(obj, open(p, "w", encoding="utf-8"), indent=1)


CHARS = {20300: "Stella", 3001: "Ann", 3002: "Bo", 3003: "Cy"}


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mod = FakeMod(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_next_id_skips_taken_and_own(self):
        b = [R.Bill(2000, "a"), R.Bill(2001, "b")]
        self.assertEqual(R.next_bill_id(b, {2002, 5}), 2003)
        self.assertEqual(R.next_bill_id([], ()), 2000)

    def test_save_load_roundtrip_single_and_pack(self):
        bills = []
        R.new_bill(bills, "Recruit Stella", [R.Member(20300, 10)], req_flag=399, text="Stella joins")
        R.new_bill(bills, "Trio", [R.Member(3001, 20), R.Member(3002, 30), R.Member(3003, 40, True)], mana_cost=500)
        r = R.save_bills(self.mod, bills, taken={1, 2, 1048}, characters=CHARS)
        self.assertEqual(r, {"bills": 2, "removed": []})
        rec = self.mod.load_patch("wishes", "recruit_wishes.json")["recruits"]
        self.assertEqual(rec["2000"], {"character": 20300, "level": 10})           # one member = plain object
        self.assertEqual(len(rec["2001"]), 3)
        rows = self.mod.load_patch("db", "WishDataBase.dat.json")
        self.assertEqual(rows["table"], "WishDataBase.dat")
        self.assertEqual([x["id"] for x in rows["added"]], [2000, 2001])
        self.assertEqual((rows["added"][0]["req_flag1"], rows["added"][1]["mana_cost"]), (399, 500))
        self.assertEqual(rows["added"][0]["desc_FR"], "Stella joins")
        back = R.load_bills(self.mod)
        self.assertEqual([(b.id, b.name, b.req_flag, len(b.members)) for b in back],
                         [(2000, "Recruit Stella", 399, 1), (2001, "Trio", 0, 3)])
        self.assertTrue(back[1].members[2].duplicates)
        # the kit's own reader accepts what the page wrote
        self.assertEqual(len(W.normalise(rec)), 4)

    def test_other_rows_and_entries_survive(self):
        self.mod.save_patch("db", "WishDataBase.dat.json", {"table": "WishDataBase.dat", "rows": {"3": {"mana_cost": 9}},
                            "added": [{"id": 2500, "name_EN": "someone else's"}]})
        self.mod.save_patch("wishes", "recruit_wishes.json", {"recruits": {"2500": {"character": 3001}}})
        # 2500 is in the recruit file, so the page owns it and shows it; remove it and a foreign row would stay
        self.assertEqual([b.id for b in R.load_bills(self.mod)], [2500])
        self.mod.save_patch("db", "WishDataBase.dat.json", {"table": "WishDataBase.dat", "rows": {"3": {"mana_cost": 9}},
                            "added": [{"id": 2500, "name_EN": "x"}, {"id": 2600, "name_EN": "foreign"}]})
        bills = R.load_bills(self.mod)
        R.new_bill(bills, "New", [R.Member(3002)])
        R.save_bills(self.mod, bills, characters=CHARS)
        d = self.mod.load_patch("db", "WishDataBase.dat.json")
        self.assertEqual(d["rows"], {"3": {"mana_cost": 9}})
        self.assertEqual(sorted(r["id"] for r in d["added"]), [2000, 2500, 2600])

    def test_remove_bill_removes_row_and_entry_only_for_managed(self):
        bills = []
        R.new_bill(bills, "a", [R.Member(3001)])
        R.new_bill(bills, "b", [R.Member(3002)])
        R.save_bills(self.mod, bills, characters=CHARS)
        r = R.save_bills(self.mod, bills[:1], characters=CHARS)
        self.assertEqual(r["removed"], [2001])
        self.assertEqual(list(self.mod.load_patch("wishes", "recruit_wishes.json")["recruits"]), ["2000"])
        self.assertEqual([x["id"] for x in self.mod.load_patch("db", "WishDataBase.dat.json")["added"]], [2000])
        R.save_bills(self.mod, [], characters=CHARS)                                 # last one: both files go
        self.assertFalse(os.path.exists(self.mod._p("wishes", "recruit_wishes.json")))
        self.assertFalse(os.path.exists(self.mod._p("db", "WishDataBase.dat.json")))

    def test_edit_keeps_extra_row_fields(self):
        self.mod.save_patch("db", "WishDataBase.dat.json", {"table": "WishDataBase.dat", "added": [
            {"id": 2000, "name_EN": "A", "block_flag1": 77, "set_flag1": 77, "req_flag1": 5}]})
        self.mod.save_patch("wishes", "recruit_wishes.json", {"recruits": {"2000": {"character": 3001}}})
        b = R.load_bills(self.mod)
        self.assertEqual((b[0].req_flag, b[0].extra), (5, {"block_flag1": 77, "set_flag1": 77}))
        b[0].name = "Renamed"
        R.save_bills(self.mod, b, characters=CHARS)
        row = self.mod.load_patch("db", "WishDataBase.dat.json")["added"][0]
        self.assertEqual((row["name_EN"], row["block_flag1"], row["set_flag1"], row["req_flag1"]),
                         ("Renamed", 77, 77, 5))

    def test_refusals_write_nothing(self):
        cases = [
            (R.Bill(1048, "x", members=[R.Member(3001)]), "bill ids must be 2000"),
            (R.Bill(2000, "x", members=[R.Member(3001)]), "already a WishDataBase row"),
            (R.Bill(2001, "x", members=[]), "lists no character"),
            (R.Bill(2001, "  ", members=[R.Member(3001)]), "needs a name"),
            (R.Bill(2001, "x", members=[R.Member(3001, 0)]), "level 0"),
            (R.Bill(2001, "x", members=[R.Member(3001), R.Member(3001)]), "listed twice"),
            (R.Bill(2001, "x", members=[R.Member(999)]), "no character 999"),
            (R.Bill(2001, "x", members=[R.Member(3001)] * 1 + [R.Member(3002, 1)] * 0, mana_cost=-1), "mana_cost"),
        ]
        for bill, msg in cases:
            with self.assertRaisesRegex(ValueError, msg):
                R.save_bills(self.mod, [bill], taken={2000}, characters=CHARS)
        with self.assertRaisesRegex(ValueError, "used twice"):
            R.save_bills(self.mod, [R.Bill(2002, "a", members=[R.Member(3001)]),
                                    R.Bill(2002, "b", members=[R.Member(3002)])], characters=CHARS)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_pack_of_129_refused(self):
        b = R.Bill(2000, "big", members=[R.Member(i + 1) for i in range(129)])
        with self.assertRaisesRegex(ValueError, "exceeds the roster"):
            R.save_bills(self.mod, [b])

    def test_room_mirrors_the_hook_rule(self):
        b = R.Bill(2000, "t", members=[R.Member(1), R.Member(2), R.Member(3, 1, True)])
        self.assertEqual(R.room(b, [], 125), (True, ""))          # 125 + 3 = 128 fits
        self.assertFalse(R.room(b, [], 126)[0])                    # 129 doesn't
        self.assertIn("already in the army", R.room(b, [2], 10)[1])
        self.assertTrue(R.room(b, [3], 10)[0])                     # member 3 allows copies

    def test_output_matches_what_the_installer_reads(self):
        bills = [R.single(20300, "Stella", 10)]
        bills[0].id = 2000
        R.save_bills(self.mod, bills, characters=CHARS)
        mod = SimpleNamespace(load_patch=self.mod.load_patch)
        self.assertEqual(W.load(mod)["recruits"], {"2000": {"character": 20300, "level": 10}})
        acc = {}
        W.merge(acc, W.load(mod)["recruits"])
        self.assertEqual(W.flatten(acc), [(2000, 20300, 10, 0)])


class PageSmoke(unittest.TestCase):
    def test_page_builds_and_saves_offscreen(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from d5gui.pages.recruitpage import RecruitPage
        with tempfile.TemporaryDirectory() as d:
            mod = FakeMod(d)
            RecruitPage.characters = lambda self: CHARS
            RecruitPage.taken_ids = lambda self: {1, 2}
            page = RecruitPage(SimpleNamespace(active_mod=mod))
            page.refresh()
            self.assertEqual((page.list.count(), page.pick.count()), (0, 4))
            page.new_bill()
            page.f_name.setText("Recruit Ann")
            page.pick.setCurrentIndex(page.pick.findData(3001))
            page.m_level.setValue(12)
            page.add_member()
            self.assertEqual(page.members.count(), 1)
            r = page.save()
            self.assertEqual(r["bills"], 1)
            self.assertEqual(mod.load_patch("wishes", "recruit_wishes.json")["recruits"],
                             {"2000": {"character": 3001, "level": 12}})
            page.refresh()                                     # comes back from disk
            self.assertEqual(page.list.count(), 1)
            self.assertIn("Recruit Ann", page.list.item(0).text())
            page.remove_member()
            page.members.setCurrentRow(0)
            page.remove_member()
            self.assertIsNone(page.save())                     # a bill with no character is refused, not written
            self.assertIn("lists no character", page.status.text())
            app.processEvents()


STEAM = os.environ.get("D5_CLEAN_GAME", "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)")


@unittest.skipUnless(os.path.isfile(os.path.join(STEAM, "disgaea5.exe")), "clean D5 copy not found (D5_CLEAN_GAME)")
class BuildFromPageOutput(unittest.TestCase):
    """a real Mod folder written by the page's save, built by modsys on the clean game (nothing written to disk)"""

    def test_build_accepts_a_pack_and_a_single(self):
        from d5lib import database, modsys
        from d5lib.gamefs import EXE_FILE, GameFS
        fs = GameFS(STEAM)
        chars = database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat"))
        wish = database.load_table("WishDataBase.dat", fs.read("Database/Database_0.dat/WishDataBase.dat"))
        ids = [r["id"] for r in chars.rows][:40:10]
        names = {r["id"]: r["name_EN"] for r in chars.rows}
        taken = {int(r["id"]) for r in wish.rows}
        with tempfile.TemporaryDirectory() as d:
            folder = os.path.join(d, "RecruitPageMod")
            os.makedirs(folder)
            json.dump({"name": "RecruitPageMod"}, open(os.path.join(folder, "mod.json"), "w"))
            mod = modsys.Mod(folder)
            bills = []
            R.new_bill(bills, "Solo", [R.Member(ids[0], 10)], taken=taken)
            R.new_bill(bills, "Pack", [R.Member(ids[1], 5), R.Member(ids[2], 7), R.Member(ids[3], 9)], taken=taken)
            R.save_bills(mod, bills, taken, names)
            logs = []
            ctx = modsys.build(fs, [mod], log=logs.append)
            exe = ctx.get(EXE_FILE)
            self.assertTrue(W.is_hooked(exe))
            self.assertIn("bill 2000", "\n".join(logs))
            self.assertIn("pack of 3", "\n".join(logs))
            # the bill rows are in the built WishDataBase
            t = database.load_table("WishDataBase.dat", ctx.get("Database/Database_0.dat/WishDataBase.dat"))
            got = {r["id"]: r["name_EN"] for r in t.rows if r["id"] >= 2000}
            self.assertEqual(got, {2000: "Solo", 2001: "Pack"})
            # a character the game lacks is refused by the page before the installer ever sees it
            with self.assertRaisesRegex(ValueError, "no character 99999"):
                R.save_bills(mod, [R.Bill(2002, "bad", members=[R.Member(99999)])], taken, names)


if __name__ == "__main__":
    unittest.main()
