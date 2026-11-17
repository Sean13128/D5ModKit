"""The character bank: export / import one unit on two synthetic saves (no game, no real save).

The saves are bytearrays with the real offsets, so the test runs the same code that runs on
a real save: the record at ROSTER + slot * UNIT, the serial at +0x3060, the roster index at +0x2E31,
the class and its row at +0x2E04 / +0x2E0A, the five items at +0x10, the mastery counters, the learned
bitmap at +0x2E70, and the game's next-serial dword at 0x5A7F60.
"""
import json
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from d5lib import savegame, unitbank  # noqa: E402

ROWS = list(range(1, 200)) + [570]       # a char.dat: rows are the sorted positions of these ids


class FakeSave:
    """the part of savegame.Save the bank uses"""

    def __init__(self, slots=(), army=0, reserve=0, uid=1):
        self.state = bytearray(savegame.STATE_SIZE)
        struct.pack_into("<h", self.state, savegame.ARMY_COUNT, army)
        struct.pack_into("<h", self.state, savegame.RESERVE_COUNT, reserve)
        unitbank.set_uid_next(self, uid)
        for i in range(savegame.SLOTS):
            self.state[savegame.ROSTER + i * savegame.UNIT + savegame.U_INDEX] = i
        for slot, spec in slots:
            self.put(slot, **spec)

    # --- the same accessors savegame.Save has
    army_count = property(lambda self: struct.unpack_from("<h", self.state, savegame.ARMY_COUNT)[0])
    reserve_count = property(lambda self: struct.unpack_from("<h", self.state, savegame.RESERVE_COUNT)[0])

    def army(self):
        return [savegame.Unit(self, i) for i in range(max(0, self.army_count))]

    def reserve(self):
        return [savegame.Unit(self, i) for i in range(savegame.SLOTS - max(0, self.reserve_count),
                                                       savegame.SLOTS)]

    def units(self):
        return self.army() + self.reserve()

    # --- building one
    def put(self, slot, name="Unit", cls=10, level=1, serial=1, squad=-1, group=0xFF, item=0):
        b = savegame.ROSTER + slot * savegame.UNIT
        st = self.state
        struct.pack_into("<I", st, b + savegame.U_USED, 1)
        struct.pack_into("<I", st, b + savegame.U_CLASS, cls)
        struct.pack_into("<h", st, b + savegame.U_ROW, ROWS.index(cls))
        struct.pack_into("<H", st, b + savegame.U_LEVEL, level)
        struct.pack_into("<Q", st, b + savegame.U_SERIAL, serial)
        struct.pack_into("<h", st, b + savegame.U_SQUAD, squad)
        st[b + savegame.U_GROUP] = group
        st[b + savegame.U_INDEX] = slot
        raw = name.encode("utf-8")[:0x2F]
        st[b + savegame.U_NAME:b + savegame.U_NAME + len(raw)] = raw
        for w in range(10):                                    # weapon mastery: level + aptitude
            o = b + savegame.U_WEAPONS + w * savegame.WEAPON_SIZE
            st[o + 4], st[o + 6] = 3 + w, 100 + w
        struct.pack_into("<I", st, b + 0x2E70, item)           # the learned-bitmap word, a marker
        st[b + unitbank.ITEMS:b + unitbank.ITEMS + 4] = struct.pack("<I", 0x1111 + slot)
        return slot

    def record(self, slot):
        b = savegame.ROSTER + slot * savegame.UNIT
        return bytes(self.state[b:b + savegame.UNIT])

    def index_bytes(self):
        return bytes(self.state[savegame.ROSTER + i * savegame.UNIT + savegame.U_INDEX]
                     for i in range(savegame.SLOTS))


def two_saves():
    """two saves that both hold a unit with serial 7 — the collision an import must survive"""
    a = FakeSave(slots=[(0, dict(name="Killia", cls=10, level=9999, serial=1)),
                        (1, dict(name="Valvatorez", cls=570, level=500, serial=7, squad=3, group=2))],
                 army=2, uid=12033)
    b = FakeSave(slots=[(0, dict(name="Seraphina", cls=80, level=300, serial=7))], army=1, uid=9)
    return a, b


