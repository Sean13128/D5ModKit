"""Site-entry ABI engine for the packed mastery mapper hook (.d5pm).

Same engine as mastery/abi_engine_mastery.py (itself modelled on evility/abi_engine_ex05c.py),
with the three things .d5pm needs:

  * internal calls -- the wrapper calls routines inside its own section (the JobRank
    threshold lookup and the encoder).  Those are still checked: RSP%16 == 8 at their
    entry, 32 bytes of clear home space for their own calls, return to the address
    their caller pushed, and no live frame at the end;
  * writable ranges -- the hook's job is to write the unit's spare area, so writes to
    the fixture record are expected and everything else must still be stack-only;
  * the caller's volatile registers are part of the contract: several game callers
    keep the class id in r8/rbx/ebp across the mapper call, so a clobber shows up as
    a wrong register at the continuation.

Checks (each aborts the run with a message naming the address):

  * callee-entry alignment after every call, and 32 bytes of home space with nothing
    live in it at that call;
  * every ret returns to the address pushed by its own call, frame balanced;
  * instructions execute only in the section, the patched site, a stub, or a declared
    continuation -- an unexpected call into the game would be caught here;
  * written memory is on the emulated stack or inside a declared writable range;
  * integer nonvolatiles, XMM6-15, mxcsr's control bits and the direction flag are
    unchanged, and so are the volatile registers the caller had live;
  * the stub receives the class id the caller passed (nothing is lost on the way in).

Unicorn is imported only by `execute()`.
"""
import struct

PAGE = 0x1000
STACK, STACK_SIZE = 0x100000000, 0x200000
SP = STACK + STACK_SIZE - 0x1000
MASK = (1 << 64) - 1
NONVOLATILE = ("rbx", "rbp", "rsi", "rdi", "r12", "r13", "r14", "r15")
VOLATILE = ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11")
# what a clobbering stub leaves in each volatile register
TRASH = {name: int(f"BAD{0x100 + i:X}00000000", 16) for i, name in enumerate(VOLATILE)}


def poison_nonvolatiles():
    return {name: 0x13579BDF00000000 + i for i, name in enumerate(NONVOLATILE)}


def poison_xmm():
    return {i: 0x123456789ABCDEF00112233400000000 + i for i in range(6, 16)}


def clobbering_stub(rax, trash=True, ret=True):
    """a deterministic stand-in for the original mapper: its answer in eax, every legal clobber"""
    from keystone import KS_ARCH_X86, KS_MODE_64, Ks
    lines = [f"mov eax, {rax}"]
    if trash:
        lines += [f"mov {name}, {TRASH[name]:#x}" for name in VOLATILE[1:]]
    if ret:
        lines.append("ret")
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_64).asm("\n".join(lines))
    return bytes(enc)


