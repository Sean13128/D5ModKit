"""D4SIG7 offline proofs, one section per piece, through the pinned game's real patched sites (Unicorn), normal and --abi.

  psylos   scale geo_colours (27) and Psylos's row 27129 (D4 129 Geo Energy): the real stat site unit_stats_evil_status_effects
           (0x1401B9575) with a 256-entry battle table holding Geo Symbol units of chosen colours, alive and dead, on and off the map.
           The row is read verbatim from d5lib/importers/d4-evility-overlay.json, so proof and pack cannot drift.

  dragon   D4 Rising Dragon 663: the second-word family attack_counter.  wrap_atkcount at the REAL call site 0x1401B1BE0 (the call of
           damage_apply_damage in FUN_1401B1BA0) and the reset in wrap_face_away at the REAL call site 0x14053FE71 (post_hit_effects in
           exec_ctl_s2_update), both through Unicorn on the kit build and, as control, on the pinned original exe.  The game's own
           damage_apply_damage is a stub that counts like D5 does (+1 on the target's stat record +0x5D8 for a non-elemental attack) so
           that the wrapper's overwrite is visible.  The row is read verbatim from the overlay.

D5Modkit/.venv-macos/bin/python evility/offline_proof_d4sig7.py [--abi] [--control NAME] [--piece psylos|dragon|roc]
Controls (a deliberately broken scale or wrapper; the proof must then FAIL): geo-dead, geo-active, geo-family, geo-distinct,
geo-carried, geo-colour; dragon-heal, dragon-miss, dragon-cap, dragon-keep, dragon-holder, dragon-reset, dragon-slot
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'evility'), str(KIT / 'tools')]
from d5lib import evility as ev                                                  # noqa: E402
from offline_proof_carriers2 import u, fixture as c2_fixture                     # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_plume1 as plume1                                            # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig7')
OVERLAY = KIT / 'd5lib/importers/d4-evility-overlay.json'
PSYLOS = 27129
PSYLOS_CHAR = 18290


def overlay_row(pack, evid):
    mods = json.loads(OVERLAY.read_text())['mods']
    return mods[pack]['behaviors']['evilities'][str(evid)]


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        # a destroyed symbol must not count
        'geo-dead': ("    cmp qword ptr [rdi + 0x2cc8], 0\n    jle .sc_geo_next                  // destroyed\n", ""),
        # a symbol that is not on the map must not count
        'geo-active': ("    cmp byte ptr [r9 + 0x2e8], 0\n    je .sc_geo_next                   // not on the map\n", ""),
        # any unit counts, not only the Geo Symbol family
        'geo-family': ("    cmp ecx, 9\n    ja .sc_geo_next                   // not a Geo Symbol family unit\n", ""),
        # every symbol counts, not distinct colours
        'geo-distinct': ("    bts qword ptr [rsp + 0x38], rcx   // a new colour: CF = 0\n    jc .sc_geo_next\n",
                         "    bts qword ptr [rsp + 0x38], rcx\n"),
        # a carried holder still counts
        'geo-carried': ("    cmp word ptr [rax + 0x2ee], 0\n    jge .sc_geo_zero                  // the holder is carried: 0\n", ""),
        # Dragon: a heal counts
        'dragon-heal': ("    cmp byte ptr [r8 + 0x3f6], 4\n    je .ac_store                        // a heal\n", ""),
        # Dragon: only a result slot above 0 counts (a miss and a buff stop counting)
        'dragon-miss': ("    cmp qword ptr [r12 + rcx + 0x1328], 0\n    jl .ac_store                        // no result for this target\n",
                        "    cmp qword ptr [r12 + rcx + 0x1328], 1\n    jl .ac_store\n"),
        # Dragon: the cap is not 20
        'dragon-cap': ("    cmp eax, 20\n    jbe .ac_cap\n    mov eax, 20\n", "    cmp eax, 99\n    jbe .ac_cap\n    mov eax, 99\n"),
        # Dragon: D5's own count is kept (the overwrite is not stored)
        'dragon-keep': ("    mov word ptr [rcx + r8], ax\n", ""),
        # Dragon: every target is counted, not only the holders
        'dragon-holder': ("    call evil_pred\n    test eax, eax\n    jz .ac_call\n", "    call evil_pred\n"),
        # Dragon: the actor's counter is not reset
        'dragon-reset': ("    mov word ptr [rax + rcx], 0\n", "    nop\n"),
        # Dragon: the game's fifth argument is not passed on
        'dragon-argument': ("    mov rax, qword ptr [rsp + 0xA0]     // the game's fifth argument, passed on\n",
                            "    mov rax, qword ptr [rsp + 0x98]     // the game's fifth argument, passed on\n"),
        # the colour is read from the wrong byte (+0x2E2D)
        'geo-colour': ("    movzx ecx, byte ptr [rdi + 0x2e2c]\n    bts qword ptr [rsp + 0x38], rcx",
                       "    movzx ecx, byte ptr [rdi + 0x2e2d]\n    bts qword ptr [rsp + 0x38], rcx"),
    }
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f'd5evil-d4sig7-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def geo(colour, *, hp=100, char_id=4810, team=2):
    b = u(char_id=char_id, team=team)
    b[0x2e2c] = colour
    struct.pack_into('<q', b, 0x2cc8, hp)
    struct.pack_into('<q', b, 0x2cd8, 100)
    return b


def fixture(subject, others, subject_rec=None):
    base = c2_fixture(subject, others)
    if subject_rec is None:
        return base

    def setup(write):
        base(write)
        subject_rec(write)
    return setup


def carried_subject(write):
    """the holder's battle record (slot 0 of the table) says carried by unit 9"""
    from offline_proof_oleffects import BATTLE_TABLE
    write(BATTLE_TABLE + 0x2ee, struct.pack('<h', 9))


