"""Disgaea 5 battle-map files (members of Map/Map_*.dat -> mapNNNNN.lzs -> 'pac').

    mapNNNNN.hex   terrain grid: size, per-panel corner heights, 'no panel' mask, env/light block
    mapNNNNN.chr   placed units: enemies, NPCs, map objects (boxes, pillars...), Geo Symbols
    mapNNNNN.gop   Geo Panel colour list (x, y, colour)
    mapNNNNN.obf   3D terrain mesh + textures (see d5lib/obf.py)

The base panel is NOT in the map; it is dungeon.dat bytes 0x36/0x37 (see DungeonTable).
Every class here keeps the original bytes and only patches known fields, so parse->serialize is
byte-identical (verified on all 448 JP + 10 EN maps).  See docs/MAPS_AND_OBJECTS.md.
"""
import os
import struct

import numpy as np

from . import lzs, pac
from .util import DATA

GRID_MAX = 128                       # engine arrays are 128x128
PANEL_COLORS = {0: "none", 1: "red", 2: "green", 3: "blue", 4: "yellow", 5: "purple", 6: "cyan"}
PANEL_RGB = {1: (230, 40, 40), 2: (40, 200, 60), 3: (40, 90, 240), 4: (240, 220, 40),
             5: (170, 60, 220), 6: (40, 220, 230)}
GEO_SYMBOL_IDS = (4810, 4811)        # char.dat ids named "GS"
ITEM_SYMBOL_IDS = (5260, 5261)
TEAM_NAMES = {1: "enemy", 2: "neutral/object", 3: "team3", 4: "team4", 5: "team5"}


# ============================================================================ .hex
class HexBlock:
    """One terrain block (a .hex file normally holds exactly one; map70601 holds three)."""
    HEAD = 0x20
    ENV = 0xD0

    def __init__(self, buf: bytes, pos: int = 0):
        self.version, self.width, self.height = struct.unpack_from("<3I", buf, pos)
        if self.version not in (3, 4, 5, 6, 7):
            raise ValueError(f"unsupported .hex version {self.version}")
        if self.version != 6:
            raise NotImplementedError(f".hex version {self.version} (only v6 occurs in the game data)")
        # 5 obf motion/animation slots (-1 = none); the engine plays motion N on terrain object k
        self.motion_ids = list(struct.unpack_from("<5i", buf, pos + 0x0C))
        p = pos + self.HEAD
        self.env = bytearray(buf[p:p + self.ENV])      # light/camera block, see env_* helpers
        p += self.ENV
        W, H = self.width, self.height
        n = (W + 1) * (H + 1) * 4
        # corners[x, y, k]: 4 corner heights of panel (x, y); last row/col are padding.
        # Heights are negative-up (e.g. -12 is one step higher than -6); mesh Y ~= -height.
        self.corners = np.frombuffer(buf, "<f4", n, p).reshape(W + 1, H + 1, 4).copy()
        p += n * 4
        self.flag_a = np.frombuffer(buf, np.uint8, GRID_MAX * GRID_MAX, p).reshape(GRID_MAX, GRID_MAX).copy()
        p += GRID_MAX * GRID_MAX
        # no_panel[x, y] == 1 -> there is no panel (hole / outside); engine refuses to path there
        self.no_panel = np.frombuffer(buf, np.uint8, GRID_MAX * GRID_MAX, p).reshape(GRID_MAX, GRID_MAX).copy()
        p += GRID_MAX * GRID_MAX
        self.end = p

    def to_bytes(self) -> bytes:
        W, H = self.width, self.height
        if self.corners.shape != (W + 1, H + 1, 4):
            raise ValueError("corners shape does not match width/height")
        out = bytearray(struct.pack("<3I5i", self.version, W, H, *self.motion_ids))
        out += self.env
        out += self.corners.astype("<f4").tobytes()
        out += self.flag_a.astype(np.uint8).tobytes()
        out += self.no_panel.astype(np.uint8).tobytes()
        return bytes(out)

    # ---- convenience
    @property
    def env_camera_angles(self):
        """(yaw, pitch?) degrees stored at env+0xC0/0xC4 (315, 90 on most maps)."""
        return struct.unpack_from("<ii", self.env, 0xC0)

    def env_floats(self):
        return np.frombuffer(bytes(self.env), "<f4")

    def elevation(self) -> np.ndarray:
        """(W, H) float array: mean corner height with sign flipped (bigger = higher)."""
        return -self.corners[:self.width, :self.height].mean(axis=2)

    def has_panel(self, x, y) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height and not self.no_panel[x, y]

    def set_height(self, x, y, h):
        """set all 4 corners of panel (x, y) to height h (file convention: negative = up)."""
        self.corners[x, y, :] = h

    def resize(self, width, height, fill_height=None):
        """change grid size (keeps overlapping data)."""
        if not (0 < width <= GRID_MAX and 0 < height <= GRID_MAX):
            raise ValueError("size out of range")
        nc = np.zeros((width + 1, height + 1, 4), np.float32)
        if fill_height is not None:
            nc[:width, :height] = fill_height
        w, h = min(width, self.width) + 1, min(height, self.height) + 1
        nc[:w, :h] = self.corners[:w, :h]
        self.corners = nc
        self.width, self.height = width, height


