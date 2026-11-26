// d5evil.inc.asm -- the evility extension's code (assembled by d5lib/evility.py into a new exe section .d5el)
//
// The Kit writes a table of *new* evility ids with their own parameters.  This code makes the game's consumers
// honour those ids: the game's own code is never rewritten, and each call site of an extended function is
// redirected to a wrapper that calls the original function and then adds the extension's contribution.
//
// Calling convention: Windows x64.  The wrappers are entered by a `call` from the patched call site, so they
// see the game function's own arguments *and* its return address; they keep every register they clobber and
// return the original function's value (plus their own contribution where the original returns a number).
//
//   wrap_pot    (rcx = unit)                  -> unit_stats_evil_potency: potency words
//   wrap_status (rcx = unit, rdx = agg)       -> unit_stats_evil_status_effects: stat aggregate
//   wrap_growth (rcx = unit, rdx = stat k)    -> unit_stats_evil_growth_bonus: growth percent for stat k
//   wrap_dealt  (rcx = A rec, rdx = D rec, r8 = K, r9 = X, [rsp+0x28] = tgt_i)
//                                             -> damage_damage_multiplier_rules: percent added to the
//                                                damage-dealt multiplier (the caller composes 100 + this)
//   wrap_taken  (rcx = pv, rdx = A rec, r8 = D rec, r9 = K, [rsp+0x28..] = X, tgt_i, fc)
//                                             -> damage_damage_reduction_rules: scales the in/out percent *pv
//   wrap_flight (rcx = battle record)         -> has_flight_like_evility (two copies): predicate
//   wrap_hit    (rcx = pv, rdx = A, r8 = D, r9 = X, [rsp+0x28] = tgt_i)
//                                             -> damage_hit_chance_rules: adds to the in/out hit percent
//   wrap_astat  (rcx = pc, rdx = A, r8 = D, r9 = K, [rsp+0x28] = status index)
//                                             -> damage_status_chance_rules: adds to the in/out ailment percent
//   wrap_achance (rcx = X, rdx = A, r8 = D, r9 = K, [rsp+0x28..] = 3 more)
//                                             -> damage_buff_ailment_chance: records the action context in
//                                                evil_ctx for the duration of the call, so wrap_astat can
//                                                match skill rows and evaluate action-context conditions
//   wrap_crit   (rcx = pv, rdx = A, r8 = D, r9 = -, [rsp+0x28] = X, [rsp+0x30] = target index)      (EX-05e)
//                                             -> critical-rate additions: adds to the in/out crit percent
//   wrap_regen  (rcx = battle record)                                                   (EX-05e)
//                                             -> turn_t1_per_unit_hp_sp: the round-edge HP/SP processor
//   wrap_nullify (rcx = A, rdx = D, r8 = _, r9 = X, [rsp+0x28] = tgt_i, [rsp+0x30] = v)
//                                             -> damage_nullify_predicate: a nullify row for the target
//                                                turns the game's "no" into "yes"
//   wrap_counter (rcx = attacker, rdx = defender)
//                                             -> exec_counter_attack_allow: a counter row for the defender
//                                                turns the game's "no" into "yes"
//   wrap_absorb (rcx = absorber battle rec, rdx = defeated unit battle rec)                          (D4REV2)
//                                             -> FUN_140200D20, damage_after_hit_evaluate's absorption
//                                                pass: an absorb row adds a share of the defeated unit's
//                                                six stats to the same stat-record accumulator D5's 6032
//                                                uses; unit_stats_evil_overrides adds it to the maxima
//                                                (evil_absorb_reapply, called from wrap_conversion)
//
// Table row (32 bytes, terminated by id 0), see d5lib/evility.py:
//   +0  u32 id            the new evility id
//   +4  u32 family_mask   bits: 1 potency words, 2 stat aggregate, 4 growth percentage, 8 damage dealt,
//                         16 damage taken, 32 flight, 64 aura (acts on the recipient), 128 hit chance,
//                         256 ailment chance, 512 base-stat conversion, 1024 critical-rate points,
//                         2048 round-edge HP/SP regeneration, 4096 damage nullification,
//                         8192 ailment immunity, 16384 damage nullify, 32768 counter,
//                         65536 attack power, 131072 defence power, 262144 move range, 524288 range,
//                         1048576 absorption of a defeated unit's stats (D4REV2),
//                         1073741824 weapon-slot percent (D4SIG4, wrap_equip)
//                         2147483648 defender evasion of the hit chance (D4SIG5, wrap_hit)
//   +8  u32 cond_off      byte offset of this row's condition entries in evil_cond
//   +12 u32 n_cond        number of conditions (all must hold)
//   +16 u32 fx_off        byte offset of this row's effects in evil_fx
//   +20 u32 n_fx          number of effects
//   +24 u32 flags         bits 8..31 (MASKWIDE1): the row's SECOND family word (24 more families, all
//                         predicate rows with mask 0; see EXT_FAMILIES in d5lib/evility.py).  A query names
//                         one in the HIGH half of rdi/rdx (`mov rdi, (bit << 32)`); every existing query is a
//                         32-bit `mov edi, N`, whose zero-extension leaves the high half 0.  bit 0: a *skill* row (EX-06).  Its id is a magic.dat skill id and the row applies
//                         when the action uses that skill, whatever the unit learned.  Skill rows are not
//                         reachable through evil_next (they are in no learned list), so evil_dmg_sum scans
//                         evil_skill_index after the ordinary rows and evil_eval matches the id at
//                         action context +0x27670.  0 on every evility row.
//   +28 reserved
// Condition (8 bytes): u16 kind, u16 a, u16 b, u16 c   (see the COND_* labels below)
// Effect (8 bytes): u32 stat word, s32 value.
//   stat word byte 0 = stat index (or, for the conversion family, the destination index;
//   byte 1 = its source), byte 2 = a runtime scale kind (0 = the value is added as written).
//   A scaled effect adds value * count, where count is a battle-map count (evil_scale) -- see
//   SCALES in d5lib/evility.py.  Bytes 1 and 2 are always 0 for the pre-EX-05d families, so an
//   older table decodes identically.
//   PLUME1 numeric/additive effects only: stat bit24 marks a capped effect. Its value word is
//   signed16 base | unsigned16 max. Decode the base before scaling, then apply min(value, max)
//   to that effect before summing. Unflagged effects keep their original s32 value and behavior.
//
// Unit record fields used: +0x3030 evility count, +0x2F30 sorted id list, +0x2E04 character id,
// +0x2DFC level (short), +0x2CC8 hp, +0x2CD8 max hp, +0x3068..+0x3076 the eight potency words,
// +0x2E32 team byte, +0x2E2A movement type (2 = flying), +0x4348 stat-record index,
// +0x138/+0x156 (312/342) weapon slot 0 item id / category, +0x390/+0x3AE (912/942) slot 1.
// Battle record: +0x240 unit record, +0x2E8 active byte, +0x2EE carrier link, +0x2F4 battle slot (short,
// the index the action context's target entries carry), +8 / +0x10 world x / z (f32), +0x2C4 facing angle
// (short, degrees).  The unit's class is its class id (char.dat id) at unit record +0x2E04.
// Action context X: +0x27670 skill id, +0x27678 Skill.dat row pointer, +0x276BC attack element byte.
// Skill row K: +1014 effect type (2 physical, 3 magic).
// Potency clamps to the game's own limits at 0x140A18780 / 0x140A18788 (qwords) exactly as the vanilla
// code does.

// --------------------------------------------------------------------------------------------- helpers
// evil_brec(rcx = unit record) -> rax = its battle record, or 0 when it is not on the map
// Clobbers rax, rcx, rdx, r8.
// evil_find(ecx = id) -> rax = the first row of that id's run, edx = how many rows share the id (0 = none).
// A lower-bound binary search finds the first row with id >= the target, then a forward count measures the
// run.  Several rows may carry one id (P3b, the same model as Overlord's evility sections: one effect per
// row, additive), so a caller that walks rows uses evil_next, which emits the whole run in order.
// Only the evility rows are searched: the skill rows come after them and carry ids from another
// namespace, so counting them in would break the ordering this search relies on.
// Leaf; clobbers only volatile integer registers.
evil_find:
    lea r8, [rip + evil_tbl]
    xor r9d, r9d
    mov r10d, dword ptr [rip + evil_evility_count]
.f_loop:
    cmp r9d, r10d
    jae .f_bound
    lea r11d, [r9d + r10d]
    shr r11d, 1
    mov eax, r11d
    shl rax, 5
    add rax, r8
    mov edx, dword ptr [rax]
    cmp edx, ecx
    jae .f_high
    lea r9d, [r11d + 1]
    jmp .f_loop
.f_high:
    mov r10d, r11d
    jmp .f_loop
.f_bound:
    xor eax, eax
    xor edx, edx
    cmp r9d, dword ptr [rip + evil_evility_count]
    jae .f_ret
    mov eax, r9d
    shl rax, 5
    add rax, r8
    cmp dword ptr [rax], ecx
    jne .f_ret
    xor r11d, r11d                    // run length
    mov r10d, r9d                     // first index of the run
.f_count:
    cmp r10d, dword ptr [rip + evil_evility_count]
    jae .f_counted
    mov edx, r10d
    shl rdx, 5
    add rdx, r8
    cmp dword ptr [rdx], ecx
    jne .f_counted
    inc r11d
    inc r10d
    jmp .f_count
.f_counted:
    mov edx, r11d
.f_ret:
    ret

// evil_presence() -> fills evil_present: bit (id & 0x7FFF) is set when a unit on the battle table has learned
// evility id.  Entries are taken on the two cheapest tests evil_near also makes (active byte +0x2E8, unit
// pointer +0x240), so the map can only say "present" for a unit evil_near would later refuse, never the
// reverse.  Leaf, no stack use; clobbers rax, rcx, rdx, r8, r9, r10, r11.
evil_presence:
    lea r10, [rip + evil_present]
    xor eax, eax
    mov ecx, 512
.pm_clear:
    mov qword ptr [r10 + rcx*8 - 8], rax
    dec ecx
    jnz .pm_clear
    mov r9, 0x141ba33b0
    xor r11d, r11d
.pm_loop:
    cmp byte ptr [r9 + 0x2e8], 0
    je .pm_next
    mov r8, qword ptr [r9 + 0x240]
    test r8, r8
    jz .pm_next
    mov ecx, dword ptr [r8 + 0x3030]
    test ecx, ecx
    jle .pm_next
    cmp ecx, 64
    jbe .pm_ids
    mov ecx, 64
.pm_ids:
    mov edx, dword ptr [r8 + 0x2f30 + rcx*4 - 4]
    and edx, 0x7fff
    bts dword ptr [r10], edx
    dec ecx
    jnz .pm_ids
.pm_next:
    add r9, 4704
    inc r11d
    cmp r11d, 256
    jl .pm_loop
    ret

// evil_next(rcx = opaque cursor, edx = family, rsi = unit) -> rax = row or 0, rcx = next cursor.
// Cursor fields: bits 0-15 the learned-id position, 16-31 the aura-index position, 32-47 the row position
// inside the current id's run.  The two sorted sources (the unit's learned ids and the table's aura rows)
// are merged so rows come out in table order, and a run of rows sharing one id is emitted one row per call
// before the id advances.  Each cursor field advances monotonically; ordinary hot calls cost
// O(learned_ids * log rows), unrelated installed rows are never scanned.
evil_next:
    push rbx
    push rdi
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x48
    mov rbx, rcx
    mov r13d, ecx
    shr r13d, 16
    and r13d, 0xffff                  // aura-index position
    mov r14, rcx
    shr r14, 32
    and r14d, 0xffff                  // row position inside a run
    mov r15d, ebx
    and r15d, 0xffff                  // learned-id position
    mov rdi, rdx                      // MASKWIDE1: the query is 64-bit, low half = family mask, high half = second family word
    mov qword ptr [rsp + 0x20], 0     // pending ordinary row
    mov qword ptr [rsp + 0x28], 0     // the pending id's run base
    mov dword ptr [rsp + 0x30], 0     // run length
    mov dword ptr [rsp + 0x34], 0     // row position being examined
    mov dword ptr [rsp + 0x38], 0     // row position of the pending row
    mov dword ptr [rsp + 0x3c], 0     // next call's row position
    mov dword ptr [rsp + 0x40], r15d  // next call's learned-id position
    mov dword ptr [rsp + 0x44], 0     // the current id's index in the learned list
    mov r12d, dword ptr [rsi + 0x3030]
    test r12d, r12d
    jns .i_nonnegative
    xor r12d, r12d
.i_nonnegative:
    cmp r12d, 64
    jbe .i_learned
    mov r12d, 64
.i_learned:
    cmp r15d, r12d
    jb .i_have_id
    mov dword ptr [rsp + 0x40], r15d  // every learned id has been offered
    mov dword ptr [rsp + 0x3c], 0
    jmp .i_auras
.i_have_id:
    mov ecx, dword ptr [rsi + 0x2f30 + r15*4]
    mov dword ptr [rsp + 0x34], r14d  // the entry row position applies to the first id only
    xor r14d, r14d
    mov dword ptr [rsp + 0x44], r15d  // the id's own index in the learned list
    inc r15d
    cmp r15d, 1
    jbe .i_find
    cmp ecx, dword ptr [rsi + 0x2f28 + r15*4]
    jne .i_find
    cmp dword ptr [rsp + 0x34], 0     // a repeated learned id: skip it unless its run is being continued
    je .i_learned
.i_find:
    call evil_find                    // rax = run base, edx = run length
    test rdx, rdx
    jz .i_no_run
    mov qword ptr [rsp + 0x28], rax
    mov dword ptr [rsp + 0x30], edx
.i_run:
    mov eax, dword ptr [rsp + 0x34]
    cmp eax, dword ptr [rsp + 0x30]
    jae .i_no_row                     // defensive: a row position past the run
    mov rdx, qword ptr [rsp + 0x28]
    mov ecx, eax
    shl rcx, 5
    add rdx, rcx
    mov eax, dword ptr [rdx + 4]
    test eax, 64
    jnz .i_run_other                  // an aura row is reached through the aura index, not here
    test eax, edi
    jnz .i_row_hit
    mov eax, dword ptr [rdx + 24]     // MASKWIDE1: the row's second family word, flags bits 8..31
    shr eax, 8
    mov r8, rdi
    shr r8, 32                        // the query's second word
    test eax, r8d
    jz .i_run_other
.i_row_hit:
    mov qword ptr [rsp + 0x20], rdx   // this row is the pending candidate
    mov eax, dword ptr [rsp + 0x34]
    mov dword ptr [rsp + 0x38], eax
    inc eax
    cmp eax, dword ptr [rsp + 0x30]
    jae .i_run_done
    mov dword ptr [rsp + 0x3c], eax   // stay on this id: its next row is the next candidate
    mov eax, dword ptr [rsp + 0x44]
    mov dword ptr [rsp + 0x40], eax
    jmp .i_auras
.i_run_done:
    mov dword ptr [rsp + 0x3c], 0
    mov dword ptr [rsp + 0x40], r15d  // the run is done: advance past the id
    jmp .i_auras
.i_run_other:
    inc dword ptr [rsp + 0x34]
    jmp .i_run
.i_no_row:
.i_no_run:
    // no row here (no run, or none of its rows names this family): offer the next learned id
    jmp .i_learned
.i_auras:
    mov eax, edi
    and eax, 0x4a010c9b                // existing aura families plus attack power (PLUME1) and weapon_percent (D4SIG4)
    jz .i_ordinary
    cmp r13d, dword ptr [rip + evil_aura_count]
    jae .i_ordinary
    // DRPGEVIL1c: the presence map.  An aura row costs a 256-entry battle-table walk (its near_has), so a
    // pass used to cost that walk once per aura row of the family -- about 2,900 instructions each, material
    // past a few dozen rows.  The first call of a pass (cursor 0) now records, in one walk, every evility id
    // a unit on the battle table has learned (one bit per id, ids are < 32768), and an aura row whose
    // near_has names an id nobody has is skipped here without being evaluated.  The map is a superset of
    // what evil_near accepts (it takes every active entry with a unit, the subject included), so a skipped
    // row is exactly a row whose near_has could not have held.
    test rbx, rbx
    jnz .i_pm_ready
    call evil_presence
.i_pm_ready:
    lea rax, [rip + evil_aura_index]
    mov eax, dword ptr [rax + r13*4]
    lea rdx, [rip + evil_tbl]
    add rax, rdx
    test dword ptr [rax + 4], edi
    jz .i_pm_skip
    mov ecx, dword ptr [rax + 12]     // conditions of the row
    mov edx, dword ptr [rax + 8]
    lea r8, [rip + evil_cond]
    add r8, rdx
    lea r9, [rip + evil_present]
.i_pm_test:
    test ecx, ecx
    jz .i_merge
    cmp word ptr [r8], 26
    jne .i_pm_next
    movzx edx, word ptr [r8 + 6]      // the evility id the provider must carry
    and edx, 0x7fff
    bt dword ptr [r9], edx
    jnc .i_pm_skip                  // no unit on the battle table has it
.i_pm_next:
    add r8, 8
    dec ecx
    jmp .i_pm_test
.i_pm_skip:
    inc r13d
    cmp r13d, dword ptr [rip + evil_aura_count]
    jae .i_ordinary
    jmp .i_pm_ready                   // the map is this pass's: do not rebuild it per skipped row
.i_merge:
    mov rdx, qword ptr [rsp + 0x20]
    test rdx, rdx
    jz .i_aura
    mov ecx, dword ptr [rdx]
    cmp dword ptr [rax], ecx
    ja .i_ordinary
    // the aura row comes first: keep the same pending row for the next call (rax keeps the aura row)
    mov r11d, dword ptr [rsp + 0x38]
    mov dword ptr [rsp + 0x3c], r11d
    mov r11d, dword ptr [rsp + 0x44]
    mov dword ptr [rsp + 0x40], r11d
.i_aura:
    inc r13d
    jmp .i_ret
.i_ordinary:
    mov rax, qword ptr [rsp + 0x20]
.i_ret:
    mov ecx, r13d
    shl ecx, 16
    or ecx, dword ptr [rsp + 0x40]
    mov edx, dword ptr [rsp + 0x3c]
    shl rdx, 32
    or rcx, rdx
    add rsp, 0x48
    pop r15
    pop r14
    pop r13
    pop r12
    pop rdi
    pop rbx
    ret

evil_brec:
    xor eax, eax
    test rcx, rcx
    jz .b_ret
    mov r8, 0x141ba33b0
    xor edx, edx
.b_loop:
    cmp qword ptr [r8 + 0x240], rcx
    je .b_found
    add r8, 4704
    inc edx
    cmp edx, 256
    jl .b_loop
    ret
.b_found:
    mov rax, r8
.b_ret:
    ret

// evil_cell(rcx = battle record) -> eax = cell x, edx = cell z  (game formula: trunc(v / 12.0f), 0 if v < 0)
// Clobbers rax, rcx, rdx, xmm0, xmm1 only.
evil_cell:
    xor eax, eax
    xor edx, edx
    test rcx, rcx
    jz .c_ret
    movss xmm0, dword ptr [rcx + 8]
    xorps xmm1, xmm1
    comiss xmm0, xmm1
    jb .c_z
    mov eax, 12
    cvtsi2ss xmm1, eax
    divss xmm0, xmm1
    cvttss2si eax, xmm0
.c_z:
    movss xmm0, dword ptr [rcx + 0x10]
    xorps xmm1, xmm1
    comiss xmm0, xmm1
    jb .c_ret
    mov edx, 12
    cvtsi2ss xmm1, edx
    divss xmm0, xmm1
    cvttss2si edx, xmm0
.c_ret:
    ret

// evil_near(rdi = subject unit, rsi = subject battle record, edx = relation (0 any, 1 ally, 2 enemy),
//           ecx = radius in panels (0xFFFF = anywhere), r8d = filter value, r10d = filter kind
//           (0 none, 1 evility id the others must carry, 2 character id, 3 monster, 4 human,
//           5 same squad id as `value`))
//   -> eax = how many units qualify (never counts the subject itself, and never a carried unit)
// Walks the game's 256-entry battle-unit table the same way the game's own aura helpers do
// (model_has_ally_evility_predicate: active byte +0x2E8, unit at +0x240, stat index < 0x28A),
// with a panel distance instead of a path query, and the game's own hostile-team table inlined.
evil_near:
    push rdi
    push rbx
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x30
    mov r14, rdi                      // subject unit
    mov r15, rsi                      // subject battle record
    mov ebx, edx                      // relation
    mov ebp, ecx                      // radius
    mov r13d, r8d                     // filter value
    mov dword ptr [rsp + 0x28], 0     // count
    mov dword ptr [rsp + 0x2c], r10d  // filter kind (r10 is the scan index below)
    test r14, r14
    jz .n_done
    test r15, r15
    jz .n_done
    mov rcx, r15
    call evil_cell
    mov dword ptr [rsp + 0x20], eax   // subject cell x
    mov dword ptr [rsp + 0x24], edx   // subject cell z
    mov rax, qword ptr [r15 + 0x240]
    movzx r12d, byte ptr [rax + 0x2e32]   // subject team
    mov r9, 0x141ba33b0               // scan cursor
    xor r11d, r11d                    // index
.n_loop:
    cmp r9, r15
    je .n_next                        // never the subject itself
    cmp byte ptr [r9 + 0x2e8], 0
    je .n_next                        // not on the map
    cmp word ptr [r9 + 0x2ee], 0
    jge .n_next                       // carried by another unit
    mov rdi, qword ptr [r9 + 0x240]
    test rdi, rdi
    jz .n_next
    cmp dword ptr [rdi + 0x4348], 0x28a
    jae .n_next                       // no stat record: not a real unit
    movzx edx, byte ptr [rdi + 0x2e32]    // candidate team
    cmp ebx, 1
    je .n_ally
    cmp ebx, 2
    je .n_enemy
    jmp .n_rel_ok
.n_ally:
    cmp edx, r12d
    jne .n_next
    jmp .n_rel_ok
.n_enemy:
    cmp edx, r12d
    je .n_next
    lea rax, [rip + evil_hostile]
    movzx eax, byte ptr [rax + r12]
    bt eax, edx
    jnc .n_next
.n_rel_ok:
    // CARRIERS2: the filter is selected by its *kind*, not by whether a value is present, so a filter
    // whose value is legitimately 0 (or unused, as for the two type filters) still filters.  Kinds:
    //   0 none, 1 the candidate has learned evility `value`, 2 the candidate's class/character id
    //   (unit record +0x2E04) is `value`, 3 the candidate is a monster, 4 the candidate is a human
    cmp dword ptr [rsp + 0x2c], 0
    je .n_dist
    cmp dword ptr [rsp + 0x2c], 2
    je .n_char_filter
    cmp dword ptr [rsp + 0x2c], 3
    je .n_monster_filter
    cmp dword ptr [rsp + 0x2c], 4
    je .n_human_filter
    cmp dword ptr [rsp + 0x2c], 5
    je .n_squad_filter
    cmp dword ptr [rsp + 0x2c], 6
    je .n_prov_filter
    cmp dword ptr [rsp + 0x2c], 7
    je .n_male_filter
    cmp dword ptr [rsp + 0x2c], 8
    je .n_female_filter
    cmp dword ptr [rsp + 0x2c], 9
    je .n_weapon_filter
    cmp dword ptr [rsp + 0x2c], 10
    je .n_statmod_filter
    cmp dword ptr [rsp + 0x2c], 11
    je .n_rank_filter
    cmp dword ptr [rsp + 0x2c], 12
    je .n_rank_filter
    cmp dword ptr [rsp + 0x2c], 13
    je .n_hp_filter
    mov r8d, dword ptr [rdi + 0x3030]     // the candidate's evility count
    test r8d, r8d
    jle .n_next
    xor r10d, r10d
.n_search:
    cmp r10d, r8d
    jge .n_next
    cmp dword ptr [rdi + 0x2f30 + r10*4], r13d
    je .n_dist
    inc r10d
    jmp .n_search
.n_char_filter:
    cmp dword ptr [rdi + 0x2e04], r13d    // the candidate's character id
    je .n_dist
    jmp .n_next
// CARRIERS2: the two type filters.  Byte +0x2E25 is the game's own class-kind byte (1 human male,
// 2 human female, 11 monster male, 12 monster female; see evil_type).  Only the human/monster split is
// asked for here, and the gender-swap evility (4301) never crosses that split, so reading the byte
// directly is exact for this question.  A candidate whose byte is 0 (undetermined) matches neither.
.n_monster_filter:
    movzx r10d, byte ptr [rdi + 0x2e25]
    cmp r10d, 11
    jae .n_dist
    jmp .n_next
.n_human_filter:
    movzx r10d, byte ptr [rdi + 0x2e25]
    cmp r10d, 1
    jb .n_next
    cmp r10d, 2
    ja .n_next
    jmp .n_dist
// EVILFX1: filter kind 5, the candidate is in the subject's squad.  `value` is the subject's squad id (the
// caller only passes one >= 0).  The candidate needs the same assignment gate (+0x30A1 != 0) and the same
// first/current squad id (+0x30A0, signed) -- the two fields the `squad` scale and vanilla Heart of a Leader
// read -- so a candidate outside any squad (id -1 or gate 0) never matches.
.n_squad_filter:
    cmp byte ptr [rdi + 0x30a1], 0
    je .n_next
    movsx r10d, byte ptr [rdi + 0x30a0]
    cmp r10d, r13d
    je .n_dist
    jmp .n_next
// DRPGEVIL1c: filter kinds 7 / 8 / 9 -- the candidate is male (class-kind byte 1 or 11), female (2 or 12),
// or has an equipped weapon of item category `value` (slot 0, else slot 1: the `weapon` condition's fields).
.n_male_filter:
    movzx r10d, byte ptr [rdi + 0x2e25]
    cmp r10d, 1
    je .n_dist
    cmp r10d, 11
    je .n_dist
    jmp .n_next
.n_female_filter:
    movzx r10d, byte ptr [rdi + 0x2e25]
    cmp r10d, 2
    je .n_dist
    cmp r10d, 12
    je .n_dist
    jmp .n_next
.n_weapon_filter:
    cmp dword ptr [rdi + 312], 0
    je .n_weapon_s1
    movzx r10d, byte ptr [rdi + 342]
    cmp r10d, r13d
    je .n_dist
.n_weapon_s1:
    cmp dword ptr [rdi + 912], 0
    je .n_next
    movzx r10d, byte ptr [rdi + 942]
    cmp r10d, r13d
    je .n_dist
    jmp .n_next
// EVILFX2: filter kinds 11 / 12 -- the candidate's current stat `value` (2..7 = ATK..SPD, the six qwords at unit
// +0x2CE8, the vector the absorb family also reads) is strictly greater (11) / strictly less (12) than the
// subject's.  "I have the highest ATK on my side" is then "no ally counts under kind 11".
.n_rank_filter:
    movzx eax, r13b
    sub eax, 2
    cmp eax, 5
    ja .n_next
    mov r8, qword ptr [rdi + rax*8 + 0x2ce8]
    mov r10, qword ptr [r14 + rax*8 + 0x2ce8]
    cmp dword ptr [rsp + 0x2c], 11
    jne .n_rank_less
    cmp r8, r10
    jg .n_dist
    jmp .n_next
.n_rank_less:
    cmp r8, r10
    jl .n_dist
    jmp .n_next
// EVILFX2: filter kind 10 -- the candidate is under a stat-change status (a buff or debuff from a skill).
// value bits 0..7 = stat 2..7 (ATK DEF INT RES HIT SPD), bit 8 = debuff (power < 0) instead of buff (> 0).
// The fields are the ones unit_stats_evil_status_effects (0x1401B97D0) reads for status slots 7..12 =
// stat + 5: active byte at stat record +1257 + slot, signed power byte at +1334 + slot (see evil_statmod).
.n_statmod_filter:
    movzx eax, r13b
    cmp eax, 2
    jb .n_next
    cmp eax, 7
    ja .n_next
    mov r8d, dword ptr [rdi + 0x4348]     // < 0x28a, tested above
    imul r8, r8, 3736
    mov r10, 0x141067dc8
    add r8, r10
    cmp byte ptr [r8 + rax + 1262], 0
    je .n_next
    movsx r10d, byte ptr [r8 + rax + 1339]
    test r13d, 0x100
    jnz .n_statmod_neg
    test r10d, r10d
    jg .n_dist
    jmp .n_next
.n_statmod_neg:
    test r10d, r10d
    jl .n_dist
    jmp .n_next
// DRPGEVIL1b: filter kind 6, the candidate carries evility (value & 0xFFFF) AND passes a test on itself --
// the holder-side condition of an aura ("while I hold a fist weapon, the party ...").  value bits 16..23 =
// test, 24..31 = argument.  Test 1: an equipped weapon has item category arg (the fields the `weapon`
// condition reads: slot 0 item +312 / category +342, slot 1 +912 / +942).  Tests 2..4: current hp
// (+0x2CC8) against arg percent of max hp (+0x2CD8), compared as hp * 100 vs max * arg, which is the
// whole-percent arithmetic of hp_above / hp_below and the inclusive hp_at_or_below.
.n_hp_filter:                         // DRPGSIG1 filter 13: the candidate is alive and its HP is at or below `value` percent of its max
    mov rcx, qword ptr [rdi + 0x2cd8]     // max hp
    test rcx, rcx
    jle .n_next
    cmp qword ptr [rdi + 0x2cc8], 0
    jle .n_next                           // a defeated unit is not "an enemy with low HP"
    imul rcx, r13                         // max * percent (r13d = the filter value, zero-extended)
    mov r8, qword ptr [rdi + 0x2cc8]
    imul r8, r8, 100
    cmp r8, rcx
    jle .n_dist
    jmp .n_next
.n_prov_filter:
    mov r8d, dword ptr [rdi + 0x3030]
    test r8d, r8d
    jle .n_next
    movzx eax, r13w
    xor r10d, r10d
.n_prov_search:
    cmp r10d, r8d
    jge .n_next
    cmp dword ptr [rdi + 0x2f30 + r10*4], eax
    je .n_prov_test
    inc r10d
    jmp .n_prov_search
.n_prov_test:
    mov eax, r13d
    shr eax, 24                       // argument
    mov r10d, r13d
    shr r10d, 16
    and r10d, 255                     // test
    cmp r10d, 1
    jne .n_prov_hp
    cmp dword ptr [rdi + 312], 0
    je .n_prov_w1
    movzx ecx, byte ptr [rdi + 342]
    cmp ecx, eax
    je .n_dist
