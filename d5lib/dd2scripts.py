"""Disgaea D2 (PS3, BLUS31313) event scripts read as the D4 scene language (DD2SPEC1, offline).

DD2's script.dat is the same NIS event-script VM as D4 / D5 (d5lib.script), stored big-endian:

* directory: BE u32 count, BE u32 offset[count], BE u32 event_id[count], code (as script.py, other endianness);
* opcode: two bytes, group then sub (the same byte order as D5, which writes ``c >> 8, c & 0xFF``);
* operand slot: u8 tag; tag 0 -> BE literal of the declared width, tag != 0 -> BE u16 variable id;
* the custom forms are the D5 ones: 0x0104 / 0x0106 (slot3 event, slot1 n, n x slot4), 0x0140 (BE s16 skip, u8 n,
  conditions), 0x1400 / 0x1410 (u8, BE u16 variable, u8 op, slot2), 0x6E20 (u8 length + bytes).

Operand widths come from DD2's own command registrations (native RTTI, 506 records: DD2EVENT1
``voices/dd2event1/scripts/survey_scripts.py``, constructor 0x9ce2c..0xa4380 of the pinned EBOOT.elf). 490 of the
500 typed records have exactly the widths of D4 (d4inventory.D4_SIGNATURES over D5's table); the 10 that differ are
sound / voice commands (0x4600..0x4630: wider sound ids) plus 0x78b7 (no operand). They are listed in DD2_WIDTHS.

``transcode`` rewrites the code into D5's little-endian byte layout instruction by instruction (no value changes, the
same instruction boundaries, so 0x0140 skips stay valid); ``Source`` then reads it with the D4 reader (d4scripts),
so the D4 converter's rules apply unchanged where DD2 and D4 share a command. Nothing here asserts that a command
*means* the same in DD2 as in D4; that is the converter's per-rule evidence.
"""
from __future__ import annotations

import hashlib
import importlib.util
import struct

from . import d4inventory, d4scripts, dd2source, script

# DD2 registration widths that differ from the D4 reader (D5 table + D4_SIGNATURES); the other typed records match.
DD2_WIDTHS = {
    0x4600: [2], 0x4602: [2, 4], 0x4604: [2, 1], 0x4606: [2, 1], 0x460A: [2], 0x460C: [2],
    0x4620: [1, 4], 0x4622: [1, 4, 1], 0x4630: [4, 1], 0x78B7: [],
}
def reader():
    """An isolated D4 script reader with DD2's widths (D5's and D4's tables are never mutated)."""
    spec = importlib.util.spec_from_file_location("d5lib._dd2_script", script.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SIGS.update({k: list(v) for k, v in d4inventory.D4_SIGNATURES.items()})
    module.SIGS.update({k: list(v) for k, v in DD2_WIDTHS.items()})
    return module


def open_pack(path):
    """a DD2 NISPACK archive from disk (d5lib.dd2source.Nispack: ``read(name)``)"""
    with open(path, "rb") as f:
        return dd2source.Nispack(f.read())


def _slot(code, q, width, out):
    tag = code[q]
    w = width if tag == 0 else 2
    out.append(tag)
    out += code[q + 1:q + 1 + w][::-1]
    if q + 1 + w > len(code):
        raise ValueError("truncated operand")
    return q + 1 + w


def transcode_event(code, sigs):
    """One event's DD2 (big-endian) code -> the same instructions in D5's little-endian layout."""
    out, q = bytearray(), 0
    while q < len(code):
        if q + 2 > len(code):
            raise ValueError("truncated opcode")
        cid = code[q] << 8 | code[q + 1]
        out += code[q:q + 2]
        q += 2
        if cid in (0x0104, 0x0106):
            q = _slot(code, q, 3, out)
            if code[q] != 0:
                raise ValueError("call with a variable argument count")
            n = code[q + 1]
            q = _slot(code, q, 1, out)
            for _ in range(n):
                q = _slot(code, q, 4, out)
        elif cid == 0x0140:
            out += code[q:q + 2][::-1]
            n = code[q + 2]
            out.append(n)
            q += 3
            for i in range(n):
                q = _slot(code, q, 2, out)
                out.append(code[q])
                q = _slot(code, q + 1, 2, out)
                if i < n - 1:
                    out.append(code[q])
                    q += 1
        elif cid in (0x1400, 0x1410):
            out.append(code[q])
            out += code[q + 1:q + 3][::-1]
            out.append(code[q + 3])
            q = _slot(code, q + 4, 2, out)
        elif cid == 0x6E20:
            n = code[q]
            out += code[q:q + 1 + n]
            q += 1 + n
        elif cid in sigs:
            for width in sigs[cid]:
                q = _slot(code, q, width, out)
        else:
            raise ValueError(f"unknown script command {cid:04x}")
        if q > len(code):
            raise ValueError("instruction overruns its event")
    return bytes(out)


def transcode(raw, sigs=None):
    """DD2 script.dat (big-endian) -> (D5-layout script.dat bytes, {event id: error} for events kept verbatim).

    An event that does not frame is copied byte for byte (its D4-reader parse then fails, as it should)."""
    sigs = sigs or reader().SIGS
    count = struct.unpack_from(">I", raw)[0]
    base = 4 + 8 * count
    offsets = list(struct.unpack_from(f">{count}I", raw, 4))
    ids = struct.unpack_from(f">{count}I", raw, 4 + 4 * count)
    if offsets and (offsets[0] != 0 or offsets != sorted(offsets) or base + offsets[-1] > len(raw)):
        raise ValueError("invalid DD2 script directory")
    ends = offsets[1:] + [len(raw) - base]
    blobs, failed = [], {}
    for eid, lo, hi in zip(ids, offsets, ends):
        code = raw[base + lo:base + hi]
        try:
            blobs.append(transcode_event(code, sigs))
        except (ValueError, IndexError) as ex:
            failed[eid] = str(ex)
            blobs.append(code)
    new_offsets, p = [], 0
    for blob in blobs:
        new_offsets.append(p)
        p += len(blob)
    out = (struct.pack("<I", count) + struct.pack(f"<{count}I", *new_offsets)
           + struct.pack(f"<{count}I", *ids) + b"".join(blobs))
    return out, failed


class Source(d4scripts.Source):
    """d4scripts.Source over DD2's script.dat: the D4 reader with DD2's widths on the transcoded code.

    ``sha256`` is the DD2 member's own hash (source identity), ``failed`` lists events the transcoder could not frame."""

    def __init__(self, raw, language="EN"):
        self.dd2_sha256 = hashlib.sha256(raw).hexdigest()
        parser = reader()
        le, self.failed = transcode(raw, parser.SIGS)
        super().__init__(le, language)
        self.parser = parser
        self.sha256 = self.dd2_sha256
