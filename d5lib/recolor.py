"""Colour variants that follow the character's own (the artist's) recolours, part by part.

An outfit or new character drawn from Disgaea RPG art plays its base character's animations, so in every pose its
drawing lies where the base character's drawing lies.  Drawing both in the same poses (index_pairs) tells, for every
colour of the new sprite, which of the base character's palette colours lie under it -- and so which of the
character's parts (a palette row of the game's sprites: hair, top, skin, gold trim ...) it is.

    * every colour takes ONE part of the base character: the votes of its pixels, pooled over colours of the same
      tint (all shades of a cape decide together, so a cape never splits into two parts), checked against the
      colours of that part (a crown drawn over the hair is not hair)
    * in a variant, every colour follows its part's change along the shading ramp (ramp_transfer): the base shades
      nearest in lightness carry their new colour; the colour keeps its own offset from them (lightness added,
      saturation scaled, hue turned), so the outfit keeps its own shading and gets the variant's colours
    * the default look (palette 0) and the textures are not changed

Measured on the game's own classes against their pixel-identical Disgaea RPG twins (the artist's variants are the
answer): the old hue-matching method was 12-16 dE off the real variants, this one 3-4.6 -- as close as the default
colours themselves.
"""
import math

import numpy as np

from . import anm, colorvariants as cv

POSE_LIMIT = 90          # poses drawn for the correspondence
TINT_SIGMA = 12.0        # Lab distance (lightness at half weight) over which colours pool their votes
COMPAT_TAU = 30.0        # a part whose colours are this far from a colour is a poor match for it
NO_MATCH = 0.2           # a material fitting no part of the character better than this keeps its colours (like the
                         # game's own metal, skin and outlines)
EXACT_DE = 14.0          # a colour this close to one of a part's colours IS that colour of the character (her skin,
                         # her hair: the same character drawn again)
EXACT_SHARE = 0.5        # ... for this share of a material's pixels: the material is that part
MERGE_TINT = 22.0        # touching materials of the same tint (Lab, lightness at half weight) are one material
MERGE_TOUCH = 0.08       # ... touching along this share of the smaller one's pixels
COVER = 0.6              # a material lying this much over the character, and mostly over one part of it (SHARE), is
SHARE = 0.6              # that part whatever its colour (red hair where his blue hair is); less (a crown above the
                         # head): the colours decide
HUE_KEEP = (25.0, 60.0)  # a colour keeps its hue offset from the part it follows up to 25 degrees, none from 60 on
L_SLACK = 15.0           # ... lightness (Lab L) within the part's own range +- this
GREY_CHROMA = 10.0       # a material greyer than this (mean Lab chroma) is not matched by its exact colours
SMALL = 0.03             # a material under this share of the sprite's pixels without a firm decision joins its
                         # neighbour (assign_parts)
MIN_CHROMA = 8.0         # below this chroma a hue means nothing


# ------------------------------------------------------------------------------------------- correspondence
def _index_layer(a, it, cache):
    """the item's cell as palette indices (0 = transparent)"""
    key = (it.tex_global, it.block)
    if key not in cache:
        t = a.textures[it.tex_global] if it.tex_global < len(a.textures) else None
        cache[key] = anm.texture_indices(a, it.tex_global) if t is not None and t.indexed else None
    ix = cache[key]
    if ix is None:
        return None
    c = it.cell
    return ix[c.y:c.y + c.h, c.x:c.x + c.w]


