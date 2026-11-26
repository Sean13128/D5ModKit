"""NEMO1 offline proof: Nemo (D4 820 Physical Malice, row 27820 = kit family summon_malice) through the pinned game's REAL patched site: wrap_revenge at the
one call of turn_per_unit_end_round_upkeep in the round-edge sweep of turn_ctl_s6_update (0x1405F8FFC) -> evil_nemo, on the kit build of the exe and, as
control, on the pinned original.  Real game code runs for events_env_team_of; stubs (each logs its arguments and rsp % 16 and poisons the volatile registers):
the game's own turn_per_unit_end_round_upkeep (0x1401E5AF0), unit_spawn_from_request (records the 0x40-byte request and builds the new unit's battle / unit
record where the game would), FUN_1401C3A00 (the living-unit count: base + spawns so far), events_clear_pick_cell (0x14023AFA0: rebuilds the free-cell
grid 0x144DF1790 from a scripted set, minus every cell a living unit stands on, as the real function does), game_rng_draw (0x140136660: scripted values,
reduced modulo the argument unless a case asks for raw garbage), map_surface_height_at (0x1401CF4D0: y = 0.5, records xmm0 / xmm1) and FUN_1401367F0 (the
facing draw).  The row is read from d5lib/importers/d4-evility-overlay.json.

<unicorn python> evility/offline_proof_nemo1.py [--abi] [--control NAME]
Controls (a deliberately broken wrapper; the proof must then FAIL): nm-row, nm-cap, nm-hp, nm-active, nm-team, nm-clear, nm-radius, nm-level, nm-none,
nm-order, nm-draw, nm-pos, nm-align (needs --abi)

NOT covered (live-needed): the real unit_spawn_from_request body, events_clear_pick_cell on a real map, the unit's AI, side and behaviour on the map, its
cleanup at battle end, that the sweep reaches a unit once per round (read in the decomp of turn_ctl_s6_update, not run).
"""
import argparse
import hashlib
import json
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(KIT), str(KIT / "evility"), str(KIT / "tools")]
from d5lib import evility as ev                                                  # noqa: E402
import offline_proof_d4sig7 as d4                                                # noqa: E402
import offline_proof_necro1 as nc                                                # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402

SCRATCH = Path("/Volumes/Data/ai-tmp/claude/nemo1")
OVERLAY = KIT / "d5lib/importers/d4-evility-overlay.json"
NEMO = 27820
SITE, ORIG_FN, CLEAR, RNG, HEIGHT, FACE, COUNT, SPAWN = (0x1405F8FFC, 0x1401E5AF0, 0x14023AFA0, 0x140136660, 0x1401CF4D0, 0x1401367F0,
                                                         0x1401C3A00, 0x1401C5AE0)
