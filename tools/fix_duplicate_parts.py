#!/usr/bin/env python3
"""DEATH2: apply the converter's duplicate-part rule to built class packs (art only).

    python tools/fix_duplicate_parts.py --check  [--mods DIR]
    python tools/fix_duplicate_parts.py --out DIR [--mods DIR] [--only NAME ...]

The rule lives in `d5lib.ownanim.duplicate_items` and now runs inside `ownanim.build()`, so a rebuild of a
pack applies it.  This tool is the same function applied to the packs already on disk: it loads each
class sprite bank (anm<family>, and anm<family+1> when it carries its own pictures), blanks the keys whose
drawing item paints no new ink, and writes only the banks that changed into --out (a mods-root overlay).
Every other file is untouched: the changed unit is exactly one `.lzs` per changed bank.

Read-only on its input; writes only under --out.  Never touches the game or the installed kit.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from d5lib import anm as A          # noqa: E402
from d5lib import ownanim           # noqa: E402


def banks_of(mod: Path):
    d = mod / "files" / "Anime" / "ANM_HI_JP.dat"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(glob.glob(str(d / "anm0*.lzs"))):
        name = os.path.basename(p)
        if name[3:8].isdigit():
            out.append(Path(p))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mods", default="/Volumes/Data/Projects/D5/Builds/LIVE5_TEST16-20261030/mods")
    ap.add_argument("--out")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    mods = Path(a.mods)
    changed = []
    for mod in sorted(mods.iterdir()):
        if not mod.is_dir() or (a.only and mod.name not in a.only):
            continue
        for bank in banks_of(mod):
            sprite = A.load(str(bank))
            receipt = ownanim.duplicate_items(sprite)
            if not receipt:
                continue
            changed.append((mod.name, bank.name, receipt))
            print("%-22s %-12s %s" % (mod.name, bank.name,
                                      ", ".join("anim %d t=%d node %d cell %d" % r for r in receipt)))
            if not a.check:
                dest = Path(a.out) / mod.name / "files/Anime/ANM_HI_JP.dat" / bank.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(A.lzs_compress(sprite.to_bytes()))
    print("%d bank(s) change%s" % (len(changed), "" if changed else " -- nothing to fix"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
