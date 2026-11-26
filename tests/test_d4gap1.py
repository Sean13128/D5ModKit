"""D4GAP1: NPC appearance rule, NPC leases, class sprite override (offline, no build)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib.importers import _d4_source, d4  # noqa: E402

DIAGNOSTIC = Path('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+')

NEW = {4390, 5301, 5305, 5306, 5307, 5308, 5309, 5310, 5388}
# D4-NPC1: the 14 rows on an owner's art (own identity/stats/skills, no art window of their own).
SHARED = {4300, 4310, 4320, 4330, 4340, 4350, 4400, 5300, 5302, 5303, 3307, 5403, 5414, 990}


@pytest.fixture(scope="module")
def imp():
    root = None if os.environ.get('D5_SOURCE_DIR') else (DIAGNOSTIC if DIAGNOSTIC.is_dir() else None)
    if root is None and not os.environ.get('D5_SOURCE_DIR'):
        pytest.skip("no prepared D4 source (D5_SOURCE_DIR) and no Disgaea Source copy")
    try:
        imp = d4.Importer()
        imp._source_cache = (str(root) if root else None, _d4_source.data_dir(root))
    except _d4_source.D4SourceError as exc:
        pytest.skip(f"D4 source not usable: {exc}")
    return imp


def test_twin_of_a_leased_unique(imp):
    """Genjuro / Justice Fuka / Malice Des X wear a leased unique's body in its bank (990 = Valvatorez)."""
    assert "D4_Unique_10" in imp.npc_twin(None, 990, "D4_Unique_990")
    assert "D4_Unique_40" in imp.npc_twin(None, 5414, "D4_Unique_5414")
    assert "D4_Unique_180" in imp.npc_twin(None, 5403, "D4_Unique_5403")


def test_twin_of_a_class_body(imp):
    built = imp.npc_twin(None, 5300, "D4_Unique_5300")          # Task Force Member = Bouncer, bank 0
    assert "built as D4_Class_1140" in built
    native = imp.npc_twin(None, 4310, "D4_Unique_4310")         # Senator Aiko = Archer, bank 0
    assert "D5-native" in native and "Archer" in native


def test_recoloured_rows_are_new_looks(imp):
    """Another colour bank is a new look: the nine leased NPCs are not twins."""
    for sid in NEW:
        assert imp.npc_twin(None, sid, f"D4_Unique_{sid}") == "", sid


def test_npc_leases_are_complete_and_disjoint():
    doc, leases = d4.load_leases()
    npc = {int(m.rsplit("_", 1)[1]): v for m, v in leases.items() if v.get("npc")}
    assert set(npc) == NEW | SHARED
    others = [v for m, v in leases.items() if not v.get("npc") and not v.get("parked")]
    for key in ("identity", "physical"):
        mine = [v[key] for v in npc.values() if not v.get("share_art_with")]
        assert len(set(mine)) == len(mine)
        assert not set(mine) & {v[key] for v in others}
    assert len({v["identity"] for v in npc.values()}) == len(npc)      # shared art, own identity row
    for key in ("quest_id", "quest_slot", "help_id"):
        mine = [v["storage"][key] for v in npc.values() if v.get("storage")]
        assert len(set(mine)) == len(mine)
        assert not set(mine) & {v["storage"][key] for v in others}
    art = json.loads((Path(d4.WORKTREE) / "d5lib/data/unique_art_leases.json").read_text())["leases"]
    for sid, v in npc.items():          # a physical number in the third lease run must be recorded
        if not v.get("share_art_with"):
            assert art[f"D4_Unique_{sid}"]["physical"] == v["physical"]
            assert v["template"] in (1010, 1020, 2140) and v["voice_id"] >= 9140
        else:                           # D4-NPC1: draws with the owner's keys, nothing of its own
            assert v["share_sprite"] == v["share_color"] and v["share_art_with"]
            assert v["voice_id"] >= 9140


def test_rifle_demon_leaves_the_vanilla_sprite_family():
    assert d4.SPRITE_FAMILY_OVERRIDE == {2190: 2840}


