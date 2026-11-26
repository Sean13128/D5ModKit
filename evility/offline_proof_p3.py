"""P3: the four additive evility passes ported from Overlord -- attack power, defence power, move range and
attack/magic range.

Default mode executes the installed wrappers from the game's own patched CALL sites (Unicorn); ``--abi`` enters
each real patched CALL instruction with the caller's RSP%16=0 and checks the exact continuation, the forwarded
stack argument and the home space, so the redirection itself is exercised.  ``--build-only`` never imports
Unicorn and only builds the fixtures and the patch (restricted hosts).

D5_KIT=/Volumes/Data/Projects/D5/Local/Worktrees/p3-evility \\
 /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \\
 evility/offline_proof_p3.py --json evility/results/p3-behavior.json
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
from abi_engine_ex05c import ACTION, AGG, OREC, OTHER, REC, UNIT, execute

ORIGINAL = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
                'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
ORIGINAL_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
# the wrapper names of d5lib/evility.py; these four are the P3 additive passes
FAMILIES = ('power', 'defense_power', 'move', 'range')
BATTLE_TABLE, STRIDE = 0x141BA33B0, 4704
EXTRA = (0x400090000, 0x400098000, 0x4000A0000, 0x4000A8000)


def u32(value):
    """the wrapper returns a 64-bit signed sum; the engine reports the low 32 bits"""
    return value & 0xFFFFFFFF


def unit(ids=(), *, team=0, char_id=10, hp=None, max_hp=None, weapon_category=None, level=None):
    b = bytearray(0x4800)
    struct.pack_into('<i', b, 0x3030, len(ids))
    for i, evid in enumerate(sorted(ids)):
        struct.pack_into('<I', b, 0x2f30 + i * 4, evid)
    struct.pack_into('<8H', b, 0x3068, *([50] * 8))
    struct.pack_into('<i', b, 0x2e04, char_id)
    b[0x2e32] = team
    b[0x2e25] = 1
    if weapon_category is not None:
        struct.pack_into('<i', b, 312, 1)          # an item in weapon slot 0
        struct.pack_into('<B', b, 342, weapon_category)
    if hp is not None:
        struct.pack_into('<q', b, 0x2cc8, hp)
    if max_hp is not None:
        struct.pack_into('<q', b, 0x2cd8, max_hp)
    if level is not None:
        struct.pack_into('<h', b, 0x2dfc, level)
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


def fixture(subject, *, subject_cell=(5, 5), on_map=True, other=None, others=()):
    """Complete mapped inputs; the subject is the unit whose behavior is being asked about."""
    def setup(write):
        table = bytearray(256 * STRIDE)
        table[0:STRIDE] = record(UNIT, x=cell(subject_cell[0]), z=cell(subject_cell[1]), slot=0)
        if other is not None:
            table[STRIDE:2 * STRIDE] = record(OTHER, slot=1)
        for i, (data, near, slot) in enumerate(others):
            ptr = EXTRA[i]
            table[slot * STRIDE:(slot + 1) * STRIDE] = record(ptr, x=cell(near[0]), z=cell(near[1]),
                                                             slot=slot)
            write(ptr, data)
        write(BATTLE_TABLE, table)
        write(REC, record(UNIT))
        write(OREC, record(OTHER))
        write(UNIT, subject)
        write(OTHER, other if other is not None else unit())
        write(ACTION, bytes(0x300))
        write(AGG, bytes(0x100))
    return setup


def cases():
    """Independent plans; every fixture is constructed without a Uc instance."""
    plans = []

    def run(name, family, expected, **kw):
        return dict(name=name, family=family, expected=u32(expected), field='output', **kw)

    # ------------------------------------------------------------------ attack power (damage_attack_bonus_rules)
    power_rows = {
        7400: {'family': 'power', 'effects': [{'value': 30}]},
        7401: {'family': 'power', 'effects': [{'value': -20}]},
        7402: {'family': 'power', 'effects': [{'value': 100}],
               'condition': {'kind': 'hp_below', 'id': 50}},
        7403: {'family': 'power', 'effects': [{'value': 32767}]},
        7404: {'family': 'power', 'effects': [{'value': 5, 'per': 'adjacent_ally'}]},
        7405: {'family': 'power', 'effects': [{'value': 10}, {'value': 15}]},
        7406: {'family': 'power', 'effects': [{'value': 40}],
               'condition': {'kind': 'weapon', 'id': 5}},
    }
    low = dict(hp=20, max_hp=100)
    ally = unit()
    power_checks = [
        run('power-adds-thirty', 'power', 30, ids=(7400,), fixture=fixture(unit((7400,)))),
        run('power-unlearned-is-unchanged', 'power', 0, ids=(), fixture=fixture(unit(()))),
        run('power-negative-subtracts', 'power', -20, ids=(7401,), fixture=fixture(unit((7401,)))),
        run('power-two-effects-add', 'power', 25, ids=(7405,), fixture=fixture(unit((7405,)))),
        run('power-signed-sixteen-bit-boundary', 'power', 32767, ids=(7403,),
            fixture=fixture(unit((7403,)))),
        run('power-condition-holds-under-the-threshold', 'power', 100, ids=(7402,),
            fixture=fixture(unit((7402,), **low))),
        run('power-condition-above-the-threshold', 'power', 0, ids=(7402,),
            fixture=fixture(unit((7402,), hp=80, max_hp=100))),
        run('power-weapon-condition-holds', 'power', 40, ids=(7406,),
            fixture=fixture(unit((7406,), weapon_category=5))),
        run('power-weapon-condition-wrong-weapon', 'power', 0, ids=(7406,),
            fixture=fixture(unit((7406,), weapon_category=2))),
        run('power-per-adjacent-ally-counts-two', 'power', 10, ids=(7404,),
            fixture=fixture(unit((7404,)), others=((ally, (5, 6), 2), (ally, (4, 5), 3)))),
        run('power-per-adjacent-ally-none-nearby', 'power', 0, ids=(7404,),
            fixture=fixture(unit((7404,)), others=((ally, (5, 9), 2),))),
        # the row belongs to the attacker: another unit carrying it changes nothing here
        run('power-on-another-unit-does-nothing', 'power', 0, ids=(),
            fixture=fixture(unit(()), other=unit((7400,)))),
    ]
    plans.append(('attack-power', power_rows, power_checks))

    # ------------------------------------------------------------------ defence power (damage_defence_bonus_rules)
    dpower_rows = {
        7410: {'family': 'defense_power', 'effects': [{'value': 20}]},
        7411: {'family': 'defense_power', 'effects': [{'value': -35}]},
        7412: {'family': 'defense_power', 'effects': [{'value': 50}],
               'condition': {'kind': 'enemy_adj', 'id': 1}},
        7413: {'family': 'defense_power', 'effects': [{'value': 10}], 'condition': {'kind': 'level', 'id': 100}},
    }
    enemy = unit(team=1)
    dpower_checks = [
        run('defense-power-adds-twenty', 'defense_power', 20, ids=(7410,), fixture=fixture(unit((7410,)))),
        run('defense-power-unlearned-is-unchanged', 'defense_power', 0, ids=(), fixture=fixture(unit(()))),
        run('defense-power-negative-subtracts', 'defense_power', -35, ids=(7411,),
            fixture=fixture(unit((7411,)))),
        run('defense-power-enemy-adjacent-fires', 'defense_power', 50, ids=(7412,),
            fixture=fixture(unit((7412,)), others=((enemy, (5, 6), 2),))),
        run('defense-power-no-enemy-adjacent', 'defense_power', 0, ids=(7412,),
            fixture=fixture(unit((7412,)), others=((enemy, (7, 7), 2),))),
        run('defense-power-level-condition-holds', 'defense_power', 10, ids=(7413,),
            fixture=fixture(unit((7413,), level=120))),
        run('defense-power-level-condition-fails', 'defense_power', 0, ids=(7413,),
            fixture=fixture(unit((7413,), level=90))),
    ]
    plans.append(('defence-power', dpower_rows, dpower_checks))

    # ------------------------------------------------------------------ move range (menus_env_move_range)
    move_rows = {
        7420: {'family': 'move', 'effects': [{'value': 1}]},
        7421: {'family': 'move', 'effects': [{'value': -2}]},
        7422: {'family': 'move', 'effects': [{'value': 3}], 'condition': {'kind': 'self_monster'}},
        7423: {'family': 'move', 'effects': [{'value': 1, 'per': 'adjacent_ally'}]},
    }
    move_checks = [
        run('move-adds-one-panel', 'move', 1, ids=(7420,), fixture=fixture(unit((7420,)))),
        run('move-unlearned-is-unchanged', 'move', 0, ids=(), fixture=fixture(unit(()))),
        run('move-negative-subtracts', 'move', -2, ids=(7421,), fixture=fixture(unit((7421,)))),
        run('move-per-adjacent-ally-counts-one', 'move', 1, ids=(7423,),
            fixture=fixture(unit((7423,)), others=((ally, (5, 6), 2),))),
    ]
    plans.append(('move-range', move_rows, move_checks))

    # ------------------------------------------------------------------ attack/magic range (0x1401EC5C0)
    range_rows = {
        7430: {'family': 'range', 'effects': [{'value': 2}]},
        7431: {'family': 'range', 'effects': [{'value': -1}]},
        7432: {'family': 'range', 'effects': [{'value': 1}], 'condition': {'kind': 'ally_adj', 'id': 1}},
    }
    range_checks = [
        run('range-adds-two-panels', 'range', 2, ids=(7430,), fixture=fixture(unit((7430,)))),
        run('range-unlearned-is-unchanged', 'range', 0, ids=(), fixture=fixture(unit(()))),
        run('range-negative-subtracts', 'range', -1, ids=(7431,), fixture=fixture(unit((7431,)))),
        run('range-ally-adjacent-fires', 'range', 1, ids=(7432,),
            fixture=fixture(unit((7432,)), others=((ally, (6, 5), 2),))),
        run('range-ally-not-adjacent', 'range', 0, ids=(7432,),
            fixture=fixture(unit((7432,)), others=((ally, (8, 5), 2),))),
    ]
    plans.append(('attack-magic-range', range_rows, range_checks))
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
    specs = [(name, ev.wrapper(name)[1], ev.wrapper(name)[2]) for name in ev.WRAPPER_NAMES.values()]
    results, builds = [], []
    for plan_name, rows, checks in cases():
        patched = ev.build_patch(original, rows)
        info = ev.section_info(patched)
        builds.append(dict(plan=plan_name, rows=len(rows), checks=len(checks),
                           section_size=info['size'],
                           patched_sha256=hashlib.sha256(patched).hexdigest()))
        for case in checks:
            family = case['family']
            _, target, sites = ev.wrapper(family)
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
                                     out_value=0, original_rax=0)
                    got = detail[case.get('field', 'output')]
                    assert got == case['expected'], (hex(got), hex(case['expected']))
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=True,
                                        **detail))
                except Exception as exc:
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=False,
                                        error=f'{type(exc).__name__}: {exc}'))
                r = results[-1]
                print(('PASS ' if r['ok'] else 'FAIL ') + case['name'] + f' {site:#x}' +
                      ('' if r['ok'] else ' ' + r['error']))
    passed = args.build_only or all(r['ok'] for r in results)
    report = dict(mode='build-only' if args.build_only else 'abi-site-entry' if args.abi else 'behavior',
                  original_sha256=ORIGINAL_SHA, builds=builds, checks=results, passed=passed,
                  limitations=[
                      'Original-game callees are deterministic volatile-clobbering stubs that return 0; the '
                      'value under test is the extension\'s own contribution added to it.',
                      'Executed paths only; Windows unwind and native gameplay are not executed.',
                      'The battle-unit table, unit records and action context are synthetic fixtures.',
                      'These rows are handed no action context, so only unit-state conditions are modelled; '
                      'action-context conditions on an additive row evaluate false by design.',
                      'Build-only is fixture/patch validation, not an emulator pass.'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(results)} fixtures built' if args.build_only else
          f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
