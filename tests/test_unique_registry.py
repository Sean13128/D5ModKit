"""Unique characters on registry identities (decision 2026-10-27) — the shape the importer must keep.

A unique character is one rank on a registry class identity (>= 10000) whose char.dat row id equals
that identity, with its sprites / portraits / faces keyed to a low "physical" row leased for it:

  * `10000 <= identity <= 10990`, a multiple of ten, rank digit 0 only (anm/manifest band
    `unique_registry_lease`), outside Overlord's 20000..21999;
  * exactly one char.dat row, at the identity, with `sprite_id == color_id == physical`;
  * a physical lease below 1000 whose keyed art numbers (n, n+1, n+2, 10000+n, 10001+n) are free;
  * the recruit quest rewards the identity (not the physical row, which holds no character).

These tests pin the importer's validation, the classcheck rule (R6), the finalizer's colour-key
handling and the manifest's band, because each one alone would let a pack ship the old low-row shape.
"""
import json
import os

import pytest

from d5lib import classcheck, newchars, nativeimports, ownership, slots


# --------------------------------------------------------------------------------------------- importer
def test_registry_identity_accepts_the_band():
    got = nativeimports.unique_identity(10000, 853)
    assert got == dict(identity=10000, physical=853,
                       keyed=[853, 854, 855, 10853, 10854])


@pytest.mark.parametrize("identity,physical", [
    (9990, 853),            # below the unique registry band (a low class id is a different band)
    (20000, 853),           # Overlord's reserved band
    (10005, 853),           # not a family base
    (10000, 10000),         # the identity is not its own art lease
    (10000, 1000),          # art lease must be a low id
    (32770, 853),           # past the range the receiver accepts
])
def test_registry_identity_refuses(identity, physical):
    with pytest.raises(ValueError):
        nativeimports.unique_identity(identity, physical)


# -------------------------------------------------------------------------------------------- classcheck
def build_unique_mod(root, identity=10000, physical=853, ranks=(0,), sprite=None, colour=None,
                     declare=True, quest_value=None, quest_type=5):
    d = os.path.join(str(root), "patches")
    os.makedirs(os.path.join(d, "db"), exist_ok=True)
    os.makedirs(os.path.join(d, "characters"), exist_ok=True)
    rows = [dict(id=identity + r, sprite_id=physical if sprite is None else sprite,
                 color_id=physical if colour is None else colour) for r in ranks]
    with open(os.path.join(d, "db", "char.dat.json"), "w", encoding="utf-8") as f:
        json.dump(dict(table="char.dat", added=rows), f)
    quest = dict(id=900, reward_type=quest_type,
                 reward_value=identity if quest_value is None else quest_value)
    with open(os.path.join(d, "db", "Quest.dat.json"), "w", encoding="utf-8") as f:
        json.dump(dict(table="Quest.dat", added=[quest]), f)
    if declare:
        with open(os.path.join(d, "characters", "unique.json"), "w", encoding="utf-8") as f:
            json.dump(dict(schema=1, identity=identity, physical=physical, template=1110,
                           template_colour=1110, kind="humanoid"), f)
    return str(root)


def test_a_declared_unique_passes_r6(tmp_path):
    mod = build_unique_mod(tmp_path)
    assert [f["rule"] for f in classcheck.check(mod)] == []


def test_an_undeclared_registry_row_is_an_error(tmp_path):
    mod = build_unique_mod(tmp_path, declare=False)
    found = classcheck.check(mod)
    assert "R6-unique-row" in {f["rule"] for f in found}
    assert classcheck.gate(found)


def test_a_colour_id_that_is_not_the_lease_is_an_error(tmp_path):
    """the game keys portraits/faces to the colour id, so a row that keeps 10000 shows the wrong art"""
    mod = build_unique_mod(tmp_path, colour=10000)
    assert "R6-unique-lease" in {f["rule"] for f in classcheck.check(mod)}


def test_a_second_rank_is_an_error(tmp_path):
    mod = build_unique_mod(tmp_path, ranks=(0, 1))
    assert "R6-unique-ranks" in {f["rule"] for f in classcheck.check(mod)}


def test_a_physical_id_that_is_not_low_is_an_error(tmp_path):
    mod = build_unique_mod(tmp_path, physical=10000, sprite=10000, colour=10000)
    assert "R6-unique-lease" in {f["rule"] for f in classcheck.check(mod)}


def test_the_recruit_quest_must_reward_the_identity(tmp_path):
    mod = build_unique_mod(tmp_path, quest_value=853)
    found = classcheck.check(mod)
    assert "R4-quest-reward" in {f["rule"] for f in found}


