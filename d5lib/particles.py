"""Particles (script commands 0x44xx) for the kit's skill preview.

The pictures are the 12 cells (4 x 4, 64 px) of Start/particle.txf: 0 glint, 1 smoke, 2 four-point sparkle, 3 glow,
4 wisp, 5 crystal shard, 6 cloud puff, 7 feather, 8 star, 9 streak, 10 ring, 11 cross sparkle.

What the commands do -- read from the handlers in disgaea5.exe (value scaling) and MEASURED IN GAME on test
choreographies (tools/_particle_test.py, 2026-10-08):
  cmd_4400 e, cell, spread_h, spread_v, speed, drag, gravity, size0, size1, size2, alpha0, alpha1, alpha2
           particles leave in a cone (degrees) around the emit direction; speed x 0.12 script units per frame
           (speed 100: ~12 / frame, seen); drag / 1000 = how much of its speed a particle keeps each frame (the
           distance it has gone is speed x (1 + d + d^2 + ...): drag 0 = one step, then it stays, 1000 = steady);
           gravity / 1000 map units per frame^2, positive = down (the game's y axis points down); sizes and
           alphas / 100 at the start, the middle point (the emit command's 8th value) and the end of its life;
           a particle's quad spans +- size map units (size 100 % = 20 script units wide)
  cmd_4410 e, r, g, b              the emitter's colour (percent), at once (0x140185b80)
  cmd_4418 e, r, g, b, a, n        the emitter's colour + opacity, fading there over n frames (0x140185c50: the
                                   game's animated value; a probe of Macrocosm shows its particles in exactly the
                                   4418 colour right away for n = 0)
  cmd_4430 e, dist, var            a particle starts up to `dist` map units out along its direction (random
                                   0..1 of it); var / 100: its speed is speed x (1 - random x var)
  cmd_4420 e, mode                 the blend mode (emitter +0x54; default 2 = adding light, 1 normal, 3 screen -
                                   colour ... as cmd_3cd6; probe: smoke without 4420 is drawn adding light)
  cmd_4450 e, value                depth bias: value / 20 map units toward the camera, like cmd_3ca0 for effects
                                   (emitter +0x50 -> the particle record's bias, 0x1403deac0)
  cmd_4428 e, k                    time scale k / 1000 (default 1): from then on the emitter's particles age k / 1000
                                   frames per frame, those already flying too (0: they freeze)
  cmd_4439 e, mode, speed, factor  speed (as cmd_4400's) and factor / 1000; mode 1: the distance is speed x age +
                                   (factor x 10 + 1) x age^2 / 2 (accelerating) instead of the series above
  cmd_4438 e, on                   particles start anywhere in a ball of cmd_4430's distance (not along their
                                   direction)
  cmd_4440 e, spin                 every particle turns at a random speed up to +- spin / 2 degrees per frame (it
                                   always starts at a random angle, spin or not)
  cmd_44c0 e                       the emitter's particles vanish at once
  cmd_44d0 e, n, sx, sy            particle size x sx / 1000 across, x sy / 1000 up, reached in n frames
                                   (cmd_44d2 e, n, sx, sy, ease, -: the same with an ease of ease / 1000)
  cmd_44d4 e, n, x, y, z           the emission's shape (and its particles' paths) stretched x / 1000 ... (default 1)
                                   (cmd_44d6 ... ease, -; x / z are along / across the facing direction)
  cmd_44d8 e, n, x, y, z           the emission turned x, y, z degrees (cmd_44da ... ease, -)
  The n-frame changes go from the value at that moment to the new one; they apply to particles already flying.
  cmd_4480 e, actor, x, y, z, rate, frames, mid      burst: about 0.45 x rate particles at once (seen), all living
                                                     `frames` frames (seen), size / opacity curve's middle at frame
                                                     `mid` (emission +0x38, the draw loop 0x1403de4f8)
  cmd_4490 e, actor, x, y, z, rate, frames, mid, up, turn   the same toward a direction (degrees: up from the
                                                     ground, turn from the facing direction; seen)
  cmd_44b5 e, actor, x, y, z, radius, count, every, life, frames, up, turn   `count` particles every `every` frames
                                                         for `frames` frames (seen)
Each particle is its own record in the sorted draw queue 6, written without depth (render state 0x01d1).
Traced 2026-10-12: the spawn (0x1403dda00: direction, start, speed, spin), the draw loop (0x1403de3a0: life
curve, distance, gravity, quad), the emission's matrix (0x1403dc790: stretch and turn from the emitter's
interpolators at +0xbc / +0xf8), the size scale (+0x80 interpolator, read as +0xa0 / +0xac in the draw loop), the
interpolators (0x140089ec0: start + (target - start) x eased progress).  The rings' (44b5) curve middle and the
emitter's drift / gravity vectors other than 4400's are not traced yet.
"""
import math
from dataclasses import dataclass, field

