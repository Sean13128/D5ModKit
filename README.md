# D5 Mod Kit — Disgaea 5 Complete modding studio

> **About this repository.** It holds the kit's code and documentation (version 1.1). The mods (outfits,
> Thunderlady, classes …), the Disgaea RPG reference art the outfit builder matches against
> (`d5lib/data/drpg_ref_humanoid.pickle`) and the bundled Python come with the release zip, not with this repository:
> they are drawn from Disgaea 5 / Disgaea RPG art. To run from a clone: `pip install -r requirements.txt`, then
> `python D5ModKit.pyw` (the native runtime DLLs are rebuilt from `d5lib/native` with `ziglang` on first install).

**New here? Open `START HERE - Guide.html`** (setup, every page, step-by-step tutorials, troubleshooting).

Start the kit by double-clicking **`Start D5 Mod Kit.bat`**. A shared copy of the kit carries its own Python in the
`runtime` folder (made by `tools/make_release.py`), so nothing needs to be installed. Without it, the kit uses an
installed Python 3.10+ with PyQt6, numpy, scipy, Pillow, pefile, keystone-engine and capstone
(`pip install PyQt6 numpy scipy pillow pefile keystone-engine capstone`; `ziglang` too for rebuilding the native
runtime).

The kit finds the game by itself: the folder it sits in, else Steam's libraries, else it asks (Home → Change game
folder…). It checks the game's exe build and warns about anything that would stop an install (another kit's or a
package's mods still installed, missing files) — `d5lib/gamecheck.py`.

## How it works (30-second version)
1. **Pick the mod you're working on** — bottom left, *Saving edits to*. A mod is a folder of changes
   (`D5ModKit/mods/<name>/`) you can switch on and off; with none chosen, your first save asks for a name.
2. **Edit and press 💾 Save** (or Ctrl+S). The change goes into the mod — the game is not touched yet. A file another
   of your mods already provides is saved back into that mod (the kit tells you), so no edit gets lost.
3. **Install & Play.** The status box (bottom left, also on Home) always says whether the game has your latest
   changes: 🟢 *Ready to play*, 🟠 *Changes not in the game yet*, or *Game running* (close it to install). Its one
   button does the right thing (**⚡ Install & Play** or **▶ Play**). Unsaved edits are listed before installing, so
   you can save them first. The kit backs up the original game data once (`D5ModKit/state/`).
4. **Restore original game…** (Home) puts every game file back exactly as it was; your mods stay in the kit.

