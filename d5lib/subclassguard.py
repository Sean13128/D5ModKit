"""Skip the Assembly's "current sub-class" panel when the saved sub-class has no char.dat row (exe section .d5sv).

The Strategy Assembly's sub-class screen draw `0x14046F980` (Steam build) draws the current-sub-class panel whenever
the unit's sub-class u16 (+0x35AC) is positive: it looks the id up with `char_find_by_id` (`0x140061F80`), and on a
miss (-1) leaves the row pointer at 0 and still passes `row + 0xF8 + language * 0x34` to `ui_draw_text`
(`0x1403FACE0`) -- a string in the null page, i.e. a crash.  A save reaches that state when the unit's sub-class is a
class whose mod was removed (or a rank row is gone): the save outlives the mod (REVIEW-SUBCLASS2, Codex).

The hook replaces the 11 bytes after the lookup (`xor ebx,ebx / test eax,eax / jns found / mov r14d,ebx / jmp`) with a
jmp to code that does the same for a found row and, on a miss, restores r15 (saved by the function before the panel,
restored inside it at `0x14046FA9E`) and jumps to the function's own epilogue `0x14046FC8C`, which restores xmm6, r14,
r12, rdi, rbp and rbx from their slots and returns.  The panel (frame + two texts) is skipped; the list was already
drawn.  No call, no stack use.  Each skip adds 1 to a dword after the code (the section is writable for it), so a live
run can read how often it happened.

It does not depend on the class mods, so it is installed in **every** build whose exe has these bytes (its own
finalizer, like the draw-packet guard d5lib.anmguard (PAGECRASH1) but not tied to outfits): a save can carry an
imported sub-class into a build where the class mod is gone.  The stored id is left alone: re-enabling the mod
restores the panel, and the player can choose another sub-class.
"""
import struct

from . import exepatch
from .gamefs import EXE_FILE
from .modsys import register_finalizer

SECTION = b".d5sv"
SITE = 0x14046FA39                       # after `call char_find_by_id`
SITE_ORIG = bytes.fromhex("33db85c07905448bf3eb10")
FOUND = 0x14046FA44                      # cdqe / imul r14, rax, 0x38c ... (the row pointer)
JOIN = 0x14046FA54                       # where both native paths meet (the miss path sets r14d = 0 first)
EPILOGUE = 0x14046FC8C                   # movaps xmm6, [rsp+0x50] ... add rsp, 0x80 / pop rsi / ret
EPILOGUE_ORIG = bytes.fromhex("0f28742450")
R15_RESTORE = 0x14046FA9E                # mov r15, [rsp+0x60] (inside the skipped panel)
R15_ORIG = bytes.fromhex("4c8b7c2460")
LOOKUP_CALL = 0x14046FA34                # call char_find_by_id (0x140061F80)
LOOKUP_ORIG = bytes.fromhex("e84725bfff")


def hook_source():
    return "\n".join(["xor ebx, ebx",
                      "test eax, eax",
                      "js sv_skip",
                      f"jmp {FOUND}",                    # decimal: already this build's addresses
                      "sv_skip:",
                      "lock inc dword ptr [rip + sv_count]",
                      "mov r15, qword ptr [rsp + 0x60]",
                      f"jmp {EPILOGUE}",
                      ".align 4",
                      "sv_count:",
                      ".long 0"])


def _get(exe, va, n):
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    return pe.get_data(va - exepatch.IMAGE_BASE, n)


def applies(exe: bytes) -> bool:
    """the exe holds the draw's own bytes at the site, the r15 restore and the epilogue (Steam build)"""
    try:
        return (_get(exe, SITE, len(SITE_ORIG)) == SITE_ORIG and _get(exe, EPILOGUE, 5) == EPILOGUE_ORIG
                and _get(exe, R15_RESTORE, 5) == R15_ORIG and _get(exe, LOOKUP_CALL, 5) == LOOKUP_ORIG)
    except Exception:
        return False


def patch(exe: bytes, log=print) -> bytes:
    if not applies(exe):
        if not exepatch.has_feature(exe, SECTION):
            log("  sub-class panel guard: site not found in this exe, not applied")
        return exe
    return exepatch.add_hook_section(exe, SECTION, [], writable=True,
                                     native_hooks=[(SITE, SITE_ORIG, hook_source(), 0xE9)])


def counter_va(exe: bytes):
    """the skip counter in a patched exe, or None"""
    import capstone
    off = _get(exe, SITE, 5)
    if not off or off[0] != 0xE9:
        return None
    hook = SITE + 5 + struct.unpack_from("<i", off, 1)[0]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    from capstone.x86 import X86_OP_MEM, X86_REG_RIP
    for ins in md.disasm(_get(exe, hook, 0x40), hook):
        if ins.mnemonic.endswith("inc"):
            op = ins.operands[0]
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                return ins.address + ins.size + op.mem.disp
    return None


def _finalize(ctx):
    exe = ctx.get(EXE_FILE)
    out = patch(exe, log=ctx.log)
    if out is not exe:
        ctx.put(EXE_FILE, out)
        ctx.log("  sub-class panel guard: a saved sub-class without its class row no longer crashes the Assembly")


register_finalizer(_finalize)