.n_prov_w1:
    cmp dword ptr [rdi + 912], 0
    je .n_next
    movzx ecx, byte ptr [rdi + 942]
    cmp ecx, eax
    je .n_dist
    jmp .n_next
.n_prov_hp:
    cmp r10d, 5
    jne .n_prov_hp_go
    // EVILFX2: test 5, the provider is under a buff of stat arg (2..7): the fields of evil_statmod
    cmp eax, 2
    jb .n_next
    cmp eax, 7
    ja .n_next
    mov r8d, dword ptr [rdi + 0x4348]
    imul r8, r8, 3736
    mov r10, 0x141067dc8
    add r8, r10
    cmp byte ptr [r8 + rax + 1262], 0
    je .n_next
    cmp byte ptr [r8 + rax + 1339], 0
    jg .n_dist
    jmp .n_next
.n_prov_hp_go:
    mov rcx, qword ptr [rdi + 0x2cd8]     // max hp
    test rcx, rcx
    jle .n_next
    imul rcx, rax                         // max * arg
    mov r8, qword ptr [rdi + 0x2cc8]      // hp
    imul r8, r8, 100
    cmp r10d, 2
    je .n_prov_ge
    cmp r10d, 3
    je .n_prov_lt
    cmp r10d, 4
    jne .n_next                           // unknown test: no provider
    cmp r8, rcx
    jle .n_dist
    jmp .n_next
.n_prov_ge:
    cmp r8, rcx
    jge .n_dist
    jmp .n_next
.n_prov_lt:
    cmp r8, rcx
    jl .n_dist
    jmp .n_next
.n_dist:
    cmp ebp, 0xffff
    je .n_count                       // no distance limit: an "on the map" count
    mov rcx, r9
    call evil_cell
    sub eax, dword ptr [rsp + 0x20]
    sub edx, dword ptr [rsp + 0x24]
    mov ecx, eax
    sar ecx, 31
    xor eax, ecx
    sub eax, ecx                      // |dx|
    mov ecx, edx
    sar ecx, 31
    xor edx, ecx
    sub edx, ecx                      // |dz|
    add eax, edx
    test eax, eax
    jz .n_next                        // same panel: not "near" for these conditions
    cmp eax, ebp
    jg .n_next
.n_count:
    inc dword ptr [rsp + 0x28]
    mov qword ptr [rip + evil_near_unit], rdi     // EVILFX2: the last qualifying unit (a regen aura's provider)
.n_next:
    add r9, 4704
    inc r11d
    cmp r11d, 256
    jl .n_loop
.n_done:
    mov eax, dword ptr [rsp + 0x28]
    add rsp, 0x30
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rbx
    pop rdi
    ret

// evil_classinfo(ecx = class id) -> eax = favourite weapon | potential type << 8, 0 when the class is not in the
// registry (DRPGPARTY1).  The registry is evil_class_tbl: evil_class_count dwords sorted by class id, each
// class | weapon << 16 | potential << 24 (built by evility.class_table).  Clobbers rax, rdx, r8, r9, r10 only.
evil_classinfo:
    push rbx
    mov r8d, dword ptr [rip + evil_class_count]     // hi (exclusive)
    lea r9, [rip + evil_class_tbl]
    xor r10d, r10d                                  // lo
.ci_loop:
    cmp r10d, r8d
    jge .ci_none
    lea eax, [r10 + r8]
    shr eax, 1
    mov edx, dword ptr [r9 + rax*4]
    movzx ebx, dx
    cmp ebx, ecx
    je .ci_found
    jb .ci_lower
    mov r8d, eax
    jmp .ci_loop
.ci_lower:
    lea r10d, [rax + 1]
    jmp .ci_loop
.ci_found:
    shr edx, 16
    mov eax, edx
    pop rbx
    ret
.ci_none:
    xor eax, eax
    pop rbx
    ret

// evil_pd_add(ecx = class id, edx = weapons seen so far as a bit mask, bit w for weapon w) -> eax = the mask
// with this class's favourite weapon added, or -1 when the class has no registered favourite weapon or an
// earlier member already has that one (DRPGPARTY1).  Clobbers rax, rcx, rdx, r8..r11.  The frame is the 32
// bytes of home space the audited ABI wants under a call plus 8 to keep rsp 16-byte aligned at the call.
evil_pd_add:
    sub rsp, 0x28
    mov r11d, edx
    cmp ecx, 0xffff
    ja .pa_bad
    call evil_classinfo
    movzx ecx, al
    test ecx, ecx
    jz .pa_bad
    cmp ecx, 9
    ja .pa_bad
    mov eax, 1
    shl eax, cl
    test r11d, eax
    jnz .pa_bad
    or eax, r11d
    add rsp, 0x28
    ret
.pa_bad:
    mov eax, -1
    add rsp, 0x28
    ret

// evil_party_distinct(rcx = unit record) -> eax = 1 when every member of the unit's own side on the map (the
// unit itself included, carried units not counted -- evil_near's rule) has a registered favourite weapon and no
// two members share one; 0 otherwise and when the unit is not on the map (DRPGPARTY1: Disgaea RPG's "the party
// characters' favourite weapon types are all different").  One walk of the battle-unit table, the same entry
// tests evil_near makes with relation 1 (ally) and the whole map.
evil_party_distinct:
    push rbx
    push rbp
    push rdi
    push rsi
    push r12
    push r13
    sub rsp, 0x28
    xor eax, eax
    test rcx, rcx
    jz .pd_ret
    mov r12, rcx                      // subject unit
    call evil_brec
    test rax, rax
    jz .pd_ret                        // not on the map: no party
    mov qword ptr [rsp + 0x20], rax   // subject battle record
    movzx r13d, byte ptr [r12 + 0x2e32]   // subject team
    mov ecx, dword ptr [r12 + 0x2e04]
    xor edx, edx
    call evil_pd_add
    cmp eax, -1
    je .pd_no
    mov ebx, eax                      // weapons seen
    mov rbp, 0x141ba33b0              // scan cursor
    xor edi, edi                      // index
.pd_loop:
    cmp rbp, qword ptr [rsp + 0x20]
    je .pd_next                       // the subject was counted first
    cmp byte ptr [rbp + 0x2e8], 0
    je .pd_next                       // not on the map
    cmp word ptr [rbp + 0x2ee], 0
    jge .pd_next                      // carried by another unit
    mov rsi, qword ptr [rbp + 0x240]
    test rsi, rsi
    jz .pd_next
    cmp dword ptr [rsi + 0x4348], 0x28a
    jae .pd_next                      // no stat record: not a real unit
    movzx eax, byte ptr [rsi + 0x2e32]
    cmp eax, r13d
    jne .pd_next                      // another side
    mov ecx, dword ptr [rsi + 0x2e04]
    mov edx, ebx
    call evil_pd_add
    cmp eax, -1
    je .pd_no
    mov ebx, eax
.pd_next:
    add rbp, 4704
    inc edi
    cmp edi, 256
    jl .pd_loop
    mov eax, 1
    jmp .pd_ret
.pd_no:
    xor eax, eax
.pd_ret:
    add rsp, 0x28
    pop r13
    pop r12
    pop rsi
    pop rdi
    pop rbp
    pop rbx
    ret

// evil_party(rcx = unit record, edx = member kind, r8d = value) -> eax = how many members of the unit's own
// side on the map are of that kind, THE UNIT ITSELF INCLUDED when it qualifies (DRPGEVIL1c: Disgaea RPG's
// "number of humanoid characters in the party" counts the holder).  Kinds: 1 human, 2 monster, 3 male,
// 4 female, 5 has an equipped weapon of item category `value`.  0 when the unit is not on the map.
// Allies are found by evil_near (relation 1, whole map), which never counts the subject, so the subject is
// tested here with the same fields the filters read.
evil_party:
    push rbx
    push rbp
    push rdi
    push rsi
    push r12
    push r13
    sub rsp, 0x38
    xor eax, eax
    test rcx, rcx
    jz .pt_ret
    mov r12, rcx                      // unit
    mov ebx, edx                      // kind
    mov r13d, r8d                     // value
    cmp ebx, 1
    jb .pt_ret
    cmp ebx, 5
    ja .pt_ret
    call evil_brec
    test rax, rax
    jz .pt_ret                        // not on the map: no party
    mov rsi, rax
    mov rdi, r12
    mov edx, 1                        // allies
    mov ecx, 0xffff                   // the whole map
    mov r8d, r13d
    mov r10d, 4                       // evil_near filter kind: 1 human -> 4, 2 monster -> 3,
    cmp ebx, 1                        // 3 male -> 7, 4 female -> 8, 5 weapon category -> 9
    je .pt_go
    mov r10d, 3
    cmp ebx, 2
    je .pt_go
    lea r10d, [rbx + 4]
.pt_go:
    call evil_near
    mov ebp, eax
    // the unit itself
    movzx ecx, byte ptr [r12 + 0x2e25]
    cmp ebx, 1
    je .pt_human
    cmp ebx, 2
    je .pt_monster
    cmp ebx, 3
    je .pt_male
    cmp ebx, 4
    je .pt_female
    cmp dword ptr [r12 + 312], 0
    je .pt_w1
    movzx ecx, byte ptr [r12 + 342]
    cmp ecx, r13d
    je .pt_self
.pt_w1:
    cmp dword ptr [r12 + 912], 0
    je .pt_done
    movzx ecx, byte ptr [r12 + 942]
    cmp ecx, r13d
    je .pt_self
    jmp .pt_done
.pt_human:
    cmp ecx, 1
    je .pt_self
    cmp ecx, 2
    je .pt_self
    jmp .pt_done
.pt_monster:
    cmp ecx, 11
    jae .pt_self
    jmp .pt_done
.pt_male:
    cmp ecx, 1
    je .pt_self
    cmp ecx, 11
    je .pt_self
    jmp .pt_done
.pt_female:
    cmp ecx, 2
    je .pt_self
    cmp ecx, 12
    jne .pt_done
.pt_self:
    inc ebp
.pt_done:
    mov eax, ebp
.pt_ret:
    add rsp, 0x38
    pop r13
    pop r12
    pop rsi
    pop rdi
    pop rbp
    pop rbx
    ret
// evil_scale(rcx = unit record, edx = scale kind) -> eax = count (0 when the unit is not on the map
// or the kind is unknown).  Kinds: 1 ally adjacent, 2 enemy adjacent, 3 any adjacent, 4 ally on the
// map, 5 enemy on the map, 6 any unit on the map -- the same table walk, panel distance and
// eligibility tests the adjacency conditions use.
// 7 and 8 are the battle's own defeated-unit counters (see .sc_defeated).
// Preserves every nonvolatile register.
evil_scale:
    push rbx
    push rbp
    push rdi
    push rsi
    push r12
    push r13
    sub rsp, 0x58
    xor eax, eax
    test rcx, rcx
    jz .sc_ret
    test edx, edx
    jz .sc_ret
    cmp edx, 6
    ja .sc_above
    mov r12, rcx                      // unit
    lea rbx, [rip + evil_scale_tbl]
    dec edx
    movzx r13d, word ptr [rbx + rdx*4]        // relation
    movzx ebp, word ptr [rbx + rdx*4 + 2]     // radius
    mov rcx, r12
    call evil_brec
    mov rsi, rax
    test rax, rax
    jz .sc_ret                        // not on the map: no count
    mov rdi, r12
    mov edx, r13d
    mov ecx, ebp
    xor r8d, r8d
    xor r10d, r10d
    call evil_near
.sc_ret:
    add rsp, 0x58
    pop r13
    pop r12
    pop rsi
    pop rdi
    pop rbp
    pop rbx
    ret
// The defeated-unit counters: the game's own six u16 slots at 0x146A5F054, indexed by the defeated
// unit's team byte (unit record +0x2E32), zeroed by battle_start_common and incremented in
// damage_after_hit_evaluate when a unit's HP reaches 0 (clamped at 99 each).  D5's own Queen of Coffins
// (evility 140) multiplies its value by the sum of all six; kind 7 sums only the teams hostile to this
// unit's team (HOSTILE_TEAMS, the same bit table the relation tests use), which is what "units I have
// defeated" means, and kind 8 sums all six, which is D5's own arithmetic.
// 9 is the squad scale (OLEFFECTS): the number of active members of the unit's own squad, asked of the game's
// own squad helper (0x1401D3990, the one vanilla Heart of a Leader, evility 51, calls).  Kinds 7/8 above are
// the defeated-unit counters.
.sc_above:
    cmp edx, 10
    je .sc_movement_cost
    cmp edx, 9
    je .sc_squad
    cmp edx, 8
    ja .sc_filter_check
.sc_defeated:
    mov r12, rcx
    movzx r8d, byte ptr [r12 + 0x2e32]        // this unit's team byte
    cmp r8d, 5
    jbe .sc_def_team
    xor r8d, r8d
.sc_def_team:
    lea rbx, [rip + evil_hostile]
    movzx r9d, byte ptr [rbx + r8]            // bit b set = this team is hostile to team b
    mov r10, 0x146a5f054
    xor ecx, ecx
    xor eax, eax
.sc_def_loop:
    cmp ecx, 6
    jae .sc_ret
    cmp edx, 8
    je .sc_def_add
    bt r9d, ecx
    jnc .sc_def_next
.sc_def_add:
    movzx r11d, word ptr [r10 + rcx*2]
    add eax, r11d
.sc_def_next:
    inc ecx
    jmp .sc_def_loop

// The squad scale: +0x30A1 is the unit's squad-assignment count gate and +0x30A0 its first/current squad id,
// the two fields vanilla Heart of a Leader reads before asking the same helper (Overlord's
// count_same_squad_units, 10_evility_runtime.c:820).  A unit with no squad assignment gets 0, exactly as
// Overlord's negative id does, so a row scaled by squad membership reads 0 outside a squad.
.sc_squad:
    xor eax, eax
    movzx r8d, byte ptr [rcx + 0x30a1]        // any squad assignment at all?
    test r8d, r8d
    jz .sc_ret
    movsx edx, byte ptr [rcx + 0x30a0]        // the squad id (signed; negative = none)
    test edx, edx
    js .sc_ret
    mov ecx, edx
    call 0x1401d3990                          // unit_stats_squads_squad_members: active member count
    jmp .sc_ret

// D5's dynamic unit movement counter, maintained by movement commit/undo and turn end.
// Negative values and records not on the map count as zero; this is not proven D4 panel distance.
.sc_movement_cost:
    call evil_brec
    test rax, rax
    jz .sc_ret
    movsx eax, word ptr [rax + 0x61c]
    test eax, eax
    jns .sc_ret
    xor eax, eax
    jmp .sc_ret

// CARRIERS2: filtered map counts.  Kinds 11..14 count *deployed* units (the same 256-entry battle-table
// walk, eligibility tests and "on the map" rule evil_near already applies for the map-wide counts), but
// keep only the candidates a filter admits, and the filter is the row's own argument (row dword 7, r8d on
// entry; one value per row, so a species that is several class ids is several rows, which add up exactly
// as every other multi-row evility does):
//   11 map_monster  any deployed unit whose class-kind byte is 11/12 (monster)  -- value unused
//   12 map_human    any deployed unit whose class-kind byte is 1/2 (human)      -- value unused
//   13 map_class    any deployed unit whose class/character id is the row's value
//   14 map_has      any deployed unit that has learned the evility in the row's value
// The subject itself is never counted (evil_near's own rule), so a holder that would also match the
// filter is not part of its own count.
.sc_filter_check:
    mov r12, rcx                      // unit
    mov dword ptr [rsp + 0x20], r8d   // the row's filter value (r8 is volatile: keep it before any call)
    cmp edx, 11
    je .sc_f_monster
    cmp edx, 12
    je .sc_f_human
    cmp edx, 13
    je .sc_f_class
    cmp edx, 14
    je .sc_f_has
    cmp edx, 15
    je .sc_f_squad
    cmp edx, 21
    je .sc_capped
    cmp edx, 22
    je .sc_hp
    cmp edx, 23
    je .sc_hp
    cmp edx, 24
    je .sc_f_class_ally
    cmp edx, 25
    je .sc_f_class_enemy
    cmp edx, 26
    je .sc_idle
    cmp edx, 27
    je .sc_geo
    cmp edx, 28
    je .sc_hk
    cmp edx, 20
    ja .sc_ret                        // 29 and up are not allocated
    // DRPGEVIL1c: 16..20 party_human / party_monster / party_male / party_female / party_weapon -- members of
    // the unit's own side on the map of that kind, the unit itself included (evil_party).
    sub edx, 15
    mov rcx, r12
    mov r8d, dword ptr [rsp + 0x20]
    call evil_party
    jmp .sc_ret
// EVILFX2: 21 party_capped -- living members of the unit's own side on the map, the unit itself included,
// capped at the row's filter value (Disgaea RPG: "the more living party members ... up to 5 characters").
// 0 when the unit is not on the map.
.sc_capped:
    mov rcx, r12
    call evil_brec
    test rax, rax
    jz .sc_ret
    mov rdi, r12
    mov rsi, rax
    mov edx, 1                        // allies
    mov ecx, 0xffff                   // the whole map
    xor r8d, r8d
    xor r10d, r10d
    call evil_near
    inc eax                           // the unit itself
    cmp eax, dword ptr [rsp + 0x20]
    jle .sc_ret
    mov eax, dword ptr [rsp + 0x20]
    jmp .sc_ret
// EVILFX2: 22 hp_pct / 23 hp_lost_pct -- the unit's hp as a whole percent of its maximum (0..100), with the
// arithmetic of the hp conditions (hp * 100 / max, truncated), or 100 minus it.  These are PERCENT scales:
// evil_scaled divides value * count by 100, so "up to +70 % the lower the HP" is value 70 per hp_lost_pct.
.sc_hp:
    mov ebx, edx
    xor eax, eax
    mov r8, qword ptr [r12 + 0x2cd8]  // max hp
    test r8, r8
    jle .sc_ret
    mov rax, qword ptr [r12 + 0x2cc8] // hp
    test rax, rax
    jns .sc_hp_pos
    xor eax, eax
.sc_hp_pos:
    cmp rax, r8
    jle .sc_hp_div
    mov rax, r8
.sc_hp_div:
    imul rax, rax, 100
    cqo
    idiv r8
    cmp ebx, 22
    je .sc_ret
    neg eax
    add eax, 100
    jmp .sc_ret
// EVILFX1: 15 map_squad -- deployed *allies* (same team byte) in the subject's own squad, the subject
// never counted (evil_near's rule).  D4's Evil Area count (Friends 840: FUN_1401ba0a0 counts other
// same-team battle units whose Evil Area list meets the holder's) mapped onto D5's squad, the system that
// replaced Evil Areas.  A subject outside any squad counts 0, as the `squad` scale does.
.sc_f_squad:
    xor eax, eax
    cmp byte ptr [r12 + 0x30a1], 0
    je .sc_ret
    movsx edx, byte ptr [r12 + 0x30a0]
    test edx, edx
    js .sc_ret
    mov dword ptr [rsp + 0x20], edx   // filter value: the subject's squad id
    mov rcx, r12
    call evil_brec
    test rax, rax
    jz .sc_ret                        // not on the map: no count
    mov rdi, r12
    mov rsi, rax
    mov edx, 1                        // relation: allies only
    mov ecx, 0xffff                   // radius: the whole map
    mov r8d, dword ptr [rsp + 0x20]
    mov r10d, 5                       // filter kind 5: same squad
    call evil_near
    jmp .sc_ret
// EVILCAP1: 24 map_class_ally / 25 map_class_enemy -- map_class (filter kind 2, the row's class id) with the
// relation of the map-wide counts instead of "any": allies are the subject's own team byte, enemies a team the
// hostile-team table marks.  Subject never counted; 0 off the map.
.sc_f_class_ally:
    mov dword ptr [rsp + 0x28], 1     // relation for evil_near
    jmp .sc_f_class_rel
.sc_f_class_enemy:
    mov dword ptr [rsp + 0x28], 2
.sc_f_class_rel:
    mov rcx, r12
    call evil_brec
    test rax, rax
    jz .sc_ret                        // not on the map: no count
    mov rdi, r12
    mov rsi, rax
    mov edx, dword ptr [rsp + 0x28]
    mov ecx, 0xffff                   // radius: the whole map
    mov r8d, dword ptr [rsp + 0x20]
    mov r10d, 2                       // filter kind 2: class/character id
    call evil_near
    jmp .sc_ret
// D4SIG2: 26 idle_turns -- D5's own idle-turn counter, the byte SR+1 of the unit's stat record
// SR = 0x141067DC8 + (unit +0x4348) * 0xE98.  turn_t3_per_unit_end_turn (0x140159F50, called from
// turn_t1_per_unit_hp_sp for team 0) raises it by one at a round edge (stops at 10) when the unit's battle record
// +0x61C (movement) is 0 and three more blocker bytes are clear, else zeroes it; FUN_140157CB0 reads it (evility
// 123's menu test).  0 when the unit has no stat record.
.sc_idle:
    xor eax, eax
    mov ecx, dword ptr [r12 + 0x4348]
    cmp ecx, 0x28a
    jae .sc_ret
    imul rcx, rcx, 0xe98
    mov rdx, 0x141067dc8
    movzx eax, byte ptr [rcx + rdx + 1]
    jmp .sc_ret
// DD2EVIL3: 28 holder_kills -- the sum of the kill_counter counts (stat record +0x5D8, raised by wrap_atkcount) of every OTHER deployed unit of the
// subject's team that has learned the evility in the row's filter ([rsp + 0x20], saved at .sc_filter_check).  Disgaea D2 Plume 570: 0xF6290 walks
// the 0xA1 battle entries, skips the unit itself, keeps the same team byte, skips defeated entries (0x31A1C == 2), objects (0x1035B0) and carried
// ones, and 0xFA6CC adds each holder's own +0x19CE.  The walk and tests are evil_team_sum's (active byte +0x2E8, not carried +0x2EE < 0, a stat
// record, HP > 0).  0 when the subject is not on the map.  The sum stays below 2^31: each count is at most 0x270F over at most 255 units.
.sc_hk:
    xor eax, eax
    mov rcx, r12
    call evil_brec
    test rax, rax
    jz .sc_ret                        // the subject is not on the map
    mov r13, rax                      // the subject's battle record
    movzx ebp, byte ptr [r12 + 0x2e32]// the subject's team
    mov rsi, 0x141ba33b0              // scan cursor over the 256-entry battle table
    xor edi, edi
    xor ebx, ebx                      // the sum
.sc_hk_loop:
    cmp rsi, r13
    je .sc_hk_next                    // the subject itself is never counted
    cmp byte ptr [rsi + 0x2e8], 0
    je .sc_hk_next                    // not on the map
    cmp word ptr [rsi + 0x2ee], 0
    jge .sc_hk_next                   // carried
    mov rcx, qword ptr [rsi + 0x240]
    test rcx, rcx
    jz .sc_hk_next
    cmp dword ptr [rcx + 0x4348], 0x28a
    jae .sc_hk_next                   // no stat record
    cmp qword ptr [rcx + 0x2cc8], 0
    jle .sc_hk_next                   // defeated
    movzx eax, byte ptr [rcx + 0x2e32]
    cmp eax, ebp
    jne .sc_hk_next                   // another team
    mov edx, dword ptr [rsp + 0x20]   // the holder's evility id
    call evil_has_id
    test eax, eax
    jz .sc_hk_next
    mov rcx, qword ptr [rsi + 0x240]
    mov eax, dword ptr [rcx + 0x4348]
    imul rax, rax, 0xe98
    mov rdx, 0x1410683a0              // stat record 0 + 0x5D8: the count
    movzx eax, word ptr [rax + rdx]
    add ebx, eax
.sc_hk_next:
    add rsi, 4704
    inc edi
    cmp edi, 256
    jl .sc_hk_loop
    mov eax, ebx
    jmp .sc_ret
// D4SIG7: 27 geo_colours -- the number of DISTINCT colours among the Geo Symbols on the map (D4 evility 129 Geo Energy,
// "Stats increased by 10% per Geo Block color on map").  D4 FUN_1401BA0A0 walks its battle table (DAT_141184AA0, 2000-byte records): for each active
// unit (+0x294 != 0, D5 +0x2E8) whose class family (+0x1806) is 0x1E1 and which is alive (FUN_140108df0 != 2: hp +0xD10 > 0) it
// collects the raw colour value of the record (+0x25A) into a set and counts the set.  D5's family test is the same one
// the Geo Symbol name switch makes (0x1402ACBB0: unit +0x2E04 / 10 == 481 = chars 4810..4819) and its colour is unit +0x2E2C
// (placement +0x248 stored by 0x1404D29C0 / 0x1405247D0, rewritten by script_cmd_unit_geo_change 0x14016B0E0 via 0x140157150).
// D4 returns 0 when the holder is off the map or carried; a candidate is not tested for carrying.  The bitmap is 256 bits
// (the colour is a byte) at [rsp + 0x38] of evil_scale's 0x58-byte frame (it was 0x38); no call is made.
.sc_geo:
    xor eax, eax
    mov rcx, r12
    call evil_brec
    test rax, rax
    jz .sc_ret                        // the holder is not on the map: 0
    cmp word ptr [rax + 0x2ee], 0
    jge .sc_geo_zero                  // the holder is carried: 0
    mov eax, dword ptr [r12 + 0x2e04]
    sub eax, 4810
    cmp eax, 9
    jbe .sc_geo_zero                  // the holder is itself a Geo Symbol: 0 (D4's first test)
    xor eax, eax
    mov qword ptr [rsp + 0x38], rax
    mov qword ptr [rsp + 0x40], rax
    mov qword ptr [rsp + 0x48], rax
    mov qword ptr [rsp + 0x50], rax
    mov r9, 0x141ba33b0               // scan cursor over the 256-entry battle table
    xor r11d, r11d
.sc_geo_loop:
    cmp byte ptr [r9 + 0x2e8], 0
    je .sc_geo_next                   // not on the map
    mov rdi, qword ptr [r9 + 0x240]
    test rdi, rdi
    jz .sc_geo_next
    mov ecx, dword ptr [rdi + 0x2e04]
    sub ecx, 4810
    cmp ecx, 9
    ja .sc_geo_next                   // not a Geo Symbol family unit
    cmp qword ptr [rdi + 0x2cc8], 0
    jle .sc_geo_next                  // destroyed
    movzx ecx, byte ptr [rdi + 0x2e2c]
    bts qword ptr [rsp + 0x38], rcx   // a new colour: CF = 0
    jc .sc_geo_next
    inc eax
.sc_geo_next:
    add r9, 4704
    inc r11d
    cmp r11d, 256
    jl .sc_geo_loop
    jmp .sc_ret
.sc_geo_zero:
    xor eax, eax
    jmp .sc_ret
.sc_f_monster:
    mov edx, 3
    jmp .sc_f_go
.sc_f_human:
    mov edx, 4
    jmp .sc_f_go
.sc_f_class:
    mov edx, 2
    jmp .sc_f_go
.sc_f_has:
    mov edx, 1
.sc_f_go:
    mov dword ptr [rsp + 0x24], edx   // filter kind for evil_near
    mov rcx, r12
    call evil_brec
    test rax, rax
    jz .sc_ret                        // not on the map: no count
    mov rdi, r12
    mov rsi, rax
    xor edx, edx                      // relation: any unit
    mov ecx, 0xffff                   // radius: the whole map
    mov r8d, dword ptr [rsp + 0x20]
    mov r10d, dword ptr [rsp + 0x24]
    call evil_near
    jmp .sc_ret

// evil_scaled(rcx = unit record, edx = scale kind, r8d = the row's filter, r9d = the effect's value)
//   -> eax = value * count.  For the percent scales (22 hp_pct, 23 hp_lost_pct) the count is a percent and
// the product is divided by 100, truncated toward zero.  Every scaled effect goes through here (EVILFX2).
evil_scaled:
    push rbx
    push rbp
    sub rsp, 0x28
    mov ebx, edx
    mov ebp, r9d
    call evil_scale
    imul eax, ebp
    cmp ebx, 22
    jb .sd_ret
    cmp ebx, 23
    ja .sd_ret
    cdq
    mov ecx, 100
    idiv ecx
.sd_ret:
    add rsp, 0x28
    pop rbp
    pop rbx
    ret

// evil_statmod(rcx = unit record, edx = stat 2..7 (ATK DEF INT RES HIT SPD)) -> eax = the signed power of the
// stat-change status on the unit (> 0 a buff, < 0 a debuff), 0 when none is active.  Status slots 7..12 are
// the six stat changes: unit_stats_evil_status_effects (0x1401B97D0) adds the signed byte at stat record
// +0x536 + slot to aggregate[slot - 5] while the byte at +0x4E9 + slot is non-zero.  Leaf; clobbers rax, r8, r9.
evil_statmod:
    xor eax, eax
    test rcx, rcx
    jz .sm_ret
    mov r8d, dword ptr [rcx + 0x4348]
    cmp r8d, 0x28a
    jae .sm_ret
    cmp edx, 2
    jb .sm_ret
    cmp edx, 7
    ja .sm_ret
    imul r8, r8, 3736
    mov r9, 0x141067dc8
    add r9, r8
    mov edx, edx
    cmp byte ptr [r9 + rdx + 1262], 0
    je .sm_ret
    movsx eax, byte ptr [r9 + rdx + 1339]
.sm_ret:
    ret

// evil_status_set(rcx = unit record, edx = status index) -> eax = 1 if that status is on the unit
// (stat record +1257 + index is the status's remaining turns; > 0 means active)
// evil_type(rcx = unit) -> eax normalized type, respecting learned evility 4301's gender swap.
// Byte +0x2E25: 1 human male, 2 human female, 11 monster male, 12 monster female.
// Mirrors the pinned class-kind getter's semantic rule, without external calls.
evil_type:
    xor eax, eax
    test rcx, rcx
    jz .t_ret
    movzx eax, byte ptr [rcx + 0x2e25]
    mov r8d, dword ptr [rcx + 0x3030]
    cmp r8d, 64
    jbe .t_count
    mov r8d, 64
.t_count:
    xor edx, edx
.t_loop:
    cmp edx, r8d
    jae .t_ret
    cmp dword ptr [rcx + rdx*4 + 0x2f30], 4301
    je .t_swap
    inc edx
    jmp .t_loop
