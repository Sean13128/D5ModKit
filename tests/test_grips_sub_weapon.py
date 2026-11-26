"""WEAPONSLOT1: the preview draws the main weapon on slot A (nodes 11-16) only; slot B (111-116) is the sub weapon and
is drawn only when a sub weapon type is given (the game binds it only for a unit with Double Bladed).  Vanilla
anm_resident, the Thief's sword attack 2011 (A and B are both shown by its keys at frame 16); skipped without the game."""
import copy
from pathlib import Path

import pytest

from d5lib import gamefs, grips

GAME = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)")


@pytest.fixture(scope="module")
def assets():
    if not GAME.is_dir():
        pytest.skip("game copy not present")
    from d5gui.skilledit.glrender import Assets
    return Assets(gamefs.GameFS(str(GAME)))


def _from(items, f):
    return sum(1 for ff, _ in items if ff is f)


def test_main_weapon_only_by_default(assets):
    main = assets.weapon(11)
    f = assets.file_of(1090, 2011)
    g = []
    items = grips.evaluate(f, 2011, 16, main, 11, grips=g)
    assert _from(items, main) > 0
    assert {n for n, *_ in g} == {11}                      # slot B nodes are not even drawn candidates
    both = []
    grips.evaluate(f, 2011, 16, main, 11, groups=("A", "B"), grips=both)
    assert {n for n, *_ in both} == {11, 111}              # the Weapon Grips page still sees both nodes
    assert {n for n, _g, _p, shown, _m in both if shown} == {11, 111}   # and the keys show both at this frame


def test_sub_weapon_on_slot_b(assets):
    main = assets.weapon(11)
    sub = copy.copy(main)                                  # a distinct object to count its draws
    f = assets.file_of(1090, 2011)
    items = grips.evaluate(f, 2011, 16, main, 11, sub_weapon=sub, sub_wtype=11)
    assert _from(items, main) > 0 and _from(items, sub) > 0
    one = grips.evaluate(f, 2011, 16, main, 11)
    assert _from(one, main) == _from(items, main) and _from(one, sub) == 0
    # a sub weapon of another type uses that type's slot-B node (spear 112), which this frame also shows
    sp = assets.weapon(12)
    mixed = grips.evaluate(f, 2011, 16, main, 11, sub_weapon=sp, sub_wtype=12)
    assert _from(mixed, sp) > 0 and _from(mixed, main) == _from(one, main)


def test_page_hand_groups_unchanged(assets):
    main = assets.weapon(11)
    f = assets.file_of(1090, 2011)
    b_only = grips.evaluate(f, 2011, 16, main, 11, ("B",))
    assert _from(b_only, main) > 0                         # editing slot B on the page shows the model on node 111
