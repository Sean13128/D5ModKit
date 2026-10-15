"""Fix a portrait's background in the kit (Characters & Classes › 🧽 Fix portrait background…, Outfits › Edit).

The portrait is shown built from its original picture (d5lib.portraitfix): what is transparent shows the chosen
background (checkerboard, the Status screen's dark blue, magenta), or a red tint with "Show removed parts".  Left
click makes something transparent, right click keeps it: a whole white area at once, or with the brush.  Save builds
the portrait again from the original picture with these marks (and every copy of it in the mod)."""
import os

import numpy as np
from PIL import Image
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                             QMessageBox, QPushButton, QRadioButton, QScrollArea, QSlider, QVBoxLayout, QWidget)
from scipy import ndimage

from d5lib import imgtools
from d5lib import portraitfix as pf

from .workspace import KIT_DIR

BACKGROUNDS = [("Checkerboard", None), ("Status screen blue", (20, 30, 70)), ("Magenta", (255, 0, 255)),
               ("White", (255, 255, 255))]


class _Canvas(QWidget):
    """the picture with its marks, zoomable; mouse presses / drags in picture pixels"""
    painted = pyqtSignal(int, int, int, bool)          # x, y, button (1 left, 2 right), drag

    def __init__(self):
        super().__init__()
        self.img = None
        self.scale = 1.0
        self.brush = 0
        self.cursor_at = None
        self.setMouseTracking(True)

    def set_image(self, qimg):
        self.img = qimg
        self._resize()
        self.update()

    def set_scale(self, s):
        self.scale = max(0.25, min(8.0, s))
        self._resize()
        self.update()

    def _resize(self):
        if self.img is not None:
            self.setFixedSize(int(self.img.width() * self.scale), int(self.img.height() * self.scale))

    def paintEvent(self, e):
        if self.img is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.scale < 1)
        p.drawImage(QRect(0, 0, self.width(), self.height()), self.img)
        if self.brush and self.cursor_at is not None:
            r = self.brush * self.scale
            p.setPen(Qt.GlobalColor.yellow)
            p.drawEllipse(QPoint(*self.cursor_at), int(r), int(r))
        p.end()

    def _at(self, e):
        pos = e.position()
        return int(pos.x() / self.scale), int(pos.y() / self.scale)

    def mousePressEvent(self, e):
        b = 1 if e.button() == Qt.MouseButton.LeftButton else 2 if e.button() == Qt.MouseButton.RightButton else 0
        if b:
            self.painted.emit(*self._at(e), b, False)

    def mouseMoveEvent(self, e):
        self.cursor_at = (int(e.position().x()), int(e.position().y()))
        if self.brush:
            self.update()
        bt = e.buttons()
        b = 1 if bt & Qt.MouseButton.LeftButton else 2 if bt & Qt.MouseButton.RightButton else 0
        if b:
            self.painted.emit(*self._at(e), b, True)

    def leaveEvent(self, e):
        self.cursor_at = None
        self.update()


