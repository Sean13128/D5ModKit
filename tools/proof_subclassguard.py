"""SUBCLASS2 rework offline proof: the Assembly sub-class panel guard (d5lib/subclassguard.py, section .d5sv).

The Strategy Assembly's sub-class screen draw 0x14046F980 is run on Unicorn x86-64 from its entry, the way the screen
calls it (RSP = 8 mod 16, rcx = the screen object), on the pinned exe and on the pinned exe + .d5sv:

* sub-class 0: no lookup, nothing drawn (pinned == patched);
* a sub-class whose row exists (a vanilla id and an imported id): the panel frame and both texts are drawn with the
  same arguments, the class name taken from row + 0xF8 + language * 0x34 (pinned == patched, same registers at return);
* a sub-class whose row is missing: the pinned exe passes a pointer in the null page to ui_draw_text (the crash); the
  patched exe draws no panel, returns normally with every non-volatile register and xmm6 restored, and counts one skip.

Stand-ins (code hooks that return like the function): the list widget's vtable call, roundf 0x140115834,
char_find_by_id 0x140061F80 (a table of ids), the panel frame 0x14041F200, the text-colour helper 0x140411580 and
ui_draw_text 0x1403FACE0 (records its string argument [rsp+0x28 at entry]).  Each clobbers the volatile registers.
--abi adds: RSP = 8 mod 16 at every stand-in entry on both paths and a mutant (no r15 restore) that must be rejected.
--static: the hook has no stack use and no call; its exits go to 0x14046FA44 and 0x14046FC8C.

    D5Modkit/.venv-macos/bin/python tools/proof_subclassguard.py [--exe <pinned>] [--abi] [--static] [--out r.json]
"""
import argparse
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

try:
    sys.path.insert(0, str(KIT / "tests"))
    import unicorn_darwin_shim                                    # noqa: F401
    unicorn_darwin_shim.install()
except (ImportError, AttributeError):                             # pragma: no cover
    pass
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError       # noqa: E402
from unicorn import x86_const as X                                            # noqa: E402

from d5lib import subclassguard as G                                         # noqa: E402

PINNED_REL = Path("D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
DRAW = 0x14046F980
ROUNDF, LOOKUP, FRAME, COLOUR, TEXT = 0x140115834, 0x140061F80, 0x14041F200, 0x140411580, 0x1403FACE0
LANG_PTR, CHAR_TABLE = 0x140BD7B30, 0x140A03880
STACK, STACK_SIZE = 0x10000000, 0x100000
OBJ, UNIT, PANEL, LANG, TABLE, STUBS = (0x200000000, 0x200100000, 0x200200000, 0x200300000, 0x200400000,
                                        0x200500000)
SENTINEL = 0x7FFF0000
ROWS = {1015: 3, 1445: 700}            # ids with a char.dat row -> row index (vanilla Warrior r5, an imported rank)
NONVOL = ["rbx", "rbp", "rsi", "rdi", "r12", "r13", "r14", "r15"]
ALL = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
REG = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in ALL + ["rip"]}


def find_pinned():
    for p in list(Path(__file__).resolve().parents) + [Path("/Volumes/Data/Projects/D5")]:
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


