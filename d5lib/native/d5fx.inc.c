/* d5fx.inc.c -- effect models without a limit (d5lib/fxpool.py writes d5fx.dat and patches the start-up preload).
 *
 * The game keeps effect models in a cache of 512 entries (0x30 bytes: used, id, manager slot = 700 + index, table
 * row, references, data, job ticket) whose data lives in the resource manager's slots 700..1099, and only shows
 * models that are already in it.  The installer leaves the models scripts show (and all mods' models) out of the
 * start-up preload; this module loads them on demand:
 *   - when a script event starts (StartScript 0x14018F4A0), the models its call tree shows (d5fx.dat lists);
 *   - when a lookup misses one: cmd_3c00 (0x14018d9f0, id in r8d), 0x1401a8a40 / 0x1401a8320 (id in ecx),
 *     0x14008ada0 (id at [rcx + 0x10]) -- detoured at their entry;
 * into a free cache entry whose manager slot is below 1100.  With none free, it releases (0x1404001f0) the model
 * that no live model instance uses (512 x 0x258 at 0x141DD7F70: +0x218 active, +0x180 manager slot) and that was
 * asked for longest ago.  Loading = what the game's load job does: the data (YKCMP .obf) -> 0x140306c40(data, slot)
 * -> the cache entry's data, then 0x1402fa580(manager, slot). */
#define FX_CACHE_VA 0x140C05A48ULL          /* -> the effect cache (512 x 0x30) */
#define FX_CACHE_N 0x200
#define FX_SLOT_BASE 700
#define FX_SLOT_END 1100                    /* the resource manager has 1100 slots */
#define FX_MGR_VA 0x146A34BF8ULL            /* -> the resource manager */
#define FX_LOAD_VA 0x140306C40ULL           /* (data, slot) -> the slot's data block */
#define FX_FINISH_VA 0x1402FA580ULL         /* (manager, slot) */
#define FX_RELEASE_VA 0x1404001F0ULL        /* (cache, index) */
#define FX_INST_VA 0x141DD7F70ULL           /* model instances: 512 x 0x258 */
#define FX_INST_N 512
#define FX_INST_SIZE 0x258
#define FX_TAB_N_VA 0x140A32ED8ULL          /* EffectTableDataBase: u16 count */
#define FX_TAB_IDS_VA 0x140A32EE8ULL        /* -> u32 ids (sorted) */
#define FX_TAB_ROWS_VA 0x140A32EF0ULL       /* -> rows (8 bytes) */
#define FX_RECENT 90                        /* frames a model asked for stays (it may be about to get an instance) */

#define VA_FX_SHOW 0x14018D9F0ULL
#define VA_FX_GET 0x1401A8A40ULL
#define VA_FX_GET2 0x1401A8320ULL
#define VA_FX_SYS 0x14008ADA0ULL
static const unsigned char FX_SHOW_ORIG[5] = {0x48, 0x89, 0x5c, 0x24, 0x08};         /* mov [rsp+8], rbx */
static const unsigned char FX_GET_ORIG[3] = {0x4c, 0x8b, 0x1d};                      /* mov r11, [rip+disp] */
static const unsigned char FX_SYS_ORIG[6] = {0x40, 0x53, 0x48, 0x83, 0xec, 0x70};    /* push rbx; sub rsp,0x70 */

typedef struct {
    unsigned char used, _p0[3];
    int id;
    int slot;
    int _p1;
    void *row;
    int ref;
    int _p2;
    void *data;
    int ticket;
    int _p3;
} fx_entry;

typedef struct { unsigned id, off, size; } fx_model;
typedef struct { unsigned ev, first, n; } fx_list;

static FILE *g_fx_file;
static fx_model *g_fx_models;
static unsigned g_fx_nmodels;
static fx_list *g_fx_lists;
static unsigned g_fx_nlists;
static unsigned *g_fx_ids;
static unsigned g_fx_stamp[FX_CACHE_N];     /* frame each cache entry was last asked for */
static int g_fx_stamp_id[FX_CACHE_N];       /* ... and for which model (an entry the game reused starts over) */
static int g_fx_hooked, g_fx_loaded, g_fx_released, g_fx_failed;
static volatile LONG g_fx_busy;
static int g_fx_mask = 31;                  /* [fx] hooks: 1 show, 2 get, 4 get2, 8 sys, 16 script start */
static int g_fx_log;                        /* [fx] log: requests logged (diagnostics) */
static int g_fx_verbose;                    /* [fx] log > 0: the first loads are logged too */
static int g_fx_room = FX_SLOT_END - FX_SLOT_BASE;   /* [fx] room: cache entries used (testing: fewer = more releases) */

