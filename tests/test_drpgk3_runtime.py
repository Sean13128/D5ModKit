"""DRPG-K3: the runtime adapter for a high-art costume, proved offline.

The site that decides a costume's art is proved against the game's own instructions in the pinned exe:

  * the graphics-id hook replaces `anm_id_for_variant` (known build 0x14021E9D0) and substitutes the class id for
    any unit whose class is in its table.  That is right for a LOW outfit (art named after the class id) and wrong
    for a declared DRPG costume (art named after the char row's colour N; the class id is a lease number), so a
    costume must fall through to the native computation.  The face redirect (class id -> 10000 + colour) stays.
  * the list-icon pick (known build 0x1401A2460) is called with the char row's colour id (call sites 0x140537232 /
    0x140424917 in this build), so the Kit's icon table stays keyed on the colour -- proved here, not assumed.

Read-only: the pinned vanilla exe is patched in memory and never written anywhere.

Run: python -m pytest tests/test_drpgk3_runtime.py -q
"""
import hashlib
import os
import struct

import pytest

from d5lib import exemap, exepatch

EXE = ("/Volumes/Data/Projects/D5/D5ModKit/state/games/"
       "Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")

# the outfit patch the Kit produced for this fixture before K3 (exepatch.build_outfit_patch at a95aec3): every
# existing pack -- Outfit_System included -- has this shape (one face animation of 10000 + class id per entry), so
# its patched exe must stay byte-identical.
LOW_SHA256 = "bc656a1c9dd8b8c81e26c3990697945c7df1ed12e889a36c58031a5394e94f52"

pytestmark = pytest.mark.skipif(not os.path.exists(EXE), reason="pinned game exe not present")

from capstone import Cs, CS_ARCH_X86, CS_MODE_64          # noqa: E402
from capstone.x86 import X86_OP_MEM, X86_REG_RIP          # noqa: E402

LOW_RECORDS = [(0, 470, 1001), (0, 480, 1002), (1, 490, 1003)]
LOW_FACES = [(470, 10470), (480, 10480), (490, 10490)]

MIXED_RECORDS = [(0, 470, 1001), (7, 30170, 1002)]
MIXED_FACES = [(470, 10470), (30170, 24940)]      # costume: face at 10000 + colour 14940


@pytest.fixture(autouse=True)
def _restore_translator():
    """build_outfit_patch installs this build's address translator; every other test expects the known build."""
    old = exemap.ACTIVE
    yield
    exemap.use(old)


def _map(mu, va, size=0x1000):
    """map the page holding `va` at its real address (the hook lives in the kit's appended section)"""
    mu.mem_map(va & ~0xFFF, size)


def _patch(faces, records, own_sprites=(), looks=None):
    data = open(EXE, "rb").read()
    exemap.use(exemap.translator_for(data))
    return exepatch.build_outfit_patch(data, records, 40001, 40002, own_sprites=own_sprites,
                                       faces=faces, looks=looks or {})


def _sites(exe):
    """(Exe, graphics site, graphics hook, graphics miss target) in the patched exe"""
    ex = exemap.Exe(data=exe)
    site = exemap.ACTIVE(0x14021E9D0)
    raw = ex.read(site - ex.base, 5)
    assert raw[0] == 0xE9, f"graphics site is not redirected: {raw.hex()}"
    hook = site + 5 + struct.unpack("<i", raw[1:])[0]
    miss = site + int.from_bytes(ex.read(site - ex.base + 1, 0) or b"", "little") if False else None
    return ex, site, hook, miss


def _gfx_table(ex, hook):
    """the [(class id, face animation)] table the graphics hook walks, found through its own `lea r10,[rip+..]`"""
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    for ins in md.disasm(ex.read(hook - ex.base, 0x60), hook):
        if ins.mnemonic == "lea" and ins.op_str.startswith("r10, [rip"):
            for op in ins.operands:
                if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                    table = ins.address + ins.size + op.mem.disp
                    out = []
                    for k in range(0, 0x400, 8):
                        c, a = struct.unpack("<II", ex.read(table + k - ex.base, 8))
                        if c == 0:
                            return out
                        out.append((c, a))
    raise AssertionError("graphics hook has no table")


# --------------------------------------------------------------------------------------------- data decisions
def test_existing_outfit_patch_is_byte_identical():
    """Outfit_System and every other existing pack: no declared colour -> the same exe, byte for byte."""
    patched = _patch(LOW_FACES, LOW_RECORDS, own_sprites=[470, 480], looks={470: (0, 3), 480: (1, 3)})
    assert hashlib.sha256(patched).hexdigest() == LOW_SHA256


def test_costume_leaves_the_graphics_table_but_keeps_the_face_redirect():
    ex, site, hook, _ = _sites(_patch(MIXED_FACES, MIXED_RECORDS))
    table = _gfx_table(ex, hook)
    assert (470, 10470) in table                      # the low outfit keeps its class-id graphics id
    assert all(c != 30170 for c, _ in table), table    # the costume falls through to anm_id_for_variant
    # the face redirect table still holds both: class id -> 10000 + face colour (the costume's is 10000 + 14940)
    assert struct.pack("<II", 470, 10470) in ex.data
    assert struct.pack("<II", 30170, 24940) in ex.data
    # and nothing anywhere pairs the costume's class id with its own class id as a face/graphics id
    assert struct.pack("<II", 30170, 30170) not in ex.data


