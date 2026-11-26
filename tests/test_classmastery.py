"""Synthetic buffers only; never imports the save reader or uses game files."""
from dataclasses import replace
import hashlib
import struct
import unittest

from d5lib import classmastery as cm

SOURCE = hashlib.sha256(b"synthetic registry source").digest()


class ClassMasteryTests(unittest.TestCase):
    def setUp(self):
        self.registry = cm.Registry((14080, 12510, 13550, 14550, 17520, 22550, 23560, 23840), SOURCE)
        self.native = hashlib.sha256(b"synthetic native state A").digest()
        self.snapshot = cm.Snapshot(17, self.native, (
            cm.Unit(9, 14085, (cm.Progress(14080, (0, 1, 2, 3, 4, 0xffffffff), 0x15),),
                    (0, 1, 65535, 65536, 2**32, 2**63, 0, 2**64-1)),
            cm.Unit(4, 1015, (cm.Progress(23840, (17, 0, 3, 0, 5, 0)),)),
        ))

    def encode(self, snapshot=None):
        return cm.encode(snapshot or self.snapshot, self.registry)

    def decode(self, data, generation=17):
        return cm.decode(data, self.registry, native_digest=self.native, generation=generation)

    def mutated(self, body):
        """Recompute checksum to test structural validation independently."""
        body[cm._PREFIX.size:cm.HEADER_SIZE] = hashlib.sha256(
            body[:cm._PREFIX.size] + body[cm.HEADER_SIZE:]).digest()
        return bytes(body)

    def test_roundtrip_retains_counters_masks_bonuses_and_subclass(self):
        expected = replace(self.snapshot, units=tuple(sorted(self.snapshot.units, key=lambda u: u.serial)))
        self.assertEqual(self.decode(self.encode()), expected)

    def test_canonical_order_does_not_assign_slots(self):
        self.assertEqual(cm.Registry(reversed(self.registry.families), SOURCE).digest, self.registry.digest)
        reversed_snapshot = replace(self.snapshot, units=tuple(reversed(self.snapshot.units)))
        self.assertEqual(self.encode(), self.encode(reversed_snapshot))

    def test_every_game_version_has_independent_state(self):
        spirit = (12510, 13550, 14550, 17520, 22550, 23560)
        entries = tuple(cm.Progress(f, (i + 1,) * 6) for i, f in enumerate(spirit))
        snap = cm.Snapshot(0, self.native, (cm.Unit(1, 23565, entries),))
        result = self.decode(self.encode(snap), snap.generation)
        self.assertEqual([p.counters[0] for p in result.units[0].progress], list(range(1, 7)))

    def test_capacity_exceeds_every_supported_community_base(self):
        families = tuple(f for f in range(10000, 32761, 10) if not 20000 <= f < 22000)
        registry = cm.Registry(families, SOURCE)
        progress = tuple(cm.Progress(f, (f, f+1, f+2, f+3, f+4, f+5), 63) for f in families)
        snap = cm.Snapshot(2**64-1, self.native, tuple(cm.Unit(i+1, 32765, progress) for i in range(128)))
        encoded = cm.encode(snap, registry)
        self.assertEqual(len(encoded), cm.dense_size(len(families)))
        self.assertEqual(cm.decode(encoded, registry, native_digest=self.native, generation=snap.generation), snap)

    def test_pairing_and_registry_changes_are_errors(self):
        data = self.encode()
        with self.assertRaisesRegex(ValueError, "mismatch"):
            cm.decode(data, self.registry, native_digest=hashlib.sha256(b"state B").digest(), generation=17)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            cm.decode(data, cm.Registry(self.registry.families + (14140,), SOURCE), native_digest=self.native, generation=17)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            cm.decode(data, cm.Registry(self.registry.families, bytes(32)), native_digest=self.native, generation=17)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.decode(data, generation=18)

    def test_corruption_header_and_payload_are_detected(self):
        for index in (0, 16, 40, cm.HEADER_SIZE+17, len(self.encode())-1):
            data = bytearray(self.encode()); data[index] ^= 1
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.decode(bytes(data))

    def test_truncation_append_and_size_mismatch(self):
        data = self.encode()
        for n in range(len(data)):
            with self.subTest(size=n), self.assertRaises(ValueError):
                self.decode(data[:n])
        with self.assertRaises(ValueError):
            self.decode(data + b"x")

    def test_future_version_flags_and_reserved_bytes_refused(self):
        for offset, value in ((8, 2), (10, 1), (12, 0)):
            data = bytearray(self.encode()); data[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.decode(self.mutated(data))
        data = bytearray(self.encode()); data[cm.HEADER_SIZE+cm._UNIT.size+29] = 1
        with self.assertRaisesRegex(ValueError, "reserved"):
            self.decode(self.mutated(data))

    def test_duplicate_unknown_and_noncanonical_decode_refused(self):
        data = bytearray(self.encode())
        struct.pack_into("<I", data, cm.HEADER_SIZE+cm._UNIT.size, 14140)
        with self.assertRaisesRegex(ValueError, "unknown"):
            self.decode(self.mutated(data))
        same = replace(self.snapshot, units=(cm.Unit(1, progress=(cm.Progress(14080), cm.Progress(14550))),))
        data = bytearray(self.encode(same))
        start = cm.HEADER_SIZE+cm._UNIT.size
        data[start:start+32], data[start+32:start+64] = data[start+32:start+64], data[start:start+32]
        with self.assertRaisesRegex(ValueError, "noncanonical"):
            self.decode(self.mutated(data))
        struct.pack_into("<I", data, start, 14080)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.decode(self.mutated(data))

    def test_invalid_registry_bases_and_duplicate_refused(self):
        for values in ((14080, 14080), (14081,), (20000,), (21990,), (32770,), (9990,), (True,)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                cm.Registry(values, SOURCE)

    def test_invalid_units_and_subclasses_refused(self):
        for unit in (cm.Unit(0), cm.Unit(True), cm.Unit(2**64), cm.Unit(1, 14086),
                     cm.Unit(1, 14140), cm.Unit(1, 20000), cm.Unit(1, -1),
                     cm.Unit(1, completion_bonuses=(0,) * 7),
                     cm.Unit(1, completion_bonuses=(-1,) * 8)):
            with self.subTest(unit=unit), self.assertRaises(ValueError):
                self.encode(replace(self.snapshot, units=(unit,)))
        for units in ((cm.Unit(1), cm.Unit(1)), tuple(cm.Unit(i+1) for i in range(129))):
            with self.assertRaises(ValueError):
                self.encode(replace(self.snapshot, units=units))

    def test_invalid_progress_never_truncated_or_aliased(self):
        entries = (cm.Progress(14140), cm.Progress(14080, (0,) * 5), cm.Progress(14080, (-1,) * 6),
                   cm.Progress(14080, (2**32,) * 6), cm.Progress(14080, (True,) * 6),
                   cm.Progress(14080, awarded_mask=64))
        for entry in entries:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.encode(replace(self.snapshot, units=(cm.Unit(1, progress=(entry,)),)))
        with self.assertRaises(ValueError):
            self.encode(replace(self.snapshot, units=(cm.Unit(1, progress=(cm.Progress(14080),) * 2),)))

    def test_generation_digest_and_size_arguments_refused(self):
        for snap in (replace(self.snapshot, generation=-1), replace(self.snapshot, generation=True),
                     replace(self.snapshot, native_digest=b"short")):
            with self.assertRaises(ValueError):
                self.encode(snap)
        for args in ((4097, 1), (1, 129), (-1, 1), (True, 1)):
            with self.assertRaises(ValueError):
                cm.dense_size(*args)

    def test_empty_state_and_zero_progress_preserved(self):
        for snap in (cm.Snapshot(0, self.native), cm.Snapshot(1, self.native, (cm.Unit(1),)),
                     cm.Snapshot(1, self.native, (cm.Unit(1, progress=(cm.Progress(14080),)),))):
            self.assertEqual(self.decode(self.encode(snap), snap.generation), snap)


if __name__ == "__main__":
    unittest.main()
