"""OUTFITOWN1: an outfit may keep its own evilities, stats, aptitudes, weapon mastery ... (`outfits.json` `own_fields`).

Offline, synthetic rows only.  Default (no declaration) stays today's behaviour: the outfit row follows its character.
"""
import tempfile
import unittest
from pathlib import Path

from d5lib import database, dbpatch, modsys, outfits


class Row(dict):
    def set(self, key, value):
        self[key] = value


def char_row(cid, **kw):
    r = {f: 0 for g in outfits.OWN_GROUPS.values() for f in g[1]}
    r.update(id=cid, sprite_id=cid, color_id=cid, body_type=0, voice_id=0, evility_count=0, name_EN=f"row{cid}",
             learn1_skill=0)
    r.update(kw)
    return Row(r)


def rows():
    base = char_row(10, base_HP=50, apt_HP=110, mastery_sword=20, mastery_gun=5, evility1=101, evility2=102,
                    evility_count=2, MOV=5, res_fire=10, learn1_skill=7)
    a = char_row(470, sprite_id=14600, color_id=470)
    b = char_row(480, sprite_id=14610, color_id=480)
    return {10: base, 470: a, 480: b}


class FollowTests(unittest.TestCase):
    def test_no_declaration_follows_the_character(self):
        r = rows()
        outfits._follow_base(r, [[10, 470], [10, 480]])
        for slot in (470, 480):
            self.assertEqual((r[slot]["base_HP"], r[slot]["mastery_sword"], r[slot]["evility1"],
                              r[slot]["evility_count"]), (50, 20, 101, 2))
        self.assertEqual(r[470]["sprite_id"], 14600)

    def test_declared_groups_keep_their_values_and_the_rest_follows(self):
        r = rows()
        own = {470: {"weapon_mastery": {"mastery_sword": 1, "mastery_gun": 25},
                     "evilities": {"evility1": 0, "evility2": 0, "evility3": 333, "evility4": 0}}}
        outfits._follow_base(r, [[10, 470], [10, 480]], (), own)
        a, b = r[470], r[480]
        self.assertEqual((a["mastery_sword"], a["mastery_gun"]), (1, 25))
        self.assertEqual([a[f] for f in dbpatch.EVILITIES], [333, 0, 0, 0])      # packed to the front
        self.assertEqual(a["evility_count"], 1)
        self.assertEqual((a["base_HP"], a["apt_HP"], a["MOV"], a["res_fire"], a["learn1_skill"]), (50, 110, 5, 10, 7))
        self.assertEqual((b["mastery_sword"], b["evility1"], b["evility_count"]), (20, 101, 2))   # other outfit follows

    def test_a_group_given_partially_keeps_only_those_fields(self):
        r = rows()
        outfits._follow_base(r, [[10, 470]], (), {470: {"base_stats": {"base_HP": 99}}})
        self.assertEqual((r[470]["base_HP"], r[470]["base_ATK"]), (99, 0))

    def test_every_group_field_exists_in_char_dat(self):
        names = {f.name for f in database.get_schema("char.dat").fields}
        for group, (_label, fields) in outfits.OWN_GROUPS.items():
            self.assertTrue(set(fields) <= names, group)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="outfitown1-")
        self.addCleanup(self.tmp.cleanup)
        self.mod = modsys.Mod(str(Path(self.tmp.name) / "pack"))
        outfits.save(self.mod, [[10, 470], [10, 480]])

    def test_set_load_clean_and_clear(self):
        g = outfits.set_own_fields(self.mod, 470, {"aptitudes": {"apt_HP": 120, "bogus": 1}, "nope": {"x": 1},
                                                   "movement": {"MOV": "6"}})
        self.assertEqual(g, {"aptitudes": {"apt_HP": 120}, "movement": {"MOV": 6}})
        self.assertEqual(outfits.load_own_fields(self.mod), {470: g})
        outfits.set_own_fields(self.mod, 470, {})
        self.assertEqual(outfits.load_own_fields(self.mod), {})
        self.assertNotIn("own_fields", self.mod.load_patch("outfits", "outfits.json"))

    def test_only_the_mods_own_outfits(self):
        with self.assertRaises(ValueError):
            outfits.set_own_fields(self.mod, 999, {"movement": {"MOV": 1}})

    def test_an_editor_save_keeps_it_and_a_removed_outfit_drops_it(self):
        outfits.set_own_fields(self.mod, 480, {"movement": {"MOV": 7}})
        outfits.save(self.mod, outfits.load(self.mod))
        self.assertEqual(outfits.load_own_fields(self.mod), {480: {"movement": {"MOV": 7}}})
        outfits.save(self.mod, [[10, 470]])
        self.assertEqual(outfits.load_own_fields(self.mod), {})

    def test_no_declaration_writes_no_key(self):
        self.assertNotIn("own_fields", self.mod.load_patch("outfits", "outfits.json"))


if __name__ == "__main__":
    unittest.main()


class DialogTests(unittest.TestCase):
    """The Outfits page dialog: ticked groups are saved with their values, unticked ones follow."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="outfitown1-ui-")
        self.addCleanup(self.tmp.cleanup)
        self.mod = modsys.Mod(str(Path(self.tmp.name) / "pack"))
        outfits.save(self.mod, [[10, 470]])
        from types import SimpleNamespace
        self.svc = SimpleNamespace(table=lambda m: SimpleNamespace(rows=list(rows().values())),
                                   ref_tooltips=lambda m: {})

    def dialog(self):
        from unittest.mock import patch
        from d5gui import outfitown
        with patch.object(outfitown, "table_names", lambda svc, m: {0: "0: (none)", 101: "101: A", 333: "333: B"}):
            return outfitown.OwnFieldsDialog(self.svc, self.mod, 10, 470, "Hero", "Swimsuit")

    def test_untouched_dialog_saves_nothing(self):
        d = self.dialog()
        self.assertEqual(d.save(), {})
        self.assertEqual(outfits.load_own_fields(self.mod), {})

    def test_ticked_groups_start_from_the_character_and_save(self):
        d = self.dialog()
        d.groups["weapon_mastery"].setChecked(True)
        gun = d.widgets["mastery_gun"][1]
        gun.setCurrentIndex(gun.findData(25))                   # S
        d.groups["evilities"].setChecked(True)
        d.widgets["evility2"][1].set_value(333)
        kept = d.save()
        self.assertEqual(kept["weapon_mastery"]["mastery_sword"], 20)      # the character's value, untouched
        self.assertEqual(kept["weapon_mastery"]["mastery_gun"], 25)
        self.assertEqual(kept["evilities"], {"evility1": 101, "evility2": 333, "evility3": 0, "evility4": 0})
        self.assertEqual(set(kept), {"weapon_mastery", "evilities"})
        d2 = self.dialog()                                                  # reopened: the saved values
        self.assertTrue(d2.groups["evilities"].isChecked())
        self.assertFalse(d2.groups["base_stats"].isChecked())
        self.assertEqual(d2.widgets["evility2"][1].value(), 333)
        from d5gui import outfitown
        self.assertEqual(outfitown.summary(self.mod, 470), "own evilities, own weapon mastery")
