"""The battle stage while a skill runs, frame by frame, the way disgaea5.exe updates it -- for the skill editor's
preview (no game needed).  choreo.Simulator runs the script events and records every command with its frame;
StageSim replays those commands into a stage (camera, screen colours, units, effect slots) and steps every animated
value one frame at a time with the game's own rules (read from the command handlers, docs/SKILL_EDITOR.md
"How the preview matches the game"):

  * animated values ("animators"): start, target, frames, counter; linear, or eased: the step of frame k is
    p^k times the first one (geometric), p = 1 + ease / 1000 (every eased command; the camera's 0x140166da0:
    ease / 10 / 100 + 1).  A value set with 0 frames jumps at once.
  * order inside a frame: the scripts run (commands), then everything (the camera too) updates one frame, then it
    is drawn.  Checked on Macrocosm's recorded pictures: the instant zoom at 86 and the white fade-out starting at 86
    show first in the same picture.  (The recording's camera log is read at the start of each game frame, before
    that frame's update, so it runs one frame behind its pictures.)
  * camera: target point (3210 linear / 3220 eased), distance in map units (3230 / 3240), pitch / yaw / roll
    (3260 turn by, 3268 turn to, 3280 eased turn by, 3290 back to the battle view), lens (3250 / 3258).
    The game camera is a perspective camera looking at the target from `distance` map units away; its vertical
    field of view is 27008 / lens degrees (the battle's 5120: 5.3 degrees, narrow; Macrocosm's planet 700: 38.6).
  * screen: fade (2810: -128 white .. 0 .. 128 black), backdrop gradient behind everything (2830 4 corners,
    2832 two colours, 2834 one colour, 2835 back to the map's), map colour / opacity (2820).
  * effects: model, place (actor + offset, or following the actor), size, scale (3c40 / 3c42), each node's own
    scale (3cb8 / 3cba), rotation (3c64 to, 3c68 by, 3c6a eased by), second rotation (3c70 to, 3c74 by),
    rotation order (3c78), colour (3c80 / 3c88), opacity (3cda / 3cdc), texture layer (3c30), blend override
    (3cd6), billboard (3cd8), frame step (show / 3c90), frame (3cc6), play count; moving (4140 / 4170).
  * units: position + moves (6642 straight, 6672 eased, 6680 jump), sprite offset (65b8 / 65bc / 65c1),
    scale (65a0 / 65a1), turn (65b4 / 65b5), tint (6480), motions / animations, extra units: a sprite (6402),
    a copy of another unit (6c04 / 6410).
Coordinates: script units (a map unit = 10, a panel = 120), y up, the caster's panel at the origin.
"""
import copy
import math
from dataclasses import dataclass, field

import numpy as np

from . import choreo

PANEL = 120.0
MAP = 10.0                          # script units per map unit
DEFAULT_DIST = 700.0                # map units
DEFAULT_PITCH = 30.0                # degrees
DEFAULT_YAW = -45.0                 # degrees: the battle camera's first view
# cmd_3250 / 3258 set the camera's lens: the vertical field of view is LENS_FOV / value degrees (every recording's
# camera block: value 5120 -> projection [1][1] 21.7082 = 5.275 degrees, 1500 -> 18.005, 750 -> 36.01, 700 -> 38.58).
# Macrocosm's planet scenes use 700-1500: a wide view.  The projection has no far plane (near 1, depth 1 - 1/z).
LENS_DEFAULT = 5120.0
LENS_FOV = 27008.0
FAR_PLANE = 65536.0                 # map units: the kit's GL depth range (the game's is unlimited)


def lens_p11(lens):
    """projection [1][1] (cot of half the vertical field of view) of a cmd_3250 lens value"""
    fov = math.radians(LENS_FOV / max(1.0, float(lens)))
    return 1.0 / math.tan(min(fov, math.radians(170.0)) / 2.0)


P11 = lens_p11(LENS_DEFAULT)        # 21.708: the battle camera's projection [1][1]
FACING_DIRS = {0: (0.0, 1.0), 1: (1.0, 0.0), 2: (0.0, -1.0), 3: (-1.0, 0.0)}   # $60201 -> caster->target (x, z)
CASTER, TARGET = choreo.CASTER, choreo.TARGET
ALL_UNITS = 10000
SNAP_EVERY = 24                      # frames between kept states (seeking backwards)
HOME_FOLLOWS_MOVES = True            # an actor's home = where its last move ended (kept for the scene's homes)
PLAIN_IS_BASE = True                 # a plain actor id = its base place (see Stage.where)


def progress(i, n, p=None):
    """how far an animator with n frames got after i (0..1); p = ease factor (None / 1 = straight)"""
    if n <= 0 or i >= n:
        return 1.0
    if p is None or abs(p - 1.0) < 1e-6:
        return i / float(n)
    try:
        return (1.0 - p ** i) / (1.0 - p ** n)
    except (OverflowError, ZeroDivisionError):
        return i / float(n)


def turn_offset(v, q):
    """a script offset (x, y, z) in the caster's frame -> world: the game turns it by q quarter turns
    (0x140088630; q = the skill's direction / 90)"""
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    q %= 4
    if q == 1:
        x, z = -z, x
    elif q == 2:
        x, z = -x, -z
    elif q == 3:
        x, z = z, -x
    return np.array([x, y, z])


def ang_dir(deg):
    """the game's facing angle (degrees: the skill's direction is its quarter turns x 90) -> (x, z) direction"""
    r = math.radians(deg)
    return np.array([-math.sin(r), math.cos(r)])


def dir_ang(d):
    return math.degrees(math.atan2(-float(d[0]), float(d[1]))) % 360.0


def facing_quarter(facing):
    """$60201 -> the quarter turns the game gives the skill's offsets (seen: the camera target of Macrocosm)"""
    return (4 - int(facing)) % 4


def ease_factor(ease, flag, div=1000.0):
    """p of an eased command: only when its last value (flag) > 0 -- the game's 0x140071a40"""
    if flag is None or flag <= 0:
        return None
    return 1.0 + ease / div


class Lerp:
    """an animated value (vector): the game's animator"""
    __slots__ = ("a", "b", "n", "i", "p")

    def __init__(self, v):
        v = np.array(v, float)
        self.a, self.b, self.n, self.i, self.p = v, v, 0, 0, None

    def get(self):
        if self.i >= self.n:
            return self.b
        return self.a + (self.b - self.a) * progress(self.i, self.n, self.p)

    def to(self, target, frames=0, p=None):
        cur = self.get()
        self.b = np.array(target, float)
        self.n = max(0, int(frames))
        self.i = 0
        self.p = p
        self.a = cur if self.n else self.b

    def by(self, delta, frames=0, p=None):
        self.to(self.b + np.array(delta, float), frames, p)

    def tick(self):
        if self.i < self.n:
            self.i += 1

    @property
    def moving(self):
        return self.i < self.n

    def __deepcopy__(self, memo):
        c = Lerp.__new__(Lerp)
        c.a, c.b, c.n, c.i, c.p = self.a, self.b, self.n, self.i, self.p
        return c


# ------------------------------------------------------------------------------------------------ unit moves
# What the game does with cmd_6642 / 6672 / 6680 (2026-10-10, disgaea5.exe): each sets up a move of the actor
# (kind at actor+0xd4) that the actor update 0x1402e5c00 runs every frame with t = 1 - frames left / frames:
#   0  velocity: a step per frame, growing / shrinking by p every `every` frames (0x1402e4fb0; cmd_6642 mode 0 is
#      the plain straight move 0x1402e66a0)
#   1  straight          2  eased steps on every axis (0x140136f50 / 0x140136e70)
#   4  straight sideways, height on the apex curve in plain time
#   5  sideways and height both on the apex curve, time reshaped around the apex by p
#   6  sideways eased steps, height on the apex curve in plain time
#   7  straight sideways, height on the apex curve with the time reshaped (0x140136910)
#   8  sideways eased steps, height on the apex curve with the time reshaped (cmd_6680, the jump)
# The apex curve (0x140136c80) is y = v u + a u^2 / 2 from the start height: highest at the apex height, ending at
# the landing height.  Every arc lands exactly on its landing point at the end; that point is the move's
# destination (the actor's 'where it got to', 1xxxx).
EPS = 1e-4


def unit_ease(e):
    """an ease value of cmd_6672 / 6680 -> its factor (0x140170920 / 0x140171940): v = e / 1000; 1 + v, or
    1 / (1 - v) when negative"""
    v = float(e) / 1000.0
    return 1.0 + v if v > 0 else 1.0 / (1.0 - v)


class EaseSteps:
    """0x140136f50 / 0x140136e70: progress 0..1 whose steps change by p every `every` frames"""
    __slots__ = ("norm", "p", "step")

    def __init__(self, p, frames, every):
        if abs(p) <= EPS or abs(every) <= EPS or abs(p - 1.0) <= EPS or frames <= 0:
            self.norm, self.p, self.step = 1.0, 1.0, 1.0
            return
        self.p = float(p)
        k = int((int(frames) - 1) / int(every)) + 1
        pk = p * p if k == 2 else p ** k
        self.step = every / float(frames)
        self.norm = (1.0 - pk) / (1.0 - p) - (k - frames / float(every)) * (pk / p)

    def at(self, t):
        if t >= 1.0:
            return 1.0
        if self.p == 1.0:
            return t
        x = t / self.step
        k = int(x) + 1
        pk = self.p * self.p if k == 2 else self.p ** k
        return ((1.0 - pk) / (1.0 - self.p) - (pk / self.p) * (k - x)) / self.norm


