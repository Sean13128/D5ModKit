#!/usr/bin/env python3
"""DRPGSKILL1: turn the private Disgaea RPG skill census into the kit's reviewed skill overlay.

    python tools/build_drpg_skill_overlay.py SOURCE_CENSUS.json PACKS[:PACKS2...] [--census-out FILE] [--check]

SOURCE_CENSUS.json is Subprojects/Engine-Extensions/drpg-skill-map/drpg_skills_source.json (made from the JP
client masters; private, never committed).  PACKS are folders of built DRPG packs (the installed mods): a pack
gives the body (bank and body type) the stand-in's caster motions are checked against, and the D5 lookalike the
earlier mapping lane reviewed for each source command.  The overlay (d5lib/importers/drpg-skill-overlay.json)
holds only the derived mapping the importer applies (per own row: the stand-in's id, its row's sha256 and the
fields that differ; no game row); it is read at build time and never recomputed there.
--census-out writes the per-character census with the final class of every skill (private, source text).

Rules (each is written into the overlay's `rules` and onto every row's label):
  E  the source name is a D5 magic.dat JP name (exact string, one row) -> the D5 row itself.
  A  own row, id 17000 + 4 * lease position + n: a copy of a stand-in D5 skill (its animation, range and area)
     with the source's SP (skill level 1), element (water -> ice), damage stat (ATK / INT) and power:
     D5 reads  effect value + level table - 100  (FUN_1401D7A20), so effect value = source level-1 percent - 100
     and the level table runs 100 .. 100 + (source level-50 percent - level-1 percent).
     Support rows (stat change / ailment as the main effect) are copies of the D5 spell of that effect; their level
     table is the magnitude itself (formula 5 / 6), source level 1 .. level 50.
     Added effects on the same targets that D5 has as an effect slot (stat down, poison, sleep, paralysis,
     amnesia) are written with the source's number; every other added effect is dropped and listed.
  X  the main effect has no D5 skill-row meaning (heal amounts, gauge, revive ...): nothing built, the pack's
     D5 lookalike stays and is labelled donor.
Stand-in for a damage skill: the lookalike the pack already carries for that command when it has the same target
class and its caster motions exist on every body of the pack (skillmotions: ok / fallback, never missing);
otherwise the D5 unique / class / monster damage skill of the same target class with, in order: motions present,
same element, same damage stat, not already used by this character, nearest tier, nearest SP.
"""
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
IMP = KIT / "d5lib/importers"
OUT = IMP / "drpg-skill-overlay.json"
NAMES = IMP / "drpg-skill-names.json"
BAND = (17000, 17599)
ELEMENT = {"none": 0, "fire": 1, "wind": 2, "water": 3, "star": 4}       # DRPG water -> D5 ice (its water spell is D5's ice spell)
ELEMENT_EN = {0: "", 1: "Fire ", 2: "Wind ", 3: "Ice ", 4: "Star "}
STAT_EN = {11: "ATK", 12: "DEF", 13: "INT", 14: "RES", 16: "SPD"}
AIL_EN = {21: "Poison", 22: "Sleep", 23: "Paralysis", 24: "Amnesia"}
ENEMY = ("enemy single", "enemy all")
RULES = dict(
    E="source name == a D5 magic.dat JP name (exact, one row): the D5 row itself is linked",
    A_power="damage: effect1_value = source level-1 percent - 100; power_lv1..10 = 100 .. 100 + (level-50 percent - level-1 percent), linear (D5 reads effect value + level table - 100, FUN_1401D7A20)",
    A_support="stat change / ailment as main effect: copy of the D5 spell of that effect, power_lv1..10 = source level-1 .. level-50 magnitude (formula 5 / 6 rows read the level table as the magnitude)",
    A_sp="sp_cost = source SP at skill level 1 (the RPG cost falls with level, D5's rises: D5's own rule applies from there)",
    A_element="fire 1, wind 2, star 4, water -> ice 3 (the RPG's water spell is D5's ice spell)",
    A_stat="relational_param 2 -> formula 2 (ATK), 4 -> formula 3 (INT)",
    A_target="the RPG has no map: one enemy -> a one-panel stand-in, all enemies -> a multi-panel stand-in; range and area are the stand-in's own",
    A_riders="added effects on the skill's own targets that D5 has as an effect slot keep the source number; all others are dropped and listed per skill",
    unlock="charactercommand.lv (character level 1 / 50 / 200) is the learn level, verbatim",
    X="main effect without a D5 skill-row meaning: not built, the pack's D5 lookalike stays (donor)",
    M1="weapon-mastery spells (charactermagiccommand) that D5 has under the same name are learned at character level = the source's weapon mastery level; OFF until decided",
    C1="drop the D5 lookalikes of the costume looks' skills from the learn list; OFF until decided",
)


