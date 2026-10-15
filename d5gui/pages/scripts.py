"""Event Scripts (advanced): view / edit the event bytecode of script.dat."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QPlainTextEdit, QApplication, QInputDialog, QMessageBox,
                             QCheckBox)

from d5lib import script, scriptpatch
from ..common import PageHeader, SearchBox, Worker, error_box, info_box

EDITED = QColor("#ff4f8b")


class ScriptsPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.vanilla = self.sf = None
        self.cur = None
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Event Scripts (advanced)",
                                 "The 19,053 event scripts that drive cutscenes, stage events, recruitment and menus. "
                                 "Commands are shown with what is known about them. Search by event id, or tick "
                                 "'operand values' to find every script that uses a number (character id, flag, item…). "
                                 "Edits are saved as a patch in your mod."))
        top = QHBoxLayout()
        self.search = SearchBox("Event id, or a number used inside scripts…")
        self.search.returnPressed.connect(self._search)
        top.addWidget(self.search, 1)
        self.by_value = QCheckBox("Search operand values")
        top.addWidget(self.by_value)
        b = QPushButton("Search")
        b.clicked.connect(self._search)
        top.addWidget(b)
        self.only_mod = QCheckBox("Edited only")
        self.only_mod.toggled.connect(self._search)
        top.addWidget(self.only_mod)
        lay.addLayout(top)
        split = QSplitter()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        split.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Pick an event")
        self.title.setObjectName("cardTitle")
        rl.addWidget(self.title)
        self.refs = QLabel("")
        self.refs.setObjectName("muted")
        self.refs.setWordWrap(True)
        rl.addWidget(self.refs)
        self.edit = QPlainTextEdit()
        self.edit.setFont(QFont("Consolas", 9))
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        rl.addWidget(self.edit, 1)
        row = QHBoxLayout()
        for text, fn in [("Apply edit", self.apply), ("💾 Save", self.save),
                         ("Revert this event", self.revert), ("New event…", self.new_event),
                         ("Discard unsaved", self.load)]:
            b = QPushButton(text)
            if text.startswith("💾"):
                b.setObjectName("primary")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        row.addWidget(self.status)
        rl.addLayout(row)
        split.addWidget(right)
        split.setSizes([300, 1100])
        lay.addWidget(split, 1)
        self._loaded = False
        ws.active_mod_changed.connect(lambda _: self._loaded and self.load())

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.load()

    def load(self):
        """parse script.dat in the background (~5 s for 1.6 million commands): the kit stays usable meanwhile"""
        if getattr(self, "_worker", None) is not None:
            self._reload = True
            return
        self._reload = False
        self.list.clear()
        self.status.setText("Loading the game's 19,053 event scripts…")
        self._worker = Worker(self._parse, self.ws.fs, self.ws.active_mod)
        self._worker.done.connect(self._loaded_scripts)
        self._worker.failed.connect(self._load_failed)
        self._worker.start()

    @staticmethod
    def _parse(fs, mod):
        from d5lib import skills
        base = skills.vanilla_scripts(fs, background=True)      # parsed once for the whole kit (Skills uses it too)
        sf = script.ScriptFile()
        sf.events = list(base.sf.events)     # a list of our own: edits replace entries, never change an Event
        vanilla = script.ScriptFile()
        vanilla.events = list(base.sf.events)   # the same Event objects: an unedited event *is* its vanilla one
        if mod:
            p = mod.load_patch("script", "script.json")
            if p:
                scriptpatch.apply(sf, p)
        refs = sf.references()
        callers = {}
        for eid, rs in refs.items():
            for r in rs:
                callers.setdefault(r, []).append(eid)
        van = {}
        for e in vanilla.events:
            van.setdefault(e.id, e)
        return vanilla, sf, van, refs, callers

    def _loaded_scripts(self, res):
        self._worker = None
        if self._reload:
            return self.load()
        self.vanilla, self.sf, self._van, self._refs, self._callers = res
        self.status.setText("")
        self._search()

    def _load_failed(self, msg):
        self._worker = None
        self.status.setText("Could not load the scripts: " + msg.splitlines()[0])

    def _edited(self, e):
        v = self._van.get(e.id)
        return v is None or (v is not e and v.encode() != e.encode())

    def _search(self):
        if not self.sf:
            return
        q = self.search.text().strip()
        val = int(q) if q.lstrip("-").isdigit() else None
        self.list.clear()
        n = 0
        for i, e in enumerate(self.sf.events):
            if self.only_mod.isChecked() and not self._edited(e):
                continue
            if q:
                if self.by_value.isChecked() and val is not None:
                    if not any(a == val for ins in e.code for a in (ins.args or []) if isinstance(a, int)):
                        continue
                elif q not in str(e.id):
                    continue
            it = QListWidgetItem(f"event {e.id}  ({len(e.code)} cmds)")
            it.setData(Qt.ItemDataRole.UserRole, i)
            if self.only_mod.isChecked() or (q and self._edited(e)):
                it.setForeground(QBrush(EDITED))
            self.list.addItem(it)
            n += 1
            if n >= 5000:
                break
        self.status.setText(f"{n} event(s)" + (" (showing first 5000)" if n >= 5000 else ""))

    def _pick(self, it, prev=None):
        if not it:
            return
        self.cur = it.data(Qt.ItemDataRole.UserRole)
        e = self.sf.events[self.cur]
        self.title.setText(f"Event {e.id}" + ("   ✏ edited" if self._edited(e) else ""))
        calls = self._refs.get(e.id, [])
        callers = self._callers.get(e.id, [])
        self.refs.setText(f"Starts events: {', '.join(map(str, calls[:20])) or '—'}      "
                          f"Started by: {', '.join(map(str, callers[:20])) or '— (game code / tables)'}")
        self.edit.setPlainText(scriptpatch.event_text(e))

    def apply(self):
        if self.sf is None:            # still loading
            return
        if self.cur is None:
            return
        try:
            ev = scriptpatch.parse_event_text(self.edit.toPlainText())
            ev.encode()
        except Exception as e:
            error_box(self, "Script error", e)
            return
        self.sf.events[self.cur] = ev
        self.status.setText("● unsaved changes")
        if self.list.currentItem():
            self.list.currentItem().setForeground(QBrush(EDITED))

    def save(self):
        if self.sf is None:            # still loading
            return
        mod = self.ws.require_mod(self)
        if not mod:
            return
        try:
            patch = scriptpatch.diff(self.vanilla, self.sf)
            mod.save_patch("script", "script.json", patch or None)
            self.status.setText("")
            self.ws.file_changed.emit(scriptpatch.SCRIPT)
            self.ws.log(f"Saved {len(patch.get('events', {}))} script event(s) to mod '{mod.name}'")
        except Exception as e:
            error_box(self, "Save failed", e)

    def revert(self):
        if self.sf is None:            # still loading
            return
        if self.cur is None:
            return
        e = self.sf.events[self.cur]
        v = self.vanilla.get(e.id)
        if v is not None:
            self.sf.events[self.cur] = scriptpatch.parse_event_text(scriptpatch.event_text(v, annotate=False))
            self.status.setText("● unsaved changes")
            self._pick(self.list.currentItem())

    def new_event(self):
        if self.sf is None:            # still loading
            return
        top = max(e.id for e in self.sf.events)
        eid, ok = QInputDialog.getInt(self, "New event", "New event id (unused):", top + 1, 1, 2 ** 24 - 1)
        if not ok:
            return
        if self.sf.get(eid):
            QMessageBox.warning(self, "New event", f"Event {eid} already exists.")
            return
        self.sf.events.append(scriptpatch.parse_event_text(f"event {eid}\n    wait_children\n"))
        self.status.setText("● unsaved changes")
        self.by_value.setChecked(False)
        self.search.setText(str(eid))
        self._search()
        if self.list.count():
            self.list.setCurrentRow(self.list.count() - 1)
        info_box(self, "New event", f"Event {eid} created. Write its commands, press Apply, then Save.\n"
                                    f"Start it from another event with:   call_event {eid}")
