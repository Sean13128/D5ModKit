/* d5live.inc.c -- live skill preview (included by d5auto.c).

   [skills] live_reload=1: whenever d5live_script.dat (next to the exe) changes while the game runs, it becomes the
   game's script data.  The D5 Mod Kit's Skills page writes it (vanilla script.dat + the enabled mods' script and
   skill edits, plain), so an edited choreography plays on the next cast without a restart.  A file that is already
   there when the game starts is ignored (it may be older than the installed mods). */

/* a plain (decrypted) script.dat becomes the running game's script data.  The script manager ([0x140A95B90]) keeps
   a pointer to the raw data at +0x10 and 0x14018E9B0 re-parses it (count, offsets, ids, code base, single-instance
   flags).  The old buffer is kept: running threads may still point into it.  -> number of scripts, or -1 */
static int load_script_data(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *buf = n > 8 ? (unsigned char *)VirtualAlloc(NULL, (SIZE_T)n + 16, MEM_COMMIT | MEM_RESERVE,
                                                               PAGE_READWRITE) : NULL;
    size_t got = buf ? fread(buf, 1, (size_t)n, f) : 0;
    fclose(f);
    unsigned char *mgr = *(unsigned char **)G(0x140A95B90ULL);
    unsigned cnt = buf ? *(unsigned *)buf : 0;
    if (!buf || got != (size_t)n || !mgr || !cnt || 4 + 8ull * cnt > (unsigned long long)n) {
        if (buf) VirtualFree(buf, 0, MEM_RELEASE);
        return -1;
    }
    typedef void (*PARSE)(void *);
    *(unsigned char **)(mgr + 0x10) = buf;
    ((PARSE)G(0x14018E9B0ULL))(mgr);
    return *(int *)(mgr + 0x18);
}

static void live_tick(void) {
    static int n, init;
    static FILETIME seen;
    if (!g_live || ++n % 30) return;                       /* twice a second */
    char path[MAX_PATH];
    snprintf(path, sizeof path, "%sd5live_script.dat", g_dir);
    WIN32_FILE_ATTRIBUTE_DATA a;
    if (!GetFileAttributesExA(path, GetFileExInfoStandard, &a)) {
        init = 1;
        return;
    }
    if (!init) {
        seen = a.ftLastWriteTime;
        init = 1;
        return;
    }
    if (!CompareFileTime(&a.ftLastWriteTime, &seen)) return;
    seen = a.ftLastWriteTime;
    logf_("live: skill preview loaded (%d scripts)", load_script_data(path));
}
