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
from scipy import ndimage

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
        if e is not None and e.get("skin"):
            out[i] = ("k",)                            # her skin (refine_skin): decided apart, follows his skin
        elif e is not None:
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
    skin_row = (info or {}).get("skin_row")
    if skin_row is not None and int(skin_row) in rows:
        for i, g in groups.items():
            if g == ("k",):
                part[i] = int(skin_row)
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
    out = repair(new, out, part, skin=_skin_rows(rows, b[0]))
    if log:
        by_row = {}
        for i, r in part.items():
            by_row[r] = by_row.get(r, 0) + int(used[i])
        log(f"  colour variants follow the character's parts: {len(part)} colours, "
            f"{len(set(groups.values()))} materials over {len(by_row)} of its parts")
    return out, part


# ------------------------------------------------------------------------------------------- her skin, texel by texel
# A shade the DRPG artist used both on her skin and elsewhere (Pram's face highlight is the white of her hair) can't
# follow two parts.  Every texel is decided skin or not -- her own skin colours (learned from where her drawing lies
# over the character's skin), the character's skin under it, and patches enclosed by skin -- and a shade used both
# ways gets a twin entry of the same colour for its skin texels.  The default look doesn't change.
NOTHING = 16             # vote column: over nothing of the character
SKIN_CONFIRM = 0.15      # a skin-toned colour with this share of its pixels over his skin (and SKIN_GLOB x the share of
SKIN_GLOB = 1.5          # all her pixels there) ...
SKIN_REF_DE = 15.0       # ... close to his main skin shades, is her skin
SKIN_DE = 7.0            # colours this close to her skin colours are skin wherever they lie (bare legs where he wears
                         # a coat)
VOTE_BLUR = 3.0          # texels: the votes are blurred over the drawing (compression blocks don't decide alone)
VOTE_SHARE = 0.55        # a texel lying this much over his skin ...
VOTE_FIT = 0.6           # ... in a colour that fits his skin this well is skin
TINY = 40                # texels: smaller patches added by the votes don't count
ISLAND_MAX = 1500        # texels: a patch this small ...
ISLAND_ENCLOSED = 0.7    # ... this much enclosed by skin ...
ISLAND_FIT = 0.45        # ... in colours this close to skin is skin (a highlight on her cheek)
MASK_WIN = 7             # texels: the mask is smoothed by the majority of this window
MASK_FIT = 0.3           # (never a colour this unlike skin)
MIN_SPLIT = 20           # texels: a shade used this much both ways gets its twin


def texel_render(a, items, bounds):
    """(texture index, flat texel index) of the topmost opaque texel at every pixel (-1: nothing), nearest sampling"""
    x0, y0, x1, y1 = bounds
    W, H = int(x1 - x0), int(y1 - y0)
    T = np.full((H, W), -1, np.int16)
    F = np.zeros((H, W), np.int64)
    cache = {}
    ys, xs = np.mgrid[0:H, 0:W]
    for it in items:
        c = it.cell
        if not c.w or not c.h or (it.color[3] if len(it.color) > 3 else 255) == 0:
            continue
        t = it.tex_global
        if t >= len(a.textures) or not a.textures[t].indexed:
            continue
        if t not in cache:
            cache[t] = anm.texture_indices(a, t)
        ix = cache[t]
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
        gx, gy = sx + c.x, sy + c.y
        ok = (sx >= 0) & (sx < c.w) & (sy >= 0) & (sy < c.h) & (gx < ix.shape[1]) & (gy < ix.shape[0])
        v = np.zeros(sx.shape, np.uint8)
        v[ok] = ix[gy[ok], gx[ok]]
        m = v > 0
        T[by0:by1, bx0:bx1][m] = t
        F[by0:by1, bx0:bx1][m] = gy[m] * ix.shape[1] + gx[m]
    return T, F


