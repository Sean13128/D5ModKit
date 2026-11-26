"""d5lib.d4screenart: header checks run anywhere; the real-archive check runs only when D4_GAME_DIR is set."""
import os
import struct
import tempfile
import unittest

from d5lib import d4screenart


class FaceHeaderTests(unittest.TestCase):
    def test_rejects_wrong_magic(self):
        with self.assertRaises(ValueError):
            d4screenart.decode_face(b"X" * 200)

    def test_rejects_bad_envelope(self):
        raw = bytearray(200)
        raw[:8] = b"NMPLTEX1"
        raw[20] = 6
        struct.pack_into("<2I", raw, 24, 4, 4)
        with self.assertRaises(ValueError):
            d4screenart.decode_face(bytes(raw))

    def test_data_dir_missing(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaises(FileNotFoundError):
            d4screenart.data_dir(t)


@unittest.skipUnless(os.environ.get("D4_GAME_DIR"), "set D4_GAME_DIR to a Disgaea 4 Complete+ folder")
class RealArchiveTests(unittest.TestCase):
    def test_one_id(self):
        with tempfile.TemporaryDirectory() as t:
            m = d4screenart.extract(os.environ["D4_GAME_DIR"], t, ids=[70])
            self.assertEqual(m["errors"], {})
            self.assertTrue(os.path.isfile(os.path.join(t, "character_id_00070/face/swf0070.png")))
            self.assertTrue(any(r["file"].endswith("p000_t000_b00_r00001.png") for r in m["cutins"]["70"]))


if __name__ == "__main__":
    unittest.main()


def test_png_uses_the_october_encoder_setting(tmp_path):
    """SOURCEPREP4-D4 acceptance 1: the extractor writes the PNG encoder setting the installed art used."""
    import io
    from PIL import Image
    from d5lib import d4screenart
    image = Image.new('RGBA', (16, 16), (12, 34, 56, 78))
    path = tmp_path / 'face.png'
    d4screenart._png(path, image)
    expected = io.BytesIO()
    image.save(expected, 'PNG', compress_level=1)
    assert path.read_bytes() == expected.getvalue()
