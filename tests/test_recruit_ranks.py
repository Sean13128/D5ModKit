"""Recruiter / Reincarnation rank rows for imported classes (EX-08).

The native class list builder (0x140664df0) adds one 8-byte entry per family -- {class, highest unlocked rank} --
and skips a family whose first rank is locked.  The Hire Character screen's rank option row stops at that count and
previews ``entry.class + option`` (0x140661e60, ``param_1 + 0x94 + sel * 8``), and the Reincarnation window reads the
same word (0x14047f1c0).  Nothing else -- JobRank rows, mastery level, a 47/53 table -- gates the offered ranks.

These tests run the carousel hook body the Kit actually installs, on a real x86-64 model, with a stand-in for
"is this class rank unlocked" (0x1401c5790).  Only the shared-buffer placeholder (``{shared}``) and that stand-in are
supplied by the test; the rest is the shipped hook source.
"""
import struct
import unittest

from d5lib import exemap, exepatch, newclasses

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError
    from unicorn.x86_const import UC_X86_REG_RBP, UC_X86_REG_RDI, UC_X86_REG_RSP
    HAVE_UNICORN = True
except ImportError:                                   # pragma: no cover - optional analysis dependency
    HAVE_UNICORN = False

IMAGE = exemap.IMAGE_BASE
CODE = 0x1406F0000                                     # where the hook body is placed for the run
BUFFER = 0x140500000                                   # the section's shared carousel buffer
OBJECT = 0x140600000                                   # the scene object: entries +0x90, count +0x208
STACK = 0x140300000
DONE = 0x140667506                                     # hook tail -> vanilla continuation
ENTRY = 0x90                                           # entries (class, unlocked ranks), 8 bytes each
COUNT = 0x208                                          # entry count


def _stub(unlocked):
    """is-class-rank-unlocked stand-in: al = 1 when ecx is in `unlocked`"""
    ids = sorted(unlocked)
    lines = ["    xor eax, eax"]
    for n, i in enumerate(ids):
        lines += [f"    cmp ecx, {i}", f"    je yes{n}"]
    lines += ["    ret"] + [f"yes{n}:" for n in range(len(ids))] + ["    mov al, 1", "    ret"]
    return exepatch._asm("\n".join(lines), newclasses.IS_UNLOCKED)


@unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the hook semantics proof")
class CarouselRankCountTests(unittest.TestCase):
    def setUp(self):
        self.previous = exemap.ACTIVE
        self.addCleanup(exemap.use, self.previous)
        # passthrough: the empty map plus an image_end of the base itself leaves every address as written
        exemap.use(exemap.Translator("test-passthrough", {}, image_end=IMAGE + 1))
        self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        # one 16 MB window holds the .text stub/jump target and every address the test places below 0x141000000
        self.mu.mem_map(IMAGE, 0x1000000)
        src = newclasses._carousel_src([1350]).replace("{shared}", hex(BUFFER))
        self.mu.mem_write(CODE, exepatch._asm(src, CODE))
        self.mu.mem_write(DONE, b"\xcc")               # end of run: int3 -> exception

    def run_hook(self, unlocked, count=0):
        self.mu.mem_write(newclasses.IS_UNLOCKED, _stub(unlocked))
        self.mu.mem_write(OBJECT + ENTRY, b"\xff" * 0x180)
        self.mu.mem_write(OBJECT + COUNT, struct.pack("<i", count) + b"\x00" * 8)
        self.mu.mem_write(BUFFER, b"\xff" * 0x1000)
        self.mu.reg_write(UC_X86_REG_RSP, STACK + 0x8000)
        self.mu.reg_write(UC_X86_REG_RDI, OBJECT)
        self.mu.reg_write(UC_X86_REG_RBP, 0x2F)        # the vanilla loop finished: run our appended families
        try:
            self.mu.emu_start(CODE, 0, count=4000)
        except UcError:
            pass                                       # int3 at DONE
        n = struct.unpack("<i", self.mu.mem_read(OBJECT + COUNT, 4))[0]
        # the entries themselves live in the section's shared buffer; every reader was moved there
        entries = [struct.unpack("<ii", self.mu.mem_read(BUFFER + 8 * k, 8)) for k in range(n)]
        return n, entries

    def test_six_flags_offer_all_six_ranks(self):
        self.assertEqual(self.run_hook(range(1350, 1356)), (1, [(1350, 6)]))

    def test_three_flags_offer_three_ranks(self):
        self.assertEqual(self.run_hook(range(1350, 1353)), (1, [(1350, 3)]))

    def test_one_flag_offers_one_rank(self):
        self.assertEqual(self.run_hook([1350]), (1, [(1350, 1)]))

    def test_highest_unlocked_rank_wins(self):
        # a gap (rank 2 locked, rank 3 unlocked) still reports the highest rank, as the vanilla builder does
        self.assertEqual(self.run_hook([1350, 1352]), (1, [(1350, 3)]))

    def test_locked_family_adds_no_entry(self):
        self.assertEqual(self.run_hook([2000]), (0, []))

    def test_existing_entries_are_appended(self):
        self.assertEqual(self.run_hook(range(1350, 1356), count=47)[0], 48)


