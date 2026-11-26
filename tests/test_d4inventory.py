"""Synthetic source bytes exercise conservative inventory boundaries; no game data."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from d5lib import d4inventory as inv, d4source, script


def nsac(entries):
    names_size = sum(11 + len(name) for name, _ in entries)
    offset = 28 + len(entries) * 10 + names_size
    names, blobs, index = [], [], []
    for i, (name, payload) in enumerate(entries):
        names.append(struct.pack("<HII", len(name), offset, len(payload)) + name.encode() + b"\0")
        index.append(struct.pack("<HII", i, offset, len(payload)))
        blobs.append(payload)
        offset += len(payload)
    return (struct.pack("<4sHH5I", b"NSAC", 2, len(entries), offset,
                        28 + len(entries) * 10 + names_size, len(entries) * 10, names_size, 0)
            + b"".join(index + names + blobs))


def table(rows):
    return struct.pack("<I", len(rows)) + b"".join(rows)


def character(cid=1080, learn=13082, ev=392):
    row = bytearray(d4source.CHAR_STRIDE)
    struct.pack_into("<H", row, 0x194, cid)
    struct.pack_into("<H", row, 0x14, learn)
    struct.pack_into("<H", row, 0x34, 20)
    struct.pack_into("<H", row, 0x1B4, ev)
    struct.pack_into("<H", row, 0x1BA, 1080)
    # A gap must not move the threshold from the original slot.
    struct.pack_into("<H", row, 0x98, 10301)
    struct.pack_into("<H", row, 0x118, 77)
    row[0x292] = 11
    return bytes(row)


def skill(sid):
    row = bytearray(d4source.SKILL_STRIDE)
    struct.pack_into("<I", row, 40, sid)
    row[184:188] = b"Test"
    return bytes(row)


def events(entries):
    offset, offsets = 0, []
    for _, blob in entries:
        offsets.append(offset)
        offset += len(blob)
    count = len(entries)
    return (struct.pack("<I", count) + struct.pack(f"<{count}I", *offsets)
            + struct.pack(f"<{count}I", *(eid for eid, _ in entries)) + b"".join(b for _, b in entries))


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, extra_events=None):
        ev = bytearray(d4source.EVILITY_STRIDE)
        struct.pack_into("<H", ev, 8, 392)
        # Duplicate IDs are deliberate; one occurrence must never replace another.
        root_code = script.Ins(0x0100, [16040200]).encode()
        event_rows = [(12013082, root_code), (16040200, b"\x01\x08"), (16040200, b"\xff\xff")]
        event_rows.extend(extra_events or [])
        path = self.root / d4source.DATABASE.format(lang="EN")
        path.parent.mkdir(parents=True)
        path.write_bytes(nsac([
            ("char.dat", table([character(), character()])),
            ("mskill.dat", table([ev])),
            ("magic.dat", table([skill(13082), skill(301)])),
            ("script.dat", events(event_rows)),
        ]))
        return inv.build_inventory(self.root)

    def test_all_occurrences_retained_and_reference_ambiguity_explicit(self):
        data = self.source()
        chars = [i for i in data["items"] if i["kind"] == "character"]
        self.assertEqual(len(chars), 2)
        self.assertNotEqual(chars[0]["uid"], chars[1]["uid"])
        self.assertEqual(chars[0]["source"]["sha256"], chars[1]["source"]["sha256"])
        collisions = {(c["namespace"], c["identifier"]): c for c in data["collisions"]}
        self.assertEqual(len(collisions[("character", 1080)]["items"]), 2)
        self.assertEqual(len(collisions[("event", 16040200)]["items"]), 2)
        calls = [e for e in data["edges"] if e["relation"] == "calls-event"]
        self.assertEqual(calls[0]["resolution"], "ambiguous")
        self.assertEqual(len(calls[0]["targets"]), 2)
        self.assertTrue(any(e["relation"] == "body-animation" and e["resolution"] == "unresolved" for e in data["unresolved"]))

    def test_skill_frontier_keeps_undecoded_paths_and_missing_skip_modes(self):
        data = self.source()
        frontier = next(x for x in data["skill_frontiers"] if x["source_id"] == 13082)
        normal = frontier["modes"]["normal"]
        self.assertEqual(len(normal["events"]), 3)
        self.assertEqual(len(normal["undecoded_events"]), 1)
        self.assertFalse(normal["closure_complete"])
        self.assertEqual(frontier["modes"]["short"]["wrapper_resolution"], "missing")
        self.assertEqual(frontier["modes"]["mid-skip"]["wrapper_resolution"], "missing")

    def test_weapon_codes_and_thresholds_preserve_sparse_slot_pairing(self):
        data = self.source()
        edges = [e for e in data["edges"] if e["relation"] == "weapon-skill-candidate"]
        self.assertEqual(len(edges), 2)
        self.assertEqual(edges[0]["threshold"], 77)
        self.assertEqual(edges[0]["source_id_candidate"], 301)
        self.assertEqual(edges[0]["confidence"], "inferred")

    def test_dynamic_calls_remain_visible_and_do_not_become_literal_zero(self):
        dynamic = script.Ins(0x0100, [script.Var(99, 2)]).encode()
        data = self.source([(12000301, dynamic)])
        frontier = next(x for x in data["skill_frontiers"] if x["source_id"] == 301)
        refs = frontier["modes"]["normal"]["dynamic_references"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["variable_id"], 99)
        self.assertEqual(refs[0]["targets"], [])

    def test_d4_signatures_are_isolated_from_d5_parser(self):
        original = copy.deepcopy(script.SIGS)
        # D4 7220 operands have widths 1/2/2, unlike D5's 2/2/2.
        raw = events([(123, b"\x72\x20\x00\x05\x00\x65\x00\x00\x97\x00")])
        records = list(inv.event_records(raw))
        self.assertTrue(records[0]["decoded"])
        self.assertTrue(records[0]["byte_exact_roundtrip"])
        self.assertEqual(script.SIGS, original)

    def test_event_and_table_ranges_fail_closed(self):
        with self.assertRaises(ValueError):
            inv.checked_rows(b"\x01\0\0\0", 20)
        raw = bytearray(events([(10, b"\x01\x08")]))
        struct.pack_into("<I", raw, 4, 4)
        with self.assertRaises(ValueError):
            list(inv.event_records(raw))

    def test_archive_duplicate_names_and_bounds(self):
        path = self.root / "pack.dat"
        path.write_bytes(nsac([("same", b"a"), ("same", b"bb")]))
        kind, records = inv.archive_entries(path)
        self.assertEqual(kind, "NSAC-v2")
        self.assertEqual([r[0] for r in records], ["same", "same"])
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            inv.archive_entries(path)

    def test_hash_range_rejects_short_read(self):
        path = self.root / "bytes"
        path.write_bytes(b"abc")
        self.assertEqual(inv.hash_range(path, 1, 2), inv.sha256(b"bc"))
        with self.assertRaises(ValueError):
            inv.hash_range(path, 1, 3)

    def test_save_bytes_excluded_and_no_runtime_acceptance_by_default(self):
        path = self.root / "Data/SAVEDATA/en/savedata.dat"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"private save; not source content")
        data = self.source()
        self.assertEqual(data["excluded"], [dict(path="Data/SAVEDATA/en/savedata.dat", reason="save bytes excluded")])
        self.assertFalse(any(i["source"].get("path") == "Data/SAVEDATA/en/savedata.dat" for i in data["items"]))
        self.assertTrue(all(i["status"]["gameplay"] == "not-tested" for i in data["items"]))
        self.assertTrue(all(i["fidelity"] in ("partial", "blocked") for i in data["items"]))
        json.dumps(data, allow_nan=False)

    def test_target_collisions_are_per_native_namespace_and_check_occupied(self):
        a = dict(uid="one", namespace="body", target_id=50, minimum=1, maximum=100)
        b = dict(a, uid="two")
        c = dict(a, namespace="portrait")
        errors = inv.validate_allocations([a, b, c], {"body": [50]})
        self.assertEqual(sum(e["reason"] == "occupied-target-id" for e in errors), 2)
        self.assertEqual(sum(e["reason"] == "target-id-collision" for e in errors), 1)
        self.assertFalse(any(e["reason"] == "duplicate-source-allocation" for e in errors))
        self.assertEqual(inv.validate_allocations([dict(a, target_id=101)])[0]["reason"], "outside-declared-range")

    def test_progress_requires_matching_hash_evidence_and_separate_native_stages(self):
        data = self.source()
        item = next(i for i in data["items"] if i["kind"] == "skill")
        record = dict(source_sha256=item["source"]["sha256"], evidence=["local acceptance report"],
                      status=dict(conversion="passed", implementation="passed"), fidelity="partial")
        inv.apply_progress(data, {item["uid"]: record})
        self.assertEqual(item["status"]["conversion"], "passed")
        self.assertEqual(item["status"]["gameplay"], "not-tested")
        with self.assertRaisesRegex(ValueError, "stale"):
            inv.apply_progress(data, {item["uid"]: dict(record, source_sha256="old")})
        with self.assertRaisesRegex(ValueError, "independent stages"):
            inv.apply_progress(data, {item["uid"]: dict(record, fidelity="faithfully-reproduced")})


if __name__ == "__main__":
    unittest.main()
