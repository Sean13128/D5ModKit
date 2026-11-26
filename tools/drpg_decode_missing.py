#!/usr/bin/env python3
"""DRPG-K2B: decode the costume-look bundles the CORERPG2 reader was missing.

Reuses RPGEXTRACT1's decode path verbatim (UnityPy 1.25.4, Texture2D -> PNG unchanged,
Sprite rects recorded) and writes into the same reader layout
`extracted/sprites/Sprites/Standard/{BattleFront,BattleBack,WaitFront,WaitBack}`,
`extracted/sprites/Chara Icons`, `extracted/sprites/Cutins`.

Additive only: an existing PNG is never overwritten or deleted.  RPGEXTRACT1's own
MANIFEST.json / looks.json / atlas-index.json are left untouched; this run records its
files in MANIFEST-k2b.json / looks-k2b.json / atlas-index-k2b.json next to them.

    python decode_missing.py 185 192 206 ...
"""
import hashlib
import json
import os
import sys

SRC = "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea RPG JP (Android)"
EX = os.path.join(SRC, "extracted")
DEV = "/sdcard/Android/data/com.disgaearpg.forwardworks/files/assetbundle/"
BUNDLE = os.path.join(EX, "sdcard/Android/data/com.disgaearpg.forwardworks/files/assetbundle")

# bundle prefix -> (reader subdir, bundle leaf template, reader file template, slot key)
SLOTS = [
    ("atlas/chara/battle/front/", "Sprites/Standard/BattleFront", "front{id}", "front{id}.png", "battle_front"),
    ("atlas/chara/battle/back/", "Sprites/Standard/BattleBack", "back{id}", "back{id}.png", "battle_back"),
    ("atlas/chara/battle/wait_front/", "Sprites/Standard/WaitFront", "front{id}", "front{id}.png", "idle_front"),
    ("atlas/chara/battle/wait_back/", "Sprites/Standard/WaitBack", "back{id}", "back{id}.png", "idle_back"),
    ("images/chara/face/", "Chara Icons", "{id}", "{id}.png", "face"),
    ("images/chara/ci/", "Cutins", "{id}", "{id}.png", "cut_in"),
]


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def reader_path(prefix, sub, bundle_tpl, file_tpl, look):
    """(bundle path relative to assetbundle/, reader PNG path relative to extracted/sprites/)."""
    return prefix + bundle_tpl.format(id=look), os.path.join(sub, file_tpl.format(id=look))


def main(looks):
    import UnityPy  # UnityPy 1.25.4: RPGEXTRACT1's own decoder; not a Kit dependency

    manifest, atlas, index, errors, skipped = [], {}, {}, [], []
    for look in looks:
        for prefix, sub, bundle_tpl, file_tpl, slot in SLOTS:
            leaf = bundle_tpl.format(id=look)
            rel = prefix + leaf
            path = os.path.join(BUNDLE, rel)
            if not os.path.isfile(path):
                errors.append({"look": look, "bundle": rel, "error": "bundle absent on disk"})
                continue
            try:
                env = UnityPy.load(path)
            except Exception as e:  # noqa: BLE001
                errors.append({"look": look, "bundle": rel, "error": f"load: {e}"})
                continue
            tex, sprites = None, []
            for obj in env.objects:
                if obj.type.name == "Texture2D":
                    tex = obj
                elif obj.type.name == "Sprite":
                    try:
                        d = obj.read()
                        sprites.append({"name": d.m_Name, "x": round(d.m_Rect.x, 2), "y": round(d.m_Rect.y, 2),
                                        "w": round(d.m_Rect.width, 2), "h": round(d.m_Rect.height, 2)})
                    except Exception:  # noqa: BLE001
                        pass
            if tex is None:
                errors.append({"look": look, "bundle": rel, "error": "no Texture2D"})
                continue
            img = tex.read().image  # PIL image, RGBA
            dest_dir = os.path.join(EX, "sprites", sub)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, file_tpl.format(id=look))
            existed = os.path.exists(dest)
            if not existed:
                img.save(dest)
            raw = open(dest, "rb").read()
            entry = {"device_path": DEV + rel, "bundle": rel, "file": os.path.relpath(dest, EX),
                     "sha256": sha256(raw), "size": len(raw),
                     "bytes_on_device": os.path.getsize(path),
                     "png_width": img.width, "png_height": img.height, "look_id": int(look),
                     "slot": slot, "bundle_sha256": sha256(open(path, "rb").read())}
            if existed:
                # decoded by an earlier invocation of this same script; re-measured, not rewritten
                entry["decoded"] = "earlier-run"
                skipped.append({"look": look, "file": entry["file"], "reason": "already decoded"})
            else:
                entry["decoded"] = "this-run"
            manifest.append(entry)
            index.setdefault(int(look), {})[slot] = entry["file"]
            atlas[rel] = {"bundle_sha256": entry["bundle_sha256"], "width": img.width, "height": img.height,
                          "sprites": sorted(sprites, key=lambda s: s["name"])}
    out = os.path.join(EX, "sprites")
    json.dump({"schema": "drpg-k2b-decode/1", "device_root": DEV, "looks": sorted(looks),
               "png_count": len(manifest), "errors": errors, "skipped": skipped, "files": manifest},
              open(os.path.join(out, "MANIFEST-k2b.json"), "w"), indent=1)
    json.dump({str(k): v for k, v in sorted(index.items())},
              open(os.path.join(out, "looks-k2b.json"), "w"), indent=1)
    json.dump(atlas, open(os.path.join(out, "atlas-index-k2b.json"), "w"), indent=1)
    print(json.dumps({"looks": len(looks), "pngs": len(manifest), "skipped": len(skipped),
                      "error_count": len(errors), "errors": errors[:5]}, indent=1))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main([int(a) for a in sys.argv[1:]]))
