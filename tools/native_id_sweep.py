"""Static candidate sweep for explicit ID-query targets in an x64 PE.

Research aid only: linear decoding and local constant propagation are not a
control-flow or behavior proof. All target addresses, ID catalogs and field
offsets are caller-supplied; no game-specific research is embedded here.
"""
from bisect import bisect_right
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import exemap


def sha(data):
    return hashlib.sha256(data).hexdigest()


def number(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def register(name):
    """Return canonical integer-register name and written bit width."""
    table = {}
    for root, names in {'rax':('rax','eax','ax','al'), 'rbx':('rbx','ebx','bx','bl'),
                        'rcx':('rcx','ecx','cx','cl'), 'rdx':('rdx','edx','dx','dl'),
                        'rsi':('rsi','esi','si','sil'), 'rdi':('rdi','edi','di','dil'),
                        'rbp':('rbp','ebp','bp','bpl'), 'rsp':('rsp','esp','sp','spl')}.items():
        table.update({n:(root,w) for n,w in zip(names,(64,32,16,8))})
    for i in range(8,16):
        table.update({f'r{i}{suffix}':(f'r{i}',width) for suffix,width in (('',64),('d',32),('w',16),('b',8))})
    return table.get(name, (name,0))


def describe(insn):
    return dict(address=hex(insn.address), bytes=insn.bytes.hex(),
                mnemonic=insn.mnemonic, operands=insn.op_str)


def analyze(instructions, targets, ids, typed_offsets):
    """Conservative straight-line facts; clear on calls and branch boundaries.

    This intentionally does not propagate through basic-block merges, memory,
    arithmetic, stack slots or function returns. Subregister writes retain only
    their known low bits. Every retained call includes its assignment source.
    """
    from capstone.x86 import X86_OP_REG, X86_OP_IMM, X86_OP_MEM
    state, tags = {}, {}
    destinations = set()
    for insn in instructions:
        if insn.mnemonic.startswith('j') and insn.operands and insn.operands[0].type == X86_OP_IMM:
            destinations.add(insn.operands[0].imm)
    queries, immediates, comparisons = [], [], []
    for position, insn in enumerate(instructions):
        if insn.address in destinations:
            state.clear(); tags.clear()
        ops = insn.operands
        is_transfer = insn.mnemonic in ('call','jmp')
        target = ops[0].imm if is_transfer and ops and ops[0].type == X86_OP_IMM else None
        if target in targets:
            spec = targets[target]
            root, _ = register(spec['register'])
            fact = state.get(root)
            required = spec.get('bits',32)
            known = fact is not None and fact['bits'] >= required
            value = fact['value'] & ((1 << required)-1) if known else None
            queries.append(dict(**describe(insn), target=hex(target), role=spec['role'],
                                argument_register=spec['register'], argument_bits=required,
                                id=value, catalogued=value in ids if known else None,
                                resolution='local-literal' if known else 'dynamic-or-unresolved',
                                assignment=fact if known else None,
                                post_context=[describe(i) for i in instructions[position+1:position+7]],
                                pre_context=[describe(i) for i in instructions[max(0,position-6):position]]))
        if not is_transfer and not insn.mnemonic.startswith('j'):
            for n, operand in enumerate(ops):
                if operand.type == X86_OP_IMM and operand.imm in ids:
                    row = dict(**describe(insn), id=operand.imm, operand_index=n)
                    immediates.append(row)
                    if insn.mnemonic in ('cmp','test'):
                        origins=[]
                        for other in ops:
                            if other.type == X86_OP_REG:
                                origins.extend(tags.get(register(insn.reg_name(other.reg))[0], []))
                            elif other.type == X86_OP_MEM and other.mem.disp in typed_offsets:
                                origins.append(dict(field_offset=hex(other.mem.disp),
                                                    field_role=typed_offsets[other.mem.disp], source=describe(insn)))
                        if origins:
                            comparisons.append(dict(**row, origins=origins,
                                                    confidence='field-offset-context-candidate',
                                                    post_context=[describe(i) for i in instructions[position+1:position+4]]))
        # Capture the old register facts before invalidating written registers.
        value_fact = None
        source_tags = []
        if insn.mnemonic in ('mov','movzx','movsx','movsxd') and len(ops)==2 and ops[0].type==X86_OP_REG:
            destination, width = register(insn.reg_name(ops[0].reg))
            source = ops[1]
            if source.type == X86_OP_IMM:
                value_fact = dict(value=source.imm & ((1 << width)-1), bits=width,
                                  source=describe(insn))
            elif source.type == X86_OP_REG:
                source_root, source_width = register(insn.reg_name(source.reg))
                old = state.get(source_root)
                # Sign/zero-extension is admitted only when all source bits are known.
                if old and old['bits'] >= source_width:
                    value = old['value'] & ((1 << source_width)-1)
                    if insn.mnemonic in ('movsx','movsxd') and value & (1 << (source_width-1)):
                        value -= 1 << source_width
                    value_fact = dict(value=value & ((1 << width)-1), bits=width,
                                      source=describe(insn), prior_source=old)
                source_tags = tags.get(source_root, [])
            elif source.type == X86_OP_MEM and source.mem.disp in typed_offsets:
                source_tags = [dict(field_offset=hex(source.mem.disp),
                                    field_role=typed_offsets[source.mem.disp], source=describe(insn))]
        elif insn.mnemonic in ('xor','sub') and len(ops)==2 and ops[0].type==X86_OP_REG and ops[1].type==X86_OP_REG and ops[0].reg==ops[1].reg:
            _, width = register(insn.reg_name(ops[0].reg))
            value_fact = dict(value=0, bits=width, source=describe(insn))
        _, written = insn.regs_access()
        for reg in written:
            root, _ = register(insn.reg_name(reg))
            state.pop(root,None); tags.pop(root,None)
        if ops and ops[0].type==X86_OP_REG:
            root, width = register(insn.reg_name(ops[0].reg))
            if value_fact:
                # x64 32-bit writes zero the upper half of the register.
                if width==32: value_fact['bits']=64
                state[root]=value_fact
            if source_tags: tags[root]=source_tags
        if insn.mnemonic in ('call','ret','retf','jmp') or insn.mnemonic.startswith('j'):
            state.clear(); tags.clear()
    return queries, comparisons, immediates


def read_index(path):
    # Some retained exporters used literal backslash-t separators.
    text=path.read_text().replace('\\t','\t')
    import csv
    rows=list(csv.DictReader(text.splitlines(), delimiter='\t'))
    rows.sort(key=lambda row:number(row['address']))
    return rows


def sweep(config, output):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    binary=Path(config['binary']); raw=binary.read_bytes()
    if sha(raw)!=config['sha256']: raise ValueError('binary SHA-256 mismatch')
    exe=exemap.Exe(raw)
    if exe.pe.FILE_HEADER.Machine!=0x8664: raise ValueError('x64 PE required')
    ids=set(map(number, config['ids']))
    targets={number(t['address']):t for t in config['targets']}
    typed={number(k):v for k,v in config.get('typed_offsets',{}).items()}
    index_path=Path(config['index']); index=read_index(index_path)
    starts=[number(row['address']) for row in index]
    croot=index_path.parent
    source_pins={}
    def owner(address):
        n=bisect_right(starts,address)-1
        if n<0:return None
        row=index[n]
        path=croot/row['file'] if row['file'] else None
        if path and path.exists() and str(path) not in source_pins:
            source_pins[str(path)]=sha(path.read_bytes())
        return dict(entry=row['address'], name=row['name'], exported_size=row['size'],
                    next_entry=hex(starts[n+1]) if n+1<len(starts) else None,
                    ownership='nearest-index-entry-partition-not-body-proof',
                    export_file=str(path) if path else None,
                    export_sha256=source_pins.get(str(path)))
    output.mkdir(parents=True, exist_ok=False)
    handles={key:(output/f'{key}.jsonl').open('w') for key in ('queries','typed-comparisons','immediates','decode-frontiers')}
    counts=Counter(); seen=set(); ranges=exe.functions(); original_ranges=set(exe._listed)
    cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True
    for lo,hi in ranges:
        blob=exe.read(lo,hi-lo)
        decoded=list(cs.disasm(blob,exe.base+lo))
        end=decoded[-1].address+decoded[-1].size-exe.base if decoded else lo
        if end!=hi:
            handles['decode-frontiers'].write(json.dumps(dict(start=hex(exe.base+lo),end=hex(exe.base+hi),
                stopped=hex(exe.base+end), provenance='pdata' if (lo,hi) in original_ranges else 'padding-heuristic-leaf'))+'\n')
            counts['partial_ranges']+=1
        fresh=[i for i in decoded if i.address not in seen]
        seen.update(i.address for i in decoded)
        counts['decoded_instructions']+=len(fresh)
        counts['decoded_bytes']+=sum(i.size for i in fresh)
        q,t,m=analyze(decoded,targets,ids,typed)
        for category,rows in (('queries',q),('typed-comparisons',t),('immediates',m)):
            for row in rows:
                dedup=(category, row['address'],row.get('operand_index'))
                # RUNTIME_FUNCTION records may overlap/chained tails.
                if dedup in seen:continue
                seen.add(dedup)
                row['owner']=owner(number(row['address']))
                row['decode_range']=dict(start=hex(exe.base+lo), end=hex(exe.base+hi),
                                         provenance='pdata' if (lo,hi) in original_ranges else 'padding-heuristic-leaf')
                handles[category].write(json.dumps(row,sort_keys=True)+'\n')
                counts[category]+=1
                if category=='queries':counts[row['resolution']]+=1
    for handle in handles.values():handle.close()
    manifest=dict(schema='native-id-static-sweep/1', binary=str(binary), binary_sha256=sha(raw),
                  image_base=hex(exe.base), index=str(index_path), index_sha256=sha(index_path.read_bytes()),
                  ranges=len(ranges), pdata_ranges=len(original_ranges), counts=dict(counts),
                  source_pins=source_pins, config=config,
                  limitations=['Static decoded windows only; no control-flow reachability or behavior proof.',
                               'Nearest exported entry is an ownership partition, not a recovered function-body claim.',
                               'Padding-based leaf ranges and inline field-offset contexts are candidates.',
                               'No propagation across calls, jumps, memory, arithmetic or merges.',
                               'Indirect calls, data-driven IDs, undecoded bytes and unknown helpers remain outside resolved coverage.'],
                  output_hashes={p.name:sha(p.read_bytes()) for p in sorted(output.glob('*.jsonl'))})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    result=sweep(json.loads(args.config.read_text()),args.output)
    print(json.dumps({key:result[key] for key in ('ranges','pdata_ranges','counts')},sort_keys=True))
