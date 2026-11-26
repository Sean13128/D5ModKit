"""DRPGEVIL1: the Disgaea RPG own-evility overlay and its importer step."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from d5lib import evility
from d5lib.importers import drpg_evilities as de

KIT = Path(__file__).resolve().parents[1]
OFF = {"D1": False, "D2": False, "D3": False, "L1": False}   # DRPGEVIL2: the overlay now records D1, D2, L1 on; these tests mean "nothing decided"


def _pack(tmp, base_id, leader_skills):
    d = Path(tmp) / "pack"
    (d / "patches/db").mkdir(parents=True)
    (d / "mod.json").write_text(json.dumps({"name": "x", "source_import": {"source": {"character": {
        "base_id": base_id, "leader_skills": leader_skills}}}}))
    rows = [{"id": 11, "evility1": 1235, "evility2": 101, "evility3": 0, "evility4": 0, "evility_count": 2},
            {"id": 30000, "evility1": 1235, "evility2": 101, "evility3": 0, "evility4": 0, "evility_count": 2}]
    (d / "patches/db/char.dat.json").write_text(json.dumps({"table": "char.dat", "added": rows}))
    return d


class Overlay(unittest.TestCase):
    def setUp(self):
        self.doc = de.overlay()
        self.all = [(b, e) for b, v in self.doc["bases"].items() for e in v["evilities"]]

    def test_ids_are_unique_inside_the_manifest_band_and_follow_the_lease_order(self):
        lease = json.loads((KIT / "d5lib/importers/drpg-leases.json").read_text())
        order = [b["lease"].split(":")[1] for b in lease["bases"]]
        ids = [e["id"] for _, e in self.all]
        self.assertEqual(len(ids), len(set(ids)))
        man = json.loads((KIT / "d5lib/data/ownership_manifest.json").read_text())
        band = next(b for b in man["namespaces"]["evility_id"]["bands"] if b["start"] == 28000)
        self.assertEqual((band["owner"], band["end"]), ("kit", 28999))
        for b, e in self.all:
            self.assertEqual(e["id"], 28000 + 4 * order.index(b) + ("main", "sub1", "sub2", "sub3").index(e["slot"]))
            self.assertEqual(e["skill_row"]["id"], e["id"])
            self.assertEqual(e["skill_row"]["owner"], self.doc["bases"][b]["row"])

    def test_every_row_is_accepted_by_the_runtime_and_all_decisions_fit_the_row_budget(self):
        total = 0
        for _, e in self.all:
            if e.get("rows"):
                total += len(evility.table({e["id"]: e["rows"]})[0])     # raises on any row the runtime refuses
        self.assertEqual(total, self.doc["counts"]["runtime_rows_all_decisions"])
        now = {e["id"]: e["rows"] for _, e in self.all if e.get("rows") and not e["needs"]}
        self.assertLessEqual(len(evility.table(now)[0]), evility.MAX_ROWS)
        # DRPGEVIL1c: every decision switched on fits the raised table (2,048 rows) in ONE table
        self.assertEqual(self.doc["counts"]["runtime_row_limit"], evility.MAX_ROWS)
        self.assertEqual(len(evility.table({e["id"]: e["rows"] for _, e in self.all if e.get("rows")})[0]), total)
        self.assertLessEqual(total + 64, evility.MAX_ROWS)
        for _, e in self.all:
            self.assertTrue(e.get("rows") or e.get("alias"))
            for r in e.get("rows") or []:
                fam = r["family"] if isinstance(r["family"], list) else [r["family"]]
                near = [c for c in r.get("conditions", []) if c["kind"] == "near_has"]
                self.assertEqual("aura" in fam, bool(near))    # an aura names its provider: the evility itself
                self.assertTrue(all(c["id"] == e["id"] for c in near))
                kinds = [c["kind"] for c in r.get("conditions", [])]
                for i, k in enumerate(kinds):                  # a holder-side condition follows its near_has
                    if k.startswith("provider_"):
                        self.assertEqual(kinds[i - 1], "near_has")

    def test_text_is_ascii_names_are_labelled_and_decisions_are_the_recorded_ones(self):
        self.assertEqual(self.doc["decisions"], {"D1": True, "D2": True, "D3": False, "L1": True, "D4": True})  # DRPGEVIL2 + DRPGPARTY1 D4
        for _, e in self.all:
            row = e["skill_row"]
            self.assertTrue(row["name_EN"].isascii() and row["name_EN"] == e["name_en"])
            self.assertEqual(row["name_JP"], e["name_jp"])
            self.assertNotIn("%", row["desc_EN"].replace("%d", ""))    # full-width percent only (DECISIONS 10-29)
            self.assertIn("provisional", e["name_label"])
            self.assertTrue(e["label"].startswith(("source:", "D5 equivalent:")))
            self.assertEqual(bool(e["needs"]), e["cls"] == "A+")

    def test_party_scope_never_applies_without_the_decision(self):
        for b in self.doc["bases"]:
            for e in de.enabled(b, OFF):
                self.assertFalse(e["needs"])
                self.assertFalse(any("aura" in r["family"] for r in e.get("rows") or []))
        gated = next(b for b, e in self.all if e["needs"] == ["D1"] and any("aura" in r["family"] for r in e["rows"]))
        self.assertGreater(len(de.enabled(gated, {"D1": True})), len(de.enabled(gated, OFF)))

    def test_every_row_is_innate_only_so_it_may_sit_past_the_learned_bitmap(self):
        from d5lib import learned
        for _, e in self.all:
            row = e["skill_row"]
            self.assertEqual((row["kind"], row["shop_rank"], row["mana_cost"], row["slot_cost"]), (2, 0, 0, 0))
            self.assertTrue(row["id"] <= learned.INNATE_MAX_ID and row["id"] != learned.INNATE_FREE)
        base = [dict(id=i, kind=0, shop_rank=0) for i in range(1, 961)]
        b = learned.budget(base + [e["skill_row"] for _, e in self.all])       # 960 + every overlay row
        self.assertEqual((b["errors"], b["innate_past"]), ([], 960 + len(self.all) - 1000))
        self.assertTrue(b["warnings"])
        bad = learned.budget(base + [dict(id=30000 + i, kind=0, shop_rank=0) for i in range(50)])
        self.assertEqual(len(bad["learnable_past"]), 10)                         # a learnable row past 999 fails
        self.assertTrue(bad["errors"])
        self.assertTrue(learned.budget([dict(id=i, kind=0, shop_rank=1) for i in range(1, 1002)])["errors"])
        self.assertTrue(learned.budget([dict(id=40000, kind=2, shop_rank=0)])["errors"])
        self.assertTrue(learned.budget([dict(id=9999, kind=2, shop_rank=0)])["errors"])

    def test_samples_are_left_alone(self):
        for b in self.doc["samples_untouched"]:
            self.assertEqual(de.enabled(b, {"D1": True, "D2": True, "D3": True}), [])


class Apply(unittest.TestCase):
    def test_apply_links_own_first_keeps_donors_and_the_gate_passes(self):
        doc = de.overlay()
        base, ev = next((b, v["evilities"]) for b, v in doc["bases"].items()
                        if [e["slot"] for e in v["evilities"] if not e["needs"]] == ["sub3"])
        own = [e for e in ev if not e["needs"]][0]
        main_rpg = own["rpg_ids"][0] - 3
        ls = [{"rpg_id": main_rpg, "evility": {"id": 1235}}, {"rpg_id": main_rpg + 1, "evility": {"id": 101}},
              {"rpg_id": own["rpg_ids"][0], "evility": {"id": 161}}]
        tmp = tempfile.mkdtemp()
        try:
            d = _pack(tmp, int(base), ls)
            self.assertEqual(de.gate(d, int(base), OFF)[0], False)
            out = de.apply(d, int(base), OFF)
            self.assertEqual(out["links"], [own["id"], 1235, 101])       # the donor of the built slot (161) is gone
            for r in json.loads((d / "patches/db/char.dat.json").read_text())["added"]:
                self.assertEqual([r[f"evility{i}"] for i in range(1, 5)], [own["id"], 1235, 101, 0])
                self.assertEqual(r["evility_count"], 3)
            self.assertEqual(json.loads((d / "patches/db/Skill.dat.json").read_text())["added"], [own["skill_row"]])
            meta = json.loads((d / "mod.json").read_text())["source_import"]
            self.assertTrue(meta["signature_evility"].startswith("donor"))
            self.assertEqual([x["kind"] for x in meta["evilities"]["links"]], ["source", "donor", "donor"])
            self.assertEqual(de.gate(d, int(base), OFF), (True, "1 own evilities linked first, 2 donor links kept"))
            before = {p: p.read_bytes() for p in d.rglob("*.json")}
            de.apply(d, int(base), OFF)                                       # idempotent
            self.assertEqual(before, {p: p.read_bytes() for p in d.rglob("*.json")})
        finally:
            shutil.rmtree(tmp)

    def test_a_base_with_nothing_built_is_untouched(self):
        doc = de.overlay()
        base = next(b for b, v in doc["bases"].items() if all(e["needs"] for e in v["evilities"]))
        tmp = tempfile.mkdtemp()
        try:
            d = _pack(tmp, int(base), [])
            before = {p: p.read_bytes() for p in d.rglob("*.json")}
            self.assertIsNone(de.apply(d, int(base), OFF))
            self.assertEqual(before, {p: p.read_bytes() for p in d.rglob("*.json")})
            self.assertTrue(de.gate(d, int(base), OFF)[0])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
