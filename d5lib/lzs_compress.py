"""NIS LZS compressor (inverse of d5lib.lzs.decompress).

Stream format (see lzs.py):  header ext[4], u32 raw_size, u32 csize (= file length - 4), u32 marker
    byte != marker            -> literal
    marker, marker            -> literal marker byte
    marker, e, n              -> copy n bytes from distance d back, where e = d if d < marker else d + 1
So distance d is 1..254 and count n is 1..255 (overlapping copies allowed).

Match finder: exact 4-byte keys.  For every position the most recent earlier position with the same
4 bytes is computed vectorised with numpy (stable argsort of the keys = hash chains without
collisions).  The greedy parser then only visits positions that *have* a candidate within the
254-byte window, emitting everything else as bulk literal runs, so the Python loop runs once per
match token rather than once per byte.  Each match walks up to `depth` older chain links and picks
the longest one; an optional one-step lazy evaluation improves ratio slightly.
"""
import struct

import numpy as np

MAX_DIST = 254
MAX_LEN = 254                # the original encoder never uses 255
MIN_LEN = 4


def choose_marker(data: bytes) -> int:
    counts = np.bincount(np.frombuffer(data, np.uint8), minlength=256)
    return int(np.argmin(counts))


def _prev_links(arr: np.ndarray) -> np.ndarray:
    """prev[i] = largest j < i with data[j:j+4] == data[i:i+4], or -1 (int64 array of len n-3)."""
    n = len(arr)
    if n < 4:
        return np.full(0, -1, np.int64)
    a = arr.astype(np.uint32)
    keys = a[:-3] | (a[1:-2] << 8) | (a[2:-1] << 16) | (a[3:] << 24)
    order = np.argsort(keys, kind="stable")
    sk = keys[order]
    prev = np.full(len(keys), -1, np.int64)
    same = sk[1:] == sk[:-1]
    prev[order[1:][same]] = order[:-1][same]
    return prev


def compress(data: bytes, tag: bytes = b"pac", depth: int = 16, lazy: bool = True, native: bool = True) -> bytes:
    """Compress `data` into a complete .lzs file. `tag` is the 3-4 byte extension ('pac', 'dat').
    Uses the native codec (d5lib.lzs_native, same stream rules) when it is available."""
    if native:
        from . import lzs_native
        if lzs_native.available():
            return lzs_native.compress(data, tag)
    data = bytes(data)
    n = len(data)
    marker = choose_marker(data) if n else 0
    mk = bytes([marker])
    mk2 = mk + mk
    arr = np.frombuffer(data, np.uint8)
    prev = _prev_links(arr)
    npos = len(prev)
    if npos:
        idx = np.arange(npos, dtype=np.int64)
        has = (prev >= 0) & (idx - prev <= MAX_DIST)
        cand = np.flatnonzero(has)
    else:
        cand = np.zeros(0, np.int64)
    cand_l = cand.tolist()
    prev_l = prev.tolist()
    ncand = len(cand_l)

    out = []
    ap = out.append

    def best_at(j):
        """longest match at j -> (length, distance); length 0 if none.
        Like the game's own encoder: never overlapping (length <= distance) and length <= 254 —
        the game's decoder copies blocks and does not reproduce overlapping matches."""
        maxlen_all = n - j
        if maxlen_all > MAX_LEN:
            maxlen_all = MAX_LEN
        best_len = 0
        best_d = 0
        c = prev_l[j]
        steps = 0
        while c >= 0 and steps < depth:
            d = j - c
            if d > MAX_DIST:
                break
            maxlen = maxlen_all if maxlen_all < d else d
            if maxlen < MIN_LEN or maxlen <= best_len:
                c = prev_l[c] if c < npos else -1
                steps += 1
                continue
            if data[c:c + maxlen] == data[j:j + maxlen]:
                ln = maxlen
            else:
                lo, hi = MIN_LEN, maxlen  # prefix of lo bytes matches (keys equal), hi does not
                if best_len >= lo:
                    if data[c:c + best_len + 1] != data[j:j + best_len + 1]:
                        c = prev_l[c] if c < npos else -1
                        steps += 1
                        continue
                    lo = best_len + 1
                while hi - lo > 1:
                    mid = (lo + hi) >> 1
                    if data[c:c + mid] == data[j:j + mid]:
                        lo = mid
                    else:
                        hi = mid
                ln = lo
            if ln > best_len:
                best_len, best_d = ln, d
                if ln == maxlen_all:
                    break
            c = prev_l[c] if c < npos else -1
            steps += 1
        return best_len, best_d

    i = 0
    k = 0
    while i < n:
        # next position >= i that has a candidate
        while k < ncand and cand_l[k] < i:
            k += 1
        if k >= ncand:
            ap(data[i:].replace(mk, mk2))
            break
        j = cand_l[k]
        ln, d = best_at(j)
        if ln < MIN_LEN:
            # candidate existed but match < 4 (cannot happen with exact keys, safety)
            ap(data[i:j + 1].replace(mk, mk2))
            i = j + 1
            continue
        if lazy and ln < MAX_LEN and j + 1 < npos and prev_l[j + 1] >= 0 and j + 1 - prev_l[j + 1] <= MAX_DIST:
            ln2, d2 = best_at(j + 1)
            if ln2 > ln + 1:
                j += 1
                ln, d = ln2, d2
        if j > i:
            ap(data[i:j].replace(mk, mk2))
        e = d if d < marker else d + 1
        ap(bytes((marker, e, ln)))
        i = j + ln
    body = b"".join(out)
    ext = bytes(tag[:4]).rstrip(b"\0")[:3].ljust(4, b"\0")
    head = ext + struct.pack("<III", n, len(body) + 12, marker)
    return head + body


def selftest(data: bytes, tag=b"pac") -> dict:
    """Compress + decompress with d5lib.lzs; returns stats (raises on mismatch)."""
    import time
    from . import lzs
    t = time.time()
    c = compress(data, tag)
    t1 = time.time() - t
    t = time.time()
    d = lzs.decompress(c)
    t2 = time.time() - t
    if d != data:
        raise AssertionError("LZS round trip mismatch")
    return {"raw": len(data), "comp": len(c), "ratio": len(c) / max(1, len(data)),
            "compress_s": t1, "decompress_s": t2}
