"""DRPGSIG2 offline proofs, normal and --abi, through the pinned game's real patched sites (Unicorn); control = the pinned original exe.

  majorita  Cheshire Cat Majorita (DRPG leaderskill 3921 + 3925: party ATK / critical damage +18 %, "invincible for 2 hits at battle start"):
            the second-word family `invincible_hits`.
              decision  wrap_nullify at the REAL call sites of damage_nullify_predicate (0x1401BF0F0 compute_target, 0x1401BF6DD heal path;
                        0x14060B657 and 0x1401C0A30 must stay out): nullify a hit with positive damage while the holder's count
                        (stat record +0xDF9) is below N, a lethal one too, and mark it pending in the kit's evil_pend table.  The game's
                        own predicate is a stub whose answer and arguments the proof sets and checks.
              count     wrap_atkcount at the REAL call site 0x1401B1BE0 (damage_apply_damage): +1 only for a pending, nullified, connected
                        hit that is not a buff, never above N, D5's own "+0xDF9 = 1" write of the stubbed apply discarded.
              end to end  compute then apply, with forecasts, misses, buffs, heals and a lethal hit in between.
            The stat half is read from the overlay row (ATK +18 on the holder and on an ally by the aura row), through the real stat site.
  jusoso    Jusoso (DRPG leaderskill 201001 + 201005: party HP / ATK / CRD +20 %, "once per battle, when defeated, revive at full HP"):
            the evility carries an ALIAS to D5's Lich Deimos 145, whose revive is D5's own code (model_update_sweep_units).  Proven here:
            the kit's alias hook (0x14021878C) adds 145 to the holder's list, the game's own has_evility (0x1402068B0) then finds it, and the
            exe's sweep block has the revive shape (evility 0x91 test, the +0x5E4 / +0xDF4 / team tests, HP = maximum, the flags set).
            The revive itself is not run (the sweep needs a battle): live-needed.

<unicorn python> evility/offline_proof_drpgsig2.py [--abi] [--control NAME] [--piece majorita|jusoso]
Controls (a deliberately broken wrapper / alias; the proof must then FAIL): inv-count, inv-v, inv-site, inv-clear, inv-game, inv-holder,
inv-pending, inv-miss, inv-buff, inv-cap, inv-keep, inv-slot, inv-pclear, alias-none, alias-wrong
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
from d5lib.importers import _drpg_text   # noqa: E402  (TEXTHASH-DRPG: JP names are hashes; these proofs read ids, rows and our own wording)
from offline_proof_carriers2 import u, fixture as c2_fixture                     # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_plume1 as plume1                                            # noqa: E402
import offline_proof_d4sig7 as d7                                                # noqa: E402
import offline_proof_ex05e as h                                                  # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/drpgsig2')
OVERLAY = KIT / 'd5lib/importers/drpg-evility-overlay.json'
MAJ, JUS = 28376, 28528                       # main evility ids of base 392 (Cheshire Cat Majorita) and base 20100 (Jusoso)
OTHER, DRAGON, REGEN = 27836, 27663, 121      # face_target_away row, attack_counter row, an ordinary regen row
SR0, STRIDE = d7.SR0, d7.SR_STRIDE
DF9 = 0xDF9
SITE_NULL, SITE_HEAL, SITE_SPEC, SITE_DEAD = 0x1401BF0F0, 0x1401BF6DD, 0x14060B657, 0x1401C0A30
GAME_NULL = 0x1401FE0D0
SITE_ADD = d7.SITE_ADD
NONE = ()


def overlay_evility(base, evid):
    d = _drpg_text.load_authored(OVERLAY)
    return next(e for e in d['bases'][str(base)]['evilities'] if e['id'] == evid)


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        # nullify while the count is below N: the count test is gone (always nullify)
        'inv-count': ("    cmp edx, eax\n    jae .n_noinv                      // all N used\n", ""),
        # a hit without positive damage is also nullified / marked
        'inv-v': ("    cmp qword ptr [rsp + 0xA8], 0     // v: the hit's damage\n    jle .n_noinv\n", ""),
        # every site takes part, not only the two whose hits the apply wrapper sees
        'inv-site': ("    cmp rax, rcx\n    jne .n_noinv\n.n_inv:", ".n_inv:"),
        # a pass that does not nullify leaves the pending mark as it was
        'inv-clear': ("    mov byte ptr [rax + rcx], 0\n    test r14d, r14d\n    jnz .n_noinv", "    test r14d, r14d\n    jnz .n_noinv"),
        # a hit the game nullifies itself still counts against N
        'inv-game': ("    test r14d, r14d\n    jnz .n_noinv                      // the game already nullifies it: nothing of ours is consumed\n", ""),
        # a unit without the row is nullified too
        'inv-holder': ("    call evil_dmg_sum                 // eax = N, 0 for a unit without the row\n    test eax, eax\n    jle .n_noinv\n",
                       "    call evil_dmg_sum\n    mov eax, 2\n"),
        # the count is raised without a pending nullification
        'inv-pending': ("    test r8d, r8d\n    jz .ac_keep                         // no pending nullification: the count stays as it was\n", ""),
        # a miss counts
        'inv-miss': ("    cmp dword ptr [r12 + rcx + 0x1330], 0\n    je .ac_keep                         // a miss\n", ""),
        # a buff counts
        'inv-buff': ("    movzx edx, byte ptr [r8 + 0x3f6]\n    sub edx, 5\n    cmp edx, 1\n    jbe .ac_keep                        // a buff / debuff (category 5, 6)\n", ""),
        # the count goes above N
        'inv-cap': ("    cmp r9d, r10d\n    jae .ac_keep\n", ""),
        # D5's own write of +0xDF9 stays (the holder's value is not stored back)
        'inv-keep': ("    mov byte ptr [rdi], r9b\n.ac_done:", ".ac_done:"),
        # a hit whose damage went through still counts
        'inv-slot': ("    cmp qword ptr [r12 + rcx + 0x1328], 0\n    jne .ac_keep                        // damage went through\n", ""),
        # the pending mark is not cleared by the apply
        'inv-pclear': ("    movzx r8d, byte ptr [rdx + rcx]     // the pending mark\n    mov byte ptr [rdx + rcx], 0\n",
                       "    movzx r8d, byte ptr [rdx + rcx]     // the pending mark\n"),
    }
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f'd5evil-drpgsig2-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def df9_va(idx):
    return SR0 + idx * STRIDE + DF9


class MajRig(d7.DragonRig):
    """the pinned exe (or the kit build) under Unicorn; the game's damage_nullify_predicate, damage_apply_damage and post_hit_effects are stubs"""

    def __init__(self, exe, pend_va=None):
        super().__init__(exe)
        from unicorn import UC_HOOK_CODE
        e, X = self.e, self.e.X
        self.pend_va = pend_va
        self._pend = {}
        self.game_null = 0
        self.nlog = []

        def game_null():
            mu = e.mu
            rsp = mu.reg_read(X.UC_X86_REG_RSP)
            args = tuple(mu.reg_read(r) for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9))
            fifth, sixth = struct.unpack('<QQ', e.read(rsp + 0x28, 16))
            self.nlog.append((args, fifth, sixth))
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                mu.reg_write(r, d7.POISON)
            return self.game_null | 0x5A00                        # junk above al: the wrapper must hand back al only (or all of eax)
        base_apply = e.stubs[d7.GAME_APPLY]

        def game_apply():
            mu = e.mu
            target = mu.reg_read(X.UC_X86_REG_RDX)
            unit = struct.unpack('<Q', e.read(target + 0x240, 8))[0]
            if unit:
                idx = struct.unpack('<I', e.read(unit + 0x4348, 4))[0]
                if idx < 0x28A:
                    mu.mem_write(df9_va(idx), b'\x01')              # D5's own "took damage" write, whatever the hit was
            return base_apply()
        e.stubs[GAME_NULL], e.stubs[d7.GAME_APPLY] = game_null, game_apply
        e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=GAME_NULL, end=GAME_NULL)
        self.d5_inc = 0

    def pend(self, idx):
        if self.pend_va is None:                           # the pinned exe has no kit section: a plain table the exe never touches
            return self._pend.get(idx, 0)
        return self.e.read(self.pend_va + idx, 1)[0]

    def set_pend(self, idx, v):
        if self.pend_va is None:
            self._pend[idx] = v
            return
        self.e.mu.mem_write(self.pend_va + idx, bytes([v]))

    def df9(self, idx):
        return self.e.read(df9_va(idx), 1)[0]

    def set_df9(self, idx, v):
        self.e.mu.mem_write(df9_va(idx), bytes([v]))


