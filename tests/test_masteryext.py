"""Class mastery extension: configuration, the assembled hooks and the patch itself (synthetic PE, no game files)."""
import struct
import unittest
from unittest.mock import patch

import pefile

from d5lib import masteryext as mx

BASE = 0x140000000
# the highest redirect site is 0x1407CDAD9, so the fixture's .text has to reach it
TEXT_RVA, TEXT_SIZE = 0x1000, 0x7D0000


def fixture(overrides=None):
    """Minimal PE32+ whose .text carries every byte the extension validates, at the pinned VAs' RVAs."""
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

    for va in mx.MAPPER_CALLS:
        rel = mx.MAPPER - (va + 5)
        data[at(va):at(va) + 5] = b"\xe8" + struct.pack("<i", rel)
    for va, orig in ((mx.SUBCLASS_SITE, mx.SUBCLASS_ORIG), (mx.FETCH_SITE, mx.FETCH_ORIG),
                     (mx.BOUND_SITE, mx.BOUND_ORIG)):
        data[at(va):at(va) + len(orig)] = orig
    for va, value in (overrides or {}).items():
        data[at(va):at(va) + len(value)] = value
    return bytes(data)


def asm(fams):
    """{tag: (address, bytes)} for the three routines, assembled the way build_patch places them"""
    base = 0x150000000
    out, offset = {}, 0
    for tag, src in mx._asm_sources(fams):
        offset += -offset % 16
        code = mx._assemble(src, base + offset)
        out[tag] = (base + offset, code)
        offset += len(code)
    return out


class FamilyTests(unittest.TestCase):
    def test_six_spare_slots_are_assigned_in_order(self):
        self.assertEqual(mx.slots([1360, 1350]), {1350: 47, 1360: 48})
        self.assertEqual(mx.slots([1350, 1355]), {1350: 47, 1355: 48})
        self.assertEqual(max(mx.slots(list(range(1350, 1410, 10))).values()), 52)

    def test_award_target_is_the_family_base_only_for_a_configured_family(self):
        fams = [1350, 1360]
        for target in (1350, 1351, 1355, 1359):
            self.assertEqual(mx.award_target(target, fams), 1350)
        for target in (1360, 1365, 1369):
            self.assertEqual(mx.award_target(target, fams), 1360)
        # out of the configured ranges: untouched, including every vanilla id and the ranks the slot test would claim
        for target in (1349, 1370, 1010, 1015, 1155, 2010, 2460, 0):
            self.assertEqual(mx.award_target(target, fams), target)
        self.assertEqual(mx.award_target(1355, []), 1355)

    def test_six_families_at_most(self):
        families = list(range(1350, 1410, 10))
        self.assertEqual(len(mx.families_from({"mastery": {"families": families}})), 6)
        with self.assertRaises(ValueError):
            mx.families_from({"mastery": {"families": families + [1410]}})

    def test_refusals(self):
        bad = [([1355], "family base"), ([1350, 1350], "twice"), ([1005], "family base"),
               ([1010], "vanilla"), ([20000], "reserved"), ([990], "reserved"), ([40000], "range")]
        for families, text in bad:
            with self.subTest(families=families):
                with self.assertRaises(ValueError) as caught:
                    mx.families_from({"mastery": {"families": families}})
                self.assertIn(text, str(caught.exception))

    def test_a_family_must_have_a_class_in_the_build(self):
        self.assertEqual(mx.families_from({"mastery": {"families": [1350]}}, {1350: {}}), [1350])
        with self.assertRaises(ValueError) as caught:
            mx.families_from({"mastery": {"families": [1350]}}, {1360: {}})
        self.assertIn("no class in this build", str(caught.exception))

    def test_no_families_is_no_extension(self):
        self.assertEqual(mx.families_from({}), [])
        self.assertEqual(mx.families_from(None), [])
        self.assertEqual(mx.families_from({"mastery": {}}), [])


