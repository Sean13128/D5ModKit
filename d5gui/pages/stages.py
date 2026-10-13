"""Stages & Maps: stage list, interactive grid editor for enemies / geo panels / base panel."""
import struct

import numpy as np
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QPointF
from PyQt6.QtGui import QColor, QBrush, QPen, QFont, QPainter, QPolygonF
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QComboBox, QGraphicsView, QGraphicsScene, QButtonGroup,
                             QFormLayout, QSpinBox, QLineEdit, QScrollArea, QGroupBox, QMessageBox,
                             QInputDialog, QCompleter, QGridLayout, QApplication, QCheckBox)

from d5lib import mapfile, pac
from ..common import PageHeader, SearchBox, error_box, info_box
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
        # hovering the box shows the description of the chosen entry (the list shows each entry's own)
        self.currentIndexChanged.connect(self._update_tip)
        self.editTextChanged.connect(self._update_tip)

    def _update_tip(self, *_):
        i = self.findText(self.currentText())
        tip = self.itemData(i, Qt.ItemDataRole.ToolTipRole) if i >= 0 else None
        self.setToolTip(tip or "")

    def value(self):
        i = self.findText(self.currentText())
        if i >= 0:
            return self.itemData(i)
        try:
            return int(self.currentText().split(" ")[0])
        except ValueError:
            return 0

    def set_value(self, v):
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
        else:
            self.setEditText(str(v))


