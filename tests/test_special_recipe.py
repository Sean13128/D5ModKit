import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from d5lib.skillarea import Shape
import special_recipe as sr

ROW = dict(id=1, name_EN="X", sp_cost=5, skill_type=0, rank=0, range=0, attack_map=3000, height_up=12, height_down=12)


def test_forward_line_needs_enemy_in_front():
    out = sr.recipe(ROW, {3000: Shape(3000, [(0, 1, 1), (0, 2, 1)])})
    assert "(0, 1), (0, 2)" in out and "No target" in out


def test_item_world_utility_and_ranged():
    assert "Item World" in sr.recipe(dict(ROW, skill_type=2, rank=1, attack_map=1000), {1000: Shape(1000, [(0, 0, 1)])})
    assert "within 3 panels" in sr.recipe(dict(ROW, range=3, attack_map=1), {1: Shape(1, [(0, 0, 3)])})
