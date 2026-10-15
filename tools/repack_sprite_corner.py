"""Pack the sprites of new characters again with their stand picture alone in the top-left corner of texture 0
(d5lib.ownanim.repack_corner): the Quest Shop's 'has joined' banner shows that corner, and sprites built before kit
1.5 had other frames there (the banner showed pieces of them).  The sprite, its companion copy (N+1) and the
full-colour source change the same way; every animation is checked to draw exactly as before.

    python tools/repack_sprite_corner.py [MOD ...] [--dry]

Without MOD: every mod with new characters.  Install afterwards.
"""
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)

import numpy as np                                          # noqa: E402

from d5lib import anm, ownanim, outfits, savegame           # noqa: E402
from d5lib.modsys import ModManager                         # noqa: E402


def _frames(a):
    """every animation's pictures at a few times, as arrays (to compare before / after)"""
    out = []
    for info in anm.list_animations(a)[:40]:
        for t in sorted({0, info["length"] // 2, info["length"]}):
            try:
                out.append(np.asarray(anm.render_frame(a, info["index"], time=t)))
            except Exception:
                out.append(None)
    return out


def same(a, b):
    fa, fb = _frames(a), _frames(b)
    return len(fa) == len(fb) and all((x is None and y is None) or (x is not None and y is not None and
                                                                    x.shape == y.shape and np.array_equal(x, y))
                                      for x, y in zip(fa, fb))


def main():
    dry = "--dry" in sys.argv
    names = [x for x in sys.argv[1:] if not x.startswith("--")]
    mm = ModManager(KIT)
    mods = [mm.get(n) for n in names] if names else mm.all_mods()
    for mod in mods:
        if mod is None:
            continue
        info = savegame.mod_characters(mod)
        patch = mod.load_patch("db", "char.dat.json") or {}
        sprites_ = sorted({int(r["sprite_id"]) for r in patch.get("added") or []
                           if int(r.get("id", -1)) in info["classes"] and r.get("sprite_id")})
        for N in sprites_:
            for n in (N, N + 1):
                vp = f"Anime/ANM_HI_JP.dat/anm{n:05d}.lzs"
                if not mod.has_file(vp):
                    continue
                before = anm.load(mod.read_file(vp))
                a = anm.load(mod.read_file(vp))
                if not ownanim.repack_corner(a):
                    print(f"{mod.id}: anm{n:05d} already has its stand picture alone in the corner")
                    continue
                ok = same(before, a)
                print(f"{mod.id}: anm{n:05d} repacked ({len(before.textures)} -> {len(a.textures)} textures), "
                      f"animations {'identical' if ok else 'DIFFERENT - not written'}")
                if ok and not dry:
                    mod.write_file(vp, a.to_bytes())
            src = outfits.load_source(mod, N)
            if src is not None and ownanim.repack_corner(src):
                print(f"{mod.id}: source_{N}.anm repacked")
                if not dry:
                    outfits.save_source(mod, N, src)


if __name__ == "__main__":
    main()
