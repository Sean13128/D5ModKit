"""tools/anm_twin.py on banks built in code (no game data): per-motion diff, missing motions, novel values."""
import copy
import importlib.util
import unittest
from pathlib import Path

from d5lib import anm

spec = importlib.util.spec_from_file_location("anm_twin", Path(__file__).resolve().parents[1] / "tools/anm_twin.py")
twin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(twin)


def block():
    """Motions 1 and 1021: control root -> one layer drawing cell 1 (depth group 80) for two keys."""
    return anm.AnmBlock(
        id=10,
        animations=[anm.Animation(1, 0), anm.Animation(1021, 0)],
        nodes=[anm.Node(0, 0, 0, 0, 0, 0, 0, 2, 1, -1), anm.Node(1, 0x100, 0, 0, 0, 0, 2, 2, -1, -1)],
        keys=[anm.Key(0, 1, 0, 0, 0, -1), anm.Key(20, 2, 0, 0, 0, -1),
              anm.Key(0, 0, 1, 0, 0, -1), anm.Key(10, 0, 1, 0, 0, -1)],
        cells=[anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 8, 8, 80)],
        transforms=[anm.Transform(0, 0, 0, 0, 100, 100, 0)], pivots=[anm.Pivot(0, 0)])


class TwinTests(unittest.TestCase):
    def test_diff_missing_and_novel(self):
        native = block()
        imported = copy.deepcopy(native)
        imported.animations = imported.animations[:1]           # 1021 missing
        imported.cells[1].unk8 = 0                              # depth group dropped
        imported.keys[2].flags = 5                              # layer key: a value no native bank stores
        c = twin.compare(twin.motions([native]), twin.motions([imported]))
        self.assertEqual(c["native_only"], [1021])
        self.assertEqual(c["diffs"][1]["depth_group"], [[80], [0]])
        self.assertEqual(c["diffs"][1]["interp"], [[0], [0, 5]])
        self.assertEqual(c["score"], 2 / 1 + 1)
        corpus = {k: {str(x): n for x, n in v.items()} for k, v in twin.values([native]).items()}
        self.assertEqual(twin.novel(twin.values([imported]), corpus)["key +2 layer"], {5: [1, None]})

    def test_named_node_reads_as_one_word(self):
        p = twin.motions([block()])[1]
        self.assertEqual(p["named"], [1])        # id 1, flags 0x100: asset id 1, binding nibble 1
        self.assertEqual(p["binding"], [1])
        self.assertEqual((p["nodes"], p["keys"], p["length"], p["control"]), (2, 4, 20, [1, 2]))


if __name__ == "__main__":
    unittest.main()
