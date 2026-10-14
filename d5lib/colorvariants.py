"""Colour variants (the 'extra colours' of the Strategy Assembly) for a repainted sprite.

A new outfit has a new palette, so the character's own colour presets can't simply be copied.  Instead
every colour of the new palette takes the change the character's preset makes to the most similar
colours of the original look (hue turn, saturation and lightness change): if preset 2 turns her blue
hair gold, the outfit's blue hair turns gold as well; colours without a counterpart follow their
nearest neighbours.
"""
import colorsys

import numpy as np

from . import anm


def _used_indices(sprite):
    counts = np.zeros(256, np.int64)
    for i, t in enumerate(sprite.textures):
        if t.indexed:
            counts += np.bincount(anm.texture_indices(sprite, i).reshape(-1), minlength=256)[:256]
    counts[0] = 0
    return counts


def _hls(rgb):
    return np.array([colorsys.rgb_to_hls(*(c / 255.0)) for c in rgb])


def _role_distance(a_hls, b_hls):
    """Distance between colours for 'which part of the character is this' (rows a, columns b)."""
    ha, la, sa = a_hls[:, 0:1], a_hls[:, 1:2], a_hls[:, 2:3]
    hb, lb, sb = b_hls[None, :, 0], b_hls[None, :, 1], b_hls[None, :, 2]
    dh = np.abs((ha - hb + 0.5) % 1.0 - 0.5)
    vivid = np.minimum(sa, sb) > 0.3               # both clearly coloured
    grey = np.maximum(sa, sb) < 0.2
    d_col = 4.0 * dh + 0.5 * np.abs(la - lb) + 0.3 * np.abs(sa - sb)
    d_grey = np.abs(la - lb) + 1.5 * np.abs(sa - sb)
    d_mix = 1.0 + np.abs(la - lb) + np.abs(sa - sb)    # coloured vs grey: poor match
    return np.where(vivid, d_col, np.where(grey, d_grey, d_mix + 2.0 * dh * (np.minimum(sa, sb) > 0.12)))


def derive_palettes(base_sprite, new_pal0, count=None, k=4, index_group=None, groups=None, anchors=None,
                    plain=None):
    """-> [palette 1, palette 2, ...] (256x4 uint8) for the new palette, following the base sprite's
    colour variants."""
    count = count or len(base_sprite.palettes)
    base0 = anm.get_palette(base_sprite, 0).astype(np.float64)
    used = _used_indices(base_sprite)
    idx = np.nonzero((used > 0) & (base0[:, 3] > 0))[0]
    if len(idx) == 0:
        return []
    b0 = base0[idx, :3]
    b0_hls = _hls(b0)
    new = new_pal0.astype(np.float64)
    new_hls = _hls(new[:, :3])
    # nearest base colours of every new colour: strongly coloured parts match by HUE (a pink hoodie is
    # "clothing like the red scarf", not "skin because it is light"), greys by lightness
    dist = _role_distance(_hls(anchors.astype(np.float64)) if anchors is not None else new_hls, b0_hls)
    if plain is not None and np.any(plain):
        # small details (eyes, mouth): the same colour on the original character, matched as it is
        rows = np.nonzero(plain)[0]
        src = (anchors if anchors is not None else new[:, :3])[rows]
        d = np.linalg.norm(_lab(src)[:, None, :] - _lab(b0)[None, :, :], axis=2) / 40.0
        dist[rows] = d
    if index_group and groups is not None:
        # a colour of a part only takes changes from the character's colours of the same part
        g_idx, g_lab = groups
        lab_of = dict(zip(g_idx.tolist(), g_lab.tolist()))
        base_lab = np.array([lab_of.get(int(i), -1) for i in idx])
        for i, g in index_group.items():
            dist[i, base_lab != g] += 100.0
    near = np.argsort(dist, axis=1)[:, :k]
    out = []
    for p in range(1, count):
        bp = anm.get_palette(base_sprite, min(p, len(base_sprite.palettes) - 1)).astype(np.float64)[idx, :3]
        bp_hls = _hls(bp)
        dh = (bp_hls[:, 0] - b0_hls[:, 0] + 0.5) % 1.0 - 0.5
        dl = bp_hls[:, 1] - b0_hls[:, 1]
        ds = bp_hls[:, 2] - b0_hls[:, 2]
        # a hue turn only means something for coloured (saturated) originals
        colourful = np.clip(b0_hls[:, 2] * 3, 0, 1)
        pal = new_pal0.copy()
        for i in range(1, 256):
            if new[i, 3] == 0:
                continue
            nb = near[i]
            w = 1.0 / (dist[i, nb] + 0.05)
            w = w / w.sum()
            ang = np.angle((w * colourful[nb] * np.exp(2j * np.pi * dh[nb])).sum()) / (2 * np.pi)
            h, l, s = new_hls[i]
            h = (h + ang) % 1.0
            # darkening / desaturating presets scale proportionally (a light pink hoodie follows the
            # dark scarf of a "black" preset); brightening ones add the same amount
            lr = np.where(dl[nb] < 0, bp_hls[nb, 1] / np.maximum(b0_hls[nb, 1], 1e-3), np.nan)
            sr = np.where(ds[nb] < 0, bp_hls[nb, 2] / np.maximum(b0_hls[nb, 2], 1e-3), np.nan)
            l_add = float((w * np.where(dl[nb] >= 0, dl[nb], 0)).sum())
            s_add = float((w * np.where(ds[nb] >= 0, ds[nb], 0)).sum())
            l_mul = float((w * np.nan_to_num(lr, nan=1.0)).sum())
            s_mul = float((w * np.nan_to_num(sr, nan=1.0)).sum())
            l = min(1.0, max(0.0, l * l_mul + l_add))
            s = min(1.0, max(0.0, s * s_mul + s_add))
            pal[i, :3] = np.clip(np.round(np.array(colorsys.hls_to_rgb(h, l, s)) * 255), 0, 255)
        out.append(pal)
    return out


