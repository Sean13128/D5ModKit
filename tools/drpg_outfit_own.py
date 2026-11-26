#!/usr/bin/env python3
"""DRPGOWN1: give Disgaea RPG outfits their own values from their DRPG unit (outfits.json `own_fields`).

For every outfit of a DRPG outfit pack (`d5lib/data/drpg_outfit_catalog.json`, slot <- DRPG unit through the pack's
`patches/outfits/drpg_units.json`), from data we already hold:

* evilities   -- the DRPG unit's own evilities that a mod already provides as working D5 evilities (a `Skill.dat` row
                 AND runtime rows in `patches/evilities/evilities.json` of some installed pack, ids from
                 `importers/drpg-evility-overlay.json`), in source slot order, then the character's own innate
                 evilities fill the free places; 4 at most.  Units with none built: group left out.
* base_stats  -- STATORACLE1's profile mapping (`statfidelity.drpg_map`, DECISION PENDING: SEANPICKS1), with the
                 character as donor and the character's DRPG twin (the unit drawn as the character) as the reference
                 instead of the RPG cast median: the character's row is reshaped by how the outfit's RPG lv1 profile
                 differs from the twin's (HP ATK DEF INT RES renormalised to the character's five-stat total, SPD
                 scaled on its own; SP and HIT the character's).  Same as the character: group left out.
* resistances -- the DRPG master's attr_fire / attr_water / attr_wind / attr_star copied to res_fire / res_ice /
                 res_wind / res_star (same scale: the twins of 21 of the 25 catalog characters equal the D5 row).
                 Same as the character: group left out.

Never filled (no source data or no established mapping): aptitudes, weapon_mastery (the RPG master has
weapon_mastery_rank_1..9 but no mapping to D5 mastery values exists), movement, weapon_resistances.

Copies each pack from --installed to --out and writes only `patches/outfits/outfits.json` (`outfits.set_own_fields`;
an outfit this tool fills nothing for has its own values cleared).  Writes MAPPING.json / MAPPING.md to --report.

  python tools/drpg_outfit_own.py --installed "<kit>/mods" --out Builds/DRPGOWN1-<date>/mods --report Builds/DRPGOWN1-<date>

Reading the RPG master needs UnityPy (not in the kit venv: PYTHONPATH=Local/runtime-pydeps/character-export), or
--master-cache (a JSON this tool writes with --write-cache; game data: scratch only, never the repo).
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from d5lib import modsys, outfits, statfidelity as sf  # noqa: E402

CATALOG = KIT / "d5lib/data/drpg_outfit_catalog.json"
OVERLAY = KIT / "d5lib/importers/drpg-evility-overlay.json"
D5_DB = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)/Data/Database/Database_0.dat")
STATS = sf.STATS                                   # HP SP ATK DEF INT RES HIT SPD
RES = (("res_fire", "attr_fire"), ("res_ice", "attr_water"), ("res_wind", "attr_wind"), ("res_star", "attr_star"))
MAX_INNATE = 4
STATS_LABEL = ("scaled: STATORACLE1 drpg_map (A2 source-profile mapping, DECISION PENDING SEANPICKS1), donor = the "
               "character's row, reference = the character's DRPG twin instead of the RPG cast median; SP, HIT the "
               "character's")
RES_LABEL = "exact: DRPG master attr_fire/water/wind/star -> res_fire/ice/wind/star (same % scale)"
SKIPPED = {
    "aptitudes": "no source data (the RPG master has no aptitudes; A2 keeps them donor)",
    "weapon_mastery": "RPG weapon_mastery_rank_1..9 exist but no mapping to D5 mastery values exists (not invented)",
    "movement": "no source data (the RPG master has no MOV/JMP/counter/throw/crit)",
    "weapon_resistances": "no source data",
}


# ------------------------------------------------------------------------------------------- source
def read_master(cache=None):
    """{DRPG character id: master row (dict)} from Disgaea Source masters/character, or from a cache JSON"""
    if cache and Path(cache).is_file():
        return {int(k): v for k, v in json.loads(Path(cache).read_text()).items()}
    import UnityPy
    env = UnityPy.load(str(sf.DRPG_MASTERS / "character"))
    obj = next(o for o in env.objects if o.type.name == "MonoBehaviour")
    return {int(r["id"]): r for r in obj.parse_as_dict()["DataList"]}


def rpg_base(r):
    """the master row's lv1 stats in D5 order (SP, HIT: None), as statfidelity.drpg_rows gives them"""
    return [r["hp_min"], None, r["atk_min"], r["def_min"], r["inte_min"], r["res_min"], None, r["spd_min"]]


def provided_evilities(mods_dir):
    """{evility id >= 28000: (pack, name_EN)} -- ids some pack gives both a Skill.dat row and runtime rows"""
    out = {}
    for d in sorted(Path(mods_dir).iterdir()):
        sk, ev = d / "patches/db/Skill.dat.json", d / "patches/evilities/evilities.json"
        if not (sk.is_file() and ev.is_file()):
            continue
        rows = json.loads(ev.read_text()).get("evilities") or {}
        for r in json.loads(sk.read_text()).get("added") or []:
            if int(r["id"]) >= 28000 and rows.get(str(r["id"])):
                out[int(r["id"])] = (d.name, r.get("name_EN", ""))
    return out


