"""SUPERSEDED by offline_proof_necro2.py (NECRO2, 2026-11-14).  This file models the end-of-action pass with the victim still ACTIVE and no damage-apply
step; live that state does not exist (the game retires the victim first), so 26 of its 62 checks fail against the NECRO2 code BY DESIGN (they expect an
end-pass-only spawn).  Its Rig and helpers are still used by offline_proof_nemo1.py and offline_proof_necro2.py.

NECRO1 offline proof: Necromancer (D4 868 Necromancy, row 27868 = kit family raise_zombie) through the pinned game's REAL patched site:
wrap_face_away at the call of post_hit_effects in exec_ctl_s2_update (0x14053FE71) -> evil_necro, on the kit build of the exe and, as control,
on the pinned original.  Real game code runs for events_env_team_of, model_team_is_hostile and events_env_is_object_rec; stubs: the game's own
post_hit_effects, unit_spawn_from_request (records the 0x40-byte request and builds the new unit's battle / unit record where the game would)
and FUN_1401C3A00 (the living-unit count: base + zombies made so far).  The row is read from d5lib/importers/d4-evility-overlay.json.

<unicorn python> evility/offline_proof_necro1.py [--abi] [--control NAME]
Controls (a deliberately broken wrapper; the proof must then FAIL): nc-hostile, nc-ko, nc-hp (HP test and cell test both removed), nc-cap, nc-cell, nc-hp1, nc-team, nc-row,
nc-undead, nc-object, nc-carry, nc-align (needs --abi)

NOT covered (live-needed): the real unit_spawn_from_request body, the unit's AI, side and behaviour on the map, its cleanup at battle end.
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
import offline_proof_longtail3 as lt3                                            # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402

SCRATCH = Path("/Volumes/Data/ai-tmp/claude/necro1")
OVERLAY = KIT / "d5lib/importers/d4-evility-overlay.json"
NEC = 27868
SITE, SPAWN, COUNT = 0x14053FE71, 0x1401C5AE0, 0x1401C3A00
BREC0, BSTRIDE, SR0, SR_STRIDE = 0x141BA33B0, 0x1260, 0x141067DC8, 0xE98
POISON = lt3.POISON
GUARDIAN = (0x140552D20, 3183)               # sequencer_ctl_s4_update: Summon Guardian's spawn block lives in it


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    a = text.index("evil_necro:")
    b = text.index("// D4SIG7: wrap_atkcount(", a)
    w = text[a:b]
    out = SCRATCH / f"d5evil-necro1-{control}.inc.asm"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    edits = {
        "nc-hostile": ("    test al, al\n    jz .nc_next\n    mov rsi, 0x141ba33b0", "    mov rsi, 0x141ba33b0"),
        "nc-ko": ("    cmp byte ptr [rbx + rbp + 0x152e], 0\n    je .nc_next", ""),
        "nc-hp": ("    cmp qword ptr [rdi + 0x2cc8], 0\n    jg .nc_next                         // still standing", ""),   # also needs nc-cell: the cell test alone blocks a standing victim
        "nc-cap": ("    cmp eax, 0x20\n    jge .nc_ret", ""),
        "nc-cell": ("    cmp edx, dword ptr [r14 + 0x10]\n    je .nc_next", "    cmp edx, dword ptr [r14 + 0x10]\n    nop"),
        "nc-hp1": ("    mov qword ptr [rax + 0x2cc8], 1     // HP 1", "    nop"),
        "nc-team": ("    mov eax, 4                          // a player-side holder", "    mov eax, 0                          // a player-side holder"),
        "nc-row": ("    test eax, eax\n    jz .nc_ret                          // not a holder", "    nop"),
        "nc-undead": ("    cmp eax, 5\n    jbe .nc_next                        // already an Undead: no zombie of a zombie", "    cmp eax, 5\n    nop"),
        "nc-object": ("    test al, al\n    jnz .nc_next\n    mov eax, dword ptr [rdi + 0x2e04]", "    mov eax, dword ptr [rdi + 0x2e04]"),
        "nc-carry": ("    cmp word ptr [r14 + 0x2ee], 0\n    jge .nc_next                        // carried", ""),
        "nc-align": ("sub rsp, 0x78", "sub rsp, 0x70"),
    }
    old, new = edits[control]
    assert w.count(old) >= 1, (control, w.count(old))
    if control == "nc-hp":      # the HP test is backed up by the cell test (a standing victim is a living unit on its own cell): break both
        o2, n2 = edits["nc-cell"]
        w = w.replace(o2, n2)
    if control == "nc-align":
        w = w.replace("add rsp, 0x78", "add rsp, 0x70")
    out.write_text(text[:a] + w.replace(old, new, 1 if control != "nc-align" else 99) + text[b:])
    return out


def overlay_row():
    return json.loads(OVERLAY.read_text())["mods"]["D4_Class_1250"]["behaviors"]["evilities"][str(NEC)]


def req_bytes(x, y, z, facing, level, team, char=2090):
    return struct.pack("<Qfffiiiiiii", 0, x, y, z, facing, char, level, 0, team, 0, -1) + bytes(0x10)


class Rig(lt3.Rig):
    def __init__(self, exe):
        super().__init__(exe)
        from unicorn import UC_HOOK_CODE
        e, X = self.e, self.e.X
        self.live_base, self.ret_slots, self.zombies = 0, [], 0
        e.mu.mem_write(SR0, bytes(SR_STRIDE * 0x28A))

        def spawn():
            mu = e.mu
            rcx, rsp = mu.reg_read(X.UC_X86_REG_RCX), mu.reg_read(X.UC_X86_REG_RSP)
            req = bytes(e.read(rcx, 0x40))
            slot = self.ret_slots.pop(0) if self.ret_slots else 200 + self.zombies
            self.log.append(("spawn", req, rsp % 16))
            if 0 <= slot < 256:
                self.zombies += 1
                x, y, z, fac, ch, lvl, _, team = struct.unpack_from("<fffiiiii", req, 8)
                self.put(slot, ids=(), hp=1000, team=team, char=ch, level=lvl, x=x, y=y, z=z, facing=fac, keep=True)
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                mu.reg_write(r, POISON)
            return slot & 0xFFFFFFFF

        def count():
            mu = e.mu
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                mu.reg_write(r, POISON)
            self.log.append(("count",))
            return self.live_base + self.zombies
        e.stubs[SPAWN], e.stubs[COUNT] = spawn, count
        for a in (SPAWN, COUNT):
            e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=a, end=a)

    def world(self):
        self.e.mu.mem_write(BREC0, bytes(256 * BSTRIDE))
        self.zombies, self.live_base, self.ret_slots = 0, 0, []
        self.e.brk = self.e.heap_mark

    def put(self, slot, *, ids=(), hp=0, team=1, char=100, level=33, x=30.0, y=0.5, z=18.0, facing=90, active=1, unit=True,
            carrier=-1, carrying=-1, keep=False):
        e = self.e
        b = bytearray(BSTRIDE)
        u = 0
        if unit:
            ub = d4.dunit(ids, slot + 1)
            struct.pack_into("<q", ub, 0x2CC8, hp)
            struct.pack_into("<q", ub, 0x2CD8, 1000)
            struct.pack_into("<i", ub, 0x2E04, char)
            struct.pack_into("<h", ub, 0x2DFC, level)
            ub[0x2E32] = team
            u = e.alloc(bytes(ub)) if not keep else e.alloc(bytes(ub))
        struct.pack_into("<Q", b, 0x240, u)
        b[0x2E8] = active
        struct.pack_into("<fff", b, 8, x, y, z)
        struct.pack_into("<h", b, 0x2C4, facing)
        struct.pack_into("<hh", b, 0x2EE, carrier, carrying)
        va = BREC0 + slot * BSTRIDE
        e.mu.mem_write(va, bytes(b))
        return va, u

    def unit_of(self, slot):
        return struct.unpack("<Q", self.e.read(BREC0 + slot * BSTRIDE + 0x240, 8))[0]

    def hp_of(self, slot):
        return struct.unpack("<q", self.e.read(self.unit_of(slot) + 0x2CC8, 8))[0]

    def go(self, ctx, att_slot, abi, section):
        self.log.clear()
        ctl = self.e.alloc(bytes(0x100))
        att = BREC0 + att_slot * BSTRIDE if att_slot is not None else 0
        ret = self.start(SITE, dict(rcx=ctl, rdx=ctx, r8=att), {}, abi, section, None)
        return ret, self.log[:], (ctl, ctx, att)


_K = {}


def kits():
    if "kit" not in _K:
        rows = {NEC: overlay_row(), 27836: {"family": "face_target_away"}, 121: {"family": "regen", "effects": [{"value": 1, "stat": "hp"}]},
                27802: {"family": "self_destruct", "effects": [{"value": 10}]}}
        assert rows[NEC] == {"family": "raise_zombie"}, rows[NEC]
        patched = ev.build_patch(ORIGINAL.read_bytes(), rows)
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="nc1-", dir=SCRATCH))
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

    HOLD = (NEC,)

    def case(name, *, holder=HOLD, hteam=0, vteam=1, vchar=100, vhp=0, killed=1, active=1, level=33, x=30.0, z=18.0, facing=90, unit=True,
             carrier=-1, carrying=-1, live=0, living_there=False, ret_slots=None, expect=1, expect_team=None, extra=None, result=40):
        """one victim in slot 5, the attacker in slot 1; expect = number of spawns"""
        problems = []
        for rig, is_kit in ((kit, True), (control, False)):
            rig.world()
            rig.live_base = live
            if ret_slots is not None:
                rig.ret_slots = list(ret_slots)
            rig.put(1, ids=holder, hp=800, team=hteam, char=500, x=6.0, z=6.0)
            va, vu = rig.put(5, hp=vhp, team=vteam, char=vchar, level=level, x=x, z=z, facing=facing, active=active, unit=unit,
                             carrier=carrier, carrying=carrying)
            if living_there:
                rig.put(9, hp=500, team=vteam, char=300, x=x, z=z)
            before = bytes(rig.e.read(vu, 0x4800)) if vu else b""
            ctx = rig.action([(5, result, killed)])
            ret, log, (ctl, c, att) = rig.go(ctx, 1, abi and is_kit, section)
            spawns = [x_ for x_ in log if x_[0] == "spawn"]
            posts = [x_ for x_ in log if x_[0] == "post"]
            who = "kit" if is_kit else "pinned"
            if ret != 0x7B7B or posts != [("post", (ctl, c, att))]:
                problems.append(f"{who}: post_hit_effects not entered once with the site arguments / result not returned: {log} {ret:#x}")
            if is_kit:
                if len(spawns) != expect:
                    problems.append(f"spawns {len(spawns)}, expected {expect}")
                if expect and spawns:
                    team = expect_team if expect_team is not None else (4 if hteam == 0 else hteam)
                    want = req_bytes(x, 0.5, z, facing, level, team)
                    if spawns[0][1] != want:
                        problems.append(f"request {spawns[0][1].hex()} != {want.hex()}")
                    if spawns[0][2] != 8:
                        problems.append(f"unit_spawn_from_request entered with rsp % 16 = {spawns[0][2]}")
                    if log.index(spawns[0]) > log.index(posts[0]):
                        problems.append("the spawn ran after post_hit_effects")
                    if rig.hp_of(200) != 1:
                        problems.append(f"the new unit's HP is {rig.hp_of(200)}, expected 1")
                if vu and bytes(rig.e.read(vu, 0x4800)) != before:
                    problems.append("the victim's unit record was modified")
                if extra:
                    problems += extra(rig, log)
            elif spawns:
                problems.append(f"pinned exe made a spawn call: {spawns}")
        report(name, problems)

    # ---- the main rule and the teams
    case("a player holder defeats an enemy: one request (class 2090, victim's level, cell and facing, team 4), HP 1, before post_hit_effects")
    case("an enemy holder (team 1) defeats a player unit: team 1 zombie", hteam=1, vteam=0)
    case("a holder on team 4 defeats an enemy: team 4", hteam=4, vteam=1)
    case("a holder on team 5 (charmed enemy) defeats a player unit: team 5", hteam=5, vteam=0)
    case("a holder on team 3 does nothing", hteam=3, vteam=1, expect=0)
    case("a holder on team 2 does nothing", hteam=2, vteam=1, expect=0)
    case("an unknown holder team 9 does nothing", hteam=9, vteam=1, expect=0)
    case("victim team 5 (hostile to team 0): raised", hteam=0, vteam=5)
    case("an ally (same team) defeated: nothing", hteam=0, vteam=0, expect=0)
    case("victim on team 4 (same side as team 0): nothing", hteam=0, vteam=4, expect=0)
    case("victim on team 3: nothing (D4 excludes teams 2 and 3)", hteam=0, vteam=3, expect=0)
    case("victim on team 2: nothing", hteam=0, vteam=2, expect=0)
    # ---- credit: what counts as defeated by this action
    case("KO byte clear with HP 0 (already down before): nothing", killed=0, expect=0)
    case("KO byte set but HP above 0: nothing", vhp=5, expect=0)
    case("KO byte clear, HP above 0 (a survivor): nothing", killed=0, vhp=300, expect=0)
    case("an inactive record: nothing", active=0, expect=0)
    case("no unit record: nothing", unit=False, expect=0)
    # ---- who holds the row
    case("no row: nothing, defeat handled as before", holder=(), expect=0)
    case("another second-word row only: nothing", holder=(27836,), expect=0)
    case("an ordinary row only: nothing", holder=(121,), expect=0)
    case("Self-Destruct's row only: nothing", holder=(27802,), expect=0)
    case("the row among other ids: raised", holder=(5, 9, NEC, 40000))
    # ---- exclusions
    for ch in (5000, 5009, 5100, 5199, 5200, 4800, 4899):
        case(f"an object (char {ch}): nothing", vchar=ch, expect=0)
    for ch in (5010, 5099, 5300, 4700, 4900):
        case(f"a non-object (char {ch}): raised", vchar=ch)
    for ch in (2090, 2092, 2095):
        case(f"an Undead victim (char {ch}): no zombie of a zombie", vchar=ch, expect=0)
    case("char 2089 and 2096 are not Undead: raised", vchar=2089)
    case("char 2096: raised", vchar=2096)
    case("a carried victim: nothing", carrier=3, expect=0)
    case("a victim carrying a unit: nothing", carrying=3, expect=0)
    case("a living unit on the victim's cell (an earlier zombie): nothing", living_there=True, expect=0)
    # ---- the 32-unit limit and a failing spawn
    case("31 living units: raised", live=31)
    case("32 living units: nothing", live=32, expect=0)
    case("40 living units: nothing", live=40, expect=0)
    for label, slot in (("-1", -1), ("256", 256), ("0x7FFFFFFF", 0x7FFFFFFF)):
        problems = []
        kit.world()
        kit.ret_slots = [slot]
        kit.put(1, ids=HOLD, hp=800, team=0, char=500, x=6.0, z=6.0)
        kit.put(5, hp=0, team=1)
        ctx = kit.action([(5, 40, 1)])
        ret, log, _ = kit.go(ctx, 1, abi, section)
        if ret != 0x7B7B or [x_[0] for x_ in log].count("post") != 1 or [x_[0] for x_ in log].count("spawn") != 1:
            problems.append(str(log))
        report(f"spawn returns {label}: no write, post_hit_effects still entered once", problems)
    # ---- level, facing and position are copied as they are
    for lv, fc in ((1, 0), (9999, -90), (0, 180), (255, -180), (-5, 45)):
        case(f"level {lv} facing {fc} copied unchanged", level=lv, facing=fc)
    case("another cell (x 66.0, z 102.0)", x=66.0, z=102.0)
    # ---- several victims in one action, a repeated pass
    problems = []
    for rig in (kit,):
        rig.world()
        rig.put(1, ids=HOLD, hp=800, team=0, char=500, x=6.0, z=6.0)
        rig.put(4, hp=0, team=1, x=30.0, z=18.0)
        rig.put(5, hp=0, team=0, x=42.0, z=18.0)             # an ally of the holder
        rig.put(6, hp=0, team=1, x=54.0, z=18.0)
        rig.put(7, hp=0, team=1, x=66.0, z=18.0, char=5000)  # an object
        rig.put(8, hp=0, team=5, x=78.0, z=18.0)
        ctx = rig.action([(4, 40, 1), (5, 40, 1), (6, 40, 1), (7, 40, 1), (8, 40, 1)])
        ret, log, _ = rig.go(ctx, 1, abi, section)
        reqs = [x_[1] for x_ in log if x_[0] == "spawn"]
        want = [req_bytes(30.0, 0.5, 18.0, 90, 33, 4), req_bytes(54.0, 0.5, 18.0, 90, 33, 4), req_bytes(78.0, 0.5, 18.0, 90, 33, 4)]
        if reqs != want:
            problems.append(f"requests {[r.hex()[:40] for r in reqs]}")
        ret2, log2, _ = rig.go(ctx, 1, abi, section)
        if [x_ for x_ in log2 if x_[0] == "spawn"]:
            problems.append("a second pass over the same action raised again")
    report("five targets: the two hostile ones and the team-5 one raised in order, ally and object not; a second pass adds nothing", problems)
    problems = []
    kit.world()
    kit.live_base = 30
    kit.put(1, ids=HOLD, hp=800, team=0, char=500, x=6.0, z=6.0)
    for s_, xx in ((4, 30.0), (5, 42.0), (6, 54.0)):
        kit.put(s_, hp=0, team=1, x=xx, z=18.0)
    ctx = kit.action([(4, 40, 1), (5, 40, 1), (6, 40, 1)])
    ret, log, _ = kit.go(ctx, 1, abi, section)
    if len([x_ for x_ in log if x_[0] == "spawn"]) != 2:
        problems.append(f"{len([x_ for x_ in log if x_[0] == 'spawn'])} spawns at 30 living units, expected 2 (30 and 31 live, then 32)")
    report("the 32 limit applies inside one action: 30 living units and three victims give two zombies", problems)
    # ---- garbage context
    problems = []
    for label, entries, count in (("count 300", [(5, 40, 1)], 300), ("count 0", [(5, 40, 1)], 0), ("slot -1", [(-1, 40, 1)], None),
                                  ("slot 256", [(256, 40, 1)], None), ("slot 0x7FFF", [(0x7FFF, 40, 1)], None)):
        kit.world()
        kit.put(1, ids=HOLD, hp=800, team=0, char=500, x=6.0, z=6.0)
        kit.put(5, hp=0, team=1)
        ctx = kit.action(entries, count=count)
        ret, log, _ = kit.go(ctx, 1, abi, section)
        if [x_ for x_ in log if x_[0] == "spawn"] or ret != 0x7B7B or len([x_ for x_ in log if x_[0] == "post"]) != 1:
            problems.append(f"{label}: {log}")
    report("a garbage target count and out-of-range slots do nothing", problems)
    problems = []
    kit.world()
    ctx = kit.action([(5, 40, 1)])
    ret = kit.start(SITE, dict(rcx=kit.e.alloc(bytes(0x100)), rdx=ctx, r8=0), {}, abi, section, None)
    if ret != 0x7B7B:
        problems.append(hex(ret))
    report("no attacker record: only post_hit_effects (as before)", problems)
    problems = []
    kit.world()
    kit.put(1, ids=HOLD, hp=800, team=0, char=500, x=6.0, z=6.0, unit=False)
    kit.put(5, hp=0, team=1)
    ctx = kit.action([(5, 40, 1)])
    ret, log, _ = kit.go(ctx, 1, abi, section)
    if [x_ for x_ in log if x_[0] == "spawn"] or ret != 0x7B7B:
        problems.append(str(log))
    report("an attacker record without a unit record does nothing", problems)
    # ---- the older passes of the same wrapper are unchanged, and Summon Guardian's code is untouched
    problems = []
    kit.world()
    kit.put(1, ids=(27836, NEC), hp=800, team=0, char=500, x=6.0, z=6.0)
    kit.put(5, hp=0, team=1)
    ctx = kit.action([(5, 40, 1)])
    ret, log, _ = kit.go(ctx, 1, abi, section)
    if [x_[0] for x_ in log if x_[0] in ("spawn", "post")] != ["spawn", "post"]:
        problems.append(str(log))
    report("a face_target_away + Necromancy holder: facing pass, then the spawn, then post_hit_effects", problems)
    problems = []
    kit.world()
    kit.put(1, ids=(27802,), hp=800, team=0, char=500, x=6.0, z=6.0)
    kit.put(5, ids=(27802,), hp=50, team=1)
    ctx = kit.action([(5, 40, 0)])
    ret, log, _ = kit.go(ctx, 1, abi, section)
    if "spawn" in [x_[0] for x_ in log]:
        problems.append("Self-Destruct holder spawned")
    report("a Self-Destruct holder hit to low HP (no Necromancy): no spawn call from the new pass", problems)
    a, ln = GUARDIAN
    k_bytes, c_bytes = bytes(kit.e.read(a, ln)), bytes(control.e.read(a, ln))
    problems = [] if k_bytes == c_bytes else ["sequencer_ctl_s4_update differs between the kit build and the pinned exe"]
    sites = [s_ for t_, tgt, ss in ev.WRAPPERS for s_ in ss if a <= s_ < a + ln]
    if sites:
        problems.append(f"patch sites inside Summon Guardian's function: {sites}")
    report("Summon Guardian's function (sequencer_ctl_s4_update, 3183 bytes) is byte-identical to the pinned exe and holds no patch site", problems)

    print(f"{n - len(fails)}/{n} checks passed (NECRO1 raise_zombie, {'abi' if abi else 'behavior'}; patched exe {sha[:16]}"
          f"{', control ' + args.control if args.control else ''})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
