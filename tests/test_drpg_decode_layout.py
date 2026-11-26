"""DRPG-K2B: the missing-look decoder must write the exact names the CORERPG2 reader reads."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("drpg_decode_missing", ROOT / "tools/drpg_decode_missing.py")
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


class DecoderLayout(unittest.TestCase):
    def test_slots_match_the_importer_reader_layout(self):
        want = {
            "Sprites/Standard/BattleFront/front314.png": "atlas/chara/battle/front/front314",
            "Sprites/Standard/BattleBack/back314.png": "atlas/chara/battle/back/back314",
            "Sprites/Standard/WaitFront/front314.png": "atlas/chara/battle/wait_front/front314",
            "Sprites/Standard/WaitBack/back314.png": "atlas/chara/battle/wait_back/back314",
            "Chara Icons/314.png": "images/chara/face/314",
            "Cutins/314.png": "images/chara/ci/314",
        }
        got = {}
        for prefix, sub, bundle_tpl, file_tpl, _slot in decoder.SLOTS:
            bundle, png = decoder.reader_path(prefix, sub, bundle_tpl, file_tpl, 314)
            got[png.replace("\\", "/")] = bundle
        self.assertEqual(got, want)

    def test_reader_path_is_unpadded(self):
        """The client names bundles `front314`, not `front0314`; a padded name finds nothing."""
        for prefix, sub, bundle_tpl, file_tpl, _slot in decoder.SLOTS:
            bundle, _png = decoder.reader_path(prefix, sub, bundle_tpl, file_tpl, 94)
            self.assertNotIn("0094", bundle)
            self.assertIn("94", bundle)


if __name__ == "__main__":
    unittest.main()
