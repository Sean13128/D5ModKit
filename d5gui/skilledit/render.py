"""Drawing a choreography scene (choreo.Timeline.scene) with QPainter: an orbit camera over the battle floor, the
caster and target sprites as billboards, effect models as textured triangles (d5lib/fxmodel.py)."""
import math

import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF, QTransform, QFont

from d5lib import anm, choreo, fxmodel, grips, particles, sprites, txf

PANEL = 120.0                     # script units per map panel (map: 12 units, scripts: tenths)
SPRITE_SCALE = 1.0                # script units per sprite pixel
DEFAULT_ZOOM = 700.0
FACING_DIRS = {0: (0.0, 1.0), 1: (1.0, 0.0), 2: (0.0, -1.0), 3: (-1.0, 0.0)}   # $60201 -> caster->target (x, z)
# cmd_6510 motion -> animation base where it isn't motion x 10 (seen in game on humanoid classes, 2026-10-08):
# 109 (cast) plays 1051 / 1057 (arms raised; 1091 is a plain stand), 151 plays the class's special 7011 (front only:
# from behind the unit is invisible)
MOTION_BASE = {109: 1050, 151: 7010}


def _rot(rx, ry, rz):
    """rotation matrix (degrees), x first, then y, then z"""
    ax, ay, az = (math.radians(v) for v in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Z @ Y @ X


class Camera:
    """orthographic orbit camera: yaw around the up axis, pitch down, scale = screen px per script unit"""

    def __init__(self):
        self.yaw, self.pitch, self.scale = 90.0, 26.0, 1.4
        self.focus = np.array([0.0, 50.0, 60.0])
        self.pan = np.array([0.0, 0.0])
        self.update()

    def update(self):
        a, b = math.radians(self.yaw), math.radians(self.pitch)
        ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
        rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
        self.R = rx @ ry
        self.right, self.up, self.fwd = self.R[0], self.R[1], self.R[2]     # world directions of screen axes

    def project(self, p, w, h):
        """(n, 3) world -> (n, 2) screen, (n,) depth (bigger = nearer)"""
        v = (np.asarray(p, float) - self.focus) @ self.R.T
        x = w / 2 + self.pan[0] + v[:, 0] * self.scale
        y = h / 2 + self.pan[1] - v[:, 1] * self.scale
        return np.c_[x, y], v[:, 2]

    def unproject_delta(self, dx, dy):
        """screen movement -> world movement in the view plane"""
        return (self.right * dx - self.up * dy) / self.scale


# ------------------------------------------------------------------------------------------------ effects
class FxPainter:
    """textures of effect models as QImages (tinted copies cached) and triangle drawing"""

    def __init__(self, get, members, mods=()):
        self.get, self.members, self.mods = get, members, list(mods)
        self.images = {}
        self.tinted = {}
        self.inv = {}
        self.poly = {}

    def model(self, eid):
        try:
            return fxmodel.load(self.get, eid, self.members, self.mods)
        except Exception:
            return None

    def image(self, eid, ti, tex, rgb):
        q = tuple(int(round(c / 10.0)) * 10 for c in rgb)
        key = (eid, ti, q)
        im = self.tinted.get(key)
        if im is None:
            a = tex.rgba
            if q != (100, 100, 100):
                a = a.astype(np.float32)
                a[..., :3] *= np.array(q, np.float32) / 100.0
                a = np.clip(a, 0, 255).astype(np.uint8)
            a = np.ascontiguousarray(a)
            im = QImage(a.data, a.shape[1], a.shape[0], 4 * a.shape[1], QImage.Format.Format_RGBA8888).copy()
            if len(self.tinted) > 600:
                self.tinted.clear()
            self.tinted[key] = im
        return im

    def triangles(self, slot, world_pos, cam):
        """batches of an effect slot's triangles: [(model, part index, layer, world tris (n, 3, 3), alpha, rgb)]"""
        m = self.model(slot["effect"])
        if m is None:
            return []
        size = (slot["size"] or 1000) / 1000.0
        sc = np.array(slot["scale"][:3], float) / 100.0 * size * fxmodel.MODEL_TO_SCRIPT
        rx, ry, rz = slot["rot"][:3]
        col = slot["color"]
        alpha = max(0.0, min(1.0, col[3] / 100.0)) if len(col) > 3 else 1.0
        if alpha <= 0.01 or not np.any(sc):
            return []
        rgb = col[:3]
        if m.flat and abs(rx) < 1e-3 and abs(ry) < 1e-3:          # a picture: faces the camera
            M = _rot(0, 0, rz).T @ np.array([cam.right, cam.up, cam.fwd])
        else:
            M = _rot(rx, ry, rz).T
        out = []
        t = max(0.0, slot["time"]) * (slot.get("speed", 100) or 100) / 100.0
        plays = slot.get("plays", -1)
        if plays is not None and plays >= 0 and m.anim is not None:
            # cmd_3c10 / 3c20 last value: how many times the model's animation plays (0 / 1 once, -1 forever);
            # then the effect is gone -- a 0-frame model shown with 0 / 1 never appears (seen in game)
            if m.anim.length <= 0 or t > m.anim.length * max(1, plays):
                return []
        an = slot.get("anim")
        if an and len(an) == 3:              # cmd_3c18 / 3c22: play the model from frame a to b (dir 1 / -1, 0 still)
            d, f0, f1 = an
            if d == 0:
                t = f0
            else:
                t = f0 + (1 if d > 0 else -1) * t
                lo, hi = min(f0, f1), max(f0, f1)
                if hi > lo and not (lo <= t <= hi):
                    if m.anim is not None and m.anim.loop == 1:
                        t = lo + (t - lo) % (hi - lo)
                    else:
                        t = min(max(t, lo), hi)
        for pi, mat, a in m.draw_list(t, 100):
            p = m.parts[pi]
            v = p.tris.reshape(-1, 3)
            if mat is not None:                          # the model's own animation (node move / turn / size)
                v = v @ mat[:3, :3].T + mat[:3, 3]
            v = (v * sc) @ M + world_pos
            out.append((m, pi, 0, v.reshape(-1, 3, 3), alpha * a, rgb))
        return out

    def inverse_uv(self, m, pi, layer):
        """(n, 3, 3) inverses of the triangles' texture-pixel matrices [[u, v, 1] x 3] (cached)"""
        key = (m.id, pi, layer)
        inv = self.inv.get(key)
        if inv is None:
            p = m.parts[pi]
            tex = m.textures[p.tex] if p.tex < len(m.textures) else None
            w, h = (tex.w, tex.h) if tex else (1, 1)
            A = np.ones((len(p.uvs), 3, 3))
            A[:, :, 0] = p.uvs[:, :, 0] * w
            A[:, :, 1] = (p.uvs[:, :, 1] + layer) * h
            det = np.linalg.det(A)
            ok = np.abs(det) > 1e-9
            inv = np.full_like(A, np.nan)
            if ok.any():
                inv[ok] = np.linalg.inv(A[ok])
            self.inv[key] = inv
        return inv

    def polys(self, m, pi, layer):
        """the part's triangles as polygons: [(triangle whose texture map is used, [flat vertex indices])];
        two triangles that share an edge and the same texture mapping (a quad) become one polygon (cached)"""
        key = (m.id, pi, layer)
        out = self.poly.get(key)
        if out is None:
            p = m.parts[pi]
            inv = self.inverse_uv(m, pi, layer)
            sol = np.einsum("nij,njk->nik", np.nan_to_num(inv), p.tris.astype(float))     # tex px -> model
            out, used = [], set()
            n = len(p.tris)
            for a in range(n):
                if a in used or not np.isfinite(inv[a, 0, 0]):
                    continue
                b = a + 1
                quad = None
                if b < n and b not in used and np.isfinite(inv[b, 0, 0]) and                         np.allclose(sol[a], sol[b], rtol=1e-3, atol=1e-3 * (1 + np.abs(sol[a]).max())):
                    pa, pb = p.tris[a], p.tris[b]
                    shared = [(i, j) for i in range(3) for j in range(3) if np.allclose(pa[i], pb[j], atol=1e-4)]
                    if len(shared) == 2:
                        x = next(j for j in range(3) if j not in (shared[0][1], shared[1][1]))
                        i0, i1 = shared[0][0], shared[1][0]
                        order = [0, 1, 2]
                        for k in range(3):                  # insert x between the two shared corners
                            u, v = order[k], order[(k + 1) % 3]
                            if {u, v} == {i0, i1}:
                                quad = [3 * a + c for c in order[:k + 1]] + [3 * b + x] +                                        [3 * a + c for c in order[k + 1:]]
                                break
                if quad:
                    used |= {a, b}
                    out.append((a, quad))
                else:
                    used.add(a)
                    out.append((a, [3 * a, 3 * a + 1, 3 * a + 2]))
            self.poly[key] = out
        return out

    def draw_batch(self, qp, batch, pts, order=None, height=None, floor=0.0):
        """draw a batch; pts = its screen points (n, 3, 2); order = polygon order (back to front) or None;
        height = the points' world heights (n * 3,): what is below `floor` is cut off -- the game's floor hides it
        (an effect shown at an actor's feet only shows its upper half; seen in game 2026-10-08 with effect 707)"""
        m, pi, layer, _, alpha, rgb = batch
        p = m.parts[pi]
        if p.tex >= len(m.textures):
            return
        tex = m.textures[p.tex]
        img = self.image(m.id, p.tex, tex, [rgb[i] * p.color[i] for i in range(3)])
        polys = self.polys(m, pi, layer)
        if not polys:
            return
        tri = np.array([t for t, _ in polys])
        sol = np.einsum("nij,njk->nik", self.inverse_uv(m, pi, layer)[tri], pts[tri])   # tex px -> screen
        flat = pts.reshape(-1, 2)
        qp.setOpacity(alpha * min(1.0, p.color[3]))
        add = tex.additive if p.additive is None else p.additive
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus if add
                              else QPainter.CompositionMode.CompositionMode_SourceOver)
        br = QBrush(img)
        for j in (range(len(polys)) if order is None else order):
            s = sol[j]
            vs = polys[j][1]
            if height is not None and min(height[v] for v in vs) < floor - FLOOR_EPS:
                poly = _clip_below(vs, flat, height, floor)
                if len(poly) < 3:
                    continue
            else:
                poly = [flat[v] for v in vs]
            br.setTransform(QTransform(s[0, 0], s[0, 1], s[1, 0], s[1, 1], s[2, 0], s[2, 1]))
            qp.setBrush(br)
            qp.drawPolygon(QPolygonF([QPointF(*q) for q in poly]))

    def poly_depths(self, batch, depth):
        """per polygon depth from per triangle depth"""
        m, pi, layer = batch[0], batch[1], batch[2]
        return np.array([depth[t] for t, _ in self.polys(m, pi, layer)])