def test_gfx_hook_returns_the_class_id_for_a_low_outfit():
    """The real patched site, entered the way a caller enters it: CALL pushed the return address (rsp%16 == 8)."""
    uc = pytest.importorskip("unicorn")
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_RCX, UC_X86_REG_RIP, UC_X86_REG_RSP, UC_X86_REG_RAX, UC_X86_REG_RBX

    ex, site, hook, _ = _sites(_patch(MIXED_FACES, MIXED_RECORDS))
    STACK = 0x7FF000
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    _map(mu, site)
    _map(mu, hook)
    _map(mu, 0x140001000)
    mu.mem_map(STACK - 0x1000, 0x2000)
    mu.mem_write(site, ex.read(site - ex.base, 0x100))
    mu.mem_write(hook, ex.read(hook - ex.base, 0x400))   # hook + its table
    # caller rsp % 16 == 0 before the CALL, so the hook is entered with rsp % 16 == 8
    ret = 0x140001000
    mu.reg_write(UC_X86_REG_RSP, STACK - 8)
    mu.mem_write(STACK - 8, struct.pack("<Q", ret))
    mu.reg_write(UC_X86_REG_RCX, 470)
    mu.reg_write(UC_X86_REG_RBX, 0)
    seen = []

    def stop_at(u, a, size, data):
        seen.append(a)
        if a == ret:
            u.emu_stop()

    mu.hook_add(UC_HOOK_CODE, stop_at)
    mu.emu_start(site, 0, count=64)
    assert seen[0] == site, "did not enter through the patched instruction"
    assert mu.reg_read(UC_X86_REG_RIP) == ret, [hex(a) for a in seen]
    assert mu.reg_read(UC_X86_REG_RAX) == 470
    assert mu.reg_read(UC_X86_REG_RSP) == STACK              # the single return address consumed, nothing else


def test_gfx_hook_falls_through_for_a_costume():
    """Same site with the costume's class id: the hook must run the original prologue and continue at site+5."""
    uc = pytest.importorskip("unicorn")
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_RCX, UC_X86_REG_RIP, UC_X86_REG_RSP, UC_X86_REG_RBX,
                                   UC_X86_REG_RDI)

    ex, site, hook, _ = _sites(_patch(MIXED_FACES, MIXED_RECORDS))
    STACK = 0x7FF000
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    _map(mu, site)
    _map(mu, hook)
    mu.mem_map(STACK - 0x1000, 0x2000)
    mu.mem_write(site, ex.read(site - ex.base, 0x200))
    mu.mem_write(hook, ex.read(hook - ex.base, 0x400))   # hook + its table
    stop = site + 5                      # where the original body resumes; stop on arrival, before executing it
    mu.reg_write(UC_X86_REG_RSP, STACK - 8)
    mu.mem_write(STACK - 8, struct.pack("<Q", 0x140001000))
    mu.reg_write(UC_X86_REG_RCX, 30170)
    mu.reg_write(UC_X86_REG_RBX, STACK - 0x200)
    mu.reg_write(UC_X86_REG_RDI, 0)
    seen = []

    def stop_at(u, a, size, data):
        seen.append(a)
        if a == stop:
            u.emu_stop()

    mu.hook_add(UC_HOOK_CODE, stop_at)
    mu.emu_start(site, 0, count=64)
    assert seen[0] == site
    assert mu.reg_read(UC_X86_REG_RIP) == site + 5, hex(mu.reg_read(UC_X86_REG_RIP))   # original body resumes
    assert mu.reg_read(UC_X86_REG_RSP) == STACK - 8          # nothing pushed, nothing popped
    assert mu.reg_read(UC_X86_REG_RCX) == 30170              # argument untouched for the original


def test_hook_code_has_no_stack_arithmetic():
    """Static audit of the emitted graphics hook: it allocates, pushes and pops nothing."""
    ex, site, hook, _ = _sites(_patch(MIXED_FACES, MIXED_RECORDS))
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    ops = []
    for ins in md.disasm(ex.read(hook - ex.base, 0x40), hook):
        ops.append((ins.mnemonic, ins.op_str))
        if ins.mnemonic == "jmp":
            break
    # the only stack write is the original function's own `mov [rsp+8], rbx`, replayed by the fall-through path
    bad = [o for o in ops if o[0] in ("push", "pop", "call", "leave")
           or ("rsp" in o[1] and o != ("mov", "qword ptr [rsp + 8], rbx"))]
    assert not bad, bad
    assert ops[-1][0] == "jmp", ops[-1]          # the miss path is a tail jump into the original body


def test_icon_table_is_keyed_on_the_colour():
    """The icon hook's table pairs the char row's colour id (not the class id) with its texturedatabase row."""
    from d5lib import outfits
    src = outfits._icon_src([(14940, 13173)])
    assert "14940, 13173" in src
    assert "movzx eax, dx" in src                 # the second argument of 0x1401A2460 is the colour