GRID, EXT_X, EXT_Z = 0x144DF1790, 0x144BD9780, 0x144BD9784
BREC0, BSTRIDE = nc.BREC0, nc.BSTRIDE
POISON = nc.POISON
ORIG_RET = 0x6C6C
STAND = ev.MALICE_STANDINS
GUARDIAN = nc.GUARDIAN


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    a = text.index("evil_nemo:")
    b = text.index("// D4SIG7: wrap_atkcount(", a)
    w = text[a:b]
    out = SCRATCH / f"d5evil-nemo1-{control}.inc.asm"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    edits = {
        "nm-row": ("    test eax, eax\n    jz .nm_ret                          // not a holder", "    nop"),
        "nm-cap": ("    cmp eax, 0x20\n    jge .nm_ret                         // the 32-unit limit", ""),
        "nm-hp": ("    cmp qword ptr [rbx + 0x2cc8], 0\n    jle .nm_ret                         // defeated", ""),
        "nm-active": ("    cmp byte ptr [r12 + 0x2e8], 0\n    je .nm_ret                          // not on the map", ""),
        "nm-team": ("    mov r13d, 4                         // a player-side holder", "    mov r13d, 0                         // a player-side holder"),
        "nm-clear": ("    call 0x14023afa0                    // events_clear_pick_cell", "    nop\n    nop\n    nop\n    nop\n    nop                    // events_clear_pick_cell"),
        "nm-radius": ("    lea eax, [r14 + 10]\n    cmp eax, ecx\n    cmovg eax, ecx\n    mov ecx, 127", "    lea eax, [r14 + 11]\n    cmp eax, ecx\n    cmovg eax, ecx\n    mov ecx, 127"),
        "nm-level": ("    add eax, esi\n    mov ecx, 1", "    mov ecx, 1"),
        "nm-none": ("    test r14d, r14d\n    jz .nm_ret                          // no free cell near the holder", "    nop"),
        "nm-order": ("    mov eax, esi\n    shl eax, 7\n    add eax, edi\n    mov rcx, 0x144df1790\n    cmp byte ptr [rcx + rax], 0\n    je .nm_pzn",
                     "    mov eax, edi\n    shl eax, 7\n    add eax, esi\n    mov rcx, 0x144df1790\n    cmp byte ptr [rcx + rax], 0\n    je .nm_pzn"),
        "nm-draw": ("    mov ecx, r14d\n    call 0x140136660                    // game_rng_draw(free cells): the cell", "    lea ecx, [r14 + 1]\n    call 0x140136660                    // game_rng_draw(free cells): the cell"),
        "nm-pos": ("    lea eax, [rax*4 + 6]\n    cvtsi2ss xmm0, eax", "    lea eax, [rax*4 + 0]\n    cvtsi2ss xmm0, eax"),
        "nm-align": ("sub rsp, 0x78", "sub rsp, 0x70"),
    }
    old, new = edits[control]
    assert w.count(old) >= 1, (control, w.count(old))
    if control == "nm-none":    # "no free cell" is guarded three times (explicit test, the draw bound, the scan running out): break all three
        for o2, n2 in (("    cmp eax, r14d\n    jae .nm_ret\n    mov r14d, eax", "    mov r14d, eax"),
                       (".nm_px:\n    cmp esi, dword ptr [rsp + 0x64]\n    jg .nm_ret", ".nm_px:\n    cmp esi, dword ptr [rsp + 0x64]\n    jg .nm_found")):
            assert w.count(o2) == 1, o2
            w = w.replace(o2, n2)
    if control == "nm-align":
        w = w.replace("add rsp, 0x78", "add rsp, 0x70")
    out.write_text(text[:a] + w.replace(old, new, 1 if control != "nm-align" else 99) + text[b:])
    return out


def overlay_row():
    return json.loads(OVERLAY.read_text())["mods"]["D4_Unique_220"]["behaviors"]["evilities"][str(NEMO)]


def req_bytes(x, z, facing, char, level, team, y=0.5):
    return struct.pack("<Qfffiiiiiii", 0, x, y, z, facing, char, level, 0, team, 0, -1) + bytes(0x10)


def cell_xz(gx, gz):
    return float(gx * 12 + 6), float(gz * 12 + 6)


def scan_window(cells, cx, cz, ext=(128, 128), radius=10):
    """the free cells of the window in the game's scan order: x outer, z inner"""
    x0, x1 = max(cx - radius, 0), min(cx + radius, ext[0] - 1, 127)
    z0, z1 = max(cz - radius, 0), min(cz + radius, ext[1] - 1, 127)
    return sorted(c for c in cells if x0 <= c[0] <= x1 and z0 <= c[1] <= z1)


