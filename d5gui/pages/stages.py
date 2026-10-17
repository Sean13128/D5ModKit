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

from d5lib import mapfile, pac, mapbuild
from ..common import PageHeader, SearchBox, error_box, info_box
from ..stagebuilder import BuilderPanel, TOOL_PLACE, TOOL_MOVE
from ..dbservice import get_service, char_names, table_names

ROLE = Qt.ItemDataRole.UserRole
CELL = 34
DUNGEON = "dungeon.dat"
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
    cell_clicked = pyqtSignal(int, int, object)   # x, y, mouse button
    cell_dragged = pyqtSignal(int, int)
    redrawn = pyqtSignal()                        # after every redraw (the 3D view shows the same map and selection)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(14, 12, 20))
        self.pkg = None
        self.base = None
        self.selected = None
        self.names = {}
        self.mid = 0
        self._drag = False
        self.visit = mapfile.APPEARS_FIRST      # the visit shown (None = every unit of every visit)

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
            pen = QPen(QColor("#ffffff") if sel else QColor(0, 0, 0), 3 if sel else 1)
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
        sc.setSceneRect(QRectF(-10, -10, W * CELL + 20, H * CELL + 20))

    def _cell(self, e):
        p = self.mapToScene(e.position().toPoint())
        return int(p.x() // CELL), int(p.y() // CELL)

    def mousePressEvent(self, e):
        if not self.pkg:
            return
        x, y = self._cell(e)
        self._drag = e.button() == Qt.MouseButton.LeftButton
        self.cell_clicked.emit(x, y, e.button())

    def mouseMoveEvent(self, e):
        if self._drag and self.pkg:
            x, y = self._cell(e)
            self.cell_dragged.emit(x, y)

    def mouseReleaseEvent(self, e):
        self._drag = False

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
            self.open_map(self.mid, self.stage_row)

    def _set_dirty(self):
        self.dirty = True
        self._set_status()

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
            if not self._in_game(self.mid):          # a map of a mod: its whole file, in its mod
                for f in list(mod.list_files()):
                    if f.startswith(self.map_vpath + "/"):  # (members saved separately by older kits)
                        mod.remove_file(f)
                self.ws.write(self.map_vpath, self.pkg.to_pac(), self, mod=mod)
                if self.build is not None:
                    mod.save_patch("stages", f"build_{self.mid:05d}.json", self.build)
                if self.stage_row is not None and self.svc.is_dirty(DUNGEON):
                    self.svc.commit(DUNGEON, self)
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
                self.lib.pkgs[int(self.mid)] = mapfile.MapPackage([(n, bytes(d)) for n, d in self.pkg.members],
                                                                  self.pkg.name)
            else:
                self.build = mapbuild.empty_build(hb.width, hb.height)
            self.ws.log(f"map{self.mid:05d}: building out of blocks ({len(self.build['pieces'])} to start with)")
        self._show_builder(on and self.build is not None)
        if on and self.build is not None and not self.build["pieces"]:
            self.recompose()

    def recompose(self):
        """the map's terrain from the build (its units and Geo Panels stay)"""
        if self.build is None or not self.pkg:
            return
        try:
            pieces = self.lib.for_build(self.build)
            new = mapbuild.compose(self.build, pieces, self.lib.skeleton(), base_pkg=self.pkg, name=self.pkg.name)
        except Exception as e:
            error_box(self, "Blocks", e)
            return
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
            self.canvas.selected = idx
            self._drag_from = idx
            self._inspect(idx)
            self.canvas.redraw()
        else:
            self._click(u.x, u.y, button)

    def _click(self, x, y, button):
        if not self.pkg or not self._in_grid(x, y):
            return
        tool = self.tool.checkedId()
        if tool >= TOOL_PLACE:
            self.builder.click(x, y, button)
            return
        if tool == 0:
            self.canvas.selected = self._unit_at(x, y)
            self._drag_from = self.canvas.selected
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

            eq = QGroupBox("Equipment")
            ef = QFormLayout(eq)
            items = self.item_choices
            for k, lab in enumerate(["Weapon", "Armor 1", "Armor 2", "Armor 3", "Armor 4"]):
                c = SearchCombo(items)
                c.set_value(u.equipment[k])
                c.activated.connect(lambda _, k=k, c=c: self._set_list(u, "equipment", k, c.value()))
                ef.addRow(lab, c)
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
        f.addRow(w)
        if not mine:
            n = QLabel("A stage of the game: it is in every save already.")
            n.setObjectName("muted")
            n.setWordWrap(True)
            f.addRow(n)
        return box

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
            mod.save_patch("stages", f"build_{new:05d}.json", b)
            mod.save_patch("stages", f"build_{self.mid:05d}.json", None)
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
                build_json = mapbuild.empty_build(12, 12)
                mapbuild.place(build_json, 60030, 3, 2)
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
