"""Generic monsters from Disgaea RPG units (docs/MONSTERS.md).

The vanilla monsters and their Disgaea RPG twins draw the same pictures, but unlike humanoids the DRPG monster atlases
have no fixed layout (they are packed by size) and every monster has its own number of poses.  What they share is
the ROLES of the poses: a stand pose, a walk cycle, a hit pose, an attack sequence, a few extra poses and an idle
cycle (the wait sheets), front and back.  So a new monster is built like this:

  template  a vanilla monster (all of its animations are reused: timing, movement, effects)
  twin map  the template's cells located on its DRPG twin's atlas (data/monster_twins/<template>.json, made by
            _research/monster_twins.py): which twin pose each cell draws, where, mirrored or turned
  roles     what each of the template's twin poses is, read from the animations the engine plays (twin_roles), and
            the new monster's poses by role (data/monster_roles/<uid>.json, load_roles)
  poses     the new monster's pose for each twin pose ({twin region: new region}): pairs_from_roles (by role) or
            suggest (by shape); pose_sheet() shows the pairing for checking
  build     every template cell gets the new monster's drawing of the same role, standing on the ground point of
            the template's own D5 cell art; cells that are only a part of a pose (an arm drawn as its own layer) are
            hidden, the cell drawing the main body carries the whole pose; the idle loops show every wait drawing
"""
import copy
import json
import os
from collections import Counter

import numpy as np
from scipy import ndimage

from . import anm, drpg, drpgmap, sprites

DATA = os.path.join(os.path.dirname(__file__), "data", "monster_twins")
ROLE_DIR = os.path.join(os.path.dirname(__file__), "data", "monster_roles")
SHEETS = ("front", "back", "wait_front", "wait_back")
PARTNER = {"front": "wait_front", "wait_front": "front", "back": "wait_back", "wait_back": "back"}
MIN_AREA = 1500            # smaller atlas pieces are effect specks (flames, sparks), not poses
WHOLE = 0.5                # a cell covering at least this share of its pose draws the whole pose

# (role, front anim, back anim, kind)   kind: first = the animation's first whole pose, seq = all, in time order
ROLE_ANIMS = [("stand", 1, 7, "first"), ("hit", 1061, 1067, "first"), ("idle", 1001, 1007, "seq"),
              ("walk", 11, 17, "seq"), ("crouch", 1121, 1127, "first"), ("jump", 1091, 1097, "seq"),
              ("attack", 2071, 2077, "seq")]
PRIORITY = ["stand", "hit", "idle", "walk", "crouch", "jump", "attack"]
HIT_FALLBACK = (1141, 1147)        # some templates draw the damage pose there (Dragon King's are cell-less links)
FLASH = 0.03               # near-white share (and >= 10x the sheet median) of a DRPG flash frame: never a pose
ROT_COLOUR_ERR = 25        # a turned placement with more colour error than this ...
ROT_MIN_IOU = 0.7          # ... and less outline overlap than this is not the same drawing
LYING = 1.4                # D5 cell art this much wider than tall draws a body lying down
HOLD_MIN_PX = 50           # a hidden cell with less art than this (an empty or speck cell) is hidden, not held
FEET_IOU = 0.3             # feet-band registration this good places an idle drawing on the first one's feet

# D5 generic monster family -> DRPG generic monster (variant 1); Sea Angel (2130) has no DRPG twin
TWINS = {2010 + 10 * k: 30001 + 4 * k for k in range(12)}
TWINS.update({2140: 30053, 2150: 30057, 2160: 30061, 2170: 30065, 2180: 30069, 2190: 30073, 2200: 30077,
              2210: 30081})
# DRPG generic monsters D5 doesn't have (variant 1; +1..+3 are colour variants)
NEW = {30085: "Spirit", 30089: "Gargoyle", 30097: "Death", 30105: "Dragon Zombie", 30113: "Rifle Demon",
       30117: "Lantern", 30125: "Living Armor", 30129: "Serpent", 30133: "Dragon", 30137: "Space Yellowtail"}


# ------------------------------------------------------------------------------------------ regions
def regions(uid, roots=None):
    """{(sheet, 'loose', key): dict(img, org, size)}: every pose-sized piece of the unit's atlases"""
    regs = drpgmap.regions(uid, roots, pieces_only=True)
    return {k: r for k, r in regs.items() if r["img"].shape[0] * r["img"].shape[1] >= MIN_AREA}


def _key(region):
    return tuple(region[:2]) + (int(region[2]),)


def white_share(img):
    a = img[..., 3] > 0
    return float(((img[..., :3].min(axis=2) > 200) & a).sum() / max(1, a.sum()))


# ------------------------------------------------------------------------------------------ template data
def twin_data(cls):
    with open(os.path.join(DATA, f"{int(cls)}.json")) as f:
        return json.load(f)


def templates():
    return sorted(int(f[:-5]) for f in os.listdir(DATA) if f.endswith(".json")) if os.path.isdir(DATA) else []


def is_pose(p):
    """a placement that draws (most of) one whole pose: a good match (exact, or alpha overlap >= 0.6) covering
    50-130% of the piece (effect layers such as Dragon King's flames match pieces badly or only partly)"""
    return p is not None and WHOLE <= p["part"] <= 1.3 and (p.get("exact") or p.get("votes", 0) >= 0.6)


def _anim_poses(b, pl, an):
    """[(time, twin key)] of the whole-pose cells an animation shows inside its played range, in time order"""
    info = anm.animation_info(b, an)
    end = info["loop"][1] if info["loop"] else info["length"]
    out = []
    for ni, depth, parent in b.walk(an.root):
        for k in b.node_keys(b.nodes[ni]):
            if k.cell and k.time <= max(end, 0):
                p = pl.get(-abs(k.cell))
                if is_pose(p):
                    out.append((k.time, _key(p["region"])))
    out.sort(key=lambda x: x[0])
    return out


