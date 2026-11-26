// d5learn.inc.asm -- the learned-evility capacity extension (assembled by d5lib/learned.py into .d5lc)
//
// WHY
//   A unit's learned evilities are one bit each in 125 bytes at unit record +0x2E70 (1,000 positions).
//   The bit number is NOT the evility id: it is the row's position in Skill.dat's id-sorted table, which
//   the game binary-searches at 0x140A04E48 (key array) / 0x140A04E38 (u16 max index) and then tests with
//   `bit = 1 << (index & 7)` at `record + 0x2E70 + (index >> 3)`.  Both ends of that mapping refuse an
//   index >= 1000 (0x14015E630 returns "not learned", 0x14015E6D0 returns -1).
//
//   So a new evility row that sorts at position 1000 or later can be added to Skill.dat without touching
//   any existing bit's meaning, but the game cannot record it in the bitmap.  This code keeps that extra
//   learning in a per-unit set outside the bitmap, for exactly those ids, and leaves every position
//   0..999 to the game itself.  The bitmap is never written by this extension and its 125 bytes keep their
//   meaning, so an old save loads with every learned evility it had.
//
// GUARD (why a shifted table cannot silently reinterpret old learning)
//   The section carries the ordered ids the extension was built against (`lc_prefix`, up to 1,000 of them:
//   the ids that own the bitmap's bits) plus `lc_base_count`.  Before the first answer the wrapper compares
//   the *live* key array's first `lc_base_count` ids with that list.  Any difference -- a row inserted below
//   an existing one, a removed row, a shorter table, no table -- sets lc_state = 2 and the extension answers
//   nothing at all: the game keeps working with the bitmap exactly as it is.  lc_state stays 0 until then.
//
// PERSISTENCE (EVCAP3, re-sited by EVCAP4)
//   The store is memory only on its own.  Two more relays report the game's own save and load to the
//   runtime (d5lib/native/d5learn.inc.c), which owns all file work on the main thread:
//     lc_save_relay  at 0x140754C5C and 0x140744FE2 -- the two `call`s of data_save_io_make_header
//                    0x1407436D0, the function that actually writes a slot file (formats
//                    "%s/Save_%03d.sav" / "%s/AutoSave.sav", fopen, fwrite the 0x1C0 header, fwrite the
//                    encoded block, fclose; answers 0 only when both writes succeeded, and deletes the
//                    partial file and answers 1 on any failure).  r8d carries the slot, which is the same
//                    number the game puts in the file name.  The relay calls it first, unaltered, and
//                    publishes the slot only on its 0 -- so what the companion gets bound to is the file the
//                    game says it wrote.
//                    *** The site EVCAP3 used (0x14074749E) is NOT a writer: its callee 0x1401194EC is
//                    DeleteFileW (the same routine data_save_io_delete_slot 0x140743090 uses to delete a
//                    slot) and it answers 0 on a *successful delete*, so that relay published on delete
//                    failure -- exactly what [debug] remote=1 produces.  INTEG12-REPORT.md finding 1;
//                    corrected here, EVCAP4-REPORT.md has the trace. ***
//     lc_load_relay  at 0x14074D846 -- the only `call` of savefile_decode_slot 0x140743130 (edx = slot,
//                    0 = AutoSave.sav).  The game's decode runs first; its 0/-1 result and the slot are
//                    published.  The runtime then replaces the store from the companion in d5_frame, i.e.
//                    on the main thread -- never on the loader thread that is running this relay.
//   lc_put / lc_clear are the runtime's entry points into this store; their addresses are published in the
//   section data (`lc_fn_put` / `lc_fn_clear`) so the store's hash, probe and capacity live in exactly one
//   place (here) and the C side cannot drift from it.
//
// ENDPOINTS
//   lc_get (rcx = unit record, edx = evility id)          -> rax low byte 1/0, the native answer's shape
//      entered by `call` at every static call site of FUN_14015e630 (20 sites).  It calls the original first:
//      when the game already answers "learned" the extension is not consulted at all.
//   lc_set (rcx = unit record, edx = evility id, r8b = on) -> eax 0 (done) / -1 (refused)
//      entered by `call` at every static call site of unitstats_set_clear_bit_idx_skill 0x14015E6D0 (123).
//      The original runs first and is left to own every id whose position is below 1,000; only its -1 (id
//      not in the table, or position >= 1,000) is considered by the store.
//
// STORE
//   Fixed-capacity open-addressing table in this section (writeable): %CAP% slots of 16 bytes
//   {u64 serial, u32 evility id, u32 state} with state 0 empty, 1 present, 2 tombstone; a probe walks at
//   most %PROBE% slots, and an insert is refused once %MAXUSED% slots are live.  A refusal is how a full
//   table stays visible: a learning that cannot be stored answers -1 (the native refusal) instead of
//   silently disappearing.  Identity is the unit's serial at record +0x3060; a record with serial 0 is
//   refused (fail closed), because nothing proves which unit it is.
//   %CAP% slots are sized for the whole content plan (every D4/D1C/DD2/D2/D3/DRPG class and unique plus
//   Overlord's), not for today's table: see EVCAP3-REPORT.md for the arithmetic.
//
// PRIVATE CONVENTIONS of the helpers below (they are ours, not the game's):
//   lc_position (edx = id)                -> eax = live position, or -1; keeps rcx, rdx
//   lc_verify   ()                        -> eax = 1 verified / 2 refused, writes lc_state; keeps rcx, rdx
//   lc_lookup   (rcx = unit, edx = id)    -> eax = 1 present / 0 absent
//   lc_store_set(rcx = unit, edx = id, r8d = on) -> eax = 0 / -1
//   lc_put      (rcx = serial, edx = id)  -> eax = 0 done / -1 refused (capacity or probe budget)
//   lc_clear    ()                        -> zeroes the table and the live count
//   Every wrapper keeps its caller's registers; nothing here writes a nonvolatile it did not save.

