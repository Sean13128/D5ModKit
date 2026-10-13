"""Characters & Classes: friendly editor for char.dat + wizard for brand-new recruitable units."""
import struct

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                             QPushButton, QLabel, QComboBox, QGroupBox, QGridLayout, QFormLayout, QSpinBox,
                             QLineEdit, QScrollArea, QMessageBox, QDialog, QDialogButtonBox, QRadioButton,
                             QCheckBox, QApplication, QTextEdit, QProgressDialog)

from d5lib import anm, charstudio, dbpatch, sprites
from ..common import PageHeader, SearchBox, ImageView, error_box, info_box
from ..dbservice import get_service, table_names
from .stages import SearchCombo, set_choice_tips

CHAR = "char.dat"
STATS = ["HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD"]
WEAPONS = [("fist", "Fist"), ("sword", "Sword"), ("spear", "Spear"), ("bow", "Bow"), ("gun", "Gun"),
           ("axe", "Axe"), ("staff", "Staff"), ("monster_phys", "Monster (phys)"), ("monster_mag", "Monster (mag)"),
           ("armor", "Armor")]
LANGS = ["JP", "EN", "FR", "CHN", "KOR"]

# hover help of the editor's stats and settings
HELP = {
    "HP": "Hit Points. The unit is knocked out when they reach 0.",
    "SP": "Skill Points. Spent to use skills and spells.",
    "ATK": "Attack. Power of physical attacks and physical skills.",
    "DEF": "Defense. Lowers the damage taken from physical attacks.",
    "INT": "Intelligence. Power of spells, magic skills and healing.",
    "RES": "Resistance. Lowers the damage taken from spells and magic skills.",
    "HIT": "Hit. Accuracy of attacks; also the power stat of gun attacks.",
    "SPD": "Speed. Evasion: the chance to dodge attacks.",
    "base": "Base value: the stat at level 1, before equipment. It grows with every level.",
    "apt": "Aptitude (%): multiplies this stat's growth and the bonus it gets from equipment. "
           "100 = normal, higher = the unit is better at this stat.",
    "MOV": "Move: how many panels the unit can walk per turn.",
    "JMP": "Jump: how high a step (in height levels) the unit can climb while moving.",
    "throw": "Throw: how many panels far the unit can throw (Lift & Throw).",
    "counter": "Counter: how many times per enemy turn the unit strikes back when attacked.",
    "crit": "Critical %: base chance of a critical hit (extra damage).",
    "attack_range": "Attack range: reach of the normal Attack command without a weapon bonus.",
    "mastery": "Starting weapon mastery level for this weapon type. Mastery grows by fighting with the "
               "weapon and raises the stats gained from it.",
    "res": "Elemental resistance (%): lowers damage of that element. Negative = weakness (more damage).",
    "wres": "Resistance (%) against attacks with this weapon type. Negative = weakness.",
    "exp_value": "EXP given to the unit that defeats this character (scaled by level).",
    "hl_value": "HL (money) dropped when this character is defeated (scaled by level).",
    "mana_value": "Mana given when this character is defeated (scaled by level).",
    "evility": "Evilities are passive abilities. Hover an entry to read what it does.\n"
               "Characters you edit or add get every evility at once (no story lock).",
    "overload_id": "Overload: the character's unique once-per-battle ability. Hover to read it.\n"
                   "Characters you edit or add have it at once (no story lock).",
    "learn": "A skill the character learns and the level at which it is learned. Units already at that level "
             "learn it the next time the game refreshes them (e.g. changing equipment). Hover a skill to read it.",
}


def _label(text, tip):
    lab = QLabel(text)
    lab.setToolTip(tip)
    return lab


def kind_of(cid):
    if cid < 1000:
        return "Unique"
    if cid < 2000:
        return "Human class"
    if cid < 3000:
        return "Monster class"
    return "Other / NPC"


