"""HELDIDS1: the shipped held-ids file must list exactly what the installed-reference pass holds.

``d5lib/importers/held-blank-keys.json`` lets a machine with no installed pack hold the same blank
key times as a build against the install.  It is written by ``tools/build_held_blank_keys.py`` from
BLANKKEYS1's measured apply record, import results and (optionally) a scan, so it may drift from what
``d5lib/holdblank.py`` decides when the installed bank is there.  ``tests/data/heldids1-install-pass.json``
is the measured table: every pack twice through ``tools/import_game.py`` (installed reference, then
``D5_INSTALLED_MODS`` at an empty folder).  These tests fail when the file lists an id the install
pass did not hold (or omits one it did).
"""
import json
from pathlib import Path

TESTS = Path(__file__).resolve().parent
KIT = TESTS.parent
FILE = KIT / "d5lib/importers/held-blank-keys.json"
EVIDENCE = TESTS / "data/heldids1-install-pass.json"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ids(ids):
    return "[" + ",".join(str(i) for i in ids) + "]"


def test_the_file_lists_exactly_the_ids_the_install_pass_holds():
    """Acceptance: no entry may exist in the file for an animation the installed-reference pass does
    not hold, and no held animation may be missing.  D1C_Unique_4 included: the table shows the pass
    holds 7011/7021, so the file may list them."""
    file_games = _load(FILE)["games"]
    measured = _load(EVIDENCE)["packs"]
    for game, packs in file_games.items():
        for pack, banks in packs.items():
            for bank, ids in banks.items():
                held = ((measured.get(game) or {}).get(pack) or {}).get(bank)
                assert held is not None, (
                    f"{pack} {bank}: the install pass does not hold this bank; the file must not list it")
                extra = sorted(set(ids) - set(held["install"]))
                assert not extra, (
                    f"{pack} {bank}: file lists ids the install pass does not hold: {_ids(extra)}")
                missing = sorted(set(held["install"]) - set(ids))
                assert not missing, (
                    f"{pack} {bank}: file omits ids the install pass holds: {_ids(missing)}")


def test_the_file_does_not_hold_a_pack_the_install_pass_leaves_alone():
    """The four BLANKKEYS1 packs that hold nothing (the 1591-only uniques) stay out of the file."""
    file_games = _load(FILE)["games"]
    measured = _load(EVIDENCE)["packs"]
    for game, packs in measured.items():
        for pack, banks in packs.items():
            listed = (file_games.get(game) or {}).get(pack)
            held_any = any(row.get("install") for row in banks.values())
            if not held_any:
                assert not listed, f"{pack}: the install pass holds nothing, the file must not list it"
            else:
                assert listed, f"{pack}: the install pass holds ids, the file must list them"
                for bank, row in banks.items():
                    if row.get("install"):
                        assert bank in listed, f"{pack} {bank}: the install pass holds ids, the file omits the bank"


def test_the_no_install_build_held_the_same_ids():
    """The point of the file: a build with D5_INSTALLED_MODS empty holds the same ids (and keys)."""
    for game, packs in _load(EVIDENCE)["packs"].items():
        for pack, banks in packs.items():
            for bank, row in banks.items():
                assert row["empty"] == row["install"], (
                    f"{pack} {bank}: no-install build {_ids(row['empty'])} != install pass {_ids(row['install'])}")
                if row.get("keys_install") and row.get("keys_empty"):
                    assert row["keys_install"] == row["keys_empty"], (
                        f"{pack} {bank}: keys filled differ between the two builds")


def test_d1c_unique_4_is_held_by_the_install_pass():
    """The pack the REPROFIX3 merge review named: measured in both builds as held 7011: 6, 7021: 7
    keys (BLANKKEYS1: Gordon 7011 2/8 drawn, 7021 6/13), so the file keeps it."""
    row = _load(EVIDENCE)["packs"]["d1c"]["D1C_Unique_4"]["anm00516.lzs"]
    assert row["install"] == [7011, 7021], row
    assert row["empty"] == [7011, 7021], row
    assert _load(FILE)["games"]["d1c"]["D1C_Unique_4"] == {"anm00516.lzs": [7011, 7021]}


def test_the_evidence_covers_every_blankkeys1_pack():
    """27 D1C + 1 D4 + 2 DD2 packs measured; the file ships the 26 that hold something."""
    measured = _load(EVIDENCE)["packs"]
    assert sorted(measured) == ["d1c", "d4", "dd2"]
    assert len(measured["d1c"]) == 27 and len(measured["d4"]) == 1 and len(measured["dd2"]) == 2
    empty = sorted(p for p, banks in measured["d1c"].items()
                   if not any(row.get("install") for row in banks.values()))
    assert empty == ["D1C_Unique_2580", "D1C_Unique_2600", "D1C_Unique_3000", "D1C_Unique_3010"], empty
