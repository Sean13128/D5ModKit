"""BANKGUI1: Character Bank page logic (d5gui/bankview.py) headless on synthetic saves, plus one offscreen smoke test."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from d5gui import bankview  # noqa: E402
from test_unit_bank_cli import INSTALLED, VANILLA, write_save  # noqa: E402


class BankView(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.a = write_save(os.path.join(self.d, "a.sav"), army=3, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7)),
            (2, dict(name="Ghost", cls=77, serial=9))])
        self.bank = os.path.join(self.d, "bank")

    def tearDown(self):
        self.tmp.cleanup()

    def test_cards_and_export_refusal(self):
        cards, _ = bankview.save_cards(self.a, INSTALLED, VANILLA, {190: ("D4", "pack")})
        self.assertEqual([c.name for c in cards], ["Killia", "Keke", "Ghost"])
        self.assertEqual((cards[1].level, cards[1].game, cards[0].game), (7, "D4", "D5"))
        self.assertIn("story-locked", cards[0].refusal)
        self.assertIsNone(cards[1].refusal)

    def test_unresolved_badge_is_question_mark(self):
        self.assertEqual(bankview.badge_for(5, {}, {}), ("?", "class 5 is in no installed mod and not in the unmodded game"))
        self.assertEqual(bankview.badge_for(5, {}, {5: "x"})[0], "D5")
        self.assertEqual(bankview.badge_for(5, {5: ("?", "r")}, {5: "x"}), ("?", "r"))

    def test_badges_from_owning_pack_real_saves(self):
        game = os.environ.get("D5_GAME_DIR", "")                  # opt-in: your installed game + kit test saves
        base = os.environ.get("D5_BANK_TEST_SAVES", "")
        van = bankview.unit_bank.VANILLA_DB or ""
        if not (os.path.isdir(game + "/D5ModKit/mods") and os.path.isfile(base + "/Save_012.sav") and os.path.isfile(van)):
            self.skipTest("set D5_GAME_DIR, D5_BANK_TEST_SAVES and D5_VANILLA_DB to run this")
        badges = bankview.game_badges(game + "/D5ModKit/mods")
        vanilla = bankview.unit_bank.char_names(van)
        got = {}
        for f in ("Save_011.sav", "Save_012.sav"):
            tmp = os.path.join(self.d, f)
            open(tmp, "wb").write(open(os.path.join(base, f), "rb").read())
            got.update({c.name: c.game for c in bankview.save_cards(tmp, {}, vanilla, badges)[0]})
        self.assertEqual([got[n] for n in ("Des X", "Roc (D4)", "Plume", "Dragon", "Aileen", "Laharl")],
                         ["D4", "D4", "DD2", "D1C", "DRPG", "D5"])

    def test_export_import_sentences(self):
        cards, _ = bankview.save_cards(self.a, INSTALLED, VANILLA)
        msg, ok = bankview.do_export(self.a, cards[0], self.bank, VANILLA)
        self.assertFalse(ok)
        self.assertIn("story-locked", msg)
        before = [u.name for u in bankview.savegame.Save(self.a).units()]
        msg, ok = bankview.do_export(self.a, cards[1], self.bank, VANILLA)
        self.assertTrue(ok, msg)
        save = bankview.savegame.Save(self.a)
        self.assertNotIn("Keke", [u.name for u in save.units()])          # Export moves: the unit left the save copy
        self.assertEqual(len(save.units()), len(before) - 1)
        bc = bankview.bank_cards(self.bank, INSTALLED, VANILLA, save)
        self.assertEqual((len(bc), bc[0].name, bc[0].refusal), (1, "Keke", None))
        self.assertTrue(bc[0].details)
        b = write_save(os.path.join(self.d, "b.sav"), army=0, uid=3)
        msg, ok = bankview.do_import(b, bc[0], INSTALLED, VANILLA)
        self.assertTrue(ok, msg)
        self.assertEqual([u.name for u in bankview.savegame.Save(b).units()], ["Keke"])

    def test_import_refusals(self):
        for cls, installed, want in ((9999, INSTALLED, "not installed"), (10, INSTALLED, "story-locked")):
            self.assertIn(want, bankview.import_refusal({"name": "X", "class": cls}, installed, VANILLA))
        full = SimpleNamespace(army_count=100, reserve_count=28)
        self.assertIn("128", bankview.import_refusal({"name": "X", "class": 190}, INSTALLED, VANILLA, full))
        self.assertIsNone(bankview.import_refusal({"name": "X", "class": 190}, INSTALLED, VANILLA,
                                                  SimpleNamespace(army_count=1, reserve_count=0)))

    def test_live_folder_refused(self):
        live = os.path.join(bankview.savegame.save_root(), "1234", "SaveData", "Save_001.sav")
        with self.assertRaises(bankview.unit_bank.Refused):
            bankview.save_cards(live, INSTALLED, VANILLA)
        msg, ok = bankview.do_import(live, SimpleNamespace(path="x", name="U"), INSTALLED, VANILLA)
        self.assertFalse(ok)
        self.assertIn("live save folder", msg)

    def test_page_builds_offscreen(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from d5gui.pages.charbank import CharBankPage
        page = CharBankPage(SimpleNamespace(game_dir=""))   # no game folder: placeholders, no crash
        page.set_paths(self.a, self.bank)
        self.assertEqual(page.left.count(), 3)
        page.left.item(1).setSelected(True)
        page.export_selected()
        self.assertEqual(page.right.count(), 1)
        self.assertIn("Exported Keke", page.status.text())
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
