#!/usr/bin/env python3
"""DRPGCUTIN2: stage the DRPG packs whose looks have a cut-in made from their own illustration.

    python tools/stage_drpg_cutin2.py INSTALLED_MODS REBUILT_MODS OUT_DIR

REBUILT_MODS = the `mods/` of `import_game.py drpg --only ...` run with D5_DRPG_OWN_CUTINS pointing at the cut-ins
`tools/make_drpg_own_cutins.py` wrote.  For every REBUILT pack that has a `source_import.cutin_from_illustration`
label: clone the installed folder (APFS clone, INSTALLED_MODS is only read) and take from the rebuild only
  - the portrait bank(s) `files/Anime/ANM_HI_JP.dat/anm<N>.lzs` that have a new `patches/characters/portrait_<N>.json`
    (+ that json and the png the binding copies next to it),
  - the label: mod.json `description`, `source_import.cutin_from_illustration`, `source_import.portraits`,
    outfits.json `portraits`, and the receipt's cut-in lines.
Everything else (body banks, tables, evilities, voices) stays the installed pack's: later lanes changed those after the
importer.  The run stops when the clone differs from the installed folder in any other file.  Writes
OUT_DIR/STAGE-RECEIPT.json.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(installed, rebuilt, out):
    installed, rebuilt, out = Path(installed), Path(rebuilt), Path(out)
    mods = out / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    receipt = dict(lane="DRPGCUTIN2", installed=str(installed), rebuilt=str(rebuilt), packs=[])
    for rb in sorted(rebuilt.glob("DRPG_Core_*")):
        meta = json.loads((rb / "mod.json").read_text())
        label = meta.get("source_import", {}).get("cutin_from_illustration")
        if not label:
            continue
        old, dest = installed / rb.name, mods / rb.name
        if dest.exists():
            sys.exit(f"{dest} exists; refusing to overwrite")
        subprocess.run(["cp", "-c", "-R", str(old), str(dest)], check=True)      # APFS clone
        chars = rb / "patches" / "characters"
        new = sorted(int(p.stem.split("_")[1]) for p in chars.glob("portrait_*.json")
                     if not (old / "patches" / "characters" / p.name).exists())
        if not new:
            sys.exit(f"{rb.name}: no new portrait binding in the rebuild")
        touched = []
        for n in new:
            for rel in (f"files/Anime/ANM_HI_JP.dat/anm{n:05d}.lzs", f"patches/characters/portrait_{n}.json",
                        f"patches/characters/portrait_{n}.png"):
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                (dest / rel).write_bytes((rb / rel).read_bytes())
                touched.append(rel)
        # label: mod.json
        m = json.loads((old / "mod.json").read_text())
        m["description"] = meta["description"]
        m["source_import"]["cutin_from_illustration"] = label
        if "portraits" in meta["source_import"]:
            m["source_import"]["portraits"] = meta["source_import"]["portraits"]
        (dest / "mod.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
        touched.append("mod.json")
        # outfits.json portraits
        of_old, of_new = old / "patches/outfits/outfits.json", rb / "patches/outfits/outfits.json"
        if of_old.exists() and of_new.exists():
            o = json.loads(of_old.read_text())
            pn = json.loads(of_new.read_text()).get("portraits")
            if pn is not None and o.get("portraits") != pn:
                o["portraits"] = pn
                (dest / "patches/outfits/outfits.json").write_text(json.dumps(o, indent=1) + "\n")
                touched.append("patches/outfits/outfits.json")
        # receipt lines
        r_old, r_new = old / "CORERPG1-receipt.json", rb / "CORERPG1-receipt.json"
        if r_old.exists() and r_new.exists():
            r = json.loads(r_old.read_text())
            rn = json.loads(r_new.read_text())
            r["features"]["cutin"] = rn["features"]["cutin"]
            r["cutin_from_illustration"] = rn["cutin_from_illustration"]
            r["notes"] = r["notes"] + [x for x in rn["notes"] if x.startswith("Cut-in:")]
            if "portraits" in rn:
                r["portraits"] = rn["portraits"]
            (dest / "CORERPG1-receipt.json").write_text(json.dumps(r, indent=1, ensure_ascii=False, default=str) + "\n")
            touched.append("CORERPG1-receipt.json")
        # gate: the clone differs from the installed folder in the touched files only
        files = lambda root: {str(f.relative_to(root)): f for f in root.rglob("*") if f.is_file()}
        fo, fd = files(old), files(dest)
        differ = sorted(k for k in fo.keys() | fd.keys() if k not in fo or k not in fd or fo[k].read_bytes() != fd[k].read_bytes())
        extra = [x for x in differ if x not in touched]
        if extra:
            sys.exit(f"{rb.name}: unexpected differences {extra}")
        receipt["packs"].append(dict(folder=rb.name, labels=label, portrait_banks=new, differ=differ,
                                     sha256={rel: sha(dest / rel) for rel in differ if rel.endswith(".lzs")}))
        print(rb.name, "differs from installed in", len(differ), "files:", ", ".join(differ))
    (out / "STAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=1) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
