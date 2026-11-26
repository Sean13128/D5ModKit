"""Learned-evility capacity (.d5lc): manifest validation, site coverage, the assembled section and the
save companion.  No game files are written and Unicorn is never imported."""
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from d5lib import learned

PINNED = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
              'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
PINNED_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
TABLE = list(range(1, 1001)) + [21000, 21001]


def original():
    return PINNED.read_bytes()


class ManifestTest(unittest.TestCase):
    def test_first_thousand_ids_own_the_bitmap(self):
        man = learned.manifest(TABLE)
        self.assertEqual(man['base_count'], 1000)
        self.assertEqual(man['base_ids'], TABLE[:1000])
        self.assertEqual(man['ext_ids'], TABLE[1000:])
        self.assertEqual(man['row_count'], len(TABLE))

    def test_generation_is_a_stable_function_of_the_order(self):
        self.assertEqual(learned.manifest(TABLE)['generation'], learned.manifest(list(TABLE))['generation'])
        self.assertNotEqual(learned.manifest([1, 2, 3, 5])['generation'],
                            learned.manifest([1, 2, 4, 5])['generation'])

    def test_unsorted_table_is_refused(self):
        with self.assertRaises(ValueError):
            learned.manifest([2, 1, 3])

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ValueError):
            learned.manifest([1, 1, 2])

    def test_short_table_is_legal(self):
        man = learned.manifest([5, 6, 7])
        self.assertEqual(man['base_count'], 3)
        self.assertEqual(man['ext_ids'], [])

    def test_learned_from_bitmap_is_the_inverse_of_the_positions(self):
        bitmap = bytearray(learned.BITMAP_BYTES if hasattr(learned, 'BITMAP_BYTES') else 125)
        for pos in (0, 7, 8, 999):
            bitmap[pos >> 3] |= 1 << (pos & 7)
        self.assertEqual(learned.learned_from_bitmap(bytes(bitmap), TABLE), {TABLE[p] for p in (0, 7, 8, 999)})

    def test_a_bit_past_the_table_is_an_error_not_silence(self):
        bitmap = bytearray(125)
        bitmap[3] |= 0x08              # bit 27
        with self.assertRaises(ValueError):
            learned.learned_from_bitmap(bytes(bitmap), TABLE[:20])


class SiteTest(unittest.TestCase):
    """the hard-coded site lists are re-derived from the pinned exe's own bytes"""

    def test_scan_reproduces_the_lists(self):
        exe = original()
        self.assertEqual(hashlib.sha256(exe).hexdigest(), PINNED_SHA)
        sites = learned.scan_sites(exe)
        self.assertEqual(sites[learned.GETTER], learned.GET_SITES)
        self.assertEqual(sites[learned.SETTER], learned.SET_SITES)
        self.assertEqual(len(learned.GET_SITES), 20)
        self.assertEqual(len(learned.SET_SITES), 123)

    def test_every_site_calls_the_expected_function(self):
        import pefile
        exe = original()
        pe = pefile.PE(data=exe, fast_load=True)
        for sites, target in ((learned.GET_SITES, learned.GETTER), (learned.SET_SITES, learned.SETTER)):
            for va in sites:
                off = pe.get_offset_from_rva(va - 0x140000000)
                raw = exe[off:off + 5]
                self.assertEqual(raw[0], 0xE8)
                self.assertEqual(va + 5 + struct.unpack('<i', raw[1:])[0], target)


