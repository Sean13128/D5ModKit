"""A positional row edit lands on the row the patch names, or it is refused.

The converted Overlord packs address rows by index (they are diffs of a whole table), which is only meaningful
against the table they were diffed from. LIVE12 shipped a fix that treated those indices as ids, and its mirror
image is the real defect class: an index that no longer holds the row the patch meant writes the change onto a
neighbour, silently. `expect` is the guard -- it names the identity of every row the patch edits, so a table that
has moved loses the edit instead of corrupting another row.

Synthetic members: the real schemas, no game data, no install.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from d5lib import database, dbpatch   # noqa: E402


def table(name, ids, key_field=None, **values):
    """A table with the member's real schema, one row per id, in the order given."""
    schema = database.get_schema(name)
    t = database.Table(name, schema)
    t.header = database._read_header(schema, bytes(schema.header_size))
    field = key_field or schema.key or "id"
    for rid in ids:
        row = t.new_row()
        row[field] = rid
        for name_, by_id in values.items():
            row[name_] = by_id.get(rid, 0)
        t.rows.append(row)
    return t


class ExpectGuardTest(unittest.TestCase):
    NAME = "item.dat"

    def patch(self, **extra):
        doc = {"table": self.NAME, "rows": {"2": {"HIT": 42}, "3": {"HIT": 43}}}
        doc.update(extra)
        return doc

    def test_the_edit_lands_when_the_identity_matches(self):
        t = table(self.NAME, [101, 102, 2116, 2117])
        warns = dbpatch.apply_patch(t, self.patch(expect={"by": "id", "rows": {"2": 2116, "3": 2117}}))
        self.assertEqual(warns, [])
        self.assertEqual([r["HIT"] for r in t.rows], [0, 0, 42, 43])
        self.assertEqual([r["id"] for r in t.rows], [101, 102, 2116, 2117])

    def test_a_row_inserted_before_the_patch_refuses_instead_of_hitting_a_neighbour(self):
        """The bug the guard exists for: another mod puts a row in front, every index after it moves."""
        moved = table(self.NAME, [101, 999, 102, 2116, 2117])
        warns = dbpatch.apply_patch(moved, self.patch(expect={"by": "id", "rows": {"2": 2116, "3": 2117}}))
        self.assertEqual([r["HIT"] for r in moved.rows], [0, 0, 0, 0, 0], "nothing may be written")
        self.assertEqual(len(warns), 2)
        self.assertTrue(all("edit refused" in w for w in warns))
        self.assertTrue(any("patch expects 2116" in w for w in warns))

    def test_strict_mode_raises_instead_of_warning(self):
        moved = table(self.NAME, [101, 999, 102, 2116, 2117])
        with self.assertRaises(ValueError):
            dbpatch.apply_patch(moved, self.patch(expect={"by": "id", "rows": {"2": 2116}}), strict=True)
        self.assertEqual([r["HIT"] for r in moved.rows], [0] * 5)

    def test_a_row_the_patch_edits_but_does_not_name_is_refused(self):
        t = table(self.NAME, [101, 102, 2116, 2117])
        warns = dbpatch.apply_patch(t, self.patch(expect={"by": "id", "rows": {"2": 2116}}))
        self.assertEqual([r["HIT"] for r in t.rows], [0, 0, 42, 0])
        self.assertEqual(len(warns), 1)
        self.assertIn("no identity in `expect`", warns[0])

    def test_a_table_that_cannot_be_keyed_refuses_every_edit(self):
        t = table(self.NAME, [101, 102, 2116])
        warns = dbpatch.apply_patch(t, {"table": self.NAME, "rows": {"0": {"HIT": 9}},
                                        "expect": {"by": "no_such_column", "rows": {"0": 101}}})
        self.assertEqual([r["HIT"] for r in t.rows], [0, 0, 0])
        self.assertIn("cannot key this table", warns[0])

    def test_a_repeating_identity_column_is_named_by_ordinal(self):
        """charhelp.dat: 334 rows, 330 ids.  `id#ord` names the nth row that carries an id."""
        t = table("charhelp.dat", [7, 7, 7, 9])
        doc = {"table": "charhelp.dat", "rows": {"1": {"line1_EN": "second"}},
               "expect": {"by": "id#ord", "rows": {"1": "7#2"}}}
        self.assertEqual(dbpatch.apply_patch(t, doc), [])
        self.assertEqual(t.rows[1]["line1_EN"], "second")
        other = table("charhelp.dat", [7, 9, 7])
        warns = dbpatch.apply_patch(other, doc)
        self.assertEqual(other.rows[1]["line1_EN"], "")
        self.assertIn("patch expects '7#2'", warns[0])

    def test_no_expect_means_no_check(self):
        """An authored-by-index patch (the Kit's own packs) is unchanged: it opts in to nothing."""
        t = table(self.NAME, [101, 102, 2116])
        self.assertEqual(dbpatch.apply_patch(t, {"table": self.NAME, "rows": {"0": {"HIT": 5}}}), [])
        self.assertEqual(t.rows[0]["HIT"], 5)


