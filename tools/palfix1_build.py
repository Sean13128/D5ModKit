"""PALFIX1: PALMERGE — SLIM29's hurt art in the class banks *without* the ten extra palettes.

The 19-palette build put the new cells at `pal = 10`. The engine resolves a cell's palette as
`pal_base + min(cell.pal + rank, npalettes - 1)` (kit renderer d5lib/anm.py:1180; the engine's own
rank byte is the same offset), so `pal = 10` forced the bank to carry palettes 10..19 — a second copy
of the character's ten rank palettes, and the payload category LIVE39 proved is the wheel-killer.

PALMERGE keeps TEST28's ten palettes and puts the new cells back at `pal = 0`, so rank p draws them
with palette p. For that to be pixel-identical to SLIM29, every art pixel index i must land on an
entry j that already carries the *whole ten-rank colour vector* of palette 10+p, i.e.
    TEST28 palette[p][j] == SLIM29 palette[10+p][i]   for p = 0..9.
An entry j whose ten-rank vector matches is reused untouched; if none exists, an entry that no base
cell pixel indexes is repainted with that vector (base art cannot see it). Only if both run out does
the tool fall back to a nearest-colour remap and record its CIELAB error.

Also applies the EDFDIFF1 param fix: every key whose `param` is past the end of table 9 (60 per bank,
2 x param-count + {0,15,30,36,42,57}) is re-based to 0, a valid triple.

usage: python tools/palfix1_build.py [out dir]
"""
from __future__ import annotations

import hashlib
import copy
import json
import shutil
import sys
from pathlib import Path

import numpy as np

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
SLIM = ROOT / 'Builds/WHEELMEM1-20261102/slim29/mods'
LIVE_PROFILE = ROOT / 'Local/Installed D5ModKit/profiles/LIVE5_TEST28'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Builds/PALFIX1-20261102/palmerge'
REL = base.REL
NAME = 'LIVE5_PALMERGE'
CLASS_MODS = ('D1C_Class_11390', 'D1C_Class_11400')
TAB = ('nodes', 'keys', 'cells', 'transforms', 'pivots', 'colors', 'params')
TAB_INDEX = {'nodes': 1, 'keys': 2, 'cells': 5, 'transforms': 6,
             'pivots': 7, 'colors': 8, 'params': 9}


def srgb_to_lab(rgba):
    c = np.asarray(rgba, np.float64)[:, :3] / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = (c @ M.T) / np.array([0.95047, 1.0, 1.08883])
    d = 6 / 29
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4 / 29)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def pixels(a, c):
    tex = a.textures[c.tex]
    m = np.frombuffer(tex.data, np.uint8).reshape(tex.height, tex.width)
    return m[c.y:c.y + c.h, c.x:c.x + c.w]


def mapped_rect(a, c, mapping):
    rows = []
    for y in range(c.y, c.y + c.h):
        row = pixels(a, c)[y - c.y]
        rows.append(bytes(mapping[int(v)] for v in row))
    return rows


