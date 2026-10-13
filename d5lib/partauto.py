"""Colour parts for a sprite: automatic first pass and the clean-up rules the part painter applies.

materials(sprite)   the sprite's colours grouped into materials (shade ramps: hair, skin, cloth ...).  Colours
                    are compared by hue first (a ramp keeps its hue from dark to light), then chroma and,
                    least, lightness; colours drawn next to each other a lot count as closer.  A colour belongs
                    to one material everywhere, so every animation frame agrees.
rows_from(...)      per-pixel parts from a colour -> part table
cleanup(...)        the rules that make parts look clean in motion, applied the same way in every frame:
                      * a patch completely surrounded by one other part joins it, whatever its size (a print on
                        the hood is the hood in every pose)
                      * black lines inside the drawing join the part around them; only the outline stays details
                      * small patches surrounded by skin in the upper part of a frame are the eyes
                      * remaining specks (a few pixels) join their surroundings
auto_parts(sprite)  materials -> parts (biggest first) -> cleanup; -> (rows, names)
"""
import numpy as np
from scipy import ndimage

from . import anm
from .colorvariants import _lab

EIGHT = np.ones((3, 3))
CUT = 10.0             # material clustering distance (fine: the painter maps several materials to one part)
MAX_PARTS = 13         # + eyes, + details
SPECK = 10             # specks up to this size join their surroundings
ENCLOSED = 0.92        # share of a patch's border touching one other part to count as enclosed
ENCLOSED_MAX = 900     # bigger patches are real parts even when enclosed (a skirt over legs ...)


def stats(sprite):
    pal = anm.get_palette(sprite, 0).astype(np.int64)
    texs = [i for i, t in enumerate(sprite.textures) if t.indexed]
    ind = {t: anm.texture_indices(sprite, t).astype(np.int64) for t in texs}
    op = {t: (ind[t] > 0) & (pal[ind[t], 3] > 0) for t in texs}
    count = np.zeros(256, np.int64)
    adj = np.zeros((256, 256), np.int64)
    for t in texs:
        i, o = ind[t], op[t]
        np.add.at(count, i[o], 1)
        for a, b, ma in ((i[:, :-1], i[:, 1:], o[:, :-1] & o[:, 1:]), (i[:-1], i[1:], o[:-1] & o[1:])):
            m = ma & (a != b)
            np.add.at(adj, (a[m], b[m]), 1)
    return pal, texs, ind, op, count, adj + adj.T


def colour_name(lab):
    L, a, b = [float(x) for x in lab]
    C = float(np.hypot(a, b))
    h = float(np.degrees(np.arctan2(b, a))) % 360
    if C < 9:
        return "White" if L > 80 else "Grey" if L > 38 else "Dark"
    if 30 <= h < 80 and L > 60 and C < 42:
        return "Skin"
    for top, n in [(15, "Pink"), (40, "Red"), (65, "Orange"), (95, "Gold"), (125, "Yellow"), (165, "Green"),
                   (215, "Teal"), (250, "Cyan"), (300, "Blue"), (335, "Purple"), (361, "Pink")]:
        if h < top:
            if n == "Red" and L > 68:
                n = "Pink"
            return ("Dark " if L < 28 else "") + n


