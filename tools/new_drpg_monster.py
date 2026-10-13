"""New generic monster from a Disgaea RPG monster (docs/MONSTERS.md).

  python tools/new_drpg_monster.py --list                         DRPG monsters D5 lacks + usable templates
  python tools/new_drpg_monster.py suggest UID TEMPLATE POSES.json [SHEET.png]
        pair the new monster's poses with the template twin's (by role and shape) and draw the pairing; check the
        sheet and fix POSES.json by hand where a pose is wrong ("front:<twin key>": "front:<new key>")
  python tools/new_drpg_monster.py create UID TEMPLATE "Name" POSES.json [--titles "T1,..,T6"] [--desc "..."]
"""
import argparse
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import modsys, monstermap, newclasses  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

GAME = paths.require_game_dir()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", choices=["suggest", "create"])
    p.add_argument("args", nargs="*")
    p.add_argument("--list", action="store_true")
    p.add_argument("--titles")
    p.add_argument("--desc", default="")
    a = p.parse_args()
    if a.list or not a.cmd:
        print("new DRPG monsters:", ", ".join(f"{u} {n}" for u, n in monstermap.NEW.items()))
        print("templates (vanilla monsters with a twin map):", monstermap.templates())
        return
    inst = modsys.Installer(GAME, KIT, log=lambda *x: None)
    fs = GameFS(GAME, backup_resolver=inst.backup_resolver)
    if a.cmd == "suggest":
        uid, tmpl, out = int(a.args[0]), int(a.args[1]), a.args[2]
        rp = monstermap.role_path(uid)
        if os.path.exists(rp):          # poses by role (d5lib/data/monster_roles/<uid>.json): far better than shape
            pairs = monstermap.pairs_from_roles(fs, tmpl, uid, monstermap.load_roles(rp), log=print)
            print(f"paired by the role file {rp}")
        else:
            pairs = monstermap.suggest(fs, tmpl, uid)
            print(f"no role file {rp}: paired by shape only. Write one (docs/MONSTERS.md) for a better pairing.")
        monstermap.save_pairs(pairs, out)
        if len(a.args) > 3:
            monstermap.pose_sheet(fs, tmpl, uid, pairs, a.args[3])
        print(f"{len(pairs)} pose pairs -> {out}")
    else:
        uid, tmpl, name, poses = int(a.args[0]), int(a.args[1]), a.args[2], a.args[3]
        mm = modsys.ModManager(KIT)
        titles = a.titles.split(",") if a.titles else None
        mod = newclasses.create_monster(fs, mm, uid, tmpl, name, monstermap.load_pairs(poses), titles=titles,
                                        hire_desc=a.desc)
        print("mod", mod.id)
        print(f"check it: python tools/qa_sprite.py mods/{mod.id}/files/Anime/ANM_HI_JP.dat/anm{mod_family(mod):05d}.lzs "
              f"{tmpl}")


def mod_family(mod):
    return int(newclasses.load_specs(mod)[0]["family"])


if __name__ == "__main__":
    main()
