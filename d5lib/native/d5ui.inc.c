/* d5ui.inc.c -- which of the game's state machines are running (screens, menus, windows, battle phases).
 *
 * The game drives its screens, menus, message windows and battle phases with one state-machine framework:
 * 0x14086a1e0 runs one state-machine object per call -- vtable at +0, next state +0x08, previous +0x10,
 * current state +0x14, phase (enter / update / leave) +0x2c, a state stack at +0x34 with its depth at +0x70.
 * A detour on that function records every object that ran during a frame; the vtable says what kind of
 * screen it is, the state where it is.  (Included by d5auto.c; needs near_page / write_code / to_static.) */
#define VA_SM_RUN 0x14086a1e0ULL
static const unsigned char SM_RUN_ORIG[6] = {0x40, 0x53, 0x48, 0x83, 0xec, 0x20};   /* push rbx; sub rsp,0x20 */

typedef struct { unsigned long long vt; unsigned char *obj; int state, phase, depth, stack[6]; } SMREC;
#define SM_MAX 384
static SMREC g_sm_buf[2][SM_MAX];
static int g_sm_n[2], g_sm_w;               /* g_sm_w: the buffer this frame writes */
static int g_sm_hooked;

static void sm_note(unsigned char *obj) {
    int w = g_sm_w;
    if (g_sm_n[w] >= SM_MAX) return;
    SMREC *r = &g_sm_buf[w][g_sm_n[w]++];
    r->obj = obj;
    r->vt = to_static(*(DWORD64 *)obj);
    r->state = *(int *)(obj + 0x14);
    r->phase = *(int *)(obj + 0x2c);
    r->depth = *(int *)(obj + 0x70);
    for (int i = 0; i < 6; i++) r->stack[i] = i < r->depth ? *(int *)(obj + 0x34 + 4 * i) : -1;
}

/* start of d5_frame: what ran during the previous frame becomes readable */
static int g_tx_n[2];
static void sm_flip(void) {
    g_sm_w ^= 1;
    g_sm_n[g_sm_w] = 0;
    g_tx_n[g_sm_w] = 0;
}
static const SMREC *sm_list(int *n) {
    int r = g_sm_w ^ 1;
    *n = g_sm_n[r];
    return g_sm_buf[r];
}
/* the state of the first running object with this vtable, or -1 */
static int sm_state(unsigned long long vt) {
    int n;
    const SMREC *l = sm_list(&n);
    for (int i = 0; i < n; i++)
        if (l[i].vt == vt) return l[i].state;
    return -1;
}

static void install_sm_hook(void) {
    unsigned char *site = (unsigned char *)G(VA_SM_RUN), *pg = near_page();
    if (!pg || memcmp(site, SM_RUN_ORIG, 6)) { logf_("ui: state-machine runner not as expected - no screen tracking"); return; }
    unsigned char *t = pg + 0x200;
    int n = 0;
    t[n++] = 0x51;                                             /* push rcx */
    t[n++] = 0x48; t[n++] = 0x83; t[n++] = 0xec; t[n++] = 0x20; /* sub rsp, 0x20 */
    t[n++] = 0x48; t[n++] = 0xb8;                              /* mov rax, sm_note */
    void *fn = (void *)sm_note;
    memcpy(t + n, &fn, 8); n += 8;
    t[n++] = 0xff; t[n++] = 0xd0;                              /* call rax */
    t[n++] = 0x48; t[n++] = 0x83; t[n++] = 0xc4; t[n++] = 0x20; /* add rsp, 0x20 */
    t[n++] = 0x59;                                             /* pop rcx */
    memcpy(t + n, SM_RUN_ORIG, 6); n += 6;                     /* the replaced instructions */
    t[n++] = 0xe9;
    *(int *)(t + n) = (int)((site + 6) - (t + n + 4)); n += 4;  /* back to 0x14086a1e6 */
    unsigned char j[6] = {0xe9, 0, 0, 0, 0, 0x90};
    *(int *)(j + 1) = (int)(t - (site + 5));
    write_code(VA_SM_RUN, j, 6);
    g_sm_hooked = 1;
    logf_("ui: state-machine tracking on");
}

