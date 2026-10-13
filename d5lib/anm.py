"""Disgaea 5 Complete (PC) sprite animation packs: ``anmNNNNN.lzs`` (LZS 'dat').

See docs/ANM.md for the full format description.  Quick overview::

    0x00  file header (0x20 bytes)
    0x20  N animation blocks (each: 0x44-byte header + 10 record tables)
    ....  ntex + npal 16-byte TXF-style image headers (textures first, then palettes)
    ....  image data (textures in order, then palettes in order)

Usage::

    from d5lib import anm
    a = anm.load("anm00010.dat")          # decompressed bytes / path / .lzs path
    img = anm.texture_to_image(a, 0, palette_index=2)
    frame = anm.render_frame(a, ('id', 6001), 0, palette_index=0)
    anm.find_character_anm('Warrior')     # -> which anm file / palette a class uses
    raw = a.to_bytes()                    # byte-identical when unmodified
    lzs_bytes = anm.lzs_compress(raw)     # ready to put back into ANM_HI_*.dat

All offsets / sizes / counts are recomputed by to_bytes(), so textures and
palettes may be resized, added or removed freely (see ANM.md "Growing data").
"""
from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass, field, astuple
from typing import List, Optional, Tuple

import numpy as np

# --------------------------------------------------------------------------------------
# record definitions
# --------------------------------------------------------------------------------------

BLOCK_HEADER_SIZE = 0x44
FILE_HEADER_SIZE = 0x20
IMG_HEADER_SIZE = 0x10
IMG_ALIGN = 0x80         # image data offsets are 128-byte aligned


def _align(v, a):
    return (v + a - 1) // a * a


FMT_INDEXED8 = 0x09      # TXF fmt byte 0: 8-bit indices into a 256-colour palette
FMT_ARGB32 = 0x00        # TXF fmt byte 0: 32-bit, bytes A,R,G,B


@dataclass
class Animation:          # table 0, 4 bytes
    id: int               # u16 animation number; last digit 1 = front view, 7 = back view
                          #     (other two directions = mirrored), e.g. 1001/1007
    root: int             # u16 index of the root node (table 1)
    FMT = "<HH"


@dataclass
class Node:               # table 1, 20 bytes: a layer/track in the node tree
    id: int               # u16 node name/id: 0 = anonymous layer; 1 = body, 10 = weapon slot,
                          #     11..17 / 111..116 = attachment points (hands, effects...)
    flags: int            # u16 0x100 set iff id != 0 (named node); 0x1000 = unknown (mostly on
                          #     cell-less group/bone nodes)
    unk2: int             # u16 (almost always 0)
    unk3: int             # u16 (always 0)
    mesh: int             # u16 1 = vertex-quad mode: transform.pivot indexes a group of 10
                          #     points (TL,TR,BR,BL,centre + 5 unknown) instead of one pivot
    unk5: int             # u16 (always 0)
    first_key: int        # i16 index of first key in table 2 (-1 = none)
    num_keys: int         # u16
    child: int            # i16 first child node (-1 = none)
    next: int             # i16 next sibling node (-1 = none)
    FMT = "<HHHHHHhHhh"


@dataclass
class Key:                # table 2, 12 bytes: keyframe of a node
    time: int             # u16 frame number (60 fps)
    flags: int            # u16 low byte: 1 = interpolate towards next key; on root (control)
                          #     nodes: 1=loop start, 2=loop back, 3=?, 4=event, 5=end/hold
                          # high byte: 0x1 / 0x2 on attachment nodes (show / hide the attached
                          #     object?), 0x6 mostly on 32-bit (cut-in) textures; see ANM.md
    cell: int             # u16 index into table 5 (0 = nothing drawn)
    xform: int            # u16 index into table 6
    color: int            # u16 index into table 8
    param: int            # u16 index into table 9: list of (anim_id, 0) pairs terminated by -1.
                          #     Named/attachment nodes: animation the attached object plays;
                          #     control nodes: linked animation id
    FMT = "<HHHHHH"


@dataclass
class PaletteInfo:        # table 3, 8 bytes (legacy console info; PC uses image headers)
    offset: int           # u32 "virtual" offset: block_size + sum(previous palettes)
    num_colors: int       # u16 original colour count (256 or 16)
    unk: int              # u16 0
    FMT = "<IHH"


@dataclass
class TextureInfo:        # table 4, 12 bytes (legacy console info)
    offset: int           # u32 virtual offset: block_size + all palettes + previous textures
    width: int            # u16
    height: int           # u16
    bpp: int              # u8 original bits per pixel (4, 8, 32)
    unk1: int             # u8 0x10
    unk2: int             # u8 0x10
    unk3: int             # u8 0
    FMT = "<IHHBBBB"


@dataclass
class Cell:               # table 5, 18 bytes: rectangle on a texture ("sprite part")
    tex: int              # u16 texture index (block-local)
    pal: int              # u16 palette index (block-local, added to the colour variant)
    unk2: int             # u16 (0, 512, 7, 15, 768 ... purpose unknown)
    flags: int            # u16 (0/1/257)
    x: int                # u16 left
    y: int                # u16 top
    w: int                # u16 width
    h: int                # u16 height
    unk8: int             # u16 (0/1 ...)
    FMT = "<HHHHHHHHH"


@dataclass
class Transform:          # table 6, 16 bytes
    x: int                # i16 position of the pivot in parent space
    y: int                # i16
    pivot: int            # u16 index into table 7 (pivot point in cell space)
    unk: int              # u16 0
    sx: int               # i16 scale X in percent (negative = mirrored)
    sy: int               # i16 scale Y in percent
    rot: int              # i32 rotation, degrees (clockwise on screen)
    FMT = "<hhHHhhi"


