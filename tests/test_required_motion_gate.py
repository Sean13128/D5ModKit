"""SHARKBANK1: importcore.required_motion_gate fails a bank that lacks a motion all clean-game banks of its body kind
hold (built in code, no game data).  The lists come from d5lib/data/required_motions.json."""
import json

from d5lib import anm, importcore, requiredmotions
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from test_idle_drawable_gate import _bank

DOC = {"required": {"monster": [0, 1001, 1007, 2071, 2077], "humanoid": [0, 6001, 6007]}}


def _mod(tmp_path, bank, sprite=2640, body_type=1):
    mod = tmp_path / "DD2_Class_Test"
    (mod / "patches/db").mkdir(parents=True)
    (mod / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 22680, "sprite_id": sprite, "body_type": body_type}]}))
    d = mod / "files/Anime/ANM_HI_JP.dat"
    d.mkdir(parents=True)
    (d / f"anm{sprite:05d}.lzs").write_bytes(bank.to_bytes())
    return mod


def test_complete_monster_bank_passes(tmp_path):
    mod = _mod(tmp_path, _bank(2640, [0, 1001, 1007, 2071, 2077]))
    assert importcore.required_motion_gate(mod, DOC) == (True, "")


def test_missing_attack_motion_fails(tmp_path):
    ok, why = importcore.required_motion_gate(_mod(tmp_path, _bank(2640, [0, 1001, 1007, 2071])), DOC)
    assert not ok and "2077" in why and "monster" in why


def test_humanoid_list_is_separate(tmp_path):
    ok_mod = _mod(tmp_path / "ok", _bank(1550, [0, 6001, 6007]), 1550, 0)
    assert importcore.required_motion_gate(ok_mod, DOC) == (True, "")
    bad_mod = _mod(tmp_path / "bad", _bank(1550, [0, 6001]), 1550, 0)
    ok, why = importcore.required_motion_gate(bad_mod, DOC)
    assert not ok and "6007" in why and "humanoid" in why


def test_unshipped_bank_is_not_checked(tmp_path):
    mod = _mod(tmp_path, _bank(2641, [0]), sprite=2641)         # row names 2641 and its bank is on disk: checked
    mod2 = tmp_path / "other"
    (mod2 / "patches/db").mkdir(parents=True)
    (mod2 / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 1, "sprite_id": 2640, "body_type": 1}]}))
    assert importcore.required_motion_gate(mod2, DOC) == (True, "")
    assert importcore.required_motion_gate(mod, DOC)[0] is False


def test_shipped_list_is_the_clean_game_list():
    doc = requiredmotions.load()
    assert {2071, 2077, 1001, 1007} <= set(doc["required"]["monster"])
    assert doc["required"]["humanoid"] == [0, 6001, 6007]
    assert requiredmotions.missing([0, 1001], 1, doc)               # a bank with two ids lacks most of the list
