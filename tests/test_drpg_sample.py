"""The DRPG sample's leases and evility rows, checked without the game.

These are the parts of the sample that can be wrong without any art: ids that leave the manifest's kit bands,
two characters taking the same row, or an evility row the Kit's `.d5el` writer cannot express.
"""
import importlib.util
import os
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from d5lib import evility, ownership  # noqa: E402


def _specs():
    path = os.path.join(ROOT, "tools", "build_drpg_sample.py")
    found = importlib.util.spec_from_file_location("build_drpg_sample", path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    # the module only defines data and functions at import time; main() is not called
    found.loader.exec_module(module)
    return module


def test_allocated_rows_are_unique_in_band_and_three_apart():
    m = _specs()
    # the shape a build gets: rows come out of the kit's free pool, inside the manifest's kit band
    rows = m.take_rows([i for i in range(200, 420)], len(m.SPECS))
    assert len(set(rows)) == len(m.SPECS)
    assert all(m.ROW_BAND[0] <= r <= m.ROW_BAND[1] for r in rows), rows
    assert all(abs(a - b) >= 3 for i, a in enumerate(rows) for b in rows[i + 1:]), rows
    try:
        m.take_rows([999], 1)
    except RuntimeError as exc:
        assert "free rows" in str(exc)
    else:
        raise AssertionError("an id outside the band must not be allocated")


def test_leased_ids_are_unique_and_in_kit_bands():
    m = _specs()
    rows = m.take_rows([i for i in range(223, 404)], len(m.SPECS))
    # sprite blocks are leased at build time; the test only needs them distinct and in-band
    sprites = [223 + 10 * i for i in range(len(m.SPECS))]
    assert len(set(rows)) == len(rows) and len(set(sprites)) == len(sprites)
    evilities = [e for s in m.SPECS for e in s["evilities"]]
    assert len(set(evilities)) == len(evilities)

    manifest = ownership.load()
    claims = []
    for s, row, sprite in zip(m.SPECS, rows, sprites):
        claims += m.claims_for(dict(s, row=row, sprite=sprite))
    findings = ownership.check_claims(manifest, claims)
    errors = [f.as_dict() for f in ownership.errors(findings)]
    assert errors == [], errors



def test_evility_rows_are_expressible():
    m = _specs()
    for s in m.SPECS:
        rows = {str(k): {kk: vv for kk, vv in v.items() if kk != "note"} for k, v in s["evilities"].items()}
        table_rows, conditions, effects = evility.table(rows)
        assert len(table_rows) == len(rows)          # the writer accepts every row unchanged
        assert len(effects) >= len(rows)


def test_every_character_has_a_leader_skill_and_skills():
    m = _specs()
    for s in m.SPECS:
        assert s["evilities"], s["name"]
        assert s["skills"] and len(s["skills"]) <= 16
        assert all(sid > 0 and 1 <= lv <= 99 for sid, lv in s["skills"])
        assert s["leader"].strip()
