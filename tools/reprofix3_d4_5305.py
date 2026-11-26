#!/usr/bin/env python3
"""REPROFIX3 (b): record the installed evility row of D4_Unique_5305 in
``d5lib/importers/d4-evility-additions.json``, the way REPROFIX1 (b) recorded 5306/5307/5308.

The pack's installed ``Skill.dat`` owns row 7126 (Wild Cry), aliased to D5 evility 1010; the builder
alone allocates its first free row (7020), so a rebuild differs from the install.  Like the three
REPROFIX1 rows this is an ``installed_rows`` entry: the row keeps the installed id and the aliased
D5 evility's own text, so the authored-row band and placeholder rules do not apply (tests/test_evilgap1.py).
A mandatory adaptation label says where it came from.  Then run ``tools/build_d4_evility_overlay.py``.

    python tools/reprofix3_d4_5305.py [--installed DIR]
"""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADD = ROOT / "d5lib/importers/d4-evility-additions.json"
PACK = "D4_Unique_5305"
D5_NAMES = {1010: "Wild Cry"}


def entry_for(pack_dir):
    patches = Path(pack_dir) / "patches"
    rows = json.loads((patches / "db/Skill.dat.json").read_text())["added"]
    row = rows[0]
    aliases = json.loads((patches / "evilities/aliases.json").read_text())
    alias = int(aliases[str(row["id"])])
    name = D5_NAMES.get(alias, "")
    label = (f"evility {row['name_EN']} ({row['id']}): installed row recorded as is (REPROFIX3) - alias of D5 "
             f"evility {alias}{' (' + name + ')' if name else ''}, stored value {row['value1']}, text "
             f"{row['desc_EN']!r}; row {row['id']} is the id the installed pack owns, below the D4 exact band; "
             f"not reviewed against the D4 text")
    return {"skill_rows": rows,
            "char_links": {str(r["id"]): {k: v for k, v in r.items() if "evil" in k}
                           for r in json.loads((patches / "db/char.dat.json").read_text())["added"]},
            "behaviors": json.loads((patches / "evilities/evilities.json").read_text()).get("evilities", {}),
            "aliases": aliases,
            "adaptations": [label],
            "installed_rows": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--installed", type=Path, default=Path(os.environ.get("D5_INSTALLED_MODS") or
                    "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods"))
    args = ap.parse_args(argv)
    doc = json.loads(ADD.read_text())
    mods = doc["mods"]
    entry = entry_for(args.installed / PACK)
    mods = {k: v for k, v in mods.items() if k != PACK}
    out = {}
    for key, value in mods.items():
        if key > PACK and PACK not in out and key.startswith("D4_Unique_") and PACK not in mods:
            out[PACK] = entry
        out[key] = value
    out.setdefault(PACK, entry)
    doc["mods"] = out
    # TEXTHASH-D4: game text is written as references (docs/TEXT_REFS.md), never as text
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hash_d4_text
    from d5lib.importers import _d4_source
    doc = hash_d4_text.hash_document(doc, _d4_source.text_pool_for_tools())
    ADD.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote", ADD, PACK, entry["skill_rows"][0]["id"], "->", entry["aliases"])


if __name__ == "__main__":
    main()
