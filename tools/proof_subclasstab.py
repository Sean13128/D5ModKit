"""SUBCLASS2 offline proof: the Class tab sub-class switch (d5lib/subclasstab.py, section .d5sb) on the pinned exe.

The patched exe is built by the kit itself on the pinned Steam exe: newclasses.build_hooks (one imported family, so the
Class tab list moves into the .d5cl buffer) and then subclasstab.build_patch, exactly as the finalizers chain at
install.  The game's own code is executed on Unicorn x86-64, entered the way the game enters the hook: at 0x14029A410
(the Class tab child's update: it calls the tab switcher 0x1402A7140 -- a stand-in here, it only handles L/R tab keys --
and then tail-jumps to 0x14029CA50), rcx = the child object, RSP = 8 mod 16, one frame per run, the same machine kept
across frames so the hook's state block carries over as it does in the game.  A frame ends when the game's own update
body is reached (0x14029CA5C, after the displaced prologue): there every register and the stack the body sees are
compared with the pinned exe's run of the same frame.

Confirm is read through the game's own carry_common_action 0x1402258B0 (SUBCLASS3), run as real code: its keyboard
half reads the action's key binding (input object [0x140BD7B30] + 0x50 + 4*8), the keyboard-mode byte 0x147A69F29, the
pointer/touch mode dword 0x147B2474C and the key edge / repeat tables 0x147B24AE0 / 0x147B24DE0, which the proof sets
the way the game's input update leaves them for a key press.  Stand-ins (code hooks that return like the real function)
for its pad half: input_physical 0x140223CE0 (logical 4 -> a physical index), input_button_state 0x140223EA0
(2 = press edge, 1 = repeat, 0 = none); and the class-rank unlock test 0x1401C6110 (a set
of unlocked ids).  Each records its arguments and RSP; each clobbers rax/rcx/rdx/r8-r11 and its 32-byte home space, as
a real callee may.

--abi adds: RSP = 8 mod 16 at every stand-in's entry, the home space poisoned by the callee holds no hook data
(the result is still right), and two mutants of the hook that the checks must reject (no 0x28 frame -> misaligned
calls; no arming frame -> a write on the frame the tab opens).
--static: stack audit of the built hook (every path from the entry: push/pop/sub/add accounting, RSP mod 16 and home
clearance at each call, RSP back to the entry value at the displaced `mov r11, rsp`, the exit jump lands on
0x14029CA5C with the original prologue's 0xB8 below the entry, no ret, no indirect branch).

    D5Modkit/.venv-macos/bin/python tools/proof_subclasstab.py [--exe <pinned>] [--abi] [--static] [--out r.json]
Exit 0 = every check passed.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))

try:
    import unicorn_darwin_shim                                    # noqa: F401,E402  (Darwin/ARM64 CTR_EL0)
    unicorn_darwin_shim.install()
except (ImportError, AttributeError):                             # pragma: no cover
    pass
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError       # noqa: E402
from unicorn import x86_const as X                                            # noqa: E402

from d5lib import exemap, newclasses, subclasstab as S                       # noqa: E402

PINNED_REL = Path("D5Modkit/state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full")
ENTRY = 0x14029A410            # the Class tab child's update: call 0x1402A7140, then jmp 0x14029CA50
TAB_SWITCH = 0x1402A7140
BODY = S.SITE_RET              # 0x14029CA5C: the game's update body after the (displaced) prologue
UNLOCK = 0x1401C6110           # Steam address of S.UNLOCK_TEST
ROSTER = 0x145207DB8           # Steam address of S.ROSTER
STACK, STACK_SIZE = 0x10000000, 0x200000
OBJ = 0x200000000              # the Class tab child (0x200B8 bytes in the game)
TEMP = 0x200100000             # a unit copy outside the roster (a battle copy)
SENTINEL = 0x7FFF0000
INPUT_PHYSICAL, INPUT_STATE = 0x140223CE0, 0x140223EA0   # the pad half of carry_common_action (stand-ins)
INPUT_PTR, INPUT_OBJ = 0x140BD7B30, 0x200200000   # the input object pointer (Steam build) and our stand-in object
KB_MODE, POINTER_MODE, KEY_EDGE, KEY_REPEAT = 0x147A69F29, 0x147B2474C, 0x147B24AE0, 0x147B24DE0
CONFIRM_KEY = 0x25                               # a key index the binding table names for Confirm (any 1..255)
FAMILY = 1440                  # the imported family the proof lists (any generic family works: the list is data)
ALL = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
NONVOL = ["rbx", "rbp", "rsi", "rdi", "r12", "r13", "r14", "r15"]
REG = {n: getattr(X, "UC_X86_REG_" + n.upper()) for n in ALL + ["rip"]}
VANILLA = list(range(1010, 1270, 10)) + list(range(2010, 2220, 10))       # 47


def find_pinned():
    here = Path(__file__).resolve()
    for p in list(here.parents) + [Path("/Volumes/Data/Projects/D5")]:
        if (p / PINNED_REL).is_file():
            return p / PINNED_REL
    return None


def sections(exe):
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    n = struct.unpack_from("<H", exe, pe + 6)[0]
    opt = pe + 0x18
    base = struct.unpack_from("<Q", exe, opt + 0x18)[0]
    size = struct.unpack_from("<I", exe, opt + 0x38)[0]
    so = opt + struct.unpack_from("<H", exe, pe + 0x14)[0]
    return base, size, [struct.unpack_from("<IIII", exe, so + 40 * i + 8) for i in range(n)]


class Machine:
    """one game: the exe mapped once, frames run one after the other on it"""

    def __init__(self, exe):
        base, size, secs = sections(exe)
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(base, (size + 0xFFF) & ~0xFFF)
        for vs, va, rs, ro in secs:
            if rs:
                mu.mem_write(base + va, exe[ro:ro + min(vs, rs)])
        mu.mem_map(STACK, STACK_SIZE)
        mu.mem_map(SENTINEL & ~0xFFF, 0x1000)
        mu.mem_map(OBJ, 0x40000)
        mu.mem_map(TEMP, 0x10000)
        mu.mem_map(INPUT_OBJ, 0x10000)
        mu.mem_write(INPUT_PTR, struct.pack("<Q", INPUT_OBJ))
        self.calls = []
        self.input = (5, 2)                     # (physical index, button state)
        self.unlocked = set()
        self.poison_home = False
        self.keyboard = None                    # None = pad only; (key, state) = keyboard mode, key bound to Confirm
        mu.hook_add(UC_HOOK_CODE, self._code)

    def w32(self, va, v):
        self.mu.mem_write(va, struct.pack("<i", v))

    def w16(self, va, v):
        self.mu.mem_write(va, struct.pack("<H", v))

    def r16(self, va):
        return struct.unpack("<H", self.mu.mem_read(va, 2))[0]

    def _return(self, mu, value):
        rsp = mu.reg_read(REG["rsp"])
        ret = struct.unpack("<Q", mu.mem_read(rsp, 8))[0]
        for n in ("rcx", "rdx", "r8", "r9", "r10", "r11"):          # a real callee may clobber volatiles
            mu.reg_write(REG[n], 0xDEAD000000000000 + len(self.calls))
        if self.poison_home:
            mu.mem_write(rsp + 8, b"\xA5" * 32)
        mu.reg_write(REG["rax"], value)
        mu.reg_write(REG["rsp"], rsp + 8)
        mu.reg_write(REG["rip"], ret)

    def _code(self, mu, addr, size, _):
        if addr == BODY:
            mu.emu_stop()
            return
        if addr == TAB_SWITCH:
            self._return(mu, 0)
            return
        stub = {INPUT_PHYSICAL: "input_physical", INPUT_STATE: "input_button_state", UNLOCK: "unlock"}.get(addr)
        if stub is None:
            return
        rsp = mu.reg_read(REG["rsp"])
        args = [mu.reg_read(REG[r]) & 0xFFFFFFFF for r in ("rcx", "rdx", "r8")]
        self.calls.append({"fn": stub, "args": args, "rsp_mod16": rsp % 16})
        if stub == "input_physical":
            self._return(mu, self.input[0] & 0xFFFFFFFFFFFFFFFF)
        elif stub == "input_button_state":
            self._return(mu, self.input[1])
        else:
            self._return(mu, 0xFFFFFF01 if args[0] in self.unlocked else 0xFFFFFF00)   # only al counts

    def _keyboard_state(self):
        mu = self.mu
        mu.mem_write(KB_MODE, bytes([1 if self.keyboard else 0]))
        mu.mem_write(POINTER_MODE, struct.pack("<i", 0))
        mu.mem_write(KEY_EDGE, bytes(256))
        mu.mem_write(KEY_REPEAT, bytes(256))
        mu.mem_write(INPUT_OBJ + 0x50 + 4 * 8, struct.pack("<Q", CONFIRM_KEY))
        mu.mem_write(INPUT_OBJ + 0x420 + 4 * 8, struct.pack("<Q", 0))
        if self.keyboard:
            key, st = self.keyboard
            if st == 2:
                mu.mem_write(KEY_EDGE + key, b"\x01")
            elif st == 1:
                mu.mem_write(KEY_REPEAT + key, b"\x01")

    def frame(self, seed=0):
        """run one update of the Class tab child -> (registers at the body, the 0xE0 stack bytes there, error)"""
        self.calls = []
        self._keyboard_state()
        rsp = STACK + STACK_SIZE // 2 - 8                            # entered by `call`: 8 mod 16
        self.mu.mem_write(rsp, struct.pack("<Q", SENTINEL))
        regs = {n: 0x3333333300000000 + (seed << 8) + i for i, n in enumerate(ALL)}
        regs.update(rsp=rsp, rcx=OBJ)
        for n, v in regs.items():
            self.mu.reg_write(REG[n], v)
        err = None
        try:
            self.mu.emu_start(ENTRY, SENTINEL, count=100000)
        except UcError as e:
            err = str(e)
        end = self.mu.reg_read(REG["rip"])
        out = {n: self.mu.reg_read(REG[n]) for n in ALL}
        stack = bytes(self.mu.mem_read(out["rsp"], 0xE0))
        return {"ended": end, "regs": out, "stack": stack, "error": err, "calls": list(self.calls)}


def setup(m, list_addr, families, tab=4, cursor=0, scroll=0, count=None, unit_slot=3, unit=None, sub=2010):
    """the Class tab child as the game builds it: list (relocated buffer or +0x1E404), count, cursor, scroll, unit"""
    for i, f in enumerate(families):
        m.w32((list_addr if list_addr else OBJ + S.NATIVE_LIST) + 4 * i, f)
    m.w32(OBJ + S.COUNT, len(families) if count is None else count)
    m.w32(OBJ + S.CURSOR, cursor)
    m.w32(OBJ + S.SCROLL, scroll)
    m.w32(OBJ + S.TAB, tab)
    ptr = unit if unit is not None else ROSTER + unit_slot * S.UNIT_SIZE
    m.mu.mem_write(OBJ + S.CHARACTER, struct.pack("<Q", ptr))
    if ptr >= ROSTER or ptr >= TEMP:
        try:
            m.w16(ptr + S.SUBCLASS, sub)
        except UcError:
            pass
    return ptr


def build(pinned, mutate=None):
    """(relocated build, its Class tab list address, native-list build).  mutate(src) -> src edits the hook."""
    prev = exemap.ACTIVE
    exemap.use(exemap.translator_for(pinned))
    orig_src = S._src
    if mutate:
        S._src = lambda a, c: mutate(orig_src(a, c))
    try:
        spec = {FAMILY: dict(family=FAMILY, template=1150, name="probe", unlocked=True, unlocked_ranks=6,
                             evility_alias={})}
        cls = list(range(FAMILY, FAMILY + 6))
        classes = newclasses.build_hooks(pinned, cls, cls, {}, (), specs=spec)
        info = S.classtab_buffer(classes)
        patched = S.build_patch(classes, info)
        native = S.build_patch_native(pinned)
    finally:
        S._src = orig_src
        exemap.use(prev)
    return classes, patched, info, native


def same_as(ref, run):
    """the game's body sees the same registers and stack as on the reference exe"""
    # [rsp, rsp+0xA8) is the body's own uninitialised local area (it holds whatever the last callee left); the
    # pushed rdi/rsi, the return address and the caller's home space above it are what the body may read
    return run["ended"] == BODY and ref["ended"] == BODY and run["regs"] == ref["regs"] \
        and run["stack"][0xA8:] == ref["stack"][0xA8:] and not run["error"]


