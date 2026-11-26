/* d5learn.inc.c -- persistence for the learned-evility capacity extension (.d5lc).  EVCAP3.
 *
 * WHAT THIS IS
 *   d5lib/learned.py builds the .d5lc section: 143 call sites of the game's "is this evility learned?" /
 *   "learn it" functions are redirected into wrappers that own every Skill.dat row at position 1,000 or
 *   later (positions 0..999 stay the game's own 1,000-bit bitmap, which is never written).  That store is
 *   memory only.  This file carries it across a save and a load:
 *
 *     save   asm (lc_save_relay, patch sites 0x140754C5C / 0x140744FE2 -- the two `call`s of the game's
 *            slot writer data_save_io_make_header 0x1407436D0) reports the slot the game wrote, and only
 *            when the writer answered 0 (both writes done, file closed).  This code builds the path the
 *            game built ("%s/Save_%03d.sav" / "%s/AutoSave.sav" from the game's own save folder), checks
 *            that the file really is a slot file of this game's format, hashes it and writes a versioned
 *            companion next to it, "<save>.d5learn.json", bound to that file's sha256.  The save file is
 *            only read here.  (EVCAP3 bound this to 0x14074749E, a DeleteFileW call; see INTEG12-REPORT.md
 *            finding 1 and EVCAP4-REPORT.md -- that site is no longer patched.)
 *     load   asm (lc_load_relay, patch site 0x14074D846) reports the slot the game just decoded (and
 *            whether the decode succeeded); this code replaces the store with the companion's contents.
 *
 *   All file work and all store mutation happens in learn_tick(), called from d5_frame -- i.e. on the
 *   game's main thread, which is the only thread that ever writes the store (learning happens on script
 *   and UI paths).  The relays themselves only publish a slot / a slot and a sequence number; the save
 *   relay runs on the writer thread and the load relay on the loader thread, so neither may touch the store
 *   or a file.
 *
 * FAIL CLOSED
 *   - No companion, or one that does not parse / does not match this save's bytes or this Skill table's
 *     generation: the store is emptied (nothing from a previous save leaks into this one) and the game runs
 *     on its native bitmap alone.  The refused file is kept as "<save>.d5learn.json.rejected".
 *   - Ids the live table does not have are counted and kept in the companion's "quarantine" list, never
 *     silently dropped.
 *   - The Skill table's first lc_base_count ids must still match the ones the build recorded (the same
 *     guard the wrappers use).  If they do not, nothing is written at all: a companion for a table this
 *     build cannot interpret would be a lie.
 *   - The native save is never opened for writing.
 *   - An agent run never writes under SaveData.  With [debug] remote=1 d5ctl fails the game's own
 *     CreateFile/DeleteFile calls there, so no save can have reached the disk in such a run; this runtime's
 *     file work does not go through the game's IAT and would not be blocked, so it refuses it itself
 *     (lc_may_write): no companion is written, rotated, renamed or removed, and a companion that would be
 *     refused is left where it is.  The store still *applies* a companion -- reading is allowed.
 *
 * The host build (D5LEARN_HOST) is the offline test target: evility/evcap3_host.c builds this same file
 * for the host with a synthetic PE image and drives every path with real files.  Nothing here is
 * conditional on the game being present.
 */

#if defined(D5LEARN_HOST)
#include <stdint.h>
#include <unistd.h>
extern unsigned char *d5learn_host_image(void);
#define LC_IMAGE() d5learn_host_image()
#define LC_RENAME(a, b, replace) (rename((a), (b)) == 0)
#define LC_FSYNC(fp) (fsync(fileno(fp)) == 0)
#pragma pack(push, 1)
typedef struct { unsigned short e_magic, e_cblp, e_cp, e_crlc, e_cparhdr, e_minalloc, e_maxalloc, e_ss, e_sp,
                 e_csum, e_ip, e_cs, e_lfarlc, e_ovno, e_res[4], e_oemid, e_oeminfo, e_res2[10];
                 int e_lfanew; } LC_DOS;
typedef struct { unsigned char Name[8]; unsigned int VirtualSize, VirtualAddress, SizeOfRawData,
                 PointerToRawData, PointerToRelocations, PointerToLinenumbers;
                 unsigned short NumberOfRelocations, NumberOfLinenumbers; unsigned int Characteristics; } LC_SEC;
typedef struct { unsigned int Signature; unsigned short Machine, NumberOfSections;
                 unsigned int TimeDateStamp, PointerToSymbolTable, NumberOfSymbols;
                 unsigned short SizeOfOptionalHeader, Characteristics; } LC_NT;
#pragma pack(pop)
#define LC_SIG 0x00004550u
#define LC_NFILESECTIONS(nt) ((nt)->NumberOfSections)
#define LC_VSIZE(sh) ((sh)->VirtualSize)
#else
#define LC_IMAGE() ((unsigned char *)GetModuleHandleA(NULL))
#include <stdint.h>
#define LC_RENAME(a, b, replace) \
    (MoveFileExA((a), (b), (replace) ? MOVEFILE_REPLACE_EXISTING : 0) != 0)
#define LC_FSYNC(fp) (_commit(_fileno(fp)) == 0)
#include <io.h>
#define LC_DOS IMAGE_DOS_HEADER
#define LC_NT IMAGE_NT_HEADERS64
#define LC_SEC IMAGE_SECTION_HEADER
#define LC_SIG IMAGE_NT_SIGNATURE
#define LC_NFILESECTIONS(nt) ((nt)->FileHeader.NumberOfSections)
#define LC_VSIZE(sh) ((sh)->Misc.VirtualSize)
/* Is this an agent run?  d5ctl fails CreateFile/DeleteFile under SaveData while [debug] remote=1, so this
 * runtime's own file work is the ONLY way anything under SaveData can change in such a run.  See
 * lc_may_write(): while remote, the companion is read and applied, never written, renamed or removed. */
