"""D4-PAL1 / D4-KG1 / D4-TRACKS1 (D4TYPES review F1, F2, F3, F7, F9). Reads the original D4 copy and
the D4CELL1 build when present (skipped otherwise); no game bytes are written anywhere."""
from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from d5lib import anm, d4unique, gamefs
from d5lib.importers import d4 as d4imp
from tests.test_d4unique import fixture

CELL1 = Path("/Volumes/Data/Projects/D5/Builds/D4CELL1-20261109/d4/mods")
ANIME = "files/Anime/ANM_HI_JP.dat"


@pytest.fixture(scope="module")
def data():
    from d4rules import data_or_skip
    return data_or_skip()


def test_rotate_banks_moves_the_wanted_bank_first_and_keeps_the_rest():
    assert d4unique.rotate_banks("abcdef", 4) == list("eabcdf")
    assert d4unique.rotate_banks("abc", 0) == list("abc")


def test_d4_bank_is_the_packet_rule(data):
    # prepare_cast_art.py: color_id % 10 when the body has that bank (430: 54 on 4 banks -> 0)
    assert [d4unique.d4_bank(data, s) for s in (180, 220, 230, 430, 10)] == [4, 4, 8, 0, 0]


def _bank(mod, number):
    return anm.parse(gamefs.decode_member((mod / ANIME / f"anm{number:05d}.lzs").read_bytes()))


@pytest.mark.parametrize("sid,number", [(180, 928), (220, 464)])
def test_slot0_gate_fails_on_d4cell1_and_passes_after_rotation(data, tmp_path, sid, number):
    held = CELL1 / f"D4_Unique_{sid}"
    if not held.is_dir():
        pytest.skip("D4CELL1 build not present")
    banks = data.body_palettes(data.chars[sid]["sprite"])
    ok, why = d4unique.slot0_gate(_bank(held, number), banks, 4)
    assert not ok and "nearest D4 bank 0" in why          # the defect: slot 0 = base bank 0
    mod = tmp_path / held.name
    shutil.copytree(held / ANIME, mod / ANIME)
    entry = SimpleNamespace(mod_folder=held.name, kind="unique", source_ref={"row": sid})
    ok, why = d4imp.Importer()._palette_slot0(entry, mod, sid, d4imp.D4_SOURCE)
    assert ok and "rotated D4 bank 4" in why
    for n in (number, number + 1):
        doc = _bank(mod, n)
        pals = [anm.get_palette(doc, k) for k in range(len(doc.palettes))]
        assert len(pals) == len(banks)                    # bank count kept
        assert all(np.array_equal(p, b) for p, b in zip(pals, d4unique.rotate_banks(banks, 4)))
    # idempotent: a second pass finds slot 0 right and changes nothing
    before = (mod / ANIME / f"anm{number:05d}.lzs").read_bytes()
    assert d4imp.Importer()._palette_slot0(entry, mod, sid, d4imp.D4_SOURCE)[0]
    assert (mod / ANIME / f"anm{number:05d}.lzs").read_bytes() == before


def test_a_generic_kind_gender_on_a_unique_keeps_the_gender_digit():
    src, tables = fixture()
    profile = dict(src, id=230, battle=dict(src["battle"], body_type=1, kind_gender=21),
                   innate_evility={"id": 999, "name": "Pending"}, evilities=[], skills=[])
    mapping = dict(evilities={"999": dict(relation="placeholder")}, skills={})
    tables["char.dat"].rows[1].set("body_type", 1)
    row, _, audit = d4unique.plan_import(profile, tables, mapping, target_id=216, template_id=570,
                                         supported_ids=[216])
    assert row["kind_gender"] == 1
    assert audit["kind_gender"]["source"] == 21 and audit["kind_gender"]["written"] == 1
    profile["battle"]["kind_gender"] = 2                     # a normal unique code is untouched
    row, _, audit = d4unique.plan_import(profile, tables, mapping, target_id=216, template_id=570,
                                         supported_ids=[216])
    assert row["kind_gender"] == 2 and "kind_gender" not in audit


def test_census_marks_story_forms_not_candidates(data):
    from d4rules import files as _rule_files
    census = {r["id"]: r for r in d4imp.Importer().unique_census(_rule_files().root)}
    for cid in (930, 940, 950, 960, 970, 980):
        assert census[cid]["story_form"] and census[cid]["why_not"].startswith("story-form")
        assert "candidate" not in census[cid]["why_not"]
    # D4-NPC1 leased 990 as a character on an owner's art: still a story form, no longer left out
    assert census[990]["story_form"] and census[990]["in_scope"] and not census[990]["why_not"]
    for cid in (180, 220, 270, 520):                         # palette swaps and real candidates
        assert not census[cid]["story_form"]
    assert "candidate" in census[270]["why_not"]


def test_class_path_refuses_a_donor_kind_that_differs_from_the_source_body(data, tmp_path, monkeypatch):
    from d4rules import files as _rule_files
    imp = d4imp.Importer()
    monkeypatch.setattr(imp, "_spec", lambda entry: dict(kind="humanoid", template=1010))
    entry = SimpleNamespace(id="d4:2040", mod_folder="D4_Class_2040", kind="class", source_ref={"row": 2040})
    monkeypatch.setattr(d4imp, "_run", lambda *a, **k: pytest.fail("builder must not run"))
    monkeypatch.setattr(imp, "pool", lambda files, fs=None: d4imp._d4_source.TextPool())
    monkeypatch.setattr(imp, "_rule_file", lambda *a, **k: tmp_path / "rules.json")
    result = imp._build_class(entry, tmp_path, _rule_files(), {"options": {}, "game_path": tmp_path,
                                                               "state_root": tmp_path})
    assert not result.built and "body_type differs" in result.error


@pytest.mark.parametrize("sid,donor", [(240, True), (250, True), (610, True), (210, False),
                                       (230, False), (180, False), (220, False), (310, False)])
def test_donor_tracks_follow_the_source_motion_count(data, sid, donor):
    assert d4imp.donor_tracks(data, sid) is donor
