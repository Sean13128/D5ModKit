#!/usr/bin/env python3
"""Write ``d5lib/importers/held-blank-keys.json``: the bank files and animation ids the
installed-reference hold pass fills, for machines with no installed pack (REPROFIX3 (e)).

The file holds **ids only** -- pack folder, bank file name and animation id -- never key counts,
cells or any other game data.  Sources, both offline:

* ``--results``:  one or more ``*.results.json`` written by ``tools/import_game.py``; each result's
  ``extra.hold_blank`` (or ``hold_blank``) is the list the D1C importer held against the install.
  This is the authoritative set for a game, exactly what the installed-reference pass does.
* ``--blankkeys``:  BLANKKEYS1's measured apply record
  (``Builds/BLANKKEYS1-20261111/blankkeys1-apply.json``), which names every held bank and id of
  D1C, D4 and DD2.  Used for packs a ``--results`` pass does not cover.
* ``--scan``:  a built mods folder plus ``--installed``; the pass is re-run read-only against the
  install and its ids recorded.  Overrides the other sources for the packs present.

    python tools/build_held_blank_keys.py --results '/path/records2/d1c-d-*.results.json' \
        --blankkeys /Volumes/Data/Projects/D5/Builds/BLANKKEYS1-20261111/blankkeys1-apply.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import anm, gamefs, holdblank  # noqa: E402

OUT = ROOT / "d5lib/importers/held-blank-keys.json"
BLANKKEYS = Path("/Volumes/Data/Projects/D5/Builds/BLANKKEYS1-20261111/blankkeys1-apply.json")
INSTALLED = Path(os.environ.get("D5_INSTALLED_MODS")
                 or "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods")
GAME_BY_PREFIX = (("D1C_", "d1c"), ("D4_", "d4"), ("DD2_", "dd2"))


def _game(name):
    for prefix, game in GAME_BY_PREFIX:
        if name.startswith(prefix):
            return game
    return None


def from_results(patterns):
    """{game: {pack: {bank: [ids]}}} from import_game results files (hold_blank records)."""
    games = {}
    for pattern in patterns:
        for f in sorted(glob.glob(pattern)):
            doc = json.loads(Path(f).read_text())
            game = doc.get("game")
            for r in doc.get("results") or []:
                held = (r.get("extra") or {}).get("hold_blank") or r.get("hold_blank")
                pack = r.get("mod_folder")
                if not held or not pack or not game:
                    continue
                slot = games.setdefault(game, {}).setdefault(pack, {})
                for bank, ids in held.items():
                    keys = ids.keys() if isinstance(ids, dict) else ids   # hold_blank: {id: keys filled}
                    slot[bank] = sorted(set(slot.get(bank, [])) | {int(i) for i in keys})
    return games


def from_blankkeys(path):
    """{game: {pack: {bank: [ids]}}} from BLANKKEYS1's apply record (bank number -> anm<bank>.lzs)."""
    games = {}
    if not Path(path).is_file():
        return games
    doc = json.loads(Path(path).read_text())
    for pack, rec in doc.items():
        game = _game(pack)
        if not game:
            continue
        for bank, st in (rec.get("banks") or {}).items():
            ids = sorted(int(i) for i in (st.get("held") or {}))
            if not ids:
                continue
            name = f"anm{int(bank):05d}.lzs"
            slot = games.setdefault(game, {}).setdefault(pack, {})
            slot[name] = sorted(set(slot.get(name, [])) | set(ids))
    return games


def scan(built_root, installed_root):
    """Re-run the read-only installed-reference detection over every built pack under ``built_root``."""
    games = {}
    for mod in sorted(Path(built_root).glob("*/")):
        game = _game(mod.name)
        if not game or not (mod / "mod.json").is_file():
            continue
        installed = Path(installed_root) / mod.name
        held = {}
        for bank, _ids in holdblank.motion_banks(mod):
            ref = installed / holdblank.BANK_DIR / bank.name
            if not ref.is_file():
                continue
            try:
                ids = holdblank.hold_ids_from_installed(anm.parse(gamefs.decode_member(bank.read_bytes())),
                                                        anm.parse(gamefs.decode_member(ref.read_bytes())))
            except Exception:                          # noqa: BLE001 - not a bank pair
                continue
            if ids:
                held[bank.name] = sorted(ids)
        if held:
            games.setdefault(game, {})[mod.name] = held
    return games


def merge(dst, src):
    for game, packs in src.items():
        target = dst.setdefault(game, {})
        for pack, banks in packs.items():
            slot = target.setdefault(pack, {})
            for bank, ids in banks.items():
                slot[bank] = sorted(set(slot.get(bank, [])) | set(ids))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", action="append", default=[], metavar="GLOB",
                    help="import_game results JSON glob(s) with hold_blank records (authoritative)")
    ap.add_argument("--blankkeys", type=Path, default=BLANKKEYS,
                    help="BLANKKEYS1 apply record (default: the 2026-11-11 build)")
    ap.add_argument("--scan", action="append", default=[], metavar="MODS_DIR",
                    help="built mods folder to re-detect against --installed (repeatable)")
    ap.add_argument("--installed", type=Path, default=INSTALLED)
    args = ap.parse_args(argv)
    games = {}
    if args.blankkeys:
        merge(games, from_blankkeys(args.blankkeys))
    merge(games, from_results(args.results))
    for root in args.scan:
        merge(games, scan(root, args.installed))
    doc = {
        "schema": "held-blank-keys/1",
        "about": "Bank files and animation ids the installed-reference hold pass (d5lib/holdblank.py) fills when a "
                 "machine has no installed pack. Ids only, no game data: the pass holds the nearest earlier drawn "
                 "key of the same private layer at each blank key time (BLANKKEYS1 rule; a labelled approximation). "
                 "Do not hand-edit; regenerate with tools/build_held_blank_keys.py.",
        "source": "BLANKKEYS1-20261111 blankkeys1-apply.json (measured held pose), import_game results with "
                  "hold_blank records (D1C final pass), and installed-reference scans of rebuilt packs",
        "games": {g: {p: dict(sorted(banks.items())) for p, banks in sorted(packs.items())}
                  for g, packs in sorted(games.items())},
    }
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n = sum(len(b) for packs in games.values() for b in packs.values())
    print(f"wrote {OUT}: " + ", ".join(f"{g} {len(p)} packs" for g, p in sorted(games.items()))
          + f" ({n} bank entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
