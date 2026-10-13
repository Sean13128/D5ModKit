"""TXF textures (UI / effect textures).

Header 16 bytes, big-endian:
  u8  fmt[4]      00 01 01 01 -> 32bpp ARGB8888 (A,R,G,B byte order)
  u16 width, u16 height
  u32 unk (0x00010000)
  u32 pixel_bytes
Some '.txf' members are plain DDS files instead (fonts, after YKCMP type 4).
Some TXF carry a trailing ICC colour profile after the pixels; it is preserved on re-encode.
"""
import io
import struct

import numpy as np
from PIL import Image


def is_dds(data: bytes) -> bool:
    return data[:4] == b"DDS "


def info(data: bytes) -> dict:
    if is_dds(data):
        h, w = struct.unpack_from("<II", data, 12)
        return {"kind": "dds", "width": w, "height": h}
    fmt = data[:4]
    w, h = struct.unpack_from(">HH", data, 4)
    unk, size = struct.unpack_from(">II", data, 8)
    return {"kind": "txf", "fmt": fmt.hex(), "width": w, "height": h, "unk": unk, "size": size}


def _dds_alpha8(data: bytes) -> Image.Image:
    h, w = struct.unpack_from("<II", data, 12)
    a = np.frombuffer(data[128:128 + w * h], np.uint8).reshape(h, w)
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = a
    return Image.fromarray(rgba, "RGBA")


def to_image(data: bytes) -> Image.Image:
    if is_dds(data):
        pf_flags = struct.unpack_from("<I", data, 80)[0]
        if pf_flags == 2:  # DDPF_ALPHA, 8-bit alpha only (fonts)
            return _dds_alpha8(data)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    i = info(data)
    w, h = i["width"], i["height"]
    if data[0] != 0:
        raise ValueError(f"unsupported txf format {i['fmt']}")
    px = np.frombuffer(data[16:16 + w * h * 4], np.uint8).reshape(h, w, 4)
    return Image.fromarray(px[:, :, (1, 2, 3, 0)].copy(), "RGBA")


def from_image(img: Image.Image, template: bytes = None) -> bytes:
    """Encode an image as a 32bpp TXF. If template given, its header flags are preserved."""
    img = img.convert("RGBA")
    w, h = img.size
    px = np.asarray(img, np.uint8)[:, :, (3, 0, 1, 2)]
    fmt = template[:4] if template and not is_dds(template) else b"\x00\x01\x01\x01"
    unk = struct.unpack_from(">I", template, 8)[0] if template and not is_dds(template) else 0x10000
    trailer = b""
    if template and not is_dds(template):
        tw, th = struct.unpack_from(">HH", template, 4)
        trailer = template[16 + tw * th * 4:]  # optional embedded ICC profile, kept verbatim
    return fmt + struct.pack(">HHII", w, h, unk, w * h * 4) + px.tobytes() + trailer
