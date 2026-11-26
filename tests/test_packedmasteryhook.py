"""Packed mastery mapper hook: configuration, the assembled routine and the patch itself.

Synthetic PE only (no game files): the fixture carries the 16 mapper call bytes and a .pdata at the
pinned VAs' RVAs, so every check the builder makes runs against the real site table.
"""
import json
import os
import struct
import tempfile
import unittest

import pefile

from d5lib import masteryext as mx
from d5lib import packedmasteryhook as pm

BASE = 0x140000000
TEXT_RVA, TEXT_SIZE = 0x1000, 0x7D0000


def fixture(overrides=None):
    """minimal PE32+ whose .text carries every byte this extension validates"""
    end = TEXT_RVA + TEXT_SIZE
    data = bytearray(end + 0x1000)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 1, 0, 0, 0, 0xF0, 0x22)
    oh = 0x98
    struct.pack_into("<H", data, oh, 0x20B)
    struct.pack_into("<Q", data, oh + 24, BASE)
    struct.pack_into("<II", data, oh + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, oh + 56, end + 0x1000, 0x400)
    struct.pack_into("<I", data, oh + 108, 16)
    sh = oh + 0xF0
    struct.pack_into("<8sIIIIIIHHI", data, sh, b".text", TEXT_SIZE, TEXT_RVA, TEXT_SIZE, 0x400, 0, 0, 0, 0,
                     0x60000020)
    struct.pack_into("<8sIIIIIIHHI", data, sh + 40, b".pdata", 0x200, end, 0x200, end + 0x400, 0, 0, 0, 0,
                     0x40000040)

    def at(va):
        return 0x400 + (va - BASE - TEXT_RVA)

    for va in pm.MAPPER_CALLS:
        rel = pm.MAPPER - (va + 5)
        data[at(va):at(va) + 5] = b"\xe8" + struct.pack("<i", rel)
    # the instructions d5lib.masteryext validates too, so a .d5cm build can share this fixture
    for va, orig in ((mx.SUBCLASS_SITE, mx.SUBCLASS_ORIG), (mx.FETCH_SITE, mx.FETCH_ORIG),
                     (mx.BOUND_SITE, mx.BOUND_ORIG)):
        data[at(va):at(va) + len(orig)] = orig
    for va, value in (overrides or {}).items():
        data[at(va):at(va) + len(value)] = value
    return bytes(data)


class FamilyTests(unittest.TestCase):
    def test_sorted_and_unique(self):
        self.assertEqual(pm.families_from([1360, 1350, 1360]), [1350, 1360])

    def test_rejects_vanilla(self):
        for fam in (1010, 2210):
            with self.assertRaises(ValueError):
                pm.families_from([fam])

    def test_rejects_non_base_and_reserved(self):
        for fam in (1355, 999, 500, 40000, 20050):
            with self.assertRaises(ValueError):
                pm.families_from([fam])

    def test_rejects_too_many(self):
        with self.assertRaises(ValueError):
            pm.families_from(list(range(1000, 100000, 10))[:pm.MAX_FAMILIES + 1])

    def test_empty(self):
        self.assertEqual(pm.families_from([]), [])
        self.assertEqual(pm.families_from(None), [])


