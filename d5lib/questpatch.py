"""Exe support for brand-new characters (one code section, ".d5qr", on top of the other .d5 patches).

Recruit quests
--------------
Quest.dat reward_type 5 ("a character joins") does not create a unit: the reward code (0x1407f1e2a) looks for a
unit of that class in the hidden reserve (the top roster slots 128 - reserve .. 127, count at 0x1455a293e) and moves
it into the army.  The vanilla overlords are put there by the story; a new character never is, so its quest would
complete without a reward.  The hook runs at the start of that reward case, for the modded recruit classes only:
when the character is neither in the reserve nor in the army, it creates the unit at level 1 with the game's own
routine (0x1402ea890, as the event command 0x7850 'join' does) and moves it into the reserve (0x1402ea4b0); the
vanilla code then recruits it as usual (message, flags).

Class shown by the colour screen
--------------------------------
The colour screen (Topic "Change Colors" / "Change More Colors") asks 0x140457aa0 for a number that it uses twice:
as the class of its preview character (0x14040df20) and as the loaded anm block whose palettes fill the colour
slots (0x1403025b0 at 0x140453bb5).  0x140457aa0 returns the unit's class with a few Killia / Christo forms
special-cased and ids >= 1010 rounded down to a multiple of 10 (tiers of a generic class share their family's
look); for vanilla characters class and sprite number are the same.  A new character (class 9003, sprite 9070)
was rounded into another row (9000), and even unrounded its palettes came from resident block 9003 (an effect):
no colours listed, and the precise editor crashed on its empty part list (0x140452771).  An outfit slot (class
470 wearing sprite 9550) had the palette half of the problem.  Two hooks: 0x140457aa0 keeps the exact class for
such new characters, and the colour screen's palette lookup maps the class to its sprite.  Everything else runs
the vanilla code.
"""
import struct

import pefile

from . import database
from .dbpatch import DB_ARCHIVE
from .exepatch import IMAGE_BASE, _asm
from .gamefs import EXE_FILE
from .modsys import register_finalizer

SECTION_NAME = b".d5qr"
HOOK_VA = 0x1407F1E2A            # movsx eax, word ptr [reserve count]   (quest row = r12)
HOOK_ORIG = bytes.fromhex("0fbf050d0bdb04")
HOOK_RET = 0x1407F1E31
RESERVE_COUNT = 0x1455A293E
ARMY_COUNT = 0x1455A293C
UNIT_CLASS = 0x145238A5C         # roster unit 0 + 0x2e04 (class id); units are 0x4750 bytes, 128 slots
UNIT_SIZE = 0x4750
CREATE_UNIT = 0x1402EA890        # (class, 0, level) -> unit appended to the army, 0 when the roster is full
TO_RESERVE = 0x1402EA4B0         # (army index) -> moves the unit into the reserve
VANILLA_RECRUITS = {250, 280, 300, 310}   # quests 2-5: the story puts these overlords in the reserve

ANM_OF_VA = 0x140457AA0          # class for the colour screen: mov rax, [rcx+0x47e0] (unit copy) / mov edx, [rax+0x2e04]
ANM_OF_ORIG = bytes.fromhex("488b81e04700008b90042e0000")
ANM_OF_RET = 0x140457AAD
# classes 0x140457aa0 maps by itself (Killia / Christo forms): left to the game
SPECIAL_CLASSES = {10, 40, 70, 530, 570, 590, 710, 800}
PAL_CALL_VA = 0x140453BB5        # colour screen: call 0x1403025b0 (loaded anm block by number, ecx = class shown)
PAL_LOOKUP = 0x1403025B0


def is_hooked(exe: bytes) -> bool:
    return SECTION_NAME in exe[:0x400]