def _lch(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    return L, np.hypot(a, b), np.arctan2(b, a)


def materials(sprite, cut=CUT):
    """-> (material per colour index (-1 unused, 0 = black outline colours), {material: dict(count, lab, name)})"""
    from scipy.cluster.hierarchy import linkage, fcluster
    pal, texs, ind, op, count, adj = stats(sprite)
    lab = _lab(pal[:, :3].astype(np.uint8))
    used = [c for c in range(1, 256) if count[c] > 0]
    black = [c for c in used if lab[c][0] < 9]
    cols = [c for c in used if c not in black]
    mat = np.full(256, -1)
    for c in black:
        mat[c] = 0
    if cols:
        L, C, H = _lch(lab[cols])
        dH = 2 * np.sqrt(np.outer(C, C)) * np.abs(np.sin((H[:, None] - H[None]) / 2))
        d = np.sqrt(dH ** 2 + (0.55 * (C[:, None] - C[None])) ** 2 + (0.28 * (L[:, None] - L[None])) ** 2)
        aff = adj[np.ix_(cols, cols)] / np.maximum(1, np.minimum.outer(count[cols], count[cols]))
        d = d * (1.0 - 0.6 * np.clip(aff * 2.5, 0, 1))
        n = len(cols)
        groups = fcluster(linkage(d[np.triu_indices(n, 1)], "average"), t=cut, criterion="distance") \
            if n > 1 else np.array([1])
        total = count[cols].sum()
        for _ in range(4):        # tiny groups join the group they touch most
            sizes = {g: int(count[[c for c, gg in zip(cols, groups) if gg == g]].sum()) for g in set(groups)}
            changed = False
            for g in sorted(sizes, key=sizes.get):
                if sizes[g] >= total * 0.003 or len(sizes) <= 2:
                    continue
                mine = [c for c, gg in zip(cols, groups) if gg == g]
                touch = {}
                for c, gg in zip(cols, groups):
                    if gg != g:
                        touch[gg] = touch.get(gg, 0) + int(adj[mine, c].sum())
                if touch and max(touch.values()) > 0:
                    groups = np.where(groups == g, max(touch, key=touch.get), groups)
                    changed = True
                    break
            if not changed:
                break
        sizes = {g: int(count[[c for c, gg in zip(cols, groups) if gg == g]].sum()) for g in set(groups)}
        order = sorted(sizes, key=lambda g: -sizes[g])
        for k, g in enumerate(order, 1):
            for c, gg in zip(cols, groups):
                if gg == g:
                    mat[c] = k
    info = {}
    for m in sorted(set(mat[mat >= 0])):
        cs = [c for c in used if mat[c] == m]
        w = count[cs]
        mean = (lab[cs] * w[:, None]).sum(0) / max(1, w.sum())
        info[int(m)] = dict(count=int(w.sum()), lab=mean, name="Details" if m == 0 else colour_name(mean),
                            colours=cs)
    return mat, info


def rows_from(sprite, part_of):
    """part_of: part per colour index -> {texture: part per pixel (-1 transparent)}"""
    pal, texs, ind, op, _, _ = stats(sprite)
    part_of = np.asarray(part_of)
    return {t: np.where(op[t], part_of[ind[t]], -1) for t in texs}


def _comp_border(r, lab, i, sl):
    sl2 = tuple(slice(max(s.start - 2, 0), s.stop + 2) for s in sl)
    c2 = lab[sl2] == i
    ring = ndimage.binary_dilation(c2, EIGHT) & ~c2
    return sl2, c2, r[sl2][ring]


def relocate(r, part, to, limit=150, touch=None, distance=10):
    """patches of `part` smaller than `limit` px, farther than `distance` from its big areas (and touching part
    `touch`, if given) -> `to` (e.g. sandal straps drawn in the hair's colours, on the skin of the feet)"""
    lab, k = ndimage.label(r == part, structure=EIGHT)
    if not k:
        return
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, k + 1))
    big = np.isin(lab, np.nonzero(sizes >= limit)[0] + 1)
    near = ndimage.distance_transform_edt(~big) if big.any() else np.full(r.shape, np.inf)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sizes[i - 1] >= limit:
            continue
        comp = lab[sl] == i
        if near[sl][comp].min() <= distance:
            continue
        if touch is not None:
            sl2, c2, nb = _comp_border(r, lab, i, sl)
            nb = nb[nb >= 0]
            if not len(nb) or (nb == touch).mean() < 0.15:
                continue
        sub = r[sl]
        sub[comp] = to


def absorb(r, part, into, share=0.8, only=None):
    """patches of `part` whose border (inside the drawing) is mostly `into` join it (a hair strand drawn all in
    shadow colours, which other parts also use); only: a mask -- just the patches of those pixels (e.g. one
    highlight colour shared by the clothes and the legs)"""
    lab, k = ndimage.label((r == part) if only is None else (r == part) & only, structure=EIGHT)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        sl2, c2, nb = _comp_border(r, lab, i, sl)
        nb = nb[nb >= 0]
        nb = nb[nb != 0]
        if len(nb) >= 3 and (nb == into).mean() >= share:
            sub = r[sl2]
            sub[c2] = into


