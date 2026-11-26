"""Source class descriptions and the independent pending-help overlay; synthetic only."""
import struct
import tempfile
from types import SimpleNamespace
import unittest

from d5lib import database, newclasses
from d5lib.sourceimports import _d4_class_help


class ClassHelpTests(unittest.TestCase):
    def test_creation_uses_all_source_lines(self):
        lines = ['A sturdy warrior.', 'Close-combat specialist.', 'Weapon Forte: Sword']
        original, displayed, desc = _d4_class_help(lines)
        self.assertEqual(original, lines)
        self.assertEqual(displayed, lines)
        self.assertEqual(desc, 'A sturdy warrior. Close-combat specialist. Weapon Forte: Sword')

    def test_pending_abilities_do_not_replace_a_help_line(self):
        # PT1029 W3: the pending list used to overwrite line 3 with "D4 skills/Evilities pending; see GAPS."
        # and that literal shipped in 45 class packs, showing on the recruiter wheel as leftover pilot text.
        lines = ['One', '', 'Three']
        original, displayed, desc = _d4_class_help(lines, [{'status': 'placeholder'}])
        self.assertEqual(lines, ['One', '', 'Three'])
        self.assertEqual(original, lines)
        self.assertEqual(displayed, lines)
        self.assertEqual(desc, 'One Three')

    def test_missing_description_is_plain_and_explicit(self):
        original, _, desc = _d4_class_help([])
        self.assertEqual(original, ['', '', ''])
        self.assertEqual(desc, 'Class description unavailable.')
        self.assertFalse(any(line.strip() for line in original))

    def test_nontext_or_extra_lines_are_rejected(self):
        for lines in ([None], ['a'] * 4):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                _d4_class_help(lines)

    def test_pool_writer_keeps_full_utf8_and_character_count(self):
        desc = _d4_class_help(['Étoile ' * 60, '戦士', 'Weapon Forte: Sword'])[2]
        table = database.load_table('StringListDataBase.dat', struct.pack('<I', 0))
        row = table.new_row()
        row.set('id', newclasses.DESC_BASE)
        for lang in newclasses.LANGS:
            if 'name_' + lang in row:
                row.set('name_' + lang, desc, truncate=True)
        table.rows.append(row)
        encoded = table.to_bytes()
        result = database.load_table('StringListDataBase.dat', encoded).rows[0]
        self.assertEqual(result['name_EN'], desc)
        self.assertEqual(result['name_EN_len'], len(desc))
        self.assertIn(desc.encode('utf-8') + b'\0', encoded)

    def test_normal_spec_writer_roundtrips_only_recruitment_text(self):
        spec = dict(family=14080, template=1080, sprite_family=1270, kind='humanoid',
                    hire_desc=_d4_class_help(['A defender.', '', 'Weapon Forte: Spear'])[2])
        with tempfile.TemporaryDirectory() as root:
            mod = SimpleNamespace(patches_dir=root)
            newclasses.save_spec(mod, spec)
            self.assertEqual(newclasses.load_specs(mod), [spec])

    def test_description_map_uses_exact_source_family_and_string_id(self):
        text = newclasses._desc_src([(14080, newclasses.DESC_BASE)])
        self.assertIn('.long 14080, 41000', text)
        self.assertTrue(text.endswith('.long 0, 0'))


if __name__ == '__main__':
    unittest.main()
