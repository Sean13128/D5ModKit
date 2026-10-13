"""Outfits: give unique characters a switchable second outfit (in-game 'Outfit' option in the unit menu)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (QMenu, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QComboBox, QDialog, QDialogButtonBox, QRadioButton,
                             QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QFormLayout,
                             QLineEdit, QApplication, QAbstractItemView, QCheckBox)

from d5lib import anm, framesheet, frameconvert, outfits, sprites
from ..common import PageHeader, ImageView, Worker, error_box, info_box, pil_to_pixmap
from ..dbservice import get_service, char_names
from .stages import SearchCombo, set_choice_tips


class SheetRowsDialog(QDialog):
    """Assign every row of a frame-dump sheet to an animation (pre-filled from recognised labels)."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sprite sheet rows")
        self.resize(900, 700)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.im, self.rows = framesheet.parse_sheet(path)
            guesses = framesheet.guess_rows(self.im, self.rows)
        finally:
            QApplication.restoreOverrideCursor()
        lay = QVBoxLayout(self)
        known = sum(1 for g in guesses if g[2])
        lay.addWidget(QLabel(f"{len(self.rows)} animation rows found, {known} labels recognised automatically. "
                             "Check each row's animation and view (front/back). Rows set to '(ignore)' are "
                             "not used (e.g. '_hand' overlay rows)."))
        self.table = QTableWidget(len(self.rows), 4)
        self.table.setHorizontalHeaderLabels(["Label", "First frame", "Animation", "View"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(90)
        self.combos = []
        for k, (r, (name, view, text)) in enumerate(zip(self.rows, guesses)):
            lab = QTableWidgetItem(text or "(unrecognised)")
            if r["label_box"]:
                lab.setIcon(QIcon(pil_to_pixmap(framesheet.frame_image(self.im, r["label_box"]))))
            self.table.setItem(k, 0, lab)
            first = framesheet.frame_image(self.im, r["cells"][0])
            first.thumbnail((80, 80))
            it = QTableWidgetItem(f"{len(r['cells'])} frame(s)")
            it.setIcon(QIcon(pil_to_pixmap(first)))
            self.table.setItem(k, 1, it)
            nc = QComboBox()
            nc.addItems(["(ignore)"] + frameconvert.ANIM_NAMES + frameconvert.HAND_NAMES)
            nc.setCurrentText(name or "(ignore)")
            vc = QComboBox()
            vc.addItems(["front", "back"])
            vc.setCurrentText(view)
            self.table.setCellWidget(k, 2, nc)
            self.table.setCellWidget(k, 3, vc)
            self.combos.append((nc, vc))
        from PyQt6.QtCore import QSize
        self.table.setIconSize(QSize(160, 80))
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 170)
        lay.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def sequences(self):
        seqs = {}
        for r, (nc, vc) in zip(self.rows, self.combos):
            name = nc.currentText()
            if name == "(ignore)":
                continue
            seqs.setdefault((name, vc.currentText()), [framesheet.frame_image(self.im, c) for c in r["cells"]])
        return seqs


class _FileRow(QWidget):
    def __init__(self, title, filt, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.path = QLineEdit()
        self.path.setPlaceholderText("(optional)")
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: self._browse(title, filt))
        h.addWidget(self.path, 1)
        h.addWidget(b)

    def _browse(self, title, filt):
        p, _ = QFileDialog.getOpenFileName(self, title, "", filt)
        if p:
            self.path.setText(p)

    def value(self):
        p = self.path.text().strip()
        return p if p and os.path.exists(p) else None


def _tip_label(text, tip):
    lab = QLabel(text)
    lab.setToolTip(tip)
    return lab


BUTTON_TIPS = {
    "paint_parts": "Decide which colour part every pixel belongs to: give each colour family its part, paint "
                   "the rest with a brush over the sprite, and watch a live recoloured animation to spot mixed-up "
                   "bits. Part N = Part N of the in-game precise colour editor.",
    "export_parts": "Write the outfit's sprite sheets and its current colour parts as PNGs (plus a legend and "
                    "instructions) so you can paint the parts yourself, e.g. in Paint.NET. Part N = Part N of the "
                    "in-game precise colour editor.",
    "import_parts": "Read the painted parts back: every part becomes its own row of the game's precise colour editor. "
                    "You only need to paint a few poses; the other frames follow by colour.",
    "show_parts": "Preview: several poses with every colour part in its legend colour.",
    "new": "Create an outfit: pick the character, a sprite sheet (or a copy of the normal sprite), and optionally "
           "a face picture and a cut-in portrait.",
    "replace": "Convert a new sprite sheet into the selected outfit's sprite (the old sprite is replaced; face and "
               "cut-in stay).",
    "rename": "Change the name shown in the in-game Outfit list.",
    "face": "Set the square face picture (status panel, Status screen, battle, character list).",
    "cutin": "Set the tall cut-in portrait (special attacks, Status screen). White backgrounds are removed.",
    "edit": "Open the outfit's sprite in Sprites & Colors to recolour parts. Afterwards press 'Re-derive color "
            "presets' so the other colour presets follow your new colours.",
    "presets": "Rebuild colour presets 1-4 from the character's own presets (the hoodie follows the scarf, the "
               "hair follows the hair …). Uses the outfit's current default colours.",
    "remove": "Delete the selected outfit from this mod (its sprite, face, cut-in and data).",
}


class NewOutfitDialog(QDialog):
    """Everything an outfit needs in one go: character, name, sprite (sheet or copy), face, cut-in."""

    def __init__(self, uniques, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New outfit")
        self.resize(640, 420)
        f = QFormLayout(self)
        intro = QLabel("The character gets an 'Outfit' entry in the unit menu (Characters → select → Outfit) "
                       "listing 'Default' and every outfit by name; the look changes at once. Level, stats and "
                       "equipment stay the same. A character can have several outfits.")
        intro.setWordWrap(True)
        f.addRow(intro)
        self.char = SearchCombo(uniques)
        self.char.setToolTip("The character or generic class that gets the outfit. Hover an entry to read who it "
                             "is.")
        f.addRow(_tip_label("Character", "The unique character, or the generic class (all its ranks: a unit of any "
                                         "rank can wear it), that gets the outfit."),
                 self.char)
        self.name = QLineEdit("Outfit")
        self.name.setToolTip("Shown in the in-game Outfit list next to 'Default'. Can be renamed later.")
        f.addRow(_tip_label("Outfit name (in game)", self.name.toolTip()), self.name)
        self.copy = QRadioButton("Start from a copy of the character's sprite (repaint it in Sprites && Colors)")
        self.sheet = QRadioButton("Convert a sprite sheet (frame dump: labelled rows of whole-pose frames)")
        self.sheet.setChecked(True)
        self.sheet.setToolTip("A sprite sheet PNG with one labelled row per animation (stand, walk, attack …), "
                              "front and back views. Every frame is matched to the game's own poses, so the "
                              "outfit animates exactly like the character. Colour presets are made automatically.")
        self.copy.setToolTip("The outfit starts as an exact copy of the character's sprite; recolour or repaint it "
                             "afterwards in Sprites & Colors.")
        f.addRow(self.sheet)
        f.addRow(self.copy)
        self.sheet_file = _FileRow("Sprite sheet", "Images (*.png)")
        self.sheet_file.path.setPlaceholderText("sprite sheet PNG")
        self.sheet_file.setToolTip(self.sheet.toolTip())
        f.addRow(_tip_label("Sprite sheet", self.sheet.toolTip()), self.sheet_file)
        self.face_file = _FileRow("Face picture", "Images (*.png *.jpg *.webp)")
        face_tip = ("Square picture (about 200×200) of the outfit's face: status panel, Status screen, battle "
                    "and character list. Optional — without it the character's normal face is used.")
        self.face_file.setToolTip(face_tip)
        f.addRow(_tip_label("Face picture", face_tip), self.face_file)
        self.mirror = QCheckBox("Mirror the face (the game's faces look to the left)")
        self.mirror.setToolTip("Tick when your picture looks to the right: the game's faces look to the left.")
        f.addRow("", self.mirror)
        self.cut_file = _FileRow("Cut-in portrait", "Images (*.png *.jpg *.webp)")
        cut_tip = ("Tall portrait shown during special attacks and on the Status screen. White backgrounds "
                   "are removed automatically. Optional — without it the character's portrait is used.")
        self.cut_file.setToolTip(cut_tip)
        f.addRow(_tip_label("Cut-in portrait", cut_tip), self.cut_file)
        hint = QLabel("Face: square picture for the status panel, Status screen, battle and character list. "
                      "Cut-in: tall picture of special attacks (white backgrounds are removed). Both can also "
                      "be set later.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        f.addRow(hint)
        self.seqs = None
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _ok(self):
        if not self.char.value():
            QMessageBox.warning(self, "New outfit", "Choose a character.")
            return
        if self.sheet.isChecked():
            path = self.sheet_file.value()
            if not path:
                QMessageBox.warning(self, "New outfit", "Choose the sprite sheet PNG (or start from a copy).")
                return
            dlg = SheetRowsDialog(path, self)
            if not dlg.exec():
                return
            self.seqs = dlg.sequences()
            if not self.seqs:
                QMessageBox.warning(self, "New outfit", "No rows were assigned to an animation.")
                return
        self.accept()


class OutfitsPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws, self.main = ws, main
        self.svc = get_service(ws)
        self.worker = None
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Outfits",
                                 "Extra outfits for unique characters, switched in game from the unit menu "
                                 "(Characters → select → Outfit → Default / outfit name). An outfit has its own "
                                 "sprite (converted from a sprite sheet), face picture and cut-in portrait."))
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        bar = QHBoxLayout()
        b = QPushButton("✨ New outfit…")
        b.setObjectName("primary")
        b.setToolTip(BUTTON_TIPS["new"])
        b.clicked.connect(self.new)
        bar.addWidget(b)
        for title, entries in [
                ("Edit ▾", [("✏ Rename outfit…", self.rename, "rename"), ("🙂 Set face picture…", self.face, "face"),
                            ("🖼 Set cut-in portrait…", self.cutin, "cutin"),
                            ("Replace outfit sprite from sheet…", self.replace, "replace")]),
                ("Colors ▾", [("🖌 Edit parts (part painter)…", self.paint_parts, "paint_parts"),
                              ("🎨 Edit outfit colors (Sprites & Colors)", self.edit, "edit"),
                              ("🔄 Re-derive color presets from the character", self.presets, "presets"), None,
                              ("👁 Show parts", self.show_parts, "show_parts"),
                              ("🧩 Export parts to paint…", self.export_parts, "export_parts"),
                              ("🧩 Import painted parts…", self.import_parts, "import_parts")])]:
            mb = QPushButton(title)
            menu = QMenu(mb)
            menu.setToolTipsVisible(True)
            for e in entries:
                if e is None:
                    menu.addSeparator()
                    continue
                a = menu.addAction(e[0], e[1])
                a.setToolTip(BUTTON_TIPS[e[2]])
            mb.setMenu(menu)
            bar.addWidget(mb)
        b = QPushButton("🖌 Parts")
        b.setToolTip(BUTTON_TIPS["paint_parts"])
        b.clicked.connect(self.paint_parts)
        bar.addWidget(b)
        b = QPushButton("🗑")
        b.setToolTip(BUTTON_TIPS["remove"])
        b.clicked.connect(self.remove)
        bar.addWidget(b)
        ll.addLayout(bar)
        note = QLabel("New outfit → check the preview → Install & Play (bottom left) → in game: Characters → "
                      "select → Outfit. The first 3 outfits (slots 470-490) also get their own small icon in the "
                      "character list.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        ll.addWidget(note)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        rl.addWidget(self.info)
        self.view = ImageView()
        self.view.setBackgroundBrush(QColor(40, 90, 60))
        self.view.setToolTip("Preview: standing front / back, walking frames, the 5 colour presets (0 = default, "
                             "chosen in the Strategy Assembly), the face picture and the cut-in portrait.")
        rl.addWidget(self.view, 1)
        split.addWidget(right)
        self.pworker = None
        self._alive = set()       # preview workers keep running until done (a destroyed running QThread aborts)
        split.setSizes([420, 900])
        lay.addWidget(split, 1)
        self._names = None
        ws.active_mod_changed.connect(lambda _: self.refresh())

    def on_show(self):
        self.refresh()

    def names(self):
        if self._names is None:
            self._names = char_names(self.svc)
        return self._names

    def _outfit_mods(self):
        mods = self.ws.mods.enabled_mods()
        if self.ws.active_mod and self.ws.active_mod.id not in {m.id for m in mods}:
            mods.append(self.ws.active_mod)
        return [m for m in mods if outfits.load(m)]

    def refresh(self):
        cur = self._cur()
        self.list.clear()
        mods = self._outfit_mods()
        if not mods:
            self.list.addItem("(no outfits yet — press ✨ New outfit)")
            return
        for mod in mods:
            for base, slot in outfits.load(mod):
                if base >= 1000:
                    continue  # compatibility entries
                n = outfits.outfit_sprite(self.ws.fs, mod, slot)
                name = outfits.outfit_name(mod, slot)
                face = "  🙂" if os.path.exists(outfits.face_path(mod, slot)) else ""
                it = QListWidgetItem(f"{self.names().get(base, base)}  —  “{name}”{face}")
                it.setData(Qt.ItemDataRole.UserRole, (base, slot, n, mod.id))
                it.setToolTip(self._outfit_tip(mod, base, slot, n) + f"<br><i>in mod {mod.name}</i>")
                self.list.addItem(it)
                if cur and cur[:2] == (base, slot):
                    self.list.setCurrentItem(it)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)

    def _outfit_tip(self, mod, base, slot, n):
        who = self.svc.ref_tooltip("char.dat", base) or ""
        who = who.replace("<qt>", "").replace("</qt>", "")
        lines = [f"<b>Outfit “{outfits.outfit_name(mod, slot)}”</b>"]
        lines.append(f"sprite anm{n:05d} (animated by the toolkit)" if n else "no sprite yet")
        lines.append("own face picture" if os.path.exists(outfits.face_path(mod, slot))
                     else "uses the character's face")
        lines.append("own small icon in the character list" if outfits.own_colour(slot)
                     else "character list shows the normal icon")
        if n:
            lines.append("colour parts detected (presets follow hair / clothes / skin separately)"
                         if os.path.exists(outfits.parts_path(mod, n)) else "colour presets: simple (re-derive to "
                                                                            "detect parts)")
        lines.append(f"char.dat row {slot} (a copy of the character: same stats and skills)")
        return "<qt>" + "<br>".join(lines) + (f"<hr>{who}" if who else "") + "</qt>"

    def _cur(self):
        it = self.list.currentItem()
        d = it.data(Qt.ItemDataRole.UserRole) if it else None
        return d[:3] if d else None

    def _mod(self):
        """the mod the selected outfit lives in"""
        it = self.list.currentItem()
        d = it.data(Qt.ItemDataRole.UserRole) if it else None
        return self.ws.mods.get(d[3]) if d else None

    def _pick(self, it=None, prev=None):
        d = self._cur()
        mod = self._mod()
        if not d or not mod:
            self.view.set_image(None)
            self.info.setText("")
            return
        base, slot, n = d
        feats = ["own sprite" if n else "no sprite"]
        feats.append("face picture" if os.path.exists(outfits.face_path(mod, slot)) else "normal face")
        feats.append("own list icon" if outfits.own_colour(slot) else "list icon = normal face")
        who = self.names().get(base, base)
        spr = f", sprite anm{n:05d}" if n else ""
        self.info.setText(f"<b>{who} — “{outfits.outfit_name(mod, slot)}”</b>  (slot {slot}{spr}, mod "
                          f"{mod.name}):  " + ", ".join(feats))
        self._preview(lambda: outfits.preview_image(self.ws.fs, mod, slot), "preview")

    def _run(self, fn, done_msg):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.worker = Worker(fn)

        def done(res):
            QApplication.restoreOverrideCursor()
            self.refresh()
            self.ws.file_changed.emit("Database/Database_0.dat/char.dat")
            self.svc.reload()
            info_box(self, "Outfits", done_msg(res) if callable(done_msg) else done_msg)

        def failed(msg):
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Outfits", msg[:3000])

        self.worker.done.connect(done)
        self.worker.failed.connect(failed)
        self.worker.start()

    def new(self):
        mod = self.ws.require_mod(self)
        if not mod:
            return
        # outfit rows (copies of their character); other pairs link real characters and stay listed
        taken = outfits.outfit_slots(mod)
        uniques = sorted((k, v) for k, v in self.names().items()
                         if 0 < k < 1000 and "Dummy" not in v and k not in taken)
        # generic classes: one entry per family (its first rank), outfit families left out
        rows = {r["id"]: r for r in self.svc.table("char.dat").rows}
        fam_taken = {t + j for t in taken if t >= 1000 for j in range(10)}
        uniques += sorted((k, f"{rows[k]['name_EN']} (generic class)") for k in rows
                          if k >= 1000 and k % 10 == 0 and k not in fam_taken and rows[k]["name_EN"])
        set_choice_tips(uniques, self.svc.ref_tooltips("char.dat"))
        dlg = NewOutfitDialog(uniques, self)
        if not dlg.exec():
            return
        base = dlg.char.value()
        seqs = dlg.seqs
        oname = dlg.name.text().strip() or "Outfit"
        face, mirror, cut = dlg.face_file.value(), dlg.mirror.isChecked(), dlg.cut_file.value()
        self.ws.log("Creating outfit… (the first time this reads the resident sprite pack, ~15 s)")

        def work():
            r = outfits.create_outfit(self.ws.fs, mod, base, seqs, log=self.ws.log, name=oname)
            if face:
                outfits.set_face(mod, r["slot"], face, mirror)
            if cut:
                outfits.set_cutin(self.ws.fs, mod, r["slot"], cut)
            return r

        self._run(work, lambda r: f"Outfit “{oname}” created (slot {r['slot']}, sprite anm{r['sprite']:05d}).\n\n"
                                  "Check the preview, then press Install & Play (bottom left). In game: Characters → "
                                  "select the character → Outfit.")

    def replace(self):
        d = self._cur()
        mod = self._mod()
        if not d or not mod:
            return
        base, slot, n = d
        p, _ = QFileDialog.getOpenFileName(self, "Sprite sheet", "", "Images (*.png)")
        if not p:
            return
        dlg = SheetRowsDialog(p, self)
        if not dlg.exec():
            return
        seqs = dlg.sequences()

        def work():
            base_sprite = next(r for r in outfits._char_tables(self.ws.fs, mod)[1].rows if r["id"] == base)["sprite_id"]
            outfits.write_sheet_sprite(self.ws.fs, mod, base_sprite, n, seqs, self.ws.log)
            return n

        self._run(work, "Outfit sprite replaced. Press Install to see it in game.")

    def rename(self):
        d = self._cur()
        mod = self._mod()
        if not d or not mod:
            return
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Rename outfit", "Name shown in the in-game outfit list:",
                                        text=outfits.outfit_name(mod, d[1]))
        if ok and text.strip():
            outfits.set_name(mod, d[1], text)
            self.refresh()

    def face(self):
        d = self._cur()
        mod = self._mod()
        if not d or not mod:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Face picture (square)", "", "Images (*.png *.jpg *.webp)")
        if not p:
            return
        mirror = QMessageBox.question(
            self, "Face picture", "Mirror the picture?\n\nThe game's faces look to the left; "
            "choose Yes if yours looks to the right.") == QMessageBox.StandardButton.Yes
        outfits.set_face(mod, d[1], p, mirror)
        self.ws.log(f"face picture of outfit slot {d[1]} set")
        self._pick()
        info_box(self, "Outfits", "Face picture set (status panel / character list). Press Install to see it in game.")

    def cutin(self):
        d = self._cur()
        mod = self._mod()
        if not d or not mod:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Cut-in portrait (tall picture)", "", "Images (*.png *.jpg *.webp)")
        if not p:
            return
        try:
            outfits.set_cutin(self.ws.fs, mod, d[1], p)
        except Exception as e:
            QMessageBox.critical(self, "Outfits", str(e))
            return
        self.ws.log(f"cut-in portrait of outfit slot {d[1]} replaced")
        self._pick()
        info_box(self, "Outfits", "Cut-in portrait replaced. Press Install to see it in game.")

    def edit(self):
        d = self._cur()
        if d and d[2]:
            page = self.main.show_page("sprites")
            page.open_sprite(d[2], 0, f"Outfit of {self.names().get(d[0], d[0])}", False)
            page.tabs.setCurrentIndex(0)
            self.ws.log("Pick the color to edit (Normal / Extra Color 1-3), change it, then Save. The outfit's "
                        "other sprite files follow automatically when installing.")

    def paint_parts(self):
        d = self._cur()
        mod = self._mod()
        if not d or not d[2] or not mod:
            return
        from ..partpainter import PartPainterDialog
        dlg = PartPainterDialog(self.ws, mod, d[1], f"{self.names().get(d[0], d[0])} — "
                                f"{outfits.outfit_name(mod, d[1])}", self)
        dlg.exec()
        self._pick()

    def export_parts(self):
        d = self._cur()
        mod = self._mod()
        if not d or not d[2] or not mod:
            return
        try:
            folder = outfits.export_partmap(self.ws.fs, mod, d[1])
        except Exception as e:
            QMessageBox.critical(self, "Parts", str(e))
            return
        self.ws.log(f"parts exported to {folder}")
        os.startfile(folder)
        info_box(self, "Parts", f"Exported to:\n{folder}\n\nPaint parts_0.png (and parts_1.png ...) over the "
                                "sprite sheet with the legend colours — HOW_TO_PAINT.txt in that folder explains it "
                                "step by step. Then come back and press “Import painted parts”.")

    def import_parts(self):
        d = self._cur()
        mod = self._mod()
        if not d or not d[2] or not mod:
            return
        start = outfits.export_folder(mod, d[1], d[2])
        folder = QFileDialog.getExistingDirectory(self, "Folder with the painted parts_0.png ...",
                                                  start if os.path.isdir(start) else "")
        if not folder:
            return

        def work():
            outfits.import_partmap(self.ws.fs, mod, d[1], folder, log=self.ws.log)
            return outfits.parts_preview(self.ws.fs, mod, d[1])

        def done(img):
            QApplication.restoreOverrideCursor()
            self.view.set_image(img, fit=True)
            info_box(self, "Parts", "Parts imported: every part is now its own row in the game's precise colour "
                                    "editor (Part N = legend colour N). The preview shows them in several poses. "
                                    "Press Install to try it in game.")

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.worker = Worker(work)
        self.worker.done.connect(done)
        self.worker.failed.connect(lambda m: (QApplication.restoreOverrideCursor(),
                                              QMessageBox.critical(self, "Parts", m[:3000])))
        self.worker.start()

    def show_parts(self):
        d = self._cur()
        mod = self._mod()
        if not d or not d[2] or not mod:
            return
        self._preview(lambda: outfits.parts_preview(self.ws.fs, mod, d[1]), "parts preview")

    def _preview(self, fn, what):
        w = Worker(fn)
        self.pworker = w
        self._alive.add(w)
        w.done.connect(lambda img, w=w: self.view.set_image(img, fit=True) if self.pworker is w else None)
        w.failed.connect(lambda msg: self.ws.log(f"{what} failed: {msg[:300]}"))
        w.finished.connect(lambda w=w: self._alive.discard(w))
        w.start()

    def presets(self):
        d = self._cur()
        mod = self._mod()
        if not d or not d[2] or not mod:
            return
        if QMessageBox.question(self, "Color presets", "Replace the outfit's extra colors (variants 1-4) with "
                                "colors derived from the character's own presets?\n\nThe default look "
                                "(variant 0) is kept.") != QMessageBox.StandardButton.Yes:
            return
        self._run(lambda: outfits.regenerate_presets(self.ws.fs, mod, d[1], self.ws.log),
                  "Color presets re-derived. Check the preview; fine-tune them with 'Edit outfit colors'.")

    def remove(self):
        d = self._cur()
        mod = self._mod()
        if not d or not mod:
            return
        if QMessageBox.question(self, "Remove outfit", "Remove this outfit and its sprite files from the mod?\n\n"
                                "If a unit is currently wearing it in your save, switch it back in game first.") \
                != QMessageBox.StandardButton.Yes:
            return
        outfits.remove_outfit(self.ws.fs, mod, d[1])
        self.svc.reload()
        self.refresh()
