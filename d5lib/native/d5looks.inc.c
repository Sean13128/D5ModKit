/* Outfit looks' custom colours (included by d5auto.c).
 *
 * A unit has three custom-colour sets (unit+0x35C4, 0x480 bytes each: 0x400 colours, +0x400 flag, +0x402
 * adjustments) and its colour index (+0x2E2C).  The outfit patch keeps every look's colours in those sets
 * for characters with up to three looks; a character with more looks calls looks_cb (pointer slot after
 * the "D5LOOKCB" marker in the exe's .d5mod section) right before the class changes.  Here the colours of
 * the look being left are kept in d5looks.bin (next to the game, by unit name and class) and the colours
 * kept for the new look are put back -- or, the first time, the outfit's plain normal colours. */
#define LK_MAX 512
#define LK_SET 0x480

typedef struct {
    char name[48];
    unsigned int cls;
    unsigned char colour, pad[3];
    unsigned char set[LK_SET];
} LKREC;

static LKREC g_lk[LK_MAX];
static int g_nlk;
static unsigned long long *g_lk_slot;

static void lk_path(char *out, size_t cap) { snprintf(out, cap, "%sd5looks.bin", g_dir); }

static void lk_load(void) {
    char p[MAX_PATH];
    lk_path(p, sizeof p);
    FILE *f = fopen(p, "rb");
    g_nlk = 0;
    if (!f) return;
    char magic[4];
    unsigned int ver = 0, n = 0;
    if (fread(magic, 1, 4, f) == 4 && !memcmp(magic, "D5LK", 4) && fread(&ver, 4, 1, f) == 1 && ver == 1 &&
        fread(&n, 4, 1, f) == 1)
        for (unsigned int i = 0; i < n && g_nlk < LK_MAX; i++)
            if (fread(&g_lk[g_nlk], sizeof(LKREC), 1, f) == 1) g_nlk++;
    fclose(f);
}

static void lk_save(void) {
    char p[MAX_PATH], tmp[MAX_PATH];
    lk_path(p, sizeof p);
    snprintf(tmp, sizeof tmp, "%s.tmp", p);
    FILE *f = fopen(tmp, "wb");
    if (!f) return;
    unsigned int ver = 1, n = (unsigned int)g_nlk;
    fwrite("D5LK", 1, 4, f);
    fwrite(&ver, 4, 1, f);
    fwrite(&n, 4, 1, f);
    fwrite(g_lk, sizeof(LKREC), g_nlk, f);
    fclose(f);
    MoveFileExA(tmp, p, MOVEFILE_REPLACE_EXISTING);
}

static LKREC *lk_find(const char *name, unsigned int cls, int create) {
    for (int i = 0; i < g_nlk; i++)
        if (g_lk[i].cls == cls && !strncmp(g_lk[i].name, name, sizeof g_lk[i].name)) return &g_lk[i];
    if (!create || g_nlk >= LK_MAX) return NULL;
    LKREC *r = &g_lk[g_nlk++];
    memset(r, 0, sizeof *r);
    snprintf(r->name, sizeof r->name, "%s", name);
    r->cls = cls;
    return r;
}

/* called by the exe on the game thread: unit, the look being left, the look being put on */
static void looks_cb(unsigned char *unit, int old_cls, int new_cls) {
    if (!readable(unit, 0x4750) || old_cls == new_cls) return;
    char name[48];
    memcpy(name, unit + 0xBC8, sizeof name - 1);
    name[sizeof name - 1] = 0;
    unsigned char *set0 = unit + 0x35C4;
    LKREC *old = lk_find(name, (unsigned)old_cls, 1);
    if (old) {
        memcpy(old->set, set0, LK_SET);
        old->colour = unit[0x2E2C];
    }
    LKREC *nw = lk_find(name, (unsigned)new_cls, 0);
    if (nw) {
        memcpy(set0, nw->set, LK_SET);
        unit[0x2E2C] = nw->colour;
    } else {
        set0[0x400] = 0;            /* no custom colours yet for this look: its normal palette */
    }
    lk_save();
    logf_("looks: %s %d -> %d (%s)", name, old_cls, new_cls, nw ? "its colours restored" : "first time: normal colours");
}

static void lk_init(void) {
    lk_load();
    /* find the pointer slot in the outfit patch's section */
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_base + ((IMAGE_DOS_HEADER *)g_base)->e_lfanew);
    IMAGE_SECTION_HEADER *sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; i++, sec++) {
        if (memcmp(sec->Name, ".d5mod", 6)) continue;
        unsigned char *p = g_base + sec->VirtualAddress, *e = p + sec->Misc.VirtualSize - 16;
        for (; p <= e; p += 8) {
            if (memcmp(p, "D5LOOKCB", 8)) continue;
            g_lk_slot = (unsigned long long *)(p + 8);
            DWORD old;
            if (VirtualProtect(g_lk_slot, 8, PAGE_EXECUTE_READWRITE, &old)) {
                *g_lk_slot = (unsigned long long)(void *)looks_cb;
                VirtualProtect(g_lk_slot, 8, old, &old);
                logf_("looks: outfit colours per look on (%d kept)", g_nlk);
            }
            return;
        }
    }
}

static void lk_shutdown(void) {
    if (!g_lk_slot) return;
    DWORD old;
    if (VirtualProtect(g_lk_slot, 8, PAGE_EXECUTE_READWRITE, &old)) {
        *g_lk_slot = 0;
        VirtualProtect(g_lk_slot, 8, old, &old);
    }
    g_lk_slot = NULL;
}