class HexFile:
    def __init__(self, data: bytes):
        self.blocks = []
        pos = 0
        while pos < len(data):
            b = HexBlock(data, pos)
            self.blocks.append(b)
            pos = b.end
        if pos != len(data):
            raise ValueError("trailing data in .hex")

    def __getattr__(self, name):
        # delegate to first block (width, height, corners, no_panel, ...)
        if name == "blocks":
            raise AttributeError(name)
        return getattr(self.blocks[0], name)

    def to_bytes(self) -> bytes:
        return b"".join(b.to_bytes() for b in self.blocks)


# ============================================================================ .gop
class GopBlock:
    """u32 count; u8 x[16384]; u8 y[16384]; u8 colour[16384]; 12 zero bytes.
    Only the first `count` entries are live; the rest may contain stale editor data (kept)."""
    N = 0x4000
    SIZE = 4 + 3 * 0x4000 + 12

    def __init__(self, buf: bytes, pos: int = 0):
        self.count = struct.unpack_from("<I", buf, pos)[0]
        p = pos + 4
        self.xs = np.frombuffer(buf, np.uint8, self.N, p).copy()
        self.ys = np.frombuffer(buf, np.uint8, self.N, p + self.N).copy()
        self.colors = np.frombuffer(buf, np.uint8, self.N, p + 2 * self.N).copy()
        self.tail = bytes(buf[p + 3 * self.N:p + 3 * self.N + 12])

    def to_bytes(self) -> bytes:
        return (struct.pack("<I", self.count) + self.xs.tobytes() + self.ys.tobytes()
                + self.colors.tobytes() + self.tail)

    def panels(self):
        """list of (x, y, colour) for the live entries; colour codes: PANEL_COLORS."""
        n = self.count
        return list(zip(self.xs[:n].tolist(), self.ys[:n].tolist(), self.colors[:n].tolist()))

    def set_panels(self, panels, clear_stale=True):
        panels = [(int(x), int(y), int(c)) for x, y, c in panels if int(c)]
        if len(panels) > self.N:
            raise ValueError("too many geo panels")
        if clear_stale:
            self.xs[:] = 0; self.ys[:] = 0; self.colors[:] = 0
        for i, (x, y, c) in enumerate(panels):
            self.xs[i], self.ys[i], self.colors[i] = x, y, c
        self.count = len(panels)

    def color_grid(self, width=GRID_MAX, height=GRID_MAX) -> np.ndarray:
        g = np.zeros((width, height), np.uint8)
        for x, y, c in self.panels():
            if x < width and y < height:
                g[x, y] = c
        return g

    def set_color_grid(self, grid):
        """grid[x, y] = colour (0 = none) -> panel list (row-major order)."""
        xs, ys = np.nonzero(grid)
        self.set_panels([(x, y, grid[x, y]) for x, y in zip(xs.tolist(), ys.tolist())])


class GopFile:
    def __init__(self, data: bytes):
        if len(data) < GopBlock.SIZE:
            raise ValueError("unexpected .gop size")
        # normally exactly one block; map00121 (demo) is 98320 bytes of zeros -> keep the rest raw
        self.blocks = [GopBlock(data, 0)]
        self.extra = bytes(data[GopBlock.SIZE:])

    def __getattr__(self, name):
        if name == "blocks":
            raise AttributeError(name)
        return getattr(self.blocks[0], name)

    def to_bytes(self) -> bytes:
        return b"".join(b.to_bytes() for b in self.blocks) + self.extra


