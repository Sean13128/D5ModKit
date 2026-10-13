"""Sprites & Colors: palette (color) editor with a live animated preview, sprite-sheet import/export."""
import colorsys
import os

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QComboBox, QTabWidget, QSlider, QCheckBox, QFileDialog,
                             QMessageBox, QColorDialog, QSpinBox, QGroupBox, QGridLayout, QInputDialog,
                             QDoubleSpinBox, QApplication, QMenu, QToolButton, QSizePolicy)

from d5lib import anm, sprites, database, dbpatch
from ..common import PageHeader, ImageView, SearchBox, Banner, pil_to_pixmap, error_box, info_box, checker_brush

ROLE = Qt.ItemDataRole.UserRole
UNIQUE_VARIANTS = ["Normal Color", "Extra Color 1", "Extra Color 2", "Extra Color 3", "Extra Color 4"]
TIER_VARIANTS = ["Tier 1 (default)", "Tier 2", "Tier 3", "Tier 4", "Tier 5", "Tier 6",
                 "Extra Color 1", "Extra Color 2", "Extra Color 3"]
BACKGROUNDS = {"Green": QColor(40, 90, 60), "Dark": QColor(24, 22, 32), "Checker": None,
               "White": QColor(255, 255, 255), "Magenta": QColor(255, 0, 255)}


def variant_names(n, generic):
    names = TIER_VARIANTS if generic else UNIQUE_VARIANTS
    return [names[i] if i < len(names) else f"Variant {i}" for i in range(n)]