class PortraitFixDialog(QDialog):
    def __init__(self, parent, ws, mod, anm_id, title=""):
        super().__init__(parent)
        self.ws, self.mod, self.anm_id = ws, mod, int(anm_id)
        self.setWindowTitle(f"Fix portrait background{' - ' + title if title else ''} (anm{self.anm_id:05d})")
        self.resize(900, 820)
        self.ok = False
        self.a, self.cur = pf.load_portrait(mod, self.anm_id)
        if self.a.textures[0].indexed:
            raise ValueError("this portrait is a paletted picture; only full-colour portraits can be fixed")
        self.fit = pf.load_info(mod, self.anm_id).get("fit", "cover")
        self.src_path = pf.source_path(mod, self.anm_id) or pf.find_drpg_source(self.cur, os.path.join(KIT_DIR, "cache"))
        if not self.src_path:
            QMessageBox.information(parent, "Fix portrait background",
                                    "The kit doesn't know the original picture of this portrait. Choose it next: "
                                    "the picture the portrait was made from, with its white background.")
            self.src_path, _ = QFileDialog.getOpenFileName(parent, "Original picture of the portrait", "",
                                                           "Images (*.png *.jpg *.webp)")
            if not self.src_path:
                raise ValueError("no original picture chosen")
        self._load_source(self.src_path, from_portrait=True)
        self._build()
        self._refresh()

    # ------------------------------------------------------------------ data
    def _load_source(self, path, from_portrait=False):
        self.src = Image.open(path).convert("RGBA")
        self.drpg = pf.is_drpg_cutin(self.src)
        params = dict(threshold=imgtools.DRPG["threshold"], spread=imgtools.DRPG["spread"]) if self.drpg else {}
        self.areas, _ = imgtools.light_areas(self.src, **params)
        self.rgb = np.asarray(self.src.convert("RGB"))
        self.mask = pf.current_mask(self.mod, self.anm_id, self.src, self.cur, self.fit) if from_portrait \
            else pf.auto_mask(self.src)
        self.undo = []

    # ------------------------------------------------------------------ layout
    def _build(self):
        lay = QHBoxLayout(self)
        side = QVBoxLayout()
        help_ = QLabel("<b>Left click</b>: make transparent<br><b>Right click</b>: keep<br><br>"
                       "Click a white area to change all of it, or switch to the brush for the edges.")
        help_.setWordWrap(True)
        side.addWidget(help_)
        self.mode = QButtonGroup(self)
        self.m_area = QRadioButton("Whole white area")
        self.m_brush = QRadioButton("Brush")
        self.m_area.setChecked(True)
        for i, b in enumerate((self.m_area, self.m_brush)):
            self.mode.addButton(b, i)
            side.addWidget(b)
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(1, 40)
        self.size.setValue(6)
        self.size_lab = QLabel()
        side.addWidget(self.size_lab)
        side.addWidget(self.size)
        self.mode.idToggled.connect(lambda *_: self._brush_changed())
        self.size.valueChanged.connect(lambda *_: self._brush_changed())
        side.addSpacing(10)
        side.addWidget(QLabel("Background"))
        self.bg = QComboBox()
        for lab, _ in BACKGROUNDS:
            self.bg.addItem(lab)
        self.bg.setCurrentIndex(1)
        self.bg.currentIndexChanged.connect(lambda *_: self._refresh())
        side.addWidget(self.bg)
        self.tint = QCheckBox("Show removed parts (red)")
        self.tint.toggled.connect(lambda *_: self._refresh())
        side.addWidget(self.tint)
        side.addSpacing(10)
        for text, fn, tip in (("↶ Undo", self._undo, "Ctrl+Z"),
                              ("Automatic guess", self._auto, "Start again from the kit's guess"),
                              ("Keep everything", self._keep_all, "Nothing transparent"),
                              ("Original picture…", self._choose_source, "Use another original picture")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addSpacing(10)
        zl = QHBoxLayout()
        for text, f in (("−", 1 / 1.25), ("+", 1.25)):
            b = QPushButton(text)
            b.setFixedWidth(36)
            b.clicked.connect(lambda _, f=f: self.canvas.set_scale(self.canvas.scale * f))
            zl.addWidget(b)
        zl.addStretch(1)
        side.addLayout(zl)
        side.addStretch(1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        save = QPushButton("💾 Save portrait")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        side.addWidget(save)
        side.addWidget(cancel)
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(230)
        lay.addWidget(sw)
        self.canvas = _Canvas()
        self.canvas.painted.connect(self._paint)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(scroll, 1)
        self.canvas.set_scale(max(0.5, min(3.0, 760 / self.src.height)))
        self._brush_changed()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Z and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._undo()
            return
        super().keyPressEvent(e)

    def _brush_changed(self):
        self.size_lab.setText(f"Brush size: {self.size.value()} px")
        self.canvas.brush = self.size.value() if self.m_brush.isChecked() else 0
        self.canvas.update()

    # ------------------------------------------------------------------ editing
    def _push(self):
        self.undo.append(self.mask.copy())
        del self.undo[:-40]

    def _paint(self, x, y, button, drag):
        h, w = self.mask.shape
        if not (0 <= x < w and 0 <= y < h):
            return
        transparent = button == 1
        if self.m_brush.isChecked():
            if not drag:
                self._push()
            r = self.size.value()
            yy, xx = np.ogrid[max(0, y - r):min(h, y + r + 1), max(0, x - r):min(w, x + r + 1)]
            disk = (yy - y) ** 2 + (xx - x) ** 2 <= r * r
            self.mask[max(0, y - r):min(h, y + r + 1), max(0, x - r):min(w, x + r + 1)][disk] = transparent
        else:
            if drag:
                return
            lab = self.areas[y, x]
            if lab:
                region = self.areas == lab
            elif not transparent and self.mask[y, x]:
                lab2, _ = ndimage.label(self.mask)          # a removed part that isn't white: give it all back
                region = lab2 == lab2[y, x]
            else:
                self.status.setText("That isn't a white area: use the brush to paint it.")
                return
            self._push()
            self.mask[region] = transparent
        self.status.setText("")
        self._refresh()

    def _undo(self):
        if self.undo:
            self.mask = self.undo.pop()
            self._refresh()

    def _auto(self):
        self._push()
        self.mask = pf.auto_mask(self.src)
        self._refresh()

    def _keep_all(self):
        self._push()
        self.mask = np.zeros_like(self.mask)
        self._refresh()

    def _choose_source(self):
        p, _ = QFileDialog.getOpenFileName(self, "Original picture of the portrait", "", "Images (*.png *.jpg *.webp)")
        if p:
            self.src_path = p
            self._load_source(p)
            self.canvas.set_scale(max(0.5, min(3.0, 760 / self.src.height)))
            self._refresh()

    # ------------------------------------------------------------------ drawing
    def _refresh(self):
        img = imgtools.apply_background(self.src, self.mask)
        a = np.asarray(img).astype(np.float32)
        h, w = a.shape[:2]
        col = BACKGROUNDS[self.bg.currentIndex()][1]
        if col is None:
            yy, xx = np.indices((h, w))
            chk = (((yy // 8) + (xx // 8)) % 2).astype(np.float32)
            back = np.dstack([150 + chk * 60] * 3)
        else:
            back = np.ones((h, w, 3), np.float32) * np.array(col, np.float32)
        al = a[:, :, 3:4] / 255.0
        out = a[:, :, :3] * al + back * (1 - al)
        if self.tint.isChecked():
            out[self.mask] = out[self.mask] * 0.4 + np.array([255, 0, 0]) * 0.6
        out = np.ascontiguousarray(out.clip(0, 255).astype(np.uint8))
        self._qbuf = out
        q = QImage(out.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.canvas.set_image(q.copy())
        removed = self.mask.mean() * 100
        self.status.setText(self.status.text() or f"{removed:.0f}% of the picture is transparent")

    def _save(self):
        try:
            pf.save(self.mod, self.anm_id, self.src, self.mask, source=self.src_path, fit=self.fit)
        except Exception as e:
            QMessageBox.critical(self, "Fix portrait background", str(e))
            return
        self.ws.file_changed.emit("Anime/")
        self.ws.log(f"Portrait anm{self.anm_id:05d} saved in '{self.mod.name}' (and its copies). Install to see it in "
                    "game.")
        self.ok = True
        self.accept()


def fix_portrait(parent, ws, mod, anm_id, title=""):
    """open the fixer -> True when the portrait was saved"""
    try:
        dlg = PortraitFixDialog(parent, ws, mod, anm_id, title)
    except Exception as e:
        QMessageBox.warning(parent, "Fix portrait background", str(e))
        return False
    dlg.exec()
    return dlg.ok