# ============================================================================ .chr
# (name, offset, struct char, count)   -- record size 0x250 (592); layout from the engine's
# unit-spawn struct initialiser at 0x1404da2bf and cross-checks against char/item/magic/Skill/GE.dat
UNIT_FIELDS = [
    ("slot", 0x00, "I", 1),          # unit number inside the map (1..n; may repeat across phases)
    ("char_id", 0x04, "I", 1),       # char.dat id (class / character / object / 4810-4811 = Geo Symbol)
    ("level", 0x08, "H", 1),
    ("facing", 0x0A, "H", 1),        # degrees: 0 = +y, 90 = +x, 180 = -y, 270 = -x
    ("x", 0x0C, "h", 1),             # panel coords; -1,-1 = not on map at start (reinforcement)
    ("y", 0x0E, "h", 1),
    ("spawn_group", 0x10, "B", 1),   # 255 = present at start; 1,2 = only seen on off-map units (wave?)
    ("unk12", 0x12, "H", 1),         # usually 1
    ("color_variant", 0x14, "H", 1),  # 0xFFFF default; 0..8 on colour-variant generic units (guess)
    ("unk16", 0x16, "B", 1),
    ("unk17", 0x17, "B", 1),         # 0/1
    ("equipment", 0x18, "I", 5),     # item.dat ids, slot 0 = weapon, 0 = empty
    ("unk2c", 0x2C, "H", 6),
    ("evilities", 0x38, "I", 20),    # Skill.dat ids (e.g. 5001 Theft Prevention)
    ("skills", 0x88, "I", 20),       # magic.dat ids (1001 Fire, 1201 Ice ...)
    ("skill_levels", 0xD8, "H", 20),
    ("skill_unk1", 0x100, "H", 20),  # per-skill value (0..9)
    ("skill_unk2", 0x128, "H", 20),  # per-skill value (0..9, 99)
    ("weapon_mastery", 0x150, "H", 10),  # index = weapon type (1 sword,3 bow,4 gun,5 axe,6 staff,7/8 monster), [9] = ?
    ("stat_mods", 0x164, "h", 8),    # signed %, e.g. -10 x8 on weak story enemies (HP,SP,ATK,DEF,INT,RES,HIT,SPD?)
    ("flags", 0x174, "B", 1),        # bitfield 1,2,4,8,16 (unknown)
    ("team", 0x175, "B", 1),         # 1 = enemy army, 2 = neutral (objects, GS, some units), 3..5 other armies
    ("unk176", 0x176, "H", 1),
    ("ai", 0x178, "i", 1),           # AI pattern id (101..116 seen), -1 = none (objects)
    ("ai_rules", 0x17C, "B", 200),   # byte 0 = `appears` (below); then the unit's AI orders: kind 255 = none,
                                     # 4 x u16 (often a map rectangle)
    ("unk244", 0x244, "B", 4),
    ("geo_color", 0x248, "I", 1),    # Geo Symbol colour (same codes as panels, 0 = clear/colourless)
    ("geo_effect", 0x24C, "I", 1),   # Geo Symbol effect = GE.dat id (1 Damage, 5 ATK+ ... 61 Game Over)
]
_FIELD_MAP = {f[0]: f for f in UNIT_FIELDS}
RECORD_SIZE = 0x250
OLD_RECORD_SIZE = 436                # 4 demo maps (map00121/00421/00721/00825): older layout

# When a unit is placed (byte 0x17C; the game's spawn 0x140525f20 asks 0x140525640 "is this the first visit": the
# stage's clear count in the save is 0).  Story stages keep two sets in one map this way: map00101 has 4 Warriors
# for the first visit and 4 Prinnies on the same panels for the visits after it is cleared; Final Trial 5 flame
# dragons, then Lucky Boards.  3347 of the game's units are 0, 423 are 1, 208 are 2.
APPEARS_ALWAYS, APPEARS_FIRST, APPEARS_REVISIT = 0, 1, 2
APPEARS = {APPEARS_ALWAYS: "Every visit", APPEARS_FIRST: "First visit (until the stage is cleared)",
           APPEARS_REVISIT: "Revisits (after the stage is cleared)"}
APPEARS_OFF = 0x17C


