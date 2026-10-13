"""Convert a 'frame dump' sprite sheet (whole-pose frames) into a Disgaea 5 humanoid sprite.

Disgaea 5 humanoid sprites are sheets of whole-pose frames at STANDARD cell rectangles; the shared motion
set (anm_resident block 1) cuts those cells out and animates them (plus small hand overlays drawn over
the weapon). So a new outfit keeps the base character's file layout and simply has every pose cell
repainted with the matching frame of the new sheet:

  1. for every motion-set animation, list the pose cells its body layer shows (in time order)
  2. match them to the frames of the same animation in the sheet (evenly, by position in the sequence)
  3. paint each sheet frame into its cell, aligned at the feet with the original pose
  4. re-quantise all textures to one 255-colour palette (+ recoloured variants for the colour menu)

Everything else (motions, hit timing, weapon attachment, effects) stays the game's own.
"""
import colorsys
import copy

import numpy as np
from PIL import Image

from . import anm

# Disgaea 5 humanoid motion id (front view; back view = +6) -> sheet animation name
DEFAULT_MAP = {
    1: "stand", 31: "stand", 101: "stand",
    11: "wait", 1121: "wait", 6001: "wait", 7001: "wait",
    21: "walk", 41: "dash",
    1021: "damage", 1031: "damage", 1041: "squat", 1051: "two_arm_up_jump", 1061: "launch",
    1091: "one_arm_up", 1131: "one_arm_up", 1101: "take_out", 1111: "take_out",
    3001: "attack_fist", 3011: "attack_sword", 3021: "attack_lance", 3031: "attack_arrow",
    3041: "attack_gun", 3051: "attack_ax", 3061: "one_arm_up",
    2001: "attack_fist", 2011: "attack_sword", 2021: "attack_lance", 2031: "attack_arrow",
    2041: "attack_gun", 2051: "attack_ax", 2061: "one_arm_up",
    4001: "two_arm_up_jump", 4011: "kabutowari",
    4021: "landing", 4031: "landing", 4041: "rolling", 4051: "rolling", 4081: "rolling",
}
# names a sheet row can be assigned to (anything else is ignored)
ANIM_NAMES = ["stand", "wait", "walk", "dash", "damage", "squat", "two_arm_up_jump", "launch", "one_arm_up",
              "take_out", "attack_fist", "attack_sword", "attack_lance", "attack_arrow", "attack_gun", "attack_ax",
              "kabutowari", "landing", "rolling", "roll_landing", "gun_aerial"]
# rows of small overlay pieces (hands / arms drawn over the weapon), e.g. 'attack_sword_hand'
HAND_NAMES = [n + "_hand" for n in ANIM_NAMES if n not in ("stand", "wait", "walk")]


def normalize_name(label: str) -> str:
    """'#1-front - #2_wait' / '#2_wait' / 'wait' -> 'wait'; 'damage_hand' stays (overlay row);
    returns '' for unknown rows."""
    import re
    s = label.strip().lower()
    s = s.split(" - ")[-1]
    s = re.sub(r"^#\d+_", "", s)
    return s if s in ANIM_NAMES or s in HAND_NAMES else ""


# earlier entries win when a cell is shared by several animations
PRIORITY = [1, 21, 11, 3001, 3011, 3021, 3031, 3041, 3051, 1021, 1031, 1041, 1051, 1061, 1091, 1101, 41,
            4011, 4001, 4021, 4041, 4081, 2001, 2011, 2021, 2031, 2041, 2051, 3061, 2061, 1111, 1121, 1131,
            31, 101, 4031, 4051, 6001, 7001]

POSE_MIN = 64  # cells smaller than this (hands, arms, effects) are not whole poses


