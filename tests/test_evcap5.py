"""EVCAP5: a learnable evility row must carry a display category.

The evility list filters on `category == tab || subcategory == tab` (0x1407CDB30 at
`mov eax,[screen+0x1b850]`; FUN_140832120 does the same with the rank tab).  The game's own
587 learnable rows all have a non-zero category; the rows the D4/D1C/DD2 importers add were
emitted with 0, which is only reachable on the unfiltered tab -- so an imported evility
vanished from any filtered evility list and could not be equipped from one.

`dbpatch.fix_evility_category` fills that 0 at patch time, deterministically, and never
overrides a category the patch names or touches a row the game would not offer to equip.

The offline proof that the two list builders really do list an id whose learning lives only
in the Kit's store is evility/probe_replay_equip.py (executes the game's own functions against
the real .d5lc section); these tests cover the data rule that decides whether a listed row is
reachable at all.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from d5lib import database, dbpatch  # noqa: E402

VANILLA = os.environ.get('D5_VANILLA', '/Volumes/Data/ai-tmp/magichange/vanilla/Database_0.dat')


def _table():
    if not os.path.exists(VANILLA):
        pytest.skip('the vanilla database is not on this machine')
    db = database.load_database(VANILLA)                        # read-only use
    return database.load_table('Skill.dat', db.table('Skill.dat').to_bytes())


def _row(category=0, kind=0, mana_cost=1000, effect_group=0):
    row = {'id': 9001, 'kind': kind, 'mana_cost': mana_cost, 'category': category,
           'effect_group': effect_group, 'name_EN': 'Test Evility'}
    return row


class _FakeRow(dict):
    def set(self, name, value, truncate=False):
        self[name] = value


@pytest.mark.parametrize('group,expected', sorted(dbpatch.EVILITY_CATEGORY.items()))
def test_group_map_matches_the_games_own_rows(group, expected):
    """Every category in the table is one the game's own learnable rows of that group use."""
    table = _table()
    cats = {r['category'] for r in table.rows
            if r['kind'] != 1 and r['mana_cost'] > 0 and r['effect_group'] == group}
    assert cats, f'effect group {group} has no learnable row in the vanilla table'
    assert expected in cats


def test_the_game_has_no_learnable_row_without_a_category():
    table = _table()
    bad = [r['id'] for r in table.rows
           if r['kind'] != 1 and r['mana_cost'] > 0 and not r['category']]
    assert bad == [], f'the vanilla table already breaks the rule: {bad[:5]}'


def test_fix_fills_a_missing_category():
    row = _FakeRow(**_row(effect_group=0))
    assert dbpatch.fix_evility_category(row, 'Skill.dat') is True
    assert row['category'] == dbpatch.EVILITY_CATEGORY[0]


def test_fix_keeps_a_named_category():
    row = _FakeRow(**_row(category=7))
    assert dbpatch.fix_evility_category(row, 'Skill.dat') is False
    assert row['category'] == 7


@pytest.mark.parametrize('fields', [dict(kind=1), dict(mana_cost=0), dict(kind=2)])
def test_fix_leaves_rows_the_game_does_not_offer(fields):
    row = _FakeRow(**_row(**fields))
    assert dbpatch.fix_evility_category(row, 'Skill.dat') is False
    assert row['category'] == 0


def test_fix_is_skill_dat_only():
    row = _FakeRow(**_row())
    assert dbpatch.fix_evility_category(row, 'Item.dat') is False
    assert row['category'] == 0


def test_an_unknown_group_falls_back_to_the_common_tab():
    row = _FakeRow(**_row(effect_group=99))
    assert dbpatch.fix_evility_category(row, 'Skill.dat') is True
    assert row['category'] == 1


def test_apply_patch_fixes_an_added_evility_row():
    table = _table()
    patch = {'table': 'Skill.dat', 'added': [{'id': 9999, 'kind': 0, 'mana_cost': 1000,
                                              'category': 0, 'effect_group': 9,
                                              'name_EN': 'EVCAP5 Test'}]}
    dbpatch.apply_patch(table, patch)
    row = [r for r in table.rows if r['id'] == 9999][0]
    assert row['category'] == dbpatch.EVILITY_CATEGORY[9]


def test_apply_patch_fixes_an_edited_evility_row():
    table = _table()
    target = [i for i, r in enumerate(table.rows)
              if r['kind'] != 1 and r['mana_cost'] > 0 and r['category']][0]
    ident = table.rows[target]['id']
    dbpatch.apply_patch(table, {'table': 'Skill.dat', 'rows': {str(target): {'category': 0}}})
    row = [r for r in table.rows if r['id'] == ident][0]
    assert row['category'] == dbpatch.EVILITY_CATEGORY.get(row['effect_group'], 1)


def test_the_table_still_round_trips():
    table = _table()
    assert database.load_table('Skill.dat', table.to_bytes()).to_bytes() == table.to_bytes()
