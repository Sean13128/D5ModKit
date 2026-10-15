"""Dialogue & Text: browse / search / edit every conversation in talk.dat, add or remove lines."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QComboBox, QTabWidget, QPlainTextEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QMessageBox, QInputDialog, QCheckBox, QApplication,
                             QAbstractItemView, QLineEdit, QFormLayout, QGroupBox)

from d5lib import talk, textpatch
from ..common import PageHeader, SearchBox, error_box, info_box
from ..dbservice import get_service, char_names
from .stages import SearchCombo

LANG_LABELS = [("en", "English"), ("jp", "Japanese"), ("fr", "French"), ("zh", "Chinese"), ("ko", "Korean")]
TEXT_OPS = set(talk.LANG_BYTES)
END_OPS = (0x02, 0x03)


def message_spans(rec):
    """[(start, end)] index ranges in rec.code; each span ends with a page/msg_end op and contains text."""
    spans, start, has_text = [], 0, False
    for i, ins in enumerate(rec.code):
        if ins.is_text:
            has_text = True
        if ins.op in END_OPS or ins.op == 0x14 or ins.is_option:
            if has_text:
                spans.append((start, i))
            start, has_text = i + 1, False
    if has_text:
        spans.append((start, len(rec.code) - 1))
    return spans


def span_speaker(rec, start):
    sp = None
    for ins in rec.code[:start + 1]:
        if ins.op == 0x05:
            sp = ins.args[0]
    for ins in rec.code[start:]:
        if ins.is_text:
            break
        if ins.op == 0x05:
            sp = ins.args[0]
    return sp


def span_lines(rec, s, e):
    """list of {lang: Ins} for the text lines in a span."""
    lines, cur = [], {}
    for ins in rec.code[s:e + 1]:
        if ins.is_text:
            if ins.lang in cur:
                lines.append(cur)
                cur = {}
            cur[ins.lang] = ins
        elif cur:
            lines.append(cur)
            cur = {}
    if cur:
        lines.append(cur)
    return lines


class DialoguePage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.svc = get_service(ws)
        self.vanilla = None
        self.tf = None
        self.rec_index = None
        self.dirty = False
        self._names = None

        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Dialogue & Text",
                                 "Every conversation in the game. Search by text or character, edit lines, add new "
                                 "lines, or rewrite a whole scene. Each line has 5 languages; English is used when you "
                                 "play in English. Tip: Find & Replace can rename something across the whole game."))
        top = QHBoxLayout()
        self.search = SearchBox("Search all dialogue (any language)…")
        self.search.returnPressed.connect(self._search)
        top.addWidget(self.search, 1)
        b = QPushButton("Search")
        b.clicked.connect(self._search)
        top.addWidget(b)
        self.only_mod = QCheckBox("Edited only")
        self.only_mod.toggled.connect(self._search)
        top.addWidget(self.only_mod)
        b = QPushButton("Find && Replace…")
        b.clicked.connect(self.find_replace)
        top.addWidget(b)
        lay.addLayout(top)

        split = QSplitter()
        self.recs = QListWidget()
        self.recs.currentItemChanged.connect(self._pick)
        split.addWidget(self.recs)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Pick a conversation")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        rl.addWidget(self.title)
        self.tabs = QTabWidget()
        rl.addWidget(self.tabs, 1)

        # --- messages tab
        mw = QWidget()
        ml = QVBoxLayout(mw)
        ml.setContentsMargins(0, 4, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show language:"))
        self.lang = QComboBox()
        for code, lab in LANG_LABELS:
            self.lang.addItem(lab, code)
        self.lang.currentIndexChanged.connect(self._fill_messages)
        row.addWidget(self.lang)
        row.addStretch(1)
        ml.addLayout(row)
        self.msgs = QTableWidget(0, 2)
        self.msgs.setHorizontalHeaderLabels(["Speaker", "Text"])
        self.msgs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.msgs.setColumnWidth(0, 190)
        self.msgs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.msgs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.msgs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.msgs.setWordWrap(True)
        self.msgs.verticalHeader().setVisible(False)
        self.msgs.currentCellChanged.connect(lambda r, *a: self._edit_message(r))
        ml.addWidget(self.msgs, 3)

        ed = QGroupBox("Edit selected message")
        el = QVBoxLayout(ed)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Speaker:"))
        self.speaker_box = QWidget()
        self.speaker_lay = QHBoxLayout(self.speaker_box)
        self.speaker_lay.setContentsMargins(0, 0, 0, 0)
        srow.addWidget(self.speaker_box, 1)
        el.addLayout(srow)
        self.lang_tabs = QTabWidget()
        self.editors = {}
        for code, lab in LANG_LABELS:
            e = QPlainTextEdit()
            e.setPlaceholderText("One text line per row (a box fits about 3 lines). Tags like <c緑>name</c> color text.")
            e.setFont(QFont("Segoe UI", 10))
            self.editors[code] = e
            self.lang_tabs.addTab(e, lab)
        el.addWidget(self.lang_tabs)
        brow = QHBoxLayout()
        for text, fn, tip in [("✔ Apply text", self.apply_text, "Store the edited text of this message"),
                              ("Copy English to all languages", self.copy_en, ""),
                              ("➕ Add message after", self.add_after, "Insert a new message box after this one"),
                              ("🗑 Delete message", self.delete_msg, "Remove this message box's text")]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            brow.addWidget(b)
        brow.addStretch(1)
        el.addLayout(brow)
        ml.addWidget(ed, 2)
        self.tabs.addTab(mw, "💬 Messages")

        # --- raw tab
        rw = QWidget()
        rwl = QVBoxLayout(rw)
        note = QLabel("Advanced: the full scene script (portraits, voices, flags, choices…). Edit and press Apply. "
                      "Text is in JSON quotes; each opcode is documented in d5lib/talk.py.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        rwl.addWidget(note)
        self.raw = QPlainTextEdit()
        self.raw.setFont(QFont("Consolas", 9))
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        rwl.addWidget(self.raw, 1)
        b = QPushButton("Apply script changes")
        b.clicked.connect(self.apply_raw)
        rwl.addWidget(b)
        self.tabs.addTab(rw, "🧾 Script (advanced)")
        self.tabs.currentChanged.connect(lambda i: i == 1 and self._fill_raw())

        bot = QHBoxLayout()
        b = QPushButton("💾 Save")
        b.setObjectName("primary")
        b.clicked.connect(self.save)
        bot.addWidget(b)
        for text, fn in [("Revert this conversation", self.revert_record), ("Discard unsaved", self.discard),
                         ("New conversation…", self.new_record)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            bot.addWidget(b)
        bot.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        bot.addWidget(self.status)
        rl.addLayout(bot)
        split.addWidget(right)
        split.setSizes([420, 1000])
        lay.addWidget(split, 1)
        self._loaded = False
        ws.active_mod_changed.connect(lambda _: self._loaded and self.load())

    # ================================================================== loading
    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.load()
            if self.recs.currentRow() < 0 and self.recs.count():
                self.recs.setCurrentRow(0)        # never open on an empty editor

    def names(self):
        if self._names is None:
            try:
                self._names = char_names(self.svc)
            except Exception:
                self._names = {}
        return self._names

    def speaker_name(self, sp):
        if sp is None or sp == 0xFFFF:
            return "—"
        if 1 <= sp <= 9:
            return f"Party member {sp}"
        return self.names().get(sp, f"#{sp}").split(" (")[0]

    def load(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.vanilla = talk.TalkFile.from_bytes(self.ws.fs.read(textpatch.TALK))
            self.tf = talk.TalkFile.from_bytes(self.ws.fs.read(textpatch.TALK))
            mod = self.ws.active_mod
            if mod:
                patch = mod.load_patch("text", "talk.json")
                if patch:
                    textpatch.apply(self.tf, patch)
        finally:
            QApplication.restoreOverrideCursor()
        self.dirty = False
        self._set_status()
        self._search()

    def _is_edited(self, i):
        if i >= len(self.vanilla.records):
            return True
        a, b = self.vanilla.records[i], self.tf.records[i]
        return a.code_bytes() != b.code_bytes() or a.header_bytes(0) != b.header_bytes(0)

    def _label(self, i, r):
        en = next((x for x in r.texts("en") if x.strip()), "")
        kind = f"talk {r.talk_id}" if r.talk_id else f"stage {r.key2} phase {r.key3}"
        return f"#{i}  [{kind}]  {en[:70]}"

    def _search(self):
        if not self.tf:
            return
        q = self.search.text().strip().lower()
        self.recs.clear()
        shown = 0
        for i, r in enumerate(self.tf.records):
            if self.only_mod.isChecked() and not self._is_edited(i):
                continue
            if q:
                hay = " ".join(ins.text for ins in r.code if ins.is_text).lower()
                if q not in hay and q != str(r.talk_id):
                    continue
            elif not r.texts("en"):
                continue
            it = QListWidgetItem(self._label(i, r))
            it.setData(Qt.ItemDataRole.UserRole, i)
            if self._is_edited(i):
                it.setForeground(QBrush(QColor("#ff4f8b")))
            self.recs.addItem(it)
            shown += 1
            if shown > 3000:
                break
        self.status.setText(f"{shown} conversation(s)" + (" (first 3000)" if shown > 3000 else ""))

    def _pick(self, it, prev=None):
        if not it:
            return
        self.rec_index = it.data(Qt.ItemDataRole.UserRole)
        r = self.tf.records[self.rec_index]
        cond = []
        if r.flags_on:
            cond.append("needs flags " + ",".join(map(str, r.flags_on)))
        if r.flags_off:
            cond.append("not after flags " + ",".join(map(str, r.flags_off)))
        kind = f"Talk #{r.talk_id}" if r.talk_id else f"Stage {r.key2} event (phase {r.key3})"
        self.title.setText(f"Record {self.rec_index}: {kind}" + (f"  —  {'; '.join(cond)}" if cond else ""))
        self._fill_messages()
        if self.tabs.currentIndex() == 1:
            self._fill_raw()

    def _fill_messages(self, *a):
        self.msgs.setRowCount(0)
        if self.rec_index is None:
            return
        r = self.tf.records[self.rec_index]
        lang = self.lang.currentData()
        self.spans = message_spans(r)
        self.msgs.setRowCount(len(self.spans))
        for row, (s, e) in enumerate(self.spans):
            sp = span_speaker(r, s)
            text = "\n".join(l[lang].text for l in span_lines(r, s, e) if lang in l)
            self.msgs.setItem(row, 0, QTableWidgetItem(self.speaker_name(sp)))
            self.msgs.setItem(row, 1, QTableWidgetItem(text))
        self.msgs.resizeRowsToContents()
        if self.spans:
            self.msgs.selectRow(0)

    def _edit_message(self, row):
        if self.rec_index is None or row < 0 or row >= len(getattr(self, "spans", [])):
            return
        r = self.tf.records[self.rec_index]
        s, e = self.spans[row]
        lines = span_lines(r, s, e)
        for code, ed in self.editors.items():
            ed.setPlainText("\n".join(l[code].text for l in lines if code in l))
        # speaker selector
        while self.speaker_lay.count():
            w = self.speaker_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
        if not hasattr(self, "_speaker_choices"):
            self._speaker_choices = [(k, f"Party member {k}") for k in range(1, 10)] + sorted(self.names().items())
        self.sp_combo = SearchCombo(self._speaker_choices)
        self.sp_combo.set_value(span_speaker(r, s) or 0)
        self.speaker_lay.addWidget(self.sp_combo, 1)
        b = QPushButton("Set speaker")
        b.setToolTip("Sets who speaks from this message on (name plate)")
        b.clicked.connect(lambda: self._set_speaker(row))
        self.speaker_lay.addWidget(b)

    # ================================================================== editing
    def _changed(self):
        self.dirty = True
        self._set_status()
        cur = self.msgs.currentRow()
        self._fill_messages()
        if 0 <= cur < self.msgs.rowCount():
            self.msgs.selectRow(cur)
        it = self.recs.currentItem()
        if it:
            it.setText(self._label(self.rec_index, self.tf.records[self.rec_index]))
            it.setForeground(QBrush(QColor("#ff4f8b")))

    def _set_status(self):
        self.status.setText("● unsaved changes" if self.dirty else "")

    def apply_text(self):
        row = self.msgs.currentRow()
        if self.rec_index is None or row < 0:
            return
        r = self.tf.records[self.rec_index]
        s, e = self.spans[row]
        new_lines = {code: ed.toPlainText().split("\n") for code, ed in self.editors.items()}
        n = max(len(v) for v in new_lines.values())
        fallback = new_lines["en"]
        # remove old text instructions in the span, insert new ones where the first text was
        first = next(i for i in range(s, e + 1) if r.code[i].is_text)
        keep = [ins for ins in r.code[s:e + 1] if not ins.is_text]
        new_text = []
        for k in range(n):
            for code, _ in [(c, None) for c in talk.LANGS]:
                src = new_lines.get(code) or fallback
                txt = src[k] if k < len(src) else (fallback[k] if k < len(fallback) else "")
                new_text.append(talk.Ins.text_line(code, txt))
        pre = [ins for ins in r.code[s:first] if not ins.is_text]
        post = [ins for ins in r.code[first:e + 1] if not ins.is_text]
        r.code[s:e + 1] = pre + new_text + post
        self._changed()

    def copy_en(self):
        en = self.editors["en"].toPlainText()
        for code, ed in self.editors.items():
            if code != "en":
                ed.setPlainText(en)

    def _set_speaker(self, row):
        r = self.tf.records[self.rec_index]
        s, e = self.spans[row]
        v = self.sp_combo.value()
        # replace a speaker op inside the span before the first text, else insert one
        first = next(i for i in range(s, e + 1) if r.code[i].is_text)
        for i in range(s, first):
            if r.code[i].op == 0x05:
                r.code[i].args[0] = v
                break
        else:
            r.code.insert(first, talk.Ins(0x05, [v]))
        self._changed()

    def add_after(self):
        row = self.msgs.currentRow()
        if self.rec_index is None or row < 0:
            QMessageBox.information(self, "Add message", "Select the message after which the new one goes.")
            return
        text, ok = QInputDialog.getMultiLineText(self, "New message",
                                                 "Text (English; up to ~3 short lines). "
                                                 "It is copied to all languages — translate later if you like:")
        if not ok or not text.strip():
            return
        r = self.tf.records[self.rec_index]
        s, e = self.spans[row]
        sp = span_speaker(r, s)
        lines = [{"en": ln} for ln in text.split("\n")]
        ins = talk.TalkFile.build_message(lines, speaker=sp, window=None)
        r.code[e + 1:e + 1] = ins
        self._changed()
        self.msgs.selectRow(row + 1)

    def delete_msg(self):
        row = self.msgs.currentRow()
        if self.rec_index is None or row < 0:
            return
        if QMessageBox.question(self, "Delete message", "Remove the text of this message box?") \
                != QMessageBox.StandardButton.Yes:
            return
        r = self.tf.records[self.rec_index]
        s, e = self.spans[row]
        end = r.code[e]
        r.code[s:e + 1] = [ins for ins in r.code[s:e] if not ins.is_text and ins.op not in END_OPS]
        self._changed()

    def _fill_raw(self):
        if self.rec_index is None:
            return
        self.raw.setPlainText(textpatch.record_text(self.tf, self.tf.records[self.rec_index]))

    def apply_raw(self):
        if self.rec_index is None:
            return
        try:
            self.tf.records[self.rec_index] = textpatch.parse_record(self.raw.toPlainText())
        except Exception as e:
            error_box(self, "Script error", e)
            return
        self._changed()

    def new_record(self):
        tid, ok = QInputDialog.getInt(self, "New conversation",
                                      "Talk id for the new conversation (scripts start conversations by this id):",
                                      max(r.talk_id for r in self.tf.records) + 1, 1, 2 ** 31 - 1)
        if not ok:
            return
        rec = talk.TalkRecord(tid, 0, 0)
        rec.code = talk.TalkFile.build_message({"en": "New line of dialogue."}) + [talk.Ins(0xFF)] \
            if 0xFF in talk.OPS else talk.TalkFile.build_message({"en": "New line of dialogue."})
        self.tf.add_record(rec)
        self.dirty = True
        self._set_status()
        self.search.setText(str(tid))
        self._search()
        info_box(self, "New conversation",
                 f"Added conversation with talk id {tid}. It plays when a script or event calls this id "
                 "(see the Script tab of an existing scene for how talks are started).")

    # ================================================================== save
    def save(self):
        mod = self.ws.require_mod(self)
        if not mod:
            return
        try:
            self.tf.to_bytes()
            patch = textpatch.diff(self.vanilla, self.tf)
            mod.save_patch("text", "talk.json", patch or None)
            self.dirty = False
            self._set_status()
            self.ws.file_changed.emit(textpatch.TALK)
            n = len(patch.get("records", {})) + len(patch.get("added", []))
            self.ws.log(f"Saved dialogue ({n} conversation(s) changed) to mod '{mod.name}'")
        except Exception as e:
            error_box(self, "Save failed", e)

    def revert_record(self):
        if self.rec_index is None or self.rec_index >= len(self.vanilla.records):
            return
        self.tf.records[self.rec_index] = textpatch.parse_record(
            textpatch.record_text(self.vanilla, self.vanilla.records[self.rec_index]))
        self._changed()

    def discard(self):
        self.load()

    def find_replace(self):
        find, ok = QInputDialog.getText(self, "Find & Replace", "Find (case-sensitive):")
        if not ok or not find:
            return
        rep, ok = QInputDialog.getText(self, "Find & Replace", f"Replace '{find}' with:")
        if not ok:
            return
        langs, ok = QInputDialog.getItem(self, "Find & Replace", "In which language?",
                                         ["English only", "All languages"], 0, False)
        if not ok:
            return
        n = 0
        recs = 0
        for r in self.tf.records:
            hit = False
            for ins in r.code:
                if ins.is_text and (langs == "All languages" or ins.lang == "en") and find in ins.text:
                    n += ins.text.count(find)
                    ins.text = ins.text.replace(find, rep)
                    hit = True
            recs += hit
        if n:
            self.dirty = True
            self._set_status()
            self._search()
        info_box(self, "Find & Replace", f"Replaced {n} occurrence(s) in {recs} conversation(s).\n"
                                         "Press Save to store them in your mod.")
