"""PT2 repair rules: one innate evility per unit, commons stay common (no game data)."""
import json
from pathlib import Path

import pytest

from d5lib import d4pilotfix as fx


def char_patch(rows, added=()):
    return {"table": "char.dat", "rows": {str(i): r for i, r in enumerate(rows)}, "added": list(added)}


def char_row(cid, evilities=(), count=None, learn=(), extra=None):
    row = {"id": cid, "evility1": 0, "evility2": 0, "evility3": 0, "evility4": 0,
           "evility_count": 0, "learn_count": 0}
    for n in range(1, 17):
        row[f"learn{n}_skill"] = 0
        row[f"learn{n}_level"] = 0
    for n, e in enumerate(evilities, 1):
        row[f"evility{n}"] = e
    row["evility_count"] = len(evilities) if count is None else count
    for n, (sid, level) in enumerate(learn, 1):
        row[f"learn{n}_skill"] = sid
        row[f"learn{n}_level"] = level
    row["learn_count"] = len(learn)
    row.update(extra or {})
    return row


def skill_patch(rows):
    return {"table": "Skill.dat", "added": list(rows)}


def stage(tmp_path, char=None, skill=None, magic=None):
    root = Path(tmp_path)
    if char is not None:
        (root / "patches/db").mkdir(parents=True, exist_ok=True)
        (root / "patches/db/char.dat.json").write_text(json.dumps(char))
    if skill is not None:
        (root / "patches/db").mkdir(parents=True, exist_ok=True)
        (root / "patches/db/Skill.dat.json").write_text(json.dumps(skill))
    if magic is not None:
        (root / "patches/db").mkdir(parents=True, exist_ok=True)
        (root / "patches/db/magic.dat.json").write_text(json.dumps(magic))
    return root


def test_common_slot_cost_ladder():
    assert fx.slot_cost_for_mana(100) == 2
    assert fx.slot_cost_for_mana(800) == 3
    assert fx.slot_cost_for_mana(1000) == 3
    assert fx.slot_cost_for_mana(5000) == 4
    assert fx.slot_cost_for_mana(30000) == 5
    assert fx.slot_cost_for_mana(None) == 2


def test_installed_playtest_row_collapses_to_the_class_evility(tmp_path):
    """The shipped pilot put four class evilities in evility1..4 (owner saw four UNIQUE)."""
    rows = [char_row(303, [7000, 7001, 7002, 7003], count=4),
            char_row(308, [7000, 7001, 7002, 7003], count=4)]
    stage(tmp_path, char=char_patch(rows))
    receipt = fx.enforce_innates(tmp_path, {7000, 6032}, require_one=True)
    patch = json.loads((Path(tmp_path) / "patches/db/char.dat.json").read_text())
    for row in patch["rows"].values():
        assert [row["evility1"], row["evility2"], row["evility3"], row["evility4"]] == [7000, 0, 0, 0]
        assert row["evility_count"] == 1
    assert [r["char_id"] for r in receipt] == [303, 308]
    assert receipt[0]["dropped"] == [7001, 7002, 7003]


def test_vanilla_unique_innate_is_kept(tmp_path):
    stage(tmp_path, char=char_patch([char_row(570, [6032], count=1)]))
    assert fx.enforce_innates(tmp_path, {6032}, require_one=True) == []
    row = json.loads((Path(tmp_path) / "patches/db/char.dat.json").read_text())["rows"]["0"]
    assert row["evility1"] == 6032 and row["evility_count"] == 1


def test_two_uniques_are_refused(tmp_path):
    stage(tmp_path, char=char_patch([char_row(303, [7000, 7004], count=2)]))
    with pytest.raises(ValueError, match="2 unique evilities"):
        fx.enforce_innates(tmp_path, {7000, 7004}, require_one=True)


def test_row_without_a_unique_is_refused_for_a_class(tmp_path):
    stage(tmp_path, char=char_patch([char_row(303, [8062], count=1)]))
    with pytest.raises(ValueError, match="no unique evility"):
        fx.enforce_innates(tmp_path, {7000}, require_one=True)


def test_common_slot_costs_are_never_free(tmp_path):
    stage(tmp_path, skill=skill_patch([
        {"id": 8062, "kind": 0, "slot_cost": 0, "mana_cost": 100},
        {"id": 8085, "kind": 0, "slot_cost": 0, "mana_cost": 30000},
        {"id": 8347, "kind": 1, "slot_cost": 3, "mana_cost": 0}]))
    receipt = fx.set_common_slot_costs(tmp_path)
    rows = {r["id"]: r for r in json.loads((Path(tmp_path) / "patches/db/Skill.dat.json").read_text())["added"]}
    assert rows[8062]["slot_cost"] == 2 and rows[8085]["slot_cost"] == 5
    assert rows[8347]["slot_cost"] == 0
    assert {r["id"] for r in receipt} == {8062, 8085, 8347}


def test_validate_flags_the_playtest_defects():
    char = char_patch([char_row(308, [7000, 7001, 7002, 7003], count=4)],
                      [char_row(216, [], count=0, learn=[(10571, 1)])])
    skill = skill_patch([{"id": 8062, "kind": 0, "slot_cost": 0, "mana_cost": 100, "source": 4, "owner": 1350},
                         {"id": 7000, "kind": 1, "slot_cost": 0, "source": 4, "owner": 1350}])
    problems = fx.check_patches(char, skill, None, vanilla_unique={7000, 6032},
                                vanilla_magic={10571}, family=1350, exactly_one=True)
    text = "\n".join(problems)
    assert "non-unique evility in an innate slot" in text
    assert "4 innate evilities" in text
    assert "common evility with slot_cost 0" in text
    assert "0 innate evilities" in text


def test_validate_accepts_the_repaired_shape():
    char = char_patch([char_row(308, [7000], count=1, learn=[(13018, 1)])])
    skill = skill_patch([{"id": 8062, "kind": 0, "slot_cost": 2, "mana_cost": 100, "source": 4, "owner": 1350},
                         {"id": 7000, "kind": 1, "slot_cost": 0, "source": 4, "owner": 1350}])
    magic = {"table": "magic.dat", "added": [{"id": 13018}]}
    assert fx.check_patches(char, skill, magic, vanilla_unique={7000},
                            vanilla_magic=set(), family=1350, exactly_one=True) == []


def test_validate_refuses_a_tree_that_is_not_there(tmp_path):
    """An empty path must not pass as 'no problems' (a false pass hides a missing build)."""
    with pytest.raises(ValueError, match="not a staged mod"):
        fx.validate_mod(None, tmp_path, family=1350)


def test_source_three_class_evility_is_refused_on_an_imported_class():
    skill = skill_patch([{"id": 7002, "kind": 0, "slot_cost": 4, "mana_cost": 5000,
                          "source": 3, "owner": 1150}])
    problems = fx.check_patches(None, skill, None, vanilla_unique=set(), vanilla_magic=set(),
                                family=1350)
    assert any("source 3" in p for p in problems)
    assert any("owner 1150" in p for p in problems)
