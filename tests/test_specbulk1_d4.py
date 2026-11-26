"""SPECBULK1: shared D4 special-attack conversion rules, checked on the original game files at test time.

Nothing from the games is stored here: every test reads Disgaea Source/ (D4 Complete+ Steam EN, clean D5 Steam) and
skips when it is absent. Addresses are code locations in the pinned executables, not game data.
"""
import hashlib
import os
import struct
import unittest
from pathlib import Path

from d5lib import choreo, d4effects, d4inventory, lzs, obf, script

SOURCE = Path(os.environ.get("D5_SOURCE_DIR", "/Volumes/Data/Projects/D5/Disgaea Source"))
D4_ROOT = SOURCE / "Disgaea 4 Complete+ (Steam 1233880)/Disgaea 4 Complete+"
D4_EXE = D4_ROOT / "Disgaea4pc.exe"
D4_EXE_SHA256 = "2436d4b39aff4291dee71b65055a11161e7ec9186ff98cc2deebc4411614c765"
D4_DATA = D4_ROOT / "Data/DATA/EN"
D5_EXE = SOURCE / "Disgaea 5 Complete (Steam 803600)/disgaea5.exe"

# D4 command -> its registered vtable (native registration trace, Research/d4-expansion-20261018 native-v1).
# Entry 4 of each vtable parses the command's operands.
VTABLES = {
    0x4600: 0x140640510, 0x4602: 0x14063F8E0, 0x4604: 0x14063F910, 0x4606: 0x14063F910, 0x460A: 0x140640510,
    0x460C: 0x140640510, 0x4630: 0x14063F400, 0x641C: 0x14063FC10, 0x64A0: 0x14063FD30, 0x2816: 0x140640690,
    0x2817: 0x1406406C0, 0x32E0: 0x1406404B0, 0x3710: 0x140640630, 0x3711: 0x140640630, 0x6419: 0x14063FC40,
    0x64F0: 0x14063FD60, 0x6B00: 0x14063F310, 0x6B02: 0x14063F160, 0x6B05: 0x14063F460, 0x6B07: 0x14063F460,
    0x6B0A: 0x14063F160, 0x6B0C: 0x14063F460, 0x6B0F: 0x140640450, 0x72D2: 0x1406407B0, 0x7897: 0x140640330,
    0x789A: 0x1406404B0, 0x78B4: 0x1406404B0, 0x78B9: 0x1406404B0, 0x78C0: 0x1406404B0, 0x78D0: 0x140640510,
    # rows that were already in D4_SIGNATURES: the method must reproduce them too
    0x4620: 0x140640660, 0x7220: 0x14063F010, 0x7228: 0x14063F910, 0x646A: 0x140640540,
}
# events of adapted D4 special-attack scenes that did not decode with the D5 widths (SPECBULK1 census)
DESYNCED_EVENTS = (12000092, 15020107, 15036200, 15046300, 15046743, 15056000, 15080800, 15082900, 15082950,
                   15083200, 15083250, 15200800, 15253600, 15362300, 15362700, 15370200, 16061150, 16061400,
                   16100100)


def _need(*paths):
    missing = [str(p) for p in paths if not Path(p).is_file()]
    if missing:
        raise unittest.SkipTest(f"source files absent: {missing}")


def _image(path):
    try:
        import pefile
    except ImportError:
        raise unittest.SkipTest("pefile not installed")
    pe = pefile.PE(str(path), fast_load=True)
    return pe.OPTIONAL_HEADER.ImageBase, pe.get_memory_mapped_image()


