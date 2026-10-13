"""Weapon grips: where a character holds its weapon, per animation and frame.  Docs: docs/WEAPON_GRIPS.md.

A battle sprite carries the weapon on attachment nodes.  Node 10 + weapon type is the hand of group A (11 sword,
12 spear, 13 bow, 14 gun, 15 axe, 16 staff), 100 + that is group B (111-116, the weapon carried across the body or
back in some motions).  The game draws the weapon sprite (3100 sword ... 3600 staff) with its grip on the node's
origin, turned and mirrored with the node.  A key's flag high byte 1 / 2 shows / hides the weapon from that key on.

Edits are kept per mod in patches/grips/<sprite>.json and applied at install, after every other mod, to the sprite
and its copy (sprite + 1):

    {"anims": {"6001": {"A":  {"*": [dx, dy, rot], "24": [dx, dy, rot, flip]},
                        "16": {"show": true}}}}

  target  "A" / "B": every weapon node of that hand (all weapon types move together), or a node id ("16" = the staff
          only).  Group and node entries add up.
  key     "*" = every key of the animation, or a key time (frame) of the node.  They add up too.
  dx, dy  pixels in the sprite's own space (x right, y down; the game mirrors the whole sprite for the other facing)
  rot     degrees clockwise, about the grip (the node's origin); flip 1 = mirror the weapon about its grip
  show    true / false: show or hide that weapon for the whole animation (sets the first key's flag)

Only animations stored in the sprite file can change: for new classes that is every animation; vanilla humanoids keep
just their idle / special poses (6xxx / 7xxx) and play the shared motions of anm_resident.

The weapon at rest: the sprites of outfits, new characters and new classes (their drawings often hold something of
their own) carry no weapon while the unit stands, waits, walks, dashes or takes a hit (REST_ANIMS): the weapon
shows from the first key of an attack or skill animation, which shows it.  "idle_weapon": true in the sprite's grips
file keeps it in their hands throughout; a sprite with grip edits keeps it too unless "idle_weapon": false (those
were set up holding it).  The game's own sprites are never changed by this.
"""
import copy
import dataclasses
import json
import math
import os

import numpy as np

from . import anm, sprites
from .modsys import register_patch_handler, register_finalizer

HANDLER = "grips"
WEAPONS = {11: ("Sword", 3100), 12: ("Spear", 3200), 13: ("Bow", 3300), 14: ("Gun", 3400), 15: ("Axe", 3500),
           16: ("Staff", 3600)}
GROUPS = {"A": tuple(range(11, 18)), "B": tuple(range(111, 118))}
SHOW, HIDE = 0x100, 0x200
ZERO = (0.0, 0.0, 0.0, 0)
# a unit at rest (front ids; the back view is + 6): stand, wait, walk, dash, stand, idle (stub), wait, taking a hit,
# waiting, the idle loop, special idle
REST_ANIMS = (1, 11, 21, 31, 41, 101, 1001, 1011, 1021, 1031, 1121, 6001, 7001)


def is_rest(aid):
    aid = int(aid)
    return aid in REST_ANIMS or (aid % 10 == 7 and aid - 6 in REST_ANIMS)


def is_attachment(nid):
    return 11 <= nid <= 17 or 111 <= nid <= 117


def group_of(nid):
    return "A" if nid < 100 else "B"


def matches(target, nid):
    t = str(target)
    return nid in GROUPS[t] if t in GROUPS else t.isdigit() and int(t) == nid


# ------------------------------------------------------------------------------------------- data
def path(mod, sprite):
    return mod.patch_path(HANDLER, f"{int(sprite)}.json")


def load(mod, sprite):
    """{anim id: {target: {key: [dx, dy, rot(, flip)] | 'show': bool}}} of one sprite (str keys as stored)"""
    d = mod.load_patch(HANDLER, f"{int(sprite)}.json") or {}
    return d.get("anims", {})


def save(mod, sprite, edits, idle=...):
    """the grip edits of one sprite (idle: the idle_weapon setting, True / False / None; left out = kept)"""
    clean = {}
    for aid, tg in (edits or {}).items():
        for target, ks in tg.items():
            for k, v in ks.items():
                if k == "show" or any(abs(float(x)) > 1e-9 for x in v):
                    clean.setdefault(str(aid), {}).setdefault(str(target), {})[str(k)] = v
    if idle is ...:
        idle = idle_weapon(mod, sprite)
    d = {}
    if clean:
        d["anims"] = clean
    if idle is not None:
        d["idle_weapon"] = bool(idle)
    mod.save_patch(HANDLER, f"{int(sprite)}.json", d or None)


