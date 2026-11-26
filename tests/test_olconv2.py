"""OLCONV2: the converted Overlord characters (Stella / Rutile / Majin).

Two kinds of test.  Lease-record and gate-behaviour tests need only the kit.  Mod-folder tests read the staged
build (`OLCONV2_STAGE`, default Builds/OLCONV2-20261119/stage/mods) and the extracted Overlord release, and skip when
either is absent (they hold game art/text and live outside the repo).  Nothing here touches the game or an install.
"""
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from tools.overlord_port import leases_unique  # noqa: E402

STAGE = Path(os.environ.get("OLCONV2_STAGE", "/Volumes/Data/Projects/D5/Builds/OLCONV2-20261119/stage/mods"))
RELEASE = Path("/Volumes/Data/ai-tmp/claude/overlord-v3")
NAMES = ("Overlord Character - Stella", "Overlord Character - Rutile", "Overlord Character - Majin")


def entries():
    return leases_unique.load()["entries"]


class LeaseRecord(unittest.TestCase):
    def test_three_entries(self):
        self.assertEqual(sorted(entries()), sorted(NAMES))

    def test_no_id_shared_between_the_three(self):
        seen = {}
        for name, e in entries().items():
            ids = [("char", e["identity"]), ("help", e["help_id"]), ("voice", e["voice"]), ("bill", e["bill"])]
            ids += [("skill", i) for i in e["evilities"]] + [("magic", i) for i in e["specials"]]
            ids += [("anm", e["physical"] + k) for k in (0, 1, 2)] + [("anm", 10000 + e["physical"]),
                                                                       ("anm", 10001 + e["physical"])]
            for key in ids:
                self.assertNotIn(key, seen, f"{key} held by {name} and {seen.get(key)}")
                seen[key] = name

    def test_ids_sit_in_the_bands_the_manifest_names(self):
        for e in entries().values():
            self.assertTrue(10000 <= e["identity"] <= 10990 and e["identity"] % 10 == 0)
            self.assertFalse(20000 <= e["identity"] < 22000, "Overlord's band stays his")
            self.assertTrue(all(29000 <= i <= 29099 for i in e["evilities"]))
            self.assertTrue(22000 <= e["bill"] <= 22099)
            self.assertTrue(9000 <= e["voice"] <= 9999)
            self.assertTrue(all(10000 + e["identity"] <= i < 10010 + e["identity"] for i in e["specials"]))
            self.assertLess(e["physical"], 1000)

    def test_third_run_window_is_carved(self):
        carve = json.loads((ROOT / "d5lib/data/unique_art_leases.json").read_text(encoding="utf-8"))["leases"]
        for name, e in entries().items():
            lo, hi = leases_unique.THIRD_RUN
            if lo <= e["physical"] <= hi:
                self.assertEqual(carve[name]["physical"], e["physical"])
                self.assertEqual(carve[name]["identity"], e["identity"])

    def test_lease_claims_reads_the_record(self):
        from d5lib import importcore
        got = {owner: c for src, owner, c in importcore.lease_claims() if src == "overlord-conv"}
        self.assertEqual(sorted(got), sorted(NAMES))
        for name, e in entries().items():
            self.assertIn(e["identity"], got[name]["char.dat"])
            self.assertIn(e["bill"], got[name]["WishDataBase.dat"])
            self.assertTrue({e["physical"], 10000 + e["physical"]} <= got[name]["anm"])

    def test_manifest_is_current(self):
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "tools/build_ownership_manifest.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class GateBehaviour(unittest.TestCase):
    def test_stats_family_refuses_a_cap(self):
        """Rutile's 40% cap cannot be written: the first build found this."""
        from d5lib import evility
        bad = {"29999": {"family": ["stats"], "effects": [{"stat": "all", "value": 5, "per": "squad", "max": 40}]}}
        with self.assertRaises(ValueError):
            evility.table(bad, {})
        ok = {"29999": {"family": ["stats"], "effects": [{"stat": "all", "value": 5, "per": "squad"}]}}
        evility.table(ok, {})

    def test_bank_gate_requires_the_full_stand_set_and_a_nonempty_dir(self):
        from tools.overlord_port import check_banks as CB
        cut = STAGE / NAMES[0] / f"files/Anime/ANM_HI_JP.dat/anm{10000 + entries()[NAMES[0]]['physical']:05d}.lzs"
        if not cut.is_file():
            self.skipTest("staged build not present")
        problems, _, _ = CB.check_bank(cut, body=True)       # a cut-in has none of the stand ids
        self.assertTrue(any("lacks the stand/idle" in p for p in problems), problems)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(CB.main([d]), 1)

    def test_learnable_row_past_bitmap_is_refused(self):
        from d5lib import learned
        rows = [{"id": i, "kind": 1, "shop_rank": 0} for i in range(1, 1000)] + [
            {"id": 29002, "kind": 0, "shop_rank": 0}, {"id": 29003, "kind": 0, "shop_rank": 0}]
        self.assertTrue(learned.budget(rows)["errors"])
        rows[-1]["kind"] = rows[-2]["kind"] = 1
        self.assertFalse(learned.budget(rows)["errors"])


