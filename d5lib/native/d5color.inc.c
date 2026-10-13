/* ================================================================================== custom colour slots
 * Strategy Assembly colours: next to "Normal Color" and "Extra Color 1-3", every character (every class id, so
 * each outfit separately) gets three "Custom Color" slots.  In the precise colour editor ("Change More Colors")
 * a key saves the colours being edited into a slot; the normal colour list ("Change Colors") then offers the
 * saved slots below the extra colours, with a live preview.  The slots are a library shared by all saves
 * (d5colors.bin next to the game); choosing one gives the unit those custom colours in its save as usual.
 *
 * Colour screen object (vtable 0x1409b9ee0, "scene"):
 *   +0x88     mode: 0 = Change Colors, 1 = Change More Colors
 *   +0x47e0   unit copy being edited (+0x2e04 class, +0x2e2c colour variant, +0x35c4 custom colour set)
 *   +0x47e8   palette index of the choice under the cursor
 *   +0x47f0   the choice list (entries added by 0x14008a9e0(list, text, value, 0))
 *   +0xf1c8   the unit copy's custom colour set: 256 colours (0x400), +0x400 "custom" flag, +0x402 the editor's
 *             per-part shade / saturation / brightness (16 x 3 shorts); 0x480 bytes in all
 *   +0x15678  preview character, rebuilt from a unit by 0x140147750(scene + 0x15678, unit)
 * Hooks (all runtime detours, removed again by core_shutdown):
 *   0x140455e93  the choice list is complete           -> add "Custom Color N" (value 100 + N) in mode 0
 *   0x140457bf0  a choice is under the cursor (preview) -> custom: its base palette, then its colours on top
 *   0x1404556cb  a choice is confirmed, after the game cleared the copy's custom colours (r14d = value)
 *                                                       -> custom: its colours into the unit copy
 */
#define CC_SLOTS 3
#define CC_SET 0x480
#define CC_VALUE 100
#define CC_MAX 1024
#define VT_COLOUR_SCENE 0x1409b9ee0ULL
#define VA_CC_LIST_END 0x140455e93ULL
#define VA_CC_CHOICE 0x140457bf0ULL
static const unsigned char CC_CHOICE_ORIG[5] = {0x48, 0x89, 0x5c, 0x24, 0x08};            /* mov [rsp+8],rbx */
#define VA_CC_CONFIRM 0x1404556cbULL
#if defined(D5_BUILD_9460A6411699)
/* the Steam build: the same code with the scene in other registers (r15 at the list end, rbp at the confirm) */
static const unsigned char CC_LIST_ORIG[7] = {0x49, 0x8b, 0x87, 0xe0, 0x47, 0x00, 0x00};   /* mov rax,[r15+0x47e0] */
static const unsigned char CC_CONFIRM_ORIG[6] = {0x8b, 0x85, 0x88, 0x00, 0x00, 0x00};     /* mov eax,[rbp+0x88] */
static const unsigned char CC_LIST_SCENE[3] = {0x4c, 0x89, 0xf9};                         /* mov rcx, r15 */
static const unsigned char CC_CONFIRM_SCENE[3] = {0x48, 0x89, 0xe9};                      /* mov rcx, rbp */
#else
static const unsigned char CC_LIST_ORIG[7] = {0x48, 0x8b, 0x86, 0xe0, 0x47, 0x00, 0x00};   /* mov rax,[rsi+0x47e0] */
static const unsigned char CC_CONFIRM_ORIG[6] = {0x8b, 0x86, 0x88, 0x00, 0x00, 0x00};     /* mov eax,[rsi+0x88] */
static const unsigned char CC_LIST_SCENE[3] = {0x48, 0x89, 0xf1};                         /* mov rcx, rsi */
static const unsigned char CC_CONFIRM_SCENE[3] = {0x48, 0x89, 0xf1};                      /* mov rcx, rsi */
#endif
#define VA_LIST_ADD 0x14008a9e0ULL
#define VA_PREVIEW_UNIT 0x140147750ULL

typedef struct { unsigned int cls; unsigned char slot, base, pad[2]; unsigned char set[CC_SET]; } CCREC;
static CCREC g_ccrec[CC_MAX];
static int g_ncc;
static int g_cc_hooked;                     /* g_cc_enabled / g_cc_key / g_cc_pad / g_cc_open: d5auto.c */
static int g_cc_sel;
static unsigned char g_cc_pending[CC_SET];  /* the colours the picker will save */
static unsigned int g_cc_pending_cls;
static unsigned char g_cc_pending_base;
static char g_cc_toast[96];
static DWORD g_cc_toast_until;
static int g_cc_in_editor;
static long long (*g_cc_choice_orig)(void *, int);
static char g_cc_text[CC_SLOTS][32];

