"""Stage a separate source-clock override for existing RPG costume mods."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import anm, rpgidle

# Older shipped Girl Laharl looks predate drpg_units.json. These are their exact
# known RPG appearances; row-patch keys are row indices, not class IDs.
LEGACY = {
    470: (68, 9550),
    480: (103, 9530),
    490: (258, 9540),
    950: (192, 9560),
    960: (193, 9570),
    980: (294, 9580),
    990: (332, 9590),
    471: (348, 9660),
    472: (378, 9670),
}
THUNDERLADY = {253: 192, 254: 294, 255: 348, 256: 403}


def costume_resources(kit):
    """Inventory known appearance-to-unit links; never alter kit settings/mods."""
    kit = Path(kit)
    resources = []
    for mod in sorted((kit / "mods").iterdir()):
        outfit = mod / "patches/outfits/outfits.json"
        db = mod / "patches/db/char.dat.json"
        if not outfit.is_file() or not db.is_file():
            continue
        definition = json.loads(outfit.read_text(encoding="utf-8"))
        rows = json.loads(db.read_text(encoding="utf-8")).get("added", [])
        mapping = mod / "patches/outfits/drpg_units.json"
        units = (
            {
                value: int(key)
                for key, value in json.loads(
                    mapping.read_text(encoding="utf-8")
                ).items()
            }
            if mapping.is_file()
            else {}
        )
        if mod.name == "Girl_Laharl_Outfits":
            units.update({slot: item[0] for slot, item in LEGACY.items()})
            rows += [
                {"id": slot, "sprite_id": number}
                for slot, (_, number) in LEGACY.items()
                if not any(row["id"] == slot for row in rows)
            ]
        if mod.name == "Thunderlady":
            units.update(THUNDERLADY)
        for row in rows:
            uid = units.get(row["id"])
            if uid is None:
                continue  # A hand-painted/non-RPG outfit has no claimed RPG clock.
            for number in (row["sprite_id"], row["sprite_id"] + 1):
                path = mod / f"files/Anime/ANM_HI_JP.dat/anm{number:05}.lzs"
                if (
                    number not in definition.get("own_sprites", [])
                    or not path.is_file()
                ):
                    continue
                sprite = anm.load(path)
                if not {6001, 6007} <= {a.id for a in sprite.blocks[0].animations}:
                    continue  # A reduced nonbody resource has no idle track to retime.
                resources.append(
                    {
                        "mod": mod.name,
                        "class": row["id"],
                        "uid": uid,
                        "sprite": number,
                        "name": definition.get("names", {}).get(
                            str(row["id"]), str(row["id"])
                        ),
                        "path": path,
                    }
                )
    if len({r["sprite"] for r in resources}) != len(resources):
        raise ValueError("Duplicate costume sprite owner")
    return resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-timings", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New override-mod folder; never installs game data",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; use a new override-mod folder")
    units = rpgidle.load_units(args.source_timings)
    resources = costume_resources(args.kit)
    if not resources:
        parser.error("No RPG costume resources found in --kit")
    missing = sorted({r["uid"] for r in resources} - {int(uid) for uid in units})
    if missing:
        parser.error("Missing source timing units: " + ", ".join(map(str, missing)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".idle-mod-", dir=args.output.parent
    ) as temporary:
        staging = Path(temporary) / "mod"
        files = staging / "files/Anime/ANM_HI_JP.dat"
        files.mkdir(parents=True)
        audit = []
        for item in resources:
            raw = item["path"].read_bytes()
            sprite, loops = rpgidle.repair_sprite(
                anm.load(raw), units[str(item["uid"])]
            )
            data = sprite.to_bytes()
            (files / item["path"].name).write_bytes(data)
            audit.append(
                {k: v for k, v in item.items() if k != "path"}
                | {
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "output_sha256": hashlib.sha256(data).hexdigest(),
                    "loops": loops,
                }
            )
            print(f"Repaired {item['name']} ({item['sprite']})", flush=True)
        (staging / "mod.json").write_text(
            json.dumps(
                {
                    "name": "RPG Costumes — Original Idle Timing",
                    "version": "1.0",
                    "description": "Original RPG idle pose clocks with coupled attachments and planted feet.",
                    "requires": sorted({r["mod"] for r in resources}),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (staging / "idle-audit.json").write_text(
            json.dumps(audit, indent=2), encoding="utf-8"
        )
        if args.output.exists():
            raise FileExistsError(args.output)
        os.rename(staging, args.output)
    print(
        f"Staged {len(resources)} bodies. Enable this mod last, then Install & Play with the game closed."
    )


if __name__ == "__main__":
    main()
