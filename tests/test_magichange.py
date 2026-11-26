"""Magichange sets: the data contract, the clone, the learn slots, the audit (no game files)."""
import unittest

from d5lib import magichange as mc


class Row(dict):
    """the two APIs the module uses on a real database.Row: mapping access and to_dict()"""
    def to_dict(self):
        return dict(self)

    def set(self, name, value):
        self[name] = value


class Table:
    def __init__(self, rows):
        self.rows = [Row(r) for r in rows]


def single(sid, user, dual=None, sp=8, motion=9, icon=8, name="Single", **kw):
    row = dict(id=sid, skill_group=mc.GROUP, user1=user, user_count=1, sp_cost=sp, motion_type=motion,
               icon=icon, name_EN=name, desc_EN="Magichange:%s" + name, name_JP=name, name_FR=name,
               name_CHN=name, name_KOR=name, desc_JP="Magichange:%s" + name, desc_FR="x",
               desc_CHN="x", desc_KOR="x", power_lv1=100, power_lv10=163, anim_id=600, attack_map=1,
               height_up=12, height_down=12, element=0, effect1_type=1, effect1_value=30)
    if dual:
        row["dual_skill"] = dual
    row.update(kw)
    return row


def pair(sid, user, sp=64, motion=8):
    row = single(sid, user, sp=sp, motion=motion, name="Pair")
    return row


def dual(sid, user, base, sp=8, motion=10, icon=10):
    row = single(sid, user, sp=sp, motion=motion, icon=icon, name="Dual")
    row["base_skill"] = base
    return row


THREE = [single(100, 900, dual=102), pair(101, 900), dual(102, 900, base=100)]
TWO = [single(200, 910, sp=8, motion=8), pair(201, 910)]


class Sets(unittest.TestCase):
    def test_three_row_family(self):
        found = mc.sets(Table(THREE))[900]
        self.assertEqual([found[r]["id"] for r in (mc.ROLE_SINGLE, mc.ROLE_PAIR, mc.ROLE_DUAL)],
                         [100, 101, 102])
        self.assertEqual(mc.shape(Table(THREE), 900), 3)

    def test_two_row_family_without_a_dual(self):
        found = mc.sets(Table(TWO))[910]
        self.assertEqual(found[mc.ROLE_SINGLE]["id"], 200)
        self.assertEqual(found[mc.ROLE_PAIR]["id"], 201)
        self.assertIsNone(found[mc.ROLE_DUAL])
        self.assertEqual(mc.shape(Table(TWO), 910), 2)

    def test_an_unowned_row_is_not_a_set(self):
        self.assertEqual(mc.shape(Table([single(300, 0)]), 0), 1)
        with self.assertRaises(ValueError):
            mc.set_of(Table([single(300, 0)]), 300)

    def test_a_dual_must_point_back(self):
        rows = THREE[:2] + [dual(102, 900, base=999)]
        with self.assertRaises(ValueError):
            mc.set_of(Table(rows), 100)

    def test_a_dual_must_be_motion_10_icon_10(self):
        bad = dual(102, 900, base=100, motion=8, icon=8)
        with self.assertRaises(ValueError):
            mc.set_of(Table(THREE[:2] + [bad]), 100)

    def test_a_row_outside_group_10_is_refused(self):
        self.assertFalse(mc.is_magichange(single(400, 900, skill_group=7)))
        with self.assertRaises(ValueError):
            mc.set_of(Table([single(400, 900, skill_group=7)]), 400)

    def test_trio_needs_all_three(self):
        mc.trio(Table(THREE), 100)
        with self.assertRaises(ValueError):
            mc.trio(Table(TWO), 200)