static void cc_path(char *out, size_t cap) { snprintf(out, cap, "%sd5colors.bin", g_dir); }

static void cc_load(void) {
    char p[MAX_PATH];
    cc_path(p, sizeof p);
    FILE *f = fopen(p, "rb");
    g_ncc = 0;
    if (!f) return;
    char magic[4];
    unsigned int ver = 0, n = 0;
    if (fread(magic, 1, 4, f) == 4 && !memcmp(magic, "D5CC", 4) && fread(&ver, 4, 1, f) == 1 && ver == 1 &&
        fread(&n, 4, 1, f) == 1) {
        for (unsigned int i = 0; i < n && g_ncc < CC_MAX; i++)
            if (fread(&g_ccrec[g_ncc], sizeof(CCREC), 1, f) == 1 && g_ccrec[g_ncc].slot < CC_SLOTS) g_ncc++;
    }
    fclose(f);
    logf_("colors: %d custom colour slot(s) in d5colors.bin", g_ncc);
}

static void cc_save_file(void) {
    char p[MAX_PATH], tmp[MAX_PATH];
    cc_path(p, sizeof p);
    snprintf(tmp, sizeof tmp, "%s.tmp", p);
    FILE *f = fopen(tmp, "wb");
    if (!f) { logf_("colors: cannot write %s", tmp); return; }
    unsigned int ver = 1, n = (unsigned int)g_ncc;
    fwrite("D5CC", 1, 4, f);
    fwrite(&ver, 4, 1, f);
    fwrite(&n, 4, 1, f);
    fwrite(g_ccrec, sizeof(CCREC), g_ncc, f);
    fclose(f);
    MoveFileExA(tmp, p, MOVEFILE_REPLACE_EXISTING);
}

static CCREC *cc_find(unsigned int cls, int slot) {
    for (int i = 0; i < g_ncc; i++)
        if (g_ccrec[i].cls == cls && g_ccrec[i].slot == slot) return &g_ccrec[i];
    return NULL;
}

static unsigned char *cc_unit(unsigned char *scene) {
    unsigned char *u = *(unsigned char **)(scene + 0x47e0);
    return readable(u, 0x4750) ? u : NULL;
}

/* ---- hook 1: the list is complete */
static void __cdecl cc_list_end(unsigned char *scene) {
    if (!g_cc_enabled) return;          /* both topics: a colour to wear, or a base for the precise editor */
    unsigned char *u = cc_unit(scene);
    if (!u) return;
    unsigned int cls = *(unsigned int *)(u + 0x2e04);
    void (*add)(void *, const char *, int, int) = (void (*)(void *, const char *, int, int))G(VA_LIST_ADD);
    for (int s = 0; s < CC_SLOTS; s++)
        if (cc_find(cls, s)) {
            snprintf(g_cc_text[s], sizeof g_cc_text[s], "Custom Color %d", s + 1);
            add(scene + 0x47f0, g_cc_text[s], CC_VALUE + s, 0);
        }
}

/* ---- hook 2: preview of the choice under the cursor (replaces the function; the original runs through
 *      g_cc_choice_orig) */
static long long __cdecl cc_choice(unsigned char *scene, int value) {
    CCREC *r = NULL;
    unsigned char *u = cc_unit(scene);
    if (value >= CC_VALUE && value < CC_VALUE + CC_SLOTS && u)
        r = cc_find(*(unsigned int *)(u + 0x2e04), value - CC_VALUE);
    long long ret = g_cc_choice_orig(scene, r ? r->base : (value >= CC_VALUE ? 0 : value));
    unsigned char *set = *(unsigned char **)(scene + 0xf1c8);
    if (r && u && readable(set, CC_SET)) {
        memcpy(set, r->set, CC_SET);
        set[0x400] = 1;
        void (*rebuild)(void *, void *) = (void (*)(void *, void *))G(VA_PREVIEW_UNIT);
        rebuild(scene + 0x15678, u);
    }
    return ret;
}

