"""New stage: pick the battlefield it starts from in a grid of pictures of the game's maps (their own 3D terrain,
d5gui.mapthumbs), name it, and choose what it starts with."""
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QListView, QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout, QWidget)

from . import mapthumbs
from .common import SearchBox

ROLE = Qt.ItemDataRole.UserRole
THUMB = QSize(240, 165)
START = [("units", "Its enemies, objects and Geo Symbols"),
         ("objects", "Only its objects and Geo Symbols (no enemies)"),
         ("empty", "Nothing: an empty battlefield"),
         ("build", "Blocks: a battlefield you build yourself (a stone slab on a 12×12 grid to start)")]


class _Painter(QThread):
    """draws the pictures one by one (cached ones come at once); the ones in view first (want())"""
    ready = pyqtSignal(int, QImage)

    def __init__(self, ids, data_dir):
        super().__init__()
        import collections
        import threading
        self.todo = collections.deque(dict.fromkeys(ids))
        self.lock = threading.Lock()
        self.done_ids = set()
        self.data_dir, self.stop = data_dir, False

    def want(self, ids):
        """these next (the pictures in view)"""
        with self.lock:
            for mid in reversed(list(ids)):
                if mid not in self.done_ids:
                    try:
                        self.todo.remove(mid)
                    except ValueError:
                        pass
                    self.todo.appendleft(mid)

    def run(self):
        while not self.stop:
            with self.lock:
                if not self.todo:
                    return
                mid = self.todo.popleft()
                self.done_ids.add(mid)
            try:
                img = mapthumbs.thumbnail(mid, self.data_dir, (THUMB.width(), THUMB.height()))
            except Exception:
                img = None
            if img is not None and not self.stop:
                self.ready.emit(mid, img)


