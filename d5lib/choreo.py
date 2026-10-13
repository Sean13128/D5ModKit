"""Skill choreography simulator and editor: what a skill's script events do, frame by frame, without the game.

A skill's choreography is a tree of script.dat events (docs/SKILL_ANIMATIONS.md).  The game runs every event as a
coroutine: `call_event` starts a child and runs it until it waits, `spawn_event` starts one nobody waits for,
`wait N` pauses N frames, `wait_children` until every child has ended (`cmd_6530 actor, N` does not wait: it
jumps the actor's motion to frame N, 0x14016d070).  Simulator does the same and records every command with the frame it ran at (Timeline);
Timeline.scene(t) rebuilds the scene at frame t for the preview: actors (motion, tint, offset), effect slots
(model, place, size, turn, colour), the camera, particles and sounds.

Values passed to helper events (found in the exe, _research/exe/operand_types.py):
  * call_event arguments become the callee's locals $20001.. as floats = argument / 10
  * a command reading a local as an int operand (slot, actor, effect id, frames: 'i' in
    data/script_operand_types.json) truncates it; as a fixed operand (positions, sizes: 'f') it multiplies by 10
  so `call_event 15130101, 10, 1060, 12560, -60, 80, ...` gives `cmd_3c00 $20001, $20002` slot 1, effect 106 and
  `cmd_3c10 .., $20003, $20004, ..` actor 1256 at x -60, y 80.

Editing (Edit): every recorded Op knows where each of its values comes from (Op.src: the literal in its own
instruction, or the call argument that fed the local), so the editor changes the right number; moving an op in
time moves its instruction inside its straight-line block (the waits around it are re-split so nothing else
moves), or the call that started it when the op lives in a shared helper.  Things the user adds go into small
"layer" events of their own (`wait <start>` + commands) spawned from the root, so they never disturb the original.
"""
import copy
import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List

from . import script

CASTER, TARGET = 1256, 3600
ACTOR_NAMES = {CASTER: "Caster", TARGET: "Target", 11000: "Camera point", 1000: "All units"}
AREA_TARGET = 3000                  # script actor 3000 + i: area target i (0 = TARGET); $60400 + i = 1 when it exists
MAX_TARGETS = 20                    # $60400..$60419 appear in the scripts
for _i in range(1, MAX_TARGETS):
    ACTOR_NAMES[AREA_TARGET + _i] = f"Target {_i + 1}"


def target_actor(i):
    """the preview's actor id of area target i"""
    return TARGET if int(i) == 0 else AREA_TARGET + int(i)


def is_target(a):
    return a == TARGET or (isinstance(a, int) and AREA_TARGET < a < AREA_TARGET + MAX_TARGETS)
LOCALS = range(20001, 20017)        # event locals (floats): call arguments / 10, local_calc results
LOOP_VAR = 20100                     # counter of the innermost loop
_DATA = os.path.join(os.path.dirname(__file__), "data")
with open(os.path.join(_DATA, "script_operand_types.json")) as _f:
    OPERAND_KINDS = json.load(_f)
with open(os.path.join(_DATA, "choreo_commands.json"), encoding="utf-8") as _f:
    COMMANDS = json.load(_f)["commands"]

# ------------------------------------------------------------------------------------------------ command kinds
EFFECT_CMDS = {0x3c00, 0x3c02, 0x3c10, 0x3c18, 0x3c20, 0x3c22, 0x3c30, 0x3c40, 0x3c42, 0x3c44, 0x3c64, 0x3c66,
               0x3c68, 0x3c6a, 0x3c70, 0x3c72, 0x3c74, 0x3c76, 0x3c78, 0x3c80, 0x3c88, 0x3c90, 0x3ca0, 0x3cb8, 0x3cba,
               0x3cbc, 0x3cbd, 0x3cbe, 0x3cc6, 0x3cd6, 0x3cd8, 0x3cda, 0x3cdc, 0x4140, 0x4170,
               0x3c98, 0x3c9a, 0x3ca5, 0x3cde}                     # (slot first: drawing switches, traced)
SHOW_CMDS = {0x3c10, 0x3c18, 0x3c20, 0x3c22}
CAMERA_CMDS = {0x3210, 0x3220, 0x3230, 0x3240, 0x3250, 0x3258, 0x325c, 0x3260, 0x3268, 0x3280, 0x3290, 0x32a0, 0x2810,
               0x2820, 0x2830, 0x2832, 0x2834, 0x2835}
ACTOR_CMDS = {0x6510, 0x6530, 0x65a0, 0x65a1, 0x65b4, 0x65b5, 0x65b8, 0x65bc, 0x65c1, 0x6642, 0x6672, 0x6680,
              0x6480, 0x6482, 0x6c04, 0x6c08, 0x6402, 0x640a, 0x6410, 0x6411, 0x6412, 0x6460, 0x6500, 0x6570, 0x6620,
              0x6660, 0x6664, 0x6470, 0x6560}
PARTICLE_CMDS = {0x4400, 0x4410, 0x4418, 0x4428, 0x4430, 0x4438, 0x4480, 0x4490, 0x44b5}
SOUND_CMDS = {0x4612, 0x4610, 0x4618, 0x4630, 0x4632}
HIT_CMDS = {0x7220}                 # damage (the number shows); 0x32a0 is the camera shake
CALL_CMDS = {0x0100, 0x0104, 0x0106}
CHILD_WAITS = {0x0108, 0x0118, 0x0120, 0x0130}
STRUCTURE = {0x0140, 0x0148, 0x0150, 0x0158}
WAIT = 0x0a00
# what the preview assumes: facing, big unit, area target i exists ($60400 + i: the first), panels to the target
# ($64000: Dazzling Eyes' heart hits when it got that far), the caster's sprite ($62199: event poses), $64815: a game
# setting (dword +0xca8 of the object at 0x147B82D10, script getter 0x140194dfa) that makes the opening camera move
# of every skill (helper 12000012) 11 frames instead of 7 -- 1 in all the recordings
DEFAULT_VARS = {60201: 0, 62802: 0, 64856: 0, 60400: 1, 64000: 1, 62199: 0, 64815: 1}

TIMED = {   # command -> index of its duration operand
    0x3c40: 1, 0x3c42: 1, 0x3c44: 1, 0x3c64: 1, 0x3c68: 1, 0x3c74: 1, 0x3c80: 1, 0x3c88: 1, 0x3cb8: 1,
    0x3cda: 1, 0x65a0: 1, 0x65b4: 1, 0x65b8: 1, 0x4428: 1, 0x3210: 4, 0x3220: 4, 0x3230: 0, 0x3240: 0,
    0x6480: 5, 0x4140: 5, 0x6642: 5, 0x4170: 5, 0x6672: 5, 0x2810: 1,
    0x3c6a: 1, 0x3c70: 1, 0x3c72: 1, 0x3c76: 1, 0x3cba: 1, 0x3cdc: 1, 0x3c66: 1,
    0x3250: 0, 0x3258: 0, 0x3260: 0, 0x3268: 0, 0x3280: 0, 0x3290: 0,
    0x2820: 4, 0x2830: 0, 0x2832: 0, 0x2834: 0, 0x2835: 0,
    0x6482: 2, 0x6664: 4, 0x6680: 5, 0x65a1: 1, 0x65b5: 1, 0x65c1: 1,
}


def kind_of(cid):
    if cid in EFFECT_CMDS:
        return "effect"
    if cid in CAMERA_CMDS:
        return "camera"
    if cid in ACTOR_CMDS:
        return "actor"
    if cid in PARTICLE_CMDS:
        return "particle"
    if cid in SOUND_CMDS:
        return "sound"
    if cid in HIT_CMDS:
        return "hit"
    if cid in CALL_CMDS:
        return "call"
    if cid == WAIT or cid in CHILD_WAITS or cid in STRUCTURE or cid in (0x1400, 0x1410):
        return "control"
    return "other"


