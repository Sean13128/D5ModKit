"""NEMO1: Nemo 820 Physical Malice (kit family summon_malice, evil_nemo called from wrap_revenge -> unit_spawn_from_request)."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev

from d4rules import mods as _rule_mods
OVERLAY = _rule_mods()["D4_Unique_220"]
ROW = 27820


def test_summon_malice_family_is_a_flag_row():
    assert ev.EXT_FAMILIES["summon_malice"] == 13 and ev.ext_query("summon_malice") == 1 << 45
    assert "summon_malice" not in ev.EXT_VALUE_FAMILIES
    ev.table({ROW: {"family": "summon_malice"}})
    with pytest.raises(ValueError):
        ev.table({ROW: {"family": "summon_malice", "effects": [{"value": 1}]}})


def test_standins_are_25_distinct_d5_class_rows():
    assert len(ev.MALICE_STANDINS) == 25 == len(set(ev.MALICE_STANDINS))
    assert all(c % 10 == 0 and (1010 <= c <= 1260 or 2010 <= c <= 2180) for c in ev.MALICE_STANDINS)


def test_nemo_pack_row_links_and_label():
    assert OVERLAY["behaviors"]["evilities"][str(ROW)] == {"family": "summon_malice"}
    rows = [r for r in OVERLAY["skill_rows"] if r["id"] == ROW]
    assert len(rows) == 1 and rows[0]["owner"] == 18110 and rows[0]["kind"] == 1 and rows[0]["name_EN"] == "Physical Malice"
    assert OVERLAY["char_links"]["18110"]["evility1"] == ROW and OVERLAY["aliases"] == {"8872": 143}
    label = [a for a in OVERLAY["adaptations"] if "Physical Malice (820)" in a]
    assert len(label) == 1
    for need in ("adapted", "FUN_1402E99D0", "FUN_1402AD4C0", "CODE", "COMMUNITY", "community, not code", "OUR CHOICES", "unit_spawn_from_request",
                 "team 0 -> 4", "Not carried", "not run offline", "Flooding Malice", "1010 Warrior", "2180 Dragon King"):
        assert need in label[0], need


def test_nemo_pass_is_in_the_existing_round_edge_wrapper():
    tag, target, sites = ev.wrapper("revenge")
    assert (tag, target, sites) == (0xE70015, ev.END_ROUND, [0x1405F8FFC])
    src = Path(ev.ASM_FILE).read_text()
    a = src.index("\nevil_nemo:")
    body = src[a:src.index("// D4SIG7: wrap_atkcount(", a)]
    for need in ("call 0x1401c5ae0", "call 0x1401c3a00", "call 0x14023afa0", "call 0x140136660", "call 0x1401cf4d0", "0x200000000000",
                 "sub rsp, 0x78", "mov r13d, 4"):
        assert need in body, need
    w = src.index("\nwrap_revenge:")
    assert "call evil_nemo" in src[w:src.index("\nwrap_steal:", w)]
    code, labels = ev._assemble(ev._asm_source(*ev.table({ROW: {"family": "summon_malice"}})), 0x14808F000)
    assert code
