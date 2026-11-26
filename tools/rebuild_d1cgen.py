"""Rebuild the 13 Disgaea 1 Complete generic class packs with ASCII text (D1CWEDGE3).

Source: the batch packs the installer used (`d1c-batches-20261026/{humanoids,monsters}/pack`).
Change: the packs' own text is rewritten to printable ASCII (`d5lib.repack.ascii_text`); ids, rows,
art, faces and descriptors are untouched.  Nothing else is copied, and every pack must pass the
class identity gate (`d5lib.classcheck.gate` -> R1..R8) before it is written to the bundle.

Usage:  python tools/rebuild_d1cgen.py [--source DIR] [--out DIR]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from d5lib import classcheck, repack                                   # noqa: E402

DEFAULT_SOURCE = "/Volumes/Data/ai-tmp/d1c-batches-20261026"
BATCHES = ("humanoids", "monsters")
# the project root's Builds/ (bundles never go into the kit repository: they carry mod folders)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(ROOT, "Builds", "D1CGEN-20261029")


def tree_sha(folder):
    h = hashlib.sha256()
    files = 0
    size = 0
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for n in sorted(names):
            p = os.path.join(root, n)
            rel = os.path.relpath(p, folder).replace(os.sep, "/")
            h.update(rel.encode("utf-8") + b"\0")
            data = open(p, "rb").read()
            h.update(hashlib.sha256(data).digest())
            files += 1
            size += len(data)
    return h.hexdigest(), files, size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    packs = []
    for batch in BATCHES:
        base = os.path.join(args.source, batch, "pack")
        for name in sorted(os.listdir(base)):
            if name.startswith("D1C_Class_") and os.path.isdir(os.path.join(base, name)):
                packs.append(os.path.join(base, name))
    if len(packs) != 13:
        raise SystemExit("expected 13 generic class packs, found %d" % len(packs))

    mods = os.path.join(args.out, "mods")
    if os.path.isdir(mods):
        shutil.rmtree(mods)
    os.makedirs(mods)

    inventory = {"bundle": os.path.basename(args.out), "built": "2026-10-29",
                 "source": args.source, "packs": []}
    replacements = collections.Counter()
    for src in packs:
        name = os.path.basename(src)
        dst = os.path.join(mods, name)
        shutil.copytree(src, dst)                     # whole folders only, never a mirror copy
        before = {p: open(p, "rb").read() for p in _json(dst)}
        replacements.update(repack.ascii_text(dst))
        after = {p: open(p, "rb").read() for p in _json(dst)}
        changed = sorted(os.path.relpath(p, dst) for p in after if before.get(p) != after[p])
        found = classcheck.check(dst)
        gate = classcheck.gate(found)
        if gate:
            raise SystemExit("%s fails the gate: %s" % (name, json.dumps(gate, sort_keys=True)))
        spec = classcheck.class_specs(dst)[0]
        digest, files, size = tree_sha(dst)
        inventory["packs"].append(dict(
            name=name, family=int(spec["family"]), sprite_family=spec.get("sprite_family"),
            kind=spec.get("kind"), name_field=spec.get("name"),
            tree_sha256=digest, files=files, bytes=size,
            text_files_changed=changed,
            warnings=sorted({f["rule"] for f in found if f["severity"] == "warning"})))
        print("%-18s family %5d sprite %4s  %2d text file(s)  %s"
              % (name, spec["family"], spec.get("sprite_family"), len(changed), digest[:12]))

    inventory["text_replacements"] = {k: v for k, v in sorted(replacements.items())}
    with open(os.path.join(args.out, "INVENTORY.json"), "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=1, sort_keys=True)
        f.write("\n")
    print("replacements:", dict(replacements))
    print("wrote", args.out)


def _json(mod_dir):
    out = []
    for root, _dirs, names in os.walk(os.path.join(mod_dir, "patches")):
        for n in sorted(names):
            if n.endswith(".json"):
                out.append(os.path.join(root, n))
    return out


if __name__ == "__main__":
    main()
