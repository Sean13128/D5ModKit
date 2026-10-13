"""Character faces (status panel / character list): resident block 9017, one animation per colour id
(char.dat color_id), drawn as a 256x256 frame + a 204x204 face picture on ARGB textures.

add_faces() gives new colour ids (outfit rows) their own face: the base character's face animation is
cloned for the new id with a new cell, and the picture goes into free space of the block's textures.
The resident pack is ~415 MB, so the result is re-encoded with lzs_splice (only the edited bytes are
stored anew).
"""
import copy
import struct

import numpy as np
from PIL import Image

from . import anm, lzs, lzs_splice

FACE_BLOCK = 9017
BANNER_BLOCK = 9018     # name banners of the skill cut-ins, animation = colour id
FACE_SIZE = 204
PAD = 4


def _find_block(data, block_id):
    h0, dsize, ntex, npal, nblk = struct.unpack_from("<5I", data, 0)
    pos, tb = anm.FILE_HEADER_SIZE, 0
    for _ in range(nblk):
        size, bid = struct.unpack_from("<IH", data, pos)
        blk, size2 = anm.AnmBlock.parse(data, pos)
        if bid == block_id:
            return pos, size, tb, blk
        tb += len(blk.texture_infos)
        pos += size
    raise KeyError(f"block {block_id} not found")


def _image_table(data):
    h0, dsize, ntex, npal, nblk = struct.unpack_from("<5I", data, 0)
    base = h0 + 0x10
    first = base - (ntex + npal) * anm.IMG_HEADER_SIZE
    out = []
    for i in range(ntex + npal):
        r = first + i * anm.IMG_HEADER_SIZE
        fmt = data[r:r + 4]
        w, h, unk, off = struct.unpack_from("<HHII", data, r + 4)
        out.append((fmt, w, h, base + off))
    return out


GRID = 4                 # faces are placed on a 4-px grid


