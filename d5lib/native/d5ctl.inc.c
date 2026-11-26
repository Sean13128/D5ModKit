/* d5ctl.inc.c -- remote control / test harness (included by d5auto.c; only active with [debug] remote=1).
 *
 * A named pipe \\.\pipe\d5auto_ctl takes one command per line and answers one line (mostly JSON).  The D5 Mod
 * Kit's tools/d5ctl.py is the client.  Commands:
 *   ping                          -> {"ok":1,"frame":N}
 *   state                         -> scene mode, Item World flags, cursor, base panel, auto-battle state, units
 *   keys K S:3:8 ...              press keys in order (name[:hold[:gap]] frames); answers when all were pressed
 *   wait N                        answers after N game frames
 *   shot PATH                     screenshot of the next presented frame -> 24-bit BMP at PATH
 *   record EVENT EVERY SCALE MAX DIR | record stop | record status
 *                                 save the game's frames from the start of script EVENT (a skill: 12000000 + id)
 *   rd ADDR N / wr ADDR HEX       read / write memory (ADDR 0x14xxxxxxx = static VA of the exe, else absolute)
 *   dump ADDR N PATH              memory -> file
 *   scan new SIZE VALUE | scan next OP [VALUE] | scan list [N]
 *                                 value scanner over writable memory (SIZE 1/2/4/8/f; OP eq ne gt lt changed
 *                                 unchanged inc dec)
 *   trace ADDR LEN RW LABEL ... | trace off
 *   watch ADDR LEN [tf|spin] | watch status|dump|off|selftest
 *                                 software write-watch (page protection + trap flag; d5wwatch.inc.c): names the
 *                                 instruction that writes a range; works where `trace` does not (CrossOver)
 *                                 hardware watchpoints (RW 1 = write, 3 = read/write), hits go to d5auto.log
 *   auto on|off                   switch auto-battle (ignores the Item World check with "auto force")
 *   focus on|off                  the game believes it has focus (GetForegroundWindow) and ignores the real
 *                                 keyboard, so it can be driven while another window is in front
 *   (input guard)                 [debug] input_guard (default 1 with remote=1; d5inputguard.h): from the first frame
 *                                 the real keyboard, mouse and pads (XInput, DirectInput) never reach the game, only
 *                                 the harness's presses; `state` counts the dropped polls (guard_kb, guard_pad).
 *                                 `set input_guard 0` (plus `focus off`) lets a person's input through again
 *   win offscreen [X Y] | hide | show | state
 *                                 move the game window off every screen / hide it / put it back (d5winhide.h);
 *                                 `set input_guard 0` puts it back too
 *   silent on|off|status          the game's four volume masters 0 (nothing is written to a save); status
 *                                 reads them back -- agent launches are silent by default (d5sound.inc.c)
 *   set NAME VALUE                tweak a setting at run time (sp_saving, kill_margin, deploy, ...)
 *   prof MS                       sample the game thread for MS ms: where its time goes (leaf / inclusive)
 *   mem                           the process's memory, handles, heaps
 *   dlg                           the process's windows and the texts of their children (reads a stuck error box)
 *   stk [N]                       the frame thread's stack words that point into modules (module+offset)
 */
#define CTL_PIPE "\\\\.\\pipe\\d5auto_ctl"

static HWND g_hwnd;                          /* the game's main window */

/* ------------------------------------------------------------------ small JSON / text helpers */
typedef struct { char *p; size_t n, cap; } SB;
static void sb_put(SB *s, const char *t, size_t k) {
    if (s->n + k + 1 > s->cap) {
        size_t c = s->cap ? s->cap : 4096;
        while (c < s->n + k + 1) c *= 2;
        char *q = (char *)realloc(s->p, c);
        if (!q) return;
        s->p = q; s->cap = c;
    }
    memcpy(s->p + s->n, t, k);
    s->n += k;
    s->p[s->n] = 0;
}
static void sbf(SB *s, const char *fmt, ...) {
    char buf[2048];
    va_list a;
    va_start(a, fmt);
    int k = vsnprintf(buf, sizeof buf, fmt, a);
    va_end(a);
    if (k > 0) sb_put(s, buf, (size_t)(k < (int)sizeof buf ? k : (int)sizeof buf - 1));
}
static void sb_str(SB *s, const char *t) {        /* JSON string */
    sb_put(s, "\"", 1);
    for (; *t; t++) {
        unsigned char c = (unsigned char)*t;
        if (c == '"' || c == '\\') { char e[2] = {'\\', (char)c}; sb_put(s, e, 2); }
        else if (c < 32 || c > 126) sbf(s, "\\u%04x", c);
        else sb_put(s, (const char *)&c, 1);
    }
    sb_put(s, "\"", 1);
}

static unsigned char *ctl_addr(unsigned long long a) {
    if (a >= 0x140000000ULL && a < 0x140000000ULL + g_image_size) return (unsigned char *)G(a);
    return (unsigned char *)a;
}

/* key names for "keys" (DIK codes) */
static int dik_of(const char *n) {
    static const struct { const char *n; int d; } T[] = {
        {"ESC", DIK_ESCAPE}, {"ENTER", DIK_RETURN}, {"SPACE", DIK_SPACE}, {"TAB", DIK_TAB}, {"BACK", DIK_BACK},
        {"UP", DIK_UP}, {"DOWN", DIK_DOWN}, {"LEFT", DIK_LEFT}, {"RIGHT", DIK_RIGHT}, {"LSHIFT", DIK_LSHIFT}, {"RSHIFT", DIK_RSHIFT},
        {"LCTRL", DIK_LCONTROL}, {"F1", DIK_F1}, {"F2", DIK_F2}, {"F3", DIK_F3}, {"F4", DIK_F4}, {"F9", DIK_F9},
        {"F10", DIK_F10}, {"F11", DIK_F11}, {"F12", DIK_F12}, {"PGUP", DIK_PRIOR}, {"PGDN", DIK_NEXT},
        {"HOME", DIK_HOME}, {"END", DIK_END}, {"DEL", DIK_DELETE}, {"INS", DIK_INSERT},
        {"COMMA", DIK_COMMA}, {"PERIOD", DIK_PERIOD}, {"SLASH", DIK_SLASH}, {"SEMICOLON", DIK_SEMICOLON},
        {"MINUS", DIK_MINUS}, {"EQUALS", DIK_EQUALS}, {"LBRACKET", DIK_LBRACKET}, {"RBRACKET", DIK_RBRACKET}};
    static const int LET[26] = {DIK_A, DIK_B, DIK_C, DIK_D, DIK_E, DIK_F, DIK_G, DIK_H, DIK_I, DIK_J, DIK_K, DIK_L,
                                DIK_M, DIK_N, DIK_O, DIK_P, DIK_Q, DIK_R, DIK_S, DIK_T, DIK_U, DIK_V, DIK_W, DIK_X,
                                DIK_Y, DIK_Z};
    static const int NUM[10] = {DIK_0, DIK_1, DIK_2, DIK_3, DIK_4, DIK_5, DIK_6, DIK_7, DIK_8, DIK_9};
    if (n[0] && !n[1]) {
        char c = n[0];
        if (c >= 'a' && c <= 'z') c -= 32;
        if (c >= 'A' && c <= 'Z') return LET[c - 'A'];
        if (c >= '0' && c <= '9') return NUM[c - '0'];
    }
    for (size_t i = 0; i < sizeof T / sizeof T[0]; i++)
        if (!_stricmp(n, T[i].n)) return T[i].d;
    if (n[0] == '#') return (int)strtol(n + 1, NULL, 16);
    return -1;
}

/* ------------------------------------------------------------------ focus */
static BOOL CALLBACK find_game_window(HWND w, LPARAM lp) {
    DWORD pid = 0;
    GetWindowThreadProcessId(w, &pid);
    if (pid == GetCurrentProcessId() && (IsWindowVisible(w) || g_wh_mode) && !GetWindow(w, GW_OWNER)) {
        char cls[64];
        GetClassNameA(w, cls, sizeof cls);
        if (strcmp(cls, "d5auto_dummy")) { *(HWND *)lp = w; return FALSE; }
    }
    return TRUE;
}
static HWND game_window(void) {
    if (!g_hwnd || !IsWindow(g_hwnd)) {
        g_hwnd = NULL;
        EnumWindows(find_game_window, (LPARAM)&g_hwnd);
    }
    return g_hwnd;
}

#define VA_IAT_GETFOREGROUNDWINDOW 0x1408d55b0ULL
typedef HWND(WINAPI *GetForegroundWindow_t)(void);
static GetForegroundWindow_t oGetForegroundWindow;
static HWND WINAPI hkGetForegroundWindow(void) {
    if (g_fake_focus && g_hwnd) return g_hwnd;
    return oGetForegroundWindow();
}
/* with fake focus the real mouse pointer is hidden from the game: it would otherwise pin list and menu cursors to
   the row under it */
#define VA_IAT_GETCURSORPOS 0x1408d5610ULL
typedef BOOL(WINAPI *GetCursorPos_t)(LPPOINT);
static GetCursorPos_t oGetCursorPos;
static BOOL WINAPI hkGetCursorPos(LPPOINT pt) {
    if (input_guarded() && pt) {
        pt->x = -32000;
        pt->y = -32000;
        return TRUE;
    }
    return oGetCursorPos(pt);
}
/* the harness never lets the game write a save while it drives it (remote=1): opening a file in SaveData for
   writing fails as if the disk refused it */
#define VA_IAT_CREATEFILEA 0x1408d5060ULL
#define VA_IAT_CREATEFILEW 0x1408d54c0ULL
#define VA_IAT_DELETEFILEA 0x1408d5350ULL
#define VA_IAT_DELETEFILEW 0x1408d5188ULL
typedef HANDLE(WINAPI *CreateFileA_t)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef HANDLE(WINAPI *CreateFileW_t)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef BOOL(WINAPI *DeleteFileA_t)(LPCSTR);
typedef BOOL(WINAPI *DeleteFileW_t)(LPCWSTR);
static CreateFileA_t oCreateFileA;
static CreateFileW_t oCreateFileW;
static DeleteFileA_t oDeleteFileA;
static DeleteFileW_t oDeleteFileW;
static int is_save_path_a(const char *p) {        /* saves, and the option files the Options menu writes */
    return p && (strstr(p, "SaveData") || strstr(p, "savedata") || strstr(p, ".sav") || strstr(p, "keysettings.bin")
                 || strstr(p, "config.ini"));
}
static int is_save_path_w(const wchar_t *p) {
    return p && (wcsstr(p, L"SaveData") || wcsstr(p, L"savedata") || wcsstr(p, L".sav") ||
                 wcsstr(p, L"keysettings.bin") || wcsstr(p, L"config.ini"));
}

/* ------------------------------------------------------------------ battle skit fast-forward
   The game's own options 'always fast forward the skits during battle' (0x1469cd8b9) and 'Skit Fast Forward Speed'
   (0x1469cd8ba, x2/x3/x4): 0x1404d0400 sets the per-frame request with 'mov byte [0x140a95a03], 1' at 0x1404d0483,
   then only every N-th frame (N = [0x140a30b34]) is drawn and the skipped ones bypass the 60 fps limiter.  While the
   harness drives the game (remote=1) skits run at g_skitff: 0 = 1x (no fast-forward), 2..4 = xN, -1 = the game's own
   option.  Memory only: nothing is saved. */
#define VA_FF_SET_ON 0x1404d0483ULL
#define VA_FF_READ 0x1404d044eULL           /* movzx r11d, byte [VA_FF_ALWAYS]: the 'always' option, read per frame */
#define VA_FF_ALWAYS 0x1469cd8b9ULL
#define VA_FF_LEVEL 0x1469cd8baULL
#define VA_FF_MULT 0x140a30b34ULL
/* g_skitff: -1 = the game's own options; 0 = never fast-forward (not even the button); 1 = normal speed, the
   fast-forward button still works (the 'always' option reads as off); 2..4 = always fast-forward at xN.
   From the ini [battle] speed (0 game, 1 normal, 2-4) or the harness 'set skitff'. */
static int g_skitff = -2;                   /* -2: not set yet (ctl_tick takes the ini value) */
static int g_skitff_orig_mult = -1;

static void skitff_apply(void) {
    /* mov byte [rip+d], 0/1 and movzx r11d, byte [VA_FF_ALWAYS]: the displacements differ between game builds */
    static const unsigned char ON[2] = {0xc6, 0x05};
    unsigned char RD[8] = {0x44, 0x0f, 0xb6, 0x1d};
    static const unsigned char RD_OFF[8] = {0x45, 0x31, 0xdb, 0x0f, 0x1f, 0x44, 0x00, 0x00};   /* xor r11d,r11d; nop5 */
    static const unsigned char RD_ON[8] = {0x41, 0xb3, 0x01, 0x0f, 0x1f, 0x44, 0x00, 0x00};    /* mov r11b,1; nop5 */
    unsigned char *p = (unsigned char *)G(VA_FF_SET_ON), *r = (unsigned char *)G(VA_FF_READ), b[7];
    *(int *)(RD + 4) = (int)((unsigned char *)G(VA_FF_ALWAYS) - (r + 8));
    if (memcmp(p, ON, 2) || p[6] > 1) return;              /* not the expected code: leave it alone */
    if (memcmp(r, RD, 8) && memcmp(r, RD_OFF, 8) && memcmp(r, RD_ON, 8)) return;
    memcpy(b, p, 7);
    b[6] = g_skitff == 0 ? 0 : 1;
    if (p[6] != b[6]) write_code(VA_FF_SET_ON, b, 7);      /* write_code keeps the original for core_shutdown */
    const unsigned char *want = g_skitff == 1 ? RD_OFF : g_skitff >= 2 ? RD_ON : RD;
    if (memcmp(r, want, 8)) write_code(VA_FF_READ, want, 8);
    int *mult = (int *)G(VA_FF_MULT);
    if (g_skitff >= 2) {
        if (g_skitff_orig_mult < 0) g_skitff_orig_mult = *mult;
        *mult = g_skitff;
    } else if (g_skitff < 2 && g_skitff_orig_mult >= 0) {     /* the game's own speed (also for the button) */
        *mult = g_skitff_orig_mult;
        g_skitff_orig_mult = -1;
    }
}
/* dev: the saves are READ from another folder (harness "saves_from DIR", "saves_from" alone switches it off; writes
   stay blocked): a copy of the game with no saves of its own (another Steam account folder) is tested on existing
   progress without copying anything into its save folder */