def twin_roles(fs, cls):
    """{twin region key: [(view 'f' / 'b', role, step)]}, read from the animations the engine plays: stand 1/7, hit
    1061/1067 (the damage pose; 1141/1147 when those are empty), idle 1001/1007, walk 11/17 (inside the loop),
    crouch 1121/1127 (jump / lift take-off), jump 1091/1097, attack 2071/2077.  step = the pose's place among the
    role's distinct poses.  Per pose in PRIORITY order; whole poses no animation above shows get []."""
    d = twin_data(cls)
    pl = {int(c): p for c, p in d["map"].items()}
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, cls, "EN")))
    b = base.blocks[0]
    by_id = {a.id: a for a in b.animations}
    roles = {}
    for role, fid, bid, kind in ROLE_ANIMS:
        for view, aid in (("f", fid), ("b", bid)):
            an = by_id.get(aid)
            seq = _anim_poses(b, pl, an) if an is not None else []
            if role == "hit" and not seq:
                an = by_id.get(HIT_FALLBACK[0 if view == "f" else 1])
                seq = _anim_poses(b, pl, an) if an is not None else []
            order = []
            for t, k in seq:
                if k not in order:
                    order.append(k)
            if kind == "first":
                order = order[:1]
            for i, k in enumerate(order):
                roles.setdefault(k, []).append((view, role, i))
    for k in roles:
        roles[k].sort(key=lambda r: PRIORITY.index(r[1]))
    for c, p in pl.items():
        if is_pose(p) and _key(p["region"]) not in roles:
            roles[_key(p["region"])] = []
    return roles


def role_names(rs):
    return ", ".join(f"{v}:{r}{s + 1 if r not in ('stand', 'hit', 'crouch') else ''}" for v, r, s in rs) or "other"


# ------------------------------------------------------------------------------------------ pairing
def _silhouette(img, size=64):
    """alpha mask scaled into a size x size box, bottom-centred (ground contact)"""
    from PIL import Image
    a = (img[..., 3] > 0).astype(np.uint8) * 255
    h, w = a.shape
    f = size / max(h, w)
    m = np.asarray(Image.fromarray(a).resize((max(1, round(w * f)), max(1, round(h * f)))), np.uint8) > 127
    out = np.zeros((size, size), bool)
    x0 = (size - m.shape[1]) // 2
    out[size - m.shape[0]:, x0:x0 + m.shape[1]] = m
    return out


def _iou(a, b):
    return (a & b).sum() / max(1, (a | b).sum())


def suggest(fs, cls, uid, roots=None):
    """{twin region key: new region key}: the new monster's poses paired with the twin's, sheet by sheet, by
    silhouette (bottom-centred, scaled) with an optimal one-to-one assignment; a sheet with fewer poses repeats
    the best ones.  A role file (pairs_from_roles) pairs better: use this for a first look."""
    from scipy.optimize import linear_sum_assignment
    twin = regions(twin_data(cls)["uid"], roots)
    new = regions(uid, roots)
    used = set(twin_roles(fs, cls))
    out = {}
    for sheet in SHEETS:
        tk = [k for k in twin if k[0] == sheet and k in used]
        nk = [k for k in new if k[0] == sheet]
        if not tk or not nk:
            continue
        ts = [_silhouette(twin[k]["img"]) for k in tk]
        ns = [_silhouette(new[k]["img"]) for k in nk]
        cost = np.array([[1 - _iou(a, b) for b in ns] for a in ts])
        r, c = linear_sum_assignment(cost)
        for i, j in zip(r, c):
            out[tk[i]] = nk[j]
        for i in set(range(len(tk))) - set(r):
            out[tk[i]] = nk[int(np.argmin(cost[i]))]
    return out


