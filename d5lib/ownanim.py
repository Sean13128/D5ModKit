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

import numpy as np
from PIL import Image

from . import anm, cellmatch
from .frameconvert import recolor

PAGE = 1024        # atlas page size (the game's own sprites use 1024 / 512 textures)
PAD = 4
# animations whose sheet row is known: plain stand, the character's own idle / special poses
OWN_ANIM_ROWS = {1: "stand", 7: "stand", 6001: "wait", 6007: "wait", 7001: "stand", 7007: "stand"}
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


def _pack(sizes, page=PAGE, pad=PAD, corner=None):
    """Shelf packing, tallest first -> [(page, x, y)], page count.  corner: the frame that goes to the top-left of
    page 0 with nothing else in the CORNER_W x CORNER_H corner -- its index (placed at the very corner) or
    (index, (x, y))."""
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
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
    flat = np.concatenate([f.reshape(-1, 4) for f in frames], 0)
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


def build(sequences, base_sprite: anm.AnmFile, motion_block, sprite_id, variants=None, report=None, log=None,
          prefer=None):
    """sequences: {(row name, 'front'|'back'): [PIL frames, full sheet canvases]} -> AnmFile
    (block id = sprite_id).  Row names: frameconvert.ANIM_NAMES / HAND_NAMES.  prefer: {animation id: row} the
    animations take their frames from (frameconvert.HUMAN_ROWS / MONSTER_ROWS; the own idle rows always).
    motion_block None: the base sprite carries all its animations itself (a monster)."""
    if motion_block is None:
        motion_block = anm.AnmBlock(base_sprite.blocks[0].id)
    variants = variants or VARIANTS
    base_blk = base_sprite.blocks[0]
    ntex = len(base_sprite.textures)
    orig_tex = [np.asarray(anm.texture_to_image(base_sprite, i, 0)) for i in range(ntex)]
    b, own_ids = _merge(motion_block, base_blk)

    def src_cell(cell):
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
    for (name, view), imgs in sequences.items():
        for img in imgs:
            canvas = None
            if isinstance(img, tuple):          # (image, (canvas h, w, top, left)): drawing bigger than its cell
                img, canvas = img
            frames.append(dict(rgba=np.asarray(img.convert("RGBA")), view=view, row=name,
                               hand=name.endswith("_hand"), canvas=canvas))
    if not frames:
        raise ValueError("no usable frames in the sheet")
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
    matches = cellmatch.match(cells, frames, log, locked, groups, prefer=rows, twins=twins)
    out = assemble(b, motion_block, base_sprite, frames, matches, sprite_id, variants)
    # the stub animations' attachment keys (1001 / 1501 ...: the character's own poses) keep their empty cells
    restore_attachment_cells(out.blocks[0], [motion_block, base_sprite.blocks[0]])
    if report is not None:
        b = out.blocks[0]
        report.update(mirrored=mirrored, frames=len({m["frame"] for m in matches.values()}),
                      pages=len(out.textures), cells=len(cells), matched=len(matches),
                      keys_shown=assemble.shown, keys_hidden=assemble.hidden,
                      offsets=getattr(cellmatch.match, "offsets", {}),
                      matches=matches, frame_info=[(f["row"], f["view"]) for f in frames])
    return out


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


def banner_layout(a):
    """An own-animation sprite (one block, 8-bit pages) packed again so the Quest Shop's 'has joined' banner shows
    its stand picture (see BANNER_BODY): that picture in BANNER_BODY where the shared motion draws it, nothing else
    in the CORNER_W x CORNER_H corner (BANNER_BEHIND stays empty).  Sprites built before kit 1.5 had other frames
    there, and the banner showed pieces of them.  Pixels, palettes and animations stay; only where each cell's
    picture sits changes.  -> True when the file changed"""
    if len(a.blocks) != 1 or not a.textures or not all(t.indexed for t in a.textures):
        return False
    b = a.blocks[0]
    if b.tex_base:
        return False
    W = a.textures[0].width
    pages = [np.frombuffer(t.data, np.uint8).reshape(t.height, t.width) for t in a.textures]
    rects = {}
    for i, c in enumerate(b.cells):
        if i and c.w and c.h and c.tex < len(pages) and c.y + c.h <= pages[c.tex].shape[0] \
                and c.x + c.w <= pages[c.tex].shape[1]:
            rects.setdefault((c.tex, c.x, c.y, c.w, c.h), []).append(i)
    keys = list(rects)
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
                                              for k, r in enumerate(keys) if k != corner):
        return False                                   # already there, alone
    pos, n = _pack([(r[3], r[4]) for r in keys], page=W, corner=(corner, (u, v)))
    new = [np.zeros((W, W), np.uint8) for _ in range(n)]
    height = [0] * n
    for r, (p, x, y) in zip(keys, pos):
        t, sx, sy, w, h = r
        new[p][y:y + h, x:x + w] = pages[t][sy:sy + h, sx:sx + w]
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


def assemble(b, motion_block, base_sprite, frames, matches, sprite_id, variants=None):
    """Merged block `b` (_merge) + frames [dict(rgba)] + matches {signed cell: dict(frame, dx, dy[, group])}
    (dx, dy: the frame's top-left in the original cell's space) -> AnmFile with its own atlas"""
    variants = variants or VARIANTS

    # ---------------------------------------------------------------- atlas of the used frames
    used = sorted({m["frame"] for m in matches.values()})
    crops = {}
    for i in used:
        a = frames[i]["rgba"]
        ys, xs = np.nonzero(a[:, :, 3] > 0)
        y0, x0 = ys.min(), xs.min()
        crops[i] = (a[y0:ys.max() + 1, x0:xs.max() + 1], int(y0), int(x0))
    pal0, idx = _palette([crops[i][0] for i in used])
    stand = _stand_frame(b, matches)
    pos, npages = _pack([(crops[i][0].shape[1], crops[i][0].shape[0]) for i in used],
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
            sig = (key.xform, "mesh", tuple((p.x, p.y) for p in pts))
            if sig not in new_xf:
                b.pivots.extend(pts)
                b.transforms.append(anm.Transform(xf.x, xf.y, len(b.pivots) - 10, xf.unk, xf.sx, xf.sy, xf.rot))
                new_xf[sig] = len(b.transforms) - 1
            key.cell = cell_of[m["frame"]]
            key.xform = new_xf[sig]
            shown += 1
            continue
        piv = b.pivots[xf.pivot] if 0 <= xf.pivot < len(b.pivots) else anm.Pivot(0, 0)
        npx, npy = piv.x - dx, piv.y - dy
        if k_i in pin:
            npx, npy = pin[k_i][0] - x0, pin[k_i][1] - y0
        sig = (key.xform, npx, npy)
        if sig not in new_xf:
            b.pivots.append(anm.Pivot(npx, npy))
            b.transforms.append(anm.Transform(xf.x, xf.y, len(b.pivots) - 1, xf.unk, xf.sx, xf.sy, xf.rot))
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
    npal = max(1, len(base_sprite.palettes))
    b.palette_infos = [anm.PaletteInfo(0, 256, 0) for _ in range(npal)]
    out = anm.AnmFile([b], textures, [])
    for p in range(npal):
        hue, sat, light = variants[p % len(variants)]
        pal = recolor(pal0, hue, sat, light) if (hue or sat or light) else pal0
        anm.set_palette(out, len(out.palettes), pal)
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
