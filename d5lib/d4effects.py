"""Strict decoder for D4 Complete+ legacy effect textures.

Native contract: pinned D4 0x1404516d0. No installation or game access.
"""
from dataclasses import dataclass
import hashlib
import struct

import numpy as np
from PIL import Image

from . import obf, txf

MAGIC = b"nismultitexform\0"
FOOTER = b"nis uti chu eoc "
LIMIT = 64 * 1024 * 1024
# Explicit reviewed offline case, identified by the complete expanded OBF.
# These seals authorize no other resource or live-engine compatibility claim.
EFFECT71_SOURCE_SHA256 = "e8e9fe8cf4f1e63e1b7f26bae7d4f0b3612268b46426f474e565272cb2564069"
EFFECT71_TARGET_SHA256 = "5221d2858422841547c777ba95336a692aba1fb457efeb01f728c65a31bedcf5"
EFFECT71_TARGET_BYTES = 133884
# Bounded storage layouts, not a claim of rendered/material compatibility.
# (legacy format, width, height, ordered palette/frame count)
PALETTE_FRAME_LAYOUTS = frozenset({
    (14, 64, 64, 2), (14, 128, 128, 2), (10, 32, 32, 2),
    (10, 16, 16, 2), (14, 64, 64, 3), (10, 32, 32, 3),
    (10, 32, 64, 3), (10, 64, 64, 3), (14, 32, 32, 2),
    (10, 64, 64, 2), (10, 32, 32, 16), (14, 16, 16, 2),
})


def palette_layout_ok(shape, extended=False):
    """The reviewed layouts above; with `extended` (SPECBULK1, 2026-11-20) also any indexed4/8 surface with
    power-of-two sides of 16..512 and 2..16 palettes: the shapes the adapted D4 special-attack scenes use. Same
    encoder and per-frame pixel verification; sizes outside the reviewed set are not yet seen in a live recording."""
    fmt, width, height, count = shape
    side = lambda n: 16 <= n <= 512 and not n & (n - 1)
    return shape in PALETTE_FRAME_LAYOUTS or (extended and fmt in (10, 14) and side(width) and side(height)
                                              and 2 <= count <= 16)


class UnsupportedEffect(ValueError):
    """A source feature has no verified receiver representation."""


@dataclass(frozen=True)
class LegacyTexture:
    attr: bytes
    width: int
    height: int
    format: int
    palettes: tuple[bytes, ...]
    indices: bytes | None
    rgba_layers: tuple[bytes, ...]
    source_sha256: str
    footer: bytes

    def image(self, palette=0):
        if not 0 <= palette < len(self.rgba_layers):
            raise ValueError("palette outside decoded layers")
        return Image.frombytes("RGBA", (self.width, self.height), self.rgba_layers[palette])


def decode_texture(entry: bytes) -> LegacyTexture:
    """Decode indexed4/8 or color32; preserve every palette and alpha byte.

    Header pointers are relative to the second legacy magic. Unknown layouts,
    padding, pitches, or wrappers are rejected instead of inferred.
    """
    if len(entry) > LIMIT or len(entry) < 84:
        raise ValueError("legacy texture size outside bounds")
    if entry[3] != 2 or entry[4:20] != MAGIC or entry[20:36] != MAGIC:
        raise UnsupportedEffect("expected OBF legacy type 2 and two magic fields")
    zero, size1, size2, zero2 = struct.unpack_from("<4I", entry, 36)
    if zero or zero2 or size1 != size2 or size1 + 84 != len(entry):
        raise ValueError("legacy wrapper size/flags mismatch")
    fmt, dimension, flag, alpha, reserved, npal = entry[52:58]
    width, height, depth, pitch = struct.unpack_from("<3HI", entry, 58)
    if (dimension, flag, alpha, reserved, depth) != (2, 0, 255, 0, 1):
        raise UnsupportedEffect("unverified legacy surface flags/depth")
    if not width or not height or width * height * 4 * max(1, npal) > LIMIT:
        raise ValueError("legacy surface dimensions outside bounds")
    if fmt not in (2, 10, 14):
        raise UnsupportedEffect(f"unverified legacy surface format {fmt:#x}")
    row_bytes = width * 4 if fmt == 2 else width if fmt == 14 else (width + 1) // 2
    if pitch != row_bytes or (fmt == 10 and width % 2):
        raise UnsupportedEffect("unverified surface row pitch")
    colors = 0 if fmt == 2 else 16 if fmt == 10 else 256
    if bool(npal) != bool(colors):
        raise ValueError("palette count incompatible with surface format")
    palette_bytes = colors * npal * 4
    pixel_bytes = pitch * height
    payload_end = 68 + palette_bytes + pixel_bytes
    footer_bytes = 32
    if payload_end + footer_bytes != len(entry):
        raise ValueError("palette/pixel extent differs from texture length")
    footer = entry[payload_end:]
    if footer[:16] != FOOTER:
        raise ValueError("legacy texture end marker mismatch")
    palettes = tuple(entry[68 + i * colors * 4:68 + (i + 1) * colors * 4] for i in range(npal))
    pixels = entry[68 + palette_bytes:payload_end]
    if fmt == 2:
        rgba = np.frombuffer(pixels, np.uint8).reshape(-1, 4)[:, (2, 1, 0, 3)].tobytes()
        layers, indices = (rgba,), None
    else:
        indices_array = np.frombuffer(pixels, np.uint8)
        if fmt == 10:
            unpacked = np.empty(width * height, np.uint8)
            unpacked[0::2], unpacked[1::2] = indices_array & 15, indices_array >> 4
            indices_array = unpacked
        indices = indices_array.tobytes()
        layers = tuple(np.frombuffer(p, np.uint8).reshape(colors, 4)[:, (2, 1, 0, 3)][indices_array].tobytes()
                       for p in palettes)
    return LegacyTexture(entry[:4], width, height, fmt, palettes, indices, layers,
                         hashlib.sha256(entry).hexdigest(), footer)


