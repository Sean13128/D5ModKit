"""Skills: what a skill looks like in battle -- its choreography (script.dat) and the pictures of its effects
(Effect.dat).  Backend: d5lib/skills.py, docs/SKILL_ANIMATIONS.md."""
import os

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon, QColor, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem, QPushButton,
                             QLabel, QPlainTextEdit, QApplication, QInputDialog, QMessageBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QFormLayout, QComboBox,
                             QDoubleSpinBox, QSpinBox, QCheckBox, QDialogButtonBox, QFileDialog, QAbstractItemView)

from d5lib import overloads, skills
from ..common import PageHeader, SearchBox, Worker, error_box, info_box, pil_to_pixmap
from ..dbservice import get_service, table_names, char_names
from ..skilledit.editor import SkillTimelineEditor
from .stages import SearchCombo
from .overloadpanel import OverloadPanel

MODDED = QColor("#ff4f8b")
CHAR = "char.dat"
LEARN_SLOTS = 16
WEAPONS = {1: "Fist", 2: "Sword", 3: "Spear", 4: "Bow", 5: "Gun", 6: "Axe", 9: "Tower", 10: "Staff"}
ELEMENTS = {1: "Fire", 2: "Wind", 3: "Ice", 4: "Star"}
CATEGORIES = (["Character & class skills"] + [f"Weapon: {w}" for w in ("Fist", "Sword", "Spear", "Bow", "Gun", "Axe",
                                                                        "Staff", "Tower")]
              + [f"Spells: {e}" for e in ("Fire", "Wind", "Ice", "Star", "Heal", "Support", "Status")]
              + ["Overloads", "Throw items", "System"])


def skill_category(row):
    """a magic.dat row -> one of CATEGORIES"""
    try:
        t, w, el, fm = row["skill_type"], row["weapon_type"], row["element"], row["formula"]
    except (KeyError, TypeError):
        return "System"
    if t == 1:
        return f"Weapon: {WEAPONS.get(w, 'Staff')}"
    if t == 2:
        if fm == 4:
            return "Spells: Heal"
        if fm == 5:
            return "Spells: Support"
        if fm == 6:
            return "Spells: Status"
        return f"Spells: {ELEMENTS.get(el, 'Star')}"
    return {0: "Character & class skills", 3: "Throw items", 4: "Overload data"}.get(t, "System")


def family_of(cid):
    """unique characters (< 1000) stand alone; a generic class's tiers (x0..x5) learn together"""
    cid = int(cid)
    return cid if cid < 1000 else cid // 10 * 10


def learnset(row):
    """[(skill id, level)] of a char.dat row"""
    out = []
    for k in range(1, LEARN_SLOTS + 1):
        try:
            sid = row[f"learn{k}_skill"]
        except KeyError:
            break
        if sid:
            out.append((int(sid), int(row[f"learn{k}_level"])))
    return out


class GiveSkillDialog(QDialog):
    def __init__(self, parent, skill_name, choices, current=None):
        super().__init__(parent)
        self.setWindowTitle("Give a skill to a character")
        f = QFormLayout(self)
        note = QLabel(f"<b>{skill_name}</b> goes into the character's learned skills (a class: every tier). "
                      "Saved into the active mod; Install to use it in game.")
        note.setWordWrap(True)
        f.addRow(note)
        self.who = SearchCombo(choices)
        if current:
            self.who.set_value(current)
        f.addRow("Character / class", self.who)
        self.level = QSpinBox()
        self.level.setRange(1, 9999)
        self.level.setValue(1)
        self.level.setToolTip("The level at which the character learns it")
        f.addRow("Learned at level", self.level)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


