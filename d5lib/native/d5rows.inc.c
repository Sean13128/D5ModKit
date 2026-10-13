/* Character-row fixer (included by d5auto.c).
 *
 * The game sorts char.dat by class id at load, and every unit keeps the ROW INDEX of its class
 * (unit+0x2E0A, set by 0x14015EB80 from the class id at +0x2E04).  Saves store that index and the game
 * does not recompute it on load, so a mod that adds a character row with a class id between existing ones
 * (new outfit / character slots) would make every later unit of an old save read the wrong row.
 * Every frame this checks the 128 roster units (army + reserve) and lets the game's own routine
 * recompute the index of any unit whose row no longer holds its class. */
#define VA_CHAR_RECORDS 0x140A31880ULL   /* -> char.dat rows, 0x38C bytes each, id at +0xD0 */
#define VA_CHAR_COUNT   0x140A31888ULL   /* u32 row count */
#define VA_ROSTER_UNIT0 0x145235C58ULL   /* roster unit 0; 128 units of 0x4750 bytes */
#define VA_UNIT_ROWFIX  0x14015EB80ULL   /* (unit) -> row index + graphics id from the class id */

static int g_rows_fixed;

/* A save with a unit whose class the game doesn't have (its mod is switched off): the game crashes when it next
   looks the class up (entering a battle, 0x14015ce30).  Said once per class: in d5auto.log (the kit's Home page
   reads it and names the mod) and on screen. */
static int g_rows_missing[16], g_nrows_missing;
static void rows_missing(int unit, int cls) {
    for (int k = 0; k < g_nrows_missing; k++)
        if (g_rows_missing[k] == cls) return;
    if (g_nrows_missing < 16) g_rows_missing[g_nrows_missing++] = cls;
    logf_("rows: MISSING CLASS %d (roster unit %d): a mod this save needs is not installed", cls, unit);
    snprintf(g_cc_toast, sizeof g_cc_toast, "Save needs a mod that's off!");
    g_cc_toast_until = GetTickCount() + 12000;
}

static void rows_tick(void) {
    const unsigned char *recs = *(const unsigned char *const *)G(VA_CHAR_RECORDS);
    unsigned int count = *(const unsigned int *)G(VA_CHAR_COUNT);
    if (!recs || !count || count > 4096) return;
    typedef void (*ROWFIX)(void *);
    ROWFIX fix = (ROWFIX)G(VA_UNIT_ROWFIX);
    for (int i = 0; i < 128; i++) {
        unsigned char *u = (unsigned char *)G(VA_ROSTER_UNIT0) + (SIZE_T)i * 0x4750;
        int cls = *(const int *)(u + 0x2E04);
        if (cls <= 0) continue;
        short row = *(const short *)(u + 0x2E0A);
        if (row >= 0 && (unsigned)row < count && *(const int *)(recs + (SIZE_T)row * 0x38C + 0xD0) == cls)
            continue;
        fix(u);
        short now = *(const short *)(u + 0x2E0A);
        if (now < 0) {      /* no row has this class: a unit of a mod that isn't installed (battles would crash) */
            rows_missing(i, cls);
            continue;
        }
        if (g_rows_fixed++ < 64)
            logf_("rows: unit %d (class %d) row %d -> %d", i, cls, (int)row, (int)now);
    }
}
