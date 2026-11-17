"""Re-encode a slightly edited LZS file without recompressing it.

NIS LZS back-references reach at most 255 bytes, so a token of the original stream can be copied
verbatim into the new stream whenever the 255 bytes before it (and its own output) are unchanged.
Edited stretches are stored as literals.  This turns "change 50 KB inside a 415 MB file" (e.g. the
resident sprite pack) into a few seconds of work and keeps the file as small as the original.

The few seconds are spent walking the old stream token by token, and an install splices the same edit into the
same pack again and again: the result of a big splice is kept in cache/lzs_splice/ as its plan (ranges of the old
file + the literals, a few MB instead of the 415 MB file), keyed by a hash of everything it depends on.
"""
import hashlib
import json
import os
import struct

WINDOW = 255
CACHE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache", "lzs_splice"))
CACHE_MIN = 16 << 20         # smaller files splice in well under a second: not worth a cache file
CACHE_KEEP = 4               # plans kept (the EN and JP packs, now and one edit ago); older ones are deleted
_MAGIC = b"LZSP1\0"


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
    runs = sorted(runs)
    key = _cache_key(old_raw, new_data, runs) if len(old_raw) >= CACHE_MIN else None
    got = _cache_load(key, old_raw) if key else None
    if got is not None:
        return got
    plan = _plan(old_raw, new_data, runs)
    out = b"".join(old_raw[p[0]:p[1]] if type(p) is tuple else p for p in plan)
    if key:
        _cache_store(key, plan, out)
    return out


def _cache_key(old_raw, new_data, runs):
    h = hashlib.sha1(_MAGIC)
    with open(__file__, "rb") as f:            # a changed splice makes other plans
        h.update(f.read())
    for part in (old_raw, new_data, json.dumps(runs).encode()):
        h.update(len(part).to_bytes(8, "little"))
        h.update(part)
    return h.hexdigest()


def _cache_load(key, old_raw):
    """the cached result, or None (none, unreadable, or not the bytes it was stored as)"""
    path = os.path.join(CACHE_DIR, key + ".bin")
    try:
        with open(path, "rb") as f:
            blob = f.read()
        if not blob.startswith(_MAGIC):
            return None
        n = int.from_bytes(blob[len(_MAGIC):len(_MAGIC) + 4], "little")
        head = json.loads(blob[len(_MAGIC) + 4:len(_MAGIC) + 4 + n])
        pos, parts = len(_MAGIC) + 4 + n, []
        for p in head["plan"]:
            if isinstance(p, list):
                parts.append(old_raw[p[0]:p[1]])
            else:
                parts.append(blob[pos:pos + p])
                pos += p
        out = b"".join(parts)
        if hashlib.sha1(out).hexdigest() != head["sha1"]:
            return None
        os.utime(path)                          # recently used: kept by the pruning
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_store(key, plan, out):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        lits = [p for p in plan if type(p) is not tuple]
        head = json.dumps({"sha1": hashlib.sha1(out).hexdigest(),
                           "plan": [list(p) if type(p) is tuple else len(p) for p in plan]}).encode()
        path = os.path.join(CACHE_DIR, key + ".bin")
        tmp = "%s.%d.tmp" % (path, os.getpid())      # one name per process: two installs never share a half-written file
        try:
            with open(tmp, "wb") as f:
                f.write(_MAGIC + len(head).to_bytes(4, "little") + head)
                f.writelines(lits)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        old = sorted((e for e in os.scandir(CACHE_DIR) if e.name.endswith(".bin")),
                     key=lambda e: e.stat().st_mtime, reverse=True)[CACHE_KEEP:]
        for e in old:
            os.remove(e.path)
    except OSError:
        pass                                    # no cache: the next install splices again


def _plan(old_raw, new_data, runs):
    """the new LZS file as a list of (start, end) ranges of old_raw and literal bytes"""
    marker = struct.unpack_from("<I", old_raw, 12)[0] & 0xFF
    mk = bytes([marker])
    esc = bytes([marker, marker])
    out = [(0, 4), b"\0" * 12]
    npos = 0

    def literal(a, b):
        if b > a:
            out.append(new_data[a:b].replace(mk, esc))

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
                out.append((copy_in_start, copy_in_end))
                npos = copy_new_end
            literal(npos, ns)
            copy_in_start, copy_in_end, copy_new_end = ins, ine, oe + shift
    if copy_in_start is not None:
        out.append((copy_in_start, copy_in_end))
        npos = copy_new_end
    literal(npos, len(new_data))
    body_len = sum(x[1] - x[0] if type(x) is tuple else len(x) for x in out[2:])
    extra = len(old_raw) - struct.unpack_from("<I", old_raw, 8)[0]     # header convention: size - 4 or size
    out[1] = struct.pack("<III", len(new_data), body_len + 16 - extra, struct.unpack_from("<I", old_raw, 12)[0])
    return out
