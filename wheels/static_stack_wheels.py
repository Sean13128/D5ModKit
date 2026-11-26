"""Static stack audit of the built `.d5mod` section for the wheel page filter (no execution of the game target).

Uses the shared audit of `Subprojects/Engine-Extensions/abi-review/proofs/static_stack.py` (its `audit()` definition,
loaded from the file so the two lanes cannot drift) over the real section `newclasses.build_hooks` appends, and

  * checks every patched site is `E9` into that section (these hooks are jumps, not calls),
  * measures RSP%16 at each patched site from the containing function's prologue (`newclasses.stack_mod16`) instead of
    assuming an entry alignment, then audits each entry with the alignment it actually has,
  * reports every CALL edge with its shadow-space clearance, and rejects an unaligned call, a CALL whose shadow space
    holds live data, an unbalanced return, an unhandled RSP write and an indirect branch.

    python wheels/static_stack_wheels.py [--original PINNED.exe] [--out JSON]

Offline only: reads the pinned exe and writes a JSON receipt.
"""
import argparse
import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

import pefile                                                   # noqa: E402

from d5lib import exemap, exepatch, newclasses                    # noqa: E402

SHARED_AUDIT = Path("/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/abi-review/proofs/static_stack.py")
FAMILY = 1350
WHEELS = [(1270, 1), (1350, 0)]


def shared_audit_source():
    """the shared audit's preamble (imports + `audit`), without running that script's own battery"""
    return SHARED_AUDIT.read_text().split("branch=sys.argv[1]")[0]


def audit_lazy(code, base, entries, wrapper_mod=8):
    """The shared audit's checks, decoded per entry instead of by one linear pass.

    `static_stack.py` decodes the section linearly from `base+16` and looks entries up in that map.  That works for a
    section whose tables all follow its code; the classes section interleaves `.long` tables between stubs, so a linear
    pass desynchronises after the first table and every later entry is "decode/region boundary".  Decoding lazily from
    each instruction the walk actually reaches gives the same instruction stream without that assumption.  The walk,
    the alignment/shadow accounting and the finding categories are the shared tool's (see its docstring).
    """
    import capstone
    from capstone.x86_const import X86_OP_IMM, X86_OP_MEM, X86_OP_REG
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    lo, hi = base, base + len(code)
    cache = {}

    def instruction(pc):
        if pc not in cache:
            if not lo <= pc < hi:
                cache[pc] = None
            else:
                cache[pc] = next(md.disasm(code[pc - lo:pc - lo + 15], pc, count=1), None)
        return cache[pc]

    calls, returns, unknown, home_stores = [], [], [], []
    for entry in sorted(entries):
        mod = wrapper_mod
        pending, seen = [(entry, 0, (0,))], set()
        while pending:
            pc, delta, slots = pending.pop()
            state = (pc, delta, slots)
            if state in seen:
                continue
            seen.add(state)
            i = instruction(pc)
            if i is None:
                if pc >= hi or pc < lo:          # the stub ends by jumping into the game's own code
                    continue
                unknown.append(dict(entry=hex(entry), pc=hex(pc), reason="decode inside region"))
                continue
            m, ops = i.mnemonic, i.operands
            if m == "push":
                delta -= 8
                slots = tuple(sorted((*slots, delta)))
            elif m == "pop":
                slots = tuple(x for x in slots if x != delta)
                delta += 8
            elif m in ("sub", "add") and len(ops) == 2 and ops[0].type == X86_OP_REG \
                    and i.reg_name(ops[0].reg) == "rsp" and ops[1].type == X86_OP_IMM:
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
                unknown.append(dict(entry=hex(entry), pc=hex(pc), reason="unhandled rsp write " + m + " " + i.op_str))
                continue
            if m not in ("push", "call"):
                for op in ops:
                    if (op.type == X86_OP_MEM and op.access & capstone.CS_AC_WRITE
                            and i.reg_name(op.mem.base) == "rsp"):
                        if op.mem.index or op.mem.disp < 32:
                            home_stores.append(dict(entry=hex(entry), pc=hex(pc), instruction=m + " " + i.op_str))
            nxt = pc + i.size
            if m.startswith("j"):
                if not ops or ops[0].type != X86_OP_IMM:
                    unknown.append(dict(entry=hex(entry), pc=hex(pc), reason="indirect branch"))
                    continue
                pending.append((ops[0].imm, delta, slots))
                if m == "jmp":
                    continue
            pending.append((nxt, delta, slots))
    return dict(calls=calls, returns=returns, unknown=unknown, home_stores=home_stores)


