"""Presets: ready-made building blocks for skill choreographies (movement, camera, screen, hits, effect motion).

Each preset turns a few plain values (frames, distance, height ...) into script commands the way the game's own
skills write them (patterns taken from the vanilla choreographies, commands as traced in disgaea5.exe -- see
data/choreo_commands.json).  The skill editor adds them as a new layer at the playhead (choreo.Edit.add_layer), so
they can be moved, retimed and changed afterwards like everything else.

Offsets are in the skill's own frame (x sideways, y up, z forward = from the caster toward the target); the game
turns them with the caster's facing.  120 = one panel."""
from dataclasses import dataclass, field

from . import choreo, script

I, W = choreo.ins, choreo.WAIT
CASTER, TARGET = choreo.CASTER, choreo.TARGET
ALL_TARGETS = 3603                      # cmd_7220 3603: every area target


@dataclass
class Param:
    name: str
    label: str
    default: float
    lo: float = 0
    hi: float = 999
    step: float = 1
    kind: str = "int"                   # int | actor
    tip: str = ""


@dataclass
class Preset:
    key: str
    group: str
    name: str
    desc: str
    params: list = field(default_factory=list)
    build: object = None                # build(values: dict, ctx: dict) -> [script.Ins]
    needs_effect: bool = False          # works on the selected effect clip (ctx: slot, actor, pos)


def wait(n):
    return script.Ins(W, [int(n)])


def _actor_param(default=CASTER, label="Who"):
    return Param("who", label, default, kind="actor", tip="The character it is done to")


# ------------------------------------------------------------------------------------------------ movement
def _dash(v, c):
    a, back = int(v["who"]), int(v["frames_back"])
    out = [I("cmd_6672", a, TARGET, 0, 0, -int(v["stop"]), int(v["frames"]), 0, -200, 1),
           wait(int(v["frames"]) + int(v["hold"]))]
    if back > 0:
        out.append(I("cmd_6672", a, a, 0, 0, 0, back, 0, -200, 1))      # plain id: where it stood at the start
    return out


def _leap(v, c):
    a = int(v["who"])
    return [I("cmd_6680", a, TARGET, 0, 0, -int(v["stop"]), int(v["frames"]), 2, -100, -10, 1)]


def _rise(v, c):
    a = int(v["who"])
    out = [I("cmd_6672", a, a, 0, int(v["height"]), 0, int(v["frames"]), 0, -200, 1)]
    if int(v["hold"]) >= 0 and int(v["frames_down"]) > 0:
        out += [wait(int(v["frames"]) + int(v["hold"])), I("cmd_6672", a, a, 0, 0, 0, int(v["frames_down"]), 0, 200, 1)]
    return out


def _teleport(v, c):
    a = int(v["who"])
    return [I("cmd_6482", a, 0, int(v["fade"])), wait(int(v["fade"]) + int(v["gap"])),
            I("cmd_6642", a, TARGET, 0, 0, int(v["side"]), 0, 0), I("cmd_6482", a, 100, int(v["fade"]))]


def _step_back(v, c):
    a = int(v["who"])
    return [I("cmd_6672", a, a, 0, 0, -int(v["distance"]), int(v["frames"]), 0, -200, 1)]


def _knockback(v, c):
    a = int(v["who"])
    return [I("cmd_6680", a, a, 0, 0, int(v["distance"]), int(v["frames"]), 2, -100, -10, 1)]


def _go_back(v, c):
    a = int(v["who"])
    return [I("cmd_6672", a, a, 0, 0, 0, int(v["frames"]), 0, -200, 1)]


def _pose(v, c):
    return [I("cmd_6510", int(v["who"]), int(v["motion"]), 10)]


# ------------------------------------------------------------------------------------------------ camera
def _close_up(v, c):
    f = int(v["frames"])
    return [I("cmd_3220", int(v["who"]), 0, int(v["height"]), 0, f, -200, 1),
            I("cmd_3240", f, int(v["zoom"]), -200, 1)]


def _swing(v, c):
    return [I("cmd_3280", int(v["frames"]), 0, int(v["angle"]), 0, -100, 1)]


def _low_angle(v, c):
    return [I("cmd_3268", int(v["frames"]), int(v["tilt"]), 0, 0)]


def _battle_view(v, c):
    f = int(v["frames"])
    return [I("cmd_3220", CASTER, 0, 0, 0, f, -200, 1), I("cmd_3290", f), I("cmd_3240", f, 700, -200, 1)]


