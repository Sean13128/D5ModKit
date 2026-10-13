"""Exact pose map between the game's humanoid sprites and Disgaea RPG unit atlases.

The vanilla generic classes of Disgaea 5 and their Disgaea RPG twins (Warrior = DRPG 10001, Valkyrie = 10002 ...)
use the same drawings, pixel for pixel and at the same size; DRPG packs them in fixed slots that every humanoid unit
shares (the same pose sits in the same slot), some of them mirrored.  Locating every cell of the vanilla sprite in
its twin's slots therefore tells, for every cell the game's animations use:

    which slot (sheet + slot index, or a loose piece such as a hand overlay), mirrored or turned, and where the
    cell lies in that slot (slot coordinates)

That is the same for every DRPG humanoid unit, so a new unit's drawings go exactly where the vanilla drawings were:
the same pose at the same place in every animation frame, hands over weapon grips as in the game.

    learn(twins)          -> the map (data/drpg_cellmap.json), consensus over all twins
    unit_frames(uid, ...) -> the new unit's image for every mapped cell + its placement in the cell

The template class's OWN animations (idle 6001 / 6007, specials 7xxx) are mapped the same way on the template's own
twin (data/drpg_ownmap_<class>.json).  They are that class's poses, so build() treats its idle loops specially:
    * the loop plays the unit's own DRPG wait drawings in the vanilla order; in-between drawings DRPG lacks are held
      (settle_idle_loops) - never a flip between near-duplicates
    * the template's separate idle hand / arm pieces are not drawn (strip_idle_overlays, drawable_own_map): they
      were placed for the template's hands and float on a new unit
    * the weapon goes into the unit's own hand: per-unit hand points (data/drpg_hands.json) carry the stand pose's
      weapon rig.  Without data the idle weapon is hidden rather than left floating, and automatic hand detection
      prints suggested hand points to check and store (build(auto_hands=True) applies them instead); a grip whose
      drawing is the template's own (its twin) is kept (place_idle_weapons)
"""
import dataclasses
import json
import math
import os

import numpy as np
from PIL import Image

from . import anm, drpg, sprites

MAP_PATH = os.path.join(os.path.dirname(__file__), "data", "drpg_cellmap.json")
HANDS_PATH = os.path.join(os.path.dirname(__file__), "data", "drpg_hands.json")
EXACT_COVER = 0.97      # share of the cell's pixels the slot drawing has at the placement
EXACT_ERR = 16          # mean colour difference (0-255) of an exact match
LOOSE = "loose"         # pieces outside every slot (hand overlays, arms)
NEAR_EXACT = 8          # colour error of a real idle-frame match is 1.5-7.4; a near-duplicate frame gives 9-16
HOLD_RATIO = 1.5        # ... or more than 1.5 x the loop's typical error (templates whose twin matches less closely)
# weapon attachment points: A = the hand weapons (weapon type + 10: 11 sword, 12 spear, 13 bow, 14, 15 axe, 16 staff),
# B = the same weapons carried the other way (on the back in the shared motions, the other hand in some idles)
GRIP_GROUPS = {"A": (11, 12, 13, 14, 15, 16, 17), "B": (111, 112, 113, 114, 115, 116, 117)}
WEAPON_NODES = (11, 12, 13, 15, 16)     # the right hand's grip in the stand pose
ATTACH_SHOW, ATTACH_HIDE = 0x100, 0x200  # attachment key flags, high byte: 1 = show, 2 = hide the attached weapon
HAND_AREA = (12, 450)   # skin blob size of a bare hand (px)
TEMPLATE_HAND_R = 16    # the template's gripping hand lies this close to its attachment point
MAX_GRIP_DIST = 120     # |dx| + 3|dy| from the template's hand to the unit's matching hand
HEAD_GRIP_DIST = 24     # ... when the template's hand is raised into the head zone
GRIP_NOISE = 7          # automatic grip moves up to this many px are detection noise (twin on its template: <= 6.8)
GRIP_BOUNDS = (-128, -200, 128, 40)     # render box of the hand detection (root coordinates)
GRIP_WINDOW = 12        # half size of the window compared around a grip point (px)
BREATH = [0, 1, 3, 3, 1]  # an idle made from a battle drawing (drpg.WRONG_VIEW): upper body settling, px per frame

# vanilla humanoid classes and their Disgaea RPG twins
# (Warrior 10001 and Magician 10005 are packed / coloured differently from the other units: not used)
TWINS = [(1020, 10002), (1050, 10003), (1060, 10004), (1040, 10009), (1070, 10013),
         (1080, 10014), (1110, 10015), (1090, 10016), (1100, 10017), (1120, 10018), (1130, 10019), (1140, 10020),
         (1150, 10021), (1180, 10023), (1190, 10025), (1200, 10026), (1220, 10027), (1250, 10028)]
TWIN_OF = dict(TWINS)


