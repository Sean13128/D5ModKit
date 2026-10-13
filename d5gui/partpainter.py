"""Part painter: decide which colour part ("Part N" of the in-game precise colour editor) every pixel of an outfit
belongs to.

The canvas shows the pose the live preview is on, so a fix shows at once in the preview -- in test colours, or in
any of the in-game colour options (Normal Color, Extra Color 1 ...), as the game will show them.  A pose that is
right can be made a reference: "Fix every frame" then carries its parts over to all the other frames
(d5lib.partlearn)."""
import colorsys
import pickle
import random

import numpy as np
from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import (QColor, QImage, QPixmap, QPainter, QPen, QBrush, QKeySequence, QShortcut, QIcon,
                         QPainterPath)
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem, QLabel,
                             QPushButton, QComboBox, QSlider, QSpinBox, QCheckBox, QToolButton, QButtonGroup,
                             QGraphicsView, QGraphicsScene, QWidget, QMessageBox, QApplication, QInputDialog,
                             QGroupBox, QAbstractItemView, QProgressDialog, QGraphicsPathItem)

from d5lib import anm, colorvariants, partmap, partpaint, outfits, sprites
from .common import ImageView, pil_to_pixmap, checker_brush

LEGEND = np.array(partmap.LEGEND + [(255, 255, 255)] * (16 - len(partmap.LEGEND)), np.uint8)
TOOLS = [("brush", "🖌 Brush", "Paint the active part (B). Right-click: pick the part under the cursor."),
         ("fill", "🪣 Fill", "Fill the connected area of that material with the active part (F)"),
         ("colour", "🎯 Colour → part", "Every pixel of the clicked colour, in every frame, becomes the active "
                                       "part (C)"),
         ("erase", "⌫ Unpaint", "Remove brush / fill painting: those pixels go back to their automatic part (E)"),
         ("pick", "💧 Pick", "Make the part under the cursor the active part (I)")]
POSE = -1           # canvas: the pose the preview shows


def np_to_pixmap(rgba):
    h, w = rgba.shape[:2]
    q = QImage(np.ascontiguousarray(rgba).data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())


