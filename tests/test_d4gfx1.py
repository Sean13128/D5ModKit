"""D4-GFX1: a registry unique gets its own graphics id, proved offline.

anm_id_for_variant (pinned 0x14021F4A0, known build 0x14021E9D0) returns palette + colour / 10 * 10 for a class id
> 999, so Pringer X (class 10260, colour 643) got 640 = Mao's.  The Kit's graphics-id hook now returns
(second word - 10000) for a table entry; outfits._finalize puts (class, 10000 + colour) there for every registry
unique whose colour does not end in 0, with or without outfits.

Site proofs enter the hook the way the game does: emulation starts AT a real `call anm_id_for_variant` instruction of
unit_construct (pinned 0x14021B510) in the patched pinned exe, with the caller's rsp % 16 == 0.  --abi adds: every
non-volatile register (rbx rbp rsi rdi r12-r15, xmm6-15) unchanged at the return, rsp back at the caller's value,
no memory write on the hit path, and on the miss path only the original prologue's own `mov [rsp+8], rbx`, with
rcx/rdx untouched when the original body resumes at site + 5.

    python -m pytest tests/test_d4gfx1.py -q
    python tests/test_d4gfx1.py [--abi]        (prints the site results; exit 1 on a failed check)
"""
import json
import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from d5lib import exemap, exepatch, importcore, outfits      # noqa: E402