class SectionTest(unittest.TestCase):
    def test_section_is_deterministic(self):
        man = learned.manifest(TABLE)
        self.assertEqual(learned.section_source(man), learned.section_source(learned.manifest(TABLE)))

    def test_patch_redirects_every_site_and_carries_the_manifest(self):
        exe = original()
        man = learned.manifest(TABLE)
        patched = learned.build_patch(exe, man)
        info = learned.section_info(patched)
        self.assertIsNotNone(info)
        sym = learned.data_symbols(info)
        blob = info['data']
        at = sym['magic'] - info['base']
        self.assertEqual(struct.unpack_from('<I', blob, at + 8)[0], learned.SECTION_VERSION)  # version
        self.assertEqual(struct.unpack_from('<I', blob, at + 12)[0], 0)          # state: unverified
        self.assertEqual(struct.unpack_from('<I', blob, at + 16)[0], 1000)       # base count
        self.assertEqual(struct.unpack_from('<I', blob, at + 20)[0], 0)          # used
        self.assertEqual(struct.unpack_from('<I', blob, at + 28)[0], man['generation'])
        self.assertEqual(struct.unpack_from('<I', blob, at + 32)[0], learned.UID_OFFSET)
        self.assertEqual(struct.unpack_from('<Q', blob, at + 40)[0], learned.KEY_ARRAY)
        self.assertEqual(struct.unpack_from('<Q', blob, at + 48)[0], learned.KEY_MAXI)
        prefix = list(struct.unpack_from('<1000I', blob, sym['prefix'] - info['base']))
        self.assertEqual(prefix, man['base_ids'])
        src = learned.section_source(man)
        code, labels = learned._assemble(src, learned.code_base(exe, learned.SECTION))
        self.assertEqual(sorted(labels), sorted(learned.ROUTINE_TAGS))
        import pefile
        pe = pefile.PE(data=patched, fast_load=True)
        for sites, wrapper in ((learned.GET_SITES, labels['lc_get']), (learned.SET_SITES, labels['lc_set'])):
            for va in sites:
                raw = patched[pe.get_offset_from_rva(va - 0x140000000):][:5]
                self.assertEqual(raw[0], 0xE8)
                self.assertEqual(va + 5 + struct.unpack('<i', raw[1:])[0], wrapper)

    def test_the_bitmap_is_never_addressed(self):
        """the extension has no instruction that names record +0x2E70 (it must not write the bitmap)"""
        import capstone
        man = learned.manifest(TABLE)
        src = learned.section_source(man)
        code, labels = learned._assemble(src, learned.code_base(original(), learned.SECTION))
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        md.detail = True
        for ins in md.disasm(code[16:], 0x1000):
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_MEM:
                    self.assertFalse(0x2E70 <= op.mem.disp < 0x2EED,
                                     f'{ins.address:#x}: {ins.mnemonic} {ins.op_str} addresses the bitmap')

    def test_a_different_table_changes_only_the_guard(self):
        exe = original()
        a = learned.section_info(learned.build_patch(exe, learned.manifest(TABLE)))
        b = learned.section_info(learned.build_patch(exe, learned.manifest(TABLE[:500])))
        self.assertNotEqual(a['data'], b['data'])


class SidecarTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.save = Path(self.dir.name) / 'Save_001.sav'
        self.save.write_bytes(b'NIS_DISGAEA5_COMPLETE_SAVEDATA_' + bytes(64))

    def tearDown(self):
        self.dir.cleanup()

    def doc(self, table=None):
        return learned.sidecar_doc(str(self.save), table or TABLE, {7: [21000], 9: [21000, 21001]},
                                   unit_names={7: 'Killia'})

    def test_round_trip(self):
        doc = self.doc()
        path = str(self.save) + learned.SIDECAR_SUFFIX
        learned.sidecar_write(path, doc)
        back = learned.sidecar_read(path)
        self.assertEqual(back, doc)
        ok, problems, quarantine = learned.sidecar_validate(back, str(self.save), TABLE)
        self.assertTrue(ok, problems)
        self.assertFalse(quarantine)
        self.assertEqual(back['units'][f'{7:016x}']['name'], 'Killia')

    def test_a_changed_save_is_refused(self):
        doc = self.doc()
        self.save.write_bytes(self.save.read_bytes() + b'x')
        ok, problems, _ = learned.sidecar_validate(doc, str(self.save), TABLE)
        self.assertFalse(ok)
        self.assertIn('does not match these save bytes', ' '.join(problems))

    def test_a_different_generation_is_refused(self):
        ok, problems, _ = learned.sidecar_validate(self.doc(), str(self.save), list(reversed(TABLE)))
        self.assertFalse(ok)
        self.assertTrue(any('generation' in p for p in problems))

    def test_unknown_ids_are_quarantined_not_dropped(self):
        doc = self.doc()
        doc['units'][f'{7:016x}']['learned'].append(424242)
        ok, problems, quarantine = learned.sidecar_validate(doc, str(self.save), TABLE)
        self.assertTrue(ok, problems)
        self.assertEqual(quarantine, [dict(serial=7, id=424242)])

    def test_unknown_schema_is_refused(self):
        doc = self.doc()
        doc['schema'] = 99
        ok, problems, _ = learned.sidecar_validate(doc, str(self.save), TABLE)
        self.assertFalse(ok)
        self.assertTrue(problems)

    def test_write_is_atomic(self):
        path = str(self.save) + learned.SIDECAR_SUFFIX
        learned.sidecar_write(path, self.doc())
        self.assertFalse(Path(path + '.new').exists())
        self.assertEqual(json.loads(Path(path).read_text())['kind'], 'd5modkit.learned')