def apply_to_sprite(sprite, palettes):
    """Replace colour variants 1.. of a (single block) sprite."""
    for p, pal in enumerate(palettes, start=1):
        if p < len(sprite.palettes):
            anm.set_palette(sprite, p, pal)
    return sprite


# ------------------------------------------------------------------------------------ parts
def _pack(c):
    c = c.astype(np.uint32)
    return (c[:, 0] << 24) | (c[:, 1] << 16) | (c[:, 2] << 8) | c[:, 3]


def base_groups(base_sprite, threshold=0.6):
    """Colours of the character that change together across its presets (hair, clothes, unchanging
    skin / outlines ...) -> (base palette indices, group label per index)."""
    from scipy.cluster.hierarchy import linkage, fcluster
    p0 = anm.get_palette(base_sprite, 0).astype(np.float64)
    used = _used_indices(base_sprite)
    idx = np.nonzero((used > 0) & (p0[:, 3] > 0))[0]
    n = len(base_sprite.palettes)
    if len(idx) < 2 or n < 2:
        return idx, np.zeros(len(idx), int)
    F = np.concatenate([(anm.get_palette(base_sprite, p)[idx, :3].astype(np.float64) - p0[idx, :3]) / 255.0
                        for p in range(1, n)], 1)
    lab = fcluster(linkage(F, "average"), threshold, "distance")
    return idx, lab


def label_pixels(rgba, base_sprite, groups=None, win=5, keep=0.35):
    """Part label (base group, 0 = transparent) of every pixel: nearest character colour, then edge
    pixels (anti-aliasing between parts) join the part that dominates their neighbourhood."""
    from scipy import ndimage
    idx, lab = groups if groups is not None else base_groups(base_sprite)
    b_hls = _hls(anm.get_palette(base_sprite, 0)[idx, :3].astype(np.float64))
    a = rgba.reshape(-1, 4)
    opaque = a[:, 3] > 0
    cols, inv = np.unique(a[opaque, :3], axis=0, return_inverse=True)
    d = _role_distance(_hls(cols.astype(np.float64)), b_hls)
    col_lab = lab[np.argmin(d, axis=1)]
    out = np.zeros(len(a), int)
    out[opaque] = col_lab[inv.reshape(-1)]
    out = out.reshape(rgba.shape[:2])
    groups_present = [g for g in np.unique(out) if g]
    if len(groups_present) < 2:
        return out
    counts = np.stack([ndimage.uniform_filter((out == g).astype(np.float32), win) for g in groups_present])
    total = counts.sum(0) + 1e-6
    own = np.zeros(out.shape, np.float32)
    for k, g in enumerate(groups_present):
        own[out == g] = counts[k][out == g]
    best = np.array(groups_present)[np.argmax(counts, 0)]
    weak = (out > 0) & (own / total < keep)
    out[weak] = best[weak]
    return out


