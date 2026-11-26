"""The second way the whole figure gets drawn twice: a part item that paints no new ink.

DEATH2 (2026-10-30).  Death (D4) motion 1001 draws three items -- body 192x184, scythe 192x176, hands
136x64.  100% of the hands item's opaque pixels land inside the body item and 75-100% of them are
byte-identical at the same place, so it draws nothing the body does not already draw; on the Recruiter
wheel (motion 1001 at the game's 1.0117 unit scale) the duplicated antialiased edges are blended twice and
the copy reads as a small second reaper over the main one.  SPRITE3's rule cannot see this: no 0x100 key is
involved.

The rule: blank a part item when (a) it is at least 20% of a bigger item's screen area -- the humanoid hand
overlays that legitimately sit on the body are 3-4% -- (b) >=99% of its opaque pixels are covered by that
item and (c) >=70% of them are byte-identical there.
"""
import numpy as np

from d5lib import anm, ownanim

WHITE = 250
GREY = 40


def sprite(body=40, part=24, part_fill=WHITE):
    """One block, one 64x64 page: a solid body square, plus a part square drawn inside it."""
    page = 64
    b = anm.AnmBlock(2120)
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0),
               anm.Cell(0, 0, 0, 0, 0, 0, body, body, 0),
               anm.Cell(0, 0, 0, 0, 40, 40, part, part, 0)]
    data = np.zeros((page, page), np.uint8)
    data[0:body, 0:body] = WHITE
    data[40:40 + part, 40:40 + part] = part_fill
    b.pivots = [anm.Pivot(body // 2, body // 2), anm.Pivot(part // 2, part // 2)]
    # both items centred on the same point: the part lands inside the body
    b.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0),
                    anm.Transform(0, 0, 1, 0, 100, 100, 0)]
    b.nodes = [anm.Node(0, 0x1000, 0, 0, 0, 0, 0, 1, 1, -1),
               anm.Node(0, 0, 0, 0, 0, 0, 1, 1, -1, 2),
               anm.Node(0, 0, 0, 0, 0, 0, 2, 1, -1, -1)]
    b.keys = [anm.Key(0, 5, 0, 0, 0, 0),
              anm.Key(0, 0, 1, 0, 0, 0),
              anm.Key(0, 0, 2, 1, 0, 0)]
    b.animations = [anm.Animation(1001, 0)]
    pal = np.zeros((256, 4), np.uint8)
    for v in range(256):
        pal[v] = (v, v, v, 255)
    tex = anm.Image8(bytes([anm.FMT_INDEXED8, 1, 1, 1]), page, page, 1, data.tobytes())
    out = anm.AnmFile([b], [tex], [])
    anm.set_palette(out, 0, pal)
    return out


def test_a_part_that_paints_no_new_ink_is_blanked_and_the_picture_does_not_change():
    a = sprite()
    before, _ = anm.render_items(a, anm.evaluate(a, ("id", 1001), 0), scale=1.0)
    receipt = ownanim.duplicate_items(a)
    assert receipt, "the duplicate part must be found"
    assert a.blocks[0].keys[2].cell == 0, "the part key must be blanked, not deleted"
    after, _ = anm.render_items(a, anm.evaluate(a, ("id", 1001), 0), scale=1.0)
    assert before.size == after.size
    assert not (np.asarray(before) != np.asarray(after)).any(), "blanking must not change the picture"


def test_a_part_with_its_own_picture_is_left_alone():
    a = sprite(part_fill=GREY)
    assert ownanim.duplicate_items(a) == []
    assert a.blocks[0].keys[2].cell == 2


def test_a_small_hand_overlay_is_left_alone():
    """40x40 body with a 16x16 part: 16% of the area, the band the humanoid hand overlays live in"""
    a = sprite(body=40, part=16)
    assert ownanim.duplicate_items(a) == []
    assert a.blocks[0].keys[2].cell == 2