/* ---- hook 3: confirmed (the game has just cleared the copy's custom colours) */
static void __cdecl cc_confirm(unsigned char *scene, int value) {
    if (value < CC_VALUE || value >= CC_VALUE + CC_SLOTS) return;
    unsigned char *u = cc_unit(scene);
    unsigned char *set = *(unsigned char **)(scene + 0xf1c8);
    if (!u || !readable(set, CC_SET)) return;
    CCREC *r = cc_find(*(unsigned int *)(u + 0x2e04), value - CC_VALUE);
    if (!r) return;
    memcpy(set, r->set, CC_SET);
    set[0x400] = 1;
    u[0x2e2c] = r->base;
    logf_("colors: class %u gets Custom Color %d", r->cls, value - CC_VALUE + 1);
}

/* a detour that calls fn(rcx = <reg>, rdx = <reg2 or 0>) with every volatile register kept, then runs the
   displaced instructions and returns to the site.  rcx_mov: the 3-byte "mov rcx, <scene register>" */
static unsigned char *cc_stub(unsigned char *t, unsigned long long va, const unsigned char *orig, int n,
                              void *fn, const unsigned char *rcx_mov, unsigned char rdx_from_r14) {
    int k = 0;
    static const unsigned char push[] = {0x50, 0x51, 0x52, 0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53};
    memcpy(t + k, push, sizeof push); k += sizeof push;                 /* push rax rcx rdx r8 r9 r10 r11 */
    t[k++] = 0x48; t[k++] = 0x83; t[k++] = 0xec; t[k++] = 0x28;         /* sub rsp, 0x28 */
    if (rcx_mov) { memcpy(t + k, rcx_mov, 3); k += 3; }                 /* mov rcx, <scene> */
    if (rdx_from_r14) { t[k++] = 0x44; t[k++] = 0x89; t[k++] = 0xf2; } /* mov edx, r14d */
    t[k++] = 0x48; t[k++] = 0xb8; memcpy(t + k, &fn, 8); k += 8;        /* mov rax, fn */
    t[k++] = 0xff; t[k++] = 0xd0;                                       /* call rax */
    t[k++] = 0x48; t[k++] = 0x83; t[k++] = 0xc4; t[k++] = 0x28;         /* add rsp, 0x28 */
    static const unsigned char pop[] = {0x41, 0x5b, 0x41, 0x5a, 0x41, 0x59, 0x41, 0x58, 0x5a, 0x59, 0x58};
    memcpy(t + k, pop, sizeof pop); k += sizeof pop;
    memcpy(t + k, orig, n); k += n;
    unsigned char *site = (unsigned char *)G(va);
    t[k++] = 0xe9; *(int *)(t + k) = (int)((site + n) - (t + k + 4)); k += 4;
    return t;
}

static void cc_jump(unsigned long long va, unsigned char *to, int n) {
    unsigned char j[16];
    unsigned char *site = (unsigned char *)G(va);
    j[0] = 0xe9;
    *(int *)(j + 1) = (int)(to - (site + 5));
    for (int i = 5; i < n; i++) j[i] = 0x90;
    write_code(va, j, n);
}

static void cc_install(void) {
    if (!g_cc_enabled || g_cc_hooked) return;
    unsigned char *pg = near_page();
    if (!pg || memcmp(G(VA_CC_LIST_END), CC_LIST_ORIG, 7) || memcmp(G(VA_CC_CHOICE), CC_CHOICE_ORIG, 5) ||
        memcmp(G(VA_CC_CONFIRM), CC_CONFIRM_ORIG, 6)) {
        logf_("colors: colour screen code not as expected - no custom colour slots");
        return;
    }
    /* original preview function: its first instruction, then back into it */
    unsigned char *orig = pg + 0x400;
    memcpy(orig, CC_CHOICE_ORIG, 5);
    orig[5] = 0xe9;
    *(int *)(orig + 6) = (int)(((unsigned char *)G(VA_CC_CHOICE) + 5) - (orig + 10));
    g_cc_choice_orig = (long long (*)(void *, int))orig;
    /* the preview function itself goes to cc_choice (same arguments) */
    unsigned char *jmp = pg + 0x420;
    void *fn = (void *)cc_choice;
    jmp[0] = 0x48; jmp[1] = 0xb8; memcpy(jmp + 2, &fn, 8);            /* mov rax, cc_choice */
    jmp[10] = 0xff; jmp[11] = 0xe0;                                   /* jmp rax */
    cc_stub(pg + 0x440, VA_CC_LIST_END, CC_LIST_ORIG, 7, (void *)cc_list_end, CC_LIST_SCENE, 0);
    cc_stub(pg + 0x4c0, VA_CC_CONFIRM, CC_CONFIRM_ORIG, 6, (void *)cc_confirm, CC_CONFIRM_SCENE, 1);
    cc_jump(VA_CC_CHOICE, jmp, 5);
    cc_jump(VA_CC_LIST_END, pg + 0x440, 7);
    cc_jump(VA_CC_CONFIRM, pg + 0x4c0, 6);
    g_cc_hooked = 1;
    logf_("colors: custom colour slots on (save key %c)", g_cc_key);
}

