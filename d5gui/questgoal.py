"""Picking what a quest asks for: clear a stage (one of the game's, or a stage of your own from Stages & Maps) or
defeat enemies of a class.  Used by the New character dialog and by "How to get this character" on the Characters
page (d5lib.questcheck does the table work)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                             QSpinBox, QVBoxLayout, QWidget)

from d5lib import mapfile, questcheck
from .common import type_to_search
from .dbservice import char_names


def _searchable(cb):
    """an editable combo found by typing part of an entry's name"""
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    cb.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    cb.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    type_to_search(cb)


class ObjectiveWidget(QWidget):
    """goal (clear a stage / defeat enemies) + its target"""

    def __init__(self, svc, parent=None, cond=None):
        super().__init__(parent)
        self.svc = svc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.goal = QComboBox()
        self.goal.addItem("Clear a stage", questcheck.CLEAR_STAGE)
        self.goal.addItem("Defeat enemies of a class", questcheck.DEFEAT)
        self.goal.setToolTip("What the player has to do before the quest can be turned in at the Quest shop")
        lay.addWidget(self.goal)
        self.stage = QComboBox()
        try:
            choices = questcheck.stage_choices(svc.table("dungeon.dat"), len(svc.vanilla("dungeon.dat").rows),
                                               mapfile.DungeonRecord)
        except Exception:
            choices = [("Dried Up Wasteland  (map00101)", 101, False)]
        for label, mid, mine in choices:
            self.stage.addItem(label, mid)
            if mine:
                self.stage.setItemData(self.stage.count() - 1, Qt.GlobalColor.cyan, Qt.ItemDataRole.ForegroundRole)
        self.stage.setToolTip("The stage to clear (your own stages from Stages & Maps are listed too; a quest that "
                              "asks for a stage of a mod needs that mod switched on)")
        _searchable(self.stage)
        lay.addWidget(self.stage)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setValue(5)
        self.klass = QComboBox()
        self.klass.addItem("any enemy", -1)
        try:
            for cid, name in sorted(char_names(svc).items()):
                if cid < 5000:
                    self.klass.addItem(f"{name}  ({cid})", cid)
        except Exception:
            pass
        _searchable(self.klass)
        hl.addWidget(self.count)
        hl.addWidget(QLabel("×"))
        hl.addWidget(self.klass, 1)
        self.defeat_row = row
        lay.addWidget(row)
        self.goal.currentIndexChanged.connect(self._goal_changed)
        self._goal_changed()
        if cond:
            self.set_cond(cond)

    def _goal_changed(self, *_):
        clear = self.goal.currentData() == questcheck.CLEAR_STAGE
        self.stage.setVisible(clear)
        self.defeat_row.setVisible(not clear)

    def cond(self):
        if self.goal.currentData() == questcheck.CLEAR_STAGE:
            return {"type": questcheck.CLEAR_STAGE, "target": int(self.stage.currentData() or 101), "count": 1}
        return {"type": questcheck.DEFEAT, "target": int(self.klass.currentData()), "count": self.count.value()}

    def set_cond(self, cond):
        t = int(cond.get("type", questcheck.CLEAR_STAGE))
        if t == questcheck.CLEAR_STAGE:
            self.goal.setCurrentIndex(0)
            k = self.stage.findData(int(cond.get("target", 101)))
            if k < 0:
                self.stage.addItem(f"map{int(cond.get('target', 0)):05d}", int(cond.get("target", 0)))
                k = self.stage.count() - 1
            self.stage.setCurrentIndex(k)
        elif t == questcheck.DEFEAT:
            self.goal.setCurrentIndex(1)
            k = self.klass.findData(int(cond.get("target", -1)))
            self.klass.setCurrentIndex(max(0, k))
            self.count.setValue(max(1, int(cond.get("count", 1))))
        else:                                         # another kind (items, levels): shown as is, changed on OK only
            self.goal.addItem(f"(objective type {t}: kept)", t)
            self.goal.setCurrentIndex(self.goal.count() - 1)
            self.stage.hide()
            self.defeat_row.hide()
        self._goal_changed()

    def changed_from(self, cond):
        return self.goal.currentData() in (questcheck.CLEAR_STAGE, questcheck.DEFEAT) and self.cond() != cond


class ObjectiveDialog(QDialog):
    def __init__(self, parent, svc, row, title="What the quest asks for"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 200)
        f = QFormLayout(self)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        intro = QLabel(f"Quest <b>“{row['name_EN']}”</b>: the player has to…")
        intro.setWordWrap(True)
        f.addRow(intro)
        self.cond0 = questcheck.objective_of(row)
        self.obj = ObjectiveWidget(svc, self, self.cond0)
        f.addRow(self.obj)
        note = QLabel("A stage of one of your mods: that mod has to be switched on when you install, or the quest "
                      "can't be finished (Home warns you).")
        note.setWordWrap(True)
        note.setObjectName("muted")
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def cond(self):
        return self.obj.cond() if self.obj.changed_from(self.cond0) else None
