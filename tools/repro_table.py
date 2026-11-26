#!/usr/bin/env python3
"""REPROFIX2: merge the per-batch comparison records of tools/repro_run.py into one per-pack table (CSV).

    D5Modkit/.venv-macos/bin/python tools/repro_table.py RECORDS_DIR OUT.csv

Reads every ``*.cmp.json`` (tools/repro_compare.py output) and every ``*.results.json`` (batches whose packs were
not built) in RECORDS_DIR.  Classes: IDENTICAL, LABELS (mod.json/receipt text only), CONTENT, NOT REBUILT.
Every CONTENT file gets a cause tag naming the lane whose overlay or fix the importer does not reproduce, or the
finding it is.  Unknown differences print as ``unclassified`` with the file, so nothing hides behind a tag.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re


# cause tag -> one-line reason (kept in the CSV's `causes` column and printed as a legend)
CAUSES = {
    "FACE+": "rebuild writes a face picture the installed pack lacks (a class colour the install never got)",
    "FACE": "D1C face pictures differ (pixels)",
    "CARTER": "D1C cut-in anm10796 made from a story bust by the D1CFACE2 overlay script, outside the importer",
    "HOLD": "blank key times: the install holds BLANKKEYS1's pose, the rebuild leaves the keys blank",
    "CLOCK": "animation key times differ only in timing: the install's bank came from an out-of-band stage "
             "(MONATK1/BLANKKEYS1 source attack frames with the donor clock restored); the build paces them "
             "from the source (PT1030ANIM)",
    "ART": "animation pictures differ: an out-of-band art stage on the installed bank",
    "D4EVIL": "D4 signature-evility rows (D4SIG1/EVILCAP1/EVILNEW2) the importer does not write",
    "DRPGEVIL": "DRPG own-evility rows where the rebuild and the install differ: the install was staged by "
                "DRPGEVIL2; the rebuild applies the current overlay, which adds DRPGPARTY1's D4 sub evilities "
                "the install predates",
    "SAMPLE": "DRPG sample base: the current overlay lists it in samples_untouched, so the rebuild writes no own "
              "evilities; the installed pack carries the rows DRPGEVIL2 staged",
    "DRPGCUTIN": "DRPG cut-in metadata: the DRPGCUTIN2 overlay writes the cutin record and its provenance into "
                 "the staged pack's mod.json (in-pack files identical); the importer does not write it",
    "ICONS": "outfit list-icon gfx row ids (allocated at build time, re-leased by modshare after the install)",
    "SHEETFIX1": "DRPG monster sheet banks: importer has SHEETFIX1 merge_satellites, the install predates it",
    "DD2ABIL": "DD2 reviewed abilities (built only with --with-reviewed-abilities)",
    "D4SKILL": "the pack's own skill rows under different allocated ids (install 13029-13033, rebuild "
               "13003-13007; the rows are identical modulo id)",
    "D4VOICE": "char.dat voice_id: VOICESILENT1 staged the unit silent (5999 + 'silent, as in the source game'); "
               "the rebuild writes the borrowed D5 donor voice 2020",
    "OPTIONS": "importer_options / specials2 bookkeeping: the rebuild records the options and the specials "
               "kept/dropped list; the installed mod.json predates REPROFIX1",
    "RECEIPT": "build and voice receipts (paths, timestamps, notes)",
    "NOBUILD": "the importer cannot build the pack",
}


def _cutin_only(detail):
    """True when a mod.json content verdict is only the DRPGCUTIN2 cut-in metadata.

    repro_compare (before its cut-in carve-out) counted every ``leased_ids`` leaf as content, including
    ``assets.files.cutin.*`` and the ``assets.provenance`` flip it causes.  The detail lists the content leaves
    first; prove all of them are cut-in metadata before calling the file a label.
    """
    m = re.match(r"\d+ leaf path\(s\) \((\d+) content\)", detail)
    if not m:
        return False
    n = int(m.group(1))
    listed = [s.strip() for s in detail.split(":", 1)[1].split(";") if s.strip()]
    content = listed[:n]
    return bool(content) and len(content) == n and all(
        ".assets.files.cutin" in k or k.endswith(".assets.provenance") for k in content)


def reclass(x):
    """A content-verdict file that is really bookkeeping: receipts and the specials2 record text are labels."""
    v, k, f, d = x["verdict"], x["kind"], x["file"], x["detail"]
    if v == "content" and "receipt" in f:
        return "label"
    if v == "content" and k == "mod.json" and "(0 content)" in d:
        return "label"
    if v == "content" and k == "mod.json" and ("cut-in metadata" in d or _cutin_only(d)):
        return "label"
    return v


def cause(pack, x):
    game, f, k = pack.split("_")[0], x["file"], x["kind"]
    name = f.rsplit("/", 1)[-1]
    d = x.get("detail", "")
    if k == "extra" and name.startswith("face_"):
        return "FACE+"
    if k == "png" and name.startswith("face_"):
        return "FACE"
    if game == "D1C" and name == "anm10796.lzs":
        return "CARTER"
    if k == "mod.json" and "cut-in metadata" in d:
        return "DRPGCUTIN"
    if game == "D4" and (name in ("magic.dat.json", "skills.json") or "learn" in d):
        return "D4SKILL"
    if game == "D4" and "voice_id" in d:
        return "D4VOICE"
    if game == "D4" and any(s in f for s in ("Skill.dat", "char.dat", "evilities", "aliases", "class_")):
        return "D4EVIL"
    if game == "D4" and k == "bank":
        return "HOLD" if all(i in d for i in ("2077", "3077", "4017")) else "ART"
    if game == "DRPG" and f.endswith("outfits.json"):
        return "ICONS"
    if game == "DRPG" and ("signature_evility" in d or any(s in f for s in ("Skill.dat", "char.dat", "evilities"))):
        return "SAMPLE" if pack.startswith("DRPG_Sample_") else "DRPGEVIL"
    if game == "DRPG" and (k == "bank" or "parts_" in f or f.endswith(".anm")):
        return "SHEETFIX1"
    if game == "DD2":
        if k == "bank" and all(i in d for i in ("2077", "3077", "4017")):
            return "HOLD"
        return "DD2ABIL"
    if game == "D1C" and k == "bank":
        return "CLOCK" if d.startswith("clock") else "ART"
    return f"unclassified {k}:{f}"


def label_cause(pack, x):
    """Why a label-only file differs: the manifest/specials bookkeeping or a receipt."""
    k, f, d = x["kind"], x["file"], x.get("detail", "")
    name = f.rsplit("/", 1)[-1]
    if k == "mod.json" and ("cut-in metadata" in d or _cutin_only(d)):
        return "DRPGCUTIN"
    if "receipt" in name:
        return "RECEIPT"
    if k == "mod.json":
        return "OPTIONS"
    return f"label:{name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("out")
    a = ap.parse_args()
    recs = {}
    for f in sorted(glob.glob(os.path.join(a.records, "*.cmp.json"))):
        for r in json.load(open(f)):
            recs[r["pack"]] = dict(r, src=os.path.basename(f))
    failed = {}
    for f in glob.glob(os.path.join(a.records, "*.results.json")):
        doc = json.load(open(f))
        for x in doc.get("results", []):
            if not x.get("built"):
                failed[x["mod_folder"]] = (x.get("error") or "not built, no error")[:200]
    rows = []
    for p, r in sorted(recs.items()):
        files = [dict(x, verdict=reclass(x)) for x in r["files"]]
        diff = [x for x in files if x["verdict"] != "same-content"]
        rank = max([0] + [{"label": 1, "content": 2}[x["verdict"]] for x in diff])
        cls = ["IDENTICAL", "LABELS", "CONTENT"][rank]
        tags = sorted({cause(p, x) for x in diff if x["verdict"] == "content"})
        ltags = sorted({label_cause(p, x) for x in diff if x["verdict"] == "label"})
        rows.append(dict(
            game=p.split("_")[0], pack=p, cls=cls, causes=" | ".join(tags),
            label_causes=" | ".join(ltags),
            content_files="; ".join(f"{x['kind']}:{x['file'].rsplit('/', 1)[-1]}"
                                    for x in diff if x["verdict"] == "content"),
            label_files="; ".join(f"{x['kind']}:{x['file'].rsplit('/', 1)[-1]}"
                                  for x in diff if x["verdict"] == "label"),
            banks_compared=sum(1 for x in files if x["kind"] == "bank"),
            banks_same_content=sum(1 for x in files if x["kind"] == "bank" and x["verdict"] == "same-content"),
            detail=next((x["detail"][:240] for x in diff if x["verdict"] == "content"), "")))
    for p, why in sorted(failed.items()):
        if p not in recs:
            rows.append(dict(game=p.split("_")[0], pack=p, cls="NOT REBUILT", causes="NOBUILD", label_causes="",
                             content_files="", label_files="", banks_compared=0, banks_same_content=0, detail=why))
    if not rows:
        raise SystemExit("no records")
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    per = collections.Counter((r["game"], r["cls"]) for r in rows)
    games = sorted({r["game"] for r in rows})
    print("game   identical  labels  content  not rebuilt  total")
    for g in games:
        print(f"{g:6}", "  ".join(f"{per[(g, c)]:9}" for c in
                                  ("IDENTICAL", "LABELS", "CONTENT", "NOT REBUILT")),
              f"{sum(v for (gg, _), v in per.items() if gg == g):8}")
    print(f"{'all':6}", "  ".join(f"{sum(v for (_, cc), v in per.items() if cc == c):9}"
                                  for c in ("IDENTICAL", "LABELS", "CONTENT", "NOT REBUILT")),
          f"{len(rows):8}")
    tagc = collections.Counter(t for r in rows for t in r["causes"].split(" | ") if t)
    print("\ncontent causes:")
    for t, n in tagc.most_common():
        print(f"{n:4} {t:12} {CAUSES.get(t, '(see the pack rows)')}")
    ltagc = collections.Counter(t for r in rows for t in r["label_causes"].split(" | ") if t)
    print("\nlabel-only causes:")
    for t, n in ltagc.most_common():
        print(f"{n:4} {t:12} {CAUSES.get(t, '(see the pack rows)')}")
    print(f"\n{len(rows)} packs; table: {a.out}")


if __name__ == "__main__":
    main()
