"""D4SIG6: Tyrant Guard 667 (Pringer X), the lethal exception, through the REAL damage_nullify_predicate (0x1401FE0D0) under Unicorn,
on the pinned original exe (control) and on the kit build (wrap_firstimp at the call 0x1401FE3B3).  Offline, read-only.

D4 `FUN_1400FF700` (target result, lines 1768-1783) nullifies a hit while the unit's hit counter is below max(1, T) and the result
HP stays above 0 (`if (lVar26 < 1) keep the lethal result`).  D5's own First Impression test inside damage_nullify_predicate (the
call to cmdmenu_preds_p_2068b0 with 6047, then the byte test of stat record +0xDF9) has no damage test, so the alias of 667 onto 6047
nullified a lethal first hit.  The wrapper answers "not carried" for a unit that holds the Tyrant Guard rearm row when the hit's
damage v (the predicate's sixth argument) is at least the unit's current HP.  Every other unit is answered by the game unchanged.

The row is read verbatim from d5lib/importers/d4-evility-overlay.json.  The whole predicate body runs (its other checks included);
the unit has a real learned list (the game's own binary search), a stat record at 0x141067DC8 + index x 0xE98 whose +0xDF9 byte is
set per case, and HP / maximum HP at +0x2CC8 / +0x2CD8.

  * --abi     : stack alignment at the site, non-volatile registers across the redirected call, aligned calls inside the section.
  * --control lethal|holder|row : a deliberately broken wrapper / row; the proof must then FAIL (exit 1).

<unicorn python> evility/offline_proof_d4sig6.py [--abi] [--control lethal|holder|row]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'tools'), str(KIT / 'evility')]
from d5lib import database, evility as ev              # noqa: E402
import stat_oracle as so                                # noqa: E402
import offline_proof_ex05e as h                         # noqa: E402

GAME = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete')
SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig6')
PRED = 0x1401FE0D0
SITE = 0x1401FE3B3
FIRST_IMPRESSION, TYRANT = 6047, 8667
STAT_BASE, STAT_STRIDE, FIRST_HIT = 0x141067DC8, 0xE98, 0xDF9
HP, MAXHP = 1000, 2000


def emu(exe):
    db = database.load_database(str(GAME / 'Data/Database/Database_0.dat'))
    return so.Emu(exe_path=exe, db=db)


def tyrant_row():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    row = mods['D4_Unique_210']['behaviors']['evilities'][str(TYRANT)]
    assert row == {'family': 'rearm_first_damage'}, row
    return row


def make_unit(ids, idx):
    u = bytearray(0x4800)
    ids = sorted(ids)
    struct.pack_into('<i', u, 0x3030, len(ids))
    for i, v in enumerate(ids):
        struct.pack_into('<I', u, 0x2F30 + 4 * i, v)
    struct.pack_into('<I', u, 0x4348, idx)
    struct.pack_into('<q', u, 0x2CC8, HP)
    struct.pack_into('<q', u, 0x2CD8, MAXHP)
    struct.pack_into('<i', u, 0x2E04, 10)
    return u


def run(e, ids, v, first_hit, abi=False, section=None, idx=3):
    """damage_nullify_predicate(attacker actor, defender actor, 0, ctx, tgt_i, v) -> al, run from its first instruction"""
    X, mu = e.X, e.mu
    e.brk = e.heap_mark
    unit = e.alloc(make_unit(ids, idx))
    actor = bytearray(0x1260)
    struct.pack_into('<Q', actor, 0x240, unit)
    defender = e.alloc(actor)
    attacker = e.alloc(bytes(0x1260))
    ctx = e.alloc(bytes(0x28000))
    rec = STAT_BASE + idx * STAT_STRIDE
    mu.mem_write(rec, bytes(0xE98))
    mu.mem_write(rec + FIRST_HIT, bytes([first_hit]))
    rsp = so.STACK + 0x100000 - 0x408                          # entry rsp = 8 mod 16, as right after a call
    mu.mem_write(rsp, struct.pack('<Q', so.RET))
    mu.mem_write(rsp + 0x28, struct.pack('<q', 0))             # tgt_i
    mu.mem_write(rsp + 0x30, struct.pack('<q', v))             # v, the damage
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    for r, val in ((X.UC_X86_REG_RCX, attacker), (X.UC_X86_REG_RDX, defender), (X.UC_X86_REG_R8, 0),
                   (X.UC_X86_REG_R9, ctx)):
        mu.reg_write(r, val)
    for r, val in {X.UC_X86_REG_RBX: 0x1111, X.UC_X86_REG_RBP: 0x2222, X.UC_X86_REG_RSI: 0x3333, X.UC_X86_REG_RDI: 0x4444,
                   X.UC_X86_REG_R12: 0x5555, X.UC_X86_REG_R13: 0x6666, X.UC_X86_REG_R14: 0x7777,
                   X.UC_X86_REG_R15: 0x8888}.items():
        mu.reg_write(r, val)
    bad, hooks, seen = [], [], []
    if abi and section:
        import capstone
        from unicorn import UC_HOOK_CODE
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        lo, hi = section
        nonvol = (X.UC_X86_REG_RBX, X.UC_X86_REG_RBP, X.UC_X86_REG_RSI, X.UC_X86_REG_RDI, X.UC_X86_REG_R12,
                  X.UC_X86_REG_R13, X.UC_X86_REG_R14, X.UC_X86_REG_R15, X.UC_X86_REG_RSP)
        saved = {}

        def code(uc, addr, size, _):
            if addr == SITE:
                seen.append(1)
                if uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append('site entered with a misaligned stack')
                saved.update({r: uc.reg_read(r) for r in nonvol})
            elif addr == SITE + 5 and saved:
                bad.extend(f'register {r} changed across the redirected call' for r, val in saved.items()
                           if uc.reg_read(r) != val)
            if lo <= addr < hi:
                ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
                if ins.mnemonic == 'call' and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append(f'misaligned call at {addr:#x}')
        hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.emu_start(PRED, so.RET, count=3_000_000)
    finally:
        for k in hooks:
            mu.hook_del(k)
    assert not bad, bad
    if abi and section and 6047 in ids:
        assert seen, 'the redirected call site was never reached'
    return mu.reg_read(X.UC_X86_REG_RAX) & 0xFF


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    old, new = {
        'lethal': ("    cmp rax, qword ptr [rbx + 0x2CC8]   // current HP\n    jl .fi_yes", "    cmp rax, qword ptr [rbx + 0x2CC8]   // current HP\n    jl .fi_yes\n    cmp rax, 99999999\n    jl .fi_yes"),
        'holder': ("    test eax, eax\n    jz .fi_yes                          // First Impression as the game has it",
                   "    test eax, eax\n    jmp .fi_lethal                      // control"),
    }[control]
    assert text.count(old) == 1, control
    if control == 'holder':
        text = text.replace(old, new).replace("    mov rax, qword ptr [rsp + 0x508]    // v, the damage of this hit",
                                              ".fi_lethal:\n    mov rax, qword ptr [rsp + 0x508]    // v, the damage of this hit")
    else:
        text = text.replace(old, new)
    out = SCRATCH / f'd5evil-d4sig6-{control}.inc.asm'
    out.write_text(text)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('lethal', 'holder', 'row'))
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if args.control in ('lethal', 'holder'):
        ev.ASM_FILE = str(mutated_asm(args.control))
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    row = dict(tyrant_row())
    if args.control == 'row':
        row = {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 1}]}   # not a rearm row: the holder test must fail
    patched = ev.build_patch(original, {TYRANT: row})
    info = ev.section_info(patched)
    tmp = Path(tempfile.mkdtemp(prefix='d4sig6-', dir=SCRATCH))
    (tmp / 'kit.exe').write_bytes(patched)
    kit, control = emu(tmp / 'kit.exe'), emu(h.ORIGINAL)         # the control is the pinned original exe, not the live one
    section = (info['code'], info['base'] + len(info['data']))
    FI, TG = (FIRST_IMPRESSION,), (FIRST_IMPRESSION, TYRANT)
    # (name, learned ids, damage v, stat byte +0xDF9, answer of the ORIGINAL game, answer the kit must give)
    cases = [
        ('no evility, first hit', (), 100, 0, 0, 0),
        ('no evility, lethal first hit', (), HP + 5, 0, 0, 0),
        ('First Impression only, first hit', FI, 100, 0, 1, 1),
        ('First Impression only, LETHAL first hit stays nullified (not a Tyrant Guard holder)', FI, HP, 0, 1, 1),
        ('First Impression only, lethal, damage 10x HP', FI, HP * 10, 0, 1, 1),
        ('First Impression only, hit already taken', FI, 100, 1, 0, 0),
        ('Tyrant Guard holder, non-lethal first hit nullified', TG, 100, 0, 1, 1),
        ('Tyrant Guard holder, damage HP-1 nullified', TG, HP - 1, 0, 1, 1),
        ('Tyrant Guard holder, damage exactly HP goes through', TG, HP, 0, 1, 0),
        ('Tyrant Guard holder, damage HP+1 goes through', TG, HP + 1, 0, 1, 0),
        ('Tyrant Guard holder, huge damage goes through', TG, 5_000_000, 0, 1, 0),
        ('Tyrant Guard holder, damage 0 nullified', TG, 0, 0, 1, 1),
        ('Tyrant Guard holder, v = -1 (a caller with no damage) nullified', TG, -1, 0, 1, 1),
        ('Tyrant Guard holder, hit already taken, non-lethal: not nullified', TG, 100, 1, 0, 0),
        ('Tyrant Guard holder, hit already taken, lethal: not nullified', TG, HP + 1, 1, 0, 0),
        ('rearm row without the 6047 alias: the game says no, so no', (TYRANT,), 100, 0, 0, 0),
        ('rearm row without the alias, lethal', (TYRANT,), HP + 1, 0, 0, 0),
        ('another stat record index (0), First Impression only', FI, HP, 0, 1, 1),
    ]
    ok = n = 0
    for name, ids, v, hit, want_orig, want_kit in cases:
        idx = 0 if name.startswith('another') else 3
        base = run(control, ids, v, hit, idx=idx)
        got = run(kit, ids, v, hit, abi=args.abi, section=section, idx=idx)
        good = base == want_orig and got == want_kit
        n += 1
        ok += good
        print(f"{'ok  ' if good else 'FAIL'} {name}: original {base} (expected {want_orig}), kit {got} (expected {want_kit})")
    print(f"{ok}/{n} {'abi' if args.abi else 'behavior'}; kit build sha256 {hashlib.sha256(patched).hexdigest()[:16]}, "
          f"control exe {control.exe_sha[:16]}")
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
