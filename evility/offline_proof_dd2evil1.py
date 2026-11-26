"""DD2EVIL1: two DD2 signature evilities through the REAL patched CALL sites, Unicorn, normal and --abi.  Offline, read-only.

  * Pringer Z, Heavy Stance 300 "Cannot be lifted": row 24300 {"family": "flight"} makes has_flight_like_evility (the 124 / 1224 / 5000
    test inside cannot_be_carried_by) true for its holder, at all three call sites (0x140157514, 0x1402DB22E, 0x140154523).
    Nothing else changes: the row carries no effects, so the stat aggregate is untouched (checked on the `stats` pass too).
  * Masked Hero, Rapid Movement 1210: row 25210 {"family": "evasion", effect value 2, per movement_cost, max 64, mode after}
    through the real call site of damage_hit_chance_rules (0x1401C2318).  DD2's own function (EBOOT.elf 0xFB0EC) clamps the percent
    to 1..100 and THEN subtracts min(64, 2 x panels moved); the independent model below is that formula.
Both rows are read verbatim from d5lib/importers/dd2-innate-evilities.json.

<unicorn python> evility/offline_proof_dd2evil1.py [--abi] [--control row|value|cap|order]
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
import offline_proof_d4sig5 as d4s5                     # noqa: E402  (fixture, the real-prologue clamp check)
from abi_engine_ex05c import execute                    # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/dd2evil1')
HEAVY, RAPID = 24300, 25210
HIT20, PT10, SC50, OTHER_FLIGHT = 27990, 27993, 27996, 27997


def data_rows():
    packs = json.loads((KIT / 'd5lib/importers/dd2-innate-evilities.json').read_text())['packs']
    heavy, rapid = packs['DD2_Unique_300'], packs['DD2_Class_22210']
    assert heavy['id'] == HEAVY and heavy['behavior'] == {'family': 'flight'}, heavy
    assert rapid['id'] == RAPID and rapid['behavior'] == {
        'family': 'evasion', 'effects': [{'value': 2, 'per': 'movement_cost', 'max': 64, 'mode': 'after'}]}, rapid
    assert heavy['row']['effect_group'] == 0 and rapid['row']['effect_group'] == 0      # no game effect rides on the row ids
    return json.loads(json.dumps(heavy['behavior'])), json.loads(json.dumps(rapid['behavior']))


def rows(control=None):
    heavy, rapid = data_rows()
    if control == 'value':
        rapid['effects'][0]['value'] = 3                 # D5's own Rapid Movement number
    if control == 'cap':
        rapid['effects'][0]['max'] = 65
    if control == 'order':
        rapid['effects'][0]['mode'] = 'points'           # before the game's clamp
    out = {(24301 if control == 'row' else HEAVY): heavy, RAPID: rapid,
           HIT20: {'family': 'hit', 'effects': [{'value': 20}]},
           PT10: {'family': 'evasion', 'effects': [{'value': 10, 'mode': 'points'}]},
           SC50: {'family': 'evasion', 'effects': [{'value': 50}]},
           OTHER_FLIGHT: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 10}]}}
    return out


def dd2_model(raw, moved):
    """DD2 EBOOT 0xFB0EC for Rapid Movement: clamp 1..100, then subtract min(64, 2 x moved) when that is above 0 (D5 floors at 1)"""
    p = max(1, min(100, raw))
    sub = min(64, 2 * moved) if 2 * moved > 0 else 0
    return max(1, p - sub)


def fx(moved=0, **kw):
    """the d4sig5 fixture (defender = unit slot 0) plus the defender's panels-moved word (battle record +0x61C)"""
    base = d4s5.fx(**kw)

    def setup(write):
        base(write)
        write(e6.BATTLE_TABLE + 0x61c, struct.pack('<h', moved))
    return setup


def hit_cases():
    def run(name, expected, ids=(), raw=80, moved=0, attacker_ids=(), direction=None):
        return dict(name=name, expected=expected, ids=ids, raw=raw,
                    fixture=fx(moved, ids=ids, attacker_ids=attacker_ids, direction=direction))
    R = (RAPID,)
    return [
        run('no row: moved 10 changes nothing (80)', 80, moved=10),
        run('Rapid Movement, moved 0: untouched', 80, R, moved=0),
        run('Rapid Movement, moved 1: 80 -> 78', 78, R, moved=1),
        run('Rapid Movement, moved 10: 80 -> 60', 60, R, moved=10),
        run('Rapid Movement, moved 31: 80 -> 18 (62 off)', 18, R, moved=31),
        run('Rapid Movement, moved 32: 80 -> 16 (64 off, the cap)', 16, R, moved=32),
        run('Rapid Movement, moved 33: still 64 off -> 16', 16, R, moved=33),
        run('Rapid Movement, moved 200: still 64 off -> 16', 16, R, moved=200),
        run('Rapid Movement, moved -3 (a negative counter): untouched', 80, R, moved=-3),
        run('Rapid Movement, raw 130 moved 10: clamped to 100 FIRST, then 20 off -> 80', 80, R, raw=130, moved=10),
        run('Rapid Movement, raw 300 moved 32: 100 - 64 -> 36', 36, R, raw=300, moved=32),
        run('Rapid Movement, raw 50 moved 32: 50 - 64 is floored at 1', 1, R, raw=50, moved=32),
        run('Rapid Movement, raw -5 moved 4: the game clamps to 1, 1 - 8 floored at 1', 1, R, raw=-5, moved=4),
        run('Rapid Movement among 51 learned ids', 60, tuple(range(100, 150)) + R, moved=10),
        run('attacker hit +20 first, then 20 off: raw 50 moved 10 -> 70 -> 50', 50, R, raw=50, moved=10, attacker_ids=(HIT20,)),
        run('Rapid Movement + a scale-50 row: 80 -> 60 -> 30 (after rows come before the scale rows)', 30, R + (SC50,), moved=10),
        run('Rapid Movement + a points-10 row (before the clamp): raw 120 -> 110 -> 100 -> 80', 80, R + (PT10,), raw=120, moved=10),
        run('a points-10 row alone: raw 120 -> 110 -> 100 (the clamp hides it, as in D4)', 100, (PT10,), raw=120),
    ]


