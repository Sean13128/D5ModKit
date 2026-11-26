"""D1 skill-table reader contract: layout, known values, cross-edition agreement, refusals."""
import struct
import unittest
from pathlib import Path

from d5lib import d1skill

HD_TABLE = Path('/Volumes/Data/Disgaea 5 Mods data/staging/faithful-source-tables-20261016/d1hd/char_e.dat')
HD_MAGIC = Path('/Volumes/Data/ai-tmp/character-export-work/d1hd-round2/start-40.bin')
PC_SUBDATA = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea PC/SUBDATA.DAT')


def sjis(text, width):
    raw = text.encode('shift_jis')
    return raw + b'\0' * (width - len(raw))


def row(edition, ident, level, power, sp, name, description,
        effect_params=(0, 0, 0, 0, 0), weapon=0, element=0, category=2, weapon_alt=0,
        range_=0, pattern=0, up=12, down=12, effect=(0, 0, 0, 0, 0)):
    layout = d1skill.LAYOUTS[edition]
    name_at, desc_at = layout['name'][0], layout['description'][0]
    header = struct.pack('<4H', ident, level, power, sp)
    out = bytearray(layout['stride'])
    out[0:8] = header
    out[name_at:name_at + (layout['name'][1] - name_at)] = sjis(name, layout['name'][1] - name_at)
    out[desc_at:desc_at + (layout['description'][1] - desc_at)] = sjis(
        description, layout['description'][1] - desc_at)
    numbers = bytes(effect_params) + bytes([weapon, element, category, weapon_alt, range_, pattern,
                                            up, down]) + bytes(effect)
    assert len(numbers) == 18
    out[layout['numbers']:layout['numbers'] + 18] = numbers
    return bytes(out)


def table(edition, rows):
    body = b''.join(rows)
    raw = struct.pack('<II', len(rows), len(rows)) + body
    return raw + b'\0' * ((-len(raw)) % 16)


class ShapeTests(unittest.TestCase):
    def test_reads_the_documented_fields(self):
        raw = table('d1hd', [row('d1hd', 701, 0, 12, 4, 'Fire', 'Fire spell', element=1, category=3)])
        doc = d1skill.read_table(raw, 'd1hd', verify=False)
        self.assertEqual(doc['count'], 1)
        self.assertEqual(doc['stride'], 180)
        self.assertEqual(doc['numbers_offset'], 162)
        fire = doc['rows'][0]
        self.assertEqual((fire['id'], fire['level'], fire['power'], fire['sp']), (701, 0, 12, 4))
        self.assertEqual(fire['name'], 'Fire')
        self.assertEqual(fire['element'], 'fire')
        self.assertEqual(fire['weapon'], 'none')
        self.assertEqual(fire['category'], 'magic')
        self.assertEqual(fire['row_offset'], 8)

    def test_pc_row_width_is_172_and_matches_the_same_record(self):
        raw = table('d1', [row('d1', 201, 1, 5, 8, 'Blade Rush', 'Sword skill', weapon=2)])
        doc = d1skill.read_table(raw, 'd1', verify=False)
        self.assertEqual(doc['stride'], 172)
        self.assertEqual(doc['numbers_offset'], 154)
        self.assertEqual(doc['rows'][0]['weapon'], 'sword')
        self.assertEqual((doc['rows'][0]['level'], doc['rows'][0]['power'],
                          doc['rows'][0]['sp']), (1, 5, 8))

    def test_weapon_element_and_category_labels(self):
        rows = [row('d1hd', 1 + n, 0, 0, 0, 'a', '', weapon=w)
                for n, w in enumerate((1, 2, 3, 4, 5, 6))]
        rows += [row('d1hd', 10 + e, 0, 0, 0, 'b', '', element=e, category=c)
                 for e, c in ((0, 4), (1, 3), (2, 3), (3, 3), (4, 3))]
        doc = d1skill.read_table(table('d1hd', rows), 'd1hd', verify=False)
        self.assertEqual([r['weapon'] for r in doc['rows'][:6]],
                         ['fist', 'sword', 'spear', 'bow', 'gun', 'axe'])
        self.assertEqual([r['element'] for r in doc['rows'][6:]], ['none', 'fire', 'wind', 'ice', 'star'])
        self.assertEqual({r['category'] for r in doc['rows'][6:]}, {'heal', 'magic'})

    def test_refuses_unknown_edition_and_bad_shapes(self):
        with self.assertRaises(ValueError):
            d1skill.read_table(b'', 'd2pc')
        good = table('d1hd', [row('d1hd', 1, 0, 0, 0, 'a', '')])
        with self.assertRaises(ValueError):
            d1skill.read_table(good + b'\0' * 17, 'd1hd', verify=False)
        broken = bytearray(good)
        struct.pack_into('<I', broken, 4, 2)
        with self.assertRaises(ValueError):
            d1skill.read_table(bytes(broken), 'd1hd', verify=False)
        trailing = bytearray(good)
        trailing[-1] = 1
        with self.assertRaises(ValueError):
            d1skill.read_table(bytes(trailing), 'd1hd', verify=False)

    def test_refuses_duplicate_ids(self):
        raw = table('d1hd', [row('d1hd', 7, 0, 0, 0, 'a', ''), row('d1hd', 7, 0, 0, 0, 'b', '')])
        with self.assertRaises(ValueError):
            d1skill.read_table(raw, 'd1hd', verify=False)

    def test_pinned_size_hash_is_enforced_when_asked(self):
        with self.assertRaises(ValueError):
            d1skill.read_table(table('d1hd', [row('d1hd', 1, 0, 0, 0, 'a', '')]), 'd1hd')


