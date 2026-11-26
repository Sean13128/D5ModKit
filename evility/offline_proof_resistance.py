"""Resistance carrier, executed from the pinned game's actual CALL (offline only).

The carrier is `element_resistance`: it writes the three element-resistance words of the aggregate that
unit_recalc hands unit_stats_evil_percent (slots 8/9/10 -- the same three D5's own Fire Body / Windy Body /
Cool Body, evilities 4008/4009/4010, and Elemental Rise 1161 write; see
/Volumes/Data/Decomp/d5/functions/1401f2a10_unit_stats_evil_percent.c lines 1007/1030/1053 and 614-616).

D4's Anti Elements (230) is the source row: "Element stats increased by 50% when HP is under 25%", and
D4's own getter (FUN_14010de70) applies that gate as hp <= floor(max hp * 25 / 100) -- inclusive at the
truncated threshold, so 250/1000 is inside it.  Condition kind 48 `hp_at_or_below` is that gate.
"""
import argparse, hashlib, struct, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import evility as ev
from abi_engine_ex05c import AGG, execute
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA, unit, fixture


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--abi', action='store_true'); args = ap.parse_args()
    raw = ORIGINAL.read_bytes(); assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    rows = {
        7600: {'family': 'element_resistance', 'effects': [{'stat': 'all', 'value': 30}]},
        7601: {'family': 'element_resistance', 'effects': [{'stat': 9, 'value': -25}]},
        # D4 230 Anti Elements: element stats +50 while HP is at or below 25% of maximum.
        7602: {'family': 'element_resistance', 'effects': [{'stat': 'all', 'value': 50}],
               'condition': {'kind': 'hp_at_or_below', 'id': 25}},
        7603: {'family': ['element_resistance', 'aura'], 'effects': [{'stat': 'all', 'value': -20}],
               'condition': {'kind': 'near_has', 'of': 2, 'radius': 1, 'id': 7603}},
    }
    patched = ev.build_patch(raw, rows); info = ev.section_info(patched)
    specs = [(name, ev.wrapper(name)[1], ev.wrapper(name)[2]) for name in ev.WRAPPER_NAMES.values()]
    cases = [
        ('all three', unit((7600,)), (), [30, 30, 30]),
        ('unlearned', unit(), (), [0, 0, 0]),
        ('negative one', unit((7601,)), (), [0, -25, 0]),
        ('stack', unit((7600, 7601)), (), [30, 5, 30]),
        # --- D4 230's HP gate, in D4's own arithmetic -------------------------------------------
        ('d4 gate inside', unit((7602,), hp=24, max_hp=100), (), [50, 50, 50]),
        ('d4 gate exactly on 25%', unit((7602,), hp=25, max_hp=100), (), [50, 50, 50]),
        ('d4 gate just above 25%', unit((7602,), hp=26, max_hp=100), (), [0, 0, 0]),
        ('d4 gate 250/1000 on the line', unit((7602,), hp=250, max_hp=1000), (), [50, 50, 50]),
        ('d4 gate 251/1000 above', unit((7602,), hp=251, max_hp=1000), (), [0, 0, 0]),
        ('d4 gate truncates max (249/999)', unit((7602,), hp=249, max_hp=999), (), [50, 50, 50]),
        ('d4 gate truncation boundary (250/999)', unit((7602,), hp=250, max_hp=999), (), [0, 0, 0]),
        ('d4 gate at zero hp', unit((7602,), hp=0, max_hp=100), (), [50, 50, 50]),
        ('d4 gate full hp', unit((7602,), hp=100, max_hp=100), (), [0, 0, 0]),
        # --- the aura half, as the row vocabulary stands today -----------------------------------
        ('enemy nearby', unit(), ((unit((7603,), team=1), (5, 6), 2),), [-20, -20, -20]),
        ('enemy too far', unit(), ((unit((7603,), team=1), (5, 7), 2),), [0, 0, 0]),
        ('ally nearby', unit(), ((unit((7603,), team=0), (5, 6), 2),), [0, 0, 0]),
    ]
    for name, subject, others, expect in cases:
        result = execute(patched, info, specs, 'resistance', ev.RESISTANCE_PASS, 0x14021D964,
                         abi=args.abi, fixture=fixture(subject, others=others))
        got = result['aggregate'][8:11]; assert got == expect, (name, got, expect)
        print('PASS', name)

    def native_effect(write):
        write(AGG + 32, struct.pack('<3i', 7, -8, 11))
    result = execute(patched, info, specs, 'resistance', ev.RESISTANCE_PASS, 0x14021D964,
                     abi=args.abi, fixture=fixture(unit((7600,))), original_effect=native_effect)
    assert result['aggregate'][8:11] == [37, 22, 41]
    print('PASS native contributions preserved')
    print(f'{len(cases)+1}/{len(cases)+1} checks passed')


if __name__ == '__main__':
    main()
