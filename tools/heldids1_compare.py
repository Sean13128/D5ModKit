#!/usr/bin/env python3
"""HELDIDS1: compare the held ids of two builds of the same packs.

The held-blank pass (``d5lib/holdblank.py``) decides which animations to hold from the **installed
pack of the same name**; on a machine with no installed pack it holds the ids recorded in
``d5lib/importers/held-blank-keys.json``.  This tool checks that the two paths agree: give it the
``tools/import_game.py`` output folders for the same game, one built with the installed packs as
reference and one built with ``D5_INSTALLED_MODS`` pointing at an empty folder, and it prints the
per-pack/per-bank table, the ids from the shipped file, and whether the bank bytes match.

    python tools/heldids1_compare.py --installed-out OUT1 --no-install-out OUT2 --game d1c \
        [--evidence PATH] [--markdown PATH]

Each option may be repeated (split runs, e.g. a 23-pack run plus a 4-pack run).  Exit 0 only when,
for every pack built, the shipped file lists exactly the ids the installed-reference pass held and
the no-install build held the same ids and filled the same keys.  Bank bytes are reported, not
required: a D1C unique's bank also carries the installed palette/atlas shape, which an ids-only file
cannot restore (the palette rule, not the hold pass).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import holdblank  # noqa: E402

BANK_DIR = holdblank.BANK_DIR


def _load_results(out_dirs, game):
    """{pack: {'ids', 'keys', 'source', 'built', 'mods'}} merged over one or more import_game outs."""
    packs = {}
    for out in out_dirs:
        doc = json.loads((out / game / "results.json").read_text(encoding="utf-8"))
        for r in doc.get("results") or []:
            extra = r.get("extra") or {}
            held = extra.get("hold_blank") or r.get("hold_blank") or {}
            packs[r["mod_folder"]] = {
                "ids": {bank: sorted(int(i) for i in v) for bank, v in held.items()},
                "keys": {bank: {int(i): int(n) for i, n in v.items()} for bank, v in held.items()}
                        if all(isinstance(v, dict) for v in held.values()) else {},
                "source": extra.get("hold_blank_source") or r.get("hold_blank_source"),
                "built": bool(r.get("built")),
                "mods": Path(out) / game / "mods" / r["mod_folder"],
            }
    return packs


def bank_hashes(mod_folder):
    """sha256 of every motion-bank-shaped file (the ``anm<n>`` files below 10000) in a pack."""
    out = {}
    for bank in sorted((Path(mod_folder) / BANK_DIR).glob("anm*.lzs")):
        if bank.name[3:8].isdigit() and int(bank.name[3:8]) < 10000:
            out[bank.name] = hashlib.sha256(bank.read_bytes()).hexdigest()
    return out


def _fmt(ids):
    return "[" + ",".join(str(i) for i in ids) + "]"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--installed-out", type=Path, action="append", required=True,
                    help="import_game --out with the installed packs as reference (repeatable)")
    ap.add_argument("--no-install-out", type=Path, action="append", required=True,
                    help="import_game --out with D5_INSTALLED_MODS empty (repeatable)")
    ap.add_argument("--game", required=True, choices=("d1c", "d4", "dd2"))
    ap.add_argument("--file", type=Path, default=holdblank.REFERENCE_FILE,
                    help="the shipped held-ids file (default: d5lib/importers/held-blank-keys.json)")
    ap.add_argument("--partial", action="store_true",
                    help="do not require every pack in the file to have been built (split runs)")
    ap.add_argument("--evidence", type=Path, help="write the measured table as JSON")
    ap.add_argument("--markdown", type=Path, help="write the table as markdown")
    args = ap.parse_args(argv)

    game = args.game
    installed = _load_results(args.installed_out, game)
    no_install = _load_results(args.no_install_out, game)
    shipped = (json.loads(args.file.read_text(encoding="utf-8")).get("games") or {}).get(game) or {}
    packs = sorted(set(installed) | set(no_install))
    if not args.partial:
        for pack in shipped:
            if pack not in packs:
                packs.append(pack)
        packs.sort()

    problems = []
    evidence = {}
    rows = ["| pack | bank | installed pass | file | no-install build | bank bytes |",
            "|---|---|---|---|---|---|"]
    for pack in packs:
        ins = installed.get(pack)
        noi = no_install.get(pack)
        fil = {b: sorted(v) for b, v in (shipped.get(pack) or {}).items()}
        if ins is None or noi is None:
            problems.append(f"{pack}: not built by both runs")
            continue
        if not ins.get("built"):
            problems.append(f"{pack}: the installed-reference build did not build")
        if not noi.get("built"):
            problems.append(f"{pack}: the no-install build did not build")
        banks = sorted(set(ins["ids"]) | set(noi["ids"]) | set(fil))
        pack_ev = {}
        hashes_a = bank_hashes(ins["mods"])
        hashes_b = bank_hashes(noi["mods"])
        for bank in banks:
            held = ins["ids"].get(bank, [])
            from_file = fil.get(bank, [])
            no_held = noi["ids"].get(bank, [])
            if from_file != held:
                problems.append(f"{pack} {bank}: file {_fmt(from_file)} != installed pass {_fmt(held)}")
            if no_held != held:
                problems.append(f"{pack} {bank}: no-install build {_fmt(no_held)} != installed pass {_fmt(held)}")
            key_counts = ins["keys"].get(bank) or {}
            no_keys = noi["keys"].get(bank) or {}
            if key_counts and no_keys and key_counts != no_keys:
                problems.append(f"{pack} {bank}: keys filled {key_counts} (installed) != {no_keys} (no install)")
            if bank not in hashes_a or bank not in hashes_b:
                bytes_note = "missing"
                problems.append(f"{pack} {bank}: bank missing from a build")
            elif hashes_a[bank] == hashes_b[bank]:
                bytes_note = "same"
            else:
                bytes_note = "differ"
            pack_ev[bank] = {"install": held, "empty": no_held, "file": from_file,
                             "keys_install": key_counts, "keys_empty": no_keys,
                             "bank_bytes": bytes_note}
            rows.append(f"| {pack} | {bank} | {_fmt(held)} | {_fmt(from_file)} | {_fmt(no_held)} | "
                        f"{'same' if from_file == held == no_held else 'differs'} / bytes {bytes_note} |")
        evidence[pack] = pack_ev

    print("\n".join(rows))
    print(f"\n{len(packs)} pack(s); {len(problems)} problem(s)")
    for p in problems:
        print(f"  PROBLEM {p}")
    if args.evidence:
        doc = {
            "schema": "heldids1-install-pass/1",
            "about": "Ids the installed-reference hold pass held for the packs in held-blank-keys.json, "
                     "and the ids the same builds held with D5_INSTALLED_MODS empty. Ids only, no game data. "
                     "Measured by two tools/import_game.py builds (HELDIDS1); bank_bytes says whether the "
                     "no-install build's bank equals the installed-reference build's bank, which a D1C "
                     "unique cannot (palette/atlas rule, not the hold pass).",
            "source": "HELDIDS1 2026-11-18 offline builds of integ-next 306268d",
            "packs": {game: evidence},
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"evidence: {args.evidence}")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
