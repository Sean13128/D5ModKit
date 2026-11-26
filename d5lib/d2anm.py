"""Disgaea D2 (PS3) animation banks: a byte-faithful big-endian reader and writer.

A D2 bank is laid out like a D5 one (docs/ANM.md): a 32-byte file header, blocks with a 0x44-byte header and ten
tables, 16-byte image descriptors, then image data at header[0] + 0x10, each image 0x80-aligned.  Everything is
big-endian and some rows differ from D5's; ROWS is the whole D2 row layout (docs/ANM.md section 10).  parse()
fills the kit's own record classes (d5lib.anm) and to_bytes() writes them back byte for byte.

Each field keeps the kit's name for the bytes at the same place, so nothing is swapped:
- A field named twice is two byte fields.  The kit's u16 holds the first as its low byte, the way D5 reads them
  (key +2/+3, cell +4/+5, +6/+7, +16/+17).  A big-endian u16 read of these swaps the two bytes.
- Nodes are 16 bytes: D5's unk3 and unk5 do not exist and must stay 0.  Words 0 and 1 are D5's node u32 laid out
  as a big-endian bitfield (id:24, binding:4, mode:4 from the top bit down); d5_node_words() rewrites them the way D5
  reads them.  Word 3 is read as mesh; word 2 is 0 in every bank.
- Transforms: the word at +6 (the kit's `unk`) is the pivot index D2 draws with; +4 (`pivot`) is 0 in every bank,
  as the high half of a big-endian i32 would be (D5 reads +4..+7 as one i32).  swap_pivots() moves the index to
  where the kit's renderer looks.
- Four effect banks have 16-byte cell rows with no +16 word (CELL16); their blocks get `cell_size = 16`.
- Images: format byte 9 is 8-bit indexed, 0 is ARGB32, 4 is DXT5 (1 byte per pixel, kept compressed here).
  Palettes are ARGB32, 256x1 or 256x4.
"""
import dataclasses
import struct

from . import anm

ROWS = [                                                    # per table: big-endian row, kit field per item
    (">HH", "id root"),
    (">HHHHhHhh", "id flags unk2 mesh first_key num_keys child next"),
    (">HBBHHHH", "time flags flags cell xform color param"),
    (">IHH", "offset num_colors unk"),
    (">IHHBBBB", "offset width height bpp unk1 unk2 unk3"),
    (">HHBBBBHHHHBB", "tex pal unk2 unk2 flags flags x y w h unk8 unk8"),
    (">hhHHhhi", "x y pivot unk sx sy rot"),
    (">hh", "x y"),
    (">20B", "rgba"),
    (">i", "value"),
]
CELL16 = (">HHBBBBHHHH", "tex pal unk2 unk2 flags flags x y w h")
BYTES_PER_PIXEL = {anm.FMT_INDEXED8: 1, anm.FMT_ARGB32: 4, 4: 1}


def _codec(cls, fmt, names):
    """(struct, row from values, values from row) for one D2 row layout."""
    st, names = struct.Struct(fmt), names.split()
    if cls is None:
        return st, lambda v: v[0], lambda r: (r,)
    if cls is anm.Color:
        return st, anm.Color, lambda r: r.rgba
    fields = [f.name for f in dataclasses.fields(cls)]
    absent = [f for f in fields if f not in names]
    low = [i + 1 < len(names) and names[i + 1] == n for i, n in enumerate(names)]
    high = [i > 0 and names[i - 1] == n for i, n in enumerate(names)]

    def read(v):
        kw = dict.fromkeys(fields, 0)
        for n, x, hi in zip(names, v, high):
            kw[n] = kw[n] | x << 8 if hi else x
        return cls(**kw)

    def write(r):
        if any(getattr(r, f) for f in absent):
            raise ValueError(f"D2 {cls.__name__} row has no {absent}: {r}")
        return [getattr(r, n) & 255 if lo else getattr(r, n) >> 8 if hi else getattr(r, n)
                for n, lo, hi in zip(names, low, high)]
    return st, read, write


CODECS = [_codec(cls, *row) for cls, row in zip(anm.TABLES, ROWS)]
CODEC_CELL16 = _codec(anm.Cell, *CELL16)


def _codecs(b):
    return CODECS[:5] + [CODEC_CELL16] + CODECS[6:] if getattr(b, "cell_size", 18) == 16 else CODECS


def row_sizes(b):
    return [c[0].size for c in _codecs(b)]


def layout(b):
    """(table offsets, block size) of a block, as D2 stores them: tables back to back, size 16-aligned."""
    offs, o = [], anm.BLOCK_HEADER_SIZE
    for rows, sz in zip(b.tables(), row_sizes(b)):
        offs.append(o)
        o += len(rows) * sz
    return offs, (o + 15) & ~15


def _parse_block(d, pos):
    size, bid, nanim = struct.unpack_from(">IHH", d, pos)
    counts = struct.unpack_from(">10H", d, pos + 8)
    offs = struct.unpack_from(">10I", d, pos + 0x1C)
    cnt = [nanim, *counts[:9]]
    b = anm.AnmBlock(bid, count9=counts[9])
    if cnt[5] and offs[6] - offs[5] == cnt[5] * 16:
        b.cell_size = 16
    for rows, n, o, (st, read, _) in zip(b.tables(), cnt, offs, _codecs(b)):
        rows.extend(read(v) for v in st.iter_unpack(d[pos + o:pos + o + n * st.size]))
    lay, lsize = layout(b)
    if list(offs) != lay or lsize != size:
        raise ValueError(f"D2 block at {pos:#x}: unexpected table layout")
    b.pad = bytes(d[pos + lay[9] + cnt[9] * 4:pos + size])
    return b, size


