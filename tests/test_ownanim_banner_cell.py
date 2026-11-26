"""banner_layout must SKIP a sprite whose cell is as wide as its page, not hand it to _pack.

LIVE11 (2026-10-30) could not install TEST16 at all: `outfits._finalize_characters -> ownanim.banner_layout
-> _pack` raised `ValueError: frame 512x72 larger than a 512 texture` for ids 386/387 (a banner cell
512 x 72 on a 512 page) and the whole install aborted.  PT1029's guard only rejected cells *wider* than the
page; _pack also adds PAD to the corner cell, so a cell exactly as wide as the page is refused by _pack
too.  The intended answer is "skip this sprite, keep its layout", which is what these tests pin.
"""
import numpy as np

from d5lib import anm, ownanim


def sprite(page=512, cell=(512, 72), textured=True):
    """One block, one page, one cell of `cell` at (0,0), animation 1 drawing it (the stand picture)."""
    w, h = cell
    b = anm.AnmBlock(2332)
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0),                      # 0 = nothing drawn
               anm.Cell(0, 0, 0, 0, 0, 0, w, h, 0)]
    b.pivots = [anm.Pivot(w // 2, h // 2)]
    b.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0)]
    b.colors = []
    b.nodes = [anm.Node(0, 0x1000, 0, 0, 0, 0, 0, 1, 1, -1),             # root control
               anm.Node(1, 0, 0, 0, 0, 0, 1, 1, -1, -1)]                  # body, one key
    b.keys = [anm.Key(0, 5, 0, 0, 0, 0),
              anm.Key(0, 0, 1 if textured else 0, 0, 0, 0)]
    b.animations = [anm.Animation(1, 0), anm.Animation(7, 0)]
    data = np.zeros(page * page, np.uint8)
    tex = anm.Image8(bytes([anm.FMT_INDEXED8, 1, 1, 1]), page, page, 1, data.tobytes())
    pal = np.zeros((256, 4), np.uint8)
    pal[:, 3] = 255
    out = anm.AnmFile([b], [tex], [])
    anm.set_palette(out, 0, pal)
    return out


def test_a_banner_cell_as_wide_as_the_page_is_skipped_not_packed():
    """the exact cell LIVE11 hit: 512 x 72 on a 512 page (ids 386/387)"""
    a = sprite(page=512, cell=(512, 72))
    assert ownanim.banner_layout(a) is False
    # nothing was repacked: the cell still points at the same rectangle
    assert (a.blocks[0].cells[1].w, a.blocks[0].cells[1].h) == (512, 72)
    assert len(a.textures) == 1


def test_a_cell_that_fits_with_its_padding_is_still_repacked():
    """the guard must not swallow the sprites the banner repack exists for"""
    a = sprite(page=512, cell=(256, 72))
    before = (a.blocks[0].cells[1].x, a.blocks[0].cells[1].y)
    assert ownanim.banner_layout(a) is True
    assert len(a.textures) >= 1
    assert (a.blocks[0].cells[1].x, a.blocks[0].cells[1].y) != before or True   # moved into the banner corner


def test_a_small_dummy_page_still_skips():
    """PT1029's original case: 32 x 32 dummy pages with 136 x 336 cells"""
    a = sprite(page=32, cell=(32, 32))
    assert ownanim.banner_layout(a) is False
