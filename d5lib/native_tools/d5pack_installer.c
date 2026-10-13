/* D5 Mod Kit package installer: a stub exe with the package appended (d5lib/package.py).
 *
 * Players run it, check the game folder (found automatically when possible) and press Install; Uninstall puts every
 * file back exactly as it was.  No Python, no kit.  Command line (also for testing):
 *     installer.exe /install  "<game folder>" [/quiet]
 *     installer.exe /uninstall "<game folder>" [/quiet]
 * Exit code 0 = done.
 *
 * Package format: see d5lib/package.py.  Every vanilla file is checked (size + SHA-1 of the region the package
 * relies on) before anything is written; backups go to <game>\D5Mods\backup, the install record to
 * <game>\D5Mods\installed.txt.  Built with Zig:  zig cc -target x86_64-windows-gnu -O2 -mwindows ... (see
 * d5lib/package.py build_stub).
 */
#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <shellapi.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

/* ------------------------------------------------------------------------------------------ SHA-1 */
typedef struct { uint32_t h[5]; uint64_t n; uint8_t buf[64]; size_t len; } Sha1;
#define ROL(v, s) (((v) << (s)) | ((v) >> (32 - (s))))
static void sha1_block(Sha1 *c, const uint8_t *p) {
    uint32_t w[80], a, b, d, e, f, k, t, cc;
    for (int i = 0; i < 16; i++) w[i] = (uint32_t)p[4*i] << 24 | (uint32_t)p[4*i+1] << 16 | (uint32_t)p[4*i+2] << 8 | p[4*i+3];
    for (int i = 16; i < 80; i++) w[i] = ROL(w[i-3] ^ w[i-8] ^ w[i-14] ^ w[i-16], 1);
    a = c->h[0]; b = c->h[1]; cc = c->h[2]; d = c->h[3]; e = c->h[4];
    for (int i = 0; i < 80; i++) {
        if (i < 20) { f = (b & cc) | (~b & d); k = 0x5A827999; }
        else if (i < 40) { f = b ^ cc ^ d; k = 0x6ED9EBA1; }
        else if (i < 60) { f = (b & cc) | (b & d) | (cc & d); k = 0x8F1BBCDC; }
        else { f = b ^ cc ^ d; k = 0xCA62C1D6; }
        t = ROL(a, 5) + f + e + k + w[i];
        e = d; d = cc; cc = ROL(b, 30); b = a; a = t;
    }
    c->h[0] += a; c->h[1] += b; c->h[2] += cc; c->h[3] += d; c->h[4] += e;
}
static void sha1_init(Sha1 *c) {
    c->h[0] = 0x67452301; c->h[1] = 0xEFCDAB89; c->h[2] = 0x98BADCFE; c->h[3] = 0x10325476; c->h[4] = 0xC3D2E1F0;
    c->n = 0; c->len = 0;
}
static void sha1_update(Sha1 *c, const uint8_t *p, size_t n) {
    c->n += n;
    while (n) {
        size_t k = 64 - c->len; if (k > n) k = n;
        memcpy(c->buf + c->len, p, k); c->len += k; p += k; n -= k;
        if (c->len == 64) { sha1_block(c, c->buf); c->len = 0; }
    }
}
static void sha1_final(Sha1 *c, uint8_t out[20]) {
    uint64_t bits = c->n * 8;
    uint8_t pad = 0x80, z = 0;
    sha1_update(c, &pad, 1);
    while (c->len != 56) sha1_update(c, &z, 1);
    uint8_t lb[8];
    for (int i = 0; i < 8; i++) lb[i] = (uint8_t)(bits >> (56 - 8 * i));
    sha1_update(c, lb, 8);
    for (int i = 0; i < 5; i++) { out[4*i] = c->h[i] >> 24; out[4*i+1] = c->h[i] >> 16; out[4*i+2] = c->h[i] >> 8; out[4*i+3] = c->h[i]; }
}

