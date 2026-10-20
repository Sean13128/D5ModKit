# D5 Mod Kit — changes

## 1.5.6 (2026-10-20)

**Music**
* **New tracks show up in the in-game music list.** The list shows a track only when the save has it unlocked, and
  the game copies a track's "always available" setting into the save only when a new game starts: a track a mod
  added stayed out of every existing save's list (until something played it). The install now patches the list
  (code section `.d5ml`, only when a mod adds tracks) so a track marked always available is listed in every save.
  Tested in the game: an added track shows in the Data Shop's Music Records of an old save and plays.

**Characters**
* **Portraits of new characters show on the Status screen.** The Status screen and the skill cut-ins draw the
  portrait of the character's *sprite* (anm sprite + 10000), and **🖼 Portrait…** wrote the one of its id (anm
  10000 + id): a new character with a look of its own kept its old portrait there. The install now gives the sprite
  the same picture (when no other character shares that sprite; if one does, Portrait… says so).
* **No Status screen crash for a look without a portrait.** A character given a sprite that has no portrait file
  (a look copied from an outfit without one, a sprite number typed in) crashed the game on its Status screen. The
  install now gives every such sprite a portrait (the character's own, else its colour's) and says so in the log,
  drawn at the game's portrait size.
* Tested in the game: a new character's own portrait shows on its Status screen; a character on a sprite without a
  portrait opens its Status screen without a crash.

**macOS** (contributed by Sean13128, pull request #5)
* The 3D Stages & Maps view is no longer blank (a shared OpenGL 4.1 context), and the kit uses the system's font
  sizes, so text isn't tiny. Windows is unchanged.

## 1.5.5 (2026-10-19)

**Stages & Maps**
* **Several units at once.** Ctrl+click adds a unit to the selection (or takes it out), Shift+drag draws a box,
  Ctrl+A takes every unit shown; on the flat map and in 3D. Drag one of them and they all move (only where every one
  of them finds a free panel), the arrow keys nudge them, Delete removes them, Ctrl+D copies them. The panel on the
  right edits them together: class, level (set, add, or a % of their own), facing, team, AI, the visit they appear
  on, equipment (item, level, rarity) and stat modifiers; *Same class / Same team / All enemies* select more.
* **Undo / redo** (Ctrl+Z / Ctrl+Y) of unit and Geo Panel edits.
* Tested in the game: a stage's enemies changed together (class and level) fight that way.

**Skills & Animations**
* **🟥 Area Shapes**, a page of its own for AttackMap.dat: every area shape with the skills that use it, painted
  panel by panel. The panels are numbered in the order the game hits the units on them (1 = the main target): paint
  them in that order, or renumber with the **#** brush (click panels in the order you want) or **Renumber** (nearest
  first, front row first …). Brushes for the cursor's panel and where the caster ends up, right-click erases,
  Shift+drag paints a straight line, turn / mirror / shift the whole shape, undo / redo. **New** and **Clone** make
  shapes of your own, **Revert** gives a game shape its panels back (changed panels are outlined), **Used by** opens
  the skills, the JSON tab shows / takes the panels as text, shapes get names and notes.
* The Area tab of a skill paints with the same brushes and numbers.
* Tested in the game: Triple Strike given a new painted shape aims and hits with it.

**Database Editor** (ideas from the Disgaea 5 *Overlord Edition* table editors)
* **A record panel** next to the grid: the selected row as a form, every field with what it means, references as
  searchable pickers, texts with their byte count and limit; **Used by** (the rows of other tables that point at
  it, double-click to go there), **Raw** (its bytes) and **JSON**.
* **⌕ Go to any record (Ctrl+P)** across every table by name or id, **← →** back and forward, **undo / redo** of row
  changes, **💾 Save all**.
* **✔ Check table**: what would crash the game or look wrong -- rows with the same id, references to rows that
  don't exist, texts too long for their field, tables the game binary-searches out of order, and Skill.dat's
  evility rules (a generic class's evility owned by a character crashes the Skill Shop; unique evilities with a
  slot cost …).
