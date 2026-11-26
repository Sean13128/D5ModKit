#!/usr/bin/env python3
"""REPRO1: compare rebuilt packs against installed packs by CONTENT, per file class.

    D5Modkit/.venv-macos/bin/python tools/repro_compare.py BUILT_MODS INSTALLED_MODS OUT.json [--only A,B] [--jobs N]

Per pack -> IDENTICAL | LABELS (only mod.json text differs) | CONTENT.  File classes:
  mod.json  semantic JSON diff; leaf paths matching CONTENT_LEAF are content, the rest labels
            (a cut-in record and the assets.provenance it flips are labels: the DRPGCUTIN2 overlay
            writes them into the staged pack, not the importer)
  *.json    semantic diff (key order ignored); rows keyed by `id` when present
  *.lzs     animation bank: decoded-bytes fast path, else tools/bank_compare (key times + rendered pictures,
            texture / palette counts)
  *.png     decoded RGBA pixels
  others    sha256 (audio etc.)
Offline and read-only on both trees.
"""
import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
sys.dont_write_bytecode = True

CONTENT_LEAF = re.compile(r"^(source_import\.)?(leased_ids|source_ranks\.\d+\.(base|aptitudes|growth|id)"
                          r"|identity\.(character_id|body|palette|body_sha256)"
                          r"|signature_evility|source_id)")
CLASSES = ("IDENTICAL", "LABELS", "CONTENT")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def flat(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, f"{pre}.{k}" if pre else str(k))
    elif isinstance(o, list):
        if o and all(isinstance(x, dict) and "id" in x for x in o) and len({str(x["id"]) for x in o}) == len(o):
            for x in o:
                yield from flat(x, f"{pre}[id={x['id']}]")
        else:
            for i, x in enumerate(o):
                yield from flat(x, f"{pre}.{i}" if pre else str(i))
    else:
        yield pre, o


def json_diff(a, b):
    fa, fb = dict(flat(a)), dict(flat(b))
    return sorted(k for k in set(fa) | set(fb) if fa.get(k, "<absent>") != fb.get(k, "<absent>"))


def cmp_json(pa, pb, is_modjson):
    a, b = json.loads(Path(pa).read_text()), json.loads(Path(pb).read_text())
    if a == b:
        return "same", ""
    keys = json_diff(a, b)
    if not keys:
        return "label", "same fields, different list order or number type"
    if is_modjson:
        # A cut-in record is overlay metadata: DRPGCUTIN2 writes the cutin path/provenance/sha256 and the
        # assets.provenance flip into the staged pack's mod.json, not into the importer.  Label it, so a
        # rebuild that does not carry the overlay is not called different content.
        cutin = [k for k in keys if ".assets.files.cutin" in k]
        extra = set(cutin)
        if cutin:
            extra |= {k for k in keys if k.endswith(".assets.provenance")}
        content = [k for k in keys if CONTENT_LEAF.search(k) and k not in extra]
        labels = [k for k in keys if k not in content]
        note = " (cut-in metadata: label)" if cutin else ""
        return ("content" if content else "label"), f"{len(keys)} leaf path(s) ({len(content)} content){note}: " + "; ".join((content + labels)[:8])
    fields = sorted({re.sub(r"^.*?\[id=([^\]]*)\]\.?", "", k) or "row" for k in keys})
    ids = sorted({m.group(1) for k in keys for m in [re.search(r"\[id=([^\]]*)\]", k)] if m})
    return "content", f"{len(keys)} leaf path(s); rows {ids[:6]}; fields {fields[:8]}; first {keys[0]}"


def cmp_png(pa, pb):
    import numpy as np
    from PIL import Image
    a, b = Image.open(pa).convert("RGBA"), Image.open(pb).convert("RGBA")
    if a.size != b.size:
        return "content", f"size {a.size} vs {b.size}"
    x, y = np.asarray(a), np.asarray(b)
    n = int((x != y).any(axis=2).sum())
    return ("same", "") if n == 0 else ("content", f"{n} of {a.size[0] * a.size[1]} pixels differ")


