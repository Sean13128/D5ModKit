"""DD2EVIL3: Plume's kill_counter family and the holder_kills scale (the runtime is proven by evility/offline_proof_dd2evil3.py)."""
import json
import pytest
from d5lib import evility as ev
from d5lib.importers import _dd2_innates as innate
from dd2innate_text import pick

ROW = [{"family": ["power", "aura"], "effects": [{"value": 10, "per": "holder_kills", "max": 200}], "filter": 26304,
        "conditions": [{"kind": "near_has", "of": 1, "radius": 65535, "id": 26304}]}, {"family": "kill_counter"}]


def test_family_scale_and_row_encoding():
    assert ev.EXT_FAMILIES["kill_counter"] == 8 and ev.ext_query("kill_counter") == 1 << 40
    assert ev.SCALES["holder_kills"] == 28 and ev.FILTER_SCALES[28] == "holder_kills"
    rows, conds, fx = ev.table({26304: ROW})
    assert [r[0] for r in rows] == [26304, 26304]
    assert rows[0][1] == ev.F_POWER | ev.F_AURA and rows[0][7] == 26304          # the filter word names the holder's own id
    assert rows[1][1] == 0 and rows[1][6] == 1 << (ev.EXT_SHIFT + 8)           # the predicate row: second-word bit 8
    assert fx == [(0x1000000 | 28 << 16, 200 << 16 | 10)]


def test_row_rules():
    for bad in ([ROW[0], {"family": "kill_counter", "effects": [{"value": 1}]}],
                [ROW[0], {"family": ["kill_counter", "face_target_away"]}],
                [{k: v for k, v in ROW[0].items() if k != "filter"}]):         # holder_kills names its holder: filter is required
        with pytest.raises(ValueError):
            ev.table({26304: bad})


def test_pack_row_is_the_proven_row_and_stays_adapted():
    pick_row = pick("DD2_Unique_570")
    assert pick_row["behavior"] == ROW and pick_row["relation"] == "adapted"
    assert "Not proved equal to DD2" in pick_row["label"]
