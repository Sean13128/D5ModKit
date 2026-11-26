#!/usr/bin/env python3
"""Stage imported packs with their own source-game voices (VOICE1): clone each pack, add `patches/voices/` and the
char.dat voice link, prove everything else byte-identical, run the voice gate.  Offline; installs nothing.

    python tools/build_source_voices.py --mods <base mods> [--mods <older base> ...] --out <bundle>/mods
        [--drpg-source "<Disgaea RPG JP (Android)>"] [--dd2-source "<Disgaea D2 PS3 disc>"]
        [--d1-source "<Disgaea 1 PC>"] [--only FOLDER_A,FOLDER_B] [--jobs 6]

DRPG_Core_* / DRPG_Sample_* packs use d5lib/drpgvoice, DD2_* packs d5lib/dd2voice, D1C_* packs d5lib/d1cvoice; a
game whose source folder is not named is skipped.

The base of a pack is the first --mods root that holds its folder (name the pending bundle first, the installed
mods last).  Re-run on a new base whenever another lane changes the DRPG packs: the voice pass is 90 s.

A pack whose character does not speak in its source game (VOICE2) is staged too: its char rows are linked to the
voice without lines (drpgvoice.SILENT_VOICE_ID) and mod.json says so; nothing else changes.

Writes <out>/<folder>/ per pack and <out>/../<tag>-build-<games>.json (per pack: looks, voice ids, clips, diff proof, gate).
Exit 1 when any pack fails its gate or its diff proof.
"""
import argparse
import hashlib
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

ALLOWED = ("patches/voices/", "patches/db/char.dat.json", "mod.json", "patches/outfits/outfits.json")     # the only paths a voice pass may touch


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _tree(root):
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file() and p.name != ".DS_Store"}


def diff_proof(src, dst):
    """Only voice files added; char.dat.json differs only in voice_id; mod.json only in source_import.voice."""
    a, b = _tree(src), _tree(dst)
    problems = [f"removed: {k}" for k in sorted(set(a) - set(b)) if not k.startswith(ALLOWED[0])]   # stale clips may go
    problems += [f"added outside patches/voices: {k}" for k in sorted(set(b) - set(a)) if not k.startswith(ALLOWED[0])]
    changed = [k for k in sorted(set(a) & set(b)) if _sha(a[k]) != _sha(b[k])]
    problems += [f"changed: {k}" for k in changed if not k.startswith(ALLOWED)]
    if "patches/db/char.dat.json" in changed:
        x, y = (json.loads(t["patches/db/char.dat.json"].read_text(encoding="utf-8-sig")) for t in (a, b))
        for r in y.get("added", []):
            r.pop("voice_id", None)
        for r in x.get("added", []):
            r.pop("voice_id", None)
        if x != y:
            problems.append("char.dat.json differs beyond voice_id")
    if "patches/outfits/outfits.json" in changed:
        x, y = (json.loads(t["patches/outfits/outfits.json"].read_text(encoding="utf-8")) for t in (a, b))
        x.pop("own_voice", None)
        y.pop("own_voice", None)
        if x != y:
            problems.append("outfits.json differs beyond own_voice")
    if "mod.json" in changed:
        x, y = (json.loads(t["mod.json"].read_text(encoding="utf-8")) for t in (a, b))
        x.get("source_import", {}).pop("voice", None)
        y.get("source_import", {}).pop("voice", None)
        if x != y:
            problems.append("mod.json differs beyond source_import.voice")
    art = [k for k in a if k.startswith(("files/", "patches/outfits/", "patches/characters/", "patches/classes/"))]
    return dict(ok=not problems, problems=problems, unchanged_files=len(set(a) & set(b)) - len(changed),
                art_files_identical=sum(1 for k in art if k in b and _sha(a[k]) == _sha(b[k])), art_files=len(art),
                changed=changed, added=len(set(b) - set(a)))


