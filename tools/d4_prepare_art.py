#!/usr/bin/env python3
"""Prepare D4 source art for any D4 character row (humanoid layout or monster clips), from the verified source.

    python tools/d4_prepare_art.py OUT_DIR SOURCE_ID [SOURCE_ID ...] [--source-root DIR]

Writes ``OUT_DIR/prepared-<id>`` and ``OUT_DIR/library-<id>``: the packet and the two-body library
``tools/build_source_pack.py`` / ``tools/build_d4_unique.py`` read (``read_prepared``).  Bodies come
from the prepared source folder's verified ``Data/DATA/ANM_HI.dat`` (SOURCEPREP4-D4, ``_d4_source``);
the shape rules are the October lane scripts' (palette = colour index mod 10, clustered fallback 0).

The importer no longer calls this: it regenerates the same packets per build in its scratch.  This
tool stays as the standalone way to look at one character's prepared art.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from d5lib.importers import _d4_source  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path, help="folder for prepared-<id> and library-<id>")
    ap.add_argument("ids", type=int, nargs="+", help="D4 source character rows")
    ap.add_argument("--source-root", type=Path, help="the D4 install folder (diagnostic; default: prepared source)")
    args = ap.parse_args(argv)
    try:
        files = _d4_source.data_dir(args.source_root)
        for sid in args.ids:
            prepared, library = _d4_source.unique_art(files, sid, args.out, v3=True)
            print(f"{sid}: {prepared} | {library}")
    except _d4_source.D4SourceError as exc:
        ap.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
