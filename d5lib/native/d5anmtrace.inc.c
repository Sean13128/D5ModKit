/* d5anmtrace.inc.c -- animation trace, null-seek guard and actor probe (ANMTRACE1; included by d5auto.c after
 * d5ctl.inc.c, whose command loop calls ctl_anmtrace / ctl_actorprobe / at_tick / at_off).
 *
 * A port of Cryswar's Overlord d5_anm_trace.c + d5_anm_trace_thunks.S (The Unlicense -- thanks, Cryswar): the same
 * five hook sites, the same prologue byte checks (a mismatch skips that hook and logs it), the same register-
 * preserving stubs (callers rely on registers beyond the Win64 ABI: anm_acquire_lzs keeps comparing EDX after its
 * call to anm_find_loaded_slot), the same null guard.  Differences: switched at run time by a harness command
 * (nothing is written into the game's code until `anmtrace on|guard`; `off` and a hot reload put the original bytes
 * back), the site gets a 5-byte jmp rel32 to a stub on the core's near page (0xC00..0xFBF) instead of
 * mov rax, imm64 / jmp rax, every id is logged (no "interesting id" filter: D4 imports use banks below 2000), the
 * script hooks are left out, and the stubs also keep XMM0-5 and the flags.
 *
 *   anmtrace on      trace: group lookup misses, bank requests, unit setup, player create, null seeks
 *   anmtrace guard   the same, and a null seek is skipped (returns) instead of reading [player+0x68]+2 (0x2F5512)
 *   anmtrace off     the original bytes back at every site;  anmtrace status: what is hooked
 *   actorprobe <slot> <frames> | off   once per frame, the battle actor in that actor-table slot (`state` units'
 *                    "slot") and its animation owner / player / record / motion
 *
 * Hook sites (RVAs of the Steam build, PE timestamp 0x5C4E7571 = the decomp in /Volumes/Data/Decomp/d5; written
 * relative to the image so exemap leaves them alone).  Pre stubs tail-jump into the original (stack arguments pass
 * through); post stubs call it from their own frame (only for functions with register arguments only):
 *   0x301240 anm_find_loaded_slot(id) -> slot or -1            post: a miss is logged (id, caller)
 *   0x3FFCB0 anm_acquire_lzs(mgr, id, u8, int) -> loader slot   post: id, flag, arg, slot, caller
 *   0x14E7E0 ui_sprite_set_anm(actor, anim, palette, motion, kind, alt, sign)        pre
 *   0x14DFD0 unit_bind_anm_owner(actor, anim, palette, motion, kind)                 pre
 *   0x2F28C0 anm_owner_restart_at_frame(owner, frame)   pre: owner+0x60 = player; player+0x68 == NULL is the seek
 *            anm_actor_build_render_root would fault on; logged, and skipped in guard mode.
 * Log lines (d5auto.log): "[anmtrace] <event> key=value ..." and "[actorprobe] <event> key=value ...";
 * d5lib/anmtrace.py parses them. */
#define AT_TIMESTAMP 0x5C4E7571u
#define AT_MAX_LINES 4000             /* trace lines per `anmtrace on` */
#define AT_STOLEN 5                   /* every site's first instruction(s): exactly 5 bytes, no rip-relative */
#define AT_PAGE_OFF 0xC00             /* on near_page(); 0xC0 bytes per stub */
#define AT_STUB_MAX 0xC0
#define AP_MAX_FRAMES 3600

/* what a stub hands its handler (rcx): the registers it saved, in push order reversed */
typedef struct {
    unsigned long long r11, r10, r9, r8, rdx, rcx, rax, rflags;   /* at entry */
    unsigned long long ret, home[4], arg5, arg6, arg7;            /* the caller's return address and stack */
} ATREGS;
typedef struct {
    unsigned long long r11, r10, r9, r8, rdx, rcx, rax, rflags;   /* as the original returned them */
    unsigned long long gap[5];                                    /* the original's home space + alignment */
    ATREGS in;
} ATPOST;

