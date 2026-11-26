"""EX-08b — the Recruiter's class list, with the REAL unlock code and the REAL carousel (no stand-ins).

The earlier proof (`tests/test_recruit_ranks.py`) ran the shipped carousel hook with a *stand-in* for
"is this class rank unlocked" (0x1401c5790 / 0x1401c6110).  That hid the two things that actually decide whether an
imported class can appear at all:

* `FUN_1401c6110` opens with a class-id range gate -- `(id - 2010) <= 0x122` (monsters 2010..2300) or
  `(id - 1000) <= 0x136` (humans 1000..1310) -- and returns 0 *before* the (hooked) table lookup for any other id.
  Family 1350 and every family of its own are outside it.  The installer widens it (`newclasses.generic_patch`:
  `cmp eax, 0x3E7` in place, the monster test to a stub); a stand-in never noticed, so an exe without the widening
  would have passed the old test.
* the unlock flag of a class is set by the lookup hook the first time the class is asked about, so a save with the
  flag at 0 still lists the class -- but only if that hook is installed.

This test therefore runs the bytes of the *built* exe: `newclasses.build_hooks` on the pinned game exe, then the
whole Hire Character list builder `0x140664df0` on Unicorn x86-64, with the game's own `char.dat` runtime layout
and a save-like flag bitmap.  Only the char.dat rows for the imported family are supplied (id at +0xD0,
`dlc_group` at +0xF2), because the game loads them from its database at boot.
"""
import os
import struct
import tempfile
import unittest

from d5lib import exemap, exepatch, newclasses

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_RCX, UC_X86_REG_RIP, UC_X86_REG_RSP)
    HAVE_UNICORN = True
except ImportError:                                    # pragma: no cover - optional analysis dependency
    HAVE_UNICORN = False

IMAGE = exemap.IMAGE_BASE
BUILDER = 0x140664DF0            # the Hire Character / Reincarnation class list builder
COUNT_G = 0x140A03888            # char.dat row count as the game keeps it
PTR_G = 0x140A03880              # char.dat row table
FLAGS = 0x140A00000              # patched per build: the flag bitmap is at exemap(0x144FFA9AE)
CHARTAB = 0x147000000            # unused .data (scratch for the row table)
OBJECT = 0x147800000             # the list object: entries +0x90, count +0x208
STACK = 0x10000000
FAMILY = 1350
RANKS = [FAMILY + k for k in range(6)]
ROW = 0x38C                      # char.dat record size


