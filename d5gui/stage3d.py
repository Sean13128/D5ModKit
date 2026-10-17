"""The stage in 3D, as the battle shows it: the map's terrain with its textures, every unit standing on its panel as
its own sprite (idling), Geo Panels on the ground, the base panel -- seen through the game's battle camera (same
angle and lens), which the mouse moves like the skill editor's free camera: middle button or Alt+drag turns it,
Shift+middle or the right button pans, the wheel zooms, F fits the map, 1 is the battle view, 7 the top view.

It edits nothing itself: it reads the Stages page's MapCanvas (the map package, the visit shown, the selection) and
raises the same signals a click on the top-down map does (cell_clicked / cell_dragged), plus unit_clicked when the
click lands on a unit's sprite, so the page's tools (select / move, add enemy, Geo Symbol, paint, base panel) work in
both views.  Drawing is d5gui.skilledit.glrender (the skill preview's GPU renderer) with the map as its battlefield
and the units as actors of a still stage."""
import math
import time

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QSurfaceFormat
from PyQt6.QtOpenGL import QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from d5lib import battlemap, mapfile
from d5lib import stage as stg
from .skilledit import glrender

PANEL, MAP = stg.PANEL, stg.MAP
GEO_RGB = {1: (0.92, 0.18, 0.18), 2: (0.18, 0.80, 0.26), 3: (0.20, 0.38, 0.95), 4: (0.95, 0.86, 0.18),
           5: (0.68, 0.26, 0.88), 6: (0.18, 0.86, 0.90)}
BASE_RGB = (0.31, 0.64, 1.0)
SELECT_RGB = (1.0, 0.31, 0.55)
HOVER_RGB = (1.0, 1.0, 1.0)
GRID_RGB = (0.75, 0.78, 1.0)
BACKDROP = np.array([[0.16, 0.14, 0.30], [0.12, 0.13, 0.30], [0.05, 0.045, 0.09], [0.06, 0.05, 0.10]])
LIFT = 1.6                                        # overlays this far over the ground (script units)
FIT_DIST_MIN = 900.0


def gl_format():
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    return fmt


def facing_dir(deg):
    """.chr facing (0 = +y of the grid, 90 = +x) -> the actor's (x, z) direction"""
    a = math.radians(float(deg or 0))
    return (math.sin(a), math.cos(a))


class _Setup:
    """what glrender asks a stage setup for: the skill's panels (none) and the ground under a point"""
    area = reach = cursor = None

    def __init__(self, view):
        self.view = view

    def ground(self, x, z):
        return self.view.ground_at(x, z)


class _State:
    """a still stage: the units as actors, the map objects (3D models: boxes, cacti, pillars) as effect slots"""
    q = 0                                         # (no skill facing: models stand as placed)

    def __init__(self, view):
        self.frame = 0
        self.setup = _Setup(view)
        self.screen = stg.Screen()
        self.screen.back.to(BACKDROP)
        self.actors = {}
        self.slots = {}
        self.cam = stg.Camera((0.0, 0.0, 0.0), stg.DEFAULT_YAW)

    def slot_world(self, sl, _depth=0):
        return sl.pos.get()


class _Assets(glrender.Assets):
    """the skill preview's loaders plus the map objects' models (Object/Object_JP.dat: mapobj_*.obf)"""

    def model(self, eid):
        if isinstance(eid, str):
            if eid not in self.models:
                try:
                    from d5lib import obf
                    data = self.get(f"Object/Object_JP.dat/{eid}.obf")
                    self.models[eid] = glrender.ModelGPU(eid, obf.ObfFile(data))
                except Exception:
                    self.models[eid] = None
            return self.models[eid]
        return super().model(eid)


class _Renderer(glrender.GLRenderer):
    def __init__(self, assets, view):
        super().__init__(assets)
        self.view = view
        self.show_grid = False

    def build(self, st, view, w, h):
        world, screen = super().build(st, view, w, h)
        try:
            self.view.overlay(world)
        except Exception:
            pass
        return world, screen


