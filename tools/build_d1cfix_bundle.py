"""Build the D1CFIX bundle: TEST14 + the 13 D1 Complete generic classes with bounded descriptions.

Why (D1CFREEZE, 2026-10-29): the wheel's selected-entry description is copied into the menu object's
0x100-byte field at +0x1c2c with no length check (0x140663200 ... jne), and the dirty byte is written
at +0x1d2c - one byte past the field.  Six of the 13 D1C descriptions were 257-280 bytes, so the copy
overwrote +0x1d30/+0x1d34 (17.0f/16.0f) and the list-pane pointer at +0x1d38 that the same screen
family calls through (vt+0xa8).  11390 (Strider, 273 bytes) is the class LIVE10 froze on.

This tool copies the 13 TEST13 packs, rewrites only `hire_desc` (same text except the third sentence,
which loses the per-skill learn-level list), runs the class gate (R1-R9) and writes a delta bundle
that is applied on top of LIVE5_TEST14-20261029.

Usage:  python tools/build_d1cfix_bundle.py [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from d5lib import classcheck, newclasses, repack                     # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BASE = os.path.join(ROOT, "Builds", "LIVE5_TEST14-20261029")
SRC13 = os.path.join(ROOT, "Builds", "LIVE5_TEST13-20261029", "mods")
DEFAULT_OUT = os.path.join(ROOT, "Builds", "D1CFIX-20261029")
THIRD = re.compile(r"(\d+) mapped D1 abilities[^.]*\.")


def tree_sha(folder):
    h = hashlib.sha256()
    files = 0
    size = 0
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for n in sorted(names):
            p = os.path.join(root, n)
            rel = os.path.relpath(p, folder).replace(os.sep, "/")
            data = open(p, "rb").read()
            h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
            files += 1
            size += len(data)
    return h.hexdigest(), files, size


def short_desc(desc):
    """The same description with its third sentence replaced (mirrors build_batch.py's line3)."""
    marker = "Disgaea 1 Complete HD art;"
    at = desc.find(marker)
    if at < 0:
        return newclasses.desc_text(desc)
    m = THIRD.search(desc, at)
    n = int(m.group(1)) if m else None
    if n is None:
        return newclasses.desc_text(desc)
    return "%sDisgaea 1 Complete HD art; %d D1 abilities are mapped to D5 skills." % (desc[:at], n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    src = sorted(os.path.join(SRC13, n) for n in os.listdir(SRC13)
                 if n.startswith("D1C_Class_") and os.path.isdir(os.path.join(SRC13, n)))
    if len(src) != 13:
        raise SystemExit("expected 13 D1C_Class_* folders in %s, found %d" % (SRC13, len(src)))
    if not os.path.isdir(BASE):
        raise SystemExit("TEST14 base bundle missing: %s" % BASE)

    out = args.out
    mods = os.path.join(out, "mods")
    if os.path.isdir(mods):
        shutil.rmtree(mods)                     # our own output folder, never the kit or the game
    os.makedirs(mods)

    inventory = {"bundle": os.path.basename(out), "built": "2026-10-29", "offline": True,
                 "installed": False,
                 "base": {"bundle": os.path.basename(BASE),
                          "inventory": os.path.join(BASE, "INVENTORY.json")},
                 "algorithm": "sha256 of sorted relative UTF-8 path + NUL + sha256(file)",
                 "mods": {}, "kit_files": {}, "descriptions": []}
    names = []
    for folder in src:
        name = os.path.basename(folder)
        dst = os.path.join(mods, name)
        shutil.copytree(folder, dst)
        repack.ascii_text(dst)                  # idempotent: the shipped text is already ASCII
        jpath = None
        for p in sorted(os.listdir(os.path.join(dst, "patches", "classes"))):
            if p.startswith("class_") and p.endswith(".json"):
                jpath = os.path.join(dst, "patches", "classes", p)
        if jpath is None:
            raise SystemExit("%s carries no class descriptor" % name)
        spec = json.load(open(jpath))
        before = spec["hire_desc"]
        after = short_desc(before)
        after = newclasses.desc_text(after)
        spec["hire_desc"] = after
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=1, ensure_ascii=False)
            f.write("\n")
        findings = classcheck.check(dst)
        errors = [f for f in findings if f["severity"] == "error"]
        if errors:
            raise SystemExit("%s fails the class gate after the rewrite: %s"
                             % (name, [f["rule"] for f in errors]))
        sha, files, size = tree_sha(dst)
        inventory["mods"][name] = {"family": spec["family"], "files": files, "bytes": size,
                                   "tree_sha256": sha, "desc_before": len(before.encode()),
                                   "desc_after": len(after.encode()), "gate": "clean R1-R9"}
        inventory["descriptions"].append({"family": spec["family"], "name": spec["name"],
                                          "before": len(before.encode()),
                                          "after": len(after.encode())})
        names.append(name)

    over = [d for d in inventory["descriptions"] if d["after"] > classcheck.DESC_MAX]
    if over:
        raise SystemExit("descriptions still over %d bytes: %s" % (classcheck.DESC_MAX, over))

    # --- profile: TEST14's load order plus the 13, in TEST13's order
    p14 = json.load(open(os.path.join(BASE, "profile", "LIVE5_TEST14", "load_order.json")))
    pdir = os.path.join(out, "profile", "LIVE5_D1CFIX")
    os.makedirs(pdir, exist_ok=True)
    order = list(p14) + names
    if len(set(order)) != len(order):
        raise SystemExit("duplicate profile entries")
    json.dump(order, open(os.path.join(pdir, "load_order.json"), "w"), indent=1)
    json.dump({"name": "LIVE5_D1CFIX",
               "description": "TEST14 plus the 13 D1 Complete generic classes rebuilt with bounded "
                              "descriptions (D1CFREEZE). 166 entries; see INSTALL.md.",
               "separate_saves": False, "created": 1793330000.0},
              open(os.path.join(pdir, "profile.json"), "w"), indent=1)

    # --- the two kit files that change (install-time writer, build-time gate)
    for sub, rel in (("kit-install", "d5lib/newclasses.py"), ("kit-build", "d5lib/classcheck.py")):
        srcf = os.path.join(HERE, rel)
        dstf = os.path.join(out, sub, rel)
        os.makedirs(os.path.dirname(dstf), exist_ok=True)
        data = open(srcf, "rb").read()
        open(dstf, "wb").write(data)
        inventory["kit_files"][sub + "/" + rel] = {"bytes": len(data),
                                                   "sha256": hashlib.sha256(data).hexdigest()}

    inventory["totals"] = {"mods": len(names),
                           "files": sum(m["files"] for m in inventory["mods"].values()),
                           "bytes": sum(m["bytes"] for m in inventory["mods"].values()),
                           "profile_entries": len(order)}
    json.dump(inventory, open(os.path.join(out, "INVENTORY.json"), "w"), indent=1)

    leases = {
        "schema": "d1cfix/1",
        "note": "Delta bundle: apply on top of LIVE5_TEST14-20261029. 13 class packs are new; every "
                "other folder, every id, every row is TEST14's. No id moved.",
        "base": os.path.basename(BASE),
        "mods": names,
        "profile": {"name": "LIVE5_D1CFIX", "entries": len(order),
                    "added": names},
        "change": {
            "what": "patches/classes/class_<family>.json hire_desc only",
            "why": "the wheel's description copy (0x140663200) has no bound and lands past the "
                   "0x100-byte field at +0x1c2c into +0x1d30/+0x1d34 and the +0x1d38 list pane",
            "before": {d["family"]: d["before"] for d in inventory["descriptions"]},
            "after": {d["family"]: d["after"] for d in inventory["descriptions"]},
            "over_255_before": [d["family"] for d in inventory["descriptions"] if d["before"] > 255],
        },
        "gates": {"classcheck": "0 errors, R9-desc-length clear on all 13"},
        "excluded": {"test13_text": "the em-dash ASCII fix (D1CWEDGE3) is already in these packs"},
    }
    json.dump(leases, open(os.path.join(out, "LEASES.json"), "w"), indent=1)

    # --- verify what was written
    verify = {"mods": {}, "kit_files": {}, "ok": True}
    for name in names:
        sha, files, size = tree_sha(os.path.join(mods, name))
        ok = sha == inventory["mods"][name]["tree_sha256"]
        verify["mods"][name] = {"tree_sha256": sha, "match": ok}
        verify["ok"] = verify["ok"] and ok
    for key, rec in inventory["kit_files"].items():
        data = open(os.path.join(out, key), "rb").read()
        ok = hashlib.sha256(data).hexdigest() == rec["sha256"]
        verify["kit_files"][key] = {"match": ok}
        verify["ok"] = verify["ok"] and ok
    json.dump(verify, open(os.path.join(out, "VERIFY.json"), "w"), indent=1)
    if not verify["ok"]:
        raise SystemExit("verification failed")
    print("bundle %s: %d mods, %d files, %.1f MB, profile %d entries"
          % (out, len(names), inventory["totals"]["files"],
             inventory["totals"]["bytes"] / 1e6, len(order)))
    for d in inventory["descriptions"]:
        print("  %-6d %-14s %3d -> %3d bytes" % (d["family"], d["name"], d["before"], d["after"]))


if __name__ == "__main__":
    main()
