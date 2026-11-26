#!/usr/bin/env python3
"""SPECDIAG1: what a live test of a special must set up.  Offline, read-only.

    D5Modkit/.venv-macos/bin/python tools/special_recipe.py SKILL_ID [SKILL_ID ...] [--game G]

Prints per magic.dat row of the installed game: SP, kind and where the target has to stand
(x sideways, y forward of the caster's facing, in panels; range 0 = shape placed from the caster)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True


def recipe(row, shape_map):
    from d5lib import skillarea
    a = skillarea.area_of(row, shape_map)
    hit = [(x, y) for x, y, k in a.cells if k != skillarea.USER_TO]
    if int(row["skill_type"]) == 2 and int(row["rank"]) == 1 and a.shape in (1, 1000):
        need = "Geo/Bonus utility, 'Item World only' by its own text: needs an Item World stage, not a normal battle"
    elif a.range > 0:
        need = (f"ranged single: target within {a.range} panels (Manhattan) and height {a.height_up} up/"
                f"{a.height_down} down; put the cursor on it, confirm, and check the Attack Entry list")
    else:
        need = f"from the caster: an enemy on one of the forward panels {hit} (shape {a.shape}); else 'No target.'"
    return f"{row['id']} {row['name_EN']}: SP {row['sp_cost']}, {need}"


def main(argv=None):
    from d5lib import database, gametruth as gt
    args = list(sys.argv[1:] if argv is None else argv)
    game = Path(args.pop(args.index("--game") + 1)) if "--game" in args else gt.GAME
    args = [a for a in args if a != "--game"]
    db = database.load_database(str(game / "Data/Database/Database_0.dat"))
    from d5lib import skillarea
    sm = skillarea.shapes(database.load_table("AttackMap.dat", db.raw["AttackMap.dat"]))
    rows = {int(r["id"]): r for r in database.load_table("magic.dat", db.raw["magic.dat"]).rows}
    for s in args:
        print(recipe(rows[int(s)], sm) if int(s) in rows else f"{s}: not in magic.dat")


if __name__ == "__main__":
    main()