@dataclass
class Pivot:              # table 7, 4 bytes
    x: int
    y: int
    FMT = "<hh"


@dataclass
class Color:              # table 8, 20 bytes: 5 RGBA vertex colours TL,TR,BR,BL,centre
    rgba: Tuple[int, ...]  # 20 bytes R,G,B,A x5 ; RGB 0x80 = 1.0 (0xFF ~ 2x brighten), A 0xFF = opaque
    FMT = "<20B"


# table 9 = plain i32 values ("params")

TABLES = [Animation, Node, Key, PaletteInfo, TextureInfo, Cell, Transform, Pivot, Color, None]
TABLE_SIZES = [4, 20, 12, 8, 12, 18, 16, 4, 20, 4]


def _unpack_table(cls, data, off, count, size):
    out = []
    if cls is None:
        return list(struct.unpack_from("<%di" % count, data, off))
    st = struct.Struct(cls.FMT)
    for i in range(count):
        v = st.unpack_from(data, off + i * size)
        if cls is Color:
            out.append(Color(tuple(v)))
        else:
            out.append(cls(*v))
    return out


_FIELD_GETTERS = {}


def _pack_table(cls, rows):
    if cls is None:
        return struct.pack("<%di" % len(rows), *rows)
    st = struct.Struct(cls.FMT)
    if cls is Color:
        return b"".join(st.pack(*r.rgba) for r in rows)
    get = _FIELD_GETTERS.get(cls)
    if get is None:                 # plain attribute access (dataclasses.astuple deep-copies every row: slow)
        import dataclasses
        import operator
        get = _FIELD_GETTERS[cls] = operator.attrgetter(*[f.name for f in dataclasses.fields(cls)])
    return b"".join(st.pack(*get(r)) for r in rows)


# --------------------------------------------------------------------------------------
# block
# --------------------------------------------------------------------------------------

@dataclass
class AnmBlock:
    id: int                                   # u16 = anm file number
    animations: List[Animation] = field(default_factory=list)
    nodes: List[Node] = field(default_factory=list)
    keys: List[Key] = field(default_factory=list)
    palette_infos: List[PaletteInfo] = field(default_factory=list)
    texture_infos: List[TextureInfo] = field(default_factory=list)
    cells: List[Cell] = field(default_factory=list)
    transforms: List[Transform] = field(default_factory=list)
    pivots: List[Pivot] = field(default_factory=list)
    colors: List[Color] = field(default_factory=list)
    params: List[int] = field(default_factory=list)
    count9: int = 0                           # 10th count slot in header (always 0)
    # indices of this block's first texture / palette in the file-global lists
    tex_base: int = 0
    pal_base: int = 0
    pad: bytes = b""                          # original alignment padding (may be non-zero junk)

    def tables(self):
        return [self.animations, self.nodes, self.keys, self.palette_infos, self.texture_infos,
                self.cells, self.transforms, self.pivots, self.colors, self.params]

    @classmethod
    def parse(cls, data: bytes, pos: int) -> Tuple["AnmBlock", int]:
        size, bid, nanim = struct.unpack_from("<IHH", data, pos)
        counts = struct.unpack_from("<10H", data, pos + 8)
        offs = struct.unpack_from("<10I", data, pos + 0x1C)
        cnt = [nanim] + list(counts[:9])
        b = cls(bid, count9=counts[9])
        for i, (tcls, tsz) in enumerate(zip(TABLES, TABLE_SIZES)):
            b.tables()[i].extend(_unpack_table(tcls, data, pos + offs[i], cnt[i], tsz))
        lay, lsize = b.layout()
        if list(offs) != lay or lsize != size:
            raise ValueError("block at %#x: unexpected table layout" % pos)
        end = offs[9] + cnt[9] * 4
        b.pad = bytes(data[pos + end:pos + size])
        return b, size

    def layout(self):
        """Return (offsets, size) of the 10 tables for serialization."""
        offs = []
        o = BLOCK_HEADER_SIZE
        for t, sz in zip(self.tables(), TABLE_SIZES):
            offs.append(o)
            o += len(t) * sz
        size = (o + 15) & ~15
        return offs, size

    def fix_virtual_offsets(self):
        """Recompute the legacy virtual offsets of table 3/4 (block_size + pals + texs)."""
        _, size = self.layout()
        o = size
        for p in self.palette_infos:
            p.offset = o
            o += p.num_colors * 4
        for t in self.texture_infos:
            t.offset = o
            o += t.width * t.height * t.bpp // 8

    def to_bytes(self) -> bytes:
        offs, size = self.layout()
        t = self.tables()
        cnt = [len(x) for x in t]
        out = bytearray(struct.pack("<IHH", size, self.id, cnt[0]))
        out += struct.pack("<10H", *(cnt[1:] + [self.count9]))
        out += struct.pack("<10I", *offs)
        for tbl, tcls in zip(t, TABLES):
            out += _pack_table(tcls, tbl)
        n = size - len(out)
        out += self.pad if len(self.pad) == n else b"\0" * n
        return bytes(out)

    # convenience -------------------------------------------------------------------
    def node_keys(self, n: Node) -> List[Key]:
        if n.first_key < 0 or n.num_keys == 0:
            return []
        return self.keys[n.first_key:n.first_key + n.num_keys]

    def walk(self, root: int, depth=0):
        """Yield (node_index, depth, parent_index) in file (tree pre-)order."""
        stack = [(root, depth, -1)]
        while stack:
            i, d, p = stack.pop()
            if i < 0 or i >= len(self.nodes):
                continue
            n = self.nodes[i]
            yield i, d, p
            # push next first so that child subtree is visited before siblings
            stack.append((n.next, d, p))
            stack.append((n.child, d + 1, i))


