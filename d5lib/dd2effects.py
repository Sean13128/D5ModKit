"""Disgaea D2 (PS3) effect models -> D5 OBF byte order (DD2SPEC1, offline).

DD2 keeps its effects as ``effectNNN.lzs`` in START.dat (NISPACK), each an OBF version 2 file in PS3 byte order.
The section layout is d5lib.obf's / fxanim's; every field is turned to D5's little-endian layout by its type:

  header       u32 total, u32 version, u32 offset[10]
  0, 1         u32 count, {i16 id, i16 index} entries (mesh / object id maps)
  2            objects: u32 nodes, u32 frames, f32 uv u, f32 uv v, u8 billboard, u8 uv interval, u8 pad[10],
               u32 node index[]  (bytes 0x10..0x1C copied)
  3            nodes: i32 mesh, i16 parent, u8, u8, u32 n, u32 trackset[n]
  4            track sets, u32 x 10
  5            keys {f32 value, u32 bits, f32 tin, f32 tout}; the bit field is frame:24 / type:8, packed from the top
               on PS3 (frame << 8 | type) and from the bottom in D4 / D5 (type << 24 | frame)
  6            meshes: u32 count, f32 uv u, f32 uv v, u8 billboard, u8 interval, u8, u8, u8 pad[12], u32 index[]
               (bytes 0x0C..0x1C copied)
  7            submeshes: u32 count, i32 texture, u8 rgba[4], f32 x5, 12 u8 fields, i32 texture2, u32 index[]
  8            f32 words (60-byte vertices)
  9            textures {u32 attr, TXF}: see texture()
Field types: Sorrow's D5 OBF reader notes (Private/.../sorrow/research-20261014/obf_format.md 3.0-3.9, from
D5 0x1402FB7B0 .. 0x140300EA0) and the kit's obf.py / fxanim.py; DD2 uses the same layout in PS3 byte order.

Evidence (not assumption): for the 99 effects used by the adapted DD2 specials whose section offsets equal the
same-numbered Disgaea 4 Complete+ PC effect, sections 0..8 converted here are compared with D4's bytes by
tests/test_dd2spec1.py; D4 PC effects are the ones the SPECBULK route already converts for D5.
"""
from __future__ import annotations

import struct

from . import obf

N = obf.N_SECTIONS


def _sw32(b):
    n = len(b) // 4
    return struct.pack(f"<{n}I", *struct.unpack(f">{n}I", b[:n * 4])) + b[n * 4:]


def _table(sec, entry):
    """offset table with per-entry converter"""
    n = struct.unpack_from(">I", sec)[0]
    offs = list(struct.unpack_from(f">{n}I", sec, 4)) + [len(sec)]
    head = struct.pack(f"<I{n}I", n, *offs[:n])
    lead = sec[4 + 4 * n:offs[0]] if n else sec[4:]
    return head + _sw32(lead) + b"".join(entry(sec[offs[i]:offs[i + 1]]) for i in range(n))


def _node(e):
    part, parent, a, b, n = struct.unpack_from(">ihBBI", e)
    out = struct.pack("<ihBBI", part, parent, a, b, n)
    return out + _sw32(e[12:])


def _bytes_at(e, lo, hi):
    """u32 words, except bytes lo..hi copied as they are (u8 fields and padding)"""
    if len(e) < hi:
        return _sw32(e)
    return _sw32(e[:lo]) + e[lo:hi] + _sw32(e[hi:])


def _pairs(sec):
    """u32 count, then {i16 id, i16 index} entries (sections 0 and 1, Sorrow obf_format.md 3.0 / 3.1)"""
    n = struct.unpack_from(">I", sec)[0]
    body = sec[4:4 + 4 * n]
    return (struct.pack("<I", n) + struct.pack(f"<{2 * n}h", *struct.unpack(f">{2 * n}h", body))
            + _sw32(sec[4 + 4 * n:]))


def _mesh(e):
    if len(e) < 48:
        return _sw32(e)
    head = _sw32(e[:8]) + e[8:12] + _sw32(e[12:32]) + e[32:44] + _sw32(e[44:48])
    return head + _sw32(e[48:])


def _points(sec):
    if len(sec) % 16:
        raise ValueError("curve point section is not a whole number of points")
    out = bytearray()
    for i in range(0, len(sec), 16):
        value, bits, tin, tout = struct.unpack_from(">IIII", sec, i)
        frame, kind = bits >> 8, bits & 0xFF
        out += struct.pack("<IIII", value, kind << 24 | frame, tin, tout)
    return bytes(out)


