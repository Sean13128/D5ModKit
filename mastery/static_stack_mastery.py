"""Capstone CFG stack audit of the Kit-assembled .d5cm section, with no target/JIT execution.

Same rules as `Subprojects/Engine-Extensions/abi-review/proofs/static_stack.py` (the shared audit
that could not be reused verbatim because it imports `d5lib.evility` and its CALL_SITES): every
routine the section exposes is walked from its entry with a CALL entry RSP%16=8, live push/return
slots are tracked, a CALL is a finding unless its RSP%16 is 0 and 32 bytes of home space are clear
of live saves/returns, a RET is a finding unless the frame is balanced, a stack store below 32 bytes
from RSP is a finding (a live local in outgoing home space), and any branch outside the section or
unhandled RSP write is a finding.  Every patched site must be an E8 CALL or the single E9 jump into
the section, and the section must be the one the kit appends.

`.d5cm` differs from `.d5el` in two ways the audit states up front: the sub-class gate is entered by
jump and leaves by jumping into native code (so its exits are terminal, and it must leave RSP as it
found it), and the sub-class screen's fetch stub writes `r15d` because it stands in for a native
`mov r15d, ...`.

    python mastery/static_stack_mastery.py --original OFFLINE_EXE --output RECEIPT.json

The receipt is written to the requested path. Unicorn is not imported.
"""
import hashlib
import argparse
import json
import struct
import sys
from pathlib import Path

import capstone
from capstone.x86_const import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

import pefile                                                  # noqa: E402
from d5lib import masteryext as mx                             # noqa: E402
from d5lib.exepatch import IMAGE_BASE                          # noqa: E402

ORIGINAL_SHA = "49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce"
MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
MD.detail = True


def audit(code, base, labels, wrapper_mod=8):
    lo, hi = base, base + len(code)
    # The claim bytes interrupt linear decoding; decode the executable region on its own.
    ins = {i.address: i for i in MD.disasm(code[16:], base + 16)}
    entries = set(labels.values())
    entries.update(i.operands[0].imm for i in ins.values()
                   if i.mnemonic == "call" and i.operands[0].type == X86_OP_IMM
                   and lo <= i.operands[0].imm < hi)
    calls, returns, unknown, home_stores, exits = [], [], [], [], []
    for entry in sorted(entries):
        mod = wrapper_mod if entry in labels.values() else 8
        pending, seen = [(entry, 0, (0,))], set()
        while pending:
            pc, delta, slots = pending.pop()
            if (pc, delta, slots) in seen:
                continue
            seen.add((pc, delta, slots))
            i = ins.get(pc)
            if i is None:
                unknown.append(dict(entry=hex(entry), pc=hex(pc), reason="decode/region boundary"))
                continue
            m, ops = i.mnemonic, i.operands
            if m == "push":
                delta -= 8
                slots = tuple(sorted((*slots, delta)))
            elif m == "pop":
                slots = tuple(x for x in slots if x != delta)
                delta += 8
            elif (m in ("sub", "add") and len(ops) == 2 and ops[0].type == X86_OP_REG
                  and i.reg_name(ops[0].reg) == "rsp" and ops[1].type == X86_OP_IMM):
                delta += ops[1].imm * (-1 if m == "sub" else 1)
            elif m == "ret":
                returns.append(dict(entry=hex(entry), pc=hex(pc), balanced=delta == 0, delta=delta))
                continue
            elif m == "call":
                clear = min((s for s in slots if s >= delta), default=0) - delta
                calls.append(dict(entry=hex(entry), pc=hex(pc), instruction=i.op_str,
                                  precall_mod16=(mod + delta) % 16, aligned=(mod + delta) % 16 == 0,
                                  home_clearance=clear, shadow_ok=clear >= 32))
            elif any(i.reg_name(r) == "rsp" for r in i.regs_access()[1]):
                unknown.append(dict(entry=hex(entry), pc=hex(pc),
                                    reason="unhandled rsp write " + m + " " + i.op_str))
                continue
            if m not in ("push", "call"):
                for op in ops:
                    if (op.type == X86_OP_MEM and op.access & capstone.CS_AC_WRITE
                            and i.reg_name(op.mem.base) == "rsp"):
                        if op.mem.index or op.mem.disp < 32:
                            home_stores.append(dict(entry=hex(entry), pc=hex(pc),
                                                    instruction=m + " " + i.op_str))
            nxt = pc + i.size
            if m.startswith("j"):
                if not ops or ops[0].type != X86_OP_IMM:
                    unknown.append(dict(entry=hex(entry), pc=hex(pc), reason="indirect branch"))
                    continue
                target = ops[0].imm
                if not lo <= target < hi:
                    exits.append(dict(entry=hex(entry), pc=hex(pc), instruction=m + " " + i.op_str,
                                      target=hex(target), stack_clean=delta == 0, delta=delta))
                    continue
                pending.append((target, delta, slots))
                if m == "jmp":
                    continue
            pending.append((nxt, delta, slots))
    return dict(calls=calls, returns=returns, unknown=unknown, home_stores=home_stores, exits=exits)


