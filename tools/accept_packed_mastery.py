"""Acknowledge that a packed mastery install (.d5pm) supersedes the six-slot mastery leases (offline).

    python tools/accept_packed_mastery.py                 # acknowledge every family in the lease file
    python tools/accept_packed_mastery.py --dry-run       # show what would be acknowledged
    python tools/accept_packed_mastery.py --state-dir DIR  # a copy of the state folder (tests, rehearsals)

Why this exists: the packed hook keeps a family's progress in a pool that reuses slots 47..52 of the
unit record, which are the six slots the `.d5cm` extension leases.  A packed build therefore cannot read
counters a save wrote for a six-slot install.  The install refuses while a lease is unacknowledged
(`d5lib.packedmasteryhook.acknowledged_leases`), so nothing is ever dropped silently; this tool writes that
acknowledgement into the lease file and records *what* was given up.  It does not migrate a save: carrying
progress over is a separate copied-save operation (`d5lib/masterymigration.py`), because it rewrites units
in a save file.

Nothing here launches the game, installs, or writes outside the lease file named on the command line.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d5lib import masteryext, modsys, paths   # noqa: E402


def lease_file(state_dir=None):
    """the mastery lease file of this game folder (or of `state_dir`)"""
    override = os.environ.get("D5_MASTERY_LEASE_DIR")
    if override:
        return os.path.join(override, masteryext.LEASE_FILE)
    if state_dir:
        return os.path.join(state_dir, masteryext.LEASE_FILE)
    return os.path.join(modsys.game_state_dir(paths.require_game_dir()), masteryext.LEASE_FILE)


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--state-dir", help="a game state folder (state/games/<game>) instead of the installed game")
    ap.add_argument("--families", nargs="*", type=int, default=None,
                    help="only these families (default: every family in the lease file)")
    ap.add_argument("--dry-run", action="store_true", help="print the acknowledgement, write nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    args = ap.parse_args(argv)

    path = lease_file(args.state_dir)
    if not os.path.exists(path):
        raise SystemExit(f"no mastery lease file at {path}: nothing to acknowledge "
                         f"(a build without six-slot leases needs no acknowledgement)")
    leases = masteryext.SlotLeases.load(path, log=lambda *_: None)
    held = dict(leases.retired)
    held.update(leases.slots)
    if not held:
        raise SystemExit(f"{path} holds no six-slot lease: nothing to acknowledge")
    wanted = sorted(held) if args.families is None else sorted({int(f) for f in args.families})
    unknown = [f for f in wanted if f not in held]
    if unknown:
        raise SystemExit(f"not in {path}: {', '.join(map(str, unknown))} (held: {', '.join(map(str, sorted(held)))})")

    ack = leases.acknowledge_packed(wanted)
    result = {"lease_file": path, "acknowledged": wanted,
              "slots": {str(f): held[f] for f in wanted},
              "dry_run": bool(args.dry_run), "packed_ack": ack}
    if not args.dry_run:
        leases.save()
        again = masteryext.SlotLeases.load(path, log=lambda *_: None)
        if sorted(int(f) for f in (again.packed_ack.get("families") or ())) != wanted:
            raise SystemExit(f"{path}: the acknowledgement did not survive the write")
        result["verified"] = True
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"lease file: {path}")
    for fam in wanted:
        print(f"  {fam} -> slot {held[fam]}{' (retired)' if fam in leases.retired and fam not in leases.slots else ''}")
    print(("would acknowledge" if args.dry_run else "acknowledged")
          + f" {len(wanted)} family(ies): a packed (.d5pm) install may now replace this mapping.")
    print("Their saved class counters stop being read.  To carry progress over, copy the save and migrate the "
          "copy with d5lib/masterymigration.py; this tool does not touch a save.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
