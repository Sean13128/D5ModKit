"""Sub-class from the Status Class tab (exe section .d5sb): Confirm on a listed class makes it the unit's sub-class.

Why: the Strategy Assembly's "Set a Sub Class" screen (`0x1404707E0`, task\\assembly\\subclassedit.cpp) keeps its rows
inside its own object -- 47 rows of 0x238 bytes at +0x2768, up to the unit pointer at +0x8FB8 of a 0x8FC0-byte
object -- and fills them from a 47-family array on its stack.  The Kit's packed/six-slot mastery hooks
(`d5lib.masteryext` FETCH_SITE / BOUND_SITE) already append configured families after the 47, but only while fewer
than 47 rows are used, so a post-game unit with 43 vanilla classes unlocked sees at most 4 imported classes
(SUBCLASS1, live).  The Status Class tab, by contrast, already lists every class (512 entries since
`d5lib.newclasses` moved its list into the .d5cl buffer).

This is Cryswar's Overlord sub-class switch (overlord/03_subclass_wishes.c: install_subclass_class_tab_state_hook,
hook_subclass_class_tab_update, subclass_class_tab_assign_owner; The Unlicense -- thanks, Cryswar), made Kit-native:

* one hook at the Class tab's per-frame update `0x14029CA50` (Steam build; Overlord's own site and stolen bytes
  `4C 8B DC 56 57 48 81 EC A8 00 00 00`), entered by `jmp`, that runs before the game's update and then the
  displaced prologue;
* it acts only when the child's visible tab (+0x1A0A8) is the Class tab (4), on the second and later frames with the
  same owner (the frame the tab opens only arms it, as Overlord does), and when the game's own menu Confirm is on its
  press edge: `carry_common_action(4, 1, 0)` (0x1402258B0, Sorrow's Input::action), the read the menus use.  It checks
  the keyboard keys bound to the action (bindings at input+0x50 / +0x420, edge table 0x147B24AE0) and then the pad
  (`input_physical` -> `input_button_state`).  SUBCLASS3: the first port read only the pad half (Overlord's
  `GetButtonIndex`/`ButtonPush` pair; his keyboard path was his own GetAsyncKeyState K), so a keyboard Confirm --
  the player's or the harness's -- never reached it (INSTALL1120A B1);
* it validates like Overlord: list count 1..cap, cursor and scroll >= 0, cursor + scroll < count, the displayed unit
  (+0x90) is an aligned record of the persistent roster (temporary battle copies are refused), the listed family is a
  family base (1000..32760, multiple of 10: registry families such as D1C Golem 11770 are generic too -- SUBCLASS3;
  the game's unlock test below is what admits a generic family; +0x35AC is read as a signed short);
* the unit's own class family is refused (SUBCLASS2 rework: a class is not its own sub-class);
* the rank follows the Assembly screen's admission, not Overlord's star count: the family's base rank must pass the
  game's unlock test (`0x1401C6110`, which the Kit's class hooks answer for imported families) -- otherwise refused,
  as the native list would not show it -- and the sub-class is the highest rank that test accepts.  With the usual
  prefix unlocks this is the native list's `family - 1 + count`; with a gap (ranks 0 and 5 only) it is rank 5, never
  a rank that is not unlocked.  The seven character-specific exceptions of `0x140470610` are not ported;
* the write is the one the native screen makes on exit (`0x140470740`: unit +0x35AC = the chosen u16).  Nothing else
  changes; the game reads +0x35AC wherever it uses the sub-class.

The hook is built only when the Class tab is relocated (`d5lib.newclasses` puts its list in the .d5cl buffer, i.e.
the build has class mods), and it reads the list from that buffer; a vanilla build is left as it is.
Overlord's runtime refuses its own hook when these bytes are not vanilla (`expected[]` check), see
`d5lib.overlord_compat.SITES[0x14029CA50]`.

A 32-byte state block at the start of the section is the live check's window:
    +0  u64 owner seen last frame (0 = Class tab not visible)
    +8  u32 Confirm presses acted on        +12 u32 last result (RESULT_*: 1 refused, 2 locked, 3 same, 4 written, 5 own class)
    +16 u32 last family                     +20 u32 last sub-class written / compared
"""
import struct