def _coarse(used, step=GRID):
    """occupancy on the placement grid: a grid cell is busy when any of its pixels is used"""
    H, W = used.shape
    gh, gw = -(-H // step), -(-W // step)
    pad = np.zeros((gh * step, gw * step), bool)
    pad[:H, :W] = used
    return pad.reshape(gh, step, gw, step).any(axis=(1, 3))


def _free_spot(grid, w, h, need, step=GRID):
    """Top-left (px) of the first free need x need square on the grid (row-major, like the game's own layout
    order), or None.  grid: _coarse of the texture's used mask (kept up to date by the caller)."""
    k = -(-need // step)
    gh, gw = grid.shape
    if gh < k or gw < k:
        return None
    ii = np.zeros((gh + 1, gw + 1), np.int32)
    ii[1:, 1:] = grid.cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
    s = ii[k:, k:] - ii[:-k, k:] - ii[k:, :-k] + ii[:-k, :-k]
    for gy, gx in np.argwhere(s == 0):
        x, y = int(gx) * step, int(gy) * step
        if x + need <= w and y + need <= h:
            return x, y
    return None


def _clone_anim(b, src_id, dst_id, face_cell):
    """Copy animation src_id's node tree to a new animation dst_id (replacing an existing one); the
    key that shows the source face picture shows face_cell instead."""
    A = {a.id: a for a in b.animations}
    src = A[src_id]
    order = [ni for ni, d, p in b.walk(src.root)]
    remap = {ni: len(b.nodes) + k for k, ni in enumerate(order)}
    # the face picture = the largest non-frame cell (the frame is the 256x256 cell)
    keys = [(ni, k) for ni in order for k in range(b.nodes[ni].first_key, b.nodes[ni].first_key +
                                                     b.nodes[ni].num_keys) if b.nodes[ni].first_key >= 0]
    face_keys = [k for ni, k in keys if b.keys[k].cell and b.cells[b.keys[k].cell].w == FACE_SIZE]
    new_nodes = []
    for ni in order:
        n = copy.deepcopy(b.nodes[ni])
        if n.first_key >= 0 and n.num_keys:
            first = len(b.keys)
            for k in range(n.first_key, n.first_key + n.num_keys):
                key = copy.deepcopy(b.keys[k])
                if k in face_keys and face_cell is not None:
                    key.cell = face_cell
                b.keys.append(key)
            n.first_key = first
        n.child = remap.get(n.child, -1) if n.child >= 0 else -1
        n.next = remap.get(n.next, -1) if n.next >= 0 else -1
        new_nodes.append(n)
    b.nodes += new_nodes
    root = remap[src.root]
    if dst_id in A:
        A[dst_id].root = root
    else:
        b.animations.append(anm.Animation(dst_id, root))
        b.animations.sort(key=lambda a: a.id)


def add_faces(old_raw: bytes, faces, log=None, banners=(), grow_now=False) -> bytes:
    """faces: [(new colour id, template colour id, PIL image or None)] for the face block 9017;
    banners: [(new colour id, template colour id)] for the name banner block 9018 (copied as is)
    -> new LZS resident pack.  The same picture given for several ids is stored once.  When the block's textures
    have no room left, they grow taller, one after the other (GROW_TEX first, then the others, widest first, up to
    16384 each: thousands of faces; grow_now: grow even when there is room, and put the new faces there -- for
    testing)."""
    data = lzs.decompress(old_raw)
    reps = []                        # (old offset, old length, new bytes): replaced / inserted spans
    edits = []                       # (absolute offset in the OLD data, bytes)
    pos, size, tb, b = _find_block(data, FACE_BLOCK)
    grows = _patch_face_block(data, b, tb, faces, edits, log, grow_now)
    b.fix_virtual_offsets()
    reps.append((pos, size, b.to_bytes()))
    if banners:
        pos2, size2, tb2, b2 = _find_block(data, BANNER_BLOCK)
        have = {a.id for a in b2.animations}
        for new_id, tmpl_id in banners:
            if tmpl_id in have:
                _clone_anim(b2, tmpl_id, new_id, None)
        b2.fix_virtual_offsets()
        reps.append((pos2, size2, b2.to_bytes()))
    return _assemble(data, old_raw, reps, edits, grows)


def _assemble(data, old_raw, reps, edits, grows):
    """the resident pack with rewritten blocks (reps: (old offset, old length, new bytes)), in-place byte edits
    (old offsets) and grown textures ([(global image index, width, old height, new height, added rows)]) -> LZS,
    only the changed parts re-encoded"""
    h0, dsize, ntex, npal, nblk = struct.unpack_from("<5I", data, 0)
    body_delta = sum(len(nb) - sz for _, sz, nb in reps)
    grown = 0
    if grows:
        imgs = _image_table(data)
        base = h0 + 0x10
        first = base - (ntex + npal) * anm.IMG_HEADER_SIZE
        added = {}
        for g, w, old_h, new_h, ins in grows:
            fmt, _, _, abs_off = imgs[g]
            added[g] = len(ins)
            reps.append((abs_off + w * old_h * 4, 0, bytes(ins)))      # the new rows, after the old pixels
            r = first + g * anm.IMG_HEADER_SIZE
            edits.append((r + 4, struct.pack("<HH", w, new_h)))
        grown = sum(added.values())
        for j in range(ntex + npal):                                 # pictures after a grown one move
            sh = sum(n for g, n in added.items() if g < j)
            if sh:
                rj = first + j * anm.IMG_HEADER_SIZE
                off = struct.unpack_from("<I", data, rj + 12)[0]
                edits.append((rj + 12, struct.pack("<I", off + sh)))
    reps.sort()
    # new file = old data with the rewritten blocks; header h0 grows by the blocks' size change
    parts, runs = [], []
    src = 0
    newpos = 0
    shifts = []                      # (old offset from which the shift applies, shift)
    shift = 0
    for p, sz, nb in reps:
        parts.append(data[src:p])
        runs.append((newpos, src, p - src))
        newpos += p - src
        parts.append(nb)
        newpos += len(nb)
        shift += len(nb) - sz
        shifts.append((p + sz, shift))
        src = p + sz
    parts.append(data[src:])
    runs.append((newpos, src, len(data) - src))
    new = bytearray(b"".join(parts))
    struct.pack_into("<II", new, 0, h0 + body_delta, dsize + grown)

    def to_new(o):
        sh = 0
        for start, s_ in shifts:
            if o >= start:
                sh = s_
        return o + sh

    for o, bts in edits:
        n = to_new(o)
        new[n:n + len(bts)] = bts
    # split the unchanged runs around the header and the edits
    cuts = sorted([(0, 16)] + [(o, o + len(bts)) for o, bts in edits])
    final = []
    for nn, oo, ln in runs:
        start, end = oo, oo + ln
        for c0, c1 in cuts:
            if c1 <= start or c0 >= end:
                continue
            if c0 > start:
                final.append((nn + (start - oo), start, c0 - start))
            start = max(start, c1)
        if end > start:
            final.append((nn + (start - oo), start, end - start))
    final = [r for r in final if r[2] > 0]
    return lzs_splice.splice(old_raw, bytes(new), final)


GROW_TEX = 13            # block-local texture that grows (1024 x 512 ARGB in the game)
GROW_STEP = 8            # face rows added at a time
MAX_HEIGHT = 16384


def _patch_face_block(data, b, tb, faces, edits, log, grow_now=False):
    """-> [(global image index, width, old height, new height, bytearray of the added rows)] of the grown textures"""
    import hashlib
    imgs = _image_table(data)
    tex = {}
    used = {}
    grid = {}
    for ti in range(len(b.texture_infos)):
        fmt, w, h, off = imgs[tb + ti]
        if fmt[0] == anm.FMT_INDEXED8:
            continue
        a = np.frombuffer(data, np.uint8, w * h * 4, off).reshape(h, w, 4)
        m = a[:, :, 0] > 0
        for c in b.cells:
            if c.tex == ti and c.w:
                m[max(0, c.y - PAD):c.y + c.h + PAD, max(0, c.x - PAD):c.x + c.w + PAD] = True
        tex[ti] = (w, h, off)
        used[ti] = m
        grid[ti] = _coarse(m)
    # textures that grow, in turn: GROW_TEX (tested in game), then the others, widest and shortest first
    queue = ([GROW_TEX] if GROW_TEX in tex else []) + sorted(
        (t for t in tex if t != GROW_TEX and tex[t][0] >= 2 * (FACE_SIZE + 2 * PAD)),
        key=lambda t: (-tex[t][0], tex[t][1]))
    state = {"i": 0}
    grows = {}                                   # texture -> {"h", "old", "ins"}

    def grow_rows(n_faces_rows):
        while state["i"] < len(queue):
            gt = queue[state["i"]]
            gw = tex[gt][0]
            g = grows.setdefault(gt, {"h": tex[gt][1], "old": tex[gt][1], "ins": bytearray()})
            new_h = min(MAX_HEIGHT, g["h"] + n_faces_rows * (FACE_SIZE + 2 * PAD))
            if new_h > g["h"]:
                add = new_h - g["h"]
                g["ins"] += bytes(gw * add * 4)
                g["h"] = new_h
                used[gt] = np.vstack([used[gt], np.zeros((add, gw), bool)])
                grid[gt] = _coarse(used[gt])
                b.texture_infos[gt].height = new_h
                return True
            state["i"] += 1                      # this one is full: the next one grows
        return False

    if grow_now:
        if grow_now == 2:                        # testing: the second texture of the queue
            state["i"] = 1
        grow_rows(GROW_STEP)
    tmpl_face = next(c for c in b.cells if c.w == FACE_SIZE)
    cells = {}                                   # picture hash -> cell index
    for new_id, tmpl_id, img in faces:
        if img is None:                          # no picture: same face as the base character
            _clone_anim(b, tmpl_id, new_id, None)
            continue
        pic = np.asarray(img.convert("RGBA").resize((FACE_SIZE, FACE_SIZE), Image.LANCZOS))
        key = hashlib.sha1(pic.tobytes()).hexdigest()
        if key in cells:
            _clone_anim(b, tmpl_id, new_id, cells[key])
            continue
        argb = np.ascontiguousarray(pic[:, :, [3, 0, 1, 2]])
        spot = None
        order = sorted(tex, key=lambda t: -used[t].shape[0])
        if grow_now and grows:
            order = list(grows)
        for _ in range(len(queue) * (MAX_HEIGHT // FACE_SIZE) + 1):
            for ti in order:
                h = used[ti].shape[0]
                p = _free_spot(grid[ti], tex[ti][0], h, FACE_SIZE + 2 * PAD)
                if p:
                    spot = (ti, p[0] + PAD, p[1] + PAD)
                    break
            if spot or not grow_rows(GROW_STEP):
                break
        if spot is None:
            raise RuntimeError("no texture space left for another face")
        ti, x, y = spot
        w, h0, off = tex[ti]
        used[ti][y - PAD:y + FACE_SIZE + PAD, x - PAD:x + FACE_SIZE + PAD] = True
        y0, y1 = (y - PAD) // GRID, -(-(y + FACE_SIZE + PAD) // GRID)
        x0, x1 = (x - PAD) // GRID, -(-(x + FACE_SIZE + PAD) // GRID)
        grid[ti][y0:y1, x0:x1] = True
        g = grows.get(ti)
        for r in range(FACE_SIZE):
            row = argb[r].tobytes()
            if g and y + r >= g["old"]:              # in the added rows
                o = ((y + r - g["old"]) * w + x) * 4
                g["ins"][o:o + len(row)] = row
            else:
                edits.append((off + ((y + r) * w + x) * 4, row))
        b.cells.append(anm.Cell(ti, tmpl_face.pal, tmpl_face.unk2, tmpl_face.flags, x, y, FACE_SIZE, FACE_SIZE,
                                tmpl_face.unk8))
        cells[key] = len(b.cells) - 1
        _clone_anim(b, tmpl_id, new_id, cells[key])
        if log:
            log(f"  face {new_id}: texture {ti} at {x},{y}")
    out = []
    for gt, g in sorted(grows.items()):
        if g["h"] == g["old"]:
            continue
        if log:
            log(f"  face texture {gt} grown to {tex[gt][0]} x {g['h']}")
        out.append((tb + gt, tex[gt][0], g["old"], g["h"], g["ins"]))
    return out


# ------------------------------------------------------------------------------------------ Overload title banners
OVL_BANNER_BLOCK = 9032  # Overload title banners: animation V (0x1404b2fc0's value, 100 .. 500) = the banner, which
                         # shows animation 1000 + V (the name picture) through a key's attached-animation list
BANNER_GROW = (7, 8, 4)  # block-local textures that grow for new name pictures (960 wide, ARGB)


def _cloned_keys(b, fn):
    n0 = len(b.keys)
    fn()
    return range(n0, len(b.keys))


def _param_lists(b):
    """{params index: [anim ids]} of the lists keys point at ((anim id, 0) pairs ending with -1)"""
    out = {}
    for k in b.keys:
        i, ids = k.param, []
        if i in out or i >= len(b.params):
            continue
        while i + 1 < len(b.params) and b.params[i] != -1:
            ids.append(b.params[i])
            i += 2
        out[k.param] = ids
    return out


def add_overload_banners(old_raw: bytes, banners, log=None) -> bytes:
    """banners: [(value V (even, new), template value T, PIL RGBA name picture)] -> new LZS resident pack where
    banner V is a copy of banner T showing the picture (animation V + 1) instead of T's name.  The pictures go into
    rows added below textures BANNER_GROW (side by side when they fit): hundreds per texture."""
    data = lzs.decompress(old_raw)
    pos, size, tb, b = _find_block(data, OVL_BANNER_BLOCK)
    imgs = _image_table(data)
    A = {a.id: a for a in b.animations}
    lists = _param_lists(b)
    grows = {}                                    # local texture -> {"old", "h", "ins", "x", "shelf"}
    queue = [t for t in BANNER_GROW if t < len(b.texture_infos)]
    state = {"i": 0}

    def place(w, h):
        while state["i"] < len(queue):
            t = queue[state["i"]]
            fmt, tw, th, off = imgs[tb + t]
            g = grows.setdefault(t, {"old": th, "h": th, "ins": bytearray(), "x": tw, "shelf": th, "sh": 0})
            if w > tw:
                state["i"] += 1
                continue
            if g["x"] + w > tw or h > g["sh"]:    # a new shelf below
                if g["h"] + h > MAX_HEIGHT:
                    state["i"] += 1
                    continue
                g["shelf"], g["sh"], g["x"] = g["h"], h, 0
                g["ins"] += bytes(tw * h * 4)
                g["h"] += h
            x, y = g["x"], g["shelf"]
            g["x"] += w + PAD
            return t, x, y
        raise RuntimeError("no texture space left for another Overload banner")

    for value, tmpl, img in banners:
        if value in A or value + 1 in A:
            raise ValueError(f"banner {value}: animation already exists")
        pic_src = 1000 + tmpl
        if tmpl not in A or pic_src not in A:
            raise KeyError(f"no Overload banner {tmpl}")
        # the template's name picture: its cells, transforms, pivots and the centre of its letters on screen
        order = [ni for ni, d, p in b.walk(A[pic_src].root)]
        pkeys = [k for ni in order if b.nodes[ni].first_key >= 0
                 for k in range(b.nodes[ni].first_key, b.nodes[ni].first_key + b.nodes[ni].num_keys)]
        cells_t = sorted({b.keys[k].cell for k in pkeys if b.keys[k].cell})
        c0 = b.cells[cells_t[0]]
        fmt, tw, th, off = imgs[tb + c0.tex]
        a = np.frombuffer(data, np.uint8, tw * th * 4, off).reshape(th, tw, 4)[c0.y:c0.y + c0.h, c0.x:c0.x + c0.w]
        cols = np.nonzero((a[:, :, 0] > 16).any(0))[0]
        mid = (cols[0] + cols[-1] + 1) / 2 if len(cols) else c0.w / 2
        pic = np.asarray(img.convert("RGBA"))
        h, w = pic.shape[:2]
        t, x, y = place(w, h)
        g = grows[t]
        argb = np.ascontiguousarray(pic[:, :, [3, 0, 1, 2]])
        twid = imgs[tb + t][1]
        for r in range(h):
            o = ((y + r - g["old"]) * twid + x) * 4
            g["ins"][o:o + w * 4] = argb[r].tobytes()
        b.pivots.append(anm.Pivot(w // 2, h // 2))
        piv = len(b.pivots) - 1
        cell_map, xf_map = {}, {}
        for ci in cells_t:
            c = b.cells[ci]
            b.cells.append(anm.Cell(t, c.pal, c.unk2, c.flags, x, y, w, h, c.unk8))
            cell_map[ci] = len(b.cells) - 1
        for k in _cloned_keys(b, lambda: _clone_anim(b, pic_src, value + 1, None)):
            key = b.keys[k]
            if key.cell in cell_map:
                if key.xform not in xf_map:
                    xt = b.transforms[key.xform]
                    centre = xt.x - b.pivots[xt.pivot].x + mid
                    b.transforms.append(anm.Transform(int(round(centre)), xt.y, piv, xt.unk, xt.sx, xt.sy, xt.rot))
                    xf_map[key.xform] = len(b.transforms) - 1
                key.xform = xf_map[key.xform]
                key.cell = cell_map[key.cell]
        new_list = None
        for k in _cloned_keys(b, lambda: _clone_anim(b, tmpl, value, None)):
            key = b.keys[k]
            ids = lists.get(key.param, [])
            if pic_src in ids:
                if new_list is None:
                    new_list = len(b.params)
                    for i in ids:
                        b.params += [value + 1 if i == pic_src else i, 0]
                    b.params.append(-1)
                key.param = new_list
        A = {a.id: a for a in b.animations}
        if log:
            log(f"  Overload banner {value} (style of {tmpl}): texture {t} at {x},{y}, {w} x {h}")
    for t, g in grows.items():
        b.texture_infos[t].height = g["h"]
    b.fix_virtual_offsets()
    out = [(tb + t, imgs[tb + t][1], g["old"], g["h"], g["ins"]) for t, g in sorted(grows.items()) if g["h"] > g["old"]]
    return _assemble(data, old_raw, [(pos, size, b.to_bytes())], [], out)


# ------------------------------------------------------------------------------------------ whole new blocks
RENAMED_BASE = 65000     # a block replaced by a new one keeps its data under this id (+ k)


def add_resident_blocks(old_raw: bytes, blocks, log=None) -> bytes:
    """blocks: {block id: AnmFile holding that one block and its own textures / palettes} -> new LZS resident pack
    with each appended as a block of its own (its textures after the pack's last texture, its palettes after the
    last palette: the game numbers a block's pictures by counting the blocks before it).  A block of the pack with
    the same id is renamed out of the way (RENAMED_BASE + k), so the new one is found.  Only the changed parts are
    re-encoded (lzs_splice).  New monster classes need their standing picture (sprite family + 2) here: the game
    takes it from the resident pack only, and a monster family without one crashes the Hire Character list."""
    IH = anm.IMG_HEADER_SIZE

    def align(o):
        return (o + anm.IMG_ALIGN - 1) // anm.IMG_ALIGN * anm.IMG_ALIGN

    def nbytes(fmt, w, h):
        return w * h * (1 if fmt[0] == anm.FMT_INDEXED8 else 4)

    data = lzs.decompress(old_raw)
    h0, dsize, ntex, npal, nblk = struct.unpack_from("<5I", data, 0)
    pos, id_pos = anm.FILE_HEADER_SIZE, {}
    for _ in range(nblk):
        size, bid = struct.unpack_from("<IH", data, pos)
        id_pos.setdefault(bid, []).append(pos + 4)
        pos += size
    blocks_end = pos
    base = h0 + 0x10
    if base - (ntex + npal) * IH != blocks_end:
        raise ValueError("unexpected resident pack layout")
    hdr = [(bytes(data[blocks_end + i * IH:blocks_end + i * IH + 4]),)
           + struct.unpack_from("<HHII", data, blocks_end + i * IH + 4) for i in range(ntex + npal)]
    tex_end = hdr[ntex - 1][4] + nbytes(hdr[ntex - 1][0], hdr[ntex - 1][1], hdr[ntex - 1][2])
    pal_start = hdr[ntex][4] if npal else align(tex_end)
    # the new blocks, their pictures
    edits, k = [], 0
    body, new_tex, new_pal = b"", [], []
    for bid, af in sorted(blocks.items()):
        for p in id_pos.get(bid, []):
            edits.append((p, struct.pack("<H", RENAMED_BASE + k)))
            k += 1
        b = af.blocks[0]
        b.id = bid
        b.fix_virtual_offsets()
        body += b.to_bytes()
        new_tex += af.textures[:len(b.texture_infos)]
        new_pal += af.palettes[:len(b.palette_infos)]
    # image data (offsets from the image base): old textures | new textures | old palettes | new palettes
    o = align(tex_end)
    tex_hdrs, tex_data = bytearray(), bytearray(bytes(o - tex_end))
    for im in new_tex:
        o2 = align(o)
        tex_data += bytes(o2 - o)
        tex_hdrs += im.fmt + struct.pack("<HHII", im.width, im.height, im.unk, o2)
        tex_data += im.data
        o = o2 + len(im.data)
    new_pal_start = align(o)
    tex_data += bytes(new_pal_start - o)
    shift = new_pal_start - pal_start
    pal_hdrs = bytearray()
    for fmt, w, h, unk, off in hdr[ntex:]:
        pal_hdrs += fmt + struct.pack("<HHII", w, h, unk, off + shift)
    o = dsize + shift
    pal_data = bytearray()
    for im in new_pal:
        o2 = align(o)
        pal_data += bytes(o2 - o)
        pal_hdrs += im.fmt + struct.pack("<HHII", im.width, im.height, im.unk, o2)
        pal_data += im.data
        o = o2 + len(im.data)
    new_dsize = o
    ntex2, npal2 = ntex + len(new_tex), npal + len(new_pal)
    body_end = blocks_end + len(body)
    base2 = body_end + (ntex2 + npal2) * IH
    head = struct.pack("<5I", base2 - 0x10, new_dsize, ntex2, npal2, nblk + len(blocks)) + \
        bytes(data[20:anm.FILE_HEADER_SIZE])
    old_tex_hdrs = data[blocks_end:blocks_end + ntex * IH]
    trailing = data[base + dsize:]
    parts = [head, data[anm.FILE_HEADER_SIZE:blocks_end], body, old_tex_hdrs, bytes(tex_hdrs), bytes(pal_hdrs),
             data[base:base + tex_end], bytes(tex_data), data[base + pal_start:base + dsize], bytes(pal_data),
             trailing]
    new = bytearray(b"".join(parts))
    for p, bts in edits:
        new[p:p + len(bts)] = bts
    # unchanged stretches (new offset, old offset, length)
    runs = []
    cuts = sorted(p for p, _ in edits)
    a = anm.FILE_HEADER_SIZE
    for p in cuts + [blocks_end]:
        if p > a:
            runs.append((a, a, p - a))
        a = p + 2
    runs.append((body_end, blocks_end, ntex * IH))
    runs.append((base2, base, tex_end))
    runs.append((base2 + new_pal_start, base + pal_start, dsize - pal_start))
    if trailing:
        runs.append((base2 + new_dsize, base + dsize, len(trailing)))
    if log:
        log(f"  resident pack: block(s) {', '.join(map(str, sorted(blocks)))} added "
            f"({len(new_tex)} texture(s), {len(new_pal)} palette(s))")
    return lzs_splice.splice(old_raw, bytes(new), [r for r in runs if r[2] > 0])
