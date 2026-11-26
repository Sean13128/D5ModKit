"""Build d5lib/importers/d1c-donor-evilities.json (D1CEVIL1, owner decision 2026-11-10).

Disgaea 1 Complete has no evilities, so every imported D1C class/character gets a DONOR evility: a vanilla
Disgaea 5 evility id, labelled donor (not source).  Ladder: 1 same character in D5, 2 same class in D5,
3 closest D5 class/character by role (reason recorded, `confidence` low = for Sean to review).
This script holds the decisions; it reads the evility ids/names/text and the donor character rows from the
pristine D5 tables and refuses a pick whose donor row does not actually carry that evility.

    D5_KIT=<kit> python tools/build_d1c_donor_evilities.py <pristine-tables.json>
(pristine-tables.json: see _dump() - written once from GameFS over the installer's originals.)
"""
import json, sys
from pathlib import Path

# mod_folder: (D5 donor char id, evility id, rung, confidence, reason)
PICKS = {
 # --- classes (13) ---
 'D1C_Class_11400': (1120, 1120, 3, 'medium', 'EDF Soldier is ranged infantry with a gun; D5 Gunner is the gun class (also the pack\'s animation template).'),
 'D1C_Class_11390': (1110, 1110, 3, 'high', 'Strider/Scout is D1\'s bow line; D5 Archer is the bow class.'),
 'D1C_Class_11830': (2510, 5002, 3, 'medium', "Death is the Disgaea wiki's Reaper (Disgaea 1 Complete) class line (ranks Nightmare, Shade, Lich, Chernobog, Death, Thanatos), which the page says is immune to ailments from Tier 5 (https://disgaea.fandom.com/wiki/Reaper_(Disgaea_1_Complete), Disgaea Wiki community editors; evidence class community, opened in the browser pane by the coordinator 2026-11-19). D5 Extremely Healthy (Level Fish) 'Nullify ailments and stat drops' is the only vanilla D5 evility that fully blocks ailments and a donor character carries it; Love Protection (Flonne, 'Nullify status ailments against unit') is Flonne-only on a donor that does not carry it. D1CEVIL2 2026-11-19 replaces Cursed Dance. The wiki gives Tier 5 onward; D5 evilities have no tier gate here, so all six ranks carry it (donor approximation)."),
 'D1C_Class_11860': (2180, 2180, 3, 'high', 'Dragon / Evil Dragon: D5 Dragon King is the dragon-family class.'),
 'D1C_Class_11900': (2090, 2090, 3, 'medium', 'Dragon Zombie: undead; D5 Undead (zombie) class drains HP on attack.'),
 'D1C_Class_11820': (2080, 2080, 3, 'medium', 'Gargoyle: winged melee monster; D5 Winged Warrior is the closest winged class.'),
 'D1C_Class_11770': (2210, 2210, 3, 'medium', 'Golem: stone/iron bulk; Immortal Body (less physical damage) fits a golem hull.'),
 'D1C_Class_11810': (2110, 2110, 3, 'medium', 'Lantern/Pumpkin: round plant-like support monster; D5 Flora Beast (Sweet Aroma, heals allies).'),
 'D1C_Class_11800': (1150, 1150, 3, 'high', 'Living Armor: hollow armor; D5 Armor Knight (Hero\'s Shield) is the armor class.'),
 'D1C_Class_11850': (1200, 1200, 3, 'medium', 'Rifle Demon: rifle-armed demon; D5 Pirate (Acceleration Shot) is the long-range gun class.'),
 'D1C_Class_11840': (2200, 2200, 3, 'medium', 'Serpent rank titles are Mizuchi, Sea Dragon, Rahab, Leviathan, Midgardsorm (D1C source): a sea-dragon line, so the D5 dragon-family class Twin Dragon (Twin Heads) fits better than Chimera Evil Eye. D1CEVIL2 2026-11-18. No community page on the class was found. Community: Disgaea Wiki https://disgaea.fandom.com/wiki/Serpent_(Disgaea) (browser pane 2026-11-19): aggressive shark-type dragon. KEEP Twin Heads.'),
 'D1C_Class_11760': (2050, 2050, 3, 'medium', 'Spirit/Ghost: small floating caster; D5 Fairy (Magic Creation) is the floating caster class.'),
 'D1C_Class_11930': (2090, 2090, 3, 'medium', 'Nosferatu/Vampire: life drainer; D5 Undead Predation (heal by damage dealt).'),
 # --- uniques ---
 'D1C_Unique_4':    (1150, 1150, 3, 'medium', 'Gordon, Defender: shield protector; Armor Knight Hero\'s Shield (protects allies).'),
 'D1C_Unique_5':    (1110, 1110, 3, 'medium', 'Jennifer, Sidekick: Support Attack (attacks when an ally attacks) reads as a sidekick. D1CEVIL2 2026-11-19 re-check: Medical Insertion (Professor) rejected, her D5 kit teaches no support spell for it to multiply and alternate Jennifer D1C_Unique_5590 copies this donor; Support Attack kept. Community (evidence class community): Disgaea Wiki \'Disgaea 1 Complete characters\' page, browser pane 2026-11-19: Jennifer\'s class is Sidekick and she \'supports Gordon the most\'. KEEP Support Attack.'),
 'D1C_Unique_2200': (2210, 2210, 3, 'medium', 'Thursday, Super Robot: metal hull; Immortal Body (less physical damage). D1CEVIL2 2026-11-19 re-check: StrategyWiki Disgaea HoD Special Classes calls him an All Purpose Robot built by Jennifer (via search summary); no better D5 evility found; kept at low (theme). Community: same wiki page, 2026-11-19: Thursday is the Super Robot that takes hits for Gordon. KEEP Immortal Body.'),
 'D1C_Unique_2216': (10, 10, 3, 'low', 'Kurtis, Rival: dark rival to the hero; Killia\'s War Demon (rival-Overlord-candidate theme).'),
 'D1C_Unique_2540': (2100, 2100, 3, 'low', 'Vyers, Dark Adonis: charmer of women; Shroom Power weakens adjacent female enemies.'),
 'D1C_Unique_2400': (2160, 2160, 3, 'high', 'Hoggmeiser, Rich Demon: Nether Noble Greedy Disposition (stats from money owned).'),
 'D1C_Unique_2550': (50, 50, 3, 'low', 'Maderas, Demon Sire: heavy-hitting demon lord; Red Magnus Super Crush (DEF break).'),
 'D1C_Unique_2580': (1170, 1170, 3, 'medium', 'Lamington, Seraph: angel caster; Celestial Host Angel Song.'),
 'D1C_Unique_2570': (1240, 6025, 3, 'medium', 'Vulcanus, Archangel: guardian angel; Celestial Hostess Angel Protection.'),
 'D1C_Unique_2600': (1150, 1150, 3, 'medium', 'Don Joaquin, 1st Defender: defender title; Armor Knight Hero\'s Shield.'),
 'D1C_Unique_2410': (670, 6078, 3, 'low', 'Sardia, Demonslayer: human demon hunter; Almaz\'s Hero\'s Proof (bonus against Overlords).'),
 'D1C_Unique_3000': (760, 6120, 1, 'high', 'Priere exists in D5 as Overlord Priere (char 760); her own unique evility.'),
 'D1C_Unique_3010': (1040, 1040, 2, 'high', 'Marjoly, Witch: D5 has the Witch class (Magic Moderation).'),
 'D1C_Unique_2420': (770, 6128, 3, 'low', 'Alt. Overlord: top-tier boss; Baal\'s Ultimate Revenge.'),
 'D1C_Unique_3140': (730, 6108, 3, 'low', 'True Overlord: the Overlord archetype; Zetta\'s Badass Overlord.'),
 'D1C_Unique_3050': (2160, 2160, 3, 'medium', 'Antoire, Noble Demon: Nether Noble Greedy Disposition.'),
 'D1C_Unique_3150': (1080, 1080, 3, 'medium', 'Serra Winguard, High Priest: priestly healer; Cleric Expert Hands.'),
 'D1C_Unique_3130': (2130, 2130, 3, 'low', 'Shark King, Evil Master: aquatic ruler; Sea Angel Lovely Song (the only aquatic D5 class).'),
 'D1C_Unique_3160': (1220, 1220, 3, 'low', 'Vesuvius, Fallen Angel: dark melee knight type; Dark Knight Ripple Impact.'),
 'D1C_Unique_3060': (530, 6009, 1, 'medium', 'Dark Flonne is Flonne\'s alter ego; D5 Flonne (char 530) Love Field. Variant form of the same character.'),
 'D1C_Unique_2611': (1050, 1050, 3, 'low', 'Prism Blue, Prism Ranger: fist-fighting hero; Martial Artist Fury.'),
 'D1C_Unique_2612': (1060, 1060, 3, 'low', 'Prism Yellow, Prism Ranger: agile hero; Fight Mistress Rapid Movement.'),
 'D1C_Unique_2903': (2170, 2170, 3, 'medium', 'Manty, Vassal: beast body (Bear animation donor); Bear Rage Charge.'),
 'D1C_Unique_2902': (2080, 2080, 3, 'medium', 'Gargo, Vassal gargoyle: Winged Warrior Spreading Miasma (same as the Gargoyle class).'),
 'D1C_Unique_2901': (2050, 2050, 3, 'medium', 'Ghoss, Vassal ghost: Fairy Magic Creation (same as the Spirit/Ghost class).'),
 'D1C_Unique_2904': (2210, 2210, 3, 'medium', 'Goleck, Vassal golem: Immortal Body (same as the Golem class).'),
 'D1C_Unique_2905': (2180, 2180, 3, 'medium', 'Dratti, Vassal dragon: Dragon King Anti-Element (same as the Dragon class).'),
 'D1C_Unique_2613': (50, 51, 3, 'low', 'Astro Carter, General: commander; Red Magnus Heart of a Leader (squad bonus).'),
 'D1C_Unique_6601': (50, 51, 3, 'medium', 'Carter is General Carter, the EDF commander and last enemy of the Human World bonus stage (Disgaea wiki EDF Headquarters page, disgaea.fandom.com/wiki/EDF_Headquarters, via search summary); Astro Carter (same man in the pack set) already uses this commander evility, Red Magnus Heart of a Leader; commander theme pick. D1CEVIL2 2026-11-19, replaces Warrior Wild Cry. Community: same wiki page, 2026-11-19: Carter is the EDF Commander and becomes Astro Carter. KEEP Heart of a Leader.'),
 'D1C_Unique_2614': (1150, 1150, 3, 'medium', 'Astro-One, Defender?: Armor Knight Hero\'s Shield kept. D1CEVIL2 2026-11-19 re-check: no community page found for this character; the guard reading rests on the rank title only. Community: Carter\'s two bodyguards (wiki search snippet, 2026-11-19). KEEP Hero\'s Shield.'),
 'D1C_Unique_2615': (1150, 1150, 3, 'medium', 'Astro-Two, Defender?: Armor Knight Hero\'s Shield kept. D1CEVIL2 2026-11-19 re-check: no community page found for this character; the guard reading rests on the rank title only. Community: Carter\'s two bodyguards (wiki search snippet, 2026-11-19). KEEP Hero\'s Shield.'),
 'D1C_Unique_3170': (2110, 2110, 3, 'medium', 'Dark Durian, Durian: fruit/plant; Flora Beast Sweet Aroma.'),
}


