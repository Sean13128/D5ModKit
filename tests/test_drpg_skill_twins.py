"""The DRPG skill-twin swap table (motions): shape and use, no game needed."""
import json
import unittest
from pathlib import Path

TWINS = Path(__file__).resolve().parents[1] / "d5lib/importers/drpg-skill-twins.json"


class SkillTwinTable(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(TWINS.read_text())

    def test_every_swap_replaces_one_of_the_three_flagged_skills_with_a_different_one(self):
        self.assertTrue(self.doc["packs"])
        for pack, swaps in self.doc["packs"].items():
            self.assertTrue(pack.startswith("DRPG_"), pack)
            for old, t in swaps.items():
                self.assertIn(int(old), (10071, 10692, 10073))
                self.assertNotEqual(int(old), t["twin"])
                self.assertIsInstance(t["twin"], int)

    def test_builder_reads_the_table_by_folder_name(self):
        src = (Path(__file__).resolve().parents[1] / "d5lib/importers/_drpg_build.py").read_text()
        self.assertIn("drpg-skill-twins.json", src)
        self.assertIn("e['mod_folder']", src)


if __name__ == "__main__":
    unittest.main()