class DiffEmitsExpectTest(unittest.TestCase):
    def test_a_diff_names_the_identity_of_every_row_it_edits(self):
        vanilla = table("item.dat", [101, 102, 103, 104])
        edited = table("item.dat", [101, 102, 103, 104], HIT={103: 7})
        patch = dbpatch.diff_table(vanilla, edited)
        self.assertEqual(patch["rows"], {"2": {"HIT": 7}})
        self.assertEqual(patch["expect"], {"by": "id", "rows": {"2": 103}})
        # the patch is still byte-exact on the table it was diffed from
        probe = table("item.dat", [101, 102, 103, 104])
        self.assertEqual(dbpatch.apply_patch(probe, patch), [])
        self.assertEqual(probe.to_bytes(), edited.to_bytes())

    def test_a_diff_that_repeats_the_identity_column_uses_ordinals(self):
        vanilla = table("charhelp.dat", [7, 7, 9])
        edited = table("charhelp.dat", [7, 7, 9])
        edited.rows[1]["line1_EN"] = "x"
        patch = dbpatch.diff_table(vanilla, edited)
        self.assertEqual(patch["expect"]["by"], "id#ord")
        self.assertEqual(patch["expect"]["rows"], {"1": "7#2"})

    def test_an_insert_only_patch_is_guarded_too(self):
        vanilla = table("item.dat", [101, 102, 103])
        edited = table("item.dat", [101, 102, 999, 103], HIT={102: 11})
        patch = dbpatch.diff_table(vanilla, edited)
        self.assertIn("insert", patch)
        self.assertEqual(patch["expect"]["rows"], {"1": 102})
        moved = table("item.dat", [101, 5, 102, 103])
        warns = dbpatch.apply_patch(moved, patch)
        self.assertEqual(moved.rows[1]["HIT"], 0)
        self.assertTrue(any("edit refused" in w for w in warns))


class KeyColumnTest(unittest.TestCase):
    """`"key": "id"` stays: it is how a pack authored by id (not diffed from a table) says what its keys mean."""

    def test_rows_keys_are_values_of_the_named_column(self):
        t = table("item.dat", [101, 102, 2116, 2117])
        warns = dbpatch.apply_patch(t, {"table": "item.dat", "key": "id",
                                        "rows": {"2117": {"HIT": 43}, "9999": {"HIT": 1}}})
        self.assertEqual([r["HIT"] for r in t.rows], [0, 0, 0, 43])
        self.assertEqual(warns, ["item.dat: no row with id 9999"])

    def test_a_table_that_cannot_be_keyed_refuses_rather_than_falls_back_to_indices(self):
        """Falling back to indices is exactly the silent wrong-row write; the patch must not do it."""
        t = table("SugorokuMapSetting.dat", [0, 1, 2, 3], key_field="unk_000")
        warns = dbpatch.apply_patch(t, {"table": "SugorokuMapSetting.dat", "key": "id",
                                        "rows": {"2": {"unk_068": 5}}})
        self.assertTrue(any("cannot key this table" in w for w in warns))
        self.assertEqual([r["unk_068"] for r in t.rows], [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
