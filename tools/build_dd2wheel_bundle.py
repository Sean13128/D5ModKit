"""Assemble Builds/DD2WHEEL-<date>/ : the nine rebuilt DD2 class packs + the kit files, verified.

    python tools/build_dd2wheel_bundle.py --src MODS --rebuilt REBUILT --kit WORKTREE --date 20261030
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

KIT_FILES = [
    "d5lib/classcheck.py",
    "d5lib/dd2source.py",
    "tests/test_dd2_control_flags.py",
    "tools/rebuild_dd2_control_flags.py",
]
WHEEL_FILES = [
    ("wheels/replay_dd2_control_decode.py", "wheels/replay_dd2_control_decode.py"),
    ("wheels/audit_dd2_anm.py", "wheels/audit_dd2_anm.py"),
]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree(root):
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            p = Path(base) / name
            out[str(p.relative_to(root))] = {"sha256": sha(p), "bytes": p.stat().st_size}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--rebuilt", required=True)
    ap.add_argument("--kit", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--receipts", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "mods").mkdir(parents=True)
    (out / "kit-install").mkdir()
    (out / "wheels").mkdir()
    (out / "receipts").mkdir()

    problems, packs = [], {}
    for name in sorted(os.listdir(args.rebuilt)):
        src = Path(args.src) / name
        new = Path(args.rebuilt) / name
        old_tree, new_tree = tree(src), tree(new)
        if set(old_tree) != set(new_tree):
            problems.append("%s: file set changed (%d -> %d)" % (name, len(old_tree), len(new_tree)))
        changed = [k for k in old_tree if k in new_tree and old_tree[k]["sha256"] != new_tree[k]["sha256"]]
        # ownership/identity surface: everything except the rebuilt animation members must be identical
        others = [k for k in old_tree if k in new_tree and old_tree[k]["sha256"] != new_tree[k]["sha256"]
                  and not (k.startswith("files/Anime/") and k.endswith(".lzs"))]
        if others:
            problems.append("%s: %d non-animation file(s) changed: %s" % (name, len(others), others[:4]))
        if len(changed) != 2:
            problems.append("%s: %d animation member(s) changed, expected 2" % (name, len(changed)))
        packs[name] = {"files": len(new_tree), "bytes": sum(v["bytes"] for v in new_tree.values()),
                       "changed_members": sorted(changed)}
        shutil.copytree(new, out / "mods" / name)

    for rel in KIT_FILES:
        src = Path(args.kit) / rel
        dest = out / "kit-install" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for rel, dest_rel in WHEEL_FILES:
        src = Path(args.kit) / rel
        dest = out / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for name in sorted(os.listdir(args.receipts)):
        p = Path(args.receipts) / name
        if p.is_file() and (name.endswith(".json") or name.endswith(".log")):
            shutil.copy2(p, out / "receipts" / name)

    inventory = {"packs": packs, "problems": problems,
                 "source": str(args.src), "rebuilt": str(args.rebuilt),
                 "files": tree(out)}
    (out / "INVENTORY.json").write_text(json.dumps(inventory, indent=1))
    lines = ["DD2WHEEL %s - nine rebuilt DD2 class packs" % args.date, ""]
    for name, rec in packs.items():
        lines.append("%-22s %3d files %11d B  changed: %s" % (name, rec["files"], rec["bytes"],
                                                             ", ".join(rec["changed_members"])))
    lines.append("")
    lines.append("kit-install: " + ", ".join(KIT_FILES))
    lines.append("problems: %d" % len(problems))
    (out / "INVENTORY.txt").write_text("\n".join(lines) + "\n")

    verify = {"ok": not problems, "files": len(inventory["files"]), "problems": problems,
              "rehash": {k: sha(out / k) for k in sorted(inventory["files"])}}
    bad = [k for k, v in verify["rehash"].items() if v != inventory["files"][k]["sha256"]]
    if bad:
        verify["ok"] = False
        verify["problems"].append("re-hash mismatch: %s" % bad[:5])
    (out / "VERIFY.json").write_text(json.dumps(verify, indent=1))
    print("packs:", len(packs), "files:", len(inventory["files"]), "problems:", len(problems))
    for p in problems[:8]:
        print("  -", p)
    print("VERIFY ok:", verify["ok"])
    return 0 if verify["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
