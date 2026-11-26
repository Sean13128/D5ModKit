"""Packed class-mastery hook (engine extension, section ".d5pm").

Steps 1 and 2 of the packed-mastery lane: the *mapper* plus the *award* path.

A configured (non-vanilla) family is mapped to **one staging slot** (52) that holds
that unit's own six counters, and the family's progress that is not currently staged
lives in a compact pool in the five spare slots 47..51 of the same unit record.
Vanilla families and every other id are answered by the game's own mapper, untouched.
If anything about the unit's spare area is unusable -- unknown/legacy bytes, a
malformed pool, a full pool, a counter that cannot be stored losslessly -- the hook
answers exactly what the vanilla mapper answered (normally -1, i.e. "this class has
no mastery") and writes nothing, which is how the game treats a class without
mastery.

The award path (step 2).  The native writer 0x14015F480 asks the mapper for the
target's slot and then awards on the counter array of that slot; its own rank limit is
`target % 10` (0x14015F51C reads r10, which the writer loaded with the target id at
0x14015F4AA), so for a rank-5 target an imported unit had all six stars rise at once
(STARS-FIX in mastery/STARS-FIX.md measured the same defect in the six-slot
extension).  At the writer's own mapper call (return address 0x14015F505) the wrapper
therefore replaces the caller's r10 with the **family base**: the writer's loop starts
at rank 0 and its own overflow path carries into rank 1, 2, ... one star at a time.
No other site's r10 is touched -- several callers keep their record pointer there.

Capacity is reserved before the writer's first side effect.  The writer's mapper call
is the only thing in the award path that can consume pool space (staging a family
packs the previously staged one back), and the hook performs that whole switch -- all
validation and the capacity arithmetic -- before it writes a single byte, then commits
in one uninterruptible batch.  An award can only grow counters toward their JobRank
thresholds, and a completed rank costs *fewer* bytes (its value is implied), so a
stage that fits before an award still fits after it.  A full pool therefore answers
-1 and the writer then does nothing at all: the game's own guard at 0x14015F508
(`cmp r8d, 0x34 / ja`) skips the counter loop, the eight bonus words, the unlock
call and the sub-class refresh.  Progress is never evicted and counters are never
truncated (DECISIONS: no eviction, no truncation).

Unlock / tier path.  The only global effect of a rank completion is
`data_progress_mark_character_seen` (0x1C62A0), which the writer calls with the
completed rank's class id.  Its first instruction is a range gate
(`(id - 0x7DA) < 0x123 || (id - 1000) < 0x137`), i.e. it accepts 1000..1310 and
2010..2300 only, so a packed family's ids return immediately with no read and no
write.  Nothing is hooked there and nothing needs to be: the hook proves the call is
a clean no-op and that the global flag bitmap is byte-identical after an award to a
packed family, while a vanilla completion still marks its class seen (see
mastery/P2E-REPORT.md).  Rank unlocks for packed families stay with the class lane's
own flags, exactly as for the six-slot extension; a packed award invents no new flag.

Install shape.  `.d5pm` and `.d5cm` redirect the same 16 mapper calls, so a build has
exactly one mapping source (`mode_for`): up to `masteryext.SLOT_COUNT` (six) families
use `.d5cm` and its leases; more families use `.d5pm`, which also carries `.d5cm`'s
sub-class gate, sub-class screen fetch and screen loop bound, so it fully replaces it.
Building the second one into the same exe is refused, loudly, by both builders.

Layout (per unit record; both are already existing vanilla storage):

    record + 0x350C  120 bytes   pool: C5 01 <staged family / 10 : u16> entries...
    record + 0x3584   24 bytes   slot 52: six u32 counters of the staged family

    entry = u24 header | 3 * n bytes of u24 counters
    header = (family / 10) | (k << 13) | (n << 16)
    k = completed leading ranks (their counter equals the JobRank threshold, so
        it is implied and costs no space)
    n = number of stored (partial) counters after the completed ones

The encoding is Cryswar's Overlord design (d5_custom_classes.c, The Unlicense)
and is the same format `d5lib.packedmastery` already specifies offline; unlike
that reference implementation nothing here evicts or truncates: a pool that
cannot take the entry leaves the record untouched.

The hook is entered by redirecting all 16 CALL sites of the mapper
(0x14021EBE0).  Which caller register holds the unit record is taken from
Overlord's site table and re-checked against the pinned build (decomp and
disassembly; see the module constants and mastery/P2D-REPORT.md).

ABI: the mapper's callers keep live values in volatile registers across the call
(0x140217230 keeps its class id in r8d, 0x1402172E0 in ebx, the Class tab in
ebp), so the wrapper saves rcx, rdx, r8, r9, r10 and r11 as well as the
callee-saved registers it uses, gives the original mapper 32 bytes of home space
with RSP%16 == 0 at the call, and returns the original's answer in eax.  It makes
no game call of its own: the JobRank thresholds it needs are read from
0xA03B38/0xA03B40 (the same table the game's own 0x1400744D0 searches).
"""
import json
import os
import struct
import time

from . import masteryext
from .exepatch import add_code_section, code_base
from .gamefs import EXE_FILE
from .masteryext import NATIVE_FAMILIES, MAPPER, MAPPER_CALLS, RANKS

SECTION_NAME = b".d5pm"
CLAIM = b"D5PM"
CLAIM_VERSION = 1

# Per-unit storage (existing vanilla fields; see d5lib.masteryext for the map).
POOL_OFFSET = 0x350C
POOL_SIZE = 120
STAGE_OFFSET = 0x3584
STAGE_SLOT = 52
POOL_MAGIC, POOL_VERSION = 0xC5, 0x01