# EVILFX3 (coordinator, 2026-11-10): the 14 installed D1C folders outside the tracker roster get donors by the same
# ladder; a duplicate / alternate of a roster entry copies that entry's donor.  Added with `--extra GAME_DIR`
# (reads the clean D5 tables directly); the 45 roster entries above are not regenerated by it.
EXTRA = {
 'D1C_Unique_2590': (10, 10, 3, 'low', 'Kurtis (second folder of the same character): copies D1C_Unique_2216 Kurtis\'s donor, Killia\'s War Demon.'),
 'D1C_Unique_2500': (2100, 2100, 3, 'low', 'Mid-Boss is Vyers\'s own nickname (same character as D1C_Unique_2540 Vyers): copies its donor, Shroom Power.'),
 'D1C_Unique_5590': (1110, 1110, 3, 'low', 'Jn:Revamp is an alternate Jennifer: copies D1C_Unique_5 Jennifer\'s donor, Archer Support Attack.'),
 'D1C_Unique_5390': (530, 6009, 1, 'medium', 'Fl:F.Angel is Flonne as a fallen angel; D5 Flonne (char 530) Love Field, as for Dark Flonne (D1C_Unique_3060).'),
 'D1C_Unique_2300': (1200, 1200, 3, 'low', 'Dark Cannon: a fixed long-range gun; Pirate Acceleration Shot (damage by distance to the target).'),
 'D1C_Unique_2301': (1200, 1200, 3, 'low', 'Mega Cannon: a fixed long-range gun; Pirate Acceleration Shot.'),
 'D1C_Unique_2302': (1200, 1200, 3, 'low', 'Astro Cannon: a fixed long-range gun; Pirate Acceleration Shot.'),
 'D1C_Unique_2907': (1150, 1150, 3, 'low', 'Gatekeeper: stands guard at the gate; Armor Knight Hero\'s Shield (protects allies).'),
 'D1C_Unique_2909': (1100, 1100, 3, 'low', 'Item World attendant: handles items; Maid Efficient Work (free item use).'),
 'D1C_Unique_2910': (2160, 2160, 3, 'low', 'Weapon Shop keeper: merchant; Nether Noble Greedy Disposition (stats from money owned), as for Hoggmeiser.'),
 'D1C_Unique_2911': (2160, 2160, 3, 'low', 'Battle Depot keeper: merchant; Nether Noble Greedy Disposition.'),
 'D1C_Unique_2914': (2160, 2160, 3, 'low', 'Data Shop keeper: merchant; Nether Noble Greedy Disposition.'),
 'D1C_Unique_2915': (2160, 2160, 3, 'low', 'Music Shop keeper: merchant; Nether Noble Greedy Disposition.'),
 'D1C_Unique_2912': (1080, 1080, 3, 'medium', 'Hospital receptionist: healer; Cleric Expert Hands.'),
}


