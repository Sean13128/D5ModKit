"""Disgaea RPG unit sprites -> frame sequences for an outfit (d5lib.ownanim).

A DRPG unit comes as four packed atlases: battle front / back (every action pose, the hand overlays) and
wait front / back (the idle loop).  The frames are the same poses as the labelled frame dumps the kit already
reads (frameconvert.ANIM_NAMES), but trimmed and packed by size: no row labels and no cell canvas.

Every humanoid DRPG unit shares that frame set, so one labelled unit is the reference
(data/drpg_ref_humanoid.pickle, made by _research/drpg_make_ref.py): label, view, cell canvas size and where
the drawing sits in it.  A new unit's frames are matched to the reference frames of the same atlas by
silhouette (best overlap over small shifts, one-to-one assignment); a matched frame takes the reference's
label, row position and canvas, placed where its silhouette fits the reference drawing best.  The canvas
travels with the frame (ownanim takes (image, canvas) pairs), so drawings larger than the cell (wings, capes)
are never clipped.  Detached bits of a frame (wing tips, floating hair) are merged into the frame they sit
next to in the atlas.
"""
import os
import pickle

import numpy as np
from PIL import Image
from scipy import ndimage

from .modsys import KIT_DIR

ROOTS = [os.path.join(KIT_DIR, "DRPG Assets (Updated)"), os.path.join(KIT_DIR, "DRPG Assets"),
         os.path.join(KIT_DIR, "DRPG Assets (Generated)")]   # SpriteForge output (same layout as Updated)
REF_PATH = os.path.join(os.path.dirname(__file__), "data", "drpg_ref_humanoid.pickle")
MERGE_GAP = 3          # atlas pieces this close to a bigger piece belong to the same frame
MIN_IOU = 0.2          # weaker matches are not used
ALPHA_NOISE = 8        # alpha at or below this is texture-compression noise, not drawing


# idle sheets that can't be used at all: left out, the idle of that view is made from the battle sheet's drawings
# ... from this battle pose (name, frame) of the view, breathing (drpgmap.regions; default the plain stand).  None
# now: Santa Liezerota 261's back idle, which faces the camera, is used as DRPG draws it, the hair behind her
# (back_idle_faces_front).
WRONG_VIEW = {}
WRONG_VIEW_POSE = {}


def unit_sheets(uid, roots=None):
    """{'front', 'back', 'wait_front', 'wait_back': png path} of DRPG unit `uid` (minus WRONG_VIEW sheets)."""
    out = _unit_sheets(uid, roots)
    for k in WRONG_VIEW.get(int(uid), ()):
        out.pop(k, None)
    return out


def _unit_sheets(uid, roots=None):
    for root in roots or ROOTS:
        a = os.path.join(root, "Characters", "Sprites")
        if os.path.exists(os.path.join(a, "front", f"front{uid}.png")):
            return {"front": os.path.join(a, "front", f"front{uid}.png"),
                    "back": os.path.join(a, "back", f"back{uid}.png"),
                    "wait_front": os.path.join(a, "wait_front", f"front{uid}.png"),
                    "wait_back": os.path.join(a, "wait_back", f"back{uid}.png")}
        b = os.path.join(root, "Sprites", "Standard")
        if os.path.exists(os.path.join(b, "BattleFront", f"front{uid}.png")):
            return {"front": os.path.join(b, "BattleFront", f"front{uid}.png"),
                    "back": os.path.join(b, "BattleBack", f"back{uid}.png"),
                    "wait_front": os.path.join(b, "WaitFront", f"front{uid}.png"),
                    "wait_back": os.path.join(b, "WaitBack", f"back{uid}.png")}
    from . import drpgscan
    for root in roots or ROOTS:                      # a folder in neither layout: searched all the way down
        got = drpgscan.unit_sheets(root, uid)
        if got:
            return got
    if not any(os.path.isdir(r) for r in roots or ROOTS):
        raise FileNotFoundError(f"the Disgaea RPG sprites are not in the kit (the release zip leaves them out): put "
                                f"them in {os.path.join(ROOTS[0], 'Characters', 'Sprites')} (front, back, wait_front, "
                                f"wait_back; see the guide, Tutorial 5)")
    raise FileNotFoundError(f"no DRPG sprites for unit {uid} in {roots or ROOTS}")


