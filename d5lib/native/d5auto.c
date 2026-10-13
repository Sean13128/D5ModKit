/* d5auto.dll -- Item World auto-battle for Disgaea 5 Complete (PC).
 *
 * Loaded by the exe patch (d5lib/autobattle.py): the game's per-frame update calls d5_frame() right after
 * it polled the keyboard / gamepad.  This file currently holds the foundation:
 *   - toggle hotkey (keyboard key + gamepad combo, from d5auto.ini), only while the game has focus
 *   - on-screen indicator, drawn into the swap chain's back buffer with ID3D11DeviceContext1::ClearView
 *     (plain rectangles: no shaders, no pipeline state touched, so the game's rendering is unaffected)
 *   - d5auto.log next to the exe for diagnostics
 * The battle logic (Item World detection, unit control) is added on top of this.
 */
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <stdarg.h>
#include <string.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi.h>
#include <dxgi1_2.h>
#include <tlhelp32.h>
#include <sddl.h>
#define DIRECTINPUT_VERSION 0x0800
#include <dinput.h>

/* The Item World auto-battle itself (d5pilot.inc.c, d5di.inc.c, d5menu.inc.c) is built in only when its sources are
 * here: the shareable kit leaves them out and gets d5noauto.inc.c's stand-ins (D5_NO_AUTO forces that too). */
#if !defined(D5_NO_AUTO) && __has_include("d5pilot.inc.c")
#define D5_AUTO 1
#else
#define D5_AUTO 0
#endif

/* ------------------------------------------------------------------------------------------ log */
static char g_dir[MAX_PATH];
static FILE *g_log;
static int g_gen;                  /* how many times the loader (d5load.c) has reloaded this core */

static void logf_(const char *fmt, ...) {
    if (!g_log) {
        char p[MAX_PATH];
        snprintf(p, sizeof p, "%sd5auto.log", g_dir);
        g_log = fopen(p, g_gen ? "a" : "w");
        if (!g_log) return;
    }
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(g_log, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list a;
    va_start(a, fmt);
    vfprintf(g_log, fmt, a);
    va_end(a);
    fputc('\n', g_log);
    fflush(g_log);
}

/* strip trailing blanks / line ends */
static void trim_end(char *t) {
    size_t k = strlen(t);
    while (k && (t[k - 1] == ' ' || t[k - 1] == '\t' || t[k - 1] == '\r' || t[k - 1] == '\n')) t[--k] = 0;
}

/* ------------------------------------------------------------------------------------- settings */
static int g_key = VK_F5;          /* keyboard toggle */
static int g_editor_key = VK_F6;   /* the in-game D.I. editor */
static volatile LONG g_cc_open;    /* custom colour slot picker open (d5color.inc.c) */
static int g_cc_enabled;           /* custom colour slots (Custom Color Slots mod) */
static int g_cc_key = 'U';
static WORD g_cc_pad = 0x0080;     /* R3 */
static int g_feat_auto = 1;        /* the auto-battle feature (Item World Auto-Battle mod) */
static volatile LONG g_menu_open;  /* the editor is open: the game gets no input (d5menu.inc.c) */
static WORD g_pad = 0x0040 | 0x0080; /* XINPUT_GAMEPAD_LEFT_THUMB | RIGHT_THUMB (L3+R3) */
static int g_test_anywhere = 0;    /* test builds: allow the toggle outside the Item World */
static int g_corner = 1;           /* indicator corner: 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right */
static int g_research = 0;         /* research build: F7 = hardware watchpoints, F8 = virtual pad test */
static int g_deploy = 1;           /* deploy the dispatch list top-down at the start of each floor */
static int g_deploy_max = 10;
static int g_stall_limit = 8;      /* D.I.: switch off after this many turns without hurting an enemy (0 = never) */
static const char *g_status_hold;  /* a message kept on screen for a few seconds after switching off */
static DWORD g_status_hold_until;
/* tactics (Demonic-Intelligence style rules applied to the game's AI) */
static int g_sp_saving = 1;        /* hide SP from units whose normal attack kills every enemy in reach */
static int g_kill_margin = 150;    /* "kills" = estimated normal-attack damage >= enemy HP * margin% */
static int g_reach = 10;           /* enemies within this many panels count as "in reach" */
static int g_heal_below = 50;      /* casters keep their SP while an ally is below this HP% */
static int g_live;                 /* [skills] live_reload=1: d5live.inc.c */
static int g_battle_speed;         /* [battle] speed: 0 the game's options, 1 normal (button still fast-forwards), 2-4 xN */
static volatile LONG g_presents, g_present_sync;   /* frames presented, last vsync interval (harness 'state') */
static int g_remote;               /* [debug] remote=1: test harness pipe (d5ctl.inc.c) */
static volatile LONG g_fake_focus; /* harness: the game believes it has focus, the real keyboard is ignored */
static volatile LONG g_frame;      /* d5_frame calls */

static int key_code(const char *s) {
    if ((s[0] == 'F' || s[0] == 'f') && s[1] >= '1' && s[1] <= '9') {
        int n = atoi(s + 1);
        if (n >= 1 && n <= 24) return VK_F1 + n - 1;
    }
    if (!_stricmp(s, "Tab")) return VK_TAB;
    if (!_stricmp(s, "Insert")) return VK_INSERT;
    if (!_stricmp(s, "Home")) return VK_HOME;
    if (!_stricmp(s, "End")) return VK_END;
    if (!_stricmp(s, "PageUp")) return VK_PRIOR;
    if (!_stricmp(s, "PageDown")) return VK_NEXT;
    if (!_stricmp(s, "Pause")) return VK_PAUSE;
    if (s[0] && !s[1]) {
        char c = s[0];
        if (c >= 'a' && c <= 'z') c -= 32;
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) return c;
    }
    return VK_F5;
}

static WORD pad_bits(const char *s) {
    static const struct { const char *n; WORD b; } names[] = {
        {"Up", 0x0001}, {"Down", 0x0002}, {"Left", 0x0004}, {"Right", 0x0008}, {"Start", 0x0010},
        {"Back", 0x0020}, {"Select", 0x0020}, {"L3", 0x0040}, {"R3", 0x0080}, {"LB", 0x0100}, {"L1", 0x0100},
        {"RB", 0x0200}, {"R1", 0x0200}, {"A", 0x1000}, {"B", 0x2000}, {"X", 0x4000}, {"Y", 0x8000}};
    WORD bits = 0;
    char buf[128];
    strncpy(buf, s, sizeof buf - 1);
    buf[sizeof buf - 1] = 0;
    for (char *tok = strtok(buf, "+ "); tok; tok = strtok(NULL, "+ "))
        for (size_t i = 0; i < sizeof names / sizeof names[0]; i++)
            if (!_stricmp(tok, names[i].n)) bits |= names[i].b;
    return bits;
}

static void load_settings(void) {
    char ini[MAX_PATH], v[128];
    snprintf(ini, sizeof ini, "%sd5auto.ini", g_dir);
    GetPrivateProfileStringA("keys", "toggle_key", "F5", v, sizeof v, ini);
    g_key = key_code(v);
    GetPrivateProfileStringA("keys", "pad_combo", "L3+R3", v, sizeof v, ini);
    g_pad = pad_bits(v);
    GetPrivateProfileStringA("keys", "editor_key", "F6", v, sizeof v, ini);
    g_editor_key = key_code(v);
    g_test_anywhere = GetPrivateProfileIntA("debug", "test_anywhere", 0, ini);
    g_corner = GetPrivateProfileIntA("display", "corner", 1, ini);
    g_research = GetPrivateProfileIntA("debug", "research", 0, ini);
    g_deploy = GetPrivateProfileIntA("auto", "deploy", 1, ini);
    g_deploy_max = GetPrivateProfileIntA("auto", "deploy_max", 10, ini);
    g_stall_limit = GetPrivateProfileIntA("auto", "stall_limit", 8, ini);
    g_sp_saving = GetPrivateProfileIntA("tactics", "sp_saving", 1, ini);
    g_kill_margin = GetPrivateProfileIntA("tactics", "kill_margin", 150, ini);
    g_reach = GetPrivateProfileIntA("tactics", "reach", 10, ini);
    g_heal_below = GetPrivateProfileIntA("tactics", "heal_below", 50, ini);
    g_remote = GetPrivateProfileIntA("debug", "remote", 0, ini);
    g_live = GetPrivateProfileIntA("skills", "live_reload", 0, ini);
    g_battle_speed = GetPrivateProfileIntA("battle", "speed", 0, ini);
    g_feat_auto = D5_AUTO && GetPrivateProfileIntA("features", "autobattle", 1, ini);
    g_cc_enabled = GetPrivateProfileIntA("colors", "enabled", 0, ini);
    GetPrivateProfileStringA("colors", "key", "U", v, sizeof v, ini);
    g_cc_key = key_code(v);
    GetPrivateProfileStringA("colors", "pad", "R3", v, sizeof v, ini);
    g_cc_pad = pad_bits(v);
    logf_("settings: key=0x%X pad=0x%04X test_anywhere=%d corner=%d", g_key, g_pad, g_test_anywhere, g_corner);
}

/* --------------------------------------------------------------------------------------- state */
static volatile LONG g_active;     /* auto-battle on */
static int g_fought_floor;         /* since it was switched on, it has been on a battle floor */
static volatile LONG g_in_iw;      /* player is in the Item World (set by the game-state reader) */
static DWORD g_flash_until;        /* show "not available here" briefly */

/* ------------------------------------------------------------------------------- game state
 * Addresses are static VAs of the vanilla exe (image base 0x140000000); the game is loaded with ASLR,
 * so every access goes through G(va) = module base + (va - 0x140000000).  Found with probe_states.py:
 *   0x146a35e48 u8   Item World session active (1 on floors AND on the post-boss screen)
 *   0x144fda560 u8   a battle map is loaded (story battles, Item World floors)
 *   0x144fda561 u8   the map is a generated Item World floor
 *   0x144ffb101 u8   Item World flags (bit 0 floor, bits 2|3 set on the post-boss screen)
 *   0x14236c400 u8   Item World floor number (unverified)
 *   0x1415a5be0      battle actors: 256 x 0x1260; +0x08/+0x0c/+0x10 position (float x/height/z, panel = /12),
 *                    +0x1d0 non-null = live, +0x240 unit record
 *   unit record      +0xbc8 name (UTF-8), +0x2dfc u16 level, +0x2cc8 HP, +0x2cd0 SP, +0x2cd8 max HP,
 *                    +0x2ce0 max SP, +0x2ce8.. ATK DEF INT RES HIT SPD (i64), +0x2e04 class id,
 *                    +0x2e08 s16 AI pattern (-1 = player controlled)
 *   0x140ba88d0      128x128 u8 path grid [x][z] from the selected unit (steps; 0xfe blocked; 0xff unreachable)
 */
