"""DRPGSIG1: the second-word family enemy_heal_percent (Seraphina XENO) and the rows built with it."""
import json
import struct
from pathlib import Path

import pytest

from d5lib import evility as ev
from d5lib.importers import _drpg_text

OVERLAY = Path(__file__).resolve().parents[1] / "d5lib/importers/drpg-evility-overlay.json"
EXE = Path("/Volumes/Data/Projects/D5/D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")


def test_enemy_heal_row_encoding():
    rows, conds, fx = ev.table({1: {"family": "enemy_heal_percent", "effects": [{"value": 35}]}})
    evid, mask, cond_off, n_cond, fx_off, n_fx, flags, filt = rows[0]
    assert (evid, mask, n_cond, n_fx) == (1, 0, 0, 1) and flags == 2 << 8 and ev.ext_query("enemy_heal_percent") == 2 << 32
    assert fx == [(0, 35)]


@pytest.mark.parametrize("bad", [
    {"family": "enemy_heal_percent"},                                                        # needs its number
    {"family": "enemy_heal_percent", "effects": []},
    {"family": "enemy_heal_percent", "effects": [{"value": 0}]},
    {"family": "enemy_heal_percent", "effects": [{"value": 101}]},
    {"family": "enemy_heal_percent", "effects": [{"value": 35}, {"value": 5}]},
    {"family": "enemy_heal_percent", "effects": [{"value": 35, "stat": "atk"}]},
    {"family": ["enemy_heal_percent", "face_target_away"], "effects": [{"value": 35}]},
    {"family": ["enemy_heal_percent", "dealt"], "effects": [{"value": 35}]},
    {"family": "face_target_away", "effects": [{"value": 35}]},                              # still a pure predicate
])
def test_enemy_heal_row_rules(bad):
    with pytest.raises(ValueError):
        ev.table({1: bad})


def test_wrapper_and_site():
    tag, target, sites = ev.wrapper("healmod")
    assert (tag, target, sites) == (0xE7001F, ev.HEAL_MOD, [0x1401BF503]) and ev.HEAL_MOD == 0x1401FFF40
    assert len(ev.TAGS) == len(ev.WRAPPERS) and len(set(ev.TAGS)) == len(ev.TAGS)
    if EXE.exists():
        raw = EXE.read_bytes()
        off = ev._offset(raw, 0x1401BF503)
        assert raw[off] == 0xE8 and 0x1401BF503 + 5 + struct.unpack_from("<i", raw, off + 1)[0] == 0x1401FFF40
        assert 0x1401BF3C0 <= 0x1401BF503 < 0x1401BF3C0 + 1058            # inside damage_heal_compute_heal
    code, labels = ev._assemble(ev._asm_source(*ev.table({})), 0x14808F000)
    assert labels[0xE7001F] > 0x14808F000


def test_seraphina_row_in_overlay():
    d = _drpg_text.load(OVERLAY)
    main = next(e for e in d["bases"]["164"]["evilities"] if e["slot"] == "main")
    assert main["id"] == 28176 and main["rows"] == [{"family": "enemy_heal_percent", "effects": [{"value": 35}]}]
    assert main["label"].startswith("source: Disgaea RPG JP leaderskill 1641; adapted:")
    ev.table({main["id"]: main["rows"]})


def test_map_hp_condition_encoding():
    row = {"family": "dealt", "effects": [{"value": 30}], "conditions": [{"kind": "map_hp_at_or_below", "count": 1, "of": 2, "id": 50}]}
    rows, conds, fx = ev.table({1: row})
    assert conds[0] == (71, 1, 2, 50) and ev.COND_KINDS["map_hp_at_or_below"] == 71


@pytest.mark.parametrize("cond", [
    {"kind": "map_hp_at_or_below", "count": 0, "of": 2, "id": 50},
    {"kind": "map_hp_at_or_below", "count": 1, "of": 3, "id": 50},
    {"kind": "map_hp_at_or_below", "count": 1, "of": 2, "id": 0},
    {"kind": "map_hp_at_or_below", "count": 1, "of": 2, "id": 101},
    {"kind": "map_hp_at_or_below", "count": 1, "of": 2},
])
def test_map_hp_condition_rules(cond):
    with pytest.raises(ValueError):
        ev.table({1: {"family": "dealt", "effects": [{"value": 30}], "conditions": [cond]}})


def test_satina_row_in_overlay():
    d = _drpg_text.load(OVERLAY)
    main = next(e for e in d["bases"]["273"]["evilities"] if e["slot"] == "main")
    assert main["id"] == 28256 and main["needs"] == ["D1", "D2"]
    assert main["label"].startswith("source: Disgaea RPG JP leaderskill 2731; adapted:") and "checked live" in main["label"]
    assert [r["family"] for r in main["rows"]] == ["dealt", ["dealt", "aura"]]
    conds = main["rows"][1]["conditions"]
    assert [c["kind"] for c in conds] == ["near_has", "map_hp_at_or_below"]          # the cheap provider test first
    ev.table({main["id"]: main["rows"]})
