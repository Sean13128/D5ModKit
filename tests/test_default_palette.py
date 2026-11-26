"""D1CCOLOR1: a unique's source-selected palette becomes default slot 0; synthetic, no game assets."""
import unittest
from types import SimpleNamespace
import numpy as np
from d5lib import anm, sourceimports


def bank(n):
    pals = [SimpleNamespace(data=bytes([k]) * 1024) for k in range(n)]
    return SimpleNamespace(palettes=pals)


class DefaultPaletteTests(unittest.TestCase):
    def test_selected_becomes_default_in_both_groups(self):
        b = bank(20)
        before = [p.data for p in b.palettes]
        self.assertEqual(sourceimports.select_default_palette(b, 3), [(0, 3), (10, 13)])
        after = [p.data for p in b.palettes]
        self.assertEqual((after[0], after[3]), (before[3], before[0]))
        self.assertEqual((after[10], after[13]), (before[13], before[10]))
        self.assertEqual(len(after), 20)
        self.assertEqual(sorted(after), sorted(before))

    def test_single_group_bank(self):
        b = bank(10)
        self.assertEqual(sourceimports.select_default_palette(b, 5), [(0, 5)])

    def test_source_zero_is_untouched(self):
        b = bank(20)
        before = [p.data for p in b.palettes]
        self.assertEqual(sourceimports.select_default_palette(b, 0), [])
        self.assertEqual(before, [p.data for p in b.palettes])


if __name__ == '__main__':
    unittest.main()


def test_dark_flonne_sprite_override():
    from d5lib.importers import d1c
    assert d1c.SPRITE_PALETTE_OVERRIDES[3060] == 2