static unsigned char *g_base;
static SIZE_T g_image_size;

static void *G(unsigned long long va) { return g_base + (va - 0x140000000ULL); }
static int in_image(const void *p, SIZE_T n) {
    return (const unsigned char *)p >= g_base && (const unsigned char *)p + n <= g_base + g_image_size;
}
static unsigned char rd8(unsigned long long va) { return *(volatile unsigned char *)G(va); }

/* every hook this core installs, so core_shutdown can take all of them out again (hot reload) */
typedef struct { void **slot; void *orig; } SLOTHOOK;
static SLOTHOOK g_slots[32];
static int g_nslots;
typedef struct { unsigned long long va; unsigned char orig[16]; int n; } CODEHOOK;
static CODEHOOK g_codes[32];
static int g_ncodes;
static volatile LONG g_inflight;   /* threads inside a hook right now */
static volatile LONG g_reload;     /* harness asked for a reload */

#define VA_IW_SESSION 0x146a35e48ULL
#define VA_BATTLE_MAP 0x144fda560ULL
#define VA_IW_FLOOR_MAP 0x144fda561ULL
#define VA_IW_FLAGS 0x144ffb101ULL
#define VA_IW_FLOOR_NO 0x14236c400ULL
#define VA_ACTORS 0x1415a5be0ULL
#define ACTOR_SIZE 0x1260
#define ACTOR_COUNT 256

static int in_item_world(void) {
    if (g_test_anywhere) return 1;
    return rd8(VA_IW_SESSION) == 1;           /* floors, mystery rooms and the rest area after a boss */
}

/* after beating a floor boss: session still active, no battle map, post-boss bits set */
static int at_post_boss_screen(void) {
    return rd8(VA_IW_SESSION) == 1 && rd8(VA_BATTLE_MAP) == 0 && (rd8(VA_IW_FLAGS) & 0x0c) != 0;
}

typedef struct {
    int slot;
    const unsigned char *actor, *unit;
    float x, h, z;
    int px, pz;
    int cls, ai;
    long long level, hp, sp, hpmax, spmax, atk, def, intl, res, hit, spd;
    char name[48];
} UNIT;

static int read_units(UNIT *out, int max) {
    int n = 0;
    const unsigned char *tab = (const unsigned char *)G(VA_ACTORS);
    for (int i = 0; i < ACTOR_COUNT && n < max; i++) {
        const unsigned char *a = tab + (SIZE_T)i * ACTOR_SIZE;
        if (!*(void *const *)(a + 0x1d0)) continue;
        const unsigned char *u = *(const unsigned char *const *)(a + 0x240);
        if (!u || !in_image(u, 0x4750)) continue;
        UNIT *d = &out[n++];
        memset(d, 0, sizeof *d);
        d->slot = i;
        d->actor = a;
        d->unit = u;
        d->x = *(const float *)(a + 0x08);
        d->h = *(const float *)(a + 0x0c);
        d->z = *(const float *)(a + 0x10);
        d->px = (int)(d->x / 12.0f);
        d->pz = (int)(d->z / 12.0f);
        d->cls = *(const int *)(u + 0x2e04);
        d->ai = *(const short *)(u + 0x2e08);
        const long long *st = (const long long *)(u + 0x2cc0);
        d->level = *(const unsigned short *)(u + 0x2dfc);
        d->hp = st[1]; d->sp = st[2]; d->hpmax = st[3]; d->spmax = st[4];
        d->atk = st[5]; d->def = st[6]; d->intl = st[7]; d->res = st[8]; d->hit = st[9]; d->spd = st[10];
        memcpy(d->name, u + 0xbc8, sizeof d->name - 1);
        d->name[sizeof d->name - 1] = 0;
    }
    return n;
}

static void log_battlefield(const char *why) {
    if (!g_base) return;
    UNIT u[64];
    int n = read_units(u, 64);
    logf_("battlefield (%s): IW session=%d floor-map=%d battle-map=%d flags=0x%02X floor#=%d units=%d", why,
          rd8(VA_IW_SESSION), rd8(VA_IW_FLOOR_MAP), rd8(VA_BATTLE_MAP), rd8(VA_IW_FLAGS), rd8(VA_IW_FLOOR_NO), n);
    for (int i = 0; i < n; i++)
        logf_("  [%3d] %-6s %-20s class %5d lv %lld  HP %lld/%lld SP %lld/%lld  ATK %lld DEF %lld INT %lld RES %lld "
              "HIT %lld SPD %lld  panel (%d,%d) h %.1f  ai %d team %d f860 %d", u[i].slot,
              *(const int *)(u[i].actor + 0x1258) == 0 ? "ALLY" : "ENEMY", u[i].name,
              u[i].cls, u[i].level, u[i].hp, u[i].hpmax, u[i].sp, u[i].spmax, u[i].atk, u[i].def, u[i].intl,
              u[i].res, u[i].hit, u[i].spd, u[i].px, u[i].pz, u[i].h, u[i].ai,
              *(const int *)(u[i].actor + 0x1258), *(const int *)(u[i].actor + 0x860));
}

/* ------------------------------------------------------------------------------------ gamepad */
typedef struct { WORD wButtons; BYTE bLeftTrigger, bRightTrigger; SHORT sThumbLX, sThumbLY, sThumbRX, sThumbRY; } PAD;
typedef struct { DWORD dwPacketNumber; PAD Gamepad; } PADSTATE;
typedef DWORD(WINAPI *XInputGetState_t)(DWORD, PADSTATE *);
static XInputGetState_t pXInputGetState;

static WORD pad_buttons(void) {
    if (!pXInputGetState) {
        static int tried;
        if (tried) return 0;
        tried = 1;
        HMODULE x = LoadLibraryA("xinput1_4.dll");
        if (!x) x = LoadLibraryA("xinput9_1_0.dll");
        if (x) pXInputGetState = (XInputGetState_t)GetProcAddress(x, "XInputGetState");
        if (!pXInputGetState) return 0;
    }
    WORD all = 0;
    for (DWORD i = 0; i < 4; i++) {
        PADSTATE s;
        if (pXInputGetState(i, &s) == 0) all |= s.Gamepad.wButtons;
    }
    return all;
}

static int game_focused(void) {
    HWND w = GetForegroundWindow();
    DWORD pid = 0;
    if (w) GetWindowThreadProcessId(w, &pid);
    return pid == GetCurrentProcessId();
}

static void auto_reset(void);

static void poll_toggle(void) {
    static int key_was, pad_was;
    int key_now = 0, pad_now = 0;
    if (game_focused()) {
        key_now = (GetAsyncKeyState(g_key) & 0x8000) != 0;
        WORD b = pad_buttons();
        pad_now = g_pad && (b & g_pad) == g_pad;
    }
    if ((key_now && !key_was) || (pad_now && !pad_was)) {
        if (g_active) {
            InterlockedExchange(&g_active, 0);
            auto_reset();
            logf_("auto-battle OFF (hotkey)");
        } else if (in_item_world()) {
            auto_reset();
            InterlockedExchange(&g_active, 1);
            logf_("auto-battle ON (hotkey)");
            log_battlefield("switched on");
        } else {
            g_flash_until = GetTickCount() + 2000;
            logf_("hotkey pressed outside the Item World - ignored");
        }
    }
    key_was = key_now;
    pad_was = pad_now;
}


/* ============================================================================ virtual controller
 * The game reads the pad through its import table entry of XInputGetState (static VA 0x1408d5738).  We point
 * that entry at vpad_XInputGetState: it returns the real pad (if any) with our synthetic buttons added, so
 * auto-battle "presses buttons" exactly like a player.  g_vpad_buttons = buttons held this frame. */
#define VA_IAT_XINPUTGETSTATE 0x1408d5738ULL
#define VA_IAT_XINPUTGETCAPS 0x1408d5730ULL
static volatile WORD g_vpad_buttons;
static volatile LONG g_vpad_active;       /* report pad 0 as connected while auto-battle drives it */
static XInputGetState_t oXInputGetState;
typedef DWORD(WINAPI *XInputGetCaps_t)(DWORD, DWORD, void *);
static XInputGetCaps_t oXInputGetCaps;

static DWORD WINAPI vpad_XInputGetState(DWORD user, PADSTATE *st) {
    DWORD r = oXInputGetState ? oXInputGetState(user, st) : ERROR_DEVICE_NOT_CONNECTED;
    if (user == 0 && g_vpad_active) {
        static DWORD packet;
        if (r != 0) {
            memset(st, 0, sizeof *st);
            r = 0;
        }
        st->Gamepad.wButtons |= g_vpad_buttons;
        st->dwPacketNumber = ++packet;
    }
    return r;
}

static DWORD WINAPI vpad_XInputGetCaps(DWORD user, DWORD flags, void *caps) {
    DWORD r = oXInputGetCaps ? oXInputGetCaps(user, flags, caps) : ERROR_DEVICE_NOT_CONNECTED;
    if (user == 0 && g_vpad_active && r != 0) {
        memset(caps, 0, 20);
        ((BYTE *)caps)[0] = 1;   /* XINPUT_DEVTYPE_GAMEPAD */
        ((BYTE *)caps)[1] = 1;   /* XINPUT_DEVSUBTYPE_GAMEPAD */
        r = 0;
    }
    return r;
}

static void install_vpad(void) {
    void **slot = (void **)G(VA_IAT_XINPUTGETSTATE);
    void **cslot = (void **)G(VA_IAT_XINPUTGETCAPS);
    DWORD old;
    if (VirtualProtect(slot, 16, PAGE_READWRITE, &old)) {
        oXInputGetState = (XInputGetState_t)*slot;
        *slot = (void *)vpad_XInputGetState;
        oXInputGetCaps = (XInputGetCaps_t)*cslot;
        *cslot = (void *)vpad_XInputGetCaps;
        VirtualProtect(slot, 16, old, &old);
        logf_("vpad: XInputGetState hooked (orig %p), caps hooked (orig %p)", (void *)oXInputGetState,
              (void *)oXInputGetCaps);
    }
}

