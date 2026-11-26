"""LONGTAIL2: Xenolith (max_hp_reflect, alias to Malicious Reflect 143), Baal Slave and the data rows of the three adaptations."""
import json
from pathlib import Path

import pytest

from d5lib import evility as ev
from d5lib.importers import _dd2_innates
from dd2innate_text import POOL, pick

DATA = json.loads(Path(_dd2_innates.DATA).read_text())


def test_max_hp_reflect_family_and_value_rule():
    assert ev.EXT_FAMILIES["max_hp_reflect"] == 9 and ev.ext_query("max_hp_reflect") == 1 << 41
    assert "max_hp_reflect" in ev.EXT_VALUE_FAMILIES
    ev.table({26306: {"family": "max_hp_reflect", "effects": [{"value": 20}]}})
    for bad in ({"family": "max_hp_reflect"}, {"family": "max_hp_reflect", "effects": [{"value": 0}]},
                {"family": "max_hp_reflect", "effects": [{"value": 101}]},
                {"family": "max_hp_reflect", "effects": [{"value": 20, "stat": "atk"}]},
                {"family": ["max_hp_reflect", "regen"], "effects": [{"value": 20}]}):
        with pytest.raises(ValueError):
            ev.table({26306: bad})


def test_xenolith_row_label_and_wrapper():
    x = pick("DD2_Unique_941")
    assert x["id"] == 26306 and x["alias"] == 143 and x["relation"] == "adapted" and x["row"]["owner"] == 941
    assert x["behavior"] == {"family": "max_hp_reflect", "effects": [{"value": 20}]}
    for need in ("community evility list", "ATTACKER's max HP", "NOT FOUND", "not source code", "adapted", "Not carried", "never kills"):
        assert need in x["label"], need
    assert "DD2_Unique_941" not in DATA["needs_new_effect"]
    ev.table({x["id"]: x["behavior"]})
    tag, target, sites = ev.wrapper("max_reflect")
    assert (tag, target, sites) == (0xE70025, ev.DAMAGE_SKILL_DAT, [0x1401AE531])
    code, labels = ev._assemble(ev._asm_source(*ev.table({x["id"]: x["behavior"]})), 0x14808F000)
    assert code and "\nwrap_maxrefl:" in Path(ev.ASM_FILE).read_text()


def _pack(tmp_path, folder, char_id):
    pack = tmp_path / folder
    (pack / "patches/db").mkdir(parents=True)
    (pack / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": char_id, "evility1": 0, "evility2": 0, "evility3": 0,
                                                                          "evility4": 0, "evility_count": 0}]}))
    (pack / "mod.json").write_text(json.dumps({"source_import": {"adaptations": []}}))
    return pack


def test_apply_xenolith_alias_row_and_link(tmp_path):
    pack = _pack(tmp_path, "DD2_Unique_941", 941)
    assert "linked on 1 char row" in _dd2_innates.apply(pack, "DD2_Unique_941", text=POOL.get)
    assert json.loads((pack / "patches/evilities/aliases.json").read_text()) == {"26306": 143}
    assert json.loads((pack / "patches/evilities/evilities.json").read_text())["evilities"]["26306"]["family"] == "max_hp_reflect"
    assert json.loads((pack / "patches/db/char.dat.json").read_text())["added"][0]["evility1"] == 26306
    row = json.loads((pack / "patches/db/Skill.dat.json").read_text())["added"][0]
    assert row["id"] == 26306 and "20" in row["desc_EN"] and row["owner"] == 941
    si = json.loads((pack / "mod.json").read_text())["source_import"]
    assert si["innate_evility"]["relation"] == "adapted" and len(si["adaptations"]) == 1
    assert _dd2_innates.gate(pack, "DD2_Unique_941")[0]


def test_piyori_main_evility_is_built_from_the_two_leaderskill_rows():
    from d5lib.importers import drpg_evilities
    own = drpg_evilities.enabled(400)
    main = own[0]
    assert main["slot"] == "main" and main["id"] == 28400 and main["rpg_ids"] == [4001, 4005] and main["needs"] == ["D1", "L1"]
    rows = main["rows"]
    win = [{"kind": "turn_max", "id": 3}]
    assert {"family": "counter", "conditions": win} in rows
    assert {"family": "taken", "effects": [{"value": -50}], "conditions": win} in rows
    assert {"family": "stats", "effects": [{"stat": "hp", "value": 20}, {"stat": "atk", "value": 20}]} in rows
    ev.table({main["id"]: rows})
    for need in ("340%", "intercept-versus-intercept", "FUN_140523970", "not live-measured", "adapted"):
        assert need in main["label"], need
    assert "Take 50％ less damage and may counter attack for the first 3 rounds" in main["skill_row"]["desc_EN"]
    assert main["name_en"] == "Rainbow Stained by Darkness"


def test_nullify_dealt_family_is_a_predicate_row():
    assert ev.EXT_FAMILIES["nullify_dealt"] == 10 and ev.ext_query("nullify_dealt") == 1 << 42
    assert "nullify_dealt" not in ev.EXT_VALUE_FAMILIES
    ev.table({26307: {"family": "nullify_dealt"}})
    ev.table({26307: {"family": "nullify_dealt", "conditions": [{"kind": "hp_below", "id": 50}]}})
    for bad in ({"family": "nullify_dealt", "effects": [{"value": 1}]}, {"family": ["nullify_dealt", "regen"]}):
        with pytest.raises(ValueError):
            ev.table({26307: bad})
    code, _ = ev._assemble(ev._asm_source(*ev.table({26307: {"family": "nullify_dealt"}})), 0x14808F000)
    assert code and "0x40000000000" in Path(ev.ASM_FILE).read_text()


def test_baal_slave_row_label_and_link(tmp_path):
    b = pick("DD2_Unique_640")
    assert b["id"] == 26307 and b["alias"] == 2072 and b["relation"] == "adapted" and b["row"]["owner"] == 10580
    assert b["behavior"] == {"family": "nullify_dealt"}
    for need in ("SELECTED", "animation plays", "only the damage is removed", "Softening Aura", "heals and buffs", "adapted", "not opened"):
        assert need in b["label"], need
    assert "DD2_Unique_640" not in DATA["needs_new_effect"]
    pack = _pack(tmp_path, "DD2_Unique_640", 10580)
    _dd2_innates.apply(pack, "DD2_Unique_640", text=POOL.get)
    assert json.loads((pack / "patches/evilities/aliases.json").read_text()) == {"26307": 2072}
    assert json.loads((pack / "patches/evilities/evilities.json").read_text())["evilities"]["26307"] == {"family": "nullify_dealt"}
    assert json.loads((pack / "patches/db/char.dat.json").read_text())["added"][0]["evility1"] == 26307
    assert _dd2_innates.gate(pack, "DD2_Unique_640")[0]
