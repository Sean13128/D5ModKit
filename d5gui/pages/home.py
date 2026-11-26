import os
import zipfile

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QToolButton, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QGridLayout, QLineEdit, QTextEdit,
                             QComboBox, QDialog, QDialogButtonBox, QFormLayout, QMenu, QTreeWidget, QTreeWidgetItem,
                             QStackedWidget, QAbstractItemView, QInputDialog, QButtonGroup, QHeaderView)

from d5lib import modinfo

from ..common import Card, PageHeader, SearchBox, human_size
from ..status import StatusPanel

ROLE = Qt.ItemDataRole.UserRole
KIND = Qt.ItemDataRole.UserRole + 1        # tree items: "mod" / "pack" / "group"


def mod_subtitle(line, missing_names=()):
    """a mod row's second column: the description (which starts with the program-change label for a patches/exe mod)
    and, beside it, the unmet-dependency warning.  Neither may hide the other."""
    dep = ("⚠ needs " + ", ".join(missing_names)) if missing_names else ""
    return " · ".join(x for x in (dep, line) if x)


class ModDialog(QDialog):
    def __init__(self, meta=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mod details")
        meta = meta or {}
        f = QFormLayout(self)
        self.name = QLineEdit(meta.get("name", ""))
        self.author = QLineEdit(meta.get("author", ""))
        self.version = QLineEdit(meta.get("version", "1.0"))
        self.desc = QTextEdit(meta.get("description", ""))
        self.desc.setFixedHeight(90)
        self.category = QComboBox()
        self.category.addItem("Automatic (from what the mod holds)", "")
        for key, label in modinfo.CATEGORIES:
            self.category.addItem(label.replace("  ", " "), key)
        i = self.category.findData(meta.get("category", ""))
        self.category.setCurrentIndex(max(0, i))
        self.category.setToolTip("Where the mod is listed on the Home page")
        f.addRow("Name", self.name)
        f.addRow("Author", self.author)
        f.addRow("Version", self.version)
        f.addRow("Category", self.category)
        f.addRow("Description", self.desc)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        return {"name": self.name.text().strip(), "author": self.author.text().strip(),
                "version": self.version.text().strip(), "description": self.desc.toPlainText().strip(),
                "category": self.category.currentData() or ""}


STEPS = [("1", "Pick a mod for new edits",
          "Edits are saved into mods: folders of changes you can switch on and off. A change to something a mod "
          "already makes goes into that mod by itself; everything else into <b>New edits go to</b> (bottom left)."),
         ("2", "Edit and press Save",
          "Use the editors on the left. <b>Save</b> (or Ctrl+S) stores the change in the mod — the game is not "
          "touched yet."),
         ("3", "Install && Play",
          "The status box (bottom left) tells you when the game is missing your latest changes. "
          "<b>Install &amp; Play</b> writes every enabled mod into the game; the originals are backed up.")]


PROFILE_HELP = ("A profile is a modpack: which mods are switched on and their load order. Each profile keeps its "
                "own, like the profiles of Mod Organizer for Skyrim; the mods themselves are shared, so switching is "
                "instant. A <b>separate project</b> profile starts from the plain game instead and sees only its own "
                "mods (Profile ▾ › Import mods from another profile copies some in). The game gets the profile's mods "
                "when you press Install. A profile can also keep its own saves (Profile ▾ › Separate saves).")


class NewProfileDialog(QDialog):
    def __init__(self, parent=None):
        from PyQt6.QtWidgets import QRadioButton
        super().__init__(parent)
        self.setWindowTitle("New profile")
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit()
        f.addRow("Name", self.name)
        v.addLayout(f)
        self.isolated = QRadioButton("A separate project: start from the plain game")
        hint1 = QLabel("Sees only its own mods: the mods of your other profiles stay out of its lists, its new ids "
                       "(classes, characters, sprites…) and its Install. Bring some over later with Profile ▾ › "
                       "Import mods from another profile (copies).")
        self.shared = QRadioButton("A modpack of the shared mods")
        hint2 = QLabel("The mods you have now, none switched on yet: pick which ones this modpack uses.")
        for w in (hint1, hint2):
            w.setWordWrap(True)
            w.setStyleSheet("color: gray; margin-left: 22px;")
        self.isolated.setChecked(True)
        for w in (self.isolated, hint1, self.shared, hint2):
            v.addWidget(w)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(460, 0)


class ImportProfileDialog(QDialog):
    """tick mods of the other profiles: copies of them come into this one"""

    def __init__(self, parent, groups, profile):
        super().__init__(parent)
        self.setWindowTitle("Import mods from another profile")
        v = QVBoxLayout(self)
        lab = QLabel(f"Tick the mods to copy into <b>{profile.name}</b>. Each comes in as a copy, like a shared mod "
                     "you import: ids that clash with this profile's mods are moved.")
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for p, mods in groups:
            top = QTreeWidgetItem([p.name + ("   (separate project)" if p.isolated else "   (shared mods)")])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
            top.setCheckState(0, Qt.CheckState.Unchecked)
            on = set(p.load_order())
            for m in mods:
                it = QTreeWidgetItem([f"{m.name}   v{m.meta.get('version', '')}" + ("" if m.id in on else
                                                                                    "   (switched off there)")])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Unchecked)
                it.setData(0, ROLE, m)
                it.setToolTip(0, m.meta.get("description") or "")
                top.addChild(it)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
        v.addWidget(self.tree)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Copy in")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(520, 460)

    def chosen(self):
        out, seen = [], set()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for k in range(top.childCount()):
                it = top.child(k)
                m = it.data(0, ROLE)
                if it.checkState(0) == Qt.CheckState.Checked and m.id not in seen:
                    seen.add(m.id)
                    out.append(m)
        return out