def psylos_cases():
    six = lambda n: [0, 0] + [n] * 6 + [0] * 10                 # noqa: E731  ATK DEF INT RES HIT SPD, not HP/SP
    holder = lambda **k: u(ids=(PSYLOS,), char_id=PSYLOS_CHAR, **k)    # noqa: E731
    c = []

    def add(name, expected, others=(), subject=None, rec=None, family='stats', field='aggregate'):
        c.append(dict(name=name, family=family, field=field, expected=expected,
                      fixture=fixture(subject if subject is not None else holder(), list(others), rec)))
    add('no Geo Symbol on the map: 0', six(0))
    add('one symbol (colour 1): +10 on the six stats', six(10), [(geo(1), 1, True)])
    add('three symbols of three colours: +30', six(30), [(geo(1), 1, True), (geo(2), 2, True), (geo(5), 3, True)])
    add('three symbols of ONE colour count once: +10', six(10), [(geo(3), 1, True), (geo(3), 2, True), (geo(3), 3, True)])
    add('two colours, four symbols: +20', six(20), [(geo(1), 1, True), (geo(1), 2, True), (geo(4), 3, True), (geo(4), 4, True)])
    add('the clear colour 0 counts as a colour (D4 counts the raw value): 0 and 6 = +20', six(20),
        [(geo(0), 1, True), (geo(6), 2, True)])
    add('all seven colours 0..6: +70', six(70), [(geo(k), k + 1, True) for k in range(7)])
    add('a destroyed symbol (hp 0) does not count', six(10), [(geo(1), 1, True), (geo(2, hp=0), 2, True)])
    add('a symbol off the map does not count', six(10), [(geo(1), 1, True), (geo(2), 2, False)])
    add('the family is chars 4810..4819: 4819 counts', six(20), [(geo(1), 1, True), (geo(2, char_id=4819), 2, True)])
    add('char 4809 and 4820 are not Geo Symbols', six(10), [(geo(1), 1, True), (geo(2, char_id=4809), 2, True),
                                                          (geo(3, char_id=4820), 3, True)])
    add('an ordinary unit with a palette colour is not counted', six(10),
        [(geo(1), 1, True), (geo(4, char_id=10), 2, True)])
    add('symbols of any team count (enemy-side object team 2 and an allied team 0)', six(20),
        [(geo(1, team=2), 1, True), (geo(2, team=0), 2, True)])
    add('colour bytes that differ by 64 stay distinct (200 and 136 are two colours)', six(20),
        [(geo(200), 1, True), (geo(136), 2, True)])
    add('the holder unlearned: 0', six(0), [(geo(1), 1, True)], subject=u(char_id=PSYLOS_CHAR))
    add('the holder carried: 0', six(0), [(geo(1), 1, True)], rec=carried_subject)
    add('the holder is itself a Geo Symbol family unit: 0', six(0), [(geo(1), 1, True)],
        subject=u(ids=(PSYLOS,), char_id=4810))
    add('only the six stats move: potency untouched', [50] * 8, [(geo(1), 1, True)], family='potency', field='potency')
    return c


