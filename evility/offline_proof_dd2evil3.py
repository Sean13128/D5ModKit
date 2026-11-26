"""DD2EVIL3 offline proof: Plume 570 "Brave Battle Princess" (row 26304) = kill_counter + holder_kills, through the pinned game's REAL call sites.

  writer  wrap_atkcount at the real call of damage_apply_damage (0x1401B1BE0, in FUN_1401B1BA0), the game's own apply stubbed to do what D5's does
          that matters here: lower the target's HP and add 1 to the target's stat record +0x5D8 (damage_apply_damage 0x1401B2527..0x1401B2544,
          skipped when ctx+0x276BC is set or the skill category is 4..6).  A kill_counter holder's +0x5D8 is its own defeat count: +1 when it
          attacks a target that was alive and is defeated by that apply; D5's +1 on a holder that is the target is taken back.
  reader  the real power site (wrap_power -> evil_dmg_sum): Plume's row is read verbatim from d5lib/importers/dd2-innate-evilities.json; the
          scale holder_kills sums the +0x5D8 of the OTHER same-team living holders, x10, capped at 200.
  wipe    the game's own model_stat_record_wipe (0x14015FAF0) run on a record with a count: the count is 0 and the reader sees 0.

<unicorn python> evility/offline_proof_dd2evil3.py [--abi] [--control NAME] [--section writer|reader|wipe]
Controls (a deliberately broken build; the proof must then FAIL): kc-lethal, kc-holder, kc-restore, kc-geo, kc-clamp, hk-self, hk-team, hk-dead,
hk-carried, hk-map, hk-id, hk-cap
"""
import argparse
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'tools'), str(KIT / 'evility')]
from d5lib import evility as ev                                                  # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_d4sig7 as s7                                                # noqa: E402
import offline_proof_ex05e as h                                                  # noqa: E402
import offline_proof_plume1 as plume1                                            # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/dd2evil3')
DATA = KIT / 'd5lib/importers/dd2-innate-evilities.json'
RID = 26304
WIPE_FN = 0x14015FAF0
SR0, SR_STRIDE = s7.SR0, s7.SR_STRIDE
POISON = s7.POISON


def plume_row(cap=None):
    d = json.loads(DATA.read_text())['packs']['DD2_Unique_570']['behavior']
    assert d == [{'family': ['power', 'aura'],
                  'effects': [{'value': 10, 'per': 'holder_kills', 'max': 200}],
                  'filter': RID,
                  'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 65535, 'id': RID}]},
                 {'family': 'kill_counter'}], d
    if cap is not None:
        d = json.loads(json.dumps(d))
        d[0]['effects'][0]['max'] = cap
    return d


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        # a count even when the target is still standing
        'kc-lethal': ("    cmp qword ptr [rsi + 0x2cc8], 0\n    jg .kc_post_done                    // still standing: no defeat\n", ""),
        # any attacker counts, not only holders
        'kc-holder': ("    cmp r15d, 3\n    jne .kc_post_done", "    test r15d, 2\n    jz .kc_post_done"),
        # D5's own +1 on a holder that is the target stays
        'kc-restore': ("    mov word ptr [rax + rcx], r14w\n.kc_post_att:", "    nop\n.kc_post_att:"),
        # a Geo Symbol family target is counted
        'kc-geo': ("    and r15d, 1                         // a Geo Symbol family target is not counted\n", ""),
        # D5's own clamp is not applied (the u16 may run on)
        'kc-clamp': ("    cmp edx, 0x270f\n    jae .kc_post_done                   // D5's own clamp\n", ""),
        # the holder_kills walk counts the subject itself
        'hk-self': ("    cmp rsi, r13\n    je .sc_hk_next                    // the subject itself is never counted\n", ""),
        'hk-team': ("    cmp eax, ebp\n    jne .sc_hk_next                   // another team\n", ""),
        'hk-dead': ("    cmp qword ptr [rcx + 0x2cc8], 0\n    jle .sc_hk_next                   // defeated\n", ""),
        'hk-carried': ("    cmp word ptr [rsi + 0x2ee], 0\n    jge .sc_hk_next                   // carried\n", ""),
        'hk-map': ("    cmp byte ptr [rsi + 0x2e8], 0\n    je .sc_hk_next                    // not on the map\n", ""),
        # any same-team unit counts, not only holders of the row
        'hk-id': ("    call evil_has_id\n    test eax, eax\n    jz .sc_hk_next\n", "    call evil_has_id\n"),
    }
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f'd5evil-dd2evil3-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