static int at_h_lookup(void *), at_h_bank(void *), at_h_setup(void *), at_h_create(void *), at_h_seek(void *);
typedef struct { const char *name; unsigned rva; int post, n; unsigned char sig[15]; int (*fn)(void *); } ATHOOK;
static const ATHOOK AT_HOOKS[] = {      /* Cryswar's prologue bytes */
    {"lookup", 0x00301240u, 1, 15, {0x48,0x89,0x5C,0x24,0x08,0x48,0x89,0x6C,0x24,0x10,0x48,0x89,0x74,0x24,0x18},
     at_h_lookup},
    {"bank", 0x003FFCB0u, 1, 14, {0x40,0x53,0x55,0x56,0x57,0x41,0x57,0x48,0x81,0xEC,0xB0,0x00,0x00,0x00}, at_h_bank},
    {"setup", 0x0014E7E0u, 0, 15, {0x48,0x89,0x5C,0x24,0x08,0x48,0x89,0x6C,0x24,0x10,0x48,0x89,0x74,0x24,0x18},
     at_h_setup},
    {"create", 0x0014DFD0u, 0, 15, {0x48,0x89,0x5C,0x24,0x08,0x48,0x89,0x6C,0x24,0x10,0x48,0x89,0x74,0x24,0x18},
     at_h_create},
    {"seek", 0x002F28C0u, 0, 13, {0x48,0x89,0x74,0x24,0x10,0x57,0x48,0x83,0xEC,0x20,0x48,0x8B,0xF9}, at_h_seek},
};
#define AT_N ((int)(sizeof AT_HOOKS / sizeof AT_HOOKS[0]))

static volatile LONG g_at_mode;          /* 0 off, 1 trace, 2 trace + null-seek guard */
static volatile LONG g_at_lines;
static int g_at_on[AT_N];                /* site patched */
static const char *g_at_why[AT_N];       /* why a hook is not on */
static unsigned char *g_at_stub[AT_N];   /* built once and kept: a thread may still be in one after `off` */

/* ------------------------------------------------------------------ stubs
 * Written into t as if t lay at address `at`; site = the hooked function, stolen = its first AT_STOLEN bytes,
 * fn = the handler.  Entry RSP = 8 mod 16 (the caller's call pushed the return address).
 * pre:  pushfq, push rax rcx rdx r8-r11 (8 x 8: RSP still 8 mod 16); sub rsp,0x88 (0x20 home + XMM0-5 + 8 -> 0 mod
 *       16); handler(rcx = the saved block); restore everything; handler != 0 -> return 0 to the caller (the
 *       original does not run), else jmp to the trampoline (stolen bytes + jmp site+5) with every register and RSP
 *       as at entry.
 * post: save the entry registers (handler sees the arguments); lea rsp,[rsp-0x28] (home + 8 -> 0 mod 16, flags
 *       kept); call the trampoline with every register as at entry; save what it returned (8 pushes, 0 mod 16);
 *       sub rsp,0x80; handler; restore what the original returned (flags included); drop 0x68; ret. */