class CharactersPage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws, self.main = ws, main
        self.svc = get_service(ws)
        self.row_index = None
        self.widgets = {}
        self._built = False
        self._loading = False
        self._names = None

        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Characters & Classes",
                                 "Edit any character or class: names, base stats, aptitudes, movement, weapon "
                                 "mastery, resistances, evilities, learned skills, sprite and voice. Use “New character / "
                                 "class” to create a brand-new recruitable unit."))
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.kind = QComboBox()
        self.kind.addItems(["All", "Unique", "Human class", "Monster class", "Other / NPC", "Added by mod"])
        self.kind.currentIndexChanged.connect(self._filter)
        ll.addWidget(self.kind)
        self.search = SearchBox("Search characters / classes…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        b = QPushButton("✨ New character / class…")
        b.setObjectName("primary")
        b.clicked.connect(self.new_unit)
        ll.addWidget(b)
        split.addWidget(left)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form = QWidget()
        self.scroll.setWidget(self.form)
        self.form_lay = QVBoxLayout(self.form)
        split.addWidget(self.scroll)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        rl.addWidget(self.title)
        self.preview = ImageView()
        self.preview.setBackgroundBrush(QColor(40, 90, 60))
        rl.addWidget(self.preview, 1)
        self.portrait = ImageView()
        self.portrait.setBackgroundBrush(QColor(30, 28, 40))
        rl.addWidget(self.portrait, 1)
        b = QPushButton("🎨 Edit this sprite / colors")
        b.clicked.connect(self.edit_sprite)
        rl.addWidget(b)
        b = QPushButton("🙂 Face picture…")
        b.setToolTip("New characters only: the face shown in the status panel, in battle and as the character list "
                     "icon. Without one they use the faces of the character they were copied from.")
        b.clicked.connect(self.set_face)
        rl.addWidget(b)
        b = QPushButton("📤 Share this character…")
        b.setToolTip("Export the mod that holds this character as a .zip anyone with the D5 Mod Kit can import "
                     "(Home › Import). A later version you share installs as an update.")
        b.clicked.connect(self.share_character)
        rl.addWidget(b)
        for text, fn in [("💾 Save", self.save), ("↺ Revert this character", self.revert),
                         ("Discard unsaved", self.discard)]:
            b = QPushButton(text)
            if text.startswith("💾"):
                b.setObjectName("primary")
            b.clicked.connect(fn)
            rl.addWidget(b)
        self.status = QLabel()
        self.status.setObjectName("muted")
        rl.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([300, 820, 360])
        lay.addWidget(split, 1)
        self._loaded = False
        self.svc.table_changed.connect(lambda m: m == CHAR and self._loaded and self._populate())
        ws.file_changed.connect(lambda v: v.startswith("Anime/") and self.__dict__.pop("_pv_cache", None))
        ws.active_mod_changed.connect(lambda _: self._loaded and self._populate())

    # ================================================================== list
    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self._populate()

    def table(self):
        return self.svc.table(CHAR)

    def lookups(self):
        if self._names is None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._names = {"magic": sorted(table_names(self.svc, "magic.dat").items()),
                               "evility": sorted(table_names(self.svc, "Skill.dat").items()),
                               "overload": sorted(table_names(self.svc, "OverlordSkill.dat").items())}
                # hover descriptions of skills, evilities and Overloads
                for key, member in (("magic", "magic.dat"), ("evility", "Skill.dat"),
                                    ("overload", "OverlordSkill.dat")):
                    set_choice_tips(self._names[key], self.svc.ref_tooltips(member))
            finally:
                QApplication.restoreOverrideCursor()
        return self._names

    def _populate(self):
        cur = self.row_index
        self.list.blockSignals(True)
        self.list.clear()
        t = self.table()
        base = len(self.svc.vanilla(CHAR).rows)
        tips = self.svc.ref_tooltips(CHAR)
        for i, r in enumerate(t.rows):
            name, title = r["name_EN"], r["title_EN"]
            if not name and not title:
                continue
            it = QListWidgetItem(f"{name} — {title}" if title and title != name else name)
            it.setData(Qt.ItemDataRole.UserRole, i)
            desc = tips.get(r["id"], "").replace("<qt>", "").replace("</qt>", "")
            it.setToolTip(f"<qt>{desc + '<br>' if desc else ''}"
                          f"<span style='color:#9aa4b8'>id {r['id']}  ·  row {i}  ·  sprite anm{r['sprite_id']:05d}</span></qt>")
            added = i >= base
            if added:
                it.setForeground(QBrush(QColor("#5fe0a0")))
            elif bytes(r.raw) != bytes(self.svc.vanilla(CHAR).rows[i].raw):
                it.setForeground(QBrush(QColor("#e0457b")))
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._filter()
        if cur is not None:
            for k in range(self.list.count()):
                if self.list.item(k).data(Qt.ItemDataRole.UserRole) == cur:
                    self.list.setCurrentRow(k)
                    break
        if self.list.currentRow() < 0:
            for k in range(self.list.count()):       # never open on an empty editor
                if not self.list.item(k).isHidden():
                    self.list.setCurrentRow(k)
                    break

    def _filter(self, *a):
        t = self.search.text().lower()
        kind = self.kind.currentText()
        base = len(self.svc.vanilla(CHAR).rows)
        rows = self.table().rows
        for k in range(self.list.count()):
            it = self.list.item(k)
            i = it.data(Qt.ItemDataRole.UserRole)
            cid = rows[i]["id"]
            ok = not t or t in it.text().lower() or t == str(cid)
            if kind == "Added by mod":
                ok = ok and i >= base
            elif kind != "All":
                ok = ok and kind_of(cid) == kind
            it.setHidden(not ok)

    def _pick(self, it, prev=None):
        if not it:
            return
        self.row_index = it.data(Qt.ItemDataRole.UserRole)
        self._build_form()
        # debounce: while scrolling quickly through the list only the final selection is rendered
        if not hasattr(self, "_pv_timer"):
            from PyQt6.QtCore import QTimer
            self._pv_timer = QTimer(self)
            self._pv_timer.setSingleShot(True)
            self._pv_timer.timeout.connect(self._preview)
        self._pv_timer.start(90)

    # ================================================================== form
    def _clear(self):
        while self.form_lay.count():
            w = self.form_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _row(self):
        return self.table().rows[self.row_index]

    def _spin(self, name, lo=None, hi=None, tip=None):
        f = self._row().field(name)
        s = QSpinBox()
        from d5lib.database import _range
        a, b = _range(f.type)
        s.setRange(max(a, -2147483647) if lo is None else lo, min(b, 2147483647) if hi is None else hi)
        s.setToolTip(tip or f.desc or name)
        s.valueChanged.connect(lambda v, n=name: self._loading or self._set(n, v))
        s.setMinimumWidth(70)
        s.setMaximumWidth(130)
        self.widgets[name] = ("spin", s)
        return s

    def _text(self, name):
        e = QLineEdit()
        e.setMaxLength(self._row().field(name).size - 1)
        e.editingFinished.connect(lambda n=name, e=e: self._loading or self._set(n, e.text()))
        self.widgets[name] = ("text", e)
        return e

    def _combo(self, name, choices, setter=None):
        c = SearchCombo(choices)
        fn = setter or self._set
        c.activated.connect(lambda _, n=name, c=c: self._loading or fn(n, c.value()))
        c.lineEdit().editingFinished.connect(lambda n=name, c=c: self._loading or fn(n, c.value()))
        self.widgets[name] = ("combo", c)
        return c

    def _load_values(self):
        """Put the selected row's values into the (already built) form — no widget churn."""
        r = self._row()
        self._loading = True
        try:
            for name, (kind, w) in self.widgets.items():
                v = r[name]
                if kind == "spin":
                    w.setValue(int(v))
                elif kind == "text":
                    w.setText(v)
                else:
                    w.set_value(v)
        finally:
            self._loading = False
        if getattr(self, "voice_box", None) is not None:
            self.voice_box.load(r)
        cid = r["id"]
        self.title.setText(f"{r['name_EN']} — {r['title_EN']}\nid {cid} · {kind_of(cid)}")
        self.id_label.setText(f"{cid}   (maps and quests refer to this id)")

    def _set(self, name, v):
        r = self._row()
        try:
            if r[name] == v:
                return
            r.set(name, v, truncate=True) if r.field(name).type == "str" else r.set(name, v)
        except Exception as e:
            QMessageBox.warning(self, "Invalid value", str(e))
            return
        if name in dbpatch.EVILITIES:            # the game uses evility1..N only (the install also closes gaps)
            r.set("evility_count", sum(1 for f in dbpatch.EVILITIES if r[f]))
        self.svc.mark_dirty(CHAR)
        self.status.setText("● unsaved changes")
        if name in ("sprite_id", "tier", "name_EN", "title_EN"):
            self._preview()

    def _build_form(self):
        if self._built:
            self._load_values()
            return
        self._built = True
        self._loading = True
        lk = self.lookups()

        g = QGroupBox("Identity")
        f = QFormLayout(g)
        f.addRow("Name (English)", self._text("name_EN"))
        f.addRow("Title / class (English)", self._text("title_EN"))
        other = QPushButton("Other languages…")
        other.clicked.connect(self._langs_dialog)
        f.addRow("", other)
        self.id_label = QLabel()
        f.addRow("Id", self.id_label)
        f.addRow("Description id", self._spin("help_id", tip="charhelp.dat entry (edit texts in Database Editor → Character descriptions)"))
        self.form_lay.addWidget(g)

        g = QGroupBox("Sprite")
        f = QFormLayout(g)
        f.addRow("Sprite file (anm number)", self._spin("sprite_id", 0, 32767, "Battle sprite = anmNNNNN; portrait = +10000"))
        f.addRow("Color variant / tier", self._spin("tier", 0, 255, "Palette used from the sprite (generic class tiers)"))
        self.form_lay.addWidget(g)

        from ..voiceui import VoiceBox
        self.voice_box = VoiceBox(self)
        self.form_lay.addWidget(self.voice_box)

        g = QGroupBox("Quick setup")
        ql = QGridLayout(g)
        ql.addWidget(_label("Start from", "Take the numbers of one of the game's playable characters: base stats, "
                                          "aptitudes, movement. Fine-tune them below afterwards."), 0, 0)
        self.preset = QComboBox()
        for key, label, desc, cid in charstudio.PRESETS:
            self.preset.addItem(label, key)
            self.preset.setItemData(self.preset.count() - 1, desc, Qt.ItemDataRole.ToolTipRole)
        ql.addWidget(self.preset, 0, 1)
        b = QPushButton("Apply preset")
        b.setToolTip("Base stats, aptitudes and movement from the preset (this character's other settings stay)")
        b.clicked.connect(self.apply_preset)
        ql.addWidget(b, 0, 2)
        b = QPushButton("📋 Copy from another…")
        b.setToolTip("Copy chosen parts (stats, aptitudes, movement, mastery, resistances, evilities, Overload, "
                     "skills) of any character or class, with a power %")
        b.clicked.connect(self.copy_from)
        ql.addWidget(b, 0, 3)
        ql.setColumnStretch(4, 1)
        self.form_lay.addWidget(g)

        g = QGroupBox("Base stats  ·  aptitudes (%)")
        gl = QGridLayout(g)
        for k, s in enumerate(STATS):
            gl.addWidget(_label(s, HELP[s]), 0, k)
            gl.addWidget(self._spin(f"base_{s}", tip=f"{HELP[s]}\n\n{HELP['base']}"), 1, k)
            gl.addWidget(self._spin(f"apt_{s}", tip=f"{HELP[s]}\n\n{HELP['apt']}"), 2, k)
        gl.addWidget(QLabel("row 1 = base value, row 2 = aptitude %"), 3, 0, 1, 8)
        self.form_lay.addWidget(g)

        g = QGroupBox("Movement && combat")
        gl = QGridLayout(g)
        for k, (n, lab) in enumerate([("MOV", "Move"), ("JMP", "Jump"), ("throw", "Throw"), ("counter", "Counter"),
                                      ("crit", "Critical %"), ("attack_range", "Attack range")]):
            gl.addWidget(_label(lab, HELP[n]), 0, k)
            gl.addWidget(self._spin(n, tip=HELP[n]), 1, k)
        self.form_lay.addWidget(g)

        g = QGroupBox("Weapon mastery (starting rank)")
        gl = QGridLayout(g)
        for k, (n, lab) in enumerate(WEAPONS):
            gl.addWidget(_label(lab, HELP["mastery"]), (k // 5) * 2, k % 5)
            gl.addWidget(self._spin(f"mastery_{n}", tip=HELP["mastery"]), (k // 5) * 2 + 1, k % 5)
        self.form_lay.addWidget(g)

        g = QGroupBox("Resistances (%)")
        gl = QGridLayout(g)
        res = [("res_fire", "Fire"), ("res_wind", "Wind"), ("res_ice", "Ice"), ("res_star", "Star")] + \
              [(f"wres_{n}", lab) for n, lab in WEAPONS[:7]] + [("wres_monster", "Monster")]
        for k, (n, lab) in enumerate(res):
            tip = HELP["res"] if n.startswith("res_") else HELP["wres"]
            gl.addWidget(_label(lab, tip), (k // 6) * 2, k % 6)
            gl.addWidget(self._spin(n, -100, 100, tip), (k // 6) * 2 + 1, k % 6)
        self.form_lay.addWidget(g)

        g = QGroupBox("Evilities && Overload")
        f = QFormLayout(g)
        for k in range(1, 5):
            f.addRow(_label(f"Evility {k}", HELP["evility"]), self._combo(f"evility{k}", lk["evility"]))
        f.addRow(_label("Overload", HELP["overload_id"]), self._combo("overload_id", lk["overload"]))
        b = QPushButton("✨ New evility of their own…")
        b.setToolTip("An evility with this character's own name and description that works like an evility you "
                     "choose (its numbers are that evility's). It goes into one of the four evility slots.")
        b.clicked.connect(self.new_evility)
        f.addRow("", b)
        self.form_lay.addWidget(g)

        g = QGroupBox("Learned skills (skill · level learned)")
        gl = QGridLayout(g)
        for k in range(1, 17):
            c = self._combo(f"learn{k}_skill", lk["magic"], self._set_skill)
            lv = self._spin(f"learn{k}_level", 0, 9999, "Level at which the skill is learned")
            gl.addWidget(c, (k - 1) // 2, ((k - 1) % 2) * 2)
            gl.addWidget(lv, (k - 1) // 2, ((k - 1) % 2) * 2 + 1)
        row = QHBoxLayout()
        b = QPushButton("✨ New skill of their own…")
        b.setToolTip("A new skill for this character: a copy of any skill (numbers and animation) with its own name "
                     "and id, learned at a level you choose. The skill editor can then give it its own animation.")
        b.clicked.connect(self.new_skill)
        row.addWidget(b)
        b = QPushButton("🎬 Edit a skill's animation…")
        b.setToolTip("Open one of this character's skills in the skill editor (Skills & Animations); a button "
                     "there brings you back here")
        b.clicked.connect(self.edit_skill_animation)
        row.addWidget(b)
        row.addStretch(1)
        gl.addLayout(row, 8, 0, 1, 4)
        self.form_lay.addWidget(g)

        g = QGroupBox("Rewards when defeated")
        gl = QGridLayout(g)
        for k, (n, lab) in enumerate([("exp_value", "EXP"), ("hl_value", "HL"), ("mana_value", "Mana")]):
            gl.addWidget(_label(lab, HELP[n]), 0, k)
            gl.addWidget(self._spin(n, tip=HELP[n]), 1, k)
        self.form_lay.addWidget(g)
        more = QLabel("Every other field of this character is available in Database Editor → Characters & Classes.")
        more.setObjectName("muted")
        more.setWordWrap(True)
        self.form_lay.addWidget(more)
        self.form_lay.addStretch(1)
        self._loading = False
        self._load_values()

    # ================================================================== character studio
    def _refresh_row(self):
        self.svc.mark_dirty(CHAR)
        self.status.setText("● unsaved changes")
        self._load_values()
        self._preview()

    def apply_preset(self):
        if self.row_index is None:
            return
        key = self.preset.currentData()
        _, label, desc, cid = charstudio.preset(key)
        src = next((r for r in self.svc.vanilla(CHAR).rows if r["id"] == cid), None)
        if src is None:
            return
        n = charstudio.copy_fields(self._row(), src, ("base", "apt", "move"))
        self._refresh_row()
        self.ws.log(f"{self._row()['name_EN']}: preset '{label}' ({n} values changed; save to keep them)")

    def copy_from(self):
        if self.row_index is None:
            return
        dlg = CopyFromDialog(self, self._row())
        if not dlg.exec():
            return
        src_i, groups, power = dlg.values()
        if src_i is None or not groups:
            return
        src = self.table().rows[src_i]
        n = charstudio.copy_fields(self._row(), src, groups, power)
        if "evilities" in groups:
            r = self._row()
            r.set("evility_count", sum(1 for f in dbpatch.EVILITIES if r[f]))
        self._refresh_row()
        self.ws.log(f"{self._row()['name_EN']}: copied {', '.join(groups)} from {src['name_EN']} "
                    f"({n} values{'' if power == 100 else f', base stats at {power}%'}; save to keep them)")

    def new_skill(self):
        if self.row_index is None:
            return
        r = self._row()
        dlg = NewSkillDialog(self, r, self.lookups()["magic"])
        if not dlg.exec():
            return
        v = dlg.values()
        if not v["copy_of"]:
            return QMessageBox.warning(self, "New skill", "Choose the skill to start from.")
        mod = self.ws.require_mod(self)
        if not mod:
            return
        try:
            sid = charstudio.new_skill(self.svc, self.ws.fs, mod, r, int(v["copy_of"]), v["name"], v["desc"],
                                       v["level"], v["sp"], mods=self.ws.mods.all_mods())
        except Exception as e:
            return error_box(self, "Could not make the skill", e)
        self.svc.commit("magic.dat", self)
        self.svc.commit(CHAR, self)
        self._names = None                         # the skill lists know the new skill now
        self._built = False
        self._clear()
        self._build_form()
        self.ws.log(f"New skill {sid} '{v['name']}' (a copy of skill {v['copy_of']}), learned by {r['name_EN']} at "
                    f"level {v['level']} -- saved into {mod.name}")
        if v["animate"]:
            self.open_in_skill_editor(sid)

    def new_evility(self):
        if self.row_index is None:
            return
        r = self._row()
        dlg = NewEvilityDialog(self, r, self.lookups()["evility"])
        if not dlg.exec():
            return
        v = dlg.values()
        if not v["like"]:
            return QMessageBox.warning(self, "New evility", "Choose the evility it works like.")
        mod = self.ws.require_mod(self)
        if not mod:
            return
        try:
            eid = charstudio.new_evility(self.svc, mod, r, int(v["like"]), v["name"], v["desc"], v["slot"],
                                         mods=self.ws.mods.all_mods())
        except Exception as e:
            return error_box(self, "Could not make the evility", e)
        self.svc.commit("Skill.dat", self)
        self.svc.commit(CHAR, self)
        self._names = None
        self._built = False
        self._clear()
        self._build_form()
        self.ws.log(f"New evility {eid} '{v['name']}' for {r['name_EN']} (works like evility {v['like']}) -- saved "
                    f"into {mod.name}")

    def edit_skill_animation(self):
        if self.row_index is None:
            return
        r = self._row()
        names = dict(self.lookups()["magic"])
        have = [(r[f"learn{k}_skill"], names.get(r[f"learn{k}_skill"], str(r[f"learn{k}_skill"])))
                for k in range(1, 17) if r[f"learn{k}_skill"]]
        if not have:
            return info_box(self, "Skills", "This character learns no skill yet.")
        from PyQt6.QtWidgets import QInputDialog
        labels = [f"{n}  ({sid})" for sid, n in have]
        text, ok = QInputDialog.getItem(self, "Edit a skill's animation", "Skill:", labels, 0, False)
        if ok:
            self.open_in_skill_editor(have[labels.index(text)][0])

    def open_in_skill_editor(self, sid):
        r = self._row()
        page = self.main.show_page("skills")
        if hasattr(page, "open_skill"):
            page.open_skill(int(sid), back=(int(r["id"]), r["name_EN"]))

    def _owner_mods(self, cid):
        """mods whose char.dat patch adds or fills in character cid"""
        van_ids = [r["id"] for r in self.svc.vanilla(CHAR).rows]
        out = []
        for m in self.ws.mods.enabled_mods():
            p = m.load_patch("db", "char.dat.json") or {}
            if any(int(r.get("id", -1)) == cid for r in p.get("added") or [] if isinstance(r, dict)) or \
                    any(int(i) < len(van_ids) and van_ids[int(i)] == cid for i in (p.get("rows") or {})):
                out.append(m)
        return out

    def share_character(self):
        if self.row_index is None:
            return
        r = self._row()
        cid = int(r["id"])
        owners = self._owner_mods(cid)
        if not owners:
            return info_box(self, "Share", f"{r['name_EN']} is the game's own character: no mod holds it. Share the "
                                           "mod with your changes from the Home page instead.")
        mod = owners[-1]
        from d5lib import modinfo
        others = [x for x in modinfo.summary(mod) if not x.startswith(("🧙", "📜", "📊", "📁", "🔗"))]
        if others and QMessageBox.question(
                self, "Share", f"{r['name_EN']} is in the mod '{mod.name}', which is shared as a whole. It also "
                               "holds:\n\n" + "\n".join(others) + "\n\nShare it anyway?") \
                != QMessageBox.StandardButton.Yes:
            return
        home = self.main.pages.get("home", {}).get("widget")
        if home is None:
            home = self.main.show_page("home")
            self.main.show_page("characters")
        home.export_mod(mod)

    def select_character(self, cid):
        """show character cid (e.g. coming back from the skill editor)"""
        if not self._loaded:
            self.on_show()
        self.search.clear()
        self.kind.setCurrentText("All")
        for k in range(self.list.count()):
            it = self.list.item(k)
            if self.table().rows[it.data(Qt.ItemDataRole.UserRole)]["id"] == int(cid):
                self.list.setCurrentRow(k)
                self.list.scrollToItem(it)
                return True
        return False

    def _set_skill(self, name, v):
        self._set(name, v)
        r = self._row()
        r.set("learn_count", sum(1 for k in range(1, 17) if r[f"learn{k}_skill"]))

    def _langs_dialog(self):
        r = self._row()
        dlg = QDialog(self)
        dlg.setWindowTitle("Names in all languages")
        f = QFormLayout(dlg)
        eds = {}
        for L in LANGS:
            a, b = QLineEdit(r[f"name_{L}"]), QLineEdit(r[f"title_{L}"])
            eds[L] = (a, b)
            row = QHBoxLayout()
            row.addWidget(a)
            row.addWidget(b)
            f.addRow(L, row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec():
            for L, (a, b) in eds.items():
                self._set(f"name_{L}", a.text())
                self._set(f"title_{L}", b.text())
            self._build_form()

    # ================================================================== preview
    def _preview(self):
        if self.row_index is None:
            return
        r = self._row()
        num, tier = r["sprite_id"], r["tier"]
        cache = self.__dict__.setdefault("_pv_cache", {})
        key = (num, tier)
        self._pv_want = key
        if key in cache:
            self._show_preview(cache[key])
            return
        if getattr(self, "_pv_worker", None) is not None and self._pv_worker.isRunning():
            return  # the running job re-checks _pv_want when it finishes
        mod_files = set(self.ws.active_mod.list_files()) if self.ws.active_mod else set()
        from ..common import Worker
        self._pv_worker = Worker(lambda: (key, self._render_sprite(num, tier, mod_files, True),
                                          self._render_sprite(num + 10000, tier, mod_files, False)))
        self._pv_worker.done.connect(self._preview_done)
        self._pv_worker.start()

    def _preview_done(self, result):
        from ..common import pil_to_pixmap
        key, body, portrait = result
        cache = self.__dict__.setdefault("_pv_cache", {})
        cache[key] = (pil_to_pixmap(body) if body else None, pil_to_pixmap(portrait) if portrait else None)
        if len(cache) > 200:
            cache.pop(next(iter(cache)))
        if key == self._pv_want:
            self._show_preview(cache[key])
        else:
            self._preview()  # selection moved on while rendering

    def _show_preview(self, pair):
        body, portrait = pair
        self.preview.set_image(body, fit=True)
        self.portrait.set_image(portrait, fit=True)

    def _render_sprite(self, num, tier, mod_files, battle):
        """Runs in a worker thread: returns a PIL image (pixmaps are made on the GUI thread)."""
        try:
            name = f"/anm{num:05d}.lzs"
            vp = next((f for f in mod_files if f.startswith("Anime/") and f.endswith(name)), None)
            vp = vp or sprites.sprite_vpath(self.ws.fs, num, self.ws.language)
            a = anm.parse(self.ws.read(vp))
            p = sprites.preview_file(self.ws.fs, a, self.ws.log) if battle else a
            anims = [x for x in anm.list_animations(p) if x["layers"] and (x["loop"] or not battle)]
            if not anims:
                return None
            pal = min(tier, max(0, len(a.palettes) - 1))
            return anm.render_frame(p, anims[0]["index"], 0, pal, scale=2.0 if battle else 1.0)
        except Exception:
            return None

    def _mod_sprite(self, num):
        mod = self.ws.active_mod
        if mod:
            for f in mod.list_files():
                if f.endswith(f"/anm{num:05d}.lzs") and f.startswith("Anime/"):
                    return f
        return None

    def edit_sprite(self):
        if self.row_index is None:
            return
        r = self._row()
        page = self.main.show_page("sprites")
        page.open_sprite(r["sprite_id"], r["tier"], f"{r['name_EN']} — {r['title_EN']}", r["id"] >= 1000)
        page.tabs.setCurrentIndex(0)

    def set_face(self):
        """Face picture of a new unique character (d5lib.newchars): status panel, battle face, list icon."""
        from PyQt6.QtWidgets import QFileDialog
        from d5lib import newchars, outfits
        mod = self.ws.active_mod
        if self.row_index is None or not mod:
            return
        r = self._row()
        van = {v["id"]: v for v in self.svc.vanilla(CHAR).rows}
        if not newchars.is_new_character(r, van, outfits.used_slots(mod)):
            info_box(self, "Face picture", "Face pictures are for new unique characters (made with “New character”). "
                     "Outfits get theirs on the Outfits page.")
            return
        p, _ = QFileDialog.getOpenFileName(self, "Face picture (square)", "", "Images (*.png *.jpg *.webp)")
        if not p:
            return
        mirror = QMessageBox.question(
            self, "Face picture", "Mirror the picture?\n\nThe game's faces look to the left; "
            "choose Yes if yours looks to the right.") == QMessageBox.StandardButton.Yes
        newchars.set_face(mod, r["id"], p, mirror)
        self.ws.log(f"face picture of {r['name_EN']} ({r['id']}) set")
        info_box(self, "Face picture", "Face picture set (status panel, battle and character list icon). "
                 "Press Install to see it in game.")

    # ================================================================== save
    def save(self):
        if self.svc.commit(CHAR, self):
            for extra in ("charhelp.dat", "Quest.dat", "JobRank.dat"):
                if self.svc.is_dirty(extra):
                    self.svc.commit(extra, self)
            self.status.setText("")
            self.ws.log(f"Saved characters into '{self.ws.active_mod.name}'. Install (bottom left) to see them in game.")

    def revert(self):
        if self.row_index is None:
            return
        v = self.svc.vanilla(CHAR)
        if self.row_index < len(v.rows):
            self.table().rows[self.row_index] = v.rows[self.row_index].copy()
            self.svc.mark_dirty(CHAR)
            self._build_form()
            self._preview()

    def discard(self):
        for m in (CHAR, "charhelp.dat", "Quest.dat", "JobRank.dat"):
            self.svc.discard(m)
        self._populate()

    # ================================================================== wizard
    def new_unit(self):
        if self.row_index is None:
            QMessageBox.information(self, "New unit", "First select the character or class to use as a template.")
            return
        dlg = NewUnitDialog(self, self._row())
        if not dlg.exec():
            return
        v = dlg.values()
        if v.get("own_mod"):
            if self.svc.dirty_members() and not self.svc.commit_all(self):
                return
            kind = "class" if v["generic"] else "character"
            mod = self.ws.mods.create(v["name"], self.ws.settings.get("author", ""),
                                      f"New {kind} {v['name']}" + (f": {v['desc'][0]}" if v["desc"] and v["desc"][0]
                                                                   else ""))
            mod.meta["category"] = "classes" if v["generic"] else "characters"
            mod.save_meta()
            self.ws.set_active_mod(mod)
            self.ws.mods_changed.emit()
            self.ws.log(f"New mod '{mod.name}' for {v['name']}: your edits are saved into it.")
        mod = self.ws.require_mod(self)
        if not mod:
            return
        if v.get("outfit") is not None:
            return self._unit_from_outfit(mod, v)
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            msg = create_unit(self, v)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            error_box(self, "Could not create unit", e)
            return
        QApplication.restoreOverrideCursor()
        self._populate()
        self.kind.setCurrentText("Added by mod")
        info_box(self, "Unit created", msg)

    def _unit_from_outfit(self, mod, v):
        """a new character with an outfit's look (charstudio.outfit_to_character; a Disgaea RPG outfit is drawn
        again from its unit, which takes a little while)"""
        src = v["outfit"]
        if self.svc.dirty_members():
            self.svc.commit_all(self)
        quest = dict(title=v["quest_title"], client=v["quest_client"], text=v["quest_text"]) if v["quest"] else None
        prog = QProgressDialog(f"Making {v['name']} with the look of {src['who']}'s outfit '{src['name']}'…",
                               None, 0, 0, self)
        prog.setWindowTitle("New character")
        prog.setMinimumDuration(0)
        prog.show()
        QApplication.processEvents()
        lines = []
        try:
            res = charstudio.outfit_to_character(self.ws.fs, mod, src, v["name"], v["title"], v["desc"], quest,
                                                 hide=v["hide_outfit"], log=lines.append)
        except Exception as e:
            prog.close()
            return error_box(self, "Could not create the character", e)
        prog.close()
        self.svc.reload()
        self.ws.file_changed.emit("Anime/")
        self._names = None
        self._populate()
        if v.get("preset"):
            self.select_character(res["id"])
            self.apply_preset_key(v["preset"])
            self.svc.commit(CHAR, self)
        self.select_character(res["id"])
        msg = (f"'{v['name']}' (id {res['id']}) has the look of {src['who']}'s outfit '{src['name']}' "
               f"(sprite anm{res['sprite']:05d})" + (f" and the recruit quest #{res['quest']}" if res.get("quest") else "")
               + ".\n\n" + ("The outfit is hidden from the Outfit menu by this mod; switch the mod off to bring it "
                              "back. " if v["hide_outfit"] else "")
               + "Stats, skills and evilities come from the outfit's character: change them on this page.\n\n"
               + "Everything is saved in your mod. Press Install to try it in game.")
        info_box(self, "Character created", msg)

    def apply_preset_key(self, key):
        i = self.preset.findData(key) if hasattr(self, "preset") else -1
        if i >= 0:
            self.preset.setCurrentIndex(i)
            self.apply_preset()


class NewUnitDialog(QDialog):
    def __init__(self, page, template_row):
        super().__init__(page)
        self.setWindowTitle("New character / class")
        self.resize(560, 520)
        t = template_row
        generic = 1000 <= t["id"] < 3000
        f = QFormLayout(self)
        f.addRow(QLabel(f"<b>Template:</b> {t['name_EN']} — {t['title_EN']} (id {t['id']})<br>"
                        "Stats, skills and evilities are copied; change them afterwards on this page."))
        self.unique = QRadioButton("Unique character (one unit, recruited once)")
        self.klass = QRadioButton("Generic class (6 tiers, created at the Netherworld registrar)")
        (self.klass if generic else self.unique).setChecked(True)
        if not generic:
            self.klass.setEnabled(False)
            self.klass.setToolTip("Pick a generic class (e.g. Warrior) as template to create a new class")
        f.addRow(self.unique)
        f.addRow(self.klass)
        self.name = QLineEdit(t["name_EN"] + " II")
        self.title = QLineEdit(t["title_EN"])
        f.addRow("Name (class name for classes)", self.name)
        f.addRow("Title (tier-1 title for classes)", self.title)
        self.desc = QTextEdit()
        self.desc.setPlaceholderText("Up to 3 short lines of description")
        self.desc.setFixedHeight(70)
        f.addRow("Description", self.desc)
        self.clone_sprite = QCheckBox("Give it its own copy of the sprite (so you can repaint / recolor it)")
        self.clone_sprite.setChecked(True)
        f.addRow(self.clone_sprite)
        # the look of an outfit (a unique character only)
        self.outfits = charstudio.outfit_sources(page.ws.mods.enabled_mods(), {
            r["id"]: r["name_EN"] for r in page.table().rows})
        self.look = QComboBox()
        self.look.addItem("The template's look", None)
        for o in sorted(self.outfits, key=lambda o: (o["who"].lower(), o["name"].lower())):
            label = f"{o['who']} — {o['name']}" + ("   (Disgaea RPG)" if o["drpg_uid"] is not None else "")
            self.look.addItem(label, o)
            self.look.setItemData(self.look.count() - 1, f"Outfit {o['outfit']} from the mod {o['mod'].name}",
                                  Qt.ItemDataRole.ToolTipRole)
        self.look.setToolTip("A new character can wear an outfit's look as its own: a Disgaea RPG outfit is drawn "
                             "again from its unit as a complete character; another outfit's sprite is copied. "
                             "Stats, skills and evilities come from the outfit's character.")
        f.addRow("Look", self.look)
        self.hide_outfit = QCheckBox("Take that outfit out of the Outfit menu (your mod hides it; the outfit's mod "
                                     "is not changed)")
        self.hide_outfit.setToolTip("Units already wearing it keep it and can still switch back to Default. "
                                    "Switch your mod off and the outfit is listed again.")
        f.addRow(self.hide_outfit)
        self.own_mod = QCheckBox("Save it in a new mod of its own (recommended: easy to share, update and switch "
                                 "off on its own)")
        self.own_mod.setChecked(True)
        f.addRow(self.own_mod)
        self.preset_box = QComboBox()
        self.preset_box.addItem("Same as the template", None)
        for key, label, desc, cid in charstudio.PRESETS:
            self.preset_box.addItem(label, key)
            self.preset_box.setItemData(self.preset_box.count() - 1, desc, Qt.ItemDataRole.ToolTipRole)
        f.addRow("Stats", self.preset_box)

        def look_changed(*_):
            o = self.look.currentData()
            self.hide_outfit.setEnabled(o is not None)
            self.clone_sprite.setEnabled(o is None)
            self.klass.setEnabled(o is None and generic)
            if o is not None:
                self.unique.setChecked(True)
                if self.name.text().endswith(" II") or not self.name.text().strip():
                    self.name.setText(o["name"])
        self.look.currentIndexChanged.connect(look_changed)
        look_changed()
        self.quest = QCheckBox("Make it recruitable with a new quest at the Quest shop")
        self.quest.setChecked(True)
        f.addRow(self.quest)
        self.quest_title = QLineEdit("A New Ally")
        self.quest_client = QLineEdit(t["name_EN"] + " II")
        self.quest_text = QLineEdit("Complete this request and I'll join you!")
        f.addRow("Quest title", self.quest_title)
        f.addRow("Quest client", self.quest_client)
        f.addRow("Quest text", self.quest_text)

        def name_changed(text, last=[self.name.text()]):
            if self.quest_client.text() in ("", last[0]):           # the client follows the name until edited
                self.quest_client.setText(text)
            last[0] = text
        self.name.textChanged.connect(name_changed)
        self.quest_client.setText(self.name.text())
        note = QLabel("New ids are always higher than every existing one, so your existing saves stay valid.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        return {"generic": self.klass.isChecked(), "name": self.name.text().strip() or "New Unit",
                "title": self.title.text().strip(), "desc": self.desc.toPlainText().strip().split("\n")[:3],
                "clone_sprite": self.clone_sprite.isChecked(), "quest": self.quest.isChecked(),
                "quest_title": self.quest_title.text().strip(), "quest_client": self.quest_client.text().strip(),
                "quest_text": self.quest_text.text().strip(), "outfit": self.look.currentData(),
                "hide_outfit": self.hide_outfit.isChecked() and self.look.currentData() is not None,
                "preset": self.preset_box.currentData(), "own_mod": self.own_mod.isChecked()}


class CopyFromDialog(QDialog):
    """copy parts of another character or class onto this one"""

    def __init__(self, page, row):
        super().__init__(page)
        self.setWindowTitle(f"Copy into {row['name_EN']}")
        self.resize(520, 360)
        f = QFormLayout(self)
        rows = page.table().rows
        choices = [(i, f"{r['name_EN']} — {r['title_EN']}  ({r['id']})") for i, r in enumerate(rows)
                   if r["name_EN"] and i != page.row_index]
        self.src = SearchCombo(choices)
        self.src.setToolTip("Type to search any character or class")
        f.addRow("From", self.src)
        self.boxes = {}
        grid = QGridLayout()
        for k, (key, label) in enumerate(charstudio.GROUP_LABELS):
            cb = QCheckBox(label)
            cb.setChecked(key in ("base", "apt", "move"))
            self.boxes[key] = cb
            grid.addWidget(cb, k // 2, k % 2)
        f.addRow("What", grid)
        self.power = QSpinBox()
        self.power.setRange(10, 500)
        self.power.setValue(100)
        self.power.setSuffix(" %")
        self.power.setToolTip("Base stats are multiplied by this (100 % = the same numbers)")
        f.addRow("Power", self.power)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        v = self.src.value()
        return (int(v) if v not in (None, "") else None,
                [k for k, cb in self.boxes.items() if cb.isChecked()], self.power.value())


class NewEvilityDialog(QDialog):
    """an evility of a character's own (charstudio.new_evility)"""

    def __init__(self, page, row, evility_choices):
        super().__init__(page)
        self.setWindowTitle(f"New evility for {row['name_EN']}")
        self.resize(560, 330)
        self.page = page
        f = QFormLayout(self)
        note = QLabel("Your evility has its own name and description and works like an evility of the game you "
                      "choose here: in battle it does exactly what that one does, with its numbers.")
        note.setWordWrap(True)
        f.addRow(note)
        self.like = SearchCombo(evility_choices)
        self.like.setToolTip("Type to search the game's evilities; hover one to read what it does")
        self.like.currentIndexChanged.connect(self._fill_desc)
        f.addRow("Works like", self.like)
        self.name = QLineEdit(f"{row['name_EN']}'s Spirit")
        f.addRow("Name", self.name)
        self.desc = QLineEdit()
        self.desc.setToolTip("Shown in game; %d is replaced by the evility's number")
        f.addRow("Description", self.desc)
        self.slot = QComboBox()
        for k in range(1, 5):
            cur = row[f"evility{k}"]
            self.slot.addItem(f"Slot {k}" + (f" (replaces {dict(evility_choices).get(cur, cur)})" if cur else
                                               " (empty)"), k)
        free = next((k for k in range(1, 5) if not row[f"evility{k}"]), 4)
        self.slot.setCurrentIndex(free - 1)
        f.addRow("Slot", self.slot)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._fill_desc()

    def _fill_desc(self, *_):
        try:
            t = self.page.svc.table("Skill.dat")
            i = t.index_of(int(self.like.value() or 0))
            if i >= 0 and (not self.desc.text() or self.desc.isModified() is False):
                self.desc.setText(t.rows[i]["desc_EN"] or "")
        except Exception:
            pass

    def values(self):
        return {"like": self.like.value(), "name": self.name.text().strip() or "New Evility",
                "desc": self.desc.text().strip(), "slot": self.slot.currentData()}


class NewSkillDialog(QDialog):
    """a new skill of a character's own (charstudio.new_skill)"""

    def __init__(self, page, row, magic_choices):
        super().__init__(page)
        self.setWindowTitle(f"New skill for {row['name_EN']}")
        self.resize(560, 360)
        f = QFormLayout(self)
        f.addRow(QLabel("The new skill starts as a copy of another skill: its numbers (range, area, power, element) "
                        "and its animation. Give it a name here, its own animation in the skill editor, and its "
                        "numbers in Database Editor › Skills."))
        f.itemAt(0).widget().setWordWrap(True)
        self.base = SearchCombo(magic_choices)
        own = [row[f"learn{k}_skill"] for k in range(1, 17) if row[f"learn{k}_skill"]]
        if own:
            self.base.set_value(own[0])
        self.base.setToolTip("The skill whose numbers and animation the new one starts from")
        f.addRow("Start from", self.base)
        self.name = QLineEdit(f"{row['name_EN']}'s Special")
        f.addRow("Name", self.name)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("One line shown in the skill list (optional)")
        f.addRow("Description", self.desc)
        self.sp = QSpinBox()
        self.sp.setRange(0, 9999)
        self.sp.setSpecialValueText("as the skill it starts from")
        self.sp.setToolTip("SP cost (0 = keep the cost of the skill it starts from)")
        f.addRow("SP cost", self.sp)
        self.level = QSpinBox()
        self.level.setRange(1, 9999)
        self.level.setValue(1)
        f.addRow("Learned at level", self.level)
        self.animate = QCheckBox("Then open the skill editor to make its animation (a button there brings you back)")
        self.animate.setChecked(True)
        f.addRow(self.animate)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        return {"copy_of": self.base.value(), "name": self.name.text().strip() or "New Skill",
                "desc": self.desc.text().strip(), "sp": self.sp.value() or None, "level": self.level.value(),
                "animate": self.animate.isChecked()}


def _set_all_langs(row, prefix, text):
    for L in LANGS:
        if f"{prefix}_{L}" in row:
            row.set(f"{prefix}_{L}", text, truncate=True)


def free_sprite_number(fs, mod):
    used = sprites.used_sprite_numbers(fs)
    if mod:
        for f in mod.list_files():
            n = f.split("/")[-1]
            if n.startswith("anm") and n[3:8].isdigit():
                used.add(int(n[3:8]))
    n = 9000
    while n + 10001 <= 32767:
        if not {n, n + 1, n + 2, n + 10000, n + 10001} & used:
            return n
        n += 10
    raise RuntimeError("no free sprite number")


def clone_sprite_files(page, src, dst):
    """Copy anm src/src+1, the standing picture src+2 and portraits src+10000/+10001 to dst numbers in the active mod."""
    ws = page.ws
    done = []
    for a, b in [(src, dst), (src + 1, dst + 1), (src + 10000, dst + 10000), (src + 10001, dst + 10001)]:
        try:
            vp = page._mod_sprite(a) or sprites.sprite_vpath(ws.fs, a, ws.language)
            f = anm.parse(ws.read(vp))
        except KeyError:
            continue
        for blk in f.blocks:
            if blk.id == a:
                blk.id = b
        ws.write(f"Anime/ANM_HI_JP.dat/anm{b:05d}.lzs", f.to_bytes(), page)
        done.append(b)
    # the small standing picture N+2 (quest "has joined!" pop-up, lists): a loose file for mod sprites, otherwise
    # a block of the resident pack.  Without it the game shows a leftover picture.
    icon = None
    try:
        vp = page._mod_sprite(src + 2) or sprites.sprite_vpath(ws.fs, src + 2, ws.language)
        icon = anm.parse(ws.read(vp))
    except KeyError:
        from d5lib import outfits
        icon = outfits._resident_icon(ws.fs, src + 2)
    if icon is not None:
        for blk in icon.blocks:
            if blk.id == src + 2:
                blk.id = dst + 2
        ws.write(f"Anime/ANM_HI_JP.dat/anm{dst + 2:05d}.lzs", icon.to_bytes(), page)
        done.append(dst + 2)
    return done


UNIQUE_SLOTS = (970, 980, 990)       # "DLC Dummy" rows of char.dat, unused by the game


def free_unique_id(svc, mod=None, fs=None):
    """-> (id, row index to edit in place) of a free dummy row, or (id, None) for a new row, or None.  The ids come
    from slots.unique_pool (shared with outfits); ids any mod already uses are taken."""
    from d5lib import slots
    chars, van = svc.table(CHAR), svc.vanilla(CHAR)
    vname = {r["id"]: r["name_EN"] for r in van.rows}
    used = {r["id"] for r in chars.rows}
    if fs is None or mod is None:
        pool = [i for fam in UNIQUE_SLOTS for i in range(fam, fam + 10)]
        taken = slots.used_dummy_ids(mod, van) if mod else set()
    else:
        pool = slots.free_unique_ids(fs, mod, van)
        taken = set()
    for uid in pool:
        if uid in taken:
            continue
        for i, r in enumerate(chars.rows):
            if r["id"] == uid:
                # a dummy row still as the game has it: edit it in place
                if uid in slots.DUMMY_ROWS and r["name_EN"] == vname.get(uid) and r["sprite_id"] == uid:
                    return uid, i
                break
        else:
            if uid not in used:
                return uid, None
    return None


def create_unit(page, v):
    svc = page.svc
    chars = svc.table(CHAR)
    t_index = page.row_index
    tmpl = chars.rows[t_index]
    lines = []
    new_rows = []
    if v["generic"]:
        fam = (tmpl["id"] // 10) * 10
        src_rows = [i for i, r in enumerate(chars.rows) if fam <= r["id"] <= fam + 5]
        # new family id above every existing char and JobRank id
        jr = svc.table("JobRank.dat")
        top = max([r["id"] for r in chars.rows] + [r["id"] for r in jr.rows])
        new_fam = (top // 10 + 1) * 10
        for i in src_rows:
            r = chars.add_row(copy_from=i)
            r.set("id", new_fam + chars.rows[i]["id"] - fam)
            new_rows.append(r)
        # class rank chain
        jrows = [i for i, r in enumerate(jr.rows) if fam <= r["id"] <= fam + 5]
        for i in jrows:
            r = jr.add_row(copy_from=i)
            off = jr.rows[i]["id"] - fam
            r.set("id", new_fam + off)
            if jr.rows[i]["next_id"]:
                r.set("next_id", new_fam + jr.rows[i]["next_id"] - fam)
        svc.mark_dirty("JobRank.dat")
        first = new_rows[0]
        _set_all_langs(first, "title", v["title"] or v["name"])
        for r in new_rows:
            _set_all_langs(r, "name", v["name"])
        unit_id = new_fam
        lines.append(f"Created class '{v['name']}' with {len(new_rows)} tiers (ids {new_fam}–{new_fam + len(new_rows) - 1}) "
                     f"and {len(jrows)} class-rank rows.")
    else:
        # The game treats every class id >= 1000 as a generic class (colour lists, tiers ...), so a unique
        # character needs an id below 1000.  All of those are taken: use the unused "DLC Dummy" rows (edited in
        # place, like outfit slots), then free ids inside their families.
        slot = free_unique_id(svc, page.ws.active_mod, page.ws.fs)
        if slot is None:
            raise RuntimeError("no free character id below 1000 left")
        unit_id, si = slot
        if si is None:
            r = chars.add_row(copy_from=t_index)
        else:
            r = chars.rows[si]
            for f in chars.fields:
                if f.name != "id":
                    r.set(f.name, tmpl[f.name])
        r.set("id", unit_id)
        _set_all_langs(r, "name", v["name"])
        _set_all_langs(r, "title", v["title"])
        new_rows.append(r)
        lines.append(f"Created character '{v['name']}' with id {unit_id}.")

    # description
    if any(v["desc"]):
        ch = svc.table("charhelp.dat")
        src = ch.index_of(tmpl["help_id"])
        hr = ch.add_row(copy_from=src if src >= 0 else None)
        # char.dat help_id is matched against the row's char_id (+4), not its id; use one fresh value for both
        # (ids >= 4000, so the game doesn't round it down to a multiple of 10)
        taken = {r["id"] for r in ch.rows} | {r["char_id"] for r in ch.rows if r is not hr}
        new_help = max(taken | {3999}) + 1
        hr.set("id", new_help)
        hr.set("char_id", new_help)
        for k in range(3):
            _set_all_langs(hr, f"line{k + 1}", v["desc"][k] if k < len(v["desc"]) else "")
        for fl in ("flag_off1", "flag_off2", "flag_off3"):
            if fl in hr:
                hr.set(fl, 0)
        for r in new_rows:
            r.set("help_id", new_help)
        svc.mark_dirty("charhelp.dat")
        lines.append(f"Added description #{new_help}.")

    # sprite
    if v["clone_sprite"]:
        n = free_sprite_number(page.ws.fs, page.ws.active_mod)
        done = clone_sprite_files(page, tmpl["sprite_id"], n)
        for r in new_rows:
            r.set("sprite_id", n)
        lines.append(f"Copied the sprite to anm{n:05d} (+ portrait anm{n + 10000:05d}); files: {len(done)}. "
                     "Open it on the Sprites & Colors page to repaint or recolor it.")

    # recruit quest
    if v["quest"]:
        q = svc.table("Quest.dat")
        src = q.index_of(1)  # 'Combat Lecture': simple, available from the start
        qr = q.add_row(copy_from=src if src >= 0 else 0)
        qid = max(r["id"] for r in q.rows if r["id"] < 2000) + 1
        if qid >= 2000:
            qid = max(r["id"] for r in q.rows) + 1
        qr.set("id", qid)
        _set_all_langs(qr, "name", v["quest_title"] or "A New Ally")
        _set_all_langs(qr, "client", v["quest_client"] or v["name"])
        for k, line in enumerate(dbpatch.quest_lines(v["quest_text"]), 1):      # wrapped like the game's own
            _set_all_langs(qr, f"desc{k}", line)
        # sort_order is the quest's progress slot in the save; the board only scans slots below the row count
        qr.set("sort_order", dbpatch.free_quest_slot(q, exclude=qr))
        qr.set("reward_type", 6 if v["generic"] else 5)
        qr.set("reward_value", unit_id)
        qr.set("reward_count", 1)
        qr.set("important", 1)
        svc.mark_dirty("Quest.dat")
        lines.append(f"Added quest #{qid} '{v['quest_title']}' that {'unlocks the class' if v['generic'] else 'recruits the character'}. "
                     "Its objective is copied from 'Combat Lecture'; change it in Database Editor → Quests.")

    svc.mark_dirty(CHAR)
    svc.commit(CHAR, page)
    for m in ("JobRank.dat", "charhelp.dat", "Quest.dat"):
        if svc.is_dirty(m):
            svc.commit(m, page)
    return "\n\n".join(lines) + "\n\nEverything is saved in your mod. Press Install to try it in game."