class Plan(unittest.TestCase):
    def test_clone_rewires_the_links(self):
        names = {mc.ROLE_SINGLE: "A", mc.ROLE_PAIR: "B", mc.ROLE_DUAL: "Twin A"}
        descs = {r: "Magichange:%s" + n for r, n in names.items()}
        out = mc.plan(Table(THREE), 100, ids=[500, 501, 502], names=names, descs=descs, user1=950,
                      levels=(3, 7, 1))
        got = {role: fields for role, fields in out}
        self.assertEqual(got[mc.ROLE_SINGLE]["id"], 500)
        self.assertEqual(got[mc.ROLE_SINGLE]["dual_skill"], 502)
        self.assertEqual(got[mc.ROLE_DUAL]["base_skill"], 500)
        self.assertEqual(got[mc.ROLE_PAIR]["dual_skill"], 0)
        self.assertEqual(got[mc.ROLE_PAIR]["base_skill"], 0)
        self.assertTrue(all(f["user1"] == 950 for f in got.values()))
        self.assertEqual(got[mc.ROLE_SINGLE]["name_EN"], "A")
        self.assertEqual(got[mc.ROLE_DUAL]["name_KOR"], "Twin A")
        # the donor's numbers, animation, area and element are kept
        self.assertEqual(got[mc.ROLE_SINGLE]["anim_id"], 600)
        self.assertEqual(got[mc.ROLE_SINGLE]["power_lv10"], 163)
        self.assertEqual(got[mc.ROLE_DUAL]["name_EN"], "Twin A")

    def test_a_two_row_donor_never_grows_a_dual(self):
        out = mc.plan(Table(TWO), 200, ids=[600, 601],
                      names={mc.ROLE_SINGLE: "A", mc.ROLE_PAIR: "B"},
                      descs={mc.ROLE_SINGLE: "Magichange:%sA", mc.ROLE_PAIR: "Magichange:%sB"},
                      user1=960)
        self.assertEqual([r for r, _f in out], [mc.ROLE_SINGLE, mc.ROLE_PAIR])
        self.assertEqual(dict(out)[mc.ROLE_SINGLE]["dual_skill"], 0)
        with self.assertRaises(ValueError):
            mc.plan(Table(TWO), 200, ids=[600, 601, 602],
                    names={mc.ROLE_SINGLE: "A", mc.ROLE_PAIR: "B", mc.ROLE_DUAL: "C"},
                    descs={}, user1=960)

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ValueError):
            mc.plan(Table(TWO), 200, ids=[600, 600],
                    names={mc.ROLE_SINGLE: "A", mc.ROLE_PAIR: "B"}, descs={}, user1=960)

    def test_insert_index_keeps_the_table_in_order(self):
        table = Table([single(10, 1), single(30, 1), single(40, 1)])
        self.assertEqual(mc.insert_index(table, 20), 1)
        self.assertEqual(mc.insert_index(table, 5), 0)
        self.assertEqual(mc.insert_index(table, 50), 3)
        with self.assertRaises(ValueError):
            mc.insert_index(table, 30)


class Attach(unittest.TestCase):
    def _char(self):
        row = Row({f"learn{k}_skill": 0 for k in range(1, 17)})
        row.update({f"learn{k}_level": 0 for k in range(1, 17)})
        row["learn_count"] = 0
        return row

    def test_slots_fill_in_order_and_count_follows(self):
        row = self._char()
        self.assertEqual(mc.attach(row, [(500, 30), (501, 70)]), [1, 2])
        self.assertEqual(row["learn1_skill"], 500)
        self.assertEqual(row["learn2_level"], 70)
        self.assertEqual(row["learn_count"], 2)
        # re-attaching updates the level instead of adding a slot
        mc.attach(row, [(500, 1)])
        self.assertEqual(row["learn_count"], 2)
        self.assertEqual(row["learn1_level"], 1)

    def test_seventeenth_skill_is_refused(self):
        row = self._char()
        mc.attach(row, [(1000 + n, 1) for n in range(16)])
        with self.assertRaises(ValueError):
            mc.attach(row, [(9999, 1)])


class Audit(unittest.TestCase):
    def test_a_clean_family_passes(self):
        self.assertEqual(mc.check(Table(THREE), [900]), [])

    def test_a_missing_pair_is_reported(self):
        problems = mc.check(Table([single(100, 900, dual=102), dual(102, 900, base=100)]), [900])
        self.assertTrue(any("no 64-SP pair" in p for p in problems), problems)

    def test_a_wrong_sp_cost_is_reported(self):
        rows = [single(100, 900, dual=102, sp=30), pair(101, 900), dual(102, 900, base=100)]
        problems = mc.check(Table(rows), [900])
        self.assertTrue(any("8 SP" in p for p in problems), problems)

    def test_an_unknown_user_is_reported(self):
        self.assertTrue(mc.check(Table(THREE), [12345]))

    def test_learned_ids(self):
        row = Row({f"learn{k}_skill": 0 for k in range(1, 17)})
        row["learn1_skill"] = 20611
        row["learn4_skill"] = 20612
        self.assertEqual(mc.learned_ids(row), [20611, 20612])


if __name__ == "__main__":
    unittest.main()