# JobRank.dat rows (0x14 bytes, u32 class key at +0, u32 threshold at +4) -- the
# two globals the game's own row lookup 0x1400744D0 reads.
JOBRANK_ROWS, JOBRANK_COUNT = 0x140A03B38, 0x140A03B40
NO_THRESHOLD = 0xFFFFFFFF

# (mapper call-site return address, caller register holding the unit record,
#  extra dereference applied to that register).  Overlord's table; every entry
# was re-checked against the pinned build:
#   0x0B3CED  record = [r13 + 0x228]   (decomp FUN_1400b3c70: param_1 + 0x228)
#   0x15F505  rbx = rcx = param_1      (decomp FUN_14015f480 param_1 = record)
#   0x217246  r10 = rcx = param_1      (decomp FUN_140217230 param_1 = record)
#   0x21732B  rdi = param_1            (decomp FUN_1402172e0, `test rdi, rdi`)
#   0x2A3A62  r10                      (`mov r10, [r14 + 0x90]` before the call)
#   0x2A3B05  r9                       (`mov r9, [r14 + 0x90]` before the call)
#   0x2A3DDA..0x2A4149 rbp             (`test rbp, rbp`; decomp reads [rbp+0x30A4..])
#   0x2A43D1  rbp                      (decomp FUN_1402a4300 + `test rbp, rbp`)
#   0x47FFCD  record = [r15 + 0x1F1A8] (r15 = rcx = param_1; decomp reads it)
#   0x7CDA91  rbp                      (`[rbp + rdx*4 + 0x30B8]` after the call)
#   0x7CDADE  rbp                      (`[rbp + rcx*4 + 0x30A0]` after the call)
SITES = (
    (0x1400B3CED, "r13", 0x228),
    (0x14015F505, "rbx", 0),
    (0x140217246, "r10", 0),
    (0x14021732B, "rdi", 0),
    (0x1402A3A62, "r10", 0),
    (0x1402A3B05, "r9", 0),
    (0x1402A3DDA, "rbp", 0),
    (0x1402A3E89, "rbp", 0),
    (0x1402A3F39, "rbp", 0),
    (0x1402A3FE9, "rbp", 0),
    (0x1402A4099, "rbp", 0),
    (0x1402A4149, "rbp", 0),
    (0x1402A43D1, "rbp", 0),
    (0x14047FFCD, "r15", 0x1F1A8),
    (0x1407CDA91, "rbp", 0),
    (0x1407CDADE, "rbp", 0),
)
assert tuple(site for site, _, _ in SITES) == tuple(va + 5 for va in MAPPER_CALLS)

FRAME = 0x118                        # 280: 14 pushes leave RSP%16 == 8, this makes it 0 at the call
RET_OFFSET = 14 * 8 + FRAME          # the caller's return address, from the frame
R10_SAVE = FRAME + 0x48              # the pushed r10 (5th push: r15,r14,r13,r12,rdi,rsi,rbp,rbx,r11,r10)
X_POOL, X_STAGE, X_PREV, X_THR = 0x20, 0x98, 0xB0, 0xC8
X_FAM, X_FID, X_STG, X_END = 0xE0, 0xE4, 0xE8, 0xEC
X_OFF_F, X_OFF_P, X_LEN_F, X_LEN_P = 0xF0, 0xF4, 0xF8, 0xFC
X_NEED, X_PFAM, X_AWARD = 0x100, 0x104, 0x108

# The writer's own mapper call: the only site whose caller keeps the awarded class id
# in a volatile register across the call (0x14015F4AA `mov r10d, edx` .. 0x14015F51C
# `mov ecx, r10d`).  The reward loop's rank limit is r10 % 10, so the wrapper hands it
# the family base (STARS-FIX) -- one star per award, native overflow carries upward.
WRITER_RET = masteryext.WRITER_RET

MAX_FAMILIES = 120                   # configured families; the 120-byte pool is a per-unit limit, not this one

MODE_SIX, MODE_PACKED = "six", "packed"
MODES = (MODE_SIX, MODE_PACKED)

# the durable record of a packed install that superseded six-slot progress (next to the lease file)
MIGRATION_FILE = "mastery_migration.json"


def requested_mode(data):
    """the mapping source a mod's mastery block asks for ({"mastery": {"mode": "six"|"packed"}}), or None

    Optional: without it the source follows the family count (`mode_for`).  It exists so a profile can
    state its choice -- a packed live test with one family, or a build that insists on the six slots.
    """
    block = (data or {}).get("mastery")
    if not isinstance(block, dict):
        return None
    mode = block.get("mode")
    if mode in (None, ""):
        return None
    if mode not in MODES:
        raise ValueError(f"mastery mode {mode!r} is not one of {MODES}")
    return mode


def mode_for(families, requested=None):
    """which mapping source a build with these family bases uses: `.d5cm` or `.d5pm`.

    `.d5pm` and `.d5cm` redirect the same 16 mapper calls, so a build has exactly one
    of them; the split is the only thing the two differ on (six native slots + leases
    vs. the packed pool), and `.d5pm` carries `.d5cm`'s sub-class hooks so it is a
    drop-in replacement once the family count passes the six leases.

    `requested` is the source a mod declared; it may only pick the six slots when the
    build has six families or fewer, because that is all `.d5cm` can map.
    """
    fams = families_from(families)
    if not fams:
        raise ValueError("no packed mastery families: no mapping source to choose")
    by_count = MODE_SIX if len(fams) <= masteryext.SLOT_COUNT else MODE_PACKED
    if requested is not None and requested not in MODES:
        raise ValueError(f"mastery mode {requested!r} is not one of {MODES}")
    if requested == MODE_SIX and by_count == MODE_PACKED:
        raise ValueError(f"{len(fams)} mastery families: the six-slot source (.d5cm) holds at most "
                         f"{masteryext.SLOT_COUNT} families, so this build has to use packed mastery "
                         f"(.d5pm) -- drop the '\''mode': '\''six'\'' declaration or split the build")
    return requested or by_count


