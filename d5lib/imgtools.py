"""Small image helpers for mod art."""
import os

import numpy as np
from PIL import Image
from scipy import ndimage


FLAT_DE = 3          # a side area within this of the background's white, ...
FLAT_SHARE = 0.985   # ... for this share of its pixels, ...
FLAT_MIN = 0.002     # ... at least this share of the picture ...
FLAT_MAX = 0.02      # ... and at most this share, not reaching the bottom edge, is background (Disgaea RPG cut-ins:
                     # a strip beside an arm is small; a white dress or bodysuit is bigger, and stays)
DRPG = dict(threshold=246, spread=10, upper=0.25)     # the settings for Disgaea RPG cut-ins (pure white background)


def light_mask(img, threshold=232, spread=24):
    """pixels light enough to be the background"""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    return (rgb.min(2) >= threshold) & (rgb.max(2) - rgb.min(2) <= spread)


def light_areas(img, threshold=232, spread=24, bridge=2):
    """label array of the light areas, as background_mask sees them (shrunk by `bridge` px so a gap of a few pixels
    in an outline doesn't join two areas; the picture's own edge rows count as light) -> (labels, count).  The
    portrait fixer selects whole areas with it."""
    light = light_mask(img, threshold, spread)
    core = ndimage.binary_erosion(light, iterations=bridge, border_value=1) if bridge else light
    lab, n = ndimage.label(core)
    if bridge:                                   # give the shrunk-away rim back to the area next to it
        grown = ndimage.grey_dilation(lab, size=(2 * bridge + 3, 2 * bridge + 3))
        lab = np.where(light & (lab == 0), grown, lab)
    return lab, n


def background_mask(img, threshold=232, spread=24, bridge=2, upper=None, bottom=True):
    """bool array: the plain white/light background around a picture (True = background), or None when the picture
    already has transparency.  Only light areas connected to the picture's border are background (white highlights
    inside the drawing stay).  The background is found on the light area shrunk by `bridge` px, so it can't leak
    into white fur / clothes through a gap of a few pixels in the outline (Santa Seraphina's fur ball);
    threshold / spread: how white a background pixel is (Disgaea RPG cut-ins: pure white, DRPG).
    upper: only light areas reaching into this top part of the picture are background (Disgaea RPG cut-ins, 0.25:
    close-ups cut off at the sides and bottom, where white clothes touch the picture's edge too).
    bottom=False: light areas touching only the bottom edge stay (a face / bust picture: the body reaches the bottom,
    so a white highlight on the clothes there is part of the drawing, not background)."""
    im = img.convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    if (a[:, :, 3] < 250).mean() > 0.01:
        return None
    rgb = a[:, :, :3]
    light = (rgb.min(2) >= threshold) & (rgb.max(2) - rgb.min(2) <= spread)
    # outside the picture counts as light: an area along the edge stays connected to it when shrunk
    core = ndimage.binary_erosion(light, iterations=bridge, border_value=1) if bridge else light
    lab, n = ndimage.label(core)
    border = set(np.unique(np.r_[lab[0], lab[-1] if bottom else [], lab[:, 0], lab[:, -1]]).astype(int)) - {0}
    edge_areas = set(border)
    if upper is not None and border:
        top = ndimage.minimum(np.indices(lab.shape)[0], lab, sorted(border))
        border = {k for k, y in zip(sorted(border), np.atleast_1d(top)) if y < upper * lab.shape[0]}
    seeds = np.isin(lab, list(border))
    if upper is not None and seeds.any():
        # small areas along the sides cut off from the top by an arm or the hair: background too when they are the
        # background's own flat white (white clothes are bigger or reach the bottom edge, and stay)
        ref = np.median(rgb[seeds], axis=0)
        same = (np.abs(rgb - ref).max(2) <= FLAT_DE)
        rest = sorted(edge_areas - border - set(np.unique(lab[-1])))
        if rest:
            size = ndimage.sum(np.ones_like(lab), lab, rest)
            flat = ndimage.mean(same, lab, rest)
            add = [k for k, n_, f in zip(rest, np.atleast_1d(size), np.atleast_1d(flat))
                   if f >= FLAT_SHARE and FLAT_MIN * lab.size <= n_ <= FLAT_MAX * lab.size]
            if add:
                seeds |= np.isin(lab, add)
    bg = ndimage.binary_dilation(seeds, iterations=bridge + 1) & light if bridge else seeds
    if bridge:                                # the picture's own edge rows / columns the shrinking lost
        edge = np.zeros_like(light)
        edge[:bridge + 1] = edge[-bridge - 1:] = True
        edge[:, :bridge + 1] = edge[:, -bridge - 1:] = True
        bg |= edge & light & ndimage.binary_dilation(seeds, iterations=2 * bridge + 2)
    return bg


