# Overloads

Make new Overloads for any character (the game's or a new one), or change the game's own: name, description, what
it does, its numbers, its animation and its title banner. Everything is on the **Skills & Animations** page: pick
the **Overloads** category (or press **⚡ New Overload…**), then the **⚡ Overload** tab. The animation is edited
like any skill's (Timeline editor, Choreography, *Use animation of…*, *Make editable copy*, *▶ Preview in game*).
Backend: `d5lib/overloads.py`.

## What an Overload can do

* **Works like a game Overload**: it runs that Overload's code — giant and stats (Super Olympia), extra actions
  (Tyrant Revelio), revive, control, steal, illusion … — under its own name, description, banner and animation.
  Any number of new Overloads can do this.
* **Numbers of its own**: it hits its area with its own skill row — kind (physical / magic attack, heal,
  ailment / stat down), power %, element, area (the user, within 3 or 5 panels, the whole map) and up to six
  effects (`type:value`, e.g. `1:300` damage +300 %, `21:100` Poison, `11:-50` ATK -50 %). Start from a copy of a
  game Overload's numbers (Ground Zero Wolf, Comet Disaster, Devouring Kris, Indomitable Spread …). Areas hit what
  the game's Overloads with that area hit: *within 5 panels* hits every unit there, allies too (as Ground Zero
  Wolf does — the target screen warns "Ally unit in range").

A game Overload can be changed the same way (rename it, give it numbers of its own, make it work like another).
**↺ Undo the active mod's changes** puts it back.

## Who has it

**➕ Give to character / class…** on the ⚡ Overload tab (a class: every rank), or the Overload box on
*Characters & Classes*. A character has one Overload. Overloads of the main cast are normally held back until the
story unlocks them; for every character a mod adds or edits they work at once (`d5lib/unlockpatch.py`).

In battle an Overload needs **Revenge Mode** (the unit's revenge gauge full), as in the game.

## Title banner

While an Overload plays, the game shows its name in a banner at the top of the screen; those names are pictures.
A new Overload — or a game one you rename — gets a picture of its own at install: its name drawn like the game's
(a two-colour gradient, a thick black outline and a shadow, in Arial Rounded when Windows has it) in the banner
style of a game Overload you pick (the lightning bar and its colours), or **a picture of your own** (any size, a
transparent background; it is fitted to the banner's height). The tab shows a preview.

## Capacity

* New Overloads: ids 300 .. 29 999.
* With numbers of their own: 208 in all, every mod together (skill ids 3048 .. 3255 — the game keeps per-unit data
  for the Overload skill range 3000 .. 3255 only). Overloads that work like a game Overload don't count.
* Banner pictures: hundreds per texture, several textures (they grow as needed).

## How it works (for the curious)

Traced in the game, 2026-10-12 (`docs/EXE_ANALYSIS.md`, "Overloads"):

* `char.dat` +0xCC (u16) is the character's Overload id. `OverlordSkill.dat` (binary-searched by id) holds the name,
  three description lines and the event that plays it (`script_id`; `script_id + 100000` when animations are cut
  short — the game's call the generic 15012900). A new Overload's event is 13270000 + id (13370000 + id the short
  one), a one-line wrapper that calls its animation.
* The battle side is a `magic.dat` row of skill type 4: `0x1401dd050` maps Overload 1-19 / 100-114 / 200-213 to
  magic 3000-3047. The kit's hook maps new (or changed) ids to their skill row.
* `0x140163bf0` switches on the Overload the unit is using (battle record +0xe60) and runs its code: specials keep a
  timed state keyed by the skill id (3003 = Super Olympia's giant and stats …) that stat, AI and display code check
  all over the exe; damage / heal / ailment Overloads apply their skill row (the case shared by 16 / 18 / 103 / 105
  does only that, through placeholder skill 3603). A new Overload's id is turned into the one it works like there
  and in the few checks that compare Overload ids (charm / control males, giant size, Future Eyre, the AI's "may it
  be used now"); one with numbers of its own takes the generic case.
* `0x1404b2fc0` picks the banner: animation 100 .. 500 of the UI block 9032 (resident pack, one per language),
  which shows the name picture 1000 + that value. New banners are animations 2000, 2002 … with their picture in
  rows added below textures 7 / 8 / 4 of the block (`facepatch.add_overload_banners`).
* Revenge Mode: unit +0x35bc (u16 gauge) == 10000.

Tested in game: a new Overload working like Super Olympia (giant, +40 % stats, 3 turns, Killia's animation, its own
banner) and one with numbers of its own (a star blast within 5 panels with Ground Zero Wolf's animation: every unit
in range was hit).

## Sharing

Shared mods with Overloads move their ids when they clash with another mod's (`d5lib/modshare.py`, kind
`overload`): the Overload id, its script id, its own skill row (within 3048 .. 3255), the characters having it, its
animation and banner picture.
