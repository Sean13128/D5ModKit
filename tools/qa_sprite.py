"""Automatic QA for a built monster / class sprite against its vanilla template.  Run it after every build.

    python tools/qa_sprite.py BUILT TEMPLATE [--class] [--out NAME] [--ids 1,7,11,...]

BUILT     path of the built sprite (anmNNNNN.lzs in a mod, or raw anm bytes)
TEMPLATE  vanilla sprite number the build took its animations from (2180 Dragon King, 1060 Fight Mistress ...)
--class   humanoid class: the template's shared motions come from anm_resident block 1 (bind_motion_set) and its
          own animations (6001/6007, 7xxx) from its own file; the built class sprite carries the merged set itself

Errors (each animation, sampled at every key time of the template and the build):
  missing     template animation ids the build lacks (the engine waits for an animation that never ends -> stalls)
  control     control-track differences (loop / event / end commands and their times)
  blank       frames where the template draws a body but the build draws (almost) nothing
  ground      the built drawing's ground point jumps between consecutive frames by more than GROUND_JUMP px when the
              template's own does not
  feet        in-place loops (idles): the feet band of a frame, registered onto the loop's first frame, moved more
              than FEET_SLIDE px (independent of the ground point rule the monster build uses)
  idle        fewer distinct drawings in an idle loop than min(template, 4)
  doubled     two or more body-sized layers at once where the template draws one (two monsters overlapping)
  collapse    a non-idle animation keeping 1/3 or fewer of the template's distinct body drawings
  detached    pieces of the built frame not connected to the body (floating hand, stray arm)
  flash       built frames that are mostly near-white where the template's are not (DRPG flash frames as poses)
  parts       (classes) a minor layer - hand, forearm - whose built drawing shrank to < 45% of the template's or
              moved > 24 px: a hand without its arm floating over the body
Warnings: repeat (the build holds a drawing where the template changes), scale (body height outliers).
Classes: ground, feet and parts findings are often just the new drawing's own shape (legs stepping where the
template glides in a long skirt, a thin arm where the template has a wide sleeve, an idle that shifts its weight).
Look at the flagged frames in the .png before changing anything.
Turned placements (a monster lying on its side) can't be seen in renders: the monster build reports them.
Writes <out>.json (all findings) and <out>.png (the flagged frames, template above build) into cache/qa/.
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import anm, modsys, sprites       # noqa: E402
from d5lib.gamefs import GameFS              # noqa: E402

OUT = os.path.join(KIT, "cache", "qa")
_fs = None


def fs():
    global _fs
    if _fs is None:
        game = paths.require_game_dir()
        _fs = GameFS(game, backup_resolver=modsys.Installer(game, KIT, log=lambda *a: None).backup_resolver)
    return _fs


BOUNDS = (-320, -440, 320, 140)
ALPHA = 128              # opaque enough to count (shadows are index 1 = alpha 128)
BLANK_MIN = 300          # px: less than this = nothing drawn
GROUND_JUMP = 6          # px
DETACH_AREA = 120        # px
DETACH_GAP = 4           # px
IDLE_IDS = (1001, 1007, 1051, 1057, 6001, 6007)
FLASH = 0.03             # share of near-white pixels (and >= 10x the view's median): a DRPG flash frame as a pose
FEET_SLIDE = 3           # px


# ------------------------------------------------------------------------------------------ loading
class View:
    """id -> (AnmFile, flat index) for rendering"""

    def __init__(self, files):
        self.at = {}
        for a in files:
            for x in anm.list_animations(a):
                self.at.setdefault(x["id"], (a, x))

    def ids(self):
        return sorted(self.at)

    def info(self, aid):
        return self.at[aid][1]

    def block(self, aid):
        a, x = self.at[aid]
        return a.blocks[x["block"]], a.blocks[x["block"]].animations[x["anim"]]

    def times(self, aid):
        a, x = self.at[aid]
        return anm.frame_times(a, x["index"])

    def render(self, aid, t, skip=()):
        """(RGBA array, draw items) at frame t; layers (node indices) in `skip` are left out (effects)"""
        a, x = self.at[aid]
        items = [it for it in anm.evaluate(a, x["index"], t) if it.node not in skip]
        img, origin = anm.render_items(a, items, 0, bounds=BOUNDS)
        return np.asarray(img), items

    def render_node(self, aid, items, node):
        """the item drawn by layer `node` alone (a monster template's body cell without its effect layers)"""
        a, x = self.at[aid]
        sel = [it for it in items if it.node == node]
        if not sel:
            return None
        img, origin = anm.render_items(a, sel, 0, bounds=BOUNDS)
        return np.asarray(img)


def _largest(items):
    best, area = None, 0
    for it in items:
        q = it.quad
        ar = abs((q[1][0] - q[0][0]) * (q[3][1] - q[0][1]) - (q[1][1] - q[0][1]) * (q[3][0] - q[0][0]))
        if ar > area:
            best, area = it, ar
    return best


def template_view(num, humanoid):
    base = anm.parse(fs().read(sprites.sprite_vpath(fs(), num, "EN")))
    if humanoid or sprites.needs_motion_set(base):
        motion = anm.bind_motion_set(anm.AnmFile([sprites.motion_block(fs(), 1)], [], []), 0, base)
        return View([base, motion])          # own ids first (6001/6007/7xxx), then the shared motions
    return View([base])


def built_view(path):
    data = open(path, "rb").read() if isinstance(path, str) else path
    try:
        a = anm.load(data)
    except Exception:
        a = anm.parse(data)
    return View([a])


# ------------------------------------------------------------------------------------------ measures
def measure(img):
    """alpha mask -> dict(area, bottom, foot_x, top, height, comps=[(area, bbox, gap)], hash)"""
    m = img[..., 3] >= ALPHA
    area = int(m.sum())
    ox, oy = -BOUNDS[0], -BOUNDS[1]
    if area < 20:
        return dict(area=area)
    ys, xs = np.nonzero(m)
    bottom = int(ys.max())
    # horizontal ground point: x centroid of the silhouette eroded by 8% of its height (the body without tail,
    # wing tips, flames; stable when a foot lifts - see anchor_eval.py)
    core = ndimage.distance_transform_edt(m) >= max(3, int(0.08 * (bottom - ys.min() + 1)))
    cx = np.nonzero(core)[1]
    foot_x = float(cx.mean()) if len(cx) else float(xs.mean())
    lab, n = ndimage.label(ndimage.binary_dilation(m, iterations=1))
    lab = lab * m
    sizes = ndimage.sum(m, lab, range(1, n + 1)) if n else []
    comps = []
    if n > 1:
        main = int(np.argmax(sizes)) + 1
        main_mask = lab == main
        dist = ndimage.distance_transform_edt(~main_mask)
        for i, s in enumerate(sizes, 1):
            if i == main or s < DETACH_AREA:
                continue
            cm = lab == i
            gap = float(dist[cm].min())
            if gap < DETACH_GAP:
                continue
            cy, cx = np.nonzero(cm)
            comps.append((int(s), (int(cx.min()) - ox, int(cy.min()) - oy, int(cx.max()) - ox, int(cy.max()) - oy),
                          round(gap, 1)))
    white = float(((img[..., :3].min(axis=2) > 200) & m).sum() / max(1, area))
    small = np.asarray(Image.fromarray(img).resize((img.shape[1] // 4, img.shape[0] // 4)))
    h = hashlib.md5((small // 24).tobytes()).hexdigest()[:10]
    return dict(area=area, bottom=bottom - oy, foot_x=round(foot_x - ox, 1), top=int(ys.min()) - oy,
                height=bottom - int(ys.min()), comps=comps, hash=h, white=round(white, 3))


def control(view, aid):
    b, an = view.block(aid)
    return [(k.time, k.flags & 0xFF) for k in b.node_keys(b.nodes[an.root])]


# ------------------------------------------------------------------------------------------ QA
def _item_mask(view, aid, it):
    a, x = view.at[aid]
    img, _ = anm.render_items(a, [it], 0, bounds=BOUNDS)
    return np.asarray(img)[..., 3] >= ALPHA


def _bodies(view, aid, items):
    """number of body-sized layers (>= 40% of the largest and >= 3000 px) drawn at once"""
    areas = [int(_item_mask(view, aid, it).sum()) for it in items]
    big = max(areas) if areas else 0
    return sum(1 for a in areas if big and a >= 0.4 * big and a >= 3000)


def _band(m):
    ys, xs = np.nonzero(m)
    out = m.copy()
    out[: ys.max() - max(8, int(0.12 * (ys.max() - ys.min() + 1))) + 1] = False
    return out


def feet_shift(A, B, search=20):
    """(dx, dy, iou): how far frame B's feet band (bottom 12% of the silhouette) lies from frame A's (same canvas)"""
    a, b = _band(A), _band(B)
    ya, xa = np.nonzero(a)
    y0, y1 = max(0, ya.min() - 10), ya.max() + 10
    x0, x1 = max(0, xa.min() - search - 10), xa.max() + search + 10
    a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    best = (-1.0, 0, 0)
    for dy in range(-6, 7):
        for dx in range(-search, search + 1):
            s = np.roll(np.roll(b, dy, 0), dx, 1)
            iou = (a & s).sum() / max(1, (a | s).sum())
            if iou > best[0]:
                best = (float(iou), dx, dy)
    return -best[1], -best[2], best[0]


def part_check(tmpl, built, aid, titems, bitems, minor=0.4, shrink=0.45, shift=24):
    """layers drawn from parts (humanoid classes): a minor layer (hand, forearm, weapon arm) whose built drawing
    shrank to under `shrink` of the template's (the arm is gone, a hand floats: Beast Master 6007 fist over the
    hair) or whose centre moved more than `shift` px.  Layers are paired by node (the build keeps the template's
    node tree; own animations are offset by the motion block's node count = the difference of the roots)."""
    tb, tan = tmpl.block(aid)
    bb, ban = built.block(aid)
    off = ban.root - tan.root
    tm = {it.node: it for it in titems}
    bm = {it.node: it for it in bitems}
    areas = {n: int(_item_mask(tmpl, aid, it).sum()) for n, it in tm.items()}
    big = max(areas.values()) if areas else 0
    out = []
    for n, it in tm.items():
        A = areas[n]
        if not big or A >= minor * big or A < 150 or (n + off) not in bm:
            continue
        mb = _item_mask(built, aid, bm[n + off])
        B = int(mb.sum())
        mt = _item_mask(tmpl, aid, it)
        ty, tx = np.nonzero(mt)
        by, bx = np.nonzero(mb)
        d = float(np.hypot(tx.mean() - bx.mean(), ty.mean() - by.mean())) if B else 0.0
        if B and (B < shrink * A or d > shift):
            out.append(dict(node=int(n), template_px=A, built_px=B, moved=round(d, 1),
                            at=(int(bx.mean()) + BOUNDS[0], int(by.mean()) + BOUNDS[1])))
    return out


def fx_nodes(num):
    """{anim id: node indices} of the template's effect layers a monster build keeps (d5lib/data/monster_fx, e.g.
    Dragon King's fire breath): the build keeps the template's node tree, so the same indices in the built sprite"""
    from d5lib import monstermap
    breath = (monstermap.load_fx(num).get("breath") or {}).get("cells")
    if not breath:
        return {}
    b = anm.parse(fs().read(sprites.sprite_vpath(fs(), num, "EN"))).blocks[0]
    cells = {abs(int(c)) for c in breath}
    out = {}
    for an in b.animations:
        nodes = {ni for ni, d, p in b.walk(an.root) if any(k.cell in cells for k in b.node_keys(b.nodes[ni]))}
        if nodes:
            out[an.id] = nodes
    return out


def qa(built, tmpl, ids=None, log=print, humanoid=False, parts=None, fx=None):
    """fx: {anim id: nodes} of kept effect layers, left out of the built frames' measures (fx_nodes)"""
    parts = humanoid if parts is None else parts
    fx = fx or {}
    rep = dict(missing=sorted(set(tmpl.ids()) - set(built.ids())), extra=sorted(set(built.ids()) - set(tmpl.ids())),
               control=[], blank=[], ground=[], feet=[], idle=[], doubled=[], collapse=[], repeat=[], detached=[],
               scale=[], flash=[], parts=[])
    frames = {}                      # (aid, t) -> (template img, built img) for the contact sheet
    flagged = []
    heights = {}
    whites = {}
    for aid in ids or tmpl.ids():
        if aid not in built.ids():
            continue
        ct, cb = control(tmpl, aid), control(built, aid)
        if ct != cb:
            rep["control"].append(dict(id=aid, template=ct, built=cb))
        ts = sorted(set(tmpl.times(aid)) | set(built.times(aid)))
        L = max(tmpl.info(aid)["length"], built.info(aid)["length"])
        ts = [t for t in ts if t <= max(L, 0)] or [0]
        mt, mb = [], []
        th, bh, masks = set(), set(), []
        for t in ts:
            it, titems = tmpl.render(aid, t)
            ib, bitems = built.render(aid, t, fx.get(aid, ()))
            a, b = measure(it), measure(ib)
            masks.append(ib[..., 3] >= ALPHA)
            if not humanoid:
                nb, nt = _bodies(built, aid, bitems), _bodies(tmpl, aid, titems)
                if nb >= 2 and nb > nt:
                    rep["doubled"].append(dict(id=aid, t=t, built=nb, template=nt))
                    flagged.append((aid, t, "doubled"))
            if not humanoid and titems and bitems:
                # ground reference of a monster template: the layer that carries the built body, drawn alone
                # (the build keeps the template's node tree; flames / effects on other layers are left out)
                big = _largest(bitems)
                body = tmpl.render_node(aid, titems, big.node) if big is not None else None
                g = measure(body) if body is not None else {}
                for k in ("bottom", "foot_x", "hash"):      # body drawing changes, not flame flicker
                    if k in g:
                        a[k] = g[k]
            mt.append(a)
            mb.append(b)
            th.add(a.get("hash"))
            bh.add(b.get("hash"))
            frames[(aid, t)] = (it, ib)
            if a.get("area", 0) >= BLANK_MIN * 3 and b.get("area", 0) < BLANK_MIN:
                rep["blank"].append(dict(id=aid, t=t, template_area=a["area"], built_area=b.get("area", 0)))
                flagged.append((aid, t, "blank"))
            if b.get("white") is not None:
                whites.setdefault(aid % 10, []).append((b["white"], a.get("white", 0), aid, t))
            if b.get("comps"):
                tc = a.get("comps") or []
                extra = [c for c in b["comps"] if not any(abs(c[1][0] - d[1][0]) < 24 and abs(c[1][1] - d[1][1]) < 24
                                                          for d in tc)]
                if extra:
                    rep["detached"].append(dict(id=aid, t=t, pieces=extra))
                    flagged.append((aid, t, "detached"))
            if "height" in b:
                heights.setdefault(aid % 10, []).append((b["height"], aid, t))
            if parts and titems and bitems:
                for f in part_check(tmpl, built, aid, titems, bitems):
                    rep["parts"].append(dict(id=aid, t=t, **f))
                    flagged.append((aid, t, "part"))
        # ground point: built jumps the template does not make
        for i in range(1, len(ts)):
            a0, a1, b0, b1 = mt[i - 1], mt[i], mb[i - 1], mb[i]
            if "bottom" not in b0 or "bottom" not in b1:
                continue
            dbx, dby = b1["foot_x"] - b0["foot_x"], b1["bottom"] - b0["bottom"]
            if "bottom" in a0 and "bottom" in a1:
                dtx, dty = a1["foot_x"] - a0["foot_x"], a1["bottom"] - a0["bottom"]
            else:
                dtx = dty = 0
            ex, ey = dbx - dtx, dby - dty
            if abs(ex) > GROUND_JUMP or abs(ey) > GROUND_JUMP:
                rep["ground"].append(dict(id=aid, t0=ts[i - 1], t1=ts[i], built=(round(dbx, 1), dby),
                                          template=(round(dtx, 1), dty)))
                flagged.append((aid, ts[i], "ground"))
        tn, bn = len(th - {None}), len(bh - {None})
        if aid not in IDLE_IDS and tn >= 4 and bn * 3 <= tn:
            rep["collapse"].append(dict(id=aid, template_distinct=tn, built_distinct=bn))
        if aid in IDLE_IDS and tmpl.info(aid)["loop"] and masks and masks[0].sum() > BLANK_MIN:
            for t, m in zip(ts[1:], masks[1:]):
                if m.sum() > BLANK_MIN:
                    dx, dy, s = feet_shift(masks[0], m)
                    if max(abs(dx), abs(dy)) > FEET_SLIDE and s > 0.2:
                        rep["feet"].append(dict(id=aid, t=t, shift=(dx, dy), iou=round(s, 2)))
                        flagged.append((aid, t, "feet"))
        # drawing changes the build does not follow
        tch = sum(1 for i in range(1, len(ts)) if mt[i].get("hash") != mt[i - 1].get("hash"))
        same = sum(1 for i in range(1, len(ts)) if mt[i].get("hash") != mt[i - 1].get("hash")
                   and mb[i].get("hash") == mb[i - 1].get("hash"))
        if tch and same / tch > 0.5 and same >= 2 and aid not in IDLE_IDS:
            rep["repeat"].append(dict(id=aid, template_changes=tch, built_holds=same))
        if aid in IDLE_IDS:
            dt = len({m.get("hash") for m in mt if "hash" in m})
            db = len({m.get("hash") for m in mb if "hash" in m})
            seq = []
            for m in mb:
                h = m.get("hash")
                if not seq or seq[-1] != h:
                    seq.append(h)
            rep["idle"].append(dict(id=aid, template_distinct=dt, built_distinct=db, keys=len(ts),
                                    built_changes=len(seq) - 1))
            if db < min(dt, 4):
                flagged.append((aid, ts[0], "idle"))
    # DRPG flash frames (white impact / skill flashes) used as a pose: far whiter than the view's usual drawing
    for view, ws in whites.items():
        med = float(np.percentile([w for w, _, _, _ in ws], 25))     # the usual drawing (flashes may be common)
        tmed = float(np.percentile([tw for _, tw, _, _ in ws], 25))
        for w, tw, aid, t in ws:
            if w >= max(FLASH, 10 * med) and tw < max(FLASH, 10 * tmed):   # and the template frame is no flash
                rep["flash"].append(dict(id=aid, t=t, built_white=w, template_white=tw, median=med, tmedian=tmed))
                flagged.append((aid, t, "flash"))
    for view, hs in heights.items():
        med = float(np.median([h for h, _, _ in hs]))
        for h, aid, t in hs:
            if abs(h - med) > 0.3 * med:
                rep["scale"].append(dict(id=aid, t=t, height=h, median=med))
    rep["flagged"] = flagged
    return rep, frames


CROP = (-200, -330, 200, 50)


def contact_sheet(frames, flagged, path, limit=40, scale=0.6):
    sel = []
    for aid, t, why in flagged:
        if (aid, t) in frames and (aid, t, why) not in sel:
            sel.append((aid, t, why))
    sel = sel[:limit]
    if not sel:
        return None
    W = int((CROP[2] - CROP[0]) * scale)
    H = int((CROP[3] - CROP[1]) * scale)
    cols = min(8, len(sel))
    rows = (len(sel) + cols - 1) // cols
    sheet = Image.new("RGB", (W * cols, (2 * H + 4) * rows), (0, 0, 0))
    for i, (aid, t, why) in enumerate(sel):
        x, y = (i % cols) * W, (i // cols) * (2 * H + 4)
        for j, img in enumerate(frames[(aid, t)]):
            bg = Image.new("RGBA", (W, H), (40, 40, 70, 255))
            x0, y0 = CROP[0] - BOUNDS[0], CROP[1] - BOUNDS[1]
            im = Image.fromarray(img).crop((x0, y0, x0 + CROP[2] - CROP[0], y0 + CROP[3] - CROP[1])).resize((W, H))
            bg.alpha_composite(im)
            d = ImageDraw.Draw(bg)
            ox, oy = -CROP[0] * scale, -CROP[1] * scale
            d.line((ox - 5, oy, ox + 5, oy), fill=(255, 0, 0, 255))
            d.line((ox, oy - 5, ox, oy + 5), fill=(255, 0, 0, 255))
            if j == 0:
                d.text((2, 2), f"{aid} t{t} {why}", fill=(255, 255, 0, 255))
            sheet.paste(bg.convert("RGB"), (x, y + j * H))
    sheet.save(path)
    return path


def summary(rep):
    lines = []
    lines.append(f"missing animations: {rep['missing'] or 'none'}" + (f"  (extra: {rep['extra']})" if rep["extra"] else ""))
    lines.append(f"control differences: {len(rep['control'])} {[c['id'] for c in rep['control']][:12]}")
    lines.append(f"blank frames: {len(rep['blank'])} {[(b['id'], b['t']) for b in rep['blank']][:12]}")
    lines.append(f"ground jumps: {len(rep['ground'])} {[(g['id'], g['t0'], g['t1'], g['built']) for g in rep['ground']][:10]}")
    lines.append(f"feet sliding in idles: {len(rep['feet'])} {[(f['id'], f['t'], f['shift']) for f in rep['feet']][:10]}")
    lines.append(f"doubled bodies: {len(rep['doubled'])} {[(d['id'], d['t']) for d in rep['doubled']][:10]}")
    lines.append(f"collapsed animations: {len(rep['collapse'])} "
                 f"{[(c['id'], c['built_distinct'], c['template_distinct']) for c in rep['collapse']][:10]}")
    lines.append(f"detached pieces: {len(rep['detached'])} {[(d['id'], d['t'], d['pieces'][0][0]) for d in rep['detached']][:10]}")
    lines.append(f"held where the template changes: {[(r['id'], r['built_holds'], r['template_changes']) for r in rep['repeat']]}")
    lines.append("idle: " + ", ".join(f"{r['id']}: {r['built_distinct']} drawings / template {r['template_distinct']} "
                                      f"({r['built_changes']} changes in {r['keys']} keys)" for r in rep["idle"]))
    lines.append(f"flash frames shown as poses: {len(rep['flash'])} {sorted({f['id'] for f in rep['flash']})}")
    lines.append(f"parts that lost their limb / moved: {len(rep['parts'])} "
                 f"{sorted({p['id'] for p in rep['parts']})[:20]}")
    lines.append(f"scale outliers: {len(rep['scale'])} {[(s['id'], s['t'], s['height'], s['median']) for s in rep['scale']][:8]}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("built")
    ap.add_argument("template", type=int)
    ap.add_argument("--class", dest="humanoid", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--ids", default=None)
    o = ap.parse_args()
    ids = [int(x) for x in o.ids.split(",")] if o.ids else None
    rep, frames = qa(built_view(o.built), template_view(o.template, o.humanoid), ids, humanoid=o.humanoid,
                     fx=None if o.humanoid else fx_nodes(o.template))
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, o.out or ("qa_" + os.path.splitext(os.path.basename(o.built))[0]))
    with open(out + ".json", "w") as f:
        json.dump(rep, f, indent=1)
    contact_sheet(frames, rep["flagged"], out + ".png")
    print(summary(rep))
    print("->", out + ".json", out + ".png")
    print("RESULT:", "OK" if not errors(rep) else f"{errors(rep)} finding(s) to look at")


def errors(rep):
    return sum(len(rep[k]) for k in ("missing", "control", "blank", "ground", "feet", "doubled", "collapse",
                                     "detached", "flash", "parts")) + \
        sum(1 for r in rep["idle"] if r["built_distinct"] < min(r["template_distinct"], 4))


if __name__ == "__main__":
    main()
