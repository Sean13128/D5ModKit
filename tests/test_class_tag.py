"""CLASSTAG1: imported generic classes carry their source game in the name ("Gargoyle (D1C)", "Masked Hero (DD2)").

Two source games ship the same class, so untagged names doubled in the recruit list.  D4 classes were already
tagged " (D4)"; the prepared-source builder now tags D1C / DD2 (and any later game) the same way.
"""
import importlib
import inspect
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

nativeimports = importlib.import_module('d5lib.nativeimports')


@pytest.mark.parametrize('name,game,want', [
    ('Gargoyle', 'd1c', 'Gargoyle (D1C)'),
    ('Masked Hero', 'dd2', 'Masked Hero (DD2)'),
    ('Shark Dragon', 'dd2', 'Shark Dragon (DD2)'),
    ('Killer Armor', 'd1c', 'Killer Armor (D1C)'),
])
def test_tag_follows_the_mod_title_spelling(name, game, want):
    assert nativeimports.class_display_name(name, game) == want


def test_longest_tagged_name_fits_the_slot():
    longest = max(nativeimports.class_display_name(n, g) for n, g in
                  [('Killer Armor', 'd1c'), ('Living Armor', 'dd2'), ('Shark Dragon', 'dd2')])
    assert len(longest) <= 18 < 52          # char.dat name_* slots are 52 bytes


def test_generic_build_tags_once_and_uniques_stay_plain():
    src = inspect.getsource(nativeimports.build_entry)
    assert 'if generic:\n            product_name = class_display_name(product_name' in src
    # the mod title must not gain a second suffix for classes; uniques keep their " (GAME)" title only
    assert "name=(product_name if generic else class_display_name(product_name" in src
    assert "_set_latin(row, 'name', product_name, source['name'])" in src      # unique rows: untagged name