def packs(roots):
    out = {}
    for root in reversed(roots):
        for d in sorted(Path(root).glob("DRPG_*")):
            m = d / "mod.json"
            if not m.is_file():
                continue
            c = ((json.loads(m.read_text()).get("source_import") or {}).get("source") or {})
            c = c.get("character") if isinstance(c, dict) else None
            if c and "base_id" in c:
                out[int(c["base_id"])] = d
    return out


def main(argv):
    check = "--check" in argv
    argv = [a for a in argv if a != "--check"]
    census_out = None
    if "--census-out" in argv:
        i = argv.index("--census-out")
        census_out = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    src = json.loads(Path(argv[0]).read_text())
    folders = packs([Path(x) for x in argv[1].split(":")])
    from d5lib.importers import _drpg_text        # TEXTHASH-DRPG: the files hold hashes and @authored; resolved here
    names = _drpg_text.load(NAMES)["names"] if NAMES.exists() else {}
    twins = _drpg_text.load(IMP / "drpg-skill-twins.json")["packs"]
    leases = {int(b["lease"].split(":")[1]): b for b in _drpg_text.load(IMP / "drpg-leases.json")["bases"]}

    from d5lib import database, dbpatch, newclasses, skillmotions, skills
    from d5lib.importers import drpg_skills
    shas = {}
    sv = skillmotions.Survey()
    fs = sv.fs
    magic = database.load_table("magic.dat", fs.read("Database/Database_0.dat/magic.dat"))
    amap = {int(r["id"]): int(r["cell_num"]) for r in
            database.load_table("AttackMap.dat", fs.read("Database/Database_0.dat/AttackMap.dat")).rows}
    van = {int(r["id"]): r for r in magic.rows}
    by_jp = {}
    for r in magic.rows:
        by_jp.setdefault(r["name_JP"], []).append(int(r["id"]))
    scripts = skills.vanilla_scripts(fs)
    events = set(scripts.ev)

    def changed(donor, row):
        """the fields of an own row that differ from its stand-in's (text once, EN: the importer writes every language)"""
        a, b = dbpatch._row_values(donor), dbpatch._row_values(row)
        return {k: v for k, v in b.items() if a[k] != v and not k.endswith(("_JP", "_FR", "_CHN", "_KOR"))}

    def cells(r):
        return amap.get(int(r["attack_map"]), 0)

    pool = [r for r in magic.rows if int(r["effect1_type"]) == 1 and int(r["formula"]) in (2, 3)
            and int(r["skill_group"]) in (7, 8, 9) and not int(r["partner_count"]) and not int(r["moves_units"])
            and not int(r["tower_units"]) and 10000 < int(r["id"]) < 13000 and int(r["sp_cost"]) > 0
            and not 10051 <= int(r["id"]) <= 10059 and not int(r["base_skill"])
            and all(int(r[f"effect{i}_type"]) < 100 for i in range(2, 7)) and cells(r) >= 1
            and scripts.root_of(int(r["id"])) is not None]
    spell = {}      # (code, sign) -> the D5 spell of that effect
    for r in magic.rows:
        if 1500 < int(r["id"]) < 1800 and int(r["rank"]) <= 1:
            spell.setdefault((int(r["effect1_type"]), 1 if int(r["effect1_value"]) >= 0 else -1), r)

    def status(folder, sid):
        """worst skillmotions status of D5 skill `sid` over every char row (body) of the pack"""
        rows = json.loads((folder / "patches/db/char.dat.json").read_text())["added"]
        st = {sv._status(folder, row, sid)["status"] for row in rows}
        return next(s for s in ("unknown", "missing", "fallback", "ok") if s in st)

    doc = dict(schema="drpg-skill-overlay/1", lane="DRPGSKILL1", band=list(BAND),
               id_rule="17000 + 4 * position in drpg-leases.json bases + n (n = the skill's place among the base's own skills, 0-2); recorded per row",
               source="JP client masters command / charactercommand / charactermagiccommand (sha256 in the census file); Global not used",
               source_sha256=src["sha256"], decisions=dict(M1=False, C1=False), rules=RULES,
               names_label="provisional literal translations (DRPGSKILL1), to be read through like the titles", bases={})
    census = dict(lane="DRPGSKILL1", sha256=src["sha256"], decode=src["decode"], rules=RULES, characters=[])
    missing_names, counts = [], {}
    for ch in src["characters"]:
        bid, pos = ch["base_id"], ch["lease_position"]
        folder = folders.get(bid)
        if folder is None:
            raise SystemExit(f"no pack folder for base {bid} {ch['name']}")
        meta = json.loads((folder / "mod.json").read_text())
        tw = twins.get(folder.name) or {}
        prior = {}
        for c in meta["source_import"]["source"]["character"].get("commands") or []:
            if c.get("d5_id") and c.get("verdict") != "omit":
                prior[int(c["rpg_id"])] = int((tw.get(str(c["d5_id"])) or {}).get("twin", c["d5_id"]))
        used, out_sk, cen_sk = set(), [], []
        for n, s in enumerate(ch["skills"]):
            main = s["effects"][0]
            e = dict(n=n, rpg_id=s["rpg_id"], name_jp=s["name_jp"], unlock_level=s["unlock_level"], d5_id=None,
                     dropped=[], adaptations=[], stand_in=None)
            same = [i for i in by_jp.get(s["name_jp"], []) if scripts.root_of(i) is not None]
            st_same = status(folder, same[0]) if len(same) == 1 else None
            kind = main["d5"]
            if len(same) == 1 and st_same in ("ok", "fallback"):
                r = van[same[0]]
                e.update(cls="E", d5_id=same[0], name_en=r["name_EN"], name_label="D5's own name",
                         label=f"same skill in D5: {same[0]} {r['name_EN']} (JP name identical); D5's own row, numbers and animation",
                         motions=st_same)
                used.add(same[0])
            elif kind == "damage" or kind.startswith(("stat:", "ail:")):
                if len(same) == 1:
                    e["adaptations"].append(f"D5 has this skill ({same[0]}) but its caster motion is absent from this body's bank; built as an own row instead")
                tgt = main["target"]
                if kind == "damage":
                    single = tgt == "enemy single"
                    want_el, want_f = ELEMENT[s["element"]], (3 if s["stat"] == "INT" else 2)
                    cand = [r for r in pool if (cells(r) == 1) == single]
                    scored = []
                    for r in cand:
                        st = status(folder, int(r["id"]))
                        if st not in ("ok", "fallback"):
                            continue
                        scored.append(((0 if prior.get(s["rpg_id"]) == int(r["id"]) else 1, st != "ok",
                                        int(r["element"]) != want_el, int(r["formula"]) != want_f, int(r["id"]) in used,
                                        abs(min(int(r["rank"]), 2) - min(n, 2)), abs(int(r["sp_cost"]) - s["sp_lv1"]), int(r["id"])), r, st))
                    if not scored:
                        e.update(cls="X", label="no D5 damage skill of this target class has its caster motions in this body's bank; the pack's lookalike stays (donor)")
                    else:
                        _, donor, st = min(scored, key=lambda x: x[0])
                        row = donor.copy()
                        v1, v50 = main["value_lv1"], main["value_lv50"]
                        row.set("effect1_value", v1 - 100)
                        for k in range(10):
                            row.set(f"power_lv{k + 1}", 100 + round((v50 - v1) * k / 9))
                        row.set("element", want_el)
                        row.set("formula", want_f)
                        riders = []
                        for x in s["effects"][1:]:
                            xk = x["d5"]
                            why = None
                            if not xk or xk in ("damage", "heal", "cure"):
                                why = "no D5 skill-row meaning" if not xk else "second damage / heal part"
                            elif x["target"] not in ENEMY:
                                why = "lands on allies / self; a D5 skill's effects all land on its targets"
                            elif x["trigger"]:
                                why = "conditional in the source"
                            elif len(riders) >= 5:
                                why = "no free effect slot"
                            if why:
                                e["dropped"].append(dict(type=x["type"], name=x["name"], target=x["target"], value=x["value_lv1"], turns=x["sub"], why=why))
                                continue
                            fam, code = xk.split(":")
                            code = int(code)
                            riders.append((abs(code), -x["value_lv1"] if fam == "stat" else min(x["value_lv1"], 100), x))
                            if x["target"] != tgt:
                                e["adaptations"].append(f"{x['name']}: source target {x['target']}, D5: the units this skill hits")
                        for i in range(2, 7):
                            t, v = (riders[i - 2][0], riders[i - 2][1]) if i - 2 < len(riders) else (0, v1 - 100)
                            row.set(f"effect{i}_type", t)
                            row.set(f"effect{i}_value", v)
                        e["kept"] = [dict(type=x["type"], name=x["name"], d5_effect=t, value=v, turns=x["sub"]) for t, v, x in riders]
                        text = f"{ELEMENT_EN[want_el]}attack on {'one enemy' if single else 'the enemies in its area'}".capitalize() + "."
                        downs = [STAT_EN[t] for t, v, x in riders if t in STAT_EN]
                        ails = [AIL_EN[t] for t, v, x in riders if t in AIL_EN]
                        if downs:
                            vals = sorted({-v for t, v, x in riders if t in STAT_EN})
                            text += f" Lowers {', '.join(downs)}" + (f" by {vals[0]}%." if len(vals) == 1 else ".")
                        if ails:
                            text += f" Inflicts {', '.join(ails)}."
                        e["adaptations"] += [
                            f"animation, range {int(donor['range'])} and area ({cells(donor)} panel{'s' if cells(donor) != 1 else ''}) are D5 {int(donor['id'])} {donor['name_EN']}'s (stand-in)",
                            f"power: {v1}% at skill level 1 to {v50}% at level 10 (source level 50)"]
                        if s["element"] == "water":
                            e["adaptations"].append("water read as D5 ice")
                        if tgt == "enemy all":
                            e["adaptations"].append("source hits all enemies; D5: the stand-in's area")
                        if int(donor["element"]) != want_el:
                            e["adaptations"].append(f"the stand-in animation is D5 element {int(donor['element'])}, the row's element is {want_el}")
                        e.update(cls="A", kind="damage", motions=st, _donor=donor, _row=row, _text=text)
                else:
                    fam, code = kind.split(":")
                    code = int(code)
                    sign = -1 if code < 0 else 1
                    donor = spell.get((abs(code), sign if fam == "stat" else 1))
                    st = status(folder, int(donor["id"])) if donor is not None else None
                    if donor is None or st not in ("ok", "fallback"):
                        e.update(cls="X", label="the D5 spell of this effect has no caster motion in this body's bank; the pack's lookalike stays (donor)")
                    else:
                        row = donor.copy()
                        v1, v50 = main["value_lv1"], main["value_lv50"]
                        if fam == "ail":
                            v1, v50 = min(v1, 100), min(v50, 100)
                        slots = [(abs(code), main)]
                        for x in s["effects"][1:]:
                            xk = x["d5"]
                            why = None
                            if not xk or xk in ("damage", "heal", "cure"):
                                why = "no D5 skill-row meaning" if not xk else "second damage / heal part"
                            elif x["target"] != tgt:
                                why = "other target than the main effect; a D5 skill's effects all land on its targets"
                            elif x["trigger"]:
                                why = "conditional in the source"
                            elif xk.split(":")[0] != fam or (fam == "stat" and (int(xk.split(":")[1]) < 0) != (code < 0)):
                                why = "other effect family than the main effect (a support row is one family)"
                            elif (min(x["value_lv1"], 100) if fam == "ail" else x["value_lv1"]) != v1 or (fam == "stat" and x["value_lv50"] != v50):
                                why = "magnitude differs from the main effect (a support row has one level table)"
                            elif len(slots) >= 6:
                                why = "no free effect slot"
                            if why:
                                e["dropped"].append(dict(type=x["type"], name=x["name"], target=x["target"], value=x["value_lv1"], turns=x["sub"], why=why))
                            else:
                                slots.append((abs(int(xk.split(":")[1])), x))
                        for i in range(1, 7):
                            t = slots[i - 1][0] if i <= len(slots) else 0
                            row.set(f"effect{i}_type", t)
                            row.set(f"effect{i}_value", sign * v1 if t else 0)
                        for k in range(10):
                            row.set(f"power_lv{k + 1}", sign * (v1 + round((v50 - v1) * k / 9)))
                        e["kept"] = [dict(type=x["type"], name=x["name"], d5_effect=t, value=sign * v1, turns=x["sub"]) for t, x in slots]
                        if fam == "stat":
                            text = f"{'Raises' if sign > 0 else 'Lowers'} the target's {', '.join(STAT_EN[t] for t, _ in slots)}. (Lasts 3 turns)"
                        else:
                            text = f"Inflicts {', '.join(AIL_EN[t] for t, _ in slots)}."
                        e["adaptations"] += [
                            f"cast like D5 {int(donor['id'])} {donor['name_EN']} (stand-in: its animation; reach and area grow with the spell's level as D5 spells do)",
                            f"magnitude: {v1} at skill level 1 to {v50} at level 10 (source level 50)",
                            f"source target: {tgt}; D5: the spell's target panel(s)"]
                        if main["sub"] not in (0, 3) and fam == "stat":
                            e["adaptations"].append(f"source lasts {main['sub']} turns; D5 stat changes last 3")
                        e.update(cls="A", kind="support", motions=st, _donor=donor, _row=row, _text=text)
            else:
                e.update(cls="X", label=f"main effect '{main['name']}' has no D5 skill-row expression with a source number; the pack's lookalike stays (donor)")
            if e["cls"] == "A":
                sid = BAND[0] + 4 * pos + n
                en = names.get(str(s["rpg_id"]))
                if not en:
                    missing_names.append((s["rpg_id"], s["name_jp"]))
                    en = s["name_jp"]
                donor, row = e.pop("_donor"), e.pop("_row")
                if sid in van or any(b + sid in events for b in (skills.SKILL_SCRIPT, skills.SKIP_SCRIPT, skills.SKIPPED_SCRIPT)):
                    raise SystemExit(f"leased id {sid} is in use by the game")
                row.set("id", sid)
                row.set("sp_cost", s["sp_lv1"])
                row.set("rank", min(n, 3))
                row.set("base_skill", 0)
                newclasses.set_langs(row, "name", en)
                d0 = donor["desc_EN"]
                prefix = d0[:d0.index("%s") + 2] if "%s" in d0 else d0[:d0.index(":") + 2] if ":" in d0 else ""
                newclasses.set_langs(row, "desc", prefix + e.pop("_text"))
                used.add(int(donor["id"]))
                e.update(d5_id=sid, name_en=en, name_label="provisional", choreography=int(scripts.root_of(int(donor["id"]))),
                         stand_in=dict(id=int(donor["id"]), name=donor["name_EN"], range=int(donor["range"]), panels=cells(donor),
                                       picked="the pack's reviewed lookalike" if prior.get(s["rpg_id"]) == int(donor["id"]) else "rule (motions, element, stat, tier, SP)"),
                         label=f"adapted: source SP {s['sp_lv1']}, element, power and added effects on D5 {int(donor['id'])} {donor['name_EN']}'s animation and target shape"
                               + (f"; {len(e['dropped'])} source effect(s) dropped" if e["dropped"] else ""),
                         set=changed(donor, row))
                shas[str(int(donor["id"]))] = drpg_skills.row_sha(dbpatch._row_values(donor))
            elif e["cls"] == "X":
                e.update(name_en=None, name_label=None, donor=prior.get(s["rpg_id"]))
            counts[e["cls"]] = counts.get(e["cls"], 0) + 1
            if e["cls"] == "A" and e["dropped"]:
                counts["A with dropped effects"] = counts.get("A with dropped effects", 0) + 1
            out_sk.append(e)
            cen_sk.append(dict(s, cls=e["cls"], d5_id=e["d5_id"], name_en=e.get("name_en"), label=e["label"], stand_in=e["stand_in"],
                               kept=e.get("kept"), dropped=e["dropped"], adaptations=e["adaptations"], motions=e.get("motions")))
        mg, seen = [], set()
        for s in ch["magic"]:
            ids = [i for i in by_jp.get(s["name_jp"], []) if 1000 < i < 2000]
            m = dict(rpg_id=s["rpg_id"], name_jp=s["name_jp"], level=s["weapon_mastery_lv"], needs=["M1"], d5_id=None, d5_name=None)
            if len(ids) == 1 and ids[0] not in seen and status(folder, ids[0]) in ("ok", "fallback"):
                seen.add(ids[0])
                m.update(d5_id=ids[0], d5_name=van[ids[0]]["name_EN"], label="same spell in D5 (JP name identical); source weapon mastery level read as character level")
            else:
                m["label"] = ("same D5 spell already linked" if len(ids) == 1 and ids[0] in seen else
                              "caster motion absent from this body's bank" if len(ids) == 1 else
                              "D5 has no spell row of this name (D5 buffs / debuffs / ailments have one row that grows with its level)")
            mg.append(m)
            counts["spell " + ("E" if m["d5_id"] else "none")] = counts.get("spell " + ("E" if m["d5_id"] else "none"), 0) + 1
        doc["bases"][str(bid)] = dict(name=ch["name"], lease_position=pos, folder=folder.name, class_id=leases[bid]["class_id"],
                                      skills=out_sk, magic=mg)
        census["characters"].append(dict(base_id=bid, name=ch["name"], name_jp=ch["name_jp"], body=ch["body"], folder=folder.name,
                                         skills=cen_sk, magic=[dict(s, **m) for s, m in zip(ch["magic"], mg)]))
    doc["counts"] = census["counts"] = counts
    doc["stand_in_sha256"] = dict(sorted(shas.items()))
    text = _drpg_text.format_doc(_drpg_text.refify_skill_overlay(json.loads(json.dumps(doc)), _drpg_text.prose_names()))   # compact: the 1 MB commit guard
    if missing_names:
        print(f"{len(missing_names)} own rows have no English name in {NAMES.name} (JP used):", file=sys.stderr)
        print(json.dumps({str(k): v for k, v in missing_names}, ensure_ascii=False, indent=0), file=sys.stderr)
    if check:
        same = OUT.exists() and OUT.read_text() == text
        print("overlay is current" if same else "overlay differs from a rebuild")
        return 0 if same else 1
    OUT.write_text(text)
    if census_out:
        census_out.write_text(json.dumps(census, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
