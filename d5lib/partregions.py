"""Regions of a sprite sheet: every pose split into areas that belong to one part each (one piece of cloth, the
hair, an arm ...), bounded by the drawing's dark lines and by real colour changes -- shading inside a part
(lighter / darker of the same colour) does not split it.

Graph segmentation (Felzenszwalb-Huttenlocher) on the pixel grid: neighbours are joined from the most similar pair
up, as long as their difference is small compared with the differences already inside the two regions.  The
colour difference counts hue and saturation fully and lightness only partly (shading).  Very dark pixels (outlines)
stay out of the graph and join the nearest region afterwards; tiny regions join their most similar neighbour.

segment() -> region id per pixel (-1 transparent); regions never cross poses."""
import numpy as np
from scipy import ndimage

L_WEIGHT = 0.35       # lightness difference counts this much (shading inside a part)
K = 220.0             # Felzenszwalb scale: larger = larger regions
MIN_SIZE = 12         # smaller regions join their most similar neighbour
DARK_L = 16.0         # Lab lightness below this = outline / line art


def _lab(rgb):
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


class _DSU:
    def __init__(self, n):
        self.p = np.arange(n)
        self.size = np.ones(n, np.int64)
        self.inner = np.zeros(n)

    def find(self, a):
        p = self.p
        r = a
        while p[r] != r:
            r = p[r]
        while p[a] != r:
            p[a], a = r, p[a]
        return r


def segment(ind, op, pal, k=K, min_size=MIN_SIZE, dark_l=DARK_L, l_weight=L_WEIGHT):
    """ind: colour index per pixel, op: opaque mask, pal: (256, 4) palette -> region id per pixel (-1 = none)"""
    H, W = ind.shape
    lab_pal = _lab(pal[:, :3])
    lab = lab_pal[ind]
    dark = op & (lab[..., 0] < dark_l)
    node = op & ~dark
    idx = np.full((H, W), -1, np.int64)
    ys, xs = np.nonzero(node)
    idx[ys, xs] = np.arange(len(ys))
    n = len(ys)
    if not n:
        return np.where(op, 0, -1)
    scale = np.array([l_weight, 1.0, 1.0])
    edges_a, edges_b, weights = [], [], []
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = idx[0:H - dy, max(0, -dx):W - max(0, dx)]
        b = idx[dy:H, max(0, dx):W - max(0, -dx)]
        m = (a >= 0) & (b >= 0)
        aa, bb = a[m], b[m]
        d = np.sqrt((((lab[ys[aa], xs[aa]] - lab[ys[bb], xs[bb]]) * scale) ** 2).sum(1))
        if dy and dx:
            d = d * 1.15                     # diagonal neighbours: a little weaker
        edges_a.append(aa)
        edges_b.append(bb)
        weights.append(d)
    ea, eb, w = np.concatenate(edges_a), np.concatenate(edges_b), np.concatenate(weights)
    order = np.argsort(w, kind="stable")
    ds = _DSU(n)
    p, size, inner = ds.p, ds.size, ds.inner
    find = ds.find
    for e in order.tolist():
        ra, rb = find(ea[e]), find(eb[e])
        if ra == rb:
            continue
        we = w[e]
        if we <= min(inner[ra] + k / size[ra], inner[rb] + k / size[rb]):
            if size[ra] < size[rb]:
                ra, rb = rb, ra
            p[rb] = ra
            size[ra] += size[rb]
            inner[ra] = we
    # tiny regions -> the most similar neighbour (edges in order: the first edge to a big region wins)
    for e in order.tolist():
        ra, rb = find(ea[e]), find(eb[e])
        if ra != rb and (size[ra] < min_size or size[rb] < min_size):
            if size[ra] < size[rb]:
                ra, rb = rb, ra
            p[rb] = ra
            size[ra] += size[rb]
    roots = np.array([find(i) for i in range(n)])
    _, lab_ids = np.unique(roots, return_inverse=True)
    out = np.full((H, W), -1, np.int64)
    out[ys, xs] = lab_ids
    # dark pixels: the nearest region (touching the same pose)
    if dark.any():
        _, (iy, ix) = ndimage.distance_transform_edt(out < 0, return_indices=True)
        out[dark] = out[iy[dark], ix[dark]]
    return out
