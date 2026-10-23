"""A battle map as the skill preview shows it: the stage's 3D terrain (mapNNNNN.obf) and its panel heights.

The terrain mesh is in map units (a panel = 12) with y UP (the engine flips it into its y-down world, as it does
effect models); panel (i, j) is centred at ((i + 0.5) * 12, (j + 0.5) * 12) and its ground is at world y = its
corner heights (negative = up).  Seen on map 101
(the first Netherworld stage, the cracked earth of the skill recordings): Killia stood on panel (7, 4) at
(90, -18, 54) -- corners -18.
"""
import os

import numpy as np

from . import mapfile

PANEL = 12.0
DEFAULT_MAP = 101
_cache = {}


class BattleMap:
    def __init__(self, map_id, data_dir=None, pkg=None):
        if pkg is None:
            pkg = mapfile.MapPackage.from_archive(int(map_id), data_dir=data_dir)
        self.id = int(map_id)
        self.rev = 0                     # bumped by an editor when the terrain changes (GPU buffers are keyed on it)
        blk = pkg.hex.blocks[0]
        self.width, self.height = blk.width, blk.height
        self.ground = -blk.corners[:blk.width, :blk.height].mean(axis=2)       # height of each panel (up = +)
        self.no_panel = blk.no_panel[:blk.width, :blk.height].astype(bool)
        o = pkg.obf
        v = o.vertices()
        self.meshes = []
        for m in o.meshes:
            ix = m.indices.astype(np.int64)
            ix = ix[:len(ix) // 3 * 3]
            if not len(ix) or ix.max() >= len(v):
                continue
            self.meshes.append(dict(pos=np.ascontiguousarray(v[ix, 0:3], np.float32),
                                    uv=np.ascontiguousarray(v[ix, 13:15], np.float32),
                                    vcol=np.ascontiguousarray(np.clip(v[ix, 9:13] * 2.0, 0, 2), np.float32),
                                    tex=m.texture_index, color=np.array(m.color, np.float32) / 255.0,
                                    flags=bytes(m.flags)))
        self.textures = o.textures
        self._rgba = {}

    def rgba(self, ti):
        a = self._rgba.get(ti)
        if a is None:
            try:
                a = np.asarray(self.textures[ti].to_image().convert("RGBA"), np.uint8)
            except (ValueError, IndexError):
                a = np.full((4, 4, 4), 200, np.uint8)
            self._rgba[ti] = a
        return a

    def has_panel(self, i, j):
        return 0 <= i < self.width and 0 <= j < self.height and not self.no_panel[i, j]

    def panel_centre(self, i, j):
        """game frame point on the ground at the centre of panel (i, j)"""
        h = float(self.ground[i, j]) if self.has_panel(i, j) else 0.0
        return np.array([(i + 0.5) * PANEL, -h, (j + 0.5) * PANEL])

    def default_panel(self, reach=3):
        """a panel with panels around it in all 4 directions (the skill's target fits whichever way it faces)"""
        best, score = (self.width // 2, self.height // 2), -1
        for i in range(self.width):
            for j in range(self.height):
                if not self.has_panel(i, j):
                    continue
                s = sum(self.has_panel(i + di * k, j + dj * k)
                        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)) for k in range(1, reach + 1))
                s = s * 100 - abs(i - self.width / 2) - abs(j - self.height / 2)
                if s > score:
                    best, score = (i, j), s
        return best


def from_package(pkg, map_id=0):
    """a BattleMap of a map package being edited (not cached)"""
    return BattleMap(map_id, pkg=pkg)


def load(map_id, data_dir):
    """cached BattleMap (None when there is no such map)"""
    key = (int(map_id), os.path.normcase(data_dir))
    if key not in _cache:
        try:
            _cache[key] = BattleMap(map_id, data_dir)
        except Exception:
            _cache[key] = None
    return _cache[key]


def map_ids(data_dir):
    """the battle maps in the game archives"""
    from .nispack import NisPack
    out = set()
    for lang in ("JP", "EN"):
        p = os.path.join(data_dir, "Map", f"Map_{lang}.dat")
        if os.path.exists(p):
            with NisPack(p) as pk:
                out |= {int(n[3:8]) for n in pk.by_name if n.startswith("map") and n.endswith(".lzs")}
    return sorted(out)