/* ---- the precise editor: the save key, the slot picker */
static unsigned char *cc_scene(void) {
    int n;
    const SMREC *l = sm_list(&n);
    for (int i = 0; i < n; i++)
        if (l[i].vt == VT_COLOUR_SCENE) return l[i].obj;
    return NULL;
}

static int g_cc_closing;      /* picker closed, the game stays blocked until its keys are released */
static void cc_close(void) { g_cc_closing = 1; }

/* a key held on the keyboard, or pressed by the test harness (injected DirectInput scancode) */
static int g_cc_focused;
static int cc_key_down(int vk) {
    if (!vk) return 0;
    if (g_cc_focused && (GetAsyncKeyState(vk) & 0x8000)) return 1;
    UINT sc = MapVirtualKeyA((UINT)vk, 0);
    return sc && sc < 256 && g_dik[sc];
}

static void cc_store(int slot) {
    CCREC *r = cc_find(g_cc_pending_cls, slot);
    if (!r) {
        if (g_ncc >= CC_MAX) { snprintf(g_cc_toast, sizeof g_cc_toast, "Custom colours full"); return; }
        r = &g_ccrec[g_ncc++];
        memset(r, 0, sizeof *r);
        r->cls = g_cc_pending_cls;
        r->slot = (unsigned char)slot;
    }
    r->base = g_cc_pending_base;
    memcpy(r->set, g_cc_pending, CC_SET);
    r->set[0x400] = 1;
    cc_save_file();
    snprintf(g_cc_toast, sizeof g_cc_toast, "Saved as Custom Color %d", slot + 1);
    g_cc_toast_until = GetTickCount() + 2500;
    logf_("colors: class %u -> Custom Color %d (base palette %d)", r->cls, slot + 1, r->base);
}

static void cc_clear(int slot) {
    for (int i = 0; i < g_ncc; i++)
        if (g_ccrec[i].cls == g_cc_pending_cls && g_ccrec[i].slot == slot) {
            g_ccrec[i] = g_ccrec[--g_ncc];
            cc_save_file();
            snprintf(g_cc_toast, sizeof g_cc_toast, "Custom Color %d cleared", slot + 1);
            g_cc_toast_until = GetTickCount() + 2500;
            logf_("colors: class %u Custom Color %d cleared", g_cc_pending_cls, slot + 1);
            return;
        }
}

static void cc_tick(void) {
    if (!g_cc_enabled) return;
    if (!g_cc_hooked) cc_install();
    unsigned char *scene = cc_scene();
    g_cc_in_editor = scene && tx_find("Edit the palette.") != NULL;
    static int key_was, pad_was;
    static int was[6];
    g_cc_focused = game_focused();
    WORD pad = g_cc_focused ? pad_buttons() : 0;
    if (!g_cc_open) {
        int key = cc_key_down(g_cc_key);
        int pb = g_cc_pad && (pad & g_cc_pad) == g_cc_pad;
        if (g_cc_in_editor && ((key && !key_was) || (pb && !pad_was))) {
            unsigned char *u = cc_unit(scene);
            unsigned char *set = *(unsigned char **)(scene + 0xf1d0);
            if (u && readable(set, CC_SET)) {
                memcpy(g_cc_pending, set, CC_SET);
                g_cc_pending_cls = *(unsigned int *)(u + 0x2e04);
                g_cc_pending_base = u[0x2e2c];
                g_cc_sel = 0;
                memset(was, 1, sizeof was);            /* keys held now don't act in the picker */
                InterlockedExchange(&g_cc_open, 1);
            }
        }
        key_was = key;
        pad_was = pb;
        return;
    }
    if (g_cc_closing) {
        int any = cc_key_down('K') || cc_key_down(VK_RETURN) || cc_key_down('L') || cc_key_down(VK_ESCAPE) ||
                  cc_key_down('X') || (pad & 0x7000);
        if (!any) { g_cc_closing = 0; InterlockedExchange(&g_cc_open, 0); }
        return;
    }
    /* picker keys (the game gets none of them) */
    static const struct { int vk; int vk2; WORD pad; } K[6] = {
        {'W', VK_UP, 0x0001}, {'S', VK_DOWN, 0x0002}, {'K', VK_RETURN, 0x1000}, {'L', VK_ESCAPE, 0x2000},
        {'X', VK_DELETE, 0x4000}, {0, 0, 0}};
    for (int i = 0; i < 5; i++) {
        int down = cc_key_down(K[i].vk) || cc_key_down(K[i].vk2) || (pad & K[i].pad);
        if (down && !was[i]) {
            if (i == 0) g_cc_sel = (g_cc_sel + CC_SLOTS - 1) % CC_SLOTS;
            if (i == 1) g_cc_sel = (g_cc_sel + 1) % CC_SLOTS;
            if (i == 2) { cc_store(g_cc_sel); cc_close(); }
            if (i == 3) cc_close();
            if (i == 4) cc_clear(g_cc_sel);
        }
        was[i] = down;
    }
    key_was = pad_was = 1;
}