def shared_audit():
    """the shared audit function (kept for the receipt's provenance; `audit_lazy` is what runs)"""
    namespace = {"__file__": str(SHARED_AUDIT)}
    exec(compile(shared_audit_source(), str(SHARED_AUDIT), "exec"), namespace)      # noqa: S102
    return namespace["audit"]


def patched(exe_path, wheels=True):
    raw = Path(exe_path).read_bytes()
    previous = exemap.ACTIVE
    exemap.use(exemap.translator_for(raw))
    try:
        spec = {FAMILY: dict(family=FAMILY, template=1150, name="probe", unlocked=True, unlocked_ranks=6,
                             evility_alias={})}
        classes = list(range(FAMILY, FAMILY + 6))
        exe = newclasses.build_hooks(raw, classes, classes, {}, (), specs=spec,
                                     wheel_entries=WHEELS if wheels else None)
    finally:
        exemap.use(previous)
    return raw, exe


def audit_build(exe, raw, audit_entries=None):
    """-> (receipt parts, findings) for one build"""
    section_base, code, _ = section_of(exe)
    sites = hook_sites(exe, section_base, len(code))
    rows, totals = [], dict(sites=len(sites), calls=0, bad_calls=0, unbalanced_returns=0,
                            unknown=0, home_stores=0, non_jump_sites=0)
    previous = exemap.ACTIVE
    exemap.use(exemap.translator_for(raw))
    try:
        for site, target, opcode in sites:
            try:
                mod = newclasses.stack_mod16(raw, None, site=site)
                assumed = False
            except ValueError:                 # a leaf function has no unwind record and no prologue: RSP%16 is 8
                mod, assumed = 8, True
            result = audit_lazy(code, section_base, [target], wrapper_mod=mod)
            calls = result["calls"]
            bad = [c for c in calls if not c["aligned"] or not c["shadow_ok"]]
            rows.append(dict(site=hex(site), target=hex(target), opcode=f"{opcode:02X}", entry_mod16=mod,
                             entry_mod16_assumed=assumed, calls=len(calls), bad_calls=len(bad),
                             unbalanced_returns=sum(not r["balanced"] for r in result["returns"]),
                             unknown=result["unknown"], home_stores=result["home_stores"],
                             detail=[dict(pc=c["pc"], insn=c["instruction"], aligned=c["aligned"],
                                          shadow_ok=c["shadow_ok"], precall_mod16=c["precall_mod16"])
                                     for c in calls]))
            totals["calls"] += len(calls)
            totals["bad_calls"] += len(bad)
            totals["unbalanced_returns"] += sum(not r["balanced"] for r in result["returns"])
            totals["unknown"] += len(result["unknown"])
            totals["home_stores"] += len(result["home_stores"])
            totals["non_jump_sites"] += 1 if opcode != 0xE9 else 0
    finally:
        exemap.use(previous)
    findings = (totals["bad_calls"] + totals["unbalanced_returns"] + totals["unknown"]
                + totals["home_stores"] + totals["non_jump_sites"])
    return dict(section_base=section_base, section_size=len(code),
                section_sha256=hashlib.sha256(code).hexdigest(), totals=totals, findings=findings,
                sites=rows)


