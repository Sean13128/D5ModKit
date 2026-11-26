"""Code patches for disgaea5.exe (Steam/CODEX build, image base 0x140000000).

Outfit feature
--------------
Character list -> unit sub-menu (Equipment / Evility / Status) gets an "Outfit" entry for characters
that have outfits.  Choosing it turns the same menu into the list of the character's outfits ("Default",
"Swimsuit", ...); choosing one sets the unit's class id to that outfit's char.dat row (a copy of the
character with another sprite / face / portrait), refreshes the unit with the game's own routine and
rebuilds the character's sprite on screen.  Stats, level, name, equipment and colour stay the same.

Reverse-engineered locations (see docs/EXE_ANALYSIS.md):
  0x140263875  opening the sub-menu for the selected character: state +0xbdc8 = 1, open(menu)
               @0x1402b09a0.  The menu (scene+0xbd98) is built once at scene start; we rebuild it here
               on every opening: init(menu, n) @0x1402b16b0 (frees / reallocates), add(menu, &entry)
               @0x1402b0cb0 with entry {u32 value, u32 flag, u32 label_id, u32 help_id}
  0x140263432  confirm dispatch: +0xbdac = selected POSITION (vanilla values 0 Equipment, 1 Evility,
               2 Status equal their positions); the entry's value is read from the menu's entry array
               (menu+0 entries of 16 bytes, menu+8 count); 0x140263a5f = keep going
  0x1400928d0  list component (scene+0x80) -> selected entry, [entry] = unit pointer
  0x14015eb80  refresh unit (+0x2E0A row index, +0x2E36 graphics id) from class id (+0x2E04)
  0x1402634e9  tail of the 'cancel' path (returns to the character list)
  0x14067e7d1  hub / party characters: the scene only rebuilds a character's sprite when the unit's
               colour changed (the class comparison reads the same unit twice) -> compare with the class
               the sprite was built with (actor+0x258) so an outfit change shows at once
  0x14014d354  sprite layer setup: outfit sprites with their own complete animation set use their own
               block instead of the shared humanoid motion set (block 1)
"""
import struct

import pefile

try:
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
except ImportError:  # pragma: no cover
    Ks = None

IMAGE_BASE = 0x140000000
SECTION_NAME = b".d5mod"

# A kit section can carry the code of several features: the exe has only 11 section-header slots and
# vanilla uses 7, so a fresh header per feature would run out. Every appended region therefore ends with a
# 28-byte claim block naming its feature, and `has_feature` parses that block instead of matching bytes: a
# claim must sit inside a kit section, name a region that starts inside it, and (if the caller asks) carry the
# configuration digest the build was made from and still point its hook sites into the section.
KIT_SECTION_PREFIX = b".d5"
CLAIM_MAGIC = b"D5KIT\x02"       # version 2: the block also carries the feature's configuration digest
CLAIM_LEGACY = b"D5KIT\x01"      # installs made before the digest existed; recognised, never written
CLAIM_SIZE = 28

OPEN_VA = 0x140263875
OPEN_ORIG = bytes.fromhex("488d8b98bd0000c783c8bd000001000000")
OPEN_RET = 0x140263886
DISPATCH_VA = 0x140263432
DISPATCH_ORIG = bytes.fromhex("8b8bacbd000085c97418")
HUB_VA = 0x14067E7D1
HUB_ORIG = bytes.fromhex("8b88042e0000")
HUB_RET = 0x14067E7DC
# faces: the character-list status panel and the Status screen play animation 10000 + graphics id
# (unit+0x2E36) of the resident UI block 9017.  Outfits with their own face picture get animation
# 10000 + outfit class id there; these hooks pick it for units wearing such an outfit.
FACE_A_VA = 0x1402AE881          # lea edx, [rcx+0x2710]   (unit = [rbx+0x90])
FACE_A_ORIG = bytes.fromhex("8d9110270000")
FACE_A_RET = 0x1402AE887
FACE_B_VA = 0x14043088E          # xor r9d,r9d / xor r8d,r8d / lea edx,[rax+r10]   (unit = r12)
FACE_B_ORIG = bytes.fromhex("4533c94533c0428d1410")
FACE_B_RET = 0x140430898
# graphics id (unit+0x2E36, = char.dat colour id for unique characters) is computed by 0x14021e9d0(class,
# colour); the character list's small face icons follow it.  Outfits with their own face get their own
# graphics id (their class id) here, while char.dat keeps the base colour id (safe for everything else).
GFX_VA = 0x14021E9D0
GFX_ORIG = bytes.fromhex("48895c2408")
GFX_RET = 0x14021E9D5
LAYER_VA = 0x14014D354
LAYER_ORIG = bytes.fromhex("98b90100000083f80a0f4cc8eb03")
LAYER_RET = 0x14014D365
# character objects rebuilt after a change (setup(actor, class, colour, 0, 0) @0x14014dc60, as the event
# command 'assign unit to actor' does): event / hub actors and unit actors
ACTORS_A = 0x14150ABD0     # 512 x 0x3e0   (lookup 0x140168a03)
ACTORS_B = 0x1415A5BE0     # 256 x 0x1260  (lookup 0x1402eac96)
# the hub's player character (leader): a global actor, found with a memory probe of the running game
# (the only object pointing at the unit; referenced by the movement code, e.g. 0x140169afd)
LEADER = 0x142349160

VANILLA_ENTRIES = [(0, 11957, 10589), (1, 10643, 10610), (2, 10593, 10590)]
MENU_VALUE = 3             # "Outfit"
PICK_BASE = 100            # outfit list entries: value = 100 + record index
MORE_VALUE = 99            # "More outfits": the next page of a long outfit list
MORE_LABEL_ID = 40009      # its StringListDataBase text (outfits.MORE_ID)
OUTFIT_PAGE = 12           # outfits per page: the list opens at a fixed place and ~14 rows fit on screen


def _asm(src, addr):
    """assemble src at addr; the game addresses written in it are those of the known build, translated to the build
    being patched (exemap.ACTIVE)"""
    if Ks is None:
        raise RuntimeError("keystone-engine is required: pip install keystone-engine")
    from . import exemap
    src = exemap.ACTIVE.text(src)
    ks = Ks(KS_ARCH_X86, KS_MODE_64)
    enc, _ = ks.asm(src, addr)
    return bytes(enc)


def _last_section(pe):
    return max(pe.sections, key=lambda s: s.VirtualAddress)


