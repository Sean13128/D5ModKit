"""DRPGSIG1 offline proofs, one section per row, through the REAL call sites under Unicorn on the kit build, control = the pinned original exe.

  heal     Seraphina XENO (DRPG leaderskill 1641, "all enemies' healing amount -35%"): the second-word family `enemy_heal_percent`,
           wrap_healmod at the one call of FUN_1401FFF40 inside damage_heal_compute_heal (0x1401BF503).  The game's own pass is stubbed
           (it multiplies the amount by 3/4 here, so the order game-pass-then-ours shows in the truncation); the walk over the battle
           table, the hostile-team table and evil_dmg_sum are the kit's real code.

  satina   Breezy Satina (DRPG leaderskill 2731, "at turn start, if an enemy has HP at or below 50%, party damage +30%"): the condition
           `map_hp_at_or_below` (evil_near filter 13) behind the dealt wrapper's real call site 0x1401C169D, on the holder's own row and on
           the party aura row, with the EX-05e battle-table fixture.

<unicorn python> evility/offline_proof_drpgsig1.py [--abi] [--control NAME]      (every section runs; a failing check exits 1)
Controls (a deliberately broken wrapper, the proof must then FAIL): heal-formula, heal-hostile, heal-row, heal-active, heal-carried,
satina-hp, satina-dead, satina-relation
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
from d5lib import evility as ev                          # noqa: E402
from d5lib.importers import _drpg_text   # noqa: E402  (TEXTHASH-DRPG: JP names are hashes; these proofs read ids, rows and our own wording)
import stat_oracle as so                                  # noqa: E402
import offline_proof_ex05e as h                           # noqa: E402
from abi_engine_ex05c import ACTION                       # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/drpgsig1')
TABLE, STRIDE = 0x141BA33B0, 0x1260
OVERLAY = KIT / 'd5lib/importers/drpg-evility-overlay.json'
SERAPHINA = 28176                       # id of the main evility of base 164 (28000 + 4 * lease position)
OTHER_FAMILY_ID, REGEN_ID = 27836, 121  # the face_target_away row (D4 Death Saber) and an ordinary regen row


def overlay_rows(base, evid):
    d = _drpg_text.load_authored(OVERLAY)
    for e in d['bases'][str(base)]['evilities']:
        if e['id'] == evid:
            return e['rows']
    raise KeyError(evid)


def make_unit(ids, team=0, hp=1000, maxhp=2000):
    u = bytearray(0x4800)
    ids = sorted(ids)
    struct.pack_into('<i', u, 0x3030, len(ids))
    for i, v in enumerate(ids):
        struct.pack_into('<I', u, 0x2F30 + 4 * i, v)
    struct.pack_into('<q', u, 0x2CC8, hp)
    struct.pack_into('<q', u, 0x2CD8, maxhp)
    u[0x2E32] = team
    return u


def make_rec(unit_ptr, active=1, carried=-1):
    r = bytearray(STRIDE)
    struct.pack_into('<Q', r, 0x240, unit_ptr)
    r[0x2E8] = active
    struct.pack_into('<h', r, 0x2EE, carried)
    return r


class Rig:
    SITE, GAME_PASS = 0x1401BF503, 0x1401FFF40

    def __init__(self, exe):
        from unicorn import UC_HOOK_CODE
        self.e = so.Emu(exe_path=exe)
        self.log = []
        e, X = self.e, self.e.X

        def game_pass(_a=None):                              # the game's own heal modifier pass: x 3/4 here
            mu = e.mu
            rcx = mu.reg_read(X.UC_X86_REG_RCX)
            amount = struct.unpack('<q', e.read(rcx, 8))[0]
            self.log.append((amount, mu.reg_read(X.UC_X86_REG_RDX), mu.reg_read(X.UC_X86_REG_R8), mu.reg_read(X.UC_X86_REG_R9)))
            mu.mem_write(rcx, struct.pack('<q', int(amount * 3 / 4)))
            return 0x5A5A
        e.stubs[self.GAME_PASS] = game_pass
        e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=self.GAME_PASS, end=self.GAME_PASS)


def run_heal(rig, healed_team, holders, amount=1000, abi=False, section=None, no_target=False):
    """holders = [(slot, ids, team, active, carried)]; the healed unit is slot 1.  Returns (final amount, log)"""
    e = rig.e
    X, mu = e.X, e.mu
    e.brk = e.heap_mark
    rig.log.clear()
    mu.mem_write(TABLE, bytes(256 * STRIDE))
    healer = e.alloc(make_unit(()))
    mu.mem_write(TABLE + 2 * STRIDE, bytes(make_rec(healer)))          # slot 2: the healer
    healed = e.alloc(make_unit((), team=healed_team))
    mu.mem_write(TABLE + 1 * STRIDE, bytes(make_rec(healed)))
    for slot, ids, team, active, carried in holders:
        u = e.alloc(make_unit(ids, team=team)) if ids is not None else 0
        mu.mem_write(TABLE + slot * STRIDE, bytes(make_rec(u, active, carried)))
    amt = e.alloc(struct.pack('<q', amount))
    rsp = so.STACK + 0x100000 - 0x400
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    target = 0 if no_target else TABLE + 1 * STRIDE
    for r, val in ((X.UC_X86_REG_RCX, amt), (X.UC_X86_REG_RDX, TABLE + 2 * STRIDE), (X.UC_X86_REG_R8, target), (X.UC_X86_REG_R9, 0x1234)):
        mu.reg_write(r, val)
    saved = {X.UC_X86_REG_RBX: 0x1111, X.UC_X86_REG_RBP: 0x2222, X.UC_X86_REG_RSI: 0x3333, X.UC_X86_REG_RDI: 0x4444,
             X.UC_X86_REG_R12: 0x5555, X.UC_X86_REG_R13: 0x6666, X.UC_X86_REG_R14: 0x7777, X.UC_X86_REG_R15: 0x8888}
    for r, val in saved.items():
        mu.reg_write(r, val)
    bad, hooks = [], []
    if abi and section:
        import capstone
        from unicorn import UC_HOOK_CODE
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        lo, hi = section

        def code(uc, addr, size, _):
            if addr == rig.SITE + 5:
                bad.extend(f'register {r} changed across the redirected call' for r, val in saved.items() if uc.reg_read(r) != val)
            if lo <= addr < hi:
                ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
                if ins.mnemonic == 'call' and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                    bad.append(f'misaligned call at {addr:#x}')
        hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.mem_write(rsp, struct.pack('<Q', 0))
        mu.reg_write(X.UC_X86_REG_RIP, rig.SITE)
        mu.emu_start(rig.SITE, rig.SITE + 5, count=3_000_000)
    finally:
        for k in hooks:
            mu.hook_del(k)
    assert not bad, bad
    assert mu.reg_read(X.UC_X86_REG_RAX) & 0xFFFF == 0x5A5A, 'the game function result is not returned'
    return struct.unpack('<q', e.read(amt, 8))[0], list(rig.log), amt


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        'heal-formula': ("    mov ecx, 100\n    sub ecx, eax\n    movsxd rcx, ecx                     // 100 - p\n",
                         "    mov ecx, 100\n    sub ecx, eax\n    inc ecx\n    movsxd rcx, ecx\n"),
        'heal-hostile': ("    jnc .hm_next                        // not hostile to the healed unit\n", ""),
        'heal-row': ("    mov rdi, 0x200000000                // F2_ENEMY_HEAL_PERCENT: second-word bit 1\n",
                     "    mov rdi, 0x100000000\n"),
        'heal-active': ("    cmp byte ptr [r14 + 0x2e8], 0\n    je .hm_next                         // not on the map\n", ""),
        'heal-carried': ("    cmp word ptr [r14 + 0x2ee], 0\n    jge .hm_next                        // carried by another unit\n"
                         "    mov rsi, qword ptr [r14 + 0x240]\n    test rsi, rsi\n    jz .hm_next\n    cmp dword ptr [rsi + 0x4348], 0x28a",
                         "    mov rsi, qword ptr [r14 + 0x240]\n    test rsi, rsi\n    jz .hm_next\n    cmp dword ptr [rsi + 0x4348], 0x28a"),
        'satina-hp': ("    cmp r8, rcx\n    jle .n_dist\n    jmp .n_next\n.n_prov_filter:", "    cmp r8, rcx\n    jl .n_dist\n    jmp .n_next\n.n_prov_filter:"),
        'satina-dead': ("    cmp qword ptr [rdi + 0x2cc8], 0\n    jle .n_next                           // a defeated unit is not \"an enemy with low HP\"\n", ""),
        'satina-relation': ("    mov edx, dword ptr [rsp + 0x3c]\n    mov r8d, dword ptr [rsp + 0x40]\n    mov r10d, 13\n",
                            "    xor edx, edx\n    mov r8d, dword ptr [rsp + 0x40]\n    mov r10d, 13\n"),
    }
    old, new = edits[control]
    # the carried / active edits appear only inside wrap_healmod: it is the last user of these exact lines
    assert text.count(old) == 1, (control, text.count(old))
    out = SCRATCH / f'd5evil-drpgsig1-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def heal_section(kit, control, abi, section, check):
    row = overlay_rows(164, SERAPHINA)
    assert row == [{'family': 'enemy_heal_percent', 'effects': [{'value': 35}]}], row
    H = lambda slot, ids, team, active=1, carried=-1: (slot, ids, team, active, carried)
    S = (SERAPHINA,)
    # (name, healed unit's team, holders, expected amount) ; the stub makes 1000 -> 750 before the wrapper
    cases = [
        ('no holder anywhere: only the game pass (750)', 0, [], 750),
        ('a hostile holder (team 1), 35 percent: 750 -> 487', 0, [H(3, S, 1)], 487),
        ('hostile holder of team 3', 0, [H(3, S, 3)], 487),
        ('hostile holder of team 5', 0, [H(3, S, 5)], 487),
        ('holder of the healed unit\'s own team: nothing', 0, [H(3, S, 0)], 750),
        ('holder of the neutral team 2: nothing', 0, [H(3, S, 2)], 750),
        ('team 1 is not hostile to team 2: a healed unit of team 2 is not touched by a team-1 holder', 2, [H(3, S, 1)], 750),
        ('team 1 healed, team 0 holder hostile to it', 1, [H(3, S, 0)], 487),
        ('team 4 healed, team 3 holder', 4, [H(3, S, 3)], 487),
        ('two hostile holders: the game\'s per-holder product (750 -> 487 -> 316)', 0, [H(3, S, 1), H(4, S, 3)], 316),
        ('three hostile holders: 316 -> 205', 0, [H(3, S, 1), H(4, S, 3), H(5, S, 5)], 205),
        ('a holder that is not on the map: nothing', 0, [H(3, S, 1, active=0)], 750),
        ('a holder carried by another unit: nothing', 0, [H(3, S, 1, carried=2)], 750),
        ('a hostile unit without the row: nothing', 0, [H(3, (), 1)], 750),
        ('a hostile unit with another ordinary row (regen): nothing', 0, [H(3, (REGEN_ID,), 1)], 750),
        ('a hostile unit with another second-word row (face_target_away): nothing', 0, [H(3, (OTHER_FAMILY_ID,), 1)], 750),
        ('the row among other learned ids', 0, [H(3, (5, 9, SERAPHINA, 40000), 1)], 487),
        ('holder in the last battle slot (255)', 0, [H(255, S, 1)], 487),
        ('holder in slot 0', 0, [H(0, S, 1)], 487),
        ('a record without a unit record: skipped', 0, [(3, None, 1, 1, -1)], 750),
    ]
    ok = n = 0
    for name, team, holders, want in cases:
        base, blog, _ = run_heal(control, team, holders)
        got, log, amt = run_heal(kit, team, holders, abi=abi, section=section)
        problems = []
        if got != want:
            problems.append(f'kit amount {got}, expected {want}')
        if base != 750:
            problems.append(f'the original exe changed the amount to {base}')
        if len(log) != 1 or log[0][0] != 1000 or log[0][1] != TABLE + 2 * STRIDE or log[0][2] != TABLE + STRIDE or log[0][3] != 0x1234:
            problems.append(f'the game pass was not entered once with the site arguments, amount 1000: {log}')
        good = not problems
        n += 1
        ok += good
        print(f"{'ok  ' if good else 'FAIL'} heal: {name}{'' if good else ': ' + '; '.join(problems)}")
    # value and amount sweeps against an independent model of the formula (signed truncation, one holder at a time)
    for value in (1, 20, 35, 50, 99, 100):
        for amount in (0, 1, 7, 100, 999, 1000, 123456):
            ev_rows = {SERAPHINA: {'family': 'enemy_heal_percent', 'effects': [{'value': value}]}}
            k2 = kit_for(ev_rows, abi)
            got, log, _ = run_heal(k2[0], 0, [H(3, S, 1), H(4, S, 3)], amount=amount, abi=abi, section=k2[1])
            a = int(amount * 3 / 4)
            for _ in range(2):
                a = a * (100 - value) // 100          # positive amounts: floor == trunc
            n += 1
            good = got == a
            ok += good
            if not good:
                print(f'FAIL heal sweep value {value} amount {amount}: {got} != {a}')
    print(f'ok   heal sweep: 6 values x 7 amounts, two holders each ({n - len(cases)} checks)')
    # no target record / no unit: the amount only goes through the game pass
    got, log, _ = run_heal(kit, 0, [H(3, S, 1)], no_target=True, abi=abi, section=section)
    n += 1
    ok += got == 750
    print(f"{'ok  ' if got == 750 else 'FAIL'} heal: no healed-unit record: only the game pass ({got})")
    return ok, n


SATINA = 28256


def satina_section(abi, control_unused=None):
    from abi_engine_ex05c import execute
    rows = overlay_rows(273, SATINA)
    assert [r['family'] for r in rows] == ['dealt', ['dealt', 'aura']] and rows[0]['conditions'] == \
        [{'kind': 'map_hp_at_or_below', 'count': 1, 'of': 2, 'id': 50}], rows
    original = h.ORIGINAL.read_bytes()
    patched = ev.build_patch(original, {SATINA: rows})
    info = ev.section_info(patched)
    specs = [(ev.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in ev.WRAPPERS]
    _, target, sites = next(sp for sp in specs if sp[0] == 'dealt')
    assert sites == [0x1401C169D], sites
    U = h.unit
    ENEMY, ALLY, NEUTRAL = 1, 0, 2
    # (name, attacker ids, attacker unit, target unit (slot 1), extra units [(unit, cell, slot)], expected percent)
    holder = lambda: U((SATINA,), team=ALLY)                                  # the holder attacks: its own row
    recipient = lambda: U((), team=ALLY)                                      # an ally of the holder: the aura row
    low = lambda team=ENEMY, hp=50, mx=100: U((), team=team, hp=hp, max_hp=mx)
    cases = [
        ('enemy at exactly 50 percent: the row holds (hp 50 of 100)', (SATINA,), holder(), low(), (), 30),
        ('enemy at 51 percent: not', (SATINA,), holder(), low(hp=51), (), 0),
        ('enemy at 49 percent', (SATINA,), holder(), low(hp=49), (), 30),
        ('fraction on the line: 33 of 66', (SATINA,), holder(), low(hp=33, mx=66), (), 30),
        ('fraction just above the line: 34 of 66', (SATINA,), holder(), low(hp=34, mx=66), (), 0),
        ('enemy at full HP', (SATINA,), holder(), low(hp=100), (), 0),
        ('enemy with 1 HP', (SATINA,), holder(), low(hp=1, mx=100000), (), 30),
        ('a defeated enemy (HP 0) is not an enemy with low HP', (SATINA,), holder(), low(hp=0), (), 0),
        ('an enemy with max HP 0 is ignored', (SATINA,), holder(), low(hp=0, mx=0), (), 0),
        ('HP above max (overheal)', (SATINA,), holder(), low(hp=150), (), 0),
        ('64-bit HP: 4e12 of 1e13 holds', (SATINA,), holder(), low(hp=4 * 10 ** 12, mx=10 ** 13), (), 30),
        ('64-bit HP: 6e12 of 1e13 does not', (SATINA,), holder(), low(hp=6 * 10 ** 12, mx=10 ** 13), (), 0),
        ('the low enemy is not the target but another unit on the map', (SATINA,), holder(), low(hp=100),
         ((low(hp=10), (6, 9), 2),), 30),
        ('two enemies, only the healthy one in sight: none low', (SATINA,), holder(), low(hp=100), ((low(hp=90), (6, 9), 2),), 0),
        ('a low ALLY does not count (relation is enemy)', (SATINA,), holder(), low(hp=100), ((low(team=ALLY, hp=10), (6, 9), 2),), 0),
        ('a low unit of the neutral team does not count', (SATINA,), holder(), low(hp=100), ((low(team=NEUTRAL, hp=10), (6, 9), 2),), 0),
        ('no row: nothing even with a low enemy', (), U((), team=ALLY), low(), (), 0),
        ('aura: an ally of the holder attacks while an enemy is low', (), recipient(), low(), ((U((SATINA,), team=ALLY), (6, 9), 2),), 30),
        ('aura: same ally, the enemy is healthy', (), recipient(), low(hp=100), ((U((SATINA,), team=ALLY), (6, 9), 2),), 0),
        ('aura: the holder is an ENEMY of the attacker: it gives nothing', (), recipient(), low(), ((U((SATINA,), team=ENEMY), (6, 9), 2),), 0),
    ]
    ok = n = 0
    for name, ids, subject, other, others, want in cases:
        n += 1
        fx = h.fixture(subject, other=other, others=others)
        try:
            d = execute(patched, info, specs, 'dealt', target, sites[0], ids=ids, abi=abi, fixture=fx, out_value=50, original_rax=0,
                        supplied_stack_args=(ACTION, 1, 0))
            assert d['output'] == want, (d['output'], want)
            ok += 1
            print('ok   satina:', name)
        except Exception as exc:                             # noqa: BLE001
            print('FAIL satina:', name, f'{type(exc).__name__}: {exc}')
    # the subject is off the map: the relation walk has no subject battle record, the row is false
    n += 1
    try:
        d = execute(patched, info, specs, 'dealt', target, sites[0], ids=(SATINA,), abi=abi,
                    fixture=h.fixture(holder(), other=low(), on_map=False), out_value=50, original_rax=0,
                    supplied_stack_args=(ACTION, 1, 0))
        assert d['output'] == 0, d['output']
        ok += 1
        print('ok   satina: subject off the map: false')
    except Exception as exc:                                 # noqa: BLE001
        print('FAIL satina: off the map', f'{type(exc).__name__}: {exc}')
    return ok, n


_KITS = {}


def kit_for(rows, abi):
    """(Rig, section) for a table of these rows on the kit build, cached by content"""
    key = json.dumps(rows, sort_keys=True)
    if key not in _KITS:
        patched = ev.build_patch(h.ORIGINAL.read_bytes(), rows)
        info = ev.section_info(patched)
        tmp = Path(tempfile.mkdtemp(prefix='drpgsig1-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _KITS[key] = (Rig(tmp / 'kit.exe'), (info['code'], info['base'] + len(info['data'])), hashlib.sha256(patched).hexdigest()[:16])
    return _KITS[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    assert hashlib.sha256(h.ORIGINAL.read_bytes()).hexdigest() == h.ORIGINAL_SHA
    control = Rig(h.ORIGINAL)                                 # the pinned original exe, not the live one
    rows = {SERAPHINA: overlay_rows(164, SERAPHINA)[0], REGEN_ID: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 1}]},
            OTHER_FAMILY_ID: {'family': 'face_target_away'}}
    kit, section, sha = kit_for(rows, args.abi)
    total_ok = total_n = 0
    ok, n = heal_section(kit, control, args.abi, section, args.control)
    total_ok += ok
    total_n += n
    ok, n = satina_section(args.abi)
    total_ok += ok
    total_n += n
    print(f"{total_ok}/{total_n} {'abi' if args.abi else 'behavior'}; kit build sha256 {sha}, control exe {control.e.exe_sha[:16]}")
    return 0 if total_ok == total_n else 1


if __name__ == '__main__':
    sys.exit(main())
