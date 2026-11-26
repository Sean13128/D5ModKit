#!/usr/bin/env python3
"""Attach the D4 Magichange attacks to their imported monsters inside D5's own Magichange mode.

One source: `magichange/magichange-content.json`.  For every character it writes

  <mod>/patches/db/magic.dat.json    the new set rows (only when the character has no D5 twin)
  <mod>/patches/db/char.dat.json     the learn slots (learn<N>_skill / learn<N>_level / learn_count)
  <mod>/mod.json                     a `source_import.adaptations` line naming the rows and what is adapted

It refuses to run when a row id is already taken (in the pristine table or by any other mod in the tree),
when the donor set's shape does not match the content's id count, when the binary-search order would break,
or when a description is not a printable single-integer format.  Read-only without --write.

  python tools/magichange_rows.py --mods /path/to/Builds/<bundle>/mods            (report)
  python tools/magichange_rows.py --mods /path/to/Builds/<bundle>/mods --write
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from d5lib import magichange as mc                     # noqa: E402
from d5lib.database import load_database               # noqa: E402
from d5lib.dbpatch import _row_values as jsonable_row   # noqa: E402

CONTENT = HERE.parent / "magichange/magichange-content.json"
# The game folder's Database_0.dat carries the installed kit's patches, so it is NOT a baseline: every
# id-collision and row-count check here must run against a byte-verified vanilla copy.  Both copies below
# are sha256 e646eaae... (806 char rows / 583 magic rows); the game folder is read only to prove which
# install the bundle lands on.
VANILLA_SHA256 = "e646eaae6e2b3911e3ec41920c2504b3fc2ca2cdf845202d7a033a40a942c095"
DEFAULT_DB = "/Volumes/Data/ai-tmp/magichange/vanilla/Database_0.dat"
LOCALES = ("JP", "EN", "FR", "CHN", "KOR")
# the fields a new magic.dat row is written with: the donor's whole row, so nothing is invented
SKIP = ("id", "user1", "user_count", "name_JP", "name_EN", "name_FR", "name_CHN", "name_KOR",
        "desc_JP", "desc_EN", "desc_FR", "desc_CHN", "desc_KOR", "dual_skill", "base_skill")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def text_problems(entry):
    out = []
    for role, desc in entry.get("descs", {}).items():
        if desc.count("%") != desc.count("%s"):
            out.append(f"{entry['character']} {role}: a % that is not %s is the crash class")
        if len(desc.encode("utf-8")) > 120:
            out.append(f"{entry['character']} {role}: description is {len(desc.encode('utf-8'))} B")
    for role, name in entry.get("names", {}).items():
        if len(name) > 31:
            out.append(f"{entry['character']} {role}: name is {len(name)} chars")
    return out


def claimed_ids(mods_root, skip_mod, table_ids):
    """ids already written by the pristine table or by any other mod's magic.dat patch"""
    taken = set(table_ids)
    owner = {}
    for mod in sorted(os.listdir(mods_root)):
        if mod == skip_mod:
            continue                      # this lane's own rows: re-running must be idempotent
        p = Path(mods_root) / mod / "patches/db/magic.dat.json"
        if not p.is_file():
            continue
        for row in read(p).get("added", []):
            taken.add(int(row["id"]))
            owner[int(row["id"])] = mod
    return taken, owner


def give_learn(char_row, sid, level):
    for k in range(1, 17):
        if int(char_row[f"learn{k}_skill"] or 0) == sid:
            char_row[f"learn{k}_level"] = int(level)
            break
    else:
        for k in range(1, 17):
            if not int(char_row[f"learn{k}_skill"] or 0):
                char_row[f"learn{k}_skill"] = sid
                char_row[f"learn{k}_level"] = int(level)
                break
        else:
            raise SystemExit(f"char {char_row['id']} already learns 16 skills")
    char_row["learn_count"] = sum(1 for j in range(1, 17) if int(char_row[f"learn{j}_skill"] or 0))