def idle_weapon(mod, sprite):
    """the sprite's setting: True (holds the weapon at rest), False (only in attacks and skills), None (default)"""
    v = (mod.load_patch(HANDLER, f"{int(sprite)}.json") or {}).get("idle_weapon")
    return None if v is None else bool(v)


def holds_at_rest(setting, edits):
    """does a mod's sprite hold its weapon at rest: its setting, else only when someone set up its grips"""
    return bool(edits) if setting is None else bool(setting)


def hide_at_rest(a):
    """the weapon nodes of every rest animation (REST_ANIMS) of AnmFile a hidden from their first key on -> keys
    changed"""
    n = 0
    for b in a.blocks:
        for an in b.animations:
            if not is_rest(an.id):
                continue
            for ni, nid in weapon_nodes(b, an):
                node = b.nodes[ni]
                for i, ki in enumerate(range(node.first_key, node.first_key + node.num_keys)):
                    k = b.keys[ki]
                    f = (k.flags & 0xFF) | (HIDE if i == 0 else 0)
                    if f != k.flags:
                        b.keys[ki] = dataclasses.replace(k, flags=f)
                        n += 1
    return n


def sprites_of(mod):
    return [int(f[:-5]) for f in mod.list_patches(HANDLER) if f[:-5].isdigit()]


def merge(base, extra):
    """edits of a later mod over an earlier one's (per animation, target and key)"""
    out = copy.deepcopy(base)
    for aid, tg in extra.items():
        for target, ks in tg.items():
            out.setdefault(str(aid), {}).setdefault(str(target), {}).update(ks)
    return out


def _entry(v):
    v = list(v) + [0, 0, 0, 0]
    return float(v[0]), float(v[1]), float(v[2]), int(v[3]) & 1


def offset_of(tg, nid, time):
    """(dx, dy, rot, flip) the edits of one animation give node id `nid` at key time `time`"""
    dx = dy = rot = 0.0
    flip = 0
    for target, ks in tg.items():
        if not matches(target, nid):
            continue
        for k in ("*", str(int(time))):
            if k in ks:
                a, b, r, f = _entry(ks[k])
                dx, dy, rot, flip = dx + a, dy + b, rot + r, flip ^ f
    return dx, dy, rot, flip


def show_of(tg, nid):
    v = None
    for target, ks in tg.items():
        if matches(target, nid) and "show" in ks:
            v = bool(ks["show"])
    return v


# ------------------------------------------------------------------------------------------- geometry
def node_states(b, an, t):
    """{node index: (parent world matrix, active key or None, world matrix)} of animation `an` at frame t"""
    out = {}

    def rec(ni, parent, seen):
        while 0 <= ni < len(b.nodes) and ni not in seen:
            seen.add(ni)
            n = b.nodes[ni]
            ks = b.node_keys(n)
            act, m = None, parent
            if ks:
                a = anm._active_key(ks, t)
                if a is not None:
                    k, nx, f = a
                    act = k
                    vals, pts, col = anm._key_state(b, n, k, nx, f)
                    m = parent @ anm._mat(*vals)
            out[ni] = (parent, act, m)
            if (not ks or act is not None) and n.child >= 0:
                rec(n.child, m, seen)
            ni = n.next

    rec(an.root, np.eye(3), set())
    return out


def _decompose(M, like=None):
    """3x3 matrix -> (x, y, sx, sy, rot) for anm.Transform: the inverse of anm._mat.  Of the two ways to write a
    mirrored or half-turned matrix (-sx, -sy, rot + 180) it picks the one with the signs of `like` (the key's old
    transform) and the rotation nearest to like's, so tweens to the neighbouring keys don't spin or flip."""
    A = M[:2, :2]
    sy = math.hypot(A[0, 1], A[1, 1]) * 100
    c, s = A[1, 1] * 100 / sy, -A[0, 1] * 100 / sy
    sx = (A[0, 0] * c + A[1, 0] * s) * 100
    rot = math.degrees(math.atan2(s, c))
    if like is not None:
        if (like.sy < 0) != (sy < 0):
            sx, sy, rot = -sx, -sy, rot + 180
        rot = like.rot + ((rot - like.rot + 180) % 360 - 180)
    return int(round(M[0, 2])), int(round(M[1, 2])), int(round(sx)), int(round(sy)), int(round(rot))