class Unit:
    """One .chr record. Attribute access reads/writes the underlying bytes."""
    __slots__ = ("raw",)

    def __init__(self, raw: bytes):
        object.__setattr__(self, "raw", bytearray(raw))

    @property
    def size(self):
        return len(self.raw)

    def _check(self, off, fmt, cnt):
        if len(self.raw) != RECORD_SIZE and off >= 0x18:
            raise AttributeError("field not available in old 436-byte records")

    def __getattr__(self, name):
        f = _FIELD_MAP.get(name)
        if f is None:
            raise AttributeError(name)
        _, off, fmt, cnt = f
        self._check(off, fmt, cnt)
        vals = struct.unpack_from(f"<{cnt}{fmt}", self.raw, off)
        return vals[0] if cnt == 1 else list(vals)

    def __setattr__(self, name, value):
        f = _FIELD_MAP.get(name)
        if f is None:
            if isinstance(getattr(type(self), name, None), property):     # (appears ...)
                object.__setattr__(self, name, value)
                return
            raise AttributeError(name)
        _, off, fmt, cnt = f
        self._check(off, fmt, cnt)
        if cnt == 1:
            struct.pack_into(f"<{fmt}", self.raw, off, value)
        else:
            value = list(value)[:cnt]
            value += [0] * (cnt - len(value))
            struct.pack_into(f"<{cnt}{fmt}", self.raw, off, *value)

    # ---- helpers
    @property
    def is_geo_symbol(self):
        return self.char_id in GEO_SYMBOL_IDS

    @property
    def is_object(self):
        return 5000 <= self.char_id < 5300 or self.char_id in GEO_SYMBOL_IDS

    @property
    def on_map(self):
        return self.x >= 0 and self.y >= 0

    @property
    def appears(self):
        """APPEARS_ALWAYS / APPEARS_FIRST / APPEARS_REVISIT (old 436-byte records: always)"""
        if len(self.raw) != RECORD_SIZE:
            return APPEARS_ALWAYS
        v = self.raw[APPEARS_OFF]
        return v if v in APPEARS else APPEARS_ALWAYS

    @appears.setter
    def appears(self, v):
        if len(self.raw) == RECORD_SIZE:
            self.raw[APPEARS_OFF] = int(v)

    def shown_in(self, visit):
        """is this unit placed on the given visit (APPEARS_FIRST / APPEARS_REVISIT)?"""
        return self.appears in (APPEARS_ALWAYS, visit)

    @property
    def repeat(self):
        """how many copies the game spawns (u16 0x12; the spawn loop runs this many times; 0 = none)"""
        return self.unk12

    @property
    def reinforcement(self):
        """a numbered group (u8 0x10, 1-127) is kept off the field until an event calls it in"""
        return 0 < self.spawn_group < 128

    def ai_rule_list(self):
        r = bytes(self.raw[0x17C:0x244])
        out = []
        for k in range(20):
            a, b, *v = struct.unpack_from("<BB4H", r, k * 10)
            out.append((a, b, tuple(v)))
        return out

    def to_dict(self) -> dict:
        names = [f[0] for f in UNIT_FIELDS] if self.size == RECORD_SIZE else \
            ["slot", "char_id", "level", "facing", "x", "y", "spawn_group", "unk12", "color_variant", "unk16", "unk17"]
        d = {n: getattr(self, n) for n in names}
        if self.size != RECORD_SIZE:
            d["_raw_tail"] = bytes(self.raw[0x18:]).hex()
        return d

    @classmethod
    def from_dict(cls, d: dict, template: "Unit" = None) -> "Unit":
        u = Unit(template.raw if template is not None else bytes(RECORD_SIZE))
        for k, v in d.items():
            if k in _FIELD_MAP:
                setattr(u, k, v)
        return u

    def copy(self) -> "Unit":
        return Unit(bytes(self.raw))

    def __repr__(self):
        return f"<Unit slot={self.slot} char={self.char_id} lv={self.level} at=({self.x},{self.y})>"


