"""Recruiter: choose which characters the Dark Assembly lets you recruit, one bill per character or per pack.

Logic and file format: d5lib/recruitpage.py (headless, tested); the hooks that make a passed bill create the
characters: d5lib/wishrecruit.py (RECRUIT1/RECRUIT2; design after Cryswar's Overlord recruit wishes, The Unlicense).
Saving writes the active mod's two files only (the bill row in patches/db and patches/wishes/recruit_wishes.json).
Nothing is installed from here, and the game is not touched.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                             QSplitter, QVBoxLayout, QWidget)

from d5lib import recruitpage as model

from ..common import PageHeader, error_box
from ..dbservice import char_names, get_service

ROLE = Qt.ItemDataRole.UserRole


class RecruitPage(QWidget):
    def __init__(self, ws, main=None):
        super().__init__()
        self.ws = ws
        self.bills = []
        self.cur = None                       # index into self.bills
        self._loading = False
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Recruiter", "Make characters recruitable at the Dark Assembly: one bill per "
                                 "character, or one bill that brings a whole pack. Saved into your active mod."))
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("background:#fff3cd; color:#664d03; padding:4px 8px; border-radius:4px;")
        lay.addWidget(self.note)
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton("➕ New bill")
        b.clicked.connect(self.new_bill)
        self.b_del = QPushButton("🗑 Remove")
        self.b_del.clicked.connect(self.remove_bill)
        row.addWidget(b), row.addWidget(self.b_del)
        ll.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        form = QFormLayout()
        self.f_name = QLineEdit()
        self.f_text = QPlainTextEdit()
        self.f_text.setMaximumHeight(60)
        self.f_mana = QSpinBox()
        self.f_mana.setRange(0, 99999999)
        self.f_diff = QSpinBox()
        self.f_diff.setRange(0, 999)
        self.f_flag = QSpinBox()
        self.f_flag.setRange(0, 99999)
        self.f_flag.setToolTip("A game flag the bill waits for before it is listed (0 = always listed)")
        self.f_id = QLabel("")
        form.addRow("Bill id", self.f_id)
        form.addRow("Bill name", self.f_name)
        form.addRow("Text", self.f_text)
        form.addRow("Mana cost", self.f_mana)
        form.addRow("Difficulty", self.f_diff)
        form.addRow("Unlock flag", self.f_flag)
        rl.addLayout(form)
        rl.addWidget(QLabel("Characters this bill brings (a pack when there is more than one):"))
        self.members = QListWidget()
        self.members.currentRowChanged.connect(self._pick_member)
        rl.addWidget(self.members, 1)
        add = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.setEditable(True)
        self.pick.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.pick.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.pick.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.m_level = QSpinBox()
        self.m_level.setRange(1, 9999)
        self.m_dup = QCheckBox("a second copy may join")
        b_add = QPushButton("Add")
        b_add.clicked.connect(self.add_member)
        b_rm = QPushButton("Remove selected")
        b_rm.clicked.connect(self.remove_member)
        for w in (self.pick, QLabel("Lv"), self.m_level, self.m_dup, b_add, b_rm):
            add.addWidget(w)
        rl.addLayout(add)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        rl.addWidget(self.status)
        bar = QHBoxLayout()
        self.b_save = QPushButton("💾 Save to mod")
        self.b_save.clicked.connect(self.save)
        bar.addStretch(1), bar.addWidget(self.b_save)
        rl.addLayout(bar)
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        for w in (self.f_name, ):
            w.textChanged.connect(self._edited)
        self.f_text.textChanged.connect(self._edited)
        for w in (self.f_mana, self.f_diff, self.f_flag):
            w.valueChanged.connect(self._edited)
        ws.active_mod_changed.connect(lambda _: self.refresh()) if hasattr(ws, "active_mod_changed") else None

    # ------------------------------------------------------------------ data (tests replace these two)
    def characters(self):
        """{char id: name} the picker offers: the active mod's own characters first, then the whole char.dat"""
        names = {}
        try:
            names = char_names(get_service(self.ws))
        except Exception:
            pass
        return names

    def taken_ids(self):
        """WishDataBase ids that are not this mod's own bills (the game's, other mods')"""
        mod = self.ws.active_mod
        own = {b.id for b in model.load_bills(mod)} if mod else set()
        try:
            t = get_service(self.ws).table("WishDataBase.dat")
            return {int(r["id"]) for r in t.rows} - own
        except Exception:
            return set()

    # ------------------------------------------------------------------ list
    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        mod = getattr(self.ws, "active_mod", None)
        self.bills = model.load_bills(mod) if mod else []
        self.b_save.setEnabled(mod is not None)
        self.note.setText(
            f"Saving writes to the mod “{getattr(mod, 'name', mod.id) if mod else '(none)'}”. A passed bill "
            f"creates its characters through the game's own recruit call; an installed copy of the kit with "
            f"this mod is needed for it to work. The roster holds 128 units, so a bill shows only while "
            f"all its characters fit.") if mod else self.note.setText("Choose an active mod first (bottom left).")
        names = self.characters()
        self.pick.clear()
        for cid, n in sorted(names.items(), key=lambda kv: (str(kv[1]).lower(), kv[0])):
            self.pick.addItem(f"{n}  [{cid}]", cid)
        self._fill(0 if self.bills else -1)

    def _fill(self, select=-1):
        self.list.blockSignals(True)
        self.list.clear()
        for b in self.bills:
            it = QListWidgetItem(f"{b.id}  {b.name}  ({len(b.members)})")
            it.setData(ROLE, b.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.list.setCurrentRow(select)
        self._pick(select)

    def _pick(self, i):
        self.cur = i if 0 <= i < len(self.bills) else None
        self._loading = True
        b = self.bills[self.cur] if self.cur is not None else None
        self.f_id.setText(str(b.id) if b else "")
        self.f_name.setText(b.name if b else "")
        self.f_text.setPlainText(b.text if b else "")
        self.f_mana.setValue(b.mana_cost if b else model.DEFAULT_MANA)
        self.f_diff.setValue(b.difficulty if b else model.DEFAULT_DIFFICULTY)
        self.f_flag.setValue(b.req_flag if b else 0)
        for w in (self.f_name, self.f_text, self.f_mana, self.f_diff, self.f_flag, self.members):
            w.setEnabled(b is not None)
        self._loading = False
        self._fill_members()

    def _fill_members(self):
        self.members.clear()
        names = self.characters()
        b = self.bills[self.cur] if self.cur is not None else None
        for m in (b.members if b else []):
            self.members.addItem(f"{names.get(m.character, '?')} [{m.character}]  Lv {m.level}"
                                 f"{'  (copies allowed)' if m.duplicates else ''}")
        self._show_status()

    def _pick_member(self, i):
        pass

    def _show_status(self):
        b = self.bills[self.cur] if self.cur is not None else None
        if not b:
            self.status.setText("")
            return
        bad = model.check([b], self.taken_ids())
        self.status.setText("Problem: " + "; ".join(bad) if bad else f"Pack of {len(b.members)}: ready to save.")
        self.status.setStyleSheet("color:#c0392b;" if bad else "color:#2e7d32;")

    # ------------------------------------------------------------------ edit
    def _edited(self, *_):
        if self._loading or self.cur is None:
            return
        b = self.bills[self.cur]
        b.name, b.text = self.f_name.text(), self.f_text.toPlainText()
        b.mana_cost, b.difficulty, b.req_flag = self.f_mana.value(), self.f_diff.value(), self.f_flag.value()
        self.list.item(self.cur).setText(f"{b.id}  {b.name}  ({len(b.members)})")
        self._show_status()

    def new_bill(self):
        b = model.new_bill(self.bills, "New recruit bill", [], taken=self.taken_ids())
        self._fill(len(self.bills) - 1)
        return b

    def remove_bill(self):
        if self.cur is None:
            return
        del self.bills[self.cur]
        self._fill(min(self.cur, len(self.bills) - 1))

    def add_member(self):
        if self.cur is None:
            self.new_bill()
        cid = self.pick.currentData()
        if cid is None:
            return
        self.bills[self.cur].members.append(model.Member(int(cid), self.m_level.value(), self.m_dup.isChecked()))
        self._fill_members()
        self.list.item(self.cur).setText(f"{self.bills[self.cur].id}  {self.bills[self.cur].name}  "
                                         f"({len(self.bills[self.cur].members)})")

    def remove_member(self):
        i = self.members.currentRow()
        if self.cur is None or i < 0:
            return
        del self.bills[self.cur].members[i]
        self._fill_members()

    def save(self):
        mod = self.ws.active_mod
        try:
            r = model.save_bills(mod, self.bills, self.taken_ids(), self.characters() or None)
        except ValueError as e:
            self.status.setText("Not saved: " + str(e))
            self.status.setStyleSheet("color:#c0392b;")
            return None
        except Exception as e:                       # noqa: BLE001
            error_box(self, "Recruiter", e)
            return None
        self.status.setText(f"Saved {r['bills']} bill(s) to the mod; removed {len(r['removed'])}. "
                            f"Install the mod to put them in the game.")
        self.status.setStyleSheet("color:#2e7d32;")
        return r
