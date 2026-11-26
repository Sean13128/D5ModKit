#!/usr/bin/env python3
"""REPRO1 driver: rebuild installed packs from source in batches with tools/import_game.py, compare each batch to
the installed pack (tools/repro_compare.py), keep only the comparison records, delete the rebuilt packs.

    D5Modkit/.venv-macos/bin/python tools/repro_run.py GAME PACKS.txt WORKDIR RECORDS [--batch 12] [--tag t]
"""
import argparse, json, shutil, subprocess, sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
PY = sys.executable
INSTALLED = "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods"

ap = argparse.ArgumentParser()
ap.add_argument("game"); ap.add_argument("packs"); ap.add_argument("work"); ap.add_argument("records")
ap.add_argument("--batch", type=int, default=12); ap.add_argument("--tag", default="a"); ap.add_argument("--jobs", type=int, default=4)
ap.add_argument("--extra", default="", help="more import_game.py flags, space separated")
a = ap.parse_args()
packs = [x.strip() for x in Path(a.packs).read_text().split() if x.strip()]
rec = Path(a.records); rec.mkdir(parents=True, exist_ok=True)
for i in range(0, len(packs), a.batch):
    chunk = packs[i:i + a.batch]
    name = f"{a.game}-{a.tag}-{i // a.batch:03d}"
    if (rec / f"{name}.cmp.json").exists():
        continue
    work = Path(a.work) / name
    cmd = [PY, str(KIT / "tools/import_game.py"), a.game, "--only", ",".join(chunk), "--out", str(work),
           "--source-voices", "--source-specials", "--jobs", str(a.jobs), *a.extra.split()]
    log = subprocess.run(cmd, capture_output=True, text=True)
    (rec / f"{name}.log").write_text(log.stdout[-6000:] + log.stderr[-3000:])
    mods = work / a.game / "mods"
    subprocess.run([PY, str(KIT / "tools/repro_compare.py"), str(mods), INSTALLED, str(rec / f"{name}.cmp.json"), "--jobs", "4"],
                   check=False)
    res = work / a.game / "results.json"
    if res.exists():
        shutil.copy(res, rec / f"{name}.results.json")
    shutil.rmtree(work, ignore_errors=True)
    print(name, "done", flush=True)