# --------------------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------------------

@dataclass
class Image8:
    """One TXF-style image (texture or palette) of the PC data."""
    fmt: bytes            # 4 bytes: 09 01 01 01 (8-bit indexed) or 00 01 01 01 (ARGB32)
    width: int
    height: int
    unk: int              # u32, always 1
    data: bytes           # raw pixels (w*h or w*h*4 bytes)
    pad: bytes = b""      # alignment padding stored after this image (normally empty)

    @property
    def indexed(self):
        return self.fmt[0] == FMT_INDEXED8

    @property
    def bpp(self):
        return 8 if self.indexed else 32

    def expected_size(self):
        return self.width * self.height * self.bpp // 8


# --------------------------------------------------------------------------------------
# file
# --------------------------------------------------------------------------------------

@dataclass
class AnmFile:
    blocks: List[AnmBlock]
    textures: List[Image8]
    palettes: List[Image8]
    hdr_unk: bytes = b"\0" * 12        # bytes 0x14..0x20 of the file header (always 0)
    trailing: bytes = b""              # bytes after the image data (never seen)

    # ---------------------------------------------------------------- parse / write
    @classmethod
    def parse(cls, data: bytes) -> "AnmFile":
        h0, dsize, ntex, npal, nblk = struct.unpack_from("<5I", data, 0)
        pos = FILE_HEADER_SIZE
        blocks = []
        tb = pb = 0
        for _ in range(nblk):
            b, size = AnmBlock.parse(data, pos)
            b.tex_base, b.pal_base = tb, pb
            tb += len(b.texture_infos)
            pb += len(b.palette_infos)
            blocks.append(b)
            pos += size
        base = h0 + 0x10
        imgs = []
        for i in range(ntex + npal):
            r = pos + i * IMG_HEADER_SIZE
            fmt = bytes(data[r:r + 4])
            w, hgt, unk, off = struct.unpack_from("<HHII", data, r + 4)
            n = w * hgt * (1 if fmt[0] == FMT_INDEXED8 else 4)
            imgs.append((off, Image8(fmt, w, hgt, unk, bytes(data[base + off:base + off + n]))))
        # data is stored in header order, each image aligned to IMG_ALIGN bytes
        o = 0
        prev = None
        for off, im in imgs:
            if off != _align(o, IMG_ALIGN):
                raise ValueError("unexpected image data offset %#x (expected %#x)" % (off, _align(o, IMG_ALIGN)))
            if prev is not None:
                prev.pad = bytes(data[base + o:base + off])
            o = off + len(im.data)
            prev = im
        f = cls(blocks, [im for _, im in imgs[:ntex]], [im for _, im in imgs[ntex:]],
                bytes(data[0x14:0x20]), bytes(data[base + o:]))
        if pos + (ntex + npal) * IMG_HEADER_SIZE != base or o != dsize:
            raise ValueError("unexpected header layout")
        return f

    def to_bytes(self, fix_virtual_offsets: bool = True) -> bytes:
        if fix_virtual_offsets:
            for b in self.blocks:
                b.fix_virtual_offsets()
        body = b"".join(b.to_bytes() for b in self.blocks)
        imgs = self.textures + self.palettes
        hdrs = bytearray()
        o = 0
        chunks = []
        for i, im in enumerate(imgs):
            if len(im.data) != im.expected_size():
                raise ValueError("image data size mismatch")
            if o != _align(o, IMG_ALIGN):
                n = _align(o, IMG_ALIGN) - o
                p = imgs[i - 1].pad
                p = p if len(p) == n else bytes(n)
                chunks.append(p)
                o += n
            hdrs += im.fmt + struct.pack("<HHII", im.width, im.height, im.unk, o)
            chunks.append(im.data)
            o += len(im.data)
        base = FILE_HEADER_SIZE + len(body) + len(hdrs)
        head = struct.pack("<5I", base - 0x10, o, len(self.textures), len(self.palettes),
                           len(self.blocks)) + self.hdr_unk
        return b"".join([head, body, bytes(hdrs)] + chunks + [self.trailing])

    # ---------------------------------------------------------------- helpers
    @property
    def block(self) -> AnmBlock:
        return self.blocks[0]

    def all_animations(self):
        """[(block_index, anim_index, Animation)]"""
        return [(bi, ai, a) for bi, b in enumerate(self.blocks) for ai, a in enumerate(b.animations)]


# --------------------------------------------------------------------------------------
# loading / LZS
# --------------------------------------------------------------------------------------

def load(src) -> AnmFile:
    """Load from decompressed bytes, compressed LZS bytes, or a file path."""
    if isinstance(src, (str, os.PathLike)):
        with open(src, "rb") as fh:
            src = fh.read()
    data = bytes(src)
    if data[:4] in (b"dat\0", b"pac\0") and struct.unpack_from("<I", data, 4)[0] != len(data):
        from . import lzs
        data = lzs.decompress(data)
    return AnmFile.parse(data)


def parse(data: bytes) -> AnmFile:
    return AnmFile.parse(data)


def load_from_archive(name: str, lang: str = "EN", data_dir: Optional[str] = None) -> AnmFile:
    """Read anmNNNNN from Data/Anime/ANM_HI_<lang>.dat, falling back to the JP base set.
    name: 'anm00010', 'anm00010.lzs' or an int."""
    from . import nispack, lzs, util
    if isinstance(name, int):
        name = "anm%05d" % name
    if not name.endswith(".lzs"):
        name += ".lzs"
    data_dir = data_dir or os.path.join(util.DATA, "Anime")
    for lg in ([lang] if lang != "JP" else []) + ["JP"]:
        p = os.path.join(data_dir, "ANM_HI_%s.dat" % lg)
        if not os.path.exists(p):
            continue
        with nispack.NisPack(p) as pk:
            if name.lower() in pk.by_name:
                return AnmFile.parse(lzs.decompress(pk.read(name)))
    raise KeyError(name)


