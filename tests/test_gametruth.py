"""GAMETRUTH1: the offline game-truth verifier (d5lib/gametruth.py).  Data tests skip without the local game."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from d5lib import gametruth as gt

SAVE = Path("/Volumes/Data/ai-tmp/claude/GAMETRUTH1B-20261110-1930/Save_001.sav")
HAVE_GAME = (gt.GAME / "disgaea5.exe").is_file() and (gt.GAME / "D5ModKit/mods").is_dir()


def test_texture_objects_marker_rule():
    assert gt.objects(SimpleNamespace(unk=1)) == 1
    assert gt.objects(SimpleNamespace(unk=0x10000)) == 256      # DD2WHEEL6: swapped marker -> 256 objects


@pytest.mark.skipif(not HAVE_GAME, reason="needs the local installed game")
def test_executed_graphics_id_and_board():
    w = gt.World(save=SAVE if SAVE.is_file() else None)
    assert w.gfx_id(1010, 0) == 1010                             # Warrior: graphics id = colour
    assert w.gfx_id(18160, 0) == 616                            # Ash: the Kit's graphics-id hook (clean exe: 610)
    if SAVE.is_file():
        listed = w.board()["listed"]
        assert listed and all(isinstance(i, int) for i in listed)


@pytest.mark.skipif(not HAVE_GAME, reason="needs the local installed game")
def test_pack_checks_can_fail():
    w = gt.World()
    r = gt.check_pack(w, w.mods / "D4_Unique_450")              # Ash: REALSURVEY1 saw page 3 blank
    by = {c.name: c.status for c in r.checks}
    assert by["status: innate evility"] == "FAIL"
    assert by["body: render root"] == "PASS"
    r = gt.check_pack(w, w.mods / "D4_Unique_450", resident_override=set())
    assert {c.name: c.status for c in r.checks}["body: monster placeholder"] == "PASS"   # humanoid: no N+2 needed


def test_unresolved_prerequisites_are_never_a_pass():
    """FIXUP1: VERIFIER-AUDIT1's three false-PASS controls (no game needed: stubbed inputs)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import game_truth_regress as gtr
    for label, check, expect, got in gtr.controls():
        assert got == expect, (label, check, expect, got)
