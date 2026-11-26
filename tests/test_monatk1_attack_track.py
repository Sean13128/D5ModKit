"""MONATK1: a monster's attack keeps its donor clock, shows every chosen source frame from tick 0, and a merged
monster block (no cells yet: cell 0 means 'no cell') still draws its first key."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import anm, ownanim


def _block():
    node = lambda id_, first, count, child=-1, nxt=-1: anm.Node(id_, 0, 0, 0, 0, 0, first, count, child, nxt)
    key = lambda t, flags=0, cell=0: anm.Key(t, flags, cell, 0, 0, 0)
    # root control 0..44, one body layer with a single drawn key (the effect-driven donor), base cell in base.cells (-1)
    return anm.AnmBlock(2170, animations=[anm.Animation(2071, 0)],
                        nodes=[node(0, 0, 2, child=1), node(0, 2, 1)],
                        keys=[key(0, 1), key(44, 2), key(26, cell=-1)],
                        cells=[])


def test_attack_tracks_scale_onto_donor_length_and_spread():
    b = _block()
    t = ownanim.attack_tracks(b, {'attack_fist_front': [0, 10, 20, 30, 40]}, aids=(2071,))
    assert t[2071]['keys'] == [(0, 0), (11, 1), (22, 2), (33, 3), (44, 4)]       # source moments on the donor's 44 ticks
    assert t[2071]['control'] == [(0, 1), (44, 2)]
    few = ownanim.attack_tracks(b, {'attack_fist_front': list(range(0, 50, 10))}, aids=(2071,), max_frames=3)
    assert [n for _, n in few[2071]['keys']] == [0, 2, 4], 'an even spread keeps both ends'
    assert ownanim.attack_tracks(b, {}, aids=(2071,)) == {}, 'no source times: nothing invented'
    assert ownanim.attack_tracks(b, {'attack_fist_front': [0, 4]}, aids=(2077,)) == {}, 'animation absent: left out'


def test_first_key_of_an_empty_cell_table_is_drawn():
    b = _block()
    base_cell = anm.Cell(0, 0, 0, 0, 0, 0, 8, 8, 0)
    src_cell = lambda c: base_cell if c < 0 else None
    b.keys[2].cell = -1
    frames = [dict(rgba=np.zeros((8, 8, 4), np.uint8), row='attack_fist', view='front') for _ in range(2)]
    matches = {-1: dict(frame=0, dx=0, dy=0)}
    track = dict(row='attack_fist', keys=[(0, 0), (30, 1)], control=[(0, 1), (44, 2)])
    ownanim._bind_source_tracks(b, frames, matches, {2071: track}, src_cell)
    drawn = [(k.time, k.cell) for i, _, _ in b.walk(0) for k in b.node_keys(b.nodes[i]) if k.cell]
    assert [t for t, _ in drawn] == [0, 30] and all(c > 0 for _, c in drawn)
