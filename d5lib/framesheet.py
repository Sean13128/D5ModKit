"""Parse 'frame dump' sprite sheets (e.g. The Spriters Resource style): labelled rows of whole-pose
frames on a solid background colour, each frame in its own transparent cell."""
import numpy as np
from PIL import Image
from scipy import ndimage


def parse_sheet(path, bg=None, min_cell=24):
    """Return (image RGBA array, rows) where rows = [{'label_box': (x0,y0,x1,y1) | None,
    'cells': [(x0,y0,x1,y1), ...]}] in reading order. Boxes are exclusive at x1/y1."""
    im = np.asarray(Image.open(path).convert("RGBA"))
    if bg is None:
        vals, counts = np.unique(im.reshape(-1, 4)[::13], axis=0, return_counts=True)
        bg = tuple(vals[counts.argmax()])
    not_bg = np.any(im != np.array(bg, np.uint8), axis=2)
    lab, n = ndimage.label(not_bg)
    objs = ndimage.find_objects(lab)
    cells, texts = [], []
    for sl in objs:
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        if (x1 - x0) >= min_cell and (y1 - y0) >= min_cell:
            cells.append((x0, y0, x1, y1))
        else:
            texts.append((x0, y0, x1, y1))
    # group cells into rows by top edge
    cells.sort(key=lambda b: (b[1], b[0]))
    rows = []
    for b in cells:
        if rows and abs(rows[-1]["cells"][0][1] - b[1]) <= 2:
            rows[-1]["cells"].append(b)
        else:
            rows.append({"cells": [b]})
    for r in rows:
        r["cells"].sort()
        top = r["cells"][0][1]
        # label = text glyphs in the strip just above the row
        glyphs = [t for t in texts if top - 16 <= t[1] and t[3] <= top]
        r["label_box"] = (min(g[0] for g in glyphs), min(g[1] for g in glyphs),
                          max(g[2] for g in glyphs), max(g[3] for g in glyphs)) if glyphs else None
    return im, rows


def frame_image(im, box):
    x0, y0, x1, y1 = box
    return Image.fromarray(im[y0:y1, x0:x1].copy(), "RGBA")


def label_strip(im, rows, scale=2):
    """Contact image of all row labels (to read them), numbered."""
    from PIL import ImageDraw
    strips = [frame_image(im, r["label_box"]) for r in rows if r["label_box"]]
    w = max(s.width for s in strips) * scale + 60
    h = sum(s.height * scale + 4 for s in strips)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    d = ImageDraw.Draw(out)
    y = 0
    k = 0
    for r in rows:
        if not r["label_box"]:
            continue
        s = frame_image(im, r["label_box"])
        out.paste(s.resize((s.width * scale, s.height * scale), Image.NEAREST), (50, y))
        d.text((2, y), str(k), fill=(255, 255, 0, 255))
        y += s.height * scale + 4
        k += 1
    return out


# ------------------------------------------------------------------------ label recognition
def label_mask(im, box):
    x0, y0, x1, y1 = box
    c = im[y0:y1, x0:x1]
    return (c[:, :, 0] > 200) & (c[:, :, 1] > 200) & (c[:, :, 2] > 200)


def _known_labels():
    import os
    import pickle
    p = os.path.join(os.path.dirname(__file__), "data", "sheet_labels.pickle")
    if not os.path.exists(p):
        return []
    with open(p, "rb") as f:
        return pickle.load(f)


def recognize_label(mask):
    """Best matching known label text for a label mask, or None (exact-font whole-label matching)."""
    best, best_d = None, None
    h, w = mask.shape
    for text, km in _known_labels():
        kh, kw = km.shape
        if abs(kw - w) > 2 or abs(kh - h) > 2:
            continue
        H, W = min(h, kh), min(w, kw)
        d = np.count_nonzero(mask[:H, :W] ^ km[:H, :W]) + abs(kw - w) * H
        if best_d is None or d < best_d:
            best, best_d = text, d
    if best is not None and best_d <= max(6, mask.sum() // 25):
        return best
    return None


def guess_rows(im, rows):
    """[(anim name or '', view 'front'|'back', recognized label text or None)] for every sheet row."""
    from .frameconvert import normalize_name
    out = []
    n = len(rows)
    for k, r in enumerate(rows):
        text = recognize_label(label_mask(im, r["label_box"])) if r["label_box"] else None
        if text:
            view = "back" if "back" in text else "front"
            out.append((normalize_name(text), view, text))
        else:
            out.append(("", "front" if k < n / 2 else "back", None))
    return out
