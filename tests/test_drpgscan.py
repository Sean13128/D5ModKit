import os
import shutil
import tempfile
import unittest
import zipfile

from PIL import Image

from d5lib import drpg, drpgscan, drpgsource


def png(path, size=(8, 8)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGBA", size, (255, 0, 0, 255)).save(path)


def fixture(base):
    """a folder holding several kinds of Disgaea RPG sources side by side"""
    flat = os.path.join(base, "DRPG-Assets-Updated", "Characters")
    png(os.path.join(flat, "Sprites", "front", "front7.png"))
    png(os.path.join(flat, "Sprites", "back", "back9.png"))
    png(os.path.join(flat, "Icons", "7.png"))
    client = os.path.join(base, "Client")
    battle = os.path.join(client, "tex", "atlas", "chara", "battle")
    for role, side in (("front", "front"), ("back", "back"), ("wait_front", "front"), ("wait_back", "back")):
        png(os.path.join(battle, role, f"{side}7.png"))
    png(os.path.join(battle, "front", "front7_1.png"), (16, 16))
    png(os.path.join(battle, "front_inversion", "front12.png"))
    png(os.path.join(client, "tex", "images", "chara", "face", "7.png"))
    png(os.path.join(client, "tex", "images", "chara", "ci", "7.png"))
    png(os.path.join(client, "sprite", "atlas", "chara", "battle", "front", "front7", "walk01.png"))
    png(os.path.join(client, "tex", "atlas", "chara", "story", "front", "front3.png"))
    jp = os.path.join(base, "JP", "atlas", "chara", "battle", "front")
    os.makedirs(jp)
    with open(os.path.join(jp, "front8"), "wb") as f:
        f.write(b"UnityFS\x00rest")
    with open(os.path.join(jp, "front99"), "wb") as f:
        f.write(b"not a bundle")
    with open(os.path.join(base, "Units IDs.txt"), "w", encoding="utf-8") as f:
        f.write("---- UNIQUES (Humans) ----\n7 Test Unit\n")


class DrpgScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "Forge")
        fixture(self.base)
        self._cache = drpgscan.CACHE_DIR
        drpgscan.CACHE_DIR = os.path.join(self.tmp, "cache")
        drpgscan.forget()

    def tearDown(self):
        drpgscan.CACHE_DIR = self._cache
        drpgscan.forget()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_every_layout_and_leaves_out_the_rest(self):
        found = drpgscan.get(self.base)
        self.assertEqual(found.uids, [7, 8, 9])            # not story (3), *_inversion (12) or a non-bundle (99)
        self.assertEqual(found.names[7], ("Test Unit", "unique"))
        self.assertTrue(found.sheet_entries(8)["front"].bundle)

    def test_a_unit_takes_its_sheets_from_its_fullest_set_and_the_plain_name(self):
        found = drpgscan.get(self.base)
        sheets = drpgscan.unit_sheets(self.base, 7)
        self.assertEqual(sorted(sheets), sorted(drpgscan.ROLES))
        for p in sheets.values():
            self.assertIn(os.path.join("Client", "tex", "atlas"), p)
        self.assertTrue(sheets["front"].endswith("front7.png"))
        self.assertEqual(set(found.sheet_entries(9)), {"back"})
        extras = drpgscan.unit_extras(self.base, 7)
        self.assertIn(os.path.join("chara", "face"), extras["icon"])  # nearest the unit's set, not the flat rip's
        self.assertIn(os.path.join("chara", "ci"), extras["cutin"])

    def test_a_zip_reads_the_same_and_unpacks_on_demand(self):
        z = os.path.join(self.tmp, "forge.zip")
        with zipfile.ZipFile(z, "w") as zf:
            for d, _, files in os.walk(self.base):
                for f in files:
                    p = os.path.join(d, f)
                    zf.write(p, os.path.relpath(p, self.tmp).replace(os.sep, "/"))
        found = drpgscan.get(z)
        self.assertEqual(found.uids, [7, 8, 9])
        p = drpgscan.unit_sheets(z, 7)["wait_back"]
        self.assertTrue(p.startswith(drpgscan.CACHE_DIR) and os.path.exists(p))

    def test_the_builders_and_the_picker_see_scanned_units(self):
        kit_rip = os.path.join(self.tmp, "DRPG Assets (Updated)")       # a fixed-layout folder after the chosen one
        png(os.path.join(kit_rip, "Characters", "Sprites", "front", "front7.png"))
        sheets = drpg.unit_sheets(7, roots=[self.base, kit_rip])
        self.assertIn(os.path.join("Client", "tex"), sheets["front"])
        self.assertEqual(drpgsource.looks_like_drpg_root(self.base), self.base)
        units = drpgsource.scan(self.base)
        self.assertEqual(units[7].missing(), [])
        self.assertEqual(units[7].name, "Test Unit")
        self.assertEqual(units[9].missing(), ["front", "wait_front", "wait_back"])
        self.assertEqual(units[7].sheets()["back"], sheets["back"])


if __name__ == "__main__":
    unittest.main()