/* ---- drawing: a small panel at the bottom of the screen (GDI -> texture -> back buffer) */
static HDC g_cdc;
static HBITMAP g_cbmp;
static unsigned char *g_cbits;
static int g_cw, g_ch;
static HFONT g_cfont, g_cfont_b;
static ID3D11Texture2D *g_ctex;
static DXGI_FORMAT g_ctex_fmt;

static int g_cpx;
static int cc_surface(int w, int h, int px) {
    if (g_cdc && w == g_cw && h == g_ch && px == g_cpx) return 1;
    if (g_cbmp) { DeleteObject(g_cbmp); g_cbmp = NULL; }
    if (!g_cdc) g_cdc = CreateCompatibleDC(NULL);
    BITMAPINFO bi;
    memset(&bi, 0, sizeof bi);
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = w;
    bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    g_cbmp = CreateDIBSection(g_cdc, &bi, DIB_RGB_COLORS, (void **)&g_cbits, NULL, 0);
    if (!g_cbmp) return 0;
    SelectObject(g_cdc, g_cbmp);
    if (g_cfont) { DeleteObject(g_cfont); DeleteObject(g_cfont_b); }
    g_cpx = px;
    g_cfont = CreateFontA(-px, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, "Segoe UI");
    g_cfont_b = CreateFontA(-px, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, "Segoe UI");
    g_cw = w; g_ch = h;
    if (g_ctex) { ID3D11Texture2D_Release(g_ctex); g_ctex = NULL; }
    return 1;
}

static void ctext(int x, int y, COLORREF c, HFONT f, const char *s) {
    SelectObject(g_cdc, f);
    SetTextColor(g_cdc, c);
    SetBkMode(g_cdc, TRANSPARENT);
    TextOutA(g_cdc, x, y, s, (int)strlen(s));
}
static void crect(int x0, int y0, int x1, int y1, COLORREF c) {
    RECT r = {x0, y0, x1, y1};
    HBRUSH b = CreateSolidBrush(c);
    FillRect(g_cdc, &r, b);
    DeleteObject(b);
}