def extra(game_dir):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from d5lib import database, gamefs, textrefs
    fs = gamefs.GameFS(game_dir)
    ch = database.load_table('char.dat', fs.read('Database/Database_0.dat/char.dat'))
    sk = database.load_table('Skill.dat', fs.read('Database/Database_0.dat/Skill.dat'))
    out = Path(__file__).resolve().parents[1] / 'd5lib/importers/d1c-donor-evilities.json'
    doc = json.loads(out.read_text())
    for mod, (cid, eid, rung, conf, reason) in EXTRA.items():
        c, s = ch.find(cid).to_dict(), sk.find(eid).to_dict()
        assert eid in [c[f'evility{k}'] for k in (1, 2, 3, 4)], f'{mod}: D5 char {cid} does not carry evility {eid}'
        assert mod not in PICKS
        # TEXTHASH-D1C-DD2: game text is a SHA-256 reference, never a literal (the build resolves it).
        doc['mods'][mod] = dict(donor_char_id=cid, donor_name=textrefs.ref(c['name_EN']), evility_id=eid,
                                evility_name=textrefs.ref(s['name_EN']), evility_text=textrefs.ref(s['desc_EN'].strip()),
                                rung=rung, confidence=conf, reason=reason,
                                scope='outside the tracker roster (EVILFX3)')
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n')
    print('wrote', out, len(doc['mods']))


