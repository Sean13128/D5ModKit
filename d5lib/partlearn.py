"""Learn parts from reference poses: the parts painted (or checked) on one or a few poses are carried over to every
other frame of the sprite.

Every colour that the reference poses give (almost) always one part takes that part everywhere.  Colours the
reference poses use for several parts (a highlight white shared by a hoodie and the legs, a skin tone seen
through a shirt ...) are decided per pixel from what surrounds it: the parts around it at two distances, the
colour families right next to it and how far down the pose it is; the reference pixels of the same colour with
the most similar surroundings vote.  This is repeated with the new parts as surroundings, then lone pixels are
smoothed away.  Colours that the reference poses don't contain keep their automatic part."""
import numpy as np
from scipy import ndimage

FIRM = 0.93           # share of one part above which a colour is firm (the same part everywhere)
RADII = (2, 6)        # surroundings: box half-sizes of the part histograms
MAT_RADIUS = 2        # colour families right around the pixel
POS_WEIGHT = 2.0      # weight of the height in the pose (0 top .. 1 feet)
UNSURE = 2.5          # a pixel whose surroundings are this much farther from every reference pixel than the
                      # reference pixels are from each other keeps its automatic part (e.g. a back view when only
                      # a front pose was given)
K = 9
ROUNDS = 3
CHUNK = 4096


def pose_boxes(op, gap=2):
    """the separate drawings (poses) on a sheet: (label image, [slices]) of the opaque pixels, pieces closer than
    `gap` px joined"""
    grown = ndimage.binary_dilation(op, iterations=gap) if gap else op
    lab, _ = ndimage.label(grown, structure=np.ones((3, 3), bool))
    lab[~op] = 0
    return lab, ndimage.find_objects(lab)


def _height(op):
    """0 at the top of each pose .. 1 at its feet"""
    lab, sls = pose_boxes(op)
    top = np.zeros(op.shape, np.float32)
    height = np.ones(op.shape, np.float32)
    for i, sl in enumerate(sls, 1):
        if sl is None:
            continue
        m = lab[sl] == i
        top[sl][m] = sl[0].start
        height[sl][m] = max(1, sl[0].stop - sl[0].start)
    ys = np.arange(op.shape[0], dtype=np.float32)[:, None]
    return (ys - top) / height


def _box(ch, r):
    return ndimage.uniform_filter(ch.astype(np.float32), 2 * r + 1, mode="constant")


class _Static:
    """the features that don't change between rounds: colour families around the pixel + height in the pose"""
    def __init__(self, ind, op, mat, mats):
        self.feats = [_box(op & (mat[ind] == m), MAT_RADIUS) for m in mats] + [_height(op) * POS_WEIGHT]


def _features(static, rows, op, parts):
    chans = [rows == p for p in parts] + [op & (rows < 0), ~op]
    return np.stack([_box(ch, r) for r in RADII for ch in chans] + static.feats, -1)


def _knn_vote(X, y, Q, k):
    """labels voted by the k nearest training rows (squared euclidean, brute force in chunks)
    -> (labels, distance to the nearest training row)"""
    k = min(k, len(X))
    xx = (X * X).sum(1)
    out = np.empty(len(Q), np.int32)
    near = np.empty(len(Q), np.float32)
    for s in range(0, len(Q), CHUNK):
        q = Q[s:s + CHUNK]
        d = (q * q).sum(1)[:, None] + xx[None] - 2 * q @ X.T
        idx = np.argpartition(d, k - 1, axis=1)[:, :k]
        dd = np.take_along_axis(d, idx, 1)
        near[s:s + CHUNK] = np.sqrt(np.maximum(dd.min(1), 0))
        w = 1.0 / (np.sqrt(np.maximum(dd, 0)) + 0.05)
        votes = np.zeros((len(q), 16), np.float32)
        lab = np.clip(y[idx], 0, 15)
        for j in range(k):
            np.add.at(votes, (np.arange(len(q)), lab[:, j]), w[:, j])
        out[s:s + CHUNK] = votes.argmax(1)
    return out, near


def _spread(X, sample=1500):
    """typical distance from a training row to its nearest other training row"""
    if len(X) < 3:
        return 0.3
    rng = np.random.default_rng(1)
    S = X[rng.choice(len(X), min(sample, len(X)), replace=False)]
    d = (S * S).sum(1)[:, None] + (X * X).sum(1)[None] - 2 * S @ X.T
    d = np.sort(np.maximum(d, 0), 1)[:, 1]              # [:, 0] is the row itself
    return float(np.sqrt(np.median(d)))


