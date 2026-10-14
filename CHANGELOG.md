# D5 Mod Kit — changes

## 1.4 (2026-10-14)

**Outfit colours without blotches**
* The extra colours of outfits and new characters (Strategy Assembly › Change Colors) had patches and squares in
  the hair, faces and clothes: Disgaea RPG's compressed art stores one colour as small blocks of slightly different
  shades, and those shades could change differently. Now shades that touch and look alike change alike, so every
  part takes its new colour in one piece.
* Her skin stays skin: a shade the artist used both on the skin and elsewhere (Pram's face highlight is the white of
  her hair) now has a twin for the skin, so a red variant no longer paints her face red. Outfits are checked once
  (where their drawing lies over the character's own skin); the default look doesn't change.
* All included outfits and characters were re-derived (`tools/rederive_colors.py --skin`); outfits you made get it
  from Outfits › Colors › *Re-derive color presets from the character*.

**Clearer lists**
* Outfits: one entry per character with its outfits inside (fold it open), and a search box. ✨ New outfit starts on
  the character whose outfits are open.
* Characters & Classes: in sections — your new characters & classes first, then the game's unique characters,
  generic classes and monster classes (one entry per class, its six ranks inside) and the others. The copies of a
  character that outfits make, and the game's empty reserved rows, aren't listed (filter *Outfit copies* shows them).

**New characters (fixes from testers' reports)**
* A new character could get the id of one of the game's empty reserved rows (970 "DLC Dummy") as a SECOND row: the
  game read the dummy's, so the character showed "DLC Dummy" with the dummy's stats, resistances, weapon mastery
  and "DLC Dummy Description Row" text around the new sprites. New characters now fill the reserved row itself, and
  characters made with an older kit are repaired when the kit or the game reads them (Install again).
* New characters no longer get ids whose numbers the game's own files use (id 11 sat on Killia's sprite files: the
  wrong small sprite and no status portrait). Every new character gets its small standing picture (menus, the quest
  shop's "has joined") at install.
* A new character always gets its own description (its name and title when none was typed), never the copied
  character's or the reserved row's.
* Characters & Classes: **Description** box (3 lines, wrapped; saved alone too), **Gender** (some evilities and
  skills check it), **🖼 Portrait…** (the status screen / skill cut-in picture of a new character) and **🗑 Delete
  this character…** (its row, description, recruit quest, sprite files and face; makes room to create it again).
* Name and title edits change every game language that still had the old text (a game in French showed the old
  name).
* Imported portraits and cut-ins: the plain white background left along the sides and bottom (beside an arm or the
  hair) is removed too; shaded white clothes stay.
* Stages & Maps: a stage the story also plays as its "(Demo)" version says so (its own map and base panel: the
  story's first battle on 1-1 is the Demo stage). Checked in game: the base panel moved in the editor is where the
  units enter.

**Contributions**
* Original Disgaea RPG idle timing for outfits (Sean13128, pull request #3): `tools/rpg_idle_sources.py` exports the
  idle clocks from your own Disgaea RPG game files, `tools/repair_outfit_idles.py` makes an override mod
  (docs/RPG_IDLE_TIMING.md). Without the exported files nothing changes.
* The editor runs on macOS (Sean13128, pull request #2; docs/MACOS.md).

**Fixes**
* Axel's *Netherworld President* outfit showed Rozalin, and Rozalin's *Hero* outfit a girl from Yomawari: the Disgaea
  RPG units list names units 405-407 one place off. Both outfits are drawn again from the right units (same outfit
  slots, so units wearing them keep them), and the unit browser shows those three units' real names.
* A new character's description longer than a help line made creating it fail ("line1_JP: 111 bytes > 91
  available"); the text is now wrapped onto the game's three 42-character lines.

**Skill editor: closer to the game**
* Every skill was run through the editor's preview to list what it didn't draw yet; the most used commands were
  traced in the game's code and now play as in the game. 66 skills (was 50) now use only commands the preview draws.
* Hurricane Blow: the enemy spins in the whirlwind (units turning, `6710`, in 170 skills, now turn and show the right
  view of their sprite).
* Purgatory Palm (and 8 more skills): its effects shown at a unit itself now appear.
* Effects that ride along with a fighter (Exploding Tiger's flames and many more) now move with it, and a unit set
  to follow another keeps its place instead of jumping onto it.
* Sprites shifted or scaled step by step, and effects resized relative to their size, play as in the game.
* Fixed: sprites turning around their own centre (Macrocosm's juggled enemy) had stopped turning in the preview.

## 1.3 (2026-10-13)

**Disgaea RPG sprites in the editor, no command line**
* Outfits › **✨ New outfit** › *Disgaea RPG sprites*, and Characters & Classes › **✨ New character / class…** ›
  Look: *Disgaea RPG sprites*: pick a unit and the kit builds the outfit, the new character (with its recruit quest)
  or the new class (its own mod, 6 ranks) by itself, in the background.
* The unit browser: choose your Disgaea RPG folder once (*What goes in this folder?* shows the layout), search units
  by name or number with their faces, and see at a glance what each one has: ✅ for each of the four sprite sheets it
  needs (battle and idle, front and back), the optional face and cut-in, and whether it can be used.
* *Use my own sheet files…*: four sheets in Disgaea RPG's layout from anywhere, each checked as you pick it.
* *Moves like*: a new character or class takes the animations of a game character or class you choose.
* Afterwards the kit says what to adjust by hand if something looks off (weapon grips, colours, another *Moves like*).
* Characters & Classes explains that *Sprite file (anm number)* picks an existing sprite, and where new looks are made.

**Sprite sheets, clearly**
* The sprite-sheet dialog (New outfit › *Convert a sprite sheet*) now lists every animation the game uses, what it is
  for (standing, idle, walking, getting hit, each weapon's attacks, spells and items …) and whether your sheet has it
  from the front and the back. It marks the four every character needs and explains what happens to the rest.
* New characters can take a sprite sheet too: ✨ New character / class… › Look: *A sprite sheet* (unique characters).

**Fixes**
* A new character or class made with "its own copy of the sprite" could get a sprite number another of your mods
  already used, so one sprite replaced the other at install. New sprite numbers now skip every mod's.

## 1.2 (2026-10-13)

**A faster, smoother kit**
* No more stutter every few seconds: the "are my mods in the game?" check ran on the window's thread every 2.5 s and
  read every mod's file list (0.15 s here, more on slower disks). It now runs in the background.
* Pages open faster and coming back to a page is instant (under 0.1 s; Outfits took 1.4 s every time, Home 0.2 s).
  Textures (4 s → 0.4 s) and Music (1.8 s → 0.2 s) no longer re-read every mod for each list row.
* Event Scripts (10-20 s) and Skills & Animations (5-6 s) open at once: the game's 19 053 scripts are read once, in
  the background, shortly after the kit starts, for both pages.
* Fewer random pauses: Python's memory clean-up passed over everything the kit keeps (0.2-0.5 s each time, many
  times while a page loaded). It runs far less often now and skips what pages keep.
* Texture thumbnails are made in the background, and the big font textures decompress about 24x faster.
* Opening Skills & Animations for the first time no longer makes the whole window flash and redraw.

**Music & Sound**
* Previews play like the game: the intro once, then the loop part over and over (no more skips at the join).
* The second "542" was a song the game never plays (it sits in an archive the game doesn't load). It is now labelled
  "not used by the game", plays when you pick it, and can't be replaced by mistake.
* The window title shows the right version again (1.1 still said 1.0).

**Cleaner Disgaea RPG looks**
* Extra colours (the Strategy Assembly's colour options) of every outfit and new character were redone: each piece of
  an outfit now follows the matching part of the character's own extra colours (her hair, her clothes, her skin), in
  whole pieces -- no more speckles of another colour inside a cape or a crown, no skin turning blue with a coat.
  Checked against the game's own classes, whose Disgaea RPG versions are the same drawings: the new extra colours
  are as close to the artist's as the default colours are (the old ones were 3-4 times further off).
* New Disgaea RPG outfits and characters get a better palette (eyes and highlights keep their own colours).
* Sprite previews (Outfits, Characters & Classes, the animation on Sprites & Colors) are drawn smooth, like the game
  draws them, instead of in hard square pixels. Sprite sheets and painting keep hard pixels.

**Music: new tracks**
* Music & Sound → ➕ Add new track…: your song under a new track number (600 and up), next to the game's instead of
  replacing one. It can be listed in the game's music list (always available) and plays wherever its number is used
  (a stage's music, an event script's bgm_play). Revert removes it.

**Updates in the kit**
* The kit checks GitHub for a newer version a few seconds after it starts (Home: *at start*, or *Check for
  updates*). A bar offers **Update now**: only the files that changed are downloaded, your own mods and settings
  stay, and a shipped file you edited is backed up first (state\update_backups). From 1.2 on; 1.1 needs this
  download once.

**Profiles (separate modpacks)**
* Home → **Profile**: keep several modpacks side by side, like the profiles of Mod Organizer for Skyrim. Each
  profile has its own mods switched on and its own load order; the mods themselves are shared, so switching is
  instant. **Install** puts the chosen profile's mods into the game, and the status box says when the game has
  another profile in it. New profile, Copy this profile, Rename and Delete are next to it (a deleted profile is kept
  in state\deleted_profiles).
* **Separate saves** (Profile ▾, optional): a profile can keep its own saves, for a modpack whose saves need its mods.
  Its saves go into the game when it is installed (and when you press Play), the others' are put aside meanwhile.
  Start it with a copy of your saves or a new game; nothing is ever deleted and every switch keeps a copy in
  state\save_backups. Only the save files move: your game settings and key bindings stay.
* Your mods list from 1.1 becomes the profile *Default*.
* A save with a unit from a mod that is switched off (a recruited character, an outfit class) made the game crash entering a battle, without a word. Now the game shows *Save needs a mod that's off!* when such a save loads, and Home names the unit and its mod ("Your save has units from mods that are switched off in this profile: Future Usalia (mod 'DRPG Human Usalia')").

**Every PC copy of the game, Steam's current one included**
* The kit installs on the Steam version as it is today (the January 2019 update with Chinese and Korean) as well as
  on the October 2018 launch build: outfits, new characters and classes, colour slots, Extra Color 4, skills and
  the kit's in-game features all work on both. Verifying the game files in Steam is no longer needed (or helpful).
* Builds the kit hasn't seen are matched by themselves: the kit finds the game code it changes by its shape. A change
  it can't place there is left out of the install and named in the log; everything else installs.
* One kit can look after several copies of the game: each game folder keeps its own backups of the original files
  (state\games), so switching the game folder on Home can't mix them up. Your 1.1 backups move to their game folder
  on the first start.
* **Copy compatibility report** (Home) still says which build a game is, for the kit's author.

**Stages & Maps**
* Stage entries whose map the game files don't have (Companion Zone (Demo), the dummy and demo stages, places the game
  builds itself) are marked in the list and explain themselves instead of failing to load.

**No duplicate outfits**
* Girl Laharl Outfits no longer lists the four Thunderlady looks (Thunderlady, Beach, Groom, Young Thunderlady):
  they belong to the Thunderlady character. Girl Laharl has 9 outfits. A unit already wearing one of those looks
  keeps working (the looks stay in the mod, just off every list).
* Outfits a mod hides are left out everywhere in the kit too: the Outfits page, the mod list's counts and the
  character studio's "outfit as a character" list.

## 1.1 (2026-10-12)

**Overloads of your own** (docs/OVERLOADS.md)
* New Overloads for any character, game or new: name, description, an animation edited like any skill's, and a
  title banner with its name (drawn in a game Overload's style, or a picture of yours).
* What it does: the code of any game Overload (giant, extra actions, revive …), or numbers of its own (damage /
  heal / ailments with its power, element, area and effects). The game's own Overloads can be renamed and changed
  the same way. Skills page → Overloads → ⚡ Overload tab, or ⚡ New Overload….
* Shared mods move clashing Overload ids like the other ids.

**More classes and unique characters**
* New generic classes are no longer limited to the game's 21 reserved class slots: **119 classes** (73 humanoid,
  46 monster) in families of their own, with the game's class checks, team-attack table and monster pictures
  extended to them (tested in game: hire, lists, battle). The reserved slots past the first few — which the game
  itself would not have shown — now work too.
* Unique characters and unique characters' outfits: **714 ids** (was ~550).

**Weapons and idles**
* Outfits, new characters and new classes no longer hold their weapon while standing, waiting or walking: it
  appears when they attack or use a skill. Weapon Grips → *Hold the weapon when not attacking* keeps it in hand (the
  Onmyo Monk and Beast Master, which had grips set up, keep theirs). The Weapon Grips page now lists the Disgaea RPG
  outfits numbered 10000 and up too.
* Santa Liezerota's back idle is her own Disgaea RPG idle with her hair layered behind her, instead of a still
  upright pose. Layered idle sheets (body + hair / cape pieces) are told apart automatically.

## 1.0 (2026-10-11) — first release

**The studio**
* Editors for characters & classes, outfits, the database (all 90 tables), dialogue, stages & maps, sprites &
  colours, weapon grips, textures, music & sound, event scripts and every archive; mods kept separate, switched on
  and off, installed in about a minute and restored byte-exact.
* **Skill editor**: plays any skill inside the kit as the game draws it (camera and lens, effect models, depth,
  particles traced from the game's code, sounds) and lets you retime, move and swap effects, camera, motions and
  sounds, give a skill another one's animation, or preview edits in the running game.
* **Character studio**: an outfit's look becomes a new recruitable character (stat presets or copied numbers,
  skills, evilities of its own, Overload, outfits), connected to the skill editor.
* **Mods on Home**: categories, packs, readable contents; **sharing** between kit users with ids moved safely so
  saves keep working, and one-file installers for players (`tools/export_pack.py`).

**Mods included**
* Outfit System, Girl Laharl Outfits and Disgaea RPG outfits for 24 more characters.
* **Thunderlady**: Girl Laharl's lightning alternative as a character of her own — her skills redone as lightning,
  her own stats, weapon masteries, resistances and evilities, and the Thunderlady outfits. Quest *The Thunderlady*.

**No limits on what the kit makes**
* Effect models load when a skill shows them, so mods can add any number (the game alone holds 400 and crashed at
  start past that); new effect ids 3000 .. 32767.
* Custom skill animations: 7 100 (was 100). List icons and faces grow their textures as needed (were 252 / ~300).
  New sprites ~1 750 (was ~1 150). Custom voices 4 000 (was 900).
* Limits that come from the game: unique characters and unique characters' outfits share the ids below 1000 (~550),
  new generic classes use the game's 21 reserved class slots, a save keeps 1 024 quests.

**Known limits**
* The skill editor's preview differs from the game in a few places (listed in `docs/SKILL_EDITOR.md`, "What is
  still approximate").
* Brand-new stages can be cloned, but how the game unlocks and lists them isn't fully known yet.
