"""D4 idle timing and idle weapon positions for an imported D4 class sprite.

An imported class (d5lib.sourceimports.build_d4_pilot) gets its poses placed into the D5 template's animation
set, so every animation keeps D5's timing and weapon positions.  For the class's own idle (front 6001, back 6007)
D4 has a rhythm and grip of its own (Armor Knight: a 153-tick loop holding still, then moving at 82, 94, 106,
130, 142; the sword held angled up).  apply() re-clocks the idle with the kit's d5lib.rpgidle (the same tool that
gives Disgaea RPG costumes their own idle clock) and copies D4's weapon-node transforms (nodes 11-16 / 111-116)
onto the same ticks, shifted by where the import draws the body relative to D4.

D4 and D5 both count 60 ticks per second (107 shared animations have identical key times).  Attacks and other
shared motions keep D5's timing and weapon positions: D5 re-authored those weapon tracks.  Research and renders:
/Volumes/Data/ai-tmp/claude/d4-timing/REPORT.md (local), prototype d4_clock_prototype.py.
"""
import copy
import os
import tempfile

import numpy as np

from . import anm, rpgidle

IDLES = ((6001, "front"), (6007, "back"))
WEAPON_NODES = {11, 12, 13, 14, 15, 16, 111, 112, 113, 114, 115, 116}


def _anim(a, aid):
    b = a.blocks[0]
    return b, next(x for x in b.animations if x.id == aid)


def _body_items(a, aid, t):
    return [it for it in anm.evaluate(a, ("id", aid), t) if a.blocks[0].nodes[it.node].id == 0]


def _offset(d4, sprite, aid, t, mirror):
    """(dx, dy): where the import draws the body at t minus where D4 draws it (alpha overlap, +-3 px search)"""
    ia, ib = _body_items(d4, aid, t), _body_items(sprite, aid, t)
    b4, b5 = anm.item_bounds(ia), anm.item_bounds(ib)
    if mirror:
        b4 = (-b4[2], b4[1], -b4[0], b4[3])
    bb = (min(b4[0], b5[0]) - 40, min(b4[1], b5[1]) - 40, max(b4[2], b5[2]) + 40, max(b4[3], b5[3]) + 40)
    if mirror:
        A = np.asarray(anm.render_items(d4, ia, 0, bounds=(-bb[2], bb[1], -bb[0], bb[3]))[0])[:, ::-1, 3] > 32
    else:
        A = np.asarray(anm.render_items(d4, ia, 0, bounds=bb)[0])[..., 3] > 32
    B = np.asarray(anm.render_items(sprite, ib, 0, bounds=bb)[0])[..., 3] > 32
    ya, xa = np.nonzero(A)
    yb, xb = np.nonzero(B)
    cx, cy = int(xb.min() - xa.min()), int(yb.max() - ya.max())
    best = (-1, 0, 0)
    for dy in range(cy - 3, cy + 4):
        for dx in range(cx - 3, cx + 4):
            s = int(np.logical_and(np.roll(np.roll(A, dy, 0), dx, 1), B).sum())
            if s > best[0]:
                best = (s, dx, dy)
    return best[1], best[2], best[0] / max(1, int(B.sum()))


def _group_xy(a, aid, ni, t):
    b, an = _anim(a, aid)
    parents = {i: p for i, _, p in b.walk(an.root)}
    x = y = 0
    p = parents[ni]
    while p >= 0:
        ks = b.node_keys(b.nodes[p])
        k = rpgidle.key_at(ks, t) if ks else None
        if k is not None:
            xf = b.transforms[k.xform]
            if xf.rot or xf.sx != 100 or xf.sy != 100:
                raise ValueError("idle group node with rotation / scale: not handled")
            x, y = x + xf.x, y + xf.y
        p = parents[p]
    return x, y


