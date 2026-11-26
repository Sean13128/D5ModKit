"""Offline finalization + validators for the DRPG 3-character sample.

Runs the Kit's own finalizer over the three sample mods (in memory: modsys.build writes no game file),
reads every row it produced back, validates the `.d5el` evility table the installer would emit, and checks
the ownership claims against the manifest.  Nothing is installed, nothing is launched.

    python3 tools/finalize_drpg_sample.py --game "<game copy>" --mods <build>/mods --claims <build>/drpg-sample-claims.json \
        --out <build>/drpg-sample-finalization.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

DB0 = "Database/Database_0.dat/"
CHARS = {233: "Melodia", 234: "Citri Smart", 235: "Noel"}
EVILITIES = (7100, 7110, 7120, 7121)
# the sprite lease per character is read from the build receipt (blocks of three are handed out at build time)
SPRITES: dict = {}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", required=True, type=Path)
    ap.add_argument("--mods", required=True, type=Path)
    ap.add_argument("--claims", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    from d5lib import database, evility, gamefs, modsys, ownership, sprites
    import d5lib.anm as anm

    mods = [modsys.Mod(str(d)) for d in sorted(args.mods.iterdir()) if d.is_dir()]
    build_receipt = json.loads((args.mods.parent / "drpg-sample-receipt.json").read_text())
    SPRITES.update({c["char_row"]: c["sprite"] for c in build_receipt["characters"]})
    receipt: dict = dict(schema="drpg-sample-finalization/1", mods=[m.id for m in mods], checks={}, notes=[])
    fs = gamefs.GameFS(str(args.game))
    try:
        logs = []
        ctx = modsys.build(fs, mods, log=lambda s: logs.append(s))
        # write the finalized members next to the receipt so the smoke manifest can bind them by hash
        import hashlib
        fin = args.out.parent / "finalized"
        files = []
        for _, (vpath, raw) in sorted(ctx.outputs.items()):
            target = fin / vpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            files.append(dict(path=vpath, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        receipt["build"] = dict(outputs=sorted(ctx.outputs), files=files, root=str(fin),
                                log=[l for l in logs if l][-12:],
                                skipped_features=list(getattr(ctx, "skipped_features", [])))
        char = database.load_table("char.dat", ctx.get(DB0 + "char.dat"))
        skill = database.load_table("Skill.dat", ctx.get(DB0 + "Skill.dat"))
        magic = database.load_table("magic.dat", ctx.get(DB0 + "magic.dat"))
        help_t = database.load_table("charhelp.dat", ctx.get(DB0 + "charhelp.dat"))
        quest = database.load_table("Quest.dat", ctx.get(DB0 + "Quest.dat"))

        rows = {}
        for cid, name in CHARS.items():
            row = char.find(cid)
            if row is None:
                receipt["checks"][f"char_{cid}"] = None
                continue
            learn = [(row[f"learn{k}_skill"], row[f"learn{k}_level"]) for k in range(1, row["learn_count"] + 1)]
            rows[cid] = dict(
                added=True, name=row["name_EN"], title=row["title_EN"], sprite_id=row["sprite_id"],
                body_type=row["body_type"], help_id=row["help_id"], voice_id=row["voice_id"],
                evilities=[row[f"evility{k}"] for k in range(1, row["evility_count"] + 1)],
                learn=learn,
                name_matches=row["name_EN"] == name,
                learn_resolves=all(magic.find(s) is not None for s, _ in learn),
                sprite_is_leased=row["sprite_id"] == SPRITES[cid],
                humanoid=row["body_type"] == 0)
            hrow = help_t.find(row["help_id"])
            rows[cid]["help"] = None if hrow is None else [hrow[f"line{k}_EN"] for k in (1, 2, 3)]
            rows[cid]["help_ok"] = bool(hrow) and bool(rows[cid]["help"][0]) and not any(
                bad in " ".join(rows[cid]["help"]).upper() for bad in ("TODO", "FIXME", "PLACEHOLDER"))
        receipt["checks"]["characters"] = rows

        ev = {}
        for evid in EVILITIES:
            r = skill.find(evid)
            ev[str(evid)] = None if r is None else dict(name=r["name_EN"], owner=r["owner"],
                                                        effect_group=r["effect_group"], kind=r["kind"])
        receipt["checks"]["evilities"] = ev
        receipt["checks"]["evilities_ok"] = all(
            v and v["effect_group"] == 0 and v["owner"] in CHARS for v in ev.values())

        # the .d5el table the evility builder would emit -- the same call the installer makes
        merged = {"evilities": {}}
        for m in mods:
            for k, v in (evility.load(m).get("evilities") or {}).items():
                merged["evilities"][k] = v
        table_rows, conds, fx = evility.table(merged["evilities"])
        receipt["checks"]["evility_table"] = dict(
            ids=[r[0] for r in table_rows], masks=[r[1] for r in table_rows],
            rows=len(table_rows), conditions=len(conds), effects=len(fx))
        receipt["checks"]["evility_table_valid"] = len(table_rows) == len(EVILITIES)

        # quests: one recruit bill per character, reward = the character
        q = {}
        for cid in CHARS:
            hit = [r for r in quest.rows if r["id"] > 0 and r.get("reward_type") == 5
                   and r.get("reward_value") == cid]
            q[str(cid)] = None if not hit else dict(id=hit[0]["id"], title=hit[0]["name_EN"],
                                                   desc1=hit[0]["desc1_EN"])
        receipt["checks"]["quests"] = q
        receipt["checks"]["quests_ok"] = all(q.values())

        # ANM members read back with the kit's reader and carry the leased numbers
        members = {}
        root = args.out.parent / "mods"
        for m in mods:
            d = Path(m.folder) / "files/Anime/ANM_HI_JP.dat"
            for p in sorted(d.glob("anm*.lzs")):
                a = anm.load(str(p))
                members[f"{m.id}/{p.name}"] = dict(block_id=a.blocks[0].id,
                                                   animations=len(a.blocks[0].animations),
                                                   cells=len(a.blocks[0].cells), palettes=len(a.palettes))
        receipt["checks"]["anm_members"] = members
        receipt["checks"]["anm_ok"] = all(
            int(k.split("/")[-1][3:8]) == v["block_id"] for k, v in members.items()) and bool(members)

        # ownership: the claims against the manifest, and that no other holder takes them
        man = ownership.load()
        claims = ownership.load_claims(str(args.claims))
        findings = ownership.check_claims(man, claims)
        receipt["ownership"] = dict(claims=len(claims),
                                    errors=[f.as_dict() for f in ownership.errors(findings)],
                                    warnings=[f.as_dict() for f in findings if f.severity == "warning"],
                                    manifest_errors=[f.as_dict() for f in ownership.check_manifest(man)])
        receipt["ok"] = (all(v.get("added") for v in rows.values() if v)
                         and all(rows[c]["name_matches"] and rows[c]["learn_resolves"]
                                 and rows[c]["sprite_is_leased"] and rows[c]["humanoid"]
                                 and rows[c]["help_ok"] for c in CHARS)
                         and receipt["checks"]["evilities_ok"]
                         and receipt["checks"]["evility_table_valid"]
                         and receipt["checks"]["quests_ok"]
                         and receipt["checks"]["anm_ok"]
                         and not receipt["ownership"]["errors"])
    finally:
        fs.reset()
    args.out.write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(dict(ok=receipt["ok"], checks={k: v for k, v in receipt["checks"].items()
                                                    if k.endswith(("_ok", "_valid"))},
                          outputs=len(receipt["build"]["outputs"]),
                          ownership_errors=len(receipt["ownership"]["errors"])), indent=1))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
