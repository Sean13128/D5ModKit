#!/usr/bin/env python3
"""Read-only: run the SCHEMA1 importcore gates over a folder of built mods and tabulate failures per game and gate.

    python tools/run_schema_gates.py [MODS_DIR] [--json OUT]

Default MODS_DIR = the held PLAYTEST-RESET packs.  Game = prefix of the folder name (D4, D1C, DD2, D2, DRPG).  The original
Database_0.dat (backup state) is read for magic.dat; nothing is written except the optional --json file.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from d5lib import importcore  # noqa: E402

HELD = Path("/Volumes/Data/Projects/D5/Local/mods-holding/20261108-PLAYTEST-RESET/mods")
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = GAME / "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mods", nargs="?", type=Path, default=HELD)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    ids = importcore.magic_ids(a.mods, GAME, STATE)
    if ids is None:
        sys.exit("original backup state not found")
    table = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))   # game -> gate -> [pass, fail]
    fails = collections.defaultdict(list)
    for mod in sorted(p for p in a.mods.iterdir() if (p / "mod.json").is_file()):
        game = mod.name.split("_")[0]
        for gate, (ok, why) in importcore.schema_gates(mod, ids).items():
            table[game][gate][0 if ok else 1] += 1
            if not ok:
                fails[gate].append(f"{mod.name}: {why}")
    gates = ["yield", "recruit_quest", "learn_skills"]
    print("game  packs  " + "  ".join(f"{g}(pass/fail)" for g in gates))
    for game in sorted(table):
        n = sum(table[game][gates[0]])
        print(f"{game:5} {n:5}  " + "  ".join(f"{table[game][g][0]:>6}/{table[game][g][1]:<6}" for g in gates))
    if a.json:
        a.json.write_text(json.dumps({"table": {g: dict(v) for g, v in table.items()}, "failures": fails}, indent=1) + "\n")


if __name__ == "__main__":
    main()
