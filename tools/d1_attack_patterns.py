#!/usr/bin/env python3
"""D1SCRIPT1: Disgaea 1's skill area shapes, read by running the game's own table builder (offline).

Disgaea 1 keeps a skill's reach and area outside magic.dat's text: the row's `pattern` byte (d1skill) picks one of
82 cell lists that the executable BUILDS IN CODE at start-up (no data file holds them), and the `range` byte is the
cursor distance for the 13 rows whose pattern is a centred shape.

    Disgaea PC   dis1_st.exe  FUN_004430d0  -> cells 0x664780 (3 bytes: i8 x, i8 y, u8 kind), first/end u16 index
                                               0x664d80 / 0x664e40, count 0x664f00
    D1 Complete  Switch main  FUN_7100012ea4 (same builder, one struct: cells +0, first +0x600, end +0x6c0, count +0x780)

The game picks entry `pattern - 1` (0 = spell: the area comes from the spell level instead), cursor range = the
row's range byte, heights = up / down (PC FUN_0044a3b0 / FUN_004cd5c0; D1C FUN_710001d338 / FUN_71000afde0).
Cells are D5's AttackMap convention (x sideways, y forward; kind 1 hit, 2 caster ends here, 3 cursor panel), checked
on the shared skills: Triple Strike = D5 1100, Overlord's Wrath / Soaring Fire = 5003, Rose Liberation = range 4 + 5.

    python tools/d1_attack_patterns.py            emulate the PC exe in Disgaea Source, compare with the table
    python tools/d1_attack_patterns.py --write    ... and (re)write d5lib/importers/d1-attack-patterns.json
    python tools/d1_attack_patterns.py --switch-main PATH   also emulate the D1C Switch main NSO and compare

Unicorn (installed in the kit venv) runs only the builder function; memset is the one call it makes.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "d5lib/importers/d1-attack-patterns.json"
PC_EXE = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 1 PC (Steam 405900)/Disgaea PC/dis1_st.exe")


def _decode(mem, cells, first, end, count):
    n = struct.unpack_from("<I", mem(count, 4))[0]
    st = struct.unpack_from(f"<{n}h", mem(first, 2 * n))
    en = struct.unpack_from(f"<{n}h", mem(end, 2 * n))
    raw = mem(cells, 0x600)
    return {i + 1: [list(struct.unpack_from("<bbB", raw, c * 3)) for c in range(st[i], en[i])] for i in range(n)}


def pc(exe=PC_EXE):
    import pefile
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP
    pe = pefile.PE(str(exe))
    base = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(base, (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF)
    for s in pe.sections:
        mu.mem_write(base + s.VirtualAddress, s.get_data())
    stub, imports = 0x10000000, {}
    mu.mem_map(stub, 0x10000)
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        for i in e.imports:
            a = stub + 4 * len(imports)
            imports[a] = i.name
            mu.mem_write(i.address, struct.pack("<I", a))
    mu.mem_map(0x20000000, 0x100000)
    mu.mem_map(0x30000000, 0x1000)
    mu.mem_write(0x20080000, struct.pack("<I", 0x30000000))
    mu.reg_write(UC_X86_REG_ESP, 0x20080000)

    def hook(uc, addr, size, _):
        if imports.get(addr) != b"memset":
            raise RuntimeError(f"builder called import {imports.get(addr)!r}")
        sp = uc.reg_read(UC_X86_REG_ESP)
        ret, dst, val, n = struct.unpack("<4I", uc.mem_read(sp, 16))
        uc.mem_write(dst, bytes([val & 0xFF]) * n)
        uc.reg_write(UC_X86_REG_EAX, dst)
        uc.reg_write(UC_X86_REG_ESP, sp + 4)
        uc.reg_write(UC_X86_REG_EIP, ret)
    mu.hook_add(UC_HOOK_CODE, hook, begin=stub, end=stub + 0xFFFF)
    mu.emu_start(0x004430D0, 0x30000000, count=5_000_000)
    return _decode(lambda a, n: bytes(mu.mem_read(a, n)), 0x664780, 0x664D80, 0x664E40, 0x664F00)


def _nso_image(path):
    """NSO0 -> flat image (segments at their memory offsets; LZ4 block decoder inline, stdlib only)."""
    d = Path(path).read_bytes()
    if d[:4] != b"NSO0":
        raise ValueError("not an NSO")
    flags, segs = struct.unpack_from("<I", d, 0xC)[0], []
    for i in range(3):
        foff, moff, size = struct.unpack_from("<III", d, 0x10 + i * 0x10)
        raw = d[foff:foff + struct.unpack_from("<I", d, 0x60 + i * 4)[0]]
        segs.append((moff, _lz4(raw, size) if flags & (1 << i) else raw))
    img = bytearray(max(m + len(r) for m, r in segs))
    for m, r in segs:
        img[m:m + len(r)] = r
    return bytes(img)


def _lz4(src, size):
    out, i = bytearray(), 0
    while i < len(src):
        t = src[i]; i += 1
        n = t >> 4
        if n == 15:
            while True:
                b = src[i]; i += 1; n += b
                if b != 255:
                    break
        out += src[i:i + n]; i += n
        if i >= len(src):
            break
        off = src[i] | src[i + 1] << 8; i += 2
        m = t & 15
        if m == 15:
            while True:
                b = src[i]; i += 1; m += b
                if b != 255:
                    break
        for _ in range(m + 4):
            out.append(out[-off])
    if len(out) != size:
        raise ValueError("LZ4 segment size mismatch")
    return bytes(out)


def switch(main_nso):
    from unicorn import UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM, Uc
    from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_SP, UC_ARM64_REG_X0, \
        UC_ARM64_REG_X1, UC_ARM64_REG_X2
    img, base, fn, out = _nso_image(main_nso), 0x7100000000, 0x7100012EA4, 0x40000000
    mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    mu.mem_map(base, (len(img) + 0x400000 + 0xFFF) & ~0xFFF)
    mu.mem_write(base, img)
    for a in (0x20000000, out):
        mu.mem_map(a, 0x100000)
    mu.mem_map(0x30000000, 0x1000)
    mu.reg_write(UC_ARM64_REG_SP, 0x20080000)
    mu.reg_write(UC_ARM64_REG_LR, 0x30000000)
    mu.reg_write(UC_ARM64_REG_X0, out)

    def hook(uc, addr, size, _):
        if addr in (0x710015A700, 0x7100A63000):     # memset thunks
            uc.mem_write(uc.reg_read(UC_ARM64_REG_X0), bytes([uc.reg_read(UC_ARM64_REG_X1) & 0xFF])
                         * uc.reg_read(UC_ARM64_REG_X2))
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif not fn <= addr < fn + 5920:
            raise RuntimeError(f"builder left its body at {addr:#x}")
    mu.hook_add(UC_HOOK_CODE, hook)
    mu.emu_start(fn, 0x30000000, count=5_000_000)
    return _decode(lambda a, n: bytes(mu.mem_read(out + a, n)), 0, 0x600, 0x6C0, 0x780), \
        hashlib.sha256(Path(main_nso).read_bytes()).hexdigest()


def main(argv):
    got = pc()
    exe_sha = hashlib.sha256(PC_EXE.read_bytes()).hexdigest()
    ok = True
    if "--switch-main" in argv:
        sw, sw_sha = switch(argv[argv.index("--switch-main") + 1])
        same = sw == got
        ok &= same
        print(f"D1 Complete Switch main ({sw_sha[:12]}): {len(sw)} patterns, identical to the PC build: {same}")
    doc = dict(
        schema="d1-attack-patterns/1",
        about="Disgaea 1 skill area shapes: key = magic.dat pattern byte (the game uses entry byte-1; 0 = spell, "
              "no entry). Cells [x sideways, y forward, kind 1 hit / 2 caster ends here / 3 cursor panel], D5 "
              "AttackMap convention. Built by tools/d1_attack_patterns.py from the game's own builder code.",
        source=dict(pc_exe="Disgaea Source/Disgaea 1 PC (Steam 405900)/Disgaea PC/dis1_st.exe", pc_exe_sha256=exe_sha,
                    pc_function="0x004430d0", d1c_function="Switch main 0x7100012ea4 (same output, checked)"),
        patterns={str(k): v for k, v in got.items()})
    if "--write" in argv:
        TABLE.write_text(json.dumps(doc, indent=0, separators=(",", ":")) + "\n")
        print(f"wrote {TABLE} ({len(got)} patterns)")
    else:
        have = json.loads(TABLE.read_text())["patterns"]
        same = have == doc["patterns"]
        ok &= same
        print(f"PC exe {exe_sha[:12]}: {len(got)} patterns, matches {TABLE.name}: {same}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
