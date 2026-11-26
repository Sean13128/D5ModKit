"""D4-NPC1: shared-art D4 characters (own identity, another pack's art) — offline, no build."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import importcore  # noqa: E402
from d5lib.importers import d4  # noqa: E402


def test_shared_shape_takes_the_owners_keys_not_an_art_window():
    from d5lib import d4unique
    shape = d4unique.unique_shape(470, identity=18340,
                                  shared=dict(owner="vanilla", sprite_id=1010, color_id=1010))
    assert shape["registry"] and shape["shared"]
    assert (shape["sprite_id"], shape["color_id"]) == (1010, 1010)
    assert shape["keyed"] == []                      # nothing leased, nothing overwritten


def test_shared_shape_still_needs_a_registry_identity():
    from d5lib import d4unique
    with pytest.raises(ValueError):
        d4unique.unique_shape(470, identity=999, shared=dict(owner="vanilla", sprite_id=1, color_id=1))


def test_check_conflicts_ignores_the_owner_art_for_a_shared_build(tmp_path):
    from d5lib import d4unique, database
    # A vanilla char table stand-in with the owner class row and the new identity absent
    class T:
        rows = []
        def index_of(self, _):
            return -1
    tables = {"char.dat": T()}
    out = d4unique.check_conflicts(tables, [], 18340, graphics={1010, 1011, 1012, 11010, 11011},
                                   physical=1010, shared=dict(owner="vanilla"))
    assert out["conflicts"] == [] and out["keyed_graphics"] == []
    with pytest.raises(ValueError):                  # a non-shared build on the same keys is a collision
        d4unique.check_conflicts(tables, [], 18340, graphics={1010}, physical=1010)


def test_mod_claims_does_not_claim_art_for_a_shared_unique(tmp_path):
    mod = tmp_path / "mods" / "D4_Unique_18340"
    (mod / "patches/characters").mkdir(parents=True)
    (mod / "mod.json").write_text(json.dumps({"id": "D4_Unique_18340", "name": "x"}))
    (mod / "patches/characters/unique.json").write_text(json.dumps(
        {"schema": 1, "identity": 18340, "physical": 1010, "shares_art_with": "vanilla",
         "sprite_id": 1010, "color_id": 1010}))
    assert not importcore.mod_claims(mod).get("anm")
    (mod / "patches/characters/unique.json").write_text(json.dumps(
        {"schema": 1, "identity": 18340, "physical": 646}))
    assert set(importcore.art_window(646)) <= importcore.mod_claims(mod)["anm"]


def test_lease_claims_skip_the_art_window_of_a_shared_row():
    claims = {(src, owner): c for src, owner, c in importcore.lease_claims() if src == "d4"}
    shared = claims[("d4", "D4_Unique_4340")]
    assert shared["char.dat"] == {18340} and not shared.get("anm")
    window = claims[("d4", "D4_Unique_4390")]        # a built NPC keeps its own window
    assert set(importcore.art_window(646)) <= window["anm"]


def test_finalizer_treats_a_shared_row_as_art_the_owner_already_has():
    from d5lib import newchars, newclasses
    shared = {"schema": 1, "identity": 18340, "physical": 1010, "shares_art_with": "vanilla"}
    assert newchars.is_new_character({"id": 18340, "color_id": 1010, "sprite_id": 1010},
                                     {}, (), {18340: shared}) is False
    assert newclasses.registry_monster_sprites({18400: dict(shared, kind="monster")}) == []


def test_classcheck_allows_the_shared_row_on_a_class_colour(tmp_path):
    from d5lib import classcheck
    def build(shares):
        mod = tmp_path / ("with" if shares else "without")
        (mod / "patches/db").mkdir(parents=True)
        (mod / "patches/characters").mkdir(parents=True)
        (mod / "patches/db/char.dat.json").write_text(json.dumps(
            {"added": [dict(id=18420, sprite_id=1120, color_id=1120, body_type=0)]}))
        decl = dict(schema=1, identity=18420, physical=1120, sprite_id=1120, color_id=1120,
                    template=1020, template_colour=1020, kind="humanoid")
        if shares:
            decl["shares_art_with"] = "vanilla"
        (mod / "patches/characters/unique.json").write_text(json.dumps(decl))
        return mod
    shared = [f for f in classcheck.check(build(True)) if f["rule"] == "R6-unique-lease"]
    plain = [f for f in classcheck.check(build(False)) if f["rule"] == "R6-unique-lease"]
    assert shared == [] and plain            # the low-lease rule still holds without shares_art_with


def test_the_npc1_leases_are_written_and_the_two_unarmed_rows_stay_closed():
    doc, leases = d4.load_leases()
    shared = {int(k.rsplit("_", 1)[1]): v for k, v in leases.items() if v.get("share_art_with")}
    assert len(shared) == 14
    for sid, v in shared.items():
        assert v["npc"] and v["identity"] >= 18300 and v["identity"] % 10 == 0
        assert v["share_sprite"] == v["share_color"]
        assert v["storage"]["quest_id"] < 1490             # below the placeholder rows the board hides
        assert v["storage"]["quest_slot"] < 1024
    npcs = json.loads((ROOT / "d5lib/importers/d4-scope.json").read_text())["_npcs"]
    assert set(npcs) == {"D4_Unique_4370", "D4_Unique_4380"}   # no art anywhere to share
    assert all("no D5/Kit art pack to share" in v["why_not"] for v in npcs.values())


def test_the_roster_lists_every_leased_row_in_scope():
    imp = d4.Importer()
    entries = {e.mod_folder: e for e in imp.roster()}
    for sid in (4300, 4310, 4320, 4330, 4340, 4350, 4400, 5300, 5302, 5303, 3307, 5403, 5414, 990):
        assert entries[f"D4_Unique_{sid}"].in_scope, sid
    assert not entries["D4_Unique_4370"].in_scope