def _smooth(rows, free, parts, passes=2):
    """pixels in `free` take the most common part of their 5x5 surroundings (when it clearly dominates)"""
    for _ in range(passes):
        counts = np.stack([ndimage.uniform_filter((rows == p).astype(np.float32), 5, mode="constant")
                           for p in parts], -1)
        best = np.asarray(parts)[counts.argmax(-1)]
        top = counts.max(-1)
        own = np.take_along_axis(counts, np.searchsorted(parts, np.clip(rows, parts[0], parts[-1]))[..., None],
                                 -1)[..., 0]
        change = free & (best != rows) & (top >= own + 0.12)
        rows[change] = best[change]
    return rows


def learn(ind, op, labels, refs, mat, ncolours=256, log=None):
    """ind/op/labels: {tex: colour index / opaque mask / current part per pixel}; refs: [(tex, x0, y0, x1, y1)]
    reference rectangles (their `labels` are the truth); mat: colour -> colour family.  -> {tex: learned part
    per pixel, -1 = no opinion (inside the references, and colours they don't contain)}"""
    texs = list(ind)
    inref = {t: np.zeros(ind[t].shape, bool) for t in texs}
    for t, x0, y0, x1, y1 in refs:
        if t in inref:
            inref[t][y0:y1, x0:x1] = True
    for t in texs:
        inref[t] &= op[t]
    counts = np.zeros((ncolours, 16), np.int64)
    for t in texs:
        m = inref[t] & (labels[t] >= 0)
        np.add.at(counts, (ind[t][m], np.clip(labels[t][m], 0, 15)), 1)
    total = counts.sum(1)
    seen = total > 0
    share = np.where(seen, counts.max(1) / np.maximum(total, 1), 0)
    firm = np.where(seen & (share >= FIRM), counts.argmax(1), -1)
    ambiguous = seen & (share < FIRM)
    parts = sorted(int(p) for p in np.nonzero(counts.sum(0))[0])
    rows, out = {}, {}
    for t in texs:
        # outside the references: firm colours their part, ambiguous ones undecided (-1), unknown ones as they were
        r = np.where(op[t], np.where(seen[ind[t]], firm[ind[t]], labels[t]), -1)
        rows[t] = np.where(inref[t], labels[t], r).astype(np.int32)
    amb = {t: op[t] & ~inref[t] & ambiguous[ind[t]] for t in texs}
    if ambiguous.any() and any(a.any() for a in amb.values()):
        mats = sorted({int(mat[c]) for c in np.nonzero(seen)[0]})
        static = {t: _Static(ind[t], op[t], mat, mats) for t in texs}
        colours = np.nonzero(ambiguous)[0]
        for rnd in range(ROUNDS):
            feats = {t: _features(static[t], rows[t], op[t], parts) for t in texs}
            new = {t: rows[t].copy() for t in texs}
            for c in colours:
                X = [feats[t][inref[t] & (ind[t] == c)] for t in texs]
                y = [labels[t][inref[t] & (ind[t] == c)] for t in texs]
                X, y = np.concatenate(X), np.concatenate(y)
                if not len(X):
                    continue
                limit = UNSURE * max(_spread(X), 0.05) + 0.1
                for t in texs:
                    m = amb[t] & (ind[t] == c)
                    if m.any():
                        pred, near = _knn_vote(X, y, feats[t][m], K)
                        new[t][m] = np.where(near <= limit, pred, labels[t][m])
            rows = new
            if log:
                log(f"  learning parts: round {rnd + 1}/{ROUNDS}")
        for t in texs:
            rows[t] = _smooth(rows[t], amb[t], parts)
    for t in texs:
        out[t] = np.where(op[t] & ~inref[t] & seen[ind[t]], rows[t], -1).astype(np.int32)
    return out


# ====================================================================== patch transfer
# A pose painted right ("key pose") is carried over to the other poses pixel by pixel: every pixel looks for the spot
# of a key pose whose 5x5 surroundings look the most like its own (colours and transparency), within a window
# around the same place of the figure, and takes that spot's part.  Colours the key poses always give one part
# keep that part directly.  Mirrored key poses are tried too.

PATCH = 2               # patch half size (5x5)
SEARCH = 14             # search window half size (px) around the aligned position
OFFSET_COST = 0.001     # per px^2 of offset (x100): prefer the nearer match among equals
FIRM_SHARE = 0.985


def _lab_of(pal):
    from .partregions import _lab
    return _lab(pal[:, :3]).astype(np.float32)


