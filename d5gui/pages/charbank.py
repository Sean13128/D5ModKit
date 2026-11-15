"""Character Bank: units of a save copy (left) and of the bank folder (right), shown as pictures.

Logic is d5gui/bankview.py (tested headless); save format is tools/unit_bank.py -> d5lib/unitbank.py.
Works on any save: one in the game's folder (or a kit profile's saves) is backed up to state/save_backups before
every change, and not changed while the game runs.
"""
import os

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from d5lib import savegame

from .. import bankview
from ..workspace import KIT_DIR
from ..common import PageHeader, pil_to_pixmap

BADGE_COLOURS = {"D5": "#7a4fd1", "D4": "#2e7d6b", "D1C": "#b5651d", "DD2": "#2f6fb5", "DRPG": "#b52f6f", "?": "#777"}


def picture(label, pil, size, why):
    """a QLabel holding the image scaled into size, or a labelled placeholder (never a wrong picture)"""
    label.setFixedSize(size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if pil is None:
        label.setWordWrap(True)
        label.setStyleSheet("border:1px dashed #999; color:#888; font-size:9px;")
        label.setText(f"art not found: {why}")
        label.setToolTip(f"art not found: {why}")
    else:
        label.setPixmap(pil_to_pixmap(pil).scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))


class CardWidget(QFrame):
    def __init__(self, card, art):
        super().__init__()
        self.card = card
        stand, face, why = art.resolve(card.cls) if art else (None, None, "game folder not set")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        f = QLabel()
        picture(f, face, QSize(72, 72), why or "this class has no face")
        s = QLabel()
        picture(s, stand, QSize(80, 96), why or "no stand pose")
        lay.addWidget(f)
        lay.addWidget(s)
        col = QVBoxLayout()
        top = QHBoxLayout()
        name = QLabel(f"<b>{card.name}</b>")
        badge = QLabel(card.game)
        badge.setStyleSheet(f"background:{BADGE_COLOURS.get(card.game, '#777')}; color:white; border-radius:3px;"
                            f" padding:0 5px; font-size:10px; font-weight:bold;")
        badge.setToolTip(card.game_why)
        top.addWidget(name)
        top.addWidget(badge)
        top.addStretch(1)
        col.addLayout(top)
        col.addWidget(QLabel(f"{card.title}  ·  Lv {card.level}"))
        if card.refusal:
            r = QLabel(card.refusal)
            r.setWordWrap(True)
            r.setStyleSheet("color:#c0392b; font-size:11px;")
            col.addWidget(r)
        col.addStretch(1)
        lay.addLayout(col, 1)


