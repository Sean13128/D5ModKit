"""Group edits of effects for the skill editor (d5gui/skilledit): move / spread / turn / resize several effects at once,
and give them new flight paths from presets (homing missile, arc, spiral, orbit, burst ...).

Positions in a choreography are offsets from an actor (script units, 120 = 1 panel, y up):
  show       cmd_3c10 / 3c18 / 3c20 / 3c22 slot, actor, x, y, z, size ...
  fly        cmd_4140 slot, actor, x, y, z, frames, mode       (move / attach to actor + offset over N frames)
             cmd_4170 slot, actor, x, y, z, frames, ...        (projectile flight to actor + offset)
The game turns these offsets by the skill's facing (stage.turn_offset: q = (4 - $60201) % 4 quarter turns): the
group transforms take world-space functions and a `quarter` and convert (cmd_3c74 is a second ROTATION, not a move).
Group transforms work in the frame of one actor (the pivot actor, the caster by default): a position given from
another actor is converted with that actor's offset from the pivot actor (`offsets`, from the preview) or left
alone.  Values that come from one literal used by several runs (a helper called several times) change once.

Paths: a preset gives every selected effect points along a curve, written as a layer event of cmd_4140 segments
(linear moves; enough of them look smooth) ending with a cmd_4170 flight into the target; the effect's own movement
commands in that time window are deleted.
"""
import math

import numpy as np

from . import choreo, script

SHOW = choreo.SHOW_CMDS
FLY = (0x4140, 0x4170)
DELTA = None                # (there is no "move by" command: 0x3c74 turns the effect's second rotation)


class Ref:
    """one position value of an effect: op, its x/y/z operand indices, the actor it's relative to (None: a delta)"""
    __slots__ = ("op", "idx", "actor", "kind")

    def __init__(self, op, idx, actor, kind):
        self.op, self.idx, self.actor, self.kind = op, idx, actor, kind

    def value(self):
        return np.array([float(self.op.args[i]) for i in self.idx])


def refs_of(ops):
    out = []
    for op in ops:
        c = op.cid
        try:
            if c in SHOW:
                out.append(Ref(op, (2, 3, 4), choreo.actor_id(op.args[1]), "show"))
            elif c in FLY:
                out.append(Ref(op, (2, 3, 4), choreo.actor_id(op.args[1]), "fly"))
        except IndexError:
            continue
    return out


class _Writer:
    """set values through the Edit once per literal; counts what could not change"""

    def __init__(self, edit):
        self.edit, self.done, self.fixed = edit, set(), 0

    def set(self, op, i, v):
        s = op.src[i] if i < len(op.src) else None
        if not s or not self.edit.can_set(op, i):
            self.fixed += 1
            return
        key = (s[0], s[1], s[2])
        if key in self.done:
            return
        self.done.add(key)
        self.edit.set_value(op, i, int(round(v)))


def transform(edit, refs, point=None, vector=None, offsets=None, pivot_actor=choreo.CASTER, quarter=0):
    """point(p) -> p' for positions, vector(v) -> v' for deltas (numpy 3-vectors, world directions, relative to
    the pivot actor).  offsets: {actor: its position minus the pivot actor's} (world) for positions from other
    actors (others are skipped).  quarter: the skill's quarter turns (the script values are turned by it in game).
    -> number of values that are fixed (inside shared game helpers)"""
    from .stage import turn_offset
    w = _Writer(edit)
    offsets = dict(offsets or {})
    offsets.setdefault(pivot_actor, np.zeros(3))
    q = int(quarter) % 4
    for r in refs:
        local = r.value()
        v = turn_offset(local, q)                       # what the game makes of it (world directions)
        if r.actor is None:
            if vector is None:
                continue
            nv = vector(v)
        else:
            if point is None or r.actor not in offsets:
                continue
            off = np.asarray(offsets[r.actor], float)
            nv = point(v + off) - off
        nv = turn_offset(nv, (4 - q) % 4)               # back to the script's own frame
        for k, i in enumerate(r.idx):
            if abs(nv[k] - local[k]) > 1e-6:
                w.set(r.op, i, nv[k])
    return w.fixed


def move(edit, refs, d, **kw):
    d = np.asarray(d, float)
    return transform(edit, refs, point=lambda p: p + d, **kw)


def spread(edit, refs, k, pivot=(0, 0, 0), axes=(1, 0, 1), **kw):
    """positions pushed away from (k > 1) or pulled to (k < 1) the pivot; moves (deltas) scaled the same"""
    pv = np.asarray(pivot, float)
    kv = np.where(np.asarray(axes, bool), float(k), 1.0)
    return transform(edit, refs, point=lambda p: pv + (p - pv) * kv, vector=lambda v: v * kv, **kw)


