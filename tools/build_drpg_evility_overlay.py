#!/usr/bin/env python3
"""DRPGEVIL1: turn the private Disgaea RPG evility census into the kit's reviewed overlay.

    python tools/build_drpg_evility_overlay.py CENSUS.json D5_GAME_DIR [--check]

CENSUS.json is Subprojects/Engine-Extensions/drpg-evility-map/drpg_evilities.json (made from the JP client
masters; private, never committed).  The overlay (d5lib/importers/drpg-evility-overlay.json) holds only the
derived, reviewed mapping the importer applies: ids, names, generated English text and runtime rows, the way
d4-evility-overlay.json does.  It is read at build time and never recomputed there.

Ids: 28000 + 4 * (the base's position in drpg-leases.json) + slot (0 main, 1-3 sub), written out per row so a
later lease reorder cannot move them.  Rows whose `needs` names a decision (D1 field-wide scope, D2 every-turn
buffs as permanent, D3 SP points as percent) are prepared but applied only when the overlay's `decisions`
switch for it is true.
"""
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
IMP = KIT / "d5lib/importers"
OUT = IMP / "drpg-evility-overlay.json"
BAND = (28000, 28999)
SLOTS = ("main", "sub1", "sub2", "sub3")
RADIUS = 30     # the installed DRPG sample auras' "whole map" radius
WEAPON_EN = {1: "fist", 2: "sword", 3: "spear", 4: "bow", 5: "gun", 6: "axe", 7: "staff",
             8: "monster physical weapon", 9: "monster magic weapon"}
DMG_EN = {1: "damage", 2: "normal attack damage", 3: "skill damage", 5: "magic damage", 7: "non-elemental damage",
          8: "elemental damage", 9: "fire damage", 10: "ice damage", 11: "wind damage", 12: "star damage",
          13: "single-target attack damage", 14: "multi-target attack damage"}
OTHER_EN = {1: "male units", 2: "female units", 3: "humanoid units", 4: "monster units"}
POTENTIAL_EN = {1: "King", 2: "Pawn", 3: "Rook", 4: "Bishop", 5: "Knight", 6: "Queen"}     # DRPGPARTY1
# DRPGPARTY1: a condition that walks the whole battle table (evil_party_distinct) goes after the cheap ones, so an
# aura row stops at its near_has first
HEAVY = ("party_weapons_distinct", "map_hp_at_or_below")
STAT_EN = {"hp": "HP", "atk": "ATK", "def": "DEF", "int": "INT", "res": "RES", "spd": "SPD"}
BUFF_EN = {2: "ATK", 3: "DEF", 4: "INT", 5: "RES", 6: "HIT", 7: "SPD"}     # EVILFX2: stat-change status ids


def UNPROV(kind):
    """a provider qualifier's name -> the condition the holder's own row tests (provider_buff -> self_buff)"""
    kind = kind[len("provider_"):]
    return {"buff": "self_buff"}.get(kind, kind)


