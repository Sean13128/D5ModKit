"""Check the allocation manifest and any set of claims against it (offline).

  python tools/check_ownership.py                          # self-check the manifest
  python tools/check_ownership.py --render                 # print the manifest as markdown
  python tools/check_ownership.py --claims a.json b.json    # check claims (install plan / fixture)
  python tools/check_ownership.py --claims a.json --project # ... and print who owns what
  python tools/check_ownership.py --claims a.json --json     # machine-readable findings
  python tools/check_ownership.py --installed "<mods dir>"   # every installed mod folder (read-only)
  python tools/check_ownership.py --installed "<mods dir>" --vanilla-database <Database_0.dat>
                                                            # ... and refuse ids the vanilla table has
  python tools/check_ownership.py --installed "<mods dir>" --profile <profile dir>/load_order.json
                                                            # ... only the mods that profile has enabled

`--installed` reads every `<mod>/patches/db/<member>.json` under the directory and reports ids two mod
folders both append, row-index patches two mods make differently, and (with `--vanilla-database`) ids
that already exist in the game's own table.  Nothing is written, nothing is installed: the game folder
and the installed kit are only read.

Exit status is 1 when any finding is an error, so it can gate a build.  Nothing here touches the game,
the installed kit or any archive -- except reading the Database file you pass explicitly.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d5lib import modclaims, ownership      # noqa: E402


def enabled_names(load_order_path):
    """The mod names a profile has enabled: `load_order.json` is a JSON list of folder names.

    Read-only; the profile directory belongs to the installed kit and is never written here.
    """
    with open(load_order_path, "r", encoding="utf-8-sig") as fh:
        order = json.load(fh)
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise ValueError(f"{load_order_path}: expected a JSON list of mod folder names")
    return order


def installed_findings(installed_dir, vanilla_database=None, only=None):
    """Scan every mod folder under `installed_dir`; returns (scan, findings)."""
    scan = modclaims.scan_mods(installed_dir, only=only)
    names = fillable = None
    if vanilla_database:
        names = modclaims.vanilla_names(vanilla_database)
        fillable = modclaims.vanilla_fillable(names)
    return scan, modclaims.findings(scan, names, fillable)


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--manifest", default=ownership.MANIFEST_PATH)
    ap.add_argument("--claims", nargs="*", default=[], help="claims JSON files (list or {'claims': [...]})")
    ap.add_argument("--installed", metavar="MODS_DIR",
                    help="scan every mod folder under this directory (read-only) for duplicate ids")
    ap.add_argument("--vanilla-database", metavar="DATABASE_0",
                    help="a vanilla Database_0.dat to refuse ids the game's own table already has")
    ap.add_argument("--profile", metavar="LOAD_ORDER_JSON",
                    help="a profile's load_order.json: check only the mods that profile enables")
    ap.add_argument("--only", metavar="MOD[,MOD]",
                    help="check only these mod folder names (comma separated)")
    ap.add_argument("--project", action="store_true", help="print the resolved owner of every claim")
    ap.add_argument("--render", action="store_true", help="print the manifest as markdown")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    ap.add_argument("--quiet", action="store_true", help="only the counts")
    args = ap.parse_args(argv)

    manifest = ownership.load(args.manifest)
    if args.render:
        print(ownership.render_markdown(manifest))
        return 0

    findings = list(ownership.check_manifest(manifest))
    claims = []
    for path in args.claims:
        claims.extend(ownership.load_claims(path))
    if claims:
        projection = ownership.Projection(manifest, claims)
        findings.extend(projection.findings())
    else:
        projection = ownership.Projection(manifest)

    only = None
    if args.only:
        only = [n.strip() for n in args.only.split(",") if n.strip()]
    if args.profile:
        names = enabled_names(args.profile)
        only = names if only is None else [n for n in names if n in set(only)]

    scan = None
    usage = []
    if args.installed:
        scan, usage = installed_findings(args.installed, args.vanilla_database, only)

    if args.json:
        print(json.dumps({"manifest": args.manifest,
                          "findings": [f.as_dict() for f in findings],
                          "projection": projection.as_dict(),
                          "installed": dict(scan.as_dict(), mods_dir=args.installed,
                                            vanilla=args.vanilla_database,
                                            findings=[f.as_dict() for f in usage]) if scan else None}, indent=2))
    else:
        if not args.quiet:
            print(f"manifest {manifest.base}: {len(manifest.namespaces)} namespaces, "
                  f"{sum(len(n.bands) for n in manifest.namespaces.values())} bands, "
                  f"{sum(len(n.members) for n in manifest.namespaces.values())} members")
            for f in findings:
                print(f)
            if scan is not None:
                scope = f" ({args.profile or args.only})" if (args.profile or args.only) else ""
                print(f"installed {args.installed}{scope}: {len(scan.mods)} mod folders, "
                      f"{len(scan.tables())} table(s) patched")
                for name in scan.missing:
                    print(f"WARNING missing        {name}: in the profile but not under {args.installed}")
                for f in usage:
                    if f.kind != "fills_vanilla_dummy":
                        print(f)
        errs = len(ownership.errors(findings)) + len(modclaims.errors(usage))
        other = len(findings) + len(usage) - errs
        print(f"{errs} error(s), {other} other finding(s)")
        if args.project:
            for c in projection.all_claims():
                print(f"  {c.namespace:16s} {c.start if c.member is None else c.member!s:>8} "
                      f"{'' if c.member is not None else '.. ' + str(c.end):>8}  {c.holder}")
    errors_now = len(ownership.errors(findings)) + len(modclaims.errors(usage))
    return 1 if errors_now else 0


if __name__ == "__main__":
    sys.exit(main())
