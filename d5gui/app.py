"""D5 Mod Kit — main window."""
import gc
import os
import sys
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
                             QLabel, QStackedWidget, QButtonGroup, QComboBox, QPlainTextEdit, QSplitter,
                             QMessageBox, QToolButton)

from .theme import QSS
from .workspace import Workspace
from .status import GameStatus, StatusPanel

PAGES = [
    # (section, key, label, module, class)
    ("", "home", "🏠  Home", "home", "HomePage"),
    ("CONTENT", "characters", "🧙  Characters && Classes", "characters", "CharactersPage"),
    ("CONTENT", "outfits", "👗  Outfits", "outfits", "OutfitsPage"),
    ("CONTENT", "database", "📊  Database Editor", "database", "DatabasePage"),
    ("CONTENT", "skills", "✨  Skills && Animations", "skills", "SkillsPage"),
    ("CONTENT", "dialogue", "💬  Dialogue && Text", "dialogue", "DialoguePage"),
    ("CONTENT", "stages", "🗺  Stages && Maps", "stages", "StagesPage"),
    ("ART", "sprites", "🎨  Sprites && Colors", "sprites", "SpritesPage"),
    ("ART", "grips", "🗡  Weapon Grips", "grips", "WeaponGripsPage"),
    ("ART", "textures", "🖼  Textures && UI", "textures", "TexturesPage"),
    ("AUDIO", "music", "🎵  Music && Sound", "music", "MusicPage"),
    ("GAMEPLAY", "autobattle", "⚔  Item World Auto-Battle", "autobattle", "AutoBattlePage"),
    ("ADVANCED", "scripts", "🧩  Event Scripts", "scripts", "ScriptsPage"),
    ("ADVANCED", "explorer", "📦  Archive Explorer", "explorer", "ExplorerPage"),
]
# a page whose module isn't in this copy of the kit is left out (the shareable kit has no auto-battle page)
PAGES = [p for p in PAGES if os.path.exists(os.path.join(os.path.dirname(__file__), "pages", p[3] + ".py"))]
LABELS = {key: label.split("  ", 1)[-1].replace("&&", "&") for _, key, label, _, _ in PAGES}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from .common import install_wheel_guard
        install_wheel_guard()               # before any widget: values change by wheel only once clicked
        from d5lib.version import VERSION
        self.setWindowTitle(f"D5 Mod Kit {VERSION} — Disgaea 5 Complete Modding Studio")
        self.resize(1500, 920)
        self.ws = Workspace()
        self.pages = {}

        root = QWidget()
        self.setCentralWidget(root)
        # An OpenGL view (the skill editor's preview) added to a window already on screen makes Qt destroy and
        # create the whole window again as an OpenGL one: the kit flashed and jumped the first time Skills &
        # Animations opened.  A hidden OpenGL widget from the start makes the window OpenGL-capable before it shows.
        try:
            from PyQt6.QtOpenGLWidgets import QOpenGLWidget
            self._gl_window = QOpenGLWidget(root)
            self._gl_window.hide()
        except Exception:
            pass
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---------------- sidebar
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(8, 8, 8, 10)
        sv.setSpacing(1)
        brand = QLabel("D5 MOD KIT")
        brand.setObjectName("brand")
        sub = QLabel("DISGAEA 5 MODDING STUDIO")
        sub.setObjectName("brandSub")
        sv.addWidget(brand)
        sv.addWidget(sub)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.stack = QStackedWidget()
        last_section = None
        for section, key, label, mod, cls in PAGES:
            if section != last_section and section:
                sl = QLabel(section)
                sl.setObjectName("sectionLabel")
                sv.addWidget(sl)
            last_section = section
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.show_page(k))
            self.group.addButton(b)
            sv.addWidget(b)
            self.pages[key] = {"button": b, "module": mod, "class": cls, "widget": None, "index": None}
        sv.addStretch(1)
        guide = QPushButton("📖  Guide && Tutorials")
        guide.setObjectName("guideButton")
        guide.setToolTip("Open the illustrated guide: setup, every page of the kit, step-by-step tutorials")
        guide.clicked.connect(open_guide)
        sv.addWidget(guide)
        sv.addSpacing(6)

        # where edits go
        ml = QLabel("SAVING EDITS TO")
        ml.setObjectName("sectionLabel")
        ml.setToolTip("The mod that Save buttons write into. Each mod is a folder of changes you can switch on/off "
                      "on the Home page.")
        sv.addWidget(ml)
        self.mod_combo = QComboBox()
        self.mod_combo.setToolTip(ml.toolTip())
        self.mod_combo.activated.connect(self._mod_selected)
        sv.addWidget(self.mod_combo)
        sv.addSpacing(8)

        # game status: one place that says whether the game has your changes, and one button
        self.status = GameStatus(self.ws, self)
        sv.addWidget(StatusPanel(self.status))
        h.addWidget(side)

        # ---------------- content + log
        self.right = QSplitter(Qt.Orientation.Vertical)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 10, 16, 6)
        from .updates import UpdateBar
        self.update_bar = UpdateBar(self)
        wl.addWidget(self.update_bar)
        wl.addWidget(self.stack)
        self.right.addWidget(wrap)
        logbox = QWidget()
        ll = QVBoxLayout(logbox)
        ll.setContentsMargins(8, 2, 8, 4)
        ll.setSpacing(2)
        lh = QHBoxLayout()
        self.log_toggle = QToolButton()
        self.log_toggle.setObjectName("logToggle")
        self.log_toggle.setText("▸  Log")
        self.log_toggle.setToolTip("Show / hide the log (everything the kit did)")
        self.log_toggle.clicked.connect(self._toggle_log)
        lh.addWidget(self.log_toggle)
        self.log_last = QLabel()
        self.log_last.setObjectName("muted")
        lh.addWidget(self.log_last, 1)
        b = QToolButton()
        b.setText("Clear")
        b.setObjectName("logToggle")
        b.clicked.connect(lambda: self.logview.clear())
        lh.addWidget(b)
        ll.addLayout(lh)
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(5000)
        self.logview.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 9))
        ll.addWidget(self.logview, 1)
        self.logview.setVisible(False)
        self.right.addWidget(logbox)
        self.right.setSizes([900, 30])          # collapsed: the last message stays visible on the bar
        self.right.setCollapsible(0, False)
        h.addWidget(self.right, 1)

        self.ws.log_message.connect(self._log)
        self.ws.mods_changed.connect(self.refresh_mods)
        self.ws.active_mod_changed.connect(lambda _: self.refresh_mods())
        self.refresh_mods()
        self.statusBar().showMessage(f"Game folder: {self.ws.game_dir}")
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_current)
        self.show_page("home")
        # The kit keeps big tables in memory (scripts, sprites, databases).  Python's full collection passes walk
        # all of them -- 0.2-0.5 s each, many times while a page loaded and now and then afterwards: the kit's
        # stutters.  Collect far less often, and freeze what pages keep (show_page) so later passes skip it.
        gc.set_threshold(20000, 20, 20)
        gc.freeze()
        QTimer.singleShot(2000, self._prewarm)
        if self.ws.settings.get("check_updates", True):
            QTimer.singleShot(5000, self.update_bar.check)

    def _prewarm(self):
        """parse the game's 19 053 scripts in the background shortly after start-up: Skills & Animations and Event
        Scripts then open at once"""
        from d5lib import skills
        from .common import Worker
        try:
            if not self.ws.game_ok() or skills.vanilla_scripts_ready(self.ws.fs):
                return
        except Exception:
            return
        self._prewarm_worker = Worker(skills.vanilla_scripts, self.ws.fs, True)
        self._prewarm_worker.start()

    # ------------------------------------------------------------------ log
    def _log(self, msg):
        self.logview.appendPlainText(msg)
        first = msg.splitlines()[0] if msg else ""
        self.log_last.setText(first[:160])
        self.statusBar().showMessage(first, 6000)

    def _toggle_log(self):
        sizes = self.right.sizes()
        if self.logview.isVisible():
            self._log_size = sizes[1]
            self.logview.setVisible(False)
            self.right.setSizes([sizes[0] + sizes[1] - 30, 30])
            self.log_toggle.setText("▸  Log")
        else:
            s = max(140, getattr(self, "_log_size", 160))
            self.logview.setVisible(True)
            self.right.setSizes([max(200, sizes[0] + sizes[1] - s), s])
            self.log_toggle.setText("▾  Log")

    # ------------------------------------------------------------------ mods
    def refresh_mods(self):
        self.mod_combo.blockSignals(True)
        self.mod_combo.clear()
        self.mod_combo.addItem("— none (asked on first save) —", None)
        enabled = set(self.ws.mods.load_order())
        for m in self.ws.mods.all_mods():
            self.mod_combo.addItem(m.name + ("" if m.id in enabled else "   (disabled)"), m.id)
        if self.ws.active_mod:
            i = self.mod_combo.findData(self.ws.active_mod.id)
            self.mod_combo.setCurrentIndex(max(0, i))
        self.mod_combo.blockSignals(False)

    def _mod_selected(self, idx):
        mid = self.mod_combo.itemData(idx)
        self.ws.set_active_mod(self.ws.mods.get(mid) if mid else None)

    # ------------------------------------------------------------------ unsaved work
    def unsaved(self):
        """[(description, save function)] of edits not saved into a mod yet, over every opened page"""
        out = []
        for key, p in self.pages.items():
            w = p["widget"]
            if w is None or key in ("characters", "database"):
                continue
            if getattr(w, "dirty", False) and hasattr(w, "save"):
                what = getattr(w, "unsaved_label", lambda: "")() if hasattr(w, "unsaved_label") else ""
                out.append((f"{LABELS[key]}{': ' + what if what else ''}", w.save))
        try:
            from .dbservice import get_service
            svc = get_service(self.ws)
            members = svc.dirty_members()
            if members:
                out.append(("Database tables: " + ", ".join(m.rsplit(".", 1)[0] for m in members),
                            lambda: svc.commit_all(self)))
        except Exception:
            pass
        return out

    def confirm_unsaved(self, action="install"):
        items = self.unsaved()
        if not items:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText("These edits are not saved into a mod yet, so they would not be "
                    + ("installed" if action == "install" else "kept") + ":\n\n• " +
                    "\n• ".join(d for d, _ in items))
        save = box.addButton("Save all" + (" && install" if action == "install" else " && quit"),
                             QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Install without them" if action == "install" else "Quit without saving",
                             QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() == save:
            for _, fn in items:
                try:
                    if fn() is False:
                        return False
                except Exception as e:
                    QMessageBox.critical(self, "Save failed", str(e))
                    return False
            return not self.unsaved()
        return box.clickedButton() == skip

    def closeEvent(self, e):
        if self.status.busy:
            QMessageBox.information(self, "Please wait", "The kit is still writing game files.")
            e.ignore()
            return
        if not self.confirm_unsaved("quit"):
            e.ignore()
            return
        e.accept()

    def _save_current(self):
        w = self.stack.currentWidget()
        if hasattr(w, "save"):
            w.save()

    # ------------------------------------------------------------------ pages
    def show_page(self, key):
        p = self.pages[key]
        if p["widget"] is None:
            try:
                module = __import__(f"d5gui.pages.{p['module']}", fromlist=[p["class"]])
                w = getattr(module, p["class"])(self.ws, self)
            except Exception as e:  # show error page instead of crashing
                w = QLabel(f"This page failed to load:\n\n{e}\n\n{traceback.format_exc()}")
                w.setWordWrap(True)
                w.setAlignment(Qt.AlignmentFlag.AlignTop)
                w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            p["widget"] = w
            p["index"] = self.stack.addWidget(w)
            QTimer.singleShot(4000, gc.freeze)        # what the new page keeps: out of the collector's passes
        p["button"].setChecked(True)
        self.stack.setCurrentIndex(p["index"])
        if hasattr(p["widget"], "on_show"):
            p["widget"].on_show()
        return p["widget"]


GUIDE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "START HERE - Guide.html"))


