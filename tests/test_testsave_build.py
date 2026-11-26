"""TESTSAVE1: the test-save builder's pure parts, plus one game-code creation when local copies exist."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import testsave_build as T  # noqa: E402

SCRATCH = os.environ.get("TESTSAVE1_SCRATCH", "/Volumes/Data/ai-tmp/claude/TESTSAVE1-20261110-1914")


class PureTest(unittest.TestCase):
    def test_fields(self):
        self.assertEqual(T.field_of(0x3060), "serial")
        self.assertEqual(T.field_of(0x2E04), "class id")
        self.assertEqual(T.field_of(0x10 + 600 * 2 + 296), "equipment (5 items)")
        self.assertEqual(T.diff_fields(b"\0" * 0x4750, b"\0" * 0x4750), {})

    def test_plan(self):
        scope = [dict(game=g, pack=f"{g}_{i}") for g, n in (("D4", 3), ("D1C", 2), ("DD2", 1), ("DRPG", 5))
                 for i in range(n)]
        p = T.plan(scope)
        self.assertEqual([len(p[k]) for k in "ABC"], [6, 3, 2])
        self.assertFalse({1, 2, 4} & set(T.SLOT_PLAN.values()))


@unittest.skipUnless(os.path.exists(os.path.join(SCRATCH, "installed", "disgaea5.exe")), "local copies absent")
class GameCodeTest(unittest.TestCase):
    def test_create_matches_the_game_record_fields(self):
        from d5lib import savegame
        cr = T.Creator(os.path.join(SCRATCH, "installed", "disgaea5.exe"),
                       os.path.join(SCRATCH, "installed", "Database_0.dat"))
        sv = savegame.Save(os.path.join(SCRATCH, "src", "Save_001.sav"))
        cr.load(sv.state)
        slot = cr.create(10260)                              # D4 Pringer X: kit anm hook gives 643, not 640
        st = cr.state()
        u = savegame.Unit(sv, 0)
        sv.state[:] = st
        u = savegame.Unit(sv, slot)
        self.assertEqual((u.cls, u.level, u.slot, sv.army_count), (10260, 1, 58, 59))
        self.assertEqual(int.from_bytes(st[u.base + 0x2E36:u.base + 0x2E38], "little"), 643)
        self.assertEqual(u.serial, 12034)                     # counter 12033 pre-incremented, as the game does

    def test_level_option_grants_level_gated_skills(self):
        """--level: creation at a high level carries the level in the record and the skills recalc grants by level"""
        from d5lib import savegame
        cr = T.Creator(os.path.join(SCRATCH, "installed", "disgaea5.exe"),
                       os.path.join(SCRATCH, "installed", "Database_0.dat"))
        sv = savegame.Save(os.path.join(SCRATCH, "src", "Save_001.sav"))
        seen = {}
        for level in (1, 9999):
            cr.load(sv.state)
            slot = cr.create(102, level)                     # DRPG Zed: skills at higher level only
            sv.state[:] = cr.state()
            u = savegame.Unit(sv, slot)
            self.assertEqual(u.level, level)
            seen[level] = T.skill_ids(sv.state, u.base)
            self.assertEqual(T.check(sv, [dict(slot=slot, cls=102)], level), [])
            self.assertTrue(T.check(sv, [dict(slot=slot, cls=102)], level + 1))   # wrong level is reported
        self.assertTrue(set(seen[1]) <= set(seen[9999]))
        self.assertGreater(len(seen[9999]), 0)


if __name__ == "__main__":
    unittest.main()
