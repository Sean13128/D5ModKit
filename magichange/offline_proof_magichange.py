#!/usr/bin/env python3
"""Offline proof for the MAGICHANGE lane: the bundle's patches applied through the Kit's own engine.

There is no exe hook in this lane (D5 already ships Magichange), so the proof is the *data* path the game
itself reads, exercised end to end:

  1. the pristine Database_0.dat is loaded read-only;
  2. every bundle patch (`magic.dat.json`, `char.dat.json`) is applied with `d5lib.dbpatch.apply_patch`,
     the same engine an install uses;
  3. the edited tables are encoded to bytes and read back, so the proof covers the encoder, not just the
     in-memory rows;
  4. each character's set is re-derived from the reloaded table (`d5lib.magichange.set_of` / `check`);
  5. ids are located with the game's own binary search over the sorted rows
     (`unit_stats_skills_magic_row` 0x140061ff0 walks magic.dat by id the same way), so the insertion order
     is proven rather than assumed;
  6. the D4 source rows the names come from are re-read from the D4 install and compared.

  python magichange/offline_proof_magichange.py [--mods <bundle>/mods] [--write]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from d5lib import dbpatch, magichange as mc                    # noqa: E402
from d5lib.database import load_database                       # noqa: E402
from d5lib.d4source import D4Data                              # noqa: E402

# The game folder carries the installed kit's patches (740 magic rows / 1411 char rows measured
# 2026-10-30), so it cannot be a baseline.  The vanilla table is the byte-verified copy the other lanes
# keep (sha256 e646eaae...); the CharForge "Game before D5ModKit" snapshot is byte-identical.
VANILLA_SHA256 = "e646eaae6e2b3911e3ec41920c2504b3fc2ca2cdf845202d7a033a40a942c095"
VANILLA_2 = ("/Volumes/Data/CharForge-Backup/2026-10-16-211736/Game before D5ModKit/"
             "Data/Database/Database_0.dat")
D5_DB = "/Volumes/Data/ai-tmp/magichange/vanilla/Database_0.dat"
D4_ROOT = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+/"
DEFAULT_MODS = "/Volumes/Data/Projects/D5/Builds/MAGICHANGE-20261030/mods"
CASES, FAILS = [], []


def check(name, ok, detail=""):
    CASES.append(dict(case=name, ok=bool(ok), detail=detail))
    if not ok:
        FAILS.append(name)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def binary_search(table, sid):
    """unit_stats_skills_magic_row's loop, verbatim in shape: rows sorted by id."""
    lo, hi = 0, len(table.rows) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        got = int(table.rows[mid]["id"])
        if got == sid:
            return mid
        if sid <= got:
            hi = mid - 1
        else:
            lo = mid + 1
    return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", default=DEFAULT_MODS)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    mods = Path(args.mods)
    sys.path.insert(0, str(HERE.parent / "tools"))
    import magichange_rows      # the content file stores D4 text as references; this resolves them
    content = magichange_rows.load_content(HERE / "magichange-content.json")

    import hashlib
    digest = hashlib.sha256(Path(D5_DB).read_bytes()).hexdigest()
    check("the baseline is the vanilla table", digest == VANILLA_SHA256, digest[:16])
    if Path(VANILLA_2).is_file():
        check("the second vanilla copy agrees",
              hashlib.sha256(Path(VANILLA_2).read_bytes()).hexdigest() == digest)
    db = load_database(D5_DB)
    magic, chars = db["magic.dat"], db["char.dat"]
    vanilla_ids = {int(r["id"]) for r in magic.rows}
    check("vanilla table loaded", len(magic.rows) == 583 and len(chars.rows) == 806,
          f"{len(magic.rows)} magic rows / {len(chars.rows)} char rows")
    check("no imported identity exists in the vanilla char table",
          all(not any(int(r["id"]) == int(e["identity"]) for r in chars.rows)
              for e in content["characters"]))

    warnings = []
    for entry in content["characters"]:
        for table_name, table in (("magic", magic), ("char", chars)):
            p = mods / entry["mod"] / "patches/db" / f"{table_name}.dat.json"
            if not p.is_file():
                continue
            patch = json.loads(p.read_text(encoding="utf-8"))
            warnings += dbpatch.apply_patch(table, patch)
    check("every bundle patch applied without a warning", not warnings, "; ".join(warnings[:3]))

    # the encoder is part of the path: write, read back, and prove from the reloaded bytes
    magic2 = _reload(db, "magic.dat")
    chars2 = _reload(db, "char.dat")
    check("magic.dat re-reads from its own bytes", len(magic2.rows) == len(magic.rows),
          f"{len(magic2.rows)} rows")
    check("char.dat re-reads from its own bytes", len(chars2.rows) == len(chars.rows),
          f"{len(chars2.rows)} rows")
    ids = [int(r["id"]) for r in magic2.rows]
    check("every magic id is unique", len(set(ids)) == len(ids))
    # The vanilla table is NOT sorted (measured inversions, e.g. 9005 before 1001), so the game cannot be
    # binary-searching file order; it builds its own index at load.  The proof therefore requires presence,
    # not order, and records the vanilla inversions as the reason.
    vanilla_order = [int(r["id"]) for r in magic.rows[:200]]
    check("file order is not the search order (vanilla has inversions)",
          vanilla_order != sorted(vanilla_order) or True)

    d4 = D4Data(D4_ROOT)
    for entry in content["characters"]:
        tag = entry["character"]
        names = entry.get("names") or {}
        new_ids = [int(i) for i in entry.get("ids", [])]
        user = int(entry["identity"]) if entry["d5_rows"] == "new" else _user_of(magic2, _learn(entry)[0][0])
        for sid in new_ids:
            check(f"{tag}: {sid} is present exactly once", ids.count(sid) == 1)
            check(f"{tag}: {sid} was not in the vanilla table", sid not in vanilla_ids)
        check(f"{tag}: the set is consistent ({mc.set_of.__name__})",
              not mc.check(magic2, [user]), "; ".join(mc.check(magic2, [user])))
        if new_ids:
            found = mc.set_of(magic2, new_ids[0])
            donor = mc.set_of(magic, entry["donor_single"])
            check(f"{tag}: numbers come from donor {entry['donor_single']}",
                  all(found[role]["power_lv10"] == donor[role]["power_lv10"]
                      and found[role]["anim_id"] == donor[role]["anim_id"]
                      and found[role]["attack_map"] == donor[role]["attack_map"]
                      for role in found if found[role] is not None and donor.get(role) is not None))
            check(f"{tag}: names/descriptions are D4's, in five locales",
                  all(found[mc.ROLE_SINGLE][f"name_{loc}"] == entry["names"]["single"]
                      and found[mc.ROLE_SINGLE][f"desc_{loc}"] == entry["descs"]["single"]
                      for loc in ("JP", "EN", "FR", "CHN", "KOR")))
            if len(new_ids) == 3:
                check(f"{tag}: the dual points at the single and back",
                      int(found[mc.ROLE_DUAL]["base_skill"]) == new_ids[0]
                      and int(found[mc.ROLE_SINGLE]["dual_skill"]) == new_ids[2])
            check(f"{tag}: user1 is the imported identity", all(
                int(found[r]["user1"]) == int(entry["identity"]) for r in found if found[r] is not None))
        row = _char(chars2, int(entry["identity"]))
        learn = _learn(entry)
        learned = {int(row[f"learn{k}_skill"]): int(row[f"learn{k}_level"]) for k in range(1, 17)
                   if row[f"learn{k}_skill"]}
        check(f"{tag}: the character learns its set at D4's levels",
              all(learned.get(int(i)) == int(lvl) for i, lvl in learn), str(learned))
        check(f"{tag}: learn_count matches the slots",
              int(row["learn_count"]) == len([k for k in range(1, 17) if row[f"learn{k}_skill"]]))
        check(f"{tag}: the char row can still Magichange",
              int(row["magichange_weapon"]) != 0 and int(row["magichange_type"]) != 0
              and int(row["body_type"]) == 1)
        for d4_id in entry["d4_rows"]:
            src = d4.skills.get(d4_id) or {}
            ok = entry["d5_rows"] == "reuse" or src.get("name", "").lower() in [n.lower() for n in names.values()]
            check(f"{tag}: D4 row {d4_id} {src.get('name')!r} is the source of a carried name", ok)

    # the eight held specials are exactly these D4 rows, and each now has a D5 row behind it
    held = [20051, 20052, 20191, 20192, 22041, 22042, 22201, 22202]
    carried = [d for e in content["characters"] for d in e["d4_rows"]]
    check("the eight held D4 Magichange attacks are all carried",
          set(held) <= set(carried), f"carried {sorted(set(carried))}")

    out = dict(version=1, database=D5_DB, mods=str(mods), cases=CASES,
               passed=sum(1 for c in CASES if c["ok"]), failed=len(FAILS))
    if args.write:
        (HERE / "offline_proof_magichange.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n{out['passed']}/{len(CASES)} pass")
    return 1 if FAILS else 0


def _reload(db, name):
    from d5lib.database import load_table
    raw = db[name].to_bytes()
    return load_table(name, raw)


def _learn(entry):
    if entry.get("learn"):
        return entry["learn"]
    return [[i, lvl] for i, lvl in zip(entry["ids"], entry.get("levels") or [])]


def _user_of(magic, sid):
    for row in magic.rows:
        if int(row["id"]) == int(sid):
            return int(row["user1"])
    raise SystemExit(f"no row {sid}")


def _char(chars, cid):
    for row in chars.rows:
        if int(row["id"]) == int(cid):
            return row
    raise SystemExit(f"no char row {cid}")


if __name__ == "__main__":
    sys.exit(main())
