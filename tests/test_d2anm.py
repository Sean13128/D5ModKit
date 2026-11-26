"""d5lib.d2anm round trip and byte-field positions on a big-endian D2 bank built in code (no game data)."""
import importlib.util
import struct
import unittest
from pathlib import Path

from d5lib import anm, d2anm

spec = importlib.util.spec_from_file_location("anm_roundtrip", Path(__file__).resolve().parents[1] / "tools/anm_roundtrip.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)


def synthetic(cell_size=18):
    """One block with rows in all ten tables, one 4x4 DXT5 sheet, one 4x2 8-bit sheet and one 256x4 palette."""
    b = anm.AnmBlock(
        id=10,
        animations=[anm.Animation(1001, 0)],
        nodes=[anm.Node(0x0102, 0x1F10, 3, 0, 1, 0, 0, 1, -1, -1)],
        keys=[anm.Key(7, 0x0301, 1, 0, 0, 0)],               # +2 = 1, +3 = 3
        palette_infos=[anm.PaletteInfo(0x1234, 256, 0)],
        texture_infos=[anm.TextureInfo(0x5678, 4, 2, 8, 0x10, 0x10, 0)],
        cells=[anm.Cell(0, 0, 0x0207, 0x0001, 1, 2, 4, 2, 0 if cell_size == 16 else 0x0035)],
        transforms=[anm.Transform(-3, 5, 0, 2, -100, 100, 90)],  # pivot index 2 in D2's word at +6
        pivots=[anm.Pivot(2, 1)],
        colors=[anm.Color((128, 128, 128, 255) * 5)],
        params=[1001, 0, -1])
    if cell_size == 16:
        b.cell_size = 16
    dxt = anm.Image8(b"\x04\x01\x01\x01", 4, 4, 0x10000, bytes(range(16)), b"\xFD" * 0x70)
    tex = anm.Image8(b"\x09\x01\x01\x01", 4, 2, 0x10000, bytes(range(8)))
    pal = anm.Image8(b"\x00\x01\x01\x01", 256, 4, 0x10000, bytes(range(256)) * 16)
    return anm.AnmFile([b], [dxt, tex], [pal])


class D2AnmTests(unittest.TestCase):
    def test_round_trip_is_byte_identical(self):
        for cell_size in (18, 16):
            raw = d2anm.to_bytes(synthetic(cell_size))
            self.assertEqual(d2anm.to_bytes(d2anm.parse(raw)), raw)
        f = d2anm.parse(raw)
        self.assertEqual(f.blocks[0].cell_size, 16)
        self.assertEqual(f.textures[0].pad, b"\xFD" * 0x70)                    # junk alignment bytes survive
        self.assertEqual(len(f.palettes[0].data), 4096)
        groups, unexplained = rt.coverage(rt.regions(f, raw, d2=True), raw)
        self.assertEqual([u["where"] for u in unexplained], ["image 0 alignment padding (non-zero)"])
        self.assertEqual(sum(groups.values()), len(raw))

    def test_fields_sit_where_d2_stores_them(self):
        raw = d2anm.to_bytes(synthetic())
        h0, dsize, ntex, npal, nblk = struct.unpack_from(">5I", raw)
        self.assertEqual((ntex, npal, nblk, h0 + 0x10 + dsize), (2, 1, 1, len(raw)))
        offs = [0x20 + o for o in struct.unpack_from(">10I", raw, 0x20 + 0x1C)]
        self.assertEqual(offs[2] - offs[1], 16)                                 # 16-byte node row
        self.assertEqual(struct.unpack_from(">HHHH", raw, offs[1]), (0x0102, 0x1F10, 3, 1))   # mesh is word 3
        self.assertEqual(raw[offs[2] + 2:offs[2] + 4], b"\x01\x03")            # key +2, +3
        cell = raw[offs[5]:offs[6]]
        self.assertEqual((len(cell), cell[4:8], cell[16:18]), (18, b"\x07\x02\x01\x00", b"\x35\x00"))
        self.assertEqual(struct.unpack_from(">hhHH", raw, offs[6]), (-3, 5, 0, 2))
        f = d2anm.parse(raw)
        d2anm.swap_pivots(f)
        self.assertEqual((f.blocks[0].transforms[0].pivot, f.blocks[0].transforms[0].unk), (2, 0))

    def test_rows_d2_lacks_must_be_empty(self):
        f = synthetic(16)
        f.blocks[0].cells[0].unk8 = 1
        with self.assertRaises(ValueError):
            d2anm.to_bytes(f)
        f = synthetic()
        f.blocks[0].nodes[0].unk5 = 1
        with self.assertRaises(ValueError):
            d2anm.to_bytes(f)


if __name__ == "__main__":
    unittest.main()
