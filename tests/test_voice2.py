"""VOICE2: silent-as-in-source packs, Disgaea 1 list roles and the map's shape (no game files, no audio)."""
import json
import tempfile
import unittest
from pathlib import Path

from d5lib import d1cvoice, dd2voice, voices
from d5lib import drpgvoice as dv


def mk_pack(root, voice_id=40, label="D5 donor"):
    mod = Path(root) / "X_Pack"
    (mod / "patches/db").mkdir(parents=True)
    (mod / "mod.json").write_text(json.dumps(dict(name="X", source_import=dict(voice=label))))
    (mod / "patches/db/char.dat.json").write_text(json.dumps(dict(added=[dict(id=700, voice_id=voice_id),
                                                                         dict(id=701, voice_id=voice_id)])))
    return mod


class Silent(unittest.TestCase):
    def test_silent_id_is_outside_game_and_custom_ids(self):
        self.assertTrue(5321 < dv.SILENT_VOICE_ID < voices.CUSTOM_FIRST)

    def test_link_silent_and_gate(self):
        with tempfile.TemporaryDirectory() as t:
            mod = mk_pack(t)
            changed = dv.link_silent(mod, "test game: no voice")
            self.assertEqual(changed, {700: (40, dv.SILENT_VOICE_ID), 701: (40, dv.SILENT_VOICE_ID)})
            self.assertTrue(json.loads((mod / "mod.json").read_text())["source_import"]["voice"].startswith("silent"))
            ok, problems, stats = dv.voice_gate(mod)
            self.assertTrue(ok, problems)
            self.assertEqual(stats["silent_rows"], 2)
            doc = json.loads((mod / "patches/db/char.dat.json").read_text())      # one row back on a donor: gate fails
            doc["added"][1]["voice_id"] = 40
            (mod / "patches/db/char.dat.json").write_text(json.dumps(doc))
            self.assertFalse(dv.voice_gate(mod)[0])

    def test_gate_rejects_silent_label_with_donor_rows(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(dv.voice_gate(mk_pack(t, label="silent, as in the source game (x)"))[0])


class D1Map(unittest.TestCase):
    def test_roles_follow_every_routed_list(self):
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[0, 1, 3]))[0], ["voice_attack", "voice_sp"])
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[3]))[0], [d1cvoice.CAST_ROLE])   # list 3 alone: heal/support cast
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[3], drpg_cue="voice_sp03"))[0], ["voice_sp"])   # a cue still wins
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[]))[0], [])
        self.assertEqual(d1cvoice.CAST_ROUTE[d1cvoice.CAST_ROLE]["0"]["cats"], [8, 9])
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[], drpg_cue="voice_magic"))[0], ["voice_magic"])

    def test_map_is_one_decision_per_pack(self):
        m = d1cvoice.voice_map()
        groups = [set(m["mods"]), set(m["silent"]), set(m["unchanged"])]
        self.assertEqual(sum(map(len, groups)), len(set().union(*groups)))
        ids = [x["voice_id"] for x in m["mods"].values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(m["voice_id_block"][0] <= i <= m["voice_id_block"][1] for i in ids))
        for folder, x in m["mods"].items():
            for stem, c in x["clips"].items():
                self.assertTrue(c["sha256"], (folder, stem))
                self.assertEqual(c.get("bank") == "se", "SE" in c["sha256"], (folder, stem))
            if x.get("sound_effect"):                 # a monster: one shared effect in all four lists
                self.assertEqual([c["slots"] for c in x["clips"].values()], [[0, 1, 2, 3]])

    def test_dd2_damage_and_death_columns_stay_unshipped(self):
        doc = json.loads(dd2voice.ROUTES_FILE.read_text())
        self.assertFalse(doc["routes"]["1:13"]["shipped"] or doc["routes"]["1:14"]["shipped"])
        self.assertIn("battle_has_no_damage_or_death_voice", doc["findings"])
        self.assertEqual(set(dd2voice.voice_map()["silent"]), {"300", "640"})


    def test_dd2voice5_routes_the_proven_columns_and_gives_every_held_one_a_reason(self):
        r = dd2voice.routes()
        self.assertEqual(r["0:2"], {0: [3, 4]})            # deployment (D5 3) and hostile spell cast (D5 4)
        self.assertEqual(r["0:5"], {0: [9]})               # heal cast at an ally (D5 9)
        self.assertEqual((r["0:6"], r["0:7"]), ({0: [10]}, {0: [11]}))     # lift, throw: unchanged
        self.assertEqual(r["0:0"], {0: [0]})               # attack only (DD2VOICE4 correction)
        # DD2VOICE5: the three proven special-skill cues play as D5 skill shouts 2, 6 and 13, never on 4 (spell cast)
        self.assertEqual((r["0:1"], r["0:4"], r["0:9"]), ({0: [2]}, {0: [6]}, {0: [13]}))
        doc = dd2voice.route_doc()
        for slot in ("0:1", "0:4", "0:9"):
            self.assertIn("adapted: cue position inside the skill not matched one to one", doc[slot]["label"])
        reasons = {c: x["hold_reason"] for c, x in doc.items() if not x["shipped"] and c.startswith("0:")}
        self.assertEqual(reasons["0:3"], "no_d5_situation")
        self.assertEqual({reasons[f"0:{s}"] for s in range(11, 18)}, {"not_called_in_source"})
        for held in ("0:3", "0:8", "0:10", "0:18"):
            self.assertNotIn(held, r)
        self.assertTrue(set(reasons.values()) <= {"no_d5_situation", "not_called_in_source", "no_place_found"})   # none unproven

    def test_dd2voice5_receipt_names_a_reason_per_held_column(self):
        # the receipt of a staged pack, when one is built next to the tests' scratch (skip otherwise)
        b = Path("/Volumes/Data/Projects/D5/Builds/DD2VOICE5-20261114/mods")
        packs = sorted(p for p in b.glob("DD2_*") if (p / "patches/voices/dd2-voice-receipt.json").is_file()) if b.is_dir() else []
        if not packs:
            self.skipTest("no staged DD2VOICE5 build")
        for p in packs:
            v = json.loads((p / "patches/voices/dd2-voice-receipt.json").read_text())["voices"][0]
            for col, h in v["held_back"].items():
                self.assertIn(h["reason"], ("unproven", "unknown", "no_d5_situation", "not_called_in_source", "no_place_found"), col)


class VoiceTrace(unittest.TestCase):
    def test_only_play_requests_are_kept(self):
        from d5lib import anmtrace
        with tempfile.TemporaryDirectory() as t:
            log = Path(t) / "d5auto.log"
            log.write_text("12:00:01.000 [voicetrace] lookup line=75200001 set=75200 caller=0x3f7954\n"
                           "12:00:01.100 [voicetrace] lookup line=75200002 set=75200 caller=0x3f7fd4\n"
                           "12:00:01.200 [anmtrace] miss id=643 caller=0x3ffce1\n")
            got = anmtrace.voice_requests(log)
        self.assertEqual([(g["line"], g["kind"], g["voice_id"], g["personality"], g["n"]) for g in got],
                         [(75200001, 0, 7520, 0, 1)])


if __name__ == "__main__":
    unittest.main()
