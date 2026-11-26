"""D4SIG10 offline proof: Medic's Base Hospital (D4 864, row 27864) through the pinned game's REAL call sites of turn_t1_per_unit_hp_sp.

wrap_regen redirects the two static calls of T1 (0x140551AC0): 0x140554B9E (sequencer_ctl_s1_update, the round-end sweep, team 0/4 units) and 0x1405FB5DF
(TurnCtl init PASS B, the other side).  Each is run from the call instruction to its return on the kit build under Unicorn (T1 itself is a stub that records
its argument and returns a marker), and the same call on the pinned original exe as the control.

D4 rule (FUN_1402EB670 lines 545-574): for each unit with 864, every roster record that is alive, has +0x20D3 == 0 and has no battle unit gets
maxHP * 5 / 100 added to HP and maxSP * 5 / 100 to SP (signed truncation), each clamped at its maximum.  D5 adaptations are in evilgap1_rows.py.

D5Modkit/.venv-macos/bin/python evility/offline_proof_d4sig10.py [--abi] [--control NAME]
Controls (a deliberately broken wrapper; the proof must then FAIL): hosp-call, hosp-id, hosp-team, hosp-dead, hosp-deployed, hosp-clamp, hosp-sp,
hosp-count, hosp-magic, hosp-recteam, hosp-pct, hosp-present
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
sys.path[:0] = [str(KIT), str(KIT / 'evility'), str(KIT / 'tools')]
from d5lib import evility as ev                                                  # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_d4sig7 as s7                                                # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig10')
OVERLAY = KIT / 'd5lib/importers/d4-evility-overlay.json'
BASE = 27864
T1 = 0x140551AC0
SITES = (0x140554B9E, 0x1405FB5DF)
ROSTER, RSTRIDE, RCOUNT = 0x145207DB8, 0x4750, 0x145574A9C
UNITS, USTRIDE = 0x141BA33B0, 4704
SR0, SRSTRIDE = 0x141067DC8, 0xE98
MARK = 0x4D4D


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        # the hospital is never called
        'hosp-call': ("    call evil_hospital                // D4SIG10", "    nop                // D4SIG10"),
        # the wrong evility id
        'hosp-id': ("    mov edx, 27864\n    call evil_has_id", "    mov edx, 27863\n    call evil_has_id"),
        # a unit of any team acts
        'hosp-team': ("    and eax, 0xfb\n    jnz .hs_ret                         // not a player-side unit\n", ""),
        # the dead are healed too
        'hosp-dead': ("    jle .hs_next                        // dead\n", ""),
        # deployed units are healed too
        'hosp-deployed': ("    je .hs_next                         // deployed: not in the base panel\n", "    nop\n"),
        # no clamp at the maximum (HP)
        'hosp-clamp': ("    cmp rbx, rax\n    cmovl rax, rbx\n    mov qword ptr [r13 + 0x2cc8], rax", "    mov qword ptr [r13 + 0x2cc8], rax"),
        # SP is not healed
        'hosp-sp': ("    mov qword ptr [r13 + 0x2cd0], rax\n", ""),
        # the loop runs one record too far
        'hosp-count': ("    cmp r14d, r12d\n    jge .hs_ret", "    cmp r14d, r12d\n    jg .hs_ret"),
        # a Magichange weapon is healed too
        'hosp-magic': ("    jne .hs_next                        // absorbed into another unit: D5's counterpart of D4's +0x20D3\n", ""),
        # another side's records are healed too
        'hosp-recteam': ("    cmp byte ptr [r13 + 0x2e32], 0\n    jne .hs_next                        // not a player record (the table also holds the other sides)\n", ""),
        # an empty slot is healed too
        'hosp-present': ("    cmp dword ptr [r13], 0\n    je .hs_next                         // empty slot\n", ""),
    }
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f'd5evil-d4sig10-{control}.inc.asm'
    if control == 'hosp-pct':
        old = "    imul rax, rbx, 5\n"
        assert text.count(old) == 2
        out.write_text(text.replace(old, "    imul rax, rbx, 6\n", 1))
        return out
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    out.write_text(text.replace(old, new))
    return out


def d4(hp, mx):
    """FUN_1402EB670: HP/SP + max * 5 / 100 (truncated toward 0), clamped at the maximum"""
    add = int(mx * 5 / 100) if mx >= 0 else -int(-mx * 5 / 100)
    new = hp + add
    return mx if mx < new else new


class HospRig(s7.DragonRig):
    def __init__(self, exe, stub_t1=True):
        super().__init__(exe)
        self.t1calls = []
        if stub_t1:
            from unicorn import UC_HOOK_CODE
            X = self.e.X

            def t1():
                self.t1calls.append(self.e.mu.reg_read(X.UC_X86_REG_RCX))
                return MARK
            self.e.stubs[T1] = t1
            self.e.mu.hook_add(UC_HOOK_CODE, self.e._stub, begin=T1, end=T1)

    def reset(self, count=0):
        e = self.e
        e.brk = e.heap_mark
        e.mu.mem_write(SR0, bytes(SRSTRIDE * 0x28A))
        e.mu.mem_write(ROSTER, bytes(RSTRIDE * 130))
        e.mu.mem_write(UNITS, bytes(USTRIDE * 256))
        e.mu.mem_write(RCOUNT, struct.pack('<h', count))
        self.t1calls.clear()

    def rec(self, i, hp=100, mx=1000, sp=10, msp=200, team=0, present=1, stat=0x28A):
        va = ROSTER + i * RSTRIDE
        b = bytearray(0x4400)
        struct.pack_into('<I', b, 0, present)
        struct.pack_into('<qqqq', b, 0x2cc8, hp, sp, 0, 0)          # +0x2CC8 HP, +0x2CD0 SP
        struct.pack_into('<q', b, 0x2cd8, mx)
        struct.pack_into('<q', b, 0x2ce0, msp)
        b[0x2e32] = team
        struct.pack_into('<I', b, 0x4348, stat)
        self.e.mu.mem_write(va, bytes(b))
        return va

    def vals(self, i):
        va = ROSTER + i * RSTRIDE
        hp, sp = struct.unpack('<qq', self.e.read(va + 0x2cc8, 16))
        return hp, sp

    def deploy(self, slot, rec, active=1):
        va = UNITS + slot * USTRIDE
        b = bytearray(USTRIDE)
        b[0x2e8] = active
        struct.pack_into('<Q', b, 0x240, rec)
        self.e.mu.mem_write(va, bytes(b))

    def magic(self, stat, v=1):
        self.e.mu.mem_write(SR0 + stat * SRSTRIDE + 0x4E2, bytes([v]))

    def provider(self, ids, team=0, stat=0x28A):
        e = self.e
        u = bytearray(s7.dunit(ids, stat))
        u[0x2e32] = team
        unit = e.alloc(bytes(u))
        b = bytearray(0x1300)
        struct.pack_into('<Q', b, 0x240, unit)
        return e.alloc(bytes(b))

    def call(self, site, brec, abi, sect):
        return self.start(site, dict(rcx=brec), {}, abi, sect, None)


_RIGS = {}


def rigs():
    if not _RIGS:
        original = ORIGINAL.read_bytes()
        assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
        st = json.loads(OVERLAY.read_text())['mods']['D4_Class_1240']
        assert st['behaviors']['evilities'] == {}, st['behaviors']
        assert [r['id'] for r in st['skill_rows']] == [BASE] and st['skill_rows'][0]['value1'] == 5
        assert all(v['evility1'] == BASE for v in st['char_links'].values()) and len(st['char_links']) == 6
        patched = ev.build_patch(original, {})
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='d4sig10-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _RIGS.update(kit=HospRig(tmp / 'kit.exe'), control=HospRig(ORIGINAL),
                     section=(info['code'], info['base'] + len(info['data'])), sha=hashlib.sha256(patched).hexdigest())
    return _RIGS


def section(abi):
    r = rigs()
    kit, control, sect = r['kit'], r['control'], r['section']
    ok = n = 0

    def report(name, problems):
        nonlocal ok, n
        n += 1
        ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + 'hospital: ' + name + ('' if not problems else ': ' + '; '.join(problems)))

    HOLD, OTHER = (BASE,), (5, 9, 27807, 27863, 40000)

    def scenario(rig, site, recs, count, deploy=(), magic=(), ids=HOLD, team=0, runs=1, a=0, sc=None):
        """recs = {index: kwargs of rec()}; returns {index: (hp, sp)} after `runs` provider calls through the real site"""
        rig.reset(count)
        for i, kw in recs.items():
            rig.rec(i, **kw)
        for slot, rec_i, active in deploy:
            rig.deploy(slot, ROSTER + rec_i * RSTRIDE, active)
        for stat in magic:
            rig.magic(stat)
        brec = rig.provider(ids, team)
        for _ in range(runs):
            rig.call(site, brec, a, sc)
        return {i: rig.vals(i) for i in recs}, brec

    base = dict(hp=100, mx=1000, sp=10, msp=200)
    for site in SITES:
        tag = f'site {site:#x}: '
        a, sc = abi, sect

        def run(name, recs, count, want, **kw):
            got, _ = scenario(kit, site, recs, count, a=a, sc=sc, **kw)
            bad = [f'record {i}: {got[i]}, want {want[i]}' for i in recs if got[i] != want[i]]
            report(tag + name, bad)

        run('an undeployed living player record gets 5% of max HP and SP', {0: base}, 1, {0: (150, 20)})
        run('HP and SP clamp at the maximum', {0: dict(hp=990, mx=1000, sp=199, msp=200)}, 1, {0: (1000, 200)})
        run('HP clamps and SP does not (independent)', {0: dict(hp=990, mx=1000, sp=10, msp=200)}, 1, {0: (1000, 20)})
        run('already at the maximum stays', {0: dict(hp=1000, mx=1000, sp=200, msp=200)}, 1, {0: (1000, 200)})
        run('truncation: max 99 -> +4, max 19 -> +0 (no minimum of 1)', {0: dict(hp=50, mx=99, sp=5, msp=19)}, 1, {0: (54, 5)})
        run('max 20 -> +1 exactly', {0: dict(hp=5, mx=20, sp=5, msp=20)}, 1, {0: (6, 6)})
        run('max 0: HP above the max is clamped to 0 (D4 does the same arithmetic)', {0: dict(hp=7, mx=0, sp=0, msp=0)}, 1, {0: (0, 0)})
        run('a dead record (HP 0) is not healed', {0: dict(hp=0, mx=1000, sp=10, msp=200)}, 1, {0: (0, 10)})
        run('a record with negative HP is not healed', {0: dict(hp=-5, mx=1000, sp=10, msp=200)}, 1, {0: (-5, 10)})
        run('an empty slot (present 0) is not healed', {0: dict(base, present=0)}, 1, {0: (100, 10)})
        run('another side\'s record (team 1) is not healed', {0: dict(base, team=1)}, 1, {0: (100, 10)})
        run('team 4 (not a player record) is not healed', {0: dict(base, team=4)}, 1, {0: (100, 10)})
        run('a deployed record (active battle unit) is not healed', {0: base, 1: base}, 2, {0: (100, 10), 1: (150, 20)}, deploy=[(7, 0, 1)])
        run('a battle unit that is not active does not count as deployed', {0: base}, 1, {0: (150, 20)}, deploy=[(7, 0, 0)])
        run('a deployed record in the last battle slot (255) is found', {0: base}, 1, {0: (100, 10)}, deploy=[(255, 0, 1)])
        run('a deployed record in battle slot 0 is found', {0: base}, 1, {0: (100, 10)}, deploy=[(0, 0, 1)])
        run('a Magichange weapon record (stat record +0x4E2) is not healed', {0: dict(base, stat=5), 1: dict(base, stat=6)}, 2,
            {0: (100, 10), 1: (150, 20)}, magic=[5])
        run('stat index 0x28A (no stat record) is healed, nothing is read', {0: dict(base, stat=0x28A)}, 1, {0: (150, 20)}, magic=[0x289])
        run('count 0: nothing', {0: base}, 0, {0: (100, 10)})
        run('count -1 (a signed short): nothing', {0: base}, -1, {0: (100, 10)})
        run('only the first `count` records: record 2 untouched', {0: base, 1: base, 2: base}, 2, {0: (150, 20), 1: (150, 20), 2: (100, 10)})
        recs = {i: dict(hp=10 + i, mx=1000, sp=1, msp=100) for i in range(128)}
        run('all 128 records, the last one (127) included', recs, 128, {i: (10 + i + 50, 6) for i in range(128)})
        run('two providers: each adds its own share (two calls)', {0: base}, 1, {0: (200, 30)}, runs=2)
        run('two providers: the clamp applies after each', {0: dict(hp=960, mx=1000, sp=190, msp=200)}, 1, {0: (1000, 200)}, runs=2)
        run('a team-4 provider acts like the game\'s own T1 gate (team & 0xFB == 0)', {0: base}, 1, {0: (150, 20)}, team=4)
        for who, ids, team in (('without the id', (), 0), ('with other ids', OTHER, 0), ('holder of the id on team 1', HOLD, 1),
                               ('holder on team 2', HOLD, 2), ('holder on team 5', HOLD, 5)):
            run(f'a provider {who}: nothing happens', {0: base}, 1, {0: (100, 10)}, ids=ids, team=team)
        # the original exe is the control: no wrapper, nothing happens
        got, _ = scenario(control, site, {0: base}, 1, a=0, sc=None)
        report(tag + 'the pinned exe heals nothing', [] if got[0] == (100, 10) else [str(got)])
        # the game's own function is entered exactly once, with the battle record and its answer is returned unchanged
        for ids, team in ((HOLD, 0), ((), 0), (HOLD, 1)):
            kit.reset(1)
            kit.rec(0, **base)
            brec = kit.provider(ids, team)
            rax = kit.call(site, brec, a, sc)
            report(tag + f'T1 entered once with the battle record, answer kept (ids {ids}, team {team})',
                   [] if kit.t1calls == [brec] and rax == MARK else [f'{kit.t1calls} rax {rax:#x}'])
        # guards
        kit.reset(1)
        kit.rec(0, **base)
        rax = kit.call(site, 0, a, sc)
        report(tag + 'a null battle record: only the game call', [] if kit.t1calls == [0] and kit.vals(0) == (100, 10) and rax == MARK else [str(kit.t1calls)])
        kit.reset(1)
        kit.rec(0, **base)
        b = kit.e.alloc(bytes(0x1300))
        rax = kit.call(site, b, a, sc)
        report(tag + 'a battle record without a unit: only the game call', [] if kit.t1calls == [b] and kit.vals(0) == (100, 10) else [str(kit.t1calls)])
        # fields the walk must not touch
        got, _ = scenario(kit, site, {0: dict(hp=100, mx=1000, sp=10, msp=200), 1: dict(base, present=0)}, 2, a=a, sc=sc)
        before = kit.e.read(ROSTER + 0 * RSTRIDE, 0x4400)
        report(tag + 'maxima, team and the other record bytes are unchanged',
               [] if (struct.unpack('<q', before[0x2cd8:0x2ce0])[0], struct.unpack('<q', before[0x2ce0:0x2ce8])[0], before[0x2e32]) == (1000, 200, 0)
               and got[1] == (100, 10) else ['changed'])
    # D4's arithmetic as a table, against the model (every record is a case)
    pairs = [(0, 0), (1, 1), (0, 19), (0, 20), (5, 99), (999, 1000), (1000, 1000), (50, 9999), (1, 2147483647), (1, 100), (0, 39), (0, 40)]
    for site in SITES:
        recs = {i: dict(hp=hp, mx=mx, sp=hp, msp=mx) for i, (hp, mx) in enumerate(pairs)}
        # HP 0 records are dead, so give them HP 1 and expect the model on that
        recs = {i: dict(hp=max(hp, 1), mx=mx, sp=max(hp, 1), msp=mx) for i, (hp, mx) in enumerate(pairs)}
        got, _ = scenario(kit, site, recs, len(pairs), a=abi, sc=sect)
        bad = [f'{recs[i]}: {got[i]}, want {(d4(recs[i]["hp"], recs[i]["mx"]), d4(recs[i]["sp"], recs[i]["msp"]))}' for i in recs
               if got[i] != (d4(recs[i]['hp'], recs[i]['mx']), d4(recs[i]['sp'], recs[i]['msp']))]
        report(f'site {site:#x}: {len(pairs)} (HP, max) pairs against the D4 arithmetic', bad)
    return ok, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    ok, n = section(args.abi)
    assert ok == n, f'{ok}/{n} checks passed'
    sha = rigs()['sha']
    if args.json:
        args.json.write_text(json.dumps(dict(mode='abi' if args.abi else 'behavior', patched_sha256=sha, passed=True, checks=n), indent=1) + '\n')
    print(f"{n}/{n} checks passed (D4SIG10 hospital, {'abi' if args.abi else 'behavior'}; patched exe {sha[:16]})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
