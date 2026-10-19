"""Spreadsheet-style editor for every database table, with a record panel (the selected row as a form: what each
field means, references as pickers, texts with their byte limits, what points at the row, its bytes), Go to any
record (Ctrl+P), back / forward, a check of the table (dbcheck: what would crash the game) and Skill.dat presets."""
import os

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QTableView, QPushButton, QLabel, QCheckBox, QComboBox, QStyledItemDelegate,
                             QMessageBox, QFileDialog, QHeaderView, QAbstractItemView, QLineEdit, QCompleter)

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QToolButton, QMenu, QDialog, QListWidget as _QList, QInputDialog

from d5lib import database, dbcheck
from ..common import PageHeader, SearchBox, error_box
from ..dbservice import get_service, describe_row, _esc
from ..dbrecord import RecordPanel, GotoDialog

MODIFIED = QColor(90, 45, 110)
ADDED = QColor(30, 80, 55)
UNK = QColor(120, 115, 140)

# friendly names for the most useful tables (member -> (category, title))
FRIENDLY = {
    "char.dat": ("Units", "Characters & Classes"),
    "charhelp.dat": ("Units", "Character descriptions"),
    "charPersonal.dat": ("Units", "Character personalities"),
    "JobRank.dat": ("Units", "Class ranks / tiers"),
    "HABIT.dat": ("Units", "Evilities"),
    "HabitAffinity.dat": ("Units", "Evility affinities"),
    "Anime_TableDataBase.dat": ("Units", "Sprite table"),
    "name.dat": ("Units", "Random generic names"),
    "magic.dat": ("Skills", "Skills & spells"),
    "Skill.dat": ("Skills", "Skill learnsets"),
    "OverlordSkill.dat": ("Skills", "Overload skills"),
    "comb.dat": ("Skills", "Combo table"),
    "item.dat": ("Items", "Items & equipment"),
    "ItemGetSkillDataBase.dat": ("Items", "Item skills"),
    "Curry.dat": ("Items", "Curry"),
    "itemexchange.dat": ("Items", "Item exchange"),
    "dungeon.dat": ("Stages", "Stages / maps"),
    "Enemy_Create_TableDataBase.dat": ("Stages", "Enemy creation"),
    "Enemy_Parameters_TableDataBase": ("Stages", "Enemy parameters"),
    "QuestEnemy.dat": ("Stages", "Quest enemies"),
    "BattleEvent.dat": ("Stages", "Battle events"),
    "Quest.dat": ("World", "Quests"),
    "senator.dat": ("World", "Dark Assembly senators"),
    "senator2.dat": ("World", "Dark Assembly bills"),
    "music.dat": ("World", "Music gallery"),
    "Trophy.dat": ("World", "Trophies"),
    "zukan.dat": ("World", "Encyclopedia"),
    "StringListDataBase.dat": ("Text", "String list (UI text)"),
    "TownEditMessageDataBase.dat": ("Text", "Town edit messages"),
}