def state(m, exe):
    st = S.state_address(exe)
    owner, presses, result, fam, target = struct.unpack("<QIIII", m.mu.mem_read(st, 24))
    return {"owner": owner, "presses": presses, "result": result, "family": fam, "target": target}


def prove(pinned, abi=False):
    classes, patched, (list_addr, cap), native = build(pinned)
    checks = []

    def check(name, ok, got=None):
        checks.append({"check": name, "ok": bool(ok), "got": got})

    fams = VANILLA + [FAMILY + 10 * k for k in range(13)]          # 60 rows: 47 vanilla + 13 imported (1440..1560)
    idx = 55                                                        # row 55 -> family 1520 (past the Assembly's 47)
    want_fam = fams[idx]

    def scenario(exe, frames, unlocked=(), sub=2010, **kw):
        """frames: [(tab, (physical, state))]; -> (machine, per-frame runs, unit pointer)"""
        m = Machine(exe)
        m.unlocked = set(unlocked)
        runs = []
        ptr = None
        for i, (tab, inp) in enumerate(frames):
            m.input = inp
            ptr = setup(m, list_addr if exe is patched or exe is classes else None, kw.get("families", fams),
                        tab=tab, cursor=kw.get("cursor", 5), scroll=kw.get("scroll", 50), count=kw.get("count"),
                        unit=kw.get("unit"), sub=sub if i == 0 else m.r16(ptr + S.SUBCLASS))
            runs.append(m.frame(seed=i))
        return m, runs, ptr

    ranks6 = range(want_fam, want_fam + 6)
    # A. the normal use: the tab opens (arms), then Confirm -> highest unlocked rank written
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=ranks6)
    st = state(m, patched)
    check(f"row {idx} (family {want_fam}, past the Assembly's 47 rows), 6 ranks unlocked, Confirm on the second frame "
          f"-> unit +0x35AC = {want_fam + 5}", m.r16(ptr + S.SUBCLASS) == want_fam + 5
          and st["result"] == S.RESULT_WRITTEN and st["family"] == want_fam and st["presses"] == 1,
          {"sub": m.r16(ptr + S.SUBCLASS), "state": st})
    check("first frame on the tab only arms (no input read, no write)", runs[0]["calls"] == [], runs[0]["calls"])
    check("the press frame reads Confirm the menus' way: carry_common_action(4, 1, 0) (real code) -> pad half "
          "input_physical(4), input_button_state(index, .., 1), then the unlock test for the base rank and the highest "
          "ranks downwards until one passes",
          [c["fn"] for c in runs[1]["calls"]] == ["input_physical", "input_button_state", "unlock", "unlock"]
          and runs[1]["calls"][0]["args"][0] == 4 and runs[1]["calls"][1]["args"][0] == 5
          and runs[1]["calls"][1]["args"][2] == 1
          and [c["args"][0] for c in runs[1]["calls"][2:]] == [want_fam, want_fam + 5], runs[1]["calls"])
    ctl_m, ctl_runs, ctl_ptr = scenario(classes, [(4, (5, 0)), (4, (5, 2))], unlocked=ranks6)
    check("control: the same two frames on the build without .d5sb leave +0x35AC at 2010",
          ctl_m.r16(ctl_ptr + S.SUBCLASS) == 2010, ctl_m.r16(ctl_ptr + S.SUBCLASS))
    check("every frame reaches the game's update body with the registers and stack the build without .d5sb gives it",
          all(same_as(r0, r1) for r0, r1 in zip(ctl_runs, runs)),
          [{"ended": hex(r["ended"]), "error": r["error"]} for r in runs])
    # B. rank rule = the Assembly screen's: family - 1 + number of unlocked ranks
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=range(want_fam, want_fam + 3))
    check(f"three ranks unlocked -> {want_fam + 2}", m.r16(ptr + S.SUBCLASS) == want_fam + 2, m.r16(ptr + S.SUBCLASS))
    # rework (Codex review): a gap -- base and rank 5 only -> rank 5, never the not-unlocked rank 1
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked={want_fam, want_fam + 5})
    check(f"rank gap (base and rank 5 unlocked only) -> {want_fam + 5}, the highest unlocked rank",
          m.r16(ptr + S.SUBCLASS) == want_fam + 5, m.r16(ptr + S.SUBCLASS))
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked={want_fam + 3, want_fam + 5})
    check("base rank locked (ranks 3 and 5 report unlocked) -> refused as locked, like the Assembly's admission",
          m.r16(ptr + S.SUBCLASS) == 2010 and state(m, patched)["result"] == S.RESULT_LOCKED, state(m, patched))
    # rework (Codex review): the unit's own class is not offered as its sub-class
    m = Machine(patched)
    m.unlocked = set(ranks6)
    own = ROSTER + 3 * S.UNIT_SIZE
    for i, inp in enumerate(((5, 0), (5, 2))):
        m.input = inp
        setup(m, list_addr, fams, cursor=5, scroll=50, sub=2010 if i == 0 else m.r16(own + S.SUBCLASS))
        m.w32(own + S.MAIN_CLASS, want_fam + 3)
        m.frame(seed=i)
    st = state(m, patched)
    check(f"own class (main {want_fam + 3}, family {want_fam} highlighted) -> refused, +0x35AC stays 2010",
          m.r16(own + S.SUBCLASS) == 2010 and st["result"] == S.RESULT_OWN, st)
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=())
    st = state(m, patched)
    check("no rank unlocked -> refused (locked), +0x35AC unchanged",
          m.r16(ptr + S.SUBCLASS) == 2010 and st["result"] == S.RESULT_LOCKED, st)
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=ranks6, sub=want_fam + 5)
    st = state(m, patched)
    check("already that sub-class -> no write (result: same)", m.r16(ptr + S.SUBCLASS) == want_fam + 5
          and st["result"] == S.RESULT_SAME, st)
    # C. input
    for name, inp in (("no press (state 0)", (5, 0)), ("repeat pulse (state 1)", (5, 1)),
                      ("Confirm not mapped (input_physical -1)", (-1, 2))):
        m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, inp)], unlocked=ranks6)
        check(f"{name} -> no write", m.r16(ptr + S.SUBCLASS) == 2010 and state(m, patched)["presses"] == 0,
              runs[1]["calls"])
    # SUBCLASS3: a keyboard Confirm (the player's or the harness's key) reaches the hook through the game's own read
    def kb_run(exe, state, mode=True):
        mk = Machine(exe)
        mk.unlocked = set(ranks6)
        rr = []
        for i, kb in enumerate(((CONFIRM_KEY, 0), (CONFIRM_KEY, state))):
            mk.input = (5, 0)                                   # the pad reports nothing
            mk.keyboard = kb if mode else None
            pk = setup(mk, list_addr, fams, cursor=5, scroll=50)
            rr.append(mk.frame(seed=i))
        return mk, rr, pk
    mk, rr, pk = kb_run(patched, 2)
    check(f"keyboard Confirm (key bound to action 4, press edge in 0x147B24AE0, pad idle) -> {want_fam + 5}; no pad read "
          "on that frame (carry_common_action answers from the keyboard table)",
          mk.r16(pk + S.SUBCLASS) == want_fam + 5 and [c["fn"] for c in rr[1]["calls"]] == ["unlock", "unlock"],
          {"sub": mk.r16(pk + S.SUBCLASS), "calls": rr[1]["calls"]})
    mk, rr, pk = kb_run(patched, 1)
    check("keyboard repeat (0x147B24DE0) -> no write", mk.r16(pk + S.SUBCLASS) == 2010, rr[1]["calls"])
    mk, rr, pk = kb_run(classes, 2)
    check("control: the same keyboard Confirm on the build without .d5sb leaves 2010",
          mk.r16(pk + S.SUBCLASS) == 2010, mk.r16(pk + S.SUBCLASS))
    # the first port's read (pad half only) misses the keyboard Confirm: run it as a mutant
    first = build(pinned, lambda src: src.replace(
        f"mov ecx, {S.CONFIRM}\nmov edx, 1\nxor r8d, r8d\ncall {S.ACTION}\n",
        f"mov ecx, {S.CONFIRM}\ncall {0x140223CE0}\nmov ecx, eax\nxor edx, edx\nmov r8d, 1\ncall {0x140223EA0}\n"))[1]
    mk, rr, pk = kb_run(first, 2)
    check("SUBCLASS2's pad-only read (input_physical -> input_button_state) does not see that keyboard Confirm "
          "(the INSTALL1120A B1 result, reproduced offline)", mk.r16(pk + S.SUBCLASS) == 2010,
          {"sub": mk.r16(pk + S.SUBCLASS), "calls": rr[1]["calls"]})
    # SUBCLASS3: registry families (D1C Golem 11770) are generic families too
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=range(11770, 11776),
                            families=VANILLA + [11770] * 13)
    check("registry family 11770 (D1C Golem, the INSTALL1120A row) -> 11775", m.r16(ptr + S.SUBCLASS) == 11775,
          state(m, patched))
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=range(1000, 3000),
                            families=VANILLA + [18110] * 13)
    check("a unique class id listed (18110): the game's unlock test says no -> refused as locked, nothing written",
          m.r16(ptr + S.SUBCLASS) == 2010 and state(m, patched)["result"] == S.RESULT_LOCKED, state(m, patched))
    m, runs, ptr = scenario(patched, [(2, (5, 2)), (2, (5, 2))], unlocked=ranks6)
    check("another tab visible (tab 2) with Confirm held -> nothing called, nothing written, state owner 0",
          m.r16(ptr + S.SUBCLASS) == 2010 and all(r["calls"] == [] for r in runs) and state(m, patched)["owner"] == 0,
          [r["calls"] for r in runs])
    m, runs, ptr = scenario(patched, [(4, (5, 2)), (2, (5, 2)), (4, (5, 2))], unlocked=ranks6)
    check("leaving the tab disarms: Class -> other tab -> Class with Confirm held writes nothing on the re-entry frame",
          m.r16(ptr + S.SUBCLASS) == 2010, [r["calls"] for r in runs])
    # D. validation (Overlord's checks)
    bad = {
        "unit pointer misaligned inside the roster": dict(unit=ROSTER + 3 * S.UNIT_SIZE + 8),
        "unit outside the roster (a battle copy)": dict(unit=TEMP),
        "cursor + scroll >= count": dict(cursor=8, scroll=52),
        "count 0": dict(count=0),
        f"count {cap + 1} (over the list's {cap})": dict(count=cap + 1),
        "negative scroll": dict(scroll=-1),
        "id 32770 listed (past the signed-short field)": dict(families=VANILLA + [32770] * 13),
        "family 1525 (not a family base)": dict(families=VANILLA + [1525] * 13),
    }
    for name, kw in bad.items():
        m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=set(range(1000, 20000)), **kw)
        st = state(m, patched)
        sub = m.r16(ptr + S.SUBCLASS)
        check(f"{name} -> refused, nothing written", sub == 2010 and st["result"] == S.RESULT_REFUSED
              and st["presses"] == 1 and not runs[1]["error"], {"sub": sub, "state": st, "error": runs[1]["error"]})
    m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=range(1010, 1016), cursor=0, scroll=0)
    check("vanilla row 0 (Warrior 1010, 6 ranks) -> 1015: the switch is not limited to imported classes",
          m.r16(ptr + S.SUBCLASS) == 1015, m.r16(ptr + S.SUBCLASS))
    # E. the native list (no class mods): +0x1E404, cap 53
    m, runs, ptr = scenario(native, [(4, (5, 0)), (4, (5, 2))], unlocked=range(2070, 2076),
                            families=VANILLA, cursor=3, scroll=29)
    check("native-list build: row 32 of the game's own list (2070) -> 2075", m.r16(ptr + S.SUBCLASS) == 2075,
          m.r16(ptr + S.SUBCLASS))
    m, runs, ptr = scenario(native, [(4, (5, 0)), (4, (5, 2))], unlocked=range(1000, 3000), families=VANILLA,
                            count=54)
    check("native-list build: count 54 (over the game's 53) -> refused", m.r16(ptr + S.SUBCLASS) == 2010,
          state(m, native))
    pinned_m, pinned_runs, _ = scenario(pinned, [(4, (5, 0)), (4, (5, 2))], unlocked=range(2070, 2076),
                                        families=VANILLA, cursor=3, scroll=29)
    check("native-list build: the body sees the pinned exe's registers and stack",
          all(same_as(r0, r1) for r0, r1 in zip(pinned_runs, runs)), [hex(r["ended"]) for r in runs])

    if abi:
        m, runs, ptr = scenario(patched, [(4, (5, 0)), (4, (5, 2))], unlocked=ranks6)
        m2 = Machine(patched)
        m2.unlocked, m2.poison_home = set(ranks6), True
        runs2 = []
        for i, inp in enumerate(((5, 0), (5, 2))):
            m2.input = inp
            p2 = setup(m2, list_addr, fams, cursor=5, scroll=50)
            runs2.append(m2.frame(seed=i))
        calls = [c for r in runs2 for c in r["calls"]]
        check("--abi: every call from the hook enters its callee at RSP 8 mod 16",
              calls and all(c["rsp_mod16"] == 8 for c in calls), [c["rsp_mod16"] for c in calls])
        check("--abi: callees that clobber rax/rcx/rdx/r8-r11 and poison their 32-byte home space change nothing: "
              "same write, and the body sees the reference registers and stack",
              m2.r16(p2 + S.SUBCLASS) == want_fam + 5 and all(same_as(a, b) for a, b in zip(runs, runs2)),
              m2.r16(p2 + S.SUBCLASS))
        # mutants: each must fail a check above
        _, mut1, _, _ = build(pinned, lambda s: s.replace("sub rsp, 0x28\n", "sub rsp, 0x20\n")
                              .replace("add rsp, 0x28\n", "add rsp, 0x20\n"))
        mm = Machine(mut1)
        mm.unlocked = set(ranks6)
        mr = []
        for i, inp in enumerate(((5, 0), (5, 2))):
            mm.input = inp
            setup(mm, S.classtab_buffer(mut1)[0] if S.classtab_buffer(mut1) else list_addr, fams, cursor=5, scroll=50)
            mr.append(mm.frame(seed=i))
        mcalls = [c for r in mr for c in r["calls"]]
        check("--abi mutant (0x20 frame instead of 0x28): rejected -- its calls enter at RSP 0 mod 16",
              any(c["rsp_mod16"] != 8 for c in mcalls), [c["rsp_mod16"] for c in mcalls])
        _, mut2, _, _ = build(pinned, lambda s: s.replace("    jmp sc_out\nsc_hidden:", "sc_hidden:")
                              if "    jmp sc_out\nsc_hidden:" in s else
                              s.replace("mov qword ptr [rsi], rbx\njmp sc_out\n", "mov qword ptr [rsi], rbx\njmp sc_armed\n"))
        mm = Machine(mut2)
        mm.unlocked = set(ranks6)
        mm.input = (5, 2)
        p3 = setup(mm, list_addr, fams, cursor=5, scroll=50)
        mm.frame()
        check("--abi mutant (no arming frame): rejected -- it writes on the frame the tab opens",
              mm.r16(p3 + S.SUBCLASS) != 2010, mm.r16(p3 + S.SUBCLASS))
    return {"exe_bytes": len(pinned), "patched_bytes": len(patched), "list": hex(list_addr), "cap": cap,
            "state": hex(S.state_address(patched)), "abi": abi, "checks": checks,
            "pass": all(c["ok"] for c in checks)}


