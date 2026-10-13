# D5 Mod Kit — changes

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