def lzs_compress(data: bytes, ext: bytes = b"dat\0", level: int = 1) -> bytes:
    """NIS LZS compressor (inverse of d5lib.lzs.decompress).

    level 0: literal-only (fast, output ~= input size);  level 1: greedy LZ
    (distance <= 254, length 4..255).  Pure python: ~1-3 MB/s at level 1.

    Level >= 1 now delegates to d5lib.lzs_compress, which (like the game's own encoder) never
    emits overlapping matches or length 255 — the game's decoder cannot handle those.
    """
    if level >= 1:
        from .lzs_compress import compress
        return compress(data, ext)
    raw = bytes(data)
    hist = np.bincount(np.frombuffer(raw, np.uint8), minlength=256) if raw else np.zeros(256)
    marker = int(np.argmin(hist))
    out = bytearray()
    n = len(raw)
    if level <= 0:
        mb = bytes([marker])
        out += raw.replace(mb, mb + mb)
    else:
        i = 0
        heads = {}
        mv = memoryview(raw)
        while i < n:
            best_len = 0
            best_d = 0
            if i + 4 <= n:
                k = raw[i:i + 3]
                cand = heads.get(k)
                if cand:
                    lim = min(255, n - i)
                    for j in reversed(cand):
                        d = i - j
                        if d > 254:
                            break
                        L = 3
                        while L < lim and raw[j + L] == raw[i + L]:
                            L += 1
                        if L > best_len:
                            best_len, best_d = L, d
                            if L == lim:
                                break
            if best_len >= 4:
                dd = best_d if best_d < marker else best_d + 1
                out += bytes((marker, dd, best_len))
                end = i + best_len
            else:
                b = raw[i]
                out += bytes((b, b)) if b == marker else bytes((b,))
                end = i + 1
            while i < end:
                if i + 3 <= n:
                    k = raw[i:i + 3]
                    lst = heads.get(k)
                    if lst is None:
                        heads[k] = [i]
                    else:
                        lst.append(i)
                        if len(lst) > 16:
                            del lst[:8]
                i += 1
    return struct.pack("<4sIII", ext, n, len(out) + 16, marker) + bytes(out)


# --------------------------------------------------------------------------------------
# palettes / textures
# --------------------------------------------------------------------------------------

def _argb_to_rgba(a: np.ndarray) -> np.ndarray:
    return a[..., [1, 2, 3, 0]]


def _rgba_to_argb(a: np.ndarray) -> np.ndarray:
    return a[..., [3, 0, 1, 2]]


def get_palette(anm: AnmFile, palette_index: int) -> np.ndarray:
    """(256,4) uint8 RGBA array of a file-global palette index."""
    p = anm.palettes[palette_index]
    return _argb_to_rgba(np.frombuffer(p.data, np.uint8).reshape(-1, 4)).copy()


def set_palette(anm: AnmFile, palette_index: int, rgba) -> None:
    """Replace palette colours. rgba: (N<=256,4) RGBA uint8 array/list. palette_index may be
    len(anm.palettes) to append a new palette (see add_palette for block bookkeeping)."""
    arr = np.asarray(rgba, dtype=np.uint8).reshape(-1, 4)
    full = np.zeros((256, 4), np.uint8)
    if palette_index < len(anm.palettes):
        full[:] = get_palette(anm, palette_index)
    full[:len(arr)] = arr[:256]
    data = _rgba_to_argb(full).tobytes()
    if palette_index == len(anm.palettes):
        anm.palettes.append(Image8(bytes([0, 1, 1, 1]), 256, 1, 1, data))
    else:
        anm.palettes[palette_index].data = data


def add_palette(anm: AnmFile, rgba=None, copy_from: int = 0, block_index: int = 0) -> int:
    """Append a palette (colour variant) to a block; returns its file-global index.
    The palette is inserted after the block's existing palettes; later blocks are shifted."""
    b = anm.blocks[block_index]
    gi = b.pal_base + len(b.palette_infos)
    src = anm.palettes[copy_from].data if rgba is None else _rgba_to_argb(
        np.asarray(rgba, np.uint8).reshape(256, 4)).tobytes()
    anm.palettes.insert(gi, Image8(bytes([0, 1, 1, 1]), 256, 1, 1, bytes(src)))
    b.palette_infos.append(PaletteInfo(0, 256, 0))
    for ob in anm.blocks[block_index + 1:]:
        ob.pal_base += 1
    return gi


def add_texture(anm: AnmFile, width: int, height: int, indexed: bool = True, block_index: int = 0) -> int:
    """Append an empty texture to a block, returns its block-local index (for Cell.tex)."""
    b = anm.blocks[block_index]
    gi = b.tex_base + len(b.texture_infos)
    fmt = bytes([FMT_INDEXED8 if indexed else FMT_ARGB32, 1, 1, 1])
    anm.textures.insert(gi, Image8(fmt, width, height, 1, bytes(width * height * (1 if indexed else 4))))
    b.texture_infos.append(TextureInfo(0, width, height, 8 if indexed else 32, 0x10, 0x10, 0))
    for ob in anm.blocks[block_index + 1:]:
        ob.tex_base += 1
    return len(b.texture_infos) - 1


def num_color_variants(anm: AnmFile, block_index: int = 0) -> int:
    return len(anm.blocks[block_index].palette_infos)


