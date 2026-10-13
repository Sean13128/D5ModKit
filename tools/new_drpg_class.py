"""Make a new recruitable generic class from a Disgaea RPG unit, animated exactly like a vanilla class.

    python tools/new_drpg_class.py UNIT TEMPLATE "Name" [--titles "T1,T2,T3,T4,T5,T6"] [--desc "one line"]
                                   [--family 1290] [--personalities "A,B,C"]
    python tools/new_drpg_class.py --templates        list the usable templates

UNIT: DRPG unit number (DRPG Assets (Updated)/Characters/Sprites/front/front<UNIT>.png).
TEMPLATE: the vanilla class whose animations, weapon handling, idle and special poses the new class uses
(e.g. 1060 Fight Mistress, 1070 Clergy, 1110 Archer).  Pick one with a similar build and weapon style.
The class gets its own mod (Class_<Name>), enabled; stats / skills / evilities start as the template's ranks --
edit them on the Characters page, then Install.  See docs/CLASSES.md.
Check where the weapon sits on the GUI's Weapon Grips page (or `python tools/grips.py sheet SPRITE 6001 sword`)
and drag it into the hand where needed: docs/WEAPON_GRIPS.md.
"""
import argparse
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import database, modsys, newclasses        # noqa: E402
from d5lib.gamefs import GameFS                       # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("unit", nargs="?", type=int)
ap.add_argument("template", nargs="?", type=int)
ap.add_argument("name", nargs="?")
ap.add_argument("--titles")
ap.add_argument("--desc", default="")
ap.add_argument("--family", type=int)
ap.add_argument("--personalities")
ap.add_argument("--templates", action="store_true")
a = ap.parse_args()

game = paths.require_game_dir()
fs = GameFS(game, backup_resolver=modsys.Installer(game, KIT, log=lambda *x: None).backup_resolver)
if a.templates or not a.name:
    rows = {r["id"]: r for r in database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat")).rows}
    print("templates:", ", ".join(f"{c} {rows[c]['name_EN']}" for c in newclasses.templates()))
    sys.exit(0)
mm = modsys.ModManager(KIT)
newclasses.create_class(fs, mm, a.unit, a.template, a.name, family=a.family,
                        titles=a.titles.split(",") if a.titles else None, hire_desc=a.desc,
                        personalities=a.personalities.split(",") if a.personalities else None)