def findings_of(result):
    return (len([c for c in result["calls"] if not c["aligned"] or not c["shadow_ok"]])
            + len([r for r in result["returns"] if not r["balanced"]])
            + len(result["unknown"]) + len(result["home_stores"])
            + len([e for e in result["exits"] if not e["stack_clean"]]))


def assemble(families, original_path):
    """the section's code exactly as build_patch places it, plus its routine labels"""
    original = original_path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, "not the pinned original exe"
    base = mx.code_base(original, mx.SECTION_NAME)
    code = bytearray(mx.CLAIM + bytes(16 - len(mx.CLAIM)))
    labels = {}
    for tag, src in mx._asm_sources(families):
        code += b"\xcc" * (-len(code) % 16)
        labels[tag] = base + len(code)
        code += mx._assemble(src, base + len(code))
    return original, base, bytes(code), labels


def sites_of(patched, families):
    """every patched site: its opcode, its continuation and, for a call, the routine it reaches"""
    pe = pefile.PE(data=patched, fast_load=True)
    info = mx.section_info(patched)
    out = []
    for site in mx.MAPPER_CALLS:
        off = pe.get_offset_from_rva(site - IMAGE_BASE)
        raw = patched[off:off + 5]
        assert raw[0] == 0xE8, (hex(site), raw.hex())
        target = site + 5 + struct.unpack("<i", raw[1:])[0]
        assert info["code"] <= target < info["base"] + info["size"], (hex(site), hex(target))
        out.append(dict(site=hex(site), opcode="E8", continuation=hex(site + 5), target=hex(target)))
    for site, opcode in ((mx.FETCH_SITE, 0xE8), (mx.SUBCLASS_SITE, 0xE9)):
        off = pe.get_offset_from_rva(site - IMAGE_BASE)
        raw = patched[off:off + 5]
        assert raw[0] == opcode, (hex(site), raw.hex())
        target = site + 5 + struct.unpack("<i", raw[1:])[0]
        assert info["code"] <= target < info["base"] + info["size"], (hex(site), hex(target))
        out.append(dict(site=hex(site), opcode=f"{opcode:02X}", continuation=hex(site + 5),
                        target=hex(target)))
    off = pe.get_offset_from_rva(mx.BOUND_SITE - IMAGE_BASE)
    assert patched[off:off + 3] == mx.BOUND_ORIG[:3], patched[off:off + 3].hex()
    out.append(dict(site=hex(mx.BOUND_SITE), opcode="in-place", continuation=hex(mx.BOUND_SITE + 4),
                    target=f"imm8 0x{patched[off + 3]:02X} (0x2F + {len(families)})"))
    return out, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", type=Path, required=True,
                    help="path to an offline copy of the pinned original executable")
    ap.add_argument("--output", type=Path, required=True, help="audit receipt path")
    args = ap.parse_args()
    out = args.output
    report = {"original_sha256": ORIGINAL_SHA, "sections": [], "findings": 0}
    for families in ([1350, 1360], list(range(1350, 1410, 10))):
        original, base, code, labels = assemble(families, args.original)
        patched = mx.build_patch(original, families)
        sites, info = sites_of(patched, families)
        result = audit(code, base, labels)
        findings = findings_of(result)
        used = {s["target"] for s in sites if s["opcode"] in ("E8", "E9")}
        assert used == {hex(v) for v in labels.values()}, (sorted(used), sorted(map(hex, labels.values())))
        report["sections"].append(dict(
            families=families, section=info["section"], section_base=hex(base), code_bytes=len(code),
            section_sha256=hashlib.sha256(code).hexdigest(), sites=sites, findings=findings, audit=result))
        report["findings"] += findings
        print(f"families {len(families)}: {len(sites)} sites, {len(result['calls'])} call edges, "
              f"{len(result['returns'])} returns, {len(result['exits'])} native exits, "
              f"{len(result['unknown'])} unknown, {len(result['home_stores'])} home stores, "
              f"findings {findings}")
    assert report["findings"] == 0, json.dumps(report, indent=1)
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(f"findings {report['findings']} for {len(report['sections'])} family configurations; receipt {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
