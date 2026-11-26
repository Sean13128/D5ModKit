"""EX-05d: runtime magnitudes, other-side HP, any-element, target count, current-SP conversion.

Default mode executes the installed wrappers directly (Unicorn); --abi enters each real patched
CALL instruction with the caller's RSP%16=0 and checks the exact continuation and home space, so
the redirection itself is exercised.  --build-only never imports Unicorn and only builds the
fixtures and the patch (restricted hosts).

D5_KIT=/Volumes/Data/Projects/D5/Local/Worktrees/engine-ext-vocab2 \
 /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \
 evility/offline_proof_ex05d.py --json evility/results/ex05d-behavior.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
from abi_engine_ex05c import UNIT, OTHER, REC, OREC, AGG, ACTION, execute

ORIGINAL = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
                'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
ORIGINAL_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
NAMES = ('potency', 'stats', 'growth', 'dealt', 'taken', 'flight', 'flight', 'hit', 'status_chance', 'conversion')
BATTLE_TABLE, STRIDE = 0x141BA33B0, 4704
EXTRA = (0x400090000, 0x400098000, 0x4000A0000, 0x4000A8000)


def unit(ids=(), *, team=0, char_id=10, type_code=1, hp=None, max_hp=None,
         sp=None, base=None, maxima=None, potency=50, weapon_category=None):
    b = bytearray(0x4800)
    struct.pack_into('<i', b, 0x3030, len(ids))
    for i, evid in enumerate(sorted(ids)):
        struct.pack_into('<I', b, 0x2f30 + i * 4, evid)
    struct.pack_into('<8H', b, 0x3068, *([potency] * 8))
    struct.pack_into('<i', b, 0x2e04, char_id)
    b[0x2e32] = team
    b[0x2e25] = type_code
    if weapon_category is not None:
        struct.pack_into('<i', b, 312, 1)          # an item in weapon slot 0
        struct.pack_into('<B', b, 342, weapon_category)
    if hp is not None:
        struct.pack_into('<q', b, 0x2cc8, hp)
    if max_hp is not None:
        struct.pack_into('<q', b, 0x2cd8, max_hp)
    if sp is not None:
        struct.pack_into('<q', b, 0x2cd0, sp)
    if base is not None:
        struct.pack_into('<8q', b, 0x2d18, *base)
    if maxima is not None:
        struct.pack_into('<8q', b, 0x2cd8, *maxima)
    return b


def record(ptr, *, x=60.0, z=60.0, slot=0, kind=0, active=1):
    b = bytearray(STRIDE)
    struct.pack_into('<Q', b, 0x240, ptr)
    struct.pack_into('<f', b, 8, x)
    struct.pack_into('<f', b, 16, z)
    struct.pack_into('<B', b, 0x2e8, active)
    struct.pack_into('<h', b, 0x2ee, -1)
    struct.pack_into('<h', b, 0x2f4, kind)
    struct.pack_into('<H', b, 756, slot)
    return b


def cell(n):
    """a world coordinate on cell n (the game's formula is trunc(world / 12.0f))"""
    return n * 12.0 + 6.0


def fixture(subject, *, subject_cell=(5, 5), on_map=True, other=None, other_cell=(10, 10),
            others=(), action_element=None, action_targets=None, regions=(), subject_is_other=False):
    """Complete mapped inputs.

    subject:      the unit record the family acts for
    other:        the other participant (defender for dealt/hit, attacker for taken)
    others:       [(unit bytes, cell, slot)] extra units placed on the battle map

    The stat/potency/conversion families read the subject from rcx; `taken` reads it from its
    *third* argument (r8, the D record), so those cases pass subject_is_other=True: the D record
    then names the subject and the A record names the attacker, the way the game calls it.
    """
    def setup(write):
        table = bytearray(256 * STRIDE)
        subject_rec = record(UNIT, x=cell(subject_cell[0]), z=cell(subject_cell[1]), slot=0)
        side_rec = record(OTHER, x=cell(other_cell[0]), z=cell(other_cell[1]), slot=1)
        if on_map:
            table[0:STRIDE] = subject_rec
        if other is not None:
            table[STRIDE:2 * STRIDE] = side_rec
        for i, (data, near, slot) in enumerate(others):
            ptr = EXTRA[i]
            table[slot * STRIDE:(slot + 1) * STRIDE] = record(ptr, x=cell(near[0]), z=cell(near[1]),
                                                             slot=slot)
            write(ptr, data)
        write(BATTLE_TABLE, table)
        # the caller's argument records: `taken` reads its subject from the D record (r8)
        if subject_is_other:
            write(REC, side_rec if other is not None else bytes(STRIDE))
            write(OREC, subject_rec)
        else:
            write(REC, subject_rec)
            write(OREC, side_rec if other is not None else bytes(STRIDE))
        write(UNIT, subject)
        if other is not None:
            write(OTHER, other)
        # the action context is addressed at +0x276BC / +160536, past the engine's first page:
        # both fields are always materialised so a zero context is a real read, not an unmapped one
        write(ACTION, bytes(0x300))
        write(ACTION + 0x276BC, struct.pack('<B', action_element or 0))
        write(ACTION + 160536, struct.pack('<h', action_targets or 0))
        for address, data in regions:
            write(address, data)
    return setup


def cases(ev):
    """Independent plans; every fixture is constructed without a Uc instance."""
    plans = []
    base_stats = [100, 200, 300, 301, 500, 600, 701, 803]

    # ---------------------------------------------------------------- runtime magnitudes
    scaled = {
        7500: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 20, 'per': 'adjacent_ally'}]},
        7501: {'family': 'potency', 'effects': [{'stat': 'atk', 'value': 20, 'per': 'adjacent_ally'}]},
        7502: {'family': 'dealt', 'effects': [{'value': 10, 'per': 'adjacent_ally'}]},
        7503: {'family': 'dealt', 'effects': [{'value': 3, 'per': 'map_enemy'}]},
        7504: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 5, 'per': 'map_any'}]},
        7505: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 30000, 'per': 'map_any'}]},
        7506: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 20}]},
        7507: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 20, 'per': 'adjacent_enemy'}]},
        7508: {'family': 'taken', 'effects': [{'value': 10, 'per': 'adjacent_ally'}]},
        7509: {'family': 'dealt', 'effects': [{'value': 4, 'per': 'map_ally'}]},
    }
    ally_a = unit(team=0)
    ally_b = unit(team=0)
    enemy = unit(team=1)
    enemy_b = unit(team=1)
    two_allies = ((ally_a, (6, 5), 2), (ally_b, (4, 5), 3))
    one_ally = ((ally_a, (6, 5), 2),)
    one_enemy = ((enemy, (6, 5), 2),)
    enemies_afar = ((enemy, (12, 12), 2), (enemy_b, (13, 13), 3))
    mixed_afar = ((ally_a, (2, 2), 2), (enemy, (12, 12), 3))

    def run(name, family, expect_field, expected, **kw):
        return dict(name=name, family=family, field=expect_field, expected=expected, **kw)

    checks = [
        run('scaled-stats-per-adjacent-ally-one', 'stats', 'aggregate', [0, 0, 20] + [0] * 15,
            ids=(7500,), fixture=fixture(unit((7500,)), others=one_ally)),
        run('scaled-stats-per-adjacent-ally-two', 'stats', 'aggregate', [0, 0, 40] + [0] * 15,
            ids=(7500,), fixture=fixture(unit((7500,)), others=two_allies)),
        run('scaled-stats-ally-two-panels-away', 'stats', 'aggregate', [0] * 18,
            ids=(7500,), fixture=fixture(unit((7500,)), others=((ally_a, (7, 5), 2),))),
        run('scaled-stats-enemy-is-not-an-ally', 'stats', 'aggregate', [0] * 18,
            ids=(7500,), fixture=fixture(unit((7500,)), others=one_enemy)),
        run('scaled-stats-not-on-the-battle-map', 'stats', 'aggregate', [0] * 18,
            ids=(7500,), fixture=fixture(unit((7500,)), on_map=False, others=two_allies)),
        run('scaled-potency-per-adjacent-ally', 'potency', 'output', 90,
            ids=(7501,), fixture=fixture(unit((7501,)), others=two_allies)),
        run('scaled-dealt-per-adjacent-ally', 'dealt', 'output', 10,
            ids=(7502,), fixture=fixture(unit((7502,)), other=unit(), others=one_ally)),
        run('scaled-dealt-per-map-enemy', 'dealt', 'output', 6,
            ids=(7503,), fixture=fixture(unit((7503,)), other=unit(), others=enemies_afar)),
        run('scaled-dealt-per-map-enemy-with-allies-present', 'dealt', 'output', 6,
            ids=(7503,), fixture=fixture(unit((7503,)), other=unit(), others=enemies_afar + ((ally_a, (2, 2), 4),))),
        # the other participant of a dealt attack is itself an ally here, so it counts too
        run('scaled-dealt-per-map-ally', 'dealt', 'output', 8,
            ids=(7509,), fixture=fixture(unit((7509,)), other=unit(), others=mixed_afar)),
        run('scaled-stats-per-map-any-counts-every-unit', 'stats', 'aggregate', [0, 0, 10] + [0] * 15,
            ids=(7504,), fixture=fixture(unit((7504,)), others=mixed_afar)),
        run('scaled-stats-clamped-to-the-effect-word', 'stats', 'aggregate', [0, 0, 32767] + [0] * 15,
            ids=(7505,), fixture=fixture(unit((7505,)), others=mixed_afar)),
        run('scaled-fixed-value-is-unchanged', 'stats', 'aggregate', [0, 0, 20] + [0] * 15,
            ids=(7506,), fixture=fixture(unit((7506,)), others=two_allies)),
        run('scaled-stats-adjacent-enemy-relation', 'stats', 'aggregate', [0, 0, 20] + [0] * 15,
            ids=(7507,), fixture=fixture(unit((7507,)), others=one_enemy)),
        # taken scales the in/out percent: 50 * (100 + 10) / 100
        run('scaled-taken-per-adjacent-ally', 'taken', 'output', 55, ids=(7508,),
            fixture=fixture(unit((7508,)), subject_is_other=True, other=unit(), others=one_ally)),
    ]
    plans.append(('runtime-magnitudes', scaled, checks))

    # ---------------------------------------------------------------- other-side HP
    hp_rows = {
        7510: {'family': 'dealt', 'effects': [{'value': 30}],
               'condition': {'kind': 'other_hp_below', 'id': 50}},
        7511: {'family': 'dealt', 'effects': [{'value': 30}],
               'condition': {'kind': 'other_hp_above', 'id': 100}},
        7512: {'family': 'taken', 'effects': [{'value': 50}],
               'condition': {'kind': 'other_hp_below', 'id': 50}},
    }
    def defender(hp, max_hp):
        return unit(hp=hp, max_hp=max_hp)
    hp_checks = [
        run('other-hp-below-fires-under-threshold', 'dealt', 'output', 30, ids=(7510,),
            fixture=fixture(unit((7510,)), other=defender(40, 100))),
        run('other-hp-below-fires-at-just-under', 'dealt', 'output', 30, ids=(7510,),
            fixture=fixture(unit((7510,)), other=defender(49, 100))),
        run('other-hp-below-does-not-fire-at-threshold', 'dealt', 'output', 0, ids=(7510,),
            fixture=fixture(unit((7510,)), other=defender(50, 100))),
        run('other-hp-below-does-not-fire-above', 'dealt', 'output', 0, ids=(7510,),
            fixture=fixture(unit((7510,)), other=defender(60, 100))),
        run('other-hp-below-no-other-side', 'dealt', 'output', 0, ids=(7510,),
            fixture=fixture(unit((7510,)))),
        run('other-hp-above-fires-at-max', 'dealt', 'output', 30, ids=(7511,),
            fixture=fixture(unit((7511,)), other=defender(100, 100))),
        run('other-hp-above-does-not-fire-below-max', 'dealt', 'output', 0, ids=(7511,),
            fixture=fixture(unit((7511,)), other=defender(90, 100))),
        # taken: the subject is the defender and "the other side" is the attacking unit
        run('other-hp-below-on-taken-reads-the-attacker', 'taken', 'output', 75, ids=(7512,),
            fixture=fixture(unit((7512,)), subject_is_other=True, other=defender(40, 100))),
        run('other-hp-below-on-taken-attacker-full', 'taken', 'output', 50, ids=(7512,),
            fixture=fixture(unit((7512,)), subject_is_other=True, other=defender(100, 100))),
    ]
    plans.append(('other-side-hp-thresholds', hp_rows, hp_checks))

    # ---------------------------------------------------------------- element / target count
    count_rows = {
        7520: {'family': 'dealt', 'effects': [{'value': 20}],
               'condition': {'kind': 'element_any'}},
        7521: {'family': 'taken', 'effects': [{'value': 50}],
               'condition': {'kind': 'element_any'}},
        7522: {'family': 'dealt', 'effects': [{'value': 30}],
               'condition': {'kind': 'target_count', 'id': 1}},
        7523: {'family': 'dealt', 'effects': [{'value': 30}],
               'condition': {'kind': 'target_count_min', 'id': 2}},
    }
    count_checks = [
        run('element-any-fire-attack', 'dealt', 'output', 20, ids=(7520,),
            fixture=fixture(unit((7520,)), other=unit(), action_element=1)),
        run('element-any-star-attack', 'dealt', 'output', 20, ids=(7520,),
            fixture=fixture(unit((7520,)), other=unit(), action_element=4)),
        run('element-any-non-elemental', 'dealt', 'output', 0, ids=(7520,),
            fixture=fixture(unit((7520,)), other=unit(), action_element=0)),
        run('element-any-zero-action-context', 'dealt', 'output', 0, ids=(7520,),
            fixture=fixture(unit((7520,)), other=unit())),
        run('element-any-on-taken', 'taken', 'output', 75, ids=(7521,),
            fixture=fixture(unit((7521,)), subject_is_other=True, other=unit(), action_element=2)),
        run('element-any-on-taken-non-elemental', 'taken', 'output', 50, ids=(7521,),
            fixture=fixture(unit((7521,)), subject_is_other=True, other=unit(), action_element=0)),
        run('target-count-one-of-one', 'dealt', 'output', 30, ids=(7522,),
            fixture=fixture(unit((7522,)), other=unit(), action_targets=1)),
        run('target-count-one-of-two', 'dealt', 'output', 0, ids=(7522,),
            fixture=fixture(unit((7522,)), other=unit(), action_targets=2)),
        run('target-count-min-two-of-two', 'dealt', 'output', 30, ids=(7523,),
            fixture=fixture(unit((7523,)), other=unit(), action_targets=2)),
        run('target-count-min-two-of-one', 'dealt', 'output', 0, ids=(7523,),
            fixture=fixture(unit((7523,)), other=unit(), action_targets=1)),
        run('target-count-zero-action-context', 'dealt', 'output', 0, ids=(7522,),
            fixture=fixture(unit((7522,)), other=unit())),
    ]
    plans.append(('element-any-and-target-count', count_rows, count_checks))

    # ---------------------------------------------------------------- current-SP conversion
    conv_rows = {
        7530: {'family': 'conversion', 'effects': [{'stat': 'atk', 'from': 'sp_current', 'value': 10}]},
        7531: {'family': 'conversion', 'effects': [{'stat': 'int', 'from': 'sp_current', 'value': -50}]},
        7532: {'family': 'conversion', 'effects': [{'stat': 'atk', 'from': 'sp_current', 'value': 10}],
               'condition': {'kind': 'weapon', 'id': 2}},
    }
    initial = [1000] * 8
    conv_checks = [
        run('conversion-current-sp', 'conversion', 'final_stats', [1000, 1000, 1080] + [1000] * 5,
            ids=(7530,), fixture=fixture(unit((7530,), sp=800, base=base_stats, maxima=initial))),
        run('conversion-current-sp-signed', 'conversion', 'final_stats', [1000] * 4 + [950] + [1000] * 3,
            ids=(7531,), fixture=fixture(unit((7531,), sp=100, base=base_stats, maxima=initial))),
        run('conversion-current-sp-zero-sp', 'conversion', 'final_stats', [1000] * 8,
            ids=(7530,), fixture=fixture(unit((7530,), sp=0, base=base_stats, maxima=initial))),
        run('conversion-current-sp-unlearned', 'conversion', 'final_stats', [1000] * 8,
            ids=(), fixture=fixture(unit((), sp=800, base=base_stats, maxima=initial))),
        run('conversion-current-sp-condition-holds', 'conversion', 'final_stats', [1000, 1000, 1080] + [1000] * 5,
            ids=(7532,), fixture=fixture(unit((7532,), sp=800, base=base_stats, maxima=initial,
                                              weapon_category=2))),
        run('conversion-current-sp-condition-fails', 'conversion', 'final_stats', [1000] * 8,
            ids=(7532,), fixture=fixture(unit((7532,), sp=800, base=base_stats, maxima=initial,
                                              weapon_category=1))),
    ]
    for case in conv_checks:
        case['base_expected'] = base_stats
    plans.append(('current-sp-conversion', conv_rows, conv_checks))
    return plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', '--site-entry', action='store_true')
    ap.add_argument('--build-only', action='store_true', help='build every plan without importing Unicorn')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    from d5lib import evility as ev
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    specs = [(name, target, sites) for name, (_, target, sites) in zip(NAMES, ev.WRAPPERS)]
    results, builds = [], []
    for plan_name, rows, checks in cases(ev):
        patched = ev.build_patch(original, rows)
        info = ev.section_info(patched)
        builds.append(dict(plan=plan_name, rows=len(rows), checks=len(checks),
                           section_size=info['size'], patched_sha256=hashlib.sha256(patched).hexdigest()))
        for case in checks:
            family = case['family']
            _, target, sites = next(s for s in specs if s[0] == family)
            for site in sites:
                if args.build_only:
                    regions = []
                    if case.get('fixture'):
                        case['fixture'](lambda addr, data: regions.append((hex(addr), len(data))))
                    results.append(dict(name=case['name'], site=hex(site), fixture_built=True,
                                        regions=regions))
                    continue
                try:
                    detail = execute(patched, info, specs, family, target, site,
                                     ids=case.get('ids', ()), abi=args.abi,
                                     fixture=case.get('fixture'),
                                     out_value=case.get('out_value', 50),
                                     original_rax=case.get('original_rax', 0))
                    if 'base_expected' in case:
                        assert detail['base_stats'] == case['base_expected'], detail['base_stats']
                    got = detail[case.get('field', 'output')]
                    assert got == case['expected'], (got, case['expected'])
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=True, **detail))
                except Exception as exc:
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=False,
                                        error=f'{type(exc).__name__}: {exc}'))
                r = results[-1]
                print(('PASS ' if r['ok'] else 'FAIL ') + case['name'] + f' {site:#x}' +
                      ('' if r['ok'] else ' ' + r['error']))
    passed = args.build_only or all(r['ok'] for r in results)
    report = dict(mode='build-only' if args.build_only else 'abi-site-entry' if args.abi else 'behavior',
                  original_sha256=ORIGINAL_SHA, builds=builds, checks=results, passed=passed,
                  limitations=['Original-game callees are deterministic volatile-clobbering stubs.',
                               'Executed paths only; Windows unwind and native gameplay are not executed.',
                               'The battle-unit table, unit records and action context are synthetic fixtures.',
                               'Build-only is fixture/patch validation, not an emulator pass.'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(results)} fixtures built' if args.build_only else
          f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
