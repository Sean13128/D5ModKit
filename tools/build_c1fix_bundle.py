#!/usr/bin/env python3
"""Build Builds/LIVE5_TEST5-<date>/ : only what changed, with an inventory the installer can check.

The bundle mirrors the installed kit's layout so every file is a whole-file copy to the same relative path:

    runtime/d5lib/native/d5sound.inc.c     the SILENT fix (the managers are heap objects -- LIVE7 §2.1)
    runtime/d5lib/tablelimits.py           new: the drawer's per-field limits + printf-format rules
    runtime/tools/check_pack_tables.py     new: run those rules over every pack / the merged database
    runtime/tests/test_tablelimits.py      new: the tests for the above
    mods/<folder>/...                      only when a mod folder changed (C1 data fix), with INVENTORY.json

`INVENTORY.txt` lists each file's sha256, its size, what it does and **the sha256 the installed kit has now**, so
each copy can be checked before and after.  `INVENTORY.json` carries the mod folders' `tree_sha256`
(sha256 of `relpath\\0sha256hex\\n` per file, REGEN/LIVE7's definition -- the trailing newline matters).

    python tools/build_c1fix_bundle.py --out "Builds/LIVE5_TEST5-<date>" [--mods "<installed kit>/mods/D4_Class_1080"]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path("/Volumes/Data/Projects/D5")
KIT_SRC = ROOT / "Local/Worktrees/c1fix"            # the worktree with the fix
INSTALLED = ROOT / "Local/Installed D5ModKit"        # a symlink; read through it, never copy the link
BUNDLE_NAME = "LIVE5_TEST5"

RUNTIME_FILES = [
    ("d5lib/native/d5sound.inc.c", "the SILENT fix: the four managers are heap objects, so the pointer test is "
                                   "readable() (VirtualQuery), not in_image() (LIVE7 §2.1)"),
    ("d5lib/tablelimits.py", "new: the Skill-Shop drawer's per-field byte limits + the printf-format rule"),
    ("tools/check_pack_tables.py", "new: run those rules over every pack and the merged Database_0.dat"),
    ("tests/test_tablelimits.py", "new: the tests for the two files above"),
]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_rows(folder: Path) -> list[tuple[str, str]]:
    rows = []
    for dirpath, _dirs, files in os.walk(folder):
        for name in sorted(files):
            p = Path(dirpath) / name
            rows.append((str(p.relative_to(folder)), sha256(p)))
    return sorted(rows)


def tree_sha(rows) -> str:
    h = hashlib.sha256()
    for rel, dig in rows:
        h.update(rel.encode() + b"\0" + dig.encode() + b"\n")   # trailing \n per entry (LIVE7 §1.1)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mods", type=Path, action="append", default=[],
                    help="a changed mod folder inside the installed kit's mods/")
    ap.add_argument("--note", default="", help="one line for INSTALL.md")
    a = ap.parse_args(argv)
    out: Path = a.out if a.out.is_absolute() else ROOT / a.out
    if out.exists():
        shutil.rmtree(out)
    (out / "runtime").mkdir(parents=True)

    lines = [f"{out.name} -- runtime + kit tools" + (" + one mod folder" if a.mods else " (no mod folders)"), ""]
    lines.append("kit source: Local/Worktrees/c1fix (branch c1fix)")
    lines.append("game build: 9460a6411699... (pinned exe)")
    lines.append("")
    lines.append("copy each file to the same relative path inside the installed kit; 'kit now' = what it has")
    for rel, why in RUNTIME_FILES:
        src = KIT_SRC / rel
        if not src.exists():
            print(f"missing: {src}")
            return 2
        dst = out / "runtime" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        now = INSTALLED / rel
        now_sha = sha256(now) if now.exists() else "NEW file"
        same = "SAME as the kit already" if now.exists() and now_sha == sha256(src) else ""
        lines.append(f"{sha256(src)}  {src.stat().st_size:8d}  runtime/{rel}")
        lines.append(f"    {why}")
        lines.append(f"    kit now: {now_sha}" + (f"   ({same})" if same else ""))

    inv = {"bundle": out.name, "runtime": {}, "mods": {}}
    for rel, _why in RUNTIME_FILES:
        src = KIT_SRC / rel
        inv["runtime"][rel] = {"sha256": sha256(src), "size": src.stat().st_size}

    if a.mods:
        lines.append("")
        lines.append("mod folders (whole-folder copy; never rsync --delete into mods/)")
        for m in a.mods:
            name = m.name
            dst = out / "mods" / name
            shutil.copytree(m, dst)
            rows = tree_rows(dst)
            inv["mods"][name] = {"files": len(rows), "tree_sha256": tree_sha(rows),
                                 "rows": [{"path": r, "sha256": s} for r, s in rows]}
            lines.append(f"mods/{name}: {len(rows)} files, tree_sha256 {tree_sha(rows)}")
    (out / "INVENTORY.txt").write_text("\n".join(lines) + "\n")
    (out / "INVENTORY.json").write_text(json.dumps(inv, indent=1) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
