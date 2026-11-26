"""DRPG-SAVESLOT1: a quest slot a known save already marks is taken; only the colliding bases move."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from d5lib.importers import _drpg_namespaces as ns  # noqa: E402
from d5lib.importers import drpg_leases as leases  # noqa: E402


def manifest(slots):
    return {"bases": [{"lease": f"drpg:{k}"} for k in slots]}


class DirtySlots(unittest.TestCase):
    def test_only_the_planted_dirty_slot_moves_and_is_recorded(self):
        cur = {f"drpg:{k}": {"help_id": 4000 + i, "quest_id": 10 + i, "quest_slot": s}
               for i, (k, s) in enumerate({"a": 700, "b": 701, "c": 702}.items())}
        dirty = {"generated": "2026-11-09", "source": "backup", "slots": [701, 5]}
        new, moved = leases.pin_namespaces(manifest("abc"), cur, set(), set(), {0, 1, 2}, first=(), dirty_slots=dirty)
        self.assertEqual(set(moved), {"drpg:b"})
        self.assertEqual(list(moved["drpg:b"]), ["quest_slot"])
        ns_ = {b["lease"]: b["namespaces"]["quest_slot"] for b in new["bases"]}
        self.assertEqual((ns_["drpg:a"], ns_["drpg:c"]), (700, 702))
        self.assertNotIn(ns_["drpg:b"], {701, 5, 0, 1, 2, 700, 702})
        self.assertEqual(new["dirty_slots"], {"generated": "2026-11-09", "source": "backup", "slots": [5, 701]})

    def test_a_mover_never_takes_a_neighbours_current_slot(self):
        cur = {"drpg:a": {"quest_slot": 3}, "drpg:b": {"quest_slot": 4}}      # a is dirty; the first free slot is 4 = b's
        new, moved = leases.pin_namespaces(manifest("ab"), cur, set(), set(), set(), first=(), dirty_slots={"slots": [3]})
        self.assertEqual({k for k, v in moved.items() if "quest_slot" in v}, {"drpg:a"})
        got = {b["lease"]: b["namespaces"]["quest_slot"] for b in new["bases"]}
        self.assertEqual(got["drpg:b"], 4)
        self.assertNotIn(got["drpg:a"], (3, 4))

    def test_without_a_dirty_file_nothing_moves(self):
        cur = {"drpg:a": {"quest_slot": 700}}
        new, moved = leases.pin_namespaces(manifest("a"), cur, set(), set(), set(), first=())
        self.assertNotIn("quest_slot", moved.get("drpg:a", {}))
        self.assertNotIn("dirty_slots", new)

    def test_reserve_skips_dirty_slots_for_unpinned_entries(self):
        orig = ns.taken_namespaces
        ns.taken_namespaces = lambda fs, root, extra=(): (set(), set(), {0})
        try:
            out = ns.reserve(["drpg:a"], None, ".", dirty_slots=[1, 2])
        finally:
            ns.taken_namespaces = orig
        self.assertEqual(out["drpg:a"]["quest_slot"], 3)

    def test_committed_manifest_records_the_dirty_slots_and_no_base_sits_on_one(self):
        m = leases.load()
        d = m.get("dirty_slots")
        self.assertTrue(d and d["generated"] and d["slots"])
        bad = [b["lease"] for b in m["bases"] if b["namespaces"]["quest_slot"] in set(d["slots"])]
        self.assertEqual(bad, [])


class SurveyTool(unittest.TestCase):
    def test_reads_every_sav_but_systemsave(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import save_quest_slots as t
        d = Path(tempfile.mkdtemp())
        (d / "SystemSave.sav").write_bytes(b"x")
        doc = t.survey(d)
        self.assertEqual(doc["saves"], [])
        self.assertEqual(doc["slots"], {})


if __name__ == "__main__":
    unittest.main()
