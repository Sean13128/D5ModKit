#!/usr/bin/env python3
"""Write `d5lib/importers/d4-evility-additions.json`: the EVILGAP1 (2026-11-10) D4 signature evility rows.

Read by `tools/build_d4_evility_overlay.py`, which merges them into `d4-evility-overlay.json` (the file the
importer reads).  Every number is sourced: name/text/value/mana from the D4 profile data
(Research/d4-expansion-20261018/mvp-successor-inputs-v1/source-profiles.json), donor rows from the D5 Skill.dat
catalog (mvp-evility-sweep/catalogs.json), rules from d5lib/evility.py's own vocabulary.  Ids are 8000 + the D4
evility id, all above 8187 (the learned-evility bitmap rule, CARRIERS2 s3), each owned by exactly one pack.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJ = Path("/Volumes/Data/Projects/D5")
CAT = json.loads((PROJ / "Research/d4-expansion-20261018/mvp-evility-sweep/catalogs.json").read_text())["d5"]
LOC = ("JP", "EN", "FR", "CHN", "KOR")
LATE = 27000                       # EVILFX2b: D4 late band, see d5lib/data/ownership_manifest.json
CARRIED = (7044, 7045, 7125)        # EVILFX2: Kojiro's installed alias rows, carried unchanged (not new rows)
SLOT_BY_MANA = ((100, 2), (250, 2), (1000, 3), (2500, 4), (5000, 4))


# TEXTHASH-D4: game text is never written here.  A name or description is a reference dict (``{"@text": sha256}``, ...);
# a note that quotes a description carries the quote as an inline marker, ``\u27e6{reference json}\u27e7``, so the string
# operations below (startswith / replace on the kit's own wording) keep working, and ``refs`` turns each marked note
# into the ``{"@segments": [...]}`` form the importer resolves at build time (docs/TEXT_REFS.md, tools/hash_d4_text.py).
_MARK = re.compile("\u27e6(.*?)\u27e7", re.S)


def refs(doc):
    if isinstance(doc, dict):
        return {k: refs(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [refs(v) for v in doc]
    if isinstance(doc, str) and "\u27e6" in doc:
        pieces, pos = [], 0
        for m in _MARK.finditer(doc):
            if doc[pos:m.start()]:
                pieces.append(doc[pos:m.start()])
            pieces.append(json.loads(m.group(1)))
            pos = m.end()
        if doc[pos:]:
            pieces.append(doc[pos:])
        return pieces[0] if len(pieces) == 1 and isinstance(pieces[0], dict) else {"@segments": pieces}
    return doc


def slot_for(mana):
    return next((c for b, c in SLOT_BY_MANA if mana <= b), 5)


def row(rid, name, desc, owner, learnable, mana, slot, **f):
    r = {"id": rid}
    r.update({f"name_{l}": name for l in LOC})
    r["slot_cost"] = slot if learnable else 0
    r.update({f"desc_{l}": desc for l in LOC})
    r.update(kind=0 if learnable else 1, effect_group=f.get("effect_group", 0), value1=f.get("value1", 0),
             value2=f.get("value2", 0), source=4, category=f.get("category", 0), subcategory=f.get("subcategory", 0),
             mana_cost=mana if learnable else 0, shop_rank=0, owner=owner, class_order=0,
             version_group=f.get("version_group", 100))
    return r


def alias(d4id, name, desc, owner, donor, learnable, mana):
    d = CAT[str(donor)]
    slot = d["slot_cost"] or slot_for(mana)
    return row(8000 + d4id, name, desc, owner, learnable, mana, slot, effect_group=d["effect_group"],
               value1=d["value1"], value2=d["value2"], category=d["category"], subcategory=d["subcategory"],
               version_group=d["version_group"])


def HELD_STATE(pack):
    import importlib.util
    sp = importlib.util.spec_from_file_location("bdo", ROOT / "tools/build_d4_evility_overlay.py")
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod.mod_state(mod.HELD / pack)


def build():
    m = {}
    # ---- group A: the kit's own families
    m["D4_Unique_490"] = dict(
        skill_rows=[row(8894, {"@text": "2ab13b0616f09f944d1ffc66224fdd8cb4e8415c8a176ead888a9a150f01ac57"}, "⟦{\"@template\": \"352f317fd442982d9cc8908bb579c7e9a67ede41e5f9b9e585e07c10fe82b940\", \"args\": [15], \"percent\": \"％\"}⟧", 10240, True, 40000, 5, value1=15)],
        behaviors={"8894": {"family": "dealt", "effects": [{"value": 15}],
                            "conditions": [{"kind": "attack_skill"}, {"kind": "attack_phys"}]}},
        adaptations=["evility Favorite Mark (894): adapted - D4 'weapon skills' are read as physical attack skills "
                     "(skill effect type physical; normal attacks excluded), +15% damage dealt (stored value 15), "
                     "kit family dealt, row 8894"])
    m["D4_Unique_460"] = dict(
        skill_rows=[row(8882, {"@text": "8b4fd55e81d4d9fab500d239c72cd3942a9c0fec4a48f77aa764d2639595bd74"}, "⟦{\"@template\": \"298018b1c3ec91fd122abf83ef5fb5d1c863c5fad0c42486fb5429973c05574b\", \"args\": [30], \"percent\": \"％\"}⟧", 18170, True, 7000, 5, value1=30)],
        behaviors={"8882": {"family": "conversion", "effects": [{"stat": "atk", "from": "def", "value": 30},
                                                                {"stat": "int", "from": "res", "value": 30}]}},
        adaptations=["evility Human Modification (882): adapted - ATK gains 30% of base DEF and INT 30% of base RES "
                     "(D4's text lists the pairs in that order), kit family conversion, row 8882"])
    # ---- group C: a D5 evility does the same thing (alias rows; the donor's rule and number are used)
    m["D4_Unique_220"] = dict(
        skill_rows=[alias(872, {"@text": "d97634207ca855c98ba525e17993a319b0d114f8e28ddd82abb15651920cd95d"}, "⟦{\"@template\": \"57f9284a08620841cc24ece5f006287adc8b34a0c8e18616a080d60c30382951\", \"args\": [10], \"percent\": \"％\"}⟧", 18110, 143, True, 40000)],
        aliases={"8872": 143},
        adaptations=["evility Malice of Confusion (872): D5 equivalent, same number - D5 Malicious Reflect (143) "
                     "inflicts 10% of damage taken on the attacker; alias row 8872"])
    m["D4_Unique_450"] = dict(
        skill_rows=[alias(880, {"@text": "c45ef61aab8fb970bbda2d45d37d27cb3cdca0c7f8bcb89d976d1681b3c801e7"}, "⟦{\"@template\": \"292bead1df1d506f6a89afd5c01bf467796051098a9da61240fe99225fa5b474\", \"args\": [20, 20], \"percent\": \"％\"}⟧", 18160, 6113, True, 40000)],
        aliases={"8880": 6113},
        adaptations=["evility Water Dragon Power (880): D5 equivalent, same numbers - D5 Hoarfrost Magic (6113) "
                     "water damage dealt +20%, taken -20%; alias row 8880"])
    m["D4_Unique_170"] = dict(
        skill_rows=[alias(873, {"@text": "8b12559313782d869ce2e3db1610496bc443365c06c7d19e2afe1f993da2a3c1"}, "D5 adaptation: ⟦{\"@template\": \"270661de2fdfe2eb342852ecc7015379dc7472b8eef9ddb7946e9a4a182e63fb\", \"args\": [20], \"trim\": 1}⟧ (D4: 10％). Uses D5 Death Spell's rule and number.", 10270, 6052, False, 0)],
        aliases={"8873": 6052},
        char_links={"10270": {"evility1": 8873, "evility_count": 1}},
        adaptations=["evility Death Magic (873): adapted - D5 Death Spell (6052) deathblow chance on magic is 20%, "
                     "D4 stores 10%; alias row 8873, innate"])
    m["D4_Unique_310"] = dict(
        skill_rows=[alias(627, {"@text": "7d17e860289688b02b44ff7560702b8a3a5637220b7597afd25c106f9d29a69c"}, {"@text": "04bff1320288eccbc804534474b9682801dba1d10f0f41a3cdcce33ffbcce52e"}, 10390, 1070, True, 5000)],
        aliases={"8627": 1070},
        char_links={"10390": {"evility1": 8625, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}},
        adaptations=["evility Angel Blessings (627): D5 equivalent - D5 Medical Heal (1070) cures all ailments when "
                     "using healing magic; alias row 8627"])
    m["D4_Unique_5301"] = dict(
        skill_rows=[alias(304, {"@text": "c87be339dd226e373bc1498b6596e506c97688019d7abc201c006f4c19694222"}, {"@authored": "D5 adaptation: multiplies the effect of support magic by 2 (D4: +50％). Uses D5 Medical Insertion's rule and number."}, 18220, 1180, False, 0)],
        aliases={"8304": 1180},
        magic_ids=[13018, 13019, 13020, 13027, 13028],   # the installed Chief's own ids (D4GAP1); a solo rebuild takes 13003+
        char_links={"18220": {"evility1": 8304, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}},
        adaptations=["evility Medical Insertion (304): adapted - D5 Medical Insertion (1180) multiplies support magic "
                     "by 2, D4 stores +50% (x1.5); alias row 8304, innate"])
    # ---- EVILGAP1b: one evility, one row, one owner.  These packs point their character at the owner's row
    # (innate link) and name the owning pack in mod.json `requires`.
    def ref(pack_, cid, owner_pack, rows, label):
        m[pack_] = dict(skill_rows=[], refs={str(r): owner_pack for r in rows}, requires=[owner_pack],
                        char_links={str(cid): {**{f"evility{i + 1}": (rows[i] if i < len(rows) else 0) for i in range(4)},
                                               "evility_count": len(rows)}},
                        adaptations=[label])
    # EVILGAP1c: the would-be owner class (1100 Ninja, 1130 Sorcerer, 1210 Celestial Host) is out of importer scope and
    # not installed (D5 has the class), so the unique owns the row itself at the same id, exact rule copied from the
    # held class pack's recorded row.
    def own(pack_, cid, d4id, owner_pack, label):
        st = HELD_STATE(owner_pack)
        r = json.loads(json.dumps(next(x for x in st["skill_rows"] if x["id"] == 8000 + d4id)))
        r["owner"] = cid
        e = m.setdefault(pack_, dict(skill_rows=[], adaptations=[]))
        e["skill_rows"] = e["skill_rows"] + [r]
        e["behaviors"] = {**e.get("behaviors", {}), str(r["id"]): st["behaviors"]["evilities"][str(r["id"])]}
        e["char_links"] = {str(cid): {"evility1": r["id"], "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}}
        e["adaptations"] = e["adaptations"] + [label]
    own("D4_Unique_5309", 18270, 211, "D4_Class_1130",
        "evility Cursed Dance (211): exact rule, row 8211 owned by this pack (stats -5% on enemies on the map, near_has of "
        "enemy radius 65535); innate. The D4 class family pack is out of importer scope, so there is no owner to reference")
    own("D4_Unique_5310", 18280, 351, "D4_Class_1100",
        "evility Misty Haze (351): adapted - row 8351 owned by this pack, `nullify` for front attacks at 50% rng as an "
        "evade stand-in; innate. The D4 class pack is out of importer scope")
    own("D4_Unique_310", 10390, 625, "D4_Class_1210",
        "evility Angel Protection (625): exact rule, row 8625 owned by this pack (`taken` aura, near_has radius 1 + element 0, "
        "-50); innate. The D4 class pack is out of importer scope")
    ref("D4_Unique_320", 10400, "D4_Class_1220", [8181, 8841],
        "evility Battle Order (181) and Prism Emblem (841): adapted reference - both are learnable in D4 but a unique cannot "
        "learn a row another pack owns, so they are linked as innate to rows 8181 and 8841 owned by D4_Class_1220; "
        "mod.json requires that pack. Friends (840, innate) is still missing")
    # ---- EVILFX1 (2026-11-10): rows the two new runtime pieces unlock, plus one D5 equivalent found on the way.
    # Appended so the earlier blocks stay byte-identical.
    # 840 Friends (Prism Red innate): kit scale map_squad (Evil Area -> squad).  Prism Red owns row 8840; the
    # Prism Ranger class (D4_Class_1220, also a D4 owner) is not rebuilt here and may reference it later.
    e = m["D4_Unique_320"]
    e["skill_rows"] = e["skill_rows"] + [row(8840, {"@text": "bd104d1b98d032274986497eeb7997c44a1d674b29140e43cd525d33468ecb6e"}, {"@authored": "Increase stats by 5％ x the # of dispatched squad allies."},
                                              10400, False, 0, 0, value1=5)]
    e["behaviors"] = {**e.get("behaviors", {}),
                      "8840": {"family": "stats", "effects": [{"stat": "all", "value": 5, "per": "map_squad"}]}}
    e["char_links"] = {"10400": {"evility1": 8840, "evility2": 8181, "evility3": 8841, "evility4": 0, "evility_count": 3}}
    e["adaptations"] = [a.replace(" Friends (840, innate) is still missing", "") for a in e["adaptations"]] + [
        "evility Friends (840): adapted - D4 counts dispatched allies of the holder's Evil Area; D5 has squads instead, "
        "so row 8840 is +5% all stats x deployed allies in the holder's own squad (kit scale map_squad, EVILFX1; holder "
        "not counted, as in D4 FUN_1401ba0a0); innate, owned by this pack"]
    # 667 Tyrant Guard (Pringer X innate): D5 First Impression (6047, first damage of the stage nullified) by alias,
    # re-armed every round edge by the kit family rearm_first_damage (EVILFX1).
    m["D4_Unique_210"] = dict(
        skill_rows=[alias(667, {"@text": "69f6acb9bff235a5308c9ec741adf2efd8c8de6653dc90ecdf7c6316b199a606"}, {"@text": "909e5f2ade4a61946253a9beed6fd3338253bcf05e63fa675f43591c16de7bbe"}, 10260, 6047, False, 0)],
        aliases={"8667": 6047},
        behaviors={"8667": {"family": "rearm_first_damage"}},
        char_links={"10260": {"evility1": 8667, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}},
        adaptations=["evility Tyrant Guard (667): exact rule for a threshold of 0 or 1 (D4SIG6) - D4 FUN_1400FF700 (target result, "
                     "lines 1768-1783) nullifies a hit while the unit's hit counter (unit +0x1183, +1 per landed hit in "
                     "FUN_140123940, reset to 0 in FUN_1400F3C20 inside the all-units turn-end pass FUN_1402EB670) is under "
                     "max(1, T) and keeps a lethal result (result HP below 1); T is the number of Tyrant Cult (669) holders on "
                     "the team (FUN_1402E9400) and no pack here carries 669, so T is 0: the first non-lethal hit of every turn "
                     "is nullified. Row 8667 = alias to D5 First Impression 6047 (nullifies while stat record byte +0xDF9 is 0, "
                     "which damage_apply_damage sets on the first damage) + kit family rearm_first_damage (the byte is cleared "
                     "at every round edge) + wrap_firstimp (the call to cmdmenu_preds_p_2068b0 inside damage_nullify_predicate "
                     "answers 'not carried' for this holder when the hit's damage is at least its HP, so a lethal hit goes "
                     "through as in D4); innate. Not measured: that the round-edge clear (0x1405F8FFC) falls where D4's "
                     "turn-end pass does, D4's +0x7B6 test on the counter, and a counter above 1 (needs T of 2 or more)"])
    # 215 Dismal Omen (Hugo, learnable): D5 Evil Spirit (141) has the same text and number.
    e = m["D4_Unique_170"]
    e["skill_rows"] = e["skill_rows"] + [alias(215, {"@text": "7308205e9a1701793dd68621930c14d19761c6656859d93597ceacc9c7aba961"}, "⟦{\"@template\": \"21796cbf00cc67ac49a86b69aa9ffe9c14130aa81c78c6d60bc0f17d049d8c69\", \"args\": [50], \"percent\": \"％\"}⟧",
                                               10270, 141, True, 1000)]
    e["aliases"] = {**e["aliases"], "8215": 141}
    e["adaptations"] = e["adaptations"] + [
        "evility Dismal Omen (215): adapted - D5 Evil Spirit (141), same text and 50: D5 multiplies heals received by "
        "the holder's enemies by 0.5 per holder (FUN_1401fff40); D4 subtracts 50 from the heal percent of heals cast by "
        "the holder's enemies (FUN_1400ff700); alias row 8215, learnable"]
    # ---- EVILFX2 (2026-11-10): rows today's vocabulary already expresses.  Appended; earlier blocks unchanged.
    # 697 Official Protection (Senator Kojiro innate, SMALLFIX1 found it unmapped).  The Bouncer class pack
    # (D4_Class_1140, in scope and installed) already owns row 8697 with exactly this rule (`stats` aura, near_has ally
    # radius 1, DEF and RES +20), so Kojiro references it: innate link + `requires`, no second owner.
    ref("D4_Unique_4390", 18210, "D4_Class_1140", [8697],
        "evility Official Protection (697): exact text and number, innate - DEF and RES +20% for each ally standing on a "
        "panel next to Kojiro (kit `stats` aura, near_has ally radius 1; Kojiro himself is not raised). Row 8697 is owned "
        "by D4_Class_1140 (Bouncer, the D4 class that has the same innate evility); mod.json requires that pack. D4's own "
        "adjacency arithmetic was not traced")
    # Kojiro is a D4GAP1 pack and has no held state: the overlay record replaces the builder's emission, so his three
    # installed learnable alias rows (7044 Synch Guard -> 1151, 7045 Mind Mastery -> 1041, 7125 Offense Mastery -> 1191)
    # are carried here verbatim from the installed pack (same ids, so no learned bit moves).
    import importlib.util
    sp = importlib.util.spec_from_file_location("bdo", ROOT / "tools/build_d4_evility_overlay.py")
    bdo = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(bdo)
    kj = bdo.mod_state(PROJ / "Local/Installed D5ModKit/mods/D4_Unique_4390")
    carried = [r for r in kj["skill_rows"] if r["id"] in CARRIED]
    assert sorted(r["id"] for r in carried) == sorted(CARRIED), "Kojiro's installed alias rows changed"
    m["D4_Unique_4390"]["carried_rows"] = carried      # not new rows: outside the 8188+ rule for added rows
    m["D4_Unique_4390"]["aliases"] = {str(i): kj["aliases"][str(i)] for i in sorted(CARRIED)}
    # 845 Let's Go! My Lady (Kyoko, learnable): the held row's near_has named evility 8045, which nobody carries, so the
    # aura never reached Raspberyl (char 650).  The provider id is the row's own id.
    # 844 Beryl's Servant 1 (Kyoko innate): "When next to Raspberyl, evasion is increased by 50%."  Evade stand-in as
    # for Reprachon's Misty Haze 8351: the hit is nullified at a 50% roll, while D5's Raspberyl (650) is adjacent.
    m["D4_Unique_350"] = dict(
        # EVILFX2b (save safety): 8844 would sort before 25 installed learnable rows and move their learned bits, so
        # the row lives in the D4 late band, 27000 + the D4 id (ownership manifest); the mapping is recorded in late_ids.
        skill_rows=[row(LATE + 844, {"@text": "d846c94a44cdc1eb9869e84b6b488ee40e55f63da79fdfd3e5542fec4fbdddeb"}, {"@authored": "50％ chance to evade attacks when next to Raspberyl."}, 10420, False, 0, 0, value1=50)],
        late_ids={"844": LATE + 844},
        char_links={"10420": {"evility1": LATE + 844, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}},
        behaviors={str(LATE + 844): {"family": "nullify", "conditions": [{"kind": "near_char", "of": 1, "radius": 1, "id": 650},
                                                                {"kind": "rng", "id": 50}]},
                   "8845": {"family": ["stats", "aura"], "effects": [{"stat": "atk", "value": 10}],
                            "conditions": [{"kind": "near_has", "of": 1, "radius": 1, "id": 8845},
                                           {"kind": "char", "id": 650}]}},
        adaptations=["evility Beryl's Servant 1 (844): adapted - D4 raises evasion by 50 while next to Raspberyl; row 27844 "
                     "(late band 27000 + D4 id, not 8844: a new row must not move an installed learnable row's position) "
                     "nullifies a hit at a 50% roll while D5's Raspberyl (character 650) stands on a neighbouring panel "
                     "(kit `nullify` + near_char + rng, the evade stand-in Misty Haze 8351 uses); innate, owned by this pack",
                     "evility Let's Go! My Lady (845): fixed - the aura row named provider evility 8045 instead of its own "
                     "id 8845, so Raspberyl (D5 character 650) never received ATK +10% next to Kyoko"])
    # ---- EVILFX3 (2026-11-10): class innates.  GAMETRUTH1 found every D4 class pack linking no innate evility; the D4
    # source gives one innate per class, the same id on all six rank rows (char.dat +0x1B4, read with d4source).  New
    # rows go to the late band (27000 + D4 id): each would sort before installed learnable rows.
    def ranks(first, link):
        return {str(first + i): {"evility1": link, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}
                for i in range(6)}

    def innate(pack_, first, d4id, name, desc, label, behavior=None, donor=None, value1=0):
        rid = LATE + d4id
        r = alias(d4id, name, desc, first, donor, False, 0) if donor else row(rid, name, desc, first, False, 0, 0, value1=value1)
        r["id"] = rid
        e = dict(skill_rows=[r], late_ids={str(d4id): rid}, char_links=ranks(first, rid), adaptations=[label])
        if donor:
            e["class_alias"] = {str(rid): donor}      # a class pack carries its alias map in its class json
        if behavior:
            e["behaviors"] = {str(rid): behavior}
        m[pack_] = e
    innate("D4_Class_1200", 14200, 121, {"@text": "edf4608bc88ed1f5d31d3bb4b7eef9254ba7578b4eb60463a83166c762b1ec8e"}, "⟦{\"@template\": \"775b0ec4b9dc8bda0e21ce2a1af1ce4e098f744de1ac626cddb560376c5d9c22\", \"args\": [100], \"percent\": \"％\"}⟧",
           "evility One Man Army (121): D5 equivalent, same number - D5 Belated Hero (6059) '⟦{\"@template\": \"15d983863273938f40b494fed094f9739d0e1f52fc6d7cb3de94702e4f8d65ed\", \"args\": [100], \"trim\": 1}⟧'; alias row 27121 (late band), innate on all six ranks", donor=6059)
    innate("D4_Class_2170", 14670, 663, {"@text": "0c9aa9584b568dad11abf9e8729424c03db7c4d2190e8e1b7b94999e2e816103"},
           "D5 adaptation: increase ATK by 10％ every time attacked by a non-elemental attack. Uses D5 Impact Charge's rule.",
           "evility Rising Dragon (663): adapted - D4 '⟦{\"@template\": \"0722264ffa6b8b238ff6e007b71ac0cfb49fda93ef152776544e7494e71eea4f\", \"args\": [10], \"percent\": \"%\", \"trim\": 1}⟧'; D5 Impact Charge (2065) has the same 10 but counts non-elemental attacks only and keeps its own reset rule; alias row 27663 (late band), innate on all six ranks", donor=2065)
    innate("D4_Class_1170", 14170, 690, {"@text": "7e98755d40916e7a97770b2139560aed3d9ffb058c3675ea5c5325c9b5dabded"}, "Increase SPD by 5％ x panels moved this turn.",
           "evility Speedy Move (690): exact rule - D4 '⟦{\"@template\": \"1ffd1b94875aa1155f3ab4181da45cbf334fb7e77d5d5deeb9b26cc029f92740\", \"args\": [5], \"percent\": \"%\", \"trim\": 1}⟧' (D4SIG5, source: FUN_1401BA0A0 term 0x2B2 adds 5 x the unit's moved-panel counter, battle record +0x4E8, to the SPD percent slot at unit +0x17FE after that slot's clamp; FUN_1401B4010 reads the slot at 0x1401B6AA9 into the SPD percent sum that scales the stat by (100 + sum) / 100; the counter is set by FUN_1400F1200 to the movement-cost value of the move's destination cell and zeroed by FUN_1400F3C20, the per-unit end-of-turn routine, which is followed by the stat recalculation); row 27690 is SPD +5% x D5's panels-moved counter (battle record +0x61C, the one D5's Assault Attack 1020 and Sonic Charge 105 multiply by), kit family stats with scale movement_cost; D5's counter is added to by confirm_push_move_entry (the move's cost, restored on undo) and zeroed by turn_t3_per_unit_end_turn, the same routine (same idle-counter block), which turn_t1_per_unit_hp_sp follows with unit_recalc; innate on all six ranks. Live read (LIVEPROOF3): SPD 112800 -> 129720, +15% right after a 3-panel move, control unchanged. Not carried: D4 sets the counter to the last move's value where D5 adds each confirmed move (the same with one move per turn); the read after End Turn (counter 0, SPD back) is not measured", value1=5,
           behavior={"family": "stats", "effects": [{"stat": "spd", "value": 5, "per": "movement_cost"}]})
    innate("D4_Class_2130", 14630, 692, {"@text": "4b06232dd572d307d575b3474755e6b34249752da1eb77c351177f225cd88376"}, "Increase elemental damage dealt by 10％ x panels moved.",
           "evility Accel Element (692): adapted - D4 '⟦{\"@template\": \"e85bf2cae5e985dd43a7bc571b233ff055f2cfaf9d58c9cb8b5e0be1b809706f\", \"args\": [10], \"percent\": \"%\", \"trim\": 1}⟧'; row 27692 is damage dealt +10% x D5's panels-moved counter for an attack that carries an element (kit family dealt, scale movement_cost, condition element_any; no cap, D5's own Assault Attack caps at 200); innate on all six ranks",
           value1=10, behavior={"family": "dealt", "effects": [{"value": 10, "per": "movement_cost"}],
                                "conditions": [{"kind": "element_any"}]})
    innate("D4_Class_2190", 14690, 693, {"@text": "2bb31862854a8a5d11e5806434563580d92f7cc62f3c0f49d31ac2150d648176"}, "⟦{\"@template\": \"b1660261f5930bf4d7688e61674f914403837d1885ed5ea71205527c220a9718\", \"args\": [], \"percent\": \"％\"}⟧",
           "evility Invincible Ruler (693): exact text and number - damage dealt +50% while D5's panels-moved counter is 0 "
           "(kit family dealt, condition not_moved); row 27693 (late band), innate on all six ranks. D4's own 'moved' test "
           "was not traced", value1=50,
           behavior={"family": "dealt", "effects": [{"value": 50}], "conditions": [{"kind": "not_moved"}]})
    # 840 Friends: the class is the D4 owner too.  Row 8840 (installed, shipped by Prism Red's pack since EVILFX1) moves
    # to the class pack - same id, same position, same rule - so the class owns it and Prism Red, which already
    # `requires` the class for 8181 / 8841, references it.  No pack has to require a pack that requires it.
    red = m["D4_Unique_320"]
    friends = next(r for r in red["skill_rows"] if r["id"] == 8840)
    red["skill_rows"] = [r for r in red["skill_rows"] if r["id"] != 8840]
    m["D4_Class_1220"] = dict(
        skill_rows=[dict(friends, owner=14220)], behaviors={"8840": red["behaviors"].pop("8840")},
        char_links=ranks(14220, 8840),
        adaptations=["evility Friends (840): innate on all six ranks, row 8840 now owned by this pack (the D4 class is the "
                     "source owner; D4_Unique_320 references it). Adapted as before: D4 counts dispatched Evil Area allies, "
                     "row 8840 is +5% all stats x deployed allies in the holder's own squad (kit scale map_squad)"])
    red["refs"] = {**red["refs"], "8840": "D4_Class_1220"}
    red["adaptations"] = [a.replace("innate, owned by this pack", "innate; since EVILFX3 the row is owned by D4_Class_1220 and referenced")
                          for a in red["adaptations"]]
    # ---- EVILNEW2 (2026-11-11): 875 Phantom Lover (Marona innate), "Increase stats by 5% per ally Spirit unit on map".
    # The Spirit family is D4_Class_2050 (class ids 14550..14555, source class group 205, EVILNEW1).  The kit's map_class
    # scale counts deployed units of either team (the native walk uses relation ANY, d5evil.inc.asm .sc_f_go); an
    # ally-only scale needs a new native scale, so this is the labelled approximation.
    m["D4_Unique_440"] = dict(
        skill_rows=[row(LATE + 875, {"@text": "7604358d927f3b10e8ede948cb66801e91a62d331484d6aa647380ce77d9fb2e"}, {"@authored": "D5 adaptation: increase stats by 5％ per Spirit unit on the map (either team)."},
                        18150, False, 0, 0, value1=5)],
        late_ids={"875": LATE + 875},
        char_links={"18150": {"evility1": LATE + 875, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}},
        behaviors={str(LATE + 875): {"family": "stats", "effects": [{"stat": "all", "value": 5, "per": "map_class"}],
                                     "classes": [14550, 14551, 14552, 14553, 14554, 14555]}},
        adaptations=["evility Phantom Lover (875): adapted - D4 '⟦{\"@template\": \"7e110bb1a400b68f5ddc60acf8d837c6f29667990d8ca675cb49f31ac125c68c\", \"args\": [5], \"percent\": \"%\", \"trim\": 1}⟧'; row 27875 (late band) is +5% all stats per deployed Spirit-family unit (D4_Class_2050 ranks 14550-14555, kit scale map_class, six rows). APPROXIMATION: the kit's map_class counts units of EITHER team, so an enemy Spirit also raises Marona (source counts allies only); Marona herself is never counted. Whether the source raises all eight stats or six is not confirmed; the D5 total-stat cap applies; innate, owned by this pack"])
    # ---- D4SIG1 (2026-11-11): five more signature innates the existing runtime can carry, every one labelled.  Appended;
    # earlier blocks stay byte-identical.  Late band 27000 + the D4 id.
    # 691 Mind Killer (Death class innate; Hugo's innate too): "Inflict 50% of damage to SP during an attack."  D5 Habitual
    # Licker (3011) is the same effect ("25% of damage inflicted by an attack is also inflicted to SP"); the native code
    # reads the percent from the donor's own Skill row (FUN_1401ada40 +0x38), so the alias gives 25, not 50.
    innate("D4_Class_2120", 14620, 691, {"@text": "8d1e1108fcae2f1fbc434a27bdd2355cc3c37cf1e3db0ea308d78e9a7e618c83"},
           "D5 adaptation: ⟦{\"@template\": \"83641fd0bda736fa56b26ca5da582ee55198a6629ff6b6b0f43126804073f379\", \"args\": [25], \"trim\": 1}⟧ (D4: 50％). Uses D5 Habitual Licker's rule and number.",
           "evility Mind Killer (691): adapted - D4 '⟦{\"@template\": \"3b55103e6762ed7ebd6729e394b4a87657b69d52c596077e23e940192b83f1ab\", \"args\": [50], \"percent\": \"%\", \"trim\": 1}⟧'; D5 Habitual Licker (3011) is the same effect but its percent is read from the donor row, 25 not 50; alias row 27691 (late band), innate on all six ranks. Hugo (D4_Unique_170) references this row", donor=3011)
    e = m["D4_Unique_170"]
    e["refs"] = {"27691": "D4_Class_2120"}
    e["requires"] = ["D4_Class_2120"]
    e["char_links"] = {"10270": {"evility1": LATE + 691, "evility2": 8873, "evility3": 0, "evility4": 0, "evility_count": 2}}
    e["adaptations"] = e["adaptations"] + [
        "evility Mind Killer (691): adapted, Hugo's source innate - references row 27691 owned by D4_Class_2120 (D5 Habitual "
        "Licker 3011: 25% of damage also inflicted to SP, D4 stores 50%); mod.json requires that pack. Death Magic 8873, "
        "which EVILGAP1 had linked as the innate, stays linked in the second slot"]
    # 851 Jet Black Sword (Gig innate): "During magichange or fusion, Equipment Aptitude increases 50%."  The kit has no
    # Magichange condition; D5 Demon Researcher (1185) is gated by the same state (it raises the stats of the equipped
    # Magichange weapon, +15 read from the donor row).
    m["D4_Unique_340"] = dict(
        skill_rows=[dict(alias(851, {"@text": "f3746d817975269481099b17d4ed2fdc5be36abf4bb1750a233f2114a066b405"},
                               {"@authored": "D5 adaptation: increase stats of the Magichange weapons by 15％ (D4: Equipment Aptitude +50％ during magichange or fusion). Uses D5 Demon Researcher's rule and number."},
                               10410, 1185, False, 0), id=LATE + 851)],
        late_ids={"851": LATE + 851},
        aliases={str(LATE + 851): 1185},
        char_links={"10410": {"evility1": LATE + 851, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}},
        adaptations=["evility Jet Black Sword (851): adapted - D4 'During magichange or fusion, Equipment Aptitude increases "
                     "50%'; D5 Demon Researcher (1185) raises the stats of the Magichange weapons the holder equips (same gate: "
                     "only while a Magichange weapon is equipped) by 15 (donor row), not 50, and only the Magichange weapon, "
                     "not all equipment; D4's giant fusion has no D5 counterpart. Alias row 27851 (late band), innate, owned "
                     "by this pack"])
    # 892 Everyone's Mechanic (Nagi innate): "Increase stats of ally weapons by 10%."  potency + aura, map-wide ally recipients
    # (radius 65535 is the kit's "anywhere"); D4 sums the value over every ally holder and caps the sum at 100 (FUN_1401b4010).
    e = m["D4_Unique_490"]
    e["skill_rows"] = e["skill_rows"] + [row(LATE + 892, {"@text": "4526b86abb5bbe791855c57faf0c4d944ab463f9bbf99491011ae41389d6dce0"},
                                              {"@authored": "D5 adaptation: increase equipment stats of ally units by 10％ (D4: weapons only)."},
                                              10240, False, 0, 0, value1=10)]
    e["late_ids"] = {"892": LATE + 892}
    e["behaviors"] = {**e["behaviors"], str(LATE + 892): {
        "family": ["potency", "aura"], "effects": [{"stat": "all", "value": 10}],
        "conditions": [{"kind": "near_has", "of": 1, "radius": 65535, "id": LATE + 892}]}}
    e["char_links"] = {"10240": {"evility1": LATE + 892, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}}
    e["adaptations"] = e["adaptations"] + [
        "evility Everyone's Mechanic (892): adapted - D4 '⟦{\"@template\": \"67a88e7a7a3b3de588518a33db86752f9c17e953eeef294c18f02701b4a96ace\", \"args\": [10], \"percent\": \"%\", \"trim\": 1}⟧' (map-wide, summed over every ally holder, total capped at 100); row 27892 is equipment potency +10% on every ally unit on the map while Nagi is deployed (kit potency + aura, near_has ally radius 65535). APPROXIMATION: the potency words scale weapons AND armour, so allies' armour is raised too; one Nagi counts once, so two holders do not stack; Nagi himself is not raised. Innate, owned by this pack"]
    # 881 Unlosing Mode (Pirohiko innate): "Stats increased by 50% when activated. (Lasts 3 turns)"; D4 activates it from a
    # menu command, once per stage (EVILNEW1).  No command in the runtime: the same +50% for the first three rounds.
    e = m["D4_Unique_460"]
    e["skill_rows"] = e["skill_rows"] + [row(LATE + 881, {"@text": "450ee08136160affe4878be027d44e60195471399f31f5be706358854ee64976"},
                                              {"@authored": "D5 adaptation: stats increased by 50％ for the first 3 rounds of a stage (D4: activated by command, lasts 3 turns)."},
                                              18170, False, 0, 0, value1=50)]
    e["late_ids"] = {"881": LATE + 881}
    e["behaviors"] = {**e["behaviors"], str(LATE + 881): {
        "family": "stats", "effects": [{"stat": "all", "value": 50}], "conditions": [{"kind": "turn_max", "id": 3}]}}
    e["char_links"] = {"18170": {"evility1": LATE + 881, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}}
    e["adaptations"] = e["adaptations"] + [
        "evility Unlosing Mode (881): adapted - D4 '⟦{\"@template\": \"2d7beb882b9379e9212ee9c1bb494606c7619026c0e705a8d3b9401e626babef\", \"args\": [50], \"percent\": \"%\"}⟧' is a menu command used once per stage (EVILNEW1: D4 0x14030B440 / 0x1402D8510); the runtime has no command, so row 27881 is stats +50% while the battle round counter is at most 3 (kit stats + turn_max): automatic, from the start of the stage, not on demand. The counter's first value in a battle is not measured, so the window is 3 or 4 rounds. Innate, owned by this pack"]
    # ---- EVILCAP1 (2026-11-11): three runtime capabilities (scales map_class_ally/enemy, family sp_damage_percent,
    # conditions magichange_host/magichange_turns) make four labelled signature rows follow the source text, and Ash's
    # Eccarlate buildable.  Appended; the blocks above stay byte-identical.  Each replaces its label, never appends one.
    def relabel(pack_, start, text):
        e = m[pack_]
        e["adaptations"] = [text if a.startswith(start) else a for a in e["adaptations"]]
        assert text in e["adaptations"], (pack_, start)
    # 875 Phantom Lover: D4 FUN_1401ba0a0 adds value x local_128[holder's team byte], the count of OTHER battle units of
    # that team whose class group (+0x1806) is 0xCD (205, Spirit).  Ally-only scale, same six D5 class ids.
    e = m["D4_Unique_440"]
    e["skill_rows"][0].update({f"desc_{l}": "Increase stats by 5％ per ally Spirit unit on the map." for l in LOC})
    e["behaviors"][str(LATE + 875)]["effects"][0]["per"] = "map_class_ally"
    # D4SIG3 (2026-11-12): D4's percent is stored at unit+0x5BE by FUN_1401ba0a0 and applied by FUN_1401b4010 (param_2,
    # flag 1) to SIX values only: ATK, DEF, INT, RES, HIT, SPD (final stat array unit+0xD30..0xD58; HP +0xD20 and SP
    # +0xD28 are not in that block).  The pack raised all eight; it now raises the traced six.
    e["behaviors"][str(LATE + 875)]["effects"] = [{"stat": s, "value": 5, "per": "map_class_ally"}
                                                  for s in ("atk", "def", "int", "res", "hit", "spd")]
    relabel("D4_Unique_440", "evility Phantom Lover (875)",
            "evility Phantom Lover (875): exact text and number - D4 '⟦{\"@template\": \"7e110bb1a400b68f5ddc60acf8d837c6f29667990d8ca675cb49f31ac125c68c\", \"args\": [5], \"percent\": \"%\", \"trim\": 1}⟧'; row 27875 (late band) is +5% per deployed ALLY Spirit-family unit (D4_Class_2050 ranks 14550-14555, kit scale map_class_ally, six rows), Marona herself never counted (D4 FUN_1401ba0a0 skips the holder, counts the holder's team, class group 205). Stat set traced (D4SIG3): the sum goes into the percent stored at unit+0x5BE which FUN_1401b4010 applies to ATK, DEF, INT, RES, HIT and SPD only (not HP or SP), so the row raises those six; the D5 total-stat cap applies; innate, owned by this pack")
    # 691 Mind Killer: the alias to 3011 stays (it is what reaches FUN_1401ADA40's Habitual Licker branch); the row's own
    # sp_damage_percent 50 replaces the donor's 25 there (wrap_spdmg).
    e = m["D4_Class_2120"]
    r = e["skill_rows"][0]
    r.update({f"desc_{l}": "⟦{\"@template\": \"3b55103e6762ed7ebd6729e394b4a87657b69d52c596077e23e940192b83f1ab\", \"args\": [50], \"percent\": \"％\"}⟧" for l in LOC}, value1=50)
    e["behaviors"] = {str(LATE + 691): {"family": "sp_damage_percent", "effects": [{"value": 50}]}}
    relabel("D4_Class_2120", "evility Mind Killer (691)",
            "evility Mind Killer (691): source text and number - D4 '⟦{\"@template\": \"3b55103e6762ed7ebd6729e394b4a87657b69d52c596077e23e940192b83f1ab\", \"args\": [50], \"percent\": \"%\", \"trim\": 1}⟧'; row 27691 (late band) keeps its alias to D5 Habitual Licker (3011), the game's own 'damage also inflicted to SP' code, and carries kit row sp_damage_percent 50 (EVILCAP1), which hands that code 50 instead of 3011's 25. Innate on all six ranks. Hugo (D4_Unique_170) references this row")
    relabel("D4_Unique_170", "evility Mind Killer (691)",
            "evility Mind Killer (691): Hugo's source innate, source text and number - references row 27691 owned by "
            "D4_Class_2120 (alias to D5 Habitual Licker 3011 plus kit row sp_damage_percent 50, EVILCAP1); mod.json "
            "requires that pack. Death Magic 8873, which EVILGAP1 had linked as the innate, stays linked in the second slot")
    # 851 Jet Black Sword: D4 FUN_1401b4010 adds the value to the holder's eight equipment-aptitude terms while its
    # Magichange timer (+0x17f0) is non-zero, and again in the giant-fusion branch (+0x2128).  The holder is the wielder:
    # D5's unit_stats_evil_rebuild_list gives the host the participant's innate evilities while a slot holds one.
    e = m["D4_Unique_340"]
    e["skill_rows"] = [row(LATE + 851, {"@text": "f3746d817975269481099b17d4ed2fdc5be36abf4bb1750a233f2114a066b405"}, {"@authored": "During Magichange, Equipment Aptitude increases 50％."},
                           10410, False, 0, 0, value1=50)]
    e.pop("aliases")
    e["behaviors"] = {str(LATE + 851): {"family": "potency", "effects": [{"stat": "all", "value": 50}],
                                        "conditions": [{"kind": "magichange_host"}]}}
    relabel("D4_Unique_340", "evility Jet Black Sword (851)",
            "evility Jet Black Sword (851): adapted - source text and number for Magichange - D4 'During magichange or fusion, "
            "Equipment Aptitude increases 50%'; row 27851 (late band) is equipment potency +50% on all eight stats while "
            "the holder wields a Magichange weapon (kit potency + condition magichange_host, EVILCAP1). D5 hands Gig's "
            "innate to the unit wielding him (unit_stats_evil_rebuild_list), so the wielder is raised, as in D4 "
            "(FUN_1401b4010). Not carried: D4's giant fusion, which D5 does not have. No alias any more (was D5 Demon "
            "Researcher 1185, +15% weapon stats). Innate, owned by this pack")
    # 878 Eccarlate (Ash innate): D4 FUN_1401ba0a0 adds the value to the stat percent while the holder's battle-record
    # Magichange turns byte (+0x61C, copied from unit +0x17f0) is 1.  D5's host slot turns byte reads 1 on the last turn
    # (turn_h13 ends the Magichange when it reads 1).  Ash is a humanoid: he is the wielder, his own row.
    e = m["D4_Unique_450"]                      # Water Dragon Power 8880 (group A) stays as it is
    e["skill_rows"] = e["skill_rows"] + [row(LATE + 878, {"@text": "0bea17f0f200fcda7aad297c635207ac19c95a62c7446485aedcbe3b4fd781b0"}, {"@authored": "Stats increased by 100％ on the last turn of a Magichange."},
                                              18160, False, 0, 0, value1=100)]
    e["late_ids"] = {"878": LATE + 878}
    e["char_links"] = {"18160": {"evility1": LATE + 878, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}}
    e["behaviors"] = {str(LATE + 878): {"family": "stats", "effects": [{"stat": s_, "value": 100} for s_ in ("atk", "def", "int", "res", "hit", "spd")],
                                        "conditions": [{"kind": "magichange_turns", "id": 1}]}}
    e["adaptations"] = e["adaptations"] + [
        "evility Eccarlate (878): source text and number - D4 '⟦{\"@template\": \"026b501ce5beb67bb4bb6db43aa5d9c44620cdececfa8cb3c6e53b7c7413d2a7\", \"args\": [100], \"percent\": \"%\", \"trim\": 1}⟧'; row 27878 (late band) is +100% ATK/DEF/INT/RES/HIT/SPD (not HP/SP: D4SIG3 trace of FUN_1401ba0a0 -> FUN_1401b4010) while a weapon slot of the holder has a Magichange participant and that slot's remaining-turn byte is 1 (kit stats + condition magichange_turns 1, EVILCAP1). Not measured: when D5 recomputes the stat aggregate after turn_h13 lowers the counter to 1 (turn_h13 itself calls no recalc). Innate, owned by this pack"]
    # ---- D4SIG2 (2026-11-12).  Appended; the blocks above stay byte-identical.
    # (1) Wording, no data change.  The tracker's rule (Tools/build_tracker.py apply_installed_evilities) reads a line as exact
    # only when it says "exact text and number" / "exact rule" / "D5 equivalent", and as "unclassified" (partial) otherwise.
    # The five EVILCAP1 lines carry the source text and number (same wording the Invincible Ruler line uses), with their
    # remaining caveats kept in the sentence, so they take that label.  Hugo's second slot (Death Magic 873) is not what the
    # D4 source gives him (his source evility is 691 only), so its line no longer calls itself his innate.
    # Coordinator 2026-11-12: Gig (D5 +15 on the Magichange weapon vs D4 +50 aptitude) and Marona (6 vs 8 stats, untraced) keep
    # their honest "adapted" reading; only rows whose text AND number match the source take the exact label.
    for pack_ in ("D4_Class_2120", "D4_Unique_170", "D4_Unique_450"):
        m[pack_]["adaptations"] = [a.replace("source text and number", "exact text and number")
                                   for a in m[pack_]["adaptations"]]
    relabel("D4_Unique_170", "evility Death Magic (873)",
            "evility Death Magic (873): adapted - D5 Death Spell (6052) deathblow chance on magic is 20%, D4 stores 10%; alias "
            "row 8873, kept in Hugo's second slot since EVILGAP1; the D4 source gives Hugo only Mind Killer (691), so this "
            "row is an extra, not one of his source evilities")
    # Mystic Beast: 10% damage per panel moved is D5's own Assault Attack (1020) mechanism, evaluated at the hit; the counter is
    # the one D5's own text calls "panels moved".  Same standard as Invincible Ruler's line.
    m["D4_Class_2130"]["adaptations"] = [
        a.replace("evility Accel Element (692): adapted - ", "evility Accel Element (692): exact text and number - ")
        for a in m["D4_Class_2130"]["adaptations"]]
    # Pringer X: the line named a difference it had not traced but did not say "adapted"; the tracker read it as unclassified.
    m["D4_Unique_210"]["adaptations"] = [
        a.replace("evility Tyrant Guard (667): ", "evility Tyrant Guard (667): adapted - ", 1)
        if a.startswith("evility Tyrant Guard (667): ") and "adapted" not in a and "exact rule" not in a else a
        for a in m["D4_Unique_210"]["adaptations"]]
    # (2) 807 Stone Statue (Demon Beast innate): "Increase DEF by 10% every turn of not moving."  D4SIG8 (2026-11-13) makes it an EXACT rule:
    # D4 FUN_1400F3C20 (per unit, round edge) raises the holder's counter (unit +0x22DE, a byte) by 1 (at most 10) when the unit's move cost
    # (+0x4E8) is 0 and ZEROES it otherwise; FUN_1401B4010 adds value x counter to DEF (cap 100).  Row 27807 is DEF +10% x D5's idle-turn counter
    # (stat record byte SR+1, kit scale idle_turns, read at unit_recalc); wrap_endturn makes the COUNTING D4's at the three calls of
    # turn_t3_per_unit_end_turn.
    innate("D4_Class_2090", 14590, 807, {"@text": "483e48333b0f9151220da17e4730786616943135a0c94e3da1fc38b32f09604d"},
           "⟦{\"@template\": \"cc847dc4aa547978b9c6364746a13d8247e741dd85e623eea14dcb6ebadcbf21\", \"args\": [10], \"percent\": \"％\"}⟧",
           "evility Stone Statue (807): exact rule - D4 '⟦{\"@template\": \"cc847dc4aa547978b9c6364746a13d8247e741dd85e623eea14dcb6ebadcbf21\", \"args\": [10], \"percent\": \"%\", \"trim\": 1}⟧': FUN_1400F3C20 (the per-unit round-edge routine, called by FUN_1402EB670) adds 1 to the holder's counter (unit +0x22DE, a byte, at most 10) when the unit's move cost (battle record +0x4E8, set by FUN_1400F1200 only from the move commit and cleared on undo) is 0 and sets it to 0 otherwise, then recalculates the unit; FUN_1401B4010 adds value 10 x the counter to the DEF percent (at most 100); nothing else (acting, being hit, being lifted or thrown) is tested. Row 27807 is DEF +10% x D5's idle-turn counter (stat record byte SR+1, 0..10; kit scale idle_turns, read when the stats are recalculated) and wrap_endturn (tag 0xE70021) redirects the three calls of turn_t3_per_unit_end_turn 0x140159F50 (turn_t1_per_unit_hp_sp for team 0, sequencer_ctl_s1_update, FUN_1405FAF90): for a unit that has learned 27807 it reads the counter and the move cost +0x61C before the call and stores D4's value afterwards (+1 up to 10 when the cost is 0, else 0), discarding D5's extra clears (stat record byte SR+2 = lifted/thrown count, +0x11E1 = hit by a skill that sets it, +0x11F5 in one mode); a unit without 27807 keeps D5's own rule. The only other writer of the byte found by decomp text search is the FUN_14015FD40 clear (its flag argument; T3 passes 0), D4's three unit-init clears have no scanned D5 counterpart (whole-record wipes were not scanned). Not carried: D5's move cost is added to by each confirmed move and restored on undo where D4 sets it to the last move's cost (the same with one move per turn); D5 recalculates the unit after T3 in turn_t1_per_unit_hp_sp (team 0), not shown for the other two sites; D4 sums the term into one DEF percent with its other terms and clamps it, the kit adds it to its own aggregate; live not checked. Innate on all six ranks", value1=10,
           behavior={"family": "stats", "effects": [{"stat": "def", "value": 10, "per": "idle_turns"}]})
    # ---- D4SIG3 (2026-11-12): 304 Medical Insertion (Chief innate).  D4 FUN_1400FF700 (cases 0xB..0x10, skill flag 5) scales the
    # status value by (read(0x130) + 100) / 100 with signed integer truncation, then caps it at 100; the stored value is +50.
    # Kit family support_magic_percent (wrap_support, both callers of FUN_1401FEFA0) does the same for support magic (magic
    # row +0x3F6 == 5) and replaces D5's own x2 of Medical Insertion 1180, which the row's alias to 1180 still gives
    # everything else.  The row id (8304) and the alias are unchanged.
    e = m["D4_Unique_5301"]
    e["skill_rows"][0].update({f"desc_{l}": "Increase the effect of support magic by 50％." for l in LOC}, value1=50)
    e["behaviors"] = {"8304": {"family": "support_magic_percent", "effects": [{"value": 50}]}}
    e["adaptations"] = [
        "evility Medical Insertion (304): exact text and number - D4 stores +50% for 304 and FUN_1400FF700 scales the "
        "buff value of a support-flagged skill by (50 + 100) / 100, signed truncation; row 8304 keeps its alias to D5 Medical "
        "Insertion (1180) and carries kit row support_magic_percent 50 (D4SIG3: wrap_support at both callers of "
        "FUN_1401FEFA0), which replaces the game's x2 with x1.5 for support magic (magic row category 5). Not carried: D4 "
        "caps the result at 100 (D5's own stage not measured). Innate, owned by this pack"]
    # ---- D4SIG4 (2026-11-13): 840 Friends and 881 Unlosing Mode are terms 0x348 and 0x371 of the same FUN_1401BA0A0 sum that
    # gave Marona/Ash six stats (0x348: value x local_288 inside the first accumulator, which flows into the returned iVar13;
    # 0x371: added when FUN_1400ED540(holder) != 0).  One returned percent -> FUN_1401B4010 -> ATK DEF INT RES HIT SPD only.
    six = ("atk", "def", "int", "res", "hit", "spd")
    cls = m["D4_Class_1220"]
    cls["behaviors"]["8840"]["effects"] = [{"stat": s_, "value": 5, "per": "map_squad"} for s_ in six]
    cls["adaptations"] = [a.replace("row 8840 is +5% all stats x deployed allies",
                                    "row 8840 is +5% ATK/DEF/INT/RES/HIT/SPD (not HP/SP, D4SIG4 trace) x deployed allies")
                          for a in cls["adaptations"]]
    red = m["D4_Unique_320"]
    red["adaptations"] = [a.replace("row 8840 is +5% all stats x deployed allies",
                                    "row 8840 is +5% ATK/DEF/INT/RES/HIT/SPD (not HP/SP, D4SIG4 trace) x deployed allies")
                          for a in red["adaptations"]]
    e = m["D4_Unique_460"]
    e["behaviors"][str(LATE + 881)]["effects"] = [{"stat": s_, "value": 50} for s_ in six]
    e["adaptations"] = [a.replace("row 27881 is stats +50% while", "row 27881 is +50% ATK/DEF/INT/RES/HIT/SPD (not HP/SP, D4SIG4 trace) while")
                        for a in e["adaptations"]]
    for p_, k_ in (("D4_Class_1220", "Friends"), ("D4_Unique_320", "Friends"), ("D4_Unique_460", "Unlosing")):
        assert any("D4SIG4" in a for a in m[p_]["adaptations"] if k_ in a), (p_, k_)
    # ---- D4SIG4 (2026-11-13): 892 Everyone's Mechanic (Nagi).  D4 FUN_1401B4010 (lines ~1150-1220): for every OTHER unit of the
    # holder's team (not the unit itself, team byte +0x1161 equal, active, not a Geo-Symbol class) it sums read(0x37C) into one
    # number, capped at 100, and that number multiplies the ITEM STAT of the equipment slots the loop treats as weapons (slot 0,
    # slot 1 only when unit +0x20D8 is not -1): item stat x (100 + sum) / 100, before the aptitude weight.  D5 unit_recalc calls
    # unit_stats_equip_stat once per stat; the kit family weapon_percent (wrap_equip) scales the result of a weapon-category slot
    # (category byte 1..9, the game's own weapon test) by (100 + sum) / 100 and takes the aura rows' sum, capped at 100.
    e = m["D4_Unique_490"]
    for r in e["skill_rows"]:
        if r["id"] == LATE + 892:
            r.update({f"desc_{l}": "⟦{\"@template\": \"67a88e7a7a3b3de588518a33db86752f9c17e953eeef294c18f02701b4a96ace\", \"args\": [10], \"percent\": \"％\"}⟧" for l in LOC})
    e["behaviors"][str(LATE + 892)] = {
        "family": ["weapon_percent", "aura"], "effects": [{"value": 10}],
        "conditions": [{"kind": "near_has", "of": 1, "radius": 65535, "id": LATE + 892}]}
    e["adaptations"] = [a for a in e["adaptations"] if not a.startswith("evility Everyone's Mechanic (892)")] + [
        "evility Everyone's Mechanic (892): exact text and number - D4 '⟦{\"@template\": \"67a88e7a7a3b3de588518a33db86752f9c17e953eeef294c18f02701b4a96ace\", \"args\": [10], \"percent\": \"%\", \"trim\": 1}⟧' (FUN_1401B4010: the value of every other unit on the holder's team summed, the sum capped at 100, multiplying the item stat of a weapon slot by (100 + sum) / 100); row 27892 (late band) is kit family weapon_percent + aura (near_has ally, radius 65535 = anywhere), applied by wrap_equip to the result of the game's own unit_stats_equip_stat for a weapon-category slot (category 1..9), signed truncation, sum capped at 100; armour and accessories are not raised, Nagi himself is not, (D4SIG4; replaces the potency row that also raised armour). Not carried: D4 adds the value of every ally holder and the kit evaluates an aura row once, however many providers (Nagi is unique, so one holder is the normal case); the result is scaled after D5's own stages of that function. With no other weapon-percent source it equals adding the percent inside the function (proved against the real function); with D5's own weapon-percent evility 6035 (+30) the two multiply (715 for item 1000 at potency 50) where D4 adds its own term 0x355 into the same sum (700); D5's later x1.5 stage is also applied before ours. D4's ally test (alive, state flags) is the kit's near_has. When D5 recomputes stats after an ally holder arrives or dies is not measured. Innate, owned by this pack"]
    # ---- D4SIG5 (2026-11-13): 351 Misty Haze (Reprachon) and 844 Beryl's Servant 1 (Kyoko), evasion.  D4 decides a hit in
    # FUN_1400FF700: rate = HIT x 100 / SPD plus flat terms (the defender's 844 value is subtracted there, only for class 350, only
    # while an adjacent same-team unit holds evility 1 = Raspberyl's Love Thy Heart), then capped at 100 and multiplied by the float
    # FUN_140107100 returns, the product of (100 - v) / 100 over the defender's evasion evilities (351 when the attack comes from the
    # front = per-target direction 0, 620 from the side, 352/353 by range ...).  D5 has the same input: damage_hit_chance_rules
    # 0x1401F5410 clamps the percent to 1..100 first and its own evasion evilities (Skill rows 0x3C, 0x4C, 0x46A ...) multiply the
    # same accumulator by (100 - v) / 100 afterwards.  The kit family `evasion` (wrap_hit) does both steps for the defender's rows.
    e = m["D4_Unique_5310"]
    e["behaviors"]["8351"] = {"family": "evasion", "effects": [{"value": 50}],
                              "conditions": [{"kind": "attack_dir", "id": 0}]}
    e["adaptations"] = [a for a in e["adaptations"] if not a.startswith("evility Misty Haze (351)")] + [
        "evility Misty Haze (351): exact rule - D4 'evade attacks from front' (FUN_140107100: the hit rate is multiplied by "
        "(100 - 50) / 100 when the attack's per-target direction is 0, front); row 8351 owned by this pack is kit family evasion "
        "(scale, 50) + attack_dir front, applied by wrap_hit to the percent damage_hit_chance_rules returns (D5's hit chance, kept in "
        "1..100); innate. Not carried: D4 rolls a hit in two stages (a failed first roll gets a second roll that decides miss or a "
        "weakened hit) where D5 rolls once, so the same chance gives D5's own miss rate; D4 can reach 0% where D5 keeps 1%; a second "
        "evasion row on one unit adds the values where D4 multiplies the factors. The D4 class pack is out of importer scope"]
    e = m["D4_Unique_350"]
    for r in e["skill_rows"]:
        if r["id"] == LATE + 844:
            r.update({f"desc_{l}": "When next to Raspberyl, evasion is increased by 50％." for l in LOC})
    e["behaviors"][str(LATE + 844)] = {"family": "evasion", "effects": [{"value": 50, "mode": "points"}],
                                       "conditions": [{"kind": "near_char", "of": 1, "radius": 1, "id": 650}]}
    e["adaptations"] = [a for a in e["adaptations"] if not a.startswith("evility Beryl's Servant 1 (844)")] + [
        "evility Beryl's Servant 1 (844): exact rule - D4 'evasion is increased by 50% next to Raspberyl' (FUN_1400FF700: 50 is "
        "subtracted from the hit rate before the cap at 100, only for the class-350 holder while an adjacent same-team unit holds "
        "Raspberyl's evility); row 27844 (late band 27000 + D4 id, so no installed learnable row changes position) is kit family "
        "evasion (points, 50) + near_char ally radius 1 of D5's Raspberyl (character 650), applied by wrap_hit before the game's own "
        "clamp of damage_hit_chance_rules to 1..100; innate, owned by this pack. Not carried: D4 rolls a hit in two stages where D5 "
        "rolls once, D4 can reach 0% where D5 keeps 1%, and the neighbour test is the kit's radius-1 test on D5's Raspberyl, not "
        "D4's own adjacency function"]
    # ---- MASKWIDE1 (2026-11-13): 836 Vanishing Cat (Death Saber innate), the first row in the widened family mask (flags bits 8..31).
    # D4 FUN_1402DD8B0 (evility 0x344) after the action's script has ended: each target with killed flag 0 that is within footprint
    # distance 1 of the attacker (FUN_1400ED660) is turned to FUN_14022F350(target, attacker) with FUN_1400F1230 + FUN_1400F3EE0.
    # D5: wrap_face_away at the one call of post_hit_effects in exec_ctl_s2_update (0x14053FE71), same order of events, with
    # ai_transition_within_range (= FUN_1400ED660), FUN_14022F350 inline in integers (D4SIG9: exact, D5's atan2 function differs) and
    # unit_set_facing (= FUN_1400F1230).
    innate("D4_Class_2200", 14700, 836, {"@text": "f13c410d484a100533a5f125e7f63a742541a3d328514ef4e67a09dcc2bd0999"}, {"@text": "a324956e326a0b745279e7b9b215c80985363f9fe900b1cc5546e1d86dd20364"},
           "evility Vanishing Cat (836): exact rule - D4 FUN_1402DD8B0 (run after every action by FUN_1402E3E20, counter-attacks "
           "included) turns each target whose killed flag (action +0x3E98+i) is 0 and that is within footprint distance 1 of the actor "
           "(FUN_1400ED660) to face directly away: FUN_14022F350(target, actor) = -90 or 90 when |dz| < |dx| (by the sign of dx), else "
           "0 when dz > 0, else 180 (so a zero distance, the actor as its own target, and every exact 45 degree tie give D4's answer), "
           "then FUN_1400F1230 / FUN_1400F3EE0 write the facing; the actor and allies are not excluded. Row 27836 (late band) is the "
           "kit's second-word family face_target_away: wrap_face_away runs before post_hit_effects (0x140542CB0, the once-per-action pass "
           "of exec_ctl_s2_update 0x14053F880, after the ctx-bound script ended and every target's vertical speed is 0) and for every "
           "target entry whose KO byte (ctx +0x152E + j x 0x260) is 0 and for which ai_transition_within_range (0x140153FF0, D4 "
           "FUN_1400ED660's counterpart) holds, calls unit_set_facing (0x14014F640) with D4's FUN_14022F350 computed inline in integers "
           "(not D5's atan2 function) of the (int)(float) world positions. Not carried (engine differences, not rule differences): D5's "
           "KO byte is set in damage_apply_damage when the hit kills (or the target is already at 0 HP) behind the same script flag 0xFFF "
           "as D4's FUN_140191170 byte, matched by structure and not branch by branch; D4's FUN_1400ED660 reads a saved cell (+0x74A, "
           "flag +0x744) in some states where D5's function reads the record's world position; D5 stores 180 as -180; the wrapper also "
           "skips an inactive record. Facing only checked offline (whether D5's later states or idle pose overwrite it, and the visual "
           "result, need the game). Innate on all six ranks",
           behavior={"family": "face_target_away"})
    # ---- D4SIG7 (2026-11-13): 129 Geo Energy (Psylos innate), "Stats increased by 10% per Geo Block color on map."  D4 FUN_1401BA0A0
    # (the stat percent sum shared with Friends 840, Marona 875, Ash 878 ...; one returned percent -> FUN_1401B4010 -> ATK DEF INT
    # RES HIT SPD): the term for evility 129 adds count x value, or 100 when that product is 100 or more, where count is the
    # number of DISTINCT raw colour values (record +0x25A) over the active, living units of family 0x1E1 (Geo Blocks).  The kit
    # scale geo_colours (27, D4SIG7) counts the same set over D5's Geo Symbol family (chars 4810..4819, colour byte unit +0x2E2C).
    m["D4_Unique_5388"] = dict(
        skill_rows=[row(LATE + 129, {"@text": "d326ddce659b712bb3e53eb2245a1aef1fe78eea42576f7c06ff8666a771a045"}, {"@authored": "Stats increased by 10％ per Geo Symbol color on map."}, 18290, False, 0, 0, value1=10)],
        late_ids={"129": LATE + 129},
        char_links={"18290": {"evility1": LATE + 129, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}},
        behaviors={str(LATE + 129): {"family": "stats", "effects": [{"stat": s_, "value": 10, "per": "geo_colours"} for s_ in six]}},
        adaptations=[
            "evility Geo Energy (129): exact rule - D4 '⟦{\"@template\": \"02d6713132c1e664287a9bffd27686c0626c15b660e9012a3a3bda9e3d79f4cc\", \"args\": [10], \"percent\": \"%\", \"trim\": 1}⟧' (FUN_1401BA0A0: over every active, living unit of family 0x1E1 it collects the raw colour value of the record, +0x25A, into a set and the term adds 10 x the number of distinct values, 100 at most; the returned percent reaches ATK/DEF/INT/RES/HIT/SPD only, FUN_1401B4010); row 27129 (late band) is kit family stats +10% on those six stats x the new scale geo_colours: the number of distinct colour bytes (unit +0x2E2C, D5's own Geo Symbol colour: placement +0x248, written by 0x1404D29C0 / 0x1405247D0 at deployment and by script_cmd_unit_geo_change; the game's maps use 0..6, 0 = clear) over the alive units on the map whose character id is 4810..4819 (D5's own Geo Symbol name switch, 0x1402ACBB0, tests the same id / 10 == 481). Like D4 a clear symbol (0) counts as a colour and a holder off the map or carried counts 0. Not carried: D4 adds the term into one percent shared with its other stat evilities and clamps that sum to -50..100 (the kit adds each row to D5's aggregate separately; Psylos holds no other, and 7 colours is at most +70); D4's class-kind exclusion of the holder (record +0x1808 in 0x33..0x34) was not mapped; that D4's family 0x1E1 is the Geo Block unit rests on EVILFX1's reading, the D4 character ids were not opened; when D5 recomputes the aggregate after a Geo Symbol dies or changes colour is not measured. Innate, owned by this pack"])
    # ---- D4SIG7 (2026-11-13): 663 Rising Dragon becomes an exact rule.  The alias to D5 Impact Charge (2065) stays: it does the READING (D5's
    # damage_attack_bonus_rules adds row value 10 x the short at stat record +0x5D8, at most +200 = D4's 20 x 10, the counterpart of D4 FUN_140106900's
    # term counter(+0x20D5) x value).  The kit row below makes the COUNTING D4's: wrap_atkcount at the per-target damage_apply_damage call and the
    # reset in wrap_face_away's once-per-action pass.  The class pack keeps its alias map; only the behavior row and the label are new.
    e = m["D4_Class_2170"]
    for r in e["skill_rows"]:
        if r["id"] == LATE + 663:
            r.update({f"desc_{l}": "Increase ATK by 10％ every time an attack is received (resets when this unit acts)." for l in LOC})
    e["behaviors"] = {str(LATE + 663): {"family": "attack_counter"}}
    e["adaptations"] = [
        "evility Rising Dragon (663): exact rule - D4 '⟦{\"@template\": \"0722264ffa6b8b238ff6e007b71ac0cfb49fda93ef152776544e7494e71eea4f\", \"args\": [10], \"percent\": \"%\", \"trim\": 1}⟧': FUN_140106900 adds value 10 x the unit's counter (+0x20D5, signed char) to the attack-power percent; FUN_140123940 (action event 0x1E, once per target) adds 1 to each target's counter (at most 20) whenever the target's result slot is not negative, so every hit, nullified hit, miss and buff counts and a heal (slot = -amount) does not; FUN_1402DD8B0 (end of every action) sets the ACTOR's counter to 0. Row 27663 (late band) keeps the alias to D5 Impact Charge (2065), which reads the counter (damage_attack_bonus_rules: 10 x the short at stat record +0x5D8, at most +200) and adds the kit row attack_counter (second-word family): wrap_atkcount at the call of damage_apply_damage in FUN_1401B1BA0 (once per action target) stores min(counter before the call + 1 for a non-heal target, 20) and discards D5's own count (non-elemental attacks only), and the once-per-action pass of exec_ctl_s2_update (wrap_face_away) zeroes the actor's counter; D5 has no other writer of that short (exe scan: the apply_damage increment, two wipes, a record copy; readers: the bonus rules and the damage breakdown display). Not carried: D5 counts a heal as a positive slot, so the heal test is the skill row's category 4 (D4: slot <= 0), and a heal of 0 on a target D4 cannot heal counts in D4 only; D4's multi-target branch skips a carried target; D5 skips a target already at 0 HP before its own count while the wrapper counts it; D5's damage is added by its own bonus rules, not D4's function. Live not checked. Innate on all six ranks"]
    # ---- D4SIG10 (2026-11-14): 864 Base Hospital (Medic innate), "Allies in the base panel recover 5% HP and SP every turn."  D4 FUN_1402EB670
    # (per unit of the round-end pass, state 0x66 of the battle machine FUN_1402EE580: entered only when no side has a pending phase, once per round)
    # walks the party roster for every unit with 864; D5's wrap_regen (T1 at the round-end sweep) runs evil_hospital for the same unit.
    innate("D4_Class_1240", 14240, 864, {"@text": "cd82e84e6cf80464940a47717d7509368428a7b92c02a372da85cc1816b7cdd9"},
           "Allies in the base panel recover 5％ HP and SP every turn.",
           "evility Base Hospital (864): exact rule with the differences below - D4 'Allies in the base panel recover 5% HP and SP every turn': "
           "FUN_1402EB670, in the per-unit pass of the battle machine's round-end state (FUN_1402EE580 state 100 -> 0x66, reached only when no side has "
           "a pending phase, so once per round, units visited in table order), for each unit that has learned 864 walks the party roster "
           "(FUN_1400FC2D0, DAT_140D54FE6 records) and for every record whose byte +0x20D3 is 0, that is not dead (HP +0xD10 > 0) and has no "
           "battle unit (FUN_140244320) adds maxHP x 5 / 100 to HP and maxSP x 5 / 100 to SP (signed truncation, no minimum of 1), each clamped at "
           "its maximum, one provider after another (no team test on the recipient). +0x20D3 is set to 1 only by code that moves a record into another "
           "unit's member list (FUN_1400EFC30, FUN_1400F23D0, FUN_1400EFDA0, FUN_140280420: a partner record of a Magichange or a giant-fusion "
           "member, read from the member-list fields they touch, not from names) and cleared when that unit separates alive (FUN_140306FD0, "
           "FUN_1403BFB50). D5: wrap_regen (the existing wrapper of turn_t1_per_unit_hp_sp's two calls, tag 0xE7000C) calls evil_hospital after "
           "the game's own T1 for a unit that has learned 27864 and whose team byte (+0x2E32 & 0xFB) is 0, which the round-end sweep of "
           "sequencer_ctl_s1_update (Sorrow: the round-end processor, once per round, every player-side unit) reaches: the same cadence. Recipients: a "
           "roster record (0x145207DB8, stride 0x4750, count the short at 0x145574A9C) that is present, team 0, alive (HP +0x2CC8 > 0), not a "
           "Magichange weapon (stat record byte +0x4E2, which EVILCAP1 found set while a monster is a weapon and cleared by FUN_14015F030: read as "
           "D5's counterpart of +0x20D3, not proven identical) and is the record of no active battle unit, +5% of its max HP and SP (HP "
           "+0x2CC8/+0x2CD8, SP +0x2CD0/+0x2CE0), clamped, once per provider. Not carried: D4 has no team test on a provider (its enemy Medics would "
           "also heal the party; D5's other side runs T1 at TurnCtl init, not at the round end, so only player-side holders act); the D5 table also "
           "holds the other sides so recipients are limited to team 0 (D4's roster is the army only); D5 has no giant fusion; D5's own facility "
           "heal of the same roster pass still applies on top; the value 5 is the row's number written into the code; a provider at 0 HP never "
           "reaches T1 in D5 (its loop skips dead units), D4's pass was not traced for dead providers; live not checked. Innate on all six ranks", value1=5)
    # ---- D4SIG10b (2026-11-14): 115 Miasma of Silence (Roc innate).  D4's "status 10" of FUN_1400E9D40 is not an ailment but the per-cell count of GEO
    # EFFECT index 10 under the unit (table DAT_1416A5EF0 [cell][effect], filled from the Geo Symbols' effect ids): GE.dat row 11 "Silence - No
    # Special Skills can be used by characters on".  D5 has the same geo effect (its GE.dat row 10 text "No Specials can be used by units on", column 10
    # of the ground table) and reads it in exactly one place, unit_effect_table_sum(unit, 10) in cmdmenu_preds_p_156820 (the base of the Skill command).
    innate("D4_Class_2110", 14610, 115, {"@text": "7b72ed4913552c94483fb8b7fca3830fe7f3d22d02771c483ca1723cf84d916e"},
           {"@text": "8979ff5c6ba5b1ca3e49c445104a55a5516751d304c6d8ec35715135a595b46b"},
           "evility Miasma of Silence (115): adapted - D4 'Prohibits special skill use by adjacent enemy units': FUN_140105640(unit, 0x73) sums the "
           "evility over every unit that is active, alive (HP > 0), of a hostile team (FUN_14022D830), not an object kind / class 0x12CA / Geo class "
           "and within distance 1 by FUN_1400ED660 (footprints); a non-zero sum withdraws the special-skill flag in the two menu builders "
           "(FUN_14030B440, FUN_14030D920, which also test the Silence geo effect, index 10 of the geo table = GE.dat 'Silence: No Special Skills can "
           "be used by characters on', through FUN_1400EDD70) and makes the AI sites (FUN_1402F5020 twice, FUN_1402F06B0, FUN_140231370, "
           "FUN_1402302B0) treat the unit as on that Silence panel (special-skill chance 0). D5 has the same geo effect (GE.dat 'Silence: No Specials "
           "can be used by units on') and reads it once, in cmdmenu_preds_p_156820 (the base of Skill, column 10 of unit_effect_table_sum), "
           "which only the player menu uses. Kit row special_seal (second-word family): wrap_roc_geo at that one call makes the Skill command "
           "unavailable for a unit with an adjacent Roc holder (same gate as the game's own Silence panel) and wrap_roc_skill at the four calls of "
           "cmdmenu_env_stat_row_can_use_skill (player menu x2, AI list_skills, executor FUN_140547750; exe call scan: no others) answers 'cannot' "
           "for a skill whose magic.dat class byte +0x3F2 is 0 (unique), 1 (weapon skill) or 2 (spell). Holder test as D4: adjacent by the game's own "
           "ai_transition_within_range (D4 FUN_1400ED660's footprint test, distance 1), hostile (the game's team table), alive, not an object / Geo "
           "class (events_env_is_object_rec). Adapted because D5's own Silence panel never reaches the AI or the executor, so "
           "the AI/executor part and its class set {0, 1, 2} (what the Skill command lists; items 3, Overload 4 and basic actions 5 stay usable) are "
           "this lane's reading of D4's AI consumers; the menu gate is the game's own. Not carried: D4 byte +0x115E (a boss/rank byte "
           "that exempts some enemy units from the AI chance consumers; no D5 counterpart), evility 0x298 Fetters ('Seal special skill', the holder's "
           "own seal, a separate rule) and 0x280 Geo Break (read by the chance consumer), of which no unit in this install holds either (not in any "
           "imported pack); D5's ailments Amnesia / Weaken (statuses 3 and 4) are untouched. Live not checked. Innate on all six ranks", value1=100,
           behavior={"family": "special_seal"})
    # ---- LONGTAIL3 (2026-11-14): 802 Self-Destruct (Battle Suit innate), "Self-destruct when HP hits below 10% by an attack."
    # D4 (decomp): FUN_14010DE70(unit, 0x322, unit+0xD20 = max HP) returns the evility's value unless the percent of max HP is below the unit's
    # HP, i.e. nonzero when HP <= trunc(max HP x percent / 100); the seven call sites (FUN_1402EE580's after-action sweep, state 0x66, and six
    # after-damage sites) then play effect 0x816 and apply the unit's OWN HP to itself as lethal damage (FUN_140190F90).  No damage to other
    # units was found in those sites.  D5: kit family self_destruct (second-word bit 11, percent 10) in wrap_face_away -> FUN_1401A3E80.
    innate("D4_Class_1190", 14190, 802, {"@text": "e17222079367c3b423f9981174a8b57aca0cd813d46d496dae7f2f185f02215b"}, "Explodes when hit down to 10％ HP or less, hurting nearby units.",
           "evility Self-Destruct (802): adapted - D4 text '⟦{\"@template\": \"aa0cfbbfeca43678e2d98271473da1de85b729506a1bcac751165c4482dd3692\", \"args\": [], \"percent\": \"%\", \"trim\": 1}⟧'. CODE (D4 decomp): the test is FUN_14010DE70(unit, 0x322, unit+0xD20): it returns nonzero when the unit's HP (+0xD10) is at most trunc(max HP x percent / 100) (so at or below the 10 percent threshold, not strictly below; the percent is the evility's own byte, 10 per the game text, not read from D4 data), and each of the seven sites (the after-action sweep in FUN_1402EE580 state 0x66 plus six after-damage sites in FUN_1402EA950, FUN_140300BB0, FUN_1402CBCB0, FUN_1402CFAC0, FUN_1402CA7C0, FUN_1402CDBD0) then plays effect 0x816 and applies the unit's own current HP to itself as lethal damage (FUN_140190F90); no damage to OTHER units appears in those sites. COMMUNITY (Disgaea wiki, page Battle Suit; evidence class community, not code): the blast hits a circle of radius 2 for 50% of the holder's current HP. D5 build: kit row self_destruct (second-word family, percent 10), read in wrap_face_away (the once-per-action pass of exec_ctl_s2_update, before post_hit_effects): for each action target that took a real hit (positive result, not a heal), is still alive, is not already exploding (+0x11DC 0) and has HP <= trunc(max HP x 10 / 100), the game's own explosion routine FUN_1401A3E80(unit, 1) runs (D5's thrown-explosive blast: 50% of current HP, area 10 and 2 from FUN_1402038C0, then the unit's HP applied to itself so it dies), so the blast amount and radius are D5's defaults, which equal the community numbers. Not carried: D4's six other sites (damage that is not an action hit: poison, Geo, fall, reflect), D4's after-action sweep of a holder that was already low (only a unit hit in this action explodes), D4's effect 0x816 (D5 plays its own explosion), the blast's exact victims (D5's field sweep decides) and the 50 percent of CURRENT HP, tiny at 10 percent HP. Blast and kill not run offline. Innate on all six ranks",
           value1=10, behavior={"family": "self_destruct", "effects": [{"value": 10}]})
    # ---- NECRO1 (2026-11-14): 868 Necromancy (Necromancer innate), "Bring back defeated enemies as zombies and use them."
    innate("D4_Class_1250", 14250, 868, {"@text": "28851d791ef22abfbef72cfbe7c34905d05d60c5f8ba6d0aa1ce7738caf59915"}, "Enemies you defeat come back as 1 HP Zombies that fight for you by themselves.",
           "evility Necromancy (868): adapted - D4 text 'Bring back defeated enemies as zombies and use them'. CODE (D4 decomp): FUN_1401946B0 "
           "(per defeat) tests 868 on the attacker, a victim of an opposite ordinary team (neither team 2 nor 3, not carried or stacked, no pending "
           "conversion, cell free, class != 0x151D) and calls FUN_1400F2680, a 17-byte setter that only marks the victim (unit+0x7B4 = 1, owner "
           "+0x7B8); the battle's retire block FUN_140302530 then builds a class 0x820 unit from the victim's data on the victim's cell "
           "(FUN_1401B9350: statuses and the four equipment slots cleared, side byte 3 for a player holder, 1 for an enemy holder), no unit slot "
           "free means no zombie. COMMUNITY (Disgaea wiki, page Necromancer; evidence class community, not code): the zombies are helpful "
           "units that cannot be controlled, with 1 HP and no equipment. Lifetime, EXP and the exact HP source were not found in D4 code. D5 "
           "build: kit row raise_zombie (second-word family bit 12). Right after the game applies the holder's damage to a target (damage_apply_damage, "
           "while the victim's record is still whole, because the game retires a defeated unit before the action's script ends) the target the holder "
           "defeated (KO byte set, HP 0) that is hostile (not team 3), not an object, not already an Undead and not carried or carrying is noted "
           "(cell, facing, level, team); at the end of the action (exec_ctl_s2_update's once-per-action pass) each noted victim whose cell holds no "
           "living unit, while fewer than 32 units live, gets one zombie, so it appears when the action ends: "
           "unit_spawn_from_request builds D5 Undead (char 2090, title Zombie) of the victim's level at the victim's position and facing on the "
           "holder's side (team 0 -> 4, the game's own AI-run friendly team; enemy holders -> 1), then its HP is set to 1 (community number). "
           "Not carried: kills by counter, chain damage, poison, Geo or fall; the victim's own data and name (a fresh Undead of its level); "
           "D4's class and +0x2138 exclusions; any lifetime (rest of the battle); EXP / bonus effects; that the zombie acts as D4's team-3 unit. "
           "Spawn, side and AI behaviour not run offline (live recipe in NECRO1-REPORT). Innate on all six ranks",
           value1=0, behavior={"family": "raise_zombie"})
    # ---- NEMO1 (2026-11-14): 820 Physical Malice (Nemo innate), "Summon a Malice unit to the map on every turn."  Appended; earlier blocks unchanged.
    e = m["D4_Unique_220"]
    e["skill_rows"] = e["skill_rows"] + [row(LATE + 820, {"@text": "64d8d95a3a5b9a8609a5255943fd32cdeda3acf90a2b763e881f46f4221d5d61"}, {"@authored": "At the start of every turn, a Malice unit appears near this unit."}, 18110, False, 0, 0)]
    e["late_ids"] = {"820": LATE + 820}
    e["behaviors"] = {str(LATE + 820): {"family": "summon_malice"}}
    e["char_links"] = {"18110": {"evility1": LATE + 820, "evility2": 0, "evility3": 0, "evility4": 0, "evility_count": 1}}
    e["adaptations"] = e["adaptations"] + [
        "evility Physical Malice (820): adapted - D4 text 'Summon a Malice unit to the map on every turn'. CODE (D4 decomp): FUN_1402E99D0, state 3 of "
        "the round-edge state machine FUN_1402EA550 (once per round, after every side has acted, not per side), finds the first unit holding 820 "
        "and, while fewer than 32 units are active, draws a class char 5330 + rand(39) (the 39 'Malice <class>' rows, tier 9; a table of up to 15 classes of "
        "flagged units already on the map switches the draw to those once it is full - read, not traced), the level L*60/100 + rand(40)*L/100 (L = the holder's level, at "
        "least 1) and has FUN_1402AD4C0 create it with side byte 1 on a random free walkable cell inside the square of radius 10 cells around the "
        "holder (-1 and nothing when no cell is free); FUN_1402E99D0 then sets the new unit's values. COMMUNITY (Disgaea wiki, page Nemo; evidence "
        "class community, not code): one Malice unit every turn. D5 build: kit row summon_malice (second-word family bit 13) read in wrap_revenge "
        "(the one call site of the round-edge sweep, once per active unit per round, turn_ctl_s6_update): a living holder, while fewer than 32 "
        "units live, rebuilds the game's free-cell grid (events_clear_pick_cell, as Summon Guardian does), counts the free cells inside the same "
        "radius-10 square, and has unit_spawn_from_request build one D5 class drawn with game_rng_draw from 25 stand-ins (D5 class rows 1010 "
        "Warrior, 1020 Valkyrie, 1030 Magician, 1040 Witch, 1080 Cleric, 1090 Thief, 1110 Archer, 1120 Gunner, 1130 Ninja, 1140 Lady Samurai, "
        "1150 Armor Knight, 1160 Magic Knight, 1180 Professor, 1260 Sorcerer, 2010 Prinny, 2030 Orc, 2060 Sludge, 2070 Slumber Cat, 2080 "
        "Mothman, 2090 Undead, 2100 Shroom, 2110 Flora Beast, 2120 Felynn, 2140 Succubus, 2180 Dragon King) at D4's level formula on a free "
        "cell drawn with game_rng_draw, on the holder's side (team 0 -> 4, the game's AI-run friendly team; enemy holders -> 1; teams 2 and 3 "
        "do nothing). OUR CHOICES: the side (D4 always uses side byte 1, even for a player-side holder), the 25 stand-ins (the other 14 Malice "
        "classes - Beast Master, Bouncer, Masked Hero, Onmyo Monk, Battle Suit, Android, Spirit, Marionette, Roc, Death, Mystic Beast, Dragon "
        "Zombie, Wood Golem, Rifle Demon - have no D5 class and are left out), the grid and free-cell rule (the game's own, not D4's walkable "
        "test), no once-per-round guard beyond the sweep itself. Not carried: the Malice look and names (an ordinary D5 class of the draw), D4's "
        "15-class table, the stat values FUN_1402E99D0 sets after creation, Flooding Malice (Nemo's second evility), any "
        "lifetime, EXP or bonus effects. Spawn, side and AI behaviour not run offline (live recipe in NEMO1-REPORT). Innate"]
    return {"schema": "d4-evility-additions/1", "lane": "EVILGAP1-20261110",
            "source": "tools/evilgap1_rows.py; merged into d4-evility-overlay.json by tools/build_d4_evility_overlay.py",
            "mods": refs(m)}


if __name__ == "__main__":
    doc = build()
    for n, st in doc["mods"].items():
        for r in st.get("skill_rows", []):
            assert 8187 < r["id"] < 9000 or st.get("late_ids", {}).get(str(r["id"] - LATE)) == r["id"], r["id"]
    (ROOT / "d5lib/importers/d4-evility-additions.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote", sum(len(s.get("skill_rows", [])) for s in doc["mods"].values()), "rows,", len(doc["mods"]), "packs")