/* ------------------------------------------------------------------------------ virtual keyboard
 * SendInput from inside the game process (same integrity level, game window focused) -- the game sees these
 * exactly like the player's own key presses. */
static void key_event(WORD vk, int up) {
    INPUT in;
    memset(&in, 0, sizeof in);
    in.type = INPUT_KEYBOARD;
    UINT sc = MapVirtualKeyA(vk, MAPVK_VK_TO_VSC);
    int ext = (vk == VK_LEFT || vk == VK_RIGHT || vk == VK_UP || vk == VK_DOWN || vk == VK_INSERT ||
               vk == VK_DELETE || vk == VK_HOME || vk == VK_END || vk == VK_PRIOR || vk == VK_NEXT);
    in.ki.wVk = vk;
    in.ki.wScan = (WORD)sc;
    in.ki.dwFlags = KEYEVENTF_SCANCODE | (ext ? KEYEVENTF_EXTENDEDKEY : 0) | (up ? KEYEVENTF_KEYUP : 0);
    SendInput(1, &in, sizeof in);
}

/* --------------------------------------------------------------------- keyboard state hook
 * The game's input update calls GetKeyboardState (import at static VA 0x1408d5640).  Our replacement
 * returns the real state plus g_vkeys (keys auto-battle holds this frame); in research builds it also logs
 * every key the game sees going down, so we learn the player's bindings. */
#define VA_IAT_GETKEYBOARDSTATE 0x1408d5640ULL
typedef BOOL(WINAPI *GetKeyboardState_t)(PBYTE);
static GetKeyboardState_t oGetKeyboardState;
static volatile BYTE g_vkeys[256];
static volatile LONG g_kbd_calls;

static BOOL WINAPI hkGetKeyboardState(PBYTE ks) {
    BOOL r = oGetKeyboardState(ks);
    InterlockedIncrement(&g_kbd_calls);
    if (r) {
        for (int i = 1; i < 256; i++)
            if (g_vkeys[i]) ks[i] |= 0x80;
        if (g_research) {
            static BYTE was[256];
            for (int i = 1; i < 256; i++) {
                BYTE down = ks[i] & 0x80;
                if (down && !was[i] && i != VK_LBUTTON && i != VK_RBUTTON) {
                    char name[64] = "?";
                    UINT sc = MapVirtualKeyA(i, MAPVK_VK_TO_VSC);
                    GetKeyNameTextA((LONG)(sc << 16), name, sizeof name);
                    logf_("key seen by the game: VK 0x%02X (%s)%s", i, name, g_vkeys[i] ? " [injected]" : "");
                }
                was[i] = down;
            }
        }
    }
    return r;
}

static void install_kbd_hook(void) {
    void **slot = (void **)G(VA_IAT_GETKEYBOARDSTATE);
    DWORD old;
    if (VirtualProtect(slot, 8, PAGE_READWRITE, &old)) {
        oGetKeyboardState = (GetKeyboardState_t)*slot;
        *slot = (void *)hkGetKeyboardState;
        VirtualProtect(slot, 8, old, &old);
        logf_("kbd: GetKeyboardState hooked (orig %p)", (void *)oGetKeyboardState);
    }
}


static void patch_slot(void **slot, void *fn, void **orig);

/* -------------------------------------------------------------------------- DirectInput hook
 * The game reads the keyboard (and maybe the pad) through DirectInput 8.  We create our own DirectInput
 * keyboard device (A and W flavour) to find the dinput8 device vtable and redirect GetDeviceState (slot 9)
 * and GetDeviceData (slot 10).  Keyboard devices get g_dik[] (keys auto-battle holds, DIK codes) added:
 * as held state for GetDeviceState, as press / release events for GetDeviceData. */
typedef HRESULT(STDMETHODCALLTYPE *GetDeviceState_t)(void *, DWORD, LPVOID);
typedef HRESULT(STDMETHODCALLTYPE *GetDeviceData_t)(void *, DWORD, LPDIDEVICEOBJECTDATA, LPDWORD, DWORD);
typedef HRESULT(STDMETHODCALLTYPE *GetDeviceInfo_t)(void *, void *);
static GetDeviceState_t oGetDeviceStateA, oGetDeviceStateW;
static GetDeviceData_t oGetDeviceDataA, oGetDeviceDataW;
static volatile BYTE g_dik[256];            /* held by auto-battle this frame */
static BYTE g_dik_sent[256];                /* what the game was last told (for GetDeviceData events) */
static volatile LONG g_di_state_calls, g_di_data_calls;

static void log_dik(int dik, const char *how) {
    char name[64] = "?";
    GetKeyNameTextA((LONG)(((dik & 0x7f) << 16) | ((dik & 0x80) ? (1 << 24) : 0)), name, sizeof name);
    logf_("key seen by the game: DIK 0x%02X (%s) via %s", dik, name, how);
}

static void di_note_device(void *dev, DWORD cb, const char *api) {
    static void *seen[16];
    static int nseen;
    for (int i = 0; i < nseen; i++)
        if (seen[i] == dev) return;
    if (nseen < 16) seen[nseen++] = dev;
    logf_("dinput: game uses %s on device %p (size %lu)", api, dev, (unsigned long)cb);
}

static HRESULT di_state(GetDeviceState_t orig, void *self, DWORD cb, LPVOID data) {
    HRESULT r = orig(self, cb, data);
    InterlockedIncrement(&g_di_state_calls);
    if ((g_fake_focus || g_menu_open || g_cc_open) && cb == 256 && data) {   /* harness: only injected keys; editor: none */
        memset(data, 0, 256);
        r = DI_OK;
    }
    if (g_fake_focus && data && (cb == 16 || cb == 20)) {   /* harness: no mouse movement / buttons (DIMOUSESTATE[2]) */
        memset(data, 0, cb);
        r = DI_OK;
    }
    if (g_research) di_note_device(self, cb, "GetDeviceState");
    if (SUCCEEDED(r) && cb == 256) {            /* keyboard state: 256 DIK bytes */
        BYTE *k = (BYTE *)data;
        if (g_research) {
            static BYTE was[256];
            for (int i = 0; i < 256; i++) {
                if ((k[i] & 0x80) && !was[i]) log_dik(i, "GetDeviceState");
                was[i] = k[i] & 0x80;
            }
        }
        if (!g_menu_open && !g_cc_open)
            for (int i = 0; i < 256; i++)
                if (g_dik[i]) k[i] |= 0x80;
    }
    return r;
}
static HRESULT STDMETHODCALLTYPE hkGetDeviceStateA(void *s, DWORD cb, LPVOID d) { return di_state(oGetDeviceStateA, s, cb, d); }
static HRESULT STDMETHODCALLTYPE hkGetDeviceStateW(void *s, DWORD cb, LPVOID d) { return di_state(oGetDeviceStateW, s, cb, d); }

static int di_is_keyboard(void *self) {
    static void *kb[8], *other[8];
    static int nkb, nother;
    for (int i = 0; i < nkb; i++) if (kb[i] == self) return 1;
    for (int i = 0; i < nother; i++) if (other[i] == self) return 0;
    DIDEVICEINSTANCEA inst;
    memset(&inst, 0, sizeof inst);
    inst.dwSize = sizeof inst;
    GetDeviceInfo_t info = (GetDeviceInfo_t)((*(void ***)self)[15]);
    int is = SUCCEEDED(info(self, &inst)) && (inst.dwDevType & 0xff) == DI8DEVTYPE_KEYBOARD;
    if (is && nkb < 8) kb[nkb++] = self;
    if (!is && nother < 8) other[nother++] = self;
    return is;
}

static HRESULT di_data(GetDeviceData_t orig, void *self, DWORD cbo, LPDIDEVICEOBJECTDATA rg, LPDWORD inout,
                       DWORD flags) {
    DWORD cap = inout ? *inout : 0;
    HRESULT r = orig(self, cbo, rg, inout, flags);
    InterlockedIncrement(&g_di_data_calls);
    if ((g_fake_focus || g_menu_open || g_cc_open) && inout && rg && !(flags & DIGDD_PEEK) && di_is_keyboard(self)) {
        r = DI_OK;
        *inout = 0;
    }
    if (g_research) di_note_device(self, cbo, "GetDeviceData");
    if (FAILED(r) || !inout || !rg || (flags & DIGDD_PEEK) || cbo < sizeof(DIDEVICEOBJECTDATA_DX3)) return r;
    if (!di_is_keyboard(self)) return r;
    DWORD n = *inout;
    if (g_research)
        for (DWORD i = 0; i < n; i++) {
            DIDEVICEOBJECTDATA *e = (DIDEVICEOBJECTDATA *)((BYTE *)rg + i * cbo);
            if (e->dwData & 0x80) log_dik((int)e->dwOfs & 0xff, "GetDeviceData");
        }
    /* synthetic press / release events for keys whose injected state changed */
    for (int k = 0; k < 256 && n < cap; k++) {
        BYTE want = g_dik[k] && !g_cc_open ? 0x80 : 0;
        if (want == g_dik_sent[k]) continue;
        DIDEVICEOBJECTDATA *e = (DIDEVICEOBJECTDATA *)((BYTE *)rg + n * cbo);
        memset(e, 0, cbo);
        e->dwOfs = (DWORD)k;
        e->dwData = want;
        e->dwTimeStamp = GetTickCount();
        e->dwSequence = 0x7fffff00u + (DWORD)k;
        g_dik_sent[k] = want;
        n++;
    }
    *inout = n;
    return r == DI_BUFFEROVERFLOW ? r : DI_OK;
}
static HRESULT STDMETHODCALLTYPE hkGetDeviceDataA(void *s, DWORD c, LPDIDEVICEOBJECTDATA r, LPDWORD n, DWORD f) { return di_data(oGetDeviceDataA, s, c, r, n, f); }
static HRESULT STDMETHODCALLTYPE hkGetDeviceDataW(void *s, DWORD c, LPDIDEVICEOBJECTDATA r, LPDWORD n, DWORD f) { return di_data(oGetDeviceDataW, s, c, r, n, f); }

