/* d5wwatch.inc.c -- software write-watch (WRITEWATCH1; included by d5auto.c after d5ctl.inc.c, whose command loop
 * calls ctl_watch and whose ctl_stop calls ww_off).  Research/debug only: the command pipe exists only with
 * [debug] remote=1, and nothing is protected or hooked until a `watch` command arrives.
 *
 * Why: the hardware watchpoints of `trace` (DR0-3) never fire under CrossOver on Apple silicon (DD2CRASH2).  This
 * uses page protection instead:
 *   watch ADDR LEN [tf|spin]   the page(s) holding [ADDR, ADDR+LEN) (LEN 1..64; ADDR 0x14xxxxxxx = static VA) become
 *                       read-only.  Every write to them faults; the vectored handler (first in the chain) saves the
 *                       thread's registers and the range's bytes, makes the page(s) writable again and
 *                         tf    (default) sets the trap flag: after that one instruction the single-step exception
 *                               arrives on the same thread, the handler compares the range (changed -> a CHANGE
 *                               record naming the faulting instruction) and makes the page(s) read-only again;
 *                         spin  (fallback if the single step never comes) a helper thread re-protects at once and
 *                               attributes a change to the last fault it saw (less exact: say so when used).
 *                       A fault whose address lies in [ADDR-64, ADDR+LEN) also gets a NEAR record at once, so a
 *                       writer is named even if the single step never arrives.
 *   watch status        counters: faults, steps, changes, near, records, slot overflows, per-frame cost
 *   watch dump          the distinct faulting instructions (also out of range) with counts and the last address
 *   watch off           protection back, nothing armed (the handler stays registered, inert, until unload)
 *   watch selftest      a private page: one out-of-range and one in-range write from ww_selftest_poke; PASS only if
 *                       the counters add up and the CHANGE record names that function (it can fail)
 * Records go to d5auto.log as "[wwatch] <kind> n=<k> key=value ..." lines (d5lib/wwatch.py parses them):
 *   change/near: frame, thread, rip (static VA or module+offset), fault address, offset into the range, 16
 *   instruction bytes, old and new bytes;  regs: every GPR and rflags at the fault;  stack: the call chain unwound
 *   with the exe's .pdata;  raw: the top 64 stack qwords (in case the unwind fails).
 * Limits: while one thread single-steps its write the page is writable for every thread (another thread's write in
 * that window is not seen, and could be attributed to the stepping thread if it hits the range); a write done by the
 * system on the game's behalf (a syscall filling a buffer in the page) returns an error instead of faulting; every
 * write to the watched page costs two exceptions (fps cost: `watch status`). */

#define WW_SLOTS 64
#define WW_RIPS 128
#define WW_MAXREC 32
#define WW_NEAR 64

/* ---- pure helpers (host-tested in tests/test_wwatch1.py) ---- */
static void ww_span(unsigned long long a, unsigned long long len, unsigned long long page, unsigned long long *pg,
                    unsigned long long *pglen) {
    *pg = a & ~(page - 1);
    *pglen = ((a + len + page - 1) & ~(page - 1)) - *pg;
}
static int ww_is_near(unsigned long long f, unsigned long long lo, unsigned long long len) {
    return f + WW_NEAR >= lo && f < lo + len;
}
static int ww_hex(char *o, size_t cap, const unsigned char *b, int n) {
    int k = 0;
    for (int i = 0; i < n && (size_t)k + 3 <= cap; i++) k += snprintf(o + k, cap - k, "%02x", b[i]);
    if (!n && cap) o[0] = 0;
    return k;
}