def convert_texture(entry: bytes, *, palette_frames: bool = False, extended: bool = False) -> tuple[bytes, dict]:
    """Lossless color conversion for one native palette; never discard variants.

    extended (SPECBULK1): the wider layout rule and attribute byte 2 (the entry's display time in an animated
    material, kept as is)."""
    if type(palette_frames) is not bool:
        raise ValueError("palette_frames must be an explicit bool")
    source = decode_texture(entry)
    if len(source.rgba_layers) != 1:
        if not palette_frames:
            raise UnsupportedEffect(f"{len(source.rgba_layers)} palette variants require verified D5 receiver mapping")
        shape = (source.format, source.width, source.height, len(source.rgba_layers))
        if not palette_layout_ok(shape, extended):
            raise UnsupportedEffect(f"unverified palette-frame layout {shape}")
        if source.attr[:2] != b"\x6c\0" or (source.attr[2] and not extended):
            raise UnsupportedEffect("palette frames require attributes 6c0000; duration/alpha variants remain blocked")
        target, frames = _encode_palette_frames(source)
        return target, {"source_sha256": source.source_sha256,
                        "target_sha256": hashlib.sha256(target).hexdigest(),
                        "width": source.width, "height": source.height,
                        "source_format": source.format, "palettes": len(frames),
                        "frames": frames, "pixel_exact": True, "attrs0_2_exact": True,
                        "source_palette_sha256": [hashlib.sha256(p).hexdigest() for p in source.palettes],
                        "source_indices_sha256": hashlib.sha256(source.indices).hexdigest(),
                        "source_footer_sha256": hashlib.sha256(source.footer).hexdigest(),
                        "storage_change": "2 to 0", "fidelity": "adapted",
                        "resource_ready": False, "rendering": "untested"}
    target = source.attr[:3] + b"\0" + txf.from_image(source.image())
    decoded = obf.Texture(target).to_image().tobytes()
    if decoded != source.rgba_layers[0]:
        raise ValueError("D5 texture pixel verification failed")
    return target, {"source_sha256": source.source_sha256,
                    "target_sha256": hashlib.sha256(target).hexdigest(),
                    "rgba_sha256": hashlib.sha256(decoded).hexdigest(),
                    "width": source.width, "height": source.height,
                    "source_format": source.format, "palettes": len(source.rgba_layers),
                    "pixel_exact": True, "rendering": "untested"}


