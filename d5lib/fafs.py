"""Data/Sound_Voice/Sound_Voice_0.dat: the 'FAFULLFS' archive of the voice packs (read in disgaea5.exe at
0x140877ea1 (loader) and 0x1408770b0 (lookup)).

Header (the first file starts at 0x200):
    +0x00 'FAFULLFS'
    +0x08 u32 count              +0x0c u16 108, u16 108 (not read by the loader)
    +0x10 u64 name table offset  (= index offset + count * 48)
    +0x18 u64 name table size
    +0x20 u64 index offset
Index: count x 48 bytes {u64 hash, u64 name offset (in the name table), u64 0, u64 size (0x200-aligned), u64 offset,
u64 timestamp}, sorted by hash (the game searches it with a lower bound, then compares the name).  The name table
('voice_en/000100.dat\\0' ...) follows the index.

Hash of a name (bytes): 8 bytes, byte i starts as len(name) ^ KEY[i]; then byte (k % 8) ^= name[k] for every k.

The files are 'DSARC FL' packs (d5lib.sound) of voice lines NNNNNNNNN.vag; pack voice_en/NNNNNN.dat (and voice_jp/)
holds the lines of voice set NNNNNN (d5lib.voices).

Mods add packs by appending them after the vanilla end with a new index + name table behind them (the vanilla bytes
stay as they are; restoring = the vanilla header back + truncate)."""
import struct
import time

from . import sound

MAGIC = b"FAFULLFS"
HEADER = 0x200
ALIGN = 0x200
ENTRY = 48
KEY = (0x54, 0xA3, 0x8A, 0x2B, 0x36, 0x70, 0xDE, 0xEF)


def name_hash(name):
    b = name.encode("ascii") if isinstance(name, str) else bytes(name)
    k = [(len(b) & 0xFF) ^ c for c in KEY]
    for i, c in enumerate(b):
        k[i & 7] ^= c
    return struct.unpack("<Q", bytes(k))[0]


def is_fafs(head):
    return head[:8] == MAGIC


class Entry:
    __slots__ = ("name", "offset", "size", "stamp")

    def __init__(self, name, offset, size, stamp=0):
        self.name, self.offset, self.size, self.stamp = name, offset, size, stamp


def read_index(fh, header=None):
    """[Entry] of an open archive; `header`: the vanilla header (the installer's backup) to read the vanilla index"""
    if header is None:
        fh.seek(0)
        header = fh.read(0x30)
    if not is_fafs(header):
        raise ValueError("not a FAFULLFS archive")
    count = struct.unpack_from("<I", header, 8)[0]
    names_at, names_len, index_at = struct.unpack_from("<QQQ", header, 0x10)
    fh.seek(index_at)
    idx = fh.read(count * ENTRY)
    fh.seek(names_at)
    names = fh.read(names_len)
    out = []
    for i in range(count):
        h, no, _, size, off, stamp = struct.unpack_from("<6Q", idx, i * ENTRY)
        end = names.find(b"\0", no)
        out.append(Entry(names[no:end].decode("ascii", "replace"), off, size, stamp))
    return out


class FafsPack:
    """Reader with the GameFS pack interface (names / by_name / read); member names are 'voice_en/000100.dat'"""

    def __init__(self, path, header=None):
        self.path = path
        self.fh = open(path, "rb")
        self.entries = read_index(self.fh, header)
        self.by_name = {e.name.lower(): e for e in self.entries}

    def names(self):
        return [e.name for e in self.entries]

    def read(self, entry):
        e = entry if isinstance(entry, Entry) else self.by_name[str(entry).replace("\\", "/").lower()]
        self.fh.seek(e.offset)
        return self.fh.read(e.size)

    def close(self):
        try:
            self.fh.close()
        except Exception:
            pass


def pack_members(data):
    """{member name: bytes} of a DSARC FL pack"""
    out = {}
    for e in sound.parse_toc(data):
        out[e.name] = data[e.offset:e.offset + e.size]
    return out


def build_pack(files):
    """DSARC FL pack of {name: bytes} (names in the given order), every file 0x200-aligned like the game's"""
    names = list(files)
    head = 16 + len(names) * sound.DSARC_ENTRY
    pos = (head + ALIGN - 1) // ALIGN * ALIGN
    toc, body = [], bytearray()
    for n in names:
        d = files[n]
        toc.append((n, len(d), pos + len(body)))
        body += d
        body += b"\0" * ((-len(body)) % ALIGN)
    out = bytearray(sound.DSARC_MAGIC + struct.pack("<Q", len(names)))
    for n, ln, off in toc:
        out += struct.pack("<116sIII", n.encode("ascii"), ln, off, 0)
    out += b"\0" * (pos - len(out))
    out += body
    out += b"\0" * ((-len(out)) % ALIGN)
    return bytes(out)


def append_patch(path, vanilla_header, vanilla_size, members, log=None):
    """Write `members` ({'voice_en/NNNNNN.dat': bytes}, new or replacing) after the vanilla end of the archive at
    `path`, then a new index + name table, then the header.  Identical member data is stored once."""
    with open(path, "r+b") as f:
        entries = read_index(f, vanilla_header)
        by_name = {e.name.lower(): e for e in entries}
        stamp = int(time.time())
        end = (vanilla_size + ALIGN - 1) // ALIGN * ALIGN
        f.seek(vanilla_size)
        f.write(b"\0" * (end - vanilla_size))
        stored = {}
        for name, data in members.items():
            name = name.replace("\\", "/").lower()
            data = data + b"\0" * ((-len(data)) % ALIGN)
            e = by_name.get(name)
            if e is None:
                e = Entry(name, 0, 0, stamp)
                entries.append(e)
                by_name[name] = e
            key = hash(data), len(data)
            if key in stored and stored[key][1] == data:
                e.offset, e.size = stored[key][0], len(data)
                continue
            f.seek(end)
            f.write(data)
            e.offset, e.size = end, len(data)
            stored[key] = (end, data)
            end += len(data)
        entries.sort(key=lambda e: name_hash(e.name))
        names = bytearray()
        idx = bytearray()
        for e in entries:
            idx += struct.pack("<6Q", name_hash(e.name), len(names), 0, e.size, e.offset, e.stamp)
            names += e.name.encode("ascii") + b"\0"
        index_at = end
        f.seek(index_at)
        f.write(idx)
        f.write(names)
        f.truncate(index_at + len(idx) + len(names))
        head = bytearray(vanilla_header[:HEADER])
        struct.pack_into("<I", head, 8, len(entries))
        struct.pack_into("<QQQ", head, 0x10, index_at + len(idx), len(names), index_at)
        f.seek(0)
        f.write(head)
    if log:
        log(f"  voice archive: {len(members)} pack(s), {len(entries)} files")
