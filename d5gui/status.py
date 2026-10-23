"""Game status: are the mods in the game?  One controller owns install / play / restore for the whole app, and
StatusPanel shows its state (sidebar and Home use the same panel, so they can never disagree)."""
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QProgressBar)

from .common import Worker

STATES = {
    # state: (dot colour, title, explanation)
    "ready": ("#3ecf8e", "Ready to play", "Your enabled mods are installed in the game."),
    "pending": ("#f5a524", "Changes not in the game yet",
                "You saved changes since the last install. Install them to see them in game."),
    "not_installed": ("#f5a524", "Mods not installed", "The game is still original. Install your mods to play them."),
    "vanilla": ("#8a90b8", "Original game", "No mod is enabled. Enable or create a mod on the Home page."),
    "other_profile": ("#f5a524", "Another profile is in the game",
                      "The game has the mods of another profile. Install to put this profile's mods in."),
    "installing": ("#7c83ff", "Installing…", "Building your mods and writing them into the game files."),
}


class GameStatus(QObject):
    changed = pyqtSignal()
    _checked = pyqtSignal(object)

    def __init__(self, ws, main):
        super().__init__()
        self.ws, self.main = ws, main
        self.state = None
        self.running = False
        self.busy = None              # "installing" / "restoring"
        self.step = ""
        self.last_result = ""
        self.worker = None
        self._checking = False
        self._again = False
        self._checked.connect(self._apply)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_later)
        self._timer.start(2500)
        ws.file_changed.connect(lambda *_: QTimer.singleShot(150, self.refresh_later))
        ws.mods_changed.connect(lambda: QTimer.singleShot(150, self.refresh_later))
        ws.log_message.connect(self._log)
        self.refresh()

    def _check(self):
        try:
            st = self.ws.install_state()
        except Exception:
            st = "pending"
        try:
            run = self.ws.is_game_running()
        except Exception:
            run = False
        return st, run

    def refresh(self):
        """check now (after an install / restore, where the next step needs the answer)"""
        if not self.busy:
            self._apply(self._check(), mine=False)

    def refresh_later(self):
        """check in the background: the install state reads every enabled mod's file list (~0.15 s, more on a slow
        disk), which on the GUI thread every 2.5 s made the whole kit stutter"""
        if self.busy:
            return
        if self._checking:
            self._again = True
            return
        self._checking = True
        threading.Thread(target=lambda: self._checked.emit(self._check()), daemon=True).start()

    def _apply(self, res, mine=True):
        if mine:
            self._checking = False
            if self._again:
                self._again = False
                QTimer.singleShot(0, self.refresh_later)
        if self.busy:
            return
        st, run = res
        if (st, run) != (self.state, self.running):
            self.state, self.running = st, run
            self.changed.emit()

    def _log(self, msg):
        if self.busy and msg:
            line = msg.strip().splitlines()[0]
            if line.startswith(("Building mod:", "patched", "Restoring", "restored", "Preparing", "Writing")):
                self.step = line
                self.changed.emit()

    # ------------------------------------------------------------------ actions
    def _quests_ok(self):
        """quests pointing at stages of switched-off mods: the player could never finish them -- ask"""
        try:
            from d5lib import questcheck
            probs = questcheck.problems(self.ws.fs, self.ws.mods.enabled_mods(), self.ws.mods.all_mods())
        except Exception:
            return True
        if not probs:
            return True
        box = QMessageBox(self.main)
        box.setWindowTitle("Install anyway?")
        box.setText("\n\n".join(p["text"] for p in probs) +
                    "\n\nSwitch those mods on (Home), or change what the quest asks for (Characters → the "
                    "character → How to get this character).")
        go = box.addButton("Install anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is go

    def _blocked(self, what):
        if self.running:
            QMessageBox.information(self.main, "Close the game first",
                                    f"Disgaea 5 is running. Close it, then {what} (the game locks its files).")
            return True
        return False

    def install(self, play=False):
        if self.busy or self._blocked("install the mods"):
            return
        if not self.main.confirm_unsaved("install"):
            return
        if not self._quests_ok():
            return
        self.busy, self.step = "installing", ""
        self.changed.emit()
        self.worker = Worker(self.ws.build_and_install)

        def done(n):
            self.busy = None
            self.last_result = f"Installed {len(self.ws.mods.load_order())} mod(s) ({n} game file(s) written)."
            self.ws.log("✔ " + self.last_result + " The game is ready to play.")
            self.state = None
            self.refresh()
            try:                                      # units made before a weapon mastery change (savecleanup)
                from .savecleanup import after_install
                after_install(self.main, self.ws)
            except Exception as e:
                self.ws.log(f"(saves not checked for weapon mastery: {e})")
            if play:
                self.play()

        def failed(msg):
            self.busy = None
            self.last_result = "Install failed: " + msg.splitlines()[0]
            self.ws.log("Install FAILED:\n" + msg)
            self.state = None
            self.refresh()
            QMessageBox.critical(self.main, "Install failed", msg[:3000])

        self.worker.done.connect(done)
        self.worker.failed.connect(failed)
        self.worker.start()

    def play(self):
        if self.running:
            QMessageBox.information(self.main, "Game is running", "Disgaea 5 is already running.")
            return
        if self.state in ("pending", "not_installed", "other_profile"):
            r = QMessageBox.question(self.main, "Install first?",
                                     "Your latest changes are not in the game yet.\n\nInstall them before playing?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                     QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Yes:
                return self.install(play=True)
            if r == QMessageBox.StandardButton.Cancel:
                return
        try:
            self.ws.launch_game()
            self.ws.log("▶ Game started.")
            QTimer.singleShot(4000, self.refresh_later)
        except Exception as e:
            QMessageBox.critical(self.main, "Could not start the game", str(e))

    def restore(self):
        if self.busy or self._blocked("restore the original game"):
            return
        if QMessageBox.question(self.main, "Restore original game",
                                "Put the game's original files back (your mods stay in the kit and can be installed "
                                "again any time)?") != QMessageBox.StandardButton.Yes:
            return
        self.busy, self.step = "restoring", ""
        self.changed.emit()
        self.worker = Worker(self.ws.restore_vanilla)

        def done(_):
            self.busy = None
            self.last_result = "Original game files restored."
            self.ws.log("✔ " + self.last_result)
            self.state = None
            self.refresh()

        def failed(msg):
            self.busy = None
            self.state = None
            self.refresh()
            QMessageBox.critical(self.main, "Restore failed", msg[:3000])

        self.worker.done.connect(done)
        self.worker.failed.connect(failed)
        self.worker.start()

    # ------------------------------------------------------------------ text
    def view(self):
        """(dot colour, title, detail, primary label, primary action, primary enabled)"""
        if self.busy:
            col, title, detail = STATES["installing"]
            if self.busy == "restoring":
                title, detail = "Restoring…", "Putting the original game files back."
            return col, title, self.step or detail, "Working…", None, False
        col, title, detail = STATES.get(self.state, STATES["pending"])
        if self.state == "other_profile":
            try:
                inst = self.ws.installer.installed_info().get("profile_name") or "another profile"
                detail = (f"The game has the mods of the profile '{inst}'. Install to put the profile "
                          f"'{self.ws.profile.name}' in.")
            except Exception:
                pass
        if self.running:
            if self.state in ("pending", "not_installed", "other_profile"):
                return ("#f5a524", "Game running — changes not in it",
                        "Close the game, then install to see your latest changes.", "Close the game to install",
                        None, False)
            return col, "Game running", "Have fun! The installed mods are active.", "Game is running", None, False
        if self.state in ("pending", "not_installed", "other_profile"):
            return col, title, detail, "⚡  Install && Play", lambda: self.install(True), True
        return col, title, detail, "▶  Play", self.play, True


class StatusPanel(QFrame):
    """Dot + title + detail + one primary button (+ secondary actions on the large version)."""

    def __init__(self, status: GameStatus, large=False, parent=None):
        super().__init__(parent)
        self.status = status
        self.large = large
        self.setObjectName("statusPanel" if not large else "statusPanelLarge")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10) if not large else lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.dot = QLabel("●")
        self.dot.setObjectName("statusDot")
        top.addWidget(self.dot)
        self.title = QLabel()
        self.title.setObjectName("statusTitle" if not large else "statusTitleLarge")
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        lay.addLayout(top)
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        self.primary = QPushButton()
        self.primary.setObjectName("primary")
        self.primary.clicked.connect(self._primary)
        row.addWidget(self.primary, 1 if not large else 0)
        self.secondary = []
        if large:
            for text, fn, tip in [
                    ("Install only", lambda: status.install(False), "Install the enabled mods without starting the game"),
                    ("Play", status.play, "Start the game"),
                    ("Restore original game…", status.restore,
                     "Put the game's original files back (your mods stay in the kit)")]:
                b = QPushButton(text)
                b.setToolTip(tip)
                b.clicked.connect(fn)
                if text.startswith("Restore"):
                    b.setObjectName("subtle")
                row.addWidget(b)
                self.secondary.append(b)
            row.addStretch(1)
        lay.addLayout(row)
        self.result = QLabel()
        self.result.setObjectName("muted")
        self.result.setWordWrap(True)
        if large:
            lay.addWidget(self.result)
        self._action = None
        status.changed.connect(self.update_view)
        self.update_view()

    def _primary(self):
        if self._action:
            self._action()

    def update_view(self):
        col, title, detail, label, action, enabled = self.status.view()
        self.dot.setStyleSheet(f"color: {col}; font-size: {'16' if self.large else '13'}pt;")
        self.title.setText(title)
        self.detail.setText(detail)
        self.primary.setText(label)
        self.primary.setEnabled(enabled)
        self._action = action
        self.bar.setVisible(bool(self.status.busy))
        busy = bool(self.status.busy) or self.status.running
        for b in self.secondary:
            b.setEnabled(not busy)
            if b.text() == "Play":             # only next to "Install & Play" (else the main button is Play)
                b.setVisible(label.startswith("⚡"))
        self.result.setText(self.status.last_result)
        self.result.setVisible(self.large and bool(self.status.last_result))
