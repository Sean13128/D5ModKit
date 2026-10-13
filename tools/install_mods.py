"""Install the enabled mods into the game (the same as the kit's Install button).   python tools/install_mods.py"""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, KIT)
from d5lib import modsys, paths            # noqa: E402
from d5lib.gamefs import GameFS            # noqa: E402

game = paths.require_game_dir()
mods = modsys.ModManager(KIT)
inst = modsys.Installer(game, KIT, log=print)
fs = GameFS(game, backup_resolver=inst.backup_resolver)
en = mods.enabled_mods()
ctx = modsys.build(fs, en, log=print)
inst.install(fs, ctx)
print("done")