def index_render(a, items, bounds):
    """palette index (0 = nothing) of the topmost drawing at every pixel, nearest sampling (no mixing)"""
    x0, y0, x1, y1 = bounds
    W, H = int(x1 - x0), int(y1 - y0)
    out = np.zeros((H, W), np.uint8)
    cache = {}
    ys, xs = np.mgrid[0:H, 0:W]
    for it in items:
        c = it.cell
        if not c.w or not c.h or (it.color[3] if len(it.color) > 3 else 255) == 0:
            continue
        src = _index_layer(a, it, cache)
        if src is None:
            continue
        q = it.quad - [x0, y0]
        bx0, by0 = max(0, int(math.floor(q[:, 0].min()))), max(0, int(math.floor(q[:, 1].min())))
        bx1, by1 = min(W, int(math.ceil(q[:, 0].max())) + 1), min(H, int(math.ceil(q[:, 1].max())) + 1)
        if bx1 <= bx0 or by1 <= by0:
            continue
        try:
            Hm = anm._homography(q, [(0, 0), (c.w, 0), (c.w, c.h), (0, c.h)])
        except np.linalg.LinAlgError:
            continue
        px = xs[by0:by1, bx0:bx1] + 0.5
        py = ys[by0:by1, bx0:bx1] + 0.5
        den = Hm[2, 0] * px + Hm[2, 1] * py + Hm[2, 2]
        sx = np.floor((Hm[0, 0] * px + Hm[0, 1] * py + Hm[0, 2]) / den).astype(np.int64)
        sy = np.floor((Hm[1, 0] * px + Hm[1, 1] * py + Hm[1, 2]) / den).astype(np.int64)
        ok = (sx >= 0) & (sx < src.shape[1]) & (sy >= 0) & (sy < src.shape[0])
        v = np.zeros(sx.shape, np.uint8)
        v[ok] = src[sy[ok], sx[ok]]
        dst = out[by0:by1, bx0:bx1]
        m = v > 0
        dst[m] = v[m]
    return out


