"""VOICESILENT1: tools/stage_d4_silent.py - D4 packs the source game leaves silent (no game files needed except one
optional test that reads the real Disgaea 4 voice containers when they are present)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
import stage_d4_silent as S  # noqa: E402
from d5lib import drpgvoice as dv  # noqa: E402

D4_SOURCE = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+")


def mk_base(root, names=("D4_Unique_610", "D4_Unique_210")):
    for i, n in enumerate(names):
        mod = Path(root) / n
        (mod / "patches/db").mkdir(parents=True)
        (mod / "patches/outfits").mkdir(parents=True)
        (mod / "mod.json").write_text(json.dumps(dict(name=n, source_import=dict(source_game="d4")), indent=2 + 0 * i),
                                      encoding="utf-8")                      # indent 2, no final newline
        (mod / "patches/db/char.dat.json").write_text(
            json.dumps(dict(table="char.dat", added=[dict(id=700 + i, voice_id=2020, name="x")]), indent=1) + "\n")
        (mod / "patches/outfits/outfits.json").write_text("{}\n")


def fake(voiced_rows=()):
    def fn(_root, row_id):
        n = 3 if row_id in voiced_rows else 0
        return dict(row=row_id, name="n", body=row_id, groups=[row_id],
                    per_lang={l: dict(table_rows=n, archive_members=n, table_total=9, archive_total=9) for l in ("EN", "JP")})
    return fn


class Layout(unittest.TestCase):
    def test_link_silent_keeps_indent_and_missing_newline(self):
        with tempfile.TemporaryDirectory() as t:
            mk_base(t)
            mod = Path(t) / "D4_Unique_610"
            before = (mod / "mod.json").read_text()
            dv.link_silent(mod, "x", keep_layout=True)
            after = (mod / "mod.json").read_text()
            self.assertTrue(before.startswith('{\n  "name"') and after.startswith('{\n  "name"'))
            self.assertFalse(after.endswith("\n"))
            self.assertTrue(json.loads(after)["source_import"]["voice"].startswith("silent, as in the source game"))

    def test_default_layout_is_unchanged_voice2_shape(self):
        with tempfile.TemporaryDirectory() as t:
            mk_base(t)
            mod = Path(t) / "D4_Unique_610"
            dv.link_silent(mod, "x")
            raw = (mod / "mod.json").read_text()
            self.assertTrue(raw.startswith('{\n "name"') and raw.endswith("\n"))


class Stager(unittest.TestCase):
    def run_stage(self, t, voiced=()):
        base, out = Path(t) / "base", Path(t) / "out"
        base.mkdir()
        mk_base(base)
        rc = S.main([str(out), "--d4-source", "unused", str(base)], packs=(("D4_Unique_610", 610), ("D4_Unique_210", 210)),
                    source_voice_fn=fake(voiced))
        return rc, base, out

    def test_silent_pack_changes_only_two_files(self):
        with tempfile.TemporaryDirectory() as t:
            rc, base, out = self.run_stage(t)
            self.assertEqual(rc, 0)
            for n in ("D4_Unique_610", "D4_Unique_210"):
                proof = S.diff_proof(base / n, out / "mods" / n)
                self.assertTrue(proof["ok"], proof)
                self.assertEqual(proof["changed"], ["mod.json", "patches/db/char.dat.json"])
                ok, problems, stats = dv.voice_gate(out / "mods" / n)
                self.assertTrue(ok, problems)
                self.assertEqual(stats["silent_rows"], 1)
                row = json.loads((out / "mods" / n / "patches/db/char.dat.json").read_text())["added"][0]
                self.assertEqual(row["voice_id"], dv.SILENT_VOICE_ID)
            rec = json.loads((out / "STAGE-RECEIPT.json").read_text())
            self.assertTrue(rec["bases_unchanged"] and all(p["staged"] for p in rec["packs"]))

    def test_stops_when_the_source_does_voice_the_character(self):
        with tempfile.TemporaryDirectory() as t:
            rc, base, out = self.run_stage(t, voiced={610})
            self.assertEqual(rc, 2)
            self.assertFalse((out / "mods" / "D4_Unique_610").exists())     # nothing written for the voiced one
            self.assertTrue((out / "mods" / "D4_Unique_210").is_dir())
            rec = json.loads((out / "STAGE-RECEIPT.json").read_text())
            self.assertEqual([p["staged"] for p in rec["packs"]], [False, True])

    def test_diff_proof_rejects_an_extra_change(self):
        with tempfile.TemporaryDirectory() as t:
            rc, base, out = self.run_stage(t)
            f = out / "mods/D4_Unique_610/patches/outfits/outfits.json"
            f.write_text('{"x": 1}\n')
            self.assertFalse(S.diff_proof(base / "D4_Unique_610", out / "mods/D4_Unique_610")["ok"])
            f = out / "mods/D4_Unique_210/patches/db/char.dat.json"
            doc = json.loads(f.read_text())
            doc["added"][0]["name"] = "changed"
            f.write_text(json.dumps(doc, indent=1) + "\n")
            self.assertIn("char.dat.json differs beyond voice_id",
                          S.diff_proof(base / "D4_Unique_210", out / "mods/D4_Unique_210")["problems"])


@unittest.skipUnless(D4_SOURCE.is_dir(), "Disgaea 4 source copy not present")
class RealSource(unittest.TestCase):
    def test_politan_and_pringer_x_have_no_voice_rows_or_members_but_pleinair_does(self):
        for row in (610, 210):
            self.assertFalse(S.voiced(S.source_voice(D4_SOURCE, row)), row)
        self.assertEqual(S.source_voice(D4_SOURCE, 210)["groups"], [210, 5405])
        # control: a character that D4 does voice (Pleinair, group 330) must read as voiced, so the check can fail
        pleinair = next(i for i, c in __import__("d5lib.d4source", fromlist=["x"]).D4Data(D4_SOURCE, "EN").chars.items()
                        if c.get("voice_group_base") == 330)
        self.assertTrue(S.voiced(S.source_voice(D4_SOURCE, pleinair)))


if __name__ == "__main__":
    unittest.main()