static int at_stub(unsigned char *t, unsigned long long at, unsigned long long site, const unsigned char *stolen,
                   int post, unsigned long long fn) {
    static const unsigned char save[] = {0x9C, 0x50, 0x51, 0x52, 0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53};
    static const unsigned char rest[] = {0x41, 0x5B, 0x41, 0x5A, 0x41, 0x59, 0x41, 0x58, 0x5A, 0x59, 0x58};
    int k = 0, fix, frame = post ? 0x80 : 0x88;
#define AT_PUT(...) do { const unsigned char b_[] = {__VA_ARGS__}; memcpy(t + k, b_, sizeof b_); k += (int)sizeof b_; } while (0)
    memcpy(t + k, save, sizeof save); k += (int)sizeof save;
    if (post) {
        AT_PUT(0x48, 0x8D, 0x64, 0x24, 0xD8);                       /* lea rsp, [rsp-0x28] */
        t[k++] = 0xE8; fix = k; k += 4;                              /* call trampoline */
        memcpy(t + k, save, sizeof save); k += (int)sizeof save;
    }
    AT_PUT(0x48, 0x81, 0xEC, (unsigned char)frame, 0, 0, 0);         /* sub rsp, frame */
    for (int x = 0; x < 6; x++)                                      /* movdqu [rsp+0x20+16x], xmmx */
        AT_PUT(0xF3, 0x0F, 0x7F, (unsigned char)(0x44 | x << 3), 0x24, (unsigned char)(0x20 + 0x10 * x));
    AT_PUT(0x48, 0x8D, 0x8C, 0x24, (unsigned char)frame, 0, 0, 0);   /* lea rcx, [rsp+frame] */
    t[k++] = 0x48; t[k++] = 0xB8; memcpy(t + k, &fn, 8); k += 8;     /* mov rax, fn */
    AT_PUT(0xFF, 0xD0, 0x85, 0xC0);                                  /* call rax; test eax, eax */
    for (int x = 0; x < 6; x++)                                      /* movdqu xmmx, [rsp+0x20+16x] */
        AT_PUT(0xF3, 0x0F, 0x6F, (unsigned char)(0x44 | x << 3), 0x24, (unsigned char)(0x20 + 0x10 * x));
    AT_PUT(0x48, 0x8D, 0xA4, 0x24, (unsigned char)frame, 0, 0, 0);   /* lea rsp, [rsp+frame] */
    memcpy(t + k, rest, sizeof rest); k += (int)sizeof rest;         /* pop r11 .. rax */
    if (post) {
        AT_PUT(0x9D, 0x48, 0x8D, 0x64, 0x24, 0x68, 0xC3);           /* popfq; lea rsp, [rsp+0x68]; ret */
    } else {
        AT_PUT(0x75, 0x06, 0x9D);                                    /* jnz skip; popfq */
        t[k++] = 0xE9; fix = k; k += 4;                              /* jmp trampoline */
        AT_PUT(0x9D, 0x31, 0xC0, 0xC3);                              /* skip: popfq; xor eax, eax; ret */
    }
#undef AT_PUT
    int tramp = k;
    *(int *)(t + fix) = tramp - (fix + 4);
    memcpy(t + k, stolen, AT_STOLEN); k += AT_STOLEN;
    t[k++] = 0xE9;
    *(int *)(t + k) = (int)(long long)((site + AT_STOLEN) - (at + k + 4)); k += 4;
    return k;
}

static int at_patch(unsigned char *site, const unsigned char *b) {
    DWORD old;
    if (!VirtualProtect(site, AT_STOLEN, PAGE_EXECUTE_READWRITE, &old)) return 0;
    memcpy(site, b, AT_STOLEN);
    VirtualProtect(site, AT_STOLEN, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, AT_STOLEN);
    return 1;
}

/* NULL = hooked (or already); else why not */
static const char *at_install(int i) {
    const ATHOOK *h = &AT_HOOKS[i];
    unsigned char *site = g_base + h->rva, *pg = near_page(), j[AT_STOLEN];
    if (g_at_on[i]) return NULL;
    if (!readable(site, h->n) || memcmp(site, h->sig, h->n)) return "prologue mismatch";
    if (!pg) return "no near page";
    if (!g_at_stub[i]) {
        unsigned char *t = pg + AT_PAGE_OFF + i * AT_STUB_MAX;
        if (at_stub(t, (unsigned long long)t, (unsigned long long)site, site, h->post, (unsigned long long)h->fn)
            > AT_STUB_MAX) return "stub too long";
        g_at_stub[i] = t;
    }
    j[0] = 0xE9;
    *(int *)(j + 1) = (int)(g_at_stub[i] - (site + 5));
    if (!at_patch(site, j)) return "VirtualProtect failed";
    g_at_on[i] = 1;
    return NULL;
}

/* every site back to its original bytes (the signature's first 5); also on hot reload (ctl_stop) */
static void at_off(void) {
    InterlockedExchange(&g_at_mode, 0);
    for (int i = 0; i < AT_N; i++)
        if (g_at_on[i] && at_patch(g_base + AT_HOOKS[i].rva, AT_HOOKS[i].sig)) g_at_on[i] = 0;
}

