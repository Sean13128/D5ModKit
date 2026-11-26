"""DRPG-K4 fixture table: look -> body set / companion / attack roots, with the checks that make it a gate.

    python tools/drpgk4_verify.py Builds/DRPGK4-20261106 [--game GAMEDIR] [--json OUT]

For every built pack, the kind-changing costume must have:
  * a `bodies` declaration and a char.dat row of that body kind (monster = body_type 1 for a 2000..2999 donor),
  * its own body animation N and N+1: a companion whose animation ids are a subset of the donor companion's for a
    monster body, the own-animation copy registered as an own sprite for a humanoid body,
  * the three monster normal-attack roots (12010000 / 12110000 / 12210000 + N) for a monster body and none for a
    humanoid body,
  * N+2 standing picture and N+10000 portrait.
A missing item fails the run (exit 1) rather than printing a note.
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import anm, modsys, paths  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

MONSTER_SCRIPTS = (12010000, 12110000, 12210000)


def companion_ids(a):
    return {x.id for b in a.blocks for x in b.animations}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--game", default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    game = args.game or paths.require_game_dir()
    fs = GameFS(game, backup_resolver=modsys.Installer(game, str(ROOT), log=lambda *a: None).backup_resolver)
    anime_name = "files/Anime/ANM_HI_JP.dat"
    table, problems = [], []
    for mod in sorted((args.root / "drpg/mods").iterdir()):
        data = json.loads((mod / "patches/outfits/outfits.json").read_text())
        bodies = {int(k): int(v) for k, v in (data.get("bodies") or {}).items()}
        colours = {int(k): int(v) for k, v in (data.get("colours") or {}).items()}
        own = {int(x) for x in data.get("own_sprites") or []}
        pairs = [tuple(map(int, p)) for p in data.get("pairs") or []]
        slot = next((b for a, b in pairs if b in bodies), None)
        if slot is None:
            continue
        base = next(a for a, b in pairs if b == slot)
        N, donor = colours.get(slot), bodies[slot]
        monster = 2000 <= donor < 3000
        row = next((r for r in json.loads((mod / "patches/db/char.dat.json").read_text()).get("added", [])
                    if int(r["id"]) == slot), {})
        scripts = {int(k) for k in json.loads((mod / "patches/script/script.json").read_text()).get("events", {})} \
            if (mod / "patches/script/script.json").is_file() else set()
        anime = mod / anime_name
        entry = dict(mod=mod.name, base_row=base, slot=slot, art=N, donor=donor,
                     body="monster" if monster else "humanoid",
                     row_body_type=row.get("body_type"),
                     own_sprite=N in own, own_companion=(N + 1) in own,
                     roots=sorted(p + N for p in MONSTER_SCRIPTS if p + N in scripts))
        checks = [
            (row.get("body_type") == (1 if monster else 0), "row body_type is the look's kind"),
            ((anime / f"anm{N:05d}.lzs").is_file(), f"body anm{N} exists"),
            ((anime / f"anm{N + 1:05d}.lzs").is_file(), f"anm{N + 1} exists"),
            ((anime / f"anm{N + 2:05d}.lzs").is_file(), f"standing anm{N + 2} exists"),
            ((anime / f"anm{N + 10000:05d}.lzs").is_file(), f"portrait anm{N + 10000} exists"),
        ]
        if monster:
            comp = companion_ids(anm.load(str(anime / f"anm{N + 1:05d}.lzs")))
            donor_comp = companion_ids(anm.parse(fs.read(f"Anime/ANM_HI_JP.dat/anm{donor + 1:05d}.lzs")))
            checks += [
                (comp <= donor_comp and comp, f"companion is a subset of donor {donor + 1}'s animation ids"),
                (not (N in own or N + 1 in own), "not listed as an own (humanoid) sprite"),
                (len(entry["roots"]) == len(MONSTER_SCRIPTS), "normal / effects-skipped / skipped-midway roots"),
            ]
            entry["companion_anims"] = len(comp)
            entry["donor_companion_anims"] = len(donor_comp)
        else:
            checks += [(N in own and N + 1 in own, "registered as own sprite (a humanoid body)"),
                       (not entry["roots"], "no monster attack roots")]
        entry["ok"] = all(ok for ok, _ in checks)
        entry["checks"] = [{"ok": bool(ok), "what": what} for ok, what in checks]
        problems += [f"{mod.name}: {what}" for ok, what in checks if not ok]
        table.append(entry)
    payload = dict(costumes=len(table), ok=not problems, problems=problems, table=table)
    if args.json:
        args.json.write_text(json.dumps(payload, indent=1) + "\n")
    print(json.dumps(payload, indent=1))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
