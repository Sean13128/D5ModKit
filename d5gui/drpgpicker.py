"""Choosing Disgaea RPG sprites in the editors: the DRPG folder, its units with a checklist of the sheets each one
has, and four sheet files picked by hand (d5lib.drpgsource)."""
import html
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QImage, QPixmap, QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
                             QListWidget, QListWidgetItem, QComboBox, QSplitter, QWidget, QDialogButtonBox,
                             QFileDialog, QMessageBox, QApplication, QToolButton, QFrame)

from d5lib import drpgsource as ds

from .common import Worker, pil_to_pixmap

OK, NO, OPT = "✅", "❌", "➖"

FOLDER_HELP = (
    "<b>What goes in the Disgaea RPG folder</b><br>"
    "Every unit needs <b>four sprite sheets</b>, named by the unit's number (1234 here). Either layout works:"
    "<table cellspacing='0' cellpadding='4'><tr><td valign='top'>"
    "<pre style=\"font-family: Consolas, 'Courier New', monospace; margin:2px 18px 2px 0\">"
    "DRPG Assets (Updated)\\\n"
    "  Characters\\\n"
    "    Sprites\\\n"
    "      front\\       front1234.png\n"
    "      back\\        back1234.png\n"
    "      wait_front\\  front1234.png\n"
    "      wait_back\\   back1234.png\n"
    "    Icons\\         1234.png  (optional)\n"
    "    Cut-Ins\\       1234.png  (optional)</pre></td><td valign='top'>"
    "<pre style=\"font-family: Consolas, 'Courier New', monospace; margin:2px 0\">"
    "DRPG Assets (Updated)\\\n"
    "  Sprites\\\n"
    "    Standard\\\n"
    "      BattleFront\\ front1234.png\n"
    "      BattleBack\\  back1234.png\n"
    "      WaitFront\\   front1234.png\n"
    "      WaitBack\\    back1234.png\n"
    "  Chara Icons\\     1234.png  (optional)\n"
    "  Cutins\\          1234.png  (optional)</pre></td></tr></table>"
    "<b>Battle sprites</b> hold every battle pose (walk, attacks, damage …), <b>Idle</b> the standing loop; each "
    "comes seen from the front and from the back. The face and cut-in are optional. A <i>Units IDs.txt</i> in the "
    "folder gives the units their names. Choose the folder that contains <i>Characters</i> (or <i>Sprites</i>); "
    "a folder called <i>DRPG Assets (Updated)</i> inside the D5ModKit folder is found by itself.")

PURPOSE = {
    "outfit": "an outfit",
    "character": "a new character",
    "class": "a new class",
}


class _Thumbs(QThread):
    """faces for the list, loaded in the background"""
    ready = pyqtSignal(int, QImage)

    def __init__(self, units, size=40):
        super().__init__()
        self.units, self.size = units, size
        self.stop = False

    def run(self):
        from PIL import Image
        for u in self.units:
            if self.stop:
                return
            p = ds.thumbnail_path(u)
            if not p:
                continue
            try:
                im = Image.open(p).convert("RGBA")
                im.thumbnail((self.size, self.size))
                data = im.tobytes("raw", "RGBA")
                q = QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()
                self.ready.emit(u.uid, q)
            except Exception:
                continue


def _checklist(unit, layouts=None, extras=None):
    """rich text: the four sheets (✅/❌ and the layout check) and the optional pictures"""
    sheets = unit.sheets()
    rows = []
    for key, label, what, fname in ds.SHEETS:
        p = sheets.get(key)
        if not p:
            mark, note = NO, f"missing: {html.escape(fname.format(uid=unit.uid))}"
        elif layouts is not None and layouts.get(key) is None and key in ds.LAYOUT_REQUIRED:
            mark, note = "⚠️", "found, but not laid out like a Disgaea RPG sheet"
        else:
            mark, note = OK, html.escape(os.path.basename(p))
        rows.append(f"<tr><td>{mark}</td><td><b>{label}</b><br><span style='color:gray'>{what}</span></td>"
                    f"<td style='color:gray'>{note}</td></tr>")
    ex = extras if extras is not None else unit.extras()
    for key, label, what in ds.EXTRAS:
        mark, note = (OK, html.escape(os.path.basename(ex[key]))) if key in ex else (OPT, "not there (optional)")
        rows.append(f"<tr><td>{mark}</td><td><b>{label}</b> <span style='color:gray'>(optional)</span><br>"
                    f"<span style='color:gray'>{what}</span></td><td style='color:gray'>{note}</td></tr>")
    return "<table cellspacing='4'>" + "".join(rows) + "</table>"


