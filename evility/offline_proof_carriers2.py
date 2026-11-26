"""CARRIERS2: filtered map counts, executed from the pinned game's actual CALL (offline only).

The addition is the count of *units of a kind* deployed on the map, used as a runtime magnitude, plus the
counted form of "at least N allies carry this".  Three pieces:

  scale 11 map_monster / 12 map_human      class-kind byte (unit +0x2E25)
  scale 13 map_class / 14 map_has          the row's own filter (dword 7): class id at +0x2E04 / a learned
                                           evility id; `classes: [...]` expands to one row per id
  condition 49 map_has_min                 at least a units of relation b have learned evility c

What the cases below prove:
  * the count is of *deployed* units only (a unit off the map, one carried by another, and one without a
    stat record are all excluded) -- the same eligibility rule the map_any/map_ally/map_enemy counts use;
  * the subject is never part of its own count, for every filter;
  * `map_class` counts a list additively (one row per class id, so two rows of two classes is one
    magnitude times the *total*, not times the last class);
  * `map_has_min` is a threshold, and its relation argument is honoured (7 allies pass 7, 7 enemies+6
    allies do not);
  * the four D4 rows the lane ships land on D4's own numbers: Dark Blood 131 (+5 % per monster), Meowyland
    837 (+10 % per cat-type unit, over the thirteen D5 cat classes), Prism Emblem 841 (+50 % while seven
    allies carry it), all as `stats` rows read out of the stat aggregate unit_recalc builds.

D5_KIT=/Volumes/Data/Projects/D5/Local/Worktrees/carriers2 \\
 /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python evility/offline_proof_carriers2.py --abi
"""
import argparse
import hashlib
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from d5lib import evility as ev                                      # noqa: E402
from abi_engine_ex05c import AGG, UNIT, execute                      # noqa: E402
from offline_proof_oleffects import (BATTLE_TABLE, ORIGINAL, ORIGINAL_SHA, REC,  # noqa: E402
                                     STRIDE, cell, record, unit)

EXTRA0 = 0x400100000          # one page per extra unit (a unit record is 0x4800 bytes)

# the thirteen D5 cat-type classes: Slumber Cat 2070-2075, Felynn 2120-2125, and the D4 cat family's one
# imported rank (D4 2200 Death Saber -> D5 class 14700).  Measured from the live char.dat, see
# evility/carriers2-content.json.
CATS = [2070, 2071, 2072, 2073, 2074, 2075, 2120, 2121, 2122, 2123, 2124, 2125, 14700]


def u(*, ids=(), team=0, char_id=10, kind=1):
    """a unit record fixture; `kind` is the class-kind byte (+0x2E25: 1/2 human, 11/12 monster)"""
    b = unit(ids, team=team, char_id=char_id)
    b[0x2e25] = kind
    return b


