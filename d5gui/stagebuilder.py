"""Building a battlefield out of blocks on the Stages page: the block library (the game's Item World pieces by
theme, and cut-outs of any map), the tools (place, move, turn, lift, delete) and the build itself
(d5lib.mapbuild: the list of placements the composed map is made from, saved with the map in its mod as
patches/stages/build_<map>.json so it can be changed again later)."""
import os

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QListView, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
                             QButtonGroup, QGroupBox, QMessageBox)

from d5lib import mapbuild, mapfile
from . import mapthumbs
from .newstage import _Painter

ROLE = Qt.ItemDataRole.UserRole
ICON = (112, 78)
TOOL_PLACE, TOOL_MOVE = 10, 11            # ids in the Stages page's tool group (0-4 are the unit tools)


class CutoutDialog(QDialog):
    """a rectangle of a map as a block"""

    def __init__(self, parent, stages, current=None):
        super().__init__(parent)
        self.setWindowTitle("A piece of a map")
        f = QFormLayout(self)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        intro = QLabel("Cut a rectangle out of any map: its terrain, rocks and walls come along as one block "
                       "(panels x, y and the size, counted on the map's top-down grid).")
        intro.setWordWrap(True)
        f.addRow(intro)
        self.map = QComboBox()
        for label, mid, _ in stages:
            self.map.addItem(f"{label}  (map{mid:05d})", mid)
        if current is not None and self.map.findData(current) >= 0:
            self.map.setCurrentIndex(self.map.findData(current))
        f.addRow("Map", self.map)
        self.x0, self.y0, self.w, self.h = QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox()
        for s, v in ((self.x0, 0), (self.y0, 0), (self.w, 5), (self.h, 5)):
            s.setRange(0 if s in (self.x0, self.y0) else 1, 127)
            s.setValue(v)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        for lab, s in (("x", self.x0), ("y", self.y0), ("width", self.w), ("height", self.h)):
            hl.addWidget(QLabel(lab))
            hl.addWidget(s)
        f.addRow("Rectangle", row)
        self.whole = QPushButton("The whole map")
        self.whole.clicked.connect(self._whole)
        f.addRow("", self.whole)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.sizes = {}

    def _whole(self):
        mid = self.map.currentData()
        size = self.sizes.get(mid)
        if size:
            self.x0.setValue(0)
            self.y0.setValue(0)
            self.w.setValue(size[0])
            self.h.setValue(size[1])

    def key(self):
        return (int(self.map.currentData()), self.x0.value(), self.y0.value(),
                self.x0.value() + self.w.value(), self.y0.value() + self.h.value())


