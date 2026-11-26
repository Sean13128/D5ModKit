"""DRPG-K2: the costume art contract and the assigned list icon (offline, synthetic inputs only).

The contract (`d5lib.importers.drpg_art`) is the check that every id a declared costume look claims resolves to art
the build wrote.  These tests drive its real decision path with a synthetic build (the ANM / texturedatabase /
exe readers are stubbed, so no game data is needed) and prove each required key can fail: a missing file, a wrong
block id, a blank standing atlas, a resident animation the build did not write, an icon cell with no pixels, an
icon table without the colour, and a row whose colour is not its art number.

Prior art: K1's `tests/test_drpg_outfits_k1.py` harness (real `modsys.Mod`, stubbed I/O); `d5lib/facepatch.py`
blocks 9017/9018; `d5lib/outfits.py` `_new_icons`/`_install_icons`.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from d5lib import anm, modsys, outfits
from d5lib.importers import drpg_art

LEASE = {"class_id": 30000, "art": 14600, "sprite_id": 14600, "color_id": 14600}


def _block_err(blocks):
    """an anm file as drpg_art sees it: block ids + animations + a texture count."""
    return [SimpleNamespace(id=b, animations=[SimpleNamespace(id=a) for a in anims],
                            texture_infos=[1], tex_base=0) for b, anims in blocks]


def build(art=14600, drop=(), resident_anims=None, atlas_pixels=True, exe=True, icon_rows=(500, 1317)):
    """a synthetic finalized build: {vpath: bytes}.  `drop` removes one contract key's file/anim."""
    blocks = {art: (art, [1]), art + 1: (art + 1, [1]), art + 2: (art + 2, ()),
              art + 10000: (art + 10000, [8000])}
    # the standing picture's own animation list is empty: its picture is texture data (cell 0x0 in vanilla)
    resident = {9017: [art, 10000 + art, 999999], 9018: [art]}
    if resident_anims is not None:
        resident = resident_anims
    out = {}
    for n, (bid, anims) in blocks.items():
        if any(k == n for k in drop):
            continue
        out[drpg_art.ANIME.format(n)] = (n, bid, anims)
    if "resident" not in drop:
        out[drpg_art.RESIDENT] = resident
    out[drpg_art.TDB] = icon_rows
    for name in drpg_art.ICON_FILES:
        out[f"{drpg_art.TEXTURES}/{name}"] = "atlas"
    if exe:
        from d5lib.gamefs import EXE_FILE
        out[EXE_FILE] = drpg_art.ICON_SECTION + b"\0" * 8 + _pair(art, icon_rows[0])
    return out


def _pair(colour, row):
    import struct
    return struct.pack("<II", colour, row)


class FakeBuild:
    """Stand-in for the kit's BuildContext.get plus the ANM/texture/db readers the contract calls."""

    def __init__(self, data, atlas_pixels=True):
        self.data = data
        self.atlas_pixels = atlas_pixels

    def get(self, vpath):
        key = vpath if vpath in self.data else vpath.lower()
        hit = next((v for k, v in self.data.items() if k.lower() == key.lower()), None)
        if hit is None:
            raise KeyError(vpath)
        return hit

    # the contract's readers, in the shapes anm / database / txf return
    def load_anm(self, data):
        tex = [SimpleNamespace(width=256, height=512, indexed=False, data=b"")]
        if isinstance(data, dict):                        # the resident pack: {block: [anim ids]}
            return SimpleNamespace(blocks=_block_err([(b, a) for b, a in data.items()]), textures=tex)
        n, bid, anims = data
        return SimpleNamespace(blocks=_block_err([(bid, anims)]), textures=tex)

    def load_table(self, member, data):
        rows = [{"id": tid, "x_EN": 0, "y_EN": 0, "w_EN": 48, "h_EN": 48} for tid in data]
        return SimpleNamespace(rows=rows)

    def to_image(self, raw):
        return Image.new("RGBA", (200, 200), (255, 0, 0, 255 if self.atlas_pixels else 0))