def _fmt(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex(" ")
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


class TableModel(QAbstractTableModel):
    def __init__(self, svc, member):
        super().__init__()
        self.svc = svc
        self.member = member
        self.table = svc.table(member)
        self.vanilla = svc.vanilla(member)
        self.all_fields = list(self.table.schema.fields)
        self.fields = self.all_fields
        self.show_refs = True

    def set_visible_fields(self, fields):
        self.beginResetModel()
        self.fields = fields
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.table.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.fields)

    def headerData(self, s, o, role=Qt.ItemDataRole.DisplayRole):
        if o == Qt.Orientation.Horizontal:
            f = self.fields[s]
            if role == Qt.ItemDataRole.DisplayRole:
                return f.name
            if role == Qt.ItemDataRole.ToolTipRole:
                bits = [f"<b>{f.name}</b> ({f.type}{', ' + str(f.size) + ' bytes' if f.type in ('str', 'bytes') else ''}"
                        f", offset 0x{f.offset:X})"]
                if f.desc:
                    bits.append(f.desc)
                if f.ref:
                    bits.append(f"→ refers to <i>{f.ref}</i>")
                bits.append(f"confidence: {f.confidence}")
                return "<br>".join(bits)
            if role == Qt.ItemDataRole.ForegroundRole and f.name.startswith("unk"):
                return QBrush(UNK)
        else:
            if role == Qt.ItemDataRole.DisplayRole:
                return str(s)
        return None

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        if not idx.isValid():
            return None
        row = self.table.rows[idx.row()]
        f = self.fields[idx.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            v = row._get(f)
            if role == Qt.ItemDataRole.EditRole:
                return v.hex(" ") if isinstance(v, (bytes, bytearray)) else v
            s = _fmt(v)
            if self.show_refs and f.ref:
                lab = self.svc.ref_label(f.ref, v)
                if lab:
                    s = f"{s} · {lab}"
            return s
        if role == Qt.ItemDataRole.BackgroundRole:
            r = idx.row()
            if r >= len(self.vanilla.rows):
                return QBrush(ADDED)
            if self.vanilla.rows[r]._get(f) != row._get(f):
                return QBrush(MODIFIED)
        if role == Qt.ItemDataRole.ToolTipRole:
            bits = []
            tip = self.svc.ref_tooltip(f.ref, row._get(f)) if f.ref else None
            if tip:
                bits.append(tip.replace("<qt>", "").replace("</qt>", ""))
            elif f.name == self.table.schema.display or f.name.startswith(("name_", "desc")):
                # the row's own name / description cell: its full description
                tip = describe_row(self.member, self.table.schema, row)
                if tip:
                    bits.append(tip.replace("<qt>", "").replace("</qt>", ""))
            else:
                # any other cell: which row, what the field means, what the value means
                disp = self.table.schema.display
                name = row.get(disp) if disp and disp != f.name else None
                if name:
                    bits.append(f"<b>{_esc(name)}</b>")
                v = row._get(f)
                line = f"<i>{_esc(f.name)}</i>"
                if f.enum and f.enum.get(str(v), f.enum.get(v)) is not None:
                    line += f" = {_esc(v)} · {_esc(f.enum.get(str(v), f.enum.get(v)))}"
                bits.append(line)
                if f.desc:
                    bits.append(f"<span style='color:#9aa4b8'>{_esc(f.desc)}</span>")
            if idx.row() < len(self.vanilla.rows):
                va = self.vanilla.rows[idx.row()]._get(f)
                if va != row._get(f):
                    bits.append(f"Original value: {_esc(_fmt(va))}")
            return "<qt>" + "<br>".join(bits) + "</qt>" if bits else None
        if role == Qt.ItemDataRole.UserRole:
            return row._get(f)
        return None

    def flags(self, idx):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def setData(self, idx, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole:
            return False
        row = self.table.rows[idx.row()]
        f = self.fields[idx.column()]
        before = row.copy()
        try:
            if f.type in ("str", "strptr"):
                row.set(f.name, str(value))
            elif f.type == "bytes":
                row.set(f.name, bytes.fromhex(str(value).replace(" ", "")))
            elif f.type in ("f32", "f64"):
                row.set(f.name, float(value))
            else:
                s = str(value).strip().split(" ")[0]
                row.set(f.name, int(s, 0))
        except Exception as e:
            QMessageBox.warning(None, "Invalid value", str(e))
            return False
        if before.raw != row.raw or before.strs != row.strs:
            cb = getattr(self, "on_edit", None)
            if cb:
                cb(self.member, idx.row(), before)
        self.svc.mark_dirty(self.member)
        self.dataChanged.emit(idx, idx)
        return True


class RefDelegate(QStyledItemDelegate):
    """Editable combo with the referenced table's entries for `ref` fields."""

    def __init__(self, svc, model_getter, parent=None):
        super().__init__(parent)
        self.svc = svc
        self.model_getter = model_getter

    def _field(self, index):
        m = self.model_getter()
        src = index.model().mapToSource(index) if hasattr(index.model(), "mapToSource") else index
        return m.fields[src.column()]

    def createEditor(self, parent, option, index):
        f = self._field(index)
        if f.ref:
            choices = self.svc.ref_choices(f.ref)
            if choices and len(choices) < 20000:
                cb = QComboBox(parent)
                cb.setEditable(True)
                tips = self.svc.ref_tooltips(f.ref)
                for kv, lab in choices:
                    cb.addItem(f"{kv} · {lab}" if lab else str(kv), kv)
                    if kv in tips:
                        cb.setItemData(cb.count() - 1, tips[kv], Qt.ItemDataRole.ToolTipRole)
                cb.completer().setFilterMode(Qt.MatchFlag.MatchContains)
                cb.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
                from ..common import type_to_search
                type_to_search(cb)
                return cb
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            v = index.data(Qt.ItemDataRole.EditRole)
            i = editor.findData(v)
            if i >= 0:
                editor.setCurrentIndex(i)
            else:
                editor.setEditText(str(v))
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            txt = editor.currentText()
            i = editor.findText(txt)
            if i >= 0:
                val = editor.itemData(i)
            elif txt.strip().split(" ")[0].lstrip("-").isdigit():
                val = txt.strip().split(" ")[0]
            else:
                return                                   # a search typed but nothing chosen: the value stays
            model.setData(index, val, Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.only_modified = False

    def set_text(self, t):
        self.text = t.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, r, parent):
        m = self.sourceModel()
        if self.only_modified:
            vr = m.vanilla.rows[r] if r < len(m.vanilla.rows) else None
            row = m.table.rows[r]
            if vr is not None and bytes(vr.raw) == bytes(row.raw) and vr.strs == row.strs:
                return False
        if not self.text:
            return True
        row = m.table.rows[r]
        for f in m.fields:
            v = row._get(f)
            if isinstance(v, (str, int)) and self.text in str(v).lower():
                return True
        return False


class DatabasePage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.main = main
        self.svc = get_service(ws)
        self.model = None
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Database Editor",
                                 "Every game table: characters, classes, skills, items, evilities, stages, quests… "
                                 "Double-click a cell to edit. Purple = changed, green = new row. Hover a column "
                                 "header for a description. Changes are saved into the active mod when you press Save."))
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tsearch = SearchBox("Find table…")
        self.tsearch.textChanged.connect(self._filter_tables)
        ll.addWidget(self.tsearch)
        self.tables = QListWidget()
        self.tables.currentItemChanged.connect(self._open_table)
        ll.addWidget(self.tables, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Select a table")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        rl.addWidget(self.title)
        bar = QHBoxLayout()
        self.search = SearchBox("Search rows (any column)…")
        self.search.textChanged.connect(lambda t: self.proxy.set_text(t))
        bar.addWidget(self.search, 2)
        self.lang = QComboBox()
        self.lang.addItems(["All languages", "EN", "JP", "FR", "CHN", "KOR"])
        self.lang.setCurrentText("EN")
        self.lang.currentTextChanged.connect(self._apply_columns)
        bar.addWidget(self.lang)
        self.col_filter = QLineEdit()
        self.col_filter.setPlaceholderText("Filter columns…")
        self.col_filter.textChanged.connect(self._apply_columns)
        bar.addWidget(self.col_filter, 1)
        self.show_unk = QCheckBox("Unknown fields")
        self.show_unk.toggled.connect(self._apply_columns)
        bar.addWidget(self.show_unk)
        self.only_mod = QCheckBox("Changed rows only")
        self.only_mod.toggled.connect(self._only_mod)
        bar.addWidget(self.only_mod)
        rl.addLayout(bar)

        nav = QHBoxLayout()
        self.b_back = QToolButton()
        self.b_back.setText("←")
        self.b_back.setToolTip("Back to the record before (Alt+Left)")
        self.b_back.clicked.connect(lambda: self._history_go(-1))
        nav.addWidget(self.b_back)
        self.b_fwd = QToolButton()
        self.b_fwd.setText("→")
        self.b_fwd.setToolTip("Forward (Alt+Right)")
        self.b_fwd.clicked.connect(lambda: self._history_go(1))
        nav.addWidget(self.b_fwd)
        b = QPushButton("⌕ Go to any record…  (Ctrl+P)")
        b.setToolTip("Find a record of any table by its name or id")
        b.clicked.connect(self.goto)
        nav.addWidget(b)
        b = QPushButton("✔ Check table")
        b.setToolTip("Look for what would crash the game or look wrong: rows with the same id, references to rows "
                     "that don't exist, texts too long, evility kinds the Skill Shop can't take …")
        b.clicked.connect(self.check)
        nav.addWidget(b)
        self.b_presets = QToolButton()
        self.b_presets.setText("Evility presets ▾")
        self.b_presets.setToolTip("Set the fields an evility of one kind needs (Skill.dat)")
        self.b_presets.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        pm = QMenu(self.b_presets)
        for k, (lab, _) in dbcheck.SKILL_PRESETS.items():
            pm.addAction(lab, lambda k=k: self.preset(k))
        self.b_presets.setMenu(pm)
        nav.addWidget(self.b_presets)
        b = QPushButton("Sort new rows")
        b.setToolTip("Put the rows you added in the order of their ids (the game's rows stay where they are)")
        b.clicked.connect(self.sort_new)
        nav.addWidget(b)
        self.b_rec = QToolButton()
        self.b_rec.setText("Record panel")
        self.b_rec.setCheckable(True)
        self.b_rec.setChecked(True)
        self.b_rec.toggled.connect(lambda on: self.record.setVisible(on))
        nav.addWidget(self.b_rec)
        for lab, fn, tip in (("↶", self.undo, "Undo the last change of a row (Ctrl+Z)"),
                             ("↷", self.redo, "Redo (Ctrl+Y)")):
            b = QToolButton()
            b.setText(lab)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            nav.addWidget(b)
        nav.addStretch(1)
        b = QPushButton("💾 Save all")
        b.setToolTip("Save the changes of every table with unsaved edits")
        b.clicked.connect(self.save_all)
        nav.addWidget(b)
        rl.addLayout(nav)

        self.view = QTableView()
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(False)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.view.horizontalHeader().setDefaultSectionSize(110)
        self.view.verticalHeader().setDefaultSectionSize(24)
        self.view.setItemDelegate(RefDelegate(self.svc, lambda: self.model, self.view))
        self.proxy = FilterProxy()
        self.view.setModel(self.proxy)
        self.record = RecordPanel(self.svc, self)
        self.record.navigate.connect(self.open_record)
        self.record.edited.connect(self._record_edited)
        self.record.before_edit.connect(self._remember)
        self._undo, self._redo = [], []
        grid_split = QSplitter()
        grid_split.addWidget(self.view)
        grid_split.addWidget(self.record)
        grid_split.setSizes([760, 440])
        rl.addWidget(grid_split, 1)
        self._hist, self._hpos = [], -1
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.goto)
        QShortcut(QKeySequence("Ctrl+Z"), self.view, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self.view, activated=self.redo)
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self._history_go(-1))
        QShortcut(QKeySequence("Alt+Right"), self, activated=lambda: self._history_go(1))

        btns = QHBoxLayout()
        self.b_save = QPushButton("💾 Save")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save)
        btns.addWidget(self.b_save)
        for text, fn, tip in [
            ("➕ Duplicate row", self.dup_row, "Append a copy of the selected row at the end of the table"),
            ("🗑 Delete new row", self.del_row, "Delete a row you added (original rows can't be removed)"),
            ("↺ Revert row", self.revert_row, "Restore the selected row to its original values"),
            ("Discard unsaved", self.discard, "Throw away edits since the last save"),
            ("Revert table", self.revert_table, "Remove all of the mod's changes to this table"),
            ("Export CSV…", self.export_csv, "Open in Excel / LibreOffice"),
            ("Import CSV…", self.import_csv, "Load rows edited in a spreadsheet")]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        rl.addLayout(btns)
        split.addWidget(right)
        split.setSizes([260, 1100])
        lay.addWidget(split, 1)
        self._populated = False
        from ..common import Refresher
        self._reopen_later = Refresher(self, self._reopen)       # once, and only while the page shows
        ws.active_mod_changed.connect(self._reopen_later)
        self.svc.table_changed.connect(lambda m: self.model and m == self.model.member and self._reopen_later())

    def on_show(self):
        if not self._populated:
            self._populated = True
            self._populate()
            if self.model is None:
                self.select_table("char.dat")     # never open on an empty grid

    def _populate(self):
        self.tables.clear()
        members = self.svc.members()
        entries = []
        for m in members:
            cat, title = FRIENDLY.get(m, ("Other", None))
            entries.append((cat, title or m, m))
        order = {"Units": 0, "Skills": 1, "Items": 2, "Stages": 3, "World": 4, "Text": 5, "Other": 6}
        entries.sort(key=lambda e: (order[e[0]], e[1].lower()))
        last = None
        for cat, title, m in entries:
            if cat != last:
                h = QListWidgetItem(cat.upper())
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                h.setForeground(QBrush(QColor("#ff4f8b")))
                self.tables.addItem(h)
                last = cat
            ok = self.svc.has_schema(m)
            it = QListWidgetItem(("   " + title) + ("" if title == m else f"  ({m})") + ("" if ok else "  ⚠"))
            it.setData(Qt.ItemDataRole.UserRole, m)
            if not ok:
                it.setToolTip("No field layout known for this table yet")
            self.tables.addItem(it)

    def _filter_tables(self, t):
        t = t.lower()
        for i in range(self.tables.count()):
            it = self.tables.item(i)
            if it.data(Qt.ItemDataRole.UserRole):
                it.setHidden(bool(t) and t not in it.text().lower())

    def select_table(self, member):
        self.on_show()
        for i in range(self.tables.count()):
            if self.tables.item(i).data(Qt.ItemDataRole.UserRole) == member:
                self.tables.setCurrentRow(i)
                return

    def _confirm_leave(self):
        if self.model and self.svc.is_dirty(self.model.member):
            r = QMessageBox.question(self, "Unsaved changes",
                                     f"Save your changes to {self.model.member} first?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                     QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return False
            if r == QMessageBox.StandardButton.Save:
                return self.save()
            self.svc.discard(self.model.member)
        return True

    def _open_table(self, it, prev=None):
        if not it or not it.data(Qt.ItemDataRole.UserRole):
            return
        member = it.data(Qt.ItemDataRole.UserRole)
        if self.model and self.model.member == member:
            return
        if not self._confirm_leave():
            self.tables.blockSignals(True)
            self.tables.setCurrentItem(prev)
            self.tables.blockSignals(False)
            return
        self._load(member)

    def _load(self, member):
        try:
            self.model = TableModel(self.svc, member)
        except Exception as e:
            self.model = None
            self.proxy.setSourceModel(None)
            self.title.setText(f"{member}: cannot open ({e})")
            return
        sch = self.model.table.schema
        self.model.on_edit = self._remember
        self.proxy.setSourceModel(self.model)
        self.view.selectionModel().currentRowChanged.connect(self._row_changed)
        self.b_presets.setVisible(member == "Skill.dat")
        self.record.show_row(self.model, None)
        cat, title = FRIENDLY.get(member, ("", member))
        self.title.setText(f"{title}  —  {len(self.model.table.rows)} rows, {len(sch.fields)} fields"
                           + (f"<br><span style='color:#8a90b8;font-weight:400'>{sch.desc}</span>" if sch.desc else ""))
        self._apply_columns()

    def _reopen(self):
        if self.model:
            m = self.model.member
            self.model = None
            self._load(m)

    def _apply_columns(self, *a):
        if not self.model:
            return
        lang = self.lang.currentText()
        cf = self.col_filter.text().lower()
        vis = []
        for f in self.model.all_fields:
            if not self.show_unk.isChecked() and (f.name.startswith("unk") or f.name.startswith("pad")):
                continue
            if lang != "All languages" and f.lang and f.lang != lang:
                continue
            if cf and cf not in f.name.lower() and cf not in (f.desc or "").lower():
                continue
            vis.append(f)
        self.model.set_visible_fields(vis)
        hdr = self.view.horizontalHeader()
        for i, f in enumerate(vis):
            if f.type in ("str", "strptr"):
                self.view.setColumnWidth(i, 200 if f.size > 40 or f.type == "strptr" else 140)
            elif f.ref:
                self.view.setColumnWidth(i, 170)
            else:
                self.view.setColumnWidth(i, 90)

    # ------------------------------------------------------------------ records
    def _row_changed(self, cur, prev=None):
        if not self.model or not cur.isValid():
            return
        r = self.proxy.mapToSource(cur).row()
        if self.record.r != r or self.record.model is not self.model:
            self.record.show_row(self.model, r)
            self._history_add(self.model.member, r)

    def _record_edited(self, r):
        if not self.model:
            return
        a, b = self.model.index(r, 0), self.model.index(r, max(0, self.model.columnCount() - 1))
        self.model.dataChanged.emit(a, b)

    def open_record(self, member, r, remember=True):
        """show row r of a table (opens the table, selects the row)"""
        if not self.model or self.model.member != member:
            self.select_table(member)
            if not self.model or self.model.member != member:
                return
        if self.only_mod.isChecked() or self.search.text():
            self.search.clear()
            self.only_mod.setChecked(False)
        idx = self.proxy.mapFromSource(self.model.index(r, 0))
        if idx.isValid():
            self.view.setCurrentIndex(idx)
            self.view.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.record.show_row(self.model, r)
        if remember:
            self._history_add(member, r)

    def _history_add(self, member, r):
        if self._hpos >= 0 and self._hist[self._hpos] == (member, r):
            return
        del self._hist[self._hpos + 1:]
        self._hist.append((member, r))
        del self._hist[:-200]
        self._hpos = len(self._hist) - 1

    def _history_go(self, d):
        k = self._hpos + d
        if 0 <= k < len(self._hist):
            self._hpos = k
            self.open_record(*self._hist[k], remember=False)

    def goto(self):
        dlg = GotoDialog(self.svc, self)
        if dlg.exec() and dlg.choice:
            self.open_record(*dlg.choice)

    def _valid_keys(self, ref):
        t, f, by_index = database.parse_ref(ref)
        m = self.svc.find_table(t) if t else None
        if not m or not self.svc.has_schema(m):
            return None
        tb = self.svc.table(m)
        if by_index:
            return set(range(len(tb.rows)))
        k = f or tb.schema.key
        return {r.get(k) for r in tb.rows} if k else None

    def check(self):
        if not self.model:
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            issues = dbcheck.check(self.model.member, self.model.table, self._valid_keys, self.model.vanilla)
        finally:
            QApplication.restoreOverrideCursor()
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Check: {self.model.member}")
        dlg.resize(760, 460)
        lay = QVBoxLayout(dlg)
        from collections import Counter
        c = Counter(i.severity for i in issues)
        lay.addWidget(QLabel(f"{c.get(dbcheck.CRASH, 0)} crash risk(s) · {c.get(dbcheck.WARN, 0)} warning(s) · "
                             f"{c.get(dbcheck.NOTE, 0)} note(s)" + ("" if issues else " — nothing found")))
        lst = _QList()
        for i in issues:
            it = QListWidgetItem(f"[{i.severity}] " + (f"row {i.row}: " if i.row is not None else "") + i.text)
            if i.severity == dbcheck.CRASH:
                it.setForeground(QBrush(QColor("#ff6b6b")))
            elif i.severity == dbcheck.WARN:
                it.setForeground(QBrush(QColor("#ffc46b")))
            it.setData(Qt.ItemDataRole.UserRole, i.row)
            lst.addItem(it)
        lst.itemDoubleClicked.connect(lambda it: it.data(Qt.ItemDataRole.UserRole) is not None and
                                      self.open_record(self.model.member, it.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(lst, 1)
        tip = QLabel("Double-click an entry to open its row.")
        tip.setObjectName("muted")
        lay.addWidget(tip)
        dlg.show()
        self._check_dlg = dlg

    def preset(self, key):
        if not self.model or self.model.member != "Skill.dat":
            return
        rows = self._sel_rows() or ([self.record.r] if self.record.r is not None else [])
        if not rows:
            QMessageBox.information(self, "Presets", "Select the evility's row first.")
            return
        r0 = self.model.table.rows[rows[0]]
        owner, ok = QInputDialog.getInt(self, dbcheck.SKILL_PRESETS[key][0], "Owner (char.dat id: a character, or "
                                        "a class family such as 1010):", int(r0["owner"]), 0, 2 ** 31 - 1)
        if not ok:
            return
        if key.startswith("class") and not dbcheck.is_class_id(owner):
            if QMessageBox.question(self, "Presets", f"{owner} isn't a class family id (1000+, a multiple of 10): "
                                    "a generic class's evility owned by anything else crashes the Skill Shop. "
                                    "Set it anyway?") != QMessageBox.StandardButton.Yes:
                return
        n = 0
        for r in rows:
            n += bool(dbcheck.apply_preset(self.model.table.rows[r], key, owner=owner))
        if n:
            self.svc.mark_dirty(self.model.member)
            self.model.layoutChanged.emit()
            self.record.refresh()
        self.ws.log(f"Skill.dat: {dbcheck.SKILL_PRESETS[key][0]} set on {n} row(s) (Save to keep it)")

    def sort_new(self):
        if not self.model:
            return
        t, base = self.model.table, len(self.model.vanilla.rows)
        k = t.schema.key
        if not k or len(t.rows) <= base + 1:
            return
        new = sorted(t.rows[base:], key=lambda r: r.get(k))
        if new == t.rows[base:]:
            return
        self.model.beginResetModel()
        t.rows[base:] = new
        self.model.endResetModel()
        self.svc.mark_dirty(self.model.member)
        self.ws.log(f"{self.model.member}: the {len(new)} new rows sorted by {k}")

    def _only_mod(self, on):
        self.proxy.only_modified = on
        self.proxy.invalidateFilter()

    def _sel_rows(self):
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.view.selectionModel().selectedIndexes()})
        return rows

    # ------------------------------------------------------------------ actions
    def save(self):
        if not self.model:
            return False
        try:
            self.model.table.to_bytes()  # validate serialisation
        except Exception as e:
            error_box(self, "This table cannot be saved", e)
            return False
        if self.svc.commit(self.model.member, self):
            self.ws.log(f"Saved {self.model.member} changes into {self.svc.saved_text()}")
            return True
        return False

    # ---- undo / redo of row changes (grid and record panel)
    def _remember(self, member, r, before):
        self._undo.append((member, r, before))
        del self._undo[:-300]
        self._redo = []

    def _swap(self, src, dst):
        if not src:
            return
        member, r, row = src.pop()
        if not self.model or self.model.member != member:
            self.open_record(member, r)
            if not self.model or self.model.member != member:
                return
        t = self.model.table
        if not 0 <= r < len(t.rows):
            return
        dst.append((member, r, t.rows[r].copy()))
        t.rows[r] = row
        self.svc.mark_dirty(member)
        self._record_edited(r)
        self.open_record(member, r, remember=False)

    def undo(self):
        self._swap(self._undo, self._redo)

    def redo(self):
        self._swap(self._redo, self._undo)

    def save_all(self):
        dirty = self.svc.dirty_members()
        if not dirty:
            self.ws.log("Nothing to save")
            return
        if self.svc.commit_all(self):
            self.ws.log(f"Saved {', '.join(sorted(dirty))} into {self.svc.saved_text()}")

    def dup_row(self):
        rows = self._sel_rows()
        if not self.model or not rows:
            QMessageBox.information(self, "Duplicate", "Select a cell in the row you want to copy.")
            return
        self.model.beginResetModel()
        for r in rows:
            self.model.table.add_row(copy_from=r)
        self.model.endResetModel()
        self.svc.mark_dirty(self.model.member)
        self.view.scrollToBottom()
        self.ws.log(f"Added {len(rows)} row(s) to {self.model.member}. Remember to give new rows a unique ID.")

    def del_row(self):
        rows = self._sel_rows()
        if not self.model or not rows:
            return
        base = len(self.model.vanilla.rows)
        if any(r < base for r in rows):
            QMessageBox.information(self, "Delete", "Only rows you added can be deleted (original rows are referenced "
                                                    "by the game by position).")
            return
        self.model.beginResetModel()
        for r in reversed(rows):
            self.model.table.delete_row(r)
        self.model.endResetModel()
        self.svc.mark_dirty(self.model.member)

    def revert_row(self):
        rows = self._sel_rows()
        if not self.model:
            return
        for r in rows:
            if r < len(self.model.vanilla.rows):
                self.model.table.rows[r] = self.model.vanilla.rows[r].copy()
        self.model.layoutChanged.emit()
        self.svc.mark_dirty(self.model.member)

    def discard(self):
        if self.model:
            self.svc.discard(self.model.member)

    def revert_table(self):
        if self.model and QMessageBox.question(self, "Revert table",
                                               "Remove ALL changes the active mod makes to this table?") \
                == QMessageBox.StandardButton.Yes:
            self.svc.revert_all(self.model.member)

    def export_csv(self):
        if not self.model:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export CSV", self.model.member.split(".")[0] + ".csv", "CSV (*.csv)")
        if p:
            database.table_to_csv(self.model.table, p)
            self.ws.log(f"Exported {self.model.member} → {p}")

    def import_csv(self):
        if not self.model:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV (*.csv)")
        if not p:
            return
        try:
            self.model.beginResetModel()
            database.table_from_csv(self.model.table, p, truncate=True)
            self.model.endResetModel()
            self.svc.mark_dirty(self.model.member)
            self.ws.log(f"Imported {p} into {self.model.member} (not saved yet)")
        except Exception as e:
            self.model.endResetModel()
            error_box(self, "CSV import failed", e)