def apex_curve(h, e):
    """0x140136c80: (v, a) of y(u) = v u + a u^2 / 2 peaking at h and ending at e (both from the start height)"""
    if abs(h) <= EPS:
        return 0.0, 2.0 * e
    if abs(e) <= EPS:
        a = -8.0 * h
        return a * -0.5, a
    d = (h - e) * h
    if abs(d) == EPS:
        r = h / e
        v = 2.0 * h / r
        return v, -(v / r)
    if d < 0:
        return h * 4.0 - e, (e - 2.0 * h) * 4.0
    q = math.sqrt(d)
    r = (q + h) / e
    if r <= 0 or r > 1:
        r = (h - q) / e
    v = 2.0 * h / r
    return v, -(v / r)


def apex_time(v, a):
    return min(1.0, max(0.0, 0.5 if abs(a) <= EPS else -v / a))


def shaped(t, r, p):
    """0x140136910: the time reshaped by p before and after the apex (r)"""
    if r >= t:
        return 0.0 if abs(r) <= EPS else r * (t / r) ** p
    return (1.0 - ((1.0 - t) / (1.0 - r)) ** p) * (1.0 - r) + r


class UnitMove:
    """one move of an actor, as the game's update runs it"""

    def __init__(self, kind, src, dst, frames):
        self.kind, self.src, self.dst = kind, np.array(src, float), np.array(dst, float)
        self.n, self.left = int(frames), int(frames)
        self.ease = None                  # EaseSteps (kinds 2, 6, 8)
        self.curve = (0.0, 0.0)           # (v, a) of the apex curve
        self.p = 1.0                      # time reshaping (kinds 5, 7, 8)
        self.vel = np.zeros(3)            # kind 0
        self.mul, self.mul_p, self.mul_mode, self.every, self.counting = 1.0, 1.0, 0, 0, 0

    @classmethod
    def velocity(cls, src, dst, frames, v=None, every=1):
        """kind 0: cmd_6642 mode 0 (v None: plain, 0x1402e66a0) / cmd_6672 mode 0 (0x1402e4fb0)"""
        m = cls(0, src, dst, frames)
        delta = m.dst - m.src
        if v is None:
            m.vel = delta / float(frames)
            return m
        m.counting = int(frames)
        if not every:
            m.vel = delta
            return m
        p = 1.0 + v if v >= 0 else 1.0 - v
        m.mul_mode = 2 if v < 0 else 1
        m.mul_p, m.every = p, int(every)
        terms = int(frames) + (1 if m.mul_mode == 1 else 0)
        total, f = 0.0, 1.0
        for r in range(terms):
            if r % m.every == 0 and r:
                f *= p
            total += f
        m.mul = p if m.mul_mode == 1 else f
        m.vel = delta / total
        return m

    def tick(self, pos):
        """-> (new position, finished)"""
        if self.kind == 0:
            new = pos.copy()
            for k in range(3):
                if pos[k] == self.dst[k]:
                    continue
                step = self.vel[k] * (self.mul if self.counting > 0 else 1.0)
                new[k] = pos[k] + step
                if (new[k] - self.dst[k]) * (pos[k] - self.dst[k]) < 0:
                    new[k] = self.dst[k]
            self.left -= 1
            if self.left <= 0:
                self.left, self.vel = 0, np.zeros(3)
            if self.counting > 0:
                done = self.counting - self.left
                if self.every > 0 and done % self.every == 0:
                    self.mul = self.mul * self.mul_p if self.mul_mode == 1 else (
                        self.mul / self.mul_p if self.mul_mode == 2 else self.mul)
                if self.left <= 0:
                    self.counting = 0
            return new, self.left <= 0
        self.left -= 1
        t = 1.0 - self.left / float(self.n)
        d = self.dst - self.src
        if t >= 1.0:
            return self.dst.copy(), True
        v, a = self.curve
        k = self.kind
        if k == 1:
            s = min(1.0, t)
            return self.src + d * s, False
        if k == 2:
            return self.src + d * self.ease.at(t), False
        if k == 4:
            return self.src + np.array([d[0] * t, v * t + a * t * t * 0.5, d[2] * t]), False
        if k == 5:
            u = shaped(t, apex_time(v, a), self.p)
            if u >= 1.0:
                return self.dst.copy(), False
            return self.src + np.array([d[0] * u, v * u + a * u * u * 0.5, d[2] * u]), False
        if k == 6:
            s = self.ease.at(t)
            return self.src + np.array([d[0] * s, v * t + a * t * t * 0.5, d[2] * s]), False
        if k == 7:
            u = shaped(t, apex_time(v, a), self.p)
            return self.src + np.array([d[0] * t, v * u + a * u * u * 0.5, d[2] * t]), False
        if k == 8:
            s = self.ease.at(t)
            u = shaped(t, apex_time(v, a), self.p)
            return self.src + np.array([d[0] * s, v * u + a * u * u * 0.5, d[2] * s]), False
        return self.src + d * t, False


# ------------------------------------------------------------------------------------------------ setup
@dataclass
class Setup:
    """who and where: what the preview assumes about the battle"""
    caster_sprite: int = None
    caster_palette: int = 0
    target_sprite: int = None
    target_palette: int = 0
    weapon: int = None                  # weapon type drawn in the caster's hands
    facing: int = 0                     # $60201
    distance: float = 1.0               # panels between caster and target
    caster_y: float = 0.0               # ground height under each (script units)
    target_y: float = 0.0
    view_yaw: float = DEFAULT_YAW       # the battle camera's turn (the player turns it in 90 degree steps)
    event_sheets: dict = field(default_factory=dict)    # vanilla event-pose sprite -> the caster's own (outfits)
    class_sprites: dict = field(default_factory=dict)   # cmd_6402 class -> sprite (char.dat; default: the same)
    targets: list = None                # area targets' places in the game's order (None: one at target_pos())
    area: list = None                   # the skill's panels: [(x, y, z, kind)] panel centres on the ground
    reach: list = None                  # panels the cursor can go to: [(x, y, z)]
    cursor: tuple = None                # the cursor's panel (x, y, z) (skills with a range)
    heights: dict = None                # {(panel dx, panel dz): ground height} around the caster's panel (the map)

    def __deepcopy__(self, memo):
        return self                     # the simulation never changes it: snapshots share it

    def ground(self, x, z):
        """the map's ground height at a place (0x1401ceba0; script units, from the caster's panel)"""
        if not self.heights:
            return 0.0
        return float(self.heights.get((int(round(x / PANEL)), int(round(z / PANEL))), 0.0))

    def caster_pos(self):
        return np.array([0.0, self.caster_y, 0.0])

    def target_pos(self):
        if self.targets:
            return np.array(self.targets[0], float)
        dx, dz = FACING_DIRS.get(int(self.facing) % 4, (0.0, 1.0))
        d = PANEL * self.distance
        return np.array([dx * d, self.target_y, dz * d])

    def target_places(self):
        return [np.array(t, float) for t in self.targets] if self.targets else [self.target_pos()]

    def local_to_world(self, x, y, height=0.0):
        """a panel offset in the skill's own frame (x sideways, y forward) -> world place (script units)"""
        p = turn_offset((x * PANEL, 0.0, y * PANEL), facing_quarter(self.facing))
        return np.array([p[0], height, p[2]])


# ------------------------------------------------------------------------------------------------ state
class Camera:
    __slots__ = ("target", "dist", "rot", "lens", "shake", "shake_hv")

    def __init__(self, target, yaw_deg):
        self.target = Lerp(target)
        self.dist = Lerp([DEFAULT_DIST])
        self.rot = Lerp([math.radians(DEFAULT_PITCH), math.radians(yaw_deg), 0.0])
        self.lens = Lerp([LENS_DEFAULT])
        self.shake = None                # cmd_32a0: [frames left, sideways, up-down] (map units)
        self.shake_hv = (0.0, 0.0)       # this frame's shake (sideways along the view's right, down)

    def lerps(self):
        return (self.target, self.dist, self.rot, self.lens)

    def tick_shake(self):
        """the game's camera update (0x14043dc4b): count down; the offset is the amount times -1 or 3 (bit 1 of
        the count left), sideways along the view's right and vertical; nothing once the count runs out"""
        sh = self.shake
        if sh is None:
            self.shake_hv = (0.0, 0.0)
            return
        sh[0] -= 1
        if sh[0] <= 0:
            self.shake, self.shake_hv = None, (0.0, 0.0)
            return
        k = 3.0 if sh[0] & 2 else -1.0
        self.shake_hv = (sh[1] * k, sh[2] * k)