def apply(sprite, d4, log=print):
    """sprite: the imported class's AnmFile (block = family); d4: the D4 body's AnmFile (d4source.D4Data.anm).
    -> (new AnmFile, audit dict).  The input is not changed."""
    frames = tempfile.mkdtemp(prefix="d4idle-")       # rpgidle reads its source drawings as PNGs
    try:
        unit = {"facings": {}}
        clock = {}
        for aid, view in IDLES:
            b, an = _anim(d4, aid)
            info = anm.animation_info(b, an)
            ni, _ = rpgidle.body_node(b, an)
            times = [k.time for k in b.node_keys(b.nodes[ni]) if k.time < info["loop"][1]]
            switches = []
            for t in times:
                png = os.path.join(frames, f"{aid}_t{t:03d}.png")
                anm.render_frame(d4, ("id", aid), time=t).save(png)
                switches.append(dict(ticks60=t, sprite_name=f"d4_{aid}_t{t:03d}", png=png))
            unit["facings"][view] = dict(duration_ticks60=info["loop"][1], switches=switches)
            clock[aid] = dict(loop=list(info["loop"]), switch_ticks=times)
        out, loops = rpgidle.repair_sprite(sprite, unit)
    finally:                                          # full paths (not rmtree): works under write-audit guards
        for name in os.listdir(frames):
            os.remove(os.path.join(frames, name))
        os.rmdir(frames)
    audit = dict(d4_clock=clock, rpgidle=loops, offsets={}, weapon_keys=0)
    pb, d4b = out.blocks[0], d4.blocks[0]
    for aid, _ in IDLES:
        _, an = _anim(out, aid)
        _, dan = _anim(d4, aid)
        d4nodes = {d4b.nodes[i].id: i for i, _, _ in d4b.walk(dan.root) if d4b.nodes[i].id in WEAPON_NODES}
        mirror = next(l["mirrored"] for l in loops if l["animation"] == aid)
        sgn = -1 if mirror else 1
        offs = {}
        for i, _, _ in list(pb.walk(an.root)):
            n = pb.nodes[i]
            if n.id not in WEAPON_NODES or n.id not in d4nodes:
                continue
            dks = d4b.node_keys(d4b.nodes[d4nodes[n.id]])
            new = []
            for k in pb.node_keys(n):
                if k.time not in offs:
                    offs[k.time] = _offset(d4, out, aid, k.time, mirror)
                dx, dy, _ = offs[k.time]
                src = rpgidle.key_at(dks, k.time)
                sx = d4b.transforms[src.xform]
                dgx, dgy = _group_xy(d4, aid, d4nodes[n.id], k.time)
                pgx, pgy = _group_xy(out, aid, i, k.time)
                k2 = copy.deepcopy(k)
                k2.flags = (src.flags & 0xFF00) if src.time == k.time else 0      # D4's show / hide at this tick
                # the key's param names the weapon pose drawn on the node (sword: 11 held; D5's back idle switches
                # to 17 after tick 0, which draws nothing here): D4's choice, not the template's
                if 0 <= src.param < len(d4b.params):
                    value = d4b.params[src.param]
                    if value not in pb.params:
                        pb.params.append(value)
                    k2.param = pb.params.index(value)
                xf = copy.deepcopy(pb.transforms[k.xform])
                xf.x = sgn * (sx.x + dgx) + dx - pgx
                xf.y = sx.y + dgy + dy - pgy
                xf.sx, xf.sy, xf.rot = sgn * sx.sx, sx.sy, sgn * sx.rot
                k2.xform = len(pb.transforms)
                pb.transforms.append(xf)
                new.append(k2)
                audit["weapon_keys"] += 1
            n.first_key, n.num_keys = len(pb.keys), len(new)
            pb.keys.extend(new)
        audit["offsets"][aid] = {t: (dx, dy, round(s, 3)) for t, (dx, dy, s) in offs.items()}
    anm.load(out.to_bytes())                                   # round trip check
    log(f"D4 idle clock: front loop {clock[6001]['loop'][1]}, back loop {clock[6007]['loop'][1]} ticks; "
        f"{audit['weapon_keys']} weapon keys from D4")
    return out, audit
