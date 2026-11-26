"""importcore: runner, gates, compare, results — exercised with a fake importer."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import importcore  # noqa: E402


def _fake_importer_class():
    from d5lib.importcore import Entry, Result

    class Importer:
        game = "fake"

        def roster(self, source_root=None):
            return [Entry(id="f:1", kind="class", name="One", mod_folder="Fake_One",
                          source_ref={"row": 1}),
                    Entry(id="f:2", kind="unique", name="Two", mod_folder="Fake_Two",
                          source_ref={"row": 2}, in_scope=False, why_not="not selected")]

        def build(self, entry, out_dir, ctx):
            out_dir = Path(out_dir)
            mod = out_dir / "native-mods" / entry.mod_folder
            (mod / "patches/db").mkdir(parents=True)
            (mod / "mod.json").write_text(json.dumps({"name": entry.name, "files": ["patches/db/x.json"]}))
            (mod / "patches/db/x.json").write_text(json.dumps({"table": "char.dat", "added": []}))
            return Result(id=entry.id, mod_folder=entry.mod_folder, built=True,
                          features={"voice": "missing"})

        def compare_reason(self, entry, diff):
            return "known difference for " + entry.id

    return Importer


@pytest.fixture()
def fake(monkeypatch):
    module = types.ModuleType("d5lib.importers.fake")
    module.Importer = _fake_importer_class()
    monkeypatch.setitem(sys.modules, "d5lib.importers.fake", module)
    return module


def test_run_builds_in_scope_and_reports_out_of_scope(fake, tmp_path):
    """An out-of-scope entry is recorded, never built, and not counted against the exit code."""
    summary = importcore.run("fake", out_dir=tmp_path, jobs=2, compare=False,
                             source_root=tmp_path, game_path=tmp_path, state_root=tmp_path,
                             log=lambda *_: None)
    root = tmp_path / "fake"
    assert (root / "mods/Fake_One/mod.json").is_file()
    assert summary["built"] == 1                      # one built, one deliberately out of scope
    assert summary["total"] == 1                      # only in-scope entries are counted
    # the fake build's own db-patch gate fails in a tmp dir (no backups), so the run exits 1;
    # what matters here is that the out-of-scope entry is not what made it fail
    assert summary["built"] == summary["total"] and summary["excluded"]
    assert [r["id"] for r in summary["results"]] == ["f:1"]
    excluded = summary["excluded"]
    assert [e["id"] for e in excluded] == ["f:2"] and excluded[0]["why"]
    saved = json.loads((root / "results.json").read_text())
    assert saved["excluded"] == excluded
    assert "out of scope" in (root / "REPORT.md").read_text()


def test_only_selects_by_id_and_folder(fake, tmp_path):
    summary = importcore.run("fake", out_dir=tmp_path, only="Fake_One", jobs=1,
                             source_root=tmp_path, game_path=tmp_path, state_root=tmp_path,
                             log=lambda *_: None)
    assert [r["id"] for r in summary["results"]] == ["f:1"]


def test_classify_identical_expected_regression(tmp_path):
    from d5lib.importcore import Entry

    entry = Entry(id="x", kind="class", name="x", mod_folder="X")
    assert importcore.classify(([], [], []), entry)[0] == "identical"
    assert importcore.classify((["a"], [], []), entry, lambda e, d: "named reason") == (
        "expected", "named reason")
    verdict, why = importcore.classify(([], ["gone.json"], []), entry)
    assert verdict == "regression" and "gone.json" in why


def test_structure_gate_rejects_bad_json(tmp_path):
    mod = tmp_path / "M"
    (mod / "patches").mkdir(parents=True)
    (mod / "mod.json").write_text("{")
    ok, why = importcore.structure_gate(mod)
    assert not ok and "mod.json" in why


def test_wheel_gate_without_installed_bank_is_open(tmp_path):
    mod = tmp_path / "M"
    mod.mkdir()
    assert importcore.wheel_gate(mod, None) == (True, "no installed bank to freeze against")


def test_tree_diff_counts_added_missing_changed(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root, files in ((a, {"same": "1", "changed": "new", "only_a": "x"}),
                        (b, {"same": "1", "changed": "old", "only_b": "y"})):
        root.mkdir()
        for name, text in files.items():
            (root / name).write_text(text)
    added, missing, changed = importcore.tree_diff(a, b)
    assert added == ["only_a"] and missing == ["only_b"] and changed == ["changed"]


# --------------------------------------------------------------------------- wheel-freeze equality
# A palette is one more image object in the bank's ``ntex + npal`` list, so the wheel-freeze
# reference is the installed bank's exact (textures, palettes) pair.  These tests build a real
# (synthetic, tiny) pair of ANM banks and pin the four cases the old ``<=`` rule got wrong.

def _bank_file(path, *, textures, palettes):
    """Write a minimal but real ANM bank with the given image counts."""
    import numpy as np

    from d5lib import anm

    f = anm.AnmFile([anm.AnmBlock(1)], [], [])
    for _ in range(textures):
        anm.add_texture(f, 32, 32, indexed=True)
    for i in range(palettes):
        pal = np.zeros((256, 4), np.uint8)
        pal[:, 3] = 255
        pal[0] = (i, 0, 0, 255)
        anm.add_palette(f, pal)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f.to_bytes())


BANK_REL = "files/Anime/ANM_HI_JP.dat/anm00533.lzs"


def _importer(installed_root, reference=True):
    """A D1C importer that is told where an installed pack may be read (the explicit --installed-reference route)."""
    from d5lib.importers import d1c
    imp = d1c.Importer()
    imp._ctx = dict(installed_root=installed_root, installed_reference=reference)
    return imp


def _d1c_pair(tmp_path, monkeypatch, built, installed):
    from d5lib.importers import d1c

    root = tmp_path / "installed-mods"
    folder = tmp_path / "mods" / "D1C_Unique_99999"
    bank = folder / BANK_REL
    _bank_file(bank, textures=built[0], palettes=built[1])
    if installed is not None:
        _bank_file(root / "D1C_Unique_99999" / BANK_REL,
                   textures=installed[0], palettes=installed[1])
    return _importer(root)._wheel_freeze(folder, [bank])


def test_d1c_wheel_freeze_passes_on_equal_counts(tmp_path, monkeypatch):
    ok, counts = _d1c_pair(tmp_path, monkeypatch, built=(2, 10), installed=(2, 10))
    assert ok is True
    assert counts["anm00533.lzs"]["same"] is True
    assert counts["anm00533.lzs"]["installed"] == counts["anm00533.lzs"]["built"] == (2, 10)


def test_d1c_wheel_freeze_fails_when_palettes_are_lost(tmp_path, monkeypatch):
    # the regression this gate exists for: 20 installed palettes, 10 rebuilt (34 unique banks)
    ok, counts = _d1c_pair(tmp_path, monkeypatch, built=(2, 10), installed=(2, 20))
    assert ok is False
    assert counts["anm00533.lzs"]["same"] is False
    assert counts["anm00533.lzs"]["delta"] == [0, -10]


def test_d1c_wheel_freeze_fails_when_textures_are_lost(tmp_path, monkeypatch):
    ok, counts = _d1c_pair(tmp_path, monkeypatch, built=(2, 10), installed=(3, 10))
    assert ok is False
    assert counts["anm00533.lzs"]["delta"] == [-1, 0]


def test_d1c_wheel_freeze_fails_when_images_are_added(tmp_path, monkeypatch):
    ok = _d1c_pair(tmp_path, monkeypatch, built=(3, 20), installed=(2, 10))[0]
    assert ok is False


def test_d1c_wheel_freeze_leaves_a_new_bank_alone(tmp_path, monkeypatch):
    ok, counts = _d1c_pair(tmp_path, monkeypatch, built=(2, 10), installed=None)
    assert ok is True and counts["anm00533.lzs"]["new"] is True


def _receiver_shape(tmp_path, monkeypatch, installed):
    from d5lib.importers import d1c
    root = tmp_path / "installed-mods"
    if installed is not None:
        _bank_file(root / "D1C_Unique_99999" / BANK_REL,
                   textures=installed[0], palettes=installed[1])
    return _importer(root)._receiver_shape("D1C_Unique_99999", 533)


def test_d1c_receiver_shape_reads_the_installed_bank(tmp_path, monkeypatch):
    # 2300's installed bank is one of the 34 that carry the graft's second palette group and extra page
    assert _receiver_shape(tmp_path, monkeypatch, (3, 20)) == (3, 20)
    assert _receiver_shape(tmp_path / "ten", monkeypatch, (2, 10)) == (2, 10)


def test_d1c_receiver_shape_is_none_for_a_new_entry(tmp_path, monkeypatch):
    # a pack with no installed copy builds naturally and has no installed reference to freeze against
    assert _receiver_shape(tmp_path, monkeypatch, None) is None


def _wheel_gate_pair(tmp_path, built, installed):
    mod, inst = tmp_path / "mod", tmp_path / "installed"
    _bank_file(mod / BANK_REL, textures=built[0], palettes=built[1])
    _bank_file(inst / BANK_REL, textures=installed[0], palettes=installed[1])
    return importcore.wheel_gate(mod, inst)


def test_shared_wheel_gate_requires_equal_counts(tmp_path):
    assert _wheel_gate_pair(tmp_path, (2, 10), (2, 10))[0] is True
    ok, why = _wheel_gate_pair(tmp_path / "a", (2, 10), (2, 20))
    assert ok is False and "10 palettes/2 textures" in why
    assert _wheel_gate_pair(tmp_path / "b", (2, 10), (3, 10))[0] is False
    assert _wheel_gate_pair(tmp_path / "c", (3, 20), (2, 10))[0] is False


def _approved_pair(tmp_path, built, installed, declared, monkeypatch):
    """ASAGI4P: a declared, owner-approved shape is the freeze reference for that member."""
    folder = next(k[0] for k in importcore.APPROVED_SHAPE_CHANGES)
    member = next(k[1] for k in importcore.APPROVED_SHAPE_CHANGES)
    monkeypatch.setitem(importcore.APPROVED_SHAPE_CHANGES, (folder, member), declared)
    mod, inst = tmp_path / "mod" / folder, tmp_path / "installed" / folder
    _bank_file(mod / "files" / member, textures=built[0], palettes=built[1])
    _bank_file(inst / "files" / member, textures=installed[0], palettes=installed[1])
    return importcore.wheel_gate(mod, inst)


_DECL4 = dict(textures=4, palettes=10, pages=((32, 32),) * 4, why="test declaration")


def test_wheel_gate_declared_shape_passes_and_is_named(tmp_path, monkeypatch):
    ok, why = _approved_pair(tmp_path, (4, 10), (3, 10), _DECL4, monkeypatch)
    assert ok is True
    assert why.startswith("declared shape change") and "test declaration" in why


def test_wheel_gate_declared_shape_is_still_equality(tmp_path, monkeypatch):
    ok, why = _approved_pair(tmp_path / "a", (5, 10), (3, 10), _DECL4, monkeypatch)
    assert ok is False and "declared 10/4" in why
    ok, why = _approved_pair(tmp_path / "b", (4, 9), (3, 10), _DECL4, monkeypatch)
    assert ok is False and "9 palettes/4 textures, declared 10/4" in why


def test_wheel_gate_declared_shape_checks_page_sizes(tmp_path, monkeypatch):
    decl = dict(_DECL4, pages=((32, 32), (32, 32), (32, 32), (16, 16)))
    ok, why = _approved_pair(tmp_path, (4, 10), (3, 10), decl, monkeypatch)
    assert ok is False and "page sizes" in why


def test_wheel_gate_undeclared_member_still_freezes_to_installed(tmp_path):
    # the declaration names one folder/member only: every other pack keeps the installed reference
    mod, inst = tmp_path / "mod" / "DRPG_Other", tmp_path / "installed" / "DRPG_Other"
    _bank_file(mod / "files" / "Anime/ANM_HI_JP.dat/anm16650.lzs", textures=4, palettes=10)
    _bank_file(inst / "files" / "Anime/ANM_HI_JP.dat/anm16650.lzs", textures=3, palettes=10)
    ok, why = importcore.wheel_gate(mod, inst)
    assert ok is False and "installed 10/3" in why


def test_pin_installed_icons_moves_only_shared_class_ids(tmp_path):
    """REPROFIX1 (d): the rebuilt pack takes the installed list-icon pair for class ids both declare."""
    import json
    for name, icons in (("mod", {"16640": [13173, 13990], "16650": [13174, 13991], "99": [1, 2]}),
                        ("inst", {"16640": [13427, 14244], "16650": [13428, 14245]})):
        f = tmp_path / name / "patches/outfits/outfits.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"icons": icons}))
    moved = importcore.pin_installed_icons(tmp_path / "mod", tmp_path / "inst")
    assert set(moved) == {"16640", "16650"}
    got = json.loads((tmp_path / "mod/patches/outfits/outfits.json").read_text())["icons"]
    assert got == {"16640": [13427, 14244], "16650": [13428, 14245], "99": [1, 2]}
    assert importcore.pin_installed_icons(tmp_path / "mod", tmp_path / "inst") == {}      # idempotent
    assert importcore.pin_installed_icons(tmp_path / "mod", tmp_path / "none") == {}


def test_record_importer_options_writes_mod_json(tmp_path):
    """REPROFIX1 (e): the options of the build go into source_import.importer_options."""
    import json
    (tmp_path / "mod.json").write_text(json.dumps({"name": "x", "source_import": {"source_game": "d1c"}}))
    rec = importcore.record_importer_options(tmp_path, "d1c", dict(source_voices=True, d1c_faces="opaque",
                                                                   d1_voice_source="/some/path"))
    doc = json.loads((tmp_path / "mod.json").read_text())
    assert doc["source_import"]["importer_options"] == rec
    assert rec == dict(source_voices=True, source_specials=False, d1c_faces="opaque",
                       d1c_hold_blank=False,                      # REPROFIX2: recorded like the other flags
                       entry="tools/import_game.py d1c")
    assert doc["source_import"]["source_game"] == "d1c"


def test_pin_installed_faces_copies_installed_and_keeps_rebuild_only(tmp_path):
    """REPROFIX1 (a): installed face pictures win; a face only the rebuild has stays."""
    for name, files in (("mod", {"patches/characters/face_1.png": b"new", "patches/characters/face_5.png": b"six"}),
                        ("inst", {"patches/characters/face_1.png": b"old", "patches/classes/face_1.png": b"cls"})):
        for rel, data in files.items():
            f = tmp_path / name / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
    got = importcore.pin_installed_faces(tmp_path / "mod", tmp_path / "inst")
    assert got == ["patches/characters/face_1.png", "patches/classes/face_1.png"]
    assert (tmp_path / "mod/patches/characters/face_1.png").read_bytes() == b"old"
    assert (tmp_path / "mod/patches/characters/face_5.png").read_bytes() == b"six"
    assert importcore.pin_installed_faces(tmp_path / "mod", tmp_path / "inst") == []
    assert importcore.pin_installed_faces(tmp_path / "mod", tmp_path / "none") == []
