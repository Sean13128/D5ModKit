"""NECRO1: Necromancer 868 Necromancy (kit family raise_zombie, evil_necro called from wrap_face_away -> unit_spawn_from_request)."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev

from d4rules import mods as _rule_mods
OVERLAY = _rule_mods()["D4_Class_1250"]
ROW = 27868


def test_raise_zombie_family_is_a_flag_row():
    assert ev.EXT_FAMILIES["raise_zombie"] == 12 and ev.ext_query("raise_zombie") == 1 << 44
    assert "raise_zombie" not in ev.EXT_VALUE_FAMILIES
    ev.table({ROW: {"family": "raise_zombie"}})
    with pytest.raises(ValueError):
        ev.table({ROW: {"family": "raise_zombie", "effects": [{"value": 1}]}})


def test_necromancer_pack_row_links_and_label():
    assert OVERLAY["behaviors"]["evilities"][str(ROW)] == {"family": "raise_zombie"}
    rows = [r for r in OVERLAY["skill_rows"] if r["id"] == ROW]
    assert len(rows) == 1 and rows[0]["owner"] == 14250 and rows[0]["kind"] == 1 and rows[0]["name_EN"] == "Necromancy"
    links = [v for k, v in OVERLAY["char_links"].items() if v["evility1"] == ROW]
    assert sorted(OVERLAY["char_links"]) == [str(14250 + i) for i in range(6)] and len(links) == 6
    label = [a for a in OVERLAY["adaptations"] if "Necromancy (868)" in a]
    assert len(label) == 1
    for need in ("adapted", "FUN_1400F2680", "FUN_140302530", "CODE", "COMMUNITY", "community, not code", "unit_spawn_from_request",
                 "team 0 -> 4", "Not carried", "not run offline"):
        assert need in label[0], need


def test_necro_pass_is_in_the_existing_face_away_wrapper():
    tag, target, sites = ev.wrapper("face_away")
    assert (tag, target, sites) == (0xE7001E, ev.POST_HIT, [0x14053FE71])
    src = Path(ev.ASM_FILE).read_text()
    a = src.index("\nevil_necro_note:")     # NECRO2: the note routine, then evil_necro (the end-pass spawn)
    body = src[a:src.index("// NEMO1: evil_nemo(", a)]
    for need in ("call 0x1401c5ae0", "call 0x1401c3a00", "0x100000000000", "mov dword ptr [rsp + 0x38], 2090", "sub rsp, 0x78", "], 1     // HP 1", "evil_zq", "evil_zdbg"):
        assert need in body, need
    assert "call evil_necro_note" in src[src.index("\nwrap_atkcount:"):src.index("\nwrap_endturn:")]
    code, labels = ev._assemble(ev._asm_source(*ev.table({ROW: {"family": "raise_zombie"}})), 0x14808F000)
    assert code
