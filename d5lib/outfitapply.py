"""OUTFITOWN2: an outfit's own values (outfits.json `own_fields`) reach the unit as soon as it switches outfit.

The outfit switch (exepatch.build_outfit_patch, `outfit_pick`) writes the new class id to unit+0x2E04 and lets the
game set the row index (+0x2E0A).  The game keeps its own copies of a class row's stats, aptitudes, weapon mastery,
movement, resistances and innate evilities in the unit record (filled at creation 0x14021B510 / rank-up 0x14021EEE0 /
reincarnation 0x140219C40, Steam addresses), so without more the outfit's own values would only arrive at the next
reincarnation.  `outfit_apply` closes that: for the field groups the old or the new outfit keeps its own values for,
the difference between the new and the old char.dat row is added to the unit's copies, then unit_recalc rebuilds the
finals.  Switching back applies the opposite difference, so the record comes back as it was.

Addresses below are the kit's known build (exepatch._asm translates them to the build being patched).  The routine
is emitted only when some outfit has own values for one of these groups, so every other outfit pack builds the same
exe as before.  Weapon resistances need nothing: the game reads them from the current row (0x14015C490, Steam).
"""

CHAR_TABLE = 0x140A31880   # pointer to the char.dat rows (0x38C each; unit+0x2E0A = row index); Steam 0x140A03880
UNIT_RECALC = 0x14021B430  # unit_recalc(unit, 0, 0); Steam 0x14021BFB0
OWN_BITS = {"evilities": 1, "base_stats": 2, "aptitudes": 4, "weapon_mastery": 8, "movement": 16, "resistances": 32}
MARKER = b"D5OAPPLY"       # 8 bytes in the outfit section; outfit_apply starts at the next 16-byte boundary

# unit fields the routine writes (for tests and docs): (unit offset, size, count, stride)
WRITES = {
    "base_stats": [(0x2DA0, 1, 8, 1), (0x2D18, 8, 8, 8)],
    "aptitudes": [(0x3078, 2, 8, 2)],
    "weapon_mastery": [(0x2DAE, 1, 9, 8)],
    "movement": [(0x2E1A, 1, 1, 1), (0x2E1C, 1, 1, 1), (0x2E1E, 1, 1, 1), (0x2E20, 1, 1, 1), (0x2E22, 1, 1, 1)],
    "resistances": [(0x2E12, 1, 4, 1)],
    "evilities": [(0x2EEE, 2, 5, 2), (0x2EF8, 2, 1, 2)],
}
# (row offset, unit offset) of the movement bytes, as unit_construct copies them
MOVEMENT = ((0xE2, 0x2E1C), (0x37C, 0x2E1A), (0x37E, 0x2E1E), (0x37D, 0x2E20), (0x380, 0x2E22))


def masks(own_fields):
    """{outfit class id: OWN_BITS of the groups it keeps its own values for} from {slot: {group: {field: v}}}"""
    out = {}
    for slot, groups in (own_fields or {}).items():
        m = 0
        for g in groups or {}:
            m |= OWN_BITS.get(g, 0)
        if m:
            out[int(slot)] = m
    return out


def apply_va(exe: bytes):
    """address of outfit_apply in a patched exe (None: the outfit section has none)"""
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    for s in pe.sections:
        if not s.Name.rstrip(b"\0").startswith(b".d5"):
            continue
        data = s.get_data()
        i = data.find(MARKER)
        if i >= 0:
            off = (i + len(MARKER) + 15) & ~15
            return pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress + off
    return None


