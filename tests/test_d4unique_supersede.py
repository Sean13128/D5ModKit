"""Unique importer supersession: an earlier D4 generation claims nothing.

Synthetic Mod stand-ins only - no game files, no exe, no install.
"""
import unittest
from types import SimpleNamespace

from d5lib import d4unique


def mods(*ids):
    return [SimpleNamespace(id=i) for i in ids]


class SupersedeTests(unittest.TestCase):
    def test_only_the_named_prefix_is_superseded(self):
        all_mods = mods('D4_Unique_180', 'D4_Unique_470', 'D4_Class_1080', 'DLCSample')
        self.assertEqual(d4unique.superseded_mod_ids(all_mods, ('D4_Unique_',)),
                         ['D4_Unique_180', 'D4_Unique_470'])

    def test_shared_prefix_is_not_a_match(self):
        self.assertEqual(d4unique.superseded_mod_ids(mods('XD4_Unique_1'), ('D4_Unique_',)), [])

    def test_several_prefixes(self):
        all_mods = mods('D4_Unique_70', 'D4_Class_1010', 'Keep_Me')
        self.assertEqual(d4unique.superseded_mod_ids(all_mods, ('D4_Unique_', 'D4_Class_')),
                         ['D4_Class_1010', 'D4_Unique_70'])

    def test_no_prefix_supersedes_nothing(self):
        self.assertEqual(d4unique.superseded_mod_ids(mods('D4_Unique_1'), ()), [])
        self.assertEqual(d4unique.superseded_mod_ids(mods('D4_Unique_1'), None), [])
        self.assertEqual(d4unique.superseded_mod_ids(mods('D4_Unique_1'), ('',)), [])


if __name__ == '__main__':
    unittest.main()
