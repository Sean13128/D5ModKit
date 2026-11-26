"""EVILFX1: the `map_squad` scale and the `rearm_first_damage` family, executed from the pinned game's
actual CALL sites (offline only).

Scale 15 `map_squad` counts deployed *allies* (same team byte) whose squad (unit +0x30A0, gate +0x30A1)
is the holder's own, never the holder.  It is D4's Evil Area count -- Friends 840, "Increase stats by 5% x
the # of dispatched Evil Area allies"; D4 FUN_1401ba0a0 counts the *other* battle units of the holder's
team whose Evil Area list meets the holder's -- mapped onto D5's squads (adapted: D5 has no Evil Areas).

Run from the stat aggregate's own call site 0x1401B9575 (unit_recalc -> unit_stats_evil_status_effects),
normal and --abi, exactly like offline_proof_carriers2.py.

Family `rearm_first_damage` (bit 1<<26) rides the existing round-edge wrapper (turn_per_unit_end_round_upkeep
0x1401E5AF0, its one static site 0x1405F8FFC): after the original returns, a unit with a holding row gets its
stat record byte +0xDF9 cleared -- the byte D5's First Impression (6047) tests in damage_nullify_predicate and
damage_apply_damage sets on the unit's first damage of the stage.  With 6047 on the unit (class alias) that is
D4 Tyrant Guard 667, "Nullify the first damage received every turn".

  D5Modkit/.venv-macos/bin/python evility/offline_proof_evilfx1.py [--abi]
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from d5lib import evility as ev                                      # noqa: E402
from abi_engine_ex05c import execute                                 # noqa: E402
from offline_proof_carriers2 import fixture                          # noqa: E402
from offline_proof_oleffects import (ORIGINAL, ORIGINAL_SHA, REVENGE_GAUGE, REVENGE_STATUS,  # noqa: E402
                                     unit)
from offline_proof_oleffects import fixture as ol_fixture            # noqa: E402
import struct                                                        # noqa: E402

STAT_BASE, STAT_STRIDE, FIRST_HIT = 0x141067DC8, 0xE98, 0xDF9
ROUND_SITE = 0x1405F8FFC

FRIENDS = 8840


def u(*, ids=(), team=0, char_id=10, squad=None):
    return unit(ids, team=team, char_id=char_id, squad=squad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    args = ap.parse_args()
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA

    rows = {
        7710: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 7, 'per': 'map_squad'}]},
        # D4 840 Friends, the row the importer writes (d4-evility-additions.json)
        FRIENDS: json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']['D4_Class_1220']['behaviors']['evilities']['8840'],
    }
    patched = ev.build_patch(raw, rows)
    info = ev.section_info(patched)
    specs = [(name, ev.wrapper(name)[1], ev.wrapper(name)[2]) for name in ev.WRAPPER_NAMES.values()]

    def stats(subject, others):
        return execute(patched, info, specs, 'stats', ev.STATUS, 0x1401B9575, abi=args.abi,
                       fixture=fixture(subject, others))['aggregate']

    checks = []

    def case(name, subject, others, expect):
        agg = stats(subject, others)
        got = agg[2] if isinstance(expect, int) else agg[:8]
        assert got == expect, (name, got, expect)
        checks.append(name)
        print('PASS', name, '->', got)

    mates = [(u(squad=(3, 1)), 1, True), (u(squad=(3, 1)), 2, True), (u(squad=(3, 1)), 3, True)]
    noise = [(u(squad=(4, 1)), 4, True),            # another squad
             (u(squad=(3, 1), team=1), 5, True),    # same squad byte, enemy team
             (u(squad=(3, 1)), 6, False),           # same squad, not deployed
             (u(squad=(3, 0)), 7, True),            # id 3 but no assignment (gate 0)
             (u(squad=(0xFF, 1)), 8, True)]         # id -1
    case('three deployed squad mates count, nothing else does (7 x 3)',
         u(ids=(7710,), squad=(3, 1)), mates + noise, 21)
    case('the holder alone counts 0 (never itself)', u(ids=(7710,), squad=(3, 1)), [], 0)
    case('holder with no squad assignment counts 0', u(ids=(7710,), squad=(3, 0)), mates, 0)
    case('holder with squad id -1 counts 0', u(ids=(7710,), squad=(0xFF, 1)), mates, 0)
    case('squad 0 is a real squad', u(ids=(7710,), squad=(0, 1)),
         [(u(squad=(0, 1)), 1, True), (u(squad=(0, 0)), 2, True)], 7)
    case('unlearned: no row, no change', u(squad=(3, 1)), mates, 0)
    # D4 840 Friends on Prism Red (char 10400): two dispatched squad mates -> +10 on the six stats (D4SIG4: not HP/SP)
    case('D4 840 Friends: +5 x 2 dispatched squad mates on ATK DEF INT RES HIT SPD, none on HP SP',
         u(ids=(FRIENDS,), char_id=10400, squad=(2, 1)),
         [(u(squad=(2, 1)), 1, True), (u(squad=(2, 1)), 2, True), (u(squad=(5, 1)), 3, True)], [0, 0] + [10] * 6)
    # ---------------------------------------------------------------- rearm_first_damage (round edge)
    rrows = {8667: {'family': 'rearm_first_damage'},
             7720: {'family': 'rearm_first_damage', 'condition': {'kind': 'hp_below', 'id': 50}},
             7721: {'family': 'permanent_revenge'}}
    rpatched = ev.build_patch(raw, rrows)
    rinfo = ev.section_info(rpatched)
    _, rtarget, rsites = ev.wrapper('revenge')
    assert rsites == [ROUND_SITE]

    def round_edge(ids, *, idx=5, flag=1, hp=None, max_hp=None, rax=0):
        subject = unit(ids, hp=hp, max_hp=max_hp)
        struct.pack_into('<I', subject, 0x4348, idx)
        slot = STAT_BASE + 5 * STAT_STRIDE + FIRST_HIT - 1          # qword watched: bytes +0xDF8..+0xDFF
        base = ol_fixture(subject)

        def setup(write):
            base(write)
            write(slot, bytes([0xAA, flag, 0xBB, 0xCC, 0xDD, 0xEE, 0x11, 0x22]))
        d = execute(rpatched, rinfo, specs, 'revenge', rtarget, ROUND_SITE, ids=ids, abi=args.abi,
                    fixture=setup, original_rax=rax, watch=slot,
                    stub_returns={REVENGE_GAUGE: 0, REVENGE_STATUS: 0})
        after = d['watched']['after'].to_bytes(8, 'little')
        return after, d

    def rcase(name, expect_flag, **kw):
        after, d = round_edge(**kw)
        assert after[1] == expect_flag, (name, after.hex())
        assert after[0] == 0xAA and after[2:] == bytes([0xBB, 0xCC, 0xDD, 0xEE, 0x11, 0x22]), (name, after.hex())
        checks.append(name)
        print('PASS', name, '-> +0xDF9 =', after[1])
        return d

    rcase('rearm: the 6047 byte is cleared at the round edge', 0, ids=(6047, 8667))
    rcase('rearm: unlearned leaves the byte set', 1, ids=(6047,))
    rcase('rearm: condition holds (hp 10/100 < 50)', 0, ids=(7720,), hp=10, max_hp=100)
    rcase('rearm: condition fails (hp 90/100)', 1, ids=(7720,), hp=90, max_hp=100)
    rcase('rearm: an already armed byte stays 0', 0, ids=(8667,), flag=0)
    rcase('rearm: stat index out of range (0x28a) writes nothing', 1, ids=(8667,), idx=0x28A)
    d = rcase('rearm: the original answer is returned untouched', 0, ids=(8667,), rax=1234)
    assert d['output'] == 1234, d['output']
    d = rcase('rearm + permanent_revenge on one unit: both happen', 0, ids=(7721, 8667))
    assert {hex(REVENGE_GAUGE), hex(REVENGE_STATUS)} <= set(d['call_edges']), d['call_edges']
    d = rcase('rearm alone issues no revenge pair', 0, ids=(8667,))
    assert hex(REVENGE_GAUGE) not in d['call_edges'], d['call_edges']
    print(f'{len(checks)}/{len(checks)} checks passed')


if __name__ == '__main__':
    main()