def _recruit_src(ids):
    nl = chr(10)
    # rsp is 16-aligned inside the reward function; only volatile registers are used (r12 = quest row survives calls)
    return nl.join([
        "recruit:",
        "    sub rsp, 0x20",
        "    mov ecx, dword ptr [r12 + 0x15d0]",
        "    lea rdx, [rip + recruit_ids]",
        f"    mov r8d, {len(ids)}",
        "ids_loop:",
        "    cmp dword ptr [rdx], ecx",
        "    je listed",
        "    add rdx, 4",
        "    dec r8d",
        "    jne ids_loop",
        "    jmp done",
        "listed:",
        "    movsx eax, word ptr [rip + RESERVE_COUNT]",
        "    mov edx, 0x80",
        "    sub edx, eax",
        "    movsxd rax, edx",
        f"    imul rax, rax, {UNIT_SIZE:#x}",
        "    lea r9, [rip + UNIT_CLASS]",
        "    add r9, rax",
        "res_loop:",
        "    cmp edx, 0x80",
        "    jge army",
        "    cmp dword ptr [r9], ecx",
        "    je done",
        "    inc edx",
        f"    add r9, {UNIT_SIZE:#x}",
        "    jmp res_loop",
        "army:",
        "    movsx r8d, word ptr [rip + ARMY_COUNT]",
        "    xor edx, edx",
        "    lea r9, [rip + UNIT_CLASS]",
        "army_loop:",
        "    cmp edx, r8d",
        "    jge create",
        "    cmp dword ptr [r9], ecx",
        "    je done",
        "    inc edx",
        f"    add r9, {UNIT_SIZE:#x}",
        "    jmp army_loop",
        "create:",
        "    xor edx, edx",
        "    mov r8d, 1",
        f"    call {CREATE_UNIT:#x}",
        "    test rax, rax",
        "    je done",
        "    movsx ecx, word ptr [rip + ARMY_COUNT]",
        "    dec ecx",
        f"    call {TO_RESERVE:#x}",
        "done:",
        "    add rsp, 0x20",
        "    movsx eax, word ptr [rip + RESERVE_COUNT]",
        f"    jmp {HOOK_RET:#x}",
        "    .align 4",
        "recruit_ids:",
        "    .long " + ", ".join(str(c) for c in (ids or [0])),
        f"    RESERVE_COUNT = {RESERVE_COUNT:#x}",
        f"    ARMY_COUNT = {ARMY_COUNT:#x}",
        f"    UNIT_CLASS = {UNIT_CLASS:#x}",
    ])


def _lookup_src(label, reg, pairs, hit, miss):
    """map `reg` through a (from, to) table: `hit` runs with eax = to, `miss` otherwise"""
    nl = chr(10)
    return nl.join([
        f"    lea r8, [rip + {label}_map]",
        f"    mov r9d, {len(pairs)}",
        f"{label}_loop:",
        "    test r9d, r9d",
        f"    je {label}_miss",
        f"    cmp dword ptr [r8], {reg}",
        f"    je {label}_hit",
        "    add r8, 8",
        "    dec r9d",
        f"    jmp {label}_loop",
        f"{label}_hit:",
        "    mov eax, dword ptr [r8 + 4]",
        hit,
        f"{label}_miss:",
        miss,
        "    .align 4",
        f"{label}_map:",
        nl.join(f"    .long {c}, {s}" for c, s in pairs),
    ])


def _class_src(pairs):
    # replaces the entry of 0x140457aa0: the exact class for listed classes, else the vanilla body
    return chr(10).join(["    mov rax, qword ptr [rcx + 0x47e0]", "    mov edx, dword ptr [rax + 0x2e04]",
                         _lookup_src("cls", "edx", pairs, "    ret", f"    jmp {ANM_OF_RET:#x}")])


def _palette_src(pairs):
    # called instead of 0x1403025b0(ecx = class shown) by the colour screen: the loaded anm block of the sprite
    return _lookup_src("pal", "ecx", pairs, "    mov ecx, eax" + chr(10) + f"    jmp {PAL_LOOKUP:#x}",
                       f"    jmp {PAL_LOOKUP:#x}")


def build_newchar_hook(exe: bytes, recruit_ids=(), class_map=None, palette_map=None) -> bytes:
    """Add the recruit and/or colour-screen hooks to an exe (vanilla or already carrying other .d5 patches).
    class_map: {class: class the colour screen shows} (see class_map());
    palette_map: {class shown: sprite number} (see palette_map())."""
    ids = sorted({int(c) for c in recruit_ids})
    cls_pairs = sorted((int(c), int(s)) for c, s in (class_map or {}).items())
    pal_pairs = sorted((int(c), int(s)) for c, s in (palette_map or {}).items())
    if (not ids and not cls_pairs and not pal_pairs) or is_hooked(exe):
        return exe
    pe = pefile.PE(data=exe, fast_load=True)   # headers and sections only: a full parse takes ~1 s
    pal_orig = b"\xE8" + struct.pack("<i", PAL_LOOKUP - (PAL_CALL_VA + 5))
    sites = [(HOOK_VA, HOOK_ORIG, ids, _recruit_src, 0xE9), (ANM_OF_VA, ANM_OF_ORIG, cls_pairs, _class_src, 0xE9),
             (PAL_CALL_VA, pal_orig, pal_pairs, _palette_src, 0xE8)]
    from . import exemap
    sites = [(exemap.site(pe, va, orig, "the new-character hook site") if used else va, orig, used, src, op)
             for va, orig, used, src, op in sites]
    sec_align = pe.OPTIONAL_HEADER.SectionAlignment
    file_align = pe.OPTIONAL_HEADER.FileAlignment
    last = max(pe.sections, key=lambda s: s.VirtualAddress)
    new_rva = (last.VirtualAddress + max(last.Misc_VirtualSize, last.SizeOfRawData) + sec_align - 1) \
        // sec_align * sec_align
    new_raw = (len(exe) + file_align - 1) // file_align * file_align
    base = IMAGE_BASE + new_rva
    code = b""
    entries = []
    for va, orig, used, src, op in sites:
        if not used:
            continue
        code += b"\xCC" * (-len(code) % 16)
        entries.append((va, orig, base + len(code), op))
        code += _asm(src(used), base + len(code))
    section = code + b"\xCC" * (-len(code) % file_align)
    out = bytearray(exe) + b"\0" * (new_raw - len(exe))
    nsec = pe.FILE_HEADER.NumberOfSections
    sh_off = pe.DOS_HEADER.e_lfanew + 4 + 20 + pe.FILE_HEADER.SizeOfOptionalHeader + 40 * nsec
    if sh_off + 40 > pe.OPTIONAL_HEADER.SizeOfHeaders:
        raise ValueError("no room for another section header")
    hdr = struct.pack("<8sIIIIIIHHI", SECTION_NAME.ljust(8, b"\0"), len(code), new_rva, len(section), new_raw,
                      0, 0, 0, 0, 0x60000020)  # code | execute | read
    out[sh_off:sh_off + 40] = hdr
    fh = pe.DOS_HEADER.e_lfanew + 4
    struct.pack_into("<H", out, fh + 2, nsec + 1)
    size_of_image = (new_rva + len(code) + sec_align - 1) // sec_align * sec_align
    struct.pack_into("<I", out, fh + 20 + 56, size_of_image)
    out += section
    for va, orig, target, op in entries:
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        out[off:off + len(orig)] = bytes([op]) + struct.pack("<i", target - (va + 5)) + b"\x90" * (len(orig) - 5)
    return bytes(out)