static const GUID d5_IID_IDirectInput8A = {0xBF798030, 0x483A, 0x4DA2, {0xAA, 0x99, 0x5D, 0x64, 0xED, 0x36, 0x97, 0x00}};
static const GUID d5_IID_IDirectInput8W = {0xBF798031, 0x483A, 0x4DA2, {0xAA, 0x99, 0x5D, 0x64, 0xED, 0x36, 0x97, 0x00}};
static const GUID d5_GUID_SysKeyboard = {0x6F1D2B61, 0xD5A0, 0x11CF, {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}};
typedef HRESULT(WINAPI *DirectInput8Create_t)(HINSTANCE, DWORD, REFIID, LPVOID *, LPUNKNOWN);

static void hook_device_vtable(void *dev, int wide) {
    void **vt = *(void ***)dev;
    if (wide) {
        patch_slot(&vt[9], (void *)hkGetDeviceStateW, (void **)&oGetDeviceStateW);
        patch_slot(&vt[10], (void *)hkGetDeviceDataW, (void **)&oGetDeviceDataW);
    } else {
        patch_slot(&vt[9], (void *)hkGetDeviceStateA, (void **)&oGetDeviceStateA);
        patch_slot(&vt[10], (void *)hkGetDeviceDataA, (void **)&oGetDeviceDataA);
    }
}

static void install_dinput_hook(void) {
    HMODULE m = LoadLibraryA("dinput8.dll");
    DirectInput8Create_t create = m ? (DirectInput8Create_t)GetProcAddress(m, "DirectInput8Create") : NULL;
    if (!create) { logf_("dinput: dinput8.dll not available"); return; }
    for (int wide = 0; wide < 2; wide++) {
        void *di = NULL, *dev = NULL;
        if (FAILED(create(GetModuleHandleA(NULL), DIRECTINPUT_VERSION, wide ? &d5_IID_IDirectInput8W : &d5_IID_IDirectInput8A,
                          &di, NULL)) || !di) continue;
        typedef HRESULT(STDMETHODCALLTYPE *CreateDevice_t)(void *, REFGUID, void **, LPUNKNOWN);
        CreateDevice_t cd = (CreateDevice_t)((*(void ***)di)[3]);
        if (SUCCEEDED(cd(di, &d5_GUID_SysKeyboard, &dev, NULL)) && dev) {
            void **vt = *(void ***)dev;
            /* the A and W devices may share one vtable: hook it once */
            if (wide && (vt[9] == (void *)hkGetDeviceStateA)) {
                logf_("dinput: W device shares the A vtable");
            } else {
                hook_device_vtable(dev, wide);
                logf_("dinput: %s device vtable hooked", wide ? "W" : "A");
            }
            ((ULONG(STDMETHODCALLTYPE *)(void *))((*(void ***)dev)[2]))(dev);
        }
        ((ULONG(STDMETHODCALLTYPE *)(void *))((*(void ***)di)[2]))(di);
    }
}

/* input test (research): F8 = hold D and RIGHT (keyboard state) + pad D-pad RIGHT for 6 frames */
static void vpad_test_tick(void) {
    static int key_was, frame = -1;
    int key = game_focused() && (GetAsyncKeyState(VK_F8) & 0x8000);
    if (key && !key_was && frame < 0) {
        frame = 0;
        InterlockedExchange(&g_vpad_active, 1);
        logf_("input test: D + RIGHT held in the game's keyboard state, pad D-pad RIGHT (GetKeyboardState "
              "calls so far: %ld, DirectInput state/data calls: %ld/%ld)", (long)g_kbd_calls,
              (long)g_di_state_calls, (long)g_di_data_calls);
    }
    key_was = key;
    if (frame >= 0) {
        g_vpad_buttons = (frame < 6) ? 0x0008 : 0;
        g_vkeys['D'] = g_vkeys[VK_RIGHT] = (frame < 6);
        g_dik[DIK_D] = g_dik[DIK_RIGHT] = (frame < 6);
        if (++frame > 30) {
            frame = -1;
            g_vpad_buttons = 0;
            if (!g_active) InterlockedExchange(&g_vpad_active, 0);
            logf_("vpad test done");
        }
    }
}

/* ============================================================================== watchpoint tracer
 * Research only: debug registers DR0-3 of every game thread watch four addresses; the vectored
 * exception handler logs each distinct instruction that touched them with a call stack (unwound with the
 * exe's .pdata) and the argument registers.  Addresses are logged as static VAs (0x14xxxxxxx). */
typedef struct { unsigned long long addr; int len; int rw; const char *what; int raw; } WATCH;  /* rw: 1 write, 3 read/write; raw: runtime address */
static char g_watch_names[4][48];
static WATCH g_watch[4];
static int g_nwatch;
static volatile LONG g_trace_hits;
static PVOID g_veh;
#define MAX_SEEN 256
static unsigned long long g_seen[MAX_SEEN];
static int g_nseen;

static unsigned long long to_static(DWORD64 a) {
    if (a >= (DWORD64)g_base && a < (DWORD64)g_base + g_image_size) return a - (DWORD64)g_base + 0x140000000ULL;
    return a;
}

static LONG CALLBACK trace_veh(EXCEPTION_POINTERS *ep) {
    if (ep->ExceptionRecord->ExceptionCode != EXCEPTION_SINGLE_STEP) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT *c = ep->ContextRecord;
    DWORD64 dr6 = c->Dr6;
    if (!(dr6 & 0xf)) return EXCEPTION_CONTINUE_SEARCH;
    c->Dr6 = 0;
    c->EFlags |= 0x10000;        /* RF: an execution breakpoint must not fire again on the same instruction */
    for (int w = 0; w < 4; w++) {
        if (!(dr6 & (1ull << w)) || w >= g_nwatch) continue;
        unsigned long long key = ((unsigned long long)w << 60) ^ to_static(c->Rip);
        int seen = 0;
        for (int i = 0; i < g_nseen; i++)
            if (g_seen[i] == key) { seen = 1; break; }
        InterlockedIncrement(&g_trace_hits);
        if (g_watch[w].rw == 0) {            /* execution watch: every call with its arguments + caller chain */
            static volatile LONG calls;
            if (InterlockedIncrement(&calls) <= 4000) {
                char stack[400];
                int n = 0;
                CONTEXT u = *c;
                u.Rip = *(DWORD64 *)c->Rsp;          /* at function entry: return address is on top */
                u.Rsp += 8;
                n += snprintf(stack + n, sizeof stack - n, " %llx", to_static(u.Rip));
                for (int f = 0; f < 10 && n < (int)sizeof stack - 24; f++) {
                    DWORD64 img = 0;
                    PRUNTIME_FUNCTION fn = RtlLookupFunctionEntry(u.Rip, &img, NULL);
                    if (!fn) break;
                    void *hd;
                    DWORD64 ef;
                    RtlVirtualUnwind(UNW_FLAG_NHANDLER, img, u.Rip, fn, &u, &hd, &ef, NULL);
                    if (!u.Rip) break;
                    n += snprintf(stack + n, sizeof stack - n, " %llx", to_static(u.Rip));
                }
                logf_("CALL %s: rcx=%llx rdx=%llx r8=%llx r9=%llx |%s", g_watch[w].what, to_static(c->Rcx),
                      (unsigned long long)c->Rdx, (unsigned long long)c->R8, (unsigned long long)c->R9, stack);
            }
            continue;
        }
        if (seen || g_nseen >= MAX_SEEN) continue;
        g_seen[g_nseen++] = key;
        char stack[640];
        int n = 0;
        CONTEXT u = *c;
        for (int f = 0; f < 24 && n < (int)sizeof stack - 24; f++) {
            DWORD64 img = 0;
            PRUNTIME_FUNCTION fn = RtlLookupFunctionEntry(u.Rip, &img, NULL);
            if (!fn) {
                if (!u.Rsp) break;
                u.Rip = *(DWORD64 *)u.Rsp;
                u.Rsp += 8;
            } else {
                void *hd;
                DWORD64 ef;
                RtlVirtualUnwind(UNW_FLAG_NHANDLER, img, u.Rip, fn, &u, &hd, &ef, NULL);
            }
            if (!u.Rip) break;
            n += snprintf(stack + n, sizeof stack - n, " %llx", to_static(u.Rip));
        }
        logf_("TRACE %s: at %llx  rcx=%llx rdx=%llx r8=%llx r9=%llx rbx=%llx rsi=%llx rdi=%llx | stack:%s",
              g_watch[w].what, to_static(c->Rip), to_static(c->Rcx), to_static(c->Rdx), to_static(c->R8),
              to_static(c->R9), to_static(c->Rbx), to_static(c->Rsi), to_static(c->Rdi), stack);
    }
    return EXCEPTION_CONTINUE_EXECUTION;
}

/* research: log the first access violations (registers, stack, call chain) before the game dies */
static PVOID g_crash_veh;
static volatile LONG g_crash_logged;
static LONG CALLBACK crash_veh(EXCEPTION_POINTERS *ep) {
    if (ep->ExceptionRecord->ExceptionCode != EXCEPTION_ACCESS_VIOLATION) return EXCEPTION_CONTINUE_SEARCH;
    if (InterlockedIncrement(&g_crash_logged) > 3) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT *c = ep->ContextRecord;
    char stack[640];
    int n = 0;
    CONTEXT u = *c;
    for (int f = 0; f < 24 && n < (int)sizeof stack - 24; f++) {
        DWORD64 img = 0;
        PRUNTIME_FUNCTION fn = RtlLookupFunctionEntry(u.Rip, &img, NULL);
        if (!fn) {
            if (!u.Rsp) break;
            u.Rip = *(DWORD64 *)u.Rsp;
            u.Rsp += 8;
        } else {
            void *hd;
            DWORD64 ef;
            RtlVirtualUnwind(UNW_FLAG_NHANDLER, img, u.Rip, fn, &u, &hd, &ef, NULL);
        }
        if (!u.Rip) break;
        n += snprintf(stack + n, sizeof stack - n, " %llx", to_static(u.Rip));
    }
    logf_("CRASH at %llx addr=%llx | rax=%llx rbx=%llx rcx=%llx rdx=%llx rsi=%llx rdi=%llx rbp=%llx",
          to_static(c->Rip), (unsigned long long)ep->ExceptionRecord->ExceptionInformation[1], c->Rax, c->Rbx, c->Rcx,
          c->Rdx, c->Rsi, c->Rdi, c->Rbp);
    logf_("CRASH   r8=%llx r9=%llx r10=%llx r11=%llx r12=%llx r13=%llx r14=%llx r15=%llx rsp=%llx | stack:%s",
          c->R8, c->R9, c->R10, c->R11, c->R12, c->R13, c->R14, c->R15, c->Rsp, stack);
    return EXCEPTION_CONTINUE_SEARCH;
}

