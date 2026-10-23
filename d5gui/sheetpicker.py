"""Sprite sheet picker: every drawing on a sheet, found by itself (d5lib.framesheet.detect_sprites) or boxed by
hand, and you say which of them are each of the game's animations, in order.  Works with any sheet: a fan sheet
with drawings scattered on one background colour, several characters and effects mixed in, or a labelled frame dump
(its rows are filled in from the labels).  The layout of a sheet is remembered (cache/sheet_layouts), so you can
come back to it.

sequences() gives what the converters take: {(animation, 'front'|'back'): [PIL RGBA frames]}."""
import hashlib
import json
import os

import numpy as np
from PIL import Image
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListView,
                             QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)

from d5lib import framesheet, frameconvert, paths
from .common import pil_to_pixmap

LAYOUTS = os.path.join(paths.KIT_DIR, "cache", "sheet_layouts")
ROLE = Qt.ItemDataRole.UserRole
HUMAN_HELP = {
    "stand": "standing still (one drawing is enough)", "wait": "idle / breathing loop", "walk": "walking loop",
    "dash": "running", "damage": "getting hit, dodging", "squat": "crouching (before a jump, lifting)",
    "two_arm_up_jump": "jumping, lifting someone", "launch": "being thrown", "one_arm_up": "casting a spell, "
    "using an item", "take_out": "drawing the weapon", "attack_fist": "punching (fist attacks)",
    "attack_sword": "sword swing", "attack_lance": "spear thrust", "attack_arrow": "shooting a bow",
    "attack_gun": "shooting a gun", "attack_ax": "axe swing", "kabutowari": "overhead strike", "landing": "landing",
    "rolling": "rolling / tumbling", "roll_landing": "landing from a roll", "gun_aerial": "shooting in the air"}
MONSTER_HELP = {
    "stand": "standing still", "wait": "idle loop", "walk": "moving", "damage": "getting hit, dodging",
    "squat": "crouching, being lifted", "two_arm_up_jump": "jumping", "attack_fist": "its normal attack",
    "one_arm_up": "its skills / spells"}
ESSENTIAL = ("stand", "wait", "walk", "damage")
COLORS = {"stand": "#3ecf8e", "wait": "#3fd0ff", "walk": "#ffb547", "damage": "#ff6b6b"}


def _key(name, view):
    return f"{name}|{view}"


class SheetView(QGraphicsView):
    """the sheet with its boxes; click selects (Ctrl adds), drag a band selects; in 'draw' mode a drag boxes a
    drawing by hand"""
    picked = pyqtSignal(list, bool)          # box indexes, add to the selection
    drawn = pyqtSignal(QRectF)
    menu = pyqtSignal(int, object)           # box index, global pos

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor(14, 12, 24))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.draw_mode = False
        self._press = None
        self._band = None
        self.items = []

    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)

    def _box_at(self, p):
        for it in self.scene().items(p):
            if isinstance(it, QGraphicsRectItem) and it.data(0) is not None:
                return it.data(0)
        return None

    def mousePressEvent(self, e):
        p = self.mapToScene(e.position().toPoint())
        if e.button() == Qt.MouseButton.RightButton:
            k = self._box_at(p)
            if k is not None:
                self.menu.emit(k, e.globalPosition().toPoint())
            return
        if e.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            return super().mousePressEvent(e)
        self._press = p
        self._band = self.scene().addRect(QRectF(p, p), QPen(QColor("#ffd34f"), 0, Qt.PenStyle.DashLine))
        self._band.setZValue(10)

    def mouseMoveEvent(self, e):
        if self._band is not None:
            p = self.mapToScene(e.position().toPoint())
            self._band.setRect(QRectF(self._press, p).normalized())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        if self._band is None:
            return super().mouseReleaseEvent(e)
        r = self._band.rect()
        self.scene().removeItem(self._band)
        self._band = None
        add = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        if r.width() < 3 and r.height() < 3:
            k = self._box_at(self._press)
            self.picked.emit([k] if k is not None else [], add)
        elif self.draw_mode:
            self.drawn.emit(r)
        else:
            hits = [it.data(0) for it in self.scene().items(r, Qt.ItemSelectionMode.IntersectsItemShape)
                    if isinstance(it, QGraphicsRectItem) and it.data(0) is not None]
            self.picked.emit(sorted(set(hits)), add)


