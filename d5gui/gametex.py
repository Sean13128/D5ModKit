"""Pictures from the game for blocks: the Netherworld ground tiles of the UI textures and the stages' own 3D
textures, fitted to a block texture (Stages & Maps › Blocks › Look… › From the game…)."""
import os

from PIL import Image
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListView, QListWidget,
                             QListWidgetItem, QVBoxLayout)

from d5lib import obf, txf
from .common import Worker, pil_to_pixmap

ROLE = Qt.ItemDataRole.UserRole
UI_TEX = "Start/Start_JP.dat/Texture.dat"


def ground_tiles(fs):
    """[(label, PIL image)]: the left 256 x 256 of every NNN_amap_01.txf (seamless Netherworld grounds)"""
    out = []
    for n in sorted(fs.children(UI_TEX)):
        if not n.endswith("_amap_01.txf"):
            continue
        try:
            img = txf.to_image(fs.read(f"{UI_TEX}/{n}")).convert("RGBA")
        except Exception:
            continue
        out.append((f"Ground {n[:3]}", img.crop((0, 0, min(256, img.width), min(256, img.height)))))
    return out


def stage_textures(fs, map_id):
    """[(label, PIL image)] of a stage's 3D model"""
    from d5lib import mapfile, pac
    name = f"map{int(map_id):05d}"
    pk = mapfile.MapPackage(pac.read_pac(fs.read(f"{fs.resolve('map', name + '.lzs', 'EN')}/{name}.lzs")), name)
    out = []
    for i, t in enumerate(pk.obf.textures):
        try:
            img = t.to_image().convert("RGBA")
        except Exception:
            continue
        if img.width >= 16 and img.height >= 16:
            out.append((f"{name} texture {i} ({img.width}×{img.height})", img))
    return out


def fit(img, target_entry):
    """the picture made for a block texture: a 160 x 128 stone top keeps its own right strip (the left 128 x 128 is
    the tiled top); a wide strip (walls, 128 x 32) is cropped from the picture, not squashed; others are scaled"""
    t = obf.Texture(target_entry)
    W, H = t.width, t.height
    if (W, H) == (160, 128):
        try:
            own = t.to_image().convert("RGBA")
        except Exception:
            own = Image.new("RGBA", (W, H), (128, 128, 128, 255))
        out = own.copy()
        out.paste(img.resize((128, 128), Image.Resampling.LANCZOS), (0, 0))
        return out
    if W >= 2 * H:
        s = img.resize((W, max(H, round(img.height * W / img.width))), Image.Resampling.LANCZOS)
        y = (s.height - H) // 2
        return s.crop((0, y, W, y + H))
    return img.resize((W, H), Image.Resampling.LANCZOS)


class GameTextureDialog(QDialog):
    """pick a picture from the game"""

    def __init__(self, parent, ws, stages):
        super().__init__(parent)
        self.ws = ws
        self.choice = None
        self.setWindowTitle("A picture from the game")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItem("Netherworld grounds (from Textures & UI)", None)
        for mid, label in stages:
            self.source.addItem(f"Stage: {label}", mid)
        self.source.currentIndexChanged.connect(self._load)
        row.addWidget(QLabel("From"))
        row.addWidget(self.source, 1)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(128, 128))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setSpacing(6)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        lay.addWidget(self.list, 1)
        self.note = QLabel("")
        self.note.setObjectName("muted")
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._load()

    def _load(self, *_):
        mid = self.source.currentData()
        self.list.clear()
        self.note.setText("Loading…")
        fs = self.ws.fs
        self._w = w = Worker(ground_tiles, fs) if mid is None else Worker(stage_textures, fs, mid)

        def done(items):
            if self.source.currentData() != mid:
                return
            for label, img in items:
                it = QListWidgetItem(QIcon(pil_to_pixmap(img.resize((128, 128)) if img.width != img.height
                                                         else img.resize((128, 128)))), label)
                it.setData(ROLE, img)
                it.setToolTip(label)
                self.list.addItem(it)
            self.note.setText(f"{len(items)} pictures. Double-click one, or pick it and press OK.")
        w.done.connect(done)
        w.failed.connect(lambda m: self.note.setText("Couldn't load them: " + m.splitlines()[0]))
        w.start()

    def accept(self):
        it = self.list.currentItem()
        if it is None:
            return
        self.choice = (it.text(), it.data(ROLE))
        super().accept()
