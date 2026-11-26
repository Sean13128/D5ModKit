"""LONGTAIL3 offline proof: Battle Suit (D4 802 Self-Destruct, row 27802 = kit family self_destruct, percent 10) through the pinned game's
REAL patched site: wrap_face_away at the call of post_hit_effects in exec_ctl_s2_update (0x14053FE71), on the kit build of the exe and, as
control, on the pinned original.  The game's own post_hit_effects and the native explosion FUN_1401A3E80 are stubs that record their
arguments (the explosion stub also does what the real routine ends with: +0x11DC = 1 on the unit object and its HP applied to itself).
The row is read verbatim from d5lib/importers/d4-evility-overlay.json, so proof and pack cannot drift.

<unicorn python> evility/offline_proof_longtail3.py [--abi] [--control NAME]
Controls (a deliberately broken wrapper; the proof must then FAIL): sd-strict, sd-heal, sd-miss, sd-killed, sd-twice, sd-row, sd-id,
sd-align (needs --abi)

NOT covered (live-needed): the blast itself (field_sweep_spawn and the real FUN_1401A3E80 body), the unit's death and its animation, whether
the game's later states accept an explosion started from this pass.
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
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402

SCRATCH = Path("/Volumes/Data/ai-tmp/claude/longtail3")
OVERLAY = KIT / "d5lib/importers/d4-evility-overlay.json"
SD, SD50, SD100 = 27802, 24081, 24082
SITE, GAME_POST, BOOM = 0x14053FE71, 0x140542CB0, 0x1401A3E80
BREC0, BSTRIDE = 0x141BA33B0, 0x1260
POISON = 0x7A7A7A7A7A7A7A7A
EXPLOSIVE = (1236, 2010, 2012, 2014)        # D5's own explosive evilities: Prinny, Explosive Body, Cross Bomber, Focused Bomb


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    a = text.index(".fa_boom:")
    b = text.index(".fa_call:\n    mov rcx, r12", a)
    w = text[a:b]
    out = SCRATCH / f"d5evil-longtail3-{control}.inc.asm"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if control == "sd-align":      # a 0x30 frame: every call in the wrapper is made with rsp 8 off a 16-byte boundary
        a2 = text.index("wrap_face_away:")
        b2 = text.index("// D4SIG7: wrap_atkcount(", a2)
        wf = text[a2:b2].replace("sub rsp, 0x38", "sub rsp, 0x30").replace("add rsp, 0x38", "add rsp, 0x30").replace("[rsp + 0x20]", "[rsp + 0x18]")
        out.write_text(text[:a2] + wf + text[b2:])
        return out
    edits = {
        "sd-strict": ("    cmp qword ptr [rsi + 0x2cc8], rax\n    jg .sd_next", "    cmp qword ptr [rsi + 0x2cc8], rax\n    jge .sd_next"),
        "sd-heal": ("    cmp byte ptr [r8 + 0x3f6], 4\n    je .sd_next", ""),
        "sd-miss": ("    cmp qword ptr [r13 + rbp + 0x1328], 0\n    jle .sd_next", "    cmp qword ptr [r13 + rbp + 0x1328], 0\n    jl .sd_next"),
        "sd-killed": ("    cmp byte ptr [r13 + rbp + 0x152e], 0\n    jne .sd_next", ""),
        "sd-twice": ("    cmp dword ptr [rsi + 0x11dc], 0\n    jne .sd_next", ""),
        "sd-row": ("    call evil_dmg_sum                   // eax = P percent, 0 for a unit without the row\n    test eax, eax\n    jle .sd_next",
                   "    call evil_dmg_sum\n    mov eax, 10"),
        "sd-id": ("    mov rdi, 0x80000000000 ", "    mov rdi, 0x40000000000 "),
    }
    old, new = edits[control]
    assert w.count(old) == 1, (control, w.count(old))
    out.write_text(text[:a] + w.replace(old, new) + text[b:])
    return out


def overlay_row():
    mods = json.loads(OVERLAY.read_text())["mods"]
    return mods["D4_Class_1190"]["behaviors"]["evilities"][str(SD)]


class Rig(d4.DragonRig):
    """DragonRig plus a stub for the native explosion; battle records live where the game keeps them (0x141BA33B0 + slot * 0x1260)"""

    def __init__(self, exe):
        super().__init__(exe)
        from unicorn import UC_HOOK_CODE
        e, X = self.e, self.e.X

        def boom():
            mu = e.mu
            rcx, rdx = mu.reg_read(X.UC_X86_REG_RCX), mu.reg_read(X.UC_X86_REG_RDX)
            rsp = mu.reg_read(X.UC_X86_REG_RSP)
            self.log.append(("boom", rcx, rdx, rsp % 16))
            unit = struct.unpack("<Q", e.read(rcx + 0x240, 8))[0]
            mu.mem_write(rcx + 0x11DC, struct.pack("<I", 1))                 # what the real routine does before it kills the unit
            mu.mem_write(unit + 0x2CC8, struct.pack("<q", 0))
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                mu.reg_write(r, POISON)
            return 0x4B4B
        e.stubs[BOOM] = boom
        e.mu.hook_add(UC_HOOK_CODE, e._stub, begin=BOOM, end=BOOM)

    def target(self, slot, ids, hp, max_hp, *, active=1, exploding=0, unit=True):
        """a battle record in the game's table; returns (brec va, unit va)"""
        e = self.e
        b = bytearray(BSTRIDE)
        u = e.alloc(d4.dunit(ids, 0x28A))
        e.mu.mem_write(u + 0x2CC8, struct.pack("<qq", hp, 0))
        e.mu.mem_write(u + 0x2CD8, struct.pack("<q", max_hp))
        struct.pack_into("<Q", b, 0x240, u if unit else 0)
        b[0x2E8] = active
        struct.pack_into("<I", b, 0x11DC, exploding)
        va = BREC0 + slot * BSTRIDE
        e.mu.mem_write(va, bytes(b))
        return va, u

    def action(self, entries, category=None, count=None):
        """entries = [(slot, result, killed)]; category = the action's skill row category byte (None = a normal attack)"""
        ctx = bytearray(0x27700)
        struct.pack_into("<h", ctx, 0x27318, len(entries) if count is None else count)
        for j, (slot, result, killed) in enumerate(entries):
            struct.pack_into("<h", ctx, j * 0x260 + 0x1318, slot)
            struct.pack_into("<q", ctx, j * 0x260 + 0x1328, result)
            ctx[j * 0x260 + 0x152E] = killed
        if category is not None:
            row = self.e.alloc(bytes(0x3F6) + bytes([category]) + bytes(9))
            struct.pack_into("<Q", ctx, 0x27678, row)
        return self.e.alloc(bytes(ctx))

    def run_site(self, ctx, abi, section, attacker_ids=()):
        self.log.clear()
        att = self.e.alloc(self._brec(self.e.alloc(d4.dunit(attacker_ids, 3))))
        ctl = self.e.alloc(bytes(0x100))
        ret = self.start(SITE, dict(rcx=ctl, rdx=ctx, r8=att), {}, abi, section, None)
        return ret, self.log[:], (ctl, ctx, att)


