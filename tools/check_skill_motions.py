"""Check every learned skill's caster motions against the unit's battle bank (d5lib/skillmotions.py).

    python tools/check_skill_motions.py MODS_DIR [MODS_DIR ...] [--json OUT] [-v]

Prints units / skills checked / missing-motion pairs / unknown per game prefix (D1C, D4, DD2, DRPG, other).
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import skillmotions  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mods", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    folders = sorted(p for root in a.mods for p in root.iterdir() if (p / "mod.json").is_file())
    sv = skillmotions.Survey(skill_roots=folders)
    tab = collections.defaultdict(lambda: collections.Counter())
    recs = []
    for mod in folders:
        g = mod.name.split("_")[0]
        g = g if g in ("D1C", "D4", "DD2", "DRPG") else "other"
        units = set()
        for r in sv.check_mod(mod):
            recs.append(r)
            units.add(r["unit"])
            tab[g]["skills"] += 1
            tab[g][r["status"]] += 1
            if r["status"] == "missing" and a.v:
                print(mod.name, r["unit"], r["skill"], r["missing"])
        tab[g]["units"] += len(units)
        tab[g]["mods"] += 1
    print("game  mods units skills ok fallback missing unknown")
    for g in sorted(tab):
        t = tab[g]
        print(f"{g:5} {t['mods']:4} {t['units']:5} {t['skills']:6} {t['ok']:3} {t['fallback']:8} {t['missing']:7} {t['unknown']:7}")
    if a.json:
        a.json.write_text(json.dumps(recs, indent=1, default=list) + "\n")


if __name__ == "__main__":
    main()