static wchar_t g_save_src[MAX_PATH];
static const wchar_t *save_file_w(const wchar_t *p) {      /* "X.sav" of ...\SaveData\X.sav, else NULL */
    const wchar_t *s = p ? wcsstr(p, L"SaveData") : NULL;
    if (!s || (s[8] != L'\\' && s[8] != L'/')) return NULL;
    s += 9;
    if (wcschr(s, L'\\') || wcschr(s, L'/') || !wcsstr(s, L".sav")) return NULL;
    return s;
}
static HANDLE WINAPI hkCreateFileA(LPCSTR p, DWORD acc, DWORD sh, LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD fl,
                                   HANDLE t) {
    if ((acc & (GENERIC_WRITE | FILE_WRITE_DATA | FILE_APPEND_DATA)) && is_save_path_a(p)) {
        logf_("ctl: save blocked (%s)", p);
        SetLastError(ERROR_ACCESS_DENIED);
        return INVALID_HANDLE_VALUE;
    }
    if (g_save_src[0] && p) {
        wchar_t w[MAX_PATH];
        if (MultiByteToWideChar(CP_ACP, 0, p, -1, w, MAX_PATH)) {
            const wchar_t *n = save_file_w(w);
            if (n) {
                wchar_t q[MAX_PATH];
                _snwprintf(q, MAX_PATH, L"%ls\\%ls", g_save_src, n);
                q[MAX_PATH - 1] = 0;
                logf_("ctl: save read from %ls", q);
                return oCreateFileW(q, acc, sh, sa, disp, fl, t);
            }
        }
    }
    return oCreateFileA(p, acc, sh, sa, disp, fl, t);
}
static HANDLE WINAPI hkCreateFileW(LPCWSTR p, DWORD acc, DWORD sh, LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD fl,
                                   HANDLE t) {
    if ((acc & (GENERIC_WRITE | FILE_WRITE_DATA | FILE_APPEND_DATA)) && is_save_path_w(p)) {
        logf_("ctl: save blocked (%ls)", p);
        SetLastError(ERROR_ACCESS_DENIED);
        return INVALID_HANDLE_VALUE;
    }
    const wchar_t *n = g_save_src[0] ? save_file_w(p) : NULL;
    if (n) {
        wchar_t q[MAX_PATH];
        _snwprintf(q, MAX_PATH, L"%ls\\%ls", g_save_src, n);
        q[MAX_PATH - 1] = 0;
        logf_("ctl: save read from %ls", q);
        return oCreateFileW(q, acc, sh, sa, disp, fl, t);
    }
    return oCreateFileW(p, acc, sh, sa, disp, fl, t);
}
static BOOL WINAPI hkDeleteFileA(LPCSTR p) {
    if (is_save_path_a(p)) { SetLastError(ERROR_ACCESS_DENIED); return FALSE; }
    return oDeleteFileA(p);
}
static BOOL WINAPI hkDeleteFileW(LPCWSTR p) {
    if (is_save_path_w(p)) { SetLastError(ERROR_ACCESS_DENIED); return FALSE; }
    return oDeleteFileW(p);
}
static void install_focus_hook(void) {
    patch_slot((void **)G(VA_IAT_GETFOREGROUNDWINDOW), (void *)hkGetForegroundWindow, (void **)&oGetForegroundWindow);
    patch_slot((void **)G(VA_IAT_GETCURSORPOS), (void *)hkGetCursorPos, (void **)&oGetCursorPos);
    patch_slot((void **)G(VA_IAT_CREATEFILEA), (void *)hkCreateFileA, (void **)&oCreateFileA);
    patch_slot((void **)G(VA_IAT_CREATEFILEW), (void *)hkCreateFileW, (void **)&oCreateFileW);
    patch_slot((void **)G(VA_IAT_DELETEFILEA), (void *)hkDeleteFileA, (void **)&oDeleteFileA);
    patch_slot((void **)G(VA_IAT_DELETEFILEW), (void *)hkDeleteFileW, (void **)&oDeleteFileW);
    logf_("ctl: GetForegroundWindow / GetCursorPos hooked; saves blocked while the harness is on");
    logf_("input: guard %s (real keyboard, mouse and pads %s; [debug] input_guard)", g_input_guard ? "on" : "off",
          g_input_guard ? "never reach the game, only the harness's presses" : "reach the game");
}

static const char *rest_after(const char *line, int n);
static void trim_end(char *s);

/* ------------------------------------------------------------------ skill recording (record command)
 * record EVENT EVERY SCALE MAX DIR: when script event EVENT starts (StartScript 0x14018F4A0, detoured: edx = the
 * event id), every EVERY-th game frame from then on is saved as DIR\fNNNNN.bmp (NNNNN = game frames since the start,
 * the frame the kit's timeline calls NNNNN), SCALE times smaller, until MAX frames; DIR\done.txt then holds the
 * count.  record stop / record status.  The game may run slower while it records: its frames stay in step. */
#define VA_START_SCRIPT 0x14018F4A0ULL
static const unsigned char START_SCRIPT_ORIG[5] = {0x48, 0x89, 0x6c, 0x24, 0x10};    /* mov [rsp+0x10], rbp */
static volatile LONG *g_rec_watch, *g_rec_hit;     /* in the trampoline page: the watched event, "it started" */
static int g_fx_ss_hooked;                         /* d5fx.inc.c detoured the script start: the recorder rides on it */
static volatile LONG *g_fx_rec_watch, *g_fx_rec_hit;
static volatile LONG g_rec_armed, g_rec_on;
static volatile LONG g_rec_start, g_rec_last, g_rec_count;
static LONG g_rec_every = 1, g_rec_scale = 2, g_rec_max = 600;
static char g_rec_dir[MAX_PATH];
static int g_rec_ready;
static FILE *g_rec_tel;                            /* DIR\telemetry.bin: camera block + drawn actors per frame */
static FILE *g_rec_probe;                          /* DIR\probe.bin: effect slots + the sorted draw queue 6 */
static LONG g_probe_from = -1, g_probe_to = -1;    /* `probe FROM TO`: the recorded frames that get a probe record */
#define PRB_SLOTS_VA 0x141DA0AE0ULL                /* effect slots (7000 + i): 256 x 0x358 */
#define PRB_SLOTS_N 64
#define PRB_SLOT_SIZE 0x358
#define PRB_DRAW_VA 0x146A34C10ULL                 /* -> draw manager: queue q records [+q*8], counts [+0x138+q*4] */
#define PRB_KEYS_VA 0x140BCB050ULL                 /* queue 6 sort keys (u64: key bits << 32 | n-1-i), sorted */
#define PRB_ORDER_VA 0x140BF2150ULL                /* queue 6 record indices in draw order (u32) */
#define PRB_REC_N 4096                             /* records / keys dumped per probe frame (fixed window) */
#define REC_CAM_VA 0x146A3AC00ULL                  /* camera state (script camera moves at 0x146A3ADA0) */
#define REC_CAM_N 0x600
#define REC_ACTORS_A 0x14150ABD0ULL                /* light / event actors: 512 x 0x3e0 */
#define REC_ACTORS_B 0x1415A5BE0ULL                /* unit actors: 256 x 0x1260 */

/* game thread: one telemetry record per frame -- 'TELE', frame, camera block, actor count, then per drawn actor:
   table (0 light / 1 unit), index, actor bytes 0x2a0-0x340, its draw object's bytes 0x00-0x60 */
static void rec_telemetry(LONG tick) {
    if (!g_rec_tel) return;
    unsigned char *cam = (unsigned char *)G(REC_CAM_VA);
    fwrite("TELE", 1, 4, g_rec_tel);
    fwrite(&tick, 4, 1, g_rec_tel);
    fwrite(cam, 1, REC_CAM_N, g_rec_tel);
    unsigned short n = 0;
    long at = ftell(g_rec_tel);
    fwrite(&n, 2, 1, g_rec_tel);
    for (int t = 0; t < 2; t++) {
        unsigned char *base = (unsigned char *)G(t ? REC_ACTORS_B : REC_ACTORS_A);
        int count = t ? 256 : 512, stride = t ? 0x1260 : 0x3e0;
        for (int i = 0; i < count; i++) {
            unsigned char *a = base + (size_t)i * stride;
            unsigned char *obj = *(unsigned char **)(a + 0x1d0);
            if (!obj || !readable(obj, 0x60)) continue;
            unsigned char tb = (unsigned char)t;
            unsigned short ix = (unsigned short)i;
            fwrite(&tb, 1, 1, g_rec_tel);
            fwrite(&ix, 2, 1, g_rec_tel);
            fwrite(a + 0x2a0, 1, 0xa0, g_rec_tel);
            fwrite(obj, 1, 0x60, g_rec_tel);
            n++;
        }
    }
    long end = ftell(g_rec_tel);
    fseek(g_rec_tel, at, SEEK_SET);
    fwrite(&n, 2, 1, g_rec_tel);
    fseek(g_rec_tel, end, SEEK_SET);
}

/* game thread, frames FROM..TO of a recording: 'PRB2', frame, 64 effect slots (0x358 bytes each), the draw manager's
   first 0x440 bytes, n (= PRB_REC_N), n sort keys, n draw-order indices, n queue-6 records (0xd8 each, manager +0x30)
   and n staged records (+0x418, the last sorted queue in draw order).  It holds the last frame drawn. */
static void rec_write_or_zero(const unsigned char *src, size_t n) {
    static unsigned char zero[0x1000];
    if (src && readable((void *)src, n)) { fwrite(src, 1, n, g_rec_probe); return; }
    while (n) { size_t k = n < sizeof zero ? n : sizeof zero; fwrite(zero, 1, k, g_rec_probe); n -= k; }
}

static void rec_probe(LONG tick) {
    if (!g_rec_probe) return;
    fwrite("PRB4", 1, 4, g_rec_probe);
    fwrite(&tick, 4, 1, g_rec_probe);
    rec_write_or_zero((unsigned char *)G(PRB_SLOTS_VA), (size_t)PRB_SLOTS_N * PRB_SLOT_SIZE);
    unsigned char *mgr = NULL;
    unsigned char **pm = (unsigned char **)G(PRB_DRAW_VA);
    if (readable(pm, 8)) mgr = *pm;
    rec_write_or_zero(mgr, 0x440);
    /* the counts are cleared once a frame is drawn, the arrays keep the last frame: a fixed window of each */
    int n = PRB_REC_N;
    fwrite(&n, 4, 1, g_rec_probe);
    rec_write_or_zero((unsigned char *)G(PRB_KEYS_VA), (size_t)n * 8);
    rec_write_or_zero((unsigned char *)G(PRB_ORDER_VA), (size_t)n * 4);
    unsigned char *recs = (mgr && readable(mgr, 0x440)) ? *(unsigned char **)(mgr + 0x30) : NULL;
    rec_write_or_zero(recs, (size_t)n * 0xd8);
    unsigned char *staged = (mgr && readable(mgr, 0x440)) ? *(unsigned char **)(mgr + 0x418) : NULL;
    rec_write_or_zero(staged, (size_t)n * 0xd8);
    /* each record's vertices: 128 bytes at its +0x30 pointer (sprites: 4 x 0x1c), 192 at +0x38 (effects: 0x3c each) */
    for (int i = 0; i < n; i++) {
        unsigned char *r = recs ? recs + (size_t)i * 0xd8 : NULL;
        unsigned char *v30 = (r && readable(r, 0xd8)) ? *(unsigned char **)(r + 0x30) : NULL;
        unsigned char *v38 = (r && readable(r, 0xd8)) ? *(unsigned char **)(r + 0x38) : NULL;
        unsigned char *m70 = (r && readable(r, 0xd8)) ? *(unsigned char **)(r + 0x70) : NULL;
        rec_write_or_zero(v30, 128);
        rec_write_or_zero(v38, 192);
        rec_write_or_zero(m70, 64);
    }
}

static int rec_prepare(void) {
    if (g_rec_ready) return 1;
    unsigned char *site = (unsigned char *)G(VA_START_SCRIPT);
    unsigned char *pg = near_page();
    if (pg && g_fx_ss_hooked) {                                     /* d5fx's detour reports the starts */
        volatile LONG *w = (volatile LONG *)(pg + 0x7f0);
        w[0] = -1;
        w[1] = 0;
        g_rec_watch = g_fx_rec_watch = w;
        g_rec_hit = g_fx_rec_hit = w + 1;
        g_rec_ready = 1;
        return 1;
    }
    if (!pg || memcmp(site, START_SCRIPT_ORIG, 5)) return 0;
    /* the page's other users: 0x00 / 0x80 AI manager, 0x100 team pick, 0x200 / 0x300 UI hooks, 0x400-0x540 colours */
    unsigned char *t = pg + 0x700;
    volatile LONG *watch = (volatile LONG *)(pg + 0x7f0), *hit = watch + 1;
    *watch = -1;
    *hit = 0;
    int n = 0;
    t[n++] = 0x3b; t[n++] = 0x15;                                   /* cmp edx, [rip + watch] */
    *(int *)(t + n) = (int)((unsigned char *)watch - (t + n + 4)); n += 4;
    t[n++] = 0x75; t[n++] = 10;                                     /* jne past the store */
    t[n++] = 0xc7; t[n++] = 0x05;                                   /* mov dword [rip + hit], 1 */
    *(int *)(t + n) = (int)((unsigned char *)hit - (t + n + 8)); n += 4;
    *(int *)(t + n) = 1; n += 4;
    memcpy(t + n, START_SCRIPT_ORIG, 5); n += 5;                    /* the instruction the jump replaced */
    t[n++] = 0xe9;
    *(int *)(t + n) = (int)((site + 5) - (t + n + 4)); n += 4;
    g_rec_watch = watch;
    g_rec_hit = hit;
    unsigned char j[5] = {0xe9};
    *(int *)(j + 1) = (int)(t - (site + 5));
    if (!write_code(VA_START_SCRIPT, j, 5)) return 0;
    g_rec_ready = 1;
    return 1;
}