def apply_background(img, bg, feather=2, soft_from=180.0, min_alpha=0.15):
    """the picture with `bg` (bool array, True = background) transparent: the edge softened and de-whitened so no
    white fringe remains.  feather: how many pixels of edge are softened; soft_from: how light (0-255, darkest
    channel) an edge pixel must be to be partly background; min_alpha: the least opacity an edge pixel keeps.
    Dark-outlined art with wide anti-aliasing (D4 faces) needs feather 4, soft_from 0, min_alpha 0 to leave no halo."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    bg = np.asarray(bg, bool)
    alpha = np.where(bg, 0.0, 255.0)
    # soft edge: pixels next to the background get alpha from how "white" they are
    near = ndimage.binary_dilation(bg, iterations=feather) & ~bg
    whiteness = (rgb.min(2) - soft_from) / (255.0 - soft_from)
    alpha[near] = np.clip(1.0 - whiteness[near], min_alpha, 1.0) * 255.0
    # remove the white that was mixed into those edge pixels
    af = alpha[..., None] / 255.0
    rgb2 = np.where(af > 0, (rgb - (1.0 - af) * 255.0) / np.maximum(af, 1e-3), 0)
    out = np.dstack([np.clip(rgb2, 0, 255), alpha]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def remove_white_background(img, threshold=232, feather=2, spread=24, bridge=2, upper=None, bottom=True,
                            soft_from=180.0, min_alpha=0.15):
    """Make the plain white/light background around a picture transparent (background_mask + apply_background).
    Pictures that already have transparency are returned unchanged."""
    bg = background_mask(img, threshold, spread, bridge, upper, bottom)
    if bg is None:
        return img.convert("RGBA")
    return apply_background(img, bg, feather, soft_from, min_alpha)


def matte_enabled():
    """Is automatic background removal switched on for source screen pictures?  Owner decision 2026-10-27
    (playtest PT1027 S3): no automatic transparency -- imported images keep their white background until a
    human-reviewed pass exists.  The earlier behaviour is an explicit opt-in: D5MODKIT_D4_MATTE=1."""
    return os.environ.get("D5MODKIT_D4_MATTE") == "1"


def screen_picture(img, matte=None):
    """A face / cut-in / portrait picture as RGBA.

    Default (matte None, or the opt-in unset): the picture is kept exactly as it is -- its white background
    stays.  `matte` names the remove_white_background options for an explicit opt-in call, and is only honoured
    when D5MODKIT_D4_MATTE=1, so a caller cannot silently reintroduce the automatic matte.  `matte=False` means
    the same as None (keep)."""
    img = img.convert("RGBA") if hasattr(img, "convert") else img
    if matte in (None, False) or not matte_enabled():
        return img
    return remove_white_background(img, **matte)


# ---------------------------------------------------------------------------------------- cut-in fitting (DD2CUTIN1)
CUTIN_ASPECT_TOLERANCE = 0.02     # D4 cut-ins (390x1248) sit 0.45% from the D5 strip (336x1080): left as a plain resize


def cutin_placement(src_size, tex_size, mode="stretch", tolerance=CUTIN_ASPECT_TOLERANCE):
    """Where a source cut-in goes in a D5 cut-in texture -> dict(mode, scale_x, scale_y, box) with box = (x, y, w, h).

    stretch  the whole texture, each axis scaled on its own (the historical behaviour of every importer).
    contain  one scale for both axes, so the picture keeps its proportions and loses no pixel: when the aspect ratios
             are within `tolerance` the picture fills the texture (D4, D1C and Disgaea RPG cut-ins already have the
             D5 strip's proportions), otherwise it is scaled to fit the texture, centred across and kept at the top,
             and the rest of the texture stays transparent (DD2: 125x544 -> 248x1080 in 336x1080)."""
    (sw, sh), (tw, th) = src_size, tex_size
    if mode == "contain" and abs((sw / sh) / (tw / th) - 1.0) > tolerance:
        s = min(tw / sw, th / sh)
        w, h = min(tw, round(sw * s)), min(th, round(sh * s))
        return dict(mode="contain", scale_x=w / sw, scale_y=h / sh, box=((tw - w) // 2, 0, w, h))
    return dict(mode="stretch" if mode != "contain" else "contain-fill", scale_x=tw / sw, scale_y=th / sh, box=(0, 0, tw, th))


def fit_cutin(img, tex_size, mode="stretch"):
    """An RGBA cut-in placed in a `tex_size` RGBA texture as cutin_placement says -> (RGBA image, placement)."""
    img = img.convert("RGBA")
    place = cutin_placement(img.size, tex_size, mode)
    x, y, w, h = place["box"]
    resized = img.resize((w, h), Image.Resampling.LANCZOS)
    if (w, h) == tuple(tex_size):
        return resized, place
    canvas = Image.new("RGBA", tuple(tex_size), (0, 0, 0, 0))
    canvas.paste(resized, (x, y))
    return canvas, place
