"""VOICES2 staging: rebuild every D4 class and unique pack's voice bank from the D4 install.

Reads Builds/LIVE5_TEST15-20261029/mods (read only) and writes a new bundle's mods/ tree.
Class voice ids keep the 9000-9044 allocation; uniques take 9100-9120 (verified free).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import build_voices2_pack as B  # noqa: E402
from d5lib import d4source  # noqa: E402

CLASS_BASE_ID = 9000
UNIQUE_BASE_ID = 9100
UNIQUE_ORDER = [10, 20, 30, 40, 50, 60, 80, 170, 180, 190, 210, 230, 240, 250,
                300, 310, 320, 340, 350, 360, 490, 500]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", type=Path, required=True, help="TEST15 mods folder (read only)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    d4 = d4source.D4Data(B.D4, "EN")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    classes = sorted(p for p in args.mods.iterdir() if p.is_dir() and p.name.startswith("D4_Class_"))
    if len(classes) != 45:
        raise SystemExit(f"expected 45 class packs, found {len(classes)}")
    inventory = []
    for i, pack in enumerate(classes):
        vid = CLASS_BASE_ID + i
        rec = B.build(pack, out / pack.name, vid, d4)
        inventory.append(rec)
        print(pack.name, "->", vid, "clips", sum(len(r["clips"]) for r in rec["receipts"]))
    for row in UNIQUE_ORDER:
        pack = args.mods / f"D4_Unique_{row}"
        if not pack.is_dir():
            print("missing unique pack", pack)
            continue
        vid = UNIQUE_BASE_ID + UNIQUE_ORDER.index(row)
        try:
            rec = B.build(pack, out / pack.name, vid, d4)
        except Exception as ex:
            print("FAILED", pack.name, ex)
            inventory.append(dict(pack=pack.name, error=str(ex)))
            continue
        inventory.append(rec)
        print(pack.name, "->", vid, "clips", sum(len(r["clips"]) for r in rec["receipts"]))
    pilot = args.mods / "D4_ArmorKnight_1080_PILOT"
    if pilot.is_dir():
        rec = B.build(pilot, out / pilot.name, 9122, d4)
        inventory.append(rec)
        print(pilot.name, "->", 9122, "clips", sum(len(r["clips"]) for r in rec["receipts"]))
    (out.parent / "VOICES2-INVENTORY.json").write_text(json.dumps(inventory, indent=1))
    print("packs built:", len(inventory))


if __name__ == "__main__":
    main()