class ChrFile:
    """u16 version (=1), u16 count, 12 zero bytes, count x record."""

    def __init__(self, data: bytes):
        self.version, n = struct.unpack_from("<HH", data, 0)
        self.pad = bytes(data[4:16])
        body = len(data) - 16
        if n and body % n:
            raise ValueError("chr: record size not integral")
        self.record_size = body // n if n else RECORD_SIZE
        rs = self.record_size
        self.units = [Unit(data[16 + i * rs:16 + (i + 1) * rs]) for i in range(n)]

    def to_bytes(self) -> bytes:
        for u in self.units:
            if u.size != self.record_size:
                raise ValueError("mixed record sizes")
        return (struct.pack("<HH", self.version, len(self.units)) + self.pad
                + b"".join(bytes(u.raw) for u in self.units))

    def add_unit(self, char_id, x, y, level=1, template: Unit = None, appears=APPEARS_ALWAYS, **fields) -> Unit:
        """append a unit (copies `template` or the first non-object unit so all defaults are sane).  `appears`:
        which visits place it (a copied template keeps its AI orders but not its visit: the editor's units used to
        inherit "first visit only" from the stage's first enemy and never showed up on a cleared stage)."""
        if template is None:
            template = next((u for u in self.units if not u.is_object), None)
        u = template.copy() if template is not None else Unit.from_dict(DEFAULT_ENEMY)
        u.slot = max([v.slot for v in self.units] + [0]) + 1
        u.char_id, u.x, u.y, u.level = char_id, x, y, level
        if u.size == RECORD_SIZE:
            u.spawn_group = 255                  # on the field from the start (not a reinforcement group)
            if u.unk12 < 1:
                u.unk12 = 1                      # (the game spawns a unit this many times)
        u.appears = appears
        for k, v in fields.items():
            setattr(u, k, v)
        self.units.append(u)
        return u

    def visit_sets(self):
        """does this map place different units on the first visit and on revisits?"""
        return any(u.appears != APPEARS_ALWAYS for u in self.units)

    def placed(self, visit):
        """the units the game places on that visit (APPEARS_FIRST / APPEARS_REVISIT)"""
        return [u for u in self.units if u.shown_in(visit)]

    def geo_symbols(self):
        return [u for u in self.units if u.is_geo_symbol]

    def enemies(self):
        return [u for u in self.units if not u.is_object]


# sensible defaults for a brand-new record (taken from a typical story enemy)
DEFAULT_ENEMY = {
    "slot": 1, "char_id": 1010, "level": 1, "facing": 180, "x": 0, "y": 0, "spawn_group": 255,
    "unk12": 1, "color_variant": 0xFFFF, "equipment": [202, 0, 1202, 0, 0], "stat_mods": [-10] * 8,
    "weapon_mastery": [0, 1, 0, 0, 0, 0, 0, 0, 0, 1], "team": 1, "ai": 102,
    # byte 0 = appears (0: every visit); then AI orders as in the game's story enemies (kind 1 first)
    "ai_rules": [0, 1] + [0] * 8 + [b for k in range(1, 20)
                                    for b in (([255, 0] if (k - 1) % 4 == 0 else [0, 255]) + [0] * 8)],
}


# ============================================================================ map package
MEMBER_EXTS = ("hex", "chr", "obf", "gop")


