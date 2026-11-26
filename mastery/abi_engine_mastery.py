"""Site-entry ABI engine for the class-mastery extension (.d5cm).

Modelled on `evility/abi_engine_ex05c.py` from EX-05c: the real patched site is entered with the
caller's stack state, every instruction the extension executes is tracked, and the original game
callee is a deterministic stub that clobbers every volatile register a real callee may clobber -- so
a missing argument save or an unbalanced frame shows up as a wrong answer rather than a crash.

Two entry kinds, because .d5cm patches two kinds of instruction:

  * `call` -- an `E8` redirection (the 16 mapper sites and the sub-class screen's fetch).  The site is
    entered with caller RSP%16 == 0; the pushed return address gives the extension entry RSP%16 == 8;
    the extension returns to exactly `site + 5` with RSP restored and no live frame.
  * `jump` -- the `E9` over the selected-award sub-class gate.  Nothing is pushed, the entry keeps
    the caller's RSP, and the stub leaves by jumping to one of the native continuations (accept or
    reject).  Those exits are where the emulation stops.

Checks (each one aborts the run with a message naming the address):

  * callee-entry alignment: after every `call`, the target starts with RSP%16 == 8;
  * 32 bytes of home space at every call, not overlapping a live push/return slot, and poisoned first
    so a caller that keeps a live value there is caught on the read;
  * every `ret` returns to the address pushed by its own `call` with the frame balanced;
  * written memory stays on the emulated stack (the extension must have no side effects of its own);
  * integer nonvolatiles (rbx, rbp, rsi, rdi, r12-r15) and XMM6-15 come back unchanged, mxcsr's
    control bits and the direction flag are untouched;
  * the argument registers a stub receives are the ones the caller set (nothing is lost or rewritten
    on the way in), and each stub's answer decides the extension's answer exactly as intended.

Unicorn is imported only by `execute()`; building fixtures never loads it.
"""
import os
import struct

DEBUG = bool(os.environ.get("ABI_DEBUG"))                     # print every executed instruction (diagnostics)

PAGE = 0x1000
STACK, STACK_SIZE = 0x100000000, 0x200000
SP = STACK + STACK_SIZE - 0x1000
MASK = (1 << 64) - 1
NONVOLATILE = ("rbx", "rbp", "rsi", "rdi", "r12", "r13", "r14", "r15")
VOLATILE = ("rax", "rcx", "rdx", "r8", "r9", "r10", "r11")
# what a clobbering stub leaves in each volatile register; a test can use it to prove the extension did *not*
# rewrite a caller's volatile register
TRASH = {name: int(f"BAD{0x100 + i:X}00000000", 16) for i, name in enumerate(VOLATILE)}


def poison_nonvolatiles():
    """distinct values no extension instruction would ever produce by accident"""
    return {name: 0x13579BDF00000000 + i for i, name in enumerate(NONVOLATILE)}


def poison_xmm():
    return {i: 0x123456789ABCDEF00112233400000000 + i for i in range(6, 16)}


def clobbering_stub(rax, trash=True, ret=True):
    """a deterministic stand-in for the original callee: its answer in eax and every legal clobber"""
    from keystone import KS_ARCH_X86, KS_MODE_64, Ks
    lines = [f"mov eax, {rax}"]
    if trash:
        lines += [f"mov {name}, {TRASH[name]:#x}" for name in VOLATILE[1:]]
    if ret:
        lines.append("ret")
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_64).asm("\n".join(lines))
    return bytes(enc)