def _encode_palette_frames(source):
    """Expand all palettes, in order, under one color-TXF payload header."""
    encoded = [txf.from_image(source.image(index)) for index in range(len(source.rgba_layers))]
    frame_bytes = source.width * source.height * 4
    header = b"\0\x01\x01\x01" + struct.pack(">HHII", source.width, source.height, 0x10000, frame_bytes)
    if any(frame[:16] != header or len(frame) != 16 + frame_bytes for frame in encoded):
        raise ValueError("palette TXF frame header/extent verification failed")
    payload = b"".join(frame[16:] for frame in encoded)
    target = source.attr[:3] + b"\0" + header[:12] + struct.pack(">I", len(payload)) + payload
    frames = []
    for index, source_pixels in enumerate(source.rgba_layers):
        offset = 20 + index * frame_bytes
        pixels = target[offset:offset + frame_bytes]
        # Decode separately bounded color frames; the ordinary image reader's
        # layer property does not describe a native multi-surface TXF vector.
        decoded = obf.Texture(target[:4] + header + pixels).to_image().tobytes()
        if decoded != source_pixels:
            raise ValueError(f"palette frame {index} pixel verification failed")
        frames.append({"index": index, "source_palette_index": index,
                       "texture_entry_offset": offset, "length": frame_bytes,
                       "encoded_argb_sha256": hashlib.sha256(pixels).hexdigest(),
                       "rgba_sha256": hashlib.sha256(decoded).hexdigest()})
    return target, frames


def _bounded_table(section, role):
    if len(section) < 4:
        raise UnsupportedEffect(f"{role}: truncated offset table")
    count = struct.unpack_from("<I", section)[0]
    if not count or count > (len(section) - 4) // 4:
        raise UnsupportedEffect(f"{role}: invalid entry count")
    offsets = list(struct.unpack_from(f"<{count}I", section, 4)) + [len(section)]
    if offsets[0] != 4 + 4 * count or any(a >= b for a, b in zip(offsets, offsets[1:])):
        raise UnsupportedEffect(f"{role}: noncanonical or empty entries")
    return [section[a:b] for a, b in zip(offsets, offsets[1:])]


def _static_palette_materials(section, texture_count, extended=False):
    """extended (opt-in, SPECBULK1): also admit 72-byte records (D5's own models have 932) and materials that step
    through texture entries (byte 0x23 = entry count, mode byte 0x22 in 0/2, the encoding D5's own models use
    about 1,500 times). The material bytes are kept; D5 then animates the converted entries, each of which may now
    hold palette frames. That combination is not live-proven."""
    records = _bounded_table(section, "palette-frame materials")
    animated = 0
    for index, record in enumerate(records):
        if len(record) not in ((60, 72) if extended else (60,)):
            raise UnsupportedEffect(f"material {index}: unverified record extent")
        texture = struct.unpack_from("<I", record, 4)[0]
        if texture >= texture_count:
            raise UnsupportedEffect(f"material {index}: texture reference outside table")
        if record[0x22] == 2 and record[0x23] == 0:
            continue
        if not extended or record[0x22] not in (0, 2):
            raise UnsupportedEffect(f"material {index}: texture-entry animation remains blocked")
        if record[0x23] and texture + record[0x23] > texture_count:
            raise UnsupportedEffect(f"material {index}: animated entries run past the texture table")
        animated += 1
    return {"count": len(records), "section_sha256": hashlib.sha256(section).hexdigest(),
            "entry_animation": "preserved (live-unproven with palette frames)" if animated else "disabled",
            "animated_records": animated, "bytes_preserved": True}


def _effect71_texture(model):
    """Convert only the sealed two-palette case; keep scene readiness separate."""
    table = model.sections[9]
    if len(table) < 8 or struct.unpack_from("<II", table) != (1, 8):
        raise UnsupportedEffect("effect71 requires one exact texture-table entry")
    entry = table[8:]
    if entry[:4] != b"\x6c\0\0\x02":
        raise UnsupportedEffect("effect71 requires attributes 6c000002")
    source = decode_texture(entry)
    if (source.format, source.width, source.height, len(source.rgba_layers)) != (14, 128, 128, 2):
        raise UnsupportedEffect("effect71 requires indexed8, two palettes and 128x128 dimensions")
    materials = model.sections[7]
    if len(materials) != 132 or struct.unpack_from("<III", materials) != (2, 12, 72):
        raise UnsupportedEffect("effect71 requires two exact 60-byte mesh/material records")
    for index, offset in enumerate((12, 72)):
        mesh = materials[offset:offset + 60]
        if struct.unpack_from("<I", mesh, 4)[0] != 0 or mesh[0x23] != 0:
            raise UnsupportedEffect(f"effect71 material {index}: unsupported texture reference or entry animation")
    target, frames = _encode_palette_frames(source)
    return target, {"index": 0, "source_sha256": source.source_sha256,
                    "target_sha256": hashlib.sha256(target).hexdigest(),
                    "width": 128, "height": 128, "source_format": 14,
                    "palettes": 2, "frames": frames, "pixel_exact": True,
                    "attrs0_2_exact": True, "storage_change": "2 to 0",
                    "rendering": "untested"}


