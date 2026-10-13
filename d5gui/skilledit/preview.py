"""The skill preview viewport -- most editing happens here (works like Blender's 3D view).

Tools (bar at the top left, or keys): Select (Q), Move (G), Rotate (R), Scale (S).
  click an effect          select it (Shift: add / remove)           drag on empty space  box select
  drag a selected effect   move it along the floor (Shift: up / down; any tool)
  Move tool                drag an arrow: along that axis · the square: along the floor
  Rotate tool              drag the ring: turn the effects around the pivot (pivot "Each its own": turn each picture)
  Scale tool               drag a corner: size and / or spacing (see "Scale")
Keys (mouse over the view)
  G / R / S                move / rotate / scale with the mouse; then X, Y (up), Z lock an axis, type a number for an
                           exact value, Enter or click = done, Esc or right-click = cancel; Ctrl snaps, Shift is finer
  Delete / X               delete the selected effects            Shift+D   duplicate them (then move)
  A / Alt+A                select all / none                       F         frame the selection
  numpad 1 / 3 / 7         front / side / top view                 Home      reset the view
  C                        game camera <-> free camera
Camera: the view starts on the GAME CAMERA (the skill's own camera, as the game shows it; the badge at the top right
says which one is on).  Looking around (middle-drag or Alt+drag orbit, Shift+middle or right-drag pan) switches to
the FREE CAMERA; then the wheel zooms.  Click the badge, press C or play the skill to go back to the game camera.
Right-click an effect for a menu."""
import math
import time

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPointF, QRectF, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QPolygonF, QCursor, QSurfaceFormat
from PyQt6.QtOpenGL import QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QToolButton, QComboBox, QLabel, QButtonGroup, QMenu,
                             QApplication, QLineEdit, QAbstractSpinBox, QFrame)

from .render import Camera


def gl_format():
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    return fmt

RING = 70.0
ACCENT = QColor("#e0457b")
GIZMO = QColor("#ffd166")
AXES = {"x": (np.array([1.0, 0, 0]), QColor("#ff5c6c")), "y": (np.array([0, 1.0, 0]), QColor("#7ee36a")),
        "z": (np.array([0, 0, 1.0]), QColor("#5aa9ff"))}
TOOLS = [("select", "Select", "Select (Q) — click or box-select effects; drag a selected one to move it"),
         ("move", "Move", "Move (G) — arrows move along one axis, the square along the floor"),
         ("rotate", "Rotate", "Rotate (R) — drag the ring to turn the selection around the pivot"),
         ("scale", "Scale", "Scale (S) — drag a corner to make them bigger / smaller or spread them out")]
PIVOTS = [("Selection centre", "centre"), ("Caster", "caster"), ("Target", "target"), ("Each its own", "own")]
SCALE_MODES = [("Size + spacing", "both"), ("Size only", "size"), ("Spacing only", "spacing")]
HINTS = {
    "select": "click: select · Shift+click: add · drag empty: box · drag effect: move · G R S · Del · Shift+D",
    "move": "drag an arrow: along it · the square: along the floor (Shift: up / down) · or press G",
    "rotate": "drag the ring: turn around the pivot (pivot 'Each its own': turn each picture) · or press R",
    "scale": "drag a corner: outward = bigger / further apart, inward = smaller / closer · or press S",
}


