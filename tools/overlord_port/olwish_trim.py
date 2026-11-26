"""OLCONV2: the OLWISH1 bill mod without the bills whose characters now live in their own packs.

OLWISH1's "Overlord Recruit Wishes" lists 14 bills.  Five recruit characters by Overlord's row ids (20000 Battle Suit,
20010 Android, 20300 Stella, 20310 Rutile, 20500 Majin).  After OLCONV2 Stella / Rutile / Majin are packs that carry
their own bill on a leased identity, and Battle Suit / Android are not converted (D4_Class_1190 / 1200 stand for them,
DECISIONS 2026-11-19), so those five bills would recruit a class row that does not exist.  This writes the other nine
(2049..2057, the repurposed vanilla NPCs; their retune lives in Overlord Rebalance, which stays off).

  python tools/overlord_port/olwish_trim.py --out <dir>      (reads the release's own WishDataBase.dat and custom_wishes.txt)
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.dont_write_bytecode = True

from d5lib import database, wishrecruit  # noqa: E402
from tools.overlord_port import recruit_wishes as RW  # noqa: E402

RELEASE = Path("/Volumes/Data/ai-tmp/claude/overlord-v3")
DROP = (20000, 20010, 20300, 20310, 20500)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    table = RW.parse_custom_wishes((RELEASE / "mods/_loader/custom_wishes.txt").read_text(encoding="utf-8"))
    table = {k: v for k, v in table.items() if k not in DROP}
    rows = [r.to_dict() for r in database.load_table(
        "WishDataBase.dat", (RELEASE / "mods/Overlord/Database/Database_0/WishDataBase.dat").read_bytes()).rows
        if r["id"] in table]
    kit_rows, recruits, report = RW.convert_rows(rows, table)
    out = Path(a.out)
    (out / "patches/db").mkdir(parents=True, exist_ok=True)
    (out / "patches" / wishrecruit.FOLDER).mkdir(parents=True, exist_ok=True)
    (out / "patches/db/WishDataBase.dat.json").write_text(
        json.dumps({"table": "WishDataBase.dat", "added": kit_rows}, ensure_ascii=False, indent=1, sort_keys=True,
                   default=lambda o: o.hex() if isinstance(o, bytes) else str(o)))
    (out / "patches" / wishrecruit.FOLDER / wishrecruit.DATA_FILE).write_text(json.dumps(recruits, indent=1))
    (out / "mod.json").write_text(json.dumps({
        "name": "Overlord Recruit Wishes", "author": RW.CREDIT, "version": "0.0.3-converted",
        "description": ("his nine recruit wishes for the repurposed vanilla NPCs (bills 1049..1057 re-keyed to "
                        "2049..2057, his required flag in req_flag1). Stella, Rutile and Majin carry their own bill "
                        "in their packs; Battle Suit and Android are not converted. Needs the kit's wishrecruit hooks."),
        "enabled_by_default": False}, indent=1))
    for b in report["bills"]:
        print(f"{b['overlord_bill']:>6} -> {b['kit_bill']:>6}  char {b['character']:>5} lv {b['level']:>4} req_flag1 {b['req_flag1']}")


if __name__ == "__main__":
    main()