class Checker:
    def __init__(self, name):
        self.name, self.ok, self.n = name, 0, 0

    def __call__(self, label, problems):
        self.n += 1
        self.ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + f'{self.name}: {label}' + ('' if not problems else ': ' + '; '.join(map(str, problems))))


# ------------------------------------------------------------------------------------------------------------------------------ writer
class KRig(s7.DragonRig):
    """DragonRig whose damage_apply_damage stub also lowers the target's HP and counts like D5's (the condition of 0x1401B2505..0x1401B2525)"""

    def __init__(self, exe):
        super().__init__(exe)
        e, X = self.e, self.e.X
        self.dmg = 0

        def game_apply():
            mu = e.mu
            rsp = mu.reg_read(X.UC_X86_REG_RSP)
            args = tuple(mu.reg_read(r) for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9))
            fifth = struct.unpack('<Q', e.read(rsp + 0x28, 8))[0]
            self.log.append(('apply', args, fifth))
            ctx = args[2]
            unit = struct.unpack('<Q', e.read(args[1] + 0x240, 8))[0] if args[1] else 0
            if unit:
                idx = struct.unpack('<I', e.read(unit + 0x4348, 4))[0]
                row = struct.unpack('<Q', e.read(ctx + 0x27678, 8))[0]
                cat = e.read(row + 0x3F6, 1)[0] if row else None
                flag = e.read(ctx + 0x276BC, 1)[0]
                if idx < 0x28A and not flag and not (cat is not None and 4 <= cat <= 6):
                    va = s7.counter_va(idx)
                    cur = struct.unpack('<h', e.read(va, 2))[0]
                    new = min(cur + 1, 0x270F)
                    mu.mem_write(va, struct.pack('<h', new if new >= 0 else 0))
                hp = struct.unpack('<q', e.read(unit + 0x2CC8, 8))[0]
                mu.mem_write(unit + 0x2CC8, struct.pack('<q', max(0, hp - self.dmg)))
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                mu.reg_write(r, POISON)
            return 0x5A5A
        e.stubs[s7.GAME_APPLY] = game_apply

    def make(self, units):
        """units = {stat_index: (ids, counter, hp, char_id)} -> {stat_index: (unit ptr, battle record)}"""
        ptrs = self.prepare({i: (v[0], v[1]) for i, v in units.items()})
        for i, v in units.items():
            ptr = ptrs[i][0]
            self.e.mu.mem_write(ptr + 0x2CC8, struct.pack('<q', v[2]))
            self.e.mu.mem_write(ptr + 0x2E04, struct.pack('<i', v[3]))
        return ptrs


_RIGS = {}


def rigs():
    if 'kit' not in _RIGS:
        import hashlib
        patched = ev.build_patch(ORIGINAL.read_bytes(), {RID: plume_row()})
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='dd2evil3-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _RIGS['kit'] = KRig(tmp / 'kit.exe')
        _RIGS['section'] = (info['code'], info['base'] + len(info['data']))
        _RIGS['sha'] = hashlib.sha256(patched).hexdigest()
        _RIGS['control'] = KRig(ORIGINAL)
    return _RIGS


