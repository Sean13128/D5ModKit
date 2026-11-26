"""Row insertion in the Kit's table patcher, and the positional references it has to keep honest.

Synthetic members only (the real schemas, no game data, no executable, no install).  The point of
these tests is what the format *promises*: an insert is anchored on a key so two mods compose, an
ambiguous or absent anchor is refused rather than guessed, a positional edit in the same patch never
moves because of an insert, and a row put below a saved bit is refused unless the migration ships.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from d5lib import database, dbpatch, ordercheck   # noqa: E402


def table(name, ids, **values):
    """A table with the member's real schema, one row per id (ids in the order given)."""
    schema = database.get_schema(name)
    t = database.Table(name, schema)
    t.header = database._read_header(schema, bytes(schema.header_size))
    for rid in ids:
        row = t.new_row()
        row[schema.key] = rid
        for field, by_id in values.items():
            row[field] = by_id.get(rid, 0)
        t.rows.append(row)
    return t


def member(name, ids, **values):
    return table(name, ids, **values).to_bytes()


class InsertTest(unittest.TestCase):
    NAME = "item.dat"

    def test_insert_before_a_key_puts_the_row_inside_the_table(self):
        base = member(self.NAME, [2111, 2115, 2121, 2122])
        patch = {"table": self.NAME, "insert": [{"before": 2121, "rows": [{"id": 2116}]}]}
        t = database.load_table(self.NAME, base)
        self.assertEqual(dbpatch.apply_patch(t, patch, strict=True), [])
        self.assertEqual([r["id"] for r in t.rows], [2111, 2115, 2116, 2121, 2122])

    def test_insert_after_a_key(self):
        base = member(self.NAME, [2111, 2115, 2121])
        patch = {"table": self.NAME, "insert": [{"after": 2115, "rows": [{"id": 2116}, {"id": 2117}]}]}
        t = database.load_table(self.NAME, base)
        dbpatch.apply_patch(t, patch, strict=True)
        self.assertEqual([r["id"] for r in t.rows], [2111, 2115, 2116, 2117, 2121])

    def test_anchor_is_a_key_not_an_index(self):
        """The same patch means the same thing after another mod inserted rows above the anchor."""
        base = member(self.NAME, [10, 20, 30])
        other = {"table": self.NAME, "insert": [{"before": 20, "rows": [{"id": 15}]}]}
        patch = {"table": self.NAME, "insert": [{"before": 30, "rows": [{"id": 25}]}]}
        t = database.load_table(self.NAME, base)
        dbpatch.apply_patch(t, other, strict=True)
        dbpatch.apply_patch(t, patch, strict=True)
        self.assertEqual([r["id"] for r in t.rows], [10, 15, 20, 25, 30])

    def test_absent_anchor_is_refused_with_a_reason(self):
        base = member(self.NAME, [10, 20])
        t = database.load_table(self.NAME, base)
        warn = dbpatch.apply_patch(t, {"table": self.NAME,
                                       "insert": [{"before": 99, "rows": [{"id": 15}]}]})
        self.assertTrue(any("no row with id == 99" in w for w in warn), warn)
        self.assertEqual([r["id"] for r in t.rows], [10, 20])

    def test_repeated_anchor_needs_an_occurrence(self):
        base = member("charhelp.dat", [5, 5, 7])
        patch = {"table": "charhelp.dat", "insert": [{"before": 5, "rows": [{"id": 5}]}]}
        t = database.load_table("charhelp.dat", base)
        warn = dbpatch.apply_patch(t, patch)
        self.assertTrue(any("needs `occurrence`" in w for w in warn), warn)
        patch["insert"][0]["occurrence"] = 2
        t = database.load_table("charhelp.dat", base)
        self.assertEqual(dbpatch.apply_patch(t, patch, strict=True), [])
        self.assertEqual(len(t.rows), 4)
        self.assertEqual(t.rows[1]["id"], 5)          # in front of the *second* id 5

    def test_positional_edits_do_not_move_because_of_a_sibling_insert(self):
        base = member(self.NAME, [10, 20, 30], price={30: 5})
        patch = {"table": self.NAME, "rows": {"2": {"price": 7}},
                 "insert": [{"before": 20, "rows": [{"id": 15}]}]}
        t = database.load_table(self.NAME, base)
        dbpatch.apply_patch(t, patch, strict=True)
        self.assertEqual([r["id"] for r in t.rows], [10, 15, 20, 30])
        self.assertEqual(t.rows[3]["price"], 7)        # row 2 of the *baseline*, now at index 3

    def test_missing_rows_key_is_refused(self):
        base = member(self.NAME, [10, 20])
        t = database.load_table(self.NAME, base)
        warn = dbpatch.apply_patch(t, {"table": self.NAME, "insert": [{"rows": [{"id": 15}]}]})
        self.assertTrue(any("needs 'before' or 'after'" in w for w in warn), warn)

    def test_inserted_rows_carry_full_field_values(self):
        base = member(self.NAME, [10, 20])
        full = database.load_table(self.NAME, base).new_row().to_dict()
        full.update({"id": 15, "price": 42, "name_EN": "Test Knife"})
        t = database.load_table(self.NAME, base)
        dbpatch.apply_patch(t, {"table": self.NAME,
                               "insert": [{"after": 10, "rows": [dbpatch._row_values(
                                   _row_from(full))]}]}, strict=True)
        self.assertEqual(t.rows[1]["price"], 42)


