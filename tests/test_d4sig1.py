"""D4SIG1: the five D4 signature innates added from existing runtime pieces are linked, owned once, labelled and compile."""
import json
from pathlib import Path

from d5lib import evility

DIR = Path(__file__).resolve().parents[1] / "d5lib/importers"
from d4rules import mods as _rule_mods
OVER = _rule_mods()


def _links(pack):
    return {k: v["evility1"] for k, v in OVER[pack]["char_links"].items()}


def test_mind_killer_class_alias_on_six_ranks_and_hugo_references_it():
    st = OVER["D4_Class_2120"]
    row = next(r for r in st["skill_rows"] if r["id"] == 27691)
    assert st["class_alias"]["27691"] == 3011                   # D5 Habitual Licker, read natively
    # EVILCAP1: the alias stays (it reaches Habitual Licker's code) and the kit row hands that code 50
    assert row["value1"] == 50 and row["kind"] == 1 and "50" in row["desc_EN"] and "%d" not in row["desc_EN"]
    assert st["behaviors"]["evilities"]["27691"] == {"family": "sp_damage_percent", "effects": [{"value": 50}]}
    assert sorted(_links("D4_Class_2120").values()) == [27691] * 6 and len(_links("D4_Class_2120")) == 6
    hugo = OVER["D4_Unique_170"]
    assert hugo["refs"] == {"27691": "D4_Class_2120"} and hugo["requires"] == ["D4_Class_2120"]
    link = hugo["char_links"]["10270"]
    assert (link["evility1"], link["evility2"], link["evility_count"]) == (27691, 8873, 2)   # Death Magic kept
    assert 27691 not in [r["id"] for r in hugo["skill_rows"]]    # one row, one owner


def test_jet_black_sword_is_a_magichange_host_potency_row_in_the_late_band():
    # EVILCAP1: the Demon Researcher alias (+15 weapon stats) is replaced by potency +50 while wielding a Magichange weapon
    st = OVER["D4_Unique_340"]
    assert [r["id"] for r in st["skill_rows"]] == [27851] and "27851" not in (st.get("aliases") or {})
    assert st["skill_rows"][0]["value1"] == 50 and st["char_links"]["10410"]["evility1"] == 27851
    b = st["behaviors"]["evilities"]["27851"]
    assert b == {"family": "potency", "effects": [{"stat": "all", "value": 50}], "conditions": [{"kind": "magichange_host"}]}
    assert evility.table({27851: b})
    assert "fusion" in st["adaptations"][0] and "1185" in st["adaptations"][0]


def test_everyones_mechanic_is_a_weapon_percent_aura_labelled_exact():
    """D4SIG4: weapon-slot only (wrap_equip), no longer the potency words that also raised armour."""
    b = OVER["D4_Unique_490"]["behaviors"]["evilities"]["27892"]
    assert b["family"] == ["weapon_percent", "aura"] and b["effects"] == [{"value": 10}]
    assert b["conditions"] == [{"kind": "near_has", "of": 1, "radius": 65535, "id": 27892}]
    assert evility.table({27892: b})
    assert OVER["D4_Unique_490"]["char_links"]["10240"]["evility1"] == 27892
    lines = [a for a in OVER["D4_Unique_490"]["adaptations"] if "(892)" in a]
    assert len(lines) == 1 and lines[0].startswith("evility Everyone's Mechanic (892): exact text and number")


def test_unlosing_mode_is_stats_50_for_three_rounds_labelled_automatic():
    b = OVER["D4_Unique_460"]["behaviors"]["evilities"]["27881"]
    assert b["family"] == "stats" and b["effects"] == [
        {"stat": s, "value": 50} for s in ("atk", "def", "int", "res", "hit", "spd")]   # D4SIG4: six stats, not HP/SP
    assert b["conditions"] == [{"kind": "turn_max", "id": 3}] and evility.table({27881: b})
    assert OVER["D4_Unique_460"]["char_links"]["18170"]["evility1"] == 27881
    assert any("automatic" in a and "not on demand" in a for a in OVER["D4_Unique_460"]["adaptations"])


def test_new_ids_are_holdable_and_unique():
    ids = [27691, 27851, 27892, 27881]
    assert all(0 < i < 32768 and i != 9999 for i in ids)
    owners = [r["id"] for st in OVER.values() for r in st.get("skill_rows", [])]
    assert all(owners.count(i) == 1 for i in ids)


def test_eccarlate_is_ash_innate_on_the_last_magichange_turn():
    st = OVER["D4_Unique_450"]
    assert [r["id"] for r in st["skill_rows"]] == [8880, 27878] and st["aliases"] == {"8880": 6113}
    assert st["char_links"]["18160"]["evility1"] == 27878 and st["char_links"]["18160"]["evility_count"] == 1
    b = st["behaviors"]["evilities"]["27878"]
    assert b["conditions"] == [{"kind": "magichange_turns", "id": 1}] and b["effects"] == [
        {"stat": s, "value": 100} for s in ("atk", "def", "int", "res", "hit", "spd")]   # D4SIG3: the six traced stats
    assert evility.table({27878: b})


def test_friends_raises_the_six_traced_stats_not_hp_sp():
    """D4SIG4: Friends 840 (term 0x348 of FUN_1401BA0A0) feeds the same six-stat percent as Marona's."""
    b = OVER["D4_Class_1220"]["behaviors"]["evilities"]["8840"]
    assert [e["stat"] for e in b["effects"]] == ["atk", "def", "int", "res", "hit", "spd"]
    assert all(e["per"] == "map_squad" and e["value"] == 5 for e in b["effects"])