class LookDialog(QDialog):
    """a block's tint and the pictures on its textures"""

    def __init__(self, parent, pl, piece, pictures_dir):
        super().__init__(parent)
        self.setWindowTitle("The block's look")
        self.pictures_dir = pictures_dir
        self.piece = piece
        tint, tex = mapbuild.look_of(pl)
        self.tint = tint
        self.tex = dict(tex)
        f = QFormLayout(self)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        intro = QLabel("A tint darkens or colours the block (white = as it is). A picture replaces one of the "
                       "block's textures: <b>From the game…</b> takes a Netherworld ground or a stage's own texture "
                       "(fitted: on a stone top it becomes the tiled part, a wall strip is cut from it), "
                       "<b>Picture…</b> a file of yours, scaled to the texture's size (the stone blocks have a "
                       "160×128 top picture, the left 128×128 of it tiled, and a 128×32 wall strip).")
        intro.setWordWrap(True)
        f.addRow(intro)
        self.tint_btn = QPushButton()
        self.tint_btn.clicked.connect(self._pick_tint)
        self._show_tint()
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.tint_btn)
        b = QPushButton("No tint")
        b.clicked.connect(lambda: (setattr(self, "tint", None), self._show_tint()))
        hl.addWidget(b)
        hl.addStretch(1)
        f.addRow("Tint", row)
        self.tex_labels = {}
        for i, entry in enumerate(piece.textures):
            if not entry:
                continue
            try:
                from d5lib import obf
                t = obf.Texture(entry)
                size = f"{t.width}×{t.height}"
            except Exception:
                size = "?"
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            lab = QLabel()
            self.tex_labels[i] = lab
            hl.addWidget(lab, 1)
            b = QPushButton("From the game…")
            b.setToolTip("A Netherworld ground tile or a texture of one of the game's stages")
            b.clicked.connect(lambda _, k=i: self._from_game(k))
            hl.addWidget(b)
            b = QPushButton("Picture…")
            b.clicked.connect(lambda _, k=i: self._pick_picture(k))
            hl.addWidget(b)
            b = QPushButton("The block's own")
            b.clicked.connect(lambda _, k=i: (self.tex.pop(k, None), self._show_tex()))
            hl.addWidget(b)
            f.addRow(f"Texture {i} ({size})", row)
        self._show_tex()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _show_tint(self):
        t = self.tint
        self.tint_btn.setText("white (as it is)" if t is None else f"rgb({t[0]}, {t[1]}, {t[2]})")
        if t is not None:
            self.tint_btn.setStyleSheet(f"background: rgb({t[0]}, {t[1]}, {t[2]}); color: "
                                        f"{'black' if sum(t) > 380 else 'white'};")
        else:
            self.tint_btn.setStyleSheet("")

    def _show_tex(self):
        for i, lab in self.tex_labels.items():
            lab.setText(self.tex.get(i) or "the block's own")

    def _pick_tint(self):
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog
        t = self.tint or (255, 255, 255)
        c = QColorDialog.getColor(QColor(*t), self, "Tint")
        if c.isValid():
            self.tint = (c.red(), c.green(), c.blue())
            self._show_tint()

    def _pick_picture(self, k):
        from PyQt6.QtWidgets import QFileDialog
        import shutil
        if not self.pictures_dir:
            QMessageBox.information(self, "Picture", "Save the stage once first (the pictures go into its mod).")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Picture", "", "Pictures (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        os.makedirs(self.pictures_dir, exist_ok=True)
        name = os.path.basename(path)
        dst = os.path.join(self.pictures_dir, name)
        if os.path.abspath(dst) != os.path.abspath(path):
            shutil.copy2(path, dst)
        self.tex[k] = name
        self._show_tex()

    def _from_game(self, k):
        from .gametex import GameTextureDialog, fit
        if not self.pictures_dir:
            QMessageBox.information(self, "Picture", "Save the stage once first (the pictures go into its mod).")
            return
        page = getattr(self.parent(), "page", None)
        stages = []
        try:
            seen = set()
            for r in page.svc.table("dungeon.dat").rows:
                rec = mapfile.DungeonRecord(bytes(r.raw))
                if rec.map_id and rec.map_id not in seen and rec.name():
                    seen.add(rec.map_id)
                    stages.append((rec.map_id, f"{rec.name()} (map {rec.map_id})"))
        except Exception:
            pass
        dlg = GameTextureDialog(self, page.ws, stages)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
            return
        label, img = dlg.choice
        try:
            pic = fit(img, self.piece.textures[k])
        except Exception as e:
            QMessageBox.warning(self, "Picture", f"That picture can't be used here: {e}")
            return
        os.makedirs(self.pictures_dir, exist_ok=True)
        name = "game_" + "".join(c if c.isalnum() else "_" for c in label).strip("_")[:60] + f"_t{k}.png"
        pic.save(os.path.join(self.pictures_dir, name))
        self.tex[k] = name
        self._show_tex()

    def apply(self, pl):
        if self.tint is None:
            pl.pop("tint", None)
        else:
            pl["tint"] = [int(v) for v in self.tint]
        if self.tex:
            pl["tex"] = {str(k): v for k, v in self.tex.items()}
        else:
            pl.pop("tex", None)


class BuilderPanel(QWidget):
    """the block library and the tools; the page owns the build and recomposes the map"""
    changed = pyqtSignal()                 # the build changed (recompose)
    marks_changed = pyqtSignal()           # only the highlights changed (redraw)

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.build = None
        self.lib = None
        self.sel = None                    # index of the chosen placement
        self.rot = 0
        self.lift = 0
        self.hover = None
        self._painter = None
        self._thumbs = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Blocks")
        bl = QVBoxLayout(box)
        top = QHBoxLayout()
        size_lab = QLabel("Map size")
        size_lab.setToolTip("Panels across and down (the grid the blocks go on)")
        top.addWidget(size_lab)
        self.w_spin, self.h_spin = QSpinBox(), QSpinBox()
        for s in (self.w_spin, self.h_spin):
            s.setRange(1, 64)
            s.valueChanged.connect(self._size_changed)
        top.addWidget(self.w_spin)
        top.addWidget(QLabel("×"))
        top.addWidget(self.h_spin)
        top.addStretch(1)
        self.b_done = QPushButton("Done building")
        self.b_done.setToolTip("Back to the unit tools (the blocks stay; Save keeps them with the map)")
        top.addWidget(self.b_done)
        bl.addLayout(top)
        light = QHBoxLayout()
        light.addWidget(QLabel("Light"))
        self.light = QComboBox()
        for k, lab in mapbuild.LIGHTS.items():
            self.light.addItem(lab, k)
        self.light.setToolTip("How the game lights the blocks. The Item World's blocks carry the Item World's light, "
                              "which comes out dark on a stage; 'Like a story stage' gives them the light of the "
                              "story maps. (Pieces cut out of maps keep their own.)")
        self.light.currentIndexChanged.connect(self._light_changed)
        light.addWidget(self.light, 1)
        bl.addLayout(light)
        self.terrain_note = QWidget()
        tn = QHBoxLayout(self.terrain_note)
        tn.setContentsMargins(0, 0, 0, 0)
        lab = QLabel("<span style='color:#ffb86b'>This build started from the map itself, and an older kit didn't "
                     "keep that terrain: blocks placed before may show twice once it is rebuilt.</span>")
        lab.setWordWrap(True)
        tn.addWidget(lab, 1)
        self.b_terrain = QPushButton("Original terrain…")
        self.b_terrain.setToolTip("Pick the map this stage was made from (New stage › its map): the build is redone "
                                  "on that terrain")
        self.b_terrain.clicked.connect(lambda: self.page.pick_terrain())
        tn.addWidget(self.b_terrain)
        self.terrain_note.setVisible(False)
        bl.addWidget(self.terrain_note)
        self.theme = QComboBox()
        self.theme.currentIndexChanged.connect(self._fill)
        bl.addWidget(self.theme)
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(*ICON))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(190)
        self.list.setToolTip("Pick a block, then click a panel of the map with 🧱 Place to put it there")
        self.list.currentItemChanged.connect(lambda *_: self._tool(TOOL_PLACE))
        bl.addWidget(self.list, 1)
        self.b_cut = QPushButton("✂ A piece of a map…")
        self.b_cut.setToolTip("Cut a rectangle out of any map (its rocks and walls come along) and use it as a block")
        self.b_cut.clicked.connect(self._cutout)
        bl.addWidget(self.b_cut)
        tools = QHBoxLayout()
        self.b_place = QToolButton()
        self.b_place.setText("🧱 Place")
        self.b_place.setCheckable(True)
        self.b_place.setToolTip("Click a panel: the chosen block's top-left corner goes there")
        self.b_move = QToolButton()
        self.b_move.setText("✥ Move")
        self.b_move.setCheckable(True)
        self.b_move.setToolTip("Click a block of the map to choose it, drag to move it")
        for b, t in ((self.b_place, TOOL_PLACE), (self.b_move, TOOL_MOVE)):
            b.clicked.connect(lambda _, t=t: self._tool(t))
            tools.addWidget(b)
        tools.addStretch(1)
        bl.addLayout(tools)
        row = QHBoxLayout()
        self.b_turn = QToolButton()
        self.b_turn.setText("↻ Turn")
        self.b_turn.setToolTip("A quarter turn (R)")
        self.b_turn.clicked.connect(self.turn)
        self.b_up = QToolButton()
        self.b_up.setText("▲ Lift")
        self.b_up.setToolTip("One height step up (+ / Page Up); the block's walls grow down to the ground")
        self.b_up.clicked.connect(lambda: self.raise_(1))
        self.b_down = QToolButton()
        self.b_down.setText("▼ Lower")
        self.b_down.setToolTip("One height step down (- / Page Down)")
        self.b_down.clicked.connect(lambda: self.raise_(-1))
        self.b_dup = QToolButton()
        self.b_dup.setText("⧉ Copy")
        self.b_dup.setToolTip("A copy of the chosen block, one panel over")
        self.b_dup.clicked.connect(self.duplicate)
        self.b_look = QToolButton()
        self.b_look.setText("🎨 Look…")
        self.b_look.setToolTip("Tint the chosen block, or put your own pictures on its textures (the stone blocks: "
                               "a 160×128 top picture and a 128×32 wall strip)")
        self.b_look.clicked.connect(self.look)
        row.addWidget(self.b_look)
        self.b_del = QToolButton()
        self.b_del.setText("🗑 Delete")
        self.b_del.setToolTip("Delete the chosen block (Delete)")
        self.b_del.clicked.connect(self.delete)
        for b in (self.b_turn, self.b_up, self.b_down, self.b_dup, self.b_del):
            row.addWidget(b)
        row.addStretch(1)
        bl.addLayout(row)
        urow = QHBoxLayout()
        urow.addWidget(QLabel("Under a lifted block"))
        self.under = QComboBox()
        for k, lab in mapbuild.UNDER.items():
            self.under.addItem(lab, k)
        self.under.setToolTip("Solid: the block's walls go on down to the ground, like a stack of blocks. Platform: "
                              "it floats, nothing under it. For the chosen block, or (🧱 Place) the next ones.")
        self.under.currentIndexChanged.connect(self._under_changed)
        urow.addWidget(self.under, 1)
        bl.addLayout(urow)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        bl.addWidget(self.status)
        lay.addWidget(box)
        self._set_status()

    # ---------------------------------------------------------------- the library
    def set_build(self, build, lib, data_dir):
        self.build, self.lib = build, lib
        self.sel = None
        self.data_dir = data_dir
        self.w_spin.blockSignals(True)
        self.h_spin.blockSignals(True)
        self.w_spin.setValue(int(build["size"][0]))
        self.h_spin.setValue(int(build["size"][1]))
        self.w_spin.blockSignals(False)
        self.h_spin.blockSignals(False)
        self.light.blockSignals(True)
        self.light.setCurrentIndex(max(0, self.light.findData(mapbuild.light_of(build))))
        self.light.blockSignals(False)
        if self.theme.count() == 0:
            self._fill_themes()
        self._set_status()

    def set_terrain_missing(self, on):
        self.terrain_note.setVisible(bool(on))

    def _light_changed(self, *_):
        if self.build is None:
            return
        v = self.light.currentData()
        if mapbuild.light_of(self.build) == v:
            return
        if v == "stage":
            self.build.pop("light", None)
        else:
            self.build["light"] = v
        self.changed.emit()

    def _sync_under(self):
        """the Under choice shows the chosen block's (Move) or the one new blocks get (Place)"""
        p = self._selected() if self.tool() == TOOL_MOVE else None
        v = mapbuild.under_of(p) if p is not None else getattr(self, "under_new", "solid")
        self.under.blockSignals(True)
        self.under.setCurrentIndex(max(0, self.under.findData(v)))
        self.under.blockSignals(False)

    def _under_changed(self, *_):
        v = self.under.currentData()
        p = self._selected() if self.tool() == TOOL_MOVE else None
        if p is None:
            self.under_new = v
            self._set_status()
            return
        if mapbuild.under_of(p) == v:
            return
        if v == "solid":
            p.pop("under", None)
        else:
            p["under"] = v
        self.changed.emit()

    def _fill_themes(self):
        try:
            names = self.page.ws.fs.list_members("Map/Map_JP.dat")
        except Exception:
            names = []
        self.ids = mapbuild.piece_ids(names)
        themes = sorted({mapbuild.theme_of(i) for i in self.ids})
        self.theme.blockSignals(True)
        for t in themes:
            n = sum(1 for i in self.ids if mapbuild.theme_of(i) == t)
            self.theme.addItem(f"{mapbuild.THEMES.get(t, f'Theme {t}')}  ({n})", t)
        self.theme.addItem("Pieces of maps (cut-outs)", "cut")
        self.theme.blockSignals(False)
        self._fill()

    def _fill(self, *_):
        self.list.clear()
        t = self.theme.currentData()
        blank = QPixmap(*ICON)
        blank.fill(Qt.GlobalColor.transparent)
        if t == "cut":
            keys = [mapbuild.key_of(p["piece"]) for p in (self.build or {}).get("pieces", [])
                    if isinstance(p["piece"], list)]
            seen = []
            for k in keys:
                if k not in seen:
                    seen.append(k)
            for k in seen:
                it = QListWidgetItem(QIcon(self._thumb(k) or blank), f"map{k[0]:05d}\n{k[1]},{k[2]} {k[3]-k[1]}×{k[4]-k[2]}")
                it.setData(ROLE, k)
                self.list.addItem(it)
            return
        ids = [i for i in self.ids if mapbuild.theme_of(i) == t]
        for mid in ids:
            size = ""
            try:
                pc = self.lib.get(mid)
                size = f"{pc.w}×{pc.h}"
            except Exception:
                pass
            it = QListWidgetItem(QIcon(self._thumb(mid) or blank), f"{mid}  {size}")
            it.setData(ROLE, mid)
            it.setToolTip(f"map{mid:05d}: {size} panels")
            self.list.addItem(it)
        missing = [i for i in ids if i not in self._thumbs]
        if missing:
            if self._painter is not None:
                self._painter.stop = True
            self._painter = _Painter(missing, self.data_dir)
            self._painter.ready.connect(self._ready)
            self._painter.start()

    def _thumb(self, key):
        img = self._thumbs.get(key)
        if img is None and isinstance(key, tuple):
            try:
                pc = self.lib.get(key)
                b = mapbuild.empty_build(pc.w, pc.h)
                mapbuild.place(b, key, 0, 0)
                pkg = mapbuild.compose(b, {key: pc}, self.lib.skeleton(), name="map00000")
                from d5lib import battlemap
                img = mapthumbs.render(battlemap.from_package(pkg), ICON)
                self._thumbs[key] = img
            except Exception:
                return None
        if img is None and isinstance(key, int) and os.path.exists(mapthumbs.thumb_path(key)):
            img = QImage(mapthumbs.thumb_path(key))
            self._thumbs[key] = img
        return QPixmap.fromImage(img.scaled(*ICON, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)) if img is not None else None

    def _ready(self, mid, img):
        self._thumbs[mid] = img
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE) == mid:
                it.setIcon(QIcon(self._thumb(mid)))

    def current_key(self):
        it = self.list.currentItem()
        return it.data(ROLE) if it else None

    def _cutout(self):
        stages = self.page._stage_choices()
        dlg = CutoutDialog(self, stages, self.page.mid)
        dlg.sizes = {mid: self.page._map_size(mid) for _, mid, _ in stages}
        if not dlg.exec():
            return
        key = dlg.key()
        try:
            self.lib.get(key)
        except Exception as e:
            QMessageBox.warning(self, "A piece of a map", f"That piece can't be cut: {e}")
            return
        self.theme.setCurrentIndex(self.theme.findData("cut"))
        self._pending_cut = key
        self._fill()
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE) == key:
                self.list.setCurrentRow(i)
                return
        it = QListWidgetItem(QIcon(self._thumb(key) or QPixmap()), f"map{key[0]:05d}\n{key[1]},{key[2]} "
                                                                    f"{key[3]-key[1]}×{key[4]-key[2]}")
        it.setData(ROLE, key)
        self.list.addItem(it)
        self.list.setCurrentItem(it)

    # ---------------------------------------------------------------- tools
    def _tool(self, t):
        self.page.tool.button(t).setChecked(True)
        self.b_place.setChecked(t == TOOL_PLACE)
        self.b_move.setChecked(t == TOOL_MOVE)
        self._set_status()
        self.marks_changed.emit()

    def tool(self):
        return self.page.tool.checkedId()

    def _set_status(self):
        if self.build is None:
            self.status.setText("")
            return
        self._sync_under()
        n = len(self.build["pieces"])
        if self.tool() == TOOL_PLACE:
            k = self.current_key()
            what = ("the chosen block" if k is None else f"block {k}" if isinstance(k, int) else "the cut-out")
            self.status.setText(f"{n} block(s). Click a panel to put {what} there (turned {self.rot * 90}°, "
                                f"{self.lift:+d} steps"
                                f"{', a platform' if getattr(self, 'under_new', 'solid') == 'platform' else ''}). "
                                "R turns, + / - lift, Delete removes the chosen block.")
        elif self.sel is not None and self.sel < n:
            p = self.build["pieces"][self.sel]
            self.status.setText(f"Block {self.sel + 1} of {n}: {p['piece']} at {p['x']}, {p['y']}, turned "
                                f"{p.get('rot', 0) * 90}°, {p.get('lift', 0):+d} steps"
                                f"{', a platform' if mapbuild.under_of(p) == 'platform' else ''}. Drag to move it.")
        else:
            self.status.setText(f"{n} block(s). Click a block of the map to choose it, drag to move it.")

    def at(self, x, y):
        """index of the topmost placement covering panel (x, y)"""
        return mapbuild.covered(self.build, self.lib.for_build(self.build)).get((x, y))

    def cells_of(self, idx):
        p = self.build["pieces"][idx]
        pc = self.lib.get(p["piece"])
        cells, _ = pc.footprint(p.get("rot", 0))
        return [(p["x"] + i, p["y"] + j) for i, j in cells]

    def ghost_cells(self, x, y):
        k = self.current_key()
        if k is None:
            return []
        try:
            cells, _ = self.lib.get(k).footprint(self.rot)
        except Exception:
            return []
        return [(x + i, y + j) for i, j in cells]

    def marks(self):
        """highlights for the 3D view: the block being placed (at the hovered panel) and the chosen block"""
        out = {}
        if self.build is None:
            return out
        t = self.tool()
        if t == TOOL_PLACE and self.hover is not None:
            out["ghost"] = self.ghost_cells(*self.hover)
        if self.sel is not None and self.sel < len(self.build["pieces"]):
            try:
                out["sel"] = self.cells_of(self.sel)
            except Exception:
                pass
        return out

    def set_hover(self, cell):
        if cell != self.hover:
            self.hover = cell
            if self.tool() == TOOL_PLACE:
                self.marks_changed.emit()

    def click(self, x, y, button):
        if self.build is None:
            return
        t = self.tool()
        if button == Qt.MouseButton.RightButton:
            idx = self.at(x, y)
            if idx is not None:
                self.sel = idx
                self._menu(idx)
            return
        if t == TOOL_PLACE:
            k = self.current_key()
            if k is None:
                self.status.setText("Pick a block in the list first.")
                return
            mapbuild.place(self.build, k, x, y, self.rot, self.lift, getattr(self, "under_new", "solid"))
            self.sel = len(self.build["pieces"]) - 1
            self._drag0 = None
            self.changed.emit()
        elif t == TOOL_MOVE:
            self.sel = self.at(x, y)
            self._drag0 = (x, y) if self.sel is not None else None
            self._set_status()
            self.marks_changed.emit()

    def drag(self, x, y):
        if self.build is None or self.tool() != TOOL_MOVE or self.sel is None or not getattr(self, "_drag0", None):
            return
        dx, dy = x - self._drag0[0], y - self._drag0[1]
        if not dx and not dy:
            return
        p = self.build["pieces"][self.sel]
        p["x"], p["y"] = p["x"] + dx, p["y"] + dy
        self._drag0 = (x, y)
        self.changed.emit()

    def _menu(self, idx):
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("↻ Turn", self.turn)
        m.addAction("▲ Lift one step", lambda: self.raise_(1))
        m.addAction("▼ Lower one step", lambda: self.raise_(-1))
        m.addAction("⧉ Copy", self.duplicate)
        m.addAction("⬆ Bring to the top", self.to_top)
        pl = self.build["pieces"][idx]
        other = "solid" if mapbuild.under_of(pl) == "platform" else "platform"
        m.addAction("▣ Solid: walls down to the ground" if other == "solid" else "▭ Platform: nothing under it",
                    lambda: self._set_under(idx, other))
        m.addSeparator()
        m.addAction("🗑 Delete", self.delete)
        m.exec(QCursor.pos())

    def _set_under(self, idx, v):
        p = self.build["pieces"][idx]
        if v == "solid":
            p.pop("under", None)
        else:
            p["under"] = v
        self.changed.emit()

    def _selected(self):
        if self.build is None or self.sel is None or self.sel >= len(self.build["pieces"]):
            return None
        return self.build["pieces"][self.sel]

    def turn(self):
        p = self._selected()
        if self.tool() == TOOL_PLACE or p is None:
            self.rot = (self.rot + 1) % 4
            self._set_status()
            self.marks_changed.emit()
            return
        p["rot"] = (int(p.get("rot", 0)) + 1) % 4
        self.changed.emit()

    def raise_(self, d):
        p = self._selected()
        if self.tool() == TOOL_PLACE or p is None:
            self.lift = max(-30, min(60, self.lift + d))
            self._set_status()
            return
        p["lift"] = max(-30, min(60, int(p.get("lift", 0)) + d))
        self.changed.emit()

    def duplicate(self):
        p = self._selected()
        if p is None:
            return
        q = dict(p)
        q["x"] += 1
        q["y"] += 1
        self.build["pieces"].append(q)
        self.sel = len(self.build["pieces"]) - 1
        self.changed.emit()

    def to_top(self):
        p = self._selected()
        if p is None:
            return
        self.build["pieces"].remove(p)
        self.build["pieces"].append(p)
        self.sel = len(self.build["pieces"]) - 1
        self.changed.emit()

    def delete(self):
        p = self._selected()
        if p is None:
            return
        self.build["pieces"].remove(p)
        self.sel = None
        self.changed.emit()

    def pictures_dir(self):
        mod = self.page._map_owner() if self.page.pkg else None
        if mod is None:
            return None
        return os.path.join(mod.patches_dir, "stages", mapbuild.PICTURES)

    def look(self):
        """tint and pictures of the chosen block"""
        p = self._selected()
        if p is None:
            QMessageBox.information(self, "Look", "Choose a block of the map first (✥ Move, then click it).")
            return
        try:
            pc = self.lib.get(p["piece"])
        except Exception as e:
            QMessageBox.warning(self, "Look", str(e))
            return
        dlg = LookDialog(self, p, pc, self.pictures_dir())
        if dlg.exec():
            dlg.apply(p)
            self.changed.emit()

    def key(self, e):
        """a key in the map view: True when it was one of the builder's"""
        k = e.key()
        if self.build is None or self.tool() not in (TOOL_PLACE, TOOL_MOVE):
            return False
        if k == Qt.Key.Key_R:
            self.turn()
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_PageUp):
            self.raise_(1)
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_PageDown):
            self.raise_(-1)
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete()
        elif k == Qt.Key.Key_D and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.duplicate()
        else:
            return False
        return True

    def _size_changed(self, *_):
        if self.build is None:
            return
        self.build["size"] = [self.w_spin.value(), self.h_spin.value()]
        self.changed.emit()