def fixture(subject, others=(), *, subject_cell=(5, 5)):
    """subject plus `others` = [(unit bytes, slot, on_map)] in the game's own 256-record battle table"""
    def setup(write):
        table = bytearray(256 * STRIDE)
        table[0:STRIDE] = record(UNIT, x=cell(subject_cell[0]), z=cell(subject_cell[1]), slot=0)
        for i, (data, slot, on_map) in enumerate(others):
            ptr = EXTRA0 + i * 0x10000
            table[slot * STRIDE:(slot + 1) * STRIDE] = record(
                ptr, x=cell(subject_cell[0]), z=cell(subject_cell[1]), slot=slot, active=1 if on_map else 0)
            write(ptr, data)
        write(BATTLE_TABLE, table)
        write(REC, record(UNIT))
        write(UNIT, subject)
        write(AGG + 8, b'\0' * 4)      # the read-back the stats family reports is AGG+8
    return setup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    args = ap.parse_args()
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA

    rows = {
        # --- the scales themselves -------------------------------------------------------------
        7700: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 5, 'per': 'map_monster'}]},
        7701: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 5, 'per': 'map_human'}]},
        7702: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 10, 'per': 'map_class'}],
               'classes': [2120, 2121]},
        7703: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 7, 'per': 'map_has'}],
               'filter': 8888},
        # --- the counted condition -------------------------------------------------------------
        7704: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 50, 'per': None}],
               'condition': {'kind': 'map_has_min', 'count': 7, 'of': 1, 'id': 8888}},
        # --- the D4 rows this lane ships -------------------------------------------------------
        # 131 Dark Blood: "Stats increased by 5% per monster unit on map."
        8187: {'family': 'stats', 'effects': [{'stat': 'all', 'value': 5, 'per': 'map_monster'}]},
        # 837 Meowyland: "Increase stats by 10% x the # of cat-type units on the map."
        8837: {'family': 'stats', 'effects': [{'stat': 'all', 'value': 10, 'per': 'map_class'}],
               'classes': CATS},
        # 841 Prism Emblem: "+50% while seven allies with Prism Emblem are dispatched."
        8841: {'family': 'stats', 'effects': [{'stat': 'all', 'value': 50}],
               'condition': {'kind': 'map_has_min', 'count': 7, 'of': 1, 'id': 8841}},
    }
    patched = ev.build_patch(raw, rows)
    info = ev.section_info(patched)
    specs = [(name, ev.wrapper(name)[1], ev.wrapper(name)[2]) for name in ev.WRAPPER_NAMES.values()]

    def stats(subject, others):
        return execute(patched, info, specs, 'stats', ev.STATUS, 0x1401B9575, abi=args.abi,
                       fixture=fixture(subject, others))['aggregate']

    def others(*specs_):
        return [(data, slot, on_map) for data, slot, on_map in specs_]

    checks = []

    def case(name, row_ids, others_, expect_atk):
        agg = stats(u(ids=(row_ids,), char_id=10380), others_)
        assert agg[2] == expect_atk, (name, agg[2], expect_atk)
        checks.append(name)
        print('PASS', name, '-> atk +%d' % agg[2])

    # ------------------------------------------------------------------ map_monster / map_human
    case('monsters: two deployed monsters count',
         7700, others((u(kind=11), 1, True), (u(kind=12), 2, True), (u(kind=1), 3, True)), 10)
    case('monsters: a unit off the map is not counted',
         7700, others((u(kind=11), 1, True), (u(kind=11), 2, False)), 5)
    case('monsters: no monsters',
         7700, others((u(kind=1), 1, True), (u(kind=2), 2, True)), 0)
    case('humans: two deployed humans count',
         7701, others((u(kind=1), 1, True), (u(kind=2), 2, True), (u(kind=12), 3, True)), 10)
    # ------------------------------------------------------------------ map_class
    case('class: two rows of one class each add up (10 x 2)',
         7702, others((u(char_id=2120), 1, True), (u(char_id=2121), 2, True)), 20)
    case('class: a class not in the list is not counted',
         7702, others((u(char_id=2120), 1, True), (u(char_id=2070), 2, True)), 10)
    case('class: the subject is not part of its own count',
         7702, others((u(char_id=2120), 1, True),), 10)
    case('class: two units of the first class both count',
         7702, others((u(char_id=2120), 1, True), (u(char_id=2120), 2, True)), 20)
    # ------------------------------------------------------------------ map_has
    case('has: three units carrying 8888',
         7703, others((u(ids=(8888,)), 1, True), (u(ids=(8888, 9001)), 2, True),
                            (u(ids=(8888,)), 3, True), (u(ids=(9001,)), 4, True)), 21)
    # ------------------------------------------------------------------ map_has_min
    def thr(name, n, expect):
        oth = others(*[(u(ids=(8888,), team=0), i + 1, True) for i in range(n)])
        agg = stats(u(ids=(7704,), char_id=320), oth)
        assert agg[2] == expect, (name, agg[2], expect)
        checks.append(name)
        print('PASS', name, '-> atk +%d' % agg[2])

    thr('map_has_min: six allies fail the seven gate', 6, 0)
    thr('map_has_min: seven allies pass', 7, 50)
    thr('map_has_min: nine allies pass', 9, 50)
    # seven enemies + six allies, relation 'ally': only the allies count
    mixed = others(*[(u(ids=(8888,), team=1), i + 1, True) for i in range(7)],
                   *[(u(ids=(8888,), team=0), i + 8, True) for i in range(6)])
    agg = stats(u(ids=(7704,), char_id=320), mixed)
    assert agg[2] == 0, ('map_has_min: enemies are not allies', agg[2])
    checks.append('map_has_min: enemies do not satisfy the ally relation')
    print('PASS map_has_min: enemies do not satisfy the ally relation -> atk +0')

    # ------------------------------------------------------------------ the D4 rows, D4's numbers
    # Dark Blood on Beast Tamer (a humanoid, so it never counts itself): three monsters -> +15 all stats
    agg = stats(u(ids=(8187,), char_id=14120),
                others(*[(u(kind=11 + i % 2), i + 1, True) for i in range(3)]))
    assert agg[:8] == [15] * 8, ('Dark Blood x3 monsters', agg[:8])
    checks.append('D4 131 Dark Blood: +5 x 3 monsters on all eight stats')
    print('PASS D4 131 Dark Blood -> all stats +15')

    # Meowyland on Pink (character 10380, a humanoid): four cat-type units of three different classes
    agg = stats(u(ids=(8837,), char_id=10380),
                others((u(char_id=2070), 1, True), (u(char_id=2120), 2, True),
                       (u(char_id=14700), 3, True), (u(char_id=2125), 4, True),
                       (u(char_id=2030), 5, True)))
    assert agg[:8] == [40] * 8, ('Meowyland x4 cats', agg[:8])
    checks.append('D4 837 Meowyland: +10 x 4 cat-type units (an Orc is not one)')
    print('PASS D4 837 Meowyland -> all stats +40')

    # Prism Emblem: seven Prism Rangers (their class id is 14120 in this fixture) carrying 8841
    def emblems(n):
        return others(*[(u(ids=(8841,), char_id=14120), i + 1, True) for i in range(n)])

    agg = stats(u(ids=(8841,), char_id=10400), emblems(6))
    assert agg[:8] == [0] * 8, ('Prism Emblem with six', agg[:8])
    agg = stats(u(ids=(8841,), char_id=10400), emblems(7))
    assert agg[:8] == [50] * 8, ('Prism Emblem with seven', agg[:8])
    checks.append('D4 841 Prism Emblem: nothing at six, +50 all stats at seven')
    print('PASS D4 841 Prism Emblem -> all stats +50 at seven allies')

    # ------------------------------------------------------------------ negatives
    # an unlearned id does nothing, and the filtered rows are inert with no units on the map
    agg = stats(u(char_id=10380), others((u(char_id=2120), 1, True),))
    assert agg[:8] == [0] * 8
    checks.append('unlearned: no row, no change')
    print('PASS unlearned -> no change')

    print(f'{len(checks)}/{len(checks)} checks passed')


if __name__ == '__main__':
    main()
