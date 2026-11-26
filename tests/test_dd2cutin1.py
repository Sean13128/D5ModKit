"""DD2CUTIN1: a DD2 cut-in keeps its proportions in the D5 cut-in texture, and the audit gate catches a stretch.

Synthetic pictures only (no game data).  The negative control is the point: the importer used to resize the 125x544
source over the whole 336x1080 texture and nothing noticed.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from d5lib import dd2cutinaudit as audit
from d5lib import imgtools

TEX = (336, 1080)


def picture(size=(125, 544), seed=1):
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 256, size=(size[1], size[0], 4), dtype=np.uint8)
    a[: size[1] // 8, :, 3] = 0                   # a transparent top, like the cut-ins' backgrounds
    return Image.fromarray(a, "RGBA")


class PlacementTests(unittest.TestCase):
    def test_narrow_picture_fits_the_height_and_loses_nothing(self):
        p = imgtools.cutin_placement((125, 544), TEX, "contain")
        x, y, w, h = p["box"]
        self.assertEqual((y, h), (0, 1080))
        self.assertEqual(w, 248)
        self.assertEqual(x, (336 - 248) // 2)
        self.assertAlmostEqual(p["scale_x"], p["scale_y"], delta=0.005)

    def test_stretch_is_the_historical_whole_texture_resize(self):
        p = imgtools.cutin_placement((125, 544), TEX, "stretch")
        self.assertEqual(p["box"], (0, 0, 336, 1080))
        self.assertNotAlmostEqual(p["scale_x"], p["scale_y"], delta=0.3)

    def test_stretch_output_is_byte_identical_to_the_old_resize(self):
        img = picture()
        out, _ = imgtools.fit_cutin(img, TEX, "stretch")
        self.assertEqual(out.tobytes(), img.resize(TEX, Image.Resampling.LANCZOS).tobytes())

    def test_d4_proportions_are_left_as_a_plain_resize(self):
        # D4 cut-in cell 390x1248 against 336x1080: 0.45% apart, so contain mode does not pad it
        p = imgtools.cutin_placement((390, 1248), TEX, "contain")
        self.assertEqual(p["box"], (0, 0, 336, 1080))
        self.assertEqual(p["mode"], "contain-fill")
        img = picture((390, 1248))
        a, _ = imgtools.fit_cutin(img, TEX, "contain")
        b, _ = imgtools.fit_cutin(img, TEX, "stretch")
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_exact_size_is_untouched(self):
        img = picture(TEX)
        a, p = imgtools.fit_cutin(img, TEX, "contain")
        self.assertEqual(a.tobytes(), img.tobytes())

    def test_wide_picture_is_padded_below_not_cropped(self):
        p = imgtools.cutin_placement((672, 540), TEX, "contain")
        self.assertEqual(p["box"][2], 336)
        self.assertLess(p["box"][3], 1080)
        self.assertEqual(p["box"][:2], (0, 0))

    def test_padding_is_transparent(self):
        out, p = imgtools.fit_cutin(picture(), TEX, "contain")
        a = np.asarray(out)
        x, y, w, h = p["box"]
        self.assertEqual(int(a[:, :x, 3].max()), 0)
        self.assertEqual(int(a[:, x + w:, 3].max()), 0)


class AuditTests(unittest.TestCase):
    def fit(self, mode, src=None):
        src = src or picture()
        return imgtools.fit_cutin(src, TEX, mode)[0]

    def test_a_contained_cutin_passes(self):
        src = picture()
        m = audit.measure(self.fit("contain", src), src)
        self.assertTrue(m["ok"], m)
        self.assertLess(m["mean_diff"], 0.5)
        self.assertTrue(m["uniform"] and m["lossless"])
        self.assertEqual(m["box"][2:], [248, 1080])

    def test_negative_control_the_old_stretch_fails(self):
        src = picture()
        m = audit.measure(self.fit("stretch", src), src)
        self.assertFalse(m["ok"])
        self.assertGreater(m["mean_diff"], audit.MAX_MEAN_DIFF)

    def test_a_cropped_cover_fit_fails(self):
        # scale to cover and crop: loses the top and bottom of the source
        src = picture()
        s = TEX[0] / src.width
        big = src.resize((TEX[0], round(src.height * s)), Image.Resampling.LANCZOS).crop((0, 0, TEX[0], TEX[1]))
        self.assertFalse(audit.measure(big, src)["ok"])

    def test_opaque_pixels_outside_the_picture_fail(self):
        src = picture()
        out = self.fit("contain", src)
        a = np.asarray(out).copy()
        a[500, 2] = (255, 0, 0, 255)                       # inside the left margin
        m = audit.measure(Image.fromarray(a, "RGBA"), src)
        self.assertFalse(m["ok"])
        self.assertEqual(m["outside_opaque"], 1)

    def test_a_different_picture_fails(self):
        m = audit.measure(self.fit("contain", picture(seed=2)), picture(seed=1))
        self.assertFalse(m["ok"])

    def test_position_is_found_not_assumed(self):
        src = picture()
        resized = src.resize((248, 1080), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", TEX, (0, 0, 0, 0))
        canvas.paste(resized, (80, 0))                     # right-anchored instead of centred
        m = audit.measure(canvas, src)
        self.assertTrue(m["ok"], m)
        self.assertEqual(m["box"][0], 80)

    def test_class_ranks_must_hold_their_own_strip(self):
        strips = [picture(seed=k) for k in range(6)]
        banks = [(12020 + j, self.fit("contain", strips[0 if j >= 6 else j])) for j in range(10)]
        with mock.patch.object(audit, "pack_banks", return_value=banks):
            ok = audit.audit_pack(Path("DD2_Class_x"), strips)
        self.assertEqual(ok["failed"], [])
        banks_old = [(12020 + j, self.fit("contain", strips[0])) for j in range(10)]     # every rank = rank 0
        with mock.patch.object(audit, "pack_banks", return_value=banks_old):
            bad = audit.audit_pack(Path("DD2_Class_x"), strips)
        self.assertEqual(len(bad["failed"]), 5)            # ranks 1..5

    def test_pack_without_a_cutin_fails(self):
        with mock.patch.object(audit, "pack_banks", return_value=[]):
            self.assertTrue(audit.audit_pack(Path("DD2_Unique_x"), [picture()])["failed"])


if __name__ == "__main__":
    unittest.main()
