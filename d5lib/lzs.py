"""NIS LZS compression (used by .lzs files inside Anime/Map archives).

Header (16 bytes): ext[4] ('dat\0','pac\0',...), u32 decompressed_size,
u32 compressed_size (including header), u32 marker (low byte used).
Stream: byte != marker -> literal. marker followed by:
    marker          -> literal marker byte
    d (d > marker: d-1), then count -> copy `count` bytes from `d` back.
"""
import struct


def decompress(data: bytes, native: bool = True) -> bytes:
    """Token-at-a-time decoder: literal runs are copied in bulk (bytes.find for the marker), so the
    Python loop runs once per back-reference instead of once per byte.  The native codec (d5lib.lzs_native) is
    used when available."""
    if native:
        from . import lzs_native
        if lzs_native.available():
            return lzs_native.decompress(data)
    data = bytes(data)
    ext, usize, csize, marker = struct.unpack_from("<4sIII", data, 0)
    marker &= 0xFF
    mk = bytes([marker])
    find = data.find
    out = bytearray()
    i = 16
    end = len(data)
    while i < end:
        j = find(mk, i)
        if j < 0:
            out += data[i:]
            break
        if j > i:
            out += data[i:j]
        d = data[j + 1]
        if d == marker:
            out.append(marker)
            i = j + 2
            continue
        if d > marker:
            d -= 1
        n = data[j + 2]
        i = j + 3
        start = len(out) - d
        if n <= d:
            out += out[start:start + n]
        else:  # overlapping copy = repeat the last d bytes
            pat = out[start:start + d]
            out += (pat * (n // d + 1))[:n]
    if len(out) != usize:
        raise ValueError(f"LZS size mismatch {len(out)} != {usize}")
    return bytes(out)


def header_ext(data: bytes) -> bytes:
    return data[:4]
