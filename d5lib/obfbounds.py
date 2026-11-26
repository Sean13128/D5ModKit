"""Native-header bounds gate for effect / object models (.obf) as Disgaea 5's loader reads them (DD2SPEC3, offline).

Walks the arithmetic of the D5 loader, not the kit's own reader (obf.Texture forces little-endian for LA88 and so
cannot see a header D5 would read the other way):

* model binding 0x1402FB7B0 / 0x1402FBDE0: the 48-byte header (u32 total, u32 version, u32 offset[10]); for the
  sections it binds it reads the first u32 at each section offset (the table counts); the vertex count is
  (offset[9] - offset[8]) / 60 (version >= 2) or / 36; the texture bank at offset[9] is u32 n, u32 off[n] and entry
  i starts at bank + off[i] (+4 = the TXF payload, its first three bytes are copied as flags);
* texture decode 0x14030FFF0 (model_decode_texture) on each TXF payload (0x140310970 first undoes a YKCMP_V1
  wrapper; one is reported, not decoded here): "DDS " -> 0x80-byte header; otherwise the u16 at +8 is the byte-order
  marker: anything but 1 (read little-endian) makes D5 byte-swap the u16 width +4, height +6, the marker and the u32
  size +12 before use. size 0 -> w*h*3 (format 0x14) or w*h*4 bytes. Else per-slice bytes by format: 0/7 w*h*4,
  9 w*h, 10/11/12/13 w*h*2, 0x14 w*h*3/2, any other format the size itself; slices = size / per-slice (an integer
  division by zero when per-slice is 0); bytes copied = per-slice * slices, memmove'd from payload + 16.
* the submesh, node and track tables (section 7, 3, 4 / 5) that the draw and animation paths index (Sorrow
  obf_format.md 3.3-3.7): every index inside its table.

check(data) -> list of problems (empty = every read and copy stays inside the model's own bytes);
textures(data) -> what D5 computes per texture (for receipts and tests).
"""
from __future__ import annotations

import struct

N = 10
PER_SLICE = {0: 4, 7: 4, 9: 1, 10: 2, 11: 2, 12: 2, 13: 2}


def native_texture(payload):
    """D5 0x14030FFF0's view of one TXF payload: dict(fmt, width, height, size, swapped, per_slice, slices, copy,
    available) or dict(error=...)."""
    if len(payload) < 16:
        return dict(error="payload shorter than the 16-byte header")
    if payload[:8] == b"YKCMP_V1":
        return dict(error="YKCMP_V1 texture payload (decompressed by 0x140310970): not modelled here")
    if payload[:4] == b"DDS ":
        if len(payload) < 0x80:
            return dict(error="DDS header shorter than 0x80")
        h, w = struct.unpack_from("<II", payload, 12)
        return dict(fmt="dds", width=w, height=h, size=w * h, swapped=False, per_slice=w * h, slices=1,
                    copy=w * h, available=len(payload) - 0x80)
    fmt = payload[0]
    w, h, marker = struct.unpack_from("<HHH", payload, 4)
    size = struct.unpack_from("<I", payload, 12)[0]
    swapped = marker != 1
    if swapped:
        w, h = struct.unpack_from(">HH", payload, 4)
        size = struct.unpack_from(">I", payload, 12)[0]
    out = dict(fmt=fmt, width=w, height=h, size=size, swapped=swapped, available=len(payload) - 16)
    if size == 0:
        per = w * h * (3 if fmt == 0x14 else 4)
        out.update(per_slice=per, slices=1, copy=per)
        return out
    per = (w * h * 3) // 2 if fmt == 0x14 else w * h * PER_SLICE[fmt] if fmt in PER_SLICE else size
    if per == 0:
        return dict(out, error="per-slice size 0: integer division by zero in the decoder")
    slices = size // per
    return dict(out, per_slice=per, slices=slices, copy=per * slices)


def _table(data, lo, hi, name, problems):
    """offset table at [lo, hi): (count, [(start, end)]) or None"""
    if hi - lo < 4:
        problems.append(f"{name}: shorter than its count")
        return None
    n = struct.unpack_from("<I", data, lo)[0]
    if 4 + 4 * n > hi - lo:
        problems.append(f"{name}: {n} offsets do not fit in {hi - lo} bytes")
        return None
    offs = list(struct.unpack_from(f"<{n}I", data, lo + 4))
    spans = []
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < n else hi - lo
        if not 4 + 4 * n <= o <= end <= hi - lo:
            problems.append(f"{name}[{i}]: entry {o}..{end} outside the table")
            return None
        spans.append((lo + o, lo + end))
    return n, spans