# ------------------------------------------------------------------------------------------ regions of a unit
def regions(uid, roots=None, pieces_only=False):
    """{(sheet, kind, index): dict(img=RGBA, org=(left, top) in region coordinates, size=(w, h))}
    kind 'slot': drpg slot index (region coordinates = slot coordinates); 'loose': pieces outside every slot,
    numbered by their position in the atlas (region coordinates = atlas coordinates of the piece's own box).
    pieces_only: no slot layouts at all, every piece is a loose region (monster atlases)"""
    out = {}
    sheets = drpg.unit_sheets(uid, roots)
    for sheet, path in sheets.items():
        pieces = drpg.atlas_pieces(path)
        # the atlas layout whose slots hold this sheet (standard or the second one, same slot order); a sheet no
        # layout fits is cut by the standard slots as before
        layout, sl, _ = (None, [], None) if pieces_only else drpg.fit_layout(pieces, sheet)
        if layout is None and pieces and sl:            # (no slot tables at all: monster atlases, every piece loose)
            # no known layout: idle frames anchored like the standard ones (drpg.wait_frames); a battle sheet packed
            # some other way is labelled by silhouette (drpg.matched_frames; its loose hand pieces are not used)
            behind = None if sheet != "wait_back" else drpg.back_idle_faces_front(sheets)
            fr = drpg.wait_frames(pieces, sheet, size=Image.open(path).size, behind=behind) if sheet.startswith("wait")                 else drpg.matched_frames(uid, sheet, roots)
            for k, (img, (left, top)) in fr.items():
                if k < len(sl):
                    out[(sheet, "slot", k)] = dict(img=img, org=(left, top), size=(sl[k]["w"], sl[k]["h"]))
            continue
        owner = {}
        loose = []
        for p in pieces:
            h, w = p["rgba"].shape[:2]
            cx, cy = p["x"] + w / 2, p["y"] + h / 2
            k = next((i for i, s in enumerate(sl) if s.get("x") is not None
                      and s["x"] <= cx < s["x"] + s["w"] and s["y"] <= cy < s["y"] + s["h"]), None)
            if k is None:
                loose.append(p)
            else:
                owner.setdefault(k, []).append(p)
        for k, ps in owner.items():
            s = sl[k]
            img, (top, left) = drpg._compose(ps, s["x"], s["y"])
            out[(sheet, "slot", k)] = dict(img=img, org=(left, top), size=(s["w"], s["h"]))
        for p in loose:
            h, w = p["rgba"].shape[:2]
            # loose pieces are named by their place (same place in every unit); their coordinates are the standard
            # atlas's (a second-layout piece is moved to its standard place)
            dx, dy = drpg.loose_place(layout, sheet, p["x"] + w / 2, p["y"] + h / 2)
            x, y = p["x"] + dx, p["y"] + dy
            out[(sheet, LOOSE, (x + w // 2) // 8 * 1000 + (y + h // 2) // 8)] = \
                dict(img=p["rgba"], org=(x, y), size=(w, h), at=(x, y))
    # an idle sheet of the wrong view (drpg.WRONG_VIEW): the idle is the battle sheet's stance drawing of that view
    # (drpg.WRONG_VIEW_POSE, else the stand), placed where idle drawings stand, breathing: the upper body settles and
    # rises over the loop (BREATH px; the other view's idle when its top moves more), the legs stay where they are
    for wait, battle, other in (("wait_front", "front", "wait_back"), ("wait_back", "back", "wait_front")):
        if wait not in drpg.WRONG_VIEW.get(int(uid), ()):
            continue
        pose = drpg.WRONG_VIEW_POSE.get(int(uid), {}).get(wait, ("stand", 0))
        sl_b = drpg.load_slots().get(battle, [])
        k0 = next((i for i, x in enumerate(sl_b) if (x["name"], x["pos"]) == pose), 0)
        st = out.get((battle, "slot", k0)) or out.get((battle, "slot", 0))
        if st is None:
            continue
        cx, bottom = drpg._lower_centroid_x(st["img"])
        ax, ay = drpg.WAIT_ANCHOR[wait]
        n = len(drpg.load_slots().get(wait, []))
        tops = []
        for k in range(n):
            r = out.get((other, "slot", k))
            ys = np.nonzero(r["img"][..., 3] > drpg.ALPHA_NOISE)[0] if r is not None else []
            tops.append(r["org"][1] + int(ys.min()) if len(ys) else None)
        bob = [t - tops[0] for t in tops] if None not in tops else []
        if not bob or max(bob) - min(bob) < 2:
            bob = BREATH[:n] + [0] * (n - len(BREATH))
        a = st["img"]
        ys = np.nonzero(a[..., 3] > drpg.ALPHA_NOISE)[0]
        hip = int(ys.min() + 0.55 * (bottom - ys.min()))        # rows above this breathe, the legs don't
        for k, sl_k in enumerate(drpg.load_slots().get(wait, [])):
            d = max(-6, min(6, int(bob[k])))
            img = a
            if d:
                up = Image.fromarray(np.ascontiguousarray(a[:hip]))
                up = np.asarray(up.resize((up.width, max(1, hip - d)), Image.LANCZOS))
                img = np.zeros_like(a)
                if d > 0:
                    img[d:hip] = up
                else:
                    img = np.concatenate([np.zeros((-d, a.shape[1], 4), a.dtype), img])
                    img[:hip - d] = up
                img[hip - min(d, 0):] = a[hip:]
            out[(wait, "slot", k)] = dict(img=img, org=(int(round(ax - cx)), ay - bottom + min(d, 0)),
                                          size=(sl_k["w"], sl_k["h"]))
    return out


def _loose_near(regs, sheet, key, radius=6):
    """the loose piece of `regs` nearest to the loose piece `key` (grid units of 8 px)"""
    kx, ky = key // 1000, key % 1000
    best = None
    for (s, kind, k), r in regs.items():
        if s != sheet or kind != LOOSE:
            continue
        d = abs(k // 1000 - kx) + abs(k % 1000 - ky)
        if d <= radius and (best is None or d < best[0]):
            best = (d, (s, kind, k))
    return best[1] if best else None


# ------------------------------------------------------------------------------------------ cells
def cells_of(fs, cls, motion=None):
    """trimmed images of the cells the class sprite fills: [(signed cell id, img, (tx, ty) trim, (w, h) rect)]
    (+ = shared motion set block 1, - = the class's own block)"""
    a = anm.parse(fs.read(sprites.sprite_vpath(fs, cls, "EN")))
    tex = [np.asarray(anm.texture_to_image(a, i, 0)) for i in range(len(a.textures))]
    motion = motion or sprites.motion_block(fs, 1)
    out = []
    for sign, blk in ((1, motion), (-1, a.blocks[0])):
        for ci, c in enumerate(blk.cells):
            if not ci or not c.w or not c.h or c.tex >= len(tex):
                continue
            img = tex[c.tex][c.y:c.y + c.h, c.x:c.x + c.w]
            m = img[..., 3] > 0
            if m.sum() < 20:
                continue
            ys, xs = np.nonzero(m)
            out.append((sign * ci, img[ys.min():ys.max() + 1, xs.min():xs.max() + 1],
                        (int(xs.min()), int(ys.min())), (c.w, c.h)))
    return out


def _variants(img):
    """(mirror, quarter turns) -> the cell drawing as it would appear in the atlas"""
    for mir in (0, 1):
        b = img[:, ::-1] if mir else img
        for k in range(4):
            yield mir, k, np.ascontiguousarray(np.rot90(b, k))


def _locate(cell, region):
    """best placement of `cell` inside `region` -> (cover, err, x, y, iou)"""
    from scipy.signal import fftconvolve
    cm = (cell[..., 3] > 0).astype(np.float32)
    rm = (region[..., 3] > 0).astype(np.float32)
    h, w = cm.shape
    H, W = rm.shape
    cor = fftconvolve(rm, cm[::-1, ::-1], mode="full")          # cor[y + h - 1, x + w - 1] = overlap at (x, y)
    tot = cm.sum()
    iy, ix = np.unravel_index(np.argmax(cor), cor.shape)
    best_ov = cor[iy, ix]
    iou = best_ov / (tot + rm.sum() - best_ov + 1e-6)
    if best_ov < tot * EXACT_COVER:
        return float(best_ov / tot), 1e9, int(ix - w + 1), int(iy - h + 1), float(iou)
    cand = np.argwhere(cor >= tot * EXACT_COVER)
    sel = cm > 0
    src = cell[..., :3].astype(np.int32)[sel]
    best = (1e9, 0, 0)
    for cy, cx in cand[:200]:
        y, x = cy - h + 1, cx - w + 1
        win = np.zeros_like(cell)
        ys0, xs0 = max(0, y), max(0, x)
        ys1, xs1 = min(H, y + h), min(W, x + w)
        win[ys0 - y:ys1 - y, xs0 - x:xs1 - x] = region[ys0:ys1, xs0:xs1]
        err = np.abs(win[..., :3].astype(np.int32)[sel] - src).mean()
        if err < best[0]:
            best = (err, int(x), int(y))
    return 1.0, float(best[0]), best[1], best[2], float(iou)


class _Bank:
    """all regions of a unit, mask spectra stacked for one-shot correlation"""

    def __init__(self, regs, n=None):
        self.keys = list(regs)
        self.regs = regs
        big = max((max(r["img"].shape[:2]) for r in regs.values()), default=0)
        n = n or max(448, -(-2 * big // 32) * 32)            # room for a cell anywhere on the biggest region
        self.n = n
        stack = np.zeros((len(self.keys), n, n), np.float32)
        for i, k in enumerate(self.keys):
            m = regs[k]["img"][..., 3] > 0
            stack[i, :m.shape[0], :m.shape[1]] = m
        self.area = stack.reshape(len(self.keys), -1).sum(1)
        self.F = np.fft.rfft2(stack)

    def correlate(self, cell):
        """-> (R, n, n) overlap maps: cor[r, y + h - 1, x + w - 1] = overlap of the cell placed at (x, y)"""
        m = (cell[..., 3] > 0).astype(np.float32)
        pad = np.zeros((self.n, self.n), np.float32)
        pad[:m.shape[0], :m.shape[1]] = m[::-1, ::-1]
        return np.fft.irfft2(self.F * np.fft.rfft2(pad)[None], s=(self.n, self.n)), m


def _colour_err(cell, region, x, y):
    h, w = cell.shape[:2]
    H, W = region.shape[:2]
    win = np.zeros_like(cell)
    ys0, xs0 = max(0, y), max(0, x)
    ys1, xs1 = min(H, y + h), min(W, x + w)
    if ys1 <= ys0 or xs1 <= xs0:
        return 1e9
    win[ys0 - y:ys1 - y, xs0 - x:xs1 - x] = region[ys0:ys1, xs0:xs1]
    sel = cell[..., 3] > 0
    return float(np.abs(win[..., :3].astype(np.int32)[sel] - cell[..., :3].astype(np.int32)[sel]).mean())


def locate_twin(fs, cls, uid, log=print, motion=None):
    """{signed cell: dict(exact=[...], approx=best)} with placements in region coordinates"""
    regs = regions(uid)
    bank = _Bank(regs)
    res = {}
    for cid, img, trim, rect in cells_of(fs, cls, motion):
        exact, approx = [], None
        for mir, k, im in _variants(img):
            if k and exact:
                break
            h, w = im.shape[:2]
            if h >= bank.n or w >= bank.n:
                continue
            cor, m = bank.correlate(im)
            tot = m.sum()
            for ri in range(len(bank.keys)):
                c = cor[ri]
                iy, ix = np.unravel_index(np.argmax(c), c.shape)
                ov = c[iy, ix]
                key = bank.keys[ri]
                reg = regs[key]
                iou = ov / (tot + bank.area[ri] - ov + 1e-6)
                pl = dict(region=list(key), mirror=mir, k=k, x=int(ix - w + 1 + reg["org"][0]),
                          y=int(iy - h + 1 + reg["org"][1]), w=int(w), h=int(h), iou=round(float(iou), 3),
                          part=round(float(tot / max(1.0, bank.area[ri])), 3))
                if ov >= tot * EXACT_COVER:
                    best = None
                    for cy, cx in np.argwhere(c >= tot * EXACT_COVER)[:60]:
                        x, y = int(cx - w + 1), int(cy - h + 1)
                        e = _colour_err(im, reg["img"], x, y)
                        if best is None or e < best[0]:
                            best = (e, x, y)
                    if best[0] <= EXACT_ERR:
                        exact.append(dict(pl, x=best[1] + reg["org"][0], y=best[2] + reg["org"][1],
                                          err=round(best[0], 1)))
                if approx is None or iou > approx[0]:
                    approx = (float(iou), pl)
        res[cid] = dict(trim=trim, rect=rect, exact=exact, approx=approx[1] if approx else None)
        if log:
            log(f"  cell {cid}: {len(exact)} exact" + ("" if exact else f", best iou {approx[1]['iou'] if approx else 0}"))
    return res


# ------------------------------------------------------------------------------------------ consensus
def _key(pl):
    reg = pl["region"]
    if reg[1] == LOOSE:      # loose pieces: by place, a little tolerance
        reg = [reg[0], LOOSE, reg[2] // 1000 // 2 * 1000 + reg[2] % 1000 // 2]
    return (tuple(reg), pl["mirror"], pl["k"])


def _transform(a, mirror, k):
    """cell orientation -> atlas orientation"""
    if mirror:
        a = a[:, ::-1]
    return np.rot90(a, k)


def _untransform(a, mirror, k):
    """atlas orientation -> cell orientation"""
    a = np.rot90(a, -k)
    if mirror:
        a = a[:, ::-1]
    return np.ascontiguousarray(a)


def _rect_box(pl, trim, rect):
    """top-left (x, y) in region coordinates of the cell rect transformed like the drawing"""
    W, H = rect
    tw, th = (pl["h"], pl["w"]) if pl["k"] % 2 else (pl["w"], pl["h"])
    m = np.zeros((H, W), bool)
    m[trim[1]:trim[1] + th, trim[0]:trim[0] + tw] = True
    t = _transform(m, pl["mirror"], pl["k"])
    ys, xs = np.nonzero(t)
    return pl["x"] - int(xs.min()), pl["y"] - int(ys.min())


def consensus(per_twin):
    """per_twin: {twin: locate_twin result} -> {signed cell: placement}"""
    cells = sorted({c for r in per_twin.values() for c in r})
    out = {}
    for c in cells:
        votes, places = {}, {}
        for twin, r in per_twin.items():
            e = r.get(c)
            if not e:
                continue
            seen = set()
            for pl in e["exact"]:
                k = _key(pl)
                if k in seen:
                    continue
                seen.add(k)
                votes[k] = votes.get(k, 0) + 2
                places.setdefault(k, []).append((pl, e["trim"], e["rect"], True))
            if not e["exact"] and e["approx"]:
                k = _key(e["approx"])
                votes[k] = votes.get(k, 0) + e["approx"]["iou"]
                places.setdefault(k, []).append((e["approx"], e["trim"], e["rect"], False))
        if not votes:
            continue

        def err(k):
            es = [p[0]["err"] for p in places[k] if p[3] and "err" in p[0]]
            return float(np.median(es)) if es else None

        # Idle frames differ by a few pixels, so one vanilla idle cell is often 'exact' in 2-5 wait slots (the real
        # match at colour error 2-7, near-duplicates at 9-16), and an own map has a single twin: every candidate has
        # the same votes.  Equal votes -> the lowest colour error, never the first one found (that collapsed the
        # idles to 1-2 drawings).
        top = max(votes.values())
        k = min((k for k in votes if votes[k] >= top - 1e-9), key=lambda k: (err(k) is None, err(k) or 0.0))
        ps = places[k]
        ex = [p for p in ps if p[3]] or ps
        # where the (mirrored / turned) cell rect lies in region coordinates: median over the twins
        boxes = [_rect_box(p[0], p[1], p[2]) for p in ex]
        ox = int(np.median([b[0] for b in boxes]))
        oy = int(np.median([b[1] for b in boxes]))
        pl = ex[0][0]
        e = err(k)
        out[c] = dict(region=list(pl["region"]), mirror=pl["mirror"], k=pl["k"], ox=ox, oy=oy, rect=list(ex[0][2]),
                      part=float(np.median([p[0]["part"] for p in ex])), votes=round(float(votes[k]), 2),
                      exact=sum(1 for p in ps if p[3]), twins=len(ps), err=None if e is None else round(e, 1))
    return out


def agreement(m, res):
    """share of a twin's exactly located cells whose placement the map `m` repeats"""
    ok = n = 0
    for c, e in res.items():
        if c not in m or not e["exact"]:
            continue
        n += 1
        pl = m[c]
        for x in e["exact"]:
            if _key(x) == _key(pl):
                bx, by = _rect_box(x, e["trim"], e["rect"])
                if abs(bx - pl["ox"]) <= 2 and abs(by - pl["oy"]) <= 2:
                    ok += 1
                    break
    return ok / max(1, n)


def robust_consensus(per_twin, min_agree=0.75, log=print):
    """consensus without the twins that disagree with the others (packed differently)"""
    keep = dict(per_twin)
    for _ in range(3):
        m = consensus(keep)
        scores = {t: agreement(consensus({u: r for u, r in keep.items() if u != t}), r) for t, r in keep.items()}
        bad = [t for t, s in scores.items() if s < min_agree]
        if log:
            log("twin agreement: " + ", ".join(f"{t} {s:.2f}" for t, s in sorted(scores.items())))
        if not bad:
            return m
        for t in bad:
            keep.pop(t)
    return consensus(keep)


def save_map(m, path=MAP_PATH):
    with open(path, "w") as f:
        json.dump({str(k): v for k, v in m.items()}, f, indent=0)


def load_map(path=MAP_PATH):
    with open(path) as f:
        return {int(k): v for k, v in json.load(f).items()}


# ------------------------------------------------------------------------------------------ apply
def cell_image(regs, pl, margin=6):
    """the unit's drawing for one mapped cell -> (RGBA image, (dx, dy) = its top-left in the cell's rect) or None.
    Whole region for a whole-drawing cell (never clipped); the cell's box (+ margin) for a cell that is a part of a
    bigger drawing."""
    key = tuple(pl["region"])
    if key[1] == LOOSE:
        key = _loose_near(regs, key[0], key[2])
        if key is None:
            return None
    r = regs.get(key)
    if r is None and key[1] == "slot":
        # a frame this unit lacks: the nearest frame of the same move (same slot name) stands in
        sl = drpg.load_slots().get(key[0], [])
        if key[2] < len(sl):
            name, pos = sl[key[2]]["name"], sl[key[2]]["pos"]
            alts = sorted((abs(s["pos"] - pos), k) for k, s in enumerate(sl)
                          if s["name"] == name and k != key[2] and (key[0], "slot", k) in regs)
            if alts:
                r = regs[(key[0], "slot", alts[0][1])]
    if r is None:
        return None
    img = r["img"]
    L, T = r["org"]
    w, h = pl["rect"]
    if not w or not h:              # an empty placeholder cell
        return None
    mir, k = pl["mirror"], pl["k"]
    # the transformed cell rect in region coordinates
    WT, HT = (h, w) if k % 2 else (w, h)
    X0, Y0 = pl["ox"], pl["oy"]
    Hr, Wr = img.shape[:2]
    ux0, uy0 = min(L, X0), min(T, Y0)
    ux1, uy1 = max(L + Wr, X0 + WT), max(T + Hr, Y0 + HT)
    canvas = np.zeros((uy1 - uy0, ux1 - ux0, 4), np.uint8)
    canvas[T - uy0:T - uy0 + Hr, L - ux0:L - ux0 + Wr] = img
    box = np.zeros(canvas.shape[:2], bool)
    box[Y0 - uy0:Y0 - uy0 + HT, X0 - ux0:X0 - ux0 + WT] = True
    canvas = _untransform(canvas, mir, k)
    box = _untransform(box, mir, k)
    ys, xs = np.nonzero(box)
    bx, by = int(xs.min()), int(ys.min())                 # the cell rect's top-left in the canvas
    if pl["part"] < 0.8 and key[1] != LOOSE:
        # a part of a bigger drawing (e.g. an arm drawn over the weapon): only the cell's box
        Hc, Wc = canvas.shape[:2]
        canvas = canvas.copy()
        keep = np.zeros((Hc, Wc), bool)
        keep[max(0, by - margin):by + h + margin, max(0, bx - margin):bx + w + margin] = True
        canvas[~keep] = 0
    a = canvas[..., 3] > 0
    if a.sum() < 10:
        return None
    ys, xs = np.nonzero(a)
    y0, x0 = int(ys.min()), int(xs.min())
    img = canvas[y0:ys.max() + 1, x0:xs.max() + 1]
    dx, dy = x0 - bx, y0 - by
    if (img[..., 3] > 0).sum() < 10:
        return None
    return np.ascontiguousarray(img), (int(dx), int(dy))


def own_map_path(cls):
    return os.path.join(os.path.dirname(__file__), "data", f"drpg_ownmap_{int(cls)}.json")


# ------------------------------------------------------------------------------------------ own animations: idle
# The template class's OWN animations are that class's poses, not shared ones.  Its idle loops (6001 / 6007) map onto
# the DRPG wait sheets (5 frames, every one a complete drawing of the unit); everything else in them (the template's
# separate idle hand / arm pieces, its weapon grips) belongs to the TEMPLATE's drawing and is wrong for a new unit.

def _wait_sheet(pl):
    return pl["region"][0] if pl is not None and pl["region"][1] == "slot" and pl["region"][0].startswith("wait") \
        else None


def _node_key_range(b, ni):
    n = b.nodes[ni]
    return range(n.first_key, n.first_key + n.num_keys) if n.first_key >= 0 and n.num_keys else range(0)


def _err_limit(errs):
    """the colour error above which a wait-sheet placement is a near-duplicate, not the drawing itself: real matches
    of an idle sit at 1.5-7.4 and cluster tightly per template; the in-between DRPG lacks gives 9-16 (or no exact
    match at all)"""
    errs = [e for e in errs if e is not None]
    return max(NEAR_EXACT, HOLD_RATIO * float(np.median(errs))) if errs else NEAR_EXACT


def idle_loops(b, own_ids, own_map):
    """The own animations that ARE the DRPG wait loop: looping animations whose body layer (the node drawing the most
    of a wait-sheet slot) shows a near-exact wait-sheet placement on at least half of its keys.  Special poses that
    only approximate a pose with some wait drawing (no loop, or approximate placements) are not idle loops.
    -> {anim id: dict(node=body layer node, sheet='wait_front'|'wait_back', keys=[key indices by time],
                       end=loop end, limit=error limit, layers=[every other node with keys])}"""
    out = {}
    for an in b.animations:
        if an.id not in own_ids:
            continue
        info = anm.animation_info(b, an)
        if not info["loop"]:
            continue
        layers, others = [], []
        for ni, d, p in b.walk(an.root):
            ks = [i for i in _node_key_range(b, ni) if b.keys[i].cell]
            if not ks:
                continue
            others.append(ni)
            sheets = [_wait_sheet(own_map.get(b.keys[i].cell)) for i in ks]
            named = [s for s in sheets if s]
            if 2 * len(named) <= len(ks):
                continue
            sheet = max(set(named), key=named.count)
            part = float(np.median([own_map[b.keys[i].cell]["part"] for i, s in zip(ks, sheets) if s == sheet]))
            layers.append((part, len(ks), ni, sheet))
        # the body layer: the biggest layer whose keys mostly ARE wait drawings (a unique character's idle can be split
        # into body / arm / scarf layers; a scarf layer with bigger crops but only a few near-exact keys is not it)
        cands = []
        for part, n, ni, sheet in layers:
            keys = sorted(_node_key_range(b, ni), key=lambda i: b.keys[i].time)
            on_sheet = [own_map[b.keys[i].cell] for i in keys
                        if _wait_sheet(own_map.get(b.keys[i].cell)) == sheet]
            limit = _err_limit([pl.get("err") for pl in on_sheet])
            good = [pl for pl in on_sheet if pl.get("err") is not None and pl["err"] <= limit]
            if 2 * len(good) >= len(keys):
                cands.append((part, n, ni, sheet, keys, limit))
        if not cands:
            continue
        part, n, ni, sheet, keys, limit = max(cands, key=lambda x: (x[0], x[1]))
        out[an.id] = dict(node=ni, sheet=sheet, keys=keys, end=info["loop"][1], limit=limit,
                          layers=[x for x in others if x != ni])
    return out


def settle_idle_loops(b, loops, own_map, regs=None):
    """Make the body layer of every idle loop play the unit's own wait drawings, nothing else.

    Vanilla idles have 6 drawings, the DRPG wait sheets 5: for every twin, vanilla drawings 1, 2, 4, 5, 6 are the
    wait slots 0, 3, 1, 2, 4 and drawing 3 is an in-between DRPG does not have (it only matches near-duplicates).
    A body key that is not the unit's drawing - the in-between (no near-exact placement), a battle-sheet piece some
    templates use for one beat (1140, 1200), the other view's sheet, or a slot this unit has no drawing for - shows
    the previous good key's drawing instead (cell and transform, i.e. that frame is held; cyclic, so a bad first
    key holds the loop's last drawing).  The loop then cycles through the unit's 5 wait drawings in the vanilla
    order and timing (e.g. 12/24/12/12/12 ticks), never flips between near-duplicates.
    -> number of keys held"""
    held = 0
    for aid, lp in loops.items():
        def good(i):
            pl = own_map.get(b.keys[i].cell)
            if _wait_sheet(pl) != lp["sheet"] or pl.get("err") is None or pl["err"] > lp["limit"]:
                return False
            return regs is None or (lp["sheet"], "slot", pl["region"][2]) in regs

        keys = lp["keys"]
        ok = [i for i in keys if good(i)]
        if not ok:
            continue
        in_loop = [i for i in ok if b.keys[i].time <= lp["end"]] or ok
        for i in keys:
            if i in ok:
                continue
            prev = [g for g in ok if b.keys[g].time < b.keys[i].time]
            src = prev[-1] if prev else in_loop[-1]
            b.keys[i].cell, b.keys[i].xform = b.keys[src].cell, b.keys[src].xform
            held += 1
    return held


def strip_idle_overlays(b, loops):
    """Idle loops of a new unit: every layer except the body layer is hidden.  Those layers are the template's own
    idle hand / arm pieces (loose hands, battle-sheet hand slots such as front 26/28/31/36/37/39/43 or back 36/38,
    exact matches or not) or a second crop of its body, all placed for the TEMPLATE's drawing; on a new unit they
    float (the Beast Master's fist above her head).  The DRPG wait frame drawn by the body layer is complete (wait
    sheets have no loose pieces), and the body layer draws it whole (see build).
    -> {anim id: [hidden signed cells]}"""
    out = {}
    for aid, lp in loops.items():
        for ni in lp["layers"]:
            for i in _node_key_range(b, ni):
                if b.keys[i].cell:
                    out.setdefault(aid, []).append(b.keys[i].cell)
                    b.keys[i].cell = 0
    return {a: sorted(set(c), reverse=True) for a, c in out.items()}


HAND_R = 11             # px: the hand layer covers the gripping fist within this radius of the grip point
HAND_TOL = 72           # colour distance (RGB) from the grip pixel's colour that still counts as the fist
HAND_MIN = 12           # px: a smaller colour patch is no fist (the grip sits on an outline): a small disc instead


def _hand_mask(img, x, y, r=HAND_R, tol=HAND_TOL):
    """the gripping fist around (x, y) in a drawing: the patch of the grip pixel's colour within r px, plus its
    dark outline (2 px) -> bool mask, or None"""
    h, w = img.shape[:2]
    a = img[..., 3] > 0
    yy, xx = np.mgrid[:h, :w]
    d2 = (xx - x) ** 2 + (yy - y) ** 2
    near = a & (d2 <= 16)
    if not near.any():
        return None
    sy, sx = np.unravel_index(np.argmin(np.where(near, d2, 1e9)), d2.shape)
    ring = a & ((xx - sx) ** 2 + (yy - sy) ** 2 <= 4)
    seed = np.median(img[ring][:, :3].astype(float), axis=0)
    close = a & (d2 <= r * r) & (np.linalg.norm(img[..., :3].astype(float) - seed, axis=2) < tol)
    from scipy import ndimage
    lab, n = ndimage.label(close)
    m = lab == lab[sy, sx] if close[sy, sx] else np.zeros_like(close)
    if m.sum() < HAND_MIN:
        m = a & (d2 <= 36)
    return ndimage.binary_dilation(m, iterations=2) & a & (d2 <= (r + 2) ** 2)


def add_hand_layers(b, loops, draw, regs, matches, frames, hands, log=None):
    """The vanilla way of holding a weapon in the idle loops of a new unit: a layer drawn ABOVE the weapon showing
    only the unit's own gripping fist (cut out of each wait drawing around its hand point from drpg_hands.json), so
    every weapon type sits inside the closed hand (vanilla idles carry such small hand layers: Archer's idle is
    hand | weapon | body).  The layer copies the body layer's keys, so it moves and changes drawing with it.
    _restack then puts the main hand's weapons between body and hand.  -> {anim id: hand layer node}"""
    done = {}
    for aid, lp in loops.items():
        pts = (hands or {}).get(lp["sheet"])
        if not pts:
            continue
        body = b.nodes[lp["node"]]
        cell_of = {}
        for i in _node_key_range(b, lp["node"]):
            c = b.keys[i].cell
            if not c or c in cell_of or c not in matches or c not in draw:
                continue
            pl = draw[c]
            slot = pl["region"][2]
            if pl["region"][0] != lp["sheet"] or slot >= len(pts) or not pts[slot]:
                continue
            key = tuple(pl["region"])
            r = regs.get(key)
            if r is None:
                continue
            marker = np.zeros_like(r["img"])          # hand points are slot coordinates; the image starts at org
            hx, hy = int(round(pts[slot][0] - r["org"][0])), int(round(pts[slot][1] - r["org"][1]))
            marker[max(0, hy - 2):hy + 3, max(0, hx - 2):hx + 3] = 255
            res = cell_image({key: dict(r, img=marker)}, pl)
            if res is None:
                continue
            mimg, (mdx, mdy) = res
            ys, xs = np.nonzero(mimg[..., 3])
            m = matches[c]
            img = frames[m["frame"]]["rgba"]
            fx, fy = mdx + xs.mean() - m["dx"], mdy + ys.mean() - m["dy"]
            mask = _hand_mask(img, fx, fy)
            if mask is None or not mask.any():
                continue
            ys, xs = np.nonzero(mask)
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            piece = img[y0:y1, x0:x1].copy()
            piece[..., 3] = np.where(mask[y0:y1, x0:x1], piece[..., 3], 0)
            frames.append(dict(rgba=np.ascontiguousarray(piece)))
            sid = -(600000 + len([s for s in matches if -700000 < s <= -600000]))
            matches[sid] = dict(frame=len(frames) - 1, dx=int(m["dx"] + x0), dy=int(m["dy"] + y0))
            cell_of[c] = sid
        if not cell_of:
            continue
        par = next((p for i, d, p in b.walk(next(a for a in b.animations if a.id == aid).root) if i == lp["node"]), -1)
        if par < 0:
            continue
        keys = [dataclasses.replace(b.keys[i], cell=cell_of.get(b.keys[i].cell, 0))
                for i in _node_key_range(b, lp["node"])]
        node = anm.Node(0, body.flags & ~0x100, 0, 0, 0, 0, len(b.keys), len(keys), -1, b.nodes[par].child)
        b.keys.extend(keys)
        b.nodes.append(node)
        b.nodes[par].child = len(b.nodes) - 1
        lp["hand_node"] = done[aid] = len(b.nodes) - 1
    if log and done:
        log(f"  hand layers above the weapon: idle {sorted(done)}")
    return done


def drawable_own_map(own_map):
    """own-pose map without the approximate loose pieces: the template's separate hand overlays of its specials /
    idle (never located exactly, often on the other view's sheet); the 'nearest loose piece' of another unit is an
    unrelated battle-sheet hand that would float at the template's hand position"""
    return {c: pl for c, pl in own_map.items() if not (pl["region"][1] == LOOSE and not pl.get("exact"))}


def template_without(base, b, ko, loops, own_map, draw):
    """copy of the template sprite without what build() hides for a new unit: the idle loops' other layers
    (strip_idle_overlays; `b` = merged block, own keys from index ko) and the own pieces drawable_own_map drops"""
    import copy
    out = copy.deepcopy(base)
    keys = out.blocks[0].keys
    for lp in loops.values():
        for ni in lp["layers"]:
            for i in _node_key_range(b, ni):
                keys[i - ko].cell = 0
    dropped = {-c for c in own_map if c not in draw}
    for k in keys:
        if k.cell in dropped:
            k.cell = 0
    return out


# ------------------------------------------------------------------------------------------ own animations: weapons
def load_hands(path=None):
    """{uid: {'wait_front' | 'wait_back': [[x, y(, rot)] per wait slot], 'mirror': {sheet: bool} (optional)}}: the
    point where the unit's weapon hand grips in each DRPG wait frame, slot coordinates (atlas orientation, as in
    drpg_slots.json).  rot (degrees, clockwise) turns the stand pose's weapon about the hand; 'mirror' overrides the
    automatic choice of mirroring the stand pose's weapon (see anchor_on_hands)."""
    path = path or HANDS_PATH
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {int(k): v for k, v in json.load(f).items() if k.isdigit()}


def _node_states(b, aid, t):
    """{node index: (parent world matrix, active key index or None, node world matrix)} of animation `aid` at t"""
    an = next(a for a in b.animations if a.id == aid)
    out = {}

    def rec(ni, parent, seen):
        while 0 <= ni < len(b.nodes) and ni not in seen:
            seen.add(ni)
            n = b.nodes[ni]
            ks = list(_node_key_range(b, ni))
            act, m = None, parent
            if ks:
                a = anm._active_key([b.keys[i] for i in ks], t)
                if a is not None:
                    k, nx, f = a
                    act = next(i for i in ks if b.keys[i] is k)
                    vals, pts, col = anm._key_state(b, n, k, nx, f)
                    m = parent @ anm._mat(*vals)
            out[ni] = (parent, act, m)
            if (not ks or act is not None) and n.child >= 0:
                rec(n.child, m, seen)
            ni = n.next

    rec(an.root, np.eye(3), set())
    return out


def _decompose(M):
    """3x3 matrix -> Transform fields (x, y, sx, sy, rot): the inverse of anm._mat (mirroring goes to sx)"""
    A = M[:2, :2]
    sy = math.hypot(A[0, 1], A[1, 1]) * 100
    c, s = A[1, 1] * 100 / sy, -A[0, 1] * 100 / sy
    sx = (A[0, 0] * c + A[1, 0] * s) * 100
    return (int(round(M[0, 2])), int(round(M[1, 2])), int(round(sx)), int(round(sy)),
            int(round(math.degrees(math.atan2(s, c)))))


def _region_to_cell_matrix(pl):
    """3x3 affine: a point of the mapped region (slot coordinates) -> the cell's own pixel coordinates (undoes the
    placement's mirror / quarter turns)"""
    w, h = pl["rect"]
    U = np.tile(np.arange(w, dtype=np.float64), (h, 1))
    V = np.tile(np.arange(h, dtype=np.float64)[:, None], (1, w))
    Ut, Vt = _transform(U, pl["mirror"], pl["k"]), _transform(V, pl["mirror"], pl["k"])
    HT, WT = Ut.shape
    p00 = np.array([Ut[0, 0], Vt[0, 0]])
    px = (np.array([Ut[0, WT - 1], Vt[0, WT - 1]]) - p00) / max(1, WT - 1)
    py = (np.array([Ut[HT - 1, 0], Vt[HT - 1, 0]]) - p00) / max(1, HT - 1)
    o = p00 - pl["ox"] * px - pl["oy"] * py
    return np.array([[px[0], py[0], o[0]], [px[1], py[1], o[1]], [0, 0, 1.0]])


def idle_frames(b, loops, own_map, regs):
    """Per idle loop and body key shown (inside the loop): (time, wait slot shown, slot -> world matrix, world x of
    the drawing's centre).  The matrix maps a slot pixel to the world position of its centre in that frame:
    placement (slot -> cell pixel), the key's pivot, the body node's world matrix.  Taken before ownanim.assemble
    re-points the cells (it keeps every node's matrix, only pivots change).  Keys after the loop end are never shown
    (some templates leave a stray one there, drawn elsewhere)."""
    out = {}
    for aid, lp in loops.items():
        fr = []
        for i in lp["keys"]:
            key = b.keys[i]
            pl = own_map.get(key.cell)
            if _wait_sheet(pl) != lp["sheet"] or key.time > lp["end"]:
                continue
            par, act, m = _node_states(b, aid, key.time)[lp["node"]]
            if act is None:
                continue
            xf = b.transforms[key.xform]
            piv = b.pivots[xf.pivot] if 0 <= xf.pivot < len(b.pivots) else anm.Pivot(0, 0)
            S = m @ np.array([[1, 0, 0.5 - piv.x], [0, 1, 0.5 - piv.y], [0, 0, 1.0]]) @ _region_to_cell_matrix(pl)
            slot = pl["region"][2]
            r = regs.get((lp["sheet"], "slot", slot))
            cx = None
            if r is not None:
                ys, xs = np.nonzero(r["img"][..., 3] > 0)
                cx = float((S @ np.array([xs.mean() + r["org"][0], ys.mean() + r["org"][1], 1.0]))[0])
            fr.append((key.time, slot, S, cx))
        out[aid] = fr
    return out


def _parent_of(b, aid, ni):
    an = next(a for a in b.animations if a.id == aid)
    return next((p for i, d, p in b.walk(an.root) if i == ni), -1)


def _siblings(b, parent):
    out, c = [], b.nodes[parent].child
    while 0 <= c < len(b.nodes) and c not in out:
        out.append(c)
        c = b.nodes[c].next
    return out


def _attach_ids(b, ni):
    ids = {b.nodes[ni].id} if b.nodes[ni].id >= 10 else set()
    if b.nodes[ni].child >= 0:
        ids |= {b.nodes[i].id for i, d, p in b.walk(b.nodes[ni].child) if b.nodes[i].id >= 10}
    return ids


def _restack(b, aid, pose_node, stand_id, hand=None):
    """attachments of `aid` in front of / behind the body as in the stand pose (first sibling = drawn on top).
    With a hand layer (add_hand_layers) the vanilla way of holding a weapon: hand layer on top, the main hand's
    weapons (group A) under it and above the body (Archer's idle: hand | weapon | body), so the fist closes around
    every weapon type; group B and the rest as in the stand pose."""
    par = _parent_of(b, aid, pose_node)
    st = next(a for a in b.animations if a.id == stand_id)
    body = [i for i, d, p in b.walk(st.root) if b.nodes[i].id == 1 and any(k.cell for k in b.node_keys(b.nodes[i]))]
    if par < 0 or not body:
        return
    sib = _siblings(b, _parent_of(b, stand_id, body[0]))
    front = set()
    for s in sib[:sib.index(body[0])]:
        front |= _attach_ids(b, s)
    ch = _siblings(b, par)
    before, after = [], []
    for s in ch:
        if s != pose_node and s != hand:
            ids = _attach_ids(b, s)
            ids = (ids & set(WEAPON_NODES)) or ids          # a group holding the hand weapons goes with them
            if hand is not None and ids & set(GRIP_GROUPS["A"]):
                on_top = True
            else:
                on_top = 2 * len(ids & front) > len(ids) if ids else ch.index(s) < ch.index(pose_node)
            (before if on_top else after).append(s)
    new = ([hand] if hand is not None and hand in ch else []) + before + [pose_node] + after
    tail = b.nodes[ch[-1]].next
    b.nodes[par].child = new[0]
    for x, y in zip(new, new[1:]):
        b.nodes[x].next = y
    b.nodes[new[-1]].next = tail


def _attachments(b, aid):
    an = next(a for a in b.animations if a.id == aid)
    return [ni for ni, d, p in b.walk(an.root) if b.nodes[ni].id >= 10 and b.nodes[ni].num_keys]


def hide_attachments(b, nodes):
    """the attached weapon is not drawn on these nodes (key flag high byte 2 = hide, as the shared motions park the
    unused group): better no weapon than one floating where the template's hand was"""
    for ni in nodes:
        for i in _node_key_range(b, ni):
            b.keys[i].flags = (b.keys[i].flags & 0xFF) | ATTACH_HIDE


def anchor_on_hands(b, aid, lp, frames, pts, mirror=None):
    """Weapon of idle loop `aid` from per-unit hand data.  The stand pose's attachment rig (anim 1 front / 7 back at
    t0: every attachment node's matrix and weapon-animation param, the right hand's weapon grip G = median of nodes
    11-16) is placed frame by frame so that G lands on the hand point of the wait drawing shown:
        new world = T(hand) . R(rot) [. F] . T(-G) . M_stand        local = inv(parent world) . new world
    Group B and the other attachments move rigidly with the rig, as in the stand pose.  When the hand is on the
    other side of the body than the stand pose's weapon hand (the Onmyo Monk's staff fist), the rig is mirrored
    about the vertical through the hand (F), so the weapon points away from the body as in the stand; `mirror`
    (data) overrides that choice.  The attachments are restacked in front of / behind the body as in the stand.
    -> dict(source='data', mirror=bool, keys=n)"""
    stand_id = 7 if lp["sheet"].endswith("back") else 1
    rig = {b.nodes[ni].id: (m, b.keys[k].param)
           for ni, (par, k, m) in _node_states(b, stand_id, 0).items() if b.nodes[ni].id >= 10 and k is not None}
    G = np.median(np.array([rig[i][0][:2, 2] for i in WEAPON_NODES if i in rig]), 0)
    hand = []
    for t, slot, S, cx in frames:
        hx, hy, rot = (list(pts[slot]) + [0])[:3]
        H = (S @ np.array([hx, hy, 1.0]))[:2]
        hand.append((t, H, math.radians(rot), cx))
    if mirror is None:      # same side as the stand's grip (stand bodies are centred on x = 0)?
        sides = [np.sign(H[0] - cx) != np.sign(G[0]) for t, H, r, cx in hand if cx is not None and abs(H[0] - cx) > 6]
        mirror = 2 * sum(sides) > len(sides) if sides else False
    F = np.diag([-1.0, 1.0, 1.0]) if mirror else np.eye(3)
    n_keys = 0
    att = _attachments(b, aid)
    for ni in att:
        n = b.nodes[ni]
        old = b.keys[n.first_key]
        if n.id not in rig:
            hide_attachments(b, [ni])
            continue
        Ms, param = rig[n.id]
        new = []
        for t, (hx, hy), r, cx in hand:
            R = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1.0]])
            W = np.array([[1, 0, hx], [0, 1, hy], [0, 0, 1.0]]) @ R @ F @ \
                np.array([[1, 0, -G[0]], [0, 1, -G[1]], [0, 0, 1.0]]) @ Ms
            x, y, sx, sy, rt = _decompose(np.linalg.inv(_node_states(b, aid, t)[ni][0]) @ W)
            b.transforms.append(anm.Transform(x, y, 0, 0, sx, sy, rt))
            flags = ((old.flags & 0xFF00) or ATTACH_SHOW) if not new else 0
            new.append(anm.Key(t, flags, 0, len(b.transforms) - 1, old.color, param))
        n.first_key, n.num_keys = len(b.keys), len(new)
        b.keys.extend(new)
        n_keys += len(new)
    _restack(b, aid, lp["node"], stand_id, lp.get("hand_node"))
    return dict(source="data", mirror=bool(mirror), keys=n_keys)


def _grip_mats(a, aid, t):
    """[(node index, node id, parent matrix, matrix)] of the active keys of animation aid at time t"""
    bi, ai = anm._resolve_anim(a, ("id", aid))
    b = a.blocks[bi]
    out = []

    def rec(ni, pm, seen):
        while 0 <= ni < len(b.nodes) and ni not in seen:
            seen.add(ni)
            n = b.nodes[ni]
            ks = b.node_keys(n)
            m = pm
            act = anm._active_key(ks, t) if ks else None
            if act is not None:
                k, nx, f = act
                vals, pts, col = anm._key_state(b, n, k, nx, f)
                m = pm @ anm._mat(*vals)
                out.append((ni, n.id, pm, m))
            if (not ks or act is not None) and n.child >= 0:
                rec(n.child, m, seen)
            ni = n.next

    rec(b.animations[ai].root, np.eye(3), set())
    return out


def _frame(a, aid, t):
    """the frame rendered in GRIP_BOUNDS (RGBA array; pixel (0, 0) = root point (GRIP_BOUNDS[0], GRIP_BOUNDS[1]))"""
    items = anm.evaluate(a, ("id", aid), t)
    if not items:
        return None
    return np.asarray(anm.render_items(a, items, 0, bounds=GRIP_BOUNDS)[0])


def _skin_hands(arr):
    """bare hands of a frame: hand-sized skin blobs [(x, y, in the head zone)] in root coordinates (head zone = top
    third of the body: face, ears - or a hand raised overhead), and the body's centre x"""
    from scipy import ndimage
    if arr is None or not (arr[..., 3] > 0).any():
        return [], 0.0
    ys_, xs_ = np.nonzero(arr[..., 3] > 0)
    cx = float(xs_.mean() + GRIP_BOUNDS[0])
    head = float(ys_.min() + 0.33 * (ys_.max() - ys_.min()) + GRIP_BOUNDS[1])
    lab, n = ndimage.label(drpg.features(arr)[1] > 0, np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        y = float(ys.mean() + GRIP_BOUNDS[1])
        if HAND_AREA[0] <= len(ys) <= HAND_AREA[1]:
            out.append((float(xs.mean() + GRIP_BOUNDS[0]), y, y <= head))
    return out, cx


def _same_drawing_near(ta, ua, P, r=GRIP_WINDOW):
    """the unit's frame reproduces the template's frame around the grip point P (same silhouette, colours within an
    exact match's error): the template's hand is there, so is its grip.  Catches what skin blobs miss (a fist that
    is one blob with the bare arm, gloves) for the template's own twin and same-pose units."""
    if ta is None or ua is None:
        return False
    x, y = int(round(P[0] - GRIP_BOUNDS[0])), int(round(P[1] - GRIP_BOUNDS[1]))
    H, W = ta.shape[:2]
    y0, y1, x0, x1 = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
    if y1 <= y0 or x1 <= x0:
        return False
    a, b = ta[y0:y1, x0:x1], ua[y0:y1, x0:x1]
    ma, mb = a[..., 3] > 0, b[..., 3] > 0
    union, inter = (ma | mb).sum(), (ma & mb).sum()
    if not union or inter < 0.9 * union:
        return False
    return float(np.abs(a[..., :3].astype(np.int32) - b[..., :3].astype(np.int32))[ma & mb].mean()) <= EXACT_ERR


def _grip_cost(h, n):
    return abs(n[0] - h[0]) + 3 * abs(n[1] - h[1])


def auto_grips(out, tmpl, bare, aid):
    """Automatic grips of idle loop `aid` for a unit WITHOUT hand data (nothing is changed here).  Per group (A = nodes
    11-17, B = 111-117) and attachment key time, two tests:
      'same'   the unit's frame reproduces the complete template frame `tmpl` around the attachment point
               (_same_drawing_near): the template's hand is there, so its grip is right (the template's own twin,
               same-pose units; its whole wait frame contains the hand the template draws as a separate piece)
      'paired' corrected skin-blob pairing: the template's bare hand H gripping the group (skin blob within
               TEMPLATE_HAND_R of the attachment point, in `bare` = the template without the pieces this build hides:
               a hand piece the unit does not draw has no counterpart), the unit's blob N nearest to it
               (|dx| + 3|dy| <= MAX_GRIP_DIST; not in the head zone unless H is raised there); move N - H, mirrored
               when N is on the other side of the body than H
    A group whose keys are mostly 'same' is 'kept'.  Else, if most keys pair, it is 'paired' with the median move
    (a median within GRIP_NOISE px and no mirror = no move); else 'none'.  The template's own twin never moves (the
    regression gate).  But a skin blob is often not a hand (bare arms, legs, belly; gloved or hidden hands): on the
    two DRPG classes built on all 18 templates only 16 of 52 pairings land within 8 px of a real hand, so a pairing
    is only a SUGGESTION unless the caller asks for it (place_idle_weapons auto=True).
    -> {group: dict(mode='kept'|'paired'|'none', delta, mirror, nodes)}"""
    b = out.blocks[0]
    an = next(x for x in b.animations if x.id == aid)
    walk = [ni for ni, d, p in b.walk(an.root)]
    tan = next(x for x in tmpl.blocks[0].animations if x.id == aid)
    pair = dict(zip(walk, [ni for ni, d, p in tmpl.blocks[0].walk(tan.root)]))
    nodes = {g: [ni for ni in walk if b.nodes[ni].id in ids and b.nodes[ni].num_keys] for g, ids in GRIP_GROUPS.items()}
    times = sorted({b.keys[i].time for g in nodes.values() for ni in g for i in _node_key_range(b, ni)})
    same, found = {g: 0 for g in nodes}, {g: [] for g in nodes}
    for t in times:
        tm = {ni: m for ni, nid, pm, m in _grip_mats(tmpl, aid, t)}
        ta, ua = _frame(tmpl, aid, t), _frame(out, aid, t)
        th, tcx = _skin_hands(_frame(bare, aid, t))
        nh, ncx = _skin_hands(ua)
        for g, ns in nodes.items():
            pts = [tm[pair[ni]][:2, 2] for ni in ns if pair.get(ni) in tm]
            if not pts:
                continue
            P = np.mean(pts, 0)
            if _same_drawing_near(ta, ua, P):
                same[g] += 1
                found[g].append((t, np.zeros(2), False))
                continue
            if not th or not nh:
                continue
            H = min(th, key=lambda h: math.hypot(h[0] - P[0], h[1] - P[1]))
            if math.hypot(H[0] - P[0], H[1] - P[1]) > TEMPLATE_HAND_R:
                continue
            # a blob in the head zone (face, ears) only answers a template hand raised there, and only very close by:
            # an overhead grip must not land on the unit's face, nor be paired with a hand far below it
            cand = [n for n in nh if not n[2] or (H[2] and _grip_cost(H, n) <= HEAD_GRIP_DIST)]
            if not cand:
                continue
            N = min(cand, key=lambda n: _grip_cost(H, n))
            if _grip_cost(H, N) > MAX_GRIP_DIST:
                continue
            mir = (H[0] - tcx) * (N[0] - ncx) < 0 and abs(N[0] - ncx) > 6 and abs(H[0] - tcx) > 6
            found[g].append((t, np.array([N[0] - H[0], N[1] - H[1]]), mir))
    rep = {}
    for g, ns in nodes.items():
        if not ns:
            continue
        lst = found[g]
        if times and 2 * same[g] >= len(times):
            rep[g] = dict(mode="kept", delta=[0.0, 0.0], mirror=False, nodes=ns)
        elif times and 2 * len(lst) >= len(times):
            d = np.median([x[1] for x in lst], 0)
            mir = 2 * sum(x[2] for x in lst) > len(lst)
            if np.hypot(*d) <= GRIP_NOISE and not mir:
                d = np.zeros(2)
            rep[g] = dict(mode="paired", delta=[round(float(d[0]), 1), round(float(d[1]), 1)], mirror=bool(mir),
                          nodes=ns)
        else:
            rep[g] = dict(mode="none", nodes=ns)
    return rep


def move_group(b, aid, nodes, d, mirror):
    """every key of the attachment `nodes` moved by d (root coordinates), mirrored about the node's vertical"""
    d = np.asarray(d, float)
    for ni in nodes:
        for ki in list(_node_key_range(b, ni)):
            key = b.keys[ki]
            L = _node_states(b, aid, key.time)[ni][0][:2, :2]
            ld = np.linalg.solve(L, d) if abs(np.linalg.det(L)) > 1e-6 else d
            xf = b.transforms[key.xform]
            b.transforms.append(anm.Transform(int(round(xf.x + ld[0])), int(round(xf.y + ld[1])), xf.pivot, xf.unk,
                                              -xf.sx if mirror else xf.sx, xf.sy, -xf.rot if mirror else xf.rot))
            key.xform = len(b.transforms) - 1


def suggest_hands(b, aid, frames, d, nslots=5):
    """hand points for drpg_hands.json from an automatic group A grip: the grip (median of the weapon nodes, world,
    moved by d) at every body key taken back to slot coordinates, median per wait slot; None for a slot the loop
    never shows"""
    per = {}
    for t, slot, S, cx in frames:
        st = _node_states(b, aid, t)
        pts = [m[:2, 2] for ni, (par, k, m) in st.items() if b.nodes[ni].id in WEAPON_NODES and k is not None]
        if pts:
            p = np.linalg.inv(S) @ np.array([*(np.median(pts, 0) + np.asarray(d, float)), 1.0])
            per.setdefault(slot, []).append(p[:2])
    return [[int(round(v)) for v in np.median(per[s], 0)] if s in per else None for s in range(nslots)]


def place_idle_weapons(out, tmpl, bare, loops, frames, hands, auto=False, log=print, uid=None):
    """The weapon of every idle loop goes into the unit's own hand.  The template's idle grips are where the
    TEMPLATE's hands were (a staff hanging below the Onmyo Monk's fist, the Beast Master's axe in a floating fist):
      1. per-unit hand data (drpg_hands.json) -> anchor_on_hands: the stand pose's weapon rig on the unit's hand
      2. no data -> auto_grips: a group whose drawing around the grip is the template's own keeps its grip; a
         skin-blob pairing is applied only with auto=True, otherwise it is logged as SUGGESTED hand points
      3. otherwise the group's weapon is hidden in that animation (key flag 0x200, like the shared motions' parked
         group) - never left floating where the template's hand was
    -> {anim id: report}"""
    b = out.blocks[0]
    rep = {}
    for aid, lp in sorted(loops.items()):
        fr = frames.get(aid) or []
        pts = hands.get(lp["sheet"]) if hands else None
        att = _attachments(b, aid)
        if not att:
            continue
        if pts and fr and all(s < len(pts) and pts[s] for t, s, S, cx in fr):
            rep[aid] = anchor_on_hands(b, aid, lp, fr, pts, (hands.get("mirror") or {}).get(lp["sheet"]))
            continue
        groups = auto_grips(out, tmpl, bare, aid) if fr else {}
        a = groups.get("A", {})
        sug = suggest_hands(b, aid, fr, a["delta"]) if a.get("mode") == "paired" else None
        placed = set()
        for g, r in groups.items():
            if r["mode"] == "kept" or (auto and r["mode"] == "paired"):
                if r["mode"] == "paired" and (r["delta"] != [0.0, 0.0] or r["mirror"]):
                    move_group(b, aid, r["nodes"], r["delta"], r["mirror"])
                placed |= set(r["nodes"])
        hide_attachments(b, [ni for ni in att if ni not in placed])
        source = "auto" if placed else "hidden"
        rep[aid] = dict(source=source, suggested=sug,
                        groups={g: {k: v for k, v in r.items() if k != "nodes"} for g, r in groups.items()})
        if log:
            what = "placed by automatic hand detection" if placed else "hidden"
            log(f"  idle {aid}: no hand data for DRPG unit {uid} ({lp['sheet']}) in drpg_hands.json - weapon {what}"
                + (f"; suggested hand points (check them on the wait frames before storing): {sug}" if sug else ""))
    return rep


# ------------------------------------------------------------------------------------------ own animations: specials
# A unique character's own special poses (7xx1 / 7xx7: its skill moves) mostly have no DRPG drawing: DRPG units only
# carry the standard battle poses.  Like the idle, a special plays ONE layer - its body layer - drawing whole DRPG
# frames; the template's other layers (separate arm / scarf / hair pieces placed for the template's drawing) are
# hidden.  A body cell located exactly keeps that drawing; any other gets the DRPG frame whose WHOLE silhouette best
# matches the template's whole pose at that moment (matched on the template's own twin, i.e. the same character),
# placed where it overlaps the template's pose most.

POSE_MIN_IOU = 0.35     # a whole-pose match weaker than this keeps the approximate cell placement
# DRPG frames a special never takes whole: tumbling frames (upside down; they win on any horizontal pose) and hand
# overlays.  Mirrored frames are not used either: they turn the unit to face the other way.
POSE_SKIP = ("rolling", "roll_landing", "_hand")


def special_layers(b, own_ids, loops, own_cells, keep=()):
    """{anim id: (body keys, overlay keys)} for the own animations that are not idle loops.  At every key time the
    body is the biggest drawing showing then (the character's drawing can move between layers over time); keys that
    are never the body are overlays (separate arm / hair pieces placed for the template's drawing).  Keys are merged
    key indices of own non-effect cells.  own_cells: the template sprite's own cells (merged keys hold own cell c as
    -c); keep: effect / prop cells (never a body, never an overlay)."""
    keep = set(keep)
    out = {}
    for an in b.animations:
        if an.id not in own_ids or an.id in loops:
            continue
        tracks = []
        for ni, d, p in b.walk(an.root):
            ks = sorted(_node_key_range(b, ni), key=lambda i: b.keys[i].time)
            if any(b.keys[i].cell < 0 and b.keys[i].cell not in keep for i in ks):
                tracks.append(ks)
        if not tracks:
            continue
        times = sorted({b.keys[i].time for ks in tracks for i in ks})
        body, seen = set(), set()
        for t in times:
            best = None
            for ks in tracks:
                act = [i for i in ks if b.keys[i].time <= t]
                if not act:
                    continue
                i = act[-1]
                c = b.keys[i].cell
                if c >= 0 or c in keep:
                    continue
                seen.add(i)
                area = own_cells[-c].w * own_cells[-c].h
                if best is None or area > best[0]:
                    best = (area, i)
            if best:
                body.add(best[1])
        out[an.id] = (body, seen - body)
    return out


def pose_match_specials(fs, cls, twin, own_map, log=print, roots=None):
    """own-map entries for the special body cells without an exact location: the twin's DRPG frame (slot) whose whole
    silhouette best matches the template's whole pose (all its layers) at the key's time -> {signed cell: placement}
    (part 1.0 = the whole frame, 'pose' marks them)"""
    from . import ownanim
    from scipy.signal import fftconvolve
    motion = sprites.motion_block(fs, 1)
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, cls, "EN")))
    b, own_ids = ownanim._merge(motion, base.blocks[0])
    loops = idle_loops(b, own_ids, own_map)
    regs = regions(twin, roots)
    B = (-256, -320, 256, 96)
    ids = {x["id"]: x["index"] for x in anm.list_animations(base)}
    cand_cache = {}
    out = {}
    keep = {c for c, v in own_map.items() if v.get("keep")}
    ko = len(motion.keys)
    for aid, (body, others) in special_layers(b, own_ids, loops, base.blocks[0].cells, keep).items():
        if aid not in ids:
            continue
        views = ("back", "wait_back") if aid % 10 == 7 else ("front", "wait_front")
        for i in sorted(body):
            k = b.keys[i]
            c = k.cell
            if c >= 0 or c in out or c in keep or (own_map.get(c) or {}).get("exact"):
                continue
            xf = b.transforms[k.xform]
            if (xf.sx, xf.sy, xf.rot) != (100, 100, 0):
                continue
            items = [it for it in anm.evaluate(base, ids[aid], k.time) if -it.key.cell not in keep]
            mine = [it for it in items if it.key is base.blocks[0].keys[i - ko]]
            if not items or not mine or not mine[0].cell.w or not mine[0].cell.h:
                continue
            img, _ = anm.render_items(base, items, bounds=B)
            R = (np.asarray(img)[..., 3] > 0).astype(np.float32)
            q = mine[0].quad
            if abs(q[1][1] - q[0][1]) > 0.5 or q[1][0] < q[0][0]:     # rotated / mirrored placement: leave it
                continue
            qx, qy = float(q[0][0]) - B[0], float(q[0][1]) - B[1]
            best = None
            names = drpg.load_slots()
            for key, r in regs.items():
                if key[1] != "slot" or key[0] not in views:
                    continue
                nm = names[key[0]][key[2]]["name"]
                if any(x in nm for x in POSE_SKIP):
                    continue
                for mir in (0,):
                    ck = (key, mir)
                    if ck not in cand_cache:
                        im = r["img"][:, ::-1] if mir else r["img"]
                        cand_cache[ck] = (im[..., 3] > 0).astype(np.float32)
                    m = cand_cache[ck]
                    h, w = m.shape
                    if h > R.shape[0] or w > R.shape[1]:
                        continue
                    cor = fftconvolve(R, m[::-1, ::-1], mode="valid")
                    y, x = np.unravel_index(int(cor.argmax()), cor.shape)
                    ov = cor[y, x]
                    iou = ov / (R.sum() + m.sum() - ov + 1e-6)
                    if best is None or iou > best[0]:
                        best = (iou, key, mir, x, y, w)
            if best is None or best[0] < POSE_MIN_IOU:
                continue
            iou, key, mir, X, Y, Wr = best
            L, T = regs[key]["org"]
            cw, ch = mine[0].cell.w, mine[0].cell.h
            ox = L + (Wr - (qx - X) - cw if mir else qx - X)
            oy = T + (qy - Y)
            out[c] = dict(region=list(key), mirror=int(mir), k=0, ox=int(round(ox)), oy=int(round(oy)),
                          rect=[int(cw), int(ch)], part=1.0, votes=0.0, exact=0, twins=1, err=None, pose=True,
                          iou=round(float(iou), 3))
            if log:
                log(f"  special {aid} t{k.time}: cell {c} -> {key[0]} slot {key[2]}{' mirrored' if mir else ''} "
                    f"(pose iou {iou:.2f})")
    return out


CHAR_COLOURS = 0.3      # colour-histogram overlap with the character's DRPG frames below which an own drawing is an
                        # effect / prop (summoned objects, slash trails: 0.00-0.18; the character's own pieces 0.4-0.76)


BODY_SHAPE = 0.55        # ... unless its silhouette overlaps one of the twin's frames this much (a tinted body:
CHAR_COLOURS_SURE = 0.15  # Asagi's darkened body 0.28); below this overlap it is an effect whatever its shape


def _colour_hist(px):
    q = (px[:, 0] // 32) * 64 + (px[:, 1] // 32) * 8 + px[:, 2] // 32
    h = np.bincount(q, minlength=512).astype(float)
    return h / max(1.0, h.sum())


def effect_cells(fs, cls, twin, own, motion=None, roots=None):
    """own cells of vanilla character `cls` that are not the character: not located exactly in its twin and coloured
    unlike the twin's battle frames (histogram overlap < CHAR_COLOURS) -> {signed cell: 'keep' entry}.  build() draws
    them unchanged (a summoned object, a slash trail); specials never hide or pose-match them."""
    regs = regions(twin, roots)
    ref = [r["img"][r["img"][..., 3] > 128][:, :3].astype(np.int64) for key, r in regs.items()
           if key[1] == "slot" and key[0] in ("front", "back")]
    if not ref:
        return {}
    H = _colour_hist(np.concatenate(ref))
    bank = None
    out = {}
    for cid, img, trim, rect in cells_of(fs, cls, motion):
        if cid >= 0 or (own.get(cid) or {}).get("exact"):
            continue
        px = img[img[..., 3] > 128][:, :3].astype(np.int64)
        if len(px) < 8:
            continue
        score = float(np.minimum(_colour_hist(px), H).sum())
        if CHAR_COLOURS_SURE <= score < CHAR_COLOURS and len(px) >= 1500:
            # a big drawing coloured unlike the character may still be the character (a darkened / tinted body in
            # a skill): its silhouette matches one of the twin's frames
            if bank is None:
                bank = _Bank({k: r for k, r in regs.items() if k[1] == "slot"})
            h, w = img.shape[:2]
            if h < bank.n and w < bank.n:
                cor, m = bank.correlate(img)
                tot = m.sum()
                ov = cor.reshape(len(bank.keys), -1).max(1)
                if float(np.max(ov / (tot + bank.area - ov + 1e-6))) >= BODY_SHAPE:
                    continue
        if score < CHAR_COLOURS:
            out[cid] = dict(region=["keep", "keep", 0], keep=True, mirror=0, k=0, ox=0, oy=0, rect=list(rect),
                            part=1.0, votes=0.0, exact=0, twins=0, err=None, colours=round(score, 3))
    return out


TWIN_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cellmap_unique")


def effect_animations(fs, cls, own_map, motion=None):
    """own special animations with no drawing that is confidently the character (no exact location, no whole-pose
    match): effect-only animations (an emblem, a summon) -> 'keep' entries for all their remaining own cells"""
    from . import ownanim
    motion = motion or sprites.motion_block(fs, 1)
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, cls, "EN")))
    b, own_ids = ownanim._merge(motion, base.blocks[0])
    loops = idle_loops(b, own_ids, own_map)
    keep = {c for c, v in own_map.items() if v.get("keep")}
    out = {}
    for aid, (body, others) in special_layers(b, own_ids, loops, base.blocks[0].cells, keep).items():
        cells = {b.keys[i].cell for i in body | others}
        if any((own_map.get(c) or {}).get("exact") or (own_map.get(c) or {}).get("pose") for c in cells):
            continue
        for c in cells:
            cell = base.blocks[0].cells[-c]
            out[c] = dict(region=["keep", "keep", 0], keep=True, mirror=0, k=0, ox=0, oy=0, rect=[cell.w, cell.h],
                          part=1.0, votes=0.0, exact=0, twins=0, err=None, effect_anim=aid)
    return out