class ExportTest(unittest.TestCase):
    def test_export_holds_the_whole_record(self):
        a, _ = two_saves()
        e = unitbank.export_unit(a, 1)
        self.assertEqual(e["name"], "Valvatorez")
        self.assertEqual(e["class"], 570)
        self.assertEqual(e["level"], 500)
        self.assertEqual(e["serial"], 7)
        self.assertEqual(bytes.fromhex(e["record"]), a.record(1))
        self.assertEqual(len(bytes.fromhex(e["record"])), savegame.UNIT)

    def test_export_is_json_safe(self):
        a, _ = two_saves()
        doc = unitbank.bank_doc([])
        unitbank.bank_add(doc, a, 0)
        self.assertEqual(json.loads(json.dumps(doc))["units"][0]["name"], "Killia")

    def test_blank_slot_is_refused(self):
        a, _ = two_saves()
        with self.assertRaises(ValueError):
            unitbank.export_unit(a, 5)
        with self.assertRaises(ValueError):
            unitbank.export_unit(a, savegame.SLOTS)

    def test_extra_learning_travels_with_the_unit(self):
        a, _ = two_saves()
        e = unitbank.export_unit(a, 1, extra_learned={7: [5001, 5002, 5001]}, sha="ab" * 32)
        self.assertEqual(e["learned_extra"], [5001, 5002])
        self.assertEqual(e["from_save"], "ab" * 32)


