#!/usr/bin/env python3
"""REPROFIX1 (b): record the installed evility rows of the D4 NPC uniques 5306/5307/5308 in
`d5lib/importers/d4-evility-additions.json` (they have no held-pack state; the builder alone gives all three the
same first free Skill row 7020, the installed packs own 7127/7128/7129).  Read-only on the installed mods;
then run `tools/build_d4_evility_overlay.py` to fold the additions into the overlay.

    python tools/reprofix1_d4_npc_evilities.py [--installed DIR]
"""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADD = ROOT / "d5lib/importers/d4-evility-additions.json"
PACKS = ("D4_Unique_5306", "D4_Unique_5307", "D4_Unique_5308")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--installed", type=Path, default=Path(os.environ.get("D5_INSTALLED_MODS") or
                    "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods"))
    args = ap.parse_args(argv)
    doc = json.loads(ADD.read_text())
    for name in PACKS:
        m = args.installed / name / "patches"
        entry = {"skill_rows": json.loads((m / "db/Skill.dat.json").read_text())["added"],
                 "char_links": {str(r["id"]): {k: v for k, v in r.items() if "evil" in k}
                                for r in json.loads((m / "db/char.dat.json").read_text())["added"]}}
        if (m / "evilities/evilities.json").is_file():
            entry["behaviors"] = json.loads((m / "evilities/evilities.json").read_text()).get("evilities", {})
        if (m / "evilities/aliases.json").is_file():
            entry["aliases"] = json.loads((m / "evilities/aliases.json").read_text())
        doc["mods"][name] = entry
    # TEXTHASH-D4: game text is written as references (docs/TEXT_REFS.md), never as text
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hash_d4_text
    from d5lib.importers import _d4_source
    doc = hash_d4_text.hash_document(doc, _d4_source.text_pool_for_tools())
    ADD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote", ADD, [n for n in PACKS])


if __name__ == "__main__":
    main()
