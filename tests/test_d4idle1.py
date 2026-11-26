"""D4IDLE1: the three D4 motion fixes, measured on the original D4 data (skipped when the game copy is absent):
the humanoid idle stub keeps D4's placement, Death's scythe shaft survives the duplicate-part rule, and the options are
recorded and selectable (old path)."""
import copy
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

import d4_motion_audit as A  # noqa: E402
from d5lib import anm, importcore, ownanim  # noqa: E402

HAVE = A.SOURCE_ROOT.is_dir()


def worst(f, view, aid, spal=0):
    w = (0.0, 0)
    for t in sorted(set(A.times(view, aid)) | set(A.times(f, aid))):
        s, p = A.picture(view, aid, t, spal), A.picture(f, aid, t, 0)
        d = A.diff_pct(p, s)
        ft = int(A.bbox(p)[3] - A.bbox(s)[3]) if p is not None and s is not None else 0
        w = max(w, (d, ft), key=lambda x: (x[0], abs(x[1])))
    return w


class Options(unittest.TestCase):
    def test_options_are_recorded(self):
        for k in ("d4_stub_xform", "d4_death_game_view", "d4_source_tracks"):
            self.assertIn(k, importcore.RECORDED_OPTIONS["d4"])

    def test_old_path_is_selectable_on_the_command_line(self):
        import import_game  # noqa: F401  (tools/ is on the path)
        src = (KIT / "tools/import_game.py").read_text()
        for flag in ("--no-d4-stub-xform", "--no-d4-death-game-view", "--no-d4-source-tracks"):
            self.assertIn(flag, src)


@unittest.skipUnless(HAVE, "original Disgaea 4 Complete+ copy not present")
class IdleStub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import animall2_convert, pt1030_bankfix
        from tools.animall2_tracks import build as human_merge
        cls.src = A.Source()
        cls.fix_bank = staticmethod(pt1030_bankfix.fix_bank)
        cls.convert = animall2_convert
        row = cls.src.char(360)                                   # Asuka, humanoid on D4's shared block
        cls.body = cls.src.anm(int(row["sprite"]))
        cls.info = dict(body=int(row["sprite"]), humanoid=True)
        cls.view = A.source_view(cls.src, cls.info)
        cls.merged = human_merge(cls.body, cls.src.anm(1), bank_id=int(row["sprite"]))

    def test_d4_stub_is_kept_and_draws_like_d4(self):
        fixed, _ = self.fix_bank(self.merged.to_bytes(), True, False, "D4_Unique_360", "D4_", 2)
        view = A.disabled(fixed)
        for aid in (1001, 1007):
            d, ft = worst(view, self.view, aid)
            self.assertLessEqual(d, 1.0, aid)
            self.assertEqual(ft, 0, aid)

    def test_old_path_draws_the_idle_9px_low(self):
        """negative control: the ANIMALL2 re-root + PT1030 rebuild (xform 0) is what the audit must catch"""
        merged = anm.parse(self.merged.to_bytes())
        self.assertTrue(self.convert.reroot_wheel(merged.blocks[0], []))
        fixed, _ = self.fix_bank(merged.to_bytes(), True, False, "D4_Unique_360", "D4_", 2)
        d, ft = worst(A.disabled(fixed), self.view, 1001)
        self.assertEqual(ft, 9)

    def test_stub_stays_zero_length_and_nests_the_body_idle(self):
        fixed, _ = self.fix_bank(self.merged.to_bytes(), True, False, "D4_Unique_360", "D4_", 2)
        b = fixed.blocks[0]
        shape = ownanim.wheel_stub_shape(b, 1001, 6001)
        self.assertTrue(shape["native"], shape)                   # <= 2 keys, no picture, names 6001
        self.assertEqual(anm.render_root_problems(b), [])


@unittest.skipUnless(HAVE, "original Disgaea 4 Complete+ copy not present")
class DeathShaft(unittest.TestCase):
    def test_composite_rule_keeps_the_hands_strip(self):
        from tools.animall2_tracks import build_monster
        from tools import pt1030_bankfix
        src = A.Source()
        body = src.anm(int(src.char(2120)["sprite"]))
        merged = build_monster(body, bank_id=int(src.char(2120)["sprite"]))
        fixed, _ = pt1030_bankfix.fix_bank(merged.to_bytes(), True, False, "D4_Class_2120", "D4_", 2)
        old = copy.deepcopy(fixed)
        self.assertTrue(ownanim.duplicate_items(old, game=True), "the geometric rule alone blanks the strip")
        self.assertEqual(ownanim.duplicate_items(fixed, game=True, composite_tol=0.002), [])
        d, _ = worst(fixed, body, 1001)
        self.assertEqual(d, 0.0)
        d_old, _ = worst(old, body, 1001)
        self.assertGreater(d_old, 1.0, "negative control: the blanked strip must show in the audit's measure")


if __name__ == "__main__":
    unittest.main()
