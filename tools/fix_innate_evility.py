"""Give every D4 class pack's ranks their own innate (unique) evility -- C4.

A generic class's ranks show `char.dat evility1` as their UNIQUE evility (PT1027: "Cu Sith has no
evilities").  D4 class packs get this wrong in three ways, all of them visible in the installed set:

  * `evility1 = 0`, `evility_count = 0` while the pack already ships its own kind-1 source-4 Skill row
    (the class's unique evility) -- 24 classes.  Nothing to build: link the row.
  * `evility1` points at a 70xx "alias" row that DEDUP2 re-leased to a *different* class (the Armor
    Knight showed "Dodge Mastery", owned by class 14590) -- 5 classes.  Re-point it at the pack's own
    unique row.
  * no innate and no unique row at all -- 14 classes; those need the row built from the D4 source
    (mskill.dat) and are only *reported* here.

Deliberately NOT changed: `learn1_skill` (the class's own attack skill), voices, mastery, JobRank and
any row id (saves reference ids).  The unique row's own id is reused, so no lease is needed.

    python tools/fix_innate_evility.py --mods "<mods dir>" --profile <load_order.json> \
        --database "<installed Database_0.dat>" --out <dir> [--report receipt.json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import database  # noqa: E402


def class_family(mod_dir: Path):
    cj = mod_dir / "patches" / "classes"
    if not cj.is_dir():
        return None
    for f in sorted(cj.iterdir()):
        if f.name.startswith("class_") and f.suffix == ".json":
            try:
                return int(json.loads(f.read_text(encoding="utf-8"))["family"])
            except Exception:
                continue
    return None


def plan(mods: Path, order, skills):
    """[(mod, family, old_evility1, unique_row_id or None, reason)]"""
    owners = {}
    by_id = {}
    for r in skills.rows:
        owners.setdefault(r["owner"], []).append(r)
        by_id[r["id"]] = r
    out = []
    for name in order:
        if not name.startswith("D4_Class_"):
            continue
        mod_dir = mods / name
        char = mod_dir / "patches" / "db" / "char.dat.json"
        if not char.exists():
            continue
        fam = class_family(mod_dir)
        if fam is None:
            continue
        added = json.loads(char.read_text(encoding="utf-8")).get("added") or []
        if not added:
            continue
        ev1 = int(added[0].get("evility1") or 0)
        uniq = [r["id"] for r in owners.get(fam, []) if r["kind"] == 1 and r["source"] == 4]
        own = ev1 in by_id and by_id[ev1]["owner"] // 10 == fam // 10
        if own:
            reason = "already its own unique row"
        elif not uniq:
            reason = "no unique row of its own (needs one built from the D4 source)"
        elif ev1 == 0:
            reason = "no innate; the pack's own unique row exists -> link it"
        else:
            reason = (f"innate {ev1} belongs to class {by_id[ev1]['owner'] if ev1 in by_id else '?'} "
                      f"({by_id[ev1]['name_EN'] if ev1 in by_id else 'missing row'}) -> re-point at its own row")
        out.append((name, fam, ev1, uniq[0] if uniq else None, reason))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mods", required=True, type=Path, help="the installed mods directory")
    ap.add_argument("--profile", required=True, type=Path, help="load_order.json of the enabled set")
    ap.add_argument("--database", required=True, type=Path, help="the Database_0.dat the game loads")
    ap.add_argument("--out", type=Path, help="write the fixed mod folders here (default: report only)")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    order = json.loads(a.profile.read_text(encoding="utf-8"))
    skills = database.load_database(str(a.database))["Skill.dat"]
    rows = plan(a.mods, order, skills)
    fixed, pending = [], []
    for name, fam, ev1, uniq, reason in rows:
        if uniq is None or "already its own" in reason:
            if uniq is None:
                pending.append(dict(mod=name, family=fam, reason=reason))
            continue
        src = a.mods / name
        dst = (a.out / name) if a.out else None
        if dst is not None:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            char = dst / "patches" / "db" / "char.dat.json"
        else:
            char = src / "patches" / "db" / "char.dat.json"
        patch = json.loads(char.read_text(encoding="utf-8"))
        n = 0
        for r in patch.get("added") or []:
            if int(r.get("evility1") or 0) != uniq:
                r["evility1"] = uniq
                n += 1
            r["evility_count"] = 1
        if dst is not None:
            char.write_text(json.dumps(patch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        fixed.append(dict(mod=name, family=fam, evility1=uniq, was=ev1, rows_changed=n, reason=reason))
        print(f"{name}: evility1 {ev1} -> {uniq} ({n} rank rows)  [{reason}]")
    receipt = dict(fixed=fixed, pending=len(pending), pending_detail=pending,
                   note="unique row ids are the packs' own kind-1 source-4 Skill rows; no ids were leased")
    print(f"\nfixed {len(fixed)} pack(s); {len(pending)} need a unique row built from the D4 source")
    for p in pending:
        print("  pending:", p["mod"], p["family"])
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
        print("receipt:", a.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
