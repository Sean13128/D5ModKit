"""Build the portraits of mods again from their original pictures with the kit's current background removal
(d5lib/portraitfix.py, imgtools.background_mask).  Kit 1.4 took white clothes that touch the picture's edge for
background (Henna's dress, Thunderlady's top): they come back.  Only pixels the current guess keeps come back;
nothing more is made transparent (--full: the current guess as it is, which can also remove more).  A portrait the
user fixed by hand (portrait_mask_<anm>.png) is left as it is.

    python tools/refit_portraits.py [MOD ...] [--apply] [--full] [--sheet OUT.png]

Without --apply: what would change.  The original of a Disgaea RPG portrait is found among the cut-ins in the DRPG
asset folders (by look) and remembered in the mod.
"""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

import numpy as np                                    # noqa: E402
from PIL import Image                                 # noqa: E402

from d5lib import portraitfix as pf                   # noqa: E402
from d5lib.modsys import ModManager                   # noqa: E402

CACHE = os.path.join(KIT, "cache")


def main():
    apply = "--apply" in sys.argv
    sheet = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else None
    names = [x for x in sys.argv[1:] if not x.startswith("--") and x != sheet]
    mm = ModManager(KIT)
    mods = [mm.get(n) for n in names] if names else mm.all_mods()
    tiles = []
    for mod in mods:
        if mod is None:
            continue
        done = set()
        for n in pf.portraits_of(mod):
            if n in done or os.path.exists(pf.mask_path(mod, n)):
                continue
            try:
                a, cur = pf.load_portrait(mod, n)
            except Exception:
                continue
            t = a.textures[0]
            if t.indexed or (t.width, t.height) != (336, 1080):
                continue
            src_p = pf.source_path(mod, n) or pf.find_drpg_source(cur, CACHE)
            if not src_p:
                print(f"{mod.id}: anm{n}: original not found")
                continue
            fit = pf.load_info(mod, n).get("fit", "cover")
            src = Image.open(src_p).convert("RGBA")
            mask = pf.auto_mask(src)
            if "--full" not in sys.argv:
                mask &= pf.current_mask(mod, n, src, cur, fit)
            new = pf.build(src, mask, (t.width, t.height), fit)
            ca, na = np.asarray(cur)[:, :, 3], np.asarray(new)[:, :, 3]
            back = int(((ca < 128) & (na >= 128)).sum())
            gone = int(((ca >= 128) & (na < 128)).sum())
            twin = pf.twins(mod, n)
            done |= set(twin)
            if back < 400 and gone < 400:
                continue
            print(f"{mod.id}: anm{n} (+{len(twin)} copies) from {os.path.basename(src_p)}: {back} px come back, "
                  f"{gone} px go")
            if sheet:
                tiles.append((f"{mod.id[:14]} {n}", cur, new))
            if apply:
                pf.save(mod, n, src, mask, source=src_p, fit=fit, keep_marks=False)
    if sheet and tiles:
        cols = 6
        W, H = 2 * 112 + 6, 360 + 14
        out = Image.new("RGB", (cols * W, ((len(tiles) + cols - 1) // cols) * H), (0, 0, 0))
        from PIL import ImageDraw
        d = ImageDraw.Draw(out)
        for i, (lab, a_, b_) in enumerate(tiles):
            x, y = (i % cols) * W, (i // cols) * H
            for k, im in enumerate((a_, b_)):
                bg = Image.new("RGBA", im.size, (255, 0, 255, 255))
                bg.alpha_composite(im)
                out.paste(bg.convert("RGB").resize((112, 360)), (x + k * 114, y + 14))
            d.text((x + 2, y), lab, fill=(255, 255, 0))
        out.save(sheet)
        print("sheet:", sheet)


if __name__ == "__main__":
    main()