class MapPackage:
    """All members of one mapNNNNN.lzs.  Parsed views are created lazily and written back by
    `commit()` / `to_lzs()`."""

    def __init__(self, members, name=None, tag=b"pac"):
        self.members = [[n, bytes(d)] for n, d in members]
        self.name = name or (self.members[0][0].rsplit(".", 1)[0] if self.members else "map00000")
        self.tag = tag
        self._parsed = {}

    # ---- constructors
    @classmethod
    def from_lzs(cls, data: bytes, name=None):
        raw = lzs.decompress(data)
        return cls(pac.read_pac(raw), name, tag=data[:4])

    @classmethod
    def from_archive(cls, map_id, langs=("EN", "JP"), data_dir=DATA):
        """read mapNNNNN.lzs from the game archives (read-only). EN/FR hold replacements of JP."""
        from .nispack import NisPack
        name = f"map{int(map_id):05d}"
        for lang in langs:
            path = os.path.join(data_dir, "Map", f"Map_{lang}.dat")
            if not os.path.exists(path):
                continue
            with NisPack(path) as p:
                if name + ".lzs" in p.by_name:
                    return cls.from_lzs(p.read(name + ".lzs"), name)
        raise KeyError(name)

    @classmethod
    def from_dir(cls, folder):
        """folder with mapNNNNN.hex/.chr/.obf/.gop (as produced by extract_all.py)."""
        name = os.path.basename(os.path.normpath(folder))
        members = []
        for ext in MEMBER_EXTS:
            p = os.path.join(folder, f"{name}.{ext}")
            if os.path.exists(p):
                members.append((f"{name}.{ext}", open(p, "rb").read()))
        extra = sorted(f for f in os.listdir(folder) if f not in [m[0] for m in members])
        members += [(f, open(os.path.join(folder, f), "rb").read()) for f in extra]
        return cls(members, name)

    # ---- member access
    def member_name(self, ext):
        for n, _ in self.members:
            if n.lower().endswith("." + ext):
                return n
        return None

    def get(self, ext) -> bytes:
        self._flush(ext)
        for n, d in self.members:
            if n.lower().endswith("." + ext):
                return d
        raise KeyError(ext)

    def set(self, ext, data: bytes):
        self._parsed.pop(ext, None)
        for m in self.members:
            if m[0].lower().endswith("." + ext):
                m[1] = bytes(data)
                return
        self.members.append([f"{self.name}.{ext}", bytes(data)])

    def _view(self, ext, cls):
        if ext not in self._parsed:
            self._parsed[ext] = cls(self.get(ext))
        return self._parsed[ext]

    @property
    def hex(self) -> HexFile:
        return self._view("hex", HexFile)

    @property
    def chr(self) -> ChrFile:
        return self._view("chr", ChrFile)

    @property
    def gop(self) -> GopFile:
        return self._view("gop", GopFile)

    @property
    def obf(self):
        from .obf import ObfFile
        return self._view("obf", ObfFile)

    def _flush(self, ext=None):
        for e, view in list(self._parsed.items()):
            if ext is None or e == ext:
                data = view.to_bytes()
                for m in self.members:
                    if m[0].lower().endswith("." + e):
                        m[1] = data

    def commit(self):
        self._flush()

    # ---- output
    def to_pac(self) -> bytes:
        self.commit()
        return pac.write_pac([(n, d) for n, d in self.members])

    def to_lzs(self, **kw) -> bytes:
        from .lzs_compress import compress
        return compress(self.to_pac(), self.tag, **kw)

    def save_dir(self, folder):
        self.commit()
        os.makedirs(folder, exist_ok=True)
        for n, d in self.members:
            with open(os.path.join(folder, n), "wb") as f:
                f.write(d)

    def renamed(self, new_map_id) -> "MapPackage":
        """copy of this map with members renamed to map<new_id>.* (for cloning a stage)."""
        self.commit()
        new = f"map{int(new_map_id):05d}"
        mem = [(new + n[len(self.name):] if n.startswith(self.name) else n, d) for n, d in self.members]
        return MapPackage(mem, new, self.tag)


# ============================================================================ dungeon.dat (stage list)
class DungeonRecord:
    """336-byte record of dungeon.dat. Known: map id, base panel, names (5 langs x 0x34 bytes)."""
    SIZE = 336
    NAME_OFF = 0x49
    NAME_LEN = 0x34
    LANGS = ("JP", "EN", "FR", "CHN", "KOR")

    def __init__(self, raw: bytes):
        self.raw = bytearray(raw)

    def _u(self, fmt, off):
        return struct.unpack_from(fmt, self.raw, off)[0]

    index = property(lambda s: s._u("<I", 0x00), lambda s, v: struct.pack_into("<I", s.raw, 0x00, v))
    map_id = property(lambda s: s._u("<I", 0x04), lambda s, v: struct.pack_into("<I", s.raw, 0x04, v))
    episode = property(lambda s: s._u("<H", 0x14), lambda s, v: struct.pack_into("<H", s.raw, 0x14, v))
    title_id = property(lambda s: s._u("<H", 0x16), lambda s, v: struct.pack_into("<H", s.raw, 0x16, v))
    base_x = property(lambda s: s.raw[0x36], lambda s, v: s.raw.__setitem__(0x36, v))
    base_y = property(lambda s: s.raw[0x37], lambda s, v: s.raw.__setitem__(0x37, v))

    def name(self, lang="EN"):
        o = self.NAME_OFF + self.LANGS.index(lang) * self.NAME_LEN
        return bytes(self.raw[o:o + self.NAME_LEN]).split(b"\0")[0].decode("utf-8", "replace")

    def set_name(self, text, lang="EN"):
        o = self.NAME_OFF + self.LANGS.index(lang) * self.NAME_LEN
        b = text.encode("utf-8")[:self.NAME_LEN - 1]
        self.raw[o:o + self.NAME_LEN] = b.ljust(self.NAME_LEN, b"\0")

    def __repr__(self):
        return f"<Stage #{self.index} map{self.map_id:05d} base=({self.base_x},{self.base_y}) {self.name()!r}>"