static DWORD WINAPI arm_thread(LPVOID p) {
    DWORD self = GetCurrentThreadId(), pid = GetCurrentProcessId();
    int armed = 0;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    THREADENTRY32 te;
    te.dwSize = sizeof te;
    for (BOOL ok = Thread32First(snap, &te); ok; ok = Thread32Next(snap, &te)) {
        if (te.th32OwnerProcessID != pid || te.th32ThreadID == self) continue;
        HANDLE th = OpenThread(THREAD_GET_CONTEXT | THREAD_SET_CONTEXT | THREAD_SUSPEND_RESUME, FALSE, te.th32ThreadID);
        if (!th) continue;
        if (SuspendThread(th) != (DWORD)-1) {
            CONTEXT c;
            memset(&c, 0, sizeof c);
            c.ContextFlags = CONTEXT_DEBUG_REGISTERS;
            if (GetThreadContext(th, &c)) {
                DWORD64 dr7 = 0;
                DWORD64 *dr[4] = {&c.Dr0, &c.Dr1, &c.Dr2, &c.Dr3};
                for (int w = 0; w < 4; w++) {
                    *dr[w] = 0;
                    if (w >= g_nwatch || !p) continue;
                    *dr[w] = g_watch[w].raw ? (DWORD64)g_watch[w].addr : (DWORD64)G(g_watch[w].addr);
                    int len = g_watch[w].len == 8 ? 2 : g_watch[w].len == 4 ? 3 : g_watch[w].len == 2 ? 1 : 0;
                    dr7 |= (1ull << (w * 2)) | ((DWORD64)g_watch[w].rw << (16 + w * 4)) | ((DWORD64)len << (18 + w * 4));
                }
                c.Dr7 = dr7;
                c.Dr6 = 0;
                if (SetThreadContext(th, &c)) armed++;
            }
            ResumeThread(th);
        }
        CloseHandle(th);
    }
    CloseHandle(snap);
    logf_("trace: %s on %d thread(s)", p ? "armed" : "disarmed", armed);
    return 0;
}

static void trace_tick(void) {
    static int key_was, armed;
    int key = game_focused() && (GetAsyncKeyState(VK_F7) & 0x8000);
    if (key && !key_was) {
        char wf[MAX_PATH];
        snprintf(wf, sizeof wf, "%sd5auto_watch.txt", g_dir);
        FILE *f = armed ? NULL : fopen(wf, "r");
        if (f) {
            /* addresses handed over by probe_menus.py: "0xADDR size label" (runtime addresses) */
            char line[256];
            g_nwatch = 0;
            g_nseen = 0;
            while (g_nwatch < 4 && fgets(line, sizeof line, f)) {
                unsigned long long a = 0;
                int sz = 4;
                char lab[40] = "watch";
                if (sscanf(line, "%llx %d %39s", &a, &sz, lab) >= 1 && a) {
                    snprintf(g_watch_names[g_nwatch], sizeof g_watch_names[0], "%s#%d write", lab, g_nwatch);
                    g_watch[g_nwatch] = (WATCH){a & ~(unsigned long long)(sz - 1), sz == 1 || sz == 2 || sz == 4 ? sz : 4,
                                                1, g_watch_names[g_nwatch], 1};
                    /* the object around it, for the layout */
                    const unsigned char *pa = (const unsigned char *)(a & ~15ULL);
                    MEMORY_BASIC_INFORMATION mbi;
                    if (VirtualQuery(pa - 0x100, &mbi, sizeof mbi) && mbi.State == MEM_COMMIT) {
                        logf_("watch %d at %llx (%d bytes) - memory around it:", g_nwatch, a, sz);
                        for (int o = -0x100; o < 0x40; o += 16) {
                            const unsigned long long *q = (const unsigned long long *)(pa + o);
                            logf_("   %+5d  %016llx %016llx", o, to_static(q[0]), to_static(q[1]));
                        }
                    }
                    g_nwatch++;
                }
            }
            fclose(f);
            remove(wf);
            if (g_nwatch) {
                if (!g_veh) g_veh = AddVectoredExceptionHandler(1, trace_veh);
                CloseHandle(CreateThread(NULL, 0, arm_thread, (LPVOID)1, 0, NULL));
                armed = 1;
                logf_("trace: watching %d address(es) from d5auto_watch.txt", g_nwatch);
            }
        } else if (!armed) {
            UNIT u[64];
            int n = read_units(u, 64);
            /* the two enemies farthest from your units (alive in the enemy turn, they have to walk) and
               the HP of your first two units (enemies attack them) */
            int e1 = -1, e2 = -1, a1 = -1, a2 = -1;
            float d1 = -1, d2 = -1;
            for (int i = 0; i < n; i++) {
                if (u[i].ai < 0) {
                    if (a1 < 0) a1 = i; else if (a2 < 0) a2 = i;
                    continue;
                }
                float best = 1e9f;
                for (int j = 0; j < n; j++)
                    if (u[j].ai < 0) {
                        float dx = u[i].x - u[j].x, dz = u[i].z - u[j].z, d = dx * dx + dz * dz;
                        if (d < best) best = d;
                    }
                if (best > d1) { e2 = e1; d2 = d1; e1 = i; d1 = best; }
                else if (best > d2) { e2 = i; d2 = best; }
            }
            if (a1 < 0 || e1 < 0) {
                logf_("trace: need at least one deployed ally and one enemy on the map");
            } else {
                g_nwatch = 0;
                g_nseen = 0;
                /* the AI deciding: BFS from the enemy (its own path-grid cell is written), its planned route
                   (actor+0x418) is written; plus an ally's HP (the attack it chose) */
                int gx = u[e1].px, gz = u[e1].pz;
                if (gx >= 0 && gx < 128 && gz >= 0 && gz < 128)
                    g_watch[g_nwatch++] = (WATCH){0x140ba88d0ULL + (unsigned long long)gx * 128 + gz, 1, 1, "path grid (enemy cell) write"};
                g_watch[g_nwatch++] = (WATCH){to_static((DWORD64)u[e1].actor) + 0x418, 4, 1, "enemy route write"};
                if (e2 >= 0)
                    g_watch[g_nwatch++] = (WATCH){to_static((DWORD64)u[e2].actor) + 0x418, 4, 1, "enemy2 route write"};
                g_watch[g_nwatch++] = (WATCH){to_static((DWORD64)u[a1].unit) + 0x2cc8, 8, 1, "ally HP write"};
                logf_("trace: watching the AI of %s (path grid + route)%s%s and %s's HP", u[e1].name,
                      e2 >= 0 ? ", route of " : "", e2 >= 0 ? u[e2].name : "", u[a1].name);
                if (!g_veh) g_veh = AddVectoredExceptionHandler(1, trace_veh);
                CloseHandle(CreateThread(NULL, 0, arm_thread, (LPVOID)1, 0, NULL));
                armed = 1;
            }
        } else {
            CloseHandle(CreateThread(NULL, 0, arm_thread, NULL, 0, NULL));
            armed = 0;
            logf_("trace: stopped (%ld hits)", (long)g_trace_hits);
        }
    }
    key_was = key;
}



static void trace_shutdown(void) {
    if (!g_veh) return;
    HANDLE t = CreateThread(NULL, 0, arm_thread, NULL, 0, NULL);   /* clear DR0-3 on every thread */
    if (t) { WaitForSingleObject(t, 2000); CloseHandle(t); }
    RemoveVectoredExceptionHandler(g_veh);
    g_veh = NULL;
}

/* ============================================================================== auto-battle core
 * The game's enemy-turn AI (state machine 0x1405fe010, manager object passed in rcx) picks the next AI
 * team in 0x1405fc6e0: it loops teams 1..5 over the "team done" bytes manager+0x135.. and hands the first
 * team with living units to the AI (manager+0x130).  Team 0 (the player) has its own done byte at +0x134
 * (zeroed with the others at the start of every AI phase, set by  mov byte [rax+rsi+0x134],1).  While
 * auto-battle is on we start that loop at team 0 -- the game's own AI plays the player's units first,
 * then the enemies take their normal turn.  Auto-battle itself only presses End Turn (key 2). */
#define VA_PICK_RDI 0x1405fc774ULL   /* lea rdi, [rsi+0x135]  ->  lea rdi, [rsi+0x134] */
#define VA_PICK_EBX 0x1405fc7a5ULL   /* lea ebx, [r13+2]      ->  lea ebx, [r13+1]  (r13 = -1) */
#define VA_SCENE_MODE 0x146a3aea0ULL /* 2 = player turn, 6 = AI turns */
static const unsigned char PICK_RDI_ORIG[7] = {0x48, 0x8d, 0xbe, 0x35, 0x01, 0x00, 0x00};
static const unsigned char PICK_EBX_ORIG[4] = {0x41, 0x8d, 0x5d, 0x02};
static int g_team0_ai;               /* code patch applied */
static const char *g_status = "";    /* shown in the indicator */

static int write_code(unsigned long long va, const unsigned char *bytes, int n) {
    unsigned char *p = (unsigned char *)G(va);
    int known = 0;
    for (int i = 0; i < g_ncodes; i++)
        if (g_codes[i].va == va) known = 1;
    if (!known && g_ncodes < 32 && n <= 16) {        /* the original bytes, for core_shutdown */
        g_codes[g_ncodes].va = va;
        g_codes[g_ncodes].n = n;
        memcpy(g_codes[g_ncodes].orig, p, n);
        g_ncodes++;
    }
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return 0;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return 1;
}

static void set_team0_ai(int on) {
    if (on == g_team0_ai) return;
    unsigned char *a = (unsigned char *)G(VA_PICK_RDI), *b = (unsigned char *)G(VA_PICK_EBX);
    if (on) {
        if (memcmp(a, PICK_RDI_ORIG, 7) || memcmp(b, PICK_EBX_ORIG, 4)) {
            logf_("auto: AI team-picker code not as expected - cannot hand your units to the AI");
            return;
        }
        unsigned char ra[7], rb[4];
        memcpy(ra, PICK_RDI_ORIG, 7);
        memcpy(rb, PICK_EBX_ORIG, 4);
        ra[3] = 0x34;
        rb[3] = 0x01;
        write_code(VA_PICK_RDI, ra, 7);
        write_code(VA_PICK_EBX, rb, 4);
    } else {
        write_code(VA_PICK_RDI, PICK_RDI_ORIG, 7);
        write_code(VA_PICK_EBX, PICK_EBX_ORIG, 4);
    }
    g_team0_ai = on;
    logf_("auto: your units are %s", on ? "played by the game's AI" : "back under your control");
}

