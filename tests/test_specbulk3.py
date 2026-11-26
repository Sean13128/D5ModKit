"""SPECBULK3: cmd_6630 puts the actor at a place at once (object_warp_to 0x1401707a0 tail-calls object_place; D4
0x1401311b0 does the same with its 6642 handler). The stage simulator modelled it as 'face like another actor', so a
scene that ends with `6630 a, a` (put a moved unit back on its base place) left the unit off its panel in the preview.
Stock scenes are read from the clean game copy at test time (skipped when absent)."""
import os
import unittest

import numpy as np

from d5lib import choreo, script, skills, stage
from d5lib.gamefs import GameFS

GAME = "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)"


def end_cell(tl, actor=choreo.CASTER):
    st = stage.StageSim(tl, stage.Setup()).at(tl.length)
    p = st.actors[actor].pos
    return int(round(p[0] / stage.PANEL)), int(round(p[2] / stage.PANEL))


class Warp(unittest.TestCase):
    def test_warp_back_to_base(self):
        ev = script.Event(1, [script.Ins(0x6642, [1256, 1256, 0, 0, 480, 4, 0]), script.Ins(choreo.WAIT, [10]),
                              script.Ins(0x6630, [1256, 1256]), script.Ins(choreo.WAIT, [2])])
        tl = choreo.simulate({1: ev}, 1)
        self.assertEqual(end_cell(tl), (0, 0))

    def test_warp_to_another_actor(self):
        ev = script.Event(1, [script.Ins(0x6630, [1256, 3600]), script.Ins(choreo.WAIT, [2])])
        self.assertEqual(end_cell(choreo.simulate({1: ev}, 1)), (0, 1))

    @unittest.skipUnless(os.path.isdir(GAME), "clean D5 copy absent")
    def test_stock_scenes_end_on_the_casters_panel(self):
        sc = skills.Scripts.load(GameFS(GAME))
        for eid in (15010300, 15011400, 15011800, 15012300, 15013500, 15013600):
            with self.subTest(eid=eid):
                self.assertTrue(any(i.cid == 0x6630 and i.args == [1256, 1256] for i in sc.ev[eid].code))
                self.assertEqual(end_cell(choreo.simulate(sc.ev, eid)), (0, 0))


if __name__ == "__main__":
    unittest.main()