class Rig(nc.Rig):
    def __init__(self, exe):
        super().__init__(exe)
        from unicorn import UC_HOOK_CODE
        e, X = self.e, self.e.X
        self.rng, self.raw, self.cells, self.face_val = [], False, set(), 1

        def vol():
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                e.mu.reg_write(r, POISON)

        def rsp16():
            return e.mu.reg_read(X.UC_X86_REG_RSP) % 16

        def orig():
            self.log.append(("orig", tuple(e.mu.reg_read(r) for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX)), rsp16()))
            vol()
            return ORIG_RET

        def clear():
            self.log.append(("clear", e.mu.reg_read(X.UC_X86_REG_RCX), rsp16()))
            g = bytearray(0x4000)
            occupied = set()
            for s in range(256):
                va = BREC0 + s * BSTRIDE
                if e.read(va + 0x2E8, 1)[0]:
                    u = struct.unpack("<Q", e.read(va + 0x240, 8))[0]
                    if u and struct.unpack("<q", e.read(u + 0x2CC8, 8))[0] > 0:
                        x, z = struct.unpack("<f", e.read(va + 8, 4))[0], struct.unpack("<f", e.read(va + 0x10, 4))[0]
                        occupied.add((int(x / 12), int(z / 12)))
            for gx, gz in self.cells - occupied:
                g[gx * 128 + gz] = 1
            e.mu.mem_write(GRID, bytes(g))
            vol()
            return 0

        def rng():
            arg = e.mu.reg_read(X.UC_X86_REG_RCX) & 0xFFFFFFFF
            self.log.append(("rng", arg, rsp16()))
            v = self.rng.pop(0) if self.rng else 0
            vol()
            return v if self.raw else (v % arg if arg else 0)

        def height():
            xm0 = struct.unpack("<f", (e.mu.reg_read(X.UC_X86_REG_XMM0) & 0xFFFFFFFF).to_bytes(4, "little"))[0]
            xm1 = struct.unpack("<f", (e.mu.reg_read(X.UC_X86_REG_XMM1) & 0xFFFFFFFF).to_bytes(4, "little"))[0]
            self.log.append(("height", xm0, xm1, rsp16()))
            vol()
            e.mu.reg_write(X.UC_X86_REG_XMM0, struct.unpack("<I", struct.pack("<f", 0.5))[0])
            return 0

        def face():
            self.log.append(("face", rsp16()))
            vol()
            return self.face_val
        hooked = set(e.stubs)           # the emulator already hooks game_rng_draw: a second hook would run the stub twice
        e.stubs[ORIG_FN], e.stubs[CLEAR], e.stubs[RNG], e.stubs[HEIGHT], e.stubs[FACE] = orig, clear, rng, height, face
        for a in (ORIG_FN, CLEAR, RNG, HEIGHT, FACE):
            if a not in hooked:
                e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=a, end=a)

    def world(self):
        super().world()
        self.rng, self.raw, self.cells, self.face_val = [], False, set(), 1
        self.e.mu.mem_write(GRID, bytes([1]) * 0x4000)         # junk: only a grid rebuilt by events_clear_pick_cell may be trusted
        self.e.mu.mem_write(EXT_X, struct.pack("<ii", 128, 128))

    def go_round(self, unit_va, brec_va, abi, section):
        self.log.clear()
        ret = self.start(SITE, dict(rcx=unit_va, rdx=brec_va), {}, abi, section, None)
        return ret, self.log[:]


_K = {}


