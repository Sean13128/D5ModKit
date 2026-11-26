# Import gates and what they taught us (2026-11)

Every importer (`tools/import_game.py d4|d1c|dd2|drpg`) runs the gates in `d5lib/importcore.py` on each pack it
builds. A pack that fails a gate is built but reported as not installable. This page lists the gates added in
November 2026 and the game fact behind each one. Format facts live in the format docs (`ANM.md`, `DATABASE.md`);
this page is about ids, slots and skills.

## Used ids across importers (`UsedIds`, `tools/check_used_ids.py`)

A pack claims ids in several tables (char, charPersonal, magic, evility, Quest ids, quest progress slots, sprite
numbers, string rows). The gate checks each claim against three sources:

1. the original game's tables (a clean backup, never the modded install);
2. every importer's lease file (`d5lib/importers/*-leases.json`, `data/unique_art_leases.json`);
3. the mods that are installed (`D5_INSTALLED_MODS`, `offlinepaths.installed_mods_root()`).

Rules that came out of real collisions:

- **Installed keeps its ids; the uninstalled side moves.** Renumbering an installed pack breaks saves.
- **Ids handed out per run are not leases.** The first Disgaea RPG build gave out quest ids from "next free" on
  every run; 110 of 146 packs then collided with D1C and DD2 packs installed in between. Quest id, quest slot and
  help rows are now pinned per base character in `drpg-leases.json`.
- **A lease check against a holding folder is not a check against the game.** Point the gate at what is installed.
- **Test packs are claims too.** A leftover test bank in an installed folder replaced another character's body;
  remove test packs before the next install.
- Sprite numbers below 2000 are scarce: count what is left before leasing a low window.

## Quest progress slots and saves (`tools/save_quest_slots.py`)

`Quest.dat` `sort_order` is the quest's progress slot in the save: three bytes per slot (completed, accepted,
seen), 0x400 slots (`d5lib/savegame.py`, `dbpatch.check_quest_slots`). Two consequences:

- A slot must stay with one quest whatever is installed, or a save shows one quest's progress on another.
- **A slot can be dirty in a player's save** from an older mod that used it. A new recruit quest on such a slot
  shows as already seen, accepted or done. `save_quest_slots.py SAVEDATA_COPY --out dirty-slots.json` lists the
  slots that are not all-zero in any save; the DRPG lease allocator takes the file (`--dirty-slots`) and never
  hands those slots out. Run it on a backup copy of the saves. Importers never open saves themselves.

### The Quest Shop board only lists slots below the row count (QBOARD1, 2026-11-10)

The board builder (`FUN_1407ec450`) walks `Quest.dat` rows in id order, stops at the first id >= 2000, and only
looks at progress slots 0 .. row count - 1. A recruit quest on a higher slot is never listed. The installer keeps
high slots listed by adding hidden rows (`dbpatch.check_quest_slots`: own id as prerequisite, so never offered).
Their id pool was 1900-1999; with 161 mods the table needed 112 and quests on slots 709-711 and 761-781 vanished
from the board. The pool is now 1490-1999 (510 ids; 1024 slots - 516 vanilla rows = 508 is the most ever needed),
so **new shop quest ids must stay below 1490**. When no unscanned slot is left, a hidden row shares the highest
real quest's slot: the board takes the first row on a slot, which is the real quest.

Other rules of the builder (source-read): a quest is skipped when its slot is completed or is one of the 10
accepted quests; it is listed when its prerequisites are completed, its story flags are set and `min_level` is
at most the highest army level; a slot already marked seen skips the prerequisite and flag tests (another reason
dirty slots matter). No reward check, no randomness. The builder stops at 1000 candidates; the display array
holds 512 entries with no bounds check, so keep the listed total well under 512.

## Skills on imported uniques (`unique_skill_gate`, `skill_motion_gate`)

- **A unique that learns nothing is recruitable but not playable.** `unique_skill_gate` fails a `D1C_Unique_N` or
  `D4_Unique_N` with `learn_count` 0 unless the reviewed source map (`d5lib/sourcemaps/d1c.json`, `d4.json`)
  says the source game gives it no skills (`no_source_skills`) or none has a D5 twin (`donor_only`).
- Each mapped skill carries its `basis`: same name, another reviewed map, same mechanics, or donor. A donor
  pairing is an approximation and is labelled as one.
- **A mapped skill must be playable by the body.** `skill_motion_gate` (`tools/check_skill_motions.py`, built on
  `d5lib/choreo.py`) resolves the caster motions of every learn-list skill and fails when the unit's battle bank
  lacks one, unless vanilla D5 runs the same skill with that motion absent for the same body type ("fallback",
  counted in the message). Pairing by name alone produced skills whose caster pose did not exist.
