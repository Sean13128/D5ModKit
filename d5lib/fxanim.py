"""The own animation of effect models (Effect.dat effectNNNN.obf, sections 2-5): read, evaluate, write.

Layout (found 2026-10-08; obf offset tables as in obf.py):
  section 2  table, 1 entry: u32 node count, u32 length (frames), u32 0, u32 0, u32 loop (0 once, 1 loop, 2 ?),
             u32 0, u32 0, then node count x u32 node order (0..n-1)
  section 3  table of NODES: i32 part (section 6 index it draws, -1 = none), i16 parent node (-1 = root),
             u8 1, u8 1, u32 n, n x u32 KEY index (section 4).  Several nodes can draw the same part (sparks).
  section 4  KEYS, 10 x u32 each: the curve point (section 5) of every channel at this key:
             0-2 translate x y z (model units), 3-5 rotate x y z (radians), 6-8 scale x y z, 9 alpha
  section 5  CURVE POINTS, 16 bytes each: f32 value, u32 (type << 24 | frame), f32 tangent in, f32 tangent out.
             type 3 = smooth (Hermite; tangents per segment), 0 = straight line, 4 = hold (step), 1 / 5 rare.
A channel of a node = the points of its keys, in key order (a constant channel repeats one point at frame 0).
The node's matrix = parent matrix x translate x rotate (z * y * x) x scale; alpha multiplies down the tree.

Examples: effect 1418 (magic circle) spins 0 -> 90 -> 120 degrees about y, grows 0 -> 0.8 -> 1.05 and fades in at 15 /
out at 95-120 frames; effect 106 (fire puff) is 4 nodes whose alpha keys show its 4 flame pictures in turn.
"""
import math
import os
import struct
from dataclasses import dataclass, field
from typing import List

import numpy as np

from . import obf

CHANNELS = ("tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz", "alpha")
SMOOTH, LINEAR, HOLD = 3, 0, 4


@dataclass
class Point:
    value: float
    type: int
    frame: int
    tin: float = 0.0
    tout: float = 0.0

    def pack(self):
        return struct.pack("<fIff", self.value, (self.type & 0xFF) << 24 | (self.frame & 0xFFFFFF), self.tin,
                           self.tout)


@dataclass
class Node:
    part: int
    parent: int
    key_ids: List[int]                    # indices into Anim.keys
    flags: bytes = b"\x01\x01"


@dataclass
class Anim:
    length: int
    loop: int
    nodes: List[Node]
    keys: List[List[int]]                 # per key: 10 point indices (one per channel)
    points: List[Point]
    order: List[int] = field(default_factory=list)
    head: tuple = (0, 0, 0, 0)            # the u32s of section 2 we don't know (kept)

    # ---------------------------------------------------------------- evaluation
    def channel(self, node, c):
        """[(frame, Point)] of channel c of a node, in key order, frames increasing"""
        out = []
        for ki in node.key_ids:
            k = self.keys[ki] if ki < len(self.keys) else [0] * 10
            p = self.points[k[c]] if k[c] < len(self.points) else Point(0.0, HOLD, 0)
            if out and p.frame <= out[-1][0]:
                if p.frame == out[-1][0]:
                    out[-1] = (p.frame, p)
                continue
            out.append((p.frame, p))
        return out

    def prepare(self):
        """per node, per channel: arrays for fast evaluation"""
        self._ch = []
        for n in self.nodes:
            chs = []
            for c in range(10):
                pts = self.channel(n, c)
                if not pts:
                    pts = [(0, Point(1.0 if c >= 6 else 0.0, HOLD, 0))]
                chs.append(([f for f, _ in pts], [p for _, p in pts]))
            self._ch.append(chs)
        self._cache = {}

    def frame_of(self, t):
        if self.length > 0:
            if self.loop == 1:
                return t % self.length
            return min(t, self.length)
        return t

    def values(self, ni, t):
        """the 10 channel values of node ni at frame t"""
        out = []
        for frames, pts in self._ch[ni]:
            if t <= frames[0] or len(frames) == 1:
                out.append(pts[0].value)
                continue
            if t >= frames[-1]:
                out.append(pts[-1].value)
                continue
            j = 0
            while frames[j + 1] <= t:
                j += 1
            a, b = pts[j], pts[j + 1]
            s = (t - frames[j]) / float(frames[j + 1] - frames[j])
            if a.type == HOLD:
                v = a.value
            elif a.type == SMOOTH:
                s2, s3 = s * s, s * s * s
                v = ((2 * s3 - 3 * s2 + 1) * a.value + (s3 - 2 * s2 + s) * a.tout +
                     (-2 * s3 + 3 * s2) * b.value + (s3 - s2) * b.tin)
            else:
                v = a.value + (b.value - a.value) * s
            out.append(v)
        return out

    def pose(self, t):
        """[(part, 4x4 matrix in model units, alpha)] drawn at frame t (cached per whole frame)"""
        f = self.frame_of(int(t))
        hit = self._cache.get(f)
        if hit is not None:
            return hit
        mats, alphas = [None] * len(self.nodes), [None] * len(self.nodes)

        def world(i, depth=0):
            if mats[i] is not None:
                return mats[i], alphas[i]
            v = self.values(i, f)
            m = _trs(v)
            a = v[9]
            p = self.nodes[i].parent
            if 0 <= p < len(self.nodes) and p != i and depth < 32:
                pm, pa = world(p, depth + 1)
                m = pm @ m
                a = a * pa
            mats[i], alphas[i] = m, a
            return m, a
        out = []
        for i, n in enumerate(self.nodes):
            m, a = world(i)
            if n.part >= 0 and a > 0.004:
                out.append((n.part, m, min(1.0, a)))
        if len(self._cache) > 2000:
            self._cache.clear()
        self._cache[f] = out
        return out

    # ---------------------------------------------------------------- writing
    def sections(self):
        """(section 2, 3, 4, 5) bytes"""
        n = len(self.nodes)
        order = self.order if len(self.order) == n else list(range(n))
        s2 = obf.build_table([struct.pack("<7I", n, self.length, self.head[0], self.head[1], self.loop,
                                          self.head[2], self.head[3]) + struct.pack(f"<{n}I", *order)])
        s3 = obf.build_table([struct.pack("<ih2sI", nd.part, nd.parent, nd.flags, len(nd.key_ids))
                              + struct.pack(f"<{len(nd.key_ids)}I", *nd.key_ids) for nd in self.nodes])
        s4 = b"".join(struct.pack("<10I", *k) for k in self.keys)
        s5 = b"".join(p.pack() for p in self.points)
        return s2, s3, s4, s5