def kits():
    if "kit" not in _K:
        rows = {NEMO: overlay_row(), 27868: {"family": "raise_zombie"}, 27836: {"family": "face_target_away"},
                121: {"family": "regen", "effects": [{"value": 1, "stat": "hp"}]}}
        assert rows[NEMO] == {"family": "summon_malice"}, rows[NEMO]
        patched = ev.build_patch(ORIGINAL.read_bytes(), rows)
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="nm1-", dir=SCRATCH))
        (tmp / "kit.exe").write_bytes(patched)
        _K["kit"] = (Rig(tmp / "kit.exe"), (info["code"], info["base"] + len(info["data"])), hashlib.sha256(patched).hexdigest())
        _K["control"] = Rig(ORIGINAL)
    return _K["kit"], _K["control"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--control")
    args = ap.parse_args()
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == ORIGINAL_SHA
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    (kit, section, sha), control = kits()
    abi = args.abi
    fails, n = [], 0

    def report(name, problems):
        nonlocal n
        n += 1
        if problems:
            fails.append(name)
        print(("ok   " if not problems else "FAIL ") + name + ("" if not problems else ": " + "; ".join(problems)))

    HOLD = (NEMO,)
    CELLS = {(19, 25), (20, 22), (21, 18), (22, 19), (25, 24)}      # around the holder's cell (20, 20)

    def case(name, *, holder=HOLD, hteam=0, hp=800, level=33, cell=(20, 20), cells=CELLS, rng=(3, 17, 2), face=1, active=1, unit=True,
             live=0, ext=(128, 128), raw=False, expect=1, extra=None, stat_idx=None):
        """the holder in slot 1; expect = number of spawns (0 or 1)"""
        problems = []
        for rig, is_kit in ((kit, True), (control, False)):
            rig.world()
            rig.live_base, rig.rng, rig.raw, rig.cells, rig.face_val = live, list(rng), raw, set(cells), face
            rig.e.mu.mem_write(EXT_X, struct.pack("<ii", *ext))
            x, z = cell_xz(*cell)
            brec, u = rig.put(1, ids=holder, hp=hp, team=hteam, char=100, level=level, x=x, z=z, active=active, unit=unit)
            if u and stat_idx is not None:
                rig.e.mu.mem_write(u + 0x4348, struct.pack("<I", stat_idx))
            ret, log = rig.go_round(u, brec, abi and is_kit, section)
            who = "kit" if is_kit else "pinned"
            origs = [x_ for x_ in log if x_[0] == "orig"]
            if ret != ORIG_RET or len(origs) != 1 or origs[0][1][0] != u or origs[0][1][1] != brec:
                problems.append(f"{who}: turn_per_unit_end_round_upkeep not entered once with the site arguments / result not returned: {log} {ret:#x}")
            spawns = [x_ for x_ in log if x_[0] == "spawn"]
            if is_kit:
                if len(spawns) != expect:
                    problems.append(f"spawns {len(spawns)}, expected {expect}: {[x_[0] for x_ in log]}")
                if any(x_[0] in ("clear", "rng", "height", "face") and x_[-1] != 8 for x_ in log):
                    problems.append(f"a call entered with rsp % 16 != 8: {log}")
                if expect and spawns:
                    free = scan_window(cells, *cell, ext=ext)
                    v, lv, c = rng
                    char = STAND[v % len(STAND)]
                    L = level if level > 0 else 1
                    lvl = max(1, L * 60 // 100 + ((lv % 40) * L) // 100)
                    team = 4 if hteam == 0 else hteam
                    gx, gz = free[c % len(free)]
                    wx, wz = cell_xz(gx, gz)
                    want = req_bytes(wx, wz, face * 90 - 90, char, lvl, team)
                    if spawns[0][1] != want:
                        problems.append(f"request {spawns[0][1].hex()} != {want.hex()}")
                    if spawns[0][2] != 8:
                        problems.append(f"unit_spawn_from_request entered with rsp % 16 = {spawns[0][2]}")
                    seq = [x_[0] for x_ in log]
                    if seq != ["orig", "count", "clear", "rng", "rng", "rng", "height", "face", "spawn"]:
                        problems.append(f"call order {seq}")
                    draws = [x_[1] for x_ in log if x_[0] == "rng"]
                    if draws != [len(STAND), 40, len(free)]:
                        problems.append(f"game_rng_draw arguments {draws}, expected {[len(STAND), 40, len(free)]}")
                    hv = [x_ for x_ in log if x_[0] == "height"][0]
                    if (hv[1], hv[2]) != (wx, wz):
                        problems.append(f"map_surface_height_at got {hv[1:3]}, expected {(wx, wz)}")
                if extra:
                    problems += extra(rig, log)
            elif spawns:
                problems.append(f"pinned exe made a spawn call: {spawns}")
            elif [x_ for x_ in log if x_[0] != "orig"]:
                problems.append(f"pinned exe called more than the original: {log}")
        report(name, problems)

    # ---- the main rule and the teams
    case("a player holder (team 0): one request - character from the list, level formula, a free cell in the window, team 4")
    case("an enemy holder (team 1): team 1", hteam=1)
    case("a holder on team 4: team 4", hteam=4)
    case("a holder on team 5 (charmed): team 5", hteam=5)
    case("a holder on team 3 does nothing", hteam=3, expect=0)
    case("a holder on team 2 does nothing", hteam=2, expect=0)
    case("an unknown holder team 9 does nothing", hteam=9, expect=0)
    # ---- who holds the row
    case("no row: nothing, the upkeep result untouched", holder=(), expect=0)
    case("another second-word row only (face_target_away): nothing", holder=(27836,), expect=0)
    case("Necromancy's row only: nothing", holder=(27868,), expect=0)
    case("an ordinary row only (regen): nothing", holder=(121,), expect=0)
    case("the row among other ids: one spawn", holder=(5, 9, NEMO, 40000))
    # ---- holder state
    case("a defeated holder (HP 0): nothing", hp=0, expect=0)
    case("a holder with negative HP: nothing", hp=-5, expect=0)
    case("an inactive record: nothing", active=0, expect=0)
    case("no unit record: nothing", unit=False, expect=0)
    case("a unit record without a stat record (index 0x28A): nothing", stat_idx=0x28A, expect=0)
    # ---- the 32-unit limit
    case("31 living units: one spawn", live=31)
    case("32 living units: nothing", live=32, expect=0)
    case("40 living units: nothing", live=40, expect=0)
    # ---- free cells: radius 10 square, map extents, none free
    case("no free cell anywhere: nothing", cells=set(), expect=0)
    case("free cells only outside the radius (x + 11, z + 11 and x - 11): nothing", cells={(31, 20), (20, 31), (9, 20), (20, 9)}, expect=0)
    case("a free cell at distance exactly 10 on the x axis only", cells={(30, 20)}, rng=(0, 0, 0))
    case("a free cell at distance exactly 10 on the z axis only", cells={(20, 10)}, rng=(24, 39, 0))
    case("the window corner (+10, +10) counts", cells={(30, 30)}, rng=(5, 5, 0))
    case("one cell past the corner (+11, +10) does not", cells={(31, 30), (30, 31)}, expect=0)
    case("a cell inside and one outside: the draw argument counts the window only", cells={(21, 21), (45, 20)}, rng=(2, 2, 7))
    case("holder at cell (2, 3): the window clamps at 0, cell (0, 0) counts", cell=(2, 3), cells={(0, 0), (12, 13), (13, 14)}, rng=(1, 1, 0))
    case("holder at the map corner (29, 29) on a 30 x 30 map: cells past the extents do not count", cell=(29, 29), ext=(30, 30),
         cells={(30, 29), (29, 30), (31, 31)}, expect=0)
    case("the same map: a cell inside the extents does", cell=(29, 29), ext=(30, 30), cells={(30, 29), (29, 25), (20, 29)}, rng=(1, 1, 1))
    case("holder at cell (120, 125): the window ends at 127", cell=(120, 125), cells={(127, 127)}, rng=(1, 1, 0))
    case("the holder's own cell is not free (the rebuilt grid leaves it out): nothing when it is the only flagged cell", cells={(20, 20)}, expect=0)
    # ---- the draws: characters, levels, cells, facing
    for v in (0, 1, 12, 24):
        case(f"character draw {v} -> {STAND[v]}", rng=(v, 7, 1))
    for lv_draw in (0, 1, 39):
        case(f"level draw {lv_draw} at L=33", rng=(3, lv_draw, 0))
    for L in (1, 2, 9, 33, 99, 255, 9999, 32767):
        case(f"holder level {L}: the level formula", level=L, rng=(4, 39, 1))
    for L in (0, -3):
        case(f"holder level {L}: treated as 1", level=L, rng=(4, 39, 1))
    for c in range(5):
        case(f"cell draw {c}: the {c}-th free cell in scan order (x outer, z inner)", rng=(2, 2, c))
    for fv in (0, 1, 2, 3):
        case(f"facing draw {fv} -> {fv * 90 - 90}", face=fv)
    # ---- a garbage random draw: nothing is written, the upkeep still runs once
    for label, rngs in (("character draw 25", (25, 0, 0)), ("character draw 0x7FFFFFFF", (0x7FFFFFFF, 0, 0)), ("level draw 40", (3, 40, 0)),
                        ("cell draw 5", (3, 3, 5))):
        problems = []
        kit.world()
        kit.rng, kit.raw, kit.cells = list(rngs), True, set(CELLS)
        x, z = cell_xz(20, 20)
        brec, u = kit.put(1, ids=HOLD, hp=800, team=0, char=100, level=33, x=x, z=z)
        ret, log = kit.go_round(u, brec, abi, section)
        if ret != ORIG_RET or [x_[0] for x_ in log].count("spawn") or [x_[0] for x_ in log].count("orig") != 1:
            problems.append(str(log))
        report(f"garbage {label}: no spawn, upkeep entered once", problems)
    # ---- spawn returns garbage: nothing else happens
    for label, slot in (("-1", -1), ("256", 256), ("0x7FFFFFFF", 0x7FFFFFFF)):
        problems = []
        kit.world()
        kit.ret_slots, kit.rng, kit.cells = [slot], [1, 1, 1], set(CELLS)
        x, z = cell_xz(20, 20)
        brec, u = kit.put(1, ids=HOLD, hp=800, team=0, char=100, level=33, x=x, z=z)
        ret, log = kit.go_round(u, brec, abi, section)
        if ret != ORIG_RET or [x_[0] for x_ in log].count("spawn") != 1 or [x_[0] for x_ in log].count("orig") != 1:
            problems.append(str(log))
        report(f"spawn returns {label}: upkeep result intact, one request", problems)
    # ---- two holders in one round sweep: each spawns once, on different cells (the second grid excludes the first spawn)
    problems = []
    kit.world()
    kit.cells, kit.rng = {(20, 21), (21, 20)}, [0, 0, 0, 0, 0, 0]
    x, z = cell_xz(20, 20)
    b1, u1 = kit.put(1, ids=HOLD, hp=800, team=0, char=100, level=33, x=x, z=z)
    b2, u2 = kit.put(2, ids=HOLD, hp=800, team=1, char=100, level=40, x=x + 12, z=z + 12)
    r1, l1 = kit.go_round(u1, b1, abi, section)
    r2, l2 = kit.go_round(u2, b2, abi, section)
    q1 = [x_[1] for x_ in l1 if x_[0] == "spawn"]
    q2 = [x_[1] for x_ in l2 if x_[0] == "spawn"]
    if len(q1) != 1 or len(q2) != 1 or q1[0][8:12] == q2[0][8:12] and q1[0][16:20] == q2[0][16:20]:
        problems.append(f"{len(q1)} / {len(q2)} spawns, same cell: {[q[:24].hex() for q in q1 + q2]}")
    report("two holders (teams 0 and 1) in one sweep: one request each, the second on a cell the first spawn left free", problems)
    # ---- a unit that is not a holder never changes anything besides the original call
    problems = []
    kit.world()
    kit.cells = set(CELLS)
    x, z = cell_xz(20, 20)
    brec, u = kit.put(1, ids=(5, 6), hp=800, team=0, char=100, level=33, x=x, z=z)
    before = bytes(kit.e.read(u, 0x4800))
    ret, log = kit.go_round(u, brec, abi, section)
    if [x_[0] for x_ in log] != ["orig"] or ret != ORIG_RET or bytes(kit.e.read(u, 0x4800)) != before:
        problems.append(str(log))
    report("a non-holder: only the original upkeep, nothing called, unit record unchanged", problems)
    problems = []
    kit.world()
    kit.cells, kit.rng = set(CELLS), [3, 17, 2]
    x, z = cell_xz(20, 20)
    brec, u = kit.put(1, ids=HOLD, hp=800, team=0, char=100, level=33, x=x, z=z)
    before = bytes(kit.e.read(u, 0x4800))
    ret, log = kit.go_round(u, brec, abi, section)
    if bytes(kit.e.read(u, 0x4800)) != before:
        problems.append("the holder's own unit record changed")
    report("a holder's own unit record is unchanged by the spawn pass", problems)
    # ---- Summon Guardian's code is untouched
    a, ln = GUARDIAN
    k_bytes, c_bytes = bytes(kit.e.read(a, ln)), bytes(control.e.read(a, ln))
    problems = [] if k_bytes == c_bytes else ["sequencer_ctl_s4_update differs between the kit build and the pinned exe"]
    sites = [s_ for t_, tgt, ss in ev.WRAPPERS for s_ in ss if a <= s_ < a + ln]
    if sites:
        problems.append(f"patch sites inside Summon Guardian's function: {sites}")
    report("Summon Guardian's function (sequencer_ctl_s4_update, 3183 bytes) is byte-identical to the pinned exe and holds no patch site", problems)

    print(f"{n - len(fails)}/{n} checks passed (NEMO1 summon_malice, {'abi' if abi else 'behavior'}; patched exe {sha[:16]}"
          f"{', control ' + args.control if args.control else ''})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