static void rec_finish(void) {
    if (!g_rec_on && !g_rec_armed) return;
    InterlockedExchange(&g_rec_armed, 0);
    if (g_rec_watch) *g_rec_watch = -1;
    if (g_rec_tel) { fclose(g_rec_tel); g_rec_tel = NULL; }
    if (g_rec_probe) { fclose(g_rec_probe); g_rec_probe = NULL; }
    if (InterlockedExchange(&g_rec_on, 0)) {
        char p[MAX_PATH + 16];
        snprintf(p, sizeof p, "%s\\done.txt", g_rec_dir);
        FILE *f = fopen(p, "w");
        if (f) { fprintf(f, "%ld %ld\n", (long)g_rec_count, (long)g_rec_last); fclose(f); }
        logf_("record: %ld frame(s) saved in %s", (long)g_rec_count, g_rec_dir);
    }
}

/* game thread: the watched event started -> frame 0; telemetry of every recorded frame */
static void rec_tick(void) {
    if (g_rec_on) {
        LONG tick = g_frame - g_rec_start;
        if (tick < g_rec_max) rec_telemetry(tick);
        if (tick >= g_probe_from && tick <= g_probe_to) rec_probe(tick);
    }
    if (g_rec_armed && g_rec_hit && *g_rec_hit) {
        *g_rec_hit = 0;
        InterlockedExchange(&g_rec_armed, 0);
        g_rec_start = g_frame;
        g_rec_last = -1;
        g_rec_count = 0;
        char p[MAX_PATH + 32];
        snprintf(p, sizeof p, "%s\\telemetry.bin", g_rec_dir);
        if (g_rec_tel) fclose(g_rec_tel);
        g_rec_tel = fopen(p, "wb");
        if (g_rec_probe) { fclose(g_rec_probe); g_rec_probe = NULL; }
        if (g_probe_from >= 0) {
            snprintf(p, sizeof p, "%s\\probe.bin", g_rec_dir);
            g_rec_probe = fopen(p, "wb");
        }
        InterlockedExchange(&g_rec_on, 1);
        logf_("record: event %ld started (game frame %ld)", g_rec_watch ? (long)*g_rec_watch : -1L, (long)g_frame);
    }
}

/* back buffer -> 24-bit BMP, `scale` times smaller (box filter) */
static int capture_bmp(IDXGISwapChain *sc, const char *path, int scale, int *ow, int *oh, int *ofmt) {
    ID3D11Device *dev = NULL;
    ID3D11DeviceContext *ctx = NULL;
    ID3D11Texture2D *bb = NULL, *res = NULL, *st = NULL;
    int ok = 0;
    if (scale < 1) scale = 1;
    if (FAILED(IDXGISwapChain_GetDevice(sc, &IID_ID3D11Device, (void **)&dev)) || !dev) goto out;
    ID3D11Device_GetImmediateContext(dev, &ctx);
    if (FAILED(IDXGISwapChain_GetBuffer(sc, 0, &IID_ID3D11Texture2D, (void **)&bb)) || !bb) goto out;
    D3D11_TEXTURE2D_DESC d;
    ID3D11Texture2D_GetDesc(bb, &d);
    ID3D11Texture2D *src = bb;
    if (d.SampleDesc.Count > 1) {
        D3D11_TEXTURE2D_DESC r = d;
        r.SampleDesc.Count = 1; r.SampleDesc.Quality = 0; r.BindFlags = 0; r.MiscFlags = 0;
        if (FAILED(ID3D11Device_CreateTexture2D(dev, &r, NULL, &res))) goto out;
        ID3D11DeviceContext_ResolveSubresource(ctx, (ID3D11Resource *)res, 0, (ID3D11Resource *)bb, 0, d.Format);
        src = res;
    }
    D3D11_TEXTURE2D_DESC s = d;
    s.SampleDesc.Count = 1; s.SampleDesc.Quality = 0; s.Usage = D3D11_USAGE_STAGING; s.BindFlags = 0;
    s.CPUAccessFlags = D3D11_CPU_ACCESS_READ; s.MiscFlags = 0; s.MipLevels = 1; s.ArraySize = 1;
    if (FAILED(ID3D11Device_CreateTexture2D(dev, &s, NULL, &st))) goto out;
    ID3D11DeviceContext_CopyResource(ctx, (ID3D11Resource *)st, (ID3D11Resource *)src);
    D3D11_MAPPED_SUBRESOURCE m;
    if (FAILED(ID3D11DeviceContext_Map(ctx, (ID3D11Resource *)st, 0, D3D11_MAP_READ, 0, &m))) goto out;
    {
        int fmt = (int)d.Format;
        int bgr = fmt == DXGI_FORMAT_B8G8R8A8_UNORM || fmt == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                  fmt == DXGI_FORMAT_B8G8R8X8_UNORM || fmt == DXGI_FORMAT_B8G8R8X8_UNORM_SRGB;
        int rgb10 = fmt == DXGI_FORMAT_R10G10B10A2_UNORM;
        int w = (int)d.Width / scale, h = (int)d.Height / scale;
        int row = (w * 3 + 3) & ~3;
        FILE *f = fopen(path, "wb");
        if (f && w > 0 && h > 0) {
            unsigned char hdr[54] = {'B', 'M'};
            *(DWORD *)(hdr + 2) = 54 + (DWORD)row * h;
            *(DWORD *)(hdr + 10) = 54;
            *(DWORD *)(hdr + 14) = 40;
            *(LONG *)(hdr + 18) = w;
            *(LONG *)(hdr + 22) = h;
            *(WORD *)(hdr + 26) = 1;
            *(WORD *)(hdr + 28) = 24;
            *(DWORD *)(hdr + 34) = (DWORD)row * h;
            fwrite(hdr, 1, 54, f);
            unsigned char *line = (unsigned char *)calloc(1, row);
            int n = scale * scale;
            for (int y = h - 1; y >= 0 && line; y--) {
                for (int x = 0; x < w; x++) {
                    unsigned r = 0, g = 0, b = 0;
                    for (int yy = 0; yy < scale; yy++) {
                        const unsigned char *p = (const unsigned char *)m.pData + (size_t)(y * scale + yy) * m.RowPitch
                                                 + (size_t)x * scale * 4;
                        for (int xx = 0; xx < scale; xx++, p += 4) {
                            if (rgb10) {
                                DWORD v = *(const DWORD *)p;
                                r += (v & 0x3ff) >> 2; g += ((v >> 10) & 0x3ff) >> 2; b += ((v >> 20) & 0x3ff) >> 2;
                            } else if (bgr) { b += p[0]; g += p[1]; r += p[2]; }
                            else { r += p[0]; g += p[1]; b += p[2]; }
                        }
                    }
                    line[x * 3] = (unsigned char)(b / n); line[x * 3 + 1] = (unsigned char)(g / n);
                    line[x * 3 + 2] = (unsigned char)(r / n);
                }
                fwrite(line, 1, row, f);
            }
            free(line);
            ok = 1;
            if (ow) *ow = w;
            if (oh) *oh = h;
            if (ofmt) *ofmt = fmt;
        }
        if (f) fclose(f);
    }
    ID3D11DeviceContext_Unmap(ctx, (ID3D11Resource *)st, 0);
out:
    if (st) ID3D11Texture2D_Release(st);
    if (res) ID3D11Texture2D_Release(res);
    if (bb) ID3D11Texture2D_Release(bb);
    if (ctx) ID3D11DeviceContext_Release(ctx);
    if (dev) ID3D11Device_Release(dev);
    return ok;
}

/* Present thread: the frames of a recording */
static void rec_capture(IDXGISwapChain *sc) {
    if (!g_rec_on) return;
    LONG tick = g_frame - g_rec_start;
    if (tick >= g_rec_max) { rec_finish(); return; }
    if (tick == g_rec_last || tick % (g_rec_every > 0 ? g_rec_every : 1)) return;
    g_rec_last = tick;
    char p[MAX_PATH + 16];
    snprintf(p, sizeof p, "%s\\f%05ld.bmp", g_rec_dir, (long)tick);
    if (capture_bmp(sc, p, (int)g_rec_scale, NULL, NULL, NULL)) InterlockedIncrement(&g_rec_count);
}

/* ------------------------------------------------------------------ screenshot (Present thread) */
static volatile LONG g_shot_req;
static char g_shot_path[MAX_PATH];
static char g_shot_result[256];
static HANDLE g_shot_done;

static void ctl_capture(IDXGISwapChain *sc) {
    rec_capture(sc);
    if (!g_shot_req) return;
    int w = 0, h = 0, fmt = 0;
    if (capture_bmp(sc, g_shot_path, 1, &w, &h, &fmt))
        snprintf(g_shot_result, sizeof g_shot_result, "{\"ok\":1,\"w\":%d,\"h\":%d,\"format\":%d}", w, h, fmt);
    else
        snprintf(g_shot_result, sizeof g_shot_result, "{\"error\":\"capture failed\"}");
    InterlockedExchange(&g_shot_req, 0);
    SetEvent(g_shot_done);
}

/* ------------------------------------------------------------------ value scanner (pipe thread) */
typedef struct { unsigned char *a; unsigned long long v; } SCANHIT;
static SCANHIT *g_scan;
static size_t g_nscan, g_capscan;
static int g_scan_size;          /* 1 2 4 8, or 'f' (float) */

static int scan_region_ok(const MEMORY_BASIC_INFORMATION *m) {
    if (m->State != MEM_COMMIT) return 0;
    if (m->Protect & (PAGE_GUARD | PAGE_NOACCESS)) return 0;
    DWORD p = m->Protect & 0xff;
    return p == PAGE_READWRITE || p == PAGE_EXECUTE_READWRITE || p == PAGE_WRITECOPY;
}
static unsigned long long scan_get(const unsigned char *a) {
    switch (g_scan_size) {
    case 1: return *a;
    case 2: return *(const unsigned short *)a;
    case 8: return *(const unsigned long long *)a;
    default: return *(const unsigned int *)a;
    }
}
static int scan_cmp(int size, unsigned long long v, unsigned long long want) {
    if (size == 'f') {
        float a, b;
        unsigned int x = (unsigned int)v, y = (unsigned int)want;
        memcpy(&a, &x, 4); memcpy(&b, &y, 4);
        return a < b - 0.01f ? -1 : a > b + 0.01f ? 1 : 0;
    }
    return v < want ? -1 : v > want ? 1 : 0;
}
static unsigned long long scan_parse(const char *t) {
    if (g_scan_size == 'f') { float f = (float)atof(t); unsigned int x; memcpy(&x, &f, 4); return x; }
    return strtoull(t, NULL, 0);
}
static void scan_add(unsigned char *a, unsigned long long v) {
    if (g_nscan == g_capscan) {
        size_t c = g_capscan ? g_capscan * 2 : 65536;
        if (c > 20000000) return;
        SCANHIT *q = (SCANHIT *)realloc(g_scan, c * sizeof *q);
        if (!q) return;
        g_scan = q; g_capscan = c;
    }
    g_scan[g_nscan].a = a; g_scan[g_nscan].v = v; g_nscan++;
}
static void scan_new(SB *out, int size, const char *val) {
    g_scan_size = size;
    g_nscan = 0;
    int step = size == 'f' ? 4 : size;
    unsigned long long want = scan_parse(val);
    unsigned char *p = (unsigned char *)0x10000;
    MEMORY_BASIC_INFORMATION m;
    while ((unsigned long long)p < 0x7ffffffeffffULL && VirtualQuery(p, &m, sizeof m)) {
        unsigned char *next = (unsigned char *)m.BaseAddress + m.RegionSize;
        if (scan_region_ok(&m)) {
            unsigned char *a = (unsigned char *)m.BaseAddress, *e = next - step;
            for (; a <= e; a += step) {
                unsigned long long v = scan_get(a);
                if (!scan_cmp(size, v, want)) scan_add(a, v);
            }
        }
        p = next;
    }
    sbf(out, "{\"ok\":1,\"hits\":%zu}", g_nscan);
}
static void scan_next(SB *out, const char *op, const char *val) {
    unsigned long long want = val && *val ? scan_parse(val) : 0;
    size_t k = 0;
    unsigned char *reg_lo = NULL, *reg_hi = NULL;
    int reg_ok = 0;
    for (size_t i = 0; i < g_nscan; i++) {
        unsigned char *a = g_scan[i].a;
        if (a < reg_lo || a >= reg_hi) {
            MEMORY_BASIC_INFORMATION m;
            if (!VirtualQuery(a, &m, sizeof m)) continue;
            reg_lo = (unsigned char *)m.BaseAddress; reg_hi = reg_lo + m.RegionSize; reg_ok = scan_region_ok(&m);
        }
        if (!reg_ok) continue;
        unsigned long long v = scan_get(a), o = g_scan[i].v;
        int c = scan_cmp(g_scan_size, v, want), co = scan_cmp(g_scan_size, v, o), keep = 0;
        if (!strcmp(op, "eq")) keep = c == 0;
        else if (!strcmp(op, "ne")) keep = c != 0;
        else if (!strcmp(op, "gt")) keep = c > 0;
        else if (!strcmp(op, "lt")) keep = c < 0;
        else if (!strcmp(op, "changed")) keep = co != 0;
        else if (!strcmp(op, "unchanged")) keep = co == 0;
        else if (!strcmp(op, "inc")) keep = co > 0;
        else if (!strcmp(op, "dec")) keep = co < 0;
        if (keep) { g_scan[k].a = a; g_scan[k].v = v; k++; }
    }
    g_nscan = k;
    sbf(out, "{\"ok\":1,\"hits\":%zu}", g_nscan);
}
static void scan_list(SB *out, int n) {
    sbf(out, "{\"hits\":%zu,\"list\":[", g_nscan);
    for (size_t i = 0; i < g_nscan && (int)i < n; i++) {
        unsigned long long a = (unsigned long long)g_scan[i].a;
        sbf(out, "%s[\"0x%llx\",%llu]", i ? "," : "", to_static(a), (unsigned long long)scan_get(g_scan[i].a));
    }
    sb_put(out, "]}", 2);
}

