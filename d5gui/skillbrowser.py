"""Pick a skill from categories instead of one long list: weapon skills by weapon, spells by element, each
character's own skills under that character, class and monster skills by class, the skills your mods add.

magic.dat tells them apart: skill_group 1-6 are the weapon skills (weapon_type 1 Fist .. 6 Axe), 0 the spells
(element 1 Fire, 2 Wind, 3 Ice, 4 Star, 0 healing / support), 7 the story characters' skills (user1..user4: who uses
them; a combination skill has two), 10 the guest characters', 8 the human classes', 9 the monsters', 11 and 255
the special ones (Netherworld Drop, captures, commands).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QSplitter, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

WEAPONS = {1: "Fist", 2: "Sword", 3: "Spear", 4: "Bow", 5: "Gun", 6: "Axe", 7: "Staff", 8: "Monster weapon",
           9: "Tower (monsters)"}
ELEMENTS = {1: "Fire", 2: "Wind", 3: "Ice", 4: "Star", 0: "Healing & support"}
ROLE = Qt.ItemDataRole.UserRole


def categories(magic, chars, vanilla_ids=(), me=None):
    """[(path tuple, id, name)] for every skill of the magic.dat table (most fall in one place; a combination skill
    is under each of its characters).  chars: {class id: name}; vanilla_ids: the game's own skill ids (others are
    'New skills'); me: (class id, name) of the character being edited: its skills first."""
    vanilla_ids = set(vanilla_ids)
    out = []
    for r in magic.rows:
        sid, name = r["id"], r["name_EN"] or f"skill {r['id']}"
        users = [r[f"user{k}"] for k in range(1, 5) if r[f"user{k}"]]
        g, wt, el = r["skill_group"], r["weapon_type"], r["element"]
        uname = [chars.get(u, f"#{u}") for u in users]
        paths = []
        if name.endswith("Dummy"):                     # the game's placeholder spells
            out.append((("Special & commands",), sid, name))
            continue
        if me and me[0] in users:
            paths.append((f"{me[1]}'s own",))
        if vanilla_ids and sid not in vanilla_ids:
            paths.append(("New skills (your mods)", uname[0] if uname else "Other"))
        elif 1 <= g <= 6 or wt in WEAPONS and wt != 10 and g not in (7, 8, 9, 10):
            paths.append(("Weapon skills", WEAPONS.get(wt or g, f"Weapon {wt or g}")))
        elif g == 0:
            paths.append(("Spells", ELEMENTS.get(el, f"Element {el}")))
        elif g in (7, 10) and users:
            for u in uname:
                paths.append(("Character skills", u))
        elif g == 8 and users:
            paths.append(("Class skills", uname[0]))
        elif g == 9 and users:
            paths.append(("Monster skills", uname[0]))
        elif users:
            paths.append(("Other skills", uname[0]))
        else:
            paths.append(("Special & commands",))
        for p in paths:
            out.append((p, sid, name))
    return out


ORDER = ["'s own", "New skills (your mods)", "Weapon skills", "Spells", "Character skills", "Class skills",
         "Monster skills", "Other skills", "Special & commands"]


def _rank(top):
    return next((i for i, k in enumerate(ORDER) if top.endswith(k) or top == k), len(ORDER))


class SkillBrowser(QDialog):
    def __init__(self, parent, svc, current=None, me=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a skill")
        self.resize(820, 560)
        self._value = None
        magic = svc.table("magic.dat")
        try:
            vanilla = {r["id"] for r in svc.vanilla("magic.dat").rows}
        except Exception:
            vanilla = set()
        chars = {}
        for r in svc.table("char.dat").rows:
            chars.setdefault(r["id"], r["name_EN"])
        self.tips = svc.ref_tooltips("magic.dat")
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or id…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._show)
        self.tree.itemDoubleClicked.connect(lambda it, _: self._pick(it))
        split.addWidget(self.tree)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(6, 0, 0, 0)
        self.desc = QLabel("Pick a skill on the left.")
        self.desc.setWordWrap(True)
        self.desc.setTextFormat(Qt.TextFormat.RichText)
        self.desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        sl.addWidget(self.desc, 1)
        split.addWidget(side)
        split.setSizes([480, 320])
        lay.addWidget(split, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(lambda: self._pick(self.tree.currentItem()))
        bb.rejected.connect(self.reject)
        row = QHBoxLayout()
        none = bb.addButton("No skill", QDialogButtonBox.ButtonRole.ResetRole)
        none.clicked.connect(self._none)
        row.addWidget(bb)
        lay.addLayout(row)
        self._build(categories(magic, chars, vanilla, me), current)

    def _build(self, cats, current):
        nodes = {}
        found = None
        for path, sid, name in sorted(cats, key=lambda c: (_rank(c[0][0]), c[0], c[1])):
            parent = None
            for depth in range(len(path)):
                key = path[:depth + 1]
                if key not in nodes:
                    it = QTreeWidgetItem([path[depth]])
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
                    nodes[key] = it
                parent = nodes[key]
            leaf = QTreeWidgetItem([f"{name}  ·  {sid}"])
            leaf.setData(0, ROLE, sid)
            tip = self.tips.get(sid)
            if tip:
                leaf.setToolTip(0, tip)
            parent.addChild(leaf)
            if sid == current and found is None:
                found = leaf
        for key, it in nodes.items():                      # counts on the folders
            n = self._count(it)
            it.setText(0, f"{key[-1]}  ({n})")
        if found is not None:
            self.tree.setCurrentItem(found)
            self.tree.scrollToItem(found)
        else:
            top = self.tree.topLevelItem(0)
            if top is not None and top.text(0).split("  (")[0].endswith("'s own"):
                top.setExpanded(True)

    @staticmethod
    def _count(it):
        n = 0
        for i in range(it.childCount()):
            c = it.child(i)
            n += 1 if c.data(0, ROLE) is not None else SkillBrowser._count(c)
        return n

    def _filter(self, text):
        t = text.strip().lower()

        def walk(it):
            if it.data(0, ROLE) is not None:
                hit = not t or t in it.text(0).lower()
                it.setHidden(not hit)
                return hit
            any_hit = False
            for i in range(it.childCount()):
                any_hit = walk(it.child(i)) or any_hit
            it.setHidden(not any_hit)
            if t:
                it.setExpanded(any_hit)
            return any_hit
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        cur = self.tree.currentItem()
        if t and (cur is None or cur.isHidden() or cur.data(0, ROLE) is None):
            first = self._first_visible()
            if first is not None:
                self.tree.setCurrentItem(first)

    def _first_visible(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())][::-1]
        while stack:
            it = stack.pop()
            if it.isHidden():
                continue
            if it.data(0, ROLE) is not None:
                return it
            stack += [it.child(i) for i in range(it.childCount())][::-1]
        return None

    def _show(self, it, _=None):
        sid = it.data(0, ROLE) if it is not None else None
        if sid is None:
            self.desc.setText("Open a group and pick a skill.")
            return
        self.desc.setText(self.tips.get(sid) or it.text(0))

    def _pick(self, it):
        if it is None or it.data(0, ROLE) is None:
            if it is not None:
                it.setExpanded(not it.isExpanded())
            return
        self._value = int(it.data(0, ROLE))
        self.accept()

    def _none(self):
        self._value = 0
        self.accept()

    def value(self):
        return self._value
