#!/usr/bin/env python3
"""Catalog D4 installed content and static references; write metadata outside the repository."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
from d5lib import d4inventory, offlinepaths  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--d4", type=Path, required=True)
    ap.add_argument("--lang", default="EN")
    ap.add_argument("--output", type=Path, required=True, help="new metadata file outside the source repository/game")
    ap.add_argument("--progress", type=Path, help="separate evidence ledger; never overwritten")
    ap.add_argument("--allocations", type=Path, help="JSON object with allocations and occupied namespace snapshots")
    args = ap.parse_args(argv)
    try:
        out = offlinepaths.offline_output(args.output, (REPOSITORY, args.d4, args.progress, args.allocations))
    except ValueError as exc:
        ap.error(str(exc))
    if out.exists():
        ap.error("output already exists; choose a new path to preserve prior evidence")
    data = d4inventory.build_inventory(args.d4, args.lang)
    if args.progress:
        d4inventory.apply_progress(data, json.loads(args.progress.read_text()))
    if args.allocations:
        plan = json.loads(args.allocations.read_text())
        errors = d4inventory.validate_allocations(plan["allocations"], plan.get("occupied"))
        data["allocation_validation"] = dict(errors=errors, native_support="not-asserted", leases="not-created")
        if errors:
            ap.error(f"unsafe target allocations: {json.dumps(errors)}")
    data["tool_provenance"] = {
        str(p.relative_to(REPOSITORY)): dict(sha256=d4inventory.hash_range(p))
        for p in (REPOSITORY / "d5lib/d4inventory.py", REPOSITORY / "tools/d4_inventory.py",
                  REPOSITORY / "d5lib/d4source.py", REPOSITORY / "d5lib/script.py",
                  REPOSITORY / "d5lib/fafs.py", REPOSITORY / "d5lib/sound.py",
                  Path(offlinepaths.__file__))
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x") as f:
        json.dump(data, f, indent=1, ensure_ascii=True, allow_nan=False)
        f.write("\n")
    print(json.dumps(dict(output=str(out), **data["summary"]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