# ------------------------------------------------------------------------------------------ validation
def families_from(families):
    """sorted family bases, validated (custom, %10 == 0, not vanilla)"""
    if families is None:
        return []
    fams = sorted({int(f) for f in families})
    for fam in fams:
        if fam % 10:
            raise ValueError(f"packed mastery family {fam} is not a family base (id % 10 must be 0)")
        if not 1000 <= fam <= 32760 or 20000 <= fam < 22000:
            raise ValueError(f"packed mastery family {fam} is reserved or out of range")
        if fam in NATIVE_FAMILIES:
            raise ValueError(f"packed mastery family {fam} is a vanilla family: it already has mastery slots")
        if not 0 < fam // 10 < 8192:
            raise ValueError(f"packed mastery family {fam} cannot be packed in 13 bits")
    if len(fams) > MAX_FAMILIES:
        raise ValueError(f"at most {MAX_FAMILIES} packed mastery families")
    return fams


# ------------------------------------------------------------------------------------------ the code
def _sites_src():
    """compare the caller's return address with the 16 documented sites, load the unit record"""
    lines = [f"    mov r11, qword ptr [rsp + {RET_OFFSET:#x}]"]
    for i, (ret, _, _) in enumerate(SITES):
        lines += [f"    mov rax, {ret:#x}", "    cmp r11, rax", f"    je pm_s{i}"]
    lines += ["    jmp pm_out_none"]
    for i, (ret, reg, deref) in enumerate(SITES):
        lines += [f"pm_s{i}:", f"    mov r14, {reg}"]
        if deref:
            lines.append(f"    mov r14, qword ptr [r14 + {deref:#x}]")
        if ret == WRITER_RET:
            # the award path only: this caller may be handed the family base instead of the rank id
            lines.append(f"    mov dword ptr [rsp + {X_AWARD:#x}], 1")
        lines.append("    jmp pm_have_record")
    return "\n".join(lines)


