"""Status / cut-in portraits (anm 10000 + id: one 336 x 1080 ARGB picture) and their background.

A portrait is made from a picture with a plain white background (a Disgaea RPG cut-in, or the user's own), whose
background is made transparent (imgtools.background_mask) and which is then fitted to the texture.  Telling the white
background from white clothes is a guess; the portrait fixer (d5gui/portraitfix.py) lets the user mark what is
background, starting from that guess, and builds the portrait again from the original picture.

Kept in the mod, next to the portrait:
    patches/characters/portrait_<anm>.json   {"source": "<file name>" or "drpg:<Disgaea RPG cut-in>", "fit": "cover"}
    patches/characters/portrait_<anm>.png    the user's own original picture (Disgaea RPG cut-ins are found again)
    patches/characters/portrait_mask_<anm>.png   the background the user marked (white = transparent), source size
"""
import json
import os

import numpy as np
from PIL import Image

from . import anm, imgtools

THUMB = (20, 64)                                    # cut-in thumbnails for finding a portrait's source


def _dir(mod):
    return os.path.join(mod.patches_dir, "characters")


def _vp(anm_id):
    return f"Anime/ANM_HI_JP.dat/anm{int(anm_id):05d}.lzs"


def info_path(mod, anm_id):
    return os.path.join(_dir(mod), f"portrait_{int(anm_id)}.json")


def mask_path(mod, anm_id):
    return os.path.join(_dir(mod), f"portrait_mask_{int(anm_id)}.png")


