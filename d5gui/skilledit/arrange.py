"""Arrange: edit several effects at once (d5lib/fxtools.py).

* Selection: the timeline's selected effect clips (Ctrl+click, Shift+drag a box, click a row's name);
  "Same effect" picks every clip of the same effect (all 8 talismans at once).
* Transform: spread out / pull in, turn, lift, move and resize the selection around a pivot (the caster, the
  selection's centre or the target).  Changes show live; Apply keeps them (one undo step), Cancel drops them.
  The same works with the gizmo in the preview.
* Paths: give the selected effects new flight paths from presets (homing missile, arc, spiral, orbit, burst ...),
  timed like their own flights or from the playhead."""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
                             QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QGridLayout)

from d5lib import fxtools

PIVOTS = [("Selection centre", "centre"), ("Caster", "caster"), ("Target", "target"), ("Each its own", "own")]
FORMATIONS = {
    # key: (label, help, [(name, label, default, lo, hi, step)])
    "circle": ("Circle", "Evenly around the pivot.",
               [("radius", "Radius", 90, 0, 900, 5), ("height", "Height above the floor", 58, -200, 600, 5),
                ("angle", "Start angle", 0, -180, 180, 5)]),
    "arc": ("Arc in front", "A fan towards the target, in front of the pivot.",
            [("radius", "Distance", 90, 0, 900, 5), ("spread_deg", "Fan angle", 120, 0, 360, 5),
             ("height", "Height above the floor", 58, -200, 600, 5)]),
    "line": ("Line across", "A row across the line to the target.",
             [("spacing", "Spacing", 40, 0, 400, 5), ("height", "Height above the floor", 58, -200, 600, 5)]),
    "scatter": ("Random scatter", "Random places around the pivot (another seed: another pattern).",
                [("radius", "Radius", 120, 0, 900, 5), ("height", "Height above the floor", 58, -200, 600, 5),
                 ("seed", "Seed", 1, 1, 999, 1)]),
}