.t_swap:
    cmp eax, 1
    je .t_inc
    cmp eax, 11
    je .t_inc
    cmp eax, 2
    je .t_dec
    cmp eax, 12
    jne .t_ret
.t_dec:
    dec eax
    ret
.t_inc:
    inc eax
.t_ret:
    ret

evil_status_set:
    xor eax, eax
    test rcx, rcx
    jz .s_ret
    mov r8d, dword ptr [rcx + 0x4348]
    cmp r8d, 0x28a
    jae .s_ret
    cmp edx, 77
    jae .s_ret
    imul r8, r8, 3736
    mov r9, 0x141067dc8
    add r9, r8
    cmp byte ptr [r9 + 1257 + rdx], 0
    jle .s_ret
    mov eax, 1
.s_ret:
    ret

// evil_fdir(rcx = a battle slot, rdx = action context) -> eax = the direction recorded on that slot's
// target entry (entry +36: 0 the attacker stands in front of the target, 1 side, 2 behind), or -1 when no
// entry carries that slot.
// The target entries live at X + 4888, 608 bytes each, with the entry count at X + 160536; entry +0 holds
// the *target's* battle slot (battle record +0x2F4).  Leaf; clobbers only the volatile registers.
evil_fdir:
    movsx eax, word ptr [rdx + 160536]      // target entry count
    xor r8d, r8d
.fd_loop:
    cmp r8d, eax
    jge .fd_none
    mov r9, r8
    imul r9, r9, 608
    lea r10, [rdx + r9 + 4888]
    movzx r9d, word ptr [r10]
    cmp r9d, ecx
    je .fd_found
    inc r8d
    jmp .fd_loop
.fd_found:
    mov eax, dword ptr [r10 + 36]
    ret
.fd_none:
    mov eax, -1
    ret

// evil_eval(rcx = row, rsi = subject unit record, rdx = other battle record or 0, r8 = action context X or 0,
//           r9d = status index being rolled (status-chance family) ) -> eax = 1 if the row applies
// Every condition of the row must hold.  For an aura row (family bit 64) the row's own id is *not* looked
// for on the subject: the aura acts on the recipient, and its conditions name the provider instead.
// Preserves all nonvolatile registers, including subject RSI when a condition needs scratch RSI.
evil_eval:
    push rdi
    push rsi
    push rbx
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x48
    mov r12, rcx                      // row
    mov r15, rsi                      // subject unit
    mov r13, rdx                      // other battle record
    mov rbp, r8                       // action context
    mov ebx, r9d                      // status index
    xor eax, eax
    test r15, r15
    jz .e_ret
    mov eax, dword ptr [r12 + 4]
    test eax, 64
    jnz .e_start                      // aura: the provider has the id, not the recipient
    test dword ptr [r12 + 24], 1      // skill row: the action's skill id is the id to match
    jnz .e_skill
// --- is the row's own id present? ---
    mov r11d, dword ptr [r15 + 0x3030]
    test r11d, r11d
    jle .e_ret
    mov r10d, dword ptr [r12]
    xor r9d, r9d
.e_search:
    cmp r9d, r11d
    jge .e_ret
    lea eax, [r9d + r11d]
    shr eax, 1
    mov edx, dword ptr [r15 + 0x2f30 + rax*4]
    cmp edx, r10d
    je .e_start
    jl .e_search_lower
    mov r11d, eax
    jmp .e_search
.e_search_lower:
    lea r9d, [eax + 1]
    jmp .e_search
.e_skill:                            // the row's id is the action's skill id, not a learned evility
    test rbp, rbp
    jz .e_ret
    mov eax, dword ptr [rbp + 0x27670]   // skill id of the action, 0 for a normal attack
    test eax, eax
    jz .e_ret
    cmp eax, dword ptr [r12]
    jne .e_ret
    jmp .e_start
.e_start:
    cmp dword ptr [r12 + 12], 0
    je .e_ok                         // unconditional hot path never scans the map
    mov qword ptr [rsp + 0x20], 0    // subject battle record, looked up lazily by near kinds
    mov eax, dword ptr [r12 + 8]
    lea rcx, [rip + evil_cond]
    add rcx, rax
    mov qword ptr [rsp + 0x28], rcx   // condition cursor
    mov eax, dword ptr [r12 + 12]
    mov dword ptr [rsp + 0x30], eax   // conditions left
.e_loop:
    mov eax, dword ptr [rsp + 0x30]
    test eax, eax
    jz .e_ok
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10]
    cmp eax, 1
    je .c_has
    cmp eax, 2
    je .c_char
    cmp eax, 3
    je .c_count
    cmp eax, 4
    je .c_hp
    cmp eax, 5
    je .c_hp
    cmp eax, 6
    je .c_level
    cmp eax, 7
    je .c_tclass
    cmp eax, 8
    je .c_allyadj
    cmp eax, 9
    je .c_enemyadj
    cmp eax, 10
    je .c_allymap
    cmp eax, 11
    je .c_enemymap
    cmp eax, 12
    je .c_unitmap
    cmp eax, 13
    je .c_anormal
    cmp eax, 14
    je .c_askill
    cmp eax, 15
    je .c_aphys
    cmp eax, 16
    je .c_amagic
    cmp eax, 17
    je .c_element
    cmp eax, 18
    je .c_weapon
    cmp eax, 19
    je .c_tstatus
    cmp eax, 20
    je .c_sstatus
    cmp eax, 21
    je .c_turn
    cmp eax, 22
    je .c_fdir
    cmp eax, 24
    je .c_rng
    cmp eax, 25
    je .c_sclass
    cmp eax, 26
    je .c_near
    cmp eax, 27
    je .c_ofly
    cmp eax, 28
    je .c_sfly
    cmp eax, 29
    je .c_ohigher
    cmp eax, 30
    je .c_olower
    cmp eax, 39
    je .c_ohp
    cmp eax, 40
    je .c_ohp
    cmp eax, 41
    je .c_eany
    cmp eax, 42
    je .c_tcount
    cmp eax, 43
    je .c_tcount
    cmp eax, 44
    je .c_nearchar
    cmp eax, 45
    je .c_oadj
    cmp eax, 46
    je .c_tslot
    cmp eax, 47
    je .c_defend
    cmp eax, 48
    je .c_hpabs
    cmp eax, 49
    je .c_maphas
    cmp eax, 54
    je .c_partymin
    cmp eax, 55
    je .c_turnmax
    cmp eax, 56
    je .c_sbuff
    cmp eax, 57
    je .c_sbuff
    cmp eax, 58
    je .c_mapstat
    cmp eax, 59
    je .c_mapstat
    cmp eax, 60
    je .c_enemymax
    cmp eax, 61
    je .c_oweapon
    cmp eax, 62
    je .c_siderank
    cmp eax, 63
    je .c_siderank
    cmp eax, 64                      // provider_buff qualifies the near_has before it (.c_near reads it)
    je .e_next
    cmp eax, 65
    je .c_notmoved
    cmp eax, 66
    je .c_magichange
    cmp eax, 67
    je .c_magichange
    cmp eax, 68
    je .c_magichange
    cmp eax, 69
    je .c_selfpot
    cmp eax, 70
    je .c_partydist
    cmp eax, 71
    je .c_maphp
    cmp eax, 50                      // DRPGEVIL1b: 50..53 qualify the provider of the near_has just before
    jb .c_not_prov                   // them (.c_near reads them); on their own turn they hold
    cmp eax, 53
    jbe .e_next
.c_not_prov:
    cmp eax, 31
    jb .e_ret
    cmp eax, 38
    jbe .c_type
    jmp .e_ret                       // unknown condition: refuse the row
// ------------------------------------------------------------------------------------------ conditions
.c_has:                              // another evility is learned as well
    mov r10, qword ptr [rsp + 0x28]
    movzx r8d, word ptr [r10 + 2]
    mov r11d, dword ptr [r15 + 0x3030]
    xor ecx, ecx
.c_hs:
    cmp ecx, r11d
    jge .e_ret
    cmp dword ptr [r15 + 0x2f30 + rcx*4], r8d
    je .e_next
    inc ecx
    jmp .c_hs
.c_char:                             // this character only
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp dword ptr [r15 + 0x2e04], ecx
    je .e_next
    jmp .e_ret
.c_count:                            // at least the argument's number of learned evilities
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp dword ptr [r15 + 0x3030], ecx
    jge .e_next
    jmp .e_ret
.c_hp:                               // hp percent threshold: kind 4 below, 5 at least
    mov rax, qword ptr [r15 + 0x2cc8]
    mov r8, qword ptr [r15 + 0x2cd8]
    test r8, r8
    jle .e_ret
    mov rcx, 100
    imul rax, rcx
    cqo
    idiv r8
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp word ptr [r10], 4
    jne .c_hp_at
    cmp eax, ecx
    jl .e_next
    jmp .e_ret
.c_hp_at:
    cmp eax, ecx
    jge .e_next
    jmp .e_ret
.c_hpabs:                            // kind 48: hp <= floor(max hp * a / 100), D4's own arithmetic.
                                    // D4's evility getter (FUN_14010de70) scales the *maximum* hp by the
                                    // evility's second parameter (a pct, truncated by the signed /100 the
                                    // decompiler shows) and then refuses the value when that scaled number
                                    // is below min(current hp, max): i.e. the effect is active at and
                                    // below the threshold, so 250/1000 is inside a 25 gate where kind 4
                                    // (integer hp percent, strictly below) puts it outside.  Comparing
                                    // hp*100 <= max*a is exactly hp <= floor(max*a/100) for integer hp,
                                    // without needing the truncating division.
    mov rax, qword ptr [r15 + 0x2cc8]
    mov r8, qword ptr [r15 + 0x2cd8]
    test r8, r8
    jle .e_ret
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    mov r9, 100
    imul rax, r9
    imul r8, rcx
    cmp rax, r8
    jle .e_next
    jmp .e_ret
.c_level:
    movsx eax, word ptr [r15 + 0x2dfc]
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp eax, ecx
    jge .e_next
    jmp .e_ret
.c_tclass:                           // the other side's class: the class id (char.dat id) of the other
                                    // unit, i.e. unit record +0x2E04 (see d5lib/savegame.py).  The battle
                                    // record's +0x2F4 this used to read is the unit's *slot* (the target
                                    // entries of the action context are addressed by exactly that slot),
                                    // not a class; the old behaviour is available as `other_slot` (44).
    test r13, r13
    jz .e_ret
    mov rax, qword ptr [r13 + 0x240]
    test rax, rax
    jz .e_ret
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp dword ptr [rax + 0x2e04], ecx
    je .e_next
    jmp .e_ret
.c_tslot:                            // the other side's battle slot (battle record +0x2F4, short)
    test r13, r13
    jz .e_ret
    movsx eax, word ptr [r13 + 0x2f4]
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp eax, ecx
    je .e_next
    jmp .e_ret
.c_defend:                           // the unit is in the game's own "defending" state: exactly the gate
                                    // D5's own Advance Guard (evility 0x480, D5 1152) is tested with in
                                    // damage_damage_reduction_rules (0x1401FB2E0), i.e.
                                    // path_query_path_unit_stack_count(its battle record) != 0.
                                    // That helper (0x140157870) counts the battle record's action-stack
                                    // entries (entries at +0xBD0, stride 0x14, i32 kind at +0; count byte
                                    // +0x1080) whose kind is 4, and on the count-0 path returns true for the
                                    // record's own "action in progress" state (team query + +0x11C0 /
                                    // +0x11E0 / stat-record byte +0xE82).  Calling it, rather than
                                    // reimplementing that fallback, is what makes the condition mean the
                                    // same thing the game's 1152 test means.
    mov rcx, r15
    call evil_brec
    test rax, rax
    jz .e_ret                        // not on the map: never defending
    mov rcx, rax
    call 0x140157870
    test eax, eax
    jnz .e_next
    jmp .e_ret
.c_allyadj:                          // at least a allies within one panel
    mov edx, 1
    jmp .c_near_count
.c_enemyadj:
    mov edx, 2
    jmp .c_near_count
.c_allymap:
    mov edx, 1
    jmp .c_map_count
.c_enemymap:
    mov edx, 2
    jmp .c_map_count
.c_unitmap:
    xor edx, edx
.c_map_count:
    mov ecx, 0xffff
    jmp .c_count_near
.c_near_count:
    mov ecx, 1
.c_count_near:
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10 + 2]     // how many
    mov dword ptr [rsp + 0x38], eax
    mov dword ptr [rsp + 0x40], edx   // the relation evil_near wants
    mov dword ptr [rsp + 0x3c], ecx   // radius survives battle lookup
    mov rcx, r15
    call evil_brec
    mov qword ptr [rsp + 0x20], rax
    mov rdi, r15
    mov rsi, rax
    mov edx, dword ptr [rsp + 0x40]
    mov ecx, dword ptr [rsp + 0x3c]
    xor r8d, r8d
    xor r10d, r10d
    call evil_near
    cmp eax, dword ptr [rsp + 0x38]
    jge .e_next
    jmp .e_ret
.c_maphas:                           // kind 49 (CARRIERS2): at least a deployed units of relation b have
                                    // learned evility c.  near_has (26) is the existential form ("at least
                                    // one within N panels"); this is the counted form D4's "if seven
                                    // allies with Prism Emblem are dispatched" needs.  The subject is
                                    // never counted, by evil_near's own rule.
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10 + 2]     // a: how many
    mov dword ptr [rsp + 0x38], eax
    movzx eax, word ptr [r10 + 4]     // b: relation (0 any, 1 ally, 2 enemy)
    mov dword ptr [rsp + 0x3c], eax
    movzx r8d, word ptr [r10 + 6]     // c: the evility id
    test r8d, r8d
    jz .e_ret
    mov dword ptr [rsp + 0x40], r8d
    mov rcx, r15
    call evil_brec
    test rax, rax
    jz .e_ret
    mov rdi, r15
    mov rsi, rax
    mov ecx, 0xffff                   // radius: the whole map
    mov edx, dword ptr [rsp + 0x3c]
    mov r8d, dword ptr [rsp + 0x40]
    mov r10d, 1
    call evil_near
    cmp eax, dword ptr [rsp + 0x38]
    jge .e_next
    jmp .e_ret
.c_anormal:                          // a normal attack: no skill id in the action context
    test rbp, rbp
    jz .e_ret
    cmp dword ptr [rbp + 0x27670], 0
    je .e_next
    jmp .e_ret
.c_askill:
    test rbp, rbp
    jz .e_ret
    cmp dword ptr [rbp + 0x27670], 0
    jne .e_next
    jmp .e_ret
.c_aphys:                            // skill effect type 2, or a normal attack (no skill row)
    test rbp, rbp
    jz .e_ret
    mov rax, qword ptr [rbp + 0x27678]
    test rax, rax
    jz .e_next
    cmp byte ptr [rax + 1014], 2
    je .e_next
    jmp .e_ret
.c_amagic:
    test rbp, rbp
    jz .e_ret
    mov rax, qword ptr [rbp + 0x27678]
    test rax, rax
    jz .e_ret
    cmp byte ptr [rax + 1014], 3
    je .e_next
    jmp .e_ret
.c_element:                          // attack element 0 none, 1 fire, 2 wind, 3 ice, 4 star
    test rbp, rbp
    jz .e_ret
    movzx eax, byte ptr [rbp + 0x276bc]
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp eax, ecx
    je .e_next
    jmp .e_ret
.c_weapon:                           // an equipped weapon has this category (slot 0, else slot 1)
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp dword ptr [r15 + 312], 0
    je .c_w1
    movzx eax, byte ptr [r15 + 342]
    cmp eax, ecx
    je .e_next
.c_w1:
    cmp dword ptr [r15 + 912], 0
    je .e_ret
    movzx eax, byte ptr [r15 + 942]
    cmp eax, ecx
    je .e_next
    jmp .e_ret
.c_tstatus:                          // the other side carries this status
    test r13, r13
    jz .e_ret
    mov rcx, qword ptr [r13 + 0x240]
    mov r10, qword ptr [rsp + 0x28]
    movzx edx, word ptr [r10 + 2]
    call evil_status_set
    test eax, eax
    jnz .e_next
    jmp .e_ret
.c_sstatus:                          // this unit carries this status
    mov rcx, r15
    mov r10, qword ptr [rsp + 0x28]
    movzx edx, word ptr [r10 + 2]
    call evil_status_set
    test eax, eax
    jnz .e_next
    jmp .e_ret
.c_partymin:                         // kind 54 (DRPGEVIL1c): at least a members of the unit's own side on the map
                                    // are of kind b (1 human, 2 monster, 3 male, 4 female, 5 weapon category c),
                                    // the unit itself included
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10 + 2]
    mov dword ptr [rsp + 0x38], eax
    movzx edx, word ptr [r10 + 4]
    movzx r8d, word ptr [r10 + 6]
    mov rcx, r15
    call evil_party
    cmp eax, dword ptr [rsp + 0x38]
    jge .e_next
    jmp .e_ret
.c_sbuff:                            // kinds 56 / 57 (EVILFX2): this unit is under a stat buff / debuff of stat a
    mov r10, qword ptr [rsp + 0x28]
    movzx edx, word ptr [r10 + 2]
    mov rcx, r15
    call evil_statmod
    mov r10, qword ptr [rsp + 0x28]
    cmp word ptr [r10], 56
    jne .c_sdebuff
    test eax, eax
    jg .e_next
    jmp .e_ret
.c_sdebuff:
    test eax, eax
    jl .e_next
    jmp .e_ret
.c_mapstat:                          // kinds 58 / 59 (EVILFX2): at least a units of relation b on the map are
                                    // under a stat buff / debuff of stat c (evil_near filter kind 10)
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10 + 2]
    mov dword ptr [rsp + 0x38], eax
    movzx eax, word ptr [r10 + 4]
    mov dword ptr [rsp + 0x3c], eax
    movzx eax, word ptr [r10 + 6]
    and eax, 255
    cmp word ptr [r10], 59
    jne .c_mapstat_go
    or eax, 0x100
.c_mapstat_go:
    mov dword ptr [rsp + 0x40], eax
    mov rcx, r15
    call evil_brec
    test rax, rax
    jz .e_ret
    mov rdi, r15
    mov rsi, rax
    mov ecx, 0xffff
    mov edx, dword ptr [rsp + 0x3c]
    mov r8d, dword ptr [rsp + 0x40]
    mov r10d, 10
    call evil_near
    cmp eax, dword ptr [rsp + 0x38]
    jge .e_next
    jmp .e_ret
.c_maphp:                            // kind 71 (DRPGSIG1): at least a units of relation b on the map are alive with HP at or below
                                    // c percent of their maximum (evil_near filter kind 13); false while the unit is off the map
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10 + 2]
    mov dword ptr [rsp + 0x38], eax
    movzx eax, word ptr [r10 + 4]
    mov dword ptr [rsp + 0x3c], eax
    movzx eax, word ptr [r10 + 6]
    mov dword ptr [rsp + 0x40], eax
    mov rcx, r15
    call evil_brec
    test rax, rax
    jz .e_ret
    mov rdi, r15
    mov rsi, rax
    mov ecx, 0xffff
    mov edx, dword ptr [rsp + 0x3c]
    mov r8d, dword ptr [rsp + 0x40]
    mov r10d, 13
    call evil_near
    cmp eax, dword ptr [rsp + 0x38]
    jge .e_next
    jmp .e_ret
.c_siderank:                         // kinds 62 / 63 (EVILFX2): no ally on the map has a strictly higher / lower
                                    // stat a than this unit (the unit has the highest / lowest on its side; ties
                                    // all qualify); false off the map
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10 + 2]
    mov dword ptr [rsp + 0x40], eax
    mov eax, 11
    cmp word ptr [r10], 62
    je .c_siderank_go
    mov eax, 12
.c_siderank_go:
    mov dword ptr [rsp + 0x3c], eax
    mov rcx, r15
    call evil_brec
    test rax, rax
    jz .e_ret
    mov rdi, r15
    mov rsi, rax
    mov edx, 1
    mov ecx, 0xffff
    mov r8d, dword ptr [rsp + 0x40]
    mov r10d, dword ptr [rsp + 0x3c]
    call evil_near
    test eax, eax
    jz .e_next
    jmp .e_ret
.c_selfpot:                          // kind 69 (DRPGPARTY1): this unit's registered potential type is in the mask a
                                    // (bit t-1 = type t, 1..6).  A class id outside the registry, or above u16, has
                                    // no type: false.
    mov ecx, dword ptr [r15 + 0x2e04]
    cmp ecx, 0xffff
    ja .e_ret
    call evil_classinfo
    shr eax, 8                       // potential type, 0 = none
    jz .e_ret
    cmp eax, 6
    ja .e_ret
    dec eax
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    bt ecx, eax
    jc .e_next
    jmp .e_ret
.c_partydist:                        // kind 70 (DRPGPARTY1): every member of this unit's side on the map (itself
                                    // included) has a registered favourite weapon and no two share one
    mov rcx, r15
    call evil_party_distinct
    test eax, eax
    jnz .e_next
    jmp .e_ret
.c_notmoved:                         // kind 65 (EVILFX3): the unit has not moved -- its panels-moved counter (battle
                                    // record +0x61C, the word D5's own Assault Attack 1020 multiplies by in
                                    // damage_damage_multiplier_rules and carry_throw_unit_idle tests for
                                    // Cool and Calm 62) is 0.  False off the map.
    mov rcx, r15
    call evil_brec
    test rax, rax
    jz .e_ret
    cmp word ptr [rax + 0x61c], 0
    je .e_next
    jmp .e_ret
.c_magichange:                       // kinds 66..68 (EVILCAP1): D5's own Magichange state in the unit's stat
                                    // record SR = 0x141067DC8 + (unit +0x4348) * 0xE98 (no record: false).
                                    // 66: SR+0x4E2 != 0, the unit is a Magichange weapon (FUN_140605E30 sets it,
                                    //     FUN_14015F030 clears it).  67: a weapon slot s (0/1) has a participant,
                                    //     SR+0x4B8+0x10*s != 0 (cmdmenu_preds_p_15cfe0).  68: such a slot's
                                    //     remaining-turn byte SR+0x4E0+s equals a (turn_h13 ends it at 1).
    mov ecx, dword ptr [r15 + 0x4348]
    cmp ecx, 0x28a
    jae .e_ret
    imul rcx, rcx, 0xe98
    mov rdx, 0x141067dc8
    add rcx, rdx
    cmp eax, 66
    jne .c_mc_host
    cmp byte ptr [rcx + 0x4e2], 0
    jne .e_next
    jmp .e_ret
.c_mc_host:
    mov r10, qword ptr [rsp + 0x28]
    movzx r8d, word ptr [r10 + 2]     // turns wanted (kind 68)
    xor edx, edx                      // slot
.c_mc_slot:
    mov r9, rdx
    shl r9, 4
    cmp qword ptr [rcx + r9 + 0x4b8], 0
    je .c_mc_skip
    cmp eax, 67
    je .e_next
    movzx r9d, byte ptr [rcx + rdx + 0x4e0]
    cmp r9d, r8d
    je .e_next
.c_mc_skip:
    inc edx
    cmp edx, 2
    jb .c_mc_slot
    jmp .e_ret
.c_enemymax:                         // kind 60 (EVILFX2): at most a enemies on the map; false off the map
    mov r10, qword ptr [rsp + 0x28]
    movzx eax, word ptr [r10 + 2]
    mov dword ptr [rsp + 0x38], eax
    mov rcx, r15
    call evil_brec
    test rax, rax
    jz .e_ret
    mov rdi, r15
    mov rsi, rax
    mov edx, 2
    mov ecx, 0xffff
    xor r8d, r8d
    xor r10d, r10d
    call evil_near
    cmp eax, dword ptr [rsp + 0x38]
    jle .e_next
    jmp .e_ret
.c_oweapon:                          // kind 61 (EVILFX2): the other side has an equipped weapon of category a
    test r13, r13
    jz .e_ret
    mov rax, qword ptr [r13 + 0x240]
    test rax, rax
    jz .e_ret
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp dword ptr [rax + 312], 0
    je .c_ow1
    movzx edx, byte ptr [rax + 342]
    cmp edx, ecx
    je .e_next
.c_ow1:
    cmp dword ptr [rax + 912], 0
    je .e_ret
    movzx edx, byte ptr [rax + 942]
    cmp edx, ecx
    je .e_next
    jmp .e_ret
.c_turnmax:                          // kind 55 (DRPGEVIL1c): the battle round counter is at most a
    mov rax, 0x145574aa8
    movsx eax, word ptr [rax]
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp eax, ecx
    jle .e_next
    jmp .e_ret
.c_turn:                             // the battle round counter
    mov rax, 0x145574aa8
    movsx eax, word ptr [rax]
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp eax, ecx
    jge .e_next
    jmp .e_ret
.c_fdir:                            // where the attacker stands relative to this target's facing,
                                    // as the action context computed it: target entry +36
                                    // (0 front, 1 side, 2 behind)
                                    // The entry is addressed by the *target's* battle slot, so the side to
                                    // read depends on which side the family acts for: a `taken` row's subject
                                    // IS the action target, a `dealt` row's subject is the attacker and the
                                    // target is the other side.  Try the other side first -- that is the
                                    // target for every row that carries an attacker and a defender -- and fall
                                    // back to the subject's own battle slot, which is what a `taken` row
                                    // needs (the previous code only ever tried the other side, so it never
                                    // matched on a `taken` row).
    test rbp, rbp
    jz .e_ret
    test r13, r13
    jz .c_fd_self
    movsx ecx, word ptr [r13 + 756]   // the other side's own slot (battle record +0x2F4)
    mov rdx, rbp
    call evil_fdir
    cmp eax, -1
    jne .c_fd_got
.c_fd_self:
    mov rcx, r15
    call evil_brec                    // the subject's battle record (0 when it is not on the map)
    test rax, rax
    jz .e_ret
    movsx ecx, word ptr [rax + 0x2f4]
    mov rdx, rbp
    call evil_fdir
    cmp eax, -1
    je .e_ret
.c_fd_got:
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp eax, ecx
    je .e_next
    jmp .e_ret
.c_rng:                              // one game RNG draw: success when draw(100) < the percent
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    mov qword ptr [rsp + 0x38], rcx
    mov ecx, 100
    call 0x140136660                 // game_rng_draw; fixed frame already supplies home space
    mov rcx, qword ptr [rsp + 0x38]
    cmp rax, rcx
    jb .e_next
    jmp .e_ret
.c_sclass:                           // the ailment being rolled is this status index
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp ebx, ecx
    je .e_next
    jmp .e_ret
.c_near:                             // at least one unit of a relation within b panels has evility c
    mov r10, qword ptr [rsp + 0x28]
    movzx edx, word ptr [r10 + 2]     // relation
    movzx ecx, word ptr [r10 + 4]     // radius
    movzx r8d, word ptr [r10 + 6]     // evility id
    test ecx, ecx
    jnz .c_near_go
    mov ecx, 1                        // a provider must be adjacent at least
.c_near_go:
    mov rcx, r15
    call evil_brec
    mov qword ptr [rsp + 0x20], rax
    mov rdi, r15
    mov rsi, rax
    mov r10, qword ptr [rsp + 0x28]
    movzx edx, word ptr [r10 + 2]
    movzx ecx, word ptr [r10 + 4]
    movzx r8d, word ptr [r10 + 6]
    test ecx, ecx
    jnz .c_near_ready
    mov ecx, 1
.c_near_ready:
    mov r10d, 1                       // the others must carry that evility id
    // DRPGEVIL1b: a provider qualifier (kinds 50..53) right after this entry also tests the provider:
    // filter kind 6, value = evility id | test << 16 | argument << 24 (test = kind - 49: 1 weapon category,
    // 2 hp at least arg %, 3 hp below arg %, 4 hp at or below arg %).
    cmp dword ptr [rsp + 0x30], 2
    jl .c_near_call
    mov rax, qword ptr [rsp + 0x28]
    movzx r10d, word ptr [rax + 8]
    cmp r10d, 64                      // EVILFX2: provider_buff -> test 5
    jne .c_near_std
    mov r10d, 5
    jmp .c_near_q
.c_near_std:
    sub r10d, 49
    cmp r10d, 1
    jb .c_near_plain
    cmp r10d, 4
    ja .c_near_plain
.c_near_q:
    shl r10d, 16
    or r8d, r10d
    movzx r10d, byte ptr [rax + 10]
    shl r10d, 24
    or r8d, r10d
    mov r10d, 6
    jmp .c_near_call
.c_near_plain:
    mov r10d, 1
.c_near_call:
    call evil_near
    test eax, eax
    jnz .e_next
    jmp .e_ret
.c_ofly:                             // the other side flies
    test r13, r13
    jz .e_ret
    mov rax, qword ptr [r13 + 0x240]
    test rax, rax
    jz .e_ret
    cmp byte ptr [rax + 0x2e2a], 2
    je .e_next
    jmp .e_ret
.c_sfly:
    cmp byte ptr [r15 + 0x2e2a], 2
    je .e_next
    jmp .e_ret
.c_ohigher:                          // "if enemy level is higher"
    test r13, r13
    jz .e_ret
    mov rax, qword ptr [r13 + 0x240]
    test rax, rax
    jz .e_ret
    movsx eax, word ptr [rax + 0x2dfc]
    movsx ecx, word ptr [r15 + 0x2dfc]
    cmp ecx, eax
    jl .e_next
    jmp .e_ret
.c_olower:
    test r13, r13
    jz .e_ret
    mov rax, qword ptr [r13 + 0x240]
    test rax, rax
    jz .e_ret
    movsx eax, word ptr [rax + 0x2dfc]
    movsx ecx, word ptr [r15 + 0x2dfc]
    cmp ecx, eax
    jg .e_next
    jmp .e_ret
// Type conditions 31..34 inspect the other side, 35..38 the subject (aura recipient).
.c_ohp:                              // the other side's hp percent: 39 strictly below a, 40 at least a
    test r13, r13
    jz .e_ret
    mov r11, qword ptr [r13 + 0x240]
    test r11, r11
    jz .e_ret
    mov rax, qword ptr [r11 + 0x2cc8]
    mov r8, qword ptr [r11 + 0x2cd8]
    test r8, r8
    jle .e_ret
    mov rcx, 100
    imul rax, rcx
    cqo
    idiv r8
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp word ptr [r10], 39
    jne .c_ohp_at
    cmp eax, ecx
    jl .e_next
    jmp .e_ret
.c_ohp_at:
    cmp eax, ecx
    jge .e_next
    jmp .e_ret
