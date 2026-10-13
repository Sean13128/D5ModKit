"""Effect models (Effect.dat effectNNNN.obf) prepared for drawing in the kit's skill preview.

What is used of the .obf (d5lib/obf.py):
  * parts (section 6: u32 n, 24 bytes, n mesh indices) -> triangles with their texture and uv
  * textures (LA88 ones: layer 0, the main picture; the other layers are softened copies)
  * the model's own animation (d5lib/fxanim.py): nodes that draw a part with their own move / turn / size / fade
    keys (flipbooks are nodes fading in and out in turn)
Units: model units are map units (1 panel = 12); script positions are tenths of them, so the preview draws the
model x 10 x size / 1000.
"""
import struct
from dataclasses import dataclass, field
from typing import List

import numpy as np

from . import fxanim, obf, skills

FRAME_TICKS = 3
MODEL_TO_SCRIPT = 10.0


@dataclass
class Part:
    tris: np.ndarray            # (n, 3, 3) positions
    uvs: np.ndarray             # (n, 3, 2)
    tex: int
    color: tuple = (1.0, 1.0, 1.0, 1.0)
    additive: bool = None       # mesh flags byte 0: 1 alpha blending, 2 / 3 adding light (None: guess by texture)


@dataclass
class Tex:
    rgba: np.ndarray            # (h * layers, w, 4) uint8
    w: int
    h: int
    layers: int
    additive: bool


@dataclass
class FxModel:
    id: int
    parts: List[Part]           # section 6 order (a node's part index points here)
    textures: List[Tex]
    groups: List[List[int]]     # without animation data: parts drawn together, several = a flipbook (guess)
    flat: bool                  # every vertex has z = 0: a picture facing the camera
    lo: np.ndarray = field(default=None)
    hi: np.ndarray = field(default=None)
    anim: object = None         # fxanim.Anim

    def draw_list(self, time, speed=100):
        """[(part index, 4x4 model matrix or None, alpha)] drawn `time` frames after the effect was shown"""
        t = max(0.0, time) * max(speed, 0) / 100.0
        if self.anim is not None and self.anim.nodes:
            return [(p, m, a) for p, m, a in self.anim.pose(t) if p < len(self.parts) and len(self.parts[p].tris)]
        step = int(t / FRAME_TICKS)
        out = []
        for g in self.groups:
            out.append((g[step % len(g)] if len(g) > 1 else g[0], None, 1.0))
        return out

    def best_frame(self):
        """a frame that shows the most of the effect (for thumbnails)"""
        if self.anim is None or not self.anim.length:
            return 6
        best, bt = -1.0, 0
        for t in range(0, self.anim.length + 1, max(1, self.anim.length // 20)):
            v = sum(a for _, _, a in self.anim.pose(t))
            if v > best + 1e-6:
                best, bt = v, t
        return bt


def _texture(t):
    try:
        img = t.to_image()
    except ValueError:
        return Tex(np.full((4, 4, 4), 255, np.uint8), 4, 4, 1, True)
    a = np.asarray(img.convert("RGBA"), np.uint8)
    layers = t.layers if t.fmt == obf.FMT_LA else 1
    additive = t.fmt == obf.FMT_LA or skills.is_additive(t)
    return Tex(a, t.width, t.height, layers, additive)


def build(o, eid=0):
    v = o.vertices()
    meshes = o.meshes
    try:
        tables = obf.read_table(o.sections[6])
        lists = []
        for p in tables:
            n = struct.unpack_from("<I", p)[0]
            lists.append(list(struct.unpack_from(f"<{n}I", p, 28)))
        if sum(len(x) for x in lists) != len(meshes):
            raise ValueError
    except (ValueError, struct.error):
        lists = [[k] for k in range(len(meshes))]
    parts = []
    for ml in lists:
        tris, uvs, tex, cols, blends = [], [], None, [], []
        for k in ml:
            if k >= len(meshes):
                continue
            m = meshes[k]
            idx = m.indices.astype(np.int64)
            idx = idx[:len(idx) // 3 * 3]
            if not len(idx) or idx.max() >= len(v):
                continue
            tris.append(v[idx, 0:3].reshape(-1, 3, 3))
            uvs.append(v[idx, 13:15].reshape(-1, 3, 2))
            cols.append(v[idx, 9:13].mean(0) * 2.0 * np.array(m.color, float) / 255.0)
            tex = m.texture_index if tex is None else tex
            blends.append(m.flags[0])
        if tris:
            parts.append(Part(np.concatenate(tris).astype(np.float32), np.concatenate(uvs).astype(np.float32),
                              tex or 0, tuple(np.clip(np.mean(cols, 0), 0, 2).tolist()),
                              (blends[0] != 1) if blends else None))
        else:                                       # keep the numbering: nodes name parts by index
            parts.append(Part(np.zeros((0, 3, 3), np.float32), np.zeros((0, 3, 2), np.float32), 0))
    textures = [_texture(t) for t in o.textures]
    # flipbooks: same texture, same place
    groups, seen = [], {}
    for i, p in enumerate(parts):
        if not len(p.tris):
            continue
        key = (p.tex, tuple(np.round(np.sort(p.tris.reshape(-1, 3), axis=0), 1).reshape(-1).tolist()))
        if key in seen:
            groups[seen[key]].append(i)
        else:
            seen[key] = len(groups)
            groups.append([i])
    allp = np.concatenate([p.tris.reshape(-1, 3) for p in parts if len(p.tris)] or [np.zeros((1, 3), np.float32)])
    lo, hi = allp.min(0), allp.max(0)
    try:
        anim = fxanim.read(o)
    except Exception:
        anim = None
    m = FxModel(int(eid), parts, textures, groups, bool(hi[2] - lo[2] < 1e-3), lo, hi, anim)
    if anim is not None and anim.nodes:     # the extent the animation really reaches
        pts = []
        for t in range(0, anim.length + 1, max(1, anim.length // 12)):
            for pi, mat, a in m.draw_list(t):
                v = parts[pi].tris.reshape(-1, 3)
                pts.append(v @ mat[:3, :3].T + mat[:3, 3])
        if pts:
            allp = np.concatenate(pts)
            m.lo, m.hi = allp.min(0), allp.max(0)
    return m


_cache = {}


def load(get, eid, members=None, mods=()):
    """FxModel of effect `eid` (vanilla or a mod's new one), cached; None if there is no such effect"""
    key = (int(eid), tuple(m.id for m in mods))
    if key not in _cache:
        o = skills.effect_model(get, int(eid), members, mods)
        _cache[key] = build(o, eid) if o is not None else None
    return _cache[key]


def clear_cache():
    _cache.clear()
