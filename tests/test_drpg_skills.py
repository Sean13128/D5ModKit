"""DRPGSKILL1: the Disgaea RPG own-skill overlay and its importer step."""
import json
import tempfile
import unittest
from pathlib import Path

from d5lib.importers import drpg_skills as ds

KIT = Path(__file__).resolve().parents[1]


def _pack(tmp, base_id, commands, learn, folder="DRPG_Core_Test"):
    d = Path(tmp) / folder
    (d / "patches/db").mkdir(parents=True)
    (d / "mod.json").write_text(json.dumps({"name": "x", "source_import": {"specials": "donor/adapted backlog", "source": {
        "character": {"base_id": base_id, "commands": commands}}}}))
    row = {"id": 11, "evility1": 1235, "learn_count": len(learn)}
    for i in range(1, 17):
        row[f"learn{i}_skill"] = learn[i - 1] if i <= len(learn) else 0
        row[f"learn{i}_level"] = 1 if i <= len(learn) else 0
    (d / "patches/db/char.dat.json").write_text(json.dumps({"table": "char.dat", "added": [row, dict(row, id=30000)]}))
    return d


class Overlay(unittest.TestCase):
    def setUp(self):
        self.doc = ds.overlay()
        self.all = [(b, s) for b, v in self.doc["bases"].items() for s in v["skills"]]

    def test_ids_are_unique_inside_the_manifest_band_and_follow_the_lease_order(self):
        lease = json.loads((KIT / "d5lib/importers/drpg-leases.json").read_text())
        order = [b["lease"].split(":")[1] for b in lease["bases"]]
        self.assertEqual(set(self.doc["bases"]), set(order))
        man = json.loads((KIT / "d5lib/data/ownership_manifest.json").read_text())
        band = next(b for b in man["namespaces"]["special_id"]["bands"] if b["start"] == 17000)
        self.assertEqual((band["owner"], band["end"]), ("kit", 17599))
        self.assertEqual(self.doc["band"], [17000, 17599])
        own = [s["d5_id"] for _, s in self.all if s["cls"] == "A"]
        self.assertEqual(len(own), len(set(own)))
        for b, s in self.all:
            if s["cls"] == "A":
                self.assertEqual(s["d5_id"], 17000 + 4 * order.index(b) + s["n"])
                self.assertEqual(s["set"]["id"], s["d5_id"])
                self.assertIn(str(s["stand_in"]["id"]), self.doc["stand_in_sha256"])
                self.assertLess(s["d5_id"], 32768)

    def test_every_own_row_carries_source_numbers_a_stand_in_and_a_label(self):
        for _, s in self.all:
            self.assertIn(s["cls"], ("E", "A", "X"))
            self.assertTrue(s["label"])
            self.assertIn(s["unlock_level"], (1, 50, 200))
            if s["cls"] == "E":
                self.assertTrue(0 < s["d5_id"] < 17000 or s["d5_id"] > 17599)
            if s["cls"] != "A":
                continue
            r = s["set"]
            self.assertTrue(s["stand_in"]["id"] and s["choreography"])
            self.assertEqual(s["name_label"], "provisional")
            self.assertTrue(r["name_EN"].isascii() and 0 < len(r["name_EN"]) < 48)
            self.assertLessEqual(len(r["desc_EN"].encode("utf-8")), 147)
            self.assertFalse([k for k in r if k.endswith(("_JP", "_FR", "_CHN", "_KOR"))])
            self.assertTrue(0 <= r.get("sp_cost", 0) <= 999)
            self.assertIn(r.get("element", 0), (0, 1, 2, 3, 4))
            self.assertIn(r.get("formula", 2), (2, 3))             # only a damage row ever changes its stat
            for k in ds.I16:
                self.assertTrue(-32768 <= r.get(k, 0) <= 32767)
            if s["kind"] == "damage":
                self.assertGreaterEqual(r.get("effect1_value", 0), -95)
                self.assertGreaterEqual(r.get("power_lv10", 163), 100)
                self.assertNotIn("power_lv1", r)                     # level 1 stays 100: effect1_value alone = source percent - 100
            for d in s["dropped"]:
                self.assertTrue(d["why"])

    def test_decisions_are_off_and_spells_wait_for_m1(self):
        self.assertEqual(self.doc["decisions"], {"M1": False, "C1": False})
        b = next(k for k, v in self.doc["bases"].items() if any(m["d5_id"] for m in v["magic"]))
        self.assertEqual(ds.spells(b), [])
        self.assertTrue(ds.spells(b, {"M1": True}))
        for v in self.doc["bases"].values():
            for m in v["magic"]:
                self.assertEqual(m["needs"], ["M1"])
                self.assertIn(m["level"], (4, 9, 13, 14, 15, 22, 30, 38, 39, 40))