/* ------------------------------------------------------------------ handlers (any thread) */
static int at_budget(void) {
    LONG n = InterlockedIncrement(&g_at_lines);
    if (n == AT_MAX_LINES + 1) logf_("[anmtrace] cap lines=%d", AT_MAX_LINES);
    return n <= AT_MAX_LINES;
}
static unsigned long long at_rva(unsigned long long a) {
    return in_image((const void *)a, 1) ? a - (unsigned long long)g_base : a;
}
static int at_slot(unsigned long long actor) {     /* battle actor table index, or -1 */
    unsigned long long t = (unsigned long long)G(VA_ACTORS);
    return actor >= t && actor < t + (unsigned long long)ACTOR_COUNT * ACTOR_SIZE && !((actor - t) % ACTOR_SIZE)
        ? (int)((actor - t) / ACTOR_SIZE) : -1;
}

static int at_h_lookup(void *p) {
    ATPOST *b = (ATPOST *)p;
    InterlockedIncrement(&g_inflight);
    if (g_at_mode && (int)b->rax < 0 && at_budget())
        logf_("[anmtrace] miss id=%d caller=0x%llx", (int)b->in.rcx, at_rva(b->in.ret));
    InterlockedDecrement(&g_inflight);
    return 0;
}

static int at_h_bank(void *p) {
    ATPOST *b = (ATPOST *)p;
    InterlockedIncrement(&g_inflight);
    if (g_at_mode && at_budget())
        logf_("[anmtrace] bank id=%d flag=%d arg=%d slot=%d caller=0x%llx", (int)b->in.rdx,
              (int)(unsigned char)b->in.r8, (int)b->in.r9, (int)b->rax, at_rva(b->in.ret));
    InterlockedDecrement(&g_inflight);
    return 0;
}

static int at_h_setup(void *p) {
    ATREGS *b = (ATREGS *)p;
    InterlockedIncrement(&g_inflight);
    if (g_at_mode && at_budget())
        logf_("[anmtrace] setup actor=0x%llx slot=%d anim=%d palette=%d motion=%d kind=%d alt=%d sign=%d caller=0x%llx",
              b->rcx, at_slot(b->rcx), (int)b->rdx, (int)b->r8, (int)b->r9, (int)b->arg5, (int)b->arg6, (int)b->arg7,
              at_rva(b->ret));
    InterlockedDecrement(&g_inflight);
    return 0;
}

static int at_h_create(void *p) {
    ATREGS *b = (ATREGS *)p;
    InterlockedIncrement(&g_inflight);
    if (g_at_mode && at_budget())
        logf_("[anmtrace] create actor=0x%llx slot=%d anim=%d palette=%d motion=%d kind=%d caller=0x%llx", b->rcx,
              at_slot(b->rcx), (int)(short)b->rdx, (int)(short)b->r8, (int)(short)b->r9, (int)b->arg5,
              at_rva(b->ret));
    InterlockedDecrement(&g_inflight);
    return 0;
}

/* nonzero = skip the original (guard mode, player without a motion entry) */
static int at_h_seek(void *p) {
    ATREGS *b = (ATREGS *)p;
    const unsigned char *o = (const unsigned char *)b->rcx;
    const unsigned char *pl = o ? *(const unsigned char *const *)(o + 0x60) : NULL;   /* the original reads it too */
    int skip;
    if (!pl || *(void *const *)(pl + 0x68)) return 0;
    InterlockedIncrement(&g_inflight);
    skip = g_at_mode == 2;
    if (g_at_mode && at_budget())
        logf_("[anmtrace] nullseek owner=0x%llx player=0x%llx group=%d motion=%d palette=%d frame=%d guard=%d "
              "caller=0x%llx", b->rcx, (unsigned long long)pl, *(const short *)(o + 0x20), *(const short *)(o + 0x22),
              o[0x24], (int)b->rdx, skip, at_rva(b->ret));
    InterlockedDecrement(&g_inflight);
    return skip;
}