import numpy as np

CELL = 64
MAX_PARTICLES = 4000
SPEED_SCALE = 0.12 * 10 / 10.0               # value / 10 x 0.12 map units = value x 0.12 script units per frame
SIZE_BASE = 20.0                              # script units across a particle at size 100 % (+- size map units)
DIST_SCALE = 10.0                             # cmd_4430 distance: map units -> script units
COUNT_PER_RATE = 0.45                         # particles per unit of `rate` in a burst (seen)


@dataclass
class Emitter:
    cell: int = 3
    spread_h: float = 360.0
    spread_v: float = 360.0
    speed: float = 0.0                        # script units / frame
    drag: float = 0.0                         # share of its speed a particle keeps each frame (0: one step)
    accel_mode: int = 0                       # cmd_4439: 1 = speed x age + accel x age^2 / 2
    accel: float = 0.0                        # script units / frame^2 (cmd_4439 mode 1)
    speed_var: float = 0.0                    # cmd_4430: speed x (1 - random x speed_var)
    gravity: float = 0.0                      # script units / frame^2 (up = +)
    sizes: tuple = (1.0, 1.0, 1.0)
    alphas: tuple = (1.0, 1.0, 0.0)
    color0: tuple = (1.0, 1.0, 1.0)          # the emitter's colour (cmd_4410 / 4418)
    alpha1: float = 1.0                       # and opacity (cmd_4418)
    col_from: tuple = None                    # cmd_4418 n > 0: (r, g, b, a) it fades from, frame, frames
    col_f0: int = 0
    col_n: int = 0
    bias: float = 0.0                         # cmd_4450: map units toward the camera
    dist: float = 0.0                     # cmd_4430: particles start up to this far along their direction
    sphere: bool = False                  # cmd_4438: ... anywhere in a ball of that radius
    spin: float = 0.0                     # cmd_4440: radians / frame, the most a particle turns
    mode: int = 2
    time_scale: float = 1.0

    @property
    def blend(self):
        """the game's blend mode (1 normal, 2 adding light, 3 screen - colour, 4 multiply, 5 colour - screen)"""
        return self.mode if 1 <= self.mode <= 5 else 2

    @property
    def additive(self):
        return self.blend == 2

    def color_at(self, t):
        """(r, g, b, a) at frame(s) t"""
        c1 = np.array(tuple(self.color0) + (self.alpha1,), float)
        if self.col_from is None or self.col_n <= 0:
            return np.broadcast_to(c1, np.shape(t) + (4,))
        x = np.clip((np.asarray(t, float) - self.col_f0) / float(self.col_n), 0.0, 1.0)[..., None]
        c0 = np.array(self.col_from, float)
        return c0 + (c1 - c0) * x


@dataclass
class Particles:
    """one emission's particles, as arrays"""
    actor: int
    spawn: np.ndarray        # frame
    pos0: np.ndarray         # (n, 3) local start (x = facing direction, y = up, z = side), script units
    vel: np.ndarray          # (n, 3) direction (x the emitter's speed)
    life: np.ndarray
    em: Emitter = field(default=None)
    mid: np.ndarray = field(default=None)     # frame of the size / opacity curve's middle point
    spd: np.ndarray = field(default=None)     # speed factor of each particle (cmd_4430 var)
    ems: list = field(default=None)
    base: np.ndarray = field(default=None)    # the command's x, y, z offset from the actor (world axes)
    angle0: np.ndarray = field(default=None)  # each particle's starting angle (radians)
    turn: np.ndarray = field(default=None)    # and turning speed (radians / frame)
    emitter: int = 0
    tracks: object = None                     # the sim's Tracks (size scale, stretch, turn over time)
    clock: tuple = None                       # (frames, the emitter's own time at them): its cmd_4428 changes
    end: float = math.inf                     # frame the emitter's particles were removed (cmd_44c0)