def learn_unique(fs, cls, twin, log=print, motion=None, roots=None, cache=True):
    """the pose map of vanilla character sprite `cls` from its DRPG twin -> saved as data/drpg_ownmap_<cls>.json;
    returns (map, report).  Own cells (negative): idle / exact cells located like a class template's, special body
    poses matched whole (pose_match_specials).  Shared motion cells (positive) the twin has exactly: where THIS
    character's drawing lies in the DRPG frame; a unique character's drawings sit a few px differently in the shared
    cells than the generic classes' (drpg_cellmap.json), and build() prefers these.  The twin location (slow) is
    cached in d5lib/data/cellmap_unique/<cls>_<twin>.json."""
    cp = os.path.join(TWIN_CACHE, f"{int(cls)}_{int(twin)}.json")
    if cache and os.path.exists(cp):
        with open(cp) as f:
            r = {int(k): v for k, v in json.load(f).items()}
    else:
        r = locate_twin(fs, cls, twin, log=None, motion=motion)
        os.makedirs(TWIN_CACHE, exist_ok=True)
        with open(cp, "w") as f:
            json.dump({str(k): v for k, v in r.items()}, f)
    own = consensus({"self": {c: v for c, v in r.items() if c < 0}})
    effects = effect_cells(fs, cls, twin, own, motion, roots)
    own.update(effects)
    poses = pose_match_specials(fs, cls, twin, own, log, roots)
    own.update(poses)
    fx_anims = effect_animations(fs, cls, own, motion)
    own.update(fx_anims)
    effects.update(fx_anims)
    shared = {c: v for c, v in r.items() if c > 0}
    # the twin's own placements of the shared cells -- only when its battle sheets are in a known slot layout (a
    # monster-packed twin such as Liezerota's 20030 is labelled by silhouette: its canvases are guesses)
    sheets = drpg.unit_sheets(twin, roots)
    slotted = all(drpg.fit_layout(drpg.atlas_pieces(sheets[k]), k)[0] for k in ("front", "back"))
    if slotted:
        own.update({c: v for c, v in consensus({"self": {c: v for c, v in shared.items() if v["exact"]}}).items()})
    save_map(own, own_map_path(cls))
    mine = {c: v for c, v in own.items() if c < 0}
    rep = dict(shared=len(shared), shared_exact=sum(1 for v in shared.values() if v["exact"]),
               own=len(mine), own_exact=sum(1 for v in mine.values() if v.get("exact")), poses=len(poses),
               effects=len(effects), shared_placements=slotted,
               agreement=round(agreement(load_map(), shared), 3))
    if log:
        log(f"own map {cls} <- DRPG {twin}: {rep}")
    return own, rep


