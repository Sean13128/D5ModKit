"""'pac' sub-archive found in map*.lzs after LZS decompression.
u32 count, 12 pad, then count * (u32 offset, char name[28]); offsets relative to data start."""
import struct


def read_pac(buf: bytes):
    count = struct.unpack_from("<I", buf, 0)[0]
    base = 16 + count * 32
    ents = []
    for i in range(count):
        off, name = struct.unpack_from("<I28s", buf, 16 + i * 32)
        ents.append([name.split(b"\0")[0].decode("ascii", "replace"), base + off])
    out = []
    for i, (name, off) in enumerate(ents):
        end = ents[i + 1][1] if i + 1 < count else len(buf)
        out.append((name, buf[off:end]))
    return out


def write_pac(files):
    count = len(files)
    head = bytearray(struct.pack("<I", count) + b"\0" * 12)
    body = bytearray()
    for name, data in files:
        head += struct.pack("<I28s", len(body), name.encode("ascii")[:28])
        body += data
    return bytes(head + body)
