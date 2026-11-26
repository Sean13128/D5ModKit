"""BANKLIVESAVE1: the bank works on a real save (a folder named like the game's save folder, in a temp dir; the real
folder is never touched) after a backup, and not while the game runs; a save elsewhere behaves as before."""
import glob
import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
sys.path.insert(0, HERE)

from d5gui import bankview  # noqa: E402
from d5lib import savegame, unitbank  # noqa: E402
import unit_bank  # noqa: E402
from test_bankfeat1 import NEEDS_LEARNED, TABLE, learned  # noqa: E402
from test_unit_bank_cli import INSTALLED, VANILLA, run, write_save  # noqa: E402


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


class LiveSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        sd = os.path.join(self.d, "AppData", *unit_bank.GAME_SAVE_DIRS, "27885847", "SaveData")
        os.makedirs(sd)
        self.live = write_save(os.path.join(sd, "Save_001.sav"), army=3, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7)),
            (2, dict(name="Other", cls=150, serial=6))])
        self.copy = write_save(os.path.join(self.d, "copy.sav"), army=2, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7))])
        self.kit = os.path.join(self.d, "kit")
        self.bank = os.path.join(self.d, "bank")
        self.orig = open(self.live, "rb").read()
        p = mock.patch.object(unit_bank, "game_running", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def backups(self):
        return glob.glob(os.path.join(self.kit, "state", "save_backups", "*", "*", "SaveData", "*"))

    def cli(self, *a):
        return run(*a, "--kit-dir", self.kit)

    def bank_file(self):
        return os.path.join(self.bank, [f for f in os.listdir(self.bank) if f.endswith(unit_bank.EXT)][0])

    def test_export_and_import_back_up_first(self):
        code, text = self.cli("export", self.live, "Keke", self.bank, "--move", "--live")
        self.assertEqual(code, 0, text)
        self.assertIn("backed up first", text)
        (b,) = self.backups()
        self.assertEqual(open(b, "rb").read(), self.orig)                    # the save as it was
        self.assertNotEqual(open(self.live, "rb").read(), self.orig)
        self.assertEqual(savegame.Save(self.live).army_count, 2)
        after_export = open(self.live, "rb").read()
        code, text = self.cli("import", self.bank_file(), self.live, "--live")
        self.assertEqual(code, 0, text)
        self.assertEqual(sorted(open(b2, "rb").read() for b2 in self.backups()), sorted([self.orig, after_export]))
        s = savegame.Save(self.live)
        self.assertEqual((s.army_count, unitbank.verify(s)), (3, []))

    def test_page_logic_export_and_import(self):
        card = bankview.save_cards(self.live, INSTALLED, VANILLA, live=True)[0][1]
        msg, ok = bankview.do_export(self.live, card, self.bank, VANILLA, live=True, kit_dir=self.kit)
        self.assertTrue(ok, msg)
        self.assertIn("backed up first", msg)
        self.assertIn(os.path.join(self.kit, "state", "save_backups"), msg)
        (b,) = self.backups()
        self.assertEqual(open(b, "rb").read(), self.orig)
        bank = bankview.bank_cards(self.bank, INSTALLED, VANILLA)[0]
        msg, ok = bankview.do_import(self.live, bank, INSTALLED, VANILLA, live=True, kit_dir=self.kit)
        self.assertTrue(ok, msg)
        self.assertIn("backed up first", msg)
        self.assertEqual(len(self.backups()), 2)
        self.assertEqual(unitbank.verify(savegame.Save(self.live)), [])

    def test_page_without_live_still_refuses(self):
        card = bankview.save_cards(self.copy, INSTALLED, VANILLA)[0][1]
        msg, ok = bankview.do_export(self.live, card, self.bank, VANILLA, kit_dir=self.kit)
        self.assertFalse(ok)
        self.assertEqual((open(self.live, "rb").read(), self.backups()), (self.orig, []))

    def test_cli_without_live_refused(self):
        for argv in (("export", self.live, "Keke", self.bank, "--move"), ("export", self.live, "Keke", self.bank)):
            code, text = self.cli(*argv)
            self.assertEqual(code, 2)
            self.assertIn("--live", text)
        self.assertEqual((open(self.live, "rb").read(), self.backups()), (self.orig, []))

    def test_backup_failure_writes_nothing(self):
        open(self.kit, "w").write("a file where the backup folder should go")
        code, text = self.cli("export", self.live, "Keke", self.bank, "--move", "--live")
        self.assertEqual(code, 2)
        self.assertIn("could not make the backup", text)
        self.assertEqual(open(self.live, "rb").read(), self.orig)
        self.assertFalse(os.path.exists(self.bank))

    def test_game_running_refuses_without_backup(self):
        with mock.patch.object(unit_bank, "game_running", return_value=True):
            code, text = self.cli("export", self.live, "Keke", self.bank, "--move", "--live")
        self.assertEqual(code, 2)
        self.assertIn("Disgaea 5 is running", text)
        self.assertEqual((open(self.live, "rb").read(), self.backups()), (self.orig, []))
        self.assertFalse(os.path.exists(self.bank))

    def test_verify_failure_puts_the_backup_back(self):
        real = unitbank.verify
        calls = []

        def verify(save):                     # clean before the write, a problem on the written file
            calls.append(1)
            return real(save) if len(calls) == 1 else ["forced problem"]
        with mock.patch.object(unitbank, "verify", verify):
            code, text = self.cli("export", self.live, "Keke", self.bank, "--move", "--live")
        self.assertEqual(code, 2)
        self.assertIn("backup was put back", text)
        self.assertEqual(len(calls), 2)
        self.assertEqual(open(self.live, "rb").read(), self.orig)
        self.assertEqual(len(self.backups()), 1)

    def test_import_verify_failure_keeps_bank_file_and_save(self):
        self.assertEqual(self.cli("export", self.copy, "Keke", self.bank)[0], 0)
        f = self.bank_file()
        real, n = unitbank.verify, []
        with mock.patch.object(unitbank, "verify", lambda s: n.append(1) or (real(s) if len(n) == 1 else ["forced"])):
            code, text = self.cli("import", f, self.live, "--live", "--move")
        self.assertEqual(code, 2)
        self.assertEqual(open(self.live, "rb").read(), self.orig)
        self.assertTrue(os.path.exists(f))                                    # still in the bank

    def test_save_outside_the_game_folders_no_backup(self):
        code, text = self.cli("export", self.copy, "Keke", self.bank, "--move")
        self.assertEqual(code, 0, text)
        self.assertNotIn("backed up", text)
        self.assertEqual(self.backups(), [])
        self.assertFalse(os.path.exists(self.kit))
        self.assertEqual(self.cli("import", self.bank_file(), self.copy)[0], 0)
        self.assertEqual(self.backups(), [])

    def test_profile_save_is_backed_up(self):
        store = os.path.join(self.kit, "profiles", "MAIN", "saves", "27885847", "SaveData")
        os.makedirs(store)
        prof = write_save(os.path.join(store, "Save_001.sav"), army=2, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5))])
        before = open(prof, "rb").read()
        code, text = self.cli("export", prof, "Keke", self.bank, "--move")      # no --live needed, not the game's folder
        self.assertEqual(code, 0, text)
        (b,) = self.backups()
        self.assertEqual(open(b, "rb").read(), before)

    @NEEDS_LEARNED
    def test_companion_is_in_the_backup(self):
        side = self.live + learned.SIDECAR_SUFFIX
        learned.sidecar_write(side, learned.sidecar_doc(self.live, TABLE, {5: [21000, 21001], 6: [21002]},
                                                        unit_names={5: "Keke", 6: "Other"}))
        old_side = open(side, "rb").read()
        code, text = self.cli("export", self.live, "Keke", self.bank, "--move", "--live")
        self.assertEqual(code, 0, text)
        names = {os.path.basename(b): open(b, "rb").read() for b in self.backups()}
        self.assertEqual(names, {"Save_001.sav": self.orig, "Save_001.sav" + learned.SIDECAR_SUFFIX: old_side})
        self.assertNotEqual(open(side, "rb").read(), old_side)               # the companion was re-bound

    @NEEDS_LEARNED
    def test_failed_write_restores_companion_too(self):
        side = self.live + learned.SIDECAR_SUFFIX
        learned.sidecar_write(side, learned.sidecar_doc(self.live, TABLE, {5: [21000]}, unit_names={5: "Keke"}))
        old_side = open(side, "rb").read()
        real, n = unitbank.verify, []
        with mock.patch.object(unitbank, "verify", lambda s: n.append(1) or (real(s) if len(n) == 1 else ["forced"])):
            code, _ = self.cli("export", self.live, "Keke", self.bank, "--move", "--live")
        self.assertEqual(code, 2)
        self.assertEqual((open(self.live, "rb").read(), open(side, "rb").read()), (self.orig, old_side))


if __name__ == "__main__":
    unittest.main()
