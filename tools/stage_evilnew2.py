#!/usr/bin/env python3
"""EVILNEW2: stage the packs whose innate evility link changes, table files only (offline).

    python tools/stage_evilfx3.py OUT_DIR BASE_MODS [BASE_MODS ...]

A pack is cloned (APFS clone) from the FIRST base that has it (e.g. tonight's combined stage, then the installed
mods), and the importers' own steps are run on the clone: d1c.apply_donor_evility, _dd2_innates.apply,
d4.Importer._reviewed_evilities.  Anything but the table files differing from the base stops the run.
Writes OUT_DIR/STAGE-RECEIPT.json.  The bases are only read.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
ALLOWED = ("mod.json", "patches/db/Skill.dat.json", "patches/db/char.dat.json", "patches/evilities/evilities.json",
           "patches/evilities/aliases.json", "patches/classes/")
D4 = ("D4_Unique_440",)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv):
    from d5lib.importers import _dd2_innates, d1c, d4
    out, bases = Path(argv[0]), [Path(b).resolve() for b in argv[1:]]
    todo = [(f, "d4") for f in D4]
    (out / "mods").mkdir(parents=True, exist_ok=True)
    receipt = dict(lane="EVILNEW2", bases=[str(b) for b in bases], packs=[])
    for folder, kind in sorted(todo):
        base = next((b / folder for b in bases if (b / folder / "mod.json").is_file()), None)
        if base is None:
            raise SystemExit(f"{folder}: in no base")
        dest = out / "mods" / folder
        if dest.exists():
            raise SystemExit(f"{dest} exists; stage into an empty folder")
        subprocess.run(["cp", "-cR", str(base), str(dest)], check=True)
        if kind == "d1c":
            note = d1c.apply_donor_evility(dest, folder)
        elif kind == "dd2":
            note = _dd2_innates.apply(dest, folder)
        else:
            note = d4.Importer._reviewed_evilities(SimpleNamespace(mod_folder=folder), dest)
        a = {str(p.relative_to(base)): p for p in base.rglob("*") if p.is_file()}
        b = {str(p.relative_to(dest)): p for p in dest.rglob("*") if p.is_file()}
        differ = sorted(k for k in a.keys() | b.keys() if k not in a or k not in b or sha(a[k]) != sha(b[k]))
        bad = [k for k in differ if not k.startswith(ALLOWED)]
        if bad:
            raise SystemExit(f"{folder}: files outside the table set differ: {bad}")
        rows = json.loads((dest / "patches/db/char.dat.json").read_text())["added"]
        if any(not r.get("evility1") for r in rows):
            raise SystemExit(f"{folder}: a char row still links no evility")
        receipt["packs"].append(dict(folder=folder, kind=kind, base=str(base.parent), note=note, differ=differ,
                                     links=sorted({r["evility1"] for r in rows}), char_rows=len(rows)))
        print(folder, differ)
    (out / "STAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    print(len(receipt["packs"]), "packs staged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