_K = {}


def rows_for_kit():
    ev_ = overlay_evility(392, MAJ)
    assert ev_['rows'][-1] == {'family': 'invincible_hits', 'effects': [{'value': 2}]}, ev_['rows']
    return {MAJ: ev_['rows'], OTHER: {'family': 'face_target_away'}, DRAGON: {'family': 'attack_counter'},
            REGEN: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 1}]},
            5000: {'family': 'invincible_hits', 'effects': [{'value': 5}]}, 5001: {'family': 'nullify'}}


def kit_rigs():
    if 'kit' not in _K:
        patched = ev.build_patch(ORIGINAL.read_bytes(), rows_for_kit())
        info = ev.section_info(patched)
        at = info['data'].find(struct.pack('<Q', ev.EVIL_PEND_MAGIC))
        assert at >= 0, 'evil_pend magic not in the section'
        pend_va = info['base'] + at + 8
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='drpgsig2-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _K['kit'] = (MajRig(tmp / 'kit.exe', pend_va), (info['code'], info['base'] + len(info['data'])), hashlib.sha256(patched).hexdigest())
        _K['control'] = MajRig(ORIGINAL, None)
    return _K['kit'], _K['control']


def make_ctx2(e, slot_value, hit_code, category, idx=2):
    """an action context: target `idx` has result slot +0x1328, hit code +0x1330; the skill row (category byte +0x3F6), None = a normal attack"""
    ctx = bytearray(0x27700)
    struct.pack_into('<q', ctx, idx * 0x260 + 0x1328, slot_value)
    struct.pack_into('<i', ctx, idx * 0x260 + 0x1330, hit_code)
    if category is not None:
        row = e.alloc(bytes(0x3F6) + bytes([category]) + bytes(9))
        struct.pack_into('<Q', ctx, 0x27678, row)
    return e.alloc(ctx)