#define LC_REMOTE() (g_remote)
#endif

#if defined(D5LEARN_HOST)
int d5learn_host_remote;                     /* the host harness sets this ("remote=1") */
#undef LC_REMOTE
#define LC_REMOTE() (d5learn_host_remote)
#endif

#define LC_MAGIC        0x4C43564535313044ull      /* "D510E VCL" -- same marker d5lib/learned.py scans for */
#define LC_VERSION      3u                         /* the section layout (claim byte) */
#define LC_DOC_SCHEMA   2u                         /* the companion document: unchanged by EVCAP4 */
#define LC_BITMAP_BITS  1000
#define LC_MAX_PATH     512
#define LC_MAX_SAVE     (64u << 20)               /* a save block is ~8.9 MB; refuse anything absurd */
#define LC_MAX_QUAR     256
/* what a slot file this game wrote looks like: a 0x1C0-byte header that starts with this nibble-transformed
 * text, then the encoded block, whose first qword is the container magic (untransformed).  Both were read
 * off the pinned build's writer (data_save_io_make_header 0x1407436D0: builtin_strncpy of the text, the
 * nibble swap loop, then savefile_encode_slot 0x140744730 writing the magic first) and checked against real
 * Save_001.sav / AutoSave.sav.  A file that does not start this way did not come from that writer, so no
 * companion is written for it. */
#define LC_HDR_LEN      0x1C0
#define LC_HDR_TEXT     "NIS_DISGAEA5_COMPLETE_SAVEDATA_"
#define LC_BLOCK_MAGIC  0xE5B2688ACB279CA6ull

/* field offsets in the data block emitted by d5lib/learned.py:section_source (see data_symbols) */
#define LC_O_MAGIC 0
#define LC_O_VERSION 8
#define LC_O_STATE 12
#define LC_O_BASE_COUNT 16
#define LC_O_USED 20
#define LC_O_CAP 24
#define LC_O_GEN 28
#define LC_O_UID 32
#define LC_O_PKEY 40
#define LC_O_PMAX 48
#define LC_O_SAVEDIR 56
#define LC_O_FN_PUT 64
#define LC_O_FN_CLEAR 72
#define LC_O_PREFIX 80

static unsigned char *g_lc;                  /* the claim bytes of the .d5lc section (0 = not installed) */
static int g_lc_looked;
static unsigned long long g_lc_prefix, g_lc_store, g_lc_ev;
typedef int (*lc_fn2_t)(unsigned long long, unsigned int);
typedef void (*lc_fn0_t)(void);
static lc_fn2_t g_lc_put;
static lc_fn0_t g_lc_clear;
static unsigned long long g_lc_serial[LC_MAX_QUAR];   /* quarantined ids from the last load */
static unsigned int g_lc_qid[LC_MAX_QUAR];
static int g_lc_nq;

#define LC_A16(x) ((unsigned long long)(((unsigned long long)(uintptr_t)(x) + 15ull) & ~15ull))

static unsigned int lcu(long long off) { return *(unsigned int *)(g_lc + off); }
static unsigned int lcuv(long long off) { return *(volatile unsigned int *)(g_lc + off); }
static void lcuset(long long off, unsigned int v) { *(unsigned int *)(g_lc + off) = v; }
static unsigned long long lcu64(long long off) { return *(unsigned long long *)(g_lc + off); }

/* --------------------------------------------------------------------------------------------- init */
static void learn_init(void) {
    unsigned char *image;
    LC_DOS *dos;
    LC_NT *nt;
    LC_SEC *sh;
    int i;
    unsigned long long base_count;
    if (g_lc || g_lc_looked) return;
    g_lc_looked = 1;
    image = LC_IMAGE();
    if (!image) return;
    dos = (LC_DOS *)image;
    if (dos->e_magic != 0x5A4D) return;
    nt = (LC_NT *)(image + dos->e_lfanew);
    if (nt->Signature != LC_SIG) return;
#if defined(D5LEARN_HOST)
    sh = (LC_SEC *)((unsigned char *)nt + 24 + nt->SizeOfOptionalHeader);
#else
    sh = IMAGE_FIRST_SECTION(nt);
#endif
    for (i = 0; i < (int)LC_NFILESECTIONS(nt); i++, sh++) {
        unsigned char *p = image + sh->VirtualAddress;
        unsigned long long n = LC_VSIZE(sh), o, o2;
        if (!n || !p) continue;
        for (o = 0; o + 4 <= n; o += 4) {
            if (p[o] == 'D' && p[o + 1] == '5' && p[o + 2] == 'L' && p[o + 3] == 'C') {
                g_lc = 0;
                if (p[o + 4] != LC_VERSION) continue;   /* another lane's section or an older format */
                for (o2 = 0; o2 + 8 <= n; o2 += 8) {     /* the data block, wherever the code left it */
                    if (*(unsigned long long *)(p + o2) == LC_MAGIC) { g_lc = p + o2; break; }
                }
                if (!g_lc) continue;
                base_count = lcu(LC_O_BASE_COUNT);
                if (base_count > LC_BITMAP_BITS || lcu(LC_O_CAP) == 0 || lcu(LC_O_CAP) > (1u << 20)) {
                    logf_("learn: .d5lc claims an implausible layout (base %llu, cap %u): ignored",
                          base_count, lcu(LC_O_CAP));
                    g_lc = 0;
                    return;
                }
                /* offsets from the data block (the runtime reads fields with lcu()/lcuset()) */
                g_lc_prefix = LC_A16(LC_O_PREFIX);
                g_lc_store = LC_A16(g_lc_prefix + 4ull * base_count);
                g_lc_ev = LC_A16(g_lc_store + 16ull * lcu(LC_O_CAP));
                g_lc_put = (lc_fn2_t)(void *)lcu64(LC_O_FN_PUT);
                g_lc_clear = (lc_fn0_t)(void *)lcu64(LC_O_FN_CLEAR);
                if (!g_lc_put || !g_lc_clear)
                    logf_("learn: WARNING the section publishes no store entry points: a load cannot be applied");
                logf_("learn: .d5lc found (table %u rows base, %u slots, %u live, generation %08x)",
                      lcu(LC_O_BASE_COUNT), lcu(LC_O_CAP), lcu(LC_O_USED), lcu(LC_O_GEN));
                return;
            }
        }
    }
    g_lc = 0;
    logf_("learn: no .d5lc section in this exe (learned-evility capacity not installed)");
}