class NewStageDialog(QDialog):
    """stages: [(label, map id, dungeon row or None)] to choose from; listed: [(label, map id, row)] of the stages a
    new one can be listed with (they have a story flag)"""

    def __init__(self, parent, stages, data_dir, current=None, listed=()):
        super().__init__(parent)
        self.setWindowTitle("New stage")
        self.resize(1180, 760)
        lay = QVBoxLayout(self)
        head = QLabel("Pick the battlefield your stage starts from. You get a copy of its terrain under a new map "
                      "number, as a stage of its own; then place enemies, Geo Panels and the base panel as you "
                      "like.")
        head.setWordWrap(True)
        lay.addWidget(head)
        top = QHBoxLayout()
        self.search = SearchBox("Search maps…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        self.only = QCheckBox("Battle stages only")
        self.only.setChecked(True)
        self.only.setToolTip("Leave out the base, Item World rooms and other places that aren't battles")
        self.only.toggled.connect(lambda *_: self._filter(self.search.text()))
        top.addWidget(self.only)
        lay.addLayout(top)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(QSize(THUMB.width() + 18, THUMB.height() + 46))
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setWordWrap(True)
        self.grid.setUniformItemSizes(True)
        self.grid.currentItemChanged.connect(self._picked)
        self.grid.itemDoubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.grid, 1)
        blank = QPixmap(THUMB)
        blank.fill(QColor(30, 28, 48))
        self._items = {}
        for label, mid, row in stages:
            it = QListWidgetItem(QIcon(blank), f"{label}\nmap{mid:05d}")
            it.setData(ROLE, (mid, row, label))
            it.setToolTip(f"{label} (map{mid:05d})")
            self.grid.addItem(it)
            self._items.setdefault(mid, []).append(it)
        f = QFormLayout()
        self.name = QLineEdit("My New Stage")
        f.addRow("Name of the new stage", self.name)
        self.start = QComboBox()
        for k, label in START:
            self.start.addItem(label, k)
        f.addRow("It starts with", self.start)
        self.panels = QCheckBox("Keep its Geo Panels")
        self.panels.setChecked(True)
        f.addRow("", self.panels)
        self.size_w, self.size_h = QSpinBox(), QSpinBox()
        for sb in (self.size_w, self.size_h):
            sb.setRange(1, 64)
            sb.setValue(12)
        self.size_row = QWidget()
        sh = QHBoxLayout(self.size_row)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.addWidget(self.size_w)
        sh.addWidget(QLabel("×"))
        sh.addWidget(self.size_h)
        sh.addWidget(QLabel("panels (changed later under 🧱 Blocks › Map size)"))
        sh.addStretch(1)
        self.size_label = QLabel("Map size")
        f.addRow(self.size_label, self.size_row)
        self.start.currentIndexChanged.connect(lambda *_: self._start_changed())
        self.listed = QComboBox()
        self.listed.addItem("Not in the stage list (test it by pointing a stage at it)", None)
        for label, mid, row in listed:
            self.listed.addItem(f"{label}  ·  episode {mid // 100}", (mid, row))
        self.listed.setToolTip("The game's stage list (Dimension Guide) shows a stage in the episode of its map "
                               "number once its story flag is set. The new stage takes the flag of the stage "
                               "chosen here: it is listed in that stage's episode, right when that stage is.")
        f.addRow("In the stage list with", self.listed)
        self.chosen = QLabel()
        self.chosen.setObjectName("muted")
        f.addRow("Starts from", self.chosen)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Create the stage")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._filter("")
        self._start_changed()
        if current is not None and current in self._items:
            self.grid.setCurrentItem(self._items[current][0])
            self.grid.scrollToItem(self._items[current][0])
        order = [current] * (current in self._items) + [m for m in self._items if m != current]
        self._painter = _Painter(order, data_dir)
        self._painter.ready.connect(self._ready)
        self._painter.start()
        self.grid.verticalScrollBar().valueChanged.connect(lambda *_: self._in_view())
        self.search.textChanged.connect(lambda *_: self._in_view())
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(200, self._in_view)

    def _in_view(self):
        """the maps shown in the grid right now go first"""
        r = self.grid.viewport().rect()
        ids = []
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            if not it.isHidden() and self.grid.visualItemRect(it).intersects(r):
                ids.append(it.data(ROLE)[0])
        if ids:
            self._painter.want(ids)

    def _ready(self, mid, img):
        icon = QIcon(QPixmap.fromImage(img))
        for it in self._items.get(mid, []):
            it.setIcon(icon)

    def _filter(self, text):
        t = (text or "").lower()
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            mid, row, label = it.data(ROLE)
            hide = bool(t) and t not in it.text().lower()
            if self.only.isChecked() and (row is None or mid >= 21001 or "(Demo)" in label or "Dummy" in label):
                hide = True
            it.setHidden(hide)

    def _picked(self, it, prev=None):
        if it is not None:
            mid, row, label = it.data(ROLE)
            self.chosen.setText(f"{label} (map{mid:05d})")
            for k in range(self.listed.count()):           # (findData doesn't compare Python tuples)
                if self.listed.itemData(k) == (mid, row):
                    self.listed.setCurrentIndex(k)
                    break

    def _ok(self):
        if self.grid.currentItem() is None or self.grid.currentItem().isHidden():
            self.chosen.setText("Pick a map first.")
            return
        self.accept()

    def _start_changed(self):
        build = self.start.currentData() == "build"
        self.size_row.setVisible(build)
        self.size_label.setVisible(build)
        self.panels.setEnabled(not build)

    def values(self):
        mid, row, label = self.grid.currentItem().data(ROLE)
        return {"map": mid, "row": row, "base_name": label, "name": self.name.text().strip() or "My New Stage",
                "start": self.start.currentData(), "panels": self.panels.isChecked(),
                "listed": self.listed.currentData(), "size": (self.size_w.value(), self.size_h.value())}

    def done(self, r):
        self._painter.stop = True
        self._painter.wait(3000)
        super().done(r)
