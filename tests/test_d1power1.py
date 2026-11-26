import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("d1_power_model", Path(__file__).resolve().parents[1] / "tools/d1_power_model.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_d1_power_formula_pieces():
    # FUN_0046f5e0 soft cap on level + 100 (floor 25)
    assert [m.soft(x) for x in (0, 130, 500, 900, 1000, 2000)] == [25, 130, 500, 700, 750, 950]
    # a D1 special is 1.5x a normal hit before its power counts; D5 needs +50 % for that
    assert abs(m.d1_ratio(0, 30, 200) - 1.5) < 1e-9
    assert abs(m.d5_percent(1.5) - 50) < 1e-9
    # Jack Rush (power 35) by a Prinny (D1 ATK base 13, aptitude 100 %) at its learn level 30: ATK 201.5, v = 45.5
    assert round(m.predict(35, (16, 8, 13, 9, 12, 10, 10, 8), bytes([10] * 8), 30)) == 84
    # defence enters both games as "attack - about half DEF": with D5 holding D1's stat profile the ratio barely moves
    no_def = m.predict(35, (16, 8, 13, 9, 12, 10, 10, 8), bytes([10] * 8), 30)
    with_def = m.predict(35, (16, 8, 13, 9, 12, 10, 10, 8), bytes([10] * 8), 30, defence=True)
    assert 0 < no_def - with_def < 20
