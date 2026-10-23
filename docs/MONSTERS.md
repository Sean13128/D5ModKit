# Generic monsters (`d5lib/monstermap.py`)

New recruitable monsters from Disgaea RPG generic monsters go into the reserved **Monster Dummy** families (char.dat
2220–2330), the same way new classes use the Human Dummy families. The pieces are:

* **`newclasses.create_monster`:** builds the mod.
* **Flags and lists:** unlock flags 17337+ (`newclasses.flag_of`); the relocated Hire / Class tab lists already hold
  monsters.

## DRPG monsters D5 doesn't have

30085 Spirit, 30089 Gargoyle, 30097 Death, 30105 Dragon Zombie, 30113 Rifle Demon, 30117 Lantern, 30125 Living Armor,
30129 Serpent, 30133 Dragon, 30137 Space Yellowtail. All have sprites, a face icon and a cut-in.

## How the sprite is made

* **Twins.** 20 D5 monster families have a DRPG twin; Sea Angel has none. DRPG unit = 30001 + 4k for D5 2010 + 10k,
  then 30053… for 2140….
* **Twin maps.** `_research/monster_twins.py` finds every D5 cell in its twin's atlas. The result is
  `d5lib/data/monster_twins/<cls>.json`: the cell → piece placement (drpgmap format) and every animation's cells.
* **No fixed layout.** Unlike humanoids, monster atlases are packed by size and every monster has its own number of
  poses (11–36). So poses are matched by **role**:
  * all 21 D5 monsters share one motion set (57 common animation ids);
  * `twin_roles(fs, template)` labels the twin's poses from the animations the engine plays, in this priority:

    | Role | Front / back animation | Note |
    |---|---|---|
    | stand | 1 / 7 | |
    | hit | 1061 / 1067 | 1141 / 1147 when those are empty; Dragon King's 1141 is a cell-less link to 1061 |
    | idle | 1001 / 1007 | |
    | walk | 11 / 17 | keys inside the loop |
    | crouch | 1121 / 1127 | the jump / lift take-off, reused by 1021 / 1031 / 1091 / 1501 |
    | jump | 1091 / 1097 | |
    | attack | 2071 / 2077 | |
