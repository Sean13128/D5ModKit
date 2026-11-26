"""BLANKKEYS1: hold_blank_keys (a pose drawn on some key times is held on the blank ones), restore_timing (a fresh
rebuild takes the installed clock back), and the drawn-key measure ignores a 0x0 cell."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from d5lib import anm, ownanim
import blankkeys_scan


def _file(layer_keys, ctl=((0, 1), (40, 2)), other=None):
    """one animation 7001: root control + one picture layer; cells: 0 none, 1 real 8x8, 2 zero-size"""
    node = lambda first, count, child=-1, nxt=-1, id_=0: anm.Node(id_, 0, 0, 0, 0, 0, first, count, child, nxt)
    keys = [anm.Key(t, f, 0, 0, 0, 0) for t, f in ctl] + [anm.Key(t, 0, c, 3, 0, 0) for t, c in layer_keys]
    nodes = [node(0, len(ctl), child=1), node(len(ctl), len(layer_keys))]
    anims = [anm.Animation(7001, 0)]
    if other:                                   # a second animation sharing the picture layer (node 1)
        nodes.append(node(0, len(ctl), child=1))
        anims.append(anm.Animation(7011, 2))
    cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 8, 8, 0), anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0)]
    b = anm.AnmBlock(1, animations=anims, nodes=nodes, keys=keys, cells=cells)
    return anm.AnmFile([b], [], [])


def _drawn(fl):
    return blankkeys_scan.drawn_keys(anm, fl, 7001)


def test_still_on_one_key_is_held_on_every_key_time():
    fl = _file([(10, 1), (20, 0)], ctl=((0, 1), (30, 2)))          # drawn at 10 only; key 20 hides; time 0 and 30 have no layer key
    assert _drawn(fl)[0] < _drawn(fl)[1]
    assert ownanim.hold_blank_keys(fl, 7001) > 0
    assert _drawn(fl)[0] == _drawn(fl)[1], 'every key time draws now'


def test_nothing_drawn_or_all_drawn_is_left_alone():
    assert ownanim.hold_blank_keys(_file([(0, 0), (20, 0)]), 7001) == 0, 'nothing to hold: nothing invented'
    assert ownanim.hold_blank_keys(_file([(0, 1), (40, 1)]), 7001) == 0


def test_a_layer_shared_with_another_animation_is_not_touched():
    fl = _file([(10, 1), (20, 0)], ctl=((0, 1), (30, 2)), other=True)
    assert ownanim.hold_blank_keys(fl, 7001) == 0


def test_zero_size_cell_is_not_a_drawn_key():
    fl = _file([(0, 2), (10, 1)])
    assert _drawn(fl) == (2, 3), "time 0 holds a 0x0 cell (blank); 10 and 40 draw the real one"


def test_restore_timing_copies_the_old_clock_but_not_for_skipped_ids():
    old, fresh = _file([(0, 1), (20, 1)]), _file([(0, 1), (100, 1)], ctl=((0, 1), (200, 2)))
    done, left = ownanim.restore_timing(fresh, old)
    assert (done, left) == (1, {})
    assert [k.time for k in fresh.blocks[0].keys] == [0, 40, 0, 20]
    fresh2 = _file([(0, 1), (100, 1)], ctl=((0, 1), (200, 2)))
    assert ownanim.restore_timing(fresh2, old, skip=(7001,)) == (0, {})
    assert [k.time for k in fresh2.blocks[0].keys] == [0, 200, 0, 100]
