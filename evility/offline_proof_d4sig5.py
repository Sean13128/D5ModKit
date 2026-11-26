"""D4SIG5: evasion (Reprachon's Misty Haze 351, Kyoko's Beryl's Servant 1 844) through the REAL patched CALL site of
damage_hit_chance_rules (0x1401C2318, the one call in damage_hit_roll_hit), Unicorn, normal and --abi.  Offline, read-only.

The wrapped game function is stubbed, but its first act -- clamp the in/out percent to 1..100 (pinned exe 0x1401F5431..0x1401F5475) -- is
modelled by `clamp_out`, and that model is itself checked against the REAL prologue bytes of the pinned exe (`prologue_check`).  Everything the
extension does around it runs: the defender's evasion rows (evil_dmg_sum with the effect-mode filter), the attacker's own `hit` rows, the
conditions (attack direction from the action context, Raspberyl next to Kyoko on the game's own 256-record battle table).  Rows 8351 and 27844
are read verbatim from d5lib/importers/d4-evility-overlay.json.

  * a sweep compares the final percent with an independent model of D4's formula (FUN_1400FF700: cap100(raw - flat), then x (100 - v) / 100,
    floor 1 for D5) for raw percents -20..300;
  * --control mode|formula|row|dir : a deliberately broken wrapper / row; the proof must then FAIL (exit 1).

<unicorn python> evility/offline_proof_d4sig5.py [--abi] [--control mode|formula|row|dir]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_ex06 as e6                         # noqa: E402
from abi_engine_ex05c import execute                    # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig5')
MISTY, BERYL = 8351, 27844
HIT20 = 27990                                           # an attacker's plain `hit` row, +20
SC30, SC20, PT10, MIXED, SC100 = 27991, 27992, 27993, 27994, 27995


def overlay_rows():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    misty = mods['D4_Unique_5310']['behaviors']['evilities'][str(MISTY)]
    beryl = mods['D4_Unique_350']['behaviors']['evilities'][str(BERYL)]
    assert misty == {'family': 'evasion', 'effects': [{'value': 50}], 'conditions': [{'kind': 'attack_dir', 'id': 0}]}, misty
    assert beryl == {'family': 'evasion', 'effects': [{'value': 50, 'mode': 'points'}],
                     'conditions': [{'kind': 'near_char', 'of': 1, 'radius': 1, 'id': 650}]}, beryl
    return misty, beryl


def rows(control=None):
    misty, beryl = overlay_rows()
    misty, beryl = json.loads(json.dumps(misty)), json.loads(json.dumps(beryl))
    if control == 'row':
        misty['effects'][0]['value'] = 51
    if control == 'dir':
        misty['conditions'][0]['id'] = 1
    return {MISTY: misty, BERYL: beryl,
            HIT20: {'family': 'hit', 'effects': [{'value': 20}]},
            SC30: {'family': 'evasion', 'effects': [{'value': 30}]},
            SC20: {'family': 'evasion', 'effects': [{'value': 20}]},
            PT10: {'family': 'evasion', 'effects': [{'value': 10, 'mode': 'points'}]},
            MIXED: {'family': 'evasion', 'effects': [{'value': 20, 'mode': 'points'}, {'value': 50}]},
            SC100: {'family': 'evasion', 'effects': [{'value': 100}]}}


def d4_model(raw, flat, scale):
    """D4 FUN_1400FF700 for one hit: rate = cap100(raw - flat) (never below 0), x the product of (100 - v) / 100, truncated;
    D5's own floor of 1 (damage_hit_roll_hit clamps to 1..99, damage_hit_chance_rules to 1..100) is the only difference."""
    rate = max(0, min(100, raw - flat))
    rate = rate * (100 - scale) // 100 if scale else rate
    return max(1, rate)


def fx(*, attacker_ids=(), **kw):
    """the ex06 fixture with the defender as subject (REC = the attacker's record, OREC = the defender's), plus the attacker's learned ids"""
    base = e6.fixture(subject_is_other=True, **kw)

    def setup(write):
        base(write)
        if attacker_ids:
            write(e6.OTHER, e6.unit(ids=attacker_ids, team=1, char_id=10, max_hp=100))
    return setup


