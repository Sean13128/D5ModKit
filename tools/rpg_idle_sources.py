"""Export portable idle source clocks/PNGs from the player's own RPG bundles."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import rpgclips
from repair_outfit_idles import costume_resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rpg-root",
        action="append",
        required=True,
        type=Path,
        help="Local raw RPG root containing prefabs/characters and atlas/chara/battle",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="New source-data folder"
    )
    parser.add_argument("--kit", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--uids",
        help="Comma-separated unit IDs; otherwise all known costume units in --kit",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new source-data folder")
    units = sorted(
        {int(u) for u in args.uids.split(",")}
        if args.uids
        else {r["uid"] for r in costume_resources(args.kit)}
    )
    if not units:
        parser.error(
            "No RPG costume units found; select an installed release kit or pass --uids"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".rpg-idle-", dir=args.output.parent
    ) as temporary:
        staging = Path(temporary) / "sources"
        staging.mkdir()
        body, evidence = {}, {}
        for uid in units:
            unit, audit = rpgclips.export_unit(uid, args.rpg_root, staging)
            body[str(uid)], evidence[str(uid)] = unit, audit
            print(f"Exported unit {uid}", flush=True)
        (staging / "rpg-idle-timings.json").write_text(
            json.dumps({"units": body}, indent=2), encoding="utf-8"
        )
        (staging / "evidence.json").write_text(
            json.dumps({"units": evidence}, indent=2), encoding="utf-8"
        )
        if args.output.exists():
            raise FileExistsError(args.output)
        os.rename(staging, args.output)
    print(args.output / "rpg-idle-timings.json")


if __name__ == "__main__":
    main()
