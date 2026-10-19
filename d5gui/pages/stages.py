"""Stages & Maps: stage list, interactive grid editor for enemies / geo panels / base panel."""
import struct

import numpy as np
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QPointF
from PyQt6.QtGui import QColor, QBrush, QPen, QFont, QPainter, QPolygonF
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QComboBox, QGraphicsView, QGraphicsScene, QButtonGroup,
                             QFormLayout, QSpinBox, QLineEdit, QScrollArea, QGroupBox, QMessageBox,
                             QInputDialog, QCompleter, QGridLayout, QApplication, QCheckBox, QStackedWidget,
                             QToolButton, QMenu)

from d5lib import mapfile, pac, mapbuild, enemyitems
from ..common import PageHeader, SearchBox, error_box, info_box
from ..stagebuilder import BuilderPanel, TOOL_PLACE, TOOL_MOVE
from ..dbservice import get_service, char_names, table_names

ROLE = Qt.ItemDataRole.UserRole
CELL = 34
DUNGEON = "dungeon.dat"
NETHER_SKILLS = "MakaiSkillDataBase.dat"
# Netherworld skills that need things of the stage they were made for (its sea, mushroom objects, a laser target,
# reinforcement units, Baal's battle)
NETHER_OWN_STAGE = {1025, 1026, 1027, 1028, 1029, 1030, 2000, 2001, 2003, 2004, 2005, 2010, 2014, 2015, 2016, 2017,
                    2018}
# ... and the ones whose row value is an amount worth changing (%, panels, points)
NETHER_AMOUNT = {1000, 1002, 1003, 1004, 1005, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014, 1015, 1018, 1019,
                 1020, 1021, 1022, 1023, 1024, 2002, 2011, 2012, 2013}
GEO_COLORS = {0: ("none", QColor(0, 0, 0, 0)), 1: ("Red", QColor(230, 40, 40)), 2: ("Green", QColor(40, 200, 60)),
              3: ("Blue", QColor(40, 90, 240)), 4: ("Yellow", QColor(240, 220, 40)),
              5: ("Purple", QColor(170, 60, 220)), 6: ("Cyan", QColor(40, 220, 230))}
TEAMS = {1: "Enemy", 2: "Neutral / object", 3: "Team 3", 4: "Team 4", 5: "Team 5"}
FACING = {0: "↓ 0 (south)", 90: "→ 90", 180: "↑ 180", 270: "← 270"}


_MODEL_CACHE = {}
_TIPS = {}


def set_choice_tips(choices, tips):
    """Hover descriptions {id: rich text} for a shared choice list (skills, evilities, items ...)."""
    _TIPS[id(choices)] = (choices, tips)
    cached = _MODEL_CACHE.get(id(choices))
    if cached is not None and cached[0] is choices:
        _apply_tips(cached[1], tips)


def _apply_tips(model, tips):
    for r in range(model.rowCount()):
        it = model.item(r)
        tip = tips.get(it.data(Qt.ItemDataRole.UserRole))
        if tip:
            it.setData(tip, Qt.ItemDataRole.ToolTipRole)


def choice_model(choices):
    """Shared item model for a list of (id, label) choices. Building a combo from a shared model is
    instant, while adding ~1500 items per combo one by one made forms slow."""
    from PyQt6.QtGui import QStandardItemModel, QStandardItem
    key = id(choices) if not isinstance(choices, tuple) else choices
    cached = _MODEL_CACHE.get(key)
    if cached is not None and cached[0] is choices:
        return cached[1]
    model = QStandardItemModel()
    it = QStandardItem("0 · (none)")
    it.setData(0, Qt.ItemDataRole.UserRole)
    model.appendRow(it)
    for k, v in choices:
        it = QStandardItem(f"{k} · {v}")
        it.setData(k, Qt.ItemDataRole.UserRole)
        model.appendRow(it)
    t = _TIPS.get(id(choices))
    if t is not None and t[0] is choices:
        _apply_tips(model, t[1])
    _MODEL_CACHE[key] = (choices, model)
    return model


class SearchCombo(QComboBox):
    """Editable combo of (id, label) with contains-search. Pass the SAME list object for combos that
    share choices: the item model is built once and shared."""

    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        model = choice_model(choices)
        self.setModel(model)
        comp = QCompleter(model, self)
        comp.setCompletionRole(Qt.ItemDataRole.DisplayRole)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(comp)
        self.setMinimumWidth(180)
        self.setMaxVisibleItems(20)
        comp.popup().setMinimumWidth(320)
        self._value = None                     # the entry chosen last (what a search left unfinished goes back to)
        # hovering the box shows the description of the chosen entry (the list shows each entry's own)
        self.currentIndexChanged.connect(self._update_tip)
        self.currentIndexChanged.connect(self._index_changed)
        self.editTextChanged.connect(self._update_tip)
        from ..common import type_to_search
        type_to_search(self, lambda c: c._restore())

    def _update_tip(self, *_):
        i = self.findText(self.currentText())
        tip = self.itemData(i, Qt.ItemDataRole.ToolTipRole) if i >= 0 else None
        self.setToolTip(tip or "")

    def _index_changed(self, i):
        if i >= 0:
            self._value = self.itemData(i)

    def _restore(self):
        """text naming no entry (a search not finished) -> the chosen entry is shown again"""
        t = self.currentText().strip()
        if self.findText(self.currentText()) < 0 and not t.lstrip("-").split(" ")[0].isdigit():
            self.set_value(self._value if self._value is not None else 0)

    def value(self):
        i = self.findText(self.currentText())
        if i >= 0:
            return self.itemData(i)
        try:
            return int(self.currentText().split(" ")[0])
        except ValueError:                    # a search typed but not chosen: the entry stays as it was
            return self._value if self._value is not None else 0

    def set_value(self, v):
        self._value = v
        if v is None:                          # (several values: the box starts empty)
            self.setCurrentIndex(-1)
            self.setEditText("")
            return
        m = self.model()
        idx = getattr(m, "_d5_index", None)
        if idx is None:  # value -> row map, built once per shared model
            idx = {}
            for r in range(m.rowCount()):
                idx.setdefault(m.item(r).data(Qt.ItemDataRole.UserRole), r)
            m._d5_index = idx
        i = idx.get(v, -1)
        if i >= 0:
            self.setCurrentIndex(i)
            if self.currentText() != self.itemText(i):     # (same entry, a search typed over its name)
                self.setEditText(self.itemText(i))
        else:
            self.setEditText(str(v))


class MapCanvas(QGraphicsView):
    cell_clicked = pyqtSignal(int, int, object)   # x, y, mouse button (keyboard modifiers: self.mods)
    cell_dragged = pyqtSignal(int, int)
    band_selected = pyqtSignal(int, int, int, int, bool)   # x0, y0, x1, y1 panels, add to the selection (Shift+drag)
    key_pressed = pyqtSignal(object)              # a key the page may use (the event; accept it to keep it)
    redrawn = pyqtSignal()                        # after every redraw (the 3D view shows the same map and selection)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(14, 12, 20))
        self.pkg = None
        self.base = None
        self.selected = None                    # the unit the inspector shows (the last one clicked)
        self.multi = set()                      # every selected unit (selected among them); more than one: a group
        self.mods = Qt.KeyboardModifier.NoModifier
        self.band = None                        # (x0, y0, x1, y1) while Shift+dragging a selection box
        self.names = {}
        self.mid = 0
        self._drag = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.visit = mapfile.APPEARS_FIRST      # the visit shown (None = every unit of every visit)

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, v):                      # one unit chosen the usual way: the group is that unit
        self._selected = v
        self.multi = {v} if v is not None else set()

    def select_group(self, members, primary=None):
        members = set(members)
        if primary not in members:
            primary = min(members) if members else None
        self._selected = primary
        self.multi = members

    def visible(self, u):
        return self.visit is None or u.shown_in(self.visit)

    def load(self, pkg, base, names):
        self.pkg, self.base, self.names = pkg, base, names
        self.redraw()

    def redraw(self):
        try:
            self._redraw()
        finally:
            self.redrawn.emit()

    def _redraw(self):
        sc = self.scene()
        sc.clear()
        if not self.pkg:
            return
        hb = self.pkg.hex.blocks[0]
        W, H = hb.width, hb.height
        elev = hb.elevation()
        live = hb.no_panel[:W, :H] == 0
        lo, hi = (elev[live].min(), elev[live].max()) if live.any() else (0, 1)
        rng = max(hi - lo, 1e-6)
        try:
            colors = self.pkg.gop.blocks[0].color_grid(W, H)
        except Exception:
            colors = np.zeros((W, H), np.uint8)
        font = QFont("Segoe UI", 7)
        for x in range(W):
            for y in range(H):
                r = QRectF(x * CELL, y * CELL, CELL, CELL)
                if not live[x, y]:
                    sc.addRect(r, QPen(QColor(30, 28, 40)), QBrush(QColor(18, 16, 24)))
                    continue
                t = (elev[x, y] - lo) / rng
                g = int(70 + 120 * t)
                sc.addRect(r, QPen(QColor(25, 23, 32)), QBrush(QColor(g, g - 6, g + 8)))
                c = int(colors[x, y])
                if c:
                    col = GEO_COLORS.get(c, ("?", QColor(255, 255, 255)))[1]
                    sc.addRect(r.adjusted(5, 5, -5, -5), QPen(Qt.PenStyle.NoPen), QBrush(col))
                if CELL >= 30 and elev[x, y] != lo:
                    tx = sc.addSimpleText(f"{elev[x, y]:.0f}", font)
                    tx.setBrush(QBrush(QColor(255, 255, 255, 70)))
                    tx.setPos(x * CELL + 2, y * CELL + CELL - 12)
        if self.base:
            bx, by = self.base
            sc.addRect(QRectF(bx * CELL + 1, by * CELL + 1, CELL - 2, CELL - 2), QPen(QColor("#4fa3ff"), 3))
            t = sc.addSimpleText("BASE", QFont("Segoe UI", 7, QFont.Weight.Bold))
            t.setBrush(QBrush(QColor("#4fa3ff")))
            t.setPos(bx * CELL + 3, by * CELL + 2)
        stacked = {}
        sets = self.pkg.chr.visit_sets()
        for i, u in enumerate(self.pkg.chr.units):
            if not u.on_map or not self.visible(u):
                continue
            k = stacked[(u.x, u.y)] = stacked.get((u.x, u.y), -1) + 1     # (all visits shown: side by side)
            cx, cy = u.x * CELL + CELL / 2 + 7 * k, u.y * CELL + CELL / 2 + 5 * k
            sel = i == self.selected
            grp = i in self.multi and len(self.multi) > 1
            if grp:                                     # a group member: a gold frame around its panel
                sc.addRect(QRectF(u.x * CELL + 2, u.y * CELL + 2, CELL - 4, CELL - 4), QPen(QColor("#ffd34f"), 2))
            pen = QPen(QColor("#ffffff") if sel else QColor("#ffd34f") if grp else QColor(0, 0, 0),
                       3 if sel or grp else 1)
            if u.is_geo_symbol:
                col = GEO_COLORS.get(u.geo_color if u.size == mapfile.RECORD_SIZE else 0, ("", QColor(240, 240, 240)))[1]
                if col.alpha() == 0:
                    col = QColor(240, 240, 240)
                poly = QPolygonF([QPointF(cx, cy - 12), QPointF(cx + 12, cy), QPointF(cx, cy + 12), QPointF(cx - 12, cy)])
                sc.addPolygon(poly, pen, QBrush(col))
            elif u.is_object:
                sc.addRect(QRectF(cx - 10, cy - 10, 20, 20), pen, QBrush(QColor(150, 150, 150)))
            else:
                team = u.team if u.size == mapfile.RECORD_SIZE else 1
                col = QColor(225, 50, 70) if team == 1 else QColor(80, 170, 255) if team == 2 else QColor(240, 170, 40)
                sc.addEllipse(QRectF(cx - 12, cy - 12, 24, 24), pen, QBrush(col))
                # facing tick
                ang = {0: (0, 1), 90: (1, 0), 180: (0, -1), 270: (-1, 0)}.get(u.facing, (0, 0))
                sc.addLine(cx, cy, cx + ang[0] * 15, cy + ang[1] * 15, QPen(QColor(255, 255, 255), 2))
            label = self.names.get(u.char_id, str(u.char_id)).split(" (")[0][:6]
            t = sc.addSimpleText(label, font)
            t.setBrush(QBrush(QColor(255, 255, 255)))
            t.setPos(cx - 15, cy - 4)
            if sets and self.visit is None and u.appears != mapfile.APPEARS_ALWAYS:
                b = sc.addSimpleText("①" if u.appears == mapfile.APPEARS_FIRST else "②",
                                     QFont("Segoe UI", 8, QFont.Weight.Bold))
                b.setBrush(QBrush(QColor("#ffd34f")))
                b.setPos(cx + 6, cy - 16)
        if self.band:
            x0, y0, x1, y1 = self.band
            sc.addRect(QRectF(min(x0, x1) * CELL, min(y0, y1) * CELL, (abs(x1 - x0) + 1) * CELL,
                              (abs(y1 - y0) + 1) * CELL), QPen(QColor("#ffd34f"), 2, Qt.PenStyle.DashLine),
                       QBrush(QColor(255, 211, 79, 40)))
        sc.setSceneRect(QRectF(-10, -10, W * CELL + 20, H * CELL + 20))

    def _cell(self, e):
        p = self.mapToScene(e.position().toPoint())
        return int(p.x() // CELL), int(p.y() // CELL)

    def mousePressEvent(self, e):
        if not self.pkg:
            return
        self.setFocus()
        x, y = self._cell(e)
        self.mods = e.modifiers()
        if e.button() == Qt.MouseButton.LeftButton and self.mods & Qt.KeyboardModifier.ShiftModifier:
            self.band = (x, y, x, y)                # Shift+drag: a selection box
            self.redraw()
            return
        self._drag = e.button() == Qt.MouseButton.LeftButton
        self.cell_clicked.emit(x, y, e.button())

    def mouseMoveEvent(self, e):
        if self.band and self.pkg:
            x, y = self._cell(e)
            if (x, y) != self.band[2:]:
                self.band = self.band[:2] + (x, y)
                self.redraw()
            return
        if self._drag and self.pkg:
            x, y = self._cell(e)
            self.cell_dragged.emit(x, y)

    def mouseReleaseEvent(self, e):
        self._drag = False
        if self.band:
            x0, y0, x1, y1 = self.band
            self.band = None
            add = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self.band_selected.emit(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), add)

    def keyPressEvent(self, e):
        e.setAccepted(False)
        self.key_pressed.emit(e)
        if not e.isAccepted():
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)


class StagesPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.svc = get_service(ws)
        self.pkg = None
        self.map_vpath = None
        self.stage_row = None
        self.dirty = False
        self._names_loaded = False

        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Stages & Maps",
                                 "Pick a stage to see its battlefield. Move, add or remove enemies, change their "
                                 "class, level, equipment and skills, paint Geo Panels, place Geo Symbols and move "
                                 "the base panel. Clone a stage to start a new level."))
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.search = SearchBox("Search stages…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.stages = QListWidget()
        self.stages.currentItemChanged.connect(self._pick)
        ll.addWidget(self.stages, 1)
        split.addWidget(left)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Pick a stage")
        self.title.setObjectName("cardTitle")
        cl.addWidget(self.title)
        tools = QHBoxLayout()
        self.tool = QButtonGroup(self)
        for i, (name, tip) in enumerate([("🖱 Select / move", "Click a unit to edit it, drag to move it"),
                                         ("➕ Add enemy", "Click an empty panel to place a new enemy"),
                                         ("💎 Add Geo Symbol", "Click a panel to place a Geo Symbol"),
                                         ("🖌 Paint Geo Panel", "Click/drag to paint panel colors"),
                                         ("🏁 Base panel", "Click where your units enter the map")]):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setToolTip(tip)
            self.tool.addButton(b, i)
            tools.addWidget(b)
        self.tool.button(0).setChecked(True)
        self.builder = BuilderPanel(self)
        self.builder.hide()
        self.tool.addButton(self.builder.b_place, TOOL_PLACE)
        self.tool.addButton(self.builder.b_move, TOOL_MOVE)
        self.builder.changed.connect(self._build_changed)
        self.builder.marks_changed.connect(self._marks_changed)
        self.builder.b_done.clicked.connect(lambda: self.b_build.setChecked(False))
        self.build = None
        self.lib = None
        self.paint_color = QComboBox()
        for k, (n, c) in GEO_COLORS.items():
            self.paint_color.addItem("Erase" if k == 0 else n, k)
        self.paint_color.setCurrentIndex(1)
        tools.addWidget(self.paint_color)
        tools.addStretch(1)
        self.b_build = QToolButton()
        self.b_build.setText("🧱 Blocks")
        self.b_build.setCheckable(True)
        self.b_build.setToolTip("Build the battlefield out of blocks: the game's Item World pieces (stone slabs, "
                                "steps, themed tiles) and pieces cut out of any map, placed, turned and lifted on a "
                                "grid. For stages of your own (make one with ➕ New stage… first).")
        self.b_build.toggled.connect(self._build_toggled)
        tools.addWidget(self.b_build)
        self.b_3d = QToolButton()
        self.b_3d.setText("🧊 3D")
        self.b_3d.setCheckable(True)
        self.b_3d.setToolTip("The battlefield as the battle shows it: its terrain, every unit as its sprite, Geo "
                             "Panels and the base panel. Middle button / Alt+drag turns the camera, Shift+middle or "
                             "the right button pans, the wheel zooms, F fits the map. Off: the top-down grid.")
        self.b_3d.toggled.connect(self._view_toggled)
        tools.addWidget(self.b_3d)
        self.b_cam = QToolButton()
        self.b_cam.setText("🎥 View")
        self.b_cam.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        cam = QMenu(self.b_cam)
        cam.addAction("Battle view  (1)", lambda: self.view3d.view_preset("battle"))
        cam.addAction("From above  (7)", lambda: self.view3d.view_preset("top"))
        cam.addAction("Low angle  (3)", lambda: self.view3d.view_preset("low"))
        cam.addAction("Fit the map  (F)", lambda: self.view3d.fit())
        cam.addSeparator()
        a = cam.addAction("Units move (idle)")
        a.setCheckable(True)
        a.setChecked(True)
        a.toggled.connect(lambda on: setattr(self.view3d, "animate", on))
        a = cam.addAction("Names  (N)")
        a.setCheckable(True)
        a.setChecked(True)
        a.toggled.connect(lambda on: (setattr(self.view3d, "show_names", on), self.view3d.update()))
        a = cam.addAction("Panel grid  (G)")
        a.setCheckable(True)
        a.setChecked(True)
        a.toggled.connect(lambda on: (setattr(self.view3d, "show_grid", on), self.view3d.update()))
        self.b_cam.setMenu(cam)
        tools.addWidget(self.b_cam)
        tools.addWidget(QLabel("Show"))
        self.visit_box = QComboBox()
        for v, label in ((mapfile.APPEARS_FIRST, "First visit"), (mapfile.APPEARS_REVISIT, "Revisits"),
                         (None, "All units")):
            self.visit_box.addItem(label, v)
        self.visit_box.setToolTip(
            "Many stages place other units once they are cleared: Dried Up Wasteland has Warriors on the first "
            "visit and Prinnies on the same panels afterwards; Final Trial has 5 flame dragons, then Lucky Boards. "
            "Show the units of one visit to edit it; new units join the visit shown. 'All units' shows both "
            "(① first visit only, ② revisits only).")
        self.visit_box.currentIndexChanged.connect(self._visit_changed)
        tools.addWidget(self.visit_box)
        cl.addLayout(tools)
        self.canvas = MapCanvas()
        self.canvas.cell_clicked.connect(self._click)
        self.canvas.cell_dragged.connect(self._drag)
        self.canvas.band_selected.connect(self._band)
        self.canvas.key_pressed.connect(self._view_key)
        self.views = QStackedWidget()
        self.views.addWidget(self.canvas)
        self.view3d = None
        try:
            from ..stage3d import Stage3DView
            self.view3d = Stage3DView(ws, self.canvas)
            self.view3d.lookup = self._unit_look
            self.view3d.cell_clicked.connect(self._click)
            self.view3d.cell_dragged.connect(self._drag)
            self.view3d.unit_clicked.connect(self._unit_click)
            self.view3d.hover_changed.connect(self.builder.set_hover)
            self.view3d.key_pressed.connect(self._view_key)
            self.canvas.redrawn.connect(self.view3d.sync)
            self.views.addWidget(self.view3d)
        except Exception as e:
            ws.log(f"(3D stage view not available: {e})")
        cl.addWidget(self.views, 1)
        if self.view3d is not None:
            self.b_3d.setChecked(bool(ws.settings.get("stages_3d", True)))
            self._view_toggled(self.b_3d.isChecked())
        else:
            self.b_3d.setEnabled(False)
            self.b_cam.setEnabled(False)
        bot = QHBoxLayout()
        self.b_save = QPushButton("💾 Save")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save)
        bot.addWidget(self.b_save)
        for text, fn, tip in [("Discard changes", self.reload, ""),
                              ("Revert to original", self.revert, "Remove this map's changes from the mod"),
                              ("➕ New stage…", self.new_stage, "A new stage of your own: pick the battlefield it "
                                                                "starts from (pictures of every map), name it, "
                                                                "choose what it starts with"),
                              ("Export 3D model (.obj)…", self.export_obj, "Open the level geometry in Blender etc.")]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bot.addWidget(b)
        bot.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        bot.addWidget(self.status)
        cl.addLayout(bot)
        split.addWidget(center)

        # inspector
        self.insp_scroll = QScrollArea()
        self.insp_scroll.setWidgetResizable(True)
        self.insp = QWidget()
        self.insp_scroll.setWidget(self.insp)
        self.insp_lay = QVBoxLayout(self.insp)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.builder)
        rl.addWidget(self.insp_scroll, 1)
        split.addWidget(right)
        split.setSizes([280, 800, 420])
        lay.addWidget(split, 1)
        self._populated = False
        self._want_map = None
        ws.file_changed.connect(lambda v: v.startswith("Map/") and self.__dict__.pop("_map_cache", None))

    # ================================================================== stage list
    def on_show(self):
        self.__dict__.pop("_song_list", None)       # songs added on Music & Sound since
        if not self._populated:
            self._populated = True
            self._populate()
            if self.stages.currentRow() < 0 and self.stages.count():
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(150, lambda: self.stages.currentRow() < 0 and self.stages.setCurrentRow(0))

    def _load_names(self):
        if self._names_loaded:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.char_names = char_names(self.svc)
            self.__dict__.pop("_look_cache", None)
            self.item_names = table_names(self.svc, "item.dat")
            self.magic_names = table_names(self.svc, "magic.dat")
            self.evility_names = table_names(self.svc, "Skill.dat")
            self.ge_names = table_names(self.svc, "GE.dat")
            # sorted choice lists are built once and shared by every combo (fast inspector)
            self.char_choices = sorted(self.char_names.items())
            self.item_choices = sorted(self.item_names.items())
            self.magic_choices = sorted(self.magic_names.items())
            self.evility_choices = sorted(self.evility_names.items())
            self.ge_choices = sorted(self.ge_names.items())
            for ch, member in ((self.char_choices, "char.dat"), (self.item_choices, "item.dat"),
                               (self.magic_choices, "magic.dat"), (self.evility_choices, "Skill.dat"),
                               (self.ge_choices, "GE.dat")):
                set_choice_tips(ch, self.svc.ref_tooltips(member))
            self._names_loaded = True
        finally:
            QApplication.restoreOverrideCursor()

    def _have_map(self, mid):
        """does the game (or the active mod) have map `mid`?  A few stage rows name maps the PC release doesn't ship
        (Companion Zone (Demo): map00221)"""
        name = f"map{mid:05d}.lzs"
        if not hasattr(self, "_maps_in_game"):
            self._maps_in_game = {n.lower() for n in self.ws.fs.list_members("Map/Map_JP.dat")}
        if name in self._maps_in_game:
            return True
        return any(f.endswith("/" + name) for m in self._map_mods() for f in m.list_files())

    def _map_mods(self):
        """the mods whose maps the editor sees: the active one and every enabled one"""
        ms = list(self.ws.mods.enabled_mods())
        a = self.ws.active_mod
        if a and all(m.id != a.id for m in ms):
            ms.append(a)
        return ms

    def _populate(self):
        self.stages.clear()
        t = self.svc.table(DUNGEON)
        for i, row in enumerate(t.rows):
            rec = mapfile.DungeonRecord(bytes(row.raw))
            have = self._have_map(rec.map_id)
            it = QListWidgetItem(f"{rec.name() or '(unnamed)'}   ·  map{rec.map_id:05d}"
                                 + ("" if have else "   (no map in the game files)"))
            it.setData(ROLE, ("stage", i, rec.map_id))
            it.setToolTip(f"dungeon.dat row {i}, stage #{rec.index}, episode {rec.episode}"
                          + ("" if have else f"<br>The game files have no map{rec.map_id:05d}: a stage entry left "
                                            "over from development (demo / dummy stages), or one whose map the game "
                                            "builds itself."))
            if not have:
                it.setForeground(QBrush(QColor("#8a90b8")))
            self.stages.addItem(it)
        hdr = QListWidgetItem("── maps without a stage entry ──")
        hdr.setFlags(Qt.ItemFlag.NoItemFlags)
        self.stages.addItem(hdr)
        used = {mapfile.DungeonRecord(bytes(r.raw)).map_id for r in t.rows}
        for n in self.ws.fs.list_members("Map/Map_JP.dat"):
            if n.startswith("map") and n[3:8].isdigit() and int(n[3:8]) not in used:
                it = QListWidgetItem(f"map{n[3:8]}")
                it.setData(ROLE, ("map", None, int(n[3:8])))
                self.stages.addItem(it)
        seen = set()
        for m in self._map_mods():
            for f in m.list_files():
                if f.startswith("Map/") and f.count("/") == 2 and f.endswith(".lzs"):
                    mid = int(f.split("/")[-1][3:8])
                    if mid not in used and mid not in seen:
                        seen.add(mid)
                        it = QListWidgetItem(f"map{mid:05d}  (new, in {m.name})")
                        it.setData(ROLE, ("map", None, mid))
                        self.stages.addItem(it)

    def _filter(self, t):
        t = t.lower()
        for i in range(self.stages.count()):
            it = self.stages.item(i)
            if it.data(ROLE):
                it.setHidden(bool(t) and t not in it.text().lower())

    def _pick(self, it, prev=None):
        if not it or not it.data(ROLE):
            return
        if self.dirty:
            r = QMessageBox.question(self, "Unsaved stage", "Save your changes first?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                     QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                self.stages.blockSignals(True)
                self.stages.setCurrentItem(prev)
                self.stages.blockSignals(False)
                return
            if r == QMessageBox.StandardButton.Save:
                self.save()
        kind, row, mid = it.data(ROLE)
        if not self._have_map(mid):
            self.title.setText(f"map{mid:05d} is not in the game files")
            info_box(self, "No map for this stage",
                     f"The game files have no map{mid:05d}, so there is nothing to open. The game has a few stage "
                     "entries like this: left over from its development (demo and dummy stages), or places whose "
                     "map the game builds itself.")
            return
        self.open_map(mid, row)

    # ================================================================== load / save
    def _map_vpath(self, mid):
        name = f"map{mid:05d}.lzs"
        for m in [self.ws.active_mod] * bool(self.ws.active_mod) + list(reversed(self._map_mods())):
            for f in m.list_files():
                if f.endswith("/" + name) and f.count("/") == 2:
                    return f
        try:
            return f"{self.ws.fs.resolve('map', name, self.ws.language)}/{name}"
        except Exception:
            return f"Map/Map_JP.dat/{name}"

    def _read_members(self, vpath):
        """Decompressed pac members (vanilla + mod overrides). Runs in a worker thread; small LRU cache."""
        cache = self.__dict__.setdefault("_map_cache", {})
        if vpath not in cache:
            cache[vpath] = pac.read_pac(self.ws.read(vpath))
            while len(cache) > 4:
                cache.pop(next(iter(cache)))
        return [(n, self.ws.read(f"{vpath}/{n}") if self.ws.is_modified(f"{vpath}/{n}") else d)
                for n, d in cache[vpath]]

    def open_map(self, mid, stage_row=None):
        """Load a map without freezing the window (decompression happens in a background thread)."""
        self._load_names()
        self._want_map = (mid, stage_row)
        if getattr(self, "_map_worker", None) is not None and self._map_worker.isRunning():
            return  # picked up when the running load finishes
        vpath = self._map_vpath(mid)
        self.title.setText(f"Loading map{mid:05d}…")
        from ..common import Worker
        self._map_worker = Worker(lambda: (mid, stage_row, vpath, self._read_members(vpath)))
        self._map_worker.done.connect(self._map_loaded)
        self._map_worker.failed.connect(lambda msg: QMessageBox.critical(self, "Could not open map", msg[:2000]))
        self._map_worker.start()

    def _map_loaded(self, result):
        mid, stage_row, vpath, members = result
        if self._want_map != (mid, stage_row):
            self.open_map(*self._want_map)  # selection changed while loading
            return
        try:
            self.map_vpath = vpath
            self.pkg = mapfile.MapPackage(members, f"map{mid:05d}")
            _ = self.pkg.hex, self.pkg.chr
        except Exception as e:
            self.pkg = None
            error_box(self, "Could not open map", e)
            return
        self.mid = mid
        self.stage_row = stage_row
        self.dirty = False
        self._orig_counts = self._enemy_counts(mid)
        base = None
        name = f"map{mid:05d}"
        if stage_row is not None:
            rec = mapfile.DungeonRecord(bytes(self.svc.table(DUNGEON).rows[stage_row].raw))
            base = (rec.base_x, rec.base_y)
            name = f"{rec.name()}  (map{mid:05d})"
        self.base = base
        self._name = name
        self.canvas.mid = mid
        self.build = None
        in_game = self._in_game(mid)
        owner = None if in_game else self._map_owner()
        if owner is not None:
            self.build = owner.load_patch("stages", f"build_{mid:05d}.json")
        self.b_build.setEnabled(not in_game)
        self.b_build.blockSignals(True)
        self.b_build.setChecked(self.build is not None)
        self.b_build.blockSignals(False)
        self._show_builder(self.build is not None)
        self.canvas.load(self.pkg, base, self.char_names)
        self._title()
        self.canvas.resetTransform()
        r = self.canvas.scene().sceneRect()
        vw, vh = max(1, self.canvas.viewport().width()), max(1, self.canvas.viewport().height())
        z = min(1.6, vw / r.width(), vh / r.height())
        self.canvas.scale(z, z)
        self.canvas.selected = None
        self._inspect(None)
        self._set_status()
        self._history_reset()
        self.terrain_missing = False
        if self.build is not None:
            if self.lib is None:
                self.lib = mapbuild.Library(self._read_pkg)
            self._use_terrain(mid, owner)
            self.builder.set_terrain_missing(self.terrain_missing)
            if mapbuild.outdated(self.build):
                # built with an older kit: the pieces were lit for the Item World (dark on a stage)
                if self.terrain_missing:
                    n = mapbuild.relight(self.pkg)
                    self.build["version"] = mapbuild.VERSION
                    if n:
                        self.pkg.rev = getattr(self.pkg, "rev", 0) + 1
                        self._set_dirty()
                        self.canvas.load(self.pkg, self.base, self.char_names)
                else:
                    self.recompose()
                self.ws.log(f"map{mid:05d}: its blocks now get a story stage's light (they came out dark in "
                            "game). Save to keep it.")

    # ---- the terrain a build started from ("this terrain as one block")
    def _terrain_path(self, mod, mid):
        import os
        return os.path.join(mod.patches_dir, "stages", mapbuild.terrain_name(mid))

    def _set_terrain(self, mid, pkg):
        """the build of map `mid` cuts its own map's block out of `pkg` (in the library; the cut-out redone)"""
        self.lib.pkgs[int(mid)] = pkg
        for k in [k for k in self.lib.pieces if isinstance(k, tuple) and k[0] == int(mid)]:
            del self.lib.pieces[k]

    def _save_terrain(self, mod, mid, pkg):
        import os
        p = self._terrain_path(mod, mid)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(pkg.to_pac())

    def _use_terrain(self, mid, owner):
        """a build that cuts its own map: read the cut-out from the terrain kept beside the build.  Builds of older
        kits have none: when nothing is placed on the cut-out yet the saved map is that terrain; otherwise it is
        missing (the map it started from can be picked with 'Original terrain…')"""
        self.terrain_missing = False
        if self.build is None or owner is None or not mapbuild.self_cut(self.build, mid):
            return
        import os
        p = self._terrain_path(owner, mid)
        if os.path.exists(p):
            with open(p, "rb") as f:
                self._set_terrain(mid, mapfile.MapPackage(pac.read_pac(f.read()), f"map{mid:05d}"))
            return
        if mapbuild.only_self(self.build, mid):
            snap = mapfile.MapPackage([(n, bytes(d)) for n, d in self.pkg.members], self.pkg.name)
            self._save_terrain(owner, mid, snap)
            self._set_terrain(mid, snap)
            return
        self.terrain_missing = True
        self.ws.log(f"map{mid:05d}: this build started from the map itself, and the terrain it started from "
                    "wasn't kept (older kit): blocks placed before may show twice when it is rebuilt. Blocks › "
                    "'Original terrain…' picks the map it was made from.")

    def pick_terrain(self):
        """'Original terrain…': the map an older build started from (its own map's block is cut out of that)"""
        if self.build is None or not self.pkg:
            return
        owner = self._map_owner()
        if owner is None:
            return
        cut = next((mapbuild.key_of(p["piece"]) for p in self.build["pieces"]
                    if isinstance(mapbuild.key_of(p["piece"]), tuple) and mapbuild.key_of(p["piece"])[0] == self.mid),
                   None)
        stages = [s for s in self._stage_choices() if self._in_game(s[1])]
        labels = [f"{n}  (map{m:05d})" for n, m, _ in stages]
        choice, ok = QInputDialog.getItem(
            self, "Original terrain", "This stage was made from the terrain of (the map you picked in New stage):",
            labels, 0, False)
        if not ok:
            return
        mid = stages[labels.index(choice)][1]
        try:
            src = self._read_pkg(mid)
            hb = src.hex.blocks[0]
            if cut is not None and (cut[3] > hb.width or cut[4] > hb.height):
                raise ValueError(f"map{mid:05d} is {hb.width}×{hb.height}: smaller than the cut-out "
                                 f"({cut[3]}×{cut[4]})")
            snap = mapfile.MapPackage([(n, bytes(d)) for n, d in src.members], f"map{self.mid:05d}")
            self._save_terrain(owner, self.mid, snap)
            self._set_terrain(self.mid, snap)
        except Exception as e:
            error_box(self, "Original terrain", e)
            return
        self.terrain_missing = False
        self.builder.set_terrain_missing(False)
        self.recompose()
        self.ws.log(f"map{self.mid:05d}: rebuilt on the terrain of map{mid:05d}. Save to keep it.")

    def _map_owner(self):
        """the mod that has this map (a new map, or changed members of a game map); the active mod first"""
        for m in [self.ws.active_mod] * bool(self.ws.active_mod) + list(reversed(self._map_mods())):
            if any(f == self.map_vpath or f.startswith(self.map_vpath + "/") for f in m.list_files()):
                return m
        return None

    def _is_modified(self):
        return self._map_owner() is not None

    def counts(self, visit):
        """(enemies, Geo Symbols, other objects) placed on a visit"""
        us = self.pkg.chr.placed(visit)
        en = sum(1 for u in us if not u.is_object and (u.size != mapfile.RECORD_SIZE or u.team == 1))
        gs = sum(1 for u in us if u.is_geo_symbol)
        return en, gs, len(us) - en - gs

    def _title(self):
        if not self.pkg:
            return
        hb = self.pkg.hex.blocks[0]
        parts = []
        for v, lab in ((mapfile.APPEARS_FIRST, "first visit"), (mapfile.APPEARS_REVISIT, "revisits")):
            en, gs, _ = self.counts(v)
            parts.append(f"{lab}: {en} enemies, {gs} Geo Symbols")
        sets = self.pkg.chr.visit_sets()
        self.title.setText(f"{self._name}  —  {hb.width}×{hb.height}  ·  "
                           + ("  ·  ".join(parts) if sets else parts[0].split(": ", 1)[1] + " (every visit)")
                           + ("   ✏ modified" if self._is_modified() else ""))

    def _enemy_counts(self, mid):
        """{visit: enemies placed} of the game's own map (else of the map as loaded): a visit that had enemies
        and has none left is worth a warning, one that never had any (a stage played once) is not"""
        chrf = self.pkg.chr
        if self._in_game(mid):
            try:
                van = dict(pac.read_pac(self.ws.fs.read(self.map_vpath)))
                chrf = mapfile.ChrFile(van[self.pkg.member_name("chr")])
            except Exception:
                pass
        return {v: sum(1 for u in chrf.placed(v) if not u.is_object and
                       (u.size != mapfile.RECORD_SIZE or u.team == 1))
                for v in (mapfile.APPEARS_FIRST, mapfile.APPEARS_REVISIT)}

    def reload(self):
        if self.pkg:
            self.dirty = False
            self.svc.discard(DUNGEON)
            if self.svc.is_dirty(NETHER_SKILLS):
                self.svc.discard(NETHER_SKILLS)
            self.open_map(self.mid, self.stage_row)

    def _set_dirty(self):
        self.dirty = True
        self._set_status()
        self._history_push()

    def _set_status(self):
        self.status.setText("● unsaved changes" if self.dirty else "")

    def problems(self):
        """[text] of what would go wrong in game with the map as it is (checked before saving)"""
        out = []
        chrf = self.pkg.chr
        hb = self.pkg.hex.blocks[0]
        orig = getattr(self, "_orig_counts", {})
        for visit, label in ((mapfile.APPEARS_FIRST, "the first visit"), (mapfile.APPEARS_REVISIT, "revisits")):
            units = chrf.placed(visit)
            enemies = [u for u in units if not u.is_object and (u.size != mapfile.RECORD_SIZE or u.team == 1)]
            if not enemies and orig.get(visit, 0):
                out.append(f"No enemy is placed on {label}: the battle is won the moment it starts. (Show: "
                           f"{'First visit' if visit == mapfile.APPEARS_FIRST else 'Revisits'}, then add enemies "
                           "or set 'Appears on' of some to 'Every visit'.)")
            spots = {}
            for u in units:
                if not u.on_map:
                    continue
                if not hb.has_panel(u.x, u.y):
                    out.append(f"{self.char_names.get(u.char_id, u.char_id)} (unit #{u.slot}) stands at "
                               f"{u.x}, {u.y}: there is no panel there, the game leaves it out.")
                spots.setdefault((u.x, u.y), []).append(u)
            for (x, y), us in spots.items():
                if len(us) > 1:
                    out.append(f"On {label}, {len(us)} units share the panel {x}, {y} "
                               f"({', '.join(str(self.char_names.get(u.char_id, u.char_id)) for u in us)}).")
            if self.base and self.base in spots:
                out.append(f"On {label}, a unit stands on the base panel {self.base[0]}, {self.base[1]}: your "
                           "army can't come out.")
        if len(chrf.units) > 255:
            out.append(f"The map has {len(chrf.units)} units; the game reads the first 255.")
        return list(dict.fromkeys(out))

    def save(self):
        if not self.pkg:
            return
        bad = self.problems()
        if bad:
            text = "In game:\n\n• " + "\n• ".join(bad[:8]) + ("\n…" if len(bad) > 8 else "")
            r = QMessageBox.warning(self, "Save the stage?", text + "\n\nSave anyway?",
                                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Save:
                return
        mod = self._map_owner() or self.ws.require_mod(self)
        if not mod:
            return
        try:
            self.pkg.commit()
            # units wearing items of a set rarity: the install patches the game's spawn for them (enemyitems)
            enemyitems.note_map(mod, self.mid, any(u.has_set_rarity for u in self.pkg.chr.units))
            if not self._in_game(self.mid):          # a map of a mod: its whole file, in its mod
                for f in list(mod.list_files()):
                    if f.startswith(self.map_vpath + "/"):  # (members saved separately by older kits)
                        mod.remove_file(f)
                self.ws.write(self.map_vpath, self.pkg.to_pac(), self, mod=mod)
                if self.build is not None:
                    mod.save_patch("stages", f"build_{self.mid:05d}.json", self.build)
                if self.stage_row is not None and self.svc.is_dirty(DUNGEON):
                    self.svc.commit(DUNGEON, self)
                if self.svc.is_dirty(NETHER_SKILLS):
                    self.svc.commit(NETHER_SKILLS, self, into=mod)
                self.dirty = False
                self._set_status()
                self.ws.log(f"Saved map{self.mid:05d} to mod '{mod.name}'")
                return
            for ext in ("chr", "gop", "hex"):
                n = self.pkg.member_name(ext)
                if not n:
                    continue
                data = self.pkg.get(ext)
                vp = f"{self.map_vpath}/{n}"
                orig = None
                try:
                    orig = dict(pac.read_pac(self.ws.fs.read(self.map_vpath))).get(n)
                except Exception:
                    pass
                if orig == data:
                    mod.remove_file(vp)
                else:
                    self.ws.write(vp, data, self, mod=mod)
            if self.stage_row is not None and self.svc.is_dirty(DUNGEON):
                self.svc.commit(DUNGEON, self)
            if self.svc.is_dirty(NETHER_SKILLS):
                self.svc.commit(NETHER_SKILLS, self, into=mod)
            self.dirty = False
            self._set_status()
            self.ws.log(f"Saved map{self.mid:05d} to mod '{mod.name}'")
        except Exception as e:
            error_box(self, "Save failed", e)

    def _in_game(self, mid):
        self._have_map(mid)
        return f"map{mid:05d}.lzs" in self._maps_in_game

    def revert(self):
        mod = self._map_owner() if self.pkg else None
        if mod is None:
            return
        if not self._in_game(self.mid):
            QMessageBox.information(self, "Revert", "This map is a new one of the mod: there is no original to go "
                                    "back to. (Discard changes reloads what was saved.)")
            return
        for f in list(mod.list_files()):
            if f.startswith(self.map_vpath + "/"):
                mod.remove_file(f)
        self.dirty = False
        self.open_map(self.mid, self.stage_row)

    # ================================================================== editing
    def _unit_at(self, x, y, visits=None):
        """the unit at a panel among those shown (or placed on `visits`); clicking a panel where several stand
        (All units) picks the next one each time"""
        units = self.pkg.chr.units
        here = [i for i, u in enumerate(units) if u.x == x and u.y == y and
                (self.canvas.visible(u) if visits is None else any(u.shown_in(v) for v in visits))]
        if not here:
            return None
        cur = self.canvas.selected
        if cur in here and visits is None:
            return here[(here.index(cur) + 1) % len(here)]
        return here[0]

    def _occupied(self, x, y, appears, skip=None):
        """does a unit stand on the panel on a visit where a unit with `appears` would be placed too?"""
        visits = ([mapfile.APPEARS_FIRST, mapfile.APPEARS_REVISIT] if appears == mapfile.APPEARS_ALWAYS
                  else [appears])
        return any(i != skip and u.x == x and u.y == y and any(u.shown_in(v) for v in visits)
                   for i, u in enumerate(self.pkg.chr.units))

    def _new_appears(self):
        """the visit a new unit joins: the one shown on a map with sets of its own, else every visit"""
        v = self.canvas.visit
        return v if v is not None and self.pkg.chr.visit_sets() else mapfile.APPEARS_ALWAYS

    def _visit_changed(self, *_):
        self.canvas.visit = self.visit_box.currentData()
        if self.pkg is None:
            return
        if self.canvas.selected is not None and not self.canvas.visible(self.pkg.chr.units[self.canvas.selected]):
            self.canvas.selected = None
        self.canvas.redraw()
        self._inspect(self.canvas.selected)
        self._title()

    def _in_grid(self, x, y):
        hb = self.pkg.hex.blocks[0]
        return 0 <= x < hb.width and 0 <= y < hb.height

    def _view_toggled(self, on):
        if self.view3d is None:
            return
        self.views.setCurrentWidget(self.view3d if on else self.canvas)
        self.b_cam.setVisible(on)
        if self.ws.settings.get("stages_3d") != on:
            self.ws.settings["stages_3d"] = on
            try:
                self.ws.save_settings()
            except Exception:
                pass
        if on:
            self.view3d.sync()

    # ================================================================== building out of blocks
    def _read_pkg(self, mid):
        return mapfile.MapPackage(self._read_members(self._map_vpath(mid)), f"map{mid:05d}")

    def _stage_choices(self):
        """[(name, map id, row)] of the maps a block can be cut from (the game's stages and your own)"""
        self._load_names()
        out = []
        for i, row in enumerate(self.svc.table(DUNGEON).rows):
            rec = mapfile.DungeonRecord(bytes(row.raw))
            if rec.map_id >= 100 and self._have_map(rec.map_id):
                out.append((rec.name() or f"map{rec.map_id:05d}", rec.map_id, i))
        return out

    def _map_size(self, mid):
        try:
            hb = self._read_pkg(mid).hex.blocks[0]
            return hb.width, hb.height
        except Exception:
            return None

    def _show_builder(self, on):
        self.builder.setVisible(on)
        if on:
            if self.lib is None:
                self.lib = mapbuild.Library(self._read_pkg)
            import os
            self.builder.set_build(self.build, self.lib, os.path.join(self.ws.game_dir, "Data"))
            self.builder._tool(TOOL_PLACE)
            if self.view3d is not None:
                self.b_3d.setChecked(True)
        else:
            if self.tool.checkedId() >= TOOL_PLACE:
                self.tool.button(0).setChecked(True)
        self._marks_changed()

    def _build_toggled(self, on):
        if not self.pkg:
            self.b_build.setChecked(False)
            return
        if on and self.build is None:
            if self._in_game(self.mid):
                self.b_build.setChecked(False)
                QMessageBox.information(self, "Blocks", "Make a stage of your own first (➕ New stage…), then build "
                                                        "its battlefield.")
                return
            box = QMessageBox(self)
            box.setWindowTitle("Build this battlefield")
            box.setText("Start from this map's terrain as one block (cut it, add to it), or from an empty grid?")
            keep = box.addButton("This terrain as one block", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("An empty grid", QMessageBox.ButtonRole.ActionRole)
            cancel = box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is cancel:
                self.b_build.setChecked(False)
                return
            hb = self.pkg.hex.blocks[0]
            if box.clickedButton() is keep:
                self.build = mapbuild.whole_map_build(self.pkg, self.mid)
                # the terrain as it is becomes a cut-out of the saved map: save first so the cut-out reads it
                if self.dirty or self._map_owner() is None:
                    self.save()
                if self.lib is None:
                    self.lib = mapbuild.Library(self._read_pkg)
                snap = mapfile.MapPackage([(n, bytes(d)) for n, d in self.pkg.members], self.pkg.name)
                owner = self._map_owner()
                if owner is not None:                   # kept beside the build: the map file changes with saves
                    self._save_terrain(owner, self.mid, snap)
                self._set_terrain(self.mid, snap)
            else:
                self.build = mapbuild.empty_build(hb.width, hb.height)
            self.ws.log(f"map{self.mid:05d}: building out of blocks ({len(self.build['pieces'])} to start with)")
        self._show_builder(on and self.build is not None)
        if on and self.build is not None and not self.build["pieces"]:
            self.recompose()

    def recompose(self):
        """the map's terrain from the build (its units and Geo Panels stay)"""
        import os
        if self.build is None or not self.pkg:
            return
        try:
            pieces = self.lib.for_build(self.build)
            owner = self._map_owner()
            pics = os.path.join(owner.patches_dir, "stages", mapbuild.PICTURES) if owner else None
            new = mapbuild.compose(self.build, pieces, self.lib.skeleton(), base_pkg=self.pkg, name=self.pkg.name,
                                   pictures_dir=pics)
        except Exception as e:
            error_box(self, "Blocks", e)
            return
        self.build["version"] = mapbuild.VERSION
        for ext in ("hex", "obf", "gop"):
            self.pkg.set(ext, new.get(ext))
        self.pkg.rev = getattr(self.pkg, "rev", 0) + 1
        self._set_dirty()
        self.canvas.load(self.pkg, self.base, self.char_names)
        self._title()

    def _build_changed(self):
        self.recompose()
        self.builder._set_status()
        self._marks_changed()

    def _marks_changed(self):
        if self.view3d is not None:
            self.view3d.marks = self.builder.marks() if self.builder.isVisible() else {}
            self.view3d.update()

    def _view_key(self, e):
        if self.builder.isVisible() and self.builder.key(e):
            e.accept()
            return
        if self.pkg and self._selection_key(e):
            e.accept()

    def _selection_key(self, e):
        """keys of the unit tools: Delete, Ctrl+A / D / Z / Y, Esc, the arrows (move the selection one panel)"""
        k, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if ctrl and k == Qt.Key.Key_Z:
            self.undo()
        elif ctrl and k == Qt.Key.Key_Y:
            self.redo()
        elif self.tool.checkedId() != 0:
            return False
        elif ctrl and k == Qt.Key.Key_A:
            self.select_all()
        elif k == Qt.Key.Key_Escape:
            self.canvas.selected = None
            self._after_selection()
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.canvas.multi:
            self._delete_selection()
        elif ctrl and k == Qt.Key.Key_D and self.canvas.multi:
            self._dup_selection()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) and self.canvas.multi:
            dx, dy = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1),
                      Qt.Key.Key_Down: (0, 1)}[k]
            if not self._move_selection(dx, dy):
                self.ws.log("Can't move the selection there (off the map, a hole, or another unit's panel).")
        else:
            return False
        return True

    def _unit_look(self, u):
        """what a unit of the map is drawn with in the 3D view: (sprite number, palette), or ("model", obf name)
        for a map object whose sprite number is in MapObjectTableDataBase (cacti, boxes, pillars: 3D models;
        treasure chests, barrels and Geo Symbols are sprites)"""
        cache = self.__dict__.setdefault("_look_cache", {})
        if not cache:
            try:
                for r in self.svc.table("char.dat").rows:
                    cache[int(r["id"])] = (int(r["sprite_id"] or 0), int(r["body_type"] or 0))
            except Exception:
                pass
            models = cache.setdefault("models", {})
            try:
                for r in self.svc.table("MapObjectTableDataBase.dat").rows:
                    models[int(r["unk_008"])] = str(r["obf_name"])
            except Exception:
                pass
        hit = cache.get(u.char_id)
        if not hit:
            return None
        num, body = hit
        if not num:
            return None
        if u.is_geo_symbol:                           # the six Geo Symbol models, one per colour (chw00001-6)
            c = u.geo_color if u.size == mapfile.RECORD_SIZE else 1
            return "model", f"chw{min(max(int(c), 1), 6):05d}"
        if body == 2 and num in cache["models"]:
            return "model", cache["models"][num]
        v = u.color_variant if u.size == mapfile.RECORD_SIZE else 0
        return num, (int(v) if 0 <= v < 16 else 0)

    def _unit_click(self, idx, button):
        """a click on a unit's sprite in the 3D view: select it (the select tool), or act on its panel"""
        if not self.pkg or not (0 <= idx < len(self.pkg.chr.units)):
            return
        u = self.pkg.chr.units[idx]
        if self.tool.checkedId() == 0:
            self._pick_unit(idx)
            self._drag_from = idx
            self._drag_cell = (u.x, u.y)
            self._after_selection()
        else:
            self._click(u.x, u.y, button)

    # ---- the selection (one unit, or a group)
    def _pick_unit(self, idx):
        """a click on unit `idx` (None: an empty panel): Ctrl adds / takes it out, a click on a member of the
        group keeps the group (to drag it), else it is the only one selected"""
        ctrl = bool(self.canvas.mods & Qt.KeyboardModifier.ControlModifier)
        group = set(self.canvas.multi)
        if ctrl:
            if idx is None:
                return
            if idx in group:
                group.discard(idx)
                self.canvas.select_group(group, self.canvas.selected if self.canvas.selected != idx else None)
            else:
                group.add(idx)
                self.canvas.select_group(group, idx)
        elif idx is not None and idx in group and len(group) > 1:
            self.canvas.select_group(group, idx)
        else:
            self.canvas.selected = idx

    def _after_selection(self):
        self.canvas.redraw()
        self._inspect(self.canvas.selected)

    def _band(self, x0, y0, x1, y1, add):
        if not self.pkg or self.tool.checkedId() != 0:
            return
        inside = {i for i, u in enumerate(self.pkg.chr.units)
                  if u.on_map and self.canvas.visible(u) and x0 <= u.x <= x1 and y0 <= u.y <= y1}
        group = (set(self.canvas.multi) | inside) if add else inside
        self.canvas.select_group(group, self.canvas.selected if self.canvas.selected in group else None)
        self._after_selection()
        if len(group) > 1:
            self.ws.log(f"{len(group)} units selected: drag one to move them all, the arrows nudge them, Delete "
                        "removes them; the panel on the right edits them together.")

    def select_all(self):
        if not self.pkg:
            return
        group = {i for i, u in enumerate(self.pkg.chr.units) if u.on_map and self.canvas.visible(u)}
        self.canvas.select_group(group)
        self._after_selection()

    def select_like(self, what):
        """every unit shown like the inspected one: 'class' (same class / character), 'team', 'enemies'"""
        units = self.pkg.chr.units
        ref = units[self.canvas.selected] if self.canvas.selected is not None else None
        shown = [i for i, u in enumerate(units) if u.on_map and self.canvas.visible(u)]
        if what == "enemies":
            group = {i for i in shown if not units[i].is_object and
                     (units[i].size != mapfile.RECORD_SIZE or units[i].team == 1)}
        elif ref is None:
            return
        elif what == "class":
            group = {i for i in shown if units[i].char_id == ref.char_id}
        else:
            group = {i for i in shown if units[i].size == mapfile.RECORD_SIZE and ref.size == mapfile.RECORD_SIZE
                     and units[i].team == ref.team}
        self.canvas.select_group(group, self.canvas.selected)
        self._after_selection()

    def _move_selection(self, dx, dy):
        """move every selected unit by (dx, dy) panels: all of them, or none (a hole, the edge, another unit)"""
        units = self.pkg.chr.units
        group = [i for i in self.canvas.multi if 0 <= i < len(units) and units[i].on_map]
        if not group or (dx, dy) == (0, 0):
            return False
        hb = self.pkg.hex.blocks[0]
        for i in group:
            u = units[i]
            x, y = u.x + dx, u.y + dy
            if not self._in_grid(x, y) or not hb.has_panel(x, y):
                return False
            visits = ([mapfile.APPEARS_FIRST, mapfile.APPEARS_REVISIT] if u.appears == mapfile.APPEARS_ALWAYS
                      else [u.appears])
            for j, v in enumerate(units):
                if j not in self.canvas.multi and v.x == x and v.y == y and any(v.shown_in(w) for w in visits):
                    return False
        for i in group:
            units[i].x += dx
            units[i].y += dy
        self._set_dirty()
        self.canvas.redraw()
        self._inspect(self.canvas.selected)
        return True

    def _delete_selection(self):
        idx = sorted(self.canvas.multi, reverse=True)
        if len(idx) > 1 and QMessageBox.question(self, "Delete units", f"Delete the {len(idx)} selected units?") \
                != QMessageBox.StandardButton.Yes:
            return
        for i in idx:
            if 0 <= i < len(self.pkg.chr.units):
                del self.pkg.chr.units[i]
        self.canvas.selected = None
        self._set_dirty()
        self.canvas.redraw()
        self._inspect(None)
        self._title()

    def _dup_selection(self):
        """copies of the selected units, the whole group shifted to the nearest free place"""
        units = self.pkg.chr.units
        group = [i for i in sorted(self.canvas.multi) if 0 <= i < len(units) and units[i].on_map]
        if not group:
            return
        if len(group) == 1:
            self._dup(group[0])
            return
        hb = self.pkg.hex.blocks[0]
        taken = {(u.x, u.y) for u in units}
        for d in range(1, 12):
            for dx, dy in [(d, 0), (0, d), (-d, 0), (0, -d), (d, d), (-d, -d), (d, -d), (-d, d)]:
                spots = [(units[i].x + dx, units[i].y + dy) for i in group]
                if all(self._in_grid(x, y) and hb.has_panel(x, y) and (x, y) not in taken for x, y in spots):
                    n0 = len(units)
                    for i, (x, y) in zip(group, spots):
                        u = units[i]
                        self.pkg.chr.add_unit(u.char_id, x, y, u.level, template=u, appears=u.appears)
                    self.canvas.select_group(range(n0, len(self.pkg.chr.units)))
                    self._set_dirty()
                    self._after_selection()
                    self._title()
                    return
        QMessageBox.information(self, "Duplicate", "No free place for a copy of the whole group nearby.")

    # ---- undo / redo (units and Geo Panels of the open map)
    def _snapshot(self):
        try:
            self.pkg.commit()
            return (self.pkg.get("chr"), self.pkg.get("gop"))
        except Exception:
            return None

    def _history_reset(self):
        self._undo, self._redo = [], []
        self._last_snap = self._snapshot() if self.pkg else None

    def _history_push(self):
        if not self.pkg or getattr(self, "_restoring", False):
            return
        snap = self._snapshot()
        last = getattr(self, "_last_snap", None)
        if snap is None or snap == last:
            return
        if last is not None:
            self._undo.append(last)
            del self._undo[:-100]
        self._redo = []
        self._last_snap = snap

    def _restore(self, snap):
        self._restoring = True
        try:
            chr_b, gop_b = snap
            self.pkg.set("chr", chr_b)
            self.pkg.set("gop", gop_b)
            self._last_snap = snap
            n = len(self.pkg.chr.units)
            keep = {i for i in self.canvas.multi if i < n}
            self.canvas.select_group(keep, self.canvas.selected if self.canvas.selected in keep else None)
            self.dirty = True
            self._set_status()
            self.canvas.redraw()
            self._inspect(self.canvas.selected)
            self._title()
        finally:
            self._restoring = False

    def undo(self):
        if not self.pkg or not getattr(self, "_undo", None):
            return
        self._redo.append(self._last_snap)
        self._restore(self._undo.pop())

    def redo(self):
        if not self.pkg or not getattr(self, "_redo", None):
            return
        self._undo.append(self._last_snap)
        self._restore(self._redo.pop())

    def _click(self, x, y, button):
        if not self.pkg or not self._in_grid(x, y):
            return
        tool = self.tool.checkedId()
        if tool >= TOOL_PLACE:
            self.builder.click(x, y, button)
            return
        if tool == 0:
            self._pick_unit(self._unit_at(x, y))
            self._drag_from = self.canvas.selected
            self._drag_cell = (x, y)
            self._inspect(self.canvas.selected)
        elif tool in (1, 2):
            appears = self._new_appears()
            if self._occupied(x, y, appears):
                return
            if tool == 1:
                tmpl = next((u for u in self.pkg.chr.units if not u.is_object and u.size == mapfile.RECORD_SIZE
                             and self.canvas.visible(u)), None) or                     next((u for u in self.pkg.chr.units if not u.is_object and u.size == mapfile.RECORD_SIZE), None)
                self.pkg.chr.add_unit(tmpl.char_id if tmpl else 1010, x, y, tmpl.level if tmpl else 1,
                                      template=tmpl, appears=appears)
            else:
                tmpl = next(iter(self.pkg.chr.geo_symbols()), None)
                if tmpl is None:
                    self.pkg.chr.add_unit(4810, x, y, 1, template=None, appears=appears, team=2, ai=-1,
                                          geo_color=1, geo_effect=1)
                else:
                    self.pkg.chr.add_unit(tmpl.char_id, x, y, tmpl.level, template=tmpl, appears=appears)
            self.canvas.selected = len(self.pkg.chr.units) - 1
            self._inspect(self.canvas.selected)
            self._set_dirty()
            self.tool.button(0).setChecked(True)
        elif tool == 3:
            self._paint(x, y)
        elif tool == 4:
            if self.stage_row is None:
                QMessageBox.information(self, "Base panel", "This map has no stage entry, so it has no base panel.")
                return
            row = self.svc.table(DUNGEON).rows[self.stage_row]
            row.raw[0x36], row.raw[0x37] = x, y
            self.svc.mark_dirty(DUNGEON)
            self.base = (x, y)
            self.canvas.base = self.base
            self._set_dirty()
        self.canvas.redraw()

    def _drag(self, x, y):
        tool = self.tool.checkedId()
        if not self._in_grid(x, y):
            return
        if tool == TOOL_MOVE:
            self.builder.drag(x, y)
            return
        if tool == 3:
            self._paint(x, y)
            self.canvas.redraw()
        elif tool == 0 and len(self.canvas.multi) > 1 and getattr(self, "_drag_from", None) in self.canvas.multi:
            lx, ly = getattr(self, "_drag_cell", (x, y))      # the whole group follows the unit dragged
            if (x, y) != (lx, ly) and self._move_selection(x - lx, y - ly):
                self._drag_cell = (x, y)
        elif tool == 0 and self.canvas.selected is not None:
            u = self.pkg.chr.units[self.canvas.selected]
            if (u.x, u.y) != (x, y) and not self._occupied(x, y, u.appears, skip=self.canvas.selected):
                u.x, u.y = x, y
                self._set_dirty()
                self.canvas.redraw()
                self._inspect(self.canvas.selected)

    def _paint(self, x, y):
        gb = self.pkg.gop.blocks[0]
        hb = self.pkg.hex.blocks[0]
        grid = gb.color_grid(hb.width, hb.height)
        c = self.paint_color.currentData()
        if grid[x, y] != c:
            grid[x, y] = c
            gb.set_color_grid(grid)
            self._set_dirty()

    # ================================================================== inspector
    def _clear_inspector(self):
        while self.insp_lay.count():
            w = self.insp_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _stage_twins(self, rec):
        """[(name, map id)] of the other stages of the same place (its '(Demo)' version: the story's first visit)"""
        base = rec.name().replace("(Demo)", "").strip()
        out = []
        for i, row in enumerate(self.svc.table(DUNGEON).rows):
            if i == self.stage_row:
                continue
            r = mapfile.DungeonRecord(bytes(row.raw))
            if r.name().replace("(Demo)", "").strip() == base and r.map_id != rec.map_id and "Stage" not in base:
                out.append((r.name(), r.map_id))
        return out

    def _inspect(self, idx):
        self._clear_inspector()
        if self.pkg and len(self.canvas.multi) > 1:
            self._inspect_group()
            return
        if idx is None or not self.pkg:
            box = QGroupBox("Stage")
            f = QFormLayout(box)
            f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            if self.stage_row is not None:
                row = self.svc.table(DUNGEON).rows[self.stage_row]
                rec = mapfile.DungeonRecord(bytes(row.raw))
                name = QLineEdit(rec.name())
                name.editingFinished.connect(lambda: self._set_stage_name(name.text()))
                f.addRow("Stage name (EN)", name)
                f.addRow("Map file", QLabel(f"map{rec.map_id:05d}"))
                f.addRow("Base panel", QLabel(f"{rec.base_x}, {rec.base_y}  (use 🏁 tool)"))
                twins = self._stage_twins(rec)
                if twins:
                    note = QLabel("The story also plays this place as " + ", ".join(
                        f"<b>{n}</b> (map{m:05d})" for n, m in twins) + ": a stage of its own, with its own map, "
                        "enemies and base panel. Change it there too if that's the battle you're testing.")
                    note.setWordWrap(True)
                    note.setObjectName("muted")
                    f.addRow(note)
            else:
                f.addRow(QLabel("This map isn't listed as a stage."))
            vis = QLabel()
            vis.setWordWrap(True)
            rows = []
            for v, lab in ((mapfile.APPEARS_FIRST, "First visit"), (mapfile.APPEARS_REVISIT, "Revisits")):
                en, gs, ob = self.counts(v)
                rows.append(f"<b>{lab}</b>: {en} enemies, {gs} Geo Symbols, {ob} objects")
            vis.setText(("This stage places other units once it is cleared. Switch <b>Show</b> above the map "
                         "to edit each visit.<br>" if self.pkg and self.pkg.chr.visit_sets() else
                         "Every visit places the same units. To give revisits other enemies, set a unit's "
                         "<b>Appears on</b>.<br>") + "<br>".join(rows) if self.pkg else "")
            f.addRow("Visits", vis)
            tip = QLabel("Select a unit on the map to edit it.\n\nLegend: red circle = enemy, blue = neutral, "
                         "diamond = Geo Symbol, grey square = object, blue frame = base panel. "
                         "Numbers show panel height.")
            tip.setWordWrap(True)
            tip.setObjectName("muted")
            f.addRow(tip)
            self.insp_lay.addWidget(box)
            if self.stage_row is not None:
                self.insp_lay.addWidget(self._stage_list_box())
            self.insp_lay.addStretch(1)
            return
        u = self.pkg.chr.units[idx]
        box = QGroupBox(f"Unit #{u.slot}: {self.char_names.get(u.char_id, u.char_id)}")
        f = QFormLayout(box)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        old = u.size != mapfile.RECORD_SIZE

        def spin(name, lo, hi):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(int(getattr(u, name)))
            s.valueChanged.connect(lambda v, n=name: self._set(u, n, v))
            return s

        cc = SearchCombo(self.char_choices)
        cc.set_value(u.char_id)
        cc.activated.connect(lambda _: self._set(u, "char_id", cc.value(), redraw=True))
        cc.lineEdit().editingFinished.connect(lambda: self._set(u, "char_id", cc.value(), redraw=True))
        f.addRow("Class / character", cc)
        f.addRow("Level", spin("level", 1, 9999))
        fc = QComboBox()
        for k, v in FACING.items():
            fc.addItem(v, k)
        fc.setCurrentIndex(max(0, fc.findData(u.facing)))
        fc.currentIndexChanged.connect(lambda _: self._set(u, "facing", fc.currentData(), redraw=True))
        f.addRow("Facing", fc)
        f.addRow("X", spin("x", -1, 127))
        f.addRow("Y", spin("y", -1, 127))
        if not old:
            ap = QComboBox()
            for k, v in mapfile.APPEARS.items():
                ap.addItem(v, k)
            ap.setCurrentIndex(max(0, ap.findData(u.appears)))
            ap.setToolTip("Which visits place this unit. A stage that isn't cleared yet places 'First visit' "
                          "units; once it is cleared, 'Revisits' units instead. 'Every visit' units are always "
                          "there.")
            ap.currentIndexChanged.connect(lambda _: self._set_appears(u, ap.currentData()))
            f.addRow("Appears on", ap)
            if u.reinforcement:
                n = QLabel(f"Reinforcement group {u.spawn_group}: kept off the field until the stage's event "
                           "script calls the group in.")
                n.setWordWrap(True)
                n.setObjectName("muted")
                f.addRow(n)
            tc = QComboBox()
            for k, v in TEAMS.items():
                tc.addItem(v, k)
            tc.setCurrentIndex(max(0, tc.findData(u.team)))
            tc.currentIndexChanged.connect(lambda _: self._set(u, "team", tc.currentData(), redraw=True))
            f.addRow("Team", tc)
            f.addRow("AI pattern", spin("ai", -1, 999))
            if u.is_geo_symbol:
                gc = QComboBox()
                for k, (n, _) in GEO_COLORS.items():
                    gc.addItem("Clear" if k == 0 else n, k)
                gc.setCurrentIndex(max(0, gc.findData(u.geo_color)))
                gc.currentIndexChanged.connect(lambda _: self._set(u, "geo_color", gc.currentData(), redraw=True))
                f.addRow("Symbol color", gc)
                ge = SearchCombo(self.ge_choices)
                ge.set_value(u.geo_effect)
                ge.activated.connect(lambda _: self._set(u, "geo_effect", ge.value()))
                f.addRow("Geo effect", ge)
            self.insp_lay.addWidget(box)

            eq = QGroupBox("Equipment (item · level · rarity)")
            eg = QGridLayout(eq)
            items = self.item_choices
            for k, lab in enumerate(["Weapon", "Armor 1", "Armor 2", "Armor 3", "Armor 4"]):
                iid, ilv, ir = u.item(k)
                c = SearchCombo(items)
                c.set_value(iid)
                c.activated.connect(lambda _, k=k, c=c: self._set_item(u, k, item_id=c.value()))
                lv = QSpinBox()
                lv.setRange(0, 9999)
                lv.setSpecialValueText("Lv –")
                lv.setPrefix("Lv ")
                lv.setValue(ilv)
                lv.setToolTip("The item's level (what the Item World raises; – = the item's own, as the game's "
                              "stages have it)")
                lv.valueChanged.connect(lambda v, k=k: self._set_item(u, k, level=v))
                ra = QSpinBox()
                ra.setRange(-1, enemyitems.RARITY_MAX)
                ra.setSpecialValueText("Random")
                ra.setValue(-1 if ir is None else ir)
                ra.setToolTip("Rarity: Common 0-24, Rare 25-49, Legendary 50-99, 100 the best (the item's stats rise "
                              "by that %). Random = as the game rolls it for its stages' enemies. Some special items "
                              "keep their fixed rarity. Install patches the game for it.")
                ra.valueChanged.connect(lambda v, k=k, ra=ra: (self._set_item(u, k, rarity=None if v < 0 else v),
                                                              ra.setSuffix("" if v < 0 else
                                                                           f"  {enemyitems.band(v)}")))
                ra.setSuffix("" if ir is None else f"  {enemyitems.band(ir)}")
                eg.addWidget(QLabel(lab), k * 2, 0)
                eg.addWidget(c, k * 2, 1, 1, 2)
                eg.addWidget(lv, k * 2 + 1, 1)
                eg.addWidget(ra, k * 2 + 1, 2)
            self.insp_lay.addWidget(eq)

            sk = QGroupBox("Skills (id · level)")
            sg = QGridLayout(sk)
            mags = self.magic_choices
            skills, levels = u.skills, u.skill_levels
            shown = max(4, min(20, sum(1 for s in skills if s) + 2))
            for k in range(shown):
                c = SearchCombo(mags)
                c.set_value(skills[k])
                c.activated.connect(lambda _, k=k, c=c: self._set_list(u, "skills", k, c.value()))
                lv = QSpinBox()
                lv.setRange(0, 9999)
                lv.setValue(levels[k])
                lv.valueChanged.connect(lambda v, k=k: self._set_list(u, "skill_levels", k, v))
                sg.addWidget(c, k, 0)
                sg.addWidget(lv, k, 1)
            self.insp_lay.addWidget(sk)

            ev = QGroupBox("Evilities")
            evl = QFormLayout(ev)
            evs = self.evility_choices
            shown = max(2, min(20, sum(1 for s in u.evilities if s) + 1))
            for k in range(shown):
                c = SearchCombo(evs)
                c.set_value(u.evilities[k])
                c.activated.connect(lambda _, k=k, c=c: self._set_list(u, "evilities", k, c.value()))
                evl.addRow(f"#{k + 1}", c)
            self.insp_lay.addWidget(ev)

            sm = QGroupBox("Stat modifiers (%)")
            smg = QGridLayout(sm)
            for k, lab in enumerate(["HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD"]):
                s = QSpinBox()
                s.setRange(-100, 32767)
                s.setValue(u.stat_mods[k])
                s.valueChanged.connect(lambda v, k=k: self._set_list(u, "stat_mods", k, v))
                smg.addWidget(QLabel(lab), k // 4 * 2, k % 4)
                smg.addWidget(s, k // 4 * 2 + 1, k % 4)
            self.insp_lay.addWidget(sm)
        else:
            self.insp_lay.addWidget(box)
        row = QHBoxLayout()
        w = QWidget()
        w.setLayout(row)
        b = QPushButton("Duplicate")
        b.clicked.connect(lambda: self._dup(idx))
        row.addWidget(b)
        b = QPushButton("🗑 Delete unit")
        b.setObjectName("danger")
        b.clicked.connect(lambda: self._delete(idx))
        row.addWidget(b)
        self.insp_lay.addWidget(w)
        self.insp_lay.addStretch(1)

    def _set(self, u, name, v, redraw=False):
        try:
            if getattr(u, name) == v:
                return
            setattr(u, name, v)
        except Exception as e:
            QMessageBox.warning(self, "Invalid value", str(e))
            return
        self._set_dirty()
        if redraw:
            self.canvas.redraw()

    # ---- several units at once
    def _group_units(self):
        units = self.pkg.chr.units
        return [units[i] for i in sorted(self.canvas.multi) if 0 <= i < len(units)]

    def _group_set(self, fn, what):
        """fn(unit) on every selected unit that has the field (old 436-byte records lack most)"""
        n = 0
        for u in self._group_units():
            try:
                if fn(u) is not False:
                    n += 1
            except (AttributeError, struct.error, ValueError, OverflowError):
                pass
        if n:
            self._set_dirty()
            self.canvas.redraw()
            self.ws.log(f"{what}: {n} unit(s)")
        return n

    def _inspect_group(self):
        units = self._group_units()
        full = [u for u in units if u.size == mapfile.RECORD_SIZE]
        from collections import Counter
        names = Counter(self.char_names.get(u.char_id, str(u.char_id)).split(" (")[0] for u in units)
        box = QGroupBox(f"{len(units)} units selected")
        f = QFormLayout(box)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        who = QLabel(", ".join(f"{n} ×{c}" if c > 1 else n for n, c in names.most_common(8)) +
                     (" …" if len(names) > 8 else ""))
        who.setWordWrap(True)
        f.addRow("Who", who)
        lv = [u.level for u in units]
        f.addRow("Levels", QLabel(f"{min(lv)} – {max(lv)}" if min(lv) != max(lv) else str(lv[0])))
        tip = QLabel("Drag one of them to move them all (or the arrow keys); Delete removes them, Ctrl+D copies "
                     "them, Ctrl+Z undoes. Ctrl+click adds or takes out a unit, Shift+drag selects a box.")
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        f.addRow(tip)
        self.insp_lay.addWidget(box)

        ed = QGroupBox("Change them all")
        ef = QFormLayout(ed)
        ef.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        cc = SearchCombo(self.char_choices)
        cc.set_value(units[0].char_id if len({u.char_id for u in units}) == 1 else None)
        b = QPushButton("Set")
        b.clicked.connect(lambda: cc.currentText().strip() and cc.value() and self._group_set(
            lambda u: setattr(u, "char_id", int(cc.value())), f"class / character {cc.value()}"))
        ef.addRow("Class / character", self._row(cc, b))
        # level: set, add, or scale
        lvl = QSpinBox()
        lvl.setRange(-9999, 9999)
        lvl.setValue(max(lv))
        mode = QComboBox()
        for k, lab in (("set", "set to"), ("add", "add"), ("pct", "% of their own")):
            mode.addItem(lab, k)
        b = QPushButton("Apply")

        def set_levels():
            v, m = lvl.value(), mode.currentData()

            def one(u):
                new = v if m == "set" else u.level + v if m == "add" else round(u.level * v / 100)
                u.level = max(1, min(9999, int(new)))
            self._group_set(one, f"level {mode.currentText()} {v}")
            self._inspect(self.canvas.selected)
        b.clicked.connect(set_levels)
        ef.addRow("Level", self._row(mode, lvl, b))
        fc = QComboBox()
        fc.addItem("—", None)
        for k, v in FACING.items():
            fc.addItem(v, k)
        fc.activated.connect(lambda _: fc.currentData() is not None and self._group_set(
            lambda u: setattr(u, "facing", fc.currentData()), f"facing {fc.currentText()}"))
        ef.addRow("Facing", fc)
        if full:
            ap = QComboBox()
            ap.addItem("—", None)
            for k, v in mapfile.APPEARS.items():
                ap.addItem(v, k)
            ap.activated.connect(lambda _: ap.currentData() is not None and self._group_set(
                lambda u: setattr(u, "appears", ap.currentData()), f"appears on: {ap.currentText()}"))
            ef.addRow("Appears on", ap)
            tc = QComboBox()
            tc.addItem("—", None)
            for k, v in TEAMS.items():
                tc.addItem(v, k)
            tc.activated.connect(lambda _: tc.currentData() is not None and self._group_set(
                lambda u: setattr(u, "team", tc.currentData()), f"team {tc.currentText()}"))
            ef.addRow("Team", tc)
            ai = QSpinBox()
            ai.setRange(-1, 999)
            ai.setValue(full[0].ai)
            b = QPushButton("Set")
            b.clicked.connect(lambda: self._group_set(lambda u: setattr(u, "ai", ai.value()), f"AI {ai.value()}"))
            ef.addRow("AI pattern", self._row(ai, b))
        self.insp_lay.addWidget(ed)

        if full:
            eq = QGroupBox("Equipment of them all")
            eg = QGridLayout(eq)
            for k, lab in enumerate(["Weapon", "Armor 1", "Armor 2", "Armor 3", "Armor 4"]):
                ids = {u.item(k)[0] for u in full}
                c = SearchCombo(self.item_choices)
                c.set_value(ids.pop() if len(ids) == 1 else None)
                lvb = QSpinBox()
                lvb.setRange(0, 9999)
                lvb.setPrefix("Lv ")
                lvb.setSpecialValueText("Lv –")
                ra = QSpinBox()
                ra.setRange(-1, enemyitems.RARITY_MAX)
                ra.setSpecialValueText("Random")
                ra.setValue(-1)
                b = QPushButton("Set")
                b.setToolTip("Every selected unit gets this item, level and rarity in this slot")
                b.clicked.connect(lambda _, k=k, c=c, lvb=lvb, ra=ra: c.currentText().strip() and self._group_set(
                    lambda u: u.set_item(k, item_id=int(c.value() or 0), level=lvb.value(),
                                         rarity=None if ra.value() < 0 else ra.value()),
                    f"{['weapon', 'armor 1', 'armor 2', 'armor 3', 'armor 4'][k]} {c.value()}"))
                eg.addWidget(QLabel(lab), k * 2, 0)
                eg.addWidget(c, k * 2, 1, 1, 3)
                eg.addWidget(lvb, k * 2 + 1, 1)
                eg.addWidget(ra, k * 2 + 1, 2)
                eg.addWidget(b, k * 2 + 1, 3)
            self.insp_lay.addWidget(eq)
            sm = QGroupBox("Stat modifiers of them all (%)")
            smg = QGridLayout(sm)
            spins = []
            for k, lab in enumerate(["HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD"]):
                sp = QSpinBox()
                sp.setRange(-100, 32767)
                vals = {u.stat_mods[k] for u in full}
                sp.setValue(vals.pop() if len(vals) == 1 else 0)
                spins.append(sp)
                smg.addWidget(QLabel(lab), k // 4 * 2, k % 4)
                smg.addWidget(sp, k // 4 * 2 + 1, k % 4)
            b = QPushButton("Set them all")
            b.clicked.connect(lambda: self._group_set(
                lambda u: setattr(u, "stat_mods", [sp.value() for sp in spins]), "stat modifiers"))
            smg.addWidget(b, 4, 0, 1, 4)
            self.insp_lay.addWidget(sm)

        sel = QGroupBox("Select")
        sl = QHBoxLayout(sel)
        for lab, what, tip in (("Same class", "class", "Every unit shown of the inspected unit's class"),
                               ("Same team", "team", "Every unit shown of its team"),
                               ("All enemies", "enemies", "Every enemy shown")):
            b = QPushButton(lab)
            b.setToolTip(tip)
            b.clicked.connect(lambda _, w=what: self.select_like(w))
            sl.addWidget(b)
        self.insp_lay.addWidget(sel)
        row = QHBoxLayout()
        w = QWidget()
        w.setLayout(row)
        b = QPushButton("⧉ Duplicate them")
        b.clicked.connect(self._dup_selection)
        row.addWidget(b)
        b = QPushButton(f"🗑 Delete {len(units)} units")
        b.setObjectName("danger")
        b.clicked.connect(self._delete_selection)
        row.addWidget(b)
        self.insp_lay.addWidget(w)
        self.insp_lay.addStretch(1)

    def _row(self, *widgets):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            h.addWidget(x, 1 if isinstance(x, (QComboBox,)) else 0)
        return w

    def _set_item(self, u, k, **change):
        before = u.item(k)
        u.set_item(k, **change)
        if u.item(k) != before:
            self._set_dirty()

    def _set_list(self, u, name, k, v):
        lst = getattr(u, name)
        if lst[k] == v:
            return
        lst[k] = v
        setattr(u, name, lst)
        self._set_dirty()

    def _dup(self, idx):
        u = self.pkg.chr.units[idx]
        hb = self.pkg.hex.blocks[0]
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)]:
            x, y = u.x + dx, u.y + dy
            if self._in_grid(x, y) and not self._occupied(x, y, u.appears) and hb.has_panel(x, y):
                self.pkg.chr.add_unit(u.char_id, x, y, u.level, template=u, appears=u.appears)
                self.canvas.selected = len(self.pkg.chr.units) - 1
                self._set_dirty()
                self.canvas.redraw()
                self._inspect(self.canvas.selected)
                return
        QMessageBox.information(self, "Duplicate", "No free panel next to this unit.")

    def _delete(self, idx):
        if idx is None or idx >= len(self.pkg.chr.units):
            return
        del self.pkg.chr.units[idx]
        self.canvas.selected = None
        self._set_dirty()
        self.canvas.redraw()
        self._inspect(None)
        self._title()

    def _set_appears(self, u, v):
        if u.appears == v:
            return
        u.appears = v
        self._set_dirty()
        if not self.canvas.visible(u):
            self.canvas.selected = None
            from PyQt6.QtCore import QTimer               # (not inside the inspector's own signal)
            QTimer.singleShot(0, lambda: self._inspect(None))
            self.ws.log(f"Unit #{u.slot} now appears on: {mapfile.APPEARS[v].lower()} (hidden in this view).")
        self.canvas.redraw()
        self._title()

    # ================================================================== scripts: triggers and battle music
    def _scripts(self):
        """(script.dat, talk.dat) of the game, parsed once"""
        if getattr(self, "_sc", None) is None:
            from d5lib import script, talk
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._sc = (script.ScriptFile.from_bytes(self.ws.fs.read("Script/script.dat"), strict=False),
                            talk.TalkFile.from_bytes(self.ws.fs.read("Script/talk.dat")))
            finally:
                QApplication.restoreOverrideCursor()
        return self._sc

    def _songs(self):
        """[(file number, label)] of every song: the game's (names from the music list) and the mods' new ones"""
        if getattr(self, "_song_list", None) is None:
            from d5lib import music
            from .music import read_music_titles
            try:
                titles = read_music_titles(self.ws.fs.read(music.MUSIC_DB))
            except Exception:
                titles = {}
            out = []
            for n in music.game_tracks(self.ws.fs):
                t, d = titles.get(n, ("", ""))
                name = d if t.startswith("BGM") and d else " — ".join(x for x in (t, d) if x)
                out.append((n, f"{n} · {name}" if name else f"{n}"))
            for m in self.ws.mods.all_mods():
                for n in music.mod_tracks(m):
                    lab = music.listing(self.ws.fs, m, n)
                    out.append((n, f"{n} · {(lab[0] + ' — ' + lab[1]) if lab else 'your song'} ({m.name})"))
            self._song_list = sorted(out)
        return self._song_list

    def _battle_song(self, map_id):
        from d5lib import stagemusic
        sf, _ = self._scripts()
        return stagemusic.effective_song(sf, self._map_mods(), map_id)

    def _set_battle_song(self, map_id, song):
        """the song into the mod that already has the stage's start event, else the stage's own mod (a new
        stage), else the active one"""
        from d5lib import stagemusic
        mod = self._map_owner() if map_id == self.mid and not self._in_game(map_id) else None
        if mod is None:
            from d5lib.stagemusic import start_event
            key = str(start_event(map_id))
            mod = next((m for m in reversed(self._map_mods())
                        if key in ((m.load_patch("script", "script.json") or {}).get("events") or {})), None)
        mod = mod or self.ws.require_mod(self)
        if not mod:
            return
        sf, _ = self._scripts()
        without = stagemusic.effective_song(sf, [m for m in self._map_mods() if m.id != mod.id], map_id)
        stagemusic.set_song(mod, map_id, None if song == without else song)     # back to the game's: no change kept
        self.ws.log(f"map{map_id:05d}: battle music {song}, saved into {mod.name}. Install to hear it.")

    # ================================================================== the game's stage list
    def _episode_stages(self, episode):
        """names of the game's stages listed in an episode's tab (map // 100)"""
        van = self.svc.vanilla(DUNGEON).rows
        return [mapfile.DungeonRecord(bytes(r.raw)).name() for r in van
                if mapfile.DungeonRecord(bytes(r.raw)).map_id // 100 == episode and
                mapfile.DungeonRecord(bytes(r.raw)).title_id]

    def _stage_list_box(self):
        box = QGroupBox("In the game's stage list")
        f = QFormLayout(box)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        t = self.svc.table(DUNGEON)
        rec = mapfile.DungeonRecord(bytes(t.rows[self.stage_row].raw))
        ep = rec.map_id // 100
        others = self._episode_stages(ep)
        mine = self.stage_row >= len(self.svc.vanilla(DUNGEON).rows)
        where = QLabel((f"Episode {ep}'s list (with {', '.join(others[:3])}{' …' if len(others) > 3 else ''})"
                        if others else f"<span style='color:#ff8a8a'>No list: the game lists a stage in the "
                                       f"episode of its map number (map{rec.map_id:05d} → episode {ep}, which has no "
                                       f"stages).</span>"))
        where.setWordWrap(True)
        where.setToolTip("The Dimension Guide shows a stage in the tab of its map number (map // 100), once its "
                         "story flag is set. Map numbers xx30-xx99 of every episode are free for new stages.")
        f.addRow("Shown in", where)
        bm = QComboBox()
        song = self._battle_song(rec.map_id)
        if song is None:
            bm.addItem("(none: the stage list's music goes on)", None)
        for n, lab in self._songs():
            bm.addItem(lab, n)
        k = bm.findData(song) if song is not None else 0
        bm.setCurrentIndex(max(0, k))
        if song is not None and k < 0:
            bm.addItem(f"{song}", song)
            bm.setCurrentIndex(bm.count() - 1)
        bm.setToolTip("The song played when the battle starts (the stage's start event). Your own songs from "
                      "Music & Sound are listed too.")
        bm.currentIndexChanged.connect(lambda _: bm.currentData() is not None and
                                       self._set_battle_song(rec.map_id, bm.currentData()))
        f.addRow("Battle music", bm)
        ne = self._netherworld_box(rec)
        if ne is not None:
            f.addRow("Netherworld effect", ne)
        lw = QComboBox()
        lw.addItem("(never: no story flag)", 0)
        if not mine and rec.title_id:
            lw.addItem(f"its own story flag ({rec.title_id}): the story unlocks it", rec.title_id)
        cur = 1 if not mine and rec.title_id else 0
        for label, mid, row in self._listed_stages():
            r2 = mapfile.DungeonRecord(bytes(t.rows[row].raw))
            if row == self.stage_row:
                continue
            lw.addItem(f"{label}  ·  episode {mid // 100}", r2.title_id)
            if r2.title_id == rec.title_id and not cur and mine:
                cur = lw.count() - 1
        lw.setCurrentIndex(cur if rec.title_id else 0)
        lw.setToolTip("The story flag that lists it: the stage is listed as soon as the stage chosen here is "
                      "(their flag is the same).")
        lw.setEnabled(mine)
        lw.currentIndexChanged.connect(lambda _: self._set_listed(lw.currentData()))
        f.addRow("Listed with", lw)
        kind = QComboBox()
        for k, label in ((0, "Story stages"), (1, "Extra stages (hidden in Carnage mode)"), (2, "Carnage list only")):
            kind.addItem(label, k)
        kind.setCurrentIndex(max(0, kind.findData(rec.raw[0x1D])))
        kind.setEnabled(mine)
        kind.currentIndexChanged.connect(lambda _: self._set_raw(0x1D, kind.currentData()))
        f.addRow("List", kind)
        for cb in (bm, lw, kind):                       # long song / stage names: don't widen the panel
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(14)
        row = QHBoxLayout()
        w = QWidget()
        w.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        if mine:
            b = QPushButton("Move to another episode…")
            b.setToolTip("Give the stage a map number of another episode: it is listed there")
            b.clicked.connect(self._move_episode)
            row.addWidget(b)
            b = QPushButton("🗑 Delete stage…")
            b.setToolTip("Take the stage out of its mod: its map, its stage-list entry, its battle start and music, "
                         "its blocks. Saves that listed it: Home › More › Check saves takes it off them.")
            b.clicked.connect(self._delete_stage)
            row.addWidget(b)
        f.addRow(w)
        if not mine:
            n = QLabel("A stage of the game: it is in every save already.")
            n.setObjectName("muted")
            n.setWordWrap(True)
            f.addRow(n)
        return box

    # ---- the stage's Netherworld effect (dungeon.dat +0x10 = a MakaiSkillDataBase id)
    def _netherworld_skills(self):
        """[(id, name, description, row)] of the Netherworld skills a stage can have (no dummies, no 'on call')"""
        try:
            t = self.svc.table(NETHER_SKILLS)
        except Exception:
            return []
        out = []
        for r in t.rows:
            sid, desc = int(r["id"]), str(r["desc_EN"] or "")
            if desc in ("ダミー", "") or int(r["trigger"]) == 4:
                continue
            out.append((sid, str(r["name_EN"]), desc, r))
        return out

    def _netherworld_box(self, rec):
        skills = self._netherworld_skills()
        if not skills:
            return None
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        cb = QComboBox()
        cb.addItem("(none)", 0)
        cur = rec.netherworld_skill
        for sid, name, desc, _ in skills:
            special = sid in NETHER_OWN_STAGE
            cb.addItem(f"{name}: {desc}" + ("  (made for its own stage)" if special else ""), sid)
        k = cb.findData(cur)
        if k < 0:
            cb.addItem(f"#{cur}", cur)
            k = cb.count() - 1
        cb.setCurrentIndex(k)
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(14)
        cb.setToolTip("What the whole battle has, as the game's Netherworlds do: Snow lowers Water resistance, Gale "
                      "Force Winds Wind resistance, Fire Powder Fire resistance (with their falling snow / wind / "
                      "embers), EXP Up, Auto HP Recovery … The ones marked 'made for its own stage' need things of "
                      "their stage (Sea of Poison: its sea; Mushroom Paradise: mushroom objects; Baal's).")
        lay.addWidget(cb)
        amt = QWidget()
        al = QHBoxLayout(amt)
        al.setContentsMargins(0, 0, 0, 0)
        sp = QSpinBox()
        sp.setRange(-999, 999)
        note = QLabel()
        note.setObjectName("muted")
        note.setWordWrap(True)
        al.addWidget(QLabel("Amount"))
        al.addWidget(sp)
        al.addStretch(1)
        lay.addWidget(amt)
        lay.addWidget(note)
        rows = {sid: r for sid, _, _, r in skills}

        def show_amount():
            sid = cb.currentData()
            r = rows.get(sid)
            on = r is not None and sid in NETHER_AMOUNT
            amt.setVisible(bool(on))
            note.setVisible(bool(on))
            if not on:
                return
            sp.blockSignals(True)
            sp.setValue(int(r["value"]))
            sp.blockSignals(False)
            users = [mapfile.DungeonRecord(bytes(x.raw)).name() for x in self.svc.table(DUNGEON).rows
                     if mapfile.DungeonRecord(bytes(x.raw)).netherworld_skill == sid]
            note.setText(f"In % (or panels / points). The same for every stage with {r['name_EN']}"
                         + (f" ({len(users)} stages)" if len(users) > 1 else "") + ".")

        def pick(_):
            sid = int(cb.currentData() or 0)
            row = self.svc.table(DUNGEON).rows[self.stage_row]
            r2 = mapfile.DungeonRecord(bytes(row.raw))
            if r2.netherworld_skill != sid:
                r2.netherworld_skill = sid
                row.raw[:] = r2.raw
                self.svc.mark_dirty(DUNGEON)
                self._set_dirty()
            show_amount()

        def amount(v):
            r = rows.get(cb.currentData())
            if r is None or int(r["value"]) == v:
                return
            r["value"] = int(v)
            self.svc.mark_dirty(NETHER_SKILLS)
            self._set_dirty()

        cb.currentIndexChanged.connect(pick)
        sp.valueChanged.connect(amount)
        show_amount()
        return w

    def _set_raw(self, off, v):
        row = self.svc.table(DUNGEON).rows[self.stage_row]
        if row.raw[off] != v:
            row.raw[off] = v
            self.svc.mark_dirty(DUNGEON)
            self._set_dirty()

    def _set_listed(self, title_id):
        row = self.svc.table(DUNGEON).rows[self.stage_row]
        rec = mapfile.DungeonRecord(bytes(row.raw))
        if rec.title_id == title_id:
            return
        rec.title_id = int(title_id or 0)
        row.raw[:] = rec.raw
        self.svc.mark_dirty(DUNGEON)
        self._set_dirty()

    def _move_episode(self):
        """a new map number in another episode's range: the map file renamed in its mod, the stage row changed"""
        eps = sorted({mapfile.DungeonRecord(bytes(r.raw)).map_id // 100
                      for r in self.svc.vanilla(DUNGEON).rows
                      if mapfile.DungeonRecord(bytes(r.raw)).title_id and
                      mapfile.DungeonRecord(bytes(r.raw)).map_id < 10000})
        labels = [f"Episode {e}: {', '.join(self._episode_stages(e)[:3])}" for e in eps]
        choice, ok = QInputDialog.getItem(self, "Move to another episode", "List the stage in:", labels, 0, False)
        if not ok:
            return
        ep = eps[labels.index(choice)]
        mod = self._map_owner()
        if mod is None or self._in_game(self.mid):
            QMessageBox.information(self, "Move", "Only a stage whose map is in a mod can get a new number.")
            return
        new = self.free_map_id(ep)
        if new is None:
            QMessageBox.warning(self, "Move", f"Episode {ep} has no free map number left.")
            return
        if self.dirty:
            self.save()
            if self.dirty:
                return
        old_vp = self.map_vpath
        pkg = mapfile.MapPackage(self._read_members(old_vp), f"map{self.mid:05d}")
        new_vp = old_vp.rsplit("/", 1)[0] + f"/map{new:05d}.lzs"
        self.ws.write(new_vp, pkg.renamed(new).to_pac(), self, mod=mod)
        from d5lib import stagemusic
        stagemusic.move_stage(mod, self.mid, new)
        b = mod.load_patch("stages", f"build_{self.mid:05d}.json")
        if b:
            # the cut-out of the map itself follows the map to its new number
            for p in b.get("pieces", []):
                k = mapbuild.key_of(p["piece"])
                if isinstance(k, tuple) and k[0] == self.mid:
                    p["piece"] = [new] + list(k[1:])
            mod.save_patch("stages", f"build_{new:05d}.json", b)
            mod.save_patch("stages", f"build_{self.mid:05d}.json", None)
        import os
        tp = self._terrain_path(mod, self.mid)
        if os.path.exists(tp):
            os.replace(tp, self._terrain_path(mod, new))
        if self.mid in enemyitems.maps_of(mod):
            enemyitems.note_map(mod, self.mid, False)
            enemyitems.note_map(mod, new, True)
        for f in list(mod.list_files()):
            if f == old_vp or f.startswith(old_vp + "/"):
                mod.remove_file(f)
        row = self.svc.table(DUNGEON).rows[self.stage_row]
        rec = mapfile.DungeonRecord(bytes(row.raw))
        rec.map_id = new
        row.raw[:] = rec.raw
        self.svc.mark_dirty(DUNGEON)
        self.svc.commit(DUNGEON, self, into=mod)
        self.__dict__.pop("_map_cache", None)
        self.ws.log(f"'{rec.name()}' is now map{new:05d} (episode {ep}). Saves that listed the old number: Home › "
                    "More › Check saves takes it off (the game adds the new one by itself)")
        self._populate()
        for i in range(self.stages.count()):
            d = self.stages.item(i).data(ROLE)
            if d and d[2] == new:
                self.stages.setCurrentRow(i)
                break

    def _delete_stage(self):
        """a stage of a mod deleted: map file, stage-list row (the mod's dungeon.dat patch), triggers, music, build"""
        from d5lib import stagemusic
        if not self.pkg or self.stage_row is None or self._in_game(self.mid):
            return
        mod = self._map_owner()
        rec = mapfile.DungeonRecord(bytes(self.svc.table(DUNGEON).rows[self.stage_row].raw))
        if mod is None:
            QMessageBox.information(self, "Delete stage", "This stage's map is in no mod of yours.")
            return
        who = []
        try:
            from d5lib import questcheck
            q = self.svc.table("Quest.dat")
            who = [r["name_EN"] for r in q.rows if int(r["cond_type"]) == questcheck.CLEAR_STAGE and
                   int(r["cond_target1"]) == self.mid]
        except Exception:
            pass
        text = (f"Delete the stage '{rec.name()}' (map{self.mid:05d}) from the mod '{mod.name}'?\n\nIts map, its "
                "place in the stage list, its battle start and music and its blocks go. Saves that listed it keep a "
                "slot for it until Home › More › Check saves takes it off (the game closes when the stage list's "
                "cursor reaches a stage that is gone).")
        if who:
            text += "\n\nThe quest(s) " + ", ".join(f"“{n}”" for n in who) + " ask to clear it: change what they " \
                    "ask for first (Characters › How to get this character), or they can't be finished."
        if QMessageBox.question(self, "Delete stage", text,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel) \
                != QMessageBox.StandardButton.Yes:
            return
        mid = self.mid
        try:
            # the stage-list row: this mod's added row with that map number
            patch = mod.load_patch("db", "dungeon.dat.json") or {}
            added = patch.get("added") or []
            keep = [r for r in added if int(r.get("map_id", -1)) != mid]
            if len(keep) != len(added):
                patch["added"] = keep
                mod.save_patch("db", "dungeon.dat.json", patch if (patch.get("added") or patch.get("rows")) else None)
            for f in list(mod.list_files()):
                if f == self.map_vpath or f.startswith(self.map_vpath + "/"):
                    mod.remove_file(f)
            mod.save_patch("stages", f"build_{mid:05d}.json", None)
            import os
            tp = self._terrain_path(mod, mid)
            if os.path.exists(tp):
                os.remove(tp)
            enemyitems.note_map(mod, mid, False)
            stagemusic.remove_stage(mod, mid)
        except Exception as e:
            error_box(self, "Delete stage", e)
            return
        self.svc.discard(DUNGEON)
        self.svc.reload(keep_unsaved=False)
        self.__dict__.pop("_map_cache", None)
        self.__dict__.pop("_maps_in_game", None)
        vp = self.map_vpath
        self.pkg = None
        self.build = None
        self.stage_row = None
        self.mid = None
        self.map_vpath = None
        self.dirty = False
        self._show_builder(False)
        self.canvas.load(None, None, self.char_names)
        self._populate()
        self._clear_inspector()
        self.title.setText("Pick a stage")
        self.ws.log(f"Deleted stage '{rec.name()}' (map{mid:05d}) from '{mod.name}'. Saves that listed it: Home › "
                    "More › Check saves.")
        self.ws.file_changed.emit(vp)

    def _set_stage_name(self, text):
        if self.stage_row is None:
            return
        row = self.svc.table(DUNGEON).rows[self.stage_row]
        rec = mapfile.DungeonRecord(bytes(row.raw))
        if rec.name() == text:
            return
        rec.set_name(text, "EN")
        row.raw[:] = rec.raw
        self.svc.mark_dirty(DUNGEON)
        self._set_dirty()

    # ================================================================== clone / export
    def free_map_id(self, episode=None):
        """a map number nothing uses: not the game's map files, not a stage of dungeon.dat (map 90001 is the
        game's own Unique Dungeon, whose file isn't in the archive), not a map of any mod.  episode: the stage list
        tab it goes in (map // 100; the game's stages use xx01-xx09 and xx21-xx25 of it) -> None when it is full"""
        used = set()
        for arch in ("Map/Map_JP.dat", "Map/Map_EN.dat"):
            try:
                used |= {int(n[3:8]) for n in self.ws.fs.list_members(arch) if n[3:8].isdigit()}
            except Exception:
                pass
        used |= {mapfile.DungeonRecord(bytes(r.raw)).map_id for r in self.svc.table(DUNGEON).rows}
        for m in self.ws.mods.all_mods():
            for f in m.list_files():
                n = f.rsplit("/", 1)[-1]
                if f.startswith("Map/") and n.startswith("map") and n[3:8].isdigit():
                    used.add(int(n[3:8]))
        if episode is not None:
            return next((m for m in range(episode * 100 + 30, episode * 100 + 100) if m not in used), None)
        new = 95001
        while new in used:
            new += 1
        return new

    def _listed_stages(self):
        """[(label, map id, row)] of the stages with a story flag (what a new stage can be listed with)"""
        out = []
        for i, row in enumerate(self.svc.table(DUNGEON).rows):
            rec = mapfile.DungeonRecord(bytes(row.raw))
            if rec.title_id and 100 <= rec.map_id < 10000 and "(Demo)" not in rec.name():
                out.append((rec.name() or f"map{rec.map_id:05d}", rec.map_id, i))
        return out

    def new_stage(self):
        import os
        from ..newstage import NewStageDialog
        self._load_names()
        stages = []
        for i, row in enumerate(self.svc.table(DUNGEON).rows):
            rec = mapfile.DungeonRecord(bytes(row.raw))
            if self._in_game(rec.map_id):
                stages.append((rec.name() or f"map{rec.map_id:05d}", rec.map_id, i))
        dlg = NewStageDialog(self, stages, os.path.join(self.ws.game_dir, "Data"),
                             current=self.mid if self.pkg else None, listed=self._listed_stages())
        if not dlg.exec():
            return
        v = dlg.values()
        mod = self.ws.require_mod(self)
        if not mod:
            return
        if self.dirty:
            self.save()
        try:
            base = mapfile.MapPackage(self._read_members(self._map_vpath(v["map"])), f"map{v['map']:05d}")
            chrf = base.chr
            if v["start"] == "objects":
                chrf.units = [u for u in chrf.units if u.is_object]
            elif v["start"] == "empty":
                chrf.units = []
            if not v["panels"]:
                base.gop.blocks[0].set_panels([])
            build_json = None
            if v["start"] == "build":
                lib = mapbuild.Library(self._read_pkg)
                gw, gh = v.get("size", (12, 12))
                build_json = mapbuild.empty_build(gw, gh)
                mapbuild.place(build_json, 60030, max(0, (gw - 5) // 2), max(0, (gh - 8) // 2))
                base = mapbuild.compose(build_json, lib.for_build(build_json), lib.skeleton(), name=base.name)
            t = self.svc.table(DUNGEON)
            with_ = None
            if v["listed"]:
                with_ = mapfile.DungeonRecord(bytes(t.rows[v["listed"][1]].raw))
                new = self.free_map_id(with_.map_id // 100)
                if new is None:
                    raise RuntimeError(f"episode {with_.map_id // 100} has no free map number left (70 per "
                                       "episode); list it with a stage of another episode")
            else:
                new = self.free_map_id()
            self.ws.write(f"Map/Map_JP.dat/map{new:05d}.lzs", base.renamed(new).to_pac(), self, mod=mod)
            row = t.add_row(copy_from=v["row"])
            rec = mapfile.DungeonRecord(bytes(row.raw))
            rec.index = max(mapfile.DungeonRecord(bytes(r.raw)).index for r in t.rows) + 1
            rec.map_id = new
            for lang in mapfile.DungeonRecord.LANGS:
                rec.set_name(v["name"], lang)
            rec.raw[0x08:0x10] = bytes(8)               # no story events of the stage it was copied from
            if with_ is not None:
                rec.title_id = with_.title_id           # listed when that stage is
                rec.raw[0x1D] = with_.raw[0x1D]         # (story / extra / Carnage list)
            else:
                rec.title_id = 0
            row.raw[:] = rec.raw
            self.svc.mark_dirty(DUNGEON)
            self.svc.commit(DUNGEON, self, into=mod)
            if build_json is not None:
                mod.save_patch("stages", f"build_{new:05d}.json", build_json)
            # what makes the stage run: its base stage's battle-start / end triggers and battle music
            from d5lib import stagemusic
            sf, tf = self._scripts()
            stagemusic.add_triggers(mod, stagemusic.trigger_texts(tf, v["map"], new))
            song = stagemusic.effective_song(sf, self._map_mods(), v["map"])
            stagemusic.set_song(mod, new, song if song is not None else 12)
        except Exception as e:
            error_box(self, "New stage", e)
            return
        self.__dict__.pop("_maps_in_game", None)
        self.dirty = False
        self._populate()
        for i in range(self.stages.count()):
            d = self.stages.item(i).data(ROLE)
            if d and d[2] == new:
                self.stages.setCurrentRow(i)
                break
        self.ws.log(f"New stage '{v['name']}' (map{new:05d}) from {v['base_name']} -- saved into {mod.name}")
        info_box(self, "New stage",
                 f"'{v['name']}' is map{new:05d}, a stage of its own in your mod, starting from "
                 f"{v['base_name']}, with its battle start and battle music.\n\nPlace its enemies, Geo Panels "
                 "and base panel, then Save and install. The game lists it in the episode shown under 'In the "
                 "game's stage list' on the right, as soon as the stage it is listed with is; saves you already "
                 "have get it the next time the game loads them.")

    clone = new_stage                                    # (older name)

    def export_obj(self):
        if not self.pkg:
            return
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Export map model (OBJ + textures) to")
        if not d:
            return
        try:
            import os
            self.pkg.obf.export_obj(os.path.join(d, f"map{self.mid:05d}.obj"))
            self.ws.log(f"Exported map{self.mid:05d} model to {d}")
        except Exception as e:
            error_box(self, "Export failed", e)
