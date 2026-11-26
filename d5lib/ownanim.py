"""Outfit sprites with their OWN complete animation set.

Humanoid sprites normally animate through the shared motion set (anm_resident block 1) whose cells are
fixed rectangles on the character's textures, so a new outfit had to be squeezed into the old pose
rectangles.  The exe patch (exepatch.LAYER_VA) lets listed outfit sprites use their own block instead;
this module builds that block:

  * a copy of the whole motion set (+ the character's own animations: idle variants 6001/7001 ...), so
    timing, movement, weapon / effect attachment and mirroring are exactly the game's
  * every ORIGINAL POSE IMAGE (cell) is replaced one-for-one by the most similar sheet frame of the same
    view (d5lib.cellmatch) -> every animation shows the same sequence of poses as the original
    (e.g. damage = stand, hurt, flinch, hurt, stand)
  * frames get their own atlas cells (never clipped); a frame keeps the original cell's transform, only
    the pivot is moved by the frame's offset inside the original cell -> motion stays as smooth as the
    original
  * small overlay pieces are replaced by the sheet's matching 'hand' rows or hidden
"""
import copy
import dataclasses

import numpy as np
from PIL import Image

from . import anm, cellmatch
from .frameconvert import recolor

PAGE = 1024        # atlas page size (the game's own sprites use 1024 / 512 textures)
PAD = 4
# animations whose sheet row is known: plain stand, the character's own idle / special poses
OWN_ANIM_ROWS = {1: "stand", 7: "stand", 6001: "wait", 6007: "wait", 7001: "stand", 7007: "stand"}
# a source's own special poses, when prepared, replace the stand those ids otherwise borrow (D5 scripts play them
# through motions 150-158: motion 150 -> 7001, 151 -> 7011)
SPECIAL_ROWS = {7001: "special", 7007: "special", 7011: "special2", 7017: "special2"}


def special_rows(sequences):
    """{animation id: row} for the special poses the sequences carry, in the view each id faces."""
    return {aid: row for aid, row in SPECIAL_ROWS.items() if (row, "back" if aid % 10 == 7 else "front") in sequences}
VARIANTS = [(0, 0, 0), (120, 0, 0), (200, 0.05, 0), (60, 0, 0.05), (0, -0.6, -0.05)]


# The Quest Shop's "... has joined!" banner draws the companion file (sprite + 1) with the shared humanoid motion
# (anm_resident block 1, animation 1 at its first key), not with the sprite's own animations: two fixed rectangles of
# texture 0, the body BANNER_BODY drawn with its top-left at BANNER_AT from the feet, and BANNER_BEHIND behind it.
# A game sprite has its standing picture exactly there.  banner_layout puts an own-animation sprite's standing
# picture in BANNER_BODY where that motion shows it, and keeps the rest of the CORNER_W x CORNER_H corner empty.
BANNER_BODY = (0, 0, 120, 192)
BANNER_AT = (-59, -172)
BANNER_BEHIND = (0, 192, 56, 192)
CORNER_W, CORNER_H = 256, 392
CORNER = CORNER_W


def _pack_spread(sizes, pages, page=PAGE, pad=PAD, corner=None):
    """_pack, but the frames are spread over exactly ``pages`` pages (one atlas page each).

    A rebuild that must keep the receiver bank's image-header count (the wheel-freeze rule) cannot
    just pack as few pages as fit: the install-time bank has N pages and the rebuilt bank must be
    able to fill them with real art instead of blank padding.  Frames are assigned to the page
    with the least used area (largest first), then each page is shelf-packed on its own; a
    partition that does not fit one page each is retried with one page fewer, and finally the
    natural ``_pack`` result is returned (the caller's shape check then reports the difference).
    """
    n = len(sizes)
    if pages is None or pages <= 0 or n == 0:
        return _pack(sizes, page=page, pad=pad, corner=corner)
    order = sorted(range(n), key=lambda i: (-sizes[i][1] * sizes[i][0], -sizes[i][1]))
    corner_index = (corner if isinstance(corner, int) else corner[0]) if corner is not None else None
    for target in range(pages, 0, -1):
        if target > n and corner_index is None:
            continue                                   # more pages than frames: a blank page anyway
        bins = [[] for _ in range(target)]
        area = [0] * target
        for i in order:
            if i == corner_index:
                bins[0].append(i)                      # the banner corner always sits on page 0
                area[0] += sizes[i][0] * sizes[i][1]
                continue
            k = min(range(target), key=lambda j: (area[j], j))
            bins[k].append(i)
            area[k] += sizes[i][0] * sizes[i][1]
        pos = [None] * n
        ok = True
        for k, members in enumerate(bins):
            if not members:
                continue                               # a blank page of PAD fits anywhere
            members = sorted(members, key=lambda i: (-sizes[i][1], -sizes[i][0]))
            corner_k = corner if (k == 0 and corner is not None and corner_index in members) else None
            sub, count = _pack(sizes, page=page, pad=pad, corner=corner_k, only=members)
            if count > 1:
                ok = False
                break
            for i in members:
                p, x, y = sub[i]
                pos[i] = (p + k, x, y)
        if ok:
            return pos, target
    return _pack(sizes, page=page, pad=pad, corner=corner)


