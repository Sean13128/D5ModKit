"""WHEELS3 — the A/B that decides the LIVE12 wedge, on the pinned exe's real bytes.

WHEELS2's carousel filter called GetKeyboardState like this (emitted bytes, pinned build):

    0x148095657  call 0x1408ce670

`0x1408d5640` (translated: 0x1408ce670) is the IMPORT ADDRESS SLOT for USER32!GetKeyboardState --
8 bytes of `.rdata` holding the function's address, the same slot `d5lib/native/d5auto.c` replaces.
A `call` to that address executes the slot's pointer bytes as code.

This script runs both forms on the real image, in Unicorn, and writes the receipt that separates
them: A (call the slot) faults inside the pointer bytes; B (load the slot, call the pointer)
returns.  Nothing is installed, launched or written outside the receipt.

    python wheels/proof_keyslot.py --out wheels/proof-keyslot.json
"""
import argparse
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))

import unicorn_darwin_shim                                       # noqa: E402  (Darwin/ARM64 CTR_EL0)

ERROR = unicorn_darwin_shim.install()

from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE,   # noqa: E402
                     UC_HOOK_MEM_INVALID, UcError)
from unicorn.x86_const import (UC_X86_REG_RAX, UC_X86_REG_RBX, UC_X86_REG_RCX,  # noqa: E402
                               UC_X86_REG_RIP, UC_X86_REG_RSP)

from d5lib import exemap, newclasses                              # noqa: E402
from test_recruit_runtime import (BUILDER, CHARTAB, COUNT_G, OBJECT, PTR_G, STACK as TSTACK,  # noqa: E402
                                  char_rows, pinned_exe, read_entry_buffer, sections)

CODE = 0x180000000          # scratch for the two call shapes (outside the image)
STUB = 0x180010000          # the stand-in the loader's pointer is aimed at
STACK = 0x10000000


def file_offset(exe, va):
    base, _, secs = sections(exe)
    for name, v, vs, rs, ro in secs:
        if v <= va - base < v + max(vs, rs):
            return ro + (va - base - v)
    raise AssertionError(f"{va:#x} is not mapped")


def section_of(exe, va):
    base, _, secs = sections(exe)
    for name, v, vs, rs, ro in secs:
        if v <= va - base < v + max(vs, rs):
            return name
    return None


def machine(exe, translate, point_slot=True):
    base, size, secs = sections(exe)
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
    for name, va, vs, rs, ro in secs:
        if rs:
            mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
    mu.mem_map(STACK, 0x200000)
    mu.mem_map(CODE, 0x1000)
    mu.mem_map(STUB, 0x1000)
    mu.mem_write(STUB, b"\xb8\x01\x00\x00\x00\xc3")               # mov eax,1 / ret
    slot = translate(newclasses.KEYS_SLOT)
    if point_slot:                                                # what the loader writes into the slot
        mu.mem_write(slot, struct.pack("<Q", STUB))
    return mu, slot


def run(mu, code, ret_addr):
    """run `code` at CODE with rsp as a CALL leaves it for the callee, catching the fault"""
    mu.mem_write(CODE, code)
    mu.reg_write(UC_X86_REG_RSP, STACK + 0x100000)                # 16-aligned at the call site
    mu.mem_write(STACK + 0x100000, struct.pack("<Q", ret_addr))    # the call's return address slot
    fault = {}

    def on_invalid(m, access, address, size, value, _):
        kind = {16: "read", 17: "write", 18: "read-unmapped", 19: "write-unmapped",
                20: "fetch-prot", 21: "fetch-unmapped"}.get(access, f"access-{access}")
        fault.update({"access": kind, "address": address, "size": size,
                      "rip": m.reg_read(UC_X86_REG_RIP)})
        m.emu_stop()
        return False                                              # stop with UC_ERR_*

    mu.hook_add(UC_HOOK_MEM_INVALID, on_invalid)          # a fresh machine per case: no removal needed
    try:
        mu.emu_start(CODE, 0, count=64)
        stopped = "returned"
    except UcError as exc:
        stopped = f"fault ({exc})"
    return {"stopped": stopped, "fault": fault, "rax": mu.reg_read(UC_X86_REG_RAX),
            "rip": mu.reg_read(UC_X86_REG_RIP)}