def rotate(edit, refs, degrees, pivot=(0, 0, 0), **kw):
    """turn positions (and moves) around the vertical axis through the pivot"""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    pv = np.asarray(pivot, float)

    def rot(v):
        return np.array([v[0] * c - v[2] * s, v[1], v[0] * s + v[2] * c])
    return transform(edit, refs, point=lambda p: pv + rot(p - pv), vector=rot, **kw)


def resize(edit, show_ops, k):
    """effect sizes (show commands' size value, operand 5) x k -- operand 6 is the frame step, not a size"""
    w = _Writer(edit)
    for op in show_ops:
        if len(op.args) > 5 and op.args[5]:
            w.set(op, 5, max(1, op.args[5] * k))
    return w.fixed


# ================================================================================================= paths
def _ease(name, t):
    t = np.clip(t, 0.0, 1.0)
    if name == "accelerate":
        return t * t
    if name == "decelerate":
        return 1 - (1 - t) ** 2
    if name == "smooth":
        return t * t * (3 - 2 * t)
    return t


def _frame_basis(S, E):
    D = E - S
    L = float(np.linalg.norm(D))
    f = D / L if L > 1e-6 else np.array([1.0, 0.0, 0.0])
    up = np.array([0.0, 1.0, 0.0])
    side = np.cross(up, f)
    n = np.linalg.norm(side)
    side = side / n if n > 1e-6 else np.array([0.0, 0.0, 1.0])
    return D, L, f, up, side


def _bezier(P, t):
    P0, P1, P2, P3 = P
    u = 1 - t
    return (u ** 3)[:, None] * P0 + (3 * u * u * t)[:, None] * P1 + (3 * u * t * t)[:, None] * P2 + (t ** 3)[:, None] * P3


