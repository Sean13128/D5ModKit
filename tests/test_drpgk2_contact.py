"""DRPG-K2B: the contact sheet must put every picture inside its own cell.

K2's sheet placed the 256x512 standing picture with cell-sized maths, so it was composited
100 px above its row -- on top of the costume's `stand front` body cell, which then looked
like three Zed figures, while the standing cell itself looked empty.  These tests build the
sheet's geometry directly and fail if any picture can leave its box.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("drpgk2_contact", ROOT / "tools/drpgk2_contact.py")
contact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contact)


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


class ContactSheetLayout(unittest.TestCase):
    def test_tall_standing_picture_gets_its_own_band_below_the_body_rows(self):
        rows = [("base", [(1, None, 0)]), ("costume", [(2, None, 0)])]
        cells = [("standing", Image.new("RGBA", (200, 400)))]  # 256x512 texture, thumbnailed
        width, height, bands = contact.layout(rows, cells)
        self.assertEqual(len(bands), 3)
        body_rows, pictures = bands[:2], bands[2]
        self.assertGreaterEqual(pictures["height"], 400)
        for row in body_rows:
            for box in row["boxes"]:
                for pbox in pictures["boxes"]:
                    self.assertFalse(overlaps(box, pbox), f"{box} overlaps {pbox}")
        self.assertGreaterEqual(height, pictures["y"] + 400)

    def test_place_never_draws_outside_its_box(self):
        sheet = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        img = Image.new("RGBA", (256, 512), (255, 0, 0, 255))
        box = (0, 0, 200, 200)
        contact.place(sheet, img, box)
        alpha = sheet.getchannel("A")
        # everything drawn must be inside the box (the whole sheet here), and the picture scaled down
        self.assertEqual(alpha.getextrema()[1], 255)
        self.assertLessEqual(alpha.getbbox()[3], box[3])

    def test_place_refuses_a_box_it_cannot_fill(self):
        sheet = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        with self.assertRaises(ValueError):
            contact.place(sheet, Image.new("RGBA", (0, 0)), (0, 0, -1, -1))

    def test_rendered_sheet_keeps_rows_apart(self):
        """End-to-end geometry: no non-background pixel of one band may reach another band."""
        rows = [("base", [(1, None, 0)]), ("costume", [(2, None, 0)])]
        cells = [("standing", Image.new("RGBA", (200, 400), (0, 255, 0, 255)))]
        width, height, bands = contact.layout(rows, cells)
        sheet = Image.new("RGBA", (width, height), (24, 24, 28, 255))
        d = ImageDraw.Draw(sheet)
        for band in bands:
            for box in band["boxes"]:
                contact.place(sheet, Image.new("RGBA", (200, 400), (0, 255, 0, 255)), box)
        rgb = sheet.convert("RGB")
        self.assertEqual(rgb.getpixel((width - 2, 2)), (24, 24, 28))
        # the standing picture's band starts below both body bands
        self.assertGreaterEqual(bands[2]["y"], bands[1]["y"] + bands[1]["height"])


if __name__ == "__main__":
    unittest.main()