class Actor:
    def __init__(self, pos, sprite=None, palette=0, direction=(0.0, 1.0)):
        self.sprite = sprite             # sprite number (None: invisible helper / not set)
        self.palette = palette
        self.copy = None                 # actor id whose look this one copies
        self.follow = None               # actor id it moves with (cmd_6c04 / 6c00)
        self.follow_off = np.zeros(3)    # where it sits from that actor (the game's local position, child +0x128)
        self.anim = None                 # cmd_6500 animation id (minus: mirrored)
        self.motion = 0                  # cmd_6510 motion
        self.motion_start = 0
        self.mtime = 0.0                 # the motion's time (frames) as drawn: + speed / 100 every frame
        self.speed = 100.0               # cmd_6570 (percent); cmd_6560 0 / 1 sets 0 / 100
        self.shadow = True               # cmd_6470 actor, 0 takes its shadow away (any other mode: a shadow)
        self.pos = np.array(pos, float)  # where it stands (moves change it)
        self.home = np.array(pos, float)
        self.base = np.array(pos, float) # where a plain reference to it points (the game's actor +0x14; 6620 sets it)
        self.start = np.array(pos, float)
        self.move = None                 # UnitMove
        self.offset = Lerp([0.0, 0.0, 0.0])
        self.scale = Lerp([1.0, 1.0, 1.0])
        self.rot = Lerp([0.0, 0.0, 0.0])           # degrees
        self.tint = Lerp([1.0, 1.0, 1.0, 1.0])
        self.dir = np.array(direction, float)      # facing (x, z)
        self.exists = True
        self.screen = False              # cmd_6460 1: drawn on the screen (cut-in portraits), not in the world
        self.spos = Lerp([0.0, 0.0])     # its place on screen: 1080p pixels from the centre (6660 / 6664)
        self.fade = Lerp([1.0])          # cmd_6482: its opacity
        self.angle = 0.0                 # the sprite's turn (degrees, clockwise in its own pixels; sprite obj +0x44)
        self.turn = None                 # (from, to, frames, i, EaseSteps or None): cmd_65b4 / 65b5 / 65b8 / 65c1
        self.pivot = (0.0, 0.0)          # what it turns around: obj +0x40 / +0x42 (x 0.0625 = sprite pixels, y down)
        self.pix = Lerp([0.0, 0.0])      # cmd_65bc: the sprite drawn shifted (sprite pixels, y down)
        self.dturn = None                # (from, to, frames, i): cmd_6710 turning the unit (degrees, actor +0x2c0..)

    def lerps(self):
        return (self.offset, self.scale, self.rot, self.tint, self.spos, self.fade, self.pix)

    def place(self, stage=None, depth=0):
        """where it is drawn: its position along its move (or the actor it follows) + the sprite offset"""
        if self.follow is not None and stage is not None and depth < 8:
            lead = stage.actors.get(self.follow)
            if lead is not None and lead is not self:
                return lead.place(stage, depth + 1) + self.follow_off + self.offset.get()
        return self.pos + self.offset.get()


class Slot:
    def __init__(self):
        self.effect = None
        self.shown = False
        self.actor = CASTER
        self.attached = None             # actor followed (cmd_3c20 / 3c22)
        self.offset = np.zeros(3)        # its offset from that actor
        self.pos = Lerp([0.0, 0.0, 0.0]) # world place (moves: 4140 / 4170)
        self.size = 1.0
        self.scale = Lerp([1.0, 1.0, 1.0])
        self.nscale = Lerp([1.0, 1.0, 1.0])
        self.rot = Lerp([0.0, 0.0, 0.0])             # degrees
        self.rot2 = Lerp([0.0, 0.0, 0.0])
        self.rot_order = 0
        self.rot2_order = None
        self.color = Lerp([1.0, 1.0, 1.0, 1.0])
        self.frame = 0.0
        self.step = 1.0
        self.start = 0
        self.end = None                  # last frame of the range (None: the model's length)
        self.loop_start = 0
        self.plays = -1
        # how the game orders it (the effect renderer 0x1402fd190 -> draw queue submit 0x14030f8a0; queues drawn 0..11
        # by 0x14030c320, queue 6 sorted back to front by 0x14030b4d0)
        self.zbias = 0.0                 # cmd_3ca0 value / 20 map units toward the camera (script units here)
        self.queue = -1                  # cmd_3cde: draw queue of every part (-1: each part's own, its layer byte + 2)
        self.drawn = True                # cmd_3c9a 0 hides it (and stops its animation) until 3c9a 1
        self.face_cam = True             # cmd_3ca5 1: parts that face the camera (billboards) don't any more
        self.layer = 0                   # cmd_3c30: texture layer of 2-layer pictures
        self.blend = -1                  # cmd_3cd6: blending of every part (-1: the model's own)
        self.billboard = -1              # cmd_3cd8 (-1: the model's own)
        self.shown_at = 0
        self.uv = np.zeros(2)
        self.cmd = None                  # the show command (for the editor)

    def lerps(self):
        return (self.pos, self.scale, self.nscale, self.rot, self.rot2, self.color)


class Screen:
    def __init__(self):
        self.fade = Lerp([0.0])                       # -128 white .. 128 black
        self.back = Lerp(np.zeros((4, 3)))            # backdrop corner colours 0..1 (TL, TR, BL, BR)
        self.map_color = Lerp([1.0, 1.0, 1.0, 1.0])
        self.units_dim = Lerp([1.0, 1.0, 1.0, 1.0])   # cmd_6480 10000: the other units
        self.back_on = False

    def lerps(self):
        return (self.fade, self.back, self.map_color, self.units_dim)


class Stage:
    def __init__(self, setup):
        self.frame = -1
        self.setup = setup
        cp, tp = setup.caster_pos(), setup.target_pos()
        d = tp - cp
        n = math.hypot(d[0], d[2]) or 1.0
        fwd = np.array([d[0] / n, d[2] / n])
        self.actors = {CASTER: Actor(cp, setup.caster_sprite, setup.caster_palette, fwd)}
        for i, p in enumerate(setup.target_places()[:choreo.MAX_TARGETS]):
            # area target i (3000 + i; the first is the main target): faces the caster as it stands
            self.actors[choreo.target_actor(i)] = Actor(p, setup.target_sprite, setup.target_palette, -fwd)
        self.slots = {}
        self.locators = {}
        self.cam = Camera(cp, setup.view_yaw)
        self.screen = Screen()
        self.map_back = np.array([[0.10, 0.09, 0.14]] * 4)     # the map's own backdrop (cmd_2835)
        self.screen.back.to(self.map_back)
        self.hits = []                  # (frame, actor, percent)
        self.q = facing_quarter(setup.facing)
        self.mirror = [False] * 12      # the skill's mirror switches (cmd_72f0 all, 32f8 / 3cd0 ... one each)

    def off(self, a, i):
        """the offset at a[i:i+3] turned to the world"""
        return turn_offset(a[i:i + 3], self.q)

    # ---------------------------------------------------------------- places
    def actor(self, a, create=True):
        a = choreo.actor_id(a)
        ac = self.actors.get(a)
        if ac is None and create and isinstance(a, int):
            ac = Actor(self.actors[CASTER].pos)
            ac.sprite = None
            ac.dir = self.actors[CASTER].dir.copy()
            self.actors[a] = ac
        return ac

    def where(self, a, _depth=0):
        """world position of an actor operand: locator 300-399; 1xxxx = actor xxxx where it is now (0x140087a60
        asks the actor for its position; mid-move too -- Macrocosm's combo camera matches its recording at every
        frame this way); a plain id = the actor's base place (+0x14: where it stood when the skill took it /
        cmd_6620 -- seen: the camera of Macrocosm's last scene goes back to the ground while the caster was left
        1000 up in the sky)"""
        try:
            a = int(a)
        except (TypeError, ValueError):
            return self.actors[CASTER].place(self)
        if 300 <= a < 400 and a in self.locators:
            return self.locators[a].copy()
        if 5000 <= a < 5256:
            # area panel i (0x140087330: the panel's centre on the ground); the preview's panels in cell order
            area = [p for p in (self.setup.area or []) if p[3] != 2]
            i = a - 5000
            if i < len(area):
                return np.array(area[i][:3], float)
            return self.setup.target_pos()
        if 7000 <= a % 10000 < 7256 and a < 20000:
            # effect slot i (0x1402eaa20: 7000 + i is the slot table 0x141DA0AE0, stride 0x358; as 7000 + i or
            # 17000 + i the resolver asks it where it is -- Dazzling Eyes puts its last hearts where slot 9 is)
            sl = self.slots.get(a % 10000 - 7000)
            if sl is not None and _depth < 8:
                return np.array(self.slot_world(sl, _depth + 1), float)
            return self.actors[CASTER].place(self).copy()
        if 10000 < a < 20000:
            ac = self.actors.get(choreo.actor_id(a - 10000)) or self.actors[CASTER]
            return ac.place(self).copy()
        ac = self.actors.get(choreo.actor_id(a))
        if ac is None:
            ac = self.actors[CASTER]
        if PLAIN_IS_BASE:
            lead = self.actors.get(ac.follow) if ac.follow is not None else None
            return (lead.base if lead is not None else ac.base).copy()
        return ac.place(self)

    def slot(self, s):
        sl = self.slots.get(s)
        if sl is None:
            sl = self.slots[s] = Slot()
        return sl

    def slot_world(self, sl, _depth=0):
        if sl.attached is not None:
            return self.where(sl.attached, _depth) + sl.offset
        return sl.pos.get()

    # ---------------------------------------------------------------- commands
    def apply(self, op, models):
        c, a, f = op.cid, op.args, op.frame
        if c in MIRROR_SET:
            on = bool(a[0]) if a and isinstance(a[0], (int, float)) else False
            k = MIRROR_SET[c]
            if k is None:
                self.mirror = [on] * 12
            else:
                self.mirror[k] = on
            return
        mm = MIRROR_ARGS.get(c)
        if mm is not None and self.mirror[mm[0]]:
            a = list(a)
            for i in mm[1]:
                if i < len(a) and isinstance(a[i], (int, float)):
                    a[i] = -a[i]
        h = _HANDLERS.get(c)
        if h is not None:
            try:
                h(self, a, f, models)
            except (IndexError, TypeError, ValueError, ZeroDivisionError):
                pass

    # ---------------------------------------------------------------- one frame
    def begin_frame(self):
        """what runs before a frame's scripts: the units' motion clocks advance (so a motion started or moved by this
        frame's commands is drawn at the time they set)"""
        for ac in self.actors.values():
            ac.mtime += ac.speed / 100.0

    def tick(self, models):
        cam = self.cam
        for lp in cam.lerps():
            lp.tick()
        cam.tick_shake()
        for lp in self.screen.lerps():
            lp.tick()
        for ac in self.actors.values():
            for lp in ac.lerps():
                lp.tick()
            if ac.dturn is not None:
                d0, d1, n, i = ac.dturn
                i += 1
                ac.dir = ang_dir(d0 + (d1 - d0) * min(1.0, i / float(n)))
                ac.dturn = None if i >= n else (d0, d1, n, i)
            if ac.turn is not None:
                a0, a1, n, i, ease = ac.turn
                i += 1
                t = 1.0 if i >= n else i / float(n)
                ac.angle = a0 + (a1 - a0) * (ease.at(t) if ease is not None else t)
                ac.turn = None if i >= n else (a0, a1, n, i, ease)
            mv = ac.move
            if mv is not None:
                ac.pos, done = mv.tick(ac.pos)
                if done:
                    ac.move = None
                    if HOME_FOLLOWS_MOVES:
                        ac.home = mv.dst.copy()
        for k, sl in list(self.slots.items()):
            if not sl.shown:
                continue
            for lp in sl.lerps():
                lp.tick()
            m = models(sl.effect) if models else None
            length = (m.anim.length if (m is not None and m.anim is not None) else 0) or 0
            end = sl.end if sl.end is not None else length
            if not sl.drawn:              # hidden by cmd_3c9a 0: the game skips its update too (0x1402ffca0)
                continue
            sl.frame += sl.step
            if sl.step >= 0 and sl.frame > end + 1:
                if sl.plays == 0:
                    sl.shown = False
                elif sl.plays > 0:
                    sl.plays -= 1
                    if sl.plays == 0:
                        sl.shown = False
                    else:
                        sl.frame = float(sl.loop_start)
                else:
                    sl.frame = float(sl.loop_start)
            elif sl.step < 0 and sl.frame < -1.0:     # backwards: the game wraps below -1 (0x140300c96), not 0
                sl.frame = float(end)

    # ---------------------------------------------------------------- for the editor (old scene format)
    def scene_dict(self):
        actors = {}
        for k, ac in self.actors.items():
            actors[k] = dict(sprite=ac.sprite, copy=ac.copy, anim=ac.anim, speed=ac.speed, motion=ac.motion,
                             motion_time=ac.mtime * 100.0 / (ac.speed or 100.0), tint=list(ac.tint.get() * 100.0),
                             offset=list(ac.offset.get()), scale=list(ac.scale.get() * 100.0),
                             rot=list(ac.rot.get()), visible=ac.exists, place=[], world=ac.place(self))
        slots = {}
        for k, sl in self.slots.items():
            if not sl.shown or sl.effect is None:
                continue
            world = self.slot_world(sl)
            slots[k] = dict(effect=sl.effect, actor=sl.attached if sl.attached is not None else sl.actor,
                            pos=list(sl.offset), size=sl.size * 1000.0, scale=list(sl.scale.get() * 100.0),
                            rot=list(sl.rot.get()), color=list(sl.color.get() * 100.0), glow=0.0,
                            speed=100.0, mode=sl.layer, layer=sl.blend, time=sl.frame,
                            anim=None, fly=None, plays=sl.plays, world=world)
        c = self.cam
        homes = {k: ac.home.copy() for k, ac in self.actors.items()}
        places = {k: ac.place(self) for k, ac in self.actors.items()}
        return dict(actors=actors, slots=slots, frame=self.frame, homes=homes, places=places,
                    camera=dict(actor=CASTER, offset=[0, 0, 0], zoom=float(c.dist.get()[0]), shake=0.0,
                                target=c.target.get(), dist=float(c.dist.get()[0]), rot=c.rot.get()),
                    particles=[], fade=float(self.screen.fade.get()[0]),
                    locators={k: v.copy() for k, v in self.locators.items()})


