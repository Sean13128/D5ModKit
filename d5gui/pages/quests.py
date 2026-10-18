"""Quests: the Quest shop's quests and the resident requests (Quest.dat) -- what they ask for, what they give, when they
show -- with new quests of your own.  A quest is a row of Quest.dat; the Characters page shows a character's recruit
quest through the same table (d5gui/questinfo.py puts a quest in words, d5gui/questgoal.py picks the objective)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                             QSpinBox, QSplitter, QVBoxLayout, QWidget)

from d5lib import dbpatch, mapfile, questcheck
from .. import questinfo
from ..common import PageHeader, SearchBox, error_box, type_to_search
from ..dbservice import char_names, get_service, table_names
from ..questgoal import ObjectiveWidget

ROLE = Qt.ItemDataRole.UserRole
QUEST = "Quest.dat"
REWARDS = [(1, "HL (the amount)"), (2, "An item"), (3, "An evility"), (4, "A skill"), (5, "A character joins"),
           (6, "A class is unlocked"), (7, "Chara World rank"), (8, "A story / system flag is set")]
KINDS = [(0, "Quest shop"), (1, "Request (resident)")]


def _searchable(cb):
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    cb.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    cb.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    type_to_search(cb)


class QuestsPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.svc = get_service(ws)
        self.row = None                     # index of the quest shown
        self._loading = False
        self._populated = False
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Quests", "The Quest shop's quests and the residents' requests: what each asks "
                                           "for, what it gives, and when it shows. Make quests of your own: a "
                                           "stage of yours to clear, enemies to defeat, a character or class as "
                                           "the prize."))
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.search = SearchBox("Search quests…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton("➕ New quest")
        b.setToolTip("A quest of your own at the Quest shop (saved into your mod)")
        b.clicked.connect(self.new_quest)
        row.addWidget(b)
        self.b_del = QPushButton("🗑 Delete")
        self.b_del.setToolTip("Delete a quest of yours (the game's own quests can't be deleted)")
        self.b_del.clicked.connect(self.delete_quest)
        row.addWidget(self.b_del)
        ll.addLayout(row)
        split.addWidget(left)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        bl = QVBoxLayout(body)
        self.title = QLabel("Pick a quest")
        self.title.setObjectName("cardTitle")
        bl.addWidget(self.title)
        self.words = QLabel()
        self.words.setWordWrap(True)
        self.words.setTextFormat(Qt.TextFormat.RichText)
        self.words.setObjectName("muted")
        bl.addWidget(self.words)

        g = QGroupBox("The quest")
        f = QFormLayout(g)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.name = QLineEdit()
        self.name.editingFinished.connect(lambda: self._set_text("name", self.name.text()))
        f.addRow("Title", self.name)
        self.client = QLineEdit()
        self.client.editingFinished.connect(lambda: self._set_text("client", self.client.text()))
        f.addRow("Client", self.client)
        self.text = QPlainTextEdit()
        self.text.setMaximumHeight(90)
        self.text.setToolTip("What the client says (wrapped into the game's 5 lines on save)")
        self.text.textChanged.connect(self._text_changed)
        f.addRow("Text", self.text)
        self.kind = QComboBox()
        for k, label in KINDS:
            self.kind.addItem(label, k)
        self.kind.currentIndexChanged.connect(lambda _: self._set("quest_kind", self.kind.currentData()))
        f.addRow("Kind", self.kind)
        self.important = QCheckBox("Important (highlighted, like the story's key quests)")
        self.important.toggled.connect(lambda on: self._set("important", 1 if on else 0))
        f.addRow("", self.important)
        bl.addWidget(g)

        g = QGroupBox("To finish it")
        v = QVBoxLayout(g)
        self.objective = ObjectiveWidget(self.svc, self)
        self.objective.goal.currentIndexChanged.connect(self._objective_changed)
        self.objective.stage.currentIndexChanged.connect(self._objective_changed)
        self.objective.klass.currentIndexChanged.connect(self._objective_changed)
        self.objective.count.valueChanged.connect(self._objective_changed)
        v.addWidget(self.objective)
        self.obj_note = QLabel()
        self.obj_note.setWordWrap(True)
        self.obj_note.setObjectName("muted")
        v.addWidget(self.obj_note)
        bl.addWidget(g)

        g = QGroupBox("The reward")
        f = QFormLayout(g)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.rtype = QComboBox()
        for k, label in REWARDS:
            self.rtype.addItem(label, k)
        self.rtype.currentIndexChanged.connect(self._reward_type_changed)
        f.addRow("Gives", self.rtype)
        self.rvalue = QComboBox()
        _searchable(self.rvalue)
        self.rvalue.currentIndexChanged.connect(self._reward_value_changed)
        self.ramount = QSpinBox()
        self.ramount.setRange(0, 999999999)
        self.ramount.valueChanged.connect(lambda v: self._set("reward_value", int(v)))
        f.addRow("Which", self.rvalue)
        f.addRow("Amount", self.ramount)
        self.rcount = QSpinBox()
        self.rcount.setRange(1, 99)
        self.rcount.valueChanged.connect(lambda v: self._set("reward_count", int(v)))
        f.addRow("How many", self.rcount)
        bl.addWidget(g)

        g = QGroupBox("When it shows")
        f = QFormLayout(g)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.prereq = QComboBox()
        _searchable(self.prereq)
        self.prereq.currentIndexChanged.connect(lambda _: self._set("prereq_quest1", int(self.prereq.currentData() or 0)))
        f.addRow("After the quest", self.prereq)
        self.flag = QSpinBox()
        self.flag.setRange(0, 99999)
        self.flag.setSpecialValueText("none")
        self.flag.setToolTip("A FlagListDataBase flag that must be set first (299 = chapter 2 cleared, 1699 = "
                             "post-game; the Database Editor lists them). 0 = none.")
        self.flag.valueChanged.connect(lambda v: self._set("req_flag1", int(v)))
        f.addRow("Needs the flag", self.flag)
        self.unlock = QComboBox()
        _searchable(self.unlock)
        self.unlock.currentIndexChanged.connect(lambda _: self._set("unlock_stage", int(self.unlock.currentData() or 0)))
        self.unlock.setToolTip("A stage the quest makes available (its stage-list flag), like the Overlord fights")
        f.addRow("Opens the stage", self.unlock)
        bl.addWidget(g)

        row = QHBoxLayout()
        self.b_save = QPushButton("💾 Save")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save)
        row.addWidget(self.b_save)
        self.b_discard = QPushButton("Discard changes")
        self.b_discard.clicked.connect(self.discard)
        row.addWidget(self.b_discard)
        row.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        row.addWidget(self.status)
        bl.addLayout(row)
        bl.addStretch(1)
        split.addWidget(scroll)
        split.setSizes([360, 900])
        lay.addWidget(split, 1)
        self.form = body
        self.form.setEnabled(False)
        self.svc.table_changed.connect(self._table_changed)

    # ------------------------------------------------------------------ data
    def on_show(self):
        if not self._populated:
            self._populated = True
            self._load_names()
            self._populate()

    def _load_names(self):
        self.char_names = char_names(self.svc)
        self.item_names = table_names(self.svc, "item.dat")
        self.skill_names = table_names(self.svc, "magic.dat")
        self.evility_names = table_names(self.svc, "Skill.dat")

    def _vanilla_rows(self):
        return len(self.svc.vanilla(QUEST).rows)

    def _populate(self):
        self.list.blockSignals(True)
        self.list.clear()
        t = self.svc.table(QUEST)
        nv = self._vanilla_rows()
        for i, r in enumerate(t.rows):
            if dbpatch.is_placeholder_quest(r):
                continue
            mine = i >= nv
            label = f"{r['name_EN'] or '(no title)'}   · {r['id']}" + ("  · yours" if mine else "") + \
                    ("  · request" if int(r["quest_kind"]) else "")
            it = QListWidgetItem(label)
            it.setData(ROLE, i)
            if mine:
                it.setForeground(Qt.GlobalColor.cyan)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._filter(self.search.text())
        self._fill_pickers()

    def _fill_pickers(self):
        t = self.svc.table(QUEST)
        for cb in (self.prereq, self.unlock):
            cb.blockSignals(True)
            cb.clear()
        self.prereq.addItem("(none)", 0)
        for r in t.rows:
            if not dbpatch.is_placeholder_quest(r):
                self.prereq.addItem(f"{r['name_EN']}  ({r['id']})", int(r["id"]))
        self.unlock.addItem("(none)", 0)
        try:
            for i, row in enumerate(self.svc.table("dungeon.dat").rows):
                rec = mapfile.DungeonRecord(bytes(row.raw))
                if rec.title_id and rec.map_id >= 100 and "(Demo)" not in rec.name():
                    self.unlock.addItem(f"{rec.name()}  (map{rec.map_id:05d})", int(rec.title_id))
        except Exception:
            pass
        for cb in (self.prereq, self.unlock):
            cb.blockSignals(False)

    def _filter(self, text):
        t = (text or "").lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _table_changed(self, member):
        if member == QUEST and self._populated:
            cur = self.row
            self._populate()
            if cur is not None and cur < self.svc.table(QUEST).rows.__len__():
                self._show(cur)

    def _r(self):
        rows = self.svc.table(QUEST).rows
        if self.row is None or self.row >= len(rows):
            return None
        return rows[self.row]

    def _pick(self, it, prev=None):
        if not it:
            return
        self._show(it.data(ROLE))

    def _show(self, idx):
        self.row = idx
        r = self._r()
        self._loading = True
        try:
            self.form.setEnabled(True)
            mine = idx >= self._vanilla_rows()
            self.b_del.setEnabled(mine)
            self.title.setText(f"{r['name_EN']}  ·  quest {r['id']}" + ("  ·  yours" if mine else ""))
            self.name.setText(r["name_EN"])
            self.client.setText(r["client_EN"])
            self.text.setPlainText("\n".join(x for x in (r[f"desc{k}_EN"] for k in range(1, 6)) if x))
            self.kind.setCurrentIndex(max(0, self.kind.findData(int(r["quest_kind"]))))
            self.important.setChecked(bool(r["important"]))
            cond = questcheck.objective_of(r)
            self.objective.set_cond(cond)
            t = int(r["cond_type"])
            self.obj_note.setText("" if t in (questcheck.CLEAR_STAGE, questcheck.DEFEAT) else
                                  f"Objective: {questinfo.objective(self.svc, r)} (a kind the picker doesn't make; "
                                  "it stays unless you pick a stage or enemies above; every field is in the "
                                  "Database Editor › Quest)")
            self.rtype.setCurrentIndex(max(0, self.rtype.findData(int(r["reward_type"]))))
            self._fill_reward_values(int(r["reward_type"]), int(r["reward_value"]))
            self.rcount.setValue(max(1, int(r["reward_count"])))
            k = self.prereq.findData(int(r["prereq_quest1"]))
            self.prereq.setCurrentIndex(max(0, k))
            self.flag.setValue(int(r["req_flag1"]))
            k = self.unlock.findData(int(r["unlock_stage"]))
            self.unlock.setCurrentIndex(max(0, k))
            self._words()
        finally:
            self._loading = False

    def _words(self):
        r = self._r()
        if r is not None:
            self.words.setText(questinfo.describe(self.svc, r))
        else:
            self.words.setText("")
        self.status.setText("● unsaved changes" if self.svc.is_dirty(QUEST) else "")

    def _fill_reward_values(self, rtype, value):
        self.rvalue.blockSignals(True)
        self.rvalue.clear()
        names = None
        if rtype == 2:
            names = self.item_names
        elif rtype == 3:
            names = self.evility_names
        elif rtype == 4:
            names = self.skill_names
        elif rtype in (5, 6):
            names = {k: v for k, v in self.char_names.items() if (rtype == 6) == (1000 <= k < 3000)}
        amount = names is None
        self.rvalue.setVisible(not amount)
        self.ramount.setVisible(amount)
        if names is not None:
            for k, n in sorted(names.items()):
                self.rvalue.addItem(f"{n}  ({k})", k)
            k = self.rvalue.findData(value)
            if k < 0 and value:
                self.rvalue.addItem(str(value), value)
                k = self.rvalue.count() - 1
            self.rvalue.setCurrentIndex(max(0, k))
        else:
            self.ramount.blockSignals(True)
            self.ramount.setValue(int(value))
            self.ramount.blockSignals(False)
        self.rvalue.blockSignals(False)

    # ------------------------------------------------------------------ edits
    def _set(self, field, value):
        r = self._r()
        if r is None or self._loading:
            return
        try:
            if r[field] == value:
                return
            r.set(field, value)
        except Exception as e:
            QMessageBox.warning(self, "Quest", str(e))
            return
        self.svc.mark_dirty(QUEST)
        self._words()

    def _set_text(self, field, value):
        r = self._r()
        if r is None or self._loading:
            return
        changed = False
        for lang in ("JP", "EN", "FR", "CHN", "KOR"):
            f = f"{field}_{lang}"
            if f in r and r[f] != value:
                r.set(f, value, truncate=True)
                changed = True
        if changed:
            self.svc.mark_dirty(QUEST)
            self._words()
            if field == "name":
                it = self.list.currentItem()
                if it:
                    it.setText(f"{value}   · {r['id']}" + ("  · yours" if self.row >= self._vanilla_rows() else ""))

    def _text_changed(self):
        r = self._r()
        if r is None or self._loading:
            return
        lines = dbpatch.quest_lines(self.text.toPlainText())
        changed = False
        for k, line in enumerate(lines, 1):
            for lang in ("JP", "EN", "FR", "CHN", "KOR"):
                f = f"desc{k}_{lang}"
                if f in r and r[f] != line:
                    r.set(f, line, truncate=True)
                    changed = True
        if changed:
            self.svc.mark_dirty(QUEST)
            self.status.setText("● unsaved changes")

    def _objective_changed(self, *_):
        r = self._r()
        if r is None or self._loading:
            return
        cond = self.objective.cond()
        if cond != questcheck.objective_of(r) and self.objective.goal.currentData() in (questcheck.CLEAR_STAGE,
                                                                                         questcheck.DEFEAT):
            questcheck.set_objective(r, cond)
            self.svc.mark_dirty(QUEST)
            self.obj_note.setText("")
            self._words()

    def _reward_type_changed(self, *_):
        r = self._r()
        if r is None or self._loading:
            return
        t = int(self.rtype.currentData())
        if int(r["reward_type"]) != t:
            r.set("reward_type", t)
            default = {1: 1000, 7: 1}.get(t, 0)
            r.set("reward_value", default)
            self.svc.mark_dirty(QUEST)
        self._loading = True
        self._fill_reward_values(t, int(r["reward_value"]))
        self._loading = False
        self._words()

    def _reward_value_changed(self, *_):
        if self._loading:
            return
        v = self.rvalue.currentData()
        if v is not None:
            self._set("reward_value", int(v))

    # ------------------------------------------------------------------ actions
    def save(self):
        if not self.svc.is_dirty(QUEST):
            self.status.setText("nothing to save")
            return
        r = self._r()
        name = r["name_EN"] if r is not None else "quest"
        if self.svc.commit(QUEST, self, suggest=f"Quest: {name}", category="quests") is False:
            return
        self.ws.log(f"Quests saved into {self.svc.saved_text()}")
        if self.row is not None and self.row >= len(self.svc.table(QUEST).rows):
            self.row = None
        self._words()

    def discard(self):
        if self.svc.is_dirty(QUEST):
            self.svc.discard(QUEST)
        self._populate()
        if self.row is not None and self.row < len(self.svc.table(QUEST).rows):
            self._show(self.row)

    def new_quest(self):
        t = self.svc.table(QUEST)
        src = t.index_of(1) if hasattr(t, "index_of") else 0
        every = self.ws.mods.all_mods()
        qr = t.add_row(copy_from=src if src >= 0 else 0)
        qid = dbpatch.new_quest_id(t, every)
        qr.set("id", qid)
        for lang in ("JP", "EN", "FR", "CHN", "KOR"):
            for fld, val in (("name", "My Quest"), ("client", "A Netherworld resident")):
                if f"{fld}_{lang}" in qr:
                    qr.set(f"{fld}_{lang}", val)
            lines = dbpatch.quest_lines("Would you do something for me?")
            for k in range(1, 6):
                if f"desc{k}_{lang}" in qr:
                    qr.set(f"desc{k}_{lang}", lines[k - 1])
        qr.set("sort_order", dbpatch.free_quest_slot(t, exclude=qr, reserved=dbpatch.mod_quest_slots(every)))
        qr.set("quest_kind", 0)
        qr.set("important", 0)
        qr.set("reward_type", 1)
        qr.set("reward_value", 1000)
        qr.set("reward_count", 1)
        for f in ("prereq_quest1", "prereq_quest2", "prereq_quest3", "prereq_quest4", "req_flag1", "req_flag2",
                  "req_flag3", "req_flag4", "unlock_stage", "unlock_stage2"):
            if f in qr:
                qr.set(f, 0)
        questcheck.set_objective(qr, {"type": questcheck.CLEAR_STAGE, "target": 101, "count": 1})
        self.svc.mark_dirty(QUEST)
        self._populate()
        idx = len(t.rows) - 1
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE) == idx:
                self.list.setCurrentRow(i)
                break
        self.ws.log(f"New quest {qid} 'My Quest' (progress slot {qr['sort_order']}): fill it in and Save")

    def delete_quest(self):
        r = self._r()
        if r is None or self.row < self._vanilla_rows():
            return
        qid = int(r["id"])
        owner = self.svc.row_owner(QUEST, self.row)
        if owner is None:
            if self.svc.is_dirty(QUEST):          # not saved yet: just drop the working row
                self.svc.discard(QUEST)
                self._populate()
                return
            QMessageBox.information(self, "Delete", "This quest is in no mod of yours.")
            return
        who = ""
        try:
            if int(r["reward_type"]) in (5, 6):
                who = self.char_names.get(int(r["reward_value"]), "")
        except Exception:
            pass
        text = f"Delete the quest “{r['name_EN']}” ({qid}) from the mod '{owner.name}'?"
        if who:
            text += f"\n\nIt gives {who}: without a quest that character can't be recruited in game."
        if QMessageBox.question(self, "Delete quest", text) != QMessageBox.StandardButton.Yes:
            return
        try:
            patch = owner.load_patch("db", "Quest.dat.json") or {}
            added = patch.get("added") or []
            keep = [x for x in added if int(x.get("id", -1)) != qid]
            patch["added"] = keep
            owner.save_patch("db", "Quest.dat.json", patch if (keep or patch.get("rows")) else None)
        except Exception as e:
            error_box(self, "Delete quest", e)
            return
        self.svc.discard(QUEST)
        self.svc.reload(keep_unsaved=True)
        self.row = None
        self.form.setEnabled(False)
        self.title.setText("Pick a quest")
        self.words.setText("")
        self._populate()
        self.ws.log(f"Deleted quest {qid} from '{owner.name}'")