/* ------------------------------------------------------------------ state */
static void ctl_state(SB *o) {
    int mode = *(volatile int *)G(VA_SCENE_MODE), cx, cz, bx, bz;
    const unsigned char *c = (const unsigned char *)G(VA_CURSOR);
    cursor_panel(&cx, &cz);
    base_panel(&bx, &bz);
    float gx = *(const float *)G(VA_GATE_X), gz = *(const float *)G(VA_GATE_X + 4);
    sbf(o, "{\"frame\":%ld,\"presents\":%ld,\"sync\":%ld,\"ms\":%lu,\"ff\":{\"always\":%d,\"level\":%d,\"mult\":%d,"
        "\"harness\":%d},\"active\":%ld,\"status\":", (long)g_frame, (long)g_presents, (long)g_present_sync,
        (unsigned long)GetTickCount(), rd8(VA_FF_ALWAYS), rd8(VA_FF_LEVEL), *(const int *)G(VA_FF_MULT), g_skitff,
        (long)g_active);
    sb_str(o, g_status ? g_status : "");
    sbf(o, ",\"mode\":%d,\"iw\":%d,\"floormap\":%d,\"battle\":%d,\"flags\":%d,\"floorno\":%d,", mode,
        rd8(VA_IW_SESSION), rd8(VA_IW_FLOOR_MAP), rd8(VA_BATTLE_MAP), rd8(VA_IW_FLAGS), rd8(VA_IW_FLOOR_NO));
    sbf(o, "\"cursor\":[%.2f,%.2f,%.2f],\"cpanel\":[%d,%d],\"base\":[%d,%d],\"gate\":[%d,%d],",
        *(const float *)(c + 8), *(const float *)(c + 12), *(const float *)(c + 16), cx, cz, bx, bz,
        (int)(gx / 12.0f), (int)(gz / 12.0f));
    sbf(o, "\"dep\":%d,\"nav\":%d,\"astate\":%d,\"focus\":%d,\"fake_focus\":%ld,\"input_guard\":%d,"
        "\"guard_kb\":%ld,\"guard_pad\":%ld,\"grid_base\":%d,\"units\":[", g_dep_on, g_nav, g_astate, game_focused(),
        (long)g_fake_focus, g_input_guard, (long)g_guard_kb, (long)g_guard_pad, grid_at(bx, bz));
    UNIT u[64];
    int n = read_units(u, 64);
    for (int i = 0; i < n; i++) {
        sbf(o, "%s{\"slot\":%d,\"name\":", i ? "," : "", u[i].slot);
        sb_str(o, u[i].name);
        sbf(o, ",\"team\":%d,\"lv\":%lld,\"hp\":%lld,\"hpmax\":%lld,\"sp\":%lld,\"spmax\":%lld,\"atk\":%lld,\"def\":%lld,"
               "\"int\":%lld,\"res\":%lld,\"hit\":%lld,\"spd\":%lld,\"p\":[%d,%d],\"h\":%.1f,\"ai\":%d,\"f860\":%d,"
               "\"cls\":%d,\"actor\":\"0x%llx\",\"unit\":\"0x%llx\"}",
            *(const int *)(u[i].actor + 0x1258), u[i].level, u[i].hp, u[i].hpmax, u[i].sp, u[i].spmax, u[i].atk,
            u[i].def, u[i].intl, u[i].res, u[i].hit, u[i].spd, u[i].px, u[i].pz, u[i].h, u[i].ai,
            *(const int *)(u[i].actor + 0x860), u[i].cls, to_static((DWORD64)u[i].actor),
            to_static((DWORD64)u[i].unit));
    }
    sb_put(o, "]}", 2);
}

/* ------------------------------------------------------------------ facility / giveup (FACILITY1)
 * Two harness commands that replace keypress walks with the game's own routines:
 *   facility [list | NAME | INDEX]  open one of the 18 Pocket Netherworld facilities directly.  A port of Cryswar's
 *       Overlord "Facility Hotkeys" (d5_facility_hotkeys_integrated.cpp, The Unlicense -- thanks, Cryswar): the same
 *       table, the same native unlock / first-visit flag gates, the same "Pocket Netherworld fully idle" test, the
 *       same four byte signatures, and the same three routes (script_cmd_menu_open 0x18AE20 for the shops inside
 *       the base, the task manager's pending task for the top-level facilities, the guide/shop selector bytes,
 *       restored once the game has read them).  It runs on the game thread at the start of a frame (his ran on a
 *       worker thread).
 *   giveup  leave the battle for the base and lose its progress: what Give Up -> "Return to the Pocket Netherworld"
 *       -> Yes does (system_ctl s4 0x620DF0: restore mode 2, world-map globals cleared, script 2013) plus the
 *       battle-manager request {9001, 1} the item-capacity exit (S37 0x4A1F1F) queues, which parks the battle in
 *       its dispatcher while script 2013 fades out.  Cryswar's overlord/09_giveup.c reroutes the same s4 path; this
 *       takes it without the menu.
 * Addresses are RVAs of the Steam build (PE timestamp 0x5C4E7571, the kit's pinned exe 49a7530b...), written
 * relative to the image so exemap does not translate them as launch-build VAs.  Each command checks the build and
 * its byte signatures at run time and refuses with the reason on anything else. */
#define FAC_TIMESTAMP 0x5C4E7571u
#define FAC_TASK_MANAGER 0x00BDFD08u      /* -> {i32 pending, i32 selected, ..., u8 +0xA18, u8 +0xA19} */
#define FAC_POCKET 0x07B58EC0u            /* -> the base (state 13) object */
#define FAC_FLAGS 0x04FCCB0Eu             /* the game's event flag bitmap */
#define FAC_MENU_OPEN 0x0018AE20u         /* script_cmd_menu_open(?, ?, short id) */
#define FAC_MENU_FORWARD 0x06A07FA8u      /* byte: menu_open forwards to the state-32 object */
#define FAC_GUIDE_BYTE 0x04FCCFF0u
#define FAC_SHOP_MODE 0x04FCCC2Du
#define FAC_SHOP_OBJECT 0x07B59848u
#define GU_BATTLE 0x07B58E68u             /* -> the state-5 battle object (vtable FAC rva 0x98BF00) */
#define GU_BATTLE_VT 0x0098BF00u
#define GU_BM 0x07B58E70u                 /* -> the battle manager (request queue at +0, count +0x80, pending +0xB5) */
#define GU_BM_ALIVE 0x07A65474u
#define GU_SCRIPTS 0x00A67CF0u            /* -> the script manager */
#define GU_SCRIPT_CREATE 0x00190140u      /* script_context_create */
#define GU_BITS_A 0x04FCD261u
#define GU_WORLD_MODE 0x07B58E88u
#define GU_WORLD_RECORD 0x07A678A8u
#define GU_WORLD_INDEX 0x07B58E8Cu
#define RVA(r) (g_base + (r))
#ifndef FAC_CALL_MENU_OPEN    /* test seams: tests/test_facility1.py builds this block on the host with stand-ins */
#define FAC_CALL_MENU_OPEN(id) ((long long (*)(void *, void *, short))RVA(FAC_MENU_OPEN))(NULL, NULL, (short)(id))
#define GU_CALL_SCRIPT(id, out) ((int (*)(long long, int, long long, long long, long long, int, long long, \
    long long *))RVA(GU_SCRIPT_CREATE))(*(long long *)RVA(GU_SCRIPTS), (id), 0, 0, 0, 0, 0, (out))
#endif

typedef struct { unsigned rva; unsigned char n; unsigned char b[124]; } FACSIG;
static const FACSIG FAC_SIGS[] = {      /* Cryswar's four */
    {0x00222131u, 12, {0x48,0x8B,0x1D,0xD0,0xDB,0x9B,0x00,0x8B,0x13,0x83,0xFA,0xFF}},
    {0x0018AE20u, 11, {0x48,0x83,0xEC,0x28,0x80,0x3D,0x7D,0xD1,0x87,0x06,0x00}},
    {0x00646E27u, 15, {0x44,0x84,0x25,0xC2,0x61,0x98,0x04,0x41,0x0F,0xB6,0xC7,0x41,0x0F,0x45,0xC4}},
    {0x006ABDE0u, 15, {0x48,0x83,0xEC,0x28,0x0F,0xB6,0x05,0x42,0x0E,0x92,0x04,0xA8,0x40,0x74,0x04}},
};
static const FACSIG GU_SIGS[] = {       /* the code giveup mirrors: s4 "Yes", the S37 queue, the battle exit */
    {0x00620E28u, 124, {0x48,0x8B,0x05,0x41,0x80,0x53,0x07,0x74,0x11,0x48,0x85,0xC0,0x74,0x1B,0xC7,0x80,0x10,0x06,
        0x0C,0x00,0x03,0x00,0x00,0x00,0xEB,0x0F,0x48,0x85,0xC0,0x74,0x0A,0xC7,0x80,0x10,0x06,0x0C,0x00,0x02,0x00,0x00,
        0x00,0x48,0x8B,0x0D,0x98,0x6E,0x44,0x00,0x48,0x8D,0x44,0x24,0x58,0x80,0x25,0xFD,0xC3,0x9A,0x04,0xFB,0x33,0xFF,
        0x80,0x25,0x83,0xC1,0x9A,0x04,0xFB,0x45,0x33,0xC9,0x48,0x89,0x44,0x24,0x38,0x45,0x33,0xC0,0x48,0x89,0x7C,0x24,
        0x30,0xBA,0xDD,0x07,0x00,0x00,0x89,0x7C,0x24,0x28,0x48,0x89,0x7C,0x24,0x20,0x89,0x3D,0xF7,0x7F,0x53,0x07,0x48,
        0x89,0x3D,0x10,0x6A,0x44,0x07,0x66,0x89,0x3D,0xED,0x7F,0x53,0x07,0xE8,0x9C,0xF2,0xB6,0xFF}},
    {0x004A1F1Fu, 98, {0x38,0x1D,0x4F,0x35,0x5C,0x07,0x74,0x5A,0x48,0x8B,0x0D,0x42,0x6F,0x6B,0x07,0x48,0x85,0xC9,
        0x74,0x34,0x48,0x63,0x81,0x80,0x00,0x00,0x00,0xC7,0x04,0xC1,0x29,0x23,0x00,0x00,0x48,0x63,0x81,0x80,0x00,0x00,
        0x00,0xC7,0x44,0xC1,0x04,0x01,0x00,0x00,0x00,0xFF,0x81,0x80,0x00,0x00,0x00,0xC6,0x81,0xB5,0x00,0x00,0x00,0x01,
        0x8B,0x01,0x89,0x81,0x88,0x00,0x00,0x00,0xEB,0x03,0x48,0x8B,0xCB,0x88,0x99,0x3E,0x0D,0x00,0x00,0xC7,0x81,0x8C,
        0x00,0x00,0x00,0xFF,0xFF,0xFF,0xFF,0x48,0x89,0x99,0x90,0x00,0x00,0x00}},
    {0x004AF036u, 33, {0x48,0x8B,0x1D,0x2B,0x9E,0x6A,0x07,0x48,0x85,0xDB,0x0F,0x84,0xC2,0x01,0x00,0x00,0x48,0x8B,0x03,
        0x48,0x8D,0x0D,0xB0,0xCE,0x4D,0x00,0x48,0x8B,0x50,0x18,0x48,0x3B,0xC1}},
};

enum { FAC_NESTED, FAC_SHOP, FAC_TOP, FAC_GUIDE };
static const char *const FAC_KIND[] = {"nested", "shop", "top", "guide"};
typedef struct { const char *name; int kind, route, unlock, first_talk, selector; unsigned vt; } FACDEF;
static const FACDEF FACS[] = {          /* Cryswar's table, in his order (INDEX = position) */
    {"equipment_shop", FAC_SHOP, 50, 14020, 9621, 0x10, 0x0098F168u},
    {"item_shop", FAC_SHOP, 50, 14020, 9626, 0x40, 0x0098ED08u},
    {"hospital", FAC_NESTED, 60, 14021, 9631, 0, 0},
    {"skill_shop", FAC_NESTED, 140, 14010, 9685, 0, 0},
    {"quest_shop", FAC_NESTED, 145, 14009, 9680, 0, 0},
    {"interrogation", FAC_NESTED, 135, 14003, 9690, 0, 0},
    {"alchemist", FAC_NESTED, 130, 14006, 9715, 0, 0},
    {"curry_shop", FAC_NESTED, 310, 14015, 9725, 0, 0},
    {"cheat_shop", FAC_NESTED, 190, 14005, 9651, 0, 0},
    {"strategy_assembly", FAC_TOP, 7, 14008, 9635, 0, 0},
    {"item_world", FAC_TOP, 14, 14000, 9610, 0, 0},
    {"squad_shop", FAC_TOP, 37, 14001, 9670, 0, 0},
    {"netherworld_research", FAC_TOP, 33, 14014, 9675, 0, 0},
    {"innocent_shop", FAC_TOP, 35, 14007, 9705, 0, 0},
    {"recruiter", FAC_TOP, 36, 14016, 9695, 0, 0},
    {"chara_world", FAC_TOP, 31, 14011, 9665, 0, 0},
    {"dimension_guide", FAC_GUIDE, 9, 0, 0, 0, 0},
    {"carnage_dimension_guide", FAC_GUIDE, 9, 14018, 9710, 1, 0},
};
#define FAC_N ((int)(sizeof FACS / sizeof FACS[0]))