# ---------------------------------------------------------------------------------------------------------------- dragon
DRAGON = 27663
SR0, SR_STRIDE, CNT = 0x141067DC8, 0xE98, 0x5D8          # stat record array; the Impact Charge counter is the short at +0x5D8
SITE_ADD, GAME_APPLY = 0x1401B1BE0, 0x1401B1FD0
SITE_RESET, GAME_POST = 0x14053FE71, 0x140542CB0
BREC_STRIDE = 0x1260
POISON = 0x7A7A7A7A7A7A7A7A


def dunit(ids, stat_index):
    b = bytearray(0x4800)
    ids = sorted(ids)
    struct.pack_into('<i', b, 0x3030, len(ids))
    for i, v in enumerate(ids):
        struct.pack_into('<I', b, 0x2F30 + 4 * i, v)
    struct.pack_into('<I', b, 0x4348, stat_index)
    return b


def counter_va(stat_index):
    return SR0 + stat_index * SR_STRIDE + CNT


class DragonRig:
    """the pinned exe (or the kit build of it) under Unicorn; the game's own damage_apply_damage and post_hit_effects are stubs"""

    def __init__(self, exe):
        import stat_oracle as so
        from unicorn import UC_HOOK_CODE
        self.so = so
        self.e = so.Emu(exe_path=exe)
        self.log = []
        self.d5_inc = 1
        e, X = self.e, self.e.X

        def game_apply():
            mu = e.mu
            rsp = mu.reg_read(X.UC_X86_REG_RSP)
            args = tuple(mu.reg_read(r) for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9))
            fifth = struct.unpack('<Q', e.read(rsp + 0x28, 8))[0]
            self.log.append(('apply', args, fifth))
            # D5's own count (damage_apply_damage 0x1401B2527..0x1401B2544): +1 on the target unit's stat record +0x5D8
            unit = struct.unpack('<Q', e.read(args[1] + 0x240, 8))[0]
            if unit and self.d5_inc:
                idx = struct.unpack('<I', e.read(unit + 0x4348, 4))[0]
                if idx < 0x28A:
                    va = counter_va(idx)
                    cur = struct.unpack('<h', e.read(va, 2))[0]
                    e.mu.mem_write(va, struct.pack('<h', cur + self.d5_inc))
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                mu.reg_write(r, POISON)                     # legal volatile clobbers: the wrapper must not rely on them
            return 0x5A5A

        def game_post():
            mu = e.mu
            self.log.append(('post', tuple(mu.reg_read(r) for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8))))
            return 0x7B7B
        e.stubs[GAME_APPLY], e.stubs[GAME_POST] = game_apply, game_post
        for a in (GAME_APPLY, GAME_POST):
            e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=a, end=a)

    def prepare(self, units):
        """units = {stat_index: (ids, counter)}; every stat record is zeroed first, then the counters are set"""
        e = self.e
        e.brk = e.heap_mark
        e.mu.mem_write(SR0, bytes(SR_STRIDE * 0x28A))
        out = {}
        for idx, (ids, counter) in units.items():
            e.mu.mem_write(counter_va(idx), struct.pack('<h', counter))
            ptr = e.alloc(dunit(ids, idx))
            brec = e.alloc(self._brec(ptr))
            out[idx] = (ptr, brec)
        return out

    @staticmethod
    def _brec(unit_ptr):
        b = bytearray(BREC_STRIDE)
        struct.pack_into('<Q', b, 0x240, unit_ptr)
        return b

    def bonus(self, ids, idx):
        """the REAL damage_attack_bonus_rules body (0x1401F6300) run from its first instruction for an attacker with learned list `ids`
        and stat index `idx` against a target of stat index idx + 1: the attack-power percent it returns (the counter is read from memory)"""
        e = self.e
        X, mu = e.X, e.mu
        brk = e.brk
        au = e.alloc(dunit(ids, idx))
        mu.mem_write(au + 0x2cc8, struct.pack('<q', 1000))
        mu.mem_write(au + 0x2cd8, struct.pack('<q', 1000))
        du = e.alloc(dunit((), idx + 1))
        mu.mem_write(du + 0x2cc8, struct.pack('<q', 1000))
        mu.mem_write(du + 0x2cd8, struct.pack('<q', 1000))
        ab, db = e.alloc(self._brec(au)), e.alloc(self._brec(du))
        ctx, k = e.alloc(bytes(0x27700)), e.alloc(bytes(0x1000))
        rsp = self.so.STACK + 0x100000 - 0x400
        mu.mem_write(rsp, struct.pack('<Q', self.so.RET))
        mu.mem_write(rsp + 0x28, struct.pack('<Q', 0))
        mu.reg_write(X.UC_X86_REG_RSP, rsp)
        for r, v in ((X.UC_X86_REG_RCX, ab), (X.UC_X86_REG_RDX, db), (X.UC_X86_REG_R8, k), (X.UC_X86_REG_R9, ctx)):
            mu.reg_write(r, v)
        mu.emu_start(0x1401F6300, self.so.RET, count=20_000_000)
        e.brk = brk
        return struct.unpack('<q', struct.pack('<Q', mu.reg_read(X.UC_X86_REG_RAX)))[0]

    def counters(self, *idxs):
        return {i: struct.unpack('<h', self.e.read(counter_va(i), 2))[0] for i in idxs}

    def start(self, site, regs, stack_words, abi, section, saved_check):
        """run the real call at `site` until site + 5; returns (rax, [problems])"""
        e = self.e
        X, mu = e.X, e.mu
        rsp = self.so.STACK + 0x100000 - 0x400
        mu.reg_write(X.UC_X86_REG_RSP, rsp)
        for r, v in regs.items():
            mu.reg_write(getattr(X, 'UC_X86_REG_' + r.upper()), v)
        for off, v in stack_words.items():
            mu.mem_write(rsp + off, struct.pack('<Q', v))
        saved = {X.UC_X86_REG_RBX: 0x1111, X.UC_X86_REG_RBP: 0x2222, X.UC_X86_REG_RSI: 0x3333, X.UC_X86_REG_RDI: 0x4444,
                 X.UC_X86_REG_R12: 0x5555, X.UC_X86_REG_R13: 0x6666, X.UC_X86_REG_R14: 0x7777, X.UC_X86_REG_R15: 0x8888}
        for r, v in saved.items():
            mu.reg_write(r, v)
        bad, hooks = [], []
        if abi:
            import capstone
            from unicorn import UC_HOOK_CODE
            md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
            lo, hi = section

            def code(uc, addr, size, _):
                if addr == site + 5:
                    bad.extend(f'register {r} changed across the redirected call' for r, v in saved.items() if uc.reg_read(r) != v)
                    if uc.reg_read(X.UC_X86_REG_RSP) != rsp:
                        bad.append('rsp changed across the redirected call')
                if lo <= addr < hi:
                    ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
                    if ins.mnemonic == 'call' and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                        bad.append(f'misaligned call at {addr:#x}')
            hooks.append(mu.hook_add(UC_HOOK_CODE, code))
        try:
            mu.reg_write(X.UC_X86_REG_RIP, site)
            mu.emu_start(site, site + 5, count=3_000_000)
        finally:
            for k in hooks:
                mu.hook_del(k)
        assert not bad, bad
        return mu.reg_read(X.UC_X86_REG_RAX)