/* ------------------------------------------------------------------ screen text
 * 0x1403fae60 draws one string (377 callers: message windows, menus, help lines, battle numbers ...):
 * ecx x, edx y, r8d / r9 style, 5th argument (stack +0x28) the string (a printf format), 6th (+0x30) a float
 * scale.  A detour records every string drawn during a frame with its position and the calling code. */
#define VA_DRAW_TEXT 0x1403fae60ULL
static const unsigned char DRAW_TEXT_ORIG[7] = {0x40, 0x55, 0x53, 0x56, 0x57, 0x41, 0x54};

typedef struct { int x, y, a3; unsigned int color; unsigned long long caller; char s[100]; } TXREC;
#define TX_MAX 320
static TXREC g_tx_buf[2][TX_MAX];
/* g_tx_n (declared above) shares g_sm_w as the frame buffer index */
static int g_tx_hooked;

/* Some callers pass a string pointer the game never reads (e.g. the unit information tab of a character without
 * personal data), so every byte we copy must be in committed, readable memory.  The last readable region is cached:
 * nearly all strings live in the same few regions. */
static const char *g_rd_lo, *g_rd_hi;

static int text_readable(const void *p) {
    const char *c = (const char *)p;
    if ((unsigned long long)c < 0x10000ULL || (unsigned long long)c >= 0x7fffffff0000ULL) return 0;
    if (c >= g_rd_lo && c < g_rd_hi) return 1;
    MEMORY_BASIC_INFORMATION mi;
    if (!VirtualQuery(c, &mi, sizeof mi) || mi.State != MEM_COMMIT) return 0;
    DWORD pr = mi.Protect & 0xff;
    if (mi.Protect & (PAGE_GUARD | PAGE_NOACCESS) || pr == PAGE_EXECUTE) return 0;
    g_rd_lo = (const char *)mi.BaseAddress;
    g_rd_hi = g_rd_lo + mi.RegionSize;
    return 1;
}

static void text_note(int x, int y, int a3, void *a4, unsigned char *rsp0) {
    int w = g_sm_w;
    if (g_tx_n[w] >= TX_MAX) return;
    const char *str = *(const char **)(rsp0 + 0x28);
    if (!text_readable(str)) {
        /* the game would crash formatting it: draw an empty string instead (logged once per caller) */
        static unsigned long long seen[16];
        unsigned long long from = to_static(*(DWORD64 *)rsp0);
        int k = 0;
        while (k < 16 && seen[k] && seen[k] != from) k++;
        if (k < 16 && !seen[k]) { seen[k] = from; logf_("ui: unreadable string %p drawn from %llx - drawing nothing", str, from); }
        if (str) *(const char **)(rsp0 + 0x28) = "";
        return;
    }
    TXREC *r = &g_tx_buf[w][g_tx_n[w]++];
    r->x = x; r->y = y; r->a3 = a3;
    r->color = a4 && text_readable(a4) ? *(const unsigned int *)a4 : 0;    /* 4th argument: pointer to the colour (RGBA) */
    r->caller = to_static(*(DWORD64 *)rsp0);
    int i = 0;
    for (; i < (int)sizeof r->s - 1; i++) {
        if (((unsigned long long)(str + i) & 0xfff) == 0 && !text_readable(str + i)) break;   /* next page */
        if (!str[i]) break;
        r->s[i] = str[i];
    }
    r->s[i] = 0;
}

static const TXREC *tx_list(int *n) {
    int r = g_sm_w ^ 1;
    *n = g_tx_n[r];
    return g_tx_buf[r];
}

/* is a string containing `needle` on screen (drawn last frame)? */
static const TXREC *tx_find(const char *needle) {
    int n;
    const TXREC *l = tx_list(&n);
    for (int i = 0; i < n; i++)
        if (strstr(l[i].s, needle)) return &l[i];
    return NULL;
}

