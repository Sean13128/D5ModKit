"""d5lib.classcheck: the identity rules a built class / unique pack must pass.

The D1C and DD2 class packs shipped without charPersonal rows and wedged the Recruiter's create
flow live (HUB2 §3/§5/§8); three recruit quests pointed at other characters' rows.  These tests pin
the rules that make those packs fail at build time instead.
"""
import json
import os

import pytest

from d5lib import classcheck


def build_mod(root, family=11390, ranks=6, personalities=0, unlocked_ranks=6,
              quests=(), char_rows=None, face=True):
    """A mod folder shaped like nativeimports.build_entry writes it."""
    d = os.path.join(str(root), "patches")
    os.makedirs(os.path.join(d, "classes"), exist_ok=True)
    os.makedirs(os.path.join(d, "db"), exist_ok=True)
    spec = dict(family=family, template=1110, kind="humanoid", sprite_family=1540, name="Strider",
                unlocked=True, unlocked_ranks=unlocked_ranks, hire_desc="x")
    with open(os.path.join(d, "classes", "class_%d.json" % family), "w", encoding="utf-8") as f:
        json.dump(spec, f)
    if face:
        open(os.path.join(d, "classes", "face_%d.png" % family), "wb").close()
    rows = char_rows if char_rows is not None else [family + k for k in range(ranks)]
    tables = {
        "char.dat": dict(table="char.dat", added=[dict(id=r) for r in rows]),
        "JobRank.dat": dict(table="JobRank.dat", added=[dict(id=family + k) for k in range(ranks)]),
        "charhelp.dat": dict(table="charhelp.dat", added=[dict(id=family, char_id=family)]),
    }
    if personalities:
        tables["charPersonal.dat"] = dict(
            table="charPersonal.dat",
            added=[dict(id=9000 + k, voice_group=family // 10, variant=k, name_EN=name)
                   for k, name in enumerate(("Diligent", "Proud", "Newbie")[:personalities])])
    if quests:
        tables["Quest.dat"] = dict(table="Quest.dat", added=list(quests))
    for name, patch in tables.items():
        with open(os.path.join(d, "db", name + ".json"), "w", encoding="utf-8") as f:
            json.dump(patch, f)
    return str(root)


def rules(findings):
    return sorted({f["rule"] for f in findings})


def test_missing_personalities_are_an_error(tmp_path):
    mod = build_mod(tmp_path)
    found = classcheck.check(mod)
    assert "R1-personalities" in rules(found)
    assert [f for f in found if f["rule"] == "R1-personalities"][0]["rows"] == 0


def test_three_personalities_pass(tmp_path):
    mod = build_mod(tmp_path, personalities=3)
    assert classcheck.check(mod) == []


def test_one_or_two_personalities_still_fail(tmp_path):
    for count in (1, 2):
        mod = build_mod(tmp_path / str(count), personalities=count)
        assert "R1-personalities" in rules(classcheck.check(mod))


def test_partial_rank_declaration_is_an_error(tmp_path):
    mod = build_mod(tmp_path, personalities=3, unlocked_ranks=1)
    found = classcheck.check(mod)
    assert rules(found) == ["R2-ranks"]
    assert found[0]["unlocked_ranks"] == 1


def test_a_kit_family_may_declare_fewer_ranks(tmp_path):
    # 1270-1350 are the game's dummy slots: those ranks unlock by playing, so a partial declaration
    # is a design choice, not the D1C defect (a registry family has no such chain).
    mod = build_mod(tmp_path, family=1330, personalities=3, unlocked_ranks=2)
    assert classcheck.check(mod) == []


def test_missing_face_is_a_warning_but_a_pack_gate(tmp_path):
    mod = build_mod(tmp_path, personalities=3, face=False)
    found = classcheck.check(mod)
    assert rules(found) == ["R3-face"]
    assert found[0]["severity"] == "warning"          # cannot crash the Recruiter
    assert classcheck.errors(found) == []
    assert [f["rule"] for f in classcheck.gate(found)] == ["R3-face"]   # a pack may not ship it


def test_quest_must_reward_an_own_row(tmp_path):
    mod = build_mod(tmp_path, personalities=3,
                    quests=[dict(id=9503, reward_type=5, reward_value=470, reward_count=1)])
    found = classcheck.check(mod)
    assert rules(found) == ["R4-quest-reward"]
    assert found[0]["reward_value"] == 470


def test_quest_rewarding_an_own_row_passes(tmp_path):
    mod = build_mod(tmp_path, personalities=3,
                    quests=[dict(id=9503, reward_type=5, reward_value=11390, reward_count=1)])
    assert classcheck.check(mod) == []


def test_non_recruit_reward_is_not_checked(tmp_path):
    mod = build_mod(tmp_path, personalities=3,
                    quests=[dict(id=9503, reward_type=3, reward_value=4160, reward_count=1)])
    assert classcheck.check(mod) == []


def test_vanilla_character_row_is_refused_but_a_dummy_row_is_not(tmp_path):
    mod = build_mod(tmp_path, personalities=3, ranks=1, char_rows=[80])
    assert rules(classcheck.check(mod, vanilla_char_ids={80})) == ["R5-vanilla-row"]
    dummy = build_mod(tmp_path / "d", personalities=3, ranks=1, char_rows=[470], family=11200)
    assert classcheck.check(dummy, vanilla_char_ids={470}, dummy_rows=(470,)) == []


def test_a_row_another_pack_adds_is_refused(tmp_path):
    mod = build_mod(tmp_path, personalities=3, ranks=1, char_rows=[45], family=11200)
    assert rules(classcheck.check(mod, foreign={45: "Pleinair_Pack"})) == ["R5-foreign-row"]


def test_the_same_mod_does_not_conflict_with_itself(tmp_path):
    mod = build_mod(tmp_path, personalities=3, ranks=1, char_rows=[45], family=11200)
    assert classcheck.check(mod, foreign={45: "Mine"}, owner="Mine") == []


def test_describe_separates_a_broken_pack_from_a_working_one(tmp_path):
    broken = build_mod(tmp_path / "broken")
    working = build_mod(tmp_path / "working", family=14240, personalities=3)
    diff = {d["field"]: d for d in classcheck.diff(classcheck.describe(working),
                                                   classcheck.describe(broken))}
    assert diff["personality"]["left"] == {1424: 3}
    assert diff["personality"]["right"] == {}
    assert diff["tables"]["right"]["charPersonal.dat"]["added"] == 0


def test_check_or_raise_names_every_blocking_rule(tmp_path):
    mod = build_mod(tmp_path, face=False, unlocked_ranks=1)
    with pytest.raises(ValueError) as excinfo:
        classcheck.check_or_raise(mod)
    message = str(excinfo.value)
    for rule in ("R1-personalities", "R2-ranks"):
        assert rule in message
    assert "R3-face" not in message                  # a face is presentation, not identity
