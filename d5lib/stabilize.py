"""Steady placement for outfits made from unlabelled frames (Disgaea RPG atlases).

Frames from a DRPG atlas come trimmed: where each drawing sat in its cell had to be guessed per frame (best overlap
with the reference pose), and the guesses differ by a few pixels from frame to frame -> the idle loop and other
animations jitter in game.  Outfits made from a labelled sheet keep the real cell canvases, so their feet move
exactly like the game's own sprite.

All outfits of one character share the same animation tables (ownanim.build on the same base sprite), so key k
shows the same pose in every outfit.  stabilize() moves every drawn key of an outfit so that its feet follow the
feet of a reference outfit (a labelled one) at the same key -- keeping each animation's overall offset (median),
so only the frame-to-frame jitter goes.  Only pivots change: the sheets (and the colour parts painted on them)
stay as they are.  Overlay pieces (hands) move with the body drawn at the same moment."""
import numpy as np

from . import anm

FEET_ROWS = 6          # the feet: the lowest rows of the drawing
MAX_FIX = 14           # bigger differences are not jitter (a different drawing): left alone
MAX_FIX_IDLE = 30      # idle loops (feet always planted): bigger fixes are still jitter
IDLE = {6001, 6007, 7001, 7007, 1, 7}


def _alpha(sprite):
    pal = anm.get_palette(sprite, 0)
    out = {}
    for t, tex in enumerate(sprite.textures):
        if tex.indexed:
            out[t] = pal[anm.texture_indices(sprite, t)][..., 3] > 60
    return out


def _anchor(alpha, it):
    """feet of the item's drawing in world space, or None"""
    c = it.cell
    m = alpha.get(it.tex_global)
    if m is None or c.w * c.h == 0:
        return None
    sub = m[c.y:c.y + c.h, c.x:c.x + c.w]
    ys, xs = np.nonzero(sub)
    if len(ys) < 30:
        return None
    low = ys >= ys.max() - FEET_ROWS
    a = np.array([xs[low].mean() + 0.5, ys.max() + 1.0])
    q = it.quad
    L = np.column_stack([(q[1] - q[0]) / c.w, (q[3] - q[0]) / c.h])
    return q[0] + L @ a, L


def _body(items):
    items = [it for it in items if it.cell.w * it.cell.h > 0]
    return max(items, key=lambda it: it.cell.w * it.cell.h) if items else None


def corrections(sprite, ref_sprite, log=None):
    """{key index: pivot shift (dx, dy) in cell space} that make `sprite` follow `ref_sprite`'s feet"""
    al, ar = _alpha(sprite), _alpha(ref_sprite)
    key_index = {id(k): i for i, k in enumerate(sprite.blocks[0].keys)}
    out = {}
    stats = []
    for info in anm.list_animations(sprite):
        if not info["layers"]:
            continue
        idx = info["index"]
        times = anm.frame_times(sprite, idx)
        rows = []
        for t in times:
            a_items = anm.evaluate(sprite, idx, t)
            r_items = anm.evaluate(ref_sprite, idx, t)
            ba, br = _body(a_items), _body(r_items)
            if ba is None or br is None:
                continue
            fa, fr = _anchor(al, ba), _anchor(ar, br)
            if fa is None or fr is None:
                continue
            rows.append((t, fr[0] - fa[0], fa[1], a_items, ba))
        if len(rows) < 2:
            continue
        med = np.median(np.array([r[1] for r in rows]), 0)
        before, after = [], []
        for t, delta, L, items, body in rows:
            fix = delta - med
            before.append(fix)
            if np.abs(fix).max() > (MAX_FIX_IDLE if info["id"] in IDLE else MAX_FIX):
                continue
            after.append(fix)
            try:
                shift = -np.linalg.solve(L, fix)
            except np.linalg.LinAlgError:
                continue
            for it in items:
                if it.cell.w * it.cell.h == 0:
                    continue
                k = key_index.get(id(it.key))
                if k is None:
                    continue
                # an overlay drawn with another transform: its own cell-space shift
                if it is not body:
                    q, c = it.quad, it.cell
                    Li = np.column_stack([(q[1] - q[0]) / c.w, (q[3] - q[0]) / c.h])
                    try:
                        s = -np.linalg.solve(Li, fix)
                    except np.linalg.LinAlgError:
                        continue
                else:
                    s = shift
                out.setdefault(k, []).append(s)
        if before:
            b = np.abs(np.array(before))
            stats.append((info["id"], float(b.max())))
    if log:
        worst = sorted(stats, key=lambda s: -s[1])[:8]
        log("  feet jitter before (px, worst animations): " + ", ".join(f"{a}:{v:.0f}" for a, v in worst))
    return {k: np.mean(v, 0) for k, v in out.items()}