def _tr(x, y):
    return np.array([[1, 0, x], [0, 1, y], [0, 0, 1.0]])


def moved(M, dx, dy, rot, flip):
    """world matrix M of a weapon node turned by rot (clockwise) / mirrored about its origin, then moved by (dx, dy)"""
    o = M[:2, 2]
    r = math.radians(rot)
    R = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1.0]])
    F = np.diag([-1.0, 1.0, 1.0]) if flip else np.eye(3)
    return _tr(o[0] + dx, o[1] + dy) @ R @ F @ _tr(-o[0], -o[1]) @ M


def weapon_nodes(b, an):
    """[(node index, node id)] of the animation's weapon attachment nodes that have keys"""
    return [(ni, b.nodes[ni].id) for ni, d, p in b.walk(an.root)
            if is_attachment(b.nodes[ni].id) and b.nodes[ni].num_keys]


def key_times(b, an, targets=None):
    """sorted key times of the weapon nodes (of `targets`, e.g. ['A']) inside the animation's loop / length"""
    info = anm.animation_info(b, an)
    end = info["loop"][1] if info["loop"] else max(info["length"], 0)
    ts = set()
    for ni, nid in weapon_nodes(b, an):
        if targets and not any(matches(t, nid) for t in targets):
            continue
        ts |= {k.time for k in b.node_keys(b.nodes[ni]) if not end or k.time <= end}
    return sorted(ts)


def apply_block(b, edits, log=None):
    """apply {anim id: {target: {...}}} to block b in place -> number of keys changed"""
    by_id = {str(an.id): an for an in b.animations}
    xf_index = {}
    changed = 0
    for aid, tg in edits.items():
        an = by_id.get(str(aid))
        if an is None or not tg:
            continue
        nodes = weapon_nodes(b, an)
        plan = []
        cache = {}
        for ni, nid in nodes:
            n = b.nodes[ni]
            for ki in range(n.first_key, n.first_key + n.num_keys):
                key = b.keys[ki]
                dx, dy, rot, flip = offset_of(tg, nid, key.time)
                if (dx, dy, rot, flip) == ZERO:
                    continue
                if key.time not in cache:
                    cache[key.time] = node_states(b, an, key.time)
                P = cache[key.time].get(ni, (np.eye(3),))[0]
                xf = b.transforms[key.xform] if 0 <= key.xform < len(b.transforms) else anm._IDENT
                M = P @ anm._mat(xf.x, xf.y, xf.sx, xf.sy, xf.rot)
                L = np.linalg.inv(P) @ moved(M, dx, dy, rot, flip)
                plan.append((ki, xf, _decompose(L, xf)))
        for ki, xf, (x, y, sx, sy, rt) in plan:     # after every matrix was taken from the unchanged tables
            t = anm.Transform(x, y, xf.pivot, xf.unk, sx, sy, rt)
            k = (x, y, xf.pivot, xf.unk, sx, sy, rt)
            if k not in xf_index:
                b.transforms.append(t)
                xf_index[k] = len(b.transforms) - 1
            b.keys[ki] = dataclasses.replace(b.keys[ki], xform=xf_index[k])     # copies share the Key objects
            changed += 1
        for ni, nid in nodes:
            v = show_of(tg, nid)
            if v is None:
                continue
            n = b.nodes[ni]
            for i, ki in enumerate(range(n.first_key, n.first_key + n.num_keys)):
                k = b.keys[ki]
                hi = (SHOW if v else HIDE) if i == 0 else 0
                b.keys[ki] = dataclasses.replace(k, flags=(k.flags & 0xFF) | hi)
            changed += 1
    if len(b.transforms) > 65535:
        raise ValueError("animation tables too large after the grip edits")
    return changed


def apply(a, edits, log=None):
    """apply grip edits to every block of AnmFile a -> keys changed"""
    return sum(apply_block(b, edits, log) for b in a.blocks)


def edited_copy(a, edits):
    """a copy of AnmFile a with the edits applied; textures and palettes are shared, not copied"""
    c = copy.copy(a)
    c.blocks = []
    for b in a.blocks:
        nb = copy.copy(b)
        nb.keys = list(b.keys)
        nb.transforms = list(b.transforms)
        c.blocks.append(nb)
    apply(c, edits)
    return c


