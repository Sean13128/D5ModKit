"""outfits._face_file must create the cache folder before writing its pickle (a fresh kit has none)."""
import os
import tempfile
import unittest
from unittest import mock

from d5lib import anm, outfits, sprites


class FaceCacheDirTests(unittest.TestCase):
    def test_first_write_creates_missing_cache_dir(self):
        block = anm.AnmBlock(9017)
        res = anm.AnmFile([block], [], [])
        fs = mock.Mock()
        fs.read.return_value = b""
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "not-yet", "cache")
            with mock.patch.object(sprites, "CACHE_DIR", cache), mock.patch.object(anm, "parse", return_value=res):
                out = outfits._face_file(fs)
            self.assertEqual(out.blocks[0].id, 9017)
            self.assertTrue(os.path.exists(os.path.join(cache, "face_block_9017.pickle")))


if __name__ == "__main__":
    unittest.main()
