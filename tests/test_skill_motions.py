"""UNIQUESKILLS1: skill caster motions vs the unit's battle bank (needs the clean D5 copy in Disgaea Source)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from d5lib import importcore, skillmotions  # noqa: E402

pytestmark = pytest.mark.skipif(not skillmotions.CLEAN_GAME.is_dir(), reason="clean D5 copy not present")


def _mod(tmp, row):
    (tmp / "patches/db").mkdir(parents=True)
    (tmp / "patches/db/char.dat.json").write_text(json.dumps({"added": [row]}))
    return tmp


def test_motion_to_animation_ids():
    assert skillmotions.anims_of(100) == (1001, 1007)
    assert skillmotions.anims_of(109) == (1051, 1057) and skillmotions.anims_of(151) == (7011, 7017)


@pytest.fixture(scope="module")
def sv():
    return skillmotions.Survey()


def test_vanilla_humanoid_heal_is_ok_and_no_bank_is_unknown(tmp_path, sv):
    row = {"id": 1, "sprite_id": 1010, "body_type": 0, "learn_count": 1, "learn1_skill": 1401}
    assert sv.check_mod(_mod(tmp_path / "a", row))[0]["status"] == "ok"
    row = dict(row, sprite_id=4999)
    assert sv.check_mod(_mod(tmp_path / "b", row))[0]["status"] == "unknown"


def test_gate_fails_a_motion_vanilla_never_runs_absent(tmp_path, sv):
    # a monster body whose bank lacks the animation of a motion no vanilla monster runs absent
    prec = sv.precedent()
    sv._precedent = set()                       # nothing is precedented: any absent animation is a hard miss
    try:
        row = {"id": 1, "sprite_id": 2020, "body_type": 1, "learn_count": 1, "learn1_skill": 12021}
        recs = sv.check_mod(_mod(tmp_path / "c", row))
        ids = sv.bank_ids("/x", 2021)
        absent = any(a not in ids for m in (sv.caster(12021) or []) if m for a in skillmotions.anims_of(m))
        assert (recs[0]["status"] == "missing") == absent
        ok, why = importcore.skill_motion_gate(tmp_path / "c", sv)
        assert ok != absent
    finally:
        sv._precedent = prec