/* key presses: a short queue of (DIK, frames to hold, frames to wait after) */
typedef struct { BYTE dik; int hold, gap; } KEYSTEP;
static KEYSTEP g_keyq[16];
static int g_keyq_n, g_keyq_i, g_key_t;

static void press(BYTE dik, int hold, int gap) {
    if (g_keyq_n < 16) g_keyq[g_keyq_n++] = (KEYSTEP){dik, hold, gap};
}

static int keys_busy(void) { return g_keyq_i < g_keyq_n; }

static void keys_tick(void) {
    if (!keys_busy()) {
        g_keyq_n = g_keyq_i = g_key_t = 0;
        return;
    }
    KEYSTEP *k = &g_keyq[g_keyq_i];
    g_dik[k->dik] = g_key_t < k->hold;
    if (++g_key_t >= k->hold + k->gap) {
        g_dik[k->dik] = 0;
        g_keyq_i++;
        g_key_t = 0;
    }
}

static void keys_clear(void) {
    for (int i = 0; i < g_keyq_n; i++) g_dik[g_keyq[i].dik] = 0;
    g_keyq_n = g_keyq_i = g_key_t = 0;
}

/* the player's units get an AI profile like a normal enemy while auto-battle is on (restored when off):
   unit+0x2e08 AI pattern (-1 = none), actor+0x860 (enemies 2/3/7, player 0) */
typedef struct { unsigned char *unit, *actor; short ai; int f860; } AIPROF;
static AIPROF g_prof[32];
static int g_nprof;
static int g_ai_pattern = 1, g_ai_f860 = 2;

static int di_unit_uses_ai(const UNIT *u);
static int g_di_on;
static void profiles_apply(const UNIT *u, int n) {
    for (int i = 0; i < n; i++) {
        if (*(const int *)(u[i].actor + 0x1258) != 0) continue;
        if (g_di_on && !di_unit_uses_ai(&u[i])) continue;   /* D.I. units act in the player phase */
        int known = 0;
        for (int k = 0; k < g_nprof; k++)
            if (g_prof[k].unit == u[i].unit) { known = 1; break; }
        if (!known && g_nprof < 32) {
            AIPROF *p = &g_prof[g_nprof++];
            p->unit = (unsigned char *)u[i].unit;
            p->actor = (unsigned char *)u[i].actor;
            p->ai = *(short *)(p->unit + 0x2e08);
            p->f860 = *(int *)(p->actor + 0x860);
            logf_("auto: %s gets an AI profile (pattern %d, f860 %d; was %d/%d)", u[i].name, g_ai_pattern, g_ai_f860,
                  p->ai, p->f860);
        }
        *(short *)(u[i].unit + 0x2e08) = (short)g_ai_pattern;
        *(int *)((unsigned char *)u[i].actor + 0x860) = g_ai_f860;
    }
}

static void profiles_restore(void) {
    for (int k = 0; k < g_nprof; k++) {
        /* only if the record still belongs to that unit (a floor change reuses the slots) */
        if (*(short *)(g_prof[k].unit + 0x2e08) == g_ai_pattern) *(short *)(g_prof[k].unit + 0x2e08) = g_prof[k].ai;
        if (*(int *)(g_prof[k].actor + 0x860) == g_ai_f860) *(int *)(g_prof[k].actor + 0x860) = g_prof[k].f860;
    }
    if (g_nprof) logf_("auto: AI profiles of %d unit(s) restored", g_nprof);
    g_nprof = 0;
}

/* detour at the AI team-selection state (0x1405fc6e0: push rsi / push r14 / sub rsp,0x48) that stores
   the AI manager pointer (rcx) for diagnostics: manager+0x130 current team, +0x134.. team done bytes */
#define VA_TEAMSEL 0x1405fc6e0ULL
static const unsigned char TEAMSEL_ORIG[8] = {0x40, 0x56, 0x41, 0x56, 0x48, 0x83, 0xec, 0x48};
static unsigned char *volatile *g_mgr_slot;

/* "your team first": the picker keeps the LAST team that has units (mov [rsi+0x130],ebx at 0x1405fc812 and
   the loop goes on).  While auto-battle is on, that store jumps to a stub that also leaves the loop
   (0x1405fc822), so the first team with units -- team 0 -- is picked first. */
#define VA_PICK_STORE 0x1405fc812ULL
#define VA_PICK_DONE 0x1405fc822ULL
static const unsigned char PICK_STORE_ORIG[6] = {0x89, 0x9e, 0x30, 0x01, 0x00, 0x00};
static unsigned char *g_tramp;          /* near-image RWX page (detours) */
static unsigned char g_pick_jmp[6];
static int g_first_ready;

static unsigned char *near_page(void) {
    if (g_tramp) return g_tramp;
    for (unsigned long long d = 0x10000; d < 0x70000000ULL && !g_tramp; d += 0x10000)
        g_tramp = (unsigned char *)VirtualAlloc(g_base - d, 0x1000, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
    return g_tramp;
}

static void prepare_first_pick(void) {
    unsigned char *site = (unsigned char *)G(VA_PICK_STORE);
    unsigned char *pg = near_page();
    if (!pg || memcmp(site, PICK_STORE_ORIG, 6)) { logf_("auto: team-pick store not as expected"); return; }
    unsigned char *t = pg + 0x100;
    memcpy(t, PICK_STORE_ORIG, 6);                     /* mov [rsi+0x130], ebx */
    t[6] = 0xe9;
    *(int *)(t + 7) = (int)((unsigned char *)G(VA_PICK_DONE) - (t + 11));
    g_pick_jmp[0] = 0xe9;
    *(int *)(g_pick_jmp + 1) = (int)(t - (site + 5));
    g_pick_jmp[5] = 0x90;
    g_first_ready = 1;
}

static void set_first_pick(int on) {
    static int state;
    if (!g_first_ready || on == state) return;
    write_code(VA_PICK_STORE, on ? g_pick_jmp : PICK_STORE_ORIG, 6);
    state = on;
}

static int readable(const void *p, SIZE_T n) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!p || !VirtualQuery(p, &mbi, sizeof mbi)) return 0;
    if (mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return 0;
    return (const unsigned char *)p + n <= (const unsigned char *)mbi.BaseAddress + mbi.RegionSize;
}

#include "d5ui.inc.c"

static void install_mgr_detour(void) {
    unsigned char *site = (unsigned char *)G(VA_TEAMSEL);
    if (memcmp(site, TEAMSEL_ORIG, 8)) { logf_("auto: team-selection code not as expected (no diagnostics)"); return; }
    unsigned char *tr = near_page();
    if (!tr) { logf_("auto: no memory near the game for the detour"); return; }
    unsigned char *data = tr + 0x80;
    int n = 0;
    /* mov [rip+disp], rcx */
    tr[n++] = 0x48; tr[n++] = 0x89; tr[n++] = 0x0d;
    *(int *)(tr + n) = (int)(data - (tr + n + 4)); n += 4;
    memcpy(tr + n, TEAMSEL_ORIG, 8); n += 8;               /* push rsi; push r14; sub rsp,0x48 */
    tr[n++] = 0xe9;
    *(int *)(tr + n) = (int)((site + 8) - (tr + n + 4)); n += 4;
    g_mgr_slot = (unsigned char *volatile *)data;
    unsigned char j[8] = {0xe9, 0, 0, 0, 0, 0x90, 0x90, 0x90};
    *(int *)(j + 1) = (int)(tr - (site + 5));
    write_code(VA_TEAMSEL, j, 8);
    logf_("auto: AI manager detour installed");
}

static void log_ai_manager(void) {
    static int last_team = -99;
    unsigned char *m = g_mgr_slot ? *g_mgr_slot : NULL;
    /* only during the AI phase, and only while the manager's memory is still there */
    if (!m || *(volatile int *)G(VA_SCENE_MODE) != 6 || !readable(m, 0x140)) return;
    int team = *(int *)(m + 0x130);
    if (team != last_team) {
        logf_("auto: AI manager %p picks team %d  (done flags %d %d %d %d %d %d)", (void *)m, team, m[0x134], m[0x135],
              m[0x136], m[0x137], m[0x138], m[0x139]);
        last_team = team;
    }
}


/* ============================================================================ floor automation
 * Cursor = the actor at 0x142349160 (+0x08 x, +0x10 z; panel = /12).  Base panel = (0x144fda574, 0x144fda578),
 * Item World gate = (0x144fda57c, 0x144fda580).  Keys (the player's bindings): WASD cursor, K confirm, L cancel. */
#define VA_CURSOR 0x142349160ULL
#define VA_BASE_X 0x144fda574ULL
#define VA_GATE_X 0x144fda57cULL
#define VA_PATHGRID 0x140ba88d0ULL
static const BYTE DIR_KEYS[4] = {DIK_W, DIK_A, DIK_S, DIK_D};
static int g_dir_dx[4], g_dir_dz[4];

static void cursor_panel(int *x, int *z) {
    const unsigned char *c = (const unsigned char *)G(VA_CURSOR);
    *x = (int)(*(const float *)(c + 0x08) / 12.0f);
    *z = (int)(*(const float *)(c + 0x10) / 12.0f);
}

static void base_panel(int *x, int *z) {
    *x = (int)(*(const float *)G(VA_BASE_X) / 12.0f);
    *z = (int)(*(const float *)G(VA_BASE_X + 4) / 12.0f);
}

static unsigned char grid_at(int x, int z) {
    if (x < 0 || z < 0 || x > 127 || z > 127) return 0xff;
    return *((const unsigned char *)G(VA_PATHGRID) + x * 128 + z);
}

#if D5_AUTO
#include "d5pilot.inc.c"
#include "d5di.inc.c"
#include "d5menu.inc.c"
#else
#include "d5noauto.inc.c"
#endif
#include "d5color.inc.c"
#include "d5rows.inc.c"
#include "d5looks.inc.c"

/* ============================================================================ AI-ally experiment
 * Research: F6 cycles  off -> A (your deployed units get AI pattern 1, like a normal enemy)
 *                      -> B (A + actor+0x860 = 2, the value enemies have) -> off (everything restored).
 * Team (actor+0x1258: 0 you, 1 enemy) is never touched.  Question: does the game's own AI then play them? */
