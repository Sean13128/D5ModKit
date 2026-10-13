"""Voices in the kit (d5lib.voices): the Voice box of the Characters page (which voice a character or class speaks
with, ▶ to hear it) and the custom voice editor (a voice's lines, any of them replaced by your own recordings)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QDialog,
                             QDialogButtonBox, QFormLayout, QLineEdit, QTreeWidget, QTreeWidgetItem, QSpinBox,
                             QCheckBox, QGridLayout, QFileDialog, QMessageBox, QRadioButton, QApplication,
                             QAbstractItemView)

from d5lib import voices
from .common import error_box, info_box
from .pages.stages import SearchCombo, choice_model

CHAR = "char.dat"


class VoiceService:
    """what the voice widgets share: the game's voices, the mods' custom voices, decoded lines, the speaker"""

    def __init__(self, ws, svc):
        self.ws, self.svc = ws, svc
        self._catalog = None
        self._banks = {}
        self.mixer = None
        self.choices = []

    def mods(self):
        ms = list(self.ws.mods.enabled_mods())
        a = self.ws.active_mod
        if a and all(m.id != a.id for m in ms):
            ms.append(a)
        return ms

    def catalog(self):
        if self._catalog is None:
            self._catalog = voices.Catalog(self.ws.fs.read, self.svc.vanilla(CHAR).rows)
        return self._catalog

    def custom(self):
        """{voice id: (voice dict, mod)} of the custom voices of the mods (later mods win)"""
        out = {}
        for m in self.mods():
            for vid, v in voices.load(m)["voices"].items():
                out[int(vid)] = (v, m)
        return out

    def bank(self, lang="EN"):
        if lang not in self._banks:
            self._banks[lang] = voices.VoiceBank(self.ws.fs, self.mods(), lang)
        return self._banks[lang]

    def changed(self):
        """the mods' custom voices changed"""
        self._banks.clear()
        self.refresh_choices()

    def refresh_choices(self):
        cat = self.catalog()
        out = []
        for vid in cat.ids:
            names = cat.owners.get(vid) or ["(no character)"]
            n = len(cat.personalities(vid))
            who = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
            out.append((vid, f"{who}" + (f"  · {n} personalities" if n > 1 else "")))
        for vid, (v, m) in sorted(self.custom().items()):
            out.append((vid, f"🎤 {v.get('name') or 'custom voice'}  · custom voice ({m.name})"))
        self.choices = out
        return out

    def speaker(self):
        if self.mixer is None:
            from .skilledit.audio import Mixer
            self.mixer = Mixer()
        return self.mixer

    def play(self, pcm, volume=1.0):
        if pcm:
            m = self.speaker()
            m.stop()
            m.play(pcm[0], pcm[1], volume)

    def play_line(self, line_id, lang="EN", volume=1.0):
        self.play(self.bank(lang).get(line_id), volume)

    def play_file(self, path, volume=1.0):
        try:
            self.play(self.bank().get_file(path), volume)
        except (OSError, ValueError) as e:
            self.ws.log(f"could not play {path}: {e}")