def _growable_section(pe, exe):
    """the kit section a new code region can be appended to, or None when the exe needs a new header.

    Only the last section can grow: its raw data must end the file (otherwise appending would have to move
    everything after it), it must be a kit section, and it must be executable. Growing keeps the header table
    at a fixed size however many features a build enables."""
    last = _last_section(pe)
    if not last.Name.startswith(KIT_SECTION_PREFIX):
        return None
    if not last.Characteristics & 0x20000000:          # IMAGE_SCN_MEM_EXECUTE
        return None
    if last.PointerToRawData + last.SizeOfRawData != len(exe):
        return None                                    # something (an overlay) was appended after it
    return last


def _section_layout(pe, exe):
    """where a code section appended to `exe` starts: (base va, grow, offset in the last section)

    The exe has room for only a few more section headers: when the last section is already one of the kit's code
    sections (and ends the file), the new code is appended to it instead of getting a header of its own. That is
    the normal path: the first kit section is the only header a build takes, and every later feature shares it."""
    sec_align = pe.OPTIONAL_HEADER.SectionAlignment
    last = _growable_section(pe, exe)
    grow = last is not None
    last = last or _last_section(pe)
    if grow:
        offset = (last.Misc_VirtualSize + 15) // 16 * 16
        base = IMAGE_BASE + last.VirtualAddress + offset
        new_rva = last.VirtualAddress
    else:
        offset = 0
        new_rva = (last.VirtualAddress + max(last.Misc_VirtualSize, last.SizeOfRawData) + sec_align - 1) \
            // sec_align * sec_align
        base = IMAGE_BASE + new_rva
    return base, grow, offset, new_rva


def code_base(exe: bytes, name: bytes = b"") -> int:
    """the address a section appended by add_code_section will start at (assemble code for this address)"""
    pe = pefile.PE(data=exe, fast_load=True)
    return _section_layout(pe, exe)[0]