def build_recruit_hook(exe: bytes, class_ids) -> bytes:
    return build_newchar_hook(exe, class_ids)


def recruit_classes(quest_table):
    """Classes that modded quests recruit (reward_type 5), without the story's own recruits."""
    return sorted({r["reward_value"] for r in quest_table.rows
                   if r["reward_type"] == 5 and r["reward_value"] not in VANILLA_RECRUITS})


def _modded(char_table, vanilla_table):
    """rows mods added or gave another sprite (the Killia / Christo forms are left alone)"""
    van = {r["id"]: r["sprite_id"] for r in vanilla_table.rows}
    return [r for r in char_table.rows
            if r["id"] not in SPECIAL_CLASSES and r["sprite_id"] and van.get(r["id"]) != r["sprite_id"]]


def class_map(char_table, vanilla_table):
    """{class: class} for new characters >= 1010 that the colour screen's rounding (ids >= 1010 -> multiple of 10)
    would turn into another row: the rounded class isn't their own family (a row with the same sprite)."""
    rows = {r["id"]: r for r in char_table.rows}
    van = {r["id"] for r in vanilla_table.rows}
    out = {}
    for r in _modded(char_table, vanilla_table):
        cls = r["id"]
        if cls in van or cls < 1010 or cls % 10 == 0:
            continue
        base = rows.get(cls // 10 * 10)
        if base is None or base["sprite_id"] != r["sprite_id"]:
            out[cls] = cls
    return out


def palette_map(char_table, vanilla_table, cmap):
    """{class the colour screen shows: sprite} where those numbers differ (the palettes are read from the loaded
    anm block with the shown number)."""
    out = {}
    for r in _modded(char_table, vanilla_table):
        cls = r["id"]
        shown = cls if cls in cmap or cls < 1010 else cls // 10 * 10
        if shown != r["sprite_id"]:
            out.setdefault(shown, r["sprite_id"])
    return out


def _finalize(ctx):
    qpath, cpath = f"{DB_ARCHIVE}/Quest.dat", f"{DB_ARCHIVE}/char.dat"
    ids, cmap, pmap = [], {}, {}
    if qpath.lower() in ctx.outputs:
        ids = recruit_classes(database.load_table("Quest.dat", ctx.get(qpath)))
    if cpath.lower() in ctx.outputs:
        chars = database.load_table("char.dat", ctx.get(cpath))
        vanilla = database.load_table("char.dat", ctx.fs.read(cpath))
        cmap = class_map(chars, vanilla)
        pmap = palette_map(chars, vanilla, cmap)
    if ids or cmap or pmap:
        ctx.put(EXE_FILE, build_newchar_hook(ctx.get(EXE_FILE), ids, cmap, pmap))
        if ids:
            ctx.log(f"  new characters: recruit hook for {', '.join(map(str, ids))}")
        if cmap or pmap:
            ctx.log("  new characters: colour screen classes " + ", ".join(map(str, sorted(cmap))) + "; palettes "
                    + ", ".join(f"{c}->{s}" for c, s in sorted(pmap.items())))


register_finalizer(_finalize)