/* ------------------------------------------------------------------------------------------- sha256 */
typedef struct {
    unsigned int h[8];
    unsigned long long len;
    unsigned char buf[64];
    unsigned int n;
} LC_SHA;

static const unsigned int LC_K[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};

#define LC_ROTR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void lc_sha_block(LC_SHA *s, const unsigned char *p) {
    unsigned int w[64], a, b, c, d, e, f, g, h, t1, t2;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = ((unsigned int)p[i * 4] << 24) | ((unsigned int)p[i * 4 + 1] << 16) |
               ((unsigned int)p[i * 4 + 2] << 8) | (unsigned int)p[i * 4 + 3];
    for (i = 16; i < 64; i++) {
        unsigned int s0 = LC_ROTR(w[i - 15], 7) ^ LC_ROTR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        unsigned int s1 = LC_ROTR(w[i - 2], 17) ^ LC_ROTR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3];
    e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (i = 0; i < 64; i++) {
        unsigned int S1 = LC_ROTR(e, 6) ^ LC_ROTR(e, 11) ^ LC_ROTR(e, 25);
        unsigned int ch = (e & f) ^ ((~e) & g);
        unsigned int S0 = LC_ROTR(a, 2) ^ LC_ROTR(a, 13) ^ LC_ROTR(a, 22);
        unsigned int mj = (a & b) ^ (a & c) ^ (b & c);
        t1 = h + S1 + ch + LC_K[i] + w[i];
        t2 = S0 + mj;
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d;
    s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void lc_sha_init(LC_SHA *s) {
    static const unsigned int iv[8] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
                                       0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
    memcpy(s->h, iv, sizeof iv);
    s->len = 0;
    s->n = 0;
}

static void lc_sha_update(LC_SHA *s, const unsigned char *p, size_t n) {
    s->len += n;
    while (n) {
        size_t take = 64 - s->n;
        if (take > n) take = n;
        memcpy(s->buf + s->n, p, take);
        s->n += (unsigned int)take;
        p += take;
        n -= take;
        if (s->n == 64) {
            lc_sha_block(s, s->buf);
            s->n = 0;
        }
    }
}

static void lc_sha_final(LC_SHA *s, char hex[65]) {
    unsigned long long bits = s->len * 8;
    unsigned char pad[72];
    size_t padlen;
    int i;
    memset(pad, 0, sizeof pad);
    pad[0] = 0x80;
    padlen = (s->n < 56) ? (56 - s->n) : (120 - s->n);
    lc_sha_update(s, pad, padlen);
    for (i = 0; i < 8; i++) pad[i] = (unsigned char)(bits >> (56 - 8 * i));
    lc_sha_update(s, pad, 8);
    for (i = 0; i < 8; i++)
        snprintf(hex + i * 8, 9, "%08x", s->h[i]);
    hex[64] = 0;
}

/* --------------------------------------------------------------------------------------- JSON output */
typedef struct { char *p; size_t n, cap; int bad; } LC_SB;

static void sb_reserve(LC_SB *b, size_t extra) {
    if (b->bad) return;
    if (b->n + extra + 1 <= b->cap) return;
    {
        size_t cap = b->cap ? b->cap : 4096;
        char *q;
        while (cap < b->n + extra + 1) cap *= 2;
        q = (char *)realloc(b->p, cap);
        if (!q) { b->bad = 1; return; }
        b->p = q;
        b->cap = cap;
    }
}

static void sb_add(LC_SB *b, const char *s) {
    size_t l = strlen(s);
    sb_reserve(b, l);
    if (b->bad) return;
    memcpy(b->p + b->n, s, l);
    b->n += l;
    b->p[b->n] = 0;
}

static void sb_addf(LC_SB *b, const char *fmt, ...) {
    char tmp[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tmp, sizeof tmp, fmt, ap);
    va_end(ap);
    sb_add(b, tmp);
}

/* ---------------------------------------------------------------------------------------- JSON input */
typedef struct { const char *p, *end; int bad; } LC_CUR;

static void jw(LC_CUR *c) {
    while (c->p < c->end && (*c->p == ' ' || *c->p == '\t' || *c->p == '\r' || *c->p == '\n')) c->p++;
}

static int jexpect(LC_CUR *c, char ch) {
    jw(c);
    if (c->p >= c->end || *c->p != ch) { c->bad = 1; return 0; }
    c->p++;
    return 1;
}

static int jstring(LC_CUR *c, char *out, size_t n) {
    size_t k = 0;
    jw(c);
    if (c->p >= c->end || *c->p != '"') { c->bad = 1; return 0; }
    c->p++;
    while (c->p < c->end && *c->p != '"') {
        char ch = *c->p++;
        if (ch == '\\') {
            if (c->p >= c->end) { c->bad = 1; return 0; }
            ch = *c->p++;
            switch (ch) {
            case 'n': ch = '\n'; break;
            case 't': ch = '\t'; break;
            case 'r': ch = '\r'; break;
            case 'b': ch = '\b'; break;
            case 'f': ch = '\f'; break;
            case 'u':                                 /* names are ASCII here; decode BMP only */
                if (c->end - c->p < 4) { c->bad = 1; return 0; }
                {
                    unsigned int v = 0;
                    int i;
                    for (i = 0; i < 4; i++) {
                        char h = c->p[i];
                        v <<= 4;
                        if (h >= '0' && h <= '9') v |= (unsigned)(h - '0');
                        else if (h >= 'a' && h <= 'f') v |= (unsigned)(h - 'a' + 10);
                        else if (h >= 'A' && h <= 'F') v |= (unsigned)(h - 'A' + 10);
                        else { c->bad = 1; return 0; }
                    }
                    c->p += 4;
                    ch = (char)(v & 0x7F);                /* ASCII subset; the rest becomes '?' */
                    if (v > 0x7F) ch = '?';
                }
                break;
            case '"': case '\\': case '/': break;
            default: c->bad = 1; return 0;
            }
        }
        if (out && k + 1 < n) out[k] = ch;
        k++;
    }
    if (c->p >= c->end) { c->bad = 1; return 0; }
    c->p++;
    if (out && n) out[k < n ? k : n - 1] = 0;
    return 1;
}

static int jnumber(LC_CUR *c, long long *out) {
    int neg = 0;
    long long v = 0;
    int any = 0;
    jw(c);
    if (c->p < c->end && (*c->p == '-' || *c->p == '+')) { neg = (*c->p == '-'); c->p++; }
    while (c->p < c->end && *c->p >= '0' && *c->p <= '9') {
        if (v > (0x7FFFFFFFFFFFFFFFll - 9) / 10) { c->bad = 1; return 0; }
        v = v * 10 + (*c->p - '0');
        c->p++;
        any = 1;
    }
    if (c->p < c->end && (*c->p == '.' || *c->p == 'e' || *c->p == 'E')) { c->bad = 1; return 0; }
    if (!any) { c->bad = 1; return 0; }
    if (out) *out = neg ? -v : v;
    return 1;
}

static int jnull(LC_CUR *c) {
    jw(c);
    if (c->end - c->p >= 4 && !memcmp(c->p, "null", 4)) { c->p += 4; return 1; }
    return 0;
}

static int jskip(LC_CUR *c);

static int jskip_array(LC_CUR *c) {
    if (!jexpect(c, '[')) return 0;
    jw(c);
    if (c->p < c->end && *c->p == ']') { c->p++; return 1; }
    for (;;) {
        if (!jskip(c)) return 0;
        jw(c);
        if (c->p < c->end && *c->p == ',') { c->p++; continue; }
        return jexpect(c, ']');
    }
}

static int jskip_object(LC_CUR *c) {
    char key[64];
    if (!jexpect(c, '{')) return 0;
    jw(c);
    if (c->p < c->end && *c->p == '}') { c->p++; return 1; }
    for (;;) {
        if (!jstring(c, key, sizeof key) || !jexpect(c, ':') || !jskip(c)) return 0;
        jw(c);
        if (c->p < c->end && *c->p == ',') { c->p++; continue; }
        return jexpect(c, '}');
    }
}

static int jskip(LC_CUR *c) {
    jw(c);
    if (c->p >= c->end) { c->bad = 1; return 0; }
    switch (*c->p) {
    case '"': { char t[256]; return jstring(c, t, sizeof t); }
    case '{': return jskip_object(c);
    case '[': return jskip_array(c);
    case 't': if (c->end - c->p >= 4 && !memcmp(c->p, "true", 4)) { c->p += 4; return 1; } c->bad = 1; return 0;
    case 'f': if (c->end - c->p >= 5 && !memcmp(c->p, "false", 5)) { c->p += 5; return 1; } c->bad = 1; return 0;
    case 'n': if (jnull(c)) return 1; c->bad = 1; return 0;
    default: { long long v; return jnumber(c, &v); }
    }
}

/* ------------------------------------------------------------------------------------ the companion */
typedef struct {
    int schema, bitmap_bits, rows;
    unsigned int generation;
    long long save_size;
    char save_name[64];
    char save_sha[65];
    /* (serial, id) pairs, in file order */
    unsigned long long *serial;
    unsigned int *id;
    int npairs;
    /* ids the file already quarantined */
    unsigned long long *qserial;
    unsigned int *qid;
    int nq;
} LC_DOC;

static void doc_free(LC_DOC *d) {
    free(d->serial); free(d->id); free(d->qserial); free(d->qid);
    memset(d, 0, sizeof *d);
}

static int doc_reserve(LC_DOC *d, int n) {
    if (n <= d->npairs) return 1;
    {
        int cap = d->npairs ? d->npairs : 256;
        unsigned long long *s;
        unsigned int *i;
        while (cap < n) cap *= 2;
        s = (unsigned long long *)realloc(d->serial, (size_t)cap * sizeof *s);
        if (!s) return 0;
        d->serial = s;
        i = (unsigned int *)realloc(d->id, (size_t)cap * sizeof *i);
        if (!i) return 0;
        d->id = i;
        d->npairs = cap;
    }
    return 1;
}

static int jparse_units(LC_CUR *c, LC_DOC *d, int *used) {
    char key[64];
    if (!jexpect(c, '{')) return 0;
    jw(c);
    if (c->p < c->end && *c->p == '}') { c->p++; return 1; }
    for (;;) {
        unsigned long long serial = 0;
        int i, digits = 0;
        if (!jstring(c, key, sizeof key)) return 0;
        for (i = 0; key[i]; i++) {
            char h = key[i];
            unsigned int v;
            if (h >= '0' && h <= '9') v = (unsigned)(h - '0');
            else if (h >= 'a' && h <= 'f') v = (unsigned)(h - 'a' + 10);
            else if (h >= 'A' && h <= 'F') v = (unsigned)(h - 'A' + 10);
            else { digits = -1; break; }
            serial = (serial << 4) | v;
            digits++;
        }
        if (digits != 16) { c->bad = 1; return 0; }
        if (!jexpect(c, ':') || !jexpect(c, '{')) return 0;
        jw(c);
        if (c->p < c->end && *c->p == '}') { c->p++; }
        else {
            for (;;) {
                char field[64];
                if (!jstring(c, field, sizeof field) || !jexpect(c, ':')) return 0;
                if (!strcmp(field, "learned")) {
                    if (!jexpect(c, '[')) return 0;
                    jw(c);
                    if (c->p < c->end && *c->p == ']') c->p++;
                    else {
                        for (;;) {
                            long long v;
                            if (!jnumber(c, &v)) return 0;
                            if ((unsigned)*used >= LC_MAX_SAVE / 16) { c->bad = 1; return 0; }
                            if (doc_reserve(d, *used + 1)) {
                                d->serial[*used] = serial;
                                d->id[*used] = (unsigned int)v;
                                (*used)++;
                            } else { c->bad = 1; return 0; }
                            jw(c);
                            if (c->p < c->end && *c->p == ',') { c->p++; continue; }
                            if (!jexpect(c, ']')) return 0;
                            break;
                        }
                    }
                } else if (!jskip(c)) return 0;
                jw(c);
                if (c->p < c->end && *c->p == ',') { c->p++; continue; }
                if (!jexpect(c, '}')) return 0;
                break;
            }
        }
        jw(c);
        if (c->p < c->end && *c->p == ',') { c->p++; continue; }
        return jexpect(c, '}');
    }
}

static int jparse_quarantine(LC_CUR *c, LC_DOC *d) {
    if (!jexpect(c, '[')) return 0;
    jw(c);
    if (c->p < c->end && *c->p == ']') { c->p++; return 1; }
    for (;;) {
        char key[64];
        unsigned long long serial = 0;
        unsigned int id = 0;
        if (!jexpect(c, '{')) return 0;
        for (;;) {
            if (!jstring(c, key, sizeof key) || !jexpect(c, ':')) return 0;
            if (!strcmp(key, "serial")) { long long v; if (!jnumber(c, &v)) return 0; serial = (unsigned long long)v; }
            else if (!strcmp(key, "id")) { long long v; if (!jnumber(c, &v)) return 0; id = (unsigned int)v; }
            else if (!jskip(c)) return 0;
            jw(c);
            if (c->p < c->end && *c->p == ',') { c->p++; continue; }
            if (!jexpect(c, '}')) return 0;
            break;
        }
        if (d->nq < LC_MAX_QUAR) {
            unsigned long long *s = (unsigned long long *)realloc(d->qserial, (size_t)(d->nq + 1) * sizeof *s);
            unsigned int *q = (unsigned int *)realloc(d->qid, (size_t)(d->nq + 1) * sizeof *q);
            if (s) d->qserial = s;
            if (q) d->qid = q;
            if (s && q) { d->qserial[d->nq] = serial; d->qid[d->nq] = id; d->nq++; }
        }
        jw(c);
        if (c->p < c->end && *c->p == ',') { c->p++; continue; }
        return jexpect(c, ']');
    }
}

static int jparse_save(LC_CUR *c, LC_DOC *d) {
    char key[64];
    if (!jexpect(c, '{')) return 0;
    for (;;) {
        if (!jstring(c, key, sizeof key) || !jexpect(c, ':')) return 0;
        if (!strcmp(key, "size")) {
            long long v;
            if (!jnumber(c, &v)) return 0;
            d->save_size = v;
        } else if (!strcmp(key, "sha256")) {
            if (!jstring(c, d->save_sha, sizeof d->save_sha)) return 0;
        } else if (!strcmp(key, "name")) {
            if (!jstring(c, d->save_name, sizeof d->save_name)) return 0;
        } else if (!jskip(c)) return 0;
        jw(c);
        if (c->p < c->end && *c->p == ',') { c->p++; continue; }
        return jexpect(c, '}');
    }
}

/* parse a companion document; -> 1 ok, 0 refused (c.bad or a structural problem) */
static int doc_parse(const char *text, size_t len, LC_DOC *d, char *kind, size_t kind_n) {
    LC_CUR c;
    int used = 0;
    char key[64];
    c.p = text;
    c.end = text + len;
    c.bad = 0;
    memset(d, 0, sizeof *d);
    d->schema = -1;
    d->bitmap_bits = -1;
    d->save_size = -1;
    if (!jexpect(&c, '{')) return 0;
    for (;;) {
        jw(&c);
        if (c.p < c.end && *c.p == '}') { c.p++; break; }
        if (!jstring(&c, key, sizeof key) || !jexpect(&c, ':')) return 0;
        if (!strcmp(key, "kind")) { if (!jstring(&c, kind, kind_n)) return 0; }
        else if (!strcmp(key, "schema")) { long long v; if (!jnumber(&c, &v)) return 0; d->schema = (int)v; }
        else if (!strcmp(key, "generation")) {
            long long v;
            if (!jnumber(&c, &v)) return 0;
            d->generation = (unsigned int)v;
        } else if (!strcmp(key, "rows")) { long long v; if (!jnumber(&c, &v)) return 0; d->rows = (int)v; }
        else if (!strcmp(key, "bitmap_bits")) {
            long long v;
            if (!jnumber(&c, &v)) return 0;
            d->bitmap_bits = (int)v;
        } else if (!strcmp(key, "save")) { if (!jparse_save(&c, d)) return 0; }
        else if (!strcmp(key, "units")) { if (!jparse_units(&c, d, &used)) return 0; }
        else if (!strcmp(key, "quarantine")) { if (!jparse_quarantine(&c, d)) return 0; }
        else if (!jskip(&c)) return 0;
        jw(&c);
        if (c.p < c.end && *c.p == ',') { c.p++; continue; }
        if (!jexpect(&c, '}')) return 0;
        break;
    }
    d->npairs = used;                        /* the arrays were sized to the real count */
    if (c.p != c.end) {
        jw(&c);
        if (c.p != c.end) return 0;          /* trailing junk: refuse rather than guess */
    }
    return 1;
}

/* -------------------------------------------------------------------------------------------- helpers */
static int lc_read_file(const char *path, unsigned char **data, size_t *size, char sha[65]) {
    FILE *f = fopen(path, "rb");
    unsigned char *buf;
    long n;
    size_t got;
    LC_SHA h;
    if (!f) return 0;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return 0; }
    n = ftell(f);
    if (n < 0 || (unsigned long long)n > LC_MAX_SAVE) { fclose(f); return 0; }
    rewind(f);
    buf = (unsigned char *)malloc((size_t)n + 1);
    if (!buf) { fclose(f); return 0; }
    got = fread(buf, 1, (size_t)n, f);
    fclose(f);
    if (got != (size_t)n) { free(buf); return 0; }
    buf[n] = 0;
    if (sha) {
        lc_sha_init(&h);
        lc_sha_update(&h, buf, (size_t)n);
        lc_sha_final(&h, sha);
    }
    *data = buf;
    *size = (size_t)n;
    return 1;
}

