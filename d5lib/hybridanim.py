"""Outfits for MONSTER-TYPE unique characters drawn from HUMANOID Disgaea RPG units (Usalia: in the game she rides
her big companion and is a monster-type unit with 58 animations of her own; her DRPG variants are ordinary humanoids).

The outfit keeps the character's own animation set -- every id, length, loop and event time (skills, attacks and
counters run on them) -- but each animation draws the humanoid DRPG unit:

    humanoid = drpgmap.build(unit on a humanoid template)        complete humanoid sprite (shared motions + idle)
    compose(template, humanoid, sources, keep)                     the template's animations, each one's drawing
                                                                   layers replaced by the humanoid source animation,
                                                                   time-warped so its event poses land on the
                                                                   template's event times

Animations listed in `keep` (props and companion-only moves: a cup, cutlery, the companion alone) keep the
template's own drawings.  Everything ends in ownanim.assemble: one atlas, one palette set.
"""
import copy
import dataclasses

import numpy as np

from . import anm, ownanim

CTRL_EVENT, CTRL_END, CTRL_LOOP_START, CTRL_LOOP_END = 4, 5, 1, 2

# Usalia (sprite 70): her animation -> the humanoid animation drawing it (back views: +6, see source_for)
USALIA_SOURCES = {
    1: 1, 2: 1, 11: 11, 41: 41,
    1001: 6001,                      # her idle loop -> the unit's own DRPG wait loop
    1011: 11, 1021: 1021, 1031: 1031, 1051: 1051, 1061: 1061, 1091: 1091, 1111: 1111, 1121: 1121, 1261: 1261,
    1501: 1,                         # the companion acts alone (she hops off and back): she stands by
    1511: 4041,                      # thrown through the air -> tumbling
    1531: 2041,                      # hammer swings -> a weapon swing
    1561: 4051,                      # spinning -> rolling
    2071: 2001,                      # normal attack (hammer from the companion's back) -> weapon attack
    3071: 3001,
    4001: 4001, 4011: 4011, 4021: 4021,
    8601: 1, 8611: 1,
}
# her companion alone and the props of her skills: drawn as in the game
USALIA_KEEP = {1521, 1527, 1541, 1547, 1551, 1557, 1571, 1581, 1591, 1601, 1607, 1617}


def source_for(aid, sources, have):
    """humanoid animation drawing template animation `aid` (have: the humanoid ids with drawings)"""
    view = 7 if aid % 10 == 7 else 1
    if aid in sources:
        s = sources[aid]
    elif aid % 10 == 7 and aid - 6 in sources:
        s = sources[aid - 6]
        s = s + 6 if s % 10 == 1 else s
    elif aid in have:
        s = aid
    else:
        s = view
    if s not in have:
        alt = s - 6 if s % 10 == 7 else s
        s = alt if alt in have else view
    return s


def _control(b, an):
    """(length, loop or None, [event times]) of an animation"""
    info = anm.animation_info(b, an)
    ev = [t for t, c in info["control"] if c == CTRL_EVENT]
    return info["length"], info["loop"], ev


def time_map(src, dst):
    """src / dst: (length, loop, events) -> function mapping a source key time to a destination time.
    Piecewise linear through the events when both have the same number of them, else a plain stretch; a static
    destination maps everything to 0."""
    ls, _, es = src
    ld, _, ed = dst
    if ld <= 0:
        return lambda t: 0
    if ls <= 0:
        return lambda t: 0
    pts = [(0, 0)]
    if es and len(es) == len(ed):
        pts += list(zip(es, ed))
    pts.append((ls, ld))
    xs = np.array([p[0] for p in pts], float)
    ys = np.array([p[1] for p in pts], float)
    order = np.argsort(xs, kind="stable")
    xs, ys = xs[order], np.maximum.accumulate(ys[order])
    return lambda t: int(round(float(np.interp(t, xs, ys))))


def _copy_subtree(src_b, dst_b, root, tmap, key_off=None):
    """deep-copy node `root` with its siblings and children from src_b (the humanoid block, same tables as dst_b) into
    dst_b with retimed keys -> index of the copy of `root` (-1 for none).  Keys mapped to the same time keep the
    last one (a static destination keeps each layer's first drawing)."""
    if root < 0:
        return -1
    order = []
    stack = [root]
    seen = set()
    while stack:                                   # every node reachable through child / next
        i = stack.pop()
        if i < 0 or i in seen or i >= len(src_b.nodes):
            continue
        seen.add(i)
        order.append(i)
        n = src_b.nodes[i]
        stack.append(n.next)
        stack.append(n.child)
    remap = {i: len(dst_b.nodes) + k for k, i in enumerate(order)}
    static = tmap(0) == tmap(10 ** 6)
    new_nodes = []
    for i in order:
        n = dataclasses.replace(src_b.nodes[i])
        named = n.id != 0
        # Monster-type sprites have only anonymous layers: the humanoid's named nodes (1 body, 10-17 / 111-117
        # weapon attachment points) and their show / hide-weapon key flags made the game crash on a monster-type
        # unit's attack.  They become plain layers.
        n.id = 0
        n.flags &= ~0x100
        if n.first_key >= 0 and n.num_keys:
            ks = src_b.keys[n.first_key:n.first_key + n.num_keys]
            timed = {}
            for k in sorted(ks, key=lambda k: k.time):
                t = tmap(k.time)
                if static:
                    timed.setdefault(t, k)          # a static pose: each layer's first drawing
                else:
                    timed[t] = k                    # squeezed together: the later key wins
            first = len(dst_b.keys)
            for t in sorted(timed):
                k = dataclasses.replace(timed[t], time=t)
                if named:
                    k.flags &= 0xFF
                dst_b.keys.append(k)
            n.first_key, n.num_keys = first, len(timed)
        n.child = remap.get(n.child, -1) if n.child >= 0 else -1
        n.next = remap.get(n.next, -1) if n.next >= 0 else -1
        new_nodes.append(n)
    dst_b.nodes += new_nodes
    return remap[root]