def finding_keys(receipt):
    """the findings in a form the two builds share: section addresses move, what a finding *is* does not"""
    keys = []
    for row in receipt["sites"]:
        for c in row["detail"]:
            if not c["aligned"] or not c["shadow_ok"]:
                keys.append(f"call {c['insn']} aligned={c['aligned']} shadow_ok={c['shadow_ok']}")
        keys += [f"unknown {u['reason']}" for u in row["unknown"]]
        keys += [f"home_store {h['instruction']}" for h in row["home_stores"]]
        keys += [f"unbalanced_return {row['site']}"] * row["unbalanced_returns"]
    return keys


def section_of(exe, name_prefix=b".d5"):
    pe = pefile.PE(data=exe, fast_load=True)
    last = max(pe.sections, key=lambda s: s.VirtualAddress)
    if not last.Name.startswith(name_prefix):
        raise SystemExit(f"the last section {last.Name!r} is not a kit section")
    base = pe.OPTIONAL_HEADER.ImageBase + last.VirtualAddress
    code = last.get_data()[:max(last.Misc_VirtualSize, last.SizeOfRawData)]
    return base, code, pe.OPTIONAL_HEADER.ImageBase


def hook_sites(exe, section_base, section_size):
    """(site, target, opcode) for every instruction that jumps into the kit section"""
    out = []
    pe = pefile.PE(data=exe, fast_load=True)
    for s in pe.sections:
        if s.Name.startswith(b".d5"):        # jumps inside the kit section are not hook sites
            continue
        data = s.get_data()
        for i in range(len(data) - 5):
            if data[i] == 0xE9:
                target = (pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress + i + 5
                          + struct.unpack_from("<i", data, i + 1)[0])
                if section_base <= target < section_base + section_size:
                    out.append((pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress + i, target, 0xE9))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", default=None, help="the pinned game exe (default: the kit's game state backup)")
    ap.add_argument("--out", default=str(KIT / "wheels" / "static-stack-wheels.json"))
    args = ap.parse_args()

    original = args.original
    if original is None:
        sys.path.insert(0, str(KIT / "tests"))
        from test_recruit_runtime import pinned_exe
        original = pinned_exe()
        if original is None:
            raise SystemExit("the pinned game exe is not in the kit's game state (pass --original)")
    args.original = original
    raw, exe = patched(original, wheels=True)
    wheels = audit_build(exe, raw)
    raw0, exe0 = patched(original, wheels=False)
    baseline = audit_build(exe0, raw0)

    current, before = collections.Counter(finding_keys(wheels)), collections.Counter(finding_keys(baseline))
    new_findings = sorted((current - before).elements())
    fixed = sorted((before - current).elements())
    receipt = dict(kit=str(KIT), source=args.original, source_sha1=hashlib.sha1(raw).hexdigest(),
                   shared_audit=str(SHARED_AUDIT),
                   shared_audit_sha256=hashlib.sha256(shared_audit_source().encode()).hexdigest(),
                   wheels=wheels, baseline_without_the_filter=baseline,
                   new_findings=new_findings, findings_the_filter_removed=fixed,
                   totals=wheels["totals"], findings=wheels["findings"])
    Path(args.out).write_text(json.dumps(receipt, indent=1) + "\n")
    t = wheels["totals"]
    print(f"sites {t['sites']} calls {t['calls']} bad_calls {t['bad_calls']} "
          f"unbalanced_returns {t['unbalanced_returns']} unknown {t['unknown']} "
          f"home_stores {t['home_stores']} findings {wheels['findings']}")
    print(f"baseline (same hooks, no page filter): findings {baseline['findings']}")
    for row in wheels["sites"]:
        for c in row["detail"]:
            print(f"  call {c['pc']} {c['insn']} aligned={c['aligned']} shadow_ok={c['shadow_ok']} "
                  f"entry_mod16={row['entry_mod16']}")
    print(f"new findings {len(new_findings)}: {new_findings}")
    print(f"pre-existing findings: {sorted((current & before).elements())}")
    if new_findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