static int lc_file_exists(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    fclose(f);
    return 1;
}

/* the same guard the wrappers use, decided here so nothing is written for a table we cannot interpret */
static int learn_guard_ok(void) {
    unsigned long long pkey = lcu64(LC_O_PKEY), pmax = lcu64(LC_O_PMAX);
    unsigned int *keys;
    unsigned int base_count = lcu(LC_O_BASE_COUNT), i;
    unsigned int *prefix = (unsigned int *)(g_lc + g_lc_prefix);
    if (!pkey || !pmax) { lcuset(LC_O_STATE, 2); return 0; }
    keys = *(unsigned int **)(uintptr_t)pkey;
    if (!keys) { lcuset(LC_O_STATE, 2); return 0; }
    if (*(unsigned short *)(uintptr_t)pmax + 1 < base_count) { lcuset(LC_O_STATE, 2); return 0; }
    for (i = 0; i < base_count; i++) {
        if (keys[i] != prefix[i]) { lcuset(LC_O_STATE, 2); return 0; }
    }
    lcuset(LC_O_STATE, 1);
    return 1;
}

/* the live table position of an id, or -1 (mirrors lc_position in d5learn.inc.asm) */
static int learn_position(unsigned int id) {
    unsigned long long pkey = lcu64(LC_O_PKEY), pmax = lcu64(LC_O_PMAX);
    unsigned int *keys;
    int lo = 0, hi;
    if (!pkey || !pmax) return -1;
    keys = *(unsigned int **)(uintptr_t)pkey;
    if (!keys) return -1;
    hi = *(unsigned short *)(uintptr_t)pmax;
    while (lo <= hi) {
        int mid = (int)(((unsigned)lo + (unsigned)hi) >> 1);
        if (keys[mid] == id) return mid;
        if (keys[mid] < id) lo = mid + 1;
        else hi = mid - 1;
    }
    return -1;
}