def _apply(dst, sources):
    from d5lib import drpgvoice
    if dst.name.startswith("DRPG_"):
        return drpgvoice.apply(dst, sources["drpg"], drpgvoice.source_manifest(sources["drpg"]))
    if dst.name.startswith("DD2_"):
        from d5lib import dd2voice
        return dd2voice.apply(dst, sources["dd2"])
    from d5lib import d1cvoice
    return d1cvoice.apply(dst, sources["d1c"])


def build_one(args):
    src, out, sources = Path(args[0]), Path(args[1]), args[2]
    from d5lib import drpgvoice
    dst = out / src.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".DS_Store"))
    try:
        receipt = _apply(dst, sources)
        ok, problems, stats = drpgvoice.voice_gate(dst)
        proof = diff_proof(src, dst)
    except Exception as exc:                                              # noqa: BLE001
        shutil.rmtree(dst, ignore_errors=True)
        return dict(mod=src.name, ok=False, error=f"{type(exc).__name__}: {exc}")
    if not receipt["voices"] and not receipt.get("silent"):          # nothing to add: do not stage an unchanged clone
        shutil.rmtree(dst)
        return dict(mod=src.name, ok=True, staged=False, donor_kept=receipt["donor_kept"])
    return dict(mod=src.name, base=str(src.parent), ok=ok and proof["ok"], staged=True, gate=dict(ok=ok, problems=problems, **stats),
                diff=proof, donor_kept=receipt["donor_kept"], silent=receipt.get("silent", []),
                voices=[dict({k: v[k] for k in ("row", "rows", "look", "voice_key", "source_id", "personalities",
                                                "unrouted_columns") if k in v},
                             voice_id=v["voice_id"], clips=len(v["clips"]), lines=v["lines"],
                             cues=sorted({c["cue"] for c in v["clips"] if c.get("cue")}),
                             unrouted=[u["cue"] for u in v.get("unrouted", []) if u.get("cue")])
                        for v in receipt["voices"]])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mods", type=Path, required=True, action="append")
    ap.add_argument("--drpg-source", type=Path)
    ap.add_argument("--dd2-source", type=Path)
    ap.add_argument("--d1-source", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--tag", default="VOICE1", help="prefix of the build report written beside --out")
    a = ap.parse_args(argv)
    only = set(a.only.split(",")) if a.only else None
    sources = {k: str(v) for k, v in (("drpg", a.drpg_source), ("dd2", a.dd2_source), ("d1c", a.d1_source)) if v}
    prefixes = tuple(p for k, ps in (("drpg", ("DRPG_Core_", "DRPG_Sample_")), ("dd2", ("DD2_",)), ("d1c", ("D1C_",)))
                     if k in sources for p in ps)
    found = {}
    for root in a.mods:
        for f in root.resolve().iterdir():
            if f.name.startswith(prefixes) and (f / "mod.json").is_file() and (only is None or f.name in only):
                found.setdefault(f.name, f)
    folders = [found[k] for k in sorted(found)]
    a.out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(a.jobs) as ex:
        results = list(ex.map(build_one, [(str(f), str(a.out), sources) for f in folders]))
    staged = [r for r in results if r.get("staged")]
    ids = [v["voice_id"] for r in staged for v in r["voices"]]
    summary = dict(packs=len(results), staged=len(staged), failed=[r["mod"] for r in results if not r["ok"]],
                   voices=len(ids), duplicate_voice_ids=sorted({i for i in ids if ids.count(i) > 1}),
                   clips=sum(v["clips"] for r in staged for v in r["voices"]),
                   silent_as_in_source=sorted(r["mod"] for r in staged if r.get("silent")),
                   donor_kept=[dict(k, mod=r["mod"]) for r in results for k in r.get("donor_kept", [])])
    (a.out.parent / f"{a.tag}-build-{'-'.join(sorted(sources))}.json").write_text(json.dumps(dict(summary=summary, results=results), indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 1 if summary["failed"] or summary["duplicate_voice_ids"] else 0


if __name__ == "__main__":
    sys.exit(main())
