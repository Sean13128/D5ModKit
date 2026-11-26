"""UNIQUESKILLS1: the reviewed D1C/D4 unique skill maps and the learn_count 0 gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from d5lib import importcore  # noqa: E402
from d5lib.importers import d1c  # noqa: E402

LABELS = {"exact", "adapted", "donor", "none"}
OLD = Path("/Volumes/Data/Projects/D5/Research/source-packs/d1c/batches/unique-skills.json")


def _mod(path, name, count):
    row = {"id": 1, "learn_count": count, "learn1_skill": 5 if count else 0}
    (path / name / "patches/db").mkdir(parents=True)
    (path / name / "patches/db/char.dat.json").write_text(json.dumps({"added": [row]}))
    return path / name


def test_every_d1c_unique_has_twins_or_says_none_in_source():
    for lid, e in d1c.skill_map().items():
        twins = [r for r in e["skills"] if r.get("d5_id")]
        assert twins or e.get("no_source_skills"), lid
        assert all(r["label"] in LABELS and r["reason"] for r in e["skills"]), lid
        assert len(d1c.unique_learn(lid)) == len({r["d5_id"] for r in twins}) <= 16


def test_donor_label_goes_with_donor_basis():
    for lid, e in d1c.skill_map().items():
        for r in e["skills"]:
            assert (r["label"] == "donor") == (r["basis"] == "donor"), (lid, r)


def test_basis_rules_are_recorded_and_consistent():
    seen = {}
    for lid, e in d1c.skill_map().items():
        ids = [r["d5_id"] for r in e["skills"] if r.get("d5_id")]
        assert len(ids) == len(set(ids)) or e.get("source", "").startswith("variant"), lid     # one twin per source special
        for r in e["skills"]:
            assert r["basis"] in {"name", "other-map", "mechanics", "donor", "none"}, (lid, r)
            if r["basis"] == "name":
                assert r["label"] == "exact"
            if r["basis"] == "mechanics" and r["d1_id"]:
                assert seen.setdefault((r["d1_id"], e["kind"]), r["d5_id"]) == r["d5_id"], (lid, r["d1_name"])   # same source skill, same twin


def test_same_name_source_skill_takes_the_same_named_d5_skill():
    # TEXTHASH-D1C-DD2: the map stores names as @text SHA-256 references; compare by digest, offline.
    from d5lib import textrefs
    sha = textrefs.sha
    kurtis = {r["d1_name"]["@text"]: r for r in d1c.skill_map()["2216"]["skills"]}
    beam = kurtis[sha("Pringer Beam")]
    assert beam["d5_name"]["@text"] == sha("Pringer Beam") and beam["basis"] == "name"
    assert kurtis[sha("Final Punch")]["d5_name"]["@text"] != sha("Pringer Beam")


def test_gate_fails_empty_unique_unless_source_has_none(tmp_path):
    assert not importcore.unique_skill_gate(_mod(tmp_path, "D1C_Unique_4", 0))[0]           # Gordon has skills
    assert importcore.unique_skill_gate(_mod(tmp_path, "D1C_Unique_2910", 0))[0]            # Weapon Shop: none in source
    assert importcore.unique_skill_gate(_mod(tmp_path, "D1C_Unique_5", 3))[0]
    assert not importcore.unique_skill_gate(_mod(tmp_path, "D4_Unique_230", 0))[0]
    assert importcore.unique_skill_gate(_mod(tmp_path, "D4_Unique_240", 0))[0]
    assert importcore.unique_skill_gate(_mod(tmp_path, "D1C_Class_11400", 0))[0]            # not a unique


def test_d4_donor_rows_exist_for_the_three_empty_uniques():
    doc = json.loads((ROOT / "d5lib/sourcemaps/d4.json").read_text())["uniques"]
    three = {k: doc[k] for k in ("240", "250", "610")}          # D4GAP1 added NPC entries beside them
    assert all(len(v["skills"]) == 4 and v["no_source_skills"] for v in three.values())