class PaletteGrid(QWidget):
    """16x16 swatch grid. Click = select, shift/ctrl or drag = multi-select, double-click = edit colour.
    Row r = 'Part r' of the in-game precise colour editor (row 0 is never offered there)."""
    edited = pyqtSignal()
    selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pal = np.zeros((256, 4), np.uint8)
        self.sel = set()
        self.used = None
        self._anchor = None
        self.setMinimumSize(16 * 18 + 26, 16 * 18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(16 * 26 + 26, 16 * 26)

    def set_palette(self, pal, used=None):
        self.pal = pal.copy()
        self.used = used
        self.update()

    def _geom(self):
        c = max(10, min((self.width() - 26) // 16, self.height() // 16))
        return c, 26

    def _index_at(self, pos):
        c, ox = self._geom()
        x, y = (int(pos.x()) - ox) // c, int(pos.y()) // c
        if 0 <= x < 16 and 0 <= y < 16 and pos.x() >= ox:
            return y * 16 + x
        return None

    def paintEvent(self, e):
        p = QPainter(self)
        c, ox = self._geom()
        p.setPen(QColor(110, 105, 135))
        for r in range(16):
            p.drawText(0, r * c, ox - 4, c, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), str(r))
        for i in range(256):
            x, y = ox + (i % 16) * c, (i // 16) * c
            r, g, b, a = [int(v) for v in self.pal[i]]
            p.fillRect(x, y, c, c, QColor(70, 70, 78))
            p.fillRect(x, y, c // 2, c // 2, QColor(100, 100, 108))
            p.fillRect(x + c // 2, y + c // 2, c - c // 2, c - c // 2, QColor(100, 100, 108))
            p.fillRect(x, y, c, c, QColor(r, g, b, a))
            if self.used is not None and not self.used[i]:
                p.setPen(QPen(QColor(0, 0, 0, 110), 1))
                p.drawLine(x + 2, y + c - 3, x + c - 3, y + 2)
            if i in self.sel:
                p.setPen(QPen(QColor("#ffffff"), 2))
                p.drawRect(x + 1, y + 1, c - 3, c - 3)
        p.setPen(QPen(QColor(20, 18, 28), 1))
        for k in range(17):
            p.drawLine(ox, k * c, ox + 16 * c, k * c)
            p.drawLine(ox + k * c, 0, ox + k * c, 16 * c)

    def mousePressEvent(self, e):
        i = self._index_at(e.position())
        if i is None:
            # click on a row number: select that whole row (= one part of the in-game editor)
            c, ox = self._geom()
            r = int(e.position().y()) // c
            if 0 <= r < 16 and e.position().x() < ox:
                row = set(range(r * 16, r * 16 + 16))
                self.sel = self.sel | row if e.modifiers() & Qt.KeyboardModifier.ControlModifier else row
                self.update()
                self.selection_changed.emit()
            return
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier and self._anchor is not None:
            a, b = sorted((self._anchor, i))
            self.sel |= set(range(a, b + 1))
        elif mods & Qt.KeyboardModifier.ControlModifier:
            self.sel ^= {i}
            self._anchor = i
        else:
            self.sel = {i}
            self._anchor = i
        self.update()
        self.selection_changed.emit()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._anchor is not None:
            i = self._index_at(e.position())
            if i is not None:
                a, b = sorted((self._anchor, i))
                self.sel = set(range(a, b + 1))
                self.update()
                self.selection_changed.emit()
        i = self._index_at(e.position())
        if i is not None:
            r, g, b, a = [int(v) for v in self.pal[i]]
            used = "" if self.used is None else ("  · used" if self.used[i] else "  · unused")
            self.setToolTip(f"#{i} (row {i // 16}): #{r:02X}{g:02X}{b:02X}  alpha {a}{used}")

    def mouseDoubleClickEvent(self, e):
        i = self._index_at(e.position())
        if i is None:
            return
        r, g, b, a = [int(v) for v in self.pal[i]]
        col = QColorDialog.getColor(QColor(r, g, b, a), self, f"Colour #{i}",
                                    QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if col.isValid():
            targets = self.sel if i in self.sel and len(self.sel) > 1 else {i}
            for t in targets:
                self.pal[t] = (col.red(), col.green(), col.blue(), col.alpha())
            self.update()
            self.edited.emit()


class SpritesPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws, self.main = ws, main
        self.file = None          # AnmFile being edited
        self.preview = None       # AnmFile used for animation preview
        self.num = None           # sprite number
        self.vpath = None
        self.label = ""
        self.generic = False
        self.dirty = False
        self._time = 0.0
        self._anim_index = None
        self._frame_cache = {}
        self._bounds = None

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.addWidget(PageHeader("Sprites & Colors",
                                 "Recolor any character or monster with a live animated preview, or export the "
                                 "sprite sheets to repaint them."))
        split = QSplitter()
        split.setChildrenCollapsible(False)

        # ---------------- left: list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        self.mode = QComboBox()
        self.mode.addItems(["Characters & classes", "All sprite files"])
        self.mode.currentIndexChanged.connect(self._populate)
        ll.addWidget(self.mode)
        self.search = SearchBox("Search name, class or number…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        legend = QLabel("✎ = changed by a mod")
        legend.setObjectName("muted")
        ll.addWidget(legend)
        split.addWidget(left)

        # ---------------- middle: editor
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLabel("Pick a character on the left")
        self.title.setObjectName("cardTitle")
        top.addWidget(self.title, 1)
        top.addWidget(QLabel("Color:"))
        self.variant = QComboBox()
        self.variant.setMinimumWidth(150)
        self.variant.setToolTip("The palette you edit. Unique characters: Normal + Extra Color 1-4 (Strategy "
                                "Assembly → Change Colors). Generic classes: one palette per tier.")
        self.variant.currentIndexChanged.connect(self._variant_changed)
        top.addWidget(self.variant)
        self.b_portrait = QToolButton()
        self.b_portrait.setText("Portrait")
        self.b_portrait.setCheckable(True)
        self.b_portrait.setToolTip("Switch between the battle sprite and the portrait / cut-in picture "
                                   "(sprite number + 10000)")
        self.b_portrait.clicked.connect(self._toggle_portrait)
        top.addWidget(self.b_portrait)
        ml.addLayout(top)
        self.banner = Banner()
        self.banner.setVisible(False)
        ml.addWidget(self.banner)

        self.tabs = QTabWidget()
        ml.addWidget(self.tabs, 1)
        self._build_color_tab()
        self._build_sheet_tab()

        bot = QHBoxLayout()
        self.b_save = QPushButton("💾 Save")
        self.b_save.setObjectName("primary")
        self.b_save.setToolTip("Save this sprite into its mod (Ctrl+S). Install afterwards to see it in game.")
        self.b_save.clicked.connect(self.save)
        bot.addWidget(self.b_save)
        b = QPushButton("Discard changes")
        b.setToolTip("Reload the sprite without your unsaved edits")
        b.clicked.connect(self.discard)
        bot.addWidget(b)
        more = QPushButton("More ▾")
        menu = QMenu(more)
        menu.addAction("Revert to the game's original…", self.revert)
        menu.addAction("Clone as a new sprite…", self.clone)
        more.setMenu(menu)
        bot.addWidget(more)
        bot.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("warn")
        bot.addWidget(self.status)
        ml.addLayout(bot)
        split.addWidget(mid)

        # ---------------- right: live preview
        split.addWidget(self._build_preview())
        split.setSizes([250, 620, 420])
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 2)
        lay.addWidget(split, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._populated = False
        ws.mods_changed.connect(lambda: self._populated and self._populate())
        ws.active_mod_changed.connect(lambda _: self._update_banner())

    # ================================================================== layout parts
    def _build_preview(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        row = QHBoxLayout()
        t = QLabel("Live preview")
        t.setObjectName("cardTitle")
        row.addWidget(t)
        row.addStretch(1)
        self.b_play = QToolButton()
        self.b_play.setText("⏸")
        self.b_play.setToolTip("Play / pause")
        self.b_play.clicked.connect(self._toggle_play)
        row.addWidget(self.b_play)
        self.speed = QComboBox()
        for s in ("0.25×", "0.5×", "1×", "2×"):
            self.speed.addItem(s, float(s[:-1]))
        self.speed.setCurrentIndex(2)
        self.speed.setToolTip("Animation speed")
        row.addWidget(self.speed)
        self.bg = QComboBox()
        self.bg.addItems(list(BACKGROUNDS))
        self.bg.setToolTip("Background")
        self.bg.currentTextChanged.connect(self._bg)
        row.addWidget(self.bg)
        v.addLayout(row)
        self.anim_combo = QComboBox()
        self.anim_combo.setToolTip("Animation (id ending in 1 = facing front, 7 = facing back)")
        self.anim_combo.currentIndexChanged.connect(self._anim_changed)
        v.addWidget(self.anim_combo)
        self.anim_view = ImageView(smooth=True)
        self.anim_view.setBackgroundBrush(BACKGROUNDS["Green"])
        self.anim_view.clicked.connect(self._pick_color)
        v.addWidget(self.anim_view, 1)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._seek)
        row.addWidget(self.slider, 1)
        row.addWidget(QLabel("Zoom"))
        self.zoom = QSpinBox()
        self.zoom.setRange(0, 8)
        self.zoom.setSpecialValueText("Fit")
        self.zoom.setValue(0)
        self.zoom.setToolTip("Zoom (Fit = as big as the panel allows)")
        self.zoom.valueChanged.connect(lambda z: self._apply_zoom())
        row.addWidget(self.zoom)
        b = QToolButton()
        b.setText("Export…")
        b.setToolTip("Save this animation as PNG frames + GIF")
        b.clicked.connect(self.export_frames)
        row.addWidget(b)
        v.addLayout(row)
        tip = QLabel("Click the character to select every shade of that part (Ctrl+click adds), then use the "
                     "sliders. The preview follows your edits live.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        v.addWidget(tip)
        return w

    def _build_color_tab(self):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(6, 6, 6, 6)
        gl = QVBoxLayout()
        self.grid = PaletteGrid()
        self.grid.edited.connect(self._palette_edited)
        gl.addWidget(self.grid, 1)
        help_ = QLabel("Row numbers = Part N of the in-game precise editor (click one to select the row). "
                       "Double-click a swatch to set its color; drag / Shift-click selects a range.")
        help_.setObjectName("muted")
        help_.setWordWrap(True)
        gl.addWidget(help_)
        l.addLayout(gl, 1)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(6)
        self.sel_label = QLabel("Nothing selected — the sliders change every color.")
        self.sel_label.setObjectName("muted")
        self.sel_label.setWordWrap(True)
        side.addWidget(self.sel_label)
        adj = QGroupBox("Adjust")
        g = QGridLayout(adj)
        g.setVerticalSpacing(4)
        self.hue = QSlider(Qt.Orientation.Horizontal)
        self.hue.setRange(-180, 180)
        self.sat = QSlider(Qt.Orientation.Horizontal)
        self.sat.setRange(-100, 100)
        self.lig = QSlider(Qt.Orientation.Horizontal)
        self.lig.setRange(-100, 100)
        tips = {"Hue": "Turns the colors around the color wheel (red → yellow → green → blue …).",
                "Saturation": "Left = greyer, right = more vivid.",
                "Brightness": "Left = darker, right = lighter."}
        self.hsl_values = {}
        for r, (lab, sl) in enumerate([("Hue", self.hue), ("Saturation", self.sat), ("Brightness", self.lig)]):
            name = QLabel(lab)
            name.setToolTip(tips[lab])
            sl.setToolTip(tips[lab])
            val = QLabel("0")
            val.setMinimumWidth(32)
            self.hsl_values[lab] = val
            g.addWidget(name, r * 2, 0)
            g.addWidget(val, r * 2, 1, Qt.AlignmentFlag.AlignRight)
            g.addWidget(sl, r * 2 + 1, 0, 1, 2)
            sl.valueChanged.connect(lambda v, lab=lab: self._hsl_moved(lab, v))
            sl.sliderReleased.connect(self._hsl_released)
        reset = QPushButton("Undo adjustment")
        reset.setToolTip("Put the colors back to how they were before you moved the sliders")
        reset.clicked.connect(self._hsl_reset)
        g.addWidget(reset, 6, 0, 1, 2)
        side.addWidget(adj)
        self._hsl_base = None
        self._hsl_timer = QTimer(self)
        self._hsl_timer.setSingleShot(True)
        self._hsl_timer.timeout.connect(self._apply_hsl)
        self._hsl_full = QTimer(self)
        self._hsl_full.setSingleShot(True)
        self._hsl_full.timeout.connect(self._hsl_finish)
        self.grid.selection_changed.connect(self._selection_changed)

        sel = QGroupBox("Select")
        sg = QGridLayout(sel)
        for k, (text, fn) in enumerate([("All", self._sel_all), ("None", self._sel_none),
                                        ("Used only", self._sel_used), ("Invert", self._sel_invert)]):
            b = QPushButton(text)
            b.clicked.connect(fn)
            sg.addWidget(b, k // 2, k % 2)
        side.addWidget(sel)

        pal = QGroupBox("Palette")
        pg = QVBoxLayout(pal)
        for text, fn, tip in [("Copy from another color…", self._copy_variant,
                               "Copy the selected entries (or all) from another color variant"),
                              ("Add a new color variant", self._add_variant, "Append a copy of this palette"),
                              ("Export palette (PNG)…", self._export_pal, "16×16 swatch image"),
                              ("Import palette (PNG)…", self._import_pal, "16×16, 256×256 or 256×1 image")]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            pg.addWidget(b)
        side.addWidget(pal)
        side.addStretch(1)
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(240)
        l.addWidget(sw)
        self.tabs.addTab(w, "🎨 Colors")

    def _build_sheet_tab(self):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(6, 6, 6, 6)
        side = QVBoxLayout()
        self.sheets = QListWidget()
        self.sheets.setMaximumHeight(110)
        self.sheets.currentRowChanged.connect(self._sheet_changed)
        side.addWidget(self.sheets)
        for text, fn, tip in [
            ("Export sheet (indexed PNG)…", self.export_sheet_indexed,
             "256-color PNG keeping the exact palette — best for pixel-perfect editing"),
            ("Export sheet (color PNG)…", self.export_sheet, "Full-color PNG in the current color"),
            ("Import edited sheet…", self.import_sheet, "Load your repainted sheet back"),
            ("Export all sheets…", self.export_all_sheets, "Every sheet of this sprite into a folder"),
            ("Import all sheets…", self.import_all_sheets, "Import anmNNNNN_sheet_N.png files from a folder")]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            side.addWidget(b)
        self.keep_pal = QCheckBox("Import: build a new palette from my image")
        self.keep_pal.setToolTip("Off: colors are matched to the existing palette (keeps color variants working).\n"
                                 "On: a new palette is generated for the current color from your image.")
        side.addWidget(self.keep_pal)
        note = QLabel("Keep the same sheet size and layout — the game cuts the sprite parts out of fixed "
                      "rectangles. Paint in the Normal color.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        side.addWidget(note)
        side.addStretch(1)
        l.addLayout(side, 1)
        self.sheet_view = ImageView()
        l.addWidget(self.sheet_view, 3)
        self.tabs.addTab(w, "🖼 Sprite sheets")

    # ================================================================== list
    def on_show(self):
        if not self._populated:
            self._populated = True
            self._populate()
        if self._anim_index is not None and self.b_play.text() == "⏸":
            self.timer.start(33)

    def hideEvent(self, e):
        self.timer.stop()          # no animating while another page is shown
        super().hideEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        if self._anim_index is not None and self.b_play.text() == "⏸":
            self.timer.start(33)

    def _char_rows(self):
        """char.dat as the game will have it: vanilla + every enabled mod's patch (+ the active mod's)"""
        vp = f"{dbpatch.DB_ARCHIVE}/char.dat"
        t = database.load_table("char.dat", self.ws.fs.read(vp))
        mods = self.ws.mods.enabled_mods()
        if self.ws.active_mod and self.ws.active_mod.id not in {m.id for m in mods}:
            mods.append(self.ws.active_mod)
        for mod in mods:
            patch = mod.load_patch("db", "char.dat.json")
            if patch:
                dbpatch.apply_patch(t, patch)
        try:
            from ..dbservice import get_service
            svc = get_service(self.ws)
            if svc.is_dirty("char.dat"):         # unsaved edits on the Characters page
                t = svc.table("char.dat")
        except Exception:
            pass
        return t.rows

    def _mod_sprites(self):
        out = set()
        for mod in self.ws.mods.all_mods():
            for f in mod.list_files():
                name = f.rsplit("/", 1)[-1]
                if f.startswith("Anime/") and name.startswith("anm") and name[3:8].isdigit():
                    out.add(int(name[3:8]))
        return out

    def _populate(self):
        self.list.blockSignals(True)
        self.list.clear()
        modded = self._mod_sprites()
        if self.mode.currentIndex() == 0:
            from collections import Counter
            from d5lib import outfits
            rows = self._char_rows()
            names = Counter(n for n, _ in {((r["name_EN"], r["title_EN"]), r["sprite_id"]) for r in rows
                                           if r["sprite_id"] and r["name_EN"]})
            outfit_names, has_outfits = {}, set()
            for mod in self.ws.mods.all_mods():
                try:
                    for base, slot in outfits.load(mod):
                        if int(base) < 1000 and int(slot) != int(base):
                            outfit_names[int(slot)] = outfits.outfit_name(mod, slot)
                            has_outfits.add(int(base))
                except Exception:
                    pass
            seen = set()
            for r in rows:
                sprite, colour, name = r["sprite_id"], r["color_id"], r["name_EN"]
                if not sprite or not name:
                    continue
                title = r["title_EN"]
                key = (sprite, name, title)
                if key in seen:
                    continue
                seen.add(key)
                var = colour - sprite if 0 <= colour - sprite < 10 else 0
                generic = r["id"] >= 1000
                mark = "  ✎" if sprite in modded else ""
                extra = ""
                if names[(name, title)] > 1:           # same name twice (outfits, forms): tell them apart
                    extra = f"  [{outfit_names[r['id']]}]" if r["id"] in outfit_names else \
                        "  [Default]" if r["id"] in has_outfits else f"  [anm{sprite:05d}]"
                it = QListWidgetItem(f"{name} — {title}{extra}{mark}")
                it.setToolTip(f"class {r['id']} · sprite anm{sprite:05d} · color {var}")
                it.setData(ROLE, (sprite, var, f"{name} — {title}{extra}", generic))
                self.list.addItem(it)
        else:
            nums = sorted(set(sprites.all_sprite_numbers(self.ws.fs)) | modded)
            for num in nums:
                it = QListWidgetItem(f"anm{num:05d}{'  ✎' if num in modded else ''}")
                it.setData(ROLE, (num, 0, f"anm{num:05d}", False))
                self.list.addItem(it)
        self.list.blockSignals(False)
        self._filter(self.search.text())

    def _filter(self, t):
        t = t.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            num = it.data(ROLE)[0]
            it.setHidden(bool(t) and t not in it.text().lower() and t not in f"{num:05d}"
                         and t not in it.toolTip().lower())

    def _pick(self, it, prev=None):
        if not it:
            return
        num, var, label, generic = it.data(ROLE)
        if self.dirty and num != self.num and not self._ask_save(prev):
            return
        self._pending = (num, var, label, generic)
        if not hasattr(self, "_pick_timer"):
            self._pick_timer = QTimer(self)
            self._pick_timer.setSingleShot(True)
            self._pick_timer.timeout.connect(lambda: self.open_sprite(*self._pending))
        self._pick_timer.start(120)          # holding the arrow keys only loads the one you stop on

    def _ask_save(self, prev=None):
        r = QMessageBox.question(self, "Unsaved sprite", "Save your changes to this sprite first?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            if prev is not None:
                self.list.blockSignals(True)
                self.list.setCurrentItem(prev)
                self.list.blockSignals(False)
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save() is not False
        self.dirty = False
        return True

    def unsaved_label(self):
        return f"anm{self.num:05d}" if self.num is not None else ""

    def open_sprite(self, num, var=0, label="", generic=None):
        vpath = None
        for v in (sprites.sprite_vpath(self.ws.fs, num, self.ws.language), f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"):
            if self.ws.exists(v):
                vpath = v
                break
        if vpath is None:
            self.title.setText(f"anm{num:05d} does not exist")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.file = anm.load(self.ws.read(vpath))
            self.preview = sprites.preview_file(self.ws.fs, self.file, self.ws.log)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            error_box(self, "Could not open sprite", e)
            return
        QApplication.restoreOverrideCursor()
        self.vpath, self.num, self.dirty = vpath, num, False
        if generic is not None:
            self.generic = generic
        self.label = label or f"anm{num:05d}"
        self.b_portrait.blockSignals(True)
        self.b_portrait.setChecked(num >= 10000)
        self.b_portrait.blockSignals(False)
        self._hsl_rebase()
        self.variant.blockSignals(True)
        self.variant.clear()
        nv = max(1, len(self.file.palettes))
        for i, n in enumerate(variant_names(nv, self.generic)):
            self.variant.addItem(f"{n}", i)
        self.variant.setCurrentIndex(min(var, nv - 1))
        self.variant.blockSignals(False)
        self.sheets.clear()
        for i, t in enumerate(self.file.textures):
            self.sheets.addItem(f"Sheet {i}  ·  {t.width}×{t.height}  ·  {'256 colors' if t.indexed else 'true color'}")
        if self.sheets.count():
            self.sheets.setCurrentRow(0)
        self._fill_anims()
        self._refresh_palette()
        self._update_title()
        self._update_banner()

    def _fill_anims(self):
        self.anim_combo.blockSignals(True)
        self.anim_combo.clear()
        best = None
        for a in anm.list_animations(self.preview):
            if a["layers"] == 0:
                continue
            face = "front" if a["id"] % 10 == 1 else "back" if a["id"] % 10 == 7 else ""
            loop = "  ⟲" if a["loop"] else ""
            self.anim_combo.addItem(f"Animation {a['id']}{'  · ' + face if face else ''}  · {a['length']} f{loop}",
                                    a["index"])
            if loop and best is None:                 # the first looping animation: the standing pose
                best = self.anim_combo.count() - 1
        self.anim_combo.blockSignals(False)
        self._anim_index = None
        if self.anim_combo.count():
            best = best or 0
            self.anim_combo.setCurrentIndex(best)
            self._anim_changed(best)
        else:
            self.anim_view.set_image(anm.texture_to_image(self.file, 0, self._global_pal()) if self.file.textures
                                     else None, fit=True)

    def _update_title(self):
        self.title.setText(f"{self.label}   ·   anm{self.num:05d}")
        self.status.setText("● unsaved changes" if self.dirty else "")

    def _target_mod(self):
        """(mod the save goes to, why) — the mod that already has this sprite, else the active one"""
        owner = self.ws.owner(self.vpath) if self.vpath else None
        return owner or self.ws.active_mod

    def _update_banner(self):
        if not self.vpath:
            self.banner.setVisible(False)
            return
        owner = self.ws.owner(self.vpath)
        active = self.ws.active_mod
        enabled = set(self.ws.mods.load_order())
        if owner:
            text = f"This sprite comes from your mod <b>{owner.name}</b> — Save updates it there."
            warn = owner.id not in enabled
            if warn:
                text += " ⚠ That mod is disabled, so it is not installed."
        elif active:
            text = f"Game's original sprite — Save puts your version into <b>{active.name}</b>."
            warn = active.id not in enabled
            if warn:
                text += " ⚠ That mod is disabled."
        else:
            text = "Game's original sprite — Save asks for a mod to keep your version in."
            warn = False
        self.banner.show_text(text, warn)

    # ================================================================== animation
    def _cur_variant(self):
        return max(0, self.variant.currentIndex())

    def _global_pal(self):
        return min(self._cur_variant(), max(0, len(self.file.palettes) - 1)) if self.file else 0

    def _anim_changed(self, row):
        if row < 0 or not self.preview:
            return
        idx = self.anim_combo.itemData(row)
        info = anm.list_animations(self.preview)[idx]
        self._anim_index = idx
        self._length = max(1, info["length"])
        self._loop = info["loop"]
        self.slider.blockSignals(True)
        self.slider.setRange(0, self._length)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self._frame_cache = {}
        items = [anm.evaluate(self.preview, idx, t) for t in range(0, self._length + 1, max(1, self._length // 40))]
        flat = [it for x in items for it in x]
        self._bounds = anm.item_bounds(flat) if flat else None
        self._time = 0.0
        self._show_time(0)
        self._apply_zoom()
        if self.b_play.text() == "⏸" and self.isVisible():
            self.timer.start(33)

    def _apply_zoom(self):
        z = self.zoom.value()
        if not z and self._bounds:
            x0, y0, x1, y1 = self._bounds
            vw, vh = self.anim_view.viewport().width() - 8, self.anim_view.viewport().height() - 8
            z = max(1.0, min(vw / max(1, x1 - x0), vh / max(1, y1 - y0)))
            z = max(1, int(z * 2) / 2)             # half steps keep pixels crisp enough
        self.anim_view.set_zoom(z or 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.zoom.value() == 0 and self._anim_index is not None:
            self._apply_zoom()

    def _frame(self, t):
        key = (self._anim_index, int(t), self._cur_variant())
        pm = self._frame_cache.get(key)
        if pm is None:
            items = anm.evaluate(self.preview, self._anim_index, int(t))
            img, _ = anm.render_items(self.preview, items, self._cur_variant(), bounds=self._bounds)
            pm = pil_to_pixmap(img)
            if len(self._frame_cache) > 400:
                self._frame_cache.clear()
            self._frame_cache[key] = pm
        return pm

    def _show_time(self, t):
        if not self.preview or self._anim_index is None:
            return
        try:
            pm = self._frame(t)
        except Exception as e:
            self.status.setText(f"render error: {e}")
            return
        z = self.anim_view.transform()
        self.anim_view.set_image(pm)
        self.anim_view.setTransform(z)

    def _toggle_play(self):
        playing = self.b_play.text() != "⏸"
        self.b_play.setText("⏸" if playing else "▶")
        if playing:
            self.timer.start(33)
        else:
            self.timer.stop()

    def _tick(self):
        if self._anim_index is None:
            return
        self._time += 2 * (self.speed.currentData() or 1.0)
        end = self._loop[1] if self._loop else self._length
        if self._time > end:
            self._time = float(self._loop[0] if self._loop else 0)
        self.slider.blockSignals(True)
        self.slider.setValue(int(self._time))
        self.slider.blockSignals(False)
        self._show_time(self._time)

    def _seek(self, v):
        self._time = float(v)
        self._show_time(v)

    def _bg(self, name):
        col = BACKGROUNDS[name]
        for v in (self.anim_view, self.sheet_view):
            v.setBackgroundBrush(checker_brush() if col is None else col)

    def export_frames(self):
        if not self.preview or self._anim_index is None:
            return
        d = QFileDialog.getExistingDirectory(self, "Export animation frames (PNG sequence + GIF)")
        if not d:
            return
        end = self._loop[1] if self._loop else self._length
        imgs = []
        for t in range(0, end + 1, 2):
            items = anm.evaluate(self.preview, self._anim_index, t)
            img, _ = anm.render_items(self.preview, items, self._cur_variant(), bounds=self._bounds)
            imgs.append(img)
            img.save(os.path.join(d, f"frame_{t:04d}.png"))
        if imgs:
            imgs[0].save(os.path.join(d, "animation.gif"), save_all=True, append_images=imgs[1:],
                         duration=66, loop=0, disposal=2)
        self.ws.log(f"Exported {len(imgs)} frames to {d}")

    def _toggle_portrait(self):
        if self.num is None:
            return
        if self.dirty and not self._ask_save():
            self.b_portrait.setChecked(self.num >= 10000)
            return
        if self.num < 10000:
            n = self.num + 10000
            if not self.ws.exists(f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs") and \
                    n not in sprites.all_sprite_numbers(self.ws.fs):
                QMessageBox.information(self, "Portrait", f"No portrait (anm{n:05d}) exists for this sprite.")
                self.b_portrait.setChecked(False)
                return
            self.open_sprite(n, self._cur_variant(), self.label.replace(" (portrait)", "") + " (portrait)")
        else:
            self.open_sprite(self.num - 10000, self._cur_variant(), self.label.replace(" (portrait)", ""))

    # ================================================================== sheets
    def _sheet_changed(self, row):
        if row < 0 or not self.file:
            return
        self.sheet_view.set_image(anm.texture_to_image(self.file, row, self._global_pal()), fit=True)

    def _variant_changed(self, _):
        self._hsl_rebase()
        self._frame_cache = {}
        self._sheet_changed(self.sheets.currentRow())
        self._refresh_palette()
        self._show_time(self._time)

    def _cur_sheet(self):
        r = self.sheets.currentRow()
        if not self.file or r < 0:
            QMessageBox.information(self, "Sprite sheet", "Pick a sprite and a sheet first.")
            return None
        return r

    def export_sheet(self):
        r = self._cur_sheet()
        if r is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export sheet", f"anm{self.num:05d}_sheet{r}.png", "PNG (*.png)")
        if p:
            anm.texture_to_image(self.file, r, self._global_pal()).save(p)

    def _indexed_image(self, r):
        t = self.file.textures[r]
        if not t.indexed:
            return anm.texture_to_image(self.file, r, 0)
        idx = anm.texture_indices(self.file, r)
        img = Image.fromarray(idx, "P")
        pal = anm.get_palette(self.file, self._global_pal())
        img.putpalette(pal[:, :3].flatten().tolist())
        img.info["transparency"] = bytes(int(a) for a in pal[:, 3])
        return img

    def export_sheet_indexed(self):
        r = self._cur_sheet()
        if r is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export indexed sheet", f"anm{self.num:05d}_sheet{r}_indexed.png",
                                           "PNG (*.png)")
        if p:
            self._indexed_image(r).save(p)

    def _import_into(self, r, path):
        img = Image.open(path)
        t = self.file.textures[r]
        if img.size != (t.width, t.height):
            q = QMessageBox.question(self, "Different size",
                                     f"Sheet {r} is {t.width}×{t.height}, your image is {img.width}×{img.height}.\n"
                                     "Sprite parts are cut from fixed rectangles, so a different size usually "
                                     "breaks the sprite. Import anyway?")
            if q != QMessageBox.StandardButton.Yes:
                return False
        anm.image_to_texture(self.file, r, img, self._global_pal(), replace_palette=self.keep_pal.isChecked())
        return True

    def import_sheet(self):
        r = self._cur_sheet()
        if r is None:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Import sheet", "", "Images (*.png *.bmp *.tga)")
        if p:
            try:
                if self._import_into(r, p):
                    self._changed()
            except Exception as e:
                error_box(self, "Import failed", e)

    def export_all_sheets(self):
        if not self.file:
            return
        d = QFileDialog.getExistingDirectory(self, "Export all sheets to")
        if d:
            for r in range(len(self.file.textures)):
                self._indexed_image(r).save(os.path.join(d, f"anm{self.num:05d}_sheet_{r}.png"))
            self.ws.log(f"Exported {len(self.file.textures)} sheets to {d}")

    def import_all_sheets(self):
        if not self.file:
            return
        d = QFileDialog.getExistingDirectory(self, "Folder with anmNNNNN_sheet_N.png files")
        if not d:
            return
        n = 0
        for r in range(len(self.file.textures)):
            p = os.path.join(d, f"anm{self.num:05d}_sheet_{r}.png")
            if os.path.exists(p) and self._import_into(r, p):
                n += 1
        if n:
            self._changed()
        self.ws.log(f"Imported {n} sheet(s)")

    # ================================================================== colors
    def _refresh_palette(self):
        if not self.file or not self.file.palettes:
            self.grid.set_palette(np.zeros((256, 4), np.uint8))
            return
        pal = anm.get_palette(self.file, self._global_pal())
        sig = tuple(id(t.data) for t in self.file.textures)
        if getattr(self, "_used_sig", None) != sig:
            used = np.zeros(256, bool)
            for t in self.file.textures:
                if t.indexed:
                    used[np.bincount(np.frombuffer(t.data, np.uint8), minlength=256) > 0] = True
            self._used, self._used_sig = used, sig
        self.grid.set_palette(pal, self._used)

    def _preview_indices(self):
        """(palette index image, colour image) of the frame on screen (rendered once more with a code palette)"""
        if not self.preview or self._anim_index is None:
            return None, None
        gp = self._cur_variant()
        pals = self.preview.palettes
        if gp >= len(pals):
            return None, None
        code = np.zeros((256, 4), np.uint8)
        code[:, 0] = np.arange(256)
        code[1:, 3] = 255
        items = anm.evaluate(self.preview, self._anim_index, int(self._time))
        colour, _ = anm.render_items(self.preview, items, gp, bounds=self._bounds)
        old = pals[gp].data
        try:
            pals[gp].data = anm._rgba_to_argb(code).tobytes()
            img, _ = anm.render_items(self.preview, items, gp, bounds=self._bounds, apply_color=False)
        finally:
            pals[gp].data = old
        a = np.asarray(img)
        idx = np.where(a[:, :, 3] > 200, a[:, :, 0], 0)
        return idx, np.asarray(colour)

    def _pick_color(self, x, y):
        """Click on the preview: select every palette shade of the clicked part (flood fill over pixels of a
        similar colour, stopping at outlines / other colours)."""
        from scipy import ndimage
        idx, col = self._preview_indices()
        if idx is None or not (0 <= y < idx.shape[0] and 0 <= x < idx.shape[1]) or not idx[y, x]:
            return
        rgb = col[:, :, :3].astype(np.float32) / 255.0
        mx, mn = rgb.max(2), rgb.min(2)
        light = (mx + mn) / 2
        sat = np.where(mx - mn > 1e-6, (mx - mn) / (1 - np.abs(2 * light - 1) + 1e-6), 0)
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        hue = (np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b) / (2 * np.pi)) % 1.0
        h0, s0, l0 = hue[y, x], sat[y, x], light[y, x]
        if s0 < 0.15:
            mask = (sat < 0.2) & (np.abs(light - l0) < 0.3)
        else:
            dh = np.abs((hue - h0 + 0.5) % 1.0 - 0.5)
            mask = (dh < 0.07) & (sat > 0.12) & (np.abs(light - l0) < 0.35)
        mask &= idx > 0
        lab, _ = ndimage.label(mask)
        region = lab == lab[y, x] if lab[y, x] else np.zeros_like(mask)
        region[y, x] = True
        fam = set()
        for v in np.unique(idx[region]):
            if not v:
                continue
            pr, pg, pb = self.grid.pal[int(v), :3] / 255.0
            h, l, s_ = colorsys.rgb_to_hls(pr, pg, pb)
            ok = (s_ < 0.2 and abs(l - l0) < 0.3) if s0 < 0.15 else \
                (abs((h - h0 + 0.5) % 1.0 - 0.5) < 0.07 and s_ > 0.12 and abs(l - l0) < 0.35)
            if ok:
                fam.add(int(v))
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self.grid.sel |= fam
        else:
            self.grid.sel = fam
        self.grid.update()
        self._selection_changed()

    def _selection_changed(self):
        self._hsl_rebase()
        n = len(self.grid.sel)
        if not n:
            self.sel_label.setText("Nothing selected — the sliders change every color.")
        else:
            rows = sorted({i // 16 for i in self.grid.sel})
            self.sel_label.setText(f"{n} color(s) selected (row{'s' if len(rows) > 1 else ''} "
                                   f"{', '.join(map(str, rows[:8]))}{'…' if len(rows) > 8 else ''}).")

    def _palette_edited(self):
        self._hsl_rebase()
        anm.set_palette(self.file, self._global_pal(), self.grid.pal)
        self._changed()

    def _targets(self):
        return sorted(self.grid.sel) if self.grid.sel else list(range(256))

    # ------------------------------------------------------------ hue / saturation / brightness sliders
    def _hsl_moved(self, lab, v):
        self.hsl_values[lab].setText(f"{v:+d}" if v else "0")
        if self.file:
            self._hsl_timer.start(30)

    def _hsl_released(self):
        self._hsl_timer.start(0)

    def _hsl_rebase(self, *_):
        """Start a new adjustment: the current colours become the base, sliders back to the middle."""
        self._hsl_base = None
        for sl, lab in ((self.hue, "Hue"), (self.sat, "Saturation"), (self.lig, "Brightness")):
            sl.blockSignals(True)
            sl.setValue(0)
            sl.blockSignals(False)
            self.hsl_values[lab].setText("0")

    def _hsl_reset(self):
        if self._hsl_base is not None:
            base = self._hsl_base[0]
            self._hsl_rebase()
            self.grid.set_palette(base, self.grid.used)
            self._palette_edited()
        else:
            self._hsl_rebase()

    def _apply_hsl(self):
        if not self.file:
            return
        gp = self._global_pal()
        if self._hsl_base is None or self._hsl_base[2] != (id(self.file), gp):
            self._hsl_base = (self.grid.pal.copy(), tuple(self._targets()), (id(self.file), gp))
        base, targets, _ = self._hsl_base
        dh, ds, dl = self.hue.value() / 360.0, self.sat.value() / 100.0, self.lig.value() / 100.0
        pal = base.copy()
        for i in targets:
            r, g, b, a = pal[i] / 255.0
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            h = (h + dh) % 1.0
            s = min(1, max(0, s + ds * (1 - s if ds > 0 else s)))
            l = min(1, max(0, l + dl * (1 - l if dl > 0 else l)))
            r, g, b = colorsys.hls_to_rgb(h, l, s)
            pal[i, :3] = np.clip(np.round(np.array([r, g, b]) * 255), 0, 255)
        # fast path while dragging: palette + the frame on screen only
        self.grid.set_palette(pal, self.grid.used)
        anm.set_palette(self.file, gp, pal)
        if self.preview is not None and self.preview is not self.file and gp < len(self.preview.palettes):
            anm.set_palette(self.preview, gp, pal)
        self.dirty = True
        self._frame_cache = {}
        self._show_time(self._time)
        self._update_title()
        self._hsl_full.start(350)

    def _hsl_finish(self):
        if self.file:
            self._sheet_changed(self.sheets.currentRow())

    def _sel_all(self):
        self.grid.sel = set(range(256))
        self.grid.update()
        self._selection_changed()

    def _sel_none(self):
        self.grid.sel = set()
        self.grid.update()
        self._selection_changed()

    def _sel_used(self):
        used = getattr(self, "_used", None)
        self.grid.sel = {i for i in range(1, 256) if used is None or used[i]}
        self.grid.update()
        self._selection_changed()

    def _sel_invert(self):
        self.grid.sel = set(range(256)) - self.grid.sel
        self.grid.update()
        self._selection_changed()

    def _copy_variant(self):
        if not self.file or len(self.file.palettes) < 2:
            return
        names = [self.variant.itemText(i) for i in range(self.variant.count())]
        s, ok = QInputDialog.getItem(self, "Copy colors", "Copy the selected entries (or all) from:", names, 0, False)
        if ok:
            src = anm.get_palette(self.file, names.index(s))
            pal = self.grid.pal.copy()
            for i in self._targets():
                pal[i] = src[i]
            self.grid.set_palette(pal, self.grid.used)
            self._palette_edited()

    def _add_variant(self):
        if not self.file:
            return
        anm.add_palette(self.file, copy_from=self._global_pal())
        n = len(self.file.palettes)
        self.variant.addItem(f"Variant {n - 1} (new)", n - 1)
        self.variant.setCurrentIndex(self.variant.count() - 1)
        self._changed()
        info_box(self, "New color variant", "A new color variant was added (copied from the current one). "
                                           "Whether the game uses more variants than the original count hasn't "
                                           "been verified — test in game.")

    def _export_pal(self):
        if not self.file:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export palette", f"anm{self.num:05d}_pal{self._global_pal()}.png",
                                           "PNG (*.png)")
        if p:
            Image.fromarray(self.grid.pal.reshape(16, 16, 4), "RGBA").resize((256, 256), Image.NEAREST).save(p)

    def _import_pal(self):
        if not self.file:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Import palette (16×16 or 256×1 image)", "", "PNG (*.png)")
        if not p:
            return
        img = Image.open(p).convert("RGBA")
        if img.size == (256, 256):
            img = img.resize((16, 16), Image.NEAREST)
        arr = np.asarray(img, np.uint8).reshape(-1, 4)
        if len(arr) != 256:
            QMessageBox.warning(self, "Palette", "Image must be 16×16, 256×256 (swatches) or 256×1 pixels.")
            return
        self.grid.set_palette(arr, self.grid.used)
        self._palette_edited()

    # ================================================================== save
    def _changed(self):
        self.dirty = True
        self._frame_cache = {}
        self.preview = sprites.preview_file(self.ws.fs, self.file)
        self._sheet_changed(self.sheets.currentRow())
        self._refresh_palette()
        self._show_time(self._time)
        self._update_title()

    def save(self):
        if not self.file:
            return False
        mod = self._target_mod()
        if mod is None:
            mod = self.ws.require_mod(self)
            if mod is None:
                return False
        owner = self.ws.owner(self.vpath)
        active = self.ws.active_mod
        if owner and active and owner.id != active.id:
            box = QMessageBox(self)
            box.setWindowTitle("Which mod?")
            box.setText(f"This sprite belongs to your mod '{owner.name}' (that copy is the one the game uses), but "
                        f"your edits currently go to '{active.name}'.")
            b_owner = box.addButton(f"Save into '{owner.name}'", QMessageBox.ButtonRole.AcceptRole)
            b_active = box.addButton(f"Save into '{active.name}'", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(b_owner)
            box.exec()
            if box.clickedButton() == b_active:
                mod = active
            elif box.clickedButton() != b_owner:
                return False
        try:
            data = self.file.to_bytes()
            anm.parse(data)  # validate
            self.ws.write(self.vpath, data, self, mod=mod)
            comp = sprites.companion(self.num)
            extra = ""
            if comp is not None:
                for cpath in (sprites.sprite_vpath(self.ws.fs, comp, self.ws.language),
                              f"Anime/ANM_HI_JP.dat/anm{comp:05d}.lzs"):
                    if self.ws.exists(cpath):
                        other = anm.load(self.ws.read(cpath))
                        if sprites.copy_images(self.file, other):
                            self.ws.write(cpath, other.to_bytes(), self, mod=mod)
                            extra = f" (+ its copy anm{comp:05d})"
                        break
            self.dirty = False
            self._update_title()
            self._update_banner()
            disabled = mod.id not in self.ws.mods.load_order()
            self.ws.log(f"Saved anm{self.num:05d}{extra} into '{mod.name}'." +
                        (" ⚠ That mod is disabled — enable it on Home to install it." if disabled else
                         " Install (bottom left) to see it in game."))
            self._populate_marks()
            return True
        except Exception as e:
            error_box(self, "Save failed", e)
            return False

    def _populate_marks(self):
        modded = self._mod_sprites()
        for i in range(self.list.count()):
            it = self.list.item(i)
            num = it.data(ROLE)[0]
            text = it.text().replace("  ✎", "")
            it.setText(text + ("  ✎" if num in modded else ""))

    def discard(self):
        if self.num is not None:
            self.dirty = False
            self.open_sprite(self.num, self._cur_variant(), self.label)

    def revert(self):
        if self.num is None:
            return
        owner = self.ws.owner(self.vpath)
        try:
            self.ws.fs.read(self.vpath)
            in_game = True
        except KeyError:
            in_game = False
        if not in_game:
            QMessageBox.information(
                self, "Revert to original",
                f"anm{self.num:05d} is not part of the original game — it only exists in your mod (a new character "
                "or outfit sprite), so there is no original to go back to.\n\nTo undo unsaved edits use 'Discard "
                "changes'.")
            return
        if not owner:
            QMessageBox.information(self, "Revert to original", "This sprite is already the game's original.")
            return
        if QMessageBox.question(self, "Revert to original",
                                f"Remove your version of anm{self.num:05d} from '{owner.name}' and use the game's "
                                "original sprite again?") != QMessageBox.StandardButton.Yes:
            return
        self.ws.revert(self.vpath, owner)
        comp = sprites.companion(self.num)
        if comp is not None:
            self.ws.revert(sprites.sprite_vpath(self.ws.fs, comp, self.ws.language), owner)
        self.dirty = False
        self.open_sprite(self.num, self._cur_variant(), self.label)
        self._populate_marks()

    def clone(self):
        if not self.file:
            return
        free = sprites.free_sprite_numbers(self.ws.fs, 9000, 1)[0]
        n, ok = QInputDialog.getInt(self, "Clone sprite", "New sprite number (must end in 0 and be unused):",
                                    free, 10, 65530, 10)
        if not ok:
            return
        if n in sprites.all_sprite_numbers(self.ws.fs) or n in self._mod_sprites():
            QMessageBox.warning(self, "Clone", f"anm{n:05d} already exists.")
            return
        clone = anm.parse(self.file.to_bytes())
        for b in clone.blocks:
            if b.id == self.num:
                b.id = n
        if not self.ws.write(f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs", clone.to_bytes(), self):
            return
        comp = sprites.companion(self.num)
        if comp is not None:
            try:
                other = anm.load(self.ws.read(sprites.sprite_vpath(self.ws.fs, comp, self.ws.language)))
                sprites.copy_images(self.file, other)
                for b in other.blocks:
                    if b.id == comp:
                        b.id = n + 1
                self.ws.write(f"Anime/ANM_HI_JP.dat/anm{n + 1:05d}.lzs", other.to_bytes(), self)
            except KeyError:
                pass
        info_box(self, "Sprite cloned",
                 f"Created anm{n:05d} (and anm{n + 1:05d}) in your mod.\n\n"
                 f"To use it, set a character's sprite to {n} on the Characters page.")
