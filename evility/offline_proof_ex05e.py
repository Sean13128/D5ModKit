"""EX-05e: critical rate, round-edge regeneration, nullification, named-character adjacency,
actor/target adjacency and damage-time auras.

Default mode executes the installed wrappers directly (Unicorn); --abi enters each real patched
CALL instruction with the caller's RSP%16=0 and checks the exact continuation and home space, so
the redirection itself is exercised.  --build-only never imports Unicorn and only builds the
fixtures and the patch (restricted hosts).

D5_KIT=/Volumes/Data/Projects/D5/Local/Worktrees/engine-ext-vocab3 \\
 /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \\
 evility/offline_proof_ex05e.py --json evility/results/ex05e-behavior.json
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
# the wrapper order of d5lib/evility.py WRAPPERS; only the families this suite uses are named
NAMES = ('potency', 'stats', 'growth', 'dealt', 'taken', 'flight', 'flight', 'hit', 'status_chance',
         'conversion', 'crit_rate', 'regen')
BATTLE_TABLE, STRIDE = 0x141BA33B0, 4704
EXTRA = (0x400090000, 0x400098000, 0x4000A0000, 0x4000A8000)
SHADOW = '0x140151c50'      # unit_set_hp_shadow: the regen family's bar refresh


def unit(ids=(), *, team=0, char_id=10, type_code=1, hp=None, max_hp=None, sp=None, max_sp=None,
         potency=50, weapon_category=None):
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
    if max_sp is not None:
        struct.pack_into('<q', b, 0x2ce0, max_sp)
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
            others=(), action_element=None, action_skill=None, action_targets=None,
            regions=(), subject_is_other=False):
    """Complete mapped inputs; `others` are [(unit bytes, cell, slot)] extra units on the map."""
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
        if subject_is_other:
            write(REC, side_rec if other is not None else bytes(STRIDE))
            write(OREC, subject_rec)
        else:
            write(REC, subject_rec)
            write(OREC, side_rec if other is not None else bytes(STRIDE))
        write(UNIT, subject)
        if other is not None:
            write(OTHER, other)
        write(ACTION, bytes(0x300))
        write(ACTION + 0x276BC, struct.pack('<B', action_element or 0))
        write(ACTION + 0x27670, struct.pack('<i', action_skill or 0))
        write(ACTION + 160536, struct.pack('<h', action_targets or 0))
        for address, data in regions:
            write(address, data)
    return setup


def cases(ev):
    """Independent plans; every fixture is constructed without a Uc instance."""
    plans = []

    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)

    # ------------------------------------------------------------------ critical rate
    crit_rows = {
        7600: {'family': 'crit_rate', 'effects': [{'value': 20}]},
        7601: {'family': 'crit_rate', 'effects': [{'value': -20}]},
        7602: {'family': 'crit_rate', 'effects': [{'value': 100}],
               'condition': {'kind': 'attack_dir', 'id': 2}},
        # an aura: the recipient's crit rate rises while a provider stands next to it
        7603: {'family': ['crit_rate', 'aura'], 'effects': [{'value': 25}],
               'condition': {'kind': 'near_has', 'of': 1, 'radius': 1, 'id': 7603}},
    }
    provider = unit((7603,))

    def behind(subject, direction):
        """the action context's target entry for the *other* unit, carrying its attack direction"""
        entry = bytearray(608)
        struct.pack_into('<H', entry, 0, 1)        # the other unit's own slot
        struct.pack_into('<i', entry, 36, direction)
        return ((ACTION + 4888, bytes(entry)),)

    crit_checks = [
        run('crit-adds-twenty-points', 'crit_rate', 'output', 70, ids=(7600,),
            fixture=fixture(unit((7600,)), other=unit())),
        run('crit-unlearned-is-unchanged', 'crit_rate', 'output', 50, ids=(),
            fixture=fixture(unit(()), other=unit())),
        run('crit-clamps-at-one-hundred', 'crit_rate', 'output', 100, ids=(7600,), out_value=95,
            fixture=fixture(unit((7600,)), other=unit())),
        run('crit-negative-stops-at-zero', 'crit_rate', 'output', 0, ids=(7601,), out_value=10,
            fixture=fixture(unit((7601,)), other=unit())),
        run('crit-behind-only-fires-behind', 'crit_rate', 'output', 100, ids=(7602,), out_value=10,
            fixture=fixture(unit((7602,)), other=unit(), action_targets=1,
                            regions=behind(unit(), 2))),
        run('crit-behind-does-not-fire-in-front', 'crit_rate', 'output', 10, ids=(7602,),
            out_value=10, fixture=fixture(unit((7602,)), other=unit(), action_targets=1,
                                          regions=behind(unit(), 0))),
        run('crit-behind-with-no-action-context', 'crit_rate', 'output', 10, ids=(7602,),
            out_value=10, fixture=fixture(unit((7602,)), other=unit())),
        # the attacker has no row of its own; an adjacent ally carries the aura's provider id
        run('crit-aura-from-an-adjacent-provider', 'crit_rate', 'output', 75, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((provider, (5, 6), 2),))),
        run('crit-aura-provider-two-panels-away', 'crit_rate', 'output', 50, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((provider, (5, 7), 2),))),
        run('crit-aura-provider-is-not-an-ally', 'crit_rate', 'output', 50, ids=(),
            fixture=fixture(unit((), team=1), other=unit(team=1),
                            others=((provider, (5, 6), 2),))),
    ]
    plans.append(('critical-rate', crit_rows, crit_checks))

    # ------------------------------------------------------------------ damage nullification
    null_rows = {
        7620: {'family': 'damage_null', 'conditions': [{'kind': 'attack_skill'},
                                                       {'kind': 'element', 'id': 0},
                                                       {'kind': 'hp_below', 'id': 25}]},
        7621: {'family': 'damage_null'},
    }
    null_checks = [
        run('null-fires-under-the-hp-threshold', 'taken', 'output', 0, ids=(7620,),
            fixture=fixture(unit((7620,), hp=20, max_hp=100), subject_is_other=True,
                            other=unit(), action_skill=392, action_element=0)),
        run('null-does-not-fire-above-it', 'taken', 'output', 50, ids=(7620,),
            fixture=fixture(unit((7620,), hp=50, max_hp=100), subject_is_other=True,
                            other=unit(), action_skill=392, action_element=0)),
        run('null-does-not-fire-on-an-elemental-attack', 'taken', 'output', 50, ids=(7620,),
            fixture=fixture(unit((7620,), hp=20, max_hp=100), subject_is_other=True,
                            other=unit(), action_skill=392, action_element=1)),
        run('null-does-not-fire-on-a-normal-attack', 'taken', 'output', 50, ids=(7620,),
            fixture=fixture(unit((7620,), hp=20, max_hp=100), subject_is_other=True,
                            other=unit(), action_skill=0, action_element=0)),
        run('null-unlearned-is-unchanged', 'taken', 'output', 50, ids=(),
            fixture=fixture(unit((), hp=20, max_hp=100), subject_is_other=True,
                            other=unit(), action_skill=392, action_element=0)),
        run('null-unconditional-row', 'taken', 'output', 0, ids=(7621,),
            fixture=fixture(unit((7621,)), subject_is_other=True, other=unit())),
        # the row belongs to the *defender*: the attacker carrying it changes nothing
        run('null-on-the-attacker-does-nothing', 'taken', 'output', 50, ids=(7621,),
            fixture=fixture(unit(()), subject_is_other=True, other=unit((7621,)))),
    ]
    plans.append(('damage-nullification', null_rows, null_checks))

    # ------------------------------------------------------------------ ailment immunity
    astat_rows = {7630: {'family': 'ailment_null'}}
    astat_checks = [
        run('ailment-null-zeroes-the-chance', 'status_chance', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=unit((7630,)))),
        run('ailment-null-absent-is-unchanged', 'status_chance', 'output', 50, ids=(),
            fixture=fixture(unit(()), other=unit())),
        # the row is the target's, not the attacker's
        run('ailment-null-on-the-attacker-does-nothing', 'status_chance', 'output', 50, ids=(7630,),
            fixture=fixture(unit((7630,)), other=unit())),
    ]
    plans.append(('ailment-immunity', astat_rows, astat_checks))

    # ------------------------------------------------------------------ round-edge regeneration
    regen_rows = {
        7640: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 10}, {'stat': 'sp', 'value': 10}]},
        7641: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 10}]},
        7642: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': -50}]},
        7643: {'family': 'regen', 'effects': [{'stat': 'hp', 'value': 100}],
               'condition': {'kind': 'hp_below', 'id': 25}},
        7644: {'family': 'regen', 'effects': [{'stat': 'sp', 'value': -100}]},
    }
    full = dict(hp=50, max_hp=100, sp=40, max_sp=200)
    regen_checks = [
        dict(name='regen-heals-hp-and-sp', family='regen', field='hp', expected=60, ids=(7640,),
             fixture=fixture(unit((7640,), **full)), sp_expected=60, original_rax=0x5A5A,
             expect_call=SHADOW),
        dict(name='regen-does-not-exceed-the-maximum', family='regen', field='hp', expected=100,
             ids=(7641,), fixture=fixture(unit((7641,), hp=95, max_hp=100, sp=40, max_sp=200)),
             expect_call=SHADOW),
        dict(name='regen-drain-stops-at-zero', family='regen', field='hp', expected=0, ids=(7642,),
             fixture=fixture(unit((7642,), hp=10, max_hp=100, sp=40, max_sp=200)),
             expect_call=SHADOW),
        dict(name='regen-conditional-row-fires-under-the-threshold', family='regen', field='hp',
             expected=100, ids=(7643,), fixture=fixture(unit((7643,), hp=10, max_hp=100)),
             expect_call=SHADOW),
        dict(name='regen-conditional-row-above-the-threshold', family='regen', field='hp',
             expected=30, ids=(7643,), fixture=fixture(unit((7643,), hp=30, max_hp=100)),
             absent_call=SHADOW),
        dict(name='regen-sp-only-writes-sp', family='regen', field='sp', expected=0, ids=(7644,),
             fixture=fixture(unit((7644,), hp=50, max_hp=100, sp=40, max_sp=200)),
             absent_call=SHADOW),
        dict(name='regen-unlearned-is-unchanged', family='regen', field='hp', expected=50, ids=(),
             fixture=fixture(unit((), **full))),
        dict(name='regen-another-units-row-does-nothing', family='regen', field='hp', expected=50,
             ids=(), fixture=fixture(unit((), **full))),
    ]
    plans.append(('round-edge-regeneration', regen_rows, regen_checks))

    # ------------------------------------------------------------------ named-character adjacency
    near_rows = {
        7650: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 50}],
               'condition': {'kind': 'near_char', 'of': 1, 'radius': 1, 'id': 650}},
        7651: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 50}],
               'condition': {'kind': 'near_char', 'of': 1, 'radius': 0, 'id': 650}},
        7652: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 50}],
               'condition': {'kind': 'near_char', 'of': 2, 'radius': 1, 'id': 650}},
        7653: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 50}],
               'condition': {'kind': 'near_char', 'of': 1, 'radius': 2, 'id': 650}},
    }
    raspberyl = unit(team=0, char_id=650)
    someone_else = unit(team=0, char_id=651)
    enemy_raspberyl = unit(team=1, char_id=650)
    atk50 = [0, 0, 50] + [0] * 15
    near_checks = [
        run('near-char-adjacent-named-ally', 'stats', 'aggregate', atk50, ids=(7650,),
            fixture=fixture(unit((7650,)), others=((raspberyl, (5, 6), 2),))),
        run('near-char-another-character-does-not-match', 'stats', 'aggregate', [0] * 18,
            ids=(7650,), fixture=fixture(unit((7650,)), others=((someone_else, (5, 6), 2),))),
        run('near-char-two-panels-away', 'stats', 'aggregate', [0] * 18, ids=(7650,),
            fixture=fixture(unit((7650,)), others=((raspberyl, (5, 7), 2),))),
        run('near-char-radius-defaults-to-one', 'stats', 'aggregate', atk50, ids=(7651,),
            fixture=fixture(unit((7651,)), others=((raspberyl, (6, 5), 2),))),
        run('near-char-relation-ally-excludes-an-enemy', 'stats', 'aggregate', [0] * 18, ids=(7650,),
            fixture=fixture(unit((7650,)), others=((enemy_raspberyl, (5, 6), 2),))),
        run('near-char-relation-enemy', 'stats', 'aggregate', atk50, ids=(7652,),
            fixture=fixture(unit((7652,)), others=((enemy_raspberyl, (5, 6), 2),))),
        run('near-char-relation-enemy-excludes-an-ally', 'stats', 'aggregate', [0] * 18, ids=(7652,),
            fixture=fixture(unit((7652,)), others=((raspberyl, (5, 6), 2),))),
        run('near-char-radius-two', 'stats', 'aggregate', atk50, ids=(7653,),
            fixture=fixture(unit((7653,)), others=((raspberyl, (5, 7), 2),))),
        run('near-char-not-on-the-map', 'stats', 'aggregate', [0] * 18, ids=(7650,), on_map=False,
            fixture=fixture(unit((7650,)), on_map=False, others=((raspberyl, (5, 6), 2),))),
    ]
    plans.append(('named-character-adjacency', near_rows, near_checks))

    # ------------------------------------------------------------------ actor/target adjacency
    adj_rows = {
        7660: {'family': 'dealt', 'effects': [{'value': 50}],
               'conditions': [{'kind': 'other_adj'}, {'kind': 'weapon', 'id': 5}]},
        7661: {'family': 'dealt', 'effects': [{'value': 50}],
               'condition': {'kind': 'other_adj'}},
        7662: {'family': 'taken', 'effects': [{'value': 50}],
               'condition': {'kind': 'other_adj'}},
    }
    adj_checks = [
        run('other-adj-adjacent-target', 'dealt', 'output', 50, ids=(7660,),
            fixture=fixture(unit((7660,), weapon_category=5), other=unit(),
                            subject_cell=(5, 5), other_cell=(6, 5))),
        run('other-adj-two-panels-away', 'dealt', 'output', 0, ids=(7660,),
            fixture=fixture(unit((7660,), weapon_category=5), other=unit(),
                            subject_cell=(5, 5), other_cell=(7, 5))),
        run('other-adj-wrong-weapon', 'dealt', 'output', 0, ids=(7660,),
            fixture=fixture(unit((7660,), weapon_category=2), other=unit(),
                            subject_cell=(5, 5), other_cell=(6, 5))),
        run('other-adj-diagonal-is-not-adjacent', 'dealt', 'output', 0, ids=(7661,),
            fixture=fixture(unit((7661,)), other=unit(), subject_cell=(5, 5), other_cell=(6, 6))),
        run('other-adj-with-no-other-side', 'dealt', 'output', 0, ids=(7661,),
            fixture=fixture(unit((7661,)))),
        # taken: the subject is the defender, so the other side is the attacker next to it
        run('other-adj-on-taken', 'taken', 'output', 75, ids=(7662,), subject_is_other=True,
            fixture=fixture(unit((7662,)), subject_is_other=True, other=unit(),
                            subject_cell=(6, 6), other_cell=(6, 7))),
        run('other-adj-on-taken-from-afar', 'taken', 'output', 50, ids=(7662,), subject_is_other=True,
            fixture=fixture(unit((7662,)), subject_is_other=True, other=unit(),
                            subject_cell=(6, 6), other_cell=(9, 7))),
    ]
    plans.append(('actor-target-adjacency', adj_rows, adj_checks))

    # ------------------------------------------------------------------ damage-time auras
    aura_rows = {
        7670: {'family': ['taken', 'aura'], 'effects': [{'value': -50}],
               'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 1, 'id': 7670},
                              {'kind': 'attack_magic'}]},
        7671: {'family': ['taken', 'aura'], 'effects': [{'value': -50}],
               'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 1, 'id': 7671},
                              {'kind': 'element', 'id': 0}]},
        7672: {'family': ['dealt', 'aura'], 'effects': [{'value': 30}],
               'condition': {'kind': 'near_has', 'of': 1, 'radius': 1, 'id': 7672}},
    }
    provider = unit((7670,))
    provider_n = unit((7671,))
    provider_d = unit((7672,))
    math_row = ((ACTION + 0x27678, struct.pack('<Q', ACTION + 0x2000)),
                (ACTION + 0x2000 + 1014, b'\x03'))     # a magic skill row (effect type 3)
    phys_row = ((ACTION + 0x27678, struct.pack('<Q', ACTION + 0x2000)),
                (ACTION + 0x2000 + 1014, b'\x02'))
    aura_checks = [
        run('aura-taken-magic-absorbs-half', 'taken', 'output', 25, ids=(), subject_is_other=True,
            fixture=fixture(unit(()), subject_is_other=True, other=unit(),
                            others=((provider, (5, 6), 2),), action_skill=392, regions=math_row)),
        run('aura-taken-physical-does-not-fire', 'taken', 'output', 50, ids=(), subject_is_other=True,
            fixture=fixture(unit(()), subject_is_other=True, other=unit(),
                            others=((provider, (5, 6), 2),), action_skill=392, regions=phys_row)),
        run('aura-taken-provider-two-panels-away', 'taken', 'output', 50, ids=(),
            subject_is_other=True,
            fixture=fixture(unit(()), subject_is_other=True, other=unit(),
                            others=((provider, (5, 8), 2),), action_skill=392, regions=math_row)),
        run('aura-taken-provider-is-an-enemy', 'taken', 'output', 50, ids=(), subject_is_other=True,
            fixture=fixture(unit((), team=1), subject_is_other=True, other=unit(team=0),
                            others=((provider, (5, 6), 2),), action_skill=392, regions=math_row)),
        run('aura-taken-non-elemental-half', 'taken', 'output', 25, ids=(), subject_is_other=True,
            fixture=fixture(unit(()), subject_is_other=True, other=unit(),
                            others=((provider_n, (5, 6), 2),), action_element=0)),
        run('aura-taken-elemental-does-not-fire', 'taken', 'output', 50, ids=(), subject_is_other=True,
            fixture=fixture(unit(()), subject_is_other=True, other=unit(),
                            others=((provider_n, (5, 6), 2),), action_element=1)),
        run('aura-dealt-adds-thirty-percent', 'dealt', 'output', 30, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((provider_d, (5, 6), 2),))),
        run('aura-dealt-no-provider-nearby', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((provider_d, (5, 9), 2),))),
        # the aura id on the recipient itself proves nothing: its own list is not the provider
        run('aura-recipient-does-not-provide-for-itself', 'dealt', 'output', 0, ids=(7672,),
            fixture=fixture(unit((7672,)), other=unit())),
    ]
    plans.append(('damage-time-auras', aura_rows, aura_checks))
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
                    got = detail[case.get('field', 'output')]
                    assert got == case['expected'], (got, case['expected'])
                    if 'sp_expected' in case:
                        assert detail['sp'] == case['sp_expected'], detail['sp']
                    if 'expect_call' in case:
                        assert case['expect_call'] in detail['call_edges'], detail['call_edges']
                    if 'absent_call' in case:
                        assert case['absent_call'] not in detail['call_edges'], detail['call_edges']
                    if case.get('original_rax') == 0x5A5A:
                        assert detail['output'] == 0x5A5A, detail['output']
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
                               'unit_set_hp_shadow is a stub here: the regen suite proves our write and the call,',
                               'not the games own shadow maths.',
                               'Build-only is fixture/patch validation, not an emulator pass.'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(results)} fixtures built' if args.build_only else
          f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
