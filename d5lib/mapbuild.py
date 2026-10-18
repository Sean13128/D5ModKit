"""Building a battle map out of blocks.

The blocks are the game's own: the Item World's building pieces (maps 60001-63011: grey stone slabs, bars, steps,
towers and pyramids; 70101-71705: themed blocks -- cracked desert, cyan ruins, snow, a Japanese town, checkered
floors, ice...), and any rectangle cut out of any map (a corner of Dried Up Wasteland with its rocks).  A build is a
grid and a list of placements (block, panel, quarter turns, lift in height steps); `compose` turns it into one map
package the game loads like any other: a .hex grid (corner heights, holes), one .obf mesh (every block's triangles
moved into place, textures shared), and the .gop / .chr of the map being edited (Geo Panels and units are placed on
the composed map with the usual tools).

Measures: a panel is 12 map units; a height step (one 'level' of the game's grid) is 4; the stone cube is 12 tall.
Corner heights are negative-up in the .hex (-13 = the top of a cube on the ground), mesh y is up.
"""
import hashlib
import os
import struct

import numpy as np

from . import mapfile
from . import obf as O

PANEL = 12.0
STEP = 4.0
CUBE = 12.0
VERSION = 1
THEMES = {600: "Stone: slabs and bars", 610: "Stone: steps and shapes", 620: "Stone: stairs and towers",
          630: "Stone: pyramids", 701: "Cracked desert", 702: "Cyan ruins", 703: "Pink shore", 704: "Mushroom woods",
          705: "Snow", 706: "Japanese town", 707: "Sand garden", 708: "(unused)", 709: "Red lanterns",
          710: "Garden bricks", 711: "Checkered floor", 712: "Brick plaza", 713: "Meadow", 714: "Purple magic",
          715: "Red circuits", 716: "Dark altar", 717: "Ice", 800: "Reward room"}
PIECE_RANGE = (60000, 80002)
SKELETON = 60001                       # the obf whose sections 0-5 (hierarchy, motion) every build keeps


def is_piece(mid):
    return PIECE_RANGE[0] <= int(mid) < PIECE_RANGE[1]


def theme_of(mid):
    return int(mid) // 100


def piece_ids(names):
    """piece map numbers among archive member names (mapNNNNN.lzs)"""
    out = []
    for n in names:
        if n.startswith("map") and n[3:8].isdigit() and is_piece(int(n[3:8])):
            out.append(int(n[3:8]))
    return sorted(out)


def key_of(spec):
    """a placement's block: an int (piece map) or (map, x0, y0, x1, y1) (a cut-out)"""
    if isinstance(spec, (list, tuple)):
        return tuple(int(v) for v in spec)
    return int(spec)


def key_json(key):
    return list(key) if isinstance(key, tuple) else int(key)


