"""OLEFFECTS: the four Overlord effects ported after P3, plus the `squad` scale for stat_per_squad_unit.

Default mode executes the installed wrappers from the game's own patched CALL sites (Unicorn); ``--abi`` enters
each real patched CALL instruction with the caller's RSP%16=0 and checks the exact continuation, the forwarded
stack argument and the home space.  ``--build-only`` never imports Unicorn.

Which effect is which site (Overlord's name -> this runtime's family -> the game's own site):

  permanent_revenge      permanent_revenge      turn_per_unit_end_round_upkeep 0x1401E5AF0, site 0x1405F8FFC
  block_overload         block_overload         cmdmenu_preds_p_15dbf0 0x14015DBF0, all 11 static sites
  steal_on_kill_percent  steal_on_kill_percent  the defeat path's victim-eligibility call, site 0x1401AF6A2
  sp_drain_per_turn      sp_drain_per_turn      the SP-recovery percentage call, site 0x140552083
  stat_per_squad_unit    stats + per=squad      no site of its own: scale kind 9 (squad helper 0x1401D3990)

D5_KIT=/Volumes/Data/Projects/D5/Local/Worktrees/oleffects \\
 /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \\
 evility/offline_proof_oleffects.py --json evility/results/oleffects-behavior.json
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
FAMILIES = ('revenge', 'overload', 'steal', 'sp_drain')
BATTLE_TABLE, STRIDE = 0x141BA33B0, 4704
EXTRA = (0x400090000, 0x400098000, 0x4000A0000, 0x4000A8000)
# the game functions the extension calls itself, stubbed to `ret` by the engine's stub_returns
REVENGE_GAUGE, REVENGE_STATUS = 0x140161A20, 0x140161790
SQUAD_MEMBERS = 0x1401D3990
SP_REGEN = 0x1401EE010


def u32(value):
    return value & 0xFFFFFFFF


def unit(ids=(), *, team=0, char_id=10, hp=None, max_hp=None, level=None, squad=None):
    """a unit record fixture; `squad` is (squad id byte, assignment-count gate byte)"""
    b = bytearray(0x4800)
    struct.pack_into('<i', b, 0x3030, len(ids))
    for i, evid in enumerate(sorted(ids)):
        struct.pack_into('<I', b, 0x2f30 + i * 4, evid)
    struct.pack_into('<8H', b, 0x3068, *([50] * 8))
    struct.pack_into('<i', b, 0x2e04, char_id)
    b[0x2e32] = team
    b[0x2e25] = 1
    if hp is not None:
        struct.pack_into('<q', b, 0x2cc8, hp)
    if max_hp is not None:
        struct.pack_into('<q', b, 0x2cd8, max_hp)
    if level is not None:
        struct.pack_into('<h', b, 0x2dfc, level)
    if squad is not None:
        b[0x30a0] = squad[0] & 0xFF
        b[0x30a1] = squad[1] & 0xFF
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
    return n * 12.0 + 6.0


def fixture(subject, *, subject_cell=(5, 5), other=None, others=()):
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
    plans = []

    def run(name, family, expected, *, calls=(), **kw):
        if family == 'revenge':
            # the two native functions the revenge wrapper calls are stubs whose answer does not matter;
            # whether they were *called* is asserted through the call edges
            kw.setdefault('stub', {REVENGE_GAUGE: 0, REVENGE_STATUS: 0})
        return dict(name=name, family=family, expected=u32(expected), field=kw.pop('field', 'output'),
                    expect_calls=tuple(hex(a) for a in calls), **kw)

    # ---------------------------------------------------------------- permanent revenge (end-of-round upkeep)
    rev_rows = {
        7600: {'family': 'permanent_revenge'},
        7601: {'family': 'permanent_revenge', 'condition': {'kind': 'hp_below', 'id': 50}},
    }
    both = (REVENGE_GAUGE, REVENGE_STATUS)
    rev_checks = [
        run('revenge-applies-the-native-pair', 'revenge', 0, ids=(7600,), calls=both,
            fixture=fixture(unit((7600,)))),
        run('revenge-unlearned-does-nothing', 'revenge', 0, fixture=fixture(unit(()))),
        # vanilla 150/6145/5026 already issue the pair inside the same function: never twice
        run('revenge-skipped-when-150-is-learned', 'revenge', 0, ids=(150, 7600),
            fixture=fixture(unit((150, 7600)))),
        run('revenge-skipped-when-6145-is-learned', 'revenge', 0, ids=(6145, 7600),
            fixture=fixture(unit((6145, 7600)))),
        run('revenge-skipped-when-5026-is-learned', 'revenge', 0, ids=(5026, 7600),
            fixture=fixture(unit((5026, 7600)))),
        run('revenge-condition-holds', 'revenge', 0, ids=(7601,), calls=both,
            fixture=fixture(unit((7601,), hp=10, max_hp=100))),
        run('revenge-condition-fails', 'revenge', 0, ids=(7601,),
            fixture=fixture(unit((7601,), hp=90, max_hp=100))),
        # the original's own answer comes back untouched
        run('revenge-original-answer-is-preserved', 'revenge', 1234, ids=(7600,), calls=both,
            vanilla_rax=1234, fixture=fixture(unit((7600,)))),
    ]
    plans.append(('permanent-revenge', rev_rows, rev_checks))

    # ---------------------------------------------------------------- block overload (11 static sites)
    ov_rows = {7610: {'family': 'block_overload'},
               7611: {'family': 'block_overload', 'condition': {'kind': 'level', 'id': 100}}}
    ov_checks = [
        run('overload-blocked', 'overload', 0, ids=(7610,), vanilla_rax=77, fixture=fixture(unit((7610,)))),
        run('overload-unlearned-keeps-the-vanilla-id', 'overload', 77, vanilla_rax=77,
            fixture=fixture(unit(()))),
        run('overload-condition-holds', 'overload', 0, ids=(7611,), vanilla_rax=77,
            fixture=fixture(unit((7611,), level=120))),
        run('overload-condition-fails', 'overload', 77, ids=(7611,), vanilla_rax=77,
            fixture=fixture(unit((7611,), level=90))),
        run('overload-other-unit-is-not-affected', 'overload', 77, vanilla_rax=77,
            fixture=fixture(unit(()), other=unit((7610,)))),
    ]
    plans.append(('block-overload', ov_rows, ov_checks))

    # ---------------------------------------------------------------- steal on kill
    st_rows = {
        7620: {'family': 'steal_on_kill_percent', 'effects': [{'value': 30}]},
        7621: {'family': 'steal_on_kill_percent', 'effects': [{'value': -25}]},
        7622: {'family': 'steal_on_kill_percent', 'effects': [{'value': 5, 'per': 'adjacent_ally'}]},
        7623: {'family': 'steal_on_kill_percent', 'effects': [{'value': 100}]},
    }
    ally = unit()
    st_checks = [
        run('steal-adds-thirty', 'steal', 50, ids=(7620,), chance=20, fixture=fixture(unit((7620,)))),
        run('steal-unlearned-is-unchanged', 'steal', 20, chance=20, fixture=fixture(unit(()))),
        run('steal-negative-subtracts', 'steal', 0, ids=(7621,), chance=20,
            fixture=fixture(unit((7621,)))),
        run('steal-clamped-at-one-hundred', 'steal', 100, ids=(7623,), chance=20,
            fixture=fixture(unit((7623,)))),
        run('steal-per-adjacent-ally-counts-two', 'steal', 30, ids=(7622,), chance=20,
            fixture=fixture(unit((7622,)), others=((ally, (5, 6), 2), (ally, (4, 5), 3)))),
        run('steal-per-adjacent-ally-none-nearby', 'steal', 20, ids=(7622,), chance=20,
            fixture=fixture(unit((7622,)), others=((ally, (5, 9), 2),))),
        run('steal-victim-is-not-the-subject', 'steal', 20, ids=(), chance=20,
            fixture=fixture(unit(()), other=unit((7620,)))),
    ]
    plans.append(('steal-on-kill', st_rows, st_checks))

    # ---------------------------------------------------------------- SP drain per turn
    sp_rows = {
        7630: {'family': 'sp_drain_per_turn', 'effects': [{'value': 12}]},
        7631: {'family': 'sp_drain_per_turn', 'effects': [{'value': -5}]},
        7632: {'family': 'sp_drain_per_turn', 'effects': [{'value': 2, 'per': 'squad'}]},
    }
    sp_checks = [
        run('sp-drain-adds-twelve', 'sp_drain', 17, ids=(7630,), regen=5, fixture=fixture(unit((7630,)))),
        run('sp-drain-unlearned-is-unchanged', 'sp_drain', 5, regen=5, fixture=fixture(unit(()))),
        run('sp-drain-negative-restores', 'sp_drain', 0, ids=(7631,), regen=5,
            fixture=fixture(unit((7631,)))),
        run('sp-drain-per-squad-unit', 'sp_drain', 11, ids=(7632,), regen=5,
            stub={SQUAD_MEMBERS: 3}, fixture=fixture(unit((7632,), squad=(2, 1)))),
        run('sp-drain-no-squad-assignment-counts-zero', 'sp_drain', 5, ids=(7632,), regen=5,
            stub={SQUAD_MEMBERS: 3}, fixture=fixture(unit((7632,)))),
    ]
    plans.append(('sp-drain-per-turn', sp_rows, sp_checks))

    # ---------------------------------------------------------------- stat_per_squad_unit (scale kind 9)
    sq_rows = {
        7640: {'family': 'stats', 'effects': [{'stat': 'all', 'value': 2, 'per': 'squad'}]},
        7641: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 5, 'per': 'squad'}]},
    }
    def agg_at(index):
        return dict(field='aggregate_index', index=index)
    sq_checks = [
        dict(name='squad-scale-adds-two-per-member-to-every-stat', family='stats', ids=(7640,),
             expected=8, **agg_at(2), stub={SQUAD_MEMBERS: 4},
             fixture=fixture(unit((7640,), squad=(3, 1)))),
        dict(name='squad-scale-unlearned-is-unchanged', family='stats', expected=0, **agg_at(2),
             stub={SQUAD_MEMBERS: 4}, fixture=fixture(unit((), squad=(3, 1)))),
        dict(name='squad-scale-no-assignment-counts-zero', family='stats', ids=(7640,), expected=0,
             **agg_at(2), stub={SQUAD_MEMBERS: 4}, fixture=fixture(unit((7640,)))),
        dict(name='squad-scale-negative-squad-id-counts-zero', family='stats', ids=(7640,), expected=0,
             **agg_at(2), stub={SQUAD_MEMBERS: 4}, fixture=fixture(unit((7640,), squad=(-1, 1)))),
        dict(name='squad-scale-one-stat-only', family='stats', ids=(7641,), expected=15, **agg_at(2),
             stub={SQUAD_MEMBERS: 3}, fixture=fixture(unit((7641,), squad=(0, 1)))),
    ]
    plans.append(('stat-per-squad-unit', sq_rows, sq_checks))

    # ---------------------------------------------------------------- power + action context (OLEFFECTS)
    # Overlord's power_percent supports the attack-element conditions; wrap_power now hands the action
    # context (r9 at the site) to the evaluator, so the element kinds work there too.
    pw_rows = {
        7650: {'family': 'power', 'effects': [{'value': 25}],
               'condition': {'kind': 'element', 'id': 1}},
        7651: {'family': 'power', 'effects': [{'value': 40}],
               'condition': {'kind': 'element_any'}},
    }
    def element_ctx(value, base=0x400060000 + 0x27000):
        page = bytearray(0x800)
        page[0x276bc - 0x27000] = value
        return {base: page}
    pw_checks = [
        run('power-element-condition-fires-on-fire', 'power', 25, ids=(7650,),
            preset=element_ctx(1), fixture=fixture(unit((7650,)))),
        run('power-element-condition-ignores-wind', 'power', 0, ids=(7650,),
            preset=element_ctx(2), fixture=fixture(unit((7650,)))),
        run('power-element-any-fires-on-star', 'power', 40, ids=(7651,),
            preset=element_ctx(4), fixture=fixture(unit((7651,)))),
        run('power-element-any-not-on-none', 'power', 0, ids=(7651,),
            preset=element_ctx(0), fixture=fixture(unit((7651,)))),
    ]
    plans.append(('power-action-context', pw_rows, pw_checks))
    return plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', '--site-entry', action='store_true')
    ap.add_argument('--build-only', action='store_true')
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
                    stub_returns = dict(case.get('stub') or {})
                    detail = execute(patched, info, specs, family, target, site,
                                     ids=case.get('ids', ()), abi=args.abi,
                                     fixture=case.get('fixture'),
                                     out_value=0,
                                     original_rax=case.get('vanilla_rax', case.get('regen', 0)),
                                     unit_args={'rbx': UNIT, 'rsi': case['chance']} if family == 'steal' else None,
                                     stub_returns=stub_returns, preset=case.get('preset'))
                    if 'index' in case:
                        got = detail['aggregate'][case['index']]
                    else:
                        got = detail[case.get('field', 'output')]
                    assert got == case['expected'], f'{got!r} != {case["expected"]!r}'
                    missing = [c for c in case.get('expect_calls', ()) if c not in detail['call_edges']]
                    assert not missing, f'expected calls not made: {missing}'
                    wasted = [c for c in (REVENGE_GAUGE, REVENGE_STATUS) if family == 'revenge'
                              and hex(c) in detail['call_edges'] and hex(c) not in case['expect_calls']]
                    assert not wasted, f'native revenge pair issued when it should not be: {wasted}'
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
                      'Original-game callees are deterministic stubs: the wrapped function returns a fixed '
                      'value and the two native revenge functions plus the squad helper are stubs whose return '
                      'the case controls.  What is proven is our contribution and the call/ABI contract.',
                      'Executed paths only; Windows unwind and native gameplay are not executed.',
                      'The battle-unit table, unit records and action context are synthetic fixtures.',
                      'The revenge wrapper is entered from its one static call site; the pair is asserted by '
                      'the call edges it makes, not by observing the game\'s status record.',
                      'The steal family\'s effect is the caller-visible esi; the victim-eligibility callee is '
                      'stubbed, so the item transfer it gates is not executed.',
                      'Build-only is fixture/patch validation, not an emulator pass.'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(results)} fixtures built' if args.build_only else
          f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