def cases():
    def run(name, expected, ids=(), raw=80, direction=None, others=(), attacker_ids=()):
        return dict(name=name, expected=expected, ids=ids, raw=raw,
                    fixture=fx(ids=ids, direction=direction, others=others, attacker_ids=attacker_ids))
    rasp = lambda team=0, char=650, cell=(5, 6): ((e6.unit(team=team, char_id=char), cell, 2),)    # noqa: E731
    out = [
        run('no row: the percent is the game result (80)', 80),
        run('no row: 150 before the call is clamped by the game to 100', 100, raw=150),
        run('no row: -5 is clamped by the game to 1', 1, raw=-5),
        # Misty Haze 8351, verbatim row
        run('Misty Haze: front attack, 80 -> 40', 40, (MISTY,), direction=0),
        run('Misty Haze: front attack, 33 -> 16 (16.5 truncated)', 16, (MISTY,), raw=33, direction=0),
        run('Misty Haze: front attack, 1 -> 1 (0 is floored)', 1, (MISTY,), raw=1, direction=0),
        run('Misty Haze: front attack, 100 -> 50', 50, (MISTY,), raw=100, direction=0),
        run('Misty Haze: front attack, 150 before the game clamp -> 100 -> 50 (D4 caps at 100 first)', 50, (MISTY,), raw=150, direction=0),
        run('Misty Haze: side attack -> untouched', 80, (MISTY,), direction=1),
        run('Misty Haze: attack from behind -> untouched', 80, (MISTY,), direction=2),
        run('Misty Haze: no target entry for the attacker -> untouched', 80, (MISTY,)),
        run('Misty Haze: 51 learned ids around the row cannot hide it', 40, tuple(range(100, 150)) + (MISTY,), direction=0),
        # Beryl's Servant 1 844, verbatim row
        run('Beryl: Raspberyl on the next panel, 80 -> 30', 30, (BERYL,), others=rasp()),
        run('Beryl: 120 before the game clamp -> 70 (the 50 comes off BEFORE the cap, as in D4)', 70, (BERYL,), raw=120, others=rasp()),
        run('Beryl: 149 -> 99', 99, (BERYL,), raw=149, others=rasp()),
        run('Beryl: 150 -> 100 (no effect: the cap hides it, as in D4)', 100, (BERYL,), raw=150, others=rasp()),
        run('Beryl: 151 -> 100', 100, (BERYL,), raw=151, others=rasp()),
        run('Beryl: 40 -> floor 1 (D4 reaches 0, D5 keeps 1)', 1, (BERYL,), raw=40, others=rasp()),
        run('Beryl: Raspberyl on the opposite neighbouring panel -> 30', 30, (BERYL,), others=rasp(cell=(4, 5))),
        run('Beryl: Raspberyl two panels away -> untouched', 80, (BERYL,), others=rasp(cell=(5, 7))),
        run('Beryl: Raspberyl is on the enemy side -> untouched', 80, (BERYL,), others=rasp(team=1)),
        run('Beryl: another character next to Kyoko -> untouched', 80, (BERYL,), others=rasp(char=10)),
        run('Beryl: nobody next to Kyoko -> untouched', 80, (BERYL,)),
        run('Beryl: direction does not matter (side attack) -> 30', 30, (BERYL,), direction=1, others=rasp()),
        # both rows on one unit: points first (before the clamp), scale last
        run('Misty + Beryl, front, Raspberyl next: 120 -> 70 -> 35', 35, (MISTY, BERYL), raw=120, direction=0, others=rasp()),
        run('Misty + Beryl, side, Raspberyl next: 120 -> 70', 70, (MISTY, BERYL), raw=120, direction=1, others=rasp()),
        run('Misty + Beryl, front, nobody next: 120 -> 100 -> 50', 50, (MISTY, BERYL), raw=120, direction=0),
        # the family itself
        run('scale 30 without conditions: 77 -> 53 (53.9 truncated)', 53, (SC30,), raw=77),
        run('scale 30 + scale 20 add up (D4 would multiply: 56): 80 -> 40', 40, (SC30, SC20)),
        run('points 10: 80 -> 70', 70, (PT10,)),
        run('one row with a points 20 and a scale 50 effect: 80 -> 60 -> 30 (the mode filter splits the row)', 30, (MIXED,)),
        run('scale 100 removes the whole chance, the floor is 1', 1, (SC100,)),
        # the attacker's own hit rows are still applied, and before the scale
        run('attacker hit +20 alone: 50 -> 70', 70, raw=50, attacker_ids=(HIT20,)),
        run('attacker hit +20, defender Misty front: 50 -> 70 -> 35', 35, (MISTY,), raw=50, direction=0, attacker_ids=(HIT20,)),
        run('attacker hit +20, defender Beryl: 80 -> 30 (points) -> 50', 50, (BERYL,), raw=80, others=rasp(), attacker_ids=(HIT20,)),
    ]
    return out


