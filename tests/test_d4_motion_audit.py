"""D4IDLE1: tools/d4_motion_audit.py -- the gate's rules (synthetic rows) and a real negative control (D4 Politan's own
body written as a pack: must pass; the same bank slid down 9 px must fail)."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

import d4_motion_audit as A  # noqa: E402


def src(**kw):
    return dict(origin="source", source=1, timing_equal=True, diff=0.0, feet=0, dx=0.0, **kw)


class GateRules(unittest.TestCase):
    def test_all_equal_passes(self):
        ok, why, _ = A.gate({1: src(), 7: src(), 11: src(), 5: dict(origin="no-source")}, info=dict(humanoid=True))
        self.assertTrue(ok, why)

    def test_offset_fails(self):
        rows = {1: src(), 7: src(), 1001: dict(origin="offset", source=1001, feet=9, dx=3.0)}
        ok, why, _ = A.gate(rows, info=dict(humanoid=True))
        self.assertFalse(ok)
        self.assertIn("1001 offset", why)

    def test_key_times_differ_fails(self):
        rows = {1: src(), 7: dict(src(), timing_equal=False)}
        self.assertFalse(A.gate(rows, info=dict(humanoid=False))[0])

    def test_blank_with_twin_fails_except_documented_ids_on_humanoids(self):
        rows = {1: src(), 7: src(), 14: dict(origin="blank", source=14)}
        self.assertTrue(A.gate(rows, info=dict(humanoid=True))[0])
        self.assertFalse(A.gate(rows, info=dict(humanoid=False))[0])
        rows[15] = dict(origin="blank", source=15)
        self.assertFalse(A.gate(rows, info=dict(humanoid=True))[0])

    def test_missing_and_differs_fail(self):
        for o in ("missing", "differs", "held", "stand"):
            rows = {1: src(), 7: src(), 11: dict(origin=o, source=11)}
            self.assertFalse(A.gate(rows, info=dict(humanoid=False))[0], o)

    def test_labelled_held_must_sit_on_the_source_ground_line(self):
        good = dict(origin="held", source=None, held_from=1, labelled=True, diff=0.0, feet=0)
        self.assertTrue(A.gate({1: src(), 7: src(), 2071: good}, info=dict(humanoid=False))[0])
        low = dict(good, feet=9)
        self.assertFalse(A.gate({1: src(), 7: src(), 2071: low}, info=dict(humanoid=False))[0])
        other = dict(good, diff=40.0)
        self.assertFalse(A.gate({1: src(), 7: src(), 2071: other}, info=dict(humanoid=False))[0])

    def test_a_pack_that_compares_nothing_cannot_pass(self):
        ok, why, _ = A.gate({5: dict(origin="no-source"), 6: dict(origin="no-source-blank")}, info=dict(humanoid=False))
        self.assertFalse(ok)
        self.assertIn("compared", why)

    def test_unreadable_pack_fails(self):
        folder, res = A.run_pack((dict(folder="D4_Unique_1", error="bank missing"), 1.0, 1, A.SOURCE_ROOT))
        self.assertFalse(res["gate"])


@unittest.skipUnless(A.SOURCE_ROOT.is_dir(), "original Disgaea 4 Complete+ copy not present")
class RealNegativeControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = A.Source(A.SOURCE_ROOT)

    def pack(self, root, name, slide):
        """Politan (D4 610, body 610: motions 0, 1, 7) as a pack whose bank is D4's own body, slid `slide` px down."""
        body = copy.deepcopy(self.src.anm(610))
        for x in body.blocks[0].transforms:
            x.y += slide
        mod = Path(root) / name
        (mod / "patches/db").mkdir(parents=True)
        (mod / A.BANK_DIR).mkdir(parents=True)
        (mod / "mod.json").write_text(json.dumps(dict(source_import=dict(source_game="d4", source_id=610))))
        (mod / "patches/db/char.dat.json").write_text(json.dumps(dict(added=[dict(sprite_id=506)])))
        (mod / A.BANK_DIR / "anm00506.lzs").write_bytes(body.to_bytes())
        return A.d4_packs(Path(root))[0]

    def test_source_body_passes_and_slid_body_fails(self):
        with tempfile.TemporaryDirectory() as d:
            pack = self.pack(d + "/ok", "D4_Unique_610", 0)
            rows, info = A.audit_pack(self.src, pack)
            ok, why, _ = A.gate(rows, pack, info)
            self.assertTrue(ok, why)
            pack = self.pack(d + "/bad", "D4_Unique_610", 9)
            rows, info = A.audit_pack(self.src, pack)
            ok, why, _ = A.gate(rows, pack, info)
            self.assertFalse(ok, "a bank slid 9 px must fail")
            self.assertEqual(rows[1]["feet"], 9)


if __name__ == "__main__":
    unittest.main()