#ifndef WW_HOST_ONLY
typedef struct {
    volatile LONG tid;                 /* owning thread (0 = free) */
    int isnear;
    DWORD64 addr;
    unsigned char old[64];
    CONTEXT ctx;                       /* registers at the fault */
} WWSLOT;
static WWSLOT g_ww_slot[WW_SLOTS];
static struct { volatile LONG64 rip; volatile LONG n; volatile LONG64 last; } g_ww_rip[WW_RIPS];
static unsigned char *g_ww_lo, *g_ww_pg;
static SIZE_T g_ww_len, g_ww_pglen;
static DWORD g_ww_prot;                /* the pages' protection before arming (restored by off) */
static volatile LONG g_ww_armed, g_ww_mode;   /* mode 0 tf, 1 spin */
static volatile LONG g_ww_faults, g_ww_steps, g_ww_changes, g_ww_nnear, g_ww_records, g_ww_full, g_ww_foreign;
static volatile LONG g_ww_dirty;
static volatile LONG64 g_ww_last_change_rip;
static PVOID g_ww_veh;
static HANDLE g_ww_spin;
static long g_ww_frame0;
static LARGE_INTEGER g_ww_t0;
static unsigned char g_ww_snap[64];    /* spin mode: the range as last re-protected */
static CONTEXT g_ww_lastctx;           /* spin mode: the last fault */
static DWORD64 g_ww_lastaddr;
static volatile LONG g_ww_lastlock;

static void ww_name(DWORD64 a, char *o, size_t cap) {
    if (a >= (DWORD64)g_base && a < (DWORD64)g_base + g_image_size) { snprintf(o, cap, "%llx", to_static(a)); return; }
    HMODULE m = NULL;
    char p[MAX_PATH];
    if (a >= 0x10000 && GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)a, &m) && m &&
        GetModuleFileNameA(m, p, sizeof p)) {
        const char *b = strrchr(p, '\\');
        snprintf(o, cap, "%s+%llx", b ? b + 1 : p, (unsigned long long)(a - (DWORD64)m));
    } else snprintf(o, cap, "%llx", (unsigned long long)a);
}

static void ww_count_rip(DWORD64 rip, DWORD64 addr) {
    unsigned h = (unsigned)((rip * 0x9E3779B97F4A7C15ULL) >> 57) & (WW_RIPS - 1);
    for (int i = 0; i < WW_RIPS; i++, h = (h + 1) & (WW_RIPS - 1)) {
        LONG64 cur = g_ww_rip[h].rip;
        if (!cur) cur = InterlockedCompareExchange64(&g_ww_rip[h].rip, (LONG64)rip, 0);
        if (!cur || cur == (LONG64)rip) {
            InterlockedIncrement(&g_ww_rip[h].n);
            g_ww_rip[h].last = (LONG64)addr;
            return;
        }
    }
}

static WWSLOT *ww_slot(DWORD tid, int claim) {
    for (int i = 0; i < WW_SLOTS; i++)
        if (g_ww_slot[i].tid == (LONG)tid) return &g_ww_slot[i];
    if (!claim) return NULL;
    for (int i = 0; i < WW_SLOTS; i++)
        if (!g_ww_slot[i].tid && !InterlockedCompareExchange(&g_ww_slot[i].tid, (LONG)tid, 0)) return &g_ww_slot[i];
    return NULL;
}

