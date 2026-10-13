"""Hand-painted colour parts for a sprite (the Strategy Assembly's precise colour editor).

The editor changes a sprite's palette by rows of 16 colours: row 1 = "Part 1" ... row 15 = "Part 15" (row 0 is never
offered).  For converted or repainted sprites the kit guesses which pixels belong together; when the guess isn't
good enough the parts can be painted by hand:

  export(...)  writes, for every texture sheet of the sprite (all animation frames are on these sheets):
                 sprite_<t>.png   the sheet as it looks in game
                 parts_<t>.png    the current parts, one legend colour per part (the layer to paint)
               plus legend.png and HOW_TO_PAINT.txt
  import_rows(...) reads the painted parts_<t>.png files back.  Painted pixels keep their part; every other pixel of
               the sprite takes the part its colour was painted with most (so painting a few poses is enough and all
               frames agree), and colours used by several parts follow the nearest painted / decided pixel.
  apply(...)   rebuilds the sprite palette so that part N is exactly editor row N (see colorvariants.repartition_rows).
"""
import os

import numpy as np

from . import anm

# legend colour of every part: index 0 = details (editor row 0: eyes, mouth ... not editable), 1-15 = Part 1-15
LEGEND = [
    (128, 128, 128),   # details (row 0)
    (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255),
    (0, 255, 255), (255, 128, 0), (128, 0, 255), (0, 128, 64), (255, 128, 192),
    (128, 64, 0), (0, 64, 128), (192, 255, 128), (128, 0, 0), (255, 255, 255),
]
LEGEND_NAMES = ["Details (not editable)"] + [f"Part {i}" for i in range(1, 16)]
MATCH = 60.0          # max RGB distance of a painted pixel to its legend colour
DOMINANT = 0.75       # a colour belongs to one part when this share of its painted pixels has that part

HOW_TO = """How to paint the parts of {name}
=========================================

The in-game precise colour editor (Strategy Assembly -> Change More Colors) edits the sprite by parts.
Part N in the editor = the colour for Part N in legend.png.  "Details" pixels (eyes, mouth, tiny marks)
stay as they are and are not offered in the editor.

Files (one pair per texture sheet; every animation frame of the sprite is on these sheets):
  sprite_<n>.png   what the sheet looks like in game (don't edit)
  parts_<n>.png    the parts as the kit sees them now: EDIT THIS ONE

In Paint.NET (or any editor with layers):
  1. Open sprite_0.png.
  2. Layers -> Import from File... -> parts_0.png  (it lands exactly on top; lower its opacity to ~50%
     in Layer Properties while you work so you can see the sprite through it).
  3. Paint with the Pencil tool (no antialiasing!) using the exact legend colours.  Use the Color Picker on
     legend.png, or type the hex values:
{legend}
  4. You don't have to paint every frame: paint a few clear poses (e.g. standing front and back) well.  Pixels
     you leave transparent are decided by the kit: a colour you painted mostly with one part gets that part in
     every frame, other pixels follow their painted neighbours.  Pixels you do paint always win.
  5. Hide the sprite layer, set the parts layer back to 100% opacity, and save ONLY the parts layer over
     parts_0.png (File -> Save As -> PNG, "Flatten" is fine once the sprite layer is hidden or deleted).
  6. Same for parts_1.png, ... if there are more sheets.
  7. In the kit: Outfits -> select the outfit -> "Import painted parts".  Check the part preview, then Install.

Rules of thumb (how the game's own sprites are split):
  - one part per thing a player would recolour: hair, skin, top, bottom, shoes, accessory, weapon ...
  - a part holds at most 16 shades; very detailed parts lose their rarest shades.
  - up to 15 parts.  Parts 1.. appear in this order in the editor list.
"""


