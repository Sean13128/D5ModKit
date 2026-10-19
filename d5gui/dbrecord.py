"""The Database page's record panel: one row of a table as a form (every field with what it means, references as
pickers, texts with their byte limits), what refers to it (Used by), its bytes (Raw); and the Go to dialog (any
record of any table, Ctrl+P)."""
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QObject
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QVBoxLayout,
                             QWidget, QApplication, QCompleter)

from d5lib import database

ROLE = Qt.ItemDataRole.UserRole
CHOICES_MAX = 20000


def _fmt(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex(" ")
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


class _Focus(QObject):
    """an editor got the focus: show its field's notes"""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.FocusIn:
            self.fn(obj)
        return False


class RecordPanel(QWidget):
    navigate = pyqtSignal(str, int)          # table, row index (Used by: a row pointing here)
    edited = pyqtSignal(int)                 # this row changed (the grid repaints it)
    before_edit = pyqtSignal(str, int, object)   # table, row index, a copy of the row before the change (undo)

    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self.svc = svc
        self.model = None
        self.r = None
        self._building = False
        self._focus = _Focus(self._show_notes)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel("Pick a row")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.b_revert = QPushButton("↺ Revert record")
        self.b_revert.setToolTip("This row back to the game's values")
        self.b_revert.clicked.connect(self._revert)
        head.addWidget(self.b_revert)
        lay.addLayout(head)
        self.tabs = QTabWidget()
        self.form_area = QScrollArea()
        self.form_area.setWidgetResizable(True)
        self.form_box = QWidget()
        self.form = QFormLayout(self.form_box)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form_area.setWidget(self.form_box)
        rec = QWidget()
        rl = QVBoxLayout(rec)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.form_area, 1)
        self.notes = QLabel("Click a field to see what it is.")
        self.notes.setWordWrap(True)
        self.notes.setObjectName("muted")
        self.notes.setMinimumHeight(48)
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.notes)
        self.tabs.addTab(rec, "Record")
        self.users = QListWidget()
        self.users.itemDoubleClicked.connect(self._goto_user)
        self.tabs.addTab(self.users, "Used by")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.raw, "Raw")
        self.json = QPlainTextEdit()
        self.json.setReadOnly(True)
        self.json.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.json, "JSON")
        self.tabs.currentChanged.connect(self._tab)
        lay.addWidget(self.tabs, 1)
        self._ref_index = {}                 # table -> [(member, field)] that refer to it

    # ---------------------------------------------------------------- a row
    def show_row(self, model, r):
        self.model, self.r = model, r
        self._build()
        self._tab(self.tabs.currentIndex())

    def refresh(self):
        if self.model is not None and self.r is not None:
            self.show_row(self.model, self.r)

    def _row(self):
        if self.model is None or self.r is None or not 0 <= self.r < len(self.model.table.rows):
            return None
        return self.model.table.rows[self.r]

    def _vanilla(self):
        v = self.model.vanilla
        return v.rows[self.r] if self.r < len(v.rows) else None

    def _build(self):
        self._building = True
        while self.form.rowCount():
            self.form.removeRow(0)
        row = self._row()
        if row is None:
            self.title.setText("Pick a row")
            self.b_revert.setEnabled(False)
            self._building = False
            return
        sch = self.model.table.schema
        van = self._vanilla()
        disp = sch.display
        name = row.get(disp) if disp and disp != sch.key else ""
        key = row.get(sch.key) if sch.key else self.r
        self.title.setText(f"{self.model.member} · row {self.r}" + (f" · {sch.key} {key}" if sch.key else "") +
                           (f" · {name}" if name else "") + ("  (new row)" if van is None else ""))
        self.b_revert.setEnabled(van is not None and (bytes(van.raw) != bytes(row.raw) or van.strs != row.strs))
        for f in self.model.fields:
            v = row._get(f)
            lab = QLabel(f.name)
            changed = van is not None and van._get(f) != v
            if changed:
                lab.setStyleSheet("color:#ff8ad8;")
                lab.setToolTip(f"Original value: {_fmt(van._get(f))}")
            elif f.name.startswith(("unk", "pad")):
                lab.setStyleSheet("color:#787390;")
            ed = self._editor(f, v)
            ed.setProperty("d5field", f.name)
            ed.installEventFilter(self._focus)
            for child in ed.findChildren(QLineEdit):
                child.setProperty("d5field", f.name)
                child.installEventFilter(self._focus)
            self.form.addRow(lab, ed)
        self._building = False

    def _editor(self, f, v):
        if f.type == "bytes":
            e = QLineEdit(_fmt(v))
            e.editingFinished.connect(lambda f=f, e=e: self._set(f, e.text()))
            return e
        choices = None
        if f.ref:
            try:
                choices = self.svc.ref_choices(f.ref)
            except Exception:
                choices = None
        if f.enum:
            choices = [(int(k) if str(k).lstrip("-").isdigit() else k, lab) for k, lab in f.enum.items()]
        if choices and len(choices) < CHOICES_MAX and f.type not in ("str", "strptr"):
            cb = QComboBox()
            cb.setEditable(True)
            cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            known = False
            for kv, lab in choices:
                cb.addItem(f"{kv} · {lab}" if lab else str(kv), kv)
            i = cb.findData(v)
            if i >= 0:
                cb.setCurrentIndex(i)
                known = True
            if not known:
                cb.setEditText(str(v))
            cb.completer().setFilterMode(Qt.MatchFlag.MatchContains)
            cb.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            from .common import type_to_search
            type_to_search(cb)
            cb.activated.connect(lambda _, f=f, cb=cb: self._set_choice(f, cb))
            cb.lineEdit().editingFinished.connect(lambda f=f, cb=cb: self._set_choice(f, cb))
            return cb
        if f.type in ("str", "strptr"):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            e = QLineEdit(str(v))
            n = QLabel()
            n.setObjectName("muted")
            limit = f.size - 1 if f.type == "str" and f.size else None

            def count(text, n=n, limit=limit):
                b = len(text.encode("utf-8"))
                n.setText(f"{b} / {limit} bytes" if limit else f"{b} bytes")
                n.setStyleSheet("color:#ff6b6b;" if limit and b > limit else "")
            count(e.text())
            e.textChanged.connect(count)
            e.editingFinished.connect(lambda f=f, e=e: self._set(f, e.text()))
            h.addWidget(e, 1)
            h.addWidget(n)
            return w
        e = QLineEdit(_fmt(v))
        e.editingFinished.connect(lambda f=f, e=e: self._set(f, e.text()))
        return e

    def _set_choice(self, f, cb):
        if self._building:
            return
        txt = cb.currentText().strip()
        i = cb.findText(txt)
        if i >= 0:
            self._set(f, cb.itemData(i))
        elif txt.split(" ")[0].lstrip("-").isdigit():
            self._set(f, txt.split(" ")[0])

    def _set(self, f, value):
        if self._building:
            return
        row = self._row()
        if row is None:
            return
        try:
            if f.type in ("str", "strptr"):
                new = str(value)
            elif f.type == "bytes":
                new = bytes.fromhex(str(value).replace(" ", ""))
            elif f.type in ("f32", "f64"):
                new = float(value)
            else:
                new = int(str(value).strip().split(" ")[0], 0) if not isinstance(value, int) else value
            if row._get(f) == new:
                return
            before = row.copy()
            row.set(f.name, new)
            self.before_edit.emit(self.model.member, self.r, before)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid value", f"{f.name}: {e}")
            self._build()
            return
        self.svc.mark_dirty(self.model.member)
        self.edited.emit(self.r)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._build)             # (labels: changed / not)

    def _revert(self):
        van = self._vanilla()
        if van is None:
            return
        self.before_edit.emit(self.model.member, self.r, self._row().copy())
        self.model.table.rows[self.r] = van.copy()
        self.svc.mark_dirty(self.model.member)
        self.edited.emit(self.r)
        self._build()

    def _show_notes(self, obj):
        name = obj.property("d5field")
        if not name or self.model is None:
            return
        f = next((x for x in self.model.table.schema.fields if x.name == name), None)
        if f is None:
            return
        bits = [f"<b>{f.name}</b> <span style='color:#8a90b8'>({f.type}"
                f"{', ' + str(f.size) + ' bytes' if f.type in ('str', 'bytes') else ''}, offset 0x{f.offset:X}, "
                f"{f.confidence})</span>"]
        if f.desc:
            bits.append(f.desc)
        if f.ref:
            bits.append(f"→ a row of <i>{f.ref}</i>")
        row = self._row()
        if row is not None and f.ref:
            try:
                lab = self.svc.ref_label(f.ref, row._get(f))
                if lab:
                    bits.append(f"= {lab}")
            except Exception:
                pass
        self.notes.setText("<br>".join(bits))

    # ---------------------------------------------------------------- used by / raw
    def _tab(self, i):
        if i == 3:
            row = self._row()
            if row is None:
                self.json.setPlainText("")
                return
            import json as _json
            d = {}
            for f in self.model.table.schema.fields:
                v = row._get(f)
                d[f.name] = v.hex(" ") if isinstance(v, (bytes, bytearray)) else v
            self.json.setPlainText(_json.dumps(d, indent=1, ensure_ascii=False))
        if i == 1:
            self._fill_users()
        elif i == 2:
            row = self._row()
            if row is None:
                self.raw.setPlainText("")
                return
            b = bytes(row.raw)
            lines = [f"{o:04X}  " + " ".join(f"{x:02x}" for x in b[o:o + 16]).ljust(48) + "  " +
                     "".join(chr(x) if 32 <= x < 127 else "." for x in b[o:o + 16]) for o in range(0, len(b), 16)]
            if row.strs:
                lines.append("")
                lines += [f"{k}: {v}" for k, v in row.strs.items()]
            self.raw.setPlainText("\n".join(lines))

    def _refs_to(self, member):
        """[(table, field, target field or None)] whose references point at `member`"""
        if member in self._ref_index:
            return self._ref_index[member]
        out = []
        for m in self.svc.members():
            if not self.svc.has_schema(m):
                continue
            try:
                sch = database.get_schema(m)
            except Exception:
                continue
            for f in sch.fields:
                if not f.ref:
                    continue
                t, tf, by_index = database.parse_ref(f.ref)
                if t and self.svc.find_table(t) == member:
                    out.append((m, f.name, tf, by_index))
        self._ref_index[member] = out
        return out

    def _fill_users(self):
        self.users.clear()
        row = self._row()
        if row is None:
            return
        sch = self.model.table.schema
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = 0
            for m, fname, tf, by_index in self._refs_to(self.model.member):
                want = self.r if by_index else (row.get(tf) if tf else (row.get(sch.key) if sch.key else None))
                if want in (None, 0, -1, ""):
                    continue
                try:
                    t = self.svc.table(m)
                except Exception:
                    continue
                d = t.schema.display
                for i, rr in enumerate(t.rows):
                    if rr.get(fname) == want:
                        lab = rr.get(d) if d else ""
                        it = QListWidgetItem(f"{m} · row {i}" + (f" · {lab}" if lab else "") + f"   ({fname})")
                        it.setData(ROLE, (m, i))
                        self.users.addItem(it)
                        n += 1
                        if n >= 2000:
                            break
            if not n:
                it = QListWidgetItem("Nothing in the tables points at this row." if self._refs_to(self.model.member)
                                     else "No table refers to this one (as far as the kit knows).")
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                self.users.addItem(it)
            self.tabs.setTabText(1, f"Used by ({n})" if n else "Used by")
        finally:
            QApplication.restoreOverrideCursor()

    def _goto_user(self, it):
        d = it.data(ROLE)
        if d:
            self.navigate.emit(*d)