def majorita_section(abi, section_report):
    (kit, section, sha), control = kit_rigs()
    ok = n = 0

    def report(name, problems):
        nonlocal ok, n
        n += 1
        ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + 'majorita: ' + name + ('' if not problems else ': ' + '; '.join(problems)))

    MJ, FIVE, DR = (MAJ,), (5000,), (DRAGON,)
    IDX = 3
    NB = (7, 1)                                 # the neighbours' DF9 bytes: idx - 1 and idx + 1 (the latter a holder too)

    # ---------------------------------------------------------------- the decision (wrap_nullify at the real call sites)
    def null(rig, ids, count, v, site=SITE_NULL, game=0, pend_pre=0, hp=None, abi_=False, idx=IDX):
        ptrs = rig.prepare({idx: (ids, 0), idx - 1: (NONE, 0), idx + 1: (MJ, 0)})
        rig.set_df9(idx, count)
        rig.set_df9(idx - 1, NB[0])
        rig.set_df9(idx + 1, NB[1])
        rig.set_pend(idx, pend_pre)
        rig.set_pend(idx - 1, 1)
        rig.set_pend(idx + 1, 1)
        if hp is not None:
            rig.e.mu.mem_write(ptrs[idx][0] + 0x2cc8, struct.pack('<q', hp))
        rig.game_null = game
        rig.nlog.clear()
        attacker = rig.e.alloc(rig._brec(0x1234))
        ret = rig.start(site, dict(rcx=attacker, rdx=ptrs[idx][1], r8=0x7777, r9=0xC7C7), {0x20: 3, 0x28: v & 0xFFFFFFFFFFFFFFFF}, abi_, section, None)
        return ret, (attacker, ptrs[idx][1]), idx

    cases = [
        # (name, ids, count, v, site, game answer, pending before, expected answer, expected pending, expected count, hp)
        ('N=2, count 0: a hit with damage is nullified and marked pending', MJ, 0, 120, SITE_NULL, 0, 0, 1, 1, 0, None),
        ('count 1 (< 2): still nullified', MJ, 1, 120, SITE_NULL, 0, 0, 1, 1, 1, None),
        ('count 2 (= N): the game answers no, so does the kit; the mark stays clear', MJ, 2, 120, SITE_NULL, 0, 0, 0, 0, 2, None),
        ('count 200 (corrupt): no', MJ, 200, 120, SITE_NULL, 0, 0, 0, 0, 200, None),
        ('a lethal hit is nullified too (damage 9999, hp 10)', MJ, 0, 9999, SITE_NULL, 0, 0, 1, 1, 0, 10),
        ('damage 1 counts as a hit', MJ, 0, 1, SITE_NULL, 0, 0, 1, 1, 0, None),
        ('damage 0: nothing to nullify, no mark', MJ, 0, 0, SITE_NULL, 0, 0, 0, 0, 0, None),
        ('negative damage (a heal sign): no', MJ, 0, -5, SITE_NULL, 0, 0, 0, 0, 0, None),
        ('a stale mark is cleared when nothing is nullified (damage 0)', MJ, 0, 0, SITE_NULL, 0, 1, 0, 0, 0, None),
        ('a stale mark is cleared once all N are used', MJ, 2, 50, SITE_NULL, 0, 1, 0, 0, 2, None),
        ('the game already nullifies (First Impression, ...): answer yes, NO mark, stale mark cleared', MJ, 0, 80, SITE_NULL, 1, 1, 1, 0, 0, None),
        ('a unit without the row: the game answers no, the kit answers no, a stale mark is cleared', NONE, 0, 80, SITE_NULL, 0, 1, 0, 0, 0, None),
        ('a unit without the row, game yes: yes', NONE, 0, 80, SITE_NULL, 1, 0, 1, 0, 0, None),
        ('a second-word row of another family is not a holder', (OTHER,), 0, 80, SITE_NULL, 0, 0, 0, 0, 0, None),
        ('the damaging-heal path (0x1401BF6DD) takes part', MJ, 0, 80, SITE_HEAL, 0, 0, 1, 1, 0, None),
        ('the special-skill executors (0x14060B657) stay out: no decision, mark cleared', MJ, 0, 80, SITE_SPEC, 0, 1, 0, 0, 0, None),
        ('the dead function FUN_1401C0A10 (0x1401C0A30) stays out', MJ, 0, 80, SITE_DEAD, 0, 1, 0, 0, 0, None),
        ('N=5 (another row): count 4 nullified', FIVE, 4, 80, SITE_NULL, 0, 0, 1, 1, 4, None),
        ('N=5: count 5 not', FIVE, 5, 80, SITE_NULL, 0, 0, 0, 0, 5, None),
        ('the row among other learned ids', (5, 9, MAJ, 40000), 1, 80, SITE_NULL, 0, 0, 1, 1, 1, None),
        ('an ordinary nullify row of this runtime still answers yes (no invincible row)', (5001,), 0, 80, SITE_NULL, 0, 0, 1, 0, 0, None),
    ]
    for name, ids, count, v, site, game, pend_pre, want, want_pend, want_count, hp in cases:
        problems = []
        ret, (attacker, brec), idx = null(kit, ids, count, v, site, game, pend_pre, hp, abi_=abi)
        if ret & 0xFF != want:
            problems.append(f'answer {ret & 0xFF}, expected {want}')
        if kit.pend(idx) != want_pend:
            problems.append(f'pending {kit.pend(idx)}, expected {want_pend}')
        if kit.df9(idx) != count:
            problems.append(f'the decision changed the count to {kit.df9(idx)}')
        if kit.pend(idx - 1) != 1 or kit.pend(idx + 1) != 1 or kit.df9(idx - 1) != NB[0] or kit.df9(idx + 1) != NB[1]:
            problems.append('a neighbouring mark or count moved')
        want_args = ((attacker, brec, 0x7777, 0xC7C7), 3, v & 0xFFFFFFFFFFFFFFFF)
        if kit.nlog != [want_args]:
            problems.append(f'the game predicate did not get the site arguments unchanged: {kit.nlog}')
        report(name, problems)
        # control: the pinned exe answers what the stub says and writes no mark
        cret, _, _ = null(control, ids, count, v, site, game, pend_pre, hp)
        if cret & 0xFF != game or control.pend(idx) != pend_pre or control.df9(idx) != count:
            report(name + ' [control exe]', [f'answer {cret & 0xFF}, pend {control.pend(idx)}, count {control.df9(idx)}'])
    # no unit / no stat record / no defender record
    for name, make in (
            ('a defender record without a unit record: only the game call', lambda rig: rig.e.alloc(bytes(d7.BREC_STRIDE))),
            ('a null defender record: only the game call', lambda rig: 0),
            ('a holder without a stat record (index 0x28A): only the game call',
             lambda rig: rig.e.alloc(rig._brec(rig.e.alloc(d7.dunit(MJ, 0x28A)))))):
        kit.prepare({})
        kit.nlog.clear()
        kit.game_null = 0
        brec = make(kit)
        ret = kit.start(SITE_NULL, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=brec, r8=1, r9=2), {0x20: 3, 0x28: 50}, abi, section, None)
        report(name, [] if ret & 0xFF == 0 and len(kit.nlog) == 1 else [f'{ret:#x} {kit.nlog}'])
    # forecasts: the same read, any number of times, never moves the count
    ptrs = kit.prepare({IDX: (MJ, 0)})
    kit.set_df9(IDX, 0)
    seen = []
    for _ in range(5):
        ret = kit.start(SITE_NULL, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=ptrs[IDX][1], r8=1, r9=2), {0x20: 3, 0x28: 99}, abi, section, None)
        seen.append(ret & 0xFF)
    report('five forecasts: always yes, the count stays 0', [] if seen == [1] * 5 and kit.df9(IDX) == 0 else [f'{seen} count {kit.df9(IDX)}'])

    # ---------------------------------------------------------------- the count (wrap_atkcount at the real apply call)
    def apply(rig, ids, pre, pend_pre, slot, hit, cat, abi_=False, idx=IDX, d5_inc=0):
        ptrs = rig.prepare({idx: (ids, 0), idx - 1: (NONE, 0), idx + 1: (MJ, 0)})
        rig.d5_inc = d5_inc
        rig.set_df9(idx, pre)
        rig.set_df9(idx - 1, NB[0])
        rig.set_df9(idx + 1, NB[1])
        rig.set_pend(idx, pend_pre)
        rig.set_pend(idx - 1, 1)
        rig.set_pend(idx + 1, 1)
        rig.log.clear()
        ctx = make_ctx2(rig.e, slot, hit, cat, idx=2)
        attacker = rig.e.alloc(rig._brec(0x1234))
        ret = rig.start(SITE_ADD, dict(rcx=attacker, rdx=ptrs[idx][1], r8=ctx, r9=2), {0x20: 0xABCD0001}, abi_, section, None)
        return ret, (attacker, ptrs[idx][1], ctx), idx

    acases = [
        # (name, ids, count before, pending, slot, hit code, category, expected count, expected pending after)
        ('a pending, nullified, connected hit: count 0 -> 1 (D5 wrote 1 as well: not a second +1)', MJ, 0, 1, 0, 1, None, 1, 0),
        ('count 1 -> 2 (D5 wrote 1: the holder value, not 1, is stored)', MJ, 1, 1, 0, 2, None, 2, 0),
        ('count 2 = N: no rise, D5\'s own write is taken back', MJ, 2, 1, 0, 1, None, 2, 0),
        ('count 5 (above N from a stale value): kept as it was', MJ, 5, 1, 0, 1, None, 5, 0),
        ('not pending (the rule did not nullify it): count kept, D5\'s write taken back (0 -> 0)', MJ, 0, 0, 120, 1, None, 0, 0),
        ('not pending, count 2 stays 2', MJ, 2, 0, 120, 1, None, 2, 0),
        ('pending but the damage went through (slot 120): no count', MJ, 0, 1, 120, 1, None, 0, 0),
        ('no mark, slot 0, connected, a damage skill (a zero-damage hit the rule did not nullify): no count', MJ, 0, 0, 0, 1, 1, 0, 0),
        ('pending but a miss (hit code 0): no count', MJ, 1, 1, 0, 0, None, 1, 0),
        ('pending, a buff (category 5): no count', MJ, 1, 1, 0, 1, 5, 1, 0),
        ('pending, a debuff (category 6): no count', MJ, 1, 1, 0, 1, 6, 1, 0),
        ('pending, damage skill category 1: counts', MJ, 0, 1, 0, 1, 1, 1, 0),
        ('pending, category 2: counts', MJ, 0, 1, 0, 2, 2, 1, 0),
        ('pending, category 4 (a damaging heal that was nullified, slot 0): counts', MJ, 0, 1, 0, 1, 4, 1, 0),
        ('pending, no result for the target (slot -1): no count', MJ, 0, 1, -1, 1, None, 0, 0),
        ('N=5 row: count 4 -> 5', FIVE, 4, 1, 0, 1, None, 5, 0),
        ('N=5 row: count 5 stays', FIVE, 5, 1, 0, 1, None, 5, 0),
        ('a unit without the row: D5\'s own write (+0xDF9 = 1) stands, the pending byte is left alone', NONE, 0, 1, 0, 1, None, 1, 1),
        ('a unit with another second-word row: D5\'s write stands', (OTHER,), 0, 0, 120, 1, None, 1, 0),
    ]
    for name, ids, pre, pend_pre, slot, hit, cat, want, want_pend in acases:
        problems = []
        ret, (attacker, tbrec, ctx), idx = apply(kit, ids, pre, pend_pre, slot, hit, cat, abi_=abi)
        if kit.df9(idx) != want:
            problems.append(f'count {kit.df9(idx)}, expected {want}')
        if kit.pend(idx) != want_pend:
            problems.append(f'pending {kit.pend(idx)}, expected {want_pend}')
        if kit.pend(idx - 1) != 1 or kit.pend(idx + 1) != 1 or kit.df9(idx - 1) != NB[0] or kit.df9(idx + 1) != NB[1]:
            problems.append('a neighbouring mark or count moved')
        if ret != 0x5A5A:
            problems.append(f'the game result was not handed back: {ret:#x}')
        if len(kit.log) != 1 or kit.log[0] != ('apply', (attacker, tbrec, ctx, 2), 0xABCD0001):
            problems.append(f'the game call did not get the site arguments unchanged: {kit.log}')
        report(name, problems)
    # D5's own +0x5D8 count and the Dragon counter are not disturbed by this row
    problems = []
    ret, _, idx = apply(kit, (DRAGON, MAJ), 0, 1, 0, 1, None, abi_=abi, d5_inc=1)
    dragon = kit.counters(IDX)[IDX]
    if kit.df9(idx) != 1 or dragon != 1:
        problems.append(f'both rows on one unit: count {kit.df9(idx)} (1), dragon counter {dragon} (1)')
    report('a unit with attack_counter AND invincible_hits: both rows work, independently', problems)
    # control exe: D5's own write only
    cret, _, cidx = apply(control, MJ, 0, 1, 0, 1, None)
    report('control exe (pinned): D5\'s own write (+0xDF9 = 1) only, the mark untouched',
           [] if control.df9(cidx) == 1 and control.pend(cidx) == 1 and cret == 0x5A5A else [f'{control.df9(cidx)} {control.pend(cidx)}'])
    # the last stat slot
    ret, _, idx = apply(kit, MJ, 0, 1, 0, 1, None, abi_=abi, idx=0x289 - 1)
    report('the holder in a high stat slot', [] if kit.df9(idx) == 1 else [str(kit.df9(idx))])
    # no unit / no stat record
    for name, make in (
            ('a target record without a unit record: only the game call', lambda rig: rig.e.alloc(bytes(d7.BREC_STRIDE))),
            ('a holder without a stat record (index 0x28A): only the game call',
             lambda rig: rig.e.alloc(rig._brec(rig.e.alloc(d7.dunit(MJ, 0x28A)))))):
        kit.prepare({})
        kit.log.clear()
        ctx = make_ctx2(kit.e, 0, 1, None)
        ret = kit.start(SITE_ADD, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=make(kit), r8=ctx, r9=2), {0x20: 1}, abi, section, None)
        report(name, [] if ret == 0x5A5A and len(kit.log) == 1 else [f'{ret:#x} {kit.log}'])

    # ---------------------------------------------------------------- end to end: compute (decision) then apply (count)
    def hit(rig, idx, damage, *, connected=True, cat=None, forecast_first=False, compute=True, abi_=abi):
        """one action on the holder: forecasts and the real compute through the nullify site, then the real apply; returns (nullified, count)"""
        e = rig.e
        brec = ptrs_[idx][1]
        attacker = e.alloc(rig._brec(0x1234))
        answers = []
        if forecast_first:
            rig.start(SITE_NULL, dict(rcx=attacker, rdx=brec, r8=1, r9=2), {0x20: 3, 0x28: damage}, abi_, section, None)
        if compute and connected and cat not in (4, 5, 6):
            rig.game_null = 0
            ret = rig.start(SITE_NULL, dict(rcx=attacker, rdx=brec, r8=1, r9=2), {0x20: 3, 0x28: damage}, abi_, section, None)
            answers.append(ret & 0xFF)
        nullified = bool(answers and answers[0])
        slot = 0 if (nullified or not connected or cat in (5, 6)) else damage
        ctx = make_ctx2(e, slot, 1 if connected else 0, cat, idx=2)
        rig.start(SITE_ADD, dict(rcx=attacker, rdx=brec, r8=ctx, r9=2), {0x20: 1}, abi_, section, None)
        return nullified, rig.df9(idx)
    ptrs_ = kit.prepare({IDX: (MJ, 0)})
    kit.set_df9(IDX, 0)
    kit.set_pend(IDX, 0)
    seq = [hit(kit, IDX, 100)]
    seq.append(hit(kit, IDX, 100, forecast_first=True))                      # a forecast first: still one count
    seq.append(hit(kit, IDX, 100, forecast_first=True))                      # the third hit goes through
    seq.append(hit(kit, IDX, 100))
    report('N=2: hit, hit, hit, hit -> nullified, nullified, through, through; count 1 2 2 2',
           [] if seq == [(True, 1), (True, 2), (False, 2), (False, 2)] else [str(seq)])
    ptrs_ = kit.prepare({IDX: (MJ, 0)})
    kit.set_df9(IDX, 0)
    seq = [hit(kit, IDX, 100, connected=False),                               # a miss: nothing
           hit(kit, IDX, 0, cat=5),                                           # a buff: nothing
           hit(kit, IDX, 80, cat=6),                                          # a debuff: nothing
           hit(kit, IDX, 100, forecast_first=True, connected=False),          # a forecast, then a miss: the stale mark is not a hit
           hit(kit, IDX, 100, cat=4, compute=False)]                          # a normal heal (slot > 0, no predicate): nothing
    report('a miss, a buff, a debuff, a forecast then a miss, a heal: the count stays 0 and the next real hit is still nullified',
           [] if [c for _, c in seq] == [0, 0, 0, 0, 0] else [str(seq)])
    zero = hit(kit, IDX, 0)
    report('a connected skill with zero damage (v = 0): not a hit, nothing consumed', [] if zero == (False, 0) else [str(zero)])
    last = hit(kit, IDX, 100)
    report('...and the next real hit is nullified (count 1)', [] if last == (True, 1) else [str(last)])
    last = hit(kit, IDX, 9999)
    report('a lethal hit (9999) while one use is left: nullified (count 2), then the next one goes through',
           [] if last == (True, 2) and hit(kit, IDX, 50) == (False, 2) else [str(last)])
    # the brief of the follow-up: ordinary special skills and spells reach the real apply through compute_target (start_skill_action 0x1405434D0
    # line 188, start_basic_attack 0x140544580 line 979); a damage skill of category 2 and 3 (not a buff) hits, is nullified and counted
    ptrs_ = kit.prepare({IDX: (MJ, 0)})
    kit.set_df9(IDX, 0)
    sp = [hit(kit, IDX, 300, cat=2), hit(kit, IDX, 300, cat=3), hit(kit, IDX, 300, cat=3)]
    report('special-skill / spell hits (skill category 2, 3): nullified and counted through the real apply, the third goes through',
           [] if sp == [(True, 1), (True, 2), (False, 2)] else [str(sp)])
    # a second unit with the same row has its own count
    ptrs_ = kit.prepare({IDX: (MJ, 0), IDX + 5: (MJ, 0)})
    hit(kit, IDX, 100)
    r1 = hit(kit, IDX + 5, 100)
    report('two holders keep separate counts', [] if kit.df9(IDX) == 1 and r1 == (True, 1) else [f'{kit.df9(IDX)} {r1}'])
    section_report.append(('majorita-behaviour', ok, n))
    return ok, n, sha


