#!/usr/bin/env python3
"""Create a private typed scene dry-run; emit bytecode only for a fully closed reviewed scene."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
from d5lib import d4source, d4scripts, offlinepaths, script  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--d4", type=Path, required=True)
    ap.add_argument("--lang", default="EN")
    ap.add_argument("--skill", type=int, default=13082)
    ap.add_argument("--receiver-script", type=Path, required=True, help="explicit read-only original D5 script snapshot")
    ap.add_argument("--contracts", type=Path)
    ap.add_argument("--occupied", type=Path, help="complete original/all-mod event snapshot with source hash and evidence")
    ap.add_argument("--event-start", type=int, default=16500000)
    ap.add_argument("--output", type=Path, required=True, help="new private result directory")
    ap.add_argument("--emit", action="store_true", help="require a fully reviewed scene, otherwise fail without bytecode")
    args = ap.parse_args(argv)
    try:
        output = offlinepaths.offline_output(args.output, (REPOSITORY, args.d4, args.receiver_script,
                                                           args.contracts, args.occupied))
    except ValueError as exc:
        ap.error(str(exc))
    if output.exists():
        ap.error("output must be a new private directory outside the repository and source game")
    raw = d4source.D4Data(args.d4, args.lang).db.read("script.dat")
    source, receiver = d4scripts.Source(raw, args.lang), d4scripts.Receiver(args.receiver_script.read_bytes())
    contracts = json.loads(args.contracts.read_text()) if args.contracts else None
    occupancy = json.loads(args.occupied.read_text()) if args.occupied else None
    report, bundle = d4scripts.translate_scene(source, receiver, args.skill, contracts,
                                              occupancy=occupancy, event_start=args.event_start)
    report["provenance"] = dict(source_root=str(args.d4.resolve()), receiver_snapshot=str(args.receiver_script.resolve()),
                                contracts_sha256=d4scripts.sha(args.contracts.read_bytes()) if args.contracts else None,
                                occupancy_sha256=d4scripts.sha(args.occupied.read_bytes()) if args.occupied else None,
                                tools={str(p.relative_to(REPOSITORY)): d4scripts.sha(p.read_bytes())
                                       for p in (REPOSITORY / "d5lib/d4scripts.py", REPOSITORY / "tools/translate_d4_scene.py",
                                                 REPOSITORY / "d5lib/d4inventory.py", Path(script.__file__),
                                                 Path(offlinepaths.__file__))})
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if args.emit and bundle is not None:
        (output / "translated-script.dat").write_bytes(bundle)
        readback = script.ScriptFile.from_bytes((output / "translated-script.dat").read_bytes(), strict=True)
        if readback.to_bytes() != bundle:
            raise ValueError("saved script readback mismatch")
        (output / "translated-events.txt").write_text(readback.disassemble())
    print(json.dumps(dict(output=str(output), status=report["status"], **report["summary"]), indent=2))
    if args.emit and bundle is None:
        print("Scene blocked: inspect manifest; no translated bytecode was written.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