class CodeTests(unittest.TestCase):
    def test_mapper_wrapper_keeps_the_id_and_returns_one_slot_per_family(self):
        code = asm([1350, 1360])["mapper"][1]
        # push rbx / sub rsp, 0x20 / mov ebx, ecx / call, so rcx (which the original divides by 10) is not reused
        self.assertEqual(code[:1], b"\x53")
        self.assertEqual(code[1:5], b"\x48\x83\xec\x20")
        self.assertEqual(code[5:7], b"\x89\xcb")
        self.assertEqual(code[7], 0xE8)
        self.assertIn(struct.pack("<i", -1350), code)                # lea edx, [rbx - 1350]
        self.assertIn(struct.pack("<i", -1360), code)
        self.assertIn(b"\xb8\x2f\x00\x00\x00", code)                 # mov eax, 47
        self.assertIn(b"\xb8\x30\x00\x00\x00", code)                 # mov eax, 48
        self.assertEqual(code[-1], 0xC3)
        self.assertEqual(code[-2], 0x5B)                             # pop rbx before ret
        # every slot answer jumps to the epilogue, so no slot falls through into the next one
        self.assertEqual(code.count(b"\xeb"), 4)                     # 2 slots + the -1 answer + the epilogue jump

    def test_only_the_award_writer_call_gets_the_family_base(self):
        """the wrapper compares the caller's return address with the writer's continuation and rewrites r10 only
        then: one return-address check and one family-base write per configured family, nothing else"""
        for fams in ([1350], [1350, 1360], list(range(1350, 1410, 10))):
            with self.subTest(families=fams):
                code = asm(fams)["mapper"][1]
                self.assertIn(b"\x48\x8b\x44\x24\x28", code)          # mov rax, [rsp + 0x28] (the return address)
                self.assertEqual(code.count(b"\x48\xba\x05\xf5\x15\x40\x01\x00\x00\x00"), len(fams))
                self.assertEqual(code.count(b"\x48\x39\xd0"), len(fams))          # cmp rax, rdx
                for i, fam in enumerate(fams):
                    # mov r10d, <family base>: the writer's rank limit then starts at rank 0
                    self.assertIn(b"\x41\xba" + struct.pack("<I", fam), code)
                    self.assertIn(struct.pack("<I", mx.SLOT_FIRST + i), code)
                self.assertEqual(code.count(b"\x41\xba"), len(fams))  # no other r10 write anywhere in the wrapper
                # the frame is unchanged, so the section's unwind record stays valid
                self.assertEqual(code[:5], b"\x53\x48\x83\xec\x20")
                self.assertTrue(code.endswith(b"\x48\x83\xc4\x20\x5b\xc3"))  # add rsp, 0x20 / pop rbx / ret

    def test_subclass_gate_jumps_to_the_original_accept_and_reject_paths(self):
        addr, code = asm([1350])["subclass"]
        self.assertNotIn(b"\xc3", code)                              # never returns: it is jumped to
        self.assertEqual(code.count(b"\xe9"), 2)                     # one for accept, one for reject
        self.assertIn(struct.pack("<i", -1350), code)                # lea eax, [rcx - 1350]
        self.assertEqual(code.count(b"\x3d"), 2)                     # cmp eax, imm32 twice (2010, 1000)
        self.assertIn(b"\x83\xf8\x05", code)                          # cmp eax, 5 (ranks 0..5)

    def test_fetch_keeps_the_native_array_below_47_and_stops_at_the_row_cap(self):
        code = asm([1350, 1360])["fetch"][1]
        self.assertEqual(code[:4], b"\x41\x83\xfd\x2f")               # cmp r13d, 0x2f
        self.assertIn(b"\x46\x8b\x7c\xad\x90", code)                 # the original instruction, unchanged
        self.assertIn(b"\x83\xbe\x8c\x00\x00\x00\x2f", code)        # cmp [rsi+0x8c], 0x2f: the row cap
        self.assertIn(b"\x45\x31\xff", code)                         # xor r15d, r15d for "no family"
        self.assertIn(b"\x41\xbf\x46\x05\x00\x00", code)            # mov r15d, 1350
        self.assertIn(b"\x41\xbf\x50\x05\x00\x00", code)            # mov r15d, 1360
        self.assertEqual(code.count(b"\xc3"), 4)                     # native array, no family, one per family

    def test_a_different_exe_is_refused(self):
        broken = fixture({mx.MAPPER_CALLS[3]: b"\x90" * 5})
        with self.assertRaises(ValueError) as caught:
            mx.build_patch(broken, [1350])
        self.assertIn("different exe build", str(caught.exception))
        for va, orig in ((mx.SUBCLASS_SITE, mx.SUBCLASS_ORIG), (mx.FETCH_SITE, mx.FETCH_ORIG),
                         (mx.BOUND_SITE, mx.BOUND_ORIG)):
            with self.subTest(site=hex(va)):
                with self.assertRaises(ValueError):
                    mx.build_patch(fixture({va: b"\x90" * len(orig)}), [1350])


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.built = mx.build_patch(fixture(), [1350, 1360])
        self.pe = pefile.PE(data=self.built, fast_load=True)

    def offset(self, va):
        return self.pe.get_offset_from_rva(va - BASE)

    def test_section_is_claimed_and_found(self):
        info = mx.section_info(self.built)
        self.assertIsNotNone(info)
        self.assertEqual(info["data"][:4], mx.CLAIM)
        self.assertEqual(self.pe.sections[-1].Name.rstrip(b"\0"), b".d5cm")
        code = self.built[self.offset(mx.MAPPER_CALLS[0]):]
        self.assertEqual(code[0], 0xE8)

    def test_all_sixteen_mapper_sites_call_the_same_wrapper(self):
        info = mx.section_info(self.built)
        targets = set()
        for va in mx.MAPPER_CALLS:
            off = self.offset(va)
            self.assertEqual(self.built[off], 0xE8, hex(va))
            targets.add(va + 5 + struct.unpack_from("<i", self.built, off + 1)[0])
        self.assertEqual(targets, {info["code"]})

    def test_subclass_gate_is_a_jmp_and_the_rest_of_its_region_is_padding(self):
        off = self.offset(mx.SUBCLASS_SITE)
        self.assertEqual(self.built[off], 0xE9)
        self.assertEqual(self.built[off + 5:off + len(mx.SUBCLASS_ORIG)], b"\x90" * (len(mx.SUBCLASS_ORIG) - 5))
        target = mx.SUBCLASS_SITE + 5 + struct.unpack_from("<i", self.built, off + 1)[0]
        self.assertGreater(target, BASE)

    def test_fetch_is_a_call_of_the_section(self):
        info = mx.section_info(self.built)
        off = self.offset(mx.FETCH_SITE)
        self.assertEqual(self.built[off], 0xE8)
        target = mx.FETCH_SITE + 5 + struct.unpack_from("<i", self.built, off + 1)[0]
        self.assertTrue(info["code"] <= target < info["base"] + info["size"], hex(target))

    def test_loop_bound_covers_the_configured_families(self):
        off = self.offset(mx.BOUND_SITE)
        self.assertEqual(self.built[off:off + 3], mx.BOUND_ORIG[:3])
        self.assertEqual(self.built[off + 3], 0x2F + 2)

    def test_an_empty_family_list_is_refused(self):
        with self.assertRaises(ValueError):
            mx.build_patch(fixture(), [])


