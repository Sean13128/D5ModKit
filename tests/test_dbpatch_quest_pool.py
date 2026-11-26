"""QBOARD1: the hidden-row pool must cover the highest progress slot the board can be asked to scan."""
import unittest
from d5lib import dbpatch


class Row(dict):
    def set(self, k, v):
        self[k] = v


class Table:
    def __init__(self, rows):
        self.rows = rows

    def add_row(self, copy_from=0):
        r = Row(self.rows[copy_from])
        self.rows.append(r)
        return r


class PoolTest(unittest.TestCase):
    def test_board_scans_a_quest_on_the_last_slot(self):
        rows = [Row(id=i + 1, sort_order=i, prereq_quest1=0) for i in range(516)]
        rows.append(Row(id=600, sort_order=dbpatch.QUEST_SLOTS - 1, prereq_quest1=0))
        t = Table(rows)
        warn = dbpatch.check_quest_slots(t)
        self.assertEqual(warn, [])
        self.assertGreaterEqual(len(t.rows), dbpatch.QUEST_SLOTS)   # row count covers slot 1023
        self.assertTrue(all(r["id"] < 2000 for r in t.rows))


if __name__ == "__main__":
    unittest.main()