class SectionTests(unittest.TestCase):
    def test_section_name_is_free(self):
        """a new section name: never a name another extension uses (the exe has no room to spare)"""
        names = {mx.SECTION_NAME, b".d5mod", b".d5ev", b".d5ly", b".d5cl", b".d5qr", b".d5el", b".d5ul",
                 b".d5wl", b".d5sg", b".d5ei", b".d5c4", b".d5fx", b".d5id", b".d5sc", b".d5auto"}
        self.assertEqual(pm.SECTION_NAME, b".d5pm")
        self.assertNotIn(pm.SECTION_NAME, names)

    def test_build_and_read_back(self):
        exe = pm.build_patch(fixture(), [1350, 1360])
        info = pm.section_info(exe)
        self.assertIsNotNone(info)
        self.assertEqual(info["section"], ".d5pm")
        self.assertEqual(pm.read_families(exe), [1350, 1360])
        offset, count, version = struct.unpack_from("<III", info["data"], 4)
        self.assertEqual((count, version), (2, pm.CLAIM_VERSION))
        self.assertEqual(offset % 4, 0)
        self.assertLessEqual(offset + 4 * count, len(info["data"]))       # the table, then exepatch's claim block
        self.assertEqual(struct.unpack_from("<2I", info["data"], offset), (1350, 1360))

    def test_every_site_redirected_to_the_wrapper(self):
        exe = pm.build_patch(fixture(), [1350, 1360])
        info = pm.section_info(exe)
        pe = pefile.PE(data=exe, fast_load=True)
        for va in pm.MAPPER_CALLS:
            off = pe.get_offset_from_rva(va - BASE)
            raw = exe[off:off + 5]
            self.assertEqual(raw[0], 0xE8, hex(va))
            self.assertEqual(va + 5 + struct.unpack("<i", raw[1:])[0], info["code"], hex(va))

    def test_unwind_records_cover_the_section(self):
        plain = fixture()
        exe = pm.build_patch(plain, [1350, 1360])
        pe = pefile.PE(data=exe, fast_load=True)
        info = pm.section_info(exe)
        directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        entries = list(struct.iter_unpack("<III", pe.get_data(directory.VirtualAddress, directory.Size)))
        ours = [e for e in entries if info["base"] - BASE <= e[0] < info["base"] - BASE + info["size"]]
        self.assertGreaterEqual(len(ours), 4)                    # wrapper, encoder, lookup, six-rank helper
        self.assertTrue(all(e[2] for e in ours))
        self.assertEqual(ours, sorted(ours))
        for start, end, unwind in ours:
            self.assertLess(start, end)

    def test_layout_is_stable_under_its_own_table_address(self):
        base = pm.code_base(fixture(), pm.SECTION_NAME)
        first, _ = pm._layout([1350, 1360], base, base)
        table = base + len(first) - 8
        second, starts = pm._layout([1350, 1360], base, table)
        self.assertEqual(len(first), len(second))
        self.assertEqual(sorted(starts), ["fetch", "mapper", "subclass"])
        self.assertEqual(starts["mapper"], base + 16)
        self.assertEqual(first[:4], b"D5PM")
        self.assertLess(starts["mapper"], starts["subclass"])
        self.assertLess(starts["subclass"], starts["fetch"])

    def test_more_families_change_the_table_and_the_subclass_stubs(self):
        """the family table grows 4 bytes each; both sub-class stubs compare per family"""
        base = pm.code_base(fixture(), pm.SECTION_NAME)
        fams = list(range(1350, 1700, 10))
        two, two_starts = pm._layout([1350, 1360], base, base)
        many, many_starts = pm._layout(fams, base, base)

        def stub(code, starts, count, tag, nxt):
            return (starts.get(nxt, len(code) - 4 * count)) - starts[tag]

        pair = ("subclass", "fetch"), ("fetch", None)
        two_grow = sum(stub(two, two_starts, 2, *p) for p in pair)
        many_grow = sum(stub(many, many_starts, len(fams), *p) for p in pair)
        self.assertGreater(many_grow, two_grow)
        extra = 4 * (len(fams) - 2) + many_grow - two_grow
        self.assertGreaterEqual(len(many) - len(two), extra)
        self.assertLessEqual(len(many) - len(two), extra + 16)            # routine alignment only
        self.assertEqual(len(pm._assemble(pm._asm_source(fams, base), base + 16)),
                         len(pm._assemble(pm._asm_source([1350, 1360], base), base + 16)))   # wrapper is fixed

    def test_the_wrapper_hands_the_writer_the_family_base_only_at_its_own_site(self):
        """STARS-FIX: the writer's rank limit is r10 % 10, so its own call gets the family base"""
        src = pm._asm_source([1350, 1360])
        self.assertIn(f"mov rax, {pm.WRITER_RET:#x}", src)
        # the flag is set inside that site's branch and read only at the stage return
        site = src[src.index("pm_s1:"):src.index("pm_s2:")]
        self.assertIn(f"mov dword ptr [rsp + {pm.X_AWARD:#x}], 1", site)
        ret = src[src.index("pm_ret_stage:"):src.index("pm_out:")]
        self.assertIn(f"cmp dword ptr [rsp + {pm.X_AWARD:#x}], 0", ret)
        self.assertIn(f"mov dword ptr [rsp + {pm.R10_SAVE:#x}], eax", ret)
        # and the family base is the value moved, taken from the configured family
        self.assertIn(f"mov eax, dword ptr [rsp + {pm.X_FAM:#x}]", ret)
        # every other site leaves the award flag alone
        for i in range(len(pm.SITES)):
            if i == 1:
                continue
            block = src[src.index(f"pm_s{i}:"):src.index(f"pm_s{i + 1}:") if i + 1 < len(pm.SITES) else src.index("pm_have_record:")]
            self.assertNotIn(f"mov dword ptr [rsp + {pm.X_AWARD:#x}], 1", block, i)

    def test_only_the_writer_site_may_change_a_caller_register(self):
        changed = [ret for ret, _ in ((s[0], s) for s in pm.SITES) if ret == pm.WRITER_RET]
        self.assertEqual(changed, [0x14015F505])

    def test_mode_for_splits_the_two_mapping_sources(self):
        self.assertEqual(pm.mode_for([1350]), pm.MODE_SIX)
        self.assertEqual(pm.mode_for(range(1350, 1410, 10)), pm.MODE_SIX)          # six families
        self.assertEqual(pm.mode_for(range(1350, 1420, 10)), pm.MODE_PACKED)       # seven
        with self.assertRaises(ValueError):
            pm.mode_for([])

    def test_subclass_gate_and_screen_are_part_of_the_packed_section(self):
        exe = pm.build_patch(fixture(), [1350, 1360])
        info = pm.section_info(exe)
        pe = pefile.PE(data=exe, fast_load=True)
        for va, orig, opcode in ((mx.SUBCLASS_SITE, mx.SUBCLASS_ORIG, 0xE9),
                                 (mx.FETCH_SITE, mx.FETCH_ORIG, 0xE8)):
            off = pe.get_offset_from_rva(va - BASE)
            raw = exe[off:off + 5]
            self.assertEqual(raw[0], opcode, hex(va))
            self.assertEqual(va + 5 + struct.unpack("<i", raw[1:])[0] in
                             range(info["code"], info["base"] + info["size"]), True, hex(va))
        off = pe.get_offset_from_rva(mx.BOUND_SITE - BASE)
        self.assertEqual(exe[off:off + 3], mx.BOUND_ORIG[:3])
        self.assertEqual(exe[off + 3], 0x2F + 2)

    def test_refuses_an_exe_that_packed_mastery_already_patched(self):
        """building the six-slot extension over a packed build is refused by name, not by site bytes"""
        exe = pm.build_patch(fixture(), [1350, 1360])
        with self.assertRaises(ValueError) as caught:
            mx.build_patch(exe, [1350, 1360])
        self.assertIn(".d5pm", str(caught.exception))

    def test_refuses_a_six_slot_build_by_name(self):
        exe = mx.build_patch(fixture(), [1350, 1360])
        with self.assertRaises(ValueError) as caught:
            pm.build_patch(exe, [1350, 1360])
        self.assertIn(".d5cm", str(caught.exception))

    def test_refuses_an_already_hooked_site(self):
        with self.assertRaises(ValueError):
            pm.build_patch(fixture({pm.MAPPER_CALLS[0]: b"\xe8\x00\x00\x00\x00"}), [1350, 1360])

    def test_refuses_an_exe_that_the_class_mastery_lane_already_patched(self):
        """both hooks redirect the same 16 calls, so the second build must refuse loudly, not half-apply"""
        exe = mx.build_patch(fixture(), [1350, 1360])
        with self.assertRaises(ValueError):
            pm.build_patch(exe, [1350, 1360])

    def test_no_families_is_an_error(self):
        with self.assertRaises(ValueError):
            pm.build_patch(fixture(), [])

    def test_section_info_of_an_unpatched_exe(self):
        self.assertIsNone(pm.section_info(fixture()))
        self.assertEqual(pm.read_families(fixture()), [])