Mods can be enabled/disabled, reordered (lower in the list wins conflicts), exported to `.zip` and shared.
The editors always show the game as your enabled mods make it (every mod's changes, the one you edit on top).

## Pages
| Page | What you can do |
|---|---|
| **Characters & Classes** | Names, stats, aptitudes, move/jump, weapon mastery, resistances, evilities, learned skills, sprite & color. **✨ New character / class** clones a template into a brand-new unit, gives it its own sprite copy, a description and a Quest-shop quest that recruits it (unique) or unlocks it (class). |
| **Outfits** | Extra outfits for unique characters, switched **in game** from the unit menu (Characters → select → **Outfit** → *Default* / outfit name; the look changes at once). **✨ New outfit** takes everything in one go: the character, the in-game name, a **sprite sheet** (frame dump with labelled rows — labels are recognised automatically; every original pose of the character gets its matching frame, so all animations, facing and motion stay the game's own), a **face picture** (status panel, Status screen, battle, character-list icon; optional mirroring) and a **cut-in portrait** (special attacks; white backgrounds are removed). The page shows a preview of everything. Installing also patches `disgaea5.exe` (backed up / restored like everything else). The first three outfits (slots 470–490) get their own small character-list icon; later ones use the character's normal icon there. |
| **Database Editor** | Every one of the 90 game tables as a spreadsheet (skills, items, evilities, stages, quests, shops, Dark Assembly…). Hover column headers for explanations, dropdowns for references, CSV export/import for Excel. |
| **Dialogue & Text** | Search all 7000 conversations, edit lines in 5 languages, change speakers, add/delete message boxes, Find & Replace across the whole game, full script view for advanced edits. |
| **Stages & Maps** | Battle map editor: move/add/delete enemies, set class, level, equipment, skills, evilities, AI, team; paint Geo Panels, place Geo Symbols, move the base panel, rename stages, clone a stage as a new level, export the 3D map to OBJ. |
| **Sprites & Colors** | Every character/monster sprite (new characters and outfits included, each opened from the mod it lives in). Palette editor with a **live animated preview** beside it: click the character to select a part, drag hue / saturation / brightness and watch the animation change; named colors (Normal / Extra Color 1-4, or tiers); palette rows = Parts of the in-game precise editor. Sprite-sheet export → repaint → import, portraits, clone as new sprite. |
| **Weapon Grips** | Where each character holds its weapon, per animation and frame. Pick a character, weapon type and animation, then **drag the weapon onto the hand** (right-drag turns it, arrow keys nudge, Q / E turn, F mirrors). Change one frame or the whole animation, show or hide the weapon, play it back. Works on new classes (every animation), outfits and the game's own characters (their idle and special poses). See [docs/WEAPON_GRIPS.md](docs/WEAPON_GRIPS.md). |
| **Skills & Animations** | What a skill looks like in battle. The **Timeline editor** plays any skill inside the kit (caster, target, effects, camera) and lets you retime, move and swap its effects, camera, motions and sounds, or add new ones from the game's effect library. You can also give a skill another skill's animation, put your own pictures into its effects, and preview edits in the running game. See [docs/SKILL_EDITOR.md](docs/SKILL_EDITOR.md) and [docs/SKILL_ANIMATIONS.md](docs/SKILL_ANIMATIONS.md). |
| **Textures & UI** | Menus, windows, icons, logos: export PNG, edit, import. Localized (English) versions are handled automatically. |
| **Music & Sound** | Play and replace all BGM tracks (intro + seamless loop) and all sound effects. MP3/WAV/FLAC are converted automatically when ffmpeg is on PATH. |
| **Event Scripts** (advanced) | All 19,053 event scripts (cutscenes, stage events, recruitment) as editable text with known command meanings, “starts / started by” links, search by any number used, and new events. |
| **Archive Explorer** | Every file inside every archive: preview, export, replace. |

## Tips & known limits
* **Keep sprite sheets the same size and layout** when repainting: sprite parts are cut from fixed rectangles
  (humanoid characters share one set of animations).
* **New ids are always above the existing maximum** (the wizard does this for you) — required so your existing
  save files keep working. Don't delete original rows.
* Brand-new stages: cloning works, but how the game unlocks and lists brand-new stages isn't fully known yet.
  To test a custom level, you can point an existing stage at your map (Database Editor → Stages → map id).
* The objective of a quest made by the wizard is copied from “Combat Lecture”; adjust it in Database Editor → Quests.
* **Capacity.** What the kit makes has no practical limit: effect models load when shown (the game alone holds
  400), ~29 700 new effect models, 7 100 custom skill animations, list icons and faces in textures that grow as
  needed (thousands), ~1 750 new sprites, 4 000 custom voices, skills / evilities / descriptions by the
  thousand; 119 new generic classes (73 humanoid, 46 monster), new Overloads by the thousand (208 with numbers of
  their own). Limits that come from the game itself: new unique characters and the outfits of unique characters
  share the ids below 1000 (714 in all), and a save keeps the progress of 1 024 quests (the game uses ~520). See
  docs/OUTFITS.md "Capacity", docs/CLASSES.md and docs/OVERLOADS.md.
* A quest's **sort_order** is its progress slot in the save: it must be unique, and Quest-shop quests (id < 2000) need a
  slot below the number of quests or the board never lists them. The wizard picks a free slot, and the installer
  moves bad ones (with a warning).
* **New unique characters get a class id below 1000** (the unused “DLC Dummy” rows 970/980/990, then 971–999):
  the game treats every class id ≥ 1000 as a generic class (colour lists, tiers ...), which broke e.g. the
  Strategy Assembly's extra colours.
* The precise colour editor edits a sprite's palette in rows of 16 colours (rows 1–15). Outfit sprites made by
  the kit put every part (hair, clothes, skin ...) in a row of its own, like the game's sprites, and each outfit
  keeps its own custom colours when you switch outfits. To decide the parts yourself: Outfits → *Export parts to
  paint*, paint them (e.g. Paint.NET), *Import painted parts* ([docs/COLORS.md](docs/COLORS.md)).
* **Evilities, skills and Overloads work on any character you edit or add** — no story locks. The game holds the
  main cast's second evilities, most Overloads and some unique skills back until a story flag is set, gives a unit
  one unique-evility slot, and reads only the first `evility_count` innate evilities (char.dat +0xC8, which the kit
  now sets for you). For every character row a mod changes, the installer patches all of that away
  (`d5lib/unlockpatch.py`); already recruited units get the new evilities / slots / skills the next time the game
  refreshes them (opening a menu, changing equipment ...). Characters no mod touches keep the story's order.
* **Disgaea RPG outfits for 25 characters** (167 outfits: Killia, Seraphina, Majorita, Asagi, Laharl, Etna, Flonne,
  Sicily, Girl Laharl, Pleinair, Valvatorez, Fenrich, Artina, Fuka, Emizel, Nisa, Mao, Salvatore, Almaz, Sapphire,
  Adell, Rozalin, Axel, Pram, Petta), one mod per character (`DRPG_Outfits_<Name>`), made from `DRPG Assets` by
  `python tools/drpg_outfits.py learn` / `build` (catalog `d5lib/data/drpg_outfit_catalog.json`; add units there).
  See docs/OUTFITS.md "DRPG outfits for every character".
* **Character studio** (Characters & Classes, [docs/CHARACTER_STUDIO.md](docs/CHARACTER_STUDIO.md)): a new
  character can wear any outfit's look (a Disgaea RPG outfit is drawn again as a complete character; the outfit can
  be hidden from the Outfit menu by the new mod without editing the outfit's mod), start from stat presets or copy
  parts of any character, get a skill of its own (the skill editor opens on it, with a way back) and evilities of
  its own (named by you, working like a game evility). One character = one mod.
* **Overloads of your own** (Skills & Animations → ⚡ New Overload…, [docs/OVERLOADS.md](docs/OVERLOADS.md)): any
  character (game or new) can get a new Overload — the code of a game Overload or numbers of its own (power,
  element, area, effects), its own animation, name banner and description — and the game's Overloads can be changed.
* **Mods on the Home page** are grouped by category with readable contents ("4 outfits for Killia: …"), search,
  packs (several mods switched as one, without changing them) and a load order view (`d5lib/modinfo.py`).
* **Sharing between kit users** ([docs/SHARING.md](docs/SHARING.md)): a shared mod carries an identity and a
  version; importing a later one updates it, ids that clash with your mods are moved and remembered (saves stay
  valid), *Make my own version* builds on someone's mod without changing it.
* **Sharing with players**: `python tools/export_pack.py Pack.exe --title "..."` makes one installer .exe that
  installs your mods into anyone's game in seconds and uninstalls them byte-exact (no Python needed). See
  [docs/SHARING.md](docs/SHARING.md). Installing everything in the kit takes about a minute.
* Mods are kept separate: **Outfit System** (the feature) / **Girl Laharl Outfits** (content, requires the system) /
  **Thunderlady** (a new character: Girl Laharl's lightning alternative, with the Thunderlady outfits). A mod lists what it needs in `mod.json`
  (`"requires"`); the Home page and the installer warn when a required mod is off.
* Recruit quests (reward “character joins”) only move a unit the story left in the hidden reserve. For new
  characters the installer adds a small exe hook that creates the unit (level 1) when the quest is completed.
* Untested in-game so far: sprites larger than the original, more color variants than the original,
  and new generic class ids above 10000 (the game special-cases class ids 1000–1310 / 2010–2300 for portrait colors).
  Test these on a spare save.

## For tinkerers
* `d5lib/` — Python library for every format (NISPACK archives, LZS/YKCMP compression, TXF textures, anm sprites,
  maps, 3D `.obf`, database tables, talk.dat dialogue, script.dat, sound archives) plus the mod/installer system.
* `docs/` — format documentation: `FORMATS.md`, `ANM.md`, `DATABASE.md`, `MAPS_AND_OBJECTS.md`, `EXE_ANALYSIS.md`.
* `_extracted/` (~9.5 GB) is only a research cache made by `extract_all.py`; the app does not need it —
  delete it to free space.
* **Sharing the whole kit:** `python tools/make_release.py OUT_DIR --zip` makes `OUT_DIR/D5ModKit` (+ `.zip`): the
  kit, the mods of a release profile (default `outfits`: the Outfit System and the outfit mods; `--profile all` /
  `--mods A,B`), a private Python 3.10 with the libraries (`runtime/`, `python310._pth` keeps it isolated from any
  installed Python), the compiled runtime DLLs (`cache/`), the Disgaea RPG sprites / faces / cut-ins the builders read,
  the guide and launchers (`Start D5 Mod Kit.bat`, `D5 Mod Kit Console.bat`).  Left out: `state/` (this PC's
  backups), the rest of `cache/`, `_research/`, `_extracted/`, the underscore test tools, `settings.json`.  Tested
  2026-10-10: a staged copy, on its own Python, installs byte-identical game files to this kit's install and its
  restore returns the original files exactly.