FLOOR_EPS = 1.0                  # script units: effects lying on the floor stay whole


def _clip_below(vs, flat, height, floor):
    """the screen polygon of vertices vs without what is below the floor (the camera is orthographic: cutting
    the screen polygon where the world height crosses the floor is exact)"""
    out = []
    n = len(vs)
    for k in range(n):
        a, b = vs[k], vs[(k + 1) % n]
        ha, hb = height[a] - floor, height[b] - floor
        if ha >= 0:
            out.append(flat[a])
        if (ha >= 0) != (hb >= 0):
            t = ha / (ha - hb)
            out.append(flat[a] + (flat[b] - flat[a]) * t)
    return out


# ------------------------------------------------------------------------------------------------ sprites
class SpriteCache:
    """frames of battle sprites (with the shared humanoid motions and an optional weapon) as QImages"""

    def __init__(self, fs, owner_read=None):
        self.fs = fs
        self.owner_read = owner_read      # vpath -> bytes of a mod's own sprite, or None
        self.files = {}
        self.frames = {}
        self.weapons = {}
        self.infos = {}

    def file(self, num):
        if num not in self.files:
            vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"
            data = self.owner_read(vp) if self.owner_read else None
            try:
                a = anm.load(data if data else self.fs.read(sprites.sprite_vpath(self.fs, num, "EN")))
                a = sprites.preview_file(self.fs, a)
                ids = {x.id for _, _, x in a.all_animations()}
            except Exception:
                a, ids = None, set()
            self.files[num] = (a, ids)
        return self.files[num]

    def anim_for(self, num, motion, back=False):
        a, ids = self.file(num)
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
        if key not in self.infos:
            a, _ = self.file(num)
            bi, ai = anm._resolve_anim(a, ("id", aid))
            self.infos[key] = anm.animation_info(a.blocks[bi], a.blocks[bi].animations[ai])
        return self.infos[key]

    def weapon(self, wtype):
        if wtype not in self.weapons:
            try:
                self.weapons[wtype] = grips.weapon_sprite(self.fs, wtype)
            except Exception:
                self.weapons[wtype] = None
        return self.weapons[wtype]

    def frame(self, num, aid, t, palette=0, wtype=None):
        """(QImage, origin x, origin y) of the sprite at animation time t (loops like the game)"""
        a, _ = self.file(num)
        if a is None or aid is None:
            return None
        inf = self.info(num, aid)
        loop = inf.get("loop")
        length = max(1, inf.get("length", 1))
        if loop and t > loop[1] and loop[1] > loop[0]:
            t = loop[0] + (t - loop[0]) % (loop[1] - loop[0])
        t = int(max(0, min(t, length)))
        key = (num, aid, t, palette, wtype)
        f = self.frames.get(key)
        if f is None:
            w = self.weapon(wtype) if wtype else None
            items = grips.evaluate(a, aid, t, w, wtype or 16)
            if not items:
                f = (None, 0, 0)
            else:
                allp = np.concatenate([it.quad for _, it in items])
                b = (int(allp[:, 0].min()) - 2, int(allp[:, 1].min()) - 2,
                     int(allp[:, 0].max()) + 2, int(allp[:, 1].max()) + 2)
                img = grips.render(items, b, 1.0, palette, char=a)
                data = img.tobytes("raw", "RGBA")
                q = QImage(data, img.width, img.height, 4 * img.width, QImage.Format.Format_RGBA8888).copy()
                f = (q, -b[0], -b[1])
            if len(self.frames) > 4000:
                self.frames.clear()
            self.frames[key] = f
        return f if f[0] is not None else None