def _mapper_src(fams, table=0):
    """the wrapper.  `table` is the absolute address of the family table (the build passes it twice)."""
    n = len(fams)
    lines = [
        # Save every register a caller may keep live across the mapper call: the
        # original mapper is a switch that only writes eax, and several callers
        # depend on that (see the module docstring).  RSP%16 == 8 at entry.
        "    push rcx", "    push rdx", "    push r8", "    push r9", "    push r10", "    push r11",
        "    push rbx", "    push rbp", "    push rsi", "    push rdi",
        "    push r12", "    push r13", "    push r14", "    push r15",
        f"    sub rsp, {FRAME:#x}",
        f"    mov dword ptr [rsp + {X_AWARD:#x}], 0",   # only the writer's site sets it
        "    mov esi, ecx",                      # the class id; rbx is the record at 0x15F505, so never touched
        "    mov r12, %d" % table,              # family table
        f"    mov r8d, {n}",
        "pm_fam:",
        "    test r8d, r8d",
        "    jz pm_not_ours",
        "    mov edx, dword ptr [r12]",
        "    mov eax, esi",
        "    sub eax, edx",
        "    cmp eax, 9",
        "    jbe pm_fam_ok",
        "    add r12, 4",
        "    dec r8d",
        "    jmp pm_fam",
        # not a configured family: the game's own answer, unchanged
        "pm_not_ours:",
        "    mov ecx, esi",
        f"    call {MAPPER:#x}",
        "    jmp pm_out",
        "pm_fam_ok:",
        f"    mov dword ptr [rsp + {X_FAM:#x}], edx",
        "    mov eax, edx",                     # fid = family / 10
        "    mov ecx, 0xCCCCCCCD",
        "    mul ecx",
        "    shr edx, 3",
        f"    mov dword ptr [rsp + {X_FID:#x}], edx",
        # The caller's record register is read *before* the mapper call: the callee's
        # only documented effect is eax, but nothing here depends on it leaving the
        # caller's volatile registers alone.
        _sites_src(),
        "pm_have_record:",
        "    lea rbx, [rsp + %d]" % X_POOL,       # scratch pool base (rbx/rbp are free once the site was read)
        "    lea rbp, [rsp + %d]" % X_STAGE,      # scratch stage base
        "    mov ecx, esi",
        f"    call {MAPPER:#x}",
        "    cmp eax, -1",
        "    jne pm_out",                       # the game knows this id after all: its answer wins
        "    test r14, r14",
        "    jz pm_out_none",
        f"    lea r15, [r14 + {POOL_OFFSET:#x}]",
        f"    cmp byte ptr [r15], {POOL_MAGIC:#x}",
        "    jne pm_blank",
        f"    cmp byte ptr [r15 + 1], {POOL_VERSION:#x}",
        "    jne pm_out_none",                  # unknown/legacy data: fail closed
    ]
    for k in range(0, POOL_SIZE, 8):         # scratch pool = the record's pool
        lines += [f"    mov rax, qword ptr [r15 + {k}]", f"    mov qword ptr [rsp + {X_POOL + k:#x}], rax"]
    lines += [
        "    movzx eax, word ptr [r15 + 2]",
        f"    mov dword ptr [rsp + {X_STG:#x}], eax",
        "    jmp pm_scan",
        "pm_blank:",
        # a spare area that is still all zero is this feature's to initialise
        "    mov r11, r15",
        f"    mov ecx, {(POOL_SIZE + 24) // 8}",
        "pm_blank_loop:",
        "    cmp qword ptr [r11], 0",
        "    jne pm_out_none",
        "    add r11, 8",
        "    dec ecx",
        "    jnz pm_blank_loop",
    ]
    for k in range(0, POOL_SIZE + 24, 8):
        lines.append(f"    mov qword ptr [rsp + {X_POOL + k:#x}], 0")
    lines += [
        f"    mov byte ptr [rsp + {X_POOL:#x}], {POOL_MAGIC:#x}",
        f"    mov byte ptr [rsp + {X_POOL + 1:#x}], {POOL_VERSION:#x}",
        f"    mov dword ptr [rsp + {X_STG:#x}], 0",
        "pm_scan:",
        f"    mov dword ptr [rsp + {X_END:#x}], 4",
        f"    mov dword ptr [rsp + {X_OFF_F:#x}], 0",
        f"    mov dword ptr [rsp + {X_OFF_P:#x}], 0",
        f"    mov dword ptr [rsp + {X_LEN_F:#x}], 0",
        f"    mov dword ptr [rsp + {X_LEN_P:#x}], 0",
        "    mov r11d, 4",
        "pm_scan_loop:",
        "    cmp r11d, 117",                   # pos + 3 <= POOL_SIZE
        "    ja pm_scan_tail",
        "    mov eax, dword ptr [rbx + r11]",
        "    and eax, 0xFFFFFF",
        "    jz pm_scan_tail",
        "    test eax, 0xF80000",              # bits 19..23 of the header are reserved
        "    jnz pm_out_none",
        "    mov edx, eax",
        "    and edx, 0x1FFF",
        "    jz pm_out_none",
        "    mov r8d, eax",
        "    shr r8d, 13",
        "    and r8d, 7",
        "    mov r9d, eax",
        "    shr r9d, 16",
        "    and r9d, 7",
        f"    cmp r8d, {RANKS}",
        "    ja pm_out_none",
        f"    mov r10d, {RANKS}",
        "    sub r10d, r8d",
        "    cmp r9d, r10d",
        "    ja pm_out_none",
        "    lea r10d, [r9 + r9*2 + 3]",       # entry length
        "    lea ecx, [r11 + r10]",
        f"    cmp ecx, {POOL_SIZE}",
        "    ja pm_out_none",
        f"    cmp edx, dword ptr [rsp + {X_FID:#x}]",
        "    jne pm_scan_notF",
        f"    cmp dword ptr [rsp + {X_OFF_F:#x}], 0",
        "    jne pm_out_none",                 # duplicate entry for one family: not ours
        f"    mov dword ptr [rsp + {X_OFF_F:#x}], r11d",
        f"    mov dword ptr [rsp + {X_LEN_F:#x}], r10d",
        "    jmp pm_scan_next",
        "pm_scan_notF:",
        f"    cmp edx, dword ptr [rsp + {X_STG:#x}]",
        "    jne pm_scan_next",
        f"    cmp dword ptr [rsp + {X_OFF_P:#x}], 0",
        "    jne pm_out_none",
        f"    mov dword ptr [rsp + {X_OFF_P:#x}], r11d",
        f"    mov dword ptr [rsp + {X_LEN_P:#x}], r10d",
        "pm_scan_next:",
        "    add r11d, r10d",
        "    jmp pm_scan_loop",
        "pm_scan_tail:",
        f"    mov dword ptr [rsp + {X_END:#x}], r11d",
        "pm_tail_zero:",
        f"    cmp r11d, {POOL_SIZE}",
        "    jae pm_scan_done",
        "    cmp byte ptr [rbx + r11], 0",
        "    jne pm_out_none",                 # garbage after the entries
        "    inc r11d",
        "    jmp pm_tail_zero",
        "pm_scan_done:",
        f"    mov eax, dword ptr [rsp + {X_STG:#x}]",
        f"    cmp eax, dword ptr [rsp + {X_FID:#x}]",
        "    je pm_ret_stage",                 # already staged: answer 52, write nothing
        f"    mov dword ptr [rsp + {X_NEED:#x}], 0",
        "    test eax, eax",
        "    jz pm_prev_done",
        "    imul eax, eax, 10",               # the staged family is packed back first
        f"    mov dword ptr [rsp + {X_PFAM:#x}], eax",
        "    mov r11, %d" % table,
        f"    mov ecx, {n}",
        "pm_prev_find:",
        "    test ecx, ecx",
        "    jz pm_out_none",                  # a staged family this build does not know
        "    cmp dword ptr [r11], eax",
        "    je pm_prev_found",
        "    add r11, 4",
        "    dec ecx",
        "    jmp pm_prev_find",
        "pm_prev_found:",
        "    mov edx, eax",
        f"    lea rsi, [rsp + {X_THR:#x}]",
        "    call pm_thr6",
        "    test eax, eax",
        "    jnz pm_out_none",
        f"    mov eax, dword ptr [rsp + {X_PFAM:#x}]",
        "    mov ecx, 0xCCCCCCCD",
        "    mul ecx",
        "    shr edx, 3",
        "    mov ecx, edx",                    # header family id of the packed-back family
        f"    lea rsi, [rsp + {X_PREV:#x}]",
        f"    lea rdi, [r14 + {STAGE_OFFSET:#x}]",
        f"    lea rdx, [rsp + {X_THR:#x}]",
        "    call pm_encode",
        "    test eax, eax",
        "    jnz pm_out_none",
        f"    mov dword ptr [rsp + {X_NEED:#x}], edx",
        "pm_prev_done:",
        # capacity, before anything is written
        f"    mov eax, dword ptr [rsp + {X_END:#x}]",
        f"    sub eax, dword ptr [rsp + {X_LEN_F:#x}]",
        f"    sub eax, dword ptr [rsp + {X_LEN_P:#x}]",
        f"    add eax, dword ptr [rsp + {X_NEED:#x}]",
        f"    cmp eax, {POOL_SIZE}",
        "    ja pm_out_none",                  # full: fail closed, nothing written
        # rebuild the pool without the entry of the family we are staging (and
        # without the staged family's own entry), then append the packed-back entry
        "    mov r11d, 4",
        "    mov r10d, 4",
        "pm_compact:",
        f"    cmp r11d, dword ptr [rsp + {X_END:#x}]",
        "    jae pm_compact_done",
        f"    cmp r11d, dword ptr [rsp + {X_OFF_F:#x}]",
        "    je pm_skip_F",
        f"    cmp r11d, dword ptr [rsp + {X_OFF_P:#x}]",
        "    je pm_skip_P",
        "    mov eax, dword ptr [rbx + r11]",
        "    shr eax, 16",
        "    and eax, 7",
        "    lea ecx, [rax + rax*2 + 3]",
        "pm_copy:",
        "    mov al, byte ptr [rbx + r11]",
        "    mov byte ptr [rbx + r10], al",
        "    inc r11d",
        "    inc r10d",
        "    dec ecx",
        "    jnz pm_copy",
        "    jmp pm_compact",
        "pm_skip_F:",
        f"    add r11d, dword ptr [rsp + {X_LEN_F:#x}]",
        "    jmp pm_compact",
        "pm_skip_P:",
        f"    add r11d, dword ptr [rsp + {X_LEN_P:#x}]",
        "    jmp pm_compact",
        "pm_compact_done:",
        f"    mov eax, dword ptr [rsp + {X_NEED:#x}]",
        "    test eax, eax",
        "    jz pm_zero_tail",
        "    xor ecx, ecx",
        "pm_append:",
        "    cmp ecx, eax",
        "    jae pm_zero_tail",
        f"    mov dl, byte ptr [rsp + rcx + {X_PREV:#x}]",
        "    mov byte ptr [rbx + r10], dl",
        "    inc ecx",
        "    inc r10d",
        "    jmp pm_append",
        "pm_zero_tail:",
        f"    cmp r10d, {POOL_SIZE}",
        "    jae pm_load_F",
        "    mov byte ptr [rbx + r10], 0",
        "    inc r10d",
        "    jmp pm_zero_tail",
        # slot 52 becomes this family's counters
        "pm_load_F:",
        f"    mov eax, dword ptr [rsp + {X_OFF_F:#x}]",
        "    test eax, eax",
        "    jz pm_no_F",
        f"    mov edx, dword ptr [rsp + {X_FAM:#x}]",
        f"    lea rsi, [rsp + {X_THR:#x}]",
        "    call pm_thr6",
        "    test eax, eax",
        "    jnz pm_out_none",
    ]
    for k in range(0, 24, 8):
        lines.append(f"    mov qword ptr [rsp + {X_STAGE + k:#x}], 0")
    lines += [
        f"    mov r11d, dword ptr [rsp + {X_OFF_F:#x}]",   # read the game's own pool: the scratch copy has
        "    mov eax, dword ptr [r15 + r11]",           # already had this entry compacted out of it
        "    and eax, 0xFFFFFF",
        "    mov r8d, eax",
        "    shr r8d, 13",
        "    and r8d, 7",
        "    mov r9d, eax",
        "    shr r9d, 16",
        "    and r9d, 7",
        "    xor ecx, ecx",
        "pm_kf:",
        "    cmp ecx, r8d",
        "    jae pm_cf_start",
        "    mov eax, dword ptr [rsp + rcx*4 + %d]" % X_THR,
        "    mov dword ptr [rbp + rcx*4], eax",
        "    inc ecx",
        "    jmp pm_kf",
        "pm_cf_start:",
        "    xor ecx, ecx",
        "pm_cf:",
        "    cmp ecx, r9d",
        "    jae pm_commit",
        "    lea edx, [rcx + rcx*2 + 3]",
        "    add edx, r11d",
        "    movzx eax, byte ptr [r15 + rdx]",
        "    movzx r10d, byte ptr [r15 + rdx + 1]",
        "    shl r10d, 8",
        "    or eax, r10d",
        "    movzx r10d, byte ptr [r15 + rdx + 2]",
        "    shl r10d, 16",
        "    or eax, r10d",
        "    lea r10d, [r8 + rcx]",
        "    cmp eax, dword ptr [rsp + r10*4 + %d]" % X_THR,
        "    ja pm_out_none",                  # a stored counter above its threshold is not ours
        "    mov dword ptr [rbp + r10*4], eax",
        "    inc ecx",
        "    jmp pm_cf",
        "pm_no_F:",
    ]
    for k in range(0, 24, 8):
        lines.append(f"    mov qword ptr [rsp + {X_STAGE + k:#x}], 0")
    lines += [
        "pm_commit:",
        f"    mov eax, dword ptr [rsp + {X_FID:#x}]",
        "    mov word ptr [rbx + 2], ax",
    ]
    for k in range(0, POOL_SIZE, 8):         # the pool first, then the staged counters
        lines += [f"    mov rax, qword ptr [rbx + {k}]", f"    mov qword ptr [r15 + {k}], rax"]
    for k in range(0, 24, 8):
        lines += [f"    mov rax, qword ptr [rbp + {k}]",
                  f"    mov qword ptr [r14 + {STAGE_OFFSET + k:#x}], rax"]
    lines += [
        "pm_ret_stage:",
        # the award path: hand the writer the family base, so its own rank loop starts
        # at star 1 and its native overflow carries one star at a time (STARS-FIX)
        f"    cmp dword ptr [rsp + {X_AWARD:#x}], 0",
        "    je pm_award_done",
        f"    mov eax, dword ptr [rsp + {X_FAM:#x}]",
        f"    mov dword ptr [rsp + {R10_SAVE:#x}], eax",
        "pm_award_done:",
        f"    mov eax, {STAGE_SLOT}",
        "pm_out:",
        f"    add rsp, {FRAME:#x}",
        "    pop r15", "    pop r14", "    pop r13", "    pop r12",
        "    pop rdi", "    pop rsi", "    pop rbp", "    pop rbx",
        "    pop r11", "    pop r10", "    pop r9", "    pop r8",
        "    pop rdx", "    pop rcx",
        "    ret",
        "pm_out_none:",
        "    mov eax, -1",
        "    jmp pm_out",
    ]
    return "\n".join(lines)


