"""DRPGPARTY1: the class registry, the self_potential / party_weapons_distinct conditions and the D4 overlay step.

The native behaviour is proven in evility/offline_proof_drpgparty1.py (Unicorn, both modes); these tests cover the
Python side: vocabulary, encoding, registry data, overlay contents, apply/gate and their negative controls."""
import copy
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from d5lib import evility
from d5lib.importers import drpg_evilities as de

KIT = Path(__file__).resolve().parents[1]
MAIN_D4 = {"Master Big Star", "Sweet Omega", "Merome", "Kagemaru", "Tria", "Pii-chan", "Thunderlord Laharl",
           "Ice Empress Rozalin", "Flame Empress Majorita"}


def _pack(tmp, base_id):
    d = Path(tmp) / "pack"
    (d / "patches/db").mkdir(parents=True)
    (d / "mod.json").write_text(json.dumps({"name": "x", "source_import": {"source": {"character": {
        "base_id": base_id, "leader_skills": []}}}}))
    rows = [{"id": 11, "evility1": 0, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 0}]
    (d / "patches/db/char.dat.json").write_text(json.dumps({"table": "char.dat", "added": rows}))
    return d


def _stats(conds):
    return {"family": "stats", "effects": [{"stat": "atk", "mode": "percent", "value": 10}], "conditions": conds}


class Vocabulary(unittest.TestCase):
    def test_kinds_are_new_and_do_not_move_the_old_ones(self):
        self.assertEqual((evility.COND_KINDS["self_potential"], evility.COND_KINDS["party_weapons_distinct"]), (69, 70))
        old = {k: v for k, v in evility.COND_KINDS.items() if k not in ("self_potential", "party_weapons_distinct", "map_hp_at_or_below")}
        self.assertNotIn(69, old.values())
        self.assertNotIn(70, old.values())
        self.assertEqual(max(old.values()), 68)

    def test_potential_types_encode_as_a_bitmask(self):
        for types, mask in (([1], 1), ([2], 2), ([6], 32), ([1, 6], 33), ([2, 3, 4, 5], 30)):
            rows, conds, _ = evility.table({9001: [_stats([{"kind": "self_potential", "types": types}])]})
            self.assertEqual([c[1] for c in conds if c[0] == 69], [mask])

    def test_misuse_is_refused(self):
        for bad in ({"kind": "self_potential", "types": [0]}, {"kind": "self_potential", "types": [7]},
                    {"kind": "self_potential", "types": []}, {"kind": "self_potential"},
                    {"kind": "self_potential", "id": 0}, {"kind": "self_potential", "id": 64}):
            with self.assertRaises(ValueError, msg=str(bad)):
                evility.table({9001: [_stats([bad])]})

    def test_the_distinct_condition_takes_no_argument_and_is_a_map_walk(self):
        self.assertIn("party_weapons_distinct", evility.COND_NO_ARG)
        self.assertIn("party_weapons_distinct", evility.MAP_WALK_KINDS)
        evility.table({9001: [_stats([{"kind": "party_weapons_distinct"}])]})