* **The new monster's roles.** A small file, `d5lib/data/monster_roles/<uid>.json`, names the new monster's poses
  by role, judged from the sheets: stand, walk, hit, crouch, jump, attack and other.
  * Back and wait sheets can be `"grid"`: packed like the front, so the same place is the same pose.
  * Leave out DRPG **flash frames** (mostly white impact drawings, e.g. the Dragon's 49049). Stand should be the
    neutral pose that matches the first wait frame, so stand → idle doesn't pop.
* **Pairing.** `pairs_from_roles(fs, template, uid, roles)` gives every twin pose the new pose of the same role.
  * Sequences are spread over the template's free steps only: steps no higher-priority role already claims. A
    3-pose attack list maps 1:1 onto a 3-drawing attack.
  * Unlabelled poses get the most similar 'other' pose, or any non-flash pose, by silhouette.
  * `tools/new_drpg_monster.py suggest` uses the role file when there is one.
* **Build.** `build()` gives every template cell that draws a whole pose the new drawing.
  * **Whole pose.** `is_pose`: a good match covering 50–130% of the piece. A **turned** placement must also really be
    the same drawing (`is_pose2`: colour error ≤ 25 against the D5 cell art, or art lying down). Dragon King had four
    false 90° matches that drew the Dragon lying on its side.
  * **Ground.** The new drawing's ground point (x of the silhouette eroded by 8% of its height, bottom row) stands on
    the ground point of the **template's own D5 cell art**, which has no flames. The twin drawing's box included
    Dragon King's flames and slid the Dragon by up to 45 px. A drawing that is the twin drawing itself (a rebuild)
    keeps the exact twin placement.
  * **Rescue.** Rejected turned placements, and first keys with nothing to hold, get the pose whose twin silhouette
    best matches the cell art, upright.
  * **Hold.** A layer whose next cell is hidden keeps the previous pose (`_hold`).
    * The main body layer goes first.
    * It never holds while another layer draws a pose, which used to give two dragons.
    * Empty cells are hidden instead.
    * The held drawing stands on the hidden cell's ground point, so hops and dashes keep their motion.
  * **Idle.** Every looping animation that shows only stand / idle poses (`idle_anims`: 1001/1007, and 1051/1057 on
    Dragon King) shows every wait drawing once, evenly over the loop.
    * The first drawing stands where the template's first cell stood; the others are placed on its feet
      (`register_feet`).
    * Keys before the loop start show the first drawing.
  * **Breath** (`_aim_breath`, `_fade_behind`): a template with `d5lib/data/monster_fx/<template>.json` keeps its
    breath layers, aimed at the new monster's mouth. Dragon King has one.
    * The file lists the breath cells, and Dragon King's mouth point in each DRPG drawing he shows while breathing.
    * The new monster's role file gives its own `"mouth"` points; without them the breath is left out.
    * Per animation, the stream moves by (new mouth − template mouth), both taken through the body drawing at the
      breath's first moment. After that the stream keeps the template's own motion.
    * The forward breaths (`fade_behind_mouth`) fade out behind the mouth in a cone, so the fire starts at the mouth
      instead of trailing back over the body. The sweeping ones (4011/4017) stay whole.
    * Check: Dragon King rebuilt from his own twin gets a (0, 0) shift everywhere.
    * The QA leaves these layers out of its body measures.
  * `keep_fx=True` on a template without breath data keeps every effect-only layer of its attacks / skills where
    the template had it.
* **Script effects.** Some fire is not in the sprite at all: the attack's choreography spawns effects from Effect.dat.
  Dragon King's normal attack (15130100) spawns a line of fire puffs (effect 106, passed to its helper as 1060: [SKILL_EDITOR.md](SKILL_EDITOR.md#values-passed-to-helper-events-from-the-exe)) at his head height, from behind
  him to the target.
  * `_research/make_dragon_breath_script.py` gives the Dragon its own copy (15902000, called by its attack event
    12012220): puffs at height 20, the 4 rearmost dropped.
  * Seen in game facing three ways, the white-hot breath then comes from the Dragon's mouth.
  * The Dragon's build script runs it. A mod's own 12010000 + sprite event wins over the template copy made at
    install.
  * The report lists the turned placements (kept / rejected / rescued) and the idle drawings.
* **Check.** `python tools/qa_sprite.py BUILT TEMPLATE` compares the build with its template frame by frame. It
  reports missing animations, control differences (stalls), blank frames, ground jumps, feet sliding in idles, too
  few idle drawings, doubled bodies, collapsed animations, detached pieces and flash frames. It ends with
  `RESULT: OK` or the number of findings; the flagged frames go to `_research/qa/`.

## The monster wizard (`d5gui/monsterwizard.py`)

Characters & Classes › **🐉 New monster class…** does the steps below without the command line:

* the Disgaea RPG monsters whose sheets are on the PC (`monstermap.drpg_monsters`: the 21 twins and the 10 new);
* the templates best first (`recommend_templates`: the D5 twin, then the twin's front stand height closest to the
  new monster's);
* a first role file guessed (`auto_roles`: the new front poses paired with the twin's by shape (`suggest`), each
  taking the role its twin pose plays in the engine's animations; flash frames out, the rest 'other'; back and wait
  sheets 'grid'), which the user fixes pose by pose (a guess: on the Dragon it got the attack right but not the
  stand);
* Preview = `pose_sheet` of `pairs_from_roles`; Create = `newclasses.create_monster` (a class of the same Disgaea RPG
  unit made before is redrawn in its family), the role file kept in the mod as `patches/monsters/roles_<uid>.json`.

## Tools

```
python tools/new_drpg_monster.py --list
python tools/new_drpg_monster.py suggest UID TEMPLATE POSES.json [SHEET.png]   pairing (role file, else shape)
python tools/new_drpg_monster.py create UID TEMPLATE "Name" POSES.json --titles "..." --desc "..."
python tools/qa_sprite.py mods/<mod>/files/Anime/ANM_HI_JP.dat/anm<family>.lzs TEMPLATE
python _research/make_drpg_monster_dragon.py [TEMPLATE]      the Dragon prototype (D4 data from the wiki)
```

Choose a template with a similar build: bipedal or not, and a similar height (stand heights: Dragon King 226,
Twin Dragon 219, Bear 193, Nether Noble 191, Undead 188, Orc 166). Its skills come with it: the new monster's
skills are copies of the template's, choreography included.

## Status (2026-10-07)

* **Prototype `Monster_Dragon`.** DRPG 30133 in family 2220, on Dragon King's animations.
  * D4 data: ranks Dragon → Bahamut, stats and aptitudes, Mv 3 / Jm 20, Fire +20 / Wind −20 / Ice −20.
  * Skills: Wind Breaker, Dragon Claw, Dragon Missile, Dragon Assassinator, copied from Dragon King's four, with their
    choreographies.
  * Evilities: Rising Dragon, Fire's Blessing, Dragon's Treasure, Imperial Wrath, King's Dignity, Damage Cut.
* **Verified in game:**
  * hired at the Recruiter;
  * face icon, status screen, stats and resistances;
  * standing, walking front and back, idle;
  * normal attack (6 damage);
  * taking a counter.
* **2026-10-08: rebuilt on Dragon King with the ported build and role file v2.** QA: 0 findings, where the old build
  had 57 ground jumps, 44 flash frames and 8 doubled bodies. Seen in game:
  * the enemy phase finishes after the Dragon is attacked and counters (Mr. Monster 19 → 7 HP);
  * it stands upright with its mouth closed, and the back idle cycles its wait drawings.
* **Counterattack stall: fixed (verified in game 2026-10-08).**
  * Cause: a monster's normal attack is script event 12010000 + sprite id, or 12110000 + sprite id when its effects are
    skipped (the user has Enemy Effects: skip). The Monster Dummy sprites have neither, and the fallback 11100000 doesn't
    exist. So in the enemy phase the counter started no script, and the battle waited forever.
  * Fix: at install (and in the live preview), new monsters get their template's 12010000 / 12110000 / 12210000 events,
    and the kit adds 11100000 / 11200000 as a safety net (see SKILL_ANIMATIONS.md).
  * The monster's companion file (anm N+1) now keeps only the template companion's animation ids, as in vanilla.
