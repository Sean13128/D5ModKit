#!/usr/bin/env python3
"""SOURCEPREP1: classify the file opens a traced import wrote (see tools/source_trace/README.md).

    python -I tools/source_trace/classify.py TRACE_DIR OUT.json [--sums SHA256SUMS ...] [--kit KIT_ROOT]

Reads every `<pid>.log` (lines `kind<TAB>mode<TAB>path`, written by sitecustomize.py when TRACE_DIR is set),
drops reads inside the kit repo, the Python install and the output tree, and sorts the rest into
original-source / base-game / installed-kit / derived / machine-specific.  Paths are grouped by directory
(one row per directory + extension) so a build that opens 9000 files gives a readable table.
Writes only OUT.json; reads no game data (hashes come from the listed SHA256SUMS files)."""
import argparse, json, os, re, sys
from collections import defaultdict
from pathlib import Path

SRC = "/Volumes/Data/Projects/D5/Disgaea Source/"
RULES = [  # (prefix, class, game-or-label)
    (SRC + "Disgaea 4 Complete+", "original", "d4"),
    (SRC + "Disgaea 1 Complete Switch", "original", "d1c"),
    (SRC + "Disgaea 1 Complete PS4", "original", "d1c"),
    (SRC + "Disgaea 1 PC", "original", "d1 (pc voices)"),
    (SRC + "Disgaea D2 PS3", "original", "dd2"),
    (SRC + "Disgaea RPG JP", "original", "drpg"),
    (SRC + "Disgaea 5 Complete", "original", "d5"),
    (SRC + "Disgaea 2 PC", "original", "d2 pc"),
    (SRC, "original", "other"),
    ("/Volumes/Data/Projects/D5/Local/Installed D5ModKit", "installed-kit", ""),
    ("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/D5ModKit", "installed-kit", "live kit in the game folder"),
    ("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete", "base-game", "d5 live install"),
    ("/Volumes/Data/Projects/D5/Research/", "derived", "Research/ (lane output)"),
    ("/Volumes/Data/Projects/D5/Builds/", "derived", "Builds/"),
    ("/Volumes/Data/Projects/D5/Assets/", "derived", "Assets/"),
    ("/Volumes/Data/Projects/D5/Local/", "derived", "Local/ (non-installed)"),
    ("/Volumes/Data/Projects/D5/", "derived", "D5 project other"),
    ("/Volumes/Data/Character Forge Art", "derived", "Character Forge Art"),
    ("/Volumes/Data/CharForge-Backup", "derived", "CharForge-Backup"),
    ("/Volumes/Data/ai-tmp/", "derived", "ai-tmp lane output"),
    ("/Users/", "machine", "home folder"),
    ("/Volumes/", "machine", "other volume"),
]
SKIP = ("/Volumes/Data/Projects/D5/Local/python-macos/", "/System/", "/usr/", "/Library/", "/private/var/", "/dev/", "/etc/", "/opt/", "/Applications/", "/bin/", "/sbin/", "/var/")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("trace"); ap.add_argument("out")
    ap.add_argument("--sums", nargs="*", default=[]); ap.add_argument("--kit", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--skip", nargs="*", default=[], help="extra path prefixes to ignore (the run's own output tree)")
    a = ap.parse_args()
    sums = {}
    for f in a.sums:
        base = Path(f).parent
        for line in open(f, encoding="utf-8", errors="replace"):
            m = re.match(r"([0-9a-f]{64})\s+\*?(.+)$", line.rstrip("\n"))
            if m: sums[str((base / m.group(2)).resolve() if False else os.path.normpath(base / m.group(2)))] = m.group(1)
    seen = {}  # path -> (kind, modes)
    for log in sorted(Path(a.trace).glob("*.log")):
        for line in open(log, encoding="utf-8", errors="replace"):
            parts = line.rstrip("\n").split("\t", 2)
            if len(parts) != 3 or parts[0] not in ("open", "list"): continue
            kind, mode, p = parts
            if kind == "open" and any(c in mode for c in "wax+"): continue
            if not p.startswith("/") or p.endswith((".pyc", ".pyd", ".so", ".dylib")): continue
            p = os.path.normpath(p)
            if p.startswith(a.kit) or p.startswith("/Volumes/Data/Projects/D5/D5Modkit/") or p.startswith(SKIP) or any(p.startswith(s) for s in a.skip): continue
            seen[(kind, p)] = 1
    rows = defaultdict(lambda: dict(n=0, bytes=0, sample=None, hashed=0, hashes=[]))
    for (kind, p) in seen:
        cls, label = "machine", ""
        for pre, c, l in RULES:
            if p.startswith(pre): cls, label = c, l; break
        d = os.path.dirname(p) if kind == "open" else p
        if cls == "original":  # one row per game + first 2 dirs under the game root
            rel = p[len(SRC):].split("/")
            d = SRC + "/".join(rel[:min(len(rel) - 1 if kind == "open" else len(rel), 6)])
        if cls == "installed-kit" and "Local/Installed D5ModKit/" in p:  # one row per installed pack folder family, not per file
            rel = p.split("Installed D5ModKit/", 1)[-1].split("/")
            d = p.split("Installed D5ModKit/")[0] + "Installed D5ModKit/" + "/".join(rel[:2])
            if len(rel) > 1 and re.match(r"(D1C|D4|DD2|DRPG)_", rel[1]): d = d.rsplit("/", 1)[0] + "/<" + rel[1].split("_")[0] + " pack>"
        ext = os.path.splitext(p)[1].lower() if kind == "open" else "<dir listing>"
        r = rows[(cls, label, d, ext)]
        r["n"] += 1
        try:
            if kind == "open" and os.path.isfile(p): r["bytes"] += os.path.getsize(p)
        except OSError: pass
        r["sample"] = r["sample"] or p
        if p in sums:
            r["hashed"] += 1
            if len(r["hashes"]) < 3: r["hashes"].append([os.path.basename(p), sums[p]])
    out = [dict(cls=k[0], label=k[1], dir=k[2], ext=k[3], **v) for k, v in sorted(rows.items())]
    Path(a.out).write_text(json.dumps(out, indent=1))
    by = defaultdict(int)
    for r in out: by[r["cls"]] += r["n"]
    print(dict(by), len(out), "rows")

main()
