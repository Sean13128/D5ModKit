"""WHEELS4 — the Hire Character wedge, reproduced offline on the exact TEST17 build, and the fix.

Why this file exists
--------------------
TEST17 (`6b9b4e93…`, the exe LIVE14 installed) freezes the game on the FIRST *Hire Character* list build,
with or without the page key held: the thread stops inside that build, the runtime's command loop never
answers again, d5auto.log stops on the Recruiter menu (LIVE12 §4, LIVE14 §4).  WHEELS2 and WHEELS3 both
"proved" their fixes on a replay that **never reproduced it**, because every replay put a five-byte
`mov eax,1; ret` stand-in behind the GetKeyboardState import slot.  A callee that returns, clobbers
nothing and needs no lock proves nothing about the live call.

What this replay does differently
---------------------------------
* It runs the **exact TEST17 payload** (`Local/payload/test17-disgaea5.exe`: the bytes INTEG17 built and
  LIVE14 installed), not a rebuild of the old source.
* It runs the **real list builder** `0x140664df0` from its entry with the **live data shape**: the 47
  vanilla families plus the 67 wheel families the build ships, the build's own owner table, the real
  unlock code and the real `char.dat`/flag lookups.
* It installs, behind the import slot, a callee that models what LIVE12/LIVE14 measured: **the call does
  not return** (`jmp $`).  That is not a guess about *which* Wine instruction blocks -- no backtrace was
  ever taken -- it is the measured outcome (no return, sleeping thread, dead pipe).  So the replay asks
  the question the fix has to answer: can this hook survive the keyboard call not coming back?

  test_test17_wedges_the_hire_character_build   NO  -> the build never leaves the builder   (TEST17 bytes)
  test_the_same_build_returns_when_the_call_returns  -> it is the call, and only the call
  FixedHookTests                                the fixed hook never calls anything; the build
                                                returns and the page follows the game's key state

The one thing this file does NOT claim: the instruction inside Wine that does not return.  The fix removes
the call instead of betting on which instruction it is (WHEELS4-REPORT.md).

Offline only: no game, no install, no save.  Skips when the payload or the pinned exe is absent.
"""
import hashlib
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from d5lib import exemap, newclasses                                  # noqa: E402

from test_recruit_runtime import (BUILDER, COUNT_G, PTR_G,  # noqa: E402
                                  STACK, char_rows, pinned_exe, read_entry_buffer, sections)

# the built image reaches 0x1480a8000 (its .d5cl section is there), so the replay's scratch areas sit above it
CHARTAB = 0x170000000
OBJECT = 0x178000000

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UcError, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_RAX, UC_X86_REG_RCX, UC_X86_REG_R10,  # noqa: F401
                                   UC_X86_REG_RIP, UC_X86_REG_RSP)
    HAVE_UNICORN = True
except ImportError:                                            # pragma: no cover - optional analysis dependency
    HAVE_UNICORN = False

ROOT = Path(__file__).resolve().parents[4]
TEST17 = ROOT / "Local/payload/test17-disgaea5.exe"
TEST17_SHA256 = "22f30afd13f6c85090bd35948de2c77fa55b3cf398e2637a470f89dba4dce430"
SLOT = 0x1408CE670                      # USER32!GetKeyboardState's import slot (this build)
EPILOGUE = 0x140664F72                  # the builder's `ret` (pop r15 / pop r14 / pop rdi precede it)
STUB = 0x150000000                      # where the callee stand-in lives
HANG = bytes.fromhex("ebfe")            # jmp $ -- "the call does not return"
RETURNS = bytes.fromhex("4c8bd1" "b814140000" "0f05" "c3")   # win32u!NtUserGetKeyboardState, syscall path
VANILLA = list(range(1000, 1320, 10)) + list(range(2010, 2310, 10))


def file_offset(exe, va):
    base, _, secs = sections(exe)
    for name, v, vs, rs, ro in secs:
        if v <= va - base < v + max(vs, rs):
            return ro + (va - base - v)
    raise AssertionError(f"{va:#x} is not in the image")