static int lc_pair_cmp(const void *a, const void *b) {
    const unsigned long long *x = (const unsigned long long *)a;
    const unsigned long long *y = (const unsigned long long *)b;
    if (x[0] != y[0]) return x[0] < y[0] ? -1 : 1;
    if (x[1] != y[1]) return x[1] < y[1] ? -1 : 1;
    return 0;
}

/* the live store, as sorted (serial, id) pairs.  -> malloc'd array of 2-qword rows, count in *n */
static unsigned long long *learn_pairs(int *n) {
    unsigned int cap = lcu(LC_O_CAP);
    unsigned long long *out;
    unsigned int i, k = 0;
    *n = 0;
    if (!cap) return NULL;
    out = (unsigned long long *)malloc((size_t)cap * 16);
    if (!out) return NULL;
    for (i = 0; i < cap; i++) {
        unsigned char *slot = (unsigned char *)(g_lc + g_lc_store + 16ull * i);
        if (*(unsigned int *)(slot + 12) != 1) continue;
        out[k * 2] = *(unsigned long long *)slot;
        out[k * 2 + 1] = *(unsigned int *)(slot + 8);
        k++;
    }
    qsort(out, k, 16, lc_pair_cmp);
    *n = (int)k;
    return out;
}

/* ------------------------------------------------------------------------------------- the two jobs */
/* Is this a slot file this game's own writer produced?  The relay only fires after the writer answered 0, so
 * anything that fails here means the path we built is not the file the game just wrote (a moved save folder,
 * a different build's format, a file something else replaced): refuse and say so -- no companion is better
 * than one bound to the wrong bytes. */
