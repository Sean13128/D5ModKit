"""Update notice: a bar over the pages when GitHub has a newer release of the kit, and the in-place update
(d5lib.updater).  The check runs in the background a few seconds after start (Home: 'Check for updates at start')."""
import os
import sys
import tempfile

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QMessageBox, QProgressDialog, QApplication)

from d5lib import updater
from d5lib.version import VERSION
from .common import Worker

KIT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class UpdateBar(QFrame):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.info = None
        self.setObjectName("updateBar")
        self.setStyleSheet("#updateBar { background: #2c2350; border: 1px solid #6c5bd4; border-radius: 8px; }")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 8, 6)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(self.text, 1)
        self.notes = QPushButton("What's new")
        self.notes.clicked.connect(self._notes)
        h.addWidget(self.notes)
        self.go = QPushButton("⬇  Update now")
        self.go.clicked.connect(self.update_now)
        h.addWidget(self.go)
        later = QPushButton("Later")
        later.clicked.connect(self.hide)
        h.addWidget(later)
        self.hide()
        self._worker = None

    # ------------------------------------------------------------------ checking
    def check(self, quiet=True):
        """ask GitHub for the newest release (background); quiet: say nothing when there is none or no internet"""
        if self._worker is not None:
            return
        self._quiet = quiet
        self._worker = Worker(updater.latest)
        self._worker.done.connect(self._checked)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _failed(self, msg):
        self._worker = None
        if not self._quiet:
            QMessageBox.information(self.main, "Check for updates",
                                    "Could not reach GitHub to check for a newer kit:\n\n" + msg.splitlines()[0])

    def _checked(self, info):
        self._worker = None
        self.info = info
        if info.get("version") and updater.newer(info["version"], VERSION):
            small = updater.update_asset(info, VERSION)
            size = f" ({small[1] / 1e6:.0f} MB)" if small and small[1] else ""
            self.text.setText(f"<b>D5 Mod Kit {info['version']}</b> is out (you have {VERSION}). "
                              + (f"Update in place{size}: your mods and settings stay." if small else
                                 "This version needs the full download from the release page."))
            self.go.setText("⬇  Update now" if small else "Open the download page")
            self.show()
        elif not self._quiet:
            QMessageBox.information(self.main, "Check for updates", f"You have the newest kit ({VERSION}).")

    def _notes(self):
        if not self.info:
            return
        box = QMessageBox(self.main)
        box.setWindowTitle(f"D5 Mod Kit {self.info['version']}")
        box.setText((self.info.get("notes") or "No notes.")[:6000])
        box.exec()

    # ------------------------------------------------------------------ updating
    def update_now(self):
        if not self.info:
            return
        small = updater.update_asset(self.info, VERSION)
        if not small:
            QDesktopServices.openUrl(QUrl(self.info.get("url") or updater.RELEASES))
            return
        if self.main.status.busy:
            QMessageBox.information(self.main, "Please wait", "The kit is still writing game files.")
            return
        if not self.main.confirm_unsaved("quit"):
            return
        url, size = small
        dest = os.path.join(tempfile.gettempdir(), updater.update_name(VERSION, self.info["version"]))
        dlg = QProgressDialog("Downloading the update…", "Cancel", 0, max(1, size), self.main)
        dlg.setWindowTitle("Updating the kit")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        self._dl = Worker(self._download_and_apply, url, dest)
        self._dl.progress.connect(lambda s: dlg.setValue(int(s)))
        dlg.canceled.connect(lambda: setattr(self, "_cancel", True))
        self._cancel = False

        def done(res):
            dlg.close()
            if res is None:
                return
            n = len(res["written"])
            extra = (f"\n\n{len(res['backed_up'])} file(s) you had changed are kept in "
                     f"state\\update_backups\\{res['version']}." if res["backed_up"] else "")
            r = QMessageBox.question(self.main, "Kit updated",
                                     f"The kit is now version {res['version']} ({n} file(s) updated).{extra}\n\n"
                                     "Restart it now?")
            self.hide()
            if r == QMessageBox.StandardButton.Yes:
                self._restart()

        def failed(msg):
            dlg.close()
            QMessageBox.critical(self.main, "Update failed",
                                 "The update could not be installed (nothing was changed if it failed while "
                                 "downloading):\n\n" + msg[:2000] + "\n\nYou can always get the full kit from "
                                 + updater.RELEASES)
        self._dl.done.connect(done)
        self._dl.failed.connect(failed)
        self._dl.start()

    def _download_and_apply(self, url, dest):
        def progress(d, t):
            self._dl.progress.emit(str(d))
            if self._cancel:
                raise RuntimeError("cancelled")
        try:
            updater.download(url, dest, progress)
        except RuntimeError as e:
            if str(e) == "cancelled":
                return None
            raise
        res = updater.apply(dest, KIT_DIR, log=self.main.ws.log)
        try:
            os.remove(dest)
        except OSError:
            pass
        return res

    def _restart(self):
        from PyQt6.QtCore import QProcess
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        QProcess.startDetached(exe, [os.path.join(KIT_DIR, "D5ModKit.pyw")], KIT_DIR)
        QApplication.instance().quit()