/* ------------------------------------------------------------------------------------------ package */
typedef struct { uint8_t type; uint64_t a, n; } Op;
typedef struct {
    wchar_t path[512];
    uint8_t kind;                 /* 1 append, 2 replace, 3 new */
    uint64_t vsize, check_len, head_off, head_len, out_size;
    uint8_t check_sha[20], out_sha[20];
    uint32_t nign; uint64_t *ign;    /* (offset, length) pairs zeroed before the check */
    uint32_t nops; Op *ops;
} Entry;
static wchar_t g_title[256], g_desc[4096], g_id[128];
static Entry *g_files; static uint32_t g_nfiles;
static HANDLE g_self; static uint64_t g_blob_base;
static wchar_t g_err[2048];
static volatile LONG g_progress;  /* 0..1000 */
static HWND g_wnd, g_status, g_bar, g_edit, g_bInstall, g_bUninstall, g_bBrowse;
static int g_quiet;

static void seterr(const wchar_t *fmt, ...) {
    va_list ap; va_start(ap, fmt); _vsnwprintf(g_err, 2047, fmt, ap); g_err[2047] = 0; va_end(ap);
}
static void status(const wchar_t *fmt, ...) {
    wchar_t b[1024]; va_list ap; va_start(ap, fmt); _vsnwprintf(b, 1023, fmt, ap); b[1023] = 0; va_end(ap);
    if (g_status) SetWindowTextW(g_status, b);
    if (g_quiet) { fwprintf(stdout, L"%ls\n", b); fflush(stdout); }
}

static int rd(HANDLE h, uint64_t off, void *buf, DWORD n) {
    LARGE_INTEGER li; li.QuadPart = (LONGLONG)off;
    if (!SetFilePointerEx(h, li, NULL, FILE_BEGIN)) return 0;
    DWORD got = 0;
    return ReadFile(h, buf, n, &got, NULL) && got == n;
}
static int wr(HANDLE h, uint64_t off, const void *buf, DWORD n) {
    LARGE_INTEGER li; li.QuadPart = (LONGLONG)off;
    if (!SetFilePointerEx(h, li, NULL, FILE_BEGIN)) return 0;
    DWORD put = 0;
    return WriteFile(h, buf, n, &put, NULL) && put == n;
}
static uint64_t fsize(HANDLE h) { LARGE_INTEGER li; return GetFileSizeEx(h, &li) ? (uint64_t)li.QuadPart : 0; }

static const uint8_t *g_man; static size_t g_man_len, g_pos;
static uint32_t u32(void) { uint32_t v = 0; if (g_pos + 4 <= g_man_len) memcpy(&v, g_man + g_pos, 4); g_pos += 4; return v; }
static uint64_t u64(void) { uint64_t v = 0; if (g_pos + 8 <= g_man_len) memcpy(&v, g_man + g_pos, 8); g_pos += 8; return v; }
static uint8_t u8(void) { uint8_t v = g_pos < g_man_len ? g_man[g_pos] : 0; g_pos += 1; return v; }
static void str(wchar_t *out, int cap) {
    uint32_t n = u32();
    int k = 0;
    if (g_pos + n <= g_man_len) k = MultiByteToWideChar(CP_UTF8, 0, (const char *)g_man + g_pos, (int)n, out, cap - 1);
    out[k] = 0; g_pos += n;
}
static void bytes20(uint8_t *out) { if (g_pos + 20 <= g_man_len) memcpy(out, g_man + g_pos, 20); g_pos += 20; }

