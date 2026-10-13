"""YKCMP_V1 container: 'YKCMP_V1' u32 type, u32 total_size(incl. header), u32 raw_size.
type 7 = zlib stream, type 4 = Yukes LZ."""
import struct
import zlib

MAGIC = b"YKCMP_V1"


def is_ykcmp(data: bytes) -> bool:
    return data[:8] == MAGIC


def _yk_lz(src: bytes, pos: int, size: int) -> bytes:
    out = bytearray()
    n = len(src)
    while len(out) < size and pos < n:
        b = src[pos]; pos += 1
        if b < 0x80:
            out += src[pos:pos + b]; pos += b
            continue
        if b < 0xC0:
            length = ((b >> 4) & 0x3) + 1
            dist = (b & 0xF) + 1
        elif b < 0xE0:
            length = (b & 0x3F) + 2
            dist = src[pos] + 1; pos += 1
        else:
            b2 = src[pos]; b3 = src[pos + 1]; pos += 2
            length = (((b & 0x1F) << 4) | (b2 >> 4)) + 3
            dist = (((b2 & 0xF) << 8) | b3) + 1
        start = len(out) - dist
        if length <= dist:
            out += out[start:start + length]
        else:
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)


def decompress(data: bytes) -> bytes:
    if not is_ykcmp(data):
        return data
    typ, total, raw = struct.unpack_from("<III", data, 8)
    if typ == 7:
        out = zlib.decompress(data[20:total])
    elif typ == 4:
        out = _yk_lz(data, 20, raw)
    else:
        raise ValueError(f"unknown YKCMP type {typ}")
    if len(out) != raw:
        raise ValueError(f"YKCMP size mismatch {len(out)} != {raw}")
    return out


def compress(raw: bytes, level: int = 9) -> bytes:
    """Always writes the zlib (type 7) variant, which the game accepts."""
    z = zlib.compress(raw, level)
    return MAGIC + struct.pack("<III", 7, len(z) + 20, len(raw)) + z
