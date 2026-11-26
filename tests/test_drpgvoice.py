"""Disgaea RPG voice import: container readers, routing, linking and the voice gate (synthetic bytes only)."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from d5lib import drpgvoice as dv
from d5lib import importcore, sfx, voices


def mk_utf(cols, rows):
    """A CRI @UTF table with per-row columns; types: 'H' u16, 'I' u32, 'B' u8, 's' string, 'd' data."""
    code = {"B": 0, "H": 2, "I": 4, "s": 0xA, "d": 0xB}
    strings, data, schema, body = b"\0", b"", b"", b""

    def s(text):
        nonlocal strings
        at = len(strings)
        strings += text.encode() + b"\0"
        return at

    for name, t in cols:
        schema += struct.pack(">BI", 0x50 | code[t], s(name))
    for r in rows:
        for (name, t), v in zip(cols, r):
            if t == "s":
                body += struct.pack(">I", s(v))
            elif t == "d":
                body += struct.pack(">II", len(data), len(v))
                data += v
            else:
                body += struct.pack(">" + t, v)
    row_len = len(body) // max(1, len(rows))
    rows_off = 24 + len(schema)
    str_off = rows_off + len(body)
    data_off = str_off + len(strings)
    head = struct.pack(">HHIIIHHI", 1, rows_off, str_off, data_off, 0, len(cols), row_len, len(rows))
    b = head + schema + body + strings + data
    return b"@UTF" + struct.pack(">I", len(b)) + b


def mk_acb(cues):
    """cues: {name: [awb ids]} -> ACB where each cue is a sequence of one track per take (the game's layout)."""
    wave, synth, track, event, seq, cue, names = [], [], [], [], [], [], []
    for name, ids in cues.items():
        first = len(track)
        for wid in ids:
            wave.append((1, 22050, 1000, wid))
            synth.append((struct.pack(">HH", 1, len(wave) - 1),))
            event.append((struct.pack(">HBHH", 2000, 4, 2, len(synth) - 1) + struct.pack(">HB", 0, 0),))
            track.append((len(event) - 1,))
        seq.append((struct.pack(f">{len(ids)}H", *range(first, first + len(ids))),))
        cue.append((3, len(seq) - 1))
        names.append((name, len(cue) - 1))
    head = [("CueNameTable", "d"), ("CueTable", "d"), ("SynthTable", "d"), ("SequenceTable", "d"),
            ("TrackTable", "d"), ("TrackEventTable", "d"), ("WaveformTable", "d")]
    tables = [mk_utf([("CueName", "s"), ("CueIndex", "H")], names),
              mk_utf([("ReferenceType", "B"), ("ReferenceIndex", "H")], cue),
              mk_utf([("ReferenceItems", "d")], synth), mk_utf([("TrackIndex", "d")], seq),
              mk_utf([("EventIndex", "H")], track), mk_utf([("Command", "d")], event),
              mk_utf([("Streaming", "B"), ("SamplingRate", "H"), ("NumSamples", "I"), ("StreamAwbId", "H")], wave)]
    return mk_utf(head, [tables])


def mk_awb(members):
    ids = sorted(members)
    head = b"AFS2" + bytes([1, 4, 2, 0]) + struct.pack("<IH", len(ids), 32) + b"\0\0"
    head += b"".join(struct.pack("<H", i) for i in ids)
    end = len(head) + 4 * (len(ids) + 1)             # AFS2: member i starts at offset[i] aligned up, ends at offset[i+1]
    offs, body = [end], b""
    for i in ids:
        body += bytes(-(end + len(body)) % 32) + members[i]
        offs.append(end + len(body))
    return head + b"".join(struct.pack("<I", o) for o in offs) + body


def mk_bundle(payload):
    """UnityFS v8 with one stored block: <junk><u32 length><payload>."""
    data = b"\x07" * 37 + struct.pack("<I", len(payload)) + payload + b"\0" * 5
    info = bytes(16) + struct.pack(">I", 1) + struct.pack(">IIH", len(data), len(data), 0) + struct.pack(">I", 0)
    head = b"UnityFS\0" + struct.pack(">I", 8) + b"5.x.x\0" + b"2022.3.62f2\0"
    head += struct.pack(">QIII", 0, len(info), len(info), 0x200)
    head += bytes(-len(head) % 16)
    blob = head + info
    return blob + bytes(-len(blob) % 16) + data


def tone(seconds=0.5, level=0.5):
    t = np.arange(int(48000 * seconds)) / 48000
    return (np.sin(2 * np.pi * 440 * t) * level).astype(np.float32)


class Containers(unittest.TestCase):
    def test_lz4_literals_and_overlapping_match(self):
        # token 0x1F: 1 literal 'a', match length 15+4+1 = 20 at offset 1  -> 'a' * 21
        self.assertEqual(dv.lz4_block(bytes([0x1F, ord("a"), 1, 0, 1]), 21), b"a" * 21)
        with self.assertRaises(ValueError):
            dv.lz4_block(bytes([0x10, ord("a")]), 5)

    def test_bundle_acb_awb_roundtrip(self):
        acb = mk_acb({"voice_attack": [0, 1], "voice_dead": [2], "voice_sp03": [3]})
        self.assertEqual(dv.unityfs_payload(mk_bundle(acb), b"@UTF"), acb)
        cues = dv.acb_cues(acb)
        self.assertEqual({k: [w["awb_id"] for w in v] for k, v in cues.items()},
                         {"voice_attack": [0, 1], "voice_dead": [2], "voice_sp03": [3]})
        self.assertEqual(dv.awb_members(mk_awb({0: b"HCA0", 3: b"HCA3" * 9})), {0: b"HCA0", 3: b"HCA3" * 9})
        with self.assertRaises(ValueError):
            dv.unityfs_payload(mk_bundle(b"nothing here"), b"AFS2")

    def test_routes_cover_every_standard_cue_and_only_valid_destinations(self):
        table = dv.routes()
        for cue in ("voice_attack", "voice_h_attack", "voice_damage", "voice_dead", "voice_magic", "voice_recover",
                    "voice_turn", "voice_get", "voice_glad", "voice_sp"):
            self.assertIn(cue, table)
            for kind, dest in table[cue].items():
                self.assertIn(int(kind), range(voices.KINDS))
                self.assertTrue(dest["cats"] and all(0 <= c < voices.SITUATIONS for c in dest["cats"]))
        self.assertEqual(dv.cue_role("voice_sp017"), "voice_sp")
        self.assertIsNone(dv.cue_role("voice_hbd_0108_1"))
        self.assertIn(0, table["voice_attack"]["0"]["cats"])
        self.assertIn(21, table["voice_dead"]["0"]["cats"])

    def test_leases_are_unique_custom_ids_in_their_block_and_claimed(self):
        ids = dv.leases()
        self.assertEqual(len(set(ids.values())), len(ids))
        self.assertTrue(all(7000 <= v <= 7499 for v in ids.values()))
        claimed = {i for src, _owner, c in importcore.lease_claims() if src == "drpg" for i in c.get("voice", ())}
        self.assertEqual(claimed, set(ids.values()))


class OtherGames(unittest.TestCase):
    def test_dd2_and_d1c_maps_routes_and_leases_are_consistent(self):
        from d5lib import d1cvoice, dd2voice
        m = dd2voice.voice_map()
        used = dd2voice.routes()
        self.assertNotIn("1:13", used)                     # a column under the leave-one-out rule is never used
        self.assertIn(10, used["0:6"][0])                  # lift, as DD2EVENT1 proved from the executable
        self.assertIn(11, used["0:7"][0])                  # throw
        for c in m["characters"].values():
            for ids in c["rows"].values():
                self.assertTrue(all(str(v) in m["clips"] for v in ids))
        d1 = d1cvoice.voice_map()
        for mod in d1["mods"].values():
            for clip in mod["clips"].values():
                roles, _why = d1cvoice.clip_roles(clip)
                self.assertTrue(all(role in {**dv.routes(), **d1cvoice.CAST_ROUTE} for role in roles))   # D1CLIST3 cast role
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[3]))[0], [d1cvoice.CAST_ROLE])   # D1CLIST3: list 3 = heal/support cast
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[0, 3]))[0], ["voice_attack"])
        self.assertEqual(d1cvoice.clip_roles(dict(slots=[], drpg_cue="voice_magic"))[0], ["voice_magic"])
        ids = [*dv.leases().values(), *dd2voice.leases().values(), *d1cvoice.leases().values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(7600 <= v <= 7699 for v in dd2voice.leases().values()))
        self.assertTrue(all(7500 <= v <= 7599 for v in d1cvoice.leases().values()))
        claimed = [i for _s, _o, c in importcore.lease_claims() for i in c.get("voice", ())]
        self.assertTrue(set(ids) <= set(claimed))


class ImportAndGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source = root / "source"
        bank = self.source / dv.BANKS / "77"
        bank.mkdir(parents=True)
        (bank / "77_acb").write_bytes(mk_bundle(mk_acb({"voice_attack": [0, 1], "voice_dead": [2], "voice_sp01": [3],
                                                         "voice_damage": [4], "voice_pv_extra": [5]})))
        (bank / "77_awb").write_bytes(mk_bundle(mk_awb({i: b"HCA\0" + bytes([i]) * 8 for i in range(6)})))
        self.mod = root / "DRPG_Core_Test_77"
        (self.mod / "patches/db").mkdir(parents=True)
        (self.mod / "mod.json").write_text(json.dumps(dict(
            name="Test (Disgaea RPG)", source_import=dict(source=dict(row=dict(base_id=77)), voice="D5 donor",
                                                          leased_ids=dict(row=700, costumes=[])))))
        (self.mod / "patches/db/char.dat.json").write_text(json.dumps(dict(
            table="char.dat", added=[dict(id=700, name_EN="Test", voice_id=40)])))
        # take 4 (voice_damage) is the source's silent placeholder
        self.decode = mock.patch.object(dv, "decode_hca", lambda hca: tone(0.05, 0) if hca[4] == 4 else tone())
        self.decode.start()

    def tearDown(self):
        self.decode.stop()
        self.tmp.cleanup()

    def test_apply_links_routes_and_passes_the_gate(self):
        receipt = dv.apply(self.mod, self.source, lease={77: 7400})
        self.assertEqual([v["voice_id"] for v in receipt["voices"]], [7400])
        self.assertEqual(sorted(u["cue"] for u in receipt["voices"][0]["unrouted"]), ["voice_damage", "voice_pv_extra"])
        doc = json.loads((self.mod / "patches/db/char.dat.json").read_text())
        self.assertEqual(doc["added"][0]["voice_id"], 7400)
        data = json.loads((self.mod / "patches/voices/voices.json").read_text())["voices"]["7400"]
        self.assertTrue(all(ln["files"] == {"JP": ln["files"]["JP"]} and ln["fallback_language"] == "JP"
                            and ln["personality"] == 0 for ln in data["lines"]))
        dead = [ln for ln in data["lines"] if ln["cue"] == "voice_dead"]
        self.assertEqual({(ln["kind"], tuple(ln["cats"])) for ln in dead},
                         {(int(k), tuple(v["cats"])) for k, v in dv.routes()["voice_dead"].items()})
        for lang in ("EN", "JP"):                        # the English setting plays the Japanese line, never a donor
            self.assertEqual(len(voices.custom_lines(7400, data, lang=lang)), len(data["lines"]))
        ok, problems, stats = dv.voice_gate(self.mod)
        self.assertTrue(ok, problems)
        self.assertEqual(stats["files"], 4)
        self.assertIn("own", json.loads((self.mod / "mod.json").read_text())["source_import"]["voice"])
        self.assertEqual(importcore.mod_claims(self.mod)["voice"], {7400})

    def test_costume_with_a_bank_is_declared_and_one_without_follows_the_base(self):
        doc = json.loads((self.mod / "patches/db/char.dat.json").read_text())
        doc["added"] += [dict(id=30000, name_EN="Test", voice_id=40), dict(id=30010, name_EN="Test", voice_id=40)]
        (self.mod / "patches/db/char.dat.json").write_text(json.dumps(doc))
        meta = json.loads((self.mod / "mod.json").read_text())
        meta["source_import"]["leased_ids"]["costumes"] = [dict(row=30000, look=77), dict(row=30010, look=78)]
        (self.mod / "mod.json").write_text(json.dumps(meta))
        (self.mod / "patches/outfits").mkdir()
        (self.mod / "patches/outfits/outfits.json").write_text(json.dumps(dict(pairs=[[700, 30000], [700, 30010]])))
        receipt = dv.apply(self.mod, self.source, lease={77: 7400, 78: 7401})      # look 78 has no bank
        rows = {r["id"]: r["voice_id"] for r in json.loads((self.mod / "patches/db/char.dat.json").read_text())["added"]}
        self.assertEqual(rows, {700: 7400, 30000: 7400, 30010: 7400})
        self.assertEqual(json.loads((self.mod / "patches/outfits/outfits.json").read_text())["own_voice"], [30000])
        self.assertIn("follows", receipt["donor_kept"][0]["voice"])
        self.assertTrue(dv.voice_gate(self.mod)[0])

    def test_gate_fails_on_missing_silent_and_unlinked(self):
        dv.apply(self.mod, self.source, lease={77: 7400})
        folder = self.mod / "patches/voices"
        victim = sorted(folder.glob("*voice_attack*.vag"))
        victim[0].unlink()
        victim[1].write_bytes(sfx.make_vag(tone(0.5, 0.0), 48000, normalize=False, trim=False))
        ok, problems, _ = dv.voice_gate(self.mod)
        self.assertFalse(ok)
        self.assertTrue(any("missing clip" in p for p in problems) and any("peak" in p for p in problems), problems)
        doc = json.loads((self.mod / "patches/db/char.dat.json").read_text())
        doc["added"][0]["voice_id"] = 7401
        (self.mod / "patches/db/char.dat.json").write_text(json.dumps(doc))
        ok, problems, _ = dv.voice_gate(self.mod)
        self.assertTrue(any("does not define" in p for p in problems) and any("no char row" in p for p in problems))

    def test_silent_bank_is_silent_here_too_and_a_damaged_bank_is_refused(self):
        with mock.patch.object(dv, "decode_hca", lambda hca: tone(0.05, 0)):
            receipt = dv.apply(self.mod, self.source, lease={77: 7400})
        # VOICE2: a bank of silent placeholders = the character does not speak in the source; no donor voice is kept
        self.assertEqual((receipt["voices"], receipt["donor_kept"], len(receipt["silent"])), ([], [], 1))
        self.assertFalse((self.mod / "patches/voices").exists())
        self.assertEqual(json.loads((self.mod / "patches/db/char.dat.json").read_text())["added"][0]["voice_id"],
                         dv.SILENT_VOICE_ID)
        self.assertTrue(dv.voice_gate(self.mod)[0])
        bad = {f"sdcard/Android/data/com.disgaearpg.forwardworks/files/assetbundle/sounds/voice/battle/77/77_awb": "0" * 64}
        with self.assertRaises(ValueError):
            dv.read_bank(self.source, 77, bad)


if __name__ == "__main__":
    unittest.main()
