"""EVILFX2: evaluator-only vocabulary for the Disgaea RPG / D4 evility census, through the real patched CALL
sites (Unicorn), normal and --abi, with the EX-05e harness.  No new call site.

  scales   party_capped (21): living members of the unit's side on the map, the unit included, capped at `filter`
           hp_pct (22) / hp_lost_pct (23): percent scales, the effect adds value * percent / 100
  conds    self_buff / self_debuff (56/57): a stat-change status on the unit (status slots 7..12)
           map_buff_min / map_debuff_min (58/59): counted over the map (evil_near filter kind 10)
           enemy_map_max (60): at most N enemies on the map
           other_weapon (61): the other side's equipped weapon category
  regen as an aura: percent of the PROVIDER's maximum HP (row flag 2) -- see cases regen-aura-*

D5_KIT=<worktree> <unicorn python> evility/offline_proof_evilfx2.py [--abi] [--json OUT]
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
from d5lib.importers import _drpg_text   # noqa: E402  (TEXTHASH-DRPG: JP names are hashes; these proofs read ids, rows and our own wording)
from abi_engine_ex05c import execute                    # noqa: E402
h.ACTION = __import__('abi_engine_ex05c').ACTION

unit, fixture = h.unit, h.fixture
STATREC = 0x141067DC8
NEAR = lambda i, of=1: {'kind': 'near_has', 'of': of, 'radius': 30, 'id': i}     # noqa: E731
ROWS = {
    7800: {'family': 'stats', 'effects': [{'stat': 'def', 'value': 70, 'per': 'hp_lost_pct'},
                                          {'stat': 'res', 'value': 70, 'per': 'hp_lost_pct'}]},
    7801: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 50, 'per': 'hp_pct'}]},
    7802: {'family': 'dealt', 'effects': [{'value': 150, 'per': 'hp_lost_pct'}]},
    7803: {'family': 'stats', 'filter': 5, 'effects': [{'stat': 'atk', 'value': 4, 'per': 'party_capped'}]},
    7804: {'family': 'dealt', 'filter': 5, 'effects': [{'value': 5, 'per': 'party_capped'}]},
    7805: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 60}], 'conditions': [{'kind': 'self_buff', 'id': 7}]},
    7806: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 60}], 'conditions': [{'kind': 'self_debuff', 'id': 3}]},
    7807: {'family': 'stats', 'effects': [{'stat': 'int', 'value': 18}],
           'conditions': [{'kind': 'map_debuff_min', 'count': 1, 'of': 2, 'id': 5}]},
    # "allies under an ATK buff get DEF +20": an aura whose recipient condition is self_buff
    7808: {'family': ['stats', 'aura'], 'effects': [{'stat': 'def', 'value': 20}],
           'conditions': [NEAR(7808), {'kind': 'self_buff', 'id': 2}]},
    7809: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 100}], 'conditions': [{'kind': 'enemy_map_max', 'id': 1}]},
    7810: {'family': 'taken', 'effects': [{'value': -40}], 'conditions': [{'kind': 'other_weapon', 'id': 4}]},
    7811: {'family': 'stats', 'effects': [{'stat': 'res', 'value': 9}],
           'conditions': [{'kind': 'map_buff_min', 'count': 2, 'of': 1, 'id': 2}]},
    7812: {'family': 'crit_rate', 'effects': [{'value': 30, 'per': 'hp_pct'}]},
    # "at turn start the party recovers 8 % of the HOLDER's max HP" (+ the holder's own row), and party SP
    7820: [{'family': 'regen', 'effects': [{'stat': 'hp', 'value': 8}]},
           {'family': ['regen', 'aura'], 'effects': [{'stat': 'hp', 'value': 8, 'base': 'provider'}],
            'conditions': [NEAR(7820)]}],
    7821: {'family': ['regen', 'aura'], 'effects': [{'stat': 'sp', 'value': 10}],
           'conditions': [NEAR(7821), {'kind': 'weapon', 'id': 2}]},
    # "the ally with the highest ATK gets ATK +50" / "the enemy with the highest ATK loses 25" / lowest SPD
    7830: [{'family': 'stats', 'effects': [{'stat': 'atk', 'value': 50}], 'conditions': [{'kind': 'side_top', 'id': 2}]},
           {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 50}],
            'conditions': [{'kind': 'side_top', 'id': 2}, NEAR(7830)]}],
    7831: {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': -25}],
           'conditions': [{'kind': 'side_top', 'id': 2}, NEAR(7831, 2)]},
    7832: {'family': ['stats', 'aura'], 'effects': [{'stat': 'def', 'value': 40}],
           'conditions': [{'kind': 'side_bottom', 'id': 7}, NEAR(7832)]},
    # "while I am under a SPD buff, the party's ATK +45"
    7833: {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 45}],
           'conditions': [NEAR(7833), {'kind': 'provider_buff', 'id': 7}]},
    # a party_min (kind 54) written right after a near_has is NOT read as a provider qualifier
    7834: {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 7}],
           'conditions': [NEAR(7834), {'kind': 'party_min', 'count': 3, 'of': 1}]},
    7822: {'family': ['regen', 'aura'], 'effects': [{'stat': 'hp', 'value': 8, 'base': 'provider'}],
           'conditions': [NEAR(7822), {'kind': 'provider_weapon', 'id': 7}]},
}


def agg(**kw):
    out = [0] * 18
    for k, v in kw.items():
        out[('hp', 'sp', 'atk', 'def', 'int', 'res', 'hit', 'spd').index(k)] = v
    return out


def idx(data, n):
    """give the unit stat-record index n (unit +0x4348)"""
    struct.pack_into('<I', data, 0x4348, n)
    return data


def mod(n, stat, power, active=1):
    """stat record n carries a stat-change status on `stat` (2..7): slot stat + 5, active byte + signed power"""
    base = STATREC + n * 3736
    return [(base + 1257 + 5 + stat, bytes([active])), (base + 0x536 + 5 + stat, struct.pack('<b', power))]


def stats(data, **kw):
    """current stat values: the six qwords ATK..SPD at unit +0x2CE8"""
    for k, v in kw.items():
        struct.pack_into('<q', data, 0x2ce8 + 8 * ('atk', 'def', 'int', 'res', 'hit', 'spd').index(k), v)
    return data


def slot1(data, category):
    struct.pack_into('<i', data, 912, 1)
    struct.pack_into('<B', data, 942, category)
    return data


def cases():
    def run(name, family, field, expected, **kw):
        return dict(name=name, family=family, field=field, expected=expected, **kw)
    ally = lambda: unit(())                      # noqa: E731
    foe = lambda: unit((), team=1)               # noqa: E731
    blank = [(STATREC, bytes(8 * 3736))]
    return [
        # ---- percent scales
        run('hp-lost-30-of-100-gives-70pct-of-70', 'stats', 'aggregate', agg(**{'def': 49, 'res': 49}), ids=(7800,),
            fixture=fixture(unit((7800,), hp=30, max_hp=100))),
        run('hp-lost-full-hp-gives-nothing', 'stats', 'aggregate', agg(), ids=(7800,),
            fixture=fixture(unit((7800,), hp=100, max_hp=100))),
        run('hp-lost-at-zero-gives-the-maximum', 'stats', 'aggregate', agg(**{'def': 70, 'res': 70}), ids=(7800,),
            fixture=fixture(unit((7800,), hp=0, max_hp=100))),
        run('hp-lost-truncates-333-of-1000', 'stats', 'aggregate', agg(**{'def': 46, 'res': 46}), ids=(7800,),
            fixture=fixture(unit((7800,), hp=333, max_hp=1000))),     # 33 % left, 67 lost, 70*67/100 = 46
        run('hp-lost-no-maximum-gives-nothing', 'stats', 'aggregate', agg(), ids=(7800,),
            fixture=fixture(unit((7800,)))),
        run('hp-lost-unlearned', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), hp=30, max_hp=100))),
        run('hp-pct-half-gives-half', 'stats', 'aggregate', agg(atk=25), ids=(7801,),
            fixture=fixture(unit((7801,), hp=50, max_hp=100))),
        run('hp-pct-full-gives-the-maximum', 'stats', 'aggregate', agg(atk=50), ids=(7801,),
            fixture=fixture(unit((7801,), hp=100, max_hp=100))),
        run('hp-pct-above-max-is-clamped', 'stats', 'aggregate', agg(atk=50), ids=(7801,),
            fixture=fixture(unit((7801,), hp=150, max_hp=100))),
        run('hp-lost-on-damage-dealt', 'dealt', 'output', 75, ids=(7802,),
            fixture=fixture(unit((7802,), hp=50, max_hp=100), other=unit())),
        run('hp-lost-on-damage-dealt-full-hp', 'dealt', 'output', 0, ids=(7802,),
            fixture=fixture(unit((7802,), hp=100, max_hp=100), other=unit())),
        run('hp-pct-on-crit-rate', 'crit_rate', 'output', 50 + 15, ids=(7812,),
            fixture=fixture(unit((7812,), hp=50, max_hp=100), other=unit())),
        # ---- party_capped
        run('party-capped-alone-counts-the-holder', 'stats', 'aggregate', agg(atk=4), ids=(7803,),
            fixture=fixture(unit((7803,)))),
        run('party-capped-two-allies', 'stats', 'aggregate', agg(atk=12), ids=(7803,),
            fixture=fixture(unit((7803,)), others=((ally(), (5, 9), 2), (ally(), (20, 20), 3)))),
        run('party-capped-enemies-are-not-counted', 'stats', 'aggregate', agg(atk=8), ids=(7803,),
            fixture=fixture(unit((7803,)), others=((ally(), (5, 9), 2), (foe(), (6, 6), 3), (foe(), (7, 7), 4)))),
        run('party-capped-stops-at-the-cap', 'dealt', 'output', 25, ids=(7804,),
            fixture=fixture(unit((7804,)), other=ally(),
                            others=((ally(), (5, 9), 2), (ally(), (6, 9), 3), (ally(), (7, 9), 4), (ally(), (8, 9), 5)))),
        run('party-capped-off-the-map', 'stats', 'aggregate', agg(), ids=(7803,),
            fixture=fixture(unit((7803,)), on_map=False, others=((ally(), (5, 9), 2),))),
        # ---- self_buff / self_debuff (stat record 1 is the subject's)
        run('self-buff-spd-active', 'stats', 'aggregate', agg(atk=60), ids=(7805,),
            fixture=fixture(idx(unit((7805,)), 1), regions=blank + mod(1, 7, 20))),
        run('self-buff-spd-is-a-debuff', 'stats', 'aggregate', agg(), ids=(7805,),
            fixture=fixture(idx(unit((7805,)), 1), regions=blank + mod(1, 7, -20))),
        run('self-buff-spd-expired', 'stats', 'aggregate', agg(), ids=(7805,),
            fixture=fixture(idx(unit((7805,)), 1), regions=blank + mod(1, 7, 20, active=0))),
        run('self-buff-another-stat', 'stats', 'aggregate', agg(), ids=(7805,),
            fixture=fixture(idx(unit((7805,)), 1), regions=blank + mod(1, 6, 20))),
        run('self-buff-on-another-units-record', 'stats', 'aggregate', agg(), ids=(7805,),
            fixture=fixture(idx(unit((7805,)), 1), regions=blank + mod(2, 7, 20))),
        run('self-debuff-def-active', 'stats', 'aggregate', agg(atk=60), ids=(7806,),
            fixture=fixture(idx(unit((7806,)), 1), regions=blank + mod(1, 3, -15))),
        run('self-debuff-def-is-a-buff', 'stats', 'aggregate', agg(), ids=(7806,),
            fixture=fixture(idx(unit((7806,)), 1), regions=blank + mod(1, 3, 15))),
        run('self-buff-no-stat-record', 'stats', 'aggregate', agg(), ids=(7805,),
            fixture=fixture(idx(unit((7805,)), 0x28a), regions=blank)),
        # ---- map_debuff_min / map_buff_min
        run('map-debuff-an-enemy-has-the-res-debuff', 'stats', 'aggregate', agg(int=18), ids=(7807,),
            fixture=fixture(idx(unit((7807,)), 1), regions=blank + mod(2, 5, -10),
                            others=((idx(foe(), 2), (9, 9), 2),))),
        run('map-debuff-the-enemy-has-a-res-buff', 'stats', 'aggregate', agg(), ids=(7807,),
            fixture=fixture(idx(unit((7807,)), 1), regions=blank + mod(2, 5, 10),
                            others=((idx(foe(), 2), (9, 9), 2),))),
        run('map-debuff-an-ally-has-it-not-an-enemy', 'stats', 'aggregate', agg(), ids=(7807,),
            fixture=fixture(idx(unit((7807,)), 1), regions=blank + mod(2, 5, -10),
                            others=((idx(ally(), 2), (9, 9), 2), (idx(foe(), 3), (9, 10), 3)))),
        run('map-debuff-another-stat', 'stats', 'aggregate', agg(), ids=(7807,),
            fixture=fixture(idx(unit((7807,)), 1), regions=blank + mod(2, 3, -10),
                            others=((idx(foe(), 2), (9, 9), 2),))),
        run('map-buff-two-allies-needed-two-have-it', 'stats', 'aggregate', agg(res=9), ids=(7811,),
            fixture=fixture(idx(unit((7811,)), 1), regions=blank + mod(2, 2, 5) + mod(3, 2, 5),
                            others=((idx(ally(), 2), (9, 9), 2), (idx(ally(), 3), (9, 10), 3)))),
        run('map-buff-two-allies-needed-one-has-it', 'stats', 'aggregate', agg(), ids=(7811,),
            fixture=fixture(idx(unit((7811,)), 1), regions=blank + mod(2, 2, 5),
                            others=((idx(ally(), 2), (9, 9), 2), (idx(ally(), 3), (9, 10), 3)))),
        # ---- buffed-ally aura
        run('buffed-ally-aura-recipient-has-the-atk-buff', 'stats', 'aggregate', agg(**{'def': 20}), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(1, 2, 10),
                            others=((idx(unit((7808,)), 2), (5, 9), 2),))),
        run('buffed-ally-aura-recipient-has-no-buff', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank,
                            others=((idx(unit((7808,)), 2), (5, 9), 2),))),
        run('buffed-ally-aura-only-the-provider-is-buffed', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(2, 2, 10),
                            others=((idx(unit((7808,)), 2), (5, 9), 2),))),
        # ---- enemy_map_max
        run('enemy-max-one-enemy', 'stats', 'aggregate', agg(atk=100), ids=(7809,),
            fixture=fixture(unit((7809,)), others=((foe(), (9, 9), 2), (ally(), (9, 10), 3)))),
        run('enemy-max-two-enemies', 'stats', 'aggregate', agg(), ids=(7809,),
            fixture=fixture(unit((7809,)), others=((foe(), (9, 9), 2), (foe(), (9, 10), 3)))),
        run('enemy-max-no-enemy', 'stats', 'aggregate', agg(atk=100), ids=(7809,),
            fixture=fixture(unit((7809,)), others=((ally(), (9, 10), 3),))),
        run('enemy-max-off-the-map', 'stats', 'aggregate', agg(), ids=(7809,),
            fixture=fixture(unit((7809,)), on_map=False)),
        # ---- other_weapon (taken: 50 in)
        run('other-weapon-attacker-has-a-bow', 'taken', 'output', 30, ids=(7810,),
            fixture=fixture(unit((7810,)), subject_is_other=True, other=unit(weapon_category=4))),
        run('other-weapon-attacker-has-a-sword', 'taken', 'output', 50, ids=(7810,),
            fixture=fixture(unit((7810,)), subject_is_other=True, other=unit(weapon_category=2))),
        run('other-weapon-attacker-unarmed', 'taken', 'output', 50, ids=(7810,),
            fixture=fixture(unit((7810,)), subject_is_other=True, other=unit())),
        run('other-weapon-bow-in-the-second-slot', 'taken', 'output', 30, ids=(7810,),
            fixture=fixture(unit((7810,)), subject_is_other=True, other=slot1(unit(), 4))),
        run('other-weapon-the-holder-has-the-bow-not-the-attacker', 'taken', 'output', 50, ids=(7810,),
            fixture=fixture(unit((7810,), weapon_category=4), subject_is_other=True, other=unit())),
    ] + EXTRA_CASES(run)


def EXTRA_CASES(run):
    hurt = dict(hp=100, max_hp=1000, sp=40, max_sp=200)
    big = lambda ids, **kw: unit(ids, hp=5000, max_hp=5000, **kw)        # noqa: E731
    R = lambda name, field, expected, **kw: dict(name=name, family='regen', field=field, expected=expected, **kw)  # noqa: E731
    S = lambda ids=(), team=0, **st: stats(unit(ids, team=team), **st)       # noqa: E731
    run = lambda name, expected, **kw: dict(name=name, family='stats', field='aggregate', expected=expected, **kw)  # noqa: E731
    blank = [(STATREC, bytes(8 * 3736))]
    rank = [
        run('side-top-recipient-has-the-highest-atk', agg(atk=50), ids=(),
            fixture=fixture(S(atk=900), others=((S((7830,), atk=500), (5, 9), 2), (S(atk=899), (6, 9), 3)))),
        run('side-top-another-ally-is-higher', agg(), ids=(),
            fixture=fixture(S(atk=900), others=((S((7830,), atk=500), (5, 9), 2), (S(atk=901), (6, 9), 3)))),
        run('side-top-a-tie-qualifies', agg(atk=50), ids=(),
            fixture=fixture(S(atk=900), others=((S((7830,), atk=900), (5, 9), 2),))),
        run('side-top-an-enemy-higher-does-not-matter', agg(atk=50), ids=(),
            fixture=fixture(S(atk=900), others=((S((7830,), atk=500), (5, 9), 2), (S(team=1, atk=5000), (6, 9), 3)))),
        run('side-top-the-holder-itself-is-the-highest', agg(atk=50), ids=(7830,),
            fixture=fixture(S((7830,), atk=900), others=((S(atk=100), (5, 9), 2),))),
        run('side-top-the-holder-is-not-the-highest', agg(), ids=(7830,),
            fixture=fixture(S((7830,), atk=900), others=((S(atk=1000), (5, 9), 2),))),
        run('side-top-compares-atk-not-int', agg(atk=50), ids=(),
            fixture=fixture(S(atk=900, int=1), others=((S((7830,), atk=500, int=9999), (5, 9), 2),))),
        run('side-top-enemy-aura-on-the-highest-atk-enemy', agg(atk=-25), ids=(),
            fixture=fixture(S(team=1, atk=900), others=((S((7831,), atk=5000), (5, 9), 2), (S(team=1, atk=100), (6, 9), 3)))),
        run('side-top-enemy-aura-not-on-a-lower-enemy', agg(), ids=(),
            fixture=fixture(S(team=1, atk=100), others=((S((7831,), atk=5000), (5, 9), 2), (S(team=1, atk=900), (6, 9), 3)))),
        run('side-bottom-recipient-has-the-lowest-spd', agg(**{'def': 40}), ids=(),
            fixture=fixture(S(spd=10), others=((S((7832,), spd=50), (5, 9), 2), (S(spd=11), (6, 9), 3)))),
        run('side-bottom-another-ally-is-lower', agg(), ids=(),
            fixture=fixture(S(spd=10), others=((S((7832,), spd=50), (5, 9), 2), (S(spd=9), (6, 9), 3)))),
        run('side-top-off-the-map', agg(), ids=(7830,),
            fixture=fixture(S((7830,), atk=900), on_map=False)),
        run('provider-buff-holder-has-the-spd-buff', agg(atk=45), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(2, 7, 20),
                            others=((idx(unit((7833,)), 2), (5, 9), 2),))),
        run('provider-buff-holder-has-a-spd-debuff', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(2, 7, -20),
                            others=((idx(unit((7833,)), 2), (5, 9), 2),))),
        run('provider-buff-only-the-recipient-is-buffed', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(1, 7, 20),
                            others=((idx(unit((7833,)), 2), (5, 9), 2),))),
        run('provider-buff-holder-buff-expired', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(2, 7, 20, active=0),
                            others=((idx(unit((7833,)), 2), (5, 9), 2),))),
        run('party-min-after-near-has-is-not-a-qualifier-holds', agg(atk=7), ids=(),
            fixture=fixture(unit(()), others=((unit((7834,)), (5, 9), 2), (unit(()), (6, 9), 3)))),
        run('party-min-after-near-has-is-not-a-qualifier-fails', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((7834,)), (5, 9), 2), (unit((), type_code=11), (6, 9), 3)))),
    ]
    return rank + [
        R('regen-aura-8pct-of-the-providers-max-hp', 'hp', 500, ids=(), expect_call=h.SHADOW,
          fixture=fixture(unit((), **hurt), others=((big((7820,)), (5, 9), 2),))),
        R('regen-aura-provider-out-of-radius', 'hp', 100, ids=(), absent_call=h.SHADOW,
          fixture=fixture(unit((), **hurt), others=((big((7820,)), (5, 36), 2),))),
        R('regen-aura-provider-is-an-enemy', 'hp', 100, ids=(), absent_call=h.SHADOW,
          fixture=fixture(unit((), **hurt), others=((big((7820,), team=1), (5, 9), 2),))),
        R('regen-aura-clamps-at-the-recipients-max', 'hp', 1000, ids=(), expect_call=h.SHADOW,
          fixture=fixture(unit((), hp=900, max_hp=1000), others=((big((7820,)), (5, 9), 2),))),
        R('regen-aura-does-not-heal-a-unit-at-zero', 'hp', 0, ids=(), absent_call=h.SHADOW,
          fixture=fixture(unit((), hp=0, max_hp=1000), others=((big((7820,)), (5, 9), 2),))),
        R('regen-aura-the-holder-heals-by-its-own-row-once', 'hp', 2400, ids=(7820,), expect_call=h.SHADOW,
          fixture=fixture(unit((7820,), hp=2000, max_hp=5000))),
        R('regen-aura-another-ally-is-not-the-base', 'hp', 500, ids=(), expect_call=h.SHADOW,
          fixture=fixture(unit((), **hurt), others=((big((7820,)), (5, 9), 2), (unit((), hp=9, max_hp=90000), (5, 8), 3)))),
        R('regen-aura-sp-is-a-percent-of-the-recipients-max-sp', 'sp', 60, ids=(), absent_call=h.SHADOW,
          fixture=fixture(unit((), weapon_category=2, **hurt), others=((unit((7821,)), (5, 9), 2),))),
        R('regen-aura-sp-recipient-condition-fails', 'sp', 40, ids=(), absent_call=h.SHADOW,
          fixture=fixture(unit((), weapon_category=1, **hurt), others=((unit((7821,)), (5, 9), 2),))),
        R('regen-aura-holder-condition-holds', 'hp', 500, ids=(), expect_call=h.SHADOW,
          fixture=fixture(unit((), **hurt), others=((big((7822,), weapon_category=7), (5, 9), 2),))),
        R('regen-aura-holder-condition-fails', 'hp', 100, ids=(), absent_call=h.SHADOW,
          fixture=fixture(unit((), **hurt), others=((big((7822,), weapon_category=2), (5, 9), 2),))),
    ]


def overlay_rows():
    """rows verbatim from the importers' overlays: the six Disgaea RPG evilities EVILFX2 builds, one gated row of
    each other new piece, and the two D4 aura rows (Kojiro's 8697, Kyoko's fixed 8845)"""
    imp = KIT / 'd5lib/importers'
    drpg = _drpg_text.load_authored(imp / 'drpg-evility-overlay.json')
    by = {e['id']: e for b in drpg['bases'].values() for e in b['evilities']}
    want = (28002, 28031, 28099, 28299, 28438, 28559, 28020, 28108, 28133, 28145, 28038, 28166, 28384,
            28471, 28123, 28075, 28065, 28304, 28092, 28021, 28093, 28095, 28305)
    rows = {i: by[i]['rows'] for i in want}
    d4 = json.loads((imp / 'd4-evility-overlay.json').read_text())['mods']
    rows[8697] = d4['D4_Class_1140']['behaviors']['evilities']['8697']
    rows[8845] = d4['D4_Unique_350']['behaviors']['evilities']['8845']
    return rows


def overlay_cases():
    def run(name, family, field, expected, **kw):
        return dict(name='overlay-' + name, family=family, field=field, expected=expected, **kw)
    ally = lambda: unit(())                      # noqa: E731
    foe = lambda: unit((), team=1)               # noqa: E731
    blank = [(STATREC, bytes(8 * 3736))]
    T = dict(supplied_stack_args=(h.ACTION, 1, 0))
    crit = [(h.ACTION + 0x152A + 0x260, b'\x01')]
    half = dict(hp=50, max_hp=100)
    return [
        run('28002-barbara-def-res-by-hp-lost', 'stats', 'aggregate', agg(**{'def': 35, 'res': 35}), ids=(28002,),
            fixture=fixture(unit((28002,), **half))),
        run('28002-barbara-full-hp', 'stats', 'aggregate', agg(), ids=(28002,),
            fixture=fixture(unit((28002,), hp=100, max_hp=100))),
        run('28031-ayame-atk-def-by-hp-lost', 'stats', 'aggregate', agg(atk=75, **{'def': 75}), ids=(28031,),
            fixture=fixture(unit((28031,), **half))),
        run('28099-ivar-atk-def-by-hp', 'stats', 'aggregate', agg(atk=25, **{'def': 25}), ids=(28099,),
            fixture=fixture(unit((28099,), **half))),
        run('28099-ivar-crit-damage-by-hp', 'taken', 'output', 62, ids=(28099,), **T,     # 50 * (100 + 25) / 100
            fixture=fixture(unit((28099,), **half), other=unit(), regions=crit)),
        run('28299-liz-def-100-atk-50-by-hp', 'stats', 'aggregate', agg(atk=25, **{'def': 50}), ids=(28299,),
            fixture=fixture(unit((28299,), **half))),
        run('28559-pudding-atk-by-hp', 'stats', 'aggregate', agg(atk=80), ids=(28559,),
            fixture=fixture(unit((28559,), hp=100, max_hp=100))),
        run('28559-pudding-crit-rate-by-hp', 'crit_rate', 'output', 50 + 15, ids=(28559,),
            fixture=fixture(unit((28559,), **half), other=unit())),
        run('28438-pringer-v3-from-a-bow', 'taken', 'output', 30, ids=(28438,),
            fixture=fixture(unit((28438,)), subject_is_other=True, other=unit(weapon_category=4))),
        run('28438-pringer-v3-from-a-gun', 'taken', 'output', 50, ids=(28438,),
            fixture=fixture(unit((28438,)), subject_is_other=True, other=unit(weapon_category=5))),
        # gated (D1 / D2) rows, one of each new piece
        dict(name='overlay-28020-noel-party-heal-8pct-of-noels-max', family='regen', field='hp', expected=500, ids=(),
             expect_call=h.SHADOW, fixture=fixture(unit((), hp=100, max_hp=1000),
                                                   others=((unit((28020,), hp=5000, max_hp=5000), (5, 25), 2),))),
        dict(name='overlay-28020-noel-heals-herself', family='regen', field='hp', expected=2400, ids=(28020,),
             expect_call=h.SHADOW, fixture=fixture(unit((28020,), hp=2000, max_hp=5000))),
        # AURA2: Citri 28304 (four rows: self + aura for stats, self + aura for HP) and Melodia 28092 (self + aura)
        run('28304-citri-alone-self-rows-only', 'stats', 'aggregate', agg(hp=25, atk=16, **{'def': 16}, int=16, res=16), ids=(28304,),
            fixture=fixture(unit((28304,)))),
        run('28304-citri-aura-reaches-an-ally', 'stats', 'aggregate', agg(hp=25, atk=16, **{'def': 16}, int=16, res=16), ids=(),
            fixture=fixture(unit(()), others=((unit((28304,)), (5, 25), 2),))),
        run('28304-citri-aura-not-an-enemy', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), team=1), others=((unit((28304,)), (5, 25), 2),))),
        run('28304-citri-aura-out-of-radius', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((28304,)), (5, 60), 2),))),
        run('28092-melodia-alone-self-row-only', 'stats', 'aggregate', agg(spd=7), ids=(28092,),
            fixture=fixture(unit((28092,)))),
        run('28092-melodia-aura-reaches-an-ally', 'stats', 'aggregate', agg(spd=7), ids=(),
            fixture=fixture(unit(()), others=((unit((28092,)), (5, 25), 2),))),
        run('28092-melodia-aura-not-an-enemy', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), team=1), others=((unit((28092,)), (5, 25), 2),))),
        # Two holders of each main: self plus ONE incoming aura for each id.
        # This synthetic multi-main holder is distinct from the real three-unit fixture below.
        run('two-28304-and-two-28092-holders-self-plus-incoming-aura',
            'stats', 'aggregate', agg(hp=50, atk=32, **{'def': 32}, int=32, res=32, spd=14), ids=(28304, 28092),
            fixture=fixture(unit((28304, 28092)), others=((unit((28092,)), (5, 25), 2), (unit((28304,)), (6, 25), 3)))),
        run('28304-recipient-holds-28092-and-gets-the-28304-aura', 'stats', 'aggregate',
            agg(hp=25, atk=16, **{'def': 16}, int=16, res=16, spd=7), ids=(28092,),
            fixture=fixture(unit((28092,)), others=((unit((28304,)), (5, 25), 2),))),
        dict(name='overlay-28020-noel-heals-herself-at-33-max-hp', family='regen', field='hp', expected=12, ids=(28020,),
             expect_call=h.SHADOW, fixture=fixture(unit((28020,), hp=10, max_hp=33))),
        dict(name='overlay-28020-noel-party-heal-at-33-provider-max-hp', family='regen', field='hp', expected=12, ids=(),
             expect_call=h.SHADOW, fixture=fixture(unit((), hp=10, max_hp=100),
                                                   others=((unit((28020,), hp=33, max_hp=33), (5, 25), 2),))),
        run('28108-piyori-three-living-members', 'stats', 'aggregate', agg(atk=12, **{'def': 12}), ids=(),
            fixture=fixture(unit(()), others=((unit((28108,)), (5, 25), 2), (ally(), (9, 9), 3)))),
        run('28133-amane-buffed-ally', 'stats', 'aggregate', agg(res=20, **{'def': 20}), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(1, 2, 10),
                            others=((idx(unit((28133,)), 2), (5, 25), 2),))),
        run('28133-amane-unbuffed-ally', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank, others=((idx(unit((28133,)), 2), (5, 25), 2),))),
        run('28145-keke-an-enemy-has-the-res-debuff', 'stats', 'aggregate', agg(int=18, res=18), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(3, 5, -10),
                            others=((idx(unit((28145,)), 2), (5, 25), 2), (idx(foe(), 3), (9, 9), 3)))),
        run('28145-keke-no-debuffed-enemy', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank,
                            others=((idx(unit((28145,)), 2), (5, 25), 2), (idx(foe(), 3), (9, 9), 3)))),
        run('28038-torachiyo-one-enemy', 'stats', 'aggregate', agg(atk=70, int=70, res=70, **{'def': 70}), ids=(28038,),
            fixture=fixture(unit((28038,)), others=((foe(), (9, 9), 2),))),
        run('28038-torachiyo-two-enemies', 'stats', 'aggregate', agg(), ids=(28038,),
            fixture=fixture(unit((28038,)), others=((foe(), (9, 9), 2), (foe(), (9, 10), 3)))),
        run('28166-black-rabbit-usa-atk-buff', 'stats', 'aggregate', agg(atk=50, **{'def': 50}), ids=(28166,),
            fixture=fixture(idx(unit((28166,)), 1), regions=blank + mod(1, 2, 20))),
        run('28384-red-queen-own-damage-taken-by-party-size', 'taken', 'output', 45, ids=(28384,),   # 2 members: -10 %
            fixture=fixture(unit((28384,)), subject_is_other=True, other=foe(), others=((ally(), (9, 9), 2),))),
        # Sakuya: Amnesia (status 3) only.  The row is the target's; the rolled status index is the first stack argument
        run('28471-sakuya-amnesia-is-nullified', 'status_chance', 'output', 0, ids=(), supplied_stack_args=(3, 0, 0),
            fixture=fixture(unit(()), other=unit((28471,)))),
        run('28471-sakuya-poison-is-not', 'status_chance', 'output', 50, ids=(), supplied_stack_args=(0, 0, 0),
            fixture=fixture(unit(()), other=unit((28471,)))),
        run('28123-rozalin-highest-atk-ally', 'stats', 'aggregate', agg(atk=50), ids=(),
            fixture=fixture(stats(unit(()), atk=900), others=((stats(unit((28123,)), atk=10), (5, 25), 2),))),
        run('28123-rozalin-not-the-highest', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(stats(unit(()), atk=5), others=((stats(unit((28123,)), atk=10), (5, 25), 2),))),
        run('28075-mao-xeno-fastest-enemy-loses-spd', 'stats', 'aggregate', agg(spd=-12), ids=(),
            fixture=fixture(stats(unit((), team=1), spd=90), others=((unit((28075,)), (5, 25), 2),
                                                                      (stats(unit((), team=1), spd=50), (9, 9), 3)))),
        run('28075-mao-xeno-slower-enemy-keeps-spd', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(stats(unit((), team=1), spd=50), others=((unit((28075,)), (5, 25), 2),
                                                                      (stats(unit((), team=1), spd=90), (9, 9), 3)))),
        run('28065-chacha-party-atk-while-she-has-the-spd-buff', 'stats', 'aggregate', agg(atk=45), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank + mod(2, 7, 20),
                            others=((idx(unit((28065,)), 2), (5, 25), 2),))),
        run('28065-chacha-no-buff', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(idx(unit(()), 1), regions=blank, others=((idx(unit((28065,)), 2), (5, 25), 2),))),
        # D4 (27844 Beryl's Servant 1 is an evasion row since D4SIG5: evility/offline_proof_d4sig5.py)
        run('8697-kojiro-adjacent-ally-def-res', 'stats', 'aggregate', agg(res=20, **{'def': 20}), ids=(),
            fixture=fixture(unit(()), others=((unit((8697,)), (5, 6), 2),))),
        run('8697-kojiro-two-panels-away', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit(()), others=((unit((8697,)), (5, 7), 2),))),
        run('8697-kojiro-himself-is-not-raised', 'stats', 'aggregate', agg(), ids=(8697,),
            fixture=fixture(unit((8697,)))),
        run('8697-kojiro-an-adjacent-enemy-is-not-raised', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), team=1), others=((unit((8697,)), (5, 6), 2),))),
        run('8845-kyoko-next-to-raspberyl', 'stats', 'aggregate', agg(atk=10), ids=(),
            fixture=fixture(unit((), char_id=650), others=((unit((8845,)), (5, 6), 2),))),
        run('8845-kyoko-next-to-someone-else', 'stats', 'aggregate', agg(), ids=(),
            fixture=fixture(unit((), char_id=10), others=((unit((8845,)), (5, 6), 2),))),
    ] + three_unit_cases()


def three_unit_cases():
    """AURA1's actual lists; no weapons, so Noel's staff-only sub does not apply.

    Run each recipient through every stats CALL site with all three units present.
    A second table disables ONLY Citri's aura rows, preserving her list and self rows.
    The paired aggregates isolate Citri's +25 HP/+16 ATK/DEF/INT/RES contribution.
    Vanilla 713x rows are in the lists; the original-game callee is stubbed by this
    evaluator proof, so these cases assert the Kit overlay contribution only.
    """
    lists = {'melodia': (7132, 28092, 28093, 28095),
             'noel': (7130, 7131, 28020, 28021),
             'citri': (7133, 28304, 28305)}
    aura_off = overlay_rows()
    aura_off[28304] = [r for r in aura_off[28304] if 'aura' not in r['family']]
    out = []
    for name, ids in lists.items():
        others = tuple((unit(other_ids), (5 + i, 6), i + 2)
                       for i, (other_name, other_ids) in enumerate(lists.items()) if other_name != name)
        # Noncontiguous battle slots are intentional when one subject is omitted.
        for off in (False, True):
            expected = (agg(spd=7) if off and name != 'citri' else
                        agg(hp=25, atk=16, **{'def': 16}, int=16, res=16, spd=7))
            case = dict(name=f'overlay-aura1-three-unit-{name}-citri-aura-{"off" if off else "on"}',
                        family='stats', field='aggregate', expected=expected, ids=ids,
                        fixture=fixture(unit(ids), others=others))
            if off:
                case['rows'] = aura_off
            out.append(case)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    from d5lib import evility as ev
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    specs = [(ev.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in ev.WRAPPERS]   # by tag, never by position
    results = []
    ov = overlay_rows()
    plan = [(ROWS, c) for c in cases()] + [(c.get('rows', ov), c) for c in overlay_cases()]
    built = {}
    for rows, case in plan:
        if id(rows) not in built:
            patched = ev.build_patch(original, rows)
            built[id(rows)] = (patched, ev.section_info(patched))
        patched, info = built[id(rows)]
        _, target, sites = next(s for s in specs if s[0] == case['family'])
        for site in sites:
            try:
                d = execute(patched, info, specs, case['family'], target, site, ids=case.get('ids', ()), abi=a.abi,
                            fixture=case['fixture'], out_value=50, original_rax=0,
                            supplied_stack_args=case.get('supplied_stack_args'), stub_returns=case.get('stub_returns'))
                got = d[case.get('field', 'output')]
                if isinstance(got, list):
                    got = [x - (1 << 16) if (1 << 15) <= x < (1 << 16) else x for x in got]
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
        a.json.write_text(json.dumps(dict(mode='abi' if a.abi else 'behavior', passed=ok,
                                          patched_sha256=hashlib.sha256(patched).hexdigest(), checks=results), indent=1) + '\n')
    print(f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