static int fx_cmp_model(const void *a, const void *b) {
    unsigned x = *(const unsigned *)a, y = ((const fx_model *)b)->id;
    return x < y ? -1 : x > y;
}
static int fx_cmp_list(const void *a, const void *b) {
    unsigned x = *(const unsigned *)a, y = ((const fx_list *)b)->ev;
    return x < y ? -1 : x > y;
}

static int fx_read_index(void) {
    char path[MAX_PATH];
    snprintf(path, sizeof path, "%sd5fx.dat", g_dir);
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    unsigned head[3];
    if (fread(head, 4, 3, f) != 3 || memcmp(head, "D5FX", 4) || head[1] != 1) { fclose(f); return 0; }
    g_fx_nmodels = head[2];
    g_fx_models = (fx_model *)malloc(sizeof(fx_model) * (g_fx_nmodels + 1));
    unsigned m = 0, k = 0;
    if (!g_fx_models || fread(g_fx_models, sizeof(fx_model), g_fx_nmodels, f) != g_fx_nmodels ||
        fread(&m, 4, 1, f) != 1) { fclose(f); return 0; }
    g_fx_nlists = m;
    g_fx_lists = (fx_list *)malloc(sizeof(fx_list) * (m + 1));
    if (!g_fx_lists || fread(g_fx_lists, sizeof(fx_list), m, f) != m || fread(&k, 4, 1, f) != 1) { fclose(f); return 0; }
    g_fx_ids = (unsigned *)malloc(sizeof(unsigned) * (k + 1));
    if (!g_fx_ids || fread(g_fx_ids, 4, k, f) != k) { fclose(f); return 0; }
    g_fx_file = f;
    logf_("fx: %u effect model(s) load when shown, %u script event(s) prefetch theirs (d5fx.dat)", g_fx_nmodels, m);
    return 1;
}

static fx_entry *fx_cache(void) {
    fx_entry **pc = (fx_entry **)G(FX_CACHE_VA);
    return (pc && readable(pc, 8)) ? *pc : NULL;
}

static void *fx_row(int id) {
    unsigned short n = *(unsigned short *)G(FX_TAB_N_VA);
    unsigned *ids = *(unsigned **)G(FX_TAB_IDS_VA);
    unsigned char *rows = *(unsigned char **)G(FX_TAB_ROWS_VA);
    if (!ids || !rows) return NULL;
    int lo = 0, hi = (int)n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (ids[mid] == (unsigned)id) return rows + (size_t)mid * 8;
        if (ids[mid] < (unsigned)id) lo = mid + 1; else hi = mid - 1;
    }
    return NULL;
}

static int fx_slot_in_use(int slot) {
    unsigned char *inst = (unsigned char *)G(FX_INST_VA);
    for (int i = 0; i < FX_INST_N; i++) {
        unsigned char *p = inst + (size_t)i * FX_INST_SIZE;
        if (*(int *)(p + 0x218) && *(int *)(p + 0x180) == slot) return 1;
    }
    return 0;
}

static fx_model *fx_find_model(int id) {
    if (!g_fx_models || id < 0) return NULL;
    unsigned key = (unsigned)id;
    return (fx_model *)bsearch(&key, g_fx_models, g_fx_nmodels, sizeof(fx_model), fx_cmp_model);
}

