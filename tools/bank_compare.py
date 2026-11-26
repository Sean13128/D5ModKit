#!/usr/bin/env python3
"""BLANKKEYS1: compare two animation banks by CONTENT (not by hash): per animation id, the key times and the rendered
picture at every key time, palette 0.  Verdict per id: same / timing (key times differ) / art (a picture differs) /
only-a / only-b.  Also textures and palettes counts.

    D5Modkit/.venv-macos/bin/python tools/bank_compare.py A.lzs B.lzs
"""
import hashlib
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

from d5lib import anm, gamefs  # noqa: E402


def load(path):
    return anm.parse(gamefs.decode_member(Path(path).read_bytes()))


def signature(fl, aid, pal=0):
    """[(key time, sha of the rendered RGBA at that time or None when nothing draws)]"""
    out = []
    for t in anm.frame_times(fl, ("id", aid)):
        its = [i for i in anm.evaluate(fl, ("id", aid), t, nested=True) if i.cell.w > 0 and i.cell.h > 0]
        if not its:
            out.append((t, None))
            continue
        img, _ = anm.render_items(fl, its, pal, bounds=(-256, -256, 256, 256))
        out.append((t, hashlib.sha1(np.asarray(img).tobytes()).hexdigest()[:12]))
    return out


def compare(a, b, pal=0):
    ids_a = {x.id for _, _, x in a.all_animations()}
    ids_b = {x.id for _, _, x in b.all_animations()}
    res = {}
    for aid in sorted(ids_a | ids_b):
        if aid not in ids_b:
            res[aid] = "only-a"
        elif aid not in ids_a:
            res[aid] = "only-b"
        else:
            sa, sb = signature(a, aid, pal), signature(b, aid, pal)
            res[aid] = ("same" if sa == sb else "timing" if [t for t, _ in sa] != [t for t, _ in sb] else "art")
    return res


def summary(a, b):
    r = compare(a, b)
    cnt = {}
    for v in r.values():
        cnt[v] = cnt.get(v, 0) + 1
    return dict(counts=cnt, textures=(len(a.textures), len(b.textures)), palettes=(len(a.palettes), len(b.palettes)),
                differing=[k for k, v in r.items() if v != "same"])


if __name__ == "__main__":
    s = summary(load(sys.argv[1]), load(sys.argv[2]))
    print(s["counts"], "textures", s["textures"], "palettes", s["palettes"])
    print("differ:", s["differing"][:60])
