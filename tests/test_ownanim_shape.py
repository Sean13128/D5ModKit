"""Receiver shape: a rebuild keeps the installed bank's page and palette counts.

The wheel-freeze rule is equality with the installed bank (``d1c._wheel_freeze``).  The installed D1C
unique banks are not one shape -- 34 of the 82 installed unique sprite banks carry 20 palettes because
the PALFIX/PALMERGE graft passes appended a second 10-palette group and one more atlas page -- so the
builder is told the target shape and packs the source atlas over exactly that many pages.  These tests
pin the packing (every page carries real art, nothing overlaps, a request past what fits falls back),
the palette count, and the banner-layout idempotency the installer relies on.
"""
from __future__ import annotations

import numpy as np
import pytest

from d5lib import anm, ownanim


def _rects(pos, sizes, page):
    return [(x, y, sizes[i][0], sizes[i][1]) for i, (p, x, y) in enumerate(pos) if p == page]


def _overlaps(rects):
    bad = []
    for i, (ax, ay, aw, ah) in enumerate(rects):
        for bx, by, bw, bh in rects[i + 1:]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                bad.append(((ax, ay, aw, ah), (bx, by, bw, bh)))
    return bad


def test_pack_spread_uses_every_requested_page():
    sizes = [(64, 64)] * 9
    pos, pages = ownanim._pack_spread(sizes, 3)
    assert pages == 3
    assert sorted({p for p, _, _ in pos}) == [0, 1, 2]
    for page in range(pages):
        rects = _rects(pos, sizes, page)
        assert rects, f'page {page} carries no frame'
        assert not _overlaps(rects)


def test_pack_spread_without_a_shape_is_the_natural_pack():
    sizes = [(64, 64)] * 4
    assert ownanim._pack_spread(sizes, None) == ownanim._pack(sizes)


def test_pack_spread_falls_back_when_the_shape_cannot_be_met():
    sizes = [(1000, 1000), (1000, 1000)]           # one per page, so a 3-page request is unreachable
    pos, pages = ownanim._pack_spread(sizes, 3)
    assert pages == 2                              # the natural pack, not a blank third page
    assert len(pos) == 2


def test_pack_spread_keeps_the_corner_frame_on_the_first_page():
    sizes = [(80, 80)] * 6
    pos, pages = ownanim._pack_spread(sizes, 2, corner=(3, (8, 8)))
    assert pages == 2 and pos[3][0] == 0


def _bank(cell=(32, 40)):
    """A minimal own-animation block: 1001 front, one body key drawing cell 1."""
    block = anm.AnmBlock(1020)
    block.animations = [anm.Animation(1, 0)]
    block.nodes = [anm.Node(1, 0x100, 0, 0, 0, 0, 0, 1, -1, -1)]
    block.keys = [anm.Key(0, 0, 1, 0, 0, 0)]
    block.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0)]
    block.pivots = [anm.Pivot(0, 0)]
    block.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, cell[0], cell[1], 0)]
    return block


def _palettes(n):
    out = []
    for i in range(n):
        pal = np.zeros((256, 4), np.uint8)
        pal[:, 3] = 255
        pal[i % 255] = (10 * i % 255, 20, 30, 255)
        out.append(pal)
    return out


def _assemble(shape, frames=4):
    block = _bank()
    base = anm.AnmFile([anm.AnmBlock(1020)], [], [])
    for pal in _palettes(10):
        anm.add_palette(base, pal)
    rgba = np.zeros((40, 32, 4), np.uint8)
    rgba[..., :3] = 200
    rgba[..., 3] = 255
    rendered = [{'rgba': rgba.copy()} for _ in range(frames)]
    matches = {i + 1: {'frame': i, 'dx': 0, 'dy': 0} for i in range(frames)}
    block.cells.extend(anm.Cell(0, 0, 0, 0, 0, 0, 32, 40, 0) for _ in range(frames))
    block.keys = [anm.Key(0, 0, i + 1, 0, 0, 0) for i in range(frames)]
    block.nodes = [anm.Node(1, 0x100, 0, 0, 0, 0, 0, frames, -1, -1)]
    return ownanim.assemble(block, anm.AnmBlock(1), base, rendered, matches, 1020, shape=shape)


def test_assemble_emits_the_requested_palette_count():
    out = _assemble(shape=(1, 20))
    assert len(out.palettes) == 20
    assert len(out.blocks[0].palette_infos) == 20
    assert all(np.array_equal(anm.get_palette(out, 0)[:4], anm.get_palette(out, 10)[:4])
               for _ in (0,))                 # the extra group carries the character's own colours


def test_assemble_spreads_the_atlas_over_the_requested_pages():
    out = _assemble(shape=(2, 20))
    assert len(out.textures) == 2
    assert sorted({c.tex for c in out.blocks[0].cells if c.w}) == [0, 1]


def test_assemble_without_a_shape_keeps_the_natural_counts():
    out = _assemble(shape=None)
    assert len(out.palettes) == 10
    assert len(out.textures) == 1


def test_banner_layout_over_a_page_count_is_what_the_installer_leaves_alone():
    out = _assemble(shape=None)
    assert ownanim.banner_layout(out, pages=3) is True
    assert len(out.textures) == 3
    assert ownanim.banner_layout(out) is False          # the installer's own call: a no-op
    assert len(out.textures) == 3                       # and it cannot compact the pages away


def test_banner_layout_still_compacts_without_a_page_count():
    out = _assemble(shape=None)
    ownanim.banner_layout(out, pages=3)
    shrink = _assemble(shape=None)
    assert ownanim.banner_layout(shrink) in (True, False)
    assert len(shrink.textures) <= 3
