"""DD2D1GAP1: DD2 packs get an exact/adapted label for the D5 equivalent they already link (link only)."""
import json
from pathlib import Path

from d5lib.importers import _dd2_innates
from dd2innate_text import POOL, pick

DATA = json.loads(Path(_dd2_innates.DATA).read_text())["packs"]
# DD2EVIL1: Masked Hero 25210 and Pringer Z 24300 became own exact rows (tests/test_dd2evil1.py); DD2EVIL2: Alex 24480, Pleinair 24320 and
# Lilliel 24420 became own rows (tests/test_dd2evil2.py); only Shark Dragon stays link only
FIVE = {"DD2_Class_22680": ("exact", 26180)}


def test_data_is_link_only():
    for folder, (rel, rid) in FIVE.items():
        p = pick(folder)
        assert (p["relation"], p["id"], p["link"]) == (rel, rid, rid)
        assert "row" not in p and "behavior" not in p and p["label"]


def test_apply_touches_only_mod_json_and_keeps_the_link(tmp_path):
    pack = tmp_path / "DD2_Class_22680"
    (pack / "patches/db").mkdir(parents=True)
    rows = {"added": [{"id": 22680, "evility1": 26180, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}]}
    (pack / "patches/db/char.dat.json").write_text(json.dumps(rows))
    assert _dd2_innates.apply(pack, "DD2_Class_22680", text=POOL.get) is None         # the row is not in the pack: nothing is linked
    (pack / "patches/db/Skill.dat.json").write_text(json.dumps({"added": [{"id": 26180}]}))
    (pack / "mod.json").write_text(json.dumps({"source_import": {"adaptations": []}}))
    before = (pack / "patches/db/char.dat.json").read_text()
    assert "linked on 1 char row" in _dd2_innates.apply(pack, "DD2_Class_22680", text=POOL.get)
    assert json.loads((pack / "patches/db/char.dat.json").read_text()) == json.loads(before)
    assert not (pack / "patches/evilities").exists()
    si = json.loads((pack / "mod.json").read_text())["source_import"]
    assert si["innate_evility"]["relation"] == "exact" and "no number in either" in si["adaptations"][0]
    assert _dd2_innates.gate(pack, "DD2_Class_22680") == (True, "innate 26180 linked on 1 row(s)")
