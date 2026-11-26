/* evcap3_host.c -- host driver for d5lib/native/d5learn.inc.c (EVCAP3, offline only).
 *
 * The learned-evility persistence code is compiled here for the host, byte for byte the same file the
 * Windows runtime (d5core.dll) compiles, with two shims:
 *   - `d5learn_host_image()` returns a synthetic PE image holding the real assembled `.d5lc` section, so
 *     the section scan, the field arithmetic and the store are exercised as they are in the game;
 *   - the game addresses the section carries (key array, max index, save folder) are repointed at host
 *     fixtures, so the guard and the id -> position search run against a table this test owns.
 * Everything else -- the guard, the store, sha256, the companion format, the publish/rotate order, the
 * refusal paths -- is the code that runs in the game.
 *
 *   evcap3_host <section.bin> <keys.bin> <savedir> <action>...
 *
 * Actions:
 *   saveslot=<n>       publish the save event for slot n the way lc_save_relay does after the game's writer
 *                      answered 0 (0 = AutoSave.sav; a negative value publishes the "not a slot" sentinel),
 *                      then run one frame.  The runtime builds "<savedir>/Save_%03d.sav" itself.
 *   load=<slot>[:ok]   publish the load event for that slot (ok|bad = the game's decode result), one frame
 *   put=<serial>:<id>  insert a learned pair through the section's own lc_put
 *   clear              empty the store through the section's own lc_clear
 *   remote=<0|1>       set the agent-run flag ([debug] remote=1 in the game): while set, the runtime reads
 *                      and applies a companion but never writes, rotates, renames or removes anything
 *   state              print the field block (state, used, cap, gen, path len)
 *   dump               print the live store, "serial id" one per line, sorted
 * Store dumps go to stdout; the runtime's log lines and errors go to stderr.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>

static unsigned char *g_image;                  /* the synthetic PE image */
static unsigned char *g_section;                /* its .d5lc section content */
static size_t g_section_len;
static unsigned int *g_keys;                    /* the live Skill key array fixture */
static unsigned short g_max = 0;
static char g_savedir[1024];   /* wider than the runtime's 512-byte name so a long folder can be tested */

unsigned char *d5learn_host_image(void) { return g_image; }

static void logf_(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "log: ");
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
}

#include "../d5lib/native/d5learn.inc.c"

/* lc_put / lc_clear live in the section as x86-64 machine code, which this host cannot execute.  The
 * harness therefore mirrors them (same slot arithmetic, same probe budget, same ceiling: the constants are
 * read from the section itself) and the x86 originals are executed by the Unicorn proof
 * (evility/offline_proof_evcap3.py, cases lc-put-* / lc-clear).  tests/test_evcap3.py asserts the two
 * implementations agree on the slot a pair lands in. */
static unsigned int host_mask, host_cap, host_max_used, host_shift;
#define HOST_PROBE 128

static unsigned int host_slot(unsigned long long serial, unsigned int id) {
    unsigned long long h = ((serial * 0x9E3779B97F4A7C15ull) ^ ((unsigned long long)id * 0xC2B2AE3D27D4EB4Full));
    return (unsigned int)(h >> host_shift) & host_mask;
}

static int host_put(unsigned long long serial, unsigned int id) {
    unsigned long long at = (unsigned long long)host_slot(serial, id) * 16ull;
    int k;
    for (k = 0; k < HOST_PROBE; k++, at += 16) {
        unsigned char *slot = g_lc + g_lc_store + at;
        unsigned int state = *(unsigned int *)(slot + 12);
        if (!state) {
            if (lcu(LC_O_USED) >= host_max_used) return -1;
            *(unsigned long long *)slot = serial;
            *(unsigned int *)(slot + 8) = id;
            *(unsigned int *)(slot + 12) = 1;
            lcuset(LC_O_USED, lcu(LC_O_USED) + 1);
            return 0;
        }
        if (state == 1 && *(unsigned long long *)slot == serial && *(unsigned int *)(slot + 8) == id)
            return 0;
    }
    return -1;
}

static void host_clear(void) {
    memset(g_lc + g_lc_store, 0, (size_t)host_cap * 16);
    lcuset(LC_O_USED, 0);
}

static unsigned char *slurp(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    unsigned char *b;
    long len;
    if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(2); }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    rewind(f);
    b = (unsigned char *)malloc((size_t)len);
    if (!b || fread(b, 1, (size_t)len, f) != (size_t)len) { fprintf(stderr, "short read %s\n", path); exit(2); }
    fclose(f);
    *n = (size_t)len;
    return b;
}