def frame_anchor(rgba):
    """(x, y) of the feet: bottom of the solid pixels, x centred on the lowest rows."""
    a = rgba[:, :, 3]
    solid = a >= 200
    ys, xs = np.nonzero(solid if solid.any() else a > 0)
    if len(ys) == 0:
        return rgba.shape[1] // 2, rgba.shape[0] - 1
    bottom = ys.max()
    low = ys >= bottom - max(4, (bottom - ys.min()) // 12)
    return int(round(xs[low].mean())), int(bottom)


def crop(img):
    arr = np.asarray(img.convert("RGBA"))
    ys, xs = np.nonzero(arr[:, :, 3] > 0)
    if len(ys) == 0:
        return None
    return arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()


def body_cell_sequence(block, anim, textures_ok, shared=True):
    """Pose cells shown by the animation's body layer, in time order.
    Shared motion set: keys of the body node (node id 1).  Character's own block: tall cells only
    (its arm/hand pieces live in other layers)."""
    tracks = []  # per body node: [(time, cell)]
    for ni, depth, parent in block.walk(anim.root):
        node = block.nodes[ni]
        if shared and node.id != 1:
            continue
        tr = []
        for k in block.node_keys(node):
            c = block.cells[k.cell] if 0 < k.cell < len(block.cells) else None
            if c is None or not textures_ok(c.tex):
                tr.append((k.time, 0))
                continue
            tr.append((k.time, k.cell))
        if tr:
            tracks.append(sorted(tr))
    # at every key time the LARGEST visible body cell is the pose; smaller simultaneous ones are
    # overlays (arm/hand pieces drawn on top of the pose frame)
    times = sorted({t for tr in tracks for t, _ in tr})
    seq, overlays = [], set()
    area = lambda cid: block.cells[cid].w * block.cells[cid].h
    for t in times:
        active = []
        for tr in tracks:
            cur = 0
            for kt, cid in tr:
                if kt <= t:
                    cur = cid
            if cur:
                active.append(cur)
        if not active:
            continue
        pose = max(active, key=area)
        overlays.update(a for a in active if a != pose)
        if not seq or seq[-1] != pose:
            seq.append(pose)
    out = []
    for cid in seq:  # keep first occurrence order
        if cid not in out:
            out.append(cid)
    body_cell_sequence.last_overlays = overlays - set(out)
    return out


def recolor(pal, hue_deg=0.0, sat=0.0, light=0.0):
    out = pal.copy()
    for i in range(1, 256):
        r, g, b, a = pal[i] / 255.0
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        h = (h + hue_deg / 360.0) % 1.0
        s = min(1, max(0, s + sat))
        l = min(1, max(0, l + light))
        out[i, :3] = np.clip(np.round(np.array(colorsys.hls_to_rgb(h, l, s)) * 255), 0, 255)
    return out


def convert(sequences, base_sprite: anm.AnmFile, motion_block, sprite_id, mapping=None, variants=None,
            report=None):
    """sequences: {(name, 'front'|'back'): [PIL frames]}.  base_sprite: the character's original anm
    (layout donor).  Returns a new AnmFile with repainted textures, block id = sprite_id."""
    mapping = mapping or DEFAULT_MAP
    variants = variants or [(0, 0, 0), (120, 0, 0), (200, 0.05, 0), (60, 0, 0.05), (0, -0.6, -0.05)]
    out = copy.deepcopy(base_sprite)
    blk = out.blocks[0]
    old_id = blk.id
    blk.id = sprite_id
    ntex = len(out.textures)
    rgba_tex = [np.asarray(anm.texture_to_image(out, i, 0)).copy() for i in range(ntex)]
    orig_tex = [t.copy() for t in rgba_tex]

    # animations from the shared motion set (cells -> character textures) + the character's own block
    sources = [(motion_block, a) for a in motion_block.animations] + [(blk, a) for a in blk.animations]
    by_id = {}
    for b, a in sources:
        by_id.setdefault(a.id, (b, a))
    cell_owner = {}  # (block_is_own, cell index) -> (anim id, frame)
    overlay_cells = set()
    assignments = []
    order = [i for i in PRIORITY] + sorted(i for i in by_id if i not in PRIORITY)
    for base_id in order:
        for aid in (base_id, base_id + 6):
            if aid not in by_id:
                continue
            name = mapping.get(base_id)
            if not name:
                continue
            frames = sequences.get((name, "back" if aid % 10 == 7 else "front")) or sequences.get((name, "front"))
            if not frames:
                continue
            b, a = by_id[aid]
            cells = body_cell_sequence(b, a, lambda t: t < ntex, shared=b is not blk)
            for ov in body_cell_sequence.last_overlays:
                overlay_cells.add((b is blk, ov))
            if not cells:
                continue
            for j, cid in enumerate(cells):
                key = (b is blk, cid)
                if key in cell_owner:
                    continue
                f = frames[min(len(frames) - 1, j * len(frames) // len(cells))]
                cell_owner[key] = (aid, f)
                assignments.append((b.cells[cid], f, aid))

    painted = 0
    clipped = []
    for c, frame_img, aid in assignments:
        fr = crop(frame_img)
        if fr is None:
            continue
        region = orig_tex[c.tex][c.y:c.y + c.h, c.x:c.x + c.w]
        if region.size == 0 or not (region[:, :, 3] > 0).any():
            continue
        ox, oy = frame_anchor(region)          # feet of the original pose inside the cell
        fx, fy = frame_anchor(fr)              # feet of the new frame
        dst = np.zeros((c.h, c.w, 4), np.uint8)
        x0, y0 = ox - fx, oy - fy
        sx0, sy0 = max(0, -x0), max(0, -y0)
        dx0, dy0 = max(0, x0), max(0, y0)
        w = min(fr.shape[1] - sx0, c.w - dx0)
        h = min(fr.shape[0] - sy0, c.h - dy0)
        if w > 0 and h > 0:
            dst[dy0:dy0 + h, dx0:dx0 + w] = fr[sy0:sy0 + h, sx0:sx0 + w]
            kept = (dst[:, :, 3] > 0).sum()
            total = (fr[:, :, 3] > 0).sum()
            loss = 1 - kept / max(1, total)
            if loss > 0.15:
                # the cell is a small piece (spin / curled-up poses): scale the frame to fit, centred
                # on the original piece instead of cropping most of it away
                ys, xs = np.nonzero(region[:, :, 3] > 0)
                cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
                s = min(c.w / fr.shape[1], c.h / fr.shape[0])
                nw, nh = max(1, int(fr.shape[1] * s)), max(1, int(fr.shape[0] * s))
                small = np.asarray(Image.fromarray(fr, "RGBA").resize((nw, nh), Image.LANCZOS))
                dst[:] = 0
                px = int(min(max(0, round(cx - nw / 2)), c.w - nw))
                py = int(min(max(0, round(cy - nh / 2)), c.h - nh))
                dst[py:py + nh, px:px + nw] = small
                loss = 0.0
            clipped.append((aid, c.w, c.h, fr.shape[1], fr.shape[0], loss))
        # keep a 1-px transparent border: texture filtering would otherwise pull in neighbouring cells
        dst[0, :] = 0
        dst[-1, :] = 0
        dst[:, 0] = 0
        dst[:, -1] = 0
        rgba_tex[c.tex][c.y:c.y + c.h, c.x:c.x + c.w] = dst
        painted += 1

    # erase overlay pieces (arm/hand parts of the old outfit) that are not used as poses anywhere,
    # without touching pixels that belong to a repainted pose cell
    pose_rects = [(c.tex, c.x, c.y, c.w, c.h) for c, _, _ in assignments]
    erased = 0
    for is_own, cid in overlay_cells:
        if (is_own, cid) in cell_owner:
            continue
        c = (blk if is_own else motion_block).cells[cid]
        if c.tex >= ntex or not c.w or not c.h:
            continue
        mask = np.ones((c.h, c.w), bool)
        for t, x, y, w, h in pose_rects:
            if t != c.tex:
                continue
            ix0, iy0 = max(x, c.x), max(y, c.y)
            ix1, iy1 = min(x + w, c.x + c.w), min(y + h, c.y + c.h)
            if ix0 < ix1 and iy0 < iy1:
                mask[iy0 - c.y:iy1 - c.y, ix0 - c.x:ix1 - c.x] = False
        rgba_tex[c.tex][c.y:c.y + c.h, c.x:c.x + c.w][mask] = 0
        erased += 1

    # one palette for all textures (index 0 transparent)
    stack = np.concatenate([t.reshape(-1, 4) for t in rgba_tex], 0)
    opaque = stack[:, 3] > 0
    side = int(np.ceil(np.sqrt(len(stack))))
    pad = np.zeros((side * side, 4), np.uint8)
    pad[:len(stack)] = stack
    img = Image.fromarray(pad.reshape(side, side, 4), "RGBA")
    q = img.quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    qp = np.array(q.getpalette("RGBA")[:255 * 4], np.uint8).reshape(-1, 4)
    pal0 = np.zeros((256, 4), np.uint8)
    pal0[1:1 + len(qp)] = qp
    idx = (np.asarray(q, np.int32).reshape(-1)[:len(stack)] + 1)
    idx[~opaque] = 0
    pos = 0
    for i, t in enumerate(rgba_tex):
        n = t.shape[0] * t.shape[1]
        out.textures[i].data = idx[pos:pos + n].astype(np.uint8).tobytes()
        pos += n
    # palettes: keep the count of the original (colour menu variants)
    for p in range(len(out.palettes)):
        hue, sat, light = variants[p % len(variants)]
        anm.set_palette(out, p, recolor(pal0, hue, sat, light) if (hue or sat or light) else pal0)
    if report is not None:
        report.update(painted=painted, cells=len(assignments), textures=ntex, erased=erased,
                      clipped=sorted(clipped, key=lambda x: -x[-1])[:12])
    return out
