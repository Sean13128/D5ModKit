"""D4SIG7: scale geo_colours (Psylos, Geo Energy 129) and the rows built with it."""
import json
from pathlib import Path

from d5lib import evility as ev

from d4rules import overlay_path as _overlay_path
OVERLAY = _overlay_path()
MODS = json.loads(OVERLAY.read_text())["mods"]
SIX = ("atk", "def", "int", "res", "hit", "spd")


def test_geo_colours_scale_encodes():
    assert ev.SCALES["geo_colours"] == 27
    _r, _c, fx = ev.table({27129: {"family": "stats", "effects": [{"stat": "atk", "value": 10, "per": "geo_colours"}]}})
    assert fx == [(2 | 27 << 16, 10)]


def test_psylos_row_pack_and_label():
    st = MODS["D4_Unique_5388"]
    assert st["behaviors"]["evilities"]["27129"] == {
        "family": "stats", "effects": [{"stat": s, "value": 10, "per": "geo_colours"} for s in SIX]}
    row = st["skill_rows"][0]
    assert row["id"] == 27129 and row["owner"] == 18290 and row["kind"] == 1 and row["value1"] == 10
    assert st["char_links"]["18290"]["evility1"] == 27129 and st["char_links"]["18290"]["evility_count"] == 1
    line = next(a for a in st["adaptations"] if a.startswith("evility Geo Energy (129)"))
    assert "exact rule" in line and "Not carried" in line and "adapted" not in line.lower()


def test_attack_counter_family_and_wrapper():
    assert ev.EXT_FAMILIES["attack_counter"] == 2 and ev.ext_query("attack_counter") == 4 << 32
    rows, conds, fx = ev.table({27663: {"family": "attack_counter"}})
    evid, mask, cond_off, n_cond, fx_off, n_fx, flags, filt = rows[0]
    assert (evid, mask, n_cond, n_fx) == (27663, 0, 0, 0) and flags == 4 << 8
    tag, target, sites = ev.wrapper("atkcount")
    assert (tag, target, sites) == (0xE70020, ev.APPLY_DAMAGE, [0x1401B1BE0]) and ev.APPLY_DAMAGE == 0x1401B1FD0
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)
    code, labels = ev._assemble(ev._asm_source(*ev.table({})), 0x14808F000)
    assert labels[0xE70020] > 0x14808F000


def test_attack_counter_rules():
    import pytest
    for bad in ({"family": "attack_counter", "effects": [{"value": 1}]},
                {"family": ["attack_counter", "face_target_away"]},
                {"family": ["attack_counter", "dealt"], "effects": [{"value": 5}]}):
        with pytest.raises(ValueError):
            ev.table({1: bad})


def test_rising_dragon_row_and_label():
    st = MODS["D4_Class_2170"]
    assert st["behaviors"]["evilities"]["27663"] == {"family": "attack_counter"}
    assert st["class_alias"]["27663"] == 2065                       # the alias still does the reading
    assert len(st["adaptations"]) == 1
    line = st["adaptations"][0]
    assert line.startswith("evility Rising Dragon (663): exact rule") and "Not carried" in line and "adapted" not in line.split("Not carried")[0].lower()
