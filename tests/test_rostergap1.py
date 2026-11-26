"""ROSTERGAP1: DD2 leases for the rows the roster asked for, parked duplicates, D1C overlay (offline, no build)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib.importers import d1c  # noqa: E402
from d5lib.importers import dd2  # noqa: E402
from d5lib.importers._dd2_baseline import leases  # noqa: E402

NEW = ("DD2_Class_22680", "DD2_Unique_941", "DD2_Unique_480", "DD2_Unique_300", "DD2_Unique_640")
PARKED = ("DD2_Class_22190", "DD2_Class_22100")


def test_dd2_new_leases_do_not_collide_and_parked_say_why():
    ls = leases()
    live = {k: v for k, v in ls.items() if not v.get("parked")}
    for k in NEW:
        assert live[k]["new"] is True
    for k in PARKED:
        assert ls[k]["parked"] and "Kit already ships" in ls[k]["why"]
    seen = {}
    for k, v in live.items():
        for kind, ids in (("char", v["rank_ids"]), ("help", [v["help"]]), ("quest", v["quests"]),
                          ("slot", [v["quest_slot"]] if v.get("quest_slot") else []),
                          ("personality", v["personalities"])):
            for i in ids:
                assert (kind, i) not in seen, f"{kind} {i}: {k} and {seen[(kind, i)]}"
                seen[(kind, i)] = k
    art = sorted(v["physical"] for v in live.values() if v["kind"] == "unique")
    assert all(b - a >= 3 for a, b in zip(art, art[1:])), "art windows overlap"


def test_dd2_new_entry_skips_baseline_gate(tmp_path, monkeypatch):
    from d5lib import importcore
    from d5lib.importers import _dd2_baseline
    pack = tmp_path / "pack"
    pack.mkdir()
    monkeypatch.setattr(_dd2_baseline, "build_baseline", lambda e, o, c: (pack, {}))
    monkeypatch.setattr(dd2, "validate_pack", lambda p: ({"identity": True}, []))
    seen = []
    monkeypatch.setattr("d5lib.importers._dd2_validation.baseline_preserved",
                        lambda *a, **k: seen.append(a) or (False, []))
    monkeypatch.delenv("D5_DD2_REVIEWED_ABILITIES", raising=False)
    from dd2innate_text import POOL
    monkeypatch.setattr('d5lib.importers._dd2_source.text_pool', lambda *a, **k: POOL)
    ctx = dict(installed_root=tmp_path)
    for folder, ran in (("DD2_Class_22680", False),  # DD2EVIL2: 480 is an own row now, 22680 is the link-only pack
                         ("DD2_Unique_140", True)):  # 570 has an innate overlay that needs a real pack
        entry = importcore.Entry(id="x", kind="unique", name="x", mod_folder=folder)
        (tmp_path / folder).mkdir()
        res = dd2.Importer().build(entry, tmp_path / folder, ctx)
        assert ("baseline_preserved" in res.gates) is ran


def test_d1c_overlay_makes_2400_2580_buildable_with_free_leases():
    rows = {int(r["id"]): r for r in d1c.unique_rows(names=False)}      # kit data: ids and rules, no game file
    assert rows[2400]["feasibility"] == rows[2580]["feasibility"] == "medium"
    assert rows[6701]["feasibility"] == "hard"           # props stay out
    both = d1c.unique_leases()
    extra = {k: both[k] for k in ("2400", "2580")}
    others = [v for k, v in both.items() if k not in extra]
    for v in extra.values():
        assert all(v["identity"] != o["identity"] for o in others)
        assert all(abs(v["physical"] - o["physical"]) >= 3 for o in others)
        for key in ("help_id", "quest_id", "quest_slot"):
            assert all(v[key] != o.get(key) for o in others)
