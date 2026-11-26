"""Read an ANM bank written by another tool (no 16-byte block alignment) and re-emit it in the Kit's layout.

The Kit's reader (d5lib.anm) refuses a block whose table offsets are right but whose size is not 16-aligned;
Overlord Edition v3's generated banks are exactly that (e.g. anm20300.dat: tables at 0x44..0x51ac, block size
0x5584 instead of the aligned 0x5590).  Everything else is the D5 ANM format, so we read the tables where the
file itself says they are and let the Kit compute the canonical layout on write.
"""
from __future__ import annotations

import struct

from d5lib import anm

FILE_HEADER_SIZE = anm.FILE_HEADER_SIZE


def parse_foreign(data: bytes) -> anm.AnmFile:
    h0, dsize, ntex, npal, nblk = struct.unpack_from("<5I", data, 0)
    pos = FILE_HEADER_SIZE
    blocks = []
    tb = pb = 0
    for _ in range(nblk):
        size, bid, nanim = struct.unpack_from("<IHH", data, pos)
        counts = struct.unpack_from("<10H", data, pos + 8)
        offs = struct.unpack_from("<10I", data, pos + 0x1C)
        cnt = [nanim] + list(counts[:9])
        b = anm.AnmBlock(bid, count9=counts[9])
        for i, (tcls, tsz) in enumerate(zip(anm.TABLES, anm.TABLE_SIZES)):
            b.tables()[i].extend(anm._unpack_table(tcls, data, pos + offs[i], cnt[i], tsz))
        b.tex_base, b.pal_base = tb, pb
        tb += len(b.texture_infos)
        pb += len(b.palette_infos)
        b.pad = b""                      # canonical layout recomputed by to_bytes()
        blocks.append(b)
        pos += size
    base = h0 + 0x10
    imgs = []
    for i in range(ntex + npal):
        r = pos + i * anm.IMG_HEADER_SIZE
        fmt = bytes(data[r:r + 4])
        w, hgt, unk, off = struct.unpack_from("<HHII", data, r + 4)
        if i < ntex:
            n = w * hgt * (1 if fmt[0] == anm.FMT_INDEXED8 else 4)
        else:
            # palettes: vanilla is 256 colours x 4 bytes (256x1); this writer states 256x4 (its own
            # height unit) but still stores 1024 bytes, so normalise to the shape the Kit and the game use
            if not (w == 256 and hgt in (1, 4)):
                raise ValueError("palette %d: unexpected %dx%d" % (i - ntex, w, hgt))
            n, hgt = 1024, 1
        imgs.append((off, anm.Image8(fmt, w, hgt, unk, bytes(data[base + off:base + off + n]))))
    # this writer does not keep the Kit's 128-byte packing order/alignment, so read every image where the
    # file says it is and let to_bytes() re-pack it canonically (offsets are rewritten, nothing is dropped)
    end = 0
    for off, im in imgs:
        end = max(end, off + len(im.data))
    trail = bytes(data[base + end:])
    if pos + (ntex + npal) * anm.IMG_HEADER_SIZE != base:
        raise ValueError("unexpected header layout")
    return anm.AnmFile(blocks, [im for _, im in imgs[:ntex]], [im for _, im in imgs[ntex:]],
                       bytes(data[0x14:0x20]), trail)


def reid(data: bytes, new_id: int) -> anm.AnmFile:
    """foreign bank bytes -> a Kit AnmFile whose (single) block carries `new_id`."""
    f = parse_foreign(data)
    if len(f.blocks) != 1:
        raise ValueError("bank has %d blocks; a character bank is one block" % len(f.blocks))
    f.blocks[0].id = new_id
    return f