/* ------------------------------------------------------------------ commands */
static void ctl_anmtrace(SB *o, int argc, char **argv) {
    static const char *const MODES[] = {"off", "on", "guard"};
    const char *m = argc > 1 ? argv[1] : "status";
    int want = !strcmp(m, "off") ? 0 : !strcmp(m, "on") ? 1 : !strcmp(m, "guard") ? 2 : -1;
    if (want < 0 && strcmp(m, "status")) {
        sbf(o, "{\"error\":\"usage: anmtrace on|guard|off|status\"}");
        return;
    }
    if (want > 0) {
        IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_base + ((IMAGE_DOS_HEADER *)g_base)->e_lfanew);
        if (nt->FileHeader.TimeDateStamp != AT_TIMESTAMP) {
            sbf(o, "{\"error\":\"refused\",\"reason\":\"unsupported game build (PE timestamp)\"}");
            return;
        }
        InterlockedExchange(&g_at_lines, 0);
        InterlockedExchange(&g_at_mode, want);
        for (int i = 0; i < AT_N; i++) {
            g_at_why[i] = at_install(i);
            if (g_at_why[i])
                logf_("[anmtrace] skip hook=%s rva=0x%X reason=%s", AT_HOOKS[i].name, AT_HOOKS[i].rva,
                      g_at_why[i][0] == 'p' ? "prologue" : "install");
        }
    } else if (!want) {
        at_off();
    }
    char line[160];
    int k = snprintf(line, sizeof line, "[anmtrace] state mode=%s", MODES[g_at_mode]);
    sbf(o, "{\"ok\":1,\"mode\":\"%s\",\"hooks\":{", MODES[g_at_mode]);
    for (int i = 0; i < AT_N; i++) {
        sbf(o, "%s\"%s\":", i ? "," : "", AT_HOOKS[i].name);
        sb_str(o, g_at_on[i] ? "on" : g_at_mode && g_at_why[i] ? g_at_why[i] : "off");
        k += snprintf(line + k, sizeof line - k, " %s=%d", AT_HOOKS[i].name, g_at_on[i]);
    }
    sbf(o, "}}");
    if (want >= 0) logf_("%s", line);
}

/* ------------------------------------------------------------------ voicetrace (VOICE2)
 * Which voice LINE the game asks for, without ears: the agent's game runs with voice volume 0, the bank mount only
 * shows the voice SET, and the manager's "playing" list (+0x808) stays empty at any sampling rate we can afford.
 *   voicetrace on | off | status
 * One pre hook, built with the anmtrace stub, off until `voicetrace on` (nothing is written into the game before):
 *   0x0AEF60 sound_voice_table_lookup(?, line id in EDX) -> row or NULL.  Its first two instructions are exactly
 *   5 bytes without a rip-relative operand (mov r9d, edx; test edx, edx).  It has two callers: sound_voice_play
 *   0x3F7900 (first statement, before the "already playing" and bank checks: return address 0x3F7954) and
 *   0x3F7FCF.  sound_voice_play itself cannot take the 5-byte jump (mov rax,rsp; push rbp; push r12 = 6 bytes).
 * Log line: "[voicetrace] lookup line=<id> set=<id / 1000> caller=0x<rva>"; play requests are the lines whose caller
 * is 0x3f7954 (d5lib/anmtrace.py voice_requests).  line id = voice set * 1000 + n, voice set = kind * 100000 +
 * voice id * 10 + personality; the n-th line of a custom voice is the n-th the kit wrote (voices.custom_lines).
 * Stub: near page 0x600-0x6BF (free: 0x000-0x540 others, 0x700 recording, 0x800-0xBFF fx, 0xC00-0xFBF anmtrace). */
#define VT_RVA 0x000AEF60u
#define VT_PAGE_OFF 0x600
static const unsigned char VT_SIG[AT_STOLEN] = {0x44, 0x8B, 0xCA, 0x85, 0xD2};
static volatile LONG g_vt_mode, g_vt_lines;
static int g_vt_on;
static unsigned char *g_vt_stub;

