"""FIXUP1: build validation runs on disposable clones; the Zed case (icons written back into the staged outfits.json)."""
import json
from types import SimpleNamespace

import pytest

from d5lib import modsys, outfits, stagecheck


def _zed(root):
    d = root / "DRPG_Core_Zed_94"
    (d / "patches/outfits").mkdir(parents=True)
    (d / "mod.json").write_text(json.dumps({"name": "Zed"}))
    (d / "patches/outfits/outfits.json").write_text(json.dumps({"icons": {"14940": [13363, 14180]}}))
    return d


def _fake_build(fs, mods, log=None):
    """what modsys.build's outfit finalizer does to its input Mods"""
    ctx = SimpleNamespace(_icon_cells={14940: (13173, 13990)}, _outfit_colour_mods={14940: mods[-1]}, log=lambda *a: None)
    outfits._declare_icon_cells(ctx, {14940})


def test_build_check_leaves_the_stage_alone_and_production_still_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(modsys, "build", _fake_build)
    stage = _zed(tmp_path)
    receipt = {"packs": [{"folder": stage.name, "staged_sha256": stagecheck.tree_hashes(stage)}]}
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods" / stage.name).symlink_to(stage)
    (tmp_path / "STAGE-RECEIPT.json").write_text(json.dumps(receipt))
    stagecheck.build_check(None, [stage])
    assert stagecheck.verify_stage(tmp_path) == []
    assert json.loads((stage / "patches/outfits/outfits.json").read_text())["icons"]["14940"] == [13363, 14180]
    _fake_build(None, [modsys.Mod(str(stage))])          # production build: the claim is recorded in the pack
    assert json.loads((stage / "patches/outfits/outfits.json").read_text())["icons"]["14940"] == [13173, 13990]
    assert stagecheck.verify_stage(tmp_path) == ["DRPG_Core_Zed_94/patches/outfits/outfits.json"]


def test_a_validation_that_writes_into_its_input_is_caught(tmp_path, monkeypatch):
    stage = _zed(tmp_path)
    monkeypatch.setattr(modsys, "build", lambda fs, mods, log=None: None)
    monkeypatch.setattr(stagecheck.shutil, "rmtree", lambda *a, **k: None)
    orig = stagecheck.subprocess.run
    def sneaky(cmd, **kw):                                  # the "clone" aliases the input: a writer would hit it
        (stage / "x.txt").write_text("changed")
        return orig(cmd, **kw)
    monkeypatch.setattr(stagecheck.subprocess, "run", sneaky)
    with pytest.raises(RuntimeError, match="wrote into its input"):
        stagecheck.build_check(None, [stage], work=str(tmp_path))
