"""WHEELS — one class wheel per game: the page filter in the real carousel hook.

The hook under test is the Kit's own bytes: `newclasses.build_hooks` on the pinned game exe, then the real list
builder `0x140664df0` (Create Character and Rebirth share it) executed on Unicorn x86-64.  The wheel page is chosen
where the list is built -- the instruction at `CAROUSEL_VA`, whose vanilla job is `cmp rbp,0x2f / jl loop` -- and the
entries are rebuilt from the capture the same hook takes.  Nothing is replaced while a menu owns its actors.

Two kinds of proof:

* `test_the_builder_lists_...`: the whole builder runs from its entry with the real unlock code (as
  `test_recruit_runtime` does), so the filter does not disturb the classes the Kit already lists.
* `SeededPageTests`: the buffer arrives as the vanilla loop would leave it (entries + count + the capture), the hook
  entry is entered with `rbp` past the loop and a synthetic keyboard state, and every page is checked: which wheel a
  family lands on, the 5-wheel cycle, Shift+digit, an empty wheel falling through, the six-entry minimum and the -1
  entries past the count.

Offline only: no game, no save, no install.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from d5lib import exemap, newclasses                      # noqa: E402

from test_recruit_runtime import (BUILDER, CHARTAB, COUNT_G, FAMILY, OBJECT, PTR_G,  # noqa: E402
                                  RANKS, STACK, char_rows, pinned_exe, read_entry_buffer, sections)

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_RCX, UC_X86_REG_RBP, UC_X86_REG_RDI, UC_X86_REG_RIP,
                                   UC_X86_REG_RSP, UC_X86_REG_RAX, UC_X86_REG_R9)
    HAVE_UNICORN = True
except ImportError:                                        # pragma: no cover - optional analysis dependency
    HAVE_UNICORN = False

SHIFT, DIGIT_1 = 0x10, 0x31
A, B, C = 1350, 1270, 1280        # three Kit class families (human dummy slots); wheels assigned per test
# WHEELS4: the hook reads the game's own per-frame key state instead of calling GetKeyboardState, so a test
# only has to write the 256 VK bytes where the input update would leave them (newclasses.WHEEL_KEY_STATE).


def keys(shift=False, digit=0, extra=()):
    state = bytearray(256)
    if shift:
        state[SHIFT] = 0x80
    if digit:
        state[DIGIT_1 + digit - 1] = 0x80
    for vk in extra:
        state[vk] = 0x80
    return bytes(state)


def build(wheels, families=(A,)):
    """the pinned exe with the Kit's class hooks, the wheel owner map and `families` enabled"""
    pinned = Path(pinned_exe()).read_bytes() if pinned_exe() else None
    if pinned is None:
        raise unittest.SkipTest("the pinned game exe is not in the kit's game state")
    previous = exemap.ACTIVE
    exemap.use(exemap.translator_for(pinned))
    try:
        specs = {A: dict(family=A, template=1150, name="A", unlocked=True, unlocked_ranks=6, evility_alias={})}
        classes = [f + k for f in families for k in range(6)]
        exe = newclasses.build_hooks(pinned, classes, classes, {}, (), specs=specs, wheel_entries=wheels)
    finally:
        exemap.use(previous)
    return pinned, exe, exemap.translator_for(pinned)


def offsets(exe):
    base, size, secs = sections(exe)
    return base, size, secs


def file_offset(exe, va):
    base, _, secs = sections(exe)
    for name, v, vs, rs, ro in secs:
        if v <= va - base < v + max(vs, rs):
            return ro + (va - base - v)
    raise AssertionError(f"{va:#x} is not mapped")