def run(exe, sub, lang=0):
    base, size, secs = sections(exe)
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    mu.mem_map(base, (size + 0xFFF) & ~0xFFF)
    for vs, va, rs, ro in secs:
        if rs:
            mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
    mu.mem_map(STACK, STACK_SIZE)
    mu.mem_map(SENTINEL & ~0xFFF, 0x1000)
    for a in (OBJ, UNIT, PANEL, LANG, TABLE, STUBS):
        mu.mem_map(a, 0x100000)
    mu.mem_write(STUBS, b"\xC3" * 16)
    mu.mem_write(OBJ + 0x80, struct.pack("<Q", STUBS + 0x100))            # the list widget: vtable
    mu.mem_write(STUBS + 0x100 + 0xF8, struct.pack("<Q", STUBS))           # vtable[0xF8/8] -> ret
    mu.mem_write(OBJ + 0x8FB8, struct.pack("<Q", UNIT))
    mu.mem_write(OBJ + 0x2378, struct.pack("<Q", PANEL))
    mu.mem_write(UNIT + 0x35AC, struct.pack("<H", sub & 0xFFFF))
    mu.mem_write(LANG + 4, struct.pack("<i", lang))
    mu.mem_write(LANG_PTR, struct.pack("<Q", LANG))
    mu.mem_write(CHAR_TABLE, struct.pack("<Q", TABLE))
    calls = []

    def ret(value=0, leaf=False):
        rsp = mu.reg_read(REG["rsp"])
        r = struct.unpack("<Q", mu.mem_read(rsp, 8))[0]
        # 0x140411580 is a leaf the compiler relies on (the caller reads r9/r10 after it): it keeps them
        for n in (() if leaf else ("rcx", "rdx", "r8", "r9", "r10", "r11")):
            mu.reg_write(REG[n], 0xDEAD000000000000 + len(calls))
        mu.reg_write(REG["rax"], value)
        mu.reg_write(REG["rsp"], rsp + 8)
        mu.reg_write(REG["rip"], r)

    def code(_mu, addr, _size, _):
        name = {ROUNDF: "roundf", LOOKUP: "char_find_by_id", FRAME: "frame", COLOUR: "colour", TEXT: "text",
                STUBS: "vtable"}.get(addr)
        if not name:
            return
        rsp = mu.reg_read(REG["rsp"])
        c = {"fn": name, "rsp_mod16": rsp % 16}
        if name == "char_find_by_id":
            c["id"] = mu.reg_read(REG["rdx"]) & 0xFFFF
            calls.append(c)
            ret(ROWS.get(c["id"], 0xFFFFFFFF))
            return
        if name == "text":
            c["string"] = struct.unpack("<Q", mu.mem_read(rsp + 0x28, 8))[0]
        calls.append(c)
        if name == "colour":
            ret(0, leaf=True)
            return
        if name == "roundf":
            rsp_ = mu.reg_read(REG["rsp"])
            r = struct.unpack("<Q", mu.mem_read(rsp_, 8))[0]
            mu.reg_write(REG["rsp"], rsp_ + 8)
            mu.reg_write(REG["rip"], r)                                  # xmm0 unchanged
            return
        ret(0)
    mu.hook_add(UC_HOOK_CODE, code)
    rsp = STACK + STACK_SIZE // 2 - 8
    mu.mem_write(rsp, struct.pack("<Q", SENTINEL))
    seed = {n: 0x4444444400000000 + i for i, n in enumerate(ALL)}
    seed.update(rsp=rsp, rcx=OBJ)
    for n, v in seed.items():
        mu.reg_write(REG[n], v)
    mu.reg_write(X.UC_X86_REG_XMM6, 0x66666666_77777777_88888888_99999999)
    err = None
    try:
        mu.emu_start(DRAW, SENTINEL, count=200000)
    except UcError as e:
        err = str(e)
    regs = {n: mu.reg_read(REG[n]) for n in ALL}
    end = mu.reg_read(REG["rip"])
    return {"sub": sub, "ended": end, "error": err, "calls": calls, "regs": regs,
            "kept": all(regs[n] == seed[n] for n in NONVOL) and regs["rsp"] == rsp + 8
            and mu.reg_read(X.UC_X86_REG_XMM6) == 0x66666666_77777777_88888888_99999999}


def build(pinned, mutate=None):
    src = G.hook_source
    if mutate:
        G.hook_source = lambda: mutate(src())
    try:
        return G.patch(pinned, log=lambda *_: None)
    finally:
        G.hook_source = src


