"""Share many mods at once: one zip per mod, one folder per game, importable by any other D5 Mod Kit.

    python tools/share_bulk.py export OUT_DIR [--games D1C,D4,DD2,DRPG,Overlord,Other] [--enabled-only]
                               [--only GLOB[,GLOB...]] [--author NAME] [--no-closure] [--stamp-uids] [--mods-dir DIR]
    python tools/share_bulk.py import FOLDER [--games D4,...] [--mods-dir DIR] [--game-dir DIR]

export never changes your mods (a mod without a uid gets a derived one inside the package; --stamp-uids saves it
into mod.json instead).  import needs the vanilla game files (read only) to move clashing ids; --game-dir overrides
the Steam lookup.  See docs/SHARING.md and d5lib/modbulk.py.
"""
import argparse
import json
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import modbulk, modsys  # noqa: E402


def _csv(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _kit_of(mods_dir):
    return os.path.dirname(os.path.abspath(mods_dir.rstrip("/\\")))


def cmd_export(a):
    mods_dir = a.mods_dir or os.path.join(KIT, "mods")
    mm = modsys.ModManager(_kit_of(mods_dir))
    rep = modbulk.export_all(mm.all_mods(), a.out_dir, games=_csv(a.games), only_enabled=a.enabled_only,
                             author=a.author, only=_csv(a.only), stamp_uids=a.stamp_uids,
                             enabled_ids={m.id for m in mm.enabled_mods()}, closure=not a.no_closure,
                             pack_games=modbulk.load_pack_games(mm.mods_dir), log=print if a.verbose else (lambda s: None))
    for g, n in sorted(rep["games"].items()):
        size = sum(e["size"] for e in rep["exported"] if e["game"] == g)
        print(f"{g}: {n} mods, {size / 1048576:.1f} MB")
    for s in rep["skipped"]:
        print(f"skipped {s['id']} ({s['game']}): {s['reason']}")
    print(f"{len(rep['exported'])} exported, {len(rep['skipped'])} skipped; {rep['uid_unstored']} had no stored uid "
          f"(derived{', now stamped' if a.stamp_uids else ', source mods unchanged'}) -> {a.out_dir}")
    return 0


def cmd_import(a):
    from d5lib import paths
    from d5lib.gamefs import GameFS
    mods_dir = a.mods_dir or os.path.join(KIT, "mods")
    kit = _kit_of(mods_dir)
    game = a.game_dir or paths.require_game_dir()
    inst = modsys.Installer(game, os.path.abspath(a.kit_dir or KIT), log=lambda *x: None)
    fs = GameFS(game, backup_resolver=inst.backup_resolver)
    os.makedirs(mods_dir, exist_ok=True)
    s = modbulk.import_folder(a.folder, os.path.abspath(mods_dir), fs, os.path.join(kit, "state"),
                              log=print if a.verbose else (lambda x: None), games=_csv(a.games))
    print(json.dumps({k: (v if k in ("failed", "repointed", "missing_requires", "renamed") else
                          (len(v) if isinstance(v, (list, dict)) else v)) for k, v in s.items()}, indent=2))
    return 1 if s["failed"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("out_dir")
    e.add_argument("--games")
    e.add_argument("--enabled-only", action="store_true")
    e.add_argument("--only", help="comma-separated globs on mod folder ids, e.g. DRPG_Core_*")
    e.add_argument("--author")
    e.add_argument("--no-closure", action="store_true", help="do not add mods that chosen mods require")
    e.add_argument("--stamp-uids", action="store_true", help="save derived uids into the source mod.json files")
    e.add_argument("--mods-dir")
    e.add_argument("-v", "--verbose", action="store_true")
    e.set_defaults(fn=cmd_export)
    i = sub.add_parser("import")
    i.add_argument("folder")
    i.add_argument("--games")
    i.add_argument("--mods-dir")
    i.add_argument("--game-dir")
    i.add_argument("--kit-dir", help="kit whose state/ holds the vanilla backups (default: this kit)")
    i.add_argument("-v", "--verbose", action="store_true")
    i.set_defaults(fn=cmd_import)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