class PreviewView(QOpenGLWidget):
    gizmoStart = pyqtSignal()
    gizmoDrag = pyqtSignal(str, object)        # move (world vec) / turn (deg) / roll (deg) / size / spread (factor)
    gizmoEnd = pyqtSignal()
    gizmoCancel = pyqtSignal()
    pickRequested = pyqtSignal(list, str)      # slots, mode: replace | add | toggle
    deleteRequested = pyqtSignal()
    duplicateRequested = pyqtSignal()          # then the view starts a move
    selectAllRequested = pyqtSignal(bool)      # True: all effects on screen, False: none
    menuRequested = pyqtSignal(object, object)  # global QPoint, slot under the mouse or None
    toolChanged = pyqtSignal(str)
    pivotChanged = pyqtSignal(str)
    clicked = pyqtSignal()
    cameraFreed = pyqtSignal()                  # the user moved the view: the free camera took over
    cameraChanged = pyqtSignal(bool)            # True: the game camera is on (badge, C, play)

    def __init__(self, renderer):
        super().__init__()
        self.r = renderer
        self.cam = Camera()
        self.game_cam = False
        self.free_pinned = False          # the free camera was picked on purpose (badge / C): play keeps it
        self._hint = ("", 0.0)            # a short message over the status line (text, until perf_counter())
        self.scene = None
        self.frame = 0
        self.drag = None
        self.modal = None
        self.fps = 0.0
        self._last = time.perf_counter()
        self.overlay = ""
        self.gizmo = None                 # callable -> dict(points, shown, paths, centre, pivot) in world, or None
        self.show_paths = True
        self.hover = None
        self.tool = "select"
        self.setFormat(gl_format())
        self.gl = None
        self.gl_error = None
        self.hud = None                  # hud.Hud (set by the editor)
        self.hud_title = ""
        self.show_hud = True
        self.setMinimumSize(320, 220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_bar()

    # ---------------------------------------------------------------- tool bar (inside the view)
    def _build_bar(self):
        self.bar = QFrame(self)
        self.bar.setObjectName("viewBar")
        self.bar.setStyleSheet("#viewBar { background: rgba(23, 21, 31, 215); border: 1px solid #3a3553; "
                               "border-radius: 8px; } QToolButton { min-width: 26px; padding: 3px 6px; } "
                               "QLabel { color: #b9b4cc; }")
        lay = QHBoxLayout(self.bar)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        self.tool_group = QButtonGroup(self)
        self.tool_btns = {}
        for key, label, tip in TOOLS:
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip)
            b.setCheckable(True)
            self.tool_group.addButton(b)
            b.clicked.connect(lambda _, k=key: self.set_tool(k))
            lay.addWidget(b)
            self.tool_btns[key] = b
        self.tool_btns["select"].setChecked(True)
        lay.addSpacing(6)
        self.pivot = QComboBox()
        for label, key in PIVOTS:
            self.pivot.addItem(f"Pivot: {label.lower()}", key)
        self.pivot.setToolTip("What rotating and scaling happen around")
        self.pivot.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.pivot.currentIndexChanged.connect(lambda _: (self.pivotChanged.emit(self.pivot.currentData()),
                                                          self.update()))
        lay.addWidget(self.pivot)
        self.scale_mode = QComboBox()
        for label, key in SCALE_MODES:
            self.scale_mode.addItem(f"Scales: {label.lower()}", key)
        self.scale_mode.setToolTip("What the Scale tool changes: how big the effects are, how far apart they are "
                                   "(from the pivot), or both")
        lay.addWidget(self.scale_mode)
        lay.addSpacing(6)
        self.paths_btn = QToolButton()
        self.paths_btn.setText("Paths")
        self.paths_btn.setCheckable(True)
        self.paths_btn.setChecked(True)
        self.paths_btn.setToolTip("Show the selected effects' flight paths")
        self.paths_btn.toggled.connect(self._paths_toggled)
        lay.addWidget(self.paths_btn)
        self.views = QComboBox()
        for label, key in (("View", None), ("Angled (Home)", "home"), ("Front (1)", "front"), ("Side (3)", "side"),
                           ("Top (7)", "top"), ("Frame the selection (F)", "frame")):
            self.views.addItem(label, key)
        self.views.setToolTip("Look from the front, side or top (numpad 1 / 3 / 7), the angled view (Home), or zoom "
                              "onto the selection (F)")
        self.views.activated.connect(self._view_picked)
        lay.addWidget(self.views)
        self._tool_options()
        self.bar.move(8, 8)
        # which camera is on, always in sight: the game's own (green) or the free one (orange, click to go back)
        self.cam_badge = QToolButton(self)
        self.cam_badge.setObjectName("camBadge")
        self.cam_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cam_badge.clicked.connect(self._badge_clicked)
        self._badge()

    def _badge(self):
        b = self.cam_badge
        if self.game_cam:
            b.setText("🎥  Game camera")
            b.setToolTip("You see the skill through its own camera, as in the game (it moves with the skill).\n"
                         "Look around with the middle mouse button (or Alt + drag) or pan with the right one: that "
                         "switches to a free camera.  C or a click here switches too.")
            b.setStyleSheet("#camBadge { background: rgba(32, 92, 58, 225); color: #d6ffe4; border: 1px solid "
                            "#3fae6e; border-radius: 10px; padding: 4px 10px; font-weight: 600; }")
        else:
            b.setText("🕹  Free camera  ·  ↩ back to the game camera (C)")
            b.setToolTip("The skill's own camera is off: the view stays where you put it.\nClick (or press C, or "
                         "play the skill) to see it through the game camera again.")
            b.setStyleSheet("#camBadge { background: rgba(150, 82, 20, 235); color: #fff1dc; border: 1px solid "
                            "#ffb05c; border-radius: 10px; padding: 4px 10px; font-weight: 600; }")
        b.adjustSize()
        self._place_badge()

    def _place_badge(self):
        b = getattr(self, "cam_badge", None)
        if b is not None:
            b.move(max(8, self.width() - b.width() - 8), 8)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_badge()

    def _badge_clicked(self):
        self.set_game_camera(not self.game_cam, pinned=True)

    def set_game_camera(self, on, pinned=False):
        """switch between the game camera and the free one (pinned: picked on purpose, so play keeps it)"""
        on = bool(on)
        if on == self.game_cam:
            self.free_pinned = pinned and not on
            return
        if on:
            self.game_cam, self.free_pinned = True, False
        else:
            self.free_camera()
            self.free_pinned = pinned
        self._badge()
        self.cameraChanged.emit(self.game_cam)
        self.update()

    def flash(self, text, seconds=2.5):
        """a short message over the status line"""
        self._hint = (text, time.perf_counter() + seconds)
        self.update()

    def _view_picked(self, k):
        key = self.views.itemData(k)
        if key == "frame":
            self.frame_selected()
        elif key:
            self.view_preset(key)
        self.views.setCurrentIndex(0)

    def _tool_options(self):
        """only what the tool uses: the pivot for Rotate / Scale, what Scale changes for Scale"""
        self.pivot.setVisible(self.tool in ("rotate", "scale"))
        self.scale_mode.setVisible(self.tool == "scale")
        self.bar.adjustSize()

    def _paths_toggled(self, on):
        self.show_paths = on
        self.update()

    def set_tool(self, key):
        self.tool = key
        self.tool_btns[key].setChecked(True)
        self._tool_options()
        self.toolChanged.emit(key)
        self.update()

    def pivot_mode(self):
        return self.pivot.currentData()

    def sizeHint(self):
        return QSize(900, 520)

    def show_scene(self, scene, frame):
        self.scene, self.frame = scene, frame
        self.update()

    def face(self, facing):
        """turn the free camera so that the caster -> target line runs left to right"""
        from .render import FACING_DIRS
        dx, dz = FACING_DIRS.get(facing, (0.0, 1.0))
        self.cam.yaw = float(np.degrees(np.arctan2(dz, dx))) - 18.0
        self.cam.focus = self.r.actor_base(1256) * 0.5 + self.r.actor_base(3600) * 0.5 + np.array([0, 50.0, 0])
        self.cam.update()
        self.update()

    def view_preset(self, which):
        from .render import FACING_DIRS
        base = self.cam.yaw
        try:
            dx, dz = FACING_DIRS.get(self.r.facing, (0.0, 1.0))
            base = float(np.degrees(np.arctan2(dz, dx)))
        except Exception:
            pass
        if which == "front":
            self.cam.yaw, self.cam.pitch = base, 2.0
        elif which == "side":
            self.cam.yaw, self.cam.pitch = base + 90.0, 2.0
        elif which == "top":
            self.cam.yaw, self.cam.pitch = base, 89.0
        else:
            self.cam.yaw, self.cam.pitch, self.cam.scale = base - 18.0, 26.0, 1.4
            self.cam.pan = np.array([0.0, 0.0])
        self.cam.update()
        self.update()

    def frame_selected(self):
        g = self.gizmo() if self.gizmo else None
        if not g:
            return
        pts = np.array(g["points"] + [p for path in (g.get("paths") or []) for p in path])
        lo, hi = pts.min(0), pts.max(0)
        self.cam.focus = (lo + hi) / 2.0
        span = max(80.0, float(np.max(hi - lo)))
        self.cam.scale = max(0.15, min(12.0, 0.7 * min(self.width(), self.height()) / span))
        self.cam.pan = np.array([0.0, 0.0])
        self.cam.update()
        self.update()

    def _cam_used(self):
        if self.game_cam and self.scene is not None and self.r is not None:
            v = self.r.game_view(self.scene, self.width(), self.height())
            if v is not None:
                return v
        return self.cam

    def free_camera(self):
        """take the game camera's view over into the free camera (the user starts moving around)"""
        if not (self.game_cam and self.scene is not None and self.r is not None):
            return
        v = self.r.game_view(self.scene, self.width(), self.height())
        if v is None:
            return
        self.cam.yaw = math.degrees(math.atan2(v.right[2], v.right[0]))
        self.cam.pitch = max(-10.0, min(89.0, v.pitch_deg))
        self.cam.focus = np.array(v.focus, float)
        self.cam.scale = max(0.15, min(12.0, v.scale))
        self.cam.pan = np.array([0.0, 0.0])
        self.cam.update()
        self.game_cam = False
        self._badge()
        self.cameraFreed.emit()
        self.cameraChanged.emit(False)

    # ---------------------------------------------------------------- picking
    def slot_at(self, p):
        """the effect slot drawn under screen point p (the smallest box containing it), or None"""
        best, area = None, None
        for slot, (x0, y0, x1, y1, c) in (getattr(self.r, "pick", None) or {}).items():
            if x0 - 6 <= p.x() <= x1 + 6 and y0 - 6 <= p.y() <= y1 + 6:
                a = max(1.0, (x1 - x0) * (y1 - y0))
                if (math.hypot(c[0] - p.x(), c[1] - p.y()) < 14) and (best is None or a < area * 4):
                    a = 0.5                           # right on its centre: wins
                if best is None or a < area:
                    best, area = slot, a
        return best

    def slots_in(self, x0, y0, x1, y1):
        xa, xb = sorted((x0, x1))
        ya, yb = sorted((y0, y1))
        return [s for s, (bx0, by0, bx1, by1, c) in (getattr(self.r, "pick", None) or {}).items()
                if xa <= c[0] <= xb and ya <= c[1] <= yb]

    # ---------------------------------------------------------------- gizmo geometry
    def _gizmo_screen(self):
        if self.gizmo is None or self.scene is None or self.r is None:
            return None
        info = self.gizmo()
        if not info:
            return None
        cam, w, h = self._cam_used(), self.width(), self.height()
        pts, _ = cam.project(np.array(info["points"]), w, h)
        c, _ = cam.project(np.array([info["centre"], info["pivot"]]), w, h)
        paths = []
        for poly in info.get("paths") or []:
            if len(poly) > 1:
                pp, _ = cam.project(np.array(poly), w, h)
                paths.append(pp)
        axes = {}
        for k, (v, col) in AXES.items():
            q, _ = cam.project(np.array([info["centre"], info["centre"] + v]), w, h)
            d = q[1] - q[0]
            n = np.hypot(*d)
            axes[k] = (d / n if n > 1e-6 else np.array([0.0, 0.0]), n)       # screen direction, px per unit
        return dict(points=pts, shown=info.get("shown") or [True] * len(pts), centre=c[0], pivot=c[1],
                    paths=paths, axes=axes, info=info)

    def _handle_at(self, g, p):
        if g is None:
            return None
        cx, cy = g["centre"]
        if self.tool == "move":
            if (p.x() - cx) ** 2 + (p.y() - cy) ** 2 <= 11 ** 2:
                return ("move", None)
            for k, (d, n) in g["axes"].items():
                if n < 1e-3 or not d.any():
                    continue
                tip = np.array([cx, cy]) + d * 62
                if (p.x() - tip[0]) ** 2 + (p.y() - tip[1]) ** 2 <= 11 ** 2:
                    return ("move", k)
                # along the shaft
                rel = np.array([p.x() - cx, p.y() - cy])
                t = float(np.dot(rel, d))
                if 14 <= t <= 62 and abs(d[0] * rel[1] - d[1] * rel[0]) <= 6:
                    return ("move", k)
        elif self.tool == "rotate":
            px, py = (cx, cy) if self.pivot_mode() == "own" else g["pivot"]
            if abs(math.hypot(p.x() - px, p.y() - py) - RING) <= 9:
                return ("rotate", None)
        elif self.tool == "scale":
            for sx in (-1, 1):
                for sy in (-1, 1):
                    hx, hy = cx + sx * 46, cy + sy * 46
                    if abs(p.x() - hx) <= 9 and abs(p.y() - hy) <= 9:
                        return ("scale", None)
        return None

    # ---------------------------------------------------------------- paint
    def initializeGL(self):
        try:
            prof = QOpenGLVersionProfile()
            prof.setVersion(4, 1)
            prof.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            self.gl = QOpenGLVersionFunctionsFactory.get(prof, self.context())
            self.gl.initializeOpenGLFunctions()
        except Exception as ex:                  # no OpenGL 4.1: say so in the view
            self.gl, self.gl_error = None, str(ex)

    def paintGL(self):
        w, h = self.width(), self.height()
        gl = self.gl
        err = self.gl_error
        qp = QPainter(self)
        qp.beginNativePainting()                  # the GPU scene first; Qt's painter takes over afterwards
        try:
            if gl is not None and self.scene is not None and self.r is not None:
                cam = self._cam_used()
                try:
                    vp = getattr(cam, "viewport", None)
                    self.r.paint(gl, w, h, self.scene, cam, self.devicePixelRatioF(), vp)
                except Exception as ex:
                    err = f"preview error: {ex}"
                dpr = self.devicePixelRatioF()
                gl.glViewport(0, 0, int(round(w * dpr)), int(round(h * dpr)))
            elif gl is not None:
                gl.glClearColor(0.08, 0.075, 0.11, 1.0)
                gl.glClear(0x4000 | 0x0100)
        finally:
            qp.endNativePainting()
        if self.scene is None:
            qp.fillRect(0, 0, w, h, QColor("#15131c"))
            qp.setPen(QColor("#8e89a6"))
            qp.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, err or "Pick a skill")
            qp.end()
            return
        if err:
            qp.setPen(QColor("#ff6b6b"))
            qp.drawText(10, 60, err)
        elif self.game_cam and self.show_hud and self.hud is not None and self.r is not None:
            cam = self._cam_used()
            if getattr(cam, "viewport", None):
                try:
                    self.hud.draw(qp, cam.viewport, self.r.stage_at(self.scene), cam, self.hud_title, w, h)
                except Exception:
                    pass
        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        if 0 < dt < 1:
            self.fps = self.fps * 0.9 + (1.0 / dt) * 0.1
        qp.setOpacity(1.0)
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            self._draw_gizmo(qp)
        except Exception:
            pass
        if self.drag and self.drag.get("mode") == "box":
            d = self.drag
            qp.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine))
            qp.setBrush(QColor(255, 255, 255, 25))
            qp.drawRect(QRectF(min(d["x0"], d["x"]), min(d["y0"], d["y"]), abs(d["x"] - d["x0"]),
                               abs(d["y"] - d["y0"])))
        # status / hint line
        qp.setFont(QFont("Segoe UI", 9))
        if self.modal:
            txt = self._modal_text()
            qp.fillRect(QRectF(0, h - 28, w, 28), QColor(30, 26, 44, 230))
            qp.setPen(QColor("#ffd166"))
            qp.drawText(QRectF(10, h - 28, w - 20, 28), Qt.AlignmentFlag.AlignVCenter, txt)
        elif self._hint[0] and time.perf_counter() < self._hint[1]:
            qp.fillRect(QRectF(0, h - 28, w, 28), QColor(30, 26, 44, 230))
            qp.setPen(QColor("#ffd166"))
            qp.drawText(QRectF(10, h - 28, w - 20, 28), Qt.AlignmentFlag.AlignVCenter, self._hint[0])
        else:
            qp.setPen(QColor("#9a95b0"))
            n = len(self.scene["slots"])
            qp.drawText(QRectF(10, h - 24, w - 20, 20), Qt.AlignmentFlag.AlignVCenter,
                        f"frame {self.frame} · {n} effect{'s' if n != 1 else ''} on screen · "
                        f"{'game camera' if self.game_cam else 'free camera (C: game camera)'}   —   "
                        f"{HINTS[self.tool]}")
        qp.end()

    def _draw_gizmo(self, qp):
        g = self._gizmo_screen()
        if g is None:
            return
        hov = self.drag["handle"] if self.drag and self.drag.get("mode") == "gizmo" else self.hover
        if self.show_paths:
            for pp in g["paths"]:
                qp.setPen(QPen(QColor(124, 214, 255, 150), 1.5, Qt.PenStyle.DashLine))
                for a, b in zip(pp[:-1], pp[1:]):
                    qp.drawLine(QPointF(*a), QPointF(*b))
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(QColor(124, 214, 255, 200))
                qp.drawEllipse(QPointF(*pp[-1]), 3, 3)
        for (x, y), on in zip(g["points"], g["shown"]):
            col = QColor(ACCENT)
            if not on:
                col.setAlpha(90)
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.setPen(QPen(col, 2))
            qp.drawEllipse(QPointF(x, y), 8, 8)
        cx, cy = g["centre"]
        px, py = g["pivot"]
        if self.pivot_mode() != "own" and self.tool in ("rotate", "scale"):
            qp.setPen(QPen(QColor(255, 209, 102, 160), 1))
            qp.drawLine(QPointF(px - 7, py), QPointF(px + 7, py))
            qp.drawLine(QPointF(px, py - 7), QPointF(px, py + 7))
        if self.tool == "move":
            for k, (d, n) in g["axes"].items():
                if n < 1e-3 or not d.any():
                    continue
                col = QColor(AXES[k][1])
                if hov == ("move", k):
                    col = col.lighter(140)
                tip = QPointF(cx + d[0] * 62, cy + d[1] * 62)
                qp.setPen(QPen(QColor(0, 0, 0, 170), 6))          # dark outline: readable over bright effects
                qp.drawLine(QPointF(cx + d[0] * 12, cy + d[1] * 12), tip)
                qp.setPen(QPen(col, 3))
                qp.drawLine(QPointF(cx + d[0] * 12, cy + d[1] * 12), tip)
                qp.setBrush(col)
                nrm = np.array([-d[1], d[0]])
                pts = [tip + QPointF(d[0] * 10, d[1] * 10), tip + QPointF(nrm[0] * 6, nrm[1] * 6),
                       tip - QPointF(nrm[0] * 6, nrm[1] * 6)]
                qp.setPen(Qt.PenStyle.NoPen)
                qp.drawPolygon(QPolygonF(pts))
                qp.setPen(col)
                qp.drawText(QPointF(tip.x() + d[0] * 16 - 4, tip.y() + d[1] * 16 + 4), k.upper())
            qp.setPen(QPen(QColor("#1b1925"), 1))
            qp.setBrush(GIZMO if hov == ("move", None) else QColor("#f0b84a"))
            qp.drawRect(QRectF(cx - 7, cy - 7, 14, 14))
        elif self.tool == "rotate":
            rx, ry = (cx, cy) if self.pivot_mode() == "own" else (px, py)
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.setPen(QPen(QColor(0, 0, 0, 160), 7))
            qp.drawEllipse(QPointF(rx, ry), RING, RING)
            qp.setPen(QPen(GIZMO if hov == ("rotate", None) else QColor(255, 209, 102, 170),
                           4 if hov == ("rotate", None) else 2.5))
            qp.drawEllipse(QPointF(rx, ry), RING, RING)
        elif self.tool == "scale":
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.setPen(QPen(QColor(255, 209, 102, 120), 1, Qt.PenStyle.DashLine))
            qp.drawRect(QRectF(cx - 46, cy - 46, 92, 92))
            qp.setPen(QPen(QColor("#1b1925"), 1))
            qp.setBrush(GIZMO if hov == ("scale", None) else QColor("#f0b84a"))
            for sx in (-1, 1):
                for sy in (-1, 1):
                    qp.drawRect(QRectF(cx + sx * 46 - 6, cy + sy * 46 - 6, 12, 12))
        if self.drag and self.drag.get("mode") in ("gizmo", "dragmove"):
            qp.setPen(QColor("#ffffff"))
            qp.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            qp.drawText(QPointF(cx + 16, cy - 14), self._value_text(self.drag))

    @staticmethod
    def _value_text(d):
        k, v = d.get("kind"), d.get("value")
        if k == "move":
            return "move  x %+.0f  y %+.0f  z %+.0f" % tuple(v)
        if k in ("turn", "roll"):
            return f"rotate {v:+.0f}°"
        if k == "scale":
            return f"scale ×{v:.2f}"
        return ""

    def _modal_text(self):
        m = self.modal
        axis = f"  ({m['axis'].upper()} axis)" if m.get("axis") else ""
        typed = f"  [{m['typed']}]" if m.get("typed") else ""
        what = {"move": "Move", "rotate": "Rotate", "scale": "Scale"}[m["op"]]
        return (f"{what}: {self._value_text(m)}{axis}{typed}     —   Enter / click: done · Esc / right-click: cancel · "
                f"X Y Z: lock an axis · type a number · Ctrl: snap · Shift: fine")

    # ---------------------------------------------------------------- transform values
    def _move_from(self, cam, g, dx, dy, axis, shift):
        k = 0.2 if shift else 1.0
        if axis:
            d, n = g["axes"][axis]
            if n < 1e-6:
                return np.zeros(3)
            amount = (dx * d[0] + dy * d[1]) / n * k
            return AXES[axis][0] * amount
        return self._floor_delta(cam, dx * k, dy * k, False)

    def _floor_delta(self, cam, dx, dy, vertical):
        if vertical:
            return np.array([0.0, -dy / cam.scale, 0.0])
        right = np.array([cam.right[0], 0.0, cam.right[2]])
        fwd = np.array([cam.up[0], 0.0, cam.up[2]])
        n = np.linalg.norm(fwd)
        fwd = fwd / n if n > 1e-6 else np.array([0.0, 0.0, -1.0])
        right /= max(1e-6, np.linalg.norm(right))
        k = 1.0 / cam.scale
        return right * dx * k - fwd * dy * k / max(0.3, np.sin(np.radians(cam.pitch)))

    def _turn_sign(self, cam):
        w, h = self.width(), self.height()
        a = np.array([[0.0, 0.0, 0.0], [100.0, 0.0, 0.0], [math.cos(0.2) * 100, 0.0, math.sin(0.2) * 100]])
        p, _ = cam.project(a, w, h)
        v1, v2 = p[1] - p[0], p[2] - p[0]
        return 1.0 if v1[0] * v2[1] - v1[1] * v2[0] > 0 else -1.0

    def _emit_value(self, d):
        """send the drag / modal value to the editor in its terms"""
        k, v = d["kind"], d["value"]
        if k == "move":
            self.gizmoDrag.emit("move", np.array(v, float))
        elif k == "rotate":
            self.gizmoDrag.emit("roll" if self.pivot_mode() == "own" else "turn", float(v))
        elif k == "scale":
            mode = self.scale_mode.currentData()
            if self.pivot_mode() == "own" or mode == "size":
                self.gizmoDrag.emit("size", float(v))
            elif mode == "spacing":
                self.gizmoDrag.emit("spread", float(v))
            else:
                self.gizmoDrag.emit("both", float(v))

    @staticmethod
    def _snap(kind, v):
        if kind == "move":
            return np.round(np.array(v) / 10.0) * 10.0
        if kind == "rotate":
            return round(v / 15.0) * 15.0
        if kind == "scale":
            return max(0.05, round(v * 10) / 10.0)
        return v

    # ---------------------------------------------------------------- modal (G / R / S)
    def start_modal(self, op):
        g = self._gizmo_screen()
        if g is None:
            return False
        p = self.mapFromGlobal(QCursor.pos())
        piv = g["centre"] if (op != "move" and self.pivot_mode() == "own") else g["pivot"]
        if op == "rotate" and self.pivot_mode() != "own":
            piv = g["pivot"]
        self.modal = dict(op=op, kind=op if op != "rotate" else "rotate", x0=p.x(), y0=p.y(), x=p.x(), y=p.y(),
                          axis=None, typed="", g=g, piv=piv,
                          value=np.zeros(3) if op == "move" else (0.0 if op == "rotate" else 1.0))
        self.gizmoStart.emit()
        self.setFocus()
        self.update()
        return True

    def _modal_update(self, mods=Qt.KeyboardModifier.NoModifier):
        m = self.modal
        g = m["g"]
        cam = self._cam_used()
        typed = None
        if m["typed"] not in ("", "-", ".", "-."):
            try:
                typed = float(m["typed"])
            except ValueError:
                typed = None
        if m["op"] == "move":
            if typed is not None:
                v = AXES[m["axis"] or "x"][0] * typed
            else:
                v = self._move_from(cam, g, m["x"] - m["x0"], m["y"] - m["y0"], m["axis"],
                                    bool(mods & Qt.KeyboardModifier.ShiftModifier))
        elif m["op"] == "rotate":
            if typed is not None:
                v = typed
            else:
                px, py = m["piv"]
                a0 = math.atan2(m["y0"] - py, m["x0"] - px)
                a1 = math.atan2(m["y"] - py, m["x"] - px)
                v = ((math.degrees(a1 - a0) + 180) % 360 - 180) * self._turn_sign(cam)
        else:
            if typed is not None:
                v = typed
            else:
                px, py = m["piv"]
                r0 = max(4.0, math.hypot(m["x0"] - px, m["y0"] - py))
                v = max(0.05, math.hypot(m["x"] - px, m["y"] - py) / r0)
        if mods & Qt.KeyboardModifier.ControlModifier:
            v = self._snap(m["op"], v)
        m["value"] = v
        m["kind"] = m["op"]
        self._emit_value(m)
        self.update()

    def _modal_done(self):
        self.modal = None
        self.gizmoEnd.emit()
        self.update()

    def _modal_cancel(self):
        self.modal = None
        self.gizmoCancel.emit()
        self.update()

    # ---------------------------------------------------------------- mouse
    def enterEvent(self, e):
        f = QApplication.focusWidget()
        if not isinstance(f, (QLineEdit, QAbstractSpinBox)):     # keys work where the mouse is (as in Blender)
            self.setFocus()

    def mousePressEvent(self, e):
        p = e.position()
        self.clicked.emit()
        mods = e.modifiers()
        if self.modal:
            if e.button() == Qt.MouseButton.LeftButton:
                self._modal_done()
            else:
                self._modal_cancel()
            return
        btn = e.button()
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if btn == Qt.MouseButton.MiddleButton or (btn == Qt.MouseButton.LeftButton and alt):
            self.free_camera()
            self.drag = dict(mode="pan" if shift else "orbit", x=p.x(), y=p.y())
            return
        if btn == Qt.MouseButton.RightButton:
            self.drag = dict(mode="rpress", x=p.x(), y=p.y(), x0=p.x(), y0=p.y())
            return
        if btn != Qt.MouseButton.LeftButton:
            return
        g = self._gizmo_screen()
        handle = self._handle_at(g, p)
        if handle is not None:
            op, axis = handle
            piv = g["centre"] if self.pivot_mode() == "own" else g["pivot"]
            self.drag = dict(mode="gizmo", handle=handle, kind=op, axis=axis, x=p.x(), y=p.y(), x0=p.x(), y0=p.y(),
                             g=g, piv=piv, value=np.zeros(3) if op == "move" else (0.0 if op == "rotate" else 1.0))
            self.gizmoStart.emit()
            return
        slot = self.slot_at(p)
        selected = set(getattr(self.r, "highlights", set()) or set())
        if slot is not None:
            if shift:
                self.pickRequested.emit([slot], "toggle")
                self.drag = None
                return
            if slot not in selected:
                self.pickRequested.emit([slot], "replace")
            self.drag = dict(mode="maybe_move", x=p.x(), y=p.y(), x0=p.x(), y0=p.y())
            return
        self.drag = dict(mode="box", x0=p.x(), y0=p.y(), x=p.x(), y=p.y(), add=shift)

    def mouseMoveEvent(self, e):
        p = e.position()
        mods = e.modifiers()
        if self.modal:
            self.modal["x"], self.modal["y"] = p.x(), p.y()
            self._modal_update(mods)
            return
        if not self.drag:
            g = self._gizmo_screen()
            hv = self._handle_at(g, p)
            if hv != self.hover:
                self.hover = hv
                self.update()
            cur = Qt.CursorShape.ArrowCursor
            if hv is not None:
                cur = {"move": Qt.CursorShape.SizeAllCursor, "rotate": Qt.CursorShape.CrossCursor,
                       "scale": Qt.CursorShape.SizeFDiagCursor}[hv[0]]
            elif self.slot_at(p) is not None:
                cur = Qt.CursorShape.PointingHandCursor
            self.setCursor(cur)
            return
        d = self.drag
        m = d["mode"]
        dx, dy = p.x() - d["x"], p.y() - d["y"]
        if m == "rpress":
            if abs(p.x() - d["x0"]) + abs(p.y() - d["y0"]) > 5:
                self.free_camera()
                d["mode"] = "pan"
            else:
                return
        d["x"], d["y"] = p.x(), p.y()
        m = d["mode"]
        if m == "maybe_move":
            if abs(p.x() - d["x0"]) + abs(p.y() - d["y0"]) > 4:
                d.update(mode="dragmove", kind="move", value=np.zeros(3))
                self.gizmoStart.emit()
            else:
                return
        if m in ("dragmove", "maybe_move"):
            cam = self._cam_used()
            d["value"] = d["value"] + self._floor_delta(cam, dx, dy, bool(mods & Qt.KeyboardModifier.ShiftModifier))
            v = self._snap("move", d["value"]) if mods & Qt.KeyboardModifier.ControlModifier else d["value"]
            self._emit_value(dict(kind="move", value=v))
            self.update()
        elif m == "gizmo":
            g = d["g"]
            cam = self._cam_used()
            if d["kind"] == "move":
                if d["axis"]:
                    d["value"] = d["value"] + self._move_from(cam, g, dx, dy, d["axis"],
                                                              bool(mods & Qt.KeyboardModifier.ShiftModifier))
                else:
                    d["value"] = d["value"] + self._floor_delta(cam, dx, dy,
                                                                bool(mods & Qt.KeyboardModifier.ShiftModifier))
            elif d["kind"] == "rotate":
                px, py = d["piv"]
                a0 = math.atan2(d["y0"] - py, d["x0"] - px)
                a1 = math.atan2(p.y() - py, p.x() - px)
                d["value"] = ((math.degrees(a1 - a0) + 180) % 360 - 180) * self._turn_sign(cam)
            else:
                cx, cy = g["centre"] if self.pivot_mode() == "own" else d["piv"]
                r0 = max(4.0, math.hypot(d["x0"] - cx, d["y0"] - cy))
                d["value"] = max(0.05, math.hypot(p.x() - cx, p.y() - cy) / r0)
            v = self._snap(d["kind"], d["value"]) if mods & Qt.KeyboardModifier.ControlModifier else d["value"]
            self._emit_value(dict(kind=d["kind"], value=v))
            self.update()
        elif m == "box":
            self.update()
        elif m == "orbit":
            self.cam.yaw += dx * 0.4
            self.cam.pitch = max(-10.0, min(89.0, self.cam.pitch + dy * 0.3))
            self.cam.update()
            self.update()
        elif m == "pan":
            self.cam.focus = self.cam.focus - self.cam.unproject_delta(dx, dy)
            self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if d is None:
            return
        m = d["mode"]
        if m in ("gizmo", "dragmove"):
            self.gizmoEnd.emit()
        elif m == "box":
            if abs(d["x"] - d["x0"]) + abs(d["y"] - d["y0"]) <= 4:
                if not d["add"]:
                    self.pickRequested.emit([], "replace")          # a click on empty space: select nothing
            else:
                self.pickRequested.emit(self.slots_in(d["x0"], d["y0"], d["x"], d["y"]),
                                        "add" if d["add"] else "replace")
        elif m == "rpress":
            self.menuRequested.emit(self.mapToGlobal(QPoint(int(d["x0"]), int(d["y0"]))),
                                    self.slot_at(QPointF(d["x0"], d["y0"])))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def wheelEvent(self, e):
        if self.game_cam:
            # no silent switch: a scroll meant for the page must not leave the skill's camera
            self.flash("The wheel zooms the free camera: press C, click the camera badge, or look around with the "
                       "middle / right mouse button first")
            return
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.cam.scale = max(0.15, min(12.0, self.cam.scale * f))
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.slot_at(e.position()) is None:
            self.view_preset("home")

    # ---------------------------------------------------------------- keys
    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        m = self.modal
        if m:
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._modal_done()
            elif k == Qt.Key.Key_Escape:
                self._modal_cancel()
            elif k in (Qt.Key.Key_X, Qt.Key.Key_Y, Qt.Key.Key_Z) and m["op"] == "move":
                a = {Qt.Key.Key_X: "x", Qt.Key.Key_Y: "y", Qt.Key.Key_Z: "z"}[k]
                m["axis"] = None if m["axis"] == a else a
                self._modal_update(mods)
            elif k == Qt.Key.Key_Backspace:
                m["typed"] = m["typed"][:-1]
                self._modal_update(mods)
            elif e.text() and e.text() in "0123456789.-":
                if e.text() == "-":
                    m["typed"] = m["typed"][1:] if m["typed"].startswith("-") else "-" + m["typed"]
                else:
                    m["typed"] += e.text()
                self._modal_update(mods)
            return
        if k in (Qt.Key.Key_G, Qt.Key.Key_R, Qt.Key.Key_S) and not ctrl:
            self.start_modal({Qt.Key.Key_G: "move", Qt.Key.Key_R: "rotate", Qt.Key.Key_S: "scale"}[k])
        elif k == Qt.Key.Key_Q and not ctrl:
            self.set_tool("select")
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_X) and not ctrl:
            self.deleteRequested.emit()
        elif k == Qt.Key.Key_D and shift:
            self.duplicateRequested.emit()
        elif k == Qt.Key.Key_A and not ctrl:
            self.selectAllRequested.emit(not alt)
        elif k in (Qt.Key.Key_F, Qt.Key.Key_Period):
            self.frame_selected()
        elif k == Qt.Key.Key_Home:
            self.view_preset("home")
        elif k == Qt.Key.Key_C and not ctrl:
            self.set_game_camera(not self.game_cam, pinned=True)
        elif k == Qt.Key.Key_1 and mods & Qt.KeyboardModifier.KeypadModifier:
            self.view_preset("front")
        elif k == Qt.Key.Key_3 and mods & Qt.KeyboardModifier.KeypadModifier:
            self.view_preset("side")
        elif k == Qt.Key.Key_7 and mods & Qt.KeyboardModifier.KeypadModifier:
            self.view_preset("top")
        else:
            super().keyPressEvent(e)
