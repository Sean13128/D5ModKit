"""EVCAP3: the learned-evility store's save/load persistence.

Two levels, both offline and both without Unicorn:
  * the Python side (section assembly, the companion's format, publish/rotate/refusal rules, the plan that
    turns a companion into store pairs);
  * the C side, compiled for the host from the *same* d5lib/native/d5learn.inc.c the Windows runtime
    builds (evility/evcap3_host.c), driven against the real assembled `.d5lc` section with a synthetic PE
    image.  That is the code path the game runs: guard, store, sha256, JSON, rotation, refusals.

No game file is written: the "save" the harness hashes is a scratch copy.
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from d5lib import learned

PINNED = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
              'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
PINNED_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
HERE = Path(__file__).resolve().parents[1]
KIT = HERE
TABLE = list(range(1, 1001)) + [21000, 21001]
EXT = TABLE[1000:]


def original():
    return PINNED.read_bytes()


def slot_file(payload=b'',
              header_text=b"NIS_DISGAEA5_COMPLETE_SAVEDATA_",
              block_magic=0xE5B2688ACB279CA6):
    """the bytes data_save_io_make_header 0x1407436D0 writes for one slot.

    Its 0x1C0-byte header is the text above with every byte nibble-transformed (``((~b) << 4) | (b >> 4)``,
    which turns the strncpy'd NULs into 0xF0), and the encoded block that follows starts with the container
    magic untransformed.  Checked against real Save_001.sav / AutoSave.sav (EVCAP4-REPORT.md); the runtime
    refuses to bind a companion to anything that does not start this way.
    """
    enc = lambda b: (((~b) & 0xFF) << 4 | (b >> 4)) & 0xFF
    head = bytes(enc(c) for c in header_text) + b'\xf0'
    head += b'\xf0' * (0x1C0 - len(head))
    assert len(head) == 0x1C0
    return head + struct.pack('<Q', block_magic) + payload


def section_blob(table=None):
    """the assembled section bytes (what the installer puts in the exe), for the host harness"""
    man = learned.manifest(table or TABLE)
    src = learned.section_source(man)
    code, labels = learned._assemble(src, learned.code_base(original(), learned.SECTION))
    return code, labels, man


class SectionTest(unittest.TestCase):
    def test_patch_redirects_the_save_and_load_sites(self):
        exe = original()
        man = learned.manifest(TABLE)
        patched = learned.build_patch(exe, man)
        info = learned.section_info(patched)
        self.assertEqual(info['section'], '.d5lc')
        import pefile
        pe = pefile.PE(data=patched, fast_load=True)
        code, labels, _ = section_blob()
        for sites, target, wrapper in ((learned.GET_SITES, learned.GETTER, labels['lc_get']),
                                       (learned.SET_SITES, learned.SETTER, labels['lc_set']),
                                       (learned.SAVE_SITES, learned.MAKE_HEADER, labels['lc_save_relay']),
                                       (learned.LOAD_SITES, learned.DECODE_SLOT, labels['lc_load_relay'])):
            for va in sites:
                raw = patched[pe.get_offset_from_rva(va - 0x140000000):][:5]
                self.assertEqual(raw[0], 0xE8, hex(va))
                self.assertEqual(va + 5 + struct.unpack('<i', raw[1:])[0], wrapper, hex(va))
                self.assertEqual(va + 5 + struct.unpack('<i', exe[pe.get_offset_from_rva(va - 0x140000000):][1:5])[0],
                                 target, 'the original call must target the game function')

    def test_site_lists_are_rederived_from_the_pinned_exe(self):
        exe = original()
        self.assertEqual(hashlib.sha256(exe).hexdigest(), PINNED_SHA)
        relays = learned.scan_relay_sites(exe)
        # saving is bound to the game's own slot writer, at both of its call sites
        self.assertEqual(tuple(relays[learned.MAKE_HEADER]), learned.SAVE_SITES)
        self.assertEqual(tuple(relays[learned.DECODE_SLOT]), learned.LOAD_SITES)
        # the site EVCAP3 used is a DeleteFileW call (INTEG12 finding 1) and is no longer redirected
        self.assertIn(learned.DELETE_SITE, relays[learned.WRITE_SLOT])
        self.assertNotIn(learned.DELETE_SITE, learned.SAVE_SITES)
        sites = learned.scan_sites(exe)
        self.assertEqual(sites[learned.GETTER], learned.GET_SITES)
        self.assertEqual(sites[learned.SETTER], learned.SET_SITES)

    def test_the_store_is_sized_for_the_whole_plan(self):
        cap = learned.STORE_CAPACITY
        self.assertEqual(cap & (cap - 1), 0, 'the mask must be a power of two')
        self.assertGreaterEqual(learned.STORE_MAX_USED, 128 * 768,
                               'room for 128 roster slots with 768 extension evilities each')
        self.assertLessEqual(learned.STORE_MAX_USED, cap * 3 // 4)
        self.assertGreaterEqual(cap - learned.STORE_MAX_USED, cap // 4, 'a quarter of the table stays free')
        self.assertLessEqual(learned.PROBE * 4, cap // 16, 'a probe must stay far below the table size')

    def test_the_data_block_ends_where_the_runtime_expects_it(self):
        patched = learned.build_patch(original(), learned.manifest(TABLE))
        info = learned.section_info(patched)
        sym = learned.data_symbols(info)
        blob = info['data']
        at = sym['magic'] - info['base']
        self.assertEqual(struct.unpack_from('<Q', blob, at)[0], learned.MAGIC)
        self.assertEqual(struct.unpack_from('<I', blob, at + 8)[0], learned.SECTION_VERSION)
        self.assertEqual(struct.unpack_from('<I', blob, at + 24)[0], learned.STORE_CAPACITY)
        self.assertEqual(struct.unpack_from('<Q', blob, at + 40)[0], learned.KEY_ARRAY)
        self.assertEqual(struct.unpack_from('<Q', blob, at + 48)[0], learned.KEY_MAXI)
        self.assertEqual(struct.unpack_from('<Q', blob, at + 56)[0], learned.SAVE_DIR)
        for field in ('fn_put', 'fn_clear'):
            fn = struct.unpack_from('<Q', blob, sym[field] - info['base'])[0]
            self.assertGreaterEqual(fn, info['code'])
            self.assertLess(fn, info['base'] + len(blob))
        self.assertLessEqual(sym['end'] - info['base'], len(blob),
                             'the data block must not overrun its section')

    def test_an_installed_section_keeps_its_generation(self):
        patched = learned.build_patch(original(), learned.manifest(TABLE))
        info = learned.section_info(patched)
        sym = learned.data_symbols(info)
        self.assertEqual(struct.unpack_from('<I', info['data'], sym['generation'] - info['base'])[0],
                         learned.manifest(TABLE)['generation'])


class InstallTest(unittest.TestCase):
    """the installer must actually run the section builder: an unregistered finalizer builds nothing"""

    def test_the_learned_finalizer_is_registered_and_ordered(self):
        from d5lib import modsys
        self.assertIn("d5lib.learned", modsys.HANDLER_MODULES)
        order = list(modsys.HANDLER_MODULES)
        at = order.index("d5lib.learned")
        # it reads the finished Skill table, so it must sort after every table writer and before the runtime
        for writer in ("d5lib.dbpatch", "d5lib.skills", "d5lib.outfits", "d5lib.newclasses", "d5lib.masteryext"):
            self.assertLess(order.index(writer), at, writer)
        self.assertLess(at, order.index("d5lib.runtime"))
        self.assertLess(at, order.index("d5lib.grips"))
        # and the module really registers a finalizer when it is imported
        import d5lib.learned  # noqa: F401
        self.assertIn("d5lib.learned", [fn.__module__ for fn in modsys.FINALIZERS])


class SidecarV2Test(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.save = Path(self.dir.name) / 'Save_001.sav'
        self.save.write_bytes(slot_file(bytes(64)))

    def tearDown(self):
        self.dir.cleanup()

    def doc(self):
        return learned.sidecar_doc(str(self.save), TABLE, {7: [21000], 9: [21000, 21001]},
                                   quarantine=[dict(serial=9, id=424242)])

    def test_schema_2_carries_the_quarantine_and_validates(self):
        doc = self.doc()
        self.assertEqual(doc['schema'], 2)
        self.assertEqual(doc['quarantine'], [dict(serial=9, id=424242)])
        ok, problems, quarantine = learned.sidecar_validate(doc, str(self.save), TABLE)
        self.assertTrue(ok, problems)
        self.assertEqual(quarantine, [dict(serial=9, id=424242)])

    def test_a_schema_1_companion_still_loads(self):
        doc = self.doc()
        doc['schema'] = 1
        del doc['quarantine']
        ok, problems, _ = learned.sidecar_validate(doc, str(self.save), TABLE)
        self.assertTrue(ok, problems)

    def test_publish_keeps_the_previous_generation(self):
        path = str(self.save) + learned.SIDECAR_SUFFIX
        first = self.doc()
        learned.sidecar_publish(path, first)
        second = self.doc()
        second['units'][f'{7:016x}']['learned'].append(21001)
        learned.sidecar_publish(path, second)
        self.assertEqual(json.loads(Path(path).read_text()), second)
        self.assertEqual(json.loads(Path(path + learned.SIDECAR_PREV).read_text()), first)
        self.assertFalse(Path(path + '.new').exists())

    def test_plan_separates_extension_ids_native_ids_and_unknowns(self):
        doc = self.doc()
        doc['units'][f'{7:016x}']['learned'] = [21000, 42]      # 42 is table position 41: the bitmap's
        pairs, native, unknown = learned.sidecar_plan(doc, TABLE)
        self.assertEqual(pairs, {7: [21000], 9: [21000, 21001]})
        self.assertEqual(native, [dict(serial=7, id=42)])
        self.assertEqual(unknown, [dict(serial=9, id=424242)])

    def test_the_plan_round_trips_through_the_document(self):
        pairs = {5: [21001], 6: [21000, 21001]}
        doc = learned.sidecar_doc(str(self.save), TABLE, pairs)
        back, native, unknown = learned.sidecar_plan(doc, TABLE)
        self.assertEqual(back, pairs)
        self.assertFalse(native or unknown)


class HostRuntimeTest(unittest.TestCase):
    """the real d5learn.inc.c, compiled for the host, driving a real companion file"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='evcap3host_')
        cls.bin = os.path.join(cls.tmp, 'evcap3_host')
        env = dict(os.environ)
        cc = shutil.which('cc') or shutil.which('clang') or 'cc'
        subprocess.run([cc, '-O1', '-g', '-DD5LEARN_HOST', '-o', cls.bin,
                        str(KIT / 'evility' / 'evcap3_host.c')], check=True, env=env,
                       capture_output=True)
        cls.blob, cls.labels, cls.man = section_blob()
        cls.section_file = os.path.join(cls.tmp, 'section.bin')
        Path(cls.section_file).write_bytes(cls.blob)
        cls.keys_file = os.path.join(cls.tmp, 'keys.bin')
        Path(cls.keys_file).write_bytes(b''.join(struct.pack('<I', i) for i in TABLE))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='evcap3saves_', dir=self.tmp)
        self.saves = os.path.join(self.dir, 'SaveData')
        os.makedirs(self.saves)
        self.save = os.path.join(self.saves, 'Save_001.sav')
        Path(self.save).write_bytes(slot_file(bytes(64)))
        self.sidecar = self.save + learned.SIDECAR_SUFFIX

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_host(self, *actions):
        r = subprocess.run([self.bin, self.section_file, self.keys_file, self.saves] + list(actions),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def pairs(self, *actions):
        """the store after `actions`, in one process (a fresh process starts with an empty store)"""
        out = self.run_host(*actions, 'dump').stdout.splitlines()
        got = []
        for line in out:
            if line.startswith('-- '):
                break
            serial, ident = line.split()
            got.append((int(serial), int(ident)))
        return got

    def test_a_saved_store_becomes_a_valid_companion(self):
        self.run_host('put=7:21000', 'put=9:21000', 'put=9:21001', 'saveslot=1')
        doc = json.loads(Path(self.sidecar).read_text())
        raw = Path(self.save).read_bytes()
        self.assertEqual(doc['kind'], 'd5modkit.learned')
        self.assertEqual(doc['schema'], 2)
        self.assertEqual(doc['generation'], self.man['generation'])
        self.assertEqual(doc['rows'], len(TABLE))
        self.assertEqual(doc['save']['size'], len(raw))
        self.assertEqual(doc['save']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(doc['units'][f'{9:016x}']['learned'], [21000, 21001])
        ok, problems, _ = learned.sidecar_validate(doc, self.save, TABLE)
        self.assertTrue(ok, problems)

    def test_the_companion_is_the_same_document_python_writes(self):
        self.run_host('put=7:21000', 'put=9:21000', 'put=9:21001', 'saveslot=1')
        theirs = json.loads(Path(self.sidecar).read_text())
        ours = learned.sidecar_doc(self.save, TABLE, {7: [21000], 9: [21000, 21001]})
        self.assertEqual(theirs, ours)

    def test_nothing_beyond_the_bitmap_writes_nothing(self):
        self.run_host('saveslot=1')
        self.assertFalse(Path(self.sidecar).exists())
        self.assertFalse(Path(self.sidecar + '.new').exists())

    def test_a_second_save_rotates_the_previous_generation(self):
        self.run_host('put=7:21000', 'saveslot=1')
        first = json.loads(Path(self.sidecar).read_text())
        Path(self.save).write_bytes(Path(self.save).read_bytes() + b'2')     # the next save's bytes
        self.run_host('put=9:21001', 'saveslot=1')
        second = json.loads(Path(self.sidecar).read_text())
        self.assertEqual(first, json.loads(Path(self.sidecar + learned.SIDECAR_PREV).read_text()))
        self.assertEqual(second['units'][f'{9:016x}']['learned'], [21001])
        self.assertNotEqual(first['save']['sha256'], second['save']['sha256'])

    def test_a_load_restores_the_store(self):
        self.run_host('put=7:21000', 'put=9:21001', 'saveslot=1')
        # a new process: the store starts empty, as after a quit
        self.assertEqual(self.pairs(), [])
        self.assertEqual(self.pairs('load=1'), [(7, 21000), (9, 21001)])

    def test_a_load_replaces_the_previous_saves_learning(self):
        self.run_host('put=5:21000', 'saveslot=1')
        # learning that is not in this companion (another unit, another save) must not survive the load
        self.assertEqual(self.pairs('put=6:21001', 'put=5:21001', 'load=1'), [(5, 21000)])

    def test_a_missing_companion_empties_the_store(self):
        self.assertEqual(self.pairs('put=5:21000', 'load=1'), [])

    def test_a_failed_decode_leaves_the_store_alone(self):
        self.assertEqual(self.pairs('put=5:21000', 'load=1:bad'), [(5, 21000)])

    def test_a_companion_for_other_bytes_is_refused_and_kept(self):
        self.run_host('put=7:21000', 'saveslot=1')
        Path(self.save).write_bytes(b'some other save')
        self.assertEqual(self.pairs('load=1'), [])
        self.assertFalse(Path(self.sidecar).exists())
        self.assertTrue(Path(self.sidecar + learned.SIDECAR_REJECTED).exists())

    def test_a_companion_for_another_table_is_refused_and_kept(self):
        self.run_host('put=7:21000', 'saveslot=1')
        doc = json.loads(Path(self.sidecar).read_text())
        doc['generation'] = (doc['generation'] ^ 0xFFFF) & 0xFFFFFFFF
        Path(self.sidecar).write_text(json.dumps(doc))
        self.assertEqual(self.pairs('load=1'), [])
        self.assertTrue(Path(self.sidecar + learned.SIDECAR_REJECTED).exists())

    def test_a_damaged_companion_is_refused_never_read_as_empty_success(self):
        self.run_host('put=7:21000', 'saveslot=1')
        text = Path(self.sidecar).read_text()
        Path(self.sidecar).write_text(text[:len(text) // 2])
        self.assertEqual(self.pairs('load=1'), [])
        self.assertTrue(Path(self.sidecar + learned.SIDECAR_REJECTED).exists())

    def test_ids_the_table_lacks_are_kept_as_quarantine(self):
        self.run_host('put=7:21000', 'saveslot=1')
        doc = json.loads(Path(self.sidecar).read_text())
        doc['units'][f'{7:016x}']['learned'].append(424242)
        Path(self.sidecar).write_text(json.dumps(doc))
        out = self.run_host('load=1', 'dump').stdout
        self.assertIn('quarantine 1', out)
        self.assertEqual(self.pairs('load=1'), [(7, 21000)])
        # a save in the same session carries the quarantined id forward, never discards it
        self.run_host('load=1', 'saveslot=1')
        back = json.loads(Path(self.sidecar).read_text())
        self.assertEqual(back['quarantine'], [dict(serial=7, id=424242)])
        self.assertEqual(back['units'][f'{7:016x}']['learned'], [21000])

    def test_a_table_that_moved_is_not_written(self):
        self.run_host('put=7:21000', 'saveslot=1')
        keep = Path(self.sidecar).read_text()
        moved = os.path.join(self.dir, 'moved.bin')
        Path(moved).write_bytes(b''.join(struct.pack('<I', i) for i in [0] + TABLE))
        r = subprocess.run([self.bin, self.section_file, moved, self.saves, 'put=7:21001',
                            'saveslot=1'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('NOT written', r.stderr)
        self.assertEqual(Path(self.sidecar).read_text(), keep)

    def test_the_save_file_is_never_written(self):
        before = Path(self.save).read_bytes()
        stat = Path(self.save).stat()
        self.run_host('put=7:21000', 'saveslot=1')
        self.assertEqual(Path(self.save).read_bytes(), before)
        self.assertEqual(Path(self.save).stat().st_mtime_ns, stat.st_mtime_ns)

    def test_an_agent_run_publishes_no_companion(self):
        """[debug] remote=1 fails the game's own writes under SaveData (d5ctl), so a save event in an agent
        run cannot be a save that reached the disk: our runtime must not write one either."""
        r = self.run_host('remote=1', 'put=7:21000', 'saveslot=1')
        self.assertIn('read only', r.stderr)
        self.assertFalse(Path(self.sidecar).exists())
        self.assertFalse(Path(self.sidecar + learned.SIDECAR_PREV).exists())
        self.assertFalse(Path(self.sidecar + '.new').exists())

    def test_an_agent_run_does_not_rename_a_refused_companion(self):
        """A refused companion is moved aside in play; an agent run only looks, so the file stays put."""
        self.run_host('put=7:21000', 'saveslot=1')
        Path(self.save).write_bytes(b'some other save')
        self.pairs('remote=1', 'load=1')
        self.assertTrue(Path(self.sidecar).exists())
        self.assertFalse(Path(self.sidecar + learned.SIDECAR_REJECTED).exists())

    def test_an_agent_run_still_applies_a_good_companion(self):
        """Reads are allowed in an agent run: the companion is applied exactly as in play."""
        self.run_host('put=7:21000', 'put=9:21001', 'saveslot=1')
        self.assertEqual(self.pairs('remote=1', 'load=1'), [(7, 21000), (9, 21001)])

    def test_a_save_folder_too_deep_to_name_a_slot_is_refused(self):
        deep = os.path.join(self.dir, 'a' * 200, 'b' * 200, 'c' * 200)
        os.makedirs(deep)
        self.assertGreater(len(deep) + len('/Save_001.sav'), 511)
        r = subprocess.run([self.bin, self.section_file, self.keys_file, deep, 'put=7:21000', 'saveslot=1'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('too long', r.stderr)
        self.assertEqual(os.listdir(deep), [])

    def test_a_file_that_is_not_a_slot_file_gets_no_companion(self):
        """The relay fires on the writer's success, so the file at the path we build must be that file."""
        Path(self.save).write_bytes(b'some other program wrote this' * 8)
        r = self.run_host('put=7:21000', 'saveslot=1')
        self.assertIn('not a slot file', r.stderr)
        self.assertFalse(Path(self.sidecar).exists())

    def test_a_slot_file_with_a_foreign_block_magic_gets_no_companion(self):
        Path(self.save).write_bytes(slot_file(bytes(64), block_magic=0))
        r = self.run_host('put=7:21000', 'saveslot=1')
        self.assertIn('not a slot file', r.stderr)
        self.assertFalse(Path(self.sidecar).exists())

    def test_a_slot_with_no_file_gets_no_companion(self):
        os.unlink(self.save)
        r = self.run_host('put=7:21000', 'saveslot=7')
        self.assertIn('cannot read back', r.stderr)
        self.assertEqual(sorted(os.listdir(self.saves)), [])

    def test_a_slot_that_cannot_name_a_file_is_reported_not_bound(self):
        r = self.run_host('put=7:21000', 'saveslot=-1')
        self.assertIn('cannot name a file', r.stderr)
        self.assertEqual(sorted(os.listdir(self.saves)), ['Save_001.sav'])

    def test_the_autosave_is_a_slot_file_too(self):
        auto = os.path.join(self.saves, 'AutoSave.sav')
        Path(auto).write_bytes(slot_file(bytes(64)))
        self.run_host('put=7:21000', 'saveslot=0')
        doc = json.loads(Path(auto + learned.SIDECAR_SUFFIX).read_text())
        self.assertEqual(doc['save']['name'], 'AutoSave.sav')
        ok, problems, _ = learned.sidecar_validate(doc, auto, TABLE)
        self.assertTrue(ok, problems)

    def test_two_saves_in_one_session_are_both_bound(self):
        """A sequence number, not a one-shot flag: a save that lands between two frames is not lost."""
        second = os.path.join(self.saves, 'Save_002.sav')
        Path(second).write_bytes(slot_file(bytes(64)))
        self.run_host('put=7:21000', 'saveslot=1', 'saveslot=2')
        for path in (self.save, second):
            doc = json.loads(Path(path + learned.SIDECAR_SUFFIX).read_text())
            ok, problems, _ = learned.sidecar_validate(doc, path, TABLE)
            self.assertTrue(ok, problems)
            self.assertEqual(doc['save']['name'], os.path.basename(path))

    def test_the_store_ceiling_is_visible_not_silent(self):
        # the runtime's own entry point, to the ceiling: everything fits up to STORE_MAX_USED, then refusals
        n = learned.STORE_MAX_USED + 3
        out = self.run_host(f'fill={n}').stdout
        self.assertIn(f'fill ok={learned.STORE_MAX_USED} refused=3', out)


if __name__ == '__main__':
    unittest.main()