from . import exemap, exepatch
from .gamefs import EXE_FILE
from .modsys import register_finalizer

SECTION_NAME = b".d5sb"

# Steam build (sha1 9460a6411699..., the one the decomp and Overlord name): native hook site and branch targets
SITE = 0x14029CA50
SITE_ORIG = bytes.fromhex("4c8bdc56574881eca8000000")
SITE_RET = SITE + len(SITE_ORIG)                # 0x14029CA5C
ACTION = 0x1402258B0                            # carry_common_action(action, 1, flags) -> 2 press edge, 1 repeat, 0
ACTION_SIG = bytes.fromhex("48895c24084889742410574883ec204863d9418bf80fb6f283fb05")
CONFIRM = 4                                     # D5 logical menu Confirm (Overlord SUBCLASS_D5_MENU_CONFIRM)

# known-build names (exemap.KNOWN_SHA1), translated like every Kit hook
UNLOCK_TEST = 0x1401C5790                       # "is this class rank unlocked" (Steam 0x1401C6110)
ROSTER = 0x145235C58                            # roster unit 0 (Steam 0x145207DB8)
CLASSTAB_APPEND = 0x1402A37F1                   # newclasses' Class tab append site (Steam 0x1402A3931)

# the Class tab child (Overlord 01_declarations.c, the decomp of 0x14029CA50 / 0x1402A7140)
TAB = 0x1A0A8
CLASS_TAB = 4
CHARACTER = 0x90
CURSOR, SCROLL, COUNT = 0x1E328, 0x1E32C, 0x1E4D8
NATIVE_LIST = 0x1E404                           # the game's own 53-entry family list (no relocation)
NATIVE_CAP = 53
UNIT_SIZE, ROSTER_MAX = 0x4750, 0x80
SUBCLASS = 0x35AC
MAIN_CLASS = 0x2E04                             # the unit's own class id (u32)
RANKS = 6
FAMILY_MIN, FAMILY_MAX = 1000, 32760

STATE_SIZE = 32
RESULT_REFUSED, RESULT_LOCKED, RESULT_SAME, RESULT_WRITTEN, RESULT_OWN = 1, 2, 3, 4, 5


def classtab_buffer(exe):
    """(address of the Class tab's family list, entry cap) the game uses in this exe: the .d5cl buffer when
    newclasses relocated the list (read back from its append stub, `lea rdx, [rip + buffer]`), else None"""
    import capstone
    import pefile
    from .newclasses import CLASSTAB_CAP
    pe = pefile.PE(data=exe, fast_load=True)
    va = exemap.ACTIVE(CLASSTAB_APPEND)
    off = pe.get_offset_from_rva(va - exepatch.IMAGE_BASE)
    if exe[off] != 0xE9:
        return None
    stub = va + 5 + struct.unpack_from("<i", exe, off + 1)[0]
    try:
        soff = pe.get_offset_from_rva(stub - exepatch.IMAGE_BASE)
    except Exception:
        return None
    from capstone.x86 import X86_OP_MEM, X86_REG_RIP
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    for ins in md.disasm(exe[soff:soff + 48], stub):
        if ins.mnemonic == "lea":
            op = ins.operands[1]
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                return ins.address + ins.size + op.mem.disp, CLASSTAB_CAP
        if ins.mnemonic == "jmp":
            break
    raise ValueError("Class tab relocation stub: no buffer reference found")