@unittest.skipUnless(HD_MAGIC.is_file(), 'retained D1 Complete HD skill table is absent')
class HdTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = d1skill.table(HD_MAGIC, 'd1hd')
        cls.rows = d1skill.by_id(cls.doc)

    def test_pinned_table(self):
        self.assertEqual(self.doc['count'], 285)
        self.assertEqual(self.doc['sha256'],
                         '4dfb1f6d91a86dcafada159d0795d04cb09f53eb3259c7da637d76581a479d5f')

    def test_known_spell_values(self):
        fire, mega, giga = self.rows[701], self.rows[702], self.rows[703]
        self.assertEqual((fire['name'], fire['power'], fire['sp'], fire['element'],
                          fire['category'], fire['level']), ('Fire', 12, 4, 'fire', 'magic', 0))
        self.assertEqual((mega['name'], mega['power'], mega['sp']), ('Mega Fire', 30, 10))
        self.assertEqual((giga['name'], giga['power'], giga['sp']), ('Giga Fire', 60, 25))
        # The SP column is the one an owner can check in game: Fire 4, Mega 10, Giga 25.

    def test_known_weapon_skill_values(self):
        blade = self.rows[201]
        self.assertEqual((blade['name'], blade['level'], blade['power'], blade['sp'],
                          blade['weapon'], blade['element']), ('Blade Rush', 1, 5, 8, 'sword', 'none'))
        self.assertEqual(self.rows[205]['name'], 'Nightsever')
        self.assertEqual(self.rows[206]['name'], 'Dimension Slash')

    def test_laharl_unique_signature_skill(self):
        knuckle = self.rows[1001]
        self.assertEqual((knuckle['name'], knuckle['power'], knuckle['sp'], knuckle['element'],
                          knuckle['category']), ('Blazing Knuckle', 10, 15, 'fire', 'physical'))

    def test_element_column_matches_named_spell_lines(self):
        for element, base in (('fire', 701), ('wind', 711), ('ice', 721), ('star', 731)):
            self.assertEqual({self.rows[base + k]['element'] for k in range(5)}, {element})

    def test_weapon_column_matches_skill_families(self):
        for weapon, base in (('fist', 101), ('sword', 201), ('spear', 301),
                             ('bow', 401), ('gun', 501), ('axe', 601)):
            self.assertEqual({self.rows[base + k]['weapon'] for k in range(6)}, {weapon})

    def test_range_is_only_set_where_the_skill_has_one(self):
        ranged = [r for r in self.doc['rows'] if r['range']]
        self.assertEqual(len(ranged), 13)
        self.assertEqual(self.rows[406]['name'], 'Doppelganger')
        self.assertEqual(self.rows[406]['range'], 4)


@unittest.skipUnless(HD_TABLE.is_file(), 'retained D1 Complete HD character table is absent')
class LearnsetTests(unittest.TestCase):
    def test_laharl_learns_his_three_unique_skills(self):
        raw = HD_TABLE.read_bytes()
        learned = d1skill.learnset(raw, 1, 'd1hd')
        self.assertEqual([(s['skill'], s['level']) for s in learned['learn']],
                         [(1001, 5), (1002, 20), (1003, 50)])

    def test_absent_and_ambiguous_characters_are_refused(self):
        raw = HD_TABLE.read_bytes()
        with self.assertRaises(ValueError):
            d1skill.learnset(raw, 65000, 'd1hd')


@unittest.skipUnless(PC_SUBDATA.is_file(), 'Disgaea PC SUBDATA is absent')
class PcCrossCheckTests(unittest.TestCase):
    def test_pc_edition_agrees_with_the_hd_edition_row_for_row(self):
        raw, provenance = d1skill.disgaea_pc_magic(PC_SUBDATA)
        self.assertEqual(provenance['member'], 41)
        self.assertEqual(provenance['sha256'],
                         '51655b5704f12010d4e2d7b49fee1bce62953654498cbbeeeeed1a68acb1bed5')
        pc = d1skill.read_table(raw, 'd1')
        self.assertEqual(pc['count'], 285)
        if not HD_MAGIC.is_file():
            self.skipTest('HD table absent, nothing to compare')
        hd = d1skill.table(HD_MAGIC, 'd1hd')
        left, right = d1skill.by_id(pc), d1skill.by_id(hd)
        self.assertEqual(list(left), list(right))
        keys = ('name', 'level', 'power', 'sp', 'element', 'weapon', 'category', 'range',
                'pattern', 'up', 'down', 'effect_params', 'effect')
        for ident, row_pc in left.items():
            self.assertEqual({k: row_pc[k] for k in keys},
                             {k: right[ident][k] for k in keys}, f'skill {ident} drifted')


if __name__ == '__main__':
    unittest.main()