static int vt_h(void *p) {
    ATREGS *b = (ATREGS *)p;
    InterlockedIncrement(&g_inflight);
    if (g_vt_mode) {
        LONG n = InterlockedIncrement(&g_vt_lines);
        if (n <= AT_MAX_LINES)
            logf_("[voicetrace] lookup line=%d set=%d caller=0x%llx", (int)b->rdx, (int)b->rdx / 1000, at_rva(b->ret));
        else if (n == AT_MAX_LINES + 1)
            logf_("[voicetrace] cap lines=%d", AT_MAX_LINES);
    }
    InterlockedDecrement(&g_inflight);
    return 0;                                   /* never skips the original */
}

static void vt_off(void) {                      /* the original bytes back; also on hot reload (ctl_stop) */
    InterlockedExchange(&g_vt_mode, 0);
    if (g_vt_on && at_patch(g_base + VT_RVA, VT_SIG)) g_vt_on = 0;
}

static void ctl_voicetrace(SB *o, int argc, char **argv) {
    const char *m = argc > 1 ? argv[1] : "status", *why = NULL;
    if (!strcmp(m, "on") && !g_vt_on) {
        IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_base + ((IMAGE_DOS_HEADER *)g_base)->e_lfanew);
        unsigned char *site = g_base + VT_RVA, *pg = near_page(), j[AT_STOLEN];
        if (nt->FileHeader.TimeDateStamp != AT_TIMESTAMP) why = "unsupported game build (PE timestamp)";
        else if (!readable(site, AT_STOLEN) || memcmp(site, VT_SIG, AT_STOLEN)) why = "prologue mismatch";
        else if (!pg) why = "no near page";
        else {
            if (!g_vt_stub) {
                unsigned char *t = pg + VT_PAGE_OFF;
                if (at_stub(t, (unsigned long long)t, (unsigned long long)site, site, 0, (unsigned long long)vt_h)
                    > AT_STUB_MAX) why = "stub too long";
                else g_vt_stub = t;
            }
            if (g_vt_stub) {
                j[0] = 0xE9;
                *(int *)(j + 1) = (int)(g_vt_stub - (site + 5));
                if (at_patch(site, j)) g_vt_on = 1; else why = "VirtualProtect failed";
            }
        }
        if (g_vt_on) { InterlockedExchange(&g_vt_lines, 0); InterlockedExchange(&g_vt_mode, 1); }
    } else if (!strcmp(m, "on")) {
        InterlockedExchange(&g_vt_lines, 0);
        InterlockedExchange(&g_vt_mode, 1);
    } else if (!strcmp(m, "off")) {
        vt_off();
    } else if (strcmp(m, "status")) {
        sbf(o, "{\"error\":\"usage: voicetrace on|off|status\"}");
        return;
    }
    if (why) {
        sbf(o, "{\"error\":\"refused\",\"reason\":");
        sb_str(o, why);
        sbf(o, "}");
        return;
    }
    sbf(o, "{\"ok\":1,\"mode\":\"%s\",\"hooked\":%d,\"lines\":%ld}", g_vt_mode ? "on" : "off", g_vt_on,
        (long)g_vt_lines);
    if (strcmp(m, "status")) logf_("[voicetrace] state mode=%s hooked=%d", g_vt_mode ? "on" : "off", g_vt_on);
}

static struct { int slot, left, n; } g_ap;

static void ctl_actorprobe(SB *o, int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "off")) {
        g_ap.left = 0;
        sbf(o, "{\"ok\":1,\"probe\":\"off\"}");
        return;
    }
    int slot = argc > 2 ? atoi(argv[1]) : -1, frames = argc > 2 ? atoi(argv[2]) : 0;
    if (slot < 0 || slot >= ACTOR_COUNT || frames < 1) {
        sbf(o, "{\"error\":\"usage: actorprobe <slot 0..%d> <frames> | actorprobe off\"}", ACTOR_COUNT - 1);
        return;
    }
    if (frames > AP_MAX_FRAMES) frames = AP_MAX_FRAMES;
    g_ap.slot = slot; g_ap.left = frames; g_ap.n = 0;
    logf_("[actorprobe] start slot=%d frames=%d", slot, frames);
    sbf(o, "{\"ok\":1,\"slot\":%d,\"frames\":%d}", slot, frames);
}

