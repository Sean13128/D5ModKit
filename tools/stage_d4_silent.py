#!/usr/bin/env python3
"""VOICESILENT1: stage the two D4 packs whose source game has no voice for them as SILENT (offline, installs nothing).

    python tools/stage_d4_silent.py OUT_DIR --d4-source "<Disgaea 4 Complete+ folder with Data/>" BASE_MODS [BASE_MODS ...]

Sean 2026-11-12 15:29: Politan (D4 610) and Pringer X (D4 210) have no voice in Disgaea 4, so they are silent like
the source; the borrowed D5 donor voice (voice 2020) is removed and the pack says "silent, as in the source game".
The mechanism is VOICE2's: drpgvoice.link_silent (char rows -> SILENT_VOICE_ID 5999, mod.json source_import.voice =
"silent, as in the source game (...)", which build_tracker.apply_voice_silent reads as "n/a (silent in source)") and
drpgvoice.voice_gate (which knows silent packs).

Before touching a pack the stager re-checks the premise in the original game: the pack's D4 voice group (the char row's
voice_group_base) must be absent from the voice table AND the voice archive of both dubs.  If the source DOES voice the
character the stager stops (exit 2) and writes nothing for it.

Each pack is cloned from the FIRST base that has it, and only two files may differ: mod.json (source_import.voice only,
indent and final newline kept) and patches/db/char.dat.json (voice_id only).  The bases are only read.
Writes OUT_DIR/mods/<pack>/ and OUT_DIR/STAGE-RECEIPT.json.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True

LANE = "VOICESILENT1"
PACKS = (("D4_Unique_610", 610), ("D4_Unique_210", 210))      # folder, D4 char row
ALLOWED = ("mod.json", "patches/db/char.dat.json")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_voice(d4root, row_id):
    from d5lib import d4voices
    return d4voices.source_voice_facts(d4root, row_id)


def voiced(facts):
    from d5lib import d4voices
    return d4voices.source_has_voice(facts)


def why_text(facts):
    from d5lib import d4voices
    return d4voices.silent_why(facts)


def diff_proof(base, dest):
    a = {p.relative_to(base).as_posix(): p for p in base.rglob("*") if p.is_file() and p.name != ".DS_Store"}
    b = {p.relative_to(dest).as_posix(): p for p in dest.rglob("*") if p.is_file() and p.name != ".DS_Store"}
    problems = [f"removed: {k}" for k in sorted(set(a) - set(b))] + [f"added: {k}" for k in sorted(set(b) - set(a))]
    changed = [k for k in sorted(set(a) & set(b)) if sha(a[k]) != sha(b[k])]
    problems += [f"changed outside {ALLOWED}: {k}" for k in changed if k not in ALLOWED]
    if "patches/db/char.dat.json" in changed:
        x, y = (json.loads(t["patches/db/char.dat.json"].read_text(encoding="utf-8-sig")) for t in (a, b))
        for doc in (x, y):
            for r in doc.get("added", []):
                r.pop("voice_id", None)
        if x != y:
            problems.append("char.dat.json differs beyond voice_id")
    if "mod.json" in changed:
        x, y = (json.loads(t["mod.json"].read_text(encoding="utf-8")) for t in (a, b))
        x.get("source_import", {}).pop("voice", None)
        y.get("source_import", {}).pop("voice", None)
        if x != y:
            problems.append("mod.json differs beyond source_import.voice")
    return dict(ok=not problems, problems=problems, files=len(a), identical=len(set(a) & set(b)) - len(changed), changed=changed)


def main(argv, packs=PACKS, source_voice_fn=source_voice):
    from d5lib import drpgvoice
    args = list(argv)
    if "--d4-source" not in args:
        raise SystemExit(__doc__)
    i = args.index("--d4-source")
    d4root = Path(args[i + 1])
    del args[i:i + 2]
    out, bases = Path(args[0]), [Path(b).resolve() for b in args[1:]]
    (out / "mods").mkdir(parents=True, exist_ok=True)

    def snap(b):
        return {f"{f}/{p.relative_to(b / f).as_posix()}": sha(p) for f, _r in packs for p in (b / f).rglob("*") if p.is_file()}
    before = {str(b): snap(b) for b in bases}
    receipt = dict(lane=LANE, bases=[str(b) for b in bases], d4_source=str(d4root), packs=[])
    voiced_packs = []
    for folder, row_id in packs:
        facts = source_voice_fn(d4root, row_id)
        if voiced(facts):
            voiced_packs.append(folder)
            print(f"STOP {folder}: the D4 source DOES hold voice lines for group {facts['groups']}: {facts['per_lang']}")
            receipt["packs"].append(dict(folder=folder, source=facts, staged=False, stopped="source has voice"))
            continue
        base = next((b / folder for b in bases if (b / folder / "mod.json").is_file()), None)
        if base is None:
            raise SystemExit(f"{folder}: in no base")
        dest = out / "mods" / folder
        if dest.exists():
            raise SystemExit(f"{dest} exists; stage into an empty folder")
        subprocess.run(["cp", "-cR", str(base), str(dest)], check=True)
        changed = drpgvoice.link_silent(dest, why_text(facts), keep_layout=True)
        ok, problems, stats = drpgvoice.voice_gate(dest)
        proof = diff_proof(base, dest)
        if not (ok and proof["ok"]):
            raise SystemExit(f"{folder}: gate {problems} diff {proof['problems']}")
        label = json.loads((dest / "mod.json").read_text(encoding="utf-8"))["source_import"]["voice"]
        receipt["packs"].append(dict(folder=folder, base=str(base.parent), source=facts, staged=True, label=label,
                                     voice_id_changes={str(k): list(v) for k, v in changed.items()},
                                     gate=dict(ok=ok, problems=problems, **stats), diff=proof))
        print(folder, "->", {k: v for k, v in changed.items()}, "differ:", proof["changed"])
    if before != {str(b): snap(b) for b in bases}:
        raise SystemExit("a base changed during staging")
    receipt["bases_unchanged"] = True
    (out / "STAGE-RECEIPT.json").write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    print(sum(1 for p in receipt["packs"] if p["staged"]), "packs staged;", len(voiced_packs), "stopped")
    return 2 if voiced_packs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
