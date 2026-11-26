"""Synthetic PE and metadata round-trips; no game files or native execution."""
import struct

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

from d5lib import evility, exepatch

BASE = exepatch.IMAGE_BASE
REGS = ('rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi',
        'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15')


def fixture():
    data = bytearray(0x800)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 2, 0, 0, 0, 0xf0, 0x22)
    oh = 0x98
    struct.pack_into('<H', data, oh, 0x20b)
    struct.pack_into('<Q', data, oh + 24, BASE)
    struct.pack_into('<II', data, oh + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, oh + 56, 0x3000, 0x400)
    struct.pack_into('<I', data, oh + 108, 16)
    struct.pack_into('<II', data, oh + 112 + 3 * 8, 0x2000, 12)
    for n, (name, rva, raw, flags) in enumerate([
            (b'.text', 0x1000, 0x400, 0x60000020),
            (b'.pdata', 0x2000, 0x600, 0x40000040)]):
        struct.pack_into('<8sIIIIIIHHI', data, oh + 0xf0 + 40 * n,
                         name, 0x200, rva, 0x200, raw, 0, 0, 0, 0, flags)
    data[0x400:0x600] = b'\xcc' * 0x200
    data[0x400] = 0xc3
    struct.pack_into('<III', data, 0x600, 0x1000, 0x1001, 0x2010)
    data[0x610:0x614] = bytes((1, 0, 0, 0))
    return bytes(data)


def build(raw):
    base = exepatch.code_base(raw)
    code, labels = evility._assemble(evility._asm_source(*evility.table({})), base)
    patches = [(BASE + 0x1020 + n * 8, b'\xcc' * 5, target, 0xe8)
               for n, target in enumerate(labels.values())]
    return exepatch.add_code_section(raw, b'.d5el', code, patches), base, code, labels


def records(pe):
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    assert directory.Size % 12 == 0
    assert directory.VirtualAddress + directory.Size <= pe.OPTIONAL_HEADER.SizeOfImage
    data = pe.get_data(directory.VirtualAddress, directory.Size)
    assert len(data) == directory.Size
    entries = list(struct.iter_unpack('<III', data))
    assert entries == sorted(entries)
    assert all(a < b and u % 4 == 0 for a, b, u in entries)
    assert all(left[1] <= right[0] for left, right in zip(entries, entries[1:]))
    for _, _, unwind in entries:
        assert pe.get_data(unwind, 1) == b'\x01'
    return entries


def test_exception_directory_preserved_and_new_code_covered_when_appending_and_growing():
    raw = fixture()
    previous = records(pefile.PE(data=raw))
    for _ in range(2):
        raw, base, code, labels = build(raw)
        entries = records(pefile.PE(data=raw))
        assert entries[:len(previous)] == previous
        expected = exepatch._d5ev_functions(code, base, labels.values())
        added = entries[len(previous):]
        assert [(a, b) for a, b, _ in added] == [(a, b) for a, b, _ in expected]
        pe = pefile.PE(data=raw)
        for (_, _, unwind), (_, _, info) in zip(added, expected):
            assert pe.get_data(unwind, len(info)) == info
        for target in labels.values():
            assert any(a <= target - BASE < b for a, b, _ in added)
        previous = entries


def test_unwind_restores_stack_and_nonvolatiles_at_prologue_and_body_pcs():
    raw, base, code, labels = build(fixture())
    pe = pefile.PE(data=raw)
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    for begin, end, unwind in records(pe)[1:]:
        header = pe.get_data(unwind, 4)
        size, count = header[1:3]
        encoded = pe.get_data(unwind + 4, count * 2)
        operations, cursor = [], 0
        while cursor < len(encoded):
            off, op = encoded[cursor:cursor + 2]
            cursor += 2
            kind, info = op & 15, op >> 4
            if kind == 0:
                operations.append((off, 'push', REGS[info]))
            elif kind == 2:
                operations.append((off, 'alloc', info * 8 + 8))
            else:
                assert kind == 1 and info == 0
                amount = struct.unpack_from('<H', encoded, cursor)[0] * 8
                cursor += 2
                operations.append((off, 'alloc', amount))
        assert operations == sorted(operations, reverse=True, key=lambda x: x[0])
        boundaries = {0, size}  # first body instruction; epilogues have a separate simulation below
        instructions = list(md.disasm(pe.get_data(begin, size), BASE + begin))
        boundaries.update(i.address + i.size - BASE - begin for i in instructions)
        for pc in boundaries:
            initial_rsp = 0x100008
            original = {r: 0xabcdef0000 + n * 17 for n, r in enumerate(REGS)}
            registers, stack, rsp = dict(original), {initial_rsp: 0xfeedface}, initial_rsp
            for i in instructions:
                off = i.address + i.size - BASE - begin
                if off > min(pc, size):
                    break
                if i.mnemonic == 'push':
                    rsp -= 8
                    stack[rsp] = registers[i.op_str]
                elif i.mnemonic == 'sub':
                    rsp -= int(i.op_str.split(', ')[1], 0)
            active = [op for op in operations if op[0] <= (pc if pc < size else 255)]
            for _, kind, value in active:
                if kind == 'push':
                    registers[value] = 0xdeadbeef
            for _, kind, value in active:
                if kind == 'alloc':
                    rsp += value
                else:
                    registers[value] = stack[rsp]
                    rsp += 8
            assert rsp == initial_rsp
            assert stack[rsp] == 0xfeedface
            assert all(registers[r] == original[r] for r in REGS if r != 'rsp')