def apply(sprite, fixes):
    """move the pivots (new pivot / transform entries; others sharing them stay as they were)"""
    b = sprite.blocks[0]
    made = {}
    n = 0
    for k, (dx, dy) in fixes.items():
        dx, dy = int(round(dx)), int(round(dy))
        if not dx and not dy:
            continue
        key = b.keys[k]
        xf = b.transforms[key.xform]
        if not (0 <= xf.pivot < len(b.pivots)):
            continue
        piv = b.pivots[xf.pivot]
        sig = (key.xform, piv.x + dx, piv.y + dy)
        if sig not in made:
            b.pivots.append(anm.Pivot(piv.x + dx, piv.y + dy))
            b.transforms.append(anm.Transform(xf.x, xf.y, len(b.pivots) - 1, xf.unk, xf.sx, xf.sy, xf.rot))
            made[sig] = len(b.transforms) - 1
        key.xform = made[sig]
        n += 1
    if len(b.transforms) > 32767 or len(b.pivots) > 32767:
        raise ValueError("animation tables too large")
    return n


def stabilize(sprite, ref_sprite, log=None):
    """sprite and ref_sprite: preview files (motion sets bound) of two outfits of the same character"""
    fixes = corrections(sprite, ref_sprite, log)
    return apply(sprite, fixes)


STAND_FROM = {1: 6001, 7: 6007}     # stand pose -> the idle loop it should match (front, back)


def stand_like_idle(sprite):
    """DRPG battle atlases start with a 'ready' pose that looks nothing like the unit's idle loop; the game shows
    the stand pose for a moment whenever the unit stops or starts moving, so it flashes.  Every key that draws the
    stand pose gets the idle loop's first frame instead, feet on the same spot.  -> {key index: (cell, pivot)}"""
    infos = {x["id"]: x for x in anm.list_animations(sprite) if x["layers"]}
    al = _alpha(sprite)
    b = sprite.blocks[0]
    key_index = {id(k): i for i, k in enumerate(b.keys)}
    out = {}
    for stand, idle in STAND_FROM.items():
        if stand not in infos or idle not in infos:
            continue
        sb = _body(anm.evaluate(sprite, infos[stand]["index"], 0))
        ib = _body(anm.evaluate(sprite, infos[idle]["index"], 0))
        if sb is None or ib is None or sb.key.cell == ib.key.cell:
            continue
        stand_cell, idle_cell = sb.key.cell, ib.key.cell
        # where the idle frame sits relative to the stand frame of the stand animation (in stand-cell units),
        # carried to every other use of the stand pose (attacks start from it, moved / mirrored)
        Ls = np.column_stack([(sb.quad[1] - sb.quad[0]) / sb.cell.w, (sb.quad[3] - sb.quad[0]) / sb.cell.h])
        d0 = np.linalg.solve(Ls, ib.quad[0] - sb.quad[0])
        for info in infos.values():
            for t in anm.frame_times(sprite, info["index"]):
                for it in anm.evaluate(sprite, info["index"], t):
                    if it.key.cell != stand_cell:
                        continue
                    k = key_index.get(id(it.key))
                    if k is None or k in out:
                        continue
                    c = it.cell
                    L = np.column_stack([(it.quad[1] - it.quad[0]) / c.w, (it.quad[3] - it.quad[0]) / c.h])
                    # drawing moved by L @ d0  <=>  pivot moved by -d0 (cell space)
                    xf = b.transforms[it.key.xform]
                    piv = b.pivots[xf.pivot]
                    out[k] = (idle_cell, (int(round(piv.x - d0[0])), int(round(piv.y - d0[1]))))
    return out


def apply_cells(sprite, changes):
    b = sprite.blocks[0]
    made = {}
    for k, (cell, (px, py)) in changes.items():
        key = b.keys[k]
        xf = b.transforms[key.xform]
        sig = (key.xform, px, py)
        if sig not in made:
            b.pivots.append(anm.Pivot(px, py))
            b.transforms.append(anm.Transform(xf.x, xf.y, len(b.pivots) - 1, xf.unk, xf.sx, xf.sy, xf.rot))
            made[sig] = len(b.transforms) - 1
        key.cell = cell
        key.xform = made[sig]
    return len(changes)


IDLE_LOOPS = (6001, 6007)
FEET_BOX = 16          # rows above the lowest drawn pixel that make the feet
SEARCH = 6


def _render(sprite, idx, t, bounds):
    im, _ = anm.render_items(sprite, anm.evaluate(sprite, idx, t), 0, bounds=bounds)
    return np.asarray(im).astype(np.int16)


