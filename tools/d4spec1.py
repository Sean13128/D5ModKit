#!/usr/bin/env python3
"""D4SPEC1: relabel the D4 packs whose tracker `specials` cell is partial/missing for a reason that is not a data gap.

    D5Modkit/.venv-macos/bin/python tools/d4spec1.py census OUT_DIR [--mods DIR]      table of the 29 (read-only)
    D5Modkit/.venv-macos/bin/python tools/d4spec1.py stage  OUT_MODS [--mods DIR]     clone + relabel changed packs

Only mod.json's `specials2` block is rewritten (importers/specials2.relabel): no table row, learn list or art moves.
Offline, read-only on the installed kit and on Disgaea Source.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
BASE = Path("/Volumes/Data/Projects/D5")
INSTALLED = BASE / "Local/Installed D5ModKit/mods"
TRACKER = BASE / "Reports/tracker/items.csv"


def targets():
    with open(TRACKER) as f:
        return [(r["name"], r["mod_folder"], r["specials"]) for r in csv.DictReader(f)
                if r["game"] == "D4" and r["specials"] in ("partial", "missing")]


def classify(plan):
    """(why, counts) in the report's vocabulary."""
    c = {k: sum(e["label"] == k for e in plan["entries"]) for k in "EAHN"}
    held = [e for e in plan["entries"] if e["label"] == "H"]
    kinds = []
    if any("Magichange" in n for e in held for n in e["notes"]):
        kinds.append("Magichange (DECISIONS 2026-10-29)")
    if any("not damage" in n for e in held for n in e["notes"]):
        kinds.append("non-damage effect, no D5 code")
    if any("shape" in n for e in held for n in e["notes"]):
        kinds.append("area shape with no faithful D5 shape")
    if any("formula class" in n for e in held for n in e["notes"]):
        kinds.append("heal-formula, no stand-in rule")
    if not plan["entries"]:
        kinds.append("source learn list empty: n/a by source")
    return kinds, c


def census(out, mods):
    from d5lib.importers import specials2
    rows = []
    for name, mod, cell in targets():
        p = specials2.plan_mod("d4", Path(mods) / mod)
        st = specials2.installed_state(Path(mods) / mod)
        kinds, c = classify(p)
        rows.append(dict(unit=name, mod=mod, tracker=cell, source_specials=[e.get("name") or f"id {e['src']}" for e in p["entries"]],
                         labels=c, installed_learn=len(st["learn"]), installed_pack_rows=len(st["magic"]),
                         remaining=kinds, plan=p))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "CENSUS-D4SPEC1.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str) + "\n")
    lines = ["| unit | pack | tracker | source specials | E/A/H/N | learn / pack rows | why open or closed |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r["labels"]
        lines.append(f"| {r['unit']} | {r['mod']} | {r['tracker']} | {len(r['source_specials'])}: {', '.join(r['source_specials']) or '(none)'} "
                     f"| {c['E']}/{c['A']}/{c['H']}/{c['N']} | {r['installed_learn']} / {r['installed_pack_rows']} | {'; '.join(r['remaining'])} |")
    (out / "CENSUS-D4SPEC1.md").write_text("\n".join(lines) + "\n")
    return rows


def stage(out_mods, mods):
    from d5lib.importers import specials2
    out_mods = Path(out_mods)
    out_mods.mkdir(parents=True, exist_ok=True)
    changed = {}
    for name, mod, cell in targets():
        src = Path(mods) / mod
        p = specials2.plan_mod("d4", src)
        dst = out_mods / mod
        if dst.exists():
            raise SystemExit(f"{dst} exists: stage into an empty folder")
        subprocess.run(["cp", "-cR", str(src), str(dst)], check=True)
        if specials2.relabel(dst, p):
            changed[mod] = [str(dst / "mod.json")]
        else:
            subprocess.run(["rm", "-rf", str(dst)], check=True)      # unchanged packs are not part of the build
    (out_mods.parent / "STAGE-D4SPEC1.json").write_text(json.dumps(changed, indent=1) + "\n")
    print(f"{len(changed)} packs relabelled: {', '.join(changed)}")
    return 0


def main(argv):
    mods = Path(argv[argv.index("--mods") + 1]) if "--mods" in argv else INSTALLED
    if argv[0] == "census":
        rows = census(argv[1], mods)
        print(len(rows), "units")
        return 0
    if argv[0] == "stage":
        return stage(argv[1], mods)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
