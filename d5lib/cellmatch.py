"""Match every pose image (cell) of a humanoid sprite to the most similar frame of a frame-dump sheet.

Frame-dump sheets of Disgaea sprites (e.g. Disgaea RPG rips) keep the ORIGINAL cell canvases: a frame
that corresponds to a game cell has exactly that cell's width/height and the drawing sits at (almost)
the same place inside it.  So:

  * candidates are the sheet frames of the same view (front / back)
  * similarity = best overlap (IoU) of the silhouettes over small shifts; frames with the exact cell size
    and the animation's own sheet row get a small bonus
  * placement: exact-size frames use ONE constant offset per view (the sheet's drawing offset measured
    over all exact matches), so the relative motion of every animation is the original's and nothing
    jitters; other frames are aligned by their best overlap
"""
import numpy as np
from scipy.signal import fftconvolve

SIZE_BONUS = 0.15
ROW_BONUS = 0.2
MAX_SHIFT = 24


def _mask(rgba):
    return (rgba[:, :, 3] > 40).astype(np.float32)


def cshape(f):
    """size of a frame's cell canvas: its own size, or f['canvas'] = (h, w, oy, ox) when the image is bigger
    than the canvas (drawings sticking out of the cell; oy, ox = canvas top-left inside the image)"""
    c = f.get("canvas")
    return (c[0], c[1]) if c else f["rgba"].shape[:2]


def corigin(f):
    c = f.get("canvas")
    return (c[2], c[3]) if c else (0, 0)


def _iou_map(o, f):
    """IoU for every placement of f (top-left at (dy, dx)) over o -> (array, origin index of shift 0)."""
    inter = fftconvolve(o, f[::-1, ::-1], mode="full")
    iou = inter / np.maximum(1e-6, o.sum() + f.sum() - inter)
    return iou, (f.shape[0] - 1, f.shape[1] - 1)


def _bottom_center(m):
    ys, xs = np.nonzero(m)
    low = ys >= ys.max() - 40
    return ys.max(), xs[low].mean()


def best_shift(o, f, around=None, radius=MAX_SHIFT):
    """(iou, dy, dx): placement of frame f in cell space of o with the best overlap, searched within
    `radius` of `around` (default: bottom-centres aligned)."""
    iou, (cy, cx) = _iou_map(o, f)
    if around is None:
        (ob, ox), (fb, fx) = _bottom_center(o), _bottom_center(f)
        around = (int(round(ob - fb)), int(round(ox - fx)))
    ay, ax = around
    y0, y1 = max(0, cy + ay - radius), min(iou.shape[0], cy + ay + radius + 1)
    x0, x1 = max(0, cx + ax - radius), min(iou.shape[1], cx + ax + radius + 1)
    sub = iou[y0:y1, x0:x1]
    if sub.size == 0:
        return 0.0, ay, ax
    k = np.unravel_index(int(sub.argmax()), sub.shape)
    return float(sub.max()), int(y0 + k[0] - cy), int(x0 + k[1] - cx)


def iou_at(o, f, dy, dx):
    H, W = o.shape
    h, w = f.shape
    oy0, ox0 = max(0, dy), max(0, dx)
    oy1, ox1 = min(H, dy + h), min(W, dx + w)
    inter = 0.0
    if oy1 > oy0 and ox1 > ox0:
        inter = (o[oy0:oy1, ox0:ox1] * f[oy0 - dy:oy1 - dy, ox0 - dx:ox1 - dx]).sum()
    return inter / max(1e-6, o.sum() + f.sum() - inter)


def detect_mirror(cells, frames, margin=0.03):
    """{view: True} for views whose sheet frames are drawn mirrored relative to the game's poses
    (rips often store the back view flipped).  Compares the overlap of every pose cell with its
    exact-size frames as they are and flipped."""
    out = {}
    for view in ("front", "back"):
        a = b = n = 0
        for k, c in cells.items():
            if c["view"] != view or not c["pose"]:
                continue
            o = _mask(c["rgba"])
            if not o.any():
                continue
            same = [_mask(f["rgba"]) for f in frames
                    if f["view"] == view and not f.get("hand") and cshape(f) == o.shape]
            if not same:
                continue
            a += max(best_shift(o, f)[0] for f in same)
            b += max(best_shift(o, np.ascontiguousarray(f[:, ::-1]))[0] for f in same)
            n += 1
        out[view] = bool(n and b / n > a / n + margin)
    return out


