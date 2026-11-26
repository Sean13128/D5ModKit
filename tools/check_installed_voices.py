#!/usr/bin/env python3
"""Readback gate for custom voices (VOICE1): does the INSTALLED game hold what the mod folders say?  Read-only.

    python tools/check_installed_voices.py --game "<Disgaea 5 Complete>" --mods <mods dir> [--only A,B]

For every mod folder with patches/voices/voices.json, in both dub tables: every line the kit would write is a row
of the installed Sound_Voice table (same voice set and situations), its clip is a member of the installed
Sound_Voice_0.dat pack with the mod's bytes, and the mod's added char.dat rows carry their voice id.
Sound cannot be judged by a screenshot; this proves the game was given the right clip for every situation.
Exit 1 on any difference.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def check(game, mods, only=None):
    from d5lib import database, fafs, modsys, voices
    from d5lib.drpgvoice import SILENT_VOICE_ID as SILENT
    from d5lib.nispack import NisPack
    data = Path(game) / "Data"
    with NisPack(str(data / "Database/Database_0.dat")) as pk:
        members = {e.name: pk.read(e) for e in pk.entries
                   if e.name in ("char.dat", "Sound_Voice_EN_0.dat", "Sound_Voice_JP_0.dat")}
    chars = {int(r["id"]): int(r["voice_id"]) for r in database.load_table("char.dat", members["char.dat"]).rows}
    tables = {lang: {l.id: l for l in voices.read_table(members[voices.TABLES[lang].rsplit("/", 1)[1]])}
              for lang in voices.TABLES}
    archive = fafs.FafsPack(str(data / voices.ARCHIVE))
    packs, problems, stats = {}, [], dict(mods=0, voices=0, lines=0, rows=0)
    for folder in sorted(Path(mods).iterdir()):
        vf = folder / "patches/voices/voices.json"
        mf = folder / "mod.json"                              # VOICE2: a pack that is silent as in its source game
        quiet = mf.is_file() and str((json.loads(mf.read_text(encoding="utf-8")).get("source_import") or {})
                                     .get("voice")).startswith("silent")
        if not (vf.is_file() or quiet) or (only and folder.name not in only):
            continue
        if quiet:                                             # its voice must have no line in either table
            stats["silent"] = stats.get("silent", 0) + 1
            for lang in voices.TABLES:
                if any(voices.split_set(l.group)[1] == SILENT for l in tables[lang].values()):
                    problems.append(f"{folder.name}: the silent voice {SILENT} has lines in the installed {lang} table")
        stats["mods"] += 1
        mod = modsys.Mod(str(folder))
        doc = voices.load(mod)
        for vid, voice in doc["voices"].items():
            stats["voices"] += 1
            for lang in voices.TABLES:
                for line, (kind, ref) in voices.custom_lines(int(vid), voice, lang=lang):
                    stats["lines"] += 1
                    row = tables[lang].get(line.id)
                    if row is None or row.group != line.group or row.cats != line.cats:
                        problems.append(f"{folder.name}: voice {vid} {lang} line {line.id} not in the installed table as built")
                        continue
                    if kind != "file":
                        continue
                    name = f"{voices.PREFIX[lang]}/{line.group:06d}.dat"
                    if name not in packs:
                        packs[name] = fafs.pack_members(archive.read(name)) if name.lower() in archive.by_name else {}
                    if packs[name].get(f"{line.id:09d}.vag") != (Path(voices.folder(mod)) / ref).read_bytes():
                        problems.append(f"{folder.name}: voice {vid} {lang} line {line.id}: installed clip differs from {ref}")
        chf = folder / "patches/db/char.dat.json"
        for r in (json.loads(chf.read_text(encoding="utf-8-sig")).get("added", []) if chf.is_file() else []):
            stats["rows"] += 1
            if chars.get(int(r["id"])) != int(r["voice_id"]):
                problems.append(f"{folder.name}: char row {r['id']} has voice {chars.get(int(r['id']))}, pack says {r['voice_id']}")
    archive.close()
    return problems, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--mods", type=Path, required=True)
    ap.add_argument("--only")
    a = ap.parse_args(argv)
    problems, stats = check(a.game, a.mods, set(a.only.split(",")) if a.only else None)
    for p in problems[:40]:
        print("FAIL", p)
    print(json.dumps(dict(stats, problems=len(problems))))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
