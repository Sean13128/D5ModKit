"""Shared application state: game data, mods, active mod, settings."""
import json
import os
import subprocess

from PyQt6.QtCore import QObject, pyqtSignal

from d5lib import modsys, paths
from d5lib.gamefs import GameFS

KIT_DIR = modsys.KIT_DIR


def game_running(exe="disgaea5.exe"):
    """Is the game running?  (process snapshot through the Windows API: no console window flashes)"""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(2, 0)
        if snap in (None, wintypes.HANDLE(-1).value):
            return False
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        found = False
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == exe:
                found = True
                break
            ok = k32.Process32NextW(snap, ctypes.byref(e))
        k32.CloseHandle(snap)
        return found
    except Exception:
        return False


class Workspace(QObject):
    active_mod_changed = pyqtSignal(object)
    mods_changed = pyqtSignal()
    file_changed = pyqtSignal(str)  # vpath edited in the active mod
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.settings_file = os.path.join(KIT_DIR, "settings.json")
        self.settings = {"game_dir": "", "language": "EN", "active_mod": None}
        if os.path.exists(self.settings_file):
            with open(self.settings_file, encoding="utf-8") as f:
                self.settings.update(json.load(f))
        # first start on a PC (or the game moved): the kit's parent folder, Steam, the usual places
        if not paths.is_game_dir(self.settings.get("game_dir")):
            found = paths.find_game()
            self.settings["game_dir"] = found or ""
            if found:
                self.save_settings()
        self.mods = modsys.ModManager(KIT_DIR)
        self._open_game()
        self.active_mod = self.mods.get(self.settings.get("active_mod") or "") if self.settings.get("active_mod") else None

    # ------------------------------------------------------------------ setup
    def _open_game(self):
        self.installer = modsys.Installer(self.game_dir, KIT_DIR, log=self.log)
        self.fs = GameFS(self.game_dir, backup_resolver=self.installer.backup_resolver)

    @property
    def game_dir(self):
        return self.settings["game_dir"]

    @property
    def language(self):
        return self.settings.get("language", "EN")

    def game_ok(self):
        return os.path.exists(os.path.join(self.game_dir, "disgaea5.exe")) and os.path.isdir(
            os.path.join(self.game_dir, "Data"))

    def save_settings(self):
        with open(self.settings_file, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=2)

    def set_game_dir(self, path):
        self.settings["game_dir"] = path
        self.save_settings()
        self.fs.reset()
        self._open_game()

    def log(self, msg):
        self.log_message.emit(str(msg))

    # ------------------------------------------------------------------ mods
    def set_active_mod(self, mod):
        self.active_mod = mod
        self.settings["active_mod"] = mod.id if mod else None
        self.save_settings()
        self.active_mod_changed.emit(mod)

    def require_mod(self, parent=None):
        """Return the active mod, asking the user to create one if needed."""
        if self.active_mod:
            return self.active_mod
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(parent, "Create a mod",
                                        "Your changes are saved into a mod.\nName for your new mod:",
                                        text="My Mod")
        if not ok or not name.strip():
            return None
        mod = self.mods.create(name.strip())
        self.mods_changed.emit()
        self.set_active_mod(mod)
        return mod

    # ------------------------------------------------------------------ file access
    def owner(self, vpath):
        """The mod whose copy of vpath the game gets: the active mod first, then the enabled mods (the last one
        in the load order wins, as at install).  None = the game's own file."""
        if self.active_mod and self.active_mod.has_file(vpath):
            return self.active_mod
        for mod in reversed(self.mods.enabled_mods()):
            if mod.has_file(vpath):
                return mod
        return None

    def read(self, vpath):
        """Effective content: the owning mod's file if any mod has one, otherwise the game's original."""
        mod = self.owner(vpath)
        return mod.read_file(vpath) if mod else self.fs.read(vpath)

    def exists(self, vpath):
        if self.owner(vpath):
            return True
        try:
            self.fs.read(vpath)
            return True
        except KeyError:
            return False

    def is_modified(self, vpath):
        return self.owner(vpath) is not None

    def write(self, vpath, data: bytes, parent=None, mod=None):
        """Save a file into a mod: the given one, else the mod that already has this file (otherwise its copy could
        win at install and the edit would be lost), else the active mod."""
        if mod is None:
            owner = self.owner(vpath)
            if owner and self.active_mod and owner.id != self.active_mod.id:
                mod = owner
                self.log(f"'{vpath.rsplit('/', 1)[-1]}' belongs to the mod '{owner.name}', so it was saved there.")
        mod = mod or self.require_mod(parent)
        if not mod:
            return False
        mod.write_file(vpath, data)
        self.file_changed.emit(vpath)
        return True

    # ------------------------------------------------------------------ install state
    def mods_signature(self):
        """Fingerprint of everything an install would read: load order, each enabled mod's files and patches
        (paths, sizes, times) and the kit's own code.  Equal to the stored one = the game has these mods."""
        import hashlib
        h = hashlib.sha1()
        for mod in self.mods.enabled_mods():
            h.update(mod.id.encode())
            for root, _, files in os.walk(mod.folder):
                for fn in sorted(files):
                    p = os.path.join(root, fn)
                    st = os.stat(p)
                    h.update(f"{os.path.relpath(p, mod.folder)}|{st.st_size}|{st.st_mtime_ns}".encode())
        lib = os.path.join(KIT_DIR, "d5lib")
        for root, _, files in os.walk(lib):
            for fn in sorted(files):
                if fn.endswith((".py", ".json", ".c", ".dll")):
                    p = os.path.join(root, fn)
                    h.update(f"{fn}|{os.stat(p).st_mtime_ns}".encode())
        return h.hexdigest()

    def install_state(self):
        """'pending' (mods changed since the install) | 'not_installed' | 'ready' | 'vanilla' (no mods at all)"""
        enabled = self.mods.load_order()
        installed = bool(self.installer.modified_archives())
        if not enabled:
            return "pending" if installed else "vanilla"
        if not installed:
            return "not_installed"
        return "ready" if self.settings.get("installed_signature") == self.mods_signature() else "pending"

    def mark_installed(self, installed=True):
        self.settings["installed_signature"] = self.mods_signature() if installed else None
        self.save_settings()

    def revert(self, vpath, mod=None):
        mod = mod or self.owner(vpath)
        if mod:
            mod.remove_file(vpath)
            self.file_changed.emit(vpath)

    # ------------------------------------------------------------------ install / launch
    def build_and_install(self):
        from d5lib import gamecheck
        problems = gamecheck.errors(self.installer)
        if problems:
            raise RuntimeError("The mods were not installed:\n\n" + "\n\n".join(problems))
        sig = self.mods_signature()              # taken first: edits made during the install count as new
        mods = self.mods.enabled_mods()
        self.log(f"Installing {len(mods)} mod(s): " + ", ".join(m.name for m in mods))
        ctx = modsys.build(self.fs, mods, log=self.log)
        self.installer.install(self.fs, ctx)
        self.settings["installed_signature"] = sig
        self.save_settings()
        return len(ctx.outputs)

    def restore_vanilla(self):
        self.installer.restore_all()
        self.fs.reset()
        self.mark_installed(False)

    def launch_game(self):
        exe = os.path.join(self.game_dir, "disgaea5.exe")
        subprocess.Popen([exe], cwd=self.game_dir)

    def is_game_running(self):
        return game_running()
