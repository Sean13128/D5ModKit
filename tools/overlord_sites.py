"""Developer tool: HOOKS.md (Overlord's hook table) -> d5lib/data/overlord_sites.json, one row per named-RVA site.

    python tools/overlord_sites.py HOOKS.md   (Research/ASSESSMENT-20261026/p2-overlord-full/HOOKS.md)

The RVAs target the pinned Steam retail image; the 2 patches without an RVA (import table, stat-cap table) are left out."""
import json
import os
import re
import sys

OUT = os.path.join(os.path.dirname(__file__), "..", "d5lib", "data", "overlord_sites.json")


def parse(text):
    rows = []
    for line in text.splitlines():
        c = [x.strip() for x in line.split("|")]
        m = len(c) > 7 and re.fullmatch(r"`0x([0-9A-Fa-f]+)`", c[2])
        if m and c[3].isdigit():
            rows.append({"rva": int(m.group(1), 16), "len": int(c[3]), "module": c[7],
                         "handler": c[5].strip("`")})
    return rows


if __name__ == "__main__":
    rows = parse(open(sys.argv[1], encoding="utf-8").read())
    with open(OUT, "w") as f:
        json.dump(rows, f, indent=0)
    print(len(rows), "sites ->", os.path.normpath(OUT))