* **Evility presets** (Skill.dat): a character's unique / learnable, a class's unique / learned evility, with its
  owner, in one click. **Sort new rows** puts your added rows in id order.

**Characters & Classes**
* **🐉 New monster class…**: a recruitable monster class drawn from a Disgaea RPG monster (the ten D5 doesn't have, or
  any of the 21 it has, in their Disgaea RPG look), without the command line. Pick the monster; the kit proposes
  whose moves it uses (its D5 twin, then the monster closest in height), guesses which drawing is its stand, walk,
  hit, crouch, jump and attack from the template's own poses, and lets you fix each one; **Preview** shows every
  template pose next to the drawing it gets. Made again later, it redraws the same class. Only monster classes are
  offered as templates (Usalia, a story character, was in the list).
* Tested in the game: a Gargoyle made with the wizard on Dragon King's moves stands, walks, attacks, takes hits and
  counters as an enemy, with its own portrait on the status screen.

**Game performance** (report: menus such as the Quest shop getting slower after some stages)
* Measured on the Steam game with 33 mods: the Quest shop stays at 60 fps after a series of stages, the game's memory
  stays flat (about 2.47 GB) and the kit's runtime costs about 0.03 ms a frame; the slowdown didn't show on the test
  PC. To find it where it happens, the runtime now writes to d5auto.log: the memory every 5 minutes and with every
  slow stretch, and during a long one (20+ frames over 40 ms in 10 seconds) a 2-second sample of where the game's
  time goes (at most 6 a session).
* **Home page**: after a session that ran slowly, a note (how slow, and whether the memory grew) and **📋 Copy lag
  report**, the lines to send with a report.

## 1.5.4 (2026-10-18)

**Stages & Maps**
* **Blocks are lit like a story stage.** The Item World's pieces carry the Item World's light (a grey material at
  half strength), so a battlefield built from them came out very dark in game while the editor showed it bright.
  The blocks now get the story maps' material (the Blocks panel's **Light** can keep the Item World's). A stage
  built with 1.5.3 or older gets the new light when it is opened: Save keeps it.
* **No more second layer of terrain.** A battlefield started from "this terrain as one block" cut that block out
  of its own map file, which every save rewrites: once reopened, the blocks placed before came back inside the
  cut-out (a lifted block showed twice, at its old height and its new one). The terrain it starts from is now kept
  beside the build. A build made with an older kit says so and offers **Original terrain…** (the map it was made
  from). The whole map's scenery around its panels comes along too (a third of it was cut away).
* **Under a lifted block**: *Solid* (its walls go down to the ground, now cut at the ground instead of hanging below
  it) or *Platform* (nothing under it). In the Blocks panel and the block's right-click menu.
* **Netherworld effect** per stage (*In the game's stage list*): Snow (Water resistance -50 %), Gale Force Winds
  (Wind), Fire Powder (Fire), Sandstorm, EXP / HL / Mana Up, Auto HP Recovery … -- dungeon.dat's "weather" field is
  the stage's Netherworld skill (MakaiSkillDataBase), with its falling snow / wind / embers. Its **Amount** can be
  changed (for every stage with that effect).
* **Enemy equipment: item level and rarity.** Each slot of a unit's equipment has its item level (the stage file had
  it all along) and a rarity (Common 0-24, Rare 25-49, Legendary 50-99, 100; or Random, as the game rolls it). The
  rarity needs an exe patch, made at install when a mod's stage uses it.

**Skills & Animations**
* **Spell tiers set the reach, not the shapes** (corrected after testing in game). A level 9 Fire with the tier
  levels moved to 1-8 hits 9 panels away, as the Area tab said. But how many of the nine spell shapes a unit may pick
  is kept with that unit's spell (one at first; levelling up doesn't change it), not set by the tier: the Area tab
  now shows every shape and says so.

