#!/usr/bin/env python3
"""DRPGEVIL1: stage the DRPG packs whose own evilities the overlay allows, without rebuilding art.

    python tools/stage_drpg_evilities.py SOURCE_MODS[:SOURCE_MODS2...] OUT_DIR [--decisions D1,D2,D3]

SOURCE_MODS may be several folders joined with ':'; a pack is taken from the first one that has it (e.g. the
staged SMALLFIX1 build first, the installed mods second).

For every DRPG_Core_* pack with at least one applicable own evility: clone the installed folder (APFS clone,
no data copied), run the importer's own table steps on the clone (drpg_titles.apply, drpg_evilities.apply: the
same functions a full rebuild calls), check the gates, and compare the clone with the installed folder file by
file.  Only patches/db/char.dat.json, patches/db/Skill.dat.json, patches/evilities/* and mod.json may differ;
anything else stops the run.  INSTALLED_MODS is only read.  Writes OUT_DIR/STAGE-RECEIPT.json.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
ALLOWED = ("patches/db/char.dat.json", "patches/db/Skill.dat.json", "patches/evilities/evilities.json",
           "patches/evilities/aliases.json", "mod.json")
EV_KEYS = {"evility1", "evility2", "evility3", "evility4", "evility_count"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv):
    from d5lib.importers import drpg_evilities, drpg_titles
    dec = {}
    if "--decisions" in argv:
        i = argv.index("--decisions")
        dec = {k: True for k in argv[i + 1].split(",") if k}
        argv = argv[:i] + argv[i + 2:]
    samples = "--samples" in argv          # DRPGSAMPLES: stage only the hand-built DRPG_Sample_* packs (overlay's samples_untouched lifted here only)
    argv = [a for a in argv if a != "--samples"]
    if samples:
        drpg_evilities.overlay()["samples_untouched"] = []
    srcs, out = [Path(x).resolve() for x in argv[0].split(":")], Path(argv[1])
    mods = out / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    receipt = dict(lane="DRPGEVIL1", sources=[str(x) for x in srcs], decisions=dec or drpg_evilities.overlay()["decisions"], packs=[])
    picked = {}
    for src in reversed(srcs):
        picked.update({d.name: d for d in src.glob("DRPG_Sample_*" if samples else "DRPG_Core_*")})
    for d in sorted(picked.values(), key=lambda d: d.name):
        meta = json.loads((d / "mod.json").read_text())
        base = meta["source_import"]["source"]["character"]["base_id"]
        if not drpg_evilities.enabled(base, dec):
            continue
        dest = mods / d.name
        if dest.exists():
            raise SystemExit(f"{dest} exists; stage into an empty folder")
        subprocess.run(["cp", "-cR", str(d), str(dest)], check=True)
        drpg_titles.apply(dest, base)
        done = drpg_evilities.apply(dest, base, dec)
        ok, why = drpg_evilities.gate(dest, base, dec)
        tok, twhy = drpg_titles.gate(dest, base)
        if not (ok and tok):
            raise SystemExit(f"{d.name}: gate failed: {why} / {twhy}")
        a = {str(p.relative_to(d)): p for p in d.rglob("*") if p.is_file()}
        b = {str(p.relative_to(dest)): p for p in dest.rglob("*") if p.is_file()}
        differ = sorted(k for k in a.keys() | b.keys() if k not in a or k not in b or sha(a[k]) != sha(b[k]))
        bad = [k for k in differ if k not in ALLOWED]
        if bad:
            raise SystemExit(f"{d.name}: files outside the table set differ: {bad}")
        old = json.loads(a["patches/db/char.dat.json"].read_text())["added"]
        new = json.loads(b["patches/db/char.dat.json"].read_text())["added"]
        keys = {k for o, n in zip(old, new) for k in o.keys() | n.keys() if o.get(k) != n.get(k)}
        title = {k for k in keys if k.startswith("title_")}
        if len(old) != len(new) or keys - EV_KEYS - title:
            raise SystemExit(f"{d.name}: char.dat fields outside evility/title changed: {sorted(keys - EV_KEYS - title)}")
        art = sorted(k for k in a if k.startswith("files/"))
        receipt["packs"].append(dict(folder=d.name, source=str(d.parent), base_id=base, own=done["own"], links=done["links"], gate=why,
                                     files=len(a), differ=differ, char_fields_changed=sorted(keys),
                                     titles_already_in_source=not title,
                                     art_files=len(art), art_identical=all(k not in differ for k in art),
                                     art_sha256={k: sha(b[k]) for k in art}))
    # Save safety: learned evilities are one bit per Skill.dat row POSITION for the first 1000 rows (d5lib/learned.py),
    # so the new rows must sort after every row another pack already has.
    # EVILFX2: rows inside this importer's own band (the overlay's `band`, carved in the ownership manifest) are the
    # earlier stage of the same packs, not another pack's rows; without this a restage over installed packs that
    # already carry 28000+ rows could never run.  Every row OUTSIDE the band must still sort before ours.
    lo, hi = drpg_evilities.overlay()["band"]
    foreign = [int(r["id"]) for src in srcs for f in src.glob("*/patches/db/Skill.dat.json")
               for r in json.loads(f.read_text()).get("added") or [] if not lo <= int(r["id"]) <= hi]
    mine = [i for p in receipt["packs"] for i in p["own"]]
    if mine and foreign and min(mine) <= max(foreign):
        raise SystemExit(f"own evility ids start at {min(mine)}, not above the highest id in use ({max(foreign)})")
    receipt["append_only"] = dict(lowest_new_id=min(mine) if mine else None, highest_existing_id=max(foreign) if foreign else None)
    receipt["counts"] = dict(packs=len(receipt["packs"]), own_evilities=sum(len(p["own"]) for p in receipt["packs"]),
                             art_files=sum(p["art_files"] for p in receipt["packs"]),
                             art_identical=all(p["art_identical"] for p in receipt["packs"]))
    (out / "STAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(receipt["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