/* a cache index whose manager slot is free: an unused entry, else the oldest unused on-demand model released */
static int fx_free_index(fx_entry *c) {
    for (int k = 0; k < g_fx_room; k++)
        if (!c[k].used) return k;
    int best = -1;
    unsigned oldest = 0xffffffffu;
    for (int k = 0; k < g_fx_room; k++) {
        if (!fx_find_model(c[k].id)) continue;                  /* preloaded by the game: stays */
        unsigned st = g_fx_stamp_id[k] == c[k].id ? g_fx_stamp[k] : 0;
        if ((unsigned)g_frame - st < FX_RECENT && st) continue;
        if (st < oldest && !fx_slot_in_use(c[k].slot)) { oldest = st; best = k; }
    }
    if (best < 0) return -1;
    int was = c[best].id;
    ((void (*)(void *, int))G(FX_RELEASE_VA))(c, best);
    g_fx_released++;
    if (g_fx_log > 0) { g_fx_log--; logf_("fx: released %d (entry %d)", was, best); }
    return c[best].used ? -1 : best;
}

static int fx_load(fx_entry *c, fx_model *m) {
    int k = fx_free_index(c);
    if (k < 0) {
        if (g_fx_failed++ < 20) logf_("fx: no room for effect model %u (every slot's model is on screen)", m->id);
        return 0;
    }
    void *buf = malloc(m->size ? m->size : 1);
    if (!buf) return 0;
    if (fseek(g_fx_file, (long)m->off, SEEK_SET) || fread(buf, 1, m->size, g_fx_file) != m->size) {
        free(buf);
        if (g_fx_failed++ < 20) logf_("fx: d5fx.dat could not be read (model %u)", m->id);
        return 0;
    }
    int slot = FX_SLOT_BASE + k;
    fx_entry *e = &c[k];
    e->used = 1;
    e->id = (int)m->id;
    e->slot = slot;
    e->row = fx_row((int)m->id);
    e->ticket = -1;
    e->data = ((void *(*)(void *, int))G(FX_LOAD_VA))(buf, slot);
    free(buf);
    ((void (*)(void *, int))G(FX_FINISH_VA))(*(void **)G(FX_MGR_VA), slot);
    e->ref = 1;
    g_fx_stamp[k] = (unsigned)g_frame;
    g_fx_stamp_id[k] = e->id;
    g_fx_loaded++;
    return 1;
}

/* the model `id` in the cache (loaded when it is one of d5fx.dat's) */
static void fx_ensure_from(int id, int from) {
    if (g_fx_log > 0) {
        g_fx_log--;
        logf_("fx: request %d (hook %d, thread %lu, busy %ld)", id, from, GetCurrentThreadId(), (long)g_fx_busy);
    }
    if (!g_fx_file || InterlockedExchange(&g_fx_busy, 1)) return;
    fx_entry *c = fx_cache();
    if (c) {
        int k;
        for (k = 0; k < FX_CACHE_N; k++)
            if (c[k].used && c[k].id == id) break;
        if (k < FX_CACHE_N) {
            g_fx_stamp[k] = (unsigned)g_frame;
            g_fx_stamp_id[k] = id;
        } else {
            fx_model *m = fx_find_model(id);
            if (m) {
                int ok = fx_load(c, m);
                if (g_fx_verbose && g_fx_loaded <= 64)
                    logf_("fx: load %d -> %s", id, ok ? "ok" : "failed");
            }
        }
    }
    InterlockedExchange(&g_fx_busy, 0);
}
static void fx_ensure(int id) { fx_ensure_from(id, 0); }

static void fx_script_start(int ev) {
    if (g_fx_rec_watch && *g_fx_rec_watch == ev && g_fx_rec_hit) *g_fx_rec_hit = 1;
    if (!g_fx_lists) return;
    unsigned key = (unsigned)ev;
    fx_list *l = (fx_list *)bsearch(&key, g_fx_lists, g_fx_nlists, sizeof(fx_list), fx_cmp_list);
    if (!l) return;
    for (unsigned i = 0; i < l->n; i++) fx_ensure_from((int)g_fx_ids[l->first + i], 16);
}

static void fx_show(int id) { fx_ensure_from(id, 1); }
static void fx_get(int id) { fx_ensure_from(id, 2); }
static void fx_get2(int id) { fx_ensure_from(id, 4); }
static void fx_sys(int id) { fx_ensure_from(id, 8); }

/* an entry detour: keeps rax rcx rdx r8 r9 r10 r11 and xmm0-3, calls fn(ecx = id from `idmode`), runs the
   displaced bytes `disp` (n), then jumps back to the site + `back`.  idmode: 0 ecx, 1 r8d, 2 [rcx+0x10], 3 edx */