/* one record: kind (change / near / spinchange), registers at the fault, the bytes before/after */
static void ww_record(const char *kind, const CONTEXT *c, DWORD64 addr, const unsigned char *old,
                      const unsigned char *now) {
    LONG k = InterlockedIncrement(&g_ww_records);
    if (k > WW_MAXREC) return;
    char rip[96], ins[40], ob[132], nb[132];
    ww_name(c->Rip, rip, sizeof rip);
    ww_hex(ins, sizeof ins, (const unsigned char *)c->Rip, 16);
    int n = (int)(g_ww_len > 64 ? 64 : g_ww_len);
    ww_hex(ob, sizeof ob, old, old ? n : 0);
    ww_hex(nb, sizeof nb, now, now ? n : 0);
    logf_("[wwatch] %s n=%ld frame=%ld tid=%lu rip=%s addr=%llx off=%lld ins=%s old=%s new=%s", kind, (long)k,
          (long)g_frame, (unsigned long)GetCurrentThreadId(), rip, to_static(addr),
          (long long)((unsigned char *)addr - g_ww_lo), ins, ob, now ? nb : "-");
    logf_("[wwatch] regs n=%ld rax=%llx rbx=%llx rcx=%llx rdx=%llx rsi=%llx rdi=%llx rbp=%llx rsp=%llx r8=%llx r9=%llx "
          "r10=%llx r11=%llx r12=%llx r13=%llx r14=%llx r15=%llx rflags=%lx", (long)k, c->Rax, c->Rbx, c->Rcx,
          c->Rdx, c->Rsi, c->Rdi, c->Rbp, c->Rsp, c->R8, c->R9, c->R10, c->R11, c->R12, c->R13, c->R14, c->R15,
          (unsigned long)c->EFlags);
    char stack[1200];
    int m = 0;
    CONTEXT u = *c;
    for (int f = 0; f < 32 && m < (int)sizeof stack - 100; f++) {
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
        char nm[96];
        ww_name(u.Rip, nm, sizeof nm);
        m += snprintf(stack + m, sizeof stack - m, " %s", nm);
    }
    logf_("[wwatch] stack n=%ld%s", (long)k, stack);
    char raw[64 * 17 + 8];
    int r = 0;
    const DWORD64 *sp = (const DWORD64 *)c->Rsp;
    MEMORY_BASIC_INFORMATION mb;
    int q = 0;
    if (VirtualQuery(sp, &mb, sizeof mb) && mb.State == MEM_COMMIT) {
        DWORD64 end = (DWORD64)mb.BaseAddress + mb.RegionSize;
        q = (int)((end - (DWORD64)sp) / 8);
        if (q > 64) q = 64;
    }
    for (int i = 0; i < q; i++) r += snprintf(raw + r, sizeof raw - r, " %llx", (unsigned long long)sp[i]);
    logf_("[wwatch] raw n=%ld rsp=%llx%s", (long)k, (unsigned long long)c->Rsp, raw);
}

static void ww_protect(int ro) {
    DWORD o;
    VirtualProtect(g_ww_pg, g_ww_pglen, ro ? PAGE_READONLY : g_ww_prot, &o);
}