class DungeonTable:
    def __init__(self, data: bytes):
        n = struct.unpack_from("<I", data)[0]
        if len(data) != 4 + n * DungeonRecord.SIZE:
            raise ValueError("unexpected dungeon.dat size")
        self.records = [DungeonRecord(data[4 + i * 336:4 + (i + 1) * 336]) for i in range(n)]

    def to_bytes(self) -> bytes:
        return struct.pack("<I", len(self.records)) + b"".join(bytes(r.raw) for r in self.records)

    def by_map(self, map_id):
        return [r for r in self.records if r.map_id == int(map_id)]

    def add_stage(self, clone_from: DungeonRecord, map_id, name=None) -> DungeonRecord:
        r = DungeonRecord(bytes(clone_from.raw))
        r.index = max(x.index for x in self.records) + 1
        r.map_id = int(map_id)
        if name:
            for lang in DungeonRecord.LANGS:
                r.set_name(name, lang)
        self.records.append(r)
        return r


# ============================================================================ preview render
def render_topdown(hexf, gopf=None, chrf=None, base=None, cell=24, names=None):
    """PIL image, x -> right, y -> down. Height = shading, geo panel colour = inner square,
    units: red circle = enemy team, grey square = object, diamond = Geo Symbol (fill = colour),
    blue frame = base panel. `names` optional {char_id: str} for a legend-free label (first 3 chars)."""
    from PIL import Image, ImageDraw
    hb = hexf.blocks[0] if hasattr(hexf, "blocks") else hexf
    W, H = hb.width, hb.height
    elev = hb.elevation()
    live = hb.no_panel[:W, :H] == 0
    lo, hi = (elev[live].min(), elev[live].max()) if live.any() else (0, 1)
    rng = max(hi - lo, 1e-6)
    img = Image.new("RGB", (W * cell + 1, H * cell + 1), (0, 0, 0))
    d = ImageDraw.Draw(img)
    colors = gopf.blocks[0].color_grid(W, H) if gopf is not None else np.zeros((W, H), np.uint8)
    for x in range(W):
        for y in range(H):
            x0, y0 = x * cell, y * cell
            if not live[x, y]:
                d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=(20, 20, 28), outline=(35, 35, 45))
                continue
            t = (elev[x, y] - lo) / rng
            g = int(70 + 170 * t)
            d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=(g, g, int(g * 0.9)), outline=(40, 40, 40))
            c = int(colors[x, y])
            if c:
                m = cell // 5
                d.rectangle([x0 + m, y0 + m, x0 + cell - m, y0 + cell - m], fill=PANEL_RGB.get(c, (255, 0, 255)))
    if base is not None:
        bx, by = base
        d.rectangle([bx * cell + 1, by * cell + 1, bx * cell + cell - 1, by * cell + cell - 1],
                    outline=(0, 120, 255), width=3)
    if chrf is not None:
        for u in chrf.units:
            if u.x < 0 or u.y < 0 or u.x >= W or u.y >= H:
                continue
            cx, cy = u.x * cell + cell / 2, u.y * cell + cell / 2
            r = cell * 0.32
            if u.size == RECORD_SIZE and u.is_geo_symbol:
                col = PANEL_RGB.get(u.geo_color, (255, 255, 255))
                d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=col, outline=(0, 0, 0))
            elif 5000 <= u.char_id < 5300:
                d.rectangle([cx - r, cy - r, cx + r, cy + r], fill=(150, 110, 60), outline=(0, 0, 0))
            else:
                team = u.team if u.size == RECORD_SIZE else 1
                col = (220, 30, 30) if team == 1 else (230, 130, 20)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=(0, 0, 0))
                # facing tick (0 deg = +y, 90 = +x)
                import math
                a = math.radians(u.facing)
                d.line([cx, cy, cx + math.sin(a) * r * 1.4, cy + math.cos(a) * r * 1.4], fill=(255, 255, 255), width=2)
            if names and cell >= 20:
                d.text((u.x * cell + 2, u.y * cell + 1), str(names.get(u.char_id, u.char_id))[:3], fill=(255, 255, 255))
    return img
