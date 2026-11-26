"""PAGECRASH1: a sprite draw packet with a NULL texture is skipped by anm_flush_draw_packets, proved offline.

The game's own code runs in Unicorn: emulation starts AT anm_render_all_owners' real `call anm_flush_draw_packets`
(caller rsp % 16 == 0) in the pinned exe, patched by d5lib.anmguard (the installer's path), and runs the whole flush:
its prologue, its loop over the packet vector (DAT_140b9a928), its epilogue, back to the caller.  The two callees are
stubs that clobber every volatile register: anm_sort_draw_depth_stable (returns), sprite_queue_draw_command (records
its register and stack arguments and the render state word, returns).

  normal   texture-bearing packets: the patched exe makes the same calls with the same arguments and state word as
           the unpatched one, and leaves the same state word.
  null     a NULL texture first / between / last / only: no fault, every other packet is queued exactly as in the
           normal run of the same packets, nothing is queued for the NULL one, the state word is restored, and the
           skip counter (anmguard.counter_va) counts the NULL packets (0 in the normal runs).
  control  the unpatched exe on a NULL packet faults reading 0x24 at 0x1402F3744 (the FREEZECATCH1 crash).
  --abi    adds: rbx rbp rsi rdi r12-r15 and xmm6-15 unchanged at the return, rsp back at the caller's value, every
           callee entered with rsp % 16 == 8, and the patched run writes the same stack bytes as the unpatched one
           (normal case) -- the hook's only memory write is its own counter, in .d5ag.

    python -m pytest tests/test_pagecrash1.py -q
    python tests/test_pagecrash1.py [--abi]        (prints the results; exit 1 on a failed check)
"""
import json
import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from d5lib import anmguard, exemap, exepatch      # noqa: E402