class VoiceBox(QGroupBox):
    """the Characters page's Voice group: pick the voice, hear it, make / edit a custom voice"""

    def __init__(self, page):
        super().__init__("Voice")
        self.page = page
        self.vs = VoiceService(page.ws, page.svc)
        self._loading = False
        self._turn = 0
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.combo = SearchCombo(self.vs.refresh_choices())
        self.combo.setToolTip("Whose voice lines this character speaks in battle. Pick any character or class.")
        self.combo.activated.connect(lambda _: self._picked())
        self.combo.lineEdit().editingFinished.connect(self._picked)
        row.addWidget(self.combo, 1)
        self.pers = QComboBox()
        self.pers.addItems(["Personality 1", "Personality 2", "Personality 3"])
        self.pers.setToolTip("Generic classes: the personality chosen when the unit is created (each has its own "
                             "lines). Only for listening here.")
        row.addWidget(self.pers)
        self.hear = QPushButton("▶ Hear")
        self.hear.setToolTip("Play one of this voice's battle lines (again for the next one)")
        self.hear.clicked.connect(self._hear)
        row.addWidget(self.hear)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.custom_btn = QPushButton("🎤 Custom voice…")
        self.custom_btn.setToolTip("Your own voice lines: start from any voice and replace its lines with your "
                                   "recordings (WAV; MP3 / OGG / FLAC with ffmpeg), add or remove lines.")
        self.custom_btn.clicked.connect(self._custom)
        row.addWidget(self.custom_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    # ------------------------------------------------------------------ page side
    def rows(self):
        """the char.dat rows that share the voice: every tier of a class, else the character's row"""
        r = self.page._row()
        cid = r["id"]
        if cid < 1000:
            return [r]
        fam = cid // 10 * 10
        return [x for x in self.page.table().rows if fam <= x["id"] <= fam + 5] or [r]

    def is_class(self):
        return self.page._row()["id"] >= 1000

    def load(self, row):
        self._loading = True
        try:
            vid = int(row["voice_id"])
            if vid not in {k for k, _ in self.vs.choices}:
                self.combo.setModel(choice_model(self.vs.refresh_choices()))
            self.combo.set_value(vid)
            self.pers.setVisible(row["id"] >= 1000)
            self._note(vid)
        finally:
            self._loading = False

    def _note(self, vid):
        cat = self.vs.catalog()
        cust = self.vs.custom().get(vid)
        if cust:
            v, m = cust
            n = sum(1 for ln in v.get("lines", []) if ln.get("file"))
            self.note.setText(f"Custom voice {vid} ({m.name}): {len(v.get('lines', []))} lines, {n} of them your "
                              f"recordings. Press 🎤 Custom voice… to edit it.")
        elif vid and not cat.lines_of(vid) and vid not in cat.ids:
            self.note.setText(f"Voice {vid} has no lines: this character is silent.")
        elif self.is_class() and len(cat.personalities(vid)) < voices.PERSONALITIES:
            self.note.setText("This voice has one personality only: units of personality 2 and 3 are silent. "
                              "Pick it again to make a copy for all three.")
        else:
            self.note.setText("")

    def _picked(self):
        if self._loading or self.page.row_index is None:
            return
        vid = self.combo.value()
        r = self.page._row()
        if vid == int(r["voice_id"]):
            return
        cat = self.vs.catalog()
        if vid not in cat.ids and vid not in self.vs.custom():
            QMessageBox.warning(self, "Voice", f"There is no voice {vid}.")
            self.load(r)
            return
        if self.is_class() and vid < voices.CUSTOM_FIRST and len(cat.personalities(vid)) < voices.PERSONALITIES:
            mod = self.page.ws.require_mod(self)
            if not mod:
                self.load(r)
                return
            ans = QMessageBox.question(
                self, "Voice for a class",
                f"{(cat.owners.get(vid) or ['This voice'])[0]}'s voice has one personality, a class has three "
                "(chosen when a unit is created).\n\nMake a custom voice that copies it for all three personalities? "
                "(Recommended: otherwise units of personality 2 and 3 say nothing.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                self.load(r)
                return
            if ans == QMessageBox.StandardButton.Yes:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    vid = voices.voice_for(cat, mod, self.vs.mods(), vid, True,
                                           f"{(cat.owners.get(vid) or ['voice'])[0]} for {r['name_EN']}")
                finally:
                    QApplication.restoreOverrideCursor()
                self.vs.changed()
        self.assign(vid)

    def assign(self, vid):
        for x in self.rows():
            x.set("voice_id", int(vid))
        self.page.svc.mark_dirty(CHAR)
        self.page.status.setText("● unsaved changes")
        self.combo.setModel(choice_model(self.vs.refresh_choices()))
        self.load(self.page._row())

    def _hear(self):
        vid = self.combo.value()
        p = self.pers.currentIndex() if self.is_class() else 0
        bank = self.vs.bank()
        ls = []
        for pp in (p, 0):
            ls = bank.lines_in(voices.set_of(0, vid, pp))
            if ls:
                break
        if not ls:
            self.note.setText(f"Voice {vid} has no battle lines.")
            return
        self._turn += 1
        self.vs.play_line(ls[self._turn % len(ls)])

    # ------------------------------------------------------------------ custom voice
    def _custom(self):
        if self.page.row_index is None:
            return
        r = self.page._row()
        vid = int(r["voice_id"])
        cust = self.vs.custom().get(vid)
        if cust:
            v, m = cust
            a = self.page.ws.active_mod
            if not a or a.id != m.id:
                info_box(self, "Custom voice", f"This custom voice belongs to the mod '{m.name}'. Make that mod the "
                         "active one (top of the window) to edit it.")
                return
            self.edit(vid, m)
            return
        mod = self.page.ws.require_mod(self)
        if not mod:
            return
        dlg = NewVoiceDialog(self, r, vid)
        if not dlg.exec():
            return
        src, pers, name = dlg.values()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            new = voices.new_voice(self.vs.catalog(), mod, self.vs.mods(), name, src, pers)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            error_box(self, "Custom voice", e)
            return
        QApplication.restoreOverrideCursor()
        self.vs.changed()
        self.assign(new)
        self.page.ws.log(f"custom voice {new} '{name}' made from voice {src} for {r['name_EN']}")
        self.edit(new, mod)

    def edit(self, vid, mod):
        dlg = VoiceEditor(self, self.vs, mod, vid)
        dlg.exec()
        self.vs.changed()
        self.combo.setModel(choice_model(self.vs.choices))
        self.load(self.page._row())


class NewVoiceDialog(QDialog):
    def __init__(self, box, row, current):
        super().__init__(box)
        self.setWindowTitle("New custom voice")
        self.box = box
        f = QFormLayout(self)
        f.addRow(QLabel("A custom voice starts as a copy of a voice's lines (battle and the game's other "
                        "situations). Then replace any of them with your own recordings, add or remove lines."))
        self.src = SearchCombo(box.vs.choices or box.vs.refresh_choices())
        self.src.set_value(current if current in box.vs.catalog().ids else 10)
        f.addRow("Start from the voice of", self.src)
        self.pers = QComboBox()
        self.pers.addItems(["Personality 1", "Personality 2", "Personality 3"])
        f.addRow("(classes) personality", self.pers)
        self.name = QLineEdit(f"{row['name_EN']} voice")
        f.addRow("Name", self.name)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        src = self.src.value()
        ps = self.box.vs.catalog().personalities(src) or [0]
        p = self.pers.currentIndex()
        return src, p if p in ps else ps[0], self.name.text().strip() or "Custom voice"


class SituationsDialog(QDialog):
    def __init__(self, parent, kind, cats):
        super().__init__(parent)
        self.setWindowTitle("Situations")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("When the game may pick this line. " + voices.KIND_HELP.get(kind, "")))
        g = QGridLayout()
        self.boxes = []
        usual = {0: range(0, 22), 1: range(22, 29), 2: range(29, 31), 3: [0, 1, 2, 20, 21, 31, 32, 33]}[kind]
        for c in range(voices.SITUATIONS):
            b = QCheckBox(str(c))
            b.setChecked(c in cats)
            if c not in usual:
                b.setToolTip("not used by this kind of line in the game's voices")
                b.setStyleSheet("color: gray")
            self.boxes.append(b)
            g.addWidget(b, c // 9, c % 9)
        lay.addLayout(g)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        return [c for c, b in enumerate(self.boxes) if b.isChecked()]


class VoiceEditor(QDialog):
    """a custom voice's lines: ▶ listen, replace with a recording, back to the original, situations, volume, add
    recordings, remove"""

    def __init__(self, parent, vs, mod, vid):
        super().__init__(parent)
        self.vs, self.mod, self.vid = vs, mod, int(vid)
        self.data = voices.load(mod)
        self.voice = self.data["voices"][str(self.vid)]
        self.setWindowTitle(f"Custom voice {self.vid}")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(self.voice.get("name", ""))
        f.addRow("Name", self.name)
        t = self.voice.get("template") or [0, 0]
        f.addRow("Made from", QLabel(f"{vs.catalog().label(t[0])}, personality {t[1] + 1}"))
        lang = QHBoxLayout()
        self.en = QRadioButton("English")
        self.jp = QRadioButton("Japanese")
        self.en.setChecked(True)
        lang.addWidget(self.en)
        lang.addWidget(self.jp)
        lang.addStretch(1)
        f.addRow("Listen to the copied lines in", lang)
        lay.addLayout(f)
        help_ = QLabel("Every line plays in the situations ticked for it; the game picks one of the lines of a "
                       "situation at random. ▶ (or double-click) to listen. Recordings: WAV (any rate, mono or "
                       "stereo); MP3 / OGG / FLAC / M4A need ffmpeg. They are converted to the game's format, "
                       "silence trimmed and the volume evened out.")
        help_.setWordWrap(True)
        help_.setObjectName("muted")
        lay.addWidget(help_)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Line", "Situations", "Sound", "Volume"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 170)
        self.tree.setColumnWidth(2, 330)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.play())
        self.tree.currentItemChanged.connect(lambda *_: self._sync())
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, fn, tip in [
                ("▶ Play", self.play, "Listen to the selected line"),
                ("🎤 Replace…", self.replace, "Replace the selected line with a recording"),
                ("↺ Original", self.original, "Back to the copied line"),
                ("Situations…", self.situations, "When the game may pick the selected lines"),
                ("➕ Add recordings…", self.add, "New lines from recordings, in the situations of the selected line "
                                               "(or choose them)"),
                ("✖ Remove", self.remove, "Remove the selected lines")]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addWidget(QLabel("Volume"))
        self.vol = QSpinBox()
        self.vol.setRange(1, 200)
        self.vol.setSuffix(" %")
        self.vol.setToolTip("How loud the game plays the selected lines (the game's own lines use 50-70 %)")
        self.vol.valueChanged.connect(self._volume)
        row.addWidget(self.vol)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._syncing = False
        self.fill()

    # ------------------------------------------------------------------ list
    def lang(self):
        return "JP" if self.jp.isChecked() else "EN"

    def fill(self, keep=None):
        self.tree.clear()
        lines = self.voice.setdefault("lines", [])
        groups = {}
        for k in range(voices.KINDS):
            it = QTreeWidgetItem([voices.KIND_NAMES[k], "", "", ""])
            it.setToolTip(0, voices.KIND_HELP[k])
            it.setData(0, Qt.ItemDataRole.UserRole, ("kind", k))
            groups[k] = it
            self.tree.addTopLevelItem(it)
        count = {k: 0 for k in range(voices.KINDS)}
        cur = None
        for i, ln in enumerate(lines):
            k = int(ln.get("kind", 0))
            if k not in groups:
                continue
            count[k] += 1
            if ln.get("file"):
                snd = f"🎤 {ln['file']}"
            elif ln.get("src"):
                snd = f"copied line {ln['src']}"
            else:
                snd = "(no sound)"
            it = QTreeWidgetItem([f"{count[k]}", ", ".join(map(str, ln.get("cats", []))) or "(none: never plays)",
                                  snd, f"{ln.get('volume', voices.DEFAULT_VOLUME)} %"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("line", i))
            groups[k].addChild(it)
            if keep is not None and i == keep:
                cur = it
        for k, it in groups.items():
            it.setText(0, f"{voices.KIND_NAMES[k]}  ({count[k]} lines)")
            it.setExpanded(k == 0)
        if cur is not None:
            self.tree.setCurrentItem(cur)
            cur.parent().setExpanded(True)

    def selected(self):
        out = []
        for it in self.tree.selectedItems():
            d = it.data(0, Qt.ItemDataRole.UserRole)
            if d and d[0] == "line":
                out.append(d[1])
        return sorted(set(out))

    def current_kind(self):
        it = self.tree.currentItem()
        if it is None:
            return 0
        d = it.data(0, Qt.ItemDataRole.UserRole)
        if d[0] == "kind":
            return d[1]
        return int(self.voice["lines"][d[1]].get("kind", 0))

    def _sync(self):
        sel = self.selected()
        if sel:
            self._syncing = True
            self.vol.setValue(int(self.voice["lines"][sel[0]].get("volume", voices.DEFAULT_VOLUME)))
            self._syncing = False

    # ------------------------------------------------------------------ actions
    def play(self):
        sel = self.selected()
        if not sel:
            return
        ln = self.voice["lines"][sel[0]]
        vol = ln.get("volume", voices.DEFAULT_VOLUME) / 70.0
        if ln.get("file"):
            self.vs.play_file(os.path.join(voices.folder(self.mod), ln["file"]), vol)
        elif ln.get("src"):
            self.vs.play_line(int(ln["src"]), self.lang(), vol)

    def _import(self, path):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return voices.import_line(self.mod, self.vid, path)
        finally:
            QApplication.restoreOverrideCursor()

    def _files(self, many):
        filt = "Audio (*.wav *.mp3 *.ogg *.flac *.m4a *.vag);;All files (*)"
        if many:
            return QFileDialog.getOpenFileNames(self, "Recordings", "", filt)[0]
        p = QFileDialog.getOpenFileName(self, "Recording", "", filt)[0]
        return [p] if p else []

    def replace(self):
        sel = self.selected()
        if len(sel) != 1:
            info_box(self, "Replace", "Select one line.")
            return
        files = self._files(False)
        if not files:
            return
        try:
            fn = self._import(files[0])
        except Exception as e:
            error_box(self, "Could not read the recording", e)
            return
        ln = self.voice["lines"][sel[0]]
        if ln.get("src"):
            ln["orig"] = ln.pop("src")
        ln["file"] = fn
        if ln.get("volume", 0) < 70:
            ln["volume"] = 80
        self.fill(sel[0])
        self.play()

    def original(self):
        for i in self.selected():
            ln = self.voice["lines"][i]
            if ln.get("orig"):
                ln["src"] = ln.pop("orig")
                ln.pop("file", None)
        self.fill()

    def situations(self):
        sel = self.selected()
        if not sel:
            return
        first = self.voice["lines"][sel[0]]
        dlg = SituationsDialog(self, int(first.get("kind", 0)), first.get("cats", []))
        if dlg.exec():
            for i in sel:
                self.voice["lines"][i]["cats"] = dlg.values()
            self.fill(sel[0])

    def add(self):
        sel = self.selected()
        kind = self.current_kind()
        if sel:
            cats = list(self.voice["lines"][sel[0]].get("cats", []))
        else:
            dlg = SituationsDialog(self, kind, [])
            if not dlg.exec():
                return
            cats = dlg.values()
        files = self._files(True)
        last = None
        for p in files:
            try:
                fn = self._import(p)
            except Exception as e:
                error_box(self, f"Could not read {os.path.basename(p)}", e)
                continue
            self.voice["lines"].append({"kind": kind, "cats": cats, "volume": 80, "file": fn})
            last = len(self.voice["lines"]) - 1
        if last is not None:
            self.fill(last)

    def remove(self):
        sel = self.selected()
        if not sel:
            return
        for i in reversed(sel):
            del self.voice["lines"][i]
        self.fill()

    def _volume(self, v):
        if self._syncing:
            return
        sel = self.selected()
        for i in sel:
            self.voice["lines"][i]["volume"] = int(v)
        for it in self.tree.selectedItems():
            d = it.data(0, Qt.ItemDataRole.UserRole)
            if d and d[0] == "line":
                it.setText(3, f"{int(v)} %")

    def save(self):
        self.voice["name"] = self.name.text().strip() or self.voice.get("name") or "Custom voice"
        voices.save(self.mod, self.data)
        self.vs.ws.log(f"custom voice {self.vid} '{self.voice['name']}' saved in '{self.mod.name}' "
                       f"({len(self.voice['lines'])} lines). Install to hear it in game.")
        self.accept()

    def reject(self):
        # recordings imported but not saved: their files go with the next save; nothing else changed
        super().reject()