# ------------------------------------------------------------------------------------------ static stack audit
def static_audit(exe, entry_mod16=8):
    """walk every path of the hook from its entry (the jmp target at 0x14029CA50)"""
    import capstone
    from capstone.x86_const import X86_OP_IMM, X86_OP_REG
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    off = pe.get_offset_from_rva(S.SITE - S.exepatch.IMAGE_BASE)
    if exe[off] != 0xE9:
        return {"ok": False, "why": "site is not a jmp"}
    start = S.SITE + 5 + struct.unpack_from("<i", exe, off + 1)[0]
    soff = pe.get_offset_from_rva(start - S.exepatch.IMAGE_BASE)
    code = exe[soff:soff + 0x400]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    cache = {}

    def ins(pc):
        if pc not in cache:
            cache[pc] = next(md.disasm(code[pc - start:pc - start + 15], pc, count=1), None)
        return cache[pc]

    findings, calls, exits, r11 = [], [], [], []
    pending, seen = [(start, 0, ())], set()
    while pending:
        pc, delta, slots = pending.pop()
        if (pc, delta, slots) in seen:
            continue
        seen.add((pc, delta, slots))
        if not start <= pc < start + len(code):
            findings.append(f"path leaves the hook at {pc:#x} (not the exit jump)")
            continue
        i = ins(pc)
        if i is None:
            findings.append(f"undecodable at {pc:#x}")
            continue
        m, ops = i.mnemonic, i.operands
        if m == "push":
            delta -= 8
            slots = tuple(sorted(slots + (delta,)))
        elif m == "pop":
            slots = tuple(x for x in slots if x != delta)
            delta += 8
        elif m in ("sub", "add") and ops[0].type == X86_OP_REG and i.reg_name(ops[0].reg) == "rsp":
            if ops[1].type != X86_OP_IMM:
                findings.append(f"rsp {m} by a register at {pc:#x}")
                continue
            delta += -ops[1].imm if m == "sub" else ops[1].imm
        elif m == "ret":
            findings.append(f"ret at {pc:#x}")
            continue
        elif m == "call":
            clear = min((s for s in slots if s >= delta), default=0) - delta
            calls.append({"pc": hex(pc), "target": i.op_str, "rsp_mod16": (entry_mod16 + delta) % 16,
                          "home_clearance": clear})
            if (entry_mod16 + delta) % 16 != 0 or clear < 32:
                findings.append(f"call at {pc:#x}: rsp mod 16 {(entry_mod16 + delta) % 16}, home {clear}")
        elif m == "mov" and i.op_str == "r11, rsp":
            r11.append({"pc": hex(pc), "delta": delta})
            if delta != 0:
                findings.append(f"displaced `mov r11, rsp` at delta {delta}")
        elif any(i.reg_name(r) == "rsp" for r in i.regs_access()[1]):
            findings.append(f"unhandled rsp write {m} {i.op_str} at {pc:#x}")
            continue
        nxt = pc + i.size
        if m.startswith("j"):
            if not ops or ops[0].type != X86_OP_IMM:
                findings.append(f"indirect branch at {pc:#x}")
                continue
            tgt = ops[0].imm
            if not start <= tgt < start + len(code):
                exits.append({"pc": hex(pc), "target": hex(tgt), "delta": delta})
                if tgt != S.SITE_RET or delta != -0xB8 or m != "jmp":
                    findings.append(f"exit {m} to {tgt:#x} at delta {delta}")
                continue
            pending.append((tgt, delta, slots))
            if m == "jmp":
                continue
        pending.append((nxt, delta, slots))
    return {"ok": not findings and bool(exits), "entry": hex(start), "entry_mod16": entry_mod16, "calls": calls,
            "exits": exits, "displaced_mov_r11": r11, "findings": findings, "states": len(seen)}