class AssemblyTests(unittest.TestCase):
    def test_site_table_matches_the_documented_sixteen(self):
        self.assertEqual(len(pm.SITES), 16)
        self.assertEqual([s[0] for s in pm.SITES], [va + 5 for va in pm.MAPPER_CALLS])
        regs = {reg for _, reg, _ in pm.SITES}
        self.assertTrue(regs <= {"r9", "r10", "r13", "r15", "rbp", "rbx", "rdi"})
        derefs = {ret: d for ret, _, d in pm.SITES if d}
        self.assertEqual(derefs, {0x1400B3CED: 0x228, 0x14047FFCD: 0x1F1A8})

    def test_the_wrapper_saves_every_register_a_caller_may_hold(self):
        src = pm._asm_source([1350])
        for reg in ("rcx", "rdx", "r8", "r9", "r10", "r11", "rbx", "rbp", "rsi", "rdi",
                    "r12", "r13", "r14", "r15"):
            self.assertIn(f"    push {reg}\n", src + "\n")
            self.assertIn(f"    pop {reg}\n", src + "\n")
        self.assertNotIn("pushfq", src)              # flags are already dead at a call boundary

    def test_no_write_path_when_nothing_is_staged(self):
        """an already-staged family returns 52 without entering the commit sequence"""
        src = pm._asm_source([1350])
        self.assertIn("je pm_ret_stage", src)
        self.assertLess(src.index("je pm_ret_stage"), src.index("pm_commit:"))
        self.assertLess(src.index("ja pm_out_none"), src.index("pm_compact:"))    # capacity before any write


