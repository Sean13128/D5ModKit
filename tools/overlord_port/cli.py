"""OLCOMPAT offline prototype — one entry point.

  python tools/overlord_port/cli.py tables --release "<extracted Overlord v3>" --out <dir> [--installed <mods dir>]
  python tools/overlord_port/cli.py effects --ini "<release>/mods/Overlord/evilities.ini" --skill-table <Skill.dat> --out <dir>
  python tools/overlord_port/cli.py arbitrate --exe <pinned vanilla exe> --declarations <overlord/01_declarations.c> --release <dir> --json <file>

Nothing here launches the game, installs anything, writes the game folder / installed kit /
profiles / saves, or publishes. `tables --out` writes a mod folder under the given directory only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import arbitrate   # noqa: E402
import baseline    # noqa: E402
import effects     # noqa: E402
import package     # noqa: E402
import tables      # noqa: E402


def cmd_tables(a):
    report = package.convert(a.release, a.out, game_dir=a.game, installed_mods=a.installed,
                             allow_vanilla_row_rewrites=not a.exclude_rebalance,
                             allow_positional=a.allow_positional_changes, write=True)
    print(json.dumps({k: report[k] for k in
                      ("verdict", "mod_order", "vanilla_rows_rewritten", "reasons")}, indent=1))
    for name, body in report.get("mods", {}).items():
        total = sum(v["rows"] + v["insert"] + v["added"] for v in body["members"].values())
        print(f"  mod {name:32s} {total:4d} row(s) in {len(body['members'])} member(s)")
    for m in report["members"]:
        print(f"  {m['status']:28s} {m['table']:26s} changed={m.get('changed_rows', 0):4d} "
              f"inserted={m.get('inserted_rows', 0):2d} added={m.get('added_rows', 0):3d} "
              f"composite={m.get('composite_byte_exact')} {m.get('reason', '')}")
    for f in report["findings"][:20]:
        print(f"  finding {f['severity']:7s} {f['kind']:14s} {f.get('namespace')} "
              f"{f.get('start')}..{f.get('end')} {f['detail']}")
    return 0 if report["verdict"] == "installable-plan" else 1


def cmd_effects(a):
    from d5lib import database
    with open(a.skill_table, "rb") as fh:
        table = database.load_table("Skill.dat", fh.read())
    data, verdicts = effects.convert(a.ini, table)
    summary = {}
    for v in verdicts:
        summary[v["verdict"]] = summary.get(v["verdict"], 0) + 1
    print(json.dumps({"sections": len(verdicts), "summary": summary,
                      "evilities": len(data["evilities"])}, indent=1))
    for v in verdicts:
        if v["verdict"] in ("refused", "unproven"):
            print(f"  {v['verdict']:8s} [{v['id']}] {v['label']}: {v.get('reason', '')}")
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        path = os.path.join(a.out, "evilities.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"evilities": data["evilities"]}, fh, indent=1)
        with open(os.path.join(a.out, "evilities-verdicts.json"), "w", encoding="utf-8") as fh:
            json.dump(verdicts, fh, indent=1)
        print("wrote", path)
    return 0


def cmd_arbitrate(a):
    report = arbitrate.arbitrate(a.exe, a.declarations, release=a.release)
    print(json.dumps({k: report[k] for k in ("sites", "verdict_counts", "exe_sha256")}, indent=1))
    for o in report["overlaps"]:
        print(f"  {o['verdict']:18s} {o['a']['owner']}:{o['a']['name']}@{o['a']['va']} "
              f"vs {o['b']['owner']}:{o['b']['name']}@{o['b']['va']}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        print("wrote", a.json)
    return 0


def cmd_members(a):
    fs = baseline.open_database(a.game)
    print(json.dumps({"game": fs.game_dir, "vanilla_available": baseline.is_vanilla_available(a.game),
                      "members": len(baseline.members(fs))}, indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tables", help="convert the release's full-table replacements to Kit row patches")
    t.add_argument("--release", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--game", default=baseline.DEFAULT_GAME)
    t.add_argument("--installed", help="mods dir to check id duplicates against (read-only)")
    t.add_argument("--allow-positional-changes", action="store_true",
                   help="convert a change that moves a saved position (needs the save importer too)")
    t.add_argument("--exclude-rebalance", action="store_true",
                   help="do not emit 'Overlord Rebalance' (the retuned rows of the game's own tables)")
    t.set_defaults(fn=cmd_tables)

    e = sub.add_parser("effects", help="convert Overlord evilities.ini to Kit evility rows")
    e.add_argument("--ini", required=True)
    e.add_argument("--skill-table", required=True)
    e.add_argument("--out")
    e.set_defaults(fn=cmd_effects)

    b = sub.add_parser("arbitrate", help="hook-site arbitration table over the pinned executable")
    b.add_argument("--exe", required=True)
    b.add_argument("--declarations", required=True)
    b.add_argument("--release")
    b.add_argument("--json")
    b.set_defaults(fn=cmd_arbitrate)

    m = sub.add_parser("members", help="list vanilla Database_0 members (sanity check)")
    m.add_argument("--game", default=baseline.DEFAULT_GAME)
    m.set_defaults(fn=cmd_members)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
