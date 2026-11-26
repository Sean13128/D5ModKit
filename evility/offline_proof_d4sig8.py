"""D4SIG8 offline proof: Demon Beast's Stone Statue (D4 807, row 27807) counts by D4's rule, through the pinned game's REAL call sites.

wrap_endturn redirects the three static calls of turn_t3_per_unit_end_turn (0x140159F50): 0x1405524FF (turn_t1_per_unit_hp_sp), 0x140554F7F
(sequencer_ctl_s1_update), 0x1405FB9B1 (FUN_1405FAF90).  Each is run from the call instruction to its return on the kit build under Unicorn, with the
game's own T3 executing (real code, real stat-record array), and the same call on the pinned original exe as the control.

D4 rule (FUN_1400F3C20): move cost == 0 -> counter + 1 while it is below 10 (a byte), else 0; nothing else is tested.
D5 rule (T3): the same, but the counter is also zeroed when the stat-record byte SR+2, the battle byte +0x11E1 or (mode 1) +0x11F5 is set.

D5Modkit/.venv-macos/bin/python evility/offline_proof_d4sig8.py [--abi] [--control NAME]
Controls (a deliberately broken wrapper; the proof must then FAIL): endturn-cost, endturn-zero, endturn-cap, endturn-holder, endturn-id,
endturn-keep, endturn-argument
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

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig8')
OVERLAY = KIT / 'd5lib/importers/d4-evility-overlay.json'
STONE = 27807
SR0, STRIDE = 0x141067DC8, 0xE98
T3 = 0x140159F50
SITES = (0x1405524FF, 0x140554F7F, 0x1405FB9B1)
MODE = 0x145574AA8                          # DAT_145574aa8: T3 tests +0x11F5 only when it is 1
BREC = 0x1300


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        # the move cost is not tested: every round edge counts
        'endturn-cost': ("    cmp word ptr [rbx + 0x61c], 0\n    jne .et_zero                        // moved this turn: D4 zeroes it\n", ""),
        # a move does not zero the counter
        'endturn-zero': (".et_zero:\n    xor ebp, ebp\n", ".et_zero:\n"),
        # the cap is not 10
        'endturn-cap': ("    cmp ebp, 10\n    jae .et_call", "    cmp ebp, 99\n    jae .et_call"),
        # every unit is a holder
        'endturn-holder': ("    call evil_has_id\n    test eax, eax\n    jz .et_call\n    movzx ebp,", "    call evil_has_id\n    movzx ebp,"),
        # the wrong evility id
        'endturn-id': ("    mov edx, 27807\n    call evil_has_id", "    mov edx, 27806\n    call evil_has_id"),
        # D4's value is not stored
        'endturn-keep': ("    mov byte ptr [rdi], bpl\n", ""),
        # the game's function is called with the unit record instead of the battle record
        'endturn-argument': ("    mov rcx, rbx\n    call 0x140159f50\n", "    mov rcx, rsi\n    call 0x140159f50\n"),
    }
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f'd5evil-d4sig8-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def d4(prev, cost):
    """FUN_1400F3C20's Stone Statue counter"""
    if cost == 0:
        return prev + 1 if prev < 10 else prev
    return 0


class T3Rig(s7.DragonRig):
    def __init__(self, exe, stub_t3=False):
        super().__init__(exe)
        self.t3calls = []
        if stub_t3:
            from unicorn import UC_HOOK_CODE
            X = self.e.X

            def t3():
                self.t3calls.append(self.e.mu.reg_read(X.UC_X86_REG_RCX))
                return 0x6C6C
            self.e.stubs[T3] = t3
            self.e.mu.hook_add(UC_HOOK_CODE, self.e._stub, begin=T3, end=T3)

    def make(self, idx, ids, prev, cost=0, sr2=0, hit=0, f5=0):
        e = self.e
        rec = bytearray(STRIDE)
        rec[1], rec[2] = prev, sr2
        e.mu.mem_write(SR0 + idx * STRIDE, bytes(rec))
        unit = e.alloc(s7.dunit(ids, idx))
        b = bytearray(BREC)
        struct.pack_into('<Q', b, 0x240, unit)
        struct.pack_into('<h', b, 0x61C, cost)
        b[0x11E1], b[0x11F5] = hit, f5
        return e.alloc(bytes(b))

    def reset(self):
        e = self.e
        e.brk = e.heap_mark
        e.mu.mem_write(SR0, bytes(STRIDE * 0x28A))
        self.t3calls.clear()

    def sr(self, idx, off=1):
        return self.e.read(SR0 + idx * STRIDE + off, 1)[0]


