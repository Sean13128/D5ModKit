#!/usr/bin/env python3
"""Offline replay of the install steps that decide a char row's voice (VOICE1b): every enabled mod's char.dat patch
in load order on the clean table, then `outfits._follow_base` with every pack's outfit pairs and `own_voice`
declarations.  Staged folders replace the installed ones of the same name.  Read-only; no game, no installer state.

    python tools/simulate_outfit_voices.py --clean "<clean Disgaea 5 Complete>" --installed <kit>/mods
        --order <kit>/profiles/MAIN/load_order.json --staged <bundle>/mods [--ignore-declarations]

Problem = a staged pack's added char row whose voice_id after the replay is not the pack's (what
tools/check_installed_voices.py would report after a real install).  Exit 1 on any.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def replay(clean, installed, order, staged, declarations=True):
    from d5lib import database, dbpatch, gamefs, modsys, outfits
    table = database.load_table("char.dat", gamefs.GameFS(str(clean)).read("Database/Database_0.dat/char.dat"))
    staged_names = {p.name for p in Path(staged).iterdir() if (p / "mod.json").is_file()}
    names = list(order) + sorted(staged_names - set(order))
    pairs, own_voice, wanted, errors = [], set(), {}, []
    for name in names:
        folder = (Path(staged) if name in staged_names else Path(installed)) / name
        if not (folder / "mod.json").is_file():
            continue
        f = folder / "patches/db/char.dat.json"
        if f.is_file():
            patch = json.loads(f.read_text(encoding="utf-8-sig"))
            try:
                dbpatch.apply_patch(table, patch)
            except Exception as exc:                               # noqa: BLE001
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
            if name in staged_names and (folder / "patches/voices/voices.json").is_file():
                wanted.update({int(r["id"]): (name, int(r["voice_id"])) for r in patch.get("added", [])})
        mod = modsys.Mod(str(folder))
        pairs += [p for p in outfits.load(mod) if p not in pairs]
        if declarations:
            own_voice.update(outfits.load_own_voice(mod))
    rows = {r["id"]: r for r in table.rows}
    synced = outfits._follow_base(rows, pairs, own_voice)
    problems = [f"{name}: char row {rid} has voice {rows[rid]['voice_id'] if rid in rows else None}, pack says {vid}"
                for rid, (name, vid) in sorted(wanted.items()) if rid not in rows or int(rows[rid]["voice_id"]) != vid]
    return dict(mods=len(names), pairs=len(pairs), own_voice=len(own_voice), rows_checked=len(wanted),
                outfit_rows_synced=synced, patch_errors=errors, problems=problems)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", type=Path, required=True)
    ap.add_argument("--installed", type=Path, required=True)
    ap.add_argument("--order", type=Path, required=True)
    ap.add_argument("--staged", type=Path, required=True)
    ap.add_argument("--ignore-declarations", action="store_true", help="negative control: the pre-VOICE1b installer")
    a = ap.parse_args(argv)
    out = replay(a.clean, a.installed, json.loads(a.order.read_text()), a.staged, not a.ignore_declarations)
    for p in out["problems"][:10]:
        print("FAIL", p)
    print(json.dumps(dict(out, problems=len(out["problems"]), patch_errors=len(out["patch_errors"]))))
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
