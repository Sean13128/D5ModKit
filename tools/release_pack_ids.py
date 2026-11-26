"""Re-lease one mod pack's colliding database ids from the ownership manifest (offline).

  python tools/release_pack_ids.py --pack "<mods>/D4_Class_1080" --mods-root "<mods>" \\
      --vanilla-database <pre-mod Database_0.dat> --out <out dir> [--json receipt.json]

  python tools/release_pack_ids.py ... --dry-run          # report the leases, copy nothing

What it does: reads the pack's `patches/db/*.json`, compares every id it appends with every *other* mod
folder's claims (144 installed folders here) and with the vanilla table, leases a fresh id from the
namespace band the manifest gives the kit (`evility_id` 7000+, `special_id` 13000+, `personality_id`
132+), and writes a fixed **copy** of the pack under `--out`.  Rows inside the pack that name one of the
re-leased ids (`char.dat` `evility1..4`, `learn*_skill`) are repointed, so the copy stays consistent.

Nothing is written to the pack, the installed kit, the game folder or a profile: the output is a new
folder.  Exit 1 if anything could not be fixed (a row-index patch conflict, no free id).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d5lib import modclaims, ownership, rellease     # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--pack", required=True, help="the mod folder to re-lease (read-only)")
    ap.add_argument("--mods-root", required=True, help="every installed mod folder (context for the scan)")
    ap.add_argument("--vanilla-database", required=True, help="a pre-mod Database_0.dat")
    ap.add_argument("--exclude", action="append", default=[],
                    help="a mod folder being replaced in the same build (repeat); ignored as context")
    ap.add_argument("--only", action="append", default=[], metavar="MEMBER:ID[,ID]",
                    help="lease only these claims, e.g. charPersonal.dat:132,133,134 (repeat). Default: "
                         "every claim of the pack that collides")
    ap.add_argument("--out", help="write the fixed copy of the pack here (required unless --dry-run)")
    ap.add_argument("--manifest", default=ownership.MANIFEST_PATH)
    ap.add_argument("--json", help="write the receipt to this path")
    ap.add_argument("--dry-run", action="store_true", help="report the leases, copy nothing")
    args = ap.parse_args(argv)

    pack = os.path.abspath(args.pack)
    root = os.path.abspath(args.mods_root)
    mod = os.path.basename(pack)
    if not os.path.isdir(os.path.join(root, mod)):
        ap.error(f"--pack {mod} is not a folder under --mods-root ({root})")

    only_ids = None
    for spec in args.only:
        member, _, ids = spec.partition(":")
        if not ids:
            ap.error(f"--only {spec}: expected MEMBER:ID[,ID]")
        only_ids = only_ids or {}
        only_ids.setdefault(member, set()).update(int(i) for i in ids.split(",") if i.strip())

    # Context is every mod folder on disk, not only the enabled profile: a leased id must be free for
    # any pack that is installed, or enabling the other pack later recreates the duplicate.
    names = set(modclaims._mod_folders(root))
    names -= set(args.exclude)
    names.add(mod)                                    # the pack is always scanned

    scan = modclaims.scan_mods(root, only=sorted(names))
    others = modclaims.Scan()
    others.mods = [m for m in scan.mods if m != mod]
    others.added = {k: {i: [h for h in hs if h != mod] for i, hs in v.items() if any(h != mod for h in hs)}
                    for k, v in scan.added.items()}
    others.patched = {k: {i: [h for h in hs if h != mod] for i, hs in v.items() if any(h != mod for h in hs)}
                      for k, v in scan.patched.items()}
    others.payloads = {(k, i): {h: p for h, p in v.items() if h != mod}
                       for (k, i), v in scan.payloads.items() if any(h != mod for h in v)}
    others.patch_payloads = {(k, i): {h: p for h, p in v.items() if h != mod}
                             for (k, i), v in scan.patch_payloads.items() if any(h != mod for h in v)}

    vanilla = modclaims.vanilla_names(args.vanilla_database)
    manifest = ownership.load(args.manifest)
    plan = rellease.plan(pack, others, vanilla, manifest, only_ids=only_ids)

    receipt = plan.as_dict()
    receipt["context"] = dict(mods_root=root, excluded=sorted(args.exclude),
                              other_mods=len(others.mods), only=args.only or None)
    if not args.dry_run:
        if not args.out:
            ap.error("--out is required unless --dry-run")
        receipt.update(rellease.apply(pack, os.path.abspath(args.out), plan))

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2)
            fh.write("\n")

    print(f"{mod}: {len(plan.leases)} lease(s), {len(plan.findings)} unfixable, "
          f"context {len(others.mods)} other mod(s){' (dry run)' if args.dry_run else ''}")
    for lease in plan.leases:
        print(f"  {lease}  <- {lease.reason}")
    for kind, member, rid, detail in plan.findings:
        print(f"  UNFIXABLE {kind} {member}[{rid}]: {detail}")
    return 0 if plan.ok else 1


if __name__ == "__main__":
    sys.exit(main())