EXE = ("/Volumes/Data/Projects/D5/D5ModKit/state/games/"
       "Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
RENDER_ALL = 0x140301FE0            # anm_render_all_owners (pinned build = the decomp's)
FLUSH = 0x1402F3650                 # anm_flush_draw_packets
SORT = 0x1400A31A0                  # anm_sort_draw_depth_stable
QUEUE = 0x14030F7B0                 # sprite_queue_draw_command
PACKETS = 0x140B9A928               # DAT_140b9a928: -> {begin, end, cap}
STATE = 0x147B55BF0                 # render_state_word (rdi at 0x1402F369D)
FAULT = 0x1402F3744
HEAP = 0x10000000
STACK = 0x7FF000
STATE0 = 0x1122334455667788
need_exe = pytest.mark.skipif(not os.path.exists(EXE), reason="pinned game exe not present")
VOLATILE = ("RAX", "RCX", "RDX", "R8", "R9", "R10", "R11")
NONVOL = dict(RBX=0x1111, RBP=0x2222, RSI=0x3333, RDI=0x4444, R12=0x5555, R13=0x6666, R14=0x7777, R15=0x8888)


def exes():
    data = open(EXE, "rb").read()
    old = exemap.ACTIVE
    exemap.use(exemap.translator_for(data))
    try:
        return data, anmguard.patch(data, log=lambda *a: None)
    finally:
        exemap.use(old)


def _call_site(ex):
    code = ex.read(RENDER_ALL - ex.base, 200)
    for k in range(len(code) - 5):
        if code[k] == 0xE8 and RENDER_ALL + k + 5 + struct.unpack_from("<i", code, k + 1)[0] == FLUSH:
            return RENDER_ALL + k
    raise AssertionError("anm_render_all_owners does not call anm_flush_draw_packets")


def run_flush(exe, textures, abi=False):
    """textures: per packet, None (NULL texture) or the texture's format byte (+0x24).  -> result dict"""
    import unicorn_darwin_shim                                   # noqa: F401  (Darwin/ARM64 CTR_EL0)
    unicorn_darwin_shim.install()
    from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED
    from unicorn import x86_const as X

    ex = exemap.Exe(exe)
    image_end = ex.base + max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in ex.pe.sections)
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    mapped = set()

    def map_image_page(page):
        if page in mapped:
            return
        mu.mem_map(page, 0x1000)
        try:
            mu.mem_write(page, ex.read(page - ex.base, 0x1000).ljust(0x1000, b"\0"))
        except Exception:                                        # noqa: BLE001  (bss: zero)
            pass
        mapped.add(page)

    faults = []

    def unmapped(u, access, addr, size, value, data):
        if ex.base <= addr < image_end:
            map_image_page(addr & ~0xFFF)
            if addr + size > (addr & ~0xFFF) + 0x1000:
                map_image_page((addr & ~0xFFF) + 0x1000)
            return True
        faults.append(dict(rip=hex(u.reg_read(X.UC_X86_REG_RIP)), addr=hex(addr)))
        return False

    mu.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, unmapped)
    mu.mem_map(HEAP, 0x10000)
    mu.mem_map(STACK - 0x4000, 0x5000)
    # textures (0x58-byte pool objects: +0x20 width, +0x22 height, +0x24 format) and 200-byte packets
    texs = []
    for i, fmt in enumerate(textures):
        if fmt is None:
            texs.append(0)
            continue
        t = HEAP + 0x100 + i * 0x60
        mu.mem_write(t, bytes(0x58))
        mu.mem_write(t + 0x20, struct.pack("<HHB", 256, 512, fmt))
        texs.append(t)
    pk0 = HEAP + 0x1000
    for i, t in enumerate(texs):
        p = bytearray(200)
        struct.pack_into("<ff", p, 4, 1.0 / 256, 1.0 / 512)     # +4/+8 uv scale
        struct.pack_into("<hhhh", p, 0x14, 10 + i, 20 + i, 30 + i, 40 + i)
        p[0x1C], p[0x1E], p[0xC0] = 1, i, 0                    # kind, depth (sort is stubbed), blend bits
        struct.pack_into("<QQ", p, 0x20, t, 0xBEEF00 + i)       # texture, palette
        struct.pack_into("<IHHIII", p, 0xA8, 7, 3, 0, 1, 2, 0)  # +0xa8 material, +0xac, +0xb0, +0xb4
        mu.mem_write(pk0 + i * 200, bytes(p))
    vec = HEAP + 0x40
    mu.mem_write(vec, struct.pack("<QQQ", pk0, pk0 + 200 * len(texs), pk0 + 200 * 64))
    owner = HEAP + 0x8000
    mu.mem_write(owner, bytes(0x400))
    for va, val in ((PACKETS, struct.pack("<Q", vec)), (STATE, struct.pack("<Q", STATE0))):
        map_image_page(va & ~0xFFF)
        mu.mem_write(va, val)

    call = _call_site(ex)
    ret = call + 5
    rsp0 = STACK - 0x200                                         # caller rsp % 16 == 0 before its CALL
    mu.reg_write(X.UC_X86_REG_RSP, rsp0)
    mu.reg_write(X.UC_X86_REG_RCX, owner)
    for k, v in NONVOL.items():
        mu.reg_write(getattr(X, "UC_X86_REG_" + k), v)
    xmm = {i: 0x0123456789ABCDEF0000000000000000 + i for i in range(6, 16)}
    for i, v in xmm.items():
        mu.reg_write(getattr(X, f"UC_X86_REG_XMM{i}"), v)
    calls, entry_mod, writes = [], [], []

    def stub_ret(u, junk):
        rsp = u.reg_read(X.UC_X86_REG_RSP)
        entry_mod.append(rsp % 16)
        for n, r in enumerate(VOLATILE):                         # a real callee clobbers these
            u.reg_write(getattr(X, "UC_X86_REG_" + r), junk + n)
        u.reg_write(X.UC_X86_REG_RIP, struct.unpack("<Q", u.mem_read(rsp, 8))[0])
        u.reg_write(X.UC_X86_REG_RSP, rsp + 8)

    def code(u, a, size, data):
        if a == SORT:
            stub_ret(u, 0xA0A0)
        elif a == QUEUE:
            rsp = u.reg_read(X.UC_X86_REG_RSP)
            stack = struct.unpack("<12Q", u.mem_read(rsp + 0x28, 0x60))      # args 5..16
            calls.append(dict(rcx=u.reg_read(X.UC_X86_REG_RCX), rdx=u.reg_read(X.UC_X86_REG_RDX),
                              xmm2=u.reg_read(X.UC_X86_REG_XMM2) & 0xFFFFFFFF,
                              xmm3=u.reg_read(X.UC_X86_REG_XMM3) & 0xFFFFFFFF,
                              stack=[hex(x) for x in stack],
                              state=struct.unpack("<Q", u.mem_read(STATE, 8))[0]))
            stub_ret(u, 0xB0B0)
        elif a == ret:
            u.emu_stop()

    mu.hook_add(UC_HOOK_CODE, code)
    mu.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size, val, d:
                writes.append((addr, size, val)) if STACK - 0x4000 <= addr < STACK + 0x1000 else None)
    err = None
    try:
        mu.emu_start(call, 0, count=20000)
    except UcError as e:
        err = str(e)
    rip = mu.reg_read(X.UC_X86_REG_RIP)
    cva = anmguard.counter_va(exe)
    if cva is not None:
        map_image_page(cva & ~0xFFF)
    out = dict(skips=struct.unpack("<I", mu.mem_read(cva, 4))[0] if cva else None, packets=["NULL" if t is None else t for t in textures], returned=rip == ret and err is None,
               error=err, faults=faults, calls=calls,
               queued=[(c["rcx"] - 0x80 - pk0) // 200 for c in calls],
               state_restored=struct.unpack("<Q", mu.mem_read(STATE, 8))[0] == STATE0)
    if abi:
        out["nonvolatile_ok"] = all(mu.reg_read(getattr(X, "UC_X86_REG_" + k)) == v for k, v in NONVOL.items()) \
            and all(mu.reg_read(getattr(X, f"UC_X86_REG_XMM{i}")) == v for i, v in xmm.items())
        out["rsp_ok"] = mu.reg_read(X.UC_X86_REG_RSP) == rsp0
        out["callee_entry_mod16"] = sorted(set(entry_mod))
        out["stack_writes"] = writes
    return out


NULL_CASES = [[9, None, 0], [None, 9, 0], [9, 0, None], [None], [None, None], [0, None, 9, None, 0]]


def _strip(c):
    return {k: v for k, v in c.items() if k != "stack_writes"}


def check_normal(orig, patched, abi):
    for texs in ([9, 0], [0, 9, 0, 9]):
        a, b = run_flush(orig, texs, abi), run_flush(patched, texs, abi)
        assert a["returned"] and b["returned"], (a, b)
        assert b["calls"] == a["calls"] and b["queued"] == list(range(len(texs))) and b["skips"] == 0, (a, b)
        assert a["state_restored"] and b["state_restored"], (a, b)
        if abi:
            for r in (a, b):
                assert r["nonvolatile_ok"] and r["rsp_ok"] and r["callee_entry_mod16"] == [8], _strip(r)
            assert b["stack_writes"] == a["stack_writes"], "the hook changed the stack writes"


def check_null(orig, patched, texs, abi):
    r = run_flush(patched, texs, abi)
    want = [i for i, t in enumerate(texs) if t is not None]
    assert r["returned"] and not r["faults"], _strip(r)
    assert r["queued"] == want and r["state_restored"] and r["skips"] == len(texs) - len(want), _strip(r)
    # each queued packet exactly as in a run of the same packet with a texture everywhere
    full = run_flush(orig, [9 if t is None else t for t in texs])
    assert r["calls"] == [full["calls"][i] for i in want], _strip(r)
    if abi:
        assert r["nonvolatile_ok"] and r["rsp_ok"], _strip(r)
        assert r["callee_entry_mod16"] in ([8], []), _strip(r)
    return r


def check_control(orig):
    r = run_flush(orig, [9, None, 0])
    assert not r["returned"] and r["faults"] == [dict(rip=hex(FAULT), addr="0x24")], _strip(r)
    return r


@need_exe
def test_negative_control_unpatched_faults_at_the_freezecatch_address():
    check_control(exes()[0])


@need_exe
@pytest.mark.parametrize("abi", [False, True], ids=["normal", "abi"])
def test_texture_packets_unchanged(abi):
    check_normal(*exes(), abi)


@need_exe
@pytest.mark.parametrize("abi", [False, True], ids=["normal", "abi"])
@pytest.mark.parametrize("texs", NULL_CASES, ids=lambda t: "-".join("N" if x is None else str(x) for x in t))
def test_null_packet_is_skipped(texs, abi):
    check_null(*exes(), texs, abi)


@need_exe
def test_hook_is_a_leaf_and_lands_where_it_should():
    """Static audit + payload: 10 site bytes = jmp .d5ag + 5 nops; the hook has no push/pop/call/rsp and leaves only
    for the original je target, the fall-through and the loop tail; nothing else in the image changed."""
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    orig, patched = exes()
    site, je, fall, tail = anmguard.find_site(orig)
    assert (site, je, fall, tail) == (0x1402F3740, 0x1402F3767, 0x1402F374A, 0x1402F38A8)
    ex, ox = exemap.Exe(patched), exemap.Exe(orig)
    raw = ex.read(site - ex.base, 10)
    assert raw[0] == 0xE9 and raw[5:] == b"\x90" * 5, raw.hex()
    hook = site + 5 + struct.unpack("<i", raw[1:5])[0]
    sec = [s for s in ex.pe.sections if s.Name.rstrip(b"\0") == b".d5ag"]
    assert sec and ex.base + sec[0].VirtualAddress <= hook < ex.base + sec[0].VirtualAddress + sec[0].Misc_VirtualSize
    assert exepatch.has_feature(patched, anmguard.SECTION)
    ops = list(Cs(CS_ARCH_X86, CS_MODE_64).disasm(ex.read(hook - ex.base, 0x40), hook))[:8]
    assert [(i.mnemonic, i.op_str) for i in ops[:4]] == [
        ("mov", "rax, qword ptr [rbx + 0x20]"), ("test", "rax, rax"), ("je", hex(ops[6].address)),
        ("cmp", "byte ptr [rax + 0x24], 9")]
    assert [(i.mnemonic, int(i.op_str, 16)) for i in ops[4:6]] == [("je", je), ("jmp", fall)]
    assert ops[6].mnemonic.endswith("inc") and ops[6].op_str.startswith("dword ptr [rip") and ops[6].bytes[0] == 0xF0
    assert (ops[7].mnemonic, int(ops[7].op_str, 16)) == ("jmp", tail)
    cva = anmguard.counter_va(patched)
    assert ops[7].address < cva < ex.base + sec[0].VirtualAddress + sec[0].Misc_VirtualSize and ex.read(cva - ex.base, 4) == bytes(4)
    assert sec[0].Characteristics & 0x80000000                              # writable, for the counter
    assert not any(i.mnemonic in ("push", "pop", "call", "ret", "leave") or "rsp" in i.op_str for i in ops)
    # every byte of the original sections is unchanged except the 10 at the site
    for s in ox.pe.sections:
        a = orig[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        b = patched[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        diff = [s.VirtualAddress + k for k in range(len(a)) if a[k] != b[k]]
        if diff:
            assert s.Name.startswith(b".text") and diff == [site - ex.base + k for k in range(len(diff))] \
                and len(diff) <= 10, (s.Name, [hex(d) for d in diff[:20]])
    assert anmguard.patch(patched, log=lambda *a: None) == patched          # applying twice changes nothing


if __name__ == "__main__":
    abi = "--abi" in sys.argv
    orig, patched = exes()
    results, ok = [], True

    def run(name, fn, *a):
        global ok
        try:
            r = fn(*a)
            results.append(dict(case=name, verdict="PASS", **({} if r is None else
                                {k: v for k, v in r.items() if k in ("queued", "faults", "state_restored", "skips")})))
        except AssertionError as e:
            ok = False
            results.append(dict(case=name, verdict="FAIL", why=str(e)[:600]))
    run("control: unpatched + NULL faults at 0x1402F3744", check_control, orig)
    run("normal packets unchanged", check_normal, orig, patched, abi)
    for texs in NULL_CASES:
        run(f"null {texs}", check_null, orig, patched, texs, abi)
    run("static + payload", test_hook_is_a_leaf_and_lands_where_it_should)
    print(json.dumps(dict(abi=abi, results=results), indent=1, default=str))
    sys.exit(0 if ok else 1)