# ------------------------------------------------------------------------------------------------ one block
class Piece:
    """a block's panel grid and mesh, in its own frame: panel (i, j) at x = i * 12, z = j * 12"""

    def __init__(self, key, pkg):
        self.key = key
        hb = pkg.hex.blocks[0]
        region = key[1:] if isinstance(key, tuple) else None
        if region:
            x0, y0, x1, y1 = region
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(hb.width, x1), min(hb.height, y1)
            if x1 <= x0 or y1 <= y0:
                raise ValueError("empty cut-out")
        else:
            x0, y0, x1, y1 = 0, 0, hb.width, hb.height
        self.w, self.h = x1 - x0, y1 - y0
        self.corners = hb.corners[x0:x1, y0:y1].astype(np.float32).copy()
        self.no_panel = hb.no_panel[x0:x1, y0:y1].astype(bool).copy()
        self.env = bytes(hb.env)
        o = pkg.obf
        v = o.vertices()
        shift = np.array([x0 * PANEL, 0.0, y0 * PANEL], np.float32)
        self.meshes = []                 # (rows (n, 15), texture index in self.textures, head 48 bytes)
        for m in o.meshes:
            ix = m.indices.astype(np.int64)
            ix = ix[:len(ix) // 3 * 3]
            if not len(ix) or ix.max() >= len(v):
                continue
            rows = v[ix].astype(np.float32).copy()
            if region:
                tri = rows[:, 0:3].reshape(-1, 3, 3)
                c = tri.mean(axis=1)
                keep = ((c[:, 0] >= x0 * PANEL) & (c[:, 0] < x1 * PANEL) &
                        (c[:, 2] >= y0 * PANEL) & (c[:, 2] < y1 * PANEL))
                rows = rows.reshape(-1, 3, 15)[keep].reshape(-1, 15)
                if not len(rows):
                    continue
            rows[:, 0:3] -= shift
            self.meshes.append((rows, int(m.texture_index), bytes(m.raw_head)))
        self.textures = [bytes(e) for e in O.read_table(o.sections[9])]
        used = {t for _, t, _ in self.meshes}
        self.textures = [t if i in used else b"" for i, t in enumerate(self.textures)]
        self.sections = [bytes(s) for s in o.sections[:7]]
        self.name = f"map{key:05d}" if isinstance(key, int) else f"map{key[0]:05d} ({key[1]},{key[2]})-({key[3]},{key[4]})"

    @property
    def size(self):
        return self.w, self.h

    def heights(self):
        """ground height of each panel in steps over 0 (nan: no panel)"""
        g = -self.corners.mean(axis=2) / STEP
        return np.where(self.no_panel, np.nan, g)

    def footprint(self, rot):
        """the live panels (i, j) of the block turned `rot` quarter turns, and its size then"""
        nop = self.no_panel
        for _ in range(rot % 4):
            nop = _turn_grid(nop)
        return [(i, j) for i in range(nop.shape[0]) for j in range(nop.shape[1]) if not nop[i, j]], nop.shape


def _turn_grid(a):
    """a (w, h, ...) grid turned a quarter turn clockwise (seen from above, x right, y down): (x, y) -> (h-1-y, x)"""
    w, h = a.shape[:2]
    out = np.empty((h, w) + a.shape[2:], a.dtype)
    for x in range(w):
        for y in range(h):
            out[h - 1 - y, x] = a[x, y]
    return out


CORNER_TURN = [3, 2, 0, 1]             # the 4 corner heights (x0y0, x1y1, x1y0, x0y1) after a quarter turn


def _turn_corners(c):
    return _turn_grid(c)[..., CORNER_TURN]


def _turn_mesh(rows, h_units):
    """mesh rows turned a quarter turn clockwise about the grid's origin: (X, Z) -> (H - Z, X); normals, tangents"""
    out = rows.copy()
    for a in (0, 3, 6):
        x, z = rows[:, a].copy(), rows[:, a + 2].copy()
        out[:, a] = (h_units - z) if a == 0 else -z
        out[:, a + 2] = x
    return out


def _tri_normals(pos):
    t = pos.reshape(-1, 3, 3)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    l = np.linalg.norm(n, axis=1)
    return n / np.maximum(l, 1e-9)[:, None]


# ------------------------------------------------------------------------------------------------ the build
def empty_build(w=10, h=10):
    return {"version": VERSION, "size": [int(w), int(h)], "pieces": []}


def place(build, key, x, y, rot=0, lift=0):
    p = {"piece": key_json(key), "x": int(x), "y": int(y), "rot": int(rot) % 4, "lift": int(lift)}
    build["pieces"].append(p)
    return p


PICTURES = "pictures"                # patches/stages/pictures/<file>: the pictures blocks are retextured with


def look_of(pl):
    """(tint rgb 0-255 or None, {texture index: picture file name}) of a placement"""
    tint = pl.get("tint")
    tint = tuple(int(v) for v in tint)[:3] if tint else None
    tex = {int(k): str(v) for k, v in (pl.get("tex") or {}).items() if v}
    return tint, tex


def _retextured(entry, path):
    """a texture entry (attr + TXF) with the picture at `path` in it (scaled to the texture's size, same format)"""
    from PIL import Image
    t = O.Texture(entry)
    img = Image.open(path).convert("RGBA").resize((t.width, t.height), Image.Resampling.LANCZOS)
    t.replace_image(img, keep_format=True)
    return t.to_entry()


def covered(build, pieces):
    """{(x, y): index of the topmost placement covering that panel}"""
    out = {}
    for k, pl in enumerate(build["pieces"]):
        pc = pieces.get(key_of(pl["piece"]))
        if pc is None:
            continue
        cells, _ = pc.footprint(pl.get("rot", 0))
        for i, j in cells:
            out[(pl["x"] + i, pl["y"] + j)] = k
    return out


def compose(build, pieces, skeleton, base_pkg=None, name="map00000", pictures_dir=None):
    """-> mapfile.MapPackage of the build.  pieces: {key: Piece} (every block the build uses); skeleton: the Piece
    whose obf sections 0-5 / .hex header are copied (piece 60001); base_pkg: the map being edited, whose .gop and
    .chr (Geo Panels, units) the result keeps; pictures_dir: where a placement's "tex" pictures are."""
    retex_cache = {}
    W, H = int(build["size"][0]), int(build["size"][1])
    W, H = max(1, min(mapfile.GRID_MAX, W)), max(1, min(mapfile.GRID_MAX, H))
    corners = np.zeros((W + 1, H + 1, 4), np.float32)
    no_panel = np.ones((mapfile.GRID_MAX, mapfile.GRID_MAX), np.uint8)
    tex_index = {}
    textures = []
    groups = {}                        # (texture, head without count / texture) -> [rows]
    order = []
    for pl in build["pieces"]:
        pc = pieces.get(key_of(pl["piece"]))
        if pc is None:
            continue
        rot, lift = int(pl.get("rot", 0)) % 4, int(pl.get("lift", 0))
        px, py = int(pl["x"]), int(pl["y"])
        c, nop = pc.corners, pc.no_panel
        meshes = [(rows.copy(), t, head) for rows, t, head in pc.meshes]
        for _ in range(rot):
            h_units = nop.shape[1] * PANEL
            c, nop = _turn_corners(c), _turn_grid(nop)
            meshes = [(_turn_mesh(rows, h_units), t, head) for rows, t, head in meshes]
        w2, h2 = nop.shape
        for i in range(w2):
            for j in range(h2):
                X, Y = px + i, py + j
                if 0 <= X < W and 0 <= Y < H and not nop[i, j]:
                    corners[X, Y] = c[i, j] - lift * STEP
                    no_panel[X, Y] = 0
        shift = np.array([px * PANEL, lift * STEP, py * PANEL], np.float32)
        tint, tex_over = look_of(pl)
        tmap = {}
        for rows, t, head in meshes:
            if t not in tmap:
                entry = pc.textures[t] if t < len(pc.textures) else b""
                pic = tex_over.get(t)
                if pic and pictures_dir:
                    path = os.path.join(pictures_dir, os.path.basename(pic))
                    ck = (hashlib.sha1(entry).hexdigest(), os.path.basename(pic))
                    if ck not in retex_cache:
                        try:
                            retex_cache[ck] = _retextured(entry, path)
                        except Exception:
                            retex_cache[ck] = entry
                    entry = retex_cache[ck]
                hsh = hashlib.sha1(entry).hexdigest()
                if hsh not in tex_index:
                    tex_index[hsh] = len(textures)
                    textures.append(entry)
                tmap[t] = tex_index[hsh]
            rows = rows.copy()
            rows[:, 0:3] += shift
            if tint is not None:
                rows[:, 9:12] = np.clip(rows[:, 9:12] * (np.array(tint, np.float32) / 255.0), 0.0, 1.0)
            parts = [rows]
            if lift > 0:               # the block's walls go on down to the ground under it
                n = _tri_normals(rows[:, 0:3])
                side = np.repeat(np.abs(n[:, 1]) < 0.35, 3)
                walls = rows[side]
                if len(walls):
                    k = 1
                    while k * CUBE < lift * STEP + CUBE:
                        w = walls.copy()
                        w[:, 1] -= k * CUBE
                        parts.append(w)
                        k += 1
            gk = (tmap[t], head[8:])
            if gk not in groups:
                groups[gk] = []
                order.append(gk)
            groups[gk].extend(parts)
    # ---- the obf
    o = O.ObfFile(_skeleton_obf(skeleton))
    verts, entries, start = [], [], 0
    for gk in order:
        rows = np.concatenate(groups[gk]).astype("<f4")
        n = len(rows)
        head = bytearray(48)
        head[8:] = gk[1]
        struct.pack_into("<II", head, 0, n, gk[0])
        entries.append(bytes(head) + np.arange(start, start + n, dtype="<u4").tobytes())
        verts.append(rows)
        start += n
    o.sections[6] = O.build_table([struct.pack("<7I", len(entries), 0, 0, 256, 0, 0, 0) +
                                   struct.pack(f"<{len(entries)}I", *range(len(entries)))])
    o.sections[7] = O.build_table(entries)
    o.sections[8] = (np.concatenate(verts) if verts else np.zeros((0, 15), "<f4")).astype("<f4").tobytes()
    o.sections[9] = O.build_table(textures or [skeleton.textures[0]])
    o._tex = o._mesh = None
    obf_bytes = o.to_bytes()
    # ---- the hex
    hb = mapfile.HexBlock(_skeleton_hex(skeleton))
    hb.resize(W, H)
    hb.corners[:] = corners
    hb.no_panel[:] = no_panel
    hb.flag_a[:] = 0
    hb.motion_ids = [0, -1, -1, -1, -1]
    hex_bytes = hb.to_bytes()
    # ---- the rest
    if base_pkg is not None:
        base_pkg.commit()
        gop_bytes = base_pkg.get("gop")
        chr_bytes = base_pkg.get("chr")
    else:
        gop_bytes = bytes(mapfile.GopBlock.SIZE)
        chr_bytes = struct.pack("<HH", 1, 0) + bytes(12)
    gb = mapfile.GopFile(gop_bytes)
    gb.blocks[0].set_panels([(x, y, c) for x, y, c in gb.blocks[0].panels() if x < W and y < H and not no_panel[x, y]])
    members = [(f"{name}.hex", hex_bytes), (f"{name}.chr", chr_bytes), (f"{name}.obf", obf_bytes),
               (f"{name}.gop", gb.to_bytes())]
    return mapfile.MapPackage(members, name)


def _skeleton_obf(skel):
    """an obf with the skeleton's sections 0-6 and empty 7-9 (to_bytes fills them)"""
    secs = list(skel.sections) + [O.build_table([]), b"", O.build_table([])]
    offs, pos = [], 8 + 4 * O.N_SECTIONS
    for s in secs:
        offs.append(pos)
        pos += len(s)
    return struct.pack(f"<II{O.N_SECTIONS}I", pos, 2, *offs) + b"".join(secs)


def _skeleton_hex(skel):
    """a one-panel .hex block with the skeleton's env block"""
    W = H = 1
    out = bytearray(struct.pack("<3I5i", 6, W, H, 0, -1, -1, -1, -1))
    out += skel.env
    out += np.zeros(((W + 1) * (H + 1) * 4,), "<f4").tobytes()
    out += bytes(mapfile.GRID_MAX * mapfile.GRID_MAX)
    out += b"\1" * (mapfile.GRID_MAX * mapfile.GRID_MAX)
    return bytes(out)


# ------------------------------------------------------------------------------------------------ loading blocks
class Library:
    """blocks by key, read once: read_pkg(map id) -> MapPackage (the game's archives, or the kit's layered files)"""

    def __init__(self, read_pkg):
        self.read_pkg = read_pkg
        self.pieces = {}
        self.pkgs = {}

    def package(self, mid):
        if mid not in self.pkgs:
            self.pkgs[mid] = self.read_pkg(int(mid))
        return self.pkgs[mid]

    def get(self, key):
        key = key_of(key)
        if key not in self.pieces:
            mid = key if isinstance(key, int) else key[0]
            self.pieces[key] = Piece(key, self.package(mid))
        return self.pieces[key]

    def skeleton(self):
        return self.get(SKELETON)

    def for_build(self, build):
        return {key_of(p["piece"]): self.get(p["piece"]) for p in build["pieces"]}


def whole_map_build(pkg, mid):
    """a build that is this map as one block (the first step of rebuilding an existing map)"""
    hb = pkg.hex.blocks[0]
    b = empty_build(hb.width, hb.height)
    place(b, (int(mid), 0, 0, hb.width, hb.height), 0, 0)
    return b
