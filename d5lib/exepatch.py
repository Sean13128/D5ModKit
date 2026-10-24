"""Code patches for disgaea5.exe (Steam/CODEX build, image base 0x140000000).

Outfit feature
--------------
Character list -> unit sub-menu (Equipment / Evility / Status) gets an "Outfit" entry for characters
that have outfits.  Choosing it turns the same menu into the list of the character's outfits ("Default",
"Swimsuit", ...); choosing one sets the unit's class id to that outfit's char.dat row (a copy of the
character with another sprite / face / portrait), refreshes the unit with the game's own routine and
rebuilds the character's sprite on screen.  Stats, level, name, equipment and colour stay the same.

Reverse-engineered locations (see docs/EXE_ANALYSIS.md):
  0x140263875  opening the sub-menu for the selected character: state +0xbdc8 = 1, open(menu)
               @0x1402b09a0.  The menu (scene+0xbd98) is built once at scene start; we rebuild it here
               on every opening: init(menu, n) @0x1402b16b0 (frees / reallocates), add(menu, &entry)
               @0x1402b0cb0 with entry {u32 value, u32 flag, u32 label_id, u32 help_id}
  0x140263432  confirm dispatch: +0xbdac = selected POSITION (vanilla values 0 Equipment, 1 Evility,
               2 Status equal their positions); the entry's value is read from the menu's entry array
               (menu+0 entries of 16 bytes, menu+8 count); 0x140263a5f = keep going
  0x1400928d0  list component (scene+0x80) -> selected entry, [entry] = unit pointer
  0x14015eb80  refresh unit (+0x2E0A row index, +0x2E36 graphics id) from class id (+0x2E04)
  0x1402634e9  tail of the 'cancel' path (returns to the character list)
  0x14067e7d1  hub / party characters: the scene only rebuilds a character's sprite when the unit's
               colour changed (the class comparison reads the same unit twice) -> compare with the class
               the sprite was built with (actor+0x258) so an outfit change shows at once
  0x14014d354  sprite layer setup: outfit sprites with their own complete animation set use their own
               block instead of the shared humanoid motion set (block 1)
"""
import struct

import pefile

try:
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
except ImportError:  # pragma: no cover
    Ks = None

IMAGE_BASE = 0x140000000
SECTION_NAME = b".d5mod"

OPEN_VA = 0x140263875
OPEN_ORIG = bytes.fromhex("488d8b98bd0000c783c8bd000001000000")
OPEN_RET = 0x140263886
DISPATCH_VA = 0x140263432
DISPATCH_ORIG = bytes.fromhex("8b8bacbd000085c97418")
HUB_VA = 0x14067E7D1
HUB_ORIG = bytes.fromhex("8b88042e0000")
HUB_RET = 0x14067E7DC
# faces: the character-list status panel and the Status screen play animation 10000 + graphics id
# (unit+0x2E36) of the resident UI block 9017.  Outfits with their own face picture get animation
# 10000 + outfit class id there; these hooks pick it for units wearing such an outfit.
FACE_A_VA = 0x1402AE881          # lea edx, [rcx+0x2710]   (unit = [rbx+0x90])
FACE_A_ORIG = bytes.fromhex("8d9110270000")
FACE_A_RET = 0x1402AE887
FACE_B_VA = 0x14043088E          # xor r9d,r9d / xor r8d,r8d / lea edx,[rax+r10]   (unit = r12)
FACE_B_ORIG = bytes.fromhex("4533c94533c0428d1410")
FACE_B_RET = 0x140430898
# graphics id (unit+0x2E36, = char.dat colour id for unique characters) is computed by 0x14021e9d0(class,
# colour); the character list's small face icons follow it.  Outfits with their own face get their own
# graphics id (their class id) here, while char.dat keeps the base colour id (safe for everything else).
GFX_VA = 0x14021E9D0
GFX_ORIG = bytes.fromhex("48895c2408")
GFX_RET = 0x14021E9D5
LAYER_VA = 0x14014D354
LAYER_ORIG = bytes.fromhex("98b90100000083f80a0f4cc8eb03")
LAYER_RET = 0x14014D365
# character objects rebuilt after a change (setup(actor, class, colour, 0, 0) @0x14014dc60, as the event
# command 'assign unit to actor' does): event / hub actors and unit actors
ACTORS_A = 0x14150ABD0     # 512 x 0x3e0   (lookup 0x140168a03)
ACTORS_B = 0x1415A5BE0     # 256 x 0x1260  (lookup 0x1402eac96)
# the hub's player character (leader): a global actor, found with a memory probe of the running game
# (the only object pointing at the unit; referenced by the movement code, e.g. 0x140169afd)
LEADER = 0x142349160