def test_donor_only_passes_the_unique_skill_gate(tmp_path):
    """learn_count 0 passes only when the map says no source skills, or donor_only (source skills, none with a D5 twin)."""
    from d5lib import importcore
    mod = tmp_path / "mods" / "D4_Unique_5308"
    (mod / "patches/db").mkdir(parents=True)
    (mod / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": 18260, "learn_count": 0}]}))
    maps = tmp_path / "maps"
    maps.mkdir()
    for entry, ok in (({}, False), ({"donor_only": True}, True), ({"no_source_skills": True}, True)):
        (maps / "d4.json").write_text(json.dumps({"uniques": {"5308": entry}}))
        assert importcore.unique_skill_gate(mod, maps)[0] is ok


def test_donor_rows_exist_for_every_npc_without_a_learn_list():
    doc = json.loads((Path(d4.WORKTREE) / "d5lib/sourcemaps/d4.json").read_text())["uniques"]
    for sid in (4390, 5305, 5306, 5307, 5308, 5309, 5310):
        e = doc[str(sid)]
        assert (e.get("no_source_skills") or e.get("donor_only")) and e["skills"]
        assert all(r["label"] == "donor" and r["d5_id"] for r in e["skills"])


def test_gate_claims_the_d4_overlay_evility_rows_for_other_importers(tmp_path):
    """DRPGBUILD2's samples took Skill.dat 7000/7003-7005, rows D4 classes 2090/2050/2120/2150 record in the
    reviewed overlay: another importer's folder on them fails, the D4 folder itself does not."""
    from d5lib import importcore
    claims = {(owner, tuple(sorted(c.get("Skill.dat", ())))) for src, owner, c in importcore.lease_claims()
              if src == "d4-overlay"}
    assert ("D4_Class_2050", (7003, 7006, 7007, 8096, 8223, 8274)) in claims
    owners = {o for o, _ in claims}
    assert "D4_Class_1010" not in owners                    # out of scope: D5 already has Warrior
    assert "D4_Class_2090" in owners


def test_lease_tool_keeps_leases_no_installed_pack_can_regenerate():
    """build_d4_leases.py used to rebuild from installed packs alone and drop the nine npc entries (and the 14
    restored uniques); it must now return every key the file on disk has."""
    sys.path.insert(0, str(Path(d4.WORKTREE) / "tools"))
    import build_d4_leases as tool
    if not tool.installed_packs():
        pytest.skip("installed D4 packs not present")
    built = tool.build()["characters"]
    on_disk = json.loads(tool.OUT.read_text())["characters"]
    assert set(on_disk) <= set(built)
    assert {str(s) for s in NEW | SHARED} <= set(built) and all(built[str(s)].get("npc") for s in NEW | SHARED)
    for s in NEW | SHARED:            # the declaration (not the pack facts) must survive a rerun unchanged
        for key in ("mod", "npc", "identity", "share_art_with", "share_sprite", "share_color"):
            assert built[str(s)].get(key) == on_disk[str(s)].get(key), (s, key)


def test_drpg_sample_evilities_are_pinned_off_the_d4_rows():
    """The three DRPG samples' evility rows are pinned in the manifest and sit on no D4 overlay row."""
    from d5lib.importers import _drpg_namespaces as ns
    man = json.loads((Path(d4.WORKTREE) / "d5lib/importers/drpg-leases.json").read_text())
    pins = {b["lease"]: b["evilities"] for b in man["bases"] if b.get("evilities")}
    assert set(pins) == set(ns._SAMPLE_EVILITIES)
    for key, remap in pins.items():
        assert set(map(int, remap)) == set(ns._SAMPLE_EVILITIES[key])
    overlay = json.loads((Path(d4.WORKTREE) / "d5lib/importers/d4-evility-overlay.json").read_text())["mods"]
    d4_ids = {int(r["id"]) for st in overlay.values() for r in st.get("skill_rows", [])}
    assert not {v for r in pins.values() for v in r.values()} & d4_ids
    got = ns.reserve_evilities({"drpg:55": {}}, None, ".", pinned=pins)     # pinned: no table, no folders read
    assert got == {"drpg:55": {7120: 7130, 7121: 7131}}