class GotoDialog(QDialog):
    """any record of any table by name or id (Ctrl+P)"""
    _index = None

    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self.svc = svc
        self.setWindowTitle("Go to a record")
        self.resize(620, 520)
        lay = QVBoxLayout(self)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Name or id, e.g. Killia, 1001, Fire, Poison Beach… (Enter opens)")
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._accept_first)
        lay.addWidget(self.edit)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda it: self._done(it))
        lay.addWidget(self.list, 1)
        self.choice = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if GotoDialog._index is None or GotoDialog._index[0] is not svc:
                GotoDialog._index = (svc, self._build())
        finally:
            QApplication.restoreOverrideCursor()
        self._filter("")

    def _build(self):
        out = []
        for m in self.svc.members():
            if not self.svc.has_schema(m):
                continue
            try:
                t = self.svc.table(m)
            except Exception:
                continue
            k, d = t.schema.key, t.schema.display
            if not d or d == k:
                continue
            for i, r in enumerate(t.rows):
                try:
                    name = r.get(d)
                except Exception:
                    continue
                if not name:
                    continue
                kv = r.get(k) if k else i
                out.append((f"{name}  ·  {k or 'row'} {kv}  ·  {m}", m, i, f"{name} {kv} {m}".lower()))
        return out

    def _filter(self, t):
        t = t.strip().lower()
        self.list.clear()
        n = 0
        for lab, m, i, low in GotoDialog._index[1]:
            if t and not all(w in low for w in t.split()):
                continue
            it = QListWidgetItem(lab)
            it.setData(ROLE, (m, i))
            self.list.addItem(it)
            n += 1
            if n >= 400:
                break
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept_first(self):
        it = self.list.currentItem()
        if it:
            self._done(it)

    def _done(self, it):
        self.choice = it.data(ROLE)
        self.accept()
