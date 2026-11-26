"""DRPGEVIL1c: the runtime table at its new maximum (2,048 rows), the presence map, and the party counts
(party_* scales, party_min) and turn_max, through the real patched
CALL sites (Unicorn), normal and --abi, with the EX-05e harness.

The table: 1,400 aura rows (stats / dealt / taken / crit_damage, some with a holder-side condition) on 1,400
evility ids, and 648 ordinary rows (324 ids x 2 rows).  Every case also checks the instruction count of the
call: before the presence map one aura row cost about 2,900 instructions per call.

D5_KIT=<worktree> <unicorn python> evility/offline_proof_drpgevil1c.py [--abi] [--json OUT]
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
A0, N_AURA, O0, N_ORD = 20000, 1400, 9000, 324
BUDGET = 60000                                           # instructions per call at 2,048 rows


def near(i, of=1):
    return {'kind': 'near_has', 'of': of, 'radius': 30, 'id': i}


def rows():
    out = {}
    for k in range(N_AURA):
        i = A0 + k
        m = k % 4
        if m == 0:
            out[i] = {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 7}], 'conditions': [near(i)]}
        elif m == 1:
            out[i] = {'family': ['dealt', 'aura'], 'effects': [{'value': 11}],
                      'conditions': [near(i), {'kind': 'provider_weapon', 'id': 3}]}
        elif m == 2:
            out[i] = {'family': ['taken', 'aura'], 'effects': [{'value': -20}], 'conditions': [near(i)]}
        else:
            out[i] = {'family': ['crit_damage', 'aura'], 'effects': [{'value': 30}], 'conditions': [near(i)]}
    for k in range(N_ORD):
        out[O0 + k] = [{'family': 'dealt', 'effects': [{'value': 3}]},
                       {'family': 'stats', 'effects': [{'stat': 'def', 'value': 2}]}]
    return out


def agg(**kw):
    out = [0] * 18
    for k, v in kw.items():
        out[('hp', 'sp', 'atk', 'def', 'int', 'res', 'hit', 'spd').index(k)] = v
    return out


def cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    first, mid, last = A0, A0 + 700, A0 + N_AURA - 4            # stats auras (k % 4 == 0)
    d_first, d_last = A0 + 1, A0 + N_AURA - 3                   # dealt auras with provider_weapon 3
    t_mid, c_mid = A0 + 702, A0 + 703
    T = dict(supplied_stack_args=(ACTION, 1, 0))
    crit = [(ACTION + 0x152A + 0x260, b'\x01')]
    return [
        run('nobody-provides-anything', 'stats', 'aggregate', agg(), ids=(), fixture=fixture(unit(()))),
        run('first-aura-of-the-index', 'stats', 'aggregate', agg(atk=7), ids=(),
            fixture=fixture(unit(()), others=((unit((first,)), (5, 9), 2),))),
        run('middle-aura', 'stats', 'aggregate', agg(atk=7), ids=(),
            fixture=fixture(unit(()), others=((unit((mid,)), (5, 9), 2),))),
        run('last-aura-of-the-index', 'stats', 'aggregate', agg(atk=7), ids=(),
            fixture=fixture(unit(()), others=((unit((last,)), (5, 9), 2),))),
        run('three-providers-add', 'stats', 'aggregate', agg(atk=21), ids=(),
            fixture=fixture(unit(()), others=((unit((first,)), (5, 9), 2), (unit((mid,)), (6, 9), 3),
                                                (unit((last,)), (7, 9), 4)))),
        run('provider-on-the-map-but-an-enemy', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((mid,), team=1), (5, 9), 2),))),
        run('provider-out-of-radius', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((mid,)), (5, 40), 2),))),
        run('holder-does-not-get-its-own-aura', 'stats', 'aggregate', agg(), ids=(mid,),
            fixture=fixture(unit((mid,)))),
        run('ordinary-rows-first-and-last-id-with-an-aura', 'stats', 'aggregate', agg(atk=7, **{'def': 4}),
            ids=(O0, O0 + N_ORD - 1),
            fixture=fixture(unit((O0, O0 + N_ORD - 1)), others=((unit((mid,)), (5, 9), 2),))),
        run('dealt-ordinary-two-ids', 'dealt', 'output', 6, ids=(O0, O0 + N_ORD - 1),
            fixture=fixture(unit((O0, O0 + N_ORD - 1)), other=unit())),
        run('dealt-aura-holder-has-the-spear', 'dealt', 'output', 11, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((unit((d_first,), weapon_category=3), (5, 9), 2),))),
        run('dealt-aura-last-holder-has-the-spear', 'dealt', 'output', 11, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((unit((d_last,), weapon_category=3), (5, 9), 2),))),
        run('dealt-aura-holder-has-a-sword', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit(()), other=unit(), others=((unit((d_last,), weapon_category=2), (5, 9), 2),))),
        run('taken-aura-on-the-defender', 'taken', 'output', 40, ids=(),
            fixture=fixture(unit(()), subject_is_other=True, other=unit(),
                            others=((unit((t_mid,)), (5, 9), 2),))),
        run('crit-damage-aura-on-a-critical', 'taken', 'output', 65, ids=(), **T,
            fixture=fixture(unit(()), other=unit(team=1), regions=crit, others=((unit((c_mid,)), (5, 9), 2),))),
        run('subject-not-on-the-map', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), on_map=False, others=((unit((mid,)), (5, 9), 2),))),
    ]


ROUND = 0x145574AA8          # the battle round counter (i16), what turn_min / turn_max read
SMALL = {
    7800: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 6, 'per': 'party_human'}]},
    7801: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 10, 'per': 'party_monster'}]},
    7802: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 4, 'per': 'party_male'}]},
    7803: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 5, 'per': 'party_female'}]},
    7804: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 15, 'per': 'party_weapon'}], 'filter': 5},
    7805: {'family': 'dealt', 'effects': [{'value': 20}],
           'conditions': [{'kind': 'party_min', 'count': 3, 'of': 4}]},
    7806: {'family': 'dealt', 'effects': [{'value': 9}],
           'conditions': [{'kind': 'party_min', 'count': 2, 'of': 5, 'id': 6}]},
    7807: {'family': 'stats', 'effects': [{'stat': 'def', 'value': 25}], 'conditions': [{'kind': 'turn_max', 'id': 3}]},
    7808: {'family': ['dealt', 'aura'], 'effects': [{'value': 4, 'per': 'party_human'}],
           'conditions': [near(7808), {'kind': 'party_min', 'count': 2, 'of': 1}]},
}


def small_cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    hm, hf, mm, mf = 1, 2, 11, 12                # class-kind byte: human male / female, monster male / female
    crowd = ((unit((), type_code=hm), (5, 9), 2), (unit((), type_code=hf), (6, 9), 3),
             (unit((), type_code=mf), (7, 9), 4), (unit((), type_code=hm, team=1), (8, 9), 5))
    rnd = lambda n: [(ROUND, n.to_bytes(2, 'little'))]            # noqa: E731
    return [
        # 2 human allies + 1 monster ally + 1 enemy human; the holder counts itself when it qualifies
        run('party-human-holder-is-human', 'stats', 'aggregate', agg(atk=18), ids=(7800,),
            fixture=fixture(unit((7800,), type_code=hm), others=crowd)),
        run('party-human-holder-is-a-monster', 'stats', 'aggregate', agg(atk=12), ids=(7800,),
            fixture=fixture(unit((7800,), type_code=mm), others=crowd)),
        run('party-monster-holder-is-a-monster', 'stats', 'aggregate', agg(atk=20), ids=(7801,),
            fixture=fixture(unit((7801,), type_code=mm), others=crowd)),
        run('party-male-counts-human-and-monster-males', 'stats', 'aggregate', agg(atk=8), ids=(7802,),
            fixture=fixture(unit((7802,), type_code=mm), others=crowd)),
        run('party-female-holder-is-male', 'stats', 'aggregate', agg(atk=10), ids=(7803,),
            fixture=fixture(unit((7803,), type_code=hm), others=crowd)),
        run('party-alone-counts-only-the-holder', 'stats', 'aggregate', agg(atk=6), ids=(7800,),
            fixture=fixture(unit((7800,), type_code=hf))),
        run('party-not-on-the-map-counts-nothing', 'stats', 'aggregate', agg(), ids=(7800,),
            fixture=fixture(unit((7800,), type_code=hm), on_map=False, others=crowd)),
        run('party-weapon-holder-and-one-ally-have-guns', 'stats', 'aggregate', agg(atk=30), ids=(7804,),
            fixture=fixture(unit((7804,), weapon_category=5),
                            others=((unit((), weapon_category=5), (5, 9), 2), (unit((), weapon_category=2), (6, 9), 3),
                                    (unit((), weapon_category=5, team=1), (7, 9), 4)))),
        run('party-min-three-females-with-the-holder', 'dealt', 'output', 20, ids=(7805,),
            fixture=fixture(unit((7805,), type_code=hf), other=unit(),
                            others=((unit((), type_code=hf), (5, 9), 2), (unit((), type_code=mf), (6, 9), 3)))),
        run('party-min-two-females-is-not-enough', 'dealt', 'output', 0, ids=(7805,),
            fixture=fixture(unit((7805,), type_code=hm), other=unit(),
                            others=((unit((), type_code=hf), (5, 9), 2), (unit((), type_code=mf), (6, 9), 3)))),
        run('party-min-weapon-two-axes', 'dealt', 'output', 9, ids=(7806,),
            fixture=fixture(unit((7806,), weapon_category=6), other=unit(),
                            others=((unit((), weapon_category=6), (5, 9), 2),))),
        run('party-min-weapon-one-axe', 'dealt', 'output', 0, ids=(7806,),
            fixture=fixture(unit((7806,), weapon_category=6), other=unit(),
                            others=((unit((), weapon_category=2), (5, 9), 2),))),
        run('turn-max-at-the-limit', 'stats', 'aggregate', agg(**{'def': 25}), ids=(7807,),
            fixture=fixture(unit((7807,)), regions=rnd(3))),
        run('turn-max-past-the-limit', 'stats', 'aggregate', agg(), ids=(7807,),
            fixture=fixture(unit((7807,)), regions=rnd(4))),
        run('turn-max-round-zero', 'stats', 'aggregate', agg(**{'def': 25}), ids=(7807,),
            fixture=fixture(unit((7807,)), regions=rnd(0))),
        # an aura row: the count and the party_min are read on the RECIPIENT's side (the same side as the holder)
        run('aura-scaled-by-the-recipients-party', 'dealt', 'output', 12, ids=(),
            fixture=fixture(unit((), type_code=hm), other=unit(team=1),
                            others=((unit((7808,), type_code=hm), (5, 9), 2), (unit((), type_code=hf), (6, 9), 3)))),
        run('aura-party-min-not-met', 'dealt', 'output', 0, ids=(),
            fixture=fixture(unit((), type_code=mm), other=unit(team=1),
                            others=((unit((7808,), type_code=hm), (5, 9), 2),))),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    from d5lib import evility as ev
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    table = rows()
    n_rows = len(ev.table(table)[0])
    assert n_rows == ev.MAX_ROWS == 2048, n_rows
    patched = ev.build_patch(original, table)
    info = ev.section_info(patched)
    specs = [(name, target, sites) for name, (_, target, sites) in zip(h.NAMES, ev.WRAPPERS)]
    small = ev.build_patch(original, SMALL)
    small_info = ev.section_info(small)
    big_bytes = info['size']
    results, worst = [], 0
    for case in [dict(c, big=True) for c in cases()] + small_cases():
        if not case.get('big'):
            patched, info = small, small_info
        _, target, sites = next(s for s in specs if s[0] == case['family'])
        for site in sites:
            try:
                d = execute(patched, info, specs, case['family'], target, site, ids=case.get('ids', ()), abi=a.abi,
                            fixture=case['fixture'], out_value=50, original_rax=0,
                            supplied_stack_args=case.get('supplied_stack_args'))
                got = d[case.get('field', 'output')]
                assert got == case['expected'], (got, case['expected'])
                assert d['instructions'] <= BUDGET, f"{d['instructions']} instructions"
                worst = max(worst, d['instructions']) if case.get('big') else worst
                results.append(dict(name=case['name'], family=case['family'], site=hex(site), ok=True,
                                    instructions=d['instructions']))
            except Exception as exc:                 # noqa: BLE001
                results.append(dict(name=case['name'], family=case['family'], site=hex(site), ok=False,
                                    error=f'{type(exc).__name__}: {str(exc)[:200]}'))
            r = results[-1]
            print(('PASS ' if r['ok'] else 'FAIL ') + r['name'] + ' ' + r['site'] + ('' if r['ok'] else ' ' + r['error']))
    ok = all(r['ok'] for r in results)
    if a.json:
        a.json.write_text(json.dumps(dict(mode='abi' if a.abi else 'behavior', rows=n_rows, section_bytes=big_bytes,
                                          worst_instructions=worst, passed=ok, checks=results), indent=1) + '\n')
    print(f"rows {n_rows}, section {big_bytes} bytes, worst call {worst} instructions")
    print(f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