def convert_obf(data: bytes, *, effect71_two_frames: bool = False,
                palette_frames: bool = False, extended: bool = False) -> tuple[bytes, dict]:
    """Convert section 9 only; preserve geometry, motion and sampler/material bytes.

    extended (needs palette_frames; SPECBULK1 bulk D4 specials): power-of-two palette layouts, 72-byte material
    records, animated texture-entry materials and entry display times. Labelled live-unproven in the report."""
    if type(extended) is not bool or (extended and not palette_frames):
        raise ValueError("extended must be an explicit bool and needs palette_frames")
    if type(effect71_two_frames) is not bool:
        raise ValueError("effect71_two_frames must be an explicit bool")
    if type(palette_frames) is not bool:
        raise ValueError("palette_frames must be an explicit bool")
    if effect71_two_frames and palette_frames:
        raise ValueError("choose the sealed effect71 mode or bounded palette-frame mode")
    if len(data) > LIMIT or len(data) < 48:
        raise ValueError("OBF size outside bounds")
    if effect71_two_frames and hashlib.sha256(data).hexdigest() != EFFECT71_SOURCE_SHA256:
        raise UnsupportedEffect("effect71 opt-in requires the exact reviewed expanded EN source fingerprint")
    total, version = struct.unpack_from("<II", data)
    if version != 2 or not 48 <= total <= len(data):
        raise UnsupportedEffect("expected bounded OBF version 2")
    model = obf.ObfFile(data)
    if any(model.trailer):
        model.pad16 = False  # preserve opaque, non-padding trailer bytes verbatim
    original = list(model.sections)
    if effect71_two_frames:
        target, record = _effect71_texture(model)
        converted, records = [target], [record]
        model.pad16 = False  # Preserve the exact source trailer, including padding.
    else:
        entries = _bounded_table(original[9], "palette-frame textures") if palette_frames else obf.read_table(original[9])
        materials = (_static_palette_materials(original[7], len(entries), extended)
                     if palette_frames else None)
        converted, records = [], []
        converted_bytes = 0
        for index, entry in enumerate(entries):
            try:
                target, record = convert_texture(entry, palette_frames=palette_frames,
                                                 extended=extended)
            except ValueError as exc:
                raise UnsupportedEffect(f"texture {index}: {exc}") from exc
            converted.append(target)
            converted_bytes += len(target)
            if palette_frames and converted_bytes > LIMIT:
                raise UnsupportedEffect("palette-frame output exceeds bounded size")
            records.append({"index": index, **record})
        if palette_frames:
            model.pad16 = False  # Preserve even all-zero opaque trailer bytes exactly.
    model.sections[9] = obf.build_table(converted)
    output = model.to_bytes()
    check = obf.ObfFile(output)
    if check.sections[:9] != original[:9]:
        raise ValueError("conversion changed non-texture sections")
    report = {"schema": "d4-effects-conversion/1", "textures": records,
              "source_sha256": hashlib.sha256(data).hexdigest(),
              "target_sha256": hashlib.sha256(output).hexdigest(),
              "non_texture_sections_exact": True,
              "status": "converted-offline", "rendering": "untested"}
    if effect71_two_frames:
        if check.trailer != model.trailer:
            raise ValueError("effect71 conversion changed the source trailer")
        if len(output) != EFFECT71_TARGET_BYTES or report["target_sha256"] != EFFECT71_TARGET_SHA256:
            raise ValueError("effect71 output differs from the reviewed offline carrier fingerprint")
        report.update(conversion_mode="exact-en-effect71-two-frames", fidelity="adapted",
                      status="partial-offline", resource_ready=False, trailer_exact=True,
                      gameplay="not-tested", presentation="not-tested",
                      remaining_gates=["source event/property mapping", "native binding/upload",
                                       "material/rendering", "scheduler/animation timing",
                                       "ownership/lifetime/cleanup", "normal/short/skip gameplay presentation"])
    elif palette_frames:
        if len(output) > LIMIT or check.trailer != model.trailer:
            raise ValueError("palette-frame output exceeds bounds or changed the source trailer")
        report.update(conversion_mode="extended-palette-frames" if extended else "bounded-static-palette-frames",
                      fidelity="adapted", live_proven=not extended,
                      status="partial-offline", resource_ready=False, trailer_exact=True,
                      materials=materials, gameplay="not-tested", presentation="not-tested",
                      remaining_gates=["source event/property mapping", "native binding/upload",
                                       "material/rendering", "scheduler/animation timing",
                                       "ownership/lifetime/cleanup", "normal/short/skip gameplay presentation"])
    return output, report
