#!/usr/bin/env python3
"""DRPGEVIL1b gate: the Skill.dat position budget of vanilla + a set of mod folders (offline, read-only).

    python tools/check_skill_budget.py MODS_DIR [MODS_DIR ...] [--game DIR] [--installed INSTALLED_MODS_DIR]

--installed (EVILFX2b, save safety): also REFUSE when any learnable row of the table made from INSTALLED_MODS_DIR
alone changes its Skill.dat position in the table made from all the MODS_DIRs (learned evilities are bits by position).
Typical: check_skill_budget.py "<kit>/mods" <build>/mods --installed "<kit>/mods".
ponytail: every folder with a mod.json counts, enabled or not, on both sides; read the profile's load order if a
disabled folder ever carries Skill rows that matter.

Merges the clean game's Skill.dat with every `<mod>/patches/db/Skill.dat.json` `added` row under the given
folders (a later folder of the same name replaces an earlier one, so "installed mods, then a build" measures
the table after that build is installed) and applies d5lib.learned.budget.  Exit 1 when a LEARNABLE row would
land past the 1,000-position learned bitmap, when the shop array would overflow, or on an id a unit record
cannot hold; a warning at 95 % of the bitmap.  SKILLTRAINERCRASH1: also exit 1 on every row learned.mastery_faults
finds (the Skill Shop crash at 0x1407CDA94).  The installer repairs kind-1 rows of that list itself and refuses kind 0.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
GAME = "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)"


def main(argv):
    from d5lib import database, gamefs, learned
    game = GAME
    if "--game" in argv:
        i = argv.index("--game")
        game = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    installed = None
    if "--installed" in argv:
        i = argv.index("--installed")
        installed = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    table = database.load_table("Skill.dat", gamefs.GameFS(game).read("Database/Database_0.dat/Skill.dat"))
    vanilla = {int(r["id"]): r.to_dict() for r in table.rows}

    def merged(roots):
        rows, folders = dict(vanilla), {}
        for root in roots:
            for d in sorted(Path(root).resolve().iterdir()):
                if (d / "mod.json").is_file():
                    folders[d.name] = d
        for d in folders.values():
            f = d / "patches/db/Skill.dat.json"
            if f.is_file():
                for r in json.loads(f.read_text()).get("added") or []:
                    rows[int(r["id"])] = r
        return rows, folders

    rows, folders = merged(argv)
    b = learned.budget(rows.values())
    print(f"Skill.dat: {b['total']} rows from vanilla + {len(folders)} mod folder(s); bitmap positions left "
          f"{b['positions_left']}; past the bitmap: {len(b['learnable_past'])} learnable, {b['innate_past']} innate-only; "
          f"shop rows {b['shop_rows']}/{learned.SHOP_ARRAY}")
    for w in b["warnings"]:
        print("WARN " + w)
    if installed:
        mv = learned.moved(merged([installed])[0].values(), rows.values())
        print(f"save safety: {len(mv)} installed learnable row(s) change position")
        if mv:
            b["errors"].append(f"{len(mv)} installed learnable evility row(s) would change Skill.dat position (learned bits "
                               f"in saves are by position); first: id {mv[0][0]} {mv[0][1]} -> {mv[0][2]}. Give the new "
                               f"row an id in the late band (ownership manifest 27000-27999 D4, 26300-26999 DD2)")
    ranks = {int(r["id"]) for r in database.load_table(
        "JobRank.dat", gamefs.GameFS(game).read("Database/Database_0.dat/JobRank.dat")).rows}
    for d in folders.values():
        f = d / "patches/db/JobRank.dat.json"
        if f.is_file():
            ranks |= {int(r["id"]) for r in json.loads(f.read_text()).get("added") or []}
    faults = learned.mastery_faults(rows.values(), ranks)
    print(f"class-mastery shop rows without their JobRank row (Skill Shop crash): {len(faults)}")
    owner = {}
    for d in folders.values():
        f = d / "patches/db/Skill.dat.json"
        if f.is_file():
            owner.update({int(r["id"]): d.name for r in json.loads(f.read_text()).get("added") or []})
    b["errors"] += [f"evility {i} ({owner.get(i, 'vanilla')}): kind {k}, source 3, no JobRank row {key}" for i, k, key in faults]
    for e in b["errors"]:
        print("FAIL " + e)
    return 1 if b["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