def operand_kind(cid, i):
    k = OPERAND_KINDS.get(f"0x{cid:04x}", "")
    return k[i] if i < len(k) else "i"


def arg_names(cid):
    d = COMMANDS.get(script.cmd_name(cid))
    n = len(script.SIGS.get(cid, []))
    names = list(d["args"]) if d else []
    return [names[i] if i < len(names) else f"p{i + 1}" for i in range(n)]


def describe(cid):
    d = COMMANDS.get(script.cmd_name(cid))
    return d["desc"] if d else ""


def _signed(v, size):
    if isinstance(v, int) and size in (2, 4) and v >= 1 << (8 * size - 1):
        return v - (1 << (8 * size))
    return v


def actor_id(a):
    """script actor operands: 1256 / 6101 = the caster, 3600 / 3603 = the target (other ids stay)"""
    try:
        a = int(a)
    except (TypeError, ValueError):
        return a
    if a in (CASTER, 6101, 12560):
        return CASTER
    if a in (TARGET, 3603, 36000, 3000, 30000) or 3600 <= a < 3610 or 36000 <= a < 36100:
        return TARGET            # 3600: the main target (= area target 0 here), 3000 / 30000: area target 0
    if AREA_TARGET < a < AREA_TARGET + 256:
        return a                 # area target i (the game: the unit on the area's i-th hit panel)
    if 30000 < a < 32560 and a % 10 == 0:
        return AREA_TARGET + (a - 30000) // 10      # x10 (call arguments are divided by 10)
    return a


def copy_source(v):
    """cmd_6410 / 6412's second value (0x140168d70): u16 = mode x 10000 + number; mode 0 / 1 an actor, 2 a unit,
    3 a class's look, 5 a sprite (9100: an empty one -- an invisible helper)"""
    try:
        u = int(v) & 0xFFFF
    except (TypeError, ValueError):
        return 0, v
    return u // 10000, u % 10000


def who(a):
    """an actor operand in words"""
    try:
        a = int(a)
    except (TypeError, ValueError):
        return str(a)
    if 300 <= a < 400:
        return f"point {a}"
    if a == 10000:
        return "all units"
    if 10000 < a < 20000:
        return f"where {who(a - 10000)} is"
    b = actor_id(a)
    if b in ACTOR_NAMES:
        return ACTOR_NAMES[b]
    if 1000 <= b < 1100:
        return f"extra {b}"
    if 5000 <= b < 5256:
        return f"area panel {b - 5000 + 1}"
    if 7000 <= b < 7256:
        return f"effect slot {b - 7000}"
    return f"actor {b}"


def _pct(v):
    return f"{int(v)}%"


def short_label(c, a):
    """timeline label of command c with operands a (None: no short form)"""
    if c == 0x3c00:
        return f"load effect {a[1]}"
    if c in SHOW_CMDS:
        return "show" + (" (attached)" if c in (0x3c20, 0x3c22) else "")
    if c == 0x3c02:
        return "remove"
    if c == 0x6510:
        return f"motion {a[1]}"
    if c in SOUND_CMDS:
        return ("voice " if c in (0x4630, 0x4632) else "sound ") + str(a[0])
    # camera / screen
    if c in (0x3210, 0x3220):
        return f"aim → {who(a[0])}"
    if c in (0x3230, 0x3240):
        return "zoom: default" if not a[1] else f"zoom {a[1]}" + (" (in)" if a[1] < 700 else " (out)" if a[1] > 700 else "")
    if c in (0x3260, 0x3280):
        parts = [f"{n} {v}°" for n, v in (("pitch", a[1]), ("yaw", a[2]), ("roll", a[3])) if v]
        return "turn camera " + (", ".join(parts) if parts else "0°")
    if c == 0x3268:
        return "camera angle"
    if c == 0x3290:
        return "camera back"
    if c == 0x325c:
        return "camera stops turning"
    if c in (0x3250, 0x3258):
        v = a[1] if len(a) > 1 else 0
        return f"camera lens {27008.0 / v:.0f}°" if v else "camera lens (battle)"
    if c == 0x2810:
        v = a[0] - 256 if a[0] > 127 else a[0]
        return "clear screen" if v == 0 else ("fade to black" if v > 0 else "fade to white") + \
            ("" if abs(v) >= 127 else f" {abs(v) * 100 // 127}%")
    if c == 0x2820:
        return "hide map" if a[3] == 0 else f"map colour {a[3]}%"
    if c in (0x2830, 0x2832, 0x2834):
        return "backdrop"
    if c == 0x2835:
        return "backdrop off"
    # effects
    if c in (0x3c40, 0x3c42):
        return f"size {a[2]}%" if a[2] == a[3] == a[4] else f"size {a[2]}/{a[3]}/{a[4]}%"
    if c in (0x3c64, 0x3c66, 0x3c70, 0x3c72):
        return "turn to " + "/".join(str(v) for v in a[2:5]) + "°"
    if c in (0x3c68, 0x3c6a, 0x3c74, 0x3c76):
        return "spin " + "/".join(str(v) for v in a[2:5]) + "°"
    if c in (0x3c80, 0x3c88):
        return "fade out" if a[5] == 0 else "colour" + ("" if a[5] == 100 else f" {a[5]}%")
    if c in (0x3cda, 0x3cdc):
        return "fade out" if a[2] == 0 else f"opacity {a[2]}%"
    if c in (0x3cb8, 0x3cba):
        return f"piece size {a[2]}%"
    if c == 0x3c90:
        return "anim speed"
    if c == 0x3cc6:
        return f"to frame {a[1]}"
    if c == 0x3cd6:
        return "blend " + {1: "normal", 2: "add light", 3: "take light", 4: "multiply", 5: "minus screen"}.get(a[1], "own")
    if c == 0x3cd8:
        return "face camera" if a[1] == 1 else "upright" if a[1] == 2 else "no billboard" if a[1] == 0 else "billboard"
    if c == 0x3c30:
        return f"layer {a[2]}"
    if c == 0x3c78:
        return "rotation order"
    if c == 0x4140:
        return f"move → {who(a[1])}"
    if c == 0x4170:
        return f"fly → {who(a[1])}"
    # actors
    if c == 0x6642:
        return f"move → {who(a[1])}" if a[5] else f"put at {who(a[1])}"
    if c == 0x6672:
        return f"dash → {who(a[1])}"
    if c == 0x6680:
        return f"jump → {who(a[1])}"
    if c == 0x6620:
        return "base = here"
    if c == 0x6480:
        return "hide" if a[4] == 0 else ("tint" if (a[1], a[2], a[3]) != (100, 100, 100) else "untint") + \
            ("" if a[4] == 100 else f" {a[4]}%")
    if c == 0x6482:
        return "hide" if a[1] == 0 else f"opacity {a[1]}%"
    if c == 0x6c04:
        return f"follow {who(a[1])}"
    if c == 0x6c08:
        return "stop following"
    if c == 0x6402:
        return f"look of class {a[1]}"
    if c == 0x640a:
        return "switch on"
    if c in (0x6410, 0x6412):
        mode, num = copy_source(a[1])
        if mode == 5:
            return "invisible helper" if num == 9100 else f"sprite {num}"
        if mode == 3:
            return f"look of class {num}"
        return f"copy of {who(num)}"
    if c == 0x6411:
        return f"cut-in of {who(a[1])}"
    if c == 0x6460:
        return "on screen" if a[1] else "in the world"
    if c == 0x6660:
        return "place cut-in"
    if c == 0x6664:
        return "slide cut-in"
    if c in (0x65a0, 0x65a1):
        return f"size {a[2]}%" if a[2] == a[3] else f"size {a[2]}/{a[3]}%"
    if c in (0x65b4, 0x65b5):
        return f"spin {a[4]}°"
    if c in (0x65b8, 0x65c1):
        return f"tilt to {a[4]}°"
    if c == 0x65bc:
        return "shift sprite" if a[2] or a[3] else "unshift sprite"
    if c == 0x72f0:
        return "mirror on" if a[0] else "mirror off"
    if c == 0x6500:
        return f"anim {a[1]}"
    if c == 0x6530:
        return f"motion to frame {a[1]}"
    if c == 0x6470:
        return "shadow on" if a[1] else "no shadow"
    if c == 0x66b0:
        return f"point {a[0]} at {who(a[1])}"
    if c == 0x66b8:
        return f"move point {a[0]}"
    # damage / particles
    if c == 0x7220:
        return f"hit {who(a[0])} {_pct(a[2])}"
    if c == 0x32a0:
        return "shake" + ("" if a[2] < 32768 else " (until stopped)")
    if c == 0x4400:
        return f"particles {a[0]}"
    if c == 0x4410:
        return "particle colour"
    if c == 0x4418:
        return "particle colour change"
    if c == 0x4428:
        return "stop particles"
    if c == 0x4430:
        return f"particle life {a[1]}"
    if c in (0x4480, 0x4490, 0x44b5):
        return {0x4480: "burst", 0x4490: "stream", 0x44b5: "ring"}[c] + f" at {who(a[1])}"
    if c == 0x3ca0:
        return f"nearer camera {a[1]}"
    if c == 0x3cde:
        return f"draw queue {a[1]}"
    if c == 0x3c9a:
        return "show" if a[1] else "hide"
    if c == 0x3ca5:
        return "faces camera off" if a[1] else "faces camera"
    if c in (0x3cbc, 0x3cbd, 0x3cbe):
        return {0x3cbc: "size + turn", 0x3cbd: "turn", 0x3cbe: "size"}[c] + " with actor" + ("" if a[1] else " off")
    if c == WAIT:
        return f"wait {a[0]}"
    if c in CALL_CMDS:
        return ("start " if c == 0x0100 else "run ") + str(a[0])
    return None


