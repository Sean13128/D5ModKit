# Skill animations (`d5lib/skills.py`)

A skill's look in battle is data, so the kit can change all of it:

* the choreography: camera, effects, motions, sounds and timing;
* the pictures inside its effects.

Tools:

* **GUI:** the Skills & Animations page.
* **CLI:** `tools/skilledit.py`.
* **Mod data:** `patches/skills/skills.json`, with the pictures next to it.

## How the game plays a skill

* **The wrapper event.** When a skill is used, the battle starts script event **12000000 + skill id** (magic.dat id).
  * Astral Wave 11031 → event 12011031.
  * A skill without its own event plays the default sequence 11000000.
  * The wrapper is usually one line: `call_event 15xxxxxx`.
* **The choreography.** The 15xxxxxx event is the choreography: a small tree of `script.dat` events. Shared helpers
  live in 12000xxx:
  * 12000010 / 12000011: start and end of the skill;
  * 12000020: actor motion sequence;
  * 12000045: damage hits at the listed frames;
  * 12000055 / 12000056: camera to the caster and back.

  (An earlier note said the choreography was exe code. It isn't: it was found by tracing `StartScript` 0x14018F4A0
  while skills ran.)
* **Effect models.** These are `Start/Start_JP.dat/Effect.dat/effectNNNN.obf`: 383 YKCMP-compressed `.obf` models,
  listed in `EffectTableDataBase.dat`.
  * A choreography loads one into an effect slot with `cmd_3c00 slot, effect`, shows it at an actor with
    `cmd_3c10` / `cmd_3c18`, and changes it with `cmd_3c40` (size), `cmd_3c80` (colour, opacity) and so on.
  * Each model has 1–13 textures and its own animation.
* **Effect texture formats.** All of them can now be read and written. Every vanilla texture round-trips byte-exactly,
  except 2 that are truncated in the game data.

  | Format | Type | Used for |
  |---|---|---|
  | `0x00` | ARGB8888 | Mostly additive glows: opaque, where black adds nothing. |
  | `0x0c` | LA88: 8-bit brightness + alpha, little-endian header | `attr` = number of layers (1–3), stacked. Colour comes from the choreography (`cmd_3c80`). |
  | `0x0b` / `0x0d` | ARGB1555 / RGB565, 16-bit big-endian | 0x0d has no alpha (opaque: drawn adding light). |
  | DXT1 / DXT3 | — | — |

  Some textures store their header little-endian; the size field tells which.
* **Effect shapes.** The kit labels each model by what it draws:
  * **flat:** circles, flashes, sprites;
  * **wall:** a cylinder around the spot. The picture's width wraps once around it, and the cylinder is about 6× wider
    than tall, so tile pictures (Tile ~10, Fit stretch) to keep them upright;
  * **mesh:** anything else.

## Skipped effects (and why a missing event hangs the battle)

* **The ids.** A skill is started as 12000000 + id. When its effects are skipped, it starts as 12100000 + id instead.
  * Effects are skipped by the Options' Ally / Enemy Effects 'skip', the skip button, or the enemy AI's turn.
  * Skipping midway restarts the skill as 12200000 + id.
* **Fallbacks.** Next the game tries 12100000 + id // 10 * 10, then 11100000. 11100000 doesn't exist in vanilla, so an
  action with no event at all starts nothing, and the battle waits forever.
* **Monster attacks.** A monster's normal attack, counters included, uses the same scheme on 12010000 / 12110000 /
  12210000 + its sprite id (launcher `0x1405474b1`).
* **What the kit adds:**
  * every skill wrapper gets its 121/122 events (the generic bodies most vanilla skills use);
  * 11100000 / 11200000 are added as a last resort;
  * new monsters get their template's attack events (`newclasses.add_class_scripts`).

  The live preview builds the same events, so a preview can't drop them.