// --------------------------------------------------------------------------------------------- getter
lc_get:
    mov r11d, 0xE80001
    push rbx
    push rsi
    push rdi
    sub rsp, 0x20
    mov rbx, rcx
    mov esi, edx
    call 0x14015E630
    test al, al
    jne lc_get_done                     // the game's own answer comes back untouched
    mov rcx, rbx
    mov edx, esi
    call lc_lookup
lc_get_done:
    add rsp, 0x20
    pop rdi
    pop rsi
    pop rbx
    ret

// --------------------------------------------------------------------------------------------- setter
lc_set:
    mov r11d, 0xE80002
    push rbx
    push rsi
    push rdi
    sub rsp, 0x20
    mov rbx, rcx
    mov esi, edx
    movzx edi, r8b
    call 0x14015E6D0
    cmp eax, -1
    jne lc_set_done
    mov rcx, rbx
    mov edx, esi
    mov r8d, edi
    call lc_store_set
lc_set_done:
    add rsp, 0x20
    pop rdi
    pop rsi
    pop rbx
    ret

// ------------------------------------------------------------------------------------------ save relay
// entered by `call` at 0x140754C5C (FUN_140754C30: the manual save of slot [ctx+0x8a7618]) and at
// 0x140744FE2 (FUN_140744F20: the autosave, slot 0).  Both call the game's own slot writer; see the header.
// Publishes the slot the game wrote (r8d, the value it put in the file name) and a sequence number, and
// nothing else: the runtime builds the path from the game's save folder and verifies the file itself.
lc_save_relay:
    mov r11d, 0xE80007
    push rbx
    push rsi
    push rdi
    sub rsp, 0x20
    mov ebx, r8d                        // the slot (0 = AutoSave.sav), read before the call clobbers r8
    call 0x1407436D0                    // the game's own write of the slot file, unaltered
    mov esi, eax
    test eax, eax
    jnz lc_sr_out                       // not 0: the write failed, the game deleted the partial file
    cmp ebx, 999
    jbe lc_sr_slot
    mov ebx, 0xFFFFFFFF                 // cannot be a slot file name: reported, never bound to a file
lc_sr_slot:
    mov dword ptr [rip + lc_sv_slot], ebx
    lock inc dword ptr [rip + lc_sv_seq]   // published after the slot; learn_tick() acts on the change
lc_sr_out:
    mov eax, esi                        // the game's own return value, untouched
    add rsp, 0x20
    pop rdi
    pop rsi
    pop rbx
    ret

// ------------------------------------------------------------------------------------------ load relay
lc_load_relay:
    mov r11d, 0xE80008
    push rbx
    push rsi
    push rdi
    sub rsp, 0x20
    mov ebx, edx                        // slot (0 = AutoSave.sav)
    call 0x140743130                    // the game's own decode, unaltered
    mov esi, eax
    mov dword ptr [rip + lc_ev_slot], ebx
    xor ecx, ecx
    test esi, esi
    setz cl                             // 1 = the slot decoded and is about to be applied
    mov dword ptr [rip + lc_ev_ok], ecx
    mov dword ptr [rip + lc_ev_load], 1
    mov eax, esi
    add rsp, 0x20
    pop rdi
    pop rsi
    pop rbx
    ret