def poses(a, limit=POSE_LIMIT):
    """(animation id, time) of the poses to compare: every animation's first and middle key, up to `limit`"""
    out = []
    for info in anm.list_animations(a):
        ts = anm.frame_times(a, info["index"])
        for t in sorted({ts[0], ts[len(ts) // 2]}):
            out.append((info["id"], t))
    if len(out) > limit:
        step = len(out) / limit
        out = [out[int(k * step)] for k in range(limit)]
    return out


def index_pairs(new, base, limit=POSE_LIMIT):
    """256 x 256 counts: pixels of new-sprite index i drawn over base-sprite index j (both preview files: shared motion
    set bound), over the poses both sprites have.  Column 0: pixels of i over nothing of the base."""
    M = np.zeros((256, 256), np.int64)
    for aid, t in poses(new, limit):
        if not anm.has_animation(base, aid):
            continue
        try:
            ia = anm.evaluate(new, ("id", aid), t)
            ib = anm.evaluate(base, ("id", aid), t)
        except Exception:
            continue
        if not ia or not ib:
            continue
        ba, bb = anm.item_bounds(ia), anm.item_bounds(ib)
        bounds = (min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3]))
        A = index_render(new, ia, bounds)
        B = index_render(base, ib, bounds)
        m = A > 0
        np.add.at(M, (A[m], B[m]), 1)
    return M


# ------------------------------------------------------------------------------------------- the base's parts
def base_rows(base):
    """{row: [palette indices the base sprite draws with]} -- the parts of the game's own sprites"""
    used = cv._used_indices(base)
    p0 = anm.get_palette(base, 0)
    out = {}
    for i in np.nonzero((used > 0) & (p0[:, 3] > 0))[0]:
        out.setdefault(int(i) // 16, []).append(int(i))
    return out


def _lch(x):
    return x[..., 0], np.hypot(x[..., 1], x[..., 2]), np.arctan2(x[..., 2], x[..., 1])


def ramp_transfer(c_lab, B0, Bk, w=None):
    """colour c (Lab) of a part following base shades B0 (Lab, n x 3, default look) -> its colour where those shades
    become Bk: the shades nearest in lightness (and w: how much of the colour lies over each) carry their change, the
    colour keeps its own offset from them (lightness added, chroma scaled, hue turned)"""
    wt = 1.0 / (np.abs(B0[:, 0] - c_lab[0]) + 4.0) ** 2
    if w is not None:
        wt = wt * w
    wt = wt / wt.sum()
    L0, C0, H0 = _lch(B0)
    Lk, Ck, Hk = _lch(Bk)
    Lc, Cc, Hc = (float(v) for v in _lch(c_lab[None]))
    tL = float((wt * (Lk + (Lc - L0))).sum())
    coloured = C0 > MIN_CHROMA
    ratio = np.clip(Cc / np.maximum(C0, 1e-3), 0, 3)
    tC = float((wt * np.where(coloured, Ck * ratio, Ck + 0.5 * (Cc - C0))).sum())
    dh = np.angle(np.exp(1j * (Hc - H0)))
    # a hue offset belongs to a colour of the part's own family (a slightly redder pink); a colour of another hue
    # following the part (red hair where his blue hair is) takes the part's new hue
    a0, a1 = np.radians(HUE_KEEP[0]), np.radians(HUE_KEEP[1])
    keep = np.clip((a1 - np.abs(dh)) / (a1 - a0), 0.0, 1.0)
    th = Hk + np.where(np.minimum(C0, Cc) > MIN_CHROMA, dh * keep, 0.0)
    v = (wt * np.maximum(Ck, 1e-3) * np.exp(1j * th)).sum()
    tH = float(np.angle(v)) if abs(v) > 1e-9 else Hc
    # never more vivid than the colour itself or the part's new colours (a bright orange fur following a cream trim
    # that turns maroon became a glaring red)
    tC = min(max(0.0, tC), max(Cc, float(Ck.max())) * 1.1)
    return np.array([min(100.0, max(0.0, tL)), tC * math.cos(tH), tC * math.sin(tH)])


# ------------------------------------------------------------------------------------------- the variants
def groups_of(pal0, used, info=None):
    """{index: material} of the new sprite's colours: the parts of its part info (colorvariants.repartition /
    repartition_rows: one material per part, small details such as eyes one by one), else its palette rows (the
    kit lays every part out in a row of its own; row 0 holds the details)"""
    out = {}
    entries = {int(k): v for k, v in ((info or {}).get("entries") or {}).items()}
    for i in range(1, 256):
        if used[i] <= 0 or pal0[i, 3] == 0:
            continue
        e = entries.get(i)
        if e is not None:
            out[i] = ("d", i) if e.get("detail") else ("p", int(e["part"]))
        else:
            out[i] = ("d", i) if i < 16 else ("p", i // 16)
    return out


def adjacency(sprite):
    """256 x 256 counts of horizontally / vertically touching pixels of two different colours in the textures"""
    A = np.zeros((256, 256), np.int64)
    for t in range(len(sprite.textures)):
        if not sprite.textures[t].indexed:
            continue
        ix = anm.texture_indices(sprite, t)
        for a, b in ((ix[:, :-1], ix[:, 1:]), (ix[:-1, :], ix[1:, :])):
            m = (a != b) & (a > 0) & (b > 0)
            np.add.at(A, (a[m], b[m]), 1)
    return A + A.T


def merge_materials(groups, pal0, used, A, votes=None):
    """one material for touching materials of the same tint (the light and dark shades of a fur collar that the part
    finder put apart): they then follow one part of the character together -- no speckles.  votes: {material: vector
    of pixels over each part of the character}; two materials lying over different parts (red skin under red hair)
    stay apart."""
    mats = {}
    for i, g in groups.items():
        mats.setdefault(g, []).append(i)
    names = [g for g in mats if g[0] == "p"]
    if len(names) < 2:
        return groups
    W = np.array([0.5, 1.0, 1.0])
    tint, size = {}, {}
    for g in names:
        idx = np.array(mats[g])
        wts = used[idx].astype(float)
        tint[g] = (cv._lab(pal0[idx, :3]) * wts[:, None]).sum(0) / max(wts.sum(), 1e-9) * W
        size[g] = wts.sum()
    parent = {g: g for g in names}

    def find(g):
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g
    pairs = []
    for x in range(len(names)):
        for y in range(x + 1, len(names)):
            a, b = names[x], names[y]
            touch = A[np.ix_(mats[a], mats[b])].sum()
            if touch < MERGE_TOUCH * min(size[a], size[b]):
                continue
            d = float(np.linalg.norm(tint[a] - tint[b]))
            if d >= MERGE_TINT:
                continue
            if votes is not None:
                va, vb = votes.get(a), votes.get(b)
                if va is not None and vb is not None and va.sum() >= 200 and vb.sum() >= 200:
                    cos = float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))
                    if cos < 0.6:
                        continue
            pairs.append((d, a, b))
    for _, a, b in sorted(pairs, key=lambda t: t[0]):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    return {i: (find(g) if g in parent else g) for i, g in groups.items()}


def _skin_tone(rgb):
    """True per colour for skin tones: warm hue, light, softly saturated"""
    import colorsys
    hsv = np.array([colorsys.rgb_to_hsv(*(np.asarray(c[:3], float) / 255.0)) for c in rgb]).reshape(-1, 3)
    h, s_, v = hsv[:, 0] * 360, hsv[:, 1], hsv[:, 2]
    return (h >= 5) & (h <= 45) & (s_ >= 0.08) & (s_ <= 0.6) & (v >= 0.55)


def _skin_rows(rows, b0):
    """rows of the character's skin -- only skin follows them (the game's zombie / tanned variants change the skin;
    a fur collar must not turn grey with it)"""
    return {r for r, idx in rows.items() if _skin_tone(b0[idx]).mean() >= 0.6}


def assign_parts(pal0, used, M, rows, b0, groups, A=None):
    """the base row (part of the character) of every material -> {index: row}.  A: adjacency of the new sprite's
    colours (small undecided materials join the material they touch most)"""
    row_ids = sorted(rows)
    if not row_ids or not groups:
        return {}
    blab = {r: cv._lab(b0[rows[r], :3]) for r in row_ids}
    W = np.array([0.5, 1.0, 1.0])
    mats = {}
    for i, g in groups.items():
        mats.setdefault(g, []).append(i)
    names = sorted(mats, key=str)
    skin = _skin_rows(rows, b0)
    exact = np.zeros((len(names), len(row_ids)))
    cover = np.zeros(len(names))
    skin_toned = np.zeros(len(names), bool)
    V = np.zeros((len(names), len(row_ids)))
    comp = np.zeros_like(V)
    tint = np.zeros((len(names), 3))
    for n, g in enumerate(names):
        idx = np.array(mats[g])
        wts = used[idx].astype(float)
        for k, r in enumerate(row_ids):
            V[n, k] = M[idx][:, rows[r]].sum()
        cover[n] = V[n].sum() / max(float(M[idx].sum()), 1.0)
        lab = cv._lab(pal0[idx, :3])
        tint[n] = (lab * wts[:, None]).sum(0) / max(wts.sum(), 1e-9)
        skin_toned[n] = float((_skin_tone(pal0[idx]) * wts).sum() / max(wts.sum(), 1e-9)) >= 0.6
        for k, r in enumerate(row_ids):
            d = np.linalg.norm((lab[:, None] - blab[r][None]) * W, axis=2).min(1)
            comp[n, k] = float((np.exp(-(d / COMPAT_TAU) ** 2) * wts).sum() / max(wts.sum(), 1e-9))
            de = np.linalg.norm(lab[:, None] - blab[r][None], axis=2).min(1)
            exact[n, k] = float(((de < EXACT_DE) * wts).sum() / max(wts.sum(), 1e-9))
        if float(np.hypot(tint[n][1], tint[n][2])) < GREY_CHROMA and not skin_toned[n]:
            exact[n] = 0.0          # greys are in every part: matching one says nothing (a coat's greys are not
                                    # the grey highlights of her black clothes)
    # a material that barely lies over the character (a crown above the head) borrows the votes of materials of
    # the same tint
    F = tint * W
    K = np.exp(-((F[:, None] - F[None]) ** 2).sum(-1) / (2 * TINT_SIGMA ** 2))
    own = V.sum(1, keepdims=True)
    P = V + (K @ V) * (own < 200) * 0.5
    share = P / np.maximum(P.sum(1, keepdims=True), 1e-9)
    # the votes say where the material lies, the colours whether it is that part: a part it lies over but looks
    # nothing like (a gold crown over the hair) does not count
    score = share * comp + 0.05 * comp
    # the skin follows the skin only: a material is skin when its colours are her skin colours, or skin tones
    for k, r in enumerate(row_ids):
        if r in skin:
            score[(exact[:, k] < EXACT_SHARE) & ~skin_toned, k] = -1.0
    out = {}
    decided = {}
    for n, g in enumerate(names):
        # skin tones over her skin: her skin (drawn a few shades off by the DRPG artist, or compressed)
        sk = [k for k in range(len(row_ids)) if row_ids[k] in skin and share[n, k] >= 0.2]
        if skin_toned[n] and sk:
            k = max(sk, key=lambda k: share[n, k])
            decided[g] = (k, True)
            for i in mats[g]:
                out[i] = row_ids[k]
            continue
        # the same colours as one of the character's parts, where that part is: it is that part (her hair, eyes)
        cand = [k for k in range(len(row_ids)) if exact[n, k] >= EXACT_SHARE and share[n, k] >= 0.1]
        top = int(np.argmax(V[n]))
        if cand:
            k = max(cand, key=lambda k: exact[n, k] * (0.5 + share[n, k]))
        elif (cover[n] >= COVER and V[n, top] >= SHARE * max(V[n].sum(), 1.0) and row_ids[top] not in skin
              and V[n].sum() >= 200
              and blab[row_ids[top]][:, 0].min() - L_SLACK <= tint[n][0] <= blab[row_ids[top]][:, 0].max() + L_SLACK):
            # where that part of the character is, whatever its hue (red hair where his blue hair is) -- as long as
            # it is about as light (a white coat over black clothes is not those clothes)
            k = top
        else:
            k = int(np.argmax(score[n]))
            if score[n, k] < 0 or comp[n, k] < NO_MATCH:
                decided[g] = (None, False)
                continue                                 # unlike every part of the character: keeps its colours
        firm = bool(cand) or (cover[n] >= COVER and share[n, k] >= SHARE)
        decided[g] = (k, firm)
        for i in mats[g]:
            out[i] = row_ids[k]
    # a small material without a firm decision (edge shades, stray bits inside a coat) takes the part of the
    # material it touches most, when its colours fit that part: one garment, one recolour -- no speckles
    if A is not None:
        size = {g: float(used[np.array(mats[g])].sum()) for g in names}
        total = sum(size.values()) or 1.0
        for _ in range(2):
            for n, g in enumerate(names):
                k, firm = decided.get(g, (None, False))
                if firm or size[g] > SMALL * total:
                    continue
                touch = {}
                for m, h in enumerate(names):
                    if h == g or decided.get(h, (None, False))[0] is None:
                        continue
                    t = float(A[np.ix_(mats[g], mats[h])].sum())
                    if t > 0:
                        touch[h] = t
                if not touch:
                    continue
                h = max(touch, key=touch.get)
                kh = decided[h][0]
                if kh == k or touch[h] < 0.3 * size[g]:
                    continue
                if comp[n, kh] >= NO_MATCH and not (row_ids[kh] in skin and not skin_toned[n]):
                    decided[g] = (kh, False)
                    for i in mats[g]:
                        out[i] = row_ids[kh]
    return out


def derive(new, base, M=None, info=None, log=None):
    """colour variants 1.. of `new` (preview file: shared motion set bound) following `base` (the character's own
    sprite, preview file) -> ([palette 1, ...], {index: base row}).  info: the sprite's part info (repartition), for
    its materials; M: index_pairs(new, base) when already made."""
    if M is None:
        M = index_pairs(new, base)
    pal0 = anm.get_palette(new, 0)
    used = cv._used_indices(new)
    rows = base_rows(base)
    nv = len(new.palettes)
    nb = len(base.palettes)
    b = [anm.get_palette(base, min(v, nb - 1)) for v in range(max(nv, 1))]
    groups = groups_of(pal0, used, info)
    # skin tones decide on their own (the old part finder put a face's lightest shades with a white coat): over her
    # skin they are her skin, over the coat the coat
    tone = _skin_tone(pal0)
    groups = {i: (("s",) + g if tone[i] and g[0] == "p" else g) for i, g in groups.items()}
    row_ids = sorted(rows)
    votes = {}
    for i, g in groups.items():
        v = np.array([M[i, rows[r]].sum() for r in row_ids], float)
        votes[g] = votes.get(g, 0) + v
    A = adjacency(new)
    groups = merge_materials(groups, pal0, used, A, votes)
    part = assign_parts(pal0, used, M, rows, b[0], groups, A)
    out = [pal0.copy() for _ in range(1, nv)]
    lab0 = cv._lab(pal0[:, :3])
    for i, r in part.items():
        members = rows[r]
        B0 = cv._lab(b[0][members, :3])
        w = M[i, members].astype(float)
        w = w + 0.05 * max(w.sum(), 1.0) / len(members)        # every shade of the part counts a little
        for v in range(1, nv):
            Bk = cv._lab(b[v][members, :3])
            if np.abs(Bk - B0).max() < 0.5:
                continue                                         # the part keeps its colour in this variant
            out[v - 1][i, :3] = cv._lab_inv(ramp_transfer(lab0[i], B0, Bk, w)[None])[0]
    # (the part info's "blend" entries are not used: every colour follows the part it lies over -- the old part
    # finder took a red demon's skin for a blend of his clothes and hair)
    if log:
        by_row = {}
        for i, r in part.items():
            by_row[r] = by_row.get(r, 0) + int(used[i])
        log(f"  colour variants follow the character's parts: {len(part)} colours, "
            f"{len(set(groups.values()))} materials over {len(by_row)} of its parts")
    return out, part
