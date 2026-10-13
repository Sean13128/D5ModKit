"""No story locks for modded characters (one code section, ".d5ul").

The game holds some evilities, Overloads and skills back until the story unlocks them, whoever has them in char.dat:
  innate evilities   ids 11, 41, 51, 61, 71, 101 (the main cast's second evilities) need a story flag, checked in
                     the three unit setups (0x14021a970 creation, 0x140217280, 0x140219040); besides, a unit only has
                     1 unique-evility slot (+1 per extra slot bought for it) and gets its innate evilities only when
                     it is set up, so a second innate evility never shows on its own
  Overload           0x14015ce30  Overloads 1, 2, 4, 6, 8, 9, 12 need a story flag (the unit gets "none" before)
  learnset skills    0x1401d5ce0  10013, 10014, 10063, combo skills ... need a story flag; 11161-11166 only for
                                  two class families
For every character row a mod adds or edits these checks are skipped, and the unit refresh gives such a unit one
unique-evility slot per innate evility and fills in the innate evilities it lacks, so whatever the mod gives it works
at once, also for units recruited before (skills are learned at the next unit refresh once the unit's level reaches
the learn level).  Characters no mod touches keep the story's order.
"""
from . import database
from .dbpatch import DB_ARCHIVE
from .exepatch import add_hook_section
from .gamefs import EXE_FILE
from .modsys import register_finalizer

SECTION_NAME = b".d5ul"

# innate evility loops of the unit setups (creation 0x14021a970, 0x140217280, 0x140219040): edx = evility id,
# r14 = char row, rbx = unit.  (site, original "cmp byte ptr [rbx+0x2e32], <zero reg> / jne add", zero reg,
# story check, add)
EVI_SITES = [
    (0x14021AE47, bytes.fromhex("4038b3322e00007554"), "sil", 0x14021AE50, 0x14021AEA4),
    (0x140217707, bytes.fromhex("4038b3322e00007554"), "sil", 0x140217710, 0x140217764),
    (0x1402194F5, bytes.fromhex("4038ab322e00007557"), "bpl", 0x1402194FE, 0x140219555),
]
# unit refresh (0x14021b430): ax = unique evility slots (1 + extra slots bought for the unit, bits 0-3 of +0x3034)
# being stored to +0x2efa.  Innate evilities only go into those slots (+0x2eee, 5 x u16, 9999 = empty; +0x2ef8 used)
# and only when a unit is set up, so a modded character gets a slot per innate evility here and any innate evility
# it lacks (added to the character later) is filled in.
SLOTS_VA = 0x14021B9DE
SLOTS_ORIG = bytes.fromhex("80bb322e000000668983fa2e0000")  # cmp byte ptr [rbx+0x2e32], 0 / mov [rbx+0x2efa], ax
SLOTS_RET = 0x14021B9EC
CHAR_RECORDS = 0x140A31880       # -> char.dat rows (0x38c each); unit +0x2e0a = row index
# Overload of a unit: rax = char row (after the forms' mapping); 0x14015cf92 returns r9d
OVL_VA = 0x14015CEB3
OVL_ORIG = bytes.fromhex("440fb788cc000000")       # movzx r9d, word ptr [rax+0xcc]
OVL_NEXT, OVL_RETURN = 0x14015CEBB, 0x14015CF92
# may the unit (rcx) learn the skill (rdx = magic row)?  -> al
LEARN_VA = 0x1401D5CE0
LEARN_ORIG = bytes.fromhex("448b02488bc1")         # mov r8d, [rdx] / mov rax, rcx
LEARN_NEXT = 0x1401D5CE6


def is_patched(exe: bytes) -> bool:
    return SECTION_NAME in exe[:0x400]


def _shared(ids):
    # free_class: eax = class -> ZF set when it is a modded class; every register kept
    nl = chr(10)
    return nl.join([
        "free_class:",
        "    push rcx",
        "    push rdx",
        "    lea rdx, [rip + free_ids]",
        f"    mov ecx, {len(ids)}",
        "fc_loop:",
        "    cmp dword ptr [rdx], eax",
        "    je fc_done",
        "    add rdx, 4",
        "    dec ecx",
        "    jne fc_loop",
        "    test rdx, rdx",                      # not listed: ZF clear
        "fc_done:",
        "    pop rdx",
        "    pop rcx",
        "    ret",
        "    .align 4",
        "free_ids:",
        "    .long " + ", ".join(str(i) for i in ids),
    ])


def _evility_src(zero, check, add):
    nl = chr(10)
    return nl.join([
        f"    cmp byte ptr [rbx + 0x2e32], {zero}",
        "    jne add",
        "    push rax",
        "    mov eax, dword ptr [r14 + 0xd0]",
        "    call {shared}",
        "    pop rax",
        "    je add",
        f"    jmp {check:#x}",
        "add:",
        f"    jmp {add:#x}",
    ])


