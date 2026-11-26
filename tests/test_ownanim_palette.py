"""Synthetic RGBA palette regression; no game assets."""
import unittest
import numpy as np
from d5lib.ownanim import _palette


class PaletteTests(unittest.TestCase):
    def test_sparse_visible_colours_survive_large_palette_request(self):
        frame = np.array([[[123, 45, 67, 0], [10, 20, 30, 255],
                           [80, 90, 100, 128], [10, 20, 30, 255]]], dtype=np.uint8)
        pal, indices = _palette([frame], colors=255)
        self.assertEqual(pal.shape, (256, 4))
        self.assertEqual(int(indices[0][0, 0]), 0)
        np.testing.assert_array_equal(pal[0], [0, 0, 0, 0])
        np.testing.assert_array_equal(pal[indices[0]][0, 1:], frame[0, 1:])
        self.assertLessEqual(int(indices[0].max()), 255)

    def test_budget_and_transparent_frame(self):
        frame = np.arange(256 * 4, dtype=np.uint8).reshape(16, 16, 4)
        frame[:, :, 3] = 255
        pal, indices = _palette([frame], colors=7)
        self.assertLessEqual(len(np.unique(indices[0])), 7)
        self.assertTrue(np.all(indices[0] > 0))
        pal, indices = _palette([np.zeros((2, 3, 4), np.uint8)])
        self.assertFalse(indices[0].any())
        self.assertFalse(pal.any())

    def test_invalid_colour_budget(self):
        for count in (0, 256, -1, True, 2.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                _palette([np.zeros((1, 1, 4), np.uint8)], colors=count)


if __name__ == '__main__':
    unittest.main()
