"""D4SIG2: the idle_turns scale encodes as designed, and the D4 overlay labels say what the tracker reads."""
import json
from pathlib import Path

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()


def test_idle_turns_scale_encodes():
    assert ev.SCALES["idle_turns"] == 26
    _r, _c, fx = ev.table({27807: {"family": "stats", "effects": [{"stat": "def", "value": 10, "per": "idle_turns"}]}})
    assert fx == [(3 | 26 << 16, 10)]


def _lines(pack):
    mods = json.loads(OVERLAY.read_text())["mods"]
    return [a for a in mods[pack]["adaptations"] if a.startswith("evility ")]


def test_exact_labels_and_hugo_second_slot_are_not_innate():
    for pack, name in (("D4_Class_2120", "Mind Killer"), ("D4_Unique_170", "Mind Killer"), ("D4_Unique_450", "Eccarlate"), ("D4_Class_2130", "Accel Element"),
                       ("D4_Unique_440", "Phantom Lover")):   # D4SIG3: stat set traced (six), so exact
        line = next(a for a in _lines(pack) if a.startswith(f"evility {name} (") and "placeholder" not in a)
        assert "exact text and number" in line and "adapted" not in line.lower(), line
    # Gig (+15 vs D4 +50) stays honestly adapted (coordinator, 2026-11-12)
    for pack, name in (("D4_Unique_340", "Jet Black Sword"),):
        line = next(a for a in _lines(pack) if a.startswith(f"evility {name} (") and "placeholder" not in a)
        assert "adapted" in line.lower() and "exact text and number" not in line, line
    death_magic = next(a for a in _lines("D4_Unique_170") if "Death Magic" in a)
    assert "innate" not in death_magic.lower()


def test_stone_statue_reads_the_idle_counter_exact_rule_since_d4sig8():
    mods = json.loads(OVERLAY.read_text())["mods"]
    row = mods["D4_Class_2090"]["behaviors"]["evilities"]["27807"]
    assert row["effects"] == [{"stat": "def", "value": 10, "per": "idle_turns"}]
    # D4SIG8: the counting is D4's now (wrap_endturn); the label no longer says adapted (tests/test_d4sig8.py)
    assert any("Stone Statue (807): exact rule" in a for a in _lines("D4_Class_2090"))
