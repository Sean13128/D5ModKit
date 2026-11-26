"""Skip a sprite draw packet whose texture is NULL instead of crashing (exe section .d5ag, PAGECRASH1).

`anm_flush_draw_packets` (0x1402F3650 in the Steam build the decomp covers) walks the frame's 200-byte draw
packets and, first thing per packet, reads the texture's format byte: `mov rax,[rbx+0x20]; cmp byte [rax+0x24],9`
(0x1402F3740/44).  packet+0x20 is the texture object the emitters (anm_emit_node_geometry, anm_render_node_hierarchy)
took from the bank record's texture table (record+0x98)[cell.tex].  The emitters themselves check that pointer for
NULL before they read +0x24, and still queue the packet when it is NULL (the record's table is NULL after
anm_release_package, or its entry is not written yet while the queued, time-sliced build fills it, or the texture
pool gave none).  The flush does not check, so a NULL texture is a page fault reading 0x24: the Recruiter D4-page
"freeze" (FREEZECATCH1: Wine's unhandled-exception box parks the frame thread).

The hook replaces those two instructions and their `je` (10 bytes) with a jmp to leaf code that does the same thing
and, when the pointer is NULL, jumps to the loop's own tail (`mov rax,[packets]; add rbx,200; ...`), which restores
the render state word and goes on with the next packet: that part of the sprite is not drawn for that frame, as the
emitters already do for a cell with no texture page.  No call, no stack use; only rax and the flags change, as in the
original.  Each skip adds 1 to a dword after the hook code (`counter_va`; the section is writable for it), so a live
run can read how often the game made a NULL packet.  The site is found by its bytes, so the patch follows the exe
build; an exe without them is left alone.

This hides the symptom: the owner that draws a record whose textures are gone or not loaded yet is the cause, and is
not fixed here (see Subprojects/Engine-Extensions/PAGECRASH1-REPORT.md).
"""
import re

from . import exepatch

SECTION = b".d5ag"
# mov rax,[rbx+0x20] / cmp byte [rax+0x24],9 / je +0x1d / test r9d,r9d
SIG = bytes.fromhex("488b4320807824097 41d4585c9".replace(" ", ""))
ORIG_LEN = 10                                   # the three instructions the jmp (+5 nops) replaces
TAIL = re.compile(rb"\x48\x8b\x05....\x48\x81\xc3\xc8\x00\x00\x00", re.S)    # mov rax,[rip+x]; add rbx,0xc8


def find_site(exe: bytes):
    """-> (site va, je target, fall-through va, loop tail va) in this exe, or None when the bytes are not there once"""
    import pefile
    hits = [m.start() for m in re.finditer(re.escape(SIG), exe)]
    if len(hits) != 1:
        return None
    pe = pefile.PE(data=exe, fast_load=True)
    off = hits[0]
    site = exepatch.IMAGE_BASE + pe.get_rva_from_offset(off)
    tail = TAIL.search(exe, off, off + 0x200)
    if not tail:
        return None
    return site, site + ORIG_LEN + exe[off + 9], site + ORIG_LEN, \
        exepatch.IMAGE_BASE + pe.get_rva_from_offset(tail.start())


def hook_source(je, fall, tail):
    """decimal targets: Translator.text translates hex game addresses, these are already this build's"""
    return "\n".join(["mov rax, qword ptr [rbx + 0x20]",
                      "test rax, rax",
                      "je ag_skip",
                      "cmp byte ptr [rax + 0x24], 9",
                      f"je {je}",
                      f"jmp {fall}",
                      "ag_skip:",
                      "lock inc dword ptr [rip + ag_count]",
                      f"jmp {tail}",
                      ".align 4",
                      "ag_count:",
                      ".long 0"])


def patch(exe: bytes, log=print) -> bytes:
    found = find_site(exe)
    if found is None:
        if not exepatch.has_feature(exe, SECTION):
            log("  draw-packet guard: site not found in this exe, not applied")
        return exe
    site, je, fall, tail = found
    log("  draw-packet guard: a sprite packet without a texture is skipped (anm_flush_draw_packets)")
    orig = exe[_off(exe, site):_off(exe, site) + ORIG_LEN]
    return exepatch.add_hook_section(exe, SECTION, [], writable=True,
                                     native_hooks=[(site, orig, hook_source(je, fall, tail), 0xE9)])


def counter_va(exe: bytes, site=0x1402F3740):
    """the address of the skip counter in a patched exe (read it live with the harness `rd`), or None"""
    import struct
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    off = _off(exe, site)
    if exe[off] != 0xE9:
        return None
    hook = site + 5 + struct.unpack_from("<i", exe, off + 1)[0]
    for ins in Cs(CS_ARCH_X86, CS_MODE_64).disasm(exe[_off(exe, hook):_off(exe, hook) + 0x40], hook):
        if ins.mnemonic.endswith("inc") and "rip" in ins.op_str:
            return ins.address + ins.size + int(ins.op_str.split("+")[1].strip(" ]"), 16)
    return None


def _off(exe, va):
    import pefile
    return pefile.PE(data=exe, fast_load=True).get_offset_from_rva(va - exepatch.IMAGE_BASE)
