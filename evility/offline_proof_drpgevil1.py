"""DRPGEVIL1: Disgaea RPG own-evility rows, taken verbatim from d5lib/importers/drpg-evility-overlay.json, run
through the real patched CALL sites (Unicorn), normal and --abi, with the EX-05e harness.

One applied row at least for every family the staged build uses (stats, dealt, taken, ailment_null, regen), with
the conditions those rows carry (weapon category, attack_skill, attack_normal, element, element_any, other_human,
target_count_min, hp_at_or_below), plus two rows that are prepared behind decision D1 and NOT applied (an ally
aura with the holder's own row, an enemy aura), so the flag-ready data is proven too.

D5_KIT=<worktree> <unicorn python> evility/offline_proof_drpgevil1.py [--abi] [--json OUT]
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
from d5lib.importers import _drpg_text   # noqa: E402  (TEXTHASH-DRPG: JP names are hashes; these proofs read ids, rows and our own wording)
from abi_engine_ex05c import execute                    # noqa: E402

OVERLAY = _drpg_text.load_authored(KIT / 'd5lib/importers/drpg-evility-overlay.json')
BY_ID = {e['id']: e for b in OVERLAY['bases'].values() for e in b['evilities']}
USED = (28000, 28003, 28012, 28051, 28063, 28078, 28131, 28155, 28380, 28410, 28574, 28008, 28098)
unit, fixture = h.unit, h.fixture


def agg(**kw):
    out = [0] * 18
    for k, v in kw.items():
        out[('hp', 'sp', 'atk', 'def', 'int', 'res', 'hit', 'spd').index(k)] = v
    return out


def cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    ally_far = unit((28008,))                # the D1 aura's provider
    foe = unit((28098,), team=1)             # the enemy aura's provider, hostile to the subject
    return [
        # stats + weapon (Barbara, Passive Warrior: ATK/DEF +27 with an axe, D5 item category 6)
        run('stats-weapon-axe-equipped', 'stats', 'aggregate', agg(atk=27, **{'def': 27}), ids=(28000,),
            fixture=fixture(unit((28000,), weapon_category=6))),
        run('stats-weapon-sword-equipped', 'stats', 'aggregate', agg(), ids=(28000,),
            fixture=fixture(unit((28000,), weapon_category=2))),
        run('stats-weapon-unlearned', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), weapon_category=6))),
        # stats unconditional (Zed: ATK/DEF +30) and two rows on one id (March Usalia: ATK +40, HP +25)
        run('stats-unconditional', 'stats', 'aggregate', agg(atk=30, **{'def': 30}), ids=(28078,),
            fixture=fixture(unit((28078,)))),
        run('stats-two-rows-one-id', 'stats', 'aggregate', agg(atk=40, hp=25), ids=(28380,),
            fixture=fixture(unit((28380,)))),
        # dealt (Barbara, Unleashed Might: skill damage +45; Yukimaru: water read as D5 ice +60)
        run('dealt-skill', 'dealt', 'output', 45, ids=(28003,),
            fixture=fixture(unit((28003,)), other=unit(), action_skill=392)),
        run('dealt-skill-normal-attack', 'dealt', 'output', 0, ids=(28003,),
            fixture=fixture(unit((28003,)), other=unit(), action_skill=0)),
        run('dealt-ice-element', 'dealt', 'output', 60, ids=(28012,),
            fixture=fixture(unit((28012,)), other=unit(), action_skill=392, action_element=3)),
        run('dealt-fire-element-does-not-match', 'dealt', 'output', 0, ids=(28012,),
            fixture=fixture(unit((28012,)), other=unit(), action_skill=392, action_element=1)),
        # taken: the row is the defender's; 50 in, scaled by (100 + value) %
        run('taken-from-humanoid', 'taken', 'output', 30, ids=(28063,),
            fixture=fixture(unit((28063,)), subject_is_other=True, other=unit(type_code=1))),
        run('taken-from-monster-unchanged', 'taken', 'output', 50, ids=(28063,),
            fixture=fixture(unit((28063,)), subject_is_other=True, other=unit(type_code=11))),
        run('taken-normal-attack', 'taken', 'output', 35, ids=(28410,),
            fixture=fixture(unit((28410,)), subject_is_other=True, other=unit(), action_skill=0)),
        run('taken-normal-attack-row-on-a-skill', 'taken', 'output', 50, ids=(28410,),
            fixture=fixture(unit((28410,)), subject_is_other=True, other=unit(), action_skill=392)),
        run('taken-elemental', 'taken', 'output', 25, ids=(28051,),
            fixture=fixture(unit((28051,)), subject_is_other=True, other=unit(), action_skill=392, action_element=2)),
        run('taken-elemental-row-on-a-plain-hit', 'taken', 'output', 50, ids=(28051,),
            fixture=fixture(unit((28051,)), subject_is_other=True, other=unit(), action_skill=392, action_element=0)),
        run('taken-multi-target', 'taken', 'output', 25, ids=(28574,),
            fixture=fixture(unit((28574,)), subject_is_other=True, other=unit(), action_skill=392, action_targets=3)),
        run('taken-single-target-unchanged', 'taken', 'output', 50, ids=(28574,),
            fixture=fixture(unit((28574,)), subject_is_other=True, other=unit(), action_skill=392, action_targets=1)),
        # ailment_null + weapon (Merome: all ailments nullified with a gun, category 5); the row is the target's
        run('ailment-null-gun-equipped', 'status_chance', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=unit((28131,), weapon_category=5))),
        run('ailment-null-staff-equipped', 'status_chance', 'output', 50, ids=(),
            fixture=fixture(unit(()), other=unit((28131,), weapon_category=7))),
        # regen (Aiko, Auto Repair: 50 % HP at the round edge while HP is 25 % or less)
        dict(name='regen-at-the-threshold', family='regen', field='hp', expected=75, ids=(28155,),
             fixture=fixture(unit((28155,), hp=25, max_hp=100)), expect_call=h.SHADOW),
        dict(name='regen-above-the-threshold', family='regen', field='hp', expected=26, ids=(28155,),
             fixture=fixture(unit((28155,), hp=26, max_hp=100)), absent_call=h.SHADOW),
        # ---- prepared behind D1, not applied: ally aura (holder row + aura, radius 30) and enemy aura
        run('D1-ally-aura-reaches-an-ally-20-panels-away', 'stats', 'aggregate', agg(atk=15), ids=(),
            fixture=fixture(unit(()), others=((ally_far, (5, 25), 2),))),
        run('D1-ally-aura-holder-gets-its-own-row-once', 'stats', 'aggregate', agg(atk=15), ids=(28008,),
            fixture=fixture(unit((28008,)), others=((unit(()), (5, 6), 2),))),
        run('D1-ally-aura-two-holders-reach-each-other', 'stats', 'aggregate', agg(atk=30), ids=(28008,),
            fixture=fixture(unit((28008,)), others=((ally_far, (5, 6), 2),))),
        run('D1-ally-aura-stops-past-30-panels', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((ally_far, (5, 36), 2),))),
        run('D1-ally-aura-does-not-reach-an-enemy', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), team=1), others=((ally_far, (5, 6), 2),))),
        run('D1-enemy-aura-lowers-a-hostile-unit', 'stats', 'aggregate', agg(res=-14, **{'def': -14}), ids=(),
            fixture=fixture(unit(()), others=((foe, (5, 20), 2),))),
        run('D1-enemy-aura-spares-its-own-side', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), team=1), others=((foe, (5, 6), 2),))),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    from d5lib import evility as ev
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    rows = {i: BY_ID[i]['rows'] for i in USED}
    patched = ev.build_patch(original, rows)
    info = ev.section_info(patched)
    specs = [(name, target, sites) for name, (_, target, sites) in zip(h.NAMES, ev.WRAPPERS)]
    results = []
    for case in cases():
        _, target, sites = next(s for s in specs if s[0] == case['family'])
        for site in sites:
            try:
                d = execute(patched, info, specs, case['family'], target, site, ids=case.get('ids', ()), abi=a.abi,
                            fixture=case['fixture'], out_value=50, original_rax=0)
                got = d[case.get('field', 'output')]
                if isinstance(got, list):
                    got = [x - (1 << 16) if x >= (1 << 15) and x < (1 << 16) else x for x in got]
                assert got == case['expected'], (got, case['expected'])
                if 'expect_call' in case:
                    assert case['expect_call'] in d['call_edges'], d['call_edges']
                if 'absent_call' in case:
                    assert case['absent_call'] not in d['call_edges'], d['call_edges']
                results.append(dict(name=case['name'], family=case['family'], site=hex(site), ok=True))
            except Exception as exc:                 # noqa: BLE001
                results.append(dict(name=case['name'], family=case['family'], site=hex(site), ok=False,
                                    error=f'{type(exc).__name__}: {exc}'))
            r = results[-1]
            print(('PASS ' if r['ok'] else 'FAIL ') + r['name'] + ' ' + r['site'] + ('' if r['ok'] else ' ' + r['error']))
    ok = all(r['ok'] for r in results)
    if a.json:
        a.json.write_text(json.dumps(dict(mode='abi' if a.abi else 'behavior', rows=sorted(rows), passed=ok,
                                          patched_sha256=hashlib.sha256(patched).hexdigest(), checks=results), indent=1) + '\n')
    print(f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
