/* NIS LZS codec for the kit (d5lib/lzs_native.py).  Same stream as d5lib/lzs.py / lzs_compress.py:
 *   byte != marker            -> literal
 *   marker, marker            -> literal marker byte
 *   marker, e, n              -> copy n bytes from distance d back (e = d if d < marker else d + 1)
 * Like the game's own encoder: distance 1..254, length 4..254 and never longer than the distance (the game's
 * decoder copies blocks and does not reproduce overlapping matches).
 * Match finder: hash chains on 4-byte keys inside the 254-byte window, longest of up to DEPTH candidates, one-step
 * lazy evaluation.  Built with Zig (python -m ziglang cc -shared -O2). */
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define MAX_DIST 254
#define MAX_LEN 254
#define MIN_LEN 4
#define HBITS 16
#define DEPTH 48

__declspec(dllexport) int lzs_choose_marker(const uint8_t *in, size_t n) {
    size_t cnt[256] = {0};
    for (size_t i = 0; i < n; i++) cnt[in[i]]++;
    int best = 0;
    for (int b = 1; b < 256; b++) if (cnt[b] < cnt[best]) best = b;
    return best;
}

static inline uint32_t key4(const uint8_t *p) {
    uint32_t v = (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
    return (v * 2654435761u) >> (32 - HBITS);
}

/* longest match at i -> length (0 = none), *dist */
static int best_at(const uint8_t *in, size_t n, size_t i, const int32_t *prev, int *dist) {
    int best = 0, bd = 0;
    if (i + MIN_LEN > n) return 0;
    size_t avail = n - i;
    int maxall = avail > MAX_LEN ? MAX_LEN : (int)avail;
    int32_t c = prev[i];
    int steps = 0;
    while (c >= 0 && steps < DEPTH) {
        size_t d = i - (size_t)c;
        if (d > MAX_DIST) break;
        int maxlen = (int)d < maxall ? (int)d : maxall;
        if (maxlen > best && in[c + best] == in[i + best]) {
            int l = 0;
            while (l < maxlen && in[c + l] == in[i + l]) l++;
            if (l > best) {
                best = l;
                bd = (int)d;
                if (l == maxall) break;
            }
        }
        c = prev[c];
        steps++;
    }
    *dist = bd;
    return best >= MIN_LEN ? best : 0;
}

/* body (without the 16-byte header) into out; returns its length, or -1 when cap is too small */
__declspec(dllexport) int64_t lzs_compress_body(const uint8_t *in, size_t n, uint8_t *out, size_t cap, int marker) {
    int32_t *prev = (int32_t *)malloc((n + 1) * sizeof(int32_t));
    int32_t *head = (int32_t *)malloc(((size_t)1 << HBITS) * sizeof(int32_t));
    if (!prev || !head) { free(prev); free(head); return -2; }
    for (size_t h = 0; h < ((size_t)1 << HBITS); h++) head[h] = -1;
    /* chains: prev[i] = last earlier position with the same hash (only the window matters) */
    for (size_t i = 0; i + 3 < n; i++) {
        uint32_t h = key4(in + i);
        prev[i] = head[h];
        head[h] = (int32_t)i;
    }
    for (size_t i = (n >= 3 ? n - 3 : 0); i < n; i++) prev[i] = -1;
    free(head);
    size_t o = 0, i = 0;
    uint8_t mk = (uint8_t)marker;
#define PUT(b) do { if (o >= cap) { free(prev); return -1; } out[o++] = (uint8_t)(b); } while (0)
    while (i < n) {
        int d1 = 0, l1 = best_at(in, n, i, prev, &d1);
        if (l1 && l1 < MAX_LEN && i + 1 < n) {
            int d2 = 0, l2 = best_at(in, n, i + 1, prev, &d2);
            if (l2 > l1 + 1) {             /* lazy: a literal now, the longer match next */
                if (in[i] == mk) { PUT(mk); PUT(mk); } else PUT(in[i]);
                i++;
                l1 = l2;
                d1 = d2;
            }
        }
        if (l1) {
            int e = d1 < marker ? d1 : d1 + 1;
            PUT(mk); PUT(e); PUT(l1);
            i += (size_t)l1;
        } else {
            if (in[i] == mk) { PUT(mk); PUT(mk); } else PUT(in[i]);
            i++;
        }
    }
#undef PUT
    free(prev);
    return (int64_t)o;
}

/* stream (after the 16-byte header) -> out; returns the decoded length, or -1 on a malformed stream / small cap */
__declspec(dllexport) int64_t lzs_decompress_body(const uint8_t *in, size_t n, uint8_t *out, size_t cap, int marker) {
    size_t i = 0, o = 0;
    uint8_t mk = (uint8_t)marker;
    while (i < n) {
        uint8_t b = in[i++];
        if (b != mk) {
            if (o >= cap) return -1;
            out[o++] = b;
            continue;
        }
        if (i >= n) return -1;
        uint8_t e = in[i++];
        if (e == mk) {
            if (o >= cap) return -1;
            out[o++] = mk;
            continue;
        }
        if (i >= n) return -1;
        size_t d = e > mk ? (size_t)e - 1 : e;
        size_t cnt = in[i++];
        if (d == 0 || d > o || o + cnt > cap) return -1;
        for (size_t k = 0; k < cnt; k++) { out[o] = out[o - d]; o++; }   /* overlap-safe */
    }
    return (int64_t)o;
}

/* Yukes LZ (YKCMP_V1 type 4; d5lib/ykcmp.py _yk_lz) from src[pos..n) -> out[0..size); returns the decoded length,
 * or < 0 where the Python decoder would not give `size` bytes (it then decides) */
__declspec(dllexport) int64_t yk_lz_decompress(const uint8_t *src, size_t n, size_t pos, uint8_t *out, size_t size) {
    size_t o = 0;
    while (o < size && pos < n) {
        uint8_t b = src[pos++];
        if (b < 0x80) {
            if (pos + b > n || o + b > size) return -2;
            memcpy(out + o, src + pos, b);
            o += b;
            pos += b;
            continue;
        }
        size_t length, dist;
        if (b < 0xC0) {
            length = ((b >> 4) & 0x3) + 1;
            dist = (b & 0xF) + 1;
        } else if (b < 0xE0) {
            if (pos >= n) return -3;
            length = (b & 0x3F) + 2;
            dist = (size_t)src[pos++] + 1;
        } else {
            if (pos + 1 >= n) return -3;
            uint8_t b2 = src[pos], b3 = src[pos + 1];
            pos += 2;
            length = ((((size_t)b & 0x1F) << 4) | (b2 >> 4)) + 3;
            dist = ((((size_t)b2 & 0xF) << 8) | b3) + 1;
        }
        if (dist > o || o + length > size) return -4;
        for (size_t k = 0; k < length; k++) { out[o] = out[o - dist]; o++; }   /* overlap-safe, like the Python */
    }
    return (int64_t)o;
}
