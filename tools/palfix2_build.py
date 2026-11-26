"""PALFIX2: map SLIM29 unique hurt art into TEST28's existing 20 palettes.

Derived from palfix1_build.py. New cells use palette 10; source uses 20. Matching
vectors over ten ranks preserves the renderer clamp for all higher rank values.
Only unused palette indices can be changed. A nearest match must have at most
one alpha-unit error and at most 2 CIE76 dE. Both views of an ineligible unique
remain TEST28. The 60 invalid key parameters per touched bank are rebased.
Run only in an offline workspace; refuses to overwrite an existing output.
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
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Builds/PALFIX2-20261102/palmerge2'
REL = base.REL
NAME = 'LIVE5_PALMERGE2'
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
    assert npal == len(t28.palettes) == 20
    assert len(bs.palette_infos) == 30
    use = np.zeros(256, np.int64)
    for c in b28.cells:
        if c.w and c.h:
            use += np.bincount(pixels(t28, c).ravel(), minlength=256)
    new_cells = bs.cells[len(b28.cells):]
    art_idx = sorted({int(i) for c in new_cells for i in np.unique(pixels(slim, c))})
    S = np.stack([anm.get_palette(slim, 20 + p) for p in range(10)])
    allT = np.stack([anm.get_palette(t28, p) for p in range(npal)])
    offset = 10  # source and destination both clamp after rank 9
    T = allT[offset:offset + 10]
    byvec = {}
    # Prefer used entries for matches: this preserves more free slots.
    for j in sorted(range(256), key=lambda j: (use[j] == 0, j)):
        byvec.setdefault(T[:, j].tobytes(), j)
    target_vectors = {S[:, i].tobytes() for i in art_idx}
    reserved = {byvec[v] for v in target_vectors if v in byvec}
    free = [int(i) for i in np.nonzero(use == 0)[0] if i not in reserved]
    mapping, how = {}, {}
    errors = []
    for i in art_idx:
        k = S[:, i].tobytes()
        if k in byvec:
            mapping[i], how[i] = byvec[k], 'existing'
        elif free:
            j = free.pop(0)
            T[:, j] = S[:, i]
            byvec[k] = j
            mapping[i], how[i] = j, 'free'
        else:
            lab_s = srgb_to_lab(S[:, i])
            # Alpha must be exact; CIELAB alone does not capture transparency.
            candidates = [j for j in range(256) if np.abs(T[:, j, 3].astype(int) - S[:, i, 3].astype(int)).max() <= 1]
            if not candidates:
                raise ValueError('no alpha-compatible palette entry')
            dist = [(float(np.linalg.norm(srgb_to_lab(T[:, j]) - lab_s, axis=1).max()), j)
                    for j in candidates]
            d, j = min(dist)
            mapping[i], how[i] = j, 'nearest'
            errors.append(d)
    stats['max_de'] = max(errors, default=0.0)
    stats['mean_de'] = float(np.mean([np.linalg.norm(srgb_to_lab(T[:, j]) - srgb_to_lab(S[:, i]), axis=1).mean() for i, j in mapping.items()]))
    stats['max_alpha_error'] = max(int(np.abs(T[:, j, 3].astype(int) - S[:, i, 3].astype(int)).max()) for i, j in mapping.items())
    stats['palette_offset'] = offset
    if stats['max_de'] > 2:
        raise ValueError('colour error exceeds 2 dE: %.4f' % stats['max_de'])

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

    # cells: palette 10 makes ranks 0..9 select palettes 10..19 and clamp thereafter
    n0 = len(b.cells)
    for c in new_cells:
        b.cells.append(anm.Cell(c.tex, offset, c.unk2, c.flags, c.x, c.y, c.w, c.h, c.unk8))
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
        out.palettes[p].data = np.asarray(allT[p][:, [3, 0, 1, 2]], np.uint8).tobytes()
    # Keep TEST28 palette descriptors byte-for-byte.
    assert len(b.palette_infos) == npal

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
        assert (anm.get_palette(chk, p) == allT[p]).all()
    for i, j in mapping.items():
        for p in range(10):
            if how[i] != 'nearest':
                assert (anm.get_palette(chk, offset + p)[j] == S[p, i]).all(), (i, j, p)
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
    base.require_base_set()
    source = ROOT / 'Builds/PALFIX1-20261102/palmerge'
    if OUT.exists():
        raise SystemExit(f'refusing to replace existing output: {OUT}')
    shutil.copytree(source, OUT)
    report = {'profile': NAME, 'banks': {}, 'excluded': {}, 'load_order_len': 188}
    for mod in base.manifest()['banks']:
        if not mod.startswith('D1C_Unique_'):
            continue
        candidates = []
        try:
            for bank in base.manifest()['banks'][mod]:
                stats = {}
                raw, _ = build(mod, bank, stats)
                candidates.append((bank, raw, stats))
        except ValueError as e:
            report['excluded'][mod] = str(e)
            print(f'{mod}: excluded: {e}', flush=True)
            continue
        for bank, raw, stats in candidates:
            dst = OUT / 'mods' / mod / REL / bank
            dst.write_bytes(anm.lzs_compress(raw))
            assert anm.load(dst.read_bytes()).to_bytes() == raw
            stats['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()
            report['banks'][f'{mod}/{bank}'] = stats
            print(f'{mod}/{bank}: {stats}', flush=True)
    old = OUT / 'profile' / 'LIVE5_PALMERGE'
    new = OUT / 'profile' / NAME
    old.rename(new)
    profile = json.loads((new / 'profile.json').read_text()); profile['name'] = NAME
    (new / 'profile.json').write_text(json.dumps(profile, indent=1) + '\n')
    assert len(json.loads((new / 'load_order.json').read_text())) == 188
    report['changed_banks'] = list(report['banks'])
    ev = OUT.parent / 'evidence'; ev.mkdir(parents=True, exist_ok=True)
    (ev / 'build.json').write_text(json.dumps(report, indent=1) + '\n')
    print('wrote', OUT, flush=True)

if __name__ == '__main__':
    main()
