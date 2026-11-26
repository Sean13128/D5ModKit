"""DD2LEN1: an own animation (6001 ...) takes the source's clock, not the donor template's 71 frames."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import anm, ownanim


def test_source_track_replaces_the_donor_clock():
    node = lambda id_, first, count, child=-1, nxt=-1: anm.Node(id_, 0, 0, 0, 0, 0, first, count, child, nxt)
    key = lambda t, flags=0, cell=0: anm.Key(t, flags, cell, 0, 0, 0)
    b = anm.AnmBlock(1080, animations=[anm.Animation(6001, 0)],
                     nodes=[node(0, 0, 2, child=1), node(0, 2, 3, nxt=2), node(0, 5, 1)],
                     keys=[key(0, 1), key(71, 2), key(0, cell=1), key(12, cell=2), key(60, cell=3), key(0, cell=1)],
                     cells=[anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0)] + [anm.Cell(0, 0, 0, 0, 0, 0, 8, 8, 0)] * 3)
    frames = [dict(rgba=np.zeros((8, 8, 4), np.uint8), row='wait', view='front') for _ in range(3)]
    matches = {c: dict(frame=c - 1, dx=0, dy=0) for c in (1, 2, 3)}
    src_cell = lambda c: b.cells[c] if 0 < c < len(b.cells) else None
    track = dict(row='wait', keys=[(0, 0), (12, 2), (24, 1), (36, 2)], control=[(0, 1), (59, 2)])
    receipt = ownanim._bind_source_tracks(b, frames, matches, {6001: track}, src_cell)
    info = anm.animation_info(b, b.animations[0])
    assert info['length'] == 59 and info['control'] == [(0, 1), (59, 2)]
    drawn = [(k.time, matches[k.cell]['frame']) for i, _, _ in b.walk(0) for k in b.node_keys(b.nodes[i]) if k.cell]
    assert drawn == [(0, 0), (12, 2), (24, 1), (36, 2)], 'one key per source moment, showing its frame'
    assert receipt[0]['emptied_layers'] == [2], 'the second body layer would be hidden by whole-body anyway'