def runtime_functions(pe):
    """the runtime function table the exception directory names"""
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    assert directory.Size % 12 == 0
    data = pe.get_data(directory.VirtualAddress, directory.Size)
    assert len(data) == directory.Size
    table = list(struct.iter_unpack("<III", data))
    assert table == sorted(table)
    return table


def unwind_info(pe, unwind_rva):
    """(prologue size, [(prologue offset, code byte)]) of one UNWIND_INFO record"""
    header = pe.get_data(unwind_rva, 4)
    assert header[0] & 7 == 1                    # version 1, no flags
    prologue_size, count = header[1], header[2]
    data = pe.get_data(unwind_rva, 4 + 2 * count)
    return prologue_size, [tuple(data[4 + n * 2:6 + n * 2]) for n in range(count)]


class UnwindTests(unittest.TestCase):
    """.d5cm frames get unwind records through exepatch, next to the exe's own"""

    def build(self):
        """a fixture whose .pdata already holds one runtime function, so retention is checked too"""
        data = bytearray(fixture())
        oh, pdata_rva = 0x98, TEXT_RVA + TEXT_SIZE
        struct.pack_into("<H", data, 0x84 + 2, 2)                 # .text and .pdata are both real sections here
        old = (TEXT_RVA, TEXT_RVA + 8, pdata_rva + 0x100)
        struct.pack_into("<III", data, pdata_rva + 0x400, *old)
        data[pdata_rva + 0x100:pdata_rva + 0x104] = bytes((1, 0, 0, 0))
        struct.pack_into("<II", data, oh + 112 + 3 * 8, pdata_rva, 12)
        return mx.build_patch(bytes(data), [1350, 1360]), old

    def routine_starts(self, built, pe):
        starts = {}
        for site in (mx.MAPPER_CALLS[0], mx.FETCH_SITE, mx.SUBCLASS_SITE):
            off = pe.get_offset_from_rva(site - BASE)
            opcode, rel = built[off], struct.unpack_from("<i", built, off + 1)[0]
            self.assertIn(opcode, (0xE8, 0xE9), hex(site))
            starts[site] = site + 5 + rel
        return starts

    def test_every_hooked_routine_has_an_unwind_record(self):
        built, old = self.build()
        pe = pefile.PE(data=built, fast_load=True)
        table = runtime_functions(pe)
        info = mx.section_info(built)
        self.assertEqual(table[0], old)                                   # the existing record is kept
        covered = {a + BASE: (b + BASE, u + BASE) for a, b, u in table[1:]}
        starts = self.routine_starts(built, pe)
        self.assertEqual(sorted(covered), sorted(starts.values()))
        for start, (end, unwind) in covered.items():
            self.assertLess(start, end)
            self.assertGreaterEqual(unwind % 4, 0)
            self.assertEqual(unwind % 4, 0)
            self.assertTrue(info["base"] <= unwind < info["base"] + info["size"], hex(unwind))
        # the mapper wrapper's whole frame: push rbx (offset 1), sub rsp, 0x20 (offset 5)
        self.assertEqual(unwind_info(pe, covered[starts[mx.MAPPER_CALLS[0]]][1] - BASE),
                         (5, [(5, 0x32), (1, 0x30)]))
        # the two stubs never touch the stack, and the gate leaves by jumping, not returning
        for site in (mx.FETCH_SITE, mx.SUBCLASS_SITE):
            self.assertEqual(unwind_info(pe, covered[starts[site]][1] - BASE), (0, []))

    def test_the_exception_directory_lives_inside_the_new_section(self):
        built, _ = self.build()
        pe = pefile.PE(data=built, fast_load=True)
        info = mx.section_info(built)
        directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        start = directory.VirtualAddress + BASE
        self.assertTrue(info["base"] <= start, hex(start))
        self.assertLessEqual(start + directory.Size, info["base"] + info["size"])