EXE = ("/Volumes/Data/Projects/D5/D5ModKit/state/games/"
       "Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
SOURCE = "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)"
HELD = "/Volumes/Data/Projects/D5/Builds/D4CELL1-20261109/d4/mods"
UNIT_CONSTRUCT = 0x14021B510            # pinned build; calls anm_id_for_variant(class, row tier)
U210 = [(10260, 10643)]
LOW_FACES = [(470, 10470), (480, 10480)]
LOW_RECORDS = [(0, 470, 1001), (0, 480, 1002)]
need_exe = pytest.mark.skipif(not os.path.exists(EXE), reason="pinned game exe not present")


# ----------------------------------------------------------------------------------------------- data rules
def test_gfx_of_reproduces_the_live_reads():
    assert importcore.gfx_of(10260, 643, 0) == 640      # Pringer X, D4RECRUIT1/D4FREEZE2 read 640
    assert importcore.gfx_of(10, 10, 0) == 10            # Killia
    assert importcore.gfx_of(102, 102, 0) == 102         # Zed (DRPG-K6)
    assert importcore.gfx_of(1013, 1013, 3) == 1013      # a generic rank: tier is the palette


def test_registry_gfx_takes_high_ids_off_the_decade_only():
    rows = {10260: {"color_id": 643}, 10270: {"color_id": 940}, 470: {"color_id": 473}}
    assert outfits.registry_gfx({10260: 2020, 10270: 2020, 470: None}, rows) == [(10260, 10643)]


def _mod(tmp_path, cid, colour, physical=None):
    (tmp_path / "patches/db").mkdir(parents=True)
    (tmp_path / "patches/db/char.dat.json").write_text(json.dumps(
        {"table": "char.dat", "added": [{"id": cid, "color_id": colour, "sprite_id": colour, "tier": 0}]}))
    if physical is not None:
        (tmp_path / "patches/characters").mkdir(parents=True)
        (tmp_path / "patches/characters/unique.json").write_text(json.dumps(
            {"identity": cid, "physical": physical, "template": 2020, "template_colour": 2020}))
    return tmp_path


def test_gate_fails_an_uncovered_row_and_passes_a_registry_unique(tmp_path):
    undeclared = _mod(tmp_path / "a", 10260, 643)
    ok, why = importcore.gfx_contract(undeclared, {640: "Mao"})
    assert not ok and why == "10260: colour 643 -> graphics 640 (Mao)"
    declared = _mod(tmp_path / "b", 10260, 643, physical=643)
    assert importcore.gfx_contract(declared, {640: "Mao"}, covered=set())[0] is False   # the Kit before D4-GFX1
    assert importcore.gfx_contract(declared, {640: "Mao"}) == (True, "")


@pytest.mark.skipif(not os.path.isdir(HELD + "/D4_Unique_210"), reason="held D4CELL1 build not present")
def test_gate_on_the_held_pringer_x():
    ok, why = importcore.gfx_contract(HELD + "/D4_Unique_210", {640: "Mao"}, covered=set())
    assert not ok and why == "10260: colour 643 -> graphics 640 (Mao)"
    assert importcore.gfx_contract(HELD + "/D4_Unique_210", {640: "Mao"}) == (True, "")


# ----------------------------------------------------------------------------------------------- site proofs
def _patched(kind):
    data = open(EXE, "rb").read()
    exemap.use(exemap.translator_for(data))
    if kind == "alone":
        return exepatch.build_gfx_patch(data, U210)
    return exepatch.build_outfit_patch(data, LOW_RECORDS, 40001, 40002, faces=LOW_FACES, gfx_ids=U210)


def _call_site(ex, site):
    """the first `call site` (E8 rel32) in unit_construct"""
    code = ex.read(UNIT_CONSTRUCT - ex.base, 0x1000)
    for k in range(len(code) - 5):
        if code[k] == 0xE8 and UNIT_CONSTRUCT + k + 5 + struct.unpack_from("<i", code, k + 1)[0] == site:
            return UNIT_CONSTRUCT + k
    raise AssertionError("unit_construct does not call anm_id_for_variant")


def run_site(exe, cls, abi=False):
    """Emulate the game's own `call anm_id_for_variant` with ecx = cls, edx = 0 -> result dict"""
    import unicorn_darwin_shim                                   # noqa: F401  (Darwin/ARM64 CTR_EL0)
    unicorn_darwin_shim.install()
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import x86_const as X

    ex = exemap.Exe(exe)
    site = exemap.ACTIVE(0x14021E9D0)
    raw = ex.read(site - ex.base, 5)
    assert raw[0] == 0xE9, f"graphics site is not redirected: {raw.hex()}"
    hook = site + 5 + struct.unpack("<i", raw[1:])[0]
    call = _call_site(ex, site)
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    for va, n in ((call, 0x20), (site, 0x20), (hook, 0x400)):
        lo, hi = va & ~0xFFF, (va + n + 0xFFF) & ~0xFFF
        for page in range(lo, hi, 0x1000):
            try:
                mu.mem_map(page, 0x1000)
            except Exception:                                    # noqa: BLE001  (already mapped)
                pass
            mu.mem_write(page, ex.read(page - ex.base, 0x1000).ljust(0x1000, b"\0"))
    STACK = 0x7FF000
    mu.mem_map(STACK - 0x2000, 0x3000)
    rsp0 = STACK - 0x100                                         # caller rsp % 16 == 0 before its CALL
    regs = dict(RBX=0x1111, RBP=0x2222, RSI=0x3333, RDI=0x4444, R12=0x5555, R13=0x6666, R14=0x7777, R15=0x8888)
    mu.reg_write(X.UC_X86_REG_RSP, rsp0)
    mu.reg_write(X.UC_X86_REG_RCX, cls)
    mu.reg_write(X.UC_X86_REG_RDX, 0)
    for k, v in regs.items():
        mu.reg_write(getattr(X, "UC_X86_REG_" + k), v)
    xmm = {i: 0x0123456789ABCDEF0000000000000000 + i for i in range(6, 16)}
    for i, v in xmm.items():
        mu.reg_write(getattr(X, f"UC_X86_REG_XMM{i}"), v)
    ret, resume = call + 5, site + 5
    seen, writes, entry_rsp = [], [], []

    def code(u, a, size, data):
        seen.append(a)
        if a == site:
            entry_rsp.append(u.reg_read(X.UC_X86_REG_RSP))
        if a in (ret, resume):
            u.emu_stop()

    mu.hook_add(UC_HOOK_CODE, code)
    mu.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size, val, d: writes.append((addr, size, val)))
    mu.emu_start(call, 0, count=64)
    rip = mu.reg_read(X.UC_X86_REG_RIP)
    out = dict(cls=cls, call=hex(call), site=hex(site), hook=hex(hook), returned=rip == ret,
               fell_through=rip == resume, rax=mu.reg_read(X.UC_X86_REG_RAX) & 0xFFFFFFFF,
               entered_via_site=site in seen, entry_rsp_mod16=entry_rsp[0] % 16 if entry_rsp else None)
    rsp = mu.reg_read(X.UC_X86_REG_RSP)
    out["rsp_ok"] = rsp == rsp0 if rip == ret else rsp == rsp0 - 8
    if abi:
        out["nonvolatile_ok"] = all(mu.reg_read(getattr(X, "UC_X86_REG_" + k)) == v for k, v in regs.items()) \
            and all(mu.reg_read(getattr(X, f"UC_X86_REG_XMM{i}")) == v for i, v in xmm.items())
        call_push = (rsp0 - 8, 8, ret)                           # the caller's own CALL
        own = [w for w in writes if w != call_push]
        if rip == ret:
            out["writes_ok"] = own == []
        else:                                                    # the replayed prologue, nothing else
            out["writes_ok"] = own == [(rsp0 - 8 + 8, 8, regs["RBX"])]
            out["args_ok"] = mu.reg_read(X.UC_X86_REG_RCX) == cls and mu.reg_read(X.UC_X86_REG_RDX) == 0
    return out


