#!/usr/bin/env python3
"""EVILFX3: write d5lib/importers/dd2-innate-evilities.json, the reviewed innate evility of DD2 packs that linked none.

    python tools/build_dd2_innates.py
Source: DD2 mskill.dat (START_4.dat) read with d5lib.dd2source; a class family's innate is its base id (the D5
numbering rule; DD2 does not store which of the three is innate), a unique's is its own id.  Ids: the installed
convention 24000 + DD2 id when that moves no installed learnable row (Evil Dragon 26200), otherwise the DD2 late band
26300+ (ownership manifest), recorded per row here.  Read by d5lib/importers/_dd2_innates.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evilgap1_rows import CAT, ROOT, row          # noqa: E402  (the same Skill.dat row shape as the D4 additions)


def arow(rid, name, desc, owner, donor):
    d = CAT[str(donor)]
    return row(rid, name, desc, owner, False, 0, 0, effect_group=d["effect_group"], value1=d["value1"], value2=d["value2"],
               category=d["category"], subcategory=d["subcategory"], version_group=d["version_group"])


PACKS = {
    "DD2_Unique_100": dict(dd2_id=100, name="Passiveness", link=10100, relation="exact",
                           label="evility Passiveness (100): the pack already ships row 10100 with its rule; it was never "
                                 "linked on the char row. Innate link only"),
    "DD2_Class_22700": dict(dd2_id=2200, name="Wind Dominance", relation="exact", alias=4015,
                            row=arow(26200, "Wind Dominance", "All wind element damage will be nullified.", 22700, 4015),
                            label="evility Wind Dominance (2200): D5 equivalent - D5 Wind Management (4015) 'Nullify wind "
                                  "element damage'; alias row 26200 (24000 + DD2 id), innate on all six ranks"),
    "DD2_Class_22620": dict(dd2_id=2120, name="Soul Reaper", relation="adapted", alias=1143, late=True,
                            row=arow(26300, "Soul Reaper", "D5 adaptation: normal attacks deathblow targets with less than 25％ HP. "
                                                           "Uses D5 Euthanasia's rule and number.", 22620, 1143),
                            label="evility Soul Reaper (2120): adapted - DD2 'Deathblow units under 25% HP'; D5 Euthanasia "
                                  "(1143) has the same 25 but for normal attacks only; alias row 26300 (DD2 late band), "
                                  "innate on all six ranks"),
    "DD2_Class_22630": dict(dd2_id=2130, name="Patience", relation="adapted", alias=2065, late=True,
                            row=arow(26301, "Patience", "D5 adaptation: increase ATK by 10％ every time attacked by a "
                                                        "non-elemental attack. Uses D5 Impact Charge's rule.", 22630, 2065),
                            label="evility Patience (2130): adapted - DD2 'Increase Attack Power by 10% each time unit is hit "
                                  "(Max 200%)'; D5 Impact Charge (2065) has the same 10 but counts non-elemental attacks "
                                  "only; alias row 26301 (DD2 late band), innate on all six ranks"),
    "DD2_Class_22590": dict(dd2_id=2090, name="Stone Statue", relation="adapted", late=True,
                            row=row(26302, "Stone Statue", "As long as unit doesn't move, increase DEF by 100％.", 22590, False, 0, 0, value1=100),
                            behavior={"family": "stats", "effects": [{"stat": "def", "value": 100}],
                                      "conditions": [{"kind": "not_moved"}]},
                            label="evility Stone Statue (2090): adapted - DD2 'As long as unit doesn't move, increase Defense "
                                  "Power by 100%'; row 26302 is DEF +100% while D5's panels-moved counter is 0 (kit stats + "
                                  "not_moved; Defense Power read as DEF, as for Passiveness 10100). DD2 does not store which "
                                  "of the family's three evilities is innate: the family base, by D5's numbering. DD2 late "
                                  "band, innate on all six ranks"),
    "DD2_Unique_570": dict(dd2_id=570, name="Brave Battle Princess", relation="adapted", late=True,
                           row=row(26304, "Brave Battle Princess",
                                   "Allies gain 10％ Attack Power per defeat the holder has made, max 200％.",
                                   10520, False, 0, 0, value1=10, value2=200),
                           behavior=[{"family": ["power", "aura"],
                                      "effects": [{"value": 10, "per": "holder_kills", "max": 200}],
                                      "filter": 26304,
                                      "conditions": [{"kind": "near_has", "of": 1, "radius": 65535, "id": 26304}]},
                                     {"family": "kill_counter"}],
                           label="evility Brave Battle Princess (570): adapted - rule carried from EBOOT: each holder's OWN count of defeats it made as the "
                                 "attacker (+0x19CE, raised at 0xE9170; allies and any team count), summed over the OTHER same-team holders "
                                 "(0xF6290 / 0xFA6CC; the holder gets nothing from her own count), +10% each, capped at +200% on the sum; "
                                 "values 10 and 200 read by dd2source.decode_evility (value/value2, mskill.dat +0x0C/+0x0E). Kit row 26304 = "
                                 "power aura (scale holder_kills, filter 26304) + kill_counter (wrap_atkcount after the real "
                                 "damage_apply_damage; stat record +0x5D8, D5's Impact Charge counter, read only for a unit that has 2065, "
                                 "which Plume does not). Not proved equal to DD2: its object test 0x1035B0 also skips unit types 51/52 "
                                 "(0x100FE8) where the kit skips the Geo Symbol family only; reset is D5's stat-record attach/wipe against "
                                 "DD2's unit-data init 0x20F78 (callers not all traced); a skill-id branch at 0xE84E4 was not followed; a "
                                 "defeat is read from the unit's HP after the apply. DD2 late band, innate only"),
    "DD2_Unique_430": dict(dd2_id=430, name="Demon Experiments", relation="exact", late=True,
                           row=row(26303, "Demon Experiments", "Within 3 panels, allies deal 10％ more damage, and enemies take 10％ more.",
                                   10500, False, 0, 0, value1=10),
                           behavior=[{"family": ["dealt", "aura"], "effects": [{"value": 10}],
                                      "conditions": [{"kind": "near_has", "of": 1, "radius": 3, "id": 26303}]},
                                     {"family": ["taken", "aura"], "effects": [{"value": 10}],
                                      "conditions": [{"kind": "near_has", "of": 2, "radius": 3, "id": 26303}]}],
                           label="evility Demon Experiments (430): exact text and number - allies within 3 panels of Mao deal "
                                 "+10% damage and enemies within 3 panels take +10% (two kit aura rows; Mao himself is not an "
                                 "ally of his own aura); row 26303 (DD2 late band), innate"),
    # DD2D1GAP1 (2026-11-11): five packs whose reviewed-abilities layer already ships and links the D5 equivalent
    # (aliases 25210, 26180, 24480, 24320, 24300).  Link and label only: no row, alias or behavior is written, the
    # label records exact vs adapted so the status page does not have to guess from "an alias row exists".
    # DD2EVIL1 (2026-11-13): Masked Hero 1210 is an own exact row (was the alias row 25210 -> D5 1060, 3 per panel).  Source: the DD2
    # EBOOT.elf hit-chance function at 0xFB0EC (see DD2EVIL1-REPORT.md): after clamping the in/out percent to 1..100 it subtracts
    # min(64, value x panels moved), value = mskill 1210's 2.  The 64 is a constant in that code, not in the text.
    "DD2_Class_22210": dict(dd2_id=1210, name="Rapid Movement", relation="exact", drop_alias=True,
                            row=row(25210, "Rapid Movement", "Increase evasion rate by panels moved x 2％. (Max 64％)", 22210, False, 0, 0,
                                    category=4, subcategory=11),
                            behavior={"family": "evasion", "effects": [{"value": 2, "per": "movement_cost", "max": 64, "mode": "after"}]},
                            label="evility Rapid Movement (1210): exact rule - DD2 EBOOT hit-chance function 0xFB0EC clamps the percent to 1..100, then "
                                  "subtracts min(64, 2 x panels moved) (2 = mskill value, 64 = a constant in that code); kit evasion row 25210, "
                                  "mode after, per movement_cost, max 64, replaces the alias to D5 1060 (3 per panel). Not carried: DD2 counts path "
                                  "steps (unit +0x522) where D5 counts movement cost (+0x61C), equal on cost-1 panels; D5 floors the chance at 1, "
                                  "the DD2 function has no floor (callers not read). 1211 Blazing Start is D5 Start Dash (1024), same 3 (learnable "
                                  "row 25211, exact); 1212 Heart of a Flea has no D5 equivalent and is not built"),
    "DD2_Class_22680": dict(dd2_id=2180, name="Water Dominance", link=26180, relation="exact",
                            label="evility Water Dominance (2180): D5 equivalent - D5 Water Management (4016) 'Nullify water "
                                  "element damage' via alias row 26180, no number in either. 2182 Aqua Depression is learnable "
                                  "row 26182 on D5 Kill With Water (4013), same 15 but 'other units on the map' where the "
                                  "source says enemy units (adapted). 2181 Cold Charge is not built (needs a per-unit counter "
                                  "of water skills used on the map)"),
    # DD2EVIL2 (2026-11-14): Alex 480, Pleinair 320 and Lilliel 420 get own rows (second-word families random_victims, ally_move, move_heal_percent).
    # Source: DD2EVIL2-REPORT.md (EBOOT.elf 0xFB984/0xFBD24/0x1A0CCC for Alex, 0xF6290/0xF7938/0xFC724 for Pleinair, 0xF64C0/0x219ED0 for Lilliel).
    "DD2_Unique_480": dict(dd2_id=480, name="God of Destruction", relation="adapted",
                           row=row(24480, "God of Destruction", "Deal damage to a random number (1 to 5) of enemy units at end of turn.", 10560, False, 0, 0,
                                   effect_group=27, category=1, version_group=150),
                           alias=6112,
                           behavior={"family": "random_victims", "effects": [{"value": 5}]},
                           label="evility God of Destruction (480): adapted - DD2 'Deal damage to a random number of enemy units at end of turn' (value 5): "
                                 "EBOOT 0xFB984 draws the count 0x1A0CCC(5) + 1 (1..5) and picks that many DISTINCT random hostile units. Rule carried: D5 "
                                 "Punishing Prophecy (6112, alias 24480) still hits its one drawn victim at the holder's end of turn, then kit row 24480 "
                                 "(random_victims 5, wrap_victims at the game's append call) adds game_rng_draw(5) more distinct hostile victims, so the count "
                                 "is 1..5, same candidate rules as D5's own list. Not carried: the damage per victim is D5's own Punishing Prophecy action "
                                 "(magic row 21, power 100); DD2's action row 10484 differs from Plum's 10474 in two bytes (+0x112 2 vs 3, +0x127 130 vs 100) "
                                 "whose meaning was not decoded, so DD2's damage is not reproduced"),
    "DD2_Unique_320": dict(dd2_id=320, name="Acceleration Mascot", relation="exact", drop_alias=True,
                           row=row(24320, "Acceleration Mascot", "Increase movement of ally units by 1.", 10480, False, 0, 0, category=11, version_group=110),
                           behavior={"family": "ally_move", "effects": [{"value": 1}]},
                           label="evility Acceleration Mascot (320): exact rule - DD2 'Increase movement of ally units by 1' (value 1): EBOOT 0xF7938 / 0xFC724 "
                                 "add value x 0xF6290(...) to the unit's move, 0xF6290 counting the OTHER units of the unit's team byte that hold the evility, "
                                 "no range, one per holder (several holders add up); kit row 24320 (ally_move 1, wrap_move) does that and replaces the alias "
                                 "to D5 6024 (+2). Not carried: D5 adds it after the game's own move-range clamp and to a unit whose range is above 0; "
                                 "liveness tests of the holder differ (D5 active / not carried / HP above 0 against DD2's 0x31A1C, 0x1035B0, +0x262)"),
    "DD2_Unique_420": dict(dd2_id=420, name="Healing Barrier", relation="adapted", late=True,
                           row=row(26305, "Healing Barrier", "Ally units (including self) recover 2％ HP per panel they move.", 10170, False, 0, 0, category=1),
                           behavior={"family": "move_heal_percent", "effects": [{"value": 2}]},
                           label="evility Healing Barrier (420): adapted - DD2 'Ally units (including self) recover 2% HP per panel they move' (value 2): "
                                 "EBOOT 0xF64C0 = 2 x (other holders on the unit's team) + 2 if the unit holds it, no range, healed at EVERY STEP of the "
                                 "walk by that percent of max HP (0x219ED0, 0x21AC3C). Kit row 26305 (move_heal_percent 2, evil_move_heal at wrap_endturn; DD2 late band, a new row at 24420 would shift installed learnable rows) heals "
                                 "the same percent once per panel moved at the END of the unit's own turn. Not carried: per-step timing (a unit that dies "
                                 "after moving is not healed), D5 movement cost where DD2 counts steps, DD2's panel flags (0x1B800 ids 0x2A / 0x25: an SP "
                                 "panel heals SP instead, a reversing panel damages) and the evility 0x804 test"),
    # LONGTAIL2 (2026-11-14): Xenolith 80 "The Artifact" -- alias to D5 Malicious Reflect (143) + the second-word family max_hp_reflect (wrap_maxrefl).
    "DD2_Unique_941": dict(dd2_id=80, name="The Artifact", relation="adapted", late=True,
                           row=arow(26306, "The Artifact", "Deals damage equal to 20％ of max HP to attackers of this unit.", 941, 143),
                           alias=143,
                           behavior={"family": "max_hp_reflect", "effects": [{"value": 20}]},
                           label="evility The Artifact (80): adapted - DD2 'Deals damage equal to N% of max HP to attackers of this unit' (value 20; mskill text "
                                 "and value from dd2source). the percent is of the ATTACKER's max HP per the community evility list (GameFAQs 'Disgaea D2: A Brighter Darkness - Evility List', Dark_Cecil: attackers lose 20% of THEIR max HP) "
                                 "and the Disgaea wiki; the Disgaea D2 code for this effect was NOT FOUND (EBOOT evility accessors, DD2EVIL1 section 3), so this is community evidence, not source code, and which attacks "
                                 "trigger it is unsettled. Carried by D5's own Malicious Reflect (143, alias row 26306) with kit "
                                 "row 26306 (max_hp_reflect 20): at the one damage_skill_dat call of the reflect rider in FUN_1401ADA40 (0x1401AE531, wrap_maxrefl) "
                                 "the hurt amount becomes 20% of the attacker's max HP (truncated, float arithmetic of the game) instead of 10% of the damage taken. "
                                 "D5's own rules stay: every damaging hit that reaches the rider triggers it (melee and ranged, as Malicious Reflect does), the "
                                 "game's clamp keeps the attacker at 1 HP or more (it never kills), and a unit holding the real 143 alone is unchanged. Not carried: "
                                 "the source's conditions for counters and special attacks (unknown), damage that is not a hit (poison, geo)"),
    # LONGTAIL2 (2026-11-14): Baal Slave 640 "Basic Principles" -- alias to D5 Softening Aura (2072) + the second-word family nullify_dealt (wrap_nullify).
    "DD2_Unique_640": dict(dd2_id=640, name="Basic Principles", relation="adapted", late=True,
                           row=arow(26307, "Basic Principles", "D5 adaptation: allies deal no damage to this unit, and this unit deals no damage to allies.",
                                    10580, 2072),
                           alias=2072,
                           behavior={"family": "nullify_dealt"},
                           label="evility Basic Principles (640): adapted - DD2 'Won't target allies when attacking, and won't be targeted by allies' (value 0, "
                                 "no number; the Disgaea D2 targeting code was not opened). Two halves on D5's rules. (1) 'won't be targeted by allies' = D5 "
                                 "Softening Aura (2072, 'Nullify damage taken from ally units'; alias row 26307): the game's own test at the top of "
                                 "damage_nullify_predicate nullifies a hit whose attacker is on the holder's side. (2) 'won't target allies when attacking' = kit row "
                                 "26307 (nullify_dealt, wrap_nullify): a hit with positive damage by the holder on a unit the SAME game test (events_env_team_of "
                                 "through cmdmenu_preds_p_2d8e00: team groups 0/4, 1/5, 3) calls an ally is nullified. Not carried: an ally can still be SELECTED as a "
                                 "target and the animation plays, only the damage is removed; heals and buffs to allies are untouched (the source says 'attacking'); "
                                 "the AI is not told; damage that is not a hit (poison, geo) and the seven other call sites of damage_nullify_predicate "
                                 "that the kit does not redirect (evility.py NULLIFY comment) are not covered; a hit on the holder itself by the holder counts as an ally hit "
                                 "(the game's test says so for 2072)"),
    # DD2EVIL1: Pringer Z 300 is an own exact row (was the alias row 24300 -> D5 1224 Heavy Stance, which also gave stats +30%).  Source: mskill
    # 300 "Cannot be lifted", value 0; the DD2 EBOOT's lift predicates (0x1B8D8, 0x22AD8) test evility 300 and nothing reads it as a stat.
    # D5 gate: the `flight` family (has_flight_like_evility, the 124 / 1224 / 5000 test inside cannot_be_carried_by).
    "DD2_Unique_300": dict(dd2_id=300, name="Heavy Stance", relation="exact", drop_alias=True,
                           row=row(24300, "Heavy Stance", "Cannot be lifted.", 10570, False, 0, 0, category=5),
                           behavior={"family": "flight"},
                           label="evility Heavy Stance (300): exact rule - DD2 'Cannot be lifted' (value 0, no number); kit flight row 24300 makes D5's own "
                                 "can't-be-carried test (the 124/1224/5000 check in cannot_be_carried_by) true for the holder, with none of D5 Heavy "
                                 "Stance's stats +30%; replaces the alias to D5 1224. DD2's own predicate also counts 580 T.O. Analyze (not Pringer Z)"),
}
# the source innate needs an effect the runtime does not have: nothing is built, the status page stays blank
NEEDS_NEW_EFFECT = {
    "DD2_Unique_140": (140, "Limitless Love", "Increase stats of ally angels by 50%: D5 has no angel unit type to select by"),
    "DD2_Unique_400": (400, "Burning Spirit", "ATK/DEF +5% each time the unit attacks or is targeted, with a maximum: a per-unit event counter"),
    "DD2_Unique_550": (550, "Flat Alliance", "stats +5% per 'flat' unit in the party: no measured flat-chest field to count"),
}

# TEXTHASH-D1C-DD2: these two rows' D5 description is the source text (nothing added), so it is a
# @text reference; every other row's description is our own adaptation wording (@authored).
SOURCE_TEXT_DESC = {"DD2_Class_22700", "DD2_Unique_300"}


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from d5lib import evility, textrefs
    for name, p in PACKS.items():
        if p.get("behavior"):
            evility.table({p["row"]["id"]: p["behavior"]})           # the runtime accepts the row, or the build stops
        p["id"] = p.get("link") or p["row"]["id"]
    for folder, p in PACKS.items():                 # TEXTHASH-D1C-DD2: names/rows as references, labels as ours
        p["name"] = textrefs.ref(p["name"])
        for key, value in list((p.get("row") or {}).items()):
            if not isinstance(value, str):
                continue
            if key.startswith("name"):
                p["row"][key] = textrefs.ref(value)
            elif key.startswith("desc"):
                p["row"][key] = (textrefs.ref(value) if folder in SOURCE_TEXT_DESC else textrefs.authored(value))
        p["label"] = textrefs.authored(p["label"])
    doc = dict(schema="dd2-innate-evilities/1",
               source="tools/build_dd2_innates.py (EVILFX3); DD2 mskill.dat text and values via d5lib.dd2source; applied by "
                      "d5lib/importers/_dd2_innates.py after the reviewed-abilities layer",
               id_rule="24000 + DD2 id when no installed learnable row moves, else the DD2 late band 26300+ (recorded per row)",
               packs=PACKS,
               needs_new_effect={k: dict(dd2_id=v[0], name=textrefs.ref(v[1]), why=v[2])
                                 for k, v in NEEDS_NEW_EFFECT.items()})
    out = ROOT / "d5lib/importers/dd2-innate-evilities.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote", out, len(PACKS), "packs")
