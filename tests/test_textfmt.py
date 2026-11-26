"""Skill Trainer descriptions must survive its extra formatting pass."""
from d5lib import textfmt


def test_vanilla_percent_and_value_are_preserved():
    text = "Increase HIT by %d％."
    assert not textfmt.bad_format(text)
    assert textfmt.format_text(text) == text


def test_literal_percent_forms_become_full_width():
    for text in ("10%.", "10%%.", "10%%%%."):
        assert textfmt.bad_format(text)
        assert textfmt.format_text(text) == "10％."
    text = "DEF & RES increased by 50%% when HP is under 25%%."
    assert textfmt.format_text(text) == "DEF & RES increased by 50％ when HP is under 25％."


def test_idempotence_and_placeholder():
    once = textfmt.format_text("Deal %d%% more damage, 5% less often.")
    assert once == "Deal %d％ more damage, 5％ less often."
    assert textfmt.format_text(once) == once
    assert not textfmt.bad_format(once)
    assert textfmt.bad_format("%%%%%")
    assert textfmt.bad_format(textfmt.format_text("%%%%%"))


def test_fix_row_touches_every_language():
    row = dict(id=8062, desc_JP="SP Aptitude increased by 10%%.", desc_EN="SP Aptitude increased by 10%.",
               desc_FR="", desc_CHN=None)
    assert textfmt.fix_row(row) == ["desc_JP", "desc_EN"]
    assert row["desc_JP"] == row["desc_EN"] == "SP Aptitude increased by 10％."
    assert row["desc_FR"] == ""


def test_validator_refuses_escaped_literal(tmp_path):
    from d5lib import d4pilotfix
    skill = dict(table="Skill.dat", added=[dict(id=9001, kind=0, slot_cost=2, source=4, owner=14000,
                                                desc_EN="ATK +10%%.")])
    def problems():
        return d4pilotfix.check_patches(None, skill, None, vanilla_unique=set(), vanilla_magic=set(), family=None)
    assert any("unsafe ASCII %" in p for p in problems())
    skill["added"][0]["desc_EN"] = "ATK +10％."
    assert not any("unsafe ASCII %" in p for p in problems())