**Install**
* **Exe patches no longer go missing.** The install's last steps ran in the order their code was first loaded, and
  the outfit step starts again from the game's original exe: a page that loaded first (the Stages page loads the
  enemy-rarity code at start-up) had its patch dropped. The install now runs them in its own fixed order (found
  while testing: the spell tiers and enemy rarities weren't in the exe).

**In game**
* **Menus with many lines are smoother.** The kit's screen-text hook asked Windows whether every string a menu drew
  was readable (two system calls per line, every frame: the Quest shop, the stage list and the character list draw
  hundreds); it now remembers the memory it has checked. The custom-colour hotkey no longer polls the controllers
  every frame outside the colour editor, and empty controller slots are asked only every 2 seconds.
* d5auto.log notes slow frames (over 40 ms) with the screen they happened on, and the kit's own time per frame
  (seen in game: the kit takes about 0.03 ms a frame).

## 1.5.3 (2026-10-18)

**Quests**
* **📜 Quests**, a page of its own: every quest of the Quest shop and every resident request, with its title, client
  and text, what it asks for (a stage to clear -- yours too -- or enemies to defeat), what it gives (HL, an item, an
  evility, a skill, a character, a class, a Chara World rank, a flag), when it shows (after another quest, a flag) and
  the stage it opens. **New quest** makes one of your own; a quest of yours can be deleted. Saving with no mod
  active offers a mod named after the quest.

**Stages & Maps**
* **🗑 Delete stage…** takes a stage of yours out of its mod: its map, its stage-list entry, its battle start and
  music and its blocks (saves that listed it: Home › More › Check saves).
* Monsters idle in the 3D view like humanoids do (they stood frozen in their first pose); **Geo Symbols** are drawn
  as the game's Geo Symbol models in their colour (they showed as Zeroken, whose sprite number the Geo Symbol
  entry carries).
* **Textures no longer glitch after saving** a stage built out of blocks: the 3D view reused the pictures of the
  earlier terrain for the new one.
* **🎨 Look…** for a block: a tint, or your own pictures on its textures (the stone blocks: a 160×128 top picture
  and a 128×32 wall strip; themed blocks one square picture). The game's files hold no other skins for the stone
  shapes: all 151 share one texture pair.
* **Map size** when a stage starts from blocks (New stage › Blocks), and the Blocks panel's grid is called that.

**Sprites & Colors**
* **⏱ Speed…** is a setting, not a stack: 50 % twice is still 50 % of the animation's original speed (the original
  timing is kept with the sprite, so 100 % brings it back exactly).

**Skills & Animations**
* **Save saves the Area tab too.** Changes to a skill's area, reach and numbers no longer need the tab's own button:
  💾 Save (and ▶ Preview in game) write them with the timeline. With no mod active, the first save offers a mod
  named after the skill ("Skill: Heal", category Skills), so one skill's changes can live in a mod of their own and
  be switched off or shared alone; the mod list says which skills a mod changes.
* **Numbers** on the Area tab: SP cost, the main effect's strength (the damage / heal bonus, or a buff's amount) and
  the power of each of the 10 skill levels, with a fill-in by step and a *Preview at level* line.
* **Spells grow with their level, and the kit shows it.** Fire, Heal, Braveheart and the other generic spells take
  no reach or area from the skill table: in battle the spell's level sets a tier (levels 1 / 5 / 10 / 20 / 40 /
  60 / 80 / 90 end tiers 1-8, tier 9 after) that is the spell's reach in panels (+1 with a staff, some classes add
  more) and how many of the nine spell shapes the player may choose (1 panel up to 3×3). The Area tab now says so,
  previews the reach and shapes at any level, lets you **edit the nine spell shapes** (every spell shares them),
  **move the tier levels** (one setting for all spells; the install patches the game for it), or **give one spell a
  reach and an area of its own** (and take them away again). Before, editing a spell's area quietly did the last of
  these without saying so.

## 1.5.2 (2026-10-17)

**Stages & Maps**
* **The stage in 3D.** A stage opens as the battle shows it: its terrain with its textures, every unit standing on
  its panel as its own sprite (idling), the map's objects (boxes, barrels, cacti, pillars) as their 3D models, Geo
  Panels, the base panel, through the game's battle camera. The mouse
  turns, pans and zooms it (F fits the map, 1 the battle view, 7 from above); units and panels are clicked and
  dragged as on the flat map, which 🧊 3D switches back to.