def pinned_exe():
    """the pinned original exe of this checkout, if this machine has it (the test skips otherwise)"""
    from pathlib import Path
    rel = Path("D5ModKit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
    here = Path(__file__).resolve()
    for parent in here.parents[:6]:
        if (parent / rel).is_file():
            return parent / rel
    return None


class RebirthWheelCoverageTests(unittest.TestCase):
    """The Reincarnation window's wheel reads must use the relocated carousel buffer, exactly like the hire screen."""

    def test_rebirth_and_hire_reads_are_relocated_sites(self):
        path = pinned_exe()
        if path is None:
            self.skipTest("pinned game exe not present")
        import re
        import capstone
        import pefile
        exe = path.read_bytes()
        pe = pefile.PE(data=exe, fast_load=True)
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        pattern = re.compile(r"\[(\w+)(?: \+ (\w+)\*(\d))? \+ (0x[0-9a-f]+)\]")
        translator = exemap.translator_for(exe)
        sites = {translator(va) for va in newclasses.CAROUSEL_SITES}
        self.addCleanup(exemap.use, exemap.ACTIVE)
        exemap.use(translator)
        covered = 0
        # (function, size): the Reincarnation window, its list handler, and the hire wizard's class/rank selection
        for va, size in ((0x14047F1C0, 7712), (0x140480FF0, 3203), (0x140661E60, 3520)):
            off = pe.get_offset_from_rva(va - exemap.IMAGE_BASE)
            for ins in md.disasm(exe[off:off + size], va):
                m = pattern.search(ins.op_str)
                if not m or int(m.group(4), 16) not in (0x90, 0x94) or not m.group(2):
                    continue
                self.assertIn(ins.address, sites, f"unrelocated carousel read at {ins.address:#x}: {ins.op_str}")
                covered += 1
        self.assertEqual(covered, 21)                     # 7 per screen; a moved build changes this count


class SharedBufferTests(unittest.TestCase):
    """P2: the carousel/proficiency buffers are process-global, so a nested build must not overwrite one in use."""

    def test_the_carousel_stub_takes_a_build_guard(self):
        src = newclasses._carousel_src([1350])
        self.assertIn(f"cmp dword ptr [rcx + {newclasses.BUF_GUARD}], 0", src)
        self.assertIn("jne cr_busy", src)
        self.assertIn("cr_busy:", src)
        # the guard word is outside every list buffer
        self.assertGreaterEqual(newclasses.BUF_SIZE, newclasses.BUF_PROF + newclasses.CLASSTAB_CAP * 4 + 4)

    def test_the_guard_is_only_taken_on_the_modded_path(self):
        lines = newclasses._carousel_src([1350]).splitlines()
        self.assertLess(lines.index(f"    jl {newclasses.CAROUSEL_LOOP:#x}"),
                        lines.index("    lea rcx, [rip + carousel_buf]"),
                        "the vanilla branch out of the stub must not have rcx clobbered first")


class DefaultUnlockedRanksTests(unittest.TestCase):
    """Every imported class offers all of its ranks unless the spec asks for a lower ceiling."""

    def test_auto_ranks_defaults_to_six(self):
        self.assertEqual(newclasses.auto_ranks(1350, {"unlocked": True}), list(range(1350, 1356)))
        self.assertEqual(newclasses.auto_ranks(14080, {"unlocked": True, "sprite_family": 1360}),
                         list(range(14080, 14086)))

    def test_explicit_ceiling_and_disabled(self):
        self.assertEqual(newclasses.auto_ranks(1350, {"unlocked": True, "unlocked_ranks": 3}),
                         [1350, 1351, 1352])
        self.assertEqual(newclasses.auto_ranks(1350, {"unlocked": False}), [])

    def test_the_class_spec_written_for_a_new_class_asks_for_six(self):
        # the D4 importer (d5lib/sourceimports) is a separate lane and is not part of this port: what this kit
        # owns is the spec it writes for a class, which must default to all six ranks.
        self.assertEqual(newclasses.auto_ranks(14080, {"unlocked": True, "sprite_family": 1360}),
                         list(range(14080, 14086)))


if __name__ == "__main__":
    unittest.main()