class ImportTest(unittest.TestCase):
    def test_round_trip_on_another_save(self):
        a, b = two_saves()
        e = unitbank.export_unit(a, 1)
        out = unitbank.import_unit(b, e, rows=ROWS)
        self.assertEqual(out["slot"], 1)                        # the end of B's army
        self.assertEqual(b.army_count, 2)
        u = savegame.Unit(b, 1)
        self.assertEqual((u.name, u.cls, u.level), ("Valvatorez", 570, 500))
        self.assertEqual(u.squad, -1)                           # the old squad is gone
        self.assertEqual(u.group, 0xFF)
        self.assertEqual(b.state[u.base + savegame.U_INDEX], 1)
        self.assertEqual(unitbank.verify(b), [])

    def test_every_byte_except_the_readdressed_ids_matches(self):
        a, b = two_saves()
        e = unitbank.export_unit(a, 1)
        unitbank.import_unit(b, e, rows=ROWS)
        src, dst = a.record(1), b.record(1)
        skip = set()
        for off, n in ((savegame.U_SERIAL, 8), (savegame.U_INDEX, 1), (savegame.U_SQUAD, 2),
                       (savegame.U_GROUP, 1), (savegame.U_ROW, 2)):
            skip |= set(range(off, off + n))
        diff = [i for i in range(savegame.UNIT) if src[i] != dst[i] and i not in skip]
        self.assertEqual(diff, [])                              # items, mastery, bitmap, name all exact

    def test_serial_is_taken_from_the_saves_own_counter(self):
        a, b = two_saves()
        e = unitbank.export_unit(a, 1)                          # serial 7, like B's own first unit
        out = unitbank.import_unit(b, e, rows=ROWS)
        self.assertEqual(out["serial"], 10)                     # B's counter + 1 (the game pre-increments), not A's 7
        self.assertEqual(unitbank.uid_next(b), 10)
        self.assertEqual(savegame.Unit(b, 0).serial, 7)          # B's own unit untouched

    def test_counter_is_kept_above_every_serial_in_use(self):
        a, b = two_saves()
        unitbank.set_uid_next(b, 7)                             # a counter left behind by an earlier edit
        first = unitbank.import_unit(b, unitbank.export_unit(a, 1), rows=ROWS)
        self.assertEqual(first["serial"], 8)                    # 7 is in use: skipped
        second = unitbank.import_unit(b, unitbank.export_unit(a, 0), rows=ROWS)
        self.assertEqual(second["serial"], 9)
        self.assertEqual(unitbank.verify(b), [])

    def test_class_row_is_readdressed_to_the_target_table(self):
        a, b = two_saves()
        e = unitbank.export_unit(a, 1)
        rows = [c for c in ROWS if c != 570] + [570]            # a char.dat that sorts 570 last
        out = unitbank.import_unit(b, e, rows=sorted(rows))
        self.assertEqual(savegame.Unit(b, 1).cls, 570)
        self.assertEqual(struct.unpack_from("<h", b.state, savegame.Unit(b, 1).base + savegame.U_ROW)[0],
                         sorted(rows).index(570))
        self.assertTrue(out["warnings"])

    def test_unknown_class_is_imported_with_a_warning(self):
        a, b = two_saves()
        e = unitbank.export_unit(a, 1)
        out = unitbank.import_unit(b, e, rows=[c for c in ROWS if c != 570])
        self.assertIsNone(out["row"])
        self.assertTrue(any("not in this save's char.dat" in w for w in out["warnings"]))

    def test_missing_subclass_is_warned(self):
        a, b = two_saves()
        base = savegame.ROSTER + 1 * savegame.UNIT
        struct.pack_into("<I", a.state, base + unitbank.SUBCLASS, 4000)
        e = unitbank.export_unit(a, 1)
        out = unitbank.import_unit(b, e, rows=ROWS)
        self.assertTrue(any("subclass 4000" in w for w in out["warnings"]))
        a2, b2 = two_saves()
        struct.pack_into("<I", a2.state, base + unitbank.SUBCLASS, 10)           # a subclass the target has: no warning
        out = unitbank.import_unit(b2, unitbank.export_unit(a2, 1), rows=ROWS)
        self.assertFalse(any("subclass" in w for w in out["warnings"]))

    def test_index_bytes_stay_in_slot_order(self):
        a, b = two_saves()
        unitbank.import_unit(b, unitbank.export_unit(a, 1), rows=ROWS)
        self.assertEqual(b.index_bytes(), bytes(range(savegame.SLOTS)))

    def test_other_units_are_not_touched(self):
        a, b = two_saves()
        before = b.record(0)
        unitbank.import_unit(b, unitbank.export_unit(a, 1), rows=ROWS)
        self.assertEqual(b.record(0), before)

    def test_full_roster_is_refused(self):
        a, b = two_saves()
        struct.pack_into("<h", b.state, savegame.ARMY_COUNT, 100)
        struct.pack_into("<h", b.state, savegame.RESERVE_COUNT, 28)
        with self.assertRaises(ValueError):
            unitbank.import_unit(b, unitbank.export_unit(a, 1), rows=ROWS)

    def test_a_slot_inside_the_roster_is_only_overwritten_at_the_end_of_the_army(self):
        a, _ = two_saves()
        c = FakeSave(slots=[(0, dict(name="Killia", serial=1)), (1, dict(name="Someone", serial=2))],
                     army=2, uid=50)
        with self.assertRaises(ValueError):
            unitbank.import_unit(c, unitbank.export_unit(a, 1), rows=ROWS, slot=1)
        out = unitbank.import_unit(c, unitbank.export_unit(a, 1), rows=ROWS, slot=2)
        self.assertEqual(out["slot"], 2)
        self.assertEqual(savegame.Unit(c, 1).name, "Someone")
        self.assertEqual(savegame.Unit(c, 2).name, "Valvatorez")

    def test_keep_ids_refuses_a_serial_another_unit_has(self):
        a, b = two_saves()
        e = unitbank.export_unit(a, 1)                          # serial 7, and B's slot 0 is serial 7
        with self.assertRaises(ValueError):
            unitbank.import_unit(b, e, rows=ROWS, keep_ids=True)

    def test_keep_ids_reinserts_into_its_own_save(self):
        a, _ = two_saves()
        e = unitbank.export_unit(a, 1)
        # what the game's Dismiss leaves behind: the record blanked, the counts unchanged
        b = savegame.ROSTER + 1 * savegame.UNIT
        a.state[b:b + savegame.UNIT] = bytes(savegame.UNIT)
        a.state[savegame.ROSTER + (savegame.SLOTS - 1) * savegame.UNIT + savegame.U_INDEX] = savegame.SLOTS - 1
        out = unitbank.import_unit(a, e, rows=ROWS, slot=savegame.SLOTS - 1, keep_ids=True)
        self.assertEqual(out["serial"], 7)
        self.assertEqual(savegame.Unit(a, savegame.SLOTS - 1).name, "Valvatorez")


class VerifyTest(unittest.TestCase):
    def test_verify_passes_on_a_good_save(self):
        a, b = two_saves()
        self.assertEqual(unitbank.verify(a), [])
        self.assertEqual(unitbank.verify(b), [])

    def test_verify_finds_a_duplicate_serial(self):
        a, _ = two_saves()
        a.put(1, name="Copy", cls=570, serial=1)                 # same serial as slot 0
        self.assertTrue(any("names slots" in p for p in unitbank.verify(a)))

    def test_verify_finds_a_wrong_index(self):
        a, _ = two_saves()
        a.state[savegame.ROSTER + savegame.U_INDEX] = 5
        self.assertTrue(any("index is 5" in p for p in unitbank.verify(a)))

    def test_verify_finds_a_counter_left_behind(self):
        a, _ = two_saves()
        unitbank.set_uid_next(a, 2)                             # below the serial 7 in slot 1
        self.assertTrue(any("below the highest" in p for p in unitbank.verify(a)))


if __name__ == "__main__":
    unittest.main()