static int lc_is_slot_file(const unsigned char *raw, size_t size) {
    const char *text = LC_HDR_TEXT;
    unsigned int i;
    unsigned long long magic;
    if (size < LC_HDR_LEN + 8) return 0;
    for (i = 0; text[i]; i++) {                      /* the header text, nibble-swapped: (((~b) << 4) | (b >> 4)) */
        unsigned char b = (unsigned char)text[i];
        unsigned char want = (unsigned char)((((unsigned char)~b) << 4) | (b >> 4));
        if (raw[i] != want) return 0;
    }
    if (raw[i] != 0xF0) return 0;                    /* the NUL strncpy added, transformed the same way */
    magic = *(const unsigned long long *)(raw + LC_HDR_LEN);   /* little endian, as the file stores it */
    return magic == LC_BLOCK_MAGIC;
}

/* The game wrote a slot file and said so.  `slot` is the number it put in the file name (0 = AutoSave.sav);
 * 0xFFFFFFFF means the value could not be a slot file name at all. */
static void learn_on_save(unsigned int slot) {
    int npairs = 0, i, n;
    char save[LC_MAX_PATH], sidecar[LC_MAX_PATH + 32], prev[LC_MAX_PATH + 48], tmp[LC_MAX_PATH + 48];
    const char *dir = (const char *)(uintptr_t)lcu64(LC_O_SAVEDIR);
    unsigned char *raw = NULL;
    size_t size = 0;
    char sha[65];
    unsigned long long *pairs;
    LC_SB b;
    FILE *f;
    unsigned int rows;
    if (slot == 0xFFFFFFFFu) {
        logf_("learn: the game reported a save slot that cannot name a file: no companion");
        return;
    }
    if (!dir || !dir[0]) {
        logf_("learn: the game's save folder is not known yet: no companion for slot %u", slot);
        return;
    }
    if (slot == 0) n = snprintf(save, sizeof save, "%s/AutoSave.sav", dir);
    else n = snprintf(save, sizeof save, "%s/Save_%03u.sav", dir, slot);
    if (n < 0 || n >= (int)sizeof save) {
        logf_("learn: the save folder path is too long to name a slot file (%d): no companion", n);
        return;
    }
    if (!learn_guard_ok()) {
        logf_("learn: Skill table does not match this build's generation -- companion NOT written for %s", save);
        return;
    }
    if (!lc_read_file(save, &raw, &size, sha)) {
        logf_("learn: cannot read back the save the game just wrote (%s): no companion", save);
        return;
    }
    if (!lc_is_slot_file(raw, size)) {
        free(raw);
        logf_("learn: %s is not a slot file this game's writer produced: no companion", save);
        return;
    }
    free(raw);
    snprintf(sidecar, sizeof sidecar, "%s.d5learn.json", save);
    snprintf(prev, sizeof prev, "%s.d5learn.json.prev", save);
    snprintf(tmp, sizeof tmp, "%s.d5learn.json.new", save);
    pairs = learn_pairs(&npairs);
    if (!pairs && lcu(LC_O_USED)) {
        logf_("learn: out of memory reading the store: no companion for %s", save);
        return;
    }
    rows = (unsigned int)(*(unsigned short *)(uintptr_t)lcu64(LC_O_PMAX)) + 1;
    if (!npairs && !lc_file_exists(sidecar)) {
        free(pairs);
        logf_("learn: save %s written, nothing beyond the bitmap to carry", save);
        return;
    }
    memset(&b, 0, sizeof b);
    sb_addf(&b, "{\"kind\":\"d5modkit.learned\",\"schema\":%u,\"generation\":%u,\"rows\":%u,"
                "\"bitmap_bits\":%u,\"save\":{\"name\":\"", LC_DOC_SCHEMA, lcu(LC_O_GEN), rows, LC_BITMAP_BITS);
    {
        const char *base = strrchr(save, '/');
        const char *base2 = strrchr(save, '\\');
        if (base2 && (!base || base2 > base)) base = base2;
        sb_add(&b, base ? base + 1 : save);
    }
    sb_addf(&b, "\",\"size\":%llu,\"sha256\":\"%s\"},\"units\":{", (unsigned long long)size, sha);
    for (i = 0; i < npairs;) {
        unsigned long long serial = pairs[i * 2];
        int first = 1;
        sb_addf(&b, "%s\"%016llx\":{\"learned\":[", i ? "," : "", serial);
        while (i < npairs && pairs[i * 2] == serial) {
            sb_addf(&b, "%s%u", first ? "" : ",", (unsigned int)pairs[i * 2 + 1]);
            first = 0;
            i++;
        }
        sb_add(&b, "],\"name\":null}");
    }
    sb_add(&b, "},\"quarantine\":[");
    for (i = 0; i < g_lc_nq; i++)
        sb_addf(&b, "%s{\"serial\":%llu,\"id\":%u}", i ? "," : "", g_lc_serial[i], g_lc_qid[i]);
    sb_add(&b, "]}\n");
    free(pairs);
    if (b.bad || !b.p) { free(b.p); logf_("learn: out of memory building the companion for %s", save); return; }
    f = fopen(tmp, "wb");
    if (!f) {
        free(b.p);
        logf_("learn: cannot create %s (save itself untouched)", tmp);
        return;
    }
    if (fwrite(b.p, 1, b.n, f) != b.n) {
        fclose(f);
        remove(tmp);
        free(b.p);
        logf_("learn: short write to %s (save itself untouched)", tmp);
        return;
    }
    LC_FSYNC(f);
    fclose(f);
    /* keep one previous generation, then publish atomically */
    if (lc_file_exists(sidecar)) LC_RENAME(sidecar, prev, 1);
    if (!LC_RENAME(tmp, sidecar, 1)) {
        remove(tmp);
        free(b.p);
        logf_("learn: cannot publish %s (previous companion kept, save untouched)", sidecar);
        return;
    }
    free(b.p);
    logf_("learn: %s: %d learnt id(s) beyond the bitmap carried for %d unit(s)%s", sidecar, npairs,
          npairs, g_lc_nq ? " (+quarantined ids kept)" : "");
}

