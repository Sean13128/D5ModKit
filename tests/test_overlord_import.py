"""Overlord save import: synthetic saves only (no game data, no real save, no install).

The save is a bytearray with the real offsets, so the test exercises the same code the importer runs:
the learned-evility bitmap at +0x2E70, the char.dat row at +0x2E0A, the six mastery slots at
0x30A4 + 47*24, and the story flags.  The tables are synthetic members with the real schemas.
"""
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from d5lib import database, learned, ordercheck, overlord_import, packedmastery, savegame  # noqa: E402


def member(name, ids, **values):
    schema = database.get_schema(name)
    t = database.Table(name, schema)
    t.header = database._read_header(schema, bytes(schema.header_size))
    for rid in ids:
        row = t.new_row()
        row[schema.key] = rid
        for field, by_id in values.items():
            row[field] = by_id.get(rid, 0)
        t.rows.append(row)
    return t.to_bytes()


class FakeSave:
    """enough of savegame.Save for the importer: state bytes, units by slot, story flags"""

    state_size = savegame.STATE_SIZE

    def __init__(self, slots):
        self.state = bytearray(self.state_size)
        self.slots = list(slots)

    def units(self):
        return [savegame.Unit(self, slot) for slot in self.slots]

    def flag(self, n):
        return bool(self.state[savegame.STORY_FLAGS + (n >> 3)] >> (n & 7) & 1)

    def set_flag(self, n, on=True):
        if on:
            self.state[savegame.STORY_FLAGS + (n >> 3)] |= 1 << (n & 7)

    def learn(self, slot, position):
        off = savegame.ROSTER + slot * savegame.UNIT + overlord_import.LEARNED
        self.state[off + (position >> 3)] |= 1 << (position & 7)

    def bitmap(self, slot):
        off = savegame.ROSTER + slot * savegame.UNIT + overlord_import.LEARNED
        return bytes(self.state[off:off + overlord_import.LEARNED_BYTES])

    def set_class(self, slot, cls, row):
        base = savegame.ROSTER + slot * savegame.UNIT
        struct.pack_into("<I", self.state, base + savegame.U_CLASS, cls)
        struct.pack_into("<h", self.state, base + savegame.U_ROW, row)
        struct.pack_into("<Q", self.state, base + savegame.U_SERIAL, 1000 + slot)
        self.state[base + savegame.U_USED] = 1

    def mastery(self, slot, area):
        base = savegame.ROSTER + slot * savegame.UNIT + overlord_import.MASTERY
        self.state[base:base + len(area)] = area