- `nativeimports.ability_sourcemap(game)` refuses a source map without `skills` and `evilities` keys, so a
  unique-skill map cannot be used as an ability map by accident.

## Monster bodies need a resident placeholder (`resident_placeholder_gate`)

See `ANM.md` section 5a. Short form: while a monster's body bank loads, the game binds sprite number N+2, and it
only finds that number in the always-loaded animation pack. A monster unique whose N+2 is a loose file is
invisible and the game freezes when it is hit. The installer adds the block (Cryswar's design); the gate fails
any monster-kind pack without one.

"Monster-kind" is the char row's `body_type` 1 (row+0x386, read by `unit_set_appearance` 0x14014ea10), not only
a registry unique declared `kind: "monster"`. NODRAW2 (2026-11-10): the 37 DRPG monster-template uniques (Beatrice
743/16730, Hanako, Suisen, Colossal Prinny...) and a few monster-body costume rows are plain `char.dat.json` rows;
neither the installer nor the gate looked at them, so their N+2 stayed loose and real recruits drew no body. Both
now also take every added row with `body_type` 1: the installer when the build ships anm N+2 loose
(`newclasses.char_monster_sprites`), the gate when the pack ships body bank N. A memory class swap onto a
humanoid army unit does not reproduce the failure, so survey invisible bodies on quest-recruited units.

## A low-row character needs a face template (`face_template_gate`, SMALLFIX1)

The status-panel portrait is a face animation the installer clones from a template (`outfits._finalize_characters`).
It learns the template from `patches/characters/unique.json` (`template_colour`), or from a row whose colour id differs
from its id. A low row (id < 1000) whose sprite id and colour id both equal its id and that has no declaration looks
"already faced" to `newchars.find()`: no animation is cloned and the portrait is blank in game (Shark King 931 and
Xenolith 941, found live 2026-11-10; the installed resident face block 9017 lacked 931/10931 and 941/10941).
`nativeimports.build_entry` now writes the declaration for the legacy low shape too; the gate fails a pack without it.

## DRPG class titles (`class_title`, SMALLFIX1)

Every DRPG pack used to write the group label "Disgaea RPG" into the title fields the status panel prints under the
name. `importers/drpg-titles.json` holds the character's own title (JP characterclassname at the base rarity; English
documented on the Disgaea RPG Wiki where it exists (DRPGTITLE2, below), otherwise a labelled provisional translation;
Disgaea RPG Global is not a source, JP supersedes it); `drpg_titles.gate` fails a pack
whose rows do not carry it. Two characters (60019, 60025) have no source title and keep the label, named in the table.