def test_canonical_epilogues_restore_from_every_instruction_boundary():
    """Model actual stack state at each epilogue PC, then execute its suffix.

    Windows recognizes canonical epilogues from machine instructions instead of
    applying the full-body unwind codes to a partially restored frame.
    """
    raw, _, _, _ = build(fixture())
    pe = pefile.PE(data=raw)
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    nonvolatile = {'rbx', 'rbp', 'rsi', 'rdi', 'r12', 'r13', 'r14', 'r15'}
    for begin, end, unwind in records(pe)[1:]:
        size = pe.get_data(unwind, 4)[1]
        instructions = list(md.disasm(pe.get_data(begin, end - begin), BASE + begin))
        original = {r: 0xabcdef0000 + n * 17 for n, r in enumerate(REGS)}
        initial_rsp, continuation = 0x100008, 0xfeedface
        frame_rsp, frame_stack = initial_rsp, {initial_rsp: continuation}
        saved = set()
        for i in instructions:
            if i.address >= BASE + begin + size:
                break
            if i.mnemonic == 'push':
                frame_rsp -= 8
                frame_stack[frame_rsp] = original[i.op_str]
                saved.add(i.op_str)
            elif i.mnemonic == 'sub':
                frame_rsp -= int(i.op_str.split(', ')[1], 0)

        epilogue_addresses = set()
        for last, i in enumerate(instructions):
            if i.mnemonic != 'ret':
                continue
            first = last
            while first and instructions[first - 1].mnemonic == 'pop':
                first -= 1
            if first and instructions[first - 1].mnemonic == 'add' and \
                    instructions[first - 1].op_str.startswith('rsp, '):
                first -= 1
            epilogue = instructions[first:last + 1]
            epilogue_addresses.update(i.address for i in epilogue)

            def step(i, rsp, registers):
                if i.mnemonic == 'add':
                    return rsp + int(i.op_str.split(', ')[1], 0)
                if i.mnemonic == 'pop':
                    registers[i.op_str] = frame_stack[rsp]
                    return rsp + 8
                assert i.mnemonic == 'ret'
                assert frame_stack[rsp] == continuation
                return rsp + 8

            # Arrive at each PC by executing its prefix from the full body state.
            # Independently execute the remaining recognized epilogue afterward.
            for stop in range(len(epilogue)):
                registers = dict(original)
                for reg in saved & nonvolatile:
                    registers[reg] = 0xdeadbeef
                rsp = frame_rsp
                for instruction in epilogue[:stop]:
                    rsp = step(instruction, rsp, registers)
                for instruction in epilogue[stop:]:
                    rsp = step(instruction, rsp, registers)
                assert rsp == initial_rsp + 8
                assert all(registers[r] == original[r] for r in nonvolatile)
        assert epilogue_addresses
        assert all(i.address in epilogue_addresses for i in instructions
                   if i.mnemonic in ('pop', 'ret') or
                   (i.mnemonic == 'add' and i.op_str.startswith('rsp, ')))


def test_empty_exception_directory_is_created_and_malformed_directory_rejected():
    import pytest
    empty = bytearray(fixture())
    struct.pack_into('<II', empty, 0x98 + 112 + 3 * 8, 0, 0)
    raw, _, _, labels = build(bytes(empty))
    assert len(records(pefile.PE(data=raw))) >= len(labels)
    malformed = bytearray(fixture())
    struct.pack_into('<I', malformed, 0x98 + 112 + 3 * 8 + 4, 13)
    with pytest.raises(ValueError, match='exception directory size'):
        build(bytes(malformed))


def test_nonfixed_or_incorrect_epilogues_are_rejected():
    import pytest
    base = BASE + 0x10000
    for source in ('push rbx; sub rsp, 0x20; add rsp, 0x18; pop rbx; ret',
                   'push rbx; sub rsp, 0x20; add rsp, 0x20; pop rsi; ret',
                   'sub rsp, 0x28; sub rsp, 8; call 0x140001000; add rsp, 0x30; ret'):
        code = b'\0' * 16 + exepatch._asm(source, base + 16)
        with pytest.raises(ValueError):
            exepatch._d5ev_functions(code, base, [])
