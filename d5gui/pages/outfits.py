"""Outfits: give unique characters a switchable second outfit (in-game 'Outfit' option in the unit menu)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (QMenu, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
                             QPushButton, QLabel, QComboBox, QDialog, QDialogButtonBox, QRadioButton,
                             QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QFormLayout,
                             QLineEdit, QApplication, QAbstractItemView, QCheckBox)

from d5lib import anm, framesheet, frameconvert, outfits, sprites
from ..common import PageHeader, ImageView, SearchBox, Worker, error_box, info_box, pil_to_pixmap
from ..dbservice import get_service, char_names
from .stages import SearchCombo, set_choice_tips


# the animations a sheet's rows can be, what the game uses each one for (frameconvert.DEFAULT_MAP), in a useful order
ANIM_USES = [
    ("stand", "standing still on the map and in battle"),
    ("wait", "the idle loop: base panel, hub, menus"),
    ("walk", "walking on the map"),
    ("damage", "getting hit"),
    ("attack_sword", "sword attacks and sword skills"),
    ("attack_fist", "fist attacks and fist skills"),
    ("attack_lance", "spear attacks and spear skills"),
    ("attack_arrow", "bow attacks and bow skills"),
    ("attack_gun", "gun attacks and gun skills"),
    ("attack_ax", "axe attacks and axe skills"),
    ("one_arm_up", "casting spells, using items"),
    ("take_out", "taking out an item or weapon"),
    ("two_arm_up_jump", "jumping, lifting someone overhead"),
    ("squat", "crouching (lifting, landing)"),
    ("launch", "being thrown"),
    ("landing", "landing after a jump or a throw"),
    ("rolling", "rolls and somersaults (some specials)"),
    ("kabutowari", "overhead swings (some specials)"),
    ("dash", "running in the hub"),
]
ESSENTIAL = {"stand", "wait", "walk", "damage"}


class SheetRowsDialog(QDialog):
    """Assign every row of a frame-dump sheet to an animation (pre-filled from recognised labels), with a live list of
    the game's animations the sheet covers."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sprite sheet rows")
        self.resize(1180, 720)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.im, self.rows = framesheet.parse_sheet(path)
            guesses = framesheet.guess_rows(self.im, self.rows)
        finally:
            QApplication.restoreOverrideCursor()
        lay = QVBoxLayout(self)
        known = sum(1 for g in guesses if g[2])
        head = QLabel(f"<b>{len(self.rows)} animation rows found, {known} named automatically from their labels.</b> "
                      "Check each row's animation and view (front / back) on the left; the list on the right shows "
                      "what your sheet covers. Rows set to '(ignore)' aren't used; '_hand' rows are the small "
                      "hand pieces drawn over the weapon.")
        head.setWordWrap(True)
        lay.addWidget(head)
        split = QSplitter()
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
            nc.currentTextChanged.connect(self._coverage)
            vc.currentTextChanged.connect(self._coverage)
        from PyQt6.QtCore import QSize
        self.table.setIconSize(QSize(160, 80))
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 170)
        split.addWidget(self.table)
        from PyQt6.QtWidgets import QScrollArea
        self.cover = QLabel()
        self.cover.setTextFormat(Qt.TextFormat.RichText)
        self.cover.setWordWrap(True)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cover.setContentsMargins(8, 4, 8, 4)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.cover)
        split.addWidget(sc)
        split.setSizes([700, 460])
        lay.addWidget(split, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._coverage()

    def _coverage(self, *_):
        """the game's animations and which views of them the rows give"""
        have = {}
        for nc, vc in self.combos:
            name = nc.currentText()
            if name != "(ignore)" and not name.endswith("_hand"):
                have.setdefault(name, set()).add(vc.currentText())
        rows = []
        missing_core = []
        n = 0
        for name, use in ANIM_USES:
            views = have.get(name, set())
            core = name in ESSENTIAL
            if views:
                n += 1
            if not views and core:
                missing_core.append(name)
            front = "✅" if "front" in views else ("❌" if core else "➖")
            back = "✅" if "back" in views else ("↪" if "front" in views else ("❌" if core else "➖"))
            color = "#d9534f" if (core and not views) else ("gray" if not views else None)
            style = f" style='color:{color}'" if color else ""
            rows.append(f"<tr><td>{front}</td><td>{back}</td><td{style}><b>{name}</b>"
                        + (" <span style='color:#f0b35a'>needed</span>" if core else "")
                        + f"<br><span style='color:gray'>{use}</span></td></tr>")
        summary = (f"<b>Your sheet covers {n} of {len(ANIM_USES)} animations.</b><br>"
                   + (f"<span style='color:#d9534f'>Missing what every character needs: {', '.join(missing_core)}."
                      "</span><br>" if missing_core else
                      "<span style='color:#3ecf8e'>Everything every character needs is there.</span><br>")
                   + "<span style='color:gray'>Every pose of the game is matched to the most similar frame of your "
                     "sheet; the rows' names guide the match. An animation the sheet lacks borrows the closest frames "
                     "of other rows, which can look off in those moves. Only the attack rows of the weapons the unit "
                     "uses matter. ↪ = no back view: the front frames are used. After the conversion, odd poses can "
                     "be fixed on the Weapon Grips and Sprites &amp; Colors pages.</span>")
        self.cover.setText(summary + "<table cellspacing='4'><tr><td><b>Front</b></td><td><b>Back</b></td>"
                                     "<td><b>Animation</b></td></tr>" + "".join(rows) + "</table>")

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

    def __init__(self, uniques, parent=None, ws=None):
        super().__init__(parent)
        self.ws = ws
        self.drpg_unit = None
        self._names = dict(uniques)
        self.setWindowTitle("New outfit")
        self.resize(680, 480)
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
        from d5lib import drpgsource
        self.drpg_ok = set(drpgsource.character_sprites())
        self.drpg = QRadioButton("Disgaea RPG sprites (a unit's four sheets: the easiest way)")
        self.drpg.setToolTip("Pick a unit from your Disgaea RPG folder (or four sheet files of your own): its "
                             "battle and idle sheets become the outfit's complete sprite, and its face and cut-in "
                             "are used too.")
        self.copy = QRadioButton("Start from a copy of the character's sprite (repaint it in Sprites && Colors)")
        self.sheet = QRadioButton("Convert a sprite sheet (frame dump: labelled rows of whole-pose frames)")
        self.drpg.setChecked(True)
        self.sheet.setToolTip("A sprite sheet PNG with one labelled row per animation (stand, walk, attack …), "
                              "front and back views. Every frame is matched to the game's own poses, so the "
                              "outfit animates exactly like the character. Colour presets are made automatically.")
        self.copy.setToolTip("The outfit starts as an exact copy of the character's sprite; recolour or repaint it "
                             "afterwards in Sprites & Colors.")
        f.addRow(self.drpg)
        drow = QHBoxLayout()
        self.drpg_btn = QPushButton("Choose the unit…")
        self.drpg_btn.clicked.connect(self._choose_drpg)
        drow.addWidget(self.drpg_btn)
        self.drpg_label = QLabel("no unit chosen yet")
        self.drpg_label.setObjectName("muted")
        drow.addWidget(self.drpg_label, 1)
        f.addRow("", drow)
        self.drpg_note = QLabel()
        self.drpg_note.setWordWrap(True)
        self.drpg_note.setObjectName("muted")
        f.addRow("", self.drpg_note)
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
        for w in (self.drpg, self.sheet, self.copy):
            w.toggled.connect(self._mode)
        self.char.currentIndexChanged.connect(self._mode)
        self.char.editTextChanged.connect(self._mode)
        self._mode()

    def _mode(self, *_):
        d = self.drpg.isChecked()
        self.drpg_btn.setEnabled(d)
        self.drpg_label.setEnabled(d)
        self.sheet_file.setEnabled(self.sheet.isChecked())
        base = self.char.value()
        if not d:
            self.drpg_note.setText("")
        elif base and base not in self.drpg_ok:
            self.drpg_note.setText("⚠ This character can't take Disgaea RPG sprites yet (the kit hasn't learned its "
                                   "poses). Characters that can: " + self._drpg_names() + ".")
        else:
            self.drpg_note.setText("The unit's face and cut-in are used when the folder has them; pictures chosen "
                                   "below replace them.")

    def _drpg_names(self):
        return ", ".join(sorted(self._names.get(c, str(c)) for c in self.drpg_ok))

    def _choose_drpg(self):
        from ..drpgpicker import DrpgPicker
        dlg = DrpgPicker(self.ws, "outfit", self)
        if dlg.exec() and dlg.unit:
            self.drpg_unit = dlg.unit
            self.drpg_label.setText(f"{dlg.unit.label()}")
            if self.name.text().strip() in ("", "Outfit") and dlg.unit.name:
                self.name.setText(dlg.unit.name)

    def _ok(self):
        if not self.char.value():
            QMessageBox.warning(self, "New outfit", "Choose a character.")
            return
        if self.drpg.isChecked():
            if self.char.value() not in self.drpg_ok:
                QMessageBox.warning(self, "New outfit", "This character can't take Disgaea RPG sprites yet. "
                                    "Characters that can: " + self._drpg_names() + ".")
                return
            if not self.drpg_unit:
                QMessageBox.warning(self, "New outfit", "Choose the Disgaea RPG unit first.")
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


NEXT_STEPS = ("If something looks off, adjust it by hand:\n"
              "• The weapon isn't in the hand → Weapon Grips page (drag the weapon onto the hand).\n"
              "• A colour or extra colour looks wrong → Paint parts… / Re-derive color presets (this page), or "
              "Sprites & Colors.\n"
              "• Face or cut-in → Face… / Cut-in… (this page).")


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
        self.search = SearchBox("Search outfits or characters…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.list = QTreeWidget()                    # one group per character, its outfits inside
        self.list.setHeaderHidden(True)
        self.list.setIndentation(14)
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
        self.view = ImageView(smooth=True)      # like the game draws it
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
        self._shown_sig = None
        ws.active_mod_changed.connect(lambda _: self.refresh())

    def on_show(self):
        if self._shown_sig != self._sig():            # rebuilding the list takes ~0.4 s: only when something changed
            self.refresh()

    def _sig(self):
        """what the list is made of: the mods (modsys.change_token) and which one is active"""
        from d5lib.modsys import change_token
        act = self.ws.active_mod
        return change_token(self.ws.mods.mods_dir), act.id if act else None

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
        self._shown_sig = self._sig()
        cur = self._cur()
        opened = {self.list.topLevelItem(k).data(0, Qt.ItemDataRole.UserRole + 1)
                  for k in range(self.list.topLevelItemCount()) if self.list.topLevelItem(k).isExpanded()}
        self.list.clear()
        mods = self._outfit_mods()
        if not mods:
            it = QTreeWidgetItem(["(no outfits yet — press ✨ New outfit)"])
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.list.addTopLevelItem(it)
            return
        # outfits a mod hides (kept only so saves using them still work, e.g. Girl Laharl's Thunderlady looks,
        # which are the Thunderlady character's own): not listed, like in the game's Outfit menu
        hidden = {int(h) for m in mods for h in outfits._data(m).get("hide", [])}
        groups = {}
        pick = None
        bold = self.list.font()
        bold.setBold(True)
        for mod in mods:
            sprites = outfits.outfit_sprites(self.ws.fs, mod)        # one table load per mod, not per outfit
            names = outfits.load_names(mod)
            for base, slot in outfits.load(mod):
                if base >= 1000 or int(slot) in hidden:
                    continue  # compatibility entries / hidden
                g = groups.get(base)
                if g is None:
                    g = groups[base] = QTreeWidgetItem([str(self.names().get(base, base))])
                    g.setData(0, Qt.ItemDataRole.UserRole + 1, int(base))
                    g.setFont(0, bold)
                    g.setFlags(Qt.ItemFlag.ItemIsEnabled)
                n = sprites.get(slot)
                name = names.get(int(slot)) or "Outfit"
                face = "  🙂" if os.path.exists(outfits.face_path(mod, slot)) else ""
                it = QTreeWidgetItem([f"“{name}”{face}"])
                it.setData(0, Qt.ItemDataRole.UserRole, (base, slot, n, mod.id))
                it.setToolTip(0, self._outfit_tip(mod, base, slot, n, name) + f"<br><i>in mod {mod.name}</i>")
                g.addChild(it)
                if cur and cur[:2] == (base, slot):
                    pick = it
        for base, g in sorted(groups.items(), key=lambda kv: kv[1].text(0).lower()):
            n = g.childCount()
            g.setToolTip(0, f"{g.text(0)}: {n} outfit{'s' if n != 1 else ''}")
            g.setText(0, f"{g.text(0)}  ({n})")
            self.list.addTopLevelItem(g)
            g.setExpanded(base in opened)
        if pick is None and groups:
            g = self.list.topLevelItem(0)
            pick = g.child(0) if g.childCount() else None
        if pick is not None:
            pick.parent().setExpanded(True)
            self.list.setCurrentItem(pick)
            self.list.scrollToItem(pick)
        self._filter()

    def _filter(self, *a):
        t = self.search.text().lower().strip()
        for k in range(self.list.topLevelItemCount()):
            g = self.list.topLevelItem(k)
            whole = bool(t) and t in g.text(0).lower()
            any_ = False
            for j in range(g.childCount()):
                c = g.child(j)
                ok = not t or whole or t in c.text(0).lower()
                c.setHidden(not ok)
                any_ |= ok
            g.setHidden(not any_ and g.childCount() > 0)
            if t and any_:
                g.setExpanded(True)

    def _outfit_tip(self, mod, base, slot, n, name=None):
        who = self.svc.ref_tooltip("char.dat", base) or ""
        who = who.replace("<qt>", "").replace("</qt>", "")
        lines = [f"<b>Outfit “{name or outfits.outfit_name(mod, slot)}”</b>"]
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
        d = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        return d[:3] if d else None

    def _mod(self):
        """the mod the selected outfit lives in"""
        it = self.list.currentItem()
        d = it.data(0, Qt.ItemDataRole.UserRole) if it else None
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

    def _run(self, fn, done_msg, busy=None):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.worker = Worker(fn)
        prog = None
        if busy:
            from PyQt6.QtWidgets import QProgressDialog
            prog = QProgressDialog(busy + "\n(this can take a minute; the log at the bottom shows the steps)", None,
                                   0, 0, self)
            prog.setWindowTitle("Outfits")
            prog.setMinimumDuration(0)
            prog.setWindowModality(Qt.WindowModality.WindowModal)
            prog.show()

        def done(res):
            if prog:
                prog.close()
            QApplication.restoreOverrideCursor()
            self.refresh()
            self.ws.file_changed.emit("Database/Database_0.dat/char.dat")
            self.svc.reload()
            info_box(self, "Outfits", done_msg(res) if callable(done_msg) else done_msg)

        def failed(msg):
            if prog:
                prog.close()
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
        dlg = NewOutfitDialog(uniques, self, ws=self.ws)
        it = self.list.currentItem()                 # the character whose group is open
        if it is not None:
            g = it.parent() or it
            base = g.data(0, Qt.ItemDataRole.UserRole + 1)
            if base is not None and any(k == base for k, _ in uniques):
                dlg.char.set_value(base)
        if not dlg.exec():
            return
        base = dlg.char.value()
        seqs = dlg.seqs
        unit = dlg.drpg_unit if dlg.drpg.isChecked() else None
        oname = dlg.name.text().strip() or "Outfit"
        face, mirror, cut = dlg.face_file.value(), dlg.mirror.isChecked(), dlg.cut_file.value()
        self.ws.log("Creating outfit… (the first time this reads the resident sprite pack, ~15 s)"
                    + (f" from Disgaea RPG unit {unit.uid}: about a minute" if unit else ""))

        def work():
            if unit is not None:
                from d5lib import drpgsource
                with drpgsource.using(self.ws.settings.get(drpgsource.SETTING)):
                    r = outfits.create_drpg_outfit(self.ws.fs, mod, base, unit.uid, oname, log=self.ws.log)
            else:
                r = outfits.create_outfit(self.ws.fs, mod, base, seqs, log=self.ws.log, name=oname)
            if face:
                outfits.set_face(mod, r["slot"], face, mirror)
            if cut:
                outfits.set_cutin(self.ws.fs, mod, r["slot"], cut)
            return r

        self._run(work, lambda r: f"Outfit “{oname}” created (slot {r['slot']}, sprite anm{r['sprite']:05d})"
                                  + (f" from Disgaea RPG unit {unit.uid}" if unit else "") + ".\n\n"
                                  "Next: check the preview here, then press Install & Play (bottom left). In game: "
                                  "Characters → select the character → Outfit.\n\n" + NEXT_STEPS,
                  busy=f"Making the outfit “{oname}”…")

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
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(folder)))
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
