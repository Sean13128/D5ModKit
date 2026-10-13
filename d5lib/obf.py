""".obf 3D container (maps: mapNNNNN.obf inside the map pac; objects: Object_*.dat; effects: Effect.dat).

Layout (little endian):
    u32 total_size          (= file length, minus zero padding to 16 when stored inside a map pac)
    u32 version             (always 2)
    u32 section_offset[10]  (absolute, contiguous, first = 0x30; section i ends where i+1 starts,
                             section 9 ends at total_size)
Sections 2, 3, 6, 7, 9 are *offset tables*: u32 n, u32 off[n] (relative to the section start,
off[0] = 4 + 4n), then n entries back to back.

    0  u32 0
    1  8 bytes (u32 1, u32 0 on almost all files)
    2  table  (scene/root objects?)
    3  table  groups: {u32 id, i16 parent(-1), u8, u8, u32 n, u32 child[n]}
    4  motion/animation data (u32 ints, not an offset table)
    5  float block (starts with 1.0)
    6  table  parts: {u32 n, u32 x8, u32 list[...]} (lists of mesh indices)
    7  table  meshes: {u32 vertex_count, u32 texture_index, u8 rgba[4], f32 x5, u8 flags[12], i32 -1,
                       u32 index[vertex_count]}   -- non-indexed triangle lists: the indices are
                       always a running counter, i.e. mesh k draws vertices [start_k, start_k+count_k)
    8  vertex buffer, 60-byte vertices: f32 pos[3], normal[3], tangent[3], color[4] (0.5 = 1.0),
       uv[2]
    9  table  textures: {u32 attr, TXF}  (TXF = 16-byte big-endian header + data (+ICC trailer))

TXF format byte (first header byte): 0x00 A8R8G8B8, 0x02 DXT1/BC1, 0x04 DXT3/BC2, 0x06 DXT5/BC3,
0x0b ARGB1555 / 0x0d ARGB4444 (16-bit big-endian words, seen in effects), 0x0c effect textures: little-endian header, 8-bit luminance + 8-bit alpha,
`attr` (= data size / (w*h*2)) layers of w x h stacked (the effect's colour commands tint them).
No mipmaps are stored.
"""
import io
import os
import struct

import numpy as np


N_SECTIONS = 10
VERTEX_SIZE = 60
TABLE_SECTIONS = (2, 3, 6, 7, 9)
FMT_ARGB, FMT_DXT1, FMT_DXT3, FMT_DXT5, FMT_LA = 0x00, 0x02, 0x04, 0x06, 0x0C
FMT_1555, FMT_565 = 0x0B, 0x0D       # 0x0D: RGB565 (all 160 vanilla ones decode smoothly only so)
FMT_NAMES = {0x00: "ARGB8888", 0x02: "DXT1", 0x04: "DXT3", 0x06: "DXT5", 0x0B: "ARGB1555",
             0x0C: "LA88", 0x0D: "RGB565"}


# ============================================================================ offset tables
def read_table(sec: bytes):
    n = struct.unpack_from("<I", sec)[0]
    offs = list(struct.unpack_from(f"<{n}I", sec, 4)) + [len(sec)]
    return [bytes(sec[offs[i]:offs[i + 1]]) for i in range(n)]


def build_table(entries) -> bytes:
    n = len(entries)
    pos = 4 + 4 * n
    offs = []
    for e in entries:
        offs.append(pos)
        pos += len(e)
    return struct.pack(f"<I{n}I", n, *offs) + b"".join(entries)


