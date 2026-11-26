"""RECRUIT1 offline proof: the recruit-wish hooks (d5lib/wishrecruit.py, section .d5wr) run as code on the pinned exe.

The patched exe is built by the module itself (wishrecruit.build_patch on the pinned Steam exe, exemap's shipped
map), then the game's own code is executed on Unicorn x86-64:

1. the Strategy Assembly bill predicate 0x14044A730, entered the way its two list builders call it
   (RSP = 8 mod 16, rcx = assembly object, rdx = the WishDataBase row, r8 = the selected unit), for every case the
   hook decides: room / roster full (army + reserve = 128) / class already in the army / duplicates allowed / the
   row's own req_flag1 unset (the game's code must still hide it) / an unlisted bill (patched == pinned for a sweep
   of ids, the control).
2. the bill effect site 0x140221793, entered with the effect function's live registers (r15 = the passed row,
   rdi = image base, rsi = 0): a listed bill calls roster_create_unit 0x1402EA3E0 (Steam build; the module names it
   by its known-build address 0x1402EA890, exemap translates it) once with (class, 0, level) and
   then continues where the game's own 12 bytes go (0x14022179F for ids >= 1000); an unlisted bill (ids below and
   above 1000) never calls it and ends exactly where, and with exactly the registers, the pinned exe ends.
   roster_create_unit itself is a stand-in that records its arguments (its real body builds a unit from char.dat
   and is the game's code, already called the same way by d5lib.questpatch and by Overlord).
--abi adds: RSP mod 16 at the roster_create_unit call (must be 8 at its entry), every register except rax/rcx
restored at the continuation, and RSP + every non-volatile register restored when the predicate returns.

    D5Modkit/.venv-macos/bin/python tools/proof_wishrecruit.py [--exe <pinned>] [--abi] [--out r.json]
Exit 0 = every check passed.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))

try:
    import unicorn_darwin_shim                                    # noqa: F401,E402  (Darwin/ARM64 CTR_EL0)
except ImportError:                                               # pragma: no cover
    pass
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError       # noqa: E402
from unicorn import x86_const as X                                            # noqa: E402

from d5lib import exemap, wishrecruit as W                                   # noqa: E402

PINNED_REL = Path("D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
# Steam-build addresses (the pinned exe the proof runs); the module's known-build names translate to these
STEAM = {"army": 0x145574A9C, "reserve": 0x145574A9E, "roster": 0x145207DB8, "flags": 0x144FCCB0E,
         "create": 0x1402EA3E0}
STACK, STACK_SIZE = 0x10000000, 0x200000
OBJ, ROW, UNIT, STATS = 0x200000000, 0x200100000, 0x200200000, 0x200300000
SENTINEL = 0x7FFF0000
NONVOL = ["rbx", "rbp", "rsi", "rdi", "r12", "r13", "r14", "r15"]
ALL = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
REG = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in ALL + ["rip"]}

CASES = {"20300": {"character": 20300, "level": 10},
         "20000": {"character": 20000, "level": 50, "duplicates": True},
         "2615001": {"character": 2615, "level": 5000},
         # RECRUIT2: a pack, one bill -> three characters (the last may be owned already)
         "2700": [{"character": 3001, "level": 20}, {"character": 3002, "level": 30},
                  {"character": 3003, "level": 40, "duplicates": True}]}
PACK = (2700, [(3001, 20), (3002, 30), (3003, 40)])


def find_pinned():
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / PINNED_REL).is_file():
            return p / PINNED_REL
    for p in (Path("/Volumes/Data/Projects/D5"),):
        if (p / PINNED_REL).is_file():
            return p / PINNED_REL
    return None


def sections(exe):
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    n = struct.unpack_from("<H", exe, pe + 6)[0]
    opt = pe + 0x18
    base = struct.unpack_from("<Q", exe, opt + 0x18)[0]
    size = struct.unpack_from("<I", exe, opt + 0x38)[0]
    so = opt + struct.unpack_from("<H", exe, pe + 0x14)[0]
    return base, size, [struct.unpack_from("<IIII", exe, so + 40 * i + 8) for i in range(n)]


class Machine:
    def __init__(self, exe):
        base, size, secs = sections(exe)
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(base, (size + 0xFFF) & ~0xFFF)
        for vs, va, rs, ro in secs:
            if rs:
                mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
        mu.mem_map(STACK, STACK_SIZE)
        mu.mem_map(SENTINEL & ~0xFFF, 0x1000)
        for a in (OBJ, ROW, UNIT, STATS):
            mu.mem_map(a, 0x100000)
        self.base = base
        self.calls = []

    def w16(self, va, v):
        self.mu.mem_write(va, struct.pack("<h", v))

    def roster(self, army=(), reserve=0):
        """army: class ids of army slots 0..; reserve: count only (its slots are left empty)"""
        self.w16(STEAM["army"], len(army))
        self.w16(STEAM["reserve"], reserve)
        for i, c in enumerate(army):
            self.mu.mem_write(STEAM["roster"] + i * W.UNIT_SIZE + 0x2E04, struct.pack("<I", c))

    def row(self, bill, req=0):
        r = bytearray(0x80)
        struct.pack_into("<I", r, 0, bill)
        struct.pack_into("<I", r, 0x40, req)
        self.mu.mem_write(ROW, bytes(r))

    def regs(self):
        return {n: self.mu.reg_read(REG[n]) for n in ALL}


def run_predicate(exe, bill, army=(), reserve=0, req=0, flags=(), abi=False):
    m = Machine(exe)
    m.roster(army, reserve)
    m.row(bill, req)
    for f in flags:
        a = STEAM["flags"] + (f >> 3)
        m.mu.mem_write(a, bytes([m.mu.mem_read(a, 1)[0] | (1 << (f & 7))]))
    m.mu.mem_write(UNIT + 0x2E04, struct.pack("<I", 1010))
    rsp = STACK + STACK_SIZE // 2 - 8                              # entered by `call`: 8 mod 16
    m.mu.mem_write(rsp, struct.pack("<Q", SENTINEL))
    seed = {n: 0x1111111100000000 + i for i, n in enumerate(NONVOL)}
    for n, v in seed.items():
        m.mu.reg_write(REG[n], v)
    m.mu.reg_write(REG["rsp"], rsp)
    m.mu.reg_write(REG["rcx"], OBJ)
    m.mu.reg_write(REG["rdx"], ROW)
    m.mu.reg_write(REG["r8"], UNIT)
    err = None
    try:
        m.mu.emu_start(W.VIS_SITE, SENTINEL, count=200000)
    except UcError as e:
        err = str(e)
    out = {"bill": bill, "visible": m.mu.reg_read(REG["rax"]) & 0xFF, "ended": hex(m.mu.reg_read(REG["rip"])),
           "error": err}
    if abi:
        r = m.regs()
        out["abi"] = {"rsp_restored": r["rsp"] == rsp + 8,
                      "nonvolatile_restored": all(r[n] == seed[n] for n in NONVOL)}
    return out


def run_effect(exe, bill, misalign=False, abi=False):
    m = Machine(exe)
    m.roster((), 0)
    m.row(bill)
    stops = {0x1402217AF, 0x14022179F}

    def code(mu, addr, size, _):
        if addr == STEAM["create"]:
            rsp = mu.reg_read(REG["rsp"])
            m.calls.append({"cls": mu.reg_read(REG["rcx"]) & 0xFFFFFFFF, "arg2": mu.reg_read(REG["rdx"]),
                            "level": mu.reg_read(REG["r8"]) & 0xFFFFFFFF, "rsp_mod16": rsp % 16})
            ret = struct.unpack("<Q", mu.mem_read(rsp, 8))[0]
            for n in ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11"):   # a real callee may clobber volatiles
                mu.reg_write(REG[n], 0xDEAD0000 + len(n))
            mu.reg_write(REG["rax"], STEAM["roster"])
            mu.reg_write(REG["rsp"], rsp + 8)
            mu.reg_write(REG["rip"], ret)
        elif addr in stops:
            mu.emu_stop()
    m.mu.hook_add(UC_HOOK_CODE, code)
    rsp = STACK + STACK_SIZE // 2 - (8 if misalign else 0)
    seed = {n: 0x2222222200000000 + i for i, n in enumerate(ALL)}
    seed.update(rsp=rsp, r15=ROW, rdi=m.base, rsi=0, rbx=STATS)
    for n, v in seed.items():
        m.mu.reg_write(REG[n], v)
    err = None
    try:
        m.mu.emu_start(W.POST_SITE, 0, count=20000)
    except UcError as e:
        err = str(e)
    r = m.regs()
    out = {"bill": bill, "ended": hex(m.mu.reg_read(REG["rip"])), "eax": r["rax"] & 0xFFFFFFFF,
           "ecx": r["rcx"] & 0xFFFFFFFF, "calls": m.calls, "error": err, "regs": r}
    if abi:
        out["abi"] = {"kept_except_rax_rcx": all(r[n] == seed[n] for n in ALL if n not in ("rax", "rcx")),
                      "create_entry_rsp_mod16": [c["rsp_mod16"] for c in m.calls]}
    return out


def prove(pinned, abi=False, cases=None):
    cases = CASES if cases is None else cases
    prev = exemap.ACTIVE
    exemap.use(exemap.translator_for(pinned))
    try:
        entries = W.normalise(cases)
        patched = W.build_patch(pinned, entries)
    finally:
        exemap.use(prev)
    checks = []

    def check(name, ok, got):
        checks.append({"check": name, "ok": bool(ok), "got": got})

    # 1. the predicate
    room = run_predicate(patched, 20300, army=[1010] * 10, abi=abi)
    check("listed bill, room, not owned -> game predicate -> visible", room["visible"] == 1, room)
    full = run_predicate(patched, 20300, army=[1010] * 100, reserve=28, abi=abi)
    check("roster full (army 100 + reserve 28) -> hidden", full["visible"] == 0, full)
    nearly = run_predicate(patched, 20300, army=[1010] * 100, reserve=27, abi=abi)
    check("army 100 + reserve 27 (one slot) -> visible", nearly["visible"] == 1, nearly)
    owned = run_predicate(patched, 20300, army=[1010, 20300], abi=abi)
    check("class already in the army -> hidden", owned["visible"] == 0, owned)
    owned_ctl = run_predicate(pinned, 20300, army=[1010, 20300])
    check("control: the pinned exe shows that same bill (the hook is what hides it)", owned_ctl["visible"] == 1,
          owned_ctl)
    dup = run_predicate(patched, 20000, army=[20000], abi=abi)
    check("duplicates allowed, class owned -> visible", dup["visible"] == 1, dup)
    lock = run_predicate(patched, 20300, req=1699, abi=abi)
    check("row req_flag1 1699 unset -> the game's own code hides it", lock["visible"] == 0, lock)
    unlock = run_predicate(patched, 20300, req=1699, flags=[1699], abi=abi)
    check("row req_flag1 1699 set -> visible", unlock["visible"] == 1, unlock)
    sweep = []
    listed = {e[0] for e in entries}
    for bill in [b for b in list(range(0, 460)) + list(range(995, 1065)) + [1999, 2000, 2614, 20010, 20500]
                 if b not in listed]:
        a = run_predicate(pinned, bill, army=[1010, 20300])
        b = run_predicate(patched, bill, army=[1010, 20300])
        if (a["visible"], a["ended"]) != (b["visible"], b["ended"]):
            sweep.append({"bill": bill, "pinned": a, "patched": b})
    check("unlisted bills (0..459, 995..1064, 1999, 2000, 2614, 20010, 20500): patched == pinned", not sweep,
          sweep[:5])
    # 1b. a pack (RECRUIT2): room for all members, the 128 limit counts every member, owned rule per member
    pk = PACK[0]
    p_room = run_predicate(patched, pk, army=[1010] * 10, abi=abi)
    check("pack: room for every member -> visible", p_room["visible"] == 1, p_room)
    p_fit = run_predicate(patched, pk, army=[1010] * 100, reserve=25, abi=abi)
    check("pack of 3: army 100 + reserve 25 + 3 = 128 -> visible", p_fit["visible"] == 1, p_fit)
    p_over = run_predicate(patched, pk, army=[1010] * 100, reserve=26, abi=abi)
    check("pack of 3: army 100 + reserve 26 + 3 = 129 -> hidden", p_over["visible"] == 0, p_over)
    p_own = run_predicate(patched, pk, army=[1010, 3002], abi=abi)
    check("pack: one member (3002, no duplicates) already owned -> hidden", p_own["visible"] == 0, p_own)
    p_dup = run_predicate(patched, pk, army=[1010, 3003], abi=abi)
    check("pack: only the duplicates-allowed member (3003) owned -> visible", p_dup["visible"] == 1, p_dup)
    p_ctl = run_predicate(pinned, pk, army=[1010] * 100, reserve=26)
    check("control: the pinned exe shows that pack bill even over the limit", p_ctl["visible"] == 1, p_ctl)
    p_lock = run_predicate(patched, pk, req=1699, abi=abi)
    check("pack: row req_flag1 unset -> the game's own code hides it", p_lock["visible"] == 0, p_lock)
    if abi:
        bad = [r for r in (p_room, p_fit, p_over, p_own, p_dup, p_lock) if not all(r["abi"].values())]
        check("--abi pack predicate: RSP and non-volatile registers restored at return", not bad, bad[:3])
    if abi:
        bad = [r for r in (room, full, nearly, owned, dup, lock, unlock) if not all(r["abi"].values())]
        check("--abi predicate: RSP and rbx/rbp/rsi/rdi/r12-r15 restored at return", not bad, bad[:3])

    # 2. the effect site
    eff = run_effect(patched, 20300, abi=abi)
    check("listed bill 20300 -> roster_create_unit(20300, 0, 10) once, continues at 0x14022179F with ecx = 20300",
          eff["calls"] and [(c["cls"], c["arg2"], c["level"]) for c in eff["calls"]] == [(20300, 0, 10)]
          and eff["ended"] == hex(0x14022179F) and eff["ecx"] == 20300 and not eff["error"],
          {k: v for k, v in eff.items() if k != "regs"})
    # a second effect entered misaligned: the built-in 2615001, else the last converted bill
    bb, bc, bl, _ = next(e for e in entries if e[0] == 2615001) if cases is CASES else entries[-1]
    big = run_effect(patched, bb, misalign=True, abi=abi)
    check(f"listed bill {bb} (entered at RSP 8 mod 16) -> roster_create_unit({bc}, 0, {bl})",
          [(c["cls"], c["arg2"], c["level"]) for c in big["calls"]] == [(bc, 0, bl)] and not big["error"],
          {k: v for k, v in big.items() if k != "regs"})
    for bill in [b for b in (0x3F5, 116, 50, 1003, 1500, 2000, 20010) if b not in listed]:
        a = run_effect(pinned, bill)
        b = run_effect(patched, bill)
        same = (a["ended"], a["regs"]) == (b["ended"], b["regs"]) and not b["calls"] and not b["error"]
        check(f"unlisted bill {bill}: no create call; ends where the pinned exe ends with the same registers",
              same, {"pinned": a["ended"], "patched": b["ended"], "calls": b["calls"]})
    pe = run_effect(patched, PACK[0], abi=abi)
    check("pack bill 2700 -> roster_create_unit once per member, in order, each with its level, then continues "
          "at 0x14022179F",
          [(c["cls"], c["arg2"], c["level"]) for c in pe["calls"]] == [(c, 0, l) for c, l in PACK[1]]
          and pe["ended"] == hex(0x14022179F) and pe["ecx"] == PACK[0] and not pe["error"],
          {k: v for k, v in pe.items() if k != "regs"})
    pm = run_effect(patched, PACK[0], misalign=True, abi=abi)
    check("pack bill entered at RSP 8 mod 16 -> all three creates",
          len(pm["calls"]) == 3 and not pm["error"], {k: v for k, v in pm.items() if k != "regs"})
    ctl = run_effect(pinned, 20300)
    check("control: the pinned exe never calls roster_create_unit for bill 20300", not ctl["calls"],
          {"calls": ctl["calls"], "ended": ctl["ended"]})
    if cases is not CASES:
        # converted data: every entry as the game would meet it
        for bill, cls, lvl, opt in [e for e in entries if len(W.packs(entries)[e[0]]) == 1]:
            e = run_effect(patched, bill, abi=abi)
            ok = [(c["cls"], c["arg2"], c["level"]) for c in e["calls"]] == [(cls, 0, lvl)] and not e["error"] \
                and e["ended"] == hex(0x14022179F)
            v = run_predicate(patched, bill, army=[1010] * 10, abi=abi)
            o = run_predicate(patched, bill, army=[1010, cls], abi=abi)
            want_owned = 1 if opt & W.OPT_DUPLICATES else 0
            check(f"converted bill {bill}: effect -> roster_create_unit({cls}, 0, {lvl}); visible with room; "
                  f"{'visible' if want_owned else 'hidden'} once owned",
                  ok and v["visible"] == 1 and o["visible"] == want_owned,
                  {"effect": [(c["cls"], c["arg2"], c["level"]) for c in e["calls"]], "room": v["visible"],
                   "owned": o["visible"]})
    if abi:
        check("--abi effect: roster_create_unit entered at RSP 8 mod 16 (both alignments)",
              eff["abi"]["create_entry_rsp_mod16"] == [8] and big["abi"]["create_entry_rsp_mod16"] == [8]
              and pe["abi"]["create_entry_rsp_mod16"] == [8] * 3 and pm["abi"]["create_entry_rsp_mod16"] == [8] * 3,
              [eff["abi"], big["abi"], pe["abi"], pm["abi"]])
        check("--abi effect: every register but rax/rcx kept across the hook (callee clobbers volatiles)",
              eff["abi"]["kept_except_rax_rcx"] and big["abi"]["kept_except_rax_rcx"]
              and pe["abi"]["kept_except_rax_rcx"] and pm["abi"]["kept_except_rax_rcx"],
              [eff["abi"], big["abi"], pe["abi"], pm["abi"]])
    if abi:
        x = xmm_liveness(pinned, W.POST_SITE)
        check(f"--abi effect: no xmm value live across {W.POST_SITE:#x} (the effect function "
              f"{x['function']} reads every xmm register only right after writing it in the same block, and touches "
              f"none at or after the site), so the hook need not save xmm0-5",
              x["ok"], x)
    return {"exe_bytes": len(pinned), "patched_bytes": len(patched), "abi": abi,
            "entries": [list(e) for e in entries], "checks": checks,
            "pass": all(c["ok"] for c in checks)}


def xmm_liveness(exe, site):
    """static (RECRUITCHK1): is any xmm/ymm value live across `site` in its function of the pinned exe?

    The post hook calls roster_create_unit, which may clobber xmm0-5 (volatile), and saves none of them.  That is
    safe when every xmm read in the function is fed by a write earlier in the same straight-line run (no branch
    target or call in between) and nothing at or after the site touches an xmm register.  Linear sweep of the
    function (.pdata bounds, exemap.Exe); stops at its jump tables (the first undecodable bytes)."""
    import capstone
    from d5lib.exemap import Exe
    x = Exe(exe)
    rva = site - x.base
    # .pdata splits a big function into fragments whose unwind info is chained (UNW_FLAG_CHAININFO) to the one
    # before: merge the contiguous chained fragments around the site into the whole function
    pdata = next(s for s in x.sections if s[0] == ".pdata")
    blob = x.data[pdata[3]:pdata[3] + min(pdata[2], pdata[4])]
    frags = sorted(struct.unpack_from("<III", blob, k) for k in range(0, len(blob) - 11, 12))
    frags = [f for f in frags if f[0] and f[1] > f[0]]
    chained = lambda f: bool((x.read(f[2], 1) or b"\0")[0] >> 3 & 4)
    i = next((k for k, f in enumerate(frags) if f[0] <= rva < f[1]), None)
    if i is None:
        return {"ok": False, "function": None, "why": "site not inside a .pdata function"}
    lo = hi = i
    while lo > 0 and chained(frags[lo]) and frags[lo - 1][1] == frags[lo][0]:
        lo -= 1
    while hi + 1 < len(frags) and chained(frags[hi + 1]) and frags[hi + 1][0] == frags[hi][1]:
        hi += 1
    fn = (frags[lo][0], frags[hi][1])
    start, end = x.base + fn[0], x.base + fn[1]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    ins = list(md.disasm(x.read(fn[0], fn[1] - fn[0]), start))
    targets = set()
    for i in ins:
        if (i.group(capstone.CS_GRP_JUMP) and i.operands and i.operands[-1].type == capstone.x86.X86_OP_IMM):
            targets.add(i.operands[-1].imm)
    fed, uses, bad = set(), [], []
    for i in ins:
        if i.address in targets:
            fed = set()                                   # a block boundary: nothing carried in counts as fed
        rd, wr = i.regs_access()
        rd = {i.reg_name(r) for r in rd if i.reg_name(r)[1:3] == "mm"}
        wr = {i.reg_name(r) for r in wr if i.reg_name(r)[1:3] == "mm"}
        if rd or wr:
            uses.append(f"{i.address:#x} {i.mnemonic} {i.op_str}")
            if i.address >= site:
                bad.append(f"at/after the site: {i.address:#x} {i.mnemonic} {i.op_str}")
        bad += [f"{i.address:#x} reads {r} not written earlier in its block" for r in sorted(rd - fed)]
        fed |= wr
        if i.group(capstone.CS_GRP_CALL) or i.group(capstone.CS_GRP_JUMP) or i.group(capstone.CS_GRP_RET):
            fed = set()
    covered = ins[-1].address + ins[-1].size if ins else start
    return {"ok": not bad and bool(ins) and start <= site < covered and any(i.mnemonic == "ret" for i in ins
                                                                            if i.address > site),
            "function": f"{start:#x}..{end:#x}", "fragments": hi - lo + 1,
            "decoded_to": hex(covered), "xmm_instructions": uses, "problems": bad}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--wishes", help="a recruit_wishes.json (converted mod data) to prove instead of the built-in cases")
    a = ap.parse_args(argv)
    path = Path(a.exe) if a.exe else find_pinned()
    if not path or not path.is_file():
        print("no pinned exe (EXE__disgaea5.exe.full) found; pass --exe", file=sys.stderr)
        return 2
    cases = json.loads(Path(a.wishes).read_text())["recruits"] if a.wishes else None
    receipt = prove(path.read_bytes(), a.abi, cases)
    receipt["exe"] = str(path)
    text = json.dumps(receipt, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    for c in receipt["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"])
    print("OVERALL", "PASS" if receipt["pass"] else "FAIL")
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