DRPGTITLE2 (rework 2026-11-19): every entry says whether its English is documented. `en_kind` "community" (9
characters) cites the Disgaea RPG Wiki (Fandom) character page in `en_source` by URL, revision, author and the
rendered star-rarity title; the title-name template (`Template:Enum/JP/Titles`) supplies the string, and the archived
Global master is cited beside it as corroboration where the two agree. Seven pair verbatim (the JP string we ship is
the JP character row's `class_name_N` and the same column has the English); two (20009, 20010) have no JP class-name
columns, so the wiki's own rarity-slot assignment is the pairing evidence. The archived Global master is not a
source (the project reads JP; Global is not used), so no row is sourced from it alone. Where the two documented names
disagree (55 Noel "Yuletide Mage" vs "Holy Night Mage", 20011 Tink "Boy-Turned-Frog" vs "Frog the Former Cute Boy")
the title stays provisional. The other 135 stay `en_kind` "provisional" and name the reason: no row in the archived
Global master snapshot (81), its Global class-name columns are empty (34), a different title set (18), or the
documented-name conflict (2). `drpg_titles.apply` rewrites every row, so a staged pack can be re-titled in place
without a rebuild.

## A body must draw on its idle motions (`idle_drawable_gate`, NODRAW1)

Every sprite bank (N and N+1) a mod ships for a char row must hold animations 1001 and 1007, and the first frame of
each (shared-pose stubs shown) must put an opaque pixel on screen. The game selects the idle motion by id and falls
back to the bank's first animation, the empty id 0, when the id is missing (`anm_actor_select_motion` 0x1402f4ba0);
the tile then shows a shadow and a HP bar only. Swept over all 302 installed D4/D1C/DD2/DRPG packs on 2026-11-10 it
flags none, including the 11 packs SURVEY1 saw empty: their banks are sound, so the gate guards the importer output
and does not explain those 11 (see `NODRAW1-REPORT.md`).

## Palette counts must fit the game's buffer (`palette_count_gate`, WRITEWATCH1, 2026-11-21)

A bank's PaletteInfo rows carry a colour count that the attack set-up copies, unclamped, into a 256-colour buffer. D2's big-endian
count read as 0x01000000 in D5 and overran it on any attack (details in `docs/ANM.md` section 10). The gate fails a bank with any row count
outside 1..256; `d2anm.d5_palette_counts` is the importer fix. The software write-watch (`watch` command, `d5lib/wwatch.py`) found the
writer; it is off unless armed through the remote pipe.

## Required motions (`required_motion_gate`, SHARKBANK1, 2026-11-21)

A shipped main bank must hold the motion ids that all clean-game banks of its body kind hold (`d5lib/data/required_motions.json`,
written by `tools/required_motions.py`). It is a guard, not the Shark Dragon explanation (that was the palette count above).

## Class names carry the source game (CLASSTAG1, 2026-11-21)

Generic classes built by `nativeimports.build_entry` are named `<name> (D1C)` / `<name> (DD2)` (`class_display_name`), like D4's
`(D4)`, so two source games' Gargoyle or Masked Hero do not double in the recruit list. Uniques are not tagged.

## The game draws node root+1 (`render_root_gate`, BACKVIEW1)

The game builds an animation's picture from node `root+1` and its children; the root is only the control track and
its own `child`/`next` links are never followed (`anm_actor_build_render_root` 0x1402f5450). Every native animation
(all 5,484 in `anm_resident`) has `root.child == -1`, `root.next == root+1` and no siblings at `root+1`. The gate
fails a pack when, at some key time, the game model (`anm.evaluate(game=True)`) draws other parts than the kit's
walk (`anm.render_root_mismatches`). PT1030ANIM's wheel stubs broke it: in game 1001 played the back idle and 1007
drew nothing (Kojiro/Chief/Garatea/Baltis seen from behind). Repair: `ownanim.fix_render_roots`. 2026-11-10 sweep:
52 of 319 installed folders failed (26 D4, 20 D1C HURTSLOT1 hit motions, 6 DRPG); see `BACKVIEW1-REPORT.md`.

ASAGI4P2 (2026-11-19): `ownanim.assemble` (the monster/DRPG atlas build) now ends with `fix_render_roots`. The monster
template's roots link the drawing through `next`, so a fresh rebuild of Creator Asagi (look 20055) had 76 + 53 animations
that the game draws differently; `game_truth` `body: render root` failed on INSTALL1119A run 1 (the installed bank had the
BACKVIEW1 sweep's repair, the rebuild did not). A no-op for banks already laid out natively.

## D1 Complete humanoids are D5 humanoids: the source rig (D1CRIG1, 2026-11-23)

Format facts (D1C Switch v0 `start.dat[98]`, D1C decomp, D5 Steam build; offline):
- D1C draws an HD humanoid with D5's ANM module. The character ids `FUN_7100046000` lists (1-9, 1002-1999, 2410,
  2700, 2907-2915, 3060, 3150, 3160, 3180, 3500, 5590) bind the owner to shared **block 1** with binding key 1 -> the
  body; any other HD character plays its body block's own motions (monsters). `FUN_7100045a70` = 0 draws classic
  sprites instead (Dark Cannon 2300-2302; our packs draw them on Laharl's HD body 10, which D1C never does).
- Block 1 is D5's `anm_resident` block 1 renumbered: its 124 cells are D5's rectangles, and 93 of its 105 motions equal
  a D5 resident motion key for key (`d1crig.D5_TO_D1C`: 1501 = 2001, 2511 = 3001, 2671 = the lift hold 1131 ...).
  A body supplies only textures, palettes and 0/6001/6007 (some bodies also 7001-7031). Its pages fill D5's sheet
  layout except cells 1, 3, 105-108 (empty) and 124 (page 8, absent).
- So D5's resident motions draw a D1C body exactly as D1C does. The motion audit below measures 0 differing pixels at
  every key of all 59 twinned motions for body 1140, with every motion on one feet line.

What the importer does (`--d1c-rig auto`, the default): a block-1 humanoid whose body fills the layout is built by
`d5lib/d1crig.build_bank`. That is ANIMALL2's merger (`tools/animall2_tracks.build`, with D4CELL1's off-page rule)
run on D5's block: the 135 resident motions are copied, the body's own animations appended, and the body's pages
and palettes kept byte for byte (palettes padded to 10 with copies of palette 0). Missing 7001-7031 are held on the
stand. The bank stays an own-animation sprite (`own_sprites`, the same exe path as every kit sprite). N+1 is the
same bank; N+2 is the builder's standing picture. A rig bank skips three passes: grounding, the HURTSLOT1 remap and
the BLANKKEYS1 hold. Those passes repair a flattened bank (held reaction pages, resampled blank keys, a donor pivot);
the reasons do not hold for D5's own motions. `ownanim.banner_layout` leaves a bank alone when its own stand already
draws the banner rectangles (`d1crig.standard_banner`), which a rig bank does. `--d1c-rig off` keeps the flattened
path (`d1cart.poses` + `ownanim.build`) for comparison; `on` fails an entry the rig cannot build.

Gates:
- The bank's page count is the body's (Scout: 4 pages, against 2 flattened). The importer records the change in
  `mod.json` `source_import.shape_changes`, and `wheel_gate` / `_wheel_freeze` compare the bank with that
  declaration (equality, page sizes too; `importcore.declared_shapes`).
- The declaration is not an approval. A rig pack needs the owner's go-ahead and a live Hire-wheel check before
  install: WHEELMEM1 found that image objects grow the wheel's resident set. Vanilla humanoid banks carry 6 pages
  + 10 palettes; a rig bank carries 4-6 + 10.
- `hurt_slots` reads n/a for a rig bank.
- The new gate `source_motions` (rig packs only) requires every motion with a D1C twin to equal the source at every
  key.

Audit: `tools/d1c_motion_audit.py MODS [--gate]` renders each D1C pack's battle bank against the D1C source playback
at every source key time. Per motion it reports an origin class (source / offset / held / stand / differs /
no-source / missing / blank), the percent of drawn pixels that differ, the feet-line offset and the cycle length.

Rank titles: class ranks take the character table's title column (Scout, Surveyor, Ranger, Strider, Geo Master,
Lord for 1140-1145), not the name column ("Strider 2" ...). Grounding: a rig bank has one feet origin, so the two
humanoid classes need none. The monster class (Vampire 11930) is still off its source line (stand 25 px, walk and
idle 36 px high). `standground.align_to_source` is not the fix there: it lands the stand (-3 px) but pushes walk and
idle 33 px low, because one shared shift cannot fit motions whose donor tracks hold the body at different heights.