def pinned_exe():
    """the pinned original exe of this checkout, if this machine has it (the test skips otherwise)"""
    from pathlib import Path
    rel = Path("D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
    here = Path(__file__).resolve()
    for parent in here.parents[:6]:
        if (parent / rel).is_file():
            return str(parent / rel)
    return None


def sections(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 0x18
    base = struct.unpack_from("<Q", data, opt + 0x18)[0]
    size = struct.unpack_from("<I", data, opt + 0x38)[0]
    secoff = opt + struct.unpack_from("<H", data, pe + 0x14)[0]
    out = []
    for i in range(nsec):
        o = secoff + 40 * i
        name = data[o:o + 8].rstrip(b"\0").decode("latin1")
        vs, va, rs, ro = struct.unpack_from("<IIII", data, o + 8)
        out.append((name, va, vs, rs, ro))
    return base, size, out


def read_entry_buffer(exe, site):
    """address the carousel hook writes its entries to: the first `lea rdx, [rip + ...]` of the hook body"""
    base, _, secs = sections(exe)

    def off(va):
        for name, v, vs, rs, ro in secs:
            if v <= va - base < v + max(vs, rs):
                return ro + (va - base - v)
        return None

    def at(va):
        for name, v, vs, rs, ro in secs:                   # the hook site -> its jmp target
            if v <= va - base < v + max(vs, rs):
                o = ro + (va - base - v)
                if exe[o] == 0xE9:
                    return va + 5 + struct.unpack_from("<i", exe, o + 1)[0]
        return None

    hook = at(site)
    assert hook, f"no hook at {site:#x}"
    body = exe[off(hook):off(hook) + 0x100]      # the append loop reaches its buffer `lea` a little later now
    k = body.find(bytes.fromhex("488d15"))                 # lea rdx, [rip + x]
    assert k >= 0, "the carousel hook does not name its entry buffer"
    return hook + k + 7 + struct.unpack_from("<i", body, k + 3)[0]


def char_rows(families):
    """the runtime char.dat rows for `families`: id at +0xD0, dlc_group 100 (base game) at +0xF2, sorted by id"""
    rows = []
    for f in families:
        r = bytearray(ROW)
        struct.pack_into("<I", r, 0xD0, f)
        struct.pack_into("<H", r, 0xF2, 100)
        rows.append(bytes(r))
    return b"".join(rows)


class RealUnlockCodeTests(unittest.TestCase):
    """`build_hooks` output executed as code: the pinned exe, the kit's own hooks, a save-like flag bitmap"""

    @classmethod
    def setUpClass(cls):
        cls.exe_path = pinned_exe()
        if not cls.exe_path:
            raise unittest.SkipTest("the pinned game exe is not in the kit's game state")
        with open(cls.exe_path, "rb") as f:
            cls.pinned = f.read()
        cls.previous = exemap.ACTIVE
        cls.translator = exemap.translator_for(cls.pinned)
        exemap.use(cls.translator)
        cls.flags_va = exemap.ACTIVE(newclasses.FLAGS_VA)
        cls.carousel_site = exemap.ACTIVE(newclasses.CAROUSEL_VA)
        spec = {FAMILY: dict(family=FAMILY, template=1150, name="Male Armor Knight (D4)",
                             unlocked=True, unlocked_ranks=6, evility_alias={})}
        cls.patched = newclasses.build_hooks(cls.pinned, list(RANKS), list(RANKS), {}, (), specs=spec)
        exemap.use(cls.previous)

    def machine(self, exe):
        base, size, secs = sections(exe)
        mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in secs:
            if rs:
                mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
        mu.mem_map(STACK, 0x200000)
        mu.mem_write(CHARTAB, char_rows(RANKS))
        mu.mem_write(PTR_G, struct.pack("<Q", CHARTAB))
        mu.mem_write(COUNT_G, struct.pack("<I", len(RANKS)))
        mu.mem_write(self.flags_va + (17001 >> 3), b"\x00" * ((17999 - 17001) // 8 + 2))
        mu.mem_write(OBJECT, b"\x00" * 0x800)
        return mu, base, secs

    def build_list(self, exe):
        """run 0x140664df0 to completion -> (count, [(class, unlocked ranks)], flag bits of our six ranks)"""
        mu, base, secs = self.machine(exe)
        buf = None
        try:
            buf = read_entry_buffer(exe, self.carousel_site)
        except AssertionError:
            pass                                           # no hook: nothing is appended, and nothing is read
        if buf:
            mu.mem_write(buf, b"\x00" * 0x2000)
        mu.reg_write(UC_X86_REG_RSP, STACK + 0x100000)
        mu.reg_write(UC_X86_REG_RCX, OBJECT)
        try:
            mu.emu_start(BUILDER, 0, count=3000000)
        except UcError:
            pass
        count = struct.unpack("<i", mu.mem_read(OBJECT + 0x208, 4))[0]
        entries = [struct.unpack("<ii", mu.mem_read(buf + 8 * k, 8)) for k in range(count)] if buf else []
        flags = [(mu.mem_read(self.flags_va + (f >> 3), 1)[0] >> (f & 7)) & 1 for f in range(17331, 17337)]
        return count, entries, flags

    @unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the real-code proof")
    def test_the_installed_hooks_list_the_class_with_six_ranks(self):
        count, entries, flags = self.build_list(self.patched)
        self.assertEqual((count, entries), (1, [(FAMILY, 6)]))
        # a save whose flags are all 0 still lists the class: the lookup hook sets its ranks on the way through
        self.assertEqual(flags, [1, 1, 1, 1, 1, 1])

    @unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the real-code proof")
    def test_without_the_kit_hooks_the_class_is_absent(self):
        """the control the stand-in could not give: the same code without the hooks appends nothing"""
        count, entries, flags = self.build_list(self.pinned)
        self.assertEqual((count, entries), (0, []))
        self.assertEqual(flags, [0, 0, 0, 0, 0, 0])

    @unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the real-code proof")
    def test_the_class_id_gate_is_widened_at_install(self):
        """family 1350 is outside the game's own 1000..1310 test; the install must widen it or nothing appears"""
        base, _, secs = sections(self.patched)
        self.assertIn(b"\x3d\xe7\x03\x00\x00", self.patched)          # cmp eax, 0x3E7 (1000..1999)
        gate = self.translator(newclasses.IS_UNLOCKED) + 0xF        # lea eax,[rcx-0x7da] / cmp eax,0x122
        for name, v, vs, rs, ro in secs:
            if v <= gate - base < v + max(vs, rs):
                self.assertEqual(self.patched[ro + gate - base - v], 0xE9)
                break
        else:
            self.fail("the is_unlocked gate site is not mapped")


class RegistryFamilyFlagTests(unittest.TestCase):
    """The unlock-flag table the installer writes must cover registry-identity families (family 14010 and up).

    The installed kit's 1.5.8 `newclasses.flag_of(cls)` indexes `ALL_FAMILIES` by the family itself, so any class a
    registry identity leases for (14010 ...) raises ``ValueError: 14010 is not in list`` and aborts the whole install
    -- the failure seen from the 1.5.8 GUI with the D4 expansion group enabled.  This branch's `flag_of(cls, specs)`
    resolves the lease instead; the three hand-applied EX-08 hunks in a 1.5.8 hybrid do not carry that.
    """

    def setUp(self):
        self.registry = {
            1350: dict(family=1350, template=1150, unlocked=True, unlocked_ranks=6),
            14010: dict(family=14010, template=1010, kind="humanoid", sprite_family=1270,
                        unlocked=True, unlocked_ranks=6),
        }

    def test_registry_family_uses_its_leased_slot_flags(self):
        newclasses.validate_specs(self.registry)                       # no raise: the lease is valid
        self.assertEqual(newclasses.flag_of(14010, self.registry), newclasses.flag_of(1270))
        self.assertEqual(newclasses.flag_of(1350, self.registry), 17331)

    def test_a_registry_family_without_a_spec_is_rejected(self):
        """the 1.5.8 behaviour, kept as the thing the hybrid install must not fall back to"""
        with self.assertRaises(ValueError):
            newclasses.flag_of(14010)

    def test_both_kinds_build_one_class_table(self):
        previous = exemap.ACTIVE
        self.addCleanup(exemap.use, previous)
        path = pinned_exe()
        if path is None:
            self.skipTest("pinned game exe not present")
        with open(path, "rb") as f:
            raw = f.read()
        exemap.use(exemap.translator_for(raw))
        classes = sorted([1350 + k for k in range(6)] + [14010 + k for k in range(6)])
        auto = [c for f, s in self.registry.items() for c in newclasses.auto_ranks(f, s)]
        exe = newclasses.build_hooks(raw, classes, auto, {}, (), specs=self.registry)
        self.assertGreater(sum(1 for a, b in zip(raw, exe) if a != b), 1000)


if __name__ == "__main__":
    unittest.main()
