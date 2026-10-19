"""Area Shapes: every area of AttackMap.dat (where a skill hits), painted like a picture.

A shape is a list of panels around the cursor (or the caster), in the order the game hits the units on them (1 = the
main target).  Paint with the brushes (d5gui/skilledit/areapanel.py: AreaGrid + BrushBar): panels go in in the order
you paint them, the # brush renumbers, Renumber tidies the order, right-click erases, Shift+drag paints a line.  The
list says which skills use a shape; New / Clone make shapes of your own (ids 40000+), Revert gives a game shape back
its panels.  A shape's name and notes are the kit's (patches/skills/shape_names.json in the mod).
"""
import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QSplitter,
                             QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QButtonGroup)

from d5lib import skillarea as sa
from ..common import PageHeader, SearchBox, error_box
from ..dbservice import get_service
from ..skilledit.areapanel import AreaGrid, BrushBar

AM = "AttackMap.dat"
MAGIC = "magic.dat"
NAMES = "shape_names.json"                 # patches/skills/shape_names.json: {"<id>": {"name": "", "notes": ""}}
ROLE = Qt.ItemDataRole.UserRole


class AreaShapesPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.main = main
        self.svc = get_service(ws)
        self.sid = None                       # the shape shown
        self.cells0 = None                    # its panels as loaded (to tell changes)
        self._loading = False
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Area Shapes", "Where skills hit (AttackMap.dat). Paint a shape panel by panel: "
                                                "the numbers are the order the targets are hit in. See which "
                                                "skills use it, make shapes of your own, give a game shape its "
                                                "panels back."))
        split = QSplitter()
        # ---- the list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.search = SearchBox("Search: id, skill, name…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        self.show_box = QComboBox()
        for k, lab in (("all", "All"), ("used", "Used by skills"), ("unused", "Unused"), ("mine", "Yours / changed")):
            self.show_box.addItem(lab, k)
        self.show_box.currentIndexChanged.connect(self._filter)
        top.addWidget(self.show_box)
        ll.addLayout(top)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Panels", "Used by", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c in (0, 1, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.currentCellChanged.connect(lambda r, *_: self._pick_row(r))
        ll.addWidget(self.table, 1)
        row = QHBoxLayout()
        b = QPushButton("➕ New")
        b.setToolTip("A shape of your own: one panel to start painting from")
        b.clicked.connect(self.new_shape)
        row.addWidget(b)
        b = QPushButton("⧉ Clone")
        b.setToolTip("A shape of your own with this shape's panels")
        b.clicked.connect(self.clone_shape)
        row.addWidget(b)
        self.b_del = QPushButton("🗑 Delete")
        self.b_del.setToolTip("Delete a shape of yours that no skill uses")
        self.b_del.clicked.connect(self.delete_shape)
        row.addWidget(self.b_del)
        row.addStretch(1)
        ll.addLayout(row)
        self.count = QLabel()
        self.count.setObjectName("muted")
        ll.addWidget(self.count)
        split.addWidget(left)
        # ---- the shape
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Pick a shape")
        self.title.setObjectName("cardTitle")
        rl.addWidget(self.title)
        self.sub = QLabel()
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        rl.addWidget(self.sub)
        self.tabs = QTabWidget()
        ed = QWidget()
        el = QVBoxLayout(ed)
        place = QHBoxLayout()
        place.addWidget(QLabel("Preview placed"))
        self.at_cursor = QRadioButton("at the cursor")
        self.at_cursor.setToolTip("Skills with a reach: the player points the cursor at a panel and the shape is "
                                  "centred on it")
        self.from_caster = QRadioButton("from the caster")
        self.from_caster.setToolTip("Skills without a reach (range 0): the shape is laid down from the caster")
        grp = QButtonGroup(self)
        grp.addButton(self.at_cursor)
        grp.addButton(self.from_caster)
        self.at_cursor.toggled.connect(self._placement)
        place.addWidget(self.at_cursor)
        place.addWidget(self.from_caster)
        place.addWidget(QLabel("  cursor"))
        self.cur = QSpinBox()
        self.cur.setRange(1, 9)
        self.cur.setSuffix(" panel(s) ahead")
        self.cur.valueChanged.connect(self._placement)
        place.addWidget(self.cur)
        place.addStretch(1)
        el.addLayout(place)
        self.grid = AreaGrid()
        self.grid.edited.connect(self._edited)
        self.brushes = BrushBar(self.grid)
        el.addWidget(self.brushes)
        el.addWidget(self.grid, 1)
        legend = QLabel("★ the caster, facing up · red: hit · orange ◆: the cursor's panel (hit too) · green ➜: where "
                        "the caster ends up · blue outline: differs from the game's shape. Left-click / drag paints, "
                        "right-click erases, Shift+drag a straight line, Ctrl+Z / Ctrl+Y undo / redo.")
        legend.setWordWrap(True)
        legend.setObjectName("muted")
        el.addWidget(legend)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("a name of your own for this shape (the kit's; the game has none)")
        self.name.textEdited.connect(self._edited)
        form.addRow("Name", self.name)
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(60)
        self.notes.setPlaceholderText("notes")
        self.notes.textChanged.connect(lambda: not self._loading and self._edited())
        form.addRow("Notes", self.notes)
        el.addLayout(form)
        self.tabs.addTab(ed, "Editor")
        # used by
        ub = QWidget()
        ul = QVBoxLayout(ub)
        self.users = QTableWidget(0, 3)
        self.users.setHorizontalHeaderLabels(["Skill", "Name", "Reach"])
        self.users.verticalHeader().setVisible(False)
        self.users.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.users.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.users.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.users.cellDoubleClicked.connect(lambda r, _c: self._open_skill(r))
        ul.addWidget(self.users, 1)
        b = QPushButton("Open the skill (Skills & Animations)")
        b.clicked.connect(lambda: self._open_skill(self.users.currentRow()))
        ul.addWidget(b)
        self.tabs.addTab(ub, "Used by")
        # JSON
        jb = QWidget()
        jl = QVBoxLayout(jb)
        self.json = QPlainTextEdit()
        jl.addWidget(self.json, 1)
        b = QPushButton("Apply the JSON")
        b.setToolTip('The shape\'s panels from the text: {"cells": [[x, y, kind], ...]} (kind 1 hit, 2 caster ends '
                     'here, 3 cursor), in hit order')
        b.clicked.connect(self._apply_json)
        jl.addWidget(b)
        self.tabs.addTab(jb, "JSON")
        self.tabs.currentChanged.connect(lambda i: i == 2 and self._fill_json())
        rl.addWidget(self.tabs, 1)
        bar = QHBoxLayout()
        self.b_save = QPushButton("💾 Save")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save)
        bar.addWidget(self.b_save)
        self.b_discard = QPushButton("Discard")
        self.b_discard.clicked.connect(self.discard)
        bar.addWidget(self.b_discard)
        self.b_revert = QPushButton("Revert to the game's")
        self.b_revert.setToolTip("Give this game shape its own panels back (saved with Save)")
        self.b_revert.clicked.connect(self.revert)
        bar.addWidget(self.b_revert)
        bar.addStretch(1)
        self.state = QLabel()
        self.state.setObjectName("muted")
        bar.addWidget(self.state)
        rl.addLayout(bar)
        split.addWidget(right)
        split.setSizes([420, 900])
        lay.addWidget(split, 1)
        self._populated = False

    # ---------------------------------------------------------------- data
    def on_show(self):
        if not self._populated:
            self._populate()

    def _tables(self):
        return self.svc.table(AM), self.svc.table(MAGIC)

    def _names(self):
        """{id: {"name", "notes"}} from the enabled mods (the last one wins)"""
        out = {}
        for m in self.ws.mods.enabled_mods():
            for k, v in (m.load_patch("skills", NAMES) or {}).items():
                out[int(k)] = v
        return out

    def _populate(self, keep=None):
        self._populated = True
        try:
            at, mt = self._tables()
        except Exception as e:
            error_box(self, "Area Shapes", e)
            return
        shapes = sa.shapes(at)
        van = sa.shapes(self.svc.vanilla(AM))
        names = self._names()
        skill_names = {int(r["id"]): str(r["name_EN"] or "") for r in mt.rows}
        users = {}
        for r in mt.rows:
            sid = int(r["attack_map"] or 0)
            if sid:
                users.setdefault(sid, []).append(int(r["id"]))
        self._users, self._skill_names, self._van, self._shape_map = users, skill_names, van, shapes
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for sid in sorted(shapes):
            sh = shapes[sid]
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem()
            it.setData(Qt.ItemDataRole.DisplayRole, sid)
            it.setData(ROLE, sid)
            self.table.setItem(r, 0, it)
            n = sum(1 for _, _, k in sh.cells if k != sa.USER_TO)
            it = QTableWidgetItem()
            it.setData(Qt.ItemDataRole.DisplayRole, n)
            self.table.setItem(r, 1, it)
            us = users.get(sid, [])
            label = names.get(sid, {}).get("name") or ""
            used = ", ".join(skill_names.get(u, str(u)) for u in us[:3]) + (f" +{len(us) - 3}" if len(us) > 3 else "")
            self.table.setItem(r, 2, QTableWidgetItem((f"{label} · " if label else "") + (used or "—")))
            mark = "★" if sid not in van else ("✎" if [tuple(c) for c in van[sid].cells] != [tuple(c) for c in sh.cells]
                                               else "")
            m = QTableWidgetItem(mark)
            m.setToolTip("★ a shape of yours · ✎ a game shape with other panels")
            self.table.setItem(r, 3, m)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.count.setText(f"{len(shapes)} shapes · {sum(1 for s in shapes if s not in van)} of yours")
        self._filter()
        target = keep if keep is not None else self.sid
        if target is not None:
            self.select_shape(target)
        elif self.table.rowCount():
            self.table.selectRow(0)

    def _filter(self, *_):
        t = self.search.text().strip().lower()
        mode = self.show_box.currentData()
        for r in range(self.table.rowCount()):
            sid = self.table.item(r, 0).data(ROLE)
            text = " ".join(self.table.item(r, c).text().lower() for c in range(3))
            ok = not t or t in text
            used = bool(self._users.get(sid))
            mark = self.table.item(r, 3).text()
            ok = ok and (mode == "all" or (mode == "used" and used) or (mode == "unused" and not used) or
                         (mode == "mine" and mark))
            self.table.setRowHidden(r, not ok)

    def select_shape(self, sid):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(ROLE) == sid:
                self.table.selectRow(r)
                self.table.scrollToItem(self.table.item(r, 0))
                return True
        return False

    def _pick_row(self, r):
        if r < 0 or self.table.item(r, 0) is None:
            return
        sid = self.table.item(r, 0).data(ROLE)
        if sid == self.sid:
            return
        if self._dirty() and QMessageBox.question(
                self, "Area Shapes", f"Shape {self.sid} has changes that aren't saved. Leave them?") != \
                QMessageBox.StandardButton.Yes:
            self.table.blockSignals(True)
            self.select_shape(self.sid)
            self.table.blockSignals(False)
            return
        self.show_shape(sid)

    def show_shape(self, sid):
        sh = self._shape_map.get(sid)
        if sh is None:
            return
        self._loading = True
        self.sid = sid
        self.cells0 = [tuple(c) for c in sh.cells]
        us = self._users.get(sid, [])
        mt = self.svc.table(MAGIC)
        reach = {int(r["id"]): int(r["range"] or 0) for r in mt.rows if int(r["id"]) in set(us)}
        centred = any(v > 0 for v in reach.values()) or any(k == sa.CURSOR for _, _, k in sh.cells)
        self.at_cursor.blockSignals(True)
        (self.at_cursor if centred else self.from_caster).setChecked(True)
        self.at_cursor.blockSignals(False)
        self.grid.area = sa.Area(skill=None, range=1 if centred else 0, shape=sid, cells=list(sh.cells), known=True)
        self.grid.cursor = self.cur.value()
        self.grid.enemies = None
        self.grid.reset_history()
        self.grid.number = sum(1 for _, _, k in sh.cells if k != sa.USER_TO) + 1
        self.brushes.sync()
        meta = self._names().get(sid, {})
        self.name.setText(meta.get("name", ""))
        self.notes.setPlainText(meta.get("notes", ""))
        self.users.setRowCount(0)
        for u in us:
            r = self.users.rowCount()
            self.users.insertRow(r)
            it = QTableWidgetItem(str(u))
            it.setData(ROLE, u)
            self.users.setItem(r, 0, it)
            self.users.setItem(r, 1, QTableWidgetItem(self._skill_names.get(u, "")))
            rg = reach.get(u, 0)
            self.users.setItem(r, 2, QTableWidgetItem("anywhere" if rg >= sa.MAP_WIDE else str(rg) if rg else
                                                      "from the caster"))
        self.tabs.setTabText(1, f"Used by ({len(us)})")
        self._loading = False
        self._refresh()
        if self.tabs.currentIndex() == 2:
            self._fill_json()

    # ---------------------------------------------------------------- editing
    def _placement(self, *_):
        if self.sid is None:
            return
        self.grid.area.range = 1 if self.at_cursor.isChecked() else 0
        self.grid.cursor = self.cur.value()
        self.grid.update()

    def _cells(self):
        return [tuple(c) for c in self.grid.area.cells]

    def _dirty(self):
        if self.sid is None or self.cells0 is None:
            return False
        meta = self._names().get(self.sid, {})
        return (self._cells() != self.cells0 or self.name.text() != meta.get("name", "") or
                self.notes.toPlainText() != meta.get("notes", ""))

    def _edited(self, *_):
        if self._loading:
            return
        self._refresh()

    def _refresh(self):
        sid = self.sid
        if sid is None:
            return
        cells = self._cells()
        van = self._van.get(sid)
        if van is not None:
            a = {(x, y, k) for x, y, k in van.cells}
            b = {(x, y, k) for x, y, k in cells}
            self.grid.diff = {(x, y) for x, y, _ in a ^ b}
            order_changed = [c for c in van.cells if c[2] != sa.USER_TO] != [c for c in cells if c[2] != sa.USER_TO]
        else:
            self.grid.diff = set()
            order_changed = False
        self.grid.update()
        hits = sum(1 for _, _, k in cells if k != sa.USER_TO)
        name = self.name.text().strip()
        self.title.setText(f"Shape {sid}" + (f" · {name}" if name else "") + f"  —  {hits} panel{'s' * (hits != 1)}")
        turns = "turns with the caster" if sa.is_directional(cells) else "the same whichever way the caster faces"
        mine = van is None
        self.sub.setText(("A shape of yours (made with the kit)" if mine else
                          "A game shape" + (" — its panels differ from the game's" if self.grid.diff else
                                            " — the hit order differs from the game's" if order_changed else "")) +
                         f" · {turns} · used by {len(self._users.get(sid, []))} skill(s)")
        dirty = self._dirty()
        self.b_save.setEnabled(dirty)
        self.b_discard.setEnabled(dirty)
        self.b_revert.setEnabled(van is not None and [tuple(c) for c in van.cells] != cells)
        self.b_del.setEnabled(mine and not self._users.get(sid))
        self.state.setText("not saved" if dirty else "")

    def _fill_json(self):
        if self.sid is None:
            return
        self.json.setPlainText(json.dumps({"id": self.sid, "directional": sa.is_directional(self._cells()),
                                           "cells": [list(c) for c in self._cells()]}, indent=1))

    def _apply_json(self):
        try:
            d = json.loads(self.json.toPlainText())
            cells = [tuple(int(v) for v in c) for c in (d["cells"] if isinstance(d, dict) else d)]
            sa._check_cells(cells)
        except Exception as e:
            QMessageBox.warning(self, "JSON", f"That isn't a shape: {e}")
            return
        self.grid.set_cells_from(cells)
        self.tabs.setCurrentIndex(0)

    def _open_skill(self, r):
        if r < 0 or self.users.item(r, 0) is None:
            return
        sid = self.users.item(r, 0).data(ROLE)
        page = self.main.show_page("skills")
        if page is not None and hasattr(page, "open_skill"):
            page.open_skill(sid)

    # ---------------------------------------------------------------- new / clone / delete / save
    def _commit(self, what):
        self.svc.mark_dirty(AM)
        if self.svc.commit(AM, self, suggest="Area shapes", category="skills") is False:
            return False
        self.ws.log(f"{what} saved into {self.svc.saved_text()} — Install to use it in the game")
        return True

    def _save_meta(self, sid, name, notes):
        mod = self.ws.active_mod
        if mod is None:
            return
        d = mod.load_patch("skills", NAMES) or {}
        if name or notes:
            d[str(sid)] = {k: v for k, v in (("name", name), ("notes", notes)) if v}
        else:
            d.pop(str(sid), None)
        mod.save_patch("skills", NAMES, d or None)

    def new_shape(self, cells=None, what="New shape"):
        if self._dirty() and QMessageBox.question(self, "Area Shapes", "Leave the changes of this shape?") != \
                QMessageBox.StandardButton.Yes:
            return
        at = self.svc.table(AM)
        try:
            sid = sa.new_shape(at, list(cells or [(0, 0, sa.CURSOR)]))
        except Exception as e:
            error_box(self, "Area Shapes", e)
            return
        if not self._commit(f"{what} {sid}"):
            return
        self.sid = None
        self._populate(keep=sid)

    def clone_shape(self):
        if self.sid is None:
            return
        self.new_shape(self._cells(), what=f"Copy of shape {self.sid}:")

    def delete_shape(self):
        sid = self.sid
        if sid is None or sid in self._van:
            return
        if self._users.get(sid):
            QMessageBox.information(self, "Delete", "Skills use this shape: give them another one first.")
            return
        if QMessageBox.question(self, "Delete", f"Delete shape {sid}?") != QMessageBox.StandardButton.Yes:
            return
        try:
            sa.delete_shape(self.svc.table(AM), sid)
        except Exception as e:
            error_box(self, "Delete", e)
            return
        if self._commit(f"Shape {sid} deleted;"):
            self._save_meta(sid, "", "")
            self.sid = None
            self._populate()

    def save(self):
        sid = self.sid
        if sid is None:
            return
        cells = self._cells()
        try:
            sa._check_cells(cells)
            if cells != self.cells0:
                sa.store_shape(self.svc.table(AM), sid, cells)
        except Exception as e:
            error_box(self, "Save", e)
            return
        if cells != self.cells0 and not self._commit(f"Shape {sid} ({len(cells)} panels)"):
            return
        if self.ws.active_mod is None and (self.name.text() or self.notes.toPlainText()):
            if hasattr(self.ws, "require_mod") and self.ws.require_mod(self, suggest="Area shapes",
                                                                       category="skills") is None:
                return
        self._save_meta(sid, self.name.text().strip(), self.notes.toPlainText().strip())
        self.cells0 = cells
        self._populate(keep=sid)

    def discard(self):
        if self.sid is None:
            return
        sid, self.sid = self.sid, None
        self.show_shape(sid)

    def revert(self):
        van = self._van.get(self.sid)
        if van is not None:
            self.grid.set_cells_from(van.cells)
