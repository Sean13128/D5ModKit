"""Properties of what is selected (works like Blender's properties editor).

Every kind of thing shows the same layout: a header (picture, name, what it is, the main actions) and folding
panels with one property per row — a short label on the left, the control on the right, and a line of help under
the ones that need it.  Panels remember whether they are open.

An effect:  Transform (attached to, position, size, turn) · Timing (appears, disappears, its animation) ·
Drawing (draw order, nearer the camera, faces the camera, blending) · Motion · Turning · Colour & fade · Script
values.  A pose: its animation playing, who, when.  A sound: hear it, pick another by ear.  Anything else: its values
in words."""
import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QScrollArea, QPushButton,
                             QComboBox, QFrame, QSlider, QToolButton, QDialog, QDialogButtonBox, QGridLayout,
                             QCheckBox, QSizePolicy)

from d5lib import choreo, fxtools

ACTORS = [("Caster", choreo.CASTER), ("Target", choreo.TARGET)]
PLAYS = [("plays once", 1), ("loops", -1), ("plays twice", 2), ("plays 3 times", 3)]
# draw queues an effect can be put in (cmd_3cde; the game draws queue 0 first, sorts queue 6 back to front)
DRAW_ORDER = [("The model's own", None),
              ("Behind the units", 4),
              ("Behind the units, over the ground pictures", 5),
              ("With the units (nearer covers farther)", 6),
              ("In front of the units", 7)]
QUEUE_WORDS = {2: "behind the units", 3: "behind the units", 4: "behind the units", 5: "behind the units",
               6: "with the units", 7: "in front of the units", 8: "in front of the units"}
BLENDS = [("The model's own", None), ("Normal", 1), ("Adds light (glow)", 2), ("Takes light away", 3),
          ("Multiplies (tints / darkens what is behind)", 4), ("Its colour minus what is behind", 5)]
OPEN = {}                                   # panel title -> open (remembered while the kit runs)
CLOSED_AT_FIRST = {"Script values", "Turning", "Colour & fade"}