static void cc_draw(IDXGISwapChain *sc) {
    int toast = g_cc_toast_until && GetTickCount() < g_cc_toast_until;    /* also other features' messages */
    if ((!g_cc_enabled && !toast) || (!g_cc_in_editor && !g_cc_open && !toast)) return;
    if (g_cc_closing && !toast) return;
    ID3D11Device *dev = NULL;
    ID3D11DeviceContext *ctx = NULL;
    ID3D11Texture2D *bb = NULL;
    if (FAILED(IDXGISwapChain_GetDevice(sc, &IID_ID3D11Device, (void **)&dev)) || !dev) return;
    ID3D11Device_GetImmediateContext(dev, &ctx);
    if (FAILED(IDXGISwapChain_GetBuffer(sc, 0, &IID_ID3D11Texture2D, (void **)&bb)) || !bb) goto out;
    D3D11_TEXTURE2D_DESC d;
    ID3D11Texture2D_GetDesc(bb, &d);
    if (d.SampleDesc.Count > 1) goto out;
    int row = (int)d.Height * 5 / 100;          /* one line of the panel */
    int w = (int)d.Width * 30 / 100, h = g_cc_open && !g_cc_closing ? row * 5 : row * 4 / 3;
    if (w < 200 || row < 16) goto out;
    if (!cc_surface(w, h, row * 11 / 20)) goto out;
    if (!g_ctex || g_ctex_fmt != d.Format) {
        if (g_ctex) { ID3D11Texture2D_Release(g_ctex); g_ctex = NULL; }
        D3D11_TEXTURE2D_DESC t;
        memset(&t, 0, sizeof t);
        t.Width = w; t.Height = h; t.MipLevels = 1; t.ArraySize = 1; t.Format = d.Format;
        t.SampleDesc.Count = 1; t.Usage = D3D11_USAGE_DEFAULT;
        if (FAILED(ID3D11Device_CreateTexture2D(dev, &t, NULL, &g_ctex))) { g_ctex = NULL; goto out; }
        g_ctex_fmt = d.Format;
    }
    const COLORREF BG = RGB(28, 18, 48), EDGE = RGB(200, 120, 255), TXT = RGB(240, 235, 255), DIM = RGB(160, 150, 190),
                   SEL = RGB(90, 40, 140), GOLD = RGB(255, 210, 90);
    crect(0, 0, w, h, EDGE);
    crect(2, 2, w - 2, h - 2, BG);
    int pad = row / 5;
    char line[96];
    if (g_cc_open && !g_cc_closing) {
        ctext(pad * 2, pad, GOLD, g_cfont_b, "Save these colours as:");
        for (int s = 0; s < CC_SLOTS; s++) {
            int y = row + s * row + pad;
            if (s == g_cc_sel) crect(pad, y - pad / 2, w - pad, y + row - pad, SEL);
            CCREC *r = cc_find(g_cc_pending_cls, s);
            snprintf(line, sizeof line, "Custom Color %d   %s", s + 1, r ? "(replace)" : "(empty)");
            ctext(pad * 3, y, s == g_cc_sel ? TXT : DIM, s == g_cc_sel ? g_cfont_b : g_cfont, line);
        }
        ctext(pad * 2, row * 4 + pad, DIM, g_cfont, "W/S choose   K save   X clear   L cancel");
    } else if (toast) {
        ctext(pad * 2, pad, GOLD, g_cfont_b, g_cc_toast);
    } else {
        snprintf(line, sizeof line, "[%c / R3]  Save as Custom Color", g_cc_key);
        ctext(pad * 2, pad, TXT, g_cfont_b, line);
    }
    GdiFlush();
    {
        int bgr = d.Format == DXGI_FORMAT_B8G8R8A8_UNORM || d.Format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                  d.Format == DXGI_FORMAT_B8G8R8X8_UNORM || d.Format == DXGI_FORMAT_B8G8R8X8_UNORM_SRGB;
        unsigned char *px = g_cbits;
        for (int i = 0; i < w * h; i++, px += 4) {
            if (!bgr) { unsigned char t = px[0]; px[0] = px[2]; px[2] = t; }
            px[3] = 255;
        }
        ID3D11DeviceContext_UpdateSubresource(ctx, (ID3D11Resource *)g_ctex, 0, NULL, g_cbits, w * 4, 0);
    }
    {
        int x = (int)d.Width * 66 / 100, y = (int)d.Height * 3 / 100;   /* top right, above the preview */
        ID3D11DeviceContext_CopySubresourceRegion(ctx, (ID3D11Resource *)bb, 0, x, y, 0, (ID3D11Resource *)g_ctex, 0, NULL);
    }
out:
    if (bb) ID3D11Texture2D_Release(bb);
    if (ctx) ID3D11DeviceContext_Release(ctx);
    if (dev) ID3D11Device_Release(dev);
}

static void cc_shutdown(void) {
    InterlockedExchange(&g_cc_open, 0);
    g_cc_closing = 0;
    if (g_ctex) { ID3D11Texture2D_Release(g_ctex); g_ctex = NULL; }
    if (g_cbmp) { DeleteObject(g_cbmp); g_cbmp = NULL; }
    if (g_cdc) { DeleteDC(g_cdc); g_cdc = NULL; }
    if (g_cfont) { DeleteObject(g_cfont); DeleteObject(g_cfont_b); g_cfont = NULL; }
    g_cw = g_ch = 0;
    g_cc_hooked = 0;
}