# ============================================================================ texture entry
class Texture:
    """Entry of section 9: u32 attr + TXF blob."""

    def __init__(self, entry: bytes):
        self.attr = bytes(entry[:4])
        self.txf = bytes(entry[4:])
        self.fmt = self.txf[0]
        e = "<" if self.fmt == FMT_LA or self._little() else ">"      # header byte order varies per texture
        self.endian = e
        self.width, self.height = struct.unpack_from(e + "HH", self.txf, 4)
        self.unk, self.size_field = struct.unpack_from(e + "II", self.txf, 8)
        self.layers = max(1, self.size_field // max(1, self.width * self.height * 2)) if self.fmt == FMT_LA else 1

    def _little(self):
        """a few textures (e.g. effect1740) store the header little-endian: the size field tells"""
        w, h, _, n = struct.unpack_from(">HHII", self.txf, 4)
        lw, lh, _, ln = struct.unpack_from("<HHII", self.txf, 4)
        bpp = {FMT_ARGB: 4, 0x0B: 2, 0x0D: 2}.get(self.fmt)
        return bpp is not None and n != w * h * bpp and ln == lw * lh * bpp and len(self.txf) >= 16 + ln

    def to_entry(self) -> bytes:
        return self.attr + self.txf

    @property
    def format_name(self):
        return FMT_NAMES.get(self.fmt, f"fmt{self.fmt:02x}")

    def data_size(self):
        w, h = self.width, self.height
        bw, bh = (w + 3) // 4, (h + 3) // 4
        return {FMT_ARGB: w * h * 4, FMT_DXT1: bw * bh * 8, FMT_DXT3: bw * bh * 16,
                FMT_DXT5: bw * bh * 16, 0x0B: w * h * 2, 0x0D: w * h * 2,
                FMT_LA: w * h * 2 * self.layers}.get(self.fmt)

    @property
    def decodable(self):
        n = self.data_size()
        return n is not None and len(self.txf) >= 16 + n

    def to_image(self):
        from PIL import Image
        w, h = self.width, self.height
        n = self.data_size()
        if n is None or len(self.txf) < 16 + n:
            raise ValueError(f"cannot decode texture format {self.format_name}")
        px = self.txf[16:16 + n]
        if self.fmt == FMT_ARGB:
            a = np.frombuffer(px, np.uint8).reshape(h, w, 4)[:, :, (1, 2, 3, 0)]
        elif self.fmt in (FMT_DXT1, FMT_DXT3, FMT_DXT5):
            a = decode_bc(px, w, h, self.fmt)
        elif self.fmt == FMT_LA:                # all layers, stacked: w x (h * layers)
            la = np.frombuffer(px, np.uint8).reshape(h * self.layers, w, 2)
            a = np.dstack([la[..., 0]] * 3 + [la[..., 1]])
        elif self.fmt in (FMT_1555, FMT_565):
            a = _decode_16(px, w, h, self.fmt)
        else:
            raise ValueError(self.format_name)
        return Image.fromarray(np.ascontiguousarray(a), "RGBA")

    def replace_image(self, img, keep_format=True, resize=False):
        """Replace pixels with a PIL image of the same size. keep_format=True re-encodes to the
        original DXT format (simple bounding-box BC encoder); False switches to ARGB8888.
        LA88 (effect) textures stay LA88: the image is all layers stacked (w x h*layers), or one w x h picture
        used for every layer; colour becomes luminance (the effect tints it), transparency stays alpha.
        resize=True: the texture takes the image's size instead (non-LA88; sides should be powers of 2)."""
        img = img.convert("RGBA")
        if self.fmt == FMT_LA:
            return self._replace_la(img)
        if resize and img.size != (self.width, self.height):
            if self.fmt in (FMT_DXT1, FMT_DXT3, FMT_DXT5) and (img.width % 4 or img.height % 4):
                raise ValueError("DXT textures need sides that are multiples of 4")
            self.width, self.height = img.size
            self.txf = self.txf[:16]                   # the old pixels (and trailer) don't fit any more
        if img.size != (self.width, self.height):
            raise ValueError(f"image must be {self.width}x{self.height}, got {img.size}")
        rgba = np.asarray(img, np.uint8)
        fmt = self.fmt if keep_format else FMT_ARGB
        if fmt == FMT_ARGB:
            data = rgba[:, :, (3, 0, 1, 2)].tobytes()
            trailer = self.txf[16 + self.data_size():] if self.fmt == FMT_ARGB else b""
        elif fmt in (FMT_DXT1, FMT_DXT3, FMT_DXT5):
            data = encode_bc(rgba, fmt)
            trailer = b""
        elif fmt in (FMT_1555, FMT_565):
            data = _encode_16(rgba, fmt)
            trailer = self.txf[16 + self.data_size():]
        else:
            raise ValueError(f"cannot encode format {self.format_name}")
        head = bytes([fmt]) + self.txf[1:4] + struct.pack(self.endian + "HHII", self.width, self.height, self.unk,
                                                          len(data))
        self.txf = head + data + trailer
        self.fmt = fmt
        self.size_field = len(data)

    def _replace_la(self, img):
        w, h, k = self.width, self.height, self.layers
        if img.size == (w, h) and k > 1:
            img = _stack([img] * k)
        if img.size != (w, h * k):
            raise ValueError(f"image must be {w}x{h} or {w}x{h * k} ({k} layers), got {img.size}")
        rgba = np.asarray(img, np.uint8).astype(np.float32)
        lum = np.max(rgba[..., :3], -1)                  # brightest channel: a coloured picture keeps its strength
        data = np.dstack([lum, rgba[..., 3]]).round().clip(0, 255).astype(np.uint8).tobytes()
        self.txf = self.txf[:16] + data + self.txf[16 + self.data_size():]


def _stack(imgs):
    from PIL import Image
    out = Image.new("RGBA", (imgs[0].width, sum(i.height for i in imgs)))
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height
    return out


# ============================================================================ BCn codec
def _565_to_rgb(c):
    r = ((c >> 11) & 31).astype(np.uint16)
    g = ((c >> 5) & 63).astype(np.uint16)
    b = (c & 31).astype(np.uint16)
    return np.stack([(r * 527 + 23) >> 6, (g * 259 + 33) >> 6, (b * 527 + 23) >> 6], -1).astype(np.int32)


def _color_block_decode(blk, force4=False):
    """blk: (N, 8) uint8 -> (N, 16, 4) uint8 RGBA."""
    c0 = blk[:, 0].astype(np.uint16) | (blk[:, 1].astype(np.uint16) << 8)
    c1 = blk[:, 2].astype(np.uint16) | (blk[:, 3].astype(np.uint16) << 8)
    p0, p1 = _565_to_rgb(c0), _565_to_rgb(c1)
    four = (c0 > c1) | force4
    pal = np.empty((len(blk), 4, 4), np.int32)
    pal[:, 0, :3], pal[:, 1, :3] = p0, p1
    pal[:, :, 3] = 255
    f4 = four[:, None]
    pal[:, 2, :3] = np.where(f4, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3, :3] = np.where(f4, (p0 + 2 * p1) // 3, 0)
    pal[:, 3, 3] = np.where(four, 255, 0)
    bits = blk[:, 4:8].astype(np.uint32)
    word = bits[:, 0] | (bits[:, 1] << 8) | (bits[:, 2] << 16) | (bits[:, 3] << 24)
    idx = (word[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    return np.take_along_axis(pal, idx[:, :, None].astype(np.int64), 1).astype(np.uint8)


def _alpha_bc3_decode(blk):
    a0 = blk[:, 0].astype(np.int32)
    a1 = blk[:, 1].astype(np.int32)
    pal = np.empty((len(blk), 8), np.int32)
    pal[:, 0], pal[:, 1] = a0, a1
    big = (a0 > a1)[:, None]
    k6 = np.arange(1, 7)
    k4 = np.arange(1, 5)
    p8 = ((7 - k6) * a0[:, None] + k6 * a1[:, None]) // 7
    p6 = ((5 - k4) * a0[:, None] + k4 * a1[:, None]) // 5
    pal[:, 2:8] = np.where(big, p8, np.concatenate([p6, np.zeros((len(blk), 1), np.int32),
                                                     np.full((len(blk), 1), 255, np.int32)], 1))
    bits = np.zeros(len(blk), np.uint64)
    for i in range(6):
        bits |= blk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    idx = (bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))) & np.uint64(7)
    return np.take_along_axis(pal, idx.astype(np.int64), 1).astype(np.uint8)


def decode_bc(data: bytes, w: int, h: int, fmt: int) -> np.ndarray:
    bw, bh = (w + 3) // 4, (h + 3) // 4
    bs = 8 if fmt == FMT_DXT1 else 16
    blk = np.frombuffer(data, np.uint8, bw * bh * bs).reshape(bw * bh, bs)
    if fmt == FMT_DXT1:
        px = _color_block_decode(blk)
    else:
        px = _color_block_decode(blk[:, 8:16], force4=True)
        if fmt == FMT_DXT3:
            nib = blk[:, 0:8]
            a = np.empty((len(blk), 16), np.uint8)
            a[:, 0::2] = (nib & 15) * 17
            a[:, 1::2] = (nib >> 4) * 17
            px[:, :, 3] = a
        else:
            px[:, :, 3] = _alpha_bc3_decode(blk[:, 0:8])
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w]


def _rgb_to_565(rgb):
    rgb = rgb.astype(np.int32)
    return (((rgb[..., 0] * 31 + 127) // 255) << 11) | (((rgb[..., 1] * 63 + 127) // 255) << 5) | \
        ((rgb[..., 2] * 31 + 127) // 255)


def encode_bc(rgba: np.ndarray, fmt: int) -> bytes:
    """Simple vectorised BC1/BC2/BC3 encoder (inset bounding box endpoints, nearest-palette indices)."""
    h, w = rgba.shape[:2]
    bw, bh = (w + 3) // 4, (h + 3) // 4
    pad = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    pad[:h, :w] = rgba
    if h % 4 or w % 4:
        pad[h:, :w] = pad[h - 1:h, :w]
        pad[:, w:] = pad[:, w - 1:w]
    blocks = pad.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4).astype(np.int32)
    n = len(blocks)
    rgb = blocks[:, :, :3]
    alpha = blocks[:, :, 3]
    punch = (fmt == FMT_DXT1) & (alpha < 128)            # (n,16) transparent texels (BC1 only)
    use3 = punch.any(1) if fmt == FMT_DXT1 else np.zeros(n, bool)
    # endpoints: bounding box of (opaque) colours, inset by 1/16
    big = np.where(punch[:, :, None], 10 ** 6, rgb)
    small = np.where(punch[:, :, None], -1, rgb)
    mn = big.min(1)
    mx = small.max(1)
    allt = punch.all(1)
    mn = np.where(allt[:, None], 0, mn)
    mx = np.where(allt[:, None], 0, mx)
    inset = (mx - mn) // 16
    mn = np.clip(mn + inset, 0, 255)
    mx = np.clip(mx - inset, 0, 255)
    c0 = _rgb_to_565(mx).astype(np.int32)
    c1 = _rgb_to_565(mn).astype(np.int32)
    # 4-colour mode needs c0 > c1, 3-colour mode needs c0 <= c1
    swap4 = (~use3) & (c0 < c1)
    swap3 = use3 & (c0 > c1)
    sw = swap4 | swap3
    c0, c1 = np.where(sw, c1, c0), np.where(sw, c0, c1)
    eq4 = (~use3) & (c0 == c1)                         # degenerate: all texels index 0
    p0, p1 = _565_to_rgb(c0.astype(np.uint16)), _565_to_rgb(c1.astype(np.uint16))
    pal = np.empty((n, 4, 3), np.int32)
    pal[:, 0], pal[:, 1] = p0, p1
    u3 = use3[:, None]
    pal[:, 2] = np.where(u3, (p0 + p1) // 2, (2 * p0 + p1) // 3)
    pal[:, 3] = np.where(u3, 0, (p0 + 2 * p1) // 3)
    d = ((rgb[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)       # (n,16,4)
    d[:, :, 3] = np.where(use3[:, None], 1 << 40, d[:, :, 3])          # index 3 = transparent in 3-mode
    idx = d.argmin(-1)
    idx = np.where(punch, 3, idx)
    idx = np.where(eq4[:, None], 0, idx)
    word = (idx.astype(np.uint32) << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    color = np.zeros((n, 8), np.uint8)
    color[:, 0], color[:, 1] = c0 & 255, c0 >> 8
    color[:, 2], color[:, 3] = c1 & 255, c1 >> 8
    for i in range(4):
        color[:, 4 + i] = (word >> (8 * i)) & 255
    if fmt == FMT_DXT1:
        return color.tobytes()
    if fmt == FMT_DXT3:
        a4 = (alpha * 15 + 127) // 255
        ab = (a4[:, 0::2] | (a4[:, 1::2] << 4)).astype(np.uint8)
        return np.concatenate([ab, color], 1).tobytes()
    # BC3 alpha: 8-level mode with a0 = max, a1 = min
    a0 = alpha.max(1)
    a1 = alpha.min(1)
    k = np.arange(8)
    apal = np.empty((n, 8), np.int32)
    apal[:, 0], apal[:, 1] = a0, a1
    for j in range(1, 7):
        apal[:, 1 + j] = ((7 - j) * a0 + j * a1) // 7
    ai = np.abs(alpha[:, :, None] - apal[:, None, :]).argmin(-1).astype(np.uint64)
    ai = np.where((a0 == a1)[:, None], 0, ai).astype(np.uint64)
    bits = (ai << (3 * np.arange(16, dtype=np.uint64))).sum(1).astype(np.uint64)
    ablk = np.zeros((n, 8), np.uint8)
    ablk[:, 0], ablk[:, 1] = a0, a1
    for i in range(6):
        ablk[:, 2 + i] = ((bits >> np.uint64(8 * i)) & np.uint64(255)).astype(np.uint8)
    return np.concatenate([ablk, color], 1).tobytes()


def _decode_16(data, w, h, fmt):
    """16-bit big-endian words: ARGB1555 (0x0b) or RGB565 (0x0d, opaque) -> RGBA"""
    v = np.frombuffer(data, ">u2", w * h).reshape(h, w).astype(np.uint32)
    if fmt == FMT_1555:
        r, g, b = ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31
        a = ((v >> 15) & 1) * 255
    else:
        r, g, b = ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31
        a = np.full_like(v, 255)
    return np.stack([r, g, b, a], -1).astype(np.uint8)


def _encode_16(rgba, fmt):
    c = rgba.astype(np.uint32)
    r, g, b, a = c[..., 0], c[..., 1], c[..., 2], c[..., 3]
    if fmt == FMT_1555:
        v = ((a >= 128) << 15) | ((r * 31 + 127) // 255 << 10) | ((g * 31 + 127) // 255 << 5) | ((b * 31 + 127) // 255)
    else:                                   # RGB565: no alpha (see-through parts become black)
        a = a.astype(np.uint32)
        r, g, b = r * a // 255, g * a // 255, b * a // 255
        v = ((r * 31 + 127) // 255 << 11) | ((g * 63 + 127) // 255 << 5) | ((b * 31 + 127) // 255)
    return v.astype(">u2").tobytes()


# ============================================================================ mesh entry
class Mesh:
    HEAD = 48

    def __init__(self, entry: bytes):
        self.raw_head = bytearray(entry[:self.HEAD])
        self.vertex_count, self.texture_index = struct.unpack_from("<II", entry, 0)
        self.color = tuple(entry[8:12])
        self.params = struct.unpack_from("<5f", entry, 12)
        self.flags = bytes(entry[32:44])
        self.indices = np.frombuffer(entry, "<u4", self.vertex_count, self.HEAD).copy()
        self.tail = bytes(entry[self.HEAD + 4 * self.vertex_count:])

    def to_entry(self) -> bytes:
        struct.pack_into("<II", self.raw_head, 0, self.vertex_count, self.texture_index)
        return bytes(self.raw_head) + self.indices.astype("<u4").tobytes() + self.tail


# ============================================================================ container
class ObfFile:
    def __init__(self, data: bytes):
        self.total_size, self.version = struct.unpack_from("<II", data, 0)
        offs = list(struct.unpack_from(f"<{N_SECTIONS}I", data, 8)) + [self.total_size]
        if offs[0] != 8 + 4 * N_SECTIONS or any(offs[i] > offs[i + 1] for i in range(N_SECTIONS)):
            raise ValueError("bad .obf section table")
        self.sections = [bytes(data[offs[i]:offs[i + 1]]) for i in range(N_SECTIONS)]
        self.trailer = bytes(data[self.total_size:])
        self.pad16 = len(data) % 16 == 0 and len(self.trailer) < 16
        self._tex = None
        self._mesh = None

    # ---- textures
    @property
    def textures(self):
        if self._tex is None:
            self._tex = [Texture(e) for e in read_table(self.sections[9])]
        return self._tex

    @property
    def meshes(self):
        if self._mesh is None:
            self._mesh = [Mesh(e) for e in read_table(self.sections[7])]
        return self._mesh

    def vertices(self) -> np.ndarray:
        """(N, 15) float32: pos xyz, normal xyz, tangent xyz, rgba, uv."""
        return np.frombuffer(self.sections[8], "<f4").reshape(-1, 15)

    def set_vertices(self, v: np.ndarray):
        self.sections[8] = np.asarray(v, "<f4").reshape(-1, 15).tobytes()

    # ---- serialisation
    def to_bytes(self) -> bytes:
        if self._tex is not None:
            self.sections[9] = build_table([t.to_entry() for t in self._tex])
        if self._mesh is not None:
            self.sections[7] = build_table([m.to_entry() for m in self._mesh])
        offs = []
        pos = 8 + 4 * N_SECTIONS
        for s in self.sections:
            offs.append(pos)
            pos += len(s)
        body = struct.pack(f"<II{N_SECTIONS}I", pos, self.version, *offs) + b"".join(self.sections)
        if self.pad16:
            body += b"\0" * (-len(body) % 16)
        else:
            body += self.trailer
        return body

    # ---- convenience
    def export_textures(self, folder, prefix="tex"):
        os.makedirs(folder, exist_ok=True)
        out = []
        for i, t in enumerate(self.textures):
            p = os.path.join(folder, f"{prefix}{i:02d}_{t.format_name}_{t.width}x{t.height}.png")
            try:
                t.to_image().save(p)
                out.append(p)
            except ValueError:
                raw = p[:-4] + ".txf"
                open(raw, "wb").write(t.txf)
                out.append(raw)
        return out

    def replace_texture(self, index, png_path_or_image, keep_format=True):
        from PIL import Image
        img = png_path_or_image if not isinstance(png_path_or_image, (str, os.PathLike)) \
            else Image.open(png_path_or_image)
        self.textures[index].replace_image(img, keep_format=keep_format)

    def export_obj(self, obj_path, texture_prefix=None, flip_v=True):
        """Write Wavefront OBJ + MTL (+ PNG textures next to it). Meshes become groups."""
        folder = os.path.dirname(os.path.abspath(obj_path))
        base = os.path.splitext(os.path.basename(obj_path))[0]
        texture_prefix = texture_prefix or base + "_tex"
        tex_files = self.export_textures(folder, texture_prefix)
        v = self.vertices()
        mtl = io.StringIO()
        for i, p in enumerate(tex_files):
            mtl.write(f"newmtl mat{i}\nKd 1 1 1\n")
            if p.endswith(".png"):
                mtl.write(f"map_Kd {os.path.basename(p)}\n")
            mtl.write("\n")
        mtl.write("newmtl mat_none\nKd 0.8 0.8 0.8\n")
        with open(os.path.join(folder, base + ".mtl"), "w") as f:
            f.write(mtl.getvalue())
        with open(obj_path, "w") as f:
            f.write(f"mtllib {base}.mtl\n")
            pos, nrm, uv = v[:, 0:3], v[:, 3:6], v[:, 13:15].copy()
            if flip_v:
                uv[:, 1] = 1.0 - uv[:, 1]
            f.write("".join("v %.5f %.5f %.5f\n" % tuple(p) for p in pos.tolist()))
            f.write("".join("vt %.5f %.5f\n" % tuple(t) for t in uv.tolist()))
            f.write("".join("vn %.4f %.4f %.4f\n" % tuple(t) for t in nrm.tolist()))
            for k, m in enumerate(self.meshes):
                mat = f"mat{m.texture_index}" if m.texture_index < len(tex_files) else "mat_none"
                f.write(f"g mesh{k:03d}\nusemtl {mat}\n")
                idx = m.indices.astype(np.int64) + 1
                tri = idx[:len(idx) // 3 * 3].reshape(-1, 3)
                f.write("".join("f %d/%d/%d %d/%d/%d %d/%d/%d\n" % (a, a, a, b, b, b, c, c, c)
                                for a, b, c in tri.tolist()))
        return obj_path