@unittest.skipUnless(STAGE.is_dir() and RELEASE.is_dir(), "staged build / Overlord release not present")
class StagedMods(unittest.TestCase):
    def load(self, name, member):
        return json.loads((STAGE / name / "patches/db" / member).read_text(encoding="utf-8"))["added"]

    def test_each_mod_is_complete_and_consistent(self):
        from d5lib import evility, wishrecruit
        for name, e in entries().items():
            m = STAGE / name
            char = self.load(name, "char.dat.json")[0]
            self.assertEqual(char["id"], e["identity"])
            self.assertEqual((char["sprite_id"], char["color_id"]), (e["physical"], e["physical"]))
            self.assertEqual(char["help_id"], e["help_id"])
            self.assertEqual(char["voice_id"], e["voice"])
            self.assertEqual(self.load(name, "charhelp.dat.json")[0]["id"], e["help_id"])
            skills = {r["id"]: r for r in self.load(name, "Skill.dat.json")}
            self.assertEqual(sorted(skills), sorted(e["evilities"]))
            self.assertTrue(all(r["kind"] != 0 for r in skills.values()), "no learnable row past the bitmap")
            for n in range(1, char["evility_count"] + 1):
                self.assertIn(char[f"evility{n}"], skills)
            if e["specials"]:
                magic = {r["id"] for r in self.load(name, "magic.dat.json")}
                self.assertEqual(sorted(magic), sorted(e["specials"]))
                learn = {char[f"learn{i}_skill"] for i in range(1, 17)}
                self.assertTrue(set(e["specials"]) <= learn)
            u = json.loads((m / "patches/characters/unique.json").read_text())
            self.assertEqual((u["identity"], u["physical"]), (e["identity"], e["physical"]))
            self.assertTrue((m / f"patches/characters/face_{e['physical']}.png").is_file())
            for off in (0, 1, 2):
                self.assertTrue((m / f"files/Anime/ANM_HI_JP.dat/anm{e['physical'] + off:05d}.lzs").is_file())
            self.assertTrue((m / f"files/Anime/ANM_HI_JP.dat/anm{10000 + e['physical']:05d}.lzs").is_file())
            beh = json.loads((m / "patches/evilities/evilities.json").read_text())["evilities"]
            self.assertEqual(sorted(int(k) for k in beh), sorted(e["evilities"]))
            evility.table(beh, {})              # the Kit's own validator accepts every converted behaviour
            rec = json.loads((m / "patches/wishes/recruit_wishes.json").read_text())["recruits"]
            self.assertEqual(list(rec), [str(e["bill"])])
            self.assertEqual(rec[str(e["bill"])]["character"], e["identity"])
            wishrecruit.normalise(rec)
            v = json.loads((m / "patches/voices/voices.json").read_text())["voices"][str(e["voice"])]
            self.assertTrue(v["lines"])
            for line in v["lines"]:
                self.assertTrue((m / "patches/voices" / line["file"]).is_file())
            meta = json.loads((m / "mod.json").read_text())
            self.assertEqual(meta["credit"][0]["author"], "Cryswar")

    def test_every_evility_description_has_at_most_one_integer_conversion(self):
        for name in entries():
            for r in self.load(name, "Skill.dat.json"):
                for k, v in r.items():
                    if k.startswith("desc_"):
                        self.assertLessEqual(v.count("%d"), 1, (name, r["id"], k))

    def test_bodies_draw_a_whole_figure_not_an_overlay(self):
        """The offline smoke accepted P4's stand pose, a wireframe overlay.  Area check: the stand / idle ids of both
        banks cover at least half the opaque area of the source's own idle loop."""
        from d5lib import anm
        import numpy as np
        for name, e in entries().items():
            areas = []
            for off in (0, 1):
                a = anm.load(str(STAGE / name / f"files/Anime/ANM_HI_JP.dat/anm{e['physical'] + off:05d}.lzs"))
                for aid in (1, 7, 1001, 6001):
                    im = anm.render_items(a, anm.evaluate(a, ("id", aid), 0, nested=True), 0)[0]
                    areas.append((off, aid, int((np.asarray(im.getchannel("A")) > 0).sum())))
            top = max(v for _, _, v in areas)
            for off, aid, v in areas:
                self.assertGreater(v, 0.5 * top, (name, off, aid, v, top))

    def test_majin_second_bank_uses_its_whole_stand_poses_and_heat_depression_is_map_wide(self):
        meta = json.loads((STAGE / NAMES[2] / "mod.json").read_text())
        text = " ".join(meta["source_import"]["adaptations"])
        self.assertIn("source 7001 (whole stand pose (front)) on 3 donor ids [1,31,101]", text)
        self.assertIn("NO source attack pose is used", text)
        beh = json.loads((STAGE / NAMES[0] / "patches/evilities/evilities.json").read_text())["evilities"]
        heat = beh[str(entries()[NAMES[0]]["evilities"][3])]
        self.assertIn(0xFFFF, [c.get("radius") for c in heat["conditions"]])
        self.assertNotIn("radius 30", " ".join(json.loads((STAGE / NAMES[0] / "mod.json").read_text())
                                               ["source_import"]["adaptations"]))

    def test_overlay_detector_flags_the_release_sketch_layers(self):
        from tools.overlord_port import convert_unique as CU
        raw = CU.foreign_bank(CU.VIS / "Anime/ANM_HI_EN/anm20300.dat")
        full, area = CU.full_poses(raw)
        self.assertNotIn(7001, full)
        self.assertNotIn(7007, full)
        self.assertIn(6001, full)

    def test_custom_wishes_file_matches_olwish1_builtin_table(self):
        """closes OLWISH1 open item 1: his real custom_wishes.txt agrees with the table the converter ships"""
        from tools.overlord_port import recruit_wishes as RW
        parsed = RW.parse_custom_wishes((RELEASE / "mods/_loader/custom_wishes.txt").read_text(encoding="utf-8"))
        self.assertEqual(sorted(parsed), sorted(RW.OVERLORD_TABLE))
        for bill, (ch, lv, dup, flag, _) in RW.OVERLORD_TABLE.items():
            self.assertEqual(parsed[bill][:4], (ch, lv, dup, flag), bill)


if __name__ == "__main__":
    unittest.main()
