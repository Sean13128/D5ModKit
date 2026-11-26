#!/usr/bin/env python3
"""REPROFIX4 (b): pin the installed magic.dat rows of D4_Unique_5388 (Psylos) in
``d5lib/importers/d4-evility-additions.json`` as ``magic_ids``.

The installed pack owns magic rows 13029-13033 (Geo Change, Geo Blast, Bonus Change, Geo Warp, Bonus Blast); the
builder takes the first free ids at build time (13003-13007), so a rebuild matched the install in content but not
in ids.  ``Importer._pin_magic_ids`` (D4-FIX4) already renames the builder's adaptation rows to a recorded list in
magic.dat, skills.json and char.dat; this adds the list for 5388 the way REPROFIX1/3 added the installed evility
rows.  Then run ``tools/build_d4_evility_overlay.py`` (default held folder).

    python tools/reprofix4_d4_5388.py [--installed DIR]
"""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADD = ROOT / "d5lib/importers/d4-evility-additions.json"
PACK = "D4_Unique_5388"


def installed_ids(pack_dir):
    doc = json.loads((Path(pack_dir) / "patches/db/magic.dat.json").read_text())
    return sorted(int(r["id"]) for r in doc.get("added") or [] if int(r["id"]) < 20000)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--installed", type=Path, default=Path(os.environ.get("D5_INSTALLED_MODS") or
                    "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods"))
    args = ap.parse_args(argv)
    doc = json.loads(ADD.read_text())
    ids = installed_ids(args.installed / PACK)
    doc["mods"][PACK]["magic_ids"] = ids
    ADD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote", ADD, PACK, "magic_ids", ids)


if __name__ == "__main__":
    main()