def prove(pinned, abi=False):
    patched = build(pinned)
    checks = []

    def check(name, ok, got=None):
        checks.append({"check": name, "ok": bool(ok), "got": got})

    strip = lambda r: {k: v for k, v in r.items() if k != "regs"}
    z0, z1 = run(pinned, 0), run(patched, 0)
    check("sub-class 0: no lookup, nothing drawn, same return (pinned == patched)",
          z1["calls"] == z0["calls"] and [c["fn"] for c in z1["calls"]] == ["vtable"] and z1["regs"] == z0["regs"]
          and z1["ended"] == SENTINEL, strip(z1))
    for sid, what in ((1015, "vanilla Warrior rank 5"), (1445, "an imported rank")):
        for lang in (0, 4):
            a, b = run(pinned, sid, lang), run(patched, sid, lang)
            want = TABLE + ROWS[sid] * 0x38C + 0xF8 + lang * 0x34
            texts = [c["string"] for c in b["calls"] if c["fn"] == "text"]
            check(f"row present ({what} {sid}, language {lang}): frame + two texts, name at row+0xF8+lang*0x34, "
                  "same calls and registers as the pinned exe",
                  b["calls"] == a["calls"] and b["regs"] == a["regs"] and texts and texts[-1] == want
                  and b["ended"] == SENTINEL and b["kept"] and not b["error"], {"texts": [hex(t) for t in texts]})
    m0, m1 = run(pinned, 1525), run(patched, 1525)
    t0 = [c["string"] for c in m0["calls"] if c["fn"] == "text"]
    check("control: row missing on the pinned exe -> ui_draw_text gets a string pointer in the null page (the crash)",
          t0 and t0[-1] < 0x1000, [hex(t) for t in t0])
    va = G.counter_va(patched)
    check("row missing on the patched exe: lookup made, no frame and no text drawn, normal return with rbx/rbp/rsi/"
          "rdi/r12-r15, xmm6 and RSP restored",
          [c["fn"] for c in m1["calls"]] == ["vtable", "roundf", "roundf", "char_find_by_id"]
          and m1["ended"] == SENTINEL and m1["kept"] and not m1["error"], strip(m1))
    check("the skip counter lives in the section (counter_va found)", va is not None, hex(va) if va else None)
    # SUBCLASS3: INSTALL1120A wrote 65000 -- as the signed short the draw compares, that is -536, so the game's own
    # `cmp word [unit+0x35AC], 0 / jle` (0x14046F9A0) skips the panel before any lookup: the guard is not reached
    n0, n1 = run(pinned, 65000), run(patched, 65000)
    check("65000 (the live test's id) is negative as a signed short: no lookup on either exe, nothing drawn, the guard "
          "not reached (why its counter stayed 0 live)",
          [c["fn"] for c in n0["calls"]] == ["vtable"] and n1["calls"] == n0["calls"] and n1["regs"] == n0["regs"],
          [c["fn"] for c in n1["calls"]])
    p0, p1 = run(pinned, 30000), run(patched, 30000)
    t0 = [c["string"] for c in p0["calls"] if c["fn"] == "text"]
    check("30000 (positive, no row): pinned passes a null-page string; patched skips the panel -- the id a live test "
          "must use to hit the guard", t0 and t0[-1] < 0x1000 and p1["kept"]
          and not any(c["fn"] == "text" for c in p1["calls"]), [hex(t) for t in t0])
    for lang in (1, 2, 3):
        r = run(patched, 1525, lang)
        check(f"row missing, language {lang}: panel skipped, normal return", r["kept"] and r["ended"] == SENTINEL
              and not any(c["fn"] == "text" for c in r["calls"]), None)
    if abi:
        allc = [c for r in (m1, run(patched, 1445), run(patched, 1445, 4)) for c in r["calls"]]
        check("--abi: every callee entered at RSP 8 mod 16 on the skip and the draw paths",
              all(c["rsp_mod16"] == 8 for c in allc), sorted({c["rsp_mod16"] for c in allc}))
        mut = build(pinned, lambda s: s.replace("mov r15, qword ptr [rsp + 0x60]\n", ""))
        mr = run(mut, 1525)
        check("--abi mutant (no r15 restore on the skip): rejected -- r15 is not the caller's at return",
              not mr["kept"], strip(mr))
    return {"exe_bytes": len(pinned), "patched_bytes": len(patched), "counter": hex(va) if va else None,
            "abi": abi, "checks": checks, "pass": all(c["ok"] for c in checks)}


def prove_static(pinned):
    import capstone
    patched = build(pinned)
    site = bytes(G._get(patched, G.SITE, 11))
    hook = G.SITE + 5 + struct.unpack_from("<i", site, 1)[0]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    code = G._get(patched, hook, 0x40)
    findings, exits = [], []
    for ins in md.disasm(code, hook):
        if ins.mnemonic in ("push", "pop", "call", "ret") or "rsp" in [ins.reg_name(r) for r in ins.regs_access()[1]]:
            findings.append(f"{ins.address:#x} {ins.mnemonic} {ins.op_str}")
        if ins.mnemonic.startswith("j") and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
            t = ins.operands[0].imm
            if not hook <= t < hook + 0x40:
                exits.append(hex(t))
        if ins.mnemonic == "jmp" and exits and exits[-1] == hex(G.EPILOGUE):
            break
    ok = not findings and exits == [hex(G.FOUND), hex(G.EPILOGUE)] and site[5:] == b"\x90" * 6
    checks = [{"check": "static: no push/pop/call/ret/rsp write; exits to 0x14046FA44 (row found) and 0x14046FC8C "
                        "(epilogue, rsp unchanged); 6 nops after the jmp", "ok": ok,
               "got": {"findings": findings, "exits": exits}}]
    return {"checks": checks, "pass": ok}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    path = Path(a.exe) if a.exe else find_pinned()
    if not path or not path.is_file():
        print("no pinned exe found; pass --exe", file=sys.stderr)
        return 2
    raw = path.read_bytes()
    receipt = prove_static(raw) if a.static else prove(raw, a.abi)
    if a.out:
        Path(a.out).write_text(json.dumps(receipt, indent=1, default=str))
    for c in receipt["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"])
    print("OVERALL", "PASS" if receipt["pass"] else "FAIL")
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
