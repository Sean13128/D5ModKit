"""D4-FIX2: a donor-only attachment aliased to a drawn 1501 gets an empty animation (ANIMALL's Death rule)."""
from d5lib import anm
from tools.animall2_convert import alias_root


def block(drawn):
    b = anm.AnmBlock(2330)
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 32, 48, 0)]
    b.nodes = [anm.Node(0, 0x1000, 0, 0, 0, 0, 0, 1, -1, -1)]
    b.keys = [anm.Key(0, 0, 1 if drawn else 0, 0, 0, 0)]
    b.animations = [anm.Animation(1501, 0)]
    return b


def test_drawn_stand_in_gives_an_empty_attachment():
    b = block(drawn=True)
    root, rule = alias_root(b, 1501, 'blank-attachment')
    assert rule == 'empty-attachment' and root == 1
    assert b.nodes[root].num_keys == 0 and b.nodes[root].first_key == -1


def test_blank_stand_in_is_shared_as_before():
    b = block(drawn=False)
    assert alias_root(b, 1501, 'blank-attachment') == (0, 'blank-attachment')
    assert len(b.nodes) == 1
