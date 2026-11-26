"""INPUTGUARD1 offline proof: the input guard (d5lib/native/d5inputguard.h) on the game's real input paths.

The guard adds no hook and writes no game byte: it is a condition inside three hooks the runtime already installs
(the XInputGetState import slot, the DirectInput device vtable's GetDeviceState, the GetKeyboardState import slot).
So the proof is (1) static, on each exe given, that those slots and call sites are what the hooks assume, and (2)
Unicorn runs of the game's own input functions (pinned exe code) calling the COMPILED hooks through the slot, the
way the game calls them:

  1. static: the import slots the runtime patches (translated from the source's known-build VAs for this exe) name
     XInputGetState / GetKeyboardState / GetCursorPos; the pad poll 0x1408A06D0 calls the XInputGetState slot; the
     DirectInput setup 0x14089DB90 asks for keyboard and mouse with cooperative level 6 (NONEXCLUSIVE|FOREGROUND) and
     0x1408A1200 for pads with 10 (NONEXCLUSIVE|BACKGROUND); the game asks for IDirectInput8A (the hooked A vtable).
  2. emulation: a proof DLL = the runtime's sources as built for this exe (d5lib.runtime, the same Zig command) plus
     four exported setters (tools/proof_inputguard_exports.c).  For each path, the game function runs from a real
     `call` with canaried callee-saved registers, (a) vanilla (slot -> the stand-in "real" API), (b) hooked with
     remote=0 and (c) hooked with the guard on; the stand-in reports real input (pad A + stick, keys K + DOWN, a
     joystick button + d-pad up):
       * pad   0x1408A06D0 (XInput, user 0)         -> the buttons word it returns and the slot's +0x84..+0xBC
       * keys  input_raw_key 0x1408A02B0 (DI 256)    -> the game's key arrays 0x147B100A8..0x147B107A8
       * joy   0x1408A0880 (DI Poll + state 0x50)    -> the buttons word and the slot's +0x34..+0x128
     (b) must equal (a) exactly (the return value, the game memory, RBX RBP RSI RDI R12-R15, XMM6-15, RSP);
     (c) must show no real input (only an injected key in the keys case) and keep the callee-saved state.
     Every entry into the hook, the stand-in and any import is checked for RSP = 8 mod 16 (aligned call).
  --abi: the stand-in behaves like a hostile API: it clobbers RCX RDX R8-R11, XMM0-5 and the flags and writes all
     four home qwords before it returns.

    D5Modkit/.venv-macos/bin/python tools/proof_inputguard.py [--exe <pinned>] [--exe <installed>] [--abi] [--out r.json]
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))

import unicorn_darwin_shim                                        # noqa: E402  (Darwin/ARM64 CTR_EL0)

unicorn_darwin_shim.install()

from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError   # noqa: E402
from unicorn import x86_const as X                                    # noqa: E402
from test_recruit_runtime import pinned_exe, sections                  # noqa: E402

BASE = 0x140000000
CALLER, STANDIN, THUNKS = 0x100000000, 0x100010000, 0x100020000
RET = CALLER + 12                            # after `mov rax, imm64; call rax`: a real call, return address pushed
STACK, HEAP = 0x10000000, 0x200000000
RSP0 = STACK + 0x100000
NONVOL = ("RBX", "RBP", "RSI", "RDI", "R12", "R13", "R14", "R15")
# Steam-build addresses (decomp of the pinned exe)
PAD_POLL, KEY_POLL, JOY_POLL, DI_SETUP, PAD_SETUP = 0x1408A06D0, 0x1408A02B0, 0x1408A0880, 0x14089DB90, 0x1408A1200
KEY_DEVICE, KEY_ARRAYS, KEY_ARRAYS_END = 0x147B100A0, 0x147B100A8, 0x147B107A8
IID_DI8 = 0x1408F7580
SLOTS = {"XInputGetState": 0x1408D5738, "GetKeyboardState": 0x1408D5640, "GetCursorPos": 0x1408D5610}   # source VAs
DIK_K, DIK_DOWN, DIK_S = 0x25, 0xD0, 0x1F
DIERR_NOTACQUIRED = 0x8007000C


# ------------------------------------------------------------------------------------------- static
def image(data):
    base, size, secs = sections(data)

    def rd(va, n):
        rva = va - base
        for _, v, vs, rs, ro in secs:
            if v <= rva < v + max(vs, rs):
                return data[ro + rva - v:ro + rva - v + n]
        return b""
    return rd


def imports_by_slot(data):
    import pefile
    pe = pefile.PE(data=data, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    return {i.address: (i.name or b"").decode() for d in pe.DIRECTORY_ENTRY_IMPORT for i in d.imports}


def disasm(rd, va, n):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    return list(md.disasm(rd(va, n), va))


def coop_levels(rd, fn, n):
    """the r8d value loaded before each `call [reg+0x68]` (SetCooperativeLevel) in fn"""
    out, r8 = [], None
    for ins in disasm(rd, fn, n):
        if ins.mnemonic == "mov" and ins.op_str.startswith("r8d, "):
            try:
                r8 = int(ins.op_str.split(", ")[1], 0)
            except ValueError:
                r8 = None
        if ins.mnemonic == "call" and ins.op_str.endswith("+ 0x68]"):
            out.append(r8)
    return out


def static_checks(data, translate):
    rd = image(data)
    imp = imports_by_slot(data)
    rows = {}
    for name, src_va in SLOTS.items():
        va = translate(src_va)
        rows[name] = {"source_va": f"{src_va:#x}", "va": f"{va:#x}", "import": imp.get(va), "ok": imp.get(va) == name}
    call = next((i for i in disasm(rd, PAD_POLL, 0x40) if i.mnemonic == "call"), None)
    tgt = call.address + call.size + call.operands[0].mem.disp if call is not None else None
    rows["pad_poll_calls_xinput"] = {"site": f"{call.address:#x}" if call else None,
                                     "slot": f"{tgt:#x}" if tgt else None,
                                     "ok": tgt == translate(SLOTS["XInputGetState"])}
    kb = coop_levels(rd, DI_SETUP, 0x42C)
    pad = coop_levels(rd, PAD_SETUP, 0x1A5)
    rows["coop_keyboard_mouse"] = {"levels": kb, "ok": kb == [6, 6]}
    rows["coop_pads"] = {"levels": pad, "ok": pad == [10]}
    iid = struct.unpack("<I", rd(IID_DI8, 4))[0]
    rows["dinput8_interface"] = {"data1": f"{iid:#x}", "ok": iid == 0xBF798030}       # IDirectInput8A
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    ts = struct.unpack_from("<I", data, pe + 8)[0]
    return {"timestamp": f"{ts:#x}", "rows": rows, "ok": all(r["ok"] for r in rows.values())}


# ------------------------------------------------------------------------------------------- proof dll
MUTATIONS = {   # negative controls: each must make the proof FAIL
    "no-pad-guard": ("if (input_guarded() && r == 0 && st) guard_xinput", "if (0 && r == 0 && st) guard_xinput"),
    "no-joy-guard": ("if (guard && data && guard_joy_is_state(cb))", "if (0 && data && guard_joy_is_state(cb))"),
    "guard-always": ("static int input_guarded(void) { return g_input_guard || g_fake_focus; }",
                     "static int input_guarded(void) { return 1; }"),
}


def build_proof_dll(exe_data, outdir, mutate=None):
    from d5lib import exemap, runtime
    exemap.use(exemap.translator_for(exe_data))
    tdir = Path(outdir)
    for path in runtime.core_sources():
        src = runtime._source_text(path)
        if mutate:
            a, b = (x.encode() for x in MUTATIONS[mutate])
            src = src.replace(a, b)
        (tdir / os.path.basename(path)).write_bytes(src)
    (tdir / "proof.c").write_text((KIT / "tools" / "proof_inputguard_exports.c").read_text())
    out = tdir / "proof.dll"
    cmd = [sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-shared", "-O2", "-o", str(out),
           str(tdir / "proof.c")] + runtime.LIBS
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-3000:])
    return out.read_bytes(), (lambda va: int(exemap.ACTIVE.text(f"{va:#x}ULL").rstrip("ULul"), 16))


def dll_exports(data):
    import pefile
    pe = pefile.PE(data=data, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"],
                                           pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    base = pe.OPTIONAL_HEADER.ImageBase
    ex = {e.name.decode(): base + e.address for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
    im = [(i.address, (i.name or b"").decode()) for d in pe.DIRECTORY_ENTRY_IMPORT for i in d.imports]
    return ex, im


# ------------------------------------------------------------------------------------------- emulation
class Machine:
    def __init__(self, exe, dll, abi):
        self.abi = abi
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_64)
        for blob in (exe, dll):
            base, size, secs = sections(blob)
            mu.mem_map(base, (size + 0xFFFF) // 0x10000 * 0x10000)
            for _, va, vs, rs, ro in secs:
                if rs:
                    mu.mem_write(base + va, blob[ro:ro + min(vs, rs)])
        for a in (CALLER, STANDIN, THUNKS):
            mu.mem_map(a, 0x10000)
        mu.mem_map(STACK, 0x200000)
        mu.mem_map(HEAP, 0x100000)
        self.exports, imports = dll_exports(dll)
        self.thunk_name = {}
        for k, (slot, name) in enumerate(imports):
            t = THUNKS + 16 * k
            mu.mem_write(t, b"\xC3")
            mu.mem_write(slot, struct.pack("<Q", t))
            self.thunk_name[t] = name
        mu.hook_add(UC_HOOK_CODE, self._thunk, begin=THUNKS, end=THUNKS + 0xFFFF)
        mu.hook_add(UC_HOOK_CODE, self._standin, begin=STANDIN, end=STANDIN + 0xFFFF)
        self.standins, self.entries, self.misaligned, self.unknown_imports = {}, [], [], set()
        self.watch = {}
        for i, name in enumerate(("pad", "kbd", "joy", "poll", "gks")):
            a = STANDIN + 0x100 * i
            mu.mem_write(a, b"\xC3")
            self.standins[a] = name
            self.standins[name] = a

    def r(self, n):
        return self.mu.reg_read(getattr(X, "UC_X86_REG_" + n))

    def w(self, n, v):
        self.mu.reg_write(getattr(X, "UC_X86_REG_" + n), v)

    def _aligned(self, what):
        rsp = self.r("RSP")
        self.entries.append((what, rsp % 16))
        if rsp % 16 != 8:
            self.misaligned.append(what)

    def _thunk(self, mu, addr, size, _):
        name = self.thunk_name.get(addr, "?")
        self._aligned("import " + name)
        if name == "memset":
            mu.mem_write(self.r("RCX"), bytes([self.r("RDX") & 0xFF]) * self.r("R8"))
            self.w("RAX", self.r("RCX"))
        elif name in ("memcpy", "memmove"):
            mu.mem_write(self.r("RCX"), bytes(mu.mem_read(self.r("RDX"), self.r("R8"))))
            self.w("RAX", self.r("RCX"))
        elif name == "GetCurrentThreadId":
            self.w("RAX", 7)
        else:
            self.unknown_imports.add(name)
            self.w("RAX", 0)

    def _standin(self, mu, addr, size, _):
        name = self.standins[addr]
        self._aligned("stand-in " + name)
        rax = 0
        if name == "pad":                     # XInputGetState(user, XINPUT_STATE*): A held, left stick right
            mu.mem_write(self.r("RDX"), struct.pack("<IHBBhhhh", 99, 0x1000, 0, 0, 32767, 0, 0, 0))
        elif name == "kbd":                   # GetDeviceState(self, 256, buf): K and DOWN held
            buf = bytearray(256)
            buf[DIK_K] = buf[DIK_DOWN] = 0x80
            mu.mem_write(self.r("R8"), bytes(buf))
        elif name == "joy":                   # GetDeviceState(self, 0x50, DIJOYSTATE*): button 0, POV 0 (up)
            js = bytearray(0x50)
            js[0x30] = 0x80
            mu.mem_write(self.r("R8"), bytes(js))
        if self.abi:                          # a hostile API: volatile registers, flags and home area clobbered
            for i, reg in enumerate(("RCX", "RDX", "R8", "R9", "R10", "R11")):
                self.w(reg, 0xBAD0000000000000 + i)
            rsp = self.r("RSP")
            mu.mem_write(rsp + 8, struct.pack("<4Q", *(0xBADBAD0000000000 + i for i in range(4))))
            for i in range(6):
                self.w(f"XMM{i}", (1 << 128) - 1)
            self.w("EFLAGS", 0x203 | 0x40)
        self.w("RAX", rax)

    def call(self, target, args=(), stack_args=()):
        mu = self.mu
        mu.mem_write(CALLER, b"\x48\xB8" + struct.pack("<Q", target) + b"\xFF\xD0\xF4")   # mov rax, fn; call rax
        for i, n in enumerate(NONVOL):
            self.w(n, 0x1111000000000000 + 0x0101 * i)
        for i in range(6, 16):
            self.w(f"XMM{i}", 0x22220000000000003333000000000000 + i)
        for reg, v in zip(("RCX", "RDX", "R8", "R9"), args):
            self.w(reg, v)
        self.w("RSP", RSP0)
        for k, v in enumerate(stack_args):
            mu.mem_write(RSP0 + 0x20 + 8 * k, struct.pack("<Q", v))
        try:
            mu.emu_start(CALLER, RET, count=2_000_000)
        except UcError as exc:
            return {"fault": f"{exc} at {self.r('RIP'):#x}"}
        return {"rax": self.r("RAX"), "rsp": self.r("RSP"), "rip": self.r("RIP"),
                "nonvol": [self.r(n) for n in NONVOL],
                "xmm": [self.mu.reg_read(getattr(X, f"UC_X86_REG_XMM{i}")) for i in range(6, 16)]}

    def setup(self, remote, guard, di, fake=0, inject=None):
        e = self.exports
        self.call(e["proof_setup"], (remote, guard, fake, self.standins["pad"]),
                  (self.standins[di], self.standins["gks"]))
        if inject is not None:
            self.call(e["proof_inject"], (inject, 1))
        self.entries.clear()


def callee_saved_ok(res):
    return ("fault" not in res and res["rsp"] == RSP0 and res["rip"] == RET and
            res["nonvol"] == [0x1111000000000000 + 0x0101 * i for i in range(8)] and
            res["xmm"] == [0x22220000000000003333000000000000 + i for i in range(6, 16)])


def run_case(exe, dll, path, mode, abi, translate):
    """path: pad / keys / joy; mode: vanilla / remote0 / guard / guard+inject"""
    m = Machine(exe, dll, abi)
    mu, e = m.mu, m.exports
    hook = e["proof_hook_pad"] if path == "pad" else e["proof_hook_dia"]
    std = {"pad": "pad", "keys": "kbd", "joy": "joy"}[path]
    if mode == "vanilla":
        target = m.standins[std]
    else:
        m.setup(remote=0 if mode == "remote0" else 1, guard=0 if mode == "remote0" else 1, di=std,
                inject=DIK_S if mode == "guard+inject" else None)
        m.call(hook)
        target = m.r("RAX")                                   # the hook's address, as patch_slot stores it
        mu.hook_add(UC_HOOK_CODE, lambda *_: m._aligned("hook"), begin=target, end=target)
    out = {"path": path, "mode": mode}
    if path == "pad":
        mu.mem_write(translate(SLOTS["XInputGetState"]), struct.pack("<Q", target))
        slot = HEAP + 0x1000
        mu.mem_write(slot, bytes(0x128))
        res = m.call(PAD_POLL, (slot,))
        out["memory"] = bytes(mu.mem_read(slot + 0x84, 0x3C)).hex()
    else:
        dev, vt = HEAP + 0x2000, HEAP + 0x3000
        vtable = [m.standins["poll"]] * 32
        vtable[9] = target
        mu.mem_write(vt, struct.pack("<32Q", *vtable))
        mu.mem_write(dev, struct.pack("<Q", vt))
        if path == "keys":
            mu.mem_write(KEY_DEVICE, struct.pack("<Q", dev))
            res = m.call(KEY_POLL)
            out["memory"] = bytes(mu.mem_read(KEY_ARRAYS, KEY_ARRAYS_END - KEY_ARRAYS)).hex()
            arr = bytes(mu.mem_read(KEY_ARRAYS + 0x100, 0x100))           # 0x147B101A8: went down this frame
            out["went_down"] = [i for i in range(256) if arr[i]]
        else:
            slot = HEAP + 0x1000
            blk = bytearray(0x128)
            struct.pack_into("<Q", blk, 0, dev)
            blk[0x11C] = 1
            blk[0xC4] = 1                                                   # centre already measured (zeros)
            mu.mem_write(slot, bytes(blk))
            res = m.call(JOY_POLL, (slot,))
            out["memory"] = bytes(mu.mem_read(slot + 0x34, 0x128 - 0x34)).hex()
    out.update(fault=res.get("fault"), rax=res.get("rax"), callee_saved=callee_saved_ok(res),
               misaligned=m.misaligned, entries=sorted({w for w, _ in m.entries}),
               imports_called=sorted(m.unknown_imports))
    if path == "pad":
        out["buttons"] = (res.get("rax") or 0) & 0xFFFF
    else:
        out["buttons"] = res.get("rax")
    if mode != "vanilla":
        m.call(e["proof_count"], (0,))
        kb = m.r("RAX")
        m.call(e["proof_count"], (1,))
        out["counted"] = {"kb": kb, "pad": m.r("RAX")}
    return out


def prove(exe, abi, mutate=None):
    with tempfile.TemporaryDirectory(prefix="inputguard-") as td:
        dll, translate = build_proof_dll(exe, td, mutate)
    cases, verdicts = [], []
    for path in ("pad", "keys", "joy"):
        rows = {mode: run_case(exe, dll, path, mode, abi, translate)
                for mode in ("vanilla", "remote0", "guard", "guard+inject")}
        cases += rows.values()
        v, r0, g, gi = rows["vanilla"], rows["remote0"], rows["guard"], rows["guard+inject"]
        real = v["buttons"] != 0 if path != "keys" else v["went_down"] == [DIK_K, DIK_DOWN]
        same = all(r0[k] == v[k] for k in ("rax", "memory", "fault")) and r0["callee_saved"]
        if path == "keys":
            dropped = g["went_down"] == [] and gi["went_down"] == [DIK_S]
            counted = g["counted"]["kb"] == 1 and gi["counted"]["kb"] == 1
        else:
            dropped = g["buttons"] == 0 and gi["buttons"] == 0 and g["memory"] != v["memory"]
            counted = g["counted"]["pad"] == 1
        ok = (real and same and dropped and counted and g["callee_saved"] and gi["callee_saved"]
              and not any(c["misaligned"] or c["fault"] for c in rows.values())
              and r0["counted"] == {"kb": 0, "pad": 0})
        verdicts.append({"path": path, "real_input_in_vanilla": real, "remote0_equals_vanilla": same,
                         "guard_drops_real_input": dropped, "guard_counts_it": counted,
                         "callee_saved_kept": all(c["callee_saved"] for c in rows.values()),
                         "aligned_entries": not any(c["misaligned"] for c in rows.values()), "ok": ok})
    return {"abi": abi, "dll_bytes": len(dll), "verdicts": verdicts, "cases": cases,
            "ok": all(x["ok"] for x in verdicts)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exe", action="append", help="exe for the static checks (default: the pinned original)")
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--mutate", choices=sorted(MUTATIONS), help="negative control: must FAIL")
    a = ap.parse_args(argv)
    pinned = Path(pinned_exe()).read_bytes()
    with tempfile.TemporaryDirectory(prefix="inputguard-") as td:
        _, translate = build_proof_dll(pinned, td)
    static = {p: static_checks(Path(p).read_bytes(), translate) for p in (a.exe or [pinned_exe()])}
    emu = prove(pinned, a.abi, a.mutate)
    rep = {"static": static, "emulation": emu, "ok": emu["ok"] and all(s["ok"] for s in static.values())}
    text = json.dumps(rep, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    for p, s in static.items():
        print(f"static {Path(p).name}: ts {s['timestamp']} " +
              " ".join(f"{k}={'ok' if r['ok'] else 'FAIL'}" for k, r in s["rows"].items()))
    for v in emu["verdicts"]:
        print(f"{'--abi ' if a.abi else ''}{v['path']}: " + " ".join(f"{k}={v[k]}" for k in v if k != "path"))
    print("PASS" if rep["ok"] else "FAIL")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