def unit_extras(uid, roots=None):
    """{'icon': face picture, 'cutin': cut-in portrait} paths that exist for unit `uid`"""
    out = {}
    for root in roots or ROOTS:
        for key, sub in (("icon", ("Characters", "Icons")), ("icon", ("Chara Icons",)),
                         ("cutin", ("Characters", "Cut-Ins")), ("cutin", ("Cutins",))):
            p = os.path.join(root, *sub, f"{uid}.png")
            if key not in out and os.path.exists(p):
                out[key] = p
    if len(out) < 2:
        from . import drpgscan
        for root in roots or ROOTS:
            for key, p in drpgscan.unit_extras(root, uid).items():
                out.setdefault(key, p)
    return out


def atlas_pieces(path):
    """Frames of a packed atlas: 8-connected pieces, small detached bits merged into the frame next to them.
    -> [dict(x, y, rgba)] (rgba trimmed, other frames' pixels cleared)"""
    a = np.asarray(Image.open(path).convert("RGBA")).copy()
    a[a[..., 3] <= ALPHA_NOISE] = 0          # compression noise (alpha 1-8 filling 8x8 blocks on some atlases)
    m = a[..., 3] > 0
    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    if not n:
        return []
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    objs = ndimage.find_objects(lab)
    # merge: a piece joins the biggest piece whose box (grown by MERGE_GAP) touches it, if that one is bigger
    parent = list(range(n + 1))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = [(o[1].start, o[0].start, o[1].stop, o[0].stop) for o in objs]
    order = sorted(range(n), key=lambda i: sizes[i])
    for i in order:
        x0, y0, x1, y1 = boxes[i]
        best = None
        for j in range(n):
            if j == i or sizes[j] <= sizes[i]:
                continue
            X0, Y0, X1, Y1 = boxes[j]
            if x0 <= X1 + MERGE_GAP and X0 - MERGE_GAP <= x1 and y0 <= Y1 + MERGE_GAP and Y0 - MERGE_GAP <= y1:
                # really close: some pixel of i within MERGE_GAP of piece j
                sub = lab[max(0, y0 - MERGE_GAP):y1 + MERGE_GAP, max(0, x0 - MERGE_GAP):x1 + MERGE_GAP]
                if (sub == j + 1).any() and (best is None or sizes[j] > sizes[best]):
                    grown = ndimage.binary_dilation(sub == i + 1, iterations=MERGE_GAP)
                    if (grown & (sub == j + 1)).any():
                        best = j
        if best is not None and sizes[i] < 0.35 * sizes[best]:
            parent[root(i + 1)] = root(best + 1)
    groups = {}
    for i in range(1, n + 1):
        groups.setdefault(root(i), []).append(i)
    out = []
    for g in groups.values():
        sel = np.isin(lab, g)
        ys, xs = np.nonzero(sel)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgba = a[y0:y1, x0:x1].copy()
        rgba[~sel[y0:y1, x0:x1]] = 0
        out.append(dict(x=int(x0), y=int(y0), rgba=rgba))
    return out


def load_reference(path=REF_PATH):
    with open(path, "rb") as f:
        return pickle.load(f)


WEIGHTS = (0.4, 0.35, 0.25)      # silhouette, skin, hair


