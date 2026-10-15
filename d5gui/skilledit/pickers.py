"""Choosing by sight: a character's poses as animated pictures, sound effects as waveforms you can hear.

PosePicker  — a grid of every pose of a sprite, each playing its animation; type to filter; double-click / OK picks.
SoundPicker — every sound effect with its waveform, length and the skills that use it; click plays it."""
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit, QLabel,
                             QDialogButtonBox, QCheckBox, QAbstractItemView)

from .thumbs import glyph

ROLE = Qt.ItemDataRole.UserRole


class PoseGrid(QListWidget):
    """animated pose pictures of one sprite: items carry (motion, animation id)"""
    picked = pyqtSignal(int)

    def __init__(self, thumbs, size=84):
        super().__init__()
        self.thumbs, self.size = thumbs, size
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 34, size + 44))
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.itemDoubleClicked.connect(lambda it: self.picked.emit(int(it.data(ROLE)[0])))
        self.num = None
        self.tick = 0
        self.todo = []
        self.anim = QTimer(self)
        self.anim.setInterval(110)                    # about the game's pace for a thumbnail
        self.anim.timeout.connect(self._step)
        self.fill = QTimer(self)
        self.fill.setInterval(0)
        self.fill.timeout.connect(self._fill_some)

    def set_sprite(self, num, poses, current=None):
        """poses: [(label, motion)]; current: the motion to select"""
        self.clear()
        self.num = num
        self.todo = []
        blank = QIcon(glyph("…", self.size, "#171a33", "#555b86"))
        rows = []
        for label, m in poses:
            aid = self.thumbs.aid_for(num, m) if num else None
            ok = aid is not None and self.thumbs.draws(num, aid)
            rows.append((not ok, label if ok else f"{label} — draws nothing", m, aid))
        rows.sort(key=lambda r: r[0])                 # poses this character has pictures for first
        for empty, label, m, aid in rows:
            it = QListWidgetItem(blank, label)
            it.setData(ROLE, (int(m), aid))
            it.setToolTip(f"{label}\nanimation {aid}" if aid else label)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.addItem(it)
            if current is not None and int(m) == int(current):
                self.setCurrentItem(it)
            self.todo.append(it)
        cur = self.currentItem()
        if cur is not None:
            self.scrollToItem(cur, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.todo.sort(key=lambda it: 0 if it is cur else 1)
        self.fill.start()
        self.anim.start()

    def _fill_some(self):
        """pictures for a few items per event-loop turn, visible ones first (the dialog stays responsive)"""
        if not self.todo:
            self.fill.stop()
            return
        vis = self.viewport().rect()
        self.todo.sort(key=lambda it: 0 if self.visualItemRect(it).intersects(vis) else 1)
        for it in self.todo[:3]:
            m, aid = it.data(ROLE)
            fr = self.thumbs.pose_frames(self.num, aid, self.size) if aid is not None else []
            it.setIcon(QIcon(fr[0] if fr else glyph("?", self.size, "#171a33", "#555b86")))
        self.todo = self.todo[3:]

    def _step(self):
        """play every visible pose (frames are cached after the first round)"""
        if self.num is None or not self.isVisible():
            return
        self.tick += 1
        vis = self.viewport().rect()
        for k in range(self.count()):
            it = self.item(k)
            if it in self.todo or not self.visualItemRect(it).intersects(vis):
                continue
            m, aid = it.data(ROLE)
            fr = self.thumbs.pose_frames(self.num, aid, self.size) if aid is not None else []
            if len(fr) > 1:
                it.setIcon(QIcon(fr[self.tick % len(fr)]))

    def apply_filter(self, text):
        t = text.strip().lower()
        for k in range(self.count()):
            it = self.item(k)
            it.setHidden(bool(t) and t not in it.text().lower())

    def current_motion(self):
        it = self.currentItem()
        return int(it.data(ROLE)[0]) if it is not None else None


class PosePicker(QDialog):
    """pick a pose of a character by its animation"""

    def __init__(self, parent, thumbs, num, poses, current=None, who="the character"):
        super().__init__(parent)
        self.setWindowTitle(f"Choose a pose for {who}")
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        hint = QLabel("Every pose plays its animation. Double-click one (or select it and OK) to use it.")
        hint.setObjectName("muted")
        top.addWidget(hint, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter: cast, attack, 109 …")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(240)
        top.addWidget(self.search)
        lay.addLayout(top)
        self.grid = PoseGrid(thumbs)
        self.grid.set_sprite(num, poses, current)
        self.grid.picked.connect(lambda m: self.accept())
        self.search.textChanged.connect(self.grid.apply_filter)
        lay.addWidget(self.grid, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def value(self):
        return self.grid.current_motion()


class SoundPicker(QDialog):
    """pick a sound effect by ear: waveform, length, the skills that use it; click plays"""
    play = pyqtSignal(int)

    def __init__(self, parent, thumbs, bank, used_in=None, current=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a sound")
        self.resize(760, 640)
        self.thumbs, self.bank, self.used_in = thumbs, bank, used_in or {}
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        hint = QLabel("Click a sound to hear it; double-click (or OK) uses it.")
        hint.setObjectName("muted")
        top.addWidget(hint, 1)
        self.only_used = QCheckBox("Only sounds skills use")
        self.only_used.setChecked(bool(self.used_in))
        top.addWidget(self.only_used)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Number or skill name…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(220)
        top.addWidget(self.search)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setIconSize(QSize(180, 34))
        self.list.setUniformItemSizes(True)
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        ids = []
        pack = getattr(bank, "pack", None)
        if pack is not None:
            for name in sorted(pack.by_name):
                try:
                    ids.append(int(name.split(".")[0]))
                except ValueError:
                    pass
        self.items = []
        for sid in ids:
            users = self.used_in.get(sid, [])
            text = f"Sound {sid}" + (f"   ·   used in {', '.join(users[:3])}" + (f" +{len(users) - 3}" if len(users) > 3
                                                                                  else "") if users else "")
            it = QListWidgetItem(text)
            it.setData(ROLE, sid)
            it.setToolTip(f"Sound effect {sid}" + (f"\nused in: {', '.join(users[:12])}" if users else ""))
            self.list.addItem(it)
            self.items.append(it)
            if current is not None and sid == int(current):
                self.list.setCurrentItem(it)
        self.todo = list(self.items)
        self.fill = QTimer(self)
        self.fill.setInterval(0)
        self.fill.timeout.connect(self._fill_some)
        self.fill.start()
        self.list.itemClicked.connect(lambda it: self.play.emit(int(it.data(ROLE))))
        self.list.itemDoubleClicked.connect(lambda it: self.accept())
        self.search.textChanged.connect(self._filter)
        self.only_used.toggled.connect(lambda _: self._filter(self.search.text()))
        self._filter("")
        cur = self.list.currentItem()
        if cur is not None:
            self.list.scrollToItem(cur, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _fill_some(self):
        if not self.todo:
            self.fill.stop()
            return
        vis = self.list.viewport().rect()
        self.todo.sort(key=lambda it: 0 if (not it.isHidden() and self.list.visualItemRect(it).intersects(vis))
                       else 1)
        for it in self.todo[:6]:
            pm, secs = self.thumbs.wave(self.bank, int(it.data(ROLE)))
            it.setIcon(QIcon(pm))
            if secs:
                it.setText(it.text().replace(f"Sound {it.data(ROLE)}", f"Sound {it.data(ROLE)}  ({secs:.2f} s)", 1))
        self.todo = self.todo[6:]

    def _filter(self, text):
        t = text.strip().lower()
        only = self.only_used.isChecked() and bool(self.used_in)
        for it in self.items:
            sid = int(it.data(ROLE))
            hide = only and sid not in self.used_in
            if t and t not in it.text().lower() and t != str(sid):
                hide = True
            it.setHidden(hide)

    def value(self):
        it = self.list.currentItem()
        return int(it.data(ROLE)) if it is not None else None


class CharacterPicker(QDialog):
    """pick a character by its picture (the Scene bar's caster / target): every class and character sprite"""

    def __init__(self, parent, thumbs, chars, current=None, title="Choose a character"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 660)
        self.thumbs = thumbs
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        hint = QLabel("Pictures fill in as you look; type to filter (name, class or sprite number). Double-click picks.")
        hint.setObjectName("muted")
        top.addWidget(hint, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Prinny, Killia, Warrior, 2010 …")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        top.addWidget(self.search)
        lay.addLayout(top)
        size = 80
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setIconSize(QSize(size, size))
        self.list.setGridSize(QSize(size + 44, size + 46))
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.size = size
        blank = QIcon(glyph("…", size, "#171a33", "#555b86"))
        self.items = []
        for label, num in chars:
            it = QListWidgetItem(blank, label)
            it.setData(ROLE, num)
            it.setToolTip(f"{label}  (sprite {num})")
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.list.addItem(it)
            self.items.append(it)
            if current is not None and num == current:
                self.list.setCurrentItem(it)
        self.todo = list(self.items)
        self.list.itemDoubleClicked.connect(lambda it: self.accept())
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.search.textChanged.connect(self._filter)
        self.fill = QTimer(self)
        self.fill.setInterval(0)
        self.fill.timeout.connect(self._fill_some)
        self.fill.start()
        cur = self.list.currentItem()
        if cur is not None:
            self.list.scrollToItem(cur, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _fill_some(self):
        """one picture per turn (the dialog stays responsive), the visible ones first (each sprite is loaded, drawn and
        let go)"""
        if not self.todo:
            self.fill.stop()
            return
        vis = self.list.viewport().rect()
        self.todo.sort(key=lambda it: 0 if (not it.isHidden() and self.list.visualItemRect(it).intersects(vis))
                       else 1)
        it = self.todo.pop(0)
        pm = self.thumbs.char_icon(int(it.data(ROLE)), self.size)
        it.setIcon(QIcon(pm if pm is not None else glyph("?", self.size, "#171a33", "#555b86")))

    def _filter(self, text):
        t = text.strip().lower()
        for it in self.items:
            it.setHidden(bool(t) and t not in it.text().lower() and t != str(it.data(ROLE)))

    def value(self):
        it = self.list.currentItem()
        return int(it.data(ROLE)) if it is not None else None
