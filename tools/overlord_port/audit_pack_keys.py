"""Audit every Overlord pack's patch files: is each `rows` key a row index or a column value?

The converted Overlord packs are produced by ``dbpatch.diff_table``, whose `rows` keys are indices into
the vanilla table. That is only safe while the table is still in that order when the patch is applied.
This tool settles, per (mod, table), what space the keys are in, with evidence that does not depend on
the answer:

  * ``index_valid``  -- is every key a row that exists in the vanilla table?
  * ``id_valid``     -- is every key a value of the identity column?
  * ``aligned``      -- does every key's vanilla row carry the same identity as the row at that index in
                        his release file (the table the pack was diffed from)?
  * ``content_ok``   -- applied positionally to vanilla, does each edited row end up carrying *his* values?
  * ``fresh_diff``   -- does re-diffing vanilla against his release reproduce the pack's `rows` keys?

The verdict is ``index`` only when the positional reading is the one that reproduces his file; ``id``
only when the key space is the identity column (the pack was authored by id, not diffed from a table).

    python tools/overlord_port/audit_pack_keys.py --mods <bundle>/mods \
        --release "<his extracted release>" [--vanilla Database_0.dat] [--json receipt.json] \
        [--write-expect] [--fixture tests/fixtures/overlord_row_identity.json]

``--write-expect`` writes the `expect` block into each index-keyed patch (the guard the Kit applies), so a
pack carries the identity of the rows it was written against. ``--fixture`` writes the independent
witness the row-identity test uses: {mod: {table: {"by": ..., "rows": {index: identity}}}}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from d5lib import database, dbpatch   # noqa: E402

DEFAULT_VANILLA = "/Volumes/Data/ai-tmp/charorder/vanilla/Database_0.dat"
DEFAULT_RELEASE = "/Volumes/Data/ai-tmp/claude/overlord-v3"
RELEASE_SUBDIR = os.path.join("mods", "Overlord", "Database", "Database_0")


def overlord_mods(mods_dir):
    return [m for m in sorted(os.listdir(mods_dir)) if m.startswith("Overlord")]


def patch_files(mods_dir):
    """[(mod, member, path)] for every Overlord db patch, in folder order."""
    out = []
    for mod in overlord_mods(mods_dir):
        d = os.path.join(mods_dir, mod, "patches", "db")
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith(".json"):
                out.append((mod, name[:-5], os.path.join(d, name)))
    return out


def identity_map(table):
    """(column spec, {index: identity}) for a table: `id`, or `<col>#ord` when the column repeats."""
    by = dbpatch._expect_column(table)
    if not by:
        return None, {}
    return by, dbpatch.row_identities(table, by) or {}


def audit_one(mods_dir, release_dir, vanilla_db, mod, member, path):
    with open(path, encoding="utf-8") as f:
        patch = json.load(f)
    rows = patch.get("rows") or {}
    entry = {"mod": mod, "member": member, "patch": os.path.relpath(path, mods_dir),
             "key": patch.get("key"), "changed_rows": len(rows),
             "added": len(patch.get("added") or []),
             "inserted": sum(len(i.get("rows") or []) for i in patch.get("insert") or [])}
    if not rows:
        entry["space"] = "none"
        entry["verdict"] = "no row edits"
        return entry
    vanilla = vanilla_db[member]
    his_path = os.path.join(release_dir, RELEASE_SUBDIR, member)
    his = database.load_table(member, open(his_path, "rb").read()) if os.path.exists(his_path) else None

    keys = sorted(int(k) for k in rows)
    entry["keys"] = len(keys)
    entry["index_valid"] = all(0 <= k < len(vanilla.rows) for k in keys)
    by, vident = identity_map(vanilla)
    entry["identity_by"] = by
    ids = set()
    if by:
        col = by.split("#")[0]
        ids = {r[col] for r in vanilla.rows}
    entry["id_valid"] = sum(1 for k in keys if k in ids) if ids else 0
    entry["id_missing"] = sorted(k for k in keys if ids and k not in ids)

    if his is not None:
        hby, hident = identity_map(his)
        entry["aligned"] = all(str(vident.get(k)) == str(hident.get(k)) for k in keys
                              if k < len(vanilla.rows) and k < len(his.rows))
        mismatched = [(k, vident.get(k), hident.get(k)) for k in keys
                      if k < len(vanilla.rows) and k < len(his.rows)
                      and str(vident.get(k)) != str(hident.get(k))]
        entry["aligned_mismatches"] = mismatched[:5]
    else:
        entry["aligned"] = None

    # apply positionally and check the values are his
    probe = database.load_table(member, vanilla.to_bytes())
    warns = dbpatch.apply_patch(probe, {k: v for k, v in patch.items() if k != "expect"})
    entry["apply_warnings"] = len(warns)
    ok = 0
    if his is not None:
        for k in keys:
            if k >= len(his.rows) or k >= len(probe.rows):
                continue
            want, got = his.rows[k].to_dict(), probe.rows[k].to_dict()
            if all(str(got.get(f)) == str(want.get(f)) for f in rows[str(k)]):
                ok += 1
        entry["content_ok"] = ok
        entry["content_total"] = len(keys)
    else:
        entry["content_ok"] = None

    # does re-diffing vanilla against his release reproduce these keys?
    if his is not None:
        fresh = dbpatch.diff_table(vanilla, his)
        entry["fresh_diff_same_keys"] = sorted(fresh.get("rows") or {}) == sorted(rows)
        entry["fresh_diff_same_values"] = all(
            (fresh.get("rows") or {}).get(k) == rows[k] for k in rows
            if str(k) in (fresh.get("rows") or {}))
    else:
        entry["fresh_diff_same_keys"] = None

    if entry["key"]:
        entry["space"] = "key:" + str(entry["key"])
        entry["verdict"] = ("authored by %s" % entry["key"]) if entry["id_valid"] == len(keys) else \
            ("authored by %s, %d keys are not a %s" % (entry["key"], len(keys) - entry["id_valid"], entry["key"]))
    elif entry.get("fresh_diff_same_keys") and entry.get("aligned"):
        entry["space"] = "index"
        entry["verdict"] = "positional: the keys ARE his table's row order (re-diff reproduces them)"
    elif entry["id_valid"] == len(keys):
        entry["space"] = "id"
        entry["verdict"] = "id-keyed: every key is an identity-column value"
    else:
        entry["space"] = "index?"
        entry["verdict"] = "unproven: neither reading reproduces his file"
    entry["expect"] = {"by": by, "rows": {str(k): vident[k] for k in keys if k in vident}} if by else None
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", required=True)
    ap.add_argument("--release", default=DEFAULT_RELEASE)
    ap.add_argument("--vanilla", default=DEFAULT_VANILLA)
    ap.add_argument("--json")
    ap.add_argument("--write-expect", action="store_true")
    ap.add_argument("--fixture")
    args = ap.parse_args()
    if "Installed D5ModKit" in os.path.abspath(args.mods):
        raise SystemExit("refusing to run against the installed kit")

    vanilla_db = database.load_database(args.vanilla)
    rows = [audit_one(args.mods, args.release, vanilla_db, *spec) for spec in patch_files(args.mods)]

    width = max((len(r["mod"]) for r in rows), default=10)
    print(f"{'mod':{width}s}  {'member':26s} {'keys':>5s}  {'space':8s} verdict")
    for r in rows:
        print(f"{r['mod']:{width}s}  {r['member']:26s} {r['keys'] if 'keys' in r else 0:5d}  "
              f"{r['space']:8s} {r['verdict']}")
        if r.get("content_ok") not in (None, r.get("content_total")):
            print(f"{'':{width}s}  ! content: {r['content_ok']}/{r['content_total']} rows carry his values")
        if r.get("aligned") is False:
            print(f"{'':{width}s}  ! identity: his row differs at {r.get('aligned_mismatches')}")

    spaces = {}
    for r in rows:
        spaces[r["space"]] = spaces.get(r["space"], 0) + 1
    total_rows = sum(r.get("changed_rows", 0) for r in rows)
    id_rows = sum(r.get("changed_rows", 0) for r in rows if r["space"].startswith("key:"))
    print(f"\n{len(rows)} patch files over {len({r['mod'] for r in rows})} mods, {total_rows} row edits; "
          f"key spaces: {spaces}; id-keyed edits: {id_rows}")

    if args.write_expect:
        n = 0
        for r in rows:
            if r["space"] != "index" or not r.get("expect"):
                continue
            path = os.path.join(args.mods, r["patch"])
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            doc["expect"] = r["expect"]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=1, sort_keys=False)
                f.write("\n")
            n += 1
        print(f"wrote `expect` into {n} positional patches")

    if args.fixture:
        fixture = {}
        for r in rows:
            if r["space"] != "index" or not r.get("expect"):
                continue
            fixture.setdefault(r["mod"], {})[r["member"]] = r["expect"]
        os.makedirs(os.path.dirname(os.path.abspath(args.fixture)), exist_ok=True)
        with open(args.fixture, "w", encoding="utf-8") as f:
            json.dump(fixture, f, indent=1, sort_keys=True)
            f.write("\n")
        print(f"wrote {args.fixture} ({sum(len(t['rows']) for m in fixture.values() for t in m.values())} identities)")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"mods": os.path.abspath(args.mods), "release": os.path.abspath(args.release),
                       "vanilla": os.path.abspath(args.vanilla), "patches": rows}, f, indent=1)
            f.write("\n")
        print(f"receipt: {args.json}")


if __name__ == "__main__":
    main()