def translate(exe, known):
    previous = exemap.ACTIVE
    exemap.use(exemap.translator_for(exe))
    try:
        return exemap.ACTIVE(known)
    finally:
        exemap.use(previous)


def pinned_bytes():
    path = pinned_exe()
    if path is None:
        raise unittest.SkipTest("the pinned game exe is not in the kit's game state")
    return Path(path).read_bytes()


def wheel_header(exe):
    """the owner table the build shipped with; the header starts the shared blob."""
    i = exe.find(b"D5WHEEL1")
    if i < 0:
        raise unittest.SkipTest("this payload carries no wheel metadata")
    magic, enabled, owners, nsnap, page, page2 = struct.unpack_from("<8sIIIII", exe, i)
    rows = [struct.unpack_from("<HBB", exe, i + 28 + 4 * k)[:2] for k in range(owners)]
    return dict(enabled=enabled, page=page, owners=rows)


def mod_families(exe, site):
    """the hook address and its own `.long` family table (the mods the build adds to the wheel)."""
    o = file_offset(exe, site)
    assert exe[o] == 0xE9, "the carousel site is not hooked"
    hook = site + 5 + struct.unpack_from("<i", exe, o + 1)[0]
    body = exe[file_offset(exe, hook):file_offset(exe, hook) + 0x1200]
    k = body.find(bytes.fromhex("488d1d"))                        # lea rbx, [rip + new_fams]
    assert k >= 0, "the hook does not name its family table"
    tgt = hook + k + 7 + struct.unpack_from("<i", body, k + 3)[0]
    fams, i = [], 0
    while True:
        v = struct.unpack_from("<i", exe, file_offset(exe, tgt) + 4 * i)[0]
        if v == 0:
            return hook, fams
        fams.append(v)
        i += 1


