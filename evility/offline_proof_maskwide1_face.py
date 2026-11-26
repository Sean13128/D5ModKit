"""MASKWIDE1: Death Saber 836 (Vanishing Cat), the second-word family `face_target_away`, through the REAL call site of
post_hit_effects in exec_ctl_s2_update (0x14053FE71) under Unicorn, on the kit build, with the game's OWN ai_transition_within_range,
carry_throw_facing_angle (and the CRT atan2) and unit_set_facing running.  Control: the pinned original exe with the same inputs.
Offline, read-only.

D4 `FUN_1402DD8B0` (evility 0x344): for each target whose killed flag is 0 and that is within footprint distance 1 of the attacker, turn it to
`FUN_14022F350(target, attacker)`: it faces directly away from the attacker.  The wrapper does the same before the game's own post_hit_effects.

Action context fixture (read from the exe's own S2 loop): target count short at +0x27318; target j at +0x1318 + j*0x260 (short battle slot at +0,
KO byte at +0x216).  Battle table 0x141BA33B0 + slot*0x1260: world x f32 +8, z f32 +0x10, active byte +0x2E8, unit record +0x240; footprint list
(count short +0x11A4, int32 pairs from +0x10A4), facing shorts +0x2C0/+0x2C2/+0x2C4.  The row is read verbatim from d4-evility-overlay.json.

  * --abi     : stack alignment at the site, non-volatile registers across the redirected call, aligned calls inside the section.
  * --control killed|dir|adjacent|holder|order : a deliberately broken wrapper / row; the proof must then FAIL (exit 1).

<unicorn python> evility/offline_proof_maskwide1_face.py [--abi] [--control killed|dir|adjacent|holder|order|zero|tie|oldangle]
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'tools'), str(KIT / 'evility')]
from d5lib import evility as ev                          # noqa: E402
import stat_oracle as so                                  # noqa: E402
import offline_proof_ex05e as h                           # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig9')
SITE, POST_HIT, ATAN2 = 0x14053FE71, 0x140542CB0, 0x1408BED58
TABLE, STRIDE = 0x141BA33B0, 0x1260
ROW_ID = 27836
CTL, CTX_SIZE = 0x7000000, 0x28000
HOLDER, OTHER_ROW = (ROW_ID,), (121,)


def death_saber_row():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    row = mods['D4_Class_2200']['behaviors']['evilities'][str(ROW_ID)]
    assert row == {'family': 'face_target_away'}, row
    return row


def cell(n):
    return n * 12.0 + 6.0


class Rig:
    def __init__(self, exe, hook_post=True):
        from unicorn import UC_HOOK_CODE
        self.e = so.Emu(exe_path=exe)
        self.log = []
        e, X = self.e, self.e.X

        def post_hit(_a=None):                                # the game's post_hit_effects is not run: record that it was entered
            mu = e.mu
            self.log.append(('post_hit', mu.reg_read(X.UC_X86_REG_RCX), mu.reg_read(X.UC_X86_REG_RDX), mu.reg_read(X.UC_X86_REG_R8),
                             {s: struct.unpack('<h', e.read(TABLE + s * STRIDE + 0x2C4, 2))[0] for s in range(8)}))
            return 0x5A5A
        e.stubs[POST_HIT] = post_hit
        e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=POST_HIT, end=POST_HIT)

        def atan2(mu, addr, size, _):                          # the CRT's atan2 is Windows library code the rig does not run
            x0 = struct.unpack('<d', bytes(mu.reg_read(X.UC_X86_REG_XMM0).to_bytes(16, 'little')[:8]))[0]
            x1 = struct.unpack('<d', bytes(mu.reg_read(X.UC_X86_REG_XMM1).to_bytes(16, 'little')[:8]))[0]
            mu.reg_write(X.UC_X86_REG_XMM0, int.from_bytes(struct.pack('<d', math.atan2(x0, x1)) + bytes(8), 'little'))
            rsp = mu.reg_read(X.UC_X86_REG_RSP)
            mu.reg_write(X.UC_X86_REG_RIP, struct.unpack('<Q', mu.mem_read(rsp, 8))[0])
            mu.reg_write(X.UC_X86_REG_RSP, rsp + 8)
        e.mu.hook_add(UC_HOOK_CODE, atan2, begin=ATAN2, end=ATAN2)


def make_unit(ids):
    u = bytearray(0x4800)
    ids = sorted(ids)
    struct.pack_into('<i', u, 0x3030, len(ids))
    for i, v in enumerate(ids):
        struct.pack_into('<I', u, 0x2F30 + 4 * i, v)
    struct.pack_into('<q', u, 0x2CC8, 1000)
    struct.pack_into('<q', u, 0x2CD8, 2000)
    return u


def make_rec(unit_ptr, x, z, facing=45, fp=((0, 0),), world=None):
    r = bytearray(STRIDE)
    struct.pack_into('<Q', r, 0x240, unit_ptr)
    wx, wz = world if world else (cell(x), cell(z))
    struct.pack_into('<f', r, 8, wx)
    struct.pack_into('<f', r, 0x10, wz)
    r[0x2E8] = 1
    struct.pack_into('<h', r, 0x11A4, len(fp))                # footprint cells as offsets from the unit's own cell (default: one at (0, 0))
    for i, (ox, oz) in enumerate(fp):
        struct.pack_into('<ii', r, 0x10A4 + 8 * i, ox, oz)
    struct.pack_into('<hhh', r, 0x2C0, facing, facing, facing)
    return r


def run(rig, attacker_ids, targets, count=None, abi=False, section=None):
    """targets = [(slot, cell x, cell z, KO byte)]; the attacker is slot 0 at cell (10, 10).  Returns ({slot: facing}, log)"""
    e = rig.e
    X, mu = e.X, e.mu
    e.brk = e.heap_mark
    rig.log.clear()
    mu.mem_write(TABLE, bytes(256 * STRIDE))
    a_unit = e.alloc(make_unit(attacker_ids))
    mu.mem_write(TABLE, bytes(make_rec(a_unit, 10, 10)))
    ctx = bytearray(CTX_SIZE)
    struct.pack_into('<h', ctx, 0x27318, len(targets) if count is None else count)
    for j, (slot, cx, cz, ko, *extra) in enumerate(targets):
        if 1 <= slot < 256:
            t_unit = e.alloc(make_unit(()))
            mu.mem_write(TABLE + slot * STRIDE, bytes(make_rec(t_unit, cx, cz, 45, *extra)))
        struct.pack_into('<h', ctx, 0x1318 + j * 0x260, slot)
        ctx[0x152E + j * 0x260] = ko
    ctx_ptr = e.alloc(ctx)
    rsp = so.STACK + 0x100000 - 0x400                          # rsp % 16 == 0 at the CALL instruction
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    for r, val in ((X.UC_X86_REG_RCX, CTL), (X.UC_X86_REG_RDX, ctx_ptr), (X.UC_X86_REG_R8, TABLE)):
        mu.reg_write(r, val)
    saved_regs = {X.UC_X86_REG_RBX: 0x1111, X.UC_X86_REG_RBP: 0x2222, X.UC_X86_REG_RSI: 0x3333, X.UC_X86_REG_RDI: 0x4444,
                  X.UC_X86_REG_R12: 0x5555, X.UC_X86_REG_R13: 0x6666, X.UC_X86_REG_R14: 0x7777, X.UC_X86_REG_R15: 0x8888}
    for r, val in saved_regs.items():
        mu.reg_write(r, val)
    bad, hooks = [], []
    if abi and section:
        import capstone
        from unicorn import UC_HOOK_CODE
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        lo, hi = section

        def code(uc, addr, size, _):
            if addr == SITE + 5:
                bad.extend(f'register {r} changed across the redirected call' for r, val in saved_regs.items()
                           if uc.reg_read(r) != val)
            if lo <= addr < hi:
                ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
                if ins.mnemonic == 'call' and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append(f'misaligned call at {addr:#x}')
        hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.mem_write(rsp, struct.pack('<Q', 0))
        mu.reg_write(X.UC_X86_REG_RIP, SITE)
        mu.emu_start(SITE, SITE + 5, count=3_000_000)
    finally:
        for k in hooks:
            mu.hook_del(k)
    assert not bad, bad
    assert mu.reg_read(X.UC_X86_REG_RAX) & 0xFFFF == 0x5A5A, 'the game function result is not returned'
    facing = {s: struct.unpack('<h', e.read(TABLE + s * STRIDE + 0x2C4, 2))[0] for s in range(1, 8)}
    both = {s: struct.unpack('<hh', e.read(TABLE + s * STRIDE + 0x2C0, 4)) for s in range(1, 8)}
    return facing, both, list(rig.log), (ctx_ptr, rsp)


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        'killed': ("    cmp byte ptr [r13 + rbp + 0x152e], 0 // D4 killed flag (S2's own \"KO'd targets are skipped\" byte)\n    jne .fa_next\n", ""),
        'dir': ("    cvttss2si ecx, dword ptr [rsi + 8]  // (int)(float) world x / z, as D4 casts them\n    cvttss2si edx, dword ptr [rsi + 0x10]\n"
                "    cvttss2si r8d, dword ptr [r14 + 8]\n    cvttss2si r9d, dword ptr [r14 + 0x10]\n",
                "    cvttss2si r8d, dword ptr [rsi + 8]\n    cvttss2si r9d, dword ptr [rsi + 0x10]\n"
                "    cvttss2si ecx, dword ptr [r14 + 8]\n    cvttss2si edx, dword ptr [r14 + 0x10]\n"),
        'adjacent': ("    call 0x140153ff0                    // ai_transition_within_range(attacker, target, 1, -1): footprint distance 1 or less\n    test al, al\n    jz .fa_next\n",
                     ""),
        'holder': ("    call evil_pred\n    test eax, eax\n    jz .fa_call\n    movsx r15d", "    movsx r15d"),
        'zero': ("    xor eax, eax\n    test edx, edx\n    jg .fa_turn                         // dz > 0\n",
                 "    xor eax, eax\n    test edx, edx\n    jge .fa_turn\n"),
        'tie': ("    jge .fa_zaxis                       // |dz| >= |dx|\n", "    jg .fa_zaxis\n"),
        'oldangle': (None, None),
        'order': ("    jz .fa_call\n    movsx r15d, word ptr [r13 + 0x27318]", "    jz .fa_call\n    jmp .fa_call_first\n.fa_resume:\n    movsx r15d, word ptr [r13 + 0x27318]"),
    }
    old, new = edits[control]
    if control == 'oldangle':       # D5's own carry_throw_facing_angle instead of D4's integer function
        i, j = text.index('    sub ecx, r8d                        // dx'), text.index('.fa_turn:\n') + len('.fa_turn:\n')
        old, new = text[i:j], '    call 0x1402d8d60\n'
    assert text.count(old) == 1, control
    text = text.replace(old, new)
    if control == 'order':      # the game's call first, the turning afterwards
        text = text.replace(".fa_call:\n    mov rcx, r12\n    mov rdx, r13\n    mov r8, r14\n    call 0x140542cb0\n",
                            ".fa_call_first:\n    mov rcx, r12\n    mov rdx, r13\n    mov r8, r14\n    call 0x140542cb0\n    jmp .fa_resume\n.fa_call:\n    mov eax, 0x5A5A\n")
    out = SCRATCH / f'd5evil-maskwide1-face-{control}.inc.asm'
    out.write_text(text)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('killed', 'dir', 'adjacent', 'holder', 'order', 'zero', 'tie', 'oldangle'))
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    row = dict(death_saber_row())
    patched = ev.build_patch(original, {ROW_ID: row, 121: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 1}]}})
    info = ev.section_info(patched)
    tmp = Path(tempfile.mkdtemp(prefix='maskwide1-', dir=SCRATCH))
    (tmp / 'kit.exe').write_bytes(patched)
    kit, control = Rig(tmp / 'kit.exe'), Rig(h.ORIGINAL)       # the control is the pinned original exe, not the live one
    section = (info['code'], info['base'] + len(info['data']))
    # target slots 1.. keep their start facing 45 unless turned.  Attacker at cell (10, 10); +x east (90), +z south (0 when dz > 0).
    # (name, attacker's learned ids, targets [(slot, cx, cz, KO)], expected facings {slot: deg} for the kit; slots not listed stay 45)
    cases = [
        ('target east of the attacker faces east (away), 90', HOLDER, [(1, 11, 10, 0)], {1: 90}),
        ('target west faces west, -90', HOLDER, [(1, 9, 10, 0)], {1: -90}),
        ('target south (+z) faces south, 0', HOLDER, [(1, 10, 11, 0)], {1: 0}),
        ('target north (-z) faces north, 180 (the game stores it as -180)', HOLDER, [(1, 10, 9, 0)], {1: -180}),
        ('target two panels away is not turned', HOLDER, [(1, 12, 10, 0)], {}),
        ('diagonal neighbour (distance 2) is not turned', HOLDER, [(1, 11, 11, 0)], {}),
        ('adjacent but KO byte set: not turned', HOLDER, [(1, 11, 10, 1)], {}),
        ('two targets: the adjacent one turns, the far one does not', HOLDER, [(1, 11, 10, 0), (2, 14, 10, 0)], {1: 90}),
        ('two adjacent targets both turn away', HOLDER, [(1, 11, 10, 0), (2, 10, 9, 0)], {1: 90, 2: -180}),
        ('a KO target and a live one: only the live one', HOLDER, [(1, 11, 10, 1), (2, 9, 10, 0)], {2: -90}),
        ('the attacker itself as target (D4 does not exclude it): a zero distance gives D4 FUN_14022F350 = 180 (stored -180)', HOLDER, [(0, 10, 10, 0)], 'self'),
        # D4SIG9: exact ties and the truncation asymmetry need a footprint cell next to the attacker while the unit's own position is diagonal
        # (the footprint list is offsets from the unit's cell; the within-range test uses any cell, the angle uses the unit's world position)
        ('exact tie dx = dz > 0 (target at (11,11), footprint cell (10,11)): D4 gives 0 (D5 own function gave 90)', HOLDER, [(1, 11, 11, 0, ((0, 0), (-1, 0)))], {1: 0}),
        ('exact tie dx < 0, dz < 0 (target at (9,9), footprint cell (10,9)): D4 gives 180 (D5 own function gave -90)', HOLDER, [(1, 9, 9, 0, ((0, 0), (1, 0)))], {1: -180}),
        ('exact tie dx < 0, dz > 0 (target at (9,11)): 0 as before', HOLDER, [(1, 9, 11, 0, ((0, 0), (1, 0)))], {1: 0}),
        ('exact tie dx > 0, dz < 0 (target at (11,9)): 180 as before', HOLDER, [(1, 11, 9, 0, ((0, 0), (-1, 0)))], {1: -180}),
        ('|dx| just above |dz| on the negative side (dx -60, dz 59, angle -45.46): -90 (D5 own function truncated it to the 0 bucket)', HOLDER,
         [(1, 5, 15, 0, ((0, 0), (5, -5)), (66.0, 185.0))], {1: -90}),
        ('|dx| just above |dz| on the positive side (dx 60, dz 59): 90', HOLDER, [(1, 15, 15, 0, ((0, 0), (-5, -5)), (186.0, 185.0))], {1: 90}),
        ('|dz| just above |dx| (dx -59, dz 60): 0', HOLDER, [(1, 5, 15, 0, ((0, 0), (5, -5)), (67.0, 186.0))], {1: 0}),
        ('no row on the attacker: nothing turns', (), [(1, 11, 10, 0)], {}),
        ('another family row (regen) on the attacker: nothing turns', OTHER_ROW, [(1, 11, 10, 0)], {}),
        ('target count 0: nothing turns', HOLDER, [(1, 11, 10, 0)], 'zero'),
        ('target count garbage (-5): nothing turns', HOLDER, [(1, 11, 10, 0)], 'neg'),
        ('target slot out of range (-1): skipped', HOLDER, [(-1, 11, 10, 0), (1, 11, 10, 0)], {1: 90}),
    ]
    ok = n = 0
    for name, ids, targets, want in cases:
        count = {'zero': 0, 'neg': -5}.get(want) if isinstance(want, str) else None
        exp = {} if isinstance(want, str) else want
        base, _, _, _ = run(control, ids, targets, count=count)
        got, both, log, (ctx_ptr, _) = run(kit, ids, targets, count=count, abi=args.abi, section=section)
        used = sorted({t[0] for t in targets if 1 <= t[0] < 256})
        want_facing = {s: exp.get(s, 45) for s in used}
        problems = []
        if want == 'self':
            a = struct.unpack('<h', kit.e.read(TABLE + 0x2C4, 2))[0]
            if a != -180:
                problems.append(f'attacker facing {a}, D4 gives 180 (stored -180)')
            want_facing = {}
        got = {s: got[s] for s in used}
        if got != want_facing:
            problems.append(f'kit facings {got} expected {want_facing}')
        if {s: base[s] for s in used} != {s: 45 for s in used}:
            problems.append(f'the original exe changed facings: {base}')
        if any(both[s][0] != both[s][1] for s in used):
            problems.append('facing shorts +0x2C0/+0x2C4 differ')
        if len(log) != 1 or log[0][0] != 'post_hit' or log[0][2] != ctx_ptr or log[0][1] != CTL or log[0][3] != TABLE:
            problems.append(f'post_hit_effects not entered exactly once with the site arguments: {log}')
        elif {s: v for s, v in log[0][4].items() if s in used} != want_facing and want != 'self':
            problems.append(f'the turning did not happen BEFORE the game call: {log[0][4]}')
        good = not problems
        n += 1
        ok += good
        print(f"{'ok  ' if good else 'FAIL'} {name}{'' if good else ': ' + '; '.join(problems)}")
    print(f"{ok}/{n} {'abi' if args.abi else 'behavior'}; kit build sha256 {hashlib.sha256(patched).hexdigest()[:16]}, "
          f"control exe {control.e.exe_sha[:16]}")
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