def mutated_asm(control):
    from d5lib import evility as ev
    text = Path(ev.ASM_FILE).read_text()
    old, new = {
        'mode': ("    mov dword ptr [rip + evil_fxmode], 2\n", "    mov dword ptr [rip + evil_fxmode], 0\n"),
        'formula': ("    mov ecx, 100\n    sub ecx, eax\n    jns .h_scale", "    mov ecx, 99\n    sub ecx, eax\n    jns .h_scale"),
    }[control]
    assert text.count(old) == 1, control
    out = SCRATCH / f'd5evil-d4sig5-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


def prologue_check(original):
    """run the REAL first instructions of damage_hit_chance_rules (pinned exe) and compare with the proof's clamp model"""
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
    from unicorn import x86_const as X
    pe = pefile.PE(data=original, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    start, stop = 0x1401F5410, 0x1401F5478
    code = original[pe.get_offset_from_rva(start - base):pe.get_offset_from_rva(start - base) + (stop - start)]
    results = {}
    for value in (-5, 0, 1, 50, 99, 100, 101, 500):
        uc = Uc(UC_ARCH_X86, UC_MODE_64)
        uc.mem_map(0x140000000, 0x2000000)
        uc.mem_write(start, bytes(code))
        uc.mem_map(0x300000000, 0x10000)
        uc.mem_write(0x300008000, struct.pack('<q', value))
        sp = 0x300009000
        uc.reg_write(X.UC_X86_REG_RSP, sp)
        uc.reg_write(X.UC_X86_REG_RCX, 0x300008000)
        uc.reg_write(X.UC_X86_REG_RDX, 0x300000100)
        uc.reg_write(X.UC_X86_REG_R8, 0x300000200)
        uc.reg_write(X.UC_X86_REG_R9, 0x300000300)
        uc.emu_start(start, stop, count=200)
        got = struct.unpack('<q', bytes(uc.mem_read(0x300008000, 8)))[0]
        assert got == max(1, min(100, value)), (value, got)
        results[value] = got
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('mode', 'formula', 'row', 'dir'))
    args = ap.parse_args()
    from d5lib import evility as ev
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if args.control in ('mode', 'formula'):
        ev.ASM_FILE = str(mutated_asm(args.control))
    original = e6.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == e6.ORIGINAL_SHA
    print('real prologue of damage_hit_chance_rules clamps to 1..100:', prologue_check(original))
    patched = ev.build_patch(original, rows(args.control))
    info = ev.section_info(patched)
    specs = [(ev.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in ev.WRAPPERS]
    _, target, sites = next(s for s in specs if s[0] == 'hit')
    assert sites == [0x1401C2318] and target == 0x1401F5410, (sites, target)
    ok = n = 0
    for case in cases():
        for site in sites:
            n += 1
            try:
                d = execute(patched, info, specs, 'hit', target, site, ids=case['ids'], abi=args.abi,
                            fixture=case['fixture'], out_value=case['raw'], clamp_out=(1, 100))
                assert d['output'] == case['expected'], (d['output'], case['expected'])
                ok += 1
                print('PASS', case['name'], hex(site))
            except Exception as exc:                 # noqa: BLE001
                print('FAIL', case['name'], hex(site), f'{type(exc).__name__}: {exc}')
    # sweep against the independent D4 model
    sweep = ((8351, 0, 50, dict(direction=0)), (27844, 50, 0, dict(others=((e6.unit(char_id=650), (5, 6), 2),))),
             (None, 0, 0, {}))
    for evid, flat, scale, kw in sweep:
        for raw in (-20, 0, 1, 30, 49, 50, 51, 77, 99, 100, 101, 120, 149, 150, 151, 300):
            n += 1
            ids = (evid,) if evid else ()
            try:
                d = execute(patched, info, specs, 'hit', target, sites[0], ids=ids, abi=args.abi, fixture=fx(ids=ids, **kw),
                            out_value=raw, clamp_out=(1, 100))
                assert d['output'] == d4_model(raw, flat, scale), (raw, d['output'], d4_model(raw, flat, scale))
                ok += 1
            except Exception as exc:                 # noqa: BLE001
                print('FAIL sweep', evid, raw, f'{type(exc).__name__}: {exc}')
    print(f'{ok}/{n} checks passed')
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