/* a pending selector-byte restore (shop / guide routes): the byte goes back once the game has read it */
static struct { int on, index; LONG frame; unsigned rva; unsigned char saved; } g_fac;

/* NULL = this exe is the build and every signature matches; else why not (static text) */
static const char *fac_build_check(const FACSIG *sigs, int n) {
    static char why[96];
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_base + ((IMAGE_DOS_HEADER *)g_base)->e_lfanew);
    if (nt->FileHeader.TimeDateStamp != FAC_TIMESTAMP) return "unsupported game build (PE timestamp)";
    for (int i = 0; i < n; i++)
        if (!readable(RVA(sigs[i].rva), sigs[i].n) || memcmp(RVA(sigs[i].rva), sigs[i].b, sigs[i].n)) {
            snprintf(why, sizeof why, "signature mismatch at rva 0x%X", sigs[i].rva);
            return why;
        }
    return NULL;
}

static int fac_flag(int id) {
    return !id || (*(volatile unsigned char *)RVA(FAC_FLAGS + (id >> 3)) >> (id & 7) & 1);
}

static void fac_restore(void) {
    if (!g_fac.on) return;
    *(volatile unsigned char *)RVA(g_fac.rva) = g_fac.saved;
    g_fac.on = 0;
}

/* every frame: put a shop/guide selector byte back once the game has taken it (Cryswar's poll_request) */
static void fac_poll(void) {
    if (!g_fac.on) return;
    const FACDEF *f = &FACS[g_fac.index];
    LONG age = g_frame - g_fac.frame;
    if (f->kind == FAC_GUIDE) {
        unsigned char *m = *(unsigned char **)RVA(FAC_TASK_MANAGER);
        if (age > 120 || !m || *(int *)m != f->route) fac_restore();    /* pending consumed (or 2 s) */
    } else {
        unsigned char *s = *(unsigned char **)RVA(FAC_SHOP_OBJECT);
        if (age > 180 || (s && *(unsigned char **)s == RVA(f->vt))) fac_restore();   /* its shop exists (or 3 s) */
    }
}

static void ctl_facility(SB *o, int argc, char **argv) {
    if (argc < 2 || !strcmp(argv[1], "list")) {
        sbf(o, "{\"ok\":1,\"facilities\":[");
        for (int i = 0; i < FAC_N; i++)
            sbf(o, "%s{\"index\":%d,\"name\":\"%s\",\"kind\":\"%s\",\"route\":%d,\"open\":%d}", i ? "," : "", i,
                FACS[i].name, FAC_KIND[FACS[i].kind], FACS[i].route,
                fac_flag(FACS[i].unlock) && fac_flag(FACS[i].first_talk));
        sbf(o, "]}");
        return;
    }
    int i = -1;
    char *end;
    long k = strtol(argv[1], &end, 10);
    if (*argv[1] && !*end) i = (k >= 0 && k < FAC_N) ? (int)k : -1;
    else for (int j = 0; j < FAC_N; j++) if (!_stricmp(argv[1], FACS[j].name)) i = j;
    if (i < 0) { sbf(o, "{\"error\":\"unknown facility\",\"reason\":\"no facility %s (facility list)\"}", argv[1]); return; }
    const FACDEF *f = &FACS[i];
    const char *why = fac_build_check(FAC_SIGS, 4);
    unsigned char *m = why ? NULL : *(unsigned char **)RVA(FAC_TASK_MANAGER);
    unsigned char *p = why ? NULL : *(unsigned char **)RVA(FAC_POCKET);
    if (why) ;
    else if (g_fac.on) why = "another facility request is still in flight";
    else if (!fac_flag(f->unlock)) why = "native unlock flag not set";
    else if (!fac_flag(f->first_talk)) why = "native first-visit flag not set";
    else if (!m || !p) why = "not in the Pocket Netherworld (no task manager / base object)";
    else if (*(int *)m != -1 || *(int *)(m + 4) != 13 || m[0xA18] || m[0xA19]) why = "Pocket Netherworld not idle (task manager)";
    /* base +0xB0 is NOT tested (Cryswar tests it == -1): it is the talk TARGET the base re-picks every frame
     * (base_interact_pick_target 0x6A8AB0: nearest talkable actor index, -1 = none), so it is >= 0 whenever the
     * leader stands next to an NPC -- right after a load, and exactly where the NPC walk opens a facility.  +0xB8
     * is the talk actually running (base_s0_update 0x6A9D10: base_interact_start_talk's result, reset to -1 each
     * frame no talk runs), so that one stays a busy state.  FACILITY1 run 3: [+0x14,+0x30,+0xB0,+0xB8] = [0,0,0,-1]. */
    else if (*(int *)(p + 0x14) || *(int *)(p + 0x30) || *(int *)(p + 0xB8) != -1)
        why = "Pocket Netherworld not idle (a facility is open or transitioning)";
    else if ((f->kind == FAC_NESTED || f->kind == FAC_SHOP) && *(volatile unsigned char *)RVA(FAC_MENU_FORWARD))
        why = "menus are routed to the state-32 object";
    else if (f->kind == FAC_GUIDE && (*(volatile unsigned char *)RVA(FAC_GUIDE_BYTE) & 1))
        why = "guide context already active";
    if (why) {
        sbf(o, "{\"error\":\"refused\",\"facility\":\"%s\",\"reason\":", f->name);
        sb_str(o, why);
        if (m && p)                                    /* what the idle test read (FACILITY1 run 2: diagnose) */
            sbf(o, ",\"manager\":[%d,%d,%d,%d],\"base\":[%d,%d,%d,%d]", *(int *)m, *(int *)(m + 4), m[0xA18],
                m[0xA19], *(int *)(p + 0x14), *(int *)(p + 0x30), *(int *)(p + 0xB0), *(int *)(p + 0xB8));
        sbf(o, "}");
        return;
    }
    if (f->kind == FAC_GUIDE || f->kind == FAC_SHOP) {
        volatile unsigned char *b = RVA(f->kind == FAC_GUIDE ? FAC_GUIDE_BYTE : FAC_SHOP_MODE);
        g_fac.on = 1; g_fac.index = i; g_fac.frame = g_frame; g_fac.saved = *b;
        g_fac.rva = f->kind == FAC_GUIDE ? FAC_GUIDE_BYTE : FAC_SHOP_MODE;
        *b = f->kind == FAC_GUIDE ? (unsigned char)((*b & 0xFE) | (f->selector & 1))
                                  : (unsigned char)((*b & ~0x50) | f->selector);
    }
    if (f->kind == FAC_NESTED || f->kind == FAC_SHOP) {
        FAC_CALL_MENU_OPEN(f->route);
    } else {
        *(volatile int *)m = f->route;                  /* the task manager's pending task */
    }
    logf_("facility %s (route %d, %s)", f->name, f->route, FAC_KIND[f->kind]);
    sbf(o, "{\"ok\":1,\"facility\":\"%s\",\"index\":%d,\"route\":%d,\"kind\":\"%s\"}", f->name, i, f->route,
        FAC_KIND[f->kind]);
}

static void ctl_giveup(SB *o) {
    const char *why = fac_build_check(GU_SIGS, 3);
    unsigned char *battle = why ? NULL : *(unsigned char **)RVA(GU_BATTLE);
    unsigned char *bm = why ? NULL : *(unsigned char **)RVA(GU_BM);
    int cur = battle ? *(int *)(battle + 0x14) : -1;
    if (why) ;
    else if (!battle || *(unsigned char **)battle != RVA(GU_BATTLE_VT)) why = "not in a battle";
    else if (!bm || !*(volatile unsigned char *)RVA(GU_BM_ALIVE)) why = "no battle manager";
    else if (cur == 42) why = "the battle is in its dispatcher (already leaving?)";
    else if (cur == 28) why = "the turn runner is active (enemy phase or an action playing)";
    else if (bm[0xB5]) why = "a battle request is already pending";
    else if (*(int *)(bm + 0x80) < 0 || *(int *)(bm + 0x80) > 15) why = "the battle request queue is full";
    if (why) {
        sbf(o, "{\"error\":\"refused\",\"reason\":");
        sb_str(o, why);
        sbf(o, ",\"substate\":%d}", cur);
        return;
    }
    /* system_ctl s4 "Yes" (0x620E21..0x620E9F): lose progress, clear the world-map resume, script 2013 */
    *(int *)(bm + 0xC0610) = 2;
    *(volatile unsigned char *)RVA(GU_BITS_A) &= 0xFB;
    *(volatile unsigned char *)RVA(FAC_GUIDE_BYTE) &= 0xFB;
    *(volatile int *)RVA(GU_WORLD_MODE) = 0;
    *(volatile long long *)RVA(GU_WORLD_RECORD) = 0;
    *(volatile short *)RVA(GU_WORLD_INDEX) = 0;
    long long ctx = 0;
    int r = GU_CALL_SCRIPT(2013, &ctx);
    /* S37's exit (0x4A1F33..0x4A1F7A): request {9001, 1} on the battle manager -> the dispatcher S42 */
    int n = *(int *)(bm + 0x80);
    ((int *)bm)[n * 2] = 9001;
    ((int *)bm)[n * 2 + 1] = 1;
    *(int *)(bm + 0x80) = n + 1;
    bm[0xB5] = 1;
    *(int *)(bm + 0x88) = *(int *)bm;
    bm[0xD3E] = 0;
    *(int *)(bm + 0x8C) = -1;
    *(long long *)(bm + 0x90) = 0;
    logf_("giveup: battle sub-state %d -> script 2013 (%d), request 9001", cur, r);
    sbf(o, "{\"ok\":1,\"substate\":%d,\"script\":%d}", cur, r);
}

/* ------------------------------------------------------------------ command dispatch */
static char g_cmd[4096];                 /* handed from the pipe thread to the game thread */
static SB g_reply;
static volatile LONG g_cmd_pending;      /* 1 = waiting for the game thread */
static HANDLE g_cmd_done;
static int g_cmd_wait_keys, g_cmd_wait_frames;

static void ctl_finish(void) {
    g_cmd_wait_keys = 0;
    g_cmd_wait_frames = 0;
    InterlockedExchange(&g_cmd_pending, 0);
    SetEvent(g_cmd_done);
}

static void fx_cmd(SB *o, int argc, char **argv);   /* d5fx.inc.c */
static void ctl_anmtrace(SB *o, int argc, char **argv), ctl_actorprobe(SB *o, int argc, char **argv);
static void at_tick(void), at_off(void);             /* d5anmtrace.inc.c */
static void ctl_voicetrace(SB *o, int argc, char **argv), vt_off(void);   /* d5anmtrace.inc.c (VOICE2) */
static void ctl_watch(SB *o, int argc, char **argv), ww_off(void);        /* d5wwatch.inc.c (WRITEWATCH1) */