class InstallTests(unittest.TestCase):
    """the patch handler and finalizer as the kit's build drives them"""

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
        def __init__(self, data):
            self.data = data

        def load_patch(self, folder, name):
            return self.data

    def test_handler_accumulates_families_from_every_mod(self):
        ctx = self.Ctx(None, {1350: {}, 1360: {}})
        mx._handler(ctx, self.Mod({"mastery": {"families": [1350]}}), None)
        mx._handler(ctx, self.Mod({"mastery": {"families": [1360]}}), None)
        mx._handler(ctx, self.Mod({}), None)
        self.assertEqual(sorted(ctx._mastery_families), [1350, 1360])

    def test_finalizer_patches_the_exe_once(self):
        ctx = self.Ctx(fixture(), {1350: {}, 1360: {}})
        mx._handler(ctx, self.Mod({"mastery": {"families": [1350, 1360]}}), None)
        mx._finalize(ctx)
        exe = ctx.outputs["EXE/disgaea5.exe"]
        self.assertIsNotNone(mx.section_info(exe))
        self.assertTrue(any("slot 47" in line and "slot 48" in line for line in ctx.lines))

    def test_finalizer_refuses_a_mastery_family_the_build_has_no_class_for(self):
        # P2: a mastery-only mod with no (or a failed) class load must not install a mapping for an absent class
        ctx = self.Ctx(fixture(), {})
        mx._handler(ctx, self.Mod({"mastery": {"families": [1350]}}), None)
        with self.assertRaises(ValueError):
            mx._finalize(ctx)

    def test_finalizer_refuses_a_family_the_build_does_not_declare(self):
        ctx = self.Ctx(fixture(), {1360: {}})
        mx._handler(ctx, self.Mod({"mastery": {"families": [1350]}}), None)
        with self.assertRaises(ValueError):
            mx._finalize(ctx)

    def test_finalizer_does_nothing_without_families(self):
        exe = fixture()
        ctx = self.Ctx(exe, {})
        mx._finalize(ctx)
        self.assertEqual(ctx.outputs["EXE/disgaea5.exe"], exe)