def hook_run(exe, translate, shift_digit):
    """the real built hook, end to end: page chosen, count, and RSP%16 at the function the slot points to"""
    base, size, secs = sections(exe)
    site = translate(newclasses.CAROUSEL_VA)
    entry = read_entry_buffer(exe, site)
    slot = translate(newclasses.KEYS_SLOT)
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    mu.mem_map(base, (size + 0xFFF) // 0x1000 * 0x1000)
    for name, va, vs, rs, ro in secs:
        if rs:
            mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
    mu.mem_map(TSTACK, 0x200000)
    mu.mem_map(STUB, 0x1000)
    mu.mem_write(STUB, b"\xb8\x01\x00\x00\x00\xc3")               # mov eax,1 / ret
    mu.mem_write(slot, struct.pack("<Q", STUB))
    families = sorted(set(newclasses.HIRE_LIST) | {1270, 1280, 1290})
    mu.mem_write(CHARTAB, char_rows(families))
    mu.mem_write(PTR_G, struct.pack("<Q", CHARTAB))
    mu.mem_write(COUNT_G, struct.pack("<I", len(families)))
    mu.mem_write(translate(newclasses.FLAGS_VA) + (17001 >> 3), b"\xff" * 300)
    mu.mem_write(OBJECT, b"\x00" * 0x800)
    mu.mem_write(entry, b"\x00" * (newclasses.CAROUSEL_CAP * 8))
    state = bytearray(256)
    state[0x10] = 0x80
    state[0x31 + shift_digit - 1] = 0x80
    seen = []

    def at_stub(m, addr, n, _):
        seen.append(m.reg_read(UC_X86_REG_RSP) % 16)
        m.mem_write(m.reg_read(UC_X86_REG_RCX), bytes(state))
    mu.hook_add(UC_HOOK_CODE, at_stub, begin=STUB, end=STUB)
    mu.reg_write(UC_X86_REG_RSP, TSTACK + 0x100000 + 8)
    mu.reg_write(UC_X86_REG_RCX, OBJECT)
    mu.emu_start(BUILDER, 0, count=20000000)
    n = struct.unpack("<i", mu.mem_read(OBJECT + 0x208, 4))[0]
    fams = [struct.unpack("<ii", mu.mem_read(entry + 8 * k, 8))[0] for k in range(max(0, min(n, 64)))]
    page = struct.unpack("<I", mu.mem_read(entry + newclasses.WHEEL_HEADER + newclasses.WHEEL_PAGE, 4))[0]
    return {"calls": len(seen), "rsp_mod16_at_callee": sorted(set(seen)), "count": n,
            "page": page, "families_head": fams}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(KIT / "wheels" / "proof-keyslot.json"))
    ap.add_argument("--original", default=None)
    args = ap.parse_args()
    original = args.original or pinned_exe()
    if original is None:
        raise SystemExit("the pinned game exe is not in the kit's game state")
    exe = Path(original).read_bytes()
    translate = exemap.translator_for(exe)

    slot = translate(newclasses.KEYS_SLOT)
    pointer = struct.unpack("<Q", exe[file_offset(exe, slot):][:8])[0]
    receipt = {
        "exe": {"path": original, "bytes": len(exe)},
        "keys_slot": {"known": f"0x{newclasses.KEYS_SLOT:x}", "translated": f"0x{slot:x}",
                      "section": section_of(exe, slot), "loaded_pointer": f"0x{pointer:x}"},
    }

    # ---- A: WHEELS2 — `call <slot address>`
    mu, slot_va = machine(exe, translate, point_slot=False)   # the slot keeps its real bytes
    a = run(mu, b"\x48\xc7\xc0\x01\x00\x00\x00"                    # mov rax,1      (what the hook leaves)
                + b"\xe8" + struct.pack("<i", slot_va - (CODE + 12))  # call <slot>
                + b"\xc3",                                            # ret
            0)
    a["form"] = "call <slot address> (WHEELS2)"
    a["executed_bytes"] = exe[file_offset(exe, slot):][:8].hex()   # the slot's own bytes, run as code
    a["registers_at_entry"] = {"rax": 0, "rsi": 0, "rdi": 0}
    receipt["A"] = a

    # ---- B: WHEELS3 — load the slot, call the pointer
    mu, slot_va = machine(exe, translate)
    b = run(mu, b"\x48\xc7\xc0\x01\x00\x00\x00"                    # mov rax,1
                + b"\x48\xbb" + struct.pack("<Q", slot_va)          # mov rbx,<slot>
                + b"\x48\x8b\x1b"                                  # mov rbx,[rbx]
                + b"\xff\xd3"                                      # call rbx
                + b"\xc3",                                         # ret
            0)
    b["form"] = "call [slot] (WHEELS3)"
    receipt["B"] = b

    # ---- C: the real built hook, with wheels enabled (the "--abi" end: measured, not assumed)
    wheels = [(1270, 1), (1280, 2), (1290, 1)]
    previous = exemap.ACTIVE
    exemap.use(translate)
    try:
        classes = [f + k for f in (1270, 1280, 1290) for k in range(6)]
        specs = {f: dict(family=f, template=1150, name="M", unlocked=True, unlocked_ranks=6, evility_alias={})
                 for f in (1270, 1280, 1290)}
        built = newclasses.build_hooks(exe, classes, classes, {}, (), specs=specs, wheel_entries=wheels)
    finally:
        exemap.use(previous)
    receipt["C"] = {
        "form": "the real hook in the built exe: Shift+2 (the D4 page)",
        "run": hook_run(built, translate, 2),
        "note": "rsp_mod16_at_callee must be [8]: 16-aligned at the CALL, the Windows x64 contract",
    }

    receipt["verdict"] = {
        "A_faults_in_data": a["stopped"].startswith("fault") and not a["fault"] == {},
        "A_fault_instruction": a["fault"].get("rip"),
        "B_returns_one": b["stopped"] == "returned" and b["rax"] == 1,
        "C_call_aligned": receipt["C"]["run"]["rsp_mod16_at_callee"] == [8],
        "C_page_chosen": receipt["C"]["run"]["page"] == 1 and receipt["C"]["run"]["count"] > 0,
        "emulated": ERROR,
    }
    Path(args.out).write_text(json.dumps(receipt, indent=1))
    print(json.dumps(receipt["verdict"], indent=1))
    print("receipt ->", args.out)


if __name__ == "__main__":
    main()
