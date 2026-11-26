"""D4SIG8: wrap_endturn (Demon Beast, Stone Statue 807) and the row's exact-rule label."""
import json
from pathlib import Path

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()
MODS = json.loads(OVERLAY.read_text())["mods"]


def test_endturn_wrapper_registered():
    tag, target, sites = ev.wrapper("endturn")
    assert (tag, target) == (0xE70021, ev.END_TURN) and ev.END_TURN == 0x140159F50
    assert sites == [0x1405524FF, 0x140554F7F, 0x1405FB9B1]
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)
    code, labels = ev._assemble(ev._asm_source(*ev.table({})), 0x14808F000)
    assert labels[0xE70021] > 0x14808F000


def test_stone_statue_row_and_label():
    st = MODS["D4_Class_2090"]
    assert st["behaviors"]["evilities"]["27807"] == {"family": "stats", "effects": [{"stat": "def", "value": 10, "per": "idle_turns"}]}
    row = next(r for r in st["skill_rows"] if r["id"] == 27807)
    assert "adaptation" not in row["desc_EN"].lower() and row["desc_EN"] == "Increase DEF by 10％ every turn of not moving."
    line = next(a for a in st["adaptations"] if a.startswith("evility Stone Statue (807)"))
    assert line.startswith("evility Stone Statue (807): exact rule") and "Not carried" in line and "adapted" not in line.split("Not carried")[0].lower()