.c_eany:                             // the attack carries any element (1..4)
    test rbp, rbp
    jz .e_ret
    cmp byte ptr [rbp + 0x276bc], 0
    jne .e_next
    jmp .e_ret
.c_tcount:                           // the action's target-entry count: 42 exactly a, 43 at least a
    test rbp, rbp
    jz .e_ret
    movsx eax, word ptr [rbp + 160536]
    mov r10, qword ptr [rsp + 0x28]
    movzx ecx, word ptr [r10 + 2]
    cmp word ptr [r10], 43
    je .c_tcount_min
    cmp eax, ecx
    je .e_next
    jmp .e_ret
.c_tcount_min:
    cmp eax, ecx
    jge .e_next
    jmp .e_ret
.c_nearchar:                         // at least one unit of a relation within b panels has character id c
    mov r10, qword ptr [rsp + 0x28]
    cmp word ptr [r10 + 2], 2         // relation: 0 any, 1 ally, 2 enemy
    ja .e_ret
    cmp word ptr [r10 + 6], 0         // the character id
    je .e_ret
    mov rcx, r15
    call evil_brec
    mov qword ptr [rsp + 0x20], rax
    mov rdi, r15
    mov rsi, rax
    mov r10, qword ptr [rsp + 0x28]
    movzx edx, word ptr [r10 + 2]
    movzx ecx, word ptr [r10 + 4]
    test ecx, ecx
    jnz .c_nc_ready
    mov ecx, 1                        // a named character has to be next to the subject
.c_nc_ready:
    movzx r8d, word ptr [r10 + 6]
    mov r10d, 2                       // the others' character id must equal it
    call evil_near
    test eax, eax
    jnz .e_next
    jmp .e_ret
.c_oadj:                             // the other participant stands on a neighbouring panel
    test r13, r13
    jz .e_ret
    mov rcx, r15
    call evil_brec
    mov qword ptr [rsp + 0x20], rax
    test rax, rax
    jz .e_ret
    mov rcx, rax
    call evil_cell
    mov dword ptr [rsp + 0x38], eax   // the subject's own panel
    mov dword ptr [rsp + 0x3c], edx
    mov rcx, r13
    call evil_cell
    sub eax, dword ptr [rsp + 0x38]
    mov ecx, eax
    sar ecx, 31
    xor eax, ecx
    sub eax, ecx                      // |dx|
    sub edx, dword ptr [rsp + 0x3c]
    mov ecx, edx
    sar ecx, 31
    xor edx, ecx
    sub edx, ecx                      // |dz|
    add eax, edx
    test eax, eax
    jz .e_ret                         // the same panel is not a neighbouring panel
    cmp eax, 1
    jle .e_next
    jmp .e_ret
.c_type:
    mov rcx, r15
    cmp eax, 35
    jae .c_type_self
    test r13, r13
    jz .e_ret
    mov rcx, qword ptr [r13 + 0x240]
    jmp .c_type_go
.c_type_self:
    sub eax, 4
.c_type_go:
    mov dword ptr [rsp + 0x38], eax
    call evil_type
    mov ecx, dword ptr [rsp + 0x38]
    cmp ecx, 31
    je .c_type_human
    cmp ecx, 32
    je .c_type_monster
    cmp ecx, 33
    je .c_type_male
    cmp eax, 2
    je .e_next
    cmp eax, 12
    je .e_next
    jmp .e_ret
.c_type_human:
    cmp eax, 1
    je .e_next
    cmp eax, 2
    je .e_next
    jmp .e_ret
.c_type_monster:
    cmp eax, 11
    je .e_next
    cmp eax, 12
    je .e_next
    jmp .e_ret
.c_type_male:
    cmp eax, 1
    je .e_next
    cmp eax, 11
    je .e_next
    jmp .e_ret
// ------------------------------------------------------------------------------------------ loop control
.e_next:
    mov r10, qword ptr [rsp + 0x28]
    add r10, 8
    mov qword ptr [rsp + 0x28], r10
    dec dword ptr [rsp + 0x30]
    jmp .e_loop
.e_ok:
    mov eax, 1
    jmp .e_exit
.e_ret:
    xor eax, eax
.e_exit:
    add rsp, 0x48
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rbx
    pop rsi
    pop rdi
    ret

// evil_apply(edi = family mask, rsi = unit record, rdx = stat aggregate or 0, r8 = other battle record or 0,
//            r9 = action context or 0)
// Applies the effects of every row whose family matches: family 1 potency words, family 2 stat aggregate.
// An aura row (family bit 64) is applied by the potency and aggregate passes as well, on the recipient.
evil_apply:
    push rsi
    push rbx
    push rbp
    push r13
    push r14
    push r15
    push r12
    sub rsp, 0x30
    mov ebp, edi                      // the family mask
    mov r12, rdx                      // agg (0 for the potency pass)
    mov r13, r8                       // other battle record
    mov qword ptr [rsp + 0x20], r9    // action context
    // The unit stays in rsi (callee-saved, and every helper here preserves it), so the
    // second frame slot is free for the effect counter that evil_scale would clobber.
    test rsi, rsi
    jz .a_ret
    xor r15d, r15d
.a_loop:
    mov rcx, r15
    mov edx, ebp
    call evil_next
    mov r15, rcx
    test rax, rax
    jz .a_ret
    mov rbx, rax
.a_eval:
    mov rcx, rbx
    mov rdx, r13
    mov r8, qword ptr [rsp + 0x20]
    xor r9d, r9d
    call evil_eval
    test eax, eax
    jz .a_next
// --- effects ---
    mov eax, dword ptr [rbx + 16]
    lea r14, [rip + evil_fx]
    add r14, rax
    mov eax, dword ptr [rbx + 20]
    mov dword ptr [rsp + 0x28], eax   // effects left (evil_scale clobbers the volatile registers)
.a_fx:
    mov eax, dword ptr [rsp + 0x28]
    test eax, eax
    jz .a_next
    mov ecx, dword ptr [r14]
    mov eax, dword ptr [r14 + 4]
    mov r8d, ecx
    shr r8d, 16
    and r8d, 255                      // runtime scale kind
    and ecx, 255                      // stat index
    test r8d, r8d
    jz .a_fx_value
    mov rcx, rsi
    mov edx, r8d
    mov r8d, dword ptr [rbx + 28]     // CARRIERS2: the row's filter argument (class id / evility id)
    mov r9d, dword ptr [r14 + 4]
    call evil_scaled                  // eax = value * count; r14 (this effect) and rsi survive it
    mov ecx, dword ptr [r14]
    and ecx, 255                      // stat index, reloaded from the effect
    cmp eax, 32767
    jle .a_fx_lo
    mov eax, 32767
.a_fx_lo:
    cmp eax, -32768
    jge .a_fx_value
    mov eax, -32768
.a_fx_value:
    cmp ebp, 1
    je .a_pot
    test r12, r12
    jz .a_cont
    add dword ptr [r12 + rcx*4], eax            // family 2: stat aggregate
    jmp .a_cont
.a_pot:
    add word ptr [rsi + rcx*2 + 0x3068], ax     // family 1: potency word (16-bit wrap, as the game does)
    movzx r8d, word ptr [rsi + rcx*2 + 0x3068]
    mov rax, 0x140a18780
    mov rax, qword ptr [rax]
    cmp r8, rax
    jae .a_hi
    mov r8, rax
    jmp .a_st
.a_hi:
    mov rax, 0x140a18788
    mov rax, qword ptr [rax]
    cmp r8, rax
    jbe .a_st
    mov r8, rax
.a_st:
    mov word ptr [rsi + rcx*2 + 0x3068], r8w
.a_cont:
    add r14, 8
    dec dword ptr [rsp + 0x28]
    jmp .a_fx
.a_next:
    jmp .a_loop
.a_ret:
    add rsp, 0x30
    pop r12
    pop r15
    pop r14
    pop r13
    pop rbp
    pop rbx
    pop rsi
    ret

// evil_growth(rsi = unit record, edx = stat k) -> eax = extra growth percent for that stat
evil_growth:
    push rbx
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x30
    xor eax, eax
    test rsi, rsi
    jz .g_ret
    mov r12d, edx                     // the stat asked for
    xor r15d, r15d                    // sum
    xor r13d, r13d                    // no other side in this pass
    mov qword ptr [rsp + 0x20], 0     // the whole cursor, not just its learned-id half
.g_loop:
    mov rcx, qword ptr [rsp + 0x20]
    mov edx, 4
    call evil_next
    mov qword ptr [rsp + 0x20], rcx
    test rax, rax
    jz .g_done
    mov rbx, rax
    mov rcx, rbx
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_eval
    test eax, eax
    jz .g_next
    mov eax, dword ptr [rbx + 16]
    lea r14, [rip + evil_fx]
    add r14, rax
    mov r11d, dword ptr [rbx + 20]
.g_fx:
    test r11d, r11d
    jz .g_next
    mov ecx, dword ptr [r14]
    cmp ecx, r12d
    jne .g_cont
    add r15d, dword ptr [r14 + 4]
.g_cont:
    add r14, 8
    dec r11d
    jmp .g_fx
.g_next:
    jmp .g_loop
.g_done:
    mov eax, r15d
.g_ret:
    add rsp, 0x30
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbx
    ret

// evil_dmg_sum(edi = family mask, rsi = subject unit record, rdx = other battle record or 0,
//              r8 = action context or 0, r9d = status index) -> eax = sum
// The percentage families carry one number per effect (the stat field is not used), added together.
evil_dmg_sum:
    push rbx
    push r15
    push r14
    push r13
    push r12
    sub rsp, 0x40
    xor r15d, r15d                    // sum
    test rsi, rsi
    jz .d_ret
    mov r14, rdi                      // family query (MASKWIDE1: 64-bit)
    mov r13, rdx                      // other battle record
    mov qword ptr [rsp + 0x20], r8    // action context
    mov qword ptr [rsp + 0x28], r9    // status index
    mov qword ptr [rsp + 0x30], 0     // the whole cursor, not just its learned-id half
.d_loop:
    mov rcx, qword ptr [rsp + 0x30]
    mov rdx, r14
    call evil_next
    mov qword ptr [rsp + 0x30], rcx
    test rax, rax
    jz .d_skill
    mov rbx, rax
    mov rcx, rbx
    mov rdx, r13
    mov r8, qword ptr [rsp + 0x20]
    mov r9, qword ptr [rsp + 0x28]
    call evil_eval
    test eax, eax
    jz .d_next
    mov eax, dword ptr [rbx + 16]
    lea r12, [rip + evil_fx]
    add r12, rax
    mov eax, dword ptr [rbx + 20]
    mov dword ptr [rsp + 0x38], eax   // effects left (evil_scale clobbers the volatile registers)
.d_fx:
    mov eax, dword ptr [rsp + 0x38]
    test eax, eax
    jz .d_next
    mov ecx, dword ptr [r12]
    mov edx, dword ptr [rip + evil_fxmode]
    test edx, edx
    jz .d_mode_ok                     // D4SIG5: 0 = every effect (all families but evasion)
    mov eax, ecx
    shr eax, 8
    and eax, 3
    inc eax                           // 1 = a "scale" effect (stat word bits 8-9 clear), 2 = "points" (bit 8), 3 = "after" (bit 9, DD2EVIL1)
    cmp eax, edx
    jne .d_skip
.d_mode_ok:
    mov eax, dword ptr [r12 + 4]
    test ecx, 0x1000000            // PLUME1: old s32 values remain untouched
    jz .d_base
    movsx eax, ax
.d_base:
    mov r8d, ecx
    shr r8d, 16
    and r8d, 255                      // runtime scale kind
    test r8d, r8d
    jz .d_add
    mov r9d, eax
    mov rcx, rsi
    mov edx, r8d
    mov r8d, dword ptr [rbx + 28]     // CARRIERS2: the row's filter argument
    call evil_scaled
.d_add:
    test dword ptr [r12], 0x1000000
    jz .d_sum
    mov ecx, dword ptr [r12 + 4]
    shr ecx, 16                     // nonnegative per-effect upper limit, after scaling
    cmp eax, ecx
    cmovg eax, ecx
.d_sum:
    add r15d, eax
.d_skip:
    add r12, 8
    dec dword ptr [rsp + 0x38]
    jmp .d_fx
.d_next:
    jmp .d_loop
// --- EX-06: skill-scope rows.  They are not in any unit's learned list, so evil_next never reaches them; the
// index below lists them in id order and each row is evaluated against the action's own skill id (evil_eval
// .e_skill).  Only the damage-time families ask for this pass (they are the ones given the action context).
.d_skill:
    cmp qword ptr [rsp + 0x20], 0
    jz .d_ret                         // no action context: no skill id to match
    mov dword ptr [rsp + 0x30], 0
.ds_loop:
    mov ecx, dword ptr [rsp + 0x30]
    cmp ecx, dword ptr [rip + evil_skill_count]
    jae .d_ret
    lea rax, [rip + evil_skill_index]
    mov eax, dword ptr [rax + rcx*4]
    lea rbx, [rip + evil_tbl]
    add rbx, rax
    inc ecx
    mov dword ptr [rsp + 0x30], ecx
    mov edx, dword ptr [rbx + 4]
    test edx, r14d
    jz .ds_loop                       // another family's row
    mov rcx, rbx
    mov rdx, r13
    mov r8, qword ptr [rsp + 0x20]
    mov r9, qword ptr [rsp + 0x28]
    call evil_eval
    test eax, eax
    jz .ds_loop
    mov eax, dword ptr [rbx + 16]
    lea r12, [rip + evil_fx]
    add r12, rax
    mov eax, dword ptr [rbx + 20]
    mov dword ptr [rsp + 0x38], eax
.ds_fx:
    mov eax, dword ptr [rsp + 0x38]
    test eax, eax
    jz .ds_loop
    mov ecx, dword ptr [r12]
    mov edx, dword ptr [rip + evil_fxmode]
    test edx, edx
    jz .ds_mode_ok
    mov eax, ecx
    shr eax, 8
    and eax, 3
    inc eax
    cmp eax, edx
    jne .ds_skip
.ds_mode_ok:
    mov eax, dword ptr [r12 + 4]
    test ecx, 0x1000000            // PLUME1: old s32 values remain untouched
    jz .ds_base
    movsx eax, ax
.ds_base:
    mov r8d, ecx
    shr r8d, 16
    and r8d, 255                      // runtime scale kind
    test r8d, r8d
    jz .ds_add
    mov r9d, eax
    mov rcx, rsi
    mov edx, r8d
    mov r8d, dword ptr [rbx + 28]     // CARRIERS2: the row's filter argument
    call evil_scaled
.ds_add:
    test dword ptr [r12], 0x1000000
    jz .ds_sum
    mov ecx, dword ptr [r12 + 4]
    shr ecx, 16                     // nonnegative per-effect upper limit, after scaling
    cmp eax, ecx
    cmovg eax, ecx
.ds_sum:
    add r15d, eax
.ds_skip:
    add r12, 8
    dec dword ptr [rsp + 0x38]
    jmp .ds_fx
.d_ret:
    mov eax, r15d
    add rsp, 0x40
    pop r12
    pop r13
    pop r14
    pop r15
    pop rbx
    ret

// evil_pred(edi = family mask, rsi = unit record, rdx = other battle record or 0,
//           r8 = action context or 0, r9d = status index) -> eax = 1 if any row applies
// For the predicate families (flight, damage nullification, ailment immunity, nullify, counter): the
// row's presence with its conditions is the whole effect.
evil_pred:
    push rbx
    push r13
    push r14
    push r15
    push r12
    sub rsp, 0x50
    xor r15d, r15d
    test rsi, rsi
    jz .p_ret
    mov r14, rdi                      // MASKWIDE1: 64-bit family query
    mov r13, rdx
    mov qword ptr [rsp + 0x40], r8    // action context (0 for the families that get none)
    mov qword ptr [rsp + 0x48], r9    // status index
    mov qword ptr [rsp + 0x20], 0     // the whole cursor, not just its learned-id half
.p_loop:
    mov rcx, qword ptr [rsp + 0x20]
    mov rdx, r14
    call evil_next
    mov qword ptr [rsp + 0x20], rcx
    test rax, rax
    jz .p_skill
    mov rbx, rax
    mov rcx, rbx
    mov rdx, r13
    mov r8, qword ptr [rsp + 0x40]   // action context (0 for the families that get none)
    mov r9, qword ptr [rsp + 0x48]   // status index
    call evil_eval
    test eax, eax
    jz .p_next
    mov r15d, 1
    jmp .p_ret
.p_next:
    jmp .p_loop
// EX-06b: skill rows are in no learned list, so evil_next never reaches them; the predicate families
// scan the id-ordered skill index afterwards, exactly as evil_dmg_sum does for the percentage families.
// Without an action context there is no skill id to match, so the pass is skipped.
.p_skill:
    cmp qword ptr [rsp + 0x40], 0
    jz .p_ret
    mov dword ptr [rsp + 0x28], 0
.ps_loop:
    mov ecx, dword ptr [rsp + 0x28]
    cmp ecx, dword ptr [rip + evil_skill_count]
    jae .p_ret
    lea rax, [rip + evil_skill_index]
    mov eax, dword ptr [rax + rcx*4]
    lea rbx, [rip + evil_tbl]
    add rbx, rax
    inc ecx
    mov dword ptr [rsp + 0x28], ecx
    mov edx, dword ptr [rbx + 4]
    test edx, r14d
    jz .ps_loop                       // another family's row
    mov rcx, rbx
    mov rdx, r13
    mov r8, qword ptr [rsp + 0x40]
    mov r9, qword ptr [rsp + 0x48]
    call evil_eval
    test eax, eax
    jz .ps_loop
    mov r15d, 1
    jmp .p_ret
.p_ret:
    mov eax, r15d
    add rsp, 0x50
    pop r12
    pop r15
    pop r14
    pop r13
    pop rbx
    ret


// evil_regen(rcx = battle record): applies every regen row the unit has, once, at the round edge.
// HP is the qword at unit+0x2CC8 (max +0x2CD8) and SP at +0x2CD0 (max +0x2CE0); an effect's value is a
// percentage of the maximum (negative drains).  Every write in the game clamps to 0..max and then
// refreshes the HP-bar shadow, so this does the same and calls unit_set_hp_shadow after an HP write.
// Preserves every nonvolatile register.
evil_regen:
    push rsi
    push rbx
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x30
    test rcx, rcx
    jz .r_ret
    mov r13, rcx                      // battle record
    mov r12, qword ptr [rcx + 0x240]  // unit record
    test r12, r12
    jz .r_ret
    mov rsi, r12                      // evil_next and evil_eval take the unit in rsi
    xor r15d, r15d                    // row cursor
.r_loop:
    mov rcx, r15
    mov edx, 2048
    call evil_next
    mov r15, rcx
    test rax, rax
    jz .r_ret
    mov rbx, rax
    mov rcx, rbx
    mov rsi, r12
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_eval
    test eax, eax
    jz .r_loop
    mov eax, dword ptr [rbx + 16]
    lea r14, [rip + evil_fx]
    add r14, rax
    mov eax, dword ptr [rbx + 20]
    mov dword ptr [rsp + 0x28], eax   // effects left
.r_fx:
    mov eax, dword ptr [rsp + 0x28]
    test eax, eax
    jz .r_loop
    mov ecx, dword ptr [r14]
    and ecx, 255                      // 0 hp, 1 sp
    movsxd rbp, dword ptr [r14 + 4]   // percent of the maximum
    test rbp, rbp
    jz .r_cont
    cmp ecx, 1
    jne .r_hp
    mov r8, qword ptr [r12 + 0x2ce0]  // max sp
    mov r9, qword ptr [r12 + 0x2cd0]  // current sp
    jmp .r_calc
.r_hp:
    mov r8, qword ptr [r12 + 0x2cd8]  // max hp
    mov r9, qword ptr [r12 + 0x2cc8]  // current hp
.r_calc:
    mov r11, r8                       // the base the percent is taken of: the unit's own maximum
    test dword ptr [r14], 0x100
    jz .r_base
    // EVILFX2: a regen AURA effect marked base = provider heals a percent of the PROVIDER's maximum HP
    // (Disgaea RPG: "party HP recovers 8 % of the holder's max HP").  The provider is the unit this row's
    // near_has just matched (evil_near_unit; the emitter refuses other map-walking conditions on such a row).
    // A unit at 0 hp is not healed.
    test r9, r9
    jle .r_cont
    mov r11, qword ptr [rip + evil_near_unit]
    test r11, r11
    jz .r_cont
    mov r11, qword ptr [r11 + 0x2cd8]
    test r11, r11
    jle .r_cont
.r_base:
    mov rax, rbp
    imul rax, r11
    cqo
    mov r10, 100
    idiv r10                          // trunc toward zero, as every other percent here
    add r9, rax
    test r9, r9
    jns .r_hi
    xor r9d, r9d                      // never below zero
    jmp .r_store
.r_hi:
    cmp r9, r8
    jle .r_store
    mov r9, r8                        // never above the maximum
.r_store:
    cmp ecx, 1
    jne .r_store_hp
    mov qword ptr [r12 + 0x2cd0], r9
    jmp .r_cont
.r_store_hp:
    mov qword ptr [r12 + 0x2cc8], r9
    mov rcx, r13
    mov rdx, r9
    call 0x140151c50                  // unit_set_hp_shadow(record, hp): the bar, not just the number
.r_cont:
    add r14, 8
    dec dword ptr [rsp + 0x28]
    jmp .r_fx
.r_ret:
    add rsp, 0x30
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rbx
    pop rsi
    ret

// evil_conversion(rsi = unit) adds percentages of immutable base stats to post-original maxima.
// Runs once per normal recalc after original overrides, before the game's final clamps.
// Source and destination are separate qword vectors; conversions never feed each other.
evil_conversion:
    push rbx
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x30
    test rsi, rsi
    jz .vconv_ret
    xor r15d, r15d
.vconv_loop:
    mov rcx, r15
    mov edx, 512
    call evil_next
    mov r15, rcx
    test rax, rax
    jz .vconv_ret
    mov rbx, rax
    mov rcx, rbx
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_eval
    test eax, eax
    jz .vconv_loop
    lea r12, [rip + evil_fx]
    mov eax, dword ptr [rbx + 16]
    add r12, rax
    mov r13d, dword ptr [rbx + 20]
.vconv_fx:
    test r13d, r13d
    jz .vconv_loop
    mov ecx, dword ptr [r12]
    movzx r14d, cl
    shr ecx, 8
    and ecx, 255
    cmp ecx, 8
    je .vconv_sp                       // 8 is the unit's *current* SP, not a base stat
    mov rax, qword ptr [rsi + rcx*8 + 0x2d18]
    jmp .vconv_mul
.vconv_sp:
    mov rax, qword ptr [rsi + 0x2cd0]
.vconv_mul:
    movsxd rcx, dword ptr [r12 + 4]
    imul rax, rcx
    cqo
    mov ecx, 100
    idiv rcx
    add qword ptr [rsi + r14*8 + 0x2cd8], rax
    add r12, 8
    dec r13d
    jmp .vconv_fx
.vconv_ret:
    add rsp, 0x30
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbx
    ret

// --- the game functions, called through the original `call` so their own prologue runs in its own frame ---
// Alignment note: a wrapper is entered by `call` from the call site, so it starts with rsp = 8 (mod 16),
// like a function just called.  Every `call` below is made with rsp = 0 (mod 16) and 32 bytes of shadow
// space, and stack arguments are copied to where the callee reads them.
tramp_pot:
    sub rsp, 0x28
    call 0x1401e1b30
    add rsp, 0x28
    ret

tramp_status:
    sub rsp, 0x28
    call 0x1401b97d0
    add rsp, 0x28
    ret

tramp_growth:
    sub rsp, 0x28
    call 0x1401e9b50
    add rsp, 0x28
    ret

tramp_regen:
    sub rsp, 0x28
    call 0x140551ac0
    add rsp, 0x28
    ret

// --- P3: the four additive passes (attack power, defence power, move, attack/magic range).  Each game
// function returns a number the caller then uses; the extension adds the rows' values to it.
tramp_dpower:
    sub rsp, 0x28
    call 0x1401f8700
    add rsp, 0x28
    ret

tramp_move:
    sub rsp, 0x28
    call 0x140157d90
    add rsp, 0x28
    ret

tramp_range:
    sub rsp, 0x28
    call 0x1401ec5c0
    add rsp, 0x28
    ret

// evil_sum_unit(edi = family mask, rsi = subject unit record) -> eax = the summed row values
// The additive families are handed no action context and no other side: their consumers (the attack- and
// defence-power rule passes, the move-range getter, the range-bonus getter) have neither, so only
// unit-state conditions can hold on these rows.
evil_sum_unit:
    sub rsp, 0x28
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum
    add rsp, 0x28
    ret

// DD2EVIL2: evil_team_sum(rcx = subject battle record, rdx = 64-bit family query, r8d = 1 to count the subject's own rows too)
// -> eax = the summed row values of the query over every deployed unit of the subject's team.  The walk is the one wrap_healmod uses (active byte
// +0x2E8, not carried +0x2EE < 0, a stat record), plus HP > 0 (a defeated holder gives nothing).  Disgaea D2's equivalent is 0xF6290 (count the
// units of the same team byte +0x6EB that hold an evility, no range), whose caller multiplies by the evility value; here each holder's row
// carries the value, so one holder adds its value and several add up.  Preserves every nonvolatile register.
evil_team_sum:
    push rbx
    push rsi
    push rdi
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x30
    mov dword ptr [rsp + 0x20], 0       // the sum
    mov dword ptr [rsp + 0x24], r8d     // count the subject itself
    mov r12, rcx
    mov rbx, rdx
    test r12, r12
    jz .ts_ret
    mov rax, qword ptr [r12 + 0x240]
    test rax, rax
    jz .ts_ret
    movzx r13d, byte ptr [rax + 0x2e32] // the subject's team
    mov r14, 0x141ba33b0                // scan cursor (the battle table evil_near uses)
    xor r15d, r15d                      // index
.ts_loop:
    mov rsi, qword ptr [r14 + 0x240]
    test rsi, rsi
    jz .ts_next
    cmp r14, r12
    jne .ts_other
    cmp dword ptr [rsp + 0x24], 0
    je .ts_next                         // the subject does not count itself (Pleinair)
    jmp .ts_sum                         // the subject itself: no map tests (Lilliel's holder is the unit ending its turn)
.ts_other:
    cmp byte ptr [r14 + 0x2e8], 0
    je .ts_next                         // not on the map
    cmp word ptr [r14 + 0x2ee], 0
    jge .ts_next                        // carried by another unit
    cmp dword ptr [rsi + 0x4348], 0x28a
    jae .ts_next                        // no stat record: not a real unit
    cmp qword ptr [rsi + 0x2cc8], 0
    jle .ts_next                        // defeated
    movzx eax, byte ptr [rsi + 0x2e32]
    cmp eax, r13d
    jne .ts_next                        // another team
.ts_sum:
    mov rdi, rbx
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                   // rsi = the candidate's unit record
    add dword ptr [rsp + 0x20], eax
.ts_next:
    add r14, 4704
    inc r15d
    cmp r15d, 256
    jl .ts_loop
.ts_ret:
    mov eax, dword ptr [rsp + 0x20]
    add rsp, 0x30
    pop r15
    pop r14
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret

// DD2EVIL2: evil_move_heal(rcx = battle record) -- Lilliel's Healing Barrier (Disgaea D2 420 "Ally units (including self) recover 2% HP per panel
// they move").  Disgaea D2 0xF64C0 returns value x (other same-team holders) + value (when the unit itself holds it); its three callers
// (0x219ED0 the walk step, 0x21AC3C the second executor, 0x210C08 a path preview loop) heal the stepping unit by that percent of max HP at EVERY
// STEP (0x219804 clamps to max HP).  D5 has no per-step site: this runs at the end of the unit's own turn (wrap_endturn, before turn_t3 zeroes the
// panels-moved word +0x61C) and applies the same per-step amount once per panel moved.  A defeated unit is not healed.
// Preserves every nonvolatile register.
evil_move_heal:
    push rbx
    push rsi
    push rdi
    push r12
    push r13
    push r14
    sub rsp, 0x28
    mov rbx, rcx
    test rbx, rbx
    jz .mh_ret
    movsx r12d, word ptr [rbx + 0x61c]  // panels moved this turn (D5's movement cost counter)
    test r12d, r12d
    jle .mh_ret
    mov rsi, qword ptr [rbx + 0x240]
    test rsi, rsi
    jz .mh_ret
    mov r13, qword ptr [rsi + 0x2cc8]   // current HP
    test r13, r13
    jle .mh_ret
    mov r14, qword ptr [rsi + 0x2cd8]   // maximum HP
    cmp r13, r14
    jge .mh_ret
    mov rcx, rbx
    mov rdx, 0x4000000000               // F2_MOVE_HEAL_PERCENT: second-word bit 6
    mov r8d, 1
    call evil_team_sum
    test eax, eax
    jle .mh_ret
    movsxd rax, eax
    imul rax, r14
    cqo
    mov rcx, 100
    idiv rcx                            // one step's heal: percent x max HP / 100, truncated toward zero
    test rax, rax
    jle .mh_ret                         // under 1 HP per step: nothing to write
    movsxd rcx, r12d
    imul rax, rcx                       // once per panel moved
    add rax, r13
    cmp rax, r14
    jle .mh_store
    mov rax, r14                        // never above the maximum
.mh_store:
    mov qword ptr [rsi + 0x2cc8], rax
    mov rcx, rbx
    mov rdx, rax
    call 0x140151c50                    // unit_set_hp_shadow(record, hp): the bar, not just the number
.mh_ret:
    add rsp, 0x28
    pop r14
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret

// --- wrappers: the patched call sites call here.
// Each starts with a build tag (mov r11d, 0xE7000N) that d5lib/evility.py searches for, so it knows where the
// wrapper is without needing assembler symbols.  r11 is caller-saved, and nothing has been pushed yet.
wrap_pot:
    mov r11d, 0xE70001
    push rdi
    push rsi
    sub rsp, 0x38
    mov qword ptr [rsp + 0x20], rcx
    call tramp_pot
    mov rsi, qword ptr [rsp + 0x20]
    mov edi, 1
    xor edx, edx
    xor r8, r8
    xor r9d, r9d
    call evil_apply
    add rsp, 0x38
    pop rsi
    pop rdi
    ret

