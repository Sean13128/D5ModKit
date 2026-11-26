"""NECRO2 offline proof: why Necromancy (row 27868, kit family raise_zombie) made no zombie live, and the fix, through the pinned game's REAL patched sites:
wrap_atkcount at the call of damage_apply_damage in FUN_1401B1BA0 (0x1401B1BE0) -> evil_necro_note, then wrap_face_away at the call of post_hit_effects in
exec_ctl_s2_update (0x14053FE71) -> evil_necro, on the kit build of the exe and, as control, on the pinned original.

What NECRO1's proof hid: it built the victim as an ACTIVE record with HP 0 at the end-of-action pass.  Read from the decomp, the game retires a defeated unit
(+0x2E8 = 0, record released) about 20 ticks after the defeat, long before the action's script ends and exec_ctl_s2_update's end pass runs.  This proof
models that: the apply stub defeats the target (HP 0, the context's KO byte set, as damage_apply_damage does), `retire` clears the battle record's active
byte and zeroes the unit record (battle_unit_reset + the enemy-pool memset), and only then the end pass runs.  The first block runs NECRO1's own design (the
code of commit 187b529) in that state: no zombie (the live failure), and with the victim still active: a zombie (what NECRO1's proof showed).

Real game code runs for events_env_team_of, model_team_is_hostile and events_env_is_object_rec; stubs: the game's damage_apply_damage, post_hit_effects,
unit_spawn_from_request (records the 0x40-byte request) and FUN_1401C3A00 (the living-unit count: base + zombies made so far).

<unicorn python> evility/offline_proof_necro2.py [--abi] [--control NAME]
Controls (a deliberately broken wrapper; the proof must then FAIL): nc2-ko, nc2-hp, nc2-hostile, nc2-cap, nc2-cell, nc2-hp1, nc2-team, nc2-row, nc2-undead,
nc2-object, nc2-carry, nc2-header, nc2-consume, nc2-align (needs --abi)

NOT covered (live-needed): the real unit_spawn_from_request body, the real timing of the retirement against the end pass, the unit's AI and behaviour.
"""
import argparse
import hashlib
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(KIT), str(KIT / "evility"), str(KIT / "tools")]
from d5lib import evility as ev                                                  # noqa: E402
import offline_proof_d4sig7 as d4                                                # noqa: E402
import offline_proof_necro1 as nc                                                # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402

SCRATCH = Path("/Volumes/Data/ai-tmp/claude/necro2")
NEC = nc.NEC
SITE_APPLY, SITE_END, GAME_APPLY = 0x1401B1BE0, 0x14053FE71, 0x1401B1FD0
BREC0, BSTRIDE = nc.BREC0, nc.BSTRIDE
POISON = nc.POISON
NECRO1_COMMIT = "187b529"


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    a = text.index("evil_necro_note:")
    b = text.index("// NEMO1: evil_nemo(", a)
    w = text[a:b]
    out = SCRATCH / f"d5evil-necro2-{control}.inc.asm"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    edits = {
        "nc2-ko": ("    cmp byte ptr [rbx + rbp + 0x152e], 0\n    je .nn_ret", ""),
        "nc2-hp": ("    cmp qword ptr [rdi + 0x2cc8], 0\n    jg .nn_ret                          // still standing", ""),
        "nc2-hostile": ("    test al, al\n    jz .nn_ret\n    lea rsi, [rip + evil_zq]", "    lea rsi, [rip + evil_zq]"),
        "nc2-cap": ("    cmp eax, 0x20\n    jl .nc_room", "    cmp eax, 0x20\n    jmp .nc_room"),
        "nc2-cell": ("    cmp edx, dword ptr [r14 + 8]\n    jne .nc_cell_next", "    cmp edx, dword ptr [r14 + 8]\n    jmp .nc_cell_next"),
        "nc2-hp1": ("    mov qword ptr [rax + 0x2cc8], 1     // HP 1", "    nop"),
        "nc2-team": ("    mov eax, 4                          // a player-side holder", "    mov eax, 0                          // a player-side holder"),
        "nc2-row": ("    test eax, eax\n    jz .nn_ret                          // not a holder", "    nop"),
        "nc2-undead": ("    cmp eax, 5\n    jbe .nn_ret                         // already an Undead: no zombie of a zombie", "    cmp eax, 5\n    nop"),
        "nc2-object": ("    test al, al\n    jnz .nn_ret\n    mov eax, dword ptr [rdi + 0x2e04]", "    mov eax, dword ptr [rdi + 0x2e04]"),
        "nc2-carry": ("    cmp word ptr [r14 + 0x2ee], 0\n    jge .nn_ret                         // carried", ""),
        "nc2-header": ("    cmp qword ptr [rbx], r12\n    jne .nc_ret                         // no notes of this action", ""),
        "nc2-consume": ("    mov qword ptr [rbx], 0              // consumed whatever follows\n    mov dword ptr [rbx + 8], 0", ""),
        "nc2-align": ("sub rsp, 0x78\n    mov rbx, r8                         // action context", "sub rsp, 0x70\n    mov rbx, r8                         // action context"),
    }
    old, new = edits[control]
    assert w.count(old) == 1, (control, w.count(old))
    w = w.replace(old, new)
    if control == "nc2-align":
        i = w.index(".nn_ret:")
        w = w[:i] + w[i:].replace("add rsp, 0x78", "add rsp, 0x70", 1)
    out.write_text(text[:a] + w + text[b:])
    return out