def _join(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _a(noun):
    return ("an " if noun[0].lower() in "aeiou" else "a ") + noun


def _who(row, on):
    """the English subject of a row's effect"""
    f, tt = row["fields"], row["fields"]["target_type"]
    if row["scope"] == "self":
        return ""
    if row["scope"] == "enemy" and tt != 30:
        return {11: "enemy units on the map", 12: "male enemy units on the map",
                13: ("humanoid" if f["target_params"][0] == 1 else "monster") + " enemy units on the map"}[tt]
    if tt == 4:
        ws = row.get("recipient_weapons") or [c["id"] for c in row["recipient_conditions"]]
        return "ally units on the map with " + ", ".join(_a(WEAPON_EN[w]) for w in ws[:-1]) + \
               (" or " if len(ws) > 1 else "") + _a(WEAPON_EN[ws[-1]]) + " equipped"
    if tt == 26:
        ts = row["recipient_conditions"][0]["types"]
        return "ally units on the map of potential type " + " or ".join(POTENTIAL_EN[t] for t in ts)
    if tt == 36:
        return f"ally units on the map that have {_a(BUFF_EN[row['recipient_conditions'][0]['id']])} buff"
    if tt in (28, 29, 30):
        return (f"the {'enemy' if tt == 30 else 'ally'} unit on the map with the "
                f"{'lowest' if tt == 29 else 'highest'} {BUFF_EN[row['recipient_conditions'][0]['id']]}")
    return {1: "all ally units on the map", 2: "female ally units on the map", 8: "other ally units on the map",
            3: ("humanoid" if f["target_params"][0] == 1 else "monster") + " ally units on the map"}[tt]


def describe(row):
    f = row["fields"]
    et, v = f["effect_type"], row["value"]
    who = _who(row, None)
    pre = []
    holder = [dict(c, kind=UNPROV(c["kind"])) for c in row.get("provider_conditions") or []]
    me = " by this unit" if holder else ""
    for k in row["kit"][:1]:
        for c in k.get("conditions", []) + holder:
            kind = c["kind"]
            if kind == "weapon" and (row["scope"] == "self" or holder):
                pre.append(f"while {_a(WEAPON_EN[c['id']])} is equipped{me}")
            elif kind == "hp_above":
                pre.append((f"while this unit's HP is " if holder else "while HP is ") +
                           ("full" if c["id"] >= 100 else f"{c['id']}％ or more"))
            elif kind == "hp_at_or_below":
                pre.append((f"while this unit's HP is " if holder else "while HP is ") + f"{c['id']}％ or less")
            elif kind == "hp_below":
                pre.append((f"while this unit's HP is " if holder else "while HP is ") + f"below {c['id']}％")
            elif kind == "ally_map":
                pre.append(f"while {c['id']} or more other allies are on the map")
            elif kind == "party_min":
                what = {1: "humanoid", 2: "monster", 3: "male", 4: "female"}.get(c["of"]) or \
                    (WEAPON_EN[c["id"]] + "-equipped")
                pre.append(f"while {c['count']} or more {what} units are on this unit's side of the map")
            elif kind == "party_weapons_distinct":
                pre.append("while the favourite weapon types of all units on this unit's side of the map are different")
            elif kind == "turn_max":
                pre.append(f"for the first {c['id']} rounds of a battle")
            elif kind == "self_buff":
                pre.append(f"while this unit has {_a(BUFF_EN[c['id']])} buff")
            elif kind == "map_debuff_min":
                pre.append(f"while an enemy unit on the map has {_a(BUFF_EN[c['id']])} debuff")
            elif kind == "enemy_map_max":
                pre.append(f"while {c['id']} or fewer enemy units are on the map")
            elif kind == "enemy_map":
                pre.append(f"while {c['id']} or more enemy units are on the map")
            elif kind == "map_hp_at_or_below":
                pre.append(f"while an enemy unit on the map has HP {c['id']}％ or less")      # DRPGSIG1
    per = row.get("per")
    if per == "party_capped":
        v = v // 5
    if et in (1, 23, 2, 24, 46, 52, 29, 30, 35):
        names = [STAT_EN[e["stat"]] for k in row["kit"] if k["family"] == "stats" for e in k["effects"]]
        if any(k["family"] == "crit_rate" for k in row["kit"]):
            names.append("critical rate")
        if any(k["family"] == "crit_damage" for k in row["kit"]):
            names.append("critical damage")
        verb = "Decrease" if et in (2, 24) else "Increase"
        s = f"{verb} {_join(names)}{' of ' + who if who else ''} by {v}％"
    elif et in (3, 49, 4, 50, 41, 43):
        dealt = et in (3, 49, 41)
        kind = DMG_EN[f["effect_type_params"][0]]
        other = OTHER_EN.get(f["limit_damage"])
        for c in row["kit"][0].get("conditions", []):
            if c["kind"] == "other_weapon":
                other = WEAPON_EN[c["id"]] + "-equipped units"
        s = (f"{'Increase' if dealt else 'Decrease'} {kind} {'dealt' if dealt else 'taken'}"
             f"{' by ' + who if who else ''}"
             f"{(' to ' if dealt else ' from ') + other if other else ''} by {v}％")
    elif et == 14:
        one = [c["id"] for c in row["kit"][0].get("conditions", []) if c["kind"] == "status_class"]
        s = "Nullify " + ({0: "Poison", 2: "Paralysis", 3: "Amnesia"}[one[0]] if one else "status ailments")
    elif et == 21:
        s = f"Recover {v}％ HP at end of turn" if not who else \
            f"At end of turn, {who} recover HP equal to {v}％ of this unit's max HP"
    elif et == 9:
        s = f"Decrease healing received by enemy units on the map by {v}％"          # DRPGSIG1
    elif et == 90:
        s = f"Nullify the damage of the first {v} hits taken in a battle"             # DRPGSIG2
    elif et == 79:
        s = "Take 50％ less damage and may counter attack"                              # LONGTAIL2: intercept, two rows (counter, taken -50)
    elif et == 48:
        s = "Once per battle, revive with full HP after being defeated (inside the Base Panel)"   # DRPGSIG2: D5 Lich Deimos 145
    elif et in (22, 80):
        s = f"Recover {v}％ SP at end of turn" if not who else \
            f"At end of turn, {who} recover{'s' if who.startswith('the ') else ''} {v}％ SP"
    else:
        raise ValueError(f"no description for effect type {et}")
    if per == "hp_pct":
        s = s.replace(f" by {v}％", f" by up to {v}％, in proportion to current HP")
    elif per == "hp_lost_pct":
        s = s.replace(f" by {v}％", f" by up to {v}％, in proportion to HP lost")
    elif per == "party_capped":
        s += " per living unit on this unit's side of the map (up to 5 units)"
    elif per:
        what = {"party_human": "humanoid", "party_monster": "monster", "party_male": "male",
                "party_female": "female"}.get(per) or (WEAPON_EN[row["kit"][0]["filter"]] + "-equipped")
        s += f" x the number of {what} units on this unit's side of the map"
    if pre:
        s += " " + " and ".join(pre)
    return s


def wire(row, evid, on):
    """the census row's kit parts -> final runtime rows (aura wiring for party / enemy scope)"""
    out = []
    rc = row.get("recipient_conditions") or []
    weapons = row.get("recipient_weapons")
    variants = [[{"kind": "weapon", "id": w}] for w in weapons] if weapons else [rc]
    prov = row.get("provider_conditions") or []           # DRPGEVIL1b: the holder-side condition
    hold = [dict(c, kind=UNPROV(c["kind"])) for c in prov]
    for k in row["kit"]:
        base_c = k.get("conditions", [])
        heavy = [c for c in base_c if c["kind"] in HEAVY]
        base_c = [c for c in base_c if c["kind"] not in HEAVY]
        for var in variants:
            if row["scope"] == "self" or row.get("wire") == "holder":      # DRPGSIG1: enemy_heal_percent sits on the holder
                parts = [(k["family"], base_c + heavy)]
            else:
                rel = 1 if row["scope"] == "party" else 2
                near = {"kind": "near_has", "of": rel, "radius": RADIUS, "id": evid}
                parts = [([k["family"], "aura"], base_c + var + [near] + prov + heavy)]   # the qualifier follows its near_has
                if row["scope"] == "party" and row["fields"]["target_type"] != 8:
                    parts.insert(0, (k["family"], hold + base_c + var + heavy))  # the holder itself: an aura never reaches its provider
            for fam, conds in parts:
                r = {"family": fam}
                if "effects" in k:
                    r["effects"] = [dict(e) for e in k["effects"]]
                    if k["family"] == "regen" and isinstance(fam, list):
                        # EVILFX2: a party heal is a percent of the HOLDER's max HP, as the source says
                        for e in r["effects"]:
                            if e["stat"] == "hp":
                                e["base"] = row.get("regen_base", "provider")
                if "filter" in k:
                    r["filter"] = k["filter"]
                if conds:
                    r["conditions"] = [dict(c) for c in conds]
                out.append(r)
    return out


def build(census, game_dir):
    from d5lib import database, evility, gamefs, textfmt
    fs = gamefs.GameFS(str(game_dir))
    skill = database.load_table("Skill.dat", fs.read("Database/Database_0.dat/Skill.dat"))
    from d5lib.importers import _drpg_text        # TEXTHASH-DRPG: names are hashes/@authored in the files; resolved here
    names = _drpg_text.load(IMP / "drpg-evility-names.json")
    names = dict(names, names=_drpg_text.evility_names(names))
    lease = _drpg_text.load(IMP / "drpg-leases.json")
    order = [int(b["lease"].split(":")[1]) for b in lease["bases"]]
    rows_by_base = {int(b["lease"].split(":")[1]): b["class_id"] for b in lease["bases"]}
    bases, n_rows = {}, {"now": 0, "all": 0}
    for ch in census["characters"]:
        bid = ch["base_id"]
        evs = []
        for si, e in enumerate(ch["evilities"]):
            assert e["slot"] == SLOTS[si]
            if e["cls"] not in ("A", "C", "A+"):
                continue
            evid = BAND[0] + 4 * order.index(bid) + si
            assert BAND[0] <= evid <= BAND[1]
            name_en = names["names"][e["name_jp"]]
            notes = sorted({n for r in e["rows"] for n in r["notes"]})
            alias = next((k["alias"] for r in e["rows"] for k in r["kit"] if "alias" in k), None)
            # DRPGSIG2: an evility with an alias row AND other rows (Jusoso: party stats + a revive) keeps both: the runtime rows of the
            # other rows and the alias of the one
            plain = [r for r in e["rows"] if not any("alias" in k for k in r["kit"])]
            if alias and not plain:
                tmpl = skill.find(alias).to_dict()
                desc, rt = tmpl["desc_EN"], None
                # an innate row of this character, not the donor's learnable common (DRPGEVIL1b budget rule)
                tmpl.update(kind=2, slot_cost=0, mana_cost=0, shop_rank=0, class_order=0)
                label = f"D5 equivalent: {alias} {tmpl['name_EN']} ({notes[0]})"
            else:
                tmpl = skill.find(1235).to_dict()
                tmpl.update(kind=2, effect_group=0, value2=0, slot_cost=0, mana_cost=0, shop_rank=0, class_order=0)
                desc = ". ".join(describe(r) for r in e["rows"]) + "."
                rt = [x for r in plain for x in wire(r, evid, None)]
                evility.table({evid: rt})                      # the runtime accepts every row, or the build stops here
                adapt = list(notes)
                if "D1" in e["needs"]:
                    adapt.append("party / all enemies read as every ally / enemy on the map")
                if "D2" in e["needs"]:
                    adapt.append("a buff re-applied every turn read as always on")
                if "D3" in e["needs"]:
                    adapt.append("SP points read as percent of max SP")
                if "D4" in e["needs"]:
                    adapt.append("potential type / favourite weapon read through the source class registry "
                                 "(a unit outside it, such as a D5-native ally, has neither)")
                if "L1" in e["needs"]:
                    adapt.append("'N turns from battle start' read as the first N battle rounds (round counter base not measured)")
                label = "source: Disgaea RPG JP leaderskill " + "+".join(str(r["rpg_id"]) for r in e["rows"]) + \
                        ("; adapted: " + "; ".join(adapt) if adapt else "; exact numbers and conditions")
                tmpl["value1"] = e["rows"][0]["value"]
            if alias == 145:
                label += ("; revives only units on the player's side (D5 Lich Deimos tests team 0), the source rule has no side limit; "
                          "an enemy-side holder would not revive")
            desc = textfmt.format_text(desc)
            for lang in ("JP", "CHN", "KOR"):
                tmpl[f"name_{lang}"] = e["name_jp"]
            for lang in ("EN", "FR"):
                tmpl[f"name_{lang}"] = name_en
            for lang in ("JP", "EN", "FR", "CHN", "KOR"):
                tmpl[f"desc_{lang}"] = desc
            tmpl.update(id=evid, owner=rows_by_base[bid])
            ev = dict(slot=e["slot"], id=evid, rpg_ids=[r["rpg_id"] for r in e["rows"]], name_jp=e["name_jp"], name_en=name_en,
                      name_label=names["label"], cls=e["cls"], needs=e["needs"], label=label, skill_row=tmpl)
            if alias:
                ev["alias"] = alias
            if rt is not None:
                ev["rows"] = rt
                n_rows["all"] += len(rt)
                n_rows["now"] += 0 if e["needs"] else len(rt)
            evs.append(ev)
        if evs:
            bases[str(bid)] = dict(name=ch["name"], row=rows_by_base[bid], evilities=evs)
    count = lambda p: sum(1 for b in bases.values() for e in b["evilities"] if p(e))
    return dict(
        schema="drpg-evility-overlay/1",
        source="generated by tools/build_drpg_evility_overlay.py from the DRPGEVIL1 census of the JP client masters "
               "leaderskill + character (Disgaea Source/Disgaea RPG JP (Android)); read by d5lib/importers/drpg_evilities.py - "
               "never recomputed at build time",
        census_sha256=census.get("source", {}).get("sha256"),
        band=list(BAND), id_rule="28000 + 4 * position in drpg-leases.json bases + slot (0 main, 1-3 sub); recorded per row",
        decisions=dict(D1=True, D2=True, D3=False, L1=True, D4=True),   # DRPGEVIL2 defaults; D4 = DRPGPARTY1 (class registry)
        decision_text=census["decisions"],
        samples_untouched=[55, 106, 311],
        counts=dict(bases=len(bases), evilities=count(lambda e: True), applied_now=count(lambda e: not e["needs"]),
                    behind_a_decision=count(lambda e: bool(e["needs"])), runtime_rows_now=n_rows["now"],
                    runtime_rows_all_decisions=n_rows["all"], runtime_row_limit=evility.MAX_ROWS),
        bases=bases)


def dump(doc):
    """compact JSON, one line per top-level key and per base (the commit guard allows no file over 1 MB), game text as
    references (TEXTHASH-DRPG: the file never holds the JP names; see d5lib/importers/_drpg_text.py)"""
    from d5lib.importers import _drpg_text
    return _drpg_text.format_doc(_drpg_text.refify_evility_overlay(doc, _drpg_text.prose_names()))


def main(argv):
    check = "--check" in argv
    args = [a for a in argv if not a.startswith("--")]
    doc = build(json.loads(Path(args[0]).read_text()), args[1])
    text = dump(doc)
    if check:
        same = OUT.exists() and OUT.read_text() == text
        print("overlay is current" if same else "overlay differs from the census")
        return 0 if same else 1
    OUT.write_text(text)
    print(json.dumps(doc["counts"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