class Replay:
    """the real builder, the build's data, and one callee behind the GetKeyboardState slot.

    `callee` is the code the loader would have bound the import to.  `writes` says the callee fills the
    caller's buffer through the syscall ABI (used only for the control case).
    """

    def __init__(self, exe, families, callee, flags_va, site, key_state=None, writes=False, state_va=None):
        """state_va: where the game publishes its per-frame key state (WHEELS4's source); TEST17 ignores it."""
        self.exe, self.site, self.writes = exe, site, writes
        self.base, self.size, self.secs = sections(exe)
        self.key_state = key_state or bytes(256)
        self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu = self.mu
        mu.mem_map(self.base, (self.size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in self.secs:
            if rs:
                mu.mem_write(self.base + va, exe[ro:ro + min(vs, rs)])
        mu.mem_map(STACK, 0x400000)
        mu.mem_map(CHARTAB, 0x200000)
        mu.mem_map(OBJECT, 0x40000)
        mu.mem_map(STUB, 0x1000)
        mu.mem_write(STUB, callee)
        mu.mem_write(SLOT, struct.pack("<Q", STUB))               # what the loader binds
        mu.mem_write(CHARTAB, char_rows(families))
        mu.mem_write(PTR_G, struct.pack("<Q", CHARTAB))
        mu.mem_write(COUNT_G, struct.pack("<I", len(set(families))))
        mu.mem_write(flags_va, b"\xff" * 0x1000)                  # a save with every class unlocked
        mu.mem_write(OBJECT, b"\x00" * 0x40000)
        if state_va is not None:
            mu.mem_write(state_va, self.key_state)                # what the input update left this frame
        self.syscall = STUB + 9
        self.calls = 0
        self.in_stub = False
        self.steps = 0
        self.trace = []
        mu.hook_add(UC_HOOK_CODE, self._code)

    def _code(self, mu, addr, size, _):
        self.steps += 1
        self.trace.append(addr)
        del self.trace[:-12]
        if addr == STUB and not self.in_stub:
            self.calls += 1                                       # the hook reached the keyboard call
        self.in_stub = STUB <= addr < STUB + 0x1000
        if self.writes and addr == self.syscall:
            mu.mem_write(mu.reg_read(UC_X86_REG_R10), self.key_state)
            mu.reg_write(UC_X86_REG_RAX, 1)
            mu.reg_write(UC_X86_REG_RIP, addr + 2)                # the syscall itself

    def run(self, limit=8_000_000):
        mu = self.mu
        mu.reg_write(UC_X86_REG_RSP, STACK + 0x200008)            # as a CALL into the builder leaves it
        mu.reg_write(UC_X86_REG_RCX, OBJECT)
        info = {"returned": False, "calls": 0, "wedge_at": None}
        try:
            # stop at the builder's own `ret`: a run that hits the instruction limit instead did not return
            mu.emu_start(BUILDER, EPILOGUE, count=limit)
            info["returned"] = mu.reg_read(UC_X86_REG_RIP) == EPILOGUE
        except UcError as error:
            info["error"] = str(error)
        rip = mu.reg_read(UC_X86_REG_RIP)
        if not info["returned"] and (STUB <= rip < STUB + 0x1000 or
                                     (self.trace and STUB <= self.trace[-1] < STUB + 0x1000)):
            info["wedge_at"] = "the GetKeyboardState call (the callee never returns)"
        info["calls"] = self.calls
        info["steps"] = self.steps
        info["reason"] = ("stopped at the instruction limit" if not info["returned"]
                          and mu.reg_read(UC_X86_REG_RIP) != EPILOGUE else "reached the builder's ret")
        info["count"] = struct.unpack("<i", mu.mem_read(OBJECT + 0x208, 4))[0]
        return info

    def header(self, buf):
        return dict(zip(("enabled", "owners", "nsnap", "page", "page2"),
                        struct.unpack("<IIIII", self.mu.mem_read(buf + newclasses.WHEEL_HEADER + 8, 20))))


@unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the replay")
class Test17WedgeTests(unittest.TestCase):
    """the exact TEST17 build: it never leaves the list builder when its keyboard call hangs"""

    @classmethod
    def setUpClass(cls):
        if not TEST17.is_file():
            raise unittest.SkipTest(f"the TEST17 payload is not on this machine ({TEST17})")
        cls.exe = TEST17.read_bytes()
        if hashlib.sha256(cls.exe).hexdigest() != TEST17_SHA256:
            raise unittest.SkipTest("the TEST17 payload does not match the recorded sha256")
        cls.pinned = pinned_bytes()
        cls.site = translate(cls.pinned, newclasses.CAROUSEL_VA)
        cls.slot = translate(cls.pinned, newclasses.KEYS_SLOT)
        cls.flags = translate(cls.pinned, newclasses.FLAGS_VA)
        cls.hook, cls.mods = mod_families(cls.exe, cls.site)
        cls.wheel = wheel_header(cls.exe)

    def test_the_payload_is_the_build_live14_installed(self):
        self.assertEqual(len(self.wheel["owners"]), 67)                       # 45 D4 + 13 D1C + 9 DD2
        self.assertEqual(self.wheel["owners"][0], (11390, 2))                 # Strider, wheel 2 = D1C
        self.assertEqual(self.wheel["enabled"], 1)
        self.assertEqual(self.slot, SLOT)                                     # the import slot the hook calls
        self.assertEqual(len(self.mods), 67)

    def test_test17_wedges_the_hire_character_build(self):
        """the reproduction: with the keyboard call not returning, the build stops inside the builder."""
        r = Replay(self.exe, VANILLA + self.mods, HANG, self.flags, self.site)
        buf = read_entry_buffer(self.exe, self.site)
        info = r.run()
        self.assertFalse(info["returned"], "TEST17's build returned: the wedge was not reproduced")
        self.assertEqual(info["wedge_at"], "the GetKeyboardState call (the callee never returns)")
        self.assertEqual(info["calls"], 1, "the replay must reach the call (once per list build)")
        self.assertEqual(info["count"], 114,
                         "the whole list (47 vanilla + the 67 wheel families) is in the buffer when the call is taken")
        self.assertEqual(r.header(buf)["owners"], 67)
        print(f"\nTEST17: no return after {info['steps']} instructions, wedged at the keyboard call "
              f"(count={info['count']} entries, owners=67, page 0/no key)")

    def test_the_same_build_returns_when_the_call_returns(self):
        """the control: nothing but the call stands between this build and its return."""
        r = Replay(self.exe, VANILLA + self.mods, RETURNS, self.flags, self.site, writes=True)
        info = r.run()
        self.assertTrue(info["returned"], "with a returning callee the TEST17 build must complete")
        self.assertGreaterEqual(info["calls"], 1)


@unittest.skipUnless(HAVE_UNICORN, "unicorn-engine is required for the replay")
class FixedHookTests(unittest.TestCase):
    """WHEELS4's hook: no call out of the game, page read from the game's own key state, build returns"""

    @classmethod
    def setUpClass(cls):
        from test_wheel_hires import D1C, D4, VANILLA_HUMAN, build
        cls.vanilla = VANILLA_HUMAN
        cls.owners = [(D4[0], 1), (D1C[0], 2)]
        families = [D4[0], D1C[0]]
        cls.pinned, cls.exe, cls.translator = build(cls.owners, families)
        cls.site = cls.translator(newclasses.CAROUSEL_VA)
        cls.keys = cls.translator(newclasses.WHEEL_KEY_STATE)
        cls.flags = cls.translator(newclasses.FLAGS_VA)
        cls.rows = cls.vanilla + [f + k for f in families for k in range(6)]

    def hook_body(self):
        o = file_offset(self.exe, self.site)
        hook = self.site + 5 + struct.unpack_from("<i", self.exe, o + 1)[0]
        return hook, self.exe[file_offset(self.exe, hook):][:0x1000]

    def test_the_hook_makes_no_call_outside_the_game(self):
        import capstone
        hook, body = self.hook_body()
        base, size, _ = sections(self.exe)
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        outside = []
        for i in md.disasm(body, hook):
            if i.mnemonic == "call":
                if not i.op_str.startswith("0x") or not base <= int(i.op_str, 16) < base + size:
                    outside.append((hex(i.address), i.op_str))
        self.assertEqual(outside, [], f"the hook must not leave the game's code: {outside}")

    def test_the_page_is_read_from_the_games_own_key_state(self):
        import capstone
        hook, body = self.hook_body()
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        movabs = [i for i in md.disasm(body, hook)
                  if i.mnemonic == "movabs" and i.op_str.startswith("r10,")]
        self.assertTrue(movabs, "the hook does not load the key state pointer")
        self.assertEqual(int(movabs[0].op_str.split(",")[1].strip(), 16), self.keys)

    def test_the_build_returns_and_shows_the_page_the_key_state_asks_for(self):
        # page 0 = D5 (the 25 vanilla humans: both mod families are on wheels of their own); page 1 = the one D4
        # family, repeated to the six the grid indexes (Cryswar's CC_GRID_MIN); page 2 = the one D1C family.
        for held, want_page, want_count in (({}, newclasses.WHEEL_PAGES, len(self.vanilla) + 2),
                                            ({0x10: 0x80}, 0, len(self.vanilla)),
                                            ({0x10: 0x80, 0x32: 0x80}, 1, 6),
                                            ({0x10: 0x80, 0x33: 0x80}, 2, 6)):
            key_state = bytearray(256)
            for vk, bit in held.items():
                key_state[vk] = bit
            # a hanging callee stays behind the import slot: the fixed build must never reach it
            r = Replay(self.exe, self.rows, HANG, self.flags, self.site,
                       key_state=bytes(key_state), state_va=self.keys)
            buf = read_entry_buffer(self.exe, self.site)
            info = r.run()
            self.assertTrue(info["returned"], f"the fixed build must complete (keys {held})")
            self.assertEqual(info["calls"], 0, "the fixed hook must not call the import at all")
            self.assertEqual(r.header(buf)["page"], want_page, f"page for keys {held}")
            self.assertEqual(info["count"], want_count, f"entries for keys {held}")

    def test_the_wedge_replay_passes_only_on_the_fix(self):
        """the gate: same replay, same data, same hanging callee -- TEST17 wedges, this returns."""
        info = Replay(self.exe, self.rows, HANG, self.flags, self.site).run()
        self.assertTrue(info["returned"])
        self.assertEqual(info["calls"], 0)


if __name__ == "__main__":
    unittest.main()
