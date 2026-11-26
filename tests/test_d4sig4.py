"""D4SIG4: weapon_percent (Nagi, Everyone's Mechanic) is wired; Friends and Unlosing Mode raise the six traced stats."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()
SIX = ["atk", "def", "int", "res", "hit", "spd"]


def _mods():
    return json.loads(OVERLAY.read_text())["mods"]


def test_weapon_percent_family_and_wrapper():
    assert ev.FAMILIES["weapon_percent"] == ev.F_WEAPON == 1 << 30
    assert ev.F_WEAPON in ev.AURA_FAMILIES and ev.F_WEAPON in ev.ADD_FAMILIES
    tag, target, sites = ev.wrapper("equip_weapon")
    assert (tag, target) == (0xE7001C, ev.EQUIP_STAT) and len(sites) == 8 and len(set(sites)) == 8
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)
    near = [{"kind": "near_has", "of": 1, "radius": 65535, "id": 1}]
    rows, _c, _fx = ev.table({7: {"family": ["weapon_percent", "aura"], "effects": [{"value": 10}], "conditions": near}})
    assert rows[0][1] == ev.F_WEAPON | ev.F_AURA
    ev.table({8: {"family": "weapon_percent", "effects": [{"value": 10}]}})


def test_weapon_percent_cannot_share_a_row_with_another_family():
    with pytest.raises(ValueError):
        ev.table({9: {"family": ["weapon_percent", "stats"], "effects": [{"value": 10}]}})


def test_nagi_row_is_the_weapon_percent_aura():
    m = _mods()["D4_Unique_490"]
    assert m["behaviors"]["evilities"]["27892"]["family"] == ["weapon_percent", "aura"]
    assert next(r for r in m["skill_rows"] if r["id"] == 27892)["desc_EN"] == "Increase stats of ally weapons by 10％."


def test_unlosing_mode_and_friends_are_the_six_stats():
    m = _mods()
    roar = m["D4_Unique_460"]["behaviors"]["evilities"]["27881"]
    assert [e["stat"] for e in roar["effects"]] == SIX
    friends = m["D4_Class_1220"]["behaviors"]["evilities"]["8840"]
    assert [e["stat"] for e in friends["effects"]] == SIX