def flight_cases():
    def run(name, expected, ids=(), original=0):
        return dict(name=name, expected=expected, ids=ids, original=original)
    return [
        run('Heavy Stance row 24300: the lift test is true (original says no)', 1, (HEAVY,)),
        run('no row: the original answer (no) stands', 0),
        run('no row: the original answer (yes, e.g. D5 Heavy Armor) stands', 1, (), 1),
        run('51 learned ids around the row', 1, tuple(range(100, 150)) + (HEAVY,)),
        run('other rows only (a stats row, a hit row): no', 0, (OTHER_FLIGHT, HIT20)),
        run('row plus the original yes: still yes', 1, (HEAVY,), 1),
    ]


def mutated_asm():
    from d5lib import evility as ev
    text = Path(ev.ASM_FILE).read_text()
    old = "    mov dword ptr [rip + evil_fxmode], 3\n    call evil_dmg_sum"
    assert text.count(old) == 1
    out = SCRATCH / 'd5evil-dd2evil1-order.inc.asm'
    out.write_text(text.replace(old, "    mov dword ptr [rip + evil_fxmode], 2\n    call evil_dmg_sum"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('row', 'value', 'cap', 'order'))
    args = ap.parse_args()
    from d5lib import evility as ev
    SCRATCH.mkdir(parents=True, exist_ok=True)
    original = e6.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == e6.ORIGINAL_SHA
    print('real prologue of damage_hit_chance_rules clamps to 1..100:', d4s5.prologue_check(original))
    if args.control == 'order':
        ev.ASM_FILE = str(mutated_asm())
    patched = ev.build_patch(original, rows(args.control))
    info = ev.section_info(patched)
    specs = [(ev.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in ev.WRAPPERS]
    ok = n = 0
    # ---- Pringer Z: the three real flight sites
    for name, target, sites in (s for s in specs if s[0] in ('flight_a', 'flight_b')):
        for case in flight_cases():
            for site in sites:
                n += 1
                try:
                    d = execute(patched, info, specs, 'flight', target, site, ids=case['ids'], abi=args.abi,
                                original_rax=case['original'])
                    assert d['output'] == case['expected'], (d['output'], case['expected'])
                    ok += 1
                    print('PASS', name, case['name'], hex(site))
                except Exception as exc:                 # noqa: BLE001
                    print('FAIL', name, case['name'], hex(site), f'{type(exc).__name__}: {exc}')
    # the row has no effect on the stat pass: a unit with 24300 gets the same aggregate as a unit with nothing
    _, st_target, st_sites = next(s for s in specs if s[0] == 'stats')
    n += 1
    try:
        a = execute(patched, info, specs, 'stats', st_target, st_sites[0], ids=(HEAVY,), abi=args.abi)['aggregate']
        b = execute(patched, info, specs, 'stats', st_target, st_sites[0], ids=(), abi=args.abi)['aggregate']
        assert a == b, (a, b)
        ok += 1
        print('PASS Heavy Stance row adds no stat (aggregate identical to a unit without it)')
    except Exception as exc:                             # noqa: BLE001
        print('FAIL no-stat check', f'{type(exc).__name__}: {exc}')
    # ---- Masked Hero: the real hit call site
    _, target, sites = next(s for s in specs if s[0] == 'hit')
    assert sites == [0x1401C2318] and target == 0x1401F5410, (sites, target)
    for case in hit_cases():
        n += 1
        try:
            d = execute(patched, info, specs, 'hit', target, sites[0], ids=case['ids'], abi=args.abi, fixture=case['fixture'],
                        out_value=case['raw'], clamp_out=(1, 100))
            assert d['output'] == case['expected'], (d['output'], case['expected'])
            ok += 1
            print('PASS', case['name'])
        except Exception as exc:                         # noqa: BLE001
            print('FAIL', case['name'], f'{type(exc).__name__}: {exc}')
    for moved in (0, 1, 2, 5, 16, 31, 32, 33, 64, 300):          # sweep against the independent DD2 model
        for raw in (-20, 0, 1, 30, 50, 64, 65, 99, 100, 101, 130, 164, 165, 300):
            n += 1
            try:
                got = execute(patched, info, specs, 'hit', target, sites[0], ids=(RAPID,), abi=args.abi, fixture=fx(moved, ids=(RAPID,)),
                              out_value=raw, clamp_out=(1, 100))['output']
                assert got == dd2_model(raw, moved), (raw, moved, got, dd2_model(raw, moved))
                ok += 1
            except Exception as exc:                     # noqa: BLE001
                print('FAIL sweep', raw, moved, f'{type(exc).__name__}: {exc}')
    print(f'{ok}/{n} checks passed')
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
