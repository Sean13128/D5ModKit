"""SOUNDVOICE1: installing the same voice packs twice writes the same Sound_Voice_0.dat bytes.

fafs.append_patch used to stamp every added index entry with time.time(), so the archive's sha changed on every
install although no pack changed.  The game never reads the time field."""
import hashlib
import os
import struct
import tempfile
import unittest
from unittest import mock

from d5lib import fafs


def vanilla_archive(entries):
    """FAFULLFS archive of [(name, data, stamp)], laid out like the game's (data from 0x200, index + names at the end)"""
    body = bytearray()
    placed = []
    for name, data, stamp in entries:
        data = data + b"\0" * ((-len(data)) % fafs.ALIGN)
        placed.append((name, 0x200 + len(body), len(data), stamp))
        body += data
    index_at = 0x200 + len(body)
    idx, names = bytearray(), bytearray()
    for name, off, size, stamp in sorted(placed, key=lambda p: fafs.name_hash(p[0])):
        idx += struct.pack("<6Q", fafs.name_hash(name), len(names), 0, size, off, stamp)
        names += name.encode("ascii") + b"\0"
    head = bytearray(0x200)
    head[:8] = fafs.MAGIC
    struct.pack_into("<I", head, 8, len(entries))
    struct.pack_into("<QQQ", head, 0x10, index_at + len(idx), len(names), index_at)
    return bytes(head + body + idx + names)


class AppendPatchDeterministicTests(unittest.TestCase):
    VANILLA = [("voice_en/000100.dat", b"A" * 700, 1529452820), ("voice_jp/000100.dat", b"B" * 300, 1529452900)]
    MEMBERS = {"voice_en/090070.dat": b"new-en" * 100, "voice_jp/090070.dat": b"new-en" * 100,   # stored once
               "voice_en/000100.dat": b"replaced" * 10}

    def build(self, tmp, name, clock):
        data = vanilla_archive(self.VANILLA)
        path = os.path.join(tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        with mock.patch("time.time", return_value=clock):
            fafs.append_patch(path, data[:fafs.HEADER], len(data), dict(self.MEMBERS))
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest(), path

    def test_two_installs_of_the_same_members_write_the_same_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, _ = self.build(tmp, "a.dat", 1_700_000_000.0)
            b, path = self.build(tmp, "b.dat", 1_800_000_000.0)
            self.assertEqual(a, b)
            with open(path, "rb") as f:
                entries = {e.name: e for e in fafs.read_index(f)}
                self.assertEqual(entries["voice_en/090070.dat"].stamp, 1529452900)      # newest vanilla stamp
                self.assertEqual(entries["voice_jp/090070.dat"].stamp, 1529452900)
                self.assertEqual(entries["voice_en/000100.dat"].stamp, 1529452820)      # replaced: keeps its own
                self.assertEqual(entries["voice_jp/000100.dat"].stamp, 1529452900)
                self.assertEqual(entries["voice_en/090070.dat"].offset, entries["voice_jp/090070.dat"].offset)
                pack = fafs.FafsPack(path)
                try:
                    self.assertEqual(pack.read("voice_en/000100.dat")[:80], b"replaced" * 10)
                    self.assertEqual(pack.read("voice_jp/000100.dat")[:300], b"B" * 300)
                finally:
                    pack.close()


if __name__ == "__main__":
    unittest.main()
