"""Is this a game the kit can work with?  Shown on the Home page and checked before an install.

check(installer) -> [(level, text)], level "error" (installing would go wrong: the kit refuses) or "warning".

* The game folder must hold disgaea5.exe and the Data archives the kit edits.
* A mods package made with tools/export_pack.py (the player installer .exe) keeps its own backups in <game>\\D5Mods:
  while it is installed, the kit must not install on top (it would take the modded files for the originals).
* disgaea5.exe already carrying the kit's code sections while this kit has no record of installing them = an exe from
  another modded setup: restore the original first.
* The game program's build is known by its SHA-1 (the original exe, or the kit's backup of it once installed): the
  launch build the kit was made on, and the builds with an address map (d5lib/data/exe_map_<sha>.json, see
  d5lib/exemap.py) such as the current Steam one.  Another build: the kit places its changes by matching the program
  itself; a change it can't place is left out of the install with a note, the data-only mods always work.
"""
import hashlib
import os

from .gamefs import EXE_FILE

KNOWN_EXE = {
    "436eefd2a29466e2ecaa5a57fd65255009896581": "Disgaea 5 Complete for PC (version of October 2018)",
    "9460a6411699a256faaf0daed6b90d903a7d6491": "Disgaea 5 Complete for PC, Steam (update of January 2019, with "
                                                "Chinese and Korean)",
}
NEEDED = ("Anime/ANM_HI_JP.dat", "Database/Database_0.dat", "Script/script.dat", "Start/Start_JP.dat")
STEAM_VERIFY = "Steam: right-click the game > Properties > Installed Files > Verify integrity of game files"


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def kit_sections(path):
    """names of the kit's code sections (.d5...) in an exe"""
    import struct
    with open(path, "rb") as f:
        head = f.read(0x1000)
    try:
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        n = struct.unpack_from("<H", head, pe + 6)[0]
        opt = struct.unpack_from("<H", head, pe + 20)[0]
        sh = pe + 24 + opt
        names = [head[sh + 40 * i:sh + 40 * i + 8].rstrip(b"\0") for i in range(n)]
    except struct.error:
        return []
    return [x.decode("latin1") for x in names if x.startswith(b".d5")]


def original_exe(installer):
    """path of the original exe: the kit's backup once it changed the exe, else the game's own"""
    rec = installer.index.get(EXE_FILE)
    if rec and rec.get("modified"):
        b = installer._bfile(EXE_FILE, ".full")
        if os.path.exists(b):
            return b
    return installer.apath(EXE_FILE)


def exe_version(installer):
    """(sha1, description or None) of the original exe"""
    h = _sha1(original_exe(installer))
    desc = KNOWN_EXE.get(h)
    if desc is None:
        from . import exemap
        if os.path.exists(os.path.join(os.path.dirname(exemap.REF_PATH), f"exe_map_{h[:12]}.json")):
            desc = f"Disgaea 5 Complete for PC (build {h[:12]})"
    return h, desc


def check(installer):
    game = installer.game_dir
    out = []
    exe = os.path.join(game, "disgaea5.exe")
    if not os.path.isfile(exe) or not os.path.isdir(os.path.join(game, "Data")):
        return [("error", f"Disgaea 5 Complete was not found in {game}. Choose the game folder (the one with "
                          f"disgaea5.exe) on the Home page.")]
    missing = [p for p in NEEDED if not os.path.isfile(os.path.join(game, "Data", p))]
    if missing:
        out.append(("error", "Game files are missing: " + ", ".join("Data/" + p for p in missing) +
                    f". Repair the game ({STEAM_VERIFY})."))
    if os.path.isfile(os.path.join(game, "D5Mods", "installed.txt")):
        out.append(("error", "A mods package (an installer .exe made with the kit) is installed in this game. "
                             "Run that installer and press Uninstall first; the kit and a package must not be "
                             "installed at the same time."))
    rec = installer.index.get(EXE_FILE)
    if not (rec and rec.get("modified")):
        secs = kit_sections(exe)
        if secs:
            out.append(("error", "The game already has mods from another copy of the D5 Mod Kit (disgaea5.exe "
                                 "contains " + ", ".join(secs) + ", which this copy did not install). Press "
                                 "'Restore original game...' in that other copy first, or put the original files "
                                 f"back ({STEAM_VERIFY}). To keep using the old copy's backups instead, copy its "
                                 "'state' folder into this kit."))
            return out
    try:
        h, desc = exe_version(installer)
    except OSError as e:
        out.append(("warning", f"disgaea5.exe could not be read ({e})."))
        return out
    if not desc:
        out.append(("warning", f"This disgaea5.exe (fingerprint {h[:12]}) is a build of the game the kit hasn't "
                               "been checked with. The kit finds its way around it by itself (the first install "
                               "takes a minute longer); a change to the game program it can't place there is left "
                               "out of the install and named in the log, everything else installs. Press 'Copy "
                               "compatibility report' and send it to the kit's author (GitHub issues) to help add "
                               "your build."))
    return out


def unknown_exe(installer):
    """is the game's exe a build the kit doesn't know (the Home page then offers the compatibility report)"""
    try:
        return exe_version(installer)[1] is None
    except OSError:
        return False


def errors(installer):
    return [t for lvl, t in check(installer) if lvl == "error"]


def save_needs_mods(game_dir, mods, enabled):
    """Units of the last game session whose class the game didn't have -- a save made with a mod that is switched
    off now (the game crashes entering a battle with it).  The kit's runtime names them in d5auto.log ("rows:
    MISSING CLASS N"); each is matched to the mod that adds the class.  -> [(class id, name, mod or None)] of the
    classes no enabled mod provides"""
    import json
    import re
    try:
        with open(os.path.join(game_dir, "d5auto.log"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    classes = {int(m) for m in re.findall(r"rows: MISSING CLASS (\d+)", text)}
    classes |= {int(m) for m in re.findall(r"rows: unit \d+ \(class (\d+)\) row -?\d+ -> -1\b", text)}
    if not classes:
        return []
    owner = {}
    for mod in mods:
        try:
            with open(os.path.join(mod.folder, "patches", "db", "char.dat.json"), encoding="utf-8") as f:
                rows = json.load(f).get("added") or []
        except (OSError, ValueError, AttributeError):
            continue
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get("id"), int):
                owner.setdefault(r["id"], (r.get("name_EN") or "", mod))
    out = []
    for c in sorted(classes):
        name, mod = owner.get(c, ("", None))
        if mod is not None and mod.id in enabled:
            continue                          # switched on since: the next install has it
        out.append((c, name, mod))
    return out
