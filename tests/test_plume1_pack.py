"""Plume's innate allocation, source values, and repeatable table-only overlay."""
import json
from d5lib.importers import _dd2_innates as innate
from dd2innate_text import POOL, pick
from d5lib import learned


def test_plume_innate_overlay_and_approximation(tmp_path):
    row_doc = pick("DD2_Unique_570")
    rid = row_doc["id"]
    assert rid == 26304 and 26200 <= rid <= 26999 and rid != 9999
    row = row_doc["row"]
    assert (row["kind"], row["mana_cost"], row["slot_cost"], row["owner"]) == (1, 0, 0, 10520)
    assert (row["value1"], row["value2"]) == (10, 200)
    # DD2EVIL3: the rule is the holder's own defeat count (kill_counter + scale holder_kills), no longer D5's six team counters
    assert "defeat the holder has made" in row["desc_EN"]
    assert row_doc["relation"] == "adapted" and "OWN count of defeats" in row_doc["label"] and "0xE9170" in row_doc["label"]
    assert row_doc["behavior"] == [{"family": ["power", "aura"],
        "effects": [{"value": 10, "per": "holder_kills", "max": 200}], "filter": rid,
        "conditions": [{"kind": "near_has", "of": 1, "radius": 65535, "id": rid}]},
        {"family": "kill_counter"}]
    (tmp_path / "patches/db").mkdir(parents=True)
    (tmp_path / "mod.json").write_text('{}')
    (tmp_path / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 10520, "evility1": 24450}]}))
    innate.apply(tmp_path, "DD2_Unique_570", text=POOL.get)
    assert innate.gate(tmp_path, "DD2_Unique_570")[0]
    first = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    innate.apply(tmp_path, "DD2_Unique_570", text=POOL.get)
    assert first == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    meta = json.loads((tmp_path / "mod.json").read_text())["source_import"]
    assert meta["innate_evility"]["relation"] == "adapted"
    assert row_doc["label"] in meta["adaptations"]
    links = json.loads((tmp_path / "patches/db/char.dat.json").read_text())["added"][0]
    assert (links["evility1"], links["evility2"], links["evility_count"]) == (rid, 24450, 2)
    installed = [{"id": 26182, "kind": 0}, {"id": 28000, "kind": 1}]
    assert learned.moved(installed, installed + [row]) == []