static void learn_apply(LC_DOC *d, const char *save) {
    int i, put = 0, dropped = 0, unknown = 0, refused = 0, q0 = g_lc_nq;
    if (g_lc_clear) g_lc_clear();
    for (i = 0; i < d->npairs; i++) {
        int pos = learn_position(d->id[i]);
        if (pos < 0) {
            unknown++;
            if (g_lc_nq < LC_MAX_QUAR) {
                g_lc_serial[g_lc_nq] = d->serial[i];
                g_lc_qid[g_lc_nq] = d->id[i];
                g_lc_nq++;
            }
            continue;
        }
        if (pos < LC_BITMAP_BITS) { dropped++; continue; }   /* the bitmap owns it: nothing to carry */
        if (g_lc_put && g_lc_put(d->serial[i], d->id[i]) == 0) put++;
        else refused++;
    }
    for (i = 0; i < d->nq; i++) {                            /* ids an earlier load already quarantined */
        if (g_lc_nq >= LC_MAX_QUAR) break;
        g_lc_serial[g_lc_nq] = d->qserial[i];
        g_lc_qid[g_lc_nq] = d->qid[i];
        g_lc_nq++;
    }
    logf_("learn: %s: applied %d learnt id(s) beyond the bitmap (unit(s) restored: %s); "
          "%d unknown kept aside, %d native-owned dropped, %d refused%s",
          save ? save : "?", put, put ? "yes" : "none", unknown, dropped, refused,
          refused ? " -- STORE FULL" : "");
    if (unknown + d->nq - (g_lc_nq - q0) > 0 && g_lc_nq >= LC_MAX_QUAR)
        logf_("learn: quarantine list full (%d): further unknown ids are not listed", LC_MAX_QUAR);
}

