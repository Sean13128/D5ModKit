"""EVILCAP1: ally/enemy class counts, the SP-damage percent family and the Magichange conditions encode as designed."""
import pytest

from d5lib import evility as ev


def test_map_class_by_relation_reads_the_filter_and_expands_class_lists():
    for name, kind in (("map_class_ally", 24), ("map_class_enemy", 25)):
        assert ev.SCALES[name] == kind and ev.FILTER_SCALES[kind] == name
        rows, _c, fx = ev.table({27875: {"family": "stats", "effects": [{"stat": "atk", "value": 5, "per": name}],
                                         "classes": [14550, 14551]}})
        assert [r[7] for r in rows] == [14550, 14551]
        assert fx == [(2 | kind << 16, 5)] * 2
        with pytest.raises(ValueError, match="needs filter"):
            ev.table({27875: {"family": "stats", "effects": [{"stat": "atk", "value": 5, "per": name}]}})
    # the any-team scale keeps its number and encoding
    assert ev.SCALES["map_class"] == 13


def test_magichange_conditions_encode_and_validate():
    rows, conds, _fx = ev.table({
        27851: {"family": "potency", "effects": [{"stat": "all", "value": 50}], "conditions": [{"kind": "magichange_host"}]},
        27878: {"family": "stats", "effects": [{"stat": "all", "value": 100}],
                "conditions": [{"kind": "magichange_turns", "id": 1}]},
        27900: {"family": "stats", "effects": [{"stat": "atk", "value": 1}], "conditions": [{"kind": "magichanged"}]}})
    assert sorted(conds) == [(66, 0, 0, 0), (67, 0, 0, 0), (68, 1, 0, 0)]
    for bad in (0, 256):
        with pytest.raises(ValueError):
            ev.table({27878: {"family": "stats", "effects": [{"stat": "all", "value": 100}],
                              "conditions": [{"kind": "magichange_turns", "id": bad}]}})


def test_sp_damage_percent_is_a_single_number_family_with_its_own_wrapper():
    rows, _c, fx = ev.table({27691: {"family": "sp_damage_percent", "effects": [{"value": 50}]}})
    assert rows[0][1] == ev.F_SPDMG == 1 << 28 and fx == [(0, 50)]
    assert ev.wrapper("sp_damage") == (0xE7001A, ev.DAMAGE_SKILL_DAT, [0x1401ADDF0])
    for bad in ({"family": ["sp_damage_percent", "dealt"], "effects": [{"value": 50}]},
                {"family": "sp_damage_percent", "effects": [{"stat": "sp", "value": 50}]}):
        with pytest.raises(ValueError):
            ev.table({27691: bad})