if __name__ == "__main__":
    unittest.main()


class InstallTests(unittest.TestCase):
    """the install side: which mapping source a profile gets, and what a packed install does to the leases.

    INTEG6: `mode_for` is now wired into the mastery finalizer, so the build picks `.d5cm` (<= 6 families,
    leases) or `.d5pm` (> 6 families, packed pool) by itself, and a packed install never assigns, retires or
    rewrites a six-slot lease -- it refuses until the six-slot progress it supersedes is acknowledged.
    """

    FAMILIES = [1350, 14080, 14140, 14170, 14220, 14240, 14250]      # seven: one more than the six slots

    class Ctx:
        def __init__(self, exe, specs, game_dir=None):
            self.outputs = {"EXE/disgaea5.exe": exe}
            self._class_specs = specs
            self.lines = []
            self.fs = type("FS", (), {"game_dir": game_dir})() if game_dir else None

        def get(self, path):
            return self.outputs[path]

        def put(self, path, data):
            self.outputs[path] = data

        def log(self, text):
            self.lines.append(text)

    class Mod:
        def __init__(self, data, mod_id="D4_Test"):
            self.data = data
            self.id = mod_id

        def load_patch(self, folder, name):
            return self.data

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        previous = os.environ.get("D5_MASTERY_LEASE_DIR")
        os.environ["D5_MASTERY_LEASE_DIR"] = self.tmp.name

        def restore():
            if previous is None:
                os.environ.pop("D5_MASTERY_LEASE_DIR", None)
            else:
                os.environ["D5_MASTERY_LEASE_DIR"] = previous

        self.addCleanup(restore)
        self.lease_file = os.path.join(self.tmp.name, mx.LEASE_FILE)

    def build(self, families, game_dir=None, mods=None):
        """run the mastery handler/finalizer the way the kit's build does, over `families`"""
        ctx = self.Ctx(fixture(), {fam: {} for fam in families}, game_dir=game_dir)
        for data in (mods or [{"mastery": {"families": families}}]):
            mx._handler(ctx, self.Mod(data), None)
        mx._finalize(ctx)
        return ctx

    def lease(self, mapping):
        leases = mx.SlotLeases.load(self.lease_file, log=lambda *_: None)
        leases.assign(mapping)
        leases.save()
        return leases

    # --- the choice of source ---------------------------------------------------------------
    def test_requested_mode_reads_the_declaration_only(self):
        self.assertIsNone(pm.requested_mode({"mastery": {"families": [1350]}}))
        self.assertIsNone(pm.requested_mode({"mastery": [1350]}))
        self.assertIsNone(pm.requested_mode({}))
        self.assertEqual(pm.requested_mode({"mastery": {"mode": "packed"}}), pm.MODE_PACKED)
        self.assertEqual(pm.requested_mode({"mastery": {"families": [1350], "mode": "six"}}), pm.MODE_SIX)
        with self.assertRaises(ValueError):
            pm.requested_mode({"mastery": {"mode": "both"}})

    def test_mode_for_counts_families_and_honours_a_declaration(self):
        six = list(range(1350, 1410, 10))
        self.assertEqual(pm.mode_for(six), pm.MODE_SIX)
        self.assertEqual(pm.mode_for(self.FAMILIES), pm.MODE_PACKED)
        self.assertEqual(pm.mode_for([1350], requested=pm.MODE_PACKED), pm.MODE_PACKED)
        with self.assertRaises(ValueError) as caught:
            pm.mode_for(self.FAMILIES, requested=pm.MODE_SIX)
        self.assertIn(".d5pm", str(caught.exception))

    def test_finalizer_installs_the_packed_section_for_seven_families(self):
        ctx = self.build(self.FAMILIES)
        exe = ctx.outputs["EXE/disgaea5.exe"]
        self.assertIsNotNone(pm.section_info(exe))                 # .d5pm
        self.assertIsNone(mx.section_info(exe))                    # never both
        self.assertEqual(pm.read_families(exe), sorted(self.FAMILIES))
        self.assertFalse(os.path.exists(self.lease_file))          # a packed build uses no lease
        self.assertTrue(any("packed (.d5pm)" in line for line in ctx.lines))

    def test_finalizer_keeps_the_six_slots_for_six_families(self):
        six = self.FAMILIES[:6]
        ctx = self.build(six)
        exe = ctx.outputs["EXE/disgaea5.exe"]
        self.assertIsNotNone(mx.section_info(exe))                 # .d5cm
        self.assertIsNone(pm.section_info(exe))
        self.assertTrue(os.path.exists(self.lease_file))
        self.assertEqual(mx.SlotLeases.load(self.lease_file, log=lambda *_: None).slots,
                         {fam: 47 + i for i, fam in enumerate(sorted(six))})

    def test_a_declared_source_cannot_be_the_six_slots_with_seven_families(self):
        ctx = self.Ctx(fixture(), {fam: {} for fam in self.FAMILIES})
        mx._handler(ctx, self.Mod({"mastery": {"families": self.FAMILIES, "mode": "six"}}), None)
        with self.assertRaises(ValueError):
            mx._finalize(ctx)

    def test_two_mods_declaring_different_sources_are_refused(self):
        ctx = self.Ctx(fixture(), {fam: {} for fam in self.FAMILIES})
        mx._handler(ctx, self.Mod({"mastery": {"families": [1350], "mode": "six"}}, "A"), None)
        with self.assertRaises(ValueError) as caught:
            mx._handler(ctx, self.Mod({"mastery": {"families": [14080], "mode": "packed"}}, "B"), None)
        self.assertIn("one mapping source", str(caught.exception))

    # --- the lease decision -----------------------------------------------------------------
    def test_packed_install_refuses_an_unacknowledged_six_slot_lease(self):
        self.lease([1350])
        before = open(self.lease_file, "rb").read()
        ctx = self.Ctx(fixture(), {fam: {} for fam in self.FAMILIES})
        mx._handler(ctx, self.Mod({"mastery": {"families": self.FAMILIES}}), None)
        with self.assertRaises(ValueError) as caught:
            mx._finalize(ctx)
        message = str(caught.exception)
        self.assertIn("1350", message)
        self.assertIn("accept_packed_mastery.py", message)
        self.assertIn("47..52", message)
        self.assertEqual(ctx.outputs["EXE/disgaea5.exe"], fixture())   # nothing was patched
        self.assertEqual(open(self.lease_file, "rb").read(), before)  # nor leased, retired or moved
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, pm.MIGRATION_FILE)))

    def test_acknowledged_lease_installs_and_records_what_was_given_up(self):
        leases = self.lease([1350, 1360])
        leases.acknowledge_packed([1350, 1360])
        leases.save()
        before = open(self.lease_file, "rb").read()
        ctx = self.Ctx(fixture(), {fam: {} for fam in self.FAMILIES})
        mx._handler(ctx, self.Mod({"mastery": {"families": self.FAMILIES}}), None)
        mx._finalize(ctx)
        exe = ctx.outputs["EXE/disgaea5.exe"]
        self.assertIsNotNone(pm.section_info(exe))
        self.assertEqual(open(self.lease_file, "rb").read(), before)  # the packed build did not touch it
        receipt = json.load(open(os.path.join(self.tmp.name, pm.MIGRATION_FILE)))
        self.assertTrue(receipt["packed"])
        self.assertEqual(receipt["six_slot_leases"], {"1350": 47, "1360": 48})
        self.assertEqual(receipt["families"], sorted(self.FAMILIES))
        self.assertIn("nothing was migrated", receipt["note"].lower())
        self.assertTrue(any("MIGRATION RECEIPT" in line for line in ctx.lines))

    def test_only_the_unacknowledged_family_blocks_the_install(self):
        leases = self.lease([1350, 1360])
        leases.acknowledge_packed([1350])
        leases.save()
        with self.assertRaises(ValueError) as caught:
            self.build(self.FAMILIES)
        self.assertIn("unacknowledged: 1360", str(caught.exception))

    def test_no_lease_needs_no_acknowledgement_and_no_receipt(self):
        ctx = self.build(self.FAMILIES)
        self.assertIsNotNone(pm.section_info(ctx.outputs["EXE/disgaea5.exe"]))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, pm.MIGRATION_FILE)))
