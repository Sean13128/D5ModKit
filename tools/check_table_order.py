"""Check the id order (and the known-evility bitset cap) of the database the game will load.

    python tools/check_table_order.py --database "<game>/Data/Database/Database_0.dat"
    python tools/check_table_order.py --database <built> --vanilla <pristine Database_0.dat>

Exit 1 when a table the game searches by id is out of order -- the state that makes ids unreachable
for the game's binary search (see d5lib.ordercheck).  Read-only: opens the archive, reports, writes
nothing.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import database, ordercheck  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database", required=True, type=Path)
    ap.add_argument("--vanilla", type=Path, help="a pristine Database_0.dat (default: trust the table list)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    db = database.load_database(str(a.database))
    vanilla = database.load_database(str(a.vanilla)) if a.vanilla else None
    bad = 0
    for member in ordercheck.ORDER_CRITICAL:
        logical = db[member].to_bytes()
        van = vanilla[member].to_bytes() if vanilla is not None else None
        found = ordercheck.findings(member, logical, vanilla=van)
        rows = len(db[member].rows)
        ids = [r["id"] for r in db[member].rows]
        inv = sum(1 for i in range(len(ids) - 1) if ids[i] > ids[i + 1])
        if not a.quiet:
            print(f"{member}: {rows} rows, {inv} inversion(s), bitset cap {ordercheck.BITSET_CAP}")
        for f in found:
            print("ERROR " + f)
        bad += len(found)
    if not a.quiet:
        print("0 finding(s)" if not bad else f"{bad} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