def _row_from(values):
    """a Row-like object from a dict, so _row_values can serialise it"""
    return _Fake(values)


class _Fake:
    def __init__(self, values):
        self._values = values

    def to_dict(self):
        return dict(self._values)


class DiffInsertTest(unittest.TestCase):
    """`diff_table` has to say "these rows go here", not "these positions changed"."""

    NAME = "item.dat"

    def test_a_mid_table_insert_becomes_an_insert_entry(self):
        base = member(self.NAME, [10, 20, 30, 40])
        target = database.load_table(self.NAME, base)
        new = target.new_row()
        new["id"] = 25
        target.rows.insert(2, new)
        patch = dbpatch.diff_table(database.load_table(self.NAME, base), target)
        self.assertEqual(patch.get("insert"), [{"before": 30, "rows": [dbpatch._row_values(new)]}])
        applied = database.load_table(self.NAME, base)
        dbpatch.apply_patch(applied, patch, strict=True)
        self.assertEqual(applied.to_bytes(), target.to_bytes())

    def test_a_tail_append_stays_an_append(self):
        base = member(self.NAME, [10, 20])
        target = database.load_table(self.NAME, base)
        target.add_row(id=30)
        patch = dbpatch.diff_table(database.load_table(self.NAME, base), target)
        self.assertNotIn("insert", patch)
        self.assertEqual(len(patch["added"]), 1)

    def test_reordering_is_not_an_insertion(self):
        base = member(self.NAME, [10, 20, 30])
        target = database.load_table(self.NAME, base)
        target.rows[0], target.rows[2] = target.rows[2], target.rows[0]
        patch = dbpatch.diff_table(database.load_table(self.NAME, base), target)
        self.assertNotIn("insert", patch)     # the positional form describes it; tables.audit refuses it

    def test_an_insert_plus_edits_round_trips(self):
        base = member(self.NAME, [10, 20, 30], price={30: 5})
        target = database.load_table(self.NAME, base)
        target.rows[2]["price"] = 9
        new = target.new_row()
        new["id"] = 25
        target.rows.insert(2, new)
        patch = dbpatch.diff_table(database.load_table(self.NAME, base), target)
        applied = database.load_table(self.NAME, base)
        dbpatch.apply_patch(applied, patch, strict=True)
        self.assertEqual(applied.to_bytes(), target.to_bytes())


class PositionalTest(unittest.TestCase):
    """The learned-evility bitmap is indexed by Skill.dat row position, so insertion is not free."""

    def test_appending_rows_costs_no_saved_bit(self):
        self.assertEqual(ordercheck.positional_errors("Skill.dat", [10, 20, 30], [10, 20, 30, 20500]), [])

    def test_inserting_a_row_below_the_cap_is_refused(self):
        err = ordercheck.positional_errors("Skill.dat", [10, 20, 30], [10, 15, 20, 30])
        self.assertTrue(err and "would change meaning" in err[0], err)

    def test_tables_without_a_positional_consumer_are_free(self):
        self.assertEqual(ordercheck.positional_errors("item.dat", [10, 20], [10, 15, 20]), [])

    def test_position_map_reports_moves_and_new_ids(self):
        mapping, unmapped, inserted, shifted = ordercheck.position_map([10, 20, 30], [10, 15, 20])
        self.assertEqual(mapping, {0: 0, 1: 2})
        self.assertEqual(unmapped, [30])
        self.assertEqual(inserted, [15])
        self.assertEqual(shifted, [20])

    def test_remap_bitmap_moves_bits_and_reports_overflow(self):
        old = [10, 20, 30]
        new = [10, 20, 20500, 30]          # 30 moved from position 2 to 3; 20500 is new content
        bitmap = bytearray(125)
        bitmap[2 >> 3] |= 1 << (2 & 7)     # learned: id 30, at old position 2
        out, overflow, unknown, moved = ordercheck.remap_bitmap(bytes(bitmap), old, new)
        self.assertEqual(out[3 >> 3] & (1 << (3 & 7)), 1 << (3 & 7) & 0xFF)
        self.assertEqual((overflow, unknown, moved), ([], [], 1))

    def test_remap_bitmap_sends_rows_past_the_cap_to_the_store(self):
        old = [10, 20]
        new = list(range(1, ordercheck.BITSET_CAP + 1)) + [20]     # 20 lands past the bitmap
        bitmap = bytearray(125)
        bitmap[1 >> 3] |= 1 << (1 & 7)     # learned: id 20 at position 1
        out, overflow, unknown, moved = ordercheck.remap_bitmap(bytes(bitmap), old, new)
        self.assertEqual(overflow, [20])
        self.assertEqual(out, bytes(125))
        self.assertEqual(unknown, [])

    def test_remap_bitmap_quarantines_an_id_the_new_table_lacks(self):
        old = [10, 20]
        new = [10]
        bitmap = bytearray(125)
        bitmap[1 >> 3] |= 1 << (1 & 7)
        out, overflow, unknown, moved = ordercheck.remap_bitmap(bytes(bitmap), old, new)
        self.assertEqual(unknown, [20])


if __name__ == "__main__":
    unittest.main()
