"""Both D4 exact-evility test suites: the import lane's synthetic mod tree and the
breadth lane's reviewed emission. Merged when the two lanes met on the 1.5.8 port.

Synthetic mod tree only - no game files, no exe, no install.
"""
import json
import tempfile
import unittest
from pathlib import Path

from d5lib import d4exact
from d5lib.d4exact import apply_exact, occupied_ids


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class ExactImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.emission = {'exact': [{'d4_id': 8, 'd5_id': 8008}], 'mod_files': {
            'patches/db/Skill.dat.json': {'added': [{'id': 8008, 'name_EN': 'Physical Boost', 'desc_EN': '15%', 'slot_cost': 2}]},
            'patches/evilities/evilities.json': {'evilities': {'8008': {'family': 'dealt', 'effects': [{'value': 15}]}}}}}
        self.profile = [{'innate_evility': {'id': 8}, 'evilities': []},
                        {'innate_evility': {'id': 8}, 'evilities': [{'id': 5}]}]
        write(self.root/'patches/db/Skill.dat.json', {'table': 'Skill.dat', 'added': [{'id': 7000}, {'id': 7001}]})
        write(self.root/'patches/db/char.dat.json', {'rows': {'1': {'evility1': 7000, 'evility2': 7001}}})
        write(self.root/'patches/classes/class_100.json', {'evility_alias': {'7000': 4053, '7001': 999}})

    def test_replaces_only_exact_alias_and_innate(self):
        result = apply_exact(self.root, self.emission, self.profile, 100, {42}, {8: 7000})
        self.assertEqual(result[0]['target_id'], 8008)
        skill = json.loads((self.root/'patches/db/Skill.dat.json').read_text())['added']
        self.assertEqual([x['id'] for x in skill], [7001, 8008])
        self.assertEqual((skill[1]['owner'], skill[1]['source'], skill[1]['kind']), (100, 4, 1))
        char = json.loads((self.root/'patches/db/char.dat.json').read_text())['rows']['1']
        self.assertEqual((char['evility1'], char['evility2']), (8008, 7001))
        descriptor = json.loads((self.root/'patches/classes/class_100.json').read_text())
        self.assertEqual(descriptor['evility_alias'], {'7001': 999})

    def test_omitted_learnable_becomes_owned_common(self):
        profile = [{'innate_evility': {'id': 347}, 'evilities': [{'id': 8, 'mana': 500}]}]
        apply_exact(self.root, self.emission, profile, 216, set())
        row = json.loads((self.root/'patches/db/Skill.dat.json').read_text())['added'][-1]
        self.assertEqual((row['kind'], row['owner'], row['mana_cost']), (0, 216, 500))

    def test_collision_fails_before_write(self):
        before = (self.root/'patches/db/Skill.dat.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'occupied'):
            apply_exact(self.root, self.emission, self.profile, 100, {8008}, {8: 7000})
        self.assertEqual(before, (self.root/'patches/db/Skill.dat.json').read_bytes())

    def test_collects_original_and_disabled_mod_claims(self):
        class Table:
            rows = [{'id': 1}]
        class Mod:
            folder = str(self.root)
            def load_patch(self, kind, name):
                path = Path(self.folder) / 'patches' / kind / name
                return json.loads(path.read_text()) if path.exists() else None
        write(self.root/'patches/evilities/evilities.json', {'evilities': {'8008': {}}})
        write(self.root/'patches/evilities/aliases.json', {'8010': 1})
        found = occupied_ids(Table(), [Mod()])
        self.assertTrue({1, 7000, 7001, 8008, 8010} <= found)

    def test_missing_behavior_fails_before_write(self):
        self.emission['mod_files']['patches/evilities/evilities.json']['evilities'] = {}
        before = (self.root/'patches/db/Skill.dat.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Incomplete emission'):
            apply_exact(self.root, self.emission, self.profile, 100, set(), {8: 7000})
        self.assertEqual(before, (self.root/'patches/db/Skill.dat.json').read_bytes())


EMISSION = {
    'exact': [{'d4_id': 85, 'd5_id': 8085}, {'d4_id': 228, 'd5_id': 8228}],
    'mod_files': {
        'patches/db/Skill.dat.json': {'added': [
            {'id': 8085, 'name_EN': 'Spear Defense', 'source': 6, 'kind': 0},
            {'id': 8228, 'name_EN': 'Last Fortress', 'source': 6, 'kind': 0},
        ]},
        'patches/evilities/evilities.json': {'evilities': {
            '8085': {'rows': [{'kind': 9}]}, '8228': {'rows': [{'kind': 11}]}}},
    },
}

PROFILE = [{
    'innate_evility': {'id': 392, 'mana': 4294967295},
    'evilities': [{'id': 228, 'mana': 1000}, {'id': 85, 'mana': 30000}],
}]


def make_mod(root: Path):
    (root / 'patches/db').mkdir(parents=True)
    (root / 'patches/classes').mkdir(parents=True)
    (root / 'patches/db/Skill.dat.json').write_text(json.dumps({'table': 'Skill.dat', 'added': [
        {'id': 7090, 'name_EN': 'Aegis', 'source': 4, 'owner': 14080},
        {'id': 7091, 'name_EN': 'Last Fortress', 'source': 4, 'owner': 14080},
        {'id': 7093, 'name_EN': 'Spear Defense', 'source': 4, 'owner': 14080},
    ]}))
    (root / 'patches/db/char.dat.json').write_text(json.dumps({'table': 'char.dat', 'added': [
        {'id': 14080, 'name_EN': 'Armor Knight (D4)', 'evility1': 7090, 'evility2': 0}]}))
    (root / 'patches/classes/class_14080.json').write_text(json.dumps(
        {'family': 14080, 'evility_alias': {'7090': 12, '7091': 6082, '7093': 53}}))


class ApplyExactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mod = Path(self.tmp.name) / 'mod'
        make_mod(self.mod)

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self, occupied=(), prior=None):
        return d4exact.apply_exact(self.mod, EMISSION, PROFILE, 14080, set(occupied),
                                   prior if prior is not None else {392: 7090, 228: 7091, 85: 7093})

    def rows(self):
        return {r['id']: r for r in json.loads(
            (self.mod / 'patches/db/Skill.dat.json').read_text())['added']}

    def test_exact_rows_take_ownership_and_aliases_go(self):
        receipt = self.apply()
        self.assertEqual([r['d4_id'] for r in receipt], [85, 228])
        rows = self.rows()
        self.assertNotIn(7091, rows)
        self.assertNotIn(7093, rows)
        self.assertIn(7090, rows, 'an adapted evility must keep its alias')
        self.assertEqual(rows[8085]['owner'], 14080)
        self.assertEqual(rows[8085]['source'], 4)
        self.assertEqual(rows[8228]['mana_cost'], 1000)
        behaviors = json.loads((self.mod / 'patches/evilities/evilities.json').read_text())['evilities']
        self.assertEqual(sorted(behaviors), ['8085', '8228'])

    def test_references_are_rebound_to_the_exact_rows(self):
        self.apply()
        char = json.loads((self.mod / 'patches/db/char.dat.json').read_text())['added'][0]
        self.assertEqual(char['evility1'], 7090)
        descriptor = json.loads((self.mod / 'patches/classes/class_14080.json').read_text())
        self.assertEqual(descriptor['evility_alias'], {'7090': 12})

    def test_innate_evility_costs_no_slot(self):
        emission = {'exact': [{'d4_id': 392, 'd5_id': 8392}],
                    'mod_files': {'patches/db/Skill.dat.json': {'added': [
                        {'id': 8392, 'name_EN': 'Aegis', 'source': 6, 'kind': 1}]},
                        'patches/evilities/evilities.json': {'evilities': {'8392': {'rows': []}}}}}
        receipt = d4exact.apply_exact(self.mod, emission, PROFILE, 14080, set(), {392: 7090})
        self.assertTrue(receipt[0]['innate'])
        self.assertEqual(self.rows()[8392]['slot_cost'], 0)
        self.assertNotIn(7090, self.rows())

    def test_innate_exact_row_is_equipped_when_the_slot_was_empty(self):
        # A D4 unique with no reviewed mapping for its innate: the donor path emits
        # no slot value, so the exact row must still reach the character row.
        (self.mod / 'patches/db/char.dat.json').write_text(json.dumps({'table': 'char.dat', 'added': [
            {'id': 14080, 'name_EN': 'Des X (D4)', 'evility1': 0, 'evility2': 0,
             'evility3': 0, 'evility4': 0, 'evility_count': 0}]}))
        emission = {'exact': [{'d4_id': 392, 'd5_id': 8392}],
                    'mod_files': {'patches/db/Skill.dat.json': {'added': [
                        {'id': 8392, 'name_EN': 'Aegis', 'source': 6, 'kind': 1}]},
                        'patches/evilities/evilities.json': {'evilities': {'8392': {'rows': []}}}}}
        d4exact.apply_exact(self.mod, emission, PROFILE, 14080, set(), {})
        char = json.loads((self.mod / 'patches/db/char.dat.json').read_text())['added'][0]
        self.assertEqual(char['evility1'], 8392)
        self.assertEqual(char['evility_count'], 1)

    def test_innate_exact_row_keeps_another_familys_row_untouched(self):
        (self.mod / 'patches/db/char.dat.json').write_text(json.dumps({'table': 'char.dat', 'added': [
            {'id': 14080, 'name_EN': 'Des X (D4)', 'evility1': 0},
            {'id': 14140, 'name_EN': 'Someone else', 'evility1': 0}]}))
        emission = {'exact': [{'d4_id': 392, 'd5_id': 8392}],
                    'mod_files': {'patches/db/Skill.dat.json': {'added': [
                        {'id': 8392, 'name_EN': 'Aegis', 'source': 6, 'kind': 1}]},
                        'patches/evilities/evilities.json': {'evilities': {'8392': {'rows': []}}}}}
        d4exact.apply_exact(self.mod, emission, PROFILE, 14080, set(), {})
        rows = json.loads((self.mod / 'patches/db/char.dat.json').read_text())['added']
        self.assertEqual(rows[1]['evility1'], 0)

    def test_occupied_target_is_refused(self):
        with self.assertRaises(ValueError):
            self.apply(occupied={8085})

    def test_missing_prior_alias_is_refused(self):
        with self.assertRaises(ValueError):
            self.apply(prior={228: 6099})  # 6099 is not a row in the staged mod

    def test_vanilla_and_other_families_untouched(self):
        self.apply()
        rows = self.rows()
        self.assertEqual(rows[7090]['owner'], 14080)


if __name__ == '__main__':
    unittest.main()