def texel_votes(new, base):
    """{texture: (texel indices (H, W), votes (H, W, 17))}: in every pose both sprites have (new, base: preview
    files), the part (palette row) of the character under each texel of the new sprite; 16 = nothing"""
    out = {}
    for t, tex in enumerate(new.textures):
        if tex.indexed:
            ix = anm.texture_indices(new, t)
            out[t] = (ix, np.zeros(ix.shape + (NOTHING + 1,), np.int32))
    for info in anm.list_animations(new):
        if not anm.has_animation(base, info["id"]):
            continue
        for tm in anm.frame_times(new, info["index"]):
            try:
                ia = anm.evaluate(new, ("id", info["id"]), tm)
                ib = anm.evaluate(base, ("id", info["id"]), tm)
            except Exception:
                continue
            if not ia or not ib:
                continue
            ba, bb = anm.item_bounds(ia), anm.item_bounds(ib)
            bounds = (min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3]))
            T, F = texel_render(new, ia, bounds)
            B = index_render(base, ib, bounds)
            row = np.where(B > 0, B.astype(np.int64) // 16, NOTHING)
            for t in np.unique(T[T >= 0]):
                sel = T == t
                V = out[int(t)][1]
                np.add.at(V.reshape(-1, NOTHING + 1), (F[sel], row[sel]), 1)
    return out


def _fit(lab, ref):
    """closeness (0..1) of colours (Lab) to reference colours, lightness at half weight"""
    d = np.linalg.norm((lab[:, None] - ref[None]) * np.array([0.5, 1.0, 1.0]), axis=2).min(1)
    return np.exp(-(d / COMPAT_TAU) ** 2)


def skin_mask(new, base, votes, log=None):
    """{texture: bool per texel: her skin}, the character's skin row it follows (None: no skin found)"""
    pal = anm.get_palette(new, 0)
    rows = base_rows(base)
    b0 = anm.get_palette(base, 0)
    skin = sorted(_skin_rows(rows, b0))
    none = ({t: np.zeros(v[0].shape, bool) for t, v in votes.items()}, None)
    if not skin:
        return none
    lab = cv._lab(pal[:, :3])
    tone = _skin_tone(pal)
    row_ids = sorted(rows)
    Vcol = np.zeros((256, NOTHING + 1))
    for ix, V in votes.values():
        m = ix > 0
        np.add.at(Vcol, ix[m], V[m])
    tot = Vcol[:, row_ids].sum(1)
    on_skin = Vcol[:, skin].sum(1)
    glob = on_skin.sum() / max(tot.sum(), 1e-9)
    bu = cv._used_indices(base)
    refs = [j for r in skin for j in rows[r]]
    ru = float(sum(bu[j] for j in refs)) or 1.0
    refs = [j for j in refs if bu[j] >= 0.15 * ru] or refs          # his main skin shades, not the darkest shading
    near = np.linalg.norm(lab[:, None] - cv._lab(b0[refs, :3])[None], axis=2).min(1) <= SKIN_REF_DE
    conf = tone & (tot >= 200) & (on_skin >= max(SKIN_CONFIRM, SKIN_GLOB * glob) * tot) & near
    if not conf.any():
        return none
    main = skin[int(np.argmax(Vcol[conf][:, skin].sum(0)))]
    like = tone & (np.linalg.norm(lab[:, None] - lab[conf][None], axis=2).min(1) <= SKIN_DE)
    like[0] = False
    ref = cv._lab(b0[rows[main], :3])
    fit = _fit(lab, ref)
    exact = np.linalg.norm(lab[:, None] - ref[None], axis=2).min(1) < EXACT_DE
    ok_col = tone | exact
    cross = ndimage.generate_binary_structure(2, 1)
    out = {}
    for t, (ix, V) in votes.items():
        op = ix > 0
        S = op & like[ix]
        # where his skin is (votes blurred over the drawing), in a colour that fits it
        sv = ndimage.gaussian_filter(V[..., skin].sum(-1).astype(float), VOTE_BLUR)
        tv = ndimage.gaussian_filter(V[..., row_ids].sum(-1).astype(float), VOTE_BLUR)
        S2 = S | (op & (tv >= 3) & (sv >= VOTE_SHARE * np.maximum(tv, 1e-6)) & (fit[ix] >= VOTE_FIT))
        comp, n = ndimage.label(S2 & ~S)
        if n:
            small = np.bincount(comp.reshape(-1)) < TINY
            small[0] = False
            S2[small[comp]] = False
        # patches enclosed by skin in colours that fit it are skin; specks of skin amid something else aren't
        for val in (False, True):
            comp, n = ndimage.label(op & (S2 == val), structure=cross)
            sizes = np.bincount(comp.reshape(-1))
            for k, sl in enumerate(ndimage.find_objects(comp), 1):
                if sl is None or sizes[k] > ISLAND_MAX:
                    continue
                y0, y1 = max(sl[0].start - 1, 0), sl[0].stop + 1
                x0, x1 = max(sl[1].start - 1, 0), sl[1].stop + 1
                m = comp[y0:y1, x0:x1] == k
                ring = ndimage.binary_dilation(m, structure=cross) & ~m & op[y0:y1, x0:x1]
                if ring.sum() < 4 or (S2[y0:y1, x0:x1][ring] != val).mean() < ISLAND_ENCLOSED:
                    continue
                cols = ix[y0:y1, x0:x1][m]
                if not val and (fit[cols].mean() < ISLAND_FIT or ok_col[cols].mean() < 0.5):
                    continue
                if val and (like[cols].mean() >= 0.5 or sizes[k] > TINY):
                    continue
                S2[y0:y1, x0:x1][m] = not val
        # smoothed over compression blocks
        f = ndimage.uniform_filter(S2.astype(np.float32), MASK_WIN)
        o = ndimage.uniform_filter(op.astype(np.float32), MASK_WIN)
        S2 = op & (((f / np.maximum(o, 1e-6) >= 0.5) & (fit[ix] >= MASK_FIT)) | like[ix])
        out[t] = S2
    if log:
        log(f"  skin: follows part {main} of the character, {int(like.sum())} skin colours")
    return out, main


def split_skin(new, mask, info):
    """her skin texels of a shade also used elsewhere get a twin entry of the same colour (in every palette); info's
    entries are updated in place (skin entries marked "skin") -> number of shades split"""
    entries = info.setdefault("entries", {})

    def get(i):
        return entries.get(str(i), entries.get(i))
    nsk = np.zeros(256, np.int64)
    non = np.zeros(256, np.int64)
    for t, m in mask.items():
        ix = anm.texture_indices(new, t)
        nsk += np.bincount(ix[m], minlength=256)[:256]
        non += np.bincount(ix[(ix > 0) & ~m], minlength=256)[:256]
    nsk[0] = non[0] = 0
    pals = [anm.get_palette(new, v) for v in range(len(new.palettes))]
    used = cv._used_indices(new)
    free = [i for i in range(255, 0, -1) if used[i] == 0 and all(p[i, 3] == 0 for p in pals) and get(i) is None]
    both = sorted((int(i) for i in np.nonzero((nsk >= MIN_SPLIT) & (non >= MIN_SPLIT))[0]),
                  key=lambda i: -min(nsk[i], non[i]))
    moved = {}
    for i in both:
        if not free:
            break
        j = free.pop(0)
        moved[i] = j
        for p in pals:
            p[j] = p[i]
        e = get(i)
        if e is not None:
            entries[str(j)] = dict(e)
    for v, p in enumerate(pals):
        anm.set_palette(new, v, p)
    if moved:
        lut = np.arange(256, dtype=np.uint8)
        for i, j in moved.items():
            lut[i] = j
        for t, m in mask.items():
            ix = anm.texture_indices(new, t)
            new.textures[t].data = np.where(m, lut[ix], ix).astype(np.uint8).tobytes()
    skin_e = {int(i) for i in np.nonzero((nsk > 0) & ((non == 0) | (nsk > non)))[0]} - set(moved)
    skin_e |= set(moved.values())
    for i in range(1, 256):
        e = get(i)
        if i in skin_e:
            if e is None:
                e = entries[str(i)] = {"part": 0}
            e["skin"] = True
        elif e is not None:
            e.pop("skin", None)
    return len(moved)


def refine_skin(sprite, base, info, fs, log=None):
    """split her skin from the shades it shares (sprite: changed in place; info: its part info, updated in place;
    the character's skin row goes to info["skin_row"]).  base: the character's own sprite file."""
    from . import sprites as _sprites
    new_p = _sprites.preview_file(fs, sprite)
    base_p = _sprites.preview_file(fs, base)
    mask, main = skin_mask(new_p, base_p, texel_votes(new_p, base_p), log=log)
    if main is None:
        info.pop("skin_row", None)
        for e in (info.get("entries") or {}).values():
            e.pop("skin", None)
        return 0
    n = split_skin(sprite, mask, info)
    info["skin_row"] = int(main)
    if log:
        log(f"  {n} shade(s) split into skin + the rest")
    return n


# ------------------------------------------------------------------------------------------- no blotches
# Shades the DRPG compression scattered over one surface (blocks of slightly different colours) must change alike in
# every variant, or the blocks show.  Each shade's change is pulled toward the changes of the shades it touches in the
# drawing, as much as they touch and as alike as their default colours are; real edges (different colours) don't pull.
# Her skin isn't pulled by what it touches unless it is a speck inside it.
REPAIR_TAU = 14.0        # dE: touching shades this alike change alike
REPAIR_SELF = 0.3        # a shade's own change, weighted per pixel
REPAIR_ITERS = 15
EMBED = 0.5              # a shade this much surrounded by another (and smaller) is a speck inside it


def repair(new, pals, part=None, skin=()):
    """variant palettes (1..) of `new` -> repaired copies; part: {index: character part it follows}"""
    p0 = anm.get_palette(new, 0)
    used = cv._used_indices(new).astype(float)
    live = np.nonzero((p0[:, 3] > 0) & (used > 0))[0]
    live = live[live > 0]
    if len(live) < 2:
        return pals
    Al = adjacency(new).astype(float)[np.ix_(live, live)]
    lab0 = cv._lab(p0[live, :3])
    Wn = Al * np.exp(-(np.linalg.norm(lab0[:, None] - lab0[None], axis=2) / REPAIR_TAU) ** 2)
    np.fill_diagonal(Wn, 0)
    if part is not None and skin:
        sk = np.isin(np.array([part.get(int(i), -1) for i in live]), list(skin))
        inside = (Al / np.maximum(Al.sum(1, keepdims=True), 1e-9) >= EMBED) & (used[live][:, None] <= used[live][None])
        Wn = Wn * ~(sk[:, None] & ~sk[None] & ~inside)
    self_w = REPAIR_SELF * used[live]
    norm = self_w + Wn.sum(1)
    out = []
    for p in pals:
        d0 = cv._lab(p[live, :3]) - lab0
        d = d0.copy()
        for _ in range(REPAIR_ITERS):
            d = (self_w[:, None] * d0 + Wn @ d) / norm[:, None]
        q = p.copy()
        q[live, :3] = cv._lab_inv(lab0 + d)
        out.append(q)
    return out