def _dirs(rng, n, up_deg, turn_deg, spread_h, spread_v):
    """n unit vectors around a direction (elevation up_deg, azimuth turn_deg), spread in degrees"""
    el = np.radians(up_deg + rng.uniform(-0.5, 0.5, n) * min(spread_v, 360.0))
    az = np.radians(turn_deg + rng.uniform(-0.5, 0.5, n) * min(spread_h, 360.0))
    return np.c_[np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)]


class Tracks:
    """an emitter's values changed over n frames (cmd_44d0 - 44da): kind -> emitter -> [(frame, n, target, ease)]"""
    DEFAULT = {"scale": (1.0, 1.0), "stretch": (1.0, 1.0, 1.0), "turn": (0.0, 0.0, 0.0)}

    def __init__(self):
        self.segs = {k: {} for k in self.DEFAULT}

    def add(self, kind, e, frame, n, target, ease=1.0):
        self.segs[kind].setdefault(e, []).append((float(frame), max(0, int(n)), tuple(map(float, target)), ease))

    def has(self, kind, e):
        return e in self.segs[kind]

    def at(self, kind, e, t):
        """value(s) at frame(s) t -> array (len(t), components)"""
        t = np.atleast_1d(np.asarray(t, float))
        cur = np.tile(np.array(self.DEFAULT[kind], float), (len(t), 1))
        start = np.array(self.DEFAULT[kind], float)
        prev = None
        for f0, n, target, k in self.segs[kind].get(e, ()):
            if prev is not None:                                 # where the previous change had got to by now
                start = self._eval(prev, np.array([f0]))[0]
            seg = (f0, n, start, np.array(target), k)
            on = t >= f0
            if on.any():
                cur[on] = self._eval(seg, t[on])
            prev = seg
        return cur

    @staticmethod
    def _eval(seg, t):
        f0, n, start, target, k = seg
        x = np.ones(len(t)) if n <= 0 else np.clip((t - f0) / n, 0.0, 1.0)
        if k != 1.0:
            x = x ** k
        return start + (target - start) * x[:, None]


def _ease(v):
    """the interpolators' ease value (/ 1000): >= 0 -> exponent v + 1, < 0 -> 1 / (1 - v)"""
    v = v / 1000.0
    return v + 1.0 if v >= 0 else 1.0 / (1.0 - v)