def test_a_class_family_row_is_not_mistaken_for_an_undeclared_unique(tmp_path):
    """R6 must not fire on a registry class's own rank rows (they are declared by the class descriptor)"""
    d = os.path.join(str(tmp_path), "patches")
    os.makedirs(os.path.join(d, "classes"), exist_ok=True)
    os.makedirs(os.path.join(d, "db"), exist_ok=True)
    with open(os.path.join(d, "classes", "class_11390.json"), "w", encoding="utf-8") as f:
        json.dump(dict(family=11390, template=1110, kind="humanoid", sprite_family=1540,
                       unlocked=True, unlocked_ranks=6), f)
    with open(os.path.join(d, "db", "char.dat.json"), "w", encoding="utf-8") as f:
        json.dump(dict(table="char.dat", added=[dict(id=11390 + k, sprite_id=1540, color_id=1540 + k)
                                                for k in range(6)]), f)
    assert not [f for f in classcheck.check(str(tmp_path)) if f["rule"].startswith("R6")]


# ------------------------------------------------------------------------------------------------ finalizer
class Table:
    def __init__(self, rows):
        self.rows = rows


def test_newchars_finds_a_registry_unique_and_keeps_its_colour():
    rows = [dict(id=10000, sprite_id=853, color_id=853, name_EN="Thursday"),
            dict(id=1110, sprite_id=1110, color_id=1110, name_EN="Warrior")]
    declared = {10000: dict(identity=10000, physical=853, template_colour=1110)}
    found = newchars.find(Table(rows), Table([]), (), declared)
    assert found == {10000: 1110}
    assert newchars.is_new_character(rows[0], {}, (), declared) is True
    # a registry row that does not point at its lease is not treated as a new character
    wrong = [dict(id=10000, sprite_id=853, color_id=10000, name_EN="Thursday")]
    assert newchars.is_new_character(wrong[0], {}, (), declared) is False


def test_a_legacy_low_unique_still_maps_to_its_own_colour():
    rows = [dict(id=931, sprite_id=931, color_id=2190, name_EN="Shark King")]
    assert newchars.find(Table(rows), Table([])) == {931: 2190}


# ------------------------------------------------------------------------------------------------ manifest
def manifest():
    return ownership.load()


def claims(*items):
    return [ownership.Claim(holder, ns, a, b, label=label) for holder, ns, a, b, label in items]


def test_the_unique_band_is_declared_with_its_own_rule():
    job = manifest().namespace("job_class_id")
    band = job.band_at(10000)
    assert band is not None and band.rule == "unique_registry_lease"
    assert job.rules["unique_registry_lease"] == {
        "first": 10000, "last": 10990, "step": 10, "ranks": 1,
        "note": job.rules["unique_registry_lease"]["note"]}


def test_a_unique_identity_is_clean_and_derives_no_class_ids():
    m = manifest()
    found = ownership.check_claims(m, claims(
        ("kit:Unique_1", "job_class_id", 10000, 10000, "u"),
        ("kit:Unique_1", "char_dat_row", 10000, 10000, "u"),
        ("kit:Unique_1", "anm_id", 853, 855, "u"),
        ("kit:Unique_1", "anm_id", 10853, 10854, "u")))
    assert [str(f) for f in ownership.errors(found)] == []


def test_two_ranks_on_a_unique_identity_are_refused():
    found = ownership.check_claims(manifest(), claims(
        ("kit:Unique_1", "job_class_id", 10000, 10001, "u")))
    assert "unique_ranks" in {f.kind for f in ownership.errors(found)}


def test_a_unique_identity_outside_the_receiver_range_is_refused():
    """11000 passes the *class* rule (it is a valid registry class id): the band assignment is what makes
    an id a unique, so the source-pack validator checks the band itself (validate_uniques `band_ok`)."""
    found = ownership.check_claims(manifest(), claims(
        ("kit:Unique_1", "job_class_id", 11000, 11000, "u")))
    assert [str(f) for f in ownership.errors(found)] == []


def test_an_overlord_id_stays_refused_for_a_unique():
    found = ownership.check_claims(manifest(), claims(
        ("kit:Unique_1", "job_class_id", 20000, 20000, "u")))
    assert ownership.errors(found)