class CharBankPage(QWidget):
    def __init__(self, ws, main=None):
        super().__init__()
        self.ws = ws
        self.save_path = ""
        self.bank_dir = ""
        self.installed, self.vanilla, self.badges, self.skill_ids = {}, {}, {}, None
        self.art = None
        self.save = None
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Character Bank", "Take a unit out of a save into the bank, or put a banked "
                                 "unit into a save. A real save is backed up first."))
        self.banner = QLabel("A save in the game's folder is changed for real, after a backup (state/save_backups). "
                             "Close the game first. A save elsewhere is your own copy: no backup.")
        self.banner.setStyleSheet("background:#fff3cd; color:#664d03; padding:4px 8px; border-radius:4px;")
        lay.addWidget(self.banner)
        bar = QHBoxLayout()
        self.save_edit = QLineEdit()
        self.save_edit.setPlaceholderText("Save (Save_NNN.sav)")
        self.bank_edit = QLineEdit()
        self.bank_edit.setPlaceholderText("Bank folder")
        b1, b2 = QPushButton("Choose save…"), QPushButton("Choose bank folder…")
        b1.clicked.connect(self._choose_save)
        b2.clicked.connect(self._choose_bank)
        bar.addWidget(self.save_edit, 1), bar.addWidget(b1), bar.addWidget(self.bank_edit, 1), bar.addWidget(b2)
        lay.addLayout(bar)
        cols = QHBoxLayout()
        self.left, self.right = QListWidget(), QListWidget()
        mid = QVBoxLayout()
        self.b_export = QPushButton("Export →")
        self.b_import = QPushButton("← Import")
        self.b_export.setToolTip("Export the selected save units to the bank folder")
        self.b_import.setToolTip("Import the selected bank units into the save")
        self.b_export.clicked.connect(self.export_selected)
        self.b_import.clicked.connect(self.import_selected)
        self.c_unequip = QCheckBox("Unequip")
        self.c_unequip.setToolTip("Export without items: the unit's equipped items go into the save's item bag")
        mid.addStretch(1), mid.addWidget(self.b_export), mid.addWidget(self.c_unequip), mid.addWidget(self.b_import)
        mid.addStretch(1)
        for lw in (self.left, self.right):
            lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            lw.setSpacing(2)
            lw.itemSelectionChanged.connect(lambda lw=lw: self._show_details(lw))
        for title, lw in (("Units in the save", self.left), ("Units in the bank", self.right)):
            v = QVBoxLayout()
            v.addWidget(QLabel(title))
            v.addWidget(lw, 1)
            cols.addLayout(v, 1)
            if lw is self.left:
                cols.addLayout(mid)
        lay.addLayout(cols, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(110)
        lay.addWidget(self.details)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.save_edit.editingFinished.connect(self.refresh)
        self.bank_edit.editingFinished.connect(self.refresh)

    # ------------------------------------------------------------------ data
    def _load_game(self):
        if self.art is not None:
            return
        gd = getattr(self.ws, "game_dir", "")
        try:
            self.art = bankview.Art(gd)
            self.installed = {c: r["name_EN"] for c, r in self.art.rows.items()}
            self.vanilla = ({c: r["name_EN"] for c, r in bankview.vanilla_rows(self.ws.fs).items()}
                            if getattr(self.ws, "fs", None) else bankview.unit_bank.game_char_names(gd))
            try:
                self.skill_ids = bankview.unit_bank.skill_ids(os.path.join(gd, "Data", "Database", "Database_0.dat"))
            except Exception:                                         # noqa: BLE001  only needed to start a companion
                self.skill_ids = None
            self.badges = bankview.game_badges(os.path.join(gd, "D5ModKit", "mods"))
        except Exception as ex:                                       # noqa: BLE001
            self.art = None
            self.status.setText(f"Cannot read the installed game ({gd}): {ex}. Cards show no art, and import "
                                f"cannot check which classes are installed.")

    def set_paths(self, save_path, bank_dir):
        self.save_edit.setText(save_path or "")
        self.bank_edit.setText(bank_dir or "")
        self.refresh()

    def _choose_save(self):
        p, _ = QFileDialog.getOpenFileName(self, "Save", self._save_start(), "Saves (*.sav)")
        if p:
            self.save_edit.setText(p)
            self.refresh()

    def _save_start(self):
        """the dialog starts where the last save was, else in the game's save folder when it exists"""
        if self.save_path:
            return os.path.dirname(self.save_path)
        root = savegame.save_root()
        return root if os.path.isdir(root) else ""

    def _choose_bank(self):
        p = QFileDialog.getExistingDirectory(self, "Bank folder")
        if p:
            self.bank_edit.setText(p)
            self.refresh()

    def refresh(self):
        self._load_game()
        self.save_path, self.bank_dir = self.save_edit.text().strip(), self.bank_edit.text().strip()
        self.left.clear(), self.right.clear()
        self.save = None
        msgs = []
        if self.save_path:
            try:
                cards, self.save = bankview.save_cards(self.save_path, self.installed, self.vanilla, self.badges, live=True)
                self._fill(self.left, cards)
            except Exception as ex:                                   # noqa: BLE001
                msgs.append(f"Save not opened: {ex}")
        if self.bank_dir:
            self._fill(self.right, bankview.bank_cards(self.bank_dir, self.installed, self.vanilla, self.save,
                                                       self.badges))
        if msgs:
            self.status.setText(" ".join(msgs))

    def _fill(self, lw, cards):
        for c in cards:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, c)
            w = CardWidget(c, self.art)
            it.setSizeHint(w.sizeHint())
            lw.addItem(it)
            lw.setItemWidget(it, w)

    def _selected(self, lw):
        return [i.data(Qt.ItemDataRole.UserRole) for i in lw.selectedItems()]

    def _show_details(self, lw):
        cards = self._selected(lw)
        if cards:
            c = cards[0]
            self.details.setPlainText("\n".join([f"{c.name} ({c.title}), Lv {c.level}, {c.game}", *c.details,
                                                 *([c.refusal] if c.refusal else [])]))

    # ------------------------------------------------------------------ actions
    def export_selected(self):
        if not (self.save_path and self.bank_dir):
            self.status.setText("Choose a save and a bank folder first.")
            return
        cards = sorted(self._selected(self.left), key=lambda c: -int(c.key))   # last slot first: a move shifts later slots
        out = [bankview.do_export(self.save_path, c, self.bank_dir, self.vanilla, live=True, kit_dir=KIT_DIR,
                                   unequip=self.c_unequip.isChecked())[0] for c in cards] or ["Select units in the save copy first."]
        self.refresh()
        self.status.setText("\n".join(out))

    def import_selected(self):
        if not (self.save_path and self.bank_dir):
            self.status.setText("Choose a save and a bank folder first.")
            return
        out = []
        for c in self._selected(self.right):
            out.append(bankview.do_import(self.save_path, c, self.installed, self.vanilla, self.skill_ids, live=True, kit_dir=KIT_DIR)[0])
        self.refresh()
        self.status.setText("\n".join(out) or "Select units in the bank first.")
