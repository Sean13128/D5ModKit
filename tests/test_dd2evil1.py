"""DD2EVIL1: Pringer Z (Heavy Stance 300) and Masked Hero (Rapid Movement 1210) are own exact rows, not aliases."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev
from d5lib.importers import _dd2_innates
from dd2innate_text import POOL, pick

DATA = json.loads(Path(_dd2_innates.DATA).read_text())["packs"]


def test_rows_are_own_and_validate():
    heavy, rapid = pick("DD2_Unique_300"), pick("DD2_Class_22210")
    assert heavy["behavior"] == {"family": "flight"} and heavy["drop_alias"] and "alias" not in heavy
    assert heavy["row"]["effect_group"] == 0 and heavy["id"] == 24300 and heavy["relation"] == "exact"
    assert "exact rule" in heavy["label"] and "stats +30%" in heavy["label"]
    assert rapid["behavior"]["effects"] == [{"value": 2, "per": "movement_cost", "max": 64, "mode": "after"}]
    assert rapid["row"]["effect_group"] == 0 and rapid["id"] == 25210 and rapid["relation"] == "exact"
    assert "exact rule" in rapid["label"]
    rows, _c, fx = ev.table({24300: heavy["behavior"], 25210: rapid["behavior"]})
    assert {r[1] for r in rows} == {ev.F_FLIGHT, ev.F_EVASION}
    word, value = fx[0]
    assert word & 0x300 == 0x200 and (word >> 16) & 0xFF == ev.SCALES["movement_cost"] and word & ev.FX_MAX and value == 2 | 64 << 16


def test_evasion_after_mode_errors():
    for bad in ({"value": 2, "mode": "later"}, {"value": -2, "mode": "after"}, {"value": 2, "stat": "atk"}):
        with pytest.raises(ValueError):
            ev.table({1: {"family": "evasion", "effects": [bad]}})


def test_apply_replaces_the_alias_and_the_stale_line(tmp_path):
    pack = tmp_path / "DD2_Unique_300"
    (pack / "patches/db").mkdir(parents=True)
    (pack / "patches/evilities").mkdir(parents=True)
    (pack / "patches/evilities/aliases.json").write_text(json.dumps({"24300": 1224}))
    (pack / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 10570, "evility1": 24300, "evility2": 0, "evility3": 0,
                                                                          "evility4": 0, "evility_count": 1}]}))
    (pack / "patches/db/Skill.dat.json").write_text(json.dumps({"added": [{"id": 24300, "effect_group": 11, "value1": 30}]}))
    (pack / "mod.json").write_text(json.dumps({"source_import": {"adaptations": ["evility Heavy Stance (300): adapted - old", "other line"]}}))
    assert "linked on 1 char row" in _dd2_innates.apply(pack, "DD2_Unique_300", text=POOL.get)
    assert not (pack / "patches/evilities/aliases.json").exists()
    assert json.loads((pack / "patches/evilities/evilities.json").read_text()) == {"evilities": {"24300": {"family": "flight"}}}
    row = json.loads((pack / "patches/db/Skill.dat.json").read_text())["added"][0]
    assert (row["effect_group"], row["value1"]) == (0, 0)
    lines = json.loads((pack / "mod.json").read_text())["source_import"]["adaptations"]
    assert len(lines) == 2 and "other line" in lines and any("exact rule" in a for a in lines) and not any("adapted - old" in a for a in lines)
    assert _dd2_innates.gate(pack, "DD2_Unique_300")[0]