class SheetPicker(QDialog):
    def __init__(self, path, parent=None, monster=False, title=None, target_height=0):
        super().__init__(parent)
        self.path, self.monster, self.target_height = path, monster, int(target_height or 0)
        self.setWindowTitle(title or "Sprite sheet")
        self.resize(1400, 860)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.im = np.asarray(Image.open(path).convert("RGBA"))
            self.bg = framesheet.background_colors(self.im)
            self.boxes = framesheet.detect_sprites(self.im, self.bg)
        finally:
            QApplication.restoreOverrideCursor()
        self.sel = []
        self.assign = {}                     # key -> [[box index, flip]]
        self.names = list(MONSTER_HELP) if monster else list(frameconvert.ANIM_NAMES)
        self.help = MONSTER_HELP if monster else HUMAN_HELP
        self._thumbs = {}

        lay = QVBoxLayout(self)
        head = QLabel(
            "<b>1.</b> Pick an animation on the right. <b>2.</b> Click its drawings on the sheet in order "
            "(Ctrl+click or drag a box around several to select more), then <b>Add the selected</b>. The preview "
            "plays it. Drawings the kit didn't box right: <b>✂ Draw a box</b> around one by hand, or right-click "
            "a box to merge or delete it. Every animation needs at least: " + ", ".join(ESSENTIAL) + ". Missing "
            "ones borrow the closest drawings." + (" (A monster: its own moves.)" if monster else ""))
        head.setWordWrap(True)
        lay.addWidget(head)
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.b_draw = QPushButton("✂ Draw a box")
        self.b_draw.setCheckable(True)
        self.b_draw.setToolTip("Drag around a drawing to box it by hand (the box shrinks to the drawing)")
        self.b_draw.toggled.connect(lambda on: setattr(self.view, "draw_mode", on))
        tools.addWidget(self.b_draw)
        b = QPushButton("Merge selected")
        b.setToolTip("One drawing made of the selected boxes (a pose the kit cut in pieces)")
        b.clicked.connect(self._merge)
        tools.addWidget(b)
        tools.addWidget(QLabel("Join pieces closer than"))
        self.gap = QSpinBox()
        self.gap.setRange(0, 12)
        self.gap.setValue(2)
        self.gap.setSuffix(" px")
        self.gap.setToolTip("Separate pieces this close count as one drawing (raise it when hair or weapons come "
                            "out as boxes of their own). Finds the drawings again: hand-drawn boxes stay.")
        self.gap.valueChanged.connect(self._redetect)
        tools.addWidget(self.gap)
        tools.addStretch(1)
        self.count = QLabel()
        self.count.setObjectName("muted")
        tools.addWidget(self.count)
        ll.addLayout(tools)
        self.view = SheetView()
        self.view.picked.connect(self._picked)
        self.view.drawn.connect(self._drawn)
        self.view.menu.connect(self._box_menu)
        ll.addWidget(self.view, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Facing"))
        self.view_box = QComboBox()
        self.view_box.addItem("front (towards you)", "front")
        self.view_box.addItem("back (away from you)", "back")
        self.view_box.setToolTip("Drawings of the character from behind go to 'back'. Without them the front "
                                 "drawings are used for both.")
        self.view_box.currentIndexChanged.connect(self._fill_targets)
        row.addWidget(self.view_box, 1)
        rl.addLayout(row)
        self.targets = QListWidget()
        self.targets.setMaximumHeight(260)
        self.targets.currentRowChanged.connect(lambda *_: self._show_target())
        rl.addWidget(self.targets)
        self.strip = QListWidget()
        self.strip.setViewMode(QListView.ViewMode.IconMode)
        self.strip.setFlow(QListView.Flow.LeftToRight)
        self.strip.setWrapping(True)
        self.strip.setIconSize(QSize(72, 72))
        self.strip.setMovement(QListView.Movement.Snap)
        self.strip.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.strip.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.strip.setMaximumHeight(190)
        self.strip.model().rowsMoved.connect(lambda *_: self._strip_reordered())
        rl.addWidget(self.strip)
        row = QHBoxLayout()
        for text, fn, tip in (("➕ Add the selected", self._add, "The drawings selected on the sheet, in reading "
                                                                 "order, at the end of this animation"),
                              ("➖ Remove", self._remove, "Take the chosen frames out of this animation"),
                              ("⇆ Flip", self._flip, "Mirror the chosen frames (drawn facing the other way)"),
                              ("Clear", self._clear, "Empty this animation")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        rl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Preview"))
        self.fps = QSpinBox()
        self.fps.setRange(2, 30)
        self.fps.setValue(8)
        self.fps.setSuffix(" fps")
        self.fps.setToolTip("Only for this preview: in game every pose takes the timing of the game's own animation")
        self.fps.valueChanged.connect(lambda v: self.timer.setInterval(int(1000 / v)))
        row.addWidget(self.fps)
        row.addStretch(1)
        row.addWidget(QLabel("Size in game"))
        self.size = QComboBox()
        if self.target_height:
            self.size.addItem("as tall as the template", 0.0)
        for f in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
            self.size.addItem(f"× {f:g}", f)
        self.size.setToolTip("Sheets drawn small (many fan sheets are half the game's size) are scaled up, pixel by "
                             "pixel so they stay sharp")
        self.size.currentIndexChanged.connect(lambda *_: self._coverage())
        row.addWidget(self.size)
        rl.addLayout(row)
        self.preview = QLabel()
        self.preview.setMinimumHeight(170)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #1b1830; border-radius: 6px;")
        rl.addWidget(self.preview, 1)
        self.cover = QLabel()
        self.cover.setWordWrap(True)
        self.cover.setObjectName("muted")
        rl.addWidget(self.cover)
        split.addWidget(right)
        split.setSizes([920, 460])
        lay.addWidget(split, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Use these drawings")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.timer = QTimer(self)
        self.timer.setInterval(125)
        self.timer.timeout.connect(self._tick)
        self._frame_i = 0
        self._load_layout() or self._from_labels()
        self._draw_sheet()
        self._fill_targets()
        self.timer.start()

    # ------------------------------------------------------------------ the sheet
    def _draw_sheet(self):
        sc = self.view.scene()
        sc.clear()
        sc.addPixmap(pil_to_pixmap(Image.fromarray(self.im, "RGBA")))
        used = {}
        for key, frames in self.assign.items():
            for bi, _ in frames:
                used.setdefault(bi, key.split("|")[0])
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        self.view.items = []
        for i, (x0, y0, x1, y1) in enumerate(self.boxes):
            sel = i in self.sel
            name = used.get(i)
            col = QColor("#ffd34f") if sel else QColor(COLORS.get(name, "#c58cff")) if name else QColor(90, 240,
                                                                                                         140, 150)
            it = sc.addRect(QRectF(x0 - 0.5, y0 - 0.5, x1 - x0 + 1, y1 - y0 + 1), QPen(col, 2 if sel or name else 1))
            it.setData(0, i)
            if sel:
                it.setBrush(QBrush(QColor(255, 211, 79, 50)))
            if name:
                t = sc.addSimpleText(name.replace("attack_", "")[:6], font)
                t.setBrush(QBrush(col))
                t.setPos(x0, y0 - 12)
            self.view.items.append(it)
        sc.setSceneRect(QRectF(-20, -20, self.im.shape[1] + 40, self.im.shape[0] + 40))
        self.count.setText(f"{len(self.boxes)} drawings found · {len(self.sel)} selected")

    def _picked(self, idx, add):
        if add:
            for i in idx:
                if i in self.sel:
                    self.sel.remove(i)
                else:
                    self.sel.append(i)
        else:
            self.sel = list(idx)
        self._draw_sheet()

    def _drawn(self, r):
        x0, y0 = max(0, int(r.left())), max(0, int(r.top()))
        x1, y1 = min(self.im.shape[1], int(r.right()) + 1), min(self.im.shape[0], int(r.bottom()) + 1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        m = framesheet.foreground(self.im[y0:y1, x0:x1], self.bg)
        if m.any():                                  # (shrunk to the drawing inside)
            ys, xs = np.nonzero(m)
            x0, x1, y0, y1 = x0 + xs.min(), x0 + xs.max() + 1, y0 + ys.min(), y0 + ys.max() + 1
        self.boxes.append((int(x0), int(y0), int(x1), int(y1)))
        self.sel = [len(self.boxes) - 1]
        self.b_draw.setChecked(False)
        self._draw_sheet()

    def _merge(self):
        if len(self.sel) < 2:
            return
        bs = [self.boxes[i] for i in self.sel]
        new = (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))
        self._replace_boxes(set(self.sel), [new])

    def _box_menu(self, k, pos):
        m = QMenu(self)
        a_del = m.addAction("Delete this box")
        a_merge = m.addAction("Merge with the selected") if self.sel and k not in self.sel else None
        a = m.exec(pos)
        if a is a_del:
            self._replace_boxes({k}, [])
        elif a_merge is not None and a is a_merge:
            self.sel.append(k)
            self._merge()

    def _replace_boxes(self, gone, new):
        """remove boxes `gone`, add `new`; assignments follow (a merged box takes the first one's places)"""
        keep = [i for i in range(len(self.boxes)) if i not in gone]
        remap = {old: n for n, old in enumerate(keep)}
        first_gone = min(gone) if gone else None
        boxes = [self.boxes[i] for i in keep] + list(new)
        for key, frames in list(self.assign.items()):
            out = []
            for bi, flip in frames:
                if bi in remap:
                    out.append([remap[bi], flip])
                elif new and bi == first_gone:
                    out.append([len(keep), flip])
            self.assign[key] = out
        self.boxes = boxes
        self.sel = [len(keep)] if new else []
        self._thumbs.clear()
        self._draw_sheet()
        self._fill_targets()

    def _redetect(self, *_):
        hand = [b for i, b in enumerate(self.boxes) if any(i == f[0] for fr in self.assign.values() for f in fr)]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            found = framesheet.detect_sprites(self.im, self.bg, gap=self.gap.value())
        finally:
            QApplication.restoreOverrideCursor()
        # boxes in use stay as they are (their animations keep them)
        old = self.boxes
        self.boxes = list(hand) + [b for b in found if b not in hand]
        remap = {old.index(b): i for i, b in enumerate(hand)}
        self.assign = {k: [[remap[bi], f] for bi, f in fr if bi in remap] for k, fr in self.assign.items()}
        self.sel = []
        self._thumbs.clear()
        self._draw_sheet()
        self._fill_targets()

    # ------------------------------------------------------------------ animations
    def _cur_key(self):
        it = self.targets.currentItem()
        return it.data(ROLE) if it else None

    def _fill_targets(self, *_):
        view = self.view_box.currentData()
        cur = self.targets.currentRow()
        self.targets.blockSignals(True)
        self.targets.clear()
        for name in self.names:
            n = len(self.assign.get(_key(name, view), []))
            need = name in ESSENTIAL and view == "front"
            it = QListWidgetItem(f"{'✅' if n else ('❗' if need else '·')}  {name}   ({n})   — "
                                 f"{self.help.get(name, '')}")
            it.setData(ROLE, _key(name, view))
            if need and not n:
                it.setForeground(QBrush(QColor("#ff8a8a")))
            self.targets.addItem(it)
        self.targets.blockSignals(False)
        self.targets.setCurrentRow(max(0, cur))
        self._show_target()
        self._coverage()

    def _thumb(self, bi, flip):
        k = (bi, flip)
        if k not in self._thumbs:
            img = framesheet.cutout(self.im, self.boxes[bi], self.bg, flip)
            self._thumbs[k] = img
        return self._thumbs[k]

    def _show_target(self):
        key = self._cur_key()
        self.strip.clear()
        if key is None:
            return
        for n, (bi, flip) in enumerate(self.assign.get(key, [])):
            img = self._thumb(bi, flip).copy()
            img.thumbnail((72, 72))
            it = QListWidgetItem(QIcon(pil_to_pixmap(img)), str(n + 1) + (" ⇆" if flip else ""))
            it.setData(ROLE, (bi, flip))
            self.strip.addItem(it)
        self._frame_i = 0

    def _strip_reordered(self):
        key = self._cur_key()
        if key is None:
            return
        self.assign[key] = [list(self.strip.item(i).data(ROLE)) for i in range(self.strip.count())]
        self._show_target()

    def _add(self):
        key = self._cur_key()
        if key is None or not self.sel:
            return
        order = [i for i in range(len(self.boxes)) if i in self.sel]
        order = sorted(order, key=lambda i: framesheet.reading_order([self.boxes[j] for j in order]).index(
            self.boxes[i]))
        self.assign.setdefault(key, []).extend([[i, False] for i in order])
        self.sel = []
        self._draw_sheet()
        self._fill_targets()
        self._save_layout()

    def _chosen(self):
        return sorted(self.strip.row(it) for it in self.strip.selectedItems())

    def _remove(self):
        key = self._cur_key()
        rows = self._chosen()
        if key is None or not rows:
            return
        self.assign[key] = [f for n, f in enumerate(self.assign.get(key, [])) if n not in rows]
        self._draw_sheet()
        self._fill_targets()
        self._save_layout()

    def _flip(self):
        key = self._cur_key()
        rows = self._chosen() or list(range(len(self.assign.get(key or "", []))))
        if key is None:
            return
        for n in rows:
            self.assign[key][n][1] = not self.assign[key][n][1]
        self._show_target()
        self._save_layout()

    def _clear(self):
        key = self._cur_key()
        if key and self.assign.get(key):
            self.assign[key] = []
            self._draw_sheet()
            self._fill_targets()
            self._save_layout()

    def _tick(self):
        key = self._cur_key()
        frames = self.assign.get(key, []) if key else []
        if not frames:
            self.preview.setText("Add drawings to see the animation")
            return
        imgs = [self._thumb(bi, f) for bi, f in frames]
        w = max(i.width for i in imgs)
        h = max(i.height for i in imgs)
        self._frame_i = (self._frame_i + 1) % len(imgs)
        img = imgs[self._frame_i]
        canvas = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
        canvas.paste(img, ((w + 8 - img.width) // 2, h + 4 - img.height), img)   # feet on one line
        z = max(1, min(4, int(160 / max(1, h + 8))))
        canvas = canvas.resize((canvas.width * z, canvas.height * z), Image.NEAREST)
        self.preview.setPixmap(pil_to_pixmap(canvas))

    def scale(self):
        """how much the drawings grow in game"""
        f = self.size.currentData()
        if f:
            return f
        frames = (self.assign.get(_key("stand", "front")) or self.assign.get(_key("wait", "front")) or
                  [x for v in self.assign.values() for x in v])
        hs = [self._thumb(bi, fl).getchannel("A").getbbox() for bi, fl in frames[:12]]
        hs = sorted(b[3] - b[1] for b in hs if b)
        if not hs or not self.target_height:
            return 1.0
        return max(1.0, round(self.target_height / hs[len(hs) // 2] * 2) / 2)

    def _coverage(self):
        have = [n for n in self.names if self.assign.get(_key(n, "front")) or self.assign.get(_key(n, "back"))]
        missing = [n for n in ESSENTIAL if n not in have]
        backs = sum(1 for n in self.names if self.assign.get(_key(n, "back")))
        self.cover.setText(f"{len(have)} of {len(self.names)} animations have drawings"
                           + (f"; still needed: {', '.join(missing)}." if missing else "; the needed ones are there.")
                           + ("" if backs else " No back views: the front drawings are used for both.")
                           + (f" In game the drawings are × {self.scale():g}." if any(self.assign.values()) else ""))

    # ------------------------------------------------------------------ remembering a sheet
    def _layout_path(self):
        h = hashlib.sha1(self.im.tobytes()[::97]).hexdigest()[:16]
        return os.path.join(LAYOUTS, f"{os.path.splitext(os.path.basename(self.path))[0][:40]}-{h}.json")

    def _save_layout(self):
        try:
            os.makedirs(LAYOUTS, exist_ok=True)
            with open(self._layout_path(), "w", encoding="utf-8") as f:
                json.dump({"boxes": self.boxes, "assign": self.assign, "monster": self.monster}, f)
        except OSError:
            pass

    def _load_layout(self):
        try:
            with open(self._layout_path(), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return False
        self.boxes = [tuple(b) for b in d.get("boxes") or []] or self.boxes
        self.assign = {k: [list(x) for x in v if 0 <= x[0] < len(self.boxes)] for k, v in
                       (d.get("assign") or {}).items()}
        return True

    def _from_labels(self):
        """a labelled frame dump: its rows go to the animations their labels name"""
        try:
            im, rows = framesheet.parse_sheet(self.path)
            guesses = framesheet.guess_rows(im, rows)
        except Exception:
            return
        for r, (name, view, text) in zip(rows, guesses):
            if not name or name.endswith("_hand") or name not in self.names:
                continue
            for c in r["cells"]:
                if c not in self.boxes:
                    self.boxes.append(c)
                self.assign.setdefault(_key(name, view), []).append([self.boxes.index(c), False])

    # ------------------------------------------------------------------ result
    def _ok(self):
        missing = [n for n in ESSENTIAL if not (self.assign.get(_key(n, "front")) or self.assign.get(_key(n, "back")))]
        if missing and QMessageBox.question(
                self, "Sprite sheet", f"No drawings for {', '.join(missing)} yet: those moves will borrow the "
                "closest other drawings, which can look odd.\n\nUse the sheet anyway?") != \
                QMessageBox.StandardButton.Yes:
            return
        if not any(self.assign.values()):
            QMessageBox.warning(self, "Sprite sheet", "Give at least one animation its drawings.")
            return
        self._save_layout()
        self.accept()

    def sequences(self):
        out = {}
        f = self.scale()
        for key, frames in self.assign.items():
            if not frames:
                continue
            name, view = key.split("|")
            imgs = [self._thumb(bi, flip) for bi, flip in frames]
            if f != 1.0:
                imgs = [im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.NEAREST)
                        for im in imgs]
            out[(name, view)] = imgs
        return out

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_fitted", False):           # the whole width of the sheet at first
            self._fitted = True
            QTimer.singleShot(0, self._fit)

    def _fit(self):
        vw = max(100, self.view.viewport().width() - 10)
        s = min(3.0, vw / max(1, self.im.shape[1]))
        self.view.resetTransform()
        self.view.scale(s, s)

    def done(self, r):
        self.timer.stop()
        super().done(r)
