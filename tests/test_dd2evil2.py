"""DD2EVIL2: Pleinair (ally_move), Lilliel (move_heal_percent) and Alex (random_victims) are own rows on three second-word families."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev
from d5lib.importers import _dd2_innates
from dd2innate_text import POOL, pick

DATA = json.loads(Path(_dd2_innates.DATA).read_text())


def test_families_bits_and_value_rule():
    assert [ev.EXT_FAMILIES[n] for n in ("ally_move", "move_heal_percent", "random_victims")] == [5, 6, 7]
    assert [ev.ext_query(n) for n in ("ally_move", "move_heal_percent", "random_victims")] == [1 << 37, 1 << 38, 1 << 39]
    for fam in ("ally_move", "move_heal_percent", "random_victims"):
        assert fam in ev.EXT_VALUE_FAMILIES
        ev.table({24999: {"family": fam, "effects": [{"value": 1}]}})
        for bad in ({"family": fam}, {"family": fam, "effects": [{"value": 0}]}, {"family": fam, "effects": [{"value": 101}]},
                    {"family": fam, "effects": [{"value": 1, "stat": "atk"}]}, {"family": [fam, "regen"], "effects": [{"value": 1}]}):
            with pytest.raises(ValueError):
                ev.table({24999: bad})


def test_rows_labels_and_ids():
    ple, lil, alx = pick("DD2_Unique_320"), pick("DD2_Unique_420"), pick("DD2_Unique_480")
    assert ple["behavior"] == {"family": "ally_move", "effects": [{"value": 1}]} and ple["drop_alias"] and "alias" not in ple and ple["id"] == 24320
    assert lil["behavior"] == {"family": "move_heal_percent", "effects": [{"value": 2}]} and lil["id"] == 26305 and lil["row"]["owner"] == 10170
    assert alx["behavior"] == {"family": "random_victims", "effects": [{"value": 5}]} and alx["alias"] == 6112 and alx["id"] == 24480
    assert ple["relation"] == "exact" and "exact rule" in ple["label"] and "Not carried" in ple["label"]
    assert lil["relation"] == alx["relation"] == "adapted" and "adapted" in lil["label"] and "adapted" in alx["label"]
    assert "STEP" in lil["label"] and "END of the unit's own turn" in lil["label"] and "game_rng_draw(5)" in alx["label"]
    assert "DD2_Unique_420" not in DATA["needs_new_effect"]
    ev.table({r["id"]: r["behavior"] for r in (ple, lil, alx)})


def test_wrapper_registered_once_and_assembles():
    tag, target, sites = ev.wrapper("victims")
    assert (tag, target, sites) == (0xE70024, ev.PATH_APPEND, [0x1401E8F76])
    assert len({t for t, _, _ in ev.WRAPPERS}) == len(ev.WRAPPERS)
    rows = {24320: {"family": "ally_move", "effects": [{"value": 1}]}, 26305: {"family": "move_heal_percent", "effects": [{"value": 2}]},
            24480: {"family": "random_victims", "effects": [{"value": 5}]}}
    code, labels = ev._assemble(ev._asm_source(*ev.table(rows)), 0x14808F000)
    src = Path(ev.ASM_FILE).read_text()
    assert code and all(f"\n{n}:" in src for n in ("evil_team_sum", "evil_move_heal", "wrap_victims"))


def _pack(tmp_path, folder, char_id, rid, alias=None, stale="x"):
    pack = tmp_path / folder
    (pack / "patches/db").mkdir(parents=True)
    (pack / "patches/evilities").mkdir(parents=True)
    (pack / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": char_id, "evility1": 0, "evility2": 0, "evility3": 0,
                                                                          "evility4": 0, "evility_count": 0}]}))
    if alias:
        (pack / "patches/evilities/aliases.json").write_text(json.dumps({str(rid): alias}))
    (pack / "mod.json").write_text(json.dumps({"source_import": {"adaptations": [f"evility {stale} ({rid - 24000}): adapted - old"]}}))
    return pack


def test_apply_pleinair_drops_the_alias(tmp_path):
    pack = _pack(tmp_path, "DD2_Unique_320", 10480, 24320, alias=6024)
    assert "linked on 1 char row" in _dd2_innates.apply(pack, "DD2_Unique_320", text=POOL.get)
    assert not (pack / "patches/evilities/aliases.json").exists()
    assert json.loads((pack / "patches/evilities/evilities.json").read_text()) == {"evilities": {"24320": {"family": "ally_move", "effects": [{"value": 1}]}}}
    row = json.loads((pack / "patches/db/Skill.dat.json").read_text())["added"][0]
    assert row["id"] == 24320 and row["desc_EN"] == "Increase movement of ally units by 1." and row["owner"] == 10480
    assert _dd2_innates.gate(pack, "DD2_Unique_320")[0]


def test_apply_alex_keeps_the_alias_and_adds_the_row(tmp_path):
    pack = _pack(tmp_path, "DD2_Unique_480", 10560, 24480, alias=6112, stale="God of Destruction")
    _dd2_innates.apply(pack, "DD2_Unique_480", text=POOL.get)
    assert json.loads((pack / "patches/evilities/aliases.json").read_text()) == {"24480": 6112}   # the trigger is still D5's own event
    assert json.loads((pack / "patches/evilities/evilities.json").read_text())["evilities"]["24480"]["family"] == "random_victims"
    si = json.loads((pack / "mod.json").read_text())["source_import"]
    assert si["innate_evility"]["relation"] == "adapted" and len(si["adaptations"]) == 1 and "adapted - old" not in si["adaptations"][0]


def test_apply_lilliel_creates_the_row_and_links(tmp_path):
    pack = _pack(tmp_path, "DD2_Unique_420", 10170, 26305)
    assert "linked on 1 char row" in _dd2_innates.apply(pack, "DD2_Unique_420", text=POOL.get)
    assert json.loads((pack / "patches/db/char.dat.json").read_text())["added"][0]["evility1"] == 26305
    assert json.loads((pack / "patches/evilities/evilities.json").read_text())["evilities"]["26305"]["family"] == "move_heal_percent"
    assert not (pack / "patches/evilities/aliases.json").exists()