static int fx_stub(unsigned char *t, unsigned long long va, const unsigned char *disp, int n, int back, void *fn,
                   int idmode) {
    int k = 0;
    static const unsigned char push[] = {0x50, 0x51, 0x52, 0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53};
    memcpy(t + k, push, sizeof push); k += sizeof push;
    t[k++] = 0x48; t[k++] = 0x83; t[k++] = 0xec; t[k++] = 0x60;                 /* sub rsp, 0x60 */
    static const unsigned char sx[] = {0xf3, 0x0f, 0x7f, 0x44, 0x24, 0x20, 0xf3, 0x0f, 0x7f, 0x4c, 0x24, 0x30,
                                       0xf3, 0x0f, 0x7f, 0x54, 0x24, 0x40, 0xf3, 0x0f, 0x7f, 0x5c, 0x24, 0x50};
    memcpy(t + k, sx, sizeof sx); k += sizeof sx;                               /* movdqu [rsp+0x20..], xmm0-3 */
    if (idmode == 1) { t[k++] = 0x44; t[k++] = 0x89; t[k++] = 0xc1; }          /* mov ecx, r8d */
    else if (idmode == 2) { t[k++] = 0x8b; t[k++] = 0x49; t[k++] = 0x10; }     /* mov ecx, [rcx+0x10] */
    else if (idmode == 3) { t[k++] = 0x89; t[k++] = 0xd1; }                    /* mov ecx, edx */
    t[k++] = 0x48; t[k++] = 0xb8; memcpy(t + k, &fn, 8); k += 8;               /* mov rax, fn */
    t[k++] = 0xff; t[k++] = 0xd0;                                               /* call rax */
    static const unsigned char lx[] = {0xf3, 0x0f, 0x6f, 0x44, 0x24, 0x20, 0xf3, 0x0f, 0x6f, 0x4c, 0x24, 0x30,
                                       0xf3, 0x0f, 0x6f, 0x54, 0x24, 0x40, 0xf3, 0x0f, 0x6f, 0x5c, 0x24, 0x50};
    memcpy(t + k, lx, sizeof lx); k += sizeof lx;
    t[k++] = 0x48; t[k++] = 0x83; t[k++] = 0xc4; t[k++] = 0x60;                 /* add rsp, 0x60 */
    static const unsigned char pop[] = {0x41, 0x5b, 0x41, 0x5a, 0x41, 0x59, 0x41, 0x58, 0x5a, 0x59, 0x58};
    memcpy(t + k, pop, sizeof pop); k += sizeof pop;
    memcpy(t + k, disp, n); k += n;
    unsigned char *site = (unsigned char *)G(va);
    t[k++] = 0xe9; *(int *)(t + k) = (int)((site + back) - (t + k + 4)); k += 4;
    return k;
}

static int fx_jump(unsigned long long va, unsigned char *to, int n) {
    unsigned char j[16];
    unsigned char *site = (unsigned char *)G(va);
    j[0] = 0xe9;
    *(int *)(j + 1) = (int)(to - (site + 5));
    for (int i = 5; i < n; i++) j[i] = 0x90;
    return write_code(va, j, n);
}

/* the 'mov r11, [rip + disp]' at a lookup's entry, re-encoded for the stub: mov r11, imm64; mov r11, [r11] */
static int fx_r11_load(unsigned char *out, unsigned long long va) {
    unsigned char *site = (unsigned char *)G(va);
    unsigned long long target = (unsigned long long)(site + 7 + *(int *)(site + 3));
    out[0] = 0x49; out[1] = 0xbb; memcpy(out + 2, &target, 8);
    out[10] = 0x4d; out[11] = 0x8b; out[12] = 0x1b;
    return 13;
}

static void fx_hook_start_script(unsigned char *pg) {
    unsigned char *site = (unsigned char *)G(VA_START_SCRIPT);
    if (memcmp(site, START_SCRIPT_ORIG, 5)) { logf_("fx: script start not as expected (no prefetch)"); return; }
    unsigned char *t = pg + 0xa00;
    fx_stub(t, VA_START_SCRIPT, START_SCRIPT_ORIG, 5, 5, (void *)fx_script_start, 3);
    if (!(g_fx_mask & 16)) return;
    if (fx_jump(VA_START_SCRIPT, t, 5)) g_fx_ss_hooked = 1;
}