class Stage3DView(QOpenGLWidget):
    cell_clicked = pyqtSignal(int, int, object)   # panel x, y, mouse button (as MapCanvas)
    cell_dragged = pyqtSignal(int, int)
    unit_clicked = pyqtSignal(int, object)        # index in chr.units, mouse button: the click hit its sprite
    hover_changed = pyqtSignal(object)            # (x, y) or None
    key_pressed = pyqtSignal(object)              # a QKeyEvent, before the view's own keys (accept it to take it)

    def __init__(self, ws, model, parent=None):
        super().__init__(parent)
        self.ws = ws
        self.model = model                        # the MapCanvas: pkg, base, names, selected, visit, visible(u)
        self.lookup = None                        # unit -> (sprite number, palette) or None (set by the page)
        self.setFormat(gl_format())
        self.gl = None
        self.gl_error = None
        self.r = None
        self.bm = None
        self._bm_key = None
        self.state = _State(self)
        self.placed = {}                          # unit index -> where it stands (actors and objects)
        self.cam = self.state.cam
        self.hover = None
        self.drag = None
        self.animate = True
        self.show_names = True
        self.show_grid = True
        self.show_geo = True
        self._fit_pending = True
        self._quads = None                        # projected panel quads of the last frame (for picking)
        self._boxes = {}                          # unit index -> screen box of its sprite / model
        self._extents = {}                        # model name -> (min, max) of its vertices
        self.message = ""
        self.marks = {}                           # "ghost": [(x, y)] block being placed, "sel": [(x, y)] chosen block
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 220)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Middle button / Alt+drag: turn the camera · Shift+middle or right drag: pan · wheel: zoom · "
                        "F: fit the map · 1: the battle's view · 7: from above · N: names on / off")

    # ---------------------------------------------------------------- data
    def _renderer(self):
        if self.r is None:
            mods = list(self.ws.mods.enabled_mods())
            a = self.ws.active_mod
            if a and all(m.id != a.id for m in mods):
                mods.append(a)

            def owner_read(vp):
                o = self.ws.owner(vp)
                return o.read_file(vp) if o else None
            assets = _Assets(self.ws.fs, mods, owner_read, members={})
            self.r = _Renderer(assets, self)
            try:
                self.r.shadow_sizes = self._shadow_sizes()
            except Exception:
                pass
        return self.r

    def _shadow_sizes(self):
        from .dbservice import get_service
        out = {}
        for r in get_service(self.ws).table("char.dat").rows:
            s, size = r.get("sprite_id"), r.get("size_radius")
            if s and size and s not in out:
                out[s] = int(size)
        return out

    def sync(self):
        """the map and the units from the model (called by the page whenever the top-down map redraws)"""
        pkg = self.model.pkg
        if pkg is None:
            self.bm = None
            self._bm_key = None
            self.state.actors = {}
            self.update()
            return
        key = (id(pkg), getattr(pkg, "rev", 0))
        if key != self._bm_key:
            try:
                self.bm = battlemap.from_package(pkg, getattr(self.model, "mid", 0) or 0)
                self.bm.rev = int(getattr(pkg, "rev", 0))        # a rebuilt terrain gets new GPU buffers
            except Exception as e:
                self.bm = None
                self.message = f"terrain not drawn: {e}"
            if self._bm_key is None or self._bm_key[0] != key[0]:
                self._fit_pending = True
                self.state.actors = {}
            self._bm_key = key
            if self.r is not None:
                self.r.set_map(self.bm, (0.0, 0.0, 0.0))
        actors, slots, placed = {}, {}, {}
        for i, u in enumerate(pkg.chr.units):
            if not u.on_map or not self.model.visible(u):
                continue
            look = self.lookup(u) if self.lookup else None
            if not look:
                continue
            num, pal = look
            pos = self.panel_pos(u.x, u.y)
            placed[i] = pos
            if num == "model":                        # a map object: its 3D model, turned as it faces
                sl = stg.Slot()
                sl.effect = pal
                sl.shown = True
                sl.pos.to(pos)
                sl.rot.to([0.0, float(u.facing or 0), 0.0])
                slots[i] = sl
                continue
            d = facing_dir(u.facing)
            old = self.state.actors.get(i)
            if old is not None and old.sprite == num and old.palette == pal:
                ac = old
                ac.pos = pos
                ac.dir = np.array(d, float)
            else:
                ac = stg.Actor(pos, num, pal, d)
                ac.mtime = float((i * 7) % 40)          # not every unit on the same frame of its idle
            actors[i] = ac
        self.state.actors = actors
        self.state.slots = slots
        self.placed = placed
        self.update()

    # ---------------------------------------------------------------- geometry
    def ground_at(self, x, z):
        """editor-frame height of the ground under (x, z) (script units; 0 off the panels)"""
        bm = self.bm
        if bm is None:
            return 0.0
        i, j = int(math.floor(x / PANEL)), int(math.floor(z / PANEL))
        if bm.has_panel(i, j):
            return float(bm.ground[i, j]) * MAP
        return 0.0

    def panel_pos(self, i, j):
        """where a unit on panel (i, j) stands"""
        h = float(self.bm.ground[i, j]) * MAP if self.bm is not None and self.bm.has_panel(i, j) else 0.0
        return np.array([(i + 0.5) * PANEL, h, (j + 0.5) * PANEL])

    def _panel_corners(self, i, j, lift=LIFT):
        y = self.ground_at((i + 0.5) * PANEL, (j + 0.5) * PANEL) + lift
        x0, x1, z0, z1 = i * PANEL, (i + 1) * PANEL, j * PANEL, (j + 1) * PANEL
        return np.array([[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]])

    def map_bounds(self):
        bm = self.bm
        if bm is None:
            return None
        live = ~bm.no_panel
        if not live.any():
            return None
        xs, zs = np.nonzero(live)
        g = bm.ground[live]
        return (xs.min() * PANEL, (xs.max() + 1) * PANEL, zs.min() * PANEL, (zs.max() + 1) * PANEL,
                float(g.min()) * MAP, float(g.max()) * MAP)

    # ---------------------------------------------------------------- camera
    def _view(self, w, h):
        return stg.GameView(self.state, w / max(1.0, h), viewport=(0.0, 0.0, float(w), float(h)))

    def fit(self):
        """the whole battlefield in view, from the battle camera's angle"""
        b = self.map_bounds()
        if b is None:
            return
        x0, x1, z0, z1, y0, y1 = b
        self.cam.target.to([(x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0])
        # the view's height on the ground covers the map's diagonal: dist = size / (2 tan(fov / 2)) at this lens
        size = math.hypot(x1 - x0, z1 - z0) * 0.78 + (y1 - y0) * 1.5 + 2 * PANEL
        pitch = float(self.cam.rot.get()[0])
        p11 = stg.lens_p11(float(self.cam.lens.get()[0]))
        dist = size / MAP * p11 / 2.0 / max(0.35, math.sin(pitch) + 0.25)
        self.cam.dist.to([max(FIT_DIST_MIN, dist)])
        self._fit_pending = False
        self.update()

    def view_preset(self, which):
        rot = self.cam.rot.get()
        if which == "battle":
            self.cam.rot.to([math.radians(stg.DEFAULT_PITCH), math.radians(stg.DEFAULT_YAW), 0.0])
        elif which == "top":
            self.cam.rot.to([math.radians(89.0), rot[1], 0.0])
        elif which == "low":
            self.cam.rot.to([math.radians(12.0), rot[1], 0.0])
        self.fit()

    def orbit(self, dx, dy):
        p, y, r = self.cam.rot.get()
        p = max(math.radians(2.0), min(math.radians(89.0), p + math.radians(dy * 0.3)))
        y = y - math.radians(dx * 0.4)
        self.cam.rot.to([p, y, r])
        self.update()

    def pan(self, dx, dy, w, h):
        v = self._view(w, h)
        d = v.unproject_delta(-dx, -dy)
        self.cam.target.to(self.cam.target.get() + d)
        self.update()

    def zoom(self, factor, at=None):
        w, h = self.width(), self.height()
        before = self._unproject_ground(at, w, h) if at is not None else None
        d = float(self.cam.dist.get()[0])
        self.cam.dist.to([max(200.0, min(60000.0, d * factor))])
        if before is not None:
            after = self._unproject_ground(at, w, h)
            if after is not None:
                self.cam.target.to(self.cam.target.get() + (before - after))
        self.update()

    def _unproject_ground(self, pt, w, h):
        """the point of the plane through the camera target (facing the camera) under a pixel"""
        v = self._view(w, h)
        t = self.cam.target.get()
        c, _ = v.project(t[None], w, h)
        d = v.unproject_delta(pt[0] - c[0, 0], pt[1] - c[0, 1])
        return t + d

    # ---------------------------------------------------------------- overlays (drawn in the world, under the units)
    def overlay(self, batch):
        if self.bm is None or self.r is None:
            return
        wr = self.r.white_rect() if hasattr(self.r, "white_rect") else self.r.atlas.white_rect()
        pkg = self.model.pkg
        pos, col = [], []

        def quad(c, rgb, a):
            pos.append(glrender._quad_tris(c[0], c[1], c[2], c[3]))
            col.append(np.tile(list(rgb) + [a], (6, 1)))

        def frame(c, rgb, a, e=PANEL * 0.07):
            x0, z0, x1, z1, y = c[0][0], c[0][2], c[2][0], c[2][2], c[0][1]
            for (ax, az, bx, bz) in ((x0, z0, x1, z0 + e), (x0, z1 - e, x1, z1), (x0, z0 + e, x0 + e, z1 - e),
                                     (x1 - e, z0 + e, x1, z1 - e)):
                pos.append(glrender._quad_tris([ax, y, az], [bx, y, az], [bx, y, bz], [ax, y, bz]))
                col.append(np.tile(list(rgb) + [a], (6, 1)))
        bm = self.bm
        if self.show_grid:
            e = PANEL * 0.02
            for i in range(bm.width):
                for j in range(bm.height):
                    if bm.has_panel(i, j):
                        frame(self._panel_corners(i, j, LIFT * 0.6), GRID_RGB, 0.16, e)
        if self.show_geo and pkg is not None:
            try:
                panels = pkg.gop.blocks[0].panels()
            except Exception:
                panels = []
            for x, y, c in panels:
                if c in GEO_RGB and bm.has_panel(x, y):
                    cs = self._panel_corners(x, y)
                    quad(cs, GEO_RGB[c], 0.40)
                    frame(cs, GEO_RGB[c], 0.85)
        if self.model.base and bm.has_panel(*self.model.base):
            cs = self._panel_corners(self.model.base[0], self.model.base[1], LIFT * 1.2)
            quad(cs, BASE_RGB, 0.16)
            frame(cs, BASE_RGB, 0.95, PANEL * 0.1)
        sel = self.model.selected
        if sel is not None and pkg is not None and 0 <= sel < len(pkg.chr.units):
            u = pkg.chr.units[sel]
            if u.on_map and bm.has_panel(u.x, u.y):
                cs = self._panel_corners(u.x, u.y, LIFT * 1.4)
                frame(cs, SELECT_RGB, 0.9 + 0.1 * math.sin(time.perf_counter() * 4), PANEL * 0.1)
        if self.hover is not None and bm.has_panel(*self.hover):
            frame(self._panel_corners(self.hover[0], self.hover[1], LIFT * 1.6), HOVER_RGB, 0.8, PANEL * 0.06)
        for x, y in self.marks.get("sel") or []:
            frame(self._panel_corners(x, y, LIFT * 1.8), (1.0, 0.55, 0.2), 0.9, PANEL * 0.09)
        for x, y in self.marks.get("ghost") or []:
            cs = self._panel_corners(x, y, LIFT * 2.0)
            quad(cs, (1.0, 0.82, 0.3), 0.22)
            frame(cs, (1.0, 0.82, 0.3), 0.9, PANEL * 0.07)
        if pos:
            p = np.concatenate(pos)
            batch.add(-9e7, glrender.BLEND_ALPHA, wr[0],
                      self.r._verts(p, np.zeros((len(p), 2)), np.tile(wr[1], (len(p), 1)), np.concatenate(col)),
                      glrender.AID_QUEUE)

    # ---------------------------------------------------------------- picking
    def _project_panels(self, view, w, h):
        bm = self.bm
        live = ~bm.no_panel
        xs, zs = np.nonzero(live)
        if not len(xs):
            self._quads = None
            return
        g = bm.ground[xs, zs] * MAP + LIFT
        X = np.stack([xs, xs + 1, xs + 1, xs], 1) * PANEL
        Z = np.stack([zs, zs, zs + 1, zs + 1], 1) * PANEL
        Y = np.repeat(g[:, None], 4, 1)
        pts = np.stack([X, Y, Z], -1).reshape(-1, 3)
        sp, depth = view.project(pts, w, h)
        self._quads = (xs, zs, sp.reshape(-1, 4, 2), depth.reshape(-1, 4).mean(axis=1))

    def panel_at(self, px, py):
        q = self._quads
        if q is None:
            return None
        xs, zs, sp, depth = q
        p = np.array([px, py])
        inside = np.ones(len(xs), bool)
        sign = None
        for k in range(4):
            a, b = sp[:, k], sp[:, (k + 1) % 4]
            cross = (b[:, 0] - a[:, 0]) * (p[1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (p[0] - a[:, 0])
            s = np.sign(cross)
            if sign is None:
                sign = s
            inside &= (s == sign) | (s == 0)
        if not inside.any():
            return None
        k = np.argmax(np.where(inside, depth, -np.inf))
        return int(xs[k]), int(zs[k])

    def _unit_boxes(self, view, w, h):
        """screen boxes of the units' sprites (nearest last)"""
        boxes = {}
        if self.r is None:
            return boxes
        right, up, back = self.r._cam_axes(view)
        for i, ac in self.state.actors.items():
            try:
                d3 = np.array([ac.dir[0], 0.0, ac.dir[1]])
                aid = self.r.assets.anim_for(ac.sprite, 0, float(d3 @ back) < 0)
                items = self.r.assets.sprite_items(ac.sprite, aid, ac.mtime) if aid is not None else []
            except Exception:
                items = []
            if not items:
                continue
            pts = []
            mirror = float(d3 @ right) > 0
            for _, it in items:
                for x, y in it.quad:
                    pts.append(ac.pos + right * (x * (-1.0 if mirror else 1.0)) + up * (-y))
            sp, depth = view.project(np.array(pts), w, h)
            boxes[i] = (sp[:, 0].min(), sp[:, 1].min(), sp[:, 0].max(), sp[:, 1].max(), float(depth.mean()))
        for i, sl in self.state.slots.items():
            m = self.r.assets.model(sl.effect)
            if m is None:
                continue
            ext = self._extents.get(sl.effect)
            if ext is None:
                pts = [g.pos for part in m.parts for g in part]
                pts = np.concatenate(pts) if pts else np.zeros((1, 3))
                ext = self._extents[sl.effect] = (pts.min(axis=0), pts.max(axis=0))
            lo, hi = ext
            R = glrender.rot_matrix(sl.rot.get(), sl.rot_order)
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            world = sl.pos.get() + (corners * glrender.MODEL_TO_SCRIPT) @ R.T
            sp, depth = view.project(world, w, h)
            boxes[i] = (sp[:, 0].min(), sp[:, 1].min(), sp[:, 0].max(), sp[:, 1].max(), float(depth.mean()))
        return boxes

    def unit_at(self, px, py):
        hits = [(b[4], i) for i, b in self._boxes.items() if b[0] <= px <= b[2] and b[1] <= py <= b[3]]
        return max(hits)[1] if hits else None

    # ---------------------------------------------------------------- GL
    def initializeGL(self):
        try:
            prof = QOpenGLVersionProfile()
            prof.setVersion(4, 1)
            prof.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            self.gl = QOpenGLVersionFunctionsFactory.get(prof, self.context())
            self.gl.initializeOpenGLFunctions()
        except Exception as ex:
            self.gl, self.gl_error = None, str(ex)

    def paintGL(self):
        w, h = self.width(), self.height()
        gl = self.gl
        err = self.gl_error
        qp = QPainter(self)
        qp.beginNativePainting()
        view = None
        try:
            if gl is not None and self.bm is not None:
                try:
                    r = self._renderer()
                    if r.map is not self.bm:
                        r.set_map(self.bm, (0.0, 0.0, 0.0))
                    if self._fit_pending:
                        self.fit()
                    view = self._view(w, h)
                    dpr = self.devicePixelRatioF()
                    r.paint(gl, w, h, self.state, view, viewport=(0, 0, int(round(w * dpr)), int(round(h * dpr))))
                    self._project_panels(view, w, h)
                    self._boxes = self._unit_boxes(view, w, h)
                except Exception as ex:
                    err = f"3D view error: {ex}"
                    import traceback
                    traceback.print_exc()
                dpr = self.devicePixelRatioF()
                gl.glViewport(0, 0, int(round(w * dpr)), int(round(h * dpr)))
            elif gl is not None:
                gl.glClearColor(0.06, 0.055, 0.10, 1.0)
                gl.glClear(0x4000 | 0x0100)
        finally:
            qp.endNativePainting()
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.bm is None:
            qp.fillRect(0, 0, w, h, QColor("#0b0d1d"))
            qp.setPen(QColor("#8a90b8"))
            qp.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, err or self.message or "Pick a stage")
            qp.end()
            return
        if err:
            qp.setPen(QColor("#ff6b6b"))
            qp.drawText(10, 20, err)
        elif view is not None:
            self._labels(qp, view, w, h)
        qp.end()

    def _labels(self, qp, view, w, h):
        pkg = self.model.pkg
        font = QFont("Segoe UI", 8)
        bold = QFont("Segoe UI", 8, QFont.Weight.Bold)
        if self.model.base and self.bm.has_panel(*self.model.base):
            c = self._panel_corners(self.model.base[0], self.model.base[1]).mean(axis=0)
            p, _ = view.project(c[None], w, h)
            qp.setFont(bold)
            qp.setPen(QColor("#4fa3ff"))
            qp.drawText(QRectF(p[0, 0] - 40, p[0, 1] - 8, 80, 16), Qt.AlignmentFlag.AlignCenter, "BASE")
        if self.show_names and pkg is not None:
            sets = pkg.chr.visit_sets()
            qp.setFont(font)
            for i, pos in self.placed.items():
                u = pkg.chr.units[i]
                p, _ = view.project(np.asarray(pos)[None], w, h)
                x, y = p[0, 0], p[0, 1] + 4
                label = self.model.names.get(u.char_id, str(u.char_id)).split(" (")[0][:14]
                if sets and self.model.visit is None and u.appears != mapfile.APPEARS_ALWAYS:
                    label += " ①" if u.appears == mapfile.APPEARS_FIRST else " ②"
                sel = i == self.model.selected
                tw = qp.fontMetrics().horizontalAdvance(label) + 8
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(QColor(255, 79, 139, 210) if sel else QColor(12, 10, 20, 170))
                qp.drawRoundedRect(QRectF(x - tw / 2, y, tw, 15), 4, 4)
                qp.setPen(QColor("#ffffff"))
                qp.drawText(QRectF(x - tw / 2, y, tw, 15), Qt.AlignmentFlag.AlignCenter, label)
        if self.hover is not None:
            qp.setFont(font)
            qp.setPen(QColor("#b8bde0"))
            qp.drawText(10, h - 10, f"panel {self.hover[0]}, {self.hover[1]}")

    # ---------------------------------------------------------------- animation
    def _tick(self):
        if not self.animate or not self.isVisible():
            return
        for ac in self.state.actors.values():
            ac.mtime += 1.0
        if self.state.actors or self.model.selected is not None:
            self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.timer.start()
        self.sync()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    # ---------------------------------------------------------------- mouse / keys
    def enterEvent(self, e):
        from PyQt6.QtWidgets import QApplication, QLineEdit, QAbstractSpinBox, QComboBox
        f = QApplication.focusWidget()
        if not isinstance(f, (QLineEdit, QAbstractSpinBox, QComboBox)):     # keys work where the mouse is
            self.setFocus()

    def leaveEvent(self, e):
        if self.hover is not None:
            self.hover = None
            self.hover_changed.emit(None)
            self.update()

    def mousePressEvent(self, e):
        p = e.position()
        mods = e.modifiers()
        btn = e.button()
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if btn == Qt.MouseButton.MiddleButton or (btn == Qt.MouseButton.LeftButton and alt):
            self.drag = dict(mode="pan" if shift else "orbit", x=p.x(), y=p.y())
            return
        if btn == Qt.MouseButton.RightButton:
            self.drag = dict(mode="rpress", x=p.x(), y=p.y(), x0=p.x(), y0=p.y())
            return
        if btn != Qt.MouseButton.LeftButton or self.bm is None:
            return
        u = self.unit_at(p.x(), p.y())
        if u is not None:
            self.drag = dict(mode="cell", x=p.x(), y=p.y(), last=None)
            self.unit_clicked.emit(u, btn)
            return
        cell = self.panel_at(p.x(), p.y())
        if cell is not None:
            self.drag = dict(mode="cell", x=p.x(), y=p.y(), last=cell)
            self.cell_clicked.emit(cell[0], cell[1], btn)

    def mouseMoveEvent(self, e):
        p = e.position()
        d = self.drag
        if not d:
            cell = self.panel_at(p.x(), p.y()) if self.bm is not None else None
            if cell != self.hover:
                self.hover = cell
                self.hover_changed.emit(cell)
                self.update()
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.unit_at(p.x(), p.y()) is not None
                           else Qt.CursorShape.ArrowCursor)
            return
        dx, dy = p.x() - d["x"], p.y() - d["y"]
        d["x"], d["y"] = p.x(), p.y()
        m = d["mode"]
        if m == "orbit":
            self.orbit(dx, dy)
        elif m == "pan":
            self.pan(dx, dy, self.width(), self.height())
        elif m == "rpress":
            if abs(p.x() - d["x0"]) + abs(p.y() - d["y0"]) > 3:
                d["mode"] = "pan"
                self.pan(dx, dy, self.width(), self.height())
        elif m == "cell":
            cell = self.panel_at(p.x(), p.y())
            if cell is not None and cell != d["last"]:
                d["last"] = cell
                self.hover = cell
                self.cell_dragged.emit(cell[0], cell[1])

    def mouseReleaseEvent(self, e):
        d = self.drag
        self.drag = None
        if d and d["mode"] == "rpress":
            p = e.position()
            cell = self.panel_at(p.x(), p.y()) if self.bm is not None else None
            if cell is not None:
                self.cell_clicked.emit(cell[0], cell[1], Qt.MouseButton.RightButton)

    def wheelEvent(self, e):
        f = 1 / 1.15 if e.angleDelta().y() > 0 else 1.15
        p = e.position()
        self.zoom(f, (p.x(), p.y()))

    def mouseDoubleClickEvent(self, e):
        if self.unit_at(e.position().x(), e.position().y()) is None and self.panel_at(
                e.position().x(), e.position().y()) is None:
            self.fit()

    def keyPressEvent(self, e):
        e.setAccepted(False)
        self.key_pressed.emit(e)
        if e.isAccepted():
            return
        k = e.key()
        if k == Qt.Key.Key_F:
            self.fit()
        elif k == Qt.Key.Key_1:
            self.view_preset("battle")
        elif k == Qt.Key.Key_7:
            self.view_preset("top")
        elif k == Qt.Key.Key_3:
            self.view_preset("low")
        elif k == Qt.Key.Key_N:
            self.show_names = not self.show_names
            self.update()
        elif k == Qt.Key.Key_G:
            self.show_grid = not self.show_grid
            self.update()
        else:
            super().keyPressEvent(e)
