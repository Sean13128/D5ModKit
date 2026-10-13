"""Presets: ready-made building blocks (d5lib/presets.py) -- pick one, set its values, add it at the playhead.

Movement (dash, leap, rise, vanish and reappear, knock back ...), camera (close-up, swing, low angle, shake,
quake), screen (fade, white flash, darken, void), hits, and motion for the selected effect (pop in, pulse, spin,
rise and fade).  Each one becomes a layer of commands on the timeline that can be moved and changed afterwards."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QScrollArea, QWidget, QVBoxLayout, QLabel, QPushButton, QFormLayout, QSpinBox,
                             QComboBox, QTreeWidget, QTreeWidgetItem, QGroupBox)

from d5lib import choreo, presets

GROUP_ICONS = {"Movement": "🏃", "Camera": "🎥", "Screen": "🌑", "Hits": "💥", "Selected effect": "✨"}


class PresetPanel(QScrollArea):
    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.key = None
        self.fields = {}
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        intro = QLabel("Ready-made building blocks. Pick one, set its values and add it at the playhead; it becomes "
                       "a layer on the timeline you can move and change like the rest.")
        intro.setWordWrap(True)
        intro.setMinimumWidth(10)
        intro.setObjectName("muted")
        lay.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(220)
        for g in presets.GROUP_ORDER:
            gi = QTreeWidgetItem([f"{GROUP_ICONS.get(g, '')}  {g}"])
            gi.setFlags(gi.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(gi)
            for p in presets.PRESETS:
                if p.group == g:
                    it = QTreeWidgetItem([p.name])
                    it.setData(0, Qt.ItemDataRole.UserRole, p.key)
                    it.setToolTip(0, p.desc or p.name)
                    gi.addChild(it)
            gi.setExpanded(True)
        self.tree.currentItemChanged.connect(lambda it, _: self._pick(it))
        self.tree.itemDoubleClicked.connect(lambda it, _: it.data(0, Qt.ItemDataRole.UserRole) and self._add())
        lay.addWidget(self.tree, 1)
        self.box = QGroupBox("")
        bl = QVBoxLayout(self.box)
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setMinimumWidth(10)
        bl.addWidget(self.desc)
        self.form_w = QWidget()
        self.form = QFormLayout(self.form_w)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.form_w)
        self.add_btn = QPushButton("➕ Add at the playhead")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self._add)
        bl.addWidget(self.add_btn)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setMinimumWidth(10)
        self.note.setObjectName("muted")
        bl.addWidget(self.note)
        lay.addWidget(self.box)
        self.box.hide()

    # ---- choices of "who"
    def _actors(self, preset):
        out = [("Caster", choreo.CASTER)]
        n = 1
        r = getattr(self.ed, "renderer", None)
        if r is not None:
            n = len(r.target_panels())
        out.append(("Target (main)", choreo.TARGET))
        for i in range(1, n):
            out.append((f"Target {i + 1}", choreo.target_actor(i)))
        if preset.key == "hit":
            out.insert(0, ("Every target in the area", presets.ALL_TARGETS))
        return out

    def _pick(self, it):
        key = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
        pr = presets.BY_KEY.get(key)
        if pr is None:
            self.box.hide()
            return
        self.key = key
        self.box.setTitle(pr.name)
        self.desc.setText(pr.desc or "")
        self.desc.setVisible(bool(pr.desc))
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        for p in pr.params:
            if p.kind == "actor":
                w = QComboBox()
                for label, a in self._actors(pr):
                    w.addItem(label, a)
                k = w.findData(int(p.default))
                w.setCurrentIndex(max(0, k))
            else:
                w = QSpinBox()
                w.setRange(int(p.lo), int(p.hi))
                w.setSingleStep(max(1, int(p.step)))
                w.setValue(int(p.default))
            if p.tip:
                w.setToolTip(p.tip)
            self.form.addRow(p.label, w)
            self.fields[p.name] = w
        self.box.show()
        self.refresh()

    def values(self):
        out = {}
        for name, w in self.fields.items():
            out[name] = w.currentData() if isinstance(w, QComboBox) else w.value()
        return out

    def refresh(self):
        """the playhead / selection changed"""
        pr = presets.BY_KEY.get(self.key)
        if pr is None:
            return
        f = getattr(self.ed, "frame", 0)
        ok, why = True, ""
        if pr.needs_effect:
            ctx = self.ed.preset_effect()
            if ctx is None:
                ok, why = False, "Select an effect clip on the timeline (or in the preview) first."
            else:
                why = f"Works on effect slot {ctx['slot']}."
        self.add_btn.setText(f"➕ Add at frame {f}")
        self.add_btn.setEnabled(ok)
        self.note.setText(why)

    def _add(self):
        if self.key:
            self.ed.add_preset(self.key, self.values())