wrap_status:
    mov r11d, 0xE70002
    push rdi
    push rsi
    sub rsp, 0x38
    mov qword ptr [rsp + 0x20], rcx
    mov qword ptr [rsp + 0x28], rdx
    call tramp_status
    mov rsi, qword ptr [rsp + 0x20]
    mov rdx, qword ptr [rsp + 0x28]
    mov edi, 2
    xor r8, r8
    xor r9d, r9d
    call evil_apply
    add rsp, 0x38
    pop rsi
    pop rdi
    ret

wrap_growth:
    mov r11d, 0xE70003
    push rbx
    push rdi
    push rsi
    sub rsp, 0x30
    mov qword ptr [rsp + 0x20], rcx
    mov qword ptr [rsp + 0x28], rdx
    call tramp_growth
    mov ebx, eax
    mov rsi, qword ptr [rsp + 0x20]
    mov rdx, qword ptr [rsp + 0x28]
    mov edi, 4
    call evil_growth
    add eax, ebx
    add rsp, 0x30
    pop rsi
    pop rdi
    pop rbx
    ret

// The damage wrappers call the game functions directly rather than through a trampoline: those take
// arguments on the stack, and a trampoline that moves rsp would move them.  The frame gives the callee its
// shadow space and a copy of each stack argument at the offset the callee reads ([rsp+0x20] is the callee's
// fifth argument once its own return address is pushed).
//
// wrap_dealt(rcx = A rec, rdx = D rec, r8 = K, r9 = X, [rsp+0x28] = tgt_i)
wrap_dealt:
    mov r11d, 0xE70004
    push r14
    push rsi
    push rdi
    push r9
    push rdx
    push rcx
    sub rsp, 0x38
    mov rax, qword ptr [rsp + 0x90]   // tgt_i (rsp0 + 0x28: return address + shadow space)
    mov qword ptr [rsp + 0x20], rax   // where the callee reads it
    call 0x1401f8fd0
    mov r14, rax
    mov rcx, qword ptr [rsp + 0x38]   // A rec
    mov rdx, qword ptr [rsp + 0x40]   // D rec
    test rcx, rcx
    jz .w_original
    mov rsi, qword ptr [rcx + 0x240]  // the attacker's unit stats record
    mov r8, qword ptr [rsp + 0x48]    // X
    mov edi, 8
    xor r9d, r9d
    call evil_dmg_sum
    movsxd rax, eax
    add rax, r14
    cmp rax, -100                     // never take the damage below zero
    jge .w_skip
    mov rax, -100
    jmp .w_skip
.w_original:
    mov rax, r14
.w_skip:
    add rsp, 0x38
    pop rcx
    pop rdx
    pop r9
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_taken(rcx = pv, rdx = A rec, r8 = D rec, r9 = K, [rsp+0x28] = X, [rsp+0x30] = tgt_i, [rsp+0x38] = fc)
wrap_taken:
    mov r11d, 0xE70005
    push r14
    push rsi
    push rdi
    push r8
    push rdx
    push rcx
    sub rsp, 0x38
    mov rax, qword ptr [rsp + 0x90]   // X
    mov qword ptr [rsp + 0x20], rax
    mov rax, qword ptr [rsp + 0x98]   // tgt_i
    mov qword ptr [rsp + 0x28], rax
    mov rax, qword ptr [rsp + 0xA0]   // fc
    mov qword ptr [rsp + 0x30], rax
    call 0x1401fb2e0
    mov rax, qword ptr [rsp + 0x38]   // the in/out percent
    mov rdx, qword ptr [rsp + 0x40]   // A rec
    mov r8, qword ptr [rsp + 0x48]    // D rec
    test rax, rax
    jz .v_done
    test r8, r8
    jz .v_done
    mov r14, rax                      // keep pv
    mov rsi, qword ptr [r8 + 0x240]   // the defender's unit stats record
    mov r8, qword ptr [rsp + 0x20]    // X
    mov rdx, qword ptr [rsp + 0x40]   // the attacker's record
    mov edi, 4096
    call evil_pred                    // a damage_null row nullifies the whole hit
    test eax, eax
    jz .v_sum
    mov qword ptr [r14], 0
    jmp .v_done
.v_sum:
    mov rsi, qword ptr [rsp + 0x48]   // the defender's record
    mov rsi, qword ptr [rsi + 0x240]
    mov rdx, qword ptr [rsp + 0x40]   // A rec
    mov r8, qword ptr [rsp + 0x20]    // X
    mov edi, 16
    xor r9d, r9d
    call evil_dmg_sum
    movsxd rcx, eax
    add rcx, 100
    mov rax, qword ptr [r14]
    imul rax, rcx
    mov rcx, 100
    cqo
    idiv rcx
    test rax, rax
    jns .v_store
    xor eax, eax
.v_store:
    mov qword ptr [r14], rax
    // DRPGEVIL1b: critical damage.  D5's own Purgatory (1222) lives in this very function: when the action
    // context's target entry says the hit is a critical (byte X + tgt_i * 0x260 + 0x152A), the value is
    // multiplied by (100 + v) / 100 for the ATTACKER's evility.  The same test, for the attacker's
    // crit_damage rows (family bit 27), after the original and after the defender's `taken` rows.
    mov r8, qword ptr [rsp + 0x20]    // X
    test r8, r8
    jz .v_done
    mov eax, dword ptr [rsp + 0x28]   // tgt_i
    cmp eax, 256
    jae .v_done                       // not a target index: no crit flag to read
    imul eax, eax, 0x260
    cmp byte ptr [r8 + rax + 0x152a], 0
    je .v_done
    mov rdx, qword ptr [rsp + 0x40]   // A rec
    test rdx, rdx
    jz .v_done
    mov rsi, qword ptr [rdx + 0x240]  // the attacker's unit record
    test rsi, rsi
    jz .v_done
    mov rdx, qword ptr [rsp + 0x48]   // the other side: the defender's record
    mov edi, 0x8000000
    xor r9d, r9d
    call evil_dmg_sum
    test eax, eax
    jz .v_done
    movsxd rcx, eax
    add rcx, 100
    mov rax, qword ptr [r14]
    imul rax, rcx
    mov rcx, 100
    cqo
    idiv rcx
    test rax, rax
    jns .v_cstore
    xor eax, eax
.v_cstore:
    mov qword ptr [r14], rax
.v_done:
    add rsp, 0x38
    pop rcx
    pop rdx
    pop r8
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_flight: the two has_flight_like_evility copies (rcx = battle record).  The game says 1 for evility
// 124 / 1224 / 5000; the extension says 1 as well when a flight row applies.  Only rcx is needed, so the
// function can be called directly with its own shadow space.
wrap_flight_a:
    mov r11d, 0xE70006
    push rsi
    push rdi
    push rcx
    push r14
    sub rsp, 0x28
    call 0x140206160
    mov r14d, eax
    // the game answers with its low byte set (1) or clear (0) - it returns the search index masked, so
    // 0xffffff00 is its "no"; normalise before deciding.
    movzx r14d, al
    mov rcx, qword ptr [rsp + 0x30]   // the battle record (rsp+0x28 frame + the rcx slot)
    test r14d, r14d
    jnz .fa_save                       // the game already calls this unit flight-capable
    test rcx, rcx
    jz .fa_save
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .fa_save
    xor edx, edx
    xor r8d, r8d                      // the flight predicate is handed no action context
    xor r9d, r9d                      // and no status index
    mov edi, 32
    call evil_pred
    mov r14d, eax
.fa_save:
    mov eax, r14d
.fa_done:
    add rsp, 0x28
    pop r14
    pop rcx
    pop rdi
    pop rsi
    ret


wrap_flight_b:
    mov r11d, 0xE70007
    push rsi
    push rdi
    push rcx
    push r14
    sub rsp, 0x28
    call 0x1402062f0
    mov r14d, eax

    // the game answers with its low byte set (1) or clear (0) - it returns the search index masked, so
    // 0xffffff00 is its "no"; normalise before deciding.
    movzx r14d, al
    mov rcx, qword ptr [rsp + 0x30]   // the battle record (rsp+0x28 frame + the rcx slot)
    test r14d, r14d
    jnz .f_save                       // the game already calls this unit flight-capable
    test rcx, rcx
    jz .f_save
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .f_save
    xor edx, edx
    xor r8d, r8d                      // the flight predicate is handed no action context
    xor r9d, r9d                      // and no status index
    mov edi, 32
    call evil_pred
    mov r14d, eax
.f_save:
    mov eax, r14d
.f_done:
    add rsp, 0x28
    pop r14
    pop rcx
    pop rdi
    pop rsi
    ret

// wrap_hit(rcx = pv, rdx = A rec, r8 = D rec, r9 = X, [rsp+0x28] = tgt_i):
// damage_hit_chance_rules is an in/out i64 percent that the function first clamps to [1, 100].  A hit row
// for the attacker adds its percentage points; the result stays inside [1, 100].
// D4SIG5 (evasion, D4 FUN_1400FF700 / FUN_140107100): the DEFENDER's evasion rows act on both sides of the
// game's own call.  A "points" row (D4 Beryl's Servant 1, 844) is subtracted from the percent BEFORE the call,
// so D5's own clamp to [1, 100] comes after it exactly as D4's cap at 100 comes after its flat terms; a "scale"
// row (D4 Misty Haze 351 and the other "evade attacks from ..." evilities) multiplies the finished percent by
// (100 - sum) / 100 after the attacker's rows, as D4 multiplies its hit rate by its product of (100 - v) / 100.
// DD2EVIL1: a third kind, "after" rows, is subtracted after the game's call and the attacker's rows, before the scale rows.
// evil_fxmode picks which of the three kinds evil_dmg_sum adds up (0 = all, the value every other caller leaves).
wrap_hit:
    mov r11d, 0xE70008
    push r14
    push rsi
    push rdi
    push r9
    push r8
    push rdx
    push rcx
    sub rsp, 0x30
    mov rax, qword ptr [rsp + 0x90]   // tgt_i
    mov qword ptr [rsp + 0x20], rax
    mov r14, qword ptr [rsp + 0x30]   // pv (rdi is the family mask, so keep it in r14)
    test r14, r14
    jz .h_call
    mov rcx, qword ptr [rsp + 0x40]   // D rec
    test rcx, rcx
    jz .h_call
    mov rsi, qword ptr [rcx + 0x240]
    mov rdx, qword ptr [rsp + 0x38]   // A rec (the other side)
    mov r8, qword ptr [rsp + 0x48]    // X
    mov edi, 0x80000000               // F_EVASION
    xor r9d, r9d
    mov dword ptr [rip + evil_fxmode], 2
    call evil_dmg_sum
    mov dword ptr [rip + evil_fxmode], 0
    movsxd rcx, eax
    sub qword ptr [r14], rcx          // the "points" rows, before the game's own clamp
.h_call:
    mov rcx, qword ptr [rsp + 0x30]
    mov rdx, qword ptr [rsp + 0x38]
    mov r8, qword ptr [rsp + 0x40]
    mov r9, qword ptr [rsp + 0x48]
    call 0x1401f5410
    test r14, r14
    jz .h_done
    mov rcx, qword ptr [rsp + 0x38]   // A rec
    test rcx, rcx
    jz .h_def
    mov rsi, qword ptr [rcx + 0x240]
    mov rdx, qword ptr [rsp + 0x40]   // D rec
    mov r8, qword ptr [rsp + 0x48]    // X
    mov edi, 128
    xor r9d, r9d
    call evil_dmg_sum
    movsxd rcx, eax
    mov rax, qword ptr [r14]
    add rax, rcx
    cmp rax, 100
    jle .h_lo
    mov eax, 100
    jmp .h_store
.h_lo:
    cmp rax, 1
    jge .h_store
    mov eax, 1
.h_store:
    mov qword ptr [r14], rax
.h_def:
    mov rcx, qword ptr [rsp + 0x40]   // D rec
    test rcx, rcx
    jz .h_done
    mov rsi, qword ptr [rcx + 0x240]
    mov rdx, qword ptr [rsp + 0x38]   // A rec
    mov r8, qword ptr [rsp + 0x48]    // X
    mov edi, 0x80000000               // F_EVASION
    xor r9d, r9d
    mov dword ptr [rip + evil_fxmode], 3
    call evil_dmg_sum                 // DD2EVIL1: the "after" rows (DD2 Rapid Movement 1210 subtracts min(64, 2 x panels moved)
    mov dword ptr [rip + evil_fxmode], 0   // from the percent AFTER the 1..100 clamp, FUN 0xFB0EC), before the scale rows
    test eax, eax
    jle .h_scalepass
    movsxd rcx, eax
    mov rax, qword ptr [r14]
    sub rax, rcx
    cmp rax, 1
    jge .h_astore
    mov eax, 1                        // D5 keeps 1 (damage_hit_roll_hit clamps to 1..99); the DD2 function itself has no floor
.h_astore:
    mov qword ptr [r14], rax
.h_scalepass:
    mov rcx, qword ptr [rsp + 0x40]   // D rec
    mov rsi, qword ptr [rcx + 0x240]
    mov rdx, qword ptr [rsp + 0x38]   // A rec
    mov r8, qword ptr [rsp + 0x48]    // X
    mov edi, 0x80000000               // F_EVASION
    xor r9d, r9d
    mov dword ptr [rip + evil_fxmode], 1
    call evil_dmg_sum
    mov dword ptr [rip + evil_fxmode], 0
    test eax, eax
    jle .h_done                       // D4 applies a factor only while its value is above 0
    mov ecx, 100
    sub ecx, eax
    jns .h_scale
    xor ecx, ecx                      // a sum of 100 or more removes the whole chance (the clamp below makes it 1)
.h_scale:
    mov rax, qword ptr [r14]
    imul rax, rcx
    mov ecx, 100
    cqo
    idiv rcx                          // signed, truncating toward zero like the game's own integer divide
    cmp rax, 100
    jle .h_dlo
    mov eax, 100
    jmp .h_dstore
.h_dlo:
    cmp rax, 1
    jge .h_dstore
    mov eax, 1
.h_dstore:
    mov qword ptr [r14], rax
.h_done:
    add rsp, 0x30
    pop rcx
    pop rdx
    pop r8
    pop r9
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_astat(rcx = pc, rdx = A rec, r8 = D rec, r9 = K, [rsp+0x28] = status index):
// damage_status_chance_rules is an in/out i32 percent.  A status_chance row for the attacker adds its
// percentage points (a row can restrict itself with the status_class condition).
wrap_astat:
    mov r11d, 0xE70009
    push r14
    push rsi
    push rdi
    push r9
    push r8
    push rdx
    push rcx
    sub rsp, 0x30
    mov rax, qword ptr [rsp + 0x90]   // the status index
    mov qword ptr [rsp + 0x20], rax
    call 0x1401ff070
    mov r14, qword ptr [rsp + 0x30]   // pc (rdi is the family mask, so keep it in r14)
    test r14, r14
    jz .s_done
    mov rcx, qword ptr [rsp + 0x40]   // the defender's record: an immunity row is the target's
    test rcx, rcx
    jz .s_done
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .s_done
    mov rdx, qword ptr [rsp + 0x38]   // the attacker's record
    xor r8d, r8d
    mov r9, qword ptr [rsp + 0x20]    // EVILFX2: the status index, so status_class holds on an ailment_null row
    mov edi, 8192                     // (r9 used to be whatever the original call left: one-ailment immunity misfired)
    call evil_pred                    // an ailment_null row zeroes the in/out chance
    test eax, eax
    jz .s_add
    mov dword ptr [r14], 0
    jmp .s_done
.s_add:
    mov rcx, qword ptr [rsp + 0x38]   // A rec
    mov rdx, qword ptr [rsp + 0x40]   // D rec
    test r14, r14
    jz .s_done
    test rcx, rcx
    jz .s_done
    mov rsi, qword ptr [rcx + 0x240]
    mov r8, qword ptr [rip + evil_ctx]  // the action context captured by wrap_achance
    mov r9, qword ptr [rsp + 0x20]    // the status index
    mov edi, 256
    call evil_dmg_sum
    movsxd rcx, eax
    movsxd rax, dword ptr [r14]
    add rax, rcx
    test rax, rax
    js .s_zero
    cmp rax, 0x7fffffff
    jle .s_store
    mov eax, 0x7fffffff
    jmp .s_store
.s_zero:
    xor eax, eax
.s_store:
    mov dword ptr [r14], eax