def _thr_src():
    """eax = JobRank threshold of class id edx, or NO_THRESHOLD; the game's own binary search over its rows"""
    return "\n".join([
        "pm_thr:",
        f"    mov r11, {JOBRANK_ROWS:#x}",
        "    mov r11, qword ptr [r11]",
        "    test r11, r11",
        "    jz pm_thr_none",
        f"    mov r10, {JOBRANK_COUNT:#x}",
        "    mov r10d, dword ptr [r10]",
        "    sub r10d, 1",
        "    js pm_thr_none",
        "    xor ecx, ecx",
        "pm_thr_loop:",
        "    cmp ecx, r10d",
        "    jg pm_thr_none",
        "    lea eax, [rcx + r10]",
        "    shr eax, 1",
        "    lea r8, [rax + rax*4]",
        "    shl r8, 2",                        # 0x14-byte rows
        "    cmp dword ptr [r11 + r8], edx",
        "    je pm_thr_found",
        "    jb pm_thr_low",
        "    lea r10d, [rax - 1]",
        "    jmp pm_thr_loop",
        "pm_thr_low:",
        "    lea ecx, [rax + 1]",
        "    jmp pm_thr_loop",
        "pm_thr_found:",
        "    mov eax, dword ptr [r11 + r8 + 4]",
        "    ret",
        "pm_thr_none:",
        f"    mov eax, {NO_THRESHOLD:#x}",
        "    ret",
    ])


def _thr6_src():
    """edx = family, rsi = destination of six u32; eax = 0 ok / 1 when any rank row is missing.

    Its own state lives in its frame (32 bytes of home space for pm_thr, then the
    family and the rank): pm_thr clobbers every volatile register, by design.
    """
    return "\n".join([
        "pm_thr6:",
        "    sub rsp, 0x28",                    # 32 home + family + rank; entry RSP%16 == 8 -> 0 for the call
        "    mov dword ptr [rsp + 0x20], edx",
        "    mov dword ptr [rsp + 0x24], 0",
        "pm_thr6_loop:",
        "    mov edx, dword ptr [rsp + 0x20]",
        "    add edx, dword ptr [rsp + 0x24]",
        "    call pm_thr",
        "    cmp eax, -1",
        "    je pm_thr6_fail",
        "    mov ecx, dword ptr [rsp + 0x24]",
        "    mov dword ptr [rsi + rcx*4], eax",
        "    inc dword ptr [rsp + 0x24]",
        f"    cmp dword ptr [rsp + 0x24], {RANKS}",
        "    jb pm_thr6_loop",
        "    xor eax, eax",
        "    add rsp, 0x28",
        "    ret",
        "pm_thr6_fail:",
        "    mov eax, 1",
        "    add rsp, 0x28",
        "    ret",
    ])


def _encode_src():
    """ecx = family id, rsi = destination, rdi = six u32 counters, rdx = six u32 thresholds.

    eax = 0 and edx = the entry length (0 for "no data"), or eax = 1 when the counters
    cannot be stored without loss (above a threshold, or a partial counter above 24 bits).
    """
    return "\n".join([
        "pm_encode:",
        "    xor r8d, r8d",                     # k: completed leading ranks
        "pm_enc_k:",
        f"    cmp r8d, {RANKS}",
        "    jae pm_enc_k_done",
        "    mov eax, dword ptr [rdi + r8*4]",
        "    cmp eax, dword ptr [rdx + r8*4]",
        "    jne pm_enc_k_done",
        "    inc r8d",
        "    jmp pm_enc_k",
        "pm_enc_k_done:",
        "    xor r9d, r9d",                     # n: stored counters after k
        f"    mov r10d, {RANKS - 1}",
        "pm_enc_n:",
        "    cmp r10d, r8d",
        "    jl pm_enc_n_done",
        "    cmp dword ptr [rdi + r10*4], 0",
        "    jz pm_enc_n_next",
        "    mov r9d, r10d",
        "    sub r9d, r8d",
        "    inc r9d",
        "    jmp pm_enc_n_done",
        "pm_enc_n_next:",
        "    dec r10d",
        "    jmp pm_enc_n",
        "pm_enc_n_done:",
        "    mov r10d, r8d",                    # nothing above a threshold, nothing lossy
        "pm_enc_check:",
        f"    cmp r10d, {RANKS}",
        "    jae pm_enc_emit",
        "    mov eax, dword ptr [rdi + r10*4]",
        "    cmp eax, dword ptr [rdx + r10*4]",
        "    ja pm_enc_refuse",
        "    inc r10d",
        "    jmp pm_enc_check",
        "pm_enc_emit:",
        "    mov eax, r8d",
        "    or eax, r9d",
        "    jz pm_enc_empty",
        "    lea r11d, [r8 + r9]",              # stored window [k, k+n)
        "    mov r10d, r8d",
        "pm_enc_stored:",
        "    cmp r10d, r11d",
        "    jae pm_enc_write",
        "    mov eax, dword ptr [rdi + r10*4]",
        "    cmp eax, 0xFFFFFF",
        "    ja pm_enc_refuse",
        "    inc r10d",
        "    jmp pm_enc_stored",
        "pm_enc_write:",
        "    mov eax, ecx",                     # header: family id | k | n
        "    mov r10d, r8d",
        "    shl r10d, 13",
        "    or eax, r10d",
        "    mov r10d, r9d",
        "    shl r10d, 16",
        "    or eax, r10d",
        "    mov byte ptr [rsi], al",
        "    shr eax, 8",
        "    mov byte ptr [rsi + 1], al",
        "    shr eax, 8",
        "    mov byte ptr [rsi + 2], al",
        "    mov r11d, r8d",                     # the first stored rank is k
        "    xor r10d, r10d",
        "pm_enc_bytes:",
        "    cmp r10d, r9d",
        "    jae pm_enc_done",
        "    mov eax, dword ptr [rdi + r11*4]",
        "    lea ecx, [r10 + r10*2 + 3]",
        "    mov byte ptr [rsi + rcx], al",
        "    shr eax, 8",
        "    mov byte ptr [rsi + rcx + 1], al",
        "    shr eax, 8",
        "    mov byte ptr [rsi + rcx + 2], al",
        "    inc r10d",
        "    inc r11d",
        "    jmp pm_enc_bytes",
        "pm_enc_done:",
        "    lea edx, [r9 + r9*2 + 3]",
        "    xor eax, eax",
        "    ret",
        "pm_enc_empty:",
        "    xor edx, edx",
        "    xor eax, eax",
        "    ret",
        "pm_enc_refuse:",
        "    mov eax, 1",
        "    ret",
    ])