* **🧱 Blocks: battlefields built out of blocks.** The game's Item World pieces (stone slabs, bars, steps, towers,
  pyramids and 17 themed sets: cracked desert, cyan ruins, snow, a Japanese town, checkered floors, ice…) and
  rectangles cut out of any map are placed on a grid, turned and lifted (a lifted block's walls grow down to the
  ground), moved and deleted, with the result shown in 3D as you go. New stage › *Blocks* starts one; a stage of
  yours made from a map can be built on too (its terrain as one block, or an empty grid). The blocks are saved with
  the map, so building goes on later.
* **First visit and revisits.** Many stages place other units once they are cleared: Dried Up Wasteland has Warriors
  the first time and Prinnies on the same panels after, Final Trial 5 flame dragons and then Lucky Boards. The map
  holds both sets (byte 0x17C of each unit: every visit / first visit / revisits). **Show** above the map switches
  between them, and every unit has **Appears on**. Before, both sets were drawn on top of each other: deleting a unit
  seemed to need two clicks, and new units were copied as "first visit only", so on a cleared stage nothing you added
  appeared and a stage without its revisit enemies was won the moment it started.
* Saving checks the stage: a visit with no enemy left, two units on one panel, a unit off the panels or on the base
  panel.
* **➕ New stage…**: pick the battlefield it starts from in pictures of every map (their own 3D terrain), name it,
  choose what it starts with (its units, only its objects, or nothing).
* **New stages in the game's stage list.** The game lists a stage in the episode of its map number once its story
  flag is set. A new stage gets a number of the chosen episode and the flag of the stage it is listed with; saves
  you already have get it when the game loads them. New stages also get the battle start of their base stage:
  without it the stage played no battle start at all. Install adds a new stage to the table the stage list reads when
  its cursor is on a stage (the game closed when the cursor reached a stage missing from it). Home › More › Check
  saves takes stages of deleted mods off a save. Older kits gave new stages map 90001, which is the game's own
  Unique Dungeon: **Move to another episode…** gives such a stage a proper number.
* Maps of every enabled mod are found and saved into their own mod.
* **Battle music** of a stage: every song of the game, or one of yours from Music & Sound (the song the stage's
  start event plays).

**Music & Sound**
* **Export…** saves a track as a WAV any audio editor opens, its intro and loop as plain .ogg files and its loop
  points (the game's file, two Ogg streams behind a small header, only opened in players like VLC).
* **Replace with my song… / Add new track…**: one song file (WAV, FLAC, OGG or MP3, no ffmpeg needed), its loop start
  and end set on the waveform, and **Hear the loop join** to check the jump. The kit cuts and converts it.

**Characters & sprites**
* **What a recruit quest asks for.** A new character's quest can ask to clear a stage (one of the game's or one of
  your own) or to defeat enemies of a class (*To finish it* in the New character dialog; *Change what the quest asks
  for…* under *How to get this character* later). A quest that needs a stage of a mod that is switched off can't be
  finished in game: Home says so, switching that mod off asks, and Install asks before going on.
* **Sprite sheets of any kind**: the kit finds every drawing on a sheet (fan sheets with drawings scattered on a
  background colour, several characters and effects mixed in) and you choose which ones are each animation, in order,
  with a live preview, flip, merge and hand-drawn boxes. Small sheets are scaled to the character's height. The
  choices are kept for the next time.
* **Monsters from a sprite sheet** move with their own animations. A monster drawn with the humanoid moves stood
  invisible in battle and showed up for one frame when it dodged.
* Animations of each game animation take the drawings you gave that animation (with free-size drawings a walk could
  pick an attack pose).
* **⏱ Speed…** (Sprites & Colors) makes an animation the sprite carries itself slower or faster, e.g. a Disgaea RPG
  class's idle that plays too quickly.
* New character: **Generic class** can always be chosen; with a unique character as template, pick the **class to
  start from**.

## 1.5.1 (2026-10-15)