* **Values passed to helpers.** `call_event` arguments reach the callee as argument / 10. Commands read them back
  as ints (slots, actors, effect ids: truncated) or ×10 (positions, sizes). So `call_event 15130101, 10, 1060, …`
  means slot 1 and effect 106. Details: [SKILL_EDITOR.md](SKILL_EDITOR.md#values-passed-to-helper-events-from-the-exe).

## What you can do

1. **Use another skill's animation.** The skill's wrapper calls another choreography. New skills made with
   `newclasses.add_skill(..., copy_of)` get their source skill's animation automatically (`skills.inherit`).
2. **Make an editable copy.** The whole choreography tree is copied to new event ids.
   * Each skill gets a block of 1000 ids: 15900000 .. 15999999, then 14000000 .. 14999999 and 5000000 .. 10999999
     (no game event there; a script names an event in 3 bytes, so ids stay below 16777216): 7 100 blocks.
     Calls inside the tree are renumbered.
   * Edit the events as text. Every known command is annotated with its arguments and meaning (`skills.annotate`), and
     comments are dropped on save.
   * The command reference is `d5lib/data/choreo_commands.json`, the GUI's "Command reference" tab, or
     `skilledit.py commands`. Each entry is marked **verified**, **high** or **guess**.
3. **Put your own pictures into its effects.** `skills.set_picture` does this:
   * The effect gets a copy with a new id (from 3000) and your picture; only this skill's copy uses it.
   * The picture is trimmed to its visible part and fitted to the texture (contain / cover / stretch, scale, rotate,
     tile).
   * On additive textures it goes onto black and is dimmed to about the original's brightness.
   * At install, the new models go into Effect.dat and get `EffectTableDataBase` rows; the table is kept sorted.
4. **Edit on a timeline.** The Skills page's Timeline editor plays the skill in the kit and edits it there
   (retime, move, swap, add, delete): [SKILL_EDITOR.md](SKILL_EDITOR.md).
5. **Preview without restarting.** `▶ Preview in game`, or `skilledit.py preview`:
   * The kit writes `d5live_script.dat` (vanilla scripts + the enabled mods' script and skill edits) next to the exe.
   * The runtime (`[skills] live_reload=1`, `d5lib/native/d5live.inc.c`) loads it into the running game within half
     a second, and the next cast plays it.
   * **Solo slot** previews the skill with only one effect slot shown, to see which slot draws what.
   * New or changed pictures still need Install and a game restart, because effects are loaded when the game starts.

## CLI

```
python tools/skilledit.py info 11271                      choreography, events, effects (shape, textures)
python tools/skilledit.py copy MOD 11271 11031            editable copy of Astral Wave's choreography
python tools/skilledit.py export MOD 11271 DIR            events -> DIR/<id>.txt (annotated); edit; then
python tools/skilledit.py import MOD DIR
python tools/skilledit.py picture MOD 11271 100 0 talisman.png --tile 10 --fit stretch
python tools/skilledit.py preview [--solo 11271:2]
python tools/skilledit.py commands
```

## Verified in game (2026-10-07, not saved)

* **The class skills play their own choreographies:**
  * Talisman Storm: its own copy of Astral Wave.
  * Shikigami Drain: Magic Siphon.
  * Beast Rush: Anaconda Impact.
  * Dominate / Wild Groom: the support buff choreography of skill 1501.
* **Effects get the right numbers:** damage 12–15, SP drain, ATK/INT/HIT and DEF/RES/SPD up.
* **New effect ids load.** Effects 3000 and 3001 (≥ the vanilla maximum 2563) load. The yin-yang shows in Astral
  Wave's rune circle, and a wall of DRPG ofuda (`385_black_miko_u`) rises around the caster.
* **Effect models have no limit** (`d5lib/fxpool.py` + the runtime's `d5fx.inc.c`, 2026-10-12). The game itself
  preloads every model of EffectTableDataBase at start into a resource manager that has room for 400 (vanilla has
  383; 402 crashed it at start, at 0x1402fb302). With mods that add models, the installer leaves every model a
  script shows (and every mod's model) out of the preload and writes `d5fx.dat` next to the exe; the runtime loads a
  model when a skill's script starts (each event's list) or when the game asks for one it doesn't have, and when
  the 400 places are full it releases the model asked for longest ago that nothing on screen uses. Tested in game
  with 432 models (all on demand but 19), and with the room cut to 60 / 80 so models were released and loaded
  again 80 times during four skills: no failure. New models take ids 3000 .. 32767 (scripts name a model in a
  signed 16-bit operand): 29 768 of them.
* **Some greyscale (LA88) models are drawn orange by the game** with no colour command on them, and stay orange
  under one (Girl Laharl's 107, the smoke 119; 106 stays white and takes a colour command). The kit draws them
  white. Why wasn't found (not the slot colour, the vertex colours, EffectTableDataBase, the picture header or its
  brightness). A copy whose pictures are DXT5 / ARGB8888 shows exactly its own colours: that is how
  `fxrestyle` recolours them (`"la": true`).
* **Live preview works:** edit → preview → next cast showed the change, with no restart. These commands were verified
  this way:
  * `cmd_3c80` colour (the talisman wall turned purple);
  * `cmd_3c42` and `cmd_3c40` size (0 hides; `100,0,100` flattens);
  * solo slot.

## Harness additions

* `scripts PATH` loads a plain `script.dat` into the running game (the same loader as the live preview).
* `trace ADDR 1 0 LABEL`: execution watch, logs every call (registers and caller).
* `tools/class_battle_test.py`: boot, hire the new classes, enter a stage, deploy.
* `tools/_exp.py` / `tools/_cast_next.py`: command experiments (solo + next-turn cast + zoomed contact sheet).
