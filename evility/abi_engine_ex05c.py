"""EX-05c synthetic behavior/site-entry engine.

Adapted from the reviewed, read-only Subprojects/Engine-Extensions/evility/abi_site_proof.py.
Unicorn is imported only by execute(): importing/building proof cases is safe in a sandbox.
Original game callees are deterministic volatile-clobbering stubs. All extension
instructions, real patched CALL sites (ABI mode), and return continuations execute.
"""
import struct

PAGE = 0x1000
STACK, STACK_SIZE = 0x100000000, 0x100000
SP = STACK + STACK_SIZE - 0x1000
UNIT, OTHER, REC, OREC = 0x400000000, 0x400010000, 0x400020000, 0x400030000
OUT, AGG, ACTION = 0x400040008, 0x400050000, 0x400060000
MASK = (1 << 64) - 1
ARGS = (0x15151515, 0x26262626, 0x37373737)
# EX-05e: a stubbed callee the extension calls directly (not a redirected call site).
STUBS = (0x140151C50,)   # unit_set_hp_shadow, called by the regen family after an HP write

def execute(patched, info, specs, family, target, site, ids=(), out_value=50, original_rax=0, null=False, vanilla=False, *, abi=True, fixture=None, supplied_stack_args=None, original_effect=None, watch=None, preset=None, stub_returns=None, unit_args=None, call_args=None, clamp_out=None):
    """`stub_returns` (D4 batch 3): {address: rax} for a game function the extension calls itself and whose
    return value the case must control — game_rng_draw (0x140136660) for the %-chance conditions.  The
    address is mapped to `ret` like STUBS and the hook writes the caller-visible rax before it runs.

    D4SIG5: `clamp_out` = (lo, hi) makes the stubbed original clamp the in/out qword at OUT, as the real
    damage_hit_chance_rules does as its first act.

    OLEFFECTS: `unit_args` sets registers a family reads *without* them being call arguments — the steal
    site keeps the killer's unit record in rbx and the accumulated chance in esi.  For a `steal` case the
    nonvolatile rsi assertion is skipped on purpose: writing esi is that family's whole external effect."""
    stub_returns = stub_returns or {}
    import capstone
    import pefile
    from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE,
                         UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE)
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

    map_bytes(info['base'], info['data'])
    map_bytes(STACK, bytes(STACK_SIZE))
    unit = bytearray(0x4800)
    struct.pack_into('<i', unit, 0x3030, len(ids))
    for i, evid in enumerate(sorted(ids)):
        struct.pack_into('<I', unit, 0x2F30 + i * 4, evid)
    struct.pack_into('<8H', unit, 0x3068, *([50] * 8))
    map_bytes(UNIT, unit)
    map_bytes(OTHER, unit)
    for address, unit_ptr in ((REC, UNIT), (OREC, OTHER)):
        rec = bytearray(PAGE)
        struct.pack_into('<Q', rec, 0x240, unit_ptr)
        map_bytes(address, rec)
    map_bytes(OUT - 8, struct.pack('<QiII', 0xA1B2C3D4, out_value, 0xDEADBEEF, 0x89ABCDEF)
              if family in ('status_chance', 'crit_rate') else struct.pack('<QqQ', 0xA1B2C3D4, out_value, 0xDEADBEEF))
    map_bytes(AGG, bytes(PAGE))
    map_bytes(ACTION, bytes(PAGE))
    if preset:
        for address, data in preset.items():
            map_bytes(address, data)
    map_bytes(0x140A18780, struct.pack('<qq', 10, 300))
    # evil_brec's only modelled global: no units on the map.
    map_bytes(0x141BA33B0, bytes(256 * 4704))
    if fixture:
        fixture(map_bytes)
    off = pe.get_offset_from_rva(site - image_base)
    site_bytes = patched[off:off + 5]
    assert site_bytes[0] == 0xE8, f'redirection must be E8 CALL, got {site_bytes.hex()}'
    wrapper = site + 5 + struct.unpack('<i', site_bytes[1:])[0]
    assert info['code'] <= wrapper < info['base'] + len(info['data'])
    if vanilla:
        site_bytes = b'\xe8' + struct.pack('<i', target - site - 5)
    map_bytes(site, site_bytes + b'\xcc')
    targets = {t for _, t, _ in specs}
    for t in targets | set(STUBS) | set(stub_returns):
        map_bytes(t, b'\xc3')
    regs = lambda name: getattr(X, 'UC_X86_REG_' + name.upper())
    read = lambda name: uc.reg_read(regs(name))
    write = lambda name, value: uc.reg_write(regs(name), value & MASK)
    nonvol = {n: 0x13579BDF00000000 + i for i, n in enumerate(
        ('rbx', 'rbp', 'rdi', 'rsi', 'r12', 'r13', 'r14', 'r15'))}
    xmm = {i: 0x123456789ABCDEF00112233400000000 + i for i in range(6, 16)}
    for n, v in nonvol.items():
        write(n, v)
    for i, v in xmm.items():
        uc.reg_write(regs('xmm' + str(i)), v)
    uc.reg_write(regs('mxcsr'), 0x1F80)
    uc.reg_write(regs('eflags'), 2)
    first = 0 if null else REC
    args = {'conversion': (UNIT, ARGS[1], 0, 0), 'potency': (UNIT, 0, 0, 0), 'stats': (UNIT, AGG, 0, 0),
            'growth': (UNIT, 2, 0, 0), 'dealt': (first, OREC, ACTION, ACTION),
            'taken': (OUT, REC, OREC, ACTION), 'flight': (REC, 0, 0, 0),
            'hit': (OUT, REC, OREC, ACTION), 'status_chance': (OUT, REC, OREC, ACTION),
            'crit_rate': (OUT, REC, OREC, ARGS[0]), 'regen': (REC, 0, 0, 0),
            'achance': (ACTION, REC, OREC, 0),
            # the two EX-06b predicate families: the *defender* (REC, which carries the evility in the
            # fixture) is the subject; the attacker's record (OREC) is the other side
            'nullify': (OREC, REC, 0, ACTION), 'counter': (OREC, REC, 0, 0),
            # P3 additive passes.  rcx is a battle record whose +0x240 is the subject unit record for
            # every one of them except defense_power, whose rdx argument already *is* the unit record.
            'power': (REC, OREC, 0, ACTION), 'defense_power': (OREC, UNIT, 0, 0),
            'move': (REC, 0, 0, 0), 'range': (REC, OREC, 0, 0),
            # OLEFFECTS: revenge takes (unit, battle record); the steal site's own argument is the victim
            # actor; sp_drain gets the actor whose SP is settled; overload gets the unit record.
            'revenge': (UNIT, OREC, 0, 0), 'steal': (OREC, 0, 0, 0),
            'sp_drain': (REC, 0, 0, 0), 'overload': (UNIT, 0, 0, 0),
            'resistance': (UNIT, REC, AGG, ARGS[0]),
            # D4SIG4: unit_stats_equip_stat(unit, slot, stat, tiers); `call_args` sets slot and stat
            'equip': (UNIT, 0, 0, 0)}[family]
    if call_args:
        args = call_args
    for n, v in zip(('rcx', 'rdx', 'r8', 'r9'), args):
        write(n, v)
    for n, v in (unit_args or {}).items():
        write(n, v)
        if n in nonvol:
            nonvol[n] = v          # a unit_args register IS the caller's value for this site
    if supplied_stack_args is not None:
        stack_args = supplied_stack_args
    elif family == 'taken':
        stack_args = (ACTION, ARGS[1], ARGS[2])
    elif family == 'crit_rate':
        stack_args = (ACTION, ARGS[1], 0)      # X, the target index
    else:
        stack_args = ARGS
    uc.mem_write(SP + 0x20, struct.pack('<3Q', *stack_args))
    write('rsp', SP if abi else SP - 8)
    if not abi:
        uc.mem_write(SP - 8, struct.pack('<Q', site + 5))
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    frames, saves, poison = [], set(), {}
    calls, writes, errors = [], [], []
    reached = [False]
    instructions = [0]
    pending = [None]
    watched = {}

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def on_code(uc, address, size, _):
        try:
            instructions[0] += 1
            rsp = read('rsp')
            if pending[0] is not None:
                expected, source = pending[0]
                check(rsp == expected and rsp % 16 == 8, f'callee entry alignment at {address:#x}')
                pending[0] = None
            if address == site + 5:
                check(rsp == SP, f'continuation RSP delta {rsp - SP}')
                check(not frames and not saves, 'live frames/saves at continuation')
                reached[0] = True
                uc.emu_stop()
                return
            if address in stub_returns:
                # write the caller-visible return value; the stub's own `ret` is still processed below so the
                # frame bookkeeping stays exact
                calls.append(hex(address))
                write('rax', stub_returns[address])
            if address in STUBS:
                calls.append(hex(address))   # the extension called it itself; the stub is a `ret`
                check(read('rcx') != 0, 'unit_set_hp_shadow called without a record')
            elif address in targets:
                if original_effect:
                    original_effect(map_bytes)
                if clamp_out:
                    # D4SIG5: the game's own damage_hit_chance_rules first clamps the in/out percent (pinned exe 0x1401F5410)
                    cur = struct.unpack('<q', bytes(uc.mem_read(OUT, 8)))[0]
                    uc.mem_write(OUT, struct.pack('<q', max(clamp_out[0], min(clamp_out[1], cur))))
                check(address == target, 'unexpected original-game call')
                # how many stack arguments the game's own function is given at this site
                count = {'taken': 3, 'achance': 3, 'nullify': 2, 'crit_rate': 2,
                         'dealt': 1, 'hit': 1, 'status_chance': 1, 'power': 1, 'resistance': 1}.get(family, 0)
                forwarded = tuple(struct.unpack('<Q', bytes(uc.mem_read(rsp + 0x28 + i * 8, 8)))[0]
                                  for i in range(count))
                if family in ('dealt', 'taken', 'hit', 'status_chance', 'crit_rate',
                              'achance', 'nullify', 'counter', 'power', 'resistance'):
                    check(forwarded == stack_args[:len(forwarded)], f'stack arguments {forwarded!r}')
                if watch:
                    watched['at_original'] = struct.unpack('<Q', bytes(uc.mem_read(watch, 8)))[0]
                got_args = tuple(read(n) for n in ('rcx', 'rdx', 'r8', 'r9'))
                if family == 'steal':
                    # this site's argument is the victim actor in rcx; the victim-eligibility callee reads
                    # nothing else, and rdx/r8/r9 are whatever the enclosing defeat path happened to hold
                    got_args = got_args[:1]
                check(got_args == args[:len(got_args)], 'original argument registers changed')
                # Legal original-game clobbers make missing argument saves visible.
                for i, n in enumerate(('rcx', 'rdx', 'r8', 'r9', 'r10', 'r11')):
                    write(n, 0xBAD0000000000000 + i)
                for i in range(6):
                    uc.reg_write(regs('xmm' + str(i)), 0xBAD00000000000000000000000000000 + i)
                write('rax', original_rax if family in ('dealt', 'regen', 'overload', 'revenge', 'sp_drain', 'equip', 'flight')
                      else 17 if family == 'growth' else 0)
            check(address in targets or address in STUBS or address in stub_returns or address == site or
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
                # Poisoning from a real callee is allowed by Windows x64. A caller
                # reading these bytes again without writing them has kept a live
                # local in outgoing home space; the memory-read hook rejects it.
                depth = len(frames)
                for i in range(4):
                    uc.mem_write(rsp + i * 8, struct.pack('<Q', 0xAABBCCDD00000000 + i))
                for p in range(rsp, rsp + 32):
                    poison[p] = depth
                frames.append((address + size, rsp - 8))
                pending[0] = (rsp - 8, address)
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

    def on_read(uc, access, address, size, value, _):
        if family in ('status_chance', 'crit_rate') and address < OUT + 4 and OUT < address + size:
            if not (OUT <= address and address + size <= OUT + 4):
                errors.append(f'ailment read outside dword {address:#x}+{size}')
                uc.emu_stop()
        if any(p in poison and len(frames) <= poison[p] for p in range(address, address + size)):
            errors.append(f'live stack local/home overlap read at {address:#x}, PC {read("rip"):#x}')
            uc.emu_stop()

    def on_write(uc, access, address, size, value, _):
        for p in range(address, address + size):
            poison.pop(p, None)
        if OUT - 8 <= address < OUT + 16:
            writes.append((address, size))
            width = 4 if family in ('status_chance', 'crit_rate') else 8
            if not (OUT <= address and address + size <= OUT + width):
                errors.append(f'in/out write out of bounds {address:#x}+{size}')
                uc.emu_stop()

    if watch:
        watched['before'] = struct.unpack('<Q', bytes(uc.mem_read(watch, 8)))[0]
    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_READ, on_read)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    if not abi:
        frames.append((site + 5, SP - 8))
    uc.emu_start(site if abi else wrapper, site + 6, timeout=8000000, count=500000)
    assert not errors, errors
    assert reached[0], 'did not reach exact site+5 continuation (timeout/instruction limit)'
    untouched = {n: v for n, v in nonvol.items() if not (family == 'steal' and n == 'rsi')}
    assert all(read(n) == v for n, v in untouched.items()), 'integer nonvolatile clobber'
    assert all(uc.reg_read(regs('xmm' + str(i))) == v for i, v in xmm.items()), 'XMM6-15 clobber'
    assert read('mxcsr') & 0xFFC0 == 0x1F80 and not read('eflags') & 0x400, 'ABI control state changed'
    if family in ('status_chance', 'crit_rate'):
        assert bytes(uc.mem_read(OUT - 8, 8)) == struct.pack('<Q', 0xA1B2C3D4)
        assert bytes(uc.mem_read(OUT + 4, 8)) == struct.pack('<II', 0xDEADBEEF, 0x89ABCDEF)
        value = struct.unpack('<i', bytes(uc.mem_read(OUT, 4)))[0]
    elif family in ('taken', 'hit'):
        value = struct.unpack('<q', bytes(uc.mem_read(OUT, 8)))[0]
    elif family == 'potency':
        value = struct.unpack('<H', bytes(uc.mem_read(UNIT + 0x306C, 2)))[0]
    elif family == 'stats':
        value = struct.unpack('<i', bytes(uc.mem_read(AGG + 8, 4)))[0]
    elif family == 'dealt':
        value = struct.unpack('<q', struct.pack('<Q', read('rax')))[0]
    elif family == 'achance':
        value = read('rax') & 0xFFFFFFFF
    elif family == 'steal':
        # OLEFFECTS: the family's effect *is* the caller's esi (the accumulated steal chance)
        value = read('rsi') & 0xFFFFFFFF
    else:
        value = read('rax') & (0xFF if family in ('flight', 'nullify', 'counter') else 0xFFFFFFFF)
    watch_after = struct.unpack('<Q', bytes(uc.mem_read(watch, 8)))[0] if watch else None
    return dict(output=value, instructions=instructions[0],
                hp=struct.unpack('<q', bytes(uc.mem_read(UNIT + 0x2cc8, 8)))[0],
                sp=struct.unpack('<q', bytes(uc.mem_read(UNIT + 0x2cd0, 8)))[0],
                potency=list(struct.unpack('<8H', bytes(uc.mem_read(UNIT + 0x3068, 16)))),
                aggregate=list(struct.unpack('<18i', bytes(uc.mem_read(AGG, 72)))),
                base_stats=list(struct.unpack('<8q', bytes(uc.mem_read(UNIT + 0x2d18, 64)))),
                final_stats=list(struct.unpack('<8q', bytes(uc.mem_read(UNIT + 0x2cd8, 64)))),
                continuation=hex(site + 5), rsp_delta=read('rsp') - SP,
                watched=dict(before=watched.get('before'), at_original=watched.get('at_original'),
                             after=watch_after),
                call_edges=sorted(set(calls)), calls_checked=len(calls),
                inout_writes=[dict(address=hex(a), size=s) for a, s in writes],
                integer_nonvolatiles_preserved=True, xmm6_15_preserved=True,
                home_writer=True)