def legend_image(scale=28):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (scale * 12, scale * len(LEGEND)), (32, 32, 32))
    d = ImageDraw.Draw(img)
    for i, (c, name) in enumerate(zip(LEGEND, LEGEND_NAMES)):
        d.rectangle([2, i * scale + 2, scale * 2, (i + 1) * scale - 3], fill=c)
        d.text((scale * 2 + 8, i * scale + scale // 3), f"{name}   #{c[0]:02X}{c[1]:02X}{c[2]:02X}", fill=(230, 230, 230))
    return img


def _indexed(sprite):
    return [i for i, t in enumerate(sprite.textures) if t.indexed]


def current_rows(sprite):
    """{texture: editor row of every pixel (-1 transparent)} from the sprite's palette layout."""
    pal = anm.get_palette(sprite, 0)
    out = {}
    for t in _indexed(sprite):
        ind = anm.texture_indices(sprite, t).astype(np.int32)
        rows = ind // 16
        rows[(ind == 0) | (pal[ind, 3] == 0)] = -1
        out[t] = rows
    return out


def rows_image(rows):
    from PIL import Image
    h, w = rows.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    leg = np.array(LEGEND, np.uint8)
    m = rows >= 0
    rgba[m, :3] = leg[rows[m]]
    rgba[m, 3] = 255
    return Image.fromarray(rgba, "RGBA")


def export(sprite, out_dir, name="the sprite", rows=None):
    """Write the sheets, the current parts, the legend and the instructions.  -> list of written files"""
    os.makedirs(out_dir, exist_ok=True)
    rows = rows or current_rows(sprite)
    files = []
    for k, t in enumerate(_indexed(sprite)):
        p = os.path.join(out_dir, f"sprite_{k}.png")
        anm.texture_to_image(sprite, t, 0).save(p)
        files.append(p)
        p = os.path.join(out_dir, f"parts_{k}.png")
        rows_image(rows[t]).save(p)
        files.append(p)
    legend_image().save(os.path.join(out_dir, "legend.png"))
    lines = "\n".join(f"       {n:<24} #{c[0]:02X}{c[1]:02X}{c[2]:02X}" for c, n in zip(LEGEND, LEGEND_NAMES))
    with open(os.path.join(out_dir, "HOW_TO_PAINT.txt"), "w", encoding="utf-8") as f:
        f.write(HOW_TO.format(name=name, legend=lines))
    return files


def read_painted(sprite, folder):
    """{texture: painted row per pixel (-1 = not painted)} from parts_<k>.png; missing files = nothing painted."""
    from PIL import Image
    leg = np.array(LEGEND, np.float64)
    out = {}
    for k, t in enumerate(_indexed(sprite)):
        tex = sprite.textures[t]
        rows = np.full((tex.height, tex.width), -1, np.int32)
        p = os.path.join(folder, f"parts_{k}.png")
        if os.path.exists(p):
            img = np.asarray(Image.open(p).convert("RGBA"))
            if img.shape[:2] != rows.shape:
                raise ValueError(f"{os.path.basename(p)} is {img.shape[1]}x{img.shape[0]}, "
                                 f"the sheet is {tex.width}x{tex.height}")
            rgb = img[..., :3].astype(np.float64)
            d = np.linalg.norm(rgb[..., None, :] - leg[None, None], axis=-1)
            best = np.argmin(d, axis=-1)
            ok = (img[..., 3] >= 128) & (np.min(d, axis=-1) <= MATCH)
            rows[ok] = best[ok]
        out[t] = rows
    return out


def propagate(sprite, painted, fallback=None):
    """Part of every opaque pixel: painted pixels keep theirs, a colour painted mostly (DOMINANT) with one part
    gets it everywhere, the rest follows the nearest decided pixel of the same sheet.
    -> {texture: row per pixel (-1 transparent)}"""
    from scipy import ndimage
    pal = anm.get_palette(sprite, 0)
    texs = _indexed(sprite)
    ind = {t: anm.texture_indices(sprite, t).astype(np.int32) for t in texs}
    opaque = {t: (ind[t] > 0) & (pal[ind[t], 3] > 0) for t in texs}
    votes = np.zeros((256, 16), np.int64)
    for t in texs:
        m = opaque[t] & (painted[t] >= 0)
        np.add.at(votes, (ind[t][m], painted[t][m]), 1)
    tot = votes.sum(1)
    colour_row = np.full(256, -1, np.int32)
    has = tot > 0
    dom = votes.argmax(1)
    share = np.where(has, votes.max(1) / np.maximum(tot, 1), 0)
    colour_row[share >= DOMINANT] = dom[share >= DOMINANT]
    fallback = fallback or current_rows(sprite)
    out = {}
    for t in texs:
        rows = np.where(painted[t] >= 0, painted[t], colour_row[ind[t]])
        rows[~opaque[t]] = -1
        undecided = opaque[t] & (rows < 0)
        decided = opaque[t] & (rows >= 0)
        if undecided.any():
            if decided.any():
                _, (iy, ix) = ndimage.distance_transform_edt(~decided, return_indices=True)
                rows[undecided] = rows[iy[undecided], ix[undecided]]
            else:
                rows[undecided] = fallback[t][undecided]
        out[t] = rows
    return out


def import_rows(sprite, folder):
    """painted parts_<k>.png -> {texture: row per pixel} for colorvariants.repartition_rows"""
    from . import colorvariants
    colorvariants._dedupe(sprite)
    return propagate(sprite, read_painted(sprite, folder))


def preview(sprite, motion_block=None, poses=(1, 7, 1001, 1011, 1021, 1031, 1041, 1101), scale=1.0):
    """Frames of the sprite with every part in its legend colour (to check the parts in all poses)."""
    import pickle
    from PIL import Image
    a = pickle.loads(pickle.dumps(sprite))
    pal = anm.get_palette(a, 0).copy()
    leg = np.array(LEGEND, np.uint8)
    for i in range(1, 256):
        if pal[i, 3]:
            pal[i, :3] = leg[i // 16]
    anm.set_palette(a, 0, pal)
    v = anm.bind_motion_set(anm.AnmFile([motion_block], [], []), 0, a) if motion_block is not None else a
    anims = {x["id"]: x["index"] for x in anm.list_animations(v)}
    tiles = []
    for pid in poses:
        if pid in anims:
            try:
                tiles.append(anm.render_frame(v, anims[pid], frame_index=1, bounds=(-160, -300, 160, 40)))
            except Exception:
                pass
    tiles = [t.convert("RGBA").crop(t.convert("RGBA").getbbox()) for t in tiles if t.convert("RGBA").getbbox()]
    if not tiles:
        return None
    tiles = [t.resize((t.width * 2, t.height * 2), Image.NEAREST) for t in tiles]
    w = sum(t.width + 16 for t in tiles)
    h = max(t.height for t in tiles) + 16
    out = Image.new("RGBA", (w, h), (40, 40, 40, 255))
    x = 8
    for tl in tiles:
        out.alpha_composite(tl, (x, h - 8 - tl.height))
        x += tl.width + 16
    strip = legend_image(14).convert("RGBA")
    out = out.resize((int(out.width * scale), int(out.height * scale)), Image.NEAREST) if scale != 1.0 else out
    full = Image.new("RGBA", (out.width + strip.width + 10, max(out.height, strip.height)), (40, 40, 40, 255))
    full.alpha_composite(out, (0, 0))
    full.alpha_composite(strip, (out.width + 10, 0))
    return full
