#!/usr/bin/env python3
"""SOURCEPREP1: list every original-game file a set of traces opened, with size and SHA-256 (from the Disgaea Source sums).

    python -I tools/source_trace/originals.py OUT.json --sums SUMS... --trace NAME=DIR ...

Live Steam Disgaea 5 reads are matched to the clean depot copy by relative path (`Data/Anime/ANM_HI_EN.dat`).
A file with no sum is listed with sha256 null (DRPG client files are covered by the DRPG extracted/MANIFEST.json)."""
import argparse, json, os, re, sys
from pathlib import Path

SRC = "/Volumes/Data/Projects/D5/Disgaea Source/"
LIVE = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/"
CLEAN = SRC + "Disgaea 5 Complete (Steam 803600)/"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--sums", nargs="*", default=[])
    ap.add_argument("--trace", nargs="*", default=[]); a = ap.parse_args()
    sums = {}
    for f in a.sums:
        for line in open(f, encoding="utf-8", errors="replace"):
            m = re.match(r"([0-9a-f]{64})\s+\*?(?:\./)?(.+)$", line.rstrip("\n"))
            if m: sums[m.group(2)] = m.group(1)
    out = {}
    for spec in a.trace:
        name, d = spec.split("=", 1)
        for log in sorted(Path(d).glob("*.log")):
            for line in open(log, encoding="utf-8", errors="replace"):
                p = line.rstrip("\n").split("\t", 2)
                if len(p) != 3 or p[0] != "open" or any(c in p[1] for c in "wax+"): continue
                path = os.path.normpath(p[2]); rel = None; kind = None
                if path.startswith(SRC): rel, kind = path[len(SRC):], "original"
                elif path.startswith(LIVE) and "/D5ModKit/" not in path:
                    rel, kind = "Disgaea 5 Complete (Steam 803600)/" + path[len(LIVE):], "base-game (live install; hash of the clean depot copy)"
                if not rel or not os.path.isfile(path): continue
                if rel.startswith("Disgaea 5 Complete (Steam 803600)") and kind == "original": kind = "base-game (clean depot copy)"
                key = (name, rel)
                out[key] = dict(trace=name, rel=rel, kind=kind, size=os.path.getsize(path), sha256=sums.get(rel))
    json.dump(sorted(out.values(), key=lambda r: (r["trace"], r["rel"])), open(a.out, "w"), indent=1)
    print(len(out), "files")

main()