class SeededPageTests(unittest.TestCase):
    """the hook's page filter, entered where the native builder falls out of its loop"""

    @classmethod
    def setUpClass(cls):
        cls.pinned, cls.exe, cls.translator = build([(B, 1), (C, 2)])
        cls.base, cls.size, cls.secs = offsets(cls.exe)
        cls.site = cls.translator(newclasses.CAROUSEL_VA)
        cls.done = cls.translator(newclasses.CAROUSEL_DONE)
        o = file_offset(cls.exe, cls.site)
        assert cls.exe[o] == 0xE9, "the carousel site is not hooked"
        cls.hook = cls.site + 5 + struct.unpack_from("<i", cls.exe, o + 1)[0]
        cls.entry = read_entry_buffer(cls.exe, cls.site)          # == the section base (carousel_buf)
        cls.keys = cls.translator(newclasses.WHEEL_KEY_STATE)      # the game's per-frame key state (data)

    def machine(self):
        mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(self.base, (self.size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in self.secs:
            if rs:
                mu.mem_write(self.base + va, self.exe[ro:ro + min(vs, rs)])
        mu.mem_map(STACK, 0x200000)
        mu.mem_write(self.keys, bytes(256))                       # nothing held, as on a fresh frame
        mu.mem_write(OBJECT, b"\x00" * 0x800)
        mu.mem_write(self.entry, b"\x00" * (newclasses.CAROUSEL_CAP * 8))   # entries only: the wheel header is
        # in the image (wheel_shared_bytes), exactly as the installer writes it
        return mu

    def seed(self, mu, entries, owners=(), page=0, enabled=True):
        """the buffer as the vanilla loop + the Kit's append leave it, plus the capture the hook takes"""
        h = self.entry + newclasses.WHEEL_HEADER
        mu.mem_write(h, struct.pack("<8sIIIII", b"D5WHEEL1", 1 if enabled else 0, len(owners),
                                    len(entries), page, page))
        for i, (family, wheel) in enumerate(sorted(owners)):
            mu.mem_write(self.entry + newclasses.WHEEL_OWNERS + 4 * i, struct.pack("<HBB", family, wheel, 0))
        for i, (family, ranks) in enumerate(entries):
            mu.mem_write(self.entry + 8 * i, struct.pack("<ii", family, ranks))
            mu.mem_write(self.entry + newclasses.WHEEL_SNAPSHOT + 8 * i, struct.pack("<ii", family, ranks))
        mu.mem_write(OBJECT + 0x208, struct.pack("<i", len(entries)))

    def run_hook(self, mu, key_state, held=True):
        """enter the hook where the native loop finishes; `held` writes the key state the input update left."""
        mu.reg_write(UC_X86_REG_RSP, STACK + 0x100000)            # 16-aligned: the builder site's alignment
        mu.reg_write(UC_X86_REG_RDI, OBJECT)
        mu.reg_write(UC_X86_REG_RBP, 0x2F)                        # the native loop is finished
        mu.mem_write(self.keys, key_state if held else bytes(256))
        self.last_rsp = []

        def at_done(m, addr, n, _):
            m.emu_stop()
        mu.hook_add(UC_HOOK_CODE, at_done, begin=self.done, end=self.done)
        mu.emu_start(self.hook, 0, count=2000000)
        return []                                                 # no call leaves the hook any more (WHEELS4)

    def result(self, mu):
        n = struct.unpack("<i", mu.mem_read(OBJECT + 0x208, 4))[0]
        entries = [struct.unpack("<ii", mu.mem_read(self.entry + 8 * k, 8)) for k in range(n)]
        page = struct.unpack("<I", mu.mem_read(self.entry + newclasses.WHEEL_HEADER + newclasses.WHEEL_PAGE, 4))[0]
        tail = [struct.unpack("<ii", mu.mem_read(self.entry + 8 * k, 8)) for k in range(n, n + 3)]
        return n, entries, page, tail

    # ---- which wheel a family lands on ----
    def test_the_d5_wheel_keeps_vanilla_and_unowned_families(self):
        mu = self.machine()
        self.seed(mu, [(1010, 6), (1020, 6), (A, 6)], owners=[(B, 1)])
        self.run_hook(mu, keys(shift=True, digit=1))
        n, entries, page, _ = self.result(mu)
        self.assertEqual((n, page), (6, 0))                        # three families, repeated once to six
        self.assertEqual(entries, [(1010, 6), (1020, 6), (A, 6)] * 2)

    def test_initial_no_key_keeps_the_full_list(self):
        mu = self.machine()
        entries = [(1010, 6), (B, 4), (C, 6)]
        self.seed(mu, entries, owners=[(B, 1), (C, 2)], page=newclasses.WHEEL_PAGES)
        self.run_hook(mu, keys())
        self.assertEqual(self.result(mu)[:3], (3, entries, newclasses.WHEEL_PAGES))

    def test_a_mod_wheel_shows_only_its_own_families(self):
        mu = self.machine()
        self.seed(mu, [(1010, 6), (B, 4), (C, 6)], owners=[(B, 1), (C, 2)])
        self.run_hook(mu, keys(shift=True, digit=2))
        n, entries, page, _ = self.result(mu)
        self.assertEqual((n, page), (6, 1))                       # one entry, repeated to the six the grid needs
        self.assertEqual(entries, [(B, 4)] * 6)

    def test_each_wheel_shows_exactly_its_own_family(self):
        for digit, wheel, expected in ((1, 0, 1010), (2, 1, B), (3, 2, C)):
            mu = self.machine()
            self.seed(mu, [(1010, 6), (B, 6), (C, 6)], owners=[(B, 1), (C, 2)])
            self.run_hook(mu, keys(shift=True, digit=digit))
            n, entries, page, _ = self.result(mu)
            self.assertEqual((n, page, {f for f, _ in entries}), (6, wheel, {expected}))

    # ---- the toggle ----
    def test_shift_alone_walks_to_the_next_wheel_and_sticks(self):
        mu = self.machine()
        self.seed(mu, [(1010, 6), (B, 6)], owners=[(B, 1)])
        self.run_hook(mu, keys(shift=True))
        n, entries, page, _ = self.result(mu)
        self.assertEqual((page, entries), (1, [(B, 6)] * 6))
        # the next opening without a key keeps the wheel the last build stored
        mu2 = self.machine()
        self.seed(mu2, [(1010, 6), (B, 6)], owners=[(B, 1)], page=1)
        self.run_hook(mu2, keys())
        self.assertEqual(self.result(mu2)[:3], (6, [(B, 6)] * 6, 1))

    def test_shift_to_an_empty_page_returns_the_full_list(self):
        mu = self.machine()
        self.seed(mu, [(1010, 6), (B, 6)], owners=[(B, 1)], page=1)
        self.run_hook(mu, keys(shift=True))
        n, entries, page, _ = self.result(mu)
        self.assertEqual((page, entries), (newclasses.WHEEL_PAGES, [(1010, 6), (B, 6)]))

    def test_an_empty_wheel_falls_through_to_the_full_list(self):
        mu = self.machine()
        self.seed(mu, [(1010, 6), (C, 6)], owners=[(C, 2)])
        self.run_hook(mu, keys(shift=True))                       # page 1 has no family
        n, entries, page, _ = self.result(mu)
        self.assertEqual((page, entries), (newclasses.WHEEL_PAGES, [(1010, 6), (C, 6)]))

    def test_an_empty_list_is_not_filtered(self):
        """nothing captured (no class at all): the guard leaves the native list alone"""
        mu = self.machine()
        self.seed(mu, [], owners=[(B, 1)])
        self.run_hook(mu, keys(shift=True))
        n, entries, page, _ = self.result(mu)
        self.assertEqual((n, entries, page), (0, [], 0))      # nothing to remember either

    def test_without_wheel_metadata_the_list_is_not_filtered(self):
        """an install with no `wheel` metadata (every existing profile) behaves exactly as before the filter"""
        mu = self.machine()
        self.seed(mu, [(1010, 6), (B, 6), (C, 6)], owners=[(B, 1), (C, 2)], enabled=False)
        self.run_hook(mu, keys(shift=True, digit=2))
        n, entries, page, _ = self.result(mu)
        self.assertEqual((n, entries, page), (3, [(1010, 6), (B, 6), (C, 6)], 0))

    def test_a_lost_keyboard_keeps_the_stored_wheel(self):
        mu = self.machine()
        self.seed(mu, [(1010, 6), (B, 6)], owners=[(B, 1)], page=1)
        self.run_hook(mu, keys(shift=True, digit=2), held=False)  # the input update saw no key at all
        self.assertEqual(self.result(mu)[:3], (6, [(B, 6)] * 6, 1))

    # ---- the buffer invariants the selected-entry calls rely on ----
    def test_a_long_wheel_is_kept_whole_and_the_tail_cleared(self):
        many = [(10000 + 10 * i, 1) for i in range(8)]
        mu = self.machine()
        self.seed(mu, [(1010, 6)] + many, owners=[(f, 1) for f, _ in many], page=1)
        self.run_hook(mu, keys())
        n, entries, page, tail = self.result(mu)
        self.assertEqual((n, page), (8, 1))
        self.assertEqual(entries, many)                            # in capture order, not repeated
        self.assertEqual(tail[0], (-1, -1))                        # the entry the old list left is cleared

    def test_selecting_every_position_of_a_filtered_wheel_reads_inside_it(self):
        """the D1CWEDGE3 property: every entry the wheel shows is a family whose ranks exist"""
        many = [(10000 + 10 * i, 1) for i in range(8)]
        mu = self.machine()
        self.seed(mu, [(1010, 6)] + many, owners=[(f, 1) for f, _ in many], page=1)
        self.run_hook(mu, keys())
        n, entries, _, _ = self.result(mu)
        self.assertEqual([f for f, _ in entries], [f for f, _ in many])
        self.assertTrue(all(1 <= ranks <= 6 for _, ranks in entries))

    def test_the_capture_survives_filtering(self):
        many = [(10000 + 10 * i, 1) for i in range(7)]
        mu = self.machine()
        self.seed(mu, [(1010, 6), (1020, 6)] + many, owners=[(f, 1) for f, _ in many], page=1)
        self.run_hook(mu, keys())
        snap = struct.unpack("<I", mu.mem_read(self.entry + newclasses.WHEEL_HEADER + newclasses.WHEEL_NSNAP, 4))[0]
        self.assertEqual(snap, 9)                                  # the next switch rebuilds from all nine
        self.assertEqual(self.result(mu)[0], 7)


class RealBuilderTests(unittest.TestCase):
    """the whole builder, entered as the game enters it: the filter must not disturb the Kit's list"""

    @classmethod
    def setUpClass(cls):
        cls.pinned, cls.exe, cls.translator = build([(B, 1)])
        cls.site = cls.translator(newclasses.CAROUSEL_VA)
        cls.entry = read_entry_buffer(cls.exe, cls.site)
        cls.keys = cls.translator(newclasses.WHEEL_KEY_STATE)
        cls.base, cls.size, cls.secs = offsets(cls.exe)
        cls.flags = cls.translator(newclasses.FLAGS_VA)

    def run_builder(self, key_state):
        mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(self.base, (self.size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in self.secs:
            if rs:
                mu.mem_write(self.base + va, self.exe[ro:ro + min(vs, rs)])
        mu.mem_map(STACK, 0x200000)
        mu.mem_write(self.keys, key_state)
        mu.mem_write(CHARTAB, char_rows(RANKS))
        mu.mem_write(PTR_G, struct.pack("<Q", CHARTAB))
        mu.mem_write(COUNT_G, struct.pack("<I", len(RANKS)))
        mu.mem_write(self.flags + (17001 >> 3), b"\x00" * ((17999 - 17001) // 8 + 2))
        mu.mem_write(OBJECT, b"\x00" * 0x800)
        mu.mem_write(self.entry, b"\x00" * (newclasses.CAROUSEL_CAP * 8))   # entries only: the wheel header is
        # in the image (wheel_shared_bytes), exactly as the installer writes it

        mu.reg_write(UC_X86_REG_RSP, STACK + 0x100000 + 8)        # as a CALL into the builder leaves it
        mu.reg_write(UC_X86_REG_RCX, OBJECT)
        try:
            mu.emu_start(BUILDER, 0, count=3000000)
        except UcError:
            pass
        n = struct.unpack("<i", mu.mem_read(OBJECT + 0x208, 4))[0]
        return n, [struct.unpack("<ii", mu.mem_read(self.entry + 8 * k, 8)) for k in range(n)]

    @unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the real-code proof")
    def test_the_real_builder_still_lists_its_class_on_the_d5_wheel(self):
        n, entries = self.run_builder(keys(shift=True, digit=1))
        self.assertEqual((n, entries), (6, [(FAMILY, 6)] * 6))

    @unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the real-code proof")
    def test_the_real_builder_keeps_the_class_off_another_wheel(self):
        n, entries = self.run_builder(keys(shift=True, digit=2))   # wheel 1; A is on wheel 0
        self.assertEqual(entries, [(FAMILY, 6)])                  # returns to the full captured list
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
