"""Unicorn engine for the learned-evility capacity extension (.d5lc).

Modelled on `abi_engine_ex05c.py` (same checks: CALL alignment, 32-byte home space clear of live saves,
exact continuation, nonvolatile preservation, an owned-instruction rule), specialised for the two wrappers
this extension installs.  The original getter/setter are `ret` stubs whose answer the case controls, so
what a case proves is *our* contribution and the call/ABI contract -- not the game's own arithmetic.

Fixture layout per case (all synthetic):
    0x400000000 unit record A (0x4800 bytes: serial at +0x3060, bitmap bytes at +0x2E70)
    0x400010000 unit record B (the "another unit" case)
    0x400020000 the live Skill key array (u32 ids, ascending) -- the guard and the search read this
    0x400030000 the u16 max index word
    section   the real assembled .d5lc section, writable, with lc_pkey/lc_pmax pointing at the fixtures
"""
import struct

PAGE = 0x1000
STACK, STACK_SIZE = 0x100000000, 0x100000
SP = STACK + STACK_SIZE - 0x1000
UNIT, OTHER = 0x400000000, 0x400010000
KEYS, MAXI = 0x400020000, 0x400030000
GLOBALS = 0x400040000          # fixture stand-in for the game's key-array pointer variable (0x140A04E48):
                               # a qword holding the array address.  The u16 max index (0x140A04E38) is a
                               # value, not a pointer, so the extension stores its address directly.
MASK = (1 << 64) - 1


def unit(serial, learned=(), bitmap=None):
    """a unit record fixture: `serial` at +0x3060, learned bits set for the given row positions"""
    b = bytearray(0x4800)
    struct.pack_into('<Q', b, 0x3060, serial)
    for pos in learned:
        b[0x2E70 + (pos >> 3)] |= 1 << (pos & 7)
    if bitmap is not None:
        b[0x2E70:0x2E70 + len(bitmap)] = bitmap
    return b


def table(ids):
    """the live key array and its max index"""
    out = b"".join(struct.pack('<I', i) for i in ids)
    return out, len(ids) - 1


