"""Carry finished colour parts from one build of an outfit sprite to another build of the same drawings (the frames
re-cut / re-packed): every frame of the new sheets is found in the old sheets by its pixels, and each pixel takes the
part its twin had.  Pixels without a twin (bits the old build didn't have) take the part of the nearest pixel that
has one."""
import numpy as np
from scipy import ndimage
from scipy.signal import fftconvolve

from . import anm

STRONG = 8          # alpha above this is drawing (below: compression noise)
TOL = 12            # RGB difference still "the same pixel" (palettes are quantized separately)


def _cells(sprite):
    pal = anm.get_palette(sprite, 0)
    rgba = {t: pal[anm.texture_indices(sprite, t)] for t, x in enumerate(sprite.textures) if x.indexed}
    out = []
    b = sprite.blocks[0]
    for ci, c in enumerate(b.cells):
        t = b.tex_base + c.tex
        if c.w * c.h == 0 or t not in rgba:
            continue
        out.append((ci, t, c.x, c.y, c.w, c.h, rgba[t][c.y:c.y + c.h, c.x:c.x + c.w]))
    return out, rgba


def transfer(old_sprite, old_rows, new_sprite, log=None, fill=True):
    """old_rows: {tex: part per pixel} of old_sprite -> {tex: part per pixel} for new_sprite (-1 transparent);
    fill=False: (rows with -1 where no twin was found, {tex: found mask}, [new cells without a twin])"""
    old, _ = _cells(old_sprite)
    new, new_rgba = _cells(new_sprite)
    rows = {t: np.full(img.shape[:2], -1, np.int32) for t, img in new_rgba.items()}
    known = {t: np.zeros(img.shape[:2], bool) for t, img in new_rgba.items()}
    olds = []
    for ci, t, x, y, w, h, img in old:
        m = img[..., 3] > STRONG
        if m.sum() < 20:
            continue
        olds.append((m.sum(), m, img, old_rows[t][y:y + h, x:x + w]))
    matched = 0
    unmatched = []
    for ci, t, x, y, w, h, img in new:
        m = img[..., 3] > STRONG
        n = int(m.sum())
        if n < 20:
            continue
        best = None
        for cnt, om, oimg, olab in olds:
            if not (0.6 * n <= cnt <= 1.4 * n):
                continue
            c = fftconvolve(m.astype(np.float32), om[::-1, ::-1].astype(np.float32), mode="full")
            k = np.unravel_index(int(c.argmax()), c.shape)
            dy, dx = k[0] - (om.shape[0] - 1), k[1] - (om.shape[1] - 1)      # old top-left in new coords
            # overlap region
            y0, x0 = max(0, dy), max(0, dx)
            y1, x1 = min(h, dy + om.shape[0]), min(w, dx + om.shape[1])
            if y1 <= y0 or x1 <= x0:
                continue
            a = img[y0:y1, x0:x1].astype(np.int16)
            b = oimg[y0 - dy:y1 - dy, x0 - dx:x1 - dx].astype(np.int16)
            both = (a[..., 3] > STRONG) & (b[..., 3] > STRONG)
            same = both & (np.abs(a[..., :3] - b[..., :3]).max(-1) <= TOL)
            score = same.sum() / max(1, n)
            if best is None or score > best[0]:
                best = (score, dy, dx, olab, oimg)
        if best is None or best[0] < 0.6:
            unmatched.append((t, x, y, x + w, y + h))
            continue
        score, dy, dx, olab, oimg = best
        matched += 1
        y0, x0 = max(0, dy), max(0, dx)
        y1, x1 = min(h, dy + olab.shape[0]), min(w, dx + olab.shape[1])
        lab = olab[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
        ok = (lab >= 0) & (img[y0:y1, x0:x1, 3] > 0)
        sub = rows[t][y:y + h, x:x + w][y0:y1, x0:x1]
        kn = known[t][y:y + h, x:x + w][y0:y1, x0:x1]
        sub[ok] = lab[ok]
        kn[ok] = True
    if not fill:
        if log:
            log(f"  parts carried over: {matched} frames found, {len(unmatched)} without a twin")
        return rows, known, unmatched
    # the rest: the part of the nearest known pixel
    for t, img in new_rgba.items():
        op = img[..., 3] > 0
        miss = op & ~known[t]
        if miss.any() and known[t].any():
            _, (iy, ix) = ndimage.distance_transform_edt(~known[t], return_indices=True)
            rows[t][miss] = rows[t][iy[miss], ix[miss]]
        rows[t][~op] = -1
    if log:
        n_new = sum(1 for c in new if (c[6][..., 3] > STRONG).sum() >= 20)
        miss = sum(int(((new_rgba[t][..., 3] > 0) & ~known[t]).sum()) for t in new_rgba)
        log(f"  parts carried over: {matched} of {n_new} frames found, {miss} px filled from neighbours")
    return rows
