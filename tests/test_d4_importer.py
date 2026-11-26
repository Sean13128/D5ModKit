"""D4 importer roster: reads the verified prepared source (or an explicit diagnostic copy), no build."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib.importers import _d4_source  # noqa: E402
from d5lib.importers.d4 import Importer  # noqa: E402

DIAGNOSTIC = Path('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+')


def source_root():
    """The prepared folder when D5_SOURCE_DIR is set, else the project's own D4 copy for diagnosis."""
    if os.environ.get('D5_SOURCE_DIR'):
        return None
    return DIAGNOSTIC if DIAGNOSTIC.is_dir() else None


@pytest.fixture(scope="module")
def imp():
    try:
        root = source_root()
        if root is None and not os.environ.get('D5_SOURCE_DIR'):
            pytest.skip("no prepared D4 source (D5_SOURCE_DIR) and no Disgaea Source copy")
        imp = Importer()
        files = _d4_source.data_dir(root)
        imp._source_cache = (str(root) if root else None, files)
    except _d4_source.D4SourceError as exc:
        pytest.skip(f"D4 source not usable: {exc}")
    return imp


def test_roster_covers_the_recorded_class_families(imp):
    # 45 allocated families: the registry's 46th row is a name-only duplicate of a D5 class
    # (audit 2026-11-03).
    roster = imp.roster()
    classes = [e for e in roster if e.kind == "class"]
    assert len(classes) == 45
    assert {e.source_ref["row"] for e in classes} >= {1010, 1080, 1250, 2010, 2200}
    assert {e.mod_folder for e in classes} >= {"D4_Class_1010", "D4_Class_1080"}


def test_every_entry_pins_a_source_file_and_row(imp):
    for entry in imp.roster():
        assert entry.source_ref["file"].endswith("DATABASE_EN.dat")
        assert isinstance(entry.source_ref["row"], int)
        assert len(entry.source_ref["sha256"]) == 64


def test_uniques_are_the_leased_packs(imp):
    uniques = [e for e in imp.roster() if e.kind == "unique"]
    assert len(uniques) >= 33
    assert all(e.mod_folder.startswith("D4_Unique_") for e in uniques)


def test_unique_census_marks_the_records_shipped_rows(imp):
    census = imp.unique_census(source_root())
    assert census, "no D4 named characters decoded from char.dat"
    shipped = {r["id"] for r in census if r["shipped"]}
    # The shipped set is the recorded lease file (D4-ROSTER1), never a listing of installed packs.
    assert {310, 10, 510, 520} <= shipped
    parked = {r["id"] for r in census if "parked" in r["why_not"]}
    assert parked == {510, 520}
    assert all(not r["in_scope"] for r in census if r["id"] in parked)
    assert all(r["in_scope"] for r in census if r["id"] in shipped and r["id"] not in parked)
    assert all(r["why_not"] for r in census if not r["in_scope"])
