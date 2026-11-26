"""D4SIG10: evil_hospital (Medic, Base Hospital 864) lives in wrap_regen; the row and its label."""
import json
from pathlib import Path

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()
MODS = json.loads(OVERLAY.read_text())["mods"]


def test_regen_wrapper_unchanged_and_hospital_assembled():
    tag, target, sites = ev.wrapper("regen")
    assert (tag, target, sites) == (0xE7000C, ev.ROUND_HP_SP, [0x140554B9E, 0x1405FB5DF]) and ev.ROUND_HP_SP == 0x140551AC0
    src = Path(ev.ASM_FILE).read_text()
    assert "call evil_hospital" in src and "mov edx, 27864" in src
    code, labels = ev._assemble(ev._asm_source(*ev.table({})), 0x14808F000)
    assert labels[0xE7000C] > 0x14808F000


def test_base_hospital_row_and_label():
    st = MODS["D4_Class_1240"]
    assert st["behaviors"]["evilities"] == {}
    row = next(r for r in st["skill_rows"] if r["id"] == 27864)
    assert row["value1"] == 5 and row["desc_EN"] == "Allies in the base panel recover 5％ HP and SP every turn."
    assert sorted(st["char_links"]) == [str(14240 + i) for i in range(6)]
    assert all(v["evility1"] == 27864 and v["evility_count"] == 1 for v in st["char_links"].values())
    line = next(a for a in st["adaptations"] if a.startswith("evility Base Hospital (864)"))
    assert line.startswith("evility Base Hospital (864): exact rule") and "Not carried" in line
