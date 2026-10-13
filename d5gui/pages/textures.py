import os

from PIL import Image
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QSplitter,
                             QPushButton, QLabel, QFileDialog, QComboBox, QMessageBox, QProgressDialog)

from d5lib import txf
from ..common import PageHeader, ImageView, SearchBox, pil_to_pixmap, error_box

ROLE = Qt.ItemDataRole.UserRole


def square_thumb(img, size=96):
    img = img.copy()
    img.thumbnail((size, size))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return canvas


class TexturesPage(QWidget):
    """Gallery of UI / system / effect textures with PNG export & import."""

    SOURCES = [
        ("UI & system textures", "Start/Start_{L}.dat/Texture_opt.dat", "Start/Start_JP.dat/Texture.dat"),
        ("World / board textures", "Start/Start_{L}.dat/charworld_opt.dat", "Start/Start_JP.dat/charworld.dat"),
    ]

    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Textures & UI",
                                 "Menus, windows, icons, fonts, logos and more. Export to PNG, edit in any paint "
                                 "program, and import it back. Localized versions (for your text language) are used "
                                 "automatically."))
        top = QHBoxLayout()
        self.source = QComboBox()
        for s in self.SOURCES:
            self.source.addItem(s[0])
        self.source.currentIndexChanged.connect(self.load)
        self.source.setItemData(0, "Menus, windows, buttons, icons, fonts and logos of the game's interface.",
                                Qt.ItemDataRole.ToolTipRole)
        self.source.setItemData(1, "Textures of the world map / board screens.", Qt.ItemDataRole.ToolTipRole)
        self.source.setToolTip("Which group of textures to show")
        top.addWidget(self.source)
        self.search = SearchBox("Filter textures…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        b = QPushButton("Export ALL to folder…")
        b.setToolTip("Save every texture of this group as PNG files into a folder (to browse or edit them "
                     "in bulk).")
        b.clicked.connect(self.export_all)
        top.addWidget(b)
        lay.addLayout(top)

        split = QSplitter()
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(96, 96))
        self.list.setGridSize(QSize(128, 128))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(self._select)
        split.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.info = QLabel("Select a texture")
        self.info.setObjectName("cardTitle")
        rl.addWidget(self.info)
        row = QHBoxLayout()
        tips = {"Export PNG…": "Save the selected texture as a PNG to edit it in any paint program.",
                "Import PNG…": "Replace the selected texture with your edited PNG (keep the same size). "
                               "Saved into the active mod.",
                "Revert": "Undo your replacement: the game's original texture is used again.",
                "Fit": "Zoom the view to fit the window.",
                "1:1": "Show the texture at its real size (one image pixel = one screen pixel)."}
        for text, fn in [("Export PNG…", self.export_png), ("Import PNG…", self.import_png),
                         ("Revert", self.revert), ("Fit", lambda: self.view.fit()), ("1:1", lambda: self.view.set_zoom(1))]:
            b = QPushButton(text)
            b.setToolTip(tips[text])
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        rl.addLayout(row)
        self.view = ImageView()
        rl.addWidget(self.view, 1)
        split.addWidget(right)
        split.setSizes([620, 700])
        lay.addWidget(split, 1)
        self._loaded = False
        self._thumb_queue = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._thumb_step)
        ws.file_changed.connect(self._file_changed)

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.load()

    def load(self):
        self.list.clear()
        _, loc_t, base = self.SOURCES[self.source.currentIndex()]
        lang = self.ws.language
        loc = loc_t.replace("{L}", lang) if lang != "JP" else None
        loc_names = set()
        items = []
        if loc:
            try:
                loc_names = {n.lower() for n in self.ws.fs.children(loc)}
                items += [(n, f"{loc}/{n}", True) for n in self.ws.fs.children(loc)]
            except Exception:
                pass
        items += [(n, f"{base}/{n}", False) for n in self.ws.fs.children(base) if n.lower() not in loc_names]
        items = [x for x in items if not x[0].endswith(".txt")]
        items.sort(key=lambda x: x[0].lower())
        for name, vpath, localized in items:
            it = QListWidgetItem(name + (" 🌐" if localized else ""))
            it.setData(ROLE, vpath)
            it.setToolTip(self._tip(name, vpath, localized))
            self.list.addItem(it)
        self._thumb_queue = list(range(self.list.count()))
        self._timer.start(0)

    def _thumb_step(self):
        for _ in range(3):
            if not self._thumb_queue:
                self._timer.stop()
                return
            i = self._thumb_queue.pop(0)
            it = self.list.item(i)
            if it is None:
                continue
            try:
                data = self.ws.read(it.data(ROLE))
                img = txf.to_image(data)
                it.setIcon(QIcon(pil_to_pixmap(square_thumb(img))))
                vpath = it.data(ROLE)
                it.setToolTip(self._tip(vpath.split("/")[-1], vpath, "_opt" in vpath or "/Start_EN" in vpath,
                                        f"{img.width}×{img.height} · {txf.info(data)['kind']}"))
            except Exception:
                pass

    def _tip(self, name, vpath, localized, size=None):
        lines = [f"<b>{name}</b>"]
        if size:
            lines.append(size)
        if localized:
            lines.append("🌐 version for your text language (the game uses this one)")
        if self.ws.is_modified(vpath):
            lines.append("✏ replaced by your mod")
        lines.append(f"<span style='color:#9aa4b8'>{vpath}</span>")
        return "<qt>" + "<br>".join(lines) + "</qt>"

    def _filter(self, t):
        t = t.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _cur(self):
        it = self.list.currentItem()
        return it.data(ROLE) if it else None

    def _select(self, it, _=None):
        if not it:
            return
        vpath = it.data(ROLE)
        try:
            data = self.ws.read(vpath)
            img = txf.to_image(data)
            i = txf.info(data)
            mod = "   ✏ modified" if self.ws.is_modified(vpath) else ""
            self.info.setText(f"{vpath.split('/')[-1]} — {img.width}×{img.height} ({i['kind']}){mod}")
            self.view.set_image(img, fit=True)
        except Exception as e:
            self.info.setText(f"{vpath}: {e}")
            self.view.set_image(None)

    def _file_changed(self, vpath):
        if self._cur() == vpath:
            self._select(self.list.currentItem())
            it = self.list.currentItem()
            try:
                it.setIcon(QIcon(pil_to_pixmap(square_thumb(txf.to_image(self.ws.read(vpath))))))
            except Exception:
                pass

    def export_png(self):
        v = self._cur()
        if not v:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", v.split("/")[-1].rsplit(".", 1)[0] + ".png",
                                              "PNG (*.png)")
        if path:
            txf.to_image(self.ws.read(v)).save(path)
            self.ws.log(f"Exported {v} → {path}")

    def import_png(self):
        v = self._cur()
        if not v:
            return
        orig = self.ws.read(v)
        if txf.is_dds(orig):
            QMessageBox.information(self, "Import", "Font textures (DDS) can't be imported yet.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import PNG", "", "Images (*.png *.jpg *.bmp *.tga)")
        if not path:
            return
        img = Image.open(path)
        w, h = txf.info(orig)["width"], txf.info(orig)["height"]
        if img.size != (w, h):
            r = QMessageBox.question(self, "Different size",
                                     f"The original is {w}×{h} but your image is {img.width}×{img.height}.\n"
                                     "UI elements use fixed coordinates, so a different size may look wrong.\n\n"
                                     "Yes = resize your image to fit, No = keep your size.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                     QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Yes:
                img = img.convert("RGBA").resize((w, h), Image.LANCZOS)
        self.ws.write(v, txf.from_image(img, orig), self)

    def revert(self):
        v = self._cur()
        if v:
            self.ws.revert(v)

    def export_all(self):
        d = QFileDialog.getExistingDirectory(self, "Export all textures to")
        if not d:
            return
        n = self.list.count()
        prog = QProgressDialog("Exporting…", "Cancel", 0, n, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        for i in range(n):
            if prog.wasCanceled():
                break
            v = self.list.item(i).data(ROLE)
            try:
                txf.to_image(self.ws.read(v)).save(os.path.join(d, v.split("/")[-1].rsplit(".", 1)[0] + ".png"))
            except Exception:
                pass
            prog.setValue(i + 1)
        self.ws.log(f"Exported {n} textures to {d}")
