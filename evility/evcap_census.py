"""EVCAP2: machine-code census of the learned-evility bitmap and the Skill row index -> bit mapping.

Scans the PINNED executable's own instructions (not Ghidra text) for every reference to a unit record's
learned-evility bitmap at +0x2E70..+0x2EEC (125 bytes = 1,000 bits) and to the sorted Skill key array
(0x140A04E48) / max-index word (0x140A04E38) that turn a Skill id into a bit position, and classifies each
consumer by whether a CALL redirection can reach it:

  A  API      every static `call` of the getter 0x14015E630 / setter 0x14015E6D0 -- what .d5lc hooks
  B  INLINE   a function that inlines the id search and the bit test/set itself (no call to hook)
  C  POINTER  a function that takes the bitmap's address (`lea …, [rec + 0x2e70]`): copies, resets, clones
  D  OTHER    a mention whose base register is the stack or not provably a unit record

Read-only: the exe and the decomp are only read.

    python evility/evcap_census.py [--json ...] [--text ...]
"""
import argparse
import hashlib
import json
from pathlib import Path

PINNED = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
              'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
PINNED_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
DECOMP = Path('/Volumes/Data/Decomp/d5')

GETTER = 0x14015E630
SETTER = 0x14015E6D0
KEY_ARRAY = 0x140A04E48
KEY_MAXI = 0x140A04E38
KEY_ROWS = 0x140A04E50          # the 0x60-byte Skill row array (Overlord's v3.5 reads it)
BITMAP, BITMAP_END = 0x2E70, 0x2EED
BITMAP_BYTES, BIT_COUNT = 125, 1000
STACK_BASES = {'rsp', 'rbp'}


def functions():
    out = {}
    with open(DECOMP / 'index.tsv', 'r', encoding='utf-8', errors='replace') as f:
        next(f, None)
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 3:
                continue
            try:
                out[int(parts[0], 16)] = (parts[1], int(parts[2]))
            except ValueError:
                pass
    return out


def owner(fn, address):
    starts = [a for a in fn if a <= address]
    if not starts:
        return None
    a = max(starts)
    name, size = fn[a]
    return f'{name} (+{address - a:#x})' if address - a < max(size, 1) else None


def fn_name(owner_text):
    return owner_text.split(' (+')[0] if owner_text else '?'


