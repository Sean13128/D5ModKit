"""Building new effect models for skills (cards, pictures, ...) from a vanilla one: own picture, own size, own
animation (d5lib/fxanim.py).  A mod keeps the result as a whole .obf next to its skills.json:
    "effects": {"3002": {"from": 1200, "obf": "fx3002.obf"}}
and the installer puts it into Effect.dat (skills._handler).

    fxbuild.picture_model(base, image, w, h)   one picture on a quad, w x h model units (map units, 12 = 1 panel);
                                               base: a one-quad in-world effect such as 1200
    fxbuild.spin(...) / fxbuild.static(...)     ready-made animations
    fxbuild.save(mod, effect_id, obf_file, from_id)
"""
import os

import numpy as np

from . import fxanim, obf, skills

PICTURE_BASE = 1200         # one in-world quad, DXT3 picture with alpha (1915-1918 look like 160 x 90 = 16:9
                            # skill backdrop pictures, so they are avoided)


BLEND = {"alpha": (1, 2), "add": (2, 4)}     # mesh flags bytes 0-1 (vanilla 1723 picture quad: 1, 2; glows: 2, 4)


def picture_model(base, image, w, h, anchor=(0.5, 0.5), keep_format=True, blend="alpha"):
    """ObfFile `base` (a one-quad model such as effect 1200) with `image` on a w x h quad; anchor = which point of
    the picture sits at the model's origin (0.5, 0.5 centre; 0.5, 1.0 bottom middle)"""
    v = np.array(base.vertices(), dtype="<f4").copy()
    if len(v) != 6:
        raise ValueError("the base model must be one quad (6 vertices)")
    x0, x1 = -w * anchor[0], w * (1 - anchor[0])
    y0, y1 = -h * (1 - anchor[1]), h * anchor[1]
    # keep the base's triangle layout: each vertex keeps its corner, found from its uv
    for k in range(6):
        u, vv = v[k, 13], v[k, 14]
        v[k, 0] = x1 if u > 0.5 else x0
        v[k, 1] = y0 if vv > 0.5 else y1
        v[k, 2] = 0.0
        v[k, 13] = 1.0 if u > 0.5 else 0.0
        v[k, 14] = 1.0 if vv > 0.5 else 0.0
    base.set_vertices(v)
    for m in base.meshes:                    # how it blends: a paper card must not add light (white where cards overlap)
        m.raw_head[32], m.raw_head[33] = BLEND[blend]
    base.textures[0].replace_image(image, keep_format=keep_format, resize=True)
    base._tex = base.textures                     # make to_bytes write the changed texture
    return base


def static(length=60, loop=True):
    """one node drawing part 0, still (a looping animation of `length` frames: a model shown with a play count
    plays its animation that many times and then disappears, so a 0-frame model only lasts with count -1)"""
    pts = [fxanim.Point(0.0, fxanim.LINEAR, 0), fxanim.Point(1.0, fxanim.LINEAR, 0)]
    key = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]
    return fxanim.Anim(length, 1 if loop else 0, [fxanim.Node(0, -1, [0])], [key], pts, [0])


def spin(axis="z", frames=30, turns=1.0, loop=True, wobble=0.0):
    """one node drawing part 0, turning `turns` times around an axis every `frames` frames (looping); wobble = a
    sway of that many radians around y instead of a full turn when turns == 0"""
    c = {"x": 3, "y": 4, "z": 5}[axis]
    pts = [fxanim.Point(0.0, fxanim.LINEAR, 0), fxanim.Point(1.0, fxanim.LINEAR, 0)]
    if turns:
        pts += [fxanim.Point(0.0, fxanim.LINEAR, 0), fxanim.Point(2 * np.pi * turns, fxanim.LINEAR, frames)]
        keys = []
        for k in (2, 3):
            key = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]
            key[c] = k
            keys.append(key)
    else:
        pts += [fxanim.Point(-wobble, fxanim.SMOOTH, 0), fxanim.Point(wobble, fxanim.SMOOTH, frames // 2),
                fxanim.Point(-wobble, fxanim.SMOOTH, frames)]
        keys = []
        for k in (2, 3, 4):
            key = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1]
            key[c] = k
            keys.append(key)
    return fxanim.Anim(frames, 1 if loop else 0, [fxanim.Node(0, -1, list(range(len(keys))))], keys, pts, [0])


def save(mod, effect_id, model, from_id):
    """store a whole effect model in the mod -> effect id"""
    d = skills.load(mod)
    name = f"fx{int(effect_id)}.obf"
    with open(os.path.join(skills.folder(mod), name), "wb") as f:
        f.write(model.to_bytes())
    d["effects"][str(int(effect_id))] = {"from": int(from_id), "obf": name}
    skills.save(mod, d)
    return int(effect_id)


def load_base(get, eid, members=None):
    return skills.load_effect(get, eid, members)


def with_anim(model, anim):
    fxanim.write(model, anim)
    return model


__all__ = ["picture_model", "static", "spin", "save", "load_base", "with_anim", "obf"]