/* runs on the game thread (d5_frame) */
static void ctl_tick(void) {
    InterlockedIncrement(&g_frame);
    rec_tick();
    if (g_skitff == -2) g_skitff = g_battle_speed ? g_battle_speed : (g_remote ? 2 : -1);
    if (!(g_frame % 30) && (g_remote || g_skitff != -1)) skitff_apply();
    if (!g_remote) return;
    fac_poll();
    at_tick();                                 /* actorprobe */
    if (!g_cmd_pending) return;
    if (g_cmd_wait_keys) { if (!keys_busy()) ctl_finish(); return; }
    if (g_cmd_wait_frames) { if (--g_cmd_wait_frames <= 0) ctl_finish(); return; }
    if (g_cmd_pending != 1) return;
    InterlockedExchange(&g_cmd_pending, 2);
    char buf[4096], *argv[64];
    int argc = 0;
    strncpy(buf, g_cmd, sizeof buf - 1);
    buf[sizeof buf - 1] = 0;
    for (char *t = strtok(buf, " \t\r\n"); t && argc < 64; t = strtok(NULL, " \t\r\n")) argv[argc++] = t;
    SB *o = &g_reply;
    o->n = 0;
    if (o->p) o->p[0] = 0;
    if (!argc) { sbf(o, "{\"error\":\"empty\"}"); ctl_finish(); return; }
    const char *c = argv[0];
    if (!strcmp(c, "state")) {
        ctl_state(o);
    } else if (!strcmp(c, "keys")) {
        int bad = 0;
        for (int i = 1; i < argc; i++) {
            char nm[32];
            int hold = 3, gap = 10;
            strncpy(nm, argv[i], sizeof nm - 1);
            nm[sizeof nm - 1] = 0;
            char *p1 = strchr(nm, ':');
            if (p1) { *p1 = 0; hold = atoi(p1 + 1); char *p2 = strchr(p1 + 1, ':'); if (p2) gap = atoi(p2 + 1); }
            int d = dik_of(nm);
            if (d < 0) { bad = 1; sbf(o, "{\"error\":\"unknown key %s\"}", nm); break; }
            press((BYTE)d, hold, gap);
        }
        if (!bad) { sbf(o, "{\"ok\":1}"); g_cmd_wait_keys = 1; return; }
#if D5_AUTO
    } else if (!strcmp(c, "menu") && argc > 1) {   /* menu open | close | key U/D/L/R/A/B/C/N/X */
        if (!strcmp(argv[1], "open") && !g_menu_open) {
            menu_collect_units(); g_mfocus = M_UNITS; g_msel_unit = 0; g_mchanged = 0; g_mdirty = 1;
            InterlockedExchange(&g_menu_open, 1);
        } else if (!strcmp(argv[1], "close") && g_menu_open) {
            if (g_mchanged) menu_save();
            InterlockedExchange(&g_menu_open, 0);
        } else if (!strcmp(argv[1], "key") && argc > 2 && g_menu_open) {
            menu_input(argv[2][0]);
        }
        sbf(o, "{\"ok\":1,\"open\":%ld,\"focus\":%d,\"unit\":%d,\"rule\":%d,\"field\":%d,\"status\":", (long)g_menu_open,
            g_mfocus, g_msel_unit, g_msel_rule, g_msel_field);
        sb_str(o, g_mstatus);
        sb_put(o, "}", 1);
#endif
    } else if (!strcmp(c, "scripts") && argc > 1) {
        /* scripts PATH: a plain (decrypted) script.dat becomes the running game's script data (d5live.inc.c) */
        const char *p = g_cmd;
        while (*p == ' ' || *p == '\t') p++;
        while (*p && *p != ' ' && *p != '\t') p++;
        while (*p == ' ' || *p == '\t') p++;
        char path[MAX_PATH];
        snprintf(path, sizeof path, "%s", p);
        for (int k = (int)strlen(path) - 1; k >= 0 && (path[k] == '\r' || path[k] == '\n' || path[k] == ' '); k--)
            path[k] = 0;
        int k = load_script_data(path);
        if (k < 0) sbf(o, "{\"error\":\"load failed\"}");
        else sbf(o, "{\"ok\":1,\"scripts\":%d}", k);
    } else if (!strcmp(c, "saves_from")) {         /* saves_from [DIR]: read the saves from DIR (dev; no writes) */
        char path[MAX_PATH];
        snprintf(path, sizeof path, "%s", rest_after(g_cmd, 1));
        for (int k = (int)strlen(path) - 1; k >= 0 && (path[k] == '\r' || path[k] == '\n' || path[k] == ' '); k--)
            path[k] = 0;
        if (!path[0]) g_save_src[0] = 0;
        else MultiByteToWideChar(CP_UTF8, 0, path, -1, g_save_src, MAX_PATH);
        logf_("ctl: saves read from %ls", g_save_src[0] ? g_save_src : L"their own folder");
        sbf(o, "{\"ok\":1,\"on\":%d}", g_save_src[0] ? 1 : 0);
    } else if (!strcmp(c, "reload")) {             /* the loader swaps in a new d5core.dll */
        InterlockedExchange(&g_reload, 1);
        sbf(o, "{\"ok\":1,\"reloading\":1}");
    } else if (!strcmp(c, "sms")) {                /* the state machines that ran last frame */
        int n;
        const SMREC *l = sm_list(&n);
        sbf(o, "{\"hooked\":%d,\"n\":%d,\"list\":[", g_sm_hooked, n);
        for (int i = 0; i < n; i++) {
            sbf(o, "%s[\"0x%llx\",\"0x%llx\",%d,%d,%d,[%d,%d,%d,%d,%d,%d]]", i ? "," : "", l[i].vt,
                (unsigned long long)l[i].obj, l[i].state, l[i].phase, l[i].depth, l[i].stack[0], l[i].stack[1],
                l[i].stack[2], l[i].stack[3], l[i].stack[4], l[i].stack[5]);
        }
        sb_put(o, "]}", 2);
    } else if (!strcmp(c, "texts")) {              /* strings drawn last frame */
        int n;
        const TXREC *l = tx_list(&n);
        sbf(o, "{\"hooked\":%d,\"n\":%d,\"list\":[", g_tx_hooked, n);
        for (int i = 0; i < n; i++) {
            sbf(o, "%s[%d,%d,%d,\"0x%llx\",", i ? "," : "", l[i].x, l[i].y, l[i].a3, l[i].caller);
            sb_str(o, l[i].s);
            sbf(o, ",\"%08x\"]", l[i].color);
        }
        sb_put(o, "]}", 2);
    } else if (!strcmp(c, "fx")) {                 /* fx [stress N ROOM]: the on-demand effect models (d5fx.inc.c) */
        fx_cmd(o, argc, argv);
    } else if (!strcmp(c, "hold") && argc > 2) {   /* hold KEY 1 / hold KEY 0 */
        int d = dik_of(argv[1]);
        if (d < 0) sbf(o, "{\"error\":\"unknown key\"}");
        else if (d >= 256) sbf(o, "{\"error\":\"key out of range\"}");
        else { g_hold_dik[d] = (BYTE)(atoi(argv[2]) != 0); sbf(o, "{\"ok\":1}"); }
    } else if (!strcmp(c, "wait") && argc > 1) {
        g_cmd_wait_frames = atoi(argv[1]);
        if (g_cmd_wait_frames > 36000) g_cmd_wait_frames = 36000;   /* 10 minutes */
        sbf(o, "{\"ok\":1}");
        if (g_cmd_wait_frames > 0) return;
    } else if (!strcmp(c, "wr") && argc > 2) {
        unsigned char *a = ctl_addr(strtoull(argv[1], NULL, 16));
        size_t k = strlen(argv[2]) / 2;
        if (!readable(a, k)) sbf(o, "{\"error\":\"not readable\"}");
        else {
            DWORD old;
            VirtualProtect(a, k, PAGE_EXECUTE_READWRITE, &old);
            for (size_t i = 0; i < k; i++) { unsigned int b; sscanf(argv[2] + i * 2, "%2x", &b); a[i] = (unsigned char)b; }
            VirtualProtect(a, k, old, &old);
            sbf(o, "{\"ok\":1,\"n\":%zu}", k);
        }
    } else if (!strcmp(c, "call") && argc > 1) {    /* call VA [a1..a4]: run a game function on the game thread */
        typedef unsigned long long (*FN4)(unsigned long long, unsigned long long, unsigned long long, unsigned long long);
        unsigned long long a[4] = {0, 0, 0, 0};
        for (int i = 0; i < 4 && i + 2 < argc; i++) a[i] = strtoull(argv[i + 2], NULL, 0);
        FN4 f = (FN4)ctl_addr(strtoull(argv[1], NULL, 16));
        unsigned long long r = f(a[0], a[1], a[2], a[3]);
        sbf(o, "{\"ok\":1,\"rax\":\"0x%llx\"}", r);
    } else if (!strcmp(c, "facility")) {             /* facility [list | NAME | INDEX]: open it natively */
        ctl_facility(o, argc, argv);
    } else if (!strcmp(c, "giveup")) {               /* leave the battle for the base (progress lost) */
        ctl_giveup(o);
    } else if (!strcmp(c, "anmtrace")) {             /* anmtrace on|guard|off|status: animation hooks (ANMTRACE1) */
        ctl_anmtrace(o, argc, argv);
    } else if (!strcmp(c, "actorprobe")) {           /* actorprobe <slot> <frames> | off: per-frame actor reads */
        ctl_actorprobe(o, argc, argv);
    } else if (!strcmp(c, "voicetrace")) {           /* voicetrace on|off|status: log every voice line request */
        ctl_voicetrace(o, argc, argv);
    } else if (!strcmp(c, "watch")) {                /* watch ADDR LEN | status|dump|off|selftest (WRITEWATCH1) */
        ctl_watch(o, argc, argv);
    } else if (!strcmp(c, "auto") && argc > 1 && !D5_AUTO) {
        sbf(o, "{\"error\":\"this runtime has no auto-battle\"}");
    } else if (!strcmp(c, "auto") && argc > 1) {
        int on = !strcmp(argv[1], "on") || !strcmp(argv[1], "force");
        if (on && strcmp(argv[1], "force") && !in_item_world()) sbf(o, "{\"error\":\"not in the Item World\"}");
        else {
            auto_reset();
            InterlockedExchange(&g_active, on);
            logf_("auto-battle %s (remote)", on ? "ON" : "OFF");
            if (on) log_battlefield("switched on (remote)");
            sbf(o, "{\"ok\":1}");
        }
    } else if (!strcmp(c, "silent")) {              /* silent on | off | status: the game's volumes 0, memory only */
        char b[512];
        if (argc > 1 && !strcmp(argv[1], "off")) sound_set(0);
        else if (argc > 1 && !strcmp(argv[1], "on")) sound_set(1);
        sound_report(b, sizeof b);
        sbf(o, "%s", b);
    } else if (!strcmp(c, "win")) {                 /* win offscreen [X Y] | hide | show | state */
        char b[256];
        game_window();
        winhide_cmd(g_hwnd, argc, argv, b, sizeof b);
        sbf(o, "%s", b);
    } else if (!strcmp(c, "focus") && argc > 1) {
        game_window();
        InterlockedExchange(&g_fake_focus, !strcmp(argv[1], "on"));
        sbf(o, "{\"ok\":1,\"hwnd\":\"%p\"}", (void *)g_hwnd);
    } else if (!strcmp(c, "set") && argc > 2) {
        int v = atoi(argv[2]), ok = 1;
        if (!strcmp(argv[1], "sp_saving")) g_sp_saving = v;
        else if (!strcmp(argv[1], "kill_margin")) g_kill_margin = v;
        else if (!strcmp(argv[1], "reach")) g_reach = v;
        else if (!strcmp(argv[1], "input_guard")) {
            g_input_guard = v != 0;
            if (!v && g_wh_mode && g_hwnd) { char *a[2] = {"win", "show"}, b[64]; winhide_cmd(g_hwnd, 2, a, b, sizeof b); }
        }
        else if (!strcmp(argv[1], "heal_below")) g_heal_below = v;
        else if (!strcmp(argv[1], "deploy")) g_deploy = v;
        else if (!strcmp(argv[1], "deploy_max")) g_deploy_max = v;
        else if (!strcmp(argv[1], "skitff")) { g_skitff = v; skitff_apply(); }
        else if (!strcmp(argv[1], "msgbox_dismiss")) g_msgbox_dismiss = v != 0;
        else ok = 0;
        sbf(o, ok ? "{\"ok\":1}" : "{\"error\":\"unknown setting\"}");
    } else if (!strcmp(c, "record") && argc > 1) {  /* record EVENT EVERY SCALE MAX DIR | record stop | status */
        if (!strcmp(argv[1], "stop")) {
            rec_finish();
            sbf(o, "{\"ok\":1,\"frames\":%ld}", (long)g_rec_count);
        } else if (!strcmp(argv[1], "status")) {
            sbf(o, "{\"armed\":%ld,\"on\":%ld,\"frames\":%ld,\"tick\":%ld}", (long)g_rec_armed, (long)g_rec_on,
                (long)g_rec_count, g_rec_on ? (long)(g_frame - g_rec_start) : -1L);
        } else if (argc > 5) {
            rec_finish();
            if (!rec_prepare()) sbf(o, "{\"error\":\"the script start can't be hooked\"}");
            else {
                g_rec_every = atol(argv[2]);
                g_rec_scale = atol(argv[3]);
                g_rec_max = atol(argv[4]);
                snprintf(g_rec_dir, sizeof g_rec_dir, "%s", rest_after(g_cmd, 5));
                trim_end(g_rec_dir);
                CreateDirectoryA(g_rec_dir, NULL);
                g_rec_count = 0;
                *g_rec_hit = 0;
                *g_rec_watch = atol(argv[1]);
                InterlockedExchange(&g_rec_armed, 1);
                sbf(o, "{\"ok\":1}");
            }
        } else sbf(o, "{\"error\":\"record EVENT EVERY SCALE MAX DIR\"}");
    } else if (!strcmp(c, "probe") && argc > 1) {    /* probe FROM TO | probe off: extra data in recordings */
        if (!strcmp(argv[1], "off")) g_probe_from = g_probe_to = -1;
        else if (argc > 2) { g_probe_from = atol(argv[1]); g_probe_to = atol(argv[2]); }
        sbf(o, "{\"ok\":1,\"from\":%ld,\"to\":%ld}", (long)g_probe_from, (long)g_probe_to);
    } else if (!strcmp(c, "trace")) {
        if (argc > 1 && !strcmp(argv[1], "off")) {
            CloseHandle(CreateThread(NULL, 0, arm_thread, NULL, 0, NULL));
            sbf(o, "{\"ok\":1,\"hits\":%ld}", (long)g_trace_hits);
        } else {
            g_nwatch = 0;
            g_nseen = 0;
            for (int i = 1; i + 3 < argc + 0 && g_nwatch < 4; i += 4) {
                unsigned long long a = strtoull(argv[i], NULL, 16);
                int raw = !(a >= 0x140000000ULL && a < 0x140000000ULL + g_image_size);
                snprintf(g_watch_names[g_nwatch], sizeof g_watch_names[0], "%s", argv[i + 3]);
                g_watch[g_nwatch] = (WATCH){a, atoi(argv[i + 1]), atoi(argv[i + 2]), g_watch_names[g_nwatch], raw};
                g_nwatch++;
            }
            if (!g_veh) g_veh = AddVectoredExceptionHandler(1, trace_veh);
            CloseHandle(CreateThread(NULL, 0, arm_thread, (LPVOID)1, 0, NULL));
            sbf(o, "{\"ok\":1,\"watches\":%d}", g_nwatch);
        }
    } else {
        sbf(o, "{\"error\":\"unknown command\"}");
    }
    ctl_finish();
}

/* the text after the first n words of a line (paths may contain spaces) */
static const char *rest_after(const char *line, int n) {
    const char *p = line;
    for (int i = 0; i < n; i++) {
        while (*p == ' ' || *p == '\t') p++;
        while (*p && *p != ' ' && *p != '\t') p++;
    }
    while (*p == ' ' || *p == '\t') p++;
    return p;
}

