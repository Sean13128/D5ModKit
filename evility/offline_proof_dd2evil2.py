"""DD2EVIL2 offline proofs: Pleinair (ally_move), Lilliel (move_heal_percent) and Alex (random_victims), through the pinned game's REAL call sites.

  pleinair  wrap_move at the real move-range call sites (the game's menus_env_move_range stubbed to a known value): +value for every OTHER
            deployed unit of the unit's team that holds row 24320 (Disgaea D2 0xF6290 skips the unit itself, no range, one per holder).
  lilliel   wrap_endturn at the three real calls of turn_t3_per_unit_end_turn with the game's own T3 running: evil_move_heal heals
            2% x (team holders, the unit itself included) of max HP per panel moved (+0x61C), before T3 zeroes the word.
  alex      wrap_victims at 0x1401E8F76 (FUN_1401E8750's append of Punishing Prophecy's victim) with the game's own path_throw_append_target,
            events_env_kind_of, events_env_team_of and model_team_is_hostile running; game_rng_draw scripted (or the game's own, for the
            distribution check).  The rows are read verbatim from d5lib/importers/dd2-innate-evilities.json.

<unicorn python> evility/offline_proof_dd2evil2.py [--abi] [--control NAME]       (every section runs; a failing check exits 1)
Controls (a deliberately broken wrapper, the proof must then FAIL): ple-self, ple-query, team, lil-percent, lil-steps, lil-cap, lil-self,
alx-draw, alx-distinct, alx-hostile, alx-holder, alx-limit
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
from d5lib import evility as ev                                                  # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_d4sig7 as s7                                                # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/dd2evil2')
DATA = KIT / 'd5lib/importers/dd2-innate-evilities.json'
PLE, LIL, ALX = 24320, 26305, 24480
OWN_MOVE, OTHER_EXT, OTHER_EXT2 = 24900, 24901, 24902        # an ordinary `move` row, an invincible_hits row, a move_heal row of another id
TABLE, STRIDE = 0x141BA33B0, 0x1260
MOVE_FN, SHADOW, RNG, APPEND, T3 = 0x140157D90, 0x140151C50, 0x140136660, 0x1402BB960, 0x140159F50
SR0, SR_STRIDE = 0x141067DC8, 0xE98
MOVE_SITES = (0x1402C8E07, 0x1402CC17C, 0x14060EBDE)       # first, middle, last of the 23 move-range call sites
T3_SITES = (0x1405524FF, 0x140554F7F, 0x1405FB9B1)
VICTIM_SITE = 0x1401E8F76
HOSTILE = {0: (1, 3, 5), 1: (0, 3, 4), 2: (), 3: (0, 1, 4, 5), 4: (1, 3, 5), 5: (0, 3, 4)}   # model_team_is_hostile (read from the decomp)


def rows():
    d = json.loads(DATA.read_text())['packs']
    out = {PLE: d['DD2_Unique_320']['behavior'], LIL: d['DD2_Unique_420']['behavior'], ALX: d['DD2_Unique_480']['behavior']}
    assert out == {PLE: {'family': 'ally_move', 'effects': [{'value': 1}]},
                   LIL: {'family': 'move_heal_percent', 'effects': [{'value': 2}]},
                   ALX: {'family': 'random_victims', 'effects': [{'value': 5}]}}, out
    out[OWN_MOVE] = {'family': 'move', 'effects': [{'value': 2}]}
    out[OTHER_EXT] = {'family': 'invincible_hits', 'effects': [{'value': 3}]}
    return out


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        # the unit itself counts for Pleinair
        'ple-self': ("    mov rdx, 0x2000000000\n    xor r8d, r8d\n    call evil_team_sum", "    mov rdx, 0x2000000000\n    mov r8d, 1\n    call evil_team_sum"),
        # the wrong second-word bit
        'ple-query': ("    mov rdx, 0x2000000000\n", "    mov rdx, 0x1000000000\n"),
        # the team test of the shared walk
        'team': ("    cmp eax, r13d\n    jne .ts_next                        // another team\n", ""),
        # Lilliel: the percent is not taken of max HP (a flat number of HP per panel)
        'lil-percent': ("    imul rax, r14\n    cqo\n    mov rcx, 100\n    idiv rcx                            // one step's heal",
                        "    cqo\n    mov rcx, 1\n    idiv rcx                            // one step's heal"),
        # once, not once per panel moved
        'lil-steps': ("    movsxd rcx, r12d\n    imul rax, rcx                       // once per panel moved\n", ""),
        # no cap at max HP
        'lil-cap': ("    cmp rax, r14\n    jle .mh_store\n    mov rax, r14                        // never above the maximum\n", ""),
        # the unit itself is not a Healing Barrier holder for itself
        'lil-self': ("    mov rdx, 0x4000000000               // F2_MOVE_HEAL_PERCENT: second-word bit 6\n    mov r8d, 1\n",
                     "    mov rdx, 0x4000000000               // F2_MOVE_HEAL_PERCENT: second-word bit 6\n    xor r8d, r8d\n"),
        # Alex: always the maximum count, not a draw
        'alx-draw': ("    mov ecx, eax\n    call 0x140136660                    // game_rng_draw(value): 0..value-1 extra victims\n    mov r13d, eax\n",
                     "    lea r13d, [rax - 1]\n"),
        # a victim may be chosen twice
        'alx-distinct': ("    cmp eax, r15d\n    je .vi_next                         // already a target\n", ""),
        # no hostility test
        'alx-hostile': ("    call 0x1402d9290                    // model_team_is_hostile(caster's team, candidate's team)\n    test al, al\n    jz .vi_next\n",
                        "    call 0x1402d9290                    // model_team_is_hostile(caster's team, candidate's team)\n"),
        # every caster gets the extra victims
        'alx-holder': ("    call evil_dmg_sum                   // the caster's unit record in rsi\n    test eax, eax\n    jle .vi_ret                         // not a holder\n",
                       "    call evil_dmg_sum                   // the caster's unit record in rsi\n    mov eax, 5\n"),
        # no target limit
        'alx-limit': ("    cmp eax, 0x20\n    jge .vi_ret                         // the context's target limit\n", ""),
    }
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f'd5evil-dd2evil2-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def make_unit(ids=(), team=0, hp=1000, maxhp=2000, stat=7, char_id=100):
    u = s7.dunit(ids, stat)
    struct.pack_into('<q', u, 0x2CC8, hp)
    struct.pack_into('<q', u, 0x2CD8, maxhp)
    struct.pack_into('<i', u, 0x2E04, char_id)
    u[0x2E32] = team
    return u


class Rig(s7.DragonRig):
    def __init__(self, exe, rng_stub=True):
        import stat_oracle as so
        from unicorn import UC_HOOK_CODE
        self.so = so
        self.e = so.Emu(exe_path=exe, rng_stub=rng_stub)
        e, X = self.e, self.e.X
        self.log, self.script, self.moves = [], [], []

        def move_fn():
            self.log.append(('move', e.mu.reg_read(X.UC_X86_REG_RCX)))
            return self.moves[0]

        def shadow():
            self.log.append(('shadow', e.mu.reg_read(X.UC_X86_REG_RCX), e.mu.reg_read(X.UC_X86_REG_RDX)))
            return 0x5A5A
        e.stubs[MOVE_FN], e.stubs[SHADOW] = move_fn, shadow
        for a in (MOVE_FN, SHADOW):
            e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=a, end=a)
        if rng_stub:
            def rng():
                n = e.mu.reg_read(X.UC_X86_REG_RCX) & 0xFFFFFFFF
                self.log.append(('rng', n))
                return (self.script.pop(0) if self.script else 0) % max(1, n)
            e.stubs[RNG] = rng

    def table(self, units):
        """units = {slot: (unit bytes, active, carried)} -> the battle table in memory; returns {slot: record address}"""
        e = self.e
        e.brk = e.heap_mark
        e.mu.mem_write(TABLE, bytes(256 * STRIDE))
        e.mu.mem_write(SR0, bytes(SR_STRIDE * 0x28A))
        self.log.clear()
        out = {}
        for slot, (u, active, carried) in units.items():
            rec = bytearray(STRIDE)
            ptr = e.alloc(u) if u is not None else 0
            struct.pack_into('<Q', rec, 0x240, ptr)
            rec[0x2E8] = active
            struct.pack_into('<h', rec, 0x2EE, carried)
            e.mu.mem_write(TABLE + slot * STRIDE, bytes(rec))
            out[slot] = TABLE + slot * STRIDE
        return out

    def hp(self, slot):
        ptr = struct.unpack('<Q', self.e.read(TABLE + slot * STRIDE + 0x240, 8))[0]
        return struct.unpack('<q', self.e.read(ptr + 0x2CC8, 8))[0]


_RIGS = {}


def rigs():
    if not _RIGS:
        original = ORIGINAL.read_bytes()
        assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
        patched = ev.build_patch(original, rows())
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='dd2evil2-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _RIGS.update(kit=Rig(tmp / 'kit.exe'), control=Rig(ORIGINAL), section=(info['code'], info['base'] + len(info['data'])),
                     sha=hashlib.sha256(patched).hexdigest(), kit_real=Rig(tmp / 'kit.exe', rng_stub=False), ctl_real=Rig(ORIGINAL, rng_stub=False))
        assert ev.wrapper('move')[2][0] == MOVE_SITES[0] and MOVE_SITES[1] in ev.wrapper('move')[2] and MOVE_SITES[2] in ev.wrapper('move')[2]
        assert tuple(ev.wrapper('endturn')[2]) == T3_SITES and tuple(ev.wrapper('victims')[2]) == (VICTIM_SITE,)
    return _RIGS


class Checker:
    def __init__(self, tag):
        self.tag, self.ok, self.n = tag, 0, 0

    def __call__(self, name, problems):
        self.n += 1
        self.ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + self.tag + ': ' + name + ('' if not problems else ': ' + '; '.join(map(str, problems))))


# --------------------------------------------------------------------------------------------------------------------- Pleinair
def run_move(rig, site, abi, section, units, subject=1, result=4, null=False):
    recs = rig.table(units)
    rig.moves[:] = [result]
    rcx = 0 if null else recs[subject]
    rax = rig.start(site, dict(rcx=rcx), {}, abi, section, None)
    return rax & 0xFFFFFFFF, rig.log


def pleinair(abi):
    r = rigs()
    kit, control, sect = r['kit'], r['control'], r['section']
    chk = Checker('pleinair')
    H = lambda ids=(PLE,), team=0, hp=1000, active=1, carried=-1, stat=7: (make_unit(ids, team, hp, stat=stat), active, carried)
    S = lambda ids=(), team=0: (make_unit(ids, team), 1, -1)
    R = 4
    # (name, units {slot: ...} (slot 1 is the moving unit), result of the game's function, expected)
    cases = [
        ('no holder anywhere: the game result', {1: S()}, R, R),
        ('the unit itself holds it, nobody else: nothing (D2 0xF6290 skips the unit itself)', {1: S((PLE,))}, R, R),
        ('one OTHER holder of the unit\'s team: +1', {1: S(), 3: H()}, R, R + 1),
        ('two other holders: +2 (one per holder)', {1: S(), 3: H(), 4: H()}, R, R + 2),
        ('seven other holders: +7', {1: S(), **{s: H() for s in range(10, 17)}}, R, R + 7),
        ('the unit holds it too and one other does: +1 (only the other)', {1: S((PLE,)), 3: H()}, R, R + 1),
        ('a holder of another team: nothing', {1: S(), 3: H(team=1)}, R, R),
        ('a holder of the neutral team 2: nothing', {1: S(), 3: H(team=2)}, R, R),
        ('team 3 moves, a team 3 holder: +1', {1: S(team=3), 3: H(team=3)}, R, R + 1),
        ('team 3 moves, a team 0 holder: nothing', {1: S(team=3), 3: H(team=0)}, R, R),
        ('a holder not on the map: nothing', {1: S(), 3: H(active=0)}, R, R),
        ('a holder carried by another unit: nothing', {1: S(), 3: H(carried=2)}, R, R),
        ('a defeated holder (HP 0): nothing', {1: S(), 3: H(hp=0)}, R, R),
        ('a holder without a stat record (index 0x28A): nothing', {1: S(), 3: H(stat=0x28A)}, R, R),
        ('a record without a unit: skipped', {1: S(), 3: (None, 1, -1)}, R, R),
        ('a unit with another ordinary row: nothing', {1: S(), 3: H(ids=(5, 9, 40000))}, R, R),
        ('a holder with another second-word row (invincible_hits): nothing', {1: S(), 3: H(ids=(OTHER_EXT,))}, R, R),
        ('a holder of Lilliel\'s or Alex\'s row: nothing', {1: S(), 3: H(ids=(LIL,)), 4: H(ids=(ALX,))}, R, R),
        ('the row among other learned ids', {1: S(), 3: H(ids=(5, 9, PLE, 40000))}, R, R + 1),
        ('holder in slot 0', {1: S(), 0: H()}, R, R + 1),
        ('holder in the last slot 255', {1: S(), 255: H()}, R, R + 1),
        ('the moving unit in slot 255, holder in slot 0', {255: S(), 0: H()}, R, R + 1),
        ('the game result 0 (an object): nothing is added', {1: S(), 3: H()}, 0, 0),
        ('the game result 99 (unlimited): +1 is added after it (a listed difference)', {1: S(), 3: H()}, 99, 100),
        ('the unit\'s own ordinary move row (+2) and one holder: +3', {1: S((OWN_MOVE,)), 3: H()}, R, R + 3),
        ('the unit\'s own move row alone: +2 (kit rows unchanged)', {1: S((OWN_MOVE,))}, R, R + 2),
    ]
    for site in MOVE_SITES:
        for name, units, res, want in cases:
            subject = 255 if 255 in units and units.get(255, (None,))[0] is not None and name.startswith('the moving unit in slot 255') else 1
            problems = []
            got, log = run_move(kit, site, abi, sect, units, subject=subject, result=res)
            if got != want:
                problems.append(f'kit {got}, expected {want}')
            if [x for x in log if x[0] == 'move'] != [('move', TABLE + subject * STRIDE)]:
                problems.append(f'the game function was not entered once with the site argument: {log}')
            no_ple = not any(PLE in struct.unpack_from('<64I', u[0], 0x2F30) for u in units.values() if u[0] is not None)
            if no_ple:                                 # no Pleinair anywhere: identical to the pinned exe except for the unit's own kit rows
                cg, _ = run_move(control, site, 0, None, units, subject=subject, result=res)
                if OWN_MOVE not in [struct.unpack_from('<I', u[0], 0x2F30 + 4 * i)[0] for u in units.values() if u[0] is not None for i in range(3)] and got != cg:
                    problems.append(f'no row anywhere but the result differs from the pinned exe: {got} != {cg}')
            chk(f'site {site:#x}: {name}', problems)
    # null record and a record without a unit: the game result only
    for site in MOVE_SITES:
        got, _ = run_move(kit, site, abi, sect, {1: S(), 3: H()}, result=R, null=True)
        chk(f'site {site:#x}: a null battle record', [] if got == R else [got])
        recs = kit.table({3: H()})
        blank = kit.e.alloc(bytes(STRIDE))
        kit.moves[:] = [R]
        got = kit.start(site, dict(rcx=blank), {}, abi, sect, None) & 0xFFFFFFFF
        chk(f'site {site:#x}: a record without a unit', [] if got == R else [got])
    return chk


# --------------------------------------------------------------------------------------------------------------------- Lilliel
def run_endturn(rig, site, abi, section, units, subject=1, cost=3, hp=None):
    recs = rig.table(units)
    rec = recs[subject]
    rig.e.mu.mem_write(rec + 0x61C, struct.pack('<h', cost))
    rig.start(site, dict(rcx=rec), {}, abi, section, None)
    return rig.hp(subject), struct.unpack('<h', rig.e.read(rec + 0x61C, 2))[0], [x for x in rig.log if x[0] == 'shadow'], rec


def lilliel(abi):
    r = rigs()
    kit, control, sect = r['kit'], r['control'], r['section']
    chk = Checker('lilliel')
    H = lambda ids=(LIL,), team=0, hp=1000, maxhp=2000, active=1, carried=-1, stat=7: (make_unit(ids, team, hp, maxhp, stat=stat), active, carried)
    # (name, units {slot: ...} (slot 1 is the moving unit), cost (panels moved), expected HP of the mover)
    pct = lambda p, mx, steps, hp, cap: min(cap, hp + (p * mx // 100) * steps)
    cases = [
        ('the mover holds it, 3 panels: 2% x 3 of 2000 = +120', {1: H()}, 3, 1120),
        ('an ally holds it (the mover does not), 3 panels: +120', {1: H(()), 3: H()}, 3, 1120),
        ('the mover and one ally hold it: 4% per panel, 3 panels: +240', {1: H(), 3: H()}, 3, 1240),
        ('three other holders and the mover: 8% x 5 panels of 2000 = +800', {1: H(), 3: H(), 4: H(), 5: H()}, 5, 1800),
        ('no holder: nothing', {1: H(())}, 3, 1000),
        ('a holder of another team: nothing', {1: H(()), 3: H(team=1)}, 3, 1000),
        ('a holder not on the map: nothing', {1: H(()), 3: H(active=0)}, 3, 1000),
        ('a carried holder: nothing', {1: H(()), 3: H(carried=2)}, 3, 1000),
        ('a defeated holder: nothing', {1: H(()), 3: H(hp=0)}, 3, 1000),
        ('0 panels moved: nothing', {1: H()}, 0, 1000),
        ('negative panels (a corrupt word): nothing', {1: H()}, -2, 1000),
        ('1 panel: +40', {1: H()}, 1, 1040),
        ('truncation per step: max HP 1999, 2% = 39.98 -> 39, x 3 = 117', {1: H(maxhp=1999)}, 3, 1117),
        ('truncation per step: max HP 49, 2% -> 0 per step: nothing', {1: H(maxhp=49, hp=10)}, 7, 10),
        ('capped at max HP: 1990 + 120 -> 2000', {1: H(hp=1990)}, 3, 2000),
        ('already at max HP: unchanged', {1: H(hp=2000)}, 3, 2000),
        ('HP above max HP is left alone', {1: H(hp=2500)}, 3, 2500),
        ('the mover is defeated (HP 0): not healed', {1: H(hp=0)}, 3, 0),
        ('max HP 0: nothing', {1: H(hp=5, maxhp=0)}, 3, 5),
        ('another second-word row (invincible_hits) is not Healing Barrier', {1: H((OTHER_EXT,))}, 3, 1000),
        ('Pleinair\'s row is not Healing Barrier', {1: H((PLE,))}, 3, 1000),
        ('64-bit HP: 4e12 of 1e13 at 2%, 2 panels: +4e11', {1: H(hp=4 * 10 ** 12, maxhp=10 ** 13)}, 2, 4 * 10 ** 12 + 4 * 10 ** 11),
        ('the unit with a record in slot 255 and a holder in slot 0', {255: H(()), 0: H()}, 3, 1120),
    ]
    for site in T3_SITES:
        for name, units, cost, want in cases:
            subject = 255 if 255 in units else 1
            problems = []
            hp, cost_after, shadows, rec = run_endturn(kit, site, abi, sect, units, subject=subject, cost=cost)
            if hp != want:
                problems.append(f'HP {hp}, expected {want}')
            if cost_after != 0:
                problems.append(f'T3 did not run: panels-moved word {cost_after}')
            healed = want != units[subject][0] and struct.unpack_from('<q', units[subject][0], 0x2CC8)[0] != want
            if bool(shadows) != healed:
                problems.append(f'shadow calls {shadows}, healed {healed}')
            if healed and shadows != [('shadow', rec, want)]:
                problems.append(f'unit_set_hp_shadow not called with (record, new HP): {shadows}')
            chk(f'site {site:#x}: {name}', problems)
        # neighbours are untouched: a holder in slot 3 and an ally in slot 4 do not change when slot 1 ends its turn
        run = run_endturn(kit, site, abi, sect, {1: H(()), 3: H(), 4: H(())}, subject=1, cost=3)
        chk(f'site {site:#x}: the other units\' HP is untouched', [] if (kit.hp(3), kit.hp(4)) == (1000, 1000) else [(kit.hp(3), kit.hp(4))])
        # the pinned exe heals nobody (D5 has no such rule)
        hp = run_endturn(control, site, 0, None, {1: H(), 3: H()}, subject=1, cost=3)[0]
        chk(f'site {site:#x}: the pinned exe does not heal', [] if hp == 1000 else [hp])
    # a null record: only the game call (T3 with a null record is the game's own)
    return chk


# --------------------------------------------------------------------------------------------------------------------- Alex
CTX = 0x27700


def make_ctx(rig, caster, already=()):
    c = bytearray(CTX)
    struct.pack_into('<h', c, 0, caster)
    struct.pack_into('<h', c, 0x1310, 1)
    for i, s in enumerate(already):
        struct.pack_into('<h', c, 0x1318 + i * 0x260, s)
    struct.pack_into('<h', c, 0x27318, len(already))
    return rig.e.alloc(c)


def targets(rig, ctx):
    n = struct.unpack('<h', rig.e.read(ctx + 0x27318, 2))[0]
    return [struct.unpack('<h', rig.e.read(ctx + 0x1318 + i * 0x260, 2))[0] for i in range(n)]


def run_victims(rig, abi, section, units, caster, first, script, already=()):
    rig.table(units)
    ctx = make_ctx(rig, caster, already)
    rig.script[:] = script
    count = len(already)
    rig.start(VICTIM_SITE, dict(rcx=ctx, rdx=count, r8=first), {}, abi, section, None)
    return targets(rig, ctx), [x for x in rig.log if x[0] == 'rng']


def model(units, caster, first, extra, picks, already=()):
    """an independent model of the rule: the game's own list rules, the first victim and what is already a target excluded, then `extra`
    distinct picks, pick k = picks[k] mod (candidates left)"""
    cu = units[caster][0]
    cteam = cu[0x2E32]
    chosen = list(already) + [first]
    cand = []
    for slot in sorted(units):
        u, active, carried = units[slot]
        if u is None or not active or carried >= 0:
            continue
        if struct.unpack_from('<I', u, 0x4348)[0] >= 0x28A or struct.unpack_from('<q', u, 0x2CC8)[0] < 1:
            continue
        cid = struct.unpack_from('<i', u, 0x2E04)[0]
        if int(cid / 100) in (0x33, 0x34, 0x30) or 0 <= cid - 5000 < 10:
            continue
        if u[0x2E32] not in HOSTILE[cteam] or slot in chosen:
            continue
        cand.append(slot)
    out = list(chosen)
    for k in range(extra):
        if not cand or len(out) >= 0x20:
            break
        out.append(cand.pop(picks[k] % len(cand)))
    return out


def alex(abi):
    r = rigs()
    kit, control, sect = r['kit'], r['control'], r['section']
    chk = Checker('alex')
    H = lambda ids=(), team=1, hp=500, active=1, carried=-1, stat=7, char_id=100: (make_unit(ids, team, hp, stat=stat, char_id=char_id), active, carried)
    CASTER = (make_unit((ALX,), 0), 1, -1)
    enemies = {s: H() for s in (2, 3, 4, 5, 6, 9)}                      # six hostile units in slots 2..9
    base = {0: CASTER, **enemies}
    # (name, units, first victim, raw draws [count draw, pick draws...], already targets)
    cases = [
        ('count draw 0: the game\'s one victim only (total count 1)', base, 3, [0], ()),
        ('count draw 1: one more distinct victim (total 2)', base, 3, [1, 0], ()),
        ('count draw 4: four more (total 5, the maximum)', base, 3, [4, 0, 0, 0, 0], ()),
        ('picks follow the draw over the remaining candidates, in slot order', base, 9, [3, 2, 4, 1], ()),
        ('the first victim is never picked again', base, 2, [2, 0, 0], ()),
        ('fewer candidates than the count: all of them, then stop', {0: CASTER, 2: H(), 3: H()}, 2, [4, 0, 0, 0, 0], ()),
        ('the only hostile unit was the game\'s victim: nothing more', {0: CASTER, 2: H()}, 2, [4, 0, 0, 0, 0], ()),
        ('the game\'s victim was not in the list (a forced slot): it is kept, extras are other units', base, 7, [1, 0], ()),
        ('a unit of the caster\'s own team is never picked', {**base, 7: H(team=0)}, 3, [4, 0, 0, 0, 0], ()),
        ('a unit of team 3 (hostile to team 0) can be picked', {0: CASTER, 2: H(), 3: H(team=3), 4: H(team=5)}, 2, [2, 0, 0], ()),
        ('the neutral team 2 is not hostile', {0: CASTER, 2: H(), 3: H(team=2), 4: H(team=2)}, 2, [2, 0, 0], ()),
        ('an inactive unit is skipped', {**base, 7: H(active=0)}, 3, [4, 0, 0, 0, 0], ()),
        ('a carried unit is skipped', {**base, 7: H(carried=2)}, 3, [4, 0, 0, 0, 0], ()),
        ('a defeated unit (HP 0) is skipped (events_env_kind_of == 2)', {**base, 7: H(hp=0)}, 3, [4, 0, 0, 0, 0], ()),
        ('an object class (id 4800, /100 = 48) is skipped', {**base, 7: H(char_id=4800)}, 3, [4, 0, 0, 0, 0], ()),
        ('an object class (id 5003) is skipped', {**base, 7: H(char_id=5003)}, 3, [4, 0, 0, 0, 0], ()),
        ('class id 5010 is an ordinary unit', {0: CASTER, 2: H(), 7: H(char_id=5010)}, 2, [1, 0], ()),
        ('a unit without a stat record is skipped', {**base, 7: H(stat=0x28A)}, 3, [4, 0, 0, 0, 0], ()),
        ('the caster in slot 255', {255: CASTER, **enemies}, 3, [2, 1, 3], ()),
        ('hostile units in slot 0 and 255', {1: CASTER, 0: H(), 255: H()}, 0, [2, 0, 0], ()),
        ('40 hostile candidates and the maximum count: five more at most', {0: CASTER, **{s: H() for s in range(10, 50)}}, 10, [4, 7, 3, 9, 1], ()),
        ('the context already holds 31 targets: only one more fits (limit 0x20)', {0: CASTER, **{s: H() for s in range(100, 140)}}, 100, [4, 0, 0, 0, 0], tuple(range(40, 71))),
    ]
    for name, units, first, script, already in cases:
        problems = []
        extra = script[0] % 5
        caster = next(s for s, u in units.items() if u is CASTER)
        want = model(units, caster, first, extra, script[1:], already)
        got, rngs = run_victims(kit, abi, sect, units, caster, first, script, already)
        if got != want:
            problems.append(f'targets {got}, model {want}')
        if len(set(got)) != len(got):
            problems.append('a victim twice')
        if not rngs or rngs[0] != ('rng', 5):
            problems.append(f'the first draw is not game_rng_draw(value 5): {rngs[:2]}')
        # the game's own path: the pinned exe appends exactly the first victim
        cg, _ = run_victims(control, 0, None, units, caster, first, script, already)
        if cg != list(already) + [first]:
            problems.append(f'the pinned exe appended {cg}')
        chk(name, problems)
    # a caster without the row: exactly the game's append, no draw
    nh = {0: (make_unit((), 0), 1, -1), **enemies}
    got, rngs = run_victims(kit, abi, sect, nh, 0, 3, [4, 0, 0, 0, 0])
    chk('a caster without the row: only the game\'s victim, no draw', [] if got == [3] and not rngs else [got, rngs])
    got, rngs = run_victims(kit, abi, sect, {0: (make_unit((OTHER_EXT, PLE, LIL), 0), 1, -1), **enemies}, 0, 3, [4, 0, 0, 0, 0])
    chk('a caster with only other second-word rows: no extra victims', [] if got == [3] and not rngs else [got, rngs])
    # a context with no caster entry / a bad caster slot: the game's append only
    for label, setup in (('no caster entry (cast count 0)', 'count'), ('caster slot 300', 'slot')):
        kit.table({0: CASTER, **enemies})
        c = bytearray(CTX)
        struct.pack_into('<h', c, 0, 300 if setup == 'slot' else 0)
        struct.pack_into('<h', c, 0x1310, 1 if setup == 'slot' else 0)
        ctx = kit.e.alloc(c)
        kit.script[:] = [4, 0, 0, 0, 0]
        kit.log.clear()
        kit.start(VICTIM_SITE, dict(rcx=ctx, rdx=0, r8=3), {}, abi, sect, None)
        chk(label + ': only the game\'s victim', [] if targets(kit, ctx) == [3] and not [x for x in kit.log if x[0] == 'rng'] else [targets(kit, ctx)])
    # the caster's record has no unit record
    kit.table({0: (None, 1, -1), **enemies})
    ctx = make_ctx(kit, 0)
    kit.start(VICTIM_SITE, dict(rcx=ctx, rdx=0, r8=3), {}, abi, sect, None)
    chk('a caster record without a unit: only the game\'s victim', [] if targets(kit, ctx) == [3] else [targets(kit, ctx)])
    # the game's own random function: the count is 1..5 and uniform, every victim hostile and distinct, and a second run from the same state repeats
    seq = []
    for rig_name in ('kit_real', 'kit_real'):
        rig = r[rig_name]
        rig.e.mu.mem_write(0x147B10AC8, bytes(0x28))            # the game's RNG state words (DAT_147b10ac8 .. ae8)
        runs = []
        units = {0: CASTER, **{s: H() for s in range(2, 12)}, 20: H(team=0), 21: H(team=2)}
        for k in range(300):
            got, _ = run_victims(rig, abi, sect, units, 0, 2 + (k % 10), [])
            runs.append(got)
        seq.append(runs)
    runs = seq[0]
    counts = [len(x) for x in runs]
    hist = {n: counts.count(n) for n in range(1, 6)}
    problems = []
    if seq[0] != seq[1]:
        problems.append('a second run from the same RNG state differs (not reproducible)')
    if any(not 1 <= n <= 5 for n in counts):
        problems.append(f'a count outside 1..5: {hist}')
    if min(hist.values()) < 30:                                  # expected 60 each of 300
        problems.append(f'the count is not spread over 1..5: {hist}')
    if any(len(set(x)) != len(x) or any(s not in range(2, 12) for s in x) for x in runs):
        problems.append('a victim twice or not a hostile unit')
    chk(f'the game\'s own RNG: 300 runs, counts {hist}, distinct, hostile, identical on a repeat from the same state', problems)
    return chk


def sweep(abi):
    """the number is the row's, not a constant of the wrapper: the same cases with other values (Pleinair 3 / 100, Lilliel 5, Alex 2)"""
    chk = Checker('values')
    original = ORIGINAL.read_bytes()
    for ple, lil, alx in ((3, 5, 2), (100, 1, 1)):
        rs = rows()
        rs[PLE] = {'family': 'ally_move', 'effects': [{'value': ple}]}
        rs[LIL] = {'family': 'move_heal_percent', 'effects': [{'value': lil}]}
        rs[ALX] = {'family': 'random_victims', 'effects': [{'value': alx}]}
        patched = ev.build_patch(original, rs)
        info = ev.section_info(patched)
        tmp = Path(tempfile.mkdtemp(prefix='dd2evil2v-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        rig, sect = Rig(tmp / 'kit.exe'), (info['code'], info['base'] + len(info['data']))
        S = lambda ids=(), team=0, hp=1000: (make_unit(ids, team, hp), 1, -1)
        got, _ = run_move(rig, MOVE_SITES[0], abi, sect, {1: S(), 3: S((PLE,)), 4: S((PLE,))}, result=4)
        chk(f'Pleinair value {ple}, two holders: {4 + 2 * ple}', [] if got == 4 + 2 * ple else [got])
        hp, _, _, _ = run_endturn(rig, T3_SITES[0], abi, sect, {1: S((LIL,)), 3: S((LIL,))}, subject=1, cost=2)
        want = min(2000, 1000 + (2 * lil * 2000 // 100) * 2)
        chk(f'Lilliel value {lil}, two holders, 2 panels: HP {want}', [] if hp == want else [hp])
        units = {0: (make_unit((ALX,), 0), 1, -1), **{s: (make_unit((), 1, 500), 1, -1) for s in range(2, 8)}}
        got, rngs = run_victims(rig, abi, sect, units, 0, 3, [9, 0, 0, 0, 0, 0])
        want_n = 1 + (9 % alx)
        chk(f'Alex value {alx}: game_rng_draw({alx}) and {want_n} victims', [] if len(got) == want_n and rngs[0] == ('rng', alx) else [got, rngs[:1]])
    return chk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    ap.add_argument('--section', choices=('pleinair', 'lilliel', 'alex', 'values'))
    args = ap.parse_args()
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    total_ok = total_n = 0
    for name, fn in (('pleinair', pleinair), ('lilliel', lilliel), ('alex', alex), ('values', sweep)):
        if args.section and args.section != name:
            continue
        chk = fn(args.abi)
        total_ok += chk.ok
        total_n += chk.n
    print(f"{total_ok}/{total_n} {'abi' if args.abi else 'behavior'}; kit build sha256 {rigs()['sha'][:16]}, control exe {rigs()['control'].e.exe_sha[:16]}")
    return 0 if total_ok == total_n else 1


if __name__ == '__main__':
    sys.exit(main())
