"""GPU drawing of the skill preview (OpenGL 4.1 core through PyQt6): what the game shows while a skill runs,
from a d5lib.stage.Stage -- game camera, backdrop, floor, units (sprites drawn from their sheets), effect models
(with the game's blending, flipbooks, billboards, node scale), particles and the screen fade.

Everything textured lives in big atlas pages; every frame the scene is turned into one vertex stream (positions in
script units, atlas uv, colour, depth bias) and drawn in as few calls as the blend modes allow, in the game's order:
draw queues 0..11 one after the other (0x14030c320), each in the order things were drawn, except queue 6, which is
sorted back to front (0x14030b4d0): an effect piece by the depth of the middle of its first triangle plus its
cmd_3ca0 bias, a unit by the depth of its feet brought 7 map units nearer.  An effect piece goes into its mesh layer
byte + 2 (alpha pictures 4, glows 6) unless cmd_3cde says otherwise; units are in queue 6 with the effects.
Effect pieces write depth except in queue 6 (the submit 0x14030f8a0 clears the depth-write bit 0x20 of the render
state only for queue 6): solid models such as Macrocosm's planet rock (1733, layers 2 / 3) hide their own far side.
Usage (a GL context current):  r = GLRenderer(assets); r.paint(gl, w, h, stage, view)
"""
import math

import numpy as np

from d5lib import anm, choreo, fxanim, grips, obf, particles, skills, txf
from d5lib import stage as stg

GL_TEXTURE_2D, GL_RGBA, GL_RGBA8, GL_UNSIGNED_BYTE, GL_FLOAT = 0x0DE1, 0x1908, 0x8058, 0x1401, 0x1406
GL_TRIANGLES, GL_BLEND, GL_DEPTH_TEST, GL_CULL_FACE = 0x0004, 0x0BE2, 0x0B71, 0x0B44
GL_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO = 0x0302, 1, 0x0303, 0
GL_FUNC_ADD, GL_FUNC_REVERSE_SUBTRACT, GL_FUNC_SUBTRACT, GL_DST_COLOR = 0x8006, 0x800B, 0x800A, 0x0306
GL_LEQUAL, GL_LESS = 0x0203, 0x0201
GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT = 0x4000, 0x0100
GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_LINEAR = 0x2801, 0x2800, 0x2601
GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE = 0x2802, 0x2803, 0x812F
GL_ARRAY_BUFFER, GL_STREAM_DRAW, GL_TEXTURE0 = 0x8892, 0x88E0, 0x84C0
GL_SCISSOR_TEST = 0x0C11

PAGE = 4096
PAD = 2
FLOATS = 14                         # pos 3, uv 2, rect 4, colour 4, depth bias 1 (script units toward the camera)
SORTED_QUEUE = 6                    # the draw queue the game sorts back to front (0x14030ae80)
UNIT_QUEUE = 6                      # units' sprites: every sprite starts in queue 6 (sprite reset 0x1402f2680)
UNIT_NEARER = 7.0 * stg.MAP         # a unit sorts as if this much nearer than its feet (draw object +0x48 = -7 map
                                    # units in the recordings; key = anchor depth +0x54 + it, 0x1402f1e90)
AID_QUEUE = -1                      # the editor's own floor grid and area panels: under everything
SHADOW_QUEUE = 4                    # units' shadows (0x1402f3520 submits them into queue 4: under units and effects)
SHADOW_SIZE = 0.75                  # shadow radius = char.dat size_radius (map units) x this (measured in recordings)
SHADOW_ALPHA = 0.55                 # how dark its middle is (the game's shadow darkens the ground to ~45 %)
SHADOW_LIFT = 0.6                   # over the ground (script units)
MODEL_TO_SCRIPT = 10.0
SPRITE_SCALE = 1.0                  # script units per sprite pixel
BLEND_ALPHA, BLEND_ADD, BLEND_SUB, BLEND_OPAQUE = 1, 2, 3, 0
# the game's blend modes (mesh flags byte 0 / cmd_3cd6; the blend state builder 0x1403d6ba0, op bits set by
# 0x140307120): 1 alpha, 2 add, 3 screen - colour (reverse subtract), 4 multiply (colour faded to white where it is
# see-through, the pixel shader's param.w path), 5 colour - screen (subtract)
BLEND_MUL, BLEND_SUBR = 4, 5
MOTION_BASE = {109: 1050, 151: 7010}
SWAP_SCALE_ON_SIDE_FACING = False
# OPEN (2026-10-14, Hurricane Blow's recording): its tornado (504, parts stood up by their node transforms, shown with
# a non-uniform size 1.6 / 0.3 / 1.6) is a tall column in the game but a flat ring in the kit, and its model points
# down in the kit's model space while the swirl (501) rises as in the game.  Experiments, off by default until the
# game's model matrix code is traced: D5_FX_LOCAL_SCALE=1 (the size scales the parts in their own space, before
# their nodes), D5_FX_FLIP_MODEL_Y=1 (model space y-down).  Both together stand the tornado up but sink the swirl.
import os as _os
LOCAL_SCALE = _os.environ.get("D5_FX_LOCAL_SCALE", "0") == "1"
FLIP_MODEL_Y = _os.environ.get("D5_FX_FLIP_MODEL_Y", "0") == "1"
DEBUG_VERTS = None                  # dev: {slot: [vertex arrays]} of the last frames drawn when set to a dict
# effects get the skill's turn from the script root's +0x68 (offsets use +0x60): 0 for skills, it seems (Macrocosm's
# rays at frame ~1000 are seen end-on in the game)
TURN_EFFECTS_WITH_FACING = True   # 0x14018d0a0 swaps x / z scale on an odd 0x14008a5d0() -- not this facing

VS = """#version 410
layout(location=0) in vec3 pos;
layout(location=1) in vec2 uv;
layout(location=2) in vec4 rect;
layout(location=3) in vec4 col;
layout(location=4) in float zb;
uniform mat4 mvp;
uniform vec3 tocam;
out vec2 vuv; out vec4 vrect; out vec4 vcol;
void main(){
  vuv = uv; vrect = rect; vcol = col;
  vec4 c = mvp * vec4(pos, 1.0);
  if (zb != 0.0) {
    // cmd_3ca0: only the depth comes nearer (the game's z' = (z + b) / (w + b), 0x14030aba0); x / y stay
    vec4 c2 = mvp * vec4(pos + tocam * zb, 1.0);
    c = vec4(c.xy / c.w * c2.w, c2.z, c2.w);
  }
  gl_Position = c;
}
"""
FS = """#version 410
in vec2 vuv; in vec4 vrect; in vec4 vcol;
uniform sampler2D tex;
uniform float texel;
uniform vec4 tint;
uniform float mulmode;
out vec4 o;
void main(){
  vec2 sz = abs(vrect.zw);
  vec2 f = vrect.z < 0.0 ? clamp(vuv, 0.0, 1.0) : fract(vuv);
  vec2 t = vrect.xy + clamp(f * sz, vec2(texel), sz - vec2(texel));
  vec4 c = texture(tex, t) * vcol * tint;
  if (c.a < 0.003) discard;
  if (mulmode > 0.5) c.rgb = c.rgb * c.a + vec3(1.0 - c.a);      // multiply: see-through parts leave it as it is
  o = c;
}
"""


