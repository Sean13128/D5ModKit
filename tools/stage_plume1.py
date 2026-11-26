#!/usr/bin/env python3
"""Stage only Plume's table changes over a read-only installed pack (offline).

python tools/stage_plume1.py OUT_DIR BASE_MODS
Copies the pack first, records game_truth --staged before/after, checks the base
hashes again, and refuses any changed file outside the reviewed table set.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
FOLDER = "DD2_Unique_570"
ALLOWED = {"mod.json", "patches/db/Skill.dat.json", "patches/db/char.dat.json",
           "patches/evilities/evilities.json"}


def hashes(pack):
    return {str(p.relative_to(pack)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(pack.rglob("*")) if p.is_file()}


def main(argv):
    from d5lib.importers import _dd2_innates
    out, base_mods = map(lambda p: Path(p).resolve(), argv)
    base, dest = base_mods / FOLDER, out / "mods" / FOLDER
    if not (base / "mod.json").is_file() or dest.exists():
        raise SystemExit("base missing or destination already exists")
    before = hashes(base)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-cR", str(base), str(dest)], check=True)
    if hashes(dest) != before:
        raise SystemExit("copy differs from base")
    truth = [sys.executable, str(KIT / "tools/game_truth.py"), "--mods", str(base_mods),
             "--staged", str(dest.parent), "--only", FOLDER, "-v"]
    # The missing innate is the baseline defect this overlay fixes (exit 1 expected).
    baseline = subprocess.run(truth + ["--json", str(out / "truth-before.json")])
    if baseline.returncode not in (0, 1):
        raise SystemExit(f"before truth failed to run: {baseline.returncode}")
    note = _dd2_innates.apply(dest, FOLDER)
    ok, why = _dd2_innates.gate(dest, FOLDER)
    if not ok:
        raise SystemExit(why)
    after = hashes(dest)
    differ = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if set(differ) - ALLOWED:
        raise SystemExit(f"files outside the table set differ: {differ}")
    if hashes(base) != before:
        raise SystemExit("read-only base changed during staging")
    subprocess.run(truth + ["--json", str(out / "truth-after.json")], check=True)
    receipt = dict(lane="PLUME1", base=str(base), pack=FOLDER, note=note, gate=why,
                   differ=differ, installed_unchanged=True, installed_hashes=before, staged_hashes=after)
    (out / "STAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(FOLDER, differ, why)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