typedef struct { unsigned char *unit, *actor; short ai; int f860; } AISAVE;
static AISAVE g_aisave[32];
static int g_naisave, g_aimode;

static void ai_restore(void) {
    for (int i = 0; i < g_naisave; i++) {
        *(short *)(g_aisave[i].unit + 0x2e08) = g_aisave[i].ai;
        *(int *)(g_aisave[i].actor + 0x860) = g_aisave[i].f860;
    }
    logf_("AI experiment: restored %d unit(s)", g_naisave);
    g_naisave = 0;
}

static void ai_experiment_tick(void) {
    static int key_was;
    int key = game_focused() && (GetAsyncKeyState(VK_F6) & 0x8000);
    if (key && !key_was) {
        if (g_aimode == 2) {
            ai_restore();
            g_aimode = 0;
        } else {
            if (g_aimode == 0) {
                UNIT u[64];
                int n = read_units(u, 64);
                g_naisave = 0;
                for (int i = 0; i < n && g_naisave < 32; i++) {
                    if (u[i].ai >= 0 || *(const int *)(u[i].actor + 0x1258) != 0) continue;
                    AISAVE *sv = &g_aisave[g_naisave++];
                    sv->unit = (unsigned char *)u[i].unit;
                    sv->actor = (unsigned char *)u[i].actor;
                    sv->ai = *(short *)(sv->unit + 0x2e08);
                    sv->f860 = *(int *)(sv->actor + 0x860);
                }
            }
            g_aimode++;
            for (int i = 0; i < g_naisave; i++) {
                *(short *)(g_aisave[i].unit + 0x2e08) = 1;
                if (g_aimode == 2) *(int *)(g_aisave[i].actor + 0x860) = 2;
            }
            logf_("AI experiment: mode %c on %d unit(s)%s", g_aimode == 1 ? 'A' : 'B', g_naisave,
                  g_aimode == 1 ? " (AI pattern 1)" : " (AI pattern 1 + actor+0x860=2)");
            log_battlefield("AI experiment");
        }
    }
    key_was = key;
}

#include "d5live.inc.c"
#include "d5ctl.inc.c"
#include "d5fx.inc.c"

/* ------------------------------------------------------------------------------ 5x7 bitmap font */
static const struct { char c; unsigned char rows[7]; } FONT[] = {
    {'A', {0x0E,0x11,0x11,0x1F,0x11,0x11,0x11}}, {'B', {0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E}},
    {'C', {0x0E,0x11,0x10,0x10,0x10,0x11,0x0E}}, {'D', {0x1E,0x11,0x11,0x11,0x11,0x11,0x1E}},
    {'E', {0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F}}, {'F', {0x1F,0x10,0x10,0x1E,0x10,0x10,0x10}},
    {'G', {0x0E,0x11,0x10,0x17,0x11,0x11,0x0F}}, {'H', {0x11,0x11,0x11,0x1F,0x11,0x11,0x11}},
    {'I', {0x0E,0x04,0x04,0x04,0x04,0x04,0x0E}}, {'J', {0x07,0x02,0x02,0x02,0x02,0x12,0x0C}},
    {'K', {0x11,0x12,0x14,0x18,0x14,0x12,0x11}}, {'L', {0x10,0x10,0x10,0x10,0x10,0x10,0x1F}},
    {'M', {0x11,0x1B,0x15,0x15,0x11,0x11,0x11}}, {'N', {0x11,0x11,0x19,0x15,0x13,0x11,0x11}},
    {'O', {0x0E,0x11,0x11,0x11,0x11,0x11,0x0E}}, {'P', {0x1E,0x11,0x11,0x1E,0x10,0x10,0x10}},
    {'Q', {0x0E,0x11,0x11,0x11,0x15,0x12,0x0D}}, {'R', {0x1E,0x11,0x11,0x1E,0x14,0x12,0x11}},
    {'S', {0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E}}, {'T', {0x1F,0x04,0x04,0x04,0x04,0x04,0x04}},
    {'U', {0x11,0x11,0x11,0x11,0x11,0x11,0x0E}}, {'V', {0x11,0x11,0x11,0x11,0x11,0x0A,0x04}},
    {'W', {0x11,0x11,0x11,0x15,0x15,0x15,0x0A}}, {'X', {0x11,0x11,0x0A,0x04,0x0A,0x11,0x11}},
    {'Y', {0x11,0x11,0x11,0x0A,0x04,0x04,0x04}}, {'Z', {0x1F,0x01,0x02,0x04,0x08,0x10,0x1F}},
    {'0', {0x0E,0x11,0x13,0x15,0x19,0x11,0x0E}}, {'1', {0x04,0x0C,0x04,0x04,0x04,0x04,0x0E}},
    {'2', {0x0E,0x11,0x01,0x02,0x04,0x08,0x1F}}, {'3', {0x1F,0x02,0x04,0x02,0x01,0x11,0x0E}},
    {'4', {0x02,0x06,0x0A,0x12,0x1F,0x02,0x02}}, {'5', {0x1F,0x10,0x1E,0x01,0x01,0x11,0x0E}},
    {'6', {0x06,0x08,0x10,0x1E,0x11,0x11,0x0E}}, {'7', {0x1F,0x01,0x02,0x04,0x08,0x08,0x08}},
    {'8', {0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E}}, {'9', {0x0E,0x11,0x11,0x0F,0x01,0x02,0x0C}},
    {'-', {0,0,0,0x1F,0,0,0}}, {':', {0,0x0C,0x0C,0,0x0C,0x0C,0}}, {'.', {0,0,0,0,0,0x0C,0x0C}},
    {'!', {0x04,0x04,0x04,0x04,0x04,0,0x04}}, {'(', {0x02,0x04,0x08,0x08,0x08,0x04,0x02}},
    {')', {0x08,0x04,0x02,0x02,0x02,0x04,0x08}}, {'/', {0x01,0x01,0x02,0x04,0x08,0x10,0x10}},
    {'+', {0,0x04,0x04,0x1F,0x04,0x04,0}},
};

static const unsigned char *glyph(char c) {
    if (c >= 'a' && c <= 'z') c -= 32;
    for (size_t i = 0; i < sizeof FONT / sizeof FONT[0]; i++)
        if (FONT[i].c == c) return FONT[i].rows;
    return NULL;
}

/* rectangles of a text (horizontal runs merged), at (x, y) with pixel size s */
static int text_rects(const char *t, int x, int y, int s, D3D11_RECT *out, int max) {
    int n = 0;
    for (; *t; t++, x += 6 * s) {
        const unsigned char *g = glyph(*t);
        if (!g) continue;
        for (int r = 0; r < 7; r++) {
            for (int c = 0; c < 5; c++) {
                if (!(g[r] & (0x10 >> c))) continue;
                int c0 = c;
                while (c + 1 < 5 && (g[r] & (0x10 >> (c + 1)))) c++;
                if (n < max) {
                    out[n].left = x + c0 * s;
                    out[n].right = x + (c + 1) * s;
                    out[n].top = y + r * s;
                    out[n].bottom = y + (r + 1) * s;
                    n++;
                }
            }
        }
    }
    return n;
}

/* ------------------------------------------------------------------------------ Present hook */
typedef HRESULT(STDMETHODCALLTYPE *Present_t)(IDXGISwapChain *, UINT, UINT);
typedef HRESULT(STDMETHODCALLTYPE *Present1_t)(IDXGISwapChain1 *, UINT, UINT, const DXGI_PRESENT_PARAMETERS *);
static Present_t oPresent;
static Present1_t oPresent1;
static int g_draw_fail;

static void draw_overlay(IDXGISwapChain *sc) {
    const char *text = NULL;
    FLOAT fg[4] = {1.0f, 0.85f, 0.2f, 1.0f};
    if (g_active) {
        text = g_status && *g_status ? g_status : "AUTO-BATTLE ON";
    } else if (g_status_hold) {
        if (!g_status_hold_until) g_status_hold_until = GetTickCount() + 6000;
        if (GetTickCount() < g_status_hold_until) { text = g_status_hold; fg[0] = 1.0f; fg[1] = 0.45f; fg[2] = 0.45f; }
        else { g_status_hold = NULL; g_status_hold_until = 0; }
    } else if (GetTickCount() < g_flash_until) {
        text = "AUTO-BATTLE: ITEM WORLD ONLY";
        fg[0] = 1.0f; fg[1] = 0.45f; fg[2] = 0.45f;
    }
    if (!text || g_draw_fail > 20) return;
    ID3D11Device *dev = NULL;
    ID3D11DeviceContext *ctx = NULL;
    ID3D11DeviceContext1 *ctx1 = NULL;
    ID3D11Texture2D *bb = NULL;
    ID3D11RenderTargetView *rtv = NULL;
    if (FAILED(IDXGISwapChain_GetDevice(sc, &IID_ID3D11Device, (void **)&dev)) || !dev) { g_draw_fail++; return; }
    ID3D11Device_GetImmediateContext(dev, &ctx);
    if (FAILED(ID3D11DeviceContext_QueryInterface(ctx, &IID_ID3D11DeviceContext1, (void **)&ctx1)) || !ctx1) {
        if (!g_draw_fail++) logf_("overlay: ID3D11DeviceContext1 not available");
        goto done;
    }
    if (FAILED(IDXGISwapChain_GetBuffer(sc, 0, &IID_ID3D11Texture2D, (void **)&bb)) || !bb) { g_draw_fail++; goto done; }
    D3D11_TEXTURE2D_DESC d;
    ID3D11Texture2D_GetDesc(bb, &d);
    if (FAILED(ID3D11Device_CreateRenderTargetView(dev, (ID3D11Resource *)bb, NULL, &rtv)) || !rtv) {
        if (!g_draw_fail++) logf_("overlay: CreateRenderTargetView failed (format %d)", d.Format);
        goto done;
    }
    {
        int s = (int)d.Height / 300;
        if (s < 2) s = 2;
        int len = (int)strlen(text);
        int w = len * 6 * s + 4 * s, h = 7 * s + 6 * s;
        int x0 = (g_corner & 1) ? (int)d.Width - w - 3 * s : 3 * s;
        int y0 = (g_corner & 2) ? (int)d.Height - h - 3 * s : 3 * s;
        D3D11_RECT box = {x0, y0, x0 + w, y0 + h};
        D3D11_RECT edge = {x0 - s / 2, y0 - s / 2, x0 + w + s / 2, y0 + h + s / 2};
        FLOAT dark[4] = {0.08f, 0.05f, 0.12f, 1.0f};
        ID3D11DeviceContext1_ClearView(ctx1, (ID3D11View *)rtv, fg, &edge, 1);
        ID3D11DeviceContext1_ClearView(ctx1, (ID3D11View *)rtv, dark, &box, 1);
        static D3D11_RECT rects[1024];
        int n = text_rects(text, x0 + 2 * s + s, y0 + 3 * s, s, rects, 1024);
        ID3D11DeviceContext1_ClearView(ctx1, (ID3D11View *)rtv, fg, rects, n);
    }
done:
    if (rtv) ID3D11RenderTargetView_Release(rtv);
    if (bb) ID3D11Texture2D_Release(bb);
    if (ctx1) ID3D11DeviceContext1_Release(ctx1);
    if (ctx) ID3D11DeviceContext_Release(ctx);
    if (dev) ID3D11Device_Release(dev);
}

