"""The resistance family only writes the three elemental accumulator slots."""
import pytest
from d5lib import evility


def test_resistance_compilation_and_aura():
    _, _, effects = evility.table({8000: {'family': 'element_resistance', 'effects': [{'stat': 'all', 'value': 30}]}})
    assert effects == [(8, 30), (9, 30), (10, 30)]
    _, _, effects = evility.table({8001: {'family': ['element_resistance', 'aura'], 'effects': [{'stat': 9, 'value': -20}], 'condition': {'kind': 'near_has', 'of': 2, 'radius': 1, 'id': 8001}}})
    assert effects == [(9, -20)]


def test_rejects_unrelated_slots_and_families():
    with pytest.raises(ValueError):
        evility.table({8000: {'family': 'element_resistance', 'effects': [{'stat': 7, 'value': 20}]}})
    with pytest.raises(ValueError):
        evility.table({8000: {'family': ['element_resistance', 'stats'], 'effects': [{'stat': 8, 'value': 20}]}})


def test_d4_comparison_gate_is_the_inclusive_absolute_kind():
    """D4 230's gate is 'hp at or below 25% of max' in absolute HP, not a strictly-below integer percent.

    D4's getter (FUN_14010de70) scales the maximum and refuses the value when the scaled number is below
    min(hp, max), so 250/1000 is inside the gate while `hp_below` (kind 4, hp*100/max < 25) puts it outside.
    """
    rows, conds, fx = evility.table({8230: {
        'family': 'element_resistance',
        'effects': [{'stat': 'all', 'value': 50}],
        'condition': {'kind': 'hp_at_or_below', 'id': 25}}})
    assert conds == [(48, 25, 0, 0)]
    assert fx == [(8, 50), (9, 50), (10, 50)]
    assert rows[0][1] & evility.F_RESISTANCE
    assert 'hp_at_or_below' in evility.COND_NAME.values() or evility.COND_KINDS['hp_at_or_below'] == 48


def test_d4_gate_needs_its_threshold():
    with pytest.raises(ValueError):
        evility.table({8230: {'family': 'element_resistance',
                              'effects': [{'stat': 'all', 'value': 50}],
                              'condition': {'kind': 'hp_at_or_below'}}})