def texture(entry):
    """One section-9 entry: u32 attr then a 16-byte TXF header + pixels.

    PS3 headers are big-endian: fmt[4], u16 w, u16 h, u16 byte-order marker (00 01), u16 reserved, u32 size. D5's
    decoder (0x14030FFF0) honours the marker, so a big-endian header is valid as it is; LA88 headers are turned to
    little-endian (marker 1) because the kit reads LA88 little-endian (obf.Texture), and checked by
    d5lib.obfbounds against D5's arithmetic. attr (layer count) is little-endian
    in both. Pixel bytes are copied: LA88 is byte pairs, DXT blocks are the GPU's own order, ARGB8888 is A,R,G,B
    bytes and the 16-bit formats are big-endian words in both games (approximation: checked by eye on decoded
    samples, see DD2SPEC1-REPORT; a swizzled PS3 surface would show as scrambled blocks)."""
    attr, txf = entry[:4], entry[4:]
    fmt = txf[0]
    w, h = struct.unpack_from(">HH", txf, 4)
    size = struct.unpack_from(">I", txf, 12)[0]
    if fmt == obf.FMT_LA:
        stored = len(txf) - 16
        if not w or not h or size % (w * h * 2) or stored % (w * h * 2):
            raise ValueError(f"LA88 size {size} does not match {w}x{h} layers")
        if size > stored:
            # effects 200 / 201 (DD2SPEC1): attr 0 and a size field twice the stored pixels (64x64: 32768 for 16384
            # bytes = two 64x64 LA88 layers, decoded by eye as the rock pictures of D4's same-numbered effect).
            # D5 counts LA88 layers from this field (obf.Texture), so it is set to what is stored. Approximation.
            if struct.unpack("<I", attr)[0] != 0 or size != 2 * stored:
                raise ValueError(f"LA88 size {size} exceeds the {stored} stored bytes")
            size = stored
        # D5 0x14030FFF0 reads the u16 at +8 as the byte-order marker (1 little-endian = no swap; anything else makes
        # it swap width, height, marker and size). PS3 stores 00 01 (1, big-endian) then a reserved u16: write the
        # marker as little-endian 1 and keep the reserved bytes (DD2SPEC3; DD2SPEC2 wrote the four bytes as one u32,
        # which D5 read as marker 0 and swapped the little-endian fields: Codex REVIEW-DD2SPEC2).
        if txf[8:10] != b"\x00\x01":
            raise ValueError(f"LA88 byte-order marker {txf[8:10].hex()} is not PS3's 00 01")
        return attr + txf[:4] + struct.pack("<HHH", w, h, 1) + txf[10:12] + struct.pack("<I", size) + txf[16:]
    if fmt in (obf.FMT_ARGB, obf.FMT_DXT1, obf.FMT_DXT3, obf.FMT_DXT5, obf.FMT_1555, obf.FMT_565):
        # copied big-endian: marker bytes 00 01 read little-endian are 0x0100, so D5 swaps every field back
        if txf[8:10] != b"\x00\x01":
            raise ValueError(f"texture byte-order marker {txf[8:10].hex()} is not PS3's 00 01")
        return entry
    raise ValueError(f"texture format {fmt:#x} not checked for DD2")


def convert(data):
    """DD2 effect OBF (decompressed) -> D5-layout OBF bytes. Raises ValueError on anything not modelled."""
    total, version = struct.unpack_from(">II", data)
    if version != 2 or not 48 <= total <= len(data):
        raise ValueError("not a DD2 OBF version 2")
    offs = list(struct.unpack_from(f">{N}I", data, 8)) + [total]
    if offs[0] != 8 + 4 * N or offs != sorted(offs):
        raise ValueError("bad DD2 OBF section table")
    s = [data[offs[i]:offs[i + 1]] for i in range(N)]
    out = [_pairs(s[0]), _pairs(s[1]), _table(s[2], lambda e: _bytes_at(e, 0x10, 0x1C)), _table(s[3], _node),
           _sw32(s[4]), _points(s[5]), _table(s[6], lambda e: _bytes_at(e, 0x0C, 0x1C)), _table(s[7], _mesh),
           _sw32(s[8]), _table(s[9], texture)]
    body = struct.pack(f"<II{N}I", total, version, *offs[:N]) + b"".join(out)
    if len(body) != total:
        raise ValueError("conversion changed the model size")
    return body + data[total:]