def scene_where(scene, a):
    """Stage.where() from a scene dict (a snapshot: positions as they were at its frame)"""
    places, homes, locs = scene.get("places", {}), scene.get("homes", {}), scene.get("locators", {})
    try:
        a = int(a)
    except (TypeError, ValueError):
        return np.array(places.get(CASTER, np.zeros(3)), float)
    if 300 <= a < 400 and a in locs:
        return np.array(locs[a], float)
    if 7000 <= a % 10000 < 7256 and a < 20000:  # where effect slot i is
        sl = scene.get("slots", {}).get(a % 10000 - 7000)
        if sl is not None and sl.get("world") is not None:
            return np.array(sl["world"], float)
        return np.array(places.get(CASTER, np.zeros(3)), float)
    if 10000 < a < 20000:                       # where the actor is (Stage.where)
        return np.array(places.get(choreo.actor_id(a - 10000), places.get(CASTER, np.zeros(3))), float)
    a = choreo.actor_id(a)
    return np.array(places.get(a, places.get(CASTER, np.zeros(3))), float)


# ------------------------------------------------------------------------------------------------ handlers
def _vec(a, i):
    return np.array([float(a[i]), float(a[i + 1]), float(a[i + 2])])


def _h_cam_target(st, a, f, m, eased=False):
    p = st.where(a[0]) + st.off(a, 1)
    st.cam.target.to(p, a[4], ease_factor(a[5], a[6]) if eased else None)


def _h_cam_dist(st, a, f, m, eased=False):
    d = float(a[1]) or DEFAULT_DIST
    st.cam.dist.to([d], a[0], ease_factor(a[2], a[3]) if eased else None)


def _h_cam_turn_by(st, a, f, m, eased=False):
    d = -np.radians([float(a[1]), float(a[2]), float(a[3])])
    st.cam.rot.to(st.cam.rot.b + d, a[0], ease_factor(a[4], a[5], 1000.0) if eased else None)


def _h_cam_turn_to(st, a, f, m):
    yaw = math.radians(st.setup.view_yaw)
    st.cam.rot.to([math.radians(30.0 - a[1]), yaw - math.radians(a[2]), -math.radians(a[3])], a[0])


def _h_cam_reset(st, a, f, m):
    st.cam.rot.to([math.radians(DEFAULT_PITCH), math.radians(st.setup.view_yaw), 0.0], a[0])


def _h_cam_stop(st, a, f, m):
    """cmd_325c (0x140166fd0): the camera stops turning -- its rotation keeps the angle it has now; aim, distance
    and lens go on (Macrocosm's opening aim continues after it in the recording)"""
    st.cam.rot.to(st.cam.rot.get())


def _signed32(v):
    v = int(v)
    return v - (1 << 32) if v >= 1 << 31 else v


def _h_shake(st, a, f, m):
    """cmd_32a0 sideways, up-down, frames (0x140167560): amounts / 10 x 0.1 map units; frames -1 = until stopped"""
    n = int(a[2])
    n = n - 65536 if n >= 32768 else n
    st.cam.shake = [0x7fff if n < 0 else n, _signed32(a[0]) / 100.0, _signed32(a[1]) / 100.0]


def _h_lens(st, a, f, m, eased=False):
    """cmd_3250 frames, value / 3258 + ease, flag: the camera's lens (field of view LENS_FOV / value degrees)"""
    st.cam.lens.to([float(a[1]) or LENS_DEFAULT], a[0], ease_factor(a[2], a[3], 1000.0) if eased else None)


def _signed8(v):
    v = int(v) & 0xFF
    return v - 256 if v >= 128 else v


def _signed16(v):
    v = int(v) & 0xFFFF
    return v - 65536 if v >= 32768 else v


def _h_fade(st, a, f, m):
    v = _signed8(a[0])
    v = 128 if v == 127 else (-128 if v == -127 else v)
    st.screen.fade.to([float(v)], a[1])


def _col8(*vals):
    return [max(0, _signed8(v)) / 128.0 for v in vals]


def _h_back4(st, a, f, m):
    cs = [_col8(*a[1 + 3 * i: 4 + 3 * i]) for i in range(4)]
    st.screen.back.to(cs, a[0])


def _h_back2(st, a, f, m):
    A, B = _col8(*a[1:4]), _col8(*a[4:7])
    cs = [A, A, B, B] if a[7] else [A, B, A, B]
    st.screen.back.to(cs, a[0])


def _h_back1(st, a, f, m):
    st.screen.back.to([_col8(*a[1:4])] * 4, a[0])


def _h_back_map(st, a, f, m):
    st.screen.back.to(st.map_back, a[0])


def _h_map_color(st, a, f, m):
    st.screen.map_color.to([a[0] / 100.0, a[1] / 100.0, a[2] / 100.0, a[3] / 100.0], a[4])


# ---- units
def _h_motion(st, a, f, m):
    ac = st.actor(a[0])
    ac.motion, ac.motion_start, ac.anim, ac.mtime = a[1], f, None, 0.0


def _h_anim(st, a, f, m):
    ac = st.actor(a[0])
    ac.anim, ac.motion_start, ac.mtime = a[1], f, 0.0