class PaintView(QGraphicsView):
    """sheet + part overlay; emits stroke(x, y, button, phase) in sheet pixels.  focus(): zoom onto one pose
    (everything else dimmed), mirrored like the preview shows it"""
    stroke = pyqtSignal(int, int, object, str)
    hovered = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(checker_brush())
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setMouseTracking(True)
        self.base_item = self.scene().addPixmap(QPixmap())
        self.over_item = self.scene().addPixmap(QPixmap())
        self.dim_item = QGraphicsPathItem()
        self.dim_item.setBrush(QBrush(QColor(10, 10, 14, 190)))
        self.dim_item.setPen(QPen(Qt.PenStyle.NoPen))
        self.dim_item.setZValue(5)
        self.scene().addItem(self.dim_item)
        self.ref_items = []
        self.cursor_item = self.scene().addEllipse(0, 0, 1, 1, QPen(QColor(255, 255, 255, 220), 0))
        self.cursor_item.setZValue(10)
        self.brush = 3
        self._down = None
        self._pan = None
        self._focus = None

    def set_images(self, base, over):
        if base is not None:
            self.base_item.setPixmap(np_to_pixmap(base))
            self.scene().setSceneRect(QRectF(0, 0, base.shape[1], base.shape[0]))
        if over is not None:
            self.over_item.setPixmap(np_to_pixmap(over))

    def set_refs(self, rects):
        for it in self.ref_items:
            self.scene().removeItem(it)
        self.ref_items = []
        pen = QPen(QColor(255, 200, 40, 230), 0)
        for x0, y0, x1, y1 in rects:
            it = self.scene().addRect(QRectF(x0 - 0.5, y0 - 0.5, x1 - x0 + 1, y1 - y0 + 1), pen)
            it.setZValue(6)
            self.ref_items.append(it)

    def focus(self, rect, mirrored=False, refit=True):
        """rect (x0, y0, x1, y1) of the pose, or None = the whole sheet"""
        self._focus = (rect, mirrored)
        path = QPainterPath()
        if rect is not None:
            path.setFillRule(Qt.FillRule.OddEvenFill)
            path.addRect(self.scene().sceneRect())
            x0, y0, x1, y1 = rect
            path.addRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        self.dim_item.setPath(path)
        if refit:
            self.refit()

    def refit(self):
        rect, mirrored = self._focus or (None, False)
        self.resetTransform()
        if mirrored:
            self.scale(-1, 1)
        if rect is None:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            x0, y0, x1, y1 = rect
            m = 6
            self.fitInView(QRectF(x0 - m, y0 - m, x1 - x0 + 2 * m, y1 - y0 + 2 * m),
                           Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._focus is not None:
            self.refit()

    def _px(self, e):
        p = self.mapToScene(e.position().toPoint())
        return int(np.floor(p.x())), int(np.floor(p.y()))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan = e.position()
            return
        x, y = self._px(e)
        self._down = e.button()
        self.stroke.emit(x, y, e.button(), "press")

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        x, y = self._px(e)
        r = self.brush
        self.cursor_item.setRect(x - r + 0.5, y - r + 0.5, 2 * r - 1, 2 * r - 1)
        self.hovered.emit(x, y)
        if self._down is not None:
            self.stroke.emit(x, y, self._down, "move")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan = None
            return
        if self._down is not None:
            x, y = self._px(e)
            self.stroke.emit(x, y, self._down, "release")
        self._down = None


class PartPainterDialog(QDialog):
    def __init__(self, ws, mod, slot, title="", parent=None):
        super().__init__(parent)
        self.ws, self.mod, self.slot = ws, mod, slot
        self.setWindowTitle(f"Part painter — {title}")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1600, 940)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.N, self.sprite = outfits.painting_sprite(ws.fs, mod, slot)
            state = outfits.load_painter(mod, self.N)
            shapes = [anm.texture_indices(self.sprite, t).shape for t, x in enumerate(self.sprite.textures)
                      if x.indexed]
            over = outfits.load_overrides(mod, self.N, shapes) if state else None
            learned = outfits.load_overrides(mod, self.N, shapes, "learned") if state else None
            self.model = partpaint.PartModel(self.sprite, state, over, learned)
            self.model.refs = self.model.key_rects()
            self.preview = sprites.preview_file(ws.fs, pickle.loads(pickle.dumps(self.sprite)))
            try:
                self.base = outfits.base_sprite(ws.fs, mod, slot)
            except Exception:
                self.base = None
        finally:
            QApplication.restoreOverrideCursor()
        self.npal = len(self.sprite.palettes)
        self.rebuilt = None              # preview of the sprite rebuilt from the current parts (in-game colours)
        self.active = 1
        self.tool = "brush"
        self.tex = self.model.texs[0]
        self.dirty = False
        self.seed = 7
        self._frame_cache = {}
        self._pose = None                # (tex, [rects], mirrored) of the preview's current pose
        self._time = 0.0
        self.rebuild_timer = QTimer(self)
        self.rebuild_timer.setSingleShot(True)
        self.rebuild_timer.timeout.connect(self._rebuild)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        help_ = QLabel("<b>1.</b> Pick a clear pose in the preview (◀ ▶ step through it) — the canvas shows that "
                       "pose. <b>2.</b> Paint it right (the preview updates at once; switch it to the in-game "
                       "colour options to check). <b>3.</b> ⭐ make it a reference, maybe also a back view and an "
                       "attack pose. <b>4.</b> ✨ <b>Fix every frame</b> carries those parts over to all frames.")
        help_.setObjectName("banner")
        help_.setWordWrap(True)
        root.addWidget(help_)
        split = QSplitter()
        split.setChildrenCollapsible(False)
        split.addWidget(self._left())
        split.addWidget(self._center())
        split.addWidget(self._right())
        split.setSizes([320, 760, 520])
        root.addWidget(split, 1)
        bot = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("muted")
        bot.addWidget(self.status, 1)
        b = QPushButton("Close")
        b.clicked.connect(self.close)
        bot.addWidget(b)
        self.b_save = QPushButton("💾 Save parts")
        self.b_save.setObjectName("primary")
        self.b_save.setToolTip("Rebuild the outfit sprite with these parts (the colour presets follow). "
                               "Install afterwards to see it in game.")
        self.b_save.clicked.connect(self.save)
        bot.addWidget(self.b_save)
        root.addLayout(bot)
        for key, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Ctrl+S", self.save), ("B", lambda: self._set_tool("brush")),
                        ("F", lambda: self._set_tool("fill")), ("C", lambda: self._set_tool("colour")),
                        ("E", lambda: self._set_tool("erase")), ("I", lambda: self._set_tool("pick")),
                        ("[", lambda: self.size.setValue(self.size.value() - 1)),
                        ("]", lambda: self.size.setValue(self.size.value() + 1)),
                        ("Space", self._toggle_play), (",", lambda: self._step(-1)), (".", lambda: self._step(1))):
            QShortcut(QKeySequence(key), self, activated=fn)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._fill_parts()
        self._fill_materials()
        self._refresh_canvas(base=True)
        self._fill_anims()
        self._update_refs()
        self.timer.start(66)
        self._update_status()

    # ================================================================== layout
    def _left(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox("Parts")
        gv = QVBoxLayout(g)
        self.parts = QListWidget()
        self.parts.currentItemChanged.connect(self._part_selected)
        self.parts.itemDoubleClicked.connect(lambda _: self._rename())
        self.parts.setToolTip("Click: the part you paint with. Double-click: rename.")
        gv.addWidget(self.parts, 1)
        row = QHBoxLayout()
        for text, fn, tip in (("＋ Add", self._add_part, "A new, empty part"),
                              ("Rename", self._rename, "Name the part (only for you; the game shows Part N)"),
                              ("Remove", self._remove_part, "Merge this part into another one")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        gv.addLayout(row)
        v.addWidget(g, 3)
        g = QGroupBox("Materials → part")
        gv = QVBoxLayout(g)
        t = QLabel("Colour families found in the sprite. Pick the part each one belongs to.")
        t.setObjectName("muted")
        t.setWordWrap(True)
        gv.addWidget(t)
        self.mats = QListWidget()
        self.mats.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.mats.currentItemChanged.connect(lambda *_: self._refresh_canvas())
        gv.addWidget(self.mats, 1)
        v.addWidget(g, 4)
        g = QGroupBox("Rules")
        gv = QVBoxLayout(g)
        self.clean = QCheckBox("Clean-up rules")
        self.clean.setChecked(self.model.clean)
        self.clean.setToolTip("Applied the same way in every frame:\n• a patch completely surrounded by one part "
                              "joins it\n• black lines inside the drawing join the part around them\n• small "
                              "patches in the face become the Eyes part\n• specks of a few pixels join their "
                              "surroundings")
        self.clean.toggled.connect(self._toggle_clean)
        gv.addWidget(self.clean)
        row = QHBoxLayout()
        b = QPushButton("↺ Automatic parts")
        b.setToolTip("Start over from the automatic parts (your painting and references are removed)")
        b.clicked.connect(self._auto)
        row.addWidget(b)
        b = QPushButton("Remove painting")
        b.setToolTip("Remove every brush / fill stroke, keep the material assignments")
        b.clicked.connect(self._clear_painting)
        row.addWidget(b)
        gv.addLayout(row)
        v.addWidget(g)
        return w

    def _center(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.tool_group = QButtonGroup(self)
        self.tool_buttons = {}
        for key, text, tip in TOOLS:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self._set_tool(k))
            self.tool_group.addButton(b)
            self.tool_buttons[key] = b
            bar.addWidget(b)
        self.tool_buttons["brush"].setChecked(True)
        bar.addWidget(QLabel(" Size"))
        self.size = QSpinBox()
        self.size.setRange(1, 40)
        self.size.setValue(2)
        self.size.valueChanged.connect(lambda v_: setattr(self.view, "brush", v_))
        bar.addWidget(self.size)
        bar.addStretch(1)
        for text, fn, tip in (("Undo", self.undo, "Undo (Ctrl+Z)"), ("Redo", self.redo, "Redo (Ctrl+Y)")):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        v.addLayout(bar)
        bar = QHBoxLayout()
        self.sheet = QComboBox()
        self.sheet.addItem("🎯 The preview's pose", POSE)
        self.sheet.setItemData(0, "The canvas follows the preview: the pose shown there, zoomed in (mirrored the "
                                  "same way)", Qt.ItemDataRole.ToolTipRole)
        for k, t in enumerate(self.model.texs):
            h, w_ = self.model.ind[t].shape
            self.sheet.addItem(f"Whole sheet {k + 1}  ({w_}×{h})", t)
        self.sheet.currentIndexChanged.connect(self._sheet_changed)
        bar.addWidget(self.sheet)
        bar.addWidget(QLabel(" Overlay"))
        self.alpha = QSlider(Qt.Orientation.Horizontal)
        self.alpha.setRange(0, 100)
        self.alpha.setValue(45)
        self.alpha.setMaximumWidth(130)
        self.alpha.setToolTip("How strongly the part colours cover the sprite (0 = only the sprite)")
        self.alpha.valueChanged.connect(lambda _: self._refresh_canvas())
        bar.addWidget(self.alpha)
        self.only_active = QCheckBox("Only the active part")
        self.only_active.toggled.connect(lambda _: self._refresh_canvas())
        bar.addWidget(self.only_active)
        b = QToolButton()
        b.setText("Fit")
        b.clicked.connect(lambda: self.view.refit())
        bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)
        self.view = PaintView()
        self.view.brush = 2
        self.view.stroke.connect(self._stroke)
        self.view.hovered.connect(self._hover)
        v.addWidget(self.view, 1)
        refbar = QHBoxLayout()
        self.b_ref = QPushButton("⭐ Use this pose as a reference")
        self.b_ref.setToolTip("When this pose's parts are right, make it a reference: “Fix every frame” copies "
                              "its parts to all other frames. A back view and an attack pose as extra references "
                              "help those frames.")
        self.b_ref.clicked.connect(self._toggle_ref)
        refbar.addWidget(self.b_ref)
        self.b_learn = QPushButton("✨ Fix every frame from the references")
        self.b_learn.setObjectName("primary")
        self.b_learn.setToolTip("Every colour the references always give one part takes that part in all frames; "
                                "shared colours (highlights, see-through cloth ...) are decided from what "
                                "surrounds them, like in the references. Brush painting still wins.")
        self.b_learn.clicked.connect(self._learn)
        refbar.addWidget(self.b_learn)
        self.b_unlearn = QPushButton("Clear")
        self.b_unlearn.setToolTip("Remove the parts carried over from the references (back to the rules)")
        self.b_unlearn.clicked.connect(self._clear_learned)
        refbar.addWidget(self.b_unlearn)
        self.ref_info = QLabel()
        self.ref_info.setObjectName("muted")
        refbar.addWidget(self.ref_info, 1)
        v.addLayout(refbar)
        tip = QLabel("Left: use the tool · Right-click: pick the part under the cursor · Wheel: zoom · "
                     "Middle-drag: pan · [ ]: brush size · Space: play/pause · , .: previous / next pose")
        tip.setObjectName("muted")
        v.addWidget(tip)
        return w

    def _right(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        t = QLabel("Live preview")
        t.setObjectName("cardTitle")
        row.addWidget(t)
        row.addStretch(1)
        self.mode = QComboBox()
        self.mode.addItem("Test colours (shows mistakes)", ("test", 0))
        self.mode.addItem("Part colours", ("parts", 0))
        self.mode.addItem("Original sprite", ("orig", 0))
        self.mode.insertSeparator(self.mode.count())
        for k in range(self.npal):
            self.mode.addItem("In game: Normal Color" if k == 0 else f"In game: Extra Color {k}", ("pal", k))
        if self.npal > 1:
            self.mode.addItem("In game: all colour options", ("all", 0))
        self.mode.setToolTip("Test colours: every part gets a clearly different colour, so a pixel in the wrong "
                             "part stands out.\nIn game: the outfit rebuilt from the current parts, in the "
                             "colours the game will show (they follow every change).")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        row.addWidget(self.mode)
        b = QToolButton()
        b.setText("🎲")
        b.setToolTip("Other test colours")
        b.clicked.connect(self._reseed)
        row.addWidget(b)
        v.addLayout(row)
        self.anim = QComboBox()
        self.anim.currentIndexChanged.connect(self._anim_changed)
        v.addWidget(self.anim)
        self.pview = ImageView()
        self.pview.setBackgroundBrush(QColor(40, 90, 60))
        v.addWidget(self.pview, 1)
        row = QHBoxLayout()
        for text, fn, tip in (("⏮", lambda: self._step(-1), "Previous pose (,)"),):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        self.play = QToolButton()
        self.play.setText("⏸")
        self.play.setToolTip("Play / pause (Space)")
        self.play.clicked.connect(self._toggle_play)
        row.addWidget(self.play)
        b = QToolButton()
        b.setText("⏭")
        b.setToolTip("Next pose (.)")
        b.clicked.connect(lambda: self._step(1))
        row.addWidget(b)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._seek)
        row.addWidget(self.slider, 1)
        self.frame_lbl = QLabel()
        self.frame_lbl.setObjectName("muted")
        row.addWidget(self.frame_lbl)
        v.addLayout(row)
        return w

    # ================================================================== lists
    def _swatch(self, part):
        pm = QPixmap(14, 14)
        r, g, b = LEGEND[part][:3]
        pm.fill(QColor(int(r), int(g), int(b)))
        return QIcon(pm)

    def _fill_parts(self):
        counts = self.model.counts()
        self.parts.blockSignals(True)
        self.parts.clear()
        for p in sorted(self.model.names):
            label = f"Part {p}: {self.model.names[p]}" if p else "Details (outline, not editable in game)"
            it = QListWidgetItem(self._swatch(p), f"{label}   ·  {counts.get(p, 0):,} px")
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.parts.addItem(it)
            if p == self.active:
                self.parts.setCurrentItem(it)
        self.parts.blockSignals(False)

    def _fill_materials(self):
        self.mats.clear()
        names = sorted(self.model.names)
        for m in sorted(self.model.minfo, key=lambda m: -self.model.minfo[m]["count"]):
            info = self.model.minfo[m]
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, m)
            self.mats.addItem(it)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 1, 4, 1)
            strip = QLabel()
            cols = sorted(info["colours"], key=lambda c: int(self.model.pal[c][:3].sum()))
            img = np.zeros((14, max(1, len(cols)) * 4, 4), np.uint8)
            for k, c in enumerate(cols):
                img[:, k * 4:k * 4 + 4] = self.model.pal[c]
            img[..., 3] = 255
            strip.setPixmap(np_to_pixmap(img).scaled(min(120, img.shape[1]), 14))
            strip.setToolTip(f"{info['name']}: {len(cols)} colours, {info['count']:,} px")
            h.addWidget(strip)
            h.addStretch(1)
            combo = QComboBox()
            combo.addItem("↔ Nearest part (shared shading)", partpaint.NEAREST)
            combo.setItemData(0, "Colours used as shading by several parts: every pixel joins the part right "
                                 "next to it", Qt.ItemDataRole.ToolTipRole)
            for p in names:
                combo.addItem(self._swatch(p), f"{p}: {self.model.names[p]}" if p else "Details", p)
            combo.setCurrentIndex(max(0, combo.findData(self.model.material_part(m))))
            combo.activated.connect(lambda _, m=m, c=combo: self._material_part(m, c.currentData()))
            h.addWidget(combo)
            it.setSizeHint(row.sizeHint())
            self.mats.setItemWidget(it, row)

    def _part_selected(self, it, _prev=None):
        if it:
            self.active = it.data(Qt.ItemDataRole.UserRole)
            if self.only_active.isChecked():
                self._refresh_canvas()

    # ================================================================== canvas
    def _pose_mode(self):
        return self.sheet.currentData() == POSE

    def _sheet_changed(self, _):
        if self._pose_mode():
            self._follow(force=True)
        else:
            self.tex = self.sheet.currentData()
            self._refresh_canvas(base=True)
            self.view.focus(None)
            self._update_refs()

    def _overlay(self):
        t = self.tex
        f = np.where(self.model.over[t] >= 0, self.model.over[t],
                     np.where(self.model.learned[t] >= 0, self.model.learned[t], self.model.base[t]))
        out = np.zeros(f.shape + (4,), np.uint8)
        m = f >= 0
        out[m, :3] = LEGEND[np.clip(f[m], 0, 15)][:, :3]
        a = int(self.alpha.value() * 2.55)
        out[m, 3] = a
        if self.only_active.isChecked():
            out[m & (f != self.active), 3] = 0
        it = self.mats.currentItem()
        if it is not None:                   # the selected material: everything else dimmed
            mm = it.data(Qt.ItemDataRole.UserRole)
            sel = self.model.op[t] & (self.model.mat[self.model.ind[t]] == mm)
            out[m & ~sel, :3] = (out[m & ~sel, :3] * 0.15).astype(np.uint8)
            out[m & ~sel, 3] = 200
        return out

    def _refresh_canvas(self, base=False):
        first = self.view.base_item.pixmap().isNull()
        self.view.set_images(self.model.rgba[self.tex] if (base or first) else None, self._overlay())
        if first and not self._pose_mode():
            QTimer.singleShot(0, lambda: self.view.focus(None))

    def _pose_at(self, t):
        """(sheet, [rects], mirrored) of the preview's pose at time t"""
        if not hasattr(self, "_aidx"):
            return None
        items = [it for it in anm.evaluate(self.preview, self._aidx, int(t))
                 if it.tex_global in self.model.ind and it.cell.w * it.cell.h > 0]
        if not items:
            return None
        main = max(items, key=lambda it: it.cell.w * it.cell.h)
        tex = main.tex_global
        rects = [(it.cell.x, it.cell.y, it.cell.x + it.cell.w, it.cell.y + it.cell.h) for it in items
                 if it.tex_global == tex]
        q = main.quad
        e1, e2 = q[1] - q[0], q[3] - q[0]
        mirrored = bool(e1[0] * e2[1] - e1[1] * e2[0] < 0)
        return tex, rects, mirrored

    def _follow(self, force=False):
        """canvas on the preview's current pose"""
        if not self._pose_mode():
            return
        pose = self._pose_at(self._time)
        if pose is None or (pose == self._pose and not force):
            return
        self._pose = pose
        tex, rects, mirrored = pose
        if tex != self.tex or force:
            self.tex = tex
            self._refresh_canvas(base=True)
        x0 = min(r[0] for r in rects)
        y0 = min(r[1] for r in rects)
        x1 = max(r[2] for r in rects)
        y1 = max(r[3] for r in rects)
        self.view.focus((x0, y0, x1, y1), mirrored)
        self._update_refs()

    def _pose_rects(self):
        """the preview's pose as the sprite frame it is drawn from"""
        if self._pose is None:
            return []
        tex, rects, _ = self._pose
        main = max(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        q = self.model.pose_of((tex,) + tuple(main))
        return [q] if q else []

    def _set_tool(self, key):
        self.tool = key
        self.tool_buttons[key].setChecked(True)
        self.view.setCursor(Qt.CursorShape.CrossCursor)

    def _disc(self, x, y):
        t = self.tex
        H, W = self.model.ind[t].shape
        r = self.size.value()
        yy, xx = np.ogrid[:H, :W]
        return (xx - x) ** 2 + (yy - y) ** 2 < r * r

    def _stroke(self, x, y, button, phase):
        t = self.tex
        H, W = self.model.ind[t].shape
        if phase == "press" and self.play.text() == "⏸":
            self._toggle_play()              # painting: hold the preview on this pose
        if not (0 <= x < W and 0 <= y < H):
            return
        if button == Qt.MouseButton.RightButton or self.tool == "pick":
            if phase == "press":
                p = self.model.part_at(t, x, y)
                if p is not None:
                    self._select_part(p)
            return
        if self.tool in ("brush", "erase"):
            if phase == "press":
                self.model.snapshot()
            if phase in ("press", "move"):
                self.model.paint(t, self._disc(x, y), -1 if self.tool == "erase" else self.active)
                self._changed(light=True)
            elif phase == "release":
                self._changed()
        elif phase == "press" and self.tool == "fill":
            self.model.snapshot()
            n = self.model.fill(t, x, y, self.active)
            self.status.setText(f"filled {n:,} px")
            self._changed()
        elif phase == "press" and self.tool == "colour":
            c = self.model.colour_at(t, x, y)
            if c is None:
                return
            self.model.snapshot()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.model.set_colours([c], self.active)
            finally:
                QApplication.restoreOverrideCursor()
            self._changed(full=True)

    def _hover(self, x, y):
        t = self.tex
        H, W = self.model.ind[t].shape
        if 0 <= x < W and 0 <= y < H and self.model.op[t][y, x]:
            p = self.model.part_at(t, x, y)
            c = self.model.colour_at(t, x, y)
            r, g, b = [int(v) for v in self.model.pal[c][:3]]
            how = ("  (painted)" if self.model.over[t][y, x] >= 0 else
                   "  (from the references)" if self.model.learned[t][y, x] >= 0 else "")
            self.status.setText(f"x {x}, y {y} · colour #{r:02X}{g:02X}{b:02X} · Part {p}: "
                                f"{self.model.names.get(p, '?')}{how}")

    def _select_part(self, p):
        for i in range(self.parts.count()):
            if self.parts.item(i).data(Qt.ItemDataRole.UserRole) == p:
                self.parts.setCurrentRow(i)
                return

    def _changed(self, light=False, full=False, learned=False):
        self.dirty = True
        self._refresh_canvas()
        if light:
            return
        if not learned and self.model.has_learned():
            self.model.learned_stale = True
        self._invalidate()
        if full:
            self._fill_materials()
        self._fill_parts()
        self._update_refs()
        self._update_status()

    def _update_status(self):
        self.setWindowTitle(self.windowTitle().rstrip(" ●") + (" ●" if self.dirty else ""))

    # ================================================================== reference poses
    def _update_refs(self):
        rects = self._pose_rects()
        is_ref = self.model.is_ref(rects) if rects else False
        self.b_ref.setText("★ Reference pose — click to remove" if is_ref else "⭐ Use this pose as a reference")
        self.b_ref.setEnabled(bool(rects))
        self.b_learn.setEnabled(bool(self.model.refs))
        self.b_unlearn.setEnabled(self.model.has_learned())
        poses = len(self.model.refs)
        if not self.model.refs:
            info = "No reference poses yet."
        else:
            info = f"{poses} reference pose{'s' if poses != 1 else ''}"
            if self.model.has_learned():
                info += (" · ⚠ parts changed since “Fix every frame” — run it again" if self.model.learned_stale
                         else " · every frame follows them")
            else:
                info += " · not carried over yet"
        self.ref_info.setText(info)
        self.view.set_refs([r[1:] for r in self.model.refs if r[0] == self.tex])

    def _toggle_ref(self):
        rects = self._pose_rects()
        if not rects:
            return
        self.model.snapshot()
        added = self.model.toggle_ref(rects)
        if self.model.has_learned():
            self.model.learned_stale = True
        self.dirty = True
        self._update_refs()
        self._update_status()
        self.status.setText("This pose is now a reference." if added else "Reference removed.")

    def _learn(self):
        if not self.model.refs:
            return
        self.model.snapshot()
        dlg = QProgressDialog("Carrying the reference poses' parts over to every frame…", None, 0, 0, self)
        dlg.setWindowTitle("Fix every frame")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.show()
        QApplication.processEvents()

        def log(msg):
            dlg.setLabelText(msg.strip())
            QApplication.processEvents()
        try:
            n = self.model.learn(log=log)
        except Exception as e:
            dlg.close()
            QMessageBox.critical(self, "Fix every frame", str(e))
            return
        dlg.close()
        self._changed(learned=True)
        self.status.setText(f"Every frame now follows the reference poses ({n:,} px changed). Brush fixes still "
                            "win — a pose you fix can become a reference too.")

    def _clear_learned(self):
        self.model.snapshot()
        self.model.clear_learned()
        self._changed(learned=True)

    # ================================================================== part / material edits
    def _material_part(self, m, part):
        self.model.snapshot()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.model.set_material(m, part)
        finally:
            QApplication.restoreOverrideCursor()
        self._changed()

    def _rename(self):
        p = self.active
        if p == 0:
            return
        name, ok = QInputDialog.getText(self, "Rename part", f"Name of Part {p}:", text=self.model.names.get(p, ""))
        if ok and name.strip():
            self.model.snapshot()
            self.model.rename(p, name.strip())
            self._changed(full=True, learned=True)

    def _add_part(self):
        name, ok = QInputDialog.getText(self, "New part", "Name:", text="New part")
        if not ok:
            return
        self.model.snapshot()
        p = self.model.add_part(name.strip() or "New part")
        if p is None:
            QMessageBox.information(self, "Parts", "The game's editor has 15 parts at most.")
            return
        self.active = p
        self._changed(full=True, learned=True)

    def _remove_part(self):
        p = self.active
        if p == 0:
            return
        others = [f"{q}: {n}" for q, n in sorted(self.model.names.items()) if q != p]
        s, ok = QInputDialog.getItem(self, "Remove part", f"Merge Part {p} ({self.model.names[p]}) into:",
                                     others, 0, False)
        if ok:
            self.model.snapshot()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.model.remove_part(p, int(s.split(":")[0]))
            finally:
                QApplication.restoreOverrideCursor()
            self.active = int(s.split(":")[0])
            self._changed(full=True, learned=True)

    def _toggle_clean(self, on):
        self.model.snapshot()
        self.model.clean = on
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.model.recompute()
        finally:
            QApplication.restoreOverrideCursor()
        self._changed()

    def _auto(self):
        if QMessageBox.question(self, "Automatic parts", "Start over from the automatic parts? (Undo brings "
                                "your work back.)") != QMessageBox.StandardButton.Yes:
            return
        self.model.snapshot()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.model.auto()
            self.model.clear_overrides()
            self.model.clear_learned()
            self.model.refs = []
            self.model.recompute()
        finally:
            QApplication.restoreOverrideCursor()
        self._changed(full=True, learned=True)

    def _clear_painting(self):
        self.model.snapshot()
        self.model.clear_overrides()
        self._changed()

    def undo(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = self.model.undo()
        finally:
            QApplication.restoreOverrideCursor()
        if ok:
            self.clean.blockSignals(True)
            self.clean.setChecked(self.model.clean)
            self.clean.blockSignals(False)
            self._changed(full=True, learned=True)

    def redo(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = self.model.redo()
        finally:
            QApplication.restoreOverrideCursor()
        if ok:
            self._changed(full=True, learned=True)

    # ================================================================== preview
    def _mode(self):
        return self.mode.currentData() or ("test", 0)

    def _mode_changed(self, _):
        self._invalidate()
        self._fit_preview()

    def _fit_preview(self):
        if not getattr(self, "_bounds", None):
            return
        x0, y0, x1, y1 = self._bounds
        w, h = x1 - x0, y1 - y0
        if self._mode()[0] == "all":
            cols = 3 if self.npal > 4 else 2
            w, h = w * cols, (h + 12) * ((self.npal + cols - 1) // cols)
        vw, vh = max(50, self.pview.viewport().width() - 8), max(50, self.pview.viewport().height() - 8)
        z = min(vw / w, vh / h)
        self.pview.set_zoom(max(1, int(z)) if z >= 1 else z)

    def _reseed(self):
        self.seed = random.randint(1, 10 ** 6)
        self._invalidate()

    def _test_colours(self):
        rnd = random.Random(self.seed)
        hues = list(np.linspace(0, 1, 16, endpoint=False))
        rnd.shuffle(hues)
        return {p: hues[p % 16] for p in range(16)}

    def _invalidate(self):
        """the preview follows the current parts"""
        kind, _ = self._mode()
        if kind in ("pal", "all"):
            self.rebuild_timer.start(120)        # rebuilding takes ~0.1 s: not on every brush dab
            return
        fin = self.model.final()
        pal = self.model.pal.astype(np.float32) / 255
        test = self._test_colours()
        prev = self.preview
        for t in self.model.texs:
            ind = self.model.ind[t]
            f = fin[t]
            if kind == "orig":
                rgba = self.model.rgba[t].copy()
            elif kind == "parts":
                rgba = np.zeros(ind.shape + (4,), np.uint8)
                m = f >= 0
                rgba[m, :3] = LEGEND[np.clip(f[m], 0, 15)][:, :3]
                rgba[m, 3] = 255
            else:
                key = np.where(f >= 0, f, 0).astype(np.int64) * 256 + ind
                lut = np.zeros((16 * 256, 4), np.uint8)
                for k in np.unique(key[f >= 0]):
                    p, c = divmod(int(k), 256)
                    r, g, b, a = pal[c]
                    h, l, s = colorsys.rgb_to_hls(r, g, b)
                    if p == 0:
                        nr, ng, nb = r, g, b
                    else:
                        nr, ng, nb = colorsys.hls_to_rgb(test[p], 0.15 + 0.75 * l, 0.75)
                    lut[k] = (int(nr * 255), int(ng * 255), int(nb * 255), int(a * 255))
                rgba = lut[key]
                rgba[f < 0] = 0
            argb = anm._rgba_to_argb(rgba)
            img = prev.textures[t]
            prev.textures[t] = anm.Image8(b"\x00\x01\x01\x01", img.width, img.height, 1,
                                          np.ascontiguousarray(argb).tobytes())
        self._frame_cache = {}
        self._show(self._time)

    def _rebuild(self):
        """the outfit rebuilt from the current parts, like Save does (for the in-game colour options)"""
        if self.base is None:
            self.status.setText("The base character's sprite was not found: no in-game colours.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            a = pickle.loads(pickle.dumps(self.sprite))
            colorvariants.repartition_rows(a, self.base, self.model.final())
            self.rebuilt = sprites.preview_file(self.ws.fs, a)
        except Exception as e:
            self.rebuilt = None
            self.status.setText(f"Preview rebuild failed: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self._frame_cache = {}
        self._show(self._time)

    def _fill_anims(self):
        self.anim.blockSignals(True)
        self.anim.clear()
        best = None
        for a in anm.list_animations(self.preview):
            if a["layers"] == 0:
                continue
            face = "front" if a["id"] % 10 == 1 else "back" if a["id"] % 10 == 7 else ""
            self.anim.addItem(f"Animation {a['id']} {face} · {a['length']} f{' ⟲' if a['loop'] else ''}",
                              a["index"])
            if best is None and a["id"] == 1:           # standing, front: the clearest pose to start with
                best = self.anim.count() - 1
        self.anim.blockSignals(False)
        self._invalidate()
        self.anim.setCurrentIndex(best or 0)
        self._anim_changed(best or 0)
        self.play.setText("▶")                          # start paused on a pose

    def _anim_changed(self, row):
        if row < 0:
            return
        idx = self.anim.itemData(row)
        info = anm.list_animations(self.preview)[idx]
        self._aidx, self._len, self._loop = idx, max(1, info["length"]), info["loop"]
        self._times = anm.frame_times(self.preview, idx)
        items = [anm.evaluate(self.preview, idx, t) for t in range(0, self._len + 1, max(1, self._len // 30))]
        flat = [i for x in items for i in x]
        self._bounds = anm.item_bounds(flat) if flat else None
        self.slider.blockSignals(True)
        self.slider.setRange(0, self._len)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self._frame_cache = {}
        self._time = 0.0
        self._show(0)
        self._follow()
        self._fit_preview()

    def _render(self, t):
        kind, k = self._mode()
        src = self.rebuilt if kind in ("pal", "all") and self.rebuilt is not None else self.preview
        items = anm.evaluate(src, self._aidx, t)
        if kind != "all" or src is self.preview:
            img, _ = anm.render_items(src, items, k if kind == "pal" and src is not self.preview else 0,
                                      bounds=self._bounds)
            return img
        from PIL import Image, ImageDraw
        imgs = [anm.render_items(src, items, p, bounds=self._bounds)[0] for p in range(self.npal)]
        cols = 3 if len(imgs) > 4 else 2
        rows = (len(imgs) + cols - 1) // cols
        w, h = imgs[0].size
        lab = 12
        out = Image.new("RGBA", (cols * w, rows * (h + lab)))
        d = ImageDraw.Draw(out)
        for k, i in enumerate(imgs):
            x, y = (k % cols) * w, (k // cols) * (h + lab)
            d.text((x + 2, y), "Normal" if k == 0 else f"Extra {k}", fill=(230, 230, 230, 255))
            out.alpha_composite(i, (x, y + lab))
        return out

    def _show(self, t):
        if not hasattr(self, "_aidx"):
            return
        key = int(t)
        pm = self._frame_cache.get(key)
        if pm is None:
            pm = pil_to_pixmap(self._render(key))
            self._frame_cache[key] = pm
        tr = self.pview.transform()
        self.pview.set_image(pm)
        self.pview.setTransform(tr)
        self.frame_lbl.setText(f"{key}/{self._len}")

    def _tick(self):
        if not hasattr(self, "_aidx") or self.play.text() != "⏸":
            return
        self._time += 2
        end = self._loop[1] if self._loop else self._len
        if self._time > end:
            self._time = float(self._loop[0] if self._loop else 0)
        self.slider.blockSignals(True)
        self.slider.setValue(int(self._time))
        self.slider.blockSignals(False)
        self._show(self._time)
        self._follow()

    def _seek(self, v):
        self._time = float(v)
        self._show(v)
        self._follow()

    def _step(self, d):
        """previous / next pose (key time) of the animation"""
        if not hasattr(self, "_times"):
            return
        if self.play.text() == "⏸":
            self._toggle_play()
        ts = self._times
        cur = int(self._time)
        if d > 0:
            nxt = [t for t in ts if t > cur]
            t = nxt[0] if nxt else ts[0]
        else:
            prv = [t for t in ts if t < cur]
            t = prv[-1] if prv else ts[-1]
        self.slider.setValue(int(t))

    def _toggle_play(self):
        self.play.setText("▶" if self.play.text() == "⏸" else "⏸")

    # ================================================================== save
    def save(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = self.model.final()
            sprite = pickle.loads(pickle.dumps(self.sprite))
            outfits.apply_rows(self.ws.fs, self.mod, self.slot, rows, log=self.ws.log, sprite=sprite)
            outfits.save_painter(self.mod, self.N, self.model.state(), self.model.overrides(),
                                 self.model.learned_rows())
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Save parts", str(e))
            return False
        QApplication.restoreOverrideCursor()
        self.dirty = False
        self._update_status()
        self.ws.file_changed.emit(f"Anime/ANM_HI_JP.dat/anm{self.N:05d}.lzs")
        self.ws.log(f"Parts saved for anm{self.N:05d}. Install (bottom left) to see them in game.")
        self.status.setText("Saved — install to see it in game.")
        return True

    def closeEvent(self, e):
        if self.dirty:
            r = QMessageBox.question(self, "Unsaved parts", "Save the parts before closing?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                     QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel or (r == QMessageBox.StandardButton.Save and not self.save()):
                e.ignore()
                return
        self.timer.stop()
        e.accept()
