#!/usr/bin/env python3
"""DD2D1GAP1: stage the packs whose tracker signature / specials cell is a labelling gap, not a data gap (offline).

    python tools/stage_dd2d1gap1.py OUT_DIR BASE_MODS [BASE_MODS ...]

Each pack is cloned (APFS clone) from the FIRST base that has it (a queued build first, then the installed mods).
  * DD2 evility label (importers/_dd2_innates.apply, link only): Masked Hero, Shark Dragon, Alex, Pleinair, Pringer Z
    -> mod.json gets `source_import.innate_evility` and the exact / adapted line; no row, alias or link moves.
  * specials2 relabel (importers/specials2.relabel): Xenolith and Sardia (label N: ids the source has no row for),
    Masked Hero and Carter (source learn list empty: `source_has_none`).
Only mod.json may differ from the base; anything else stops the run.  Writes OUT_DIR/STAGE-RECEIPT.json.  Bases are read.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
EVIL = ("DD2_Class_22210", "DD2_Class_22680", "DD2_Unique_480", "DD2_Unique_320", "DD2_Unique_300")
SPEC = (("DD2_Class_22210", "dd2"), ("DD2_Unique_941", "dd2"), ("D1C_Unique_2410", "d1c"), ("D1C_Unique_6601", "d1c"))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv):
    from d5lib.importers import _dd2_innates, specials2
    out, bases = Path(argv[0]), [Path(b).resolve() for b in argv[1:]]
    (out / "mods").mkdir(parents=True, exist_ok=True)
    spec = dict(SPEC)
    receipt = dict(lane="DD2D1GAP1", bases=[str(b) for b in bases], packs=[])
    for folder in sorted(set(EVIL) | set(spec)):
        base = next((b / folder for b in bases if (b / folder / "mod.json").is_file()), None)
        if base is None:
            raise SystemExit(f"{folder}: in no base")
        dest = out / "mods" / folder
        if dest.exists():
            raise SystemExit(f"{dest} exists; stage into an empty folder")
        subprocess.run(["cp", "-cR", str(base), str(dest)], check=True)
        notes = []
        if folder in EVIL:
            before = (dest / "patches/db/char.dat.json").read_bytes()
            notes.append(_dd2_innates.apply(dest, folder))
            ok, why = _dd2_innates.gate(dest, folder)
            if not ok:
                raise SystemExit(f"{folder}: {why}")
            cd = dest / "patches/db/char.dat.json"
            if json.loads(cd.read_bytes()) == json.loads(before):       # re-serialised only: keep the base bytes
                cd.write_bytes(before)
        if folder in spec:
            plan = specials2.plan_mod(spec[folder], dest)
            notes.append(f"specials2 relabel: {specials2.relabel(dest, plan)}")
        a = {str(p.relative_to(base)): p for p in base.rglob("*") if p.is_file()}
        b = {str(p.relative_to(dest)): p for p in dest.rglob("*") if p.is_file()}
        differ = sorted(k for k in a.keys() | b.keys() if k not in a or k not in b or sha(a[k]) != sha(b[k]))
        if differ != ["mod.json"]:
            raise SystemExit(f"{folder}: expected only mod.json to differ, got {differ}")
        receipt["packs"].append(dict(folder=folder, base=str(base.parent), notes=notes, differ=differ))
    (out / "STAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=1) + "\n")
    for p in receipt["packs"]:
        print(p["folder"], "<-", Path(p["base"]).parent.name, "|", "; ".join(p["notes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
