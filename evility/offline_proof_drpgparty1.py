"""DRPGPARTY1: the class registry and its two conditions, through the pinned game's real patched CALL sites
(Unicorn), normal and --abi, in the way offline_proof_drpgevil1c.py runs them.  Offline only.

  * self_potential (kind 69): "party members of potential type Queen / Rook ... get X".  The recipient's class id
    (unit +0x2E04) is looked up in the registry (evil_classinfo, a binary search over the sorted class dwords).
  * party_weapons_distinct (kind 70): "the party's favourite weapon types are all different".  One walk of the
    battle table over the unit's own side (itself included); a class with no registered favourite weapon breaks it.
  * the aura rows are written exactly as tools/build_drpg_evility_overlay.py writes them (own row + aura row with
    near_has), and the registry is the one tools/build_drpg_class_registry.py writes (a slice of it is also
    checked for shape against d5lib/importers/drpg-class-registry.json).

Negative controls (a PASS must be able to fail):
  * wrong expectation: the same fixtures run with an expectation moved by one must MISMATCH (the check inverts);
  * mutated registry: Queen swapped for Rook in the registry and weapons swapped, same rows and fixtures: the
    answers must change (so the cases really read the registry, not a constant).

D5_KIT=<worktree> <unicorn python> evility/offline_proof_drpgparty1.py [--abi] [--json OUT]
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
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_ex05e as h                         # noqa: E402
from abi_engine_ex05c import execute                    # noqa: E402

unit, fixture = h.unit, h.fixture
h.EXTRA = tuple(0x400090000 + 0x8000 * i for i in range(12))      # up to 12 extra units (a 10-unit side plus 2)
BT, STRIDE = h.BATTLE_TABLE, h.STRIDE

# ---- the registry used by the cases: class -> (favourite weapon item category, potential type)
Q, R, K, B, KING, PAWN = 6, 3, 5, 4, 1, 2           # potential types: Queen, Rook, Knight, Bishop, King, Pawn
REG = {
    1: (6, Q), 2: (1, R),                               # first entries of the table
    1001: (2, Q), 1002: (1, R), 1003: (6, Q), 1004: (2, K), 1005: (9, B), 1006: (3, KING), 1007: (4, PAWN),
    1008: (5, R), 1009: (7, K), 1010: (8, Q), 1011: (0, K), 1012: (3, 0),
    30000: (4, B), 65535: (5, Q),                        # the u16 edge
}
for n in range(100, 200):                              # filler so the binary search has depth
    REG[n] = (1 + n % 9, 1 + n % 6)


def classes(reg=REG):
    return {str(k): {'weapon': w, 'potential': p} for k, (w, p) in reg.items()}


def near(i, of=1):
    return {'kind': 'near_has', 'of': of, 'radius': 30, 'id': i}


POT = lambda *t: {'kind': 'self_potential', 'types': list(t)}          # noqa: E731
DIST = {'kind': 'party_weapons_distinct'}
ROWS = {
    7900: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 10}], 'conditions': [POT(Q)]},
    7901: {'family': 'stats', 'effects': [{'stat': 'def', 'value': 7}], 'conditions': [POT(R, K)]},
    7902: {'family': 'stats', 'effects': [{'stat': 'res', 'value': 5}], 'conditions': [{'kind': 'self_potential', 'id': 63}]},
    7903: {'family': 'dealt', 'effects': [{'value': 30}], 'conditions': [DIST]},
    7904: {'family': ['stats', 'aura'], 'effects': [{'stat': 'spd', 'value': 12}], 'conditions': [DIST, near(7904)]},
    7905: {'family': ['stats', 'aura'], 'effects': [{'stat': 'hp', 'value': 24}], 'conditions': [POT(Q), near(7905)]},
    7906: {'family': 'stats', 'effects': [{'stat': 'int', 'value': 9}], 'conditions': [POT(KING, B)]},
}


def agg(**kw):
    out = [0] * 18
    for k, v in kw.items():
        out[('hp', 'sp', 'atk', 'def', 'int', 'res', 'hit', 'spd').index(k)] = v
    return out


def regions_flag(slot, offset, data):
    return (BT + slot * STRIDE + offset, data)


def cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    u = lambda ids=(), cls=10, **kw: unit(ids, char_id=cls, **kw)      # noqa: E731
    A, Bc, C, D = 1001, 1002, 1003, 1004                # sword/Queen, fist/Rook, axe/Queen, sword/Knight
    c = []
    # ------------------------------------------------------------------ self_potential, the holder's own row
    c += [
        run('potential-queen-holder-is-a-queen', 'stats', 'aggregate', agg(atk=10), ids=(7900,),
            fixture=fixture(u((7900,), A))),
        run('potential-queen-holder-is-a-rook', 'stats', 'aggregate', agg(), ids=(7900,),
            fixture=fixture(u((7900,), Bc))),
        run('potential-queen-class-not-in-the-registry', 'stats', 'aggregate', agg(), ids=(7900,),
            fixture=fixture(u((7900,), 4242))),
        run('potential-queen-class-id-above-u16-must-not-alias', 'stats', 'aggregate', agg(), ids=(7900,),
            fixture=fixture(u((7900,), 0x10000 + A))),
        run('potential-queen-class-zero', 'stats', 'aggregate', agg(), ids=(7900,),
            fixture=fixture(u((7900,), 0))),
        run('potential-queen-unlearned-row-does-nothing', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), A))),
        run('potential-queen-registered-with-no-type', 'stats', 'aggregate', agg(), ids=(7900,),
            fixture=fixture(u((7900,), 1012))),
        run('potential-rook-or-knight-rook', 'stats', 'aggregate', agg(**{'def': 7}), ids=(7901,),
            fixture=fixture(u((7901,), Bc))),
        run('potential-rook-or-knight-knight', 'stats', 'aggregate', agg(**{'def': 7}), ids=(7901,),
            fixture=fixture(u((7901,), D))),
        run('potential-rook-or-knight-queen-is-not', 'stats', 'aggregate', agg(), ids=(7901,),
            fixture=fixture(u((7901,), A))),
        run('potential-mask-63-bishop', 'stats', 'aggregate', agg(res=5), ids=(7902,),
            fixture=fixture(u((7902,), 1005))),
        run('potential-mask-63-king', 'stats', 'aggregate', agg(res=5), ids=(7902,),
            fixture=fixture(u((7902,), 1006))),
        run('potential-mask-63-unregistered-gets-nothing', 'stats', 'aggregate', agg(), ids=(7902,),
            fixture=fixture(u((7902,), 4243))),
        run('potential-king-or-bishop-pawn-is-not', 'stats', 'aggregate', agg(), ids=(7906,),
            fixture=fixture(u((7906,), 1007))),
        run('potential-king-or-bishop-king', 'stats', 'aggregate', agg(int=9), ids=(7906,),
            fixture=fixture(u((7906,), 1006))),
        # the binary search: both ends, the middle, a hole between two entries, the u16 edge
        run('registry-first-entry', 'stats', 'aggregate', agg(atk=10), ids=(7900,), fixture=fixture(u((7900,), 1))),
        run('registry-second-entry-is-a-rook', 'stats', 'aggregate', agg(), ids=(7900,), fixture=fixture(u((7900,), 2))),
        run('registry-hole-between-entries', 'stats', 'aggregate', agg(), ids=(7900,), fixture=fixture(u((7900,), 3))),
        run('registry-filler-class-in-the-middle-is-a-queen', 'stats', 'aggregate', agg(atk=10), ids=(7900,),
            fixture=fixture(u((7900,), 107))),                  # filler: potential 1 + 107 % 6 = 6, a Queen
        run('registry-filler-class-in-the-middle-is-not', 'stats', 'aggregate', agg(), ids=(7900,),
            fixture=fixture(u((7900,), 108))),                  # filler: potential 1 + 108 % 6 = 1, a King
        run('registry-the-u16-edge', 'stats', 'aggregate', agg(atk=10), ids=(7900,), fixture=fixture(u((7900,), 65535))),
        run('registry-just-below-the-edge', 'stats', 'aggregate', agg(), ids=(7900,), fixture=fixture(u((7900,), 65534))),
        run('registry-30000-is-a-bishop', 'stats', 'aggregate', agg(), ids=(7900,), fixture=fixture(u((7900,), 30000))),
    ]
    # ------------------------------------------------------------------ the potential aura (own row + aura row)
    prov = lambda **kw: u((7905,), 1002, **kw)             # noqa: E731  a Rook holding 7905 (a Queen's aura)
    c += [
        run('potential-aura-queen-recipient', 'stats', 'aggregate', agg(hp=24), ids=(),
            fixture=fixture(u((), A), others=((prov(), (5, 9), 2),))),
        run('potential-aura-rook-recipient-gets-nothing', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), Bc), others=((prov(), (5, 9), 2),))),
        run('potential-aura-unregistered-ally-gets-nothing', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), 4244), others=((prov(), (5, 9), 2),))),
        run('potential-aura-provider-out-of-radius', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), A), others=((prov(), (5, 40), 2),))),
        run('potential-aura-provider-is-an-enemy', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), A), others=((prov(team=1), (5, 9), 2),))),
        # one row per evility id: two providers of the SAME evility do not stack (as for every kit aura)
        run('potential-aura-two-providers-of-one-evility-do-not-stack', 'stats', 'aggregate', agg(hp=24), ids=(),
            fixture=fixture(u((), A), others=((prov(), (5, 9), 2), (prov(), (6, 9), 3)))),
    ]
    # ------------------------------------------------------------------ party_weapons_distinct
    ally = lambda cls, slot, x=5, **kw: (u((), cls, **kw), (x, 9), slot)          # noqa: E731
    c += [
        run('distinct-three-allies-all-different', 'dealt', 'output', 30, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(C, 3)))),
        run('distinct-two-swords', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(D, 3)))),
        run('distinct-the-duplicate-is-the-last-ally', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(C, 3), ally(1008, 4),
                                                                      ally(1009, 5), ally(1004, 6)))),
        run('distinct-an-unregistered-ally-breaks-it', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(4242, 3)))),
        run('distinct-a-class-with-no-favourite-weapon-breaks-it', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(1011, 3)))),
        run('distinct-the-holder-unregistered', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), 4242), other=u(team=1), others=(ally(Bc, 2),))),
        run('distinct-alone-is-vacuously-true', 'dealt', 'output', 30, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1))),
        run('distinct-alone-unregistered-is-false', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), 4242), other=u(team=1))),
        run('distinct-an-enemy-with-the-same-weapon-does-not-count', 'dealt', 'output', 30, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(D, 3, team=1)))),
        run('distinct-an-unregistered-enemy-does-not-count', 'dealt', 'output', 30, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(4242, 3, team=1)))),
        run('distinct-a-carried-duplicate-is-not-on-the-map', 'dealt', 'output', 30, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(D, 3)),
                            regions=[regions_flag(3, 0x2ee, struct.pack('<h', 1))])),
        run('distinct-an-inactive-duplicate-is-not-on-the-map', 'dealt', 'output', 30, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(Bc, 2), ally(D, 3)),
                            regions=[regions_flag(3, 0x2e8, b'\x00')])),
        run('distinct-holder-not-on-the-map', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), on_map=False, others=(ally(Bc, 2),))),
        run('distinct-class-id-above-u16-is-unregistered', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), A), other=u(team=1), others=(ally(0x10000 + 1002, 2),))),
    ]
    eight = [u((), cls) for cls in (1001, 1002, 1006, 1007, 1008, 1005, 1009, 1010)]     # weapons 2 1 3 4 5 9 7 8
    eight_side = tuple((x, (5, 9), 2 + i) for i, x in enumerate(eight))
    tenth = eight_side + ((u((), 1004), (5, 9), 10),)                                    # + a second sword
    c += [
        run('distinct-nine-units-all-nine-weapons', 'dealt', 'output', 30, ids=(7903,),
            fixture=fixture(u((7903,), 1003), other=u(team=1), others=eight_side)),          # holder: axe (6)
        run('distinct-a-tenth-member-must-repeat-one-of-the-nine', 'dealt', 'output', 0, ids=(7903,),
            fixture=fixture(u((7903,), 1003), other=u(team=1), others=tenth)),
    ]
    # the aura form: the recipient's own side is judged, whoever holds the evility
    hold = lambda **kw: u((7904,), 1002, **kw)             # noqa: E731
    c += [
        run('distinct-aura-recipient-in-a-distinct-party', 'stats', 'aggregate', agg(spd=12), ids=(),
            fixture=fixture(u((), A), others=((hold(), (5, 9), 2), ally(C, 3)))),
        run('distinct-aura-party-has-two-swords', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), A), others=((hold(), (5, 9), 2), ally(D, 3)))),
        run('distinct-aura-provider-out-of-radius', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), A), others=((hold(), (5, 40), 2), ally(C, 3)))),
        run('distinct-aura-enemy-provider', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(u((), A), others=((hold(team=1), (5, 9), 2), ally(C, 3)))),
    ]
    return c


def build(rows, reg):
    from d5lib import evility as ev
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    patched = ev.build_patch(original, rows, None, classes(reg))
    specs = [(ev.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in ev.WRAPPERS]
    return patched, ev.section_info(patched), specs


def run_case(bundle, case, abi):
    patched, info, specs = bundle
    _, target, sites = next(s for s in specs if s[0] == case['family'])
    out = []
    for site in sites:
        d = execute(patched, info, specs, case['family'], target, site, ids=case.get('ids', ()), abi=abi,
                    fixture=case['fixture'], out_value=50, original_rax=0,
                    supplied_stack_args=case.get('supplied_stack_args'))
        out.append((site, d))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    from d5lib import evility as ev
    bundle = build(ROWS, REG)
    results, got_by_case = [], {}
    for case in cases():
        for site, d in run_case(bundle, case, a.abi):
            got = d[case['field']]
            ok = got == case['expected']
            got_by_case[case['name']] = got
            results.append(dict(name=case['name'], family=case['family'], site=hex(site), ok=ok,
                                got=got if not ok else None, expected=case['expected'], instructions=d['instructions']))
            print(('PASS ' if ok else 'FAIL ') + case['name'] + ' ' + hex(site) + ('' if ok else f' got {got} want {case["expected"]}'))
    # ---- negative control 1: a deliberately wrong expectation must mismatch on a spread of cases
    wrong = 0
    for case in cases():
        if case['name'] not in ('potential-queen-holder-is-a-queen', 'potential-queen-holder-is-a-rook',
                                'distinct-three-allies-all-different', 'distinct-two-swords',
                                'potential-aura-queen-recipient', 'distinct-aura-party-has-two-swords'):
            continue
        for site, d in run_case(bundle, case, a.abi):
            got = d[case['field']]
            exp = case['expected']
            deliberately_wrong = [x + 1 for x in exp] if isinstance(exp, list) else exp + 1
            mismatch = got != deliberately_wrong
            wrong += 1
            results.append(dict(name='negative-control-wrong-expectation-' + case['name'], site=hex(site),
                                ok=mismatch, expected_wrong=deliberately_wrong, got=got))
            print(('PASS ' if mismatch else 'FAIL ') + 'negative control (wrong expectation) ' + case['name'] + ' ' + hex(site))
    # ---- negative control 2: mutate the registry (every favourite weapon the same, potential types rotated);
    # the answers MUST change
    mutated = {k: (1 if w else 0, (p % 6) + 1 if p else p) for k, (w, p) in REG.items()}
    mbundle = build(ROWS, mutated)
    flips = 0
    for case in cases():
        if case['name'] not in ('potential-queen-holder-is-a-queen', 'distinct-three-allies-all-different',
                                'potential-aura-queen-recipient', 'potential-rook-or-knight-rook'):
            continue
        for site, d in run_case(mbundle, case, a.abi):
            got = d[case['field']]
            flipped = got != case['expected']
            flips += 1
            results.append(dict(name='negative-control-mutated-registry-' + case['name'], site=hex(site),
                                ok=flipped, got=got, expected_unmutated=case['expected']))
            print(('PASS ' if flipped else 'FAIL ') + 'negative control (mutated registry changes the answer) '
                  + case['name'] + ' ' + hex(site))
    # ---- shape checks that need no emulation
    rows, conds, fx = ev.table(ROWS)
    results.append(dict(name='conditions-encode-as-69-and-70', ok={69, 70} <= {c[0] for c in conds}))
    try:
        ev.class_table({'5': {'weapon': 10, 'potential': 1}})
        bad = False
    except ValueError:
        bad = True
    results.append(dict(name='registry-rejects-an-out-of-range-weapon', ok=bad))
    try:
        ev._merge_classes({1: {'weapon': 1, 'potential': 1}}, {'1': {'weapon': 2, 'potential': 1}})
        bad = False
    except ValueError:
        bad = True
    results.append(dict(name='registry-merge-rejects-a-conflicting-class', ok=bad))
    ok = all(r['ok'] for r in results)
    if a.json:
        a.json.write_text(json.dumps(dict(mode='abi' if a.abi else 'behavior', passed=ok, checks=results), indent=1) + '\n')
    print(f"{sum(r['ok'] for r in results)}/{len(results)} checks passed "
          f"({wrong} wrong-expectation controls, {flips} mutated-registry controls)")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