def _shake(v, c):
    return [I("cmd_32a0", int(v["side"]), int(v["updown"]), int(v["frames"]))]


def _quake(v, c):
    s, u = int(v["side"]), int(v["updown"])
    out = []
    for k in range(int(v["steps"])):
        if k:
            out.append(wait(2))
        out.append(I("cmd_32a0", s >> k, u >> k, 2))
    return out


# ------------------------------------------------------------------------------------------------ screen
def _fade_black(v, c):
    return [I("screen_fade", 127, int(v["frames"])), wait(int(v["frames"]) + int(v["hold"])),
            I("screen_fade", 0, int(v["frames_back"]))]


def _white_flash(v, c):
    return [I("screen_fade", 129, 0), wait(int(v["hold"])), I("screen_fade", 0, int(v["frames"]))]


def _darken(v, c):
    d = int(v["level"])
    return [I("cmd_2820", d, d, d + 10, 100, int(v["frames"])), wait(int(v["frames"]) + int(v["hold"])),
            I("cmd_2820", 100, 100, 100, 100, int(v["frames"]))]


def _void(v, c):
    f = int(v["frames"])
    return [I("cmd_2834", f, 6, 6, 16), I("cmd_2820", 100, 100, 100, 0, f), wait(f + int(v["hold"])),
            I("cmd_2820", 100, 100, 100, 100, f), I("cmd_2835", f)]


# ------------------------------------------------------------------------------------------------ hits
def _hit(v, c):
    who = int(v["who"])
    t = ALL_TARGETS if who == ALL_TARGETS else who
    out = [I("cmd_7220", t, t, int(v["percent"]))]
    if who != ALL_TARGETS:
        out.append(I("cmd_6510", who, 106, 20))
    if int(v["shake"]):
        out.append(I("cmd_32a0", 0, int(v["shake"]), 6))
    return out


