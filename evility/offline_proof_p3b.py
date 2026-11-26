"""P3b: several rows per evility id (Overlord's model), proven offline.

One evility id may now carry more than one row: each row has its own family, its own conditions and its own
magnitudes, and every consumer walks the whole run of rows that share an id and adds them up.  That is the
same model as Overlord's `evilities.ini` (`[<id> <label>]`, one effect per section, additive), and it is what
real D4/DD2 rows need: two magnitudes of different kinds on one id, or one family twice under two conditions.

Default mode executes the installed wrappers from the game's own patched CALL sites (Unicorn); ``--abi``
enters each real patched CALL instruction with the caller's RSP%16=0 and checks the exact continuation, the
forwarded stack arguments and the home space.  ``--build-only`` never imports Unicorn.

D5_KIT=/Volumes/Data/Projects/D5/Local/Worktrees/p3b-multieffect \\
 /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \\
 evility/offline_proof_p3b.py --json evility/results/p3b-behavior.json
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
BATTLE_TABLE, STRIDE = 0x141BA33B0, 4704
PROVIDER = 0x400080000
# every family the multi-row plans touch, so one plan can be checked through several passes
FAMILIES = ('potency', 'stats', 'move', 'range', 'power', 'defense_power', 'dealt', 'taken')


def u32(value):
    return value & 0xFFFFFFFF


def unit(ids=(), *, team=0, char_id=10, hp=None, max_hp=None):
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
    return b


def record(ptr, *, x=60.0, z=60.0, slot=0, active=1):
    b = bytearray(STRIDE)
    struct.pack_into('<Q', b, 0x240, ptr)
    struct.pack_into('<f', b, 8, x)
    struct.pack_into('<f', b, 16, z)
    struct.pack_into('<B', b, 0x2e8, active)
    struct.pack_into('<h', b, 0x2ee, -1)
    struct.pack_into('<h', b, 0x2f4, slot)
    struct.pack_into('<H', b, 756, slot)
    return b


def cell(n):
    """a world coordinate on cell n (the game's formula is trunc(world / 12.0f))"""
    return n * 12.0 + 6.0


def fixture(subject, *, subject_cell=(5, 5), other=None, others=(), provider=None,
            provider_cell=(5, 6)):
    """Complete mapped inputs.  Slot 0 is the unit REC points at (the attacker for the damage passes), slot 1
    the unit OREC points at (the defender), slot 2 an optional aura provider."""
    def setup(write):
        table = bytearray(256 * STRIDE)
        table[0:STRIDE] = record(UNIT, x=cell(subject_cell[0]), z=cell(subject_cell[1]), slot=0)
        table[STRIDE:2 * STRIDE] = record(OTHER, x=cell(15), z=cell(15), slot=1)
        if provider is not None:
            table[2 * STRIDE:3 * STRIDE] = record(PROVIDER, x=cell(provider_cell[0]),
                                                  z=cell(provider_cell[1]), slot=2)
        for i, (data, near, slot) in enumerate(others):
            ptr = 0x400090000 + i * 0x8000
            table[slot * STRIDE:(slot + 1) * STRIDE] = record(ptr, x=cell(near[0]),
                                                             z=cell(near[1]), slot=slot)
            write(ptr, data)
        write(BATTLE_TABLE, table)
        write(REC, record(UNIT))
        write(OREC, record(OTHER))
        write(UNIT, subject)
        write(OTHER, other if other is not None else unit())
        if provider is not None:
            write(PROVIDER, provider)
        write(ACTION, bytes(0x300))
        write(AGG, bytes(0x100))
    return setup


def cases():
    plans = []

    # ------------------------------------------------------------------ one id, several families and rows
    rows = {
        # two different families on one id: an attack-power penalty and a move bonus
        7300: [{'family': 'potency', 'effects': [{'stat': 'atk', 'value': -30}]},
               {'family': 'move', 'effects': [{'value': 3}]}],
        # the same family twice: the two rows add
        7301: [{'family': 'potency', 'effects': [{'stat': 'atk', 'value': 10}]},
               {'family': 'potency', 'effects': [{'stat': 'def', 'value': 20}]}],
        # the same family twice with different conditions: +3 under 25 % HP, +1 always
        7302: [{'family': 'move', 'effects': [{'value': 3}],
                'condition': {'kind': 'hp_below', 'id': 25}},
               {'family': 'move', 'effects': [{'value': 1}]}],
        # two percentage families that used to share one magnitude
        7303: [{'family': 'dealt', 'effects': [{'value': 10}]},
               {'family': 'taken', 'effects': [{'value': -20}]}],
        # two additive passes on one id (Overlord's power_percent + defense_power_percent)
        7304: [{'family': 'power', 'effects': [{'value': 30}]},
               {'family': 'defense_power', 'effects': [{'value': 20}]}],
        # the same stat through the potency pass and the aggregate pass
        7305: [{'family': 'potency', 'effects': [{'stat': 'atk', 'value': 7}]},
               {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 5}]}],
        # two aura rows on one id (DD2 430): allies deal more, enemies take more
        7306: [{'family': ['aura', 'dealt'], 'effects': [{'value': 10}],
                'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 3, 'id': 7306}]},
               {'family': ['aura', 'taken'], 'effects': [{'value': 20}],
                'conditions': [{'kind': 'near_has', 'of': 2, 'radius': 3, 'id': 7306}]}],
        # one family twice, no conditions: 5 + 6
        7311: [{'family': 'dealt', 'effects': [{'value': 5}]},
               {'family': 'dealt', 'effects': [{'value': 6}]}],
        # a legacy single-row entry, unchanged by all of this
        7310: {'family': 'potency', 'effects': [{'stat': 'atk', 'value': 40}]},
    }
    low = dict(hp=20, max_hp=100)
    aura_ally = unit((7306,))
    aura_enemy = unit((7306,), team=1)
    checks = [
        dict(name='one-id-two-families-potency-side', family='potency', ids=(7300,), expected=20),
        dict(name='one-id-two-families-move-side', family='move', ids=(7300,), expected=3),
        dict(name='same-family-two-rows-both-apply', family='potency', ids=(7301,),
             field='potency', expected=[50, 50, 60, 70, 50, 50, 50, 50]),
        dict(name='per-row-condition-holds', family='move', ids=(7302,), expected=4,
             fixture=fixture(unit((7302,), **low))),
        dict(name='per-row-condition-fails', family='move', ids=(7302,), expected=1,
             fixture=fixture(unit((7302,), hp=80, max_hp=100))),
        dict(name='two-percent-families-dealt-side', family='dealt', ids=(7303,), expected=10),
        dict(name='two-percent-families-taken-side', family='taken', ids=(7303,), expected=40),
        dict(name='two-additive-passes-power-side', family='power', ids=(7304,), expected=30),
        dict(name='two-additive-passes-defense-side', family='defense_power', ids=(7304,),
             expected=20),
        dict(name='same-stat-two-families-potency', family='potency', ids=(7305,),
             field='potency', expected=[50, 50, 57, 50, 50, 50, 50, 50]),
        dict(name='same-stat-two-families-aggregate', family='stats', ids=(7305,), expected=5),
        dict(name='same-family-two-rows-sum', family='dealt', ids=(7311,), expected=11),
        dict(name='legacy-single-row-unchanged', family='potency', ids=(7310,),
             field='potency', expected=[50, 50, 90, 50, 50, 50, 50, 50]),
        dict(name='duplicate-learned-id-still-applies-once', family='potency', ids=(7300, 7300),
             expected=20),
        dict(name='unlearned-is-unchanged', family='potency', ids=(), expected=50),
        dict(name='unlearned-move-is-unchanged', family='move', ids=(), expected=0),
        # the aura rows: only the row whose family was asked for applies, on the recipient
        dict(name='aura-two-rows-one-id-dealt-row-only', family='dealt', ids=(),
             fixture=fixture(unit(), provider=aura_ally, provider_cell=(5, 6)), expected=10),
        dict(name='aura-two-rows-one-id-taken-row-only', family='taken', ids=(),
             fixture=fixture(unit(), provider=aura_enemy, provider_cell=(15, 16)),
             other=unit((7306,)), expected=60),
        dict(name='aura-two-rows-no-provider', family='dealt', ids=(), expected=0),
        dict(name='aura-two-rows-out-of-radius', family='dealt', ids=(),
             fixture=fixture(unit(), provider=aura_ally, provider_cell=(9, 5)), expected=0),
    ]
    plans.append(('multi-row', rows, checks))
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
        table_rows, _conds, _fx = ev.table(rows)
        shared = sorted({r[0] for r in table_rows if sum(1 for q in table_rows if q[0] == r[0]) > 1})
        builds.append(dict(plan=plan_name, ids=len(rows), rows=len(table_rows),
                           shared_ids=shared, section_size=info['size'],
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
                                     out_value=50, original_rax=0)
                    got = detail[case.get('field', 'output')]
                    assert got == case['expected'], (got, case['expected'])
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=True,
                                        **detail))
                except Exception as exc:
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=False,
                                        error=f'{type(exc).__name__}: {exc}'))
                r = results[-1]
                print(('PASS ' if r['ok'] else 'FAIL ') + case['name'] + f' {family} {site:#x}' +
                      ('' if r['ok'] else ' ' + r['error']))
    passed = args.build_only or all(r['ok'] for r in results)
    report = dict(mode='build-only' if args.build_only else 'abi-site-entry' if args.abi else 'behavior',
                  original_sha256=ORIGINAL_SHA, builds=builds, checks=results, passed=passed,
                  limitations=[
                      'Original-game callees are deterministic stubs that return 0; the value under test is '
                      "the extension's own contribution added to it.",
                      "Executed paths only; Windows unwind and native gameplay are not executed, and the "
                      "game's own arithmetic around these returns is a stub.",
                      'The battle-unit table, unit records and action context are synthetic fixtures.',
                      'The aura checks prove which row of a shared id applies, not the game-side aura '
                      'collection (that is EX-05e\'s proof, unchanged).'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(results)} fixtures built' if args.build_only else
          f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