def _src(list_addr, cap):
    """the hook (entered by jmp at the update's first byte: return address on top, rsp = 8 mod 16, rcx = owner).
    Every register it touches is pushed and popped; the displaced prologue then runs on the caller's own rsp."""
    if list_addr is None:
        family = f"mov r12d, dword ptr [rbx + rdi*4 + {NATIVE_LIST:#x}]"
        lead = []
    else:
        family = "mov r12d, dword ptr [rax + rdi*4]"
        lead = ["lea rax, [rip + SC_LIST]"]            # rip-relative: the game runs with ASLR
    return "\n".join([
        "push rax", "push rcx", "push rdx", "push r8", "push r9", "push r10",
        "push rbx", "push rsi", "push rdi", "push rbp", "push r12", "push r13",
        "sub rsp, 0x28",                                # 12 pushes + 0x28: rsp = 0 mod 16 at every call
        "mov rbx, rcx",
        "lea rsi, [rip + sc_state]",
        f"cmp dword ptr [rbx + {TAB:#x}], {CLASS_TAB}",
        "jne sc_hidden",
        "cmp qword ptr [rsi], rbx",
        "je sc_armed",
        "mov qword ptr [rsi], rbx",                     # first frame on this owner: arm only
        "jmp sc_out",
        "sc_hidden:",
        "mov qword ptr [rsi], 0",
        "jmp sc_out",
        "sc_armed:",
        f"mov ecx, {CONFIRM}",
        "mov edx, 1",
        "xor r8d, r8d",
        f"call {ACTION}",                                # decimal: this build's address; keyboard + pad
        "cmp eax, 2",
        "jne sc_out",
        "inc dword ptr [rsi + 8]",
        f"mov dword ptr [rsi + 12], {RESULT_REFUSED}",
        "mov dword ptr [rsi + 16], 0",
        "mov dword ptr [rsi + 20], 0",
        f"mov eax, dword ptr [rbx + {COUNT:#x}]",
        "test eax, eax",
        "jle sc_out",
        f"cmp eax, {cap}",
        "jg sc_out",
        f"mov edi, dword ptr [rbx + {CURSOR:#x}]",
        f"mov edx, dword ptr [rbx + {SCROLL:#x}]",
        "test edi, edi",
        "js sc_out",
        "test edx, edx",
        "js sc_out",
        "add edi, edx",
        "jo sc_out",
        "cmp edi, eax",
        "jge sc_out",
        f"mov rbp, qword ptr [rbx + {CHARACTER:#x}]",
        "lea rax, [rip + SC_ROSTER]",
        "mov rcx, rbp",
        "sub rcx, rax",
        "jb sc_out",
        f"cmp rcx, {UNIT_SIZE * ROSTER_MAX:#x}",
        "jae sc_out",
        "mov rax, rcx",
        "xor edx, edx",
        f"mov ecx, {UNIT_SIZE:#x}",
        "div rcx",
        "test rdx, rdx",
        "jne sc_out",
        *lead,
        family,
        "mov dword ptr [rsi + 16], r12d",
        f"cmp r12d, {FAMILY_MIN}",
        "jl sc_out",
        f"cmp r12d, {FAMILY_MAX}",
        "jg sc_out",
        "mov eax, r12d",
        "xor edx, edx",
        "mov ecx, 10",
        "div ecx",
        "test edx, edx",
        "jne sc_out",
        f"mov eax, dword ptr [rbp + {MAIN_CLASS:#x}]",    # the unit's own class: not its own sub-class
        "xor edx, edx",
        "mov ecx, 10",
        "div ecx",
        "imul eax, eax, 10",
        "cmp eax, r12d",
        "jne sc_other",
        f"mov dword ptr [rsi + 12], {RESULT_OWN}",
        "jmp sc_out",
        "sc_other:",
        "mov ecx, r12d",                                # the base rank admits the family (the Assembly's test)
        f"call {UNLOCK_TEST:#x}",
        "lea rsi, [rip + sc_state]",
        "test al, al",
        "jne sc_base",
        f"mov dword ptr [rsi + 12], {RESULT_LOCKED}",
        "jmp sc_out",
        "sc_base:",
        f"mov r13d, {RANKS - 1}",                       # then the highest rank the unlock test accepts
        "sc_rank:",
        "lea ecx, [r12 + r13]",
        f"call {UNLOCK_TEST:#x}",
        "test al, al",
        "jne sc_found",
        "dec r13d",
        "jne sc_rank",
        "sc_found:",
        "lea rsi, [rip + sc_state]",
        "lea edi, [r13 + 1]",                           # number of the rank, so target = family - 1 + edi
        "sc_unlocked:",
        "lea eax, [r12 + rdi - 1]",
        "mov dword ptr [rsi + 20], eax",
        f"cmp ax, word ptr [rbp + {SUBCLASS:#x}]",
        "jne sc_write",
        f"mov dword ptr [rsi + 12], {RESULT_SAME}",
        "jmp sc_out",
        "sc_write:",
        f"mov word ptr [rbp + {SUBCLASS:#x}], ax",
        f"mov dword ptr [rsi + 12], {RESULT_WRITTEN}",
        "sc_out:",
        "add rsp, 0x28",
        "pop r13", "pop r12", "pop rbp", "pop rdi", "pop rsi", "pop rbx",
        "pop r10", "pop r9", "pop r8", "pop rdx", "pop rcx", "pop rax",
        "mov r11, rsp",                                 # the displaced 12 bytes
        "push rsi",
        "push rdi",
        "sub rsp, 0xa8",
        f"jmp {SITE_RET}",
        f"SC_ROSTER = {ROSTER:#x}",
        *([f"SC_LIST = {list_addr}"] if list_addr is not None else []),     # decimal: already this build's address
        "sc_state = {shared}",
    ])