def check(data, *, textures_only=False):
    problems = []
    if len(data) < 48:
        return ["model shorter than its 48-byte header"]
    total, version = struct.unpack_from("<II", data)
    offs = list(struct.unpack_from(f"<{N}I", data, 8))
    if total > len(data):
        problems.append(f"declared size {total} exceeds the {len(data)} model bytes")
        return problems
    bounds = offs + [total]
    if offs[0] != 48 or any(bounds[i] > bounds[i + 1] for i in range(N)):
        problems.append(f"section offsets not ascending inside the model: {offs}")
        return problems
    for i in range(N):
        if bounds[i + 1] - bounds[i] < 4 and i not in (0, 8):
            problems.append(f"section {i}: no room for the count D5 reads")
    bank = _table(data, bounds[9], bounds[10], "section 9 textures", problems)
    if bank:
        for i, (lo, hi) in enumerate(bank[1]):
            if hi - lo < 4 + 16:
                problems.append(f"texture {i}: entry of {hi - lo} bytes has no TXF header")
                continue
            t = native_texture(data[lo + 4:hi])
            if "error" in t:
                problems.append(f"texture {i}: {t['error']}")
            elif t["copy"] == 0 and t["available"] > 0:
                problems.append(f"texture {i}: D5 decodes 0 slices ({t['width']}x{t['height']}, size {t['size']}, "
                                f"{'swapped' if t['swapped'] else 'little-endian'} header) from {t['available']} bytes")
            elif t["copy"] > t["available"]:
                problems.append(f"texture {i}: D5 copies {t['copy']} bytes ({t['width']}x{t['height']}, size "
                                f"{t['size']}, {'swapped' if t['swapped'] else 'little-endian'} header) from "
                                f"{t['available']} stored; {total - (lo + 4 + 16)} bytes left in the model")
    if textures_only:
        return problems
    vsize = 60 if version >= 2 else 36
    vertices = (bounds[9] - bounds[8]) // vsize
    textures = bank[0] if bank else 0
    keys = (bounds[6] - bounds[5]) // 16
    tracks = (bounds[5] - bounds[4]) // 40
    sub = _table(data, bounds[7], bounds[8], "section 7 submeshes", problems)
    if sub:
        head = 48 if version >= 2 else 24
        for i, (lo, hi) in enumerate(sub[1]):
            if hi - lo < head:
                problems.append(f"submesh {i}: shorter than its header")
                continue
            count, tex = struct.unpack_from("<Ii", data, lo)
            if head + 4 * count > hi - lo:
                problems.append(f"submesh {i}: {count} indices overrun the entry")
                continue
            if not -1 <= tex < max(textures, 1) and textures:
                problems.append(f"submesh {i}: texture {tex} of {textures}")
            if count and max(struct.unpack_from(f"<{count}I", data, lo + head)) >= vertices:
                problems.append(f"submesh {i}: index past the {vertices} vertices")
    nodes = _table(data, bounds[3], bounds[4], "section 3 nodes", problems)
    if nodes:
        for i, (lo, hi) in enumerate(nodes[1]):
            if hi - lo < 12:
                problems.append(f"node {i}: shorter than its header")
                continue
            n = struct.unpack_from("<I", data, lo + 8)[0]
            if 12 + 4 * n > hi - lo:
                problems.append(f"node {i}: {n} track sets overrun the entry")
                continue
            if n and max(struct.unpack_from(f"<{n}I", data, lo + 12)) >= tracks:
                problems.append(f"node {i}: track set past the {tracks} in section 4")
    if tracks:
        ks = struct.unpack_from(f"<{tracks * 10}I", data, bounds[4])
        if max(ks) >= keys:
            problems.append(f"section 4: key index {max(ks)} past the {keys} keys")
    return problems


def textures(data):
    """[(index, native_texture dict)] for the model's texture bank (for receipts)"""
    total = struct.unpack_from("<I", data)[0]
    offs = list(struct.unpack_from(f"<{N}I", data, 8)) + [total]
    problems = []
    bank = _table(data, offs[9], offs[10], "section 9", problems)
    return [(i, native_texture(data[lo + 4:hi])) for i, (lo, hi) in enumerate(bank[1])] if bank else []
