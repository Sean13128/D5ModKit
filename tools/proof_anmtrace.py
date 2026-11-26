"""ANMTRACE1 offline proof: the `anmtrace` hooks (d5lib/native/d5anmtrace.inc.c) on real exe bytes.

1. signatures: the prologue bytes the runtime checks before it hooks a site (AT_HOOKS, parsed from the C source) and
   the PE timestamp, on each exe given (the pinned original; the installed, kit-patched one).  A mismatch means that
   hook would be skipped (and logged) on that exe.
2. site entry (Unicorn, the pinned exe's code): the C file is built for this machine (Zig) and asked for each stub's
   bytes (at_stub, the function the runtime calls), laid out as the runtime lays them out (near page + 0xC00 + i *
   0xC0), the site patched with the same jmp rel32, then each case runs twice from a real `call site` with
   RSP = 0 mod 16 before the call -- vanilla and hooked -- from the same state (distinct canaries in every GPR,
   XMM0-15, the flags and the caller's home / stack-argument slots) and must end the same:
   * pre hooks (setup 0x14E7E0, create 0x14DFD0, seek 0x2F28C0 tracing): stop at site+5, the first instruction
     after the patch: every GPR, RSP, RIP, flags, XMM0-15, the caller's frame and every write outside the stack
     below the entry RSP are equal; the handler got the entry registers, arg5-7 and the return address;
   * seek in guard mode: the original does not run; back at the caller with RAX = 0 and everything else as before;
   * post hooks (lookup 0x301240 miss and hit; bank 0x3FFCB0 with lookup also hooked, the EDX contract: acquire_lzs
     compares EDX after its call to the lookup): the whole function runs to its return; registers, flags, XMM,
     the heap and the caller's frame are equal, except the caller's 0x20-byte home area, which the original now
     spills into the stub's frame (Win64: the home area is the callee's, its content after the call is undefined);
     the handler got the entry arguments and the original's return value;
   * negative control: the lookup handler overwrites the saved EDX -> the bank request must come out different.
   --abi: the stand-in handler behaves like a hostile C function -- it clobbers RCX RDX R8-R11, XMM0-5 and the
   flags and writes all four home qwords -- and the handler must be entered with RSP = 8 mod 16.
Cryswar's Overlord d5_anm_trace.c (The Unlicense) is the source of the sites and the prologue bytes.

    D5Modkit/.venv-macos/bin/python tools/proof_anmtrace.py [--exe <pinned>] [--exe <installed>] [--abi] [--out r.json]
"""
import argparse
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))

import unicorn_darwin_shim                                        # noqa: E402  (Darwin/ARM64 CTR_EL0)

unicorn_darwin_shim.install()

from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UcError   # noqa: E402
from unicorn import x86_const as X                                                         # noqa: E402
from test_recruit_runtime import pinned_exe, sections                                      # noqa: E402

SRC = KIT / "d5lib" / "native" / "d5anmtrace.inc.c"
TIMESTAMP = 0x5C4E7571
BASE = 0x140000000
NEAR, CALLER, HANDLER = BASE - 0x10000, BASE - 0x20000, 0x500000000
SKIP_REF = CALLER + 0x100                    # xor eax, eax; ret
STACK, HEAP = 0x10000000, 0x200000000
RSP0 = STACK + 0x100000                      # caller RSP before its call: 0 mod 16
BANKS = 0x1469B05F8                          # anm_find_loaded_slot's table: {records, count} every 0x150
GPR = ("RAX", "RBX", "RCX", "RDX", "RSI", "RDI", "RBP", "RSP", "R8", "R9", "R10", "R11", "R12", "R13", "R14",
       "R15", "RIP")
FLAGS = 0xCD5                                # CF PF AF ZF SF DF OF