// --------------------------------------------------------------------------------------------- guard
// lc_verify: the live Skill table still starts with the ids this build was made against.
lc_verify:
    mov r11d, 0xE80003
    push rcx
    push rdx
    mov eax, 2
    mov r8, qword ptr [rip + lc_pmax]
    test r8, r8
    jz lc_vf_bad
    movzx r9d, word ptr [r8]
    inc r9d                             // live row count
    mov r10d, dword ptr [rip + lc_base_count]
    cmp r9d, r10d
    jb lc_vf_bad                        // fewer rows than the guard was built from
    mov r8, qword ptr [rip + lc_pkey]
    test r8, r8
    jz lc_vf_bad
    mov r8, qword ptr [r8]              // the live key array itself
    test r8, r8
    jz lc_vf_bad
    lea r11, [rip + lc_prefix]
    xor ecx, ecx
lc_vf_loop:
    cmp ecx, r10d
    jae lc_vf_ok
    mov eax, dword ptr [r8 + rcx*4]
    cmp eax, dword ptr [r11 + rcx*4]
    jne lc_vf_bad
    inc ecx
    jmp lc_vf_loop
lc_vf_ok:
    mov dword ptr [rip + lc_state], 1
    mov eax, 1
    jmp lc_vf_exit
lc_vf_bad:
    mov dword ptr [rip + lc_state], 2
    mov eax, 2
lc_vf_exit:
    pop rdx
    pop rcx
    ret

// lc_position: the game's own lower-bound search over the live key array (edx = id -> eax = position/-1)
lc_position:
    mov r11d, 0xE80004
    mov r8, qword ptr [rip + lc_pkey]
    test r8, r8
    jz lc_ps_none
    mov r8, qword ptr [r8]
    test r8, r8
    jz lc_ps_none
    mov r9, qword ptr [rip + lc_pmax]
    test r9, r9
    jz lc_ps_none
    movzx r9d, word ptr [r9]            // max index (signed search over 0..max)
    xor r10d, r10d                      // lo
    mov r11d, r9d                       // hi
lc_ps_loop:
    cmp r10d, r11d
    jg lc_ps_none
    mov eax, r10d
    add eax, r11d
    sar eax, 1                          // mid
    cmp dword ptr [r8 + rax*4], edx      // the key at mid against the wanted id
    je lc_ps_hit
    jb lc_ps_right
    lea r11d, [rax - 1]
    jmp lc_ps_loop
lc_ps_right:
    lea r10d, [rax + 1]
    jmp lc_ps_loop
lc_ps_hit:
    ret
lc_ps_none:
    mov eax, -1
    ret

// --------------------------------------------------------------------------------------------- store
// lc_lookup: is (serial, id) in the store?  Only positions >= 1,000 are ours; the guard must have passed.
lc_lookup:
    mov r11d, 0xE80005
    // entry rsp%16 = 8: 0x28 both aligns to 0 for the calls below and keeps their 32-byte home space
    // clear of this routine's own return address (a bare `sub rsp, 8` would put home space on top of it)
    sub rsp, 0x28
    cmp dword ptr [rip + lc_state], 1
    je lc_lk_go
    call lc_verify
    cmp eax, 1
    jne lc_lk_no
lc_lk_go:
    call lc_position
    cmp eax, 1000
    jl lc_lk_no                         // the game owns this position and already said no
    mov rax, qword ptr [rcx + 0x3060]
    test rax, rax
    jz lc_lk_no
    mov r8, rax                         // serial
    // slot = (high bits of serial*K1 ^ id*K2), the store's one hash (see the note at the top)
    mov r10, r8
    mov rax, 0x9E3779B97F4A7C15
    imul r10, rax
    mov eax, edx
    mov r11, 0xC2B2AE3D27D4EB4F
    imul rax, r11
    xor r10, rax
    shr r10, %SHIFT%
    and r10d, %MASK%
    mov rax, r10
    shl rax, 4
    lea r9, [rip + lc_store]
    add r9, rax
    mov r11d, %PROBE%
lc_lk_probe:
    mov eax, dword ptr [r9 + 12]
    test eax, eax
    jz lc_lk_no                         // empty slot: the probe chain ends here
    cmp eax, 1
    jne lc_lk_next
    cmp qword ptr [r9], r8
    jne lc_lk_next
    cmp dword ptr [r9 + 8], edx
    jne lc_lk_next
    mov eax, 1
    jmp lc_lk_exit
lc_lk_next:
    add r9, 16
    dec r11d
    jnz lc_lk_probe
lc_lk_no:
    xor eax, eax
lc_lk_exit:
    add rsp, 0x28
    ret

// lc_store_set: record or drop (serial, id); only reached when the game refused this id.
lc_store_set:
    mov r11d, 0xE80006
    push rbx
    push rsi
    sub rsp, 0x28
    mov esi, r8d                        // keep `on` before the guard, which clobbers r8
    // the same guard as the getter: a table this build was not made against records nothing
    cmp dword ptr [rip + lc_state], 1
    je lc_ss_guard_ok
    call lc_verify
    cmp eax, 1
    jne lc_ss_refuse