class LeaseTests(unittest.TestCase):
    """P1: the family -> slot mapping is persisted and never re-derived from the enabled set.

    The save holds six anonymous counter arrays, so a slot does not carry its family's name: re-deriving the
    mapping from the sorted enabled set moved one family's saved progress to another as soon as a family was
    added or removed below it.
    """

    def test_adding_a_lower_family_does_not_move_an_existing_one(self):
        leases = mx.SlotLeases(None, log=lambda *_: None)
        self.assertEqual(leases.assign([1360]), {1360: 47})
        self.assertEqual(leases.assign([1350, 1360]), {1350: 48, 1360: 47})

    def test_removing_a_family_reserves_its_slot_and_re_enabling_finds_it(self):
        leases = mx.SlotLeases(None, log=lambda *_: None)
        leases.assign([1350, 1360])
        leases.assign([1360])
        self.assertNotIn(1350, leases.slots)
        self.assertEqual(leases.retired[1350], 47)
        self.assertEqual(leases.assign([1350, 1360]), {1350: 47, 1360: 48})

    def test_a_slot_is_never_given_to_a_second_family(self):
        leases = mx.SlotLeases(None, log=lambda *_: None)
        leases.assign([1350, 1360, 1370, 1380, 1390, 1400])
        with self.assertRaises(ValueError) as caught:
            leases.assign([1350, 1360, 1370, 1380, 1390, 1400, 1410])
        self.assertIn("no free mastery slot", str(caught.exception))
        self.assertIn("1410", str(caught.exception))

    def test_leases_round_trip_through_the_file(self):
        import json
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, mx.LEASE_FILE)
            first = mx.SlotLeases(path, log=lambda *_: None)
            first.assign([1350, 1360])
            first.save()
            second = mx.SlotLeases.load(path, log=lambda *_: None)
            self.assertEqual(second.assign([1350]), {1350: 47})
            self.assertEqual(second.retired, {1360: 48})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["version"], mx.LEASE_VERSION)

    def test_a_damaged_lease_file_refuses_instead_of_renumbering(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, mx.LEASE_FILE)
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")
            with self.assertRaises(ValueError):
                mx.SlotLeases.load(path, log=lambda *_: None)

    def test_the_built_section_records_its_mapping(self):
        exe = mx.build_patch(fixture(), [1350, 1360])
        self.assertEqual(mx.read_mapping(exe), {1350: 47, 1360: 48})

    def test_a_build_adopts_the_mapping_of_the_install_it_replaces(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ctx = InstallTests.Ctx(fixture(), {1350: {}, 1360: {}}, game_dir=d)
            mx._handler(ctx, InstallTests.Mod({"mastery": {"families": [1350, 1360]}}), None)
            mx._finalize(ctx)                              # install #1: 1350 -> 47, 1360 -> 48
            with open(os.path.join(d, "disgaea5.exe"), "wb") as f:   # what the installer wrote into the game
                f.write(ctx.outputs["EXE/disgaea5.exe"])
            os.remove(mx.lease_path(ctx))                  # simulate a kit that predates the lease file
            again = InstallTests.Ctx(fixture(), {1350: {}, 1360: {}}, game_dir=d)
            mx._handler(again, InstallTests.Mod({"mastery": {"families": [1360]}}), None)
            mx._finalize(again)                            # install #2: 1360 alone
            self.assertEqual(mx.read_mapping(again.outputs["EXE/disgaea5.exe"]), {1360: 48})
            leases = mx.SlotLeases.load(mx.lease_path(again), log=lambda *_: None)
            self.assertEqual(leases.slots, {1360: 48})
            self.assertEqual(leases.retired, {1350: 47})


if __name__ == "__main__":
    unittest.main()
