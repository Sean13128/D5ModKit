"""D4-ROSTER1: class scope list + lease-driven unique roster (offline, no build)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib.importers import _d4_source  # noqa: E402
from d5lib.importers.d4 import Importer, load_leases  # noqa: E402

DIAGNOSTIC = Path('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+')

INSTALLED_CLASSES = {1080, 1140, 1190, 1200, 1220, 1240, 1250, 2110, 2130, 2160, 2200}


@pytest.fixture(scope="module")
def roster():
    root = None if os.environ.get('D5_SOURCE_DIR') else (DIAGNOSTIC if DIAGNOSTIC.is_dir() else None)
    if root is None and not os.environ.get('D5_SOURCE_DIR'):
        pytest.skip("no prepared D4 source (D5_SOURCE_DIR) and no Disgaea Source copy")
    try:
        imp = Importer()
        imp._source_cache = (str(root) if root else None, _d4_source.data_dir(root))
    except _d4_source.D4SourceError as exc:
        pytest.skip(f"D4 source not usable: {exc}")
    return imp.roster()


def test_class_scope(roster):
    classes = [e for e in roster if e.kind == "class"]
    assert len(classes) == 45
    on = {e.source_ref["row"] for e in classes if e.in_scope}
    assert INSTALLED_CLASSES <= on
    assert len(on) == 18                     # 16 workbook Buildable + 1190/1200 Overlord-convert
    assert all(e.why_not for e in classes if not e.in_scope)
    assert all("D5" in e.why_not or "Overlord" in e.why_not for e in classes if not e.in_scope)


def test_uniques_follow_the_lease_file(roster):
    _doc, leases = load_leases()
    uniques = {e.mod_folder: e for e in roster if e.kind == "unique"}
    leased = {m for m, v in leases.items() if not v["parked"]}
    assert len(leased) == 32 + 9 + 14 and all(uniques[m].in_scope for m in leased)   # D4GAP1: + 9; D4-NPC1: + 14 shared-art
    assert not uniques["D4_Unique_510"].in_scope and not uniques["D4_Unique_520"].in_scope
    for m in ("D4_Unique_10", "D4_Unique_230", "D4_Unique_500"):   # leased, not installed today
        assert uniques[m].in_scope and "shipped" in uniques[m].detail
    # D4GAP1: the 25 NPC rows are 9 leased builds + 16 closed rows, each with its own written reason
    assert not [e for e in uniques.values() if e.why_not == "D4-NPC1"]
    assert sum(e.in_scope for e in uniques.values()) == 32 + 9 + 14


def test_ids_unique(roster):
    ids = [e.id for e in roster]
    assert len(ids) == len(set(ids))
    assert "d4:1080" in ids and "d4:u10" in ids


def test_run_reports_excluded_and_only_selects(roster, tmp_path):
    """Selecting only out-of-scope ids builds nothing (no game/build touched) and lists them excluded."""
    from d5lib import importcore
    out_of_scope = [e.id for e in roster if not e.in_scope]
    assert len(out_of_scope) == 27 + 2 + 2      # D4-NPC1: only the two rows with no owner art remain listed
    log = []
    summary = importcore.run("d4", out_dir=tmp_path, only=",".join(out_of_scope), game_path=tmp_path,
                             state_root=tmp_path, log=log.append)
    assert summary["total"] == 0 and len(summary["excluded"]) == len(out_of_scope)
    assert {x["id"] for x in summary["excluded"]} == set(out_of_scope)
    assert (tmp_path / "d4" / "results.json").is_file()
    # --only by id / folder resolves in-scope entries without a warning (selection only, no build)
    one = [e for e in roster if e.id == "d4:u10"]
    assert one and one[0].in_scope and one[0].mod_folder == "D4_Unique_10"
