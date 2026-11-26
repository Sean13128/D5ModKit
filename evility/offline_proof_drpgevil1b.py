"""DRPGEVIL1b: the two effects added for the Disgaea RPG evilities, through the real patched CALL sites
(Unicorn), normal and --abi, with the EX-05e harness.  No new call site: both live in existing wrappers.

  provider qualifiers (conditions 50..53, written right after a near_has): the aura's HOLDER must also hold a
      weapon of a category / be above, below, at-or-below an hp percent.  evil_near filter kind 6.
  crit_damage (family bit 27): on a critical hit the attacker's rows multiply the value by (100 + v) / 100,
      inside the `taken` wrapper -- where D5's own Purgatory (1222) does it.

D5_KIT=<worktree> <unicorn python> evility/offline_proof_drpgevil1b.py [--abi] [--json OUT]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_ex05e as h                         # noqa: E402
from abi_engine_ex05c import ACTION, execute            # noqa: E402

unit, fixture = h.unit, h.fixture
NEAR = lambda i, of=1: {'kind': 'near_has', 'of': of, 'radius': 30, 'id': i}     # noqa: E731
ROWS = {
    # the shape the DRPG overlay writes: the holder's own row + the aura row with the holder-side condition
    7700: [{'family': 'dealt', 'effects': [{'value': 12}], 'conditions': [{'kind': 'weapon', 'id': 1}]},
           {'family': ['dealt', 'aura'], 'effects': [{'value': 12}],
            'conditions': [NEAR(7700), {'kind': 'provider_weapon', 'id': 1}]}],
    7701: {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 20}],
           'conditions': [NEAR(7701), {'kind': 'provider_hp_above', 'id': 50}]},
    7702: {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 20}],
           'conditions': [NEAR(7702), {'kind': 'provider_hp_below', 'id': 50}]},
    7703: {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 20}],
           'conditions': [NEAR(7703), {'kind': 'provider_hp_at_or_below', 'id': 25}]},
    # a recipient condition written AFTER the qualifier is still tested on the recipient
    7704: {'family': ['dealt', 'aura'], 'effects': [{'value': 12}],
           'conditions': [NEAR(7704), {'kind': 'provider_weapon', 'id': 1}, {'kind': 'attack_skill'}]},
    # an enemy aura with a holder-side condition
    7705: {'family': ['stats', 'aura'], 'effects': [{'stat': 'def', 'value': -15}],
           'conditions': [NEAR(7705, 2), {'kind': 'provider_weapon', 'id': 7}]},
    7710: {'family': 'crit_damage', 'effects': [{'value': 25}]},
    7711: {'family': 'taken', 'effects': [{'value': -40}]},
    7712: {'family': 'crit_damage', 'effects': [{'value': 30}], 'conditions': [{'kind': 'weapon', 'id': 5}]},
    7713: {'family': ['crit_damage', 'aura'], 'effects': [{'value': 20}], 'conditions': [NEAR(7713)]},
}


def agg(**kw):
    out = [0] * 18
    for k, v in kw.items():
        out[('hp', 'sp', 'atk', 'def', 'int', 'res', 'hit', 'spd').index(k)] = v
    return out


def crit(entry):
    """mark target entry `entry` of the action context as a critical hit (X + entry * 0x260 + 0x152A)"""
    return [(ACTION + 0x152A + entry * 0x260, b'\x01')]


def cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    fist, sword = unit((7700,), weapon_category=1), unit((7700,), weapon_category=2)
    T = lambda tgt: dict(supplied_stack_args=(ACTION, tgt, 0))      # noqa: E731  X, target index, fc
    return [
        # ---- holder-side condition: weapon
        run('provider-weapon-holder-has-the-fist', 'dealt', 'output', 12, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((fist, (5, 10), 2),))),
        run('provider-weapon-holder-has-a-sword', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((sword, (5, 10), 2),))),
        run('provider-weapon-holder-out-of-radius', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((fist, (5, 36), 2),))),
        run('provider-weapon-any-qualifying-holder-counts', 'dealt', 'output', 12, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((sword, (5, 6), 2), (fist, (5, 20), 3)))),
        run('provider-weapon-enemy-holder-does-not-count', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit((), team=1), other=unit(), others=((fist, (5, 6), 2),))),
        run('provider-weapon-the-holder-itself-own-row', 'dealt', 'output', 12, ids=(7700,),
            fixture=fixture(unit((7700,), weapon_category=1), other=unit())),
        run('provider-weapon-the-holder-itself-wrong-weapon', 'dealt', 'output', 0, ids=(7700,),
            fixture=fixture(unit((7700,), weapon_category=2), other=unit())),
        run('provider-weapon-second-slot', 'dealt', 'output', 12, ids=(),
            fixture=fixture(unit(()), other=unit(),
                            others=((slot1(unit((7700,)), 1), (5, 10), 2),))),
        run('recipient-condition-after-the-qualifier-holds', 'dealt', 'output', 12, ids=(),
            fixture=fixture(unit(()), other=unit(), action_skill=392,
                            others=((unit((7704,), weapon_category=1), (5, 10), 2),))),
        run('recipient-condition-after-the-qualifier-fails', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=unit(), action_skill=0,
                            others=((unit((7704,), weapon_category=1), (5, 10), 2),))),
        run('provider-weapon-enemy-aura-holder-has-the-staff', 'stats', 'aggregate', agg(**{'def': -15}), ids=(),
            fixture=fixture(unit(()), others=((unit((7705,), team=1, weapon_category=7), (5, 12), 2),))),
        run('provider-weapon-enemy-aura-holder-has-a-gun', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((7705,), team=1, weapon_category=5), (5, 12), 2),))),
        # ---- holder-side condition: hp
        run('provider-hp-above-at-50', 'stats', 'aggregate', agg(atk=20), ids=(),
            fixture=fixture(unit(()), others=((unit((7701,), hp=50, max_hp=100), (5, 9), 2),))),
        run('provider-hp-above-at-49', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((7701,), hp=49, max_hp=100), (5, 9), 2),))),
        run('provider-hp-below-at-49', 'stats', 'aggregate', agg(atk=20), ids=(),
            fixture=fixture(unit(()), others=((unit((7702,), hp=49, max_hp=100), (5, 9), 2),))),
        run('provider-hp-below-at-50', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((7702,), hp=50, max_hp=100), (5, 9), 2),))),
        run('provider-hp-at-or-below-at-250-of-1000', 'stats', 'aggregate', agg(atk=20), ids=(),
            fixture=fixture(unit(()), others=((unit((7703,), hp=250, max_hp=1000), (5, 9), 2),))),
        run('provider-hp-at-or-below-at-251-of-1000', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((7703,), hp=251, max_hp=1000), (5, 9), 2),))),
        run('provider-hp-holder-without-a-max-is-no-provider', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((7701,)), (5, 9), 2),))),
        # ---- critical damage: 50 in; the attacker is the subject, the defender the other side
        run('crit-damage-on-a-critical', 'taken', 'output', 62, ids=(7710,), **T(1),
            fixture=fixture(unit((7710,)), other=unit(), regions=crit(1))),
        run('crit-damage-no-critical', 'taken', 'output', 50, ids=(7710,), **T(1),
            fixture=fixture(unit((7710,)), other=unit(), regions=[(ACTION + 0x152A + 0x260, b'\x00')])),
        run('crit-damage-flag-of-another-target', 'taken', 'output', 50, ids=(7710,), **T(1),
            fixture=fixture(unit((7710,)), other=unit(), regions=crit(0) + [(ACTION + 0x152A + 0x260, b'\x00')])),
        run('crit-damage-target-entry-0', 'taken', 'output', 62, ids=(7710,), **T(0),
            fixture=fixture(unit((7710,)), other=unit(), regions=crit(0))),
        run('crit-damage-row-on-the-defender-does-nothing', 'taken', 'output', 50, ids=(), **T(1),
            fixture=fixture(unit(()), other=unit((7710,)), regions=crit(1))),
        run('crit-damage-unlearned', 'taken', 'output', 50, ids=(), **T(1),
            fixture=fixture(unit(()), other=unit(), regions=crit(1))),
        run('crit-damage-after-the-defenders-reduction', 'taken', 'output', 37, ids=(7710,), **T(1),
            fixture=fixture(unit((7710,)), other=unit((7711,)), regions=crit(1))),
        run('crit-damage-conditional-gun', 'taken', 'output', 65, ids=(7712,), **T(1),
            fixture=fixture(unit((7712,), weapon_category=5), other=unit(), regions=crit(1))),
        run('crit-damage-conditional-sword', 'taken', 'output', 50, ids=(7712,), **T(1),
            fixture=fixture(unit((7712,), weapon_category=2), other=unit(), regions=crit(1))),
        run('crit-damage-two-rows-add', 'taken', 'output', 77, ids=(7710, 7712), **T(1),
            fixture=fixture(unit((7710, 7712), weapon_category=5), other=unit(), regions=crit(1))),
        run('crit-damage-aura-from-an-ally', 'taken', 'output', 60, ids=(), **T(1),
            fixture=fixture(unit(()), other=unit(team=1), regions=crit(1),
                            others=((unit((7713,)), (5, 9), 2),))),
        run('crit-damage-not-a-target-index', 'taken', 'output', 50, ids=(7710,), **T(256),
            fixture=fixture(unit((7710,)), other=unit(), regions=crit(1))),
    ]


def slot1(data, category):
    """an item in weapon slot 1 only (+912 item, +942 category)"""
    import struct
    struct.pack_into('<i', data, 912, 1)
    struct.pack_into('<B', data, 942, category)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    from d5lib import evility as ev
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    patched = ev.build_patch(original, ROWS)
    info = ev.section_info(patched)
    specs = [(name, target, sites) for name, (_, target, sites) in zip(h.NAMES, ev.WRAPPERS)]
    results = []
    for case in cases():
        _, target, sites = next(s for s in specs if s[0] == case['family'])
        for site in sites:
            try:
                d = execute(patched, info, specs, case['family'], target, site, ids=case.get('ids', ()), abi=a.abi,
                            fixture=case['fixture'], out_value=50, original_rax=0,
                            supplied_stack_args=case.get('supplied_stack_args'))
                got = d[case.get('field', 'output')]
                if isinstance(got, list):
                    got = [x - (1 << 16) if (1 << 15) <= x < (1 << 16) else x for x in got]
                assert got == case['expected'], (got, case['expected'])
                results.append(dict(name=case['name'], family=case['family'], site=hex(site), ok=True))
            except Exception as exc:                 # noqa: BLE001
                results.append(dict(name=case['name'], family=case['family'], site=hex(site), ok=False,
                                    error=f'{type(exc).__name__}: {exc}'))
            r = results[-1]
            print(('PASS ' if r['ok'] else 'FAIL ') + r['name'] + ' ' + r['site'] + ('' if r['ok'] else ' ' + r['error']))
    ok = all(r['ok'] for r in results)
    if a.json:
        a.json.write_text(json.dumps(dict(mode='abi' if a.abi else 'behavior', passed=ok,
                                          patched_sha256=hashlib.sha256(patched).hexdigest(), checks=results), indent=1) + '\n')
    print(f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