def cleanup(rows, eyes_part=None, skin_parts=(), protect=(), details=0, moves=(), absorbs=(), eye_from=(),
            ind=None):
    """the rules described above, in place; moves: [(part, to, limit[, touch])] for relocate(),
    absorbs: [(part, into[, share[, [palette colours]]])] for absorb() (colours need ind: {tex: colour indices});
    eye_from: parts whose colours also draw the eyes (eyes mixing
    several parts' colours: their small patches together, in the face, become eyes); -> changed patches"""
    changed = 0
    for t, r in rows.items():
        for mv in moves:
            relocate(r, *mv)
        for ab in absorbs:
            if len(ab) > 3:
                if ind is not None:
                    absorb(r, ab[0], ab[1], ab[2], np.isin(ind[t], list(ab[3])))
            else:
                absorb(r, *ab)
        frames, _ = ndimage.label(r >= 0, structure=EIGHT)
        fobjs = ndimage.find_objects(frames)
        # black lines inside the drawing join the part around them (the outline touches transparency)
        det = r == details
        if det.any():
            inside = det & ~ndimage.binary_dilation(r < 0, EIGHT)
            other = (r >= 0) & ~det
            if inside.any() and other.any():
                _, (iy, ix) = ndimage.distance_transform_edt(~other, return_indices=True)
                r[inside] = r[iy[inside], ix[inside]]
        # eyes
        if eyes_part is not None and skin_parts:
            for p in set(np.unique(r)) - set(skin_parts) - {-1, eyes_part}:
                lab, _ = ndimage.label(r == p, structure=EIGHT)
                for i, sl in enumerate(ndimage.find_objects(lab), 1):
                    comp = lab[sl] == i
                    if comp.sum() > 70:
                        continue
                    sl2, c2, nb = _comp_border(r, lab, i, sl)
                    nb = nb[nb >= 0]
                    if not len(nb) or np.isin(nb, list(skin_parts) + [eyes_part]).mean() < 0.45:
                        continue
                    fid = frames[sl][comp][0]
                    fsl = fobjs[fid - 1][0] if fid else None
                    if fsl is None or (sl[0].start - fsl.start) / max(1, fsl.stop - fsl.start) > 0.42:
                        continue
                    sub = r[sl2]
                    sub[c2] = eyes_part
                    changed += 1
            if eye_from:
                lab, _ = ndimage.label(np.isin(r, list(eye_from)), structure=EIGHT)
                for i, sl in enumerate(ndimage.find_objects(lab), 1):
                    comp = lab[sl] == i
                    if comp.sum() > 140:
                        continue
                    sl2, c2, nb = _comp_border(r, lab, i, sl)
                    nb = nb[nb > 0]
                    if not len(nb) or np.isin(nb, list(skin_parts) + [eyes_part]).mean() < 0.3:
                        continue
                    fid = frames[sl][comp][0]
                    fsl = fobjs[fid - 1][0] if fid else None
                    if fsl is None or (sl[0].start - fsl.start) / max(1, fsl.stop - fsl.start) > 0.42:
                        continue
                    sub = r[sl2]
                    sub[c2] = eyes_part
                    changed += 1
        # enclosed patches and specks
        for _ in range(3):
            n = 0
            for p in set(np.unique(r)) - {-1} - set(protect) - ({eyes_part} if eyes_part is not None else set()):
                lab, k = ndimage.label(r == p, structure=EIGHT)
                if not k:
                    continue
                sizes = ndimage.sum(np.ones_like(lab), lab, range(1, k + 1))
                for i, sl in enumerate(ndimage.find_objects(lab), 1):
                    size = sizes[i - 1]
                    if size > ENCLOSED_MAX:
                        continue
                    sl2, c2, nb = _comp_border(r, lab, i, sl)
                    if (nb < 0).mean() > 0.1:       # on the outline: a real edge of the drawing
                        if size > SPECK:
                            continue
                    nb = nb[nb >= 0]
                    if len(nb) < 3:
                        continue
                    vals, cnt = np.unique(nb, return_counts=True)
                    y = vals[cnt.argmax()]
                    share = cnt.max() / len(nb)
                    if y != p and (share >= ENCLOSED or (size <= SPECK and share >= 0.6)):
                        sub = r[sl2]
                        sub[c2] = y
                        n += 1
            changed += n
            if not n:
                break
    return changed


def auto_parts(sprite, log=None):
    mat, info = materials(sprite)
    order = [m for m in sorted(info, key=lambda m: -info[m]["count"]) if m != 0]
    part_of = np.full(256, -1)
    names = {0: "Details"}
    for k, m in enumerate(order[:MAX_PARTS], 1):
        for c in info[m]["colours"]:
            part_of[c] = k
        names[k] = info[m]["name"]
    for m in order[MAX_PARTS:]:           # the rest join the nearest kept material
        to = min(order[:MAX_PARTS], key=lambda q: float(((info[q]["lab"] - info[m]["lab"]) ** 2).sum()))
        for c in info[m]["colours"]:
            part_of[c] = order.index(to) + 1
    if 0 in info:
        for c in info[0]["colours"]:
            part_of[c] = 0
    rows = rows_from(sprite, part_of)
    skin = [p for p, n in names.items() if n.startswith("Skin")]
    eyes = max(names) + 1
    names[eyes] = "Eyes"
    cleanup(rows, eyes_part=eyes, skin_parts=skin)
    if not any((r == eyes).any() for r in rows.values()):
        names.pop(eyes)
    _dedupe(names)
    if log:
        log("auto parts: " + ", ".join(f"{p} {n}" for p, n in sorted(names.items())))
    return rows, names


def _dedupe(names):
    seen = {}
    for p in sorted(names):
        n = names[p]
        seen[n] = seen.get(n, 0) + 1
        if seen[n] > 1:
            names[p] = f"{n} {seen[n]}"
