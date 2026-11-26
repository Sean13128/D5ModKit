#!/usr/bin/env python3
"""GAMETRUTH1 (gametruth1b): what will the game do with each installed pack?  Offline, read-only.

    D5Modkit/.venv-macos/bin/python tools/game_truth.py [--game G] [--mods M] [--save SAVE_COPY]
        [--only A,B] [--folder-mode] [--json OUT] [-v]
    D5Modkit/.venv-macos/bin/python tools/game_truth.py --regress [--json OUT]

Per pack and check: PASS / FAIL / NOT MODELLED / N/A, the decompiled function it rests on and whether that function
is executed under Unicorn or its rule re-implemented (d5lib/gametruth.py).  Pass a COPY of a save for the Quest Shop
board check.  --folder-mode reads banks/rows from the folders (pre-fix folders in Local/kit-backups).  --regress runs
the labelled set of 2026-11-10 (tools/game_truth_regress.py).  Exit 1 when an enabled pack FAILs.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True


def main(argv=None):
    from d5lib import gametruth as gt
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", type=Path, default=gt.GAME)
    ap.add_argument("--mods", type=Path)
    ap.add_argument("--save", type=Path)
    ap.add_argument("--only")
    ap.add_argument("--folder-mode", action="store_true")
    ap.add_argument("--staged", type=Path, nargs="+", help="EVILFX3: simulate an install of these mods dirs over --mods "
                    "(folder mode; the last dir that has a pack wins)")
    ap.add_argument("--no-survey", action="store_true")
    ap.add_argument("--regress", action="store_true")
    ap.add_argument("--json", type=Path)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    if a.regress:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import game_truth_regress
        return game_truth_regress.main(a.json)
    if a.staged:
        import tempfile
        installed = a.mods or a.game / "D5ModKit" / "mods"
        view = gt.staged_view(Path(tempfile.mkdtemp(prefix="gametruth-staged-")) / "mods", installed, *a.staged)
        w = gt.World(a.game, view, save=a.save, folder_mode=True,
                     load_order=installed.parent / "profiles" / "MAIN" / "load_order.json")
        gt.add_staged_skill(w)
    else:
        w = gt.World(a.game, a.mods, save=a.save, folder_mode=a.folder_mode)
    rs = gt.run(w, only=set(a.only.split(",")) if a.only else None, survey=not a.no_survey)
    tab = collections.defaultdict(collections.Counter)
    modes = collections.defaultdict(collections.Counter)
    for r in rs:
        for c in r.checks:
            tab[c.name][c.status] += 1
            modes[c.name][c.mode] += 1
            if a.v or c.status == "FAIL":
                print(f"{c.status:12} {r.pack:42} {c.name:30} {c.why[:150]}")
    print(f"\n{'check':32} {'PASS':>5} {'FAIL':>5} {'NOT MOD':>7} {'N/A':>5}  mode")
    for name, n in tab.items():
        print(f"{name:32} {n['PASS']:5} {n['FAIL']:5} {n['NOT MODELLED']:7} {n['N/A']:5}  {', '.join(f'{m} {k}' for m, k in modes[name].items())}")
    # FIXUP1: exit 0 permits NOT MODELLED; say what is pending so a green run is not read as battle acceptance
    pend = {n: c["NOT MODELLED"] for n, c in tab.items() if c["NOT MODELLED"]}
    print("\nPENDING COVERAGE (NOT MODELLED, not accepted):", ", ".join(f"{n} x{k}" for n, k in pend.items()) or "none")
    print("Live only, never covered here: battle entry, normal attacks, skill/evility effects in battle, audible sound, timing/freezes.")
    if a.json:
        a.json.write_text(json.dumps(gt.to_json(rs), indent=1) + "\n")
    return 1 if any(r.worst() == "FAIL" and r.enabled for r in rs) else 0


if __name__ == "__main__":
    sys.exit(main())
