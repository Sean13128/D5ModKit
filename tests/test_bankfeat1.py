"""BANKFEAT1: Character Bank features (a) import moves the bank file, (b) learned companion travels, (c) faces."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
sys.path.insert(0, HERE)

from d5lib import savegame  # noqa: E402
import unit_bank  # noqa: E402
from d5gui import bankview  # noqa: E402
from test_unit_bank_cli import INSTALLED, VANILLA, run, write_save  # noqa: E402
try:                                    # optional kit part (learned-evility companion)
    from d5lib import learned
except ImportError:
    learned = None
NEEDS_LEARNED = unittest.skipIf(learned is None, "this kit has no d5lib.learned (the companion is optional)")


class ImportMoves(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = self.tmp.name
        self.a = write_save(os.path.join(d, "a.sav"), army=2, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7))])
        self.b = write_save(os.path.join(d, "b.sav"), army=1, uid=40, slots=[(0, dict(name="Killia", cls=10, serial=1))])
        self.bank = os.path.join(d, "bank")
        unit_bank.export(self.a, 1, self.bank, VANILLA)
        self.f = os.path.join(self.bank, os.listdir(self.bank)[0])

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_copies_by_default_and_moves_with_flag(self):
        self.assertEqual(run("import", self.f, self.b)[0], 0)
        self.assertTrue(os.path.exists(self.f))                              # CLI default unchanged
        c = write_save(os.path.join(self.d, "c.sav"), army=1, uid=40, slots=[(0, dict(name="Killia", cls=10, serial=1))])
        code, text = run("import", self.f, c, "--move")
        self.assertEqual(code, 0, text)
        self.assertFalse(os.path.exists(self.f))
        self.assertTrue(os.path.exists(os.path.join(self.bank, "imported", os.path.basename(self.f))))

    def test_page_import_moves_once_and_list_hides_it(self):
        card = [c for c in bankview.bank_cards(self.bank, INSTALLED, VANILLA)][0]
        msg, ok = bankview.do_import(self.b, card, INSTALLED, VANILLA)
        self.assertTrue(ok, msg)
        self.assertEqual(savegame.Save(self.b).army_count, 2)
        self.assertEqual(bankview.bank_cards(self.bank, INSTALLED, VANILLA), [])      # nothing left to import twice
        msg, ok = bankview.do_import(self.b, card, INSTALLED, VANILLA)                # stale card: file is gone
        self.assertFalse(ok)
        self.assertEqual(savegame.Save(self.b).army_count, 2)

    def test_refused_import_leaves_the_file(self):
        card = bankview.bank_cards(self.bank, INSTALLED, VANILLA)[0]
        msg, ok = bankview.do_import(self.b, card, {10: "Killia"}, VANILLA)           # class not installed
        self.assertFalse(ok)
        self.assertTrue(os.path.exists(self.f))
        self.assertEqual(savegame.Save(self.b).army_count, 1)

    def test_name_clash_in_imported_keeps_both(self):
        os.makedirs(os.path.join(self.bank, "imported"))
        old = os.path.join(self.bank, "imported", os.path.basename(self.f))
        open(old, "w").write("older")
        self.assertEqual(run("import", self.f, self.b, "--move")[0], 0)
        self.assertEqual(open(old).read(), "older")
        self.assertEqual(len(os.listdir(os.path.join(self.bank, "imported"))), 2)


TABLE = list(range(1, 1001)) + [21000, 21001, 21002]      # ids at positions 1000.. need the extension's store


@NEEDS_LEARNED
class Companion(unittest.TestCase):
    """a unit's learned-evility companion entries travel through export and import; the companion stays valid"""

    def setUp(self):
        from d5lib import learned
        self.learned = learned
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = self.tmp.name
        self.a = write_save(os.path.join(d, "a.sav"), army=3, uid=9, slots=[
            (0, dict(name="Killia", cls=10, serial=1)), (1, dict(name="Keke", cls=190, serial=5, level=7)),
            (2, dict(name="Other", cls=150, serial=6))])
        learned.sidecar_write(self.a + learned.SIDECAR_SUFFIX, learned.sidecar_doc(      # the kit's own companion writer
            self.a, TABLE, {5: [21000, 21001], 6: [21002]}, unit_names={5: "Keke", 6: "Other"}))
        self.b = write_save(os.path.join(d, "b.sav"), army=1, uid=40, slots=[(0, dict(name="Killia", cls=10, serial=1))])
        self.bank = os.path.join(d, "bank")

    def tearDown(self):
        self.tmp.cleanup()

    def valid(self, path):
        doc = self.learned.sidecar_read(path + self.learned.SIDECAR_SUFFIX)
        ok, problems, quarantine = self.learned.sidecar_validate(doc, path, TABLE)
        self.assertTrue(ok, problems)
        self.assertEqual(quarantine, [])
        return {s: ids for s, ids in self.learned.sidecar_plan(doc, TABLE)[0].items()}

    def test_move_out_and_into_another_save(self):
        self.assertEqual(self.valid(self.a), {5: [21000, 21001], 6: [21002]})
        unit_bank.export(self.a, 1, self.bank, VANILLA, move=True)
        self.assertEqual(self.valid(self.a), {6: [21002]})                    # left with the unit, still valid for the new bytes
        f = os.path.join(self.bank, os.listdir(self.bank)[0])
        self.assertEqual(unit_bank.read_entry(f)["learned_extra"], [21000, 21001])
        self.assertEqual(run("import", f, self.b)[0], 0)                      # b has no companion, no --db: warned, not carried
        self.assertFalse(os.path.exists(self.b + self.learned.SIDECAR_SUFFIX))
        res, _ = unit_bank.import_(f, self.b, INSTALLED, VANILLA, skill_ids=TABLE,
                                     allow_duplicate=True)                    # again (deliberate copy): now start one
        self.assertEqual(self.valid(self.b), {res["serial"]: [21000, 21001]})
        c = write_save(os.path.join(self.d, "c.sav"), army=1, uid=40, slots=[(0, dict(name="Killia", cls=10, serial=1))])
        self.learned.sidecar_write(c + self.learned.SIDECAR_SUFFIX, self.learned.sidecar_doc(c, TABLE, {1: [21002]}))
        res, _ = unit_bank.import_(f, c, INSTALLED, VANILLA)                  # existing companion: extended, re-bound
        self.assertEqual(self.valid(c), {1: [21002], res["serial"]: [21000, 21001]})

    def test_stale_companion_is_left_alone_and_said(self):
        open(self.b, "ab").close()
        self.learned.sidecar_write(self.b + self.learned.SIDECAR_SUFFIX, self.learned.sidecar_doc(self.b, TABLE, {}))
        unit_bank.export(self.a, 1, self.bank, VANILLA)
        f = os.path.join(self.bank, os.listdir(self.bank)[0])
        s = savegame.Save(self.b); s.state[0x10] ^= 1; s.write()            # companion now stale
        before = open(self.b + self.learned.SIDECAR_SUFFIX).read()
        res, _ = unit_bank.import_(f, self.b, INSTALLED, VANILLA, skill_ids=TABLE)
        self.assertEqual(open(self.b + self.learned.SIDECAR_SUFFIX).read(), before)
        self.assertTrue(any("not carried" in w for w in res["warnings"]))

    def test_old_bank_file_without_the_field_imports(self):
        import json
        unit_bank.export(self.a, 1, self.bank, VANILLA)
        f = os.path.join(self.bank, os.listdir(self.bank)[0])
        doc = json.load(open(f))
        doc["units"][0].pop("learned_extra")
        json.dump(doc, open(f, "w"))
        self.assertEqual(run("import", f, self.b)[0], 0)


