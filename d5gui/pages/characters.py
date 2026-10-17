"""Characters & Classes: friendly editor for char.dat + wizard for brand-new recruitable units."""
import os
import struct

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
                             QTreeWidgetItemIterator, QPushButton, QLabel, QComboBox, QGroupBox, QGridLayout, QFormLayout, QSpinBox,
                             QLineEdit, QScrollArea, QMessageBox, QDialog, QDialogButtonBox, QRadioButton,
                             QCheckBox, QApplication, QTextEdit, QPlainTextEdit, QProgressDialog)

from d5lib import anm, charstudio, dbpatch, sprites
from ..common import PageHeader, SearchBox, ImageView, error_box, info_box, ResponsiveGrid
from ..dbservice import get_service, table_names
from .stages import SearchCombo, set_choice_tips

CHAR = "char.dat"
STATS = ["HP", "SP", "ATK", "DEF", "INT", "RES", "HIT", "SPD"]
# weapon mastery letters (0x14015b8b0: aptitude // 5 + 1, at most 6; 0 = can't use) and the value a letter sets
RANKS = [("S", 25), ("A", 20), ("B", 15), ("C", 10), ("D", 5), ("E", 1), ("—  (can't use)", 0)]


def rank_of(v):
    return 0 if v <= 0 else min(6, int(v) // 5 + 1)


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
    "mastery": "Weapon mastery rank: how fast this character's mastery of the weapon grows (S fastest .. E "
               "slowest, — can't use it). The game shows the letter on the Status screen; the number behind it "
               "(char.dat aptitude, 25+ = S, 20 = A, 15 = B, 10 = C, 5 = D, 1-4 = E) can be fine-tuned in the "
               "Database editor. Every unit starts at weapon level 0 and gains levels by fighting.",
    "wlevel": "Weapon level a new unit of this class starts with (0-100; the game's own units start at 0). It is "
              "given when the unit is made: recruited, joining in the story or created at the registrar; a unit that "
              "already has more keeps it. Saved in the mod you save edits to; Install to apply.",
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


ROLE = Qt.ItemDataRole.UserRole
DUMMY_NAMES = {"Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy"}   # the game's empty reserved rows
RESERVED_TEXTS = DUMMY_NAMES | {"Unique Dummy Character", "DLC Character", "Generic Human Dummy",
                                "Generic Monster Dummy"}
NEW = "New (made with mods)"
OUTFITS = "Outfit copies"
# list sections, top to bottom: (key, title, kind filter that shows it, open at first)
SECTIONS = [("new", "✨ New characters & classes", NEW, True),
            ("unique", "Unique characters", "Unique", True),
            ("human", "Generic classes", "Human class", True),
            ("monster", "Monster classes", "Monster class", True),
            ("other", "Other / NPC", "Other / NPC", False),
            ("outfit", "Outfit copies (made by the Outfits page)", OUTFITS, True)]


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
        self.kind.addItems(["All", NEW, "Unique", "Human class", "Monster class", "Other / NPC", OUTFITS])
        self.kind.setToolTip("Which characters to list. Outfits are edited on the Outfits page; their copies of the "
                             "character are listed here only under 'Outfit copies'.")
        self.kind.currentIndexChanged.connect(self._filter)
        row = QHBoxLayout()
        row.addWidget(self.kind, 1)
        b = QPushButton("⟳")
        b.setFixedWidth(34)
        b.setToolTip("Reload the list from the mods (it also reloads by itself when mods are switched on / off, "
                     "deleted or imported; unsaved edits are kept)")
        b.clicked.connect(self.refresh_list)
        row.addWidget(b)
        ll.addLayout(row)
        self.search = SearchBox("Search characters / classes…")
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.setUniformRowHeights(True)
        self.list.setIndentation(14)
        self.list.currentItemChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        b = QPushButton("✨ New character / class…")
        b.setObjectName("primary")
        b.clicked.connect(self.new_unit)
        ll.addWidget(b)
        split.addWidget(left)

        mid = QWidget()
        mlay = QVBoxLayout(mid)
        mlay.setContentsMargins(0, 0, 0, 0)
        mlay.setSpacing(6)
        self.nav = ResponsiveGrid(min_cell=92, max_cols=12, spacing=4)     # jump to a section (_build_nav)
        mlay.addWidget(self.nav)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.form = QWidget()
        self.scroll.setWidget(self.form)
        self.form_lay = QVBoxLayout(self.form)
        self.form_lay.setSpacing(10)
        mlay.addWidget(self.scroll, 1)
        split.addWidget(mid)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        rl.addWidget(self.title)
        self.saved_in = QLabel("")
        self.saved_in.setObjectName("muted")
        self.saved_in.setWordWrap(True)
        rl.addWidget(self.saved_in)
        self.preview = ImageView(smooth=True)
        self.preview.setBackgroundBrush(QColor(40, 90, 60))
        rl.addWidget(self.preview, 1)
        self.portrait = ImageView(smooth=True)
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
        b = QPushButton("🖼 Portrait…")
        b.setToolTip("New characters only: the big picture on the status screen and in the skill cut-in. A plain "
                     "white background is made transparent.")
        b.clicked.connect(self.set_portrait)
        rl.addWidget(b)
        b = QPushButton("🧽 Fix portrait background…")
        b.setToolTip("New characters: choose what of the portrait is see-through. Click a white area or paint with "
                     "the brush (left: transparent, right: keep); it is built again from the original picture.")
        b.clicked.connect(self.fix_portrait)
        rl.addWidget(b)
        b = QPushButton("📤 Share this character…")
        b.setToolTip("Export the mod that holds this character as a .zip anyone with the D5 Mod Kit can import "
                     "(Home › Import). A later version you share installs as an update.")
        b.clicked.connect(self.share_character)
        rl.addWidget(b)
        b = QPushButton("🗑 Delete this character…")
        b.setToolTip("A unique character your mod made: its row (a reserved row goes back to the game's), "
                     "description, recruit quest, sprite files and face picture. Makes room to create it again.")
        b.clicked.connect(self.delete_character)
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
        from ..common import Refresher
        self._relist = Refresher(self, lambda: self._loaded and self._populate())
        self.svc.table_changed.connect(lambda m: m == CHAR and self._relist())
        ws.file_changed.connect(lambda v: v.startswith("Anime/") and self.__dict__.pop("_pv_cache", None))
        ws.active_mod_changed.connect(self._relist)
        ws.mods_changed.connect(lambda: self.__dict__.pop("_pv_cache", None))   # sprite files may be gone

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

    def _outfit_rows(self):
        """char.dat ids of outfits (copies of a character the Outfits page made), in every mod"""
        from d5lib import outfits
        ids = set()
        for m in self.ws.mods.all_mods():
            try:
                pairs = outfits.load(m)
            except Exception:
                continue
            for _, slot in pairs:
                ids.update(range(int(slot), int(slot) + 10) if outfits.is_generic(slot) else {int(slot)})
        return ids

    def _leaves(self):
        it = QTreeWidgetItemIterator(self.list)
        while it.value():
            node = it.value()
            if node.childCount() == 0 and node.data(0, ROLE) is not None:
                yield node
            it += 1

    def _populate(self):
        """the list in sections: new characters & classes made with mods first, then the game's unique characters,
        generic and monster classes (one entry per class, its ranks inside), others.  Outfit copies (Outfits page)
        and the game's unused reserved rows are left out."""
        if getattr(self, "_relist", None) is not None:
            self._relist.done()                       # (a refresh still queued for the same change is not needed)
        cur = getattr(self, "_cur_key", None)        # (id, name) of the shown character: row numbers move
        opened = {n.data(0, ROLE + 1) for n in self._groups() if n.isExpanded()} if self.list.topLevelItemCount() \
            else None
        self.list.blockSignals(True)
        self.list.clear()
        t = self.table()
        van = self.svc.vanilla(CHAR).rows
        base = len(van)
        tips = self.svc.ref_tooltips(CHAR)
        outfit_ids = self._outfit_rows()
        bold = self.list.font()
        bold.setBold(True)
        sections, families = {}, {}
        seen_new = set()

        def section(key):
            if key not in sections:
                title = next(s[1] for s in SECTIONS if s[0] == key)
                sections[key] = n = QTreeWidgetItem([title])
                n.setData(0, ROLE + 1, key)
                n.setFont(0, bold)
                n.setFlags(Qt.ItemFlag.ItemIsEnabled)
            return sections[key]

        for i, r in enumerate(t.rows):
            name, title = r["name_EN"], r["title_EN"]
            if not name and not title:
                continue
            cid = r["id"]
            added = i >= base
            dummy = not added and van[i]["name_EN"] in DUMMY_NAMES
            if cid in outfit_ids:
                key = "outfit"
            elif added or (dummy and name not in DUMMY_NAMES):
                key = "new"
            elif dummy:
                continue                                     # a reserved row nobody uses yet
            else:
                key = {"Unique": "unique", "Human class": "human", "Monster class": "monster"}.get(kind_of(cid),
                                                                                                  "other")
            label = f"{name} — {title}" if title and title != name else name
            twin = key == "new" and (name, title) in seen_new          # e.g. Killixia's row kept for older saves
            seen_new.add((name, title)) if key == "new" else None
            it = QTreeWidgetItem([label + ("  (older saves)" if twin else "")])
            it.setData(0, ROLE, i)
            desc = tips.get(cid, "").replace("<qt>", "").replace("</qt>", "")
            it.setToolTip(0, f"<qt>{desc + '<br>' if desc else ''}"
                             + ("<i>A second row of this character, kept so saves made with an older version of its "
                                "mod still load. Edit the first one.</i><br>" if twin else "")
                             + f"<span style='color:#9aa4b8'>id {cid}  ·  row {i}"
                             f"  ·  sprite anm{r['sprite_id']:05d}</span></qt>")
            if added or (dummy and key == "new"):
                it.setForeground(0, QBrush(QColor("#5fe0a0")))
            elif bytes(r.raw) != bytes(van[i].raw):
                it.setForeground(0, QBrush(QColor("#ff4f8b")))
            if cid >= 1000 and key in ("human", "monster", "new", "outfit"):
                fk = (key, cid // 10)                        # a class: its six ranks under one entry
                fam = families.get(fk)
                if fam is None:
                    families[fk] = fam = QTreeWidgetItem([name or title])
                    fam.setData(0, ROLE, i)                  # (selecting the class shows its first rank)
                    fam.setData(0, ROLE + 1, f"{key}:{cid // 10}")
                    fam.setToolTip(0, it.toolTip(0))
                    fam.setForeground(0, it.foreground(0))
                    section(key).addChild(fam)
                fam.addChild(it)
            else:
                section(key).addChild(it)
        for key, *_ in SECTIONS:
            if key in sections:
                self.list.addTopLevelItem(sections[key])
        for (key, _), fam in families.items():
            n = fam.childCount()
            if n == 1:                                       # one row (a character kept for older saves): no fold
                sec, leaf = fam.parent(), fam.takeChild(0)
                sec.insertChild(sec.indexOfChild(fam), leaf)
                sec.removeChild(fam)
                continue
            fam.setText(0, f"{fam.text(0)}  ({n} ranks)")
        for key, s in sections.items():
            s.setText(0, f"{s.text(0)}  ({sum(1 for _ in self._leaves_of(s))})")
            s.setExpanded(opened is None and next(x[3] for x in SECTIONS if x[0] == key)
                          or (opened is not None and key in opened))
        if opened:
            for fam in families.values():
                fam.setExpanded(fam.data(0, ROLE + 1) in opened)
        self.list.blockSignals(False)
        self._filter()
        if cur is not None:
            rows = self.table().rows
            want = [i for i, r in enumerate(rows) if r["id"] == cur[0]]
            want.sort(key=lambda i: rows[i]["name_EN"] != cur[1])
            if any(self._select_row(i) for i in want[:1]):
                return
        for leaf in self._leaves():                   # never open on an empty editor
            if not leaf.isHidden() and not (leaf.parent() and leaf.parent().isHidden()):
                self.list.setCurrentItem(leaf)
                break

    def _groups(self):
        it = QTreeWidgetItemIterator(self.list)
        while it.value():
            if it.value().childCount():
                yield it.value()
            it += 1

    @staticmethod
    def _leaves_of(node):
        for k in range(node.childCount()):
            c = node.child(k)
            if c.childCount():
                yield from CharactersPage._leaves_of(c)
            else:
                yield c

    def _select_row(self, row):
        for leaf in self._leaves():
            if leaf.data(0, ROLE) == row and not leaf.isHidden():
                p = leaf.parent()
                while p is not None:
                    p.setExpanded(True)
                    p = p.parent()
                self.list.setCurrentItem(leaf)
                self.list.scrollToItem(leaf)
                return True
        return False

    def _filter(self, *a):
        t = self.search.text().lower().strip()
        kind = self.kind.currentText()
        rows = self.table().rows
        for k in range(self.list.topLevelItemCount()):
            sec = self.list.topLevelItem(k)
            key = sec.data(0, ROLE + 1)
            want = next(s[2] for s in SECTIONS if s[0] == key)
            shown = (kind == want) or (kind == "All" and key != "outfit")
            any_sec = False
            for c in range(sec.childCount()):
                node = sec.child(c)
                kids = [node.child(j) for j in range(node.childCount())] or [node]
                any_node = False
                for leaf in kids:
                    cid = rows[leaf.data(0, ROLE)]["id"]
                    ok = shown and (not t or t in leaf.text(0).lower() or t in node.text(0).lower()
                                    or t == str(cid))
                    if leaf is not node:
                        leaf.setHidden(not ok)
                    any_node |= ok
                node.setHidden(not any_node)
                if t and any_node and node.childCount():
                    node.setExpanded(True)
                any_sec |= any_node
            sec.setHidden(not any_sec)
            if t and any_sec:
                sec.setExpanded(True)

    def _pick(self, it, prev=None):
        if not it or it.data(0, ROLE) is None:
            return
        self.row_index = it.data(0, ROLE)
        r = self.table().rows[self.row_index]
        self._cur_key = (r["id"], r["name_EN"])
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

    def _weapon_levels(self, cid):
        """the starting weapon levels of a class as the install gives them (the mods' tables in load order)"""
        from d5lib import weaponlevels
        return list(weaponlevels.merged(self.ws.mods.enabled_mods()).get(cid, [0] * len(WEAPONS)))

    def _char_mod(self, ask=True):
        """the mod this character's changes are saved in: the mod that made it or (last) changes it
        (DBService.row_owner), else the active mod (asked for when there is none and `ask`)"""
        m = self.svc.row_owner(CHAR, self.row_index) if self.row_index is not None else None
        if m is not None:
            return m
        return self.ws.require_mod(self) if ask else self.ws.active_mod

    def _show_saved_in(self):
        if self.row_index is None:
            self.saved_in.setText("")
            return
        o = self.svc.owner_map(CHAR).get(self.row_index)
        m = self.ws.mods.get(o[0]) if o else None
        if m is not None:
            why = "it adds this character" if o[1] == "added" else "it changes this character"
            self.saved_in.setText(f"💾 Saved in the mod “{m.name}” ({why})")
            self.saved_in.setToolTip("Changes to a character a mod makes or changes are saved in that mod "
                                     "automatically, whichever mod is chosen bottom left.")
        else:
            act = self.ws.active_mod
            self.saved_in.setText(f"💾 Saved in “{act.name}” (bottom left): no mod changes this character yet"
                                  if act else "💾 A game character no mod changes: saved in the mod chosen bottom "
                                              "left (asked for on the first save)")
            self.saved_in.setToolTip("The game's own characters no mod changes go into the mod chosen bottom left "
                                     "(“New edits go to”). Once a mod changes a character, its changes go there.")

    def _set_weapon_level(self, k, v):
        from d5lib import weaponlevels
        cid = self._row()["id"]
        # the mod whose level the game gets (the last listing this class), else the character's own mod
        mod = next((m for m in reversed(self.ws.mods.enabled_mods()) if cid in weaponlevels.load(m)), None) \
            or self._char_mod()
        if not mod:
            return
        table = weaponlevels.load(mod)
        lv = table.get(cid) or self._weapon_levels(cid)
        lv[k] = int(v)
        table[cid] = lv
        weaponlevels.save(mod, table)
        self.status.setText(f"Weapon level saved in '{mod.name}': Install to give it to new units (units in your "
                            "saves made earlier are offered the update after the install)")

    def _rank(self, name):
        """weapon mastery as the game shows it: a letter (the aptitude value // 5 + 1, S at 25+); choosing a letter
        keeps a value already in its band, else sets the band's base value"""
        c = QComboBox()
        for lab, v in RANKS:
            c.addItem(lab, v)
        c.setMaximumWidth(130)
        c.setToolTip(HELP["mastery"])
        c.activated.connect(lambda _, n=name, c=c: self._loading or self._set_rank(n, c.currentData()))
        self.widgets[name] = ("rank", c)
        return c

    def _set_rank(self, name, base):
        cur = int(self._row()[name])
        if rank_of(cur) != rank_of(base):
            self._set(name, base)
        self._show_rank(name)

    def _show_rank(self, name):
        kind, c = self.widgets[name]
        v = int(self._row()[name])
        i = c.findData(next(b for lab, b in RANKS if rank_of(b) == rank_of(v)))
        c.setCurrentIndex(i if i >= 0 else 0)
        c.setToolTip(HELP["mastery"] + f"\n\nNow: {c.currentText()} (aptitude {v})")

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
                elif kind == "rank":
                    self._show_rank(name)
                else:
                    w.set_value(v)
            for w, v in zip(getattr(self, "wlevels", []), self._weapon_levels(r["id"])):
                w.setValue(int(v))
        finally:
            self._loading = False
        if getattr(self, "voice_box", None) is not None:
            self.voice_box.load(r)
        self._loading = True
        try:
            if "kind_gender" in r:
                k = self.gender.findData(int(r["kind_gender"]) % 10)
                self.gender.setCurrentIndex(k if k >= 0 else 0)
            self.desc_edit.setPlainText("\n".join(x for x in self._desc_lines(r) if x))
        finally:
            self._loading = False
        cid = r["id"]
        self.title.setText(f"{r['name_EN']} — {r['title_EN']}\nid {cid} · {kind_of(cid)}")
        self._show_saved_in()
        self.id_label.setText(f"{cid}   (maps and quests refer to this id)")
        self._show_recruit(r)

    def _show_recruit(self, r):
        """the quest that recruits this character (or unlocks this class), in words"""
        from .. import questinfo
        box = getattr(self, "recruit_box", None)
        if box is None:
            return
        qs = questinfo.recruit_quests(self.svc, r["id"])
        box.setVisible(bool(qs))
        self._recruit_quests = qs
        if qs:
            box.setTitle("How to get this character" if qs[0]["reward_type"] == 5 else "How to unlock this class")
            self.recruit_label.setText("<br><br>".join(questinfo.describe(self.svc, q) for q in qs))

    def _edit_recruit(self):
        """the objective of the recruit quest: a stage to clear (yours too) or enemies to defeat"""
        from ..questgoal import ObjectiveDialog
        from d5lib import questcheck
        qs = getattr(self, "_recruit_quests", None) or []
        if not qs:
            return
        row = qs[0]
        dlg = ObjectiveDialog(self, self.svc, row)
        if not dlg.exec():
            return
        cond = dlg.cond()
        if cond is None:
            return
        questcheck.set_objective(row, cond)
        self.svc.mark_dirty("Quest.dat")
        if self.svc.commit("Quest.dat", self) is False:
            return
        from .. import questinfo
        self.ws.log(f"Quest '{row['name_EN']}' now asks: {questinfo.objective(self.svc, row)} "
                    f"({self.svc.saved_text()})")
        self._show_recruit(self._row())

    def _set(self, name, v):
        r = self._row()
        try:
            if r[name] == v:
                return
            old = r[name]
            r.set(name, v, truncate=True) if r.field(name).type == "str" else r.set(name, v)
        except Exception as e:
            QMessageBox.warning(self, "Invalid value", str(e))
            return
        if name in ("name_EN", "title_EN"):
            # every language that still shows the old text (or a reserved row's) follows: a game in French shows
            # name_FR, and a new character made in English must not stay 'DLC Dummy' there
            pre = name[:-3]
            for L in LANGS:
                f = f"{pre}_{L}"
                if L != "EN" and f in r and (r[f] in (old, "") or r[f] in RESERVED_TEXTS):
                    r.set(f, v, truncate=True)
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
        f.addRow("Name", self._text("name_EN"))
        f.addRow("Title / class", self._text("title_EN"))
        other = QPushButton("Other languages…")
        other.setToolTip("Name and title per game language. Editing them above also changes every language that "
                         "still had the old text (a game set to French shows the French name).")
        other.clicked.connect(self._langs_dialog)
        f.addRow("", other)
        self.gender = QComboBox()
        for lab, v in (("Male", 1), ("Female", 2), ("None", 3)):
            self.gender.addItem(lab, v)
        self.gender.setToolTip("Some evilities and skills check it (char.dat kind_gender: the ones digit; the tens "
                               "digit, the kind of unit, stays)")
        self.gender.currentIndexChanged.connect(self._set_gender)
        f.addRow("Gender", self.gender)
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlaceholderText("What the status screen says about this character: up to 3 lines of about "
                                          "42 characters (longer text is wrapped)")
        self.desc_edit.setFixedHeight(66)
        self.desc_edit.setToolTip("Saved in every game language that still had the old text. A character that "
                                  "shares its description with another gets one of its own.")
        from PyQt6.QtCore import QTimer
        self._desc_timer = QTimer(self)
        self._desc_timer.setSingleShot(True)
        self._desc_timer.setInterval(700)
        self._desc_timer.timeout.connect(self._save_desc)
        self.desc_edit.textChanged.connect(lambda: self._loading or self._desc_timer.start())
        f.addRow("Description", self.desc_edit)
        self.id_label = QLabel()
        f.addRow("Id", self.id_label)
        f.addRow("Description id", self._spin("help_id", tip="charhelp.dat entry the description above is kept in"))
        self.form_lay.addWidget(g)

        self.recruit_box = QGroupBox("How to get this character")
        rl = QVBoxLayout(self.recruit_box)
        self.recruit_label = QLabel()
        self.recruit_label.setWordWrap(True)
        self.recruit_label.setTextFormat(Qt.TextFormat.RichText)
        self.recruit_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rl.addWidget(self.recruit_label)
        self.recruit_btn = QPushButton("Change what the quest asks for…")
        self.recruit_btn.setToolTip("The quest's objective: clear a stage (one of the game's or one of yours) or "
                                    "defeat enemies of a class")
        self.recruit_btn.clicked.connect(self._edit_recruit)
        rl.addWidget(self.recruit_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.form_lay.addWidget(self.recruit_box)

        g = QGroupBox("Sprite")
        f = QFormLayout(g)
        f.addRow("Sprite file (anm number)", self._spin("sprite_id", 0, 32767,
                                                        "Which of the game's sprites this unit uses: anmNNNNN (battle "
                                                        "sprite); its portrait is NNNNN + 10000. To give a unit a new "
                                                        "look, see below."))
        f.addRow("Color variant / tier", self._spin("tier", 0, 255, "Palette used from the sprite (generic class tiers)"))
        new_look = QLabel("This number picks one of the sprites the game (or a mod) already has. A new character or "
                          "class with Disgaea RPG sprites: <b>✨ New character / class…</b> › Look: <i>Disgaea RPG "
                          "sprites</i>. A new look for an existing character (Disgaea RPG sprites or a sprite sheet): "
                          "<b>Outfits › New outfit</b>.")
        new_look.setWordWrap(True)
        new_look.setObjectName("muted")
        f.addRow(new_look)
        self.form_lay.addWidget(g)

        from ..voiceui import VoiceBox
        self.voice_box = VoiceBox(self)
        self.form_lay.addWidget(self.voice_box)

        g = QGroupBox("Quick setup")
        ql = QVBoxLayout(g)
        rg = ResponsiveGrid(min_cell=170, max_cols=3)
        self.preset = QComboBox()
        for key, label, desc, cid in charstudio.PRESETS:
            self.preset.addItem(label, key)
            self.preset.setItemData(self.preset.count() - 1, desc, Qt.ItemDataRole.ToolTipRole)
        b = QPushButton("Apply preset")
        b.setToolTip("Base stats, aptitudes and movement from the preset (this character's other settings stay)")
        b.clicked.connect(self.apply_preset)
        rg.add_cell("Start from", self.preset, b, tip="Take the numbers of one of the game's playable characters: "
                    "base stats, aptitudes, movement. Fine-tune them below afterwards.")
        b = QPushButton("📋 Copy from another…")
        b.setToolTip("Copy chosen parts (stats, aptitudes, movement, mastery, resistances, evilities, Overload, "
                     "skills) of any character or class, with a power %")
        b.clicked.connect(self.copy_from)
        rg.add_cell("Or take parts of another", b)
        ql.addWidget(rg)
        self.form_lay.addWidget(g)

        g = QGroupBox("Base stats  ·  aptitudes")
        gl = QVBoxLayout(g)
        rg = ResponsiveGrid(min_cell=96, max_cols=8)
        for s in STATS:
            base = self._spin(f"base_{s}", tip=f"{HELP[s]}\n\n{HELP['base']}")
            apt = self._spin(f"apt_{s}", tip=f"{HELP[s]}\n\n{HELP['apt']}")
            apt.setSuffix(" %")
            cell = rg.add_cell(s, base, apt, tip=HELP[s])
            cell.findChild(QLabel).setObjectName("statLabel")
        gl.addWidget(rg)
        note = QLabel("Upper box: the base value · lower box: the aptitude (how much of it the unit gets, %)")
        note.setObjectName("muted")
        note.setWordWrap(True)
        gl.addWidget(note)
        self.form_lay.addWidget(g)

        g = QGroupBox("Movement && combat")
        gl = QVBoxLayout(g)
        rg = ResponsiveGrid(min_cell=96, max_cols=6)
        for n, lab in [("MOV", "Move"), ("JMP", "Jump"), ("throw", "Throw"), ("counter", "Counter"),
                       ("crit", "Critical %"), ("attack_range", "Attack range")]:
            rg.add_cell(lab, self._spin(n, tip=HELP[n]), tip=HELP[n])
        gl.addWidget(rg)
        self.form_lay.addWidget(g)

        g = QGroupBox("Weapon mastery  ·  rank and starting level")
        gl = QVBoxLayout(g)
        rg = ResponsiveGrid(min_cell=168, max_cols=5)
        self.wlevels = []
        for k, (n, lab) in enumerate(WEAPONS):
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(self._rank(f"mastery_{n}"), 1)
            lv = QSpinBox()
            lv.setRange(0, 100)
            lv.setPrefix("Lv ")
            lv.setMinimumWidth(78)
            lv.setToolTip(HELP["wlevel"])
            lv.valueChanged.connect(lambda v, k=k: self._loading or self._set_weapon_level(k, v))
            self.wlevels.append(lv)
            cell.addWidget(lv)
            rg.add_cell(lab, cell, tip=HELP["mastery"])
        gl.addWidget(rg)
        self.form_lay.addWidget(g)

        g = QGroupBox("Resistances (%)")
        gl = QVBoxLayout(g)
        rg = ResponsiveGrid(min_cell=96, max_cols=6)
        res = [("res_fire", "Fire"), ("res_wind", "Wind"), ("res_ice", "Ice"), ("res_star", "Star")] + \
              [(f"wres_{n}", lab) for n, lab in WEAPONS[:7]] + [("wres_monster", "Monster")]
        for n, lab in res:
            tip = HELP["res"] if n.startswith("res_") else HELP["wres"]
            rg.add_cell(lab, self._spin(n, -100, 100, tip), tip=tip)
        gl.addWidget(rg)
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

        g = QGroupBox("Learned skills  ·  skill and level learned")
        gl = QVBoxLayout(g)
        rg = ResponsiveGrid(min_cell=330, max_cols=2)
        for k in range(1, 17):
            c = self._combo(f"learn{k}_skill", lk["magic"], self._set_skill)
            c.setMinimumWidth(150)
            lv = self._spin(f"learn{k}_level", 0, 9999, "Level at which the skill is learned")
            lv.setPrefix("Lv ")
            lv.setMinimumWidth(78)
            lv.setMaximumWidth(96)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            num = QLabel(f"{k}")
            num.setObjectName("slotNumber")
            num.setFixedWidth(18)
            cell.addWidget(num)
            cell.addWidget(c, 1)
            pick = QPushButton("📂")
            pick.setFixedWidth(34)
            pick.setToolTip("Choose from the skills in groups: weapon skills by weapon, spells by element, each "
                            "character's and class's own skills, the skills your mods add")
            pick.clicked.connect(lambda _, n=f"learn{k}_skill", c=c: self._browse_skill(n, c))
            cell.addWidget(pick)
            cell.addWidget(lv)
            rg.add_cell(cell)
        gl.addWidget(rg)
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
        gl.addLayout(row)
        self.form_lay.addWidget(g)

        g = QGroupBox("Rewards when defeated")
        gl = QVBoxLayout(g)
        rg = ResponsiveGrid(min_cell=110, max_cols=3)
        for n, lab in [("exp_value", "EXP"), ("hl_value", "HL"), ("mana_value", "Mana")]:
            rg.add_cell(lab, self._spin(n, tip=HELP[n]), tip=HELP[n])
        gl.addWidget(rg)
        self.form_lay.addWidget(g)
        more = QLabel("Every other field of this character is available in Database Editor → Characters & Classes.")
        more.setObjectName("muted")
        more.setWordWrap(True)
        self.form_lay.addWidget(more)
        self.form_lay.addStretch(1)
        self._build_nav()
        self._loading = False
        self._load_values()

    NAV = [("Identity", "Identity"), ("How to get", "Recruit"), ("Sprite", "Sprite"), ("Voice", "Voice"),
           ("Quick setup", "Setup"), ("Base stats", "Stats"), ("Movement", "Movement"), ("Weapon mastery", "Mastery"),
           ("Resistances", "Resists"), ("Evilities", "Evilities"), ("Learned skills", "Skills"), ("Rewards", "Rewards")]

    def _build_nav(self):
        """the row of chips above the form: each jumps to its section"""
        boxes = [self.form_lay.itemAt(i).widget() for i in range(self.form_lay.count())]
        for start, label in self.NAV:
            box = next((b for b in boxes if isinstance(b, QGroupBox) and b.title().replace("&&", "&").startswith(start)),
                       None)
            if box is None:
                continue
            b = QPushButton(label)
            b.setObjectName("chip")
            b.setToolTip(box.title().replace("&&", "&"))
            b.clicked.connect(lambda _, box=box: self.scroll.verticalScrollBar().setValue(max(0, box.y() - 8)))
            self.nav.add(b)

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

    def _browse_skill(self, name, combo):
        from ..skillbrowser import SkillBrowser
        r = self._row()
        dlg = SkillBrowser(self, self.svc, current=combo.value(), me=(r["id"], r["name_EN"]))
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.value() is not None:
            combo.set_value(dlg.value())
            self._set_skill(name, dlg.value())

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
        mod = self._char_mod()                       # (a mod's character: its own mod)
        if not mod:
            return
        try:
            sid = charstudio.new_skill(self.svc, self.ws.fs, mod, r, int(v["copy_of"]), v["name"], v["desc"],
                                       v["level"], v["sp"], mods=self.ws.mods.all_mods())
        except Exception as e:
            return error_box(self, "Could not make the skill", e)
        self.svc.commit("magic.dat", self, into=mod)
        self.svc.commit(CHAR, self, into=mod)
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
        mod = self._char_mod()
        if not mod:
            return
        try:
            eid = charstudio.new_evility(self.svc, mod, r, int(v["like"]), v["name"], v["desc"], v["slot"],
                                         mods=self.ws.mods.all_mods())
        except Exception as e:
            return error_box(self, "Could not make the evility", e)
        self.svc.commit("Skill.dat", self, into=mod)
        self.svc.commit(CHAR, self, into=mod)
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
        rows = self.table().rows
        row = next((i for i, r in enumerate(rows) if r["id"] == int(cid)), None)
        if row is None:
            return False
        for kind in ("All", OUTFITS):                # an outfit's copy is listed only under 'Outfit copies'
            self.kind.setCurrentText(kind)
            if self._select_row(row):
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

    # ================================================================== gender, description, delete
    def _set_gender(self, *_):
        if self._loading or self.row_index is None:
            return
        r = self._row()
        if "kind_gender" not in r:
            return
        self._set("kind_gender", int(r["kind_gender"]) // 10 * 10 + int(self.gender.currentData()))

    def _help_row(self, r):
        """(charhelp index, row) of character r's description: the row whose char_id is r's help_id"""
        ch = self.svc.table("charhelp.dat")
        for i, h in enumerate(ch.rows):
            if h["char_id"] == r["help_id"]:
                return i, h
        return None, None

    def _desc_lines(self, r):
        _, h = self._help_row(r)
        if h is None:
            return ["", "", ""]
        return [h.get(f"line{k}_EN") or "" for k in (1, 2, 3)]

    def _save_desc(self):
        """the description box -> the character's own help row (made when it shares one, or has none)"""
        if self.row_index is None:
            return
        r = self._row()
        lines = dbpatch.help_lines(self.desc_edit.toPlainText())
        old = self._desc_lines(r)
        if lines == old:
            return
        ch = self.svc.table("charhelp.dat")
        i, h = self._help_row(r)
        shared = h is None or any(x is not r and x["help_id"] == r["help_id"] for x in self.table().rows)
        if shared:
            # one of its own: a fresh id (>= 4000: the game doesn't round it), the same value as id and char_id
            hid = max({x["id"] for x in ch.rows} | {x["char_id"] for x in ch.rows} | {3999}) + 1
            h = ch.add_row(copy_from=i)
            h.set("id", hid)
            h.set("char_id", hid)
            for fl in ("flag_off1", "flag_off2", "flag_off3"):
                if fl in h:
                    h.set(fl, 0)
            self._set("help_id", hid)
            kind, w = self.widgets.get("help_id", (None, None))
            if w is not None:
                self._loading = True
                w.setValue(hid)
                self._loading = False
        for k in range(3):
            for L in LANGS:
                f = f"line{k + 1}_{L}"
                if f in h and (L == "EN" or shared or h[f] in (old[k], "") or h[f].startswith("DLC Dummy")):
                    h.set(f, lines[k], truncate=True)
        self.svc.mark_dirty("charhelp.dat")
        self.status.setText("● unsaved changes")

    def _is_new(self, i, r):
        """a character or class a mod added (an added row, or a reserved dummy row filled in)"""
        van = self.svc.vanilla(CHAR).rows
        return i >= len(van) or (van[i]["name_EN"] in DUMMY_NAMES and r["name_EN"] not in DUMMY_NAMES)

    def refresh_list(self):
        self.__dict__.pop("_pv_cache", None)
        self.svc.reload(keep_unsaved=True)              # (the page repopulates on the service's signal)
        if self._loaded:
            self._populate()
        self._preview()

    def delete_character(self):
        """remove a new character a mod made -- in the mod that made it (picked for the deletion, then the mod
        that was chosen in 'Saving edits to' again): its row (a reserved row goes back to the game's), its own
        description, its recruit quest, its sprite files and face picture"""
        if self.row_index is None:
            return
        r = self._row()
        cid, name = r["id"], r["name_EN"]
        if 1000 <= cid < 3000 or not self._is_new(self.row_index, r):
            QMessageBox.information(self, "Delete character",
                                    "Only characters your mods made can be deleted here. A game character goes back "
                                    "to how the game has it with ↺ Revert; a new class is its own mod (Home: switch "
                                    "it off or delete the mod).")
            return
        owners = self._owner_mods(cid)
        if not owners:
            QMessageBox.information(self, "Delete character", f"No enabled mod makes '{name}' (id {cid}).")
            return
        act = self.ws.active_mod
        adders = [m for m in owners if any(isinstance(x, dict) and int(x.get("id", -1)) == cid
                                           for x in (m.load_patch("db", "char.dat.json") or {}).get("added") or [])]
        owner = (adders or [m for m in owners if act and m.id == act.id] or owners)[-1]   # the mod that made it
        if QMessageBox.question(self, "Delete character",
                                f"Delete '{name}' (id {cid}) from the mod '{owner.name}'?\n\nIts description, recruit "
                                "quest, sprite files and face picture go too. Saves that have this character can "
                                "be cleaned next (you choose which).") != QMessageBox.StandardButton.Yes:
            return
        from .. import savecleanup
        try:                                             # what saves hold of it, read before its rows go
            info = savecleanup.mod_info(self.ws, owner)
            mine = {int(x["sort_order"]) for x in (owner.load_patch("db", "Quest.dat.json") or {}).get("added") or []
                    if int(x.get("reward_value", -1)) == cid and "sort_order" in x}
            held = ({cid: name}, {o: b for o, b in info["outfits"].items() if b == cid},
                    {s: t for s, t in info["quests"].items() if s in mine}, info.get("guard"))
        except Exception as e:
            held = ({cid: name}, {}, {}, None)
            self.ws.log(f"(recruit quest of '{name}' not looked up: {e})")
        if self.svc.dirty_members():
            self.save()                                  # (edits of the mod chosen now are kept, not lost)
        back = act if (act is None or act.id != owner.id) else None
        if back is not None or act is None:
            self.ws.set_active_mod(owner)                # the page reloads: find the character again
            rows = self.table().rows
            i = next((k for k, x in enumerate(rows) if x["id"] == cid and x["name_EN"] == name), None)
            if i is None:
                self.ws.set_active_mod(back)
                return
            self.row_index = i
            r = rows[i]
        try:
            self._delete_row(r, cid, name, owner)
        finally:
            if act is not None and act.id != owner.id:
                self.ws.set_active_mod(act)
        savecleanup.offer(self, self.ws, f"'{name}'", *held)

    def _delete_row(self, r, cid, name, act):
        from d5lib import newchars
        chars = self.table()
        van = self.svc.vanilla(CHAR).rows
        i = self.row_index
        sprite, hid = r["sprite_id"], r["help_id"]
        if i < len(van):
            chars.rows[i] = van[i].copy()                 # the reserved row as the game has it
        else:
            chars.delete_row(i)
        self.svc.mark_dirty(CHAR)
        ch = self.svc.table("charhelp.dat")
        if hid >= 4000 and not any(x["help_id"] == hid for x in chars.rows):
            for k in range(len(ch.rows) - 1, len(self.svc.vanilla("charhelp.dat").rows) - 1, -1):
                if ch.rows[k]["char_id"] == hid:
                    ch.delete_row(k)
            self.svc.mark_dirty("charhelp.dat")
        q = self.svc.table("Quest.dat")
        qv = len(self.svc.vanilla("Quest.dat").rows)
        for k in range(len(q.rows) - 1, qv - 1, -1):
            if q.rows[k]["reward_type"] == 5 and q.rows[k]["reward_value"] == cid:
                q.delete_row(k)
                self.svc.mark_dirty("Quest.dat")
        # its own sprite files (the game's own numbers stay)
        game = set(sprites.used_sprite_numbers(self.ws.fs))
        for n in (sprite, sprite + 1, sprite + 2, sprite + 10000, sprite + 10001, cid + 2, cid + 10000):
            vp = f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs"
            if n not in game and act.has_file(vp):
                act.remove_file(vp)
        newchars.remove_face(act, cid)
        self.row_index = None
        self.save()
        self._populate()
        self.ws.log(f"Deleted character '{name}' (id {cid}) from '{act.name}'. Install to update the game.")

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
        if self.row_index is None:
            return
        mod = self._char_mod()
        if not mod:
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

    def set_portrait(self):
        """The big picture of a new unique character: the status screen and the skill cut-in (anm 10000 + its id,
        made from its template's portrait; a plain white background is made transparent)."""
        from PyQt6.QtWidgets import QFileDialog
        from d5lib import newchars, outfits
        if self.row_index is None:
            return
        mod = self._char_mod()
        if not mod:
            return
        r = self._row()
        van = {v["id"]: v for v in self.svc.vanilla(CHAR).rows}
        if not newchars.is_new_character(r, van, outfits.used_slots(mod)):
            info_box(self, "Portrait", "Portraits here are for new unique characters (made with “New character”). "
                     "Outfits get theirs on the Outfits page (Edit › Set cut-in portrait).")
            return
        p, _ = QFileDialog.getOpenFileName(self, "Portrait (tall picture: head at the top)", "",
                                           "Images (*.png *.jpg *.webp)")
        if not p:
            return
        cid = r["id"]
        dst = 10000 + cid
        vp = f"Anime/ANM_HI_JP.dat/anm{dst:05d}.lzs"
        try:
            if not mod.has_file(vp):
                tmpl = r["color_id"] if r["color_id"] != cid else r["sprite_id"]
                if not any(outfits._clone(self.ws.fs, mod, src, dst)
                           for src in (r["sprite_id"] + 10000, tmpl + 10000, 10010)):
                    raise RuntimeError("no portrait file to start from")
            outfits._set_portrait(mod, dst, p)
        except Exception as e:
            error_box(self, "Portrait", e)
            return
        self.ws.log(f"portrait of {r['name_EN']} ({cid}) set: anm{dst:05d}")
        info_box(self, "Portrait", "Portrait set (status screen and skill cut-in). A plain white background is made "
                 "transparent. Press Install to see it in game.")

    def fix_portrait(self):
        """the portrait of a new character (anm 10000 + id, else its sprite's anm sprite + 10000) in the portrait
        fixer (d5gui/portraitfix.py), in the mod that has the file"""
        if self.row_index is None:
            return
        r = self._row()
        cid = r["id"]
        mods = self._owner_mods(cid) + [m for m in self.ws.mods.enabled_mods() if m not in self._owner_mods(cid)]
        for n in (10000 + cid, r["sprite_id"] + 10000):
            vp = f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs"
            mod = next((m for m in mods if m.has_file(vp)), None)
            if mod is not None:
                from ..portraitfix import fix_portrait
                fix_portrait(self, self.ws, mod, n, r["name_EN"])
                return
        info_box(self, "Fix portrait background", "This character has no portrait of its own in a mod: the game's "
                 "own portraits have no background to fix. (Outfits: Outfits page › Edit.)")

    # ================================================================== save
    def save(self):
        members = [m for m in (CHAR, "charhelp.dat", "Quest.dat", "JobRank.dat") if self.svc.is_dirty(m)] or [CHAR]
        self.svc.saved_into = []
        if all(self.svc.commit(m, self) for m in members):      # (a description alone is saved too)
            where = self.svc.saved_into
            self.status.setText(("Saved in " + ", ".join(f"'{n}'" for n in where) + ".") if where else "")
            self.ws.log((f"Saved characters into {', '.join(repr(n) for n in where)}. " if where else
                         "Nothing to save. ") + "Install (bottom left) to see them in game.")
            self._show_saved_in()

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
        if v.get("drpg") is not None:
            return self._unit_from_drpg(v)
        if v.get("sheet"):
            v["clone_sprite"] = True             # the sheet is drawn onto the character's own copy of the sprite
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
        self.kind.setCurrentText(NEW)
        if v.get("sheet") and getattr(self, "_last_clone", None):
            return self._sheet_onto_clone(mod, v, msg)
        info_box(self, "Unit created", msg)

    def _sheet_onto_clone(self, mod, v, msg):
        """the new character's own sprite copy redrawn from the sprite sheet (outfits.write_sheet_sprite), in the
        background"""
        from d5lib import outfits
        from ..common import Worker
        base_sprite, n = self._last_clone
        self._last_clone = None
        prog = QProgressDialog(f"Drawing '{v['name']}' from the sprite sheet…\n(a minute at most; the log at the "
                               "bottom shows the steps)", None, 0, 0, self)
        prog.setWindowTitle("New character")
        prog.setMinimumDuration(0)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.show()
        self._sheet_worker = w = Worker(lambda: outfits.write_sheet_sprite(self.ws.fs, mod, base_sprite, n,
                                                                           v["sheet"], self.ws.log))

        def done(rep):
            prog.close()
            self.ws.file_changed.emit("Anime/")
            info_box(self, "Character created",
                     msg + f"\n\nIts sprite anm{n:05d} is drawn from your sprite sheet: {rep.get('matched')} of "
                           f"{rep.get('cells')} of the game's poses matched to {rep.get('frames')} sheet frames.\n\n"
                           "If something looks off, adjust it by hand: the weapon on the Weapon Grips page, colours "
                           "in Sprites & Colors; or make it again with a sheet that has more rows.")

        def failed(err):
            prog.close()
            QMessageBox.critical(self, "Sprite sheet", "The character was created with a copy of the template's "
                                 "sprite, but the sheet could not be drawn onto it:\n\n" + err[:2500])

        w.done.connect(done)
        w.failed.connect(failed)
        w.start()

    def _unit_from_outfit(self, mod, v):
        """a new character with an outfit's look (charstudio.outfit_to_character; a Disgaea RPG outfit is drawn
        again from its unit, which takes a little while)"""
        src = v["outfit"]
        if self.svc.dirty_members():
            self.svc.commit_all(self)
        quest = dict(title=v["quest_title"], client=v["quest_client"], text=v["quest_text"],
                     cond=v.get("quest_cond")) if v["quest"] else None
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
        if v.get("preset") or v.get("fresh"):
            self._after_create(res["id"], v)
        self.select_character(res["id"])
        msg = (f"'{v['name']}' (id {res['id']}) has the look of {src['who']}'s outfit '{src['name']}' "
               f"(sprite anm{res['sprite']:05d})" + (f" and the recruit quest #{res['quest']}" if res.get("quest") else "")
               + ".\n\n" + ("The outfit is hidden from the Outfit menu by this mod; switch the mod off to bring it "
                              "back. " if v["hide_outfit"] else "")
               + ("It starts with no learned skills, evilities or Overload: give it its own on this page.\n\n"
                  if v.get("fresh") else
                  "Stats, skills and evilities come from the outfit's character: change them on this page.\n\n")
               + "Everything is saved in your mod. Press Install to try it in game.")
        info_box(self, "Character created", msg)

    def _unit_from_drpg(self, v):
        """a new character or class drawn from a Disgaea RPG unit (outfits.create_drpg_character /
        newclasses.create_class), built in the background"""
        from d5lib import drpgsource, newclasses, outfits
        from ..common import Worker
        unit, anim = v["drpg"], v["anim"]
        if self.svc.dirty_members() and not self.svc.commit_all(self):
            return
        chosen = self.ws.settings.get(drpgsource.SETTING)
        source_id = self._row()["id"]
        made_mod = None                                  # a mod made for it: gone again when the build fails
        prev_active = self.ws.active_mod
        if v["generic"]:
            mm = self.ws.mods

            def work():
                with drpgsource.using(chosen):
                    mod = newclasses.create_class(self.ws.fs, mm, unit.uid, anim, v["name"],
                                                  titles=[v["title"]] * 6 if v["title"] else None,
                                                  hire_desc=(v["desc"] or [""])[0], log=self.ws.log)
                fam = max(s["family"] for s in newclasses.load_specs(mod))
                return mod, fam
        else:
            if v.get("own_mod"):
                mod = self.ws.mods.create(v["name"], self.ws.settings.get("author", ""),
                                          f"New character {v['name']} (Disgaea RPG unit {unit.uid})")
                mod.meta["category"] = "characters"
                mod.save_meta()
                made_mod = mod
                self.ws.set_active_mod(mod)
                self.ws.mods_changed.emit()
            else:
                mod = self.ws.require_mod(self)
                if not mod:
                    return
            quest = dict(title=v["quest_title"], client=v["quest_client"], text=v["quest_text"],
                     cond=v.get("quest_cond")) if v["quest"] else None

            def work():
                with drpgsource.using(chosen):
                    res = outfits.create_drpg_character(self.ws.fs, mod, source_id, anim, unit.uid, v["name"],
                                                        title=v["title"] or None, desc=[d for d in v["desc"] if d],
                                                        quest=quest, log=self.ws.log)
                return mod, res
        what = "class" if v["generic"] else "character"
        prog = QProgressDialog(f"Drawing the new {what} '{v['name']}' from Disgaea RPG unit {unit.uid}…\n"
                               "(about a minute; the log at the bottom shows the steps)", None, 0, 0, self)
        prog.setWindowTitle(f"New {what}")
        prog.setMinimumDuration(0)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.show()
        self._drpg_worker = w = Worker(work)

        def done(r):
            prog.close()
            mod, res = r
            self.svc.reload()
            self.ws.file_changed.emit("Anime/")
            self.ws.mods_changed.emit()
            self._names = None
            self._populate()
            if v["generic"]:
                self.ws.set_active_mod(mod)
                self.select_character(res)
                msg = (f"The class '{v['name']}' (class ids {res}-{res + 5}) is drawn from Disgaea RPG unit {unit.uid} "
                       f"and moves like {self._label_of(anim)}. It has its own mod, '{mod.name}', switched on.\n\n"
                       "Next: give it its stats, skills and evilities on this page, then press Install & Play. In "
                       "game it is hired at the Netherworld registrar.")
            else:
                if v.get("preset") or v.get("fresh"):
                    self._after_create(res["id"], v)
                self.select_character(res["id"])
                msg = (f"'{v['name']}' (id {res['id']}, sprite anm{res['sprite']:05d}) is drawn from Disgaea RPG unit "
                       f"{unit.uid} and moves like {self._label_of(anim)}"
                       + (f"; recruit quest #{res['quest']} is at the Quest shop" if res.get("quest") else "")
                       + ".\n\nNext: check the stats, skills and evilities on this page, then press Install & Play.")
            msg += ("\n\nIf something looks off, adjust it by hand:\n"
                    "• The weapon isn't in the hand → Weapon Grips page (drag the weapon onto the hand).\n"
                    "• Colours → Sprites & Colors.\n"
                    "• It moves oddly in some attacks → make it again with another 'Moves like' choice.")
            info_box(self, f"New {what}", msg)

        def failed(msg):
            prog.close()
            if made_mod is not None and not any(f for f in made_mod.list_files()) and                     not any(os.scandir(made_mod.patches_dir) if os.path.isdir(made_mod.patches_dir) else ()):
                # nothing was made: the empty mod made for it goes again (no 'Henna', 'Henna_2' ... left behind)
                self.ws.set_active_mod(prev_active)
                self.ws.mods.delete(made_mod.id)
                self.ws.mods_changed.emit()
            QMessageBox.critical(self, f"New {what}", msg[:3000])

        w.done.connect(done)
        w.failed.connect(failed)
        w.start()

    def _label_of(self, cid):
        try:
            rows = {r["id"]: r for r in self.table().rows}
            return rows[cid]["name_EN"] or str(cid)
        except Exception:
            return str(cid)

    def _after_create(self, cid, v):
        """the stats preset and the fresh start (no skills, evilities, Overload) chosen in the New dialog"""
        self.select_character(cid)
        if v.get("preset"):
            self.apply_preset_key(v["preset"])
        if v.get("fresh"):
            fam = range(cid, cid + 6) if cid >= 1000 else (cid,)          # a class: every tier
            for r in self.table().rows:
                if r["id"] in fam:
                    charstudio.start_fresh(r)
            self.svc.mark_dirty(CHAR)
        self.svc.commit(CHAR, self)
        self._load_values()

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
        tip = QLabel(f"<b>Template:</b> {t['name_EN']} — {t['title_EN']} (id {t['id']})<br>"
                     "The new one starts as a copy of it (weapon ranks, resistances, movement, and the stats and "
                     "skills you choose below); change anything afterwards on this page.")
        tip.setWordWrap(True)
        f.addRow(tip)
        self.unique = QRadioButton("Unique character (one unit, recruited once)")
        self.klass = QRadioButton("Generic class (6 tiers, created at the Netherworld registrar)")
        (self.klass if generic else self.unique).setChecked(True)
        f.addRow(self.unique)
        f.addRow(self.klass)
        # a class is made from a class (its 6 tiers and rank chain): the chosen template's, or one picked here
        self.class_from = QComboBox()
        rows = page.table().rows
        for i, r in enumerate(rows):
            if 1000 <= r["id"] < 3000 and r["id"] % 10 == 0 and r["name_EN"] and                     r["name_EN"] not in RESERVED_TEXTS and not r["name_EN"].startswith("Dummy"):
                self.class_from.addItem(f"{r['name_EN']}  ({r['id']})", i)
        fam = t["id"] // 10 * 10
        want = next((k for k in range(self.class_from.count())
                     if rows[self.class_from.itemData(k)]["id"] == (fam if generic else 1010)), 0)
        self.class_from.setCurrentIndex(want)
        self.class_from.setToolTip("A new class starts as a copy of a class: its 6 tiers, class ranks, weapon ranks "
                                   "and resistances (and its look unless you choose another below).")
        f.addRow("Class to start from", self.class_from)

        def kind_changed(*_):
            look = getattr(self, "look", None)          # (a Disgaea RPG class takes its moves from "Animations from")
            show = self.klass.isChecked() and (look is None or look.currentData() != "drpg")
            self.class_from.setVisible(show)
            lab = f.labelForField(self.class_from)
            if lab is not None:
                lab.setVisible(show)
            # the stats / skills it copies are the chosen class's when it is a class
            src = (self.class_from.currentText().split("  (")[0] if show else t["name_EN"])
            if getattr(self, "preset_box", None) is not None:
                self.preset_box.setItemText(0, f"Same as {src}")
                self.fresh.setItemText(1, f"Copy {src}'s")
        self._kind_changed = kind_changed
        self.klass.toggled.connect(kind_changed)
        self.class_from.currentIndexChanged.connect(kind_changed)
        kind_changed()
        self.name = QLineEdit(t["name_EN"] + " II")
        self.title = QLineEdit(t["title_EN"])
        f.addRow("Name (class name for classes)", self.name)
        f.addRow("Title (tier-1 title for classes)", self.title)
        self.desc = QTextEdit()
        self.desc.setPlaceholderText("Up to 3 lines of about 42 characters (longer text is wrapped to fit)")
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
        self.look.addItem("Disgaea RPG sprites (choose a unit…)", "drpg")
        self.look.setItemData(1, "A unit from your Disgaea RPG folder (or four sheet files of your own) becomes the "
                                 "new character's or class's complete sprite, face and cut-in.",
                              Qt.ItemDataRole.ToolTipRole)
        self.look.addItem("A sprite sheet (any sheet: pick its drawings)…", "sheet")
        self.look.setItemData(2, "A sprite sheet PNG: the kit finds every drawing on it and you choose which are "
                                 "standing, idle, walking, hit, the attacks … Every pose of the template's sprite is "
                                 "redrawn with them (a monster template: its own moves). Unique characters only.",
                              Qt.ItemDataRole.ToolTipRole)
        self.sheet_seqs = None
        for o in sorted(self.outfits, key=lambda o: (o["who"].lower(), o["name"].lower())):
            label = f"{o['who']} — {o['name']}" + ("   (Disgaea RPG)" if o["drpg_uid"] is not None else "")
            self.look.addItem(label, o)
            self.look.setItemData(self.look.count() - 1, f"Outfit {o['outfit']} from the mod {o['mod'].name}",
                                  Qt.ItemDataRole.ToolTipRole)
        self.look.setToolTip("A new character can wear an outfit's look as its own: a Disgaea RPG outfit is drawn "
                             "again from its unit as a complete character; another outfit's sprite is copied. "
                             "Stats, skills and evilities come from the outfit's character.")
        f.addRow("Look", self.look)
        # Disgaea RPG sprites: the unit, and whose animations it moves with
        from d5lib import drpgsource
        self.page = page
        self.drpg_unit = None
        self._row_names = {r["id"]: r["name_EN"] for r in page.table().rows}
        self._char_anims = drpgsource.character_sprites()
        self._class_anims = drpgsource.class_templates()
        self._tid = t["id"]
        drow = QHBoxLayout()
        self.drpg_btn = QPushButton("Choose the unit…")
        self.drpg_btn.clicked.connect(self._choose_drpg)
        drow.addWidget(self.drpg_btn)
        self.drpg_label = QLabel("no unit chosen yet")
        self.drpg_label.setObjectName("muted")
        drow.addWidget(self.drpg_label, 1)
        self.drpg_row = QWidget()
        self.drpg_row.setLayout(drow)
        drow.setContentsMargins(0, 0, 0, 0)
        f.addRow("Disgaea RPG unit", self.drpg_row)
        self.anim = QComboBox()
        self.anim.setToolTip("Disgaea 5 moves every character with the poses of a game character: walking, the "
                             "attacks of each weapon, casting, getting hit, special poses. A Disgaea RPG unit brings "
                             "its pictures but no moves, so its pictures are drawn into the poses of the character "
                             "chosen here.\n\nOnly the movement comes from it — not stats, skills or evilities. Pick "
                             "one with a similar build and fighting style (a sword fighter for a sword fighter).")
        f.addRow("Animations from", self.anim)
        self.anim_note = QLabel()
        self.anim_note.setWordWrap(True)
        self.anim_note.setObjectName("muted")
        f.addRow("", self.anim_note)
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
        self.preset_box.addItem(f"Same as {t['name_EN']}", None)
        for key, label, desc, cid in charstudio.PRESETS:
            self.preset_box.addItem(label, key)
            self.preset_box.setItemData(self.preset_box.count() - 1, desc, Qt.ItemDataRole.ToolTipRole)
        self.preset_box.setToolTip("Base stats and aptitudes (how strong it grows); every unit starts at level 1")
        f.addRow("Starting stats", self.preset_box)
        self.fresh = QComboBox()
        self.fresh.addItem("None — give it its own on this page (recommended)", True)
        self.fresh.addItem(f"Copy {t['name_EN']}'s", False)
        self.fresh.setToolTip(f"Learned skills, evilities and Overload. Copying gives it {t['name_EN']}'s own skills "
                              "(their unique attacks included) and evilities; with None it starts with an empty list "
                              "and you choose its skills on the Characters & Classes page (or the 📂 skill browser).")
        f.addRow("Skills, evilities, Overload", self.fresh)

        def look_changed(*_):
            o = self.look.currentData()
            drpg = o == "drpg"
            sheet = o == "sheet"
            if sheet and self.sheet_seqs is None and not self._choose_sheet():
                self.look.setCurrentIndex(0)
                return
            self.hide_outfit.setEnabled(o is not None and not drpg and not sheet)
            self.clone_sprite.setEnabled(o is None)
            self.klass.setEnabled(o is None or drpg)
            self.klass.setToolTip("" if self.klass.isEnabled() else
                                  "An outfit's look or a sprite sheet makes a unique character (one unit).")
            if o is not None and not drpg:
                self.unique.setChecked(True)
                if not sheet and (self.name.text().endswith(" II") or not self.name.text().strip()):
                    self.name.setText(o["name"])
            for w in (self.drpg_row, self.anim, self.anim_note):
                w.setVisible(drpg)
                lab = f.labelForField(w)
                if lab is not None:
                    lab.setVisible(drpg)
            for w in (self.clone_sprite, self.hide_outfit):      # nothing to do with a DRPG unit's / a sheet's look
                w.setVisible(not drpg and not sheet)
            self._kind_changed()
            if drpg:
                self._fill_anims()
                if self.drpg_unit is None:
                    self._choose_drpg()
        self.look.currentIndexChanged.connect(look_changed)
        self.unique.toggled.connect(lambda *_: self._fill_anims() if self.look.currentData() == "drpg" else None)
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
        from ..questgoal import ObjectiveWidget
        self.objective = ObjectiveWidget(page.svc, self)
        f.addRow("To finish it", self.objective)
        self.quest.toggled.connect(lambda on: [w.setEnabled(on) for w in
                                               (self.quest_title, self.quest_client, self.quest_text, self.objective)])

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
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    # ---- Disgaea RPG sprites
    def _choose_drpg(self):
        from ..drpgpicker import DrpgPicker
        dlg = DrpgPicker(self.page.ws, "class" if self.klass.isChecked() else "character", self)
        if dlg.exec() and dlg.unit:
            self.drpg_unit = dlg.unit
            self.drpg_label.setText(dlg.unit.label())
            if dlg.unit.name and (self.name.text().endswith(" II") or not self.name.text().strip()):
                self.name.setText(dlg.unit.name)
            if dlg.unit.group == "generic" and self.klass.isEnabled():
                self.klass.setChecked(True)

    def _template_info(self):
        """(monster, standing height in px) of the template's sprite: a monster carries its own moves (the sheet is
        drawn onto those); the sheet's drawings are scaled to the height"""
        try:
            from d5lib import anm, sprites
            r = next(x for x in self.page.table().rows if x["id"] == self._tid)
            a = anm.parse(self.page.ws.read(sprites.sprite_vpath(self.page.ws.fs, r["sprite_id"],
                                                                  self.page.ws.language)))
            return not sprites.needs_motion_set(a), sprites.stand_height(self.page.ws.fs, a)
        except Exception:
            return False, 0

    def _choose_sheet(self):
        """the sprite sheet PNG and which of its drawings each animation uses -> True when chosen"""
        from PyQt6.QtWidgets import QFileDialog
        from ..sheetpicker import SheetPicker
        p, _ = QFileDialog.getOpenFileName(self, "Sprite sheet", "", "Images (*.png *.gif *.webp *.bmp)")
        if not p:
            return False
        monster, height = self._template_info()
        try:
            dlg = SheetPicker(p, self, monster=monster, target_height=height,
                              title=f"Sprite sheet for the new {'monster' if monster else 'character'}")
        except Exception as e:
            QMessageBox.warning(self, "Sprite sheet", f"The sheet could not be read: {e}")
            return False
        if not dlg.exec():
            return False
        seqs = dlg.sequences()
        if not seqs:
            QMessageBox.warning(self, "Sprite sheet", "No drawings were given to an animation.")
            return False
        self.sheet_seqs = seqs
        self.look.setItemText(2, f"Sprite sheet: {os.path.basename(p)} ({len(seqs)} animations)")
        return True

    def _fill_anims(self):
        """the characters / classes whose animations a DRPG unit can take (their poses are learned)"""
        klass = self.klass.isChecked()
        ids = self._class_anims if klass else self._char_anims
        cur = self.anim.currentData()
        self.anim.blockSignals(True)
        self.anim.clear()
        for c in ids:
            self.anim.addItem(f"{self._row_names.get(c, c)}  ({c})", c)
        want = cur if cur in ids else (self._tid if self._tid in ids else
                                       (self._tid // 10 * 10 if self._tid // 10 * 10 in ids else None))
        i = self.anim.findData(want) if want is not None else -1
        self.anim.setCurrentIndex(max(0, i))
        self.anim.blockSignals(False)
        self.anim_note.setText(
            "Why: Disgaea RPG units have pictures but no Disgaea 5 animations, so the new " +
            ("class" if klass else "character") + " moves like the one chosen here (walking, attacks, casting). "
            "Only its movement is borrowed: stats, skills and evilities are set below and on this page. Only "
            "characters and classes whose poses the kit has learned are listed.")

    def _ok(self):
        if self.look.currentData() == "drpg":
            if self.drpg_unit is None:
                QMessageBox.warning(self, "New character / class", "Choose the Disgaea RPG unit first.")
                return
            if self.anim.currentData() is None:
                QMessageBox.warning(self, "New character / class", "Choose whose animations it moves with.")
                return
        self.accept()

    def values(self):
        drpg = self.look.currentData() == "drpg"
        sheet = self.look.currentData() == "sheet"
        return {"generic": self.klass.isChecked(), "class_from": self.class_from.currentData(),
                "name": self.name.text().strip() or "New Unit",
                "title": self.title.text().strip(), "desc": self.desc.toPlainText().strip().split("\n"),
                "clone_sprite": self.clone_sprite.isChecked(), "quest": self.quest.isChecked(),
                "quest_title": self.quest_title.text().strip(), "quest_client": self.quest_client.text().strip(),
                "quest_text": self.quest_text.text().strip(), "quest_cond": self.objective.cond(),
                "outfit": None if drpg or sheet else self.look.currentData(),
                "hide_outfit": self.hide_outfit.isChecked() and self.look.currentData() is not None and not drpg
                and not sheet,
                "preset": self.preset_box.currentData(), "own_mod": self.own_mod.isChecked(),
                "fresh": bool(self.fresh.currentData()),
                "drpg": self.drpg_unit if drpg else None, "anim": self.anim.currentData() if drpg else None,
                "sheet": self.sheet_seqs if sheet else None}


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
    """a sprite number group nobody uses: not the game, and not ANY mod of the kit (switched on or not -- a number
    two mods share makes the later one's sprite replace the other's at install)"""
    from d5lib import outfits
    if mod is not None:
        return outfits._free_sprite(fs, mod)
    used = sprites.used_sprite_numbers(fs)
    for n in outfits.SPRITE_NUMBERS:
        if not {n, n + 1, n + 2, n + 10000, n + 10001} & used:
            return n
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
    if v["generic"] and v.get("class_from") is not None:
        t_index = v["class_from"]                  # a class is made from a class (chosen in the dialog)
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
    if not v["generic"] and not any(v["desc"]):
        v["desc"] = dbpatch.default_help(v["name"], v["title"])      # its own description, never the template's
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
        help_text = dbpatch.help_lines(v["desc"])
        for k in range(3):
            _set_all_langs(hr, f"line{k + 1}", help_text[k])
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
        page._last_clone = (tmpl["sprite_id"], n)
        for r in new_rows:
            r.set("sprite_id", n)
        lines.append(f"Copied the sprite to anm{n:05d} (+ portrait anm{n + 10000:05d}); files: {len(done)}. "
                     "Open it on the Sprites & Colors page to repaint or recolor it.")

    # recruit quest
    if v["quest"]:
        q = svc.table("Quest.dat")
        src = q.index_of(1)  # 'Combat Lecture': simple, available from the start
        qr = q.add_row(copy_from=src if src >= 0 else 0)
        every = page.ws.mods.all_mods()                 # ids and slots stay unique across all mods, on or off
        qid = dbpatch.new_quest_id(q, every)
        qr.set("id", qid)
        _set_all_langs(qr, "name", v["quest_title"] or "A New Ally")
        _set_all_langs(qr, "client", v["quest_client"] or v["name"])
        for k, line in enumerate(dbpatch.quest_lines(v["quest_text"]), 1):      # wrapped like the game's own
            _set_all_langs(qr, f"desc{k}", line)
        # sort_order is the quest's progress slot in the save; the board only scans slots below the row count
        qr.set("sort_order", dbpatch.free_quest_slot(q, exclude=qr, reserved=dbpatch.mod_quest_slots(every)))
        qr.set("reward_type", 6 if v["generic"] else 5)
        qr.set("reward_value", unit_id)
        qr.set("reward_count", 1)
        qr.set("important", 1)
        from d5lib import questcheck
        questcheck.set_objective(qr, v.get("quest_cond"))
        svc.mark_dirty("Quest.dat")
        from .. import questinfo
        lines.append(f"Added quest #{qid} '{v['quest_title']}' that {'unlocks the class' if v['generic'] else 'recruits the character'}. "
                     f"Its objective: {questinfo.objective(svc, qr)} (change it under 'How to get this character').")

    if v.get("preset") and not v["generic"]:          # (a class's tiers keep their own growing numbers)
        _, label, _, pcid = charstudio.preset(v["preset"])
        src = next((x for x in svc.vanilla(CHAR).rows if x["id"] == pcid), None)
        if src is not None:
            for r in new_rows:
                charstudio.copy_fields(r, src, ("base", "apt", "move"))
            lines.append(f"Starting stats: {label}.")
    if v.get("fresh"):
        for r in new_rows:
            charstudio.start_fresh(r)
        lines.append("It starts with no learned skills, evilities or Overload: give it its own on this page.")
    svc.mark_dirty(CHAR)
    svc.commit(CHAR, page)
    for m in ("JobRank.dat", "charhelp.dat", "Quest.dat"):
        if svc.is_dirty(m):
            svc.commit(m, page)
    return "\n\n".join(lines) + "\n\nEverything is saved in your mod. Press Install to try it in game."
