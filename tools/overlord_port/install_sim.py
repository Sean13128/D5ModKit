"""Install simulation: apply the converted Overlord package the way the installer would (offline).

No game folder, no archive and no profile is written.  Vanilla members come from the install's own
append-mode backup header (`baseline.py`), the two mod folders come from `package.convert`, and the
steps below are the ones `d5lib.modsys` + `d5lib.dbpatch` + `d5lib.ordercheck` perform:

  1. for each enabled mod, in load order: load the member, apply its row patch, put it back;
  2. once every mod is in: put Skill.dat back in id order (`dbpatch._finalize_order`);
  3. build the learned-evility manifest from the *finished* table (`learned.manifest_from_member`).

What it proves:
  * every member the package ships ends up **byte-identical** to Overlord v3's own file, so the
    conversion is lossless in the real composition order and not just per member;
  * the finished Skill.dat is id-sorted and every row the package adds sorts **above** every row the
    game ships, so no saved learned-evility bit changes meaning (`ordercheck.positional_errors`);
  * the ids the package appends are the ones the ownership manifest gives to Overlord.

Run:
    python tools/overlord_port/install_sim.py --mods <dir with the two mod folders> \
        --release "<extracted Overlord v3>" [--json receipt.json]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import baseline      # noqa: E402
import package       # noqa: E402

from d5lib import database, dbpatch, learned, ordercheck, ownership   # noqa: E402

MOD_ORDER = package.MOD_ORDER


def load_members(fs, names):
    out = {}
    for name in names:
        out[name] = baseline.read(fs, name)
    return out


def mod_order(mods_dir):
    """the pack's member order when the bundle has one, else the converter's order"""
    path = os.path.join(mods_dir, "packs.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            packs = (json.load(f).get("packs") or [])
        if packs and packs[0].get("members"):
            return tuple(packs[0]["members"])
    return MOD_ORDER


def apply_mods(fs, mods_dir, members, order=None):
    """the installer's db handler, in load order: each mod's patches onto the running member"""
    order = order or mod_order(mods_dir)
    log = []
    for mod in order:
        db = os.path.join(mods_dir, mod, "patches", "db")
        if not os.path.isdir(db):
            continue
        for fname in sorted(os.listdir(db)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(db, fname), encoding="utf-8") as f:
                patch = json.load(f)
            member = patch.get("table") or fname[:-5]
            table = database.load_table(member, members[member])
            warns = dbpatch.apply_patch(table, patch)
            members[member] = table.to_bytes()
            log.append({"mod": mod, "member": member,
                        "edited": len(patch.get("rows") or {}),
                        "inserted": sum(len(i.get("rows") or []) for i in patch.get("insert") or []),
                        "added": len(patch.get("added") or []),
                        "warnings": warns})
    return log


def finalize(members, vanilla):
    """the two finalizers that matter to this package: id order, then the learned manifest"""
    out = {}
    if "Skill.dat" in members:
        fixed, moved = ordercheck.sort_keyed("Skill.dat", members["Skill.dat"],
                                             vanilla=vanilla.get("Skill.dat"), log=None)
        members["Skill.dat"] = fixed
        out["skill_rows_reordered"] = moved
        ids = ordercheck._ids(database.load_table("Skill.dat", fixed))
        base_ids = ordercheck._ids(database.load_table("Skill.dat", vanilla["Skill.dat"]))
        out["positional_errors"] = ordercheck.positional_errors("Skill.dat", base_ids, ids)
        out["vanilla_rows"] = len(base_ids)
        out["final_rows"] = len(ids)
        out["added_ids"] = sorted(set(ids) - set(base_ids))
        out["lowest_added_position"] = min((ids.index(i) for i in out["added_ids"]), default=None)
        man = learned.manifest_from_member(fixed)
    if "char.dat" in members:
        # unit +0x2E0A is a char.dat *row*: a vanilla class row must keep its index
        from d5lib import overlord_import
        before = overlord_import.row_of_id(vanilla["char.dat"])
        after = overlord_import.row_of_id(members["char.dat"])
        moved = {i: [before[i], after[i]] for i in before if i in after and before[i] != after[i]}
        out["char_rows_moved"] = moved
        out["char_rows_added"] = sorted(set(after) - set(before))
        out["learned_manifest"] = {"row_count": man["row_count"], "base_count": man["base_count"],
                                   "ext_ids": man["ext_ids"],
                                   "generation": "0x%08x" % man["generation"]}
    return out


def simulate(mods_dir, release_dir, game_dir=None, json_path=None, exclude=()):
    fs = baseline.open_database(game_dir or baseline.DEFAULT_GAME)
    rel = os.path.join(release_dir, package.RELEASE_SUBDIR)
    target = {}
    for name in sorted(os.listdir(rel)):
        if name.lower().endswith(".dat") and os.path.exists(os.path.join(rel, name)):
            target[name] = open(os.path.join(rel, name), "rb").read()
    shipped = [n for n in target if n in set(baseline.members(fs))]
    members = load_members(fs, shipped)
    vanilla = dict(members)
    order = tuple(m for m in mod_order(mods_dir) if m not in set(exclude))
    applied = apply_mods(fs, mods_dir, members, order=order)
    fin = finalize(members, vanilla)
    per_member = {}
    for name in shipped:
        want = database.load_table(name, target[name]).to_bytes()
        per_member[name] = {"equal": members[name] == want}
    manifest = ownership.load()
    receipt = {
        "mods": os.path.abspath(mods_dir),
        "release": os.path.abspath(release_dir),
        "game_dir": os.path.abspath(fs.game_dir),
        "exe_sha256_pinned": "(not used: no executable is read)",
        "members": len(shipped),
        "mods_applied": list(m for m in (order if 'order' in dir() else [])),
        "byte_identical": sum(1 for v in per_member.values() if v["equal"]),
        "per_member": per_member,
        "applied": applied,
        "finalize": fin,
        "subset": bool(exclude),
        "verdict": ("ok" if (not fin.get("positional_errors") and not fin.get("char_rows_moved")
                             and (exclude or all(v["equal"] for v in per_member.values())))
                    else "mismatch"),
    }
    # ownership: what the package claims must be what the manifest gives Overlord
    receipt["ownership"] = _ownership_claims(mods_dir, manifest)
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=1, ensure_ascii=False)
    return receipt


def _ownership_claims(mods_dir, manifest):
    """every id the shipped mod folders add, checked against the ownership manifest"""
    from d5lib import modclaims
    ns = dict(modclaims.NAMESPACES)
    ns.setdefault("WishDataBase.dat", "wish_id")
    scan = modclaims.scan_mods(mods_dir)
    claims = []
    for member, ids in scan.added.items():
        namespace = ns.get(member)
        if not namespace:
            continue
        for rid in sorted(ids):
            holders = ", ".join(sorted(ids[rid]))
            claims.append(ownership.Claim(holders, namespace, rid, rid,
                                          label=f"{member} added row {rid}",
                                          evidence="converted from the Overlord v3 release"))
    findings = ownership.check_claims(manifest, claims)
    return {"claimed": len(claims),
            "namespaces": sorted({c.namespace for c in claims}),
            "findings": [f.as_dict() for f in findings],
            "errors": sum(1 for f in findings if f.severity == ownership.ERROR)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mods", required=True, help="directory holding 'Overlord Edition' and 'Overlord Rebalance'")
    ap.add_argument("--release", required=True)
    ap.add_argument("--game", default=baseline.DEFAULT_GAME)
    ap.add_argument("--json")
    ap.add_argument("--exclude", action="append", default=[],
                    help="skip this mod (repeatable): proves a subset is still coherent")
    a = ap.parse_args(argv)
    r = simulate(a.mods, a.release, a.game, a.json, exclude=a.exclude)
    print(json.dumps({k: r[k] for k in ("members", "mods_applied", "byte_identical", "verdict")}, indent=1))
    for name, v in r["per_member"].items():
        print(f"  {'same' if v['equal'] else 'DIFFERS':8s} {name}")
    f = r["finalize"]
    print(f"  Skill.dat: {f.get('vanilla_rows')} -> {f.get('final_rows')} rows, "
          f"{f.get('skill_rows_reordered')} re-ordered, {len(f.get('added_ids') or [])} added, "
          f"lowest added position {f.get('lowest_added_position')}")
    if f.get("positional_errors"):
        print("  BLOCKER: " + "; ".join(f["positional_errors"]))
    print(f"  learned manifest: {f.get('learned_manifest')}")
    print(f"  char.dat: {len(f.get('char_rows_moved') or {})} vanilla class row(s) moved, "
          f"{len(f.get('char_rows_added') or [])} added")
    return 0 if r["verdict"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
