#!/usr/bin/env python3
"""DRPGCUTIN2: cut-ins for the Disgaea RPG looks whose source has no `chara/ci/<id>`, made from the look's own art.

    # 1. decode (needs UnityPy: /Volumes/Data/ai-tmp/hermes/drpg-tables/.venv/bin/python)
    python tools/make_drpg_own_cutins.py decode ASSETBUNDLE_IMAGES_DIR SCRATCH_DIR ID [ID ...]
    # 2. frame (kit venv): writes OUT_DIR/<id>.png, the folder the importer reads (d5lib.drpgcutin.OWN_DIR)
    python tools/make_drpg_own_cutins.py frame SCRATCH_DIR OUT_DIR ID [ID ...]

ASSETBUNDLE_IMAGES_DIR = `Disgaea Source/Disgaea RPG JP (Android)/extracted/sdcard/Android/data/com.disgaearpg.forwardworks/
files/assetbundle/images` (read only).  Looks in d5lib.drpgcutin.OVERRIDES use their listed larger picture, the others the
generic rule on `chara/illust/<id>` (rule and measurements: d5lib/drpgcutin.py).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from d5lib import drpgcutin


def texture(bundle):
    import UnityPy
    for o in UnityPy.load(bundle).objects:
        if o.type.name == "Texture2D":
            return o.read().image
    sys.exit(f"no texture in {bundle}")


if __name__ == "__main__":
    mode, a, b, ids = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    os.makedirs(b, exist_ok=True)
    for i in ids:
        if mode == "decode":
            rel = drpgcutin.OVERRIDES[i][0] if i in drpgcutin.OVERRIDES else f"chara/illust/{i}"
            texture(os.path.join(a, rel)).save(os.path.join(b, f"art_{i}.png"))
        else:
            from PIL import Image
            img = Image.open(os.path.join(a, f"art_{i}.png"))
            if i in drpgcutin.OVERRIDES:
                out = drpgcutin.frame_window(img, *drpgcutin.OVERRIDES[i][1:])
            else:
                out = drpgcutin.frame_illustration(img)
            out.save(os.path.join(b, f"{i}.png"))