def _asm_source(fams, table=0):
    """the wrapper and the routines it calls, as one assembly source: the wrapper names
    routines that come after it, and one source lets the assembler resolve them."""
    return chr(10).join((_mapper_src(fams, table), _encode_src(), _thr_src(), _thr6_src()))


def _sources(fams, table=0):
    """[(tag, source)]: the wrapper blob, then .d5cm's two sub-class stubs, so a packed
    build replaces the six-slot extension completely.  Each is self-contained."""
    return [("mapper", _asm_source(fams, table)),
            ("subclass", masteryext._subclass_src(fams)), ("fetch", masteryext._fetch_src(fams))]


def _claim_header(offset, count):
    """the 16-byte claim: "D5PM", the family table's offset and length, and the format version.  The table is
    written after the code, so nothing but instructions may sit in front of the first routine (base + 16)."""
    return CLAIM + bytes(16 - len(CLAIM) - 12) + struct.pack("<III", int(offset), int(count), CLAIM_VERSION)


def _assemble(src, base):
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_64).asm(src, base)
    return bytes(enc)


def _layout(fams, base, table):
    """assemble the whole section body (claim + routines + family table) for `base`; the wrapper is at base + 16"""
    code = bytearray(_claim_header(0, len(fams)))
    starts = {}
    for tag, src in _sources(fams, table):
        code += b"\xcc" * (-len(code) % 16)      # one routine per 16-byte boundary, so unwind records never overlap
        starts[tag] = base + len(code)
        code += _assemble(src, base + len(code))
    code += b"\xcc" * (-len(code) % 4)
    code[0:16] = _claim_header(len(code), len(fams))
    code += struct.pack("<%dI" % len(fams), *[int(f) for f in fams])
    return bytes(code), starts


def _offsets(exe):
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    return lambda va: pe.get_offset_from_rva(va - IMAGE_BASE)


def _check_sites(exe, at):
    """refuse a different exe build, another hook that already redirected these sites, or a `.d5cm` build"""
    if masteryext.section_info(exe):
        raise ValueError('packed mastery (.d5pm) and the six-slot mastery extension (.d5cm) map the same 16 '
                         'class-mastery calls: this exe already carries ".d5cm".  A build has one mapping '
                         'source -- remove the six-slot block (up to six families) or keep it and drop the '
                         'packed one -- never both')
    for va in MAPPER_CALLS:
        orig = exe[at(va):at(va) + 5]
        if orig[:1] != b"\xe8" or va + 5 + struct.unpack("<i", orig[1:])[0] != MAPPER:
            raise ValueError(f"packed mastery: {va:#x} is not a call of {MAPPER:#x} "
                             f"(different exe build, or that site is already hooked)")
    for va, orig in ((masteryext.SUBCLASS_SITE, masteryext.SUBCLASS_ORIG),
                     (masteryext.FETCH_SITE, masteryext.FETCH_ORIG),
                     (masteryext.BOUND_SITE, masteryext.BOUND_ORIG)):
        if exe[at(va):at(va) + len(orig)] != orig:
            raise ValueError(f"packed mastery: {va:#x} does not hold the expected instruction "
                             f"(different exe build, or that site is already hooked)")


def build_patch(exe, families):
    """the exe with section .d5pm: the mapper wrapper at all 16 call sites, plus the
    sub-class gate, sub-class screen fetch and screen bound the six-slot extension owns"""
    fams = families_from(families)
    if not fams:
        raise ValueError("no packed mastery families: nothing to extend")
    at = _offsets(exe)
    _check_sites(exe, at)
    base = code_base(exe, SECTION_NAME)
    # two passes: the wrapper names the table's address, which depends on the routines' own size
    first, _ = _layout(fams, base, base)
    table = base + len(first) - 4 * len(fams)
    second, starts = _layout(fams, base, table)
    if len(second) != len(first):
        raise ValueError("packed mastery: the section layout is not stable under its own table address")
    patches = [(va, exe[at(va):at(va) + 5], starts["mapper"], 0xE8) for va in MAPPER_CALLS]
    patches.append((masteryext.SUBCLASS_SITE, masteryext.SUBCLASS_ORIG, starts["subclass"], 0xE9))
    patches.append((masteryext.FETCH_SITE, masteryext.FETCH_ORIG, starts["fetch"], 0xE8))
    out = add_code_section(exe, SECTION_NAME, second, patches)
    # the sub-class screen's loop bound (imm8 of `cmp r13, 0x2f`): our families follow the 47 vanilla ones
    off = _offsets(out)(masteryext.BOUND_SITE)
    if out[off:off + 3] != masteryext.BOUND_ORIG[:3]:
        raise ValueError("packed mastery: the sub-class loop bound changed under the section append")
    if 0x2F + len(fams) > 0xFF:
        raise ValueError(f"{len(fams)} packed mastery families: the sub-class screen's loop bound is an imm8")
    from . import exemap
    exemap.claim(masteryext.BOUND_SITE + 3, 1, "sub-class loop bound")      # written in place below
    out = bytearray(out)
    out[off + 3] = 0x2F + len(fams)
    return bytes(out)


