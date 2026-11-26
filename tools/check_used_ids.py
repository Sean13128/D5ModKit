#!/usr/bin/env python3
"""Run the LEASEGATE1 used-id gate on built mod folders (offline, read-only).

    python tools/check_used_ids.py MODS_DIR [MODS_DIR ...] [--extra-roots DIR ...] [--only A,B] [--no-siblings]

Every folder under each MODS_DIR is checked against vanilla, every importer's recorded lease (except its own
folder's) and every other mod folder under the installed mods, the extra roots and the other MODS_DIRs.
Exit 1 on any collision.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = GAME / "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mods", nargs="+", type=Path)
    ap.add_argument("--extra-roots", nargs="*", type=Path, default=[])
    ap.add_argument("--only")
    ap.add_argument("--no-siblings", action="store_true", help="do not count the other MODS_DIRs as roots")
    a = ap.parse_args(argv)
    from d5lib import importcore
    roots = importcore.default_extra_roots([*a.extra_roots, *([] if a.no_siblings else a.mods)])
    used = importcore.UsedIds(GAME, STATE, roots)
    only = set(filter(None, (a.only or "").split(",")))
    bad = n = 0
    for d in a.mods:
        for f in sorted(d.iterdir()):
            if (f / "mod.json").is_file() and (not only or f.name in only):
                ok, why = used.check(f)
                n += 1
                bad += not ok
                print(f"{'ok  ' if ok else 'FAIL'} {f.name}{': ' + why if why else ''}", flush=True)
    print(f"{n} folder(s), {bad} with collisions")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
