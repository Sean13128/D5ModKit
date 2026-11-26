"""MASKWIDE1: the second family word (flags bits 8..31) and Death Saber 836 (face_target_away, wrap_face_away)."""
import json
import struct
from pathlib import Path

import pytest

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()


def test_old_rows_encode_as_before():
    # every first-word family keeps mask = the family bits and flags = the scope alone (bits 8+ are 0)
    for name, bit in ev.FAMILIES.items():
        if name in ("aura", "resistance"):
            continue
        row = ev.table({7000: _minimal(name)})[0][0]
        assert row[1] == bit and row[6] == 0 and row[7] == 0, name
    rows, _c, _f = ev.table({}, {5: {"family": "dealt", "effects": [{"value": 1}]}})
    assert rows[0][1] == ev.F_DEALT and rows[0][6] == ev.ROW_SKILL


def _minimal(name):
    if name in [ev.FAMILY_NAME[f] for f in ev.PREDICATE_FAMILIES]:
        return {"family": name}
    if name == "conversion":
        return {"family": name, "effects": [{"stat": "atk", "from": "def", "value": 5}]}
    if name == "regen":
        return {"family": name, "effects": [{"stat": "hp", "value": 1}]}
    if name in ("potency", "stats", "growth"):
        return {"family": name, "effects": [{"stat": "atk", "value": 1}]}
    return {"family": name, "effects": [{"value": 1}]}


def test_second_word_row():
    rows, conds, fx = ev.table({27836: {"family": "face_target_away"}})
    evid, mask, cond_off, n_cond, fx_off, n_fx, flags, filt = rows[0]
    assert (evid, mask, n_cond, n_fx, filt) == (27836, 0, 0, 0, 0)
    assert flags == 1 << 8 and ev.ext_query("face_target_away") == 1 << 32
    assert not (flags & ev.ROW_SKILL)


def test_second_word_rules():
    for bad in ({"family": ["face_target_away", "dealt"], "effects": [{"value": 1}]},
                {"family": "face_target_away", "effects": [{"value": 1}]}):
        with pytest.raises(ValueError):
            ev.table({1: bad})
    with pytest.raises(ValueError):                              # not a skill-scope family
        ev.table({}, {1: {"family": "face_target_away"}})
    old = dict(ev.EXT_FAMILIES)
    try:
        ev.EXT_FAMILIES["test_b"] = 3
        assert ev.table({1: {"family": "test_b"}})[0][0][6] == 1 << 11
        with pytest.raises(ValueError):                          # two second-word families on one row
            ev.table({1: {"family": ["face_target_away", "test_b"]}})
        ev.EXT_FAMILIES["test_c"] = 24
        with pytest.raises(ValueError):
            ev.table({1: {"family": "test_c"}})
    finally:
        ev.EXT_FAMILIES.clear()
        ev.EXT_FAMILIES.update(old)


def test_wrapper_and_site():
    tag, target, sites = ev.wrapper("face_away")
    assert (tag, target, sites) == (0xE7001E, ev.POST_HIT, [0x14053FE71]) and ev.POST_HIT == 0x140542CB0
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)
    exe = Path("/Volumes/Data/Projects/D5/D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
    if exe.exists():
        raw = exe.read_bytes()
        off = ev._offset(raw, 0x14053FE71)
        assert raw[off] == 0xE8 and 0x14053FE71 + 5 + struct.unpack_from("<i", raw, off + 1)[0] == 0x140542CB0
        assert 0x14053F880 <= 0x14053FE71 < 0x14053F880 + 2759          # inside exec_ctl_s2_update


def test_assembles_with_the_new_wrapper():
    code, labels = ev._assemble(ev._asm_source(*ev.table({})), 0x14808F000)
    assert labels[0xE7001E] > 0x14808F000


def test_death_saber_row_and_label():
    m = json.loads(OVERLAY.read_text())["mods"]["D4_Class_2200"]
    assert m["behaviors"]["evilities"] == {"27836": {"family": "face_target_away"}}
    assert [r["id"] for r in m["skill_rows"]] == [27836]
    assert all(m["char_links"][str(c)]["evility1"] == 27836 and m["char_links"][str(c)]["evility_count"] == 1
               for c in range(14700, 14706))
    ev.table({27836: m["behaviors"]["evilities"]["27836"]})


def test_death_saber_label_is_exact_and_angle_is_d4s_own():
    # D4SIG9: the facing is D4 FUN_14022F350 computed in integers (proof: evility/offline_proof_maskwide1_face.py, 23 cases + controls)
    m = json.loads(OVERLAY.read_text())["mods"]["D4_Class_2200"]
    line = next(a for a in m["adaptations"] if a.startswith("evility Vanishing Cat (836)"))
    assert line.startswith("evility Vanishing Cat (836): exact rule") and "adapted" not in line.lower() and "Not carried" in line
    asm = Path(ev.ASM_FILE).read_text()
    body = asm[asm.index("\nwrap_face_away:"):asm.index("\nwrap_atkcount:")]
    assert "0x1402d8d60" not in body and "cmovs" in body and "call 0x14014f640" in body
