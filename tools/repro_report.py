#!/usr/bin/env python3
"""REPRO1: merge the per-batch comparison records of tools/repro_run.py into one per-pack table (CSV) and print counts.

    D5Modkit/.venv-macos/bin/python tools/repro_report.py RECORDS_DIR OUT.csv [--expect games.txt ...]

Later records (tag x, then dd2 'r') override earlier ones.  Cause tags name the lane whose later change or overlay the
importer does not reproduce.  Classes: IDENTICAL, LABELS (mod.json/receipt text only), CONTENT, NOT REBUILT.
"""
import argparse, collections, csv, glob, json, os
from pathlib import Path

CAUSES = {
    "FACE": "D1C face pictures: importer (FACEFIX1 RGBA cut-outs from start.dat[73]) is newer than the installed D1CFACE1B faces",
    "FACE+": "D1C face: importer writes a sixth colour face the installed pack lacks",
    "D4EVIL": "D4 signature evility rows added by hand/overlay (D4SIG1, EVILCAP1, EVILNEW2): Skill.dat/char.dat/evilities.json rows the importer does not write",
    "DRPGEVIL": "DRPG signature evility rows added later (DRPGEVIL1, INSTALL4 L1 packs): importer writes none",
    "ICONS": "DRPG outfit list-icon gfx ids differ (e.g. Bieko 116: importer 13173/13990, installed 13378/14195; a later icon re-lease, probably modshare's remap, is not in the importer)",
    "SHEETFIX1": "DRPG monster sheet banks: importer has SHEETFIX1 merge_satellites; installed predates it (staged Builds/SHEETFIX1 equals the rebuild)",
    "DD2ABIL": "DD2 reviewed abilities: only built with --with-reviewed-abilities",
    "NOBUILD": "importer cannot build the pack",
}


def reclass_file(x, pack):
    v, k, f, d = x["verdict"], x["kind"], x["file"], x["detail"]
    if v == "content" and "receipt" in f:
        return "label"
    if v == "content" and k == "mod.json":
        listed = d.split(": ", 1)[-1].split("; ")
        if all(p.startswith("specials2.") for p in listed[:3]) and "(0 content)" not in d and "table" not in d:
            return "label"        # specials2 record text; the rows themselves are tables and compare separately
    return v


def cause(x, pack):
    game, f, k = pack.split("_")[0], x["file"], x["kind"]
    if k == "png" and "face_" in f: return "FACE"
    if k == "extra" and "face_" in f: return "FACE+"
    if game == "D4" and any(s in f for s in ("Skill.dat", "char.dat", "evilities", "class_", "aliases")): return "D4EVIL"
    if game == "DRPG" and f.endswith("outfits.json"): return "ICONS"
    if game == "DRPG" and any(s in f for s in ("Skill.dat", "char.dat", "evilities")) or (game == "DRPG" and k == "mod.json"): return "DRPGEVIL"
    if game == "DRPG" and (k == "bank" or "parts_" in f or f.endswith(".anm")): return "SHEETFIX1"
    if game == "DD2": return "DD2ABIL"
    return f"unclassified {k}:{f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records"); ap.add_argument("out"); ap.add_argument("--expect", nargs="*", default=[])
    a = ap.parse_args()
    recs = {}
    for pat in ("d1c-a-*", "d4-a-*", "drpg-*", "dd2-a-*", "dd2-r-*", "*-x-*"):
        for f in sorted(glob.glob(f"{a.records}/{pat}.cmp.json")):
            for r in json.load(open(f)):
                recs[r["pack"]] = dict(r, src=os.path.basename(f))
    failed = {}
    for f in glob.glob(f"{a.records}/*.results.json"):
        for x in json.load(open(f))["results"]:
            if not x.get("built"):
                failed[x["mod_folder"]] = (x.get("error") or "")[:160]
    rows = []
    for p, r in sorted(recs.items()):
        files = [dict(x, verdict=reclass_file(x, p)) for x in r["files"]]
        diff = [x for x in files if x["verdict"] != "same-content"]
        w = max([0] + [{"label": 1, "content": 2}[x["verdict"]] for x in diff])
        cls = ["IDENTICAL", "DIFFERS ONLY IN LABELS", "DIFFERS IN CONTENT"][w]
        tags = sorted({cause(x, p) for x in diff if x["verdict"] == "content"})
        rows.append(dict(game=p.split("_")[0], pack=p, cls=cls, causes=" | ".join(tags),
                         content_files="; ".join(f"{x['kind']}:{x['file'].split('/')[-1]}" for x in diff if x["verdict"] == "content"),
                         label_files="; ".join(f"{x['kind']}:{x['file'].split('/')[-1]}" for x in diff if x["verdict"] == "label"),
                         banks_compared=sum(1 for x in files if x["kind"] == "bank"),
                         banks_bytes_differ_content_same=sum(1 for x in files if x["kind"] == "bank" and x["verdict"] == "same-content"),
                         first_content_detail=next((x["detail"][:200] for x in diff if x["verdict"] == "content"), "")))
    for p, why in sorted(failed.items()):
        if p not in recs:
            rows.append(dict(game=p.split("_")[0], pack=p, cls="NOT REBUILT", causes="NOBUILD", content_files="", label_files="",
                             banks_compared=0, banks_bytes_differ_content_same=0, first_content_detail=why))
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    cnt = collections.Counter((r["game"], r["cls"]) for r in rows)
    for k, v in sorted(cnt.items()): print(k, v)
    cc = collections.Counter(t for r in rows for t in r["causes"].split(" | ") if t)
    for k, v in cc.most_common(): print(v, k, "-", CAUSES.get(k, ""))
    print(len(rows), "packs")


if __name__ == "__main__":
    main()
