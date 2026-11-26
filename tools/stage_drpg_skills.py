#!/usr/bin/env python3
"""DRPGSKILL1: stage the DRPG packs whose own skills the overlay allows, without rebuilding art.

    python tools/stage_drpg_skills.py SOURCE_MODS[:SOURCE_MODS2...] OUT_DIR [--decisions M1,C1] [--only ID,ID]

For every DRPG pack with at least one own skill: clone the source folder (APFS clone, no data copied), run the
importer's own table step on the clone (drpg_skills.apply, the function a full rebuild calls), check the gate
(overlay rows, every learn link resolves, caster motions present on every body, field widths), and compare the
clone with the source folder file by file.  Only patches/db/char.dat.json (learn fields), patches/db/magic.dat.json,
patches/skills/skills.json and mod.json may differ; anything else stops the run.  SOURCE_MODS is only read.
Writes OUT_DIR/STAGE-RECEIPT.json (sha256 of every staged file).
--build-check CONTEXT_MODS[,..] also runs modsys.build on disposable clones and re-hashes the stage against the receipt.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
ALLOWED = ("patches/db/char.dat.json", "patches/db/magic.dat.json", "patches/skills/skills.json", "mod.json")
LEARN = {f"learn{i}_{k}" for i in range(1, 17) for k in ("skill", "level")} | {"learn_count"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv):
    from d5lib import skillmotions
    from d5lib.importers import drpg_evilities, drpg_skills, drpg_titles
    dec, only = {}, None
    if "--decisions" in argv:
        i = argv.index("--decisions")
        dec = {k: True for k in argv[i + 1].split(",") if k}
        argv = argv[:i] + argv[i + 2:]
    check = None
    if "--build-check" in argv:        # modsys.build on disposable clones (never the staged folders); then re-verify
        i = argv.index("--build-check")
        check = [Path(x) for x in argv[i + 1].split(",") if x]       # read-only context mods, e.g. installed Outfit_System
        argv = argv[:i] + argv[i + 2:]
    if "--only" in argv:
        i = argv.index("--only")
        only = {int(x) for x in argv[i + 1].split(",")}
        argv = argv[:i] + argv[i + 2:]
    srcs, out = [Path(x).resolve() for x in argv[0].split(":")], Path(argv[1])
    mods = out / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    sv = skillmotions.Survey()
    vanilla = drpg_skills.vanilla_rows(sv.fs)
    band = drpg_skills.overlay()["band"]
    receipt = dict(lane="DRPGSKILL1", sources=[str(x) for x in srcs],
                   decisions={k: bool(dec.get(k, v)) for k, v in drpg_skills.overlay()["decisions"].items()}, packs=[])
    picked = {}
    for src in reversed(srcs):
        picked.update({d.name: d for d in src.glob("DRPG_*") if (d / "mod.json").is_file()})
    # ids of this band already carried by another folder of the sources would be a second owner
    foreign = {}
    for src in srcs:
        for f in src.glob("*/patches/db/magic.dat.json"):
            for r in json.loads(f.read_text()).get("added") or []:
                foreign.setdefault(int(r["id"]), set()).add(f.parents[2].name)
    for d in sorted(picked.values(), key=lambda d: d.name):
        meta = json.loads((d / "mod.json").read_text())
        c = (meta.get("source_import") or {}).get("source")
        c = c.get("character") if isinstance(c, dict) else None
        if not c or "base_id" not in c:
            continue
        base = int(c["base_id"])
        if (only and base not in only) or not drpg_skills.enabled(base, dec):
            continue
        dest = mods / d.name
        if dest.exists():
            raise SystemExit(f"{dest} exists; stage into an empty folder")
        subprocess.run(["cp", "-cR", str(d), str(dest)], check=True)
        done = drpg_skills.apply(dest, base, dec, vanilla)
        ok, why = drpg_skills.gate(dest, base, dec, survey=sv, vanilla=vanilla)
        # the other importer gates must say what they said on the untouched source folder (the installed packs were
        # staged with their own evility decisions, recorded in mod.json)
        edec = ((meta.get("source_import") or {}).get("evilities") or {}).get("decisions")
        eok, ewhy = drpg_evilities.gate(dest, base, edec)
        tok, twhy = drpg_titles.gate(dest, base)
        if (eok, ewhy) != drpg_evilities.gate(d, base, edec) or (tok, twhy) != drpg_titles.gate(d, base):
            raise SystemExit(f"{d.name}: evility / title gate changed by the skill step")
        if not ok:
            raise SystemExit(f"{d.name}: skill gate failed: {why}")
        clash = [i for i in done["rows"] if foreign.get(i, set()) - {d.name}]
        if clash:
            raise SystemExit(f"{d.name}: leased skill ids {clash} are carried by another folder")
        a = {str(p.relative_to(d)): p for p in d.rglob("*") if p.is_file()}
        b = {str(p.relative_to(dest)): p for p in dest.rglob("*") if p.is_file()}
        differ = sorted(k for k in a.keys() | b.keys() if k not in a or k not in b or sha(a[k]) != sha(b[k]))
        bad = [k for k in differ if k not in ALLOWED]
        if bad:
            raise SystemExit(f"{d.name}: files outside the table set differ: {bad}")
        old = json.loads(a["patches/db/char.dat.json"].read_text())["added"]
        new = json.loads(b["patches/db/char.dat.json"].read_text())["added"]
        keys = {k for o, n in zip(old, new) for k in o.keys() | n.keys() if o.get(k) != n.get(k)}
        if len(old) != len(new) or keys - LEARN:
            raise SystemExit(f"{d.name}: char.dat fields outside the learn list changed: {sorted(keys - LEARN)}")
        if "patches/db/magic.dat.json" in a:        # another lane's rows in the same pack must survive untouched
            om = {int(r["id"]): r for r in json.loads(a["patches/db/magic.dat.json"].read_text()).get("added") or []}
            nm = {int(r["id"]): r for r in json.loads(b["patches/db/magic.dat.json"].read_text()).get("added") or []}
            if any(nm.get(i) != r for i, r in om.items() if not band[0] <= i <= band[1]):
                raise SystemExit(f"{d.name}: a magic.dat row outside the DRPG band changed")
        same = sorted(k for k in a if k not in differ)
        receipt["packs"].append(dict(folder=d.name, source=str(d.parent), base_id=base, own=done["own"], rows=done["rows"],
                                     learn=done["learn"], learn_before=[[int(old[0].get(f"learn{i}_skill") or 0), int(old[0].get(f"learn{i}_level") or 0)]
                                                                        for i in range(1, int(old[0].get("learn_count") or 0) + 1)],
                                     gate=why, evility_gate=[eok, ewhy], title_gate=[tok, twhy],
                                     files=len(a), differ=differ, char_fields_changed=sorted(keys),
                                     identical_files=len(same), identical_sha256={k: sha(b[k]) for k in same},
                                     staged_sha256={k: sha(p) for k, p in b.items()}))
    mine = [i for p in receipt["packs"] for i in p["rows"]]
    if len(mine) != len(set(mine)):
        raise SystemExit("a leased skill id is written by two packs")
    receipt["counts"] = dict(packs=len(receipt["packs"]), own_links=sum(len(p["own"]) for p in receipt["packs"]),
                             own_rows=len(mine), identical_files=sum(p["identical_files"] for p in receipt["packs"]),
                             changed_files=sum(len(p["differ"]) for p in receipt["packs"]))
    (out / "STAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    if check is not None:
        from d5lib import stagecheck
        stagecheck.build_check(sv.fs, [mods / p["folder"] for p in receipt["packs"]], extra=check)
    bad = stagecheck.verify_stage(out) if check is not None else []
    if bad:
        raise SystemExit(f"staged files changed after the receipt: {bad[:5]}")
    print(json.dumps(receipt["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
