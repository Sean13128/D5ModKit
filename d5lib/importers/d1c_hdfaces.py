"""Disgaea 1 Complete HD face portraits (D1CHDFACE1): the ``swf####`` textures in SUBDATA.DAT ``anmdat.fad``.

These are the faces Disgaea 1 Complete itself draws in its menus, in the redrawn D1 Complete art that matches
the HD battle bodies. The older face table in ``start.dat[73]`` (``d1c_source.face``, D1CFACE1) is the
earlier PC-era drawing set; where a family was redesigned for D1 Complete (2080 reaper, 2100 rifle demon,
2150 skull dragon) only this set matches the HD body.

Read-only, from the verified prepared SUBDATA.DAT (``_d1c_source``, SOURCEPREP4-D1C):

  SUBDATA.DAT  PS_FS_V1: magic(8) count(u64), then 64-byte entries name[48] size(u64) offset(u64)
  anmdat.fad   268 face entries, each: name ``swf####\\0``(8) u32 entry size, u32 0, u32 packed size,
               u32 raw size, u16 width, u16 height, u16 colours (256), u16 bits (8), ... ``YKCMP_V1`` at entry + 48
               (type 4, Yukes LZ). Raw = 256 RGBA palette entries (1024 bytes) + width*height 8-bit indices,
               linear rows. All 268 are 256x256, alpha 255 everywhere, white background.

Name rule (decomp ``FUN_7100006af8`` @ 0x7100006af8, Switch v0, ``/Volumes/Data/Decomp/d1c``): the game formats
``swf%04d`` from the character's table row: sprite id (+0x60) + palette (+0x49, or the unit's own palette),
except ids 2300 -> 2300, 2301/2302 -> 2301, 2918 -> 2230 and 3190 -> 3600 (``SPECIAL``).
The PS4 copy (``zz_anmdat.fad``) holds the same 268 names with a different pixel layout; not read here.
"""
from __future__ import annotations

import functools
import re
import struct
from pathlib import Path

FAD_NAME = 'anmdat.fad'
SPECIAL = {2300: 2300, 2301: 2301, 2302: 2301, 2918: 2230, 3190: 3600}
_ENTRY = re.compile(rb'swf(\d{4})\0')


def _fad() -> bytes:
    from d5lib.importers import _d1c_source
    return _d1c_source.fad_member()


@functools.lru_cache(maxsize=1)
def index() -> dict:
    """{face id: (entry offset, width, height)} for every valid ``swf####`` entry in anmdat.fad."""
    raw = _fad()
    out = {}
    for m in _ENTRY.finditer(raw):
        x = m.start()
        if raw[x + 48:x + 56] != b'YKCMP_V1':
            continue                                  # a name reference elsewhere in the FAD, not an entry
        rawsize, w, h, _colours, bits = struct.unpack_from('<I4H', raw, x + 20)
        if bits != 8 or not 0 < w <= 1024 or not 0 < h <= 1024 or rawsize != 1024 + w * h:
            raise ValueError(f'unexpected face texture header for swf{m.group(1).decode()}')
        sid = int(m.group(1))
        if sid in out:
            raise ValueError(f'duplicate face swf{sid:04d}')
        out[sid] = (x, w, h)
    return out


def ids() -> list:
    return sorted(index())


def picture(face_id: int):
    """The face ``swf####`` as an RGBA PIL image, or None when the FAD has no such face."""
    import numpy as np
    from PIL import Image
    from d5lib import ykcmp
    e = index().get(int(face_id))
    if e is None:
        return None
    x, w, h = e
    raw = _fad()
    _typ, total, rawsize = struct.unpack_from('<III', raw, x + 56)
    data = ykcmp.decompress(raw[x + 48:x + 48 + total])
    if len(data) != 1024 + w * h:
        raise ValueError(f'face swf{int(face_id):04d} decoded to {len(data)} bytes')
    pal = np.frombuffer(data[:1024], np.uint8).reshape(256, 4)
    idx = np.frombuffer(data[1024:], np.uint8).reshape(h, w)
    return Image.fromarray(pal[idx], 'RGBA')


def face_id(character_id, colour: int | None = None):
    """The ``swf`` id Disgaea 1 Complete shows for this character table row (None: no such row).

    ``colour`` None: the row's own palette; an int: a class colour slot (sprite + colour)."""
    if character_id is None:
        return None
    cid = int(character_id)
    if cid in SPECIAL:
        return SPECIAL[cid]
    from d5lib.importers import d1c_art
    row = next((c for c in d1c_art.source().characters() if c['id'] == cid), None)
    if row is None:
        return None
    return row['legacy_body'] + (row['palette'] if colour is None else int(colour))