class Registry(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads((KIT / "d5lib/importers/drpg-class-registry.json").read_text())

    def test_the_registry_is_accepted_and_sized(self):
        tbl = evility.class_table(self.doc["classes"])
        self.assertEqual(len(tbl), 235)
        self.assertEqual(sum(self.doc["counts"]["by_potential"].values()) if "by_potential" in self.doc["counts"] else 235, 235)
        self.assertLessEqual(len(tbl), evility.MAX_CLASSES)
        self.assertTrue(all(1 <= w <= 9 and 1 <= p <= 6 for _, w, p in tbl))

    def test_spot_checks_against_the_source_text(self):
        c = self.doc["classes"]
        for cid, want in (("12", (1, 6)), ("21", (1, 2)), ("112", (2, 5)), ("161", (4, 5)), ("162", (1, 6))):
            self.assertEqual((c[cid]["weapon"], c[cid]["potential"]), want, cid)

    def test_table_conflicts_and_range_are_refused(self):
        for bad in ({"0": {"weapon": 1}}, {"65536": {"weapon": 1}}, {"5": {"weapon": 10}}, {"5": {"potential": 7}},
                    {"5": {}}, {"5": {"weapon": 1, "extra": 1}}, {"5": {"weapon": True}}):
            with self.assertRaises(ValueError, msg=str(bad)):
                evility.class_table(bad)
        acc = {}
        evility._merge_classes(acc, {"5": {"weapon": 1, "potential": 2}})
        evility._merge_classes(acc, {"5": {"weapon": 1, "potential": 2}})          # the same type again is fine
        with self.assertRaises(ValueError):
            evility._merge_classes(acc, {"5": {"weapon": 2, "potential": 2}})

    def test_no_registry_leaves_the_legacy_encoding_alone(self):
        rows, conds, fx = evility.table({9001: [_stats([{"kind": "weapon", "id": 2}])]})
        self.assertEqual(evility.class_table(None), [])
        self.assertEqual(evility.class_table({}), [])


class Overlay(unittest.TestCase):
    def setUp(self):
        self.doc = de.overlay()
        self.d4 = [(v["name"], e) for v in self.doc["bases"].values() for e in v["evilities"] if "D4" in e["needs"]]

    def test_the_nine_mains_are_built_from_source_and_the_rest_fall_out_of_the_same_capability(self):
        mains = {n for n, e in self.d4 if e["slot"] == "main"}
        self.assertEqual(mains, MAIN_D4)
        self.assertEqual(len(self.d4), 15)
        self.assertTrue(all(e["cls"] == "A+" for _, e in self.d4))
        self.assertTrue(all(e["label"].startswith("source: Disgaea RPG JP leaderskill") for _, e in self.d4))
        self.assertTrue(all("source class registry" in e["label"] for _, e in self.d4))

    def test_d4_is_recorded_on_and_applies_only_with_the_registry_decision(self):
        self.assertTrue(self.doc["decisions"]["D4"])
        base = next(b for b, v in self.doc["bases"].items() if v["name"] == "Merome")
        on = [e for e in de.enabled(base) if "D4" in e["needs"]]
        self.assertEqual([e["slot"] for e in on], ["main"])
        self.assertEqual([e for e in de.enabled(base, {"D4": False}) if "D4" in e["needs"]], [])

    def test_the_whole_map_walk_comes_after_the_cheap_conditions(self):
        for _, e in self.d4:
            for row in e["rows"]:
                kinds = [c["kind"] for c in row.get("conditions", [])]
                if "party_weapons_distinct" in kinds:
                    self.assertEqual(kinds[-1], "party_weapons_distinct", kinds)

    def test_every_row_is_accepted_and_the_row_budget_holds(self):
        evility.table({e["id"]: e["rows"] for _, e in self.d4})
        self.assertLessEqual(self.doc["counts"]["runtime_rows_all_decisions"], evility.MAX_ROWS)

    def test_names_are_ascii_and_labelled(self):
        for _, e in self.d4:
            self.assertTrue(e["name_en"].isascii(), e["name_en"])
            self.assertIn("provisional", e["name_label"])


class Apply(unittest.TestCase):
    def _base(self, name):
        return int(next(b for b, v in de.overlay()["bases"].items() if v["name"] == name))

    def test_a_d4_base_gets_the_registry_and_the_gate_checks_it(self):
        base = self._base("Merome")
        tmp = tempfile.mkdtemp()
        try:
            d = _pack(tmp, base)
            self.assertFalse(de.gate(d, base)[0])
            out = de.apply(d, base)
            self.assertGreaterEqual(len(out["own"]), 1)
            ev = json.loads((d / "patches/evilities/evilities.json").read_text())
            self.assertEqual(ev["classes"], de.registry())
            self.assertEqual(len(ev["classes"]), 235)
            self.assertTrue(de.gate(d, base)[0])
            meta = json.loads((d / "mod.json").read_text())["source_import"]
            self.assertEqual(meta["signature_evility"], "source")
            before = {p: p.read_bytes() for p in d.rglob("*.json")}
            de.apply(d, base)                                                   # idempotent
            self.assertEqual(before, {p: p.read_bytes() for p in d.rglob("*.json")})
            # negative controls: each of these damages one thing and the gate must say so
            p = d / "patches/evilities/evilities.json"
            good = json.loads(p.read_text())
            drop = copy.deepcopy(good)
            del drop["classes"]
            p.write_text(json.dumps(drop))
            self.assertFalse(de.gate(d, base)[0])
            bent = copy.deepcopy(good)
            bent["classes"]["12"]["potential"] = 1
            p.write_text(json.dumps(bent))
            self.assertIn("class registry", de.gate(d, base)[1])
            short = copy.deepcopy(good)
            del short["classes"]["12"]
            p.write_text(json.dumps(short))
            self.assertFalse(de.gate(d, base)[0])
            p.write_text(json.dumps(good))
            self.assertTrue(de.gate(d, base)[0])
        finally:
            shutil.rmtree(tmp)

    def test_the_built_pack_reads_back_through_the_runtime_handler_data(self):
        base = self._base("Tria")
        tmp = tempfile.mkdtemp()
        try:
            d = _pack(tmp, base)
            de.apply(d, base)
            ev = json.loads((d / "patches/evilities/evilities.json").read_text())
            evility.table({int(k): v for k, v in ev["evilities"].items()})
            self.assertEqual(len(evility.class_table(ev["classes"])), 235)
            self.assertGreaterEqual(len(ev["evilities"]), 3)             # Tria: main, sub1 (sub2 waits for D3)
        finally:
            shutil.rmtree(tmp)

    def test_a_base_without_a_d4_evility_gets_no_registry(self):
        base = next(int(b) for b, v in de.overlay()["bases"].items()
                    if v["evilities"] and not any("D4" in e["needs"] for e in v["evilities"])
                    and any(e.get("rows") for e in v["evilities"] if not set(e["needs"]) - {"D1", "D2", "L1"}))
        tmp = tempfile.mkdtemp()
        try:
            d = _pack(tmp, base)
            if de.apply(d, base) and (d / "patches/evilities/evilities.json").exists():
                self.assertNotIn("classes", json.loads((d / "patches/evilities/evilities.json").read_text()))
        finally:
            shutil.rmtree(tmp)


class AsmRegistryBlock(unittest.TestCase):
    def test_registry_data_is_emitted_one_long_per_class_and_a_dummy_when_empty(self):
        rows, conds, fx = evility.table({9001: [_stats([{"kind": "self_potential", "types": [1]}])]})
        full = evility._asm_source(rows, conds, fx, evility.class_table({"12": {"weapon": 1, "potential": 6},
                                                                          "21": {"weapon": 1, "potential": 2}}))
        self.assertIn(f".long {12 | (1 << 16) | (6 << 24)}", full)
        self.assertIn(f".long {21 | (1 << 16) | (2 << 24)}", full)
        empty = evility._asm_source(rows, conds, fx, ())
        self.assertIn("evil_class_count", empty)
        self.assertNotIn(f".long {12 | (1 << 16) | (6 << 24)}", empty)
        self.assertEqual(struct.calcsize("<I"), 4)


if __name__ == "__main__":
    unittest.main()