.s_done:
    add rsp, 0x30
    pop rcx
    pop rdx
    pop r8
    pop r9
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_achance(rcx = X action context, rdx = A rec, r8 = D rec, r9 = K,
//              [rsp+0x28..] = three more arguments)
// EX-06b: damage_status_chance_rules gets no action context of its own (its arguments are the in/out
// percent, both records, K and the ailment index), but every caller of damage_buff_ailment_chance does
// pass the ActionContext as *its* first argument.  So this wrapper records that pointer for the duration
// of the call and wrap_astat reads it back -- the ailment pass then matches skill rows and evaluates
// action-context conditions exactly like the other damage wrappers, without changing any argument.
// The slot is saved and restored, so nesting and an unexpected caller degrade to "no skill id" rather
// than to a stale pointer.
wrap_achance:
    mov r11d, 0xE7000D
    push r14
    push rsi
    push rdi
    push r8
    push rdx
    push rcx
    sub rsp, 0x48
    mov rax, qword ptr [rsp + 0xA0]   // stack argument 5
    mov qword ptr [rsp + 0x20], rax
    mov rax, qword ptr [rsp + 0xA8]   // stack argument 6
    mov qword ptr [rsp + 0x28], rax
    mov rax, qword ptr [rsp + 0xB0]   // stack argument 7
    mov qword ptr [rsp + 0x30], rax
    mov rax, qword ptr [rip + evil_ctx]
    mov qword ptr [rsp + 0x38], rax   // previous context (0 unless nested)
    mov rax, qword ptr [rsp + 0x48]   // rcx == the ActionContext
    mov qword ptr [rip + evil_ctx], rax
    call 0x1401bf810
    mov r14, rax
    mov rax, qword ptr [rsp + 0x38]
    mov qword ptr [rip + evil_ctx], rax
    mov rax, r14
    add rsp, 0x48
    pop rcx
    pop rdx
    pop r8
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_nullify(rcx = A rec, rdx = D rec, r8 = _, r9 = X action context, [rsp+0x28] = tgt_i,
//              [rsp+0x30] = v)
// damage_nullify_predicate answers 1 when the hit is nullified.  When the game says no, a row of the
// nullify family whose conditions hold (evaluated for the *defender*, with the attacker as the other
// side and the action context available) makes the answer yes.
wrap_nullify:
    mov r11d, 0xE7000E
    push r14
    push rdi
    push rsi
    push r9
    push r8
    push rdx
    push rcx
    sub rsp, 0x40
    mov rax, qword ptr [rsp + 0xA0]   // tgt_i
    mov qword ptr [rsp + 0x20], rax
    mov rax, qword ptr [rsp + 0xA8]   // v
    mov qword ptr [rsp + 0x28], rax
    call 0x1401fe0d0
    movzx r14d, al
    // DRPGSIG2: second-word family invincible_hits (Cheshire Cat Majorita 392: "invincible for 2 hits at battle start").  The DECISION is made
    // here: a defender holding the row, whose count (stat record +0xDF9, a byte) is below N, has a hit with positive damage nullified, and the
    // kit's evil_pend byte for its stat record is set; every other pass through here (a forecast, a hit the game nullifies itself, a site that
    // wrap_atkcount cannot see) clears the byte.  The COUNT is raised only by wrap_atkcount after the real damage_apply_damage.  Only the
    // return addresses of the two sites whose hits that apply call sees take part (compute_target 0x1401BF0F0 and the damaging-heal path 0x1401BF6DD).
    mov rdx, qword ptr [rsp + 0x48]   // D rec: the defender's battle record
    test rdx, rdx
    jz .n_noinv
    mov rsi, qword ptr [rdx + 0x240]
    test rsi, rsi
    jz .n_noinv
    mov ecx, dword ptr [rsi + 0x4348]
    cmp ecx, 0x28a
    jae .n_noinv                      // no stat record
    lea rax, [rip + evil_pend]
    mov byte ptr [rax + rcx], 0
    test r14d, r14d
    jnz .n_noinv                      // the game already nullifies it: nothing of ours is consumed
    mov rax, qword ptr [rsp + 0x78]   // the redirected call's return address
    mov rcx, 0x1401BF0F5
    cmp rax, rcx
    je .n_inv
    mov rcx, 0x1401BF6E2
    cmp rax, rcx
    jne .n_noinv
.n_inv:
    cmp qword ptr [rsp + 0xA8], 0     // v: the hit's damage
    jle .n_noinv
    mov rdi, 0x800000000              // F2_INVINCIBLE_HITS: second-word bit 3
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                 // eax = N, 0 for a unit without the row
    test eax, eax
    jle .n_noinv
    mov ecx, dword ptr [rsi + 0x4348]
    imul rdx, rcx, 0xe98
    mov r8, 0x141068bc1               // stat record 0 + 0xDF9
    movzx edx, byte ptr [rdx + r8]    // hits taken so far
    cmp edx, eax
    jae .n_noinv                      // all N used
    lea rax, [rip + evil_pend]
    mov byte ptr [rax + rcx], 1
    mov r14d, 1
.n_noinv:
    test r14d, r14d
    jnz .n_ret                        // nullified (the game's own answer, or invincible_hits)
    mov rcx, qword ptr [rsp + 0x40]   // A rec (the other side)
    mov rdx, qword ptr [rsp + 0x48]   // D rec (the subject)
    test rdx, rdx
    jz .n_ret
    mov rsi, qword ptr [rdx + 0x240]
    test rsi, rsi
    jz .n_ret
    mov rdx, rcx                      // evil_pred's other side = the attacker's battle record
    mov r8, qword ptr [rsp + 0x58]    // X
    xor r9d, r9d
    mov edi, 16384
    call evil_pred
    mov r14d, eax
    test r14d, r14d
    jnz .n_ret
    // LONGTAIL2: second-word family nullify_dealt (bit 10; Disgaea D2 Baal Slave 640 "won't target allies when attacking").  The ATTACKER's rows
    // (subject = the attacker's unit, other side = the defender, the action context) nullify a hit with positive damage when the game's own
    // ally relation says the defender is on the attacker's side: the very test D5's Softening Aura (2072, 0x818) makes at the top of
    // damage_nullify_predicate -- events_env_team_of(rec, 1) of both sides through cmdmenu_preds_p_2d8e00 (team groups 0/4, 1/5, 3).  A hit
    // with damage 0 or less (a heal, a buff) is left alone.
    cmp qword ptr [rsp + 0xA8], 0     // v: the hit's damage
    jle .n_ret
    mov rcx, qword ptr [rsp + 0x40]   // A rec
    mov rdx, qword ptr [rsp + 0x48]   // D rec: the other side
    test rcx, rcx
    jz .n_ret
    test rdx, rdx
    jz .n_ret
    mov rsi, qword ptr [rcx + 0x240]  // the attacker's unit record: the holder
    test rsi, rsi
    jz .n_ret
    mov r8, qword ptr [rsp + 0x58]    // X
    xor r9d, r9d
    mov rdi, 0x40000000000            // nullify_dealt: second-word bit 10
    call evil_pred
    test eax, eax
    jz .n_ret
    mov rcx, qword ptr [rsp + 0x40]   // the attacker's team, as 2072 reads it
    mov edx, 1
    call 0x14015b910                  // events_env_team_of(A rec, 1)
    movzx esi, al
    mov rcx, qword ptr [rsp + 0x48]   // the defender's team
    mov edx, 1
    call 0x14015b910                  // events_env_team_of(D rec, 1)
    movzx edx, al
    mov ecx, esi
    call 0x1402d8e00                  // cmdmenu_preds_p_2d8e00(A's team, D's team): does the defender count as an ally
    test al, al
    jz .n_ret
    mov r14d, 1
.n_ret:
    mov eax, r14d
    add rsp, 0x40
    pop rcx
    pop rdx
    pop r8
    pop r9
    pop rsi
    pop rdi
    pop r14
    ret

// wrap_counter(rcx = attacker rec, rdx = defender rec)
// exec_counter_attack_allow answers 1 when the defender may counter this attack.  It gets no action
// context, so a counter row can only be conditioned on unit state (hp, level, class, adjacency,
// statuses...); a skill row can never match here and the build refuses it for this family.
wrap_counter:
    mov r11d, 0xE7000F
    push r14
    push rdi
    push rsi
    push rdx
    push rcx
    sub rsp, 0x30
    call 0x1401ece00
    movzx r14d, al
    test r14d, r14d
    jnz .k_ret                        // the game already allows it
    mov rcx, qword ptr [rsp + 0x30]   // attacker rec (the other side)
    mov rdx, qword ptr [rsp + 0x38]   // defender rec (the subject)
    test rdx, rdx
    jz .k_ret
    mov rsi, qword ptr [rdx + 0x240]
    test rsi, rsi
    jz .k_ret
    mov rdx, rcx                      // evil_pred's other side = the attacker's battle record
    xor r8d, r8d
    xor r9d, r9d
    mov edi, 32768
    call evil_pred
    mov r14d, eax
.k_ret:
    mov eax, r14d
    add rsp, 0x30
    pop rcx
    pop rdx
    pop rsi
    pop rdi
    pop r14
    ret

// Overrides(unit, optional context); the original sees the unchanged two arguments.
wrap_conversion:
    mov r11d, 0xE7000A
    push rsi
    sub rsp, 0x30
    mov qword ptr [rsp + 0x20], rcx
    call 0x1401eee30
    mov rsi, qword ptr [rsp + 0x20]
    call evil_conversion
    mov rsi, qword ptr [rsp + 0x20]
    call evil_absorb_reapply           // the absorb family's second half (see evil_absorb_reapply)
    add rsp, 0x30
    pop rsi
    ret

// wrap_crit(rcx = pv (int*), rdx = A rec, r8 = D rec, r9 = -, [rsp+0x28] = X, [rsp+0x30] = target index):
// FUN_1401f60a0 is the game's own critical-rate addition pass (0x41E and 0x4D1 live there); a crit_rate
// row for the attacker adds its own percentage points on top, kept inside the 0..100 the caller uses.
wrap_crit:
    mov r11d, 0xE7000B
    push r14
    push rsi
    push rdi
    push r9
    push r8
    push rdx
    push rcx
    sub rsp, 0x30
    mov rax, qword ptr [rsp + 0x90]   // X (the caller's 5th argument)
    mov qword ptr [rsp + 0x20], rax
    mov rax, qword ptr [rsp + 0x98]   // the target index (its 6th)
    mov qword ptr [rsp + 0x28], rax
    call 0x1401f60a0
    mov r14, qword ptr [rsp + 0x30]   // pv
    test r14, r14
    jz .k_done
    mov rcx, qword ptr [rsp + 0x38]   // A rec
    test rcx, rcx
    jz .k_done
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .k_done
    mov rdx, qword ptr [rsp + 0x40]   // D rec
    mov r8, qword ptr [rsp + 0x20]    // X
    mov edi, 1024
    xor r9d, r9d
    call evil_dmg_sum
    movsxd rcx, eax
    movsxd rax, dword ptr [r14]
    add rax, rcx
    cmp rax, 100
    jle .k_lo
    mov eax, 100
    jmp .k_store
.k_lo:
    test rax, rax
    jns .k_store
    xor eax, eax
.k_store:
    mov dword ptr [r14], eax
.k_done:
    add rsp, 0x30
    pop rcx
    pop rdx
    pop r8
    pop r9
    pop rdi
    pop rsi
    pop r14
    ret

// D4SIG10: evil_hospital(rcx = battle record) -- Medic's Base Hospital (D4 864, row 27864), called by wrap_regen after the game's own T1 for the unit.
// D4 FUN_1402EB670, per unit of the round-end pass (state 0x66 of the battle machine, once per round after every side has acted): a unit with 864
// walks the party roster and for every record that is not dead (HP +0xD10 > 0), has +0x20D3 == 0 and has no battle unit (FUN_140244320) adds
// maxHP * v / 100 to HP and maxSP * v / 100 to SP (signed truncation, v = 5), each clamped at its maximum, one provider after another.
// D5: wrap_regen's two sites are T1 at the round-end sweep (sequencer_ctl_s1_update, team 0/4 units, once per round) and TurnCtl init PASS B (the
// other side); only a unit whose team byte (+0x2E32 & 0xFB) is 0 acts here, so the heal fires once per round per player-side Medic.  Recipients: a
// roster record (0x145207DB8 + r * 0x4750, r < the i16 at 0x145574A9C) that is present (+0 != 0), team 0, alive (HP +0x2CC8 > 0), not a Magichange
// weapon (stat record byte +0x4E2 == 0, D5's counterpart of D4's +0x20D3) and not the record of any active battle unit (unit +0x2E8 != 0 and +0x240 == the record).  HP +0x2CC8 / max +0x2CD8, SP +0x2CD0 / max +0x2CE0.
evil_hospital:
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x28
    test rcx, rcx
    jz .hs_ret
    mov rsi, qword ptr [rcx + 0x240]    // the provider's unit record
    test rsi, rsi
    jz .hs_ret
    movzx eax, byte ptr [rsi + 0x2e32]
    and eax, 0xfb
    jnz .hs_ret                         // not a player-side unit
    mov rcx, rsi
    mov edx, 27864
    call evil_has_id
    test eax, eax
    jz .hs_ret
    mov rax, 0x145574a9c
    movsx r12d, word ptr [rax]          // roster count (a signed short, as the game's own loop reads it)
    mov r13, 0x145207db8                // roster record cursor
    xor r14d, r14d
.hs_loop:
    cmp r14d, r12d
    jge .hs_ret
    cmp dword ptr [r13], 0
    je .hs_next                         // empty slot
    cmp byte ptr [r13 + 0x2e32], 0
    jne .hs_next                        // not a player record (the table also holds the other sides)
    cmp qword ptr [r13 + 0x2cc8], 0
    jle .hs_next                        // dead
    mov eax, dword ptr [r13 + 0x4348]
    cmp eax, 0x28a
    jae .hs_deploy                      // no stat record: nothing to test
    imul rax, rax, 0xe98
    mov rcx, 0x1410682aa                // SR + 0x4E2 of stat record 0 (SR0 0x141067DC8): set while the record is a Magichange weapon
    cmp byte ptr [rax + rcx], 0
    jne .hs_next                        // absorbed into another unit: D5's counterpart of D4's +0x20D3
.hs_deploy:
    mov rax, 0x141ba33b0                // battle unit table: 256 x 4704
    xor ecx, ecx
.hs_scan:
    cmp byte ptr [rax + 0x2e8], 0
    je .hs_scan_next
    cmp qword ptr [rax + 0x240], r13
    je .hs_next                         // deployed: not in the base panel
.hs_scan_next:
    add rax, 4704
    inc ecx
    cmp ecx, 256
    jl .hs_scan
    // HP: + max * 5 / 100 (signed truncation), clamped at the maximum
    mov rbx, qword ptr [r13 + 0x2cd8]
    imul rax, rbx, 5
    cqo
    mov ecx, 100
    idiv rcx
    add rax, qword ptr [r13 + 0x2cc8]
    cmp rbx, rax
    cmovl rax, rbx
    mov qword ptr [r13 + 0x2cc8], rax
    // SP likewise
    mov rbx, qword ptr [r13 + 0x2ce0]
    imul rax, rbx, 5
    cqo
    mov ecx, 100
    idiv rcx
    add rax, qword ptr [r13 + 0x2cd0]
    cmp rbx, rax
    cmovl rax, rbx
    mov qword ptr [r13 + 0x2cd0], rax
.hs_next:
    add r13, 0x4750
    inc r14d
    jmp .hs_loop
.hs_ret:
    add rsp, 0x28
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// wrap_regen(rcx = battle record): the game applies a unit's round-edge HP/SP once per unit here.  The
// original runs first and untouched; a regen row then adds its percentage of the maximum, clamps the way
// the game's own writes do, and refreshes the HP-bar shadow (unit_set_hp_shadow) so the bar cannot go
// stale until the next refresh.
wrap_regen:
    mov r11d, 0xE7000C
    push rbx
    push rsi
    push rdi
    sub rsp, 0x30
    mov qword ptr [rsp + 0x20], rcx
    call tramp_regen
    mov rbx, rax                      // the original function's own answer
    mov rcx, qword ptr [rsp + 0x20]
    call evil_regen
    mov rcx, qword ptr [rsp + 0x20]
    call evil_hospital                // D4SIG10: Medic's Base Hospital (27864), a no-op for every other unit
    mov rax, rbx
    add rsp, 0x30
    pop rdi
    pop rsi
    pop rbx
    ret

// --------------------------------------------------------------------------------------------- P3 additive
// The four families below add their values to a number the game's own function returns.  Every one of them
// takes the subject's unit record from a different argument, which is why they are written out separately
// instead of sharing one trampoline.

// wrap_power(rcx = attacker battle record, rdx = record table, r8 = the Skill.dat row, r9 = the action
// context, [rsp+0x28] = target index) -- damage_attack_bonus_rules, the pre-defence attack-power percent.
// Five arguments, one of them on the stack, so the fifth is copied into the frame the callee reads.
// OLEFFECTS: the action context (r9 at the call site) is handed to the row evaluator, so attack-element and
// other action-context conditions now hold on a `power` row -- Overlord's power_percent supports exactly the
// attack-element conditions (entry_condition_matches_attack); unit-state conditions are unaffected.
wrap_power:
    mov r11d, 0xE70010
    push r14
    push rsi
    push rdi
    push r9
    push rdx
    push rcx
    sub rsp, 0x38
    mov rax, qword ptr [rsp + 0x90]   // the fifth argument (frame + saves + return address + arg slot)
    mov qword ptr [rsp + 0x20], rax
    call 0x1401f6300
    mov r14, rax
    mov rcx, qword ptr [rsp + 0x38]   // the attacker's battle record
    test rcx, rcx
    jz .pw_orig
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .pw_orig
    mov edi, 65536
    xor edx, edx
    mov r8, qword ptr [rsp + 0x48]    // the action context (r9 at the call site)
    xor r9d, r9d
    call evil_dmg_sum
    movsxd rax, eax
    add rax, r14
    jmp .pw_done
.pw_orig:
    mov rax, r14
.pw_done:
    add rsp, 0x38
    pop rcx
    pop rdx
    pop r9
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_dpower(rcx = attacker actor, rdx = the defender's unit record) -- damage_defence_bonus_rules, the
// pre-application defence-power percent.  The subject is *rdx* here: it is already the unit record.
wrap_dpower:
    mov r11d, 0xE70011
    push r14
    push rsi
    push rdi
    push rdx
    sub rsp, 0x28
    call tramp_dpower
    mov r14, rax
    mov rsi, qword ptr [rsp + 0x28]   // the defender's unit record
    test rsi, rsi
    jz .dw_orig
    mov edi, 131072
    call evil_sum_unit
    movsxd rax, eax
    add rax, r14
    jmp .dw_done
.dw_orig:
    mov rax, r14
.dw_done:
    add rsp, 0x28
    pop rdx
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_move(rcx = unit battle record) -- menus_env_move_range, the unit's move range in panels.
wrap_move:
    mov r11d, 0xE70012
    push r14
    push rsi
    push rdi
    push rcx
    sub rsp, 0x28
    call tramp_move
    mov r14, rax
    mov rcx, qword ptr [rsp + 0x28]   // the unit's battle record
    test rcx, rcx
    jz .mv_orig
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .mv_orig
    mov edi, 262144
    call evil_sum_unit
    movsxd rax, eax
    add r14, rax
    // DD2EVIL2: Pleinair (second-word family ally_move, bit 5): +value for every OTHER deployed unit of this unit's team that holds the
    // row (Disgaea D2 0xF7938 / 0xFC724 add 0xF6290(...) x value to the unit's move byte; 0xF6290 skips the unit itself).  A unit whose move range
    // is 0 (D5's objects) gets nothing, as D5's own 6024 (inside the path pass) leaves them.
    test r14, r14
    jle .mv_orig
    mov rcx, qword ptr [rsp + 0x28]
    mov rdx, 0x2000000000
    xor r8d, r8d
    call evil_team_sum
    movsxd rax, eax
    add r14, rax
.mv_orig:
    mov rax, r14
.mv_done:
    add rsp, 0x28
    pop rcx
    pop rdi
    pop rsi
    pop r14
    ret

// wrap_range(rcx = unit battle record, rdx = the skill/context argument) -- the game's attack/magic range
// bonus getter (evilities 1033 and 3305 in vanilla).  Both arguments are passed through untouched.
wrap_range:
    mov r11d, 0xE70013
    push r14
    push rsi
    push rdi
    push rcx
    sub rsp, 0x28
    call tramp_range
    mov r14, rax
    mov rcx, qword ptr [rsp + 0x28]   // the unit's battle record
    test rcx, rcx
    jz .rg_orig
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .rg_orig
    mov edi, 524288
    call evil_sum_unit
    movsxd rax, eax
    add rax, r14
    jmp .rg_done
.rg_orig:
    mov rax, r14
.rg_done:
    add rsp, 0x28
    pop rcx
    pop rdi
    pop rsi
    pop r14
    ret

// evil_absorb_reapply(rsi = unit record) -- the *second half* of the absorb family, run from the
// unit_stats_evil_overrides wrapper (0x1401EEE30, which already carries the conversion family).
// D5's own Absorption (6032) is a two-step mechanic: FUN_140200D20 stores a share of each defeated unit's
// six stats into the unit's stat record at +0x5A8 (six qwords), and unit_stats_evil_overrides adds that
// accumulator into the unit's max-stat work vector unit+0x2CE8..+0x2D10 while the unit carries 6032.
// A unit carrying our id does not carry 6032, so the original pass would leave the accumulator unused;
// this adds it for units with an absorb row, exactly as the 6032 block does for its own.
// Preserves every nonvolatile register.
evil_absorb_reapply:
    push rbx
    push r13
    push rdi
    sub rsp, 0x20
    test rsi, rsi
    jz .ar_ret
    mov edi, 1048576
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred                    // does any absorb row of this unit apply?
    test eax, eax
    jz .ar_ret
    mov eax, dword ptr [rsi + 0x4348]
    cmp eax, 0x28a
    jae .ar_ret                       // no stat record
    imul rax, rax, 0xe98
    mov rcx, 0x141067dc8
    add rcx, rax
    xor r13d, r13d
.ar_loop:
    cmp r13d, 6
    jae .ar_ret
    mov rax, qword ptr [rcx + r13*8 + 0x5a8]
    add qword ptr [rsi + r13*8 + 0x2ce8], rax
    inc r13d
    jmp .ar_loop
.ar_ret:
    add rsp, 0x20
    pop rdi
    pop r13
    pop rbx
    ret

// wrap_absorb(rcx = the absorber's battle record, rdx = the defeated unit's battle record)
//   -> damage_after_hit_evaluate's absorption pass FUN_140200D20 (its only call site).
// The original runs first (so vanilla 6032 keeps behaving exactly as before), then every absorb row the
// absorber carries adds its own percentage of the defeated unit's six stats to the same stat-record
// accumulator D5 uses (stat record +0x5A8, six qwords).  evil_absorb_reapply adds that accumulator into
// the max stats at the next recalc.  Values are clamped to 0..20000000, as the game clamps them.
wrap_absorb:
    mov r11d, 0xE70014
    push rbx
    push rsi
    push r13
    push r14
    push rdi
    sub rsp, 0x30
    mov qword ptr [rsp + 0x20], rcx
    mov r13, rdx
    call 0x140200d20
    mov rcx, qword ptr [rsp + 0x20]
    test rcx, rcx
    jz .ab_done
    test r13, r13
    jz .ab_done
    mov rsi, qword ptr [rcx + 0x240]        // the absorber's unit record
    test rsi, rsi
    jz .ab_done
    mov rbx, qword ptr [r13 + 0x240]        // the defeated unit's unit record
    test rbx, rbx
    jz .ab_done
    mov edi, 1048576
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                       // summed percentage of this unit's absorb rows
    mov r14d, eax
    test r14d, r14d
    jz .ab_done
    mov eax, dword ptr [rsi + 0x4348]
    cmp eax, 0x28a
    jae .ab_done
    imul rax, rax, 0xe98
    mov rcx, 0x141067dc8
    add rcx, rax                            // the absorber's stat record
    xor r13d, r13d
.ab_loop:
    cmp r13d, 6
    jae .ab_done
    mov rax, qword ptr [rbx + r13*8 + 0x2ce8]   // the defeated unit's stat k (ATK..SPD)
    movsxd rdx, r14d
    imul rax, rdx
    cqo
    mov r8d, 100
    idiv r8
    add qword ptr [rcx + r13*8 + 0x5a8], rax
    mov rdx, qword ptr [rcx + r13*8 + 0x5a8]
    test rdx, rdx
    jns .ab_hi
    xor edx, edx
    jmp .ab_store
.ab_hi:
    mov rax, 0x1312d00
    cmp rdx, rax
    jle .ab_store
    mov rdx, rax
.ab_store:
    mov qword ptr [rcx + r13*8 + 0x5a8], rdx
    inc r13d
    jmp .ab_loop
.ab_done:
    add rsp, 0x30
    pop rdi
    pop r14
    pop r13
    pop rsi
    pop rbx
    ret

// --------------------------------------------------------------------------------------------- OLEFFECTS
// Four more Overlord effects, ported from Cryswar's Overlord (The Unlicense) as CALL redirections at the
// game's own static call sites -- never an entry patch or a mid-function stub, which is what Overlord does:
//   revenge  (permanent_revenge)   turn_per_unit_end_round_upkeep 0x1401E5AF0, its only static site 0x1405F8FFC
//   steal    (steal_on_kill_percent) the Cat Burglar accumulation call 0x1401AF6A2 -> victim eligibility
//   sp_drain (sp_drain_per_turn)   the SP-recovery-percent call 0x140552083 -> 0x1401EE010, inside
//                                  turn_t1_per_unit_hp_sp
//   overload (block_overload)      cmdmenu_preds_p_15dbf0 0x14015DBF0, all 11 static sites
// `squad` (stat_per_squad_unit) needs no hook of its own: it is scale kind 9 above.

// evil_has_id(rcx = unit record, edx = evility id) -> eax = 1 when the unit has learned that id.
// A linear scan of the same learned list (count +0x3030, sorted ids +0x2F30) evil_type walks.  Used only to
// avoid applying a native revenge pair twice when a unit carries both vanilla 150/6145/5026 and our row.
evil_has_id:
    xor eax, eax
    test rcx, rcx
    jz .hi_ret
    mov r8d, dword ptr [rcx + 0x3030]
    test r8d, r8d
    js .hi_ret
    cmp r8d, 64
    jbe .hi_cap
    mov r8d, 64
.hi_cap:
    xor r9d, r9d
.hi_loop:
    cmp r9d, r8d
    jae .hi_ret
    cmp dword ptr [rcx + r9*4 + 0x2f30], edx
    je .hi_yes
    inc r9d
    jmp .hi_loop
.hi_yes:
    mov eax, 1
.hi_ret:
    ret

tramp_endround:
    sub rsp, 0x28
    call 0x1401e5af0
    add rsp, 0x28
    ret

// wrap_revenge(rcx = unit record, rdx = the unit's battle record) -> turn_per_unit_end_round_upkeep.
// The original runs first and untouched; then, for a unit carrying a revenge row, the game's own revenge
// pair -- the gauge effect 0x140161A20(unit, 6, brec, 0, 0) and the status set 0x140161790(unit, 0x1A, 99, 99)
// -- is issued once, exactly as vanilla Endless Animosity (150) and the two other native revenge ids
// (6145, 5026) do for themselves inside the same function.  A unit carrying one of those three is skipped so
// the native pair is never issued twice (Overlord's own guard, 10_evility_runtime.c:683).
// Timing differs from Overlord in one redocumented way: Overlord patches two mid-function bytes and runs
// after the 150 block only; this wrapper runs after the whole end-of-round upkeep, so it is one pass later
// inside the same round edge and is skipped for all three native ids rather than one.
wrap_revenge:
    mov r11d, 0xE70015
    push rbx
    push rbp
    push rsi
    push rdi
    push r12
    sub rsp, 0x30
    mov qword ptr [rsp + 0x28], rcx     // unit (0x28: 0x20 is the outgoing home/5th-argument slot)
    mov r12, rdx                        // the battle record
    call tramp_endround
    mov rbx, rax                        // the original's answer, restored on the way out
    mov rcx, qword ptr [rsp + 0x28]
    test rcx, rcx
    jz .rv_done
// EVILFX1 rearm_first_damage: D5's own First Impression (6047) nullifies damage while the defender's stat
// record byte +0xDF9 is 0, and damage_apply_damage (0x1401B1FD0) sets that byte to 1 on the first damage the
// unit takes in the stage.  Nothing else reads or writes it (decomp: only damage_apply_damage,
// damage_nullify_predicate and the forecast text 0x14020D1C0 touch stat record +0xDF9).  A unit carrying a
// rearm row gets the byte cleared here, once per unit per round edge, so its 6047 (added by the class alias
// hook) nullifies the first damage of every turn -- D4 Tyrant Guard 667, whose own counter (unit +0x1183)
// is reset by D4's per-unit turn upkeep FUN_1400f3c20.
    mov rsi, rcx
    mov edi, 67108864
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .rv_rearm_done
    mov rcx, qword ptr [rsp + 0x28]
    mov eax, dword ptr [rcx + 0x4348]
    cmp eax, 0x28a
    jae .rv_rearm_done
    imul rax, rax, 3736
    mov rdx, 0x141067dc8
    mov byte ptr [rdx + rax + 0xdf9], 0
.rv_rearm_done:
    mov rcx, qword ptr [rsp + 0x28]
    mov edx, 150
    call evil_has_id
    test eax, eax
    jnz .rv_done
    mov rcx, qword ptr [rsp + 0x28]
    mov edx, 6145
    call evil_has_id
    test eax, eax
    jnz .rv_done
    mov rcx, qword ptr [rsp + 0x28]
    mov edx, 5026
    call evil_has_id
    test eax, eax
    jnz .rv_done
    mov rsi, qword ptr [rsp + 0x28]
    mov edi, 2097152
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .rv_done
    mov rcx, qword ptr [rsp + 0x28]
    mov edx, 6
    mov r8, r12
    xor r9d, r9d
    mov qword ptr [rsp + 0x20], 0
    call 0x140161a20
    mov rcx, qword ptr [rsp + 0x28]
    mov edx, 0x1a
    mov r8d, 99
    mov r9d, 99
    call 0x140161790
.rv_done:
    // NEMO1: summon_malice (second-word bit 13): evil_nemo(unit record, battle record) -- once per unit per round edge, after everything above
    mov rcx, qword ptr [rsp + 0x28]
    mov rdx, r12
    call evil_nemo
    mov rax, rbx
    add rsp, 0x30
    pop r12
    pop rdi
    pop rsi
    pop rbp
    pop rbx
    ret

// wrap_steal(rcx = the victim actor) -- the site is the victim-eligibility `call` (0x140203A40) in
// damage_after_hit_evaluate's defeat path, reached after vanilla has accumulated the Cat Burglar (3036)
// chance into esi.  rbx still holds the killer's *unit record* there (the site tests it for 0x4B2/0xBDC just
// before), so the rows are summed for that unit; the number is added to esi and the original call is then
// made unchanged.  Overlord reads the killer actor from r15 and goes through [r15+0x240]; the unit record it
// arrives at is the same one rbx already holds at this site, and taking it directly needs no new assumption.
// The result is clamped to 0..100 exactly as Overlord clamps it (10_evility_runtime.c:748): the caller rolls
// 0..99 and compares.  esi is a nonvolatile register the *caller* reads afterwards, so the merged chance is
// written into the saved esi slot and `pop rsi` loads it: the frame still reverses exactly.
wrap_steal:
    mov r11d, 0xE70016
    push rbx
    push rsi
    push rbp
    push rdi
    sub rsp, 0x28
    mov qword ptr [rsp + 0x20], rcx     // the victim actor: the original call's own argument
    mov ebp, esi                        // the vanilla accumulated chance
    mov rsi, rbx                        // the killer's unit record
    mov edi, 8388608
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum
    add eax, ebp
    test eax, eax
    jns .st_hi
    xor eax, eax
.st_hi:
    cmp eax, 100
    jle .st_ok
    mov eax, 100
.st_ok:
    mov dword ptr [rsp + 0x38], eax     // the caller's esi: the value `pop rsi` below restores
    mov rcx, qword ptr [rsp + 0x20]
    call 0x140203a40                    // the original victim-eligibility check, unchanged
    add rsp, 0x28
    pop rdi
    pop rbp
    pop rsi
    pop rbx
    ret

// wrap_spdrain(rcx = the actor whose round-edge SP is being settled) -> the game's SP-recovery percentage
// (0x1401EE010), called from turn_t1_per_unit_hp_sp at 0x140552083.
// Vanilla then computes `drain_percent - (regen + our rows)`: a positive row drains that much more of the
// unit's maximum SP, a negative one restores it, which is exactly Overlord's effect on the same number
// (apply_custom_sp_drain adds to the drain percent; 10_evility_runtime.c:753).
wrap_spdrain:
    mov r11d, 0xE70017
    push rsi
    push rdi
    push rcx
    sub rsp, 0x30
    mov qword ptr [rsp + 0x20], rcx     // the actor (a battle record; +0x240 is its unit record)
    call 0x1401ee010
    mov dword ptr [rsp + 0x28], eax
    mov rcx, qword ptr [rsp + 0x20]
    test rcx, rcx
    jz .sd_done
    mov rsi, qword ptr [rcx + 0x240]
    test rsi, rsi
    jz .sd_done
    mov edi, 16777216
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum
    add dword ptr [rsp + 0x28], eax
.sd_done:
    mov eax, dword ptr [rsp + 0x28]
    add rsp, 0x30
    pop rcx
    pop rdi
    pop rsi
    ret

// wrap_overload(rcx = unit record) -> cmdmenu_preds_p_15dbf0, the central unit -> Overload-id resolver that
// battle command availability and execution both ask.  Returning 0 is the game's own "no Overload" answer,
// so the command is greyed and refused -- the same thing Overlord's entry stub does
// (hook_overload_id_resolver, 10_evility_runtime.c:1476).
wrap_overload:
    mov r11d, 0xE70018
    push rbx
    push rsi
    push rdi
    push rdx
    push r8
    push r9
    push rcx
    sub rsp, 0x30
    mov rsi, rcx
    mov edi, 4194304
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    mov rcx, qword ptr [rsp + 0x30]
    mov rdx, qword ptr [rsp + 0x48]
    mov r8, qword ptr [rsp + 0x40]
    mov r9, qword ptr [rsp + 0x38]
    test eax, eax
    jz .ov_orig
    xor eax, eax                        // blocked: the game's own "no Overload" answer
    jmp .ov_done
.ov_orig:
    call 0x14015dbf0                    // no row: the vanilla resolver, in its own frame
.ov_done:
    add rsp, 0x30
    pop rcx
    pop r9
    pop r8
    pop rdx
    pop rdi
    pop rsi
    pop rbx
    ret



// Overlord's element-resistance modifier pass, redirected from unit_recalc's game CALL.
// Five arguments: rcx=unit, rdx=battle context, r8=18-dword accumulator, r9=HP%, stack=SP%.
wrap_resistance:
    mov r11d, 0xE70019
    push rdi
    push rsi
    sub rsp, 0x48
    mov qword ptr [rsp + 0x28], rcx
    mov qword ptr [rsp + 0x30], r8
    mov rax, qword ptr [rsp + 0x80]
    mov qword ptr [rsp + 0x20], rax
    call 0x1401f2a10
    mov qword ptr [rsp + 0x38], rax
    mov rsi, qword ptr [rsp + 0x28]
    mov rdx, qword ptr [rsp + 0x30]
    mov edi, 33554432
    xor r8d, r8d
    xor r9d, r9d
    call evil_apply
    mov rax, qword ptr [rsp + 0x38]
    add rsp, 0x48
    pop rsi
    pop rdi
    ret

// EVILCAP1: wrap_spdmg -- the Skill-row lookup FUN_1401ADA40 makes for D5's Habitual Licker (3011, "25 % of the damage
// inflicted by an attack is also inflicted to SP"), redirected at its only site 0x1401ADDF0:
// damage_skill_dat(rcx, edx = 0xBC3).  The caller reads one dword of the row it gets back, +0x38 (the percent), and
// applies floor(damage * percent / 100) to the target's SP with its own code (deploy_env_deploy_env_box_apply_damage).
// FUN_1401ADA40 keeps the attacker's battle record in rbx, the target's in r13 and the action context in r15 for
// its whole body (set once at 0x1401ADA69..87, never written again), so at this call they are the attacker, target
// and action.  When the attacker has sp_damage_percent rows whose conditions hold and their sum is positive, the
// wrapper hands back a row whose +0x38 is that sum instead; otherwise the game's own row, unchanged.  The branch is
// only reached while the attacker carries 3011, so a mod row pairs this family with an alias of its id to 3011.
wrap_spdmg:
    mov r11d, 0xE7001A
    push rsi
    push rdi
    sub rsp, 0x38
    call 0x14008d0f0                    // damage_skill_dat: the game's own row for 3011 (rcx, edx untouched)
    mov qword ptr [rsp + 0x20], rax
    mov rsi, qword ptr [rbx + 0x240]    // the attacker's unit record
    test rsi, rsi
    jz .spd_done
    mov edi, 268435456
    mov rdx, r13                        // the target's battle record
    mov r8, r15                         // the action context
    xor r9d, r9d
    call evil_dmg_sum
    test eax, eax
    jle .spd_done
    lea rcx, [rip + evil_spdmg_row]
    mov dword ptr [rcx + 0x38], eax
    mov qword ptr [rsp + 0x20], rcx
.spd_done:
    mov rax, qword ptr [rsp + 0x20]
    add rsp, 0x38
    pop rdi
    pop rsi
    ret

// LONGTAIL2: wrap_maxrefl -- the Skill-row lookup FUN_1401ADA40 makes for D5's Malicious Reflect (143, "Inflict 10 % of damage
// taken to attacker"), redirected at its only site 0x1401AE531: damage_skill_dat(rcx = index, edx = 0x8F).  The caller then
// reads rdi (the damage the defender took, a positive qword it loaded from the action context at 0x1401AE51B) and the row's
// +0x38 (the percent), computes trunc(percent / 100.0f * (float)rdi), clamps it below the attacker's current HP and applies it
// to the attacker (0x1401AE541..0x1401AE5BB).  Registers at the call: rbx = the attacker (the unit that gets hurt), r13 = the
// defender (the unit that searched positive for 143), r15 = the action context, rdi = the damage taken, xmm6 = 100.0f.
// For a defender holding a max_hp_reflect row (second-word bit 9) the wrapper hands back a row whose +0x38 is 100 AND replaces
// rdi with P percent of the ATTACKER's max HP (unit record +0x2CD8), so the game's own arithmetic gives that amount and its own
// clamp keeps it from killing.  Writing rdi is the one deliberate departure from "return everything unchanged": rdi is dead
// after 0x1401AE541 (both of its later writes, 0x1401AE572 and 0x1401AE582, reload it from [rbx + 0x240] before any read), and
// the only reader between the call and that overwrite is the cvtsi2ss at 0x1401AE541 we mean to feed.  A defender without the
// row (the real 143 alone) gets the game's own row and the untouched rdi.
wrap_maxrefl:
    mov r11d, 0xE70025
    push rsi
    push rdi
    sub rsp, 0x38
    call 0x14008d0f0                    // damage_skill_dat: the game's own row for 143 (rcx, edx untouched)
    mov qword ptr [rsp + 0x20], rax
    mov rsi, qword ptr [r13 + 0x240]    // the defender's unit record: the holder
    test rsi, rsi
    jz .mr_done
    mov rax, qword ptr [rbx + 0x240]    // the attacker's unit record
    test rax, rax
    jz .mr_done
    mov rax, qword ptr [rax + 0x2cd8]   // the attacker's max HP
    mov qword ptr [rsp + 0x28], rax
    mov rdi, 0x20000000000              // max_hp_reflect: second-word bit 9
    mov rdx, rbx                        // the other side: the attacker's battle record
    mov r8, r15                         // the action context
    xor r9d, r9d
    call evil_dmg_sum                   // eax = P percent, 0 for a defender without the row
    test eax, eax
    jle .mr_done
    cdqe
    imul rax, qword ptr [rsp + 0x28]    // max HP x P
    mov ecx, 100
    cqo
    idiv rcx
    mov qword ptr [rsp + 0x38], rax     // the amount goes into rdi's saved slot: the canonical epilogue's pop hands it to the game
    lea rcx, [rip + evil_spdmg_row]
    mov dword ptr [rcx + 0x38], 100     // 100 / 100.0f x amount = amount
    mov rax, rcx
    add rsp, 0x38
    pop rdi                             // the only register the wrapper changes besides the volatile ones
    pop rsi
    ret
.mr_done:
    mov rax, qword ptr [rsp + 0x20]
    add rsp, 0x38
    pop rdi
    pop rsi
    ret

// D4SIG3: wrap_support -- FUN_1401FEFA0(rcx = int* value, rdx, r8 = the caster's battle record, r9, [stack] = the
// action's skill id pointer), redirected at both static callers (0x1401C0076 damage_buff_compute_buff, 0x140201F03 the
// skill-value preview).  The game's function multiplies *rcx by the +0x38 of D5's Medical Insertion (1180) row when the
// caster learned 1180 and the skill is support magic (magic row +0x3F6 == 5).  The wrapper first keeps the value, runs
// the game's own function (unchanged behaviour for every unit without a support_magic_percent row), then, when the
// caster's rows sum to a positive percent and the same support-magic test holds, writes value * (100 + percent) / 100
// (signed truncation, as D4's FUN_1400FF700 computes it) over the result.  The inner damage_skill_dat call at
// 0x1401FF046 cannot be wrapped for this: r8, rax and r10 (the caster) are all dead after the magic-row lookup there.
wrap_support:
    mov r11d, 0xE7001B
    push rbx
    push rsi
    push rdi
    sub rsp, 0x40
    mov rbx, rcx                        // the value the game multiplies
    mov rsi, r8                         // the caster's battle record
    mov eax, dword ptr [rcx]
    mov dword ptr [rsp + 0x28], eax     // the value before the game's own multiply
    mov rax, qword ptr [rsp + 0x80]     // stack argument 5, forwarded
    mov qword ptr [rsp + 0x20], rax
    call 0x1401fefa0                    // the game's own function (rcx, rdx, r8, r9 as received)
    test rsi, rsi
    jz .sup_done
    mov rsi, qword ptr [rsi + 0x240]    // the caster's unit record
    test rsi, rsi
    jz .sup_done
    mov rax, qword ptr [rsp + 0x80]
    test rax, rax
    jz .sup_done
    mov edx, dword ptr [rax]            // the same support-magic test FUN_1401FEFA0 makes
    xor ecx, ecx
    call 0x140061ff0                    // unit_stats_skills_magic_row
    test eax, eax
    js .sup_done
    cdqe
    imul rax, rax, 0x474
    mov rcx, 0x140a03868
    add rax, qword ptr [rcx]
    jz .sup_done
    cmp byte ptr [rax + 0x3f6], 5
    jne .sup_done
    mov edi, 536870912                  // F_SUPPORT
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                   // rsi = the caster's unit record
    test eax, eax
    jle .sup_done
    add eax, 100
    imul eax, dword ptr [rsp + 0x28]
    cdq
    mov ecx, 100
    idiv ecx
    mov dword ptr [rbx], eax
.sup_done:
    add rsp, 0x40
    pop rdi
    pop rsi
    pop rbx
    ret

// D4SIG4: wrap_equip -- unit_stats_equip_stat(rcx = the unit record, edx = slot, r8d = stat, r9 = the tier counts), redirected at
// the eight static calls in unit_recalc.  The game's function returns the slot's contribution to one stat; the item is a weapon
// when its category byte (+0x156 of the slot's 600-byte entry) is 1..9, the same test the function itself makes.  For a weapon
// slot the wrapper scales that result by (100 + percent) / 100 (signed truncation), the percent being the unit's weapon_percent
// rows (aura rows = the allies' Everyone's Mechanic) summed and capped at 100, as D4's FUN_1401B4010 caps its sum.
// Every other unit, slot and stat is returned as the game computed it.
wrap_equip:
    mov r11d, 0xE7001C
    push rbx
    push rsi
    push rdi
    sub rsp, 0x30
    mov rsi, rcx                        // the unit record
    movsxd rbx, edx                     // the slot
    call 0x140219630                    // the game's own function (rcx, rdx, r8, r9 as received)
    mov qword ptr [rsp + 0x20], rax
    test rax, rax
    jz .eq_done
    test rsi, rsi
    jz .eq_done
    imul rcx, rbx, 600
    movzx eax, byte ptr [rsi + rcx + 0x156]
    dec eax
    cmp eax, 9
    jae .eq_done                        // not a weapon category
    mov edi, 1073741824                 // F_WEAPON
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                   // rsi = the unit record
    test eax, eax
    jle .eq_done
    mov ecx, 100
    cmp eax, ecx
    cmovg eax, ecx                      // the source cap: the summed percent stops at 100
    add eax, 100
    cdqe
    imul rax, qword ptr [rsp + 0x20]
    cqo
    mov ecx, 100
    idiv rcx
    mov qword ptr [rsp + 0x20], rax
.eq_done:
    mov rax, qword ptr [rsp + 0x20]
    add rsp, 0x30
    pop rdi
    pop rsi
    pop rbx
    ret

// D4SIG6: wrap_firstimp -- cmdmenu_preds_p_2068b0(rcx = unit record, edx = evility id) -> al, redirected at the ONE call inside
// damage_nullify_predicate that asks whether the defender carries First Impression (6047, 0x1401FE3B3; the byte test of stat
// record +0xDF9 follows it).  The game's answer is returned unchanged unless the defender also holds a rearm_first_damage row
// (D4 Tyrant Guard 667) and the hit is lethal: D4's FUN_1400FF700 nullifies a hit only while the resulting HP stays above 0
// (`if (lVar26 < 1) keep the lethal result`), D5's 6047 test has no damage test at all.  For such a unit a hit whose damage v
// is at least its current HP (unit +0x2CC8) is answered "not carried", so the predicate goes on as for any unit without 6047.
// v is the predicate's own sixth argument: the caller's frame is fixed (7 pushes + sub 0x450, v at [S + 0x4B8] where S is the
// rsp at this call; wrapper entry is S - 8, three pushes and sub 0x30 below that, so v is at [rsp + 0x508]).
wrap_firstimp:
    mov r11d, 0xE7001D
    push rbx
    push rsi
    push rdi
    sub rsp, 0x30
    mov rbx, rcx                        // the unit record
    call 0x1402068b0                    // the game's answer for 6047 (rcx, edx as received)
    test al, al
    jz .fi_ret                          // not carried: nothing to decide
    test rbx, rbx
    jz .fi_yes
    mov rsi, rbx
    mov edi, 67108864                   // F_REARM: the Tyrant Guard holders only
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .fi_yes                          // First Impression as the game has it
    mov rax, qword ptr [rsp + 0x508]    // v, the damage of this hit
    cmp rax, qword ptr [rbx + 0x2CC8]   // current HP
    jl .fi_yes                          // non-lethal: nullified as before
    xor eax, eax                        // lethal: D4 lets it through
    jmp .fi_ret
.fi_yes:
    mov eax, 1
.fi_ret:
    add rsp, 0x30
    pop rdi
    pop rsi
    pop rbx
    ret

// MASKWIDE1: wrap_face_away(rcx = ctl, rdx = action context, r8 = the attacker's battle record) -> post_hit_effects 0x140542CB0, the
// once-per-action pass in exec_ctl_s2_update, reached after the action's script has ended and every target's vertical speed is 0.
// D4 Death Saber 836 (evility 0x344), FUN_1402DD8B0: for each target whose killed flag is 0 and which is within footprint distance 1 of
// the attacker (FUN_1400ED660 = D5 ai_transition_within_range 0x140153FF0, same argument order), the target is turned to
// FUN_14022F350(target x, target z, attacker x, attacker z), computed inline since D4SIG9 (D5's carry_throw_facing_angle 0x1402D8D60 uses
// atan2 and differs for a zero distance, exact 45 degree ties and the truncated negative bucket edges), with unit_set_facing 0x14014F640
// (D4 FUN_1400F1230 + FUN_1400F3EE0; D5 stores 180 as -180).  So the target faces directly AWAY from the attacker.
// The attacker must hold a second-word family row `face_target_away` (query = bit 32 of rdi).  Done BEFORE the game's own pass, as D4
// does it ahead of its other end-of-action work; the game's call is then made with the arguments it was entered with.
// Action context: target count short at +0x27318, target j at +0x1318 + j*0x260: short battle slot at +0, killed flag byte at +0x216.
wrap_face_away:
    mov r11d, 0xE7001E
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x38
    mov r12, rcx                        // ctl
    mov r13, rdx                        // action context
    mov r14, r8                         // attacker battle record
    test r14, r14
    jz .fa_call
    test r13, r13
    jz .fa_call
    mov rsi, qword ptr [r14 + 0x240]    // the attacker's unit record
    test rsi, rsi
    jz .fa_call
    // D4SIG7: D4 FUN_1402DD8B0 clears the actor's attack counter (unit +0x20D5) at the end of every action; the holder of an
    // `attack_counter` row (second-word bit 2) has D5's Impact Charge counter, the short at stat record +0x5D8, set to 0 here.
    mov rdi, 0x400000000                // F2_ATTACK_COUNTER
    xor edx, edx
    mov r8, r13
    xor r9d, r9d
    call evil_pred
    mov rsi, qword ptr [r14 + 0x240]    // evil_pred keeps rsi; reloaded for clarity
    test eax, eax
    jz .fa_face
    mov eax, dword ptr [rsi + 0x4348]
    cmp eax, 0x28a
    jae .fa_face                        // no stat record
    imul rax, rax, 0xe98
    mov rcx, 0x1410683a0                // 0x141067DC8 + 0x5D8
    mov word ptr [rax + rcx], 0
.fa_face:
    mov rdi, 0x100000000                // F2_FACE_TARGET_AWAY: second-word bit 0
    xor edx, edx
    mov r8, r13                         // the action context, for the row's conditions
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .fa_boom
    movsx r15d, word ptr [r13 + 0x27318]
    cmp r15d, 256
    jbe .fa_count_ok
    xor r15d, r15d                      // garbage count: do nothing
.fa_count_ok:
    xor ebx, ebx                        // target index
.fa_loop:
    cmp ebx, r15d
    jae .fa_boom
    imul ebp, ebx, 0x260
    cmp byte ptr [r13 + rbp + 0x152e], 0 // D4 killed flag (S2's own "KO'd targets are skipped" byte)
    jne .fa_next
    movsx eax, word ptr [r13 + rbp + 0x1318]
    cmp eax, 256
    jae .fa_next                        // slot out of range (also catches -1)
    imul rax, rax, 0x1260
    mov rsi, 0x141ba33b0
    add rsi, rax                        // the target's battle record
    cmp byte ptr [rsi + 0x2e8], 0       // active
    je .fa_next
    cmp qword ptr [rsi + 0x240], 0      // has a unit record
    je .fa_next
    mov rcx, r14
    mov rdx, rsi
    mov r8d, 1
    mov r9d, -1
    call 0x140153ff0                    // ai_transition_within_range(attacker, target, 1, -1): footprint distance 1 or less
    test al, al
    jz .fa_next
    cvttss2si ecx, dword ptr [rsi + 8]  // (int)(float) world x / z, as D4 casts them
    cvttss2si edx, dword ptr [rsi + 0x10]
    cvttss2si r8d, dword ptr [r14 + 8]
    cvttss2si r9d, dword ptr [r14 + 0x10]
    // D4SIG9: D4 FUN_14022F350(tx, tz, ax, az) exactly, in integers (D5's carry_throw_facing_angle differs for a zero distance and
    // for exact / truncated 45 degree ties): dx = tx - ax, dz = tz - az; dx <= 0 and |dz| < |dx| -> -90; dx > 0 and |dz| < |dx| -> 90;
    // otherwise dz > 0 -> 0, else 180 (so a zero distance gives 180).
    sub ecx, r8d                        // dx
    sub edx, r9d                        // dz
    mov r8d, ecx
    neg r8d
    cmovs r8d, ecx                      // |dx|
    mov r9d, edx
    neg r9d
    cmovs r9d, edx                      // |dz|
    cmp r9d, r8d
    jge .fa_zaxis                       // |dz| >= |dx|
    mov eax, 90
    test ecx, ecx
    jg .fa_turn                         // dx > 0
    mov eax, -90
    jmp .fa_turn
.fa_zaxis:
    xor eax, eax
    test edx, edx
    jg .fa_turn                         // dz > 0
    mov eax, 180
.fa_turn:
    mov rcx, rsi
    mov edx, eax
    call 0x14014f640                    // unit_set_facing(target, angle)
.fa_next:
    inc ebx
    jmp .fa_loop
.fa_boom:
    // LONGTAIL3: self_destruct (second-word bit 11; D4 Battle Suit 802 "Self-destruct when HP hits below 10% by an attack").  D4 tests evility 0x322
    // with FUN_14010DE70 (HP <= trunc(max HP x percent / 100), unit +0xD10 <= +0xD20 x percent / 100) and then plays effect 0x816 and applies the
    // unit's own HP to itself (FUN_140190F90); D5's counterpart is FUN_1401A3E80(unit object, 1), the explosion of an explosive unit that lands
    // (carry_land 0x1406357E0): blast of 50 percent of current HP over its own area, then the unit's HP applied to itself.  Here, once per action
    // and BEFORE the game's own post_hit_effects: every target entry whose result is a positive amount (a real hit: not a miss, a buff, a nullified
    // hit or a heal of skill category 4) and whose KO byte is 0, whose unit is active, alive (HP > 0), not already exploding (+0x11DC == 0) and holds
    // the row, with HP <= trunc(max HP x P / 100), explodes.  Forecasts never reach this pass.
    movsx r15d, word ptr [r13 + 0x27318]
    cmp r15d, 256
    jbe .sd_count_ok
    xor r15d, r15d                      // garbage count: do nothing
.sd_count_ok:
    xor ebx, ebx
.sd_loop:
    cmp ebx, r15d
    jae .nc_run
    imul ebp, ebx, 0x260
    cmp qword ptr [r13 + rbp + 0x1328], 0
    jle .sd_next                        // no result, a miss, a buff or a nullified hit
    cmp byte ptr [r13 + rbp + 0x152e], 0
    jne .sd_next                        // defeated by this action
    mov r8, qword ptr [r13 + 0x27678]   // the action's skill row
    test r8, r8
    jz .sd_nh                           // a normal attack
    cmp byte ptr [r8 + 0x3f6], 4
    je .sd_next                         // a heal (D5 stores its amount as a positive result)
.sd_nh:
    movsx eax, word ptr [r13 + rbp + 0x1318]
    cmp eax, 256
    jae .sd_next                        // slot out of range (also catches -1)
    imul rax, rax, 0x1260
    mov rsi, 0x141ba33b0
    add rsi, rax                        // the target's battle record
    cmp byte ptr [rsi + 0x2e8], 0
    je .sd_next                         // not active
    cmp dword ptr [rsi + 0x11dc], 0
    jne .sd_next                        // already exploding: never processed twice
    mov qword ptr [rsp + 0x20], rsi
    mov rsi, qword ptr [rsi + 0x240]    // the unit record
    test rsi, rsi
    jz .sd_next
    cmp qword ptr [rsi + 0x2cc8], 0
    jle .sd_next                        // already down
    mov rdi, 0x80000000000              // F2_SELF_DESTRUCT: second-word bit 11
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                   // eax = P percent, 0 for a unit without the row
    test eax, eax
    jle .sd_next
    mov rsi, qword ptr [rsp + 0x20]
    mov rsi, qword ptr [rsi + 0x240]
    cdqe
    imul rax, qword ptr [rsi + 0x2cd8]  // max HP x P
    mov ecx, 100
    cqo
    idiv rcx                            // trunc(max HP x P / 100), D4's own integer division
    cmp qword ptr [rsi + 0x2cc8], rax
    jg .sd_next                         // HP above the threshold
    mov rcx, qword ptr [rsp + 0x20]
    mov edx, 1                          // the flag carry_land passes
    call 0x1401a3e80                    // FUN_1401A3E80(unit object, 1): the native explosion
.sd_next:
    inc ebx
    jmp .sd_loop
.nc_run:
    // NECRO1: raise_zombie (second-word bit 12): evil_necro(ctx, attacker battle record) raises a zombie for each target the holder defeated
    mov rcx, r13
    mov rdx, r14
    call evil_necro
.fa_call:
    mov rcx, r12
    mov rdx, r13
    mov r8, r14
    call 0x140542cb0
    add rsp, 0x38
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// NECRO2: Necromancy is two routines.  NECRO1 raised the zombie from the end-of-action pass (wrap_face_away) by reading the victim's battle record
// there; live (LIVEFX5) nothing came.  Reading from the code (not yet seen live): damage_after_hit_evaluate 0x1401AEB10 sets the victim's HP to 0 and
// a 20-tick countdown (+0x2B2); model_update_sweep_units 0x1404A8D10 ticks it every frame (battle_unit_update 0x14015A1B0) and, at 0, retires the
// unit (record_release, battle_unit_reset 0x14015B9E0 clears +0x2E8, an enemy-pool record is zeroed), all while the action's script (a skill's
// recoil and return take far longer than 20 frames) is still running; exec_ctl_s2_update's end pass comes after the script.  So at the end pass a
// victim of the action is usually no longer active and its record no longer holds its cell or level.  Now evil_necro_note (called by wrap_atkcount
// right after the game's damage_apply_damage, where the victim's record is whole) copies the victim's cell, facing, level and the zombie's team into
// the kit's queue evil_zq, and evil_necro (end pass) spawns from the queue.
// evil_zq: +0 attacker battle record the notes belong to, +8 count, +16 up to 16 entries of 32 bytes {x, y, z (floats), facing, level, team, 8 pad}.
// evil_zdbg (dwords): 0 note routine entered by a holder, 1 note stored, 2 end pass found this attacker's queue header (set by any note call of a holder), 3 entry skipped (living unit on the
// cell), 4 spawn called, 5 spawn gave a slot, 6 spawn refused, 7 note dropped (queue full), 8 end pass entered by any attacker, 9 entry skipped (32 limit).
// evil_necro_note(rcx = attacker battle record, rdx = target battle record, r8 = action context, r9d = target index), after the real damage_apply_damage.
// D4 FUN_1401946B0 marks a defeated hostile unit; the retire block FUN_140302530 builds a class-0x820 unit on its cell (team 3 holder / 1).  D5 stand-in:
// the attacker holds the row (second-word bit 12), the target's KO byte (ctx +0x1318 + idx*0x260 + 0x216: the game sets it only for a real action's
// defeat) is set, its record is active, it has a stat record, HP <= 0, is not an object (events_env_is_object_rec), not already an Undead (char
// 2090..2095), not carried / carrying, is hostile to the holder (model_team_is_hostile on events_env_team_of(,1)) and not team 3, and the holder's team
// is 0, 1, 4 or 5 (0 -> 4, the AI-run friendly team).  Preserves every nonvolatile register; fixed frame 8 pushes + 0x78, request-free.
evil_necro_note:
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x78
    mov rbx, r8                         // action context
    mov r12, rcx                        // attacker battle record
    mov r14, rdx                        // target battle record
    mov r13d, r9d                       // target index
    test rbx, rbx
    jz .nn_ret
    test r12, r12
    jz .nn_ret
    test r14, r14
    jz .nn_ret
    mov rsi, qword ptr [r12 + 0x240]    // the attacker's unit record
    test rsi, rsi
    jz .nn_ret
    mov rdi, 0x100000000000             // F2_RAISE_ZOMBIE: second-word bit 12
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .nn_ret                          // not a holder
    inc dword ptr [rip + evil_zdbg]
    lea rsi, [rip + evil_zq]
    cmp qword ptr [rsi], r12
    je .nn_same
    mov qword ptr [rsi], r12            // another attacker: notes of an action whose end pass never came are dropped
    mov dword ptr [rsi + 8], 0
.nn_same:
    test r13d, r13d
    jnz .nn_first
    mov dword ptr [rsi + 8], 0          // target 0 is the first apply of an action: start a fresh list
.nn_first:
    mov rcx, r12
    mov edx, 1
    call 0x14015b910                    // events_env_team_of(holder, 1)
    movzx r15d, al                      // the holder's team
    cmp r15d, 5
    ja .nn_ret
    cmp r15d, 2
    je .nn_ret
    cmp r15d, 3
    je .nn_ret
    mov eax, r15d
    test eax, eax
    jnz .nn_zt
    mov eax, 4                          // a player-side holder: the AI-run friendly team 4
.nn_zt:
    mov dword ptr [rsp + 0x60], eax     // the zombie's team
    cmp r13d, 256
    jae .nn_ret
    imul ebp, r13d, 0x260
    cmp byte ptr [rbx + rbp + 0x152e], 0
    je .nn_ret                          // not defeated by this action
    cmp byte ptr [r14 + 0x2e8], 0
    je .nn_ret                          // not active
    mov rdi, qword ptr [r14 + 0x240]    // the victim's unit record
    test rdi, rdi
    jz .nn_ret
    cmp dword ptr [rdi + 0x4348], 0x28a
    jae .nn_ret                         // no stat record
    cmp qword ptr [rdi + 0x2cc8], 0
    jg .nn_ret                          // still standing
    mov rcx, rdi
    call 0x14021f690                    // events_env_is_object_rec(unit record)
    test al, al
    jnz .nn_ret
    mov eax, dword ptr [rdi + 0x2e04]
    sub eax, 2090
    cmp eax, 5
    jbe .nn_ret                         // already an Undead: no zombie of a zombie
    cmp word ptr [r14 + 0x2ee], 0
    jge .nn_ret                         // carried
    cmp word ptr [r14 + 0x2f0], 0
    jge .nn_ret                         // carrying a unit
    mov rcx, r14
    mov edx, 1
    call 0x14015b910                    // events_env_team_of(victim, 1)
    movzx edx, al
    cmp edx, 3
    je .nn_ret
    mov ecx, r15d
    call 0x1402d9290                    // model_team_is_hostile(holder's team, victim's team)
    test al, al
    jz .nn_ret
    lea rsi, [rip + evil_zq]
    mov eax, dword ptr [rsi + 8]
    cmp eax, 16
    jb .nn_room
    inc dword ptr [rip + evil_zdbg + 28]
    jmp .nn_ret                         // ponytail: 16 victims per action; more are not raised
.nn_room:
    mov rdi, qword ptr [r14 + 0x240]    // reloaded: the calls above may not keep it
    shl eax, 5
    lea rdx, [rsi + rax + 16]
    mov ecx, dword ptr [r14 + 8]
    mov dword ptr [rdx], ecx            // x
    mov ecx, dword ptr [r14 + 0xc]
    mov dword ptr [rdx + 4], ecx        // y
    mov ecx, dword ptr [r14 + 0x10]
    mov dword ptr [rdx + 8], ecx        // z
    movsx ecx, word ptr [r14 + 0x2c4]
    mov dword ptr [rdx + 12], ecx       // facing
    movsx ecx, word ptr [rdi + 0x2dfc]
    mov dword ptr [rdx + 16], ecx       // the victim's level
    mov ecx, dword ptr [rsp + 0x60]
    mov dword ptr [rdx + 20], ecx       // the zombie's team
    inc dword ptr [rsi + 8]
    inc dword ptr [rip + evil_zdbg + 4]
.nn_ret:
    add rsp, 0x78
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// NECRO2: evil_necro(rcx = action context, rdx = the attacker's battle record), called from wrap_face_away's once-per-action pass (the end of the
// action, after its script): spawns a D5 Undead zombie (char 2090) for each entry evil_necro_note queued for this attacker in this action, on the entry's
// cell, while fewer than 32 units live (FUN_1401C3A00, the count Summon Guardian tests) and no living unit stands on the cell: unit_spawn_from_request
// with a 0x40-byte request {+0 0 (build from the char id), +8/+0xC/+0x10 x/y/z, +0x14 facing, +0x18 char 2090, +0x1C level, +0x24 team, +0x2C -1}; then
// the new unit's HP (record +0x2CC8) = 1.  The queue is always emptied.  Fixed frame: 8 pushes + 0x78 keeps every call 16-byte aligned; the request is
// at rsp + 0x20.  Preserves every nonvolatile register.
evil_necro:
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x78
    mov r12, rdx                        // attacker battle record
    inc dword ptr [rip + evil_zdbg + 32]
    test r12, r12
    jz .nc_ret
    lea rbx, [rip + evil_zq]
    cmp qword ptr [rbx], r12
    jne .nc_ret                         // no notes of this action
    inc dword ptr [rip + evil_zdbg + 8]
    mov eax, dword ptr [rbx + 8]
    cmp eax, 16
    jbe .nc_cnt
    xor eax, eax
.nc_cnt:
    mov dword ptr [rsp + 0x64], eax     // the number of entries
    mov qword ptr [rbx], 0              // consumed whatever follows
    mov dword ptr [rbx + 8], 0
    xor r13d, r13d                      // entry index
.nc_loop:
    cmp r13d, dword ptr [rsp + 0x64]
    jae .nc_ret
    mov eax, r13d
    shl eax, 5
    lea r14, [rbx + rax + 16]           // the entry
    inc r13d
    mov rsi, 0x141ba33b0                // no living unit on the cell
    xor ecx, ecx
.nc_cell:
    cmp byte ptr [rsi + 0x2e8], 0
    je .nc_cell_next
    mov rax, qword ptr [rsi + 0x240]
    test rax, rax
    jz .nc_cell_next
    cmp qword ptr [rax + 0x2cc8], 0
    jle .nc_cell_next                   // down
    mov edx, dword ptr [rsi + 8]
    cmp edx, dword ptr [r14]
    jne .nc_cell_next
    mov edx, dword ptr [rsi + 0x10]
    cmp edx, dword ptr [r14 + 8]
    jne .nc_cell_next
    inc dword ptr [rip + evil_zdbg + 12]
    jmp .nc_loop                        // a living unit stands there
.nc_cell_next:
    add rsi, 0x1260
    inc ecx
    cmp ecx, 256
    jb .nc_cell
    call 0x1401c3a00                    // FUN_1401C3A00: the number of living bound units
    cmp eax, 0x20
    jl .nc_room
    inc dword ptr [rip + evil_zdbg + 36]
    jmp .nc_ret                         // the 32-unit limit: no more this action
.nc_room:
    xor eax, eax                        // the request
    mov qword ptr [rsp + 0x20], rax
    mov qword ptr [rsp + 0x28], rax
    mov qword ptr [rsp + 0x30], rax
    mov qword ptr [rsp + 0x38], rax
    mov qword ptr [rsp + 0x40], rax
    mov qword ptr [rsp + 0x48], rax
    mov qword ptr [rsp + 0x50], rax
    mov qword ptr [rsp + 0x58], rax
    mov eax, dword ptr [r14]
    mov dword ptr [rsp + 0x28], eax     // x
    mov eax, dword ptr [r14 + 4]
    mov dword ptr [rsp + 0x2c], eax     // y
    mov eax, dword ptr [r14 + 8]
    mov dword ptr [rsp + 0x30], eax     // z
    mov eax, dword ptr [r14 + 12]
    mov dword ptr [rsp + 0x34], eax     // facing
    mov dword ptr [rsp + 0x38], 2090    // D5 Undead, tier 0 "Zombie"
    mov eax, dword ptr [r14 + 16]
    mov dword ptr [rsp + 0x3c], eax     // the victim's level
    mov eax, dword ptr [r14 + 20]
    mov dword ptr [rsp + 0x44], eax     // the team
    mov dword ptr [rsp + 0x4c], -1      // no variant
    inc dword ptr [rip + evil_zdbg + 16]
    lea rcx, [rsp + 0x20]
    call 0x1401c5ae0                    // unit_spawn_from_request: the battle slot or -1
    cmp eax, 256
    jb .nc_slot
    inc dword ptr [rip + evil_zdbg + 24]
    jmp .nc_loop                        // -1 (no record / no slot) or garbage
.nc_slot:
    inc dword ptr [rip + evil_zdbg + 20]
    imul rax, rax, 0x1260
    mov rcx, 0x141ba33b0
    add rcx, rax
    mov rax, qword ptr [rcx + 0x240]
    test rax, rax
    jz .nc_loop
    mov qword ptr [rax + 0x2cc8], 1     // HP 1
    jmp .nc_loop
.nc_ret:
    add rsp, 0x78
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// NEMO1: evil_nemo(rcx = unit record, rdx = the unit's battle record), called from wrap_revenge, the wrapper of the round-edge sweep's one call of
// turn_per_unit_end_round_upkeep (0x1405F8FFC in turn_ctl_s6_update: once per active unit per round, all teams).  D4 Nemo (820 "Physical Malice",
// "Summon a Malice unit to the map on every turn"): FUN_1402E99D0, state 3 of the D4 round-edge state machine FUN_1402EA550, finds the first unit
// holding 820, and while fewer than 32 units live (a failed FUN_1402AD4C0 returns -1) draws a Malice class (char 0x14D2 + rand 0x27), a level
// L*60/100 + rand(0x28)*L/100 (min 1; L = the holder's level) and has FUN_1402AD4C0 create it on a random free walkable cell within 10 cells (a
// square) of the holder, side byte 1.  D5 stand-in: for an active (+0x2E8), living holder of the row (second-word bit 13): with fewer than 32 living
// units (FUN_1401C3A00, the count Summon Guardian tests), events_clear_pick_cell(0x144BD9750) rebuilds the game's free-cell grid exactly as the
// Guardian block of sequencer_ctl_s4_update does; the free cells of the grid inside the square of radius 10 around the holder's cell are counted;
// none -> nothing; else game_rng_draw picks the character from evil_malice_tbl, the level, and the cell (first index = x, second = z, scan order as
// the Guardian block); the request is the Guardian block's: +8/+0xC/+0x10 world x = cell * 12 + 6, y = map_surface_height_at(x, z), z, +0x14 facing
// = FUN_1401367f0() * 90 - 90, +0x18 the character, +0x1C the level, +0x24 the team, +0x2C -1; unit_spawn_from_request is entered once.  Team as
// NECRO1: holder team 0 -> 4, 1 -> 1, 4 -> 4, 5 -> 5; teams 2 and 3 do nothing.  Nothing else is changed (no Guardian reward items, skill bits or
// multipliers).  Fixed frame: 8 pushes + 0x78 keep every call 16-byte aligned; the request is at rsp + 0x20, the window bounds at rsp + 0x60..0x6C.
// Preserves every nonvolatile register.
evil_nemo:
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x78
    mov rbx, rcx                        // unit record
    mov r12, rdx                        // battle record
    test rbx, rbx
    jz .nm_ret
    test r12, r12
    jz .nm_ret
    cmp byte ptr [r12 + 0x2e8], 0
    je .nm_ret                          // not on the map
    cmp dword ptr [rbx + 0x4348], 0x28a
    jae .nm_ret                         // no stat record
    cmp qword ptr [rbx + 0x2cc8], 0
    jle .nm_ret                         // defeated
    mov rsi, rbx
    mov rdi, 0x200000000000             // F2_SUMMON_MALICE: second-word bit 13
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .nm_ret                          // not a holder
    mov rcx, r12
    mov edx, 1
    call 0x14015b910                    // events_env_team_of(holder, 1)
    movzx r13d, al                      // the holder's team
    cmp r13d, 5
    ja .nm_ret
    cmp r13d, 2
    je .nm_ret
    cmp r13d, 3
    je .nm_ret
    test r13d, r13d
    jnz .nm_cap
    mov r13d, 4                         // a player-side holder: the AI-run friendly team 4
.nm_cap:
    call 0x1401c3a00                    // FUN_1401C3A00: the number of living bound units
    cmp eax, 0x20
    jge .nm_ret                         // the 32-unit limit
    mov eax, dword ptr [rip + evil_malice_count]
    test eax, eax
    jle .nm_ret
    mov rcx, 0x144bd9750
    call 0x14023afa0                    // events_clear_pick_cell: the free-cell grid at 0x144DF1790 and its count, as Summon Guardian
    cvttss2si eax, dword ptr [r12 + 8]  // the holder's cell: trunc(x) / 12 and trunc(z) / 12
    test eax, eax
    js .nm_ret
    cdq
    mov ecx, 12
    idiv ecx
    mov r14d, eax                       // cell x
    cvttss2si eax, dword ptr [r12 + 0x10]
    test eax, eax
    js .nm_ret
    cdq
    mov ecx, 12
    idiv ecx
    mov r15d, eax                       // cell z
    xor ecx, ecx                        // the window: radius 10 cells, inside the map extents and the 128 x 128 grid
    lea eax, [r14 - 10]
    test eax, eax
    cmovs eax, ecx
    mov dword ptr [rsp + 0x60], eax     // first x
    mov rdx, 0x144bd9780
    mov ecx, dword ptr [rdx]
    dec ecx
    lea eax, [r14 + 10]
    cmp eax, ecx
    cmovg eax, ecx
    mov ecx, 127
    cmp eax, ecx
    cmovg eax, ecx
    mov dword ptr [rsp + 0x64], eax     // last x
    xor ecx, ecx
    lea eax, [r15 - 10]
    test eax, eax
    cmovs eax, ecx
    mov dword ptr [rsp + 0x68], eax     // first z
    mov rdx, 0x144bd9784
    mov ecx, dword ptr [rdx]
    dec ecx
    lea eax, [r15 + 10]
    cmp eax, ecx
    cmovg eax, ecx
    mov ecx, 127
    cmp eax, ecx
    cmovg eax, ecx
    mov dword ptr [rsp + 0x6c], eax     // last z
    xor r14d, r14d                      // r14d = the number of free cells in the window
    mov esi, dword ptr [rsp + 0x60]
.nm_cx:
    cmp esi, dword ptr [rsp + 0x64]
    jg .nm_cdone
    mov edi, dword ptr [rsp + 0x68]
.nm_cz:
    cmp edi, dword ptr [rsp + 0x6c]
    jg .nm_cxn
    mov eax, esi
    shl eax, 7
    add eax, edi
    mov rcx, 0x144df1790
    cmp byte ptr [rcx + rax], 0
    je .nm_czn
    inc r14d
.nm_czn:
    inc edi
    jmp .nm_cz
.nm_cxn:
    inc esi
    jmp .nm_cx
.nm_cdone:
    test r14d, r14d
    jz .nm_ret                          // no free cell near the holder
    mov ecx, dword ptr [rip + evil_malice_count]
    call 0x140136660                    // game_rng_draw(count): the stand-in
    cmp eax, dword ptr [rip + evil_malice_count]
    jae .nm_ret
    mov eax, eax
    lea rcx, [rip + evil_malice_tbl]
    mov ebp, dword ptr [rcx + rax*4]    // the character id
    movsx r15d, word ptr [rbx + 0x2dfc] // the holder's level L, at least 1
    mov ecx, 1
    test r15d, r15d
    cmovle r15d, ecx
    mov ecx, 40
    call 0x140136660                    // game_rng_draw(40)
    cmp eax, 40
    jae .nm_ret
    imul eax, r15d                      // rand * L
    xor edx, edx
    mov ecx, 100
    div ecx                             // rand * L / 100
    mov esi, eax
    imul eax, r15d, 60
    cdq
    idiv ecx                            // L * 60 / 100
    add eax, esi
    mov ecx, 1
    test eax, eax
    cmovle eax, ecx
    mov r15d, eax                       // the level
    mov ecx, r14d
    call 0x140136660                    // game_rng_draw(free cells): the cell
    cmp eax, r14d
    jae .nm_ret
    mov r14d, eax                       // cells to skip
    mov esi, dword ptr [rsp + 0x60]
.nm_px:
    cmp esi, dword ptr [rsp + 0x64]
    jg .nm_ret
    mov edi, dword ptr [rsp + 0x68]
.nm_pz:
    cmp edi, dword ptr [rsp + 0x6c]
    jg .nm_pxn
    mov eax, esi
    shl eax, 7
    add eax, edi
    mov rcx, 0x144df1790
    cmp byte ptr [rcx + rax], 0
    je .nm_pzn
    test r14d, r14d
    jz .nm_found
    dec r14d
.nm_pzn:
    inc edi
    jmp .nm_pz
.nm_pxn:
    inc esi
    jmp .nm_px
.nm_found:
    xor eax, eax                        // the request
    mov qword ptr [rsp + 0x20], rax
    mov qword ptr [rsp + 0x28], rax
    mov qword ptr [rsp + 0x30], rax
    mov qword ptr [rsp + 0x38], rax
    mov qword ptr [rsp + 0x40], rax
    mov qword ptr [rsp + 0x48], rax
    mov qword ptr [rsp + 0x50], rax
    mov qword ptr [rsp + 0x58], rax
    lea eax, [rsi + rsi*2]
    lea eax, [rax*4 + 6]
    cvtsi2ss xmm0, eax
    movss dword ptr [rsp + 0x28], xmm0  // world x = cell * 12 + 6
    lea eax, [rdi + rdi*2]
    lea eax, [rax*4 + 6]
    cvtsi2ss xmm1, eax
    movss dword ptr [rsp + 0x30], xmm1  // world z
    call 0x1401cf4d0                    // map_surface_height_at(x, z) -> xmm0 (xmm0 / xmm1 still hold x / z)
    movss dword ptr [rsp + 0x2c], xmm0  // world y
    call 0x1401367f0                    // FUN_1401367f0(): the Guardian block's facing draw
    imul eax, eax, 0x5a
    sub eax, 0x5a
    mov dword ptr [rsp + 0x34], eax     // facing
    mov dword ptr [rsp + 0x38], ebp     // the character
    mov dword ptr [rsp + 0x3c], r15d    // the level
    mov dword ptr [rsp + 0x44], r13d    // the team
    mov dword ptr [rsp + 0x4c], -1      // no variant
    lea rcx, [rsp + 0x20]
    call 0x1401c5ae0                    // unit_spawn_from_request
.nm_ret:
    add rsp, 0x78
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// D4SIG7: wrap_atkcount(rcx = attacker battle record, rdx = target battle record, r8 = action context, r9d = target index, [stack] flags)
// -> damage_apply_damage 0x1401B1FD0, the one call FUN_1401B1BA0 (the per-target apply of an action, called only by
// unit_battle_action_impl) makes at 0x1401B1BE0.  D4 FUN_140123940 (event 0x1E, once per action target) adds 1 to the target's counter
// +0x20D5 (signed char, at most 20) whenever the target's result slot is not negative: a hit, a nullified hit, a MISS (hit code 0, slot 0)
// and a buff (slot 0) all count; a heal (slot = -amount) does not.  D5 stores a heal's amount as a positive slot (battle_damage_compute_target:
// skill category 4 -> damage_heal_compute_heal), so the heal test is the skill row's category byte (+0x3F6) == 4.  The counter the holder
// uses is D5's own Impact Charge (2065) counter, the short at stat record +0x5D8 (stat record = 0x141067DC8 + unit +0x4348 * 0xE98), which
// damage_apply_damage itself counts by D5's rule; the wrapper takes the value from BEFORE the call and stores min(that + D4's 0 or 1, 20),
// so the holder's counter is D4's and D5's own count is discarded.  A unit without an `attack_counter` row (second-word bit 2) is untouched.
wrap_atkcount:
    mov r11d, 0xE70020
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x38
    mov rbp, rcx                        // attacker battle record
    mov rbx, rdx                        // target battle record
    mov r12, r8                         // action context
    mov r13d, r9d                       // target index
    mov rax, qword ptr [rsp + 0xA0]     // the game's fifth argument, passed on
    mov qword ptr [rsp + 0x20], rax
    mov dword ptr [rsp + 0x30], -1      // the target's counter before the call, or -1 when it holds no attack_counter row
    mov dword ptr [rsp + 0x34], -1      // DRPGSIG2: N << 8 | the invincible_hits count before the call, or -1 when it holds no such row
    // DD2EVIL3: kill_counter (second-word bit 8).  r14d = the TARGET's count before the call when the target holds the row (D5 raises +0x5D8 of
    // every target itself: that is taken back below), else -1; r15d bit 0 = the attacker holds the row, bit 1 = the target was alive before the
    // call and is not a Geo Symbol family unit (Disgaea D2's 0x1035B0 tests family 0x1E1 first: chars 4810..4819).
    mov r14d, -1
    xor r15d, r15d
    test rbx, rbx
    jz .kc_att
    mov rsi, qword ptr [rbx + 0x240]
    test rsi, rsi
    jz .kc_att
    cmp dword ptr [rsi + 0x4348], 0x28a
    jae .kc_att
    cmp qword ptr [rsi + 0x2cc8], 0
    jle .kc_tdead
    or r15d, 2
.kc_tdead:
    mov eax, dword ptr [rsi + 0x2e04]
    sub eax, 4810
    cmp eax, 9
    ja .kc_tgeo
    and r15d, 1                         // a Geo Symbol family target is not counted
.kc_tgeo:
    mov rdi, 0x10000000000              // F2_KILL_COUNTER: second-word bit 8
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .kc_att
    mov eax, dword ptr [rsi + 0x4348]
    imul rax, rax, 0xe98
    mov rcx, 0x1410683a0                // the count: stat record + 0x5D8
    movzx r14d, word ptr [rax + rcx]
.kc_att:
    test rbp, rbp
    jz .kc_pre_done
    mov rsi, qword ptr [rbp + 0x240]
    test rsi, rsi
    jz .kc_pre_done
    cmp dword ptr [rsi + 0x4348], 0x28a
    jae .kc_pre_done
    mov rdi, 0x10000000000
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .kc_pre_done
    or r15d, 1
.kc_pre_done:
    test rbx, rbx
    jz .ac_call
    mov rsi, qword ptr [rbx + 0x240]    // the target's unit record
    test rsi, rsi
    jz .ac_call
    cmp dword ptr [rsi + 0x4348], 0x28a
    jae .ac_call                        // no stat record
    mov rdi, 0x400000000                // F2_ATTACK_COUNTER: second-word bit 2
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred
    test eax, eax
    jz .ac_noatk
    mov eax, dword ptr [rsi + 0x4348]
    imul rax, rax, 0xe98
    mov rcx, 0x1410683a0                // the counter: stat record + 0x5D8
    movzx eax, word ptr [rax + rcx]
    mov dword ptr [rsp + 0x30], eax
.ac_noatk:
    mov rdi, 0x800000000                // DRPGSIG2 F2_INVINCIBLE_HITS: second-word bit 3
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                   // eax = N, 0 for a unit without the row
    test eax, eax
    jle .ac_call
    mov ecx, dword ptr [rsi + 0x4348]
    imul rcx, rcx, 0xe98
    mov rdx, 0x141068bc1                // the count: stat record + 0xDF9
    movzx ecx, byte ptr [rcx + rdx]
    shl eax, 8
    or eax, ecx                         // N << 8 | the count before the call
    mov dword ptr [rsp + 0x34], eax
.ac_call:
    mov rcx, rbp
    mov rdx, rbx
    mov r8, r12
    mov r9d, r13d
    call 0x1401b1fd0
    mov qword ptr [rsp + 0x28], rax     // the game's result, handed back unchanged
    // DD2EVIL3: take back D5's own +1 on a kill_counter holder that was the target, then count a defeat made by a holder as the attacker.
    test r14d, r14d
    js .kc_post_att
    mov rsi, qword ptr [rbx + 0x240]
    mov eax, dword ptr [rsi + 0x4348]
    imul rax, rax, 0xe98
    mov rcx, 0x1410683a0
    mov word ptr [rax + rcx], r14w
.kc_post_att:
    cmp r15d, 3
    jne .kc_post_done                   // not (a holder attacking a target that was alive)
    mov rsi, qword ptr [rbx + 0x240]
    cmp qword ptr [rsi + 0x2cc8], 0
    jg .kc_post_done                    // still standing: no defeat
    mov rsi, qword ptr [rbp + 0x240]
    mov eax, dword ptr [rsi + 0x4348]
    imul rax, rax, 0xe98
    mov rcx, 0x1410683a0
    movzx edx, word ptr [rax + rcx]
    cmp edx, 0x270f
    jae .kc_post_done                   // D5's own clamp
    inc edx
    mov word ptr [rax + rcx], dx
.kc_post_done:
    // NECRO2: a target that was alive before the call and may be defeated now: evil_necro_note queues the raise_zombie holder's victim while its record is whole
    test r15d, 2
    jz .nn_skip
    mov rcx, rbp                        // attacker battle record
    mov rdx, rbx                        // target battle record
    mov r8, r12                         // action context
    mov r9d, r13d                       // target index
    call evil_necro_note
.nn_skip:
    mov eax, dword ptr [rsp + 0x30]
    test eax, eax
    js .ac_ret                          // not a holder
    movsxd rcx, r13d
    imul rcx, rcx, 0x260
    xor edx, edx                        // D4's increment: 0 or 1
    cmp qword ptr [r12 + rcx + 0x1328], 0
    jl .ac_store                        // no result for this target
    mov r8, qword ptr [r12 + 0x27678]   // the action's skill row
    test r8, r8
    jz .ac_inc                          // a normal attack
    cmp byte ptr [r8 + 0x3f6], 4
    je .ac_store                        // a heal
.ac_inc:
    mov edx, 1
.ac_store:
    add eax, edx
    cmp eax, 20
    jbe .ac_cap
    mov eax, 20
.ac_cap:
    mov rsi, qword ptr [rbx + 0x240]
    mov ecx, dword ptr [rsi + 0x4348]
    imul rcx, rcx, 0xe98
    mov r8, 0x1410683a0
    mov word ptr [rcx + r8], ax
.ac_ret:
    // DRPGSIG2: the invincible_hits COUNT, only here (the real apply).  D5 itself sets +0xDF9 to 1 on the first connected hit; for a holder the
    // byte is the count: the value from before the call, plus 1 when this hit was nullified by the rule (pending mark set by wrap_nullify, result
    // slot 0, hit connected: +0x1330 != 0, and not a buff: skill category 5 / 6), never above N.
    mov eax, dword ptr [rsp + 0x34]
    test eax, eax
    js .ac_done                         // not a holder
    mov rsi, qword ptr [rbx + 0x240]
    mov ecx, dword ptr [rsi + 0x4348]   // below 0x28a: checked before the call
    lea rdx, [rip + evil_pend]
    movzx r8d, byte ptr [rdx + rcx]     // the pending mark
    mov byte ptr [rdx + rcx], 0
    imul rdi, rcx, 0xe98
    mov rdx, 0x141068bc1
    add rdi, rdx                        // &count
    movzx r9d, al                       // the count before the call
    mov r10d, eax
    shr r10d, 8                         // N
    test r8d, r8d
    jz .ac_keep                         // no pending nullification: the count stays as it was
    cmp r9d, r10d
    jae .ac_keep
    movsxd rcx, r13d
    imul rcx, rcx, 0x260
    cmp qword ptr [r12 + rcx + 0x1328], 0
    jne .ac_keep                        // damage went through
    cmp dword ptr [r12 + rcx + 0x1330], 0
    je .ac_keep                         // a miss
    mov r8, qword ptr [r12 + 0x27678]   // the action's skill row
    test r8, r8
    jz .ac_use                          // a normal attack
    movzx edx, byte ptr [r8 + 0x3f6]
    sub edx, 5
    cmp edx, 1
    jbe .ac_keep                        // a buff / debuff (category 5, 6)
.ac_use:
    inc r9d
.ac_keep:
    mov byte ptr [rdi], r9b
.ac_done:
    mov rax, qword ptr [rsp + 0x28]
    add rsp, 0x38
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// D4SIG8: wrap_endturn(rcx = battle record) -> turn_t3_per_unit_end_turn 0x140159F50, at its three static call sites (exe call scan:
// 0x1405524FF in turn_t1_per_unit_hp_sp, 0x140554F7F in sequencer_ctl_s1_update, 0x1405FB9B1 in FUN_1405FAF90).  D4 FUN_1400F3C20 (the per-unit
// round-edge routine, called by FUN_1402EB670) raises the holder's Stone Statue counter (unit +0x22DE, a byte) by 1 (at most 10) when the unit's
// move cost +0x4E8 is 0 and ZEROES it otherwise; nothing else is tested.  D5's own counter is the byte SR+1 of the stat record
// (SR = 0x141067DC8 + unit +0x4348 * 0xE98) which T3 raises only when the move cost +0x61C is 0 AND the stat-record byte SR+2 (a lift/throw count),
// the battle byte +0x11E1 (hit by a skill that sets it) and, in one mode, +0x11F5 are all 0.  For a unit that has learned evility 27807 (row
// 27000 + 807, read by scale idle_turns) the wrapper takes the counter and the move cost BEFORE the call (T3 clears +0x61C), runs T3, then stores
// D4's value: prev + 1 if prev < 10 else prev when the cost is 0, else 0.  Units without the id are untouched.
wrap_endturn:
    mov r11d, 0xE70021
    push rbx
    push rsi
    push rdi
    push rbp
    sub rsp, 0x28
    mov rbx, rcx                        // battle record
    mov ebp, -1                         // D4's new counter, or -1 when the unit is not a holder
    test rbx, rbx
    jz .et_call
    mov rcx, rbx
    call evil_move_heal                 // DD2EVIL2: Lilliel's heal for the panels moved, before T3 zeroes +0x61C
    mov rsi, qword ptr [rbx + 0x240]    // the unit record
    test rsi, rsi
    jz .et_call
    mov eax, dword ptr [rsi + 0x4348]
    cmp eax, 0x28a
    jae .et_call                        // no stat record
    imul rdi, rax, 0xe98
    mov rax, 0x141067dc9                // SR + 1
    add rdi, rax
    mov rcx, rsi
    mov edx, 27807
    call evil_has_id
    test eax, eax
    jz .et_call
    movzx ebp, byte ptr [rdi]           // the counter before the call
    cmp word ptr [rbx + 0x61c], 0
    jne .et_zero                        // moved this turn: D4 zeroes it
    cmp ebp, 10
    jae .et_call                        // at the cap (D4 leaves it as it is)
    inc ebp
    jmp .et_call
.et_zero:
    xor ebp, ebp
.et_call:
    mov rcx, rbx
    call 0x140159f50
    test ebp, ebp
    js .et_ret                          // not a holder
    mov byte ptr [rdi], bpl
.et_ret:
    add rsp, 0x28
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// DRPGSIG1: wrap_healmod(rcx = &heal amount (s64), rdx = healer battle record, r8 = healed unit's battle record, r9 = skill row) ->
// FUN_1401FFF40, the one call damage_heal_compute_heal (0x1401BF3C0) makes after the heal amount is computed (exe call scan: the single
// caller, 0x1401BF503).  The game's function applies D5's Evil Spirit (141): for each unit hostile to the healed one that holds 141 the
// amount is multiplied by (1 - the vanilla row's +0x38 / 100), and then the healer's own 3305 term.  The wrapper runs it first, with the
// arguments it was entered with, then does the same walk for the second-word family `enemy_heal_percent` (query = bit 33 of rdi): every
// active, uncarried unit of a team hostile to the healed unit's team (the table evil_near uses) whose rows sum to p percent multiplies the
// amount by (100 - min(p, 100)) / 100, signed truncation, one holder at a time (the game's per-holder product).  The walk skips the healed
// unit itself.  Nothing else about the heal is touched.
wrap_healmod:
    mov r11d, 0xE7001F
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x38
    mov rbx, rcx                        // the heal amount
    mov r12, r8                         // the healed unit's battle record
    call 0x1401fff40                    // the game's own pass (rcx, rdx, r8, r9 as received)
    mov qword ptr [rsp + 0x28], rax     // its result, handed back unchanged
    test r12, r12
    jz .hm_ret
    mov rax, qword ptr [r12 + 0x240]
    test rax, rax
    jz .hm_ret
    movzx r13d, byte ptr [rax + 0x2e32] // the healed unit's team
    mov r14, 0x141ba33b0                // scan cursor
    xor r15d, r15d                      // index
.hm_loop:
    cmp r14, r12
    je .hm_next                         // never the healed unit itself
    cmp byte ptr [r14 + 0x2e8], 0
    je .hm_next                         // not on the map
    cmp word ptr [r14 + 0x2ee], 0
    jge .hm_next                        // carried by another unit
    mov rsi, qword ptr [r14 + 0x240]
    test rsi, rsi
    jz .hm_next
    cmp dword ptr [rsi + 0x4348], 0x28a
    jae .hm_next                        // no stat record: not a real unit
    movzx edx, byte ptr [rsi + 0x2e32]  // the candidate's team
    cmp edx, r13d
    je .hm_next
    lea rax, [rip + evil_hostile]
    movzx eax, byte ptr [rax + r13]
    bt eax, edx
    jnc .hm_next                        // not hostile to the healed unit
    mov rdi, 0x200000000                // F2_ENEMY_HEAL_PERCENT: second-word bit 1
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                   // rsi = the holder's unit record
    test eax, eax
    jle .hm_next
    cmp eax, 100
    jle .hm_pct
    mov eax, 100
.hm_pct:
    mov ecx, 100
    sub ecx, eax
    movsxd rcx, ecx                     // 100 - p
    mov rax, qword ptr [rbx]
    imul rax, rcx
    cqo
    mov ecx, 100
    idiv rcx
    mov qword ptr [rbx], rax
.hm_next:
    add r14, 4704
    inc r15d
    cmp r15d, 256
    jl .hm_loop
.hm_ret:
    mov rax, qword ptr [rsp + 0x28]
    add rsp, 0x38
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// D4SIG10: Roc's Miasma of Silence (D4 115, row 27115, second-word family special_seal, bit 4).
// D4 FUN_140105640(unit, 0x73) sums evility 0x73 over every unit that is active, alive (HP > 0), of a team hostile to the asked unit, not an object
// kind (FUN_1400ED900) / class 0x12CA / Geo class (FUN_1401B1280) and within distance 1 by FUN_1400ED660 (footprints); a non-zero sum makes the menu
// builders FUN_14030B440 / FUN_14030D920 withdraw the special-skill flag and the AI sites (FUN_1402F5020, FUN_1402F06B0, FUN_140231370,
// FUN_1402302B0) treat the unit as standing on D4's Silence geo effect (GE.dat row 11, "No Special Skills can be used by characters on").
// evil_roc(rcx = battle unit) -> eax = 1 when such a holder is next to the unit.  D5 counterparts: alive = record HP +0x2CC8 > 0; object / Geo =
// the game's events_env_is_object_rec test (id / 100 in {48, 51, 52} or 5000..5009; D4's class 0x12CA = 4810 is inside it); hostile = the kit's evil_hostile bit table (the
// game's model_team_is_hostile); adjacency = the game's own ai_transition_within_range 0x140153FF0 (other, unit, 1, -1) = D4 FUN_1400ED660's
// footprint test; holder = a learned special_seal row.
evil_roc:
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x28
    xor r15d, r15d
    test rcx, rcx
    jz .rc_ret
    mov r12, rcx                        // the asked unit
    mov r13, qword ptr [r12 + 0x240]
    test r13, r13
    jz .rc_ret
    movzx r14d, byte ptr [r13 + 0x2e32] // its team
    mov rbx, 0x141ba33b0
    xor ebp, ebp
.rc_loop:
    cmp rbx, r12
    je .rc_next
    cmp byte ptr [rbx + 0x2e8], 0
    je .rc_next                         // not on the map
    mov rsi, qword ptr [rbx + 0x240]
    test rsi, rsi
    jz .rc_next
    cmp qword ptr [rsi + 0x2cc8], 0
    jle .rc_next                        // dead
    movzx edx, byte ptr [rsi + 0x2e32]
    cmp edx, r14d
    je .rc_next
    lea rax, [rip + evil_hostile]
    movzx eax, byte ptr [rax + r14]
    bt eax, edx
    jnc .rc_next                        // not hostile
    mov eax, dword ptr [rsi + 0x2e04]
    mov edi, eax
    cdq
    mov ecx, 100
    idiv ecx
    lea edx, [rax - 0x33]
    cmp edx, 2
    jb .rc_next                         // object / Geo class 51, 52
    cmp eax, 0x30
    je .rc_next                         // 48xx
    sub edi, 5000
    cmp edi, 10
    jb .rc_next                         // 5000..5009
    mov rdi, 0x1000000000               // F2_SPECIAL_SEAL: second-word bit 4
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_pred                      // rsi = the candidate's unit record
    test eax, eax
    jz .rc_next
    mov rcx, rbx
    mov rdx, r12
    mov r8d, 1
    mov r9d, -1
    call 0x140153ff0                    // ai_transition_within_range(other, unit, 1, -1)
    test al, al
    jz .rc_next
    mov r15d, 1
    jmp .rc_ret
.rc_next:
    add rbx, 4704
    inc ebp
    cmp ebp, 256
    jl .rc_loop
.rc_ret:
    mov eax, r15d
    add rsp, 0x28
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret

// D4SIG10: wrap_roc_geo(rcx = battle unit, edx = column) -> unit_effect_table_sum 0x14015B890, at its one call in cmdmenu_preds_p_156820 (the base of
// "Skill": column 10 = the Silence geo effect, the game's own gate of the Skill command).  The game's answer is kept; for column 10, when it is 0
// and evil_roc says a Roc holder is adjacent, the answer is 1 (as if the unit stood on a Silence panel).
wrap_roc_geo:
    mov r11d, 0xE70022
    push rbx
    push rsi
    push rdi
    sub rsp, 0x20
    mov rbx, rcx
    mov esi, edx
    call 0x14015b890
    mov edi, eax
    cmp esi, 10
    jne .rcg_done
    test dil, dil
    jnz .rcg_done
    mov rcx, rbx
    call evil_roc
    test eax, eax
    jz .rcg_done
    mov edi, 1
.rcg_done:
    mov eax, edi
    add rsp, 0x20
    pop rdi
    pop rsi
    pop rbx
    ret

// D4SIG10: wrap_roc_skill(rcx = battle unit, rdx = magic.dat row or 0, r8 = cost) -> cmdmenu_env_stat_row_can_use_skill 0x140155280, at its four calls
// (the player menu twice, the AI's list_skills, the executor's FUN_140547750).  When the game allows the skill, the row's class byte +0x3F2 is 0
// (unique), 1 (weapon skill) or 2 (spell) and a Roc holder is adjacent, the answer becomes 0.  Items (3), Overload (4) and the basic actions (5) are
// not specials.
wrap_roc_skill:
    mov r11d, 0xE70023
    push rbx
    push rsi
    push rdi
    sub rsp, 0x20
    mov rbx, rcx
    mov rsi, rdx
    call 0x140155280
    mov edi, eax
    test al, al
    jz .rs_done
    test rsi, rsi
    jz .rs_done
    movzx eax, byte ptr [rsi + 0x3f2]
    cmp eax, 2
    ja .rs_done
    mov rcx, rbx
    call evil_roc
    test eax, eax
    jz .rs_done
    xor edi, edi
.rs_done:
    movzx eax, dil
    add rsp, 0x20
    pop rdi
    pop rsi
    pop rbx
    ret

// DD2EVIL2: Alex's God of Destruction (Disgaea D2 480, row 24480, second-word family random_victims, bit 7, value 5).
// Disgaea D2 0x1A0CCC(n) is (sum of three RNG words) mod n, the same shape as D5's game_rng_draw (0x140136660); the evility-event builder 0xFB984 (code
// 0x36EEC6, evility 480) lists the hostile units, draws the count = 0x1A0CCC(value 5) + 1 (1..5) and picks that many DISTINCT random victims
// (a mark per candidate), each of which is then hit by the evility's own action (magic.dat 10484).  D5's own Punishing Prophecy (6112, event
// 0x36F2A4 in FUN_1401E8750) draws ONE victim (game_rng_draw over the hostile list) and hands it to path_throw_append_target(ctx, 0, slot) at
// 0x1401E8F76.  wrap_victims is that one call: the game's append runs first for its victim; then, when the caster (ctx cast entry 0: the short
// at ctx+0, the count at ctx+0x1310) holds the row, it draws extra = game_rng_draw(value) (0..value-1: total count 1..value, as D2) and appends
// that many MORE distinct victims, each drawn by game_rng_draw over the remaining candidates, with the game's own list rules (active, a stat
// record, events_env_kind_of != 2, not an object class, not carried, model_team_is_hostile(team_of(caster,1), team_of(unit,1))), at most 0x20 targets.
// rcx = ctx, edx = index (0), r8d = the game's victim slot.  Every nonvolatile register is preserved; rax is not used by the caller.
wrap_victims:
    mov r11d, 0xE70024
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    push r13
    push r14
    push r15
    sub rsp, 0x138
    mov rbx, rcx                        // ctx
    call 0x1402bb960                    // the game's own append of its drawn victim (rcx, edx, r8d as received)
    cmp word ptr [rbx + 0x1310], 0
    jle .vi_ret                         // no caster entry
    movsx eax, word ptr [rbx]           // the caster's battle slot
    cmp eax, 255
    ja .vi_ret
    imul rax, rax, 0x1260
    mov r12, 0x141ba33b0
    add r12, rax                        // the caster's battle record
    mov rsi, qword ptr [r12 + 0x240]
    test rsi, rsi
    jz .vi_ret
    mov rdi, 0x8000000000               // F2_RANDOM_VICTIMS: second-word bit 7
    xor edx, edx
    xor r8d, r8d
    xor r9d, r9d
    call evil_dmg_sum                   // the caster's unit record in rsi
    test eax, eax
    jle .vi_ret                         // not a holder
    mov ecx, eax
    call 0x140136660                    // game_rng_draw(value): 0..value-1 extra victims
    mov r13d, eax
    test r13d, r13d
    jz .vi_ret
    // the remaining candidates, in slot order, into [rsp + 0x20 .. + 0x120): one byte (the slot) each
    xor r14d, r14d                      // candidate count
    xor r15d, r15d                      // slot
    mov rbp, 0x141ba33b0                // record cursor
.vi_walk:
    cmp byte ptr [rbp + 0x2e8], 0
    je .vi_next
    mov rdi, qword ptr [rbp + 0x240]
    test rdi, rdi
    jz .vi_next
    cmp dword ptr [rdi + 0x4348], 0x28a
    jae .vi_next
    mov rcx, rdi
    call 0x140137af0                    // events_env_kind_of(unit record): 2 = defeated / empty
    cmp eax, 2
    je .vi_next
    mov eax, dword ptr [rdi + 0x2e04]   // the object-class test of the game's list
    cdq
    mov ecx, 100
    idiv ecx
    lea edx, [rax - 0x33]
    cmp edx, 2
    jb .vi_next
    cmp eax, 0x30
    je .vi_next
    mov eax, dword ptr [rdi + 0x2e04]
    sub eax, 5000
    cmp eax, 10
    jb .vi_next
    cmp word ptr [rbp + 0x2ee], 0
    jge .vi_next                        // carried
    mov rcx, rbp
    mov edx, 1
    call 0x14015b910                    // events_env_team_of(candidate, 1)
    movzx edi, al
    mov rcx, r12
    mov edx, 1
    call 0x14015b910                    // events_env_team_of(caster, 1)
    movzx ecx, al
    mov edx, edi
    call 0x1402d9290                    // model_team_is_hostile(caster's team, candidate's team)
    test al, al
    jz .vi_next
    movsx ecx, word ptr [rbx + 0x27318] // targets already in the context: the game's victim and ours
    xor edx, edx
.vi_dup:
    cmp edx, ecx
    jge .vi_add
    imul eax, edx, 0x260
    movsx eax, word ptr [rbx + rax + 0x1318]
    cmp eax, r15d
    je .vi_next                         // already a target
    inc edx
    jmp .vi_dup
.vi_add:
    lea rax, [rsp + 0x20]
    mov byte ptr [rax + r14], r15b
    inc r14d
.vi_next:
    add rbp, 4704
    inc r15d
    cmp r15d, 256
    jl .vi_walk
.vi_pick:
    test r14d, r14d
    jz .vi_ret                          // nobody left
    movsx eax, word ptr [rbx + 0x27318]
    cmp eax, 0x20
    jge .vi_ret                         // the context's target limit
    mov ecx, r14d
    call 0x140136660                    // game_rng_draw(candidates left)
    mov edi, eax
    movzx r8d, byte ptr [rsp + rdi + 0x20]
    // remove it from the list (keep the slot order)
    lea rax, [rsp + 0x20]
    lea rcx, [rax + rdi]
    lea rdx, [rax + r14 - 1]
.vi_shift:
    cmp rcx, rdx
    jae .vi_shifted
    mov r9b, byte ptr [rcx + 1]
    mov byte ptr [rcx], r9b
    inc rcx
    jmp .vi_shift
.vi_shifted:
    dec r14d
    movsx edx, word ptr [rbx + 0x27318] // the game's own index: the running target count
    mov rcx, rbx
    call 0x1402bb960                    // path_throw_append_target(ctx, count, slot)
    dec r13d
    jnz .vi_pick
.vi_ret:
    add rsp, 0x138
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret
