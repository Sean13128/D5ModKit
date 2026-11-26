"""Mapped learn-list plumbing for prepared-source imports (no game data needed)."""
import unittest

from d5lib import nativeimports


class Row(dict):
    def set(self, key, value):
        self[key] = value


def blank_row():
    row = Row({f'learn{i}_skill': 0 for i in range(1, 17)})
    row.update({f'learn{i}_level': 0 for i in range(1, 17)})
    row['learn_count'] = 0
    return row


class SkillPlanTests(unittest.TestCase):
    def test_none_means_nothing_mapped(self):
        self.assertEqual(nativeimports._skill_plan(None, 3), [[], [], []])

    def test_flat_plan_applies_to_every_rank(self):
        plan = nativeimports._skill_plan([(101, 1), (106, 20)], 2)
        self.assertEqual(plan, [[(101, 1), (106, 20)], [(101, 1), (106, 20)]])

    def test_per_rank_plan_requires_one_list_per_rank(self):
        plan = nativeimports._skill_plan([[(101, 1)], []], 2)
        self.assertEqual(plan, [[(101, 1)], []])
        with self.assertRaises(ValueError):
            nativeimports._skill_plan([[(101, 1)]], 2)

    def test_bad_shape_is_refused(self):
        with self.assertRaises(ValueError):
            nativeimports._skill_plan('101,1', 1)


class ApplyLearnTests(unittest.TestCase):
    def test_slots_are_written_in_order_and_the_rest_cleared(self):
        row = blank_row()
        row['learn1_skill'] = 999
        nativeimports._apply_learn(row, [(101, 1), (106, 20)])
        self.assertEqual((row['learn1_skill'], row['learn1_level']), (101, 1))
        self.assertEqual((row['learn2_skill'], row['learn2_level']), (106, 20))
        self.assertEqual(row['learn3_skill'], 0)
        self.assertEqual(row['learn16_skill'], 0)
        self.assertEqual(row['learn_count'], 2)

    def test_empty_plan_clears_a_donor_list(self):
        row = blank_row()
        nativeimports._apply_learn(row, [(101, 1)])
        nativeimports._apply_learn(row, [])
        self.assertEqual([row[f'learn{i}_skill'] for i in range(1, 17)], [0] * 16)
        self.assertEqual(row['learn_count'], 0)

    def test_refuses_duplicates_and_overfull_lists(self):
        with self.assertRaises(ValueError):
            nativeimports._apply_learn(blank_row(), [(101, 1), (101, 5)])
        with self.assertRaises(ValueError):
            nativeimports._apply_learn(blank_row(), [(100 + i, 1) for i in range(17)])


if __name__ == '__main__':
    unittest.main()