def _extension_functions(code, base, targets, *, label=".d5el", allow_exits=False, allowed_writes=()):
    """Discover the extension's reachable routines and encode their fixed-frame prologues.

    Deliberately restricted to sections whose entries are CALL targets and whose
    frames have contiguous push/sub prologues and Windows x64 epilogues. Reject
    unsupported stack manipulation rather than emit plausible but false unwind
    records. Decode by CFG so inline tables never become executable ranges.

    `allow_exits` accepts a branch out of the extension as a routine end (.d5cm's
    sub-class gate is a jump into native code and never returns), and
    `allowed_writes` names nonvolatile registers a routine is supposed to write
    because it stands in for a native instruction that wrote them.
    """
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from capstone.x86_const import X86_OP_IMM, X86_OP_REG
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    entries = {base + 16, *targets}
    routines = {}
    instructions = {}
    def instruction(pc):
        if pc not in instructions:
            decoded = next(md.disasm(code[pc - base:pc - base + 15], pc, count=1), None)
            if decoded is None:
                raise ValueError(f"{label}: cannot decode {pc:#x}")
            instructions[pc] = decoded
        return instructions[pc]
    while entries - routines.keys():
        entry = min(entries - routines.keys())
        pending, seen = [entry], {}
        while pending:
            pc = pending.pop()
            if pc in seen:
                continue
            if not base + 16 <= pc < base + len(code):
                if allow_exits:
                    continue
                raise ValueError(f"{label}: branch outside extension")
            i = instruction(pc)
            seen[pc] = i
            m, ops = i.mnemonic, i.operands
            nxt = pc + i.size
            if m == "ret":
                continue
            if m == "call":
                if ops[0].type != X86_OP_IMM:
                    raise ValueError(f"{label}: indirect call is not supported")
                target = ops[0].imm
                if base <= target < base + len(code):
                    entries.add(target)
            if m.startswith("j"):
                if ops[0].type != X86_OP_IMM:
                    raise ValueError(f"{label}: indirect branch is not supported")
                pending.append(ops[0].imm)
                if m == "jmp":
                    continue
            pending.append(nxt)
        routines[entry] = seen
    regs = {name: n for n, name in enumerate(
        ("rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
         "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"))}
    nonvolatile = {"rbx", "rbp", "rsi", "rdi", "r12", "r13", "r14", "r15"}
    result = []
    previous_end = base + 16
    for entry, seen in sorted(routines.items()):
        end = max(pc + i.size for pc, i in seen.items())
        if entry < previous_end:
            raise ValueError(f"{label}: overlapping/shared-tail functions need separate frames")
        previous_end = end
        pc, codes, prologue, saved = entry, [], set(), set()
        pushes, allocation = [], 0
        while pc in seen:
            i = seen[pc]
            m, ops = i.mnemonic, i.operands
            off = pc + i.size - entry
            if off > 255:
                raise ValueError(f"{label}: prologue too long")
            if m == "mov" and pc == entry and i.op_str.startswith("r11d, "):
                pass  # wrapper's build tag, before its fixed frame
            elif m == "push" and ops[0].type == X86_OP_REG:
                reg = i.reg_name(ops[0].reg)
                if reg == "rsp" or reg not in regs:
                    raise ValueError(f"{label}: unsupported push")
                if allocation:
                    raise ValueError(f"{label}: push after allocation")
                pushes.append(reg)
                if reg in nonvolatile:
                    codes.append(bytes((off, regs[reg] << 4)))  # UWOP_PUSH_NONVOL
                    saved.add(reg)
                else:
                    codes.append(bytes((off, 2)))  # UWOP_ALLOC_SMALL, 8 bytes
            elif m == "sub" and i.op_str.startswith("rsp, ") and ops[1].type == X86_OP_IMM:
                amount = ops[1].imm
                if allocation:
                    raise ValueError(f"{label}: multiple stack allocations")
                allocation = amount
                if amount < 8 or amount % 8 or amount > 0x7fff8:
                    raise ValueError(f"{label}: unsupported stack allocation")
                if amount <= 128:
                    codes.append(bytes((off, ((amount // 8 - 1) << 4) | 2)))
                else:
                    codes.append(bytes((off, 1)) + struct.pack("<H", amount // 8))
            else:
                break
            prologue.add(pc)
            pc += i.size
        prologue_size = pc - entry
        # RtlVirtualUnwind recognizes only canonical epilogues. Also verify that
        # every nonvolatile write has a corresponding prologue save.
        intentional = set(allowed_writes)
        for address, i in seen.items():
            if address in prologue:
                continue
            m = i.mnemonic
            writes = {i.reg_name(r) for r in i.regs_access()[1]}
            aliases = {alias: reg for reg, aliases in (
                ("rbx", ("ebx", "bx", "bl", "bh")), ("rbp", ("ebp", "bp", "bpl")),
                ("rsi", ("esi", "si", "sil")), ("rdi", ("edi", "di", "dil")),
                *((f"r{n}", (f"r{n}d", f"r{n}w", f"r{n}b")) for n in range(12, 16)))
                for alias in aliases}
            writes = {aliases.get(r, r) for r in writes}
            if writes & {f"xmm{n}" for n in range(6, 16)}:
                raise ValueError(f"{label}: XMM nonvolatile saves require explicit unwind support")
            if writes & (nonvolatile - saved - intentional):
                raise ValueError(f"{label}: unsaved nonvolatile write at {address:#x}: {i.mnemonic} {i.op_str}")
            if "rsp" not in writes or m in ("call", "ret"):
                continue
            if m not in ("add", "pop") or (m == "add" and not i.op_str.startswith("rsp, ")):
                raise ValueError(f"{label}: non-fixed stack at {address:#x}")
            tail = address + i.size
            while tail in seen and seen[tail].mnemonic == "pop":
                tail += seen[tail].size
            if tail not in seen or seen[tail].mnemonic != "ret":
                raise ValueError(f"{label}: noncanonical epilogue at {address:#x}")
        # Every return must undo exactly this prologue. Shape alone would
        # accept a wrong ADD constant or a reordered/missing POP sequence.
        predecessors = {address + i.size: i for address, i in seen.items()}
        for address, i in seen.items():
            if i.mnemonic != "ret":
                continue
            cursor, popped = address, []
            while cursor in predecessors and predecessors[cursor].mnemonic == "pop":
                previous = predecessors[cursor]
                popped.append(previous.op_str)
                cursor = previous.address
            actual_allocation = 0
            previous = predecessors.get(cursor)
            if previous is not None and previous.mnemonic == "add" and previous.op_str.startswith("rsp, "):
                actual_allocation = previous.operands[1].imm
            if popped != pushes or actual_allocation != allocation:
                raise ValueError(f"{label}: epilogue does not reverse prologue at {address:#x}")
        encoded = b"".join(reversed(codes))
        count = len(encoded) // 2
        if count > 255:
            raise ValueError(f"{label}: too many unwind codes")
        info = bytes((1, prologue_size, count, 0)) + encoded
        info += b"\0" * (-len(info) % 4)
        result.append((entry - IMAGE_BASE, end - IMAGE_BASE, info))
    return result


def _d5ev_exception_data(pe, code, base, targets, *, label=".d5el", allow_exits=False, allowed_writes=()):
    """Append xdata and a sorted copy of the existing plus new runtime table."""
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]  # IMAGE_DIRECTORY_ENTRY_EXCEPTION
    if directory.Size % 12:
        raise ValueError("invalid PE exception directory size")
    old = pe.get_data(directory.VirtualAddress, directory.Size) if directory.Size else b""
    if len(old) != directory.Size:
        raise ValueError("truncated PE exception directory")
    entries = list(struct.iter_unpack("<III", old))
    payload = bytearray(code)
    payload += b"\0" * (-len(payload) % 4)
    for start, end, info in _extension_functions(code, base, targets, label=label, allow_exits=allow_exits,
                                                 allowed_writes=allowed_writes):
        unwind = base - IMAGE_BASE + len(payload)
        entries.append((start, end, unwind))
        payload += info
    entries.sort()
    previous_end = 0
    for start, end, unwind in entries:
        if start < previous_end or start >= end or not unwind or unwind % 4:
            raise ValueError("invalid/overlapping PE runtime functions")
        previous_end = end
    table_rva = base - IMAGE_BASE + len(payload)
    for entry in entries:
        payload += struct.pack("<III", *entry)
    return bytes(payload), table_rva, len(entries) * 12


# Sections that receive fixed-frame unwind records (xdata + a relocated runtime
# table). .d5cm and .d5pm both carry the sub-class gate (entered by jump, leaves by
# jump into native code) and the sub-class screen's fetch stub (writes the r15d its
# native instruction wrote).
UNWIND_SECTIONS = {
    b".d5el": dict(label=".d5el"),
    b".d5cm": dict(label=".d5cm", allow_exits=True, allowed_writes=("r15",)),
    b".d5pm": dict(label=".d5pm", allow_exits=True, allowed_writes=("r15",)),
    # EVCAP2: the learned-evility capacity extension (d5lib/learned.py) -- wrappers plus four private
    # helpers, every one a fixed-frame CALL entry with a canonical epilogue.
    b".d5lc": dict(label=".d5lc"),
}


def _d5ev_functions(code, base, targets):
    """The .d5el encoding under its original name (used by the unwind tests)."""
    return _extension_functions(code, base, targets, **UNWIND_SECTIONS[b".d5el"])


def _claim_block(name: bytes, length: int, digest: int = 0) -> bytes:
    """the 28-byte block that ends one feature's region: magic, feature name, length of its code and a digest of the
    configuration it was built from (0 when the feature has none)."""
    return (CLAIM_MAGIC + name[:8].ljust(8, b"\0") + struct.pack("<III", length, digest, 0) + b"\0\0")


def _config_digest(value) -> int:
    """a stable 32-bit digest of a feature's configuration, so a build can tell "installed from these inputs" from
    "installed from different inputs" (0 = the feature has no configuration to compare)."""
    if value is None or value == 0:
        return 0
    import hashlib
    if not isinstance(value, (bytes, bytearray)):
        value = json_dumps(value).encode("utf-8")
    return struct.unpack("<I", hashlib.sha256(bytes(value)).digest()[:4])[0]


def json_dumps(value) -> str:
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def feature_claims(exe: bytes):
    """every claim block found in a kit section, as {name, section, rva, length, digest, version, valid}.

    Parsing is bounded: a block must lie wholly inside its section, name a region that starts inside the section
    and use a known magic, so stray bytes that happen to spell a feature name are not a claim."""
    pe = pefile.PE(data=exe, fast_load=True)
    out = []
    for s in pe.sections:
        if not s.Name.startswith(KIT_SECTION_PREFIX):
            continue
        data = pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)
        pos = data.find(b"D5KIT")
        while pos >= 0:
            chunk = data[pos:pos + CLAIM_SIZE]
            if len(chunk) < 20 or chunk[:6] not in (CLAIM_MAGIC, CLAIM_LEGACY):
                pos = data.find(b"D5KIT", pos + 1)
                continue
            legacy = chunk[:6] == CLAIM_LEGACY
            if not legacy and len(chunk) < CLAIM_SIZE:
                pos = data.find(b"D5KIT", pos + 1)
                continue
            name = chunk[6:14].rstrip(b"\0")
            if legacy:
                length, digest = struct.unpack_from("<I", chunk, 16), 0
            else:
                length, digest, _reserved = struct.unpack_from("<III", chunk, 14)
            region = pos - length
            out.append({"name": name, "section": s.Name.rstrip(b"\0").decode("ascii", "replace"),
                        "rva": s.VirtualAddress + pos, "length": length, "digest": digest,
                        "version": 1 if legacy else 2,
                        "valid": bool(name) and region >= 0 and length > 0})
            pos = data.find(b"D5KIT", pos + 1)
    return out


def _hook_opcode(exe: bytes, pe, va: int, opcode: int) -> bool:
    """does the byte at `va` start the given hook opcode?  (no opinion when the address is outside the file)"""
    try:
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
    except Exception:
        return False
    return off is not None and 0 <= off < len(exe) and exe[off] == opcode


def _hook_lands(exe: bytes, pe, va: int, opcode: int, lo: int, hi: int) -> bool:
    """is the instruction at `va` the jmp/call `opcode` into [lo, hi)?"""
    try:
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
    except Exception:
        return False
    if off is None or off + 5 > len(exe) or exe[off] != opcode:
        return False
    return lo <= va + 5 + struct.unpack("<i", exe[off + 1:off + 5])[0] < hi


def has_feature(exe: bytes, name: bytes, digest=None, hooks=()) -> bool:
    """whether `exe` carries the kit feature that writes section/claim `name`, *and* that claim is a complete one.

    A section header is shared by every feature that grew into it, so the section name alone is not evidence for the
    features that did not own the header: the claim block is.  `digest` (see _config_digest) makes a claim built from
    different inputs count as "not installed", and `hooks` = [(va, opcode)] requires those sites to still jump into
    the section, so a half-applied or stale patch is rebuilt instead of accepted.  Installs older than the claim
    block are still recognised by their section header name (there is nothing else to check on them)."""
    name = name[:8].rstrip(b"\0")
    want = _config_digest(digest)
    pe = pefile.PE(data=exe, fast_load=True)
    if hooks:
        # the callers name the site in known-build addresses; this exe's own address is what is patched.  Try the
        # given address and its translation, and check only the candidates that actually hold the hook opcode: when
        # none does (an exe no translator covers, a payload under inspection) "cannot check" must not read as
        # "not installed", so the claim alone decides.
        from . import exemap
        candidates = []
        for va, op in hooks:
            candidates.append((va, op))
            try:
                candidates.append((exemap.ACTIVE(va), op))
            except Exception:
                pass
        hooks = [(va, op) for va, op in candidates if _hook_opcode(exe, pe, va, op)]
        # nothing held the opcode -> no translator covers this exe: the claim alone decides
    for s in pe.sections:
        if not s.Name.startswith(KIT_SECTION_PREFIX):
            continue
        lo = IMAGE_BASE + s.VirtualAddress
        hi = lo + s.Misc_VirtualSize
        for claim in feature_claims(exe):
            if claim["section"] != s.Name.rstrip(b"\0").decode("ascii", "replace") or claim["name"] != name:
                continue
            if not claim["valid"]:
                continue
            if claim["version"] >= 2 and want and claim["digest"] != want:
                continue
            if hooks and not all(_hook_lands(exe, pe, va, op, lo, hi) for va, op in hooks):
                continue
            return True
    if not want and not hooks:
        return any(s.Name.rstrip(b"\0") == name for s in pe.sections)
    return False


def add_code_section(exe: bytes, name: bytes, code: bytes, patches, writable=False, digest=None) -> bytes:
    """Append already-assembled `code` as section `name` and point patch sites at addresses inside it.
    patches: [(va, original bytes, target va, opcode 0xE9 jmp / 0xE8 call)].  `code` must have been assembled
    for `code_base(exe, name)`. When the last section is a kit code section, the code is appended to it
    instead of taking a header (see `_section_layout`); the region ends with a claim block naming `name`.
    Sections in `UNWIND_SECTIONS` (.d5el, .d5cm) additionally receive fixed-frame
    unwind records and a relocated exception directory retaining the existing entries."""
    pe = pefile.PE(data=exe)
    base, grow, offset, new_rva = _section_layout(pe, exe)
    exception = None
    if name in UNWIND_SECTIONS:
        code, table_rva, table_size = _d5ev_exception_data(pe, code, base, [p[2] for p in patches],
                                                          **UNWIND_SECTIONS[name])
        exception = (table_rva, table_size)
    length = len(code)
    code += b"\xCC" * (-len(code) % 4) + _claim_block(name, length, _config_digest(digest))
    sec_align = pe.OPTIONAL_HEADER.SectionAlignment
    file_align = pe.OPTIONAL_HEADER.FileAlignment
    secs = sorted(pe.sections, key=lambda s: s.VirtualAddress)
    last = secs[-1]
    fh = pe.DOS_HEADER.e_lfanew + 4
    sh_base = fh + 20 + pe.FILE_HEADER.SizeOfOptionalHeader
    if grow:
        i = pe.sections.index(last)
        sh = sh_base + 40 * i
        vsize = offset + len(code)
        raw = (vsize + file_align - 1) // file_align * file_align
        body = bytearray(exe[last.PointerToRawData:last.PointerToRawData + last.Misc_VirtualSize])
        body += b"\xCC" * (offset - len(body)) + code
        body += b"\xCC" * (raw - len(body))
        out = bytearray(exe[:last.PointerToRawData]) + body
        struct.pack_into("<I", out, sh + 8, vsize)
        struct.pack_into("<I", out, sh + 16, raw)
        if writable:
            struct.pack_into("<I", out, sh + 36, last.Characteristics | 0x80000000)
        struct.pack_into("<I", out, fh + 20 + 56,
                         (last.VirtualAddress + vsize + sec_align - 1) // sec_align * sec_align)
    else:
        new_raw = (len(exe) + file_align - 1) // file_align * file_align
        section = code + b"\xCC" * (-len(code) % file_align)
        out = bytearray(exe) + b"\0" * (new_raw - len(exe))
        nsec = pe.FILE_HEADER.NumberOfSections
        sh_off = sh_base + 40 * nsec
        if sh_off + 40 > pe.OPTIONAL_HEADER.SizeOfHeaders:
            last = _last_section(pe)
            raise ValueError(
                f"no room for another section header for {name.decode('ascii', 'replace')}: "
                f"{pe.FILE_HEADER.NumberOfSections} sections, {pe.OPTIONAL_HEADER.SizeOfHeaders} bytes of headers, "
                f"and the last section {last.Name.rstrip(bytes(1)).decode('ascii', 'replace')} cannot be grown "
                "(not a .d5 kit code section, or not at the end of the file)")
        out[sh_off:sh_off + 40] = struct.pack("<8sIIIIIIHHI", name.ljust(8, b"\0"), len(code), new_rva,
                                              len(section), new_raw, 0, 0, 0, 0,
                                              0xE0000020 if writable else 0x60000020)  # code|execute|read(|write)
        struct.pack_into("<H", out, fh + 2, nsec + 1)
        struct.pack_into("<I", out, fh + 20 + 56, (new_rva + len(code) + sec_align - 1) // sec_align * sec_align)
        out += section
    if exception is not None:
        directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        struct.pack_into("<II", out, directory.get_file_offset(), *exception)
    from . import exemap
    for va, orig, target, op in patches:
        exemap.claim(va, len(orig), f"{name.decode(errors='replace')} patch")   # every in-place patch is in the site ledger
        off = pe.get_offset_from_rva(va - IMAGE_BASE)
        out[off:off + len(orig)] = bytes([op]) + struct.pack("<i", target - (va + 5)) + b"\x90" * (len(orig) - 5)
    return bytes(out)


def add_hook_section(exe: bytes, name: bytes, hooks, shared_src="", writable=False, shared_bytes=b"", *,
                     native_hooks=(), digest=None) -> bytes:
    """Append a code section `name` to the exe and point hook sites at code inside it.
    hooks: [(va, original bytes, asm source, opcode 0xE9 jmp / 0xE8 call)].  `shared_src` (a subroutine with its
    data) is placed first; hook sources reach it as {shared}.  Each source is assembled at its own address, so labels
    only need to be unique within one source.  shared_bytes: raw data placed first instead (e.g. a zeroed buffer;
    writable=True makes the section writable).  `hooks` uses known-build VAs; `native_hooks` uses VAs discovered
    in this input exe and requires exact original bytes (no translation). Assembly in either list still uses
    known-build hex addresses; write discovered branch targets in decimal, as exemap.at() does.

    Hooks another runtime owns (Overlord's, when its runtime is part of this install) are dropped here, at the
    one place every feature goes through: see d5lib.overlord_compat."""
    from . import exemap, overlord_compat
    hooks, _yielded = overlord_compat.filter_hooks(name, hooks)
    native_hooks, _native_yielded = overlord_compat.filter_hooks(name, native_hooks, native=True)
    pe = pefile.PE(data=exe)
    hooks = [(exemap.site(pe, va, orig, "hook site"), orig, body, op) for va, orig, body, op in hooks]
    for va, orig, body, op in native_hooks:
        if pe.get_data(va - IMAGE_BASE, len(orig)) != orig:
            raise ValueError(f"unexpected exe version: native hook site {va:#x} doesn't match")
        hooks.append((va, orig, body, op))
    base = _section_layout(pe, exe)[0]
    code = bytes(shared_bytes) if shared_bytes else (_asm(shared_src, base) if shared_src else b"")
    starts = []
    for _, _, body, _ in hooks:
        code += b"\xCC" * (-len(code) % 16)
        starts.append(base + len(code))
        code += _asm(body.replace("{shared}", hex(base)), base + len(code))
    patches = [(va, orig, target, op) for (va, orig, _, op), target in zip(hooks, starts)]
    return add_code_section(exe, name, code, patches, writable, digest=digest)


LAYER_SECTION = b".d5ly"


def build_layer_patch(exe: bytes, own_sprites) -> bytes:
    """Only the sprite layer hook of the outfit patch (sprites with their own complete animation set, e.g. new
    classes), for installs without outfits."""
    own = sorted({int(x) for x in own_sprites})
    nl = chr(10)
    src = nl.join([
        "    cwde",
        "    mov ecx, 1",
        "    cmp eax, 0xa",
        "    cmovl ecx, eax",
        "    lea r10, [rip + own_sprites]",
        f"    mov r11d, {len(own)}",
        "own_loop:",
        "    test r11d, r11d",
        "    je own_done",
        "    cmp eax, dword ptr [r10]",
        "    je own_hit",
        "    add r10, 4",
        "    dec r11d",
        "    jmp own_loop",
        "own_hit:",
        "    mov ecx, eax",
        "own_done:",
        f"    jmp {LAYER_RET:#x}",
        "    .align 4",
        "own_sprites:",
        "    .long " + ", ".join(map(str, own)),
    ])
    return add_hook_section(exe, LAYER_SECTION, [(LAYER_VA, LAYER_ORIG, src, 0xE9)])


GFX_SECTION = b".d5gx"


def _gfx_src(table, n, entries):
    """The graphics-id hook (anm_id_for_variant entry, known build 0x14021E9D0): a class in the table returns at once,
    every other class runs the original function.  A hit returns the class id while every entry is (c, 10000 + c),
    the code the outfit patch always had; otherwise it returns the entry's second word - 10000 (D4-GFX1: a registry
    unique's own colour id, which the native rounds to another character's for class ids > 999).  Leaf code: it
    touches rax, r10 and r11 only and leaves rsp alone."""
    hit = "mov eax, ecx" if all(a == 10000 + c for c, a in entries) else \
        "mov eax, dword ptr [r10+4]\n        sub eax, 10000"
    return f"""
        lea r10, {table}
        mov r11d, {max(1, n)}
    g_loop:
        cmp dword ptr [r10], ecx
        je g_hit
        add r10, 8
        dec r11d
        jne g_loop
        mov qword ptr [rsp+8], rbx
        jmp {GFX_RET:#x}
    g_hit:
        {hit}
        ret"""


def build_gfx_patch(exe: bytes, entries) -> bytes:
    """Only the graphics-id hook of the outfit patch, for installs without outfits (D4-GFX1).
    entries: [(class id, 10000 + graphics id)]: anm_id_for_variant returns that graphics id for the class."""
    entries = sorted({(int(c), int(a)) for c, a in entries})
    table = "\n".join(f"    .long {c}, {a}" for c, a in entries)
    src = _gfx_src("[rip + gfx_map]", len(entries), entries) + f"""
    .align 4
gfx_map:
{table}"""
    return add_hook_section(exe, GFX_SECTION, [(GFX_VA, GFX_ORIG, src, 0xE9)])


def is_patched(exe: bytes) -> bool:
    """the outfit/menu patch is present (by section name or by its claim block, whichever the build kept)"""
    return has_feature(exe, SECTION_NAME)


def colour_swaps(n, a, b):
    """Custom colours of an outfit group with n looks: the worn look's set is the unit's colour set 0,
    the others wait in sets 1 and 2 in look order.  -> swap ops (1 = sets 0/1, 2 = sets 0/2, 3 = sets 1/2)
    turning the layout for look a into the one for look b."""
    lay = [a] + sorted(x for x in range(n) if x != a)
    ops = []
    if lay[0] != b:
        j = lay.index(b)
        lay[0], lay[j] = lay[j], lay[0]
        ops.append(j)
    if n > 2 and lay[1] > lay[2]:
        lay[1], lay[2] = lay[2], lay[1]
        ops.append(3)
    return ops


def build_outfit_patch(exe: bytes, records, label_id: int, help_id: int, own_sprites=(), faces=(),
                       looks=None, more_label=MORE_LABEL_ID, gfx_ids=(), own_masks=None) -> bytes:
    """Return a patched copy of a VANILLA exe.
    records: [(group, class id, label string id)] -- every outfit group lists its members in menu order
    (first = the character's normal look, "Default"); label 0 = hidden member (legacy ids that only
    belong to the group).
    faces: [(outfit class id, face animation id)] for outfits with their own face picture.
    looks: {class id: (look index, looks in the group)} -- each look keeps its own custom colours
    (Strategy Assembly precise colours) in one of the unit's three colour sets; 0 looks = shared.
    gfx_ids: [(class id, 10000 + graphics id)] that only the graphics-id hook uses (registry uniques, see
    build_gfx_patch).
    own_masks: {outfit class id: outfitapply.OWN_BITS}: outfits with their own stats / evilities ...; a switch
    to or from one applies the row difference to the unit (OUTFITOWN2, d5lib.outfitapply).  None/empty: the code
    is exactly what it was without it."""
    from . import exemap
    pe = pefile.PE(data=exe, fast_load=True)   # headers and sections only: a full parse takes ~1 s
    if is_patched(exe):
        raise ValueError("exe already contains the .d5mod section (patch the vanilla exe)")
    at = {}
    for va, orig in ((OPEN_VA, OPEN_ORIG), (DISPATCH_VA, DISPATCH_ORIG), (HUB_VA, HUB_ORIG),
                     (LAYER_VA, LAYER_ORIG), (FACE_A_VA, FACE_A_ORIG), (FACE_B_VA, FACE_B_ORIG),
                     (GFX_VA, GFX_ORIG)):
        # checked here, claimed where written: add_code_section claims each patch it applies, and the face, layer
        # and gfx hooks are only written when their features are present
        at[va] = exemap.site(pe, va, orig, "outfit menu patch site", claim=False)

    base = code_base(exe)          # the vanilla exe's first kit section header (.d5mod)

    nl = chr(10)
    entries = VANILLA_ENTRIES + [(MENU_VALUE, label_id, help_id)]
    table = nl.join(f"        .long {v}, 0, {lab}, {hlp}" for v, lab, hlp in entries)
    recs = list(records) or [(0, 0, 0)]
    looks = looks or {}
    rtab = nl.join(f"        .long {PICK_BASE + i}, 0, {int(lab)}, {help_id}, {int(g)}, {int(c)}, "
                   f"{looks.get(int(c), (0, 0))[0]}, {looks.get(int(c), (0, 0))[1]}"
                   for i, (g, c, lab) in enumerate(recs))
    # swap ops for (looks n, from a, to b): two bytes each, table index n*9 + a*3 + b
    sw = []
    for n in range(4):
        for a in range(3):
            for b in range(3):
                ops = colour_swaps(n, a, b) if 2 <= n <= 3 and a < n and b < n else []
                sw.append(ops[0] if ops else 0)
                sw.append(ops[1] if len(ops) > 1 else 0)
    swtab = "        .byte " + ", ".join(str(x) for x in sw)
    own_sprites = sorted({int(x) for x in own_sprites})
    olist = nl.join(f"        .long {x}" for x in own_sprites) or "        .long 0"
    nrec = len(recs)
    faces = [(int(c), int(a)) for c, a in faces]
    flist = nl.join(f"        .long {c}, {a}" for c, a in faces) or "        .long 0, 0"
    # DRPG-K3: the graphics-id hook (anm_id_for_variant, 0x14021E9D0 in the known build) substitutes the class
    # id for a unit whose class is in this table.  That is right for an outfit whose own art is named after its
    # class id (face/banner/portrait at 10000+class, list icon keyed on the class id) -- every low outfit.  It is
    # WRONG for a declared DRPG costume: its class id is a lease number (30xxx) while its art is named after the
    # char row's colour (N), and the natives derive the graphics id from the row, not the class id
    # (anm_id_for_variant 0x14021F4A0 reads row+0xDE; the list-icon pick 0x1401A3010 is called with row+0xDE at
    # 0x140537232/0x140424917).  Such a look must fall through to the native computation, so only the entries
    # whose face animation is 10000+class go into the graphics table.  When every entry qualifies (every pack the
    # kit has built so far) the generated code is byte-identical: same table label, same count.
    gfx = [(c, a) for c, a in faces if a == 10000 + c] + [(int(c), int(a)) for c, a in gfx_ids]
    split = gfx != faces
    glist = nl.join(f"        .long {c}, {a}" for c, a in gfx) or "        .long 0, 0"
    gfx_lea = "[rip + gfx_map]" if split else "[rip + face_map]"
    gfx_n = len(gfx) if split else len(faces)
    gfx_tables = f"    gfx_map:{nl}{glist}{nl}" if split else ""
    from . import outfitapply
    own_save, own_call, own_code = outfitapply.src(own_masks or {})
    # Code conventions: every entry point keeps rsp 16-byte aligned at each call; rbx = the character
    # list scene in the dispatch / open hooks; edi = 0 in the dispatch (as the game's own code there).
    src = f"""
    dispatch:
        mov ecx, dword ptr [rbx+0xbdac]
        cmp ecx, dword ptr [rbx+0xbda0]
        jae d_value
        mov rax, qword ptr [rbx+0xbd98]
        test rax, rax
        je d_value
        mov edx, ecx
        shl rdx, 4
        mov ecx, dword ptr [rax+rdx]
    d_value:
        cmp ecx, {MENU_VALUE}
        je outfit_menu
        cmp ecx, {MORE_VALUE}
        je outfit_more
        cmp ecx, {PICK_BASE}
        jge outfit_pick
        test ecx, ecx
        je 0x140263454
        jmp 0x14026343c

    outfit_more:
        inc dword ptr [rip + outfit_page]
        jmp om_start
    outfit_menu:
        mov dword ptr [rip + outfit_page], 0
    om_start:
        push r12
        push r13
        push r14
        push r15
        sub rsp, 0x30
        call selected_unit
        mov r12, rax
        call find_group
        cmp eax, -1
        je om_close
        mov r13d, eax
        lea r14, [rip + outfit_records]
        xor edx, edx
        mov ecx, {nrec}
    om_count:
        cmp dword ptr [r14+16], r13d
        jne om_c1
        cmp dword ptr [r14+8], 0
        je om_c1
        inc edx
    om_c1:
        add r14, 32
        dec ecx
        jne om_count
        mov eax, dword ptr [rip + outfit_page]
        imul eax, eax, {OUTFIT_PAGE}
        cmp eax, edx
        jb om_pg_ok
        mov dword ptr [rip + outfit_page], 0
        xor eax, eax
    om_pg_ok:
        mov dword ptr [rsp+0x20], eax
        mov ecx, edx
        sub ecx, eax
        cmp ecx, {OUTFIT_PAGE}
        jbe om_pg_n
        mov ecx, {OUTFIT_PAGE}
    om_pg_n:
        mov dword ptr [rsp+0x24], ecx
        mov dword ptr [rsp+0x28], edx
        cmp edx, {OUTFIT_PAGE}
        jbe om_pg_init
        inc ecx
    om_pg_init:
        mov edx, ecx
        lea rcx, [rbx+0xbd98]
        call 0x1402b16b0
        lea r14, [rip + outfit_records]
        mov r15d, {nrec}
    om_add:
        cmp dword ptr [r14+16], r13d
        jne om_a1
        cmp dword ptr [r14+8], 0
        je om_a1
        cmp dword ptr [rsp+0x20], 0
        je om_take
        dec dword ptr [rsp+0x20]
        jmp om_a1
    om_take:
        cmp dword ptr [rsp+0x24], 0
        je om_a1
        dec dword ptr [rsp+0x24]
        mov rdx, r14
        lea rcx, [rbx+0xbd98]
        call 0x1402b0cb0
    om_a1:
        add r14, 32
        dec r15d
        jne om_add
        cmp dword ptr [rsp+0x28], {OUTFIT_PAGE}
        jbe om_show
        lea rdx, [rip + more_entry]
        lea rcx, [rbx+0xbd98]
        call 0x1402b0cb0
    om_show:
        lea rcx, [rbx+0xbd98]
        call 0x1402b09a0
        mov byte ptr [rbx+0xbdcc], 0
        add rsp, 0x30
        pop r15
        pop r14
        pop r13
        pop r12
        mov rbp, qword ptr [rsp+0x60]
        jmp 0x140263a5f
    om_close:
        add rsp, 0x30
        pop r15
        pop r14
        pop r13
        pop r12
        jmp back_to_list

    outfit_pick:
        push r12
        push r13
        push r14
        push r15
        sub rsp, 0x30
        sub ecx, {PICK_BASE}
        cmp ecx, {nrec}
        jae op_done
        mov r14d, ecx
        shl r14, 5
        lea rax, [rip + outfit_records]
        add r14, rax
        call selected_unit
        test rax, rax
        je op_done
        mov r12, rax
        call swap_colours{own_save}
        mov eax, dword ptr [r14+20]
        mov dword ptr [r12+0x2e04], eax
        mov rcx, r12
        call 0x14015eb80{own_call}
        lea r13, [rip + ACTORS_A]
        mov r14d, 512
        mov r15d, 0x3e0
        call refresh_actors
        lea r13, [rip + ACTORS_B]
        mov r14d, 256
        mov r15d, 0x1260
        call refresh_actors
        lea r13, [rip + LEADER]
        mov r14d, 1
        xor r15d, r15d
        call refresh_actors
    op_done:
        add rsp, 0x30
        pop r15
        pop r14
        pop r13
        pop r12
    back_to_list:
        mov byte ptr [rbx+0xbdcc], 0
        mov dword ptr [rbx+0xbdc8], edi
        mov rbp, qword ptr [rsp+0x60]
        jmp 0x1402634e9

    open_hook:
        push r12
        push r13
        sub rsp, 0x20
        call selected_unit
        mov r12, rax
        call find_group
        mov r13d, 3
        cmp eax, -1
        je oh_init
        mov r13d, 4
    oh_init:
        mov edx, r13d
        lea rcx, [rbx+0xbd98]
        call 0x1402b16b0
        lea r12, [rip + menu_entries]
    oh_add:
        mov rdx, r12
        lea rcx, [rbx+0xbd98]
        call 0x1402b0cb0
        add r12, 16
        dec r13d
        jne oh_add
        add rsp, 0x20
        pop r13
        pop r12
        lea rcx, [rbx+0xbd98]
        mov dword ptr [rbx+0xbdc8], 1
        jmp {OPEN_RET:#x}

    swap_colours:
        mov ecx, dword ptr [r12+0x2e04]
        lea r8, [rip + outfit_records]
        mov r9d, {nrec}
    sc_find:
        cmp dword ptr [r8+20], ecx
        je sc_found
        add r8, 32
        dec r9d
        jne sc_find
        ret
    sc_found:
        mov eax, dword ptr [r8+16]
        cmp eax, dword ptr [r14+16]
        jne sc_ret
        mov eax, dword ptr [r14+28]
        cmp eax, 3
        ja sc_runtime
        cmp eax, 2
        jb sc_ret
        mov ecx, dword ptr [r8+24]
        cmp ecx, 3
        jae sc_ret
        mov edx, dword ptr [r14+24]
        cmp edx, 3
        jae sc_ret
        imul eax, eax, 9
        imul ecx, ecx, 3
        add eax, ecx
        add eax, edx
        lea r8, [rip + swap_ops]
        movzx r10d, word ptr [r8+rax*2]
        movzx ecx, r10b
        call sc_op
        shr r10d, 8
        movzx ecx, r10b
        call sc_op
    sc_ret:
        ret
    sc_runtime:
        # more looks than the unit has colour sets: the kit's runtime keeps every look's colours
        # (d5looks.inc.c fills looks_cb at start-up; without the runtime the looks share the colours)
        mov rax, qword ptr [rip + looks_cb]
        test rax, rax
        je sc_ret
        sub rsp, 0x28
        mov rcx, r12
        mov edx, dword ptr [r12+0x2e04]
        mov r8d, dword ptr [r14+20]
        call rax
        add rsp, 0x28
        ret
    sc_op:
        test ecx, ecx
        je so_ret
        lea r8, [r12+0x35c4]
        lea r9, [r12+0x3a44]
        cmp ecx, 1
        je so_go
        lea r9, [r12+0x3ec4]
        cmp ecx, 2
        je so_go
        lea r8, [r12+0x3a44]
    so_go:
        mov edx, 0x90
    so_loop:
        mov rax, qword ptr [r8]
        mov r11, qword ptr [r9]
        mov qword ptr [r8], r11
        mov qword ptr [r9], rax
        add r8, 8
        add r9, 8
        dec edx
        jne so_loop
    so_ret:
        ret

    selected_unit:
        sub rsp, 0x28
        lea rcx, [rbx+0x80]
        call 0x1400928d0
        test rax, rax
        je su_ret
        mov rax, qword ptr [rax]
    su_ret:
        add rsp, 0x28
        ret

    find_group:
        mov eax, -1
        test r12, r12
        je fg_ret
        mov ecx, dword ptr [r12+0x2e04]
        lea r8, [rip + outfit_records]
        mov r9d, {nrec}
    fg_loop:
        cmp dword ptr [r8+20], ecx
        je fg_hit
        add r8, 32
        dec r9d
        jne fg_loop
        ret
    fg_hit:
        mov eax, dword ptr [r8+16]
    fg_ret:
        ret

    refresh_actors:
        sub rsp, 0x38
    ra_loop:
        cmp qword ptr [r13+0x240], r12
        jne ra_next
        cmp qword ptr [r13+0x1d0], 0
        je ra_next
        mov rcx, r13
        mov edx, dword ptr [r12+0x2e04]
        movzx r8d, byte ptr [r12+0x2e2c]
        xor r9d, r9d
        mov dword ptr [rsp+0x20], 0
        call 0x14014dc60
    ra_next:
        add r13, r15
        dec r14d
        jne ra_loop
        add rsp, 0x38
        ret

    hub_compare:
        mov ecx, dword ptr [rax+0x2e04]
        cmp ecx, dword ptr [r14+0x258]
        je hc_done
        cmp dword ptr [r14+0x258], 0x1f4
        jne hc_diff
        cmp ecx, 0x28
        je hc_done
    hc_diff:
        mov ecx, dword ptr [r14+0x258]
    hc_done:
        jmp {HUB_RET:#x}

    face_a:
        lea edx, [rcx+0x2710]
        mov r10, qword ptr [rbx+0x90]
        call face_remap
        jmp {FACE_A_RET:#x}

    face_b:
        lea edx, [rax+r10]
        mov r10, r12
        call face_remap
        xor r9d, r9d
        xor r8d, r8d
        jmp {FACE_B_RET:#x}

    gfx_hook:{_gfx_src(gfx_lea, gfx_n, gfx)}

    face_remap:
        test r10, r10
        je fr_ret
        mov r11d, dword ptr [r10+0x2e04]
        lea r10, [rip + face_map]
        push rcx
        mov ecx, {max(1, len(faces))}
    fr_loop:
        cmp dword ptr [r10], r11d
        je fr_hit
        add r10, 8
        dec ecx
        jne fr_loop
        pop rcx
        ret
    fr_hit:
        mov edx, dword ptr [r10+4]
        pop rcx
    fr_ret:
        ret

    layer_block:
        cwde
        mov ecx, 1
        cmp eax, 0xa
        cmovl ecx, eax
        lea r10, [rip + own_sprites]
        mov r11d, {len(own_sprites)}
    own_loop:
        test r11d, r11d
        je own_done
        cmp eax, dword ptr [r10]
        je own_hit
        add r10, 4
        dec r11d
        jmp own_loop
    own_hit:
        mov ecx, eax
    own_done:
        jmp {LAYER_RET:#x}
        int3
        int3
        int3
        int3
    menu_entries:
{table}
    more_entry:
        .long {MORE_VALUE}, 0, {more_label}, {help_id}
    outfit_records:
{rtab}
    swap_ops:
{swtab}
        .align 4
    own_sprites:
{olist}
    face_map:
{flist}
        .align 8
{gfx_tables}    looks_marker:
        .byte 0x44, 0x35, 0x4c, 0x4f, 0x4f, 0x4b, 0x43, 0x42
    looks_cb:
        .quad 0
    outfit_page:
        .long 0{own_code}
    ACTORS_A = {ACTORS_A:#x}
    ACTORS_B = {ACTORS_B:#x}
    LEADER = {LEADER:#x}
    """
    code_va = base
    code = _asm(src, code_va)
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    labels = {}
    insns = list(Cs(CS_ARCH_X86, CS_MODE_64).disasm(code, code_va))
    # locate entry points by their first instruction (keystone doesn't return symbol addresses)
    labels["dispatch"] = code_va
    for k, ins in enumerate(insns):
        if "open" not in labels and ins.mnemonic == "push" and ins.op_str == "r12" and k + 2 < len(insns) \
                and insns[k + 1].op_str == "r13" and insns[k + 2].op_str == "rsp, 0x20":
            labels["open"] = ins.address
        if ins.mnemonic == "cmp" and ins.op_str == "ecx, dword ptr [r14 + 0x258]" and "hub" not in labels:
            labels["hub"] = insns[k - 1].address
        if ins.mnemonic == "cwde" and "layer" not in labels:
            labels["layer"] = ins.address
        if ins.mnemonic == "lea" and ins.op_str == "edx, [rcx + 0x2710]" and "face_a" not in labels:
            labels["face_a"] = ins.address
        if ins.mnemonic == "lea" and ins.op_str == "edx, [rax + r10]" and "face_b" not in labels:
            labels["face_b"] = ins.address
        nf = max(1, gfx_n)
        if ins.mnemonic == "mov" and ins.op_str in ("r11d, " + str(nf), "r11d, " + hex(nf)) and "gfx" not in labels                 and insns[k - 1].mnemonic == "lea":
            labels["gfx"] = insns[k - 1].address
    if len(labels) != 7:
        raise RuntimeError(f"could not locate entry points in assembled code: {labels}")
    patches = [(at[DISPATCH_VA], DISPATCH_ORIG, labels["dispatch"], 0xE9),
               (at[OPEN_VA], OPEN_ORIG, labels["open"], 0xE9),
               (at[HUB_VA], HUB_ORIG, labels["hub"], 0xE9)]
    if own_sprites:
        patches.append((at[LAYER_VA], LAYER_ORIG, labels["layer"], 0xE9))
    if faces:
        patches += [(at[FACE_A_VA], FACE_A_ORIG, labels["face_a"], 0xE9),
                    (at[FACE_B_VA], FACE_B_ORIG, labels["face_b"], 0xE9)]
    if gfx:
        patches.append((at[GFX_VA], GFX_ORIG, labels["gfx"], 0xE9))
    # writable: the outfit list page lives in the section
    return add_code_section(exe, SECTION_NAME, code, patches, writable=True)
