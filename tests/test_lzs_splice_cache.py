import os
import random
import tempfile
import unittest
from unittest.mock import patch

from d5lib import lzs, lzs_compress, lzs_splice


class SpliceCacheTests(unittest.TestCase):
    def _case(self):
        rng = random.Random(803600)
        old = bytes(rng.randrange(16) for _ in range(200_000))
        old_raw = lzs_compress.compress(old, native=False)
        a, b = 90_000, 90_500
        new = old[:a] + bytes(rng.randrange(256) for _ in range(b - a)) + old[b:]
        return old_raw, new, [(0, 0, a), (b, b, len(old) - b)]

    def test_cached_result_is_the_same_file(self):
        old_raw, new, runs = self._case()
        with tempfile.TemporaryDirectory() as d, patch.object(lzs_splice, "CACHE_DIR", d), \
                patch.object(lzs_splice, "CACHE_MIN", 0):
            first = lzs_splice.splice(old_raw, new, runs)
            self.assertEqual(len(os.listdir(d)), 1)
            with patch.object(lzs_splice, "_plan", side_effect=AssertionError("not cached")):
                self.assertEqual(lzs_splice.splice(old_raw, new, runs), first)
        self.assertEqual(lzs.decompress(first, native=False), new)

    def test_damaged_cache_is_ignored(self):
        old_raw, new, runs = self._case()
        with tempfile.TemporaryDirectory() as d, patch.object(lzs_splice, "CACHE_DIR", d), \
                patch.object(lzs_splice, "CACHE_MIN", 0):
            first = lzs_splice.splice(old_raw, new, runs)
            path = os.path.join(d, os.listdir(d)[0])
            with open(path, "r+b") as f:
                f.seek(-1, os.SEEK_END)
                f.write(b"\xff" if f.read(1) != b"\xff" else b"\0")
            self.assertEqual(lzs_splice.splice(old_raw, new, runs), first)

    def test_small_files_are_not_cached(self):
        old_raw, new, runs = self._case()
        with tempfile.TemporaryDirectory() as d, patch.object(lzs_splice, "CACHE_DIR", d):
            lzs_splice.splice(old_raw, new, runs)
            self.assertEqual(os.listdir(d), [])

    def test_unwritable_cache_dir_still_splices(self):
        old_raw, new, runs = self._case()
        with tempfile.TemporaryDirectory() as d:
            blocker = os.path.join(d, "file")
            open(blocker, "w").close()                 # a file where the cache directory should be
            with patch.object(lzs_splice, "CACHE_DIR", os.path.join(blocker, "sub")), \
                    patch.object(lzs_splice, "CACHE_MIN", 0):
                out = lzs_splice.splice(old_raw, new, runs)
        self.assertEqual(lzs.decompress(out, native=False), new)


if __name__ == "__main__":
    unittest.main()