def _operand_widths(base, img, parser):
    """Run one D4 operand parser over a literal-only operand stream and read the widths from its memory reads."""
    try:
        from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_MODE_64, Uc, UcError
        from unicorn.x86_const import UC_X86_REG_R8, UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_RSP
    except ImportError:
        raise unittest.SkipTest("unicorn not installed")
    buf, ctx, interp, this, stack, sentinel = 0x10000000, 0x11000000, 0x11100000, 0x11200000, 0x12000000, 0x13000000
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    mu.mem_map(base, (len(img) + 0xFFF) & ~0xFFF)
    mu.mem_write(base, img)
    for address in (buf, ctx, interp, this, stack, sentinel):
        mu.mem_map(address, 0x100000)
    mu.mem_write(ctx + 8, struct.pack("<Q", interp))
    mu.mem_write(interp + 0x38, struct.pack("<Q", buf))
    mu.mem_write(this + 0x10, struct.pack("<Q", sentinel))
    mu.mem_write(stack + 0x80000, struct.pack("<Q", sentinel))
    mu.reg_write(UC_X86_REG_RSP, stack + 0x80000)
    mu.reg_write(UC_X86_REG_RCX, this)
    mu.reg_write(UC_X86_REG_RDX, ctx)
    mu.reg_write(UC_X86_REG_R8, ctx)
    reads = set()
    mu.hook_add(UC_HOOK_MEM_READ, lambda uc, a, addr, size, v, d: reads.add((addr - buf, size))
                if buf <= addr < buf + 0x1000 else None)
    mu.hook_add(UC_HOOK_CODE, lambda uc, addr, size, d: uc.emu_stop()
                if sentinel <= addr < sentinel + 0x100000 else None)
    try:
        mu.emu_start(parser, 0, count=20000)
    except UcError:
        pass
    end = struct.unpack("<Q", mu.mem_read(interp + 0x38, 8))[0] - buf
    widths, pos = [], 0
    while pos < end:
        values = [size for offset, size in reads if offset == pos + 1]
        if (pos, 1) not in reads or not values:
            return None
        widths.append(max(values))
        pos += 1 + max(values)
    return widths if pos == end else None


class D4OperandWidths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _need(D4_EXE)
        if hashlib.sha256(D4_EXE.read_bytes()).hexdigest() != D4_EXE_SHA256:
            raise unittest.SkipTest("different Disgaea4pc.exe build")
        cls.base, cls.img = _image(D4_EXE)

    def test_signatures_match_native_parsers(self):
        for opcode, vtable in VTABLES.items():
            with self.subTest(opcode=f"{opcode:04x}"):
                parser = struct.unpack_from("<Q", self.img, vtable - self.base + 4 * 8)[0]
                self.assertEqual(_operand_widths(self.base, self.img, parser), d4inventory.D4_SIGNATURES[opcode])


class D4ScriptDecode(unittest.TestCase):
    def test_special_scene_events_decode_byte_exact(self):
        _need(D4_DATA / "DATABASE_EN.dat")
        from d5lib import d4scripts
        from d5lib.d4source import Nsac
        source = d4scripts.Source(Nsac(D4_DATA / "DATABASE_EN.dat").read("script.dat"))
        for eid in DESYNCED_EVENTS:
            with self.subTest(event=eid):
                record = source.event(eid)
                self.assertFalse(record.get("error"), record.get("error"))
                self.assertTrue(any(ins.cid == 0x4630 or ins.cid >> 8 in (0x46, 0x64, 0x6B) for ins in record["event"].code))