# ------------------------------------------------------------------------------------------- host build
HOST = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef int LONG; typedef unsigned int DWORD; typedef unsigned short WORD; typedef size_t SIZE_T;
typedef struct { char pad[0x3C]; int e_lfanew; } IMAGE_DOS_HEADER;
typedef struct { DWORD Signature; struct { WORD m; WORD n; DWORD TimeDateStamp; } FileHeader; } IMAGE_NT_HEADERS64;
#define PAGE_EXECUTE_READWRITE 0x40
static int n_protect;
static int VirtualProtect(void *p, SIZE_T n, DWORD a, DWORD *old) { (void)p; (void)n; (void)a; *old = 0x20; n_protect++; return 1; }
static void *GetCurrentProcess(void) { return 0; }
static int FlushInstructionCache(void *h, const void *p, SIZE_T n) { (void)h; (void)p; (void)n; return 1; }
static LONG InterlockedIncrement(volatile LONG *p) { return ++*p; }
static LONG InterlockedDecrement(volatile LONG *p) { return --*p; }
static LONG InterlockedExchange(volatile LONG *p, LONG v) { LONG o = *p; *p = v; return o; }
typedef struct { char *p; size_t n, cap; } SB;
static void sbf(SB *s, const char *fmt, ...) {
    va_list a; va_start(a, fmt); s->n += vsnprintf(s->p + s->n, s->cap - s->n, fmt, a); va_end(a);
}
static void sb_str(SB *s, const char *t) { sbf(s, "\"%s\"", t); }
#define IMAGE_SIZE 0x2000000
static unsigned char *g_base; static volatile LONG g_frame, g_inflight;
static void *G(unsigned long long va) { return g_base + (va - 0x140000000ULL); }
#define VA_ACTORS 0x1415a5be0ULL
#define ACTOR_SIZE 0x1260
#define ACTOR_COUNT 256
static int in_image(const void *p, SIZE_T n) {
    return (const unsigned char *)p >= g_base && (const unsigned char *)p + n <= g_base + IMAGE_SIZE;
}
static int readable(const void *p, SIZE_T n) { (void)n; return p != NULL; }
static unsigned char g_page[0x1000];
static unsigned char *near_page(void) { return g_page; }
static void logf_(const char *fmt, ...) {
    char b[1024]; va_list a; va_start(a, fmt); vsnprintf(b, sizeof b, fmt, a); va_end(a);
    printf("LOG %s\n", b);
}
/*BLOCK*/
static void hexout(const unsigned char *p, int n) { for (int i = 0; i < n; i++) printf("%02x", p[i]); printf("\n"); }
static unsigned long long X(const char *s) { return strtoull(s, NULL, 16); }

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "stub")) {          /* stub POST AT SITE STOLENHEX FN -> hex */
        unsigned char t[512], st[AT_STOLEN];
        for (int i = 0; i < AT_STOLEN; i++) { char h[3] = {argv[5][2 * i], argv[5][2 * i + 1], 0}; st[i] = (unsigned char)strtoul(h, 0, 16); }
        int n = at_stub(t, X(argv[3]), X(argv[4]), st, atoi(argv[2]), X(argv[6]));
        hexout(t, n);
        return 0;
    }
    /* a scenario: options, then commands separated by "," */
    g_base = calloc(1, IMAGE_SIZE);
    int pe = 0x100; memcpy(g_base + 0x3C, &pe, 4);
    unsigned ts = AT_TIMESTAMP; memcpy(g_base + pe + 8, &ts, 4);
    for (int i = 0; i < AT_N; i++) memcpy(g_base + AT_HOOKS[i].rva, AT_HOOKS[i].sig, AT_HOOKS[i].n);
    int i = 1;
    for (; i < argc && strcmp(argv[i], "--"); i++) {
        if (!strcmp(argv[i], "badts")) { ts = 1; memcpy(g_base + pe + 8, &ts, 4); }
        else if (!strncmp(argv[i], "flip=", 5)) g_base[strtoul(argv[i] + 5, 0, 16)] ^= 1;
    }
    /* a battle actor in slot 3: owner -> player -> record 643 (1 palette, 2 pages) / motion 1007 */
    unsigned char *act = (unsigned char *)G(VA_ACTORS) + 3 * ACTOR_SIZE;
    static unsigned char own[0x100], pl[0x100], rec[0xC0], mo[4];
    int v;
    v = 643; memcpy(act + 0x2A0, &v, 4); v = -1; memcpy(act + 0x1E4, &v, 4); memcpy(act + 0x1E8, &v, 4); memcpy(act + 0x1EC, &v, 4);
    act[0x2E2] = 1; act[0x2E6] = 1; act[0x2E8] = 0;
    unsigned char *p8 = own; memcpy(act + 0x1D0, &p8, 8);
    short s16 = 643; memcpy(own + 0x20, &s16, 2); s16 = 1007; memcpy(own + 0x22, &s16, 2); own[0x24] = 0;
    p8 = pl; memcpy(own + 0x60, &p8, 8);
    v = 49 << 16; memcpy(pl + 0x28, &v, 4); v = 0x10000; memcpy(pl + 0x30, &v, 4); v = -1; memcpy(pl + 0x40, &v, 4);
    pl[0x3C] = 0; pl[0x3A] = 0; s16 = 7; memcpy(pl + 0x3E, &s16, 2);
    p8 = rec; memcpy(pl + 0x60, &p8, 8); p8 = mo; memcpy(pl + 0x68, &p8, 8);
    s16 = 643; memcpy(rec + 8, &s16, 2); s16 = 1; memcpy(rec + 0x10, &s16, 2); s16 = 2; memcpy(rec + 0x12, &s16, 2);
    s16 = 1007; memcpy(mo, &s16, 2);
    /* slot 4: an actor without an owner */
    char out[4096];
    printf("BEGIN\n");
    for (i++; i < argc; i++) {
        char *av[8]; int ac = 0;
        for (; i < argc && strcmp(argv[i], ","); i++) if (ac < 8) av[ac++] = argv[i];
        SB o = {out, 0, sizeof out}; out[0] = 0;
        if (!strcmp(av[0], "anmtrace")) ctl_anmtrace(&o, ac, av);
        else if (!strcmp(av[0], "actorprobe")) ctl_actorprobe(&o, ac, av);
        else if (!strcmp(av[0], "tick")) { for (int k = 0; k < atoi(av[1]); k++) { g_frame++; at_tick(); } }
        else if (!strcmp(av[0], "dump")) { FILE *f = fopen(av[1], "wb"); fwrite(g_base + 0x100000, 1, 0x300000, f); fclose(f); }
        else if (!strcmp(av[0], "sites")) { for (int k = 0; k < AT_N; k++) { printf("SITE %s ", AT_HOOKS[k].name); hexout(g_base + AT_HOOKS[k].rva, 5); } }
        else if (!strcmp(av[0], "noplayer")) { memset(own + 0x60, 0, 8); }
        else if (!strcmp(av[0], "handlers")) {
            ATPOST b; memset(&b, 0, sizeof b);
            b.rax = 0xFFFFFFFFull; b.in.rcx = 643; b.in.ret = (unsigned long long)(g_base + 0x3FFCE1);
            printf("V lookup_miss %d\n", at_h_lookup(&b));
            b.rax = 2; printf("V lookup_hit %d\n", at_h_lookup(&b));
            memset(&b, 0, sizeof b);
            b.rax = 0xFFFFFFFFull; b.in.rdx = 643; b.in.r8 = 0x1200; b.in.r9 = 1; b.in.ret = (unsigned long long)(g_base + 0x14E853);
            printf("V bank %d\n", at_h_bank(&b));
            ATREGS r; memset(&r, 0, sizeof r);
            r.rcx = (unsigned long long)act; r.rdx = 643; r.r8 = 0; r.r9 = 1007; r.arg5 = 1; r.arg6 = 645; r.arg7 = 1;
            r.ret = (unsigned long long)(g_base + 0x14EBA0);
            printf("V setup %d\n", at_h_setup(&r));
            r.rdx = 0xABCD0283; r.r8 = 0x10000; r.r9 = 0x7703EF; r.arg5 = 1; r.ret = (unsigned long long)(g_base + 0x14E8D4);
            printf("V create %d\n", at_h_create(&r));
            static unsigned char sown[0x100], spl[0x100], smo[4];
            unsigned char *q = spl; memcpy(sown + 0x60, &q, 8);
            s16 = 643; memcpy(sown + 0x20, &s16, 2); s16 = 1007; memcpy(sown + 0x22, &s16, 2);
            memset(&r, 0, sizeof r); r.rcx = (unsigned long long)sown; r.rdx = 12; r.ret = (unsigned long long)(g_base + 0x2F4C9A);
            printf("V seek_null %d\n", at_h_seek(&r));
            q = smo; memcpy(spl + 0x68, &q, 8);
            printf("V seek_ok %d\n", at_h_seek(&r));
            memset(sown + 0x60, 0, 8);
            printf("V seek_noplayer %d\n", at_h_seek(&r));
        }
        if (o.n) printf("REPLY %s\n", out);
    }
    printf("INFLIGHT %d PROTECT %d\n", (int)g_inflight, n_protect);
    return 0;
}
"""


def build_host(outdir=None):
    """the C file built for this machine with the stand-ins above -> path of the binary (raises if Zig fails)"""
    outdir = Path(outdir or tempfile.mkdtemp(prefix="anmtrace_"))
    (outdir / "t.c").write_text(HOST.replace("/*BLOCK*/", SRC.read_text()))
    exe = outdir / "t"
    r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-O1", "-w", "-o", str(exe), str(outdir / "t.c")],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-3000:])
    return exe


def c_hooks(src):
    """AT_HOOKS as the runtime ships them: [(name, rva, post, signature)]"""
    block = re.search(r"AT_HOOKS\[\] = \{(.*?)\n\};", src, re.S).group(1)
    out = []
    for m in re.finditer(r'\{"(\w+)", (0x[0-9A-Fa-f]+)u, (\d), (\d+), \{([^}]*)\}', block):
        sig = bytes(int(x, 16) for x in m.group(5).replace("\n", " ").split(",") if x.strip())
        assert len(sig) == int(m.group(4)), m.group(1)
        out.append((m.group(1), int(m.group(2), 16), int(m.group(3)), sig))
    return out


def rva_bytes(data, rva, n):
    _, _, secs = sections(data)
    for name, va, vs, rs, ro in secs:
        if va <= rva < va + max(vs, rs):
            return data[ro + rva - va:ro + rva - va + n]
    return b""


def check_signatures(data, hooks):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    ts = struct.unpack_from("<I", data, pe + 8)[0]
    rows = [{"hook": n, "rva": f"0x{rva:X}", "n": len(sig), "match": rva_bytes(data, rva, len(sig)) == sig}
            for n, rva, _, sig in hooks]
    return {"timestamp": f"0x{ts:X}", "timestamp_ok": ts == TIMESTAMP, "signatures": rows,
            "ok": ts == TIMESTAMP and all(r["match"] for r in rows)}


def stub_bytes(host, post, at, site, stolen, fn):
    r = subprocess.run([str(host), "stub", str(post), f"{at:x}", f"{site:x}", stolen.hex(), f"{fn:x}"],
                       capture_output=True, text=True, check=True)
    return bytes.fromhex(r.stdout.strip())


# ------------------------------------------------------------------------------------------- emulation
def handler_code(verdict, abi):
    """the stand-in for the C handler: well-behaved (mov eax, verdict; ret) or, with --abi, hostile"""
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    lines = []
    if abi:
        for i, reg in enumerate(("rcx", "rdx", "r8", "r9", "r10", "r11")):
            lines.append(f"mov {reg}, {0xBAD0000000000000 + i:#x}")
        lines += ["mov [rsp+8], rcx", "mov [rsp+0x10], rdx", "mov [rsp+0x18], r8", "mov [rsp+0x20], r9"]
        lines += [f"pcmpeqd xmm{i}, xmm{i}" for i in range(6)]
        lines += ["xor eax, eax", "stc"]                         # ZF PF CF set, the rest cleared
    lines += [f"mov eax, {verdict}", "ret"]
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_64).asm("; ".join(lines))
    return bytes(enc)


class Machine:
    def __init__(self, exe):
        base, size, secs = sections(exe)
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
        for name, va, vs, rs, ro in secs:
            if rs:
                mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
        self.image_end = base + size
        mu.mem_map(NEAR, 0x1000)
        mu.mem_map(CALLER, 0x1000)
        mu.mem_map(HANDLER, 0x1000)
        mu.mem_map(STACK, 0x200000)
        mu.mem_map(HEAP, 0x100000)
        self.calls, self.writes = [], []
        mu.hook_add(UC_HOOK_CODE, self._handler, begin=HANDLER, end=HANDLER)
        mu.hook_add(UC_HOOK_MEM_WRITE, lambda m, acc, addr, size, val, _: self.writes.append((addr, size)))

    def _handler(self, mu, addr, size, _):
        rsp, rcx = mu.reg_read(X.UC_X86_REG_RSP), mu.reg_read(X.UC_X86_REG_RCX)
        blk = struct.unpack("<34Q", mu.mem_read(rcx, 34 * 8))
        self.calls.append({"rsp_mod16": rsp % 16, "block": blk})
        if self.corrupt_rdx and len(self.calls) == 1:            # negative control: lose the original's EDX
            mu.mem_write(rcx + 0x20, struct.pack("<Q", 0x4141414141414141))

    def hook(self, host, i, rva, post, verdict, abi):
        mu = self.mu
        site = BASE + rva
        at = NEAR + 0xC00 + i * 0xC0
        stub = stub_bytes(host, post, at, site, bytes(mu.mem_read(site, 5)), HANDLER)
        assert len(stub) <= 0xC0, len(stub)
        mu.mem_write(at, stub)
        mu.mem_write(site, b"\xE9" + struct.pack("<i", at - (site + 5)))
        mu.mem_write(HANDLER, handler_code(verdict, abi))
        return stub

    def setup(self, target, rsp0=RSP0):
        mu = self.mu
        self.corrupt_rdx = False
        mu.mem_write(CALLER, b"\xE8" + struct.pack("<i", target - (CALLER + 5)) + b"\xF4")
        mu.mem_write(SKIP_REF, b"\x31\xC0\xC3")
        for i, name in enumerate(GPR[:-1]):
            mu.reg_write(getattr(X, "UC_X86_REG_" + name), 0x1111000000000000 + 0x0101 * i)
        mu.reg_write(X.UC_X86_REG_RSP, rsp0)
        for i in range(16):
            mu.reg_write(getattr(X, f"UC_X86_REG_XMM{i}"), 0x22220000000000003333000000000000 + (i << 64) + i)
        mu.reg_write(X.UC_X86_REG_EFLAGS, 0x202 | 0x1 | 0x80 | 0x800)    # CF SF OF set
        mu.mem_write(rsp0, b"".join(struct.pack("<Q", 0x4444000000000000 + k) for k in range(32)))

    def regs(self, name):
        return self.mu.reg_read(getattr(X, "UC_X86_REG_" + name))

    def snapshot(self):
        mu = self.mu
        return {"gpr": {n: self.regs(n) for n in GPR}, "flags": self.regs("EFLAGS") & FLAGS,
                "xmm": [mu.reg_read(getattr(X, f"UC_X86_REG_XMM{i}")) for i in range(16)],
                "frame": bytes(mu.mem_read(RSP0 - 8, 0x108)), "heap": bytes(mu.mem_read(HEAP, 0x10000)),
                "writes": sorted({(a, s) for a, s in self.writes if not (STACK <= a < RSP0 - 8)})}

    def run(self, until):
        self.writes.clear()
        try:
            self.mu.emu_start(CALLER, until, count=500000)
            return "stopped"
        except UcError as exc:
            return f"fault ({exc}) at {self.regs('RIP'):#x}"


def plant_banks(mu, slot, ids):
    """one loaded bank in anm_find_loaded_slot's table: records (0xC0, u16 id at +8), sorted"""
    recs = HEAP + 0x20000
    for k, i in enumerate(sorted(ids)):
        mu.mem_write(recs + k * 0xC0 + 8, struct.pack("<H", i))
    mu.mem_write(BANKS + slot * 0x150, struct.pack("<Q", recs))
    mu.mem_write(BANKS + slot * 0x150 + 8, struct.pack("<i", len(ids)))