def open_guide(_=None):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(GUIDE))


def ensure_game_dir():
    """first start on a PC: find Disgaea 5 Complete, or ask for its folder (saved in settings.json)"""
    import json
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    from d5lib import paths
    if paths.game_dir():
        g = paths.game_dir()
    else:
        QMessageBox.information(None, "Where is Disgaea 5 Complete?",
                                "The D5 Mod Kit could not find Disgaea 5 Complete on this PC.\n\n"
                                "Choose the game folder next: the one that contains disgaea5.exe and the Data "
                                "folder. (Steam: right-click the game > Manage > Browse local files shows it.)")
        g = None
        while not g:
            d = QFileDialog.getExistingDirectory(None, "Disgaea 5 Complete folder (with disgaea5.exe)")
            if not d:
                QMessageBox.warning(None, "No game folder", "The kit needs the game to work. You can choose "
                                    "the folder later on the Home page (Change game folder...).")
                return
            if paths.is_game_dir(d):
                g = os.path.abspath(d)
            else:
                QMessageBox.warning(None, "Not the game folder", f"{d}\n\ndoes not contain disgaea5.exe and "
                                    "the Data folder. Try again.")
    try:
        with open(paths.SETTINGS, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    if s.get("game_dir") != g:
        s["game_dir"] = g
        with open(paths.SETTINGS, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)


def main():
    kit = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if kit not in sys.path:
        sys.path.insert(0, kit)
    app = QApplication(sys.argv)
    app.setApplicationName("D5 Mod Kit")
    app.setStyleSheet(QSS.replace("'Segoe UI', 'Yu Gothic UI'", "'Helvetica Neue', 'Hiragino Sans'")
                      if sys.platform == "darwin" else QSS)
    ensure_game_dir()
    w = MainWindow()
    w.show()
    from .common import Worker
    app.aboutToQuit.connect(Worker.wait_all)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
