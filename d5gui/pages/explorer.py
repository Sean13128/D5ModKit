import io
import os

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QSplitter,
                             QPushButton, QPlainTextEdit, QLabel, QFileDialog, QStackedWidget, QMessageBox)
from PyQt6.QtGui import QFont

from d5lib import txf
from d5lib.util import hexdump
from ..common import PageHeader, ImageView, SearchBox, error_box, human_size

ROLE = Qt.ItemDataRole.UserRole


class ExplorerPage(QWidget):
    """Browse every file in every archive; export/replace anything."""

    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Archive Explorer",
                                 "Every file in the game, unpacked on the fly. Export anything, or replace it with your "
                                 "own file (saved into the active mod). Files shown decompressed."))
        top = QHBoxLayout()
        self.search = SearchBox("Filter loaded names…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        lay.addLayout(top)

        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", ""])
        self.tree.setColumnWidth(0, 320)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.currentItemChanged.connect(self._select)
        split.addWidget(self.tree)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.title = QLabel("Select a file")
        self.title.setObjectName("cardTitle")
        rl.addWidget(self.title)
        row = QHBoxLayout()
        self.b_export = QPushButton("Export file…")
        self.b_export.clicked.connect(self.export)
        self.b_png = QPushButton("Export as PNG…")
        self.b_png.clicked.connect(self.export_png)
        self.b_replace = QPushButton("Replace with file…")
        self.b_replace.clicked.connect(self.replace)
        self.b_import_png = QPushButton("Import PNG…")
        self.b_import_png.clicked.connect(self.import_png)
        self.b_revert = QPushButton("Revert to original")
        self.b_revert.clicked.connect(self.revert)
        for b in (self.b_export, self.b_png, self.b_replace, self.b_import_png, self.b_revert):
            row.addWidget(b)
        row.addStretch(1)
        rl.addLayout(row)
        self.preview = QStackedWidget()
        self.hex = QPlainTextEdit()
        self.hex.setReadOnly(True)
        self.hex.setFont(QFont("Consolas", 9))
        self.hex.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.img = ImageView()
        self.preview.addWidget(self.hex)
        self.preview.addWidget(self.img)
        rl.addWidget(self.preview, 1)
        split.addWidget(right)
        split.setSizes([460, 900])
        lay.addWidget(split, 1)
        self.current = None
        self._populated = False

    def on_show(self):
        if not self._populated:
            self._populated = True
            for a in self.ws.fs.archives():
                kind = self.ws.fs.archive_kind(a)
                it = QTreeWidgetItem([a, human_size(os.path.getsize(self.ws.fs.archive_path(a))), kind])
                it.setData(0, ROLE, (a, kind, True))
                if kind in ("nispack", "psfs"):
                    it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
                self.tree.addTopLevelItem(it)

    def _expand(self, item):
        vpath, kind, is_archive = item.data(0, ROLE)
        if item.childCount():
            return
        try:
            if is_archive and kind in ("nispack", "psfs"):
                pack = self.ws.fs.pack(vpath)
                for e in pack.entries:
                    ch = QTreeWidgetItem([e.name, human_size(e.size), ""])
                    ch.setData(0, ROLE, (f"{vpath}/{e.name}", "member", False))
                    if e.name.lower().endswith((".lzs",)) and e.name.lower().startswith("map") or \
                            e.name.lower() in ("texture.dat", "texture_opt.dat", "charworld.dat",
                                               "charworld_opt.dat", "effect.dat"):
                        ch.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
                    item.addChild(ch)
            elif not is_archive:
                for n in self.ws.fs.children(vpath):
                    ch = QTreeWidgetItem([n, "", ""])
                    ch.setData(0, ROLE, (f"{vpath}/{n}", "child", False))
                    item.addChild(ch)
        except Exception as e:
            error_box(self, "Could not open", e)

    def _filter(self, text):
        text = text.lower()

        def walk(it):
            vis = not text or text in it.text(0).lower()
            for i in range(it.childCount()):
                vis = walk(it.child(i)) or vis
            it.setHidden(not vis)
            return vis

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _select(self, item, _=None):
        if not item:
            return
        vpath, kind, is_archive = item.data(0, ROLE)
        self.current = None if is_archive else vpath
        self.title.setText(vpath + ("   ✏ (modified in active mod)" if self.ws.is_modified(vpath) else ""))
        if is_archive:
            self.hex.setPlainText("Archive. Expand it to see its files.")
            self.preview.setCurrentWidget(self.hex)
            return
        try:
            data = self.ws.read(vpath)
        except Exception as e:
            self.hex.setPlainText(f"Error: {e}")
            self.preview.setCurrentWidget(self.hex)
            return
        low = vpath.lower()
        if low.endswith((".txf", ".dds", ".ks4")) and not data[:8] == b"NISPACK\0":
            try:
                self.img.set_image(txf.to_image(data), fit=True)
                self.preview.setCurrentWidget(self.img)
                return
            except Exception:
                pass
        self.hex.setPlainText(f"{human_size(len(data))} ({len(data)} bytes)\n\n" + hexdump(data[:65536]) +
                              ("\n…" if len(data) > 65536 else ""))
        self.preview.setCurrentWidget(self.hex)

    # ------------------------------------------------------------------ actions
    def export(self):
        if not self.current:
            return
        name = self.current.split("/")[-1]
        if name.lower().endswith(".lzs"):
            name = name[:-4] + ".bin"
        path, _ = QFileDialog.getSaveFileName(self, "Export", name)
        if path:
            with open(path, "wb") as f:
                f.write(self.ws.read(self.current))
            self.ws.log(f"Exported {self.current} → {path}")

    def export_png(self):
        if not self.current:
            return
        try:
            img = txf.to_image(self.ws.read(self.current))
        except Exception as e:
            QMessageBox.information(self, "Not an image", f"This file is not a supported texture.\n{e}")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", self.current.split("/")[-1] + ".png", "PNG (*.png)")
        if path:
            img.save(path)

    def replace(self):
        if not self.current:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Replace with file")
        if path:
            with open(path, "rb") as f:
                if self.ws.write(self.current, f.read(), self):
                    self._select(self.tree.currentItem())

    def import_png(self):
        if not self.current:
            return
        orig = self.ws.read(self.current)
        if txf.is_dds(orig) or orig[:1] != b"\0":
            QMessageBox.information(self, "Import PNG", "PNG import is supported for 32-bit TXF textures.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import PNG", "", "Images (*.png *.jpg *.bmp *.tga)")
        if path:
            img = Image.open(path)
            if self.ws.write(self.current, txf.from_image(img, orig), self):
                self._select(self.tree.currentItem())

    def revert(self):
        if self.current:
            self.ws.revert(self.current)
            self._select(self.tree.currentItem())