def load_content(path, only=None, pool=None):
    """The content file with its game-text references resolved (TEXTHASH-D4: the checked-in file holds SHA-256
    references, never D4's names or descriptions).  Only the entries in ``only`` (when given) are resolved, from
    ``pool`` or, without one, from the prepared D4 folder and the Disgaea 5 tables."""
    content = read(path)
    from d5lib.importers import _d4_source
    entries = [e for e in content["characters"] if only is None or e["mod"] in only]
    if any(_d4_source.has_refs(e) for e in entries):
        pool = pool if pool is not None else _d4_source.text_pool_for_tools()
        content = dict(content, characters=[pool.resolve_doc(e) for e in entries])
    return content


def apply(mods, database=DEFAULT_DB, content_path=CONTENT, write=False, only=None, adaptation=True,
          magic_table=None, pool=None):
    """The writer as a function: (problems, report).  `only` limits it to those mod folders (the importer
    passes the one pack it just built); the CLI passes none and keeps its bundle behaviour.

    ``magic_table`` (SOURCEPREP4-D4) is the original ``magic.dat`` parsed from the user's own base game
    through the kit's backup index; the importer passes it so no machine-specific vanilla copy is read.
    """
    args = argparse.Namespace(mods=str(mods), database=str(database), content=str(content_path), write=write)
    content = load_content(args.content, only, pool)
    if magic_table is None:
        db = load_database(args.database)          # read-only: neither copy is ever written
        if hashlib.sha256(Path(args.database).read_bytes()).hexdigest() != VANILLA_SHA256:
            raise SystemExit(f"{args.database} is not the vanilla table ({VANILLA_SHA256})")
        magic = db["magic.dat"]
    else:
        magic = magic_table
    table_ids = {int(r["id"]) for r in magic.rows}
    taken_by_others, owner = claimed_ids(args.mods, None, table_ids)

    problems, report = [], []
    for entry in content["characters"]:
        if only is not None and entry["mod"] not in only:
            continue
        mod_dir = Path(args.mods) / entry["mod"]
        char_patch_path = mod_dir / "patches/db/char.dat.json"
        if not char_patch_path.is_file():
            problems.append(f"{entry['mod']}: no char.dat patch")
            continue
        patch = read(char_patch_path)
        rows = [r for r in patch.get("added", []) if int(r["id"]) == int(entry["identity"])]
        if len(rows) != 1:
            problems.append(f"{entry['mod']}: expected one added char row {entry['identity']}, found {len(rows)}")
            continue
        char_row = rows[0]
        if not int(char_row.get(mc.MAGICHANGE_WEAPON) or 0) or not int(char_row.get(mc.MAGICHANGE_TYPE) or 0):
            problems.append(f"{entry['mod']}: char row cannot Magichange (weapon/type 0)")
        if int(char_row.get("body_type") or 0) != 1:
            problems.append(f"{entry['mod']}: body_type {char_row.get('body_type')} is not monster")
        problems += text_problems(entry)

        taken = set(table_ids) | {int(r["id"]) for mod in os.listdir(args.mods)
                                  if mod != entry["mod"] and (Path(args.mods) / mod / "patches/db/magic.dat.json").is_file()
                                  for r in read(Path(args.mods) / mod / "patches/db/magic.dat.json").get("added", [])}
        new_rows = []
        learn = entry.get("learn")
        if entry["d5_rows"] == "new":
            ids = [int(i) for i in entry["ids"]]
            if learn is None:
                learn = [[i, lvl] for i, lvl in zip(ids, entry.get("levels") or [])]
            for i in ids:
                if i in taken:
                    problems.append(f"{entry['mod']}: id {i} already taken" +
                                    (f" by {owner[i]}" if i in owner else " by the vanilla table or another mod"))
            planner = _Calc(magic, entry)
            donor = mc.set_of(magic, entry["donor_single"])
            shape = 3 if (donor[mc.ROLE_PAIR] is not None and donor[mc.ROLE_DUAL]) else 2
            if shape != len(ids):
                problems.append(f"{entry['mod']}: donor {entry['donor_single']} ships {shape} rows, "
                                f"content gives {len(ids)}")
            if len(problems) == 0 or not any(entry["mod"] in p for p in problems):
                new_rows = planner.rows()
            for row in new_rows:
                idx = mc.insert_index(magic, int(row["id"]))
                magic.rows.insert(idx, _clone(magic, row))
        for sid, level in learn:
            if int(sid) not in table_ids and not any(int(r["id"]) == int(sid) for r in new_rows):
                problems.append(f"{entry['mod']}: learn id {sid} is not a magic.dat row")
            give_learn(char_row, int(sid), int(level))

        # the audit runs against the table as it now stands, donor + new rows together
        user = int(entry["identity"]) if entry["d5_rows"] == "new" else _user_of(magic, learn[0][0])
        problems += [f"{entry['mod']}: {p}" for p in mc.check(magic, [user])]

        report.append(dict(mod=entry["mod"], character=entry["character"], identity=entry["identity"],
                           donor=entry["donor_single"], new_ids=[int(r["id"]) for r in new_rows],
                           learn=learn, user1=user))

        if args.write:
            if new_rows:
                mp = mod_dir / "patches/db/magic.dat.json"
                mpat = read(mp) if mp.is_file() else {"table": "magic.dat", "added": []}
                have = {int(r["id"]) for r in mpat.get("added", [])}
                mpat["added"] = [r for r in mpat.get("added", []) if int(r["id"]) not in
                                 {int(n["id"]) for n in new_rows}] + new_rows
                mpat["added"].sort(key=lambda r: int(r["id"]))
                dump(mp, mpat)
            dump(char_patch_path, patch)
            if adaptation:
                _adaptation(mod_dir, entry, new_rows)
    return problems, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", required=True)
    ap.add_argument("--database", default=DEFAULT_DB)
    ap.add_argument("--content", default=str(CONTENT))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    problems, report = apply(args.mods, args.database, args.content, args.write)
    if args.write:
        from d5lib.importers import _d4_source
        sys.path.insert(0, str(HERE))
        import hash_d4_text                      # the report names characters: written as references, not text
        doc = dict(version=1, strings_budget="descriptions carry one %s, D5's Magichange prefix",
                   characters=report, problems=problems)
        dump(HERE.parent / "magichange/rows.json",
             hash_d4_text.hash_document(doc, _d4_source.text_pool_for_tools(), extra={"character"}))
    for line in problems:
        print("PROBLEM", line)
    for r in report:
        print(f"{r['character']:<14} {r['mod']:<14} identity {r['identity']} donor {r['donor']} "
              f"new {r['new_ids']} learn {r['learn']} user1 {r['user1']}")
    if args.write:
        print("wrote", len(report), "characters")
    return 1 if problems else 0


