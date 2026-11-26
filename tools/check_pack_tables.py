"""Offline validator for database text in D5 Mod Kit packs.

    python tools/check_pack_tables.py --mods "<kit>/mods" \
        --database "<game>/Data/Database/Database_0.dat" --json out.json

For every ``<mod>/patches/db/*.json`` patch (the d5lib.dbpatch format: {"table": ...,
"rows": {"<index>": {field: value}}, "added": [...], "sections": {...}}) and for the
merged installed Database_0.dat it checks the text fields d5lib.tablelimits knows about:

  * length -- Skill.dat name_* must fit 63 bytes + NUL, desc_* 255 bytes + NUL, i.e. the
    buffers of the Skill-Shop drawer FUN_1407d22b0 / FUN_1407ce3e0 (an over-long
    description makes _vsnprintf_s hit the invalid-parameter handler: c0000409);
  * format -- a description is used as a printf format with ONE integer argument, so
    only %d (once) and %% are safe.

Prints a per-table/per-field census (how many values, the longest, how many over the
limit) and every finding; exits 1 when there is any finding.  Read-only: opens the
archive and the patches, writes nothing except the --json report.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import tablelimits as tl  # noqa: E402


# ------------------------------------------------------------------ patch reading
def patch_files(mod_dir: Path):
    d = mod_dir / "patches" / "db"
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def iter_patch_rows(patch: dict, fallback_table: str = ""):
    """yield (table, row_id, fields) for every row of a patch, sections included"""
    table = patch.get("table") or fallback_table
    for idx, fields in (patch.get("rows") or {}).items():
        if not isinstance(fields, dict):
            continue
        rid = fields.get("id", f"#{idx}")
        yield table, rid, fields, f"rows[{idx}]"
    for k, fields in enumerate(patch.get("added") or []):
        if not isinstance(fields, dict):
            continue
        yield table, fields.get("id", f"added[{k}]"), fields, f"added[{k}]"
    for name, sub in (patch.get("sections") or {}).items():
        if not isinstance(sub, dict):
            continue
        for t, rid, fields, where in iter_patch_rows(sub, table):
            yield f"{t}[{name}]", rid, fields, f"sections.{name}.{where}"


def walk_mods(dirs):
    """[(mod_name, mod_dir)] for every mod folder under the given roots"""
    out = []
    for root in dirs:
        root = Path(root)
        if not root.is_dir():
            print(f"WARNING: not a directory: {root}", file=sys.stderr)
            continue
        if (root / "patches").is_dir():
            out.append((root.name, root))
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "patches").is_dir():
                out.append((child.name, child))
    return out


SEVERITIES = ("display", "crash", "overflow")


def keep(finding, minimum: str) -> bool:
    return SEVERITIES.index(finding["severity"]) >= SEVERITIES.index(minimum)


# ------------------------------------------------------------------ census
class Census:
    def __init__(self):
        self.fields = {}          # (table, field) -> stats
        self.findings = []
        self.skipped = defaultdict(lambda: {"values": 0, "max": 0})  # unknown-limit fields
        self.bad_json = []
        self.sources = defaultdict(int)

    def note(self, table, field, value):
        key = (table, field)
        st = self.fields.get(key)
        if st is None:
            st = self.fields[key] = {"n": 0, "max": 0, "max_id": None, "over": 0,
                                     "bad_format": 0, "limit": tl.limit_for(table, field),
                                     "formatted": tl.is_formatted(table, field)}
        nb = tl.byte_len(value)
        st["n"] += 1
        if nb > st["max"]:
            st["max"], st["max_id"] = nb, None
        if st["limit"] is not None and nb > st["limit"]:
            st["over"] += 1
        rule = tl.rule_for(table, field)
        if rule is not None:
            ok, _ = tl.format_ok(value, allowed=rule[0], max_conversions=rule[1])
            if not ok:
                st["bad_format"] += 1
        if st["limit"] is None:
            sk = self.skipped[key]
            sk["values"] += 1
            sk["max"] = max(sk["max"], nb)
        return st

    def add(self, table, rid, fields, where, source):
        rows = [(rid, fields)]
        found = tl.findings(table, rows)
        for f in found:
            f["where"] = where
            f["source"] = source
            self.findings.append(f)
        for field, value in fields.items():
            if not isinstance(value, str):
                continue
            st = self.note(table, field, value)
            if st["max_id"] is None and tl.byte_len(value) == st["max"]:
                st["max_id"] = rid


def scan_patches(dirs, census: Census):
    mods = walk_mods(dirs)
    for name, mod_dir in mods:
        for path in patch_files(mod_dir):
            try:
                patch = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                census.bad_json.append((str(path), f"{type(e).__name__}: {e}"))
                continue
            if not isinstance(patch, dict):
                census.bad_json.append((str(path), "not a JSON object"))
                continue
            census.sources["mod"] += 1
            for table, rid, fields, where in iter_patch_rows(patch, path.stem):
                census.add(table, rid, fields, where, f"{name}/{path.name}")
    return mods


def scan_database(path: Path, census: Census):
    from d5lib import database
    db = database.load_database(str(path))
    tables = {}
    for member in db.order:
        t = db.get(member) if hasattr(db, "get") else None
        if t is None:
            continue
        tables[member] = t
    checked = 0
    for member, table in tables.items():
        key = tl._norm_table(member)
        if key not in tl.LIMITS:
            continue
        checked += 1
        fields_wanted = set(tl.LIMITS[key])
        for row in table.rows:
            fields = {}
            for f in fields_wanted:
                try:
                    v = row[f]
                except Exception:
                    continue
                fields[f] = v
            if not fields:
                continue
            try:
                rid = row["id"]
            except Exception:
                rid = ""
            census.add(member, rid, fields, "database row", f"database:{path.name}")
        census.sources["database"] += 1
    return checked, getattr(db, "errors", {})


# ------------------------------------------------------------------ reporting
def print_census(census: Census, stream=sys.stdout):
    print("=== census (string fields of every patch + the merged table) ===", file=stream)
    hdr = f"{'table':<16} {'field':<12} {'n':>6} {'max':>5} {'limit':>6} {'over':>5} {'badfmt':>6}"
    print(hdr, file=stream)
    print("-" * len(hdr), file=stream)
    for (table, field), st in sorted(census.fields.items()):
        lim = "-" if st["limit"] is None else str(st["limit"])
        print(f"{table:<16} {field:<12} {st['n']:>6} {st['max']:>5} {lim:>6} "
              f"{st['over']:>5} {st['bad_format']:>6}", file=stream)
    print(file=stream)
    if census.skipped:
        print("fields with NO known limit (length not checked, only reported):", file=stream)
        for (table, field), sk in sorted(census.skipped.items()):
            print(f"  {table}.{field}: {sk['values']} value(s), longest {sk['max']} bytes",
                  file=stream)
        print(file=stream)
    print(f"=== findings: {len(census.findings)} ===", file=stream)
    for f in census.findings:
        print(f"{f['severity'].upper():<8} {f['kind']:<6} {f['table']}.{f['field']} id={f['id']} "
              f"[{f['source']} {f['where']}] {f['detail']}", file=stream)
    if census.bad_json:
        print(file=stream)
        print("unreadable patch files:", file=stream)
        for p, why in census.bad_json:
            print(f"  {p}: {why}", file=stream)


def report(census: Census, paths):
    return {
        "paths": paths,
        "census": {f"{t}.{f}": {**st, "max_id": st["max_id"]}
                   for (t, f), st in sorted(census.fields.items())},
        "unknown_limits": {f"{t}.{f}": sk for (t, f), sk in sorted(census.skipped.items())},
        "findings": census.findings,
        "unreadable": census.bad_json,
        "sources": dict(census.sources),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mods", action="append", default=[], metavar="DIR",
                    help="a mods folder (or one mod folder); repeatable")
    ap.add_argument("--database", type=Path, help="merged Database_0.dat to check too")
    ap.add_argument("--json", type=Path, help="write the census + findings here")
    ap.add_argument("--quiet-census", action="store_true", help="print findings only")
    ap.add_argument("--min-severity", choices=list(SEVERITIES), default="display",
                    help="report/exit on findings at or above this severity "
                         "(overflow = CRT fast-fail class, crash = %s/%n read a missing "
                         "argument, display = a conversion the call cannot fill)")
    a = ap.parse_args(argv)

    if not a.mods and not a.database:
        ap.error("give --mods and/or --database")

    census = Census()
    paths = {"mods": a.mods, "database": str(a.database) if a.database else None}
    if a.mods:
        mods = scan_patches(a.mods, census)
        paths["mod_folders"] = len(mods)
        paths["mods_with_db_patches"] = sorted(n for n, d in mods if patch_files(d))
        print(f"scanned {len(mods)} mod folder(s), "
              f"{len(paths['mods_with_db_patches'])} with patches/db", file=sys.stderr)
    errs = {}
    if a.database:
        try:
            n, errs = scan_database(a.database, census)
            paths["database_tables_checked"] = n
        except Exception as e:
            print(f"ERROR loading {a.database}: {type(e).__name__}: {e}", file=sys.stderr)
            paths["database_error"] = f"{type(e).__name__}: {e}"

    if a.min_severity != "display":
        census.findings = [f for f in census.findings if keep(f, a.min_severity)]
        print(f"(reporting only {a.min_severity}+ findings)", file=sys.stderr)
    if not a.quiet_census:
        print_census(census)
    else:
        print(f"=== findings: {len(census.findings)} ===")
        for f in census.findings:
            print(f"{f['severity'].upper():<8} {f['kind']:<6} {f['table']}.{f['field']} id={f['id']} "
                  f"[{f['source']} {f['where']}] {f['detail']}")
    if errs:
        print(f"note: {len(errs)} archive member(s) had no schema/parse error", file=sys.stderr)

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(report(census, paths), indent=1, ensure_ascii=False),
                          encoding="utf-8")
        print(f"wrote {a.json}", file=sys.stderr)
    return 1 if census.findings or census.bad_json else 0


if __name__ == "__main__":
    sys.exit(main())