def writer(abi):
    chk = Checker('writer')
    r = rigs()
    kit, ctl, sect = r['kit'], r['control'], r['section']
    P, N = (RID,), ()
    CHAR = 10

    def hit(rig, units, attacker, target, dmg, *, slot=40, cat=None, flag=0, abi_=False, null_attacker=False):
        ptrs = rig.make(units)
        rig.dmg = dmg
        rig.log.clear()
        ctx = s7.make_ctx(rig.e, slot, cat, idx=2)
        if flag:
            rig.e.mu.mem_write(ctx + 0x276BC, bytes([flag]))
        arec = 0 if null_attacker else ptrs[attacker][1]
        ret = rig.start(s7.SITE_ADD, dict(rcx=arec, rdx=ptrs[target][1], r8=ctx, r9=2), {0x20: 0xABCD0001}, abi_, sect if rig is kit else (0, 0), None)
        hp = {i: struct.unpack('<q', rig.e.read(ptrs[i][0] + 0x2CC8, 8))[0] for i in units}
        return ret, rig.counters(*units), hp, rig.log[:], (arec, ptrs[target][1], ctx)

    def case(label, units, attacker, target, dmg, want, *, want_hp=None, **kw):
        problems = []
        ret, counters, hp, log, (arec, trec, ctx) = hit(kit, units, attacker, target, dmg, abi_=abi, **kw)
        for i, w in want.items():
            if counters[i] != w:
                problems.append(f'slot {i}: counter {counters[i]}, expected {w}')
        if ret != 0x5A5A:
            problems.append(f'the game result was not handed back: {ret:#x}')
        if len(log) != 1 or log[0] != ('apply', (arec, trec, ctx, 2), 0xABCD0001):
            problems.append(f'the game call did not get the site arguments unchanged: {log}')
        if want_hp is not None and hp[target] != want_hp:
            problems.append(f'target HP {hp[target]}, expected {want_hp}')
        report_ctl = hit(ctl, units, attacker, target, dmg, **kw)
        if report_ctl[0] != 0x5A5A:
            problems.append('control exe: result lost')
        chk(label, problems)

    # slots: 1 = Plume (attacker), 2 = victim, 3 = a second Plume, 4 = another unit
    U = lambda ids, ctr, hp=100, char=CHAR: (ids, ctr, hp, char)                   # noqa: E731
    case('Plume kills an enemy: her count 0 -> 1 (D5 also counted the victim, not Plume)',
         {1: U(P, 0), 2: U(N, 0, 30), 3: U(P, 4), 4: U(N, 7)}, 1, 2, 50, {1: 1, 2: 1, 3: 4, 4: 7}, want_hp=0)
    case('a count already 5 -> 6', {1: U(P, 5), 2: U(N, 0, 30)}, 1, 2, 30, {1: 6})
    case('a hit that does not defeat: no count', {1: U(P, 2), 2: U(N, 0, 100)}, 1, 2, 30, {1: 2}, want_hp=70)
    case('a hit that leaves 1 HP: no count', {1: U(P, 2), 2: U(N, 0, 31)}, 1, 2, 30, {1: 2}, want_hp=1)
    case('exactly lethal (HP = damage): counts', {1: U(P, 2), 2: U(N, 0, 30)}, 1, 2, 30, {1: 3}, want_hp=0)
    case('a target already at 0 HP is not defeated by this apply: no count', {1: U(P, 2), 2: U(N, 0, 0)}, 1, 2, 30, {1: 2})
    case('another unit kills: Plume\'s count does not move, the other unit has no count', {1: U(P, 3), 2: U(N, 0, 30), 4: U(N, 0, 100)}, 4, 2, 50,
         {1: 3, 4: 0})
    case('another unit kills the unit a Plume stands beside: no holder count moves', {1: U(P, 3), 3: U(P, 6), 2: U(N, 0, 30), 4: U(N, 9, 100)}, 4, 2, 50,
         {1: 3, 3: 6, 4: 9})
    case('Plume defeats a unit of her own side: counted (D2 has no team test at 0xE9170)', {1: U(P, 0), 2: U(N, 0, 30, 20)}, 1, 2, 50, {1: 1})
    case('two Plumes: the killer counts, the other does not', {1: U(P, 0), 3: U(P, 0), 2: U(N, 0, 30)}, 3, 2, 50, {1: 0, 3: 1})
    case('Plume is hit (not defeated): D5\'s +1 on her is taken back, 4 stays 4', {1: U(P, 4, 100), 2: U(N, 0, 100)}, 2, 1, 20, {1: 4}, want_hp=80)
    case('Plume is defeated: her count stays 4 and the killer gets nothing', {1: U(P, 4, 10), 2: U(N, 3, 100)}, 2, 1, 50, {1: 4, 2: 3}, want_hp=0)
    case('a Plume defeats another Plume: the killer +1, the victim\'s own count stays', {1: U(P, 2, 100), 3: U(P, 5, 10)}, 1, 3, 50, {1: 3, 3: 5})
    case('a non-holder target keeps D5\'s own +1', {1: U(P, 0), 2: U(N, 5, 100)}, 1, 2, 10, {1: 0, 2: 6})
    case('a hit with ctx+0x276BC set: D5 adds nothing and a holder target keeps its count', {1: U(P, 4, 100), 2: U(N, 0, 100)}, 2, 1, 20, {1: 4}, flag=1)
    case('a heal-category action (4) on a holder: unchanged', {1: U(P, 4, 100), 2: U(N, 0, 100)}, 2, 1, 0, {1: 4}, cat=4)
    case('a lethal hit under category 1 counts', {1: U(P, 0), 2: U(N, 0, 10)}, 1, 2, 50, {1: 1}, cat=1)
    case('a Geo Symbol family target (char 4810) is not counted', {1: U(P, 2), 2: U(N, 0, 10, 4810)}, 1, 2, 50, {1: 2})
    case('char 4819 is still the family', {1: U(P, 2), 2: U(N, 0, 10, 4819)}, 1, 2, 50, {1: 2})
    case('char 4809 and 4820 are ordinary units', {1: U(P, 2), 2: U(N, 0, 10, 4809), 4: U(N, 0, 10, 4820)}, 1, 2, 50, {1: 3})
    case('the clamp: a count of 9999 stays 9999', {1: U(P, 9999), 2: U(N, 0, 10)}, 1, 2, 50, {1: 9999})
    case('9998 -> 9999', {1: U(P, 9998), 2: U(N, 0, 10)}, 1, 2, 50, {1: 9999})
    case('a holder in the last stat slot (0x289)', {0x289: U(P, 7), 2: U(N, 0, 10)}, 0x289, 2, 50, {0x289: 8})
    case('no attacker record: nothing is counted, nothing crashes', {1: U(P, 3), 2: U(N, 0, 10)}, 1, 2, 50, {1: 3}, null_attacker=True)
    case('the neighbours are untouched', {1: U(P, 0), 2: U(N, 0, 10), 0: U(P, 11), 3: U(P, 12)}, 1, 2, 50, {0: 11, 1: 1, 3: 12})
    # a holder without a stat record
    ptrs = kit.make({2: (N, 0, 10, CHAR)})
    unit = kit.e.alloc(s7.dunit(P, 0x28A))
    kit.e.mu.mem_write(unit + 0x2CC8, struct.pack('<q', 100))
    arec = kit.e.alloc(kit._brec(unit))
    kit.dmg = 50
    kit.log.clear()
    ctx = s7.make_ctx(kit.e, 40, None, idx=2)
    ret = kit.start(s7.SITE_ADD, dict(rcx=arec, rdx=ptrs[2][1], r8=ctx, r9=2), {0x20: 1}, abi, sect, None)
    chk('a holder without a stat record (index 0x28A): only the game call', [] if ret == 0x5A5A and len(kit.log) == 1 else [hex(ret)])
    ptrs = kit.make({1: (P, 0, 100, CHAR)})
    ctx = s7.make_ctx(kit.e, 40, None, idx=2)
    kit.log.clear()
    ret = kit.start(s7.SITE_ADD, dict(rcx=ptrs[1][1], rdx=0, r8=ctx, r9=2), {0x20: 1}, abi, sect, None)
    chk('a null target record: only the game call', [] if ret == 0x5A5A and len(kit.log) == 1 else [hex(ret)])
    # a run of events through the real site
    ptrs = kit.make({1: U(P, 0), 2: U(N, 0, 10), 3: U(P, 0)})
    kit.dmg = 50
    for att, tgt_hp, dmg in ((1, 10, 50), (3, 10, 50), (1, 100, 5), (1, 10, 50), (3, 10, 50), (3, 100, 20)):
        kit.e.mu.mem_write(ptrs[2][0] + 0x2CC8, struct.pack('<q', tgt_hp))
        kit.dmg = dmg
        ctx = s7.make_ctx(kit.e, 40, None, idx=2)
        kit.start(s7.SITE_ADD, dict(rcx=ptrs[att][1], rdx=ptrs[2][1], r8=ctx, r9=2), {0x20: 1}, abi, sect, None)
    c = kit.counters(1, 2, 3)
    chk('a run: Plume 1 killed twice, Plume 2 twice, two non-lethal hits (the victim\'s D5 count is 6)', [] if (c[1], c[3], c[2]) == (2, 2, 6) else [c])
    return chk