def strip_special_overlays(b, specials, keep=()):
    """specials' overlay keys hidden (own non-effect cells that are never the body; weapon attachments and effect /
    prop cells stay) -> {anim id: [cells]}"""
    keep = set(keep)
    out = {}
    for aid, (body, others) in specials.items():
        for i in others:
            if b.keys[i].cell < 0 and b.keys[i].cell not in keep:
                out.setdefault(aid, []).append(b.keys[i].cell)
                b.keys[i].cell = 0
    return {a: sorted(set(c), reverse=True) for a, c in out.items()}


def build(fs, uid, template_cls, sprite_id, cmap=None, own_map=None, variants=None, log=print, roots=None,
          hands=None, identity=None, auto_hands=False, specials=False):
    """DRPG unit `uid` -> a sprite with the template class's complete animation set (shared motions + its own
    idle / specials), every cell replaced by the unit's drawing of the same pose at the same place
    -> (AnmFile, report)

    Shared motions are placed by the shared map only.  The template's idle loops (idle_loops) play the unit's own
    DRPG wait drawings (settle_idle_loops); for a new unit they also lose the template's idle hand pieces
    (strip_idle_overlays), draw the wait frame whole, and get the weapon in the unit's own hand
    (place_idle_weapons; hands: drpg_hands.json entry of the unit, default load_hands()[uid]; auto_hands: apply the
    automatic skin-blob grips of a unit without hand data instead of only suggesting them).  identity: the unit is the
    template's twin (default: TWIN_OF), whose idle pieces and grips already belong to its drawing - only the loop is
    settled.  Approximate loose own pieces are never drawn (drawable_own_map)."""
    from . import ownanim
    motion = sprites.motion_block(fs, 1)
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, template_cls, "EN")))
    b, own_ids = ownanim._merge(motion, base.blocks[0])
    regs = regions(uid, roots)
    cmap = cmap if cmap is not None else load_map()
    if own_map is None:
        own_map = load_map(own_map_path(template_cls)) if os.path.exists(own_map_path(template_cls)) else {}
    # a unique character's map also holds its own placements of the shared motion cells (learn_unique)
    over = {c: v for c, v in own_map.items() if c > 0}
    generic = cmap
    if over:
        cmap = {**cmap, **over}
        own_map = {c: v for c, v in own_map.items() if c < 0}
    if identity is None:
        identity = TWIN_OF.get(int(template_cls)) == int(uid)
    loops = idle_loops(b, own_ids, own_map)
    held = settle_idle_loops(b, loops, own_map, regs)
    stripped = {} if identity else strip_idle_overlays(b, loops)
    draw = drawable_own_map(own_map)
    bare = None if identity else template_without(base, b, len(motion.keys), loops, own_map, draw)
    if not identity:        # the body layer draws the complete wait frame (some templates crop it to their body cell)
        for lp in loops.values():
            for i in lp["keys"]:
                c = b.keys[i].cell
                if c in draw:
                    draw[c] = dict(draw[c], part=max(1.0, draw[c]["part"]))
    sp, sp_hidden = {}, {}
    keep = {c for c, v in own_map.items() if v.get("keep")}
    if specials and not identity:   # unique characters' skill poses: the body layer plays whole DRPG frames
        sp = special_layers(b, own_ids, loops, base.blocks[0].cells, keep)
        sp_hidden = strip_special_overlays(b, sp, keep)
        for body, others in sp.values():
            for i in body:
                c = b.keys[i].cell
                if c in draw:
                    draw[c] = dict(draw[c], part=max(1.0, draw[c]["part"]))
    frames_of = idle_frames(b, loops, own_map, regs)
    frames, matches, missing = [], {}, []
    keep_imgs = None
    for cid in sorted({k.cell for k in b.keys if k.cell}):
        pl = cmap.get(cid) if cid > 0 else draw.get(cid)
        if pl is None:
            missing.append(cid)
            continue
        if pl.get("keep"):          # an effect / prop of the template: its own drawing, unchanged
            if keep_imgs is None:
                keep_imgs = {c: (img, trim) for c, img, trim, rect in cells_of(fs, template_cls, motion) if c < 0}
            if cid not in keep_imgs:
                missing.append(cid)
                continue
            img, (tx, ty) = keep_imgs[cid]
            matches[cid] = dict(frame=len(frames), dx=int(tx), dy=int(ty))
            frames.append(dict(rgba=np.ascontiguousarray(img)))
            continue
        r = cell_image(regs, pl)
        if r is None and cid > 0 and generic.get(cid) is not None and generic.get(cid) is not pl:
            r = cell_image(regs, generic[cid])     # the character's own placement is a piece this unit lacks
        if r is None:
            missing.append(cid)
            continue
        img, (dx, dy) = r
        matches[cid] = dict(frame=len(frames), dx=dx, dy=dy)
        frames.append(dict(rgba=img))
    hand_pts = {} if identity else (load_hands().get(int(uid), {}) if hands is None else hands)
    hand_layers = add_hand_layers(b, loops, draw, regs, matches, frames, hand_pts, log) if hand_pts else {}
    out = ownanim.assemble(b, motion, base, frames, matches, sprite_id, variants)
    weapons = {}
    if not identity:
        weapons = place_idle_weapons(out, base, bare, loops, frames_of, hand_pts, auto_hands, log, uid)
        for n in (len(b.keys), len(b.transforms)):
            if n > 32767:
                raise ValueError("animation tables too large")
    # the stub animations' attachment keys (1001 / 1501 ...: the character's own poses) keep their empty cells
    attached = ownanim.restore_attachment_cells(out.blocks[0], [motion, base.blocks[0]])
    rep = dict(cells=len(matches), missing=missing, frames=len(frames), attachments=attached,
               shown=ownanim.assemble.shown, hidden=ownanim.assemble.hidden, held=held,
               idle_loops={a: lp["sheet"] for a, lp in sorted(loops.items())},
               idle_overlays_hidden=stripped, own_overlays_hidden=sorted(c for c in own_map if c not in draw),
               special_overlays_hidden=sp_hidden,
               idle_weapons=weapons, hand_layers=hand_layers)
    if log:
        log(f"DRPG {uid} on {template_cls}'s animations: {len(matches)} cells placed, {len(missing)} without a drawing; "
            f"idle loops {sorted(loops)}: {held} in-between keys held"
            + ("" if identity else ", weapons " + ", ".join(f"{a} {w['source']}" for a, w in sorted(weapons.items()))))
    return out, rep