## Build hygiene

- D1C builds are serial (a lock in `importers/d1c.py`): two builds at once overwrote each other's state.
- Compare reasons are not acceptance: measure the built bank against the source body.
- `tools/drpg_batch_check.py` is valid only before the first batch of a set is installed; after that the batch's
  own rows read as "not free". From the second batch on, use `check_used_ids.py`.

## Runtime: input guard (`[debug] input_guard`, `d5lib/native/d5auto.c`)

The game reads pads in the background (XInput and DirectInput) and a hidden window still receives keys, so a
player's controller or typing reached the game during automated runs. With `remote=1` the runtime core drops real
keyboard, mouse and pad input; pipe input is unaffected. `state` reports `input_guard`, `guard_kb` and
`guard_pad` (counts of dropped events). Check `input_guard 1` after boot before sending any input.

## Disgaea RPG own skills (`own_skills`, DRPGSKILL1)

`d5lib/importers/drpg_skills.py` applies `drpg-skill-overlay.json` (built by `tools/build_drpg_skill_overlay.py`
from the JP client's `command` / `charactercommand` / `charactermagiccommand` masters; restage without art with
`tools/stage_drpg_skills.py`). Format facts learned:

* The RPG has no map. A command effect's target is one enemy, all enemies, one ally, all allies or self
  (`effect_targets` 1-5); there is no range, area, cooldown or charge gauge. Cost is SP (`sp_min`, falling to
  `sp_max_50`). `relational_param` 2 = ATK-based, 4 = INT-based. `charactercommand.lv` is a character level
  (1 / 50 / 200); `charactermagiccommand.weapon_mastery_lv` is a weapon mastery level (4, 9, 15, 22, 30, 40).
* D5 reads a damage or heal skill's power as `effectN_value + power_lv[level] - 100`, and a support / debuff
  row's (formula 5 / 6) as `power_lv[level]` alone; other added effects use `effectN_value` as written
  (`FUN_1401D7A20`, `FUN_1401D78E0`). So an own damage row sets `effect1_value = source percent - 100` and keeps
  `power_lv1 = 100`.
* Learned skills live in the unit record by id (`+0xCC0`, 16-byte entries, at most 512; `unit_stats_skills_grant`
  0x140160B00) and are found by a binary search of magic.dat by id (`unit_stats_skills_magic_row`). Row position
  does not matter, unlike learned evilities. A learn list only grants: removing a link never removes a skill a
  saved unit already holds.
* Own rows are ids 17000 + 4 * lease position + n (band 17000-17599 in the ownership manifest). The overlay stores
  no game row: per own skill the stand-in's id, the sha256 of the stand-in's vanilla row, and the fields that differ.

