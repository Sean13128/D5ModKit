"""The gate's member-local replay agrees with the actual grips finalizer."""
import importlib.util
from pathlib import Path

from d5lib import anm, grips

spec = importlib.util.spec_from_file_location('render_gate', Path(__file__).resolve().parents[1] / 'tools/striderlift_render_diff.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_grips_rest_replay_and_baseline_relative_gate():
    block = anm.AnmBlock(1)
    block.animations = [anm.Animation(21, 0), anm.Animation(2, 1), anm.Animation(3, 2)]
    block.nodes = [anm.Node(11, 0, 0, 0, 0, 0, 0, 1, -1, -1),
                   anm.Node(0, 0, 0, 0, 0, 0, 1, 1, -1, -1),
                   anm.Node(0, 0, 0, 0, 0, 0, -1, 0, -1, -1)]
    block.keys = [anm.Key(0, anm.NESTED | grips.SHOW, 0, 0, 0, 0),
                  anm.Key(0, anm.NESTED, 0, 0, 0, 3)]
    block.params = [2, 0, -1, 3, 0, -1]
    raw = anm.AnmFile([block], [], []).to_bytes()

    class Context:
        _outfit_own = {1000}
        outputs = {'anime/anm_hi_jp.dat/anm01000.lzs': True}
        def __init__(self):
            self.data = raw
        def get(self, path):
            return self.data
        def put(self, path, data):
            self.data = data
        def log(self, message):
            pass

    ctx = Context()
    grips._rest(ctx, {})
    actual = anm.load(ctx.data)
    replay_bytes = gate.replay_member(raw, 'grips')
    assert replay_bytes == ctx.data
    replay = anm.load(replay_bytes)
    assert gate.replay_member(raw, 'none') == raw
    assert actual.blocks[0].keys[0].flags & grips.HIDE
    assert not actual.blocks[0].keys[0].flags & grips.SHOW
    assert not anm.compare_structure(actual, replay)['structural_problems']
    replay.blocks[0].params[4] = -2
    assert anm.compare_structure(actual, replay)['structural_problems']