/* ------------------------------------------------------------------ sampling profiler (prof MS)
 * The game thread is stopped about once a millisecond for MS milliseconds: where it is (the leaf: exe addresses as
 * static VAs, others as module+offset) and which exe functions it is in (return addresses on its stack that
 * follow a call, the first 8 counted once per sample: 'inclusive').  No unwinding (no loader locks): the stack
 * scan can name a stale return address now and then, the leaf never lies. */
typedef struct { unsigned long long a; unsigned n; } PFHIT;
#define PF_CAP 8192
static PFHIT g_pf_leaf[PF_CAP], g_pf_incl[PF_CAP];

static void pf_count(PFHIT *t, unsigned long long a) {
    unsigned h = (unsigned)((a * 0x9E3779B97F4A7C15ULL) >> 51) & (PF_CAP - 1);
    for (int i = 0; i < PF_CAP; i++, h = (h + 1) & (PF_CAP - 1)) {
        if (t[h].a == a) { t[h].n++; return; }
        if (!t[h].a) { t[h].a = a; t[h].n = 1; return; }
    }
}
static int pf_cmp(const void *x, const void *y) {
    unsigned a = ((const PFHIT *)x)->n, b = ((const PFHIT *)y)->n;
    return a < b ? 1 : a > b ? -1 : 0;
}
/* a return address in the exe: the bytes before it are a call */
static int pf_after_call(const unsigned char *r) {
    if (r < g_base + 0x1000 || r >= g_base + g_image_size) return 0;
    if (r[-5] == 0xe8) return 1;                                   /* call rel32 */
    if (r[-6] == 0xff && r[-5] == 0x15) return 1;                  /* call [rip + x] */
    if (r[-2] == 0xff && (r[-1] & 0xf8) == 0xd0) return 1;         /* call reg */
    if (r[-3] == 0x41 && r[-2] == 0xff && (r[-1] & 0xf8) == 0xd0) return 1;
    if (r[-3] == 0xff && (r[-2] & 0x38) == 0x10 && (r[-2] & 0xc0) == 0x40) return 1;   /* call [reg + d8] */
    if (r[-6] == 0xff && (r[-5] & 0x38) == 0x10 && (r[-5] & 0xc0) == 0x80) return 1;   /* call [reg + d32] */
    return 0;
}
static void pf_put_addr(SB *o, unsigned long long a) {
    if (a >= 0x140000000ULL && a < 0x140000000ULL + g_image_size) { sbf(o, "\"0x%llx\"", a); return; }
    HMODULE m = NULL;
    char name[MAX_PATH] = "?";
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCSTR)a, &m) && m) {
        GetModuleFileNameA(m, name, sizeof name);
        char *s = strrchr(name, '\\');
        if (s) memmove(name, s + 1, strlen(s));
        sbf(o, "\"%s+0x%llx\"", name, a - (unsigned long long)m);
    } else sbf(o, "\"0x%llx\"", a);
}

static volatile LONG g_pf_sampling;            /* a profile is being taken (harness or perf report) */

static void ctl_prof(SB *o, int ms) {
    if (!g_game_tid) { sbf(o, "{\"error\":\"no game frame yet\"}"); return; }
    HANDLE th = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, g_game_tid);
    if (!th) { sbf(o, "{\"error\":\"OpenThread %lu\"}", GetLastError()); return; }
    memset(g_pf_leaf, 0, sizeof g_pf_leaf);
    memset(g_pf_incl, 0, sizeof g_pf_incl);
    LARGE_INTEGER f, t0, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t0);
    LONG fr0 = g_frame;
    int samples = 0, in_exe = 0;
    for (;;) {
        QueryPerformanceCounter(&t);
        if ((t.QuadPart - t0.QuadPart) * 1000 / f.QuadPart >= ms) break;
        if (SuspendThread(th) == (DWORD)-1) break;
        CONTEXT cx;
        memset(&cx, 0, sizeof cx);
        cx.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (GetThreadContext(th, &cx)) {
            samples++;
            unsigned long long leaf = to_static(cx.Rip);
            if (leaf != cx.Rip) in_exe++;
            pf_count(g_pf_leaf, leaf);
            unsigned long long seen[8];
            int ns = 0;
            if (leaf != cx.Rip) seen[ns++] = leaf;     /* the leaf counts as 'in' its own function too */
            const unsigned long long *sp = (const unsigned long long *)cx.Rsp;
            MEMORY_BASIC_INFORMATION mi;
            if (VirtualQuery(sp, &mi, sizeof mi) && mi.State == MEM_COMMIT) {
                const unsigned long long *end = (const unsigned long long *)((char *)mi.BaseAddress + mi.RegionSize);
                for (int i = 0; sp + i < end && i < 2048 && ns < 8; i++) {
                    const unsigned char *r = (const unsigned char *)sp[i];
                    if (!pf_after_call(r)) continue;
                    seen[ns++] = to_static((DWORD64)r);
                }
            }
            for (int i = 0; i < ns; i++) {
                int dup = 0;
                for (int j = 0; j < i; j++) dup |= seen[j] == seen[i];
                if (!dup) pf_count(g_pf_incl, seen[i]);
            }
        }
        ResumeThread(th);
        LARGE_INTEGER w0, w;                       /* ~1 ms to the next sample (Sleep(1) may be 15 ms) */
        QueryPerformanceCounter(&w0);
        do { YieldProcessor(); QueryPerformanceCounter(&w); } while ((w.QuadPart - w0.QuadPart) * 1000 < f.QuadPart);
    }
    CloseHandle(th);
    LONG frames = g_frame - fr0;
    qsort(g_pf_leaf, PF_CAP, sizeof(PFHIT), pf_cmp);
    qsort(g_pf_incl, PF_CAP, sizeof(PFHIT), pf_cmp);
    sbf(o, "{\"ok\":1,\"ms\":%d,\"frames\":%ld,\"samples\":%d,\"in_exe\":%d,\"leaf\":[", ms, (long)frames, samples, in_exe);
    for (int i = 0; i < 60 && g_pf_leaf[i].n; i++) {
        sbf(o, "%s[", i ? "," : "");
        pf_put_addr(o, g_pf_leaf[i].a);
        sbf(o, ",%u]", g_pf_leaf[i].n);
    }
    sb_put(o, "],\"incl\":[", 10);
    for (int i = 0; i < 80 && g_pf_incl[i].n; i++)
        sbf(o, "%s[\"0x%llx\",%u]", i ? "," : "", g_pf_incl[i].a, g_pf_incl[i].n);
    sb_put(o, "]}", 2);
}

/* the process's memory (Task Manager's numbers) */
typedef struct { DWORD cb, PageFaultCount; SIZE_T PeakWorkingSetSize, WorkingSetSize, QuotaPeakPagedPoolUsage,
    QuotaPagedPoolUsage, QuotaPeakNonPagedPoolUsage, QuotaNonPagedPoolUsage, PagefileUsage, PeakPagefileUsage,
    PrivateUsage; } PF_PMC;
__declspec(dllimport) BOOL WINAPI K32GetProcessMemoryInfo(HANDLE, void *, DWORD);
static void ctl_mem(SB *o) {
    PF_PMC pm;
    memset(&pm, 0, sizeof pm);
    pm.cb = sizeof pm;
    K32GetProcessMemoryInfo(GetCurrentProcess(), &pm, sizeof pm);
    DWORD handles = 0;
    GetProcessHandleCount(GetCurrentProcess(), &handles);
    HANDLE heaps[256];
    DWORD nh = GetProcessHeaps(256, heaps);
    sbf(o, "{\"ok\":1,\"private_mb\":%.1f,\"working_mb\":%.1f,\"handles\":%lu,\"heaps\":%lu,\"gdi\":%lu,\"user\":%lu}",
        pm.PrivateUsage / 1048576.0, pm.WorkingSetSize / 1048576.0, handles, nh,
        GetGuiResources(GetCurrentProcess(), 0), GetGuiResources(GetCurrentProcess(), 1));
}

/* ------------------------------------------------------------------ SOAKFREEZE2: read the dialog that freezes the game
 * The wheel soak sometimes stops the frame thread inside a modal message loop (SOAKFREEZE1: GetMessage under the draw
 * frames, a 320x117 window).  Three tools, all harness-only (remote=1), none changes what the game does by default:
 *   - MessageBoxA/W are hooked (import slots found by name): text, caption, flags, the caller and the exe return
 *     addresses on the stack go to d5auto.log BEFORE the box opens.  [debug] msgbox_dismiss=1 / 'set msgbox_dismiss 1'
 *     answers MB_OK boxes with OK and MB_YESNO boxes with No instead of showing them (a soak then goes on).
 *   - 'dlg' (pipe thread, works while the frame thread is blocked): every window of the process with its class, text,
 *     rectangle and thread, plus the texts of dialog children: reads any dialog, not only MessageBox.
 *   - 'stk [N]': the first N stack words of the frame thread that point into a module (module+offset), with their
 *     distance from the stack pointer, and the thread's RIP/RSP: the whole stack, not prof's first eight. */
typedef int(WINAPI *MessageBoxW_t)(HWND, LPCWSTR, LPCWSTR, UINT);
typedef int(WINAPI *MessageBoxA_t)(HWND, LPCSTR, LPCSTR, UINT);
static MessageBoxW_t oMessageBoxW;
static MessageBoxA_t oMessageBoxA;

static void **iat_slot(const char *dll, const char *fn) {       /* the import slot of DLL!FN in the game's exe */
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)g_base;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY *dd = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dd->VirtualAddress) return NULL;
    for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(g_base + dd->VirtualAddress); d->Name; d++) {
        if (_stricmp((const char *)g_base + d->Name, dll)) continue;
        IMAGE_THUNK_DATA64 *nm = (IMAGE_THUNK_DATA64 *)(g_base + (d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk));
        void **iat = (void **)(g_base + d->FirstThunk);
        for (; nm->u1.AddressOfData; nm++, iat++) {
            if (nm->u1.Ordinal & IMAGE_ORDINAL_FLAG64) continue;
            if (!strcmp((const char *)((IMAGE_IMPORT_BY_NAME *)(g_base + nm->u1.AddressOfData))->Name, fn)) return iat;
        }
    }
    return NULL;
}

static void sb_wstr(SB *s, const wchar_t *w) {                    /* JSON string from UTF-16 */
    sb_put(s, "\"", 1);
    for (; w && *w; w++) {
        if (*w == '"' || *w == '\\') { char e[2] = {'\\', (char)*w}; sb_put(s, e, 2); }
        else if (*w < 32 || *w > 126) sbf(s, "\\u%04x", (unsigned)*w);
        else { char c = (char)*w; sb_put(s, &c, 1); }
    }
    sb_put(s, "\"", 1);
}

static void msgbox_log(const char *api, const wchar_t *text, const wchar_t *cap, UINT flags, const void *ret,
                       const unsigned long long *sp) {
    SB s = {0};
    sb_wstr(&s, text);
    SB c = {0};
    sb_wstr(&c, cap);
    char chain[400];
    int n = 0;
    for (int i = 0; i < 256 && n < (int)sizeof chain - 24; i++) {         /* exe return addresses above this call */
        if (pf_after_call((const unsigned char *)sp[i])) n += snprintf(chain + n, sizeof chain - n, " %llx", to_static(sp[i]));
    }
    chain[n] = 0;
    logf_("MSGBOX %s flags=0x%x from %llx caption=%s text=%s | exe frames:%s", api, flags, to_static((DWORD64)ret),
          c.p ? c.p : "\"\"", s.p ? s.p : "\"\"", chain);
    free(s.p);
    free(c.p);
}
static int WINAPI hkMessageBoxW(HWND h, LPCWSTR t, LPCWSTR c, UINT f) {
    msgbox_log("W", t, c, f, __builtin_return_address(0), (const unsigned long long *)__builtin_frame_address(0));
    if (g_msgbox_dismiss && ((f & 0xf) == MB_OK || (f & 0xf) == MB_YESNO)) return (f & 0xf) == MB_OK ? IDOK : IDNO;
    return oMessageBoxW(h, t, c, f);
}
static int WINAPI hkMessageBoxA(HWND h, LPCSTR t, LPCSTR c, UINT f) {
    wchar_t wt[512], wc[128];
    MultiByteToWideChar(CP_ACP, 0, t ? t : "", -1, wt, 512);
    MultiByteToWideChar(CP_ACP, 0, c ? c : "", -1, wc, 128);
    msgbox_log("A", wt, wc, f, __builtin_return_address(0), (const unsigned long long *)__builtin_frame_address(0));
    if (g_msgbox_dismiss && ((f & 0xf) == MB_OK || (f & 0xf) == MB_YESNO)) return (f & 0xf) == MB_OK ? IDOK : IDNO;
    return oMessageBoxA(h, t, c, f);
}
static void install_msgbox_hook(void) {
    void **w = iat_slot("user32.dll", "MessageBoxW"), **a = iat_slot("user32.dll", "MessageBoxA");
    if (w) patch_slot(w, (void *)hkMessageBoxW, (void **)&oMessageBoxW);
    if (a) patch_slot(a, (void *)hkMessageBoxA, (void **)&oMessageBoxA);
    logf_("ctl: MessageBox hooked (W slot %llx, A slot %llx), dismiss %s ([debug] msgbox_dismiss)",
          w ? to_static((DWORD64)w) : 0ULL, a ? to_static((DWORD64)a) : 0ULL, g_msgbox_dismiss ? "on" : "off");
}

