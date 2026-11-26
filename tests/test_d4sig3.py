"""D4SIG3: Phantom Lover and Eccarlate raise the six stats D4 applies the percent to; support_magic_percent (Chief) is wired."""
import json
from pathlib import Path

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()
SIX = ["atk", "def", "int", "res", "hit", "spd"]


def _mods():
    return json.loads(OVERLAY.read_text())["mods"]


def test_phantom_lover_and_eccarlate_raise_six_stats_not_hp_sp():
    m = _mods()
    marona = m["D4_Unique_440"]["behaviors"]["evilities"]["27875"]
    assert [e["stat"] for e in marona["effects"]] == SIX and all(e["per"] == "map_class_ally" for e in marona["effects"])
    ash = m["D4_Unique_450"]["behaviors"]["evilities"]["27878"]
    assert [e["stat"] for e in ash["effects"]] == SIX and all(e["value"] == 100 for e in ash["effects"])
    assert ev.table({27875: marona, 27878: ash})                      # the runtime accepts both


def test_support_magic_percent_family_and_wrapper():
    assert ev.FAMILIES["support_magic_percent"] == ev.F_SUPPORT == 1 << 29
    assert ev.F_SUPPORT in ev.STACK_FAMILIES                           # its own wrapper: cannot share a row with another family
    assert ev.wrapper("support_boost") == (0xE7001B, ev.SUPPORT_BOOST, [0x1401C0076, 0x140201F03])
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)
    rows, _c, _fx = ev.table({8304: {"family": "support_magic_percent", "effects": [{"value": 50}]}})
    assert rows[0][1] == ev.F_SUPPORT
    try:
        ev.table({8305: {"family": "support_magic_percent", "effects": [{"value": 50}, {"stat": "atk", "value": 1}]}})
    except ValueError:
        pass
    else:
        raise AssertionError("a stat on a number family must be refused")


def test_chief_row_and_label():
    chief = _mods()["D4_Unique_5301"]
    assert chief["behaviors"]["evilities"]["8304"] == {"family": "support_magic_percent", "effects": [{"value": 50}]}
    assert chief["aliases"] == {"8304": 1180}                           # D5's own x2 stays for the alias; the wrapper overrides it
    line = next(a for a in chief["adaptations"] if a.startswith("evility Medical Insertion ("))
    assert "exact text and number" in line and "adapted" not in line.lower(), line