# ------------------------------------------------------------------------------------------------ scene
class ParticlePainter:
    """the particle sheet (Start/particle.txf, 4 x 4 cells of 64 px) as tinted QImages"""

    def __init__(self, get):
        self.cells = None
        self.tinted = {}
        try:
            img = txf.to_image(get("Start/Start_JP.dat/particle.txf")).convert("RGBA")
            a = np.asarray(img, np.uint8)
            self.cells = [np.ascontiguousarray(a[(k // 4) * 64:(k // 4 + 1) * 64, (k % 4) * 64:(k % 4 + 1) * 64])
                          for k in range(16)]
        except Exception:
            self.cells = None

    def image(self, cell, rgb):
        q = tuple(int(round(max(0.0, min(2.0, c)) * 8)) for c in rgb)
        key = (cell, q)
        im = self.tinted.get(key)
        if im is None:
            a = self.cells[cell].astype(np.float32)
            a[..., :3] *= np.array(q, np.float32) / 8.0
            a = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
            im = QImage(a.data, 64, 64, 256, QImage.Format.Format_RGBA8888).copy()
            if len(self.tinted) > 800:
                self.tinted.clear()
            self.tinted[key] = im
        return im

    def draw(self, qp, payload):
        em, pts, sizes, rgba = payload
        if self.cells is None:
            return
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus if em.additive
                              else QPainter.CompositionMode.CompositionMode_SourceOver)
        for (x, y), s, c in zip(pts, sizes, rgba):
            if s < 0.5 or c[3] <= 0.01:
                continue
            qp.setOpacity(float(min(1.0, c[3])))
            qp.drawImage(QRectF(x - s / 2, y - s / 2, s, s), self.image(em.cell, c[:3]))


class SceneRenderer:
    def __init__(self, fx: FxPainter, spr: SpriteCache, parts: ParticlePainter = None):
        self.fx, self.spr = fx, spr
        self.parts = parts
        self.particles = None            # particles.ParticleSim of the shown timeline
        self.caster_sprite, self.target_sprite = None, None
        self.caster_palette, self.target_palette = 0, 0
        self.weapon = None
        self.facing = 0
        self.distance = 1.0              # panels
        self.show_grid = True
        self.highlight = None            # slot number drawn with its marker
        self.hidden_slots = set()        # effect slots not drawn (a hidden timeline track)
        self.pick = {}                   # after draw(): slot -> screen box + centre (picking in the viewport)
        self.floor_clip = True           # hide what is below the floor, as the game does
        self.floor = 0.0                 # height of the floor (the panels are flat here)

    # ---------------------------------------------------------------- places
    def actor_base(self, a):
        if a == choreo.TARGET:
            dx, dz = FACING_DIRS.get(self.facing, (0.0, 1.0))
            return np.array([dx * PANEL * self.distance, 0.0, dz * PANEL * self.distance])
        return np.zeros(3)

    def actor_pos(self, scene, a, depth=0):
        a = choreo.actor_id(a)
        if isinstance(a, int) and 300 <= a < 400 and a in scene["locators"]:
            base, off = scene["locators"][a]
            return self.actor_pos(scene, base, depth + 1) + np.array(off, float)
        if isinstance(a, int) and 10000 <= a < 20000:          # 1xxxx = where actor xxxx stood at the start
            b = choreo.actor_id(a - 10000)
            return self.actor_base(b if b in (choreo.CASTER, choreo.TARGET) else choreo.CASTER)
        st = scene["actors"].get(a)
        if st is None and a not in (choreo.CASTER, choreo.TARGET):
            a = choreo.CASTER
            st = scene["actors"].get(a)
        p = self.actor_base(a) if a in (choreo.CASTER, choreo.TARGET) else self.actor_base(choreo.CASTER)
        if st and depth < 6:
            for base, off, f in st.get("place") or []:        # cmd_6642: each move from where the last ended
                q = self.actor_pos(scene, base, depth + 1) if choreo.actor_id(base) != a else p
                q = q + np.array(off, float)
                p = p + (q - p) * f
        off = np.array(st["offset"], float) if st else np.zeros(3)
        return p + off

    def slot_pos(self, scene, s):
        p = self.actor_pos(scene, s["actor"]) + np.array(s["pos"], float)
        for dst_actor, dst, f in s.get("fly") or []:
            q = self.actor_pos(scene, dst_actor) + np.array(dst, float)
            p = p + (q - p) * f
        return p

    def game_camera(self, cam, scene):
        c = scene["camera"]
        cam.focus = self.actor_pos(scene, c["actor"]) + np.array(c["offset"], float)
        z = c["zoom"] or DEFAULT_ZOOM
        if z < 0:
            z = DEFAULT_ZOOM + z
        cam.scale = 1.4 * DEFAULT_ZOOM / max(150.0, z)
        cam.pan = np.array([c.get("shake", 0.0) * 2.0, 0.0])
        cam.update()

    # ---------------------------------------------------------------- drawing
    def draw(self, qp: QPainter, w, h, scene, cam, t):
        qp.fillRect(0, 0, w, h, QColor("#15131c"))
        if self.show_grid:
            self._grid(qp, w, h, cam)
        items = []
        for a, num, pal in ((choreo.CASTER, self.caster_sprite, self.caster_palette),
                            (choreo.TARGET, self.target_sprite, self.target_palette)):
            st = scene["actors"].get(a)
            p = self.actor_pos(scene, a)
            _, d = cam.project(p[None], w, h)
            items.append((float(d[0]), "sprite", (a, num, pal, st, p)))
        for a, st in scene["actors"].items():           # extra actors: summoned sprites, copies of the caster
            if a in (choreo.CASTER, choreo.TARGET) or not (st.get("sprite") or st.get("copy")):
                continue
            if st.get("sprite"):
                num, pal = st["sprite"], 0
            else:
                num, pal = ((self.caster_sprite, self.caster_palette) if st["copy"] == choreo.CASTER
                            else (self.target_sprite, self.target_palette))
            p = self.actor_pos(scene, a)
            _, d = cam.project(p[None], w, h)
            items.append((float(d[0]), "sprite", (a, num, pal, st, p)))
        self.pick = {}                                   # slot -> (screen box x0, y0, x1, y1, centre) for picking
        for k, s in sorted(scene["slots"].items()):
            if k in self.hidden_slots:
                continue
            wp = self.slot_pos(scene, s)
            bias = 0.01 * (s.get("layer") or 0)
            c, _ = cam.project(wp[None], w, h)
            box = [c[0][0], c[0][1], c[0][0], c[0][1]]
            for batch in self.fx.triangles(s, wp, cam):
                tris = batch[3]
                pts, d = cam.project(tris.reshape(-1, 3), w, h)
                if len(pts):
                    lo, hi = pts.min(0), pts.max(0)
                    box = [min(box[0], lo[0]), min(box[1], lo[1]), max(box[2], hi[0]), max(box[3], hi[1])]
                pts = pts.reshape(-1, 3, 2)
                depth = self.fx.poly_depths(batch, d.reshape(-1, 3).mean(1))
                if not len(depth):
                    continue
                # one draw item per batch, its polygons back to front (glows add up: their order hardly shows)
                items.append((float(depth.mean()) + bias, "fx", (batch, pts, np.argsort(depth, kind="stable"),
                                                                 tris[..., 1].reshape(-1))))
            self.pick[k] = (box[0], box[1], box[2], box[3], (float(c[0][0]), float(c[0][1])))
        if self.particles is not None and self.parts is not None:
            fx, fz = FACING_DIRS.get(self.facing, (0.0, 1.0))
            axes = np.array([[fx, 0.0, fz], [0.0, 1.0, 0.0], [-fz, 0.0, fx]])      # local x / y / z -> world
            for p, m, age in self.particles.at(t):
                pos, size, rgba = particles.state(p, m, age)
                world = self.actor_pos(scene, p.actor) + p.base + pos @ axes
                pts, d = cam.project(world, w, h)
                items.append((float(d.mean()), "particles", (p.em, pts, size * cam.scale, rgba)))
        items.sort(key=lambda x: x[0])
        qp.setPen(Qt.PenStyle.NoPen)
        for _, kind, payload in items:
            if kind == "sprite":
                self._sprite(qp, w, h, cam, t, *payload)
            elif kind == "particles":
                self.parts.draw(qp, payload)
            else:
                batch, pts, order, height = payload
                self.fx.draw_batch(qp, batch, pts, order, height if self.floor_clip else None, self.floor)
        qp.setOpacity(1.0)
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.highlight is not None and self.highlight in scene["slots"]:
            p, _ = cam.project(self.slot_pos(scene, scene["slots"][self.highlight])[None], w, h)
            self._marker(qp, p[0], QColor("#e0457b"))
        fade = scene.get("fade") or 0
        if fade:
            qp.fillRect(0, 0, w, h, QColor(0, 0, 0, int(max(0, min(255, fade * 2.55)))))

    def marker_pos(self, scene, slot, cam, w, h):
        if slot not in scene["slots"]:
            return None
        p, _ = cam.project(self.slot_pos(scene, scene["slots"][slot])[None], w, h)
        return p[0]

    @staticmethod
    def _marker(qp, p, color):
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.setPen(QPen(color, 2))
        qp.drawEllipse(QPointF(p[0], p[1]), 9, 9)
        qp.drawLine(QPointF(p[0] - 14, p[1]), QPointF(p[0] + 14, p[1]))
        qp.drawLine(QPointF(p[0], p[1] - 14), QPointF(p[0], p[1] + 14))
        qp.setPen(Qt.PenStyle.NoPen)

    def _grid(self, qp, w, h, cam):
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        n = 5
        ends = []
        for i in range(-n, n + 1):
            a, b = (i - 0.5) * PANEL, (n + 0.5) * PANEL
            ends += [[a, 0, -b], [a, 0, b], [-b, 0, a], [b, 0, a]]
        p, _ = cam.project(np.array(ends), w, h)
        qp.setPen(QPen(QColor(70, 64, 96, 120), 1))
        for k in range(0, len(p), 2):
            qp.drawLine(QPointF(*p[k]), QPointF(*p[k + 1]))
        qp.setPen(Qt.PenStyle.NoPen)

    def _sprite(self, qp, w, h, cam, t, a, num, pal, st, p):
        pt, _ = cam.project(p[None], w, h)
        x, y = pt[0]
        # floor shadow
        qp.setOpacity(1.0)
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        qp.setBrush(QColor(0, 0, 0, 90))
        qp.drawEllipse(QPointF(x, y), 22 * cam.scale, 7 * cam.scale)
        motion = st["motion"] if st else 0
        mt = st["motion_time"] if st else t
        mt = mt * (st.get("speed") or 100) / 100.0 if st else mt
        tint = st["tint"] if st else [100, 100, 100, 100]
        sc = st["scale"] if st else [100, 100, 100]
        anim = st.get("anim") if st else None
        mirror = a == choreo.CASTER          # the sprites' front view faces left: the caster turns to the target
        f = None
        if num:
            if anim:                          # cmd_6500: an animation by id, minus = mirrored
                aid = abs(anim)
                a_ids = self.spr.file(num)[1]
                if aid not in a_ids:
                    aid = self.spr.anim_for(num, aid // 10)
                mirror = anim < 0
            else:
                aid = self.spr.anim_for(num, motion)
            f = self.spr.frame(num, aid, mt, pal, self.weapon if a == choreo.CASTER else None)
            if f is None:                        # nothing drawn at this moment: the idle pose instead
                for fb in (6001, 1001, 1, 11):
                    if fb != aid and fb in self.spr.file(num)[1]:
                        f = self.spr.frame(num, fb, mt, pal, self.weapon if a == choreo.CASTER else None)
                        if f is not None:
                            break
        s = cam.scale * SPRITE_SCALE
        if f is None:
            qp.setBrush(QColor("#e0457b") if a == choreo.CASTER else QColor("#6d8bd8"))
            qp.drawRoundedRect(QRectF(x - 14 * s, y - 70 * s, 28 * s, 70 * s), 6, 6)
            qp.setPen(QColor("#fff"))
            qp.setFont(QFont("Segoe UI", 8))
            qp.drawText(QRectF(x - 40, y - 70 * s - 18, 80, 16), Qt.AlignmentFlag.AlignCenter,
                        "Caster" if a == choreo.CASTER else "Target")
            qp.setPen(Qt.PenStyle.NoPen)
            return
        img, ox, oy = f
        sx = s * sc[0] / 100.0 * (-1 if mirror else 1)
        sy = s * sc[1] / 100.0
        qp.save()
        qp.translate(x, y)
        qp.scale(sx, sy)
        qp.setOpacity(max(0.0, min(1.0, tint[3] / 100.0)) if len(tint) > 3 else 1.0)
        qp.drawImage(QPointF(-ox, -oy), img)
        if any(abs(c - 100) > 3 for c in tint[:3]):
            # tint: brighten with Plus, darken with Multiply-like overlay
            over = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
            over.fill(Qt.GlobalColor.transparent)
            p2 = QPainter(over)
            p2.drawImage(0, 0, img)
            p2.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            r, g, b = (max(0, min(255, int((c - 100) * 2.55))) for c in tint[:3])
            if max(tint[:3]) > 100:
                p2.fillRect(over.rect(), QColor(r, g, b))
                p2.end()
                qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            else:
                k = [max(0, min(255, int(c * 2.55))) for c in tint[:3]]
                p2.fillRect(over.rect(), QColor(*k))
                p2.end()
                qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            qp.drawImage(QPointF(-ox, -oy), over)
        qp.restore()
