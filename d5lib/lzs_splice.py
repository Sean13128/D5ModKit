"""Re-encode a slightly edited LZS file without recompressing it.

NIS LZS back-references reach at most 255 bytes, so a token of the original stream can be copied
verbatim into the new stream whenever the 255 bytes before it (and its own output) are unchanged.
Edited stretches are stored as literals.  This turns "change 50 KB inside a 415 MB file" (e.g. the
resident sprite pack) into a few seconds of work and keeps the file as small as the original.
"""
import struct

WINDOW = 255


def _tokens(raw):
    """Yield (in_start, in_end, out_start, out_end) of every token of an LZS stream (literal runs are
    yielded as one token each)."""
    marker = struct.unpack_from("<I", raw, 12)[0] & 0xFF
    mk = bytes([marker])
    find = raw.find
    i, o, end = 16, 0, len(raw)
    while i < end:
        j = find(mk, i)
        if j < 0:
            yield i, end, o, o + (end - i)
            return
        if j > i:
            yield i, j, o, o + (j - i)
            o += j - i
        d = raw[j + 1]
        if d == marker:
            yield j, j + 2, o, o + 1
            o += 1
            i = j + 2
            continue
        n = raw[j + 2]
        yield j, j + 3, o, o + n
        o += n
        i = j + 3


def splice(old_raw: bytes, new_data: bytes, runs) -> bytes:
    """old_raw: original LZS file.  new_data: the new decompressed content.  runs: [(new_off, old_off,
    length)] stretches where new_data[new_off:new_off+length] == old data[old_off:old_off+length]
    (sorted by new_off, non-overlapping).  Returns a valid LZS file for new_data."""
    marker = struct.unpack_from("<I", old_raw, 12)[0] & 0xFF
    mk = bytes([marker])
    esc = bytes([marker, marker])
    out = [old_raw[:4], b"\0" * 12]
    npos = 0

    def literal(a, b):
        if b > a:
            out.append(new_data[a:b].replace(mk, esc))

    runs = sorted(runs)
    ri = 0
    # usable window of the current run in OLD coordinates
    def usable(r):
        new_off, old_off, length = r
        return old_off + WINDOW, old_off + length, new_off - old_off

    cur = usable(runs[0]) if runs else None
    copy_in_start = copy_in_end = None     # pending contiguous copy of old tokens
    copy_new_end = None
    for ins, ine, os_, oe in _tokens(old_raw):
        while cur is not None and os_ >= cur[1]:
            ri += 1
            cur = usable(runs[ri]) if ri < len(runs) else None
        if cur is None:
            break
        lo, hi, shift = cur
        if os_ >= lo and oe <= hi:
            ns = os_ + shift
            if copy_in_start is not None and ins == copy_in_end and ns == copy_new_end:
                copy_in_end, copy_new_end = ine, oe + shift          # extend the pending copy
                continue
            if copy_in_start is not None:
                out.append(old_raw[copy_in_start:copy_in_end])
                npos = copy_new_end
            literal(npos, ns)
            copy_in_start, copy_in_end, copy_new_end = ins, ine, oe + shift
    if copy_in_start is not None:
        out.append(old_raw[copy_in_start:copy_in_end])
        npos = copy_new_end
    literal(npos, len(new_data))
    body_len = sum(len(x) for x in out[2:])
    extra = len(old_raw) - struct.unpack_from("<I", old_raw, 8)[0]     # header convention: size - 4 or size
    out[1] = struct.pack("<III", len(new_data), body_len + 16 - extra, struct.unpack_from("<I", old_raw, 12)[0])
    return b"".join(out)