int main(int argc, char **argv) {
    size_t klen = 0;
    unsigned char *kb;
    int i;
    if (argc < 5) {
        fprintf(stderr, "usage: %s <section.bin> <keys.bin> <savedir> <action>...\n", argv[0]);
        return 2;
    }
    g_section = slurp(argv[1], &g_section_len);
    kb = slurp(argv[2], &klen);
    g_keys = (unsigned int *)kb;
    g_max = (unsigned short)(klen / 4 - 1);
    snprintf(g_savedir, sizeof g_savedir, "%s", argv[3]);

    g_image = (unsigned char *)calloc(1, 0x1000 + g_section_len + 16);
    if (!g_image) return 2;
    {
        LC_DOS *dos = (LC_DOS *)g_image;
        LC_NT *nt = (LC_NT *)(g_image + 0x40);
        LC_SEC *sh = (LC_SEC *)(g_image + 0x40 + 24 + 0);
        dos->e_magic = 0x5A4D;
        dos->e_lfanew = 0x40;
        nt->Signature = LC_SIG;
        nt->Machine = 0x8664;
        nt->NumberOfSections = 1;
        nt->SizeOfOptionalHeader = 0;
        memcpy(sh->Name, ".d5lc", 6);
        sh->VirtualSize = (unsigned int)g_section_len;
        sh->VirtualAddress = 0x1000;
        sh->SizeOfRawData = (unsigned int)g_section_len;
        sh->PointerToRawData = 0x1000;
        memcpy(g_image + 0x1000, g_section, g_section_len);
    }
    learn_init();
    if (!g_lc) {
        fprintf(stderr, "no section found\n");
        return 3;
    }
    /* the game addresses the section carries, repointed at this test's fixtures */
    *(unsigned long long *)(g_lc + LC_O_PKEY) = (unsigned long long)(uintptr_t)&g_keys;
    *(unsigned long long *)(g_lc + LC_O_PMAX) = (unsigned long long)(uintptr_t)&g_max;
    *(unsigned long long *)(g_lc + LC_O_SAVEDIR) = (unsigned long long)(uintptr_t)g_savedir;
    /* host stand-ins for the two x86 routines the section publishes (see above) */
    host_cap = lcu(LC_O_CAP);
    host_mask = host_cap - 1;
    host_max_used = host_cap / 4 * 3;
    host_shift = 64;
    while ((1u << (64 - host_shift)) < host_cap) host_shift--;   /* log2(cap) high bits of the mix */
    g_lc_put = host_put;
    g_lc_clear = host_clear;

    for (i = 4; i < argc; i++) {
        const char *a = argv[i];
        if (!strncmp(a, "saveslot=", 9)) {
            /* the game's writer published this slot (EVCAP4): slot first, then the sequence number */
            long slot = strtol(a + 9, NULL, 10);
            lcuset(g_lc_ev + 0, (unsigned int)(slot < 0 ? 0xFFFFFFFFu : (unsigned long)slot));
            lcuset(g_lc_ev + 4, lcu(g_lc_ev + 4) + 1);
            learn_tick();
        } else if (!strncmp(a, "load=", 5)) {
            const char *spec = a + 5;
            int slot = atoi(spec);
            int ok = 1;
            const char *colon = strchr(spec, ':');
            if (colon) ok = strcmp(colon + 1, "bad") != 0;
            lcuset(g_lc_ev + 12, (unsigned int)slot);
            lcuset(g_lc_ev + 16, ok ? 1u : 0u);
            lcuset(g_lc_ev + 8, 1);
            learn_tick();
        } else if (!strncmp(a, "put=", 4)) {
            unsigned long long serial = 0;
            unsigned int id = 0;
            const char *spec = a + 4;
            const char *colon = strchr(spec, ':');
            if (!colon) { fprintf(stderr, "bad put %s\n", spec); return 2; }
            serial = strtoull(spec, NULL, 10);
            id = (unsigned int)strtoul(colon + 1, NULL, 10);
            if (!g_lc_put || g_lc_put(serial, id) != 0) { fprintf(stderr, "put refused\n"); }
        } else if (!strncmp(a, "fill=", 5)) {
            /* insert `n` pairs through the section's own lc_put: the capacity ceiling, without 98k argv */
            int n = atoi(a + 5), ok = 0, refused = 0, k;
            for (k = 0; k < n; k++) {
                if (g_lc_put && g_lc_put(1000 + (k / 700), 21000 + (k % 700)) == 0) ok++;
                else refused++;
            }
            printf("fill ok=%d refused=%d\n", ok, refused);
        } else if (!strncmp(a, "remote=", 7)) {
            d5learn_host_remote = atoi(a + 7) ? 1 : 0;
            fprintf(stderr, "host: remote=%d\n", d5learn_host_remote);
        } else if (!strcmp(a, "clear")) {
            if (g_lc_clear) g_lc_clear();
        } else if (!strcmp(a, "fields")) {
            printf("data %p claim %p prefix %p store %p ev %p put %p clear %p\n",
                   (void *)g_lc, (void *)(g_lc - 0), (void *)g_lc_prefix, (void *)g_lc_store,
                   (void *)g_lc_ev, (void *)g_lc_put, (void *)g_lc_clear);
        } else if (!strcmp(a, "state")) {
            printf("state %u used %u cap %u gen %08x base %u saveslot %u saveseq %u\n",
                   lcu(LC_O_STATE), lcu(LC_O_USED), lcu(LC_O_CAP), lcu(LC_O_GEN), lcu(LC_O_BASE_COUNT),
                   lcu(g_lc_ev + 0), lcu(g_lc_ev + 4));
        } else if (!strcmp(a, "dump")) {
            int n = 0;
            unsigned long long *pairs = learn_pairs(&n);
            int k;
            for (k = 0; k < n; k++) printf("%llu %u\n", pairs[k * 2], (unsigned int)pairs[k * 2 + 1]);
            free(pairs);
            printf("-- %d pair(s), quarantine %d\n", n, g_lc_nq);
        } else {
            fprintf(stderr, "unknown action %s\n", a);
            return 2;
        }
    }
    return 0;
}
