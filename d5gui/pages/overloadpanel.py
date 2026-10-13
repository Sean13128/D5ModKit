"""Overloads on the Skills page: name and description, what it does (the code of a game Overload, or numbers of its
own), its title banner and who has it; new Overloads.  Backend: d5lib/overloads.py (docs/OVERLOADS.md).

An Overload is listed on the Skills page as skill skills.OVL_KEY + its id, so its animation is edited there like any
skill's (Timeline editor, Choreography, Use animation of…)."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel, QLineEdit,
                             QPushButton, QComboBox, QSpinBox, QListWidget, QListWidgetItem, QDialog,
                             QDialogButtonBox, QColorDialog, QFileDialog, QMessageBox, QScrollArea, QApplication)

from d5lib import overloads, skills
from ..common import error_box, info_box, pil_to_pixmap
from ..dbservice import char_names
from .stages import SearchCombo

TABLE, MAGIC, CHAR = "OverlordSkill.dat", "magic.dat", "char.dat"
FORMULAS = [(2, "Physical attack (ATK)"), (3, "Magic attack (INT)"), (4, "Heal"), (6, "Ailment / stat down")]
ELEMENTS = [(0, "None"), (1, "Fire"), (2, "Wind (lightning)"), (3, "Ice"), (4, "Star")]
AREAS = [(1000, "The user only"), (31100, "Within 3 panels (like Devouring Kris)"),
         (31000, "Within 5 panels (like Ground Zero Wolf)"), (30000, "The whole map (like Comet Disaster)")]
# game Overloads whose numbers are a good start for one of its own (damage, drain, heal, ailment)
NUMBER_SOURCES = [109, 107, 8, 200, 16, 104, 105, 102, 18, 17]


def ovl_of(sid):
    return int(sid) - skills.OVL_KEY


class NewOverloadDialog(QDialog):
    def __init__(self, parent, game_names):
        super().__init__(parent)
        self.setWindowTitle("New Overload")
        f = QFormLayout(self)
        self.name = QLineEdit("New Overload")
        f.addRow("Name", self.name)
        self.desc = [QLineEdit() for _ in range(3)]
        for k, e in enumerate(self.desc):
            f.addRow(f"Description line {k + 1}", e)
        self.like = QComboBox()
        self.like.addItem("Nothing special: numbers of its own (damage, drain, heal or ailments)", 0)
        for o, n in game_names:
            self.like.addItem(f"Works like {n} ({o})", o)
        self.like.setCurrentIndex(1)
        f.addRow("What it does", self.like)
        self.anim = QComboBox()
        for o, n in game_names:
            self.anim.addItem(f"{n} ({o})", o)
        f.addRow("Animation (a copy)", self.anim)
        self.like.currentIndexChanged.connect(self._sync)
        note = QLabel("A game Overload's code (giant, extra actions, revive …) is what makes it special; an Overload "
                      "with numbers of its own hits its area with its power, element and effects. Its name gets a "
                      "title banner of its own. Give it to characters afterwards (here or on Characters & Classes).")
        note.setWordWrap(True)
        note.setObjectName("muted")
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._sync()

    def _sync(self):
        o = self.like.currentData()
        k = self.anim.findData(o if o else 109)
        if k >= 0:
            self.anim.setCurrentIndex(k)


class OverloadPanel(QScrollArea):
    changed = pyqtSignal()                  # the mod's Overload data changed (the page reloads)

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.ws = page.ws
        self.svc = page.svc
        self.ovl = None
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        lay = QVBoxLayout(body)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        self.head.setObjectName("muted")
        lay.addWidget(self.head)

        g = QGroupBox("Name && description")
        f = QFormLayout(g)
        self.name = QLineEdit()
        f.addRow("Name", self.name)
        self.desc = [QLineEdit() for _ in range(3)]
        for k, e in enumerate(self.desc):
            f.addRow(f"Line {k + 1}", e)
        b = QPushButton("💾 Save name && description")
        b.clicked.connect(self.save_text)
        f.addRow(b)
        lay.addWidget(g)

        g = QGroupBox("What it does")
        f = QFormLayout(g)
        self.like = QComboBox()
        self.like.setToolTip("The game Overload whose code runs (giant, extra actions, revive …), or nothing special: "
                             "then it hits with numbers of its own")
        f.addRow("Works like", self.like)
        row = QHBoxLayout()
        self.like_btn = QPushButton("Apply")
        self.like_btn.clicked.connect(self.save_like)
        row.addWidget(self.like_btn)
        row.addStretch(1)
        f.addRow(row)
        self.numbers_note = QLabel("")
        self.numbers_note.setWordWrap(True)
        self.numbers_note.setObjectName("muted")
        f.addRow(self.numbers_note)
        row = QHBoxLayout()
        self.own_from = QComboBox()
        row.addWidget(self.own_from, 1)
        self.own_btn = QPushButton("Give it numbers of its own")
        self.own_btn.clicked.connect(self.own_numbers)
        row.addWidget(self.own_btn)
        self.drop_btn = QPushButton("Use the numbers of the Overload it works like")
        self.drop_btn.clicked.connect(self.drop_numbers)
        row.addWidget(self.drop_btn)
        f.addRow("Numbers", row)
        self.formula = QComboBox()
        for v, t in FORMULAS:
            self.formula.addItem(t, v)
        f.addRow("Kind", self.formula)
        self.power = QSpinBox()
        self.power.setRange(1, 9999)
        self.power.setSuffix(" %")
        f.addRow("Power", self.power)
        self.element = QComboBox()
        for v, t in ELEMENTS:
            self.element.addItem(t, v)
        f.addRow("Element", self.element)
        self.area = QComboBox()
        for v, t in AREAS:
            self.area.addItem(t, v)
        self.area.setEditable(False)
        f.addRow("Area", self.area)
        self.effects = QLineEdit()
        self.effects.setToolTip("Up to 6 effects as type:value, e.g. 1:300 (damage +300 %), 21:100 (Poison 100 %), "
                                "11:-50 (ATK -50 %), 111:50 + 106:1 + 107:100 (steal 50 % SP) — see magic.dat's "
                                "effect types in the Database editor")
        f.addRow("Effects", self.effects)
        self.save_num_btn = QPushButton("💾 Save numbers")
        self.save_num_btn.clicked.connect(self.save_numbers)
        f.addRow(self.save_num_btn)
        lay.addWidget(g)

        g = QGroupBox("Title banner")
        f = QFormLayout(g)
        self.style = QComboBox()
        self.style.setToolTip("The banner (lightning bar, colours) of this game Overload, with this Overload's name")
        f.addRow("Style of", self.style)
        row = QHBoxLayout()
        self.top_btn = QPushButton("Top colour")
        self.top_btn.clicked.connect(lambda: self.pick_color(0))
        self.bot_btn = QPushButton("Bottom colour")
        self.bot_btn.clicked.connect(lambda: self.pick_color(1))
        b2 = QPushButton("Style's colours")
        b2.clicked.connect(self.style_colors)
        for w in (self.top_btn, self.bot_btn, b2):
            row.addWidget(w)
        row.addStretch(1)
        f.addRow("Name colours", row)
        row = QHBoxLayout()
        b3 = QPushButton("🖼 Own picture…")
        b3.setToolTip("A picture of the name instead (any size; fitted to the banner's height, transparent "
                      "background)")
        b3.clicked.connect(self.choose_picture)
        b4 = QPushButton("Remove picture")
        b4.clicked.connect(lambda: self.save_banner(picture=""))
        row.addWidget(b3)
        row.addWidget(b4)
        row.addStretch(1)
        f.addRow("Picture", row)
        self.preview = QLabel()
        self.preview.setMinimumHeight(90)
        self.preview.setStyleSheet("background: #2a1830;")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f.addRow(self.preview)
        b5 = QPushButton("💾 Save banner")
        b5.clicked.connect(lambda: self.save_banner())
        f.addRow(b5)
        lay.addWidget(g)

        g = QGroupBox("Who has it")
        v = QVBoxLayout(g)
        self.who = QListWidget()
        self.who.setMaximumHeight(140)
        v.addWidget(self.who)
        row = QHBoxLayout()
        b6 = QPushButton("➕ Give to character / class…")
        b6.setObjectName("primary")
        b6.clicked.connect(self.give)
        b7 = QPushButton("➖ Take from the selected one")
        b7.clicked.connect(self.take)
        row.addWidget(b6)
        row.addWidget(b7)
        row.addStretch(1)
        v.addLayout(row)
        lay.addWidget(g)

        row = QHBoxLayout()
        self.del_btn = QPushButton("🗑 Delete this Overload")
        self.del_btn.clicked.connect(self.delete)
        self.reset_btn = QPushButton("↺ Undo the active mod's changes")
        self.reset_btn.clicked.connect(self.reset)
        row.addWidget(self.del_btn)
        row.addWidget(self.reset_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.colors = None

    # ------------------------------------------------------------------ data
    def game_names(self):
        t = self.svc.vanilla(TABLE)
        return [(int(r["id"]), r["name_EN"]) for r in t.rows if overloads.is_game_overload(int(r["id"]))]

    def names(self):
        return {int(r["id"]): r["name_EN"] for r in self.svc.table(TABLE).rows}

    def mods(self):
        return self.page.mods()

    def info(self):
        return overloads.info(self.ws.fs, self.mods(), self.ovl)

    def magic_of(self, ovl):
        """(magic id, own numbers?) of an Overload, as the mods leave it"""
        e = overloads.merged(self.mods()).get(int(ovl), {})
        return overloads.magic_of(e, int(ovl)) if (e or overloads.is_game_overload(ovl)) else None, \
            bool(e.get("skill"))

    def show_overload(self, ovl):
        self.ovl = int(ovl)
        inf = self.info()
        game = self.game_names()
        names = dict(game)
        for cb, first in ((self.like, "Nothing special: numbers of its own"), (self.style, None),
                          (self.own_from, None)):
            cb.blockSignals(True)
            cb.clear()
            if first:
                cb.addItem(first, 0)
            for o, n in game:
                if cb is self.own_from and o not in NUMBER_SOURCES:
                    continue
                cb.addItem(f"{n} ({o})" if cb is not self.own_from else f"copy of {n}'s ({o})", o)
            cb.blockSignals(False)
        self.like.setCurrentIndex(max(0, self.like.findData(inf["like"])))
        self.style.setCurrentIndex(max(0, self.style.findData(inf["banner"] or inf["like"] or 1)))
        self.name.setText(inf["name"])
        for k, e in enumerate(self.desc):
            e.setText(inf["desc"][k])
        kind = "a game Overload" if inf["game"] else "a new Overload"
        what = (f"its own numbers (skill {inf['magic']})" if inf["own_numbers"] else
                f"works like {names.get(inf['like'], inf['like'])}" if inf["like"] else "—")
        self.head.setText(f"Overload {self.ovl} — {kind}, {what}. Its animation is on the Timeline editor and "
                          "Choreography tabs; ▶ Preview in game shows it once the mod is installed.")
        own = inf["own_numbers"]
        self.numbers_note.setText(
            "It hits with the numbers below (its own skill row)." if own else
            "It uses the numbers of the Overload it works like. Give it numbers of its own to change its power, "
            "element, area and effects without changing any other Overload.")
        self.drop_btn.setVisible(own)
        self.own_btn.setVisible(not own)
        self.own_from.setVisible(not own)
        for w in (self.formula, self.power, self.element, self.area, self.effects, self.save_num_btn):
            w.setEnabled(own)
        row = next((r for r in self.svc.table(MAGIC).rows if int(r["id"]) == int(inf["magic"] or 0)), None)
        if row is not None:
            self.formula.setCurrentIndex(max(0, self.formula.findData(int(row["formula"]))))
            self.power.setValue(int(row["power_lv1"]))
            self.element.setCurrentIndex(max(0, self.element.findData(int(row["element"]))))
            am = int(row["attack_map"])
            if self.area.findData(am) < 0:
                self.area.addItem(f"Area shape {am}", am)
            self.area.setCurrentIndex(self.area.findData(am))
            effs = [(row[f"effect{n}_type"], row[f"effect{n}_value"]) for n in range(1, 7) if row[f"effect{n}_type"]]
            self.effects.setText(", ".join(f"{t}:{v}" for t, v in effs))
        self.colors = [tuple(c) for c in inf["colors"]] if inf["colors"] else None
        self.del_btn.setVisible(not inf["game"])
        self.reset_btn.setVisible(inf["game"])
        self._fill_who()
        self._preview()

    def _fill_who(self):
        self.who.clear()
        names = char_names(self.svc)
        for r in self.svc.table(CHAR).rows:
            if int(r["overload_id"]) == self.ovl:
                cid = int(r["id"])
                it = QListWidgetItem(f"{names.get(cid, r['name_EN'])}  ({cid})")
                it.setData(Qt.ItemDataRole.UserRole, cid)
                self.who.addItem(it)

    def _preview(self):
        try:
            import os
            mod = self.ws.active_mod
            p = overloads.picture_path(mod, self.ovl) if mod else None
            if p and os.path.exists(p):
                from PIL import Image
                img = Image.open(p).convert("RGBA")
                img = img.resize((max(1, round(img.width * overloads.BANNER_H / img.height)), overloads.BANNER_H))
            else:
                style = self.style.currentData() or 1
                colors = self.colors or overloads.BANNER_COLORS.get(style) or overloads.BANNER_COLORS[1]
                img = overloads.banner_picture(self.name.text(), colors)
            self.preview.setPixmap(pil_to_pixmap(img))
        except Exception as e:
            self.preview.setText(f"(preview failed: {e})")
        for btn, k in ((self.top_btn, 0), (self.bot_btn, 1)):
            style = self.style.currentData() or 1
            c = (self.colors or overloads.BANNER_COLORS.get(style) or overloads.BANNER_COLORS[1])[k]
            btn.setStyleSheet(f"background: rgb{tuple(c)}; color: black;")

    # ------------------------------------------------------------------ edits
    def _mod(self):
        mod = self.ws.require_mod(self)
        if mod and self.svc.dirty_members():
            self.svc.commit_all(self)
        return mod

    def _done(self, msg=None, members=(TABLE, MAGIC)):
        self.svc.reload()
        for m in members:
            self.svc.table_changed.emit(m)
        self.ws.file_changed.emit(f"{overloads.DB_ARCHIVE}/{TABLE}")
        if msg:
            self.ws.log(msg)
        self.changed.emit()

    def save_text(self):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        try:
            overloads.set_text(self.ws.fs, mod, self.ovl, self.name.text().strip(), [e.text() for e in self.desc])
        except Exception as e:
            return error_box(self, "Overload", e)
        self._done(f"Overload {self.ovl}: name and description saved into {mod.name}")

    def save_like(self):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        try:
            overloads.set_like(self.ws.fs, mod, self.ovl, self.like.currentData() or 0)
        except Exception as e:
            return error_box(self, "Overload", e)
        self._done(f"Overload {self.ovl}: works like {self.like.currentText()}")

    def own_numbers(self):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        try:
            overloads.give_numbers(self.ws.fs, mod, self.ovl, from_ovl=self.own_from.currentData())
        except Exception as e:
            return error_box(self, "Overload", e)
        self._done(f"Overload {self.ovl}: numbers of its own ({self.own_from.currentText()})")

    def drop_numbers(self):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        overloads.drop_numbers(self.ws.fs, mod, self.ovl)
        self._done(f"Overload {self.ovl}: the numbers of the Overload it works like")

    def save_numbers(self):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        try:
            effs = []
            for part in self.effects.text().replace(";", ",").split(","):
                if part.strip():
                    t, v = part.split(":")
                    effs.append((int(t), int(v)))
            overloads.set_numbers(self.ws.fs, mod, self.ovl, power=self.power.value(), effects=effs,
                                  formula=self.formula.currentData(), element=self.element.currentData(),
                                  attack_map=self.area.currentData())
        except Exception as e:
            return error_box(self, "Overload numbers", e)
        self._done(f"Overload {self.ovl}: numbers saved")

    def pick_color(self, k):
        style = self.style.currentData() or 1
        cur = list(self.colors or overloads.BANNER_COLORS.get(style) or overloads.BANNER_COLORS[1])
        c = QColorDialog.getColor(QColor(*cur[k]), self, "Name colour")
        if c.isValid():
            cur[k] = (c.red(), c.green(), c.blue())
            self.colors = cur
            self._preview()

    def style_colors(self):
        self.colors = None
        self._preview()

    def choose_picture(self):
        p, _ = QFileDialog.getOpenFileName(self, "Picture of the name", "", "Images (*.png *.webp *.jpg)")
        if p:
            self.save_banner(picture=p)

    def save_banner(self, picture=None):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        try:
            overloads.set_banner(mod, self.ovl, style=self.style.currentData() or 1, colors=self.colors or [],
                                 picture=picture)
        except Exception as e:
            return error_box(self, "Banner", e)
        self._preview()
        self._done(f"Overload {self.ovl}: title banner saved — Install to see it in the game", members=())

    def give(self):
        if self.ovl is None:
            return
        rows = self.svc.table(CHAR).rows
        ids = {int(r["id"]) for r in rows}
        choices = [(cid, n) for cid, n in sorted(char_names(self.svc).items()) if cid in ids]
        dlg = QDialog(self)
        dlg.setWindowTitle("Give Overload")
        f = QFormLayout(dlg)
        who = SearchCombo(choices)
        f.addRow("Character / class", who)
        note = QLabel("A class: every rank of it. A character has one Overload (this replaces the one it has).")
        note.setWordWrap(True)
        note.setObjectName("muted")
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if not dlg.exec():
            return
        try:
            cid = int(who.value())
        except (TypeError, ValueError):
            return
        self._set_owner(cid, self.ovl)

    def take(self):
        it = self.who.currentItem()
        if it is None:
            return info_box(self, "Overload", "Select a character in the list first.")
        self._set_owner(int(it.data(Qt.ItemDataRole.UserRole)), 0)

    def _set_owner(self, cid, ovl):
        if not self.ws.require_mod(self):
            return
        rows = self.page._tier_rows(cid)
        if not rows:
            return
        for r in rows:
            r.set("overload_id", int(ovl))
        self.svc.mark_dirty(CHAR)
        if self.svc.commit(CHAR, self):
            self.ws.log(f"{rows[0]['name_EN']}: Overload {ovl or 'none'} (saved into {self.ws.active_mod.name})")
            self._fill_who()

    def delete(self):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        if str(self.ovl) not in overloads.load(mod)["overloads"]:
            return info_box(self, "Overload", "The active mod doesn't make this Overload.")
        if QMessageBox.question(self, "Overload", f"Delete Overload {self.ovl} ({self.name.text()}) and its "
                                "animation from the active mod? Characters having it get none.") \
                != QMessageBox.StandardButton.Yes:
            return
        overloads.remove(self.ws.fs, mod, self.ovl)
        self.ovl = None
        self._done("Overload deleted", members=(TABLE, MAGIC, CHAR))

    def reset(self):
        mod = self._mod()
        if not mod or self.ovl is None:
            return
        if QMessageBox.question(self, "Overload", "Undo the active mod's changes to this Overload (name, numbers, "
                                "works like, banner)? Its animation stays: ↺ Back to vanilla above removes it.") \
                != QMessageBox.StandardButton.Yes:
            return
        overloads.reset(self.ws.fs, mod, self.ovl)
        self._done(f"Overload {self.ovl}: back to the game's")

    def new_overload(self):
        mod = self._mod()
        if not mod:
            return None
        dlg = NewOverloadDialog(self, self.game_names())
        if not dlg.exec():
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ovl = overloads.create(self.ws.fs, mod, dlg.name.text().strip() or "New Overload",
                                   [e.text() for e in dlg.desc], like=dlg.like.currentData() or 0,
                                   animation_of=dlg.anim.currentData())
        except Exception as e:
            QApplication.restoreOverrideCursor()
            error_box(self, "New Overload", e)
            return None
        QApplication.restoreOverrideCursor()
        self._done(f"New Overload {ovl} ({dlg.name.text()}) in {mod.name}")
        return ovl
