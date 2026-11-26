"""EVCAP3/EVCAP4 offline proof: the save/load relays and the runtime's store entry points (.d5lc v3).

Two kinds of case, both Unicorn, both normal and ``--abi``:

  * relay cases enter the *game's own patched CALL* -- 0x140754C5C and 0x140744FE2 (the two writes of a slot
    file, through data_save_io_make_header 0x1407436D0) and 0x14074D846 (savefile_decode_slot 0x140743130)
    -- with the argument registers the game
    uses, and require the exact ``site+5`` continuation.  ``--abi`` enters the CALL instruction itself, so the
    relay's prologue/epilogue and its inner call are exercised as the game makes them.  The game function is
    a ``ret`` stub whose answer each case sets: what is proven is *our* contribution (the slot and sequence
    number the save relay publishes, the slot and decode result the load relay records, the return value each
    hands back) and the call/ABI contract.  The save relay runs at *both* writer call sites.
  * routine cases call ``lc_put`` / ``lc_clear`` at their section entries (the runtime's own CALL sites, which
    no game instruction reaches), with the same alignment and nonvolatile rules.

    D5_KIT=<worktree> PYTHONPATH=<worktree>/tests <venv>/python evility/offline_proof_evcap3.py [--abi] [--json F]
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

ORIGINAL = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
                'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
ORIGINAL_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
BASE_IDS = list(range(1, 1001))
EXT_IDS = [21000, 21001]
TABLE = BASE_IDS + EXT_IDS

PAGE = 0x1000
STACK, STACK_SIZE = 0x100000000, 0x100000
SP = STACK + STACK_SIZE - 0x1000
ARG0, ARG1 = 0x400060000, 0x400060800   # the caller's rcx/rdx: opaque to the relay, never dereferenced
KEYS, MAXI = 0x400020000, 0x400030000
SENTINEL = 0x400070000
STOP_ABOVE = 0x7FFFFFFFF000          # the hooks stop the run; this only bounds it


def emu(patched, info, *, site=None, entry=None, regs, stubs, keys, maxi_, abi=True, budget=400000,
        preset=None):
    """run one case; `stubs` = {address: return value} for the game functions a relay calls.

    Returns {rax, instructions, calls, section bytes, merged field accessors}.
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

    map_bytes(STACK, bytes(STACK_SIZE))
    map_bytes(info['base'], info['data'])
    map_bytes(KEYS, b''.join(struct.pack('<I', i) for i in keys) + bytes(16))
    map_bytes(MAXI, struct.pack('<H', maxi_) + bytes(16))
    map_bytes(SENTINEL, struct.pack('<Q', 0xDEADBEEF) + bytes(64))
    for address, value in stubs.items():
        map_bytes(address, b'\xc3')
    for address, data in (preset or {}).items():
        map_bytes(address, data)
    reg = lambda n: getattr(X, 'UC_X86_REG_' + n.upper())
    read = lambda n: uc.reg_read(reg(n))
    write = lambda n, v: uc.reg_write(reg(n), v & ((1 << 64) - 1))
    nonvol = {n: 0x13579BDF00000000 + i for i, n in enumerate(
        ('rbx', 'rbp', 'rdi', 'rsi', 'r12', 'r13', 'r14', 'r15'))}
    for n, v in nonvol.items():
        write(n, v)
    uc.reg_write(reg('mxcsr'), 0x1F80)
    uc.reg_write(reg('eflags'), 2)
    for n, v in regs.items():
        write(n, v)
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    frames, saves, poison, calls, errors = [], set(), {}, [], []

    if entry is not None:
        uc.mem_write(SP - 8, struct.pack('<Q', SENTINEL))
        write('rsp', SP - 8)
        start = entry
        frames.append((SENTINEL, SP - 8))
    else:
        off = pe.get_offset_from_rva(site - image_base)
        site_bytes = patched[off:off + 5]
        assert site_bytes[0] == 0xE8, f'redirection must be E8 CALL, got {site_bytes.hex()}'
        wrapper = site + 5 + struct.unpack('<i', site_bytes[1:])[0]
        assert info['code'] <= wrapper < info['base'] + len(info['data'])
        map_bytes(site, site_bytes + b'\xcc')
        start = site if abi else wrapper
        if abi:
            uc.mem_write(SP + 0x20, struct.pack('<4Q', 0, 0, 0, 0))
            write('rsp', SP)
        else:
            write('rsp', SP - 8)
            uc.mem_write(SP - 8, struct.pack('<Q', site + 5))
            frames.append((site + 5, SP - 8))

    pending = [None]
    reached = [False]
    n = [0]

    def on_code(uc, address, size, _):
        try:
            n[0] += 1
            rsp = read('rsp')
            if pending[0] is not None:
                expected = pending[0]
                assert rsp == expected and rsp % 16 == 8, f'callee entry alignment at {address:#x}'
                pending[0] = None
            if entry is None and address == site + 5:
                assert rsp == SP, f'continuation RSP delta {rsp - SP}'
                assert not frames and not saves, 'live frames/saves at continuation'
                reached[0] = True
                uc.emu_stop()
                return
            if entry is not None and address == SENTINEL:
                assert rsp == SP, f'return RSP delta {rsp - SP}'
                reached[0] = True
                uc.emu_stop()
                return
            if address in stubs:
                calls.append(hex(address))
                before = tuple(read(x) for x in ('rcx', 'rdx', 'r8'))
                calls[-1] = (hex(address), before)
                write('rax', stubs[address] & ((1 << 64) - 1))
            assert address in stubs or (entry is not None and address == entry) or \
                (entry is None and address == site) or \
                info['code'] <= address < info['base'] + len(info['data']), f'unowned instruction {address:#x}'
            ins = next(cs.disasm(bytes(uc.mem_read(address, size)), address))
            if ins.mnemonic == 'push':
                saves.add(rsp - 8)
            elif ins.mnemonic == 'pop':
                saves.discard(rsp)
            elif ins.mnemonic == 'call':
                assert rsp % 16 == 0, f'CALL alignment at {address:#x}'
                assert STACK <= rsp and rsp + 32 <= STACK + STACK_SIZE, 'unwritable home space'
                protected = saves | {f[1] for f in frames}
                assert not any(rsp < p + 8 and p < rsp + 32 for p in protected), \
                    f'home space overlaps live save/return at {address:#x}'
                for i in range(4):
                    uc.mem_write(rsp + i * 8, struct.pack('<Q', 0xAABBCCDD00000000 + i))
                for p in range(rsp, rsp + 32):
                    poison[p] = 1
                frames.append((address + size, rsp - 8))
                pending[0] = rsp - 8
            elif ins.mnemonic == 'ret':
                assert frames, 'RET without a CALL frame'
                continuation, return_slot = frames.pop()
                assert rsp == return_slot, f'RET RSP changed at {address:#x}'
                actual = struct.unpack('<Q', bytes(uc.mem_read(rsp, 8)))[0]
                assert actual == continuation, f'wrong continuation at {address:#x}'
            if address in stubs:
                # the stub is `ret`: hand the emulator the caller's continuation as usual
                pass
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc} at {address:#x}')
            uc.emu_stop()

    def on_write(uc, access, address, size, value, _):
        poison.pop(address, None)

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    uc.emu_start(start, STOP_ABOVE, timeout=20000000, count=budget)
    assert not errors, errors
    assert reached[0], 'did not reach the expected end'
    assert all(read(x) == v for x, v in nonvol.items()), 'integer nonvolatile clobber'
    return dict(rax=read('rax'), instructions=n[0], calls=calls,
                data=bytes(uc.mem_read(info['base'], len(info['data']))),
                read=lambda address, size: bytes(uc.mem_read(address, size)))


def section_state(result, sym, info):
    """the section's own fields, read out of the memory the case left behind"""
    base = info['base']

    def u32(name):
        return struct.unpack_from('<I', result['data'], sym[name] - base)[0]

    return dict(state=u32('state'), used=u32('used'), cap=u32('cap'),
                sv_slot=u32('sv_slot'), sv_seq=u32('sv_seq'), ev_load=u32('ev_load'),
                ev_slot=u32('ev_slot'), ev_ok=u32('ev_ok'))


def save_cases():
    """save cases run at *both* call sites of the game's slot writer (0x140754C5C manual, 0x140744FE2 auto)"""
    return [
        dict(name='save-publishes-the-slot-the-writer-was-given', kind='save', result=0, slot=7,
             expect_seq=1, expect_slot=7, expect_rax=0),
        dict(name='save-a-failed-write-publishes-nothing', kind='save', result=1, slot=7,
             expect_seq=0, expect_rax=1),
        dict(name='save-the-game-result-is-handed-back-untouched', kind='save', result=0x1234, slot=3,
             expect_seq=0, expect_rax=0x1234),
        dict(name='save-autosave-slot-zero', kind='save', result=0, slot=0,
             expect_seq=1, expect_slot=0, expect_rax=0),
        dict(name='save-a-slot-that-cannot-name-a-file-is-reported-not-bound', kind='save', result=0,
             slot=-1, expect_seq=1, expect_slot=0xFFFFFFFF, expect_rax=0),
        dict(name='load-records-the-slot-and-a-good-decode', kind='load', result=0, slot=7,
             expect_load=1, expect_slot=7, expect_ok=1, expect_rax=0),
        dict(name='load-records-a-failed-decode', kind='load', result=1, slot=3,
             expect_load=1, expect_slot=3, expect_ok=0, expect_rax=1),
        dict(name='load-autosave-slot-zero', kind='load', result=0, slot=0,
             expect_load=1, expect_slot=0, expect_ok=1, expect_rax=0),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', '--site-entry', action='store_true')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    from d5lib import learned
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, 'pinned exe changed'
    man = learned.manifest(TABLE)
    patched = learned.build_patch(original, man)
    info = learned.section_info(patched)
    sym = learned.data_symbols(info)
    code, labels = learned._assemble(learned.section_source(man),
                                     learned.code_base(original, learned.SECTION))

    results = []
    for case in save_cases():
        sites = learned.SAVE_SITES if case['kind'] == 'save' else learned.LOAD_SITES
        target = learned.MAKE_HEADER if case['kind'] == 'save' else learned.DECODE_SLOT
        for site in sites:
            # the game's own argument shape: the writer gets (rcx = per-slot header, rdx = save block,
            # r8d = slot); the decode gets (rcx = destination, edx = slot, r8 = nothing)
            slot64 = case['slot'] & 0xFFFFFFFFFFFFFFFF
            regs = (dict(rcx=ARG0, rdx=ARG1, r8=slot64) if case['kind'] == 'save'
                    else dict(rcx=ARG0, rdx=slot64, r8=0))
            want_args = (ARG0, ARG1, slot64) if case['kind'] == 'save' else (ARG0, slot64, 0)
            r = emu(patched, info, site=site, regs=regs, stubs={target: case['result']},
                    keys=TABLE, maxi_=len(TABLE) - 1, abi=args.abi)
            st = section_state(r, sym, info)
            name = case['name'] + ('' if len(sites) == 1 else f' @ {site:#x}')
            problems = []
            if (r['rax'] & 0xFFFFFFFF) != (case['expect_rax'] & 0xFFFFFFFF):
                problems.append(f"rax {r['rax']:#x} != {case['expect_rax']:#x}")
            if len(r['calls']) != 1:
                problems.append(f"the game function was called {len(r['calls'])} times")
            elif [x[1] for x in r['calls']] != [want_args]:
                problems.append(f"the game's function got {r['calls'][0][1]}")
            fields = (('sv_seq', 'expect_seq'), ('sv_slot', 'expect_slot')) if case['kind'] == 'save' \
                else (('ev_load', 'expect_load'), ('ev_slot', 'expect_slot'), ('ev_ok', 'expect_ok'))
            for field, key in fields:
                if case.get(key) is not None and st[field] != case[key]:
                    problems.append(f'{field} {st[field]} != {case[key]}')
            if case['kind'] == 'save' and case.get('expect_seq') == 0 and st['sv_slot'] != 0:
                problems.append('a failed write still set the slot')
            if case['kind'] == 'load' and st['sv_seq'] != 0:
                problems.append('a load touched the save event')
            if st['used'] != 0 or st['state'] != 0:
                problems.append('the relay touched the store or the guard')
            results.append(dict(name=name, kind=case['kind'], site=f'{site:#x}', ok=not problems,
                                problems=problems, state=st,
                                calls=[[c[0], [hex(x) for x in c[1]]] for c in r['calls']],
                                rax=hex(r['rax']), instructions=r['instructions']))
            for p in problems:
                print('FAIL', name, p)

    # ---- the runtime's own entry points: lc_put / lc_clear -------------------------------------------
    def routine(name, entry, regs, preset=None, check=None):
        r = emu(patched, info, entry=entry, regs=regs, stubs={}, keys=TABLE, maxi_=len(TABLE) - 1)
        return r

    def store_slots(r):
        raw = r['read'](sym['store'], sym['store_size'])
        out = []
        for i in range(0, len(raw), 16):
            serial, ident, state = struct.unpack('<QII', raw[i:i + 16])
            if state:
                out.append((serial, ident, state))
        return out

    def seeded(pairs):
        """a preset that puts `pairs` in the store at the shared hash slots, with the live count set"""
        out = {}
        for serial, ident in pairs:
            at = sym['store'] + learned.slot(serial, ident) * 16
            out[at] = struct.pack('<QII', serial, ident, 1) + bytes(4)
        out[sym['used']] = struct.pack('<I', len(pairs))
        return out

    def put_entry(serial, ident, preset=None):
        return emu(patched, info, entry=labels['lc_put'], regs=dict(rcx=serial, rdx=ident), stubs={},
                   keys=TABLE, maxi_=len(TABLE) - 1, preset=preset)

    def used_of(r):
        return struct.unpack_from('<I', r['data'], sym['used'] - info['base'])[0]

    routine_cases = []
    # lc_put: one insert lands in the slot the shared hash picks
    r = put_entry(7, 21000)
    raw = r['read'](sym['store'] + learned.slot(7, 21000) * 16, 16)
    ok = (r['rax'] & 0xFFFFFFFF) == 0 and struct.unpack('<QII', raw[:16]) == (7, 21000, 1) and used_of(r) == 1
    routine_cases.append(dict(name='put-inserts-at-the-shared-hash-slot', ok=ok, rax=hex(r['rax']),
                              slot=learned.slot(7, 21000)))
    # lc_put: the same pair again changes nothing
    r2 = put_entry(7, 21000, seeded([(7, 21000)]))
    ok = (r2['rax'] & 0xFFFFFFFF) == 0 and used_of(r2) == 1 and len(store_slots(r2)) == 1
    routine_cases.append(dict(name='put-again-is-idempotent', ok=ok, rax=hex(r2['rax'])))
    # lc_put: a second, different pair goes in beside the first
    r2b = put_entry(9, 21001, seeded([(7, 21000)]))
    ok = (r2b['rax'] & 0xFFFFFFFF) == 0 and used_of(r2b) == 2 and len(store_slots(r2b)) == 2
    routine_cases.append(dict(name='put-a-second-pair-goes-in-beside-the-first', ok=ok, rax=hex(r2b['rax'])))
    # lc_put at the ceiling: refused, and visibly so
    full = dict(seeded([]))
    full[sym['used']] = struct.pack('<I', learned.STORE_MAX_USED)
    r2c = put_entry(7, 21000, full)
    ok = (r2c['rax'] & 0xFFFFFFFF) == 0xFFFFFFFF and used_of(r2c) == learned.STORE_MAX_USED
    routine_cases.append(dict(name='put-refuses-at-the-ceiling', ok=ok, rax=hex(r2c['rax'])))
    # lc_clear: empties the whole table and the live count
    r3 = emu(patched, info, entry=labels['lc_clear'], regs=dict(rcx=0, rdx=0), stubs={},
             keys=TABLE, maxi_=len(TABLE) - 1, preset=seeded([(7, 21000), (9, 21001)]))
    live = store_slots(r3)
    ok = not live and used_of(r3) == 0
    routine_cases.append(dict(name='clear-empties-the-store', ok=ok, live=len(live)))
    for c in routine_cases:
        if not c['ok']:
            print('FAIL', c['name'])
    results.extend(dict(name=c['name'], kind='routine', ok=c['ok'], problems=[] if c['ok'] else ['failed'],
                        **{k: v for k, v in c.items() if k not in ('name', 'ok')}) for c in routine_cases)

    passed = all(r['ok'] for r in results)
    report = dict(mode='abi-site-entry' if args.abi else 'behavior', original_sha256=ORIGINAL_SHA,
                  section=dict(name=info['section'], size=info['size'], base=hex(info['base'])),
                  capacity=learned.STORE_CAPACITY, max_used=learned.STORE_MAX_USED, probe=learned.PROBE,
                  generation=man['generation'], checks=results, passed=passed,
                  limitations=[
                      'The game function each relay calls (data_save_io_make_header 0x1407436D0, '
                      'savefile_decode_slot 0x140743130) is a `ret` stub whose answer each case sets: what '
                      'is proven is the '
                      'relay\'s own work and the CALL/ABI contract, not the game\'s save or decode.  The '
                      'slot-to-path arithmetic and the "is this really a slot file" check run in '
                      'tests/test_evcap3.py and evcap3_save_roundtrip.py, on real save bytes.',
                      'No file is written by this proof; the companion itself is proven by '
                      'tests/test_evcap3.py (the same C code, host-built) and evcap3_save_roundtrip.py.',
                      'Windows unwind records are generated and statically audited, never exercised.'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f"{sum(1 for r in results if r['ok'])}/{len(results)} cases passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
