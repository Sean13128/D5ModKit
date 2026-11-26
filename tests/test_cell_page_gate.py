"""D4CELL1: the D4 humanoid merge zeroes shared cells on pages the body lacks; importcore gates on it."""
from pathlib import Path

import pytest

from d5lib import anm, importcore
from tools import animall2_tracks

BANK = "files/Anime/ANM_HI_JP.dat/anm00376.lzs"


def _file(block_id, pages, cells, anim_id):
    f = anm.AnmFile([anm.AnmBlock(block_id)], [], [])
    for _ in range(pages):
        anm.add_texture(f, 32, 32, indexed=True)
    b = f.blocks[0]
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0)] + [anm.Cell(t, 0, 0, 0, 0, 0, 8, 8, 0) for t in cells]
    b.nodes = [anm.Node(1, 0x100, 0, 0, 0, 0, 0, len(cells), -1, -1)]
    b.keys = [anm.Key(i, 0, i + 1, 0, 0, 0) for i in range(len(cells))]
    b.animations = [anm.Animation(anim_id, 0)]
    return f


def _merged(blank=True, monkeypatch=None):
    body = _file(376, 1, [0], 1)                 # a one-page D4 body
    shared = _file(1, 0, [0, 3], 14)             # D4's shared block: one cell on page 0, one on page 3
    if not blank:
        monkeypatch.setattr(animall2_tracks, "blank_off_page", lambda cells, textures: 0)
    return animall2_tracks.build(body, shared, bank_id=376)


def _mod(tmp_path, bank):
    mod = tmp_path / "D4_Unique_310"
    (mod / BANK).parent.mkdir(parents=True)
    (mod / BANK).write_bytes(bank.to_bytes())
    return mod


def test_merge_zeroes_the_off_page_shared_cell(tmp_path):
    a = _merged()
    cells = a.blocks[0].cells
    assert (cells[2].w, cells[2].h, cells[2].tex) == (0, 0, 0)          # was page 3 of a 1-page body
    assert (cells[1].w, cells[1].tex) == (8, 0) and cells[4].w == 8      # on-page shared + own cells kept
    assert importcore.cell_page_gate(_mod(tmp_path, a)) == (True, "")


def test_gate_fails_on_the_old_merge(tmp_path, monkeypatch):
    ok, why = importcore.cell_page_gate(_mod(tmp_path, _merged(False, monkeypatch)))
    assert not ok and "anm00376.lzs block 376: 1 key-drawn cell(s) on a page past its 1" in why


D4FIX4 = Path("/Volumes/Data/Projects/D5/Builds/D4-FIX4-20261109/d4/mods/D4_Unique_310")


@pytest.mark.skipif(not D4FIX4.is_dir(), reason="D4-FIX4 build not on this machine")
def test_gate_fails_on_the_d4fix4_builder_output():
    ok, why = importcore.cell_page_gate(D4FIX4)
    assert not ok and "144 key-drawn cell(s) on a page past its 9" in why


def test_dd2_baseline_blanks_cells_on_missing_pages(tmp_path):
    """DD2-FIX1.7: the DD2 final bank pass zeroes cells past the bank's pages, so the gate passes."""
    from d5lib.importers._dd2_baseline import blank_missing_pages
    bank = _file(1550, 2, [0, 5], 1)             # one cell on page 0, one on page 5 of a 2-page bank
    assert importcore.cell_page_gate(_mod(tmp_path, bank))[0] is False
    assert blank_missing_pages(bank) == 1
    assert importcore.cell_page_gate(_mod(tmp_path / "after", bank)) == (True, "")