class ArrangePanel(QScrollArea):
    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)
        self.summary = QLabel("Select effects on the timeline.")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("cardTitle")
        lay.addWidget(self.summary)
        row = QHBoxLayout()
        for text, tip, fn in (("All like these", "Select every effect that uses the same picture (e.g. all 8 talismans)",
                               lambda: self.ed.timeline.select_similar()),
                              ("Whole tracks", "Select everything on the tracks of the selected effects",
                               lambda: self.ed.timeline.select_rows_of_selection()),
                              ("None", "Select nothing (Esc)", lambda: self.ed.timeline.clear_selection())):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)

        # ---------------------------------------------------------------- transform
        g = QGroupBox("Space out, rotate, move, resize")
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.pivot = QComboBox()
        for label, key in PIVOTS:
            self.pivot.addItem(label, key)
        self.pivot.setToolTip("The point spacing and rotating happen around (the same as 'Pivot' in the preview)")
        f.addRow("Pivot", self.pivot)
        self.spread = self._dspin(0.1, 6.0, 1.0, 0.05, "×", "Further apart (more than 1) or closer together (less "
                                  "than 1) around the pivot; their paths stretch the same way")
        f.addRow("Spacing", self.spread)
        self.spread_y = QCheckBox("also in height")
        f.addRow("", self.spread_y)
        self.turn = self._dspin(-360, 360, 0, 5, "°", "Swing them around the pivot (seen from above)")
        f.addRow("Rotate", self.turn)
        self.lift = self._dspin(-600, 600, 0, 5, "", "Up (+) or down (-); 120 = the height of one panel")
        f.addRow("Raise / lower", self.lift)
        mv = QHBoxLayout()
        self.mx = self._dspin(-1200, 1200, 0, 10, "", "Move along x (script units)")
        self.mz = self._dspin(-1200, 1200, 0, 10, "", "Move along z (script units)")
        mv.addWidget(QLabel("x"))
        mv.addWidget(self.mx)
        mv.addWidget(QLabel("z"))
        mv.addWidget(self.mz)
        w = QWidget()
        w.setLayout(mv)
        mv.setContentsMargins(0, 0, 0, 0)
        f.addRow("Shift", w)
        self.size = self._dspin(0.05, 10.0, 1.0, 0.05, "×", "How big they are (2 = twice as big)")
        f.addRow("Size", self.size)
        self.with_target = QCheckBox("also where they land on the target")
        self.with_target.setToolTip("Off (normal): flights into the target keep hitting it")
        f.addRow("", self.with_target)
        br = QHBoxLayout()
        self.apply_btn = QPushButton("✔ Keep")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.commit)
        self.apply_btn.setToolTip("Keep the changes shown (one undo step)")
        self.cancel_btn = QPushButton("↩ Discard")
        self.cancel_btn.clicked.connect(self.cancel)
        br.addWidget(self.apply_btn)
        br.addWidget(self.cancel_btn)
        f.addRow(br)
        hint = QLabel("Changes show in the preview right away. Easier: select the effects in the preview and use "
                      "the Move / Rotate / Scale tools there (keys G, R, S).")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        f.addRow(hint)
        lay.addWidget(g)
        for w in (self.spread, self.turn, self.lift, self.mx, self.mz, self.size):
            w.valueChanged.connect(self._transform_changed)
        for w in (self.spread_y, self.with_target):
            w.toggled.connect(self._transform_changed)
        self.pivot.currentIndexChanged.connect(self._transform_changed)

        # ---------------------------------------------------------------- formation
        g = QGroupBox("Put them in a shape")
        v = QVBoxLayout(g)
        self.form_shape = QComboBox()
        for key, (label, _, _) in FORMATIONS.items():
            self.form_shape.addItem(label, key)
        self.form_shape.currentIndexChanged.connect(self._formation_shape_changed)
        v.addWidget(self.form_shape)
        self.form_help = QLabel("")
        self.form_help.setWordWrap(True)
        self.form_help.setObjectName("muted")
        v.addWidget(self.form_help)
        self.form_box = QWidget()
        self.form_params = QFormLayout(self.form_box)
        self.form_params.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.form_box)
        fr = QHBoxLayout()
        self.form_try = QPushButton("👁 Preview")
        self.form_try.setToolTip("Place the selected effects so (each one's whole path moves along)")
        self.form_try.clicked.connect(self._formation_changed)
        self.form_btn = QPushButton("✔ Keep")
        self.form_btn.setObjectName("primary")
        self.form_btn.clicked.connect(self.commit_formation)
        fc = QPushButton("↩ Discard")
        fc.clicked.connect(self.cancel)
        fr.addWidget(self.form_try)
        fr.addWidget(self.form_btn)
        fr.addWidget(fc)
        v.addLayout(fr)
        lay.addWidget(g)
        self.fwidgets = {}

        # ---------------------------------------------------------------- paths
        g = QGroupBox("Flight paths")
        v = QVBoxLayout(g)
        self.preset = QComboBox()
        for key, (label, _, _) in fxtools.PRESETS.items():
            self.preset.addItem(label, key)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        v.addWidget(self.preset)
        self.preset_help = QLabel("")
        self.preset_help.setWordWrap(True)
        self.preset_help.setObjectName("muted")
        v.addWidget(self.preset_help)
        self.params_box = QWidget()
        self.params = QFormLayout(self.params_box)
        self.params.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.params_box)
        f2 = QFormLayout()
        self.ease = QComboBox()
        for key, label in fxtools.EASES:
            self.ease.addItem(label, key)
        f2.addRow("Speed", self.ease)
        self.keep_timing = QCheckBox("when each one flies now")
        self.keep_timing.setChecked(True)
        self.keep_timing.setToolTip("On: every effect flies when and as long as its flight does now (damage and hit "
                                    "effects stay in time). Off: from the playhead, for the frames below.")
        f2.addRow("Timing", self.keep_timing)
        self.flight_len = QSpinBox()
        self.flight_len.setRange(0, 600)
        self.flight_len.setSpecialValueText("as now")
        self.flight_len.setSuffix(" frames")
        self.flight_len.setToolTip("With the effects' own flight times: make every flight this long (0 = as now). "
                                   "What comes after each flight in the same script (its hit effect, damage, sound) "
                                   "moves later with the new arrival.")
        f2.addRow("Flight length", self.flight_len)
        self.duration = QSpinBox()
        self.duration.setRange(2, 600)
        self.duration.setValue(30)
        self.duration.setSuffix(" frames")
        f2.addRow("Duration", self.duration)
        self.stagger = QSpinBox()
        self.stagger.setRange(0, 120)
        self.stagger.setSuffix(" frames apart")
        f2.addRow("One after another", self.stagger)
        self.aim_y = QSpinBox()
        self.aim_y.setRange(-200, 400)
        self.aim_y.setValue(45)
        self.aim_y.setToolTip("Where on the target the effects land (height above its feet)")
        f2.addRow("Aim height", self.aim_y)
        v.addLayout(f2)
        pr = QHBoxLayout()
        self.path_btn = QPushButton("✔ Keep path")
        self.path_btn.setObjectName("primary")
        self.path_btn.clicked.connect(self.commit_path)
        pc = QPushButton("↩ Discard")
        pc.clicked.connect(self.cancel)
        self.path_live = QPushButton("👁 Preview")
        self.path_live.setToolTip("Show the path in the preview now (Keep path keeps it)")
        self.path_live.clicked.connect(self._path_changed)
        pr.addWidget(self.path_live)
        pr.addWidget(self.path_btn)
        pr.addWidget(pc)
        v.addLayout(pr)
        lay.addWidget(g)
        for w in (self.ease, self.keep_timing, self.duration, self.stagger, self.aim_y, self.flight_len):
            sig = getattr(w, "valueChanged", None) or getattr(w, "currentIndexChanged", None) or w.toggled
            sig.connect(self._path_changed_if_live)
        self.show_paths = QCheckBox("Show the selected effects' paths in the preview")
        self.show_paths.setChecked(True)
        self.show_paths.toggled.connect(self._paths_toggled)
        lay.addWidget(self.show_paths)
        lay.addStretch(1)

        self.mode = None            # None | "transform" | "formation" | "path"
        self.pwidgets = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._apply_live)
        self._preset_changed()
        self._formation_shape_changed()
        self.set_selection([])

    # ---------------------------------------------------------------- widgets
    def _dspin(self, lo, hi, val, step, suffix, tip):
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(2 if step < 1 else 0)
        sb.setSingleStep(step)
        sb.setValue(val)
        if suffix:
            sb.setSuffix(f" {suffix}")
        sb.setToolTip(tip)
        sb.setKeyboardTracking(False)
        return sb

    def _preset_changed(self, *_):
        key = self.preset.currentData()
        label, help_, params = fxtools.PRESETS[key]
        self.preset_help.setText(help_)
        while self.params.rowCount():
            self.params.removeRow(0)
        self.pwidgets = {}
        for name, lab, default, lo, hi, step in params:
            sb = self._dspin(lo, hi, default, step, "", lab)
            sb.valueChanged.connect(self._path_changed_if_live)
            self.params.addRow(lab, sb)
            self.pwidgets[name] = sb
        k = self.ease.findData(fxtools.DEFAULT_EASE.get(key, "linear"))
        self.ease.blockSignals(True)
        self.ease.setCurrentIndex(max(0, k))
        self.ease.blockSignals(False)
        orbit = not fxtools.targets_target(key)
        self.aim_y.setEnabled(not orbit)
        if orbit:
            self.keep_timing.setChecked(False)
        self._path_changed_if_live()

    def _formation_shape_changed(self, *_):
        key = self.form_shape.currentData()
        label, help_, params = FORMATIONS[key]
        self.form_help.setText(help_)
        while self.form_params.rowCount():
            self.form_params.removeRow(0)
        self.fwidgets = {}
        for name, lab, default, lo, hi, step in params:
            sb = self._dspin(lo, hi, default, step, "", lab)
            sb.valueChanged.connect(self._formation_changed_if_live)
            self.form_params.addRow(lab, sb)
            self.fwidgets[name] = sb
        self._formation_changed_if_live()

    def _formation_changed_if_live(self, *_):
        if self.mode == "formation":
            self.timer.start(60)

    def _formation_changed(self, *_):
        if self.mode not in (None, "formation"):
            self.cancel()
        self.mode = "formation"
        self.timer.start(0)

    def formation_params(self):
        d = {k: w.value() for k, w in self.fwidgets.items()}
        d.update(shape=self.form_shape.currentData(), pivot=self.pivot.currentData())
        return d

    def commit_formation(self):
        if self.mode != "formation":
            if self.mode is not None:
                self.cancel()
            self.mode = "formation"
        self.timer.stop()
        self._apply_live()
        self.ed.live_commit()
        self.mode = None

    def _paths_toggled(self, on):
        self.ed.view.show_paths = on
        self.ed.view.update()

    def _reset_transform(self):
        for w, v in ((self.spread, 1.0), (self.turn, 0), (self.lift, 0), (self.mx, 0), (self.mz, 0), (self.size, 1.0)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)

    # ---------------------------------------------------------------- selection
    def set_selection(self, items):
        clips = [it for it in items if it.kind == "clip"]
        if not clips:
            self.summary.setText("Select effects first: click them in the preview (Shift+click or drag a box for "
                                 "several), or on the timeline. Then space them out, put them in a shape, or give "
                                 "them a flight path (homing missile …).")
        else:
            names = {}
            for it in clips:
                names[it.label] = names.get(it.label, 0) + 1
            txt = ", ".join(f"{n} ×{c}" if c > 1 else n for n, c in names.items())
            self.summary.setText(f"{len(clips)} effect{'s' if len(clips) != 1 else ''} selected: {txt}")
        on = bool(clips)
        for w in (self.apply_btn, self.path_btn, self.path_live, self.form_btn, self.form_try):
            w.setEnabled(on)

    # ---------------------------------------------------------------- live editing
    def _transform_changed(self, *_):
        if self.mode in ("path", "formation"):
            self.cancel()
        self.mode = "transform"
        self.timer.start(60)

    def _path_changed_if_live(self, *_):
        if self.mode == "path":
            self.timer.start(80)

    def _path_changed(self, *_):
        if self.mode in ("transform", "formation"):
            self.cancel()
        self.mode = "path"
        self.timer.start(0)

    def transform_params(self):
        return dict(pivot=self.pivot.currentData(), spread=self.spread.value(), spread_y=self.spread_y.isChecked(),
                    turn=self.turn.value(), lift=self.lift.value(), move=(self.mx.value(), 0.0, self.mz.value()),
                    size=self.size.value(), with_target=self.with_target.isChecked())

    def path_params(self):
        return dict(preset=self.preset.currentData(), ease=self.ease.currentData(),
                    params={k: w.value() for k, w in self.pwidgets.items()}, keep=self.keep_timing.isChecked(),
                    length=self.flight_len.value(),
                    duration=self.duration.value(), stagger=self.stagger.value(), aim_y=self.aim_y.value())

    def _apply_live(self):
        if self.mode is None:
            return
        if not self.ed.live_active() and not self.ed.live_begin():
            self.mode = None
            return
        if self.mode == "transform":
            self.ed.live_transform(self.transform_params())
        elif self.mode == "formation":
            self.ed.live_formation(self.formation_params())
        else:
            self.ed.live_path(self.path_params())

    def commit(self):
        """keep the transform shown now"""
        if self.timer.isActive():
            self.timer.stop()
            self._apply_live()
        self.ed.live_commit()
        self.mode = None
        self._reset_transform()

    def commit_path(self):
        """apply the path preset to the selection and keep it"""
        if self.mode != "path":
            if self.mode is not None:
                self.cancel()
            self.mode = "path"
        self.timer.stop()
        self._apply_live()
        self.ed.live_commit()
        self.mode = None

    def cancel(self):
        self.timer.stop()
        self.ed.live_cancel()
        self.mode = None
        self._reset_transform()