def _h_motion_frame(st, a, f, m):
    """cmd_6530 actor, N: the motion jumps to frame N (0x14016d070 -> 0x1402f5740 time = N << 16); no wait"""
    st.actor(a[0]).mtime = float(max(0, a[1]))


def _h_sprite(st, a, f, m):
    ac = st.actor(a[0])
    num = int(a[1])
    num = st.setup.class_sprites.get(num, num)
    ac.sprite = st.setup.event_sheets.get(num, num)
    ac.copy = None
    ac.motion, ac.motion_start, ac.anim, ac.mtime = 0, f, None, 0.0
    ac.exists = True


def _slot_operand(st, v):
    """an effect slot addressed like an actor: 7000 + i (17000 + i: the same) -> its Slot, else None"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    if 7000 <= v % 10000 < 7256 and v < 20000:
        return st.slots.get(v % 10000 - 7000)
    return None


def _lead_operand(v):
    """what a follower is placed from: an effect slot as it is (7000 + i), an actor where it is NOW (1xxxx)"""
    v = int(v)
    if 7000 <= v % 10000 < 7256 or v >= 10000:
        return v
    return 10000 + v


def _h_follow(st, a, f, m):
    """cmd_6c04 a, b (0x140184670 -> 0x1402e78e0): a moves with b from now on, staying where it is -- the game
    stores a's place relative to b's (child +0x128) (Macrocosm: the Killia you see follows the hidden caster).
    a can be an effect slot (7000 + i): Exploding Tiger's flames ride along with the dashing fighter"""
    sl = _slot_operand(st, a[0])
    if sl is not None:
        here = st.slot_world(sl)
        sl.attached = _lead_operand(a[1])
        sl.offset = here - st.where(sl.attached)
        return
    ac = st.actor(a[0])
    src = choreo.actor_id(a[1])
    if src in st.actors and src != choreo.actor_id(a[0]):
        here = ac.place(st) - ac.offset.get()
        ac.follow = src
        ac.follow_off = here - st.actors[src].place(st)
        ac.dir = st.actors[src].dir.copy()


def _h_attach_at(st, a, f, m):
    """cmd_6c00 a, b, x, y, z (0x140184470 -> 0x1402e7b20): a moves with b from now on, at the offset x, y, z from it
    (tenths of map units, turned by the skill's facing; x mirrored by switch 10, cmd_6c80)"""
    sl = _slot_operand(st, a[0])
    if sl is not None:
        sl.attached = _lead_operand(a[1])
        sl.offset = st.off(a, 2) / 10.0
        return
    ac = st.actor(a[0])
    src = choreo.actor_id(a[1])
    if src in st.actors and src != choreo.actor_id(a[0]):
        ac.follow = src
        ac.follow_off = st.off(a, 2) / 10.0
        ac.dir = st.actors[src].dir.copy()


def _h_unfollow(st, a, f, m):
    """cmd_6c08 a: a stops following, staying where it is"""
    sl = _slot_operand(st, a[0])
    if sl is not None:
        if sl.attached is not None:
            sl.pos.to(st.slot_world(sl))
            sl.attached = None
        return
    ac = st.actor(a[0], create=False)
    if ac is not None and ac.follow is not None:
        ac.pos = ac.place(st) - ac.offset.get()
        ac.follow = None
        ac.follow_off = np.zeros(3)


def _h_copy(st, a, f, m):
    """cmd_6410 / 6412 a, b (0x140168d70): b = mode x 10000 + number (u16) -- mode 0 / 1: a looks like actor
    `number` (an after-image); 3: like class `number`; 5: sprite `number` (9100 is empty: an invisible helper)"""
    mode, num = choreo.copy_source(a[1])
    if mode <= 1:
        s = st.actors.get(choreo.actor_id(num)) if num > 0 else None
        if s is not None:
            ac = st.actor(a[0])
            ac.sprite, ac.palette, ac.copy = s.sprite, s.palette, choreo.actor_id(num)
            ac.dir = s.dir.copy()
    elif mode == 3:
        ac = st.actor(a[0])
        ac.sprite, ac.copy = st.setup.class_sprites.get(num, num), None
    elif mode == 5:
        ac = st.actor(a[0])
        ac.sprite, ac.copy = (None if num == 9100 else num), None


def _h_new(st, a, f, m):
    st.actor(a[0]).exists = True


def _h_cutin(st, a, f, m):
    """cmd_6411 a, b: a shows b's cut-in portrait (the sprite file 10000 + b's sprite: animations 8000-8100)"""
    s = st.actors.get(choreo.actor_id(a[1]))
    if s is not None and s.sprite:
        ac = st.actor(a[0])
        ac.sprite, ac.palette, ac.copy = 10000 + int(s.sprite), s.palette, None


def _h_screen(st, a, f, m):
    st.actor(a[0]).screen = bool(a[1])


def _h_actor_fade(st, a, f, m):
    """cmd_6482 a, opacity %, frames: the same opacity cmd_6480 sets (the cut-in: 6480 hides it, 6482 shows it)"""
    ac = st.actor(a[0])
    v = ac.tint.b.copy()
    v[3] = a[1] / 100.0
    ac.tint.to(v, a[2])


def _h_screen_place(st, a, f, m):
    st.actor(a[0]).spos.to([a[1] / 10.0, a[2] / 10.0])


def _h_screen_move(st, a, f, m):
    st.actor(a[0]).spos.to([a[1] / 10.0, a[2] / 10.0], a[4], ease_factor(a[5], a[6]))


def _h_place_at(st, a, f, m):
    ac = st.actor(a[0])
    src = st.actor(a[1], create=False)
    if src is not None:
        ac.pos = src.place(st) - src.offset.get()
        ac.home = ac.pos.copy()
        ac.base = ac.pos.copy()
        ac.dir = src.dir.copy()


def _h_face_as(st, a, f, m):
    ac, src = st.actor(a[0]), st.actor(a[1], create=False)
    if src is not None:
        ac.dir = src.dir.copy()


def _h_home(st, a, f, m):
    ac = st.actor(a[0])
    ac.home = ac.pos.copy()
    ac.base = ac.pos.copy()


def _h_shadow(st, a, f, m):
    """cmd_6470 actor, mode (0x14016a5b0 -> actor +0x25c): how its shadow finds the ground; 0 = no shadow (the
    shadow draw 0x1402f3520 skips a sprite whose +0x324 the update 0x140149bd7 cleared for mode 0)"""
    st.actor(a[0]).shadow = bool(a[1])


def _h_speed(st, a, f, m):
    """cmd_6570 actor, percent (0x14016d860: the sprite's speed = percent / 100)"""
    st.actor(a[0]).speed = float(a[1])


def _h_pause(st, a, f, m):
    """cmd_6560 actor, on: 0 stops the motion, anything else plays it at 100 % (0x14016d530 sets the same speed
    field as cmd_6570: an earlier speed is not kept)"""
    st.actor(a[0]).speed = 0.0 if a[1] == 0 else 100.0


def _face_to(st, a, dst):
    ac = st.actor(a[0])
    d = dst - ac.pos
    if abs(d[0]) + abs(d[2]) > 1e-3 and choreo.actor_id(a[0]) != choreo.actor_id(a[1]):
        k = math.hypot(d[0], d[2])
        ac.dir = np.array([d[0] / k, d[2] / k])
    return ac


def _start_move(st, ac, mv, frames):
    """frames <= 0: at once (0x1402e4610 puts it there)"""
    if int(frames) <= 0:
        ac.pos, ac.move = mv.dst.copy(), None
        if HOME_FOLLOWS_MOVES:
            ac.home = mv.dst.copy()
    else:
        ac.move = mv


def _landing(st, ac, mode, dst, yoff):
    """(landing height, apex height) of the arc modes (the same in 6642 / 6672 / 6680): 1 the ground there / the
    destination, 2 the destination without the offset's height / the destination, 5 the ground / the offset above
    the lower of the ground and the start, 6 the destination without the offset / the offset above the lower of
    that and the start"""
    cur = float(ac.pos[1])
    if mode in (1, 11, 21):
        return st.setup.ground(dst[0], dst[2]), float(dst[1])
    if mode in (2, 12, 22):
        return float(dst[1]) - yoff, float(dst[1])
    if mode == 5:
        g = st.setup.ground(dst[0], dst[2])
        return g, min(g, cur) + yoff
    if mode == 6:
        land = float(dst[1]) - yoff
        return land, min(land, cur) + yoff
    return None, None


def _arc(kind, ac, dst, frames, land, apex):
    end = np.array([dst[0], land, dst[2]])
    mv = UnitMove(kind, ac.pos, end, frames)
    y0 = float(ac.pos[1])
    mv.curve = apex_curve(apex - y0, land - y0)
    return mv


def _h_move(st, a, f, m):
    """cmd_6642 actor, to, x, y, z, frames, mode (0x14016fa40): 0 straight; 1 / 2 / 5 / 6 an arc (kind 4)"""
    dst = st.where(a[1]) + st.off(a, 2)
    ac = _face_to(st, a, dst)
    n, mode = int(a[5]), int(a[6]) if len(a) > 6 else 0
    if mode == 0:
        _start_move(st, ac, UnitMove.velocity(ac.pos, dst, max(1, n)), n)
        return
    land, apex = _landing(st, ac, mode, dst, float(a[3]))
    if land is None:
        return
    _start_move(st, ac, _arc(4, ac, dst, n, land, apex), n)


