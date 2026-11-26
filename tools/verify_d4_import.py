"""Check a finalized offline D4 class build against the D4 source, field by field (read-only).

  python tools/verify_d4_import.py --d4 "<D4 install>" --build <output of build_source_pack.py --finalize>

Compares, for every rank: base stats, aptitudes, gender, MOV / move type / attack range, JMP, throw, counter, crit,
Fire / Wind / Ice resistances, innate evilities (names and the D5 evility each works like) and learned skills
(names and levels) with what d5lib.d4source reads from D4, and checks the class spec (unlocked ranks, evility
aliases).  Prints one line per check and exits 1 on any mismatch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d5lib import anm, d4source, database, dbpatch, newclasses, sourcefidelity  # noqa: E402
from d5lib.sourceimports import load_d4_mapping  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--d4", required=True, type=Path)
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--mapping", type=Path)
    args = ap.parse_args()
    result = json.loads((args.build / "build-result.json").read_text())
    receipt = json.loads((args.build / "pilot-receipt.json").read_text())
    family, ids = receipt["family"], [r["id"] for r in receipt["source_ranks"]]
    out = args.build / "finalized-logical" / "Database" / "Database_0.dat"
    char = {r["id"]: r for r in database.load_table("char.dat", (out / "char.dat").read_bytes()).rows}
    skill = {r["id"]: r for r in database.load_table("Skill.dat", (out / "Skill.dat").read_bytes()).rows}
    # A class with no copied skill emits no magic.dat: the finalizer only writes tables a mod changes.
    magic_path = out / "magic.dat"
    magic = {r["id"]: r for r in database.load_table("magic.dat", magic_path.read_bytes()).rows} \
        if magic_path.is_file() else None
    spec = json.loads(next(Path(result["mod"]).glob("patches/classes/class_*.json")).read_text())
    mapping = load_d4_mapping(args.mapping)
    prof = d4source.D4Data(args.d4).class_profile(ids[0], len(ids))
    fails = 0

    def check(what, got, want):
        nonlocal fails
        ok = got == want
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {what}: {got}" + ("" if ok else f" (D4: {want})"))

    for k, src in enumerate(prof):
        row = char[family + k]
        tag = f"rank {k + 1} {row['title_EN']}"
        check(f"{tag} base", [row["base_" + s] for s in sourcefidelity.STATS], src["base"])
        check(f"{tag} aptitudes", [row["apt_" + s] for s in sourcefidelity.STATS], src["aptitudes"])
        for f, v in src["battle"].items():
            check(f"{tag} {f}", row[f] % 10 if f == "kind_gender" else row[f], v % 10 if f == "kind_gender" else v)
        innate = src["innate_evility"]
        want_ev = [innate["name"]] if mapping["evilities"].get(str(innate["id"]), {}).get("relation", "omit") != "omit" else []
        got_ev = [skill[row[f]]["name_EN"] for f in dbpatch.EVILITIES[:row["evility_count"]]]
        check(f"{tag} built-in (Unique) evilities", got_ev, want_ev)
        check(f"{tag} built-in kinds", [skill[row[f]]["kind"] for f in dbpatch.EVILITIES[:row["evility_count"]]],
              [1] * len(want_ev))
        want_sk = [(s["name"], s["level"]) for s in src["skills"]
                   if mapping["skills"].get(str(s["id"]), {}).get("relation", "omit") != "omit"]
        if magic is None:
            if row["learn_count"] or want_sk:
                check(f"{tag} skills (not checked: this build writes no magic.dat)", row["learn_count"], 0)
            continue
        got_sk = [(magic[row[f"learn{n}_skill"]]["name_EN"], row[f"learn{n}_level"]) for n in range(1, row["learn_count"] + 1)]
        check(f"{tag} skills", got_sk, want_sk)
    # Rank colours: a rank's unit uses char.dat color_id = family + rank, so rank k shows sprite palette k -- D4
    # palettes 0-5 are its six tiers and 6-9 the extra colours.  Ten identical banks are the "repeated palette 0"
    # defect reported from the first playtest, so an unauthentic bank is a failure here.
    physical = newclasses.sprite_family(family, spec)
    sprite_file = Path(result["mod"]) / "files/Anime/ANM_HI_JP.dat" / f"anm{physical:05d}.lzs"
    if sprite_file.is_file():
        sprite = anm.load(sprite_file.read_bytes())
        banks = [anm.get_palette(sprite, k) for k in range(len(sprite.palettes))]
        d4banks = d4source.D4Data(args.d4).body_palettes(receipt["source_ranks"][0]["body"])
        check("distinct colour banks", len({bank.tobytes() for bank in banks}), len(banks))
        for k, bank in enumerate(banks[:len(d4banks)]):
            have = {tuple(int(x) for x in colour[:3]) for colour in bank if colour[3]}
            want = {tuple(int(x) for x in colour[:3]) for colour in d4banks[k] if colour[3]}
            check(f"colour bank {k} colours outside D4 palette {k}", len(have - want), 0)

    # Engine path: a reviewed exact D4 evility is its own extension row (Skill.dat 8000 + D4 ID) instead of a
    # donor alias. Those rows satisfy the source list, so the alias/shop comparisons below must not expect them.
    d4_ids = {e["id"] for r in prof for e in [r["innate_evility"]] + r["evilities"]}
    exact = {r["id"]: r for r in skill.values()
             if r["owner"] == family and r["id"] >= 8000 and r["id"] - 8000 in d4_ids}
    exact_d4 = {i - 8000 for i in exact}
    source_names = {e["id"]: e["name"] for r in prof for e in [r["innate_evility"]] + r["evilities"]}
    check("exact extension rows are source-4 and own their D4 row",
          sorted({(r["source"], r["owner"]) for r in exact.values()}), [(4, family)] if exact else [])
    check("exact extension rows keep the D4 name", [exact[8000 + i]["name_EN"] for i in sorted(exact_d4)],
          [source_names[i] for i in sorted(exact_d4)])
    # D4 rank evilities: Common, learnable in the Skill Shop by this class only (character-owned, D4 mana)
    shop_want = {e["name"]: e.get("mana") for r in prof for e in r["evilities"]
                 if e["id"] not in exact_d4
                 and mapping["evilities"].get(str(e["id"]), {}).get("relation", "omit") != "omit"}
    shop_got = {r["name_EN"]: r["mana_cost"] for r in skill.values()
                if r["owner"] == family and r["kind"] == 0 and r["id"] not in exact}
    check("shop evilities (name: mana)", shop_got, shop_want)
    check("shop evilities are character-owned (source 4, shop rank 0)",
          sorted({(r["source"], r["shop_rank"]) for r in skill.values() if r["owner"] == family}), [(4, 0)])
    aliases = {int(a): b for a, b in spec.get("evility_alias", {}).items()}
    want_alias = {e["name"]: mapping["evilities"][str(e["id"])]["works_like"]
                  for e in [prof[-1]["innate_evility"]] + prof[-1]["evilities"]
                  if e["id"] not in exact_d4
                  and mapping["evilities"].get(str(e["id"]), {}).get("relation", "omit") != "omit"}
    check("evility aliases", {skill[a]["name_EN"]: b for a, b in aliases.items()}, want_alias)
    check("unlocked ranks", spec.get("unlocked_ranks"), len(ids))
    print(f"\n{fails} mismatch(es)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