def instructions(cs, data, va):
    pc, end = 0, len(data)
    while pc < end:
        ins = next(cs.disasm(data[pc:pc + 15], va + pc, count=1), None)
        if ins is None:
            pc += 1
            continue
        yield ins
        pc += ins.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path, default=Path('evility/evcap-census.json'))
    ap.add_argument('--text', type=Path, default=Path('evility/EVCAP2-CENSUS.txt'))
    args = ap.parse_args()
    import capstone
    import pefile
    X = capstone.x86
    exe = PINNED.read_bytes()
    assert hashlib.sha256(exe).hexdigest() == PINNED_SHA, 'pinned exe changed'
    pe = pefile.PE(data=exe, fast_load=True)
    fn = functions()
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    calls_get, calls_set, bitmap_sites, key_refs = [], [], [], []
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:
            continue
        va = pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress
        data = exe[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        for ins in instructions(cs, data, va):
            mem = [op.mem for op in ins.operands if op.type == X.X86_OP_MEM]
            if ins.mnemonic == 'call' and ins.operands and ins.operands[0].type == X.X86_OP_IMM:
                t = ins.operands[0].imm & 0xFFFFFFFFFFFFFFFF
                if t in (GETTER, SETTER):
                    (calls_get if t == GETTER else calls_set).append(
                        dict(site=f'0x{ins.address:x}', owner=owner(fn, ins.address)))
            for m in mem:
                base = ins.reg_name(m.base) if m.base else None
                index = ins.reg_name(m.index) if m.index else None
                if BITMAP <= m.disp < BITMAP_END:
                    rec = dict(site=f'0x{ins.address:x}', owner=owner(fn, ins.address),
                               text=f'{ins.mnemonic} {ins.op_str}', base=base, index=index,
                               disp=f'0x{m.disp:x}', width=ins.mnemonic.split()[-1] if 'ptr' in ins.op_str else '?')
                    rec['stack_relative'] = base in STACK_BASES
                    bitmap_sites.append(rec)
                if m.base == X.X86_REG_RIP:
                    target = ins.address + ins.size + m.disp
                    if target in (KEY_ARRAY, KEY_MAXI, KEY_ROWS):
                        key_refs.append(dict(site=f'0x{ins.address:x}', owner=owner(fn, ins.address),
                                             of={KEY_ARRAY: 'key_array', KEY_MAXI: 'max_index',
                                                 KEY_ROWS: 'row_array'}[target],
                                             text=f'{ins.mnemonic} {ins.op_str}'))
    api_funcs = {}
    for rec in calls_get + calls_set:
        api_funcs.setdefault(fn_name(rec['owner']), set()).add(rec['site'])
    key_funcs = {}
    for r in key_refs:
        key_funcs.setdefault(fn_name(r['owner']), []).append(r)
    real_bitmap = [r for r in bitmap_sites if not r['stack_relative']]
    stack_bitmap = [r for r in bitmap_sites if r['stack_relative']]
    inlined = defaultdict_list()
    pointer = defaultdict_list()
    other = defaultdict_list()
    for r in real_bitmap:
        name = fn_name(r['owner'])
        if name in key_funcs:
            inlined[name].append(r)
        elif r['text'].startswith('lea'):
            pointer[name].append(r)
        else:
            other[name].append(r)
    groups = dict(
        api=[dict(function=k, sites=sorted(v)) for k, v in sorted(api_funcs.items())],
        inlined=[dict(function=k, sites=v) for k, v in sorted(inlined.items())],
        pointer=[dict(function=k, sites=v) for k, v in sorted(pointer.items())],
        other=[dict(function=k, sites=v) for k, v in sorted(other.items())],
        stack=stack_bitmap,
    )
    report = dict(exe=str(PINNED), sha256=PINNED_SHA, getter=f'0x{GETTER:x}', setter=f'0x{SETTER:x}',
                  bitmap=dict(offset=f'0x{BITMAP:x}', last=f'0x{BITMAP_END - 1:x}', bytes=BITMAP_BYTES,
                              bits=BIT_COUNT),
                  calls_to_getter=calls_get, calls_to_setter=calls_set,
                  key_array_refs=key_refs, groups=groups,
                  counts=dict(get_calls=len(calls_get), set_calls=len(calls_set),
                              api_functions=len(groups['api']), inlined_functions=len(groups['inlined']),
                              pointer_functions=len(groups['pointer']), other_functions=len(groups['other']),
                              stack_mentions=len(stack_bitmap), key_refs=len(key_refs)))
    lines = ['EVCAP2 machine-code census of the learned-evility bitmap (pinned exe sha256 %s...)' % PINNED_SHA[:16],
             '',
             f'bitmap: unit record +0x{BITMAP:x}..+0x{BITMAP_END - 1:x} ({BITMAP_BYTES} bytes, {BIT_COUNT} bits)',
             f'id -> position: key array 0x{KEY_ARRAY:x}, max index 0x{KEY_MAXI:x}, rows 0x{KEY_ROWS:x}',
             '',
             'A. API call sites -- hooked by .d5lc',
             f'   getter 0x{GETTER:x}: {len(calls_get)} sites in {len(api_funcs)} functions',
             f'   setter 0x{SETTER:x}: {len(calls_set)} sites']
    lines += [f'   {c["site"]}  {c["owner"]}' for c in calls_get + calls_set]
    lines += ['', 'B. inlined id->bit consumers (no call to hook)']
    for g in groups['inlined']:
        lines.append(f'   {g["function"]}')
        lines += [f'      {s["site"]}  {s["text"]}' for s in g['sites']]
    lines += ['', 'C. bitmap pointer taken (copies / resets / clones)']
    for g in groups['pointer']:
        lines.append(f'   {g["function"]}')
        lines += [f'      {s["site"]}  {s["text"]}' for s in g['sites']]
    lines += ['', 'D. unproven base (not provably the unit record) -- listed, not classified']
    for g in groups['other']:
        lines.append(f'   {g["function"]}')
        lines += [f'      {s["site"]}  {s["text"]}' for s in g['sites']]
    lines += ['', f'stack-relative mentions excluded ({len(stack_bitmap)}): not a unit record']
    lines += ['', 'key-array / max-index / row-array references']
    lines += [f'   {r["site"]}  {r["of"]:9s} {r["owner"]}  {r["text"]}' for r in key_refs]
    args.text.write_text('\n'.join(lines) + '\n')
    args.json.write_text(json.dumps(report, indent=1) + '\n')
    c = report['counts']
    print(f"A: {c['get_calls']} getter + {c['set_calls']} setter calls in {c['api_functions']} functions; "
          f"B: {c['inlined_functions']} inlined; C: {c['pointer_functions']} pointer; "
          f"D: {c['other_functions']}; stack {c['stack_mentions']}; key refs {c['key_refs']}")
    print(f'wrote {args.text} and {args.json}')


def defaultdict_list():
    from collections import defaultdict
    return defaultdict(list)


if __name__ == '__main__':
    main()