VANILLA_ENTRIES = [(0, 11957, 10589), (1, 10643, 10610), (2, 10593, 10590)]
MENU_VALUE = 3             # "Outfit"
PICK_BASE = 100            # outfit list entries: value = 100 + record index
MORE_VALUE = 99            # "More outfits": the next page of a long outfit list
MORE_LABEL_ID = 40009      # its StringListDataBase text (outfits.MORE_ID)
OUTFIT_PAGE = 12           # outfits per page: the list opens at a fixed place and ~14 rows fit on screen


def _asm(src, addr):
    """assemble src at addr; the game addresses written in it are those of the known build, translated to the build
    being patched (exemap.ACTIVE)"""
    if Ks is None:
        raise RuntimeError("keystone-engine is required: pip install keystone-engine")
    from . import exemap
    src = exemap.ACTIVE.text(src)
    ks = Ks(KS_ARCH_X86, KS_MODE_64)
    enc, _ = ks.asm(src, addr)
    return bytes(enc)


def add_hook_section(exe: bytes, name: bytes, hooks, shared_src="", writable=False, shared_bytes=b"") -> bytes:
    """Append a code section `name` to the exe and point hook sites at code inside it.
    hooks: [(va, original bytes, asm source, opcode 0xE9 jmp / 0xE8 call)].  `shared_src` (a subroutine with its
    data) is placed first; hook sources reach it as {shared}.  Each source is assembled at its own address, so labels
    only need to be unique within one source.  shared_bytes: raw data placed first instead (e.g. a zeroed buffer;
    writable=True makes the section writable)."""
    from . import exemap
    pe = pefile.PE(data=exe, fast_load=True)   # headers and sections only: a full parse takes ~1 s
    hooks = [(exemap.site(pe, va, orig, "hook site"), orig, body, op) for va, orig, body, op in hooks]
    sec_align = pe.OPTIONAL_HEADER.SectionAlignment
    file_align = pe.OPTIONAL_HEADER.FileAlignment
    secs = sorted(pe.sections, key=lambda s: s.VirtualAddress)
    last = secs[-1]
    fh = pe.DOS_HEADER.e_lfanew + 4
    sh_base = fh + 20 + pe.FILE_HEADER.SizeOfOptionalHeader
    # The exe has room for only a few more section headers: when the last section is already one of the kit's code
    # sections (and ends the file), the new code is appended to it instead of getting a header of its own.
    grow = (last.Name.startswith(b".d5") and last.Characteristics & 0x20000000
            and last.PointerToRawData + last.SizeOfRawData == len(exe))
    if grow:
        offset = (last.Misc_VirtualSize + 15) // 16 * 16
        base = IMAGE_BASE + last.VirtualAddress + offset
    else:
        new_rva = (last.VirtualAddress + max(last.Misc_VirtualSize, last.SizeOfRawData) + sec_align - 1) \
            // sec_align * sec_align
        base = IMAGE_BASE + new_rva
    code = bytes(shared_bytes) if shared_bytes else (_asm(shared_src, base) if shared_src else b"")
    starts = []
    for _, _, body, _ in hooks:
        code += b"\xCC" * (-len(code) % 16)
        starts.append(base + len(code))
        code += _asm(body.replace("{shared}", hex(base)), base + len(code))
    if grow:
        i = pe.sections.index(last)
        sh = sh_base + 40 * i
        vsize = offset + len(code)
        raw = (vsize + file_align - 1) // file_align * file_align
        body = bytearray(exe[last.PointerToRawData:last.PointerToRawData + last.Misc_VirtualSize])
        body += b"\xCC" * (offset - len(body)) + code
        body += b"\xCC" * (raw - len(body))
        out = bytearray(exe[:last.PointerToRawData]) + body
        struct.pack_into("<I", out, sh + 8, vsize)
        struct.pack_into("<I", out, sh + 16, raw)
        if writable:
            struct.pack_into("<I", out, sh + 36, last.Characteristics | 0x80000000)
        struct.pack_into("<I", out, fh + 20 + 56,
                         (last.VirtualAddress + vsize + sec_align - 1) // sec_align * sec_align)
    else:
        new_raw = (len(exe) + file_align - 1) // file_align * file_align
        section = code + b"\xCC" * (-len(code) % file_align)
        out = bytearray(exe) + b"\0" * (new_raw - len(exe))
        nsec = pe.FILE_HEADER.NumberOfSections
        sh_off = sh_base + 40 * nsec
        if sh_off + 40 > pe.OPTIONAL_HEADER.SizeOfHeaders:
            raise ValueError("no room for another section header")
        out[sh_off:sh_off + 40] = struct.pack("<8sIIIIIIHHI", name.ljust(8, b"\0"), len(code), new_rva,
                                              len(section), new_raw, 0, 0, 0, 0,
                                              0xE0000020 if writable else 0x60000020)  # code|execute|read(|write)
        struct.pack_into("<H", out, fh + 2, nsec + 1)
        struct.pack_into("<I", out, fh + 20 + 56, (new_rva + len(code) + sec_align - 1) // sec_align * sec_align)
        out += section
    for (va, orig, _, op), target in zip(hooks, starts):
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        out[off:off + len(orig)] = bytes([op]) + struct.pack("<i", target - (va + 5)) + b"\x90" * (len(orig) - 5)
    return bytes(out)


LAYER_SECTION = b".d5ly"


def build_layer_patch(exe: bytes, own_sprites) -> bytes:
    """Only the sprite layer hook of the outfit patch (sprites with their own complete animation set, e.g. new
    classes), for installs without outfits."""
    own = sorted({int(x) for x in own_sprites})
    nl = chr(10)
    src = nl.join([
        "    cwde",
        "    mov ecx, 1",
        "    cmp eax, 0xa",
        "    cmovl ecx, eax",
        "    lea r10, [rip + own_sprites]",
        f"    mov r11d, {len(own)}",
        "own_loop:",
        "    test r11d, r11d",
        "    je own_done",
        "    cmp eax, dword ptr [r10]",
        "    je own_hit",
        "    add r10, 4",
        "    dec r11d",
        "    jmp own_loop",
        "own_hit:",
        "    mov ecx, eax",
        "own_done:",
        f"    jmp {LAYER_RET:#x}",
        "    .align 4",
        "own_sprites:",
        "    .long " + ", ".join(map(str, own)),
    ])
    return add_hook_section(exe, LAYER_SECTION, [(LAYER_VA, LAYER_ORIG, src, 0xE9)])


def _jmp(frm, to, total_len):
    rel = to - (frm + 5)
    b = b"\xE9" + struct.pack("<i", rel)
    return b + b"\x90" * (total_len - len(b))


def is_patched(exe: bytes) -> bool:
    return SECTION_NAME in exe[:0x400]


def colour_swaps(n, a, b):
    """Custom colours of an outfit group with n looks: the worn look's set is the unit's colour set 0,
    the others wait in sets 1 and 2 in look order.  -> swap ops (1 = sets 0/1, 2 = sets 0/2, 3 = sets 1/2)
    turning the layout for look a into the one for look b."""
    lay = [a] + sorted(x for x in range(n) if x != a)
    ops = []
    if lay[0] != b:
        j = lay.index(b)
        lay[0], lay[j] = lay[j], lay[0]
        ops.append(j)
    if n > 2 and lay[1] > lay[2]:
        lay[1], lay[2] = lay[2], lay[1]
        ops.append(3)
    return ops


def build_outfit_patch(exe: bytes, records, label_id: int, help_id: int, own_sprites=(), faces=(),
                       looks=None, more_label=MORE_LABEL_ID) -> bytes:
    """Return a patched copy of a VANILLA exe.
    records: [(group, class id, label string id)] -- every outfit group lists its members in menu order
    (first = the character's normal look, "Default"); label 0 = hidden member (legacy ids that only
    belong to the group).
    faces: [(outfit class id, face animation id)] for outfits with their own face picture.
    looks: {class id: (look index, looks in the group)} -- each look keeps its own custom colours
    (Strategy Assembly precise colours) in one of the unit's three colour sets; 0 looks = shared."""
    from . import exemap
    pe = pefile.PE(data=exe, fast_load=True)   # headers and sections only: a full parse takes ~1 s
    if is_patched(exe):
        raise ValueError("exe already contains the .d5mod section (patch the vanilla exe)")
    at = {}
    for va, orig in ((OPEN_VA, OPEN_ORIG), (DISPATCH_VA, DISPATCH_ORIG), (HUB_VA, HUB_ORIG),
                     (LAYER_VA, LAYER_ORIG), (FACE_A_VA, FACE_A_ORIG), (FACE_B_VA, FACE_B_ORIG),
                     (GFX_VA, GFX_ORIG)):
        at[va] = exemap.site(pe, va, orig, "outfit menu patch site")

    sec_align = pe.OPTIONAL_HEADER.SectionAlignment
    file_align = pe.OPTIONAL_HEADER.FileAlignment
    last = pe.sections[-1]
    new_rva = (last.VirtualAddress + last.Misc_VirtualSize + sec_align - 1) // sec_align * sec_align
    new_raw = (len(exe) + file_align - 1) // file_align * file_align
    base = IMAGE_BASE + new_rva

    nl = chr(10)
    entries = VANILLA_ENTRIES + [(MENU_VALUE, label_id, help_id)]
    table = nl.join(f"        .long {v}, 0, {lab}, {hlp}" for v, lab, hlp in entries)
    recs = list(records) or [(0, 0, 0)]
    looks = looks or {}
    rtab = nl.join(f"        .long {PICK_BASE + i}, 0, {int(lab)}, {help_id}, {int(g)}, {int(c)}, "
                   f"{looks.get(int(c), (0, 0))[0]}, {looks.get(int(c), (0, 0))[1]}"
                   for i, (g, c, lab) in enumerate(recs))
    # swap ops for (looks n, from a, to b): two bytes each, table index n*9 + a*3 + b
    sw = []
    for n in range(4):
        for a in range(3):
            for b in range(3):
                ops = colour_swaps(n, a, b) if 2 <= n <= 3 and a < n and b < n else []
                sw.append(ops[0] if ops else 0)
                sw.append(ops[1] if len(ops) > 1 else 0)
    swtab = "        .byte " + ", ".join(str(x) for x in sw)
    own_sprites = sorted({int(x) for x in own_sprites})
    olist = nl.join(f"        .long {x}" for x in own_sprites) or "        .long 0"
    nrec = len(recs)
    faces = [(int(c), int(a)) for c, a in faces]
    flist = nl.join(f"        .long {c}, {a}" for c, a in faces) or "        .long 0, 0"
    # Code conventions: every entry point keeps rsp 16-byte aligned at each call; rbx = the character
    # list scene in the dispatch / open hooks; edi = 0 in the dispatch (as the game's own code there).
    src = f"""
    dispatch:
        mov ecx, dword ptr [rbx+0xbdac]
        cmp ecx, dword ptr [rbx+0xbda0]
        jae d_value
        mov rax, qword ptr [rbx+0xbd98]
        test rax, rax
        je d_value
        mov edx, ecx
        shl rdx, 4
        mov ecx, dword ptr [rax+rdx]
    d_value:
        cmp ecx, {MENU_VALUE}
        je outfit_menu
        cmp ecx, {MORE_VALUE}
        je outfit_more
        cmp ecx, {PICK_BASE}
        jge outfit_pick
        test ecx, ecx
        je 0x140263454
        jmp 0x14026343c

    outfit_more:
        inc dword ptr [rip + outfit_page]
        jmp om_start
    outfit_menu:
        mov dword ptr [rip + outfit_page], 0
    om_start:
        push r12
        push r13
        push r14
        push r15
        sub rsp, 0x30
        call selected_unit
        mov r12, rax
        call find_group
        cmp eax, -1
        je om_close
        mov r13d, eax
        lea r14, [rip + outfit_records]
        xor edx, edx
        mov ecx, {nrec}
    om_count:
        cmp dword ptr [r14+16], r13d
        jne om_c1
        cmp dword ptr [r14+8], 0
        je om_c1
        inc edx
    om_c1:
        add r14, 32
        dec ecx
        jne om_count
        mov eax, dword ptr [rip + outfit_page]
        imul eax, eax, {OUTFIT_PAGE}
        cmp eax, edx
        jb om_pg_ok
        mov dword ptr [rip + outfit_page], 0
        xor eax, eax
    om_pg_ok:
        mov dword ptr [rsp+0x20], eax
        mov ecx, edx
        sub ecx, eax
        cmp ecx, {OUTFIT_PAGE}
        jbe om_pg_n
        mov ecx, {OUTFIT_PAGE}
    om_pg_n:
        mov dword ptr [rsp+0x24], ecx
        mov dword ptr [rsp+0x28], edx
        cmp edx, {OUTFIT_PAGE}
        jbe om_pg_init
        inc ecx
    om_pg_init:
        mov edx, ecx
        lea rcx, [rbx+0xbd98]
        call 0x1402b16b0
        lea r14, [rip + outfit_records]
        mov r15d, {nrec}
    om_add:
        cmp dword ptr [r14+16], r13d
        jne om_a1
        cmp dword ptr [r14+8], 0
        je om_a1
        cmp dword ptr [rsp+0x20], 0
        je om_take
        dec dword ptr [rsp+0x20]
        jmp om_a1
    om_take:
        cmp dword ptr [rsp+0x24], 0
        je om_a1
        dec dword ptr [rsp+0x24]
        mov rdx, r14
        lea rcx, [rbx+0xbd98]
        call 0x1402b0cb0
    om_a1:
        add r14, 32
        dec r15d
        jne om_add
        cmp dword ptr [rsp+0x28], {OUTFIT_PAGE}
        jbe om_show
        lea rdx, [rip + more_entry]
        lea rcx, [rbx+0xbd98]
        call 0x1402b0cb0
    om_show:
        lea rcx, [rbx+0xbd98]
        call 0x1402b09a0
        mov byte ptr [rbx+0xbdcc], 0
        add rsp, 0x30
        pop r15
        pop r14
        pop r13
        pop r12
        mov rbp, qword ptr [rsp+0x60]
        jmp 0x140263a5f
    om_close:
        add rsp, 0x30
        pop r15
        pop r14
        pop r13
        pop r12
        jmp back_to_list

    outfit_pick:
        push r12
        push r13
        push r14
        push r15
        sub rsp, 0x30
        sub ecx, {PICK_BASE}
        cmp ecx, {nrec}
        jae op_done
        mov r14d, ecx
        shl r14, 5
        lea rax, [rip + outfit_records]
        add r14, rax
        call selected_unit
        test rax, rax
        je op_done
        mov r12, rax
        call swap_colours
        mov eax, dword ptr [r14+20]
        mov dword ptr [r12+0x2e04], eax
        mov rcx, r12
        call 0x14015eb80
        lea r13, [rip + ACTORS_A]
        mov r14d, 512
        mov r15d, 0x3e0
        call refresh_actors
        lea r13, [rip + ACTORS_B]
        mov r14d, 256
        mov r15d, 0x1260
        call refresh_actors
        lea r13, [rip + LEADER]
        mov r14d, 1
        xor r15d, r15d
        call refresh_actors
    op_done:
        add rsp, 0x30
        pop r15
        pop r14
        pop r13
        pop r12
    back_to_list:
        mov byte ptr [rbx+0xbdcc], 0
        mov dword ptr [rbx+0xbdc8], edi
        mov rbp, qword ptr [rsp+0x60]
        jmp 0x1402634e9

    open_hook:
        push r12
        push r13
        sub rsp, 0x20
        call selected_unit
        mov r12, rax
        call find_group
        mov r13d, 3
        cmp eax, -1
        je oh_init
        mov r13d, 4
    oh_init:
        mov edx, r13d
        lea rcx, [rbx+0xbd98]
        call 0x1402b16b0
        lea r12, [rip + menu_entries]
    oh_add:
        mov rdx, r12
        lea rcx, [rbx+0xbd98]
        call 0x1402b0cb0
        add r12, 16
        dec r13d
        jne oh_add
        add rsp, 0x20
        pop r13
        pop r12
        lea rcx, [rbx+0xbd98]
        mov dword ptr [rbx+0xbdc8], 1
        jmp {OPEN_RET:#x}

    swap_colours:
        mov ecx, dword ptr [r12+0x2e04]
        lea r8, [rip + outfit_records]
        mov r9d, {nrec}
    sc_find:
        cmp dword ptr [r8+20], ecx
        je sc_found
        add r8, 32
        dec r9d
        jne sc_find
        ret
    sc_found:
        mov eax, dword ptr [r8+16]
        cmp eax, dword ptr [r14+16]
        jne sc_ret
        mov eax, dword ptr [r14+28]
        cmp eax, 3
        ja sc_runtime
        cmp eax, 2
        jb sc_ret
        mov ecx, dword ptr [r8+24]
        cmp ecx, 3
        jae sc_ret
        mov edx, dword ptr [r14+24]
        cmp edx, 3
        jae sc_ret
        imul eax, eax, 9
        imul ecx, ecx, 3
        add eax, ecx
        add eax, edx
        lea r8, [rip + swap_ops]
        movzx r10d, word ptr [r8+rax*2]
        movzx ecx, r10b
        call sc_op
        shr r10d, 8
        movzx ecx, r10b
        call sc_op
    sc_ret:
        ret
    sc_runtime:
        # more looks than the unit has colour sets: the kit's runtime keeps every look's colours
        # (d5looks.inc.c fills looks_cb at start-up; without the runtime the looks share the colours)
        mov rax, qword ptr [rip + looks_cb]
        test rax, rax
        je sc_ret
        sub rsp, 0x28
        mov rcx, r12
        mov edx, dword ptr [r12+0x2e04]
        mov r8d, dword ptr [r14+20]
        call rax
        add rsp, 0x28
        ret
    sc_op:
        test ecx, ecx
        je so_ret
        lea r8, [r12+0x35c4]
        lea r9, [r12+0x3a44]
        cmp ecx, 1
        je so_go
        lea r9, [r12+0x3ec4]
        cmp ecx, 2
        je so_go
        lea r8, [r12+0x3a44]
    so_go:
        mov edx, 0x90
    so_loop:
        mov rax, qword ptr [r8]
        mov r11, qword ptr [r9]
        mov qword ptr [r8], r11
        mov qword ptr [r9], rax
        add r8, 8
        add r9, 8
        dec edx
        jne so_loop
    so_ret:
        ret

    selected_unit:
        sub rsp, 0x28
        lea rcx, [rbx+0x80]
        call 0x1400928d0
        test rax, rax
        je su_ret
        mov rax, qword ptr [rax]
    su_ret:
        add rsp, 0x28
        ret

    find_group:
        mov eax, -1
        test r12, r12
        je fg_ret
        mov ecx, dword ptr [r12+0x2e04]
        lea r8, [rip + outfit_records]
        mov r9d, {nrec}
    fg_loop:
        cmp dword ptr [r8+20], ecx
        je fg_hit
        add r8, 32
        dec r9d
        jne fg_loop
        ret
    fg_hit:
        mov eax, dword ptr [r8+16]
    fg_ret:
        ret

    refresh_actors:
        sub rsp, 0x38
    ra_loop:
        cmp qword ptr [r13+0x240], r12
        jne ra_next
        cmp qword ptr [r13+0x1d0], 0
        je ra_next
        mov rcx, r13
        mov edx, dword ptr [r12+0x2e04]
        movzx r8d, byte ptr [r12+0x2e2c]
        xor r9d, r9d
        mov dword ptr [rsp+0x20], 0
        call 0x14014dc60
    ra_next:
        add r13, r15
        dec r14d
        jne ra_loop
        add rsp, 0x38
        ret

    hub_compare:
        mov ecx, dword ptr [rax+0x2e04]
        cmp ecx, dword ptr [r14+0x258]
        je hc_done
        cmp dword ptr [r14+0x258], 0x1f4
        jne hc_diff
        cmp ecx, 0x28
        je hc_done
    hc_diff:
        mov ecx, dword ptr [r14+0x258]
    hc_done:
        jmp {HUB_RET:#x}

    face_a:
        lea edx, [rcx+0x2710]
        mov r10, qword ptr [rbx+0x90]
        call face_remap
        jmp {FACE_A_RET:#x}

    face_b:
        lea edx, [rax+r10]
        mov r10, r12
        call face_remap
        xor r9d, r9d
        xor r8d, r8d
        jmp {FACE_B_RET:#x}

    gfx_hook:
        lea r10, [rip + face_map]
        mov r11d, {max(1, len(faces))}
    g_loop:
        cmp dword ptr [r10], ecx
        je g_hit
        add r10, 8
        dec r11d
        jne g_loop
        mov qword ptr [rsp+8], rbx
        jmp {GFX_RET:#x}
    g_hit:
        mov eax, ecx
        ret

    face_remap:
        test r10, r10
        je fr_ret
        mov r11d, dword ptr [r10+0x2e04]
        lea r10, [rip + face_map]
        push rcx
        mov ecx, {max(1, len(faces))}
    fr_loop:
        cmp dword ptr [r10], r11d
        je fr_hit
        add r10, 8
        dec ecx
        jne fr_loop
        pop rcx
        ret
    fr_hit:
        mov edx, dword ptr [r10+4]
        pop rcx
    fr_ret:
        ret

    layer_block:
        cwde
        mov ecx, 1
        cmp eax, 0xa
        cmovl ecx, eax
        lea r10, [rip + own_sprites]
        mov r11d, {len(own_sprites)}
    own_loop:
        test r11d, r11d
        je own_done
        cmp eax, dword ptr [r10]
        je own_hit
        add r10, 4
        dec r11d
        jmp own_loop
    own_hit:
        mov ecx, eax
    own_done:
        jmp {LAYER_RET:#x}
        int3
        int3
        int3
        int3
    menu_entries:
{table}
    more_entry:
        .long {MORE_VALUE}, 0, {more_label}, {help_id}
    outfit_records:
{rtab}
    swap_ops:
{swtab}
        .align 4
    own_sprites:
{olist}
    face_map:
{flist}
        .align 8
    looks_marker:
        .byte 0x44, 0x35, 0x4c, 0x4f, 0x4f, 0x4b, 0x43, 0x42
    looks_cb:
        .quad 0
    outfit_page:
        .long 0
    ACTORS_A = {ACTORS_A:#x}
    ACTORS_B = {ACTORS_B:#x}
    LEADER = {LEADER:#x}
    """
    code_va = base
    code = _asm(src, code_va)
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    labels = {}
    insns = list(Cs(CS_ARCH_X86, CS_MODE_64).disasm(code, code_va))
    # locate entry points by their first instruction (keystone doesn't return symbol addresses)
    labels["dispatch"] = code_va
    for k, ins in enumerate(insns):
        if "open" not in labels and ins.mnemonic == "push" and ins.op_str == "r12" and k + 2 < len(insns) \
                and insns[k + 1].op_str == "r13" and insns[k + 2].op_str == "rsp, 0x20":
            labels["open"] = ins.address
        if ins.mnemonic == "cmp" and ins.op_str == "ecx, dword ptr [r14 + 0x258]" and "hub" not in labels:
            labels["hub"] = insns[k - 1].address
        if ins.mnemonic == "cwde" and "layer" not in labels:
            labels["layer"] = ins.address
        if ins.mnemonic == "lea" and ins.op_str == "edx, [rcx + 0x2710]" and "face_a" not in labels:
            labels["face_a"] = ins.address
        if ins.mnemonic == "lea" and ins.op_str == "edx, [rax + r10]" and "face_b" not in labels:
            labels["face_b"] = ins.address
        nf = max(1, len(faces))
        if ins.mnemonic == "mov" and ins.op_str in ("r11d, " + str(nf), "r11d, " + hex(nf)) and "gfx" not in labels                 and insns[k - 1].mnemonic == "lea":
            labels["gfx"] = insns[k - 1].address
    if len(labels) != 7:
        raise RuntimeError(f"could not locate entry points in assembled code: {labels}")
    section = code
    vsize = len(section)
    section += b"\xCC" * (-len(section) % file_align)

    out = bytearray(exe) + b"\0" * (new_raw - len(exe))
    nsec = pe.FILE_HEADER.NumberOfSections
    sh_off = pe.DOS_HEADER.e_lfanew + 4 + 20 + pe.FILE_HEADER.SizeOfOptionalHeader + 40 * nsec
    if sh_off + 40 > pe.OPTIONAL_HEADER.SizeOfHeaders:
        raise ValueError("no room for another section header")
    hdr = struct.pack("<8sIIIIIIHHI", SECTION_NAME.ljust(8, b"\0"), vsize, new_rva, len(section), new_raw,
                      0, 0, 0, 0, 0xE0000020)  # code | execute | read | write (the outfit list page)
    out[sh_off:sh_off + 40] = hdr
    fh = pe.DOS_HEADER.e_lfanew + 4
    struct.pack_into("<H", out, fh + 2, nsec + 1)
    oh = fh + 20
    size_of_image = (new_rva + vsize + sec_align - 1) // sec_align * sec_align
    struct.pack_into("<I", out, oh + 56, size_of_image)  # SizeOfImage (PE32+ offset 56)
    out += section

    def put(va, b):
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        out[off:off + len(b)] = b

    def hook(va, label, orig):
        put(at[va], _jmp(at[va], labels[label], len(orig)))

    hook(DISPATCH_VA, "dispatch", DISPATCH_ORIG)
    hook(OPEN_VA, "open", OPEN_ORIG)
    hook(HUB_VA, "hub", HUB_ORIG)
    if own_sprites:
        hook(LAYER_VA, "layer", LAYER_ORIG)
    if faces:
        hook(FACE_A_VA, "face_a", FACE_A_ORIG)
        hook(FACE_B_VA, "face_b", FACE_B_ORIG)
        hook(GFX_VA, "gfx", GFX_ORIG)
    return bytes(out)