class ParticleSim:
    """build from a choreo.Timeline: ParticleSim(tl.ops); .at(t) -> list of (Particles, mask, age)

    Emitter settings can change after an emission started (vanilla sets colours right after the emit command):
    a particle takes the emitter's settings as they are at the end of its spawn frame."""

    CONFIG = (0x4400, 0x4410, 0x4418, 0x4430, 0x4420, 0x4428, 0x4438, 0x4439, 0x4440, 0x4450)
    TRACKS = {0x44d0: ("scale", 2, False), 0x44d2: ("scale", 2, True), 0x44d4: ("stretch", 3, False),
              0x44d6: ("stretch", 3, True), 0x44d8: ("turn", 3, False), 0x44da: ("turn", 3, True)}

    def __init__(self, ops, length=None):
        self.emissions = []
        self.tracks = Tracks()
        hist = {}                           # emitter -> [(frame, Emitter after that frame's settings)]
        cur = {}
        pending = []
        kills = {}                          # emitter -> [(order, frame)] (cmd_44c0)
        for order, op in enumerate(o for o in ops if 0x4400 <= o.cid < 0x4500):
            c, a, f = op.cid, op.args, op.frame
            try:
                if c == 0x44c0:
                    kills.setdefault(a[0], []).append((order, f))
                    continue
                if c in self.TRACKS:
                    kind, nc, eased = self.TRACKS[c]
                    vals = [v / 1000.0 for v in a[2:2 + nc]]
                    if kind == "stretch":                   # script x / z: across / along the facing direction
                        vals = [vals[2], vals[1], vals[0]]
                    elif kind == "turn":
                        vals = [math.radians(v * 1000.0) for v in (vals[2], vals[1], vals[0])]
                    self.tracks.add(kind, a[0], f, a[1], vals, _ease(a[2 + nc]) if eased else 1.0)
                    continue
                e = cur.setdefault(a[0], Emitter())
                if c in self.CONFIG:
                    self._config(e, c, a, f)
                    h = hist.setdefault(a[0], [])
                    snap = Emitter(**e.__dict__)
                    if h and h[-1][0] == f:
                        h[-1] = (f, snap)
                    else:
                        h.append((f, snap))
                elif c in (0x4480, 0x4490, 0x44b5):
                    pending.append((c, list(a), f, order))
            except (IndexError, TypeError, ZeroDivisionError):
                continue
        # each emitter's own clock: its time scale (cmd_4428) adds up frame by frame (an emission's age += scale)
        clocks = {}
        for e_id, h in hist.items():
            steps = []
            for fr, snap in h:
                if not steps or steps[-1][1] != snap.time_scale:
                    steps.append((float(fr), snap.time_scale))
            if len(steps) > 1 or (steps and steps[0][1] != 1.0):
                xs, ys, acc = [steps[0][0]], [steps[0][0]], steps[0][0]
                for (f0, k0), (f1, _) in zip(steps, steps[1:]):
                    acc += (f1 - f0) * k0
                    xs.append(f1)
                    ys.append(acc)
                xs.append(xs[-1] + 1e6)
                ys.append(ys[-1] + 1e6 * steps[-1][1])
                clocks[e_id] = (np.array(xs), np.array(ys))
        total = 0
        for k, (c, a, f, order) in enumerate(pending):
            if total >= MAX_PARTICLES:
                break
            h = hist.get(a[0], [])

            def at(frame, h=h):
                best = Emitter()
                for fr, snap in h:
                    if fr <= frame:
                        best = snap
                return best
            try:
                p = self._emit(c, a, f, at(f), k)
            except (IndexError, TypeError, ZeroDivisionError):
                p = None
            if p is not None:
                # settings per particle: as of its spawn frame (most often the same for all of them)
                p.ems = [at(int(sf)) for sf in p.spawn]
                p.em = p.ems[0] if p.ems else at(f)
                p.emitter, p.tracks = a[0], self.tracks
                p.clock = clocks.get(a[0])
                p.end = min((kf for o, kf in kills.get(a[0], ()) if o > order), default=math.inf)
                total += len(p.spawn)
                self.emissions.append(p)

    @staticmethod
    def _config(e, c, a, f=0):
        if c == 0x4400:
            e.cell = int(a[1]) % 12
            e.spread_h, e.spread_v = float(a[2]), float(a[3])
            e.speed = a[4] * SPEED_SCALE
            e.drag = a[5] / 1000.0
            e.accel_mode = 0
            e.gravity = -a[6] / 100.0                 # positive = down: the game's y axis points down
            e.sizes = (a[7] / 100.0, a[8] / 100.0, a[9] / 100.0)
            e.alphas = (a[10] / 100.0, a[11] / 100.0, a[12] / 100.0)
        elif c == 0x4410:
            e.color0 = (a[1] / 100.0, a[2] / 100.0, a[3] / 100.0)
            e.col_from, e.col_n = None, 0
        elif c == 0x4418:
            n = int(a[5]) if len(a) > 5 else 0
            e.col_from = tuple(e.color_at(f)) if n > 0 else None
            e.color0 = (a[1] / 100.0, a[2] / 100.0, a[3] / 100.0)
            e.alpha1 = a[4] / 100.0
            e.col_f0, e.col_n = int(f), max(0, n)
        elif c == 0x4430:
            e.dist = max(0.0, float(a[1])) * DIST_SCALE
            e.speed_var = max(0.0, a[2] / 100.0)
        elif c == 0x4420:
            e.mode = int(a[1])
        elif c == 0x4428:
            e.time_scale = a[1] / 1000.0
        elif c == 0x4450:
            e.bias = float(a[1]) / 20.0
        elif c == 0x4438:
            e.sphere = bool(a[1])
        elif c == 0x4440:
            e.spin = a[1] / 360.0 * math.pi
        elif c == 0x4439:
            e.accel_mode = int(a[1])
            e.speed = a[2] * SPEED_SCALE
            f = a[3] / 1000.0
            if e.accel_mode:
                e.accel = (f * 10.0 + 1.0) * 10.0          # map units -> script units
            else:
                e.drag = f

    @staticmethod
    def _emit(c, a, f, e, seed):
        """particles in the emitter's local frame: x = the facing direction (toward the target), y = up, z = side"""
        rng = np.random.default_rng(seed * 7919 + 17)
        actor = a[1]
        base = np.array(a[2:5], float)
        if c in (0x4480, 0x4490):
            rate, frames, mid = max(0, a[5]), max(1, a[6]), max(0, a[7])
            n = int(min(400, max(1, round(rate * COUNT_PER_RATE))))
            spawn = np.full(n, float(f))                          # all at once (seen)
            life = np.full(n, float(frames))                      # all live `frames` frames (seen)
            mids = np.full(n, float(min(mid, frames)))
            up, turn = (a[8], a[9]) if c == 0x4490 else (0.0, 0.0)
            d = _dirs(rng, n, up, turn, e.spread_h, e.spread_v)
            off = np.zeros((n, 3))
        else:                                                     # 44b5 rings
            radius, count, every = max(0, a[5]), max(1, a[6]), max(1, a[7])
            frames = a[9] if a[9] > 0 else 60
            rings = max(1, int(frames // every))
            n = int(min(400, count * rings))
            k = np.arange(n)
            spawn = f + (k // count) * float(every)
            life = np.full(n, float(a[8] if a[8] > 0 else max(every * 2, 20)))
            mids = life / 2.0
            ang = 2 * np.pi * (k % count) / count + rng.uniform(0, 2 * np.pi / count, n)
            ring = np.c_[np.cos(ang), np.zeros(n), np.sin(ang)]
            off = ring * (radius / 10.0 if radius > 1000 else radius)
            d = _dirs(rng, n, a[10], a[11], e.spread_h, e.spread_v)
        # the start: random 0..1 of cmd_4430's distance out along the direction (cmd_4438: anywhere in a ball of
        # that radius); the speed: x (1 - random x var); a random angle, turning at up to +- the emitter's spin
        if e.sphere and e.dist:
            th = np.arccos(1.0 - 2.0 * rng.uniform(0.0, 1.0, n))
            ph = rng.uniform(0.0, 2.0 * np.pi, n)
            r = e.dist * np.sqrt(rng.uniform(0.0, 1.0, n))
            pos = off + np.c_[np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)] * r[:, None]
        else:
            dist = e.dist * rng.uniform(0.0, 1.0, n)
            pos = off + d * dist[:, None]
        spd = 1.0 - rng.uniform(0.0, 1.0, n) * e.speed_var if e.speed_var else np.ones(n)
        p = Particles(actor, spawn, pos, d, life, e)
        p.base = base
        p.mid = mids
        p.spd = spd
        p.angle0 = rng.uniform(0.0, 2.0 * np.pi, n)
        p.turn = e.spin * (2.0 * rng.uniform(0.0, 1.0, n) - 1.0)
        return p

    def at(self, t):
        out = []
        for p in self.emissions:
            if t >= p.end:
                continue
            age = emitter_time(p, t) - emitter_time(p, p.spawn)
            age[t < p.spawn] = -1.0
            m = (age >= 0) & (age < p.life)
            if m.any():
                out.append((p, m, age[m]))
        return out


def curve(vals, x, mid=None):
    """start / middle / end values -> value at life fraction x (array); mid: the middle point's fraction"""
    v0, v1, v2 = vals
    mid = 0.5 if mid is None else np.clip(mid, 1e-6, 1.0)
    a = np.clip(x / mid, 0.0, 1.0)
    b = np.clip((x - mid) / np.maximum(1.0 - mid, 1e-6), 0.0, 1.0)
    return np.where(x < mid, v0 + (v1 - v0) * a, v1 + (v2 - v1) * b)


def travelled(age, d):
    """distance (in speeds) a particle has gone after `age` frames keeping share d of its speed each frame -- as the
    game's draw loop adds it up: whole steps speed x d^i, then the fraction of the next one"""
    age = np.asarray(age, float)
    steps = np.where(age > 0, np.maximum(1, np.ceil(age)), 0)
    if abs(d - 1.0) < 1e-9:
        whole = steps
    else:
        whole = (1.0 - d ** steps) / (1.0 - d)
    frac = age - np.floor(age)
    return whole + frac * d ** steps


def emitter_time(p, t):
    """the emitter's own time at frame(s) t (its time scale changes added up; plain frames before the first)"""
    if getattr(p, "clock", None) is None:
        return np.asarray(t, float) * (p.em.time_scale if p.em is not None else 1.0)
    xs, ys = p.clock
    t = np.asarray(t, float)
    return np.where(t < xs[0], t, np.interp(t, xs, ys))


def frame_of(p, m, age):
    """frames (real ones) of the live particles at their ages"""
    sp = p.spawn[m]
    if getattr(p, "clock", None) is None:
        return sp + age / (p.em.time_scale or 1.0)
    xs, ys = p.clock
    own = emitter_time(p, sp) + age
    with np.errstate(all="ignore"):
        back = np.interp(own, ys, xs)              # the clock never runs backwards: invert it where it moves
    return np.where(np.isfinite(back), back, sp)


def _turn_matrix(r):
    """(n, 3) angles (radians, about x, y, z) -> (n, 3, 3) rotations (x, then y, then z)"""
    cx, cy, cz = np.cos(r).T
    sx, sy, sz = np.sin(r).T
    o, z = np.ones(len(r)), np.zeros(len(r))
    rx = np.stack([np.stack([o, z, z], -1), np.stack([z, cx, -sx], -1), np.stack([z, sx, cx], -1)], 1)
    ry = np.stack([np.stack([cy, z, sy], -1), np.stack([z, o, z], -1), np.stack([-sy, z, cy], -1)], 1)
    rz = np.stack([np.stack([cz, -sz, z], -1), np.stack([sz, cz, z], -1), np.stack([z, z, o], -1)], 1)
    return rz @ ry @ rx


def state(p, m, age, now=None):
    """local positions (x facing, y up, z side; add p.base), sizes (script units), rgba of the live particles"""
    pos, half, ang, rgba = quads(p, m, age, now)
    return pos, half.mean(1) * 2.0, rgba


def quads(p, m, age, now=None):
    """local positions, half sizes (n, 2: across, up; script units), angles (radians), rgba of the live particles"""
    e = p.em
    ems = [p.ems[i] for i in np.nonzero(m)[0]] if getattr(p, "ems", None) else [e]
    if any(x is not ems[0] for x in ems):
        e = ems[-1]                       # settings changed during the emission: the newest live ones
    else:
        e = ems[0]
    spd = p.spd[m] if getattr(p, "spd", None) is not None else 1.0
    v = p.vel[m] * (e.speed * spd if np.ndim(spd) == 0 else e.speed * spd[:, None])
    if e.accel_mode:
        disp = v * age[:, None] + p.vel[m] * (0.5 * e.accel * age ** 2)[:, None]
    else:
        disp = v * travelled(age, e.drag)[:, None]
    pos = p.pos0[m] + disp
    t = frame_of(p, m, age) if now is None else np.full(len(age), float(now))
    tr = getattr(p, "tracks", None)
    if tr is not None and tr.has("stretch", p.emitter):        # the emission's matrix: stretch, then turn
        pos = pos * tr.at("stretch", p.emitter, t)
    if tr is not None and tr.has("turn", p.emitter):
        pos = np.einsum("nij,nj->ni", _turn_matrix(tr.at("turn", p.emitter, t)), pos)
    pos[:, 1] += 0.5 * e.gravity * age ** 2
    life = p.life[m]
    x = age / life
    mid = (p.mid[m] / life) if getattr(p, "mid", None) is not None else None
    size = curve(e.sizes, x, mid) * (SIZE_BASE / 2.0)
    half = np.c_[size, size]
    if tr is not None and tr.has("scale", p.emitter):
        half = half * tr.at("scale", p.emitter, t)
    ang = (p.angle0[m] + p.turn[m] * age) if getattr(p, "angle0", None) is not None else np.zeros(len(age))
    alpha = curve(e.alphas, x, mid)
    c = e.color_at(t)
    return pos, half, ang, np.c_[c[:, :3], alpha * c[:, 3]]