def _check_signatures(exe):
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    for va, sig, what in ((ACTION, ACTION_SIG, "carry_common_action"),):
        if pe.get_data(va - exepatch.IMAGE_BASE, len(sig)) != sig:
            raise ValueError(f"sub-class Class tab: {what} {va:#x} doesn't match (unexpected exe build)")


def yielded(exe=None):
    """True when Overlord's runtime owns the Class tab update site in this install"""
    from . import overlord_compat
    hooks = [(SITE, SITE_ORIG, "", 0xE9)]
    return bool(overlord_compat.filter_hooks(SECTION_NAME, hooks, native=True)[1])


def build_patch(exe: bytes, list_info=None) -> bytes:
    """the exe with section .d5sb and the Class tab hook.  list_info = (list address, cap) or None for the game's
    own list; default: what classtab_buffer() finds (unchanged exe when the Class tab is not relocated)."""
    if list_info is None:
        list_info = classtab_buffer(exe)
        if list_info is None:
            return exe
    if yielded():
        return exe
    _check_signatures(exe)
    addr, cap = list_info
    return exepatch.add_hook_section(exe, SECTION_NAME, [], writable=True, shared_bytes=bytes(STATE_SIZE),
                                     native_hooks=[(SITE, SITE_ORIG, _src(addr, cap), 0xE9)],
                                     digest={"list": addr, "cap": cap})


def build_patch_native(exe: bytes) -> bytes:
    """the hook over the game's own Class tab list (+0x1E404, 53 entries): for proofs of a build without classes"""
    _check_signatures(exe)
    return exepatch.add_hook_section(exe, SECTION_NAME, [], writable=True, shared_bytes=bytes(STATE_SIZE),
                                     native_hooks=[(SITE, SITE_ORIG, _src(None, NATIVE_CAP), 0xE9)],
                                     digest={"list": 0, "cap": NATIVE_CAP})


def is_hooked(exe: bytes) -> bool:
    return exepatch.has_feature(exe, SECTION_NAME)


def state_address(exe: bytes):
    """the state block's address in a built exe (the section region's first byte), or None"""
    for c in exepatch.feature_claims(exe):
        if c["name"] == SECTION_NAME[:8].rstrip(b"\0") and c["valid"]:
            return exepatch.IMAGE_BASE + c["rva"] - ((c["length"] + 3) & ~3)
    return None


# ------------------------------------------------------------------------------------------ install
def _finalize(ctx):
    exe = ctx.get(EXE_FILE)
    info = classtab_buffer(exe)
    if info is None:
        return
    if yielded():
        ctx.log("  sub-class from the Class tab: Overlord's runtime owns the Class tab update (0x14029CA50); "
                "the Kit writes no .d5sb hook")
        return
    ctx.put(EXE_FILE, build_patch(exe, info))
    ctx.log("  sub-class from the Class tab: Confirm on a listed class sets the unit's sub-class "
            f"(list of {info[1]} at {info[0]:#x})")


register_finalizer(_finalize)