def _user_of(magic, sid):
    for row in magic.rows:
        if int(row["id"]) == int(sid):
            return int(row["user1"])
    raise SystemExit(f"no row {sid}")


def _clone(table, fields):
    """a Table Row built from a plain dict, so the audit sees what the bundle will write"""
    row = table.new_row()
    for k, v in fields.items():
        row[k] = v
    return row


class _Calc:
    """the content entry -> the exact rows magichange.plan would build"""

    def __init__(self, table, entry):
        self.table, self.entry = table, entry

    def rows(self):
        roles = ([mc.ROLE_SINGLE, mc.ROLE_PAIR, mc.ROLE_DUAL] if len(self.entry["ids"]) == 3
                 else [mc.ROLE_SINGLE, mc.ROLE_PAIR])
        out = mc.plan(self.table, self.entry["donor_single"], ids=self.entry["ids"],
                      names=self.entry["names"], descs=self.entry["descs"],
                      user1=int(self.entry["identity"]),
                      levels=tuple(self.entry.get("levels") or [1] * len(roles)))
        return [jsonable_row(_clone(self.table, fields)) for _role, fields in out]


def _adaptation(mod_dir, entry, new_rows):
    mp = mod_dir / "mod.json"
    doc = read(mp)
    si = doc.setdefault("source_import", {})
    lines = si.setdefault("adaptations", [])
    if entry["d5_rows"] == "new":
        line = (f"Magichange attacks {', '.join(str(r['id']) for r in new_rows)}: adapted -> cloned from the "
                f"body template's own Magichange set {entry['donor_single']} (D5 numbers, animation, area and "
                f"element kept; D4 name and text carried). D4 source skills {entry['d4_rows']}.")
    else:
        line = (f"Magichange attacks {', '.join(str(i) for i, _l in entry['learn'])}: exact -> D5's own "
                f"Desco Magichange set (same names as D4 {entry['d4_rows']}), attached to the learnset.")
    if line not in lines:
        lines.append(line)
    dump(mp, doc)


if __name__ == "__main__":
    sys.exit(main())