def _thumb(img, size=96, bg=(30, 30, 60, 255)):
    from PIL import Image
    im = img.copy()
    im.thumbnail((size, size))
    out = Image.new("RGBA", (size, size), bg)
    out.alpha_composite(im.convert("RGBA"), ((size - im.width) // 2, (size - im.height) // 2))
    return pil_to_pixmap(out)


class PictureDialog(QDialog):
    """a picture for one effect texture: fit / scale / rotate / tile / brightness, with a preview"""

    def __init__(self, parent, tex, original, geometry):
        super().__init__(parent)
        self.setWindowTitle("Replace picture")
        self.tex, self.path = tex, None
        lay = QVBoxLayout(self)
        hint = {"wall": "This effect is a ring / wall around the spot: the picture's width wraps once around it. "
                        "Use Tile ~10 with Fit = stretch for upright pictures.",
                "flat": "This effect is a flat picture (circle, flash, sprite).",
                "mesh": "This effect is a 3D shape: the picture is wrapped over it."}[geometry]
        note = QLabel(f"Texture {tex.width}x{tex.height} {tex.format_name}"
                      + (f", {tex.layers} layers" if tex.layers > 1 else "")
                      + (" — additive: black shows nothing, light adds up" if skills.is_additive(tex) else "")
                      + f".\n{hint}")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        self.before = QLabel()
        self.before.setPixmap(_thumb(original, 220))
        self.after = QLabel("Choose a picture")
        self.after.setFixedSize(220, 220)
        self.after.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.before)
        row.addWidget(QLabel("→"))
        row.addWidget(self.after)
        lay.addLayout(row)
        form = QFormLayout()
        b = QPushButton("Choose picture…")
        b.clicked.connect(self._choose)
        form.addRow("Picture", b)
        self.fit = QComboBox()
        self.fit.addItems(["contain", "cover", "stretch"])
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.05, 4.0)
        self.scale.setSingleStep(0.05)
        self.scale.setValue(1.0)
        self.rotate = QSpinBox()
        self.rotate.setRange(-360, 360)
        self.tile = QSpinBox()
        self.tile.setRange(1, 64)
        if geometry == "wall":
            self.tile.setValue(10)
            self.fit.setCurrentText("stretch")
        self.auto = QCheckBox("automatic")
        self.auto.setChecked(True)
        self.bright = QDoubleSpinBox()
        self.bright.setRange(0.05, 2.0)
        self.bright.setSingleStep(0.05)
        self.bright.setValue(1.0)
        br = QHBoxLayout()
        br.addWidget(self.auto)
        br.addWidget(self.bright)
        form.addRow("Fit", self.fit)
        form.addRow("Scale", self.scale)
        form.addRow("Rotate (°)", self.rotate)
        form.addRow("Tile across", self.tile)
        form.addRow("Brightness", br)
        lay.addLayout(form)
        for w in (self.fit, self.scale, self.rotate, self.tile, self.auto, self.bright):
            sig = getattr(w, "currentTextChanged", None) or getattr(w, "valueChanged", None) or w.toggled
            sig.connect(self._update)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def options(self):
        return {"fit": self.fit.currentText(), "scale": self.scale.value(), "rotate": self.rotate.value(),
                "tile": self.tile.value(), "brightness": None if self.auto.isChecked() else self.bright.value()}

    def _choose(self):
        p, _ = QFileDialog.getOpenFileName(self, "Picture", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if p:
            self.path = p
            self._update()

    def _update(self, *_):
        self.bright.setEnabled(not self.auto.isChecked())
        if not self.path:
            return
        try:
            img = skills.prepare(self.path, self.tex, **self.options())
            self.after.setPixmap(_thumb(img, 220, (0, 0, 0, 255) if skills.is_additive(self.tex) else (30, 30, 60, 255)))
        except Exception as e:
            self.after.setText(str(e))


class SkillsPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.svc = get_service(ws)
        self.sc = None
        self.skill = None
        self._loaded = False
        lay = QVBoxLayout(self)
        self.header = PageHeader(
            "Skills",
            "What a skill looks like in battle. The Timeline editor plays the whole skill right here and lets you "
            "retime, move and swap its effects, camera, motions and sounds, or add new ones from the game's effect "
            "library (your first change makes an editable copy in your mod). The Choreography tab shows the raw "
            "script; ▶ Preview in game sends your version to the running game without a restart; new pictures "
            "need Install and a game restart.")
        lay.addWidget(self.header)
        self.topw = QWidget()
        top = QHBoxLayout(self.topw)
        top.setContentsMargins(0, 0, 0, 0)
        self.search = SearchBox("Skill name or id…")
        self.search.textChanged.connect(self._fill)
        top.addWidget(self.search, 2)
        self.category = QComboBox()
        self.category.addItem("All skills", None)
        for c in CATEGORIES:
            self.category.addItem(c, c)
        self.category.setToolTip("Show one kind of skill")
        self.category.currentIndexChanged.connect(self._fill)
        top.addWidget(self.category, 1)
        self.who = SearchCombo([])
        self.who.setToolTip("Show the skills one character or class learns (and at which level)")
        self.who.setMinimumWidth(220)
        self.who.activated.connect(lambda _: self._fill())
        self.who.lineEdit().editingFinished.connect(self._fill)
        self.who.lineEdit().setPlaceholderText("Skills of a character / class…")
        top.addWidget(self.who, 2)
        self.only_mod = QCheckBox("Changed by mods only")
        self.only_mod.toggled.connect(self._fill)
        top.addWidget(self.only_mod)
        b = QPushButton("⚡ New Overload…")
        b.setToolTip("A new Overload: the code of a game Overload or numbers of its own, its own name banner and "
                     "animation, for any character")
        b.clicked.connect(self.new_overload)
        top.addWidget(b)
        lay.addWidget(self.topw)

        split = QSplitter()
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        self.list.currentItemChanged.connect(self._pick)
        split.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.headw = QWidget()
        hl = QVBoxLayout(self.headw)
        hl.setContentsMargins(0, 0, 0, 0)
        # coming from a character's setup (Characters & Classes): one click back to it
        self.back_btn = QPushButton()
        self.back_btn.setObjectName("primary")
        self.back_btn.hide()
        self.back_btn.clicked.connect(self._go_back)
        self._back = None
        hl.addWidget(self.back_btn)
        self.title = QLabel("Pick a skill")
        self.title.setObjectName("cardTitle")
        hl.addWidget(self.title)
        self.info = QLabel("")
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        hl.addWidget(self.info)
        row = QHBoxLayout()
        for text, fn, tip in [("🎬 Use animation of…", self.use_other, "Play another skill's animation for this one"),
                              ("✏ Make editable copy", self.make_copy, "Your own copy of the animation to change"),
                              ("↺ Back to vanilla", self.reset, "Remove the changes a mod makes to this skill's animation"),
                              ("➕ Give to character…", self.give_skill,
                               "Add this skill to a character's or class's learned skills"),
                              ("➖ Remove from character", self.take_skill,
                               "Remove it from the character chosen above"),
                              ("▶ Preview in game", self.preview, "Send your version to the running game")]:
            b = QPushButton(text)
            b.setToolTip(tip)
            if text.startswith("▶"):
                b.setObjectName("primary")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        hl.addLayout(row)
        rl.addWidget(self.headw)

        self.tabs = QTabWidget()
        # --- timeline editor
        self.editor = SkillTimelineEditor(ws, self)
        self.tabs.addTab(self.editor, "🎬 Timeline editor")
        # --- choreography
        ch = QWidget()
        cl = QHBoxLayout(ch)
        self.events = QListWidget()
        self.events.setMaximumWidth(160)
        self.events.currentItemChanged.connect(self._pick_event)
        cl.addWidget(self.events)
        ce = QVBoxLayout()
        self.edit = QPlainTextEdit()
        self.edit.setFont(QFont("Consolas", 9))
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        ce.addWidget(self.edit, 1)
        er = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save event")
        self.save_btn.clicked.connect(self.save_event)
        er.addWidget(self.save_btn)
        self.ev_note = QLabel("")
        self.ev_note.setObjectName("muted")
        er.addWidget(self.ev_note, 1)
        ce.addLayout(er)
        cl.addLayout(ce, 1)
        self.tabs.addTab(ch, "Choreography")
        # --- who learns it
        lw = QWidget()
        ll = QVBoxLayout(lw)
        note = QLabel("Characters and classes that learn this skill, and at which level (a class: all its tiers). "
                      "Changes are saved into the active mod at once and show on the Characters & Classes page too "
                      "(and changes made there show here).")
        note.setWordWrap(True)
        note.setObjectName("muted")
        ll.addWidget(note)
        self.learn_table = QTableWidget(0, 3)
        self.learn_table.setHorizontalHeaderLabels(["Character / class", "Learns it at level", ""])
        self.learn_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.learn_table.verticalHeader().setVisible(False)
        self.learn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.learn_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        ll.addWidget(self.learn_table, 1)
        lr = QHBoxLayout()
        b = QPushButton("➕ Give to a character / class…")
        b.setObjectName("primary")
        b.clicked.connect(self.give_skill)
        lr.addWidget(b)
        lr.addStretch(1)
        ll.addLayout(lr)
        self.tabs.addTab(lw, "👥 Who learns it")
        self.learn_tab = lw
        # --- Overload (its own data: name, what it does, banner, who has it)
        self.ovl_panel = OverloadPanel(self)
        self.ovl_panel.changed.connect(self._overload_changed)
        self.tabs.addTab(self.ovl_panel, "⚡ Overload")
        # --- effects
        fx = QWidget()
        fl = QVBoxLayout(fx)
        self.fx = QTableWidget(0, 5)
        self.fx.setHorizontalHeaderLabels(["Slot", "Effect", "Shape", "Textures", "Note"])
        self.fx.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.fx.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fx.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fx.currentCellChanged.connect(lambda *a: self._pick_fx())
        fl.addWidget(self.fx, 2)
        self.tex = QListWidget()
        self.tex.setViewMode(QListWidget.ViewMode.IconMode)
        self.tex.setIconSize(QSize(96, 96))
        self.tex.setMinimumHeight(140)
        self.tex.setResizeMode(QListWidget.ResizeMode.Adjust)
        fl.addWidget(self.tex, 1)
        fr = QHBoxLayout()
        for text, fn in [("🖼 Replace picture…", self.replace_picture), ("🔁 Use another effect…", self.swap_effect),
                         ("👁 Solo this slot in preview", self.solo), ("📤 Export textures…", self.export_textures)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            fr.addWidget(b)
        fr.addStretch(1)
        fl.addLayout(fr)
        self.tabs.addTab(fx, "Effects && pictures")
        # --- reference
        self.ref = QTableWidget(0, 4)
        self.ref.setHorizontalHeaderLabels(["Command", "Arguments", "What it does", "Known"])
        self.ref.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.ref.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ref.cellDoubleClicked.connect(self._insert_cmd)
        self.tabs.addTab(self.ref, "Command reference")
        rl.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([300, 1100])
        lay.addWidget(split, 1)
        from ..common import Refresher
        self._reload = Refresher(self, lambda: self._loaded and self.load())
        ws.active_mod_changed.connect(self._reload)
        ws.mods_changed.connect(self._reload)
        self._changed_tables = set()
        self._retable = Refresher(self, lambda: self._loaded and self._refresh_tables())
        self.svc.table_changed.connect(self._table_changed)

    def _table_changed(self, member):
        """char.dat / magic.dat changed (here, on the Characters page, in the Database editor): who learns what,
        names -- refreshed once after the current event (the level box that saved may still be in its signal; a
        reload changes every table at once), or when the page is shown next"""
        if not self._loaded or member not in (CHAR, "magic.dat", "OverlordSkill.dat"):
            return
        self._changed_tables.add(member)
        self._retable()

    def _refresh_tables(self, member=None):
        changed, self._changed_tables = self._changed_tables | ({member} if member else set()), set()
        if changed & {"magic.dat", "OverlordSkill.dat"}:
            self.names = self._all_names()
        self._load_categories()
        self._fill()
        if self.skill is not None:
            self._show(self.skill, editor=False)

    # ------------------------------------------------------------------ data
    def mods(self):
        ms = list(self.ws.mods.enabled_mods())
        a = self.ws.active_mod
        if a and all(m.id != a.id for m in ms):
            ms.append(a)
        return ms

    def on_show(self):
        if self._loaded:
            return
        if not skills.vanilla_scripts_ready(self.ws.fs):
            self._load_in_background()
            return
        self._first_load()

    def _first_load(self):
        if not self._loaded:
            self._loaded = True
            self._fill_reference()
            self.load()

    def _load_in_background(self):
        """the game's 19 053 scripts are parsed once (~2 s): in a worker, the page shows at once and the kit stays
        usable (MainWindow also starts this a moment after start-up)"""
        if getattr(self, "_bg", None) is not None:
            return
        self.list.clear()
        self.list.addItem("Loading the game's skill animations…")
        self._bg = Worker(skills.vanilla_scripts, self.ws.fs, True)

        def done(_):
            self._bg = None
            self._first_load()

        def failed(msg):
            self._bg = None
            self.list.clear()
            self.list.addItem("Could not load the skill scripts: " + msg.splitlines()[0])
        self._bg.done.connect(done)
        self._bg.failed.connect(failed)
        self._bg.start()

    def reload_quiet(self):
        """re-read the scripts and the mods' skill data without touching the views (the timeline editor's saves)"""
        self.sc = skills.with_mods(self.ws.fs, self.mods())
        self.owned = {}
        for m in self.mods():
            for sid in skills.load(m)["skills"]:
                self.owned[int(sid)] = m

    def _all_names(self):
        """magic.dat skills + the Overloads (key skills.OVL_KEY + Overload id)"""
        names = table_names(self.svc, "magic.dat")
        try:
            for r in self.svc.table("OverlordSkill.dat").rows:
                if int(r["id"]):
                    names[skills.OVL_KEY + int(r["id"])] = f"⚡ {r['name_EN']}"
        except Exception:
            pass
        return names

    def load(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.names = self._all_names()
            self._load_categories()
            self.sc = skills.with_mods(self.ws.fs, self.mods())
            self.members = skills.effect_members(self.ws.fs.read)
            self.owned = {}
            for m in self.mods():
                for sid in skills.load(m)["skills"]:
                    self.owned[int(sid)] = m
        finally:
            QApplication.restoreOverrideCursor()
        self._fill()
        if self.skill is not None:
            self._show(self.skill)

    def _load_categories(self):
        self.cats, self.learners = {}, {}
        self.learn_fams = {}                    # skill -> {family: {cid: level}}
        try:
            for r in self.svc.table("magic.dat").rows:
                self.cats[int(r["id"])] = skill_category(r)
        except Exception:
            pass
        for sid in self.names:
            if skills.is_ovl_key(sid):
                self.cats[sid] = "Overloads"
        self.char_rows = {}
        try:
            for r in self.svc.table(CHAR).rows:
                cid = int(r["id"])
                if cid in self.char_rows:
                    continue
                self.char_rows[cid] = r
                for sid, lv in learnset(r):
                    who = f"{r['name_EN']}" if cid < 1000 else f"{r['name_EN']} ({r['title_EN']})"
                    self.learners.setdefault(sid, []).append((who, lv))
                    self.learn_fams.setdefault(sid, {}).setdefault(family_of(cid), {})[cid] = lv
        except Exception:
            pass
        try:
            names = char_names(self.svc)
            choices = [(cid, n) for cid, n in sorted(names.items()) if cid in self.char_rows
                       and learnset(self.char_rows[cid])]
        except Exception:
            choices = []
        self.who_choices = choices
        from .stages import choice_model
        cur = self.who.value() if self.who.currentText() else 0
        self.who.setModel(choice_model(choices))
        self.who.setItemText(0, "All characters")
        if cur:
            self.who.set_value(cur)
        else:
            self.who.setCurrentIndex(0)

    def _who(self):
        """the character chosen in the filter (char.dat row) or None"""
        try:
            v = int(self.who.value() or 0)
        except (TypeError, ValueError):
            v = 0
        return self.char_rows.get(v) if v else None

    def _fill(self, *_):
        if not self.sc:
            return
        q = self.search.text().strip().lower()
        cat = self.category.currentData()
        who = self._who()
        levels = dict(learnset(who)) if who is not None else None
        cur = self.skill
        self.list.blockSignals(True)
        self.list.clear()
        entries = sorted(self.names.items())
        if levels is not None:
            entries = sorted(((sid, n) for sid, n in entries if sid in levels), key=lambda e: (levels[e[0]], e[0]))
        for sid, name in entries:
            if self.only_mod.isChecked() and sid not in self.owned:
                continue
            if cat is not None and self.cats.get(sid) != cat:
                continue
            if self.cats.get(sid) == "Overload data":      # edited through its Overload (⚡ tab)
                continue
            if q and q not in str(sid) and q not in str(name).lower():
                continue
            text = f"{sid - skills.OVL_KEY}  {name}" if skills.is_ovl_key(sid) else f"{sid}  {name}"
            if levels is not None:
                text = f"Lv {levels[sid]:<4} {name}  ({sid})"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, sid)
            it.setToolTip(f"{name} · {self.cats.get(sid, '')}")
            if sid in self.owned:
                it.setForeground(QBrush(MODDED))
            self.list.addItem(it)
            if sid == cur:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)

    # ------------------------------------------------------------------ characters' skills
    def _tier_rows(self, cid):
        t = self.svc.table(CHAR)
        if cid < 1000:
            return [r for r in t.rows if int(r["id"]) == cid][:1]
        fam = cid // 10 * 10
        return [r for r in t.rows if fam <= int(r["id"]) <= fam + 5]

    def give_skill(self):
        if self.skill is None:
            return
        if skills.is_ovl_key(self.skill):
            return self.ovl_panel.give()
        choices = [(cid, n) for cid, n in sorted(char_names(self.svc).items()) if cid in self.char_rows]
        cur = self._who()
        dlg = GiveSkillDialog(self, self.names.get(self.skill, str(self.skill)), choices,
                              int(cur["id"]) if cur is not None else None)
        if not dlg.exec():
            return
        try:
            cid = int(dlg.who.value())
        except (TypeError, ValueError):
            return
        rows = self._tier_rows(cid)
        if not rows:
            return QMessageBox.warning(self, "Skills", f"No character {cid}.")
        lv = dlg.level.value()
        for r in rows:
            have = learnset(r)
            if any(sid == self.skill for sid, _ in have):
                for k in range(1, LEARN_SLOTS + 1):
                    if r[f"learn{k}_skill"] == self.skill:
                        r.set(f"learn{k}_level", lv)
                continue
            free = next((k for k in range(1, LEARN_SLOTS + 1) if not r[f"learn{k}_skill"]), None)
            if free is None:
                return QMessageBox.warning(self, "Skills", f"{r['name_EN']} already learns {LEARN_SLOTS} skills; "
                                           "remove one first (Characters page).")
            r.set(f"learn{free}_skill", self.skill)
            r.set(f"learn{free}_level", lv)
            r.set("learn_count", sum(1 for k in range(1, LEARN_SLOTS + 1) if r[f"learn{k}_skill"]))
        self.svc.mark_dirty(CHAR)
        if self.svc.commit(CHAR, self):
            self.ws.log(f"{rows[0]['name_EN']} learns {self.names.get(self.skill)} at level {lv} "
                        f"(saved into {self.svc.saved_text()})")
            self._load_categories()
            self._fill()
            self._show(self.skill, editor=False)

    def take_skill(self):
        if self.skill is not None and skills.is_ovl_key(self.skill):
            return self.ovl_panel.take()
        who = self._who()
        if self.skill is None or who is None:
            return info_box(self, "Skills", "Choose the character in the “Skills of a character / class” box above "
                                            "first.")
        rows = self._tier_rows(int(who["id"]))
        if not any(any(sid == self.skill for sid, _ in learnset(r)) for r in rows):
            return info_box(self, "Skills", f"{who['name_EN']} doesn't learn this skill.")
        if QMessageBox.question(self, "Skills", f"Remove {self.names.get(self.skill)} from {who['name_EN']}'s "
                                                "learned skills?") != QMessageBox.StandardButton.Yes:
            return
        for r in rows:
            keep = [(sid, lv) for sid, lv in learnset(r) if sid != self.skill]
            for k in range(1, LEARN_SLOTS + 1):
                sid, lv = keep[k - 1] if k - 1 < len(keep) else (0, 0)
                r.set(f"learn{k}_skill", sid)
                r.set(f"learn{k}_level", lv)
            r.set("learn_count", len(keep))
        self.svc.mark_dirty(CHAR)
        if self.svc.commit(CHAR, self):
            self._load_categories()
            self._fill()

    def _family_name(self, fam):
        r = self.char_rows.get(fam) or next((self.char_rows[c] for c in range(fam, fam + 6) if c in self.char_rows),
                                            None)
        if r is None:
            return f"#{fam}"
        return r["name_EN"] if fam < 1000 else f"{r['name_EN']} (class)"

    def _learn_rows(self, sid):
        """[(family, name, level text)] of the characters / classes that learn skill sid"""
        out = []
        for fam, lv in sorted((getattr(self, "learn_fams", {}).get(sid) or {}).items()):
            levels = sorted(set(lv.values()))
            out.append((fam, self._family_name(fam), str(levels[0]) if len(levels) == 1 else
                        f"{levels[0]}–{levels[-1]}"))
        return out

    def _fill_learners(self):
        from PyQt6.QtWidgets import QSpinBox
        t = self.learn_table
        t.setRowCount(0)
        if self.skill is None:
            return
        for fam, name, lv in self._learn_rows(self.skill):
            r = t.rowCount()
            t.insertRow(r)
            split = "–" in lv
            it = QTableWidgetItem(name + (f"   · tiers differ: {lv}" if split else ""))
            it.setToolTip("All tiers of the class" + (f"; they learn it at levels {lv} (set one level for all "
                                                      "here, or each tier on the Characters & Classes page)"
                                                      if split else "") if fam >= 1000 else "")
            t.setItem(r, 0, it)
            sp = QSpinBox()
            sp.setRange(1, 9999)
            sp.setValue(int(lv.split("–")[0]))
            sp.setToolTip("The level at which it is learned (Enter or leave the box to save)" +
                          (" — every tier gets this level" if split else ""))
            sp.editingFinished.connect(lambda f=fam, w=sp: self._set_level(f, w.value()))
            t.setCellWidget(r, 1, sp)
            b = QPushButton("Remove")
            b.clicked.connect(lambda _, f=fam: self._remove_from(f))
            t.setCellWidget(r, 2, b)
        t.resizeColumnToContents(2)

    def _set_level(self, fam, lv):
        """everyone in the family who learns this skill learns it at level lv"""
        rows = self._tier_rows(fam)
        changed = False
        for r in rows:
            for k in range(1, LEARN_SLOTS + 1):
                if r[f"learn{k}_skill"] == self.skill and int(r[f"learn{k}_level"]) != int(lv):
                    changed = True
        if not changed:
            return
        for r in rows:
            for k in range(1, LEARN_SLOTS + 1):
                if r[f"learn{k}_skill"] == self.skill:
                    r.set(f"learn{k}_level", int(lv))
        self.svc.mark_dirty(CHAR)
        if self.svc.commit(CHAR, self):
            self.ws.log(f"{self._family_name(fam)} learns {self.names.get(self.skill)} at level {lv} "
                        f"(saved into {self.svc.saved_text()})")

    def _remove_from(self, fam):
        if QMessageBox.question(self, "Skills", f"Remove {self.names.get(self.skill)} from "
                                                f"{self._family_name(fam)}'s learned skills?") \
                != QMessageBox.StandardButton.Yes:
            return
        for r in self._tier_rows(fam):
            keep = [(sid, lv) for sid, lv in learnset(r) if sid != self.skill]
            for k in range(1, LEARN_SLOTS + 1):
                sid, lv = keep[k - 1] if k - 1 < len(keep) else (0, 0)
                r.set(f"learn{k}_skill", sid)
                r.set(f"learn{k}_level", lv)
            r.set("learn_count", len(keep))
        self.svc.mark_dirty(CHAR)
        self.svc.commit(CHAR, self)

    # ------------------------------------------------------------------ focus
    def set_focus_mode(self, on):
        """the timeline editor gets the whole window: page header, skill list and the main sidebar hide"""
        for w in (self.header, self.topw, self.list, self.headw):
            w.setVisible(not on)
        side = self.window().findChild(QWidget, "sidebar")
        if side is not None:
            side.setVisible(not on)
        if on:
            self.tabs.setCurrentWidget(self.editor)

    def _pick(self, it, prev=None):
        if it:
            self._show(it.data(Qt.ItemDataRole.UserRole))

    def open_skill(self, sid, back=None):
        """show skill sid in the editor (e.g. a new skill made on the Characters page); back = (character id,
        name): a button returns to that character's setup"""
        if not self._loaded:
            self._first_load()                     # now (waits for a background load already running)
        else:
            self.load()                            # the skill may be brand new
        self._back = back
        if back:
            self.back_btn.setText(f"↩  Back to {back[1].replace('&', '&&')}'s setup (Characters && Classes)")
            self.back_btn.setToolTip("Your skill edits are saved as you make them")
        self.back_btn.setVisible(bool(back))
        self.search.clear()
        self.category.setCurrentIndex(0)
        self.only_mod.setChecked(False)
        self.who.setCurrentIndex(0)
        self._fill()
        for k in range(self.list.count()):
            if self.list.item(k).data(Qt.ItemDataRole.UserRole) == int(sid):
                self.list.setCurrentRow(k)
                self.list.scrollToItem(self.list.item(k))
                break
        else:
            self._show(int(sid))

    def area_skill(self, sid):
        """(magic.dat row, may its area be changed) of a skill; an Overload: its skill row (own numbers: its own)"""
        if sid is None or not skills.is_ovl_key(sid):
            return sid, True
        return self.ovl_panel.magic_of(int(sid) - skills.OVL_KEY)

    def new_overload(self):
        if not self._loaded:
            self._first_load()
        ovl = self.ovl_panel.new_overload()
        if ovl:
            self.open_skill(skills.OVL_KEY + ovl)
            self.tabs.setCurrentWidget(self.ovl_panel)

    def _overload_changed(self):
        self.load()
        if self.skill is not None and skills.is_ovl_key(self.skill) and self.skill not in self.names:
            self.skill = None
            self.title.setText("Pick a skill")

    def _go_back(self):
        if not self._back:
            return
        cid = self._back[0]
        self._back = None
        self.back_btn.hide()
        page = self.window().show_page("characters") if hasattr(self.window(), "show_page") else None
        if page is not None and hasattr(page, "select_character"):
            page.select_character(cid)

    def _data(self):
        """(mod owning this skill's setting, its skills.json data, choreography root, is an editable copy)"""
        m = self.owned.get(self.skill)
        d = skills.load(m) if m else None
        e = d["skills"].get(str(self.skill), {}) if d else {}
        root = e.get("choreography") or self.sc.root_of(self.skill)
        custom = bool(m and root and skills.is_custom_choreo(root)
                      and str(root) in d["events"])
        return m, d, root, custom

    def _show(self, sid, editor=True):
        self.skill = sid
        is_ovl = skills.is_ovl_key(sid)
        self.tabs.setTabVisible(self.tabs.indexOf(self.ovl_panel), is_ovl)
        self.tabs.setTabVisible(self.tabs.indexOf(self.learn_tab), not is_ovl)
        if is_ovl:
            try:
                self.ovl_panel.show_overload(sid - skills.OVL_KEY)
            except Exception as e:
                self.ws.log(f"overload panel: {e}")
        m, d, root, custom = self._data()
        shown = f"Overload {sid - skills.OVL_KEY}" if skills.is_ovl_key(sid) else sid
        self.title.setText(f"{self.names.get(sid, '?')}  ({shown})  ·  {getattr(self, 'cats', {}).get(sid, '')}")
        if not root:
            txt = f"No choreography of its own: plays the default sequence ({skills.DEFAULT_SCRIPT})."
        elif custom:
            src = d["skills"][str(sid)].get("copied_from")
            txt = f"Editable choreography {root}" + (f", copied from {src}" if src else "") + f" — mod {m.name}."
        else:
            txt = f"Choreography {root}" + (f" (set by mod {m.name})" if m else " (vanilla)") + \
                  ". Make an editable copy to change it."
        fams = self._learn_rows(sid)
        if fams:
            txt += "  Learned by: " + ", ".join(f"{n} (Lv {lv})" for _, n, lv in fams[:6]) + \
                   (f" +{len(fams) - 6}" if len(fams) > 6 else "") + "  (👥 Who learns it)."
        if custom and m is not None:
            txt += f"  Edits are saved in the mod '{m.name}'."
        self.info.setText(txt)
        self.events.clear()
        self.tree = self.sc.tree(root) if root else []
        for e in self.tree:
            QListWidgetItem(str(e), self.events)
        if self.tree:
            self.events.setCurrentRow(0)
        else:
            self.edit.clear()
        self.save_btn.setEnabled(self._editable())
        self._fill_learners()
        self._fill_fx()
        if editor:
            self.open_editor()

    def open_editor(self, force=False):
        m, d, root, custom = self._data()
        try:
            self.editor.open(self.skill, int(root) if root else None, m, custom, self._editable(), force)
        except Exception as e:
            self.ws.log(f"timeline editor: {e}")

    def _editable(self):
        """the skill has an editable copy (in the mod that holds it: edits are saved there)"""
        m, d, root, custom = self._data()
        return bool(custom and m is not None)

    def _pick_event(self, it, prev=None):
        if not it:
            return
        eid = int(it.text())
        m, d, root, custom = self._data()
        text = d["events"][str(eid)] if custom and str(eid) in d["events"] else self.sc.text(eid) or ""
        self.edit.setPlainText(skills.annotate(text))
        self.edit.setReadOnly(not self._editable())
        self.ev_note.setText("" if self._editable() else "read only (vanilla) — Make editable copy to change it")

    # ------------------------------------------------------------------ actions
    def _mod_for_edit(self, suggest=None, category=None):
        """the mod this skill's changes are saved in: the mod that holds its animation setting or editable copy,
        else the mod that makes or changes the skill (its magic.dat row: a mod's character's own skill goes into
        that mod), else the active mod (asked for when there is none: suggest = the name offered, e.g. 'Skill:
        Heal', so one skill's changes can live in a mod of their own)"""
        m = self.owned.get(self.skill)
        if m is not None:
            return m
        try:
            t = self.svc.table("magic.dat")
            i = next((k for k, r in enumerate(t.rows) if r["id"] == self.skill), None)
            o = self.svc.row_owner("magic.dat", i) if i is not None else None
            if o is not None:
                return o
        except Exception:
            pass
        if suggest is None and self.skill is not None:
            suggest = f"Skill: {self.names.get(self.skill, self.skill)}"
        return self.ws.require_mod(self, suggest=suggest, category=category or "skills")

    def _changed(self):
        self.load()
        self.ws.file_changed.emit(skills.SCRIPT)

    def use_other(self):
        if self.skill is None:
            return
        txt, ok = QInputDialog.getText(self, "Use animation of…", "Skill id or name (or a choreography event id):")
        if not ok or not txt.strip():
            return
        t = txt.strip()
        if t.isdigit():
            src = int(t)
        else:
            hits = [k for k, v in self.names.items() if t.lower() in str(v).lower()]
            if not hits:
                return QMessageBox.warning(self, "Skills", f"No skill named like '{t}'.")
            src = hits[0]
        root = src if src >= skills.CHOREO_MIN else self.sc.root_of(src)
        if not root:
            return QMessageBox.warning(self, "Skills", f"Skill {src} has no choreography of its own.")
        mod = self._mod_for_edit()
        if mod:
            skills.assign(mod, self.skill, root)
            self._changed()

    def make_copy(self):
        if self.skill is None:
            return
        m, d, root, custom = self._data()
        if custom and self._editable():
            return info_box(self, "Skills", "This skill already has an editable copy in the active mod.")
        mod = self._mod_for_edit()
        if mod:
            new = skills.make_custom(self.ws.fs, mod, self.skill, root or skills.DEFAULT_SCRIPT, self.sc)
            self._changed()
            info_box(self, "Skills", f"Editable copy {new}: change its events on the Choreography tab, "
                                     "then ▶ Preview in game.")

    def reset(self):
        mod = self.owned.get(self.skill) if self.skill is not None else None
        if mod is None or str(self.skill) not in skills.load(mod)["skills"]:
            return info_box(self, "Skills", "No mod changes this skill's animation.")
        if QMessageBox.question(self, "Skills", "Remove this skill's choreography and pictures from the mod "
                                                f"'{mod.name}'?") != QMessageBox.StandardButton.Yes:
            return
        d = skills.load(mod)
        e = d["skills"].pop(str(self.skill))
        root = int(e.get("choreography", 0))
        if skills.is_custom_choreo(root):
            text = "".join(d["events"].pop(k) for k in list(d["events"]) if root <= int(k) < root + 1000)
            for fx in [k for k in d["effects"] if f", {k}" in text]:
                d["effects"].pop(fx)
        skills.save(mod, d)
        self._changed()

    def save_event(self):
        it = self.events.currentItem()
        if not it or not self._editable():
            return
        try:
            skills.set_event(self._data()[0], int(it.text()), self.edit.toPlainText())
        except Exception as e:
            return error_box(self, "Script error", e)
        self.ev_note.setText("saved — ▶ Preview in game to see it")
        self.sc = skills.with_mods(self.ws.fs, self.mods())
        self.open_editor(force=True)

    def preview(self, solo=None):
        try:
            data = skills.live_script(self.ws.fs, self.mods(), solo)
            p = skills.send_live(self.ws.game_dir, data)
        except Exception as e:
            return error_box(self, "Preview", e)
        running = self.ws.is_game_running()
        self.ws.log(f"Skill preview written to {p}" + (" — the game loads it now" if running else ""))
        info_box(self, "Preview", ("The running game has the new choreography: cast the skill to see it."
                                   if running else "Written. Start the game (installed with this mod) and cast "
                                                   "the skill, then press Preview again after each change.")
                 + "\n\nNew or changed pictures (effects) need Install and a game restart.")

    # ------------------------------------------------------------------ effects tab
    def _fill_fx(self):
        self.fx.setRowCount(0)
        self.tex.clear()
        self.fx_rows = []
        for e in self.tree:
            for line in (self.sc.text(e) or "").splitlines():
                mm = skills.EFFECT_RE.match(line)
                if not mm:
                    continue
                slot, eid = line.split()[1].rstrip(","), int(mm.group(2))     # slot: a number or a $variable
                info = skills.effect_info(self.ws.fs.read, eid, self.members, self.mods())
                r = self.fx.rowCount()
                self.fx.insertRow(r)
                vals = [slot, eid, info["geometry"] if info else "?",
                        len(info["textures"]) if info else 0,
                        (f"your picture(s), copy of effect {info['from']}" if info and info["from"] else "")]
                for c, v in enumerate(vals):
                    self.fx.setItem(r, c, QTableWidgetItem(str(v)))
                self.fx_rows.append((e, slot, eid, info))
        self.fx.resizeColumnsToContents()

    def _cur_fx(self):
        r = self.fx.currentRow()
        return self.fx_rows[r] if 0 <= r < len(self.fx_rows) else None

    def _pick_fx(self):
        self.tex.clear()
        cur = self._cur_fx()
        if not cur or not cur[3]:
            return
        for i, img, w, h, fmt, layers, add in cur[3]["textures"]:
            it = QListWidgetItem(f"#{i} {w}x{h}\n{fmt}" + (f" x{layers}" if layers > 1 else ""))
            if img is not None:
                first = img.crop((0, 0, w, h)) if layers > 1 else img
                it.setIcon(QIcon(_thumb(first, 96, (0, 0, 0, 255) if add else (30, 30, 60, 255))))
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.tex.addItem(it)

    def replace_picture(self):
        cur = self._cur_fx()
        ti = self.tex.currentItem()
        if not cur or not ti:
            return info_box(self, "Replace picture", "Pick an effect (table) and one of its textures (below).")
        mod = self._mod_for_edit()
        if not mod:
            return
        e, slot, eid, info = cur
        idx = ti.data(Qt.ItemDataRole.UserRole)
        o = skills.effect_model(self.ws.fs.read, eid, self.members, self.mods())
        tex = o.textures[idx]
        orig = info["textures"][idx][1]
        if orig is None:
            return QMessageBox.warning(self, "Replace picture", "This texture's format can't be edited.")
        dlg = PictureDialog(self, tex, orig, info["geometry"])
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.path:
            return
        try:
            nid = skills.set_picture(self.ws.fs, mod, self.skill, eid, idx, dlg.path, **dlg.options())
        except Exception as ex:
            return error_box(self, "Replace picture", ex)
        self._changed()
        info_box(self, "Replace picture", f"The skill now uses effect {nid} with your picture. Install and restart "
                                          "the game to see it.")

    def swap_effect(self):
        cur = self._cur_fx()
        if not cur:
            return
        if not self._editable():
            return info_box(self, "Skills", "Make an editable copy first.")
        e, slot, eid, info = cur
        new, ok = QInputDialog.getInt(self, "Use another effect", f"Slot {slot} shows effect {eid}. New effect id "
                                                                  "(any effectNNNN of Effect.dat, or a mod's new one):",
                                      eid, 1, 9999)
        if not ok or new == eid:
            return
        if skills.effect_info(self.ws.fs.read, new, self.members, self.mods()) is None:
            return QMessageBox.warning(self, "Skills", f"There is no effect {new}.")
        mod = self._data()[0]                          # (the mod holding the editable copy)
        d = skills.load(mod)
        lines = []
        for line in d["events"][str(e)].splitlines():
            mm = skills.EFFECT_RE.match(line)
            if mm and line.split()[1].rstrip(",") == slot:
                line = f"{mm.group(1)}{new}" + line[mm.end():]
            lines.append(line)
        skills.set_event(mod, e, "\n".join(lines) + "\n")
        self._changed()

    def solo(self):
        cur = self._cur_fx()
        if cur and self.skill is not None:
            if not cur[1].isdigit():
                return info_box(self, "Skills", "This slot number is computed while the skill runs.")
            if not self._editable():
                return info_box(self, "Skills", "Solo works on an editable copy: make one first.")
            self.preview({self.skill: [int(cur[1])]})

    def export_textures(self):
        cur = self._cur_fx()
        if not cur or not cur[3]:
            return
        d = QFileDialog.getExistingDirectory(self, "Export textures to")
        if not d:
            return
        n = 0
        for i, img, w, h, fmt, layers, add in cur[3]["textures"]:
            if img is not None:
                img.save(os.path.join(d, f"effect{cur[2]}_{i}_{w}x{h}.png"))
                n += 1
        self.ws.log(f"Exported {n} texture(s) of effect {cur[2]} to {d}")

    # ------------------------------------------------------------------ reference tab
    def _fill_reference(self):
        ref = skills.reference()
        self.ref.setRowCount(len(ref))
        for r, (name, x) in enumerate(ref.items()):
            for c, v in enumerate([name, ", ".join(x["args"]), x["desc"], x["sure"]]):
                self.ref.setItem(r, c, QTableWidgetItem(v))
        self.ref.resizeColumnToContents(0)
        self.ref.resizeColumnToContents(1)

    def _insert_cmd(self, r, c):
        name = self.ref.item(r, 0).text()
        args = [a for a in self.ref.item(r, 1).text().split(", ") if a and not a.endswith("...")]
        if self.edit.isReadOnly():
            return
        self.tabs.setCurrentIndex(0)
        self.edit.textCursor().insertText(f"    {name} {', '.join('0' for _ in args)}\n")
