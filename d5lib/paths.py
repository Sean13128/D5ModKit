"""Where the game is.

The kit can live anywhere: inside the game folder (the simplest: `<game>\\D5ModKit`) or elsewhere.  The game folder
is, in this order: the one saved in settings.json ("game_dir", set on the Home page), the folder the kit sits in,
then Disgaea 5 Complete found through Steam (every Steam library: the Windows registry and the macOS/Linux default
roots with their ``libraryfolders.vdf``) or the usual install places.

    from d5lib import paths
    game = paths.game_dir()          # None when no game folder was found (the GUI then asks for it)
"""
import json
import os
import re

KIT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SETTINGS = os.path.join(KIT_DIR, "settings.json")
STEAM_APP_ID = 803600
GAME_FOLDER = "Disgaea 5 Complete"


def is_game_dir(path):
    """the folder holds the PC game (disgaea5.exe and its Data folder)"""
    return bool(path) and os.path.isfile(os.path.join(path, "disgaea5.exe")) and \
        os.path.isdir(os.path.join(path, "Data"))


def _reg(root, key, value):
    try:
        import winreg
        with winreg.OpenKey(root, key) as k:
            return winreg.QueryValueEx(k, value)[0]
    except OSError:
        return None
    except ImportError:
        return None


def _add_library_folders(root, libs):
    """append root and every ``steamapps/libraryfolders.vdf`` path under it (deduplicated)"""
    root = os.path.normpath(root)
    if root not in libs:
        libs.append(root)
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = os.path.normpath(m.group(1).replace("\\\\", "\\"))
        if p not in libs:
            libs.append(p)


def steam_libraries():
    """every Steam library folder of this PC, from the Windows registry (main install first)"""
    try:
        import winreg
    except ImportError:
        return []
    roots = [_reg(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
             _reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
             _reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")]
    libs = []
    for root in roots:
        if root:
            _add_library_folders(root, libs)
    return libs


def platform_steam_roots():
    """the default Steam roots on macOS and Linux (no registry there)"""
    home = os.path.expanduser("~")
    out = []
    for candidate in (os.path.join(home, "Library/Application Support/Steam"),
                      os.path.join(home, ".steam/steam"),
                      os.path.join(home, ".local/share/Steam"),
                      os.path.join(home, ".var/app/com.valvesoftware.Steam/data/Steam")):
        candidate = os.path.normpath(candidate)
        if os.path.isdir(candidate) and candidate not in out:
            out.append(candidate)
    return out


def steam_libraries_all():
    """every Steam library folder of this machine: registry (Windows) plus macOS/Linux defaults and their vdf"""
    libs = list(steam_libraries())
    for root in platform_steam_roots():
        _add_library_folders(root, libs)
    return libs


def steam_app(appid, folder):
    """the installed folder of one Steam app (``folder`` is its steamapps/common name), or None"""
    for library in steam_libraries_all():
        game = os.path.join(library, "steamapps", "common", folder)
        if os.path.isdir(game):
            return game
    return None


def candidates():
    """places the game may be, most likely first"""
    out = [os.path.dirname(KIT_DIR)]
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {STEAM_APP_ID}",
                        rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {STEAM_APP_ID}"):
                p = _reg(root, key, "InstallLocation")
                if p:
                    out.append(p)
    except ImportError:
        pass
    out += [os.path.join(lib, "steamapps", "common", GAME_FOLDER) for lib in steam_libraries_all()]
    for drive in "CDEFGH":
        out += [rf"{drive}:\Program Files (x86)\Steam\steamapps\common\{GAME_FOLDER}",
                rf"{drive}:\Program Files\Steam\steamapps\common\{GAME_FOLDER}",
                rf"{drive}:\SteamLibrary\steamapps\common\{GAME_FOLDER}",
                rf"{drive}:\Steam\steamapps\common\{GAME_FOLDER}",
                rf"{drive}:\Games\{GAME_FOLDER}"]
    seen, res = set(), []
    for p in out:
        p = os.path.normpath(p)
        if p.lower() not in seen:
            seen.add(p.lower())
            res.append(p)
    return res


def find_game():
    """the first candidate that holds the game, or None"""
    return next((p for p in candidates() if is_game_dir(p)), None)


def kit_setting(key, default=None):
    """a value of the kit's settings.json (the GUI's settings), or default"""
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError, AttributeError):
        return default


def saved_game_dir():
    return kit_setting("game_dir")


def game_dir():
    """the game folder: settings.json, else the kit's parent / Steam / usual places (None when none is found)"""
    saved = saved_game_dir()
    if is_game_dir(saved):
        return os.path.abspath(saved)
    return find_game()


def require_game_dir():
    """game_dir() or a clear error (command-line tools)"""
    g = game_dir()
    if not g:
        raise SystemExit("Disgaea 5 Complete was not found.  Start the D5 Mod Kit once and choose the game folder on "
                         "the Home page (or put the D5ModKit folder inside the game folder).")
    return g
