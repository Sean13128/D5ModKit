"""Compatibility report of the game's disgaea5.exe: which build it is, whether Steam's DRM wraps it, and how many of the
places the kit patches can be found in it (d5lib.exemap).  Nothing of the game goes into the report.

    python tools/exe_report.py [GAME_FOLDER or path of disgaea5.exe]

Paste the output into a GitHub issue (https://github.com/eraser4521/D5ModKit/issues) or send it to the kit's author.
"""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, KIT)
from d5lib import exemap, modsys, paths, gamecheck   # noqa: E402


def exe_path(arg=None):
    if arg:
        return arg if arg.lower().endswith(".exe") else os.path.join(arg, "disgaea5.exe")
    g = paths.require_game_dir()
    try:
        return gamecheck.original_exe(modsys.Installer(g, KIT, log=lambda *a: None))
    except Exception:
        return os.path.join(g, "disgaea5.exe")


if __name__ == "__main__":
    p = exe_path(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"D5 Mod Kit compatibility report ({os.path.basename(p)})")
    print(exemap.report(p))