def diff(a, b, skip_home=False):
    """what differs between two snapshots (the caller's home area optionally ignored)"""
    out = [n for n in GPR if a["gpr"][n] != b["gpr"][n]]
    if a["flags"] != b["flags"]:
        out.append("flags")
    out += [f"xmm{i}" for i in range(16) if a["xmm"][i] != b["xmm"][i]]
    fa, fb = bytearray(a["frame"]), bytearray(b["frame"])
    if skip_home:                       # frame starts at RSP0-8 (the return address): home = +8 .. +0x28
        fa[8:0x28] = fb[8:0x28] = bytes(0x20)
    if fa != fb:
        out.append("caller frame")
    if a["heap"] != b["heap"]:
        out.append("heap")
    wa = [w for w in a["writes"] if not (skip_home and RSP0 <= w[0] < RSP0 + 0x20)]
    wb = [w for w in b["writes"] if not (skip_home and RSP0 <= w[0] < RSP0 + 0x20)]
    if wa != wb:
        out.append("writes outside the stack")
    return out


def entry_args_ok(blk, pre):
    """the handler saw the entry registers, stack arguments and the caller's return address"""
    o = 0 if pre else 13                                        # ATPOST.in starts at qword 13
    regs = dict(zip(("R11", "R10", "R9", "R8", "RDX", "RCX", "RAX"), blk[o:o + 7]))
    want = {n: 0x1111000000000000 + 0x0101 * GPR.index(n) for n in regs}
    stack = blk[o + 13:o + 16] == tuple(0x4444000000000000 + k for k in (4, 5, 6))   # [entry+0x28..] = RSP0+0x20..
    return regs == want and blk[o + 8] == CALLER + 5 and stack