# ------------------------------------------------------------------------------------------- render
_weapons = {}


def weapon_sprite(fs, wtype, model=None):
    """AnmFile of a weapon: `model` = its sprite number (item.dat weapon_anm), default the base weapon of the type
    (11 sword ... 16 staff)"""
    num = model or WEAPONS[wtype][1]
    if num not in _weapons:
        _weapons[num] = anm.load(fs.read(sprites.sprite_vpath(fs, num, "EN")))
    return _weapons[num]


def weapon_models(fs, wtype):
    """[(sprite number, item names)] of the game's weapons of a type (item.dat weapon_anm in the type's 100-block)"""
    from . import database
    lo = WEAPONS[wtype][1]
    names = {}
    try:
        t = database.load_table("item.dat", fs.read("Database/Database_0.dat/item.dat"))
        for r in t.rows:
            n = r["weapon_anm"]
            if lo <= n < lo + 100 and r["name_EN"] and r["name_EN"] not in names.setdefault(n, []):
                names[n].append(r["name_EN"])
    except Exception:
        pass
    return sorted(names.items()) or [(lo, [WEAPONS[wtype][0]])]


def _visible(ks, t):
    vis = None
    for k in ks:
        if k.time <= t and (k.flags >> 8) & 3:
            vis = (k.flags >> 8) & 1
    return vis


def evaluate(a, aid, t, weapon=None, wtype=16, groups=("A", "B"), grips=None, nested=False, _depth=0):
    """draw items [(AnmFile, DrawItem)] in painting order: the character at frame t with the weapon AnmFile drawn on
    the shown nodes 10 + wtype (group A) / 110 + wtype (group B).  grips (a list) receives (node id, group, (x, y),
    shown, world matrix) of every weapon node of that type.
    nested: a stub animation shows the animation its 0x100 keys name (anm.NESTED; the shared poses 114-125,
    155-160 … are the character's own hurt / guard … animation with a little shake around it) -- for showing only."""
    bi, ai = anm._resolve_anim(a, ("id", aid))
    b = a.blocks[bi]
    an = b.animations[ai]
    nest = nested and _depth < 3 and anm.is_stub(a, bi, ai)
    want = {g: (wtype if g == "A" else wtype + 100) for g in groups}
    items = []

    def rec(ni, pm, depth, seen):
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
                if k.cell and k.cell < len(b.cells):
                    c = b.cells[k.cell]
                    if n.mesh:
                        quad = anm._apply(m, pts)
                    else:
                        px, py = pts[0]
                        quad = anm._apply(m, np.array([[0, 0], [c.w, 0], [c.w, c.h], [0, c.h]], float) - [px, py])
                    items.append((a, anm.DrawItem(ni, depth, k, c, quad, col, b.tex_base + c.tex, c.pal, bi)))
                elif nest and anm.is_nested(k):
                    sub_id = b.params[k.param] if 0 <= k.param < len(b.params) else None
                    if sub_id is not None and sub_id != aid and anm.has_animation(a, sub_id):
                        sub = evaluate(a, sub_id, max(0.0, t - k.time), weapon, wtype, groups, None, True, _depth + 1)
                        items.extend(reversed([(f, anm.DrawItem(it.node, it.depth + depth, it.key, it.cell,
                                                                anm._apply(m, it.quad), it.color, it.tex_global,
                                                                it.pal_local, it.block)) for f, it in sub]))
                if n.id in want.values():
                    shown = bool(_visible(ks, t))
                    if grips is not None:
                        grips.append((n.id, group_of(n.id), tuple(m[:2, 2]), shown, m))
                    if shown and weapon is not None:
                        prm = b.params[k.param] if 0 <= k.param < len(b.params) else 1
                        wb = weapon.blocks[0]
                        wid = prm if any(x.id == prm for x in wb.animations) else wb.animations[0].id
                        sub = [(weapon, anm.DrawItem(it.node, it.depth, it.key, it.cell, anm._apply(m, it.quad),
                                                     it.color, it.tex_global, it.pal_local, it.block))
                               for it in anm.evaluate(weapon, ("id", wid), 0)]
                        items.extend(reversed(sub))
            if (not ks or act is not None) and n.child >= 0:
                rec(n.child, m, depth + 1, seen)
            ni = n.next

    rec(an.root, np.eye(3), 0, set())
    items.reverse()
    return items


