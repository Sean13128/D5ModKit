"""OLWISH1: the Overlord recruit-wish converter (tools/overlord_port/recruit_wishes.py) and the offline save check.
Synthetic rows only: no game data, no save, no install."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "overlord_port"))

from d5lib import wishrecruit   # noqa: E402

import recruit_save_check as RS   # noqa: E402
import recruit_wishes as RW   # noqa: E402


def row(i, **kw):
    r = {"id": i, "name_EN": f"bill {i}", "mana_cost": 10, "difficulty": 3, "vote_modifier": 0}
    for k in ("req", "block", "set", "clear"):
        for n in range(1, 5):
            r[f"{k}_flag{n}"] = 0
    r.update(kw)
    return r


def rows():
    return [row(b) for b in RW.OVERLORD_TABLE]


class Fake:
    def __init__(self, classes=(), flags=()):
        self._c, self._f = classes, set(flags)

    def units(self):
        return [type("U", (), {"cls": c})() for c in self._c]

    def flag(self, n):
        return n in self._f


class ConvertTests(unittest.TestCase):
    def test_rekey(self):
        self.assertEqual([RW.rekey(b) for b in (1049, 1057, 999, 1000, 1999, 2000, 20000, 20500)],
                         [2049, 2057, 999, 2000, 2999, 2000, 20000, 20500])

    def test_table_matches_release_notes(self):
        t = RW.OVERLORD_TABLE
        self.assertEqual(len(t), 14)
        self.assertEqual([t[b][3] for b in sorted(t)],
                         [1199, 1699, 19117, 13502, 13502, 13502, 13502, 13502, 19146, 17127, 1699, 399, 399, 1699])
        self.assertEqual([t[b][1] for b in sorted(t)],
                         [60, 120, 2000, 9999, 9999, 9999, 9999, 9999, 5000, 50, 100, 10, 10, 100])
        self.assertEqual(sorted(b for b in t if t[b][2]), [20000, 20010, 20500])

    def test_convert_rows(self):
        out, rec, rep = RW.convert_rows(rows(), RW.OVERLORD_TABLE)
        self.assertEqual([r["id"] for r in out], list(range(2049, 2058)) + [20000, 20010, 20300, 20310, 20500])
        by = {r["id"]: r for r in out}
        self.assertEqual(by[2049]["req_flag1"], 1199)
        self.assertEqual(by[2052]["req_flag1"], 13502)
        self.assertEqual(by[20300]["req_flag1"], 399)
        self.assertEqual(rec["recruits"]["2057"]["character"], 2615)
        self.assertEqual(rec["recruits"]["2057"]["level"], 5000)
        for b in ("20000", "20010", "20500"):
            self.assertTrue(rec["recruits"][b]["duplicates"])
        self.assertNotIn("duplicates", rec["recruits"]["20300"])
        # the kit's own rules accept it, and every id is >= 2000
        entries = wishrecruit.normalise(rec["recruits"])
        self.assertEqual(len(entries), 14)
        self.assertTrue(all(e[0] >= wishrecruit.MIN_ID for e in entries))
        self.assertEqual({k: v for k, v in rep["bills"][0].items()},
                         {"overlord_bill": 1049, "kit_bill": 2049, "character": 90, "level": 60,
                          "duplicates": False, "req_flag1": 1199})

    def test_other_row_fields_kept(self):
        rs = rows()
        rs[0]["vote_modifier"] = -100
        rs[0]["name_EN"] = "Recruit X"
        out, _, _ = RW.convert_rows(rs, RW.OVERLORD_TABLE)
        self.assertEqual((out[0]["vote_modifier"], out[0]["name_EN"]), (-100, "Recruit X"))
        self.assertEqual(rs[0]["id"], 1049)          # input untouched

    def test_refusals(self):
        with self.assertRaises(ValueError):           # a table entry with no row
            RW.convert_rows(rows()[:-1], RW.OVERLORD_TABLE)
        with self.assertRaises(ValueError):           # a row with no entry
            RW.convert_rows(rows() + [row(1058)], RW.OVERLORD_TABLE)
        rs = rows()
        rs[0]["req_flag1"] = 5
        with self.assertRaises(ValueError):           # never overwrite a flag the row already has
            RW.convert_rows(rs, RW.OVERLORD_TABLE)
        t = dict(RW.OVERLORD_TABLE)
        t[1049] = (90, 10000, False, 1199, "")
        with self.assertRaises(ValueError):           # level outside the kit's range
            RW.convert_rows(rows(), t)
        t = {1049: (90, 5, False, 1, ""), 2049: (91, 5, False, 1, "")}
        with self.assertRaises(ValueError):           # re-keying 1049 would hit an existing 2049
            RW.convert_rows([row(1049), row(2049)], t)

    def test_parse_custom_wishes(self):
        text = "﻿# header\n1052=770,9999,0,13502,baal  # c\n20000 = 20000, 50, 1, 17127\n\n1049=90,60,0\n"
        t = RW.parse_custom_wishes(text)
        self.assertEqual(t[1052][:4], (770, 9999, False, 13502))
        self.assertEqual(t[20000][:4], (20000, 50, True, 17127))
        self.assertEqual(t[1049][:4], (90, 60, False, 0))
        with self.assertRaises(ValueError):
            RW.parse_custom_wishes("1052=770\n")
        with self.assertRaises(ValueError):
            RW.parse_custom_wishes("abc=1,2,0\n")
        with self.assertRaises(ValueError):
            RW.parse_custom_wishes("1052=770,5,maybe\n")

    def test_convert_writes_mod(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.json")
            json.dump({"table": "WishDataBase.dat", "added": rows()}, open(src, "w"))
            out = os.path.join(d, "mod")
            RW.convert(src, out)
            rec = json.load(open(os.path.join(out, "patches", "wishes", "recruit_wishes.json")))
            db = json.load(open(os.path.join(out, "patches", "db", "WishDataBase.dat.json")))
            self.assertEqual(sorted(map(int, rec["recruits"])), [r["id"] for r in db["added"]])
            self.assertEqual(db["table"], "WishDataBase.dat")
            self.assertTrue(os.path.isfile(os.path.join(out, "mod.json")))
            self.assertEqual(wishrecruit.normalise(rec["recruits"])[0][:3], (2049, 90, 60))


class SaveCheckTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.rec, _ = RW.convert_rows(rows(), RW.OVERLORD_TABLE)

    def test_passes_and_reports_gates(self):
        r = RS.check(Fake([1010, 20], flags=[1699, 399]), self.rows, self.rec)
        self.assertTrue(r["pass"])
        self.assertEqual(r["listed_bills_in_save"], [2050, 20010, 20300, 20310, 20500])

    def test_flags_set_by_a_row_fail(self):
        self.rows[3]["set_flag1"] = 77
        self.assertFalse(RS.check(Fake(), self.rows, self.rec)["pass"])

    def test_recruit_class_already_held_fails(self):
        self.assertFalse(RS.check(Fake([770]), self.rows, self.rec)["pass"])

    def test_only_save1_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                RS.run(os.path.join(d, "Save_002.sav"), d, d)


if __name__ == "__main__":
    unittest.main()