def case_pre(exe, host, hooks, name, abi, verdict=0):
    i = [h[0] for h in hooks].index(name)
    _, rva, post, _ = hooks[i]
    v = Machine(exe)
    # guard: what the stub must amount to is "return 0 at once"; the reference is a function that does exactly
    # that (xor eax, eax; ret), called from the same state
    v.setup(SKIP_REF if verdict else BASE + rva)
    until = CALLER + 5 if verdict else BASE + rva + 5
    stop_v = v.run(until)
    van = v.snapshot()
    h = Machine(exe)
    stub = h.hook(host, i, rva, post, verdict, abi)
    h.setup(BASE + rva)
    stop_h = h.run(until)
    hk = h.snapshot()
    d = diff(van, hk)
    calls = h.calls
    r = {"hook": name, "mode": "guard" if verdict else "pass", "stub_bytes": len(stub), "vanilla": stop_v,
         "hooked": stop_h, "rip": f"{hk['gpr']['RIP']:#x}", "differs": d, "handler_calls": len(calls),
         "handler_args_ok": bool(calls) and entry_args_ok(calls[0]["block"], True)}
    r["pass"] = stop_v == stop_h == "stopped" and not d and len(calls) == 1 and r["handler_args_ok"]
    if abi:
        r["handler_rsp_mod16"] = [c["rsp_mod16"] for c in calls]
        r["pass"] &= r["handler_rsp_mod16"] == [8]
    return r


