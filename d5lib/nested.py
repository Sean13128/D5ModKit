"""Plain (non-obfuscated) NISPACK nested inside Start_*.dat (Texture.dat, Effect.dat, charworld.dat)."""
import struct


def is_plain_nispack(buf: bytes) -> bool:
    return buf[:8] == b"NISPACK\0"


def read_plain(buf: bytes):
    cnt = struct.unpack_from("<I", buf, 12)[0]
    out = []
    for i in range(cnt):
        n, o, s, t = struct.unpack_from("<32sIII", buf, 16 + i * 44)
        out.append((n.split(b"\0")[0].decode("ascii", "replace"), buf[o:o + s], t))
    return out


def write_plain(files, align=0x800):
    """files: list of (name, data, stamp)."""
    count = len(files)
    pos = (16 + count * 44 + align - 1) // align * align
    table = bytearray()
    blobs = []
    for name, data, stamp in files:
        table += struct.pack("<32sIII", name.encode("ascii")[:32], pos, len(data), stamp)
        blobs.append((pos, data))
        pos = (pos + len(data) + align - 1) // align * align
    out = bytearray(b"NISPACK\0" + struct.pack("<II", 0, count) + table)
    for off, data in blobs:
        out += b"\0" * (off - len(out))
        out += data
    out += b"\0" * ((len(out) + align - 1) // align * align - len(out))
    return bytes(out)