**The kit no longer closes by itself**
* 1.5 closed at once, with no message, when a window or panel with a search box went away: Save or Cancel in
  🎤 Custom voice… (the "New custom voice" box), the New skill / New evility dialogs and the others with a search
  box, choosing another unit on Stages & Maps, rebuilding the Characters form, and quitting the kit. The new search
  boxes (1.5) still listened to such a box while it was being deleted; they no longer do.
* Should anything else go wrong in a button, a timer or a list, the kit now keeps running: the error shows in the
  log at the bottom and is written to `state/crash_log.txt` (send that file when reporting a problem). A crash of
  Qt itself leaves a trace in `state/faulthandler.log`, and a kit that can't start says why.
* Sound in the voice editor and the skill preview: an audio device that is unplugged or fails no longer stops the
  sound for good (the next sound opens it again), and a recording that can't be played is reported in the log.

## 1.5 (2026-10-14)

**Edits go into the mod they belong to**
* No more picking the right mod bottom left before editing. A change to something a mod makes or changes is saved
  in that mod by itself: edit Thunderlady and 💾 Save writes into the Thunderlady mod, whatever mod is chosen. That
  covers her stats, ranks, starting weapon levels, learned skills, evilities, description, recruit quest, face and
  portrait, her new skills and evilities (✨), her custom voice, and a mod's own skills on Skills & Animations (their
  editable animation is edited in its mod: no more "make that mod active"). When several mods change a game
  character, the last one in the load order gets it. Characters & Classes says where the shown character is saved.
* The box bottom left is now **New edits go to**: the mod for everything no mod has yet (the game's own characters,
  skills and data no mod changes, and new things you make). With none chosen, editing a mod's character no longer
  asks for a new mod.
* Earlier kits saved such changes into the mod chosen at the time, as a change of "row N" of the table, and row N
  is someone else when the mods or their order change (and such a mod, shared, changes a random character on
  another PC). Your mods are checked when the kit opens and these changes move into the mod that makes the
  character, with a copy of the files in `state/mod_backups` first; the game gets exactly the same tables. Here:
  Thunderlady's stats kept in the Henna mod, and Liezerota's kept in the Thunderlady mod.
* Saving no longer rewrites a mod whose changes are the same (it marked the game as needing an install).

**Search boxes find what you type**
* Typing in a skill, evility, Overload or character box (Characters & Classes, Skills & Animations, Database Editor
  and the other pages) now replaces the shown entry and lists everything containing the words: "star" lists Star,
  Mega Star, Giga Star … Before, a click put the cursor inside the shown name, so the search ran on a mix of both and
  found nothing; and a search left without choosing could set the slot to "nothing". Now it goes back to the entry
  that was chosen.

**Characters and outfits can't spoil each other**
* Sprite numbers 10000-12999 are the portraits of characters 0-2999 (10000 + id), and earlier kits could give an
  outfit or new character a sprite there. Etna's Lioness Princess (10970) was drawn as Killixia's portrait and over
  its own and the Supreme outfit's portraits. New sprites never get those numbers, new characters skip ids whose
  files a mod already uses, and new classes skip families whose portraits are taken.
  `tools/fix_sprite_numbers.py` moved the 141 included sprites that sat there (saves are unaffected: they refer to
  characters by id) and Etna's two outfits were rebuilt.