lc_ss_guard_ok:
    call lc_position
    cmp eax, 1000
    jl lc_ss_refuse
    mov rbx, qword ptr [rcx + 0x3060]
    test rbx, rbx
    jz lc_ss_refuse
    // slot = (high bits of serial*K1 ^ id*K2), the same hash lc_lookup and lc_put use
    mov r10, rbx
    mov rax, 0x9E3779B97F4A7C15
    imul r10, rax
    mov eax, edx
    mov r11, 0xC2B2AE3D27D4EB4F
    imul rax, r11
    xor r10, rax
    shr r10, %SHIFT%
    and r10d, %MASK%
    mov rax, r10
    shl rax, 4
    lea r9, [rip + lc_store]
    add r9, rax
    mov r10d, %PROBE%
lc_ss_probe:
    mov eax, dword ptr [r9 + 12]
    test eax, eax
    jz lc_ss_absent
    cmp eax, 1
    jne lc_ss_next
    cmp qword ptr [r9], rbx
    jne lc_ss_next
    cmp dword ptr [r9 + 8], edx
    je lc_ss_found
lc_ss_next:
    add r9, 16
    dec r10d
    jnz lc_ss_probe
    jmp lc_ss_absent
lc_ss_found:
    test esi, esi
    jnz lc_ss_ok                        // already learned: setting again changes nothing
    mov dword ptr [r9 + 12], 2
    sub dword ptr [rip + lc_used], 1
    jmp lc_ss_ok
lc_ss_absent:
    test esi, esi
    jz lc_ss_ok                         // clearing something not present is the native "done"
    mov eax, dword ptr [r9 + 12]
    test eax, eax
    jnz lc_ss_refuse                    // probe budget spent on a live chain
    cmp dword ptr [rip + lc_used], %MAXUSED%
    jae lc_ss_refuse                    // refuse to overfill: a refused learning stays visible
    mov qword ptr [r9], rbx
    mov dword ptr [r9 + 8], edx
    mov dword ptr [r9 + 12], 1
    add dword ptr [rip + lc_used], 1
lc_ss_ok:
    xor eax, eax
    jmp lc_ss_done
lc_ss_refuse:
    mov eax, -1
lc_ss_done:
    add rsp, 0x28
    pop rsi
    pop rbx
    ret

// --------------------------------------------------------------------------- the runtime's entry points
// lc_put: insert (serial, id) as learned -- the same slot, hash and probe budget as lc_store_set, so the
// companion loader cannot place an entry where a lookup would not find it.  No table or bitmap logic:
// the caller has already resolved the id against the live table.
lc_put:
    mov r11d, 0xE8000A
    push rbx
    mov rbx, rcx                        // serial
    mov r8d, edx                        // id
    // slot = (high bits of serial*K1 ^ id*K2), the same hash lc_lookup and lc_put use
    mov r10, rbx
    mov rax, 0x9E3779B97F4A7C15
    imul r10, rax
    mov eax, edx
    mov r11, 0xC2B2AE3D27D4EB4F
    imul rax, r11
    xor r10, rax
    shr r10, %SHIFT%
    and r10d, %MASK%
    mov rax, r10
    shl rax, 4
    lea r9, [rip + lc_store]
    add r9, rax
    mov r10d, %PROBE%
lc_put_probe:
    mov eax, dword ptr [r9 + 12]
    test eax, eax
    jz lc_put_absent
    cmp eax, 1
    jne lc_put_next
    cmp qword ptr [r9], rbx
    jne lc_put_next
    cmp dword ptr [r9 + 8], r8d
    je lc_put_ok
lc_put_next:
    add r9, 16
    dec r10d
    jnz lc_put_probe
    jmp lc_put_refuse
lc_put_absent:
    cmp dword ptr [rip + lc_used], %MAXUSED%
    jae lc_put_refuse
    mov qword ptr [r9], rbx
    mov dword ptr [r9 + 8], r8d
    mov dword ptr [r9 + 12], 1
    add dword ptr [rip + lc_used], 1
lc_put_ok:
    xor eax, eax
    jmp lc_put_done
lc_put_refuse:
    mov eax, -1
lc_put_done:
    pop rbx
    ret

// lc_clear: empty the store (a load replaces the previous save's extension-only learning wholesale)
lc_clear:
    mov r11d, 0xE80009
    push rdi
    push rcx
    lea rdi, [rip + lc_store]
    xor eax, eax
    mov ecx, %CLEARQ%
    rep stosq
    mov dword ptr [rip + lc_used], 0
    pop rcx
    pop rdi
    ret