def _multi_hit(v, c):
    n = max(1, int(v["hits"]))
    each = max(1, int(v["percent"]) // n)
    out = []
    for k in range(n):
        if k:
            out.append(wait(int(v["gap"])))
        out.append(I("cmd_7220", ALL_TARGETS, ALL_TARGETS, each))
        out.append(I("cmd_32a0", 0, int(v["shake"]), 4))
    return out


# ------------------------------------------------------------------------------------------------ effect motion
def _pop_in(v, c):
    s, f = c["slot"], int(v["frames"])
    big = int(v["overshoot"])
    return [I("cmd_3c40", s, 0, 0, 0, 0), I("cmd_3c42", s, f, big, big, big, -200, 1), wait(f),
            I("cmd_3c40", s, max(1, f // 2), 100, 100, 100)]


def _fade_in(v, c):
    return [I("cmd_3cda", c["slot"], 0, 0), I("cmd_3cda", c["slot"], int(v["frames"]), 100)]


def _fade_out(v, c):
    return [I("cmd_3cda", c["slot"], int(v["frames"]), 0)]


def _grow(v, c):
    k = int(v["size"])
    return [I("cmd_3c42", c["slot"], int(v["frames"]), k, k, k, -200, 1)]


def _pulse(v, c):
    s, f, k = c["slot"], int(v["frames"]), int(v["size"])
    out = []
    for i in range(int(v["times"])):
        if i:
            out.append(wait(f))
        out += [I("cmd_3c40", s, f // 2 or 1, k, k, k), wait(f // 2 or 1), I("cmd_3c40", s, f - (f // 2) or 1, 100, 100, 100)]
    return out


def _spin(v, c):
    return [I("cmd_3c68", c["slot"], int(v["frames"]), 0, int(v["turns"]) * 360, 0)]


def _rise_fade(v, c):
    s, f = c["slot"], int(v["frames"])
    x, y, z = (int(q) for q in c.get("pos", (0, 0, 0)))
    return [I("cmd_4140", s, int(c.get("actor", CASTER)), x, y + int(v["rise"]), z, f, 0), I("cmd_3cda", s, f, 0)]


# ------------------------------------------------------------------------------------------------ the list
def _p(name, label, default, lo=0, hi=999, step=1, tip=""):
    return Param(name, label, default, lo, hi, step, "int", tip)


FR = "frames (60 = 1 second)"
PRESETS = [
    # movement
    Preset("dash", "Movement", "Dash to the target and back",
           "Runs up to the target (stopping a little before it), waits, then dashes back to where it started.",
           [_actor_param(), _p("frames", "Dash time", 12, 1, 240, tip=FR), _p("stop", "Stop before the target", 80, 0, 600,
                                                                            5, "120 = one panel"),
            _p("hold", "Wait there", 20, 0, 600, tip=FR), _p("frames_back", "Way back (0 = stay)", 14, 0, 240, tip=FR)],
           _dash),
    Preset("leap", "Movement", "Leap at the target", "Jumps in an arc and lands in front of the target.",
           [_actor_param(), _p("frames", "Jump time", 20, 1, 240, tip=FR), _p("stop", "Land before the target", 60, 0,
                                                                              600, 5, "120 = one panel")], _leap),
    Preset("rise", "Movement", "Rise into the air (and come down)",
           "Floats straight up, waits, and comes back down (Way down 0: stays up).",
           [_actor_param(), _p("height", "Height", 240, 10, 3000, 10, "120 = one panel"),
            _p("frames", "Rise time", 20, 1, 240, tip=FR), _p("hold", "Wait up there", 30, 0, 600, tip=FR),
            _p("frames_down", "Way down (0 = stay up)", 12, 0, 240, tip=FR)], _rise),
    Preset("teleport", "Movement", "Vanish and appear by the target",
           "Fades out, reappears next to the target (beside it or behind it) and fades back in.",
           [_actor_param(), _p("fade", "Fade time", 4, 0, 60, tip=FR), _p("gap", "Gone for", 6, 0, 120, tip=FR),
            _p("side", "Place (minus = in front, plus = behind)", -80, -600, 600, 10, "120 = one panel")], _teleport),
    Preset("step_back", "Movement", "Step back", "Hops back a bit (away from the target).",
           [_actor_param(), _p("distance", "Distance", 60, 0, 600, 5, "120 = one panel"),
            _p("frames", "Time", 10, 1, 120, tip=FR)], _step_back),
    Preset("knockback", "Movement", "Knock back", "Pushes a character away from the caster in a small arc.",
           [_actor_param(TARGET), _p("distance", "Distance", 120, 0, 1200, 10, "120 = one panel"),
            _p("frames", "Time", 14, 1, 120, tip=FR)], _knockback),
    Preset("go_back", "Movement", "Back to the start", "Moves back to where it stood when the skill began.",
           [_actor_param(), _p("frames", "Time", 12, 0, 240, tip=FR)], _go_back),
    Preset("pose", "Movement", "Pose", "Plays one of the character's motions (100 ready, 109 cast, 151 cast "
           "release, 106 hurt, 400 damaged ...).",
           [_actor_param(), _p("motion", "Motion", 109, 0, 9999)], _pose),
    # camera
    Preset("close_up", "Camera", "Close-up", "Turns the camera onto someone and zooms in (700 = the normal view).",
           [_actor_param(TARGET, "On"), _p("zoom", "Distance (smaller = closer)", 350, 50, 3000, 10),
            _p("height", "Look at height", 40, -400, 600, 5), _p("frames", "Time", 20, 0, 240, tip=FR)], _close_up),
    Preset("swing", "Camera", "Swing around", "The camera circles around the scene by an angle.",
           [_p("angle", "Angle (degrees)", 90, -360, 360, 5), _p("frames", "Time", 30, 1, 480, tip=FR)], _swing),
    Preset("low_angle", "Camera", "Low angle", "The camera drops lower and looks up (0 = the battle view's angle).",
           [_p("tilt", "Lower by (degrees)", 15, -60, 30), _p("frames", "Time", 20, 0, 240, tip=FR)], _low_angle),
    Preset("battle_view", "Camera", "Back to the battle view", "Camera back on the caster with the normal angle "
           "and distance.", [_p("frames", "Time", 20, 0, 240, tip=FR)], _battle_view),
    Preset("shake", "Camera", "Shake", "A short camera shake, like the game's hits (0 / 80 for 6 frames).",
           [_p("updown", "Up-down", 80, 0, 2000, 10), _p("side", "Sideways", 0, 0, 2000, 10),
            _p("frames", "Time", 6, 1, 120, tip=FR)], _shake),
    Preset("quake", "Camera", "Quake (fading out)", "A strong shake that gets weaker (Exploding Tiger's).",
           [_p("side", "Sideways", 200, 0, 2000, 10), _p("updown", "Up-down", 80, 0, 2000, 10),
            _p("steps", "Steps", 4, 1, 8)], _quake),
    # screen
    Preset("fade_black", "Screen", "Fade to black and back", "", [
        _p("frames", "Fade time", 10, 0, 240, tip=FR), _p("hold", "Stay black", 20, 0, 600, tip=FR),
        _p("frames_back", "Back in", 10, 0, 240, tip=FR)], _fade_black),
    Preset("white_flash", "Screen", "White flash", "The screen turns white at once and clears.",
           [_p("hold", "Stay white", 2, 0, 120, tip=FR), _p("frames", "Clear in", 16, 0, 240, tip=FR)], _white_flash),
    Preset("darken", "Screen", "Darken the battlefield", "The map gets darker (the units stay lit), then back.",
           [_p("level", "Brightness %", 40, 0, 100, 5), _p("frames", "Fade time", 10, 0, 240, tip=FR),
            _p("hold", "Stay dark", 60, 0, 1200, tip=FR)], _darken),
    Preset("void", "Screen", "Into the void", "The map disappears into a dark backdrop, then comes back.",
           [_p("frames", "Fade time", 15, 0, 240, tip=FR), _p("hold", "Stay", 60, 0, 1200, tip=FR)], _void),
    # hits
    Preset("hit", "Hits", "Hit", "Deals a share of the skill's damage (the number shows) with a shake.",
           [Param("who", "Who", ALL_TARGETS, kind="actor", tip="Every target in the area, or one"),
            _p("percent", "Damage %", 100, 1, 1000, 5, "Share of the skill's damage"),
            _p("shake", "Shake", 80, 0, 2000, 10)], _hit),
    Preset("multi_hit", "Hits", "Several hits", "The damage split into quick hits on every target.",
           [_p("hits", "Hits", 5, 1, 30), _p("percent", "Damage % in all", 100, 1, 1000, 5),
            _p("gap", "Between hits", 6, 1, 120, tip=FR), _p("shake", "Shake", 40, 0, 2000, 10)], _multi_hit),
    # effect motion (the selected effect)
    Preset("pop_in", "Selected effect", "Pop in", "Grows from nothing past its size and settles.",
           [_p("frames", "Time", 8, 1, 120, tip=FR), _p("overshoot", "Biggest size %", 120, 100, 400, 5)], _pop_in,
           True),
    Preset("fade_in", "Selected effect", "Fade in", "", [_p("frames", "Time", 10, 1, 240, tip=FR)], _fade_in, True),
    Preset("fade_out", "Selected effect", "Fade out", "", [_p("frames", "Time", 10, 1, 240, tip=FR)], _fade_out,
           True),
    Preset("grow", "Selected effect", "Grow / shrink", "Changes its size smoothly (100 = as shown).",
           [_p("size", "Size %", 200, 0, 2000, 10), _p("frames", "Time", 20, 1, 480, tip=FR)], _grow, True),
    Preset("pulse", "Selected effect", "Pulse", "Throbs bigger and back a few times.",
           [_p("size", "Size %", 130, 0, 1000, 5), _p("frames", "One beat", 12, 2, 120, tip=FR),
            _p("times", "Beats", 3, 1, 20)], _pulse, True),
    Preset("spin", "Selected effect", "Spin", "Turns around the vertical axis.",
           [_p("turns", "Turns (minus = the other way)", 1, -20, 20), _p("frames", "Time", 30, 1, 960, tip=FR)],
           _spin, True),
    Preset("rise_fade", "Selected effect", "Rise and fade", "Floats up while it fades out.",
           [_p("rise", "Rise", 80, -600, 1200, 5, "120 = one panel"), _p("frames", "Time", 20, 1, 480, tip=FR)],
           _rise_fade, True),
]
BY_KEY = {p.key: p for p in PRESETS}
GROUP_ORDER = ["Movement", "Camera", "Screen", "Hits", "Selected effect"]


def defaults(preset):
    return {p.name: p.default for p in preset.params}


def build(key, values=None, ctx=None):
    """the script lines of a preset (values: its parameters; missing ones use the defaults)"""
    pr = BY_KEY[key]
    v = defaults(pr)
    v.update(values or {})
    return pr.build(v, ctx or {})