class HomePage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws, self.main = ws, main
        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        outer.addWidget(PageHeader("Home", "Your mods and the state of the game."))

        # ---- how it works
        steps = QHBoxLayout()
        steps.setSpacing(10)
        for num, title, text in STEPS:
            c = Card()
            c.setObjectName("stepCard")
            row = QHBoxLayout()
            n = QLabel(num)
            n.setObjectName("stepNum")
            n.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(n)
            col = QVBoxLayout()
            t = QLabel(title.replace("&&", "&"))
            t.setObjectName("cardTitle")
            col.addWidget(t)
            d = QLabel(text)
            d.setObjectName("muted")
            d.setWordWrap(True)
            col.addWidget(d)
            row.addLayout(col, 1)
            c.lay.addLayout(row)
            steps.addWidget(c, 1)
        steps_box = QWidget()
        steps_box.setLayout(steps)
        steps.setContentsMargins(0, 0, 0, 0)
        hide = QToolButton()
        hide.setText("✕")
        hide.setToolTip("Hide these tips (Guide & Tutorials has them)")
        hide.setAutoRaise(True)
        hide.clicked.connect(lambda: (steps_box.hide(), self.ws.settings.__setitem__("hide_home_steps", True),
                                      self.ws.save_settings()))
        steps.addWidget(hide, 0, Qt.AlignmentFlag.AlignTop)
        steps_box.setVisible(not self.ws.settings.get("hide_home_steps"))
        outer.addWidget(steps_box)

        # ---- game status (the same controller as the sidebar box)
        outer.addWidget(StatusPanel(main.status, large=True))

        grid = QGridLayout()
        grid.setSpacing(10)
        outer.addLayout(grid, 1)

        # ---- mods: by category (tree) or in load order (list)
        m = Card("Mods")
        prow = QHBoxLayout()
        pl = QLabel("Profile:")
        pl.setToolTip(PROFILE_HELP)
        prow.addWidget(pl)
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(180)
        self.profile_box.setToolTip(PROFILE_HELP)
        self.profile_box.activated.connect(self._profile_chosen)
        prow.addWidget(self.profile_box, 1)
        b = QPushButton("＋ New profile…")
        b.setToolTip("A new modpack: starts with no mod switched on (or copy this one from the menu next to it)")
        b.clicked.connect(lambda: self.new_profile(copy=False))
        prow.addWidget(b)
        pm = QPushButton("Profile ▾")
        menu = QMenu(pm)
        menu.addAction("Copy this profile…", lambda: self.new_profile(copy=True))
        menu.addAction("Import mods from another profile…", self.import_from_profile)
        menu.addAction("Rename…", self.rename_profile)
        menu.addAction("Delete…", self.delete_profile)
        menu.addSeparator()
        self.act_saves = menu.addAction("Separate saves for this profile")
        self.act_saves.setCheckable(True)
        self.act_saves.setToolTip("This profile keeps its own saves: they go into the game with its mods")
        self.act_saves.triggered.connect(self.toggle_profile_saves)
        menu.setToolTipsVisible(True)
        pm.setMenu(menu)
        prow.addWidget(pm)
        m.lay.addLayout(prow)
        self.profile_note = QLabel()
        self.profile_note.setObjectName("muted")
        self.profile_note.setWordWrap(True)
        m.lay.addWidget(self.profile_note)
        top = QHBoxLayout()
        self.search = SearchBox("Find a mod, a character, an outfit…")
        self.search.textChanged.connect(lambda _: self._fill_tree())
        top.addWidget(self.search, 1)
        self.view_group = QButtonGroup(self)
        for i, (text, tip) in enumerate([("By category", "Mods grouped by what they add; tick a group to switch all of it"),
                                         ("Load order", "The order mods are installed in: drag to reorder, lower "
                                                        "mods win when two change the same thing")]):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setChecked(i == 0)
            self.view_group.addButton(b, i)
            top.addWidget(b)
        self.view_group.idClicked.connect(lambda i: (self.mod_views.setCurrentIndex(i), self.refresh()))
        m.lay.addLayout(top)
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        m.lay.addWidget(self.count_label)
        self.mod_views = QStackedWidget()
        self.modtree = QTreeWidget()
        self.modtree.setColumnCount(2)
        self.modtree.setHeaderLabels(["Mod", "What it adds"])
        self.modtree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.modtree.header().resizeSection(0, 250)
        self.modtree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.modtree.itemChanged.connect(self._tree_checked)
        self.modtree.currentItemChanged.connect(self._show_mod)
        self.modtree.itemDoubleClicked.connect(self._tree_double)
        self.modtree.itemExpanded.connect(self._remember_open)
        self.modtree.itemCollapsed.connect(self._remember_open)
        self.modtree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.modtree.customContextMenuRequested.connect(self._menu)
        self.mod_views.addWidget(self.modtree)
        self.modlist = QListWidget()
        self.modlist.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.modlist.model().rowsMoved.connect(self._save_order)
        self.modlist.itemChanged.connect(self._save_order)
        self.modlist.currentItemChanged.connect(self._show_mod)
        self.modlist.itemDoubleClicked.connect(lambda _: self.activate_mod())
        self.modlist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.modlist.customContextMenuRequested.connect(self._menu)
        self.mod_views.addWidget(self.modlist)
        m.lay.addWidget(self.mod_views, 1)
        hint = QLabel("☑ = installed into the game.  ✎ = the mod your edits are saved into (double-click a mod to "
                      "choose it).  Select several mods and right-click › <b>Group into a pack</b> to switch them as "
                      "one; the mods themselves don't change.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        m.lay.addWidget(hint)
        row = QHBoxLayout()
        b = QPushButton("＋ New mod")
        b.clicked.connect(self.new_mod)
        row.addWidget(b)
        self.b_active = QPushButton("✎ Save my edits here")
        self.b_active.setToolTip("Make the selected mod the one your Save buttons write into")
        self.b_active.clicked.connect(self.activate_mod)
        row.addWidget(self.b_active)
        more = QPushButton("More ▾")
        menu = QMenu(more)
        for text, fn in [("Edit details…", self.edit_mod), ("Open folder", self.open_mod_folder),
                         ("Group selected into a pack…", self.make_pack), (None, None),
                         ("Share (export as .zip)…", self.export_mod),
                         ("Import / update from .zip…", self.import_mod),
                         ("Share all by game…", self.export_all_by_game),
                         ("Import folder…", self.import_folder),
                         ("Make my own version…", self.derive_mod), (None, None),
                         ("Check saves…", self.check_saves),
                         ("Delete mod…", self.delete_mod)]:
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text, fn)
        more.setMenu(menu)
        row.addWidget(more)
        row.addStretch(1)
        m.lay.addLayout(row)
        grid.addWidget(m, 0, 0)

        # ---- selected mod: what it adds, then its files
        d = Card()
        self.mod_title = QLabel()
        self.mod_title.setObjectName("cardTitle")
        d.lay.addWidget(self.mod_title)
        self.mod_info = QLabel()
        self.mod_info.setWordWrap(True)
        self.mod_info.setTextFormat(Qt.TextFormat.RichText)
        d.lay.addWidget(self.mod_info)
        self.mod_summary = QLabel()
        self.mod_summary.setWordWrap(True)
        self.mod_summary.setTextFormat(Qt.TextFormat.RichText)
        self.mod_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        d.lay.addWidget(self.mod_summary)
        fl = QLabel("Files and changes")
        fl.setObjectName("muted")
        d.lay.addWidget(fl)
        self.mod_files = QListWidget()
        d.lay.addWidget(self.mod_files, 1)
        row = QHBoxLayout()
        b = QPushButton("Remove selected change")
        b.setToolTip("Delete this change from the mod (the game gets the original back at the next install)")
        b.clicked.connect(self.remove_change)
        row.addWidget(b)
        row.addStretch(1)
        d.lay.addLayout(row)
        grid.addWidget(d, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # ---- game folder / language
        g = QHBoxLayout()
        self.game_label = QLabel()
        self.game_label.setObjectName("muted")
        g.addWidget(self.game_label, 1)
        g.addWidget(QLabel("Language:"))
        self.lang = QComboBox()
        self.lang.addItems(["EN", "FR", "JP"])
        self.lang.setCurrentText(self.ws.language)
        self.lang.currentTextChanged.connect(self._lang_changed)
        self.lang.setToolTip("The language you play in. Sprites / maps with localized versions are edited in that "
                             "language's archive.")
        g.addWidget(self.lang)
        b = QPushButton("Change game folder…")
        b.clicked.connect(self.change_game_dir)
        g.addWidget(b)
        from PyQt6.QtWidgets import QCheckBox
        from d5lib.version import VERSION
        up = QPushButton(f"Check for updates (v{VERSION})")
        up.setToolTip("Ask GitHub whether there is a newer D5 Mod Kit. Updates download only what changed; your "
                      "mods and settings stay.")
        up.clicked.connect(lambda: self.main.update_bar.check(quiet=False))
        g.addWidget(up)
        auto = QCheckBox("at start")
        auto.setToolTip("Check for a newer kit a few seconds after the kit starts (needs the internet; nothing is "
                        "downloaded unless you press Update now)")
        auto.setChecked(bool(self.ws.settings.get("check_updates", True)))
        auto.toggled.connect(lambda v: (self.ws.settings.__setitem__("check_updates", bool(v)),
                                        self.ws.save_settings()))
        g.addWidget(auto)
        outer.addLayout(g)
        self.check_label = QLabel()
        self.check_label.setWordWrap(True)
        self.check_label.setTextFormat(Qt.TextFormat.RichText)
        self.check_label.hide()
        outer.addWidget(self.check_label)

        ws.mods_changed.connect(self.refresh)
        ws.active_mod_changed.connect(lambda _: self.refresh())
        ws.file_changed.connect(lambda _: self._show_mod())
        self.refresh()

    # ------------------------------------------------------------------ state
    def on_show(self):
        from d5lib.modsys import change_token
        if getattr(self, "_shown_token", None) != (change_token(self.ws.mods.mods_dir), self.ws.game_dir):
            self.refresh()                     # ~0.2 s (every mod's files are read): only when something changed

    def refresh(self):
        from d5lib.modsys import change_token
        self._shown_token = (change_token(self.ws.mods.mods_dir), self.ws.game_dir)
        ok = self.ws.game_ok()
        self.game_label.setText(("Game: " if ok else "❌ Game not found in ") + (self.ws.game_dir or "(no folder)") +
                                ("" if ok else "  — choose the folder with disgaea5.exe"))
        self._show_checks(ok)
        self._fill_profiles()
        self._names = None
        self._fill_tree()
        cur = self._selected_mod()
        self.modlist.blockSignals(True)
        self.modlist.clear()
        order = self.ws.mods.load_order()
        mods = {m.id: m for m in self.ws.mods.all_mods()}
        ids = order + [i for i in mods if i not in order]
        for mid in ids:
            mod = mods[mid]
            active = self.ws.active_mod and self.ws.active_mod.id == mid
            missing = [r for r in mod.meta.get("requires") or [] if r not in order] if mid in order else []
            warn = "   ⚠ needs " + ", ".join(mods[r].name if r in mods else r for r in missing) if missing else ""
            it = QListWidgetItem(f"{mod.name}   v{mod.meta.get('version', '')}{'   ✎ editing' if active else ''}"
                                 f"{warn}")
            it.setData(ROLE, mid)
            it.setToolTip(mod.meta.get("description") or "")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            it.setCheckState(Qt.CheckState.Checked if mid in order else Qt.CheckState.Unchecked)
            if active:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.modlist.addItem(it)
            if cur and cur.id == mid:
                self.modlist.setCurrentItem(it)
        self.modlist.blockSignals(False)
        self._show_mod()

    # ---- profiles
    def _fill_profiles(self):
        ps = self.ws.mods.profiles
        cur = self.ws.profile
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        for p in ps.all():
            self.profile_box.addItem(p.name + ("   (separate project)" if p.isolated else "") +
                                     ("   (own saves)" if p.separate_saves else ""), p.id)
        self.profile_box.setCurrentIndex(max(0, self.profile_box.findData(cur.id)))
        self.profile_box.blockSignals(False)
        self.act_saves.setChecked(cur.separate_saves)
        inst = self.ws.installed_profile()
        n = len(self.ws.mods.load_order())
        note = f"{n} mod(s) switched on in this profile."
        if cur.isolated:
            note += "  A separate project: only its own mods (Profile › Import mods from another profile copies some in)."
        if inst and inst.id != cur.id:
            note += f"  The game has the profile <b>{inst.name}</b> installed: Install puts this one in."
        elif inst:
            note += "  This is the profile in the game."
        self.profile_note.setText(note)

    def _profile_chosen(self, index):
        pid = self.profile_box.itemData(index)
        if pid and pid != self.ws.profile.id:
            self.ws.set_profile(pid)

    def new_profile(self, copy=False):
        cur = self.ws.profile
        if copy:
            name, ok = QInputDialog.getText(self, "Copy profile",
                                            f"A copy of '{cur.name}' (the same mods switched on, in the same order)."
                                            "\n\nName of the profile:", text=f"{cur.name} copy")
            isolated = False
        else:
            dlg = NewProfileDialog(self)
            ok = dlg.exec() == QDialog.DialogCode.Accepted
            name, isolated = dlg.name.text(), dlg.isolated.isChecked()
        if not ok or not name.strip():
            return
        try:
            p = self.ws.mods.profiles.create(name.strip(), copy_from=cur if copy else None, isolated=isolated)
        except ValueError as e:
            return QMessageBox.warning(self, "Profile", str(e))
        self.ws.set_profile(p.id)

    def import_from_profile(self):
        """copies of mods of the other profiles in this one (ids that clash with this profile's mods are moved)"""
        groups = self.ws.mods.other_profiles_mods()
        if not groups:
            return QMessageBox.information(self, "Import from another profile",
                                           "This profile already sees every mod of the other profiles.")
        dlg = ImportProfileDialog(self, groups, self.ws.profile)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.chosen():
            return
        from PyQt6.QtWidgets import QApplication
        from d5lib import modshare
        done, failed = [], []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for mod in dlg.chosen():
                try:
                    res = modshare.copy_to_profile(mod, self.ws.mods.mods_dir, self.ws.fs,
                                                   os.path.join(os.path.dirname(self.ws.mods.mods_dir), "state"),
                                                   log=self.ws.log)
                    done.append(mod.name + (" (some ids moved)" if res.get("moved") else ""))
                except Exception as e:
                    failed.append(f"{mod.name}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self.ws.mods_changed.emit()
        msg = (f"Copied into '{self.ws.profile.name}':\n  " + "\n  ".join(done)) if done else "Nothing copied."
        if failed:
            msg += "\n\nNot copied:\n  " + "\n  ".join(failed)
        msg += ("\n\nThey are copies: changing them here doesn't change the other profile's."
                if done and self.ws.profile.isolated else "")
        (QMessageBox.warning if failed else QMessageBox.information)(self, "Import from another profile", msg)

    def rename_profile(self):
        cur = self.ws.profile
        name, ok = QInputDialog.getText(self, "Rename profile", "New name:", text=cur.name)
        if not ok or not name.strip() or name.strip() == cur.name:
            return
        try:
            self.ws.mods.profiles.rename(cur.id, name)
        except ValueError as e:
            return QMessageBox.warning(self, "Profile", str(e))
        self.ws.mods.set_profile(cur.id)
        self.ws.mods_changed.emit()

    def delete_profile(self):
        ps = self.ws.mods.profiles
        cur = self.ws.profile
        others = [p for p in ps.all() if p.id != cur.id]
        if not others:
            return QMessageBox.information(self, "Profile", "This is your only profile: make another one first.")
        extra = "  Its own saves are kept too." if ps.has_own_saves(cur) else ""
        what = (f"It is a separate project: its {len(self.ws.mods.all_mods())} mod(s) go with it. Both are kept in "
                if cur.isolated else "Only the profile goes (which mods it switches on); the mods stay in the kit. "
                "It is kept in ")
        if QMessageBox.question(self, "Delete profile",
                                f"Delete the profile '{cur.name}'?\n\n{what}D5ModKit/state/deleted_profiles in "
                                f"case you want it back.{extra}") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.ws.set_profile(others[0].id)      # the active profile can't go: move to another one first
            ps.delete(cur.id, live_owner=self.ws.saves().live_owner())
        except ValueError as e:
            self.ws.set_profile(cur.id)
            return QMessageBox.warning(self, "Profile", str(e))
        self.ws.mods_changed.emit()

    def toggle_profile_saves(self, on):
        ps = self.ws.mods.profiles
        cur = self.ws.profile
        self.act_saves.setChecked(cur.separate_saves)
        if bool(on) == cur.separate_saves:
            return
        if self.ws.is_game_running():
            return QMessageBox.information(self, "Close the game first",
                                           "Disgaea 5 is running. Close it before changing where its saves go.")
        inst = self.ws.installed_profile()
        installed = inst.id if inst else None
        if not on:
            if QMessageBox.question(self, "Shared saves",
                                    f"Let '{cur.name}' use the shared saves again?\n\nIts own saves stay in its "
                                    "folder (switch this on again later to get them back). The shared saves go into "
                                    "the game the next time this profile is installed.") \
                    != QMessageBox.StandardButton.Yes:
                return
            ps.set_separate_saves(cur.id, False, self.ws.saves(), installed=installed, log=self.ws.log)
        else:
            box = QMessageBox(self)
            box.setWindowTitle("Separate saves")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(f"Give '{cur.name}' its own saves?")
            box.setInformativeText(
                "A modpack's saves can depend on its mods (a unit in a class or outfit only this profile has). With "
                "its own saves, this profile's saves go into the game when it is installed, and the saves of the "
                "other profiles are put aside meanwhile (nothing is deleted; every switch also keeps a copy in "
                "D5ModKit/state/save_backups).\n\nTip: Steam Cloud keeps whatever saves are in the game; launch "
                "through the kit (Play) so the right saves are in place.\n\nStart this profile with:")
            b_copy = box.addButton("A copy of my current saves", QMessageBox.ButtonRole.AcceptRole)
            b_keep = box.addButton("Its earlier saves", QMessageBox.ButtonRole.AcceptRole) \
                if ps.has_own_saves(cur) else None
            b_new = box.addButton("No saves (a new game)", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            c = box.clickedButton()
            start = "copy" if c is b_copy else "keep" if (b_keep is not None and c is b_keep) else \
                "empty" if c is b_new else None
            if not start:
                return
            try:
                ps.set_separate_saves(cur.id, True, self.ws.saves(), start=start, installed=installed,
                                      log=self.ws.log)
            except OSError as e:
                return QMessageBox.critical(self, "Separate saves", f"The saves could not be copied: {e}")
        self.ws.mods.set_profile(cur.id)
        self.ws.mods_changed.emit()

    # ---- the category tree
    def _skill_names(self):
        if getattr(self, "_sknames", None) is None:
            from d5lib.dbpatch import DB_ARCHIVE
            self._sknames = modinfo.skill_names(lambda: self.ws.fs.read(f"{DB_ARCHIVE}/magic.dat"))
        return self._sknames

    def _class_names(self):
        if getattr(self, "_names", None) is None:
            from d5lib.dbpatch import DB_ARCHIVE
            try:
                self._names = modinfo.class_names(lambda: self.ws.fs.read(f"{DB_ARCHIVE}/char.dat"),
                                                  self.ws.mods.all_mods())
            except Exception:
                self._names = modinfo.Names()
        return self._names

    def _fill_tree(self):
        if not hasattr(self, "modtree"):
            return
        cur = self._selected_mod()
        names = self._class_names()
        order = self.ws.mods.load_order()
        mods = {m.id: m for m in self.ws.mods.all_mods()}
        packs = modinfo.Packs(self.ws.mods.mods_dir)
        q = self.search.text().strip().lower()
        opened = set(self.ws.settings.get("home_open_groups") or ["system", "characters", "classes", "gameplay",
                                                                   "skills", "story", "art", "data", "other"])
        self.modtree.blockSignals(True)
        self.modtree.clear()
        by_cat = {}
        info = {}
        for mid, mod in mods.items():
            cat = modinfo.category(mod)
            info[mid] = (cat, modinfo.group_of(mod, names), modinfo.one_line(mod, names))
            by_cat.setdefault(cat, []).append(mid)

        def matches(mid):
            if not q:
                return True
            mod = mods[mid]
            text = " ".join([mod.name, mid, mod.meta.get("description") or "", info[mid][1] or "", info[mid][2] or ""])
            if q in text.lower():
                return True
            return any(q in n.lower() for _, _, n in modinfo.outfits_of(mod))

        def mod_item(parent, mid):
            mod = mods[mid]
            active = self.ws.active_mod and self.ws.active_mod.id == mid
            missing = [r for r in mod.meta.get("requires") or [] if r not in order] if mid in order else []
            label = mod.name
            grp = info[mid][1]
            if grp and info[mid][0] == "outfits" and grp.lower() not in label.lower():
                label = f"{grp} — {label}"
            it = QTreeWidgetItem(parent, [label + ("   ✎" if active else ""),
                                          mod_subtitle(info[mid][2], [mods[r].name if r in mods else r
                                                                      for r in missing])])
            it.setData(0, ROLE, mid)
            it.setData(0, KIND, "mod")
            tip = (mod.meta.get("description") or "") + (f"\nby {mod.meta.get('author')}" if mod.meta.get("author") else "")
            it.setToolTip(0, tip)
            it.setToolTip(1, tip)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if mid in order else Qt.CheckState.Unchecked)
            if active:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            if cur and cur.id == mid:
                self.modtree.setCurrentItem(it)
            return it

        def group_state(item):
            n = item.childCount()
            on = sum(1 for i in range(n) if item.child(i).checkState(0) == Qt.CheckState.Checked)
            part = any(item.child(i).checkState(0) == Qt.CheckState.PartiallyChecked for i in range(n))
            item.setCheckState(0, Qt.CheckState.Checked if on == n and n else
                               Qt.CheckState.PartiallyChecked if on or part else Qt.CheckState.Unchecked)

        total = enabled = 0
        for cat, label in modinfo.CATEGORIES:
            ids = [m for m in by_cat.get(cat, []) if matches(m)]
            if not ids:
                continue
            ids.sort(key=lambda m: ((info[m][1] or "").lower(), mods[m].name.lower()))
            on = sum(1 for m in ids if m in order)
            total += len(ids)
            enabled += on
            top = QTreeWidgetItem(self.modtree, [f"{label}", f"{len(ids)} mod{'s' if len(ids) != 1 else ''} · {on} on"])
            top.setData(0, KIND, "group")
            top.setData(0, ROLE, cat)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            done = set()
            for pack in packs.packs:                         # packs whose members are in this category
                mem = [m for m in pack.get("members", []) if m in ids]
                if not mem:
                    continue
                pk = QTreeWidgetItem(top, [f"📦 {pack['name']}", pack.get("description") or
                                           f"pack of {len(mem)} mod{'s' if len(mem) != 1 else ''}"])
                pk.setData(0, KIND, "pack")
                pk.setData(0, ROLE, pack["id"])
                pk.setFlags(pk.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                for mid in mem:
                    mod_item(pk, mid)
                    done.add(mid)
                group_state(pk)
                pk.setExpanded(bool(q) or f"pack:{pack['id']}" in opened)
            for mid in ids:
                if mid not in done:
                    mod_item(top, mid)
            group_state(top)
            top.setExpanded(bool(q) or cat in opened)
        self.modtree.blockSignals(False)
        n_all = len(mods)
        self.count_label.setText(f"{len(order)} of {n_all} mods on" + (f" · {total} found" if q else ""))

    def _remember_open(self, item):
        key = item.data(0, ROLE)
        if item.data(0, KIND) == "pack":
            key = f"pack:{key}"
        elif item.data(0, KIND) != "group":
            return
        if self.search.text().strip():
            return
        opened = set(self.ws.settings.get("home_open_groups") or ["system", "characters", "classes", "gameplay",
                                                                   "skills", "story", "art", "data", "other"])
        (opened.add if item.isExpanded() else opened.discard)(key)
        self.ws.settings["home_open_groups"] = sorted(opened)
        self.ws.save_settings()

    def _tree_checked(self, item, col):
        """a box was ticked.  A group's box changes each of its mods one by one: the load order is written once,
        after Qt has finished (rebuilding the tree in between would delete the items it is still changing)"""
        if col != 0 or getattr(self, "_tick_pending", False):
            return
        self._tick_pending = True
        QTimer.singleShot(0, self._apply_ticks)

    def _apply_ticks(self):
        self._tick_pending = False
        order = self.ws.mods.load_order()
        want = {}

        def walk(it):
            for i in range(it.childCount()):
                c = it.child(i)
                if c.data(0, KIND) == "mod":
                    want[c.data(0, ROLE)] = c.checkState(0) == Qt.CheckState.Checked
                else:
                    walk(c)
        walk(self.modtree.invisibleRootItem())
        new = [m for m in order if want.get(m, True)]
        mods = {m.id: m for m in self.ws.mods.all_mods()}
        for mid, on in want.items():
            if on and mid not in new:
                for r in mods[mid].meta.get("requires") or []:        # what it needs goes first
                    if r in mods and r not in new:
                        new.append(r)
                new.append(mid)
        if new != order:
            self.ws.mods.save_load_order(new)
            self.ws.mods_changed.emit()
            self._quest_warning(order, new)

    def _quest_warning(self, before, after):
        """a mod switched off that a quest's stage lives in: say so now (the quest could never be finished)"""
        off = [m for m in before if m not in after]
        if not off:
            return
        try:
            from d5lib import questcheck
            mods = {m.id: m for m in self.ws.mods.all_mods()}
            probs = questcheck.problems(self.ws.fs, [mods[i] for i in after if i in mods], list(mods.values()))
            probs = [p for p in probs if p["mod"] is not None and p["mod"].id in off]
        except Exception:
            return
        if not probs:
            return
        from PyQt6.QtWidgets import QMessageBox
        text = "<br><br>".join(p["text"] for p in probs)
        box = QMessageBox(self)
        box.setWindowTitle("A quest needs that mod")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(text + "<br><br>Switch it back on, or change what the quest asks for (Characters → the "
                           "character → <i>How to get this character</i>).")
        on = box.addButton("Switch it back on", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Leave it off", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is on:
            need = [p["mod"].id for p in probs]
            self.ws.mods.save_load_order(after + [m for m in before if m in need and m not in after])
            self.ws.mods_changed.emit()

    def _tree_double(self, item, col):
        if item.data(0, KIND) == "mod":
            self.activate_mod()

    def _selected_ids(self):
        if self.mod_views.currentIndex() == 1:
            return [it.data(ROLE) for it in self.modlist.selectedItems()]
        out = []
        for it in self.modtree.selectedItems():
            if it.data(0, KIND) == "mod":
                out.append(it.data(0, ROLE))
            elif it.data(0, KIND) == "pack":
                out += [it.child(i).data(0, ROLE) for i in range(it.childCount())]
        return list(dict.fromkeys(out))

    def make_pack(self):
        ids = self._selected_ids()
        if len(ids) < 2:
            QMessageBox.information(self, "Group into a pack", "Select two or more mods (Ctrl+click), then group "
                                    "them. A pack is switched on and off as one; the mods themselves don't change.")
            return
        name, ok = QInputDialog.getText(self, "Group into a pack", f"Name of the pack ({len(ids)} mods):")
        if not ok or not name.strip():
            return
        pack = modinfo.Packs(self.ws.mods.mods_dir).create(name.strip(), ids)
        opened = set(self.ws.settings.get("home_open_groups") or [])
        opened.add(f"pack:{pack['id']}")
        self.ws.settings["home_open_groups"] = sorted(opened)
        self.ws.save_settings()
        self.ws.log(f"Pack '{name.strip()}': {', '.join(ids)}")
        self.refresh()

    def ungroup_pack(self, pack_id):
        modinfo.Packs(self.ws.mods.mods_dir).remove(pack_id)
        self.refresh()

    def leave_pack(self, mod_id):
        modinfo.Packs(self.ws.mods.mods_dir).remove_member(mod_id)
        self.refresh()

    def _save_order(self, *a):
        order = []
        for i in range(self.modlist.count()):
            it = self.modlist.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                order.append(it.data(ROLE))
        self.ws.mods.save_load_order(order)
        self.ws.mods_changed.emit()

    def _selected_mod(self):
        if not hasattr(self, "modlist"):
            return None
        if hasattr(self, "mod_views") and self.mod_views.currentIndex() == 0:
            it = self.modtree.currentItem()
            if it is None or it.data(0, KIND) != "mod":
                return None
            return self.ws.mods.get(it.data(0, ROLE))
        it = self.modlist.currentItem()
        return self.ws.mods.get(it.data(ROLE)) if it else None

    def _show_mod(self, *a):
        mod = self._selected_mod() or self.ws.active_mod
        self.mod_files.clear()
        if not mod:
            self.mod_title.setText("No mod selected")
            self.mod_info.setText("Create a mod with <b>＋ New mod</b>, or just start editing — the kit asks for a "
                                  "name the first time you save.")
            return
        meta = mod.meta
        mods = {m.id: m for m in self.ws.mods.all_mods()}
        order = self.ws.mods.load_order()
        self.mod_title.setText(meta.get("name") or mod.id)
        state = "enabled — installed with the others" if mod.id in order else "disabled — not installed"
        editing = " · <b>new edits go here</b>" if self.ws.active_mod and self.ws.active_mod.id == mod.id else ""
        req = meta.get("requires") or []
        req_txt = ("<br><span style='color:#c9a0ff'>Requires: " + ", ".join(
            (mods[r].name if r in mods else r) + ("" if r in order else " (not enabled!)")
            for r in req) + "</span>") if req else ""
        import html as _h
        based = meta.get("based_on") or []
        lineage = ("<br><span style='color:#8a90b8'>Based on " + " › ".join(
            _h.escape(f"{b.get('name', '?')} v{b.get('version', '?')}" + (f" by {b['author']}" if b.get("author") else ""))
            for b in based) + "</span>") if based else ""
        moved = meta.get("local_ids") or {}
        moved_txt = ("<br><span style='color:#8a90b8'>Ids moved on this PC (kept for its updates): " + ", ".join(
            f"{k} {len(v)}" for k, v in moved.items()) + "</span>") if moved else ""
        self.mod_info.setText(f"<span style='color:#8a90b8'>by {meta.get('author') or '—'} · v{meta.get('version') or '?'}"
                              f" · {state}{editing}</span><br>{meta.get('description') or ''}{req_txt}{lineage}"
                              f"{moved_txt}")
        import html as _html
        lines = modinfo.summary(mod, self._class_names(), self.ws.mods.all_mods(), self._skill_names())
        cat = modinfo.CATEGORY_LABELS.get(modinfo.category(mod), "")
        pack = modinfo.Packs(self.ws.mods.mods_dir).pack_of(mod.id)
        head = f"<b>What it adds</b> <span style='color:#8a90b8'>· {cat.split('  ', 1)[-1]}" + \
            (f" · in the pack {_html.escape(pack['name'])}" if pack else "") + "</span>"
        self.mod_summary.setText(head + "<br>" + "<br>".join(_html.escape(x) for x in lines))
        for f in mod.list_files():
            size = os.path.getsize(mod.file_path(f))
            it = QListWidgetItem(f"📄 {f}   ({human_size(size)})")
            it.setData(ROLE, ("file", f))
            self.mod_files.addItem(it)
        if os.path.isdir(mod.patches_dir):
            for h in sorted(os.listdir(mod.patches_dir)):
                for p in mod.list_patches(h):
                    it = QListWidgetItem(f"🧩 {h}: {p}")
                    it.setData(ROLE, ("patch", h, p))
                    self.mod_files.addItem(it)
        if not self.mod_files.count():
            self.mod_files.addItem("(no changes yet)")

    def _menu(self, pos):
        tree = self.mod_views.currentIndex() == 0
        view = self.modtree if tree else self.modlist
        it = view.itemAt(pos)
        if not it:
            return
        m = QMenu(self)
        kind = it.data(0, KIND) if tree else "mod"
        if kind == "pack":
            pid = it.data(0, ROLE)
            m.addAction("Ungroup (the mods stay as they are)", lambda: self.ungroup_pack(pid))
            m.exec(view.mapToGlobal(pos))
            return
        if kind == "group":
            return
        if len(self._selected_ids()) > 1:
            m.addAction("📦 Group into a pack…", self.make_pack)
            m.addSeparator()
        m.addAction("✎ Save my edits here", self.activate_mod)
        m.addAction("Edit details…", self.edit_mod)
        m.addAction("Open folder", self.open_mod_folder)
        m.addAction("Share (export as .zip)…", self.export_mod)
        m.addAction("Make my own version…", self.derive_mod)
        mid = it.data(0, ROLE) if tree else it.data(ROLE)
        if modinfo.Packs(self.ws.mods.mods_dir).pack_of(mid):
            m.addAction("Take out of its pack", lambda: self.leave_pack(mid))
        m.addSeparator()
        m.addAction("Delete mod…", self.delete_mod)
        m.exec(view.mapToGlobal(pos))

    def _show_checks(self, ok):
        """problems with this game that would stop or limit an install (d5lib.gamecheck)"""
        import html
        from d5lib import gamecheck
        try:
            found = gamecheck.check(self.ws.installer) if ok else []
        except Exception as e:
            found = [("warning", f"The game could not be checked: {e}")]
        try:
            need = gamecheck.save_needs_mods(self.ws.game_dir, self.ws.mods.all_mods(), set(self.ws.mods.load_order()))                 if ok else []
        except Exception:
            need = []
        if need:
            what = ", ".join((f"{n} " if n else f"class {c} ") + (f"(mod '{m.name}')" if m else "(no mod of this kit)")
                             for c, n, m in need)
            found.append(("warning", "Your save has units from mods that are switched off in this profile: " + what +
                          ". The game crashes entering a battle with that save: switch those mods on (or pick a "
                          "profile that has them) and install."))
        try:
            slow = gamecheck.slow_session(self.ws.game_dir) if ok else None
        except Exception:
            slow = None
        if slow:
            grow = (f" Its memory went from {slow['mem'][0]:.0f} to {slow['mem'][1]:.0f} MB." if slow["mem"] and
                    slow["mem"][1] - slow["mem"][0] > 300 else "")
            found.append(("warning", f"The game ran slowly in your last session ({slow['stretches']} stretch"
                          f"{'es' if slow['stretches'] != 1 else ''} of 10 seconds, frames up to {slow['worst']} ms)."
                          f"{grow} 'Copy lag report' copies where its time went: send it with your report."))
        self._lag = slow
        if not slow and hasattr(self, "lag_btn"):
            self.lag_btn.hide()
        try:
            from d5lib import questcheck
            for t in questcheck.problem_texts(self.ws.fs, self.ws.mods.enabled_mods(), self.ws.mods.all_mods()) \
                    if ok else []:
                found.append(("warning", t + " Switch that mod on, or change what the quest asks for (Characters, "
                                         "'How to get this character')."))
        except Exception as e:
            found.append(("warning", f"(quests not checked: {e})"))
        if not found:
            self.check_label.hide()
            return
        rows = [("⛔ " if lvl == "error" else "⚠ ") + html.escape(t) for lvl, t in found]
        color = "#ff6b6b" if any(l == "error" for l, _ in found) else "#f0b35a"
        self.check_label.setText(f"<div style='color:{color}'>" + "<br>".join(rows) + "</div>")
        self.check_label.show()
        unknown = ok and gamecheck.unknown_exe(self.ws.installer)
        if unknown and not hasattr(self, "report_btn"):
            from PyQt6.QtWidgets import QPushButton
            self.report_btn = QPushButton("📋  Copy compatibility report")
            self.report_btn.setToolTip("Which build of the game this is and how much of it the kit can find "
                                       "(nothing of the game itself). Paste it into a GitHub issue or send it to "
                                       "the kit's author.")
            self.report_btn.clicked.connect(self._copy_report)
            lay = self.check_label.parentWidget().layout()
            lay.insertWidget(lay.indexOf(self.check_label) + 1, self.report_btn)
        if hasattr(self, "report_btn"):
            self.report_btn.setVisible(bool(unknown))
        if self._lag and not hasattr(self, "lag_btn"):
            from PyQt6.QtWidgets import QPushButton
            self.lag_btn = QPushButton("📋  Copy lag report")
            self.lag_btn.setToolTip("The lines of the game's d5auto.log about slow frames: how slow, the memory, and "
                                    "where the game spent its time (nothing personal). Send them with your report.")
            self.lag_btn.clicked.connect(self._copy_lag)
            lay = self.check_label.parentWidget().layout()
            lay.insertWidget(lay.indexOf(self.check_label) + 1, self.lag_btn)
        if hasattr(self, "lag_btn"):
            self.lag_btn.setVisible(bool(self._lag))

    def _copy_lag(self):
        from PyQt6.QtWidgets import QApplication
        from d5lib import version
        text = f"D5 Mod Kit {version.VERSION} lag report\n" + (getattr(self, "_lag", None) or {}).get("report", "")
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Lag report copied",
                                "The report is on the clipboard. Paste it into an issue at "
                                "github.com/eraser4521/D5ModKit/issues (or send it to the kit's author).")

    def _copy_report(self):
        from PyQt6.QtWidgets import QApplication
        from d5lib import exemap, gamecheck
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = "D5 Mod Kit compatibility report\n" + exemap.report(gamecheck.original_exe(self.ws.installer))
        except Exception as e:
            text = f"D5 Mod Kit compatibility report failed: {e}"
        finally:
            QApplication.restoreOverrideCursor()
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Compatibility report copied",
                                "The report is on the clipboard. Paste it into a new issue at "
                                "github.com/eraser4521/D5ModKit/issues (or send it to the kit's author).\n\n"
                                + text[:1200])

    # ------------------------------------------------------------------ actions
    def _lang_changed(self, lang):
        self.ws.settings["language"] = lang
        self.ws.save_settings()

    def change_game_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Disgaea 5 Complete folder", self.ws.game_dir)
        if d:
            self.ws.set_game_dir(d)
            self.refresh()

    def new_mod(self):
        dlg = ModDialog({"name": "My Mod"}, self)
        if dlg.exec():
            v = dlg.values()
            mod = self.ws.mods.create(v["name"] or "My Mod", v["author"], v["description"])
            mod.meta["version"] = v["version"]
            mod.save_meta()
            self.ws.set_active_mod(mod)
            self.ws.mods_changed.emit()
            self.ws.log(f"Created mod '{mod.name}' — your edits are now saved into it.")

    def edit_mod(self):
        mod = self._selected_mod()
        if not mod:
            return
        dlg = ModDialog(mod.meta, self)
        if dlg.exec():
            mod.meta.update(dlg.values())
            mod.save_meta()
            self.ws.mods_changed.emit()

    def activate_mod(self):
        mod = self._selected_mod()
        if mod:
            self.ws.set_active_mod(mod)
            if mod.id not in self.ws.mods.load_order():
                if QMessageBox.question(self, "Enable the mod?",
                                        f"'{mod.name}' is disabled, so its changes are not installed. Enable it?") \
                        == QMessageBox.StandardButton.Yes:
                    self.ws.mods.set_enabled(mod.id, True)
                    self.ws.mods_changed.emit()
            self.ws.log(f"Edits are now saved into '{mod.name}'.")

    def open_mod_folder(self):
        mod = self._selected_mod()
        if mod:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(mod.folder)))

    def export_mod(self, mod=None):
        """share the mod: a zip with its identity (uid) and version, so whoever installs a later version gets an
        update instead of a second copy (d5lib.modshare)"""
        from d5lib import modshare
        from ..common import error_box
        mod = mod or self._selected_mod()
        if not mod:
            return
        ver, ok = QInputDialog.getText(self, "Share mod", f"Version of '{mod.name}' you are sharing (raise it for an "
                                       "update, so players get it as one):", text=mod.meta.get("version") or "1.0")
        if not ok:
            return
        author = mod.meta.get("author") or ""
        if not author:
            author, ok = QInputDialog.getText(self, "Share mod", "Author (your name, shown to players):")
            if not ok:
                return
        path, _ = QFileDialog.getSaveFileName(self, "Share mod", f"{mod.id}_v{ver.strip() or '1.0'}.zip",
                                              "Zip (*.zip)")
        if not path:
            return
        try:
            modshare.export_package(mod, path, version=ver.strip() or None, author=author.strip() or None)
        except Exception as e:
            return error_box(self, "Could not export", e)
        self.ws.log(f"Shared {mod.name} v{mod.meta.get('version')} -> {path}")
        self.refresh()

    def import_mod(self):
        """install a shared mod: an update of one that's here (same identity) replaces it and keeps its ids on this
        PC; a new one is added; ids that clash with another mod here are moved (d5lib.modshare)"""
        from d5lib import modshare
        from ..common import error_box
        path, _ = QFileDialog.getOpenFileName(self, "Import mod", "", "Zip (*.zip)")
        if not path:
            return
        try:
            top, meta = modshare.read_package(path)
        except Exception as e:
            return QMessageBox.warning(self, "Import", f"Not a mod package: {e}")
        mine = next((m for m in self.ws.mods.all_mods() if meta.get("uid") and m.meta.get("uid") == meta.get("uid")),
                    None)
        if mine is not None:
            q = (f"'{mine.name}' v{mine.meta.get('version', '?')} is installed: update it to "
                 f"v{meta.get('version', '?')}?\n\nThe current version is kept as a backup (D5ModKit/state/"
                 "mod_backups). The ids it uses on this PC stay the same, so your saves keep working.")
            if QMessageBox.question(self, "Update mod", q) != QMessageBox.StandardButton.Yes:
                return
        lines = []
        from PyQt6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = modshare.import_package(path, self.ws.mods.mods_dir, self.ws.fs,
                                          os.path.join(os.path.dirname(self.ws.mods.mods_dir), "state"),
                                          log=lines.append, exe_consent=self._ask_exe_consent)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            return error_box(self, "Could not import", e)
        QApplication.restoreOverrideCursor()
        self.ws.mods_changed.emit()
        for line in lines:
            self.ws.log(line)
        moved = res["moved"]
        msg = (f"{'Updated' if res['update'] else 'Imported'} '{meta.get('name', res['mod_id'])}' "
               f"v{meta.get('version', '?')}" + (f" by {meta['author']}" if meta.get("author") else "") + ".")
        if moved:
            msg += ("\n\nSome of its ids were already used by your other mods, so they were moved here (the mod "
                    "remembers this for its updates): " + "; ".join(
                        f"{k}: " + ", ".join(f"{a}→{b}" for a, b in v.items()) for k, v in moved.items()))
        if res.get("backup"):
            msg += f"\n\nThe previous version is kept in {res['backup']}."
        if res.get("exe"):
            msg += ("\n\n⚠ It changes the game's program" + (
                ", and you approved it." if res.get("enabled") else " and is OFF: you did not approve it."))
        elif not res.get("enabled", True):
            msg += "\n\nIt is switched off in this profile."
        msg += "\n\nInstall to put it into the game."
        QMessageBox.information(self, "Mod imported", msg)

    def _ask_exe_consent(self, line):
        """True when the player approves a package's game-program patches (default answer: No)"""
        from PyQt6.QtWidgets import QApplication
        QApplication.restoreOverrideCursor()
        try:
            q = (f"{line}\n\nThis mod carries machine code that is written into the game's program and runs inside "
                 "the game. Only approve it if you trust its author. If you say No it is imported but stays off.\n\n"
                 "Approve and turn it on?")
            return QMessageBox.question(self, "This mod changes the game's program", q,
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        finally:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def export_all_by_game(self):
        """mass export: one zip per mod in a folder per game, with manifests, importable by other kits
        (d5lib.modbulk; the mods themselves are not changed)"""
        from d5lib import modbulk
        from ..common import error_box
        from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox
        mods = self.ws.mods.all_mods()
        pg = modbulk.load_pack_games(self.ws.mods.mods_dir)
        count = {}
        for m in mods:
            g = modbulk.game_of(m, pg)
            count[g] = count.get(g, 0) + 1
        dlg = QDialog(self)
        dlg.setWindowTitle("Share all by game")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Export every mod of the checked games as its own zip, in one folder per game.\n"
                             "Your mods are not changed."))
        boxes = {}
        for g in modbulk.GAMES:
            if count.get(g):
                boxes[g] = QCheckBox(f"{g}  ({count[g]} mods)")
                boxes[g].setChecked(g != "DRPG")            # DRPG is gigabytes
                lay.addWidget(boxes[g])
        enabled_only = QCheckBox("Only mods that are switched on")
        lay.addWidget(enabled_only)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        games = [g for g, b in boxes.items() if b.isChecked()]
        if not games:
            return
        author = next((m.meta.get("author") for m in mods if m.meta.get("author")), "")
        author, ok = QInputDialog.getText(self, "Share all by game", "Author (your name, shown to players; may be "
                                          "empty to keep each mod's own):", text=author or "")
        if not ok:
            return
        out = QFileDialog.getExistingDirectory(self, "Export into this folder")
        if not out:
            return
        lines = []

        def log(line):
            lines.append(line)
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rep = modbulk.export_all(mods, out, games=games, only_enabled=enabled_only.isChecked(),
                                     author=author.strip() or None, log=log, pack_games=pg,
                                     enabled_ids={m.id for m in self.ws.mods.enabled_mods()})
        except Exception as e:
            QApplication.restoreOverrideCursor()
            return error_box(self, "Could not export", e)
        QApplication.restoreOverrideCursor()
        for line in lines:
            self.ws.log(line)
        msg = f"Exported {len(rep['exported'])} mods to {out}:\n" + "\n".join(
            f"  {g}: {n}" for g, n in sorted(rep["games"].items()))
        if rep["skipped"]:
            msg += f"\n\nSkipped {len(rep['skipped'])}:\n" + "\n".join(
                f"  {s['id']}: {s['reason']}" for s in rep["skipped"][:15])
        msg += "\n\nGive the folder to another kit user: Home › More › Import folder…"
        self.ws.log(msg.split("\n")[0])
        QMessageBox.information(self, "Share all by game", msg)

    def import_folder(self):
        """mass import: every package zip under a folder (all game subfolders), mods others need first; clashing ids
        are moved and 'requires' re-pointed (d5lib.modbulk)"""
        from d5lib import modbulk
        from ..common import error_box
        from PyQt6.QtWidgets import QApplication
        folder = QFileDialog.getExistingDirectory(self, "Import every mod package in this folder")
        if not folder:
            return
        n = len(modbulk._scan_zips(folder))
        if not n:
            return QMessageBox.information(self, "Import folder", "No .zip packages in that folder.")
        if QMessageBox.question(self, "Import folder", f"Import {n} package(s)? Mods you already have (same identity) "
                                "are updated, the old versions are kept as backups. Clashing ids are moved, never "
                                "your other mods'.") != QMessageBox.StandardButton.Yes:
            return
        lines = []

        def log(line):
            lines.append(line)
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            s = modbulk.import_folder(folder, self.ws.mods.mods_dir, self.ws.fs,
                                      os.path.join(os.path.dirname(self.ws.mods.mods_dir), "state"), log=log)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            return error_box(self, "Could not import", e)
        QApplication.restoreOverrideCursor()
        self.ws.mods_changed.emit()
        for line in lines:
            self.ws.log(line)
        msg = (f"Imported {len(s['imported'])}, updated {len(s['updated'])}, failed {len(s['failed'])}.")
        if s["moved"]:
            msg += f"\n\n{len(s['moved'])} mod(s) had ids moved because your mods already use them."
        if s["repointed"]:
            msg += "\n\nRequirements re-pointed: " + "; ".join(
                f"{m}: " + ", ".join(f"{a} → {b}" for a, b in d.items()) for m, d in s["repointed"].items())
        if s["missing_requires"]:
            msg += "\n\nRequired mods that are not installed: " + "; ".join(
                f"{m} needs {', '.join(r)}" for m, r in s["missing_requires"].items())
        if s["failed"]:
            msg += "\n\nFailed:\n" + "\n".join(
                f"  {os.path.basename(f['file'])}: {f['reason']}" for f in s["failed"][:15])
        msg += "\n\nInstall to put the mods into the game."
        self.ws.log(msg.split("\n")[0])
        QMessageBox.information(self, "Import folder", msg)

    def derive_mod(self):
        """iterate on someone's mod without changing it: a copy with its own identity that remembers its origin"""
        from d5lib import modshare
        mod = self._selected_mod()
        if not mod:
            return
        name, ok = QInputDialog.getText(self, "Make my own version", f"Name of your version of '{mod.name}':",
                                        text=f"{mod.name} (my version)")
        if not ok or not name.strip():
            return
        new = modshare.derive(mod, name.strip(), self.ws.settings.get("author", ""))
        on = mod.id in self.ws.mods.load_order()
        if on:                                     # the copy takes the original's place in the game
            self.ws.mods.save_load_order([new.id if m == mod.id else m for m in self.ws.mods.load_order()])
        self.ws.set_active_mod(new)
        self.ws.mods_changed.emit()
        self.ws.log(f"'{name.strip()}' made from '{mod.name}'" + (" (it takes its place in the game; the original "
                                                                     "is kept, switched off)" if on else "") +
                    ". Your edits are saved into it.")

    def check_saves(self):
        from .. import savecleanup
        savecleanup.check_saves(self, self.ws)

    def delete_mod(self):
        mod = self._selected_mod()
        if not mod:
            return
        if QMessageBox.question(self, "Delete mod", f"Permanently delete the mod '{mod.name}' and all its files?") \
                != QMessageBox.StandardButton.Yes:
            return
        from .. import savecleanup
        try:
            held = savecleanup.mod_info(self.ws, mod)      # read before its files go: what saves can hold of it
        except Exception as e:
            held = None
            self.ws.log(f"(saves not checked for '{mod.name}': {e})")
        if self.ws.active_mod and self.ws.active_mod.id == mod.id:
            self.ws.set_active_mod(None)
        self.ws.mods.delete(mod.id)
        modinfo.Packs(self.ws.mods.mods_dir).remove_member(mod.id)
        self.ws.mods_changed.emit()
        if held:
            savecleanup.offer(self, self.ws, f"the mod '{mod.name}'", held["classes"], held["outfits"], held["quests"],
                              guard=held.get("guard"))

    def remove_change(self):
        it = self.mod_files.currentItem()
        mod = self._selected_mod() or self.ws.active_mod
        if not it or not mod or not it.data(ROLE):
            return
        d = it.data(ROLE)
        if QMessageBox.question(self, "Remove change", f"Remove '{d[-1]}' from '{mod.name}'?") \
                != QMessageBox.StandardButton.Yes:
            return
        if d[0] == "file":
            mod.remove_file(d[1])
            self.ws.file_changed.emit(d[1])
        else:
            os.remove(mod.patch_path(d[1], d[2]))
            self.ws.file_changed.emit(d[1])
        self._show_mod()