def features(rgba):
    """(silhouette, skin, hair) masks: outfits change the outline, but face / arms / legs and the hair place the
    pose the same way for every outfit of a character"""
    import colorsys
    a = rgba[..., 3] > 40
    rgb = rgba[..., :3].astype(np.float32) / 255
    mx, mn = rgb.max(-1), rgb.min(-1)
    l = (mx + mn) / 2
    s = np.where(mx - mn > 1e-6, (mx - mn) / (1 - np.abs(2 * l - 1) + 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    h = (np.degrees(np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b)) + 360) % 360
    skin = a & ((h < 40) | (h > 345)) & (l > 0.62) & (s > 0.2) & (s < 0.95)
    hair = a & (h > 215) & (h < 275) & (s > 0.25) & (l > 0.2) & (l < 0.8)
    return [x.astype(np.float32) for x in (a, skin, hair)]


def _score(ref_feats, feats, radius=28):
    """(score, dy, dx): weighted overlap of the three masks at the best common placement"""
    from scipy.signal import fftconvolve
    o0, f0 = ref_feats[0], feats[0]
    total = None
    for w, o, f in zip(WEIGHTS, ref_feats, feats):
        if not o.any() or not f.any():
            continue
        inter = fftconvolve(o, f[::-1, ::-1], mode="full")
        iou = inter / np.maximum(1e-6, o.sum() + f.sum() - inter)
        total = w * iou if total is None else total + w * iou
    cy, cx = f0.shape[0] - 1, f0.shape[1] - 1
    # search near bottom-centres aligned
    ys, xs = np.nonzero(o0)
    yf, xf = np.nonzero(f0)
    ay = int(ys.max() - yf.max())
    ax = int(round(xs[ys >= ys.max() - 30].mean() - xf[yf >= yf.max() - 30].mean()))
    y0, y1 = max(0, cy + ay - radius), min(total.shape[0], cy + ay + radius + 1)
    x0, x1 = max(0, cx + ax - radius), min(total.shape[1], cx + ax + radius + 1)
    sub = total[y0:y1, x0:x1]
    if sub.size == 0:
        return 0.0, ay, ax
    k = np.unravel_index(int(sub.argmax()), sub.shape)
    return float(sub.max()), int(y0 + k[0] - cy), int(x0 + k[1] - cx)


def match_unit(uid, ref=None, roots=None, log=None, sheets=None):
    """-> ({(name, view): [(PIL image, (canvas_h, canvas_w, oy, ox))]}, report)
    canvas tuple: the cell canvas size and where its top-left lies inside the image; report['pos'][(name, view)]:
    the reference position of every frame.  sheets: only these atlases"""
    from scipy.optimize import linear_sum_assignment
    ref = ref or load_reference()
    seqs, report = {}, {"unit": uid, "sheets": {}}
    only = sheets
    sheets = unit_sheets(uid, roots)
    for key, path in sheets.items():
        if only and key not in only:
            continue
        pieces = atlas_pieces(path)
        refs = [r for r in ref if r["sheet"] == key]
        if not pieces or not refs:
            continue
        cost = np.full((len(refs), len(pieces)), 1.0)
        fit = {}
        pf = [features(p["rgba"]) for p in pieces]
        for i, r in enumerate(refs):
            rf = r["feats"]
            for j, p in enumerate(pieces):
                m = pf[j][0]
                # size sanity: very different drawings can't be the same pose
                hr, wr = rf[0].shape
                if not (0.45 < m.shape[0] / hr < 2.2 and 0.35 < m.shape[1] / wr < 2.8):
                    continue
                score, dy, dx = _score(rf, pf[j])
                fit[i, j] = (score, dy, dx)
                cost[i, j] = 1.0 - score
        ri, pj = linear_sum_assignment(cost)
        used = 0
        for i, j in zip(ri, pj):
            if (i, j) not in fit or fit[i, j][0] < MIN_IOU:
                continue
            r, p = refs[i], pieces[j]
            iou, dy, dx = fit[i, j]
            ch, cw = r["canvas"]
            oy, ox = r["offset"]
            # drawing top-left in canvas space, then an image big enough for canvas and drawing
            py, px = oy + dy, ox + dx
            h, w = p["rgba"].shape[:2]
            top, left = min(0, py), min(0, px)
            H, W = max(ch, py + h) - top, max(cw, px + w) - left
            img = np.zeros((H, W, 4), np.uint8)
            img[py - top:py - top + h, px - left:px - left + w] = p["rgba"]
            seqs.setdefault((r["name"], r["view"]), []).append(
                (r["pos"], Image.fromarray(img, "RGBA"), (ch, cw, -top, -left), round(iou, 3)))
            used += 1
        report["sheets"][key] = dict(pieces=len(pieces), refs=len(refs), matched=used)
    out = {}
    report["pos"] = {}
    for k, v in seqs.items():
        v.sort(key=lambda e: e[0])
        out[k] = [(img, canvas) for _, img, canvas, _ in v]
        report["pos"][k] = [e[0] for e in v]
    report["frames"] = sum(len(v) for v in out.values())
    if log:
        log(f"DRPG unit {uid}: " + ", ".join(f"{k} {v['matched']}/{v['refs']}" for k, v in report["sheets"].items()))
    return out, report


# ====================================================================== exact frames from the atlas slots
# The atlases are not trimmed: every frame sits in a fixed rectangle ("slot") at its canvas position.  The slots are
# the same for every humanoid unit (data/drpg_slots.json, from Girl Laharl's labelled frames:
# _research/drpg_make_slots.py), so a unit's frame = the pieces inside that slot, at their place in it: the right
# pose label and the exact placement, like a labelled frame dump.  Idle sheets laid out on another grid are placed
# by registering the frames on their unmoving lower body (pixel-exact).  A sheet packed differently falls back to
# match_unit.

SLOTS_PATH = os.path.join(os.path.dirname(__file__), "data", "drpg_slots.json")
# Second atlas layout ("B": the original characters 2-15 and some early units such as 96 Formal Killia): the same
# frames in the same slot order, placed on an 8 px grid elsewhere; hand / loose pieces carry their A -> B shift
# (_research/drpg_make_slots_b.py).  Slot index k means the same pose in both layouts.
SLOTS_B_PATH = os.path.join(os.path.dirname(__file__), "data", "drpg_slots_b.json")
SLOT_FIT = 0.9          # share of the big pieces that must lie inside their slot for the slots to apply
LOOSE_NEAR = 30         # a B piece this close (px) to a known loose place takes that place's A key


def load_slots(path=SLOTS_PATH):
    import json
    with open(path) as f:
        return json.load(f)


_LAYOUTS = None


def load_layouts():
    """[(name, slots)] in the order they are tried: the standard layout first"""
    global _LAYOUTS
    if _LAYOUTS is None:
        _LAYOUTS = [("A", load_slots())]
        if os.path.exists(SLOTS_B_PATH):
            _LAYOUTS.append(("B", load_slots(SLOTS_B_PATH)))
    return _LAYOUTS


def fit_layout(pieces, sheet):
    """-> (layout name, slots of `sheet`, {slot index: [pieces]}) of the first layout whose slots hold the sheet's
    frames, or (None, standard slots, None)"""
    for name, lay in load_layouts():
        sl = [s for s in lay.get(sheet, []) if s.get("x") is not None]
        if sl and pieces:
            owner = _slot_frames(pieces, sl)
            if owner is not None:
                full = lay[sheet]
                return name, full, {full.index(sl[k]): ps for k, ps in owner.items()}
    return None, load_layouts()[0][1].get(sheet, []), None


def loose_place(layout, sheet, cx, cy):
    """A loose piece centred at (cx, cy) of a layout-B atlas -> its (dx, dy) shift to standard-atlas coordinates,
    or (0, 0)"""
    if layout != "B":
        return 0, 0
    best = None
    for e in dict(load_layouts()).get("B", {}).get("loose", {}).get(sheet, []):
        d = abs(e["x"] - cx) + abs(e["y"] - cy)
        if d <= LOOSE_NEAR and (best is None or d < best[0]):
            best = (d, e["shift"])
    return (-best[1][0], -best[1][1]) if best else (0, 0)


def _tall(pieces):
    hmax = max(p["rgba"].shape[0] for p in pieces)
    return [p for p in pieces if p["rgba"].shape[0] > 0.6 * hmax]


def _slot_frames(pieces, slots):
    """-> {slot index: [pieces]} or None when the sheet is packed differently"""
    big = _tall(pieces)
    owner, inside = {}, 0
    for p in pieces:
        h, w = p["rgba"].shape[:2]
        cx, cy = p["x"] + w / 2, p["y"] + h / 2
        k = next((i for i, s in enumerate(slots)
                  if s["x"] <= cx < s["x"] + s["w"] and s["y"] <= cy < s["y"] + s["h"]), None)
        if k is None:
            continue
        s = slots[k]
        if p in big and s["x"] <= p["x"] and s["y"] <= p["y"] and p["x"] + w <= s["x"] + s["w"] \
                and p["y"] + h <= s["y"] + s["h"]:
            inside += 1
        owner.setdefault(k, []).append(p)
    if inside < SLOT_FIT * len(big):
        return None
    return owner


def _compose(pieces, ox, oy):
    """pieces -> (RGBA image, (top, left) of the image relative to the point (ox, oy) of the atlas)"""
    x0 = min(p["x"] for p in pieces)
    y0 = min(p["y"] for p in pieces)
    x1 = max(p["x"] + p["rgba"].shape[1] for p in pieces)
    y1 = max(p["y"] + p["rgba"].shape[0] for p in pieces)
    img = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    for p in pieces:
        h, w = p["rgba"].shape[:2]
        sub = img[p["y"] - y0:p["y"] - y0 + h, p["x"] - x0:p["x"] - x0 + w]
        m = p["rgba"][..., 3] > 0
        sub[m] = p["rgba"][m]
    return img, (y0 - oy, x0 - ox)


def _framed(img, top, left, ch, cw):
    """drawing whose top-left lies at (top, left) of a ch x cw canvas -> (PIL image, (ch, cw, oy, ox)) as
    match_unit gives them (canvas top-left at (oy, ox) of the image)"""
    h, w = img.shape[:2]
    T, L = min(0, top), min(0, left)
    H, W = max(ch, top + h) - T, max(cw, left + w) - L
    out = np.zeros((H, W, 4), np.uint8)
    out[top - T:top - T + h, left - L:left - L + w] = img
    return Image.fromarray(out, "RGBA"), (ch, cw, -T, -L)


def register(a, b, frac=0.4, R=12, center=(0, 0)):
    """(dy, dx): where b's top-left lies relative to a's when their lower bodies (the bottom `frac` of a)
    coincide pixel for pixel (searched within R px of `center`)"""
    ha, wa = a.shape[:2]
    hb, wb = b.shape[:2]
    ya0 = int(ha * (1 - frac))
    A = a[ya0:].astype(np.int16)
    aop = A[..., 3] > 0
    best = (-1e9, 0, 0)
    for dy in range(center[0] - R, center[0] + R + 1):
        ys = np.arange(ya0, ha) - dy
        ok = (ys >= 0) & (ys < hb)
        if not ok.any():
            continue
        for dx in range(center[1] - R, center[1] + R + 1):
            xs = np.arange(wa) - dx
            okx = (xs >= 0) & (xs < wb)
            sub = np.zeros_like(A)
            sub[np.ix_(ok, okx)] = b[np.ix_(ys[ok], xs[okx])]
            bop = sub[..., 3] > 0
            eq = aop & bop & (np.abs(A - sub).max(-1) <= 2)
            score = eq.sum() - 0.5 * (aop ^ bop).sum()
            if score > best[0]:
                best = (score, dy, dx)
    return best[1], best[2]


# Where a DRPG idle frame stands in its canvas: units whose wait sheets fit the slots put the first wait frame's
# feet at y 176 (p10-p90 172-176) and the centroid of its lowest quarter at x 85 (front) / 87 (back) (+-6 px with the
# stance; measured on 120 units).  Wait sheets on another grid (bigger frames, 1024 sheets, extra layer pieces) are
# anchored there.
WAIT_ANCHOR = {"wait_front": (85, 176), "wait_back": (87, 176)}


def _lower_centroid_x(a):
    m = a[..., 3] > ALPHA_NOISE
    ys, xs = np.nonzero(m)
    bottom, H = ys.max(), ys.max() - ys.min()
    return float(np.nonzero(m[int(bottom - 0.25 * H):bottom + 1])[1].mean()), int(bottom)


def _reading_order(ps):
    ps = sorted(ps, key=lambda p: p["y"])
    out, row, y_row = [], [], None
    for p in ps:
        if y_row is not None and p["y"] > y_row + p["rgba"].shape[0] // 2:
            out += sorted(row, key=lambda q: q["x"])
            row = []
        y_row = p["y"] if not row else y_row
        row.append(p)
    return out + sorted(row, key=lambda q: q["x"])


def wait_layers(pieces, bodies):
    """Layered idle sheets: some units draw their idle as a body plus separate pieces (long hair, a cape) on the
    same grid, the pieces in the right half of the sheet at the same place in their cell 512 px to the right of their
    body (Liezerota 163 / 261: short-haired bodies, the long hair behind them).
    -> {body index: [layer pieces]}: each right-half piece goes to the body it covers most once moved 512 px left;
    empty unless at least two bodies get one and none of them is a whole frame."""
    if not bodies:
        return {}
    hb = float(np.median([b["rgba"].shape[0] for b in bodies]))
    out = {}
    for lay in (p for p in pieces if p["x"] >= 512 and p["y"] < 512):
        lh, lw = lay["rgba"].shape[:2]
        lx = lay["x"] - 512
        best, area = None, 0
        for i, b in enumerate(bodies):
            bh, bw = b["rgba"].shape[:2]
            ox = max(0, min(b["x"] + bw, lx + lw) - max(b["x"], lx))
            oy = max(0, min(b["y"] + bh, lay["y"] + lh) - max(b["y"], lay["y"]))
            if ox * oy > area:
                best, area = i, ox * oy
        if best is None or area < 0.5 * lw * lh:
            continue
        if lh >= 0.9 * hb:
            return {}                                  # whole frames, not layers
        out.setdefault(best, []).append(lay)
    return out if len(out) >= min(2, len(bodies)) else {}


LAYER_MATCH = 40        # mean RGBA difference (64 x 64) below which two layer pieces are the same drawing


def _layer_pieces(path):
    pieces = atlas_pieces(path)
    bodies = [p for p in _tall(pieces) if p["x"] < 512 and p["y"] < 512]
    return [lay for ls in wait_layers(pieces, bodies).values() for lay in ls]


_facing = {}


def back_idle_faces_front(sheets):
    """True when a layered back idle sheet (body + separate long hair / cape) draws the unit facing the camera: its
    layer pieces are the front idle's (mirrored or not; Santa Liezerota 261, whose 'back' idle is her front one
    turned the other way).  Its layers then go behind the body, as on the front sheet; a real back view (Liezerota
    163: the back of a short-haired body, the long hair over it) keeps them over the body.  sheets: unit_sheets()"""
    key = (sheets.get("wait_back"), sheets.get("wait_front"))
    if key in _facing:
        return _facing[key]
    out = False
    try:
        back = _layer_pieces(key[0]) if key[0] else []
        front = _layer_pieces(key[1]) if key[1] else []
    except Exception:
        back = front = []
    if back and front:
        def norm(a):
            return np.asarray(Image.fromarray(np.ascontiguousarray(a)).resize((64, 64), Image.BILINEAR)).astype(float)

        def dist(a, b):
            m = (a[..., 3] > 64) | (b[..., 3] > 64)
            return float(np.abs(a - b)[m].mean()) if m.any() else 999.0
        F = [norm(lay["rgba"]) for lay in front]
        ds = [min(min(dist(a, f), dist(a[:, ::-1], f)) for f in F) for a in (norm(lay["rgba"]) for lay in back)]
        out = float(np.median(ds)) < LAYER_MATCH
    _facing[key] = out
    return out


def _with_layer(body, lays, behind):
    """body + its layer pieces (atlas coordinates, the layers 512 px to the right) -> (RGBA, body's (dx, dy) in it)"""
    bh, bw = body["rgba"].shape[:2]
    placed = [(lay["rgba"], lay["x"] - 512, lay["y"]) for lay in lays]
    x0 = min([body["x"]] + [x for _, x, _ in placed])
    y0 = min([body["y"]] + [y for _, _, y in placed])
    x1 = max([body["x"] + bw] + [x + img.shape[1] for img, x, _ in placed])
    y1 = max([body["y"] + bh] + [y + img.shape[0] for img, _, y in placed])
    canvas = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    parts = placed + [(body["rgba"], body["x"], body["y"])]
    for img, x, y in (parts if behind else parts[::-1]):
        canvas.alpha_composite(Image.fromarray(np.ascontiguousarray(img)), (x - x0, y - y0))
    return np.asarray(canvas), (body["x"] - x0, body["y"] - y0)


def wait_frames(pieces, sheet, n=5, size=None, behind=None):
    """the idle frames of a wait sheet laid out on another grid -> {slot index: (img, (left, top) in slot coords)}:
    the first n tall frames of the first 512 block in reading order; the first stands at WAIT_ANCHOR, the others are
    registered on it by their unmoving lower body.  size: the atlas (w, h); frames running off its edge are cut off
    in the source and left out (the idle holds the drawing before).  behind: a layered sheet's long hair / cape goes
    behind the body (default: on the front sheet; see back_idle_faces_front)"""
    tall = _tall(pieces)
    if not tall:
        return {}
    ordered = []
    for blk in sorted({(p["y"] // 512, p["x"] // 512) for p in tall})[:1]:
        inb = sorted((p for p in tall if (p["y"] // 512, p["x"] // 512) == blk), key=lambda p: p["y"])
        row, y_row = [], None
        for p in inb:
            if y_row is not None and p["y"] > y_row + p["rgba"].shape[0] // 2:
                ordered += sorted(row, key=lambda q: q["x"])
                row = []
            y_row = p["y"] if not row else y_row
            row.append(p)
        ordered += sorted(row, key=lambda q: q["x"])
    frames = ordered[:n]
    layers = wait_layers(pieces, frames)
    first = frames[0]["rgba"]
    cx, bottom = _lower_centroid_x(first)
    ax, ay = WAIT_ANCHOR.get(sheet, (85, 176))
    left0, top0 = int(round(ax - cx)), ay - bottom
    out = {}
    for i, p in enumerate(frames):
        h, w = p["rgba"].shape[:2]
        if size and (p["x"] + w >= size[0] or p["y"] + h >= size[1]) and i:
            continue
        if i:
            # frames differ in extent (flames, capes): start from the lower bodies' centroid / feet, then pixels
            cxi, bi = _lower_centroid_x(p["rgba"])
            dy, dx = register(first, p["rgba"], frac=0.15, R=8, center=(bottom - bi, int(round(cx - cxi))))
        else:
            dy, dx = 0, 0
        if i in layers:          # the body's own long hair / cape: behind it seen from the front, over it from behind
            img, (bx, by) = _with_layer(p, layers[i], behind=(sheet != "wait_back") if behind is None else behind)
            out[i] = (img, (left0 + dx - bx, top0 + dy - by))
        else:
            out[i] = (p["rgba"], (left0 + dx, top0 + dy))
    return out


def matched_frames(uid, sheet, roots=None):
    """frames of a battle sheet packed like no known layout, labelled by silhouette (match_unit) -> {slot index:
    (img, (left, top) in slot coords)} for the standard slots of the same pose"""
    m, rep = match_unit(uid, roots=roots, sheets=(sheet,))
    sl = load_slots().get(sheet, [])
    index = {(s["name"], s["view"], s["pos"]): k for k, s in enumerate(sl)}
    out = {}
    for (name, view), frames in m.items():
        for pos, (img, (ch, cw, oy, ox)) in zip(rep["pos"][(name, view)], frames):
            k = index.get((name, view, pos))
            if k is not None:
                out[k] = (np.asarray(img), (-ox, -oy))
    return out


def slot_unit(uid, roots=None, log=None, slots=None):
    """-> ({(name, view): [(PIL image, (ch, cw, oy, ox))]}, report) like match_unit, from the slots; sheets the
    slots don't fit are matched by match_unit"""
    slots = slots or load_layouts()[0][1]
    sheets = unit_sheets(uid, roots)
    seqs, report, fallback = {}, {"unit": uid, "sheets": {}}, []
    for key, path in sheets.items():
        sl = slots.get(key, [])
        pieces = atlas_pieces(path)
        if not pieces or not sl:
            continue
        owner = _slot_frames(pieces, sl)
        if owner is None and slots is load_layouts()[0][1]:
            name, full, own = fit_layout(pieces, key)       # the second layout (same slot order)
            if own is not None:
                sl, owner = full, own
        if owner is not None:
            for k, ps in owner.items():
                s = sl[k]
                img, (top, left) = _compose(ps, s["x"], s["y"])
                seqs.setdefault((s["name"], s["view"]), []).append((s["pos"], *_framed(img, top, left, s["h"], s["w"])))
            report["sheets"][key] = dict(how="slots", frames=len(owner), slots=len(sl))
            continue
        if key.startswith("wait"):
            # another grid: the first frames in reading order, placed by their lower body on the first one
            # several 512 x 512 blocks (a second idle set / an upper-body layer beside or below the first):
            # the first block's frames, in reading order
            tall = _tall(pieces)
            ordered = []
            for blk in sorted({(p["y"] // 512, p["x"] // 512) for p in tall}):
                inb = sorted((p for p in tall if (p["y"] // 512, p["x"] // 512) == blk), key=lambda p: p["y"])
                row, y_row = [], None
                for p in inb:
                    if y_row is not None and p["y"] > y_row + p["rgba"].shape[0] // 2:
                        ordered += sorted(row, key=lambda q: q["x"])
                        row = []
                    y_row = p["y"] if not row else y_row
                    row.append(p)
                ordered += sorted(row, key=lambda q: q["x"])
            frames = ordered[:len(sl)]
            s0 = sl[0]
            first = frames[0]
            for i, p in enumerate(frames):
                dy, dx = (0, 0) if i == 0 else register(first["rgba"], p["rgba"], frac=0.15)
                top, left = first["y"] + dy, first["x"] + dx      # grid cell 0 starts at the atlas corner
                s = sl[i]
                seqs.setdefault((s["name"], s["view"]), []).append(
                    (s["pos"], *_framed(p["rgba"], top, left, s0["h"], s0["w"])))
            report["sheets"][key] = dict(how="registered", frames=len(frames), slots=len(sl))
            continue
        fallback.append(key)
    if fallback:
        m, rep = match_unit(uid, roots=roots)
        for (name, view), frames in m.items():
            ref_sheet = {r["sheet"] for r in load_reference() if r["name"] == name and r["view"] == view}
            if ref_sheet & set(fallback):
                seqs[(name, view)] = [(i, img, c) for i, (img, c) in enumerate(frames)]
        for key in fallback:
            report["sheets"][key] = dict(how="matched (packed differently)", **rep["sheets"].get(key, {}))
    out = {}
    for k, v in seqs.items():
        v.sort(key=lambda e: e[0])
        out[k] = [(img, canvas) for _, img, canvas in v]
    report["frames"] = sum(len(v) for v in out.values())
    if log:
        log(f"DRPG unit {uid}: " + ", ".join(f"{k} {v['how']}" for k, v in report["sheets"].items()))
    return out, report