def majorita_stat_half(abi):
    """ATK +18 on the holder (own row) and on an ally (aura row) through the real stat site; the crit damage rows are DRPGEVIL1b's family"""
    original = ORIGINAL.read_bytes()
    rows = {MAJ: overlay_evility(392, MAJ)['rows']}
    bundle = plume1.build(ev, original, rows)
    atk = lambda n: [0, 0, n] + [0] * 15                                         # noqa: E731  aggregate order: HP SP ATK DEF INT RES HIT SPD ...
    hu, hf = h.unit, h.fixture
    plans = [
        ('stat half: the holder gets ATK +18 from its own row', (MAJ,), hf(hu((MAJ,))), atk(18)),
        ('stat half: an ally within the aura gets ATK +18', (), hf(hu(()), others=((hu((MAJ,)), (5, 9), 2),)), atk(18)),
        ('stat half: an ally with no holder on the map gets nothing', (), hf(hu(())), atk(0)),
        ('stat half: an enemy-team unit gets nothing', (), hf(hu(()), others=((hu((MAJ,), team=1), (5, 9), 2),)), atk(0)),
    ]
    out = []
    for name, ids, fx, expected in plans:
        case = dict(name=name, family='stats', field='aggregate', expected=expected, fixture=fx, ids=ids)
        for site, result in plume1.run_case(bundle, case, abi):
            got = result['aggregate']
            assert got == expected, (name, hex(site), got, expected)
            out.append(dict(name=name, site=hex(site), ok=True))
        print('ok   majorita: ' + name)
    return out