def make_ctx(e, slot_value, category, idx=0):
    """an action context: the result slot of target `idx` and the skill row pointer (category byte +0x3F6); category None = no skill"""
    ctx = bytearray(0x27700)
    struct.pack_into('<q', ctx, idx * 0x260 + 0x1328, slot_value)
    if category is not None:
        row = e.alloc(bytes(0x400)[:0x3F6] + bytes([category]) + bytes(9))
        struct.pack_into('<Q', ctx, 0x27678, row)
    return e.alloc(ctx)


def dragon_rows():
    row = overlay_row('D4_Class_2170', DRAGON)
    assert row == {'family': 'attack_counter'}, row
    return {DRAGON: row, 27836: {'family': 'face_target_away'}, 121: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 1}]}}


_DK = {}


def dragon_kit(abi):
    if 'kit' not in _DK:
        import hashlib as hl
        import tempfile
        patched = ev.build_patch(ORIGINAL.read_bytes(), dragon_rows())
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='d4sig7-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _DK['kit'] = (DragonRig(tmp / 'kit.exe'), (info['code'], info['base'] + len(info['data'])), hl.sha256(patched).hexdigest())
        _DK['control'] = DragonRig(ORIGINAL)
    return _DK['kit'], _DK['control']


def dragon_section(abi, control_name=None):
    (kit, section, sha), control = dragon_kit(abi)
    ok = n = 0

    def report(name, problems):
        nonlocal ok, n
        n += 1
        ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + 'dragon: ' + name + ('' if not problems else ': ' + '; '.join(problems)))

    DR, NONE = (DRAGON,), ()
    # ---- the add site (per-target damage application)
    def add_case(rig, ids, pre, slot, category, d5_inc, idx=3, abi_=False):
        units = {idx: (ids, pre), idx - 1: (NONE, 77), idx + 1: (DR, 5)}          # the neighbours must not move
        ptrs = rig.prepare(units)
        rig.d5_inc = d5_inc
        rig.log.clear()
        ctx = make_ctx(rig.e, slot, category, idx=2)
        attacker = rig.e.alloc(rig._brec(0x1234))
        ret = rig.start(SITE_ADD, dict(rcx=attacker, rdx=ptrs[idx][1], r8=ctx, r9=2), {0x20: 0xABCD0001}, abi_, section, None)
        return ret, rig.counters(idx - 1, idx, idx + 1), rig.log[:], (attacker, ptrs[idx][1], ctx)

    cases = [
        # (name, target ids, counter before, slot, category, D5's own +1, expected counter)
        ('a damaging hit: D5 counted it too, the result is still +1 (the overwrite, not a second +1)', DR, 0, 120, None, 1, 1),
        ('an elemental hit D5 does not count: the wrapper counts it (3 -> 4)', DR, 3, 40, None, 0, 4),
        ('a miss (D5 result slot 0, hit code 0) counts, as D4 counts it', DR, 2, 0, None, 0, 3),
        ('a nullified hit (slot 0) counts', DR, 0, 0, 1, 1, 1),
        ('a buff (category 5, slot 0) counts', DR, 4, 0, 5, 0, 5),
        ('a buff (category 6, slot 0) counts', DR, 4, 0, 6, 0, 5),
        ('a heal (category 4, a positive amount) does NOT count', DR, 6, 90, 4, 0, 6),
        ('a heal does not count even when D5 itself added one (the overwrite takes it back)', DR, 6, 90, 4, 1, 6),
        ('skill category 1 / 2 / 3 count', DR, 1, 33, 1, 0, 2),
        ('skill category 2', DR, 1, 33, 2, 0, 2),
        ('skill category 3', DR, 1, 33, 3, 0, 2),
        ('no result for the target (slot -1): no count', DR, 8, -1, None, 1, 8),
        ('the cap is 20: 19 -> 20', DR, 19, 5, None, 1, 20),
        ('already 20 stays 20', DR, 20, 5, None, 1, 20),
        ('above the cap (25, from D5) is brought to 20', DR, 25, 5, None, 1, 20),
        ('a huge D5 counter (9999) is brought to 20', DR, 9999, 5, None, 0, 20),
        ('a unit without the row keeps D5\'s own count (+1)', NONE, 5, 30, None, 1, 6),
        ('a unit without the row and no D5 count stays', NONE, 5, 30, None, 0, 5),
        ('a unit with another second-word row is not a holder', (27836,), 5, 30, None, 1, 6),
        ('a unit with an ordinary row is not a holder', (121,), 5, 30, None, 1, 6),
        ('the row among other learned ids', (5, 9, DRAGON, 40000), 2, 30, None, 0, 3),
    ]
    for name, ids, pre, slot, cat, d5, want in cases:
        problems = []
        ret, counters, log, (attacker, tbrec, ctx) = add_case(kit, ids, pre, slot, cat, d5, abi_=abi)
        base_ret, base_counters, base_log, _ = add_case(control, ids, pre, slot, cat, d5)
        if counters[3] != want:
            problems.append(f'kit counter {counters[3]}, expected {want}')
        if counters[2] != 77 or counters[4] != 5:
            problems.append(f'a neighbouring counter moved: {counters}')
        if ret != 0x5A5A:
            problems.append(f'the game result was not handed back: {ret:#x}')
        if len(log) != 1 or log[0] != ('apply', (attacker, tbrec, ctx, 2), 0xABCD0001):
            problems.append(f'the game call did not get the site arguments unchanged: {log}')
        if base_counters[3] != pre + d5 or base_ret != 0x5A5A:
            problems.append(f'control exe: counter {base_counters[3]} (D5 only: {pre + d5})')
        report(name, problems)
    # no unit / no stat record / no target record
    for name, make in (
            ('a target record without a unit record: only the game call', lambda rig: (rig.e.alloc(bytes(BREC_STRIDE)), 0)),
    ):
        ptrs = kit.prepare({3: (DR, 4)})
        kit.d5_inc = 1
        kit.log.clear()
        ctx = make_ctx(kit.e, 5, None, idx=2)
        brec, _ = make(kit)
        ret = kit.start(SITE_ADD, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=brec, r8=ctx, r9=2), {0x20: 1}, abi, section, None)
        report(name, [] if ret == 0x5A5A and len(kit.log) == 1 and kit.counters(3)[3] == 4 else [f'{ret:#x} {kit.log} {kit.counters(3)}'])
    ptrs = kit.prepare({})
    ctx = make_ctx(kit.e, 5, None, idx=2)
    ret = kit.start(SITE_ADD, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=0, r8=ctx, r9=2), {0x20: 1}, abi, section, None)
    report('a null target record: only the game call', [] if ret == 0x5A5A else [hex(ret)])
    unit = kit.e.alloc(dunit(DR, 0x28A))                    # stat index out of range: no stat record
    brec = kit.e.alloc(kit._brec(unit))
    kit.log.clear()
    ret = kit.start(SITE_ADD, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=brec, r8=ctx, r9=2), {0x20: 1}, abi, section, None)
    report('a holder without a stat record (index 0x28A): only the game call', [] if ret == 0x5A5A and len(kit.log) == 1 else [hex(ret)])
    # the holder in the highest legal stat slot
    top = 0x289
    ptrs = kit.prepare({top: (DR, 7)})
    kit.d5_inc = 1
    ctx = make_ctx(kit.e, 5, None, idx=2)
    kit.start(SITE_ADD, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=ptrs[top][1], r8=ctx, r9=2), {0x20: 1}, abi, section, None)
    report('the holder in the last stat slot (0x289)', [] if kit.counters(top)[top] == 8 else [str(kit.counters(top))])
    # a run of events with the reset in the middle, driven through the real sites
    ptrs = kit.prepare({3: (DR, 0), 4: (NONE, 0)})
    kit.d5_inc = 1
    seq = []
    for slot, cat in ((10, None), (0, None), (0, 5), (50, 4), (7, 1)):
        ctx = make_ctx(kit.e, slot, cat, idx=2)
        kit.start(SITE_ADD, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=ptrs[3][1], r8=ctx, r9=2), {0x20: 1}, abi, section, None)
        seq.append(kit.counters(3)[3])
    report('a run: hit, miss, buff, heal, hit -> 1 2 3 3 4', [] if seq == [1, 2, 3, 3, 4] else [str(seq)])
    # ---- the reset site (the once-per-action pass)
    def reset_case(rig, ids, counter, idx=3, with_face=False, abi_=False, count=0):
        ptrs = rig.prepare({idx: (ids, counter), idx - 1: (DR, 11), idx + 1: (DR, 13)})
        rig.log.clear()
        ctx = bytearray(0x27700)
        struct.pack_into('<h', ctx, 0x27318, count)
        ctx = rig.e.alloc(ctx)
        ctl = rig.e.alloc(bytes(0x100))
        ret = rig.start(SITE_RESET, dict(rcx=ctl, rdx=ctx, r8=ptrs[idx][1]), {}, abi_, section, None)
        return ret, rig.counters(idx - 1, idx, idx + 1), rig.log[:], (ctl, ctx, ptrs[idx][1])
    rcases = [
        ('the actor holds the row: its counter goes to 0 at the end of the action', DR, 17, 0),
        ('a counter of 20 goes to 0', DR, 20, 0),
        ('a counter already 0 stays 0', DR, 0, 0),
        ('a unit without the row keeps its counter', NONE, 9, 9),
        ('a face_target_away holder that is not an attack_counter holder keeps its counter', (27836,), 9, 9),
        ('both rows: the counter is reset (no target to turn)', (DRAGON, 27836), 14, 0),
    ]
    for name, ids, counter, want in rcases:
        problems = []
        ret, counters, log, (ctl, ctx, brec) = reset_case(kit, ids, counter, abi_=abi)
        _, base_counters, _, _ = reset_case(control, ids, counter)
        if counters[3] != want:
            problems.append(f'kit counter {counters[3]}, expected {want}')
        if counters[2] != 11 or counters[4] != 13:
            problems.append(f'a neighbouring counter moved: {counters}')
        if ret != 0x7B7B or log != [('post', (ctl, ctx, brec))]:
            problems.append(f'post_hit_effects was not entered once with the site arguments: {log} {ret:#x}')
        if base_counters[3] != counter:
            problems.append(f'control exe changed the counter to {base_counters[3]}')
        report(name, problems)
    ptrs = kit.prepare({})
    kit.log.clear()
    ctx = kit.e.alloc(bytes(0x27700))
    ret = kit.start(SITE_RESET, dict(rcx=kit.e.alloc(bytes(0x100)), rdx=ctx, r8=0), {}, abi, section, None)
    report('no attacker record: only post_hit_effects', [] if ret == 0x7B7B and len(kit.log) == 1 else [str(kit.log)])
    unit = kit.e.alloc(dunit(DR, 0x28A))
    kit.log.clear()
    ret = kit.start(SITE_RESET, dict(rcx=kit.e.alloc(bytes(0x100)), rdx=ctx, r8=kit.e.alloc(kit._brec(unit))), {}, abi, section, None)
    report('an attacker with no stat record (index 0x28A): only post_hit_effects', [] if ret == 0x7B7B and len(kit.log) == 1 else [str(kit.log)])
    # ---- the reading side: D5's real attack-bonus rules, with the Impact Charge id (2065) in the list (the class alias puts it there)
    for rig_name, rig in (('kit build', kit), ('pinned exe', control)):
        got = []
        for c in (0, 1, 2, 5, 10, 19, 20, 21, 25, 9999):
            kit_units = rig.prepare({3: (NONE, c)})
            got.append(rig.bonus((DRAGON, 2065), 3))
        want = [min(10 * c, 200) for c in (0, 1, 2, 5, 10, 19, 20, 21, 25, 9999)]
        report(f'D5 damage_attack_bonus_rules ({rig_name}): +10 x counter, at most +200 (D4: 20 x 10): {got}', [] if got == want else [f'expected {want}'])
    rig = kit
    rig.prepare({3: (NONE, 0)})
    for c in (0, 7):
        rig.prepare({3: (NONE, c)})
        none = rig.bonus((DRAGON,), 3)                        # the kit row alone (no alias, no 2065 in the list): no bonus
        report(f'without the donor id 2065 in the list the bonus stays 0 (counter {c}): the alias does the reading', [] if none == 0 else [str(none)])
    # end to end through the real sites: events, then the real bonus, then the action end
    ptrs = kit.prepare({3: ((DRAGON, 2065), 0)})
    kit.d5_inc = 1
    seen = []
    for slot, cat in ((10, None), (0, None), (0, 5), (50, 4), (7, 1)):
        ctx = make_ctx(kit.e, slot, cat, idx=2)
        kit.start(SITE_ADD, dict(rcx=kit.e.alloc(kit._brec(1)), rdx=ptrs[3][1], r8=ctx, r9=2), {0x20: 1}, abi, section, None)
        seen.append(kit.bonus((DRAGON, 2065), 3))
    ctx = bytearray(0x27700)
    ctx = kit.e.alloc(ctx)
    kit.start(SITE_RESET, dict(rcx=kit.e.alloc(bytes(0x100)), rdx=ctx, r8=ptrs[3][1]), {}, abi, section, None)
    seen.append(kit.bonus((DRAGON, 2065), 3))
    report('end to end: hit, miss, buff, heal, hit then the unit acts: ATK bonus 10 20 30 30 40 0', [] if seen == [10, 20, 30, 30, 40, 0] else [str(seen)])
    return ok, n, sha


