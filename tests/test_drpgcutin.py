"""DRPGCUTIN2: the framing of a cut-in made from a look's own illustration (d5lib/drpgcutin.py)."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from d5lib import drpgcutin


def figure(top=200, width=300, glow=False):
    """640 x 960 transparent illustration: a figure `width` wide from row `top` down (+ optional thin prop above it)"""
    a = np.zeros((960, 640, 4), np.uint8)
    a[top:900, 320 - width // 2:320 + width // 2] = (200, 30, 30, 255)
    if glow:
        a[0:top, 300:340] = (20, 20, 20, 255)          # a thin rod above the head: not the figure's top
    return Image.fromarray(a, "RGBA")


class FramingTests(unittest.TestCase):
    def test_window_is_the_measured_zoom_at_the_figures_top_centred_on_it(self):
        x, y, w, h = drpgcutin.window(figure())
        self.assertEqual((w, h), (round(260 / drpgcutin.ZOOM), round(836 / drpgcutin.ZOOM)))
        self.assertEqual(y, 200)
        self.assertAlmostEqual(x + w / 2, 320, delta=1)

    def test_a_thin_prop_above_the_head_is_not_the_top(self):
        self.assertEqual(drpgcutin.window(figure(glow=True))[1], 200)

    def test_cut_in_is_opaque_260_by_836_over_white(self):
        img = drpgcutin.frame_illustration(figure(width=40))        # narrow figure: the window shows white beside it
        self.assertEqual(img.size, drpgcutin.SIZE)
        a = np.asarray(img)
        self.assertTrue((a[..., 3] == 255).all())
        self.assertTrue((a[5, 5, :3] == 255).all())

    def test_override_window_is_the_table_entry_at_the_pictures_own_resolution(self):
        art = Image.new("RGBA", (1024, 1024), (10, 200, 10, 255))
        for lid, (_, cx, top, h) in drpgcutin.OVERRIDES.items():
            out = drpgcutin.frame_window(art, cx, top, h)
            self.assertEqual(out.size, drpgcutin.SIZE, lid)
            self.assertLessEqual(h, 1024)
        self.assertEqual(drpgcutin.OVERRIDES["60019"][3], 836)       # window as tall as the cut-in: no blow-up

    def test_only_a_file_in_an_own_cutins_folder_is_made_from_an_illustration(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "own-cutins").mkdir()
            (Path(d) / "Cut-Ins").mkdir()
            self.assertTrue(drpgcutin.is_own(Path(d) / "own-cutins" / "426.png"))
            self.assertFalse(drpgcutin.is_own(Path(d) / "Cut-Ins" / "222.png"))


if __name__ == "__main__":
    unittest.main()