@dataclass
class Op:
    frame: int
    eid: int                  # event holding the instruction
    pc: int                   # its index in the event at the time of the run
    ins: object               # script.Ins
    args: list                # operand values as executed
    kind: str
    dur: int = 0
    chain: tuple = ()         # ((eid, pc), ...) call sites from the root down to the event holding this op
    src: list = field(default_factory=list)   # per operand: (eid, pc, operand index, scale) of the literal, or None
    calls: tuple = ()         # the call instructions (Ins) above it

    @property
    def ident(self):
        """identity that survives edits and re-simulation (instructions are kept as objects when they move)"""
        return tuple(id(i) for i in self.calls) + (id(self.ins),)

    @property
    def cid(self):
        return self.ins.cid

    @property
    def name(self):
        return self.ins.name

    @property
    def end(self):
        return self.frame + self.dur

    @property
    def slot(self):
        return self.args[0] if self.kind in ("effect", "particle") and self.args else None

    @property
    def actor(self):
        return actor_id(self.args[0]) if self.kind == "actor" and self.args else None

    def label(self):
        """a short name for the timeline: what it does and its main value ("zoom 400", "dash → Target")"""
        try:
            t = short_label(self.cid, self.args)
        except (IndexError, TypeError, ValueError):
            t = None
        if t:
            return t
        d = COMMANDS.get(self.name)
        return (d["desc"].split(" (")[0].split(";")[0][:28]) if d else self.name


# Loading pauses.  cmd_640a actor ("switch on", 0x1401689d0) waits -- it rewinds the script and returns 0 -- while
# the actor's sprite files are still loading (+0x1e4 / +0x20c / +0x224 != -1).  How long that takes depends on the
# PC and on what is already in memory; measured on the recordings (first cast in a battle): an event-pose sheet
# (cmd_6402 / 6405 with 7000-7999) is ready 10 frames after it was asked for, a cut-in portrait (cmd_6411) 7 frames;
# class sprites cost nothing (Macrocosm's class 20 actor: no wait).  With the 11-frame opening ($64815) Macrocosm's
# frames then equal its recording's from the start, Dazzling Eyes' (sheet, then cut-in) too.
LOAD_FRAMES = 10
LOAD_FRAMES_CUTIN = 7


@dataclass
class Context:
    """what the preview assumes: facing ($60201: 0-3) and big unit ($62802) branches, and the root's arguments;
    loading: simulate the loading pauses of a first cast (see LOAD_FRAMES); in_battle: sprite numbers the battle
    already holds (caster, targets); sprite_exists(n): False for numbers with no sprite file (invisible helpers)"""
    vars: Dict[int, int] = field(default_factory=lambda: dict(DEFAULT_VARS))
    args: tuple = ()
    loading: bool = False
    in_battle: tuple = ()
    sprite_exists: object = None


# ------------------------------------------------------------------------------------------------ simulation
class _Fiber:
    __slots__ = ("gen", "wake", "children", "done", "eid", "waiting_children", "chain", "calls")

    def __init__(self, eid, chain, calls=()):
        self.gen = None
        self.eid, self.chain, self.calls = eid, chain, calls
        self.wake = 0
        self.children = []
        self.done = False
        self.waiting_children = False