class DrpgPicker(QDialog):
    """pick a Disgaea RPG unit (or four sheets of your own) for an outfit, a new character or a new class"""

    def __init__(self, ws, purpose="character", parent=None, title=None):
        super().__init__(parent)
        self.ws, self.purpose = ws, purpose
        self.unit = None
        self.units = {}
        self._layouts = {}
        self._thumbs = None
        self._detail_token = 0
        self.setWindowTitle(title or "Disgaea RPG sprites")
        self.resize(1040, 680)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>Choose the Disgaea RPG unit for {PURPOSE.get(purpose, 'it')}</b>")
        lay.addWidget(head)
        intro = QLabel("Its four sprite sheets are turned into a complete Disgaea 5 sprite: every animation, from the "
                       "front and the back, moving like the game's own characters. Its face and cut-in are used "
                       "too when the folder has them.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        # ---- the folder
        row = QHBoxLayout()
        row.addWidget(QLabel("Disgaea RPG folder:"))
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        row.addWidget(self.folder, 1)
        b = QPushButton("Choose folder…")
        b.clicked.connect(self.choose_folder)
        row.addWidget(b)
        self.help_btn = QToolButton()
        self.help_btn.setText("What goes in this folder?")
        self.help_btn.setCheckable(True)
        row.addWidget(self.help_btn)
        lay.addLayout(row)
        self.help = QLabel(FOLDER_HELP)
        self.help.setWordWrap(True)
        self.help.setTextFormat(Qt.TextFormat.RichText)
        self.help.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.help.setFrameShape(QFrame.Shape.StyledPanel)
        self.help.setContentsMargins(10, 8, 10, 8)
        self.help.hide()
        self.help_btn.toggled.connect(self.help.setVisible)
        lay.addWidget(self.help)

        # ---- units | details
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        frow = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search a name or unit number…")
        self.search.textChanged.connect(self.fill)
        frow.addWidget(self.search, 1)
        self.group = QComboBox()
        self.group.addItem("Characters & classes", "human")
        self.group.addItem("Unique characters", "unique")
        self.group.addItem("Generic classes", "generic")
        self.group.addItem("Monsters", "monster")
        self.group.addItem("My own sheets", "custom")
        self.group.addItem("Everything", "")
        self.group.currentIndexChanged.connect(self.fill)
        frow.addWidget(self.group)
        ll.addLayout(frow)
        self.count = QLabel()
        self.count.setObjectName("muted")
        ll.addWidget(self.count)
        self.list = QListWidget()
        self.list.setIconSize(QSize(40, 40))
        self.list.setUniformItemSizes(True)
        self.list.currentItemChanged.connect(self.show_unit)
        self.list.itemDoubleClicked.connect(lambda _: self._ok())
        ll.addWidget(self.list, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QGridLayout(right)
        self.picture = QLabel()
        self.picture.setFixedSize(220, 240)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setFrameShape(QFrame.Shape.StyledPanel)
        rl.addWidget(self.picture, 0, 0, 3, 1, Qt.AlignmentFlag.AlignTop)
        self.name = QLabel()
        self.name.setObjectName("cardTitle")
        self.name.setWordWrap(True)
        rl.addWidget(self.name, 0, 1)
        self.kind = QLabel()
        self.kind.setObjectName("muted")
        self.kind.setWordWrap(True)
        rl.addWidget(self.kind, 1, 1)
        self.check = QLabel()
        self.check.setTextFormat(Qt.TextFormat.RichText)
        self.check.setWordWrap(True)
        self.check.setAlignment(Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self.check, 2, 1)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.verdict, 3, 0, 1, 2)
        rl.setColumnStretch(1, 1)
        rl.setRowStretch(4, 1)
        split.addWidget(right)
        split.setSizes([380, 660])
        lay.addWidget(split, 1)

        # ---- own sheets / ok
        brow = QHBoxLayout()
        own = QPushButton("Use my own sheet files…")
        own.setToolTip("Four sheets in Disgaea RPG's layout from anywhere (another download, sheets you edited): "
                       "pick each file, the kit checks it and keeps a copy.")
        own.clicked.connect(self.own_sheets)
        brow.addWidget(own)
        brow.addStretch(1)
        self.bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setText("Use this unit")
        self.bb.accepted.connect(self._ok)
        self.bb.rejected.connect(self.reject)
        brow.addWidget(self.bb)
        lay.addLayout(brow)
        self.rescan()

    # ------------------------------------------------------------------ folder / list
    def rescan(self):
        chosen = self.ws.settings.get(ds.SETTING) or None
        ds.apply(chosen)
        fol = ds.folders(chosen)
        self.folder.setText(chosen or (fol[0] if fol else "(none chosen yet)"))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.units = ds.scan(chosen)
        finally:
            QApplication.restoreOverrideCursor()
        if not [u for u in self.units.values() if not u.custom]:
            self.help_btn.setChecked(True)
        self.fill()
        if self._thumbs:
            self._thumbs.stop = True
        self._thumbs = _Thumbs(sorted(self.units.values(), key=lambda u: u.uid))
        self._thumbs.ready.connect(self._thumb)
        self._thumbs.start()

    def choose_folder(self):
        start = self.ws.settings.get(ds.SETTING) or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, "Disgaea RPG folder (the one with Characters or Sprites)", start)
        if not d:
            return
        root = ds.looks_like_drpg_root(d)
        if not root:
            QMessageBox.warning(self, "Disgaea RPG folder",
                                f"{d}\n\nhas no sprite sheets in a layout the kit knows. Choose the folder that "
                                "contains Characters\\Sprites\\front (or Sprites\\Standard\\BattleFront).")
            self.help_btn.setChecked(True)
            return
        self.ws.settings[ds.SETTING] = root
        self.ws.save_settings()
        self.rescan()

    def _visible(self, u):
        g = self.group.currentData()
        if g == "custom":
            ok = u.custom
        elif g == "human":
            ok = not u.monster
        elif g == "monster":
            ok = u.monster
        elif g in ("unique", "generic"):
            ok = u.group == g
        else:
            ok = True
        q = self.search.text().strip().lower()
        return ok and (not q or q in u.name.lower() or q in str(u.uid))

    def fill(self, *_):
        cur = self.unit.uid if self.unit else None
        self.list.blockSignals(True)
        self.list.clear()
        self._items = {}
        shown = 0
        for u in sorted(self.units.values(), key=lambda u: (u.custom is False, u.uid)):
            if not self._visible(u):
                continue
            it = QListWidgetItem(("⚠ " if u.missing() else "") + u.label())
            it.setData(Qt.ItemDataRole.UserRole, u.uid)
            if u.missing():
                it.setToolTip("Missing: " + ", ".join(lbl for k, lbl, *_ in ds.SHEETS if k in u.missing()))
            if getattr(self, "_icons", {}).get(u.uid):
                it.setIcon(self._icons[u.uid])
            self.list.addItem(it)
            self._items[u.uid] = it
            shown += 1
            if u.uid == cur:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        total = len([u for u in self.units.values() if not u.custom])
        self.count.setText(f"{shown} shown · {total} units in the folder"
                           + (f" · {len(self.units) - total} of your own" if len(self.units) > total else ""))
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _thumb(self, uid, q):
        if not hasattr(self, "_icons"):
            self._icons = {}
        icon = QIcon(QPixmap.fromImage(q))
        self._icons[uid] = icon
        it = getattr(self, "_items", {}).get(uid)
        if it is not None:
            it.setIcon(icon)

    # ------------------------------------------------------------------ details
    def show_unit(self, it, *_):
        if it is None:
            self.unit = None
            return
        u = self.units.get(it.data(Qt.ItemDataRole.UserRole))
        self.unit = u
        self.name.setText(u.name or f"Unit {u.uid}")
        kind = {"unique": "Unique character", "generic": "Generic class", "unique monster": "Unique monster",
                "generic monster": "Monster class"}.get(u.group, "Unit")
        self.kind.setText(f"{kind} · unit {u.uid}" + (" · your own sheets" if u.custom else "")
                          + f"\n{os.path.dirname(os.path.dirname(u.sheets()['front'] or u.root))}")
        self.check.setText(_checklist(u))
        self.picture.setText("…")
        self.verdict.setText("<span style='color:gray'>Checking the sheets…</span>")
        self._detail_token += 1
        token = self._detail_token
        w = Worker(lambda: (ds.preview(u), ds.layouts(u), u.extras()))
        w.done.connect(lambda res, token=token, u=u: self._details(token, u, res))
        w.start()
        self._w = w

    def _details(self, token, u, res):
        if token != self._detail_token:
            return
        im, lays, extras = res
        self._layouts[u.uid] = lays
        if im is not None:
            im.thumbnail((210, 230))
            self.picture.setPixmap(pil_to_pixmap(im))
        else:
            self.picture.setText("(no picture)")
        self.check.setText(_checklist(u, lays, extras))
        self.verdict.setText(self._verdict(u, lays))

    def _problem(self, u, lays):
        """(title, explanation) of what stops this unit, or None when it is ready"""
        miss = u.missing()
        bad = [k for k in ds.LAYOUT_REQUIRED if lays.get(k) is None and k not in miss]
        if u.monster and self.purpose in PURPOSE:
            return ("A monster", "monsters move differently from humanoid characters, so this unit can't become "
                    f"{PURPOSE[self.purpose]} here. Pick a character or class unit.")
        if miss:
            return ("Not usable yet", ", ".join(lbl for k, lbl, *_ in ds.SHEETS if k in miss) +
                    " missing. Add the file(s) to the folder (see 'What goes in this folder?').")
        if bad:
            return ("Can't be converted", ", ".join(lbl for k, lbl, *_ in ds.SHEETS if k in bad) +
                    " isn't packed like a Disgaea RPG sheet, so the kit can't tell which drawing is which pose. "
                    "For sheets of another kind, use a frame-dump sheet (Outfits › New outfit › Convert a sprite "
                    "sheet).")
        return None

    def _verdict(self, u, lays):
        p = self._problem(u, lays)
        if p:
            return f"<span style='color:#d9534f'><b>{p[0]}:</b> {html.escape(p[1])}</span>"
        return "<span style='color:#3ecf8e'><b>Ready:</b> all four sheets found and recognised.</span>"

    def _ok(self):
        u = self.unit
        if u is None:
            return
        lays = self._layouts.get(u.uid)
        if lays is None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                lays = ds.layouts(u)
            finally:
                QApplication.restoreOverrideCursor()
            self._layouts[u.uid] = lays
        p = self._problem(u, lays)
        if p:
            QMessageBox.warning(self, "Disgaea RPG sprites", f"{p[0]}: {p[1]}")
            return
        if self._thumbs:
            self._thumbs.stop = True
        self.accept()

    def own_sheets(self):
        dlg = OwnSheetsDialog(self)
        if not dlg.exec():
            return
        self.units = ds.scan(self.ws.settings.get(ds.SETTING) or None)
        self.group.setCurrentIndex(self.group.findData("custom"))
        self.unit = self.units.get(dlg.uid)
        self.fill()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == dlg.uid:
                self.list.setCurrentRow(i)

    def done(self, r):
        if self._thumbs:
            self._thumbs.stop = True
            self._thumbs.wait(2000)
        super().done(r)