/* May this runtime write under SaveData?  In an agent run ([debug] remote=1) the harness has failed the
 * game's own CreateFile/DeleteFile calls under SaveData, so the shape the run sees is "nothing is saved".
 * Our file work does not go through the game's IAT and would not be blocked, so it is refused here instead:
 * a companion is read and applied (read only), never written, rotated, renamed or removed.  Without this,
 * a refused companion would be renamed to ".rejected" -- a real change to Sean's save folder -- by a run
 * that is only supposed to be looking. */
static int lc_may_write(void) {
    if (!LC_REMOTE()) return 1;
    logf_("learn: remote=1 (agent run): the save folder is read only for this runtime");
    return 0;
}

/* A refused companion is moved aside so it cannot be mistaken for a good one -- except in an agent run,
 * where nothing under SaveData is touched: then it stays where it is and the log says so. */
static const char *lc_keep_rejected(const char *sidecar, const char *rejected) {
    if (!lc_may_write()) return sidecar;
    return LC_RENAME(sidecar, rejected, 1) ? rejected : sidecar;
}

static void learn_on_load(int slot, int ok) {
    char save[LC_MAX_PATH], sidecar[LC_MAX_PATH + 32], rejected[LC_MAX_PATH + 48];
    const char *dir = (const char *)(uintptr_t)lcu64(LC_O_SAVEDIR);
    int n;
    unsigned char *raw = NULL, *text = NULL;
    size_t size = 0, tsize = 0;
    const char *kept;
    char sha[65], kind[32];
    LC_DOC doc;
    if (!ok) {
        logf_("learn: slot %d did not decode -- store left as it is", slot);
        return;
    }
    if (!dir || !dir[0]) {
        logf_("learn: the game's save folder is not known yet -- store left as it is");
        return;
    }
    if (slot == 0) n = snprintf(save, sizeof save, "%s/AutoSave.sav", dir);
    else n = snprintf(save, sizeof save, "%s/Save_%03d.sav", dir, slot);
    if (n < 0 || n >= (int)sizeof save) {
        if (g_lc_clear) g_lc_clear();
        logf_("learn: the save folder path is too long to name a slot file (%d): nothing applied", n);
        return;
    }
    snprintf(sidecar, sizeof sidecar, "%s.d5learn.json", save);
    snprintf(rejected, sizeof rejected, "%s.rejected", sidecar);
    if (!lc_read_file(sidecar, &text, &tsize, NULL)) {
        if (g_lc_clear) g_lc_clear();
        logf_("learn: %s: no companion -- this save's native evilities only", save);
        return;
    }
    if (!doc_parse((const char *)text, tsize, &doc, kind, sizeof kind)) {
        free(text);
        if (g_lc_clear) g_lc_clear();
        kept = lc_keep_rejected(sidecar, rejected);
        logf_("learn: %s: companion unreadable -- kept as %s, native evilities only", save, kept);
        return;
    }
    free(text);
    if (strcmp(kind, "d5modkit.learned") || (doc.schema != 1 && doc.schema != LC_DOC_SCHEMA) ||
        doc.bitmap_bits != (int)LC_BITMAP_BITS || doc.generation != lcu(LC_O_GEN)) {
        int schema = doc.schema;
        unsigned int gen = doc.generation;
        doc_free(&doc);
        if (g_lc_clear) g_lc_clear();
        kept = lc_keep_rejected(sidecar, rejected);
        logf_("learn: %s: companion is for another format/table (schema %d, generation %08x != %08x) -- "
              "kept as %s, native evilities only", save, schema, gen, lcu(LC_O_GEN), kept);
        return;
    }
    if (!lc_read_file(save, &raw, &size, sha) || doc.save_size != (long long)size ||
        strcmp(doc.save_sha, sha)) {
        free(raw);
        doc_free(&doc);
        if (g_lc_clear) g_lc_clear();
        kept = lc_keep_rejected(sidecar, rejected);
        logf_("learn: %s: companion does not match these save bytes -- kept as %s, native evilities only",
              save, kept);
        return;
    }
    free(raw);
    g_lc_nq = 0;
    learn_apply(&doc, save);
    doc_free(&doc);
}

/* ----------------------------------------------------------------------------------------------- tick */
static unsigned int g_lc_saveseq;            /* the last lc_sv_seq this runtime acted on */

static void learn_tick(void) {
    learn_init();
    if (!g_lc) return;
    if (lcu(g_lc_ev + 8)) {                       /* load event: slot at +12, decode result at +16 */
        unsigned int slot = lcu(g_lc_ev + 12), ok = lcu(g_lc_ev + 16);
        lcuset(g_lc_ev + 8, 0);
        learn_on_load((int)slot, (int)ok);
    }
    /* save event: the game's writer thread published a slot at +0 and then bumped +4 (lock inc).  The
     * sequence number, not a flag, is what makes a write that lands between two frames visible; reading
     * the slot after the sequence is safe because both are 32-bit aligned stores, and the worst case is
     * acting on a newer slot whose file is then hashed anyway. */
    if (lcuv(g_lc_ev + 4) != g_lc_saveseq) {
        unsigned int slot = lcu(g_lc_ev + 0);
        g_lc_saveseq = lcuv(g_lc_ev + 4);
        if (lc_may_write()) learn_on_save(slot);
    }
}