The gate fails when a pack's rows, choreography links or learn list are not the overlay's, when a link resolves to
no magic.dat row, when a value leaves its field width, or (stage tool, with `skillmotions.Survey`) when a caster
motion is missing from any body of the pack. Decisions `M1` (weapon-mastery spells at character level = mastery
level) and `C1` (drop the costume looks' D5 lookalikes) are off.

## Unique default palette (D1CCOLOR1, 2026-11-11)

A D1 Complete unique's art is built from colour-0 source art and `sourceimports.map_source_palettes` matches it against
source palette 0, so the built bank starts with source palette 0 in slot 0. The source character table (start.dat[43],
224-byte rows, palette byte at row+0x49) selects the palette the character really wears (Prism Blue: body 2610, palette 1).
Rule: for a unique with selected palette p > 0, `sourceimports.select_default_palette(bank, p)` swaps slots 0 and p
(and 10 and 10+p when the bank has the graft's offset-10 group), on the battle bank, its companion and the standing icon.
Palette count, textures, cells and every sprite/colour/art key are unchanged; the old default moves to slot p. Classes keep
per-rank bindings and are not touched; a source-0 unique is byte-identical. `build_entry(default_palette=p)` applies it at
build time; the D1C importer applies it to the built pack from the table's palette byte. 13 installed packs were affected
(Prism Blue/Yellow, Astro Carter/One/Two, Sardia, Dratti, Antoire, Shark King, Serra Winguard, Vesuvius, Dark Durian, Jn:Revamp).
Offline proof is the rendered default frame against the source palette; native look is a live check.

## D1 Complete face portraits (D1CFACE1, 2026-11-11)

The source has a face for every class colour and most uniques: start.dat[73] is a table of 365 spans. Layout: u32 count,
then count+1 u32 offsets from byte 4, then count u16 sprite ids. Each span is a 16-byte header (u16 w, u16 h, kind 3)
followed by raw RGBA on an opaque white background; 272 spans are 256x256 faces, 4 are 64x64 icons, 89 are empty.
A character's face is the span whose id equals `legacy_body + palette` of its start.dat[43] record (class colour c is
body + c). The span index is NOT the record index (only 0-4 coincide). `d1c_art.py` uses the source face first and keeps
the earlier cut-in crop as a labelled fallback. Held on the crop: Dark Flonne (her record resolves to Flonne's face) and
Sardia, Serra Winguard, Antoire (the face found has a hair colour unlike the sprite palette; `SOURCE_FACE_HOLD`).
This is a table lookup cross-checked by eye; the game's own lookup was not traced, and the in-game look of a 256 source
face scaled to 204 is a live check. Earlier notes saying D1 gives generic classes no bust were wrong.
Seen live (LIVE9): used as-is the faces show as a small face in a white box, because the span has no real alpha (255
everywhere, white baked in) and the portrait fills only a 160 px block at the top of the 256 cell. `cut_out_face`
(FACEFIX1) makes near-white pixels connected to the border transparent (enclosed white such as eyes and teeth stays),
feathers the edge, drops slivers of neighbouring atlas cells, crops to the subject and centres it in the 204x204 frame
like the Disgaea 4 / Disgaea RPG faces. Pale subjects need an eye check (Living Armor's flame glow is bitten).

## D1 Complete HD faces: anmdat.fad, not start.dat[73] (D1CHDFACE1, 2026-11-18)

start.dat[73] (above) is the older, PC-era face set: same compositions as the Disgaea PC 64x64 pixel faces, redrawn
at 256. Disgaea 1 Complete's own redrawn faces, the ones matching the HD battle bodies, are 268 textures named
`swf####` inside SUBDATA.DAT `anmdat.fad` (Switch; the PS4 `zz_anmdat.fad` has the same 268 names in another pixel
layout). Entry: name `swf####\0` (8), u32 entry size, u32 0, u32 packed size, u32 raw size, u16 width, u16 height,
u16 colours (256), u16 bits (8), then `YKCMP_V1` type 4 (Yukes LZ) at entry + 48; raw = 256 RGBA palette entries +
width*height 8-bit indices, linear rows. All are 256x256 full head-and-shoulders frames on opaque white (alpha 255).
The game's key (D1C decomp `FUN_7100006af8`, Switch v0) is `swf%04d` of the table row's sprite id (+0x60) + palette
(+0x49), except ids 2300 -> 2300, 2301/2302 -> 2301, 2918 -> 2230, 3190 -> 3600. Every installed D1C row and all six
colours of the 13 D1C classes have a face. Where a family was redesigned for D1 Complete (2080 reaper, 2100 rifle
demon, 2150 skull dragon) only this set matches the body, and the hair-colour mismatches that held Sardia, Serra
Winguard and Antoire on cut-in crops disappear (their keyed face is colour-true here). Shared faces by the game's
rule: Dark Flonne shows Flonne's face (sprite 3; `swf5390` is the fallen-angel Flonne), Maderas the Nosferatu face.
`d5lib/importers/d1c_hdfaces.py` reads it; `--d1c-faces hd` (default) writes it resized to 204 on its white;
`hd-cutout` applies the FACEFIX1 flood fill (clean on these full-frame faces in an offline sheet; not seen live).
Class faces are written under `patches/characters` and `patches/classes`.

D1CHDFACE2 (2026-11-18) rebuilt the whole in-scope roster with the HD default: 59 packs (13 classes + 46 uniques;
the three object bodies 2916, 6701 and 2918 stay out of scope). The 46 uniques include 14 D1CHDFACE1's 45-row sheet
did not list (cannons 2300-2302, Mid-Boss 2500, Kurtis 2590, Gatekeeper 2907, the shop and Item World NPCs
2909-2915, Fl:F.Angel 5390, Jn:Revamp 5590); the game's key gives them faces too (2300 -> swf2300, 2302 -> swf2301,
2907 -> swf1130, 5590 -> swf0006). All 124 distinct pictures (202 files with the `patches/classes` copies) are
204x204 and pixel-equal to `d5lib.importers.d1c_art.hd_face_picture`; every pack passed every gate. A rebuild
differs from the installed 11-12 packs in its faces plus the bank/db differences the importer has accumulated
since (46 packs carried changed sprite banks or db patches, all `expected` in `--compare-installed`, none missing);
12 packs are face-only.

## Offline roster contact sheets (SHEET1, 2026-11-11)

`tools/roster_sheets.py` renders every installed imported unit offline: stand, walk, attack, hurt and its skills' caster
motions, front and back, at the row's palette, into one PNG per unit and an index per source game, with a JSON of
PASS/FAIL/NOT CHECKED checks (motion exists, frame drawn, size versus stand, front differs from back, palette in range).
It reads the installed archive and the clean game's skill scripts, so it shows what the files say, not what the game
loads. A FAIL names the unit and motion; NOT CHECKED means the evidence is missing, never a pass. The whole roster
(245 units) takes under a minute. It renders frame 0 (attack: the middle frame) only. Image output is game art: write
it outside the repository (`--out`).

## Disgaea RPG monsters with a detached piece (SHEETFIX1, 2026-11-11)

Some Disgaea RPG monster frames draw a small companion piece apart from the body (Lord Desdeath's floating orb). Cut
as its own region it made the wait sheet read orb, body, orb, body, so idle loops showed the orb alone and the front
and back region counts differed (35 vs 29), which mispaired back poses with front ones. `drpg.merge_satellites` joins
such pieces to their body; `monstermap.regions` applies it only where it makes the front and back counts equal (an
unguarded merge regressed another look). Affected: Lord Desdeath (20108), Yubana (20092), and Creator Asagi's HGC Asagi
look 20055 (ASAGI4P, 2026-11-18 — held back by REPROFIX1 until Sean accepted the extra atlas page; see "An approved
bank shape change" below). 22 of 42 monster looks still
have unequal front/back counts and are unverified. Separately: a monster's normal attack is script event
12010000 + sprite, which plays motion 207 (ids 2071/2077; Death's is motion 151 = 1511/1517 on a monster body). These
ids live in the MAIN bank `anm<sprite>`, not the companion `anm<sprite+1>` (clean game: 78 ids in a main bank, 54 in
its companion). An earlier reading of this section said 48 imported monsters lacked the motion: that was the sheet tool
reading the companion bank, corrected in MONATK1; all 48 hold it. That the game plays it from the main bank is inferred
from the clean layout, not yet seen live.

## Monster attack frames that do not draw (MONATK1, 2026-11-11)

Measured offline as "key times that draw": D1 Complete Dragon Zombie and Golem drew their attack on 1 of 10 key times
(the donor attack puts the body on a layer the import hides); Spirit, Serpent and Death are partial. `ownanim.attack_tracks`
puts the source attack frames (D1C `attack_fist`, source 1071/1077) on the donor's clock via the source-track mechanism,
and fixes a first-key "no cell" fault. Dragon Zombie is rebuilt with 6 of the source's 12 frames (8 needed a fourth
texture page, which the texture-count gate refuses): an approximation in frame count and timing. Disgaea RPG monsters
have atlases without animation, so their attacks are template timing with the unit's own poses: approximated.

## A rebuild equals the install (REPROFIX1, 2026-11-16; REPROFIX2, 2026-11-17)

The installed packs were built at different times by lanes that patched them outside the importer (hand-tuned faces,
list-icon re-leases, held poses). Where the importer cannot reproduce such a patch from the source, the build now
takes the installed pack's own result, and every build records the flags it used:

- **D1C faces** (since D1CHDFACE1 the default is `--d1c-faces hd`, the game's own HD faces, see above; before it the
  default was `installed`). `--d1c-faces installed` reuses the installed pictures. The install carries the
  D1CFACE2 faces (RGBA, hand-tuned crops and busts); the importer's own source face (`opaque`, D1CFACE1B) or the
  FACEFIX1 flood-fill cut-out (`cutout`) differ in ~98% of pixels. Installed `face_*.png` under `patches/characters`
  and `patches/classes` replace or join the rebuilt ones; a face only the rebuild has stays (see the Serpent note
  under REPROFIX2 below).
- **List-icon rows are pinned** (DRPG, `--no-icon-pin` to keep the isolated allocation): `outfits._new_icons`
  allocates texturedatabase rows from the machine's database at build time, and `modshare` moves a pack's pair when
  it is imported after others, so the installed row ids follow import order, not the art. `importcore.pin_installed_icons`
  copies the installed pair for the class ids both packs declare.
- **The build's flags are recorded** in `mod.json` `source_import.importer_options` (voices, specials, reviewed
  abilities, faces, hold, icon pin), so a later rebuild need not guess them (`--no-d1c-hold-blank`,
  `--d1c-faces`, `--no-icon-pin` were added for this).
- **D1C blank key times are held** (REPROFIX2, default; `--no-d1c-hold-blank` turns it off). A whole-body import keeps
  one body track per animation; where the donor's body keyed a track the import hides, the pose is blank at some key
  times. BLANKKEYS1 measured this and patched the installed packs with `ownanim.hold_blank_keys` (the nearest earlier
  drawn key of the same private layer is repeated; shared layers and animations that draw nothing are left alone).
  The installed Serpent bank draws on all 30 key times of 1501; the build used to leave three of them blank, which is
  why `anm02720` differed. Labelled approximation: the pose is held, not animated (BLANKKEYS1 sec. 3 item 3: the real
  source attack for Serpent/Death is still open).
- **Known rebuild-vs-install leftovers** (2026-11-17, both labelled, not defects of the build): Serpent
  `face_11840_5.png` exists only in the rebuild — the source body 2090 has six palettes and face sprite 2095 exists,
  the D1CFACE2 script's Serpent line covers five colours (`Builds/D1CFACE2-20261112/scripts/build2.py`), so in the
  installed pack colour 5 has no picture of its own and the kit's reader (`newclasses.face_path`) gives it the colour-0
  one. Not seen in game: whether the game itself falls back the same way is unverified. Carter 6601 `anm10796` is the D1CFACE2 cut-in made from the story
  bust (PC `NEW_BU####.TX2`, decoded through `Migration/CharacterForge` + hand-tuned crops); it lives in that script, not
  in the importer.

## An approved bank shape change (ASAGI4P, 2026-11-18)

The wheel-freeze rule (`importcore.wheel_gate`) compares a rebuilt bank's image-header counts with the installed
copy for equality, because the wheel's resident set grows one-for-one with them (WHEELMEM1). Sometimes the owner
accepts a change: the SHEETFIX1 satellite merge gives Creator Asagi's HGC Asagi look 20055 (class 30820, sprite
16650) four atlas pages where the installed bank has three, and Sean took the 4-page atlas (ASK-AD0982, 2026-11-18).
A pack like that is listed in `importcore.APPROVED_SHAPE_CHANGES` by (mod folder, member path) with the approved
`textures`, `palettes` and page sizes. The gate then compares against the declared shape instead of the installed
one — still for equality, page sizes included — and returns a `declared shape change ...` note that lands in the
build report. The declaration is not a blanket waiver: an undeclared member keeps the installed reference, and a
declared bank that drifts from its approved shape fails. Once the rebuilt pack is installed the declaration agrees
with the installed bank. Adding an entry is an owner decision, not a lane decision: the cost is one more image
header in the wheel's resident set.

## DD2 battle fields come from the source row (`dd2_field_audit`, DD2FIELDS1, 2026-11-23)

The DD2 builder was handed only id, base stats, aptitudes, title, palette and help text; every other `char.dat` field of
the built row came from the D5 donor (`_dd2_baseline._worker`). The 676-byte source row holds the battle block, and
nothing noticed that 225 of 607 compared values differed across all 12 installed packs. Format facts, all measured
(evidence per field: `Research/import-checklist/source-values/dd2-FIELD-MAP.md`):

| Source offset | D5 field | Note |
|---|---|---|
| +0x1A2 u16, +0x1A6 u16 | `MOV`, `attack_range` | same units |
| +0x1A4 u16 (0/1) | `move_type` 0/1 | 1 = flying |
| +0x28D, +0x290, +0x291, +0x292 u8 | `JMP`, `throw`, `counter`, `crit` | `crit` is the percent shown on the status screen, D5 uses the same scale |
| +0x285, +0x286, +0x287 i8 | `res_fire`, `res_wind`, `res_ice` | element id 1/2/3 of `magic.dat` +0x111 indexes unit+0x116B.. (damage code `0xF5524`); positive resists |
| +0x27C..+0x282 u8 | `mastery_fist..staff` | S 25, A 20, B 15-18, C 10-14, D 5-9, E 2-4; D5's unit |
| +0x289 u8 | `kind_gender` | D5 reads it only to pick the random-name bank (`unit_class_name_bank`: 0..2 keep the row's name) |
| +0x000 i32 | `immunity_flags` | only none -> 0 and all 28 bits -> -1 carry; D2's partial masks use another bit order |

Stay on the donor, with the reason in the pack's `mod.json` `battle_fields.donor_reasons`: `hl_value`, `exp_value`,
`mana_value` (located by pattern only; D5 rebalanced them), `is_unique` (no reader found in the D5 export, risk
unsettled), `res_star` (no byte), weapon resistances, partial immunity masks.

`d5lib/importers/_dd2_baseline.py` reads them through `dd2source.battle_fields` and `nativeimports._gameplay_row(...,
battle=...)`; `mod.json` `source_import.battle_fields` lists per rank and field the value, offset, class
(source-exact or rule-converted) and evidence. The old behaviour is `tools/import_game.py dd2 --no-dd2-source-fields`
(option `dd2_source_fields`, recorded in `mod.json`).

Palette: a unique's art is extracted in the palette the row selects (+0x28B, Virunga 5), but `map_source_palettes`
looked those colours up in bank 0, found no match and shipped bank-0 colours in every slot. `base_bank` now names the
bank the art comes from and `default_palette` puts it in slot 0 (bank shape unchanged: same textures, 10 palettes).

The gate: `python tools/dd2_field_audit.py --mods DIR --gate` compares every carried field of every `DD2_*` pack in DIR
with the source `char.dat` (independent offset table) and, for a unique, checks that every opaque slot-0 colour is in the
source default palette; exit 1 on any difference. On the 12 installed packs it fails (225 differences, Virunga 20 of 31
colours); on the DD2FIELDS1 rebuild it passes. Limits: classes' per-rank palettes are not checked; the audit proves the
file holds the source value, not that the game uses it (native acceptance is separate).

## DD2 cut-ins keep their proportions (`dd2_cutin_audit`, DD2CUTIN1, 2026-11-25)

The DD2 importer handed `nativeimports._portrait` / `newclasses.set_portraits` the whole 128x544 source cut-in page and
both resized it over the 336x1080 D5 cut-in texture: x 2.62, y 1.99, the strip's aspect 0.230 became 0.311 (12 of 12
packs, 32 cut-ins), and a class gave every rank rank 0's strip. Format facts, measured (Research/source-format/DD2-*.md,
DD2-SPR-07): the cut-in is `ANM_HI` member `anm<10000 + id (+ rank for a class)>`, one 128x544 texture whose drawn cell
(motion 8000) is **125x544 at x=1**; classes have a strip per rank (12020..12025). D5's own cut-ins fill the whole
336x1080 texture (opaque bounding box 0..335 x 0..1079 on every one checked), so the slot is a full-bleed strip.

What D4, D1C and Disgaea RPG do, for the choice: D4's cell is 390x1248 (aspect 0.3125, 0.45% from the D5 strip), D1C's
authored cut-ins are 336x1080, Disgaea RPG's are 260x836 (0.311): all three are already the D5 proportions, so a plain
resize is a uniform scale for them. DD2 is the only game whose strip is narrower (35%).

`imgtools.cutin_placement` / `fit_cutin` (mode `contain`): the drawn cell is scaled with ONE scale to the texture's
height (125x544 -> 248x1080), centred across, transparent on both sides (44 px). It loses no source pixel (scaling to
cover would crop 26% of the picture's height) and invents none (no edge fill). Pictures within 2% of the texture's
aspect still fill it, so D4/D1C/DRPG output is unchanged and mode `stretch` is byte-identical to the old resize
(tested). The DD2 importer passes `contain` and the drawn cell plus each class rank's own strip (a rank without one keeps
rank 0's) when option `dd2_cutin_fit` is on (default; recorded in `mod.json`; `tools/import_game.py dd2
--no-dd2-cutin-fit` = the old path, byte-identical to the installed banks). Bank shape unchanged: same files, same
336x1080 + 32x32 textures.

The gate: `python tools/dd2_cutin_audit.py --mods DIR --gate` (logic `d5lib/dd2cutinaudit.py`; importer gate `cutin_fit`)
measures every cut-in bank of every `DD2_*` pack: one scale on both axes, nothing cropped, the picture equals the source
resized by that scale, every pixel outside it transparent, and rank k of a class holds rank k's strip. The position is
searched, not assumed. Against the 12 installed packs and the old-path build it fails on all 48 banks; on the new build
it passes (worst mean difference 0.00 of 255). Limits: the audit's source cell comes from the importer's own cell
reader (the independent check is `Tools/source_readers/dd2/compare.py`); nothing shows how the game draws a strip
narrower than its texture, which only a native look can settle.
