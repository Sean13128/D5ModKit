"""STATORACLE1: the stat formula, the labels and the gate (offline; the Unicorn differential is tools/stat_oracle.py)."""
import json

from d5lib import statfidelity as sf

SERAPHINA = [26, 15, 14, 15, 15, 15, 21, 16]


def test_formula_matches_live_readings():
    # status panel, fresh LV1 recruits (coordinator 2026-11-10): every stat inside the 47..53 roll range
    for live in ([27, 15, 13, 14, 14, 15, 20, 16], [25, 15, 13, 15, 15, 15, 22, 15]):
        lo, hi = sf.stats_at(SERAPHINA, 1, [47] * 8), sf.stats_at(SERAPHINA, 1, [53] * 8)
        assert all(a <= v <= b for a, v, b in zip(lo, live, hi))
    assert sf.stats_at(SERAPHINA, 100)[0] == 26 * 101 // 2 * 496 // 100       # HP x 496 % at level 100
    assert sf.stats_at(SERAPHINA, 9999)[2] == 14 * 5000                       # HP cap 800 %, others base*5000


def test_growth_byte_wrap_flagged():
    assert sf.row_flags([300] + [10] * 7) and not sf.row_flags(SERAPHINA)
    assert sf.stats_leveled([256] + [10] * 7, 100)[0] < sf.stats_leveled([255] + [10] * 7, 100)[0]


def test_labels():
    src = [10, 5, 8, 6, 4, 4, 7, 6]
    assert sf.label_vector(src, src) == ["exact"] * 8
    assert sf.label_vector([x * 3 for x in src], src) == ["scaled"] * 8
    assert sf.label_vector(SERAPHINA, src, SERAPHINA) == ["donor"] * 8
    assert sf.likely_cause([10, 5, 8, 6, 4, 6, 7, 4], src, None) == "stat order: RES/SPD swapped"


def test_drpg_map_keeps_profile_and_tier():
    med = {0: 184, 2: 56, 3: 55, 4: 54, 5: 56, 7: 56}
    caster = [109, None, 26, 29, 44, 40, None, 56]                            # high INT/RES profile
    out = sf.drpg_map(caster, SERAPHINA, med)
    assert out[1] == 15 and out[6] == 21                                      # SP, HIT stay donor
    assert out[4] > out[2] and out[5] > out[2]                                # INT, RES above ATK as in the source
    assert abs(sum(out[k] for k in (0, 2, 3, 4, 5)) - sum(SERAPHINA[k] for k in (0, 2, 3, 4, 5))) <= 3
    assert sf.drpg_profile_distance(out, caster, SERAPHINA, med) < sf.drpg_profile_distance(SERAPHINA, caster, SERAPHINA, med)


def test_gate_label_present_and_consistent(tmp_path):
    vanilla = [dict(id=40, name_EN="Seraphina", **{f"base_{s}": v for s, v in zip(sf.STATS, SERAPHINA)},
                    **{f"apt_{s}": 100 for s in sf.STATS})]
    row = dict(id=900, tier=0, name_EN="X", **{f"base_{s}": v for s, v in zip(sf.STATS, [10, 5, 8, 6, 4, 4, 7, 6])},
               **{f"apt_{s}": 100 for s in sf.STATS})
    (tmp_path / "patches/db").mkdir(parents=True)
    (tmp_path / "patches/db/char.dat.json").write_text(json.dumps({"table": "char.dat", "added": [row]}))
    meta = {"name": "X", "description": "Source art and exact stored source bases/aptitudes",
            "source_import": {"source_ranks": [{"id": 1}]}}
    (tmp_path / "mod.json").write_text(json.dumps(meta))
    src = {1: dict(base=[10, 5, 8, 6, 4, 4, 7, 6], apt=[100] * 8)}
    ok, why, rec = sf.stat_label_gate(tmp_path, "d4", vanilla, src)
    assert ok and rec["computed"] == ["exact"], why
    src[1]["base"] = [10, 5, 8, 6, 4, 6, 7, 4]                                # rows now contradict "exact"
    ok, why, _ = sf.stat_label_gate(tmp_path, "d4", vanilla, src)
    assert not ok and "declared 'exact'" in why
    meta["description"] = "no claim"
    (tmp_path / "mod.json").write_text(json.dumps(meta))
    ok, why, _ = sf.stat_label_gate(tmp_path, "d4", vanilla, src)
    assert not ok and "no stat fidelity label" in why
