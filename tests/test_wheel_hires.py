"""WHEELS3 — the class under the cursor, after the page filter, for both menus.

WHEELS2 proved the page *list*; it never proved the thing the menu then does with it: take the
cursor, index the list, hire that class.  This file proves that end of the contract on the real
built bytes:

* `PageHireTests`: the whole Hire Character builder `0x140664df0` runs with a mixed list (the game's
  own families plus 58 mod families on the D4 and D1C wheels).  For each page and **each cursor
  position**, the entry is read the way the game reads it -- by executing the relocated read stub
  at the site the game uses (the Recruiter's selected-entry reads, and Rebirth's own three reads) --
  and must be the family the page says belongs there.
* `BothMenusTests` (static): the Rebirth scene's enter (`0x140483710`, vtable 0x14098bc90 +8) calls
  the Recruiter enter (`0x140663b20`), whose builder call is the hooked site, so one page value
  drives both menus.
* `KeyboardCallTests`: the one CALL the filter adds goes through the GetKeyboardState import
  address slot (data, not code) and lands 16-byte aligned with 32 bytes of home space -- measured
  in the emulator at the callee and read from the emitted bytes.

Offline only: the pinned game exe as the kit's build base; no game, no save, no install.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from d5lib import exemap, newclasses                            # noqa: E402

from test_recruit_runtime import (BUILDER, CHARTAB, COUNT_G, OBJECT, PTR_G,  # noqa: E402
                                  STACK, char_rows, pinned_exe, read_entry_buffer, sections)

try:
    from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError)
    from unicorn.x86_const import (UC_X86_REG_RAX, UC_X86_REG_RBX, UC_X86_REG_RCX, UC_X86_REG_RDX,
                                   UC_X86_REG_RIP, UC_X86_REG_RSI, UC_X86_REG_RDI, UC_X86_REG_RSP,
                                   UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_R10, UC_X86_REG_R11,
                                   UC_X86_REG_R12, UC_X86_REG_R13, UC_X86_REG_R14, UC_X86_REG_R15)
    HAVE_UNICORN = True
except ImportError:                                              # pragma: no cover
    HAVE_UNICORN = False

STUB = 0x180000000                       # a stand-in for the imported GetKeyboardState: mov eax,1 / ret
VANILLA_HUMAN = list(range(1010, 1260, 10))          # the 25 human hire families (their flags are the game's)
D5_MOD = [1330, 1340]                                # two mods left on the D5 wheel
D4 = [1400 + 10 * i for i in range(45)]              # 45 D4 classes -> wheel 1
D1C = [1850 + 10 * i for i in range(13)]             # 13 D1C classes -> wheel 2
MODS = D5_MOD + D4 + D1C

# the reads the game itself uses, as the kit names them (known-build addresses -> translated per build)
RECRUITER_FAMILY, RECRUITER_RANKS = 0x14066A7C9, 0x14066A7B5   # [rdi+idx*8+0x90] / [+0x94] in the cursor step
REBIRTH_CLASS, REBIRTH_NEIGHBOUR, REBIRTH_RANKS = 0x140472260, 0x1404724E9, 0x140472949


def keys(shift=False, digit=0):
    st = bytearray(256)
    if shift:
        st[0x10] = 0x80
    if digit:
        st[0x31 + digit - 1] = 0x80
    return bytes(st)


def build(wheels, families):
    pinned = Path(pinned_exe()).read_bytes()
    previous = exemap.ACTIVE
    exemap.use(exemap.translator_for(pinned))
    try:
        specs = {f: dict(family=f, template=1150, name="M", unlocked=True, unlocked_ranks=6, evility_alias={})
                 for f in families}
        classes = [f + k for f in families for k in range(6)]
        exe = newclasses.build_hooks(pinned, classes, classes, {}, (), specs=specs, wheel_entries=wheels)
    finally:
        exemap.use(previous)
    return pinned, exe, exemap.translator_for(pinned)


def file_offset(exe, va):
    base, _, secs = sections(exe)
    for name, v, vs, rs, ro in secs:
        if v <= va - base < v + max(vs, rs):
            return ro + (va - base - v)
    raise AssertionError(f"{va:#x} is not mapped")


def jump_target(exe, va):
    """the stub a relocated site jumps to (must be a 5-byte E9)"""
    o = file_offset(exe, va)
    assert exe[o] == 0xE9, f"{va:#x} is not relocated"
    return va + 5 + struct.unpack_from("<i", exe, o + 1)[0]


def page_of(family):
    if family in D4:
        return 1
    if family in D1C:
        return 2
    return 0


class Machine:
    """the built exe, the real builder, and the game's own per-frame key state (WHEELS4: no call)"""

    def __init__(self, exe, translator, key_state, base, size, secs, entry, keys):
        self.exe, self.translator, self.key_state = exe, translator, key_state
        self.entry, self.keys = entry, keys
        self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu = self.mu
        mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in secs:
            if rs:
                mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
        mu.mem_map(STACK, 0x200000)
        mu.mem_write(keys, key_state)                              # what the input update left for this frame
        mu.mem_write(CHARTAB, char_rows(VANILLA_HUMAN + [f + k for f in MODS for k in range(6)]))
        mu.mem_write(PTR_G, struct.pack("<Q", CHARTAB))
        mu.mem_write(COUNT_G, struct.pack("<I", len(VANILLA_HUMAN) + 6 * len(MODS)))
        flags = translator(newclasses.FLAGS_VA)
        mu.mem_write(flags + (17001 >> 3), b"\xff" * ((21000 - 17001) // 8 + 2))
        mu.mem_write(OBJECT, b"\x00" * 0x800)
        mu.mem_write(entry, b"\x00" * (newclasses.CAROUSEL_CAP * 8))
        self.calls = []

    def build_list(self):
        mu = self.mu
        mu.reg_write(UC_X86_REG_RSP, STACK + 0x100000 + 8)       # as a CALL into the builder leaves it
        mu.reg_write(UC_X86_REG_RCX, OBJECT)
        mu.emu_start(BUILDER, 0, count=20000000)
        return self.count()

    def count(self):
        return struct.unpack("<i", self.mu.mem_read(OBJECT + 0x208, 4))[0]

    def read_site(self, site_known, idx):
        """run the game's own relocated read stub for entry `idx` and return what it loads

        Each stub is `push rX / lea rX,[buf] / mov <dst>,[rX + <idxreg>*8 + k] / pop rX / jmp back`.
        The index register and the destination are read from the stub's own bytes, so a site that
        indexes with a different register is exercised as the game would.
        """
        import capstone
        site = self.translator(site_known)
        stub = jump_target(self.exe, site)
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        cells = list(md.disasm(self.exe[file_offset(self.exe, stub):][:0x30], stub))
        until, index_reg, dest_reg = None, None, None
        for i in cells:
            if i.mnemonic == "jmp":
                until = int(i.op_str, 16)                   # the stub's own tail: stop there
                break
            if i.mnemonic in ("mov", "cmp") and "*8" in i.op_str and "[" in i.op_str:
                assert index_reg is None, "the stub loads more than once"
                m = [t for t in i.op_str.split("[")[1].split("]")[0].split(" + ")]
                cand = [t.split("*")[0].strip() for t in m if "*" in t]
                index_reg = cand[0] if cand else None
                if i.mnemonic == "mov":
                    dest_reg = i.op_str.split(",")[0].strip()
        assert until is not None and index_reg is not None, "the stub is not a bounded indexed read"
        regs = {"rax": UC_X86_REG_RAX, "rbx": UC_X86_REG_RBX, "rcx": UC_X86_REG_RCX, "rdx": UC_X86_REG_RDX,
                "rsi": UC_X86_REG_RSI, "rdi": UC_X86_REG_RDI, "r8": UC_X86_REG_R8, "r9": UC_X86_REG_R9,
                "r10": UC_X86_REG_R10, "r11": UC_X86_REG_R11, "r12": UC_X86_REG_R12, "r13": UC_X86_REG_R13,
                "r14": UC_X86_REG_R14, "r15": UC_X86_REG_R15,
                "eax": UC_X86_REG_RAX, "ebx": UC_X86_REG_RBX, "ecx": UC_X86_REG_RCX, "edx": UC_X86_REG_RDX,
                "esi": UC_X86_REG_RSI, "edi": UC_X86_REG_RDI, "r8d": UC_X86_REG_R8, "r9d": UC_X86_REG_R9,
                "r10d": UC_X86_REG_R10, "r11d": UC_X86_REG_R11, "r12d": UC_X86_REG_R12,
                "r13d": UC_X86_REG_R13, "r14d": UC_X86_REG_R14, "r15d": UC_X86_REG_R15}
        mu = self.mu
        mu.reg_write(regs[index_reg], idx)
        mu.reg_write(UC_X86_REG_RSP, STACK + 0x180000)
        mu.emu_start(stub, until, count=200)                # stops at the stub's jmp back
        if dest_reg is None:
            return None                                     # a `cmp` site: no loaded value
        return struct.unpack("<i", struct.pack("<I", mu.reg_read(regs[dest_reg]) & 0xFFFFFFFF))[0]


class PageHireTests(unittest.TestCase):
    """per page, per cursor position: the entry the game reads is the class the page put there"""

    @classmethod
    def setUpClass(cls):
        if not HAVE_UNICORN:
            raise unittest.SkipTest("unicorn-engine is required")
        if pinned_exe() is None:
            raise unittest.SkipTest("the pinned game exe is not in the kit's game state")
        cls.pinned, cls.exe, cls.translator = build(
            [(f, 1) for f in D4] + [(f, 2) for f in D1C], MODS)
        cls.base, cls.size, cls.secs = sections(cls.exe)
        cls.entry = read_entry_buffer(cls.exe, cls.translator(newclasses.CAROUSEL_VA))
        cls.keys = cls.translator(newclasses.WHEEL_KEY_STATE)

    def machine(self, shift, digit):
        return Machine(self.exe, self.translator, keys(shift, digit),
                       self.base, self.size, self.secs, self.entry, self.keys)

    def expected(self, page):
        return {0: VANILLA_HUMAN + D5_MOD, 1: D4, 2: D1C}[page]

    def test_each_page_under_every_cursor_position(self):
        for page, (shift, digit) in enumerate([(True, 1), (True, 2), (True, 3)]):
            m = self.machine(shift, digit)
            n = m.build_list()
            want = self.expected(page)
            self.assertEqual(n, len(want), f"page {page}: count")
            for cursor in range(n):
                self.assertEqual(m.read_site(RECRUITER_FAMILY, cursor), want[cursor],
                                 f"page {page}: the Recruiter's selected-entry read at cursor {cursor}")

    def test_the_selected_entry_pairs_keep_their_rank_counts(self):
        """the ranks slot is read beside the family (the rank index is clamped to it)"""
        m = self.machine(True, 2)                                  # the D4 page
        n = m.build_list()
        for cursor in range(n):
            self.assertEqual(m.read_site(RECRUITER_RANKS, cursor), 6,
                             f"cursor {cursor}: the page kept the class's unlocked rank count")

    def test_rebirths_own_reads_see_the_same_page(self):
        m = self.machine(True, 3)                                  # the D1C page
        n = m.build_list()
        self.assertEqual(n, len(D1C))
        for cursor in range(n):
            for site in (REBIRTH_CLASS, REBIRTH_NEIGHBOUR):
                self.assertIn(m.read_site(site, cursor), D1C,
                              f"Rebirth read {site:#x} at index {cursor}")
            # the third Rebirth read is a `cmp` (rank count == 1) with no loaded value: check its input
            self.assertEqual(struct.unpack("<i", m.mu.mem_read(self.entry + 8 * cursor + 4, 4))[0], 6)

    def test_a_vanilla_only_page_leaves_the_vanilla_reads_intact(self):
        """page 0 holds the game's own families: the same families, in the same order"""
        m = self.machine(True, 1)
        n = m.build_list()
        self.assertEqual([m.read_site(RECRUITER_FAMILY, i) for i in range(n)], VANILLA_HUMAN + D5_MOD)


class BothMenusTests(unittest.TestCase):
    """static: Rebirth's enter calls the Recruiter's enter, whose builder call is the hooked site"""

    @classmethod
    def setUpClass(cls):
        if pinned_exe() is None:
            raise unittest.SkipTest("the pinned game exe is not in the kit's game state")
        cls.pinned, cls.exe, cls.translator = build([(f, 1) for f in D4], MODS)

    def call_target(self, va):
        o = file_offset(self.exe, va)
        self.assertEqual(self.exe[o], 0xE8, f"{va:#x} is not a CALL")
        return va + 5 + struct.unpack_from("<i", self.exe, o + 1)[0]

    def test_rebirth_enter_calls_the_recruiter_enter(self):
        vtable, slot = 0x14098BC90, 8                              # the Reincarnation (Rebirth) scene
        self.assertEqual(self.call_target(0x140483732), 0x140663B20)
        entered = struct.unpack("<Q", self.pinned[file_offset(self.pinned, vtable + slot):][:8])[0]
        self.assertEqual(entered, 0x140483710, "the Rebirth scene's enter slot")

    def test_the_builder_call_is_the_hooked_site(self):
        builder = self.translator(newclasses.CAROUSEL_VA)
        self.assertEqual(self.call_target(0x140663C32), 0x140664DF0)   # the shared builder
        self.assertEqual(self.exe[file_offset(self.exe, builder)], 0xE9)   # and its tail is the hook


class KeyReadTests(unittest.TestCase):
    """WHEELS4: the page key is a read of the game's own key state -- no call, no stack switch"""

    @classmethod
    def setUpClass(cls):
        if not HAVE_UNICORN:
            raise unittest.SkipTest("unicorn-engine is required")
        if pinned_exe() is None:
            raise unittest.SkipTest("the pinned game exe is not in the kit's game state")
        cls.pinned, cls.exe, cls.translator = build([(f, 1) for f in D4], MODS)
        cls.base, cls.size, cls.secs = sections(cls.exe)
        cls.entry = read_entry_buffer(cls.exe, cls.translator(newclasses.CAROUSEL_VA))
        cls.keys = cls.translator(newclasses.WHEEL_KEY_STATE)

    def hook_bytes(self):
        o = file_offset(self.exe, self.translator(newclasses.CAROUSEL_VA))
        hook = self.translator(newclasses.CAROUSEL_VA) + 5 + struct.unpack_from("<i", self.exe, o + 1)[0]
        return hook, self.exe[file_offset(self.exe, hook):][:0x1000]

    def test_the_hook_calls_nothing_outside_the_game(self):
        """every CALL in the hook body stays in the game image (the two IS_UNLOCKED asks); none leaves it."""
        import capstone
        hook, body = self.hook_bytes()
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        outside = []
        for i in md.disasm(body, hook):
            if i.mnemonic == "call":
                if i.op_str.startswith("0x"):
                    tgt = int(i.op_str, 16)
                    if not self.base <= tgt < self.base + self.size:
                        outside.append((hex(i.address), i.op_str))
                else:
                    outside.append((hex(i.address), i.op_str))       # an indirect call: the callee is unknown
        self.assertEqual(outside, [], f"the builder hook must not call out of the game: {outside}")

    def test_the_key_state_address_is_in_writable_data(self):
        off = file_offset(self.pinned, self.keys)
        base, _, secs = sections(self.pinned)
        name = None
        for nm, v, vs, rs, ro in secs:
            if v <= self.keys - base < v + max(vs, rs):
                name = nm
        self.assertEqual(name, ".data")
        self.assertNotEqual(self.keys, 0)

    def test_the_page_follows_the_key_state_the_game_publishes(self):
        # This build has D4 (page 1) only: an empty D1C page returns to the full list.
        for shift, digit, want in ((False, 0, newclasses.WHEEL_PAGES), (True, 2, 1),
                                   (True, 3, newclasses.WHEEL_PAGES)):
            m = Machine(self.exe, self.translator, keys(shift, digit), self.base, self.size,
                        self.secs, self.entry, self.keys)
            m.build_list()
            got = struct.unpack("<I", m.mu.mem_read(
                self.entry + newclasses.WHEEL_HEADER + newclasses.WHEEL_PAGE, 4))[0]
            self.assertEqual(got, want, f"page for shift={shift} digit={digit}")


if __name__ == "__main__":
    unittest.main()
