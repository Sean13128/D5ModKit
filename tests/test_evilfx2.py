"""EVILFX2: the emitter accepts the new vocabulary and refuses its misuse (behaviour: evility/offline_proof_evilfx2.py)."""
import pytest

from d5lib import evility as ev

NEAR = {"kind": "near_has", "of": 1, "radius": 30, "id": 7900}


def test_new_scales_and_conditions_compile():
    rows, conds, fx = ev.table({
        7900: [{"family": "stats", "filter": 5, "effects": [{"stat": "atk", "value": 4, "per": "party_capped"}]},
               {"family": "stats", "effects": [{"stat": "def", "value": 70, "per": "hp_lost_pct"}]},
               {"family": "taken", "effects": [{"value": -40}], "conditions": [{"kind": "other_weapon", "id": 4}]},
               {"family": ["stats", "aura"], "effects": [{"stat": "atk", "value": 45}],
                "conditions": [NEAR, {"kind": "provider_buff", "id": 7}, {"kind": "side_top", "id": 2}]},
               {"family": ["regen", "aura"], "effects": [{"stat": "hp", "value": 8, "base": "provider"}], "conditions": [NEAR]},
               {"family": "stats", "effects": [{"stat": "int", "value": 18}],
                "conditions": [{"kind": "map_debuff_min", "count": 1, "of": 2, "id": 5}, {"kind": "enemy_map_max", "id": 0}]}]})
    assert len(rows) == 6
    assert (0 | 0x100, 8) in fx                      # the provider-base flag on the hp effect
    assert (2 | 21 << 16, 4) in fx and rows[0][7] == 5   # party_capped reads the row's filter


@pytest.mark.parametrize("row", [
    {"family": "stats", "effects": [{"stat": "atk", "value": 4, "per": "party_capped"}]},                 # no cap
    {"family": "stats", "effects": [{"stat": "atk", "value": 1}], "conditions": [{"kind": "self_buff", "id": 1}]},
    {"family": "stats", "effects": [{"stat": "atk", "value": 1}], "conditions": [{"kind": "provider_buff", "id": 2}]},
    {"family": "regen", "effects": [{"stat": "hp", "value": 8, "base": "provider"}]},                     # not an aura
    {"family": ["regen", "aura"], "effects": [{"stat": "hp", "value": 8, "base": "provider"}],
     "conditions": [NEAR, {"kind": "party_min", "count": 2, "of": 1}]},                                   # second map walk
    {"family": ["regen", "aura"], "effects": [{"stat": "sp", "value": 8, "base": "provider"}], "conditions": [NEAR]},
])
def test_misuse_is_refused(row):
    with pytest.raises(ValueError):
        ev.table({7900: row})


def test_save_safety_gate_refuses_a_row_before_an_installed_learnable_row():
    from d5lib import learned
    installed = [{"id": 100, "kind": 0}, {"id": 8845, "kind": 0}, {"id": 26182, "kind": 0}, {"id": 28000, "kind": 2}]
    assert learned.moved(installed, installed + [{"id": 8844, "kind": 1}]) == [(8845, 1, 2), (26182, 2, 3)]
    assert learned.moved(installed, installed + [{"id": 27844, "kind": 1}]) == []      # the late band: only innate rows move
    assert learned.moved(installed, installed[1:]) == [(100, 0, None), (8845, 1, 0), (26182, 2, 1)]   # a removed row too


def test_used_ids_a_staged_copy_stands_for_the_installed_folder(tmp_path, monkeypatch):
    """EVILFX3: a row may move from one staged pack to another (Friends 8840: Prism Red -> the Prism Ranger class)."""
    from d5lib import importcore
    for root, name in (("installed", "A"), ("staged", "A"), ("staged", "B")):
        (tmp_path / root / name).mkdir(parents=True)
        (tmp_path / root / name / "mod.json").write_text("{}")
    claims = {("installed", "A"): {"evility": {8840}}, ("staged", "A"): {}, ("staged", "B"): {"evility": {8840}}}
    monkeypatch.setattr(importcore, "mod_claims", lambda f: claims[(f.parent.name, f.name)])
    monkeypatch.setattr(importcore, "lease_claims", lambda **_kwargs: [])
    both = importcore.UsedIds(tmp_path, tmp_path, [tmp_path / "installed", tmp_path / "staged"]).index()
    assert [o for _, o in both[("evility", 8840)]] == ["B"]                    # the staged A no longer claims it
    only_b = importcore.UsedIds(tmp_path, tmp_path, [tmp_path / "installed"]).index()
    assert [o for _, o in only_b[("evility", 8840)]] == ["A"]                  # without a staged A the claim stands