def lock_sequences(groups, cells, frames):
    """groups: [(view, [cell keys in original order])] (the pose cells of one animation).  When a sheet
    row of that view has exactly the same frame sizes in the same order, it IS that animation (e.g. the
    walk cycle) -> {cell key: frame index} one-for-one."""
    rows = {}
    for i, f in enumerate(frames):
        rows.setdefault((f["row"], f["view"]), []).append(i)
    out = {}
    for view, keys in groups:
        if len(keys) < 2:
            continue
        sizes = [cells[k]["rgba"].shape[:2] for k in keys]
        for (row, rv), idx in rows.items():
            if rv != view or len(idx) != len(keys) or frames[idx[0]].get("hand"):
                continue
            if [cshape(frames[i]) for i in idx] == sizes:
                for k, i in zip(keys, idx):
                    out.setdefault(k, i)
    return out


def match(cells, frames, log=None, locked=None, groups=None, prefer=None, twins=None):
    """cells:  {key: dict(rgba=array, view='front'|'back', pose=bool, anims={animation ids})}
    frames: [dict(rgba=array (full canvas), view, row=name, hand=bool)]
    locked: {cell key: frame index} fixed beforehand (see lock_sequences)
    groups: [(animation id, view, [pose cell keys])]
    prefer: {animation id: sheet row} for animations without counterparts (e.g. own idle -> 'wait')
    twins:  {back-view cell: front-view cell shown at the same moment of the twin animation}
    Returns {key: dict(frame=index, dy, dx, score, exact)} (dy, dx = frame top-left in cell space).

    Rules: a sheet frame with EXACTLY the cell's size is the cell's counterpart (the rips keep the
    original canvases), so exact-size candidates are the only ones considered when they exist; back-view
    animations prefer the rows their front-view twin matched; each frame normally stands for one
    original pose (global assignment), sharing costs a little.  Overlay cells (pose=False) only take
    exact-size 'hand' frames."""
    from scipy.optimize import linear_sum_assignment
    fmasks = [_mask(f["rgba"]) for f in frames]
    cmasks = {k: _mask(c["rgba"]) for k, c in cells.items()}
    locked = dict(locked or {})
    row_pos, seen = [], {}
    for f in frames:        # index of each frame within its sheet row
        key = (f["row"], f["view"])
        row_pos.append(seen.get(key, 0))
        seen[key] = row_pos[-1] + 1
    groups = groups or []
    front_cells = {aid: ks for aid, view, ks in groups if view == "front"}
    raw = {}
    COPIES, SHARE_COST = 6, 0.03

    def candidates(k, pref_rows, any_size=False, pref_pos=None, only_rows=None):
        c = cells[k]
        o = cmasks[k]
        H, W = o.shape
        cand = {}
        for i, f in enumerate(frames):
            if k in locked and locked[k] != i:
                continue
            if f["view"] != c["view"] or not fmasks[i].any():
                continue
            if only_rows and f["row"] not in only_rows:
                continue
            exact = cshape(f) == (H, W)
            if bool(f.get("hand")) == c["pose"] and not (exact and f.get("hand")):
                continue
            if not c["pose"] and not exact:
                continue
            s_, dy, dx = best_shift(o, fmasks[i])
            score = s_ + (SIZE_BONUS if exact else 0) + (ROW_BONUS if f["row"] in pref_rows else 0) +                 (ROW_BONUS / 2 if pref_pos is not None and row_pos[i] == pref_pos else 0)
            cand[i] = (score, dy, dx, exact, s_)
        if not any_size and any(v[3] for v in cand.values()):
            cand = {i: v for i, v in cand.items() if v[3]}
        return cand

    # animations without any exact-size counterpart (e.g. the character's own idle animation vs the
    # sheet's 'wait' row): take ONE row for the whole animation, frames in order, one common offset
    group_shift, group_of = {}, {}
    used = {}
    for i in locked.values():
        used[i] = used.get(i, 0) + 1
    for aid, view, ks in groups:
        ks = [k for k in ks if k in cells and k not in locked and cmasks[k].any()]
        if len(ks) < 2:
            continue
        sizes = {cmasks[k].shape for k in ks}
        own = all(isinstance(k, int) and k < 0 for k in ks)   # character's own animation (idle)
        if not own and any(cshape(f) in sizes and f["view"] == view and not f.get("hand")
                           for i, f in enumerate(frames)):
            continue
        per_row = {}
        for k in ks:
            for i, v in candidates(k, set(), any_size=True).items():
                r = per_row.setdefault(frames[i]["row"], {})
                r[k] = max(r.get(k, 0), v[0])
        if not per_row:
            continue
        nfr = {r: sum(1 for f in frames if f["row"] == r and f["view"] == view) for r in per_row}
        row = max(per_row, key=lambda r: sum(per_row[r].values()) / len(ks) * min(1, nfr[r] / len(ks)))
        if prefer and prefer.get(aid) in nfr:
            row = prefer[aid]
        idx = [i for i, f in enumerate(frames) if f["row"] == row and f["view"] == view]
        shifts = []
        for j, k in enumerate(ks):
            i = idx[round(j * (len(idx) - 1) / max(1, len(ks) - 1))] if len(ks) <= len(idx) else                 idx[min(len(idx) - 1, j * len(idx) // len(ks))]
            locked[k] = i
            shifts.append(best_shift(cmasks[k], fmasks[i])[1:])
        med = (int(np.median([x[0] for x in shifts])), int(np.median([x[1] for x in shifts])))
        for k in ks:
            group_shift[k] = med
            group_of[k] = aid

    for view in ("front", "back"):
        table = {}
        for k, c in cells.items():
            if c["view"] != view or not cmasks[k].any():
                continue
            pref, pos = {prefer[a] for a in c.get("anims", ()) if prefer and a in prefer}, None
            if view == "back" and twins and twins.get(k) in raw:
                fi = raw[twins[k]][1]
                pref, pos = {frames[fi]["row"]}, row_pos[fi]
                # the back view of an animation uses the same sheet row as its front view
                cand = candidates(k, pref, pref_pos=pos, only_rows=pref, any_size=True) or                     candidates(k, pref, pref_pos=pos)
            else:
                cand = candidates(k, pref, pref_pos=pos)
            if not cand:
                continue
            if c["pose"] and k not in locked:
                table[k] = cand
            else:
                i = max(cand, key=lambda j: cand[j][0])
                raw[k] = (cand[i][0], i) + cand[i][1:]
        if not table:
            continue
        keys = list(table)
        fr = sorted({i for c in table.values() for i in c})
        cols = [(i, j) for i in fr for j in range(COPIES)]
        cost = np.full((len(keys), len(cols)), 10.0)
        for r, k in enumerate(keys):
            for ci, (i, j) in enumerate(cols):
                if i in table[k]:
                    cost[r, ci] = -(table[k][i][0] - SHARE_COST * (j + used.get(i, 0)))
        rr, cc = linear_sum_assignment(cost)
        for r, ci in zip(rr, cc):
            k, i = keys[r], cols[ci][0]
            if i not in table[k]:
                i = max(table[k], key=lambda j: table[k][j][0])
            raw[k] = (table[k][i][0], i) + table[k][i][1:]

    # row consistency: a pose that belongs only to animations whose other poses come from one sheet row
    # (e.g. a sword swing) must use that row too, not a same-size frame of another weapon
    from collections import Counter
    majority = {}
    for aid, view, ks in groups:
        rows_ = [frames[raw[k][1]]["row"] for k in ks if k in raw and len(cells[k].get("anims", ())) <= 4]
        if len(rows_) >= 2:
            majority[aid] = Counter(rows_).most_common(1)[0][0]
    for k in list(raw):
        c = cells[k]
        if not c["pose"] or k in locked:
            continue
        ms = {majority.get(a) for a in c.get("anims", ())}
        if len(ms) != 1 or None in ms:
            continue
        R = ms.pop()
        if frames[raw[k][1]]["row"] == R or frames[raw[k][1]].get("hand"):
            continue
        cand = candidates(k, {R}, any_size=True, only_rows={R})
        if cand:
            i = max(cand, key=lambda j: cand[j][0])
            raw[k] = (cand[i][0], i) + cand[i][1:]

    # one drawing offset per view, measured over the exact-size pose matches
    offsets = {}
    for view in ("front", "back"):
        # canvas top-left in cell space (= image top-left + the canvas' place inside the image)
        sh = [(v[2] + corigin(frames[v[1]])[0], v[3] + corigin(frames[v[1]])[1])
              for k, v in raw.items() if v[4] and cells[k]["pose"] and cells[k]["view"] == view]
        if sh:
            offsets[view] = (int(np.median([s[0] for s in sh])), int(np.median([s[1] for s in sh])))
    out = {}
    for k, (score, i, dy, dx, exact, s) in raw.items():
        view = cells[k]["view"]
        if exact and view in offsets:
            gy, gx = offsets[view]
            gy, gx = gy - corigin(frames[i])[0], gx - corigin(frames[i])[1]
            # keep the constant offset unless it is clearly worse than the free fit
            if iou_at(cmasks[k], fmasks[i], gy, gx) >= s - 0.12:
                dy, dx = gy, gx
        if k in group_shift:
            dy, dx = group_shift[k]
        out[k] = dict(frame=i, dy=dy, dx=dx, score=round(score, 3), exact=exact, group=group_of.get(k))
    if log:
        log(f"cell matching: {len(out)} of {len(cells)} cells, drawing offsets {offsets}")
    match.offsets = offsets
    return out
