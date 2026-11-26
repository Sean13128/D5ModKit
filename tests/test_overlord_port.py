"""OLCOMPAT offline tools: synthetic tests, no game data, no executable, no install.

The point of these tests is the *decisions*: a re-ordered table must be refused rather than
half-applied, a repeated key must downgrade the member to non-composable, Overlord's `taken`
reduction must come out negative, a multiplier effect must be refused instead of silently mapped,
and two hook ranges that share bytes must never be reported as compatible.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools", "overlord_port")
sys.path.insert(0, ROOT)
sys.path.insert(0, TOOLS)

from d5lib import database   # noqa: E402

import arbitrate   # noqa: E402
import effects     # noqa: E402
import package     # noqa: E402
import tables      # noqa: E402

IMAGE = 0x140000000


def table_bytes(name, ids, **values):
    """A minimal member with the real schema, one row JSON per id."""
    schema = database.get_schema(name)
    table = database.Table(name, schema)
    table.header = database._read_header(schema, bytes(schema.header_size))
    for rid in ids:
        row = table.new_row()
        row[schema.key] = rid
        for field, values_by_id in values.items():
            row[field] = values_by_id.get(rid, 0)
        table.rows.append(row)
    return table.to_bytes()


class RoundTripTest(unittest.TestCase):
    NAME = "Curry.dat"

    def _bytes(self, ids, **kw):
        return table_bytes(self.NAME, ids, **kw)

    def test_identical_is_a_no_op(self):
        data = self._bytes([1, 2, 3])
        result = tables.audit(self.NAME, data, data)
        self.assertTrue(result.convertible, result.reason)
        self.assertEqual((result.changed_rows, result.added_rows), (0, 0))

    def test_changed_and_added_rows_are_reported(self):
        base = self._bytes([1, 2, 3])
        target = tables.database.load_table(self.NAME, base)
        target.rows[1]["price"] = 999
        target.add_row(**{"id": 4, "price": 5})
        result = tables.audit(self.NAME, base, target.to_bytes())
        self.assertTrue(result.convertible, result.reason)
        self.assertEqual(result.changed_rows, 1)
        self.assertEqual(result.added_rows, 1)
        self.assertEqual(result.added_ids, [4])

    def test_key_reorder_is_refused(self):
        base = self._bytes([1, 2, 3])
        target = tables.database.load_table(self.NAME, base)
        target.rows[0]["id"], target.rows[1]["id"] = 2, 1
        result = tables.audit(self.NAME, base, target.to_bytes())
        self.assertEqual(result.status, tables.REFUSED)
        self.assertIn("row key/order changes", result.reason)

    def test_truncation_is_refused(self):
        base = self._bytes([1, 2, 3])
        target = tables.database.load_table(self.NAME, base)
        target.delete_row(2)
        result = tables.audit(self.NAME, base, target.to_bytes())
        self.assertEqual(result.status, tables.REFUSED)

    def test_repeated_key_is_not_composable(self):
        base = self._bytes([1, 1, 2])                 # the table itself repeats ids (charhelp)
        target = tables.database.load_table(self.NAME, base)
        target.rows[1]["price"] = 7
        result = tables.audit(self.NAME, base, target.to_bytes())
        self.assertTrue(result.convertible, result.reason)
        self.assertEqual(result.status, tables.UNKEYED)
        self.assertTrue(result.duplicate_keys)
        self.assertFalse(result.composable)


class EffectsTest(unittest.TestCase):
    def _convert(self, ini_text, skill_rows=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "evilities.ini")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ini_text)
            return effects.convert(path, skill_rows)

    def test_sign_and_new_lane_and_refusals(self):
        ini = ("[6314 Damage Taken]\nenabled=1\neffect=damage_taken_reduction\nvalue=Fixed:30\n"
               "[20500 Vengeance]\nenabled=1\neffect=permanent_revenge\n"
               "[20310 Squad]\nenabled=1\neffect=stat_per_squad_unit\nvalue=Fixed:3\n"
               "[6311 Ailment]\nenabled=1\neffect=ailment_infliction\nvalue=Fixed:30\n"
               "[1040 Range]\nenabled=1\neffect=magic_range\nmagic=all\nvalue=Fixed:2\n")
        data, verdicts = self._convert(ini)
        rows = data["evilities"]
        self.assertEqual(rows["6314"][0]["family"], "taken")
        self.assertEqual(rows["6314"][0]["effects"][0]["value"], -30)      # sign flipped
        self.assertEqual(rows["20500"][0], {"family": "permanent_revenge"})
        self.assertEqual(rows["20310"][0]["effects"][0]["per"], "squad")
        self.assertNotIn("6311", rows)                                     # multiply vs add: refused
        self.assertIn("1040", rows)                                        # magic=all is no filter
        verdict_by_id = {v["id"]: v["verdict"] for v in verdicts}
        self.assertEqual(verdict_by_id[20500], "new-lane")
        self.assertEqual(verdict_by_id[6311], "refused")

    def test_values_come_from_the_table_row(self):
        ini = ("[6307 A]\nenabled=1\neffect=damage_dealt_percent\nvalue=ValueA\n"
               "[6307 B]\nenabled=1\neffect=damage_taken_reduction\nvalue=ValueB\n")
        with tempfile.TemporaryDirectory() as tmp:
            name = "Skill.dat"
            data = table_bytes(name, [6307])
            table = database.load_table(name, data)
            table.rows[0]["value1"] = 12
            table.rows[0]["value2"] = 7
            path = os.path.join(tmp, "evilities.ini")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ini)
            out, _verdicts = effects.convert(path, database.load_table(name, table.to_bytes()))
        self.assertEqual(out["evilities"]["6307"][0]["effects"][0]["value"], 12)
        self.assertEqual(out["evilities"]["6307"][1]["effects"][0]["value"], -7)

    def test_disabled_and_unknown_are_named(self):
        ini = ("[1 Off]\nenabled=0\neffect=damage_dealt_percent\nvalue=Fixed:1\n"
               "[2 Nope]\nenabled=1\neffect=not_an_effect\n")
        data, verdicts = self._convert(ini)
        self.assertEqual(data["evilities"], {})
        self.assertEqual([v["verdict"] for v in verdicts], ["disabled", "refused"])


class SiteParseTest(unittest.TestCase):
    def test_declarations_and_install_calls(self):
        text = ("#define POWER_HOOK_RVA 0x001F6AA8u\n#define POWER_HOOK_STOLEN_LEN 5u\n"
                "void f(void){ d5_hook_install(base, 0x1C62A0u, p_unlock, 13u, 0, 0); }\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "01_declarations.c")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            sites = arbitrate.parse_overlord_sites(path, source_dir=tmp)
        got = {s["name"]: (s["va"], s["len"]) for s in sites}
        self.assertEqual(got["POWER_HOOK"], (IMAGE + 0x1F6AA8, 5))
        self.assertEqual(got["hook_install@0x1c62a0"], (IMAGE + 0x1C62A0, 13))


class CompareTest(unittest.TestCase):
    def _sites(self, *specs):
        return [{"owner": o, "name": n, "va": IMAGE + va, "len": ln,
                 "function": (IMAGE + fn, IMAGE + fn + 0x100) if fn else None}
                for o, n, va, ln, fn in specs]

    def test_exact_overlap_is_not_compatible(self):
        sites = self._sites(("kit", ".d5fi", 0x1A0880, 5, 0x1A0880),
                            ("overlord", "PORTRAIT", 0x1A0880, 14, 0x1A0880))
        out = arbitrate.compare(sites)
        self.assertEqual([o["verdict"] for o in out], ["needs-arbitration"])
        self.assertEqual(out[0]["kind"], "partial-overlap")     # 5 bytes inside his 14
        same = self._sites(("kit", ".d5id", 0x29F753, 6, 0x29F753),
                           ("overlord", "CHARHELP", 0x29F753, 6, 0x29F753))
        self.assertEqual(arbitrate.compare(same)[0]["kind"], "exact-overlap")

    def test_containment_is_partial_overlap(self):
        sites = self._sites(("kit", "sp_drain_per_turn", 0x552083, 5, None),
                            ("overlord", "SP_DRAIN_HOOK", 0x552080, 11, None))
        out = arbitrate.compare(sites)
        self.assertEqual(out[0]["verdict"], "duplicate-effect")   # same effect, overlapping bytes
        self.assertEqual(out[0]["kind"], "partial-overlap")

    def test_same_function_only_is_ordered_interaction(self):
        sites = self._sites(("kit", ".d5id", 0x15DBFF, 5, 0x15DBF0),
                            ("overlord", "OVERLOAD_ID_RESOLVER", 0x15DBF0, 12, 0x15DBF0))
        out = arbitrate.compare(sites)
        self.assertEqual([o["verdict"] for o in out], ["ordered-interaction"])

    def test_disjoint_sites_are_silent(self):
        sites = self._sites(("kit", ".d5c4", 0x4552F1, 13, 0x454B10),
                            ("overlord", "OTHER", 0x7CD9C0, 5, 0x7CD9C0))
        self.assertEqual(arbitrate.compare(sites), [])


class FeatureSplitTest(unittest.TestCase):
    """One mod per feature: nothing may be dropped, and a member can feed two kinds in one mod."""

    def test_every_row_lands_in_exactly_one_mod(self):
        patches = {"char.dat": {"table": "char.dat", "rows": {"3": {"base_HP": 9}},
                                "added": [{"id": 20000}, {"id": 20500}]},
                   "HABIT.dat": {"table": "HABIT.dat", "rows": {"1": {"level_cap": 200000}}},
                   "item.dat": {"table": "item.dat", "insert": [{"before": 2121, "rows": [{"id": 2116}]}]},
                   "Skill.dat": {"table": "Skill.dat", "rows": {"7": {"value1": 5}},
                                 "added": [{"id": 6307}]}}
        feats, rebalance = package.split_features(patches)
        self.assertEqual([r["id"] for r in feats["Overlord Character - Majin"]["char.dat"]["added"]], [20500])
        self.assertEqual([r["id"] for r in feats["Overlord Character - Battle Suit"]["char.dat"]["added"]],
                         [20000])
        self.assertEqual(feats["Overlord Innocent Renames"]["HABIT.dat"]["rows"], {"1": {"level_cap": 200000}})
        self.assertEqual(feats["Overlord Items"]["item.dat"]["insert"][0]["before"], 2121)
        self.assertEqual(feats["Overlord Evilities"]["Skill.dat"]["added"], [{"id": 6307}])
        self.assertEqual(rebalance["char.dat"]["rows"], {"3": {"base_HP": 9}})
        self.assertEqual(rebalance["Skill.dat"]["rows"], {"7": {"value1": 5}})
        self.assertNotIn("item.dat", rebalance)

    def test_a_member_can_feed_two_kinds_in_one_mod(self):
        """Curry.dat gives one added row and some retuned rows to the same mod; both must survive."""
        patches = {"Curry.dat": {"table": "Curry.dat", "rows": {"0": {"desc_EN": "x"}},
                                 "added": [{"id": 12}]}}
        feats, rebalance = package.split_features(patches)
        part = feats["Overlord Curry"]["Curry.dat"]
        self.assertEqual(part["added"], [{"id": 12}])
        self.assertEqual(part["rows"], {"0": {"desc_EN": "x"}})
        self.assertNotIn("Curry.dat", rebalance)

    def test_nothing_is_left_behind(self):
        patches = {"magic.dat": {"table": "magic.dat", "rows": {"1": {"power": 5}},
                                 "added": [{"id": 40300}]}}
        feats, rebalance = package.split_features(patches)
        got = (len(feats["Overlord Specials"]["magic.dat"]["added"]) +
               len(rebalance["magic.dat"]["rows"]))
        self.assertEqual(got, 2)

    def test_the_install_order_puts_rebalance_last(self):
        self.assertEqual(package.MOD_ORDER[-1], package.REBALANCE_NAME)
        self.assertEqual(len(package.MOD_ORDER), len(package.FEATURES) + 1)
        self.assertIn("Overlord Innocent Renames", package.MOD_ORDER)


if __name__ == "__main__":
    unittest.main()