def image_size(im):
    return im.width * im.height * BYTES_PER_PIXEL[im.fmt[0]]


def parse(d) -> anm.AnmFile:
    """Decompressed D2 bank -> anm.AnmFile; to_bytes() of the result gives the same bytes back."""
    h0, dsize, ntex, npal, nblk = struct.unpack_from(">5I", d)
    pos, blocks, tb, pb = anm.FILE_HEADER_SIZE, [], 0, 0
    for _ in range(nblk):
        b, size = _parse_block(d, pos)
        b.tex_base, b.pal_base = tb, pb
        tb += len(b.texture_infos)
        pb += len(b.palette_infos)
        blocks.append(b)
        pos += size
    base = h0 + 0x10
    if pos + (ntex + npal) * anm.IMG_HEADER_SIZE != base:
        raise ValueError("D2 image descriptors do not end at header[0] + 0x10")
    images, o, prev = [], 0, None
    for i in range(ntex + npal):
        r = pos + i * anm.IMG_HEADER_SIZE
        w, h, unk, off = struct.unpack_from(">HHII", d, r + 4)
        if off != anm._align(o, anm.IMG_ALIGN):
            raise ValueError(f"D2 image {i} at {off:#x}, expected {anm._align(o, anm.IMG_ALIGN):#x}")
        if prev:
            prev.pad = bytes(d[base + o:base + off])
        im = anm.Image8(bytes(d[r:r + 4]), w, h, unk, b"")
        im.data = bytes(d[base + off:base + off + image_size(im)])
        images.append(im)
        o, prev = off + len(im.data), im
    if o != dsize:
        raise ValueError("D2 image data size differs from header[1]")
    return anm.AnmFile(blocks, images[:ntex], images[ntex:], bytes(d[0x14:0x20]), bytes(d[base + o:]))


def _block_bytes(b):
    offs, size = layout(b)
    t = b.tables()
    cnt = [len(x) for x in t]
    out = bytearray(struct.pack(">IHH10H10I", size, b.id, cnt[0], *cnt[1:], b.count9, *offs))
    for rows, (st, _, write) in zip(t, _codecs(b)):
        out += b"".join(st.pack(*write(r)) for r in rows)
    n = size - len(out)
    return bytes(out + (b.pad if len(b.pad) == n else bytes(n)))


def to_bytes(f: anm.AnmFile) -> bytes:
    """anm.AnmFile read by parse() -> D2 bank bytes.  Offsets, sizes and counts are recomputed; the console's own
    palette/texture info offsets (tables 3 and 4) are written as they are."""
    body = b"".join(_block_bytes(b) for b in f.blocks)
    images = f.textures + f.palettes
    descriptors, chunks, o = bytearray(), [], 0
    for i, im in enumerate(images):
        if len(im.data) != image_size(im):
            raise ValueError(f"D2 image {i}: {len(im.data)} bytes for {im.width}x{im.height} format {im.fmt[0]}")
        n = anm._align(o, anm.IMG_ALIGN) - o
        if n:
            pad = images[i - 1].pad
            chunks.append(pad if len(pad) == n else bytes(n))
            o += n
        descriptors += im.fmt + struct.pack(">HHII", im.width, im.height, im.unk, o)
        chunks.append(im.data)
        o += len(im.data)
    base = anm.FILE_HEADER_SIZE + len(body) + len(descriptors)
    head = struct.pack(">5I", base - 0x10, o, len(f.textures), len(f.palettes), len(f.blocks)) + f.hdr_unk
    return b"".join([head, body, bytes(descriptors), *chunks, f.trailing])


def swap_pivots(f: anm.AnmFile):
    """Put each transform's pivot index (D2 +6) where the kit's renderer reads it (+4), and back again."""
    for b in f.blocks:
        for x in b.transforms:
            x.pivot, x.unk = x.unk, x.pivot


def d5_palette_counts(f: anm.AnmFile):
    """Rewrite each PaletteInfo's colour count (+4..+7) as D5 reads it (WRITEWATCH1, 2026-11-21).

    D2 stores the count as one big-endian i32 at +4 (256 = 00 00 01 00), so the kit's byte-faithful
    `num_colors` (+4) is 0 and `unk` (+6) is 256.  D5 reads +4..+7 as one little-endian i32: copied raw the
    count is 0x01000000, and the attack set-up (0x1402F9550, start_basic_attack / start_skill_action) copies
    that many colours of a monster's current palette into its 256-colour buffer 0x1469AF859, writing 64 MB
    over the globals after it (the dlmalloc mspace handle 0x147B59E30 among them: DD2 Shark Dragon crash).
    A count above 256 is clamped (the game's buffer holds 256; to_d5_images keeps 256 colours).  Not
    reversible.
    """
    for b in f.blocks:
        for p in b.palette_infos:
            v = p.num_colors << 16 | p.unk
            p.num_colors, p.unk = min(v, 256) if v > 0 else 256, 0


def d5_node_words(f: anm.AnmFile):
    """Rewrite each node's words 0-1 as D5's node u32 (docs/ANM.md section 8.1 and 10).

    D2 keeps the same three fields in big-endian bitfield order: bytes +0..+2 the id, +3 high nibble the binding
    flag, +3 low nibble the draw mode (D2 0x6311 = D5 id 99, flags 0x1100, as D5's own anm02070 has it).  A D2
    asset id (binding 0, id != 0) names a D2 record, not a D5 one, so it is dropped.  Not reversible.
    """
    for b in f.blocks:
        for n in b.nodes:
            v = n.id << 16 | n.flags
            ref, bind, mode = v >> 8, v >> 4 & 15, v & 15
            n.id, n.flags = (ref if bind else 0) & 0xFFFF, (ref >> 16 if bind else 0) | bind << 8 | mode << 12
