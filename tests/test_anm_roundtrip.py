"""d5lib.anm parse/to_bytes round trip and tools/anm_roundtrip.py coverage on a bank built in code (no game data)."""
import importlib.util
import struct
import unittest
from pathlib import Path

from d5lib import anm

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("anm_roundtrip", ROOT / "tools/anm_roundtrip.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)


def synthetic(block_pad=b"", image_pad=b""):
    """One block with rows in all ten tables, one 4x2 8-bit texture and one 256-colour palette."""
    b = anm.AnmBlock(
        id=10,
        animations=[anm.Animation(1001, 0)],
        nodes=[anm.Node(0, 0, 0, 0, 0, 0, 0, 1, -1, -1)],
        keys=[anm.Key(0, 0x0301, 1, 0, 0, 0)],              # flags: +2 = 1, +3 = 3 (two bytes in D5)
        palette_infos=[anm.PaletteInfo(0, 256, 0)],
        texture_infos=[anm.TextureInfo(0, 4, 2, 8, 0x10, 0x10, 0)],
        cells=[anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0x0207, 0x0101, 0, 0, 4, 2, 1)],
        transforms=[anm.Transform(-3, 5, 0, 0, -100, 100, 90)],
        pivots=[anm.Pivot(2, 1)],
        colors=[anm.Color((128, 128, 128, 255) * 5)],
        params=[1001, 0, -1])
    b.pad = block_pad
    tex = anm.Image8(b"\x09\x01\x01\x01", 4, 2, 1, bytes(range(8)), image_pad)
    pal = anm.Image8(b"\x00\x01\x01\x01", 256, 1, 1, bytes(range(256)) * 4)
    return anm.AnmFile([b], [tex], [pal])


class AnmRoundTripTests(unittest.TestCase):
    def test_parse_then_write_is_byte_identical(self):
        raw = synthetic().to_bytes()
        self.assertEqual(anm.AnmFile.parse(raw).to_bytes(), raw)
        h0, dsize, ntex, npal, nblk = struct.unpack_from("<5I", raw, 0)
        self.assertEqual((ntex, npal, nblk), (1, 1, 1))
        self.assertEqual(h0 + 0x10 + dsize, len(raw))               # image data ends the file
        self.assertEqual(dsize, 0x80 + 1024)                        # palette 128-byte aligned after the texture

    def test_junk_padding_survives_and_is_reported_unexplained(self):
        _, size = synthetic().blocks[0].layout()
        tail = size - (anm.BLOCK_HEADER_SIZE + sum(n * s for n, s in zip([1, 1, 1, 1, 1, 2, 1, 1, 1, 3],
                                                                          anm.TABLE_SIZES)))
        raw = synthetic(b"\xAB" * tail, b"\xFD" * (0x80 - 8)).to_bytes()
        f = anm.AnmFile.parse(raw)
        self.assertEqual(f.to_bytes(), raw)
        groups, unexplained = rt.coverage(rt.regions(f, raw), raw)
        self.assertEqual([u["where"] for u in unexplained],
                         ["block 0 tail padding (non-zero)", "image 0 alignment padding (non-zero)"])
        self.assertEqual(groups["unexplained"], tail + 0x80 - 8)
        self.assertEqual(sum(groups.values()), len(raw))

    def test_zero_padding_is_fully_explained(self):
        raw = synthetic().to_bytes()
        groups, unexplained = rt.coverage(rt.regions(anm.AnmFile.parse(raw), raw), raw)
        self.assertEqual(unexplained, [])
        self.assertEqual(sum(groups.values()), len(raw))

    def test_first_difference_is_located(self):
        raw = synthetic().to_bytes()
        R = rt.regions(anm.AnmFile.parse(raw), raw)
        cells = next(s for s, e, label, _ in R if label.endswith("cells"))
        self.assertEqual(rt.region_of(R, cells + 18 + 5), "block 0 table 5 cells")
        self.assertEqual(rt.region_of(R, 0x15), "file header +0x14")


if __name__ == "__main__":
    unittest.main()
