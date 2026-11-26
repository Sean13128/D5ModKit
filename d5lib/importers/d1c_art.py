"""Disgaea 1 Complete authored cut-ins and faces (no game data in this file).

D1C ships real face portraits in start.dat[73] (D1CFACE1, see ``source_face_picture``); the crop
below is the labelled fallback.  It also ships one authored
illustration per character per palette, inside the big animation pack (Switch
``start.dat[98]``, PS4 ``start.dat[96]``): every cut-in is one block holding a 336x1080 ARGB32
picture (the same size as a D5 cut-in) plus a 32x32 white flash card.  D1CCUTIN1 established
the binding rule and verified it on Etna (20 -> 21), Flonne (30 -> 31) and Dark Flonne (30,
palette 2 -> 32).

This module turns that authored art into the two pictures the kit's writers take:

  * cut-in  -> the raw picture, unchanged except ARGB->RGBA, handed to
    ``d5lib.nativeimports.build_entry(cutin_paths=...)`` which replaces the donor cut-in's
    main texture (``_portrait``).  ``features.cutin = "own"``.
  * face    -> a 204x204 head-and-shoulders crop of that same authored picture, handed to
    ``build_entry(face_paths=...)`` -> ``d5lib.newchars.set_face`` ->
    ``d5lib.facepatch.add_faces`` (204x204 picture in the 256 frame cell).  It is *derived from
    authored art*, not an authored face drawing; ``features.face`` is reported as ``"own"`` with
    that qualification recorded in the entry notes.

Binding rule (D1CCUTIN1, re-measured here): ``cut-in block = HD body + 1 + palette`` where
``palette`` is the character table's palette byte (member 43, record +0x49).  Overrides are
listed with their evidence; every character is additionally colour-checked against its own
body block's palette banks, and a character whose check fails keeps the derived pictures and is
reported as "no verified authored art" instead of being given someone else's illustration.
"""
from __future__ import annotations

import functools
import json
import shutil
from pathlib import Path

from . import _d1c_source

# SOURCEPREP4-D1C: an installed pack is never read here unless the caller hands one in (the explicit
# --installed-reference fallback of CORED1CC); the default build reads only the verified source.

CUTIN_SIZE = (336, 1080)
FACE_SIZE = 204

# Dark Flonne's character record has palette byte 0 yet her authored cut-in is block 32, one block
# past Flonne's (D1CCUTIN1, pixel evidence: red eyes / red bow vs Flonne's blue ribbon; the two
# pictures' raw ARGB sha256 differ).  The value here is the palette *in the block formula*
# (body + 1 + palette), so 1 gives 32 for body 30 -- CORED1CB corrected the earlier 2, which aimed
# at 33 and has no picture.  How the game picks 32 is not traced; the art evidence is the basis.
PALETTE_OVERRIDES = {3060: 1}

# Face crop: the authored picture is a 336x1080 bust (a D5 cut-in's own size), so a face crop is a
# square of at most the picture width.  CORED1C used a fixed square at 35% of the height, which was
# measured on one template and cut the eyes off pictures whose face sits higher (and showed a body
# part on most monsters).  CORED1CB replaces it with a per-picture box: the reviewed table in
# `d1c-faces-crop.json` beside this module, else the local-detail head estimate.
FACE_SIZE = 204
HEAD_SIDE = 336


def crop_table():
    """{block id: [x0, y0, x1, y1]} from the reviewed per-picture table (empty when absent).

    The table ships with the importer (``d1c-faces-crop.json`` beside this file) so a rebuild from a
    fresh checkout frames the same faces.
    """
    out = {}
    for key, value in (_crop_doc().get('boxes') or {}).items():
        box = (value or {}).get('box') if isinstance(value, dict) else value
        if box and len(box) == 4:
            out[str(int(key))] = [int(v) for v in box]
    return out


def _crop_doc():
    try:
        return json.loads((Path(__file__).resolve().parent / 'd1c-faces-crop.json').read_text())
    except (OSError, ValueError):
        return {}


def crop_entry(block):
    """The table row for a picture: {'box': [...], 'fit': bool, 'how': str} (None when absent)."""
    if block is None:
        return None
    row = (_crop_doc().get('boxes') or {}).get(str(int(block)))
    return row if isinstance(row, dict) else None