def case_post(exe, host, hooks, label, names, args, abi, plant=None, corrupt=False, probe=None):
    """call `names[0]` (args in RCX RDX R8 R9) to its return, vanilla vs with every hook in `names`"""
    idx = {h[0]: k for k, h in enumerate(hooks)}
    target = BASE + hooks[idx[names[0]]][1]

    def prep(m, rsp0=RSP0):
        m.setup(target, rsp0)
        for reg, val in zip(("RCX", "RDX", "R8", "R9"), args):
            m.mu.reg_write(getattr(X, "UC_X86_REG_" + reg), val)
        if plant:
            plant(m.mu)
    v = Machine(exe)
    prep(v)
    stop_v = v.run(CALLER + 5)
    van = v.snapshot()
    h = Machine(exe)
    for n in names:
        h.hook(host, idx[n], hooks[idx[n]][1], hooks[idx[n]][2], 0, abi)
    prep(h)
    h.corrupt_rdx = corrupt
    stop_h = h.run(CALLER + 5)
    hk = h.snapshot()
    d = diff(van, hk, skip_home=True)
    # a post stub runs the original 0x70 bytes deeper; status flags that depend on RSP (add rsp, imm at its
    # epilogue) differ for that reason alone -- also in vanilla called from another depth, so no caller can use them
    v2 = Machine(exe)
    prep(v2, RSP0 - 0x70)
    v2.run(CALLER + 5)
    depth = v2.regs("EFLAGS") & FLAGS != van["flags"]
    if "flags" in d and depth and (van["flags"] ^ hk["flags"]) & 0x400 == 0:      # DF (0x400) must still match
        d.remove("flags")
    r = {"case": label, "hooks": names, "vanilla": stop_v, "hooked": stop_h, "rax": f"{hk['gpr']['RAX']:#x}",
         "vanilla_rax": f"{van['gpr']['RAX']:#x}", "differs": d,
         "flags_depend_on_depth_in_vanilla": depth, "handler_calls": len(h.calls)}
    outer = h.calls[-1]["block"] if h.calls else None          # the outermost hook returns last
    if probe:
        r["probe_vanilla"], r["probe_hooked"] = probe(v.mu), probe(h.mu)
    r["handler_args_ok"] = bool(outer) and outer[6] == van["gpr"]["RAX"] and outer[13 + 8] == CALLER + 5
    r["pass"] = stop_v == stop_h == "stopped" and not d and len(h.calls) == len(names) and r["handler_args_ok"]
    if abi:
        r["handler_rsp_mod16"] = [c["rsp_mod16"] for c in h.calls]
        r["pass"] &= set(r["handler_rsp_mod16"]) == {8}
    r["blocks"] = [{"entry_rcx": c["block"][13 + 5], "entry_rdx": c["block"][13 + 4],
                    "returned_rax": c["block"][6], "ret": f"{c['block'][13 + 8]:#x}"} for c in h.calls]
    return r