# A node's matrix as the game builds it (0x1402fdca0, row vectors): size, then turns about z, x, y, then the place --
# in the game's y-down world (its places are the file's with y negated, x 10 / y -10 / z 10).  The kit draws in a y-up
# world, the game's mirrored in y, where those turns about x and z go the other way (as the script's own turns,
# glrender.FLIP_XZ).  Before 2026-10-14 the kit turned x, y, z the file's way: Hurricane Blow's tornado (504, stood up
# by a 90-degree turn about z) pointed into the ground.  D5_FX_OLD_TRS=1: the old way (for comparisons).
_OLD_TRS = os.environ.get("D5_FX_OLD_TRS", "0") == "1"


def _trs(v):
    tx, ty, tz, rx, ry, rz, sx, sy, sz = v[:9]
    if not _OLD_TRS:
        rx, rz = -rx, -rz
    cx, snx, cy, sny, cz, snz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -snx], [0, snx, cx]])
    Y = np.array([[cy, 0, sny], [0, 1, 0], [-sny, 0, cy]])
    Z = np.array([[cz, -snz, 0], [snz, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = ((Z @ Y @ X) if _OLD_TRS else (Y @ X @ Z)) * np.array([sx, sy, sz])
    m[:3, 3] = (tx, ty, tz)
    return m


def read(o):
    """Anim of an ObfFile, or None when it has none"""
    try:
        s2 = obf.read_table(o.sections[2])
        s3 = obf.read_table(o.sections[3])
    except Exception:
        return None
    if not s2 or not s3:
        return None
    n, length, h0, h1, loop, h2, h3 = struct.unpack_from("<7I", s2[0])
    order = list(struct.unpack_from(f"<{n}I", s2[0], 28)) if len(s2[0]) >= 28 + 4 * n else []
    s4, s5 = o.sections[4], o.sections[5]
    keys = [list(struct.unpack_from("<10I", s4, 40 * k)) for k in range(len(s4) // 40)]
    points = []
    for k in range(len(s5) // 16):
        v, tf, ti, to = struct.unpack_from("<fIff", s5, 16 * k)
        points.append(Point(v, tf >> 24, tf & 0xFFFFFF, ti, to))
    nodes = []
    for e in s3:
        part, parent = struct.unpack_from("<ih", e)
        flags = e[6:8]
        cnt = struct.unpack_from("<I", e, 8)[0]
        idx = struct.unpack_from(f"<{cnt}I", e, 12)
        nodes.append(Node(part, parent, list(idx), flags))
    a = Anim(length, loop, nodes, keys, points, order, (h0, h1, h2, h3))
    a.prepare()
    return a


def write(o, anim):
    """put anim into ObfFile o (sections 2-5)"""
    o.sections[2], o.sections[3], o.sections[4], o.sections[5] = anim.sections()