def _slots_src():
    nl = chr(10)
    return nl.join([
        "    push rcx",
        "    push rdx",
        "    push r8",
        "    push r9",
        "    push r10",
        "    mov ecx, eax",                                   # slots the game computed
        "    mov eax, dword ptr [rbx + 0x2e04]",
        "    call {shared}",
        "    jne keep",
        "    movsx rdx, word ptr [rbx + 0x2e0a]",
        "    imul rdx, rdx, 0x38c",
        "    add rdx, qword ptr [rip + CHAR_RECORDS]",         # char row (rip-relative: the image is relocated)
        "    movzx r8d, byte ptr [rdx + 0xc8]",                # innate evilities
        "    cmp r8d, 4",
        "    jbe cnt_ok",
        "    mov r8d, 4",
        "cnt_ok:",
        "    mov eax, r8d",
        "    cmp eax, ecx",
        "    cmovb eax, ecx",
        "    mov word ptr [rbx + 0x2efa], ax",
        "    xor r9d, r9d",
        "ev_loop:",
        "    cmp r9d, r8d",
        "    jge done",
        "    mov ecx, dword ptr [rdx + r9*4 + 0xb8]",
        "    test ecx, ecx",
        "    je ev_next",
        "    xor eax, eax",
        "find:",                                              # already in a slot?
        "    cmp word ptr [rbx + rax*2 + 0x2eee], cx",
        "    je ev_next",
        "    inc eax",
        "    cmp eax, 5",
        "    jb find",
        "    xor eax, eax",
        "    movsx r10d, word ptr [rbx + 0x2efa]",
        "empty:",                                             # first free slot
        "    cmp eax, r10d",
        "    jge ev_next",
        "    cmp word ptr [rbx + rax*2 + 0x2eee], 0x270f",
        "    je put",
        "    inc eax",
        "    jmp empty",
        "put:",
        "    mov word ptr [rbx + rax*2 + 0x2eee], cx",
        "    inc word ptr [rbx + 0x2ef8]",
        "ev_next:",
        "    inc r9d",
        "    jmp ev_loop",
        "done:",
        "    movzx eax, word ptr [rbx + 0x2efa]",
        "    jmp out",
        "keep:",
        "    mov eax, ecx",
        "    mov word ptr [rbx + 0x2efa], ax",
        "out:",
        "    pop r10",
        "    pop r9",
        "    pop r8",
        "    pop rdx",
        "    pop rcx",
        "    cmp byte ptr [rbx + 0x2e32], 0",
        f"    jmp {SLOTS_RET:#x}",
        f"    CHAR_RECORDS = {CHAR_RECORDS:#x}",
    ])


def _overload_src():
    nl = chr(10)
    return nl.join([
        "    movzx r9d, word ptr [rax + 0xcc]",
        "    push rax",
        "    mov eax, dword ptr [rax + 0xd0]",
        "    call {shared}",
        "    pop rax",
        "    je free",
        f"    jmp {OVL_NEXT:#x}",
        "free:",
        f"    jmp {OVL_RETURN:#x}",
    ])


def _learn_src():
    nl = chr(10)
    return nl.join([
        "    mov r8d, dword ptr [rdx]",
        "    mov rax, rcx",
        "    push rax",
        "    mov eax, dword ptr [rcx + 0x2e04]",
        "    call {shared}",
        "    pop rax",
        "    je ok",
        f"    jmp {LEARN_NEXT:#x}",
        "ok:",
        "    mov al, 1",
        "    ret",
    ])


def build_unlock_patch(exe: bytes, class_ids) -> bytes:
    ids = sorted({int(c) for c in class_ids})
    if not ids or is_patched(exe):
        return exe
    hooks = [(va, orig, _evility_src(zero, check, add), 0xE9) for va, orig, zero, check, add in EVI_SITES]
    hooks += [(SLOTS_VA, SLOTS_ORIG, _slots_src(), 0xE9), (OVL_VA, OVL_ORIG, _overload_src(), 0xE9),
              (LEARN_VA, LEARN_ORIG, _learn_src(), 0xE9)]
    return add_hook_section(exe, SECTION_NAME, hooks, _shared(ids))


def modded_classes(char_table, vanilla_table):
    """ids of the char.dat rows mods added or changed"""
    van = {r["id"]: bytes(r.raw) for r in vanilla_table.rows}
    return sorted(r["id"] for r in char_table.rows if van.get(r["id"]) != bytes(r.raw))


def _finalize(ctx):
    cpath = f"{DB_ARCHIVE}/char.dat"
    if cpath.lower() not in ctx.outputs:
        return
    chars = database.load_table("char.dat", ctx.get(cpath))
    ids = modded_classes(chars, database.load_table("char.dat", ctx.fs.read(cpath)))
    if ids:
        ctx.put(EXE_FILE, build_unlock_patch(ctx.get(EXE_FILE), ids))
        ctx.log("  no story locks (evilities, Overload, skills) for modded characters: " + ", ".join(map(str, ids)))


register_finalizer(_finalize)