def texture_to_image(anm: AnmFile, tex_index: int, palette_index: int = 0):
    """File-global texture -> PIL RGBA image. palette_index is file-global (for single-block
    files it equals the colour variant)."""
    from PIL import Image
    t = anm.textures[tex_index]
    if t.indexed:
        idx = np.frombuffer(t.data, np.uint8).reshape(t.height, t.width)
        pal = get_palette(anm, palette_index) if anm.palettes else np.stack(
            [np.arange(256)] * 3 + [np.full(256, 255)], 1).astype(np.uint8)
        arr = pal[idx]
    else:
        arr = _argb_to_rgba(np.frombuffer(t.data, np.uint8).reshape(t.height, t.width, 4))
    return Image.fromarray(np.ascontiguousarray(arr), "RGBA")


def texture_indices(anm: AnmFile, tex_index: int) -> np.ndarray:
    t = anm.textures[tex_index]
    if not t.indexed:
        raise ValueError("texture is not indexed")
    return np.frombuffer(t.data, np.uint8).reshape(t.height, t.width).copy()


def quantize_to_palette(rgba: np.ndarray, pal: np.ndarray, alpha_weight: float = 2.0) -> np.ndarray:
    """Nearest-colour mapping (RGBA, weighted alpha). Fully transparent pixels map to the
    first fully-transparent palette entry."""
    flat = rgba.reshape(-1, 4).astype(np.int32)
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    p = pal.astype(np.int32)
    w = np.array([1, 1, 1, alpha_weight])
    res = np.empty(len(uniq), np.uint8)
    transp = np.where(p[:, 3] == 0)[0]
    for s in range(0, len(uniq), 4096):
        u = uniq[s:s + 4096]
        # premultiply colour by alpha so invisible colour differences do not matter
        ua = u.copy(); ua[:, :3] = ua[:, :3] * ua[:, 3:4] // 255
        pa = p.copy(); pa[:, :3] = pa[:, :3] * pa[:, 3:4] // 255
        d = (((ua[:, None, :] - pa[None, :, :]) ** 2) * w).sum(-1)
        r = d.argmin(1)
        if len(transp):
            r[u[:, 3] == 0] = transp[0]
        res[s:s + 4096] = r
    return res[inv.reshape(-1)].reshape(rgba.shape[:-1])


def image_to_texture(anm: AnmFile, tex_index: int, img, palette_index: Optional[int] = 0,
                     replace_palette: bool = False, resize_ok: bool = True) -> None:
    """Import a PIL image into texture `tex_index` (file-global).

    * indexed texture, replace_palette=False: re-quantize to palette `palette_index`
      (the pixel indices are shared by all colour variants, so choose the variant the
      artwork was painted in).  If the image is mode 'P' it is used as raw indices.
    * indexed texture, replace_palette=True: build a new <=256 colour palette from the
      image (PIL quantize) and write it to `palette_index` (other variants keep their
      old colours, which then no longer match - edit them with set_palette).
    * ARGB32 texture: stored directly.
    If the size differs the texture is resized in the file (resize_ok) and the legacy
    TextureInfo of the owning block is updated; cells keep their pixel rectangles.
    """
    from PIL import Image
    t = anm.textures[tex_index]
    w, h = img.size
    if (w, h) != (t.width, t.height):
        if not resize_ok:
            raise ValueError("size mismatch")
        t.width, t.height = w, h
        for b in anm.blocks:
            li = tex_index - b.tex_base
            if 0 <= li < len(b.texture_infos):
                b.texture_infos[li].width, b.texture_infos[li].height = w, h
    if not t.indexed:
        arr = np.asarray(img.convert("RGBA"), np.uint8)
        t.data = _rgba_to_argb(arr).tobytes()
        return
    if img.mode == "P" and not replace_palette:
        t.data = np.asarray(img, np.uint8).tobytes()
        return
    rgba = np.asarray(img.convert("RGBA"), np.uint8)
    if replace_palette:
        q = img.convert("RGBA").quantize(colors=255, method=Image.Quantize.FASTOCTREE)
        qp = np.array(q.getpalette("RGBA")[:255 * 4], np.uint8).reshape(-1, 4) if hasattr(q, "getpalette") else None
        pal = np.zeros((256, 4), np.uint8)
        pal[1:1 + len(qp)] = qp
        idx = np.asarray(q, np.uint8).astype(np.int32) + 1
        idx[rgba[..., 3] == 0] = 0
        set_palette(anm, palette_index, pal)
        t.data = idx.astype(np.uint8).tobytes()
        return
    pal = get_palette(anm, palette_index)
    t.data = quantize_to_palette(rgba, pal).astype(np.uint8).tobytes()


# --------------------------------------------------------------------------------------
# animation evaluation / rendering
# --------------------------------------------------------------------------------------

@dataclass
class DrawItem:
    node: int
    depth: int
    key: Key
    cell: Cell
    quad: np.ndarray          # (4,2) screen coords of the cell corners TL,TR,BR,BL (origin = feet)
    color: Tuple[int, ...]    # 5 x RGBA (TL,TR,BR,BL,centre); RGB 128 = 1.0, A 255 = opaque
    tex_global: int
    pal_local: int
    block: int = 0


def _resolve_anim(anm: AnmFile, anim_index) -> Tuple[int, int]:
    """anim_index: int (flat index over all blocks), ('id', animation_id) or (block, idx)."""
    if isinstance(anim_index, tuple):
        if anim_index[0] == "id":
            for bi, ai, a in anm.all_animations():
                if a.id == anim_index[1]:
                    return bi, ai
            raise KeyError(anim_index)
        return anim_index
    flat = anm.all_animations()
    bi, ai, _ = flat[anim_index]
    return bi, ai