def _feat(ind, op, lab_pal):
    """per pixel: L a b (scaled) + opacity flag"""
    f = np.zeros(ind.shape + (4,), np.float32)
    f[..., :3] = lab_pal[ind] * np.array([0.6, 1.0, 1.0], np.float32)
    f[..., 3] = np.where(op, 0.0, 60.0)
    f[~op, :3] = 0
    return f


def _closest(keys, top, n):
    """the n (key, mirrored?) pairs whose silhouette fits the target best (bottom centres aligned)"""
    ty, tx = np.nonzero(top)
    if not len(ty):
        return []
    scored = []
    for kind, kop, klab in keys:
        for flip in (False, True):
            ko = kop[:, ::-1] if flip else kop
            ky, kx = np.nonzero(ko)
            if not len(ky):
                continue
            dy = int(ty.max() - ky.max())
            dx = int(round((tx.min() + tx.max()) / 2 - (kx.min() + kx.max()) / 2))
            a = set(zip((ky + dy).tolist(), (kx + dx).tolist()))
            b = set(zip(ty.tolist(), tx.tolist()))
            iou = len(a & b) / max(1, len(a | b))
            scored.append((iou, kind, kop, klab, flip))
    scored.sort(key=lambda r: -r[0])
    return [(k, o, l, f) for _, k, o, l, f in scored[:n]]


def transfer(keys, target, lab_pal, search=SEARCH, best_n=2):
    """keys: [(ind, op, labels)] crops of key poses; target: (ind, op) crop -> (labels, cost) for the target crop
    (-1 where transparent)"""
    tind, top = target
    H, W = tind.shape
    tf = _feat(tind, top, lab_pal)
    best = np.full((H, W), np.inf, np.float32)
    lab = np.full((H, W), -1, np.int32)
    ker = 2 * PATCH + 1
    for kind, kop, klab, flip in _closest(keys, top, best_n):
        if True:
            ki, ko, kl = (kind[:, ::-1], kop[:, ::-1], klab[:, ::-1]) if flip else (kind, kop, klab)
            kf = _feat(ki, ko, lab_pal)
            kh, kw = ki.shape
            # align bottom centres of the two drawings
            ty, tx = np.nonzero(top)
            ky, kx = np.nonzero(ko)
            if not len(ty) or not len(ky):
                continue
            ay = int(ty.max() - ky.max())
            ax = int(round((tx.min() + tx.max()) / 2 - (kx.min() + kx.max()) / 2))
            pad = search + PATCH + 2
            P = np.zeros((kh + 2 * pad, kw + 2 * pad, 4), np.float32)
            P[..., 3] = 60.0
            P[pad:pad + kh, pad:pad + kw] = kf
            PL = np.full((kh + 2 * pad, kw + 2 * pad), -1, np.int32)
            PL[pad:pad + kh, pad:pad + kw] = kl
            for dy in range(-search, search + 1):
                for dx in range(-search, search + 1):
                    # target pixel (y, x) <-> key pixel (y - ay + dy, x - ax + dx)
                    oy, ox = pad - ay + dy, pad - ax + dx
                    y0, x0 = max(0, -oy), max(0, -ox)
                    y1, x1 = min(H, P.shape[0] - oy), min(W, P.shape[1] - ox)
                    if y1 <= y0 or x1 <= x0:
                        continue
                    src = P[oy + y0:oy + y1, ox + x0:ox + x1]
                    d = np.minimum(((tf[y0:y1, x0:x1] - src) ** 2).sum(-1), 2500.0)
                    c = ndimage.uniform_filter(d, ker, mode="nearest") + d * 0.5 \
                        + OFFSET_COST * (dx * dx + dy * dy) * 100
                    sub_best = best[y0:y1, x0:x1]
                    better = c < sub_best
                    if better.any():
                        sub_best[better] = c[better]
                        lab[y0:y1, x0:x1][better] = PL[oy + y0:oy + y1, ox + x0:ox + x1][better]
    lab[~top] = -1
    return lab, best


def firm_colours(keys, ncolours=256):
    """colour -> part for colours the key poses (almost) always give one part, else -1"""
    counts = np.zeros((ncolours, 16), np.int64)
    for kind, kop, klab in keys:
        m = kop & (klab >= 0)
        np.add.at(counts, (kind[m], np.clip(klab[m], 0, 15)), 1)
    tot = counts.sum(1)
    share = counts.max(1) / np.maximum(tot, 1)
    return np.where((tot >= 3) & (share >= FIRM_SHARE), counts.argmax(1), -1)