# ------------------------------------------------------------------------------------------------ atlas
class Atlas:
    """texture pages with shelf packing; add(rgba) -> (page, (u0, v0, du, dv)); upload happens in flush(gl)"""

    def __init__(self):
        self.pages = []                  # [dict(tex, shelves, pending)]
        self.entries = {}
        self.sizes = {}                  # key -> (w, h) of the picture as given
        self.white = None
        self.pbo = None                  # pixel unpack buffer the uploads go through

    def _page(self):
        p = dict(tex=None, shelves=[], y=0, pending=[])
        self.pages.append(p)
        return len(self.pages) - 1

    def add(self, key, rgba):
        hit = self.entries.get(key)
        if hit is not None:
            return hit
        rgba = np.ascontiguousarray(rgba, np.uint8)
        h, w = rgba.shape[:2]
        self.sizes[key] = (w, h)
        if w + 2 * PAD > PAGE or h + 2 * PAD > PAGE:          # too big: scaled down to fit
            from PIL import Image
            k = (PAGE - 2 * PAD) / max(w, h)
            rgba = np.asarray(Image.fromarray(rgba, "RGBA").resize((max(1, int(w * k)), max(1, int(h * k)))))
            h, w = rgba.shape[:2]
        W, H = w + 2 * PAD, h + 2 * PAD
        for pi, p in enumerate(self.pages):
            spot = self._fit(p, W, H)
            if spot is not None:
                break
        else:
            pi = self._page()
            p = self.pages[pi]
            spot = self._fit(p, W, H)
        x, y = spot
        padded = np.pad(rgba, ((PAD, PAD), (PAD, PAD), (0, 0)), mode="edge")
        p["pending"].append((x, y, padded))
        e = (pi, ((x + PAD) / PAGE, (y + PAD) / PAGE, w / PAGE, h / PAGE))
        self.entries[key] = e
        return e

    @staticmethod
    def _fit(p, W, H):
        for sh in p["shelves"]:
            if sh[1] >= H and sh[2] + W <= PAGE:
                x = sh[2]
                sh[2] += W
                return x, sh[0]
        if p["y"] + H <= PAGE:
            sh = [p["y"], H, W]
            p["shelves"].append(sh)
            p["y"] += H
            return 0, sh[0]
        return None

    def flush(self, gl):
        for p in self.pages:
            if p["tex"] is None:
                p["tex"] = gl.glGenTextures(1)
                gl.glBindTexture(GL_TEXTURE_2D, p["tex"])
                gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, PAGE, PAGE, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
                for k in (GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER):
                    gl.glTexParameteri(GL_TEXTURE_2D, k, GL_LINEAR)
                for k in (GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T):
                    gl.glTexParameteri(GL_TEXTURE_2D, k, GL_CLAMP_TO_EDGE)
            if p["pending"]:
                # through a pixel buffer: QOpenGLBuffer.allocate copies the bytes and glTexSubImage2D gets a null
                # pointer (= offset 0 into it).  PyQt's own conversion of a numpy pixel array corrupted memory
                # (random crashes in the garbage collector later; 2026-10-10)
                pbo = self._unpack_buffer()
                pbo.bind()
                gl.glBindTexture(GL_TEXTURE_2D, p["tex"])
                for x, y, a in p["pending"]:
                    a = np.ascontiguousarray(a, np.uint8)
                    if a.ndim != 3 or a.shape[2] != 4:
                        continue
                    data = a.tobytes()
                    pbo.allocate(data, len(data))
                    gl.glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, a.shape[1], a.shape[0], GL_RGBA, GL_UNSIGNED_BYTE,
                                       None)
                pbo.release()
                p["pending"] = []

    def _unpack_buffer(self):
        if getattr(self, "pbo", None) is None:
            from PyQt6.QtOpenGL import QOpenGLBuffer
            self.pbo = QOpenGLBuffer(QOpenGLBuffer.Type.PixelUnpackBuffer)
            self.pbo.create()
            self.pbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamDraw)
        return self.pbo

    def white_rect(self):
        if self.white is None:
            self.white = self.add(("white",), np.full((4, 4, 4), 255, np.uint8))
        return self.white

    def release(self, gl):
        for p in self.pages:
            if p["tex"] is not None:
                gl.glDeleteTextures(1, [p["tex"]])
        if getattr(self, "pbo", None) is not None:
            self.pbo.destroy()
            self.pbo = None
        self.pages, self.entries, self.sizes, self.white = [], {}, {}, None


# ------------------------------------------------------------------------------------------------ effect models
class MeshGPU:
    __slots__ = ("pos", "uv", "vcol", "color", "tex", "flags", "wrap", "bill", "centre")


class ModelGPU:
    """an effect model ready to draw: per part its meshes (triangles, uv, colours, texture, flags)"""

    def __init__(self, eid, o):
        self.id = eid
        self.anim = fxanim.read(o)
        self.billboard = int(self.anim.loop) if self.anim is not None else 0
        self.length = int(self.anim.length) if self.anim is not None else 0
        self.textures = o.textures
        self.tex_layers = []
        self.tex_dur = []
        for t in o.textures:
            self.tex_layers.append(t.layers if t.fmt == obf.FMT_LA else 1)
            self.tex_dur.append(t.attr[2] if len(t.attr) > 2 else 0)
        self._rgba = {}
        v = o.vertices()
        meshes = o.meshes
        try:
            tables = obf.read_table(o.sections[6])
        except Exception:
            tables = []
        parts = []
        for p in tables:
            try:
                n = int(np.frombuffer(p, "<u4", 1)[0])
                idx = list(np.frombuffer(p, "<u4", n, 28))
                bill = p[12] if len(p) > 12 else 0
            except (ValueError, IndexError):
                idx, bill = [], 0
            parts.append((idx, bill))
        if not parts:
            parts = [([k], 0) for k in range(len(meshes))]
        self.parts = []
        for ml, bill in parts:
            out = []
            for k in ml:
                if k >= len(meshes):
                    continue
                m = meshes[k]
                ix = m.indices.astype(np.int64)
                ix = ix[:len(ix) // 3 * 3]
                if not len(ix) or ix.max() >= len(v):
                    continue
                g = MeshGPU()
                g.pos = np.ascontiguousarray(v[ix, 0:3], np.float32)
                g.uv = np.ascontiguousarray(v[ix, 13:15], np.float32)
                g.vcol = np.ascontiguousarray(np.clip(v[ix, 9:13] * 2.0, 0, 2), np.float32)
                g.color = np.array(m.color, np.float32) / 255.0
                g.tex = m.texture_index
                g.flags = bytes(m.flags)
                g.wrap = bool((g.uv < -0.01).any() or (g.uv > 1.01).any())
                g.bill = bill
                g.centre = g.pos.mean(0)
                out.append(g)
            self.parts.append(out)

    def rgba(self, ti, layer):
        """RGBA of texture ti (layer of an LA88 picture)"""
        key = (ti, layer)
        a = self._rgba.get(key)
        if a is None:
            t = self.textures[ti]
            try:
                img = np.asarray(t.to_image().convert("RGBA"), np.uint8)
            except ValueError:
                img = np.full((4, 4, 4), 255, np.uint8)
            if t.fmt == obf.FMT_LA and self.tex_layers[ti] > 1:
                h = t.height
                img = img[layer * h:(layer + 1) * h]
            a = self._rgba[key] = img
        return a

    def texture_at(self, g, frame):
        """the texture a mesh shows at a model frame (flipbooks: mesh flags 3 count, 7 delay, 8 length, 2 end)"""
        base = g.tex
        count = g.flags[3] if len(g.flags) > 8 else 0
        if not count or base < 0:
            return base
        delay, total, endmode = g.flags[7], max(1, g.flags[8]), g.flags[2]
        f = int(frame)
        if f >= delay + total and endmode != 0:
            return base + count - 1 if endmode == 2 else base
        r = (f - delay) % total if f - delay > 0 else 0
        for k in range(1, count):
            ti = base + k
            if ti >= len(self.tex_dur):
                return ti - 1
            d = self.tex_dur[ti]
            if d > r:
                return ti - 1
            r -= d
        return min(base + count - 1, len(self.tex_dur) - 1)

    def pose(self, frame):
        """[(part index, 4x4, alpha)] at a model frame"""
        if self.anim is None or not self.anim.nodes:
            return [(i, None, 1.0) for i in range(len(self.parts))]
        f = min(max(0.0, frame), float(self.length)) if self.length > 0 else max(0.0, frame)
        a = self.anim
        key = int(f)
        hit = a._cache.get(("g", key))
        if hit is None:
            mats, alphas = [None] * len(a.nodes), [None] * len(a.nodes)

            def world(i, depth=0):
                if mats[i] is not None:
                    return mats[i], alphas[i]
                vals = a.values(i, key)
                m = fxanim._trs(vals)
                al = vals[9]
                pr = a.nodes[i].parent
                if 0 <= pr < len(a.nodes) and pr != i and depth < 32:
                    pm, pa = world(pr, depth + 1)
                    m = pm @ m
                    al = al * pa
                mats[i], alphas[i] = m, al
                return m, al
            hit = []
            for i, n in enumerate(a.nodes):
                m, al = world(i)
                if 0 <= n.part < len(self.parts) and al > 0.004:
                    hit.append((n.part, m, min(1.0, al)))
            if len(a._cache) > 4000:
                a._cache.clear()
            a._cache[("g", key)] = hit
        return hit


def _rot_axis(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == 0:
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == 1:
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# rotation orders (cmd_3c78): axes applied first .. last.  0 (the default) is the game's Rz * Rx * Ry
# (0x1402ffca0: roll, then pitch, then yaw -- D3D's yaw-pitch-roll); the others are not traced yet
ORDERS = [(2, 0, 1), (2, 1, 0), (0, 2, 1), (0, 1, 2), (1, 0, 2), (1, 2, 0)]


# The game builds effect matrices in its render frame, which is y-down (the camera block, 0x146A3AC00), while the
# kit draws in a y-up frame: mirroring y turns a rotation about x or z the other way and leaves y alone.  Seen on
# Macrocosm's space rings (903 turned 0 / 30 / -120: round rings around Killia in the game, flattened ellipses
# without this), 2026-10-10.
FLIP_XZ = np.array([-1.0, 1.0, -1.0])


def rot_matrix(r, order=0):
    """a script rotation (degrees: rx, ry, rz) as drawn in the kit's y-up frame"""
    r = np.asarray(r, float) * FLIP_XZ
    m = np.eye(3)
    for ax in ORDERS[int(order) % 6]:
        m = _rot_axis(ax, r[ax]) @ m
    return m


def quarter_matrix(q):
    """the game's quarter turns of a skill (stage.turn_offset) as a 3x3"""
    m = np.eye(3)
    for _ in range(q % 4):
        m = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]]) @ m
    return m


