"""Weapon Grips: where each character holds its weapon, per animation and frame.  Backend: d5lib/grips.py,
docs/WEAPON_GRIPS.md."""
import math

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem, QPushButton,
                             QLabel, QComboBox, QCheckBox, QSpinBox, QGroupBox, QFormLayout, QMessageBox,
                             QApplication, QToolButton, QSlider)

from d5lib import anm, grips, sprites, database, dbpatch
from ..common import PageHeader, SearchBox, Banner, pil_to_pixmap, error_box

ROLE = Qt.ItemDataRole.UserRole
BOX_MARGIN = 48
NAMES = {1: "Stand", 7: "Stand", 6001: "Idle", 6007: "Idle"}
GRIPS_MOD = "Weapon_Grips"          # mods.create("Weapon Grips") makes this folder


class GripCanvas(QWidget):
    """The frame, zoomed, with the grip markers.  Left drag moves the weapon, right drag turns it about the grip,
    the wheel zooms."""
    moved = pyqtSignal(float, float)        # total drag in sprite pixels since the press
    turned = pyqtSignal(float)              # total turn in degrees since the press
    pressed = pyqtSignal()
    released = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(360, 360)
        self.pm = None
        self.box = (0, 0, 1, 1)
        self.zoom = 3.0
        self.markers = []        # (x, y, colour, selected)
        self.bg = QColor(40, 90, 60)
        self._press = None
        self._button = None
        self.grip = None
        self.fit_box = None      # the part to fit into the view (the render box has a margin to drag into)
        self.auto_fit = True

    def set_frame(self, pm, box, markers, grip):
        self.pm, self.box, self.markers, self.grip = pm, box, markers, grip
        self.update()

    def _origin(self):
        """screen position of the box's top left: the fit box is centred"""
        fx0, fy0, fx1, fy1 = self.fit_box or self.box
        cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
        return self.width() / 2 - (cx - self.box[0]) * self.zoom, self.height() / 2 - (cy - self.box[1]) * self.zoom

    def to_screen(self, x, y):
        ox, oy = self._origin()
        return QPointF(ox + (x - self.box[0]) * self.zoom, oy + (y - self.box[1]) * self.zoom)

    def to_sprite(self, p):
        ox, oy = self._origin()
        return (p.x() - ox) / self.zoom + self.box[0], (p.y() - oy) / self.zoom + self.box[1]

    def fit(self):
        self.auto_fit = True
        x0, y0, x1, y1 = self.fit_box or self.box
        self.zoom = max(1.0, min((self.width() - 24) / max(1, x1 - x0), (self.height() - 24) / max(1, y1 - y0)))
        self.zoom = max(1.0, int(self.zoom * 2) / 2)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.auto_fit:
            self.fit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        if self.pm is None:
            p.setPen(QColor(220, 220, 220))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Pick a character")
            return
        ox, oy = self._origin()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawPixmap(QRectF(ox, oy, self.pm.width() * self.zoom, self.pm.height() * self.zoom), self.pm,
                     QRectF(0, 0, self.pm.width(), self.pm.height()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for x, y, col, sel in self.markers:
            q = self.to_screen(x, y)
            p.setPen(QPen(QColor(*col), 2 if sel else 1))
            r = 7 if sel else 4
            p.drawEllipse(q, r, r)
            if sel:
                p.drawLine(QPointF(q.x() - 12, q.y()), QPointF(q.x() - 8, q.y()))
                p.drawLine(QPointF(q.x() + 8, q.y()), QPointF(q.x() + 12, q.y()))
                p.drawLine(QPointF(q.x(), q.y() - 12), QPointF(q.x(), q.y() - 8))
                p.drawLine(QPointF(q.x(), q.y() + 8), QPointF(q.x(), q.y() + 12))

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton) and self.pm is not None:
            self._press, self._button = e.position(), e.button()
            self.pressed.emit()

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        if self._button == Qt.MouseButton.LeftButton:
            d = e.position() - self._press
            self.moved.emit(d.x() / self.zoom, d.y() / self.zoom)
        elif self.grip is not None:
            g = self.to_screen(*self.grip)
            a0 = math.atan2(self._press.y() - g.y(), self._press.x() - g.x())
            a1 = math.atan2(e.position().y() - g.y(), e.position().x() - g.x())
            self.turned.emit((math.degrees(a1 - a0) + 180) % 360 - 180)

    def mouseReleaseEvent(self, e):
        if self._press is not None:
            self._press = None
            self.released.emit()

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.zoom = min(16.0, max(1.0, self.zoom * f))
        self.auto_fit = False
        self.update()

    def contextMenuEvent(self, e):
        e.accept()


class WeaponGripsPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws, self.main = ws, main
        self.num = None
        self.label = ""
        self.orig = None          # the sprite as installed would get it, before this page's edits
        self.others = {}          # grip edits of the other enabled mods
        self.edits = {}           # this sprite's edits in the target mod (being edited)
        self.mod = None           # target mod
        self.dirty = False
        self.view = None
        self.box = None
        self._drag0 = None
        self._populated = False
        self._play_t = self._t = 0
        self._length = 1

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.addWidget(PageHeader(
            "Weapon Grips",
            "Where each character holds its weapon. Pick a character, an animation and a frame, then drag the weapon "
            "onto the hand (right-drag turns it, arrow keys nudge 1 px, Q / E turn 1°, F flips it, Page Up / Down "
            "change frame). Save keeps it in a mod; Install puts it in the game."))
        split = QSplitter()
        split.setChildrenCollapsible(False)

        # ---------------- left: characters
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.search = SearchBox("Search name, class or number…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        legend = QLabel("★ = sprite made by a mod (every animation editable)\n✎ = has grip edits")
        legend.setObjectName("muted")
        ll.addWidget(legend)
        split.addWidget(left)

        # ---------------- middle: canvas
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.title = QLabel("Pick a character on the left")
        self.title.setObjectName("cardTitle")
        top.addWidget(self.title, 1)
        self.b_play = QToolButton()
        self.b_play.setText("▶")
        self.b_play.setToolTip("Play the animation with your grips")
        self.b_play.clicked.connect(self._toggle_play)
        top.addWidget(self.b_play)
        b = QToolButton()
        b.setText("Fit")
        b.clicked.connect(lambda: self.canvas.fit())
        top.addWidget(b)
        ml.addLayout(top)
        self.banner = Banner()
        self.banner.setVisible(False)
        ml.addWidget(self.banner)
        self.canvas = GripCanvas()
        self.canvas.pressed.connect(self._drag_start)
        self.canvas.moved.connect(self._drag_move)
        self.canvas.turned.connect(self._drag_turn)
        self.canvas.released.connect(self._drag_end)
        self.canvas.keyPressEvent = _canvas_key(self)
        ml.addWidget(self.canvas, 1)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setToolTip("Time (frames at 60 per second); the weapon's frames are listed on the right")
        self.slider.valueChanged.connect(lambda v: self._show(v))
        ml.addWidget(self.slider)
        split.addWidget(mid)

        # ---------------- right: controls
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox("Weapon")
        f = QFormLayout(g)
        self.wtype = QComboBox()
        for nid, (name, num) in grips.WEAPONS.items():
            self.wtype.addItem(name, nid)
        self.wtype.setCurrentIndex(5)
        self.wtype.currentIndexChanged.connect(self._type_changed)
        f.addRow("Type", self.wtype)
        self.model = QComboBox()
        self.model.setToolTip("The weapon drawn in the preview (the game's weapons of this type). Grips apply to every "
                              "weapon of the type; long weapons show best whether the grip looks right.")
        self.model.currentIndexChanged.connect(self._weapon_changed)
        f.addRow("Model", self.model)
        self.hand = QComboBox()
        self.hand.addItem("Main hand (A: nodes 11-16)", "A")
        self.hand.addItem("Second slot (B: nodes 111-116)", "B")
        self.hand.setToolTip("The game draws the equipped (main) weapon on slot A in battle and idle poses. Slot B "
                             "carries it across the body or back in a few motions.")
        self.hand.currentIndexChanged.connect(self._weapon_changed)
        f.addRow("Slot", self.hand)
        self.only_type = QCheckBox("Only this weapon type")
        self.only_type.setToolTip("Off: the move applies to every weapon type held in this hand (recommended).\n"
                                  "On: only the chosen type moves, e.g. a staff a little lower than swords.")
        self.only_type.toggled.connect(self._weapon_changed)
        f.addRow("", self.only_type)
        self.rest = QCheckBox("Hold the weapon when not attacking")
        self.rest.setToolTip("Off (the default for outfits, new characters and new classes): no weapon while the "
                             "unit stands, waits, walks or takes a hit; it appears when the unit attacks or uses a "
                             "skill (their drawings often hold something of their own).\n"
                             "On: the weapon stays in hand throughout, where the grips below place it.\n"
                             "The game's own characters always keep theirs.")
        self.rest.toggled.connect(self._rest_changed)
        f.addRow("At rest", self.rest)
        rl.addWidget(g)

        g = QGroupBox("Animation")
        v = QVBoxLayout(g)
        self.anim = QComboBox()
        self.anim.currentIndexChanged.connect(self._anim_changed)
        v.addWidget(self.anim)
        self.frames = QListWidget()
        self.frames.setMaximumHeight(170)
        self.frames.currentRowChanged.connect(self._frame_changed)
        v.addWidget(self.frames)
        self.anim_note = QLabel("")
        self.anim_note.setObjectName("muted")
        self.anim_note.setWordWrap(True)
        v.addWidget(self.anim_note)
        rl.addWidget(g)

        g = QGroupBox("Grip")
        f = QFormLayout(g)
        self.scope = QComboBox()
        self.scope.addItem("This frame only", "frame")
        self.scope.addItem("Every frame of the animation", "all")
        self.scope.setToolTip("Every frame: one change for the whole animation, added to each frame's own change")
        self.scope.currentIndexChanged.connect(self._refresh_values)
        f.addRow("Change", self.scope)
        self.dx, self.dy, self.rot = QSpinBox(), QSpinBox(), QSpinBox()
        for s, rng in ((self.dx, 300), (self.dy, 300), (self.rot, 360)):
            s.setRange(-rng, rng)
            s.valueChanged.connect(self._values_edited)
        self.dx.setSuffix(" px")
        self.dy.setSuffix(" px")
        self.rot.setSuffix("°")
        f.addRow("Move right", self.dx)
        f.addRow("Move down", self.dy)
        f.addRow("Turn (clockwise)", self.rot)
        self.flip = QCheckBox("Mirror the weapon")
        self.flip.toggled.connect(self._values_edited)
        f.addRow("", self.flip)
        self.show_mode = QComboBox()
        self.show_mode.addItems(["As animated", "Always shown", "Hidden"])
        self.show_mode.setToolTip("Show or hide this weapon for the whole animation")
        self.show_mode.currentIndexChanged.connect(self._show_mode_changed)
        f.addRow("Weapon", self.show_mode)
        self.total = QLabel("")
        self.total.setObjectName("muted")
        f.addRow("This frame in all", self.total)
        rl.addWidget(g)

        row = QHBoxLayout()
        for text, fn, tip in (("Copy to every frame", self.copy_all, "Give every frame this frame's grip change"),
                              ("Reset frame", self.reset_frame, "Remove this frame's change"),
                              ("Reset animation", self.reset_anim, "Remove every change of this animation")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        rl.addLayout(row)
        rl.addStretch(1)
        row = QHBoxLayout()
        self.b_save = QPushButton("💾 Save")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save)
        row.addWidget(self.b_save)
        b = QPushButton("Discard")
        b.clicked.connect(self.discard)
        row.addWidget(b)
        row.addStretch(1)
        rl.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("warn")
        self.status.setWordWrap(True)
        rl.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([240, 640, 340])
        split.setStretchFactor(1, 3)
        lay.addWidget(split, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.redraw = QTimer(self)
        self.redraw.setSingleShot(True)
        self.redraw.timeout.connect(self._render)
        from ..common import Refresher
        ws.mods_changed.connect(Refresher(self, lambda: self._populated and self._populate()))
        self._type_changed()

    # ================================================================== characters
    def on_show(self):
        if not self._populated:
            self._populated = True
            self._populate()

    def hideEvent(self, e):
        self.timer.stop()
        self.b_play.setText("▶")
        super().hideEvent(e)

    def _char_rows(self):
        t = database.load_table("char.dat", self.ws.fs.read(f"{dbpatch.DB_ARCHIVE}/char.dat"))
        mods = self.ws.mods.enabled_mods()
        if self.ws.active_mod and self.ws.active_mod.id not in {m.id for m in mods}:
            mods.append(self.ws.active_mod)
        for mod in mods:
            patch = mod.load_patch("db", "char.dat.json")
            if patch:
                dbpatch.apply_patch(t, patch)
        return t.rows

    def _populate(self):
        self.list.blockSignals(True)
        self.list.clear()
        own, edited, looks = set(), set(), {}
        for mod in self.ws.mods.all_mods():
            for k, v in ((mod.load_patch("outfits", "outfits.json") or {}).get("names") or {}).items():
                looks[int(k)] = v                       # an outfit's name, to tell a character's outfits apart
            for f in mod.list_files():
                name = f.rsplit("/", 1)[-1]
                if f.startswith("Anime/") and name.startswith("anm") and name[3:8].isdigit():
                    own.add(int(name[3:8]))
            edited |= set(grips.sprites_of(mod))
        seen = set()
        items = []
        try:
            rows = self._char_rows()
        except Exception as e:
            rows = []
            self.status.setText(f"char.dat: {e}")
        for r in rows:
            s, name = r["sprite_id"], r["name_EN"]
            if not s or not name or s in seen or r["id"] >= 2000:      # 2000+: monsters, no weapon
                continue
            seen.add(s)
            mark = ("  ★" if s in own else "") + ("  ✎" if s in edited else "")
            title = looks.get(int(r["id"])) or r["title_EN"]
            it = QListWidgetItem(f"{name} — {title}{mark}")
            it.setToolTip(f"class {r['id']} · sprite anm{s:05d}")
            it.setData(ROLE, (s, f"{name} — {title}"))
            items.append((0 if s in own else 1, it))
        for _, it in sorted(items, key=lambda x: x[0]):
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._filter(self.search.text())

    def _filter(self, t):
        t = t.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower() and t not in it.toolTip().lower())

    def _pick(self, it, prev=None):
        if not it:
            return
        num, label = it.data(ROLE)
        if self.dirty and num != self.num:
            r = QMessageBox.question(self, "Unsaved grips", "Save your grip changes first?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                     QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                self.list.blockSignals(True)
                self.list.setCurrentItem(prev)
                self.list.blockSignals(False)
                return
            if r == QMessageBox.StandardButton.Save and self.save() is False:
                return
        self.open_sprite(num, label)

    def unsaved_label(self):
        return self.label

    def open_sprite(self, num, label=""):
        vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            owner = self.ws.owner(vp)
            data = owner.read_file(vp) if owner else self.ws.fs.read(sprites.sprite_vpath(self.ws.fs, num, "EN"))
            self.orig = anm.load(data)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            error_box(self, "Could not open sprite", e)
            return
        QApplication.restoreOverrideCursor()
        self.num, self.label, self.dirty = num, label, False
        # a game sprite's grips go to the mod that already has grips for it, else the 'Weapon Grips' mod
        self.mod = owner or next((m for m in self.ws.mods.enabled_mods()[::-1] if grips.load(m, num)), None) \
            or self.ws.mods.get(GRIPS_MOD)
        self.others = {}
        for mod in self.ws.mods.enabled_mods():
            if not self.mod or mod.id != self.mod.id:
                self.others = grips.merge(self.others, grips.load(mod, num))
        self.edits = grips.load(self.mod, num) if self.mod else {}
        self.owned = owner is not None
        self.idle = grips.idle_weapon(self.mod, num) if self.mod else None
        if self.owned and self.idle is None:            # shown as it installs: kept by sprites set up holding it
            self.idle = grips.holds_at_rest(None, grips.merge(self.others, self.edits))
        self.rest.blockSignals(True)
        self.rest.setChecked(bool(self.idle) if self.owned else True)
        self.rest.setEnabled(self.owned)
        self.rest.blockSignals(False)
        self.title.setText(f"{label}   ·   anm{num:05d}")
        own = sprites.needs_motion_set(self.orig) is False
        if owner:
            text = f"This sprite comes from your mod <b>{owner.name}</b>: the grips are saved there."
        elif self.mod:
            text = f"Game's original sprite: the grips are saved into your mod <b>{self.mod.name}</b>."
        else:
            text = "Game's original sprite: Save puts the grips into a new mod <b>Weapon Grips</b>."
        if not own:
            text += " Only its own idle and special poses can change; its other motions are shared by every " \
                    "humanoid."
        self.banner.show_text(text, False)
        self.anim.blockSignals(True)
        self.anim.clear()
        for aid, bi in grips.weapon_anims(self.orig):
            face = " (front)" if aid % 10 == 1 else " (back)" if aid % 10 == 7 else ""
            self.anim.addItem(f"{NAMES.get(aid, 'Animation')} {aid}{face}", aid)
        self.anim.blockSignals(False)
        idle = self.anim.findData(6001)
        self.anim.setCurrentIndex(idle if idle >= 0 else 0)
        self._anim_changed(self.anim.currentIndex())
        self._update_status()

    # ================================================================== animation / frames
    def _aid(self):
        return self.anim.currentData()

    def _target(self):
        h = self.hand.currentData()
        if self.only_type.isChecked():
            w = self.wtype.currentData()
            return str(w if h == "A" else w + 100)
        return h

    def _node(self):
        w = self.wtype.currentData()
        return w if self.hand.currentData() == "A" else w + 100

    def _times(self):
        if self.orig is None or self._aid() is None:
            return []
        bi, ai = anm._resolve_anim(self.orig, ("id", self._aid()))
        b = self.orig.blocks[bi]
        return grips.key_times(b, b.animations[ai], [self.hand.currentData()])

    def _anim_changed(self, i):
        if i < 0 or self.orig is None:
            return
        aid = self._aid()
        bi, ai = anm._resolve_anim(self.orig, ("id", aid))
        info = anm.animation_info(self.orig.blocks[bi], self.orig.blocks[bi].animations[ai])
        self._length = max(1, info["loop"][1] if info["loop"] else info["length"])
        self._rebuild_view()
        w = self._weapon()
        x0, y0, x1, y1 = grips.anim_bounds(self.view, aid, w, self.wtype.currentData())
        self.box = (x0 - BOX_MARGIN, y0 - BOX_MARGIN, x1 + BOX_MARGIN, y1 + BOX_MARGIN)
        self.canvas.fit_box = (x0, y0, x1, y1)
        self.slider.blockSignals(True)
        self.slider.setRange(0, self._length)
        self.slider.blockSignals(False)
        self._fill_frames()
        note = f"{len(self._times())} frames with a weapon key; frames between them follow the nearest key before."
        if self._hidden_at_rest() and grips.is_rest(aid):
            note = ("Not shown in game: this character holds no weapon while standing, waiting, walking or taking a "
                    "hit (tick 'Hold the weapon when not attacking' above to show it and place it here). ") + note
        self.anim_note.setText(note)
        sm = None
        for target, ks in self.edits.get(str(aid), {}).items():
            if target == self._target() and "show" in ks:
                sm = ks["show"]
        self.show_mode.blockSignals(True)
        self.show_mode.setCurrentIndex(0 if sm is None else 1 if sm else 2)
        self.show_mode.blockSignals(False)
        QTimer.singleShot(0, self.canvas.fit)

    def _fill_frames(self):
        aid = self._aid()
        cur = self.frames.currentRow()
        self.frames.blockSignals(True)
        self.frames.clear()
        tg = self.edits.get(str(aid), {})
        for t in self._times():
            mark = "  ✎" if any(str(t) in ks for ks in tg.values()) else ""
            self.frames.addItem(f"Frame {t}{mark}")
        self.frames.blockSignals(False)
        self.frames.setCurrentRow(min(max(0, cur), self.frames.count() - 1))
        self._frame_changed(self.frames.currentRow())

    def _cur_time(self):
        ts = self._times()
        r = self.frames.currentRow()
        return ts[r] if 0 <= r < len(ts) else 0

    def _frame_changed(self, r):
        self._t = self._cur_time()
        self.slider.blockSignals(True)
        self.slider.setValue(self._t)
        self.slider.blockSignals(False)
        self._refresh_values()

    def _type_changed(self, *_):
        self.model.blockSignals(True)
        self.model.clear()
        for num, names in grips.weapon_models(self.ws.fs, self.wtype.currentData()):
            self.model.addItem(f"{names[0]}{' …' if len(names) > 1 else ''}  ·  anm{num:05d}", num)
            self.model.setItemData(self.model.count() - 1, ", ".join(names), Qt.ItemDataRole.ToolTipRole)
        self.model.blockSignals(False)
        self._weapon_changed()

    def _weapon(self):
        return grips.weapon_sprite(self.ws.fs, self.wtype.currentData(), self.model.currentData())

    def _weapon_changed(self, *_):
        if self.orig is not None:
            self._anim_changed(self.anim.currentIndex())     # frames, view box and show / hide of that weapon

    # ================================================================== values
    def _key(self):
        return "*" if (self.scope.currentData() == "all") else str(self._cur_time())

    def _entry(self):
        v = self.edits.get(str(self._aid()), {}).get(self._target(), {}).get(self._key())
        return list(grips._entry(v)) if v else [0.0, 0.0, 0.0, 0]

    def _refresh_values(self, *_):
        dx, dy, rot, flip = self._entry()
        for w, val in ((self.dx, dx), (self.dy, dy), (self.rot, rot)):
            w.blockSignals(True)
            w.setValue(int(round(val)))
            w.blockSignals(False)
        self.flip.blockSignals(True)
        self.flip.setChecked(bool(flip))
        self.flip.blockSignals(False)
        self._update_total()
        self._render()

    def _update_total(self):
        tg = self.edits.get(str(self._aid()), {})
        t = grips.offset_of(tg, self._node(), self._cur_time()) if self._aid() is not None else grips.ZERO
        self.total.setText(f"{t[0]:+.0f}, {t[1]:+.0f} px, {t[2]:+.0f}°{', mirrored' if t[3] else ''}")

    def _set_entry(self, dx, dy, rot, flip):
        aid, target, key = str(self._aid()), self._target(), self._key()
        ks = self.edits.setdefault(aid, {}).setdefault(target, {})
        v = [int(round(dx)), int(round(dy)), int(round(rot))] + ([1] if flip else [])
        if v[:3] == [0, 0, 0] and not flip:
            ks.pop(key, None)
        else:
            ks[key] = v
        self._mark_dirty()
        self._update_total()

    def _values_edited(self, *_):
        if self.orig is None:
            return
        self._set_entry(self.dx.value(), self.dy.value(), self.rot.value(), self.flip.isChecked())
        self._schedule()

    def _show_mode_changed(self, i):
        if self.orig is None:
            return
        ks = self.edits.setdefault(str(self._aid()), {}).setdefault(self._target(), {})
        if i == 0:
            ks.pop("show", None)
        else:
            ks["show"] = i == 1
        self._mark_dirty()
        self._schedule()

    def _hidden_at_rest(self):
        return bool(getattr(self, "owned", False)) and not self.rest.isChecked()

    def _rest_changed(self, on):
        if self.orig is None or not getattr(self, "owned", False):
            return
        self.idle = bool(on)
        self._mark_dirty()
        self._anim_changed(self.anim.currentIndex())
        self._schedule()

    def _mark_dirty(self):
        self.dirty = True
        self._rebuild_view()
        self._update_status()

    def _update_status(self):
        self.status.setText("● unsaved changes" if self.dirty else "")
        self.b_save.setEnabled(self.orig is not None)

    # ================================================================== drag / keys
    def _drag_start(self):
        self._drag0 = self._entry()

    def _drag_move(self, dx, dy):
        if self._drag0 is None:
            return
        v = self._drag0
        self._apply_values(v[0] + dx, v[1] + dy, v[2], v[3])

    def _drag_turn(self, deg):
        if self._drag0 is None:
            return
        v = self._drag0
        self._apply_values(v[0], v[1], v[2] + deg, v[3])

    def _drag_end(self):
        self._drag0 = None
        self._fill_marks()

    def _apply_values(self, dx, dy, rot, flip):
        for w, val in ((self.dx, dx), (self.dy, dy), (self.rot, rot)):
            w.blockSignals(True)
            w.setValue(int(round(val)))
            w.blockSignals(False)
        self._set_entry(dx, dy, rot, flip)
        self._schedule()

    def _fill_marks(self):
        tg = self.edits.get(str(self._aid()), {})
        for i, t in enumerate(self._times()):
            it = self.frames.item(i)
            if it:
                it.setText(f"Frame {t}" + ("  ✎" if any(str(t) in ks for ks in tg.values()) else ""))
        self._refresh_values()

    def _schedule(self):
        self.redraw.start(15)

    # ================================================================== render
    def _rebuild_view(self):
        if self.orig is not None:
            self.view = grips.edited_copy(self.orig, grips.merge(self.others, self.edits))
            if self._hidden_at_rest():
                grips.hide_at_rest(self.view)            # as the game will show it (attacks and skills keep theirs)

    def _show(self, t):
        """slider: show time t and select the weapon key in effect then (the one an edit changes)"""
        self._play_t = self._t = t
        ts = self._times()
        r = max([i for i, k in enumerate(ts) if k <= t] or [0])
        if ts and r != self.frames.currentRow():
            self.frames.blockSignals(True)
            self.frames.setCurrentRow(r)
            self.frames.blockSignals(False)
        self._refresh_values()

    def _render(self, t=None):
        if self.view is None or self._aid() is None or self.box is None:
            return
        t = self._t if t is None else t
        w = self._weapon()
        g = []
        try:
            items = grips.evaluate(self.view, self._aid(), t, w, self.wtype.currentData(),
                                   (self.hand.currentData(),), grips=g)
            img = grips.render(items, self.box, 1, char=self.view)
        except Exception as e:
            self.status.setText(f"render error: {e}")
            return
        marks, grip = [], None
        for nid, grp, (x, y), shown, m in g:
            sel = nid == self._node()
            col = (255, 230, 0) if grp == "A" else (0, 230, 255)
            marks.append((x, y, col if shown else (150, 150, 150), sel))
            if sel:
                grip = (x, y)
        self.canvas.set_frame(pil_to_pixmap(img), self.box, marks, grip)

    def _toggle_play(self):
        if self.timer.isActive():
            self.timer.stop()
            self.b_play.setText("▶")
            self._show(self._play_t)
        else:
            self._play_t = self._cur_time()
            self.timer.start(33)
            self.b_play.setText("⏸")

    def _tick(self):
        self._play_t = (self._play_t + 2) % (self._length + 1)
        self.slider.blockSignals(True)
        self.slider.setValue(self._play_t)
        self.slider.blockSignals(False)
        self._render(self._play_t)

    # ================================================================== buttons
    def copy_all(self):
        if self.orig is None:
            return
        v = self._entry()
        if (self.scope.currentData() == "all"):
            return
        for t in self._times():
            ks = self.edits.setdefault(str(self._aid()), {}).setdefault(self._target(), {})
            ks[str(t)] = [int(round(v[0])), int(round(v[1])), int(round(v[2]))] + ([1] if v[3] else [])
        self._mark_dirty()
        self._fill_marks()

    def reset_frame(self):
        if self.orig is None:
            return
        self._set_entry(0, 0, 0, 0)
        self._fill_marks()

    def reset_anim(self):
        if self.orig is None:
            return
        self.edits.pop(str(self._aid()), None)
        self.show_mode.blockSignals(True)
        self.show_mode.setCurrentIndex(0)
        self.show_mode.blockSignals(False)
        self._mark_dirty()
        self._fill_marks()

    def save(self):
        if self.orig is None:
            return
        if self.mod is None:
            self.mod = self.ws.mods.create("Weapon Grips", "D5 Mod Kit",
                                           "Where the game's own characters hold their weapons (Weapon Grips page).")
            self.ws.mods_changed.emit()
        grips.save(self.mod, self.num, self.edits, idle=self.idle if getattr(self, "owned", False) else ...)
        self.dirty = False
        self._update_status()
        self.status.setText(f"Saved into {self.mod.name}. Install to see it in game.")
        self.ws.log(f"Weapon grips of anm{self.num:05d} saved into {self.mod.name}")
        self._populate_marks()
        return True

    def _populate_marks(self):
        cur = self.list.currentItem()
        if cur and self.edits and "✎" not in cur.text():
            cur.setText(cur.text() + "  ✎")

    def discard(self):
        if self.num is not None:
            self.dirty = False
            self.open_sprite(self.num, self.label)


def _canvas_key(page):
    def handler(e):
        k, mod = e.key(), e.modifiers()
        step = 5 if mod & Qt.KeyboardModifier.ShiftModifier else 1
        v = page._entry()
        moves = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0), Qt.Key.Key_Up: (0, -step),
                 Qt.Key.Key_Down: (0, step)}
        if page.orig is None:
            return
        if k in moves:
            page._apply_values(v[0] + moves[k][0], v[1] + moves[k][1], v[2], v[3])
            page._fill_marks()
        elif k in (Qt.Key.Key_Q, Qt.Key.Key_E):
            page._apply_values(v[0], v[1], v[2] + (-step if k == Qt.Key.Key_Q else step), v[3])
            page._fill_marks()
        elif k == Qt.Key.Key_F:
            page._apply_values(v[0], v[1], v[2], 0 if v[3] else 1)
            page.flip.blockSignals(True)
            page.flip.setChecked(not v[3])
            page.flip.blockSignals(False)
            page._fill_marks()
        elif k in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            n = page.frames.count()
            if n:
                page.frames.setCurrentRow((page.frames.currentRow() + (1 if k == Qt.Key.Key_PageDown else -1)) % n)
    return handler
