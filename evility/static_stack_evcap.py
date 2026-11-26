"""Static stack audit of the assembled .d5lc section (no target execution).

Same method as Subprojects/Engine-Extensions/abi-review/proofs/static_stack.py: assume every function entry
is reached by a `call` (entry RSP % 16 = 8), walk the CFG, track the frame delta and the live push slots,
and reject every `call` that is not 16-byte aligned with 32 bytes of home space clear of a live save or
return address.  Also verifies that every instruction the build patched is a 5-byte `E8` into the section
and that each routine's every `ret` reverses its own prologue.

    python evility/static_stack_evcap.py [--json evility/evcap-static-stack.json]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))

ORIGINAL = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
                'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
ORIGINAL_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
TABLE = list(range(1, 1001)) + [21000, 21001]


def audit(code, base, entries, lo, hi):
    """CFG stack audit; -> findings"""
    import capstone
    from capstone.x86_const import X86_OP_IMM, X86_OP_REG
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    ins = {x.address: x for x in md.disasm(code[16:], base + 16)}
    calls, returns, unknown, home_stores = [], [], [], []
    for entry in sorted(entries):
        pending = [(entry, 0, (0,))]
        seen = set()
        while pending:
            pc, delta, slots = pending.pop()
            if (pc, delta, slots) in seen:
                continue
            seen.add((pc, delta, slots))
            i = ins.get(pc)
            if i is None:
                unknown.append(dict(entry=hex(entry), pc=hex(pc), reason='decode/region boundary'))
                continue
            m, ops = i.mnemonic, i.operands
            if m == 'push':
                delta -= 8
                slots = tuple(sorted((*slots, delta)))
            elif m == 'pop':
                slots = tuple(x for x in slots if x != delta)
                delta += 8
            elif m in ('sub', 'add') and len(ops) == 2 and ops[0].type == X86_OP_REG \
                    and i.reg_name(ops[0].reg) == 'rsp' and ops[1].type == X86_OP_IMM:
                delta += ops[1].imm * (-1 if m == 'sub' else 1)
            elif m == 'ret':
                returns.append(dict(entry=hex(entry), pc=hex(pc), balanced=delta == 0, delta=delta))
                continue
            elif m == 'call':
                clear = min((s for s in slots if s >= delta), default=0) - delta
                calls.append(dict(entry=hex(entry), pc=hex(pc), instruction=i.op_str,
                                  precall_mod16=(8 + delta) % 16, aligned=(8 + delta) % 16 == 0,
                                  home_clearance=clear, shadow_ok=clear >= 32))
            elif any(i.reg_name(r) == 'rsp' for r in i.regs_access()[1]):
                unknown.append(dict(entry=hex(entry), pc=hex(pc), reason='unhandled rsp write %s %s' % (m, i.op_str)))
                continue
            if m not in ('push', 'call'):
                for op in ops:
                    if op.type == capstone.x86.X86_OP_MEM and op.access & capstone.CS_AC_WRITE \
                            and i.reg_name(op.mem.base) == 'rsp':
                        if op.mem.index or op.mem.disp < 32:
                            home_stores.append(dict(entry=hex(entry), pc=hex(pc),
                                                    instruction='%s %s' % (m, i.op_str)))
            nxt = pc + i.size
            if m.startswith('j'):
                if not ops or ops[0].type != X86_OP_IMM:
                    unknown.append(dict(entry=hex(entry), pc=hex(pc), reason='indirect branch'))
                    continue
                pending.append((ops[0].imm, delta, slots))
                if m == 'jmp':
                    continue
            pending.append((nxt, delta, slots))
    return dict(calls=calls, returns=returns, unknown=unknown, home_stores=home_stores)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path, default=Path('evility/evcap-static-stack.json'))
    args = ap.parse_args()
    from d5lib import learned
    import pefile
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, 'pinned exe changed'
    man = learned.manifest(TABLE)
    patched = learned.build_patch(original, man)
    info = learned.section_info(patched)
    src = learned.section_source(man)
    code, labels = learned._assemble(src, learned.code_base(original, learned.SECTION))
    lo, hi = learned.code_base(original, learned.SECTION), learned.code_base(original, learned.SECTION) + len(code)
    report = audit(code, learned.code_base(original, learned.SECTION), set(labels.values()), lo, hi)
    # every patched instruction must be an E8 into the section, at the named wrapper
    pe = pefile.PE(data=patched, fast_load=True)
    sites = []
    plan = [(learned.GET_SITES, labels['lc_get'], learned.GETTER),
            (learned.SET_SITES, labels['lc_set'], learned.SETTER),
            (learned.SAVE_SITES, labels['lc_save_relay'], learned.MAKE_HEADER),
            (learned.LOAD_SITES, labels['lc_load_relay'], learned.DECODE_SLOT)]
    for site_list, wrapper, target in plan:
        for va in site_list:
            raw = patched[pe.get_offset_from_rva(va - 0x140000000):][:5]
            dest = va + 5 + struct.unpack('<i', raw[1:])[0]
            sites.append(dict(site=hex(va), opcode=raw[0], target_ok=dest == wrapper,
                              was_call_to=f'0x{target:x}'))
    findings = []
    for c in report['calls']:
        if not c['aligned']:
            findings.append(f"unaligned call at {c['pc']} ({c['instruction']})")
        if not c['shadow_ok']:
            findings.append(f"home space not clear at {c['pc']} ({c['instruction']})")
    for r in report['returns']:
        if not r['balanced']:
            findings.append(f"unbalanced ret at {r['pc']} (delta {r['delta']})")
    findings += [f"undecoded instruction at {u['pc']} ({u['reason']})" for u in report['unknown']]
    findings += [f"stack store in outgoing home space at {h['pc']} ({h['instruction']})" for h in report['home_stores']]
    findings += [f"site {s['site']} is not a call into the wrapper" for s in sites if not s['target_ok']]
    out = dict(original_sha256=ORIGINAL_SHA, section=info['section'], routines=len(labels),
               call_edges=len(report['calls']), returns=len(report['returns']),
               patched_sites=len(sites), findings=findings)
    args.json.write_text(json.dumps(out, indent=1) + '\n')
    print(f"{len(labels)} routines, {len(report['calls'])} call edges, {len(sites)} patched E8 sites, "
          f"{len(findings)} findings")
    for f in findings:
        print('  ' + f)
    return 0 if not findings else 1


if __name__ == '__main__':
    sys.exit(main())