_RIGS = {}


def rigs():
    if not _RIGS:
        original = ORIGINAL.read_bytes()
        assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
        row = json.loads(OVERLAY.read_text())['mods']['D4_Class_2090']['behaviors']['evilities'][str(STONE)]
        assert row == {'family': 'stats', 'effects': [{'stat': 'def', 'value': 10, 'per': 'idle_turns'}]}, row
        patched = ev.build_patch(original, {STONE: row})
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='d4sig8-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _RIGS.update(kit=T3Rig(tmp / 'kit.exe'), stub=T3Rig(tmp / 'kit.exe', stub_t3=True), control=T3Rig(ORIGINAL),
                     section=(info['code'], info['base'] + len(info['data'])), sha=hashlib.sha256(patched).hexdigest())
    return _RIGS


def run(rig, site, abi, section, ids, prev, cost=0, sr2=0, hit=0, mode=0, f5=0, idx=3, neighbours=True):
    """one real call of T3 through `site`; returns (counter, sr2 after, cost after, neighbour counters)"""
    rig.reset()
    rig.e.mu.mem_write(MODE, struct.pack('<I', mode))
    if neighbours:
        rig.make(idx - 1, (STONE,), 7, sr2=1)
        rig.make(idx + 1, (), 9, sr2=1)
    brec = rig.make(idx, ids, prev, cost, sr2, hit, f5)
    rig.start(site, dict(rcx=brec), {}, abi, section, None)
    cost_after = struct.unpack('<h', rig.e.read(brec + 0x61C, 2))[0]
    return rig.sr(idx), rig.sr(idx, 2), cost_after, (rig.sr(idx - 1), rig.sr(idx + 1))