def _static_shift(a, b, lo, R=SEARCH):
    """(dy, dx) to move b so its unmoving lower body (pixels identical in colour) covers a's best"""
    A = a[lo:]
    aop = A[..., 3] > 128
    best = (-1e9, 0, 0)
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            Bs = np.roll(np.roll(b, dy, 0), dx, 1)[lo:]
            bop = Bs[..., 3] > 128
            eq = aop & bop & (np.abs(A[..., :3] - Bs[..., :3]).max(-1) <= 6)
            s = int(eq.sum()) - 0.25 * int((aop ^ bop).sum()) - 0.01 * (dy * dy + dx * dx)
            if s > best[0]:
                best = (s, dy, dx)
    return best[1], best[2]


def lock_idle_feet(sprite, anims=IDLE_LOOPS, log=None):
    """Idle loops with the feet exactly still (like the game's own sprites): every frame of the loop is moved so
    its unmoving lower body (legs, shoes: pixels of the same colour at the same place) covers the first frame's.
    Moving parts (wing tips, tails, capes) don't count: their pixels don't match.  -> {key index: pivot shift}"""
    infos = {x["id"]: x for x in anm.list_animations(sprite) if x["layers"]}
    key_index = {id(k): i for i, k in enumerate(sprite.blocks[0].keys)}
    B = (-120, -220, 120, 40)
    out = {}
    for aid in anims:
        if aid not in infos:
            continue
        idx = infos[aid]["index"]
        times = anm.frame_times(sprite, idx)
        f0 = _render(sprite, idx, times[0], B)
        ys = np.nonzero((f0[..., 3] > 128).any(1))[0]
        if not len(ys):
            continue
        lo = int(ys.max() - 0.3 * (ys.max() - ys.min()))
        moved = []
        for t in times[1:]:
            dy, dx = _static_shift(f0, _render(sprite, idx, t, B), lo)
            if not dy and not dx:
                continue
            moved.append((t, dy, dx))
            fix = np.array([dx, dy], float)            # world shift that puts this frame's legs on frame 0's
            for it in anm.evaluate(sprite, idx, t):
                c = it.cell
                if c.w * c.h == 0:
                    continue
                k = key_index.get(id(it.key))
                if k is None or k in out:
                    continue
                q = it.quad
                L = np.column_stack([(q[1] - q[0]) / c.w, (q[3] - q[0]) / c.h])
                try:
                    out[k] = -np.linalg.solve(L, fix)
                except np.linalg.LinAlgError:
                    pass
        if log and moved:
            log(f"  idle {aid}: feet locked on {len(moved)} frame(s) {[(dy, dx) for _, dy, dx in moved]}")
    return out


def shift_animation(sprite, aid, dx, dy):
    """{key index: pivot shift} that moves every drawing of animation `aid` by (dx, dy) on screen"""
    infos = {x["id"]: x for x in anm.list_animations(sprite) if x["layers"]}
    key_index = {id(k): i for i, k in enumerate(sprite.blocks[0].keys)}
    out = {}
    idx = infos[aid]["index"]
    fix = np.array([dx, dy], float)
    for t in anm.frame_times(sprite, idx):
        for it in anm.evaluate(sprite, idx, t):
            c = it.cell
            k = key_index.get(id(it.key))
            if c.w * c.h == 0 or k is None or k in out:
                continue
            q = it.quad
            L = np.column_stack([(q[1] - q[0]) / c.w, (q[3] - q[0]) / c.h])
            out[k] = -np.linalg.solve(L, fix)
    return out


def _bottom(sprite, aid, B=(-120, -220, 120, 40)):
    infos = {x["id"]: x for x in anm.list_animations(sprite) if x["layers"]}
    f = _render(sprite, infos[aid]["index"], 0, B)
    ys = np.nonzero((f[..., 3] > 128).any(1))[0]
    return int(ys.max()) + B[1]


def idle_ground(sprite, ref_sprite, tolerance=5, log=None):
    """Idle loops standing on the same ground as the stand pose: when an idle loop's feet sit higher / lower than
    the stand pose's by more than `tolerance` px beyond what the reference outfit has, the loop is moved
    vertically to the reference's step.  -> {key index: pivot shift}"""
    out = {}
    for stand, idle in ((1, 6001), (7, 6007)):
        want = _bottom(ref_sprite, idle) - _bottom(ref_sprite, stand)
        have = _bottom(sprite, idle) - _bottom(sprite, stand)
        if abs(have - want) > tolerance:
            out.update(shift_animation(sprite, idle, 0, want - have))
            if log:
                log(f"  idle {idle}: moved {want - have:+d} px to stand on the stand pose's ground")
    return out
