"""D4SIG5: the evasion family (Misty Haze 351, Beryl's Servant 1 844) is wired and the two rows use it."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()


def _mods():
    return json.loads(OVERLAY.read_text())["mods"]


def test_evasion_family_and_effect_modes():
    assert ev.FAMILIES["evasion"] == ev.F_EVASION == 1 << 31 and ev.F_EVASION in ev.STACK_FAMILIES
    rows, _c, fx = ev.table({1: {"family": "evasion", "effects": [{"value": 50}, {"value": 20, "mode": "points"}]}})
    assert rows[0][1] == ev.F_EVASION and [f[0] for f in fx] == [0, 0x100]
    for bad in ({"value": 50, "mode": "half"}, {"value": -5}, {"value": 5, "stat": "atk"}, {"value": 5, "per": "no_such_count"}, {"value": 5, "mode": "later"}):
        with pytest.raises(ValueError):
            ev.table({2: {"family": "evasion", "effects": [bad]}})
    with pytest.raises(ValueError):
        ev.table({3: {"family": ["evasion", "stats"], "effects": [{"value": 5}]}})


def test_the_two_rows_are_evasion():
    m = _mods()
    misty = m["D4_Unique_5310"]["behaviors"]["evilities"]["8351"]
    assert misty["family"] == "evasion" and misty["effects"] == [{"value": 50}]
    beryl = m["D4_Unique_350"]["behaviors"]["evilities"]["27844"]
    assert beryl["family"] == "evasion" and beryl["effects"] == [{"value": 50, "mode": "points"}]
    for pack, key in (("D4_Unique_5310", "(351)"), ("D4_Unique_350", "(844)")):
        line = next(a for a in m[pack]["adaptations"] if key in a)
        assert "exact rule" in line and "adapted" not in line.lower(), line   # the tracker reads this word


def test_speedy_move_is_labelled_exact_with_its_caveats():
    m = _mods()["D4_Class_1170"]
    line = next(a for a in m["adaptations"] if "(690)" in a)
    assert "exact rule" in line and "adapted" not in line.lower() and "still missing" not in line, line
    assert "0x17FE" in line and "FUN_1400F3C20" in line and "turn_t3_per_unit_end_turn" in line
    assert m["behaviors"]["evilities"]["27690"]["effects"] == [{"stat": "spd", "value": 5, "per": "movement_cost"}]