def _append_template(b, tb):
    """append the template block's node / key / transform / pivot / colour / param tables to b; template keys show
    their cell as -cell -> (node offset, key offset)"""
    no, ko, xo, po, co, pa = (len(b.nodes), len(b.keys), len(b.transforms), len(b.pivots), len(b.colors),
                              len(b.params))
    for n in tb.nodes:
        n = dataclasses.replace(n)
        if n.first_key >= 0 and n.num_keys:
            n.first_key += ko
        if n.child >= 0:
            n.child += no
        if n.next >= 0:
            n.next += no
        b.nodes.append(n)
    for k in tb.keys:
        b.keys.append(dataclasses.replace(k, cell=-k.cell, xform=k.xform + xo, color=k.color + co, param=k.param + pa))
    for x in tb.transforms:
        b.transforms.append(dataclasses.replace(x, pivot=x.pivot + po))
    b.pivots += [dataclasses.replace(p) for p in tb.pivots]
    b.colors += [copy.deepcopy(c) for c in tb.colors]
    b.params += list(tb.params)
    return no, ko


def _cell_rgba(a, cell, cache):
    if cell.tex not in cache:
        cache[cell.tex] = np.asarray(anm.texture_to_image(a, cell.tex, 0))
    t = cache[cell.tex]
    return np.ascontiguousarray(t[cell.y:cell.y + cell.h, cell.x:cell.x + cell.w])


def compose(template, humanoid, sprite_id, sources=None, keep=(), log=None):
    """template: the monster-type character's sprite (own animations only); humanoid: a complete humanoid sprite of
    the unit (drpgmap.build) -> AnmFile with the template's animation set drawn by the humanoid (module doc)"""
    sources = USALIA_SOURCES if sources is None else sources
    keep = set(keep)
    hb = humanoid.blocks[0]
    tb = template.blocks[0]
    b = copy.deepcopy(hb)
    have = {an.id for an in hb.animations if any(k.cell for ni, d, p in hb.walk(an.root)
                                                 for k in hb.node_keys(hb.nodes[ni]))}
    H = {an.id: an for an in hb.animations}
    no, ko = _append_template(b, tb)
    anims = []
    report = {}
    for an in tb.animations:
        if an.id in keep or not any(k.cell for ni, d, p in tb.walk(an.root) for k in tb.node_keys(tb.nodes[ni])):
            anims.append(anm.Animation(an.id, an.root + no))
            report[an.id] = "kept"
            continue
        s = source_for(an.id, sources, have)
        src = H[s]
        tmap = time_map(_control(hb, src), _control(tb, an))
        # the template's control node (its timing and events) over the humanoid's layers, which hang off the
        # humanoid control node as children and / or as the following sibling group
        root = dataclasses.replace(b.nodes[an.root + no])
        hroot = hb.nodes[src.root]
        root.child = _copy_subtree(hb, b, hroot.child, tmap)
        root.next = _copy_subtree(hb, b, hroot.next, tmap)
        b.nodes.append(root)
        anims.append(anm.Animation(an.id, len(b.nodes) - 1))
        report[an.id] = s
    b.animations = sorted(anims, key=lambda a: a.id)
    # frames: every humanoid cell as drawn, the kept template cells as drawn
    frames, matches = [], {}
    hcache, tcache = {}, {}
    used = {k.cell for k in b.keys if k.cell}
    for c in sorted(used):
        cell = hb.cells[c] if c > 0 else tb.cells[-c]
        if not cell.w or not cell.h:
            continue
        img = _cell_rgba(humanoid if c > 0 else template, cell, hcache if c > 0 else tcache)
        if (img[..., 3] > 0).sum() < 4:
            continue
        matches[c] = dict(frame=len(frames), dx=0, dy=0)
        frames.append(dict(rgba=img))
    out = ownanim.assemble(b, hb, template, frames, matches, sprite_id)
    if log:
        log(f"  {len(report)} animations: {sum(1 for v in report.values() if v == 'kept')} kept as drawn, the rest "
            f"drawn by humanoid motions")
    compose.report = report
    return out
