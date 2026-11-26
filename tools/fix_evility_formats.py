#!/usr/bin/env python3
"""Check / repair the evility descriptions in mod folders so the game can printf them (PTFIX C1).

  python tools/fix_evility_formats.py --check <mods dir> [--only A B ...] [--json out.json]
  python tools/fix_evility_formats.py --fix   <mods dir> [--only A B ...]

Skill.dat's `desc_<lang>` is the FORMAT string the game hands to its own sprintf_s, with the row value as
an argument (0x1407D22B0 line 78).  A malformed format kills the screen that draws it; see
`d5lib/textfmt.py` for the whole story.  `--fix` rewrites the JSON in place, so run it on a BUILD OUTPUT
(a bundle under Builds/), never on a source pack: the source pack should be regenerated with the helper.

Exit status: 1 when `--check` finds a bad description (so it can gate a bundle).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d5lib import textfmt      # noqa: E402

LANGS = ("JP", "EN", "FR", "CHN", "KOR")


def walk_mods(root, only=None):
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isdir(p) or not os.path.isfile(os.path.join(p, "mod.json")):
            continue
        if only and name not in only:
            continue
        yield name, p


def scan_mod(name, path):
    """{relpath: [problem, ...]} for every db patch of this mod that carries descriptions."""
    out = {}
    db = os.path.join(path, "patches", "db")
    if not os.path.isdir(db):
        return out
    for f in sorted(os.listdir(db)):
        # Skill.dat only: magic.dat descriptions use %s on purpose ('Fist:%sHitting 3 times...',
        # 435 vanilla rows), so a percent there is not automatically a defect.
        if f != "Skill.dat.json":
            continue
        p = os.path.join(db, f)
        try:
            with open(p, "r", encoding="utf-8-sig") as fh:
                patch = json.load(fh)
        except (ValueError, OSError):
            continue
        rows = list(patch.get("added") or []) + list((patch.get("rows") or {}).values())
        found, fixed = [], []
        for r in rows:
            for lang in LANGS:
                key = "desc_" + lang
                text = r.get(key) or ""
                if textfmt.bad_format(text):
                    found.append(dict(id=r.get("id"), field=key, old=text,
                                      new=textfmt.format_text(text)))
        if found:
            out[os.path.join("patches", "db", f)] = found
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("root", help="directory holding <mod>/mod.json folders (a bundle's mods/)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="report only; exit 1 when something is bad")
    g.add_argument("--fix", action="store_true", help="rewrite the patch JSON in place")
    ap.add_argument("--only", nargs="+", help="only these mod folder names")
    ap.add_argument("--json", help="write the findings to this file")
    a = ap.parse_args(argv)

    report, bad_mods = {}, 0
    for name, path in walk_mods(a.root, a.only):
        found = scan_mod(name, path)
        if not found:
            continue
        bad_mods += 1
        report[name] = {k: [dict(id=x["id"], field=x["field"], old=x["old"], new=x["new"]) for x in v]
                        for k, v in found.items()}
        n = sum(len(v) for v in found.values())
        print(f"{name}: {n} bad description(s) in {len(found)} file(s)")
        if a.fix:
            for rel, items in found.items():
                p = os.path.join(path, rel)
                with open(p, "r", encoding="utf-8-sig") as fh:
                    patch = json.load(fh)
                # rewrite by id, again from the file, so a repeated id is handled by its own text
                for r in list(patch.get("added") or []) + list((patch.get("rows") or {}).values()):
                    textfmt.fix_row(r, LANGS)
                with open(p, "w", encoding="utf-8") as fh:
                    json.dump(patch, fh, indent=1, ensure_ascii=False)
                    fh.write("\n")
            left = scan_mod(name, path)
            if left:
                print(f"  !! {name}: still bad after the rewrite: {left}")
                return 2
            print(f"  fixed {n}; re-check clean")
    if not report:
        print(f"{a.root}: no evility description needs changing")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, ensure_ascii=False)
        print(f"report: {a.json}")
    if a.check and bad_mods:
        print(f"{bad_mods} mod(s) with a malformed description -- unsafe for the multi-pass Skill Trainer path")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
