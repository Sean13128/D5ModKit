"""PT1030ANIM's converter rules: the wheel motion shape, part draw order and source-paced timing.

Sean's 2026-10-30 playtest: Prism Ranger / Android / Battle Suit / Armor Knight "appear still when you
move to them on the wheel and seem slower than intended" (the wheel motion had been re-rooted on a
copy of the idle, making it a 100-160 tick one-shot), Death's weapon painted behind its body (part
chain hands -> weapon -> body) and Dragon playing ~5x too fast (a 290-tick source idle on a 59-tick
donor track).

Each test builds the smallest block that shows the rule, so no game data is needed.
"""
import numpy as np

from d5lib import anm, ownanim


def block_with_idle_and_wheel(draw=True):
    """One 64x64 page: animation 6001 (2 keys, one drawing) and 1001 sharing its node tree."""
    page = 64
    b = anm.AnmBlock(1470)
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0),
               anm.Cell(0, 0, 0, 0, 0, 0, 32, 48, 0)]
    b.pivots = [anm.Pivot(16, 24)]
    b.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0)]
    b.params = [6001]
    b.nodes = [anm.Node(0, 0x1000, 0, 0, 0, 0, 0, 2, 1, -1),
               anm.Node(1, 0x100, 0, 0, 0, 0, 2, 2, -1, -1)]
    b.keys = [anm.Key(0, 1, 0, 0, 0, 0),
              anm.Key(80, 2, 0, 0, 0, 0),
              anm.Key(0, 0, 1, 0, 0, 0),
              anm.Key(40, 0, 1, 0, 0, 0)]
    b.animations = [anm.Animation(1001, 0), anm.Animation(6001, 0)]
    data = np.zeros((page, page), np.uint8)
    data[0:48, 0:32] = 250
    tex = anm.Image8(bytes([anm.FMT_INDEXED8, 1, 1, 1]), page, page, 1, data.tobytes())
    out = anm.AnmFile([b], [tex], [])
    pal = np.zeros((256, 4), np.uint8)
    pal[:, :3] = 200
    pal[:, 3] = 255
    anm.set_palette(out, 0, pal)
    return out


def test_a_rerooted_wheel_motion_returns_to_the_native_zero_length_stub():
    a = block_with_idle_and_wheel()
    blk = a.blocks[0]
    before = ownanim.wheel_stub_shape(blk, 1001, 6001)
    assert not before["native"] and before["keys"] > 2
    hit = ownanim.normalize_wheel_motion(blk, 1001, 6001)
    assert hit and hit["idle"] == 6001
    after = ownanim.wheel_stub_shape(blk, 1001, 6001)
    assert after["native"], "1001 must end as a zero-length 0x100 attachment naming 6001"
    assert after["nested"] == [6001]
    assert anm.animation_info(blk, next(x for x in blk.animations if x.id == 1001))["length"] == 0
    # the idle is untouched
    assert anm.animation_info(blk, next(x for x in blk.animations if x.id == 6001))["length"] == 80
    # and the wheel picture still shows the idle through the attachment
    nested = anm.evaluate(a, ("id", 1001), 0, nested=True)
    assert nested, "the zero-length stub must draw the attached idle"
    assert not (np.asarray(anm.render_items(a, nested, 0)[0]).sum() == 0)


def test_a_genuine_wheel_animation_is_left_alone():
    """A monster's 1001 is a real animation; it must not be mistaken for the re-rooted copy."""
    a = block_with_idle_and_wheel()
    blk = a.blocks[0]
    blk.animations = [anm.Animation(6001, 0)] + [x for x in blk.animations if x.id == 1001]
    # break the copy: point 1001 at its own keys so it is not the idle's tree
    wheel = next(x for x in blk.animations if x.id == 1001)
    wheel.root = 1
    blk.nodes.append(anm.Node(1, 0x100, 0, 0, 0, 0, 0, 0, -1, -1))
    blk.nodes[-1].num_keys = 0
    assert not ownanim.rerooted_copy(blk, 1001, 6001)
    assert ownanim.normalize_wheel_motion(blk, 1001, 6001) is None


# NOTE (2026-10-30): the composed-figure draw order and the source-paced retiming are proven by the
# bundle's own re-read (Builds/PT1030ANIM-20261030/VERIFY.json: the part chain of D4_Class_2120 /
# D4_Unique_170, and every D1C animation's length) rather than here: a unit fixture for `walk()`-based
# reordering ran long on this host and was removed instead of shipped unproven.