def render(items, bounds, scale=1.0, palette=0, background=(0, 0, 0, 0), char=None):
    """PIL image of evaluate()'s items; bounds = (x0, y0, x1, y1) in sprite space; palette = colour variant of the
    character file `char` (the weapon keeps its own)"""
    from PIL import Image
    x0, y0, x1, y1 = bounds
    canvas = Image.new("RGBA", (max(1, int(math.ceil((x1 - x0) * scale))), max(1, int(math.ceil((y1 - y0) * scale)))),
                       tuple(background))
    for f, it in items:
        img, _ = anm.render_items(f, [it], palette if f is char else 0, scale, bounds=bounds)
        canvas.alpha_composite(img)
    return canvas


def weapon_anims(a):
    """[(anim id, block index)] of the animations in the file that carry weapon nodes"""
    out = []
    for bi, b in enumerate(a.blocks):
        for an in b.animations:
            if weapon_nodes(b, an):
                out.append((an.id, bi))
    return out


def anim_bounds(a, aid, weapon=None, wtype=16, margin=8):
    """sprite-space box around the animation's frames (with the weapon)"""
    bi, ai = anm._resolve_anim(a, ("id", aid))
    b = a.blocks[bi]
    times = anm.frame_times(a, ("id", aid))
    pts = []
    for t in times[:: max(1, len(times) // 12)]:
        for f, it in evaluate(a, aid, t, weapon, wtype):
            pts.append(it.quad)
    if not pts:
        return (-64, -128, 64, 32)
    p = np.concatenate(pts)
    return (int(p[:, 0].min()) - margin, int(p[:, 1].min()) - margin,
            int(p[:, 0].max()) + margin, int(p[:, 1].max()) + margin)


# ------------------------------------------------------------------------------------------- install
def _handler(ctx, mod, patch_dir):
    acc = getattr(ctx, "_grips", {})
    idle = getattr(ctx, "_grip_idle", {})
    for s in sprites_of(mod):
        acc[s] = merge(acc.get(s, {}), load(mod, s))
        v = idle_weapon(mod, s)
        if v is not None:
            idle[s] = v
    ctx._grips = acc
    ctx._grip_idle = idle


def _finalize(ctx):
    acc = getattr(ctx, "_grips", {})
    for s, edits in sorted(acc.items()):
        if not edits:
            continue
        for num in (s, s + 1):
            vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"            # where mods put sprites
            try:
                if vp.lower() not in ctx.outputs:
                    vp = sprites.sprite_vpath(ctx.fs, num, "EN")         # the game's own file
                data = ctx.get(vp)
            except Exception:
                continue
            a = anm.load(data)
            n = apply(a, edits)
            if n:
                ctx.put(vp, a.to_bytes())
                ctx.log(f"  weapon grips: anm{num:05d} {n} key(s) changed")
    _rest(ctx, acc)


def _rest(ctx, acc):
    """the weapon at rest of the mods' own sprites (outfits, new characters, new humanoid classes): hidden unless
    the sprite holds it (holds_at_rest)"""
    idle = getattr(ctx, "_grip_idle", {})
    own = {int(x) for x in getattr(ctx, "_outfit_own", ())}
    for fam, spec in getattr(ctx, "_class_specs", {}).items():
        if not 2000 <= int(spec.get("template", 0)) < 3000:          # monsters carry no weapon
            own |= {int(fam), int(fam) + 1}
    done = []
    for num in sorted(own):
        main = num - 1 if num % 10 == 1 else num                         # the copy N + 1 follows sprite N
        if holds_at_rest(idle.get(main), acc.get(main)):
            continue
        vp = f"Anime/ANM_HI_JP.dat/anm{num:05d}.lzs"
        if vp.lower() not in ctx.outputs:
            continue
        a = anm.load(ctx.get(vp))
        if hide_at_rest(a):
            ctx.put(vp, a.to_bytes())
            done.append(num)
    if done:
        ctx.log(f"  weapon at rest: hidden in {len(done)} sprite file(s) (attacks and skills show it; "
                "Weapon Grips page: 'Hold the weapon when not attacking')")


register_patch_handler(HANDLER, _handler, order=95)
register_finalizer(_finalize)