class MapCanvas(QGraphicsView):
    cell_clicked = pyqtSignal(int, int, object)   # x, y, mouse button
    cell_dragged = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(14, 12, 20))
        self.pkg = None
        self.base = None
        self.selected = None
        self.names = {}
        self._drag = False

    def load(self, pkg, base, names):
        self.pkg, self.base, self.names = pkg, base, names
        self.redraw()

    def redraw(self):
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
        for i, u in enumerate(self.pkg.chr.units):
            if not u.on_map:
                continue
            cx, cy = u.x * CELL + CELL / 2, u.y * CELL + CELL / 2
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
        self.paint_color = QComboBox()
        for k, (n, c) in GEO_COLORS.items():
            self.paint_color.addItem("Erase" if k == 0 else n, k)
        self.paint_color.setCurrentIndex(1)
        tools.addWidget(self.paint_color)
        tools.addStretch(1)
        cl.addLayout(tools)
        self.canvas = MapCanvas()
        self.canvas.cell_clicked.connect(self._click)
        self.canvas.cell_dragged.connect(self._drag)
        cl.addWidget(self.canvas, 1)
        bot = QHBoxLayout()
        self.b_save = QPushButton("💾 Save")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save)
        bot.addWidget(self.b_save)
        for text, fn, tip in [("Discard changes", self.reload, ""),
                              ("Revert to original", self.revert, "Remove this map's changes from the mod"),
                              ("Clone as new stage…", self.clone, "Copy this map to a new map id and add a stage entry"),
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
        split.addWidget(self.insp_scroll)
        split.setSizes([280, 800, 420])
        lay.addWidget(split, 1)
        self._populated = False
        self._want_map = None
        ws.file_changed.connect(lambda v: v.startswith("Map/") and self.__dict__.pop("_map_cache", None))

    # ================================================================== stage list
    def on_show(self):
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

    def _populate(self):
        self.stages.clear()
        t = self.svc.table(DUNGEON)
        for i, row in enumerate(t.rows):
            rec = mapfile.DungeonRecord(bytes(row.raw))
            it = QListWidgetItem(f"{rec.name() or '(unnamed)'}   ·  map{rec.map_id:05d}")
            it.setData(ROLE, ("stage", i, rec.map_id))
            it.setToolTip(f"dungeon.dat row {i}, stage #{rec.index}, episode {rec.episode}")
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
        if self.ws.active_mod:
            for f in self.ws.active_mod.list_files():
                if f.startswith("Map/") and f.count("/") == 2 and f.endswith(".lzs"):
                    mid = int(f.split("/")[-1][3:8])
                    if mid not in used:
                        it = QListWidgetItem(f"map{mid:05d}  (new, in your mod)")
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
        self.open_map(mid, row)

    # ================================================================== load / save
    def _map_vpath(self, mid):
        name = f"map{mid:05d}.lzs"
        if self.ws.active_mod:
            for f in self.ws.active_mod.list_files():
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
        base = None
        name = f"map{mid:05d}"
        if stage_row is not None:
            rec = mapfile.DungeonRecord(bytes(self.svc.table(DUNGEON).rows[stage_row].raw))
            base = (rec.base_x, rec.base_y)
            name = f"{rec.name()}  (map{mid:05d})"
        self.base = base
        hb = self.pkg.hex.blocks[0]
        n_en = len([u for u in self.pkg.chr.units if not u.is_object])
        self.title.setText(f"{name}  —  {hb.width}×{hb.height} grid, {n_en} enemies, "
                           f"{len(self.pkg.chr.geo_symbols())} Geo Symbols"
                           + ("   ✏ modified" if self._is_modified() else ""))
        self.canvas.load(self.pkg, base, self.char_names)
        self.canvas.resetTransform()
        r = self.canvas.scene().sceneRect()
        vw, vh = max(1, self.canvas.viewport().width()), max(1, self.canvas.viewport().height())
        z = min(1.6, vw / r.width(), vh / r.height())
        self.canvas.scale(z, z)
        self.canvas.selected = None
        self._inspect(None)
        self._set_status()

    def _is_modified(self):
        mod = self.ws.active_mod
        if not mod:
            return False
        return any(f.startswith(self.map_vpath) for f in mod.list_files())

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

    def save(self):
        if not self.pkg:
            return
        mod = self.ws.require_mod(self)
        if not mod:
            return
        try:
            self.pkg.commit()
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
                    self.ws.write(vp, data, self)
            if self.stage_row is not None and self.svc.is_dirty(DUNGEON):
                self.svc.commit(DUNGEON, self)
            self.dirty = False
            self._set_status()
            self.ws.log(f"Saved map{self.mid:05d} to mod '{mod.name}'")
        except Exception as e:
            error_box(self, "Save failed", e)

    def revert(self):
        if not self.pkg or not self.ws.active_mod:
            return
        for f in list(self.ws.active_mod.list_files()):
            if f.startswith(self.map_vpath + "/"):
                self.ws.active_mod.remove_file(f)
        self.dirty = False
        self.open_map(self.mid, self.stage_row)

    # ================================================================== editing
    def _unit_at(self, x, y):
        for i, u in enumerate(self.pkg.chr.units):
            if u.x == x and u.y == y:
                return i
        return None

    def _in_grid(self, x, y):
        hb = self.pkg.hex.blocks[0]
        return 0 <= x < hb.width and 0 <= y < hb.height

    def _click(self, x, y, button):
        if not self.pkg or not self._in_grid(x, y):
            return
        tool = self.tool.checkedId()
        if tool == 0:
            self.canvas.selected = self._unit_at(x, y)
            self._drag_from = self.canvas.selected
            self._inspect(self.canvas.selected)
        elif tool in (1, 2):
            if self._unit_at(x, y) is not None:
                return
            if tool == 1:
                tmpl = next((u for u in self.pkg.chr.units if not u.is_object), None)
                u = self.pkg.chr.add_unit(tmpl.char_id if tmpl else 1010, x, y, tmpl.level if tmpl else 1, template=tmpl)
            else:
                tmpl = next(iter(self.pkg.chr.geo_symbols()), None)
                if tmpl is None:
                    u = self.pkg.chr.add_unit(4810, x, y, 1, template=None, team=2, ai=-1, geo_color=1, geo_effect=1)
                else:
                    u = self.pkg.chr.add_unit(tmpl.char_id, x, y, tmpl.level, template=tmpl)
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
        if tool == 3:
            self._paint(x, y)
            self.canvas.redraw()
        elif tool == 0 and self.canvas.selected is not None:
            u = self.pkg.chr.units[self.canvas.selected]
            if (u.x, u.y) != (x, y) and self._unit_at(x, y) is None:
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

    def _inspect(self, idx):
        self._clear_inspector()
        if idx is None or not self.pkg:
            box = QGroupBox("Stage")
            f = QFormLayout(box)
            if self.stage_row is not None:
                row = self.svc.table(DUNGEON).rows[self.stage_row]
                rec = mapfile.DungeonRecord(bytes(row.raw))
                name = QLineEdit(rec.name())
                name.editingFinished.connect(lambda: self._set_stage_name(name.text()))
                f.addRow("Stage name (EN)", name)
                f.addRow("Map file", QLabel(f"map{rec.map_id:05d}"))
                f.addRow("Base panel", QLabel(f"{rec.base_x}, {rec.base_y}  (use 🏁 tool)"))
            else:
                f.addRow(QLabel("This map isn't listed as a stage."))
            tip = QLabel("Select a unit on the map to edit it.\n\nLegend: red circle = enemy, blue = neutral, "
                         "diamond = Geo Symbol, grey square = object, blue frame = base panel. "
                         "Numbers show panel height.")
            tip.setWordWrap(True)
            tip.setObjectName("muted")
            f.addRow(tip)
            self.insp_lay.addWidget(box)
            self.insp_lay.addStretch(1)
            return
        u = self.pkg.chr.units[idx]
        box = QGroupBox(f"Unit #{u.slot}: {self.char_names.get(u.char_id, u.char_id)}")
        f = QFormLayout(box)
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
            if self._in_grid(x, y) and self._unit_at(x, y) is None and hb.has_panel(x, y):
                self.pkg.chr.add_unit(u.char_id, x, y, u.level, template=u)
                self.canvas.selected = len(self.pkg.chr.units) - 1
                self._set_dirty()
                self.canvas.redraw()
                self._inspect(self.canvas.selected)
                return
        QMessageBox.information(self, "Duplicate", "No free panel next to this unit.")

    def _delete(self, idx):
        del self.pkg.chr.units[idx]
        self.canvas.selected = None
        self._set_dirty()
        self.canvas.redraw()
        self._inspect(None)

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
    def clone(self):
        if not self.pkg:
            return
        used = set()
        for n in self.ws.fs.list_members("Map/Map_JP.dat"):
            if n[3:8].isdigit():
                used.add(int(n[3:8]))
        new = 90001
        while new in used:
            new += 1
        new, ok = QInputDialog.getInt(self, "Clone stage", "New map id (unused number):", new, 1, 99999)
        if not ok:
            return
        if new in used:
            QMessageBox.warning(self, "Clone", f"map{new:05d} already exists.")
            return
        name, ok = QInputDialog.getText(self, "Clone stage", "Name of the new stage:", text="My New Stage")
        if not ok:
            return
        mod = self.ws.require_mod(self)
        if not mod:
            return
        self.pkg.commit()
        clone = self.pkg.renamed(new)
        self.ws.write(f"Map/Map_JP.dat/map{new:05d}.lzs", clone.to_pac(), self)
        if self.stage_row is not None:
            t = self.svc.table(DUNGEON)
            src = t.rows[self.stage_row]
            row = t.add_row(copy_from=self.stage_row)
            rec = mapfile.DungeonRecord(bytes(row.raw))
            rec.index = max(mapfile.DungeonRecord(bytes(r.raw)).index for r in t.rows) + 1
            rec.map_id = new
            for lang in mapfile.DungeonRecord.LANGS:
                rec.set_name(name, lang)
            row.raw[:] = rec.raw
            self.svc.mark_dirty(DUNGEON)
            self.svc.commit(DUNGEON, self)
        self._populate()
        info_box(self, "Stage cloned",
                 f"Created map{new:05d} and a new stage entry '{name}' in your mod.\n\n"
                 "Edit it like any other stage. How the game unlocks and lists brand-new stages isn't "
                 "fully known yet. If it doesn't show up in game, test your level by pointing an existing "
                 "stage at it instead (Database Editor → dungeon.dat → map id).")

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