def _pack(sizes, page=PAGE, pad=PAD, corner=None, only=None):
    """Shelf packing, tallest first -> [(page, x, y)], page count.  corner: the frame that goes to the top-left of
    page 0 with nothing else in the CORNER_W x CORNER_H corner -- its index (placed at the very corner) or
    (index, (x, y)).  only: restrict the packing to these frame indices (already ordered by the caller)."""
    order = list(range(len(sizes))) if only is None else [i for i in only]
    order = sorted(order, key=lambda i: (-sizes[i][1], -sizes[i][0]))
    pos = [None] * len(sizes)
    pages = []  # [x, y, shelf_h]
    if corner is not None:
        ci, (cx, cy) = corner if isinstance(corner, tuple) else (corner, (pad // 2, pad // 2))
        w, h = sizes[ci]
        if cx + w + pad <= page and cy + h + pad <= page:
            pages.append([max(CORNER_W, cx + w + pad), 0, max(CORNER_H, cy + h + pad)])
            pos[ci] = (0, cx, cy)
            order = [i for i in order if i != ci]
    for i in order:
        w, h = sizes[i]
        if w + pad > page or h + pad > page:
            raise ValueError("frame %dx%d larger than a %d texture" % (w, h, page))
        for p, st in enumerate(pages):
            if st[0] + w + pad > page:
                st[0], st[1], st[2] = 0, st[1] + st[2], 0
            if st[1] + h + pad <= page:
                pos[i] = (p, st[0] + pad // 2, st[1] + pad // 2)
                st[0] += w + pad
                st[2] = max(st[2], h + pad)
                break
        else:
            pages.append([w + pad, 0, h + pad])
            pos[i] = (len(pages) - 1, pad // 2, pad // 2)
    return pos, len(pages)


def _palette(frames, colors=255, iters=16, power=0.55):
    """Shared palette for RGBA arrays -> (256x4 palette, [index arrays]).  Pillow's octree palette, refined by
    weighted k-means: every colour counts as (pixels ** 0.55), so the few pixels of eyes, mouths and highlights get
    palette colours of their own instead of being merged into the big areas (the octree alone was ~1.6x further
    from the Disgaea RPG drawings and smeared their eyes)."""
    from scipy.spatial import cKDTree
    if type(colors) is not int or not 1 <= colors <= 255:
        raise ValueError("colors must be an integer in 1..255 (index 0 is transparent)")
    flat = np.concatenate([f.reshape(-1, 4) for f in frames], 0)
    vis = flat[:, 3] > 0
    unique, inverse = np.unique(flat[vis], axis=0, return_inverse=True)
    if len(unique) <= colors:
        # Sparse art needs no quantization. Avoid more k-means centres than
        # visible colours, preserving semitransparent RGBA exactly.
        pal = np.zeros((256, 4), np.uint8)
        pal[1:1 + len(unique)] = unique
        idx = np.zeros(len(flat), np.uint8)
        idx[vis] = inverse + 1
        out, pos = [], 0
        for f in frames:
            h, w = f.shape[:2]
            out.append(idx[pos:pos + h * w].reshape(h, w))
            pos += h * w
        return pal, out
    side = int(np.ceil(np.sqrt(len(flat))))
    pad = np.zeros((side * side, 4), np.uint8)
    pad[:len(flat)] = flat
    q = Image.fromarray(pad.reshape(side, side, 4), "RGBA").quantize(
        colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    qp = np.array(q.getpalette("RGBA")[:colors * 4], np.uint8).reshape(-1, 4)
    vis = flat[:, 3] > 0
    if vis.any():
        W = np.array([1.0, 1.15, 0.85, 1.3])          # green most visible; alpha edges matter

        def feat(c):
            c = c.astype(np.float64)
            return np.concatenate([c[:, :3] * (c[:, 3:4] / 255.0), c[:, 3:4]], 1) * W
        key = np.ascontiguousarray(flat[vis]).view(np.uint32).ravel()
        uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        uc = uk.view(np.uint8).reshape(-1, 4)
        if len(uc) <= colors:                           # (pixel art: its own colours fit as they are)
            pal = np.zeros((256, 4), np.uint8)
            pal[1:1 + len(uc)] = uc
            idx = np.zeros(len(flat), np.int32)
            idx[vis] = inv.ravel() + 1
            out, pos = [], 0
            for f in frames:
                h, w_ = f.shape[:2]
                out.append(idx[pos:pos + h * w_].reshape(h, w_).astype(np.uint8))
                pos += h * w_
            return pal, out
        X = feat(uc)
        w = cnt.astype(np.float64) ** power
        C = feat(qp)
        for _ in range(iters):
            d, a = cKDTree(C).query(X)
            sw = np.bincount(a, w, len(C))
            ok = sw > 0
            for j in range(4):
                s_ = np.bincount(a, w * X[:, j], len(C))
                C[ok, j] = s_[ok] / sw[ok]
            empty = np.nonzero(~ok)[0]
            if len(empty):                              # re-seed at the worst-served colours
                k = min(len(empty), len(X))
                C[empty[:k]] = X[np.argsort(-(d ** 2) * w)[:k]]
        _, a = cKDTree(C).query(X)
        # palette colour = the pixel-weighted mean of its real colours
        sw = np.bincount(a, cnt, len(C))
        P = np.stack([np.bincount(a, cnt * uc[:, j].astype(np.float64), len(C)) for j in range(4)], 1)
        P = np.where(sw[:, None] > 0, P / np.maximum(sw, 1)[:, None], 0)
        qp = np.clip(np.round(P), 0, 255).astype(np.uint8)
        qp[sw == 0] = 0
        _, a2 = cKDTree(feat(qp)).query(X)
        idx = np.zeros(len(flat), np.int32)
        idx[vis] = a2[inv.ravel()] + 1
    else:
        idx = np.zeros(len(flat), np.int32)
    pal = np.zeros((256, 4), np.uint8)
    pal[1:1 + len(qp)] = qp
    out, pos = [], 0
    for f in frames:
        h, w_ = f.shape[:2]
        out.append(idx[pos:pos + h * w_].reshape(h, w_).astype(np.uint8))
        pos += h * w_
    return pal, out


def _index_to_palette(pal, frames):
    """Index RGBA arrays against an existing palette (nearest colour in _palette's feature space).

    Used when a large explicitly supplied row must not take part in fitting the palette: the donor's
    own artwork then quantises exactly as it did before, and only the supplied row may approximate.
    """
    from scipy.spatial import cKDTree
    rows = np.nonzero(pal[:, 3] > 0)[0]
    rows = rows[rows > 0]
    qp = pal[rows]

    def feat(c):
        c = c.astype(np.float64)
        return np.concatenate([c[:, :3] * (c[:, 3:4] / 255.0), c[:, 3:4]], 1) * np.array([1.0, 1.15, 0.85, 1.3])

    out, pos = [], 0
    flat = np.concatenate([f.reshape(-1, 4) for f in frames], 0)
    idx = np.zeros(len(flat), np.uint8)
    vis = flat[:, 3] > 0
    if vis.any() and len(qp):
        _, inv = np.unique(np.ascontiguousarray(flat).view(np.uint32).ravel(), return_inverse=True)
        _, first = np.unique(np.ascontiguousarray(flat).view(np.uint32).ravel(), return_index=True)
        uc = flat[first]
        _, a = cKDTree(feat(qp)).query(feat(uc))
        idx[vis] = rows[a[inv[vis]]]
    for f in frames:
        h, w = f.shape[:2]
        out.append(idx[pos:pos + h * w].reshape(h, w))
        pos += h * w
    return out


def _extend_palette(pal, frames, tolerance=2.0):
    """Add exact colours the fitted palette lacks to its unused entries.

    The palette is fitted without the shared walk so the donor's other animations keep their exact
    colours; a colour the stand/idle art never showed (a boot sole, an inner leg) would otherwise be
    approximated. Returns (palette, added colours) -- nothing is added when the entries run out.
    """
    from scipy.spatial import cKDTree
    pal = pal.copy()
    flat = np.concatenate([f.reshape(-1, 4) for f in frames], 0)
    colours = np.unique(flat[flat[:, 3] > 0], axis=0)

    def feat(c):
        c = c.astype(np.float64)
        return np.concatenate([c[:, :3] * (c[:, 3:4] / 255.0), c[:, 3:4]], 1) * np.array([1.0, 1.15, 0.85, 1.3])

    rows = np.nonzero(pal[:, 3] > 0)[0]
    rows = rows[rows > 0]
    d, _ = cKDTree(feat(pal[rows])).query(feat(colours))
    missing = colours[d > tolerance]
    free = [i for i in range(1, len(pal)) if pal[i, 3] == 0]
    added = []
    for colour, slot in zip(missing, free):
        pal[slot] = colour
        added.append(dict(index=int(slot), colour=[int(v) for v in colour]))
    return pal, added


def _merge(motion_block, own_block):
    """Motion set + the character's own animations (ids not in the motion set) in one block.
    Own-block keys get their cell index negated so the source cell can still be told apart."""
    b = copy.deepcopy(motion_block)
    own = copy.deepcopy(own_block)
    no, ko, xo, po, co, pa = (len(b.nodes), len(b.keys), len(b.transforms), len(b.pivots), len(b.colors),
                              len(b.params))
    have = {a.id for a in b.animations}
    for n in own.nodes:
        if n.first_key >= 0 and n.num_keys:
            n.first_key += ko
        if n.child >= 0:
            n.child += no
        if n.next >= 0:
            n.next += no
    for k in own.keys:
        k.xform += xo
        k.color += co
        k.param += pa
        k.cell = -k.cell
    for x in own.transforms:
        x.pivot += po
    b.nodes += own.nodes
    b.keys += own.keys
    b.transforms += own.transforms
    b.pivots += own.pivots
    b.colors += own.colors
    b.params += own.params
    own_ids = set()
    for a in own.animations:
        if a.id not in have:
            b.animations.append(anm.Animation(a.id, a.root + no))
            own_ids.add(a.id)
    b.animations.sort(key=lambda a: a.id)
    return b, own_ids


def _cell_usage(b, own_ids, src_cell):
    """{signed cell: dict(view, rows, pose)} for every cell shown by a body layer, and
    [(view, [pose cells])] per animation."""
    usage, groups = {}, []
    _cell_usage.timelines = timelines = {}
    for an in b.animations:
        shared = an.id not in own_ids
        view = "back" if an.id % 10 == 7 else "front"
        tracks = []
        for ni, depth, parent in b.walk(an.root):
            node = b.nodes[ni]
            if shared and node.id != 1:
                continue
            ks = list(range(node.first_key, node.first_key + node.num_keys)) \
                if node.first_key >= 0 and node.num_keys else []
            ks = [k for k in ks if b.keys[k].time >= 0]
            if any(src_cell(b.keys[k].cell) for k in ks):
                tracks.append(ks)
        if not tracks:
            continue
        times = sorted({b.keys[k].time for ks in tracks for k in ks})
        poses = set()
        for t in times:
            active = []
            for ks in tracks:
                cur = None
                for k in ks:
                    if b.keys[k].time <= t:
                        cur = k
                if cur is not None and src_cell(b.keys[cur].cell):
                    active.append(b.keys[cur].cell)
            if not active:
                continue
            area = lambda cid: src_cell(cid).w * src_cell(cid).h
            pose = max(active, key=area)
            timelines.setdefault(an.id, []).append((t, pose))
            for cid in active:
                u = usage.setdefault(cid, dict(view=view, pose=False, anims=set()))
                if cid == pose:
                    u["anims"].add(an.id)
                    u["pose"] = True
                    poses.add(cid)
        groups.append((an.id, view, sorted(poses, key=abs)))
    return usage, groups


# The donor's attachment/part animations, in the band a monster motion set keeps them: the main
# animations pull them in with a 0x100 key (Rifle Demon 1001 -> 1591, Death 1001 -> 1501) and draw them
# under that node's transform.  Their donor pictures are small pieces (a gun, a scythe blade); a D4
# source pose is ONE whole figure with no separable parts, so putting a source frame there draws the
# whole body a second time.  In the Recruiter wheel (motion 1001, sprite+0) that is exactly what Sean
# saw: D4 Rifle Demon showed a one-third-size copy of itself at its feet, D4 Death a second full-size
# reaper merged into the first (SPRITE3).
ATTACHMENT_ANIMS = range(1500, 2000)


def donor_attachments(block):
    """Animation ids of `block` that another animation attaches through a 0x100 key -- the donor's
    part/attachment animations (1501, 1511, 1591, 1601 ...).  A 0x100 key naming the character's own
    body animation (6001/6007, the humanoid sets) is not a part and is left alone.  The key's own cell
    is not a reliable test: it is an empty/signature cell for Death's set (cell 0) and a textured one
    for Rifle Demon's (cell 1); the target animation's id band is the discriminator."""
    ids = set()
    for animation in block.animations:
        for ni, _, _ in block.walk(animation.root):
            for key in block.node_keys(block.nodes[ni]):
                if (key.flags & 0xFF00) != anm.NESTED:
                    continue
                if 0 <= key.param < len(block.params):
                    ids.add(block.params[key.param])
    return {i for i in ids if i in ATTACHMENT_ANIMS}


def _blank_attachments(block, ids):
    """Give the attachment animations no picture: a source import has no separate part art, and the
    donor's part art belongs to the donor class.  Returns what was blanked, for the report."""
    blanked = []
    for animation in block.animations:
        if animation.id not in ids:
            continue
        for ni, _, _ in block.walk(animation.root):
            node = block.nodes[ni]
            for index in range(node.first_key, node.first_key + node.num_keys):
                key = block.keys[index]
                if key.cell:
                    blanked.append(dict(animation=animation.id, node=node.id, key=index,
                                        source_cell=key.cell, time=key.time))
                    key.cell = 0
    return blanked


# A *second* way the whole figure gets drawn twice, which SPRITE3's attachment rule cannot see because no
# 0x100 key is involved: the source pose is spread over several drawing items of ONE animation, and one of
# those items is a copy of a part the body item already paints.  Death (D4) is the case -- motion 1001 has
# three items (body 192x184, scythe 192x176, hands 136x64) and the hands item is painted at the lower body
# with 100% of its opaque pixels already covered by the body item and 75-100% of them byte-identical at the
# same place.  At the wheel's fractional scale (unit_apply_scale 1.0117) the duplicated antialiased edges are
# blended twice, so the copy reads as a small second figure over the main one.  Removing it draws nothing
# new: every pixel it contributes is already there, with the same colour (DEATH2 measurement, 2026-10-30).
DUPLICATE_SHARE = 0.20        # of the larger item's screen area; the humanoid hand overlays are 3-4%
DUPLICATE_INSIDE = 0.99       # of the smaller item's opaque pixels must land on the larger item
DUPLICATE_EXACT = 0.70        # ... and this many must be byte-identical RGBA at the same place
IDLE_ANIMS = (1, 7, 101, 1001, 1007)
# Sheet row that carries an explicitly supplied shared-bank walk (not matched to any animation).
WALK_SOURCE_ROW = 'walksrc'
# Sheet row that carries an explicitly supplied shared-bank damage reaction (D1C bank 1 1031/1037).
# D5's hurt animation is pose base 2 (motion 21/27): script event 15092305 plays it on the target of a
# hit together with the impact effect, and its vanilla render is a standing flinch that recovers.
DAMAGE_SOURCE_ROW = 'dmgsrc'
DAMAGE_ANIMS = {21: 'front', 27: 'back'}


def duplicate_items(sprite, anims=IDLE_ANIMS, share=DUPLICATE_SHARE, inside=DUPLICATE_INSIDE,
                    exact=DUPLICATE_EXACT, game=False, composite_tol=None):
    """Keys of `sprite` whose drawing item paints no new ink (a duplicate of a sibling item).

    Returns [(animation id, time, node index, cell index)] -- the receipt, and the keys are blanked
    (cell = 0) in place.  A key object is shared by identity across the animations that use it, so a
    blanked key disappears from every animation that draws it; that is intended (it is the same ink).

    D4IDLE1: the geometric test above ignores draw order, so an item that a LATER sibling would cover
    is judged a duplicate even when the order the game paints it in puts it on top (Death's hands strip:
    the scythe shaft between the hands).  `game=True` evaluates the picture the game draws (node root+1,
    anm.evaluate(game=True)) and `composite_tol` (fraction of the composite's opaque pixels) then keeps an
    item whose removal changes the finished picture by more than that; None keeps the old behaviour."""
    import numpy as np

    def canvas(item, x0, y0, W, H):
        img, _origin = anm.render_items(sprite, [item], scale=1.0)
        a = np.asarray(img.convert("RGBA"))
        c = np.zeros((H, W, 4), np.uint8)
        left = int(round(item.quad[:, 0].min() - x0))
        top = int(round(item.quad[:, 1].min() - y0))
        h = min(a.shape[0], H - top)
        w = min(a.shape[1], W - left)
        if h > 0 and w > 0:
            c[top:top + h, left:left + w] = a[:h, :w]
        return c

    blanked = []
    for aid in anims:
        if not anm.has_animation(sprite, aid):
            continue
        for t in anm.frame_times(sprite, ("id", aid)):
            items = anm.evaluate(sprite, ("id", aid), t, game=game)
            if len(items) < 2:
                continue
            areas = [(it.quad[:, 0].max() - it.quad[:, 0].min()) * (it.quad[:, 1].max() - it.quad[:, 1].min())
                     for it in items]
            x0 = min(it.quad[:, 0].min() for it in items) - 2
            y0 = min(it.quad[:, 1].min() for it in items) - 2
            x1 = max(it.quad[:, 0].max() for it in items) + 2
            y1 = max(it.quad[:, 1].max() for it in items) + 2
            W, H = int(x1 - x0), int(y1 - y0)
            for j, small in enumerate(items):
                if small.key.cell == 0 or not small.cell.w or not small.cell.h:
                    continue
                for i, big in enumerate(items):
                    if i == j or areas[i] <= 0 or areas[j] / areas[i] < share:
                        continue
                    cj, ci = canvas(small, x0, y0, W, H), canvas(big, x0, y0, W, H)
                    mj, mi = cj[..., 3] > 128, ci[..., 3] > 128
                    n = int(mj.sum())
                    if not n:
                        continue
                    covered = int(np.logical_and(mj, mi).sum()) / n
                    if covered < inside:
                        continue
                    same = int(np.logical_and(np.logical_and(mj, mi), (cj == ci).all(2)).sum()) / n
                    if same < exact:
                        continue
                    if composite_tol is not None:
                        bounds = anm.item_bounds(items)
                        full = np.asarray(anm.render_items(sprite, items, 0, bounds=bounds)[0].convert("RGBA"), np.int16)
                        less = np.asarray(anm.render_items(sprite, [it for it in items if it is not small], 0,
                                                           bounds=bounds)[0].convert("RGBA"), np.int16)
                        moved = int((np.abs(full - less).max(2) > 8).sum())
                        if moved > composite_tol * max(1, int((full[..., 3] > 128).sum())):
                            continue
                    blanked.append((aid, t, small.node, small.key.cell))
                    small.key.cell = 0
                    break
    return blanked



def source_paced_retime(sprite, sequences, source_times, rows):
    """Rescale each animation to the length of the source animation its frames come from.

    `source_times` = {(row, view): [tick, ...]} the source reader recorded; a receiver track that
    gets 7 donor keys cannot show a 13-pose source idle, but it must still take the source's
    *duration*, or the class plays ~4x too fast (Dragon 1001: 59 ticks vs the source's 290).
    Returns the receipt; animations whose length already agrees are untouched.
    """
    if not source_times:
        return []
    out = []
    for a in sprite.blocks[0].animations:
        view = 'back' if a.id % 10 == 7 else 'front'
        row = rows.get(a.id)
        if row is None:
            continue                     # a link/animation this import does not source (1141 ...)
        times = source_times.get((row, view)) or source_times.get((row, 'front'))
        if not times:
            continue
        src_len = max(times)
        info = anm.animation_info(sprite.blocks[0], a)
        dst = int(info.get('length') or 0)
        if src_len < 2 or dst < 2:
            continue
        ratio = src_len / float(dst)
        if 0.85 <= ratio <= 1.15:
            continue
        keys = anm.retime(sprite, [a.id], ratio)
        # the loop/end control keys must still close the animation after the rescale: a key whose
        # time now lands after the loop end would be outside the playback window (frame_times
        # truncates at the loop end, so those frames would silently disappear)
        block = sprite.blocks[0]
        anim = next(x for x in block.animations if x.id == a.id)
        tree = [k for ni, _, _ in block.walk(anim.root) for k in block.node_keys(block.nodes[ni])]
        if tree:
            last = max(k.time for k in tree)
            for k in block.node_keys(block.nodes[anim.root]):
                if (k.flags & 0xFF) in (2, 5) and k.time < last:
                    k.time = last
                    keys += 1
        out.append(dict(animation=a.id, row=row, view=view, source_length=src_len,
                        donor_length=dst, factor=round(ratio, 3), keys=keys))
    return out


def build(sequences, base_sprite: anm.AnmFile, motion_block, sprite_id, variants=None, report=None, log=None,
          prefer=None, source_fallbacks=False, whole_body=False, source_times=None,
          anchor_feet=False, uniform_offset=False, source_tracks=None, shape=None, hold_blank=False):
    """sequences: {(row name, 'front'|'back'): [PIL frames, full sheet canvases]} -> AnmFile
    (block id = sprite_id).  Row names: frameconvert.ANIM_NAMES / HAND_NAMES.  prefer: {animation id: row} the
    animations take their frames from (frameconvert.HUMAN_ROWS / MONSTER_ROWS; the own idle rows always).
    motion_block None: the base sprite carries all its animations itself (a monster).
    hold_blank: BLANKKEYS1, opt-in (default off: a rebuild must not change animations nobody asked about) -- run
    hold_blank_keys on every animation whose drawing sits on only some key times (the whole-body import keeps ONE
    main-body track per animation, `_whole_body_tracks`, so a donor whose body moves between tracks leaves blank keys).
    shape: (pages, palettes) the receiver bank already has -- the rebuilt bank is packed and given that many
    atlas pages and palette entries instead of the natural count, so a rebuild does not change the image-header
    count of a bank the game already loads (the wheel-freeze rule)."""
    if motion_block is None:
        motion_block = anm.AnmBlock(base_sprite.blocks[0].id)
    variants = variants or VARIANTS
    base_blk = base_sprite.blocks[0]
    ntex = len(base_sprite.textures)
    orig_tex = [np.asarray(anm.texture_to_image(base_sprite, i, 0)) for i in range(ntex)]
    b, own_ids = _merge(motion_block, base_blk)
    # A source pose is a whole figure: never paint one into the donor's attachment/part animations, or
    # the body is drawn a second time under the attachment's transform (SPRITE3).
    attachments = donor_attachments(b)
    attachment_keys = _blank_attachments(b, attachments)

    def src_cell(cell):
        if 0 < cell < len(b.cells) and cell >= len(motion_block.cells):
            return b.cells[cell]        # a cell this import added (the bound shared walk)
        c = motion_block.cells[cell] if cell > 0 else base_blk.cells[-cell] if cell < 0 else None
        if c is None or c.tex >= ntex or not c.w or not c.h:
            return None
        return c

    usage, groups = _cell_usage(b, own_ids, src_cell)
    cells = {}
    for cid, u in usage.items():
        c = src_cell(cid)
        cells[cid] = dict(u, rgba=orig_tex[c.tex][c.y:c.y + c.h, c.x:c.x + c.w])
    frames = []
    walk_source = {}
    damage_source = {}
    for (name, view), imgs in sequences.items():
        for img in imgs:
            canvas = None
            if isinstance(img, tuple):          # (image, (canvas h, w, top, left)): drawing bigger than its cell
                img, canvas = img
            if name == DAMAGE_SOURCE_ROW:
                # An explicitly supplied shared-bank damage reaction, same contract as the walk: it
                # never enters the sheet matching, so no other animation is re-dressed by it.
                if not canvas:
                    raise ValueError('Shared damage frames need an explicit canvas')
                damage_source.setdefault(view, []).append(
                    dict(rgba=np.asarray(img.convert("RGBA")), view=view, row=name, hand=False,
                         canvas=canvas))
                continue
            if name == WALK_SOURCE_ROW:
                # An explicitly supplied shared-bank walk. It stays out of the sheet matching: the
                # donor walk cells are shared with 21/41/31 (and the twin view), so letting the global
                # assignment see these frames would re-dress those animations. _bind_shared_walk
                # appends them after matching and points D5 11/17 at them key by key.
                if not canvas:
                    raise ValueError('Shared walk frames need an explicit canvas')
                walk_source.setdefault(view, []).append(
                    dict(rgba=np.asarray(img.convert("RGBA")), view=view, row=name, hand=False,
                         canvas=canvas))
                continue
            frames.append(dict(rgba=np.asarray(img.convert("RGBA")), view=view, row=name,
                               hand=name.endswith("_hand"), canvas=canvas))
    if not frames:
        raise ValueError("no usable frames in the sheet")
    # An extended launch canvas marks an explicitly supplied D1 shared lift.
    # Match the donor using the original held stand row first: adding a radically
    # different pose to the global assignment would otherwise alter unrelated
    # animations. Then bind the real launch drawing only to exclusive lift cells.
    lift_frames = {}
    for i, frame in enumerate(frames):
        if frame['row'] == 'launch' and frame.get('canvas'):
            view = frame['view']
            if view in lift_frames:
                raise ValueError('Multiple extended lift frames are not supported')
            lift_frames[view] = frame
            stand = next((f for f in frames if f['row'] == 'stand' and f['view'] == view), None)
            if stand is None:
                raise ValueError('Extended lift needs the original stand row')
            frames[i] = dict(stand, row='launch')
    mirrored = cellmatch.detect_mirror(cells, frames)
    for f in frames:
        if mirrored.get(f["view"]):
            f["rgba"] = np.ascontiguousarray(f["rgba"][:, ::-1])
            if f.get("canvas"):
                ch, cw, oy, ox = f["canvas"]
                f["canvas"] = (ch, cw, oy, f["rgba"].shape[1] - ox - cw)
    if log and any(mirrored.values()):
        log("sheet frames drawn mirrored (flipped to match the game): " +
            ", ".join(v for v, m in mirrored.items() if m))
    locked = cellmatch.lock_sequences([(v, ks) for _, v, ks in groups], cells, frames)
    # back-view pose -> the front-view pose shown at the same moment of the twin animation (x7 <-> x1)
    votes = {}
    tl = _cell_usage.timelines
    for aid, seq in tl.items():
        if aid % 10 != 7 or aid - 6 not in tl:
            continue
        front = tl[aid - 6]
        for t, bc in seq:
            fc = None
            for ft, c in front:
                if ft <= t:
                    fc = c
            if fc is not None and bc in cells and fc in cells and cells[bc]["view"] == "back":
                v = votes.setdefault(bc, {})
                v[fc] = v.get(fc, 0) + 1
    twins = {bc: max(v, key=v.get) for bc, v in votes.items()}
    rows = dict(prefer or {})
    rows.update(OWN_ANIM_ROWS)
    rows.update(special_rows(sequences))
    matches = cellmatch.match(cells, frames, log, locked, groups, prefer=rows, twins=twins,
                              anchor_feet=anchor_feet, uniform_offset=uniform_offset)
    held_roots = {}
    for view, frame in lift_frames.items():
        aid = 1061 if view == 'front' else 1067
        targets = [k for k, c in cells.items() if aid in c.get('anims', ()) and c['pose']]
        if not targets or any(cells[k].get('anims') != {aid} for k in targets):
            raise ValueError(f'Lift {aid} does not have exclusive donor cells')
        # Preserve the original being-lifted tree and its matches before the old
        # exclusive donor cells are bound to the carrier artwork.
        def clone_node(index):
            if index < 0:
                return -1
            node = copy.copy(b.nodes[index])
            result = len(b.nodes)
            b.nodes.append(node)
            if node.first_key >= 0 and node.num_keys:
                keys = [copy.copy(k) for k in b.node_keys(node)]
                node.first_key = len(b.keys)
                for key in keys:
                    if key.cell in targets:
                        original = key.cell
                        b.cells.append(copy.copy(b.cells[original]))
                        key.cell = len(b.cells) - 1
                        matches[key.cell] = dict(matches[original])
                    b.keys.append(key)
            node.child = clone_node(node.child)
            node.next = clone_node(node.next)
            return result
        original = next(a for a in b.animations if a.id == aid)
        held_roots[aid] = clone_node(original.root)
        if mirrored.get(view):
            frame = dict(frame, rgba=np.ascontiguousarray(frame['rgba'][:, ::-1]))
            ch, cw, oy, ox = frame['canvas']
            frame['canvas'] = (ch, cw, oy, frame['rgba'].shape[1] - ox - cw)
        index = len(frames)
        frames.append(frame)
        for k in targets:
            if k not in matches:
                raise ValueError(f'Lift {aid} donor cell has no match')
            base = matches[k]
            by, bx = cellmatch.corigin(frames[base['frame']])
            cy, cx = cellmatch.corigin(frame)
            # Anchor on the cell's own current (held stand) placement, not the sheet-wide median: the
            # lift must keep the previous pose's foot line. The extended canvas adds (cy, cx) of
            # padding above/left, and the old frame carries its own origin inside its image.
            matches[k] = dict(base, frame=index, dy=base['dy'] + by - cy, dx=base['dx'] + bx - cx)
    walk_bound = _bind_shared_walk(b, frames, matches, walk_source, mirrored) if walk_source else []
    # Preserve the donor's held 21/27 trees under private ids first: stub aliases (1011/1017, the
    # 5000-band idles and every other stub that nested the held picture) keep pointing at the
    # picture they showed, and only the real hurt slot changes.
    damage_held = _preserve_damage_held(b) if damage_source else {}
    damage_bound = (_bind_shared_damage(b, frames, matches, damage_source, mirrored)
                    if damage_source else [])
    tracks_bound = _bind_source_tracks(b, frames, matches, source_tracks, src_cell) if source_tracks else []
    fallbacks = []
    if source_fallbacks:
        from .frameconvert import frame_anchor
        for animation in b.animations:
            view = 'back' if animation.id % 10 == 7 else 'front'
            desired = rows.get(animation.id, 'stand')
            for ni, _, _ in b.walk(animation.root):
                node = b.nodes[ni]
                if node.id not in (0, 1):
                    continue  # never turn a weapon/attachment into a second body
                for key in b.node_keys(node):
                    cid = key.cell
                    old = src_cell(cid)
                    if not cid or cid in matches or old is None:
                        continue
                    rgba = orig_tex[old.tex][old.y:old.y + old.h, old.x:old.x + old.w]
                    if not (rgba[..., 3] > 40).any():
                        continue  # preserve the donor's intentionally blank key
                    candidates = [i for i, frame in enumerate(frames) if frame['view'] == view and frame['row'] == desired]
                    if not candidates:
                        candidates = [i for i, frame in enumerate(frames) if frame['view'] == view and frame['row'] == 'stand']
                    if not candidates:
                        continue
                    i = candidates[0]
                    ox, oy = frame_anchor(rgba)
                    nx, ny = frame_anchor(frames[i]['rgba'])
                    if uniform_offset and getattr(cellmatch.match, 'offsets', None):
                        # same one-canvas placement as the matched cells (see cellmatch.match)
                        oy2, ox2 = next(iter(cellmatch.match.offsets.values()))
                        matches[cid] = dict(frame=i, dx=ox2, dy=oy2, score=0, exact=False)
                    else:
                        matches[cid] = dict(frame=i, dx=ox-nx, dy=oy-ny, score=0, exact=False)
                    fallbacks.append(dict(source_cell=cid, animation=animation.id, row=frames[i]['row'], view=view,
                        reason='Unmatched donor body drawing uses a source frame at donor timing'))
    # The preserved roots are not assigned to an ID until after the old lift
    # has been placed. Include them in whole-body suppression in the meantime.
    temporary_held = [anm.Animation(65000 + n, root)
                      for n, root in enumerate(held_roots.values())]
    b.animations.extend(temporary_held)
    composition = (_whole_body_tracks(b, src_cell, matches, frames)
                   if whole_body else None)
    for animation in temporary_held:
        b.animations.remove(animation)
    hidden_keys = []
    if report is not None:
        for index, key in enumerate(b.keys):
            if not key.cell or key.cell in matches:
                continue
            owners = []
            for animation in b.animations:
                for ni, _, _ in b.walk(animation.root):
                    node = b.nodes[ni]
                    if node.first_key <= index < node.first_key + node.num_keys:
                        owners.append(dict(animation=animation.id, node=node.id))
            hidden_keys.append(dict(key_index=index, source_cell=key.cell, time=key.time, owners=owners,
                source_cell_has_primary_pose=bool(cells.get(key.cell, {}).get('pose')),
                reason='No matched source frame; donor drawing hidden'))
    out = assemble(b, motion_block, base_sprite, frames, matches, sprite_id, variants,
                   palette_fit_exclude={row['frame'] for row in walk_bound}, shape=shape)
    # the stub animations' attachment keys (1001 / 1501 ...: the character's own poses) keep their empty cells
    restore_attachment_cells(out.blocks[0], [motion_block, base_sprite.blocks[0]])
    if walk_bound:
        # Measured, not assumed, exactly like the lift: the walk drawing comes from the motion block and
        # the stand pose from the class body, so only the assembled pack can say where the foot line is.
        walk_placement = _place_shared_walk(out, walk_bound, source_times, log)
        walk_aliases = _keep_walk_aliases(out, log)
        if report is not None:
            report['shared_walk_placement'] = walk_placement
            report['shared_walk_aliases'] = walk_aliases
    if damage_bound:
        damage_placement = _place_shared_damage(out, damage_bound, log)
        damage_aliases = _repoint_damage_aliases(out, damage_held, log)
        if report is not None:
            report['shared_damage'] = damage_bound
            report['shared_damage_placement'] = damage_placement
            report['shared_damage_aliases'] = damage_aliases
    if lift_frames:
        # Keep other donor aliases on the original stand fallback; only 1141/1147
        # name the newly authored lift. A separate parameter prevents changing
        # another key that shares the original parameter table entry.
        block = out.blocks[0]
        # Measure the original held tree against the stand in the assembled pack.
        # Aliases redirected to stand must preserve the held tree's exact pivot placement.
        def _corner(aid):
            items = anm.evaluate(out, ('id', aid), anm.frame_times(out, ('id', aid))[0], nested=True)
            image, origin = anm.render_items(out, items, palette_index=0)
            bbox = image.getchannel('A').getbbox()
            if bbox is None:
                raise ValueError(f'blank animation {aid}')
            return (bbox[0] - origin[0], bbox[1] - origin[1])
        corrections = {}
        by_id = {a.id: a for a in block.animations}
        for target, stand in ((1061, 1), (1067, 7)):
            root = by_id[target].root
            by_id[target].root = held_roots[target]
            try:
                held_corner = _corner(target)
                stand_corner = _corner(stand)
                corrections[target] = tuple(int(round(h - s)) for h, s in zip(held_corner, stand_corner))
            finally:
                by_id[target].root = root
        for ai, animation in enumerate(block.animations):
            if animation.id in (1141, 1147) or not anm.is_stub(out, 0, ai):
                continue
            for ni, _, _ in block.walk(animation.root):
                for key in block.node_keys(block.nodes[ni]):
                    if anm.is_nested(key) and key.param < len(block.params):
                        target = block.params[key.param]
                        if target in (1061, 1067):
                            key.param = len(block.params)
                            block.params.extend([1 if target == 1061 else 7, 0, -1])
                            transform = copy.copy(block.transforms[key.xform])
                            dx, dy = corrections[target]
                            transform.x += dx
                            transform.y += dy
                            key.xform = len(block.transforms)
                            block.transforms.append(transform)
        # The lift drawing comes from the motion block while the stand pose comes from the class's own
        # body block; the two do not share an origin, so the lift would float or sink against the
        # stand. Measure both with the kit renderer and put the lift on the pack's stand foot line.
        def _bottom(aid):
            items = anm.evaluate(out, ('id', aid), anm.frame_times(out, ('id', aid))[0], nested=True)
            image, origin = anm.render_items(out, items, palette_index=0)
            bbox = image.getchannel('A').getbbox()
            if bbox is None:
                raise ValueError(f'blank animation {aid}')
            return bbox[3] - origin[1]

        def _shift(aid, amount):
            for animation in block.animations:
                if animation.id != aid:
                    continue
                for ni, _, _ in block.walk(animation.root):
                    for key in block.node_keys(block.nodes[ni]):
                        if key.cell > 0:
                            block.transforms[key.xform].y += amount

        for lift_id, stand_id in ((1061, 1001), (1067, 1007)):
            amount = int(round(_bottom(stand_id) - _bottom(lift_id)))
            if amount:
                _shift(lift_id, amount)
                if abs(_bottom(stand_id) - _bottom(lift_id)) > 1:
                    raise ValueError(f'Lift {lift_id} did not reach the stand foot line')
                if log:
                    log(f'lift {lift_id} moved {amount:+g} px onto the stand foot line')
    # source-paced timing: a source animation has its own length; the donor's track length makes a
    # 13-pose source idle play in 59 ticks (Dragon) or a 7-pose walk in 39 (Beast).  The receiver
    # keeps its own key count here; the whole animation is rescaled to the source's length so the
    # class moves at the pace its art was drawn for.
    # The bound walk takes the source walk's length, not the held 'wait' row's: retiming it to the wait
    # animation would play the real walk at the wrong pace (STRIDERLIFT4's packs ran 7 keys / 71 ticks).
    retime_rows = dict(rows)
    for entry in walk_bound:
        retime_rows[entry['animation']] = WALK_SOURCE_ROW
    retimed = source_paced_retime(out, sequences, source_times, retime_rows)
    uprighted = upright_whole_poses(out)
    if held_roots:
        block = out.blocks[0]
        by_id = {a.id: a for a in block.animations}
        for held, carrier, holding in ((1061, 1101, 1131),
                                       (1067, 1107, 1137)):
            lift_root = by_id[held].root
            by_id[carrier].root = lift_root
            by_id[holding].root = lift_root
            # The 114 alias still references 106, so it follows the restored carried pose.
            by_id[held].root = held_roots[held]
    if report is not None:
        report['source_paced_retime'] = retimed
        report['source_tracks'] = tracks_bound
        report['upright_whole_poses'] = uprighted
    if hold_blank:
        for a in out.blocks[0].animations:
            hold_blank_keys(out, a.id)
    # a part item that paints no new ink over a bigger item of the same animation (Death 1001's hands)
    duplicates = duplicate_items(out)
    if report is not None:
        b = out.blocks[0]
        report.update(palette_added=getattr(assemble, 'palette_added', []),
                      mirrored=mirrored, frames=len({m["frame"] for m in matches.values()}),
                      pages=len(out.textures), cells=len(cells), matched=len(matches),
                      keys_shown=assemble.shown, keys_hidden=assemble.hidden,
                      hidden_key_details=hidden_keys,
                      source_frame_fallbacks=fallbacks,
                      attachment_animations=sorted(attachments),
                      attachment_keys_blanked=attachment_keys,
                      duplicate_items_blanked=duplicates,
                      offsets=getattr(cellmatch.match, "offsets", {}),
                      whole_body_composition=composition,
                      matches=matches, frame_info=[(f["row"], f["view"]) for f in frames])
    if shape and report is not None:
        report['receiver_shape'] = dict(pages=shape[0], palettes=shape[1],
                                        pages_built=len(out.textures), palettes_built=len(out.palettes))
    return out


def _shared_walk_body_keys(b, aid):
    """Key indices of one animation's drawing layers, in time order."""
    animation = next((a for a in b.animations if a.id == aid), None)
    if animation is None:
        raise ValueError(f'Shared walk needs donor animation {aid}')
    keys = []
    for ni, _, _ in b.walk(animation.root):
        node = b.nodes[ni]
        if node.first_key < 0 or not node.num_keys:
            continue
        keys.extend(i for i in range(node.first_key, node.first_key + node.num_keys) if b.keys[i].cell)
    return animation, keys


def _bind_shared_walk(b, frames, matches, walk_source, mirrored):
    """Point D5 11/17's body keys at an explicitly supplied source walk, one frame per key.

    The donor cells these keys show are shared with the neighbouring animations (21/27, 41/47, 31,
    6001/6007), so each key gets its own copy of the donor cell: those animations keep the picture
    they had, and only the traced level-walk slot changes. Returns the receipt rows.
    """
    bound = []
    for view, supplied in sorted(walk_source.items()):
        aid = 11 if view == 'front' else 17
        animation, keys = _shared_walk_body_keys(b, aid)
        if len(keys) != len(supplied):
            raise ValueError(f'walk {aid}: the donor has {len(keys)} drawn keys, '
                             f'the source walk has {len(supplied)} frames')
        flip = mirrored.get(view)
        for index, raw in zip(keys, supplied):
            frame = raw
            if flip:
                frame = dict(raw, rgba=np.ascontiguousarray(raw['rgba'][:, ::-1]))
                ch, cw, oy, ox = raw['canvas']
                frame['canvas'] = (ch, cw, oy, raw['rgba'].shape[1] - ox - cw)
            donor_cell = b.keys[index].cell
            base = matches.get(donor_cell)
            if base is None:
                raise ValueError(f'walk {aid}: donor key {index} has no matched picture')
            by, bx = cellmatch.corigin(frames[base['frame']])
            cy, cx = cellmatch.corigin(frame)
            b.cells.append(copy.copy(b.cells[donor_cell]))
            frames.append(frame)
            b.keys[index].cell = len(b.cells) - 1
            matches[b.keys[index].cell] = dict(base, frame=len(frames) - 1, score=base.get('score'),
                                               exact=base.get('exact'),
                                               dy=base['dy'] + by - cy, dx=base['dx'] + bx - cx)
            bound.append(dict(animation=aid, view=view, key=index, donor_cell=donor_cell,
                              frame=len(frames) - 1, mirrored=bool(flip)))
    return bound


def attack_tracks(block, source_times, aids=(2071, 2077), row='attack_fist', max_frames=None):
    """MONATK1: source_tracks for a monster's normal attack (2071 front / 2077 back).

    (max_frames: spread that many of the source frames over the keys.)  A donor whose attack draws its body on one key (the rest is effect layers, which a source import hides) leaves the
    imported monster invisible for the other keys.  Each source frame of the source's own attack (row_times of
    `row_<view>`, as the source reader recorded them) becomes one key on the donor's main-body track, at the source's
    moment scaled onto the donor animation's length (the donor's pace and control keys stay).
    -> {animation id: dict(row, keys=[(time, frame number)], control=[(time, flags)])}; an animation the block lacks or a
    row without source times is left out."""
    out = {}
    for aid in aids:
        view = 'back' if aid % 10 == 7 else 'front'
        times = (source_times or {}).get(f'{row}_{view}') or (source_times or {}).get(f'{row}_front')
        animation = next((a for a in block.animations if a.id == aid), None)
        if not times or animation is None:
            continue
        length = int(anm.animation_info(block, animation).get('length') or 0)
        top = max(times) or 1
        keys, last = [], -1
        pick = list(range(len(times)))
        if max_frames and len(pick) > max_frames:       # an atlas that cannot take every frame: an even spread, ends kept
            pick = sorted({round(i * (len(times) - 1) / (max_frames - 1)) for i in range(max_frames)})
        for n in pick:
            t = times[n]
            at = 0 if n == pick[0] else max(int(round(t * length / top)) if length else t, last + 1)   # drawn from the first tick
            keys.append((at, n))
            last = at
        out[aid] = dict(row=row, keys=keys,
                        control=[(k.time, k.flags) for k in block.node_keys(block.nodes[animation.root])])
    return out


def _bind_source_tracks(b, frames, matches, tracks, src_cell):
    """Give own animations the source's own clock instead of the donor's (DD2LEN1).

    tracks = {animation id: dict(row=sheet row, keys=[(time, frame number in the row)],
    control=[(time, flags)])}: one drawn key per source moment, at the source's time, showing
    that moment's frame, and the source's control keys on the root.  The keys go on the donor's
    main-body track (the one _whole_body_tracks keeps) and each copies its largest key (cell,
    transform, placement), so the drawing sits where the donor pose sat; the other body-layer
    leaves of the animation are emptied, as whole-body would hide them anyway.  Returns the receipt.
    """
    out = []
    for aid, track in sorted(tracks.items()):
        view = 'back' if aid % 10 == 7 else 'front'
        row = [i for i, f in enumerate(frames) if f['row'] == track['row'] and f['view'] == view]
        animation = next((a for a in b.animations if a.id == aid), None)
        if animation is None or not row:
            continue
        tree = [i for i, _, _ in b.walk(animation.root)]
        shared = {i for a in b.animations if a.id != aid for i, _, _ in b.walk(a.root)}
        candidates = []                         # (area, -node, key) of each matched whole-pose key
        for ni in tree[1:]:
            node = b.nodes[ni]
            if node.id not in (0, 1) or node.first_key < 0:
                continue
            for ki in range(node.first_key, node.first_key + node.num_keys):
                cell, m = src_cell(b.keys[ki].cell), matches.get(b.keys[ki].cell)
                if cell is not None and m is not None and not frames[m['frame']].get('hand'):
                    candidates.append((cell.w * cell.h, -ni, ki))
        if not candidates:
            raise ValueError(f'source track {aid}: the donor has no matched body key')
        _, body, base_ki = max(candidates)
        body = -body
        layers = [ni for ni in tree[1:] if b.nodes[ni].id in (0, 1) and b.nodes[ni].child < 0
                  and b.nodes[ni].num_keys and all(not k.flags >> 8 for k in b.node_keys(b.nodes[ni]))]
        if shared & {animation.root, body, *layers}:
            raise ValueError(f'source track {aid}: its root or body layers are shared with another animation')
        base = b.keys[base_ki]
        base_match = matches[base.cell]
        by, bx = cellmatch.corigin(frames[base_match['frame']])
        old_cells = {k.cell for ni in {body, *layers} for k in b.node_keys(b.nodes[ni]) if k.cell}
        if not b.cells:                          # a monster's merged block starts empty and cell 0 means 'no cell'
            b.cells.append(copy.copy(src_cell(base.cell)))
        first = len(b.keys)
        for time, number in track['keys']:
            frame = row[number]
            cy, cx = cellmatch.corigin(frames[frame])
            b.cells.append(copy.copy(src_cell(base.cell)))
            key = copy.copy(base)
            key.time, key.cell = time, len(b.cells) - 1
            b.keys.append(key)
            matches[key.cell] = dict(base_match, frame=frame, dy=base_match['dy'] + by - cy,
                                     dx=base_match['dx'] + bx - cx)
        for ni in layers:
            b.nodes[ni].first_key, b.nodes[ni].num_keys = -1, 0
        b.nodes[body].first_key, b.nodes[body].num_keys = first, len(track['keys'])
        root = b.nodes[animation.root]
        template = b.keys[root.first_key] if root.num_keys else anm.Key(0, 0, 0, 0, 0, 0)
        root.first_key = len(b.keys)
        for time, flags in track['control']:
            key = copy.copy(template)
            key.time, key.flags = time, flags
            b.keys.append(key)
        root.num_keys = len(track['control'])
        live = {b.keys[i].cell for n in b.nodes if n.first_key >= 0
                for i in range(n.first_key, n.first_key + n.num_keys)}
        for cell in old_cells - live:
            matches.pop(cell, None)
        out.append(dict(animation=aid, row=track['row'], view=view, body_node=body, keys=len(track['keys']),
                        control=track['control'], emptied_layers=[n for n in layers if n != body]))
    return out


def _preserve_damage_held(b):
    """Copy the donor's held 21/27 trees under private ids before the hurt art is bound.

    Stub aliases across the bank nested the held picture these two animations drew (the walk build
    points 1011/1017 and the 5000-band idles at them on purpose). Keeping a copy of the original
    tree means those aliases can be re-pointed at exactly the picture and placement they had, while
    21/27 themselves become the source game's hurt reaction. Ids 65003/65004 are in the private
    band the lift build already uses for scratch trees; no vanilla motion id is in that range and
    the game's selector falls back rather than requesting an id a bank does not have.
    """
    preserved = {}
    ids = {21: 65003, 27: 65004}
    for animation in list(b.animations):
        new_id = ids.get(animation.id)
        if new_id is None:
            continue
        seen = {}

        def clone(index):
            if index < 0:
                return -1
            if index in seen:
                return seen[index]
            node = copy.copy(b.nodes[index])
            new = len(b.nodes)
            b.nodes.append(node)
            seen[index] = new
            node.child = clone(node.child)
            node.next = clone(node.next)
            if node.first_key >= 0 and node.num_keys:
                keys = [copy.copy(k) for k in b.keys[node.first_key:node.first_key + node.num_keys]]
                node.first_key = len(b.keys)
                node.num_keys = len(keys)
                b.keys.extend(keys)
            return new

        root = clone(animation.root)
        b.animations.append(anm.Animation(new_id, root))
        preserved[animation.id] = new_id
    return preserved


def _bind_shared_damage(b, frames, matches, damage_source, mirrored):
    """Point D5 21/27's body keys at an explicitly supplied source hurt reaction.

    The source reaction has fewer keys than the D5 slot, so the frames are placed by phase position
    (key i of K -> source frame round(i / (K-1) * (N-1))) instead of one-to-one: both are a single
    flinch-and-recover phase, and the slot keeps the receiver's own length, which is what the battle
    reaction scripts are timed against. Every key gets its own copy of the donor cell, so the
    neighbouring animations that share those cells keep the picture they had.
    """
    bound = []
    for view, supplied in sorted(damage_source.items()):
        aid = next(a for a, v in DAMAGE_ANIMS.items() if v == view)
        animation, keys = _shared_walk_body_keys(b, aid)
        count = len(supplied)
        flip = mirrored.get(view)
        placed = []
        start = len(frames)
        for n, raw in enumerate(supplied):
            frame = raw
            if flip:
                frame = dict(raw, rgba=np.ascontiguousarray(raw['rgba'][:, ::-1]))
                ch, cw, oy, ox = raw['canvas']
                frame['canvas'] = (ch, cw, oy, raw['rgba'].shape[1] - ox - cw)
            placed.append(start + n)
            frames.append(frame)
        for i, index in enumerate(keys):
            pick = placed[0] if len(keys) == 1 else placed[int(round(i / (len(keys) - 1) * (count - 1)))]
            donor_cell = b.keys[index].cell
            base = matches.get(donor_cell)
            if base is None:
                raise ValueError(f'damage {aid}: donor key {index} has no matched picture')
            frame = frames[pick]
            by, bx = cellmatch.corigin(frames[base['frame']])
            cy, cx = cellmatch.corigin(frame)
            b.cells.append(copy.copy(b.cells[donor_cell]))
            b.keys[index].cell = len(b.cells) - 1
            matches[b.keys[index].cell] = dict(base, frame=pick, score=base.get('score'),
                                               exact=base.get('exact'),
                                               dy=base['dy'] + by - cy, dx=base['dx'] + bx - cx)
            bound.append(dict(animation=aid, view=view, key=index, donor_cell=donor_cell,
                              frame=pick, source_frame=pick - placed[0], mirrored=bool(flip)))
    return bound


def _place_shared_damage(out, bound, log=None):
    """Put the bound hurt reaction on the pack's own stand foot line, measured after assembly.

    The source drawings share one canvas, so a single shift per animation keeps their relative
    motion; the lowest point of the flinch meets the stand's foot line and the median centre meets
    the stand's centre, exactly like the shared walk.
    """
    import numpy as np
    block = out.blocks[0]
    receipt = []
    for aid, view in sorted({(row['animation'], row['view']) for row in bound}):
        stand_id = 1001 if view == 'front' else 1007
        stand_items = anm.evaluate(out, ('id', stand_id), anm.frame_times(out, ('id', stand_id))[0], nested=True)
        stand_image, stand_origin = anm.render_items(out, stand_items, palette_index=0)
        _, stand_bottom, stand_centre = _content(stand_image, stand_origin)
        rows = []
        for t in anm.frame_times(out, ('id', aid)):
            items = anm.evaluate(out, ('id', aid), t, nested=True)
            image, origin = anm.render_items(out, items, palette_index=0)
            rows.append((t,) + _content(image, origin))
        dy = int(round(stand_bottom - max(r[2] for r in rows)))
        dx = int(round(stand_centre - float(np.median([r[3] for r in rows]))))
        animation = next(a for a in block.animations if a.id == aid)
        if dy or dx:
            touched = {}
            for ni, _, _ in block.walk(animation.root):
                key_iter = block.node_keys(block.nodes[ni])
                for key in key_iter:
                    if key.cell > 0:
                        if key.xform not in touched:
                            transform = copy.copy(block.transforms[key.xform])
                            transform.x += dx
                            transform.y += dy
                            touched[key.xform] = len(block.transforms)
                            block.transforms.append(transform)
                        key.xform = touched[key.xform]
        receipt.append(dict(animation=aid, view=view, dx=dx, dy=dy))
        if log:
            log(f'hurt {aid} placed dx={dx:+d} dy={dy:+d}')
    return receipt


def _repoint_damage_aliases(out, held, log=None):
    """Point the stubs that nested the held 21/27 picture at the preserved copy of it."""
    swapped = []
    if not held:
        return swapped
    block = out.blocks[0]
    for ai, animation in enumerate(block.animations):
        if animation.id in held.values() or animation.id in DAMAGE_ANIMS:
            continue
        if not anm.is_stub(out, 0, ai):
            continue
        for ni, _, _ in block.walk(animation.root):
            for key in block.node_keys(block.nodes[ni]):
                if not anm.is_nested(key) or not 0 <= key.param < len(block.params):
                    continue
                target = block.params[key.param]
                if target in held:
                    block.params.append(held[target])
                    key.param = len(block.params) - 1
                    swapped.append(dict(animation=animation.id, nested_was=target,
                                        now=held[target], time=key.time))
    if swapped and log:
        log('hurt aliases kept on the preserved held picture: ' +
            ', '.join(sorted({str(s['animation']) for s in swapped})))
    return swapped


def _content(image, origin):
    """(bbox, bottom relative to the pivot, mean x of the bottom 40 rows relative to the pivot)."""
    bbox = image.getchannel('A').getbbox()
    if not bbox:
        raise ValueError('blank render')
    import numpy as np
    alpha = np.asarray(image.getchannel('A'))
    rows = min(40, bbox[3] - bbox[1])
    band = alpha[bbox[3] - rows:bbox[3], :]
    xs = np.nonzero(band > 128)[1]
    centre = float(xs.mean()) + bbox[0] if len(xs) else (bbox[0] + bbox[2]) / 2
    return bbox, bbox[3] - origin[1], centre - origin[0]


def _keep_walk_aliases(out, log=None):
    """Keep the stub animations that nested walk 11/17 on the held stand picture they showed.

    The old walk slot drew the held wait/stand picture, so the aliases that point at it (1011/1017
    and the 5000-band idles) would otherwise start walking in place. Each nested key gets its own
    parameter naming the neighbouring animation that still draws that held picture (21/27) -- the
    one the donor already shared the walk cells with -- so content *and* placement are unchanged.
    """
    block = out.blocks[0]
    swapped = []
    for ai, animation in enumerate(block.animations):
        if animation.id in (11, 17) or not anm.is_stub(out, 0, ai):
            continue
        for ni, _, _ in block.walk(animation.root):
            for key in block.node_keys(block.nodes[ni]):
                if not anm.is_nested(key) or not 0 <= key.param < len(block.params):
                    continue
                target = block.params[key.param]
                if target not in (11, 17):
                    continue
                held = 21 if target == 11 else 27
                key.param = len(block.params)
                block.params.extend([held, 0, -1])
                swapped.append(dict(animation=animation.id, nested_was=target, now=held, time=key.time))
    if swapped and log:
        log('walk aliases kept on the held stand picture: ' +
            ', '.join(sorted({str(s['animation']) for s in swapped})))
    return swapped


def _place_shared_walk(out, bound, source_times=None, log=None):
    """Put the bound walk on the pack's own stand foot line and give it the source's length.

    Like the shared lift, the walk drawing comes from the motion block while the stand pose comes
    from the class's own body block, and the two do not share an origin. Everything is measured with
    the kit renderer after assembly; the build refuses a result that is more than 1 px off.
    """
    import numpy as np
    block = out.blocks[0]
    receipt = []
    for aid, view in sorted({(row['animation'], row['view']) for row in bound}):
        stand_id = 1001 if view == 'front' else 1007
        stand_items = anm.evaluate(out, ('id', stand_id), anm.frame_times(out, ('id', stand_id))[0], nested=True)
        stand_image, stand_origin = anm.render_items(out, stand_items, palette_index=0)
        _, stand_bottom, stand_centre = _content(stand_image, stand_origin)

        def measure():
            rows = []
            for t in anm.frame_times(out, ('id', aid)):
                items = anm.evaluate(out, ('id', aid), t, nested=True)
                image, origin = anm.render_items(out, items, palette_index=0)
                rows.append((t,) + _content(image, origin))
            return rows

        rows = measure()
        dy = int(round(stand_bottom - max(r[2] for r in rows)))
        dx = int(round(stand_centre - float(np.median([r[3] for r in rows]))))
        animation = next(a for a in block.animations if a.id == aid)
        if dy or dx:
            # one shift per distinct transform: assemble reuses a transform for identical placements
            touched = set()
            for ni, _, _ in block.walk(animation.root):
                for key in block.node_keys(block.nodes[ni]):
                    if key.cell > 0 and key.xform not in touched:
                        touched.add(key.xform)
                        block.transforms[key.xform].y += dy
                        block.transforms[key.xform].x += dx
        rows = measure()
        after = max(r[2] for r in rows)
        if abs(stand_bottom - after) > 1:
            raise ValueError(f'Walk {aid} did not reach the stand foot line')
        entry = dict(animation=aid, view=view, stand=stand_id, shift=[dx, dy],
                     stand_bottom=stand_bottom, walk_bottom=after,
                     frames=[dict(time=t, bottom=b - stand_bottom, centre=c) for t, _, b, c in rows])
        if log:
            log(f'walk {aid}: {len(rows)} frames, moved ({dx:+d}, {dy:+d}) onto stand {stand_id} foot line')
        receipt.append(entry)
    return receipt


def _whole_body_tracks(block, source_cell, matches, frames):
    """D4 prepared drawings are complete poses, unlike donor component layers.

    Keep one original main-body track per animation, chosen by its largest
    original cell area. A cell shared with a body elsewhere can also be used
    by an arm, hair or shield track: the decision must be per track/key, never
    a global cell whitelist. Only complete-pose matches on body nodes 0/1
    participate. Hands, weapon/effect nodes and empty attachment/control keys
    stay intact. No clock, transform, pivot, hierarchy or source frame changes.
    """
    areas = {}
    for index, key in enumerate(block.keys):
        match = matches.get(key.cell)
        cell = source_cell(key.cell) if key.cell else None
        if match is not None and cell is not None and cell.w and cell.h:
            if not frames[match['frame']].get('hand'):
                areas[index] = cell.w * cell.h
    kept, hidden, animations = set(), set(), []
    for animation in block.animations:
        tracks = []
        for index, _, _ in block.walk(animation.root):
            node = block.nodes[index]
            keys = ([i for i in range(node.first_key, node.first_key + node.num_keys)
                     if i in areas] if node.first_key >= 0 else [])
            if node.id in (0, 1) and keys:
                tracks.append((index, keys))
        if not tracks:
            continue
        primary, _ = max(tracks, key=lambda item: (max(areas[k] for k in item[1]), -item[0]))
        for index, keys in tracks:
            (kept if index == primary else hidden).update(keys)
        animations.append(dict(animation=animation.id, primary_node=primary,
                               candidate_nodes=[index for index, _ in tracks]))
    if kept & hidden:
        raise ValueError('Whole-body donor tracks share conflicting primary keys')
    records = [dict(key=index, source_cell=block.keys[index].cell)
               for index in sorted(hidden)]
    for index in hidden:
        block.keys[index].cell = 0
    return dict(policy='one complete source pose on the original main-body track',
                animations=animations, suppressed_component_keys=records,
                clocks_transforms_attachments_unchanged=True)


def _stand_cell(b):
    """the cell the plain stand animation (id 1, front) draws first (the biggest of its first keys), or None"""
    a = next((a for a in b.animations if a.id == 1), None)
    if a is None:
        return None
    best = None
    for ni, _, _ in b.walk(a.root):
        ks = [k for k in b.node_keys(b.nodes[ni]) if 0 < k.cell < len(b.cells)]
        if ks:
            c = b.cells[ks[0].cell]
            if best is None or c.w * c.h > best[0]:
                best = (c.w * c.h, ks[0].cell)
    return best[1] if best else None


def _stand_item(a):
    """(cell index, quad top-left x, y) of the biggest picture the stand animation (id 1, front) draws at its first
    key, when it is drawn unscaled and unturned; else None"""
    info = next((x for x in anm.list_animations(a) if x["id"] == 1), None)
    if info is None:
        return None
    best = None
    for it in anm.evaluate(a, info["index"], 0):
        c, q = it.cell, np.asarray(it.quad, float)
        if not it.key.cell or not c.w or not c.h:
            continue
        x0, y0 = q[:, 0].min(), q[:, 1].min()
        if abs(q[1][0] - q[0][0] - c.w) > 0.5 or abs(q[3][1] - q[0][1] - c.h) > 0.5:
            continue                                   # scaled, mirrored or turned
        if best is None or c.w * c.h > best[0]:
            best = (c.w * c.h, it.key.cell, int(round(x0)), int(round(y0)))
    return best[1:] if best else None


def banner_layout(a, pages=None):
    """An own-animation sprite (one block, 8-bit pages) packed again so the Quest Shop's 'has joined' banner shows
    its stand picture (see BANNER_BODY): that picture in BANNER_BODY where the shared motion draws it, nothing else
    in the CORNER_W x CORNER_H corner (BANNER_BEHIND stays empty).  Sprites built before kit 1.5 had other frames
    there, and the banner showed pieces of them.  Pixels, palettes and animations stay; only where each cell's
    picture sits changes.  -> True when the file changed

    ``pages``: pack the rects over exactly this many pages (d5lib.ownanim._pack_spread) instead of as few as
    fit.  A rebuild that has to keep a receiver bank's image-header count uses this so the atlas it writes is
    already this layout: the installer's own banner_layout call then finds the corner right and returns False,
    which keeps the page count instead of compacting it away."""
    if len(a.blocks) != 1 or not a.textures or not all(t.indexed for t in a.textures):
        return False
    b = a.blocks[0]
    if b.tex_base:
        return False
    from . import d1crig
    if d1crig.standard_banner(a):
        return False              # D1CRIG1: a bank in D5's standard sheet layout already shows the banner's stand
                                  # (the shared motion and the bank's own stand draw the same rectangles); repacking
                                  # would move every part cell of the D1C body for nothing
    W = a.textures[0].width
    atlas = [np.frombuffer(t.data, np.uint8).reshape(t.height, t.width) for t in a.textures]
    rects = {}
    for i, c in enumerate(b.cells):
        if i and c.w and c.h and c.tex < len(atlas) and c.y + c.h <= atlas[c.tex].shape[0] \
                and c.x + c.w <= atlas[c.tex].shape[1]:
            rects.setdefault((c.tex, c.x, c.y, c.w, c.h), []).append(i)
    keys = list(rects)
    if any(w + PAD > W or h + PAD > W for (_, _, _, w, h) in keys):
        return False              # a page narrower than its pictures (+ the corner padding _pack adds): sprites
                                  # whose first pages are dummies of another size (D4_Unique_50 / Desco: seven
                                  # 32 x 32 pages, then 1024 x 1024) are not a single-page-size sprite, and
                                  # _pack cannot repack them.  A cell exactly as wide as the page (a 512 x 72
                                  # banner cell on a 512 page, ids 386/387) reaches _pack's own
                                  # "frame larger than a texture" guard, so the test must include PAD too
                                  # (LIVE11 2026-10-30 aborted the whole install on that cell).
    st = _stand_item(a)
    if st is None:
        return False
    sc, qx, qy = st
    corner = next((k for k, r in enumerate(keys) if sc in rects[r]), None)
    if corner is None:
        return False
    w0, h0 = keys[corner][3], keys[corner][4]
    bx, by, bw, bh = BANNER_BODY
    u = max(0, bx + qx - BANNER_AT[0])
    v = max(0, by + qy - BANNER_AT[1])
    if h0 <= bh and v + h0 > by + bh:                  # below the body rect it would show through BANNER_BEHIND
        v = by + bh - h0
    u, v = min(u, CORNER_W - w0 - PAD // 2) if w0 + PAD < CORNER_W else u, v
    t0, x0, y0 = keys[corner][:3]
    if (t0, x0, y0) == (0, u, v) and not any(r[0] == 0 and r[1] < CORNER_W and r[2] < CORNER_H
                                              for k, r in enumerate(keys) if k != corner) \
            and (pages is None or len(a.textures) == pages):
        return False                                   # already there, alone (over the wanted page count)
    pos, n = _pack_spread([(r[3], r[4]) for r in keys], pages, page=W, corner=(corner, (u, v)))
    new = [np.zeros((W, W), np.uint8) for _ in range(n)]
    height = [0] * n
    for r, (p, x, y) in zip(keys, pos):
        t, sx, sy, w, h = r
        new[p][y:y + h, x:x + w] = atlas[t][sy:sy + h, sx:sx + w]
        height[p] = max(height[p], y + h + PAD)
        for i in rects[r]:
            c = b.cells[i]
            b.cells[i] = anm.Cell(p, c.pal, c.unk2, c.flags, x, y, w, h, c.unk8)
    fmt = a.textures[0].fmt
    textures = []
    for p in range(n):
        hh = min(W, max(16, 1 << (height[p] - 1).bit_length()))
        textures.append(anm.Image8(fmt, W, hh, 1, new[p][:hh].tobytes()))
    info = b.texture_infos[0] if b.texture_infos else anm.TextureInfo(0, W, W, 8, 0x10, 0x10, 0)
    b.texture_infos = [anm.TextureInfo(0, t.width, t.height, info.bpp, info.unk1, info.unk2, info.unk3)
                       for t in textures]
    a.textures[:] = textures
    return True


repack_corner = banner_layout


def _stand_frame(b, matches):
    """the frame the plain stand animation (id 1, front) shows first: the biggest picture its keys draw at their first
    time -> frame index, or None"""
    a = next((a for a in b.animations if a.id == 1), None)
    if a is None:
        return None
    best = None
    for ni, _, _ in b.walk(a.root):
        ks = [k for k in b.node_keys(b.nodes[ni]) if k.cell]
        if not ks:
            continue
        m = matches.get(ks[0].cell)
        if m is None:
            continue
        c = b.cells[ks[0].cell] if 0 < ks[0].cell < len(b.cells) else None
        area = (c.w * c.h) if c is not None else 0
        if best is None or area > best[0]:
            best = (area, m["frame"])
    return best[1] if best else None


def assemble(b, motion_block, base_sprite, frames, matches, sprite_id, variants=None,
             palette_fit_exclude=(), shape=None):
    """Merged block `b` (_merge) + frames [dict(rgba)] + matches {signed cell: dict(frame, dx, dy[, group])}
    (dx, dy: the frame's top-left in the original cell's space) -> AnmFile with its own atlas

    `palette_fit_exclude`: frame indices that are drawn but take no part in fitting the shared palette
    (the explicitly supplied shared walk), so every other animation keeps the exact colours it had.
    `shape`: (pages, palettes) of the receiver bank the rebuild replaces; see `build`.
    """
    variants = variants or VARIANTS

    # ---------------------------------------------------------------- atlas of the used frames
    used = sorted({m["frame"] for m in matches.values()})
    crops = {}
    for i in used:
        a = frames[i]["rgba"]
        ys, xs = np.nonzero(a[:, :, 3] > 0)
        y0, x0 = ys.min(), xs.min()
        crops[i] = (a[y0:ys.max() + 1, x0:xs.max() + 1], int(y0), int(x0))
    fit = [i for i in used if i not in set(palette_fit_exclude)]
    if len(fit) == len(used):
        pal0, idx = _palette([crops[i][0] for i in used])
    else:
        pal0, _ = _palette([crops[i][0] for i in fit])
        pal0, palette_added = _extend_palette(pal0, [crops[i][0] for i in used if i in set(palette_fit_exclude)])
        assemble.palette_added = palette_added
        idx = _index_to_palette(pal0, [crops[i][0] for i in used])
    stand = _stand_frame(b, matches)
    pos, npages = _pack_spread([(crops[i][0].shape[1], crops[i][0].shape[0]) for i in used],
                               shape[0] if shape else None,
                               corner=used.index(stand) if stand in used else None)
    pages = [np.zeros((PAGE, PAGE), np.uint8) for _ in range(npages)]
    height = [0] * npages
    tmpl = next((c for c in motion_block.cells if c.w), anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0))
    new_cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0)]
    cell_of = {}
    for i, ix, (p, x, y) in zip(used, idx, pos):
        h, w = ix.shape
        pages[p][y:y + h, x:x + w] = ix
        height[p] = max(height[p], y + h + PAD)
        cell_of[i] = len(new_cells)
        new_cells.append(anm.Cell(p, 0, tmpl.unk2, tmpl.flags, x, y, w, h, tmpl.unk8))

    # ---------------------------------------------------------------- idle-type animations
    # (frames from a sheet row without exact counterparts, e.g. 'wait'): pin the sheet canvas to ONE
    # place for the whole animation, so only the drawing's own motion shows (no drift / jitter)
    pin = {}
    by_anim = {}
    for cid, m in matches.items():
        if m.get("group") is not None:
            by_anim.setdefault(m["group"], set()).add(cid)
    for an in b.animations:
        cids = by_anim.get(an.id)
        if not cids:
            continue
        ks = []
        for ni, depth, parent in b.walk(an.root):
            for k_i in range(b.nodes[ni].first_key, b.nodes[ni].first_key + b.nodes[ni].num_keys)                     if b.nodes[ni].first_key >= 0 else []:
                key = b.keys[k_i]
                xf = b.transforms[key.xform]
                if key.cell in cids and xf.sx == 100 and xf.sy == 100 and xf.rot == 0:
                    ks.append(k_i)
        if not ks:
            continue
        pos = []
        for k_i in ks:
            key = b.keys[k_i]
            xf = b.transforms[key.xform]
            piv = b.pivots[xf.pivot]
            m = matches[key.cell]
            pos.append((xf.x - piv.x + m["dx"], xf.y - piv.y + m["dy"]))   # canvas top-left, parent space
        C = (int(round(np.median([p[0] for p in pos]))), int(round(np.median([p[1] for p in pos]))))
        for k_i in ks:
            xf = b.transforms[b.keys[k_i].xform]
            pin[k_i] = (xf.x - C[0], xf.y - C[1])        # pivot in canvas space

    # ---------------------------------------------------------------- re-point keys
    # mesh layers place their cell on 4 explicit corners (a group of 10 points: TL, TR, BR, BL, centre + 5 more)
    # instead of a pivot: the new corners are the crop rectangle mapped through the original quad
    mesh_keys = {i for n in b.nodes if n.mesh and n.first_key >= 0 for i in range(n.first_key, n.first_key + n.num_keys)}
    src_cells = b.cells
    new_xf = {}
    shown = hidden = 0
    for k_i, key in enumerate(b.keys):
        if not key.cell:
            continue
        m = matches.get(key.cell)
        if m is None:
            key.cell = 0           # old-outfit piece without a counterpart in the sheet
            hidden += 1
            continue
        crop, y0, x0 = crops[m["frame"]]
        dy, dx = m["dy"] + y0, m["dx"] + x0      # top-left of the cropped frame in original cell space
        xf = b.transforms[key.xform]
        if k_i in mesh_keys:
            src = src_cells[key.cell] if key.cell > 0 else base_sprite.blocks[0].cells[-key.cell]
            W, H = max(1, src.w), max(1, src.h)
            q = np.array([[p.x, p.y] for p in (b.pivots[xf.pivot + j] if xf.pivot + j < len(b.pivots)
                                               else anm.Pivot(0, 0) for j in range(10))], float)

            def at(x, y):
                u, v = x / W, y / H
                top = q[0] + (q[1] - q[0]) * u
                bot = q[3] + (q[2] - q[3]) * u
                return top + (bot - top) * v
            ch, cw = crop.shape[:2]
            pts = [at(dx, dy), at(dx + cw, dy), at(dx + cw, dy + ch), at(dx, dy + ch), at(dx + cw / 2, dy + ch / 2)]
            pts = [anm.Pivot(int(round(p[0])), int(round(p[1]))) for p in pts] + \
                [anm.Pivot(int(p[0]), int(p[1])) for p in q[5:10]]
            rot = xf.rot if frames[m["frame"]].get("hand") else 0
            sig = (key.xform, "mesh", tuple((p.x, p.y) for p in pts), rot)
            if sig not in new_xf:
                b.pivots.extend(pts)
                b.transforms.append(anm.Transform(xf.x, xf.y, len(b.pivots) - 10, xf.unk, xf.sx, xf.sy, rot))
                new_xf[sig] = len(b.transforms) - 1
            key.cell = cell_of[m["frame"]]
            key.xform = new_xf[sig]
            shown += 1
            continue
        piv = b.pivots[xf.pivot] if 0 <= xf.pivot < len(b.pivots) else anm.Pivot(0, 0)
        npx, npy = piv.x - dx, piv.y - dy
        if k_i in pin:
            npx, npy = pin[k_i][0] - x0, pin[k_i][1] - y0
        # A whole-pose source drawing is upright and already carries its own lean: the donor key's
        # rotation belongs to the donor's picture, not to the motion.  Painting a complete figure
        # into a rotated key is what tumbled Gargoyle's walk frame and Nightmare's idle variant
        # (rot -20..-130 on the 1500-band keys).  Overlay (hand) art keeps the donor rotation.
        rot = xf.rot if frames[m["frame"]].get("hand") else 0
        sig = (key.xform, npx, npy, rot)
        if sig not in new_xf:
            b.pivots.append(anm.Pivot(npx, npy))
            b.transforms.append(anm.Transform(xf.x, xf.y, len(b.pivots) - 1, xf.unk, xf.sx, xf.sy, rot))
            new_xf[sig] = len(b.transforms) - 1
        key.cell = cell_of[m["frame"]]
        key.xform = new_xf[sig]
        shown += 1

    b.cells = new_cells
    b.id = sprite_id
    b.tex_base = b.pal_base = 0
    textures = []
    for p in range(npages):
        hh = min(PAGE, max(16, 1 << (height[p] - 1).bit_length()))
        textures.append(anm.Image8(bytes([anm.FMT_INDEXED8, 1, 1, 1]), PAGE, hh, 1, pages[p][:hh].tobytes()))
    b.texture_infos = [anm.TextureInfo(0, t.width, t.height, 8, 0x10, 0x10, 0) for t in textures]
    npal = (shape[1] if shape else 0) or max(1, len(base_sprite.palettes))
    b.palette_infos = [anm.PaletteInfo(0, 256, 0) for _ in range(npal)]
    out = anm.AnmFile([b], textures, [])
    for p in range(npal):
        hue, sat, light = variants[p % len(variants)]
        pal = recolor(pal0, hue, sat, light) if (hue or sat or light) else pal0
        anm.set_palette(out, len(out.palettes), pal)
    # ASAGI4P2: the game draws node root+1 only (BACKVIEW1).  The template's roots link the drawing through child/next,
    # so a rebuilt bank fails game_truth 'body: render root' until each root gets the native control + container pair.
    # No-op for an animation already laid out natively.
    fix_render_roots(b)
    for n in (len(b.nodes), len(b.keys), len(b.transforms), len(b.pivots), len(b.cells)):
        if n > 32767:
            raise ValueError("animation tables too large")
    assemble.shown, assemble.hidden = shown, hidden
    return out


def restore_attachment_cells(b, sources):
    """Give attachment keys back their empty cells.

    A stub animation of the motion set (1001, 1501, 1511 ...) is a control key plus an attachment key (flags 0x100)
    that plays the character's own animation named in its param (1001 -> 6001, 1501 -> 7001).  The attachment key's
    cell is an EMPTY cell whose texture index tells the game what is attached (2: the character's own poses); some
    characters' own animations use the same.  Building an atlas turned every empty cell into cell 0 (texture 0): the
    attached animation never showed -- a character in an outfit vanished during skills (Seraphina's Dazzling Eyes).
    sources: blocks the animations come from (the motion set, the template's own block), matched by animation id and
    walked in parallel.  -> number of keys fixed"""
    by_id = {}
    for src in sources:
        for a in src.animations:
            by_id.setdefault(a.id, (src, a))
    empty, fixed = {}, 0
    for an in b.animations:
        hit = by_id.get(an.id)
        if hit is None:
            continue
        src, sa = hit
        mine, theirs = list(b.walk(an.root)), list(src.walk(sa.root))
        if len(mine) != len(theirs):
            continue
        for (ni, _, _), (si, _, _) in zip(mine, theirs):
            mk, sk = b.node_keys(b.nodes[ni]), src.node_keys(src.nodes[si])
            if len(mk) != len(sk):
                continue
            for k, s in zip(mk, sk):
                if not (s.flags & 0xFF00) or not 0 < s.cell < len(src.cells):
                    continue
                c = src.cells[s.cell]
                if c.w or c.h:
                    continue                       # a drawing: the atlas has it
                sig = (c.tex, c.pal, c.unk2, c.flags, c.unk8)
                if sig not in empty:
                    have = next((i for i, x in enumerate(b.cells) if i and not x.w and not x.h and
                                 (x.tex, x.pal, x.unk2, x.flags, x.unk8) == sig), None)
                    if have is None:
                        b.cells.append(copy.copy(c))
                        have = len(b.cells) - 1
                    empty[sig] = have
                if k.cell != empty[sig]:
                    k.cell = empty[sig]
                    fixed += 1
    return fixed


def bytes_with_id(raw: bytes, old_id, new_id) -> bytes:
    """an uncompressed single-block sprite file with its block id changed (no parse / re-serialize); falls back to
    with_id for anything else"""
    import struct
    if raw[:3] not in (b"dat", b"pac") and len(raw) > anm.FILE_HEADER_SIZE + 6             and struct.unpack_from("<I", raw, 16)[0] == 1             and struct.unpack_from("<H", raw, anm.FILE_HEADER_SIZE + 4)[0] == old_id:
        out = bytearray(raw)
        struct.pack_into("<H", out, anm.FILE_HEADER_SIZE + 4, new_id)
        return bytes(out)
    return with_id(anm.load(raw), new_id).to_bytes()


def with_id(sprite: anm.AnmFile, new_id) -> anm.AnmFile:
    out = copy.deepcopy(sprite)
    out.blocks[0].id = new_id
    return out


# --------------------------------------------------------------------------------------------
# PT1030ANIM (2026-10-30): two structural rules the built D4 banks did not follow.
#
# 1. WHEEL MOTION SHAPE.  Every D5 humanoid's wheel motion (1001 front / 1007 back) is a
#    zero-length control animation whose only body key is an empty 0x100 attachment naming the
#    class's own idle (6001 / 6007); the game plays the idle through it and loops that.  ANIMALL2
#    re-rooted 1001/1007 on the idle's node tree, so the wheel motion became a 100-160 tick
#    one-shot carrying the source idle's long first hold -- Prism Ranger, Android, Battle Suit and
#    Armor Knight looked frozen on arrival and slow afterwards.  A re-rooted copy is recognisable:
#    it shares the idle's root index, or its key stream is the idle's.
# 2. PART DRAW ORDER.  Siblings of one parent paint in chain order.  The D4 monster template chains
#    hands -> weapon -> body, so the body covers the weapon.  A composed figure wants the body
#    underneath, so the group is ordered by its largest drawing.
def _largest_cell(block, node):
    best = 0
    if node.first_key < 0 or not node.num_keys:
        return 0
    for k in block.node_keys(node):
        if k.cell and 0 < k.cell < len(block.cells):
            c = block.cells[k.cell]
            best = max(best, c.w * c.h)
    return best


def _tree_shape(block, aid):
    a = next((x for x in block.animations if x.id == aid), None)
    if a is None:
        return None
    return (a.root, tuple((k.time, k.cell, k.flags) for ni, _, _ in block.walk(a.root)
                          for k in block.node_keys(block.nodes[ni])))


def wheel_stub_shape(block, aid, idle):
    """{'native': bool, ...} -- is `aid` the native zero-length attachment stub for `idle`?"""
    a = next((x for x in block.animations if x.id == aid), None)
    if a is None:
        return None
    keys = []
    for ni, _, _ in block.walk(a.root):
        keys += block.node_keys(block.nodes[ni])
    drawings = sum(1 for k in keys if k.cell and 0 < k.cell < len(block.cells)
                   and (block.cells[k.cell].w or block.cells[k.cell].h))
    nested = [block.params[k.param] for k in keys
              if (k.flags & 0xFF00) == anm.NESTED and 0 <= k.param < len(block.params)]
    return dict(keys=len(keys), drawings=drawings, nested=nested,
                native=bool(len(keys) <= 2 and not drawings and idle in nested))


def rerooted_copy(block, aid, idle):
    """True when `aid` plays the idle's own node tree (ANIMALL2's root swap or PT1029's copy)."""
    s, i = _tree_shape(block, aid), _tree_shape(block, idle)
    if s is None or i is None:
        return False
    return s[0] == i[0] or (len(s[1]) > 2 and s[1] == i[1])


def normalize_wheel_motion(block, aid, idle):
    """Restore `aid` to the native stub shape: one control key (end) + one 0x100 key naming `idle`.

    Returns the change description, or None when the animation is already native-shaped or is a
    genuine (non-re-rooted) animation.  Nothing else in the block changes.
    """
    info = wheel_stub_shape(block, aid, idle)
    if info is None or info['native'] or not rerooted_copy(block, aid, idle):
        return None
    if not any(a.id == idle for a in block.animations):
        return None
    if idle in block.params:
        p = block.params.index(idle)
    else:
        block.params.append(idle)
        p = len(block.params) - 1
    block.keys.append(anm.Key(time=0, flags=5, cell=0, xform=0, color=0, param=p))
    k_ctl = len(block.keys) - 1
    block.keys.append(anm.Key(time=0, flags=anm.NESTED, cell=0, xform=0, color=0, param=p))
    k_body = len(block.keys) - 1
    # native order (anm_resident's own 1001): control root, container root+1, body under it -- the game draws node
    # root+1 and its children only (BACKVIEW1; anm.render_root_problems)
    r = len(block.nodes)
    block.nodes.append(anm.Node(id=0, flags=0x1000, unk2=0, unk3=0, mesh=0, unk5=0,
                                first_key=k_ctl, num_keys=1, child=-1, next=r + 1))
    block.nodes.append(anm.Node(id=0, flags=0, unk2=0, unk3=0, mesh=0, unk5=0,
                                first_key=-1, num_keys=0, child=r + 2, next=-1))
    block.nodes.append(anm.Node(id=1, flags=0x100, unk2=0, unk3=0, mesh=0, unk5=0,
                                first_key=k_body, num_keys=1, child=-1, next=-1))
    next(a for a in block.animations if a.id == aid).root = r
    block.fix_virtual_offsets()
    return dict(animation=aid, idle=idle, was_keys=info['keys'],
                was_drawings=info['drawings'], was_nested=info['nested'])


def fix_render_roots(block):
    """BACKVIEW1: give every animation the game's render-root layout (anm.render_root_problems) -> [animation ids].

    An animation whose root links its drawing through exactly one of child / next gets a new control node (the old
    root's keys) followed by a keyless container whose child is that drawing, so node root+1 holds what the kit's
    walk drew.  Old nodes stay in the table unreferenced; key, cell and image data do not change."""
    changed = []
    for a in block.animations:
        if not anm.render_root_problem(block, a):
            continue
        old = block.nodes[a.root]
        links = [x for x in (old.child, old.next) if x != -1]
        if len(links) != 1:
            continue
        r = len(block.nodes)
        block.nodes.append(dataclasses.replace(old, child=-1, next=r + 1))
        block.nodes.append(anm.Node(id=0, flags=0, unk2=0, unk3=0, mesh=0, unk5=0,
                                    first_key=-1, num_keys=0, child=links[0], next=-1))
        a.root = r
        changed.append(a.id)
    if changed:
        block.fix_virtual_offsets()
    return changed


def order_part_layers(block, anims=(1001, 1007), min_items=3):
    """Paint a composed figure's biggest part first (stable sort; equal areas keep their order)."""
    changed = []
    for aid in anims:
        a = next((x for x in block.animations if x.id == aid), None)
        if a is None:
            continue
        items = [ni for ni, _, _ in block.walk(a.root) if _largest_cell(block, block.nodes[ni])]
        if len(items) < min_items:
            continue
        for parent in sorted({p for _, _, p in block.walk(a.root)}):
            chain, i = [], (block.nodes[parent].child if parent >= 0 else -1)
            while i is not None and i >= 0:
                chain.append(i)
                i = block.nodes[i].next if block.nodes[i].next >= 0 else None
            group = [i for i in chain if i in items]
            if len(group) < 2 or not all(block.nodes[i].id == 0 for i in group):
                continue
            areas = {i: _largest_cell(block, block.nodes[i]) for i in group}
            order = sorted(group, key=lambda i: -areas[i])
            if order == group:
                continue
            seq = order + [i for i in chain if i not in group]
            for x_, y_ in zip(seq, seq[1:]):
                block.nodes[x_].next = y_
            block.nodes[seq[-1]].next = -1
            if parent >= 0:
                block.nodes[parent].child = seq[0]
            changed.append(dict(animation=aid, parent=parent, before=chain, after=seq,
                                areas=[areas[i] for i in order]))
    return changed

def upright_whole_poses(sprite, min_side=64, min_area=64 * 64):
    """Draw every whole-pose source drawing upright.

    A source pose is a complete, already-posed figure.  The donor key it replaces may carry a
    rotation (Nightmare's 1500-band idle variants: -20 .. -130 deg; Gargoyle's walk: 90 deg), which
    belongs to the donor's *picture*, not to the motion: painting a whole figure into it tumbles the
    character for that frame.  Keys still drawing a part/overlay (a hand, a wing strip) keep theirs.
    """
    changed = []
    for block in sprite.blocks:
        new_xf = {}
        for ni, _, _ in block.walk(next((a.root for a in block.animations), 0)):
            node = block.nodes[ni]
            if node.id not in (0, 1):
                continue
            for key in block.node_keys(node):
                if not key.cell or not 0 < key.cell < len(block.cells):
                    continue
                cell = block.cells[key.cell]
                if cell.w < min_side or cell.h < min_side or cell.w * cell.h < min_area:
                    continue
                xf = block.transforms[key.xform]
                if xf.rot % 360 == 0:
                    continue
                sig = (key.xform, xf.rot)
                if sig not in new_xf:
                    block.transforms.append(anm.Transform(xf.x, xf.y, xf.pivot, xf.unk,
                                                          xf.sx, xf.sy, 0))
                    new_xf[sig] = len(block.transforms) - 1
                changed.append(dict(node=node.id, time=key.time, cell=key.cell, rot=xf.rot))
                key.xform = new_xf[sig]
    return changed


# ---------------------------------------------------------------------------------------------- BLANKKEYS1
def _draws(b, key):
    c = b.cells[key.cell] if 0 < key.cell < len(b.cells) else None
    return bool(c and c.w > 0 and c.h > 0)


def hold_blank_keys(fl, aid, min_drawn=1):
    """BLANKKEYS1: an animation whose drawn pose sits on only some of its key times (a held still built on one key, a
    back view whose body track went to cell 0 on the other keys) -> every blank key time shows the nearest drawn key
    of the same layer (the previous one first), keeping that key's cell, transform and colour.  A labelled APPROXIMATION:
    the pose is held, not animated, and nothing is invented for a layer that never draws.

    Only layers private to this animation are touched (a shared layer would change the other animation too), only keys
    at a key time where the whole animation draws nothing, and only the plain picture layers (no attachment flags).
    fl: AnmFile.  -> number of keys filled (0 = nothing to do / nothing safe to do)."""
    bi, ai = anm._resolve_anim(fl, ("id", aid))
    b = fl.blocks[bi]
    a = b.animations[ai]
    tree = [i for i, _, _ in b.walk(a.root)]
    shared = {i for x in b.animations if x is not a for i, _, _ in b.walk(x.root)}
    times = anm.frame_times(fl, ("id", aid))
    drawn_at = {t: any(i.cell.w > 0 and i.cell.h > 0 for i in anm.evaluate(fl, ("id", aid), t, nested=True)) for t in times}
    if sum(drawn_at.values()) < min_drawn or all(drawn_at.values()):
        return 0
    filled = 0
    for ni in tree[1:]:
        node = b.nodes[ni]
        ks = b.node_keys(node)
        if ni in shared or not ks or node.id not in (0, 1) or any(k.flags >> 8 for k in ks):
            continue
        real = [k for k in ks if _draws(b, k)]
        if not real:
            continue
        run = {}
        for k in ks:
            if _draws(b, k) or drawn_at.get(k.time, True):
                run[k.time] = k                             # a drawn key, or a blank one at a time another layer draws
        for t in times:
            if drawn_at[t] or t in run:
                continue
            src = max((r for r in real if r.time <= t), key=lambda r: r.time, default=None) or real[0]
            nk = copy.copy(src)
            nk.time = t
            run[t] = nk
            filled += 1
        node.first_key, node.num_keys = len(b.keys), len(run)       # a fresh run at the end of the table (the old keys stay unused)
        b.keys.extend(run[t] for t in sorted(run))
    return filled


def restore_timing(fresh, old, skip=()):
    """BLANKKEYS1: a fresh rebuild draws the same pictures as the installed bank but on a different clock (the installed
    packs predate source-paced timing, PT1030ANIM e0b16c4).  Copy every key time (picture layers and control keys) from
    the installed bank `old` onto `fresh` for each animation id both hold with the same tree shape and key counts, except
    ids in `skip` (the ones the rebuild changes on purpose).  -> (animations restored, ids left on the fresh clock and why)"""
    done, left = 0, {}
    ob = {a.id: (old.blocks[bi], a) for bi, _, a in old.all_animations()}
    for bi, _, a in fresh.all_animations():
        if a.id in skip:
            continue
        if a.id not in ob:
            left[a.id] = "not in the installed bank"
            continue
        fb = fresh.blocks[bi]
        o, oa = ob[a.id]
        fw, ow = list(fb.walk(a.root)), list(o.walk(oa.root))
        if [(d, fb.nodes[i].num_keys) for i, d, _ in fw] != [(d, o.nodes[i].num_keys) for i, d, _ in ow]:
            left[a.id] = "tree shape or key counts differ"
            continue
        for (fi, _, _), (oi, _, _) in zip(fw, ow):
            for fk, ok in zip(fb.node_keys(fb.nodes[fi]), o.node_keys(o.nodes[oi])):
                fk.time = ok.time
        done += 1
    return done, left