def grid_order(keys):
    """region keys of one sheet in reading order (rows = centres less than ~64 px apart)"""
    ks = sorted(keys, key=lambda k: k[2] % 1000)
    rows, cur = [], []
    for k in ks:
        if cur and k[2] % 1000 - cur[-1][2] % 1000 > 8:
            rows.append(cur)
            cur = []
        cur.append(k)
    if cur:
        rows.append(cur)
    return [k for r in rows for k in sorted(r, key=lambda k: k[2] // 1000)]


def role_path(uid):
    return os.path.join(ROLE_DIR, f"{int(uid)}.json")


def load_roles(path):
    """the new monster's poses by role:
    {"front": {"stand": key, "walk": [keys in order], "hit": key, "crouch": key, "jump": [keys],
               "attack": [keys in order], "other": [keys]},
     "back": same, or "grid" (the back sheet is packed like the front: same place in reading order = same pose),
     "wait_front": [keys] / "grid", "wait_back": [keys] / "grid"}   keys = region numbers (atlas place).
    Leave DRPG flash frames (mostly white impact drawings) out of every role."""
    with open(path) as f:
        return json.load(f)


def _resolve_roles(roles, new):
    """role file -> {sheet: {role: key or [keys]}} with region tuples, 'grid' expanded"""
    def key(sheet, n):
        return (sheet, drpgmap.LOOSE, int(n))
    out = {}
    order = {s: grid_order([k for k in new if k[0] == s]) for s in SHEETS}
    for sheet in ("front", "wait_front"):
        r = roles.get(sheet)
        if r == "grid" or r is None:
            out[sheet] = {"idle": order[sheet]} if sheet == "wait_front" else {}
        elif isinstance(r, list):
            out[sheet] = {"idle": [key(sheet, n) for n in r]}
        else:
            out[sheet] = {k: ([key(sheet, n) for n in v] if isinstance(v, list) else key(sheet, v))
                          for k, v in r.items() if not k.startswith("_")}
    for sheet, src in (("back", "front"), ("wait_back", "wait_front")):
        r = roles.get(sheet, "grid")
        if r == "grid":
            pos = {k: i for i, k in enumerate(order[src])}
            dst = order[sheet]

            def conv(k):
                i = pos.get(k)
                return dst[i] if i is not None and i < len(dst) else None
            out[sheet] = {k: ([conv(x) for x in v] if isinstance(v, list) else conv(v)) for k, v in out[src].items()}
        elif isinstance(r, list):
            out[sheet] = {"idle": [key(sheet, n) for n in r]}
        else:
            out[sheet] = {k: ([key(sheet, n) for n in v] if isinstance(v, list) else key(sheet, v))
                          for k, v in r.items() if not k.startswith("_")}
    return out


def pairs_from_roles(fs, cls, uid, roles, roots=None, log=None, why=None):
    """{twin region: new region}: every twin pose gets the new monster's pose of the same role.  Sequences (walk,
    attack, jump, idle) are spread over the template's FREE steps only (poses a higher-priority role does not
    already claim), so a 3-pose attack list maps 1:1 onto a 3-drawing attack.  Poses without a role get the 'other'
    pose (or any pose of the sheet that is no flash frame) most similar in silhouette.  why: dict filled with the
    reason per pose."""
    twin = regions(twin_data(cls)["uid"], roots)
    new = regions(uid, roots)
    r = _resolve_roles(roles, new)
    troles = twin_roles(fs, cls)
    named = {v for s in r.values() for x in s.values() for v in (x if isinstance(x, list) else [x]) if v}
    free = {}
    for k, rs in troles.items():
        if rs:
            view, role, step = rs[0]
            free.setdefault((view, role), []).append((step, k))
    for v in free.values():
        v.sort()
    free_idx = {vr: {k: i for i, (s, k) in enumerate(v)} for vr, v in free.items()}
    why = {} if why is None else why
    out = {}
    for k, rs in troles.items():
        sheet = k[0]
        pick = None
        for view, role, step in rs:
            if k not in free_idx.get((view, role), {}):
                continue                                  # claimed by a higher-priority role
            i, n = free_idx[(view, role)][k], len(free[(view, role)])
            for pool in (r.get(sheet, {}), r.get(PARTNER[sheet], {})):   # this sheet's roles, then its partner's
                v = pool.get(role)                                        # (Dragon King's back stand: wait sheet)
                if isinstance(v, list) and [x for x in v if x]:
                    v = [x for x in v if x]
                    pick = v[min(len(v) - 1, i * len(v) // max(1, n))]
                elif v is not None and not isinstance(v, list):
                    pick = v
                if pick is not None:
                    break
            if pick is not None:
                why[k] = f"{view}:{role}{i + 1}/{n}"
                break
        if pick is None:
            ws = {x: white_share(new[x]["img"]) for x in new if x[0] == sheet}
            med = float(np.median(list(ws.values()))) if ws else 0.0
            cand = [x for x in (r.get(sheet, {}).get("other") or []) if x] or \
                   [x for x in ws if x in named or ws[x] < max(FLASH, 10 * med)]
            if cand:
                ts = _silhouette(twin[k]["img"])
                pick = max(cand, key=lambda c: _iou(ts, _silhouette(new[c]["img"])))
                why[k] = "shape"
        if pick is not None:
            out[k] = pick
    if log:
        for k in sorted(out, key=lambda k: (SHEETS.index(k[0]), k[2])):
            log(f"  {k[0]:10s} {k[2]:6d} -> {out[k][0]:10s} {out[k][2]:6d}  {why.get(k, '')}")
    return out


def pose_sheet(fs, cls, uid, pairs, path, roots=None):
    """picture of the pairing: per twin pose (with its roles) the new monster's pose next to it"""
    from PIL import Image, ImageDraw
    twin = regions(twin_data(cls)["uid"], roots)
    new = regions(uid, roots)
    roles = twin_roles(fs, cls)
    cell = 150
    keys = sorted(pairs, key=lambda k: (SHEETS.index(k[0]), role_names(roles.get(k, []))))
    sheet = Image.new("RGB", (cell * 2 + 220, (cell + 4) * len(keys)), (30, 30, 50))
    d = ImageDraw.Draw(sheet)
    for i, k in enumerate(keys):
        y = i * (cell + 4)
        for j, img in enumerate((twin[k]["img"], new[pairs[k]]["img"])):
            im = Image.fromarray(img)
            im.thumbnail((cell, cell))
            sheet.paste(im, (j * cell + (cell - im.width) // 2, y + cell - im.height), im)
        d.text((2 * cell + 8, y + 8), f"{k[0]} {k[2]} -> {pairs[k][2]}", fill=(255, 255, 0))
        d.text((2 * cell + 8, y + 26), role_names(roles.get(k, []))[:34], fill=(200, 200, 255))
    sheet.save(path)
    return path


def save_pairs(pairs, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({f"{k[0]}:{k[2]}": f"{v[0]}:{v[2]}" for k, v in pairs.items()}, f, indent=1)


def load_pairs(path):
    with open(path) as f:
        d = json.load(f)

    def k(s):
        a, b = s.split(":")
        return (a, drpgmap.LOOSE, int(b))
    return {k(a): k(b) for a, b in d.items()}


# ------------------------------------------------------------------------------------------ geometry
def _cell_rgba(base, cell, cache):
    key = (cell.tex, cell.pal)
    if key not in cache:
        cache[key] = np.asarray(anm.texture_to_image(base, cell.tex, cell.pal))
    return cache[key][cell.y:cell.y + cell.h, cell.x:cell.x + cell.w]


def placement_fit(base, twin, cid, p, cache):
    """(alpha IoU, mean colour error, aspect of the D5 art) of the twin drawing, placed as the twin map says, against
    the D5 cell's own art"""
    art = _cell_rgba(base, base.blocks[0].cells[-cid], cache)
    r = drpgmap.cell_image(twin, p)
    if r is None:
        return 0.0, 255.0, 1.0
    timg, (dx, dy) = r
    H, W = art.shape[:2]
    can = np.zeros((H, W, 4), np.uint8)
    x0, y0, x1, y1 = max(0, dx), max(0, dy), min(W, dx + timg.shape[1]), min(H, dy + timg.shape[0])
    if x1 > x0 and y1 > y0:
        can[y0:y1, x0:x1] = timg[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    a, b = art[..., 3] >= 128, can[..., 3] >= 128
    both = a & b
    err = float(np.abs(art[both][:, :3].astype(int) - can[both][:, :3].astype(int)).mean()) if both.any() else 255.0
    ys, xs = np.nonzero(a)
    aspect = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1) if len(ys) else 1.0
    return float(both.sum() / max(1, (a | b).sum())), err, float(aspect)


def is_pose2(p, fit=None):
    """is_pose, minus turned placements that are not the same drawing as the D5 cell: not exact, outline overlap with
    the D5 art < ROT_MIN_IOU and colour error > ROT_COLOUR_ERR, and the art doesn't lie down.  Dragon King's charge
    pose (1511 / 4021), rearing pose (4027) and dash (1501) were 'matched' to other poses turned 90 degrees (overlap
    0.61, colour error 65), which drew the new monster lying on its side.  Real turned drawings are exact, or overlap
    well (Prinny's spin: 0.75-0.89, shaded differently in DRPG), or have little colour error (Bear, Orc)."""
    if not is_pose(p):
        return False
    if p["k"] % 4 and not p.get("exact"):
        return fit is not None and (fit[0] >= ROT_MIN_IOU or fit[1] <= ROT_COLOUR_ERR or fit[2] >= LYING)
    return True


def ground_point(img, alpha=128):
    """(x, y) of a drawing's ground point: x centroid of its silhouette eroded by 8% of its height (tails, wing tips
    and flame wisps drop out), y = one below the bottom row"""
    a = img[..., 3] >= alpha
    ys, xs = np.nonzero(a)
    if not len(ys):
        return None
    h = ys.max() - ys.min() + 1
    core = ndimage.distance_transform_edt(a) >= max(3, int(0.08 * h))
    cy, cx = np.nonzero(core)
    x = float(cx.mean()) if len(cx) else float(xs.mean())
    return x, float(ys.max() + 1)


def feet_mask(img, frac=0.12):
    a = img[..., 3] >= 128
    ys, xs = np.nonzero(a)
    band = max(8, int(frac * (ys.max() - ys.min() + 1)))
    m = a.copy()
    m[: ys.max() - band + 1] = False
    return m


def register_feet(A, B, search=30):
    """(dx, dy, iou): shift to add to drawing B, bottom-left aligned with A, so that B's feet band (the bottom 12%
    of the silhouette) lies best on A's.  Idle drawings stand on the same feet."""
    ma, mb = feet_mask(A), feet_mask(B)
    H = max(A.shape[0], B.shape[0]) + 2 * search
    W = max(A.shape[1], B.shape[1]) + 2 * search
    ca = np.zeros((H, W), bool)
    ca[H - search - A.shape[0]:H - search, search:search + A.shape[1]] = ma
    ya, xa = np.nonzero(ca)
    best = (-1.0, 0, 0)
    cb = np.zeros((H, W), bool)
    for dy in range(-6, 7):
        y0 = H - search - B.shape[0] + dy
        if y0 < 0 or y0 + B.shape[0] > H:
            continue
        for dx in range(-search, search + 1):
            x0 = search + dx
            if x0 < 0 or x0 + B.shape[1] > W:
                continue
            cb[:] = False
            cb[y0:y0 + B.shape[0], x0:x0 + B.shape[1]] = mb
            s = (ca & cb).sum() / max(1, (ca | cb).sum())
            if s > best[0]:
                best = (float(s), dx, dy)
    return best[1], best[2], best[0]


# ------------------------------------------------------------------------------------------ build
def build(fs, uid, template_cls, sprite_id, pairs, variants=None, log=print, roots=None, roles=None, keep_fx=None):
    """DRPG monster `uid` -> sprite `sprite_id` with all of vanilla monster `template_cls`'s animations, each cell
    showing the new monster's pose of the same role -> (AnmFile, report)

    * ground: the new drawing's ground point (ground_point) stands on the ground point of the template's own D5 cell
      art (flame-free); the twin drawing only when the cell art is cut off at its bottom; a drawing that IS the twin
      drawing (rebuild, colour variant) keeps the twin map's exact placement
    * turned twin placements that are not the same drawing are rejected (is_pose2) and rescued (_rescuer)
    * gaps where the template draws a part hold the layer's previous pose (_hold)
    * idle loops show every wait drawing of the role file (roles; default data/monster_roles/<uid>.json, else the
      wait sheets in reading order), feet planted (_idle_cycles)
    * breath: a template with data/monster_fx/<template>.json "breath" (Dragon King) keeps its breath layers, aimed
      at the new monster's mouth (role file "mouth"); keep_fx=False leaves them out, keep_fx=True (templates
      without breath data) keeps every effect-only layer of the attacks / skills where the template had it"""
    from . import ownanim
    d = twin_data(template_cls)
    pl = {int(c): p for c, p in d["map"].items()}
    base = anm.parse(fs.read(sprites.sprite_vpath(fs, template_cls, "EN")))
    empty = anm.AnmBlock(1)
    b, own_ids = ownanim._merge(empty, base.blocks[0])
    twin = regions(d["uid"], roots)
    new = regions(uid, roots)
    if roles is None:
        roles = load_roles(role_path(uid)) if os.path.exists(role_path(uid)) else {}
    frames, matches, hidden = [], {}, []
    frame_of, cache, gp_new, cell_gp, turned = {}, {}, {}, {}, {}
    frame_src, cell_twin = {}, {}      # frame -> (new region key, mirror, k, crop origin); cell -> twin placement

    def new_frame(nkey, mirror, k):
        fk = (nkey, mirror, k)
        if fk not in frame_of:
            nimg = drpgmap._untransform(new[nkey]["img"], mirror, k)
            ys, xs = np.nonzero(nimg[..., 3] > 0)
            nimg = np.ascontiguousarray(nimg[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
            frame_of[fk] = len(frames)
            frames.append(dict(rgba=nimg))
            gp_new[frame_of[fk]] = ground_point(nimg)
            frame_src[frame_of[fk]] = (nkey, mirror, k, (int(xs.min()), int(ys.min())))
        return frame_of[fk]

    for cid in sorted({k.cell for k in b.keys if k.cell}):
        p = pl.get(cid)
        fit = placement_fit(base, twin, cid, p, cache) if p is not None and p["k"] % 4 and is_pose(p) else None
        if fit is not None:
            turned[cid] = dict(decision="kept" if is_pose2(p, fit) else "rejected", colour_err=round(fit[1], 1),
                               aspect=round(fit[2], 2))
        if not is_pose2(p, fit):
            hidden.append(cid)
            continue
        tkey = _key(p["region"])
        nkey = pairs.get(tkey)
        r = drpgmap.cell_image(twin, p)
        if nkey is None or nkey not in new or r is None:
            hidden.append(cid)
            continue
        timg, (dx, dy) = r
        fi = new_frame(nkey, p["mirror"], p["k"])
        nimg = frames[fi]["rgba"]
        ts, ns = _silhouette(timg), _silhouette(nimg)
        if _iou(ts, ns) >= 0.9 and abs(timg.shape[0] - nimg.shape[0]) <= 2:
            gx, gy = dx + timg.shape[1] / 2, dy + timg.shape[0]          # the twin drawing itself: exact place
            nx, ny = nimg.shape[1] / 2, nimg.shape[0]
        else:
            cimg = _cell_rgba(base, base.blocks[0].cells[-cid], cache)
            g = ground_point(cimg)
            tg = ground_point(timg)
            if g is None or (g[1] >= cimg.shape[0] - 1 and dy + tg[1] - g[1] > 12):
                g = (dx + tg[0], dy + tg[1])     # cell art cut off at its bottom (upper part of a pose in pieces)
            gx, gy = g
            nx, ny = gp_new[fi]
        cell_gp[cid] = (gx, gy)
        cell_twin[cid] = p
        matches[cid] = dict(frame=fi, dx=int(round(gx - nx)), dy=int(round(gy - ny)))
    rescue_one, rescued = _rescuer(b, base, pl, twin, pairs, matches, new_frame, gp_new, cache, hidden)
    for cid in [c for c, t in turned.items() if t["decision"] == "rejected"]:
        rescue_one(cid)
    held = _hold(b, base, matches, gp_new, cache, rescue_one)
    for cid in rescued:
        if cid in turned:
            turned[cid]["decision"] = "rescued"
    breath = load_fx(template_cls).get("breath") if keep_fx is not False else None
    aimed = None
    if breath:
        cells = {-abs(int(c)) for c in breath["cells"]}
        mouths = roles.get("mouth") or {}
        if not mouths:
            if log:
                log(f"  no mouth points for {uid} (role file 'mouth'): the template's breath is left out")
            kept = []
        else:
            kept = _keep_fx(b, base, pl, matches, frames, cache, only=cells)
            aimed = _aim_breath(b, matches, frames, cell_twin, frame_src, twin, new, cells,
                                _mouth_table(breath.get("mouth")), _mouth_table(mouths), base, cache,
                                set(breath.get("fade_behind_mouth") or ()))
            if log and aimed["missing"]:
                log(f"  breath: no mouth point for {sorted(aimed['missing'])} (template twin 't:' / new 'n:'); "
                    f"(the breath is aimed at its first moment that has both)")
    else:
        kept = _keep_fx(b, base, pl, matches, frames, cache) if keep_fx else []
    idle = {}
    if int(uid) != int(d["uid"]):       # the twin itself already plays its own idle drawings
        idle = _idle_cycles(b, pl, matches, _resolve_roles(roles, new), new_frame, frames, gp_new, cell_gp,
                            idle_anims(b, pl, twin_roles(fs, template_cls)))
    out = ownanim.assemble(b, base.blocks[0], base, frames, matches, sprite_id, variants)
    rep = dict(cells=len(matches), hidden=len(hidden), frames=len(frames), held=held, rescued=rescued, idle=idle,
               turned=turned, fx_kept=len(kept), breath=aimed)
    if log:
        log(f"DRPG monster {uid} on {template_cls}'s animations: {len(matches)} cells drawn, {len(hidden)} hidden "
            f"(parts of a pose or unmatched), {len(frames)} drawings; idle {idle}; "
            f"turned placements {sum(t['decision'] != 'kept' for t in turned.values())} replaced")
    return out, rep


def _rescuer(b, base, pl, twin, pairs, matches, new_frame, gp_new, cache, hidden):
    """-> (rescue_one(cid) -> bool, {cell: what it got}).  A body cell without a usable twin pose (a rejected turned
    placement, or a weak match at a moment no earlier pose can be held: a static animation, a layer's first key) gets
    the new pose paired with the twin pose whose silhouette best matches the D5 cell's own art (upright, in the view's
    facing), standing on the cell's ground point.  Dragon King: the charge pose of 1511 / 4021, the rearing 4027."""
    views = {}
    for an in b.animations:
        for ni, depth, parent in b.walk(an.root):
            for k in b.node_keys(b.nodes[ni]):
                if k.cell:
                    views.setdefault(k.cell, set()).add("f" if an.id % 10 == 1 else "b")
    fam = {"f": ("front", "wait_front"), "b": ("back", "wait_back")}
    cand = [k for k in pairs if k in twin]
    mvote = {"f": [0, 0], "b": [0, 0]}          # the mirror most upright whole poses of a view use = its facing
    for q in pl.values():
        if is_pose(q) and not q["k"] % 4:
            mvote["f" if q["region"][0] in fam["f"] else "b"][q["mirror"]] += 1
    facing = {v: int(m[1] > m[0]) for v, m in mvote.items()}
    sil, out = {}, {}

    def rescue_one(cid):
        p = pl.get(cid)
        if cid in matches:
            return True
        if p is None or not (0.5 <= p["part"] <= 1.3) or cid not in hidden:
            return False
        art = _cell_rgba(base, base.blocks[0].cells[-cid], cache)
        if (art[..., 3] >= 128).sum() < 2000:
            return False
        vs = views.get(cid, set())
        view = next(iter(vs)) if len(vs) == 1 else ("f" if p["region"][0] in fam["f"] else "b")
        a0 = _silhouette(art)
        best = None
        mir = facing[view]
        for tk in cand:
            if tk[0] not in fam[view]:
                continue
            if (tk, mir) not in sil:
                sil[(tk, mir)] = _silhouette(twin[tk]["img"][:, ::-1] if mir else twin[tk]["img"])
            s = _iou(a0, sil[(tk, mir)])
            if best is None or s > best[0]:
                best = (s, tk)
        if best is None:
            return False
        fi = new_frame(pairs[best[1]], mir, 0)
        g = ground_point(art)
        nx, ny = gp_new[fi]
        matches[cid] = dict(frame=fi, dx=int(round(g[0] - nx)), dy=int(round(g[1] - ny)))
        hidden.remove(cid)
        out[cid] = f"{best[1][0]}:{best[1][2]}{'m' if mir else ''} iou {best[0]:.2f}"
        return True
    return rescue_one, out


def _hold(b, base, matches, gp_new, cache, rescue_one=None):
    """A key whose cell has no drawing (a part or an effect layer of the template) would leave a gap in the body.
    The main body layer is handled first.  A hidden cell is held (keeps showing the layer's previous pose) unless
    another layer shows a pose at that moment (Dragon King 1501 t12: two dragons) or the cell has (almost) no art;
    the held drawing stands on the hidden cell's own ground point, so hops and dashes keep their motion.  Hiding small
    part cells instead was tried: it blanked the monster in skill animations of 2050 / 2110 / 2140 / 2190.  A layer's
    first key with nothing earlier to hold is rescued.
    -> {anim id: number of held keys}"""
    area, synth, held = {}, {}, {}

    def art_area(cid):
        if cid not in area:
            c = base.blocks[0].cells[-cid] if cid < 0 and -cid < len(base.blocks[0].cells) else None
            area[cid] = 0 if c is None or not c.w else int((_cell_rgba(base, c, cache)[..., 3] >= 128).sum())
        return area[cid]

    for an in b.animations:
        nodes = [ni for ni, depth, parent in b.walk(an.root) if b.nodes[ni].first_key >= 0 and b.nodes[ni].num_keys]

        def shown_by_other(ni, t):
            for nj in nodes:
                if nj != ni:
                    act = [k for k in b.node_keys(b.nodes[nj]) if k.time <= t]
                    if act and act[-1].cell in matches:
                        return True
            return False

        nodes.sort(key=lambda nj: -sum(1 for k in b.node_keys(b.nodes[nj]) if k.cell in matches))
        for ni in nodes:
            n = b.nodes[ni]
            last = None
            for k in b.keys[n.first_key:n.first_key + n.num_keys]:
                if not k.cell:
                    last = None
                elif k.cell in matches:
                    last = (k.cell, matches[k.cell]["frame"])
                elif last is None:
                    if rescue_one is not None and not shown_by_other(ni, k.time) and rescue_one(k.cell):
                        last = (k.cell, matches[k.cell]["frame"])
                else:
                    if art_area(k.cell) < HOLD_MIN_PX or shown_by_other(ni, k.time):
                        k.cell = 0          # hidden here; the pose is still held at the layer's later gaps
                        continue
                    fi = last[1]
                    if (k.cell, fi) not in synth:
                        g = ground_point(_cell_rgba(base, base.blocks[0].cells[-k.cell], cache))
                        nx, ny = gp_new[fi]
                        sid = -(800000 + len(synth))
                        matches[sid] = dict(frame=fi, dx=int(round(g[0] - nx)), dy=int(round(g[1] - ny)))
                        synth[(k.cell, fi)] = sid
                    k.cell = synth[(k.cell, fi)]
                    held[an.id] = held.get(an.id, 0) + 1
    return held


def idle_anims(b, pl, troles):
    """{anim id: 'f' / 'b'}: the idle loops = looping animations showing at least two whole poses, all of them the
    template's stand / idle poses (1001 / 1007 everywhere, 1051 / 1057 on Dragon King; Prinny's 1051 spin is not)"""
    calm = {k for k, rs in troles.items() if any(r[1] in ("stand", "idle") for r in rs)}
    idle = {k for k, rs in troles.items() if any(r[1] == "idle" for r in rs)}
    out = {}
    for an in b.animations:
        if an.id % 10 not in (1, 7) or not anm.animation_info(b, an)["loop"]:
            continue
        ks = {k for t, k in _anim_poses(b, pl, an)}
        if len(ks) >= 2 and ks <= calm and ks & idle:
            out[an.id] = "f" if an.id % 10 == 1 else "b"
    return out


def _idle_cycles(b, pl, matches, r, new_frame, frames, gp_new, cell_gp, anims):
    """Idle loops: the body layer shows every wait drawing of its view once, evenly over the loop (the template's
    idle collapses to 2-3 twin poses).  The first drawing stands where the loop's first cell stood, the others on
    its feet (register_feet); keys before the loop start show the first drawing.  Other layers' poses are hidden.
    -> {anim id: [wait region numbers]}"""
    waits = {"f": [x for x in (r.get("wait_front", {}).get("idle") or []) if x],
             "b": [x for x in (r.get("wait_back", {}).get("idle") or []) if x]}
    done, ids = {}, {}
    for an in b.animations:
        view = anims.get(an.id)
        if view is None or len(waits[view]) < 2:
            continue
        info = anm.animation_info(b, an)
        l0, l1 = info["loop"]
        best, bn = None, 0
        for ni, depth, parent in b.walk(an.root):
            c = sum(1 for k in b.node_keys(b.nodes[ni]) if k.cell in matches)
            if c > bn:
                best, bn = ni, c
        if best is None:
            continue
        node = b.nodes[best]
        first = next((k for k in b.node_keys(node) if k.cell in cell_gp), None)
        if first is None:
            continue
        gx, gy = cell_gp[first.cell]
        p0 = pl.get(first.cell)
        mir, kk = (p0["mirror"], p0["k"]) if p0 else (0, 0)
        seq = waits[view]
        fis = [new_frame(n, mir, kk) for n in seq]
        img0 = frames[fis[0]]["rgba"]
        X0, Y0 = gx - gp_new[fis[0]][0], gy - gp_new[fis[0]][1]
        new_keys = []
        for j, fi in enumerate(fis):
            img = frames[fi]["rgba"]
            X, Y = X0, Y0
            if j:
                dx, dy, s = register_feet(img0, img)
                if s >= FEET_IOU:
                    X, Y = X0 + dx, Y0 + img0.shape[0] - img.shape[0] + dy
                else:
                    X, Y = gx - gp_new[fi][0], gy - gp_new[fi][1]
            # a cell id per (drawing, first cell): the placement is relative to that cell's pivot
            cid = ids.setdefault((fi, first.cell, int(round(X)), int(round(Y))), -(900000 + len(ids)))
            matches[cid] = dict(frame=fi, dx=int(round(X)), dy=int(round(Y)))
            k = copy.copy(first)
            k.time = 0 if j == 0 else l0 + int(round(j * (l1 - l0) / len(fis)))
            k.flags = first.flags & ~0xFF
            k.cell = cid
            new_keys.append(k)
        node.first_key, node.num_keys = len(b.keys), len(new_keys)
        b.keys.extend(new_keys)
        for ni, depth, parent in b.walk(an.root):
            if ni != best:
                for k in b.node_keys(b.nodes[ni]):
                    if k.cell in matches:
                        k.cell = 0
        done[an.id] = [x[2] for x in seq]
    return done


FX_ANIM = lambda aid: aid >= 1500       # noqa: E731  attacks / skills (1501.. specials, 2071 attack, 3xxx, 4xxx)
FX_DIR = os.path.join(os.path.dirname(__file__), "data", "monster_fx")


def load_fx(cls):
    """data/monster_fx/<template>.json: the template's effects a new monster keeps.
    {"breath": {"cells": [D5 cell numbers of the breath layers],
                "mouth": {"front:<twin region>": [x, y], ...}}}   the template twin's mouth in its DRPG drawings"""
    p = os.path.join(FX_DIR, f"{int(cls)}.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def _mouth_table(d):
    """{"front:13080": [x, y]} -> {(sheet, 'loose', 13080): (x, y)}"""
    out = {}
    for k, v in (d or {}).items():
        if ":" in k and not k.startswith("_"):
            s, n = k.split(":")
            out[(s, drpgmap.LOOSE, int(n))] = (float(v[0]), float(v[1]))
    return out


def _marker(img, pt):
    m = np.zeros_like(img)
    x, y = int(round(pt[0])), int(round(pt[1]))
    m[max(0, y - 2):y + 3, max(0, x - 2):x + 3] = 255
    return m


def _twin_point(twin, p, pt):
    """cell coordinates of point pt (in the twin's region drawing) when the drawing is placed by twin-map placement p:
    a marker drawn there goes through drpgmap.cell_image exactly like the drawing"""
    key = tuple(p["region"])
    if key[1] == drpgmap.LOOSE:
        key = drpgmap._loose_near(twin, key[0], key[2]) or key
    r = twin.get(key)
    if r is None:
        return None
    res = drpgmap.cell_image({key: dict(r, img=_marker(r["img"], pt))}, dict(p, region=list(key)))
    if res is None:
        return None
    img, (dx, dy) = res
    ys, xs = np.nonzero(img[..., 3])
    return dx + xs.mean(), dy + ys.mean()


def _new_point(new, src, pt):
    """frame coordinates of point pt (in the new monster's region drawing) for frame source (key, mirror, k, crop)"""
    nkey, mirror, k, (x0, y0) = src
    m = drpgmap._untransform(_marker(new[nkey]["img"], pt), mirror, k)
    ys, xs = np.nonzero(m[..., 3])
    return (xs.mean() - x0, ys.mean() - y0) if len(xs) else None


def _states(b, an, t):
    """{node: (parent world matrix, active key, world matrix, pivot)} of animation `an` at frame t"""
    out = {}

    def rec(ni, parent, seen):
        while 0 <= ni < len(b.nodes) and ni not in seen:
            seen.add(ni)
            n = b.nodes[ni]
            ks = b.node_keys(n)
            act, m, piv = None, parent, (0.0, 0.0)
            a = anm._active_key(ks, t) if ks else None
            if a is not None:
                k, nx, f = a
                act = k
                vals, pts, col = anm._key_state(b, n, k, nx, f)
                m = parent @ anm._mat(*vals)
                piv = tuple(pts[0])
            out[ni] = (parent, act, m, piv)
            if (not ks or act is not None) and n.child >= 0:
                rec(n.child, m, seen)
            ni = n.next

    rec(an.root, np.eye(3), set())
    return out


def _aim_breath(b, matches, frames, cell_twin, frame_src, twin, new, cells, tmouth, nmouth, base=None,
                cache=None, fade=()):
    """The template's breath layers come out of the new monster's mouth.  Per animation, the breath layer groups
    (the top-most layers drawing the breath cells) move by (new mouth - template mouth), both taken through the body
    drawing shown at the breath's first moment that has mouth points on both sides (the template's twin drawing and
    the new drawing share the body cell's place, so the shift is that cell-space difference turned into world
    space).  The stream keeps the template's own motion.  -> report {anim id: [(key time, (dx, dy))], 'missing'}"""
    rep = {"missing": set()}
    for an in b.animations:
        par = {ni: p for ni, d, p in b.walk(an.root)}
        show = {ni for ni in par if any(k.cell in cells for k in b.node_keys(b.nodes[ni]))}
        if not show:
            continue

        def under_breath(ni):
            q = par.get(ni)
            while q is not None and q >= 0:
                if q in show:
                    return True
                q = par.get(q)
            return False
        groups = [ni for ni in show if not under_breath(ni)]
        offsets = {}
        times = sorted({k.time for g in groups for k in b.node_keys(b.nodes[g])})
        for t in times:
            st = _states(b, an, t)
            best = None
            for ni, (P, k, M, piv) in st.items():
                if k is None or ni in show or k.cell not in matches or k.cell in cells:
                    continue
                fi = matches[k.cell]["frame"]
                if fi not in frame_src:
                    continue
                area = int((frames[fi]["rgba"][..., 3] > 0).sum())       # the body = the biggest drawing shown
                if best is None or area > best[0]:
                    best = (area, k, M, piv)
            if best is None:
                continue
            area, k, M, piv = best
            p = cell_twin.get(k.cell)
            src = frame_src[matches[k.cell]["frame"]]
            tk = tuple(p["region"]) if p is not None else None
            if tk is None or tk not in tmouth:
                rep["missing"].add(f"t:{tk[0]}:{tk[2]}" if tk else f"t:held cell {k.cell}")
                continue
            if src[0] not in nmouth:
                rep["missing"].add(f"n:{src[0][0]}:{src[0][2]}")
                continue
            tp = _twin_point(twin, p, tmouth[tk])
            npt = _new_point(new, src, nmouth[src[0]])
            if tp is None or npt is None:
                continue
            m = matches[k.cell]
            d_cell = np.array([m["dx"] + npt[0] - tp[0], m["dy"] + npt[1] - tp[1]])
            h, w = frames[m["frame"]]["rgba"].shape[:2]
            mouth = M @ np.array([m["dx"] + npt[0] - piv[0], m["dy"] + npt[1] - piv[1], 1.0])
            centre = M @ np.array([m["dx"] + w / 2 - piv[0], m["dy"] + h / 2 - piv[1], 1.0])
            offsets[t] = (M[:2, :2] @ d_cell, mouth[:2], centre[:2])
        if not offsets:
            continue
        # one aim per animation, at the breath's first moment: the stream then moves exactly as the template's
        # (re-aiming at every key made it jump when the body changed drawing mid-breath, Dragon King 4017 t10)
        off, mouth, centre = offsets[min(offsets)]
        done = []
        for g in groups:
            n = b.nodes[g]
            for ki in range(n.first_key, n.first_key + n.num_keys):
                key = b.keys[ki]
                P = _states(b, an, key.time)[g][0]
                dl = np.linalg.solve(P[:2, :2], off) if abs(np.linalg.det(P[:2, :2])) > 1e-9 else off
                xf = b.transforms[key.xform]
                b.transforms.append(anm.Transform(int(round(xf.x + dl[0])), int(round(xf.y + dl[1])), xf.pivot, xf.unk,
                                                  xf.sx, xf.sy, xf.rot))
                key.xform = len(b.transforms) - 1
                done.append((key.time, tuple(int(round(v)) for v in off)))
        rep[an.id] = done
        if an.id in fade:
            forward = 1.0 if mouth[0] >= centre[0] else -1.0
            rep.setdefault("faded", {})[an.id] = _fade_behind(b, an, show, cells, matches, frames, base, cache, mouth,
                                                              forward)
    return rep


FADE_ZERO_BEHIND = 8       # px behind the mouth where the breath has faded out ...
FADE_FULL_AHEAD = 20       # ... and in front of it where it shows fully: the fire emerges from the mouth
FADE_CONE = 0.6            # px further ahead per px above / below the mouth: the fire opens out from the mouth like a
                           # cone instead of starting at a straight edge (the game blends it additively: a straight
                           # faded edge still shows as a line)


def _fade_behind(b, an, show, cells, matches, frames, base, cache, mouth, forward):
    """The breath part behind the mouth (a torrent trailing back over the template's head and shoulders) fades out,
    so the fire visibly starts at the new monster's mouth: every breath key of the animation gets a copy of its cell
    art whose pixels fade by their world x behind the mouth (forward = +1 facing right, -1 facing left).  Breath
    keys are steps (no tweens, no meshes), so one copy per key is exact.  -> keys changed"""
    copies, changed = {}, 0
    for ni in show:
        n = b.nodes[ni]
        for ki in range(n.first_key, n.first_key + n.num_keys):
            key = b.keys[ki]
            if key.cell not in cells:
                continue
            st = _states(b, an, key.time)
            P, act, M, piv = st[ni]
            c = base.blocks[0].cells[-key.cell]
            if not c.w or not c.h:
                continue
            sig = (key.cell, tuple(np.round(M[:2].ravel(), 3)), piv)
            if sig not in copies:
                art = _cell_rgba(base, c, cache).copy()
                h, w = art.shape[:2]
                xs = np.arange(w)[None, :] - piv[0]
                ys = np.arange(h)[:, None] - piv[1]
                wx = M[0, 0] * xs + M[0, 1] * ys + M[0, 2]
                wy = M[1, 0] * xs + M[1, 1] * ys + M[1, 2]
                ahead = (wx - mouth[0]) * forward - FADE_CONE * np.abs(wy - mouth[1])
                f = np.clip((ahead + FADE_ZERO_BEHIND) / (FADE_ZERO_BEHIND + FADE_FULL_AHEAD), 0.0, 1.0)
                if f.min() >= 1.0:
                    copies[sig] = key.cell
                elif not (art[..., 3] * f > 8).any():
                    copies[sig] = 0
                else:
                    art[..., 3] = (art[..., 3] * f).astype(np.uint8)
                    frames.append(dict(rgba=np.ascontiguousarray(art)))
                    sid = -(700000 + len([s for s in matches if -800000 < s <= -700000]))
                    matches[sid] = dict(frame=len(frames) - 1, dx=0, dy=0)
                    copies[sig] = sid
            if copies[sig] != key.cell:
                key.cell = copies[sig]
                changed += 1
    return changed


def _keep_fx(b, base, pl, matches, frames, cache, only=None):
    """the template's own effect layers (Dragon King's fire breath, flame bursts) in attack / skill animations stay
    as they are: cells that are not a pose, used ONLY by attack / skill animations, and not drawn in the body's own
    colours (Dragon King's horns have their own layers).  only: exactly these (merged, negative) cells instead"""
    if only is not None:
        kept = []
        for cid in sorted(only):
            if cid in matches or -cid >= len(base.blocks[0].cells):
                continue
            c = base.blocks[0].cells[-cid]
            if not c.w or not c.h:
                continue
            frames.append(dict(rgba=np.ascontiguousarray(_cell_rgba(base, c, cache))))
            matches[cid] = dict(frame=len(frames) - 1, dx=0, dy=0)
            kept.append(cid)
        return kept
    used = {}
    for an in b.animations:
        for ni, depth, parent in b.walk(an.root):
            for k in b.node_keys(b.nodes[ni]):
                if k.cell:
                    used.setdefault(k.cell, set()).add(an.id)
    cnt, tot = Counter(), 0
    for cid, p in pl.items():
        if is_pose(p) and -cid < len(base.blocks[0].cells):
            q = _cell_rgba(base, base.blocks[0].cells[-cid], cache)
            q = q[q[..., 3] >= 128][:, :3]
            cnt.update(map(tuple, q))
            tot += len(q)
    body = {c for c, n in cnt.items() if n > 0.003 * max(1, tot)}
    kept = []
    for cid, aids in used.items():
        if cid in matches or cid >= 0 or -cid >= len(base.blocks[0].cells):
            continue
        p = pl.get(cid)
        if (p is not None and p["part"] <= 1.3) or not all(FX_ANIM(a) for a in aids):
            continue
        c = base.blocks[0].cells[-cid]
        if not c.w or not c.h:
            continue
        art = _cell_rgba(base, c, cache)
        if (art[..., 3] > 0).sum() < 10:
            continue
        q = art[art[..., 3] >= 128][:, :3]
        if len(q) and np.mean([tuple(x) in body for x in q]) > 0.5:
            continue
        frames.append(dict(rgba=np.ascontiguousarray(art)))
        matches[cid] = dict(frame=len(frames) - 1, dx=0, dy=0)
        kept.append(cid)
    return kept
