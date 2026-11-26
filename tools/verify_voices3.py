"""VOICES3 gates: voice-only diff vs TEST18B, decode proof, coverage, references."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import numpy as np  # noqa: E402
from d5lib import sfx, sound  # noqa: E402

BASE = Path("/Volumes/Data/Projects/D5/Builds/LIVE5_TEST18B-20261030/mods")
NEW = Path("/Volumes/Data/ai-tmp/voices3/out/mods")
RECEIPT = Path("/Volumes/Data/ai-tmp/voices3/gate-report.json")
PEAK_LIMIT = 0.8501
WEAPON_SITUATIONS = [0, 1, 2, 4, 6, 11, 13]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel_files(root):
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def char_diff(old, new):
    a = json.loads(old.read_text())
    b = json.loads(new.read_text())
    diffs = []
    if set(a) != set(b):
        diffs.append("top-level keys")
    for key in ("added", "rows"):
        ga, gb = a.get(key), b.get(key)
        if isinstance(ga, list) and isinstance(gb, list):
            if len(ga) != len(gb):
                diffs.append(f"{key} length")
                continue
            for ra, rb in zip(ga, gb):
                for f in set(ra) | set(rb):
                    if ra.get(f) != rb.get(f):
                        diffs.append(f"{key}:{ra.get('id')}:{f}")
        elif isinstance(ga, dict) and isinstance(gb, dict):
            if set(ga) != set(gb):
                diffs.append(f"{key} ids")
                continue
            for k in ga:
                for f in set(ga[k]) | set(gb[k]):
                    if ga[k].get(f) != gb[k].get(f):
                        diffs.append(f"{key}:{k}:{f}")
        elif ga != gb:
            diffs.append(key)
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, default=BASE)
    ap.add_argument("--new", type=Path, default=NEW)
    ap.add_argument("--receipt", type=Path, default=RECEIPT)
    args = ap.parse_args()
    report = dict(base=str(args.base), packs=[], clips=0, problems=[], situations={})
    covered_all = {}
    for pack in sorted(p for p in args.new.iterdir() if p.is_dir()):
        old = args.base / pack.name
        entry = dict(pack=pack.name, problems=[])
        of, nf = rel_files(old), rel_files(pack)
        changed = [k for k in nf if k in of and sha(of[k]) != sha(nf[k])]
        same = [k for k in nf if k in of and sha(of[k]) == sha(nf[k])]
        removed = sorted(set(of) - set(nf))
        added = sorted(set(nf) - set(of))
        for k in changed:
            if k == "patches/db/char.dat.json":
                d = char_diff(of[k], nf[k])
                bad = [x for x in d if not x.endswith(":voice_id")]
                if bad:
                    entry["problems"].append(f"char.dat.json changed beyond voice_id: {bad[:5]}")
            elif not k.startswith("patches/voices/"):
                entry["problems"].append(f"non-voice file changed: {k}")
        for k in removed:
            if not k.startswith("patches/voices/"):
                entry["problems"].append(f"non-voice file removed: {k}")
        for k in added:
            if not k.startswith("patches/voices/"):
                entry["problems"].append(f"non-voice file added: {k}")
        entry.update(changed=len(changed), unchanged=len(same), added=len(added), removed=len(removed),
                     char_voice_id_diff=[x for x in char_diff(of["patches/db/char.dat.json"],
                                                               nf["patches/db/char.dat.json"])
                                         if x.endswith(":voice_id")])
        vj = pack / "patches/voices/voices.json"
        data = json.loads(vj.read_text())
        vid, watch = next(iter(data["voices"].items()))
        entry["voice_id"] = int(vid)
        lines = watch["lines"]
        files = set(p.name for p in (pack / "patches/voices").iterdir() if p.suffix == ".vag")
        covered = {c for l in lines for c in l["cats"]}
        covered_all[pack.name] = sorted(covered)
        missing_situations = [c for c in WEAPON_SITUATIONS if c not in covered]
        if missing_situations:
            entry["problems"].append(f"weapon-skill situations with no line: {missing_situations}")
        for l in lines:
            for lang, name in (l.get("files") or {}).items():
                if name not in files:
                    entry["problems"].append(f"line references missing file {name}")
        orphans = files - {n for l in lines for n in (l.get("files") or {}).values()}
        if orphans:
            entry["problems"].append(f"files not referenced by any line: {sorted(orphans)[:3]}")
        for name in sorted(files):
            try:
                raw = (pack / "patches/voices" / name).read_bytes()
                wav = sound.parse_se(raw)["wav"]
                pcm, rate = sfx.read_wav(wav)
                peak = float(np.max(np.abs(pcm))) if len(pcm) else 0.0
                if rate != 48000:
                    entry["problems"].append(f"{name}: rate {rate}")
                if not np.isfinite(pcm).all():
                    entry["problems"].append(f"{name}: non-finite samples")
                if peak > PEAK_LIMIT:
                    entry["problems"].append(f"{name}: peak {peak:.4f}")
                if len(pcm) < 1000:
                    entry["problems"].append(f"{name}: only {len(pcm)} samples")
            except Exception as ex:
                entry["problems"].append(f"{name}: decode failed {ex}")
        entry["clips"] = len(files)
        report["clips"] += len(files)
        report["problems"] += [f"{pack.name}: {p}" for p in entry["problems"]]
        report["packs"].append(entry)
    report["situations"] = covered_all
    print("packs:", len(report["packs"]), "clips:", report["clips"], "problems:", len(report["problems"]))
    for p in report["problems"][:40]:
        print("  !", p)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