static HRESULT STDMETHODCALLTYPE hkPresent(IDXGISwapChain *sc, UINT sync, UINT flags) {
    static int seen;
    InterlockedIncrement(&g_inflight);
    if (!seen++) logf_("overlay: first Present through the hook");
    if (!(flags & DXGI_PRESENT_TEST)) { InterlockedIncrement(&g_presents); g_present_sync = (LONG)sync; }
    if (!(flags & DXGI_PRESENT_TEST)) { if (g_feat_auto) draw_overlay(sc); menu_draw(sc); cc_draw(sc); ctl_capture(sc); }
    Present_t o = oPresent;
    InterlockedDecrement(&g_inflight);
    return o(sc, sync, flags);
}

static HRESULT STDMETHODCALLTYPE hkPresent1(IDXGISwapChain1 *sc, UINT sync, UINT flags, const DXGI_PRESENT_PARAMETERS *p) {
    static int seen;
    InterlockedIncrement(&g_inflight);
    if (!seen++) logf_("overlay: first Present1 through the hook");
    if (!(flags & DXGI_PRESENT_TEST)) { InterlockedIncrement(&g_presents); g_present_sync = (LONG)sync; }
    if (!(flags & DXGI_PRESENT_TEST)) { if (g_feat_auto) draw_overlay((IDXGISwapChain *)sc); menu_draw((IDXGISwapChain *)sc); cc_draw((IDXGISwapChain *)sc); ctl_capture((IDXGISwapChain *)sc); }
    Present1_t o = oPresent1;
    InterlockedDecrement(&g_inflight);
    return o(sc, sync, flags, p);
}

static void patch_slot(void **slot, void *fn, void **orig) {
    DWORD old;
    if (*slot == fn) return;
    if (VirtualProtect(slot, sizeof(void *), PAGE_EXECUTE_READWRITE, &old)) {
        *orig = *slot;
        if (g_nslots < 32) { g_slots[g_nslots].slot = slot; g_slots[g_nslots].orig = *slot; g_nslots++; }
        *slot = fn;
        VirtualProtect(slot, sizeof(void *), old, &old);
    }
}

typedef DWORD(WINAPI *XIGetState_t)(DWORD, void *);
static XIGetState_t oXIGetState;
static DWORD WINAPI hkXIGetState(DWORD user, void *st) {
    DWORD r = oXIGetState(user, st);
    if ((g_menu_open || g_cc_open) && r == 0 && st) memset((unsigned char *)st + 4, 0, 12);   /* buttons, triggers, sticks */
    return r;
}
static void install_pad_block(void) {
    patch_slot((void **)G(0x1408d5738ULL), (void *)hkXIGetState, (void **)&oXIGetState);
}

static void install_present_hook(void) {
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = DefWindowProcA;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "d5auto_dummy";
    RegisterClassA(&wc);
    HWND hw = CreateWindowA("d5auto_dummy", "", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, NULL, NULL, wc.hInstance, NULL);
    DXGI_SWAP_CHAIN_DESC sd = {0};
    sd.BufferCount = 1;
    sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferDesc.Width = 64;
    sd.BufferDesc.Height = 64;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.OutputWindow = hw;
    sd.SampleDesc.Count = 1;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    IDXGISwapChain *sc = NULL;
    ID3D11Device *dev = NULL;
    ID3D11DeviceContext *ctx = NULL;
    HRESULT hr = D3D11CreateDeviceAndSwapChain(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL, 0, NULL, 0, D3D11_SDK_VERSION,
                                               &sd, &sc, &dev, NULL, &ctx);
    if (FAILED(hr) || !sc) {
        hr = D3D11CreateDeviceAndSwapChain(NULL, D3D_DRIVER_TYPE_WARP, NULL, 0, NULL, 0, D3D11_SDK_VERSION,
                                           &sd, &sc, &dev, NULL, &ctx);
    }
    if (SUCCEEDED(hr) && sc) {
        void **vt = *(void ***)sc;
        patch_slot(&vt[8], (void *)hkPresent, (void **)&oPresent);
        IDXGISwapChain1 *sc1 = NULL;
        if (SUCCEEDED(IDXGISwapChain_QueryInterface(sc, &IID_IDXGISwapChain1, (void **)&sc1)) && sc1) {
            void **vt1 = *(void ***)sc1;
            patch_slot(&vt1[22], (void *)hkPresent1, (void **)&oPresent1);
            IDXGISwapChain1_Release(sc1);
        }
        logf_("overlay: Present hooked (%p)", (void *)oPresent);
        IDXGISwapChain_Release(sc);
        ID3D11DeviceContext_Release(ctx);
        ID3D11Device_Release(dev);
    } else {
        logf_("overlay: could not create a probe swap chain (0x%08lX) - no indicator", (unsigned long)hr);
    }
    DestroyWindow(hw);
}

/* ------------------------------------------------------------------------------------- entry */
static void core_init_hooks(void);
__declspec(dllexport) int core_frame(void) {
    static int init;
    if (!init) {
        init = 1;
        g_base = (unsigned char *)GetModuleHandleA(NULL);
        {
            IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)g_base;
            IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_base + dos->e_lfanew);
            g_image_size = nt->OptionalHeader.SizeOfImage;
        }
        logf_("d5auto loaded (game base %p, image size 0x%zX)", (void *)g_base, (size_t)g_image_size);
        load_settings();
        if (g_research && !g_crash_veh) g_crash_veh = AddVectoredExceptionHandler(0, crash_veh);
        fx_install();
        install_present_hook();
        install_dinput_hook();
        install_pad_block();
        load_skill_data();
        load_programs();
        cc_load();
        lk_init();
        ctl_start();
    }
    if (g_reload) return 1;
    sm_flip();
    ctl_tick();
    live_tick();
    if (g_feat_auto) {
        poll_toggle();
        g_menu_key = g_editor_key;
        menu_tick();
    }
    cc_tick();
    rows_tick();
    if (g_research || g_remote) screen_log_tick();
    if (g_research) {
        trace_tick();
        ai_experiment_tick();
    }
    auto_tick();
    InterlockedExchange(&g_in_iw, in_item_world());
    {
        static LONG was_active;
        if (g_active && !was_active) g_fought_floor = 0;   /* switched on: wherever it is */
        was_active = g_active;
    }
    if (g_active && !g_test_anywhere) {
        /* off after a floor boss (post-boss screen, held for ~0.5 s so a floor change never trips it)
           or when the Item World session ends */
        /* only when the post-boss area is reached: switched on again there, it goes on to the next stage */
        /* only when it arrives there from a floor: switched on in the rest area, it goes on to the next stage */
        static int boss_frames;
        boss_frames = at_post_boss_screen() ? boss_frames + 1 : 0;
        if (rd8(VA_BATTLE_MAP)) g_fought_floor = 1;
        if (boss_frames > 30 && g_fought_floor) {
            InterlockedExchange(&g_active, 0);
            logf_("auto-battle OFF (floor boss beaten - waiting before the next floor)");
        } else if (rd8(VA_IW_SESSION) == 0) {
            InterlockedExchange(&g_active, 0);
            logf_("auto-battle OFF (left the Item World)");
        }
    }
    return 0;
}

/* the loader unloads this core: every hook out, threads stopped, the game as if we were never there */
__declspec(dllexport) void core_shutdown(void) {
    logf_("core: shutting down (reload)");
    InterlockedExchange(&g_active, 0);
    fx_uninstall();
    auto_tick();                              /* restores AI profiles, SP, team patches (g_active is 0) */
    memset((void *)g_dik, 0, sizeof g_dik);
    ctl_stop();
    trace_shutdown();
    menu_shutdown();
    cc_shutdown();
    lk_shutdown();
    for (int i = g_nslots - 1; i >= 0; i--) {  /* vtable / import-table slots */
        DWORD old;
        if (VirtualProtect(g_slots[i].slot, 8, PAGE_EXECUTE_READWRITE, &old)) {
            *g_slots[i].slot = g_slots[i].orig;
            VirtualProtect(g_slots[i].slot, 8, old, &old);
        }
    }
    for (int i = g_ncodes - 1; i >= 0; i--) {  /* code patches / detours */
        unsigned char *p = (unsigned char *)G(g_codes[i].va);
        DWORD old;
        if (VirtualProtect(p, g_codes[i].n, PAGE_EXECUTE_READWRITE, &old)) {
            memcpy(p, g_codes[i].orig, g_codes[i].n);
            VirtualProtect(p, g_codes[i].n, old, &old);
            FlushInstructionCache(GetCurrentProcess(), p, g_codes[i].n);
        }
    }
    for (int i = 0; i < 200 && g_inflight; i++) Sleep(5);
    Sleep(30);                                 /* another thread may still be in a trampoline */
    logf_("core: all hooks removed");
    if (g_log) { fclose(g_log); g_log = NULL; }
}

__declspec(dllexport) void core_set_gen(int gen) { g_gen = gen; }

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    if (reason == DLL_PROCESS_ATTACH) {
        GetModuleFileNameA(h, g_dir, MAX_PATH);
        char *s = strrchr(g_dir, '\\');
        if (s) s[1] = 0;
        DisableThreadLibraryCalls(h);
    }
    return TRUE;
}

/* ------------------------------------------------------------------ test hooks (toolkit self-test) */
__declspec(dllexport) void d5_test_force(int on) { InterlockedExchange(&g_active, on); }
__declspec(dllexport) void d5_test_draw(void *swapchain) { draw_overlay((IDXGISwapChain *)swapchain); }
