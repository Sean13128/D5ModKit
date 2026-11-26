"""LONGTAIL3: Battle Suit 802 Self-Destruct (kit family self_destruct in wrap_face_away -> the native explosion FUN_1401A3E80)."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev

from d4rules import mods as _rule_mods
OVERLAY = _rule_mods()["D4_Class_1190"]
ROW = 27802


def test_self_destruct_family_and_value_rule():
    assert ev.EXT_FAMILIES["self_destruct"] == 11 and ev.ext_query("self_destruct") == 1 << 43
    assert "self_destruct" in ev.EXT_VALUE_FAMILIES
    ev.table({ROW: {"family": "self_destruct", "effects": [{"value": 10}]}})
    for bad in ({"family": "self_destruct"}, {"family": "self_destruct", "effects": [{"value": 0}]},
                {"family": "self_destruct", "effects": [{"value": 101}]},
                {"family": ["self_destruct", "regen"], "effects": [{"value": 10}]}):
        with pytest.raises(ValueError):
            ev.table({ROW: bad})


def test_battle_suit_pack_row_links_and_label():
    assert OVERLAY["behaviors"]["evilities"][str(ROW)] == {"family": "self_destruct", "effects": [{"value": 10}]}
    rows = [r for r in OVERLAY["skill_rows"] if r["id"] == ROW]
    assert len(rows) == 1 and rows[0]["owner"] == 14190 and rows[0]["kind"] == 1 and rows[0]["name_EN"] == "Self-Destruct"
    links = [v for k, v in OVERLAY["char_links"].items() if v["evility1"] == ROW]
    assert sorted(OVERLAY["char_links"]) == [str(14190 + i) for i in range(6)] and len(links) == 6
    label = [a for a in OVERLAY["adaptations"] if "Self-Destruct (802)" in a]
    assert len(label) == 1
    for need in ("adapted", "FUN_14010DE70", "CODE", "COMMUNITY", "community, not code", "FUN_1401A3E80", "Not carried", "not run offline"):
        assert need in label[0], need


def test_wrapper_site_is_the_existing_face_away_pass():
    tag, target, sites = ev.wrapper("face_away")
    assert (tag, target, sites) == (0xE7001E, ev.POST_HIT, [0x14053FE71])
    src = Path(ev.ASM_FILE).read_text()
    a = src.index("\nwrap_face_away:")
    body = src[a:src.index("\nwrap_atkcount:", a)]
    assert "call 0x1401a3e80" in body and "0x80000000000" in body and "cmp dword ptr [rsi + 0x11dc], 0" in body
    code, labels = ev._assemble(ev._asm_source(*ev.table({ROW: {"family": "self_destruct", "effects": [{"value": 10}]}})), 0x14808F000)
    assert code
