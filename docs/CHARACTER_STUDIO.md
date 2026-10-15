# Character studio

Everything that makes a custom character, on the Characters & Classes page (`d5gui/pages/characters.py`), backed by
`d5lib/charstudio.py`. Every change goes into the mod that makes or changes the character (the mod chosen bottom left for the game's own characters no mod changes); new ids are free ones, so saves keep working.

## New character / class (wizard)

* **Template**: the selected character or class; the new one copies its row (stats, skills, evilities, Overload).
* **Look**: the template's (with its own copy of the sprite to repaint) or **any outfit** of the enabled mods
  (`charstudio.outfit_sources`):
  * a Disgaea RPG outfit (its mod's `drpg_units.json` names the unit) is drawn again as a complete character from
    that unit: `outfits.create_drpg_character` (the template's whole animation set, face, portrait, cut-in);
  * another outfit: its char.dat row and sprite files (N .. N+2, portraits 10000 + N, own animation set, colour
    parts, face) are copied under a new character id and sprite number (`charstudio._copy_outfit_character`).
  * **Take that outfit out of the Outfit menu**: the new character's mod lists the outfit in its `outfits.json`
    `"hide"`. The outfit stays a member of its group (a record with label 0, like legacy ids: identity, faces,
    switching back to Default all keep working); it is only not listed. The outfit's own mod is never edited, and
    switching the character's mod off brings the outfit back.
* **Stats**: the template's or a preset (`charstudio.PRESETS`: the numbers of one of the game's playable characters
  -- Killia, Red Magnus, Christo, Usalia, Zeroken, Seraphina, Flonne, Laharl).
* **A new mod of its own** (default): one character = one mod (category "characters"), easy to share and update.
* **Recruit quest**: objective copied from "Combat Lecture"; the recruit hook creates the unit.

## Shaping it

* **Quick setup**: *Apply preset* (base stats, aptitudes, movement), *Copy from another…* (`charstudio.copy_fields`:
  base stats, aptitudes, movement & combat, weapon mastery, resistances, evilities, Overload, learned skills of
  any character or class; base stats at a power %).
* **New skill of their own** (`charstudio.new_skill`): a magic.dat row copied from any skill (numbers; its animation
  through `skills.inherit`), id next to the character's own (unique skills are 10000 + class id + n, e.g. Killia's
  10011-10014; else 13000+), learned at a level in a free slot. The skill editor can open on it
  (`SkillsPage.open_skill(sid, back=(id, name))`); its **↩ Back to …'s setup** button returns to the character.
* **New evility of their own** (`charstudio.new_evility`): a Skill.dat row with its own name and description
  (owner = the character, kind 1 = unique, id next to the character's: Killia's are 10 and 11), put into one of the
  four evility slots. In game it works like the evility it names: `patches/evilities/aliases.json`
  `{"new id": existing id}`, the evility alias hook of `d5lib/newclasses.py` (0x14021878C; it now runs for these
  too, not only for new classes). Its numbers are the named evility's.
* Evilities, Overload and learned skills are searchable lists with hover descriptions; the story locks on them are
  removed for every character a mod touches (`d5lib/unlockpatch.py`).
* **An Overload of its own**: *Skills & Animations* → **⚡ New Overload…** makes one (the code of a game Overload or
  numbers of its own, its own name banner and animation); give it to the character there or pick it in the
  Overload box. See docs/OVERLOADS.md.

## Sharing

**📤 Share this character…** exports the mod holding the character (`d5lib/modshare.py`, see docs/SHARING.md):
others import it, a later version installs as an update, clashing ids are moved and remembered.

## Verified in game (2026-10-11)

With a test mod installed over all the other mods: a new character from Killia's DRPG "Formal" outfit (with the
outfit hidden) and one from Girl Laharl's "Swimsuit" (copied sprite) were created by the game's own unit creation,
show in the character list with their faces and list icons, and fight with their own sprites; Killia's Outfit menu
no longer lists "Formal" while Killia, wearing it, keeps it and can switch back. The active evility lists read in
battle: the new character's own evility 253 plus War Demon (10) it works like; Killia's new evility 17 plus Mass
Blaster (1210) -- through her outfit row (outfit rows follow their character, docs/OUTFITS.md). Killia's new skill
"IGT Fist" (10015, a copy of Exploding Tiger) is in her Special list, plays the animation and deals damage.

## Example: Thunderlady (mods/Thunderlady)

Made entirely with the studio's functions by `_research/make_thunderlady.py` (it remakes the mod; the ids come out
the same each time): Girl Laharl's "Thunderlady" outfit as character 253 "Thunderlady — Storm Overlord" with a
recruit quest, her other Thunderlady outfits (Beach, Groom, Young) as her outfits and hidden from Girl Laharl's
list, stats leaning to SPD / INT, her own weapon ranks and resistances (wind +50, star −25), two evilities working
like Overlord's Dignity and a paralysis-on-attack one, and Girl Laharl's four skills as wind-element copies whose
animations `fxrestyle.restyle_skill(..., "lightning")` moved from fire to lightning (recoloured effect models and
script colours, coloured copies of the greyscale models the game paints orange, lightning strikes at the hits).

Verified in game (2026-10-12): created with the game's own unit creation at level 200, list icon, face, Status
(stats, aptitudes, resistances, weapon ranks), both evilities in her unique slots (the paralysis one paralysed a
Prinny), all four skills in her Special list as Wind and cast in battle with damage: Thunder Knuckle and
Thunderlady's Wrath are blue / white lightning from start to end, Thunder Dimension keeps Girl Laharl's black-and-white
dimension with blue lightning rays (and its red-and-yellow warning sign, an object picture), Thunder Impact is blue
space and a blue meteor, and the screen flashes blue as the camera flies into it (Girl Laharl's flashes orange: the
screen fade colour `screen_color 100, 50, 0`, which the restyle now recolours). Her skills' effect models load on
demand (d5lib/fxpool.py).

## Not possible / not yet

* An evility's own numbers (it uses the named evility's values).