def req_bytes(*a, **k):
    return nc.req_bytes(*a, **k)


class Rig(nc.Rig):
    def __init__(self, exe, zq=None):
        super().__init__(exe)
        from unicorn import UC_HOOK_CODE
        e, X = self.e, self.e.X
        self.zq = zq
        self.plan = {}

        def game_apply():
            mu = e.mu
            rsp = mu.reg_read(X.UC_X86_REG_RSP)
            att, tgt, ctx, idx = (mu.reg_read(r) for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9))
            self.log.append(("apply", (att, tgt, ctx, idx & 0xFFFFFFFF), struct.unpack("<Q", e.read(rsp + 0x28, 8))[0]))
            plan = self.plan.get(idx & 0xFFFFFFFF)
            unit = struct.unpack("<Q", e.read(tgt + 0x240, 8))[0]
            if plan and unit:
                hp_after, ko = plan                  # what damage_apply_damage ends with for a defeat: HP 0 (damage_after_hit_evaluate), the KO byte
                mu.mem_write(unit + 0x2CC8, struct.pack("<q", hp_after))
                mu.mem_write(ctx + (idx & 0xFFFFFFFF) * 0x260 + 0x152E, bytes([ko]))
            for r in (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9, X.UC_X86_REG_R10, X.UC_X86_REG_R11):
                mu.reg_write(r, POISON)
            return 0x5A5A
        e.stubs[GAME_APPLY] = game_apply

    def world(self):
        super().world()
        self.plan = {}
        if self.zq:
            self.e.mu.mem_write(self.zq, bytes(528 + 64))

    def counters(self):
        return list(struct.unpack("<16I", self.e.read(self.zq + 528, 64))) if self.zq else []

    def queue(self):
        hdr, cnt = struct.unpack("<QI", self.e.read(self.zq, 12))
        return hdr, cnt

    def retire(self, slot):
        """the game's retirement of a defeated enemy-pool unit: battle_unit_reset clears +0x2E8, the record is zeroed (memset(r, 0, 0x4348))"""
        u = self.unit_of(slot)
        self.e.mu.mem_write(u, bytes(0x4348))
        self.e.mu.mem_write(BREC0 + slot * BSTRIDE + 0x2E8, b"\0")

    def apply(self, ctx, att_slot, idx, victim_slot, abi, section):
        att = BREC0 + att_slot * BSTRIDE
        return self.start(SITE_APPLY, dict(rcx=att, rdx=BREC0 + victim_slot * BSTRIDE, r8=ctx, r9=idx), {0x20: 0xABCD0001}, abi, section, None)


_K = {}