class Simulator:
    """runs a choreography tree: Simulator(events, root, ctx).run() -> Timeline"""
    MAX_FRAMES = 3600

    def __init__(self, ev, root, ctx=None):
        self.ev = ev                         # {eid: script.Event}
        self.root = int(root)
        self.ctx = ctx or Context()
        self.ops: List[Op] = []
        self.frame = 0
        self.fibers: List[_Fiber] = []
        self.motion_start = {}
        self.vars = dict(self.ctx.vars)
        self.exec_count = {}
        self.sprite_of = {}                  # actor -> sprite number it was given (cmd_6402 / 6405 / 6411)
        self.ready_at = {}                   # actor -> frame its sprite has loaded (cmd_640a waits for it)
        self.loading_until = {}              # sprite number -> frame it has loaded

    # ------------------------------------------------------------------ operands
    def _read(self, v, regs, size, kind):
        """operand value as a command sees it"""
        if isinstance(v, script.Var):
            if v.id in LOCALS:
                f = regs.get(v.id, 0.0)
                if not math.isfinite(f):
                    return 0
                return int(f * 10) if kind == "f" or size == 4 else int(f)
            n = int(regs.get(LOOP_VAR, 0)) if v.id == LOOP_VAR else int(self.vars.get(v.id, 0))
            return n * 10 if size == 4 else n
        return _signed(v, size)

    @staticmethod
    def _src(v, eid, pc, i, srcs, size, kind):
        if isinstance(v, script.Var):
            if v.id in LOCALS and srcs.get(v.id):
                e, p, k = srcs[v.id]
                return (e, p, k, 1 if (kind == "f" or size == 4) else 10)
            return None
        return (eid, pc, i, 1)

    def _cond_val(self, v, regs):
        if isinstance(v, script.Var):
            return regs.get(v.id, 0.0) if v.id in LOCALS else self.vars.get(v.id, 0)
        return _signed(v, 2)

    def _cond(self, ins, regs):
        res = None
        for i, cd in enumerate(ins.conds):
            a, b = self._cond_val(cd.lhs, regs), self._cond_val(cd.rhs, regs)
            op = script.CMP_OPS.get(cd.op)
            r = {"==": a == b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b, "!=": a != b}.get(op, False)
            if res is None:
                res = r
            elif script.LOGIC_OPS.get(ins.logic[i - 1]) == "and":
                res = res and r
            else:
                res = res or r
        return bool(res)

    # ------------------------------------------------------------------ events
    def _event(self, fiber, args, arg_srcs):
        """generator running one event; args are the call's raw literals (or caller values x10)"""
        eid = fiber.eid
        e = self.ev.get(eid)
        if e is None or e.raw is not None:
            return
        regs = {20001 + i: a / 10.0 for i, a in enumerate(args)}
        srcs = {20001 + i: s for i, s in enumerate(arg_srcs)}
        code = e.code
        index = {id(x): k for k, x in enumerate(code)}
        loops = []
        pc = 0
        guard = 0
        while pc < len(code):
            guard += 1
            if guard > 50000:
                return
            ins = code[pc]
            c = ins.cid
            key = (eid, pc)
            self.exec_count[key] = self.exec_count.get(key, 0) + 1
            if c == 0x0140:
                if not self._cond(ins, regs):
                    pc = index[id(ins.target)] if ins.target is not None else len(code)
                    continue
            elif c == 0x0150:
                a = self._read(ins.args[0], regs, 2, "i")
                b = self._read(ins.args[1], regs, 2, "i")
                cnt = max(a, 0)
                loops.append([pc, cnt, max(b, cnt)])
                regs[LOOP_VAR] = cnt
            elif c == 0x0158:
                if loops:
                    lp = loops[-1]
                    if lp[1] < lp[2]:
                        lp[1] += 1
                        regs[LOOP_VAR] = lp[1]
                        pc = lp[0] + 1
                        continue
                    loops.pop()
                    regs[LOOP_VAR] = loops[-1][1] if loops else 0
            elif c in (0x1440, 0x1442, 0x1446):
                # local[i] = a/10 <op> b/10 (op 0 add, 1 sub, 2 mul, 3 div, 4 mod; 0x140184020); local_set: = b/10
                i = self._read(ins.args[0], regs, 1, "i")
                if c == 0x1446:
                    a, opn, b = 0, 0, self._read(ins.args[1], regs, 4, "f")
                    lit = 1
                else:
                    a = self._read(ins.args[1], regs, 4, "f")
                    opn = self._read(ins.args[2], regs, 1, "i")
                    b = self._read(ins.args[3], regs, 4, "f")
                    lit = 3
                fa, fb = a / 10.0, b / 10.0
                if opn == 0:
                    r = fa + fb
                elif opn == 1:
                    r = fa - fb
                elif opn == 2:
                    r = fa * fb
                elif opn in (3, 4):
                    ia, ib = int(fa), int(fb)
                    if ib == 0:
                        r = 0.0
                    else:
                        q = abs(ia) // abs(ib) * (1 if (ia >= 0) == (ib >= 0) else -1)
                        r = float(q if opn == 3 else ia - q * ib)
                else:
                    r = fb
                vid = 20000 + int(i)
                regs[vid] = r if math.isfinite(r) and abs(r) < 1e7 else 0.0
                # editable when it is a plain "local = literal"
                plain = opn == 0 and not isinstance(ins.args[lit], script.Var) and                     (c == 0x1446 or ins.args[1] == 0)
                srcs[vid] = (eid, pc, lit) if plain else None
            elif c in (0x1400, 0x1410):
                raw, vid, opn, val = ins.args
                v = self._cond_val(val, regs)
                cur = regs.get(vid, 0.0) if vid in LOCALS else self.vars.get(vid, 0)
                new = {0: v, 1: v, 2: cur + v, 3: cur - v, 4: cur * v}.get(opn, v)
                if vid in LOCALS:
                    regs[vid] = new
                else:
                    self.vars[vid] = new
            elif c == WAIT:
                n = self._read(ins.args[0], regs, 2, "i")
                self._record(fiber, pc, ins, [n], [self._src(ins.args[0], eid, pc, 0, srcs, 2, "i")])
                if n > 0:
                    yield ("wait", n)
            elif c in CHILD_WAITS:
                yield ("children",)
                if c in (0x0108, 0x0118):        # wait_children: wait, then END the event (0x14018c080);
                    return                       # wait_children_c (0x0120) / wait_idle continue
            elif c in CALL_CMDS:
                target = self._read(ins.args[0], regs, 3, "i")
                cargs, csrcs = [], []
                for k, a in enumerate(ins.args[1:]):
                    if isinstance(a, script.Var):
                        if a.id in LOCALS:
                            cargs.append(int(regs.get(a.id, 0.0) * 10))
                            csrcs.append(srcs.get(a.id))
                        else:
                            cargs.append(int(self.vars.get(a.id, 0)) * 10)
                            csrcs.append(None)
                    else:
                        cargs.append(_signed(a, 4))
                        csrcs.append((eid, pc, k + 1))
                self._record(fiber, pc, ins, [target] + cargs, [None] * (1 + len(cargs)))
                # every child counts for wait_children, spawn_event's too (seen in game 2026-10-08: a root that
                # spawned long events first stalled at its first wait_children_c until they ended)
                self._start(target, cargs, csrcs, fiber, waited=True, site=(eid, pc), site_ins=ins)
            elif c in STRUCTURE:
                pass
            else:
                sig = script.SIGS.get(c, [])
                vals, sv = [], []
                for i, a in enumerate(ins.args):
                    if isinstance(a, bytes):
                        vals.append(a)
                        sv.append(None)
                        continue
                    size = sig[i] if i < len(sig) else 2
                    k = operand_kind(c, i)
                    vals.append(self._read(a, regs, size, k))
                    sv.append(self._src(a, eid, pc, i, srcs, size, k))
                self._record(fiber, pc, ins, vals, sv)
                if c == 0x6510:
                    self.motion_start[actor_id(vals[0])] = self.frame
                elif c in (0x6402, 0x6405, 0x6411):
                    self._spawned(c, vals)
                elif c == 0x640a and self.ctx.loading:
                    ready = self.ready_at.get(actor_id(vals[0]), 0)
                    if ready > self.frame:
                        yield ("wait", ready - self.frame)
            pc += 1

    def _spawned(self, c, vals):
        """an actor got a sprite: when its files will have loaded (see LOAD_FRAMES)"""
        try:
            a, n = actor_id(vals[0]), int(vals[1])
        except (IndexError, TypeError, ValueError):
            return
        if c == 0x6411:                       # a cut-in: the portrait file of the other actor's sprite
            src = actor_id(n)
            base = self.sprite_of.get(src)
            if base is None and src == CASTER and self.ctx.in_battle:
                base = self.ctx.in_battle[0]
            if base is None:
                return
            n, cost = 10000 + int(base), LOAD_FRAMES_CUTIN
        elif 7000 <= n < 8000:                 # an event-pose sheet
            cost = LOAD_FRAMES
        else:                                  # a class's sprite: in memory already (see LOAD_FRAMES)
            self.sprite_of[a] = n
            return
        self.sprite_of[a] = n
        if n in self.ctx.in_battle or (self.ctx.sprite_exists is not None and not self.ctx.sprite_exists(n)):
            return
        until = self.loading_until.get(n)
        if until is None:
            until = self.loading_until[n] = self.frame + cost
        self.ready_at[a] = max(self.ready_at.get(a, 0), until)

    def _record(self, fiber, pc, ins, vals, srcs):
        kind = kind_of(ins.cid)
        dur = 0
        if ins.cid in TIMED and TIMED[ins.cid] < len(vals):
            try:
                dur = max(0, int(vals[TIMED[ins.cid]]))
            except (TypeError, ValueError):
                dur = 0
        if ins.cid == WAIT:
            dur = max(0, int(vals[0]))
        op = Op(self.frame, fiber.eid, pc, ins, vals, kind, dur, fiber.chain, srcs, fiber.calls)
        self.ops.append(op)
        return op

    def _start(self, eid, args, srcs, parent, waited=True, site=None, site_ins=None):
        if parent is not None and len(parent.chain) > 24:        # an event calling itself
            return None
        if parent is not None and site:
            f = _Fiber(int(eid), parent.chain + (site,), parent.calls + (site_ins,))
        else:
            f = _Fiber(int(eid), ())
        f.gen = self._event(f, args, srcs)
        if waited and parent is not None:
            parent.children.append(f)
        self.fibers.append(f)
        self._step(f)
        return f

    def _step(self, f):
        """run fiber f until it blocks"""
        while not f.done:
            try:
                r = next(f.gen)
            except StopIteration:
                f.done = True
                return
            if r[0] == "wait":
                f.wake = self.frame + r[1]
                return
            if r[0] == "children":
                if all(ch.done for ch in f.children):
                    continue
                f.waiting_children = True
                return

    def run(self):
        """until the root event ends (the game then ends the skill; events it spawned and never waited for are
        cut there too)"""
        root = self._start(self.root, list(self.ctx.args), [None] * len(self.ctx.args), None)
        while self.frame < self.MAX_FRAMES:
            if root.done:
                break
            self.frame += 1
            progress = True
            while progress:            # children ending this frame release their parents this frame
                progress = False
                for f in list(self.fibers):
                    if f.done:
                        continue
                    if f.waiting_children:
                        if all(ch.done for ch in f.children):
                            f.waiting_children = False
                            self._step(f)
                            progress = True
                    elif 0 <= f.wake <= self.frame:
                        f.wake = -1
                        self._step(f)
                        progress = True
        return Timeline(self.ops, self.frame, self.root, self.ev, self.exec_count, self.ctx)


