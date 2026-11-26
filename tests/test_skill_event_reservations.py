"""Synthetic event namespace reservations; no assets/native execution."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from d5lib import charstudio, d4expansion, modsys, newclasses, script, skills


def script_bytes(*events):
    sf = script.ScriptFile()
    sf.events = [script.Event(eid, [script.Ins(0x0108)]) for eid in events]
    return sf.to_bytes()


class SkillEventReservationsTests(unittest.TestCase):
    def test_literal_wrapper_custom_and_class_claims_preserve_preflight_set(self):
        with tempfile.TemporaryDirectory() as td:
            mod = modsys.Mod(str(Path(td) / 'Fixture'))
            literal, custom, sid = 12010233, 15900001, 13080
            mod.save_patch('script', 'script.json', {'events': {str(literal): f'event {literal}\n    wait_children\n'}})
            mod.save_patch('skills', 'skills.json', {'skills': {str(sid): {'choreography': custom}},
                'events': {str(custom): f'event {custom}\n    wait_children\n'}, 'effects': {'3001': {}}})
            specs = [dict(family=14010, template=1010, kind='humanoid', sprite_family=1270),
                     dict(family=14510, template=2010, kind='monster', sprite_family=2350)]
            expected = {literal, custom, *(base + sid for base in (12000000, 12100000, 12200000))}
            for spec in specs:
                mod.save_patch('classes', f'class_{spec["family"]}.json', spec)
                expected.update(base + spec['family'] + k for base in newclasses.CLASS_SCRIPTS for k in range(10))
                if spec['kind'] == 'monster':
                    expected.update(base + spec['sprite_family'] + k for base in newclasses.MONSTER_SCRIPTS for k in range(10))
            self.assertEqual(skills.event_ids(mod), expected)
            claims, _ = d4expansion.reservations(None, mod, {})
            self.assertEqual({int(c.split(':')[1]) for c in claims if c.startswith('events:')}, expected)
            self.assertIn('effects:3001', claims)
            reserved = charstudio.all_mod_skill_ids([mod])
            for eid in expected:
                for base in (skills.SKILL_SCRIPT, skills.SKIP_SCRIPT, skills.SKIPPED_SCRIPT):
                    if eid > base:
                        self.assertIn(eid - base, reserved)

    def test_magic_free_id_with_any_occupied_wrapper_is_skipped(self):
        magic = SimpleNamespace(rows=[])
        self.assertEqual(charstudio.free_skill_id(magic, 236), 10231)
        for base in (12000000, 12100000, 12200000):
            with tempfile.TemporaryDirectory() as td:
                mod = modsys.Mod(str(Path(td) / 'Old'))
                eid = base + 10231
                mod.save_patch('script', 'script.json', {'events': {str(eid): f'event {eid}\n    wait_children\n'}})
                taken = charstudio.all_mod_skill_ids([mod])
                self.assertEqual(charstudio.free_skill_id(magic, 236, taken), 10232)
                self.assertEqual(charstudio.free_skill_id(magic, 236, taken | {10232}), 10233)

    def test_original_raw_carrier_and_dynamic_magic_reservations_accumulate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old, completed = [modsys.Mod(str(root / name)) for name in ('Old', 'Completed')]
            old.write_file(skills.SCRIPT, script_bytes(12010231))
            completed.save_patch('db', 'magic.dat.json', {'added': [{'id': 10232}]})
            completed.save_patch('skills', 'skills.json', {'skills': {'10233': {'choreography': 15900000}}})
            self.assertEqual(skills.event_ids(old), set())
            self.assertEqual(skills.event_ids(old, include_raw=True), {12010231})
            claims, _ = d4expansion.reservations(None, old, {})
            self.assertEqual(claims, {'file:script/script.dat'})
            fs = SimpleNamespace(read=lambda path: script_bytes(12110234))
            taken = charstudio.all_mod_skill_ids([old, completed], fs=fs)
            self.assertEqual(charstudio.free_skill_id(SimpleNamespace(rows=[]), 236, taken), 10235)
            self.assertIn(10234, charstudio.all_mod_skill_ids((), fs=fs))

    def test_mismatched_literal_event_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            mod = modsys.Mod(str(Path(td) / 'Wrong'))
            mod.save_patch('script', 'script.json', {'events': {'12010231': 'event 12010232\n    wait_children\n'}})
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                charstudio.all_mod_skill_ids([mod])