# ------------------------------------------------------------------------------------------------ assets
class Assets:
    """shared loaders: effect models, sprite files, particle pictures (CPU side; independent of GL)"""

    def __init__(self, fs, mods=(), owner_read=None, members=None):
        self.fs = fs
        self.get = fs.read
        self.mods = list(mods)
        self.members = members if members is not None else skills.effect_members(fs.read)
        self.owner_read = owner_read
        self.models = {}
        self.sprite_files = {}
        self.weapons = {}
        self.items = {}
        self.anim_info = {}
        self.particle_cells = None

    def model(self, eid):
        if eid is None:
            return None
        eid = int(eid)
        if eid not in self.models:
            try:
                o = skills.effect_model(self.get, eid, self.members, self.mods)
                self.models[eid] = ModelGPU(eid, o) if o is not None else None
            except Exception:
                self.models[eid] = None
        return self.models[eid]

    def sim_model(self, eid):
        """for stage.StageSim: something with .anim.length"""
        return self.model(eid)

    # ---- sprites
    def sprite(self, num):
        """(file, animation ids) of a battle sprite: the shared humanoid motions bound to it + its own animations"""
        return self._sprite(num)[:2]

    def _sprite(self, num):
        if num not in self.sprite_files:
            from d5lib import sprites
            vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"
            data = self.owner_read(vp) if self.owner_read else None
            raw = bound = None
            try:
                raw = anm.load(data if data else self.fs.read(sprites.sprite_vpath(self.fs, num, "EN")))
                bound = sprites.preview_file(self.fs, raw)
            except Exception:
                bound = raw
            own = {x.id for _, _, x in raw.all_animations()} if raw is not None else set()
            shared = {x.id for _, _, x in bound.all_animations()} if bound is not None and bound is not raw else set()
            self.sprite_files[num] = (bound, own | shared, raw, own, shared)
        return self.sprite_files[num]

    def file_of(self, num, aid):
        """the file holding an animation: the bound motions (shared), else the sprite's own"""
        bound, ids, raw, own, shared = self._sprite(num)
        if aid in shared:
            return bound
        return raw

    def weapon(self, wtype):
        if wtype not in self.weapons:
            try:
                self.weapons[wtype] = grips.weapon_sprite(self.fs, wtype)
            except Exception:
                self.weapons[wtype] = None
        return self.weapons[wtype]

    def anim_for(self, num, motion, back=False):
        a, ids = self.sprite(num)
        if a is None:
            return None
        base = MOTION_BASE.get(motion)
        first = [base + (7 if back else 1), base + 1] if base else []
        for cand in first + [motion * 10 + (7 if back else 1), motion * 10 + 1, 6001, 1001, 1]:
            if cand in ids:
                return cand
        return min(ids) if ids else None

    def info(self, num, aid):
        key = (num, aid)
        if key not in self.anim_info:
            a = self.file_of(num, aid)
            try:
                bi, ai = anm._resolve_anim(a, ("id", aid))
                self.anim_info[key] = anm.animation_info(a.blocks[bi], a.blocks[bi].animations[ai])
            except Exception:
                self.anim_info[key] = {}
        return self.anim_info[key]

    def chain(self, num, aid, t, depth=0):
        """(animation, time) actually shown: an animation's last control key 5 continues with another one
        (the shared motion stubs: 1501 -> the class's own 7001, 1001 -> 6001; attacks back to standing)"""
        a, ids = self.sprite(num)
        if a is None or aid not in ids or depth > 6:
            return aid, t
        key = ("chain", num, aid)
        nxt = self.anim_info.get(key)
        if nxt is None:
            nxt = (None, None)
            a = self.file_of(num, aid)
            try:
                bi, ai = anm._resolve_anim(a, ("id", aid))
                b = a.blocks[bi]
                ks = [k for k in b.node_keys(b.nodes[b.animations[ai].root]) if (k.flags & 0xFF) == 5]
                if ks:
                    k = ks[-1]
                    if 0 <= k.param < len(b.params):
                        nxt = (k.time, int(b.params[k.param]))
            except Exception:
                pass
            self.anim_info[key] = nxt
        end, target = nxt
        if target is not None and target != aid and t >= end and target in ids:
            if self.info(num, aid).get("loop"):
                return aid, t
            return self.chain(num, target, t - end, depth + 1)
        return aid, t

    def sprite_items(self, num, aid, t, wtype=None):
        """[(file, DrawItem)] of a sprite at animation time t (loops like the game), cached per whole frame"""
        a, ids = self.sprite(num)
        if a is None or aid not in ids:
            return []
        aid, t = self.chain(num, aid, t)
        inf = self.info(num, aid)
        loop = inf.get("loop")
        length = max(1, inf.get("length", 1) or 1)
        if loop and t > loop[1] and loop[1] > loop[0]:
            t = loop[0] + (t - loop[0]) % (loop[1] - loop[0])
        t = int(max(0, min(t, length)))
        key = (num, aid, t, wtype)
        hit = self.items.get(key)
        if hit is None:
            w = self.weapon(wtype) if wtype else None
            try:
                hit = grips.evaluate(self.file_of(num, aid), aid, t, w, wtype or 16, nested=True)
            except Exception:
                hit = []
            if len(self.items) > 20000:
                self.items.clear()
            self.items[key] = hit
        return hit

    def particle_rgba(self, cell):
        if self.particle_cells is None:
            try:
                img = txf.to_image(self.get("Start/Start_JP.dat/particle.txf")).convert("RGBA")
                arr = np.asarray(img, np.uint8)
                self.particle_cells = [np.ascontiguousarray(arr[(k // 4) * 64:(k // 4 + 1) * 64,
                                                                (k % 4) * 64:(k % 4 + 1) * 64]) for k in range(16)]
            except Exception:
                self.particle_cells = []
        if not self.particle_cells:
            return None
        return self.particle_cells[cell % len(self.particle_cells)]


# ------------------------------------------------------------------------------------------------ the renderer
AREA_RGB = {1: (1.0, 0.30, 0.22), 3: (1.0, 0.62, 0.20), 2: (0.30, 0.95, 0.62)}   # hit, cursor (hit), caster ends
REACH_RGB = (0.35, 0.62, 1.0)                                                       # where the cursor can go
AREA_LIFT = 1.5                                                                      # over the ground (script units)


class Batch:
    """records of one frame: (draw queue, sort key (bigger = nearer), submission number, blend, page, vertex array
    (n, FLOATS), writes depth).  Screen-space batches use the key alone (queue 0)."""

    def __init__(self):
        self.items = []

    def add(self, key, blend, page, verts, queue=0, zwrite=False):
        if len(verts):
            self.items.append((queue, key, len(self.items), blend, page, verts, zwrite))

    def ordered(self):
        """the game's order: queue by queue; the sorted queue back to front, the others as drawn"""
        return sorted(self.items, key=lambda r: (r[0], r[1] if r[0] == SORTED_QUEUE else 0.0, r[2]))


def _quad_tris(p0, p1, p2, p3):
    """two triangles of a quad TL, TR, BR, BL -> (6, 3)"""
    return np.array([p0, p1, p2, p0, p2, p3])


class GLRenderer:
    """draws a stage; the editor sets the look options below"""

    def __init__(self, assets):
        self.assets = assets
        self.atlas = Atlas()
        self.prog = None
        self.vao = None
        self.vbo = None
        self.show_grid = True
        self.show_area = True            # the skill's panels on the ground (Setup.area / reach / cursor)
        self.hidden_slots = set()
        self.highlights = []
        self.particles = None            # particles.ParticleSim of the timeline
        self.pick = {}                   # slot -> screen box (x0, y0, x1, y1, centre) after paint
        self.weapon = None
        self.show_shadows = True
        self.shadow_sizes = {}           # sprite number -> char.dat size_radius (map units; 6 when unknown)
        self.stats = {}
        self.map = None                  # d5lib.battlemap.BattleMap drawn around the stage
        self.map_origin = np.zeros(3)    # the game-frame point of the editor's origin (the caster's panel)
        self._map_gpu = None             # (key, vao, vbo, [(first, count, page, blend)])

    def set_map(self, bm, origin):
        self.map = bm
        self.map_origin = np.array(origin, float)

    # ---------------------------------------------------------------- GL objects
    def init_gl(self, gl):
        from PyQt6.QtOpenGL import QOpenGLShaderProgram, QOpenGLShader, QOpenGLVertexArrayObject, QOpenGLBuffer
        self.prog = QOpenGLShaderProgram()
        self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VS)
        self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FS)
        if not self.prog.link():
            raise RuntimeError("preview shader: " + self.prog.log())
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.vbo.create()
        self.vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamDraw)
        self.vbo.bind()
        stride = FLOATS * 4
        for loc, n, off in ((0, 3, 0), (1, 2, 12), (2, 4, 20), (3, 4, 36), (4, 1, 52)):
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribPointer(loc, n, GL_FLOAT, False, stride, off)
        self.vao.release()
        self.loc_mvp = self.prog.uniformLocation("mvp")
        self.loc_tex = self.prog.uniformLocation("tex")
        self.loc_texel = self.prog.uniformLocation("texel")
        self.loc_tint = self.prog.uniformLocation("tint")
        self.loc_tocam = self.prog.uniformLocation("tocam")
        self.loc_mul = self.prog.uniformLocation("mulmode")

    def _map_buffers(self, gl):
        """the map's triangles (editor frame) in a static buffer of their own, uploaded once per map / place"""
        bm = self.map
        key = (bm.id, getattr(bm, "rev", 0), tuple(np.round(self.map_origin, 3)))
        if self._map_gpu is not None and self._map_gpu[0] == key:
            return self._map_gpu
        from PyQt6.QtOpenGL import QOpenGLVertexArrayObject, QOpenGLBuffer
        if self._map_gpu is None:
            vao = QOpenGLVertexArrayObject()
            vao.create()
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            vbo.create()
        else:
            vao, vbo = self._map_gpu[1], self._map_gpu[2]
        o = self.map_origin
        parts, ranges, first = [], [], 0
        for m in bm.meshes:
            world = m["pos"] * np.array([1.0, -1.0, 1.0])          # the terrain is stored y up, the world is y down
            e = (world - o) * np.array([stg.MAP, -stg.MAP, stg.MAP])
            page, rect = self.atlas.add(("map", bm.id, getattr(bm, "rev", 0), m["tex"]), _MapLazy(bm, m["tex"]))
            n = len(e)
            parts.append(self._verts(e, m["uv"], np.tile((rect[0], rect[1], -rect[2], rect[3]), (n, 1)),
                                     m["vcol"] * m["color"]))
            ranges.append((first, n, page, m["flags"][0] if m["flags"] else 1))
            first += n
        verts = np.concatenate(parts).astype(np.float32) if parts else np.zeros((0, FLOATS), np.float32)
        vao.bind()
        vbo.bind()
        vbo.allocate(verts.tobytes(), verts.nbytes)
        stride = FLOATS * 4
        for loc, n, off in ((0, 3, 0), (1, 2, 12), (2, 4, 20), (3, 4, 36), (4, 1, 52)):
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribPointer(loc, n, GL_FLOAT, False, stride, off)
        vao.release()
        self._map_gpu = (key, vao, vbo, ranges)
        return self._map_gpu

    def _draw_map(self, gl, st, M):
        mapc = st.screen.map_color.get()
        if self.map is None or mapc[3] <= 0.003:
            return
        key, vao, vbo, ranges = self._map_buffers(gl)
        self.atlas.flush(gl)
        vao.bind()
        gl.glUniformMatrix4fv(self.loc_mvp, 1, True, M.reshape(-1).tolist())
        self.prog.setUniformValue(self.loc_tint, float(min(mapc[0], 2.0)), float(min(mapc[1], 2.0)),
                                  float(min(mapc[2], 2.0)), float(min(mapc[3], 1.0)))
        gl.glEnable(GL_DEPTH_TEST)
        gl.glDepthFunc(GL_LEQUAL)
        gl.glDepthMask(True)
        for first, count, page, blend in ranges:
            self._state(gl, BLEND_ALPHA if mapc[3] < 0.999 or blend == BLEND_ALPHA else BLEND_OPAQUE, page)
            gl.glDrawArrays(GL_TRIANGLES, first, count)
        self.prog.setUniformValue(self.loc_tint, 1.0, 1.0, 1.0, 1.0)
        vao.release()
        self.vao.bind()

    def release_gl(self, gl):
        self.atlas.release(gl)
        self.prog = None

    # ---------------------------------------------------------------- vertex helpers
    def _verts(self, pos, uv, rect, col, zb=0.0):
        n = len(pos)
        v = np.empty((n, FLOATS), np.float32)
        v[:, 0:3] = pos
        v[:, 3:5] = uv
        v[:, 5:9] = rect
        v[:, 9:13] = col
        v[:, 13] = zb
        return v

    # ---------------------------------------------------------------- building a frame
    def build(self, st, view, w, h):
        """the stage as vertex records (world space) + screen-space records"""
        world, screen = Batch(), Batch()
        self.pick = {}
        cam = self._cam_axes(view)
        wr = self.atlas.white_rect()
        # backdrop: 4 corners (TL, TR, BL, BR) behind everything
        back = st.screen.back.get()
        p = np.array([[-1, 1, 0.9999], [1, 1, 0.9999], [1, -1, 0.9999], [-1, -1, 0.9999]], np.float32)
        cols = np.array([list(back[0]) + [1], list(back[1]) + [1], list(back[3]) + [1], list(back[2]) + [1]])
        tri = _quad_tris(0, 1, 2, 3)
        screen.add(-1e9, BLEND_OPAQUE, wr[0], self._verts(p[tri], np.zeros((6, 2)), np.tile(wr[1], (6, 1)),
                                                           cols[tri]))
        mapc = st.screen.map_color.get()
        if self.show_grid and self.map is None and mapc[3] > 0.01:
            self._floor(world, view, mapc)
        if self.show_area and mapc[3] > 0.01:
            self._area(world, st, mapc)
        cut = 0.0
        for a, ac in st.actors.items():
            if ac.screen:
                cut = max(cut, self._screen_actor(screen, st, a, ac))
            else:
                if self.show_shadows and mapc[3] > 0.01:
                    self._shadow(world, st, ac, mapc)
                self._actor(world, st, a, ac, view, cam)
        if cut > 0.003:
            # a cut-in on screen: the battle dims and black bars close in (measured on Dazzling Eyes)
            dq = np.array([[-1, 1, 0], [1, 1, 0], [1, -1, 0], [-1, -1, 0]], np.float32)
            screen.add(5e8, BLEND_ALPHA, wr[0], self._verts(dq[tri], np.zeros((6, 2)), np.tile(wr[1], (6, 1)),
                                                            np.tile([0, 0, 0, 0.5 * cut], (6, 1))))
            for y0, y1 in ((1.0, 1.0 - 2 * 0.238 * cut), (-1.0, -1.0 + 2 * 0.195 * cut)):
                bq = np.array([[-1, y0, 0], [1, y0, 0], [1, y1, 0], [-1, y1, 0]], np.float32)
                screen.add(5e8 + 1, BLEND_OPAQUE, wr[0], self._verts(bq[tri], np.zeros((6, 2)),
                                                                     np.tile(wr[1], (6, 1)), np.tile([0, 0, 0, 1], (6, 1))))
        for k, sl in st.slots.items():
            if sl.shown and sl.drawn and sl.effect is not None and k not in self.hidden_slots:
                self._effect(world, st, k, sl, view, cam, w, h)
        if self.particles is not None:
            self._particles(world, st, view, cam)
        fade = float(st.screen.fade.get()[0])
        if abs(fade) > 0.5:
            c = 0.0 if fade > 0 else 1.0
            al = min(1.0, abs(fade) / 128.0)
            fq = np.array([[-1, 1, 0], [1, 1, 0], [1, -1, 0], [-1, -1, 0]], np.float32)
            screen.add(1e9, BLEND_ALPHA, wr[0], self._verts(fq[tri], np.zeros((6, 2)), np.tile(wr[1], (6, 1)),
                                                            np.tile([c, c, c, al], (6, 1))))
        return world, screen

    @staticmethod
    def _cam_axes(view):
        """editor-space right / up / toward-camera unit vectors of a view (stage.GameView or render.Camera)"""
        right, up, back = view.right, view.up, view.fwd
        return right / np.linalg.norm(right), up / np.linalg.norm(up), back / np.linalg.norm(back)

    def _depth(self, view, p):
        _, d = view.project(np.atleast_2d(p), 100, 100)
        return float(d[0])

    # ---- floor
    def _floor(self, batch, view, mapc):
        n = 6
        lines = []
        for i in range(-n, n + 1):
            a, b = (i - 0.5) * stg.PANEL, (n + 0.5) * stg.PANEL
            lines += [([a, 0, -b], [a, 0, b]), ([-b, 0, a], [b, 0, a])]
        wr = self.atlas.white_rect()
        quads = []
        wdt = 1.2
        for p0, p1 in lines:
            p0, p1 = np.array(p0, float), np.array(p1, float)
            d = p1 - p0
            side = np.cross(d / np.linalg.norm(d), [0, 1, 0]) * wdt
            quads.append(_quad_tris(p0 - side, p1 - side, p1 + side, p0 + side))
        pos = np.concatenate(quads)
        col = np.tile([0.42 * mapc[0], 0.40 * mapc[1], 0.55 * mapc[2], 0.55 * mapc[3]], (len(pos), 1))
        batch.add(-1e8, BLEND_ALPHA, wr[0], self._verts(pos, np.zeros((len(pos), 2)), np.tile(wr[1], (len(pos), 1)),
                                                        col), AID_QUEUE)

    # ---- the skill's panels on the ground (editor aid: the game shows them while aiming, not during the skill)
    def _area(self, batch, st, mapc):
        su = st.setup
        if not su.area and not su.reach:
            return
        wr = self.atlas.white_rect()
        a = float(min(1.0, mapc[3]))
        pos, col = [], []

        def panel(c, rgb, fill, edge):
            x, y, z = float(c[0]), float(c[1]) + AREA_LIFT, float(c[2])
            h, e = stg.PANEL * 0.47, stg.PANEL * 0.06
            pos.append(_quad_tris([x - h, y, z - h], [x + h, y, z - h], [x + h, y, z + h], [x - h, y, z + h]))
            col.append(np.tile(list(rgb) + [fill * a], (6, 1)))
            for (x0, z0, x1, z1) in ((x - h, z - h, x + h, z - h + e), (x - h, z + h - e, x + h, z + h),
                                     (x - h, z - h + e, x - h + e, z + h - e), (x + h - e, z - h + e, x + h, z + h - e)):
                pos.append(_quad_tris([x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]))
                col.append(np.tile(list(rgb) + [edge * a], (6, 1)))
        hit = {(round(c[0]), round(c[2])) for c in su.area or []}
        for c in su.reach or []:
            if (round(c[0]), round(c[2])) not in hit:
                panel(c, REACH_RGB, 0.13, 0.35)
        for c in su.area or []:
            panel(c, AREA_RGB.get(int(c[3]), AREA_RGB[1]), 0.30, 0.85)
        if su.cursor is not None:
            x, y, z = su.cursor[0], su.cursor[1] + AREA_LIFT * 1.5, su.cursor[2]
            r = stg.PANEL * 0.18
            pos.append(_quad_tris([x - r, y, z], [x, y, z - r], [x + r, y, z], [x, y, z + r]))
            col.append(np.tile([1.0, 0.95, 0.55, 0.9 * a], (6, 1)))
        p = np.concatenate(pos)
        batch.add(-9e7, BLEND_ALPHA, wr[0], self._verts(p, np.zeros((len(p), 2)), np.tile(wr[1], (len(p), 1)),
                                                       np.concatenate(col)), AID_QUEUE)

    # ---- units
    def _actor(self, batch, st, a, ac, view, cam):
        num = ac.sprite
        if not ac.exists or num is None:
            return
        tint = ac.tint.get()
        if a not in (choreo.CASTER, choreo.TARGET):
            pass
        alpha = float(tint[3])
        if alpha <= 0.003:
            return
        right, up, back = cam
        # which way it faces on screen: front / back view, mirrored when facing right
        d3 = np.array([ac.dir[0], 0.0, ac.dir[1]])
        facing_right = float(d3 @ right) > 0
        seen_back = float(d3 @ back) < 0
        t = ac.mtime
        mirror = facing_right
        if ac.anim:
            aid = abs(int(ac.anim))
            ids = self.assets.sprite(num)[1]
            if aid not in ids:
                aid = self.assets.anim_for(num, aid // 10, seen_back)
            mirror = ac.anim < 0
        else:
            aid = self.assets.anim_for(num, ac.motion, seen_back)
        wtype = self.weapon if a == choreo.CASTER or ac.copy == choreo.CASTER else None
        items = self.assets.sprite_items(num, aid, t, wtype) if aid is not None else []
        if not items:
            for fb in (6001, 1001, 1, 11):
                if fb != aid and fb in self.assets.sprite(num)[1]:
                    items = self.assets.sprite_items(num, fb, t, wtype)
                    if items:
                        break
        if not items:
            return
        base = ac.place(st)
        sc = ac.scale.get() * SPRITE_SCALE
        sx = sc[0] * (-1.0 if mirror else 1.0)
        sy = sc[1]
        dim = None                       # cmd_6480 10000 dims the units not in the skill (none on this stage)
        pos_l, uv_l, rect_l, col_l, pages = [], [], [], [], []
        # the sprite's turn (cmd_65b4 / 65b8; the game's sprite draw 0x1402f1b47): in the sprite's own pixels (y down)
        # around the pivot (stored value x 0.0625), clockwise for positive angles, before the sprite is mirrored;
        # then the pixel shift of cmd_65bc (not mirrored)
        ang = math.radians(ac.angle % 360.0) if ac.angle % 360.0 else 0.0
        ca, sa = math.cos(ang), math.sin(ang)
        px, py = ac.pivot[0] * 0.0625, ac.pivot[1] * 0.0625
        ox, oy = ac.pix.get()
        ou, ov = ox * abs(sc[0]), -oy * abs(sc[1])
        for f, it in items:
            c = it.cell
            if c.w == 0 or c.h == 0:
                continue
            key, rgba = self._cell_texture(f, it, ac.palette if f is not self.assets.weapon(wtype) else 0)
            if rgba is None:
                continue
            page, (u0, v0, du, dv) = self.atlas.add(key, rgba)
            tw, th = self.atlas.sizes[key]
            q = it.quad
            corners = []
            for i in range(4):
                x, y = q[i][0], q[i][1]
                if ang:
                    x, y = px + (x - px) * ca - (y - py) * sa, py + (x - px) * sa + (y - py) * ca
                corners.append(base + right * (x * sx + ou) + up * (-y * sy + ov))
            tri = _quad_tris(*corners)
            uvq = np.array([[c.x / tw, c.y / th], [(c.x + c.w) / tw, c.y / th],
                            [(c.x + c.w) / tw, (c.y + c.h) / th], [c.x / tw, (c.y + c.h) / th]])
            uvt = uvq[[0, 1, 2, 0, 2, 3]]
            col = np.array(it.color[:4], float) if len(it.color) else np.array([128, 128, 128, 255.0])
            cc = np.array([col[0] / 128.0, col[1] / 128.0, col[2] / 128.0, col[3] / 255.0])
            cc = cc * np.array([tint[0], tint[1], tint[2], alpha])
            if dim is not None:
                cc = cc * dim
            pos_l.append(tri)
            uv_l.append(uvt)
            rect_l.append(np.tile([u0, v0, -du, dv], (6, 1)))
            col_l.append(np.tile(cc, (6, 1)))
            pages.append(page)
        if not pos_l:
            return
        # sorted by its feet brought 7 map units nearer (the game's sprite key), so a circle on the ground under it
        # is drawn first and an effect in front of it after
        key = float(base @ back) + UNIT_NEARER
        # one record per atlas page (normally all on one)
        pages = np.array(pages)
        for pg in set(pages.tolist()):
            sel = np.nonzero(pages == pg)[0]
            batch.add(key, BLEND_ALPHA, pg, self._verts(np.concatenate([pos_l[i] for i in sel]),
                                                        np.concatenate([uv_l[i] for i in sel]),
                                                        np.concatenate([rect_l[i] for i in sel]),
                                                        np.concatenate([col_l[i] for i in sel])), UNIT_QUEUE)

    def _shadow_rect(self):
        """a soft round shadow picture (the game uses a texture of its own; this one is measured to look the same)"""
        if getattr(self, "_shadow_tex", None) is None:
            n = 64
            y, x = np.mgrid[0:n, 0:n]
            d = np.hypot(x - (n - 1) / 2.0, y - (n - 1) / 2.0) / ((n - 1) / 2.0)
            a = np.clip((1.0 - d) / 0.65, 0.0, 1.0)
            a = a * a * (3 - 2 * a)                      # smooth edge, flat-ish middle
            rgba = np.zeros((n, n, 4), np.uint8)
            rgba[..., 3] = (a * 255).astype(np.uint8)
            self._shadow_tex = self.atlas.add(("shadow",), rgba)
        return self._shadow_tex

    def _shadow(self, batch, st, ac, mapc):
        """a unit's shadow on the ground under it (it stays on the ground when the unit jumps)"""
        if not ac.exists or ac.sprite is None or not getattr(ac, "shadow", True):
            return
        alpha = float(ac.tint.get()[3]) * float(min(1.0, mapc[3]))
        if alpha <= 0.01:
            return
        p = ac.place(st)
        try:
            gy = st.setup.ground(p[0], p[2])
        except Exception:
            gy = 0.0
        r = float(self.shadow_sizes.get(ac.sprite, 6) or 6) * SHADOW_SIZE * stg.MAP * float(abs(ac.scale.get()[0]))
        x, y, z = float(p[0]), gy + SHADOW_LIFT, float(p[2])
        page, (u0, v0, du, dv) = self._shadow_rect()
        quad = _quad_tris([x - r, y, z - r], [x + r, y, z - r], [x + r, y, z + r], [x - r, y, z + r])
        uv = np.array([[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]], float)
        batch.add(0.0, BLEND_ALPHA, page, self._verts(quad, uv, np.tile([u0, v0, -du, dv], (6, 1)),
                                                      np.tile([0.0, 0.0, 0.0, SHADOW_ALPHA * alpha], (6, 1))),
                  SHADOW_QUEUE)

    def _screen_actor(self, batch, st, a, ac):
        """a cut-in: its sprite in 1080p screen pixels around the screen centre (clip space here); -> opacity"""
        num = ac.sprite
        if not ac.exists or num is None:
            return 0.0
        alpha = float(ac.tint.get()[3] * ac.fade.get()[0])
        if alpha <= 0.003:
            return 0.0
        aid = abs(int(ac.anim)) if ac.anim else 8000
        t = ac.mtime
        items = self.assets.sprite_items(num, aid, t)
        if not items:
            return 0.0
        sc = ac.scale.get()
        cx, cy = ac.spos.get()
        to_clip = np.array([1.0 / 960.0, -1.0 / 540.0])
        tint = ac.tint.get()
        for f, it in items:
            c = it.cell
            if c.w == 0 or c.h == 0:
                continue
            key, rgba = self._cell_texture(f, it, ac.palette)
            if rgba is None:
                continue
            page, (u0, v0, du, dv) = self.atlas.add(key, rgba)
            tw, th = self.atlas.sizes[key]
            q = np.array(it.quad, float) * sc[:2] + [cx, cy]
            p = np.c_[q * to_clip, np.zeros(4)]
            uvq = np.array([[c.x / tw, c.y / th], [(c.x + c.w) / tw, c.y / th],
                            [(c.x + c.w) / tw, (c.y + c.h) / th], [c.x / tw, (c.y + c.h) / th]])
            col = np.array(it.color[:4], float)
            cc = np.array([col[0] / 128.0, col[1] / 128.0, col[2] / 128.0, col[3] / 255.0]) *                 np.array([tint[0], tint[1], tint[2], alpha])
            idx = [0, 1, 2, 0, 2, 3]
            batch.add(6e8, BLEND_ALPHA, page, self._verts(p[idx], uvq[idx], np.tile([u0, v0, -du, dv], (6, 1)),
                                                          np.tile(cc, (6, 1))))
        return alpha

    def _cell_texture(self, f, it, variant):
        """(atlas key, RGBA of the whole texture with the cell's palette)"""
        if it.tex_global >= len(f.textures):
            return None, None
        b = f.blocks[it.block]
        npal = len(b.palette_infos)
        gp = b.pal_base + min(it.pal_local + variant, max(0, npal - 1)) if f.palettes else 0
        gp = min(gp, max(0, len(f.palettes) - 1))
        key = ("anm", id(f), it.tex_global, gp)
        if key in self.atlas.entries:
            return key, _Dummy
        try:
            img = anm.texture_to_image(f, it.tex_global, gp)
            arr = np.asarray(img, np.uint8)
        except Exception:
            return None, None
        return key, arr

    # ---- effects
    def _effect(self, batch, st, k, sl, view, cam, w, h):
        m = self.assets.model(sl.effect)
        if m is None:
            return
        col = np.minimum(sl.color.get(), 1.0)
        world_pos = st.slot_world(sl)
        c, dpt = view.project(np.atleast_2d(world_pos), w, h)
        centre_px = (float(c[0][0]), float(c[0][1]))
        if col[3] <= 0.003:
            self.pick[k] = (centre_px[0], centre_px[1], centre_px[0], centre_px[1], centre_px)
            return
        q = st.q
        sc = sl.scale.get().copy()
        if q % 2 and SWAP_SCALE_ON_SIDE_FACING:
            sc[0], sc[2] = sc[2], sc[0]
        if not np.any(np.abs(sc) > 1e-6):
            self.pick[k] = (centre_px[0], centre_px[1], centre_px[0], centre_px[1], centre_px)
            return
        R = rot_matrix(sl.rot.get(), sl.rot_order)
        if sl.rot2_order is not None or np.any(np.abs(sl.rot2.get()) > 1e-6):
            R = rot_matrix(sl.rot2.get(), (sl.rot2_order or 6) - 6) @ R
        if TURN_EFFECTS_WITH_FACING:
            R = quarter_matrix(q) @ R
        S = np.diag(sc * MODEL_TO_SCRIPT)
        inst = R @ S
        nsc = sl.nscale.get()
        local = LOCAL_SCALE and not np.allclose(np.abs(sc), abs(sc[0]), rtol=1e-4)
        right, up, back = cam
        bill_model = sl.billboard if sl.billboard >= 0 else m.billboard
        zb = float(sl.zbias)
        roll = -sl.rot.get()[2]                       # the render frame's roll (see FLIP_XZ)
        cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
        r_full, u_full = right * cr + up * sr, up * cr - right * sr
        r_y = np.array([right[0], 0.0, right[2]])
        r_y /= max(1e-6, np.linalg.norm(r_y))
        b_y = np.cross(r_y, [0.0, 1.0, 0.0])
        frame = sl.frame
        recs = []                         # (queue, key, blend, page, vertices): one per piece, in model order
        for pi, nm, alpha in m.pose(frame):
            if pi >= len(m.parts):
                continue
            if nm is None:
                nm = np.eye(4)
            N3 = nm[:3, :3] * nsc[None, :]
            T = nm[:3, 3]
            if local:                     # scaled in the part's space: N (S p) + S T, then turned and placed
                N3 = (N3 * sc[None, :]) * MODEL_TO_SCRIPT
                T = T * sc * MODEL_TO_SCRIPT
            if FLIP_MODEL_Y:
                N3 = N3 * np.array([[1.0], [-1.0], [1.0]])
                T = T * np.array([1.0, -1.0, 1.0])
            for g in m.parts[pi]:
                bill = (bill_model if bill_model else g.bill) if sl.face_cam else 0
                if bill:
                    # facing the camera: the node's place goes through the instance, its shape doesn't turn
                    centre = world_pos + (R @ T if local else inst @ T)
                    shape = (g.pos @ N3.T) * (sc * MODEL_TO_SCRIPT)
                    if bill == 2:
                        pos = centre + np.outer(shape[:, 0], r_y) + np.outer(shape[:, 1], [0.0, 1.0, 0.0])                             + np.outer(shape[:, 2], b_y)
                    else:
                        pos = centre + np.outer(shape[:, 0], r_full) + np.outer(shape[:, 1], u_full)                             + np.outer(shape[:, 2], back)
                elif local:
                    pos = world_pos + (g.pos @ N3.T + T) @ R.T
                else:
                    pos = world_pos + (g.pos @ N3.T + T) @ inst.T
                if DEBUG_VERTS is not None:                 # dev: tools/_compare_recording.py --bbox
                    DEBUG_VERTS.setdefault(k, []).append(np.asarray(pos, float))
                ti = m.texture_at(g, frame)
                if ti is None or ti < 0 or ti >= len(m.textures):
                    page, rect = self.atlas.white_rect()
                else:
                    layer = min(max(0, sl.layer), m.tex_layers[ti] - 1)
                    page, rect = self.atlas.add(("fx", m.id, ti, layer), _Lazy(m, ti, layer))
                blend = sl.blend if sl.blend >= 0 else g.flags[0]
                n = len(pos)
                v = np.empty((n, FLOATS), np.float32)
                v[:, 0:3] = pos
                v[:, 3:5] = g.uv
                v[:, 5:9] = (rect[0], rect[1], rect[2] if g.wrap else -rect[2], rect[3])
                v[:, 9:13] = g.vcol * (g.color * np.array([col[0], col[1], col[2], col[3] * alpha], np.float32))
                v[:, 13] = zb
                queue = sl.queue if sl.queue >= 0 else (g.flags[1] + 2 if len(g.flags) > 1 else SORTED_QUEUE)
                # the game sorts a piece by the middle of its first triangle (0x14030b810) plus the bias
                recs.append((queue, float(pos[:3].mean(0) @ back) + zb, blend, page, v))
        allv = []
        for queue, key, blend, page, v in recs:
            batch.add(key, blend, page, v, queue, queue != SORTED_QUEUE)
            allv.append(v[:, :3])
        if allv:
            pts = np.concatenate(allv)
            pts = pts[:: max(1, len(pts) // 64)]
            pp, _ = view.project(pts, w, h)
            lo, hi = pp.min(0), pp.max(0)
            self.pick[k] = (lo[0], lo[1], hi[0], hi[1], centre_px)
        else:
            self.pick[k] = (centre_px[0], centre_px[1], centre_px[0], centre_px[1], centre_px)

    # ---- particles
    def _particles(self, batch, st, view, cam):
        right, up, back = cam
        fx, fz = stg.FACING_DIRS.get(int(st.setup.facing) % 4, (0.0, 1.0))
        axes = np.array([[fx, 0.0, fz], [0.0, 1.0, 0.0], [-fz, 0.0, fx]])
        for p, msk, age in self.particles.at(st.frame):
            rgba = self.assets.particle_rgba(p.em.cell)
            if rgba is None:
                continue
            page, rect = self.atlas.add(("pt", p.em.cell), rgba)
            pos, half, ang, colr = particles.quads(p, msk, age, st.frame)
            centre = st.where(p.actor) + stg.turn_offset(p.base, st.q) + pos @ axes
            n = len(centre)
            if not n:
                continue
            # corners +- half size along the camera's right / up, turned by the particle's angle (as the game)
            cs, sn = np.cos(ang)[:, None], np.sin(ang)[:, None]
            hx, hy = half[:, :1], half[:, 1:2]

            def corner(dx, dy):
                x, y = dx * hx, dy * hy
                return centre + right * (x * cs - y * sn) + up * (x * sn + y * cs)
            c0, c1, c2, c3 = corner(-1, 1), corner(1, 1), corner(1, -1), corner(-1, -1)
            tri = np.stack([c0, c1, c2, c0, c2, c3], 1).reshape(-1, 3)
            uv = np.tile([[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]], (n, 1))
            col = np.repeat(np.clip(colr, 0, 2), 6, axis=0)
            zb = float(p.em.bias) * stg.MAP             # cmd_4450 (map units -> script units)
            v = self._verts(tri, uv, np.tile([rect[0], rect[1], -rect[2], rect[3]], (len(tri), 1)), col, zb)
            keys = centre @ back + zb
            blend = p.em.blend
            for i in range(n):                          # each particle is its own record in the sorted queue
                batch.add(float(keys[i]), blend, page, v[i * 6:(i + 1) * 6], SORTED_QUEUE)

    # ---------------------------------------------------------------- drawing
    def paint(self, gl, w, h, st, view, viewport=None, clear=True):
        """draw the stage at view (stage.GameView or render.Camera) into the current framebuffer
        (viewport: x, y, w, h in pixels of the framebuffer; GL y from the bottom)"""
        if self.prog is None:
            self.init_gl(gl)
        world, screen = self.build(st, view, w, h)
        self.atlas.flush(gl)
        vx, vy, vw, vh = viewport or (0, 0, w, h)
        gl.glViewport(vx, vy, vw, vh)
        if clear:
            gl.glDisable(GL_SCISSOR_TEST)
            gl.glClearColor(0.0, 0.0, 0.0, 1.0)
            gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        gl.glDisable(GL_CULL_FACE)
        self.prog.bind()
        self.vao.bind()
        gl.glActiveTexture(GL_TEXTURE0)
        self.prog.setUniformValue(self.loc_tex, 0)
        self.prog.setUniformValue(self.loc_texel, 0.5 / PAGE)
        self.prog.setUniformValue(self.loc_tint, 1.0, 1.0, 1.0, 1.0)
        # screen-space backdrop
        ident = np.eye(4, dtype=np.float32)
        bg = [r for r in screen.items if r[1] < 0]
        fg = sorted((r for r in screen.items if r[1] >= 0), key=lambda r: (r[1], r[2]))
        gl.glDisable(GL_DEPTH_TEST)
        gl.glDepthMask(False)
        self.prog.setUniformValue(self.loc_tocam, 0.0, 0.0, 0.0)
        self._draw(gl, bg, ident)
        # the world
        M = view.matrix() if hasattr(view, "matrix") else self._ortho(view, w, h)
        self._draw_map(gl, st, M.astype(np.float32))
        gl.glEnable(GL_DEPTH_TEST)
        gl.glDepthFunc(GL_LEQUAL)
        gl.glDepthMask(False)
        back = self._cam_axes(view)[2]
        self.prog.setUniformValue(self.loc_tocam, float(back[0]), float(back[1]), float(back[2]))
        n = self._draw(gl, world.ordered(), M.astype(np.float32))
        gl.glDisable(GL_DEPTH_TEST)
        self.prog.setUniformValue(self.loc_tocam, 0.0, 0.0, 0.0)
        self._draw(gl, fg, ident)
        gl.glDepthMask(True)
        gl.glDisable(GL_BLEND)
        self.vao.release()
        self.prog.release()
        self.stats = dict(records=len(world.items), vertices=n)

    def _ortho(self, cam, w, h):
        """clip matrix of the editor's orbit camera (render.Camera: scale px / unit, pan)"""
        R = cam.R
        V = np.eye(4)
        V[:3, :3] = R
        V[:3, 3] = -R @ cam.focus
        P = np.eye(4)
        P[0, 0] = cam.scale * 2.0 / w
        P[1, 1] = cam.scale * 2.0 / h
        P[2, 2] = -1.0 / 20000.0
        P[0, 3] = cam.pan[0] * 2.0 / w
        P[1, 3] = -cam.pan[1] * 2.0 / h
        return P @ V

    def _draw(self, gl, items, M):
        """records in the given order, consecutive ones with the same blend / page in one call"""
        if not items:
            return 0
        verts = np.concatenate([r[5] for r in items]).astype(np.float32, copy=False)
        self.vbo.bind()
        self.vbo.allocate(verts.tobytes(), verts.nbytes)
        gl.glUniformMatrix4fv(self.loc_mvp, 1, True, M.reshape(-1).tolist())
        first = 0
        cur = None
        run_start, run_n = 0, 0
        zw = False
        for _q, _k, _n, blend, page, v, zwrite in items:
            key = (blend, page, zwrite)
            if key != cur:
                if run_n:
                    gl.glDrawArrays(GL_TRIANGLES, run_start, run_n)
                self._state(gl, blend, page)
                if zwrite != zw:
                    gl.glDepthMask(bool(zwrite))
                    zw = zwrite
                cur = key
                run_start, run_n = first, 0
            run_n += len(v)
            first += len(v)
        if run_n:
            gl.glDrawArrays(GL_TRIANGLES, run_start, run_n)
        if zw:
            gl.glDepthMask(False)
        return first

    def _state(self, gl, blend, page):
        gl.glBindTexture(GL_TEXTURE_2D, self.atlas.pages[page]["tex"])
        self.prog.setUniformValue(self.loc_mul, 1.0 if blend == BLEND_MUL else 0.0)
        if blend == BLEND_OPAQUE:
            gl.glDisable(GL_BLEND)
            return
        gl.glEnable(GL_BLEND)
        # the picture's alpha only weighs the colour: the frame stays opaque (alpha 1) whatever is drawn
        if blend == BLEND_MUL:
            gl.glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD)
            gl.glBlendFuncSeparate(GL_DST_COLOR, GL_ZERO, GL_ZERO, GL_ONE)
        elif blend == BLEND_SUBR:
            gl.glBlendEquationSeparate(GL_FUNC_SUBTRACT, GL_FUNC_ADD)
            gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE, GL_ZERO, GL_ONE)
        elif blend == BLEND_ADD:
            gl.glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD)
            gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE, GL_ZERO, GL_ONE)
        elif blend == BLEND_SUB:
            gl.glBlendEquationSeparate(GL_FUNC_REVERSE_SUBTRACT, GL_FUNC_ADD)
            gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE, GL_ZERO, GL_ONE)
        else:
            gl.glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD)
            gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE)


_Dummy = np.zeros((1, 1, 4), np.uint8)


class _MapLazy:
    def __init__(self, bm, ti):
        self.bm, self.ti = bm, ti

    def __array__(self, dtype=None, copy=None):
        a = self.bm.rgba(self.ti)
        return a if dtype is None else a.astype(dtype)


class _Lazy:
    """an effect texture decoded only when the atlas needs it"""

    def __init__(self, m, ti, layer):
        self.m, self.ti, self.layer = m, ti, layer

    def __array__(self, dtype=None, copy=None):
        a = self.m.rgba(self.ti, self.layer)
        return a if dtype is None else a.astype(dtype)