# ------------------------------------------------------------------------------------------------------------------------------ reader
def reader(abi):
    chk = Checker('reader')
    original = ORIGINAL.read_bytes()
    bundle = plume1.build(ev, original, {RID: plume_row()})

    def ally(ids=(), ctr=0, *, team=0, hp=100, idx=1, char=10):
        b = h.unit(ids, team=team, hp=hp, max_hp=100, char_id=char)
        struct.pack_into('<I', b, 0x4348, idx)
        return b, (idx, ctr)

    def region(ctrs):
        out = []
        for idx, ctr in ctrs:
            out.append((s7.counter_va(idx), struct.pack('<h', ctr)))
        return out

    def run(label, want, subject=((), 0), others=(), *, subject_team=0, on_map=True, carried=(), inactive=(), rec=None):
        """subject = (ids, own count) at slot 0, stat index 0; `others` = [(unit bytes, counter spec)] in slots 2.."""
        sub_u = h.unit(subject[0], team=subject_team, hp=100, max_hp=100)
        struct.pack_into('<I', sub_u, 0x4348, 0)
        regions = region([(0, subject[1])] + [spec for _, spec in others])
        base = h.fixture(sub_u, on_map=on_map, other=h.unit(team=1),
                         others=tuple((u, (5, 5 + 1 + i), 2 + i) for i, (u, _) in enumerate(others)), regions=regions)

        def setup(write):
            base(write)
            for i in carried:
                write(h.BATTLE_TABLE + (2 + i) * h.STRIDE + 0x2EE, struct.pack('<h', 7))
            for i in inactive:
                write(h.BATTLE_TABLE + (2 + i) * h.STRIDE + 0x2E8, b'\x00')
        case = dict(name=label, family='power', field='output', expected=want, ids=subject[0], fixture=setup)
        problems = []
        for site, result in plume1.run_case(bundle, case, abi):
            if result['output'] != want:
                problems.append(f'{hex(site)}: {result["output"]}, expected {want}')
        chk(label, problems)

    A = ally
    run('no kills anywhere: 0', 0, others=[A((RID,), 0)])
    run('one holder with 1 kill: +10', 10, others=[A((RID,), 1)])
    run('3 kills: +30', 30, others=[A((RID,), 3)])
    run('19 kills: +190', 190, others=[A((RID,), 19)])
    run('20 kills: +200 (the cap)', 200, others=[A((RID,), 20)])
    run('21 kills: still 200', 200, others=[A((RID,), 21)])
    run('99 kills: 200', 200, others=[A((RID,), 99)])
    run('two holders (2 and 3 kills): +50, one row evaluation', 50, others=[A((RID,), 2), A((RID,), 3, idx=2)])
    run('two holders (15 and 15): the cap is on the sum, 200', 200, others=[A((RID,), 15), A((RID,), 15, idx=2)])
    run('three holders (1, 2, 4)', 70, others=[A((RID,), 1), A((RID,), 2, idx=2), A((RID,), 4, idx=3)])
    run('the recipient\'s own count is not added (recipient 7 kills, holder 2): +20', 20, subject=((), 7), others=[A((RID,), 2)])
    run('a holder recipient gets only the OTHER holder\'s count (own 5, other 3): +30', 30, subject=((RID,), 5), others=[A((RID,), 3)])
    run('a lone holder is not her own ally: 0 (even with a count of 5)', 0, subject=((RID,), 5))
    run('a non-holder ally with +0x5D8 = 9 (D5\'s Impact Charge) adds nothing', 10, others=[A((RID,), 1), A((), 9, idx=2)])
    run('a defeated holder (HP 0) gives nothing', 0, others=[A((RID,), 6, hp=0)])
    run('a defeated holder is skipped, a living one counts', 20, others=[A((RID,), 6, hp=0), A((RID,), 2, idx=2)])
    run('a holder off the map gives nothing', 0, others=[A((RID,), 6)], inactive=(0,))
    run('a carried holder gives nothing', 0, others=[A((RID,), 6)], carried=(0,))
    run('a holder off the map is skipped, a living one counts', 20, others=[A((RID,), 6), A((RID,), 2, idx=2)], inactive=(0,))
    run('a carried holder is skipped, a living one counts', 20, others=[A((RID,), 6), A((RID,), 2, idx=2)], carried=(0,))
    run('an enemy-team holder gives nothing and buffs nobody', 0, others=[A((RID,), 6, team=1)])
    run('an enemy holder next to an allied one: only the ally counts', 20, others=[A((RID,), 6, team=1), A((RID,), 2, idx=2)])
    run('an enemy recipient is not buffed by the allied holder', 0, subject_team=1, others=[A((RID,), 6)])
    run('the recipient off the map: 0', 0, on_map=False, others=[A((RID,), 6)])
    run('a holder with count 0 and one with 4: +40', 40, others=[A((RID,), 0), A((RID,), 4, idx=2)])
    run('a negative stored count is read as unsigned (0xFFFF = 65535): capped at 200', 200, others=[A((RID,), -1)])
    # the row with another cap and another value: the number is the row's, not the asm's
    bundle2 = plume1.build(ev, original, {RID: [dict(plume_row()[0], effects=[{'value': 25, 'per': 'holder_kills', 'max': 60}]), {'family': 'kill_counter'}]})
    for ctr, want in ((2, 50), (3, 60), (9, 60)):
        sub_u = h.unit((), team=0, hp=100, max_hp=100)
        a, spec = A((RID,), ctr)
        fx = h.fixture(sub_u, other=h.unit(team=1), others=((a, (5, 6), 2),), regions=region([(0, 0), spec]))
        case = dict(name='v', family='power', field='output', expected=want, ids=(), fixture=fx)
        problems = [f'{hex(s)}: {r["output"]}' for s, r in plume1.run_case(bundle2, case, abi) if r['output'] != want]
        chk(f'row value 25 cap 60, {ctr} kills: {want}', problems)
    return chk