def build(mod, bank, stats):
    t28 = anm.load(base.bank_path(mod, bank))
    slim = anm.load(SLIM / mod / REL / bank)
    b28, bs = t28.block, slim.block
    npal = len(b28.palette_infos)
    assert npal == len(t28.palettes) == 10, (mod, bank, 'base palettes')
    assert len(bs.palette_infos) == 20, 'SLIM29 must carry the ten added palettes'

    # ---- the ten-rank colour vectors ------------------------------------------------
    T = np.stack([anm.get_palette(t28, p) for p in range(npal)])                 # (10,256,4)
    S = np.stack([anm.get_palette(slim, 10 + p) for p in range(npal)])           # target
    use = np.zeros(256, np.int64)
    for c in b28.cells:
        if c.w and c.h:
            use += np.bincount(pixels(t28, c).ravel(), minlength=256)
    free = [int(i) for i in np.nonzero(use == 0)[0]]

    new_cells = bs.cells[len(b28.cells):]
    art_idx = sorted({int(i) for c in new_cells for i in np.unique(pixels(slim, c))})
    byvec = {}
    for j in range(256):
        byvec.setdefault(T[:, j].tobytes(), []).append(j)

    mapping, how = {}, {}
    for i in art_idx:
        k = S[:, i].tobytes()
        if k in byvec:
            mapping[i] = byvec[k][0]
            how[i] = 'existing'
        elif free:
            j = free.pop(0)
            for p in range(npal):
                T[p, j] = S[p, i]
            mapping[i] = j
            how[i] = 'free'
        else:
            # nearest remap: closest existing ten-rank vector in CIELAB, worst rank decides
            lab_s = srgb_to_lab(np.repeat(S[:, i][None, :, :], 1, 0).reshape(-1, 4))
            best, bestj = None, 0
            for j in range(256):
                d = np.linalg.norm(srgb_to_lab(T[:, j]) - lab_s, axis=1).max()
                if best is None or d < best:
                    best, bestj = d, j
            mapping[i] = bestj
            how[i] = 'nearest'
            stats.setdefault('nearest_error', []).append(float(best))

    # ---- the built member -----------------------------------------------------------
    out = anm.load(t28.to_bytes())              # independent copy
    b = out.block
    assert len(b.cells) == len(b28.cells)
    # textures: SLIM29 pasted the art into TEST28's free atlas space; outside the new cells the
    # bytes must be TEST28's own. Assert that before trusting them.
    for ti in range(len(t28.textures)):
        a = np.frombuffer(t28.textures[ti].data, np.uint8).reshape(t28.textures[ti].height, t28.textures[ti].width)
        s = np.frombuffer(slim.textures[ti].data, np.uint8).reshape(slim.textures[ti].height, slim.textures[ti].width)
        cover = np.zeros(a.shape, np.uint8)
        for c in new_cells:
            if c.tex == ti:
                cover[c.y:c.y + c.h, c.x:c.x + c.w] = 1
        assert (a[cover == 0] == s[cover == 0]).all(), (mod, bank, ti, 'base atlas changed')
        out.textures[ti].data = slim.textures[ti].data
        out.textures[ti].fmt, out.textures[ti].width = slim.textures[ti].fmt, slim.textures[ti].width
        out.textures[ti].height, out.textures[ti].unk = slim.textures[ti].height, slim.textures[ti].unk
        # repaint the cells' palette indices
        buf = bytearray(out.textures[ti].data)
        stride = out.textures[ti].width
        for c in new_cells:
            if c.tex != ti:
                continue
            for r, row in enumerate(mapped_rect(slim, c, mapping)):
                buf[(c.y + r) * stride + c.x:(c.y + r) * stride + c.x + c.w] = row
        out.textures[ti].data = bytes(buf)

    # cells: the appended rectangles, pal back to 0 (rank offsets them into 0..9)
    n0 = len(b.cells)
    for c in new_cells:
        b.cells.append(anm.Cell(c.tex, 0, c.unk2, c.flags, c.x, c.y, c.w, c.h, c.unk8))
    # table tails and the animation table are SLIM29's (cells were appended above, pal 0)
    for name in TAB:
        if name == 'cells':
            assert bs.cells[n0:] and len(bs.cells[n0:]) == len(b.cells) - n0
            continue
        mine, theirs = getattr(b, name), getattr(bs, name)
        k = len(t28.block.tables()[TAB_INDEX[name]])
        assert theirs[:k] == mine[:k], (name, 'TEST28 prefix differs from SLIM29')
        getattr(b, name).extend(theirs[k:])
    assert len(bs.animations) == len(b28.animations)
    b.animations = copy.deepcopy(bs.animations)

    # palettes: TEST28's ten, plus the free-slot colours
    for p in range(npal):
        out.palettes[p].data = np.asarray(T[p][:, [3, 0, 1, 2]], np.uint8).tobytes()
    b.palette_infos = [anm.PaletteInfo(0, 256, 0) for _ in range(npal)]

    # EDFDIFF1: every out-of-range key.param -> 0 (a valid triple)
    bad = [k for k in b.keys if k.param >= len(b.params)]
    for k in bad:
        k.param = 0

    f = anm.AnmFile([b], out.textures, out.palettes, t28.hdr_unk, t28.trailing)
    b.fix_virtual_offsets()
    raw = f.to_bytes()
    back = anm.load(raw).to_bytes()
    assert back == raw, (mod, bank, 'serialize roundtrip')

    # ---- proof ----------------------------------------------------------------------
    chk = anm.load(raw)
    for p in range(npal):
        assert (anm.get_palette(chk, p) == T[p]).all()
    for i, j in mapping.items():
        for p in range(npal):
            assert (anm.get_palette(chk, p)[j] == S[p, i]).all(), (i, j, p)
    for n, c in enumerate(new_cells):
        assert pixels(chk, chk.block.cells[len(b28.cells) + n]).tolist() == \
            [[mapping[int(v)] for v in row] for row in pixels(slim, c).tolist()]
    stats.update({'palettes': npal, 'art_indices': len(art_idx),
                  'existing': sum(1 for v in how.values() if v == 'existing'),
                  'free_slot': sum(1 for v in how.values() if v == 'free'),
                  'nearest': sum(1 for v in how.values() if v == 'nearest'),
                  'free_slots_left': len(free), 'param_fixed': len(bad),
                  'cells_added': len(new_cells), 'raw': len(raw),
                  'test28_raw': len(t28.to_bytes()), 'slim_raw': len(slim.to_bytes())})
    return raw, chk


