"""Library of the game's effect models (Effect.dat) and the mods' new ones: thumbnails with names, categories,
search by name / number / skill that uses it; drag one onto the timeline (or double-click: add at the playhead).
Right-click an effect to rename it or change its category (d5lib/fxnames.py)."""
import numpy as np
from PyQt6.QtCore import Qt, QSize, QTimer, QMimeData, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPainter, QColor, QPixmap
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QListWidget, QListWidgetItem, QLineEdit, QLabel, QHBoxLayout,
                             QCheckBox, QComboBox, QMenu, QInputDialog)

from d5lib import fxnames
from .render import Camera
from .timeline import MIME

THUMB = 92


def render_thumb(fx, eid, t=None, size=THUMB):
    m = fx.model(eid)
    if m is not None and t is None:
        t = m.best_frame()
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#0b0d1d"))
    if m is None or not m.parts:
        return img
    cam = Camera()
    cam.yaw, cam.pitch = 0.0, 0.0 if m.flat else 35.0
    cam.update()
    ext = (m.hi - m.lo) * 10.0
    span = max(1.0, float(np.max(ext[[0, 1]] if m.flat else ext)))
    cam.scale = (size - 10) / span
    cam.focus = (m.lo + m.hi) / 2.0 * 10.0
    slot = dict(effect=eid, size=1000, scale=[100, 100, 100], rot=[0, 0, 0], color=[100, 100, 100, 100], time=t,
                speed=100)
    qp = QPainter(img)
    qp.setPen(Qt.PenStyle.NoPen)
    try:
        for batch in fx.triangles(slot, np.zeros(3), cam):
            pts, d = cam.project(batch[3].reshape(-1, 3), size, size)
            pts = pts.reshape(-1, 3, 2)
            order = np.argsort(fx.poly_depths(batch, d.reshape(-1, 3).mean(1)))
            fx.draw_batch(qp, batch, pts, order)
    except Exception:
        pass
    qp.end()
    return img


class _List(QListWidget):
    def mimeData(self, items):
        md = QMimeData()
        if items:
            md.setData(MIME, str(items[0].data(Qt.ItemDataRole.UserRole)).encode())
        return md

    def mimeTypes(self):
        return [MIME]


class EffectLibrary(QFrame):
    picked = pyqtSignal(int)          # double-click
    current = pyqtSignal(int)
    renamed = pyqtSignal(int)         # an effect's name / category changed

    def __init__(self, fx, names=None):
        super().__init__()
        self.fx = fx
        self.names = names or fxnames.Names()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        hint = QLabel("Drag an effect onto the timeline, or double-click to add it at the playhead. "
                      "Right-click to rename it.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: name, number or a skill that uses it…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        row = QHBoxLayout()
        self.cat = QComboBox()
        self.cat.addItem("All categories", None)
        for key, label in fxnames.CATEGORIES:
            self.cat.addItem(label, key)
        self.cat.currentIndexChanged.connect(self._filter)
        row.addWidget(self.cat, 1)
        self.used_only = QCheckBox("In this skill")
        self.used_only.toggled.connect(self._filter)
        row.addWidget(self.used_only)
        lay.addLayout(row)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        lay.addWidget(self.count)
        self.list = _List()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setGridSize(QSize(THUMB + 26, THUMB + 40))
        self.list.setWordWrap(True)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setDragEnabled(True)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(4)
        self.list.itemDoubleClicked.connect(lambda it: self.picked.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.list.currentItemChanged.connect(
            lambda it, _: it and self.current.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        self.items = {}
        self.used = set()
        self.todo = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._work)
        blank = QPixmap(THUMB, THUMB)
        blank.fill(QColor("#0b0d1d"))
        self.blank = QIcon(blank)

    def _text(self, e):
        return ("★ " if e in self.used else "") + self.names.name(e)

    def fill(self, ids):
        self.list.clear()
        self.items = {}
        for e in sorted(ids):
            it = QListWidgetItem(self.blank, self._text(e))
            it.setData(Qt.ItemDataRole.UserRole, e)
            it.setToolTip(self.names.tooltip(e))
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.list.addItem(it)
            self.items[e] = it
        self.todo = sorted(ids)
        self.timer.start(15)
        self._filter()

    def refresh_names(self):
        for e, it in self.items.items():
            it.setText(self._text(e))
            it.setToolTip(self.names.tooltip(e))
        self._filter()

    def set_used(self, used):
        self.used = set(used)
        for e, it in self.items.items():
            it.setText(self._text(e))
        self._filter()

    def select(self, eid):
        it = self.items.get(int(eid))
        if it is not None:
            if it.isHidden():
                self.search.clear()
                self.cat.setCurrentIndex(0)
                self.used_only.setChecked(False)
            self.list.setCurrentItem(it)
            self.list.scrollToItem(it)

    def _filter(self, *_):
        q = self.search.text().strip()
        only = self.used_only.isChecked()
        cat = self.cat.currentData()
        shown = 0
        for e, it in self.items.items():
            hide = (bool(q) and not self.names.matches(e, q)) or (only and e not in self.used) or \
                   (cat is not None and self.names.cat(e) != cat)
            it.setHidden(hide)
            shown += not hide
        self.count.setText(f"{shown} of {len(self.items)} effects")

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        e = int(it.data(Qt.ItemDataRole.UserRole))
        m = QMenu(self)
        m.addAction(f"✏  Rename “{self.names.name(e)}”…", lambda: self._rename(e))
        cm = m.addMenu("🗂  Category")
        for key, label in fxnames.CATEGORIES:
            a = cm.addAction(label, lambda k=key: self._set_cat(e, k))
            a.setCheckable(True)
            a.setChecked(self.names.cat(e) == key)
        m.addAction("↺  Back to the kit's name", lambda: self._reset(e))
        m.exec(self.list.mapToGlobal(pos))

    def _rename(self, e):
        name, ok = QInputDialog.getText(self, "Rename effect", f"Name of effect {e}:", text=self.names.name(e))
        if ok and name.strip():
            self.names.rename(e, name=name.strip())
            self._changed(e)

    def _set_cat(self, e, key):
        self.names.rename(e, cat=key)
        self._changed(e)

    def _reset(self, e):
        self.names.rename(e, name="", cat="")
        self._changed(e)

    def _changed(self, e):
        it = self.items.get(e)
        if it is not None:
            it.setText(self._text(e))
            it.setToolTip(self.names.tooltip(e))
        self._filter()
        self.renamed.emit(e)

    def _work(self):
        # visible ones first
        vis = [e for e, it in self.items.items() if e in self.todo and not it.isHidden()
               and self.list.visualItemRect(it).intersects(self.list.viewport().rect())]
        batch = (vis or self.todo)[:3]
        for e in batch:
            self.todo.remove(e)
            self.items[e].setIcon(QIcon(QPixmap.fromImage(render_thumb(self.fx, e))))
        if not self.todo:
            self.timer.stop()