def simulate(ev, root, ctx=None):
    return Simulator(ev, root, ctx).run()


# ------------------------------------------------------------------------------------------------ timeline
class Timeline:
    def __init__(self, ops, length, root, events, exec_count, ctx):
        self.ops: List[Op] = ops
        self.length = length
        self.root = root
        self.events = events
        self.exec_count = exec_count
        self.ctx = ctx

    def tracks(self):
        """[(track key, title, [ops])] in display order: camera, caster, target, effect slots, particles, sound,
        hits"""
        out, order = {}, []

        def add(key, title, op):
            if key not in out:
                out[key] = (title, [])
                order.append(key)
            out[key][1].append(op)
        for op in self.ops:
            k = op.kind
            if k == "camera":
                add(("camera",), "Camera", op)
            elif k == "actor":
                a = op.actor
                add(("actor", a), ACTOR_NAMES.get(a, f"Actor {a}"), op)
            elif k == "effect":
                add(("slot", op.slot), f"Effect slot {op.slot}", op)
            elif k == "particle":
                add(("particle", op.slot), f"Particles {op.slot}", op)
            elif k == "sound":
                add(("sound",), "Sound", op)
            elif k == "hit":
                add(("hit",), "Hits", op)
        rank = {"camera": 0, "actor": 1, "slot": 2, "particle": 3, "other": 4, "sound": 5, "hit": 6}

        def sk(key):
            sub = key[1] if len(key) > 1 else 0
            kind = key[0]
            if kind == "actor":
                if sub == CASTER or is_target(sub):
                    sub = 0 if sub == CASTER else 1 + (0 if sub == TARGET else sub - AREA_TARGET)
                else:
                    kind = "other"           # extra actors (after-images, party members) after the effects
            return rank[kind], sub if isinstance(sub, int) else 0
        order.sort(key=sk)
        return [(k, out[k][0], out[k][1]) for k in order]

    def clips(self, slot):
        """effect slot -> [dict(start, end, effect, ops, show)]: from a show to the next load / show / remove"""
        spans, cur, effect, pending = [], None, None, []
        for op in self.ops:
            if op.kind != "effect" or op.slot != slot:
                continue
            c = op.cid
            if c == 0x3c00:
                if cur:
                    cur["end"] = op.frame
                    spans.append(cur)
                    cur = None
                effect = op.args[1]
                pending = [op]
            elif c in SHOW_CMDS:
                if cur:
                    cur["end"] = op.frame
                    spans.append(cur)
                cur = dict(start=op.frame, end=None, effect=effect, ops=pending + [op], show=op)
                pending = []
            elif c == 0x3c02:
                if cur:
                    cur["end"] = op.frame
                    cur["ops"].append(op)
                    spans.append(cur)
                    cur = None
            else:
                (cur["ops"] if cur else pending).append(op)
        if cur:
            cur["end"] = self.length
            spans.append(cur)
        for s in spans:
            s["end"] = max(s["end"], s["start"] + 1)
        return spans

    def motions(self, actor):
        """[(start, end, motion, op)] of the actor's cmd_6510 motions"""
        ms = [op for op in self.ops if op.cid == 0x6510 and op.actor == actor]
        out = []
        for k, op in enumerate(ms):
            end = ms[k + 1].frame if k + 1 < len(ms) else self.length
            out.append((op.frame, max(end, op.frame + 1), op.args[1], op))
        return out

    def scene(self, t):
        """the state at frame t (dict: actors, slots, camera, particles, fade, locators); with a stage simulation
        bound (d5lib.stage.StageSim, the editor's preview) it comes from there"""
        sim = getattr(self, "stage", None)
        if sim is not None:
            return sim.scene(t)
        st = _SceneState()
        for op in self.ops:
            if op.frame > t:
                break
            try:
                st.apply(op)
            except (IndexError, TypeError, ValueError):
                pass
        return st.result(t)


# ------------------------------------------------------------------------------------------------ scene state
def _lerp(a, b, f):
    return [x + (y - x) * f for x, y in zip(a, b)]


class _Anim:
    """a value changing linearly over N frames from its value at the start"""
    __slots__ = ("start", "frames", "src", "dst")

    def __init__(self, start, frames, src, dst):
        self.start, self.frames, self.src, self.dst = start, frames, list(src), [float(x) for x in dst]

    def at(self, t):
        if self.frames <= 0 or t >= self.start + self.frames:
            return list(self.dst)
        f = max(0.0, (t - self.start) / self.frames)
        return _lerp(self.src, self.dst, f)


def _const(v):
    return _Anim(0, 0, v, v)