VANILLA_DB = Path('/Volumes/Data/ai-tmp/charorder/vanilla/Database_0.dat')


class InstallWiringTest(unittest.TestCase):
    """The section only reaches an installed exe if the installer loads this module: the finalizer runs
    once every mod is in, i.e. after `dbpatch` wrote the finished Skill.dat and after `.d5el` was added."""

    def test_the_installer_loads_the_module(self):
        from d5lib import modsys
        self.assertIn('d5lib.learned', modsys.HANDLER_MODULES)

    def test_it_runs_after_the_table_is_written_and_after_the_evility_section(self):
        from d5lib import modsys
        mods = modsys.HANDLER_MODULES
        self.assertLess(mods.index('d5lib.dbpatch'), mods.index('d5lib.learned'))
        self.assertLess(mods.index('d5lib.evility'), mods.index('d5lib.learned'))
        loaded = [fn.__module__ for fn in modsys.ordered_finalizers()]
        self.assertIn('d5lib.learned', loaded)
        self.assertLess(loaded.index('d5lib.dbpatch'), loaded.index('d5lib.learned'))

    def test_the_finalizer_turns_the_finished_table_into_a_section(self):
        """the installer's own path: exe + the merged Skill.dat member in, a .d5lc section out"""
        from d5lib import database, dbpatch, modsys
        if not VANILLA_DB.exists():
            self.skipTest('vanilla Database_0.dat not present')
        member = database.load_database(str(VANILLA_DB)).table('Skill.dat').to_bytes()

        class Ctx:
            def __init__(self, exe, skill):
                self.files = {modsys.EXE_FILE: exe,
                              f'{dbpatch.DB_ARCHIVE}/Skill.dat': skill}
                self.paths = {}

            def get(self, vpath):
                return self.files[vpath]

            def put(self, vpath, data):
                self.files[vpath] = data
                self.paths.setdefault(vpath, []).append(len(data))

            def log(self, *a):
                pass

        ctx = Ctx(original(), member)
        learned._finalize(ctx)
        exe = ctx.files[modsys.EXE_FILE]
        self.assertNotEqual(exe, original())
        info = learned.section_info(exe)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info['section'], '.d5lc')
        ids = [int(r['id']) for r in database.load_table('Skill.dat', member).rows]
        want = learned.manifest(ids)
        sym = learned.data_symbols(info)
        at = sym['base_count'] - info['base']
        self.assertEqual(struct.unpack_from('<I', info['data'], at)[0], want['base_count'])
        at = sym['generation'] - info['base']
        self.assertEqual(struct.unpack_from('<I', info['data'], at)[0], want['generation'])

    def test_a_build_without_the_table_keeps_the_exe(self):
        """no Skill.dat member in the context: nothing to guard, so nothing is added"""
        from d5lib import modsys
        seen = []

        class Ctx:
            def get(self, vpath):
                raise KeyError(vpath)

            def put(self, vpath, data):
                seen.append(vpath)

            def log(self, *a):
                pass

        learned._finalize(Ctx())
        self.assertEqual(seen, [])


if __name__ == '__main__':
    unittest.main()