static void fx_install(void) {
    char ini[MAX_PATH];
    snprintf(ini, sizeof ini, "%sd5auto.ini", g_dir);
    g_fx_mask = GetPrivateProfileIntA("fx", "hooks", 31, ini);
    g_fx_log = GetPrivateProfileIntA("fx", "log", 0, ini);
    g_fx_verbose = g_fx_log > 0;
    g_fx_room = GetPrivateProfileIntA("fx", "room", FX_SLOT_END - FX_SLOT_BASE, ini);
    if (g_fx_room < 1 || g_fx_room > FX_SLOT_END - FX_SLOT_BASE) g_fx_room = FX_SLOT_END - FX_SLOT_BASE;
    if (g_fx_hooked || !fx_read_index()) return;
    unsigned char *pg = near_page();
    if (!pg || memcmp(G(VA_FX_SHOW), FX_SHOW_ORIG, 5) || memcmp(G(VA_FX_GET), FX_GET_ORIG, 3) ||
        memcmp(G(VA_FX_GET2), FX_GET_ORIG, 3) || memcmp(G(VA_FX_SYS), FX_SYS_ORIG, 6)) {
        logf_("fx: effect code not as expected - effect models load only at start");
        return;
    }
    /* the page's other users: 0x000-0x540 auto-battle / UI / colours, 0x700 recording; ours: 0x800-0xbff */
    unsigned char r11a[16], r11b[16];
    int na = fx_r11_load(r11a, VA_FX_GET), nb = fx_r11_load(r11b, VA_FX_GET2);
    fx_stub(pg + 0x800, VA_FX_SHOW, FX_SHOW_ORIG, 5, 5, (void *)fx_show, 1);
    fx_stub(pg + 0x880, VA_FX_GET, r11a, na, 7, (void *)fx_get, 0);
    fx_stub(pg + 0x900, VA_FX_GET2, r11b, nb, 7, (void *)fx_get2, 0);
    fx_stub(pg + 0x980, VA_FX_SYS, FX_SYS_ORIG, 6, 6, (void *)fx_sys, 2);
    int ok = 1;
    if (g_fx_mask & 1) ok &= fx_jump(VA_FX_SHOW, pg + 0x800, 5);
    if (g_fx_mask & 2) ok &= fx_jump(VA_FX_GET, pg + 0x880, 7);
    if (g_fx_mask & 4) ok &= fx_jump(VA_FX_GET2, pg + 0x900, 7);
    if (g_fx_mask & 8) ok &= fx_jump(VA_FX_SYS, pg + 0x980, 6);
    fx_hook_start_script(pg);
    g_fx_hooked = ok;
    logf_("fx: effect models load when shown%s (hooks %d)", ok ? "" : " (a detour failed)", g_fx_mask);
}

static void fx_uninstall(void) {
    if (!g_fx_hooked) return;
    if (g_fx_mask & 1) write_code(VA_FX_SHOW, FX_SHOW_ORIG, 5);
    unsigned char a[7], b[7];
    /* the original rip-relative loads */
    memcpy(a, FX_GET_ORIG, 3); memcpy(b, FX_GET_ORIG, 3);
    *(int *)(a + 3) = (int)(0x140C05A48ULL - (VA_FX_GET + 7));
    *(int *)(b + 3) = (int)(0x140C05A48ULL - (VA_FX_GET2 + 7));
    if (g_fx_mask & 2) write_code(VA_FX_GET, a, 7);
    if (g_fx_mask & 4) write_code(VA_FX_GET2, b, 7);
    if (g_fx_mask & 8) write_code(VA_FX_SYS, FX_SYS_ORIG, 6);
    if (g_fx_ss_hooked) { write_code(VA_START_SCRIPT, START_SCRIPT_ORIG, 5); g_fx_ss_hooked = 0; }
    g_fx_hooked = 0;
    if (g_fx_file) { fclose(g_fx_file); g_fx_file = NULL; }
    logf_("fx: %d model(s) loaded on demand, %d released", g_fx_loaded, g_fx_released);
}