class Faces(unittest.TestCase):
    def test_imported_game_face_comes_from_the_installed_resident_pack(self):
        game = os.environ.get("D5_GAME_DIR", "")                  # opt-in: an installed game with the D4 pack
        if not os.path.isdir(game + "/D5ModKit/mods/D4_Unique_170"):
            self.skipTest("set D5_GAME_DIR to an installed game with the D4 pack to run this")
        import copy
        import pickle
        from unittest import mock
        from d5lib import outfits, sprites
        art = bankview.Art(game)
        stale = copy.deepcopy(outfits._face_file(art.fs, fresh=True))     # a cache written from the clean game: no imported faces
        stale.blocks[0].animations = [a for a in stale.blocks[0].animations if a.id < 10900]
        cdir = tempfile.TemporaryDirectory()
        self.addCleanup(cdir.cleanup)
        pickle.dump(stale, open(os.path.join(cdir.name, "face_block_9017.pickle"), "wb"))
        sprites_cache = mock.patch.object(sprites, "CACHE_DIR", cdir.name)
        sprites_cache.start()
        self.addCleanup(sprites_cache.stop)
        art = bankview.Art(game)
        hugo = 10270                                     # D4 Hugo, face anim 10000 + 937 painted into the installed resident
        face = art.resolve(hugo)[1]
        self.assertIsNotNone(face)
        self.assertEqual(face.size, (204, 204))
        self.assertIsNone(outfits.base_face_image(art.fs, art.rows[hugo]["color_id"]))   # the cache path alone cannot
        self.assertIsNotNone(art.resolve(10)[1])         # Killia (D5) still resolves


if __name__ == "__main__":
    unittest.main()
