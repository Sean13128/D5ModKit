"""Small image helpers for mod art."""
import numpy as np
from PIL import Image
from scipy import ndimage


FLAT_DE = 3          # a side / bottom area within this of the background's white, ...
FLAT_SHARE = 0.985   # ... for this share of its pixels, ...
FLAT_MIN = 0.002     # ... and at least this share of the picture, is background (Disgaea RPG cut-ins)


def remove_white_background(img, threshold=232, feather=2, spread=24, bridge=2, upper=None):
    """Make the plain white/light background around a picture transparent.  Only light areas connected
    to the picture's border are removed (white highlights inside the drawing stay); the edge is
    softened and de-whitened so no white fringe remains.  Pictures that already have transparency are
    returned unchanged.  The background is found on the light area shrunk by `bridge` px, so it can't leak
    into white fur / clothes through a gap of a few pixels in the outline (Santa Seraphina's fur ball);
    threshold / spread: how white a background pixel is (Disgaea RPG cut-ins: pure white, 246 / 10).
    upper: only light areas reaching into this top part of the picture are background (Disgaea RPG cut-ins,
    0.25: close-ups cut off at the sides and bottom, where white clothes touch the picture's edge too)."""
    im = img.convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    if (a[:, :, 3] < 250).mean() > 0.01:
        return im
    rgb = a[:, :, :3]
    light = (rgb.min(2) >= threshold) & (rgb.max(2) - rgb.min(2) <= spread)
    # outside the picture counts as light: an area along the edge stays connected to it when shrunk
    core = ndimage.binary_erosion(light, iterations=bridge, border_value=1) if bridge else light
    lab, n = ndimage.label(core)
    border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])) - {0}
    edge_areas = set(border)
    if upper is not None and border:
        top = ndimage.minimum(np.indices(lab.shape)[0], lab, sorted(border))
        border = {k for k, y in zip(sorted(border), np.atleast_1d(top)) if y < upper * lab.shape[0]}
    seeds = np.isin(lab, list(border))
    if upper is not None and seeds.any():
        # areas along the sides / bottom cut off from the top by an arm or the hair: background too when they are
        # the background's own flat white (white clothes there are shaded, and stay)
        ref = np.median(rgb[seeds], axis=0)
        same = (np.abs(rgb - ref).max(2) <= FLAT_DE)
        rest = sorted(edge_areas - border)
        if rest:
            size = ndimage.sum(np.ones_like(lab), lab, rest)
            flat = ndimage.mean(same, lab, rest)
            add = [k for k, n, f in zip(rest, np.atleast_1d(size), np.atleast_1d(flat))
                   if f >= FLAT_SHARE and n >= FLAT_MIN * lab.size]
            if add:
                seeds |= np.isin(lab, add)
    bg = ndimage.binary_dilation(seeds, iterations=bridge + 1) & light if bridge else seeds
    if bridge:                                # the picture's own edge rows / columns the shrinking lost
        edge = np.zeros_like(light)
        edge[:bridge + 1] = edge[-bridge - 1:] = True
        edge[:, :bridge + 1] = edge[:, -bridge - 1:] = True
        bg |= edge & light & ndimage.binary_dilation(seeds, iterations=2 * bridge + 2)
    alpha = np.where(bg, 0.0, 255.0)
    # soft edge: pixels next to the background get alpha from how "white" they are
    near = ndimage.binary_dilation(bg, iterations=feather) & ~bg
    whiteness = (rgb.min(2) - 180.0) / (255.0 - 180.0)
    alpha[near] = np.clip(1.0 - whiteness[near], 0.15, 1.0) * 255.0
    # remove the white that was mixed into those edge pixels
    af = alpha[..., None] / 255.0
    rgb2 = np.where(af > 0, (rgb - (1.0 - af) * 255.0) / np.maximum(af, 1e-3), 0)
    out = np.dstack([np.clip(rgb2, 0, 255), alpha]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")
