"""Structural audit of built ANM banks: node graph cycles, dangling indices, param link chains.

Offline, read-only.  Reads a mods folder and parses every shipped .lzs member with the kit's anm module.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

KIT = Path(os.environ.get("D5KIT", "/Volumes/Data/Projects/D5/Local/Worktrees/dd2wheel"))
sys.path.insert(0, str(KIT))
from d5lib import anm  # noqa: E402


def graph_check(b):
    """Look for cycles / dangling links in (child,next)."""
    out = []
    for i, n in enumerate(b.nodes):
        for name, v in (("child", n.child), ("next", n.next)):
            if v != -1 and not (0 <= v < len(b.nodes)):
                out.append(f"node {i} {name}={v} out of range ({len(b.nodes)})")
    # bounded walk from each animation root and from node 0
    def walk_bound(root, limit=10000):
        seen = set()
        stack = [root]
        steps = 0
        while stack:
            i = stack.pop()
            steps += 1
            if steps > limit:
                return f"walk from {root} exceeded {limit} steps"
            if i < 0 or i >= len(b.nodes):
                return f"walk from {root} hit index {i}"
            if i in seen:
                return f"walk from {root} revisited node {i} after {steps} steps"
            seen.add(i)
            n = b.nodes[i]
            if n.next != -1:
                stack.append(n.next)
            if n.child != -1:
                stack.append(n.child)
        return None
    return out, walk_bound


def audit_block(b, tag):
    findings = []
    a_ids = {a.id for a in b.animations}
    out, walk_bound = graph_check(b)
    findings += out
    for a in b.animations:
        if not (0 <= a.root < len(b.nodes)):
            findings.append(f"anim {a.id} root={a.root} out of range ({len(b.nodes)})")
            continue
        r = walk_bound(a.root)
        if r:
            findings.append(f"anim {a.id}: {r}")
    # keys
    for n in b.nodes:
        if n.first_key < 0:
            if n.num_keys:
                findings.append(f"node keys: first_key={n.first_key} num={n.num_keys}")
            continue
        if n.first_key + n.num_keys > len(b.keys):
            findings.append(f"node keys {n.first_key}+{n.num_keys} > keys {len(b.keys)}")
    for ki, k in enumerate(b.keys):
        if k.cell >= len(b.cells):
            findings.append(f"key {ki} cell={k.cell} >= cells {len(b.cells)}")
        if k.xform >= len(b.transforms):
            findings.append(f"key {ki} xform={k.xform} >= transforms {len(b.transforms)}")
        if k.color >= len(b.colors):
            findings.append(f"key {ki} color={k.color} >= colors {len(b.colors)}")
        if k.param:
            # param list: (anim_id, 0) pairs terminated by -1, starting at this index
            j = k.param
            chain = []
            steps = 0
            while 0 <= j < len(b.params) and steps < 64:
                v = b.params[j]
                if v == -1:
                    chain.append("END")
                    break
                chain.append(v)
                j += 2
                steps += 1
            else:
                findings.append(f"key {ki} param={k.param} chain not terminated: {chain[:8]}")
            # linked animation id must exist in this block (nested reference)
            for v in chain:
                if isinstance(v, int) and v > 0 and v not in a_ids:
                    findings.append(f"NOTE key {ki} param links anim {v} not in this block")
    for ci, c in enumerate(b.cells):
        if c.tex >= len(b.texture_infos):
            findings.append(f"cell {ci} tex={c.tex} >= textures {len(b.texture_infos)}")
        if c.pal >= max(1, len(b.palette_infos)):
            findings.append(f"cell {ci} pal={c.pal} >= palettes {len(b.palette_infos)}")
    for ti, t in enumerate(b.transforms):
        if t.pivot >= len(b.pivots):
            findings.append(f"transform {ti} pivot={t.pivot} >= pivots {len(b.pivots)}")
    return findings


def audit_file(fp: Path):
    try:
        f = anm.load(fp)
    except Exception as exc:  # noqa: BLE001
        return [f"parse failed: {type(exc).__name__}: {exc}"], None
    res = []
    for bi, b in enumerate(f.blocks):
        res += [f"block{bi}: {x}" for x in audit_block(b, fp.name)]
    return res, f


def main():
    root = Path(sys.argv[1])
    out = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        files = sorted((d / "files").rglob("*.lzs")) if (d / "files").exists() else []
        rec = {}
        for fp in files:
            r, f = audit_file(fp)
            if r:
                rec[fp.name] = r
        out[d.name] = {"files": len(files), "findings": rec}
        print(d.name, len(files), "files,", sum(len(v) for v in rec.values()), "findings")
        for k, v in list(rec.items())[:6]:
            for line in v[:6]:
                print("   ", k, line)
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1))


main()