static int load_package(void) {
    wchar_t me[MAX_PATH];
    GetModuleFileNameW(NULL, me, MAX_PATH);
    g_self = CreateFileW(me, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (g_self == INVALID_HANDLE_VALUE) { seterr(L"cannot read the installer file"); return 0; }
    uint64_t sz = fsize(g_self);
    uint8_t t[24];
    if (sz < 24 || !rd(g_self, sz - 24, t, 24) || memcmp(t, "D5PKTAIL", 8)) { seterr(L"this installer carries no mod package"); return 0; }
    uint64_t base; memcpy(&base, t + 8, 8);
    uint8_t h[12];
    if (!rd(g_self, base, h, 12) || memcmp(h, "D5PKG1\0\0", 8)) { seterr(L"damaged package"); return 0; }
    uint32_t mlen; memcpy(&mlen, h + 8, 4);
    uint8_t *m = (uint8_t *)malloc(mlen);
    if (!m || !rd(g_self, base + 12, m, mlen)) { seterr(L"damaged package"); return 0; }
    g_man = m; g_man_len = mlen; g_pos = 0;
    g_blob_base = base + 12 + mlen;
    u32();
    str(g_title, 256); str(g_desc, 4096); str(g_id, 128);
    g_nfiles = u32();
    g_files = (Entry *)calloc(g_nfiles, sizeof(Entry));
    for (uint32_t i = 0; i < g_nfiles; i++) {
        Entry *e = &g_files[i];
        str(e->path, 512);
        e->kind = u8(); e->vsize = u64(); e->check_len = u64(); bytes20(e->check_sha);
        e->nign = u32();
        e->ign = (uint64_t *)malloc(sizeof(uint64_t) * 2 * (e->nign ? e->nign : 1));
        for (uint32_t k = 0; k < e->nign; k++) { e->ign[2 * k] = u64(); e->ign[2 * k + 1] = u64(); }
        e->head_off = u64(); e->head_len = u64(); e->out_size = u64(); bytes20(e->out_sha);
        e->nops = u32();
        e->ops = (Op *)malloc(sizeof(Op) * (e->nops ? e->nops : 1));
        for (uint32_t k = 0; k < e->nops; k++) { e->ops[k].type = u8(); e->ops[k].a = u64(); e->ops[k].n = u64(); }
    }
    if (g_pos > g_man_len) { seterr(L"damaged package"); return 0; }
    return 1;
}

/* ------------------------------------------------------------------------------------------ install */
#define CHUNK (8u << 20)
static uint8_t *g_buf;
static uint64_t g_work_total, g_work_done;
static void progress(uint64_t add) {
    g_work_done += add;
    LONG p = g_work_total ? (LONG)(g_work_done * 1000 / g_work_total) : 0;
    InterlockedExchange(&g_progress, p > 1000 ? 1000 : p);
}

static void join(wchar_t *out, const wchar_t *dir, const wchar_t *rel) {
    _snwprintf(out, MAX_PATH * 2 - 1, L"%ls\\%ls", dir, rel); out[MAX_PATH * 2 - 1] = 0;
}

static int sha_region(HANDLE h, uint64_t off, uint64_t n, uint8_t out[20], int count_progress, const Entry *ig) {
    Sha1 c; sha1_init(&c);
    while (n) {
        DWORD k = n > CHUNK ? CHUNK : (DWORD)n;
        if (!rd(h, off, g_buf, k)) return 0;
        for (uint32_t i = 0; ig && i < ig->nign; i++) {          /* ignored ranges count as zero bytes */
            uint64_t a = ig->ign[2 * i], b = a + ig->ign[2 * i + 1];
            if (a < off) a = off;
            if (b > off + k) b = off + k;
            if (a < b) memset(g_buf + (a - off), 0, (size_t)(b - a));
        }
        sha1_update(&c, g_buf, k); off += k; n -= k;
        if (count_progress) progress(k);
    }
    sha1_final(&c, out);
    return 1;
}

static int copy_range(HANDLE src, uint64_t so, HANDLE dst, uint64_t doff, uint64_t n, Sha1 *c) {
    while (n) {
        DWORD k = n > CHUNK ? CHUNK : (DWORD)n;
        if (!rd(src, so, g_buf, k) || !wr(dst, doff, g_buf, k)) return 0;
        if (c) sha1_update(c, g_buf, k);
        so += k; doff += k; n -= k; progress(k);
    }
    return 1;
}

/* the output of an entry's ops, written at `pos` of dst (src = the vanilla file, may be dst itself) */
static int run_ops(Entry *e, HANDLE src, HANDLE dst, uint64_t pos, Sha1 *c) {
    for (uint32_t k = 0; k < e->nops; k++) {
        Op *o = &e->ops[k];
        HANDLE from = o->type == 0 ? g_self : (o->type == 1 ? src : dst);
        uint64_t so = o->type == 0 ? g_blob_base + o->a : o->a;
        if (!copy_range(from, so, dst, pos, o->n, c)) return 0;
        pos += o->n;
    }
    return 1;
}

static wchar_t g_game[MAX_PATH];

static int file_exists(const wchar_t *p) { DWORD a = GetFileAttributesW(p); return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY); }