def run_pieces(pieces, abi, control=None):
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    rows, plans = {}, []
    if 'psylos' in pieces:
        row = overlay_row('D4_Unique_5388', PSYLOS)
        assert row == {'family': 'stats', 'effects': [{'stat': s, 'value': 10, 'per': 'geo_colours'}
                                                       for s in ('atk', 'def', 'int', 'res', 'hit', 'spd')]}, row
        rows[PSYLOS] = row
        plans += psylos_cases()
    checks = []
    if 'dragon' in pieces:
        ok, n, dsha = dragon_section(abi)
        assert ok == n, f'dragon: {ok}/{n} checks passed'
        checks += [dict(name='dragon', ok=True)] * n
        if not plans:
            return checks, dsha
    bundle = plume1.build(ev, original, rows)
    for case in plans:
        for site, result in plume1.run_case(bundle, case, abi):
            got = result[case['field']]
            assert got == case['expected'], (case['name'], hex(site), got, case['expected'])
            checks.append(dict(name=case['name'], site=hex(site), ok=True))
        print('PASS', case['name'])
    return checks, hashlib.sha256(bundle[0]).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    ap.add_argument('--piece', action='append', choices=['psylos', 'dragon', 'roc'])
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    pieces = args.piece or ['psylos', 'dragon']
    checks, sha = run_pieces(pieces, args.abi)
    report = dict(mode='abi' if args.abi else 'behavior', patched_sha256=sha, passed=True, checks=checks)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f"{len(checks)}/{len(checks)} checks passed (D4SIG7 {'+'.join(pieces)}, {'abi' if args.abi else 'behavior'}; patched exe {sha[:16]})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
