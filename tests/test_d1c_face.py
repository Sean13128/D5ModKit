"""D1CFACE1: source face lookup (start.dat[73] by sprite id). Needs the original Switch copy; skipped without it."""
import unittest

from d5lib.importers import d1c_art


def _source():
    try:
        src = d1c_art.source()
        src.face_ids()
        return src
    except Exception:  # noqa: BLE001 - no game copy on this machine
        return None


@unittest.skipIf(_source() is None, 'original D1C Switch copy not available')
class SourceFace(unittest.TestCase):
    def test_leads_and_palette_variants(self):
        ids = _source().face_ids()
        self.assertEqual([ids[i] for i in (1, 2, 3, 4, 5)], [0, 1, 2, 3, 4])    # sprite id -> face index
        for sid in (1010, 1011, 1015, 2611, 2615, 1056, 2016):
            self.assertIn(sid, ids)

    def test_unique_key_is_sprite_plus_palette(self):
        self.assertEqual(d1c_art.source_face_id(3160), 1165)     # Vesuvius: body 1160, palette 5
        self.assertEqual(d1c_art.source_face_id(2905), 2112)     # Dratti: body 2110, palette 2
        self.assertEqual(d1c_art.source_face_id(2611), 2611)     # Prism Blue

    def test_class_colour_and_hold(self):
        self.assertEqual(d1c_art.source_face_id(1140, 3), 1143)
        for held in (3060, 2410, 3150, 3050):
            self.assertIsNone(d1c_art.source_face_id(held))      # held back, old crop kept
        sid, img = d1c_art.source_face_picture(1140, 0)                       # default: the installed opaque face
        self.assertEqual((sid, img.size, img.mode), (1140, (204, 204), 'RGB'))
        sid, img = d1c_art.source_face_picture(1140, 0, cutout=True)          # opt-in FACEFIX1 cut-out
        self.assertEqual((sid, img.size, img.mode), (1140, (204, 204), 'RGBA'))
        self.assertEqual(img.getpixel((0, 0))[3], 0)                          # background is transparent
        self.assertEqual(d1c_art.source_face_picture(2080, 6), (2086, None))   # no 7th face


class OpaqueFace(unittest.TestCase):
    def test_opaque_face_is_rgb_on_white(self):
        from PIL import Image
        im = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        im.paste((10, 20, 30, 255), (16, 16, 48, 48))
        out = d1c_art.opaque_face(im, 32)
        self.assertEqual((out.mode, out.size), ('RGB', (32, 32)))
        self.assertEqual(out.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(out.getpixel((16, 16)), (10, 20, 30))


class CutOut(unittest.TestCase):
    def test_flood_fill_keeps_inner_white(self):
        from PIL import Image, ImageDraw
        im = Image.new('RGBA', (64, 64), (255, 255, 255, 255))
        d = ImageDraw.Draw(im)
        d.ellipse((16, 8, 48, 56), fill=(60, 60, 60, 255))
        d.ellipse((26, 20, 38, 32), fill=(255, 255, 255, 255))                # enclosed white (an eye)
        out, st = d1c_art.cut_out_face(im, 32)
        self.assertEqual((out.mode, out.size), ('RGBA', (32, 32)))
        self.assertEqual(out.getpixel((0, 0))[3], 0)
        self.assertEqual(out.getpixel((16, 12))[3], 255)                      # the eye survived
        self.assertGreater(st['scale'], 0.5)


if __name__ == '__main__':
    unittest.main()
