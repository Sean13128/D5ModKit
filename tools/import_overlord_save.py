#!/usr/bin/env python3
"""Import an Overlord-era save into a Kit + Overlord-package install.  Offline; copies only.

    python tools/import_overlord_save.py \
        --save  "/path/to/copy/Save_001.sav" \
        --out   "/path/to/copy/Save_001-imported.sav" \
        --source-skill "/path/to/overlord-era/Skill.dat" \
        --target-skill "/path/to/kit/Skill.dat" \
        --source-char  "/path/to/overlord-era/char.dat" \
        --target-char  "/path/to/kit/char.dat" \
        --packed-family 14080 --packed-family 1080 \
        --report report.json

`--source-skill` describes the table the save was written against (Overlord's 819-row Skill.dat);
`--target-skill` the table the install will have. The class files are optional but recommended: they
let the char.dat *row* number be recomputed from the class id.

The companion (`<out>.d5learn.json`) is written only when learned ids land past bitmap position 1000,
and binds itself to the output save's exact sha256 (d5lib.learned).  The game applies it on load.

Nothing here launches the game, installs anything, or writes a save under the live SaveData folder
unless --allow-live-paths is given.  The input file is never modified.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from d5lib import overlord_import, savegame   # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", required=True, help="the Overlord-era save (a copy)")
    ap.add_argument("--out", required=True, help="the imported save to write (a different file)")
    ap.add_argument("--source-skill", required=True, help="Skill.dat the save was written against")
    ap.add_argument("--target-skill", required=True, help="Skill.dat the install will have")
    ap.add_argument("--source-char", help="char.dat the save was written against")
    ap.add_argument("--target-char", help="char.dat the install will have")
    ap.add_argument("--packed-family", action="append", type=int, default=[],
                    help="a class family the target build packs in the mastery pool (repeatable)")
    ap.add_argument("--no-companion", action="store_true", help="do not write the learned companion")
    ap.add_argument("--report", help="write the report JSON here")
    ap.add_argument("--dry-run", action="store_true", help="inspect only; write nothing")
    ap.add_argument("--allow-live-paths", action="store_true",
                    help="permit --out inside the game's own SaveData folder (you should not need this)")
    a = ap.parse_args(argv)

    root = savegame.save_root()
    if not a.allow_live_paths:
        if overlord_import.under_live(root, a.out):
            ap.error(f"--out is inside the game's save folder ({root}); work on a copy, or pass "
                     f"--allow-live-paths deliberately")
        if overlord_import.under_live(root, a.save):
            print(f"note: --save is inside the live save folder; it is only read, and --out is a copy",
                  file=sys.stderr)
    if os.path.abspath(a.save) == os.path.abspath(a.out):
        ap.error("--out must be a different file from --save")

    if a.dry_run:
        plan = overlord_import.Plan(
            source_skill=open(a.source_skill, "rb").read(),
            target_skill=open(a.target_skill, "rb").read(),
            source_char=open(a.source_char, "rb").read() if a.source_char else None,
            target_char=open(a.target_char, "rb").read() if a.target_char else None,
            packed_families=a.packed_family).inspect(savegame.Save(a.save))
        report = plan.as_dict()
        print(json.dumps({k: report[k] for k in ("source_rows", "target_rows", "totals")}, indent=1))
        for note in report["notes"]:
            print("  " + note)
        return 0

    report, companion = overlord_import.convert(
        a.save, a.out, source_skill=a.source_skill, target_skill=a.target_skill,
        source_char=a.source_char, target_char=a.target_char,
        packed_families=a.packed_family, companion=not a.no_companion)
    print(json.dumps({k: report[k] for k in ("source_rows", "target_rows", "totals")}, indent=1))
    for note in report["notes"]:
        print("  " + note)
    print(f"  wrote {report['output']}")
    if companion:
        print(f"  companion {companion}")
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, ensure_ascii=False)
        print(f"  report {a.report}")
    lost = report["totals"]["unknown"] + report["totals"]["classes_unknown"]
    return 0 if not lost else 1


if __name__ == "__main__":
    sys.exit(main())