def _fan(k, n, alternate=True):
    """where projectile k of n goes sideways, -1 .. 1: alternating left / right, wider and wider (or in order)"""
    if n <= 1:
        return 1.0
    if not alternate:
        return -1.0 + 2.0 * k / (n - 1)
    half = max(1, (n + 1) // 2)
    return (1.0 if k % 2 == 0 else -1.0) * (0.35 + 0.65 * (k // 2) / max(1, half - 1))


PRESETS = {
    # key: (label, help, parameters [(name, label, default, lo, hi, step)])
    "homing": ("Homing missile",
               "Shoots out to the sides, then curves in on the target like a homing rocket (accelerating).",
               [("width", "Fan width", 160, 0, 800, 10), ("height", "Rise", 90, -200, 600, 10),
                ("back", "Pull back", 30, -200, 300, 10), ("curve", "Curve", 0.55, 0.05, 0.95, 0.05),
                ("alternate", "Alternate sides (1/0)", 1, 0, 1, 1), ("segments", "Smoothness", 10, 3, 30, 1)]),
    "straight": ("Straight shot", "A straight line into the target.",
                 [("segments", "Smoothness", 2, 1, 30, 1)]),
    "arc": ("Arc / lob", "A thrown arc that lands on the target.",
            [("height", "Arc height", 120, -300, 800, 10), ("segments", "Smoothness", 10, 3, 30, 1)]),
    "spiral": ("Spiral in", "Corkscrews around the line to the target, closing in.",
               [("radius", "Radius", 60, 0, 400, 5), ("turns", "Turns", 2.0, 0.25, 8, 0.25),
                ("segments", "Smoothness", 18, 6, 40, 1)]),
    "orbit": ("Orbit the caster", "Circles around the caster (no target): radius, height, turns.",
              [("radius", "Radius", 90, 10, 600, 5), ("height", "Height", 60, -100, 400, 5),
               ("turns", "Turns", 1.0, 0.25, 8, 0.25), ("segments", "Points per turn", 16, 6, 48, 1)]),
    "burst": ("Burst outward", "Flies out from where it is, every effect in its own direction.",
              [("distance", "Distance", 180, 10, 800, 10), ("rise", "Upward", 0.4, -1, 1, 0.1),
               ("segments", "Smoothness", 6, 1, 20, 1)]),
}
EASES = [("accelerate", "Speeds up"), ("smooth", "Smooth"), ("linear", "Even"), ("decelerate", "Slows down")]
DEFAULT_EASE = {"homing": "linear", "straight": "accelerate", "arc": "linear", "spiral": "linear", "orbit": "linear",
                "burst": "decelerate"}


def path_points(preset, S, E, k, n, p, ease="accelerate"):
    """[(t 0..1, point)] after the start, in the pivot actor's frame (the last point = E for target presets)"""
    S, E = np.asarray(S, float), np.asarray(E, float)
    m = max(1, int(round(p.get("segments", 8))))
    if preset == "orbit":
        segs = max(2, int(round(m * p["turns"])))
        ts = np.arange(1, segs + 1) / segs
    else:
        ts = np.arange(1, m + 1) / m
    te = _ease(ease, ts)
    D, L, f, up, side = _frame_basis(S, E)
    if preset == "straight":
        pts = S + np.outer(te, D)
    elif preset == "arc":
        pts = S + np.outer(te, D) + np.outer(4 * te * (1 - te), up * p["height"])
    elif preset == "homing":
        fan = _fan(k, n, p.get("alternate", 1) >= 0.5)
        c1 = S - f * p["back"] + side * (p["width"] * fan) + up * p["height"]
        c2 = S + D * p["curve"] + side * (p["width"] * fan * 0.6) + up * (p["height"] * 0.6)
        pts = _bezier((S, c1, c2, E), te)
    elif preset == "spiral":
        th = 2 * math.pi * (p["turns"] * te + k / max(1, n))
        r = p["radius"] * (1 - te)
        pts = S + np.outer(te, D) + np.outer(r * np.cos(th), side) + np.outer(r * np.sin(th), up)
    elif preset == "orbit":
        a0 = math.atan2(S[2], S[0]) if np.hypot(S[0], S[2]) > 1 else 2 * math.pi * k / max(1, n)
        a = a0 + 2 * math.pi * p["turns"] * te
        pts = np.c_[p["radius"] * np.cos(a), np.full(len(a), p["height"]), p["radius"] * np.sin(a)]
    elif preset == "burst":
        a = 2 * math.pi * (k + 0.5) / max(1, n)
        d = np.array([math.cos(a), p["rise"], math.sin(a)])
        d /= np.linalg.norm(d)
        pts = S + np.outer(te, d * p["distance"])
    else:
        raise ValueError(f"unknown path preset {preset}")
    return list(zip(ts.tolist(), [np.asarray(q) for q in pts]))


def targets_target(preset):
    return preset in ("homing", "straight", "arc", "spiral")


def _frames(ts, total):
    """frame lengths of the segments ending at times ts (0..1) -- integers >= 1 adding up to total"""
    ends = [max(1, int(round(t * total))) for t in ts]
    out, prev = [], 0
    for e in ends:
        e = max(e, prev + 1)
        out.append(e - prev)
        prev = e
    return out


def path_lines(slot, preset, start, S, E, k, n, frames, p, ease="accelerate", pivot_actor=choreo.CASTER,
               target_actor=choreo.TARGET, target_offset=(0, 45, 0)):
    """the script lines of one effect's path (a layer event body): wait until `start`, then cmd_4140 segments in
    the pivot actor's frame; target presets end with a cmd_4170 flight into target_actor + target_offset.
    S = where the effect is at `start`, E = the target point, both in the pivot actor's frame."""
    pts = path_points(preset, S, E, k, n, p, ease)
    seg = _frames([t for t, _ in pts], max(1, int(frames)))
    lines = []
    if start > 0:
        lines.append(script.Ins(choreo.WAIT, [int(start)]))
    last = len(pts) - 1
    for j, ((t, q), f) in enumerate(zip(pts, seg)):
        if j == last and targets_target(preset):
            ox, oy, oz = (int(round(v)) for v in target_offset)
            lines.append(choreo.ins("cmd_4170", slot, int(target_actor), ox, oy, oz, f, 0, 0, 1))
        else:
            x, y, z = (int(round(v)) for v in q)
            lines.append(choreo.ins("cmd_4140", slot, int(pivot_actor), x, y, z, f, 0))
        lines.append(script.Ins(choreo.WAIT, [f]))
    return lines


FACING_DIRS = {0: (0.0, 1.0), 1: (1.0, 0.0), 2: (0.0, -1.0), 3: (-1.0, 0.0)}   # $60201 -> caster->target (x, z)


def turn_to_facing(v, facing_from, facing_to):
    """a caster-frame offset seen for one facing, turned to what it is for another ($60201 values)"""
    a = FACING_DIRS[facing_from]
    b = FACING_DIRS[facing_to]
    t = math.atan2(b[1], b[0]) - math.atan2(a[1], a[0])
    c, s = math.cos(t), math.sin(t)
    v = np.asarray(v, float)
    return np.array([v[0] * c - v[2] * s, v[1], v[0] * s + v[2] * c])


def path_event_body(slot, preset, per_facing, k, n, frames, p, ease="accelerate", pivot_actor=choreo.CASTER,
                    target_actor=choreo.TARGET, target_offset=(0, 45, 0)):
    """script text of a path, one branch per facing ($60201): per_facing = {facing: (S, E)} in the pivot actor's
    frame (skill scripts place things in world directions, so a curve to the side differs per facing)"""
    out = []
    facings = sorted(per_facing)
    for j, f in enumerate(facings):
        S, E = per_facing[f]
        pts = path_points(preset, S, E, k, n, p, ease)
        seg = _frames([t for t, _ in pts], max(1, int(frames)))
        out.append(f"    if ($60201 == {int(f)}) else F{j}")
        last = len(pts) - 1
        for i, ((t, q), fr) in enumerate(zip(pts, seg)):
            if i == last and targets_target(preset):
                ox, oy, oz = (int(round(v)) for v in target_offset)
                out.append(f"      cmd_4170 {slot}, {int(target_actor)}, {ox}, {oy}, {oz}, {fr}, 0, 0, 1")
            else:
                x, y, z = (int(round(v)) for v in q)
                out.append(f"      cmd_4140 {slot}, {int(pivot_actor)}, {x}, {y}, {z}, {fr}, 0")
            out.append(f"      wait {fr}")
        out.append("    endif")
        out.append(f"  F{j}:")
    return "\n".join(out) + "\n"


def flight_of(clip_ops):
    """the op an effect flies to its target with (cmd_4170, or a cmd_4140 to the target), or None"""
    best = None
    for op in clip_ops:
        if op.cid == 0x4170 or op.cid == 0x4140 and choreo.actor_id(op.args[1]) == choreo.TARGET:
            best = op
    return best


def movement_in(clip_ops, f0, f1):
    """the effect's own movement commands in frames [f0, f1)"""
    return [op for op in clip_ops if (op.cid in FLY or op.cid == DELTA) and f0 <= op.frame < f1]


# ================================================================================================= single effects
def roll(edit, tl, clips, degrees):
    """turn each effect's own picture by `degrees` (about its facing axis): the cmd_3c64 at its show changes, or one
    is added right after the show -> number of effects that couldn't change (inside shared helpers)"""
    fixed = 0
    w = _Writer(edit)
    inserts = []
    for c in clips:                    # values first (by position), then insertions (positions shift after them)
        show = c["show"]
        rot = next((o for o in c["ops"] if o.cid == 0x3c64 and o.frame == show.frame), None)
        if rot is not None and edit.can_set(rot, 4):
            w.set(rot, 4, rot.args[4] + degrees)
        else:
            a = edit.anchor(show, tl)
            if a is None or a[1] is not show.ins:
                fixed += 1
            else:
                inserts.append((a[0], a[1], int(show.args[0])))
    for eid, ins, slot in inserts:
        code = edit.ev[eid].code
        k = next((n for n, x in enumerate(code) if x is ins), None)
        if k is None:
            fixed += 1
            continue
        code.insert(k + 1, choreo.ins("cmd_3c64", slot, 0, 0, 0, int(round(degrees))))
        edit.changed.add(eid)
    return fixed + w.fixed


def at_show(clip_ops, show, cid):
    """the clip's commands `cid` on the frame it is shown (the ones that set up how it starts / is drawn)"""
    return [o for o in clip_ops if o.cid == cid and o.frame == show.frame and o is not show]


def put_at_show(edit, tl, show, existing, name, args):
    """the command `name *args` (args[0] = the slot) where an effect is shown: the existing ones get the new values,
    or a line goes in right after the show; args None takes them out -> number of values that couldn't change"""
    if args is None:
        if existing:
            edit.delete(list(existing), tl)
        return 0
    if existing:
        w = _Writer(edit)
        for op in existing:
            for i, v in enumerate(args):
                if i and i < len(op.args) and op.args[i] != v:
                    w.set(op, i, v)
        return w.fixed
    a = edit.anchor(show, tl)
    if a is None or a[1] is not show.ins:
        return 1
    code = edit.ev[a[0]].code
    k = next((n for n, x in enumerate(code) if x is a[1]), None)
    if k is None:
        return 1
    code.insert(k + 1, choreo.ins(name, *[int(round(v)) for v in args]))
    edit.changed.add(a[0])
    return 0


def duplicate_lines(clip_ops, new_slot, offset=(0, 0, 0)):
    """a copy of an effect clip in another slot: (first frame, script lines) for a layer event.  Values are taken as
    the clip ran (loops and helper arguments resolved); positions not on the target move by `offset`."""
    ops = sorted(clip_ops, key=lambda o: o.frame)             # stable: same-frame commands keep their order
    t0 = ops[0].frame
    lines, cur = [], t0
    off = [int(round(v)) for v in offset]
    for o in ops:
        if o.frame > cur:
            lines.append(script.Ins(choreo.WAIT, [o.frame - cur]))
            cur = o.frame
        args = list(o.args)
        args[0] = int(new_slot)
        if (o.cid in SHOW or o.cid in FLY) and choreo.actor_id(args[1]) != choreo.TARGET:
            for k in range(3):
                args[2 + k] = int(args[2 + k]) + off[k]
        lines.append(script.Ins(o.cid, args))
    return t0, lines


def _who(a):
    a = choreo.actor_id(a)
    return {choreo.CASTER: "the caster", choreo.TARGET: "the target"}.get(a, f"actor {a}")


def describe(op, names=None):
    """an effect command in plain words"""
    c, a = op.cid, op.args
    try:
        if c == 0x3c00:
            return f"loads {names.name(a[1]) if names else 'effect'} ({a[1]})"
        if c in SHOW:
            return f"appears on {_who(a[1])} at ({a[2]}, {a[3]}, {a[4]}), size {a[5] / 10:g} %"
        if c == 0x3c02:
            return "disappears"
        if c == 0x4140:
            return f"moves to {_who(a[1])} + ({a[2]}, {a[3]}, {a[4]}) in {a[5]} frames"
        if c == 0x4170:
            return f"flies to {_who(a[1])} + ({a[2]}, {a[3]}, {a[4]}) in {a[5]} frames"
        if c == DELTA:
            return f"moves by ({a[2]}, {a[3]}, {a[4]}) in {a[1]} frames"
        if c == 0x3c64:
            return f"turns to ({a[2]}°, {a[3]}°, {a[4]}°)" + (f" in {a[1]} frames" if a[1] else "")
        if c == 0x3c68:
            return f"spins by ({a[2]}°, {a[3]}°, {a[4]}°)" + (f" in {a[1]} frames" if a[1] else "")
        if c in (0x3c40, 0x3c42, 0x3c44):
            return f"stretches to ({a[2]} %, {a[3]} %, {a[4]} %)" + (f" in {a[1]} frames" if a[1] else "")
        if c in (0x3c80, 0x3c88):
            return (f"colour ({a[2]} %, {a[3]} %, {a[4]} %), opacity {a[5]} %" + (f" in {a[1]} frames" if a[1]
                                                                                    else ""))
        if c == 0x3ca0:
            return f"drawn {a[1] / 20:g} map units nearer the camera"
        if c == 0x3cde:
            return f"draw queue {a[1]}" + {4: " (behind the units)", 5: " (behind the units)", 6: " (with the units)",
                                            7: " (in front of the units)"}.get(int(a[1]), "")
        if c == 0x3c9a:
            return "shows again" if a[1] else "hidden"
        if c == 0x3ca5:
            return "stops facing the camera" if a[1] else "faces the camera"
        if c == 0x3cda:
            return f"glow {a[2]}" + (f" in {a[1]} frames" if a[1] else "")
    except (IndexError, TypeError):
        pass
    return choreo.describe(c) or op.name


MOVE_CMDS = (0x4140, 0x4170, DELTA)
TURN_CMDS = (0x3c64, 0x3c68)
LOOK_CMDS = (0x3c80, 0x3c88, 0x3cda, 0x3ca0, 0x3c40, 0x3c42, 0x3c44)


def move_groups(clip_ops):
    """the clip's moves for a list: runs of consecutive cmd_4140 to one actor become one 'path' entry ->
    [(first frame, last frame, [ops], text)]"""
    out = []
    run = []

    def flush():
        if not run:
            return
        if len(run) == 1:
            out.append((run[0].frame, run[0].end, list(run), describe(run[0])))
        else:
            out.append((run[0].frame, run[-1].end, list(run),
                        f"follows a path of {len(run)} steps around {_who(run[0].args[1])} "
                        f"({run[-1].end - run[0].frame} frames)"))
    for o in clip_ops:
        if o.cid not in MOVE_CMDS:
            continue
        if o.cid == 0x4140 and run and run[-1].cid == 0x4140 and choreo.actor_id(run[-1].args[1]) == \
                choreo.actor_id(o.args[1]):
            run.append(o)
            continue
        flush()
        run = [o] if o.cid == 0x4140 else []
        if o.cid != 0x4140:
            out.append((o.frame, o.end, [o], describe(o)))
    flush()
    return sorted(out, key=lambda e: e[0])