def wipe(abi):
    chk = Checker('wipe')
    r = rigs()
    kit = r['kit']
    e, X = kit.e, kit.e.X
    ptrs = kit.make({1: ((RID,), 7, 100, 10)})
    va = s7.counter_va(1)
    before = struct.unpack('<h', e.read(va, 2))[0]
    mu = e.mu
    rsp = kit.so.STACK + 0x100000 - 0x400
    mu.mem_write(rsp, struct.pack('<Q', kit.so.RET))
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    mu.reg_write(X.UC_X86_REG_RCX, SR0 + 1 * SR_STRIDE)
    mu.emu_start(WIPE_FN, kit.so.RET, count=200_000)
    after = struct.unpack('<h', e.read(va, 2))[0]
    other = struct.unpack('<h', e.read(s7.counter_va(2), 2))[0]
    chk(f'the game\'s own model_stat_record_wipe takes the count {before} to {after} (neighbour record untouched)', [] if (before, after, other) == (7, 0, 0) else [(before, after, other)])
    return chk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    ap.add_argument('--section', choices=('writer', 'reader', 'wipe'))
    args = ap.parse_args()
    import hashlib
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == ORIGINAL_SHA
    if args.control:
        if args.control == 'hk-cap':
            plume_orig = plume_row
            globals()['plume_row'] = lambda cap=None: plume_orig(255)
            DATA_CHECK = None
        else:
            ev.ASM_FILE = str(mutated_asm(args.control))
    ok = n = 0
    for name, fn in (('writer', writer), ('reader', reader), ('wipe', wipe)):
        if args.section and args.section != name:
            continue
        chk = fn(args.abi)
        ok += chk.ok
        n += chk.n
    print(f"{ok}/{n} {'abi' if args.abi else 'behavior'}")
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
