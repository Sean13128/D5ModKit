from tools.check_ui_strings import check


def test_quest_name_reference_and_unknown_width():
    limits = {('quest.dat', 'name_en'): 19}
    assert not check('Quest.dat', {'name_EN': 'Loves Pointlessness'}, limits)
    assert len(check('Quest.dat', {'name_EN': 'A Present for the Netherworld'}, limits)) == 1
    assert 'unmeasured' in check('Quest.dat', {'name_EN': 'Noël'}, limits)[0]
    assert not check('Skill.dat', {'name_EN': 'x' * 40}, limits)