def load_info(mod, anm_id):
    try:
        with open(info_path(mod, anm_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def remember_source(mod, anm_id, image, fit="cover"):
    """note where portrait anm_id came from: a Disgaea RPG cut-in by name, anything else copied into the mod"""
    os.makedirs(_dir(mod), exist_ok=True)
    src = None
    if isinstance(image, str) and os.path.exists(image):
        p = os.path.normpath(image)
        parts = p.replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[-2] in ("Cut-Ins", "Cutins"):
            src = "drpg:" + parts[-1]
    if src is None:
        img = Image.open(image) if isinstance(image, str) else image
        name = f"portrait_{int(anm_id)}.png"
        img.convert("RGBA").save(os.path.join(_dir(mod), name))
        src = name
    with open(info_path(mod, anm_id), "w", encoding="utf-8") as f:
        json.dump({"source": src, "fit": fit}, f, indent=1)
    try:
        os.remove(mask_path(mod, anm_id))                 # a new picture: the old marks don't fit it
    except OSError:
        pass


def _drpg_cutins(roots=None):
    from . import drpg
    out = {}
    for root in roots or drpg.ROOTS:
        for sub in (("Characters", "Cut-Ins"), ("Cutins",)):
            d = os.path.join(root, *sub)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.lower().endswith(".png") and f not in out:
                        out[f] = os.path.join(d, f)
    return out


def source_path(mod, anm_id, roots=None):
    """the original picture of portrait anm_id when it is known (remember_source), else None"""
    info = load_info(mod, anm_id)
    s = info.get("source")
    if not s:
        return None
    if s.startswith("drpg:"):
        return _drpg_cutins(roots).get(s[5:])
    p = os.path.join(_dir(mod), s)
    return p if os.path.exists(p) else None


def _thumbs(cache_dir, roots=None):
    """(names, paths, thumbs N x 64 x 20 x 3) of every Disgaea RPG cut-in, cached"""
    files = _drpg_cutins(roots)
    names = sorted(files)
    path = os.path.join(cache_dir, "drpg_cutin_thumbs.npz")
    try:
        z = np.load(path, allow_pickle=False)
        if list(z["names"]) == names:
            return names, [files[n] for n in names], z["thumbs"]
    except (OSError, ValueError, KeyError):
        pass
    th = np.zeros((len(names), THUMB[1], THUMB[0], 3), np.uint8)
    for i, n in enumerate(names):
        try:
            th[i] = np.asarray(Image.open(files[n]).convert("RGB").resize(THUMB, Image.BILINEAR))
        except OSError:
            pass
    os.makedirs(cache_dir, exist_ok=True)
    np.savez_compressed(path, names=np.array(names), thumbs=th)
    return names, [files[n] for n in names], th


def find_drpg_source(portrait, cache_dir, roots=None, limit=14.0):
    """the Disgaea RPG cut-in a portrait (RGBA picture) was made from: the closest one over its drawn pixels ->
    path, or None when none is close"""
    names, paths, th = _thumbs(cache_dir, roots)
    if not len(names):
        return None
    p = np.asarray(portrait.convert("RGBA").resize(THUMB, Image.BILINEAR)).astype(np.float32)
    drawn = p[:, :, 3] > 250
    if drawn.sum() < 50:
        return None
    d = np.abs(th[:, drawn, :].astype(np.float32) - p[drawn, :3][None]).mean(axis=(1, 2))
    i = int(np.argmin(d))
    return paths[i] if d[i] <= limit else None


def load_portrait(mod, anm_id):
    """(AnmFile, RGBA picture) of the mod's portrait anm_id"""
    a = anm.load(mod.read_file(_vp(anm_id)))
    return a, anm.texture_to_image(a, 0).convert("RGBA")


def _cover(size, tex_size):
    """scale and left crop of fit_portrait for a picture of `size` on a texture of `tex_size`"""
    s = max(tex_size[0] / size[0], tex_size[1] / size[1])
    w = max(tex_size[0], round(size[0] * s))
    return s, (w - tex_size[0]) // 2


def is_drpg_cutin(src):
    """a Disgaea RPG cut-in (260 x 836: a close-up on pure white, cut off at the sides and bottom)"""
    if src.size == (260, 836):
        return True
    rgb = np.asarray(src.convert("RGB"))
    return abs(src.size[0] / src.size[1] - 260 / 836) < 0.01 and (rgb[0].min(1) >= 246).mean() > 0.6


def auto_mask(src):
    """the background as the kit guesses it (with the Disgaea RPG settings for their cut-ins)"""
    m = imgtools.background_mask(src, **imgtools.DRPG) if is_drpg_cutin(src) else imgtools.background_mask(src)
    return np.zeros(src.size[::-1], bool) if m is None else m


def current_mask(mod, anm_id, src, portrait=None, fit="cover"):
    """the background of the portrait as it is now, in the source picture's pixels: the user's marks when there are
    any, else read back from the portrait's transparency"""
    p = mask_path(mod, anm_id)
    if os.path.exists(p):
        m = np.asarray(Image.open(p).convert("L").resize(src.size, Image.NEAREST)) >= 128
        return m
    if portrait is None:
        portrait = load_portrait(mod, anm_id)[1]
    al = np.asarray(portrait)[:, :, 3]
    tw, th = portrait.size
    if fit == "cover":
        s, x0 = _cover(src.size, (tw, th))
        W, H = max(tw, round(src.size[0] * s)), max(th, round(src.size[1] * s))
        canvas = np.full((H, W), 255, np.uint8)
        canvas[:th, x0:x0 + tw] = al
        back = np.asarray(Image.fromarray(canvas).resize(src.size, Image.NEAREST))
    else:
        back = np.asarray(Image.fromarray(al).resize(src.size, Image.NEAREST))
    return back < 128


def build(src, mask, tex_size, fit="cover"):
    """the portrait texture picture: `src` with `mask` transparent, fitted like the kit fits portraits"""
    from .outfits import fit_portrait
    img = imgtools.apply_background(src, mask)
    if fit == "cover":
        return fit_portrait(img, tex_size)
    return img.resize(tex_size, Image.LANCZOS)


def save(mod, anm_id, src, mask, source=None, fit="cover", keep_marks=True):
    """write portrait anm_id built from `src` with `mask` (and keep the marks, and where the picture came from)"""
    a, _ = load_portrait(mod, anm_id)
    t = a.textures[0]
    img = build(src, mask, (t.width, t.height), fit)
    if t.indexed:
        raise ValueError("this portrait is a paletted picture; only full-colour portraits can be fixed")
    old = bytes(t.data)
    data = anm._rgba_to_argb(np.asarray(img)).tobytes()
    t.data = data
    mod.write_file(_vp(anm_id), a.to_bytes())
    # its copies (an outfit's portrait by slot and by sprite number, set_cutin) get the same picture
    for other in twins(mod, anm_id, old):
        b = anm.load(mod.read_file(_vp(other)))
        b.textures[0].data = data
        mod.write_file(_vp(other), b.to_bytes())
    os.makedirs(_dir(mod), exist_ok=True)
    if keep_marks:
        Image.fromarray((np.asarray(mask, bool) * 255).astype(np.uint8)).save(mask_path(mod, anm_id))
    if source is not None and not load_info(mod, anm_id).get("source"):
        info = {"fit": fit}
        parts = os.path.normpath(source).replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[-2] in ("Cut-Ins", "Cutins"):
            info["source"] = "drpg:" + parts[-1]
        else:
            name = f"portrait_{int(anm_id)}.png"
            src.convert("RGBA").save(os.path.join(_dir(mod), name))
            info["source"] = name
        with open(info_path(mod, anm_id), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1)
    return img


def twins(mod, anm_id, data=None):
    """other portraits of the mod holding the same picture as anm_id (or as texture bytes `data`)"""
    if data is None:
        data = bytes(anm.load(mod.read_file(_vp(anm_id))).textures[0].data)
    out = []
    for n in portraits_of(mod):
        if n == int(anm_id):
            continue
        try:
            t = anm.load(mod.read_file(_vp(n))).textures[0]
        except Exception:
            continue
        if len(t.data) == len(data) and bytes(t.data) == data:
            out.append(n)
    return out


def portraits_of(mod):
    """the full-colour portraits (anm 10000 .. 29999, 336 x 1080) a mod has -> sorted anm ids"""
    out = []
    for f in mod.list_files():
        base = f.rsplit("/", 1)[-1]
        if not (base.startswith("anm") and base.endswith(".lzs")):
            continue
        n = base[3:-4]
        if n.isdigit() and 10000 <= int(n) < 30000:
            out.append(int(n))
    return sorted(out)