def vanilla_skill_names(db=D5_DB):
    try:
        from d5lib import database
        t = database.load_table("Skill.dat", database.load_database(str(db)).raw["Skill.dat"])
        return {int(r["id"]): r["name_EN"] for r in t.rows}
    except Exception:                                  # names are for the report only
        return {}


# ------------------------------------------------------------------------------------------- mapping
def evility_set(drpg_built, char_evs, cap=MAX_INNATE):
    """the outfit's innate evilities: the DRPG unit's built ones in source order, then the character's own, <= cap"""
    out = []
    for e in list(drpg_built) + list(char_evs):
        if e and e not in out:
            out.append(e)
    return out[:cap]


def map_stats(char_base, outfit_rpg, twin_rpg):
    """character base stats (8, D5 order) reshaped by outfit-vs-twin RPG lv1 profile (statfidelity.drpg_map)"""
    if any(not twin_rpg[k] for k in (0, 2, 3, 4, 5, 7)):
        return list(char_base)
    return sf.drpg_map(outfit_rpg, list(char_base), twin_rpg)


def map_res(rpg_row):
    return {f: max(-128, min(127, int(rpg_row[a]))) for f, a in RES}


def char_evilities(row):
    return [row[f"evility{i}"] for i in range(1, int(row.get("evility_count", 0)) + 1) if row[f"evility{i}"]]


def plan_pack(pack_dir, entry, master, overlay, provided, names, stats=True, res=True):
    """-> list of per-outfit dicts (groups to set + report fields) for one installed pack"""
    units = {int(k): int(v) for k, v in json.loads((pack_dir / "patches/outfits/drpg_units.json").read_text()).items()}
    rows = {int(r["id"]): r for r in json.loads((pack_dir / "patches/db/char.dat.json").read_text())["added"]}
    onames = {int(k): v for k, v in (json.loads((pack_dir / "patches/outfits/outfits.json").read_text())
                                     .get("names") or {}).items()}
    twin = master.get(entry["twin"])
    nm = lambda e: names.get(e) or (provided.get(e) or ("", ""))[1] or f"#{e}"      # noqa: E731
    out = []
    for unit, oname in entry["outfits"]:
        slot = units.get(int(unit))
        if slot is None or slot not in rows:
            continue
        row, src = rows[slot], master.get(int(unit))
        rec = dict(character=entry["name"], pack=pack_dir.name, slot=slot, outfit=onames.get(slot, oname),
                   drpg_unit=int(unit), drpg_name=(src or {}).get("name"), groups={}, skipped=dict(SKIPPED), labels={})
        # evilities
        base = overlay.get(str(unit))
        before = char_evilities(row)
        rec["evilities_before"] = [[e, nm(e)] for e in before]
        if base:
            built = [e["id"] for e in base["evilities"] if e["id"] in provided]
            unbuilt = [[e["id"], e["name_en"], e["cls"]] for e in base["evilities"] if e["id"] not in provided]
            if built:
                after = evility_set(built, before)
                rec["groups"]["evilities"] = {f"evility{i + 1}": (after[i] if i < len(after) else 0)
                                              for i in range(MAX_INNATE)}
                rec["evilities_after"] = [[e, nm(e)] for e in after]
                rec["labels"]["evilities"] = [dict(id=e["id"], slot=e["slot"], cls=e["cls"], label=e["label"],
                                                   provider=provided[e["id"]][0])
                                              for e in base["evilities"] if e["id"] in provided]
                rec["evilities_unbuilt"] = unbuilt
            else:
                rec["skipped_evilities"] = "the unit's evilities are decoded but none is built as a D5 evility"
        else:
            rec["skipped_evilities"] = ("not decoded: this DRPG unit is not one of the 146 DRPGEVIL1 census bases, "
                                        "so no D5 evility exists for it")
        if src is None or twin is None:
            rec["skipped_stats"] = rec["skipped_resistances"] = "no RPG master row"
            out.append(rec)
            continue
        # base stats
        cb = [row["base_" + s] for s in STATS]
        if stats:
            new = map_stats(cb, rpg_base(src), rpg_base(twin))
            rec["stats_before"], rec["stats_after"] = cb, new
            if new != cb:
                rec["groups"]["base_stats"] = {"base_" + s: v for s, v in zip(STATS, new)}
                rec["labels"]["base_stats"] = STATS_LABEL
            else:
                rec["skipped_stats"] = "the mapping gives the character's own stats"
        else:
            rec["skipped_stats"] = "--no-stats"
        # resistances
        if res:
            r_new, r_old = map_res(src), {f: row[f] for f, _ in RES}
            rec["res_before"], rec["res_after"] = r_old, r_new
            if r_new != r_old:
                rec["groups"]["resistances"] = r_new
                rec["labels"]["resistances"] = RES_LABEL
            else:
                rec["skipped_resistances"] = "same as the character"
        else:
            rec["skipped_resistances"] = "--no-resistances"
        out.append(rec)
    return out