def list_animations(anm: AnmFile):
    """List of dicts: index (flat, use for render_frame), block, anim, id, root,
    length (frames @60fps), loop (start,end) or None, control [(time, cmd)], layers."""
    out = []
    for flat, (bi, ai, a) in enumerate(anm.all_animations()):
        b = anm.blocks[bi]
        info = animation_info(b, a)
        info.update(index=flat, block=bi, anim=ai, id=a.id, root=a.root)
        out.append(info)
    return out


def animation_info(b: AnmBlock, a: Animation) -> dict:
    root = b.nodes[a.root]
    ctl = [(k.time, k.flags & 0xFF) for k in b.node_keys(root)]
    length = 0
    layers = 0
    for ni, d, p in b.walk(a.root):
        ks = b.node_keys(b.nodes[ni])
        if ks:
            length = max(length, ks[-1].time)
        if any(k.cell for k in ks):
            layers += 1
    loop = None
    starts = [t for t, c in ctl if c == 1]
    ends = [t for t, c in ctl if c == 2]
    if ends:
        loop = (starts[0] if starts else 0, ends[0])
        length = ends[0]
    else:
        e5 = [t for t, c in ctl if c == 5]
        if e5:
            length = max(e5)
    return dict(length=length, loop=loop, control=ctl, layers=layers)


def _active_key(keys: List[Key], t: float):
    """(key, next_key_or_None, fraction) or None if t is before the first key."""
    if not keys or t < keys[0].time:
        return None
    i = 0
    for j, k in enumerate(keys):
        if k.time <= t:
            i = j
        else:
            break
    k = keys[i]
    if (k.flags & 0xFF) == 1 and i + 1 < len(keys) and keys[i + 1].time > k.time:
        n = keys[i + 1]
        return k, n, (t - k.time) / (n.time - k.time)
    return k, None, 0.0


_IDENT = Transform(0, 0, 0, 0, 100, 100, 0)
_WHITE = Color((128, 128, 128, 255) * 5)


def _get(lst, i, default):
    return lst[i] if 0 <= i < len(lst) else default


def _pivot_pts(b: AnmBlock, idx: int, n: int) -> np.ndarray:
    return np.array([[p.x, p.y] for p in (_get(b.pivots, idx + j, Pivot(0, 0)) for j in range(n))], float)


def _key_state(b: AnmBlock, node: Node, key: Key, nxt: Optional[Key], f: float):
    """Interpolated (x, y, sx, sy, rot), pivot-or-vertices, 5-colour tuple."""
    x = _get(b.transforms, key.xform, _IDENT)
    vals = np.array([x.x, x.y, x.sx, x.sy, x.rot], float)
    npts = 4 if node.mesh else 1
    pts = _pivot_pts(b, x.pivot, npts)
    col = np.array(_get(b.colors, key.color, _WHITE).rgba, float)
    if nxt is not None:
        y = _get(b.transforms, nxt.xform, _IDENT)
        vals += (np.array([y.x, y.y, y.sx, y.sy, y.rot], float) - vals) * f
        pts += (_pivot_pts(b, y.pivot, npts) - pts) * f
        col += (np.array(_get(b.colors, nxt.color, _WHITE).rgba, float) - col) * f
    return vals, pts, tuple(int(round(c)) for c in col)


