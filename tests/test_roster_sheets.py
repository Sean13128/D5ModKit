"""SHEET1: roster_sheets checks can fail (negative control) and unknown is never PASS."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import roster_sheets as rs  # noqa: E402

GAME_OK = rs.GAME.is_dir() and (rs.PROJECT / "Reports/tracker/items_compact.csv").is_file()


class Logic(unittest.TestCase):
    def test_worst_never_passes_unknown(self):
        self.assertEqual(rs.worst([rs.PASS, rs.NC]), rs.NC)
        self.assertEqual(rs.worst([rs.PASS, rs.NC, rs.FAIL]), rs.FAIL)
        self.assertEqual(rs.worst([]), rs.NC)


@unittest.skipUnless(GAME_OK, "needs the installed game and the tracker roster")
class Negative(unittest.TestCase):
    def test_removed_motion_fails_and_control_passes(self):
        ctx = rs.Ctx()
        ent = next(e for e in rs.roster() if e["pack"] == "D4_Class_2110")      # Roc
        good, _, _ = rs.unit_frames(ctx, ent)
        self.assertEqual(good["checks"]["pose exists"]["status"], rs.PASS)
        orig = ctx.bank

        def broken(pack, n):                                                     # scratch copy: hurt 1061/1067 deleted
            a, src = orig(pack, n)
            if a is not None:
                import copy
                a = copy.deepcopy(a)
                a.blocks[0].animations = [x for x in a.blocks[0].animations if x.id not in (1061, 1067)]
            return a, src
        ctx.bank = broken
        bad, _, _ = rs.unit_frames(ctx, ent)
        self.assertEqual(bad["checks"]["pose exists"]["status"], rs.FAIL)
        self.assertEqual(sorted(p["id"] for p in bad["poses"] if p["checks"]["exists"] == rs.FAIL), [1061, 1067])


if __name__ == "__main__":
    unittest.main()