def stage(installed, out_mods, recs_by_pack):
    """copy each pack, then set (or clear) every DRPG outfit's own values; only outfits.json changes"""
    for pack, recs in recs_by_pack.items():
        dest = Path(out_mods) / pack
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(Path(installed) / pack, dest, copy_function=shutil.copy2)
        mod = modsys.Mod(str(dest))
        for r in recs:
            outfits.set_own_fields(mod, r["slot"], r["groups"] or None)


# ------------------------------------------------------------------------------------------- report
def _ev(lst):
    return ", ".join(f"{e} {n}" for e, n in lst) or "-"


def write_report(recs, report_dir, meta):
    report_dir = Path(report_dir)
    (report_dir / "MAPPING.json").write_text(json.dumps(dict(meta=meta, outfits=recs), indent=1, ensure_ascii=False))
    n = len(recs)
    ev = sum("evilities" in r["groups"] for r in recs)
    st = sum("base_stats" in r["groups"] for r in recs)
    rs = sum("resistances" in r["groups"] for r in recs)
    none = sum(not r["groups"] for r in recs)
    L = [f"# DRPGOWN1 outfit own values ({meta['date']})", "",
         f"Tool `tools/drpg_outfit_own.py` (kit branch drpgown1). Outfits {n}: evilities {ev}, base stats {st}, "
         f"resistances {rs}, untouched {none}. Packs staged: {len(meta['packs'])}.", "",
         "Labels: evilities = the DRPGEVIL1/2 overlay label of each id (cls A exact, A+ adapted under the decided "
         "switches D1/D2/D4/L1); base stats = " + STATS_LABEL + "; resistances = " + RES_LABEL + ".", "",
         "Never filled: " + "; ".join(f"{k}: {v}" for k, v in SKIPPED.items()) + ".", "",
         "| character | slot | outfit | DRPG unit | groups | evilities before -> after | stats (HP SP ATK DEF INT RES "
         "HIT SPD) | res fire/ice/wind/star | skipped |", "|---|---|---|---|---|---|---|---|---|"]
    for r in recs:
        g = ", ".join(r["groups"]) or "none"
        evs = (f"{_ev(r['evilities_before'])} -> {_ev(r['evilities_after'])}" if "evilities" in r["groups"]
               else "unchanged")
        sts = (" ".join(map(str, r["stats_before"])) + " -> " + " ".join(map(str, r["stats_after"]))
               if "base_stats" in r["groups"] else "unchanged")
        rss = ("/".join(str(v) for v in r["res_before"].values()) + " -> " +
               "/".join(str(v) for v in r["res_after"].values()) if "resistances" in r["groups"] else "unchanged")
        sk = "; ".join(f"{k}: {r[k]}" for k in ("skipped_evilities", "skipped_stats", "skipped_resistances") if k in r)
        L.append(f"| {r['character']} | {r['slot']} | {r['outfit']} | {r['drpg_unit']} | {g} | {evs} | {sts} | {rss} "
                 f"| {sk} |")
    (report_dir / "MAPPING.md").write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--installed", required=True, help="the installed kit's mods folder (read only)")
    ap.add_argument("--out", required=True, help="staging mods folder")
    ap.add_argument("--report", required=True)
    ap.add_argument("--master-cache")
    ap.add_argument("--write-cache", action="store_true")
    ap.add_argument("--no-stats", action="store_true")
    ap.add_argument("--no-resistances", action="store_true")
    ap.add_argument("--date", default="")
    a = ap.parse_args(argv)
    master = read_master(a.master_cache)
    if a.write_cache and a.master_cache and not Path(a.master_cache).is_file():
        Path(a.master_cache).write_text(json.dumps({str(k): v for k, v in master.items()}, ensure_ascii=False))
    from d5lib.importers import _drpg_text      # TEXTHASH-DRPG: JP names are references; only name_en/cls/id are used here
    overlay = _drpg_text.load_authored(OVERLAY)["bases"]
    provided = provided_evilities(a.installed)
    names = vanilla_skill_names()
    names.update({k: v[1] for k, v in provided.items()})
    recs, by_pack = [], {}
    for entry in json.loads(CATALOG.read_text())["characters"]:
        pack = Path(a.installed) / entry["mod"]
        if not (pack / "patches/outfits/drpg_units.json").is_file():
            continue
        rs = plan_pack(pack, entry, master, overlay, provided, names, stats=not a.no_stats, res=not a.no_resistances)
        recs += rs
        by_pack[entry["mod"]] = rs
    os.makedirs(a.out, exist_ok=True)
    stage(a.installed, a.out, by_pack)
    write_report(recs, a.report, dict(date=a.date, packs=sorted(by_pack), installed=str(a.installed),
                                      catalog_missing=[e["mod"] for e in json.loads(CATALOG.read_text())["characters"]
                                                       if e["mod"] not in by_pack]))
    print(f"{len(recs)} outfits in {len(by_pack)} packs; report {a.report}/MAPPING.md")


if __name__ == "__main__":
    main()