def execute(patched, info, site, *, kind="call", fixture=None, regs=None, stubs=(), stop=(),
            preserve=(), expect_args=None, answer=None, outputs=(), max_instructions=200000) -> dict:
    """Execute one patched site.

    patched   the built exe; `info` the section_info() of its extension section
    site      the patched instruction's VA
    kind      "call" (E8) or "jump" (E9)
    fixture   fixture(write) mapping world state before the run
    regs      {register: value} set before the entry (caller state)
    stubs     [(va, bytes)] original-game callees/continuations replaced in the emulated copy
    stop      extra addresses to stop at (the native continuations of a jump)
    preserve  {register: value} that must be unchanged at the stop
    expect_args  {register: value} a stub must receive, checked when the stub is entered
    answer    {register: value} the extension's own output at the stop
    outputs   nonvolatile registers the patched instruction itself writes (the extension's destinations)
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
        # one page of margin: unicorn 2.1.4 refuses to *fetch* in the last 256 bytes of a region
        end = (address + len(data) + PAGE - 1) & -PAGE
        for page in range(address & -PAGE, end + PAGE, PAGE):
            if page not in mapped:
                uc.mem_map(page, PAGE)
                mapped.add(page)
        uc.mem_write(address, bytes(data))

    size = (pe.OPTIONAL_HEADER.SizeOfImage + PAGE - 1) & -PAGE
    # Only the extension's own bytes, the emulated stack and the stubs need to be mapped: the run starts at
    # the patched site and stops at the native continuation, so no other game code is ever executed.
    map_bytes(info["base"], info["data"])
    map_bytes(STACK, bytes(STACK_SIZE))
    map_bytes(site, patched[pe.get_offset_from_rva(site - base):pe.get_offset_from_rva(site - base) + 5])
    for va, raw in stubs:
        map_bytes(va, raw)
    if fixture:
        fixture(map_bytes)

    off = pe.get_offset_from_rva(site - base)
    raw = patched[off:off + 5]
    opcode = 0xE8 if kind == "call" else 0xE9
    assert raw[0] == opcode, f"site {site:#x} is {raw[0]:#04x}, not {opcode:#04x}"
    target = site + 5 + struct.unpack("<i", raw[1:])[0]
    assert info["code"] <= target < info["base"] + info["size"], hex(target)

    regs_of = lambda name: getattr(X, "UC_X86_REG_" + name.upper())
    read = lambda name: uc.reg_read(regs_of(name))
    write = lambda name, value: uc.reg_write(regs_of(name), value & MASK)

    for name, value in poison_nonvolatiles().items():
        write(name, value)
    for i, value in poison_xmm().items():
        uc.reg_write(regs_of(f"xmm{i}"), value)
    uc.reg_write(regs_of("mxcsr"), 0x1F80)
    uc.reg_write(regs_of("eflags"), 2)
    for name, value in (regs or {}).items():
        write(name, value)
    uc.mem_write(SP + 0x20, bytes(0x60))                     # the caller's outgoing home space
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
                if require_stub:                             # calls the extension itself makes must go to a stub
                    check(address in stub_at,
                          f"unexpected original-game call from {source:#x} to {address:#x}")
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
                # Legal original-game clobbers make missing argument saves visible.
                for i, name in enumerate(VOLATILE):
                    write(name, 0xBADC0DE000000000 + i)
                for i in range(6):
                    uc_.reg_write(regs_of(f"xmm{i}"), 0xBAD00000000000000000000000000000 + i)
            in_stub = any(va <= address < va + len(raw) for va, raw in stub_at.items())
            check(address == site or in_stub or
                  info["code"] <= address < info["base"] + len(info["data"]) or address in stops,
                  f"unowned instruction {address:#x}")
            if DEBUG:
                print(f"   {address:#x} rsp={rsp:#x} rbx={read('rbx'):#x} "
                      f"mem8={bytes(uc_.mem_read(rsp, 8)).hex()}")
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
                for i in range(4):                            # a real callee may clobber its home space
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
        if not (STACK <= address and address + size_ <= STACK + STACK_SIZE):
            errors.append(f"write outside the emulated stack at {address:#x}+{size_}, PC {read('rip'):#x}")
            uc_.emu_stop()
            return
        for p in range(address, address + size_):
            poison.pop(p, None)
        writes.append((address, size_))

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_READ, on_read)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    uc.emu_start(site, 0, timeout=8000000, count=max_instructions)   # the hook stops us at a stop
    assert not errors, errors
    assert reached[0], f"did not reach {sorted(hex(s) for s in stops)} (timeout/instruction limit)"
    for name, value in (preserve or {}).items():
        check(read(name) == value & MASK, f"caller-live {name} changed: {read(name):#x} != {value:#x}")
    for name, value in poison_nonvolatiles().items():
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
                site=hex(site), continuation=hex(site + 5), wrapper=hex(target))
