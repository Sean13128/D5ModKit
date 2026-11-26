"""LONGTAIL2 offline proof: Piyori XENO main evility 28400 (leaderskill 4001 + 4005), the intercept half (counter + taken -50 for the
first 3 rounds), through the real patched CALL sites of wrap_taken and wrap_counter (EX-05e harness, the game's own callee stubbed).

The rows are read verbatim from the shipped overlay (d5lib/importers/drpg-evility-overlay.json, base 400).  The round counter is the
i16 at 0x145574AA8, which the game sets to 1 at battle start (decomp FUN_140523970, called by battle_start_common) and raises at each
round edge (turn_ctl_s6_update); turn_max 3 therefore holds for counter values 1, 2 and 3.

D5_KIT=<worktree> <unicorn python> evility/offline_proof_longtail2_piyori.py [--abi] [--control NAME]
Controls (a deliberately broken row set; the proof must then FAIL): no-turn (the window is dropped), sign (+50), no-counter, wrong-id
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'evility'))
import offline_proof_ex05e as h                         # noqa: E402
from d5lib.importers import _drpg_text   # noqa: E402  (TEXTHASH-DRPG: JP names are hashes; these proofs read ids, rows and our own wording)
from abi_engine_ex05c import execute                    # noqa: E402

ROUND = 0x145574AA8
RID = 28400
unit, fixture = h.unit, h.fixture


def shipped_rows():
    doc = _drpg_text.load_authored(KIT / 'd5lib/importers/drpg-evility-overlay.json')
    ev = doc['bases']['400']['evilities'][0]
    assert ev['id'] == RID and ev['rpg_ids'] == [4001, 4005], ev
    return ev['rows']


def controlled(rows, control):
    rows = json.loads(json.dumps(rows))
    cnt = [r for r in rows if r['family'] == 'counter']
    tkn = [r for r in rows if r['family'] == 'taken']
    assert len(cnt) == 1 and len(tkn) == 1 and cnt[0]['conditions'] == [{'kind': 'turn_max', 'id': 3}] == tkn[0]['conditions']
    if control == 'no-turn':
        cnt[0].pop('conditions')
        tkn[0].pop('conditions')
    elif control == 'sign':
        tkn[0]['effects'][0]['value'] = 50
    elif control == 'no-counter':
        rows.remove(cnt[0])
    elif control == 'wrong-id':
        return {RID + 1: rows}
    return {RID: rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    a = ap.parse_args()
    from d5lib import evility as ev
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    table = controlled(shipped_rows(), a.control)
    patched = ev.build_patch(original, table)
    info = ev.section_info(patched)
    specs = [(n, *ev.wrapper(n)[1:]) for n in ('taken', 'counter')]
    rnd = lambda n: [(ROUND, n.to_bytes(2, 'little'))]            # noqa: E731
    cases = []
    for r in (1, 2, 3, 4, 5, 999):
        inside = r <= 3
        cases += [
            (f'round {r}: damage taken by the holder 50 -> {25 if inside else 50}', 'taken', 50, 25 if inside else 50,
             dict(ids=(RID,), fixture=fixture(unit((RID,)), subject_is_other=True, other=unit(team=1), regions=rnd(r)))),
            (f'round {r}: the holder may counter: {1 if inside else 0}', 'counter', 50, 1 if inside else 0,
             dict(ids=(RID,), fixture=fixture(unit((RID,)), other=unit(team=1), regions=rnd(r)))),
        ]
    cases += [
        ('a unit without the evility: damage taken stays 50 (round 1)', 'taken', 50, 50,
         dict(ids=(), fixture=fixture(unit(()), subject_is_other=True, other=unit(team=1), regions=rnd(1)))),
        ('a unit without the evility: no counter (round 1)', 'counter', 50, 0,
         dict(ids=(), fixture=fixture(unit(()), other=unit(team=1), regions=rnd(1)))),
        ('the evility on the ATTACKER does not halve what its victim takes (round 1)', 'taken', 50, 50,
         dict(ids=(), fixture=fixture(unit(()), subject_is_other=True, other=unit((RID,), team=1), regions=rnd(1)))),
        ('the holder at battle start (counter 1) with 40 other ids around the row', 'taken', 50, 25,
         dict(ids=tuple(range(1, 41)) + (RID,), fixture=fixture(unit(tuple(range(1, 41)) + (RID,)), subject_is_other=True,
                                                               other=unit(team=1), regions=rnd(1)))),
    ]
    ok = n = 0
    for name, family, out_value, want, kw in cases:
        _, target, sites = next(s for s in specs if s[0] == family)
        for site in sites:
            n += 1
            try:
                d = execute(patched, info, specs, family, target, site, abi=a.abi, out_value=out_value, original_rax=0, **kw)
                got = d['output']
                assert got == want, (got, want)
                ok += 1
                print(f'PASS {name} {site:#x}')
            except Exception as exc:                 # noqa: BLE001
                print(f'FAIL {name} {site:#x}: {type(exc).__name__}: {str(exc)[:160]}')
    print(f"{ok}/{n} {'abi' if a.abi else 'behavior'}")
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