class _SceneState:
    def __init__(self):
        self.actors = {CASTER: self._actor(), TARGET: self._actor()}
        self.slots = {}
        self.cam = dict(actor=CASTER, anim=None, zoom=None, shake=None)
        self.particles = {}
        self.fade = None
        self.locators = {}

    @staticmethod
    def _actor():
        return dict(motion=0, motion_start=0, tint=_const([100, 100, 100, 100]), offset=_const([0, 0, 0]),
                    scale=_const([100, 100, 100]), rot=_const([0, 0, 0]), visible=True, sprite=None, copy=None,
                    anim=None, speed=100, place=[])

    @staticmethod
    def _slot():
        return dict(effect=None, visible=False, actor=CASTER, pos=[0, 0, 0], size=1000, start=0, attached=False,
                    anim=None, scale=_const([100, 100, 100]), rot=_const([0, 0, 0]), move=_const([0, 0, 0]),
                    color=_const([100, 100, 100, 100]), glow=_const([0]), speed=100, mode=0, layer=0, fly=None)

    def actor(self, a):
        a = actor_id(a)
        if a not in self.actors:
            self.actors[a] = self._actor()
        return self.actors[a]

    def slot(self, s):
        if s not in self.slots:
            self.slots[s] = self._slot()
        return self.slots[s]

    def cam_at(self, t):
        an = self.cam["anim"]
        return an.at(t) if an else [0.0, 0.0, 0.0]

    def zoom_at(self, t):
        z = self.cam["zoom"]
        return z.at(t)[0] if z else 0.0

    def apply(self, op):
        c, a, f = op.cid, op.args, op.frame
        if c == 0x6510:
            ac = self.actor(a[0])
            ac["motion"], ac["motion_start"], ac["anim"] = a[1], f, None
        elif c == 0x6402:                          # extra actor drawn with a sprite (monster summons)
            ac = self.actor(a[0])
            ac.update(sprite=a[1], copy=None, motion=0, motion_start=f, anim=None, place=[])
        elif c in (0x6410, 0x6412):                # extra actor copying another one (after-images)
            ac = self.actor(a[0])
            if isinstance(a[1], int) and a[1] > 0:
                ac.update(copy=actor_id(a[1]), sprite=None, place=[])
        elif c == 0x6500:                          # an animation by id (minus = mirrored)
            ac = self.actor(a[0])
            ac["anim"], ac["motion_start"] = a[1], f
        elif c == 0x6570:
            self.actor(a[0])["speed"] = a[1]
        elif c in (0x6642, 0x6672):                # place / move relative to another actor over N frames
            ac = self.actor(a[0])
            ac["place"] = ac["place"] + [(f, a[5], a[1], list(a[2:5]))]
        elif c == 0x6480:
            ac = self.actor(a[0])
            ac["tint"] = _Anim(f, a[5], ac["tint"].at(f), a[1:5])
        elif c == 0x65b8:
            ac = self.actor(a[0])
            ac["offset"] = _Anim(f, a[1], ac["offset"].at(f), a[2:5])
        elif c == 0x65a0:
            ac = self.actor(a[0])
            ac["scale"] = _Anim(f, a[1], ac["scale"].at(f), a[2:5])
        elif c == 0x65b4:
            ac = self.actor(a[0])
            ac["rot"] = _Anim(f, a[1], ac["rot"].at(f), a[2:5])
        elif c == 0x66b0:
            self.locators[a[0]] = (actor_id(a[1]), list(a[2:5]))
        elif c == 0x3c00:
            s = self.slot(a[0])
            s.update(self._slot())
            s["effect"] = a[1]
        elif c in SHOW_CMDS:
            s = self.slot(a[0])
            s.update(visible=True, actor=actor_id(a[1]), pos=list(a[2:5]), size=a[5] or 1000, start=f,
                     attached=c in (0x3c20, 0x3c22), fly=None,
                     anim=(a[7], a[8], a[9]) if c in (0x3c18, 0x3c22) else None,
                     plays=a[7] if c in (0x3c10, 0x3c20) else -1)
        elif c == 0x3c02:
            if a[0] in self.slots:
                self.slots[a[0]]["visible"] = False
        elif c in (0x3c40, 0x3c42, 0x3c44, 0x3cb8):
            s = self.slot(a[0])
            s["scale"] = _Anim(f, a[1], s["scale"].at(f), a[2:5])
        elif c == 0x3c64:
            s = self.slot(a[0])
            s["rot"] = _Anim(f, a[1], s["rot"].at(f), a[2:5])
        elif c == 0x3c68:
            s = self.slot(a[0])
            cur = s["rot"].at(f)
            s["rot"] = _Anim(f, a[1], cur, [cur[i] + a[2 + i] for i in range(3)])
        elif c == 0x3c74:
            s = self.slot(a[0])
            cur = s["move"].at(f)
            s["move"] = _Anim(f, a[1], cur, [cur[i] + a[2 + i] for i in range(3)])
        elif c in (0x3c80, 0x3c88):
            s = self.slot(a[0])
            s["color"] = _Anim(f, a[1], s["color"].at(f), a[2:6])
        elif c == 0x3cda:
            s = self.slot(a[0])
            s["glow"] = _Anim(f, a[1], s["glow"].at(f), [a[2]])
        elif c == 0x3c30:
            self.slot(a[0])["mode"] = a[1]
        elif c == 0x3cd6:
            self.slot(a[0])["layer"] = a[1]
        elif c in (0x4140, 0x4170):
            sl = self.slot(a[0])
            sl["fly"] = (sl["fly"] or []) + [(f, a[5], actor_id(a[1]), list(a[2:5]))]
        elif c in (0x3220, 0x3210):
            cur = self.cam_at(f)
            self.cam["actor"] = actor_id(a[0])
            self.cam["anim"] = _Anim(f, a[4], cur, a[1:4])
            if c == 0x3220:
                self.cam["zoom"] = _Anim(f, a[4], [self.zoom_at(f)], [a[5]])
        elif c == 0x3230:
            self.cam["zoom"] = _Anim(f, a[0], [self.zoom_at(f)], [a[1]])
        elif c == 0x3240:
            self.cam["shake"] = (f, a[0], a[1])
        elif c == 0x2810:
            cur = self.fade.at(f) if self.fade else [0.0]
            self.fade = _Anim(f, a[1], cur, [a[0]])
        elif c in (0x4480, 0x4490, 0x44b5):
            self.particles[a[0]] = dict(start=f, actor=actor_id(a[1]), pos=list(a[2:5]), args=list(a), stop=None)
        elif c == 0x4428 and a[0] in self.particles:
            self.particles[a[0]]["stop"] = f + a[1]

    def result(self, t):
        actors = {}
        for k, a in self.actors.items():
            actors[k] = dict(sprite=a["sprite"], copy=a["copy"], anim=a["anim"], speed=a["speed"],
                             place=[(base, off, 1.0 if n <= 0 else min(1.0, max(0.0, (t - f0) / n)))
                                    for f0, n, base, off in a["place"] if f0 <= t],
                             motion=a["motion"], motion_time=t - a["motion_start"], tint=a["tint"].at(t),
                             offset=a["offset"].at(t), scale=a["scale"].at(t), rot=a["rot"].at(t),
                             visible=a["visible"])
        slots = {}
        for k, s in self.slots.items():
            if not s["visible"] or s["effect"] is None:
                continue
            mv = s["move"].at(t)
            fly = None
            if s["fly"]:            # moves one after the other, each from where the last one got to
                fly = [(dst_actor, dst, 1.0 if n <= 0 else min(1.0, max(0.0, (t - f0) / n)))
                       for f0, n, dst_actor, dst in s["fly"] if f0 <= t]
            slots[k] = dict(effect=s["effect"], actor=s["actor"], pos=[s["pos"][i] + mv[i] for i in range(3)],
                            size=s["size"], scale=s["scale"].at(t), rot=s["rot"].at(t), color=s["color"].at(t),
                            glow=s["glow"].at(t)[0], speed=s["speed"], mode=s["mode"], layer=s["layer"],
                            time=t - s["start"], anim=s["anim"], fly=fly, plays=s.get("plays", -1))
        shake = 0.0
        if self.cam["shake"]:
            f0, n, strength = self.cam["shake"]
            if f0 <= t < f0 + n:
                shake = strength * math.sin((t - f0) * 1.9) * (1 - (t - f0) / max(1, n))
        parts = [dict(p, id=k, time=t - p["start"]) for k, p in self.particles.items()
                 if p["stop"] is None or t < p["stop"] + 20]
        return dict(actors=actors, slots=slots,
                    camera=dict(actor=self.cam["actor"], offset=self.cam_at(t), zoom=self.zoom_at(t), shake=shake),
                    particles=parts, fade=self.fade.at(t)[0] if self.fade else 0.0, locators=dict(self.locators))


# ------------------------------------------------------------------------------------------------ editing
def ins(name, *args):
    """a script instruction by mnemonic: ins('cmd_3c00', 5, 106)"""
    cid = script.MNEM[name] if name in script.MNEM else int(name[4:], 16)
    return script.Ins(cid, list(args))


def _is_wait(i):
    return i.cid == WAIT and isinstance(i.args[0], int)


def _uses_locals(i):
    return any(isinstance(a, script.Var) and a.id in LOCALS for a in i.args)


def _uses_var(i, vid):
    return any(isinstance(a, script.Var) and a.id == vid for a in i.args)


END_CMDS = (0x0108, 0x0118)          # wait_children / wait_children_b: wait for the children, then end the event