def _mat(tx, ty, sx, sy, rot_deg):
    """parent-space matrix: translate * rotate(clockwise on screen, y down) * scale(percent)."""
    r = math.radians(rot_deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([[c * sx / 100.0, -s * sy / 100.0, tx],
                     [s * sx / 100.0, c * sy / 100.0, ty],
                     [0, 0, 1]], float)


def _apply(m, pts):
    p = np.c_[pts, np.ones(len(pts))]
    return (m @ p.T)[:2].T


NESTED = 0x100                 # key flags: draw animation params[key.param] here (the node's transform applies)


def is_nested(k) -> bool:
    return (k.flags & 0xFF00) == NESTED and not k.cell


_STUBS = {}


def is_stub(anm: AnmFile, bi: int, ai: int) -> bool:
    """an animation that draws no picture of its own (the shared poses that show another animation through a
    0x100 key); in ordinary animations 0x100 keys mean something else (weapon / part references)"""
    key = (id(anm), bi, ai)
    hit = _STUBS.get(key)
    if hit is None:
        b = anm.blocks[bi]
        hit = _STUBS[key] = animation_info(b, b.animations[ai])["layers"] == 0
        if len(_STUBS) > 50000:
            _STUBS.clear()
    return hit


def has_animation(anm: AnmFile, anim_id) -> bool:
    try:
        _resolve_anim(anm, ("id", int(anim_id)))
        return True
    except (KeyError, TypeError, ValueError):
        return False


def evaluate(anm: AnmFile, anim_index, time: float, nested: bool = False, _depth: int = 0) -> List[DrawItem]:
    """Evaluate the node tree of an animation at `time` (frames). Returns draw items in
    painting order (back to front).  nested: a stub animation (no pictures of its own) shows the animation its 0x100
    keys name (the shared humanoid poses: a hurt / guard animation with a shake around it) -- for showing only:
    those items belong to the other animation (editing tools leave nested off)."""
    bi, ai = _resolve_anim(anm, anim_index)
    b = anm.blocks[bi]
    a = b.animations[ai]
    items: List[DrawItem] = []
    nest = nested and _depth < 3 and is_stub(anm, bi, ai)

    def rec(ni, parent_m, depth, seen):
        while 0 <= ni < len(b.nodes) and ni not in seen:
            seen.add(ni)
            n = b.nodes[ni]
            ks = b.node_keys(n)
            m = parent_m
            act = _active_key(ks, time) if ks else None
            visible = not ks or act is not None
            if act is not None:
                k, nx, f = act
                vals, pts, col = _key_state(b, n, k, nx, f)
                m = parent_m @ _mat(*vals)
                if k.cell and k.cell < len(b.cells):
                    c = b.cells[k.cell]
                    if n.mesh:          # 4 explicit vertices (TL,TR,BR,BL) relative to the node
                        quad = _apply(m, pts)
                    else:               # rectangle placed so that the pivot lands on (x,y)
                        px, py = pts[0]
                        quad = _apply(m, np.array([[0, 0], [c.w, 0], [c.w, c.h], [0, c.h]], float)
                                      - [px, py])
                    items.append(DrawItem(ni, depth, k, c, quad, col, b.tex_base + c.tex, c.pal, bi))
                elif nest and is_nested(k):
                    sub_id = b.params[k.param] if 0 <= k.param < len(b.params) else None
                    if sub_id is not None and sub_id != a.id and has_animation(anm, sub_id):
                        sub = evaluate(anm, ("id", sub_id), max(0.0, time - k.time), True, _depth + 1)
                        items.extend(reversed([DrawItem(it.node, it.depth + depth, it.key, it.cell, _apply(m, it.quad),
                                                        it.color, it.tex_global, it.pal_local, it.block)
                                               for it in sub]))
            if visible and n.child >= 0:
                rec(n.child, m, depth + 1, seen)
            ni = n.next

    rec(a.root, np.eye(3), 0, set())
    # file order = front to back (the first node is drawn on top) -> reverse for painting
    items.reverse()
    return items


def frame_times(anm: AnmFile, anim_index) -> List[int]:
    """Distinct key times of an animation (the 'frames' of render_frame)."""
    bi, ai = _resolve_anim(anm, anim_index)
    b = anm.blocks[bi]
    ts = set()
    for ni, d, p in b.walk(b.animations[ai].root):
        for k in b.node_keys(b.nodes[ni]):
            ts.add(k.time)
    info = animation_info(b, b.animations[ai])
    return sorted(t for t in ts if not info["loop"] or t <= info["loop"][1]) or [0]


def _cell_image(anm: AnmFile, it: DrawItem, variant: int, cache: dict):
    """Crop of the cell (RGBA). variant = colour variant (palette offset within the block)."""
    key = (it.tex_global, it.pal_local, variant, it.block)
    if key not in cache:
        if it.tex_global >= len(anm.textures):
            cache[key] = None
        else:
            b = anm.blocks[it.block]
            npal = len(b.palette_infos)
            gp = b.pal_base + min(it.pal_local + variant, max(0, npal - 1)) if anm.palettes else 0
            cache[key] = texture_to_image(anm, it.tex_global, min(gp, max(0, len(anm.palettes) - 1)))
    im = cache[key]
    if im is None:
        return None
    c = it.cell
    return im.crop((c.x, c.y, c.x + c.w, c.y + c.h))


def _homography(src, dst):
    """3x3 H with H @ src_i ~ dst_i (4 point pairs)."""
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    h = np.linalg.solve(np.array(A, float), np.array(dst, float).reshape(-1))
    return np.append(h, 1).reshape(3, 3)


def item_bounds(items: List[DrawItem]):
    if not items:
        return (-8, -8, 8, 8)
    allp = np.concatenate([it.quad for it in items])
    return (min(-4, math.floor(allp[:, 0].min()) - 2), min(-4, math.floor(allp[:, 1].min()) - 2),
            max(4, math.ceil(allp[:, 0].max()) + 2), max(4, math.ceil(allp[:, 1].max()) + 2))


def render_items(anm: AnmFile, items: List[DrawItem], palette_index: int = 0, scale: float = 1.0,
                 bounds=None, background=(0, 0, 0, 0), show_origin: bool = False,
                 apply_color: bool = True):
    """Compose draw items (normal alpha blending). Returns (PIL image, (origin_x, origin_y))."""
    from PIL import Image, ImageDraw
    cache = {}
    x0, y0, x1, y1 = bounds if bounds is not None else item_bounds(items)
    W = max(1, int(math.ceil((x1 - x0) * scale)))
    H = max(1, int(math.ceil((y1 - y0) * scale)))
    canvas = Image.new("RGBA", (W, H), tuple(background))
    for it in items:
        c = it.cell
        if c.w == 0 or c.h == 0:
            continue
        src = _cell_image(anm, it, palette_index, cache)
        if src is None:
            continue
        col = it.color
        if apply_color and (col[:4] != (128, 128, 128, 255)):
            arr = np.asarray(src, np.float32).copy()
            arr[..., :3] *= np.array(col[:3], np.float32) / 128.0
            arr[..., 3] *= col[3] / 255.0
            src = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
        dst = (it.quad - [x0, y0]) * scale
        e1, e2 = dst[1] - dst[0], dst[3] - dst[0]
        if abs(e1[0] * e2[1] - e1[1] * e2[0]) < 1e-6:
            continue                      # degenerate (zero width) quad
        srcq = [(0, 0), (c.w, 0), (c.w, c.h), (0, c.h)]
        try:
            Hm = _homography(dst, srcq)   # output pixel -> source pixel
        except np.linalg.LinAlgError:
            continue
        layer = src.transform((W, H), Image.PERSPECTIVE, data=tuple(Hm.reshape(-1)[:8]),
                              resample=Image.BILINEAR)
        canvas.alpha_composite(layer)
    origin = (-x0 * scale, -y0 * scale)
    if show_origin:
        d = ImageDraw.Draw(canvas)
        ox, oy = origin
        d.line((ox - 6, oy, ox + 6, oy), fill=(255, 0, 0, 255))
        d.line((ox, oy - 6, ox, oy + 6), fill=(255, 0, 0, 255))
    return canvas, origin


def render_frame(anm: AnmFile, anim_index, frame_index: int = 0, palette_index: int = 0,
                 time: Optional[float] = None, **kw):
    """Render the pose of animation `anim_index` at its `frame_index`-th key time (or at an
    explicit `time` in frames) as a PIL RGBA image cropped to the sprite (+2px).
    palette_index = colour variant (0 = default).  anim_index: flat index (see
    list_animations), ('id', 1001) or (block, anim).  kw -> render_items (scale, bounds,
    background, show_origin)."""
    if time is None:
        ts = frame_times(anm, anim_index)
        time = ts[min(frame_index, len(ts) - 1)]
    items = evaluate(anm, anim_index, time)
    img, origin = render_items(anm, items, palette_index, **kw)
    return img


def render_animation_strip(anm: AnmFile, anim_index, palette_index: int = 0, step: Optional[int] = None,
                           max_frames: int = 24, background=(0, 96, 0, 255)):
    """Horizontal strip of frames sharing common bounds (red cross = origin)."""
    from PIL import Image
    ts = frame_times(anm, anim_index)
    if step:
        ts = list(range(0, max(ts) + 1, step))
    ts = ts[:max_frames]
    all_items = [evaluate(anm, anim_index, t) for t in ts]
    b = item_bounds([it for items in all_items for it in items])
    frames = [render_items(anm, items, palette_index, bounds=b, background=background,
                           show_origin=True)[0] for items in all_items]
    W = sum(f.width for f in frames)
    strip = Image.new("RGBA", (max(1, W), frames[0].height if frames else 1), background)
    x = 0
    for f in frames:
        strip.paste(f, (x, 0))
        x += f.width
    return strip


# --------------------------------------------------------------------------------------
# character lookup
# --------------------------------------------------------------------------------------

@dataclass
class CharSprite:
    record: int            # char.dat record index
    name: str              # EN name
    title: str             # EN class / title
    graphics_id: int       # char.dat +0xDE (u16) (+0xD0 = same except for NPC/special records)
    base_id: int           # char.dat +0xF6 (u16) "base character" id (faces/portraits, fallback)
    anm: int               # sprite file number = graphics_id - graphics_id % 10  (anmNNNN0)
    anm_light: int         # anm + 1: reduced copy (same sheets/palettes, fewer anims)
    palette: int           # colour variant = graphics_id % 10 (generic class tier)
    motion_set: Optional[str] = None   # 'resident:1' if the file has no standard motions

    @property
    def exists(self):
        from . import util
        return os.path.exists(os.path.join(util.EXTRACTED, "Anime", "ANM_HI_JP", "anm%05d.dat" % self.anm))


CHAR_REC_SIZE = 908
CHAR_NAME_OFFSETS = [0xF8, 0x12C, 0x160, 0x194, 0x1C8]     # JP, EN, FR, zh-TW, KO (52 bytes each)
CHAR_TITLE_OFFSETS = [0x1FC, 0x240, 0x284, 0x2C8, 0x30C]    # 68 bytes each
CHAR_GRAPHICS_OFFSET = 0xDE
CHAR_BASE_OFFSET = 0xF6


def read_char_table(path: Optional[str] = None) -> List[CharSprite]:
    from . import util
    p = path or os.path.join(util.EXTRACTED, "Database", "Database_0", "char.dat")
    d = open(p, "rb").read()
    count = struct.unpack_from("<I", d, 0)[0]
    rec = (len(d) - 4) // count
    out = []
    for i in range(count):
        r = d[4 + i * rec:4 + (i + 1) * rec]
        gid = struct.unpack_from("<H", r, CHAR_GRAPHICS_OFFSET)[0]
        base = struct.unpack_from("<H", r, CHAR_BASE_OFFSET)[0]
        out.append(CharSprite(i, _cstr(r, CHAR_NAME_OFFSETS[1], 52), _cstr(r, CHAR_TITLE_OFFSETS[1], 68),
                              gid, base, gid - gid % 10, gid - gid % 10 + 1, gid % 10))
    return out


def find_character_anm(name: str) -> List[CharSprite]:
    """Search char.dat (EN name or title, case-insensitive substring; exact matches first) and
    return CharSprite entries: which anmNNNNN file draws the character and which palette
    (colour variant) it uses.  e.g. find_character_anm('Killia')[0].anm == 10."""
    q = name.lower()
    hits = [c for c in read_char_table() if q in c.name.lower() or q in c.title.lower()]
    hits.sort(key=lambda c: (c.name.lower() != q and c.title.lower() != q, c.record))
    for c in hits:
        c.motion_set = None
        try:
            if c.exists:
                from . import util
                f = os.path.join(util.EXTRACTED, "Anime", "ANM_HI_JP", "anm%05d.dat" % c.anm)
                with open(f, "rb") as fh:
                    head = fh.read(0x2C)
                nanim = struct.unpack_from("<H", head, 0x26)[0]
                if nanim < 20:
                    c.motion_set = "resident:1"
        except OSError:
            pass
    return hits


def bind_motion_set(motion: AnmFile, block_index: int, sprite: AnmFile) -> AnmFile:
    """Combine a shared motion block (e.g. anm_resident block with id 1 = humanoid motions)
    with a character's sprite file (textures + palettes).  The result is a view for
    rendering only (do not save it).  Cells of the motion block index the sprite's textures."""
    import copy
    b = copy.copy(motion.blocks[block_index])
    b.tex_base = 0
    b.pal_base = 0
    b.palette_infos = list(sprite.blocks[0].palette_infos)
    return AnmFile([b], sprite.textures, sprite.palettes)


def _cstr(b, o, n=60):
    s = b[o:o + n].split(b"\0")[0]
    return s.decode("utf-8", "replace")