_K = {}


def kits():
    if "kit" not in _K:
        rows = {SD: overlay_row(), SD50: {"family": "self_destruct", "effects": [{"value": 50}]},
                SD100: {"family": "self_destruct", "effects": [{"value": 100}]},
                27836: {"family": "face_target_away"}, 121: {"family": "regen", "effects": [{"value": 1, "stat": "hp"}]}}
        assert rows[SD] == {"family": "self_destruct", "effects": [{"value": 10}]}, rows[SD]
        patched = ev.build_patch(ORIGINAL.read_bytes(), rows)
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="lt3-", dir=SCRATCH))
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

    HOLD, NONE = (SD,), ()

    def case(name, ids, hp, max_hp, result=100, killed=0, category=None, active=1, exploding=0, expect=1):
        """one target in slot 5; expect = number of explosions (1 = of that unit)"""
        problems = []
        for rig, is_kit in ((kit, True), (control, False)):
            va, _ = rig.target(5, ids, hp, max_hp, active=active, exploding=exploding)
            ctx = rig.action([(5, result, killed)], category)
            ret, log, (ctl, c, att) = rig.run_site(ctx, abi and is_kit, section)
            booms = [x for x in log if x[0] == "boom"]
            posts = [x for x in log if x[0] == "post"]
            who = "kit" if is_kit else "pinned"
            if ret != 0x7B7B or posts != [("post", (ctl, c, att))]:
                problems.append(f"{who}: post_hit_effects not entered once with the site arguments / result not returned: {log} {ret:#x}")
            if is_kit:
                if len(booms) != expect or (expect and (booms[0][1], booms[0][2]) != (va, 1)):
                    problems.append(f"explosions {booms}, expected {expect} of unit {va:#x} with flag 1")
                if booms and booms[0][3] != 8:
                    problems.append(f"the native routine was entered with rsp % 16 = {booms[0][3]} (a normal call entry has 8)")
                if expect and booms and posts and log.index(booms[0]) > log.index(posts[0]):
                    problems.append("the explosion ran after post_hit_effects")
            elif booms:
                problems.append(f"pinned exe made an explosion call: {booms}")
        report(name, problems)

    # ---- the threshold (percent 10, max HP 1000 -> trunc 100): D4's test is HP <= trunc(max x percent / 100)
    case("a holder left at 99 of 1000 HP by a real hit explodes (once, flag 1, before post_hit_effects)", HOLD, 99, 1000)
    case("exactly at the threshold (100 of 1000) explodes: D4 FUN_14010DE70 passes when HP <= threshold", HOLD, 100, 1000)
    case("one above (101 of 1000) does not", HOLD, 101, 1000, expect=0)
    case("full HP does not", HOLD, 1000, 1000, expect=0)
    case("1 HP of 1000 explodes", HOLD, 1, 1000)
    case("max HP 9 (threshold trunc(0.9) = 0): 1 HP does not (D4's integer division)", HOLD, 1, 9, expect=0)
    case("max HP 19 (threshold 1): 1 HP explodes", HOLD, 1, 19)
    case("max HP 10 (threshold 1): 2 HP does not", HOLD, 2, 10, expect=0)
    case("max HP 1000000: 100000 HP explodes", HOLD, 100000, 1000000)
    case("max HP 1000000: 100001 HP does not", HOLD, 100001, 1000000, expect=0)
    # ---- what kind of result
    case("a killing hit does not (KO byte set, HP 0)", HOLD, 0, 1000, killed=1, expect=0)
    case("HP 0 without the KO byte does not", HOLD, 0, 1000, expect=0)
    case("KO byte set although HP shows alive: not processed", HOLD, 50, 1000, killed=1, expect=0)
    case("a miss (result 0) does not, even for a unit already below the threshold", HOLD, 50, 1000, result=0, expect=0)
    case("no result for the target (-1) does not", HOLD, 50, 1000, result=-1, expect=0)
    case("a buff (result 0, category 5) does not", HOLD, 50, 1000, result=0, category=5, expect=0)
    case("a heal (category 4, a positive amount) does not", HOLD, 50, 1000, result=300, category=4, expect=0)
    case("a damaging skill (category 1) counts", HOLD, 50, 1000, result=300, category=1)
    case("a magic skill (category 2) counts", HOLD, 50, 1000, result=300, category=2)
    case("result 1 (the smallest real hit) counts", HOLD, 50, 1000, result=1)
    # ---- who
    case("no row: nothing", NONE, 50, 1000, expect=0)
    case("another second-word row only (face_target_away): nothing", (27836,), 50, 1000, expect=0)
    case("an ordinary row only: nothing", (121,), 50, 1000, expect=0)
    case("D5's own explosive evilities (1236, 2010, 2012, 2014) without the row: nothing, as before", EXPLOSIVE, 50, 1000, expect=0)
    case("the row among other ids and D5's explosive ones: explodes", (5, 9, SD, 2010, 40000), 50, 1000)
    case("an inactive record does not", HOLD, 50, 1000, active=0, expect=0)
    case("a unit already exploding (+0x11DC = 1) is not processed again", HOLD, 50, 1000, exploding=1, expect=0)
    # ---- the percent comes from the row
    case("a 50 percent row: 500 of 1001 explodes (trunc 500.5)", (SD50,), 500, 1001)
    case("a 50 percent row: 501 of 1001 does not", (SD50,), 501, 1001, expect=0)
    case("a 100 percent row: a living unit explodes", (SD100,), 1000, 1000)
    # ---- several targets, a repeated pass, malformed context
    problems = []
    va = {}
    for slot, ids, hp in ((4, HOLD, 50), (5, HOLD, 900), (6, NONE, 10), (7, HOLD, 70), (8, EXPLOSIVE, 5)):
        va[slot], _ = kit.target(slot, ids, hp, 1000)
    ctx = kit.action([(4, 40, 0), (5, 40, 0), (6, 40, 0), (7, 40, 0), (8, 40, 0)])
    ret, log, _ = kit.run_site(ctx, abi, section)
    booms = [x[1] for x in log if x[0] == "boom"]
    if booms != [va[4], va[7]]:
        problems.append(f"explosions {[hex(b) for b in booms]}, expected slots 4 then 7 only")
    ret2, log2, _ = kit.run_site(ctx, abi, section)
    if [x for x in log2 if x[0] == "boom"]:
        problems.append("a second pass over the same action exploded a unit that is already exploding")
    report("five targets: only the two low holders explode, in order, and a second pass adds nothing", problems)
    problems = []
    for label, entries, count in (("count 300 (garbage)", [(5, 40, 0)], 300), ("count 0", [(5, 40, 0)], 0),
                                  ("slot -1", [(-1, 40, 0)], None), ("slot 256", [(256, 40, 0)], None),
                                  ("slot 0x7FFF", [(0x7FFF, 40, 0)], None)):
        kit.target(5, HOLD, 50, 1000)
        ctx = kit.action(entries, count=count)
        ret, log, _ = kit.run_site(ctx, abi, section)
        if [x for x in log if x[0] == "boom"] or ret != 0x7B7B or len(log) != 1:
            problems.append(f"{label}: {log}")
    report("a garbage target count and out-of-range slots do nothing", problems)
    problems = []
    kit.target(5, HOLD, 50, 1000, unit=False)
    ctx = kit.action([(5, 40, 0)])
    ret, log, _ = kit.run_site(ctx, abi, section)
    if [x for x in log if x[0] == "boom"] or ret != 0x7B7B:
        problems.append(str(log))
    report("a target record without a unit record does nothing", problems)
    # ---- the attacker side is unchanged
    problems = []
    kit.log.clear()
    ctx = kit.action([(5, 40, 0)])
    ret = kit.start(SITE, dict(rcx=kit.e.alloc(bytes(0x100)), rdx=ctx, r8=0), {}, abi, section, None)
    if ret != 0x7B7B or len(kit.log) != 1:
        problems.append(str(kit.log))
    report("no attacker record: only post_hit_effects (as before)", problems)
    problems = []
    kit.target(5, HOLD, 50, 1000)
    ctx = kit.action([(5, 40, 0)])
    ret, log, _ = kit.run_site(ctx, abi, section, attacker_ids=(27836,))
    if [x[0] for x in log] != ["boom", "post"]:
        problems.append(f"a face_target_away attacker: {log}")
    report("a face_target_away attacker hitting a low holder: facing pass, explosion, then post_hit_effects", problems)

    print(f"{n - len(fails)}/{n} checks passed (LONGTAIL3 self_destruct, {'abi' if abi else 'behavior'}; patched exe {sha[:16]}"
          f"{', control ' + args.control if args.control else ''})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
