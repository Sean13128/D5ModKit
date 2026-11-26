"""Registry identities use explicit immutable resource/unlock leases."""
import struct
import unittest
from unittest.mock import patch

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from d5lib import exemap, exepatch, newclasses
from test_class_hooks_mapping import fixture, BASE


class RegistryClassTests(unittest.TestCase):
    def setUp(self):
        self.old = exemap.ACTIVE
        self.addCleanup(exemap.use, self.old)
        self.specs = {
            14080: dict(family=14080, kind='humanoid', sprite_family=1360, template=1010),
            14700: dict(family=14700, kind='monster', sprite_family=2340, template=2010)}

    def test_old_flags_unchanged_and_leases_independent_of_order(self):
        for family in newclasses.ALL_FAMILIES:
            for k in range(6):
                self.assertEqual(newclasses.flag_of(family + k),
                                 17283 + 6 * newclasses.ALL_FAMILIES.index(family) + k)
        for k in range(6):
            self.assertEqual(newclasses.flag_of(14080 + k, self.specs), newclasses.flag_of(1360 + k))
        self.assertEqual(newclasses.validate_specs(list(reversed(list(self.specs.values())))), self.specs)

    def test_the_reported_registry_family_14010_builds(self):
        """The installed 1.5.8 kit refused this: `14010 is not in list` from flag_of(14010) -> ALL_FAMILIES.index,
        because only ALL_FAMILIES had unlock flags.  A registry family with a lease must get its own table entry."""
        specs = {14010: dict(family=14010, kind='humanoid', sprite_family=1360, template=1150)}
        newclasses.validate_specs(specs)
        slot = newclasses.ALL_FAMILIES.index(1360)
        for k in range(6):
            self.assertEqual(newclasses.flag_of(14010 + k, specs), 17283 + 6 * slot + k)
        table = newclasses._table_src([14010, 14015], specs)
        self.assertIn(".long 14010, 17409", table)
        self.assertIn(".long 14015, 17414", table)

    def test_a_registry_family_without_a_lease_still_refuses(self):
        with self.assertRaises(ValueError) as caught:
            newclasses.flag_of(14010)
        self.assertIn("slot lease", str(caught.exception))

    def test_normal_allocator_respects_a_registry_lease_even_without_art_files(self):
        from unittest.mock import Mock
        mod = Mock()
        mod.list_files.return_value = []
        with patch.object(newclasses, 'load_specs', return_value=[
                dict(family=14080, kind='humanoid', sprite_family=1270)]):
            self.assertEqual(newclasses.free_family([mod]), 1280)

    def test_rejects_missing_reserved_wrong_type_and_duplicate_leases(self):
        invalid = [
            {14080: dict(family=14080)},
            {20600: dict(family=20600, kind='humanoid', sprite_family=1360)},
            {14080: dict(family=14080, kind='monster', sprite_family=1360)},
            {**self.specs, 1360: dict(family=1360)},
            {14080: self.specs[14080], 14140: dict(family=14140, kind='humanoid', sprite_family=1360)}]
        for specs in invalid:
            with self.subTest(specs=specs), self.assertRaises(ValueError):
                newclasses.validate_specs(specs)
        with self.assertRaises(ValueError):
            newclasses.flag_of(14080)
        with self.assertRaisesRegex(ValueError, 'reserved'):
            newclasses.flag_of(14086, self.specs)
        with self.assertRaisesRegex(ValueError, 'explicit physical'):
            newclasses.fill_class(None, None, 14080, 1010, 'fixture', ['fixture']*6)
        with self.assertRaises(ValueError):
            newclasses.fill_class(None, None, 14080, 2010, 'fixture', ['fixture']*6,
                                  sprite_family=1360)

    def test_high_identity_low_graphics_and_script_namespaces(self):
        s = self.specs[14700]
        self.assertEqual(newclasses.sprite_family(14700, s), 2340)
        self.assertEqual(newclasses.class_kind(14700, s), 'monster')
        # Identity and resource-script event numbers must not be conflated.
        from d5lib import scriptpatch
        class Event:
            def __init__(self, id): self.id = id
        class File:
            def __init__(self, events): self.events = events
        vanilla = File([Event(3100000+2010), Event(12010000+2010)])
        current = File([])
        with patch.object(scriptpatch, 'event_text', side_effect=lambda e, annotate: f'event {e.id}'), \
             patch.object(scriptpatch, 'apply') as apply:
            self.assertEqual(newclasses.add_class_scripts(current, vanilla, {14700: s}), 2)
            self.assertEqual(set(apply.call_args.args[1]['events']), {'3114700', '12012340'})

    def test_registry_generic_sites_keep_native_return_addresses(self):
        raw, mapping, _ = fixture()
        mapping[BASE + 0x200b] = BASE + 0x2800
        mapping[BASE + 0x2018] = BASE + 0x2820
        exemap.use(exemap.Translator('synthetic-moved', mapping, image_end=BASE + 0x5000))
        changed, hooks, counts = newclasses.generic_patch(raw, specs=self.specs)
        self.assertEqual(counts, (1, 0, 1))
        self.assertEqual({h[0] for h in hooks}, {BASE+0x2000, BASE+0x200d})
        result = exepatch.add_hook_section(changed, b'.d5cl', [], native_hooks=hooks)
        pe = pefile.PE(data=result)
        cs = Cs(CS_ARCH_X86, CS_MODE_64)
        for site, _, _, _ in hooks:
            jump = pe.get_data(site-BASE, 5)
            target = site+5+struct.unpack_from('<i', jump, 1)[0]
            decoded = list(cs.disasm(pe.get_data(target-BASE, 120), target))
            targets = {int(i.op_str, 16) for i in decoded if i.mnemonic=='jmp'}
            self.assertIn(site+11, targets)
            self.assertNotIn(BASE+0x2800, targets)
            self.assertNotIn(BASE+0x2820, targets)

    def test_synthetic_save_codec_preserves_high_identity_and_row_index(self):
        from d5lib import savegame
        ids = [f+k for f in (14080, 14700, 23840) for k in range(6)]
        save = savegame.Save.__new__(savegame.Save)
        save.header = bytearray(savegame.HEADER)
        save.header[:len(savegame.MAGIC)] = savegame.MAGIC
        save.state = bytearray(savegame.STATE_SIZE)
        struct.pack_into('<h', save.state, savegame.ARMY_COUNT, len(ids))
        for n, cid in enumerate(ids):
            unit = savegame.Unit(save, n)
            unit.set_class(cid)
            struct.pack_into('<h', save.state, unit.base+savegame.U_ROW, -1)
        self.assertEqual(save.fix_rows(ids), len(ids))
        loaded = savegame.Save.__new__(savegame.Save)
        savegame._parse_into(loaded, save.to_bytes())
        self.assertEqual(loaded.state, save.state)
        self.assertEqual([u.cls for u in loaded.army()], ids)
        self.assertEqual([struct.unpack_from('<h', loaded.state, u.base+savegame.U_ROW)[0]
                          for u in loaded.army()], list(range(len(ids))))


if __name__ == '__main__': unittest.main()