def _h_move_eased(st, a, f, m):
    """cmd_6672 actor, to, x, y, z, frames, mode, ease, every (0x140170920): 0 speeding up / slowing down step by
    step, 100 eased steps, 1 / 2 / 21 / 22 / 5 / 6 arcs (kinds 5 / 7), 11 / 12 eased sideways + arc (kind 6)"""
    dst = st.where(a[1]) + st.off(a, 2)
    ac = _face_to(st, a, dst)
    n, mode = int(a[5]), int(a[6]) if len(a) > 6 else 100
    e = float(a[7]) if len(a) > 7 else 0.0
    every = int(a[8]) if len(a) > 8 else 1
    p = unit_ease(e)
    if mode == 0:
        _start_move(st, ac, UnitMove.velocity(ac.pos, dst, max(1, n), e / 1000.0, every), n)
        return
    if mode == 100:
        mv = UnitMove(2, ac.pos, dst, n)
        mv.ease = EaseSteps(p, n, every)
        _start_move(st, ac, mv, n)
        return
    land, apex = _landing(st, ac, mode, dst, float(a[3]))
    if land is None:
        return
    kind = {1: 5, 2: 5, 5: 7, 6: 7, 21: 7, 22: 7, 11: 6, 12: 6}[mode]
    mv = _arc(kind, ac, dst, n, land, apex)
    if kind == 6:
        mv.ease = EaseSteps(p, n, every)
    else:
        mv.p = p
    _start_move(st, ac, mv, n)


def _h_jump(st, a, f, m):
    """cmd_6680 actor, to, x, y, z, frames, mode, ease up-down, ease sideways, every (0x140171940 -> 0x1402e5770,
    kind 8): modes 1 / 2 / 5 / 6 pick the landing and the apex; the y offset is how high it jumps"""
    dst = st.where(a[1]) + st.off(a, 2)
    ac = _face_to(st, a, dst)
    n, mode = int(a[5]), int(a[6])
    p_v, p_h = unit_ease(a[7]), unit_ease(a[8])
    every = int(a[9]) if len(a) > 9 else 1
    if mode == 0:
        _start_move(st, ac, UnitMove.velocity(ac.pos, dst, max(1, n), p_h, every), n)
        return
    land, apex = _landing(st, ac, mode, dst, float(a[3]))
    if land is None:
        return
    mv = _arc(8, ac, dst, n, land, apex)
    mv.ease = EaseSteps(p_h, n, every)
    mv.p = p_v
    _start_move(st, ac, mv, n)


def _h_pixel_offset(st, a, f, m):
    """cmd_65bc actor, frames, x, y (0x14016e690 -> 0x1402f2d80): the sprite drawn shifted by x, y x 0.1875 sprite
    pixels (y down) -- Macrocosm lifts the juggled enemy with 0, -300"""
    n = int(a[1]) if a[1] > 1 else 0
    st.actor(a[0]).pix.to([float(a[2]) * 0.1875, float(a[3]) * 0.1875], n)


def _h_pixel_shift(st, a, f, m):
    """cmd_65ba actor, frames, x, y (0x14016e550 -> 0x1402f2d80): like 65bc, but BY x, y from where the sprite is
    drawn now (the game subtracts x, y x -0.1875 from the sprite's current offset)"""
    n = int(a[1]) if a[1] > 1 else 0
    ac = st.actor(a[0])
    cx, cy = ac.pix.get()
    ac.pix.to([cx + float(a[2]) * 0.1875, cy + float(a[3]) * 0.1875], n)


def _h_unit_turn(st, a, f, m):
    """cmd_6710 unit, frames, degrees (0x140173ca0): the unit turns, which changes the view of it drawn (front / back,
    mirrored). frames >= 10000: TO the skill's direction + degrees, the short way, over frames - 10000 (0x140149070);
    else BY degrees from where it faces -- whole spins too -- over frames (0x140149170). Degrees mirrored by switch 7
    (cmd_67f0)"""
    ac = st.actor(a[0])
    cur = dir_ang(ac.dir)
    if a[1] >= 10000:
        n = int(a[1]) - 10000
        end = cur + _norm180(facing_quarter(st.setup.facing) * 90.0 + float(a[2]) - cur)
    else:
        n = int(a[1])
        end = cur + float(a[2])
    if n <= 0:
        ac.dir, ac.dturn = ang_dir(end), None
    else:
        ac.dturn = (cur, end, n, 0)


def _norm180(d):
    d = (d + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def _start_turn(ac, delta, frames, px, py, ease=None):
    """0x14014ba70: the turn starts from the sprite's angle (0..359) around the pivot (values x 3, drawn x 0.0625)"""
    cur = ac.angle % 360.0
    ac.pivot = (float(px) * 3.0, float(py) * 3.0)
    n = int(frames)
    if n <= 0:
        ac.angle, ac.turn = cur + delta, None
    else:
        ac.angle, ac.turn = cur, (cur, cur + delta, n, 0, ease)


def _h_turn(st, a, f, m, eased=False):
    """cmd_65b4 actor, frames, pivot x, pivot y, degrees (+ ease, every: 65b5): turn the sprite BY degrees
    (clockwise in its own pixels, so mirrored sprites turn the other way on screen; Macrocosm's juggled enemy)"""
    ease = EaseSteps(unit_ease(a[5]), int(a[1]), int(a[6]) if len(a) > 6 else 1) if eased and len(a) > 5 else None
    _start_turn(st.actor(a[0]), float(a[4]), a[1], a[2], a[3], ease)


def _h_turn_to(st, a, f, m, eased=False):
    """cmd_65b8 actor, frames, pivot x, pivot y, degrees (+ ease, every: 65c1; 0x14016e350): turn the sprite TO an
    angle the short way round"""
    ac = st.actor(a[0])
    cur = _norm180(ac.angle % 360.0)
    ease = EaseSteps(unit_ease(a[5]), int(a[1]), int(a[6]) if len(a) > 6 else 1) if eased and len(a) > 5 else None
    _start_turn(ac, _norm180(float(a[4]) - cur), a[1], a[2], a[3], ease)


def _h_scale(st, a, f, m, eased=False):
    st.actor(a[0]).scale.to(_vec(a, 2) / 100.0, a[1], ease_factor(a[5], a[6]) if eased else None)


def _plus1(a):
    """cmd_65b6 / 65b9 / 65bb / 65bd: jump into 65b4 / 65b8 / 65ba / 65bc with the second operand (frames) + 1"""
    return [a[0], a[1] + 1] + list(a[2:])


def _h_tint(st, a, f, m):
    v = [a[1] / 100.0, a[2] / 100.0, a[3] / 100.0, a[4] / 100.0]
    if choreo.actor_id(a[0]) == ALL_UNITS:
        st.screen.units_dim.to(v, a[5])
        return
    st.actor(a[0]).tint.to(v, a[5])


def _h_locator(st, a, f, m):
    st.locators[int(a[0])] = st.where(a[1]) + st.off(a, 2)


def _h_locator_move(st, a, f, m):
    k = int(a[0])
    if k in st.locators:
        st.locators[k] = st.locators[k] + st.off(a, 1)


def _h_damage(st, a, f, m):
    pct = a[2] if len(a) > 2 else 0
    try:
        raw = int(a[0])
    except (TypeError, ValueError):
        raw = None
    if raw == 3603:
        # every area target (cmd_7220 3603, 3603, 100 is the most common hit; the game's damage code takes 3603,
        # 3613, 10000, 20000, 25000, 30000 without a place)
        for i in range(len(st.setup.target_places())):
            st.hits.append((f, choreo.target_actor(i), pct))
        return
    st.hits.append((f, choreo.actor_id(a[0]), pct))


# ---- effects
def _h_load(st, a, f, m):
    sl = st.slot(a[0])
    sl.__init__()
    sl.effect = int(a[1])


def _h_show(st, a, f, m, attached=False, ranged=False):
    sl = st.slot(a[0])
    if sl.effect is None:
        return
    actor = a[1]
    off = st.off(a, 2)
    base = st.where(actor)
    sl.actor = choreo.actor_id(actor)
    sl.offset = off
    sl.attached = actor if attached else None
    sl.pos.to(base + off)
    sl.size = float(a[5]) / 1000.0
    sl.step = a[6] / 1000.0             # 0: the model holds its frame (3880 vanilla shows do)
    sl.plays = a[7]
    sl.shown = True
    sl.drawn = True
    sl.shown_at = f
    if ranged and len(a) > 11 and any(a[8:12]):
        sl.start, sl.end, sl.loop_start = int(a[8]), (int(a[9]) if a[9] > 0 else None), int(a[8])
    else:
        sl.start, sl.end, sl.loop_start = 0, None, 0
    sl.frame = float(sl.start) if sl.step >= 0 else float(sl.end or 0)
    sl.rot.to([0.0, 0.0, 0.0])
    sl.rot2.to([0.0, 0.0, 0.0])
    # the show's size IS the effect's size (0x140178750 -> 0x140089170: size / 1000 on every axis at once, x flipped
    # when mirrored), the same value cmd_3c40 / 3c42 change later
    k = float(a[5]) / 1000.0
    sl.scale.to([-k if st.mirror[3] else k, k, k])


def _h_remove(st, a, f, m):
    sl = st.slots.get(a[0])
    if sl is not None:
        sl.shown = False


def _h_fx_scale(st, a, f, m, eased=False):
    st.slot(a[0]).scale.to(_vec(a, 2) / 100.0, a[1], ease_factor(a[5], a[6]) if eased else None)


def _h_fx_scale_by(st, a, f, m, eased=True):
    """cmd_3c48 slot, frames, sx, sy, sz, ease, every (0x14017a4d0): like 3c42, but percent OF the effect's current
    size (the game multiplies by the slot's size +0x2c8..; no mirroring: the current size has the sign already)"""
    sl = st.slot(a[0])
    sl.scale.to(sl.scale.get() * (_vec(a, 2) / 100.0), a[1], ease_factor(a[5], a[6]) if eased else None)


def _h_fx_nscale(st, a, f, m, eased=False):
    st.slot(a[0]).nscale.to(_vec(a, 2) / 100.0, a[1], ease_factor(a[5], a[6]) if eased else None)


def _h_fx_rot_to(st, a, f, m, which="rot", eased=False):
    lp = getattr(st.slot(a[0]), which)
    lp.to(_vec(a, 2), a[1], ease_factor(a[5], a[6]) if eased else None)


def _h_fx_rot_by(st, a, f, m, which="rot", eased=False):
    lp = getattr(st.slot(a[0]), which)
    lp.to(lp.b + _vec(a, 2), a[1], ease_factor(a[5], a[6]) if eased else None)


def _h_fx_order(st, a, f, m):
    sl = st.slot(a[0])
    if a[1] <= 5:
        sl.rot_order = int(a[1])
    else:
        sl.rot2_order = int(a[1])


def _h_fx_color(st, a, f, m, eased=False):
    v = [a[2] / 100.0, a[3] / 100.0, a[4] / 100.0, a[5] / 100.0]
    st.slot(a[0]).color.to(v, a[1], ease_factor(a[6], a[7]) if eased else None)


def _h_fx_alpha(st, a, f, m, eased=False):
    sl = st.slot(a[0])
    cur = sl.color.b.copy()
    cur[3] = a[2] / 100.0
    sl.color.to(cur, a[1], ease_factor(a[3], a[4]) if eased else None)


def _h_fx_zbias(st, a, f, m):
    """cmd_3ca0 slot, value (0x14017c790): the effect is drawn value / 20 map units nearer the camera -- in the depth
    test and in the order of the sorted queue (z' = (z + b) / (w + b), b = value / -20: 0x14030aba0, 0x14030b4d0).
    Vanilla: 100-1000 on most effects (20 788 uses), so they sit on the ground or a unit without cutting into it."""
    st.slot(a[0]).zbias = float(_signed16(a[1])) / 20.0 * MAP


def _h_fx_queue(st, a, f, m):
    """cmd_3cde slot, queue (0x14017d5e0): every part of the effect goes into that draw queue (0-11; the game draws
    queue 0 first); without it a part uses its mesh layer byte + 2 (alpha pictures 4, glows 6)"""
    q = int(a[1])
    if q < 12:
        st.slot(a[0]).queue = q


def _h_fx_drawn(st, a, f, m):
    """cmd_3c9a slot, 0 / 1 (0x14017c6f0): hide the effect (it stops animating) / show it again"""
    st.slot(a[0]).drawn = bool(a[1])


def _h_fx_face_cam(st, a, f, m):
    """cmd_3ca5 slot, 1 (0x14017c860 -> 0x1402ffca0): its billboard parts stop turning to the camera"""
    st.slot(a[0]).face_cam = not bool(a[1])


def _h_fx_step(st, a, f, m):
    st.slot(a[0]).step = a[1] / 990.0


def _h_fx_frame(st, a, f, m):
    st.slot(a[0]).frame = float(a[1])


def _h_fx_layer(st, a, f, m):
    st.slot(a[0]).layer = int(a[2] if len(a) > 2 else a[1])


def _h_fx_blend(st, a, f, m):
    st.slot(a[0]).blend = _signed8(a[1])


def _h_fx_billboard(st, a, f, m):
    st.slot(a[0]).billboard = _signed8(a[1])


def _h_fx_move(st, a, f, m, eased=False):
    sl = st.slot(a[0])
    dst = st.where(a[1]) + st.off(a, 2)
    if sl.attached is not None:
        sl.pos.to(st.slot_world(sl))
        sl.attached = None
    p = ease_factor(a[7], a[8]) if eased and len(a) > 8 else None
    sl.pos.to(dst, a[5], p)


_HANDLERS = {
    0x3210: _h_cam_target, 0x3220: lambda s, a, f, m: _h_cam_target(s, a, f, m, True),
    0x3230: _h_cam_dist, 0x3240: lambda s, a, f, m: _h_cam_dist(s, a, f, m, True),
    0x3260: _h_cam_turn_by, 0x3280: lambda s, a, f, m: _h_cam_turn_by(s, a, f, m, True),
    0x3268: _h_cam_turn_to, 0x3290: _h_cam_reset, 0x325c: _h_cam_stop, 0x32a0: _h_shake,
    0x3250: _h_lens, 0x3258: lambda s, a, f, m: _h_lens(s, a, f, m, True),
    0x2810: _h_fade, 0x2830: _h_back4, 0x2832: _h_back2, 0x2834: _h_back1, 0x2835: _h_back_map,
    0x2820: _h_map_color,
    0x6510: _h_motion, 0x6500: _h_anim, 0x6402: _h_sprite, 0x6405: _h_sprite, 0x6c04: _h_follow, 0x6c08: _h_unfollow,
    0x6c00: _h_attach_at,
    0x6410: _h_copy, 0x6412: _h_copy, 0x640a: _h_new, 0x65f4: _h_place_at, 0x65f6: _h_place_at,
    0x6630: _h_face_as, 0x6620: _h_home, 0x6411: _h_cutin, 0x6460: _h_screen,
    0x6482: _h_actor_fade, 0x6660: _h_screen_place, 0x6664: _h_screen_move, 0x6570: _h_speed, 0x6560: _h_pause,
    0x6530: _h_motion_frame, 0x6470: _h_shadow,
    0x6642: _h_move, 0x6672: _h_move_eased, 0x6680: _h_jump,
    0x65b8: _h_turn_to, 0x65c1: lambda s, a, f, m: _h_turn_to(s, a, f, m, True), 0x65bc: _h_pixel_offset,
    0x65a0: _h_scale, 0x65a1: lambda s, a, f, m: _h_scale(s, a, f, m, True),
    0x65b4: _h_turn, 0x65b5: lambda s, a, f, m: _h_turn(s, a, f, m, True),
    0x6480: _h_tint, 0x66b0: _h_locator, 0x66b8: _h_locator_move, 0x7220: _h_damage,
    # thin wrappers of the commands above (their handlers only rearrange operands, disgaea5.exe 2026-10-13)
    0x65b0: lambda s, a, f, m: _h_scale(s, [a[0], a[1], a[2], a[3], a[2]], f, m),        # 0x14016df60: x = z
    0x65b6: lambda s, a, f, m: _h_turn(s, _plus1(a), f, m),
    0x65b9: lambda s, a, f, m: _h_turn_to(s, _plus1(a), f, m),
    0x65bd: lambda s, a, f, m: _h_pixel_offset(s, _plus1(a), f, m),
    0x65ba: _h_pixel_shift, 0x65bb: lambda s, a, f, m: _h_pixel_shift(s, _plus1(a), f, m),
    0x6710: _h_unit_turn,
    # 0x140178d40 / 0x1401790b0: cmd_3c18 at the actor itself (no offset), size, step (+ from frame)
    0x3c12: lambda s, a, f, m: _h_show(s, [a[0], a[1], 0, 0, 0, a[2], a[3], 0, 0, 0, 0, 0], f, m, ranged=True),
    0x3c1a: lambda s, a, f, m: _h_show(s, [a[0], a[1], 0, 0, 0, a[2], a[3], 0, a[4], 0, 0, 0], f, m, ranged=True),
    0x3c00: _h_load, 0x3c02: _h_remove, 0x3c04: _h_remove,
    0x3c10: _h_show, 0x3c18: lambda s, a, f, m: _h_show(s, a, f, m, ranged=True),
    0x3c20: lambda s, a, f, m: _h_show(s, a, f, m, attached=True),
    0x3c22: lambda s, a, f, m: _h_show(s, a, f, m, attached=True, ranged=True),
    0x3c40: _h_fx_scale, 0x3c42: lambda s, a, f, m: _h_fx_scale(s, a, f, m, True),
    # 3c44 = 3c48 without the easing: percent OF the current size (0x14017a220 reads the slot's size +0x2c8)
    0x3c44: lambda s, a, f, m: _h_fx_scale_by(s, a, f, m, eased=False), 0x3c48: _h_fx_scale_by,
    0x3cb8: _h_fx_nscale, 0x3cba: lambda s, a, f, m: _h_fx_nscale(s, a, f, m, True),
    0x3c64: _h_fx_rot_to, 0x3c66: lambda s, a, f, m: _h_fx_rot_to(s, a, f, m, eased=True),
    0x3c68: _h_fx_rot_by, 0x3c6a: lambda s, a, f, m: _h_fx_rot_by(s, a, f, m, eased=True),
    0x3c70: lambda s, a, f, m: _h_fx_rot_to(s, a, f, m, "rot2"),
    0x3c72: lambda s, a, f, m: _h_fx_rot_to(s, a, f, m, "rot2", True),
    0x3c74: lambda s, a, f, m: _h_fx_rot_by(s, a, f, m, "rot2"),
    0x3c76: lambda s, a, f, m: _h_fx_rot_by(s, a, f, m, "rot2", True),
    0x3c78: _h_fx_order,
    0x3c80: _h_fx_color, 0x3c88: lambda s, a, f, m: _h_fx_color(s, a, f, m, True),
    0x3cda: _h_fx_alpha, 0x3cdc: lambda s, a, f, m: _h_fx_alpha(s, a, f, m, True),
    0x3ca0: _h_fx_zbias, 0x3cde: _h_fx_queue, 0x3c9a: _h_fx_drawn, 0x3ca5: _h_fx_face_cam,
    0x3c90: _h_fx_step, 0x3cc6: _h_fx_frame,
    0x3c30: _h_fx_layer, 0x3cd6: _h_fx_blend, 0x3cd8: _h_fx_billboard,
    0x4140: _h_fx_move, 0x4170: lambda s, a, f, m: _h_fx_move(s, a, f, m, True),
}
SIMULATED = set(_HANDLERS)


# ------------------------------------------------------------------------------------------------ the simulator
# ---- mirroring (2026-10-10, disgaea5.exe): skills mirror themselves for facings 1 / 2 (cmd_72f0 1: 1266 vanilla uses)
# instead of being written twice.  Each command family reads one byte of the skill's context and then negates the
# sideways values -- a reflection across the skill's own forward / up plane (handlers 0x140167060, 0x14017a760 ...)
MIRROR_SET = {0x72f0: None, 0x32f8: 1, 0x3cd0: 2, 0x3cd2: 3, 0x3cd4: 4, 0x44f0: 5, 0x65f0: 6, 0x67f0: 7, 0x66f0: 8,
              0x6880: 9, 0x6c80: 10, 0x66f8: 11}
MIRROR_ARGS = {}                         # command -> (switch, operand indices negated)
for _c in (0x3210, 0x3220):
    MIRROR_ARGS[_c] = (1, (1,))          # camera aim: x offset
for _c in (0x3260, 0x3280):
    MIRROR_ARGS[_c] = (0, (2, 3))        # camera turns: yaw, roll
for _c in (0x3c64, 0x3c66, 0x3c68, 0x3c6a, 0x3c70, 0x3c72, 0x3c74, 0x3c76):
    MIRROR_ARGS[_c] = (2, (3, 4))        # effect turns: ry, rz
for _c in (0x3c40, 0x3c42):
    MIRROR_ARGS[_c] = (3, (2,))          # effect size: x (the model is drawn mirrored)
for _c in (0x3c10, 0x3c18, 0x3c20, 0x3c22, 0x3c24, 0x4140, 0x4170, 0x4180, 0x41a0, 0x41a1):
    MIRROR_ARGS[_c] = (4, (2,))          # effect show / flights: x offset
MIRROR_ARGS[0x6500] = (6, (1,))          # actor animation: drawn mirrored
for _c in (0x65b4, 0x65b5, 0x65b6, 0x65b8, 0x65b9, 0x65c1):
    MIRROR_ARGS[_c] = (6, (4,))          # sprite turn / offset
for _c in (0x65ba, 0x65bb, 0x65bc, 0x65bd):
    MIRROR_ARGS[_c] = (6, (2,))
for _c in (0x6642, 0x6650, 0x6672, 0x6674, 0x6678, 0x6680, 0x66b0):
    MIRROR_ARGS[_c] = (11, (2,))         # unit moves, locators: x offset
MIRROR_ARGS[0x66b8] = (11, (1,))
MIRROR_ARGS[0x6c00] = (10, (2,))
MIRROR_ARGS[0x6710] = (7, (2,))          # unit turns: degrees (0x140173ca0 reads switch 7)         # attach at an offset: x (0x140184470 reads switch 10)
SIMULATED |= set(MIRROR_SET)


class StageSim:
    """StageSim(timeline, setup, models).at(t) -> Stage after frame t (kept states make seeking cheap);
    models(effect id) -> fxmodel.FxModel or None (lengths of the models' own animations)"""

    def __init__(self, tl, setup, models=None):
        self.tl, self.setup, self.models = tl, setup, models
        self.by_frame = {}
        for op in tl.ops:
            if op.cid in _HANDLERS or op.cid in MIRROR_SET:
                self.by_frame.setdefault(op.frame, []).append(op)
        self.length = tl.length
        self._snaps = {}
        self._cur = None

    def _fresh(self):
        return Stage(self.setup)

    def at(self, t):
        t = int(max(0, min(t, self.length)))
        cur = self._cur
        if cur is None or cur.frame > t:
            k = max((f for f in self._snaps if f <= t), default=None)
            cur = copy.deepcopy(self._snaps[k]) if k is not None else self._fresh()
        while cur.frame < t:
            f = cur.frame + 1
            cur.begin_frame()
            for op in self.by_frame.get(f, ()):
                cur.apply(op, self.models)
            cur.tick(self.models)
            cur.frame = f
            if f % SNAP_EVERY == 0 and f not in self._snaps:
                self._snaps[f] = copy.deepcopy(cur)
        self._cur = cur
        return cur

    def scene(self, t):
        d = self.at(t).scene_dict()
        d["sim"] = self
        return d


# ------------------------------------------------------------------------------------------------ camera
def game_frame(p):
    """editor point(s) (script units, y up) -> the game's map frame (map units, y down)"""
    p = np.asarray(p, float)
    return p * np.array([1.0 / MAP, -1.0 / MAP, 1.0 / MAP])


class GameView:
    """the game camera of a stage: view basis, eye, projection; project() like render.Camera.project.
    viewport: (x, y, w, h) of the 16:9 picture inside the widget (letterboxed), in the widget's pixels"""

    def __init__(self, stage, aspect=16 / 9.0, viewport=None):
        c = stage.cam
        pitch, yaw, roll = (float(v) for v in c.rot.get())
        self.pitch_deg = math.degrees(pitch)
        self.yaw_deg = math.degrees(yaw)
        self.dist = float(c.dist.get()[0])
        self.lens = float(c.lens.get()[0])
        tgt = game_frame(c.target.get())
        fwd = np.array([math.cos(pitch) * math.sin(-yaw), math.sin(pitch), math.cos(pitch) * math.cos(-yaw)])
        right = np.array([math.cos(-yaw), 0.0, -math.sin(-yaw)])
        down = np.cross(fwd, right)
        if roll:
            cr, sr = math.cos(roll), math.sin(roll)
            right, down = right * cr + down * sr, down * cr - right * sr
        self.g_fwd, self.g_right, self.g_down = fwd, right, down        # the game's frame (y down)
        sh, sv = getattr(c, "shake_hv", (0.0, 0.0))
        if sh or sv:                                                      # cmd_32a0: the whole camera shifts
            tgt = tgt + np.array([math.cos(-yaw), 0.0, -math.sin(-yaw)]) * sh + np.array([0.0, sv, 0.0])
        self.eye = tgt - fwd * self.dist
        self.target = tgt
        self.aspect = aspect
        self.p11 = lens_p11(self.lens)
        self.p00 = self.p11 / aspect
        self.viewport = viewport
        # like render.Camera (the editor frame, y up): right, up, fwd (toward the viewer), scale px per unit
        flip = np.array([1.0, -1.0, 1.0])
        self.right = right * flip
        self.up = -down * flip
        self.fwd = -fwd * flip
        self.R = np.array([self.right, self.up, self.fwd])
        self.focus = c.target.get()
        self.pitch = self.pitch_deg
        self.yaw = self.yaw_deg
        self.pan = np.zeros(2)
        vh = viewport[3] if viewport else 396.0
        self.scale = self.p11 * (vh / 2.0) / max(1e-6, self.dist) / MAP

    def unproject_delta(self, dx, dy):
        """screen movement (pixels) -> world movement in the view plane at the target's distance"""
        return (self.right * dx - self.up * dy) / self.scale

    def update(self):
        pass

    def camera_space(self, p_editor):
        g = game_frame(p_editor) - self.eye
        return np.c_[g @ self.g_right, g @ self.g_down, g @ self.g_fwd]

    def project(self, p, w, h):
        """(n, 3) editor points -> (n, 2) pixels in a w x h image, (n,) depth (bigger = nearer, like render.Camera)"""
        v = self.camera_space(np.atleast_2d(p))
        z = np.maximum(v[:, 2], 1e-3)
        x0, y0, vw, vh = self.viewport if self.viewport else (0.0, 0.0, w, h)
        x = x0 + vw / 2.0 + v[:, 0] * self.p00 / z * (vw / 2.0)
        y = y0 + vh / 2.0 + v[:, 1] * self.p11 / z * (vh / 2.0)
        return np.c_[x, y], -v[:, 2]

    def px_per_unit(self, h):
        """screen pixels per script unit at the target's distance"""
        return self.p11 * (h / 2.0) / self.dist / MAP

    def matrix(self, near=1.0):
        """4x4 clip matrix of editor points (row-major numpy; transpose for OpenGL)"""
        S = np.diag([1.0 / MAP, -1.0 / MAP, 1.0 / MAP, 1.0])
        V = np.eye(4)
        V[0, :3], V[1, :3], V[2, :3] = self.g_right, self.g_down, self.g_fwd
        V[:3, 3] = -V[:3, :3] @ self.eye
        far = FAR_PLANE
        P = np.zeros((4, 4))
        P[0, 0] = self.p00
        P[1, 1] = -self.p11                     # camera y points down; clip y up
        P[2, 2] = (far + near) / (far - near)
        P[2, 3] = -2.0 * far * near / (far - near)
        P[3, 2] = 1.0
        return P @ V @ S