/* one probe line per frame (ctl_tick).  Offsets (decomp, Steam build):
 *   actor   +0x2A0 bound anm (ui_sprite_set_anm), +0x1E4 loader slot / +0x1E8 pending anm / +0x1EC pending motion
 *           (ui_sprite_set_anm, unit_deferred_anm_bind), +0x2E2 kind (unit_bind_anm_owner), +0x2E6 / +0x2E8 the two
 *           bytes ui_sprite_draw needs non-zero, +0x1D0 the animation owner
 *   owner   +0x20 group / +0x22 motion / +0x24 palette (unit_bind_anm_owner), +0x60 the player
 *   player  +0x28 tick (Q16), +0x30 / +0x40 step masks, +0x3C ended/held (anm_actor_advance), +0x3A palette,
 *           +0x3E loaded slot (-1 = group lookup missed), +0x60 record, +0x68 motion entry
 *           (anm_instance_load_anim_and_motion, anm_owner_create_instance)
 *   record  +0x08 id, +0x10 palette count, +0x12 texture count (anm_find_loaded_record, anm_render_node_hierarchy)
 *   motion  +0x00 motion id (anm_actor_select_motion) */
static void at_tick(void) {
    if (g_ap.left <= 0) return;
    g_ap.left--;
    const unsigned char *a = (const unsigned char *)G(VA_ACTORS) + (SIZE_T)g_ap.slot * ACTOR_SIZE;
    char s[640];
    int k = snprintf(s, sizeof s, "[actorprobe] sample slot=%d frame=%ld n=%d", g_ap.slot, (long)g_frame, g_ap.n++);
#define AP_ADD(...) (k += snprintf(s + k, sizeof s - k, __VA_ARGS__))
    if (!readable(a, ACTOR_SIZE)) { AP_ADD(" actor=none"); logf_("%s", s); return; }
    AP_ADD(" anm=%d loader=%d pend_anm=%d pend_motion=%d kind=%d vis=%d draw=%d", *(const int *)(a + 0x2A0),
           *(const int *)(a + 0x1E4), *(const int *)(a + 0x1E8), *(const int *)(a + 0x1EC),
           *(const unsigned short *)(a + 0x2E2), a[0x2E6], a[0x2E8]);
    const unsigned char *ow = *(const unsigned char *const *)(a + 0x1D0);
    if (!ow || !readable(ow, 0x68)) { AP_ADD(" owner=none"); logf_("%s", s); return; }
    AP_ADD(" o_group=%d o_motion=%d o_palette=%d", *(const short *)(ow + 0x20), *(const short *)(ow + 0x22), ow[0x24]);
    const unsigned char *pl = *(const unsigned char *const *)(ow + 0x60);
    if (!pl || !readable(pl, 0x70)) { AP_ADD(" player=none"); logf_("%s", s); return; }
    AP_ADD(" tick=%d step30=%d step40=%d held=%d palette=%d pslot=%d", *(const int *)(pl + 0x28),
           *(const int *)(pl + 0x30), *(const int *)(pl + 0x40), pl[0x3C], (signed char)pl[0x3A],
           *(const short *)(pl + 0x3E));
    const unsigned char *rec = *(const unsigned char *const *)(pl + 0x60);
    if (rec && readable(rec, 0x14))
        AP_ADD(" rec=%d npal=%d ntex=%d", *(const unsigned short *)(rec + 8), *(const short *)(rec + 0x10),
               *(const short *)(rec + 0x12));
    else AP_ADD(" rec=none");
    const unsigned char *mo = *(const unsigned char *const *)(pl + 0x68);
    if (mo && readable(mo, 4)) AP_ADD(" motion=%d", *(const unsigned short *)mo);
    else AP_ADD(" motion=none");
#undef AP_ADD
    logf_("%s", s);
}
