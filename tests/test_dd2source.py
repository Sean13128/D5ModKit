"""DD2 source-table readers on synthetic bytes (no game data).

The reader itself was lifted unchanged from the accepted dd2-source-pack lane; these tests pin the
parts the DD2 coverage review relies on: the archive table, the strict count/stride check, the text
decoding, the two decoders and the Evility id numbering.
"""
import struct
import unittest

from d5lib import dd2source


def nispack(members):
    """A minimal NISPACK archive: header, one 44-byte entry per member, then the data."""
    names = list(members)
    table = dd2source.PACK_HEADER + len(names) * dd2source.PACK_ENTRY
    offset = table
    entries, body = b"", b""
    for name in names:
        data = members[name]
        field = name.encode("ascii").ljust(dd2source.PACK_NAME, b"\0")
        entries += field + struct.pack(">III", offset, len(data), 0)
        body += data
        offset += len(data)
    return b"NISPACK\0" + struct.pack(">II", 0x01000000, len(names)) + entries + body


def table(rows, stride):
    """BE16 count + two pad bytes + rows, exactly the shape every DD2 table has."""
    return struct.pack(">Hxx", len(rows)) + b"".join(rows)


class NispackTests(unittest.TestCase):
    def test_reads_members_by_name(self):
        pack = dd2source.Nispack(nispack({"char.dat": b"abc", "magic.dat": b"de"}))
        self.assertEqual(len(pack), 2)
        self.assertIn("char.dat", pack)
        self.assertEqual(pack.read("char.dat"), b"abc")

    def test_rejects_a_foreign_file(self):
        with self.assertRaises(ValueError):
            dd2source.Nispack(b"not a pack" + b"\0" * 32)


class RowTests(unittest.TestCase):
    def test_refuses_a_count_or_stride_mismatch(self):
        rows = table([b"x" * 4, b"y" * 4], 4)
        self.assertEqual(len(dd2source._rows(rows, "test", 4, 2)), 2)
        with self.assertRaises(ValueError):
            dd2source._rows(rows, "test", 4, 3)          # count disagrees with the header
        with self.assertRaises(ValueError):
            dd2source._rows(rows, "test", 8, 2)          # stride disagrees with the length

    def test_text_is_strict(self):
        self.assertEqual(dd2source._text(b"ok\0garbage", "name", "row 0"), "ok")
        with self.assertRaises(ValueError):
            dd2source._text(b"no terminator", "name", "row 0")
        with self.assertRaises(ValueError):
            dd2source._text(b"\xff\xfe\0", "name", "row 0")


class DecoderTests(unittest.TestCase):
    def _skill_row(self, ident, name, desc):
        row = bytearray(dd2source.SKILL_STRIDE)
        struct.pack_into(">H", row, 0, ident)
        row[0x0A:0x0A + len(desc)] = desc.encode()
        row[0x9E:0x9E + len(name)] = name.encode()
        row[0xCE:0xCE + len(name)] = name.encode()
        return bytes(row)

    def test_decodes_a_skill_row(self):
        row = self._skill_row(101, "Triple Strike", "Fist: three hits")
        self.assertEqual(dd2source.decode_skill(row),
                         {"id": 101, "name": "Triple Strike", "name_alt": "Triple Strike",
                          "description": "Fist: three hits"})

    def test_decodes_an_evility_row(self):
        row = bytearray(dd2source.EVILITY_STRIDE)
        struct.pack_into(">H", row, dd2source.EVILITY_ID, 2180)
        struct.pack_into(">H", row, dd2source.EVILITY_VALUE, 10)
        row[dd2source.EVILITY_VALUE2] = 200
        start, end = dd2source.EVILITY_NAME
        row[start:start + 4] = b"Name"
        start, end = dd2source.EVILITY_DESCRIPTION
        row[start:start + 4] = b"Desc"
        decoded = dd2source.decode_evility(row)
        self.assertEqual(decoded["id"], 2180)
        self.assertEqual(decoded["value"], 10)
        self.assertEqual(decoded["value2"], 200)
        self.assertEqual(decoded["name"], "Name")
        self.assertEqual(decoded["description"], "Desc")

    def test_evility_numbering_is_per_family_base(self):
        self.assertEqual(dd2source.evility_ids(2180), [2180, 2181, 2182])
        self.assertEqual(dd2source.evility_ids(80), [80, 81, 82])


if __name__ == "__main__":
    unittest.main()