def cmp_bank(pa, pb):
    from d5lib import gamefs
    import bank_compare as bc
    ra, rb = Path(pa).read_bytes(), Path(pb).read_bytes()
    da, db = gamefs.decode_member(ra), gamefs.decode_member(rb)
    if da == db:
        return "same", ""
    nbytes = (sum(1 for i in range(min(len(da), len(db))) if da[i] != db[i]) + abs(len(da) - len(db))) if len(da) < 4_000_000 else -1
    s = bc.summary(bc.anm.parse(da), bc.anm.parse(db))
    c = s["counts"]
    tex, pal = s["textures"], s["palettes"]
    bad = {k: v for k, v in c.items() if k != "same"}
    extra = f"; textures {tex[0]}/{tex[1]} palettes {pal[0]}/{pal[1]}" if tex[0] != tex[1] or pal[0] != pal[1] else ""
    if not bad and not extra:
        return "same", f"decoded bytes differ in {nbytes} byte(s), every animation same by key times and pictures"
    kind = "clock" if set(bad) <= {"timing"} and not extra else "art/structure"
    return "content", f"{kind}: {bad} of {sum(c.values())} animations; differing ids {s['differing'][:12]}{extra}"


def compare_pack(args):
    built, inst = Path(args[0]), Path(args[1])
    rec = dict(pack=built.name, files=[], cls="IDENTICAL")
    if not inst.is_dir():
        rec.update(cls="CONTENT", note="no installed pack")
        return rec
    A = {p.relative_to(built).as_posix(): p for p in built.rglob("*") if p.is_file() and p.name != ".DS_Store"}
    B = {p.relative_to(inst).as_posix(): p for p in inst.rglob("*") if p.is_file() and p.name != ".DS_Store"}
    worst = 0
    for rel in sorted(set(A) | set(B)):
        if rel not in B:
            v, d, k = "content", "rebuild only (installed pack lacks it)", "extra"
        elif rel not in A:
            v, d, k = "content", "installed only (rebuild lacks it)", "missing"
        else:
            pa, pb = A[rel], B[rel]
            ext = pa.suffix.lower()
            try:
                if pa.read_bytes() == pb.read_bytes():
                    continue
                if rel == "mod.json":
                    k = "mod.json"; v, d = cmp_json(pa, pb, True)
                elif ext == ".json":
                    k = "table"; v, d = cmp_json(pa, pb, False)
                    if v == "content" and "receipt" in pa.name:       # build receipts hold paths, notes and timestamps
                        v, k = "label", "receipt"
                elif ext == ".lzs":
                    k = "bank"; v, d = cmp_bank(pa, pb)
                elif ext == ".png":
                    k = "png"; v, d = cmp_png(pa, pb)
                else:
                    k = "audio" if "voice" in rel or ext in (".vag", ".ogg", ".wav", ".at9") else "other"
                    v, d = "content", f"sha256 {sha(pa)[:10]} vs {sha(pb)[:10]}"
            except Exception as e:                                      # noqa: BLE001
                v, d, k = "content", f"compare error {type(e).__name__}: {e}", "error"
        if v == "same":
            rec["files"].append(dict(file=rel, kind=k, verdict="same-content", detail=d))
            continue
        rec["files"].append(dict(file=rel, kind=k, verdict=v, detail=d))
        worst = max(worst, 2 if v == "content" else 1)
    rec["cls"] = CLASSES[worst]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("built"); ap.add_argument("installed"); ap.add_argument("out")
    ap.add_argument("--only"); ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    built, inst = Path(a.built), Path(a.installed)
    names = sorted(p.name for p in built.iterdir() if p.is_dir())
    if a.only:
        names = [n for n in names if n in set(a.only.split(","))]
    jobs = [(str(built / n), str(inst / n)) for n in names]
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        recs = list(ex.map(compare_pack, jobs))
    Path(a.out).write_text(json.dumps(recs, indent=1))
    for r in recs:
        print(r["pack"], r["cls"], len([f for f in r["files"] if f["verdict"] != "same-content"]), "differing file(s)")


if __name__ == "__main__":
    main()