def src(class_masks):
    """-> (code keeping the old class / row in outfit_pick, the call after the class change, the routine).

    outfit_apply(rcx unit, edx old class id, r8d old char row index), called after the unit took its new class and
    row.  Groups (bit set for the old or the new class): the new row minus the old row is added to

      base_stats      growth bytes +0x2DA0+k (u8, clamp 1..255: rank-up's own rule) and base stats +0x2D18+8k
                      (i64, + delta * (level+1) / 2 = unit_init_stats' share of a row base at its mean roll 50%,
                      at least 1)
      aptitudes       +0x3078+2k (u16, row +0x350+k u8; clamp 0..65535)
      weapon_mastery  base aptitude byte +0x2DAE+8k, 9 weapons (row +0x358+2k), clamp 0..127
      movement        MOVEMENT bytes, clamp 0..255
      resistances     +0x2E12..+0x2E15 (row +0x36C.., i8, clamp -128..127)
      evilities       innate slots +0x2EEE (u16 x5, count +0x2EF8, 9999 = empty, kept packed): the evilities only
                      the old row has give their slot to those only the new row has, pair by pair in row order;
                      one the unit doesn't hold (story-gated) passes nothing on; a surplus old one is removed, a
                      surplus new one goes in after its predecessor in the new row while a slot is free (+0x2EFA).
                      Evilities both rows have are left alone.

    Nothing changed -> nothing written and no recalc; else unit_recalc(unit, 0, 0) (it rebuilds the evility list
    +0x2F30 and the finals)."""
    if not class_masks:
        return "", "", ""
    nl = chr(10)
    table = nl.join(f"        .long {int(c)}, {int(m)}" for c, m in sorted(class_masks.items()))
    marker = ", ".join(f"{b:#04x}" for b in MARKER)
    save = """
        mov ecx, dword ptr [r12+0x2e04]
        mov dword ptr [rsp+0x20], ecx
        movsx ecx, word ptr [r12+0x2e0a]
        mov dword ptr [rsp+0x24], ecx"""
    call = """
        mov rcx, r12
        mov edx, dword ptr [rsp+0x20]
        mov r8d, dword ptr [rsp+0x24]
        call outfit_apply"""
    movement = nl.join(f"""        mov ecx, {r:#x}
        mov edx, {u:#x}
        call oa_ub
        or dword ptr [rsp+0x58], eax""" for r, u in MOVEMENT)
    code = f"""
        .align 8
    own_masks:
{table}
    apply_marker:
        .byte {marker}
        .align 16
    outfit_apply:
        push rbx
        push rsi
        push rdi
        push r12
        push r13
        push r14
        push r15
        sub rsp, 0x60
        mov r12, rcx
        mov r13d, edx
        mov r14d, r8d
        mov ecx, r13d
        call oa_mask
        mov ebx, eax
        mov ecx, dword ptr [r12+0x2e04]
        call oa_mask
        or ebx, eax
        je oa_ret
        movsx eax, word ptr [r12+0x2e0a]
        test eax, eax
        js oa_ret
        test r14d, r14d
        js oa_ret
        cmp eax, r14d
        je oa_ret
        mov rcx, qword ptr [rip + OA_CHAR_TABLE]
        test rcx, rcx
        je oa_ret
        imul rdi, rax, 0x38c
        add rdi, rcx
        movsxd rsi, r14d
        imul rsi, rsi, 0x38c
        add rsi, rcx
        mov dword ptr [rsp+0x58], 0
        test bl, 2
        je oa_apt
        xor r15d, r15d
    oa_bs:
        movsx eax, word ptr [rdi+r15*2+4]
        movsx ecx, word ptr [rsi+r15*2+4]
        sub eax, ecx
        je oa_bs_n
        mov dword ptr [rsp+0x58], 1
        movzx ecx, byte ptr [r12+r15+0x2da0]
        add ecx, eax
        mov edx, 1
        cmp ecx, edx
        cmovl ecx, edx
        mov edx, 255
        cmp ecx, edx
        cmovg ecx, edx
        mov byte ptr [r12+r15+0x2da0], cl
        movsx ecx, word ptr [r12+0x2dfc]
        inc ecx
        imul eax, ecx
        cdq
        sub eax, edx
        sar eax, 1
        movsxd rax, eax
        add rax, qword ptr [r12+r15*8+0x2d18]
        mov ecx, 1
        cmp rax, rcx
        cmovl rax, rcx
        mov qword ptr [r12+r15*8+0x2d18], rax
    oa_bs_n:
        inc r15d
        cmp r15d, 8
        jb oa_bs
    oa_apt:
        test bl, 4
        je oa_wm
        xor r15d, r15d
    oa_ap:
        movzx eax, byte ptr [rdi+r15+0x350]
        movzx ecx, byte ptr [rsi+r15+0x350]
        sub eax, ecx
        je oa_ap_n
        mov dword ptr [rsp+0x58], 1
        movzx ecx, word ptr [r12+r15*2+0x3078]
        add eax, ecx
        xor ecx, ecx
        cmp eax, ecx
        cmovl eax, ecx
        mov ecx, 0xffff
        cmp eax, ecx
        cmovg eax, ecx
        mov word ptr [r12+r15*2+0x3078], ax
    oa_ap_n:
        inc r15d
        cmp r15d, 8
        jb oa_ap
    oa_wm:
        test bl, 8
        je oa_mv
        xor r15d, r15d
    oa_wl:
        movsx eax, word ptr [rdi+r15*2+0x358]
        movsx ecx, word ptr [rsi+r15*2+0x358]
        sub eax, ecx
        je oa_wl_n
        mov dword ptr [rsp+0x58], 1
        movsx ecx, byte ptr [r12+r15*8+0x2dae]
        add eax, ecx
        xor ecx, ecx
        cmp eax, ecx
        cmovl eax, ecx
        mov ecx, 127
        cmp eax, ecx
        cmovg eax, ecx
        mov byte ptr [r12+r15*8+0x2dae], al
    oa_wl_n:
        inc r15d
        cmp r15d, 9
        jb oa_wl
    oa_mv:
        test bl, 16
        je oa_res
{movement}
    oa_res:
        test bl, 32
        je oa_ev
        mov ecx, 0x36c
        mov edx, 0x2e12
    oa_rs:
        call oa_sb
        or dword ptr [rsp+0x58], eax
        inc ecx
        inc edx
        cmp ecx, 0x370
        jb oa_rs
    oa_ev:
        test bl, 1
        je oa_fin
        mov r8, rsi
        mov r9, rdi
        lea r10, [rsp+0x20]
        call oa_diff
        mov dword ptr [rsp+0x40], eax
        mov r8, rdi
        mov r9, rsi
        lea r10, [rsp+0x30]
        call oa_diff
        mov dword ptr [rsp+0x44], eax
        xor r15d, r15d
    oa_el:
        cmp r15d, dword ptr [rsp+0x40]
        jb oa_e1
        cmp r15d, dword ptr [rsp+0x44]
        jae oa_fin
    oa_e1:
        mov r13d, -1
        cmp r15d, dword ptr [rsp+0x44]
        jae oa_e2
        mov r13d, dword ptr [rsp+r15*4+0x30]
    oa_e2:
        cmp r15d, dword ptr [rsp+0x40]
        jae oa_ins
        mov ecx, dword ptr [rsp+r15*4+0x20]
        call oa_find
        test eax, eax
        js oa_en
        mov dword ptr [rsp+0x58], 1
        cmp r13d, -1
        je oa_rm
        mov word ptr [r12+rax*2+0x2eee], r13w
        jmp oa_en
    oa_rm:
        mov ecx, eax
        call oa_remove
        jmp oa_en
    oa_ins:
        mov ecx, r13d
        call oa_place
        mov edx, eax
        mov ecx, r13d
        call oa_insert
        or dword ptr [rsp+0x58], eax
    oa_en:
        inc r15d
        jmp oa_el
    oa_fin:
        cmp dword ptr [rsp+0x58], 0
        je oa_ret
        mov rcx, r12
        xor edx, edx
        xor r8d, r8d
        call {UNIT_RECALC:#x}
    oa_ret:
        add rsp, 0x60
        pop r15
        pop r14
        pop r13
        pop r12
        pop rdi
        pop rsi
        pop rbx
        ret

    oa_mask:
        lea r8, [rip + own_masks]
        mov r9d, {len(class_masks)}
        xor eax, eax
    oa_ml:
        cmp dword ptr [r8], ecx
        je oa_mh
        add r8, 8
        dec r9d
        jne oa_ml
        ret
    oa_mh:
        mov eax, dword ptr [r8+4]
        ret

    oa_ub:
        movzx eax, byte ptr [rdi+rcx]
        movzx r8d, byte ptr [rsi+rcx]
        sub eax, r8d
        je oa_ub_r
        movzx r8d, byte ptr [r12+rdx]
        add eax, r8d
        xor r8d, r8d
        cmp eax, r8d
        cmovl eax, r8d
        mov r8d, 255
        cmp eax, r8d
        cmovg eax, r8d
        mov byte ptr [r12+rdx], al
        mov eax, 1
    oa_ub_r:
        ret

    oa_sb:
        movsx eax, byte ptr [rdi+rcx]
        movsx r8d, byte ptr [rsi+rcx]
        sub eax, r8d
        je oa_sb_r
        movsx r8d, byte ptr [r12+rdx]
        add eax, r8d
        mov r8d, -128
        cmp eax, r8d
        cmovl eax, r8d
        mov r8d, 127
        cmp eax, r8d
        cmovg eax, r8d
        mov byte ptr [r12+rdx], al
        mov eax, 1
    oa_sb_r:
        ret

    oa_diff:
        push rbx
        push rsi
        xor eax, eax
        movzx ecx, byte ptr [r8+0xc8]
        cmp ecx, 4
        jbe oa_d0
        mov ecx, 4
    oa_d0:
        movzx esi, byte ptr [r9+0xc8]
        cmp esi, 4
        jbe oa_d1
        mov esi, 4
    oa_d1:
        xor edx, edx
    oa_dl:
        cmp edx, ecx
        jae oa_dr
        mov r11d, dword ptr [r8+rdx*4+0xb8]
        test r11d, r11d
        je oa_dn
        xor ebx, ebx
    oa_dk:
        cmp ebx, esi
        jae oa_dadd
        cmp r11d, dword ptr [r9+rbx*4+0xb8]
        je oa_dn
        inc ebx
        jmp oa_dk
    oa_dadd:
        mov dword ptr [r10+rax*4], r11d
        inc eax
    oa_dn:
        inc edx
        jmp oa_dl
    oa_dr:
        pop rsi
        pop rbx
        ret

    oa_find:
        movzx ecx, cx
        movsx edx, word ptr [r12+0x2ef8]
        cmp edx, 5
        jle oa_f0
        mov edx, 5
    oa_f0:
        xor eax, eax
    oa_fl:
        cmp eax, edx
        jge oa_fno
        movzx r8d, word ptr [r12+rax*2+0x2eee]
        cmp r8d, ecx
        je oa_fr
        inc eax
        jmp oa_fl
    oa_fno:
        mov eax, -1
    oa_fr:
        ret

    oa_remove:
        movsx edx, word ptr [r12+0x2ef8]
        cmp edx, 5
        jle oa_r0
        mov edx, 5
    oa_r0:
        dec edx
        mov eax, ecx
    oa_rl:
        cmp eax, edx
        jge oa_rz
        movzx r8d, word ptr [r12+rax*2+0x2ef0]
        mov word ptr [r12+rax*2+0x2eee], r8w
        inc eax
        jmp oa_rl
    oa_rz:
        mov word ptr [r12+rax*2+0x2eee], 9999
        dec word ptr [r12+0x2ef8]
        ret

    oa_place:
        push rbx
        mov ebx, ecx
        movzx edx, byte ptr [rdi+0xc8]
        cmp edx, 4
        jbe oa_p0
        mov edx, 4
    oa_p0:
        xor eax, eax
    oa_pl:
        cmp eax, edx
        jae oa_pend
        cmp ebx, dword ptr [rdi+rax*4+0xb8]
        je oa_pj
        inc eax
        jmp oa_pl
    oa_pj:
        test eax, eax
        je oa_pr
        mov ecx, dword ptr [rdi+rax*4+0xb4]
        call oa_find
        test eax, eax
        js oa_pend
        inc eax
        jmp oa_pr
    oa_pend:
        movsx eax, word ptr [r12+0x2ef8]
        cmp eax, 5
        jle oa_pr
        mov eax, 5
    oa_pr:
        pop rbx
        ret

    oa_insert:
        movsx eax, word ptr [r12+0x2ef8]
        movsx r8d, word ptr [r12+0x2efa]
        cmp r8d, 5
        jle oa_i0
        mov r8d, 5
    oa_i0:
        cmp eax, r8d
        jge oa_ifull
        cmp edx, eax
        jle oa_il
        mov edx, eax
    oa_il:
        cmp eax, edx
        jle oa_iput
        movzx r8d, word ptr [r12+rax*2+0x2eec]
        mov word ptr [r12+rax*2+0x2eee], r8w
        dec eax
        jmp oa_il
    oa_iput:
        mov word ptr [r12+rax*2+0x2eee], cx
        inc word ptr [r12+0x2ef8]
        mov eax, 1
        ret
    oa_ifull:
        xor eax, eax
        ret
    OA_CHAR_TABLE = {CHAR_TABLE:#x}
"""
    return save, call, code