static void install_text_hook(void) {
    unsigned char *site = (unsigned char *)G(VA_DRAW_TEXT), *pg = near_page();
    if (!pg || memcmp(site, DRAW_TEXT_ORIG, 7)) { logf_("ui: text function not as expected - no screen text"); return; }
    unsigned char *t = pg + 0x300;
    int n = 0;
    t[n++] = 0x51; t[n++] = 0x52; t[n++] = 0x41; t[n++] = 0x50; t[n++] = 0x41; t[n++] = 0x51; /* push rcx rdx r8 r9 */
    t[n++] = 0x48; t[n++] = 0x8d; t[n++] = 0x44; t[n++] = 0x24; t[n++] = 0x20;              /* lea rax, [rsp+0x20] */
    t[n++] = 0x48; t[n++] = 0x83; t[n++] = 0xec; t[n++] = 0x28;                            /* sub rsp, 0x28 */
    t[n++] = 0x48; t[n++] = 0x89; t[n++] = 0x44; t[n++] = 0x24; t[n++] = 0x20;              /* mov [rsp+0x20], rax */
    t[n++] = 0x48; t[n++] = 0xb8;                                                          /* mov rax, text_note */
    void *fn = (void *)text_note;
    memcpy(t + n, &fn, 8); n += 8;
    t[n++] = 0xff; t[n++] = 0xd0;                                                          /* call rax */
    t[n++] = 0x48; t[n++] = 0x83; t[n++] = 0xc4; t[n++] = 0x28;                            /* add rsp, 0x28 */
    t[n++] = 0x41; t[n++] = 0x59; t[n++] = 0x41; t[n++] = 0x58; t[n++] = 0x5a; t[n++] = 0x59; /* pop r9 r8 rdx rcx */
    memcpy(t + n, DRAW_TEXT_ORIG, 7); n += 7;
    t[n++] = 0xe9;
    *(int *)(t + n) = (int)((site + 7) - (t + n + 4)); n += 4;
    unsigned char j[7] = {0xe9, 0, 0, 0, 0, 0x90, 0x90};
    *(int *)(j + 1) = (int)(t - (site + 5));
    write_code(VA_DRAW_TEXT, j, 7);
    g_tx_hooked = 1;
    logf_("ui: screen-text capture on");
}

/* ------------------------------------------------------------------ screen log (research)
 * Logs every new "screen": the running state machines with their states and the strings on screen (numbers
 * blanked, key legends / news ticker left out), once it has been stable for a few frames. */
static int tx_noise(unsigned long long caller) {
    return caller == 0x140427b02ULL        /* key legend */
        || caller == 0x14042163aULL;       /* news ticker / geo label */
}

static void screen_sig(char *out, size_t cap) {
    size_t k = 0;
    int n;
    const SMREC *l = sm_list(&n);
    k += snprintf(out + k, cap - k, "m%d", *(volatile int *)G(VA_SCENE_MODE));
    for (int i = 0; i < n && k < cap - 32; i++)
        if (l[i].state != -1) k += snprintf(out + k, cap - k, " %llx:%d", l[i].vt & 0xffff, l[i].state);
    const TXREC *t = tx_list(&n);
    for (int i = 0; i < n && k < cap - 8; i++) {
        if (tx_noise(t[i].caller)) continue;
        k += snprintf(out + k, cap - k, " |");
        for (const char *p = t[i].s; *p && k < cap - 4; p++)
            out[k++] = (*p >= '0' && *p <= '9') ? '#' : *p;
        out[k] = 0;
    }
}

static void screen_log_tick(void) {
    static char last[4096], cand[4096];
    static int stable;
    char sig[4096];
    screen_sig(sig, sizeof sig);
    if (strcmp(sig, cand)) { strcpy(cand, sig); stable = 0; return; }
    if (++stable != 12 || !strcmp(cand, last)) return;
    strcpy(last, cand);
    int n;
    const SMREC *l = sm_list(&n);
    char sms[1024];
    size_t k = 0;
    sms[0] = 0;
    for (int i = 0; i < n && k < sizeof sms - 32; i++)
        if (l[i].state != -1) k += snprintf(sms + k, sizeof sms - k, " %llx:%d", l[i].vt, l[i].state);
    logf_("SCREEN mode %d |%s", *(volatile int *)G(VA_SCENE_MODE), sms);
    const TXREC *t = tx_list(&n);
    for (int i = 0; i < n; i++)
        if (!tx_noise(t[i].caller)) logf_("   (%4d,%4d) %llx  %s", t[i].x, t[i].y, t[i].caller, t[i].s);
}