class ContractTests(unittest.TestCase):
    def run_contract(self, data, icon_cells=None, row=None, atlas_pixels=True):
        b = FakeBuild(data, atlas_pixels)
        cells = icon_cells if icon_cells is not None else {14600: (500, 1317)}
        with patch.object(drpg_art.anm, "load", side_effect=b.load_anm), \
             patch.object(drpg_art.anm, "texture_to_image",
                          return_value=Image.new("RGBA", (256, 512), (0, 0, 0, 255 if atlas_pixels else 0))), \
             patch.object(drpg_art.database, "load_table", side_effect=b.load_table), \
             patch.object(drpg_art.txf, "to_image", side_effect=b.to_image):
            return drpg_art.contract(LEASE, b.get, icon_cells=cells, row=row)

    def test_complete_look_passes_and_names_every_id(self):
        ok, problems, table = self.run_contract(build())
        self.assertTrue(ok, problems)
        self.assertEqual(problems, [])
        self.assertEqual((table["body"], table["own_anim"], table["standing"], table["portrait"]),
                         (14600, 14601, 14602, 24600))
        self.assertEqual(table["resident"]["9017"], [14600, 24600])
        self.assertEqual(table["resident"]["9018"], [14600])
        self.assertEqual(table["icon"], [500, 1317])

    def test_missing_standing_file_fails(self):
        ok, problems, _ = self.run_contract(build(drop=(14602,)))
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("standing:") and "not written" in p for p in problems), problems)

    def test_missing_body_file_fails(self):
        ok, problems, _ = self.run_contract(build(drop=(14600,)))
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("body:") for p in problems), problems)

    def test_blank_standing_atlas_fails(self):
        ok, problems, _ = self.run_contract(build(), atlas_pixels=False)
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("standing:") and "blank" in p for p in problems), problems)

    def test_resident_face_or_banner_animation_is_required(self):
        ok, problems, _ = self.run_contract(build(resident_anims={9017: [14600, 10000 + 14600]}))
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("banner:") for p in problems), problems)
        ok, problems, _ = self.run_contract(build(resident_anims={9017: [10000 + 14600], 9018: [14600]}))
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("face_framed:") for p in problems), problems)

    def test_no_resident_pack_reports_each_resident_key(self):
        ok, problems, _ = self.run_contract(build(drop=("resident",)))
        self.assertFalse(ok)
        self.assertEqual(sum(1 for p in problems if "resident block" in p), 3)

    def test_icon_needs_an_assigned_cell(self):
        ok, problems, _ = self.run_contract(build(), icon_cells={})
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("icon:") and "no list-icon cell" in p for p in problems), problems)

    def test_icon_cell_without_pixels_fails(self):
        ok, problems, _ = self.run_contract(build(), atlas_pixels=False)
        self.assertTrue(any(p.startswith("icon:") and "no pixels" in p for p in problems), problems)

    def test_icon_without_its_hook_entry_fails(self):
        data = build()
        from d5lib.gamefs import EXE_FILE
        data[EXE_FILE] = drpg_art.ICON_SECTION + b"\0" * 8               # section, no table entry
        ok, problems, _ = self.run_contract(data)
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("icon:") and "no entry" in p for p in problems), problems)

    def test_row_colour_must_be_its_art_number(self):
        ok, problems, _ = self.run_contract(build(), row={"sprite_id": 14600, "color_id": 30000})
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith("row 30000") for p in problems), problems)

    def test_look_ids_are_the_manifest_numbers(self):
        ids = drpg_art.look_ids(LEASE)
        self.assertEqual((ids["class_id"], ids["art"], ids["standing"], ids["portrait"], ids["banner"]),
                         (30000, 14600, 14602, 24600, 14600))
        self.assertEqual(drpg_art.summary(["icon: a", "icon: b", "banner: c"]), "banner x1, icon x2")


class AssignedIconTests(unittest.TestCase):
    """The build records the list-icon cell it assigned; nothing is derived from the declared colour."""

    def test_declared_icon_cells_reads_the_allocation(self):
        ctx = SimpleNamespace(_icon_cells={14600: (500, 1317)})
        self.assertEqual(outfits._declared_icon_cells(ctx, 14600), (500, 1317))
        self.assertEqual(outfits._declared_icon_cells(ctx, 14610), ())
        self.assertEqual(outfits._declared_icon_cells(SimpleNamespace(), 14600), ())

    def test_install_icons_records_each_key(self):
        ctx = SimpleNamespace(_icon_cells=None, log=lambda *_: None)
        exe = b"exe"
        with patch.object(outfits, "_new_icons", return_value=([(14600, 500)], 500, 1)), \
             patch.object(outfits.exepatch, "add_hook_section", return_value=exe):
            self.assertIs(outfits._install_icons(ctx, exe, [(14600, [14600], None)]), exe)
        self.assertEqual(ctx._icon_cells, {14600: (500, 500 + outfits.ICON_64)})
        self.assertEqual(outfits._declared_icon_cells(ctx, 14600), (500, 500 + outfits.ICON_64))


class BuildWiringTests(unittest.TestCase):
    """The build's own receipt carries the contract, so a missing key fails the build (not a note)."""

    def test_build_marks_art_contract_in_its_gates(self):
        source = Path(__file__).resolve().parents[1] / "d5lib/importers/_drpg_build.py"
        text = source.read_text()
        self.assertIn("art_contract=art_ok", text)
        self.assertIn("ok=readback and wheel and monster_scripts and art_ok and title_ok and evil_ok and skill_ok and not skipped", text)   # SMALLFIX1 class_title, DRPGEVIL1 own_evilities, DRPGSKILL1 own_skills
        self.assertIn("art_contracts=art_contracts", text)


if __name__ == "__main__":
    unittest.main()