def section_info(exe):
    """where the installed section is, or None -- the claim bytes are searched, not the section name, because a
    section appended by add_code_section grows into the previous kit section when the exe has no room for another"""
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    for s in pe.sections:
        data = pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)
        at = data.find(CLAIM)
        if at >= 0:
            return {"base": IMAGE_BASE + s.VirtualAddress + at, "code": IMAGE_BASE + s.VirtualAddress + at + 16,
                    "size": s.Misc_VirtualSize - at, "data": data[at:],
                    "section": s.Name.rstrip(b"\0").decode("ascii", "replace")}
    return None


def read_families(exe):
    """the family table recorded in the installed .d5pm section, or [] when there is none"""
    info = section_info(exe)
    if not info:
        return []
    data = info["data"]
    try:
        offset, count, version = struct.unpack_from("<III", data, 4)
    except struct.error:
        return []
    if version != CLAIM_VERSION or not count:
        return []
    if offset + 4 * count > len(data):
        return []
    return list(struct.unpack_from("<%dI" % count, data, offset))


# ------------------------------------------------------------------------------------------ install
def install(ctx, families, log=None):
    """patch this build's exe with `.d5pm` for `families` (the packed side of the mastery finalizer).

    A packed build does not use the six-slot leases, so this never assigns, retires or rewrites one: the
    mapping a six-slot build left behind stays exactly as it is, and reinstalling that build finds its
    mapping again unchanged.  Existing leases *are* read, because the pool reuses slots 47..52 for every
    unit, so counters a save already holds for them stop being read -- fail-safe (the hook answers the
    vanilla "no mastery" and writes nothing) but never silent: the operator has to acknowledge it once
    (`tools/accept_packed_mastery.py`) and the decision is written to a receipt beside the lease file.
    Migration of a save is a separate, explicit copied-save operation (`d5lib/masterymigration`).
    """
    fams = families_from(families)
    if not fams:
        raise ValueError("no packed mastery families: nothing to extend")
    log = log or ctx.log
    path = masteryext.lease_path(ctx)
    leases = masteryext.SlotLeases.load(path, log)
    held = acknowledged_leases(leases, path)
    exe = build_patch(ctx.get(EXE_FILE), fams)          # refuses a `.d5cm` exe by name, before any site
    ctx.put(EXE_FILE, exe)
    log(f"  class mastery: packed (.d5pm) for {len(fams)} families ({', '.join(str(f) for f in fams)}); "
        f"no six-slot lease is assigned, retired or moved")
    log("  class mastery: lease file " + (path if path else "none (this build has no game folder)"))
    if held:
        write_migration_receipt(path, fams, held, log)
    return exe


def acknowledged_leases(leases, path=None):
    """{family: slot} of the six-slot leases an operator accepted to give up, or refuse

    Slots 47..52 hold the packed pool and the staging slot, so a counter array a save wrote for the
    six-slot mapping is not read by a packed build.  Nothing is lost on disk (the unit record is left
    alone), but the class progress stops counting, so the install stops until that is acknowledged.
    """
    held = dict(leases.retired)
    held.update(leases.slots)                            # a live lease wins over a retired one
    if not held:
        return {}
    acknowledged = {int(f) for f in (leases.packed_ack or {}).get("families") or ()}
    missing = sorted(fam for fam in held if fam not in acknowledged)
    if missing:
        names = ", ".join(f"{fam} (slot {slot}{', retired' if fam in leases.retired and fam not in leases.slots else ''})"
                          for fam, slot in sorted(held.items(), key=lambda kv: kv[1]))
        raise ValueError(
            f"packed mastery (.d5pm) reuses the six-slot mastery storage (slots {masteryext.SLOT_FIRST}.."
            f"{masteryext.SLOT_FIRST + masteryext.SLOT_COUNT - 1}) on every unit, so the class progress a save "
            f"already holds for {names} would no longer be read.  A packed install does not migrate a six-slot "
            f"save by itself.  Either acknowledge it (python3 tools/accept_packed_mastery.py) and carry the "
            f"progress over on a *copy* of the save (d5lib/masterymigration.py), or install a build with "
            f"{masteryext.SLOT_COUNT} families or fewer, which keeps .d5cm and its leases "
            f"(unacknowledged: {', '.join(str(f) for f in missing)}; leases: {path or 'in memory'})")
    return held


def write_migration_receipt(path, families, held, log=print):
    """durable record of a packed install that superseded six-slot progress (the install log scrolls away)"""
    if not path:
        return None
    record = {"version": CLAIM_VERSION, "packed": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "section": SECTION_NAME.decode("ascii"), "families": list(families),
              "six_slot_leases": {str(fam): slot for fam, slot in sorted(held.items())},
              "note": ("packed mastery reuses slots 47..52: the six-slot counters a save holds for these "
                       "families are no longer read.  Nothing was migrated by the install -- copy the save and "
                       "use d5lib/masterymigration.py if the progress has to carry over.")}
    out = os.path.join(os.path.dirname(path) or ".", MIGRATION_FILE)
    try:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)
    except OSError as e:
        log(f"  class mastery: the migration receipt could not be written ({e})")
        return None
    log(f"  class mastery: MIGRATION RECEIPT {out}: six-slot progress for "
        f"{', '.join(str(f) for f in sorted(held))} is no longer read by this packed build "
        f"(nothing was migrated; see the note in the file)")
    return out