def fallback_blocks():
    """Pictures whose cut-in cannot be framed into a face: the importer keeps the installed face.

    CORED1CC: the acceptance rule is both eyes (or the eye area of a masked character) and the
    mouth/jaw inside the frame with the head 50-85% of the cell.  A picture that cannot satisfy it
    (the crop would cut through the eyes, or the head is a giant close-up with no whole head in the
    picture) is never shipped as a bad crop -- the pack keeps the face the installed copy carries.
    """
    doc = _crop_doc()
    return {str(int(k)) for k in (doc.get('fallback') or [])}



def detail_peak(picture):
    """(y of the densest detail window, its mean detail) -- the head in a bust illustration.

    A face is the most detailed region of a cut-in: eyes, mouth and hair edges all put gradient
    magnitude there, while the background and flat clothing do not.  The window is face-sized and
    square, and is searched over the upper 80% of the picture.
    """
    import numpy as np
    from PIL import Image, ImageFilter
    grey = np.asarray(picture.convert('L'), dtype=np.float32)
    gy, gx = np.gradient(grey)
    mag = np.hypot(gx, gy)
    smooth = np.asarray(Image.fromarray(np.clip(mag, 0, 255).astype(np.uint8))
                        .filter(ImageFilter.BoxBlur(14)), dtype=np.float32)
    height, width = smooth.shape
    side = min(HEAD_SIDE, width)
    smooth[: int(height * 0.05)] = 0
    smooth[int(height * 0.80):] = 0
    integral = np.pad(smooth.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best, best_y = -1.0, 0
    for y in range(0, height - side + 1, 6):
        total = integral[y + side, side] - integral[y, side]
        if total > best:
            best, best_y = total, y
    return best_y, float(best / (side * side))


def source():
    """The D1C source reader (``_d1c_source``, over the verified prepared SUBDATA.DAT)."""
    return _d1c_source


def cutin_block(body: int, palette: int = 0, character_id: int | None = None) -> int:
    """The pack block holding this character's authored cut-in (D1CCUTIN1 rule + overrides)."""
    if character_id is not None and int(character_id) in PALETTE_OVERRIDES:
        palette = PALETTE_OVERRIDES[int(character_id)]
    return int(body) + 1 + int(palette or 0)


def blocks():
    """{block id: block} of the source pack (parsed once)."""
    src = source()
    return {b.id: b for b in src.pack().blocks}


@functools.lru_cache(maxsize=1)
def _cutin_ids():
    src = source()
    a = src.pack()
    out = {}
    for b in a.blocks:
        for k in range(len(b.texture_infos)):
            t = a.textures[b.tex_base + k]
            if (t.width, t.height) == CUTIN_SIZE:
                out[b.id] = b.tex_base + k
                break
    return out


def resolve_block(body: int, palette: int = 0, character_id: int | None = None):
    """(block, fallback) whose authored picture to use: the formula's block, else the body's first.

    The character table's palette byte does not always name the palette the cut-in was drawn in:
    Jn:Revamp's row says 1 while its authored picture is the body's first block (CORED1CB measured
    body 50 -> picture at 51, nothing at 52).  The fallback is recorded, never silent.
    """
    block = cutin_block(body, palette, character_id)
    if has_cutin(block):
        return block, False
    first = int(body) + 1
    if first != block and has_cutin(first):
        return first, True
    return block, False


# D1CFACE1: Switch start.dat[73] holds the real face portraits (256x256 RGBA, white background),
# identified by sprite id (``d1c_source.face_ids``): HD body + palette, e.g. 1011..1015, 2611..2615.
# A character's face is the one whose id is its table record's ``legacy_body + palette``; a class colour
# c is ``body + c``.  Held back (kept on the derived cut-in crop, labelled): see SOURCE_FACE_HOLD.
# 2410 Sardia, 3150 Serra Winguard, 3050 Antoire: the id lookup (sprite + palette 3 / 5 / 1) lands on a face whose
# hair colour differs from the unique's own sprite palette (green / grey / olive vs mauve / red / orange); whether the
# game uses that id for a unique is untraced, so the colour-true crop stays until it is.
SOURCE_FACE_HOLD = {
    3060: "sprite 3 palette 0 is Flonne's face; Dark Flonne's cut-in is a different drawing",
    2410: "id 1083 face is mauve-haired; Sardia's sprite palette 3 is green-haired (lookup for uniques untraced)",
    3150: "id 1135 face is red-haired; Serra Winguard's sprite palette 5 is grey-haired (lookup for uniques untraced)",
    3050: "id 2161 face is orange-haired; Antoire's sprite palette 1 is olive-haired (lookup for uniques untraced)",
}


def source_face_id(character_id, colour: int | None = None):
    """Sprite id whose member-73 face this character shows (None: no row / held back)."""
    if character_id is None or int(character_id) in SOURCE_FACE_HOLD:
        return None
    row = next((c for c in source().characters() if c['id'] == int(character_id)), None)
    if row is None:
        return None
    return row['legacy_body'] + (row['palette'] if colour is None else int(colour))


def opaque_face(picture, size: int = FACE_SIZE):
    """size x size RGB face: the source portrait on its own white background, resized (D1CFACE1B).

    This is the face the installed D1C packs carry; the default until hand-made cut-outs land (REPROFIX1).
    """
    from PIL import Image
    rgba = picture.convert('RGBA')
    bg = Image.new('RGB', rgba.size, (255, 255, 255))
    bg.paste(rgba, mask=rgba.split()[3])
    return bg.resize((size, size), Image.LANCZOS)


def source_face_picture(character_id, colour: int | None = None, size: int = FACE_SIZE, cutout: bool = False):
    """(sprite id, size x size face) from member 73, or (None, None) when the source has none.

    ``cutout`` False (default): the installed opaque RGB face (``opaque_face``); True: the FACEFIX1
    flood-fill RGBA cut-out (``cut_out_face``, opt-in with ``--d1c-face-cutout``).

    ``colour`` None: a unique (the record's own palette); an int: a class colour slot.
    """
    sid = source_face_id(character_id, colour)
    if sid is None:
        return None, None
    _, picture = source().face_by_sprite(sid)
    if picture is None:
        return sid, None
    return sid, (cut_out_face(picture, size)[0] if cutout else opaque_face(picture, size))


def hd_face_picture(character_id, colour: int | None = None, size: int = FACE_SIZE, cutout: bool = False):
    """(swf id, size x size face) from Disgaea 1 Complete's own HD face set (``d1c_hdfaces``, anmdat.fad), or
    (id, None) when the set has no face for that id, (None, None) when there is no table row (D1CHDFACE1).

    The game's own key (decomp FUN_7100006af8): table row sprite + palette, or ``colour`` for a class slot.
    The source is a full head-and-shoulders frame on white, so it is only resized (RGB on white, the
    D1CFACE1B shape); ``cutout`` applies the FACEFIX1 flood fill instead (RGBA)."""
    from d5lib.importers import d1c_hdfaces
    fid = d1c_hdfaces.face_id(character_id, colour)
    if fid is None:
        return None, None
    picture = d1c_hdfaces.picture(fid)
    if picture is None:
        return fid, None
    return fid, (cut_out_face(picture, size)[0] if cutout else opaque_face(picture, size))


def cut_out_face(picture, size: int = FACE_SIZE, white: int = 248):
    """(size x size RGBA face, stats) from a source portrait (FACEFIX1).

    The source portrait is opaque white around the subject (alpha is 255 except a few corner pixels), so
    the background is the near-white region *connected to the image border* (flood fill: white clothing,
    eyes, Golem's body and Prinny bellies inside an outline are kept), eroded one pixel and feathered so no
    white halo remains.  The result is cropped to the subject's box (4% margin) and centred in a square
    frame, which is how the other importers' faces fill their frame.  stats: scale (output px per source
    px), bg (fraction removed), inner_white (near-white fraction of the kept subject), bbox.
    """
    import numpy as np
    from PIL import Image, ImageFilter
    rgba = picture.convert('RGBA')
    a = np.array(rgba)
    near = ((a[..., :3] >= white).all(-1) | (a[..., 3] < 128))
    h, w = near.shape
    bg = np.zeros_like(near)
    todo = [(y, x) for y in range(h) for x in range(w) if (y in (0, h - 1) or x in (0, w - 1)) and near[y, x]]
    for y, x in todo:
        bg[y, x] = True
    while todo:                                    # flood fill from the border, 4-connected
        y, x = todo.pop()
        for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= yy < h and 0 <= xx < w and near[yy, xx] and not bg[yy, xx]:
                bg[yy, xx] = True
                todo.append((yy, xx))
    soft = Image.fromarray((bg * 255).astype('uint8')).filter(ImageFilter.MaxFilter(3)).filter(
        ImageFilter.GaussianBlur(0.7))
    a[..., 3] = (255 - np.array(soft)).astype('uint8') * (a[..., 3] > 0)
    # Stray fragments (Ghoss/Spirit: pieces of a neighbouring atlas cell at the edge) are dropped: keep only
    # connected pieces of at least 10% of the biggest one.
    solid = a[..., 3] > 8
    label = np.zeros(solid.shape, int)
    sizes = []
    for sy, sx in zip(*np.where(solid)):
        if label[sy, sx]:
            continue
        sizes.append(0)
        label[sy, sx] = len(sizes)
        todo = [(sy, sx)]
        while todo:
            y, x = todo.pop()
            sizes[-1] += 1
            for yy in range(max(y - 1, 0), min(y + 2, h)):
                for xx in range(max(x - 1, 0), min(x + 2, w)):
                    if solid[yy, xx] and not label[yy, xx]:
                        label[yy, xx] = len(sizes)
                        todo.append((yy, xx))
    if sizes:
        big = max(sizes)
        drop = [i + 1 for i, n in enumerate(sizes) if n < 0.1 * big]
        a[np.isin(label, drop), 3] = 0
    else:
        drop = []
    ys, xs = np.where(a[..., 3] > 8)
    if not len(xs):
        raise ValueError('face has no subject after background removal')
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    side = int(round(max(x1 - x0, y1 - y0) * 1.04))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    box = (int(round(cx - side / 2)), int(round(cy - side / 2)))
    img = Image.fromarray(a).crop(box + (box[0] + side, box[1] + side))   # outside the source: transparent
    keep = a[..., 3] > 128
    stats = dict(scale=round(size / side, 3), bg=round(float(bg.mean()), 3),
                 dropped=len(drop), inner_white=round(float((near & keep).sum() / max(keep.sum(), 1)), 3),
                 bbox=[int(x0), int(y0), int(x1), int(y1)])
    return img.resize((size, size), Image.LANCZOS), stats


def has_cutin(block: int) -> bool:
    return int(block) in _cutin_ids()


def cutin_picture(block: int):
    """The authored 336x1080 picture of ``block`` as an RGBA PIL image (ARGB->RGBA only)."""
    from d5lib import anm
    idx = _cutin_ids().get(int(block))
    if idx is None:
        raise KeyError(f'block {block} is not a D1C cut-in block')
    src = source()
    return anm.texture_to_image(src.pack(), idx).convert('RGBA')


def face_picture(picture, size: int = FACE_SIZE, block: int | None = None, use_table: bool = False):
    """A 204x204 head crop of an authored cut-in picture.

    CORED1CB: the fixed square of half the picture height at 35% (CORED1C) framed too high for many
    pictures -- eyes above the crop or chin below it, and monsters' faces are elsewhere -- so the box
    now comes from the reviewed per-picture table (``faces-crop.json``) when the picture has one,
    and otherwise from the local-detail head estimate below.  The square is at most the picture
    width (336), which is what a bust illustration allows.

    CORED1CC: a table row may carry ``"fit": true`` for a box that is not square (a head taller
    than the picture is wide, or a whole bust).  That crop is fitted into the cell at its own
    aspect ratio and padded with the crop's own background colour, instead of being squashed into
    the square -- the earlier resize stretched every tall box vertically by 20-50%.
    """
    from PIL import Image
    row = crop_entry(block) if use_table else None
    box = list(row['box']) if row and row.get('box') else None
    fit = bool(row and row.get('fit'))
    if box is None:
        top, _ = detail_peak(picture)
        y0 = max(0, min(picture.size[1] - HEAD_SIDE, int(round(top + 0.04 * HEAD_SIDE))))
        box = [0, y0, HEAD_SIDE, y0 + HEAD_SIDE]
        fit = False
    image = picture.crop(tuple(box))
    if not fit:
        return image.resize((size, size), Image.LANCZOS)
    return _fit_square(image, size)


def _fit_square(image, size):
    """Fit ``image`` into a size x size cell at its own aspect ratio, padded with its background."""
    import numpy as np
    from PIL import Image
    width, height = image.size
    border = np.concatenate([np.asarray(image)[0], np.asarray(image)[-1],
                             np.asarray(image)[:, 0], np.asarray(image)[:, -1]])
    bg = tuple(int(v) for v in np.median(border[:, :3], axis=0))
    scale = min(size / width, size / height)
    nw, nh = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    cell = Image.new('RGB', (size, size), bg)
    cell.paste(image.convert('RGB').resize((nw, nh), Image.LANCZOS),
               ((size - nw) // 2, (size - nh) // 2))
    return cell



def palette_identity(block: int, body: int) -> dict:
    """Colour evidence that cut-in ``block`` is drawn for ``body``'s palette of the same character.

    Compares the cut-in's colours with each of the body block's authored palette banks (the 256
    RGB vectors the game swaps to draw that character in another colour).  Returns the assigned
    palette, the best-matching one, the shared-share score of each, and whether the assignment is
    the best match.  A body with a single palette cannot discriminate and reports ``single``.
    """
    import numpy as np
    from d5lib import anm
    src = source()
    a = src.pack()
    body_block = next((b for b in a.blocks if b.id == int(body)), None)
    if body_block is None:
        return dict(assigned=None, best=None, scores={}, ok=False, why='body block missing')
    picture = np.asarray(cutin_picture(block).convert('RGB')).reshape(-1, 3)
    # 6-bit-per-channel colour key set of the authored picture: ignores dithering and shading noise
    keys = {(int(r) >> 2, int(g) >> 2, int(b) >> 2) for r, g, b in picture[::11]}
    banks = [anm.get_palette(a, i) for i in range(body_block.pal_base,
                                                  body_block.pal_base + len(body_block.palette_infos))]
    if len(banks) < 2:
        return dict(assigned=0, best=0, scores={0: None}, ok=True, why='single palette')
    scores = {}
    for i, bank in enumerate(banks):
        rgb = np.asarray(bank)[:, :3].astype(int)
        have = {(int(r) >> 2, int(g) >> 2, int(b) >> 2) for r, g, b in rgb if (r or g or b)}
        scores[i] = round(len(have & keys) / max(1, len(have)), 3)
    return dict(assigned=None, best=max(scores, key=scores.get), scores=scores, ok=True,
                why='palette banks compared')


def install_authored(mod_folder, *, kind: str, target: int, physical: int, body: int,
                     palette: int = 0, palettes: int = 1, character_id: int | None = None,
                     log=None, face_cutout: bool = False, face_source: str = 'member73',
                     installed_pack=None) -> dict:
    """Replace a built pack's derived face / cut-in with the authored ones, in place.

    ``kind`` is ``'unique'`` (one rank: art keyed to the leased ``physical`` row) or ``'class'``
    (a registry family: ``target`` is the family and colours 0..9 are the ten palette slots).
    Writes the same files the kit's own writers do -- ``newchars.set_face`` / ``newclasses.set_face``
    for the 204x204 picture, and ``nativeimports._portrait``'s texture replacement for the cut-in
    anm -- so nothing about the mod's shape changes, only which picture it carries.
    Returns what was written and what fell back to the derived art.

    ``face_source`` ``'hd'`` (D1CHDFACE1): faces from Disgaea 1 Complete's own HD face set
    (``hd_face_picture``, no hold list: it has the colour-true face for every row); a class also gets the
    same picture under ``patches/classes`` (``newclasses.face_path``, the file the game reads for class
    faces, D1CFACE2 live).  ``'member73'``: the start.dat[73] faces (D1CFACE1).
    """
    import numpy as np
    from PIL import Image
    from d5lib import anm

    mod_folder = Path(mod_folder)
    anime = mod_folder / 'files/Anime/ANM_HI_JP.dat'
    faces_dir = mod_folder / 'patches/characters'
    written = dict(face=[], cutin=[], skipped=[], fallback=[])

    def face_ok(colour: int) -> bool:
        if kind == 'class':
            fname = f'face_{int(target)}.png' if not colour else f'face_{int(target)}_{int(colour)}.png'
        else:
            fname = f'face_{int(physical)}.png'
        pick = hd_face_picture if face_source == 'hd' else source_face_picture
        sid, source_image = pick(character_id, colour if kind == 'class' else None, cutout=face_cutout)
        if source_image is not None:
            faces_dir.mkdir(parents=True, exist_ok=True)
            source_image.save(faces_dir / fname)
            written['face'].append(fname)
            written.setdefault('source_face', {})[fname] = (f'swf{sid:04d}' if face_source == 'hd' else sid)
            if face_source == 'hd' and kind == 'class':
                classes_dir = mod_folder / 'patches/classes'
                classes_dir.mkdir(parents=True, exist_ok=True)
                source_image.save(classes_dir / fname)
                written['face'].append(f'classes/{fname}')
            return True
        written['skipped'].append(dict(kind='face', colour=colour, why=(
            f'no source face for sprite id {sid}' if sid else 'held back (SOURCE_FACE_HOLD)') +
            '; derived cut-in crop kept'))
        block, fell_back = resolve_block(body, min(colour, max(0, palettes - 1)), character_id)
        if fell_back:
            written['skipped'].append(dict(kind='face', colour=colour,
                                           why=f'table palette has no picture; used block {block}'))
        if not has_cutin(block):
            written['skipped'].append(dict(kind='face', colour=colour, why=f'no cut-in block {block}'))
            return False
        if kind == 'class':
            name = f'face_{int(target)}.png' if not colour else f'face_{int(target)}_{int(colour)}.png'
        else:
            name = f'face_{int(physical)}.png'
        if str(int(block)) in fallback_blocks():
            # CORED1CC: no crop of this picture meets the face rule -> keep the installed picture.
            source = (Path(installed_pack) / 'patches/characters' / name) if installed_pack else None
            if source is None or not source.is_file():
                written['skipped'].append(dict(kind='face', colour=colour,
                                               why=f'fallback picture {block}: no installed reference pack '
                                                   f'(--installed-reference) carrying {name}'))
                return False
            faces_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, faces_dir / name)
            written['fallback'].append(name)
            return True
        picture = cutin_picture(block)
        image = face_picture(picture, block=block, use_table=True)
        faces_dir.mkdir(parents=True, exist_ok=True)
        image.save(faces_dir / name)
        written['face'].append(name)
        return True

    def cutin_ok(colour: int, number: int) -> bool:
        path = anime / f'anm{number:05d}.lzs'
        if not path.is_file():
            written['skipped'].append(dict(kind='cutin', colour=colour, why='the build wrote no such anm'))
            return False
        block, fell_back = resolve_block(body, min(colour, max(0, palettes - 1)), character_id)
        if fell_back:
            written['skipped'].append(dict(kind='cutin', colour=colour,
                                           why=f'table palette has no picture; used block {block}'))
        if not has_cutin(block):
            written['skipped'].append(dict(kind='cutin', colour=colour, why=f'no cut-in block {block}'))
            return False
        picture = cutin_picture(block)
        a = anm.parse(path.read_bytes())
        texture = a.textures[0]
        if texture.indexed:
            raise ValueError('authored D1C cut-in needs an RGBA receiver texture')
        texture.data = anm._rgba_to_argb(np.asarray(
            picture.resize((texture.width, texture.height), Image.LANCZOS))).tobytes()
        for other in a.textures[1:]:                 # the same clear _portrait() makes
            other.data = bytes(len(other.data))
        path.write_bytes(a.to_bytes())
        written['cutin'].append(path.name)
        return True

    if kind == 'class':
        # Faces are keyed to the class family (newclasses.set_face(family)); the ten cut-in
        # portraits are keyed to the class's *physical* sprite row (nativeimports._portrait ->
        # newclasses.set_portraits(fs, mod, physical, ...)), which is what the batch writes.
        for colour in range(max(1, min(palettes, 10))):
            face_ok(colour)
            cutin_ok(colour, 10000 + int(physical) + colour)
    else:
        face_ok(int(palette or 0))
        cutin_ok(int(palette or 0), 10000 + int(physical))
    if log:
        log(f"  authored art: faces {len(written['face'])}, cut-ins {len(written['cutin'])}, "
            f"skipped {len(written['skipped'])}")
    return written


def resolve(character_id: int, body: int, palette: int = 0) -> dict:
    """Everything the importer needs to know about one character's authored art.

    Returns {block, picture, face, identity, authored, why}.  ``authored`` is False when the pack
    has no cut-in at the computed block, so the caller keeps the derived pictures and reports it.
    """
    block = cutin_block(body, palette, character_id)
    if not has_cutin(block):
        return dict(block=block, authored=False, why=f'no cut-in block {block} in the pack')
    picture = cutin_picture(block)
    ident = palette_identity(block, body)
    assigned = PALETTE_OVERRIDES.get(int(character_id), int(palette or 0))
    ident['assigned'] = assigned
    ident['override'] = int(character_id) in PALETTE_OVERRIDES
    # A body with several palettes must agree with the assigned one; a body with one cannot.
    ok = ident.get('best') in (None, assigned) or ident.get('best') == assigned
    return dict(block=block, picture=picture, face=face_picture(picture), identity=ident,
                authored=bool(ok), why=('assigned palette is the best colour match'
                                        if ok else
                                        f'palette {ident.get("best")} matches better than {assigned}'))