# ---------------------------------------------------------------------------------------------- art leases
def test_the_sprite_lease_pool_skips_used_numbers_and_keeps_three_apart(monkeypatch):
    from d5lib import sprites
    monkeypatch.setattr(sprites, "used_sprite_numbers", lambda fs: {860, 10867, 5000})
    pool = slots.unique_sprite_pool(None, first=853, last=870)
    assert 853 in pool
    assert 860 not in pool and 866 not in pool       # 860 is used; 866 keys 10866-10867, which is used
    for a, b in zip(pool, pool[1:]):
        assert b - a >= slots.SPRITE_LEASE_SPACING


def test_a_taken_lease_moves_the_next_one_three_away(monkeypatch):
    from d5lib import sprites
    monkeypatch.setattr(sprites, "used_sprite_numbers", lambda fs: set())
    pool = slots.unique_sprite_pool(None, taken={853}, first=853, last=860)
    assert pool[0] >= 856


def test_the_default_pool_covers_both_measured_runs_with_853_first(monkeypatch):
    """A lease handed out before the second run existed keeps its number: 853..999 comes first."""
    from d5lib import sprites
    monkeypatch.setattr(sprites, "used_sprite_numbers", lambda fs: set())
    pool = slots.unique_sprite_pool(None)
    first_run = [n for n in pool if n >= 853]
    second_run = [n for n in pool if n <= 403]
    assert pool[:len(first_run)] == first_run, "the 853..999 run must stay in front of the low run"
    assert min(first_run) == 853 and max(first_run) == 997
    assert second_run and 223 in second_run and max(second_run) <= 401  # p+2 must stay inside 223-403
    assert 402 not in second_run and 403 not in second_run
    for run in ([n for n in pool if n >= 853], [n for n in pool if n <= 403]):
        for a, b in zip(run, run[1:]):
            assert b - a >= slots.SPRITE_LEASE_SPACING
    # a lease inside either run blocks its neighbours in the same measurement
    blocked = slots.unique_sprite_pool(None, taken={224})
    assert 223 not in blocked and 226 not in blocked and 227 in blocked


def test_first_and_last_still_measure_one_explicit_run(monkeypatch):
    from d5lib import sprites
    monkeypatch.setattr(sprites, "used_sprite_numbers", lambda fs: set())
    pool = slots.unique_sprite_pool(None, first=900, last=906)
    assert pool == [900, 903, 906]


def test_the_lease_pool_walks_the_measured_runs_in_order(monkeypatch):
    """853-999, then 223-401, then the carved windows of 404-852 (DECISIONS 2026-10-29)."""
    from d5lib import sprites
    assert slots.SPRITE_LEASE_RUNS == ((853, 999), (223, 401), (404, 852))
    exhausted = set(range(853, 1002)) | set(range(223, 404))
    monkeypatch.setattr(sprites, "used_sprite_numbers", lambda fs: set(exhausted))
    pool = slots.unique_sprite_pool(None)
    assert pool and pool[0] == 404, pool[:3]


def test_the_manifest_carves_a_third_run_lease_out_of_the_vanilla_band(tmp_path, monkeypatch):
    """A recorded third-run lease owns its five keys; the rest of 404-852 stays vanilla."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/tools")
    import build_ownership_manifest as builder

    record = tmp_path / "leases.json"
    record.write_text(json.dumps({"leases": {"D1C_Unique_9001": {"physical": 516}}}))
    monkeypatch.setattr(builder, "ART_LEASE_RECORD", str(record))
    manifest = ownership.Manifest(builder.build())
    anm = manifest.namespace("anm_id")
    for n in (516, 517, 518, 10516, 10517):
        assert anm.band_at(n).owner == "kit", n
    assert anm.band_at(515).owner == "vanilla"
    assert anm.band_at(519).owner == "vanilla"
    assert anm.band_at(10515).owner == "vanilla"
    assert anm.band_at(10518).owner == "vanilla"


def test_a_lease_record_outside_the_third_run_is_refused(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/tools")
    import build_ownership_manifest as builder

    record = tmp_path / "leases.json"
    record.write_text(json.dumps({"leases": {"D1C_Unique_9002": {"physical": 900}}}))
    monkeypatch.setattr(builder, "ART_LEASE_RECORD", str(record))
    try:
        builder.third_run_leases()
    except SystemExit as exc:
        assert "outside the third run" in str(exc)
    else:
        raise AssertionError("900 belongs to the first run, not the third")
    record.write_text(json.dumps({"leases": {"D1C_Unique_9003": {"physical": 300}}}))
    try:
        builder.third_run_leases()
    except SystemExit as exc:
        assert "outside the third run" in str(exc)
    else:
        raise AssertionError("a 300 lease belongs to the second run, not the third")