def build(asm_file, tag):
    ev.ASM_FILE = str(asm_file)
    rows = {NEC: nc.overlay_row(), 27836: {"family": "face_target_away"}, 121: {"family": "regen", "effects": [{"value": 1, "stat": "hp"}]},
            27802: {"family": "self_destruct", "effects": [{"value": 10}]}, 27808: {"family": "kill_counter"}}
    patched = ev.build_patch(ORIGINAL.read_bytes(), rows)
    info = ev.section_info(patched)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=tag, dir=SCRATCH))
    (tmp / "kit.exe").write_bytes(patched)
    return Rig(tmp / "kit.exe", ev.SECTION_SYMBOLS.get("evil_zq")), (info["code"], info["base"] + len(info["data"])), hashlib.sha256(patched).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--control")
    args = ap.parse_args()
    assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == ORIGINAL_SHA
    SCRATCH.mkdir(parents=True, exist_ok=True)
    cur_asm = ev.ASM_FILE
    old_asm = SCRATCH / "d5evil-necro1-design.inc.asm"
    old_asm.write_text(subprocess.run(["git", "-C", str(KIT), "show", f"{NECRO1_COMMIT}:d5lib/native/d5evil.inc.asm"], capture_output=True, text=True,
                                      check=True).stdout)
    old, old_section, _ = build(old_asm, "old-")
    ev.ASM_FILE = cur_asm
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    kit, section, sha = build(ev.ASM_FILE, "nc2-")
    control = Rig(ORIGINAL)
    abi = args.abi
    fails, n = [], 0

    def report(name, problems):
        nonlocal n
        n += 1
        if problems:
            fails.append(name)
        print(("ok   " if not problems else "FAIL ") + name + ("" if not problems else ": " + "; ".join(problems)))

    HOLD = (NEC,)

    def run(rig, sec, *, victims, holder=HOLD, hteam=0, live=0, ret_slots=None, retire=True, apply_abi=None, end=True, att_slot=1, count=None):
        """victims: list of dicts (slot, team, char, hp_before, hp_after, ko, ...) -> (log, ctx pieces).  The holder is in slot 1 (or att_slot)."""
        rig.world()
        rig.live_base = live
        if ret_slots is not None:
            rig.ret_slots = list(ret_slots)
        rig.put(att_slot, ids=holder, hp=800, team=hteam, char=500, x=6.0, z=6.0)
        for v in victims:
            rig.put(v["slot"], hp=v.get("hp_before", 1), team=v.get("team", 1), char=v.get("char", 100), level=v.get("level", 33), x=v.get("x", 30.0),
                    z=v.get("z", 18.0), facing=v.get("facing", 90), carrier=v.get("carrier", -1), carrying=v.get("carrying", -1))
            if v.get("living_there"):
                rig.put(v["slot"] + 20, hp=500, team=v.get("team", 1), char=300, x=v.get("x", 30.0), z=v.get("z", 18.0))
        ctx = rig.action([(v["slot"], 40, 0) for v in victims], count=count)
        rig.log.clear()
        for j, v in enumerate(victims):
            rig.plan[j] = (v.get("hp_after", 0), v.get("ko", 1))
            rig.apply(ctx, att_slot, j, v["slot"], (abi if apply_abi is None else apply_abi) and rig is not control, section_of[id(rig)])
        if retire:
            for v in victims:
                if not v.get("keep"):
                    rig.retire(v["slot"])
        applies = [x_ for x_ in rig.log if x_[0] == "apply"]
        ret = None
        if end:
            ret, log, pieces = rig.go(ctx, att_slot, abi and rig is not control, section_of[id(rig)])
            rig.log[:0] = [x_ for x_ in applies if x_ not in rig.log]
            return applies, rig.log[:], ctx, pieces, ret
        return applies, rig.log[:], ctx, None, ret

    section_of = {id(kit): section, id(old): old_section, id(control): None}
    V = dict(slot=5)

    # ---- the live failure, reproduced offline with NECRO1's own design (commit 187b529) in the state the decomp describes
    for label, retire, want in (("the victim retired before the end pass (the state read from the decomp)", True, 0),
                                ("the victim still active with HP 0 at the end pass (the state NECRO1's proof built)", False, 1)):
        problems = []
        # the old design has no note step; its apply wrapper is the unchanged wrap_atkcount
        applies, log, ctx, (ctl, c, att), ret = run(old, old_section, victims=[dict(V)], retire=retire, apply_abi=False)
        spawns = [x_ for x_ in log if x_[0] == "spawn"]
        if len(spawns) != want:
            problems.append(f"NECRO1 design: {len(spawns)} spawns, expected {want}")
        report(f"NECRO1's design (187b529), {label}: {want} zombie(s)", problems)

    # ---- the fix, in the real state
    def case(name, *, expect=1, holder=HOLD, hteam=0, victims=None, expect_team=None, live=0, retire=True, extra=None, ret_slots=None, count=None, att_slot=1):
        problems = []
        vs = victims if victims is not None else [dict(V)]
        for rig, is_kit in ((kit, True), (control, False)):
            applies, log, ctx, pieces, ret = run(rig, section_of[id(rig)], victims=vs, holder=holder, hteam=hteam, live=live, retire=retire,
                                                 ret_slots=ret_slots, count=count, att_slot=att_slot)
            ctl, c, att = pieces
            who = "kit" if is_kit else "pinned"
            posts = [x_ for x_ in log if x_[0] == "post"]
            spawns = [x_ for x_ in log if x_[0] == "spawn"]
            if ret != 0x7B7B or posts != [("post", (ctl, c, att))]:
                problems.append(f"{who}: post_hit_effects not entered once with the site arguments / result not returned: {ret:#x}")
            if len(applies) != len(vs) or any(a[1][:3] != (att, BREC0 + v["slot"] * BSTRIDE, c) or a[2] != 0xABCD0001 for a, v in zip(applies, vs)):
                problems.append(f"{who}: damage_apply_damage arguments changed: {applies}")
            if is_kit:
                if len(spawns) != expect:
                    problems.append(f"spawns {len(spawns)}, expected {expect}")
                if expect and spawns:
                    v = vs[0]
                    team = expect_team if expect_team is not None else (4 if hteam == 0 else hteam)
                    want = req_bytes(v.get("x", 30.0), 0.5, v.get("z", 18.0), v.get("facing", 90), v.get("level", 33), team)
                    if spawns[0][1] != want:
                        problems.append(f"request {spawns[0][1].hex()} != {want.hex()}")
                    if spawns[0][2] != 8:
                        problems.append(f"unit_spawn_from_request entered with rsp % 16 = {spawns[0][2]}")
                    if log.index(spawns[0]) > log.index(posts[0]):
                        problems.append("the spawn ran after post_hit_effects")
                    if rig.hp_of(200) != 1:
                        problems.append(f"the new unit's HP is {rig.hp_of(200)}, expected 1")
                if rig.queue() != (0, 0):
                    problems.append(f"the queue was not emptied: {rig.queue()}")
                if extra:
                    problems += extra(rig, log)
            else:
                if spawns:
                    problems.append(f"pinned exe made a spawn call: {spawns}")
        report(name, problems)

    case("a player holder defeats an enemy that is retired before the end pass: one request (2090, the victim's level, cell, facing, team 4), HP 1, "
         "before post_hit_effects")
    case("the same with the victim still active at the end pass", retire=False)
    case("an enemy holder (team 1) defeats a player unit: team 1 zombie", hteam=1, victims=[dict(V, team=0)])
    case("a holder on team 4 defeats an enemy: team 4", hteam=4)
    case("a holder on team 5 defeats a player unit: team 5", hteam=5, victims=[dict(V, team=0)])
    for ht in (2, 3, 9):
        case(f"a holder on team {ht} does nothing", hteam=ht, expect=0)
    case("victim team 5: raised", victims=[dict(V, team=5)])
    case("an ally (same team): nothing", victims=[dict(V, team=0)], expect=0)
    case("victim on team 4: nothing", victims=[dict(V, team=4)], expect=0)
    case("victim on team 3: nothing", victims=[dict(V, team=3)], expect=0)
    case("victim on team 2: nothing", victims=[dict(V, team=2)], expect=0)
    case("KO byte never set although HP reaches 0 (a forecast-like pass): nothing", victims=[dict(V, ko=0)], expect=0)
    case("the target survives the hit (HP 300 left, KO byte 0): nothing", victims=[dict(V, hp_after=300, ko=0)], expect=0)
    case("KO byte set but HP above 0: nothing", victims=[dict(V, hp_after=5, ko=1)], expect=0)
    case("a target already down before the hit (HP 0 before): nothing", victims=[dict(V, hp_before=0)], expect=0)
    case("no row: nothing, defeat handled as before", holder=(), expect=0)
    case("another second-word row only: nothing", holder=(27836,), expect=0)
    case("an ordinary row only: nothing", holder=(121,), expect=0)
    case("Self-Destruct's row only: nothing", holder=(27802,), expect=0)
    case("kill_counter's row only: nothing", holder=(27808,), expect=0)
    case("the row among other ids: raised", holder=(5, 9, NEC, 40000))
    for ch in (5000, 5009, 5100, 5199, 5200, 4800, 4899):
        case(f"an object (char {ch}): nothing", victims=[dict(V, char=ch)], expect=0)
    for ch in (5010, 5099, 5300, 4700, 4900):
        case(f"a non-object (char {ch}): raised", victims=[dict(V, char=ch)])
    for ch in (2090, 2092, 2095):
        case(f"an Undead victim (char {ch}): no zombie of a zombie", victims=[dict(V, char=ch)], expect=0)
    case("char 2089: raised", victims=[dict(V, char=2089)])
    case("char 2096: raised", victims=[dict(V, char=2096)])
    case("a carried victim: nothing", victims=[dict(V, carrier=3)], expect=0)
    case("a victim carrying a unit: nothing", victims=[dict(V, carrying=3)], expect=0)
    case("a living unit on the victim's cell at the end pass (something moved in): nothing", victims=[dict(V, living_there=True)], expect=0)
    case("31 living units: raised", live=31)
    case("32 living units: nothing", live=32, expect=0)
    case("40 living units: nothing", live=40, expect=0)
    for lv, fc in ((1, 0), (9999, -90), (0, 180), (255, -180), (-5, 45)):
        case(f"level {lv} facing {fc} copied unchanged", victims=[dict(V, level=lv, facing=fc)])
    case("another cell (x 66.0, z 102.0)", victims=[dict(V, x=66.0, z=102.0)])
    case("the attacker is in another slot (7)", att_slot=7)

    for label, slot in (("-1", -1), ("256", 256), ("0x7FFFFFFF", 0x7FFFFFFF)):
        problems = []
        applies, log, ctx, pieces, ret = run(kit, section, victims=[dict(V)], ret_slots=[slot])
        names = [x_[0] for x_ in log]
        if ret != 0x7B7B or names.count("post") != 1 or names.count("spawn") != 1 or kit.queue() != (0, 0):
            problems.append(str(log))
        report(f"spawn returns {label}: no write, post_hit_effects still entered once, queue emptied", problems)

    # ---- several victims
    problems = []
    vs = [dict(slot=4, x=30.0, z=18.0), dict(slot=5, team=0, x=42.0, z=18.0), dict(slot=6, x=54.0, z=18.0), dict(slot=7, char=5000, x=66.0, z=18.0),
          dict(slot=8, team=5, x=78.0, z=18.0)]
    applies, log, ctx, pieces, ret = run(kit, section, victims=vs)
    reqs = [x_[1] for x_ in log if x_[0] == "spawn"]
    want = [req_bytes(30.0, 0.5, 18.0, 90, 33, 4), req_bytes(54.0, 0.5, 18.0, 90, 33, 4), req_bytes(78.0, 0.5, 18.0, 90, 33, 4)]
    if reqs != want:
        problems.append(f"requests {[r.hex()[:40] for r in reqs]}")
    ret2, log2, _ = kit.go(ctx, 1, abi, section)
    if [x_ for x_ in log2 if x_[0] == "spawn"]:
        problems.append("a second end pass over the same action raised again")
    report("five targets, all retired: the two hostile ones and the team-5 one raised in order, ally and object not; a second end pass adds nothing", problems)
    problems = []
    vs = [dict(slot=4 + j, x=30.0 + 12 * j, z=18.0) for j in range(3)]
    applies, log, ctx, pieces, ret = run(kit, section, victims=vs, live=30)
    if len([x_ for x_ in log if x_[0] == "spawn"]) != 2:
        problems.append(f"{len([x_ for x_ in log if x_[0] == 'spawn'])} spawns at 30 living units, expected 2")
    report("the 32 limit applies inside one action: 30 living units and three victims give two zombies", problems)
    problems = []
    vs = [dict(slot=30 + j, x=12.0 * j + 30.0, z=18.0) for j in range(20)]
    applies, log, ctx, pieces, ret = run(kit, section, victims=vs, ret_slots=list(range(100, 140)))
    if len([x_ for x_ in log if x_[0] == "spawn"]) != 16 or kit.counters()[7] != 4:
        problems.append(f"{len([x_ for x_ in log if x_[0] == 'spawn'])} spawns, drop counter {kit.counters()[7]}: expected 16 and 4")
    report("twenty victims in one action: the queue holds 16 (the rest are counted as dropped)", problems)

    # ---- stale notes, garbage and the attacker
    problems = []
    run(kit, section, victims=[dict(V)], end=False)                          # a note whose end pass never came
    hdr, cnt = kit.queue()
    if cnt != 1:
        problems.append(f"no note queued: {kit.queue()}")
    # a second holder (slot 2) acts next and defeats nobody: the old note must not be spawned by its end pass
    kit.put(2, ids=HOLD, hp=800, team=0, char=500, x=9.0, z=9.0)
    ctx2 = kit.action([(9, 40, 0)])
    kit.put(9, hp=500, team=1, x=90.0, z=90.0)
    kit.log.clear()
    kit.plan[0] = (400, 0)
    kit.apply(ctx2, 2, 0, 9, abi, section)
    ret, log, _ = kit.go(ctx2, 2, abi, section)
    if [x_ for x_ in log if x_[0] == "spawn"] or kit.queue() != (0, 0):
        problems.append(f"a stale note was spawned or kept: {log} {kit.queue()}")
    report("a note whose end pass never came is not spawned by another attacker's action", problems)
    problems = []
    run(kit, section, victims=[dict(V)], end=False)
    ctx2 = kit.action([(9, 40, 0)])
    kit.put(9, hp=500, team=1, x=90.0, z=90.0)
    kit.log.clear()
    kit.plan[0] = (400, 0)
    kit.apply(ctx2, 1, 0, 9, abi, section)                                   # the same holder, a new action: target 0 starts a fresh list
    ret, log, _ = kit.go(ctx2, 1, abi, section)
    if [x_ for x_ in log if x_[0] == "spawn"]:
        problems.append("the same holder's next action spawned the stale note")
    report("the same holder's next action (target 0) drops a stale note", problems)
    problems = []
    for label, idx in (("index 300", 300), ("index -1", 0xFFFFFFFF), ("index 256", 256)):
        kit.world()
        kit.put(1, ids=HOLD, hp=800, team=0, char=500, x=6.0, z=6.0)
        kit.put(5, hp=1, team=1)
        ctx = kit.action([(5, 40, 1)])
        kit.log.clear()
        kit.start(SITE_APPLY, dict(rcx=BREC0 + BSTRIDE, rdx=BREC0 + 5 * BSTRIDE, r8=ctx, r9=idx), {0x20: 1}, abi, section, None)
        if kit.queue()[1] != 0:
            problems.append(f"{label}: a note was queued")
    report("a garbage target index queues nothing", problems)
    problems = []
    kit.world()
    ctx = kit.action([(5, 40, 1)])
    ret = kit.start(SITE_END, dict(rcx=kit.e.alloc(bytes(0x100)), rdx=ctx, r8=0), {}, abi, section, None)
    if ret != 0x7B7B:
        problems.append(hex(ret))
    report("no attacker record at the end pass: only post_hit_effects (as before)", problems)
    problems = []
    kit.world()
    kit.put(1, ids=HOLD, hp=800, team=0, char=500, x=6.0, z=6.0, unit=False)
    kit.put(5, hp=1, team=1)
    ctx = kit.action([(5, 40, 0)])
    kit.log.clear()
    kit.plan[0] = (0, 1)
    ret = kit.apply(ctx, 1, 0, 5, abi, section)
    if ret != 0x5A5A or kit.queue()[1] != 0:
        problems.append(f"{ret:#x} {kit.queue()}")
    report("an attacker record without a unit record at the damage apply: result handed back, nothing queued", problems)

    # ---- the older passes of the same wrappers are unchanged
    problems = []
    kit.world()
    kit.put(1, ids=(27836, NEC), hp=800, team=0, char=500, x=6.0, z=6.0)
    kit.put(5, hp=1, team=1)
    ctx = kit.action([(5, 40, 0)])
    kit.plan[0] = (0, 1)
    kit.log.clear()
    kit.apply(ctx, 1, 0, 5, abi, section)
    applied = [x_[0] for x_ in kit.log if x_[0] == "apply"]
    kit.retire(5)
    ret, log, _ = kit.go(ctx, 1, abi, section)
    if applied + [x_[0] for x_ in log if x_[0] in ("spawn", "post")] != ["apply", "spawn", "post"]:
        problems.append(str(log))
    report("a face_target_away + Necromancy holder: apply, then the facing pass, the spawn, post_hit_effects", problems)
    problems = []
    kit.world()
    kit.put(1, ids=(27802,), hp=800, team=0, char=500, x=6.0, z=6.0)
    kit.put(5, ids=(27802,), hp=50, team=1)
    ctx = kit.action([(5, 40, 0)])
    kit.log.clear()
    ret, log, _ = kit.go(ctx, 1, abi, section)
    if "spawn" in [x_[0] for x_ in log]:
        problems.append("Self-Destruct holder spawned")
    report("a Self-Destruct holder hit to low HP (no Necromancy): no spawn", problems)
    a, ln = nc.GUARDIAN
    k_bytes, c_bytes = bytes(kit.e.read(a, ln)), bytes(control.e.read(a, ln))
    problems = [] if k_bytes == c_bytes else ["sequencer_ctl_s4_update differs between the kit build and the pinned exe"]
    sites = [s_ for t_, tgt, ss in ev.WRAPPERS for s_ in ss if a <= s_ < a + ln]
    if sites:
        problems.append(f"patch sites inside Summon Guardian's function: {sites}")
    report("Summon Guardian's function (sequencer_ctl_s4_update, 3183 bytes) is byte-identical to the pinned exe and holds no patch site", problems)
    # ---- the debug counters tell the stages apart
    problems = []
    run(kit, section, victims=[dict(V)])
    c = kit.counters()
    if c[:10] != [1, 1, 1, 0, 1, 1, 0, 0, 1, 0]:
        problems.append(f"counters after one raised victim: {c}")
    run(kit, section, victims=[dict(V, ko=0)])
    c = kit.counters()
    if c[:10] != [1, 0, 1, 0, 0, 0, 0, 0, 1, 0]:
        problems.append(f"counters after a holder's hit that defeated nobody: {c}")
    run(kit, section, victims=[dict(V)], holder=())
    c = kit.counters()
    if c[:10] != [0, 0, 0, 0, 0, 0, 0, 0, 1, 0]:
        problems.append(f"counters with no holder: {c}")
    run(kit, section, victims=[dict(V)], end=False)
    c = kit.counters()
    if c[:10] != [1, 1, 0, 0, 0, 0, 0, 0, 0, 0]:
        problems.append(f"counters when the end pass never runs (note, no pass): {c}")
    report("the debug counters (evil_zdbg) separate: no holder / holder with no kill / noted but the end pass never ran / spawned", problems)

    print(f"{n - len(fails)}/{n} checks passed (NECRO2 raise_zombie, {'abi' if abi else 'behavior'}; patched exe {sha[:16]}"
          f"{', control ' + args.control if args.control else ''})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