def terminate(code):
    """every event the game runs must end with wait_children (all 6017 vanilla choreography events do); without it
    the thread runs on in the game and the skill stalls (seen in game 2026-10-08) -- the simulator just stopped"""
    if not code or code[-1].cid not in END_CMDS:
        code.append(script.Ins(0x0108, []))
    return code


def _barrier(i):
    """instructions a move can't cross: structure, waits of unknown length"""
    return i.cid in STRUCTURE or i.cid in CHILD_WAITS or (i.cid == WAIT and not _is_wait(i))


class Edit:
    """Editable copy of a choreography's own events (`eids`, e.g. a custom copy's block) on top of `ev` (vanilla +
    mods).  Change values, move ops in time, delete them, add layer events; `simulate()` shows the result and
    `events_text()` gives the events to save."""

    BODY = 499          # the skill's own root code moves to root + 499 once layers are added (see _host)

    def __init__(self, ev, eids, root, layer_base=None):
        self.base = ev
        self.root = int(root)
        self.ev = {int(e): copy.deepcopy(ev[int(e)]) for e in eids if int(e) in ev}
        self.changed = set()
        self.layer_base = layer_base or (self.root + 500)
        self.history, self.future = [], []
        root_ev = self.ev.get(self.root)
        if root_ev is not None and root_ev.code and root_ev.code[0].cid in CALL_CMDS and root_ev.code[0].args and                 self._is_layer(root_ev.code[0].args[0]) and not self._is_host(root_ev.code):
            self._host()                 # layers an older kit started at the top of the body: give them a host

    # ---------------------------------------------------------------- state
    def events(self):
        d = dict(self.base)
        d.update(self.ev)
        return d

    def simulate(self, ctx=None):
        return Simulator(self.events(), self.root, ctx).run()

    def editable(self, eid):
        return eid in self.ev

    def _snap(self):
        return {k: copy.deepcopy(v) for k, v in self.ev.items()}, set(self.changed)

    def checkpoint(self):
        """call before every change (undo point)"""
        self.history.append(self._snap())
        if len(self.history) > 200:
            self.history.pop(0)
        self.future.clear()

    def undo(self):
        if not self.history:
            return False
        self.future.append(self._snap())
        self.ev, self.changed = self.history.pop()
        return True

    def redo(self):
        if not self.future:
            return False
        self.history.append(self._snap())
        self.ev, self.changed = self.future.pop()
        return True

    # ---------------------------------------------------------------- values
    def can_set(self, op, i):
        s = op.src[i] if i < len(op.src) else None
        return bool(s) and s[0] in self.ev

    @staticmethod
    def shared(op, i, tl):
        """True when the literal behind value i also feeds other runs (a helper called several times)"""
        s = op.src[i] if i < len(op.src) else None
        return bool(s) and tl.exec_count.get((s[0], s[1]), 1) > 1

    def set_value(self, op, i, value):
        """operand i of op (as executed) = value; writes the literal it came from"""
        s = op.src[i] if i < len(op.src) else None
        if not s or s[0] not in self.ev:
            raise ValueError("this value comes from a shared game helper; it can't be changed here")
        eid, pc, k, scale = s
        self.ev[eid].code[pc].args[k] = int(round(float(value) * scale))
        self.changed.add(eid)

    # ---------------------------------------------------------------- blocks and time
    def _block(self, eid, pos):
        """[start, end) of the straight-line block holding code[pos]: no structure, no waits of unknown length,
        only its first instruction may be a jump target"""
        code = self.ev[eid].code
        targets = {id(i.target) for i in code if i.cid == 0x0140 and i.target is not None}
        s = pos
        while s > 0 and id(code[s]) not in targets and not _barrier(code[s - 1]):
            s -= 1
        e = pos + 1
        while e < len(code) and not _barrier(code[e]) and id(code[e]) not in targets:
            e += 1
        return s, e

    def anchor(self, op, tl):
        """(eid, Ins) to move / delete for op: its own instruction, or the call that started it when it lives in a
        helper that runs more than once or isn't ours"""
        levels = list(op.chain) + [(op.eid, op.pc)]
        for eid, pc in reversed(levels):
            if eid in self.ev and tl.exec_count.get((eid, pc), 1) == 1 and pc < len(self.ev[eid].code):
                return eid, self.ev[eid].code[pc]
        return None

    def move(self, ops, delta, tl):
        """move ops by delta frames (each group inside its block; earlier than its block start is clamped) ->
        frames actually moved (the smallest over the groups)"""
        delta = int(delta)
        groups = {}
        for op in ops:
            a = self.anchor(op, tl)
            if a is None:
                continue
            eid, i = a
            if _barrier(i) or i.cid == WAIT:
                continue
            g = groups.setdefault(eid, [])
            if all(x is not i for x in g):
                g.append(i)
        if not groups:
            raise ValueError("these commands belong to shared game helpers; make the skill's own copy first")
        plans = []
        for eid, items in groups.items():
            code = self.ev[eid].code
            by_block = {}
            for i in items:
                k = next(n for n, x in enumerate(code) if x is i)
                by_block.setdefault(self._block(eid, k), []).append(i)
            for (s, e), its in by_block.items():
                timed, total, mine = self._timing(eid, s, e, its)
                if not mine:
                    continue
                d = max(delta, -min(x[0] for x in mine))
                in_layer = self.layer_base <= eid < self.layer_base + 500
                detachable = d > 0 and not in_layer
                if any(_uses_var(x[2], LOOP_VAR) for x in mine):
                    detachable = False        # the loop counter only exists inside its loop
                plans.append((eid, s, e, its, detachable, max(x[0] for x in mine) + d > total))
        # past the end of a block, commands go into an event of their own; when one part of a move has to, every
        # part does, so the moved commands keep their order (a load before its show on the same frame)
        detach = any(det and over for _, _, _, _, det, over in plans)
        moved = []
        for eid, s, e, its, det, over in sorted(plans, key=lambda p: (p[0], p[1]), reverse=True):
            moved.append(self._move_block(eid, s, e, its, delta, detach and det))
        self.changed |= set(groups)
        return min(moved, key=abs) if moved else 0

    def _timing(self, eid, s, e, items):
        """([relative frame, index, Ins] of the block's commands, block length, the ones in items)"""
        code = self.ev[eid].code
        timed, t = [], 0
        for k in range(s, e):
            i = code[k]
            if _is_wait(i):
                t += _signed(i.args[0], 2)
                continue
            timed.append([t, k, i])
        return timed, t, [x for x in timed if any(x[2] is i for i in items)]

    def _move_block(self, eid, s, e, items, delta, detach=False):
        code = self.ev[eid].code
        first = code[s]
        retarget = [i for ev in self.ev.values() for i in ev.code if i.cid == 0x0140 and i.target is first]
        timed, total, mine = self._timing(eid, s, e, items)
        if not mine:
            return 0
        d = max(delta, -min(x[0] for x in mine))
        if detach:
            # the commands move into an event of their own, started where they were and waiting `d` frames first
            # (nothing after the block is delayed)
            mine.sort(key=lambda x: (x[0], x[1]))
            t0 = mine[0][0]
            lines, cur = [script.Ins(WAIT, [d])], t0
            for ft, _, i in mine:
                if ft > cur:
                    lines.append(script.Ins(WAIT, [ft - cur]))
                    cur = ft
                lines.append(i)
            # a moved call the event waits for (wait_children) stays waited for: call_event, else spawn_event;
            # the new event then waits for that call too, as the block did
            waited = any(x[2].cid in (0x0104, 0x0106) for x in mine)
            if waited:
                after = code[e] if e < len(code) and code[e].cid in CHILD_WAITS else None
                lines.append(script.Ins(after.cid if after is not None else 0x0108, []))
            # locals the commands read are handed over as call arguments ($20014 -> $20001 ...): exact in every
            # branch; such a call is waited for like any call_event
            locs = sorted({a.id for x in mine for a in x[2].args if isinstance(a, script.Var) and a.id in LOCALS})
            remap = {v: 20001 + k for k, v in enumerate(locs)}
            for _, _, i in mine:
                i.args = [script.Var(remap[a.id], a.kind) if isinstance(a, script.Var) and a.id in remap else a
                          for a in i.args]
            nid = self.free_layer()
            self.ev[nid] = script.Event(nid, terminate(lines))
            self.changed.add(nid)
            gone = {id(x[2]) for x in mine}
            if locs:
                start = script.Ins(0x0104, [nid] + [script.Var(v) for v in locs])
            elif waited:
                start = script.Ins(0x0104, [nid])
            else:
                start = script.Ins(0x0100, [nid])
            timed = [x for x in timed if id(x[2]) not in gone] + [[t0, mine[0][1], start]]
        else:
            for x in mine:
                x[0] += d
                x[1] += 10 ** 6 if d > 0 else -10 ** 6
        timed.sort(key=lambda x: (x[0], x[1]))
        end_t = max([total] + [x[0] for x in timed])
        new, cur = [], 0
        for ft, _, i in timed:
            if ft > cur:
                new.append(script.Ins(WAIT, [ft - cur]))
                cur = ft
            new.append(i)
        if end_t > cur:
            new.append(script.Ins(WAIT, [end_t - cur]))
        code[s:e] = new
        for i in retarget:
            i.target = code[s] if s < len(code) else None
        return d

    def delete(self, ops, tl):
        """remove the ops' instructions (or the helper calls that made them); the timing of the rest stays"""
        gone = 0
        # resolve every target first: anchors are found by position, which shifts once something is deleted
        targets, seen = [], set()
        for op in ops:
            a = self.anchor(op, tl)
            if a is not None and id(a[1]) not in seen:
                seen.add(id(a[1]))
                targets.append(a)
        for eid, i in targets:
            code = self.ev[eid].code
            k = next((n for n, x in enumerate(code) if x is i), None)
            if k is None or i.cid in STRUCTURE or i.cid == WAIT:
                continue
            nxt = code[k + 1] if k + 1 < len(code) else None
            for x in (x for ev in self.ev.values() for x in ev.code if x.cid == 0x0140 and x.target is i):
                x.target = nxt
            del code[k]
            self.changed.add(eid)
            gone += 1
        return gone

    # ---------------------------------------------------------------- layers (things the user adds)
    def _is_layer(self, eid):
        return isinstance(eid, int) and self.layer_base <= eid < self.layer_base + 500

    def _is_host(self, code):
        return len(code) >= 2 and code[-1].cid in END_CMDS and all(i.cid in CALL_CMDS for i in code[:-1]) and \
            any(i.args and not self._is_layer(i.args[0]) for i in code[:-1])

    def _host(self):
        """the root as a host: it starts the layers and the skill's body (moved into its own event) side by side and
        waits for all of them.  In the game wait_children waits for every child thread, so layers started inside
        the body would hold up the body at its first wait_children_c (seen in game 2026-10-08)."""
        root = self.ev[self.root]
        if self._is_host(root.code):
            return root
        used = set(self.ev) | set(self.base)
        bid = self.root + self.BODY
        while bid in used or self._is_layer(bid):
            bid += 1 if bid < self.layer_base else 0
            if bid >= self.layer_base:
                bid = self.root + 1
                while bid in used:
                    bid += 1
                break
        code = root.code
        starts = []
        while code and code[0].cid in CALL_CMDS and code[0].args and self._is_layer(code[0].args[0]):
            starts.append(code.pop(0))
        # (layer starts further down are commands moved past their block: they stay where they are, their place is
        # their start time)
        self.ev[bid] = script.Event(bid, terminate(code))
        root.code = starts + [script.Ins(0x0104, [bid]), script.Ins(0x0108, [])]
        self.changed |= {bid, self.root}
        return root

    def layer_ids(self):
        return sorted(e for e in self.ev if self.layer_base <= e < self.layer_base + 500)

    def free_layer(self):
        used = set(self.ev) | set(self.base)
        e = self.layer_base
        while e in used:
            e += 1
        return e

    def used_slots(self, tl=None):
        s = set()
        for op in (tl.ops if tl else []):
            if op.kind == "effect" and isinstance(op.slot, int):
                s.add(op.slot)
        for e in self.ev.values():
            for i in e.code:
                if i.cid in EFFECT_CMDS and i.args and isinstance(i.args[0], int):
                    s.add(i.args[0])
        return s

    def free_slot(self, tl=None):
        used = self.used_slots(tl)
        for s in range(200, 40, -1):
            if s not in used:
                return s
        raise ValueError("no free effect slot")

    def add_layer(self, frame, lines):
        """new event: wait <frame>, then the lines; spawned at the start of the root -> its id"""
        eid = self.free_layer()
        code = terminate(([script.Ins(WAIT, [int(frame)])] if frame > 0 else []) + list(lines))
        self.ev[eid] = script.Event(eid, code)
        self._host().code.insert(0, script.Ins(0x0100, [eid]))
        self.changed |= {eid, self.root}
        return eid

    def add_layer_text(self, frame, body):
        """like add_layer, the body given as script text (if / else / labels allowed, e.g. one branch per facing)"""
        from .scriptpatch import parse_event_text
        eid = self.free_layer()
        head = f"event {eid}\n" + (f"    wait {int(frame)}\n" if frame > 0 else "")
        ev = parse_event_text(head + body)
        terminate(ev.code)
        self.ev[eid] = ev
        self._host().code.insert(0, script.Ins(0x0100, [eid]))
        self.changed |= {eid, self.root}
        return eid

    def add_effect(self, frame, effect, actor=CASTER, pos=(0, 60, 0), size=1000, frames=40, fade=10, tl=None):
        """an effect from the library: load, show at actor + pos, fade out over the last `fade` frames, remove"""
        slot = self.free_slot(tl)
        x, y, z = (int(v) for v in pos)
        lines = [ins("cmd_3c00", slot, int(effect)),
                 ins("cmd_3c10", slot, int(actor), x, y, z, int(size), 1000, 0)]     # 1000: frame step 1
        hold = max(0, frames - fade)
        if hold:
            lines.append(script.Ins(WAIT, [hold]))
        if fade:
            lines.append(ins("cmd_3c80", slot, fade, 100, 100, 100, 0))
            lines.append(script.Ins(WAIT, [fade]))
        lines.append(ins("cmd_3c02", slot))
        return self.add_layer(frame, lines), slot

    def remove_layer(self, eid):
        root = self.ev[self.root].code
        for k, i in enumerate(root):
            if i.cid in CALL_CMDS and i.args and i.args[0] == eid:
                nxt = root[k + 1] if k + 1 < len(root) else None
                for x in (x for x in root if x.cid == 0x0140 and x.target is i):
                    x.target = nxt
                del root[k]
                break
        self.ev.pop(eid, None)
        self.changed.add(self.root)
        self.changed.discard(eid)

    def insert_after(self, op, line, tl):
        """add `line` right after op's own instruction (same frame) -> True, or False if op isn't ours"""
        a = self.anchor(op, tl)
        if a is None:
            return False
        eid, i = a
        code = self.ev[eid].code
        k = next(n for n, x in enumerate(code) if x is i)
        code.insert(k + 1, line)
        self.changed.add(eid)
        return True

    # ---------------------------------------------------------------- output
    def events_text(self, only_changed=True):
        out = {}
        for eid, e in sorted(self.ev.items()):
            if only_changed and eid not in self.changed:
                continue
            out[eid] = "\n".join(l for l in script.disassemble_event(e, comments=False) if l.strip()) + "\n"
        return out
