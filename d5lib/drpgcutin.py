"""A Disgaea RPG cut-in made from the character's own illustration (DRPGCUTIN2).

Four RPG looks have no `chara/ci/<id>` file in the source game (Colossal Prinny Blue 60019 / Red 60021, Dark Lord
Valvolga 60025, Halloween Strategist Higan 426); the source does hold each one's `chara/illust/<id>` (640 x 960,
transparent background).  The real cut-ins (`chara/ci/<id>`, 260 x 836, opaque, white background) are NOT crops of
their illustration: they are a separate drawing (another pose and expression), so no window can be registered
(SIFT with a similarity fit registers 4 of 316 pairs; 40005, a mirror prop, registers with 180 inliers and is the one
clean check).  Framing is therefore taken from statistics measured on the real cut-ins and their illustrations
(946 pairs; ids with both files; the numbers are in DRPGCUTIN2-REPORT.md):
    zoom (cut-in px per illustration px)  2.25  where the window gets as full as it gets: over 158 controls the window's
                                                median alpha coverage is 0.754 / 0.798 / 0.836 / 0.851 / 0.854 / 0.865 at zoom
                                                1.5 / 1.75 / 2.0 / 2.25 / 2.5 / 2.75 (the real cut-ins: 0.925 = 1 - the 0.075
                                                median of white connected to the border, so they are at least this tight).
                                                Floor from SIFT keypoint sizes (cut-in / illustration; mode 1.75 over 182
                                                pairs, mismatches pull it down); 40005, registered with 180 inliers: 1.76
    window                                 260/2.25 x 836/2.25 = 116 x 372 illustration px
    top                                    the figure's top (alpha bbox): window top minus figure top = -0.05 H on 40005,
                                           0.02 H at the lower quartile of 95 noisy fits
    horizontal centre                      the median column of the figure's top 40%
    ink                                    every real cut-in is full bleed: 0.895 of the frame non-white (quartiles
                                           0.836 .. 0.938), ink on the top row and both side columns (946 of 946)
The window is scaled to 260 x 836 over white (the real files are opaque, white background; the kit's cut-in path
handles that the same way).
"""
import os

from PIL import Image

SIZE = (260, 836)
ZOOM = 2.25
# a folder name: a cut-in found under it is made from an illustration, not from a source cut-in file
OWN_DIR = "own-cutins"


def is_own(path):
    """True when `path` is a cut-in made from an illustration (lives in a folder named OWN_DIR)"""
    return OWN_DIR in os.path.realpath(str(path)).replace("\\", "/").split("/")


# Per-look override (DRPGCUTIN2 follow-up): look id -> (bundle under assetbundle/images/, centre x, window top, window height)
# in that picture's pixels, window width = height * 260 / 836.  The generic rule above blows the 640x960 illustration up
# 2.25 times (soft) and put Valvolga on his moon; the source's larger skill art of the same character is used instead.
OVERRIDES = {
    "60019": ("no_naming/effect/skill_img/60019_giant_prinny/prinny_illust_a", 460, 154, 836),   # 1024x1024, head: beak + eye
    "60021": ("no_naming/effect/skill_img/60019_giant_prinny/prinny_illust_b", 460, 154, 836),
    "60025": ("no_naming/effect/skill_img/60025valvolga/micky_ci", 690, 210, 760),               # 1500x1024, his face at ~(690, 560)
}


def frame_window(img, cx, top, h):
    """the SIZE-shaped window of `img` (centre column cx, top row `top`, height h), over white, scaled to SIZE"""
    img = img.convert("RGBA")
    w = round(h * SIZE[0] / SIZE[1])
    white = Image.new("RGBA", img.size, (255, 255, 255, 255))
    white.alpha_composite(img)
    return white.crop((round(cx - w / 2), top, round(cx - w / 2) + w, top + h)).resize(SIZE, Image.LANCZOS)


def window(rgba, zoom=ZOOM):
    """(x, y, w, h) of the zoom-sized window of the illustration `rgba`: top at the figure's top (first row at least a quarter as wide as the figure's median row), centred on the
    median column of the figure's top 40%"""
    import numpy as np                  # (lazy: the decode step runs in a venv without numpy)
    m = np.asarray(rgba.convert("RGBA"))[..., 3] > 128          # not the faint glow around a figure (Valvolga)
    H, W = m.shape
    c = m.sum(1)
    rows = np.nonzero(c)[0]
    bottom = int(rows[-1]) + 1
    top = int(np.nonzero(c >= 0.25 * np.median(c[c > 0]))[0][0])        # a thin prop above the head (Valvolga's rod) is not the top
    cx = np.median(np.nonzero(m[top:top + max(8, (bottom - top) * 2 // 5)])[1])
    w, h = round(SIZE[0] / zoom), round(SIZE[1] / zoom)
    return int(round(min(max(cx - w / 2, 0), W - w))), min(top, H - h), w, h


def frame_illustration(img, **kw):
    """an illustration (PIL, RGBA, transparent background) -> the 260 x 836 opaque RGBA cut-in"""
    img = img.convert("RGBA")
    x, y, w, h = window(img, **kw)
    white = Image.new("RGBA", img.size, (255, 255, 255, 255))
    white.alpha_composite(img)
    return white.crop((x, y, x + w, y + h)).resize(SIZE, Image.LANCZOS)
