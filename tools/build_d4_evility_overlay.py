#!/usr/bin/env python3
"""Write `d5lib/importers/d4-evility-overlay.json`: the reviewed D4 evility state, recorded once.

D4-FIX4 (coordinator decision 2, 2026-11-09).  The held D4 class/unique packs carry the evility state
the D4REV1-4 review (`Subprojects/Engine-Extensions/d4-review`, reviewed per evility against the D4 text,
the stored value and the D5 twin), PT1030DATA item 4 (unique evility links 8890/8891/8892) and CARRIERS2
(8187/8841/...) settled; the importer's own emission (`d4_extension_rows.json`) predates all of it, gives
the same exact row id to several packs and leaves class innate evilities unlinked.  Like the lease table,
the answer is read back from the held packs once and applied by the importer, never recomputed:

  per mod  skill_rows    patches/db/Skill.dat.json  (every added row is an evility row)
           behaviors     patches/evilities/evilities.json
           aliases       patches/evilities/aliases.json     (uniques: slot row -> D5 evility)
           class_alias   patches/classes/class_*.json "evility_alias"   (classes)
           char_links    char.dat rows: every field with "evil" in its name
           magic_ids     magic.dat ids below 20000 (builder-allocated adaptation rows), held ids

Run (offline, read-only; D5_INSTALLED_MODS names the held mods folder):
  python tools/build_d4_evility_overlay.py            # writes the table
  python tools/build_d4_evility_overlay.py --check    # exit 1 when stale or inconsistent
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path("/Volumes/Data/Projects/D5")
HELD = Path(os.environ.get("D5_INSTALLED_MODS")
            or BASE / "Local/mods-holding/20261108-PLAYTEST-RESET/mods")
OUT = ROOT / "d5lib/importers/d4-evility-overlay.json"
REVIEWED = BASE / "Subprojects/Engine-Extensions/d4-review/reviewed-rows"
PARKED = {"D4_Unique_510", "D4_Unique_520"}
# EVILGAP1c: held class packs the importer scope marks out (D5 ships the class): never installed, so their rows are
# owned by the uniques that need them (8211 Graceus, 8351 Reprachon, 8625 Main Hero B), not by these packs
OUT_OF_SCOPE = {"D4_Class_1100", "D4_Class_1130", "D4_Class_1210"}
ADDITIONS = ROOT / "d5lib/importers/d4-evility-additions.json"   # EVILGAP1: rows added after the held packs


def jload(p):
    return json.loads(Path(p).read_text())


def mod_state(m):
    st = {}
    for key, rel in (("skill_rows", "patches/db/Skill.dat.json"),
                     ("behaviors", "patches/evilities/evilities.json"),
                     ("aliases", "patches/evilities/aliases.json")):
        p = m / rel
        if p.is_file():
            doc = jload(p)
            st[key] = doc["added"] if key == "skill_rows" else doc
    cls = sorted(glob.glob(str(m / "patches/classes/class_*.json")))
    if cls and "evility_alias" in jload(cls[0]):
        st["class_alias"] = jload(cls[0])["evility_alias"]
    mg = m / "patches/db/magic.dat.json"
    if mg.is_file():
        # adaptation rows the builder allocates (first free id): pinned so independent builds never collide
        low = sorted(int(r["id"]) for r in jload(mg).get("added") or [] if int(r["id"]) < 20000)
        if low:
            st["magic_ids"] = low
    ch = m / "patches/db/char.dat.json"
    if ch.is_file():
        st["char_links"] = {str(r["id"]): {k: v for k, v in r.items() if "evil" in k}
                            for r in jload(ch).get("added") or []}
    return st


def merge_additions(mods):
    """Add the EVILGAP1 rows (tools/evilgap1_rows.py) on top of the held-pack state."""
    if not ADDITIONS.is_file():
        return
    for name, add in jload(ADDITIONS)["mods"].items():
        st = mods.setdefault(name, {})
        # carried_rows (EVILFX2): a pack with no held state keeps its installed rows, recorded verbatim
        st["skill_rows"] = list(st.get("skill_rows", [])) + add.get("carried_rows", []) + add["skill_rows"]   # [] keeps the empty Skill.dat file
        for k in ("refs", "requires"):           # EVILGAP1b: reference, not ownership
            if add.get(k):
                st[k] = add[k]
        st.setdefault("behaviors", {"evilities": {}})["evilities"].update(add.get("behaviors") or {})
        if add.get("aliases"):
            st["aliases"] = {**st.get("aliases", {}), **add["aliases"]}
        if add.get("class_alias"):      # EVILFX3: a class pack's alias map lives in its class json
            st["class_alias"] = {**st.get("class_alias", {}), **add["class_alias"]}
        for cid, fields in (add.get("char_links") or {}).items():
            st.setdefault("char_links", {}).setdefault(cid, {}).update(fields)
        if add.get("magic_ids"):        # builder-allocated adaptation rows, pinned to the installed pack's ids
            st["magic_ids"] = add["magic_ids"]
        if add.get("adaptations"):
            st["adaptations"] = list(st.get("adaptations", [])) + add["adaptations"]


def build():
    mods = {}
    for m in sorted(HELD.glob("D4_*")):
        if m.name in PARKED or m.name in OUT_OF_SCOPE or not (m / "mod.json").is_file():
            continue
        st = mod_state(m)
        if st:
            mods[m.name] = st
    merge_additions(mods)
    return {"schema": "d4-evility-overlay/1",
            "source": "generated by tools/build_d4_evility_overlay.py from the held D4 packs "
                      "(Local/mods-holding/20261108-PLAYTEST-RESET): D4REV1-4 review + PT1030DATA item 4 "
                      "+ CARRIERS2 rows; read by d5lib/importers/d4.py - never recomputed at build time",
            "mods": mods}


def problems(doc):
    """Internal consistency: unique Skill ids across packs; behaviors match the D4REV reviewed rows."""
    out = []
    own = collections.defaultdict(list)
    for name, st in doc["mods"].items():
        for r in st.get("skill_rows", []):
            own[int(r["id"])].append(name)
    for name, st in doc["mods"].items():       # a reference must name a required pack that owns the row
        for row, owner in (st.get("refs") or {}).items():
            if owner not in (st.get("requires") or []):
                out.append(f"{name}: references row {row} of {owner} but does not require it")
            if int(row) not in {int(r["id"]) for r in doc["mods"].get(owner, {}).get("skill_rows", [])}:
                out.append(f"{name}: references row {row}, which {owner} does not own")
    out += [f"Skill id {i} owned by {v}" for i, v in sorted(own.items()) if len(v) > 1]
    for p in glob.glob(str(REVIEWED / "**/D4_*.json"), recursive=True):
        name = Path(p).stem
        st = doc["mods"].get(name)
        if st is None:
            continue
        held = (st.get("behaviors") or {}).get("evilities", {})
        for k, v in jload(p)["evilities"].items():
            if held.get(k) != v:
                out.append(f"{name}: reviewed row {k} differs from the held pack")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    doc = build()
    # TEXTHASH-D4: game text is written as references (docs/TEXT_REFS.md), never as text
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hash_d4_text
    from d5lib.importers import _d4_source
    doc = hash_d4_text.hash_document(doc, _d4_source.text_pool_for_tools())
    bad = problems(doc)
    for b in bad:
        print("PROBLEM:", b)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.check:
        ok = OUT.is_file() and OUT.read_text() == text and not bad
        print("d4-evility-overlay.json is current" if ok else "d4-evility-overlay.json is stale or inconsistent")
        return 0 if ok else 1
    OUT.write_text(text)
    rows = sum(len(s.get("skill_rows", [])) for s in doc["mods"].values())
    print(f"wrote {OUT} ({len(doc['mods'])} mods, {rows} Skill rows, {len(bad)} problem(s))")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
