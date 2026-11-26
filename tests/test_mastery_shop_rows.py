"""SKILLTRAINERCRASH1: no evility row may make the Skill Shop read a JobRank row that does not exist (0x1407CDA94)."""
import unittest
from unittest import mock

from d5lib import charstudio, database, learned


def row(**k):
    return {"id": 218, "kind": 1, "source": 3, "owner": 217, "class_order": 0, "mana_cost": 10000,
            "version_group": 100, **k}


class Faults(unittest.TestCase):
    RANKS = range(1010, 1016)

    def test_character_row_sold_by_mastery(self):
        self.assertEqual(learned.mastery_faults([row()], self.RANKS), [(218, 1, 222)])

    def test_rows_the_shop_never_looks_up(self):
        for k in (dict(source=4), dict(mana_cost=0), dict(version_group=151), dict(kind=2), dict(source=0)):
            self.assertEqual(learned.mastery_faults([row(**k)], self.RANKS), [], k)

    def test_class_rows(self):
        self.assertEqual(learned.mastery_faults([row(owner=1010, class_order=6)], self.RANKS), [])
        self.assertEqual(learned.mastery_faults([row(kind=0, owner=1010, class_order=5)], self.RANKS), [])
        self.assertEqual(learned.mastery_faults([row(kind=0, owner=1010, class_order=7)], self.RANKS), [(218, 0, 1016)])

    def test_zero_key_is_null(self):
        self.assertEqual(learned.mastery_faults([row(kind=0, owner=1, class_order=0)], [0]), [(218, 0, 0)])


class _Row(dict):
    def set(self, k, v):
        self[k] = v

    def to_dict(self):
        return dict(self)


class _Table:
    def __init__(self, rows):
        self.rows = [_Row(r) for r in rows]

    def index_of(self, i):
        return next((n for n, r in enumerate(self.rows) if r["id"] == i), -1)

    def add_row(self, copy_from):
        self.rows.append(_Row(self.rows[copy_from]))
        return self.rows[-1]

    def to_bytes(self):
        return [dict(r) for r in self.rows]


class _Ctx:
    def __init__(self):
        self.out, self.lines = {}, []

    def get(self, path):
        return path.rsplit("/", 1)[1]

    def put(self, path, data):
        self.out[path.rsplit("/", 1)[1]] = data

    def log(self, line):
        self.lines.append(line)


class Guard(unittest.TestCase):
    def run_guard(self, rows):
        tables = {"Skill.dat": _Table(rows), "JobRank.dat": _Table([{"id": i} for i in range(1010, 1016)])}
        ctx = _Ctx()
        with mock.patch.object(database, "load_table", lambda name, data: tables[name]):
            learned._guard_mastery(ctx)
        return ctx

    def test_unique_row_is_repaired(self):
        ctx = self.run_guard([row(), row(id=1016, owner=1010)])
        self.assertEqual([(r["id"], r["source"], r["mana_cost"]) for r in ctx.out["Skill.dat"]],
                         [(218, 4, 0), (1016, 3, 10000)])
        self.assertIn("evility 218", ctx.lines[0])

    def test_clean_table_is_not_written(self):
        self.assertEqual(self.run_guard([row(owner=1010)]).out, {})

    def test_learnable_row_is_refused(self):
        with self.assertRaisesRegex(ValueError, "218"):
            self.run_guard([row(kind=0, class_order=1)])


class Creator(unittest.TestCase):
    def test_new_evility_is_a_characters_own(self):
        table = _Table([row(id=1160, owner=1160, class_order=6)])
        svc = mock.Mock()
        svc.table.return_value = table
        mod = mock.Mock()
        mod.load_patch.return_value = {}
        char = _Row({"id": 217, "evility1": 0, "evility2": 0, "evility3": 0, "evility4": 0})
        with mock.patch.object(charstudio, "set_langs"):
            eid = charstudio.new_evility(svc, mod, char, 1160, "Transform")
        new = table.rows[-1]
        self.assertEqual((new["id"], new["owner"], new["kind"], new["source"], new["mana_cost"]), (eid, 217, 1, 4, 0))
        self.assertEqual(learned.mastery_faults([new], range(1010, 1016)), [])


if __name__ == "__main__":
    unittest.main()
