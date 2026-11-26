"""FACILITY1 offline proof: the `facility` / `giveup` harness commands (d5lib/native/d5ctl.inc.c) on real exe bytes.

1. signatures: every byte signature the runtime checks (FAC_SIGS, GU_SIGS, parsed from d5ctl.inc.c so the proof
   checks the shipped tables) and the PE timestamp, against each exe given (the pinned original and the installed,
   kit-patched one).  A mismatch is a blocker: the commands would refuse on that exe.
2. site entry (Unicorn, the pinned exe's code): the routines the commands enter, entered the way the runtime's C
   call enters them (RSP = 8 mod 16, args in RCX/RDX/R8):
   * script_cmd_menu_open 0x18AE20(0, 0, route) for every nested/shop facility: the base object gets the request
     triple base_object_request_menu writes (+0x88 = route, +8 = next, +0xC = 3, +0x2C = 2, +0x30E4 = kind);
     and the two gates refuse (forward byte set; task manager in state 26) without touching it;
   * battle_request_route_request 0x4A7240(battle, {9001, 1}): the request giveup queues pushes S42.
   --abi adds: RSP mod 16 at the inner call (base_object_request_menu), RSP and every non-volatile register
   restored at return.
Cryswar's Overlord facility hotkeys (The Unlicense) are the source of the routes and signatures.

    D5Modkit/.venv-macos/bin/python tools/proof_facility.py --exe <pinned> --exe <installed> [--abi] [--out r.json]
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))

import unicorn_darwin_shim                                        # noqa: E402  (Darwin/ARM64 CTR_EL0)

unicorn_darwin_shim.install()

from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError   # noqa: E402
from unicorn.x86_const import (UC_X86_REG_RAX, UC_X86_REG_RBX, UC_X86_REG_RBP, UC_X86_REG_RCX,  # noqa: E402
                               UC_X86_REG_RDI, UC_X86_REG_RDX, UC_X86_REG_RIP, UC_X86_REG_RSI,
                               UC_X86_REG_RSP, UC_X86_REG_R8, UC_X86_REG_R12, UC_X86_REG_R13,
                               UC_X86_REG_R14, UC_X86_REG_R15)
from test_recruit_runtime import pinned_exe, sections               # noqa: E402

SRC = KIT / "d5lib" / "native" / "d5ctl.inc.c"
TIMESTAMP = 0x5C4E7571
BASE = 0x140000000
MENU_OPEN, REQUEST_MENU, ROUTE_REQUEST = 0x18AE20, 0x6A4680, 0x4A7240
TASK_MANAGER, POCKET, FORWARD = 0xBDFD08, 0x7B58EC0, 0x6A07FA8
HEAP, STACK, RET = 0x200000000, 0x10000000, 0x300000000
NONVOL = (UC_X86_REG_RBX, UC_X86_REG_RBP, UC_X86_REG_RSI, UC_X86_REG_RDI,
          UC_X86_REG_R12, UC_X86_REG_R13, UC_X86_REG_R14, UC_X86_REG_R15)
# base_object_request_menu: id -> (next sub-state, +0x30E4 kind or None)   (decomp 0x1406A4680)
EXPECT = {50: (7, 2), 60: (7, 3), 130: (7, 0x12), 135: (7, 0x13), 140: (7, 0x10), 145: (7, 0x11), 190: (7, 0xC),
          310: (7, 0x14)}


def c_tables(src):
    """FAC_SIGS / GU_SIGS {rva, n, bytes} and FACS {name, kind, route} as the runtime ships them"""
    def sigs(name):
        block = re.search(name + r"\[\] = \{(.*?)\n\};", src, re.S).group(1)
        out = []
        for m in re.finditer(r"\{(0x[0-9A-Fa-f]+)u, (\d+), \{([^}]*)\}\}", block):
            b = bytes(int(x, 16) for x in m.group(3).replace("\n", " ").split(",") if x.strip())
            assert len(b) == int(m.group(2)), (name, m.group(1))
            out.append((int(m.group(1), 16), b))
        return out
    facs = [(m.group(1), m.group(2), int(m.group(3))) for m in
            re.finditer(r'\{"(\w+)", FAC_(\w+), (\d+), ', src)]
    return sigs("FAC_SIGS"), sigs("GU_SIGS"), facs


def rva_bytes(data, rva, n):
    _, _, secs = sections(data)
    for name, va, vs, rs, ro in secs:
        if va <= rva < va + max(vs, rs):
            return data[ro + rva - va:ro + rva - va + n]
    return b""


def check_signatures(data, fac_sigs, gu_sigs):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    ts = struct.unpack_from("<I", data, pe + 8)[0]
    rows = []
    for group, sigs in (("facility", fac_sigs), ("giveup", gu_sigs)):
        for rva, want in sigs:
            got = rva_bytes(data, rva, len(want))
            rows.append({"group": group, "rva": f"0x{rva:X}", "n": len(want), "match": got == want})
    return {"timestamp": f"0x{ts:X}", "timestamp_ok": ts == TIMESTAMP, "signatures": rows,
            "ok": ts == TIMESTAMP and all(r["match"] for r in rows)}


def machine(exe):
    base, size, secs = sections(exe)
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
    for name, va, vs, rs, ro in secs:
        if rs:
            mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
    mu.mem_map(HEAP, 0x400000)
    mu.mem_map(STACK, 0x200000)
    mu.mem_map(RET, 0x1000)
    mu.mem_write(RET, b"\xf4")                                   # hlt: the return lands here
    return mu


def call(mu, fn_rva, args, abi, watch=None):
    """enter fn as a C call does (RSP = 8 mod 16, return address pushed); run to the return"""
    rsp = STACK + 0x100000 - 8
    mu.mem_write(rsp, struct.pack("<Q", RET))
    mu.reg_write(UC_X86_REG_RSP, rsp)
    for reg, v in zip((UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8), args):
        mu.reg_write(reg, v)
    marks = [0x1111000000000000 + i for i in range(len(NONVOL))]
    for reg, v in zip(NONVOL, marks):
        mu.reg_write(reg, v)
    seen = []
    if watch is not None:
        mu.hook_add(UC_HOOK_CODE, lambda m, a, n, _: seen.append(m.reg_read(UC_X86_REG_RSP) % 16),
                    begin=BASE + watch, end=BASE + watch)
    try:
        mu.emu_start(BASE + fn_rva, RET, count=200000)
        stop = "returned"
    except UcError as exc:
        stop = f"fault ({exc}) at {mu.reg_read(UC_X86_REG_RIP):#x}"
    out = {"entry_rsp_mod16": rsp % 16, "stopped": stop, "rax": mu.reg_read(UC_X86_REG_RAX)}
    if abi:
        out["rsp_restored"] = mu.reg_read(UC_X86_REG_RSP) == rsp + 8
        out["nonvolatile_preserved"] = all(mu.reg_read(r) == v for r, v in zip(NONVOL, marks))
        if watch is not None:
            out["inner_call_rsp_mod16"] = sorted(set(seen))
    return out


def menu_open_case(exe, route, abi, forward=0, task_state=13):
    mu = machine(exe)
    mgr, pocket = HEAP, HEAP + 0x10000
    mu.mem_write(mgr, struct.pack("<ii", -1, task_state))
    mu.mem_write(pocket, b"\0" * 0x4000)
    mu.mem_write(pocket + 8, struct.pack("<i", 0x7EADBEEF))
    mu.mem_write(BASE + TASK_MANAGER, struct.pack("<Q", mgr))
    mu.mem_write(BASE + POCKET, struct.pack("<Q", pocket))
    mu.mem_write(BASE + FORWARD, bytes([forward]))
    r = call(mu, MENU_OPEN, (0, 0, route), abi, watch=REQUEST_MENU)
    i32 = lambda off: struct.unpack("<i", mu.mem_read(pocket + off, 4))[0]   # noqa: E731
    r.update({"route": route, "id": i32(0x88), "next": i32(8), "mode": i32(0xC), "phase": i32(0x2C),
              "kind": i32(0x30E4)})
    return r


def route_request_case(exe, abi):
    mu = machine(exe)
    battle, req = HEAP, HEAP + 0x300000
    mu.mem_write(battle, b"\0" * 0x2A0000)                       # the object is 2,746,880 bytes
    mu.mem_write(req, struct.pack("<ii", 9001, 1))
    r = call(mu, ROUTE_REQUEST, (battle, req), abi)
    depth = struct.unpack("<i", mu.mem_read(battle + 0x74, 4))[0]
    pushed = [struct.unpack("<i", mu.mem_read(battle + 0x30 + 4 * k, 4))[0] for k in range(4)]
    r.update({"request": [9001, 1], "depth": depth, "stack_head": pushed})
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", action="append", help="exe to check the signatures on (repeat); default: pinned")
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    src = SRC.read_text()
    fac_sigs, gu_sigs, facs = c_tables(src)
    exes = args.exe or [pinned_exe()]
    receipt = {"signatures": {}, "site_entry": {}}
    ok = True
    for p in exes:
        s = check_signatures(Path(p).read_bytes(), fac_sigs, gu_sigs)
        receipt["signatures"][p] = s
        ok &= s["ok"]
    exe = Path(pinned_exe()).read_bytes()
    cases = []
    for name, kind, route in facs:
        if kind not in ("NESTED", "SHOP"):
            continue
        r = menu_open_case(exe, route, args.abi)
        nxt, knd = EXPECT[route]
        r["facility"] = name
        r["pass"] = (r["stopped"] == "returned" and r["rax"] == 1 and r["id"] == route and r["next"] == nxt
                     and r["mode"] == 3 and r["phase"] == 2 and r["kind"] == knd)
        if args.abi:
            r["pass"] &= r["rsp_restored"] and r["nonvolatile_preserved"] and r["inner_call_rsp_mod16"] == [8]
        cases.append(r)
    for label, kw in (("forward byte set", {"forward": 1}), ("task manager in state 26", {"task_state": 26})):
        r = menu_open_case(exe, 145, args.abi, **kw)
        r["facility"] = f"quest_shop refused: {label}"
        r["pass"] = r["stopped"] == "returned" and r["next"] == 0x7EADBEEF and r["id"] == 0
        cases.append(r)
    receipt["site_entry"]["menu_open"] = cases
    g = route_request_case(exe, args.abi)
    g["pass"] = g["stopped"] == "returned" and g["depth"] == 1 and g["stack_head"][0] == 42
    if args.abi:
        g["pass"] &= g["rsp_restored"] and g["nonvolatile_preserved"]
    receipt["site_entry"]["giveup_route_request"] = g
    ok &= all(c["pass"] for c in cases) and g["pass"]
    receipt["ok"] = ok
    text = json.dumps(receipt, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    print(text if not args.out else f"{'PASS' if ok else 'FAIL'} -> {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