class EffectPicker(QDialog):
    """the effect library in a dialog: double-click (or OK) picks"""

    def __init__(self, parent, fx, names, current=None):
        super().__init__(parent)
        from .library import EffectLibrary
        self.setWindowTitle("Choose a picture")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        self.lib = EffectLibrary(fx, names)
        self.lib.fill(sorted(set(list(names.custom) + [int(k) for k in _vanilla_ids()])))
        if current is not None:
            self.lib.select(current)
        self.lib.picked.connect(lambda e: self.accept())
        lay.addWidget(self.lib, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def value(self):
        it = self.lib.list.currentItem()
        return int(it.data(Qt.ItemDataRole.UserRole)) if it else None


def _vanilla_ids():
    from d5lib import fxnames
    return list(fxnames.vanilla())


class Panel(QFrame):
    """a folding panel: header button + rows of (label | control) with optional help lines"""

    def __init__(self, title, icon="", count=None):
        super().__init__()
        self.setObjectName("propPanel")
        self.setStyleSheet("#propPanel { background: #1d1a28; border: 1px solid #2f2a42; border-radius: 6px; }")
        self.title = title
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.head = QPushButton()
        self.head.setCheckable(True)
        self.head.setFlat(True)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.head.setStyleSheet("QPushButton { text-align: left; padding: 6px 10px; border: none; "
                                "background: #26223a; color: #f2eff9; font-weight: 600; border-radius: 6px; }"
                                "QPushButton:hover { background: #2e2946; } QPushButton:checked { background: #26223a; }")
        self._label = (f"{icon}  {title}" if icon else title).replace("&", "&&")   # '&' would be a shortcut
        if count is not None:
            self._label += f"   ({count})"
        v.addWidget(self.head)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(10, 6, 10, 8)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(5)
        self.grid.setColumnStretch(1, 1)
        v.addWidget(self.body)
        self.rows = 0
        on = OPEN.get(title, title not in CLOSED_AT_FIRST)
        self.head.setChecked(on)
        self._set(on)
        self.head.toggled.connect(self._set)

    def _set(self, on):
        OPEN[self.title] = on
        self.body.setVisible(on)
        self.head.setText(("▾  " if on else "▸  ") + self._label)

    def row(self, label, widget, help=None, tip=None):
        lab = QLabel(label)
        lab.setStyleSheet("color: #a9a4bd;")
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lab.setMinimumWidth(84)
        if tip:
            lab.setToolTip(tip)
            widget.setToolTip(widget.toolTip() or tip)
        self.grid.addWidget(lab, self.rows, 0)
        self.grid.addWidget(widget, self.rows, 1)
        self.rows += 1
        if help:
            h = QLabel(help)
            h.setWordWrap(True)
            h.setStyleSheet("color: #7f7a96; font-size: 8.5pt;")
            self.grid.addWidget(h, self.rows, 1)
            self.rows += 1
        return widget

    def full(self, widget):
        self.grid.addWidget(widget, self.rows, 0, 1, 2)
        self.rows += 1
        return widget

    def note(self, text):
        h = QLabel(text)
        h.setWordWrap(True)
        h.setStyleSheet("color: #8e89a6;")
        return self.full(h)


def _hbox(*widgets, stretch_last=False):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    for k, x in enumerate(widgets):
        if isinstance(x, str):
            l = QLabel(x)
            l.setStyleSheet("color: #8e89a6;")
            h.addWidget(l)
        else:
            h.addWidget(x, 1 if (stretch_last and k == len(widgets) - 1) else 0)
    if not stretch_last:
        h.addStretch(1)
    return w


class PropertiesPanel(QScrollArea):
    valueEdited = pyqtSignal(object, int, int)       # op, operand index, value
    retime = pyqtSignal(object, int)                 # selection, new start frame
    libraryRequested = pyqtSignal(object)            # (kept for the editor; unused here)
    trimTo = pyqtSignal(object, int)                 # clip item, new end frame
    deleteOps = pyqtSignal(list)                     # ops to remove
    moveClipBy = pyqtSignal(object, object)          # clip item, (dx, dy, dz)
    pickEffect = pyqtSignal(object)                  # load op: choose another picture
    playSound = pyqtSignal(object)                   # op
    actionRequested = pyqtSignal(str)                # 'delete' | 'duplicate' | 'arrange' | 'frame'
    putAtShow = pyqtSignal(object, list, str, object)  # show op, its existing ops, command, args (None: remove)
    pickPose = pyqtSignal(object)                    # pose op: choose another pose by its picture
    pickSound = pyqtSignal(object)                   # sound op: choose another sound by ear

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(10, 10, 10, 10)
        self.lay.setSpacing(8)
        self.setWidget(self.body)
        self.sel = None
        self.idents = None
        self.pending = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._commit)
        self.anim = QTimer(self)                     # the pose picture plays
        self.anim.setInterval(110)
        self.anim.timeout.connect(self._anim_step)
        self._anim = None                            # (label, [pixmaps], i)
        self.motions = []
        self.names = None
        self.thumb = None               # callable(effect id) -> QPixmap
        self.thumbs = None              # thumbs.Thumbs (poses, sounds)
        self.sprite_of = None           # callable(actor) -> sprite number shown for it
        self.model_queues = None        # callable(effect id) -> set of the draw queues its parts use
        self.sound_bank = None
        self.editable = lambda op, i: True
        self.multi = []
        self.show_item(None)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.body.setMaximumWidth(self.viewport().width())          # never wider than the column

    # ---------------------------------------------------------------- building blocks
    def _clear(self):
        self.anim.stop()
        self._anim = None

        def clear(lay):
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
                elif it.layout() is not None:
                    clear(it.layout())
        clear(self.lay)

    def _panel(self, title, icon="", count=None):
        p = Panel(title, icon, count)
        self.lay.addWidget(p)
        return p

    def _spin(self, op, i, lo=-32768, hi=32767, scale=1, suffix="", tip=None, now=False, width=None):
        sb = QSpinBox()
        sb.setRange(lo, hi)
        try:
            sb.setValue(int(round(op.args[i] / scale)))
        except (TypeError, ValueError, IndexError):
            pass
        if suffix:
            sb.setSuffix(f" {suffix}")
        if width:
            sb.setMaximumWidth(width)
        sb.setKeyboardTracking(False)
        ok = self.editable(op, i)
        sb.setEnabled(ok)
        sb.setToolTip(tip if ok else "This value is fixed inside a shared game helper (not part of this skill).")
        sb.valueChanged.connect(lambda v, op=op, i=i: self._queue(op, i, int(round(v * scale)), now))
        return sb

    def _actor_combo(self, op, i):
        cb = QComboBox()
        cur = choreo.actor_id(op.args[i])
        for label, a in ACTORS:
            cb.addItem(label, a)
            pm = self._actor_icon(a)
            if pm is not None:
                cb.setItemIcon(cb.count() - 1, pm)
        if cur not in (choreo.CASTER, choreo.TARGET):
            cb.addItem(choreo.who(op.args[i]) if hasattr(choreo, "who") else f"Actor {op.args[i]}", op.args[i])
        cb.setCurrentIndex(max(0, cb.findData(cur if cur in (choreo.CASTER, choreo.TARGET) else op.args[i])))
        cb.setEnabled(self.editable(op, i))
        cb.currentIndexChanged.connect(lambda k: self._queue(op, i, int(cb.itemData(k)), now=True))
        return cb

    def _actor_icon(self, a):
        if self.thumbs is None or self.sprite_of is None:
            return None
        try:
            num = self.sprite_of(a)
            pm = self.thumbs.pose_icon(num, 0, size=40) if num else None
        except Exception:
            pm = None
        from PyQt6.QtGui import QIcon
        return QIcon(pm) if pm is not None else None

    def _list(self, p, entries, empty):
        """entries: [(text, ops)]; each gets a ✖ remove button"""
        if not entries:
            p.note(empty)
            return
        for text, ops in entries:
            l = QLabel(text)
            l.setWordWrap(True)
            b = QToolButton()
            b.setText("✖")
            b.setToolTip("Remove this")
            b.clicked.connect(lambda _, ops=ops: self.deleteOps.emit(list(ops)))
            p.full(self._line(l, b))

    @staticmethod
    def _line(label, button):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(label, 1)
        h.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        return w

    def _advanced(self, ops):
        """every raw value of the ops (a folded panel)"""
        p = self._panel("Script values", "⚙")
        p.note("The commands exactly as the script has them (for what the panels above don't cover).")
        for op in ops:
            t = QLabel(f"<b>frame {op.frame}</b> · {fxtools.describe(op, self.names)}"
                       f"<span style='color:#8e89a6'>  ({op.name})</span>")
            t.setWordWrap(True)
            p.full(t)
            for i, n in enumerate(choreo.arg_names(op.cid)):
                if i >= len(op.args) or isinstance(op.args[i], bytes):
                    continue
                p.row(n.replace("_", " "), self._spin(op, i))

    def _header(self, title, sub, pix=None, actions=()):
        box = QFrame()
        box.setObjectName("propHead")
        box.setStyleSheet("#propHead { background: #211d2e; border: 1px solid #3a3553; border-radius: 8px; }")
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 8, 10, 8)
        row = QHBoxLayout()
        img = None
        if pix is not None:
            img = QLabel()
            img.setFixedSize(76, 76)
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setPixmap(pix.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
            img.setStyleSheet("background: #15131c; border: 1px solid #3a3553; border-radius: 6px;")
            row.addWidget(img)
        col = QVBoxLayout()
        t = QLabel(title)
        t.setStyleSheet("font-size: 11pt; font-weight: 700; color: #f2eff9;")
        t.setWordWrap(True)
        col.addWidget(t)
        s = QLabel(sub)
        s.setStyleSheet("color: #9a95b0;")
        s.setWordWrap(True)
        col.addWidget(s)
        col.addStretch(1)
        row.addLayout(col, 1)
        v.addLayout(row)
        if actions:
            ar = QHBoxLayout()
            ar.setSpacing(4)
            for text, fn, tip, enabled in actions:
                b = QToolButton()
                b.setText(text)
                b.setToolTip(tip)
                b.setEnabled(enabled)
                b.clicked.connect(fn)
                ar.addWidget(b)
            ar.addStretch(1)
            v.addLayout(ar)
        self.lay.addWidget(box)
        return img

    # ---------------------------------------------------------------- show
    @staticmethod
    def _ops(sel):
        if sel is None:
            return []
        if isinstance(sel, tuple):
            return [sel[2]]
        return list(sel.ops)

    def show_item(self, sel, multi=None):
        multi = [m for m in (multi or []) if not isinstance(m, tuple)]
        ops = self._ops(sel)
        idents = [o.ident for o in ops] + [("n", len(multi))] + [tuple(map(str, o.args)) for o in ops]
        if idents == self.idents:
            self.sel = sel
            return
        f = self.body.focusWidget() if self.body.isAncestorOf(self.focusWidget() or self) else None
        if f is not None and isinstance(f, QSpinBox) and self.idents and idents[:len(ops)] == self.idents[:len(ops)]:
            self.sel = sel                     # the user is typing in a box: keep it (values refresh afterwards)
            return
        keep = self.verticalScrollBar().value()
        self.sel, self.idents, self.multi = sel, idents, multi
        self._clear()
        if len(multi) > 1:
            self._many(multi)
        elif sel is None:
            self._nothing()
        elif isinstance(sel, tuple):
            self._command(sel[2], sel)
        elif sel.kind == "clip":
            self._effect(sel)
        elif sel.kind == "motion":
            self._pose(sel)
        elif sel.ops and sel.ops[0].cid in choreo.SOUND_CMDS:
            self._sound(sel.ops[0], sel)
        else:
            self._command(sel.ops[0], sel)
        self.lay.addStretch(1)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(keep))

    def _nothing(self):
        self._header("Nothing selected", "Click something in the preview or on the timeline to see it here.")
        p = self._panel("How to", "💡")
        for t in ("Click an effect in the preview (or a clip on the timeline): its properties show here, in panels.",
                  "Preview: drag a selected effect to move it, or use Move / Rotate / Scale at the top left (keys "
                  "G, R, S). Shift+click or drag a box to select several.",
                  "Timeline: drag a clip to move it in time, drag its right edge to change when it ends; "
                  "right-click for poses, sounds, camera moves and presets.",
                  "An effect drawn over a character when it should be under it: Drawing → Draw order."):
            p.note("• " + t)

    def _many(self, items):
        clips = [it for it in items if it.kind == "clip"]
        names = {}
        for it in clips:
            names[it.label] = names.get(it.label, 0) + 1
        self._header(f"{len(items)} things selected",
                     ", ".join(f"{n} ×{c}" if c > 1 else n for n, c in names.items()) or "",
                     actions=[("🗑 Delete", lambda: self.actionRequested.emit("delete"), "Delete them (Del)", True),
                              ("⧉ Duplicate", lambda: self.actionRequested.emit("duplicate"), "Copies (Shift+D)",
                               True),
                              ("🎯 Group & paths", lambda: self.actionRequested.emit("arrange"),
                               "Spacing, shapes and flight paths for all of them", True),
                              ("⌖ Frame", lambda: self.actionRequested.emit("frame"), "Zoom onto them (F)", True)])
        p = self._panel("Together", "👥")
        p.note("Move, rotate or scale them together in the preview (tools at the top left, or G / R / S); on the "
               "timeline drag one of them to move them all in time.")

    # ---------------------------------------------------------------- an effect
    def _effect(self, it):
        load = next((o for o in it.ops if o.cid == 0x3c00), None)
        show = next((o for o in it.ops if o.cid in choreo.SHOW_CMDS), None)
        e = it.effect
        names = self.names
        cat = names.cat_name(e) if names is not None and e is not None else ""
        used = names.used(e)[:3] if names is not None and e is not None else []
        pix = self.thumb(e) if self.thumb and e is not None else None
        sub = f"{cat} · effect {e} · slot {it.slot}" + (f"\nalso in: {', '.join(used)}" if used else "")
        acts = [("🖼 Picture…", lambda: self.pickEffect.emit(load), "Choose another picture for this effect",
                 load is not None and self.editable(load, 1)),
                ("⧉ Copy", lambda: self.actionRequested.emit("duplicate"), "A copy of it (Shift+D)", True),
                ("🗑 Delete", lambda: self.actionRequested.emit("delete"), "Remove this effect (Del)", True),
                ("⌖ Frame", lambda: self.actionRequested.emit("frame"), "Zoom the preview onto it (F)", True)]
        self._header(it.label, sub, pix, acts)

        # -- Transform
        if show is not None:
            p = self._panel("Transform", "✥")
            p.row("Attached to", self._actor_combo(show, 1),
                  tip="Whose place it is shown at (it follows that character when the show command attaches it)")
            self.pos_boxes = []
            boxes = []
            for k, (lab, tip) in enumerate((("X", "sideways (120 = one panel)"), ("Y", "height above the ground"),
                                            ("Z", "forward (120 = one panel)"))):
                sb = QSpinBox()
                sb.setRange(-30000, 30000)
                sb.setMinimumWidth(56)
                sb.setMaximumWidth(92)
                sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                sb.setValue(int(show.args[2 + k]))
                sb.setKeyboardTracking(False)
                sb.setPrefix(f"{lab} ")
                sb.setToolTip(f"{lab}: {tip}. Moving the effect moves its whole path with it.")
                sb.setEnabled(self.editable(show, 2 + k))
                sb.valueChanged.connect(lambda val, k=k: self._moved(it, show, k, val))
                boxes.append(sb)
                self.pos_boxes.append(sb)
            p.row("Position", _hbox(*boxes), "From that character's feet: X sideways, Y up, Z forward "
                                             "(120 = one panel). Its whole path moves with it.")
            size = QWidget()
            sh = QHBoxLayout(size)
            sh.setContentsMargins(0, 0, 0, 0)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(1, 600)
            cur = max(1, int(round(show.args[5] / 10))) if show.args[5] else 100
            sl.setValue(min(600, cur))
            sb = QSpinBox()
            sb.setRange(1, 3000)
            sb.setMaximumWidth(84)
            sb.setSuffix(" %")
            sb.setValue(cur)
            sb.setKeyboardTracking(False)
            ok = self.editable(show, 5)
            sl.setEnabled(ok)
            sb.setEnabled(ok)
            sl.valueChanged.connect(lambda v: sb.setValue(v))
            sl.sliderReleased.connect(lambda: self._size(show, sb.value(), now=True))
            sb.valueChanged.connect(lambda v: (sl.blockSignals(True), sl.setValue(min(600, v)), sl.blockSignals(False),
                                               None if sl.isSliderDown() else self._size(show, v)))
            sh.addWidget(sl, 1)
            sh.addWidget(sb)
            p.row("Size", size, tip="How big it is (100 % = the picture's own size)")
            rot = fxtools.at_show(it.ops, show, 0x3c64)
            cur_r = [int(rot[0].args[k]) for k in (2, 3, 4)] if rot and len(rot[0].args) > 4 else [0, 0, 0]
            rboxes = []
            for k, lab in enumerate("XYZ"):
                rb = QSpinBox()
                rb.setRange(-3600, 3600)
                rb.setMaximumWidth(84)
                rb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                rb.setPrefix(f"{lab} ")
                rb.setSuffix("°")
                rb.setValue(cur_r[k])
                rb.setKeyboardTracking(False)
                rboxes.append(rb)
            for rb in rboxes:
                rb.valueChanged.connect(lambda _v, rot=rot: self._put(
                    show, rot, "cmd_3c64", [int(show.args[0]), 0] + [b.value() for b in rboxes]))
            p.row("Turn", _hbox(*rboxes), "Its picture's own turn when it appears (X tips it forward, Y turns "
                                         "it round, Z spins it flat). Turns later on are under Turning.")

        # -- Timing
        p = self._panel("Timing", "⏱")
        s0 = QSpinBox()
        s0.setRange(0, 9999)
        s0.setValue(it.start)
        s0.setPrefix("frame ")
        s0.setKeyboardTracking(False)
        s0.valueChanged.connect(lambda v: self.retime.emit(self.sel, v))
        p.row("Appears", _hbox(s0, f"{it.start / 60:.2f} s"), tip="When it appears (moves the whole effect in time)")
        if it.removable_end:
            s1 = QSpinBox()
            s1.setRange(it.start + 1, 99999)
            s1.setValue(it.end)
            s1.setPrefix("frame ")
            s1.setKeyboardTracking(False)
            s1.valueChanged.connect(lambda v: self.trimTo.emit(it, v))
            p.row("Disappears", _hbox(s1, f"on screen {it.end - it.start} frames"),
                  tip="When it is taken off the screen (or drag the clip's right edge on the timeline)")
        else:
            p.row("Disappears", QLabel(f"when its animation ends (frame {it.end})"))
        if show is not None and show.cid in (0x3c10, 0x3c20) and len(show.args) > 7:
            cb = QComboBox()
            for label, val in PLAYS:
                cb.addItem(label, val)
            cur = show.args[7]
            cur = 1 if cur == 0 else cur
            if cb.findData(cur) < 0:
                cb.addItem(f"plays {cur} times", cur)
            cb.setCurrentIndex(cb.findData(cur))
            cb.setEnabled(self.editable(show, 7))
            cb.currentIndexChanged.connect(lambda k: self._queue(show, 7, int(cb.itemData(k)), True))
            p.row("Animation", cb, tip="How often the effect's own animation runs before it disappears "
                                       "(loops: until it is taken off)")
        if show is not None and len(show.args) > 6:
            p.row("Speed", self._spin(show, 6, -5000, 5000, scale=10, suffix="%", width=110,
                                      tip="How fast its own animation plays: 100 % = normal, 0 = holds its "
                                          "first picture, minus = backwards"),
                  "100 % = as made; 0 holds the first picture; minus plays it backwards.")

        # -- Drawing
        if show is not None:
            self._drawing(it, show)

        # -- Motion / Turning / Colour
        moves = fxtools.move_groups(it.ops)
        p = self._panel("Motion", "➶", len(moves))
        self._list(p, [(f"frame {a}–{b}: {t}", ops) for a, b, ops, t in moves],
                   "It stays where it is shown. (🎯 Group & paths gives it a flight path.)")
        turns = [o for o in it.ops if o.cid in fxtools.TURN_CMDS and not (show is not None and o.cid == 0x3c64 and
                                                                          o.frame == show.frame)]
        p = self._panel("Turning", "⟳", len(turns))
        self._list(p, [(f"frame {o.frame}: {fxtools.describe(o)}", [o]) for o in turns],
                   "It doesn't turn while it is on screen. (The Rotate tool with pivot 'Each its own' turns it.)")
        looks = [o for o in it.ops if o.cid in fxtools.LOOK_CMDS and o.cid not in (0x3ca0, 0x3cde, 0x3ca5, 0x3cd6)]
        p = self._panel("Colour & fade", "🎨", len(looks))
        self._list(p, [(f"frame {o.frame}: {fxtools.describe(o)}", [o]) for o in looks], "No colour changes.")
        self._advanced([o for o in it.ops])

    def _drawing(self, it, show):
        """draw order (cmd_3cde), nearer the camera (3ca0), facing the camera (3ca5), blending (3cd6)"""
        p = self._panel("Drawing", "◧")
        slot = int(show.args[0])
        ok = self.editable(show, 0)
        q_ops = fxtools.at_show(it.ops, show, 0x3cde)
        own = self.model_queues(it.effect) if self.model_queues and it.effect is not None else set()
        own_txt = " / ".join(sorted({QUEUE_WORDS.get(q, f"queue {q}") for q in own})) or "with the units"
        cb = QComboBox()
        for label, q in DRAW_ORDER:
            cb.addItem(f"{label}  ({own_txt})" if q is None else label, q)
        cur = int(q_ops[0].args[1]) if q_ops and len(q_ops[0].args) > 1 else None
        if cur is not None and cb.findData(cur) < 0:
            cb.addItem(f"Queue {cur}", cur)
        cb.setCurrentIndex(max(0, cb.findData(cur)))
        cb.setEnabled(ok)
        cb.currentIndexChanged.connect(lambda k: self._put(
            show, q_ops, "cmd_3cde", None if cb.itemData(k) is None else [slot, int(cb.itemData(k))]))
        p.row("Draw order", cb,
              "Behind the units: under every character (a circle on the ground). With the units: what is nearer "
              "the camera covers what is farther. In front: over every unit. (cmd_3cde, as in the game.)")
        z_ops = fxtools.at_show(it.ops, show, 0x3ca0)
        zb = QSpinBox()
        zb.setRange(0, 4000)
        zb.setSingleStep(20)
        zb.setMaximumWidth(110)
        zb.setValue(int(z_ops[0].args[1]) if z_ops and len(z_ops[0].args) > 1 else 0)
        zb.setKeyboardTracking(False)
        zb.setEnabled(ok)
        zb.valueChanged.connect(lambda v: self._put(show, z_ops, "cmd_3ca0", [slot, int(v)] if v else None))
        p.row("Nearer camera", _hbox(zb, f"= {zb.value() / 20:.0f} map units" if zb.value() else "off"),
              "Draws it this much nearer the camera (20 = one map unit) so it sits over the ground or a unit "
              "right behind it instead of cutting into them. Most game effects use 100–1000.")
        b_ops = fxtools.at_show(it.ops, show, 0x3ca5)
        fc = QCheckBox("Turns to face the camera")
        fc.setChecked(not (b_ops and len(b_ops[0].args) > 1 and b_ops[0].args[1]))
        fc.setEnabled(ok)
        fc.toggled.connect(lambda on: self._put(show, b_ops, "cmd_3ca5", None if on else [slot, 1]))
        p.row("Facing", fc, "Parts made to face the camera (flat flashes, sparkles) do so; untick to keep them "
                            "as placed (cmd_3ca5).")
        l_ops = fxtools.at_show(it.ops, show, 0x3cd6)
        bl = QComboBox()
        for label, v in BLENDS:
            bl.addItem(label, v)
        curb = int(l_ops[0].args[1]) if l_ops and len(l_ops[0].args) > 1 else None
        if curb is not None and bl.findData(curb) < 0:
            bl.addItem(f"Mode {curb}", curb)
        bl.setCurrentIndex(max(0, bl.findData(curb)))
        bl.setEnabled(ok)
        bl.currentIndexChanged.connect(lambda k: self._put(
            show, l_ops, "cmd_3cd6", None if bl.itemData(k) is None else [slot, int(bl.itemData(k))]))
        p.row("Blending", bl, tip="Normal: covers what is behind; Adds light: glows (black = see-through); Takes "
                                  "light away: darkens")

    def _put(self, show, existing, name, args):
        self.putAtShow.emit(show, list(existing), name, args)

    def _moved(self, it, show, k, val):
        d = [0.0, 0.0, 0.0]
        d[k] = float(val - int(show.args[2 + k]))
        if any(d):
            self.moveClipBy.emit(it, tuple(d))

    def _size(self, show, pct, now=False):
        """the show's size (its 7th value is the animation speed, not a second size)"""
        self._queue(show, 5, int(pct) * 10, now)

    # ---------------------------------------------------------------- a pose
    def _pose(self, it):
        op = it.ops[0]
        num = None
        try:
            num = self.sprite_of(op.args[0]) if self.sprite_of else None
        except Exception:
            num = None
        frames = []
        if self.thumbs is not None and num:
            try:
                frames = self.thumbs.pose_frames(num, self.thumbs.aid_for(num, op.args[1]), 72)
            except Exception:
                frames = []
        img = self._header(f"Pose: {it.label}", f"{choreo.who(op.args[0]) if hasattr(choreo, 'who') else ''} · "
                                                f"frames {it.start}–{it.end} ({(it.end - it.start) / 60:.2f} s)",
                           frames[0] if frames else None,
                           [("🏃 Change pose…", lambda: self.pickPose.emit(op), "Choose another pose by its picture",
                             self.editable(op, 1)),
                            ("🗑 Delete", lambda: self.deleteOps.emit([op]), "Remove this pose change", True)])
        if img is not None and len(frames) > 1:
            self._anim = (img, frames, 0)
            self.anim.start()
        p = self._panel("Pose", "🏃")
        p.row("Character", self._actor_combo(op, 0))
        cb = QComboBox()
        cur = op.args[1]
        for label, m in self.motions:
            cb.addItem(label, m)
        if cb.findData(cur) < 0:
            cb.addItem(f"Pose {cur}", cur)
        cb.setCurrentIndex(cb.findData(cur))
        cb.setEnabled(self.editable(op, 1))
        cb.currentIndexChanged.connect(lambda k: self._queue(op, 1, int(cb.itemData(k)), now=True))
        p.row("Pose", cb, "Or 🏃 Change pose… to pick it by its animation.")
        sb = QSpinBox()
        sb.setRange(0, 9999)
        sb.setValue(int(it.start))
        sb.setPrefix("frame ")
        sb.setKeyboardTracking(False)
        sb.valueChanged.connect(lambda val: self.retime.emit(self.sel, val))
        p.row("Starts", sb)
        if len(op.args) > 2:
            p.row("Blend in", self._spin(op, 2, 0, 255, suffix="frames", width=120,
                                         tip="frames to blend from the previous pose"))
        self._advanced([op])

    def _anim_step(self):
        if self._anim is None:
            self.anim.stop()
            return
        img, frames, i = self._anim
        try:
            img.setPixmap(frames[(i + 1) % len(frames)].scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                               Qt.TransformationMode.SmoothTransformation))
        except RuntimeError:                       # the label is gone
            self.anim.stop()
            self._anim = None
            return
        self._anim = (img, frames, i + 1)

    # ---------------------------------------------------------------- a sound
    def _sound(self, op, sel):
        pix, secs = (None, 0.0)
        if self.thumbs is not None and self.sound_bank is not None and op.cid != 0x4618 and op.args:
            try:
                pix, secs = self.thumbs.wave(self.sound_bank, int(op.args[0]), 220, 60)
            except Exception:
                pix, secs = None, 0.0
        title = op.label()
        self._header(title[:1].upper() + title[1:], f"frame {op.frame}" + (f" · {secs:.2f} s long" if secs else "")
                     + f" · {op.name}", None,
                     [("▶ Play", lambda: self.playSound.emit(op), "Hear it", True),
                      ("🔊 Choose by ear…", lambda: self.pickSound.emit(op), "Pick another sound: hear them first",
                       self.editable(op, 0) and op.cid in (0x4610, 0x4612)),
                      ("🗑 Delete", lambda: self.deleteOps.emit([op]), "Remove this sound", True)])
        if pix is not None:
            l = QLabel()
            l.setPixmap(pix)
            l.setStyleSheet("border: 1px solid #3a3553; border-radius: 4px;")
            self.lay.addWidget(l)
        p = self._panel("Sound", "🔊")
        sb = QSpinBox()
        sb.setRange(0, 9999)
        sb.setValue(int(op.frame))
        sb.setPrefix("frame ")
        sb.setKeyboardTracking(False)
        sb.valueChanged.connect(lambda val: self.retime.emit(self.sel, val))
        p.row("Plays at", sb)
        names = choreo.arg_names(op.cid)
        for i, n in enumerate(names):
            if i >= len(op.args) or isinstance(op.args[i], bytes):
                continue
            nice = {"0": "Sound", "1": "Volume %", "2": "Speed (1000 = normal)"}.get(str(i), n.replace("_", " "))
            p.row(nice, self._spin(op, i, width=130))
        self._advanced([op])

    # ---------------------------------------------------------------- any other command
    def _command(self, op, sel):
        c = op.cid
        title = fxtools.describe(op, self.names) if op.kind == "effect" else op.label()
        self._header(title[:1].upper() + title[1:], f"frame {op.frame}" + (f", lasts {op.dur} frames" if op.dur
                                                                            else "") + f" · {op.name}",
                     actions=[("🗑 Delete", lambda: self.deleteOps.emit([op]), "Remove this command", True)])
        d = choreo.describe(c)
        p = self._panel("Values", "⚙")
        if d:
            p.note(d)
        sb = QSpinBox()
        sb.setRange(0, 9999)
        sb.setValue(int(op.frame))
        sb.setPrefix("frame ")
        sb.setKeyboardTracking(False)
        sb.valueChanged.connect(lambda val: self.retime.emit(self.sel, val))
        p.row("At", sb)
        for i, n in enumerate(choreo.arg_names(c)):
            if i >= len(op.args) or isinstance(op.args[i], bytes):
                continue
            p.row(n.replace("_", " "), self._spin(op, i, width=130))

    # ---------------------------------------------------------------- values
    def _queue(self, op, i, v, now=False):
        self.pending[(op.ident, i)] = (op, i, v)
        self.timer.start(0 if now else 150)

    def _commit(self):
        items, self.pending = list(self.pending.values()), {}
        for op, i, v in items:
            self.valueEdited.emit(op, i, v)