static LONG CALLBACK ww_veh(EXCEPTION_POINTERS *ep) {
    DWORD code = ep->ExceptionRecord->ExceptionCode;
    CONTEXT *c = ep->ContextRecord;
    if (code == EXCEPTION_ACCESS_VIOLATION) {
        if (!g_ww_armed || ep->ExceptionRecord->NumberParameters < 2) return EXCEPTION_CONTINUE_SEARCH;
        ULONG_PTR *inf = ep->ExceptionRecord->ExceptionInformation;
        unsigned char *f = (unsigned char *)inf[1];
        if (inf[0] != 1 || f < g_ww_pg || f >= g_ww_pg + g_ww_pglen) return EXCEPTION_CONTINUE_SEARCH;
        InterlockedIncrement(&g_ww_faults);
        ww_count_rip(to_static(c->Rip), to_static((DWORD64)f));
        int n = (int)(g_ww_len > 64 ? 64 : g_ww_len);
        int isnear = ww_is_near((unsigned long long)f, (unsigned long long)g_ww_lo, g_ww_len);
        if (isnear) {
            InterlockedIncrement(&g_ww_nnear);
            ww_record("near", c, (DWORD64)f, g_ww_lo, NULL);
        }
        if (g_ww_mode == 0) {
            WWSLOT *s = ww_slot(GetCurrentThreadId(), 1);
            if (s) {
                s->addr = (DWORD64)f;
                s->isnear = isnear;
                memcpy(s->old, g_ww_lo, n);
                s->ctx = *c;
            } else InterlockedIncrement(&g_ww_full);
            ww_protect(0);
            c->EFlags |= 0x100;                        /* TF: one instruction, then EXCEPTION_SINGLE_STEP */
        } else {
            while (InterlockedExchange(&g_ww_lastlock, 1)) YieldProcessor();
            g_ww_lastctx = *c;
            g_ww_lastaddr = (DWORD64)f;
            InterlockedExchange(&g_ww_lastlock, 0);
            ww_protect(0);
            InterlockedExchange(&g_ww_dirty, 1);
        }
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    if (code == EXCEPTION_SINGLE_STEP) {
        WWSLOT *s = ww_slot(GetCurrentThreadId(), 0);
        if (!s) return EXCEPTION_CONTINUE_SEARCH;
        InterlockedIncrement(&g_ww_steps);
        c->EFlags &= ~0x100u;
        int n = (int)(g_ww_len > 64 ? 64 : g_ww_len);
        if (memcmp(s->old, g_ww_lo, n)) {
            InterlockedIncrement(&g_ww_changes);
            InterlockedExchange64(&g_ww_last_change_rip, (LONG64)s->ctx.Rip);
            ww_record("change", &s->ctx, s->addr, s->old, g_ww_lo);
        }
        InterlockedExchange(&s->tid, 0);
        if (g_ww_armed) ww_protect(1);
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static DWORD WINAPI ww_spin_thread(LPVOID p) {
    (void)p;
    int n = (int)(g_ww_len > 64 ? 64 : g_ww_len);
    while (g_ww_armed && g_ww_mode == 1) {
        if (!InterlockedExchange(&g_ww_dirty, 0)) { SwitchToThread(); continue; }
        SwitchToThread();                              /* let the faulting thread finish its instruction */
        ww_protect(1);
        if (memcmp(g_ww_snap, g_ww_lo, n)) {
            CONTEXT c;
            DWORD64 a;
            while (InterlockedExchange(&g_ww_lastlock, 1)) YieldProcessor();
            c = g_ww_lastctx;
            a = g_ww_lastaddr;
            InterlockedExchange(&g_ww_lastlock, 0);
            InterlockedIncrement(&g_ww_changes);
            InterlockedExchange64(&g_ww_last_change_rip, (LONG64)c.Rip);
            ww_record("spinchange", &c, a, g_ww_snap, g_ww_lo);
            memcpy(g_ww_snap, g_ww_lo, n);
        }
    }
    return 0;
}

static void ww_reset(void) {
    memset((void *)g_ww_rip, 0, sizeof g_ww_rip);
    for (int i = 0; i < WW_SLOTS; i++) g_ww_slot[i].tid = 0;
    g_ww_faults = g_ww_steps = g_ww_changes = g_ww_nnear = g_ww_records = g_ww_full = g_ww_foreign = 0;
    g_ww_last_change_rip = 0;
    g_ww_dirty = 0;
}

/* arm on a runtime range; returns NULL or the reason it refused */
static const char *ww_arm(unsigned char *lo, SIZE_T len, int mode) {
    if (g_ww_armed) return "already armed (watch off first)";
    if (!len || len > 64) return "LEN must be 1..64";
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    unsigned long long pg, pglen;
    ww_span((unsigned long long)lo, len, si.dwPageSize, &pg, &pglen);
    MEMORY_BASIC_INFORMATION mb;
    if (!VirtualQuery((void *)pg, &mb, sizeof mb) || mb.State != MEM_COMMIT) return "range not committed";
    if (!(mb.Protect & (PAGE_READWRITE | PAGE_WRITECOPY))) return "page is not plain read/write";
    if ((unsigned long long)mb.BaseAddress + mb.RegionSize < pg + pglen) return "range spans two regions";
    ww_reset();
    g_ww_lo = lo;
    g_ww_len = len;
    g_ww_pg = (unsigned char *)pg;
    g_ww_pglen = (SIZE_T)pglen;
    g_ww_prot = mb.Protect & 0xff;
    g_ww_mode = mode;
    memcpy(g_ww_snap, lo, len);
    if (!g_ww_veh) g_ww_veh = AddVectoredExceptionHandler(1, ww_veh);
    if (!g_ww_veh) return "AddVectoredExceptionHandler failed";
    g_ww_frame0 = g_frame;
    QueryPerformanceCounter(&g_ww_t0);
    InterlockedExchange(&g_ww_armed, 1);
    DWORD o;
    if (!VirtualProtect(g_ww_pg, g_ww_pglen, PAGE_READONLY, &o)) {
        InterlockedExchange(&g_ww_armed, 0);
        return "VirtualProtect failed";
    }
    if (mode == 1) g_ww_spin = CreateThread(NULL, 0, ww_spin_thread, NULL, 0, NULL);
    logf_("[wwatch] armed lo=%llx len=%lu page=%llx pages=%lu prot=%lx mode=%s", to_static((DWORD64)lo),
          (unsigned long)len, to_static(pg), (unsigned long)(pglen / si.dwPageSize), (unsigned long)g_ww_prot,
          mode ? "spin" : "tf");
    return NULL;
}

static void ww_disarm(void) {
    if (!g_ww_armed) return;
    InterlockedExchange(&g_ww_armed, 0);
    ww_protect(0);
    if (g_ww_spin) {
        WaitForSingleObject(g_ww_spin, 1000);
        CloseHandle(g_ww_spin);
        g_ww_spin = NULL;
    }
    logf_("[wwatch] off faults=%ld steps=%ld changes=%ld near=%ld records=%ld full=%ld", (long)g_ww_faults,
          (long)g_ww_steps, (long)g_ww_changes, (long)g_ww_nnear, (long)g_ww_records, (long)g_ww_full);
}

static void ww_off(void) {                 /* hot reload / unload: nothing may point into this DLL afterwards */
    ww_disarm();
    if (g_ww_veh) {
        for (int i = 0; i < 50; i++) {     /* a thread still between its fault and its single step */
            int busy = 0;
            for (int s = 0; s < WW_SLOTS; s++) busy |= g_ww_slot[s].tid != 0;
            if (!busy) break;
            Sleep(10);
        }
        RemoveVectoredExceptionHandler(g_ww_veh);
        g_ww_veh = NULL;
    }
}

static void ww_status(SB *o) {
    LARGE_INTEGER t, fq;
    QueryPerformanceCounter(&t);
    QueryPerformanceFrequency(&fq);
    double s = g_ww_t0.QuadPart ? (double)(t.QuadPart - g_ww_t0.QuadPart) / (double)fq.QuadPart : 0;
    long fr = g_frame - g_ww_frame0;
    sbf(o, "{\"ok\":1,\"armed\":%ld,\"mode\":\"%s\",\"lo\":\"%llx\",\"len\":%lu,\"faults\":%ld,\"steps\":%ld,"
           "\"changes\":%ld,\"near\":%ld,\"records\":%ld,\"full\":%ld,\"frames\":%ld,\"seconds\":%.2f,"
           "\"fps\":%.2f,\"faults_per_frame\":%.1f,\"last_change_rip\":\"%llx\"}",
        (long)g_ww_armed, g_ww_mode ? "spin" : "tf", g_ww_lo ? to_static((DWORD64)g_ww_lo) : 0ull,
        (unsigned long)g_ww_len, (long)g_ww_faults, (long)g_ww_steps, (long)g_ww_changes, (long)g_ww_nnear,
        (long)g_ww_records, (long)g_ww_full, fr, s, s > 0 ? fr / s : 0.0, fr > 0 ? (double)g_ww_faults / fr : 0.0,
        to_static((DWORD64)g_ww_last_change_rip));
}

__attribute__((noinline)) static void ww_selftest_poke(volatile unsigned long long *p, unsigned long long v) {
    *p = v;
}

static void ww_selftest(SB *o, int mode) {
    if (g_ww_armed) { sbf(o, "{\"error\":\"a watch is armed (watch off first)\"}"); return; }
    unsigned char *pg = (unsigned char *)VirtualAlloc(NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!pg) { sbf(o, "{\"error\":\"VirtualAlloc failed\"}"); return; }
    const char *why = ww_arm(pg + 0x100, 8, mode);
    if (why) { VirtualFree(pg, 0, MEM_RELEASE); sbf(o, "{\"error\":\"%s\"}", why); return; }
    ww_selftest_poke((volatile unsigned long long *)(pg + 0x800), 0x5555);       /* out of range */
    if (mode == 1) Sleep(30);
    long f1 = g_ww_faults, s1 = g_ww_steps, c1 = g_ww_changes;
    ww_selftest_poke((volatile unsigned long long *)(pg + 0x100), 0x1122334455667788ULL);   /* in range */
    if (mode == 1) Sleep(30);
    long f2 = g_ww_faults, s2 = g_ww_steps, c2 = g_ww_changes;
    DWORD64 rip = (DWORD64)g_ww_last_change_rip, fn = (DWORD64)(void *)ww_selftest_poke;
    unsigned long long now = *(volatile unsigned long long *)(pg + 0x100);
    MEMORY_BASIC_INFORMATION mb;
    VirtualQuery(pg, &mb, sizeof mb);
    DWORD prot_armed = mb.Protect;
    ww_disarm();
    VirtualQuery(pg, &mb, sizeof mb);
    DWORD prot_off = mb.Protect;
    VirtualFree(pg, 0, MEM_RELEASE);
    int rip_ok = rip >= fn && rip < fn + 32;
    int pass = f1 == 1 && c1 == 0 && f2 == 2 && c2 == 1 && rip_ok && now == 0x1122334455667788ULL &&
               (mode == 1 || (s1 == 1 && s2 == 2)) && prot_off == PAGE_READWRITE;
    sbf(o, "{\"ok\":1,\"pass\":%d,\"mode\":\"%s\",\"faults\":[%ld,%ld],\"steps\":[%ld,%ld],\"changes\":[%ld,%ld],"
           "\"rip_off\":%lld,\"rip_ok\":%d,\"value_ok\":%d,\"prot_armed\":\"%lx\",\"prot_off\":\"%lx\"}",
        pass, mode ? "spin" : "tf", f1, f2, s1, s2, c1, c2, (long long)(rip - fn), rip_ok,
        now == 0x1122334455667788ULL, (unsigned long)prot_armed, (unsigned long)prot_off);
    logf_("[wwatch] selftest pass=%d mode=%s faults=%ld/%ld steps=%ld/%ld changes=%ld/%ld rip_off=%lld", pass,
          mode ? "spin" : "tf", f1, f2, s1, s2, c1, c2, (long long)(rip - fn));
}

static void ctl_watch(SB *o, int argc, char **argv) {
    const char *a = argc > 1 ? argv[1] : "status";
    if (!strcmp(a, "off")) {
        ww_disarm();
        ww_status(o);
    } else if (!strcmp(a, "status")) {
        ww_status(o);
    } else if (!strcmp(a, "selftest")) {
        ww_selftest(o, argc > 2 && !strcmp(argv[2], "spin"));
    } else if (!strcmp(a, "dump")) {
        sbf(o, "{\"ok\":1,\"rips\":[");
        int first = 1;
        for (int i = 0; i < WW_RIPS; i++) {
            if (!g_ww_rip[i].rip) continue;
            sbf(o, "%s{\"rip\":\"%llx\",\"n\":%ld,\"last\":\"%llx\"}", first ? "" : ",",
                (unsigned long long)g_ww_rip[i].rip, (long)g_ww_rip[i].n, (unsigned long long)g_ww_rip[i].last);
            first = 0;
        }
        sbf(o, "]}");
    } else if (argc > 2 && (a[0] >= '0' && a[0] <= '9')) {
        unsigned long long addr = strtoull(a, NULL, 16);
        unsigned long long len = strtoull(argv[2], NULL, 0);
        int mode = argc > 3 && !strcmp(argv[3], "spin");
        const char *why = ww_arm(ctl_addr(addr), (SIZE_T)len, mode);
        if (why) sbf(o, "{\"error\":\"%s\"}", why);
        else ww_status(o);
    } else {
        sbf(o, "{\"error\":\"usage: watch ADDR LEN [tf|spin] | watch status|dump|off|selftest [spin]\"}");
    }
}
#endif
