"""Outfits › Edit › Own evilities, stats & weapons… (OUTFITOWN1).

An outfit is its character in other clothes: by default its char.dat row follows the character's (outfits._follow_base),
so a mod that changes the character changes every outfit.  Here a group (evilities, base stats, aptitudes, weapon
mastery, movement, resistances) can be given values of the outfit's own instead; they are stored in the outfit pack's
outfits.json (`own_fields`) and applied at install.  An unticked group keeps following the character."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QLabel, QScrollArea, QSpinBox,
                             QComboBox, QVBoxLayout, QWidget)

from d5lib import database, outfits
from .dbservice import table_names
from .pages.characters import HELP, RANKS, STATS, WEAPONS, rank_of
from .pages.stages import SearchCombo, set_choice_tips

CHAR = "char.dat"
WEAPON_LABEL = dict(WEAPONS)
FIELD_LABEL = {**{f"base_{s}": s for s in STATS}, **{f"apt_{s}": f"{s} %" for s in STATS},
               **{f"mastery_{k}": v for k, v in WEAPONS}, "MOV": "Move", "JMP": "Jump", "counter": "Counter",
               "throw": "Throw", "crit": "Critical %",
               **{f"res_{e}": e.capitalize() for e in ("fire", "wind", "ice", "star")},
               **{f"wres_{k}": f"vs {v}" for k, v in WEAPONS if k not in ("monster_phys", "monster_mag", "armor")},
               "wres_monster": "vs Monster"}
FIELD_HELP = {**{f"base_{s}": f"{HELP[s]}\n\n{HELP['base']}" for s in STATS},
              **{f"apt_{s}": f"{HELP[s]}\n\n{HELP['apt']}" for s in STATS},
              **{f: HELP[f] for f in ("MOV", "JMP", "counter", "throw", "crit")},
              **{f"res_{e}": HELP["res"] for e in ("fire", "wind", "ice", "star")}}


def _row(svc, cid):
    return next((r for r in svc.table(CHAR).rows if int(r["id"]) == int(cid)), None)


class OwnFieldsDialog(QDialog):
    """Tick a group to give the outfit its own values; unticked groups follow the character."""

    def __init__(self, svc, mod, base, slot, who, outfit_name, parent=None):
        super().__init__(parent)
        self.svc, self.mod, self.slot = svc, mod, int(slot)
        self.setWindowTitle(f"Own values: {who} — “{outfit_name}”")
        self.resize(820, 760)
        base_row = _row(svc, base)
        if base_row is None:
            raise ValueError(f"character {base} not found in char.dat")
        schema = {f.name: f for f in database.get_schema(CHAR).fields}
        saved = outfits.load_own_fields(mod).get(self.slot, {})
        lay = QVBoxLayout(self)
        note = QLabel(f"By default the outfit has {who}'s values, and changes to {who} apply to it too. Tick a group "
                      "to give this outfit values of its own; untick it to follow the character again. Install to "
                      "apply. A unit takes the outfit's values as soon as it switches to it and gives them back "
                      "when it switches away; each group says how.")
        note.setWordWrap(True)
        lay.addWidget(note)
        inner = QWidget()
        il = QVBoxLayout(inner)
        self.groups, self.widgets = {}, {}
        evil = None
        for gname, (label, fields) in outfits.OWN_GROUPS.items():
            box = QGroupBox(f"Own {label.lower()}")
            box.setCheckable(True)
            box.setChecked(gname in saved)
            timing = outfits.OWN_TIMING.get(gname)
            if timing:
                box.setToolTip(timing)
            grid = QGridLayout(box)
            row0 = 0
            if timing:
                t = QLabel(timing)
                t.setWordWrap(True)
                t.setObjectName("muted")
                grid.addWidget(t, 0, 0, 1, 8)
                row0 = 1
            have = saved.get(gname, {})
            cols = 2 if gname == "evilities" else 4
            for c in range(cols):
                grid.setColumnStretch(2 * c + 1, 1)
            for i, f in enumerate(fields):
                v = int(have.get(f, base_row[f]))
                if gname == "evilities":
                    if evil is None:
                        evil = sorted(table_names(svc, "Skill.dat").items())
                        set_choice_tips(evil, svc.ref_tooltips("Skill.dat"))
                    w = SearchCombo(evil)
                    w.setMinimumWidth(150)
                    w.set_value(v)
                    w.setToolTip(HELP["evility"])
                    lab = f"Evility {i + 1}"
                elif gname == "weapon_mastery":
                    w = QComboBox()
                    for t, rv in RANKS:
                        w.addItem(t, rv)
                    band = next(rv for _t, rv in RANKS if rank_of(rv) == rank_of(v))
                    w.setCurrentIndex(w.findData(band))
                    w.setProperty("raw", v)           # a value already in the chosen band is kept
                    w.setToolTip(HELP["mastery"] + f"\n\nNow: {w.currentText()} (aptitude {v})")
                    lab = WEAPON_LABEL.get(f[len("mastery_"):], f)
                else:
                    w = QSpinBox()
                    a, b = database._range(schema[f].type)
                    w.setRange(max(a, -2147483647), min(b, 2147483647))
                    w.setValue(v)
                    w.setToolTip(FIELD_HELP.get(f, HELP.get("wres", "")) if not f.startswith("wres_")
                                 else HELP["wres"])
                    lab = FIELD_LABEL.get(f, f)
                r, c = divmod(i, cols)
                grid.addWidget(QLabel(lab), row0 + r, 2 * c, Qt.AlignmentFlag.AlignRight)
                grid.addWidget(w, row0 + r, 2 * c + 1)
                self.widgets[f] = (gname, w)
            self.groups[gname] = box
            il.addWidget(box)
        il.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(inner)
        lay.addWidget(sc, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _value(self, gname, w):
        if gname == "evilities":
            return int(w.value() or 0)
        if gname == "weapon_mastery":
            band, raw = int(w.currentData()), int(w.property("raw") or 0)
            return raw if rank_of(raw) == rank_of(band) else band
        return int(w.value())

    def values(self):
        """{group: {field: value}} for the ticked groups"""
        out = {}
        for f, (gname, w) in self.widgets.items():
            if self.groups[gname].isChecked():
                out.setdefault(gname, {})[f] = self._value(gname, w)
        return out

    def save(self):
        return outfits.set_own_fields(self.mod, self.slot, self.values())


def summary(mod, slot):
    """'own evilities, weapon mastery' / '' for the page's info line"""
    own = outfits.load_own_fields(mod).get(int(slot), {})
    return ", ".join(f"own {outfits.OWN_GROUPS[g][0].lower()}" for g in outfits.OWN_GROUPS if g in own)