def site_entry(exe, host, hooks, abi):
    cases = [case_pre(exe, host, hooks, n, abi) for n in ("setup", "create", "seek")]
    cases.append(case_pre(exe, host, hooks, "seek", abi, verdict=1))
    cases.append(case_post(exe, host, hooks, "lookup miss (no bank loaded)", ["lookup"], (643,), abi))
    cases.append(case_post(exe, host, hooks, "lookup hit (643 in bank slot 2)", ["lookup"], (643,), abi,
                           plant=lambda mu: plant_banks(mu, 2, [100, 643, 900])))
    mgr = HEAP + 0x1000

    def bank_mgr(mu):                           # loader entry 0 already asked for 643, its task gone (-1)
        mu.mem_write(mgr, struct.pack("<5i", 0, 643, 1, 0, -1))
    def refs(mu):                               # entry 0's reference count: 1 = acquire_lzs matched it by EDX
        return struct.unpack("<i", bytes(mu.mem_read(mgr, 4)))[0]
    bank = case_post(exe, host, hooks, "bank request, lookup hooked too (EDX across the call)", ["bank", "lookup"],
                     (mgr, 643, 0x55, 1), abi, plant=bank_mgr, probe=refs)
    bank["pass"] &= bank["probe_vanilla"] == bank["probe_hooked"] == 1
    cases.append(bank)
    neg = case_post(exe, host, hooks, "negative control: lookup handler loses EDX", ["bank", "lookup"],
                    (mgr, 643, 0x55, 1), abi, plant=bank_mgr, corrupt=True, probe=refs)
    neg["pass"] = bool(neg["differs"]) and neg["probe_hooked"] != 1     # the comparison must see it
    cases.append(neg)
    return cases


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", action="append", help="exe to check the signatures on (repeat); default: pinned")
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    hooks = c_hooks(SRC.read_text())
    receipt = {"signatures": {}}
    ok = True
    for p in args.exe or [pinned_exe()]:
        s = check_signatures(Path(p).read_bytes(), hooks)
        receipt["signatures"][p] = s
        ok &= s["ok"]
    exe = Path(pinned_exe()).read_bytes()
    with tempfile.TemporaryDirectory(prefix="anmtrace_") as d:
        host = build_host(d)
        receipt["site_entry"] = site_entry(exe, host, hooks, args.abi)
    ok &= all(c["pass"] for c in receipt["site_entry"])
    receipt["abi"] = args.abi
    receipt["ok"] = ok
    text = json.dumps(receipt, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    print(text if not args.out else f"{'PASS' if ok else 'FAIL'} -> {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