class Apply(unittest.TestCase):
    def setUp(self):
        real = ds.overlay()
        self.base, self.skill = next((b, s) for b, v in real["bases"].items() for s in v["skills"]
                                     if s["cls"] == "A" and s["n"] == 0 and len([x for x in v["skills"] if x["cls"] == "A"]) == len(v["skills"]))
        self.skills = real["bases"][self.base]["skills"]
        # no game here: stand-in rows are fakes, pinned in a copy of the overlay
        self.vanilla = {s["stand_in"]["id"]: {"id": s["stand_in"]["id"], "name_JP": "x", "name_EN": "x", "desc_EN": "Unique:%sx",
                                              "sp_cost": 10, "rank": 0, "attack_map": 1, "anim_id": 5, "learn_level": 0,
                                              **{k: 0 for k in ds.I16}} for s in self.skills}
        self.vanilla[10101] = {"id": 10101}
        self._real_overlay = ds.overlay
        patched = dict(real, stand_in_sha256={str(k): ds.row_sha(v) for k, v in self.vanilla.items()})
        ds.overlay = lambda: patched

    def tearDown(self):
        ds.overlay = self._real_overlay

    def _commands(self):
        return [dict(rpg_id=s["rpg_id"], d5_id=s["stand_in"]["id"], verdict="lookalike") for s in self.skills] + \
               [dict(rpg_id=999, d5_id=10101, verdict="lookalike")]         # a costume look's lookalike

    def test_apply_links_own_skills_first_keeps_other_links_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            learn = [s["stand_in"]["id"] for s in self.skills] + [10101]
            learn = list(dict.fromkeys(learn))
            d = _pack(tmp, int(self.base), self._commands(), learn)
            done = ds.apply(d, self.base, vanilla=self.vanilla)
            want = [[s["d5_id"], s["unlock_level"]] for s in self.skills] + [[10101, 1]]
            self.assertEqual(done["learn"], want)
            rows = json.loads((d / "patches/db/char.dat.json").read_text())["added"]
            for r in rows:
                self.assertEqual([[r[f"learn{i}_skill"], r[f"learn{i}_level"]] for i in range(1, len(want) + 1)], want)
                self.assertEqual((r["learn_count"], r["evility1"], r[f"learn{len(want) + 1}_skill"]), (len(want), 1235, 0))
            magic = json.loads((d / "patches/db/magic.dat.json").read_text())["added"]
            self.assertEqual([r["id"] for r in magic], sorted(s["d5_id"] for s in self.skills))
            ch = json.loads((d / "patches/skills/skills.json").read_text())["skills"]
            self.assertEqual(ch[str(self.skill["d5_id"])], {"choreography": self.skill["choreography"]})
            meta = json.loads((d / "mod.json").read_text())["source_import"]
            self.assertEqual(meta["specials"], "donor/adapted backlog")
            self.assertEqual([x["kind"] for x in meta["skills"]["links"]][-1], "donor")
            self.assertEqual(magic[0]["name_JP"], magic[0]["name_EN"])
            self.assertTrue(ds.gate(d, self.base, vanilla=self.vanilla)[0])
            before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
            ds.apply(d, self.base, vanilla=self.vanilla)                                           # a second apply changes nothing
            self.assertEqual(before, {p: p.read_bytes() for p in d.rglob("*") if p.is_file()})

    def test_gate_refuses_a_changed_row_a_dangling_link_and_a_moved_learn_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pack(tmp, int(self.base), self._commands(), [s["stand_in"]["id"] for s in self.skills][:1])
            ds.apply(d, self.base, vanilla=self.vanilla)
            self.assertTrue(ds.gate(d, self.base, vanilla=self.vanilla)[0])
            self.assertRaises(ValueError, ds.row_of, self.skill, {self.skill["stand_in"]["id"]: {"id": 1}})     # not the pinned row
            p = d / "patches/db/magic.dat.json"
            doc = json.loads(p.read_text())
            doc["added"][0]["sp_cost"] += 1
            p.write_text(json.dumps(doc))
            self.assertIn("not the overlay's", ds.gate(d, self.base)[1])
            doc["added"][0]["sp_cost"] -= 1
            p.write_text(json.dumps(doc))
            self.assertTrue(ds.gate(d, self.base)[0])
            c = d / "patches/db/char.dat.json"
            doc = json.loads(c.read_text())
            doc["added"][1]["learn1_skill"] = 1001
            c.write_text(json.dumps(doc))
            self.assertIn("learn list", ds.gate(d, self.base)[1])

    def test_c1_drops_the_costume_lookalikes_and_m1_adds_the_spells(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _pack(tmp, int(self.base), self._commands(), [s["stand_in"]["id"] for s in self.skills] + [10101])
            done = ds.apply(d, self.base, {"C1": True, "M1": True}, self.vanilla)
            ids = [i for i, _ in done["learn"]]
            self.assertNotIn(10101, ids)
            sp = ds.spells(self.base, {"M1": True})
            self.assertEqual(ids[len(self.skills):], [m["d5_id"] for m in sp])
            self.assertEqual([lv for _, lv in done["learn"]][len(self.skills):], [m["level"] for m in sp])


if __name__ == "__main__":
    unittest.main()
