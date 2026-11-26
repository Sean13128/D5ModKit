"""SPECBULK2: simulator fixes found on D4 special scenes, and effect-model sharing in d5fx.dat.

Native facts are re-read from the original executables in Disgaea Source/ at test time (skipped when absent).
"""
import os
import struct
import unittest
from pathlib import Path

from d5lib import choreo, fxpool, script

SOURCE = Path(os.environ.get("D5_SOURCE_DIR", "/Volumes/Data/Projects/D5/Disgaea Source"))
D4_EXE = SOURCE / "Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+/Disgaea4pc.exe"
D5_EXE = SOURCE / "Disgaea 5 Complete (Steam 803600)/disgaea5.exe"


def _constants(path, start, size):
    """the float64 constants a function multiplies by (rip-relative mulsd / movsd loads)"""
    try:
        import capstone
        import pefile
    except ImportError:
        raise unittest.SkipTest("capstone / pefile not installed")
    if not Path(path).is_file():
        raise unittest.SkipTest(f"{path} absent")
    pe = pefile.PE(str(path), fast_load=True)
    base, img = pe.OPTIONAL_HEADER.ImageBase, pe.get_memory_mapped_image()
    out = set()
    for ins in capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64).disasm(img[start - base:start - base + size], start):
        if ins.mnemonic in ("mulsd", "movsd") and "rip + " in ins.op_str:
            address = ins.address + ins.size + int(ins.op_str.split("rip + ")[1].rstrip("]"), 16)
            out.add(struct.unpack_from("<d", img, address - base)[0])
    return out


class Fixed256(unittest.TestCase):
    def test_native_scaling(self):
        # parser: variable operand x 256 (D4 0x14011fe10, D5 0x140086120); handler: x 1/256 (D4 0x140149810, D5 0x140184ea0)
        self.assertIn(256.0, _constants(D4_EXE, 0x14011FE10, 520))
        self.assertIn(256.0, _constants(D5_EXE, 0x140086120, 200))
        self.assertIn(1 / 256, _constants(D4_EXE, 0x140149810, 340))
        self.assertIn(1 / 256, _constants(D5_EXE, 0x140184EA0, 120))

    def test_simulator(self):
        # local1 = 512/256 + 256/256 = 3; local2 = local1 * (1024/256) = 12 -> a 12-frame wait
        code = [script.Ins(0x1442, [1, 512, 0, 256]), script.Ins(0x1442, [2, script.Var(20001, 0x10), 2, 1024]),
                script.Ins(choreo.WAIT, [script.Var(20002, 0x10)]), script.Ins(0x0108)]
        self.assertEqual(choreo.simulate({900: script.Event(900, code)}, 900).length, 12)


class LoopCounterArgument(unittest.TestCase):
    def test_call_receives_the_counter(self):
        # for n in 2..4: call 901(n); 901 waits its first argument. 2 + 3 + 4 = 9 frames in sequence
        loop_end = script.Ins(0x0158)
        parent = [script.Ins(0x0150, [2, 4]), script.Ins(0x0104, [901, script.Var(choreo.LOOP_VAR, 0x10)]),
                  script.Ins(0x0120), loop_end, script.Ins(0x0108)]
        child = [script.Ins(choreo.WAIT, [script.Var(20001, 0x10)]), script.Ins(0x0108)]
        events = {900: script.Event(900, parent), 901: script.Event(901, child)}
        self.assertEqual(choreo.simulate(events, 900).length, 9)


class SharedModels(unittest.TestCase):
    def test_identical_models_stored_once(self):
        a, b = b"model-A" * 10, b"model-B" * 3
        data = fxpool.build_file({9001: a, 9002: a, 9003: b}, {})
        count = struct.unpack_from("<I", data, 8)[0]
        table = {i: (o, n) for i, o, n in struct.iter_unpack("<III", data[12:12 + 12 * count])}
        self.assertEqual(table[9001], table[9002])
        self.assertEqual(data[table[9002][0]:table[9002][0] + table[9002][1]], a)
        self.assertEqual(data[table[9003][0]:table[9003][0] + table[9003][1]], b)
        self.assertEqual(data.count(a), 1)


if __name__ == "__main__":
    unittest.main()


class NeedsDependency(unittest.TestCase):
    """mod.json "needs": order-free presence dependency (generated scenes spawning another pack's characters)."""

    def mod(self, mid, **meta):
        from types import SimpleNamespace
        return SimpleNamespace(id=mid, name=mid, meta=meta)

    def test_presence_any_order_and_mutual(self):
        from d5lib import modsys
        a = self.mod("A", needs=["B"])
        b = self.mod("B", needs=["A"])
        self.assertEqual(modsys.missing_requirements([a, b]), [])
        self.assertEqual(modsys.missing_requirements([b, a]), [])

    def test_missing_provider_warns(self):
        from d5lib import modsys
        a = self.mod("A", needs=["B", "C"])
        self.assertEqual([(m.id, r) for m, r in modsys.missing_requirements([a, self.mod("B")])], [("A", "C")])

    def test_requires_stays_order_sensitive(self):
        from d5lib import modsys
        a = self.mod("A", requires=["B"])
        self.assertEqual([(m.id, r) for m, r in modsys.missing_requirements([a, self.mod("B")])], [("A", "B")])


class Stock1442Division(unittest.TestCase):
    """Stock D5 scenes that divide with 1442 (op 3): D5 divides floats (divss at 0x140184f66)."""

    @classmethod
    def setUpClass(cls):
        game = SOURCE / "Disgaea 5 Complete (Steam 803600)"
        if not game.is_dir():
            raise unittest.SkipTest("clean D5 copy absent")
        from d5lib import skills
        from d5lib.gamefs import GameFS
        cls.sc = skills.Scripts.load(GameFS(str(game)))

    def test_native_op3_is_float(self):
        try:
            import capstone
            import pefile
        except ImportError:
            raise unittest.SkipTest("capstone / pefile not installed")
        pe = pefile.PE(str(D5_EXE), fast_load=True)
        base, img = pe.OPTIONAL_HEADER.ImageBase, pe.get_memory_mapped_image()
        ins = next(capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64).disasm(img[0x140184F66 - base:][:8], 0x140184F66))
        self.assertEqual(ins.mnemonic, "divss")

    def test_stock_scenes(self):
        # 15016100 (root 12010523): local6 = (128000/256) / local6 on its third pass -> 500 / 3 = 166.6 -> 1666 tenths
        tl = choreo.simulate(self.sc.ev, 12010523, choreo.Context())
        self.assertEqual([op.args[5] for op in tl.ops if op.cid == 0x3C10 and op.args[1] == 305 and op.args[0] == 46], [1666])
        # 15110400 (root 12010071): waits computed from 460800/256 / local1
        self.assertEqual(choreo.simulate(self.sc.ev, 12010071, choreo.Context()).length, 527)