def execute(patched, info, site, *, kind="call", fixture=None, regs=None, stubs=(), stop=(),
            preserve=None, expect_args=None, answer=None, outputs=(), writable=(), probe=(), max_instructions=200000):
    """Execute one patched site.

    `internal` ranges are implied by the extension section itself.  `writable` is a list of
    (start, end) the hook is supposed to write (the unit record's spare area).
    """
    import capstone
    import pefile
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MODE_64, Uc
    from unicorn import x86_const as X

    pe = pefile.PE(data=patched, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    mapped = set()

    def map_bytes(address, data):
        end = (address + len(data) + PAGE - 1) & -PAGE
        for page in range(address & -PAGE, end + PAGE, PAGE):
            if page not in mapped:
                uc.mem_map(page, PAGE)
                mapped.add(page)
        uc.mem_write(address, bytes(data))

    map_bytes(info["base"], info["data"])
    map_bytes(STACK, bytes(STACK_SIZE))
    off = pe.get_offset_from_rva(site - base)
    map_bytes(site, patched[off:off + 5])
    for va, raw in stubs:
        map_bytes(va, raw)
    if fixture:
        fixture(map_bytes)

    raw = patched[off:off + 5]
    opcode = 0xE8 if kind == "call" else 0xE9
    assert raw[0] == opcode, f"site {site:#x} is {raw[0]:#04x}, not {opcode:#04x}"
    target = site + 5 + struct.unpack("<i", raw[1:])[0]
    assert info["code"] <= target < info["base"] + info["size"], hex(target)
    internal = (info["base"], info["base"] + len(info["data"]))

    regs_of = lambda name: getattr(X, "UC_X86_REG_" + name.upper())
    read = lambda name: uc.reg_read(regs_of(name))
    write = lambda name, value: uc.reg_write(regs_of(name), value & MASK)

    poison_regs = poison_nonvolatiles()
    for name, value in poison_regs.items():
        write(name, value)
    for i, value in poison_xmm().items():
        uc.reg_write(regs_of(f"xmm{i}"), value)
    uc.reg_write(regs_of("mxcsr"), 0x1F80)
    uc.reg_write(regs_of("eflags"), 2)
    for name, value in (regs or {}).items():
        write(name, value)
    uc.mem_write(SP + 0x20, bytes(0x60))
    write("rsp", SP)
    stops = set(stop) | ({site + 5} if kind == "call" else set())
    assert stops, "a jump site needs the native continuations it may exit to"
    stub_at = {va: raw for va, raw in stubs}

    frames, saves, poison = [], set(), {}
    calls, writes, errors = [], [], []
    reached, entered, instructions, exits_hit = [False], [], [0], []
    pending = [None]
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def on_code(uc_, address, size_, _):
        try:
            instructions[0] += 1
            rsp = read("rsp")
            if pending[0] is not None:
                expected, source, require_stub = pending[0]
                check(rsp == expected and rsp % 16 == 8,
                      f"callee entry alignment at {address:#x} (from {source:#x}): rsp%16={rsp % 16}")
                inside = internal[0] <= address < internal[1]
                if require_stub:                             # a call the hook makes must be its own or a stub
                    check(address in stub_at or inside,
                          f"unexpected call from {source:#x} to {address:#x} (outside the extension, not a stub)")
                pending[0] = None
            if address in stops:
                check(rsp == SP, f"continuation RSP delta {rsp - SP} at {address:#x}")
                check(not frames, f"live frames at the continuation {address:#x}")
                check(not saves, f"live saved registers at the continuation {address:#x}")
                reached[0] = True
                exits_hit.append(address)
                uc_.emu_stop()
                return
            if address in stub_at:
                entered.append(address)
                for name, value in (expect_args or {}).items():
                    check(read(name) == value & MASK,
                          f"stub {address:#x} received {name}={read(name):#x}, caller passed {value:#x}")
                for i, name in enumerate(VOLATILE):
                    write(name, 0xBADC0DE000000000 + i)
                for i in range(6):
                    uc_.reg_write(regs_of(f"xmm{i}"), 0xBAD00000000000000000000000000000 + i)
            in_stub = any(va <= address < va + len(raw_) for va, raw_ in stub_at.items())
            check(address == site or in_stub or internal[0] <= address < internal[1] or address in stops,
                  f"unowned instruction {address:#x}")
            ins = next(cs.disasm(bytes(uc_.mem_read(address, size_)), address))
            if ins.mnemonic == "push":
                saves.add(rsp - 8)
            elif ins.mnemonic == "pop":
                saves.discard(rsp)
            elif ins.mnemonic == "call":
                check(rsp % 16 == 0, f"CALL alignment at {address:#x}: rsp%16={rsp % 16}")
                check(STACK <= rsp and rsp + 32 <= STACK + STACK_SIZE, "unwritable home space")
                protected = saves | {frame[1] for frame in frames}
                check(not any(rsp < p + 8 and p < rsp + 32 for p in protected),
                      f"home space overlaps a live save/return at {address:#x}")
                depth = len(frames)
                for i in range(4):
                    uc_.mem_write(rsp + i * 8, struct.pack("<Q", 0xAABBCCDD00000000 + i))
                for p in range(rsp, rsp + 32):
                    poison[p] = depth
                frames.append((address + size_, rsp - 8))
                pending[0] = (rsp - 8, address, address != site)
                calls.append(hex(address))
            elif ins.mnemonic == "ret":
                check(kind == "call", f"RET in a jump-entered routine at {address:#x}")
                check(bool(frames), f"RET without a CALL frame at {address:#x}")
                continuation, return_slot = frames.pop()
                check(rsp == return_slot, f"RET RSP changed at {address:#x}")
                actual = struct.unpack("<Q", bytes(uc_.mem_read(rsp, 8)))[0]
                check(actual == continuation, f"wrong return address at {address:#x}")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            uc_.emu_stop()

    def on_read(uc_, access, address, size_, value, _):
        if any(p in poison and len(frames) <= poison[p] for p in range(address, address + size_)):
            errors.append(f"live home-space read at {address:#x}, PC {read('rip'):#x}")
            uc_.emu_stop()

    def on_write(uc_, access, address, size_, value, _):
        on_stack = STACK <= address and address + size_ <= STACK + STACK_SIZE
        if not on_stack and not any(a <= address and address + size_ <= b for a, b in writable):
            errors.append(f"write outside the emulated stack at {address:#x}+{size_}, PC {read('rip'):#x}")
            uc_.emu_stop()
            return
        for p in range(address, address + size_):
            poison.pop(p, None)
        writes.append((address, size_))

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_READ, on_read)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    uc.emu_start(site, 0, timeout=8000000, count=max_instructions)
    assert not errors, errors
    assert reached[0], f"did not reach {sorted(hex(s) for s in stops)} (timeout/instruction limit)"
    for name, value in (preserve or {}).items():
        check(read(name) == value & MASK, f"caller-live {name} changed: {read(name):#x} != {value:#x}")
    for name, value in poison_regs.items():
        if name in (preserve or {}) or name in outputs:
            continue
        check(read(name) == value, f"integer nonvolatile {name} clobbered: {read(name):#x} != {value:#x}")
    for i, value in poison_xmm().items():
        check(uc.reg_read(regs_of(f"xmm{i}")) == value, f"XMM{i} clobbered")
    check(read("mxcsr") & 0xFFC0 == 0x1F80, "mxcsr control bits changed")
    check(not read("eflags") & 0x400, "direction flag set")
    for name, value in (answer or {}).items():
        check(read(name) == value & MASK, f"{name} is {read(name):#x}, expected {value:#x}")
    return dict(instructions=instructions[0], stopped_at=hex(exits_hit[0]),
                call_edges=sorted(set(calls)), calls=len(calls),
                stubs_entered=[hex(v) for v in entered], rsp_delta=read("rsp") - SP,
                writes=len(writes), answer={n: read(n) for n in ("rax", "rcx", "rdx", "r10", "r15")},
                probed={hex(a): bytes(uc.mem_read(a, n)) for a, n in probe},
                site=hex(site), continuation=hex(site + 5), wrapper=hex(target))
