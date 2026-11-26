#!/usr/bin/env python3
"""Extract Disgaea 4 faces and cut-ins from your own D4 install (D4FACETOOL1).

    python tools/d4_extract_screen_art.py GAME_DIR OUT_DIR [--id N ...] [--all-palettes] [--refresh]

GAME_DIR is the Disgaea 4 Complete+ folder (or its Data / Data/DATA).  OUT_DIR gets character_id_<N>/face and /cutin
PNGs plus manifest.json; point the D4 importer at it.  Reads only WF.dat and ANM_HI.dat; writes only OUT_DIR.

OUT_DIR is the importer's shared cache, so the run takes the same per-folder lock and merges the previous receipt
(R4): a subset run adds its ids and keeps every other row, and a PNG already on disk is kept and re-hashed.  Pass
--refresh to deliberately replace the requested ids' PNGs with freshly extracted bytes.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import d4screenart  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("game")
    ap.add_argument("out")
    ap.add_argument("--id", type=int, action="append", help="only this resource id (repeatable)")
    ap.add_argument("--all-palettes", action="store_true", help="also write cut-ins for palettes 1..15 (default 0)")
    ap.add_argument("--refresh", action="store_true",
                    help="rewrite the requested PNGs (default: keep and record files already in OUT_DIR)")
    a = ap.parse_args()
    pals = tuple(range(16)) if a.all_palettes else (0,)
    try:
        m = d4screenart.extract_locked(a.game, a.out, a.id, pals,
                                       log=lambda n: print(n, end=" ", flush=True), refresh=a.refresh)
    except d4screenart.ForeignReceipt as exc:
        # R5: the folder's manifest.json belongs to another tool (or is not JSON); never overwrite it.
        print(f"\nrefusing to overwrite {a.out}: {exc}", file=sys.stderr)
        return 2
    print(f"\nfaces {len(m['faces'])}, cut-in members {len(m['cutins'])}, errors {len(m['errors'])} -> {a.out}")
    return 1 if m["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