# ------------------------------------------------------------------------------------------------------------------------- jusoso
def jusoso_section(abi, control_name, section_report):
    import capstone
    import pefile
    from unicorn import UC_HOOK_CODE
    import stat_oracle as so
    ok = n = 0

    def report(name, problems):
        nonlocal ok, n
        n += 1
        ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + 'jusoso: ' + name + ('' if not problems else ': ' + '; '.join(problems)))

    e_ = overlay_evility(20100, JUS)
    row = e_['skill_row']
    assert e_['alias'] == 145 and row['id'] == JUS and e_['rows'][-1]['family'] == ['crit_damage', 'aura'], e_
    aliases = {JUS: 145}
    if control_name == 'alias-none':
        aliases = {}
    elif control_name == 'alias-wrong':
        aliases = {JUS: 146}
    from d5lib import newclasses as nc
    src = nc._evility_src(aliases)
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    HOOK = 0x148100000                       # scratch address outside the exe image's own code
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_64).asm(src, HOOK)[0])
    rig = so.Emu(exe_path=ORIGINAL)
    mu, X = rig.mu, rig.X
    mu.mem_map(HOOK, 0x2000)
    mu.mem_write(HOOK, code)
    RET = nc.EVI_RET

    def run_hook(ids):
        unit = bytearray(0x4800)
        struct.pack_into('<i', unit, 0x3030, len(ids))
        for i, v in enumerate(ids):
            struct.pack_into('<I', unit, 0x2F30 + 4 * i, v)
        ptr = rig.alloc(bytes(unit))
        rsp = so.STACK + 0x100000 - 0x400
        mu.reg_write(X.UC_X86_REG_RSP, rsp)
        mu.reg_write(X.UC_X86_REG_RDI, ptr)
        mu.mem_write(rsp, struct.pack('<Q', so.RET))
        hooks = []
        hit = []

        def stop(uc, addr, size, _):
            hit.append(addr)
            uc.emu_stop()
        hooks.append(mu.hook_add(UC_HOOK_CODE, stop, begin=RET, end=RET))
        try:
            mu.emu_start(HOOK, so.RET, count=2_000_000)
        finally:
            for h in hooks:
                mu.hook_del(h)
        assert hit == [RET], f'the alias hook did not reach the exe code after it: {hit}'
        cnt = struct.unpack('<i', rig.read(ptr + 0x3030, 4))[0]
        lst = list(struct.unpack('<%dI' % cnt, rig.read(ptr + 0x2F30, 4 * cnt)))
        return ptr, cnt, lst

    def has_evility(ptr, cnt, lst, evid):
        """the game's own has_evility (0x1402068B0) on a list sorted the way the game sorts it right after the hook"""
        mu.mem_write(ptr + 0x2F30, struct.pack('<%dI' % cnt, *sorted(lst)))
        rsp = so.STACK + 0x100000 - 0x400
        mu.reg_write(X.UC_X86_REG_RSP, rsp)
        mu.mem_write(rsp, struct.pack('<Q', so.RET))
        mu.reg_write(X.UC_X86_REG_RCX, ptr)
        mu.reg_write(X.UC_X86_REG_RDX, evid)
        mu.emu_start(0x1402068B0, so.RET, count=2_000_000)
        return mu.reg_read(X.UC_X86_REG_RAX) & 0xFF

    ptr, cnt, lst = run_hook([5, 77, JUS, 40000])
    report('the alias hook adds 145 to the list of the holder of 28528 (4 -> 5 ids)',
           [] if (145 in lst and cnt == 5 and set(lst) == {5, 77, JUS, 40000, 145}) else [f'{cnt} {lst}'])
    report('the game\'s own has_evility(unit, 145) finds it', [] if has_evility(ptr, cnt, lst, 145) == 1 else ['not found'])
    ptr2, cnt2, lst2 = run_hook([5, 77, 40000])
    report('a unit that does not hold 28528 gets nothing (has_evility 145 = 0)',
           [] if (cnt2 == 3 and has_evility(ptr2, cnt2, lst2, 145) == 0) else [f'{cnt2} {lst2}'])
    ptr3, cnt3, lst3 = run_hook([JUS])
    report('a holder with nothing else: the list is [28528, 145]', [] if (cnt3 == 2 and set(lst3) == {JUS, 145}) else [str(lst3)])
    full = [1000 + i for i in range(0x3F)] + [JUS]
    ptr4, cnt4, lst4 = run_hook(full)
    report('a full list (64 ids): nothing is added (the hook\'s limit)', [] if cnt4 == 0x40 and 145 not in lst4 else [f'{cnt4}'])

    # the revive shape of the game's own sweep (static decode of the pinned exe)
    pe = pefile.PE(data=ORIGINAL.read_bytes(), fast_load=True)
    start, size = 0x1404A8D10, 0
    idx = Path('/Volumes/Data/Decomp/d5/index.tsv')
    if idx.exists():
        for line in idx.read_text().splitlines():
            p = line.split('\t')
            if p[0] == '0x1404a8d10':
                size = int(p[2])
    size = size or 0x1700
    data = pe.get_data(start - 0x140000000, size)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    ins = list(md.disasm(data, start))
    txt = [f'{i.mnemonic} {i.op_str}' for i in ins]
    cmp91 = [i for i in ins if i.mnemonic == 'cmp' and i.op_str.endswith(', 0x91')]
    revive = [k for k in range(1, len(ins)) if ins[k].mnemonic == 'mov' and '+ 0x2cc8]' in ins[k].op_str and ins[k].op_str.endswith(', rax')
              and ins[k - 1].mnemonic == 'mov' and ins[k - 1].op_str.startswith('rax, qword ptr [') and '+ 0x2cd8]' in ins[k - 1].op_str]
    team = [i for i in ins if i.mnemonic == 'cmp' and '+ 0x2e32]' in i.op_str and i.op_str.endswith(', 0')]
    report('the sweep tests the unit\'s evility list for id 0x91 (145): one binary search, `cmp ..., 0x91`',
           [] if len(cmp91) == 1 else [f'{len(cmp91)} compares with 0x91'])
    report('the sweep sets HP (+0x2CC8) to the maximum (+0x2CD8) in one `mov rax, [x + 0x2cd8]; mov [x + 0x2cc8], rax`',
           [] if len(revive) == 1 else [f'{len(revive)} such pairs'])
    report('the sweep tests the unit\'s team byte (+0x2E32) against 0 (the player side)', [] if team else ['no team test'])
    follow = ins[revive[0] + 1: revive[0] + 4] if revive else []
    report('after the HP copy the sweep stores 1 into three flag bytes (once per stage)',
           [] if sum(1 for i in follow if i.mnemonic == 'mov' and 'byte ptr' in i.op_str and i.op_str.endswith(', 1')) == 2 else [str([f'{i.mnemonic} {i.op_str}' for i in follow])])
    section_report.append(('jusoso', ok, n))
    return ok, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    ap.add_argument('--piece', action='append', choices=['majorita', 'jusoso'])
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == ORIGINAL_SHA
    if args.control and args.control.startswith('inv-'):
        ev.ASM_FILE = str(mutated_asm(args.control))
    pieces = args.piece or ['majorita', 'jusoso']
    section_report = []
    total_ok = total = 0
    sha = ''
    if 'majorita' in pieces:
        ok, n, sha = majorita_section(args.abi, section_report)
        stat = majorita_stat_half(args.abi)
        total_ok += ok + len(stat)
        total += n + len(stat)
        if ok != n:
            print(f'majorita: {ok}/{n} checks passed')
            return 1
    if 'jusoso' in pieces:
        ok, n = jusoso_section(args.abi, args.control, section_report)
        total_ok += ok
        total += n
        if ok != n:
            print(f'jusoso: {ok}/{n} checks passed')
            return 1
    report = dict(mode='abi' if args.abi else 'behavior', patched_sha256=sha, passed=total_ok == total, sections=section_report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f"{total_ok}/{total} checks passed (DRPGSIG2 {'+'.join(pieces)}, {'abi' if args.abi else 'behavior'}; patched exe {sha[:16]})")
    return 0 if total_ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