def _lab(rgb):
    """sRGB (n x 3, 0..255) -> CIELab."""
    c = np.asarray(rgb, np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def _lab_inv(lab):
    """CIELab (n x 3) -> sRGB 0..255 (clipped)"""
    lab = np.asarray(lab, np.float64)
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200
    f = np.stack([fx, fy, fz], 1)
    xyz = np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787) * np.array([0.9505, 1.0, 1.089])
    m = np.linalg.inv(np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]))
    c = np.clip(xyz @ m.T, 0, 1)
    c = np.where(c > 0.0031308, 1.055 * c ** (1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


REF_DIR = __import__("os").path.join(__import__("os").path.dirname(__file__), "data", "wiki_colors")
REF_GROUP = 14.0         # mean dE per variant below which two reference colours change alike (= one part)


def load_reference(path):
    """a reference recolour table (data/wiki_colors/*.json, made from the Disgaea wiki's rank / extra colour sprites:
    pixel-aligned recolours of one drawing) -> (names, rank-1 RGB (n, 3), variant RGB (n, V, 3), pixel counts)"""
    import json
    with open(path) as f:
        d = json.load(f)
    r1, rk, w = [], [], []
    for k, (n, vs) in d["colors"].items():
        if any(v is None or "undefined" in v for v in vs):
            continue
        r1.append([int(x) for x in k.split(",")])
        rk.append([[int(x) for x in v.split(",")] for v in vs])
        w.append(n)
    return d.get("names") or [], np.array(r1, float), np.array(rk, float), np.array(w, float)


def _ref_groups(r1, rk):
    """reference colours that change alike over the variants belong to one part (all of the robe's shades turn
    green at rank 2): average-linkage clusters of their per-variant Lab changes"""
    from scipy.cluster.hierarchy import linkage, fcluster
    L1 = _lab(r1)
    D = np.stack([_lab(rk[:, v]) - L1 for v in range(rk.shape[1])], 1)        # (n, V, 3)
    if len(r1) < 2:
        return np.ones(len(r1), int)
    flat = D.reshape(len(r1), -1)
    V = rk.shape[1]

    def metric(a, b):
        return float(np.linalg.norm((a - b).reshape(V, 3), axis=1).mean())
    from scipy.spatial.distance import pdist
    return fcluster(linkage(pdist(flat, metric), "average"), REF_GROUP, "distance")


def from_reference(sprite, path, info=None, log=None):
    """Colour variants 1.. of a sprite from a reference recolour table (the Disgaea wiki's rank 1-6 / Extra color
    1-3 / Dark sprites of the same class, data/wiki_colors).  Per part of the sprite's palette (info['entries'] of
    repartition, else every colour alone): the reference part that matches its colours best (Lab), then every
    shade takes that part's variant colour plus the shade's own offset from the matched rank-1 colour, so the
    unit keeps its shading and gets the reference's colours.  Palette 0 stays.  -> number of variants written"""
    names, r1, rk, w = load_reference(path)
    if not len(r1):
        return 0
    pal = anm.get_palette(sprite, 0)
    used = _used_indices(sprite)
    live = [i for i in range(1, 256) if pal[i, 3] > 0 and used[i] > 0]
    groups = _ref_groups(r1, rk)
    L1 = _lab(r1)
    parts = {}
    for i in live:
        e = (info or {}).get("entries", {}).get(str(i)) or (info or {}).get("entries", {}).get(i)
        parts.setdefault(e["part"] if e else -i, []).append(i)
    target = {}
    for part, idx in parts.items():
        lab = _lab(pal[idx, :3])
        wts = used[idx].astype(float)
        best = None
        for g in np.unique(groups):
            m = groups == g
            d = np.linalg.norm(lab[:, None] - L1[m][None], axis=2).min(1)
            cost = float((d * wts).sum() / max(1.0, wts.sum()))
            if best is None or cost < best[0]:
                best = (cost, g)
        m = np.nonzero(groups == best[1])[0]
        near = m[np.argmin(np.linalg.norm(lab[:, None] - L1[m][None], axis=2), axis=1)]
        for i, j, c in zip(idx, near, lab):
            target[i] = (j, c - L1[j])
    nv = min(len(sprite.palettes) - 1, rk.shape[1] - 1)
    for v in range(1, nv + 1):
        new = pal.copy()
        for i, (j, off) in target.items():
            new[i, :3] = _lab_inv((_lab(rk[j:j + 1, v]) + off)[None, :].reshape(1, 3))[0]
        anm.set_palette(sprite, v, new)
    if log:
        log(f"  colour variants 1-{nv} from {__import__('os').path.basename(path)} "
            f"({len(parts)} parts, {len(np.unique(groups))} reference parts)")
    return nv


def reference_for(uid):
    """the reference recolour table of a DRPG unit (data/wiki_colors/*.json 'units') or None"""
    import json
    import os
    if not os.path.isdir(REF_DIR):
        return None
    for f in sorted(os.listdir(REF_DIR)):
        if f.endswith(".json"):
            p = os.path.join(REF_DIR, f)
            with open(p) as fh:
                if int(uid) in (json.load(fh).get("units") or []):
                    return p
    return None


def _colour_parts(base_sprite, pal, threshold=20.0, used=None):
    """Parts of a palette (hair, hoodie, skin ...): colours of the same tint.  Clustered in Lab with
    lightness down-weighted, so a part's shading ramp stays together while differently tinted parts
    of similar brightness (pink hoodie / skin) are separated."""
    from scipy.cluster.hierarchy import linkage, fcluster
    live = np.nonzero(pal[:, 3] > 0)[0]
    live = live[live > 0]
    if used is not None:
        live = live[used[live] > 0]
    if len(live) < 2:
        return {int(i): 1 for i in live}
    L = _lab(pal[live, :3])
    F = np.stack([0.35 * L[:, 0], L[:, 1], L[:, 2]], 1)
    lab = fcluster(linkage(F, "average"), threshold, "distance")
    return {int(i): int(g) for i, g in zip(live, lab)}


def _smooth_labels(lab, win=3, keep=0.4, rgb=None, cores=None):
    """Edge pixels (anti-aliasing between parts) join the part that dominates their neighbourhood --
    only when their colour is closer to that part's core colour (thin details such as a gold anklet on
    skin keep their own part)."""
    from scipy import ndimage
    present = [g for g in np.unique(lab) if g]
    if len(present) < 2:
        return lab
    counts = np.stack([ndimage.uniform_filter((lab == g).astype(np.float32), win) for g in present])
    total = counts.sum(0) + 1e-6
    own = np.zeros(lab.shape, np.float32)
    for k, g in enumerate(present):
        own[lab == g] = counts[k][lab == g]
    best = np.array(present)[np.argmax(counts, 0)]
    out = lab.copy()
    weak = (lab > 0) & (own / total < keep) & (best != lab)
    if rgb is not None and cores:
        ys, xs = np.nonzero(weak)
        c = rgb[ys, xs, :3].astype(np.int32)
        own_core = np.array([cores.get(int(g), (0, 0, 0)) for g in lab[ys, xs]], np.int32)
        new_core = np.array([cores.get(int(g), (0, 0, 0)) for g in best[ys, xs]], np.int32)
        closer = ((c - new_core) ** 2).sum(1) < ((c - own_core) ** 2).sum(1)
        stray = (own / total)[ys, xs] < 0.25            # a lone speck always joins its surroundings
        keep_own = ~closer & ~stray
        weak[ys[keep_own], xs[keep_own]] = False
    out[weak] = best[weak]
    return out


def _part_adjacency(labels):
    """{(a, b): touching pixel pairs} of parts in label images (0 = transparent, ignored)."""
    adj = {}
    for lab in labels:
        for a, b in ((lab[:, :-1], lab[:, 1:]), (lab[:-1, :], lab[1:, :])):
            m = (a != b) & (a > 0) & (b > 0)
            u, c = np.unique(np.stack([a[m], b[m]], 1), axis=0, return_counts=True)
            for (x, y), n in zip(u.tolist(), c.tolist()):
                adj[(x, y)] = adj.get((x, y), 0) + n
                adj[(y, x)] = adj.get((y, x), 0) + n
    return adj


def _blend_parts(labels, cores, counts, log=None):
    """{blend part: (part a, part b)}.  A small part whose colour lies between the two parts it touches
    most is anti-aliasing (a hair strand drawn over skin, the dark edge of the hoodie); in every preset
    it becomes the same mix of those two parts' new colours."""
    adj = _part_adjacency(labels)
    w = np.array([0.35, 1.0, 1.0])            # tint matters, lightness less (AA is often darker)
    out = {}
    for p in sorted(counts, key=lambda g: -counts[g]):
        if cores.get(p) is None:
            continue
        nbs = sorted({b for (a, b) in adj if a == p and cores.get(b) is not None and counts[b] > counts[p]
                      and b not in out}, key=lambda b: -adj[(p, b)])
        if len(nbs) < 2:
            continue
        a, b = nbs[:2]
        cp = _lab(np.array([cores[p]]))[0] * w
        ca, cb = _lab(np.array([cores[a], cores[b]])) * w
        ab = cb - ca
        t = float(np.clip(np.dot(cp - ca, ab) / max(np.dot(ab, ab), 1e-6), 0, 1))
        off = float(np.linalg.norm(ca + t * ab - cp))
        if 0.1 < t < 0.9 and off < 0.5 * min(np.linalg.norm(cp - ca), np.linalg.norm(cp - cb)):
            out[p] = (a, b)
            if log:
                log(f"  part {p} {tuple(cores[p])} = blend of {tuple(cores[a])} / {tuple(cores[b])}")
    return out


def part_labels(sprite, base_sprite, log=None):
    """Part label image of every indexed texture of `sprite` (0 = transparent).
    -> (pal, lut, texs, ind, labels, pre_core, blends, core_derived)"""
    pal = anm.get_palette(sprite, 0)
    part_of = _colour_parts(base_sprite, pal, used=_used_indices(sprite))
    lut = np.zeros(256, int)
    for i, g in part_of.items():
        lut[i] = g
    texs = [i for i, t in enumerate(sprite.textures) if t.indexed]
    ind = {i: anm.texture_indices(sprite, i) for i in texs}
    rgba = {i: pal[ind[i]] for i in texs}
    raw_hist = {}
    for i in texs:
        for q, c in zip(*np.unique(ind[i][ind[i] > 0], return_counts=True)):
            raw_hist[int(q)] = raw_hist.get(int(q), 0) + int(c)
    pre_core = {}
    for g in set(part_of.values()):
        members = [q for q in part_of if part_of[q] == g and q in raw_hist]
        if members:
            pre_core[g] = tuple(int(v) for v in pal[max(members, key=raw_hist.get), :3])
    labels = {i: _smooth_labels(lut[ind[i]], rgb=rgba[i], cores=pre_core) for i in texs}
    present = sorted({int(g) for i in texs for g in np.unique(labels[i]) if g})
    counts = {g: sum(int((labels[i] == g).sum()) for i in texs) for g in present}
    # every part's core colour through the derived presets
    core_pal = np.zeros((256, 4), np.uint8)
    for g in present:
        if pre_core.get(g) is not None:
            core_pal[g, :3], core_pal[g, 3] = pre_core[g], 255
    core_derived = derive_palettes(base_sprite, core_pal, len(sprite.palettes))
    blends = _blend_parts([labels[i] for i in texs], pre_core, counts, log)
    return pal, lut, texs, ind, labels, pre_core, blends, core_derived


FEATURE = 1000          # label offset of the small-detail parts (eyes, mouth ...)
FEATURE_AREA = 60       # a patch smaller than this (pixels) is a detail, not a piece of a garment
DETAIL_MATCH = 12.0     # Lab distance: 'the original character has this colour'
LONE_DISTANCE = 8       # ... or a small patch further than this from the big pieces of its part


def _mark_features(labels, ind, texs, log=None, skip=()):
    """Colours used mostly in small enclosed patches (eyes, mouth, small face details) get their own
    'detail' part (label + FEATURE): a red eye must not recolour like a red bikini of the same tint.
    Patches of garment colours (a piece of hoodie between two hair strands) stay with their part."""
    from scipy import ndimage
    small = {}
    lones = {}
    small_n = np.zeros(256, np.int64)
    all_n = np.zeros(256, np.int64)
    for i in texs:
        lab = labels[i]
        m = np.zeros(lab.shape, bool)
        lone = np.zeros(lab.shape, bool)
        for g in np.unique(lab):
            if not g or g in skip:
                continue
            comp, n = ndimage.label(lab == g)
            if n:
                size = np.bincount(comp.reshape(-1))
                size[0] = 0
                sm = (size[comp] < FEATURE_AREA) & (comp > 0)
                m |= sm
                # a small patch far from the part's big pieces (a brown shadow in the face, not a piece
                # of the anklet of the same colour)
                near_big = ndimage.binary_dilation((comp > 0) & ~sm, iterations=LONE_DISTANCE)
                lone |= sm & ~near_big
        small[i] = m
        lones[i] = lone
        small_n += np.bincount(ind[i][m], minlength=256)[:256]
        all_n += np.bincount(ind[i][lab > 0], minlength=256)[:256]
    feat = (small_n > 0.6 * np.maximum(all_n, 1)) & (all_n > 0)
    feat[0] = False
    out = {}
    for i in texs:
        m = small[i] & (feat[ind[i]] | lones[i])
        out[i] = np.where(m, labels[i] + FEATURE, labels[i])
    if log:
        log(f"  detail colours: {int(feat.sum())}")
    return out


def _dedupe(sprite):
    """Pixels of identical colours share one index again (undoes an earlier repartition, so running
    it twice gives the same result)."""
    pal = anm.get_palette(sprite, 0)
    first = {}
    lut = np.arange(256, dtype=np.uint8)
    for q in range(1, 256):
        if pal[q, 3] == 0:
            continue
        lut[q] = first.setdefault(tuple(int(v) for v in pal[q]), q)
    if (lut == np.arange(256)).all():
        return
    for i, t in enumerate(sprite.textures):
        if t.indexed:
            t.data = lut[anm.texture_indices(sprite, i)].tobytes()


CONSISTENT = 0.8        # a colour that is this much one part is that part in every frame


def _consistent(labels, ind, texs, log=None):
    """Same colour, same part in every animation frame: a colour whose pixels are mostly (CONSISTENT) one part
    becomes that part everywhere; only colours really shared by parts keep the spatial decision."""
    n = max(int(labels[i].max()) for i in texs) + 1 if texs else 1
    votes = np.zeros((256, n), np.int64)
    for i in texs:
        m = labels[i] > 0
        np.add.at(votes, (ind[i][m], labels[i][m]), 1)
    tot = votes.sum(1)
    top = votes.argmax(1)
    firm = (tot > 0) & (votes.max(1) >= CONSISTENT * np.maximum(tot, 1))
    out = {}
    changed = 0
    for i in texs:
        lab = labels[i].copy()
        m = (lab > 0) & firm[ind[i]]
        new = top[ind[i]]
        changed += int((m & (lab != new)).sum())
        lab[m] = new[m]
        out[i] = lab
    if log:
        log(f"  consistent parts: {changed} pixels moved to their colour's main part")
    return out


def repartition(sprite, base_sprite, colors=255, log=None, fs=None):
    """Re-encode an indexed sprite so every part (hair, hoodie, skin ...) has its own palette colours
    (an index is never shared by two parts, so presets can't bleed into a neighbouring part) and
    derive the colour presets per part.  Rewrites textures + all palettes of `sprite`.
    -> part info (json-able; keep it to re-derive the presets later with derive_parts)."""
    _dedupe(sprite)
    pal, lut, texs, ind, labels, pre_core, blends, _ = part_labels(sprite, base_sprite, log)
    labels = _mark_features(labels, ind, texs, log, skip=set(blends))
    labels = _consistent(labels, ind, texs, log)
    present = sorted({int(g) for i in texs for g in np.unique(labels[i]) if g})
    # core colour of every part: its most used colour among pixels that are "really" of the part
    core_oi = {}
    for g in present:
        hist = np.zeros(256, np.int64)
        for i in texs:
            m = (labels[i] == g) & (lut[ind[i]] == g % FEATURE)
            hist += np.bincount(ind[i][m], minlength=256)[:256]
        if hist.any():
            core_oi[g] = int(np.argmax(hist))
    # keep every original colour; an index used by two parts becomes one entry per part (exclusive)
    pairs = {}
    for i in texs:
        key = labels[i].astype(np.int64) * 256 + ind[i]
        u, c = np.unique(key[labels[i] > 0], return_counts=True)
        for kk, cc in zip(u.tolist(), c.tolist()):
            pairs[kk] = pairs.get(kk, 0) + cc
    keep = {g * 256 + oi for g, oi in core_oi.items()}
    remap = _merge_pairs(pairs, pal, colors, keep=keep)
    if remap and log:
        log(f"  {len(remap)} rare shades merged into their nearest shade (palette limit)")
    order, slot, more = _block_layout(pairs, pal, blends, keep, log)
    remap.update(more)
    for q, t in list(remap.items()):
        while t in remap:
            t = remap[t]
        remap[q] = t
    new_index = dict(slot)
    for q, t in remap.items():
        new_index[q] = new_index[t]
    new_pal = np.zeros((256, 4), np.uint8)
    for q in order:
        new_pal[new_index[q]] = pal[q % 256]
    # a detail follows the original character's same colour only when she really has that colour
    b0 = anm.get_palette(base_sprite, 0)
    b_lab = _lab(b0[np.nonzero((_used_indices(base_sprite) > 0) & (b0[:, 3] > 0))[0], :3])
    core_idx = {g: new_index[g * 256 + oi] for g, oi in core_oi.items()}
    entries = {}
    for q in order:
        g, oi = divmod(q, 256)
        part = g % FEATURE
        e = {"part": int(part), "core": int(core_idx.get(part, new_index[q]))}
        if g >= FEATURE and float(np.linalg.norm(b_lab - _lab(pal[oi:oi + 1, :3]), axis=1).min()) < DETAIL_MATCH:
            e["detail"] = True
        if g in blends and all(x in core_idx for x in blends[g]):
            e["blend"] = [int(core_idx[x]) for x in blends[g]]
        entries[new_index[q]] = e
    lut2 = np.zeros(len(present) and (max(present) + 1) * 256, np.uint8)
    for q, n in new_index.items():
        lut2[q] = n
    for i in texs:
        key = labels[i].astype(np.int64) * 256 + ind[i]
        new = np.where(labels[i] > 0, lut2[np.clip(key, 0, len(lut2) - 1)], 0).astype(np.uint8)
        sprite.textures[i].data = new.tobytes()
    anm.set_palette(sprite, 0, new_pal)
    info = {"entries": entries}
    derive_parts(sprite, base_sprite, info, fs=fs, log=log)
    return info


PART_SWITCH = 36.0      # merge cost of giving a few pixels another part's identical colour (~ dE 6)
BLOCK = 16              # the Strategy Assembly's precise colour editor edits the palette in rows of 16 colours
DETAILS = -1            # editor row group of the small details (eyes, mouth ...)


def _block_layout(pairs, pal, blends, keep, log=None):
    """Palette layout for the precise colour editor (Strategy Assembly), which edits the palette by rows of 16
    colours and lists rows 1-15 (a row whose first colour is visible; row 0 is never offered): like the game's
    own sprites every part (hair, hoodie, skin ...) gets ONE row of its own, anti-aliasing blends go with the
    part they blend from, and the small details (eyes, mouth) take row 0.  A part with more than 16 shades keeps
    its 16 most important ones; with more than 15 parts the smallest share rows.
    -> (keys in index order, {key: palette index}, {merged key: kept key}); `pairs` is updated in place."""
    def group_of(label):
        if label >= FEATURE:
            return DETAILS
        if label in blends and blends[label]:
            return blends[label][0] % FEATURE
        return label
    members = {}
    for q in pairs:
        members.setdefault(group_of(q // 256), []).append(q)
    weight = {g: sum(pairs[q] for q in members[g]) for g in members}
    parts = sorted((g for g in members if g != DETAILS), key=lambda g: -weight[g])
    units = [[g] for g in parts]
    while len(units) > BLOCK - 1:                 # rows 1-15: the smallest parts share
        tail = units.pop()
        units[-1] = units[-1] + tail
    row0 = [DETAILS] if DETAILS in members else []
    if not row0 and units and len(units) == BLOCK - 1:
        row0 = units.pop()
    layout = [(0, row0)] + [(i + 1, u) for i, u in enumerate(units)]
    lab = _lab(pal[:, :3])
    remap, slot, order = {}, {}, []
    for row, groups in layout:
        keys = [q for g in groups for q in members[g]]
        if not keys:
            continue
        cap = BLOCK - (1 if row == 0 else 0)
        sub = {q: pairs[q] for q in keys}
        if len(sub) > cap:
            more = _merge_pairs(sub, pal, cap, keep=keep & set(sub))
            remap.update(more)
        kept = sorted(sub, key=lambda q: (-sub[q], q))[:cap]
        for q in sub:
            if q not in kept:                     # still too many (only core shades left): nearest kept
                t = min(kept, key=lambda k: float(((lab[k % 256] - lab[q % 256]) ** 2).sum()))
                remap[q] = t
                sub[t] += sub[q]
        for q in keys:
            pairs.pop(q, None)
        for q in kept:
            pairs[q] = sub[q]
        # the row's first entry must be visible (the editor lists a row by it): the part's main shade first
        kept.sort(key=lambda q: (q not in keep, -sub[q]))
        for n, q in enumerate(kept):
            slot[q] = BLOCK * row + n + (1 if row == 0 else 0)
            order.append(q)
    if log:
        log(f"  palette rows: {len(units)} part row(s) (1-{len(units)}) + details in row 0")
    return order, slot, remap


def _merge_pairs(pairs, pal, colors, keep=()):
    """More (part, colour) entries than the palette holds: merge away the entries whose loss is least
    visible -- few pixels x (colour difference^2, or PART_SWITCH when another part has the same colour,
    so the default look stays exact).  -> {merged key: kept key}; `pairs` is updated in place."""
    remap = {}
    if len(pairs) <= colors:
        return remap
    lab = _lab(pal[:, :3])
    d2 = ((lab[:, None] - lab[None]) ** 2).sum(-1)
    keys = np.array(sorted(pairs), np.int64)
    alive = np.ones(len(keys), bool)
    part, col = keys // 256, keys % 256
    count = np.array([pairs[int(k)] for k in keys], np.float64)
    fixed = np.array([int(k) in keep for k in keys])

    def best_of(n):
        c = d2[col[n], col] + PART_SWITCH * (part != part[n])
        c[~alive] = np.inf
        c[n] = np.inf
        m = int(np.argmin(c))
        return m, float(c[m])

    tgt = np.zeros(len(keys), int)
    cost = np.full(len(keys), np.inf)
    for n in range(len(keys)):
        if not fixed[n]:
            tgt[n], cost[n] = best_of(n)
    left = len(keys)
    while left > colors:
        score = np.where(alive & ~fixed, count * cost, np.inf)
        n = int(np.argmin(score))
        if not np.isfinite(score[n]):
            break
        m = tgt[n]
        alive[n] = False
        left -= 1
        count[m] += count[n]
        q, t = int(keys[n]), int(keys[m])
        pairs[t] += pairs.pop(q)
        remap[q] = t
        for x, y in list(remap.items()):
            if y == q:
                remap[x] = t
        for r in np.nonzero(alive & ~fixed & (tgt == n))[0]:
            tgt[r], cost[r] = best_of(r)
    return remap


def derive_parts(sprite, base_sprite, info, fs=None, log=None):
    """Colour presets 1.. of a repartitioned sprite from its part info (see repartition), following the
    CURRENT first palette (so recolouring a part in the editor and re-deriving keeps the new colours).
    fs (the game files, for the shared motions): every colour follows the part of the character it lies over in the
    same poses (d5lib.recolor) -- the method used whenever the game files are at hand; without them, the old
    hue-matching one below."""
    if fs is not None:
        from . import recolor, sprites as _sprites
        if not info.get("painted") and not info.get("skin_checked"):
            # her skin apart from the shades it shares (once: the sprite and its part info are updated)
            try:
                recolor.refine_skin(sprite, base_sprite, info, fs, log=log)
                info["skin_checked"] = True
            except Exception as e:
                if log:
                    log(f"  (skin check skipped: {e})")
        try:
            pals, _ = recolor.derive(_sprites.preview_file(fs, sprite), _sprites.preview_file(fs, base_sprite),
                                     info=info, log=log)
            apply_to_sprite(sprite, pals)
            return sprite
        except Exception as e:                           # never lose the variants over it
            if log:
                log(f"  (part-following colour variants failed: {e}; hue matching instead)")
    pal = anm.get_palette(sprite, 0)
    entries = {int(k): v for k, v in info["entries"].items()}
    anchors = pal[:, :3].copy()
    plain = np.zeros(256, bool)
    for n, e in entries.items():
        if e.get("detail"):
            plain[n] = True
        elif 0 <= e.get("core", n) < 256:
            anchors[n] = pal[e["core"], :3]
    derived = derive_palettes(base_sprite, pal, len(sprite.palettes), anchors=anchors, plain=plain)
    # blends (anti-aliasing between two parts): the same mix of the two parts' new colours
    for n, e in entries.items():
        if not e.get("blend"):
            continue
        ia, ib = e["blend"]
        A, B = pal[ia, :3].astype(float), pal[ib, :3].astype(float)
        c = pal[n, :3].astype(float)
        t = float(np.clip(np.dot(c - A, B - A) / max(np.dot(B - A, B - A), 1e-6), 0, 1))
        # the colour relative to the plain mix (a bit darker / greyer) stays so in the preset
        _, l0, s0 = colorsys.rgb_to_hls(*((A + t * (B - A)) / 255.0))
        _, lc, sc = colorsys.rgb_to_hls(*(c / 255.0))
        lr = float(np.clip(lc / max(l0, 1e-3), 0.3, 3.0))
        sr = float(np.clip(sc / max(s0, 1e-3), 0.0, 3.0))
        for d in derived:
            mix = d[ia, :3].astype(float) * (1 - t) + d[ib, :3].astype(float) * t
            h, l, sat = colorsys.rgb_to_hls(*(mix / 255.0))
            rgb = colorsys.hls_to_rgb(h, min(1.0, l * lr), min(1.0, sat * sr))
            d[n, :3] = np.clip(np.round(np.array(rgb) * 255), 0, 255)
    apply_to_sprite(sprite, derived)
    return sprite


def repartition_rows(sprite, base_sprite, rows, log=None, fs=None):
    """Re-encode an indexed sprite from explicit parts: rows = {texture: editor row per pixel (-1 transparent)},
    e.g. painted by hand (d5lib.partmap).  Part N becomes palette row N (editor "Part N"), row 0 the details; a row
    keeps at most 16 shades (row 0: 15), ordered dark to light.  The colour presets are derived per part.
    -> part info (json-able, like repartition)"""
    pal = anm.get_palette(sprite, 0)
    texs = [i for i, t in enumerate(sprite.textures) if t.indexed]
    ind = {i: anm.texture_indices(sprite, i).astype(np.int64) for i in texs}
    pairs = {}
    for i in texs:
        m = rows[i] >= 0
        key = rows[i][m].astype(np.int64) * 256 + ind[i][m]
        for k, c in zip(*np.unique(key, return_counts=True)):
            pairs[int(k)] = pairs.get(int(k), 0) + int(c)
    lab = _lab(pal[:, :3])
    remap, slot = {}, {}
    entries = {}
    merged = 0
    for row in sorted({k // 256 for k in pairs}):
        sub = {k: c for k, c in pairs.items() if k // 256 == row}
        cap = BLOCK - (1 if row == 0 else 0)
        if len(sub) > cap:
            more = _merge_pairs(sub, pal, cap)
            remap.update(more)
            merged += len(more)
        kept = sorted(sub, key=lambda k: -sub[k])[:cap]
        for k in list(sub):
            if k not in kept:
                t = min(kept, key=lambda q: float(((lab[q % 256] - lab[k % 256]) ** 2).sum()))
                remap[k] = t
                merged += 1
        # dark -> light inside the row (the editor shows the row's shades as a strip)
        kept.sort(key=lambda k: float(lab[k % 256][0]))
        core = max(kept, key=lambda k: sub[k])
        for n, k in enumerate(kept):
            slot[k] = BLOCK * row + n + (1 if row == 0 else 0)
        for k in kept:
            e = {"part": int(row), "core": int(slot[core])}
            if row == 0:
                e["detail"] = True
            entries[slot[k]] = e
    for k, t in list(remap.items()):
        while t in remap:
            t = remap[t]
        slot[k] = slot[t]
    new_pal = np.zeros((256, 4), np.uint8)
    for k, n in slot.items():
        if k not in remap:
            new_pal[n] = pal[k % 256]
    lut = np.zeros(16 * 256, np.uint8)
    for k, n in slot.items():
        lut[k] = n
    for i in texs:
        key = np.clip(rows[i], 0, 15).astype(np.int64) * 256 + ind[i]
        sprite.textures[i].data = np.where(rows[i] >= 0, lut[key], 0).astype(np.uint8).tobytes()
    anm.set_palette(sprite, 0, new_pal)
    if log:
        used = sorted({k // 256 for k in pairs})
        log(f"  parts: rows {used}, {merged} rare shades merged into the nearest shade of their part")
    info = {"entries": entries, "painted": True}
    derive_parts(sprite, base_sprite, info, fs=fs, log=log)
    return info