class OwnSheetsDialog(QDialog):
    """four sheets in Disgaea RPG's layout from anywhere: each file checked as it is chosen, then copied as a unit
    of its own (state/drpg_custom)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My own sheet files")
        self.resize(820, 520)
        self.uid = None
        self.files, self.marks = {}, {}
        lay = QVBoxLayout(self)
        intro = QLabel("Pick four sprite sheets laid out like Disgaea RPG's: each sheet is one picture holding every "
                       "pose of that view, packed side by side. They can come from another download, or be sheets "
                       "you repainted. Each file is checked when you choose it. The kit keeps a copy, so you can "
                       "move or delete the originals afterwards.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        g = QGridLayout()
        r = 0
        for key, label, what, _ in ds.SHEETS:
            g.addWidget(QLabel(f"<b>{label}</b><br><span style='color:gray'>{what}</span>"), r, 0)
            line = QLineEdit()
            line.setReadOnly(True)
            line.setPlaceholderText("required")
            g.addWidget(line, r, 1)
            b = QPushButton("Choose…")
            b.clicked.connect(lambda _, k=key, ln=line: self._choose(k, ln, True))
            g.addWidget(b, r, 2)
            mark = QLabel(NO)
            g.addWidget(mark, r, 3)
            self.marks[key] = mark
            r += 1
        for key, label, what in ds.EXTRAS:
            g.addWidget(QLabel(f"<b>{label}</b> <span style='color:gray'>(optional)</span><br>"
                               f"<span style='color:gray'>{what}</span>"), r, 0)
            line = QLineEdit()
            line.setReadOnly(True)
            line.setPlaceholderText("optional")
            g.addWidget(line, r, 1)
            b = QPushButton("Choose…")
            b.clicked.connect(lambda _, k=key, ln=line: self._choose(k, ln, False))
            g.addWidget(b, r, 2)
            mark = QLabel(OPT)
            g.addWidget(mark, r, 3)
            self.marks[key] = mark
            r += 1
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("Name (for your list):"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. My Etna repaint")
        nrow.addWidget(self.name, 1)
        lay.addLayout(nrow)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.status)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Add these sheets")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.layouts = {}

    def _choose(self, key, line, sheet):
        p, _ = QFileDialog.getOpenFileName(self, "Choose the file", os.path.dirname(line.text()) if line.text() else "",
                                           "Pictures (*.png)" if sheet else "Pictures (*.png *.jpg *.webp)")
        if not p:
            return
        line.setText(p)
        self.files[key] = p
        if not sheet:
            self.marks[key].setText(OK)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lay = ds.sheet_layout(p, key)
        finally:
            QApplication.restoreOverrideCursor()
        self.layouts[key] = lay
        lay = lay or (key not in ds.LAYOUT_REQUIRED)
        self.marks[key].setText(OK if lay else "⚠️")
        self.marks[key].setToolTip("Recognised" if lay else "Not laid out like a Disgaea RPG sheet")
        bad = [lbl for k, lbl, *_ in ds.SHEETS if k in self.layouts and not self.layouts[k] and k in ds.LAYOUT_REQUIRED]
        self.status.setText("" if not bad else
                            "<span style='color:#d9534f'>" + ", ".join(bad) + ": not packed like a Disgaea RPG "
                            "sheet. Check that you picked the right file for the row (battle vs idle, front vs "
                            "back). Sheets of another kind can be used through Outfits › New outfit › Convert a "
                            "sprite sheet.</span>")

    def _ok(self):
        missing = [lbl for k, lbl, *_ in ds.SHEETS if not self.files.get(k)]
        if missing:
            QMessageBox.warning(self, "My own sheet files", "Choose these sheets first: " + ", ".join(missing) + ".")
            return
        bad = [lbl for k, lbl, *_ in ds.SHEETS if not self.layouts.get(k) and k in ds.LAYOUT_REQUIRED]
        if bad:
            QMessageBox.warning(self, "My own sheet files",
                                ", ".join(bad) + " isn't laid out like a Disgaea RPG sheet, so it can't be converted.")
            return
        sheets = {k: self.files[k] for k, *_ in ds.SHEETS}
        extras = {k: self.files[k] for k, *_ in ds.EXTRAS if self.files.get(k)}
        try:
            self.uid, _ = ds.stage_custom(sheets, self.name.text().strip(), extras)
        except Exception as e:
            QMessageBox.critical(self, "My own sheet files", str(e))
            return
        self.accept()