def run(patched, info, sym, kind, site, *, ident, on=False, abi=True, unit_a=None, unit_b=None,
        keys=None, maxi=None, native_answer=0, state=None, preset=None):
    """execute one call through the real patched site.

    kind: 'get' (rcx = unit, edx = id) or 'set' (rcx = unit, edx = id, r8b = on).
    native_answer: what the stubbed original returns in rax (0/1 for get, 0/-1 for set).
    keys/maxi: the live table fixture; `state` presets lc_state (None = leave as built, i.e. 0).
    """
    import capstone
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import x86_const as X
    pe = pefile.PE(data=patched, fast_load=True)
    image_base = pe.OPTIONAL_HEADER.ImageBase
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    mapped = set()

    def map_bytes(address, data):
        for page in range(address & -PAGE, (address + len(data) + PAGE - 1) & -PAGE, PAGE):
            if page not in mapped:
                uc.mem_map(page, PAGE)
                mapped.add(page)
        uc.mem_write(address, bytes(data))

    def read_mem(address, n):
        return bytes(uc.mem_read(address, n))

    def u32at(address):
        return struct.unpack('<I', read_mem(address, 4))[0]

    map_bytes(info['base'], info['data'])
    map_bytes(STACK, bytes(STACK_SIZE))
    map_bytes(UNIT, unit_a if unit_a is not None else unit(1))
    map_bytes(OTHER, unit_b if unit_b is not None else unit(2))
    key_ids = list(keys if keys is not None else [])
    key_bytes, key_max = table(key_ids)
    map_bytes(KEYS, key_bytes + bytes(16))
    map_bytes(MAXI, struct.pack('<H', maxi if maxi is not None else key_max) + bytes(16))
    # point the extension's guard/search at the fixtures instead of the game's live globals
    map_bytes(GLOBALS, struct.pack('<Q', KEYS) + bytes(16))
    uc.mem_write(sym['pkey'], struct.pack('<Q', GLOBALS))     # the game's 0x140A04E48 is a pointer variable
    uc.mem_write(sym['pmax'], struct.pack('<Q', MAXI))        # ... while 0x140A04E38 is the u16 itself
    if state is not None:
        uc.mem_write(sym['state'], struct.pack('<I', state))
    if preset:
        for address, data in preset.items():
            uc.mem_write(address, data)
    off = pe.get_offset_from_rva(site - image_base)
    site_bytes = patched[off:off + 5]
    assert site_bytes[0] == 0xE8, f'redirection must be E8 CALL, got {site_bytes.hex()}'
    wrapper = site + 5 + struct.unpack('<i', site_bytes[1:])[0]
    assert info['code'] <= wrapper < info['base'] + len(info['data'])
    map_bytes(site, site_bytes + b'\xcc')
    original = 0x14015E630 if kind == 'get' else 0x14015E6D0
    map_bytes(original, b'\xc3')
    regs = lambda name: getattr(X, 'UC_X86_REG_' + name.upper())
    read = lambda name: uc.reg_read(regs(name))
    write = lambda name, value: uc.reg_write(regs(name), value & MASK)
    nonvol = {n: 0x13579BDF00000000 + i for i, n in enumerate(
        ('rbx', 'rbp', 'rdi', 'rsi', 'r12', 'r13', 'r14', 'r15'))}
    for n, v in nonvol.items():
        write(n, v)
    for i in range(6, 16):
        uc.reg_write(regs('xmm' + str(i)), 0x123456789ABCDEF00112233400000000 + i)
    uc.reg_write(regs('mxcsr'), 0x1F80)
    uc.reg_write(regs('eflags'), 2)
    args = (UNIT, ident, 1 if on else 0, 0)
    for n, v in zip(('rcx', 'rdx', 'r8', 'r9'), args):
        write(n, v)
    uc.mem_write(SP + 0x20, struct.pack('<4Q', 0, 0, 0, 0))
    write('rsp', SP if abi else SP - 8)
    if not abi:
        uc.mem_write(SP - 8, struct.pack('<Q', site + 5))
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    frames, saves, poison = [], set(), {}
    calls, errors = [], []
    reached = [False]
    instructions = [0]
    pending = [None]

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def on_code(uc, address, size, _):
        try:
            instructions[0] += 1
            rsp = read('rsp')
            if pending[0] is not None:
                expected = pending[0]
                check(rsp == expected and rsp % 16 == 8, f'callee entry alignment at {address:#x}')
                pending[0] = None
            if address == site + 5:
                check(rsp == SP, f'continuation RSP delta {rsp - SP}')
                check(not frames and not saves, 'live frames/saves at continuation')
                reached[0] = True
                uc.emu_stop()
                return
            if address == original:
                calls.append(hex(address))
                got = tuple(read(n) for n in ('rcx', 'rdx', 'r8'))
                if kind == 'set':
                    check(got == args[:3], f'original argument registers changed: {got!r} != {args[:3]!r}')
                else:
                    check(got[:2] == args[:2], f'original argument registers changed: {got!r}')
                for i, n in enumerate(('rcx', 'rdx', 'r8', 'r9', 'r10', 'r11')):
                    write(n, 0xBAD0000000000000 + i)
                write('rax', native_answer & MASK)
            check(address in (original,) or address == site or
                  info['code'] <= address < info['base'] + len(info['data']),
                  f'unowned instruction {address:#x}')
            ins = next(cs.disasm(bytes(uc.mem_read(address, size)), address))
            if ins.mnemonic == 'push':
                saves.add(rsp - 8)
            elif ins.mnemonic == 'pop':
                saves.discard(rsp)
            elif ins.mnemonic == 'call':
                check(rsp % 16 == 0, f'CALL alignment at {address:#x}')
                check(STACK <= rsp and rsp + 32 <= STACK + STACK_SIZE, 'unwritable home space')
                protected = saves | {f[1] for f in frames}
                check(not any(rsp < p + 8 and p < rsp + 32 for p in protected),
                      f'home space overlaps live save/return at {address:#x}')
                for i in range(4):
                    uc.mem_write(rsp + i * 8, struct.pack('<Q', 0xAABBCCDD00000000 + i))
                for p in range(rsp, rsp + 32):
                    poison[p] = len(frames)
                frames.append((address + size, rsp - 8))
                pending[0] = rsp - 8
                calls.append(hex(address))
            elif ins.mnemonic == 'ret':
                check(bool(frames), 'RET without a CALL frame')
                continuation, return_slot = frames.pop()
                check(rsp == return_slot, f'RET RSP changed at {address:#x}')
                actual = struct.unpack('<Q', bytes(uc.mem_read(rsp, 8)))[0]
                check(actual == continuation, f'wrong continuation at {address:#x}')
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
            uc.emu_stop()

    def on_write(uc, access, address, size, value, _):
        for p in range(address, address + size):
            poison.pop(p, None)

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    if not abi:
        frames.append((site + 5, SP - 8))
    uc.emu_start(site if abi else wrapper, site + 6, timeout=8000000, count=500000)
    assert not errors, errors
    assert reached[0], 'did not reach the exact site+5 continuation'
    assert all(read(n) == v for n, v in nonvol.items()), 'integer nonvolatile clobber'
    assert all(uc.reg_read(regs('xmm' + str(i))) == 0x123456789ABCDEF00112233400000000 + i
               for i in range(6, 16)), 'XMM6-15 clobber'
    def store_live():
        raw = read_mem(sym['store'], sym['store_size'])
        out = []
        for i in range(0, len(raw), 16):
            serial, ident_, st = struct.unpack('<QII', raw[i:i + 16])
            if st:
                out.append([serial, ident_, st])
        return out

    rax = read('rax')
    return dict(output=rax & 0xFFFFFFFF, low_byte=rax & 0xFF,
                state=u32at(sym['state']), used=u32at(sym['used']),
                store=store_live(),
                bitmapsamples=[bytes(read_mem(UNIT + 0x2E70, 8)).hex(),
                               bytes(read_mem(OTHER + 0x2E70, 8)).hex()],
                instructions=instructions[0], continuation=hex(site + 5),
                call_edges=sorted(set(calls)), rsp_delta=read('rsp') - SP)
