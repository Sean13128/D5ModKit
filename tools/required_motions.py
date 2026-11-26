#!/usr/bin/env python3
"""Write d5lib/data/required_motions.json from the clean Disgaea 5 banks (SHARKBANK1).

    python tools/required_motions.py [--out d5lib/data/required_motions.json] [--check]

Counts, per body kind (char.dat body_type), how many clean-game sprite banks hold each animation id and keeps the
ids present in at least `requiredmotions.THRESHOLD` of them.  `--check` re-derives the lists and fails when the
checked-in file differs.  Reads the clean game in `Disgaea Source/` (skillmotions.CLEAN_GAME); touches nothing else.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

from d5lib import database, requiredmotions, skillmotions  # noqa: E402


def derive():
    sv = skillmotions.Survey()
    rows = database.load_table("char.dat", sv.fs.read("Database/Database_0.dat/char.dat")).rows
    kinds = {}
    for r in rows:
        sp = int(r["sprite_id"] or 0)
        if sp:
            kinds.setdefault(sp, int(r["body_type"] or 0))
    banks = {0: {}, 1: {}}
    for sp, kind in sorted(kinds.items()):
        if kind not in banks:
            continue
        ids = sv.bank_ids("/nonexistent", sp)           # the clean bank anm{sprite}
        if ids is not None:
            banks[kind][sp] = sorted(ids)
    out = {"source": "clean Disgaea 5 Complete (Steam 803600) char.dat + ANM_HI_JP banks", "threshold": requiredmotions.THRESHOLD,
           "banks": {}, "required": {}, "common": {}, "counts": {}}
    for kind, name in ((0, "humanoid"), (1, "monster")):
        d = banks[kind]
        c = collections.Counter(i for v in d.values() for i in v)
        n = len(d)
        out["banks"][name] = n
        out["required"][name] = sorted(i for i, k in c.items() if k >= requiredmotions.THRESHOLD * n)
        out["common"][name] = sorted(i for i, k in c.items() if 0.5 * n <= k < requiredmotions.THRESHOLD * n)
        out["counts"][name] = {str(i): k for i, k in sorted(c.items()) if k >= 0.5 * n}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(requiredmotions.DATA))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    doc = derive()
    text = json.dumps(doc, indent=1) + "\n"
    if a.check:
        same = Path(a.out).read_text(encoding="utf-8") == text
        print("required_motions.json", "matches" if same else "DIFFERS from the clean game")
        return 0 if same else 1
    Path(a.out).write_text(text, encoding="utf-8")
    print(f"wrote {a.out}: monster {len(doc['required']['monster'])} ids of {doc['banks']['monster']} banks, "
          f"humanoid {doc['required']['humanoid']} of {doc['banks']['humanoid']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