class ImportTest(unittest.TestCase):
    SRC_SKILL = [10, 20, 30, 20500]         # the Overlord-era table: 4 rows, his content last
    TGT_SKILL = [10, 15, 20, 30, 40, 20500]  # ours: two extra rows *below* his content id

    def setUp(self):
        self.src = member("Skill.dat", self.SRC_SKILL)
        self.tgt = member("Skill.dat", self.TGT_SKILL)
        self.src_char = member("char.dat", [1, 2, 20000])
        self.tgt_char = member("char.dat", [1, 2, 3, 20000])

    def plan(self, **kw):
        return overlord_import.Plan(source_skill=self.src, target_skill=self.tgt,
                                    source_char=self.src_char, target_char=self.tgt_char, **kw)

    def test_learned_positions_are_remapped_through_the_id(self):
        save = FakeSave([0])
        save.set_class(0, 20000, 2)
        save.learn(0, 0)          # id 10 at his position 0 -> our position 0
        save.learn(0, 3)          # id 20500 at his position 3 -> our position 5
        plan = self.plan().apply(save)
        self.assertEqual(save.bitmap(0)[0] & 1, 1)              # bit 0 still id 10
        self.assertEqual(save.bitmap(0)[0] >> 5 & 1, 1)         # bit 5 = id 20500
        self.assertEqual(plan.totals["learned"], 2)
        self.assertEqual(plan.totals["unknown"], 0)
        self.assertEqual(plan.totals["moved"], 1)

    def test_an_id_the_target_table_lacks_is_quarantined_not_dropped(self):
        src = member("Skill.dat", [10, 20, 9999])
        save = FakeSave([0])
        save.set_class(0, 20000, 2)
        save.learn(0, 2)          # id 9999, which the target table does not have
        plan = overlord_import.Plan(source_skill=src, target_skill=self.tgt).apply(save)
        self.assertEqual(plan.unknown_ids, {9999: 1})
        self.assertEqual(save.bitmap(0), bytes(overlord_import.LEARNED_BYTES))
        self.assertIn("quarantine", " ".join(plan.notes()))

    def test_a_position_past_the_bitmap_goes_to_the_store(self):
        src = member("Skill.dat", [10])
        tgt = member("Skill.dat", [1] + list(range(100, 100 + ordercheck.BITSET_CAP)) + [10])
        save = FakeSave([0])
        save.set_class(0, 20000, 2)
        save.learn(0, 0)          # id 10, which now sits at position 1001
        plan = overlord_import.Plan(source_skill=src, target_skill=tgt).apply(save)
        self.assertEqual(plan.totals["overflow"], 1)
        self.assertEqual(plan.overflow_by_serial(), {1000: [10]})
        self.assertEqual(save.bitmap(0), bytes(overlord_import.LEARNED_BYTES))

    def test_class_row_is_recomputed_from_the_class_id(self):
        save = FakeSave([0])
        save.set_class(0, 20000, 2)          # his row for id 20000 is 2, ours is 3
        plan = self.plan().apply(save)
        base = savegame.ROSTER + savegame.U_ROW
        self.assertEqual(struct.unpack_from("<h", save.state, base)[0], 3)
        self.assertEqual(plan.totals["classes_repointed"], 1)

    def test_a_class_the_target_lacks_is_reported_and_left_alone(self):
        save = FakeSave([0])
        save.set_class(0, 7777, 0)
        plan = self.plan().apply(save)
        self.assertEqual(plan.unknown_classes, {7777: 1})
        self.assertEqual(save.units()[0].cls, 7777)
        self.assertIn("does not have", " ".join(plan.notes()))

    def test_mastery_is_left_byte_identical_and_its_families_are_read(self):
        area = packedmastery.encode_pool({1350: (5, 0, 0, 0, 0, 0)},
                                         {1350: (100, 200, 300, 400, 500, 600)})
        save = FakeSave([0])
        save.set_class(0, 20000, 3)
        save.mastery(0, area)
        before = bytes(save.state)
        plan = self.plan(packed_families=[1350]).apply(save)
        self.assertEqual(save.state, bytearray(before))        # nothing rewritten
        self.assertEqual(plan.mastery_families, {1350: 1})
        self.assertEqual(plan.as_dict()["unmappable"]["mastery_families_not_packed"], [])

    def test_a_mastery_family_the_build_does_not_pack_is_reported(self):
        area = packedmastery.encode_pool({14000: (5, 0, 0, 0, 0, 0)},
                                         {14000: (100, 200, 300, 400, 500, 600)})
        save = FakeSave([0])
        save.set_class(0, 20000, 3)
        save.mastery(0, area)
        plan = self.plan(packed_families=[1350])
        plan.apply(save)
        self.assertEqual(plan.as_dict()["unmappable"]["mastery_families_not_packed"], [14000])

    def test_unpacked_mastery_bytes_are_reported_not_interpreted(self):
        save = FakeSave([0])
        save.set_class(0, 20000, 3)
        save.mastery(0, b"\x01" * overlord_import.MASTERY_SIZE)
        plan = self.plan().apply(save)
        self.assertEqual(len(plan.mastery_unpacked), 1)
        self.assertIn("neither all", " ".join(plan.notes()))

    def test_overlord_wip_unlock_flags_are_reported_not_rewritten(self):
        save = FakeSave([0])
        save.set_class(0, 20000, 3)
        save.set_flag(17283)
        before = bytes(save.state)
        plan = self.plan().apply(save)
        self.assertEqual(plan.flags, [17283])
        self.assertEqual(save.state, bytearray(before))

    def test_identity_when_the_tables_are_the_same(self):
        save = FakeSave([0, 1])
        save.set_class(0, 20000, 2)
        save.set_class(1, 1, 0)
        save.learn(0, 1)          # id 20
        before = bytes(save.state)
        plan = overlord_import.Plan(source_skill=self.src, target_skill=self.src,
                                    source_char=self.src_char, target_char=self.src_char).apply(save)
        self.assertEqual(save.state, bytearray(before))
        self.assertEqual(plan.totals["moved"], 0)

    def test_an_unused_unit_cost_nothing(self):
        save = FakeSave([0])
        plan = self.plan().apply(save)
        self.assertEqual(plan.totals["learned"], 0)
        self.assertEqual(plan.totals["unknown"], 0)

    def test_a_bit_beyond_the_source_table_is_reported_as_an_error(self):
        save = FakeSave([0])
        save.set_class(0, 20000, 2)
        save.learn(0, 500)        # his table has 4 rows
        rec = self.plan().apply(save).units[0]
        self.assertIn("bit 500", rec["error"])

    def test_sidecar_document_binds_to_the_save_bytes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "Save_001.sav")
            with open(path, "wb") as f:
                f.write(b"not a real save, only bytes to bind to")
            ids = overlord_import.table_ids(self.tgt)
            doc = learned.sidecar_doc(path, ids, {1000: [20500]})
            ok, problems, quarantine = learned.sidecar_validate(doc, path, ids)
            self.assertTrue(ok, problems)
            self.assertEqual(quarantine, [])
            with open(path, "wb") as f:
                f.write(b"different bytes")
            ok, problems, _ = learned.sidecar_validate(doc, path, ids)
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
