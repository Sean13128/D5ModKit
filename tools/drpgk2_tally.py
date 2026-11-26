#!/usr/bin/env python3
"""Tally the DRPG-K2 costume build batch: which of the 89 leased costume looks were built and contract-checked.

    python tools/drpgk2_tally.py --out <build out dir> [<more out dirs>] --json Builds/DRPGK2-<date>/batch.json

Reads only each run's `results.json` and the per-entry `build/*/receipt.json` the builder wrote.  A look counts as
BUILT only when its family build passed and its own art contract has no problems; every other look is reported with
its cause (the build's error, or the contract problems verbatim).  Nothing is inferred: a look whose family was not
built in this batch is NOT CHECKED, not PASS.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def looks_by_owner(leases):
    out = defaultdict(list)
    for c in leases["costumes"]:
        out[c["owner"]].append(c)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, nargs="+", required=True, help="import_game --out directories")
    ap.add_argument("--leases", type=Path, default=ROOT / "d5lib/importers/drpg-leases.json")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    leases = json.loads(args.leases.read_text())
    owner_looks = looks_by_owner(leases)
    built, failed, missing = {}, {}, {}
    for out in args.out:
        results = out / "drpg" / "results.json"
        if not results.is_file():
            continue
        for r in json.loads(results.read_text())["results"]:
            owner = r["id"]
            receipt_path = out / "drpg" / "build" / owner.replace(":", "-") / "receipt.json"
            receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
            contracts = {c["look"]: c for c in receipt.get("art_contracts") or []}
            if not r.get("built"):
                for look in owner_looks.get(owner, []):
                    failed[look["lease"]] = (r.get("error") or "build failed").splitlines()[0][:200]
                    built.pop(look["lease"], None)   # a later run supersedes an earlier outcome
                continue
            for look in owner_looks.get(owner, []):
                c = contracts.get(look["lease"].split(":")[-1]) or contracts.get(int(look["lease"].split(":")[-1]))
                if c is None:
                    # a built family whose costume was not declared in this run (e.g. an extra-look path)
                    failed[look["lease"]] = "built family has no art contract for this look"
                elif c.get("ok"):
                    built[look["lease"]] = c
                    failed.pop(look["lease"], None)  # rebuilt later and passed: the failure is stale
                else:
                    failed[look["lease"]] = "; ".join(c.get("problems") or [])[:300]
                    built.pop(look["lease"], None)
    for look in leases["costumes"]:
        if look["lease"] not in built and look["lease"] not in failed:
            missing[look["lease"]] = "not built in the runs given (120-minute batch cap)"
    causes = Counter()
    for why in failed.values():
        causes[why.split(":")[0]] += 1
    tally = dict(total=len(leases["costumes"]), built=len(built), failed=len(failed), not_checked=len(missing),
                 causes=dict(causes), looks=built, failures=failed, not_checked_looks=missing)
    print(f"{len(built)}/{tally['total']} costume looks built and art-contract-PASS; "
          f"{len(failed)} FAIL; {len(missing)} not built in this batch")
    for lease, why in sorted(failed.items()):
        print(f"  FAIL {lease}: {why}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(tally, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {args.json}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