def main():
    n = base.require_base_set()
    print(f'TEST28 base asserted: {n} pinned banks', flush=True)
    order = json.loads((LIVE_PROFILE / 'load_order.json').read_text())
    assert len(order) == 188, len(order)
    doc = json.loads((LIVE_PROFILE / 'profile.json').read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / 'mods').mkdir(parents=True)
    report = {'profile': NAME, 'banks': {}, 'load_order_len': len(order)}
    for mod in base.manifest()['banks']:
        shutil.copytree(base.base_dir(mod) / mod, OUT / 'mods' / mod)   # 17 uniques stay TEST28
    for mod in CLASS_MODS:
        for bank in base.manifest()['banks'][mod]:
            stats = {}
            raw, _ = build(mod, bank, stats)
            dst = OUT / 'mods' / mod / REL / bank
            dst.write_bytes(anm.lzs_compress(raw))
            assert anm.load(dst.read_bytes()).to_bytes() == raw
            stats['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()
            stats['raw_sha256'] = hashlib.sha256(raw).hexdigest()
            report['banks'][f'{mod}/{bank}'] = stats
            print(f"  {mod}/{bank}: raw {len(raw):,} (TEST28 {stats['test28_raw']:,}, "
                  f"SLIM29 {stats['slim_raw']:,}) art {stats['art_indices']} -> "
                  f"existing {stats['existing']} / free {stats['free_slot']} / "
                  f"nearest {stats['nearest']}, params fixed {stats['param_fixed']}", flush=True)
    pdir = OUT / 'profile' / NAME
    pdir.mkdir(parents=True)
    (pdir / 'load_order.json').write_text(json.dumps(order, indent=1) + '\n')
    d = dict(doc); d['name'] = NAME
    (pdir / 'profile.json').write_text(json.dumps(d, indent=1) + '\n')

    # file delta vs TEST28
    changed, identical = [], 0
    for mod in base.manifest()['banks']:
        src, dst = base.base_dir(mod) / mod, OUT / 'mods' / mod
        rels = {p.relative_to(src) for p in src.rglob('*') if p.is_file()}
        assert rels == {p.relative_to(dst) for p in dst.rglob('*') if p.is_file()}, mod
        for rel in sorted(rels):
            if (src / rel).read_bytes() == (dst / rel).read_bytes():
                identical += 1
            else:
                changed.append(f'{mod}/{rel.relative_to(REL)}')
    report.update({'files': identical + len(changed), 'identical': identical, 'changed_banks': changed})
    assert len(changed) == 4, changed
    ev = OUT.parent / 'evidence'
    ev.mkdir(parents=True, exist_ok=True)
    (ev / 'build.json').write_text(json.dumps(report, indent=1) + '\n')
    print(f'{identical} files identical, changed: {changed}')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