def section(abi):
    r = rigs()
    kit, stub, control, sect = r['kit'], r['stub'], r['control'], r['section']
    ok = n = 0

    def report(name, problems):
        nonlocal ok, n
        n += 1
        ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + 'endturn: ' + name + ('' if not problems else ': ' + '; '.join(problems)))

    HOLD, NONE, OTHER = (STONE,), (), (5, 9, 27663, 40000)
    # (name, prev, cost, sr2, hit, mode, f5)
    table = [
        ('idle round edge: 0 -> 1', 0, 0, 0, 0, 0, 0),
        ('idle: 3 -> 4', 3, 0, 0, 0, 0, 0),
        ('idle: 9 -> 10', 9, 0, 0, 0, 0, 0),
        ('at the cap 10 stays 10', 10, 0, 0, 0, 0, 0),
        ('moved (cost 3) zeroes it', 5, 3, 0, 0, 0, 0),
        ('moved (cost 1) zeroes it', 1, 1, 0, 0, 0, 0),
        ('moved (cost 0x7FFF) zeroes it', 6, 0x7FFF, 0, 0, 0, 0),
        ('moved (negative cost -1, a nonzero short) zeroes it', 6, -1, 0, 0, 0, 0),
        ('lifted/thrown (SR+2 = 1) does not stop the count: D5 would zero, D4 counts', 5, 0, 1, 0, 0, 0),
        ('SR+2 = 3 does not stop the count', 0, 0, 3, 0, 0, 0),
        ('hit by a skill (+0x11E1 = 1) does not stop the count', 5, 0, 0, 1, 0, 0),
        ('mode 1 with +0x11F5 = 1 does not stop the count', 5, 0, 0, 0, 1, 1),
        ('mode 0 with +0x11F5 = 1 counts (D5 counts too)', 5, 0, 0, 0, 0, 1),
        ('all three D5 blockers set, idle: counts', 2, 0, 2, 1, 1, 1),
        ('all three D5 blockers set and moved: zero', 8, 4, 2, 1, 1, 1),
        ('a corrupt counter of 200 is left alone when idle (D4 tests < 10)', 200, 0, 0, 0, 0, 0),
        ('a corrupt counter of 200 is zeroed by a move', 200, 2, 0, 0, 0, 0),
    ]
    for site in SITES:
        tag = f'site {site:#x}: '
        for name, prev, cost, sr2, hit, mode, f5 in table:
            problems = []
            got, g2, gcost, neigh = run(kit, site, abi, sect, HOLD, prev, cost, sr2, hit, mode, f5)
            want = d4(prev, cost)
            if got != want:
                problems.append(f'holder counter {got}, D4 says {want}')
            if neigh != (7, 9):
                problems.append(f'a neighbour moved: {neigh}')
            if g2 != 0 or gcost != 0:
                problems.append(f'the game call did not run (SR+2 {g2}, cost {gcost})')     # T3 clears both
            for who, ids in (('a unit without the id', NONE), ('a unit with other ids', OTHER)):
                kg, _, _, kn = run(kit, site, abi, sect, ids, prev, cost, sr2, hit, mode, f5)
                cg, _, _, _ = run(control, site, 0, None, ids, prev, cost, sr2, hit, mode, f5)
                if kg != cg or kn != (7, 9):
                    problems.append(f'{who}: kit {kg} != pinned exe {cg}')
            report(tag + name, problems)
    # D5's own rule (the control exe) really differs from D4 on the blocker cases: otherwise the cases above prove nothing
    d5 = [run(control, SITES[0], 0, None, HOLD, p, c, s, h, m, f)[0] for _, p, c, s, h, m, f in table]
    d5_want = [0 if (c or s or h or (m == 1 and f)) else (p + 1 if p < 10 else p) for _, p, c, s, h, m, f in table]
    report('the pinned exe follows D5 rule (zeroed by SR+2, +0x11E1, mode-1 +0x11F5 and a move)', [] if d5 == d5_want else [f'{d5} != {d5_want}'])
    differs = sum(1 for (_, p, c, s, h, m, f), g in zip(table, d5) if g != d4(p, c))
    report(f'D5 and D4 differ on {differs} of {len(table)} table rows', [] if differs >= 5 else ['too few differing rows'])
    # a run of round edges through a real site: idle x3 (SR+2 set on the 3rd), move, idle, idle (hit), 11 idle -> cap
    for site in SITES:
        rig = kit
        rig.reset()
        rig.e.mu.mem_write(MODE, struct.pack('<I', 0))
        seq = []
        for cost, sr2, hit in ((0, 0, 0), (0, 0, 0), (0, 1, 0), (4, 0, 0), (0, 0, 0), (0, 0, 1)) + ((0, 0, 0),) * 8:
            rec = rig.make(3, HOLD, rig.sr(3), cost, sr2, hit)
            rig.start(site, dict(rcx=rec), {}, abi, sect, None)
            seq.append(rig.sr(3))
        want = [1, 2, 3, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        report(f'site {site:#x}: a run of round edges (idle, idle, lifted, move, idle, hit, idle x8): {seq}', [] if seq == want else [f'expected {want}'])
    # the guards: the game call is made with the site argument unchanged and nothing is written when there is no holder state
    for site in SITES:
        stub.reset()
        stub.e.mu.mem_write(MODE, struct.pack('<I', 0))
        brec = stub.make(3, HOLD, 4, 0)
        stub.start(site, dict(rcx=brec), {}, abi, sect, None)
        report(f'site {site:#x}: the game function is entered once with the battle record unchanged',
               [] if stub.t3calls == [brec] and stub.sr(3) == 5 else [f'{stub.t3calls} counter {stub.sr(3)}'])
        stub.reset()
        stub.start(site, dict(rcx=0), {}, abi, sect, None)
        report(f'site {site:#x}: a null battle record: only the game call', [] if stub.t3calls == [0] else [str(stub.t3calls)])
        stub.reset()
        rec = stub.e.alloc(bytes(BREC))
        stub.start(site, dict(rcx=rec), {}, abi, sect, None)
        report(f'site {site:#x}: a record without a unit: only the game call', [] if stub.t3calls == [rec] else [str(stub.t3calls)])
        stub.reset()
        unit = stub.e.alloc(s7.dunit(HOLD, 0x28A))
        b = bytearray(BREC)
        struct.pack_into('<Q', b, 0x240, unit)
        rec = stub.e.alloc(bytes(b))
        stub.start(site, dict(rcx=rec), {}, abi, sect, None)
        report(f'site {site:#x}: a holder with stat index 0x28A (no stat record): only the game call, no write',
               [] if stub.t3calls == [rec] and all(stub.sr(i) == 0 for i in (0, 3, 0x289)) else [str(stub.t3calls)])
    # the highest legal stat slot
    got = run(kit, SITES[0], abi, sect, HOLD, 4, 0, idx=0x289, neighbours=False)[0]
    report('the holder in the last stat slot (0x289): 4 -> 5', [] if got == 5 else [str(got)])
    got = run(kit, SITES[1], abi, sect, HOLD, 4, 0, idx=0, neighbours=False)[0]
    report('the holder in stat slot 0: 4 -> 5', [] if got == 5 else [str(got)])
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
    print(f"{n}/{n} checks passed (D4SIG8 endturn, {'abi' if args.abi else 'behavior'}; patched exe {sha[:16]})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