def build(tables, roster_mods):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from d5lib import textrefs
    ch = {c['id']: c for c in tables['chars']}
    sk = tables['skill']
    missing = [m for m in roster_mods if m not in PICKS]
    extra = [m for m in PICKS if m not in roster_mods]
    assert not missing and not extra, (missing, extra)
    rows = {}
    for mod, (cid, eid, rung, conf, reason) in PICKS.items():
        c = ch[cid]
        assert eid in c['evs'], f'{mod}: D5 char {cid} {c["name"]} does not carry evility {eid}: {c["evs"]}'
        s = sk[str(eid)]
        # TEXTHASH-D1C-DD2: game text is a SHA-256 reference, never a literal (the build resolves it).
        rows[mod] = dict(
            donor_char_id=cid, donor_name=textrefs.ref(c['name']), evility_id=eid,
            evility_name=textrefs.ref(s['name']), evility_text=textrefs.ref(s['desc'].strip()),
            rung=rung, confidence=conf, reason=reason)
    return dict(
        schema='d1c-donor-evilities/1',
        provenance=('D1CEVIL1 2026-11-10, owner decision: Disgaea 1 Complete has no evilities, so each D1C class/character '
                    'gets a DONOR evility (labelled donor, not source) from a vanilla D5 evility; ids/names/text read from '
                    'the pristine D5 char.dat and Skill.dat (installer originals); generated by tools/build_d1c_donor_evilities.py'),
        ladder='1 same character in D5; 2 same class in D5; 3 closest D5 class/character by role (reason recorded)',
        mods=rows)


if __name__ == '__main__':
    if sys.argv[1] == '--extra':
        sys.exit(extra(sys.argv[2]))
    tables = json.load(open(sys.argv[1]))
    roster = json.load(open(sys.argv[2]))
    out = Path(__file__).resolve().parents[1] / 'd5lib/importers/d1c-donor-evilities.json'
    out.write_text(json.dumps(build(tables, roster), indent=1, ensure_ascii=False) + '\n')
    print('wrote', out, len(PICKS))