* Characters & Classes reloads by itself when mods are switched on or off, deleted or imported (the list kept old
  row numbers: other characters showed up under the wrong names, a deleted mod's character as "DLC Dummy"). Unsaved
  edits are carried over, the shown character stays shown, and **⟳** reloads by hand.
* **🗑 Delete this character…** works for a character of any mod: it is deleted in the mod that made it.
* A class entry holding a single row (Killixia's row kept for older saves) is no longer a fold with itself inside.
* ✨ New character from a character another mod makes (Thunderlady, Future Usalia …) no longer fails with "source /
  template character not found", and a failed attempt removes the empty mod it made.

**Saves: a deleted character leaves nothing behind**
* Deleting a mod (Home) or a character (🗑 Delete this character…) now offers to take its units out of the saves
  that have them: the game's save folder and the saves the kit keeps for profiles, each save ticked or not. It is
  done the way the game's own Dismiss does it (squads, groups, the units walking the base, the army's order), units
  in one of the mod's outfits go back to their own look, its recruit quests start fresh, and the game's own
  characters are never touched. The saves are copied to `state/save_backups` first. Without this, the game showed
  the unit as "DLC Dummy" or crashed at the next battle.
* **Home › More › Check saves…** finds units whose character no mod makes any more (deleted before this existed)
  and offers the same clean-up. `d5lib/savegame.py` reads and writes saves (the October 2018 and today's Steam build
  use the same format).
* **Recruit quests keep their progress slot.** A save stores a quest's progress by its slot (Quest.dat
  sort_order). The install checked slots after each mod, before the later mods' quests were in, and moved quests
  around depending on what was switched on, so a save could show one character's quest done for another one.
  Slots are now checked once at the end and a quest keeps its slot whatever else is switched on (hidden placeholder
  quests fill the quest board's count when needed). Thunderlady's quest is now written on slot 396, where every
  earlier install put it, so saves that recruited her keep it. New quests take ids and slots no mod uses, switched
  on or off.
* **Check saves** also compares recruit quests with the army: a quest shown done while its character isn't in the
  save (progress a deleted character's quest left on the slot) opens again, and a character whose quest isn't
  marked done gets it marked done (so the Quest Shop can't recruit a second one). Deleting a mod clears its quests'
  progress, unless a save has the character of another quest on the same slot.

**New characters**
* **A new character starts with its own skills, not the template's.** ✨ New character used to copy everything of
  the character it starts from, unique skills, evilities and Overload included. Now *Skills, evilities, Overload*
  is "None — give it its own on this page" unless you choose to copy them; its weapon ranks, resistances and
  movement still come from the template, and **Starting stats** picks its stats (this choice was ignored unless
  the new character wore a Disgaea RPG unit or an outfit).
* "Moves like" is now **Animations from**, with the reason beside it: a Disgaea RPG unit has pictures but no
  Disgaea 5 animations, so it borrows the moves (walking, attacks, casting) of the character chosen there, and
  nothing else.
* The message after making a character showed its description instead of what was made.
* The Quest Shop's "… has joined!" banner showed pieces of other poses with a new character (a glove, a boot,
  half a figure): it draws the character's sprite with the game's shared standing motion, which cuts two fixed
  rectangles out of the texture, and a new character's texture had other frames there. Installing now puts the
  standing picture exactly where that motion looks, with nothing else nearby, for every new character
  (Thunderlady, Henna, Liezerota, Future Usalia and any you make; `ownanim.banner_layout`). The drawings and
  animations don't change.
* **Portraits keep their white clothes.** The background removal took white clothes that touch the picture's edge
  for background (Henna's dress, Thunderlady's top, Groom Thunderlady's flowers); it no longer does, and those
  portraits were built again from their Disgaea RPG originals (`tools/refit_portraits.py`, which only ever brings
  pixels back).
* **🧽 Fix portrait background…** (Characters & Classes; Outfits › Edit › Fix cut-in background…): the portrait on
  a checkerboard or the Status screen's blue; left click makes a white area (or what the brush paints)
  transparent, right click keeps it. It is built again from the original picture, every copy of it in the mod
  follows, and the kit remembers the original and your marks for next time.
* **Weapon mastery: rank and starting level.** Each weapon shows the rank letter the game shows (S, A, B, C, D, E,
  or can't use; the number behind it is the class's aptitude, value ÷ 5 + 1: it was a number labelled "starting
  level", which it isn't). Next to it, **Lv**: the weapon level a new unit of the class starts with (the game's
  own units start at 0). The game keeps no such level per class, so the install adds it: right after a unit is made
  (recruited, joining in the story, created at the registrar) the game's own "set weapon level" is called for each
  listed weapon (`d5lib/weaponlevels.py`, mod file `patches/characters/weapon_levels.json`); a unit that already
  has more keeps it.
* **Units you already have get the new ranks and levels.** The game copies a class's ranks into a unit once, when
  it is made, so a character recruited before you changed her ranks kept the old ones in game (Henna's staff stayed
  C at Lv 0). After an install the kit lists such units in your saves (rank C → S, Staff Lv 0 → 5 …) and, if you
  agree, updates them: ranks become the class's, and weapon levels below the starting level are raised (levels
  earned in game stay). The saves are copied to `state/save_backups` first. Home › More › Check saves… does the same
  any time.
* Characters & Classes shows **how to get this character**: the recruit quest (or class unlock) in words, with its
  objective and what has to happen before the Quest Shop offers it.
* Learned skills have a **📂** button: the skills in groups (weapon skills by weapon, spells by element, each
  character's and class's own, monsters', the ones your mods add) with a search box and the description beside.

**Editor**
* **A new look**, after Disgaea 5's own menus: deep indigo panels framed in blue, teal headers on every section,
  gold stat names, Disgaea pink for each page's main button, cyan for what has the focus, larger text, clearer
  lists and tabs. The skill editor and the other pages follow the same colours (`d5gui/theme.py`).
* **Characters & Classes fits any window size**: stats, movement, weapon mastery, resistances and learned skills
  rearrange into fewer columns in a narrow window instead of being cut off (a sideways scroll bar appears only if
  something still doesn't fit), and a row of buttons above the form jumps to a section (Identity, Stats, Mastery,
  Skills …).
* Spin boxes have their own up / down buttons (stacked, as in other programs): on some Windows 11 setups the up
  arrow did nothing.
* Tooltips show after a quarter of a second and stay up 30 seconds (longer for long texts); a list entry's tooltip
  no longer goes away when the mouse moves a little.
* Making a character no longer freezes the editor for a moment: pages you aren't looking at catch up when you open
  them, and a change reloads each page once instead of once per table.

**Skill editor**
* **Your mods' characters can be the caster** (and the target) in the preview: new characters, imported ones and
  outfits are listed after the game's (marked "(mod)"). Their sprites are numbered from 13000, which the list left
  out.
* **Anyone using another character's own skill stays visible, in their own look.** Macrocosm hides its caster and
  shows Killia through stand-ins (his event pose, his awakened form) that it picks by the caster's sprite; with any
  other caster (Henna, Thunderlady, Seraphina …) none matched, so nothing was drawn for most of the skill. Such a
  skill (Killia's and Seraphina's own skills) now has one more version, played by every caster but its own
  character: the stand-ins show the caster, poses only the owner's sprites have become poses every sprite has (his
  event poses: standing; his special poses: an attack or the cast pose), the owner's voice lines are left out (the
  caster's own stay), and the timing is the same. The install adds it when someone other than the owner learns the
  skill; Killia still gets the original. The preview shows it for any other caster (`d5lib/standins.py`). Checked
  in game: Henna casting Macrocosm is seen through the whole skill.
* The preview drew a character a skill calls up by class (`cmd_6402`) with the class number as a sprite number: a
  mod's character came out invisible.
* 66 skills keep their animation in event numbers the editor didn't count as a skill's (Killia's own skills, the
  throwing items, some weapon skills): only their first line was shown, and an editable copy copied that line
  alone. Their whole animation is shown and copied now.
* Ten skills recorded from the game (Steam) and compared frame by frame with the preview. Fixed: effects resized with
  command 3c44 grew to an absolute size instead of a percent of their size.
* The parts of an effect model turn the way the game turns them (about z, then x, then y, in the game's upside-down
  world): Hurricane Blow's tornado stands up in the preview instead of pointing into the ground. It is still drawn
  flatter than in the game.

**Updating**
* A release carries one download, D5ModKit.zip: copy it over your kit (Replace), or press **Update now** in the kit,
  which writes only the files that changed and keeps your mods, profiles and settings.
* **What's new** opens the release notes in a window of their own that scrolls (in 1.3 and 1.4 a long changelog
  grew taller than the screen and its end could not be read).

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