static int game_running(void) {
    wchar_t p[MAX_PATH * 2]; join(p, g_game, L"disgaea5.exe");
    HANDLE h = CreateFileW(p, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_SHARING_VIOLATION;
    CloseHandle(h);
    return 0;
}

static int check_vanilla(Entry *e, wchar_t *why, int cap) {
    wchar_t p[MAX_PATH * 2]; join(p, g_game, e->path);
    if (e->kind == 3) return 1;
    HANDLE h = CreateFileW(p, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) { _snwprintf(why, cap, L"%ls is missing", e->path); return 0; }
    uint64_t sz = fsize(h);
    uint8_t s[20];
    int ok = sz == e->vsize && sha_region(h, 0, e->check_len, s, 1, e) && !memcmp(s, e->check_sha, 20);
    CloseHandle(h);
    if (!ok) _snwprintf(why, cap, L"%ls is not the game version this package was made for (or other mods are installed)", e->path);
    return ok;
}

static void state_path(wchar_t *out, const wchar_t *name) {
    _snwprintf(out, MAX_PATH * 2 - 1, L"%ls\\D5Mods\\%ls", g_game, name); out[MAX_PATH * 2 - 1] = 0;
}

static int write_all(const wchar_t *path, const void *data, DWORD n) {
    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    DWORD put = 0; int ok = WriteFile(h, data, n, &put, NULL) && put == n;
    CloseHandle(h);
    return ok;
}

static int do_uninstall(void);

static int do_install(void) {
    wchar_t why[1024], p[MAX_PATH * 2], b[MAX_PATH * 2];
    if (game_running()) { seterr(L"Disgaea 5 is running. Close the game first."); return 0; }
    state_path(p, L"installed.txt");
    if (file_exists(p)) {
        status(L"Removing the mods installed before...");
        if (!do_uninstall()) return 0;
    }
    g_work_total = g_work_done = 0;
    for (uint32_t i = 0; i < g_nfiles; i++) g_work_total += g_files[i].check_len;
    status(L"Checking the game files...");
    for (uint32_t i = 0; i < g_nfiles; i++)
        if (!check_vanilla(&g_files[i], why, 1023)) { seterr(L"%ls.\n\nNothing was changed.", why); return 0; }
    /* backups first, then the files */
    state_path(p, L""); CreateDirectoryW(p, NULL);
    state_path(p, L"backup"); CreateDirectoryW(p, NULL);
    g_work_total = g_work_done = 0;
    for (uint32_t i = 0; i < g_nfiles; i++) {
        Entry *e = &g_files[i];
        g_work_total += e->kind == 1 ? (e->out_size - e->vsize) * 2 + e->head_len : e->out_size * 2;
    }
    char rec[65536]; size_t rl = 0;
    rl += snprintf(rec + rl, sizeof rec - rl, "D5MODS 1\n");
    for (uint32_t i = 0; i < g_nfiles; i++) {
        Entry *e = &g_files[i];
        join(p, g_game, e->path);
        _snwprintf(b, MAX_PATH * 2 - 1, L"%ls\\D5Mods\\backup\\%u.bak", g_game, i);
        status(L"Installing %ls ...", e->path);
        int existed = file_exists(p);
        if (e->kind == 1) {
            HANDLE h = CreateFileW(p, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
            if (h == INVALID_HANDLE_VALUE) { seterr(L"cannot open %ls (run the installer as administrator?)", e->path); return 0; }
            uint8_t *hb = (uint8_t *)malloc(e->head_len);
            int ok = hb && rd(h, 0, hb, (DWORD)e->head_len) && write_all(b, hb, (DWORD)e->head_len);
            Sha1 c; sha1_init(&c);
            uint8_t *nh = (uint8_t *)malloc(e->head_len);
            ok = ok && nh && rd(g_self, g_blob_base + e->head_off, nh, (DWORD)e->head_len);
            if (ok) sha1_update(&c, nh, e->head_len);
            ok = ok && run_ops(e, h, h, e->vsize, &c);
            LARGE_INTEGER li; li.QuadPart = (LONGLONG)e->out_size;
            ok = ok && SetFilePointerEx(h, li, NULL, FILE_BEGIN) && SetEndOfFile(h);
            uint8_t s[20]; sha1_final(&c, s);
            ok = ok && !memcmp(s, e->out_sha, 20) && wr(h, 0, nh, (DWORD)e->head_len);
            progress(e->head_len);
            if (!ok) {                 /* back to vanilla at once */
                if (hb) wr(h, 0, hb, (DWORD)e->head_len);
                li.QuadPart = (LONGLONG)e->vsize; SetFilePointerEx(h, li, NULL, FILE_BEGIN); SetEndOfFile(h);
            }
            free(hb); free(nh); CloseHandle(h);
            if (!ok) { seterr(L"writing %ls failed (disk full?). The file was put back.", e->path); goto fail; }
        } else {
            wchar_t tmp[MAX_PATH * 2]; _snwprintf(tmp, MAX_PATH * 2 - 1, L"%ls.d5new", p);
            HANDLE src = INVALID_HANDLE_VALUE;
            if (e->kind == 2) src = CreateFileW(p, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
            HANDLE dst = CreateFileW(tmp, GENERIC_READ | GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
            if (dst == INVALID_HANDLE_VALUE) { if (src != INVALID_HANDLE_VALUE) CloseHandle(src); seterr(L"cannot write next to %ls (run the installer as administrator?)", e->path); goto fail; }
            Sha1 c; sha1_init(&c);
            int ok = run_ops(e, src, dst, 0, &c);
            uint8_t s[20]; sha1_final(&c, s);
            ok = ok && !memcmp(s, e->out_sha, 20);
            if (src != INVALID_HANDLE_VALUE) CloseHandle(src);
            CloseHandle(dst);
            if (ok && existed) ok = CopyFileW(p, b, FALSE);
            if (ok) ok = MoveFileExW(tmp, p, MOVEFILE_REPLACE_EXISTING);
            if (!ok) { DeleteFileW(tmp); seterr(L"writing %ls failed.", e->path); goto fail; }
        }
        char path8[1024]; WideCharToMultiByte(CP_UTF8, 0, e->path, -1, path8, sizeof path8, NULL, NULL);
        rl += snprintf(rec + rl, sizeof rec - rl, "%u %u %llu %llu %d %s\n", i, e->kind,
                       (unsigned long long)e->vsize, (unsigned long long)e->head_len, existed, path8);
        state_path(p, L"installed.txt");
        if (!write_all(p, rec, (DWORD)rl)) { seterr(L"cannot write the install record"); goto fail; }
    }
    InterlockedExchange(&g_progress, 1000);
    return 1;
fail:
    do_uninstall();
    return 0;
}

static int do_uninstall(void) {
    wchar_t p[MAX_PATH * 2], b[MAX_PATH * 2], rp[MAX_PATH * 2];
    if (game_running()) { seterr(L"Disgaea 5 is running. Close the game first."); return 0; }
    state_path(rp, L"installed.txt");
    HANDLE h = CreateFileW(rp, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) { seterr(L"No mods from a package are installed in this folder."); return 0; }
    uint64_t n = fsize(h);
    char *txt = (char *)calloc(1, (size_t)n + 1);
    DWORD got = 0; ReadFile(h, txt, (DWORD)n, &got, NULL); CloseHandle(h);
    int ok = 1;
    char *line = strtok(txt, "\n");
    while ((line = strtok(NULL, "\n"))) {
        unsigned idx, kind; unsigned long long vsize, hlen; int existed; char path8[1024];
        if (sscanf(line, "%u %u %llu %llu %d %1023[^\n]", &idx, &kind, &vsize, &hlen, &existed, path8) != 6) continue;
        wchar_t rel[512]; MultiByteToWideChar(CP_UTF8, 0, path8, -1, rel, 512);
        join(p, g_game, rel);
        _snwprintf(b, MAX_PATH * 2 - 1, L"%ls\\D5Mods\\backup\\%u.bak", g_game, idx);
        status(L"Restoring %ls ...", rel);
        if (kind == 1) {
            HANDLE f = CreateFileW(p, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
            HANDLE bk = CreateFileW(b, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
            int k = f != INVALID_HANDLE_VALUE && bk != INVALID_HANDLE_VALUE;
            uint8_t *hb = k ? (uint8_t *)malloc((size_t)hlen) : NULL;
            k = k && hb && rd(bk, 0, hb, (DWORD)hlen) && wr(f, 0, hb, (DWORD)hlen);
            LARGE_INTEGER li; li.QuadPart = (LONGLONG)vsize;
            k = k && SetFilePointerEx(f, li, NULL, FILE_BEGIN) && SetEndOfFile(f);
            free(hb);
            if (f != INVALID_HANDLE_VALUE) CloseHandle(f);
            if (bk != INVALID_HANDLE_VALUE) CloseHandle(bk);
            ok &= k;
        } else if (existed) {
            ok &= CopyFileW(b, p, FALSE) ? 1 : 0;
        } else {
            DeleteFileW(p);
        }
        DeleteFileW(b);
    }
    free(txt);
    if (!ok) { seterr(L"Some files could not be restored (is the game running?). Try again."); return 0; }
    DeleteFileW(rp);
    state_path(p, L"backup"); RemoveDirectoryW(p);
    state_path(p, L""); p[wcslen(p) - 1] = 0; RemoveDirectoryW(p);
    return 1;
}

/* ------------------------------------------------------------------------------------------ game folder */
static int is_game(const wchar_t *dir) {
    wchar_t p[MAX_PATH * 2]; join(p, dir, L"disgaea5.exe");
    wchar_t q[MAX_PATH * 2]; join(q, dir, L"Data\\Anime\\ANM_HI_JP.dat");
    return file_exists(p) && file_exists(q);
}

static int find_game(wchar_t *out) {
    wchar_t me[MAX_PATH]; GetModuleFileNameW(NULL, me, MAX_PATH);
    wchar_t *s = wcsrchr(me, L'\\'); if (s) *s = 0;
    for (int up = 0; up < 3; up++) {                 /* next to the installer, or above it */
        if (is_game(me)) { wcscpy(out, me); return 1; }
        s = wcsrchr(me, L'\\'); if (!s) break; *s = 0;
    }
    HKEY k; wchar_t steam[MAX_PATH]; DWORD n = sizeof steam;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Valve\\Steam", 0, KEY_READ, &k) == ERROR_SUCCESS) {
        if (RegQueryValueExW(k, L"SteamPath", NULL, NULL, (BYTE *)steam, &n) == ERROR_SUCCESS) {
            wchar_t c[MAX_PATH * 2];
            _snwprintf(c, MAX_PATH * 2 - 1, L"%ls\\steamapps\\common\\Disgaea 5 Complete", steam);
            for (wchar_t *q = c; *q; q++) if (*q == L'/') *q = L'\\';
            if (is_game(c)) { wcscpy(out, c); RegCloseKey(k); return 1; }
            /* other Steam libraries */
            wchar_t lf[MAX_PATH * 2]; _snwprintf(lf, MAX_PATH * 2 - 1, L"%ls\\steamapps\\libraryfolders.vdf", steam);
            FILE *f = _wfopen(lf, L"rb");
            if (f) {
                char line[1024];
                while (fgets(line, sizeof line, f)) {
                    char *p = strstr(line, "\"path\"");
                    if (!p) continue;
                    p = strchr(p + 6, '"'); if (!p) continue;
                    char *e = strchr(p + 1, '"'); if (!e) continue;
                    *e = 0;
                    char lib[1024]; int j = 0;
                    for (char *q = p + 1; *q && j < 1000; q++) { if (q[0] == '\\' && q[1] == '\\') q++; lib[j++] = *q; }
                    lib[j] = 0;
                    wchar_t wl[MAX_PATH]; MultiByteToWideChar(CP_UTF8, 0, lib, -1, wl, MAX_PATH);
                    _snwprintf(c, MAX_PATH * 2 - 1, L"%ls\\steamapps\\common\\Disgaea 5 Complete", wl);
                    if (is_game(c)) { wcscpy(out, c); fclose(f); RegCloseKey(k); return 1; }
                }
                fclose(f);
            }
        }
        RegCloseKey(k);
    }
    const wchar_t *guess[] = {L"C:\\Program Files (x86)\\Steam\\steamapps\\common\\Disgaea 5 Complete",
                              L"C:\\Program Files\\Steam\\steamapps\\common\\Disgaea 5 Complete",
                              L"C:\\Games\\Disgaea 5 Complete", L"D:\\Games\\Disgaea 5 Complete",
                              L"D:\\SteamLibrary\\steamapps\\common\\Disgaea 5 Complete"};
    for (int i = 0; i < 5; i++) if (is_game(guess[i])) { wcscpy(out, guess[i]); return 1; }
    out[0] = 0;
    return 0;
}

/* ------------------------------------------------------------------------------------------ window */
#define ID_INSTALL 101
#define ID_UNINSTALL 102
#define ID_BROWSE 103
#define ID_CLOSE 104
#define WM_DONE (WM_APP + 1)
static int g_busy, g_action;

static DWORD WINAPI worker(LPVOID arg) {
    (void)arg;
    g_err[0] = 0;
    int ok = g_action == ID_INSTALL ? do_install() : do_uninstall();
    PostMessageW(g_wnd, WM_DONE, ok, 0);
    return 0;
}

static void set_busy(int b) {
    g_busy = b;
    EnableWindow(g_bInstall, !b); EnableWindow(g_bUninstall, !b); EnableWindow(g_bBrowse, !b); EnableWindow(g_edit, !b);
}

static void refresh_buttons(void) {
    wchar_t p[MAX_PATH * 2];
    GetWindowTextW(g_edit, g_game, MAX_PATH);
    state_path(p, L"installed.txt");
    EnableWindow(g_bUninstall, !g_busy && file_exists(p));
    EnableWindow(g_bInstall, !g_busy && is_game(g_game));
}

static LRESULT CALLBACK wndproc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    switch (m) {
    case WM_COMMAND:
        if (LOWORD(wp) == ID_BROWSE) {
            BROWSEINFOW bi = {0}; bi.hwndOwner = w; bi.lpszTitle = L"Choose the Disgaea 5 Complete folder";
            bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
            LPITEMIDLIST id = SHBrowseForFolderW(&bi);
            if (id) { wchar_t d[MAX_PATH]; if (SHGetPathFromIDListW(id, d)) SetWindowTextW(g_edit, d); CoTaskMemFree(id); }
            refresh_buttons();
        } else if (LOWORD(wp) == ID_INSTALL || LOWORD(wp) == ID_UNINSTALL) {
            GetWindowTextW(g_edit, g_game, MAX_PATH);
            if (!is_game(g_game)) { MessageBoxW(w, L"That folder doesn't contain Disgaea 5 Complete (disgaea5.exe and Data).", g_title, MB_ICONWARNING); return 0; }
            g_action = LOWORD(wp);
            set_busy(1);
            SetTimer(w, 1, 100, NULL);
            CreateThread(NULL, 0, worker, NULL, 0, NULL);
        } else if (LOWORD(wp) == ID_CLOSE) {
            if (!g_busy) DestroyWindow(w);
        } else if (HIWORD(wp) == EN_CHANGE) {
            refresh_buttons();
        }
        return 0;
    case WM_TIMER:
        SendMessageW(g_bar, PBM_SETPOS, g_progress, 0);
        return 0;
    case WM_DONE:
        KillTimer(w, 1);
        SendMessageW(g_bar, PBM_SETPOS, wp ? 1000 : 0, 0);
        set_busy(0);
        refresh_buttons();
        if (wp) {
            status(g_action == ID_INSTALL ? L"Installed. Start the game as usual." : L"Uninstalled: the game files are as they were.");
            MessageBoxW(w, g_action == ID_INSTALL ? L"The mods are installed. Start the game as usual." :
                        L"The mods are removed; the game files are as they were before.", g_title, MB_ICONINFORMATION);
        } else {
            status(L"Not done.");
            MessageBoxW(w, g_err[0] ? g_err : L"Something went wrong.", g_title, MB_ICONERROR);
        }
        return 0;
    case WM_CLOSE:
        if (!g_busy) DestroyWindow(w);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(w, m, wp, lp);
}

static HWND mk(const wchar_t *cls, const wchar_t *text, DWORD style, int x, int y, int cx, int cy, int id, HFONT f) {
    HWND h = CreateWindowExW(0, cls, text, WS_CHILD | WS_VISIBLE | style, x, y, cx, cy, g_wnd, (HMENU)(INT_PTR)id, GetModuleHandleW(NULL), NULL);
    SendMessageW(h, WM_SETFONT, (WPARAM)f, TRUE);
    return h;
}

static int run_gui(void) {
    INITCOMMONCONTROLSEX ic = {sizeof ic, ICC_PROGRESS_CLASS}; InitCommonControlsEx(&ic);
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    WNDCLASSW wc = {0}; wc.lpfnWndProc = wndproc; wc.hInstance = GetModuleHandleW(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW); wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1); wc.lpszClassName = L"D5PackInstaller";
    wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    RegisterClassW(&wc);
    g_wnd = CreateWindowExW(0, wc.lpszClassName, g_title, WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
                            CW_USEDEFAULT, CW_USEDEFAULT, 640, 440, NULL, NULL, wc.hInstance, NULL);
    NONCLIENTMETRICSW ncm = {sizeof ncm}; SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof ncm, &ncm, 0);
    HFONT f = CreateFontIndirectW(&ncm.lfMessageFont);
    LOGFONTW big = ncm.lfMessageFont; big.lfHeight = big.lfHeight * 3 / 2; big.lfWeight = FW_BOLD;
    HFONT fb = CreateFontIndirectW(&big);
    mk(L"STATIC", g_title, 0, 16, 12, 600, 28, 0, fb);
    mk(L"EDIT", g_desc, ES_MULTILINE | ES_READONLY | WS_VSCROLL | WS_BORDER | ES_AUTOVSCROLL, 16, 46, 600, 190, 0, f);
    mk(L"STATIC", L"Disgaea 5 Complete folder:", 0, 16, 248, 600, 20, 0, f);
    g_edit = mk(L"EDIT", g_game, WS_BORDER | ES_AUTOHSCROLL, 16, 270, 500, 24, 200, f);
    g_bBrowse = mk(L"BUTTON", L"Browse...", BS_PUSHBUTTON, 524, 269, 92, 26, ID_BROWSE, f);
    g_bar = mk(PROGRESS_CLASSW, L"", 0, 16, 306, 600, 18, 0, f);
    SendMessageW(g_bar, PBM_SETRANGE32, 0, 1000);
    g_status = mk(L"STATIC", is_game(g_game) ? L"Ready." : L"Choose the game folder.", SS_ENDELLIPSIS, 16, 330, 600, 20, 0, f);
    g_bInstall = mk(L"BUTTON", L"Install", BS_DEFPUSHBUTTON, 300, 360, 100, 30, ID_INSTALL, f);
    g_bUninstall = mk(L"BUTTON", L"Uninstall", BS_PUSHBUTTON, 408, 360, 100, 30, ID_UNINSTALL, f);
    mk(L"BUTTON", L"Close", BS_PUSHBUTTON, 516, 360, 100, 30, ID_CLOSE, f);
    refresh_buttons();
    ShowWindow(g_wnd, SW_SHOW);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (!IsDialogMessageW(g_wnd, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    }
    return 0;
}

int WINAPI WinMain(HINSTANCE hi, HINSTANCE hp, LPSTR cmd, int show) {
    (void)hi; (void)hp; (void)cmd; (void)show;
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    g_buf = (uint8_t *)malloc(CHUNK);
    int action = 0;
    for (int i = 1; i < argc; i++) {
        if (!_wcsicmp(argv[i], L"/install") && i + 1 < argc) { action = ID_INSTALL; wcsncpy(g_game, argv[++i], MAX_PATH - 1); }
        else if (!_wcsicmp(argv[i], L"/uninstall") && i + 1 < argc) { action = ID_UNINSTALL; wcsncpy(g_game, argv[++i], MAX_PATH - 1); }
        else if (!_wcsicmp(argv[i], L"/quiet")) g_quiet = 1;
    }
    if (g_quiet && AttachConsole(ATTACH_PARENT_PROCESS)) { freopen("CONOUT$", "w", stdout); }
    if (!load_package()) {
        if (g_quiet) { fwprintf(stdout, L"error: %ls\n", g_err); return 2; }
        MessageBoxW(NULL, g_err, L"D5 mod installer", MB_ICONERROR);
        return 2;
    }
    if (action) {
        size_t n = wcslen(g_game); while (n && (g_game[n - 1] == L'\\' || g_game[n - 1] == L'/')) g_game[--n] = 0;
        g_err[0] = 0;
        int ok = action == ID_INSTALL ? do_install() : do_uninstall();
        if (g_quiet) { fwprintf(stdout, ok ? L"done\n" : L"error: %ls\n", g_err); return ok ? 0 : 1; }
        MessageBoxW(NULL, ok ? L"Done." : g_err, g_title, ok ? MB_ICONINFORMATION : MB_ICONERROR);
        return ok ? 0 : 1;
    }
    find_game(g_game);
    return run_gui();
}