CASES = [("alone", 10260, 643), ("alone", 10, None), ("outfit", 10260, 643), ("outfit", 470, 470),
         ("outfit", 30170, None)]


def _check(r, want, abi):
    assert r["entered_via_site"] and r["entry_rsp_mod16"] == 8, r
    assert r["rsp_ok"], r
    if want is None:
        assert r["fell_through"], r
    else:
        assert r["returned"] and r["rax"] == want, r
    if abi:
        assert r["nonvolatile_ok"] and r["writes_ok"] and r.get("args_ok", True), r


@need_exe
@pytest.mark.parametrize("abi", [False, True], ids=["normal", "abi"])
@pytest.mark.parametrize("kind,cls,want", CASES)
def test_site(kind, cls, want, abi):
    old = exemap.ACTIVE
    try:
        _check(run_site(_patched(kind), cls, abi), want, abi)
    finally:
        exemap.use(old)


@need_exe
def test_hook_code_is_a_leaf():
    """Static audit: no push/pop/call and no rsp use but the replayed prologue, in both builds."""
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    old = exemap.ACTIVE
    try:
        for kind in ("alone", "outfit"):
            ex = exemap.Exe(_patched(kind))
            site = exemap.ACTIVE(0x14021E9D0)
            hook = site + 5 + struct.unpack("<i", ex.read(site - ex.base + 1, 4))[0]
            ops = []
            for ins in Cs(CS_ARCH_X86, CS_MODE_64).disasm(ex.read(hook - ex.base, 0x40), hook):
                ops.append((ins.mnemonic, ins.op_str))
                if ins.mnemonic == "ret":
                    break
            bad = [o for o in ops if o[0] in ("push", "pop", "call", "leave")
                   or ("rsp" in o[1] and o != ("mov", "qword ptr [rsp + 8], rbx"))]
            assert not bad, (kind, bad)
            assert ("sub", "eax, 0x2710") in ops, (kind, ops)
    finally:
        exemap.use(old)


@need_exe
@pytest.mark.skipif(not os.path.isdir(SOURCE) or not os.path.isdir(HELD + "/D4_Unique_210"),
                    reason="Disgaea Source or held D4CELL1 build not present")
def test_finalizer_emits_the_hook_without_outfits():
    """The installer's own finalizer, on the vanilla game files with Pringer X's row and unique.json and no outfit:
    its exe returns 643 for class 10260 at the real call site (about 15 s)."""
    from d5lib import database, dbpatch, gamefs, modsys
    old = exemap.ACTIVE
    try:
        fs = gamefs.GameFS(SOURCE)
        exemap.use(exemap.translator_for(fs.read(outfits.EXE_FILE)))
        ctx = modsys.BuildContext(fs, log=lambda *a: None)
        t = database.load_table("char.dat", fs.read(outfits.CHAR))
        mod = Path(HELD) / "D4_Unique_210"
        dbpatch.apply_patch(t, json.loads((mod / "patches/db/char.dat.json").read_text()), strict=True)
        ctx.put(outfits.CHAR, t.to_bytes())
        ctx._char_uniques = {10260: json.loads((mod / "patches/characters/unique.json").read_text())}
        outfits._finalize(ctx)
        exe = ctx.get(outfits.EXE_FILE)
        _check(run_site(exe, 10260, True), 643, True)
        _check(run_site(exe, 10, True), None, True)
    finally:
        exemap.use(old)


if __name__ == "__main__":
    abi = "--abi" in sys.argv
    results, ok = [], True
    for kind, cls, want in CASES:
        r = run_site(_patched(kind), cls, abi)
        try:
            _check(r, want, abi)
            r["verdict"] = "PASS"
        except AssertionError:
            r["verdict"], ok = "FAIL", False
        results.append(dict(build=kind, want=want, **r))
    print(json.dumps(results, indent=1))
    sys.exit(0 if ok else 1)
