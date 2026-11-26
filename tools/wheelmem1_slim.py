"""WHEELMEM1: SLIM29 — the 21/27 hurt art re-packed inside TEST28's own budget.

TEST29c is TEST28 plus one donor block appended *whole*: 4,094 extra nodes, 10,946 extra keys,
2,020 transforms and 2,250 KB of donor atlas per class bank — and then the donor atlas a second
time (it copies TEST29's image set over TEST28's), which is why c is 1.6x larger than b.

Only 7 nodes x 21 keys x 7 cells of that donor are reachable from 21 (and the same from 27).
SLIM29 extracts exactly that subgraph, re-bases every index, and copies the 14 cell rectangles
into free (unreferenced) space of TEST28's existing textures.  Nothing is added but ~15 KB of
tables and one 10-colour palette group per bank.

Rendering must be pixel-identical to TEST29c for 21/27 and to TEST28 everywhere else.

usage: python tools/wheelmem1_slim.py <out bundle dir>
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import numpy as np

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
CAND = ROOT / 'Builds/TEST29FIX1-20261101/candidate-c/mods'
EV = ROOT / 'Builds/WHEELMEM1-20261102/evidence'
HURT = (21, 27)
NESTED = 0x100


def covered_mask(a, ti):
    t = a.textures[ti]
    m = np.zeros((t.height, t.width), np.uint8)
    for c in a.block.cells:
        if c.tex == ti and c.w and c.h:
            m[c.y:c.y + c.h, c.x:c.x + c.w] = 1
    return m == 0          # True = free


def place(free, w, h):
    H, W = free.shape
    if w > W or h > H:
        return None
    ii = np.zeros((H + 1, W + 1), np.int32)
    ii[1:, 1:] = np.cumsum(np.cumsum(free.astype(np.int32), 0), 1)
    s = ii[h:, w:] - ii[:-h, w:] - ii[h:, :-w] + ii[:-h, :-w]
    ys, xs = np.where(s == w * h)
    if not len(ys):
        return None
    return int(ys[0]), int(xs[0])


def extract(t, x, y, w, h):
    """Rows of an 8-bit indexed texture rect."""
    stride = t.width
    return [bytes(t.data[(y + r) * stride + x:(y + r) * stride + x + w]) for r in range(h)]


def paste(t, x, y, rows, w):
    stride = t.width
    buf = bytearray(t.data)
    for r, row in enumerate(rows):
        buf[(y + r) * stride + x:(y + r) * stride + x + w] = row
    t.data = bytes(buf)


def build(a, c, stats):
    x, y = a.block, c.block
    nb = copy.deepcopy(x)
    textures = copy.deepcopy(a.textures)
    palettes = copy.deepcopy(a.palettes)
    nb.textures = textures
    nb.palettes = palettes
    bt, bp = len(a.textures), len(a.palettes)
    free = {ti: covered_mask(a, ti) for ti in range(bt)}
    new_tex = None

    # --- palettes: keep the base set plus each donor group the hurt art uses
    group_map = {}
    used_cells = []
    for aid in HURT:
        anim = next(t for t in y.animations if t.id == aid)
        reach, todo = set(), [anim.root]
        while todo:
            ni = todo.pop()
            if ni in reach or not 0 <= ni < len(y.nodes):
                continue
            reach.add(ni)
            n = y.nodes[ni]
            todo.extend((n.child, n.next))
        for ni in reach:
            for k in y.node_keys(y.nodes[ni]):
                if k.cell and k.cell not in used_cells:
                    used_cells.append(k.cell)
    for ci in used_cells:
        cc = y.cells[ci]
        if cc.pal >= bp:
            gb = cc.pal - (cc.pal % 10)
            if gb not in group_map:
                group_map[gb] = bp + 10 * len(group_map)
                for i in range(10):
                    nb.palettes.append(copy.deepcopy(c.palettes[gb + i]))
                    nb.palette_infos.append(anm.PaletteInfo(0, 256, 0))

    # --- one new cell per distinct donor rect, pixels into free atlas space
    cell_map = {}
    for ci in used_cells:
        cc = y.cells[ci]
        if cc.tex < bt:
            cell_map[ci] = ci          # already a TEST28 cell
            continue
        src = c.textures[cc.tex]
        if cc.w == 0 or cc.h == 0:
            cell_map[ci] = 0
            continue
        rows = extract(src, cc.x, cc.y, cc.w, cc.h)
        new_ti = new_x = new_y = None
        for ti in range(bt):
            pos = place(free[ti], cc.w, cc.h)
            if pos is not None:
                new_ti, (new_y, new_x) = ti, pos
                free[ti][new_y:new_y + cc.h, new_x:new_x + cc.w] = False
                paste(nb.textures[ti], new_x, new_y, rows, cc.w)
                break
        if new_ti is None:
            if new_tex is None:
                h = 1
                while h < cc.h:
                    h *= 2
                new_tex = len(nb.textures)
                nb.textures.append(anm.Image8(b'\x09\x01\x01\x01', 1024, h, 1,
                                              bytes(1024 * h)))
                nb.texture_infos.append(anm.TextureInfo(0, 1024, h, 8, 0x10, 0x10, 0))
                free[new_tex] = np.ones((h, 1024), bool)
            pos = place(free[new_tex], cc.w, cc.h)
            if pos is None:
                raise SystemExit(f'{cc.w}x{cc.h} does not fit the fallback atlas')
            new_ti, (new_y, new_x) = new_tex, pos
            free[new_tex][new_y:new_y + cc.h, new_x:new_x + cc.w] = False
            paste(nb.textures[new_ti], new_x, new_y, rows, cc.w)
        pal = cc.pal if cc.pal < bp else group_map[cc.pal - (cc.pal % 10)] + (cc.pal % 10)
        nb.cells.append(anm.Cell(new_ti, pal, cc.unk2, cc.flags, new_x, new_y,
                                 cc.w, cc.h, cc.unk8))
        cell_map[ci] = len(nb.cells) - 1

    # --- reachable node/key/transform/pivot/colour/param subgraph of 21 and 27
    for aid in HURT:
        anim = next(t for t in y.animations if t.id == aid)
        reach, todo = set(), [anim.root]
        order = []
        while todo:
            ni = todo.pop()
            if ni in reach or not 0 <= ni < len(y.nodes):
                continue
            reach.add(ni)
            order.append(ni)
            n = y.nodes[ni]
            todo.extend((n.child, n.next))
        order.sort()
        idx = {}
        for ni in order:
            idx[ni] = len(nb.nodes) + len(idx)
        for ni in order:
            n = copy.deepcopy(y.nodes[ni])
            keys = []
            for k in y.node_keys(y.nodes[ni]):
                k = copy.deepcopy(k)
                if k.cell:
                    k.cell = k.cell if k.cell < len(x.cells) else cell_map[k.cell]
                if k.xform >= len(x.transforms):
                    tf = copy.deepcopy(y.transforms[k.xform])
                    if tf.pivot >= len(x.pivots):
                        tf.pivot = len(nb.pivots)
                        nb.pivots.append(copy.deepcopy(y.pivots[y.transforms[k.xform].pivot]))
                    k.xform = len(nb.transforms)
                    nb.transforms.append(tf)
                if k.color >= len(x.colors):
                    col = copy.deepcopy(y.colors[k.color])
                    k.color = len(nb.colors)
                    nb.colors.append(col)
                if k.flags & NESTED:
                    rec = y.params[k.param:k.param + 3]
                    if len(rec) == 3:
                        if len(nb.params) % 3:
                            nb.params.extend([0] * (3 - len(nb.params) % 3))
                        k.param = len(nb.params)
                        nb.params.extend(rec)
                keys.append(k)
            n.first_key = len(nb.keys)
            n.num_keys = len(keys)
            n.child = idx.get(n.child, -1)
            n.next = idx.get(n.next, -1)
            nb.keys.extend(keys)
            nb.nodes.append(n)
        new_root = idx[anim.root]
        next(t for t in nb.animations if t.id == aid).root = new_root
    stats.append({'cells_added': len(nb.cells) - len(x.cells),
                  'nodes_added': len(nb.nodes) - len(x.nodes),
                  'keys_added': len(nb.keys) - len(x.keys),
                  'transforms_added': len(nb.transforms) - len(x.transforms),
                  'params_added': len(nb.params) - len(x.params),
                  'textures_added': len(nb.textures) - bt,
                  'palettes_added': len(nb.palettes) - bp})
    return anm.AnmFile([nb], nb.textures, nb.palettes, a.hdr_unk, a.trailing)


def main():
    out = Path(sys.argv[1])
    n = base.require_base_set()
    print(f'TEST28 base asserted: {n} pinned banks', flush=True)
    rows = []
    for mod, banks in base.manifest()['banks'].items():
        dest = out / 'mods' / mod
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(base.base_dir(mod) / mod, dest)
        for bank in banks:
            a = anm.load(base.bank_path(mod, bank))
            c = anm.load(CAND / mod / base.REL / bank)
            stats = []
            slim = build(a, c, stats)
            raw = slim.to_bytes()
            dst = dest / base.REL / bank
            dst.write_bytes(anm.lzs_compress(raw))
            row = {'mod': mod, 'bank': bank, 'test28_raw': len(a.to_bytes()),
                   'test29c_raw': len(c.to_bytes()), 'slim_raw': len(raw), **stats[0]}
            rows.append(row)
            print(f'  {mod}/{bank}: TEST28 {row["test28_raw"]:,} | c {row["test29c_raw"]:,} '
                  f'| SLIM {len(raw):,} (+{len(raw)-row["test28_raw"]:,})', flush=True)
    EV.mkdir(parents=True, exist_ok=True)
    (EV / 'slim-manifest.json').write_text(json.dumps(rows, indent=1))
    print('wrote', out)


if __name__ == '__main__':
    main()