class D4LocalArithmetic(unittest.TestCase):
    def test_native_divide_differs(self):
        """D4 0x1440 op 3 divides floats (divss); D5 truncates and uses idiv."""
        _need(D4_EXE, D5_EXE)
        try:
            import capstone
        except ImportError:
            raise unittest.SkipTest("capstone not installed")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        base, img = _image(D4_EXE)
        d4 = [i.mnemonic for i in md.disasm(img[0x1401496C0 - base:0x1401496C0 - base + 328], 0x1401496C0)]
        self.assertIn("divss", d4)
        base, img = _image(D5_EXE)
        d5 = [i.mnemonic for i in md.disasm(img[0x140184CD0 - base:0x140184CD0 - base + 455], 0x140184CD0)]
        self.assertIn("idiv", d5)
        self.assertNotIn("divss", d5)

    def _register(self, float_divide):
        code = [script.Ins(0x1440, [1, 150, 3, 40]), script.Ins(choreo.WAIT, [script.Var(20001, 0x10)]),
                script.Ins(0x0108)]
        tl = choreo.simulate({900: script.Event(900, code)}, 900, choreo.Context(float_divide=float_divide))
        return tl.length

    def test_dialects(self):
        # 15 / 4: D5 waits int(3) frames; D4's register holds 3.75 (the wait reads it the same way)
        self.assertEqual(self._register(False), 3)
        self.assertEqual(self._register(True), 3)
        code = [script.Ins(0x1440, [1, 150, 3, 40]), script.Ins(0x1440, [2, script.Var(20001, 0x10), 2, 40]),
                script.Ins(choreo.WAIT, [script.Var(20002, 0x10)]), script.Ins(0x0108)]
        ev = {900: script.Event(900, code)}
        self.assertEqual(choreo.simulate(ev, 900, choreo.Context()).length, 12)                     # 3 * 4
        # D4: 3.75, read back as an operand in tenths (37) * 4 = 14.8 -> a 14-frame wait
        self.assertEqual(choreo.simulate(ev, 900, choreo.Context(float_divide=True)).length, 14)
        zero = [script.Ins(0x1440, [1, 150, 3, 0]), script.Ins(choreo.WAIT, [script.Var(20001, 0x10)]),
                script.Ins(0x0108)]
        # divide by zero: D4 stores an infinite float; the simulator keeps it as 0 (labelled approximation)
        self.assertEqual(choreo.simulate({900: script.Event(900, zero)}, 900,
                                         choreo.Context(float_divide=True)).length, 0)


class D4EffectRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _need(D4_DATA / "EFFECT.dat")
        from d5lib.d4source import Nsac
        cls.archive = Nsac(D4_DATA / "EFFECT.dat")

    def model(self, eid):
        return lzs.decompress(self.archive.read(f"effect{eid:03d}.lzs"))

    def test_layout_rule(self):
        ok = lambda shape: d4effects.palette_layout_ok(shape, extended=True)
        self.assertFalse(d4effects.palette_layout_ok((14, 64, 32, 2)))     # default: reviewed layouts only
        self.assertTrue(ok((14, 64, 32, 2)))
        self.assertTrue(ok((10, 512, 512, 2)))
        self.assertFalse(ok((14, 48, 32, 2)))     # not a power of two
        self.assertFalse(ok((2, 64, 64, 2)))      # color32 has no palettes
        self.assertFalse(ok((14, 64, 64, 17)))
        self.assertFalse(ok((14, 1024, 64, 2)))

    def test_new_layout_on_real_model(self):
        # effect 120: indexed8 64x32 with two palettes, static materials
        with self.assertRaises(d4effects.UnsupportedEffect):
            d4effects.convert_obf(self.model(120), palette_frames=True)
        output, report = d4effects.convert_obf(self.model(120), palette_frames=True, extended=True)
        self.assertEqual(report["conversion_mode"], "extended-palette-frames")
        self.assertFalse(report["live_proven"])
        self.assertEqual(obf.ObfFile(output).sections[:9], obf.ObfFile(self.model(120)).sections[:9])

    def test_entry_animation_is_opt_in(self):
        raw = self.model(107)       # palette textures under materials that step through texture entries
        with self.assertRaises(d4effects.UnsupportedEffect):
            d4effects.convert_obf(raw, palette_frames=True)
        with self.assertRaises(ValueError):
            d4effects.convert_obf(raw, extended=True)
        output, report = d4effects.convert_obf(raw, palette_frames=True, extended=True)
        self.assertGreater(report["materials"]["animated_records"], 0)
        self.assertEqual(obf.ObfFile(output).sections[7], obf.ObfFile(raw).sections[7])   # material bytes kept

    def test_72_byte_material_records(self):
        raw = self.model(118)
        with self.assertRaises(d4effects.UnsupportedEffect):
            d4effects.convert_obf(raw, palette_frames=True)
        _, report = d4effects.convert_obf(raw, palette_frames=True, extended=True)
        self.assertEqual(report["materials"]["count"], 36)


if __name__ == "__main__":
    unittest.main()