typedef struct { SB *o; int n; } DLGCTX;
static BOOL CALLBACK dlg_child(HWND w, LPARAM lp) {
    DLGCTX *x = (DLGCTX *)lp;
    wchar_t cls[48] = L"", txt[256] = L"";
    DWORD_PTR r = 0;
    GetClassNameW(w, cls, 48);
    SendMessageTimeoutW(w, WM_GETTEXT, 256, (LPARAM)txt, SMTO_ABORTIFHUNG, 300, &r);
    sbf(x->o, "%s[", x->n++ ? "," : "");
    sb_wstr(x->o, cls);
    sb_put(x->o, ",", 1);
    sb_wstr(x->o, txt);
    sb_put(x->o, "]", 1);
    return x->n < 24;
}
static BOOL CALLBACK dlg_top(HWND w, LPARAM lp) {
    DLGCTX *x = (DLGCTX *)lp;
    DWORD pid = 0, tid = GetWindowThreadProcessId(w, &pid);
    if (pid != GetCurrentProcessId() || x->n >= 32) return TRUE;
    wchar_t cls[64] = L"", txt[256] = L"";
    DWORD_PTR r = 0;
    RECT rc = {0, 0, 0, 0};
    GetClassNameW(w, cls, 64);
    GetWindowRect(w, &rc);
    SendMessageTimeoutW(w, WM_GETTEXT, 256, (LPARAM)txt, SMTO_ABORTIFHUNG, 300, &r);
    sbf(x->o, "%s{\"hwnd\":\"%p\",\"tid\":%lu,\"vis\":%d,\"owner\":\"%p\",\"rect\":[%ld,%ld,%ld,%ld],\"class\":",
        x->n++ ? "," : "", (void *)w, (unsigned long)tid, IsWindowVisible(w) ? 1 : 0, (void *)GetWindow(w, GW_OWNER),
        (long)rc.left, (long)rc.top, (long)rc.right, (long)rc.bottom);
    sb_wstr(x->o, cls);
    sb_put(x->o, ",\"text\":", 8);
    sb_wstr(x->o, txt);
    sb_put(x->o, ",\"children\":[", 13);
    DLGCTX k = {x->o, 0};
    EnumChildWindows(w, dlg_child, (LPARAM)&k);
    sb_put(x->o, "]}", 2);
    return TRUE;
}
static void ctl_dlg(SB *o) {
    sbf(o, "{\"ok\":1,\"game_tid\":%lu,\"windows\":[", (unsigned long)g_game_tid);
    DLGCTX x = {o, 0};
    EnumWindows(dlg_top, (LPARAM)&x);
    sb_put(o, "]}", 2);
}

#define STK_MAX 1024
static void ctl_stk(SB *o, int n) {
    if (!g_game_tid) { sbf(o, "{\"error\":\"no game frame yet\"}"); return; }
    HANDLE th = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, g_game_tid);
    if (!th) { sbf(o, "{\"error\":\"OpenThread %lu\"}", GetLastError()); return; }
    unsigned long long w[STK_MAX], rip = 0, rsp = 0;
    int got = 0;
    if (n < 1) n = 256;
    if (n > STK_MAX) n = STK_MAX;
    if (SuspendThread(th) != (DWORD)-1) {
        CONTEXT cx;
        memset(&cx, 0, sizeof cx);
        cx.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (GetThreadContext(th, &cx)) {
            rip = cx.Rip;
            rsp = cx.Rsp;
            const unsigned long long *sp = (const unsigned long long *)cx.Rsp;
            MEMORY_BASIC_INFORMATION mi;
            if (VirtualQuery(sp, &mi, sizeof mi) && mi.State == MEM_COMMIT) {
                const unsigned long long *end = (const unsigned long long *)((char *)mi.BaseAddress + mi.RegionSize);
                while (got < n && sp + got < end) { w[got] = sp[got]; got++; }
            }
        }
        ResumeThread(th);
    }
    CloseHandle(th);
    sbf(o, "{\"ok\":1,\"rsp\":\"0x%llx\",\"rip\":", rsp);
    pf_put_addr(o, rip);
    sb_put(o, ",\"words\":[", 10);
    int k = 0;
    for (int i = 0; i < got; i++) {                    /* code addresses only: [words from SP, address, after-a-call] */
        HMODULE m = NULL;
        unsigned long long a = w[i];
        if (a < 0x10000 || !GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                               GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)a, &m) || !m) continue;
        sbf(o, "%s[%d,", k++ ? "," : "", i);
        pf_put_addr(o, a);
        sbf(o, ",%d]", pf_after_call((const unsigned char *)a));
    }
    sb_put(o, "]}", 2);
}

/* commands that the pipe thread answers itself (no game-thread work) */
static int ctl_direct(const char *line, SB *o) {
    char buf[4096], *argv[16];
    int argc = 0;
    strncpy(buf, line, sizeof buf - 1);
    buf[sizeof buf - 1] = 0;
    for (char *t = strtok(buf, " \t\r\n"); t && argc < 16; t = strtok(NULL, " \t\r\n")) argv[argc++] = t;
    if (!argc) return 0;
    if (!strcmp(argv[0], "ping")) { sbf(o, "{\"ok\":1,\"frame\":%ld}", (long)g_frame); return 1; }
    if (!strcmp(argv[0], "prof")) {
        int ms = argc > 1 ? atoi(argv[1]) : 2000;
        if (InterlockedExchange(&g_pf_sampling, 1)) { sbf(o, "{\"error\":\"a profile is running\"}"); return 1; }
        ctl_prof(o, ms < 50 ? 50 : ms > 20000 ? 20000 : ms);
        InterlockedExchange(&g_pf_sampling, 0);
        return 1;
    }
    if (!strcmp(argv[0], "mem")) { ctl_mem(o); return 1; }
    if (!strcmp(argv[0], "dlg")) { ctl_dlg(o); return 1; }
    if (!strcmp(argv[0], "stk")) { ctl_stk(o, argc > 1 ? atoi(argv[1]) : 256); return 1; }
    if (!strcmp(argv[0], "rd") && argc > 2) {
        unsigned char *a = ctl_addr(strtoull(argv[1], NULL, 16));
        int n = atoi(argv[2]);
        if (n < 1 || n > 65536 || !readable(a, (SIZE_T)n)) { sbf(o, "{\"error\":\"not readable\"}"); return 1; }
        sbf(o, "{\"ok\":1,\"hex\":\"");
        for (int i = 0; i < n; i++) sbf(o, "%02x", a[i]);
        sb_put(o, "\"}", 2);
        return 1;
    }
    if (!strcmp(argv[0], "dump") && argc > 3) {
        unsigned char *a = ctl_addr(strtoull(argv[1], NULL, 16));
        size_t n = (size_t)strtoull(argv[2], NULL, 0);
        char path[MAX_PATH];
        snprintf(path, sizeof path, "%s", rest_after(line, 3));
        trim_end(path);
        FILE *f = fopen(path, "wb");
        if (!f) { sbf(o, "{\"error\":\"cannot write\"}"); return 1; }
        size_t done = 0;
        while (done < n) {                       /* page by page: unreadable pages become zeros */
            size_t k = 0x1000 - (((size_t)(a + done)) & 0xfff);
            if (k > n - done) k = n - done;
            if (readable(a + done, k)) fwrite(a + done, 1, k, f);
            else { static const unsigned char z[4096]; fwrite(z, 1, k, f); }
            done += k;
        }
        fclose(f);
        sbf(o, "{\"ok\":1,\"n\":%zu}", n);
        return 1;
    }
    if (!strcmp(argv[0], "scan") && argc > 1) {
        if (!strcmp(argv[1], "new") && argc > 3) {
            int size = argv[2][0] == 'f' ? 'f' : atoi(argv[2]);
            if (size != 1 && size != 2 && size != 4 && size != 8 && size != 'f') { sbf(o, "{\"error\":\"size\"}"); return 1; }
            scan_new(o, size, argv[3]);
        } else if (!strcmp(argv[1], "next") && argc > 2) {
            scan_next(o, argv[2], argc > 3 ? argv[3] : NULL);
        } else if (!strcmp(argv[1], "list")) {
            scan_list(o, argc > 2 ? atoi(argv[2]) : 50);
        } else {
            sbf(o, "{\"error\":\"scan new SIZE VALUE | next OP [VALUE] | list [N]\"}");
        }
        return 1;
    }
    if (!strcmp(argv[0], "shot") && argc > 1) {
        snprintf(g_shot_path, sizeof g_shot_path, "%s", rest_after(line, 1));
        trim_end(g_shot_path);
        ResetEvent(g_shot_done);
        InterlockedExchange(&g_shot_req, 1);
        if (WaitForSingleObject(g_shot_done, 5000) != WAIT_OBJECT_0) {
            InterlockedExchange(&g_shot_req, 0);
            sbf(o, "{\"error\":\"no frame was presented in 5 s\"}");
        } else {
            sbf(o, "%s", g_shot_result);
        }
        return 1;
    }
    return 0;
}

/* the pipe is for this user only, and reachable from a normal (medium integrity) process even when the game
   runs elevated */
static SECURITY_ATTRIBUTES *pipe_sa(void) {
    static SECURITY_ATTRIBUTES sa;
    static PSECURITY_DESCRIPTOR sd;
    if (sd) return &sa;
    HANDLE tok;
    char *sid = NULL, sddl[512];
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &tok)) {
        BYTE buf[256];
        DWORD n;
        if (GetTokenInformation(tok, TokenUser, buf, sizeof buf, &n)) ConvertSidToStringSidA(((TOKEN_USER *)buf)->User.Sid, &sid);
        CloseHandle(tok);
    }
    if (!sid) return NULL;
    snprintf(sddl, sizeof sddl, "D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;%s)S:(ML;;NW;;;ME)", sid);
    LocalFree(sid);
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorA(sddl, SDDL_REVISION_1, &sd, NULL)) { sd = NULL; return NULL; }
    sa.nLength = sizeof sa;
    sa.lpSecurityDescriptor = sd;
    return &sa;
}

static volatile LONG g_ctl_quit;
static HANDLE g_ctl_thread;

static DWORD WINAPI ctl_thread(LPVOID p) {
    (void)p;
    while (!g_ctl_quit) {
        HANDLE h = CreateNamedPipeA(CTL_PIPE, PIPE_ACCESS_DUPLEX, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT, 1,
                                    1 << 20, 1 << 16, 0, pipe_sa());
        if (h == INVALID_HANDLE_VALUE) { logf_("ctl: CreateNamedPipe failed (%lu)", GetLastError()); return 0; }
        if (!ConnectNamedPipe(h, NULL) && GetLastError() != ERROR_PIPE_CONNECTED) { CloseHandle(h); continue; }
        if (g_ctl_quit) { CloseHandle(h); break; }
        char in[8192];
        size_t have = 0;
        while (!g_ctl_quit) {
            DWORD got = 0;
            if (!ReadFile(h, in + have, (DWORD)(sizeof in - 1 - have), &got, NULL) || !got) break;
            have += got;
            in[have] = 0;
            char *nl;
            while ((nl = strchr(in, '\n')) != NULL) {
                *nl = 0;
                SB direct = {0};
                const char *reply;
                if (ctl_direct(in, &direct)) {
                    reply = direct.p ? direct.p : "{}";
                } else {
                    strncpy(g_cmd, in, sizeof g_cmd - 1);
                    g_cmd[sizeof g_cmd - 1] = 0;
                    ResetEvent(g_cmd_done);
                    InterlockedExchange(&g_cmd_pending, 1);
                    DWORD wr = WAIT_TIMEOUT;               /* "wait" may take minutes */
                    for (int slice = 0; slice < 15 * 60 * 4 && !g_ctl_quit; slice++) {
                        wr = WaitForSingleObject(g_cmd_done, 250);
                        if (wr == WAIT_OBJECT_0) break;
                        if (!PeekNamedPipe(h, NULL, 0, NULL, NULL, NULL) && GetLastError() == ERROR_BROKEN_PIPE &&
                            g_cmd_wait_frames > 1)
                            g_cmd_wait_frames = 1;         /* the client is gone: its "wait" ends now */
                    }
                    if (wr != WAIT_OBJECT_0) {
                        g_cmd_wait_frames = 0;           /* nothing of this command may finish the next one */
                        g_cmd_wait_keys = 0;
                        InterlockedExchange(&g_cmd_pending, 0);
                        reply = "{\"error\":\"the game thread did not answer (paused?)\"}";
                    } else {
                        reply = g_reply.p ? g_reply.p : "{}";
                    }
                }
                DWORD wrote;
                WriteFile(h, reply, (DWORD)strlen(reply), &wrote, NULL);
                WriteFile(h, "\n", 1, &wrote, NULL);
                free(direct.p);
                size_t rest = have - (size_t)(nl + 1 - in);
                memmove(in, nl + 1, rest);
                have = rest;
                in[have] = 0;
            }
            if (have >= sizeof in - 1) have = 0;
        }
        DisconnectNamedPipe(h);
        CloseHandle(h);
    }
    return 0;
}

static void ctl_start(void) {
    if (!g_remote) return;
    g_shot_done = CreateEventA(NULL, TRUE, FALSE, NULL);
    g_cmd_done = CreateEventA(NULL, TRUE, FALSE, NULL);
    install_focus_hook();
    install_msgbox_hook();
    g_ctl_thread = CreateThread(NULL, 0, ctl_thread, NULL, 0, NULL);
    logf_("ctl: remote control on %s", CTL_PIPE);
}

static void ctl_stop(void) {
    fac_restore();                             /* a shop/guide selector byte still set (hot reload) */
    at_off();                                  /* anmtrace hooks out (hot reload) */
    vt_off();                                  /* voicetrace hook out */
    ww_off();                                  /* write-watch: pages writable, handler out */
    if (!g_ctl_thread) return;
    InterlockedExchange(&g_ctl_quit, 1);
    SetEvent(g_cmd_done);
    SetEvent(g_shot_done);
    for (int i = 0; i < 50; i++) {             /* break ConnectNamedPipe / ReadFile */
        CancelSynchronousIo(g_ctl_thread);
        HANDLE c = CreateFileA(CTL_PIPE, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
        if (c != INVALID_HANDLE_VALUE) CloseHandle(c);
        if (WaitForSingleObject(g_ctl_thread, 20) == WAIT_OBJECT_0) break;
    }
    CloseHandle(g_ctl_thread);
    g_ctl_thread = NULL;
}
