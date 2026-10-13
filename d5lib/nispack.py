"""NISPACK archive reader/writer (Disgaea 5 PC, obfuscated with crypt.decode)."""
import os
import struct
from dataclasses import dataclass
from . import crypt

ALIGN = 0x800
ENTRY_SIZE = 44


@dataclass
class Entry:
    name: str
    offset: int
    size: int
    stamp: int


class NisPack:
    def __init__(self, path):
        self.path = path
        self.fh = open(path, "rb")
        head = crypt.decode(self.fh.read(16))
        if head[:8] != b"NISPACK\0":
            raise ValueError(f"{path}: not a NISPACK archive")
        self.unk, count = struct.unpack_from("<II", head, 8)
        table = crypt.decode(self.fh.read(count * ENTRY_SIZE))
        self.entries = []
        for i in range(count):
            name, off, size, stamp = struct.unpack_from("<32sIII", table, i * ENTRY_SIZE)
            self.entries.append(Entry(name.split(b"\0")[0].decode("ascii", "replace"), off, size, stamp))
        self.by_name = {e.name.lower(): e for e in self.entries}

    def close(self):
        self.fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def read(self, entry) -> bytes:
        if isinstance(entry, str):
            entry = self.by_name[entry.lower()]
        self.fh.seek(entry.offset)
        return crypt.decode(self.fh.read(entry.size))

    def names(self):
        return [e.name for e in self.entries]


def write_nispack(path, files, unk=0):
    """files: list of (name, bytes, stamp). Writes obfuscated archive."""
    count = len(files)
    header_len = 16 + count * ENTRY_SIZE
    pos = (header_len + ALIGN - 1) // ALIGN * ALIGN
    table = bytearray()
    layout = []
    for name, data, stamp in files:
        nb = name.encode("ascii")[:32]
        table += struct.pack("<32sIII", nb, pos, len(data), stamp)
        layout.append((pos, data))
        pos = (pos + len(data) + ALIGN - 1) // ALIGN * ALIGN
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(crypt.encode(b"NISPACK\0" + struct.pack("<II", unk, count) + bytes(table)))
        for off, data in layout:
            cur = f.tell()
            if cur < off:
                f.write(crypt.encode(b"\0" * (off - cur)))
            f.write(crypt.encode(data))
        end = f.tell()
        padto = (end + ALIGN - 1) // ALIGN * ALIGN
        if padto > end:
            f.write(crypt.encode(b"\0" * (padto - end)))
    os.replace(tmp, path)