def prove_static(pinned):
    classes, patched, _, native = build(pinned)
    from d5lib import newclasses as N
    prev = exemap.ACTIVE
    exemap.use(exemap.translator_for(pinned))
    try:
        try:
            mod = N.stack_mod16(pinned, None, site=S.SITE)
            measured = True
        except ValueError:
            mod, measured = 8, False
    finally:
        exemap.use(prev)
    # the caller tail-jumps (0x14029A426 jmp after add rsp,0x20 / pop rbx): the entry RSP is its own entry RSP
    out = {"entry_mod16": mod, "measured": measured,
           "relocated": static_audit(patched, mod), "native": static_audit(native, mod)}
    checks = [{"check": f"static stack audit, {k} build: {len(v['calls'])} calls aligned with >= 32 bytes home, "
                        f"{len(v['exits'])} exit(s) to 0x14029CA5C at -0xB8, displaced mov r11,rsp at 0, 0 findings",
               "ok": v["ok"], "got": v} for k, v in (("relocated", out["relocated"]), ("native", out["native"]))]
    checks.append({"check": "entry RSP mod 16 = 8 (function entry)", "ok": mod == 8, "got": mod})
    return {"static": out, "checks": checks, "pass": all(c["ok"] for c in checks)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    path = Path(a.exe) if a.exe else find_pinned()
    if not path or not path.is_file():
        print("no pinned exe (EXE__disgaea5.exe.full) found; pass --exe", file=sys.stderr)
        return 2
    raw = path.read_bytes()
    receipt = prove_static(raw) if a.static else prove(raw, a.abi)
    receipt["exe"] = str(path)
    text = json.dumps(receipt, indent=1, default=lambda o: o.hex() if isinstance(o, bytes) else str(o))
    if a.out:
        Path(a.out).write_text(text)
    for c in receipt["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"])
    print("OVERALL", "PASS" if receipt["pass"] else "FAIL")
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
