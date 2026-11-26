"""D4SIG10b: Roc, Miasma of Silence (special_seal, wrap_roc_geo, wrap_roc_skill) and its adapted label."""
import json
from pathlib import Path

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()
MODS = json.loads(OVERLAY.read_text())["mods"]


def test_wrappers_registered():
    assert ev.wrapper("roc_geo") == (0xE70022, ev.EFFECT_SUM, [0x140156A47]) and ev.EFFECT_SUM == 0x14015B890
    tag, target, sites = ev.wrapper("roc_skill")
    assert (tag, target) == (0xE70023, ev.CAN_USE_SKILL) and ev.CAN_USE_SKILL == 0x140155280
    assert sites == [0x14054785D, 0x1402D0A90, 0x14062E7BD, 0x14062EC38]
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)
    code, labels = ev._assemble(ev._asm_source(*ev.table({27115: {"family": "special_seal"}})), 0x14808F000)
    assert labels[0xE70022] > 0x14808F000 and labels[0xE70023] > labels[0xE70022]


def test_special_seal_family_is_a_plain_predicate_row():
    assert ev.EXT_FAMILIES["special_seal"] == 4 and ev.ext_query("special_seal") == 1 << 36
    rows, conds, fx = ev.table({27115: {"family": "special_seal"}})
    assert len(rows) == 1 and not fx


def test_roc_row_and_label():
    st = MODS["D4_Class_2110"]
    assert st["behaviors"]["evilities"]["27115"] == {"family": "special_seal"}
    row = next(r for r in st["skill_rows"] if r["id"] == 27115)
    assert row["value1"] == 100 and row["desc_EN"] == "Prohibits special skill use by adjacent enemy units."
    assert all(v["evility1"] == 27115 and v["evility_count"] == 1 for v in st["char_links"].values()) and len(st["char_links"]) == 6
    line = next(a for a in st["adaptations"] if a.startswith("evility Miasma of Silence (115)"))
    assert line.startswith("evility Miasma of Silence (115): adapted") and "Not carried" in line and "Fetters" in line
