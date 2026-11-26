#!/usr/bin/env python3
"""SPECIALS2: census, staging and gates for the source special attacks of the D4 / D1C / DD2 packs (offline).

    python tools/specials2.py census GAME [--mods DIR] [--out DIR]     plans + CENSUS-<game>.md (read-only)
    python tools/specials2.py stage  GAME OUT_MODS [--mods DIR]        clone installed folders, write tables, gate

GAME = d4 | d1c | dd2.  --mods defaults to the installed kit's mods (read-only).  `stage` clones each folder
(APFS clone, no data copied), runs importers/specials2.apply on the clone, runs the skill gate and proves
every file outside the four table/metadata files byte-identical to the installed folder.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
BASE = Path("/Volumes/Data/Projects/D5")
INSTALLED = BASE / "Local/Installed D5ModKit/mods"
PREFIX = {"d4": "D4_", "d1c": "D1C_", "dd2": "DD2_"}
TABLE_FILES = {"mod.json", "patches/db/magic.dat.json", "patches/db/char.dat.json", "patches/skills/skills.json"}


def plans(game, mods):
    from d5lib.importers import specials2
    twins = specials2.reviewed_twins(game)
    return [specials2.plan_mod(game, mod, twins) for mod in sorted(Path(mods).iterdir())
            if mod.name.startswith(PREFIX[game]) and (mod / "mod.json").is_file()]


def census_md(game, ps):
    count = {}
    lines = [f"# SPECIALS2 census: {game.upper()} ({len(ps)} installed packs)", "",
             "| pack | source skill (level) | source SP / power / element / range / area | installed today | plan | D5 row | stand-in (motion) | labels |",
             "|---|---|---|---|---|---|---|---|"]
    for p in ps:
        if not p["entries"]:
            lines.append(f"| {p['mod']} | (no source skills{': ' + p['note'] if p.get('note') else ''}) | | "
                         f"{', '.join(str(k['d5_id']) + ' ' + k['name'] for k in p['kept']) or 'none'} | keep | | | |")
            count["none"] = count.get("none", 0) + 1
        for e in p["entries"]:
            count[e["label"]] = count.get(e["label"], 0) + 1
            s = e.get("source") or {}
            lines.append("| {} | {} {} ({}) | {} / {} / {} / {} / {} | {} | {} | {} | {} | {} |".format(
                p["mod"], e["src"], e.get("name") or "?", e["level"], s.get("sp"), s.get("power"), s.get("element"),
                s.get("range"), s.get("attack_map"), e.get("carried"), e["label"], e.get("d5_id") or "",
                f"{e['standin']} {e['standin_name']} ({e['motion']})" if e.get("standin") else e.get("motion", ""),
                "; ".join(e.get("notes") or [])))
    lines += ["", "Counts: " + ", ".join(f"{k} {v}" for k, v in sorted(count.items()))]
    return "\n".join(lines) + "\n", count


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    return {str(f.relative_to(root)): f for f in sorted(Path(root).rglob("*")) if f.is_file()}


def stage(game, out, mods):
    from d5lib.importers import specials2
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ps = plans(game, mods)
    todo = [p for p in ps if any(e["label"] in "EA" for e in p["entries"])]
    roots = [mods, out] + [d for d in (BASE / "Builds").glob("*/mods")]
    added = specials2.lease(todo, roots) if todo else 0
    d5 = specials2.context(game)[0]
    conc = specials2.context(game)[1]["conc"]
    receipt = dict(game=game, leases_added=added, power_fit={f: conc.fit(f) for f in (2, 3)}, packs={})
    for p in todo:
        src, dst = Path(mods) / p["mod"], out / p["mod"]
        if dst.exists():
            raise SystemExit(f"{dst} exists: stage into an empty folder")
        subprocess.run(["cp", "-cR", str(src), str(dst)], check=True)
        before = json.loads((dst / "patches/db/char.dat.json").read_text())
        specials2.apply(dst, p)
        a, b = tree(src), tree(dst)
        changed = sorted(k for k in b if k not in a or sha(a[k]) != sha(b[k]))
        lost = sorted(k for k in a if k not in b)
        outside = [k for k in changed if k not in TABLE_FILES] + lost
        after = json.loads((dst / "patches/db/char.dat.json").read_text())
        drift = [r["id"] for r0, r in zip(before.get("added") or [], after.get("added") or [])
                 if {k: v for k, v in r0.items() if not k.startswith("learn")} != {k: v for k, v in r.items() if not k.startswith("learn")}]
        old_ids = {int(r["id"]) for r in (json.loads((src / "patches/db/magic.dat.json").read_text()).get("added") or [])} \
            if (src / "patches/db/magic.dat.json").is_file() else set()
        new_ids = {int(r["id"]) for r in (json.loads((dst / "patches/db/magic.dat.json").read_text()).get("added") or [])} \
            if (dst / "patches/db/magic.dat.json").is_file() else set()
        problems = specials2.gate(dst, d5)
        if outside:
            problems.append(f"files changed outside the table set: {outside}")
        if drift:
            problems.append(f"char rows changed outside the learn fields: {drift}")
        if old_ids - new_ids:
            problems.append(f"installed magic.dat ids removed (a save may hold them): {sorted(old_ids - new_ids)}")
        receipt["packs"][p["mod"]] = dict(changed=changed, identical_files=len(b) - len(changed),
                                           rows_added=sorted(new_ids - old_ids), problems=problems)
    (out.parent / f"STAGE-RECEIPT-{game}.json").write_text(json.dumps(receipt, indent=1) + "\n")
    (out.parent / f"PLAN-{game}.json").write_text(json.dumps(ps, indent=1, ensure_ascii=False, default=str) + "\n")
    md, count = census_md(game, ps)
    (out.parent / f"CENSUS-{game}.md").write_text(md)
    bad = {k: v["problems"] for k, v in receipt["packs"].items() if v["problems"]}
    print(f"{game}: {len(todo)} packs staged, {added} ids leased, counts {count}, {len(bad)} with problems")
    for k, v in bad.items():
        print(" ", k, v)
    return 1 if bad else 0


def main(argv):
    cmd, game = argv[0], argv[1]
    mods = Path(argv[argv.index("--mods") + 1]) if "--mods" in argv else INSTALLED
    if cmd == "census":
        ps = plans(game, mods)
        md, count = census_md(game, ps)
        if "--out" in argv:
            out = Path(argv[argv.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / f"CENSUS-{game}.md").write_text(md)
            (out / f"PLAN-{game}.json").write_text(json.dumps(ps, indent=1, ensure_ascii=False, default=str) + "\n")
        else:
            print(md)
        print(count)
        return 0
    if cmd == "stage":
        return stage(game, argv[2], mods)
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
