# Skill timeline editor (Skills page → 🎬 Timeline editor)

Plays a skill's whole animation inside the kit -- the way the game shows it: its camera, effects, cut-in, the battle
map -- and lets you change it on a timeline, without starting the game. Backend: `d5lib/choreo.py` (script
simulation and edits), `d5lib/stage.py` (the battle stage frame by frame), `d5lib/battlemap.py` (maps),
`d5lib/fxmodel.py` / `fxanim.py` (effect models), `d5lib/skillarea.py` (where it hits), `d5lib/presets.py`
(building blocks). GUI: `d5gui/skilledit/` (`glrender.py` draws on the GPU). Without the kit's window:
`python tools/render_skill.py SKILL OUTDIR` renders frames and a contact sheet the same way.
How the game plays skills: [SKILL_ANIMATIONS.md](SKILL_ANIMATIONS.md).

## Using it

Most editing happens **in the preview**, the way Blender's 3D view works (Blender manual and Spine docs were the
reference for the keys and mouse). The panel on the right says in plain words what the selection is and does; the
timeline below is for timing.

### Finding a skill

Above the list: **search**, a **category** (character & class skills, weapon skills per weapon, spells per element /
heal / support / status, Overloads (each with its ⚡ Overload tab: docs/OVERLOADS.md), throw items) and **Skills of
a character / class** (only what that character
learns, with the level). The title shows the skill's category and who learns it. **➕ Give to character…** adds the
skill to a character's or class's learned skills (every tier) at a level; **➖ Remove from character** takes it away
from the character chosen in the filter (both saved into the active mod at once). **⤢ Focus** gives the editor the
whole window.

**👥 Who learns it** (a tab next to the Timeline editor) lists every character and class that learns the skill with
the level: change the level (Enter or leave the box saves it; a class: all its tiers), **Remove**, or **➕ Give to a
character / class…**. It is the same data as *Learned skills* on the **Characters & Classes** page: a change on one
page shows on the other (both save into the active mod). When a class's tiers learn it at different levels (set
per tier on the Characters page) the row says *tiers differ*.

### The preview (viewport)

| Do | How |
|---|---|
| select an effect | click it (Shift+click: add / remove); drag on empty space: box select; A all, Alt+A none |
| move it | drag a selected effect (along the floor; Shift: up / down) — or **G**, then move the mouse |
| tools | the bar at the top left: **Select** (Q), **Move** (arrows: along X / Y (up) / Z; the square: along the floor), **Rotate** (drag the ring), **Scale** (drag a corner). Only the options a tool uses show up |
| exact values | **G / R / S**, then **X / Y / Z** to lock an axis, type a number, **Enter** or click = done, **Esc** or right-click = cancel; **Ctrl** snaps (10 units / 15° / 0.1), **Shift** is finer |
| pivot (Rotate, Scale) | selection centre, caster, target, or **each its own** (Rotate then turns each picture, Scale only its size) |
| Scale changes | size + spacing (Blender-like), size only, or spacing only |
| delete / duplicate | **Delete** or **X** / **Shift+D** (the copy follows the mouse; Esc leaves it where it was) |
| copy / paste | Ctrl+C / Ctrl+V (pastes at the playhead, also into another skill) |
| view | middle-drag or Alt+drag orbit, Shift+middle or right-drag pan (both switch to the free camera), wheel zoom (free camera only); **View** list: angled (Home), front / side / top (numpad 1 / 3 / 7), frame the selection (**F**) |
| more | right-click an effect: delete, duplicate, copy, move / rotate / scale, select all like it, frame, properties |
| camera | The **badge** at the top right of the preview always says which camera is on. **🎥 Game camera** (green, the default): the skill's own camera, 16:9, moving with the skill as in the game. Looking around with the middle / right mouse button (or Alt+drag) switches to the **free camera** (orange badge: *↩ back to the game camera*). Click the badge, press **C**, tick *Game camera* in the Scene bar, or play the skill (▶) to go back. The wheel never leaves the game camera by itself (a scroll meant for the page used to) |
| scene | **Stage** (a battle map or a flat floor), **Facing**, **↔** panels to the cursor (skills with a reach) or to the target, **HUD** (skill name, hit numbers), **Area** (the skill's panels on the ground) |

The selected effects are ringed (faint when not on screen at this frame) and their flight paths are drawn as dashed
trails (**Paths**). Every drag or G / R / S is one undo step (Ctrl+Z / Ctrl+Y). Moving or scaling an effect moves its
whole path; landings on the target stay on the target.

### ✏ Properties

Laid out like Blender's properties editor: a header (picture, name, what it is, its buttons) and folding panels
(click a panel's title; the kit remembers which are open), one property per row — a short label, the control, and a
line of help under the ones that need it.

* **An effect** — header: its picture, *🖼 Picture…* (choose another from the picture list), *⧉ Copy*, *🗑 Delete*,
  *⌖ Frame*.
  * **Transform**: *Attached to* (caster / target, with their pictures), *Position* X / Y (height) / Z (120 = one
    panel; its whole path moves with it), *Size* (%), *Turn* X / Y / Z (its picture's own turn when it appears:
    `cmd_3c64` at the show).
  * **Timing**: *Appears* / *Disappears* (frame and seconds), *Animation* (plays once / loops / n times), *Speed* of
    its own animation (100 % as made, 0 holds the first picture, minus plays it backwards; the show's 7th value).
  * **Drawing**: *Draw order* (`cmd_3cde`: the model's own / behind the units / with the units, nearer covers
    farther / in front of the units), *Nearer camera* (`cmd_3ca0`, 20 = one map unit: sits on the ground or over a
    unit right behind it instead of cutting into it), *Facing* (`cmd_3ca5`: camera-facing parts stop facing the
    camera), *Blending* (`cmd_3cd6`). Each writes the game's own command right after the show (or changes the one
    that is there), so the game draws it the same way.
  * **Motion**, **Turning**, **Colour & fade**: what it does while it is on screen (✖ removes one); **Script values**:
    every raw value.
* **Several things**: what is selected, Delete / Duplicate / Group & paths / Frame.
* **A pose**: its animation playing in the header, *🏃 Change pose…* (the pose picker), character, pose, start
  frame, blend.
* **A sound**: its waveform, *▶ Play*, *🔊 Choose by ear…* (the sound picker), volume, speed.
* Other commands: their description, values with names, Delete.

### Choosing by sight and by ear

* **Pose picker** (*🏃 Change pose…*, *Add pose…* on the timeline): every pose of that character as a picture that
  plays its animation (drawn from the same sprite data as the preview); type to filter; double-click picks. Poses
  the character has no pictures for are listed last (*draws nothing*).
* **Sound picker** (*🔊 Choose by ear…*, *Add sound…*): every sound effect with its waveform, length and the skills
  that use it (*Only sounds skills use* narrows it); a click plays it, a double-click picks it.
* **Characters** (the 🖼 buttons next to Caster and Target in the Scene bar): every class and character as a
  picture of it standing; type to filter by name, class or sprite number. Pictures fill in as you look (each sprite
  is loaded, drawn and let go again, about a quarter of a second each, so the picker stays light).
* **Pictures** (*🖼 Picture…*): the effect library with previews. The Scene bar shows the chosen caster's and
  target's pictures; the timeline shows each effect's picture and each pose's figure at the start of its clip.

### ➕ Add effects

All game effects and the mods' new ones, with thumbnails and names; search by name, number or a skill that uses it;
a category list; ★ = used by this skill. Drag one onto the timeline, or double-click to add it at the playhead.
Right-click to rename it or change its category (game effects: `state/effect_labels.json`; a mod's own effects: in
that mod).

### 🎯 Group & paths

For several effects at once (*All like these* selects every effect with the same picture, e.g. all 8 talismans).
Changes show in the preview right away; **✔ Keep** makes them one undo step, **↩ Discard** drops them.

* **Space out, rotate, move, resize**: spacing (further apart / closer) around the pivot, rotate around it, raise /
  lower, shift, size; flights keep landing on the target unless *also where they land on the target* is on.
* **Put them in a shape**: circle, arc in front, line across, random scatter (height above the floor).
* **Flight paths**: homing missile (out to the sides, then curving in), straight, arc / lob, spiral in, orbit the
  caster, burst outward; speed curve; timing *when each one flies now* (hit and damage stay in time; **Flight
  length** makes every flight longer and moves each effect's hit / damage with it) or from the playhead. Written as
  small events of `cmd_4140` steps ending with a `cmd_4170` flight (in the skill's own frame: the game turns them
  with the facing).

### 🧩 Presets

Ready-made building blocks (`d5lib/presets.py`), written with the commands the game's own skills use. Pick one, set
its values (frames: 60 = one second; distances: 120 = one panel) and **➕ Add at frame N** (the playhead), or
double-click it; or right-click the timeline → **🧩 Add preset** (on a character's track it is done to that
character). Each one becomes a layer of commands you can move, retime and change like the rest; Ctrl+Z takes it back.

| Group | Presets |
|---|---|
| Movement | dash to the target and back, leap at the target, rise into the air (and come down), vanish and appear by the target, step back, knock back, back to the start, pose |
| Camera | close-up (on anyone), swing around, low angle, back to the battle view, shake, quake (fading out) |
| Screen | fade to black and back, white flash, darken the battlefield, into the void (the map disappears) |
| Hits | hit (every target in the area or one; the number shows), several hits |
| Selected effect | pop in, fade in, fade out, grow / shrink, pulse, spin, rise and fade (select an effect clip first) |

### 🟥 Area

Where the skill hits (magic.dat `range`, `attack_map`, `height_up` / `height_down`; AttackMap.dat shapes;
`d5lib/skillarea.py`). A grid of panels around the caster (★, facing up): **red** = hit, **orange** = the cursor's
panel (hit too), **green** = where the caster ends up (skills that move the caster), **blue** = where the player can
put the cursor. The same panels show on the ground of the preview (**Area** in the Scene bar hides them; the game
shows them while aiming, not during the skill).

* **Click / drag** panels to add or remove them; **right-click** a panel to change its kind (hit → cursor → caster
  ends here).
* **Cursor reach**: 0 = no cursor, the area is placed from the caster (Exploding Tiger: the 3 panels in front);
  more = the player puts the cursor up to that many panels away and the area is centred on it (Dazzling Eyes: 3);
  99 = anywhere. **Cursor at** moves the preview's cursor (the same as ↔ in the Scene bar).
* **Height reach** up / down: how much higher or lower a target may stand.
* **Start from a game shape**: every shape of the game with the skills that use it.
* **Place enemies** (switch at the top, or *Enemies on every hit panel* / *One enemy*): click hit panels to put
  enemies on them. The preview then plays the skill on all of them as the game does — each is a target of its own
  (*Target 2*, *Target 3* … tracks; numbered on the grid in the game's target order, 1 = the main target).
* **💾 Save area** writes the reach and the panels into the active mod (row changes of magic.dat and AttackMap.dat;
  Install to use them in the game). An area that matches a game shape uses it; otherwise the skill gets a shape of
  its own (ids from 40000), so other skills that shared the old shape keep theirs. **↺ Undo changes** goes back to
  the saved area.

### The timeline

* Tracks are **grouped**: Camera, Caster & targets, Effects, Particles, Sounds, Hits & damage, and — folded at the
  start, since most edits don't need them — Extra characters, copies & markers and Other commands. Click a group's ▾
  to fold / unfold it; the group row shows a summary of everything in it. *Find tracks* filters by name (and shows
  matches inside folded groups).
* Effect tracks are named after their picture (*Red rune circle*) and listed in the order they first appear (the
  list reads like the skill plays); poses after the pose (*cast (109)*), helper actors in words (*Where the caster
  stood*). Every key says what it does with its main value: *aim → Target*, *zoom 400 (in)*, *turn camera yaw 90°*,
  *shake*, *fade to black*, *dash → Target*, *jump → Target*, *hide*, *size 150%*, *spin 0/360/0°*, *hit Target 30%*.
  The ruler and the top left show frames and seconds (60 frames = 1 s).
* **Select**: click (Shift / Ctrl: add or remove), drag on empty space for a box (Shift adds, Ctrl removes), a track's
  name selects its clips; A all, Alt+A none, Ctrl+I invert, [ / ] everything before / after the playhead. Clicking
  empty space deselects and moves the playhead; the ruler scrubs.
* **Where things start and end**: every clip has a bright cap on both edges and shows its picture (effect) or figure
  (pose) at its start; the selected one is also marked on the ruler with its first and last frame. Things that
  happen at one moment are a mark at their frame with a chip saying what they do. Hovering a clip says its frames
  and length in seconds.
* **Move in time**: drag a clip — the WHOLE clip moves (its show and everything it does), the whole selection with
  it; nothing moves until the mouse has gone 5 pixels (a click stays a click), the old place stays outlined, and a
  readout says *frame 20 → 32 (+12)*; snaps to the playhead and other clips' edges (Alt: no snap); **Esc** cancels.
  Or press **G** and move the mouse. **Change when it ends**: drag a clip's right edge (the grip on the selected
  one).
* **One command inside a clip** (a move, a colour change …): the selected clip shows them as small marks along its
  bottom; click one to see its values, **Alt+drag** one to move just that command (a plain drag always takes the
  whole clip, so its parts never come apart by accident).
* **Delete**: Delete / X, the right-click menu, or hover a track's name and click 🗑 to delete the whole track. 👁
  hides an effect track in the preview (not in the game).
* **Duplicate** Shift+D (Ctrl+D), **copy / paste** Ctrl+C / Ctrl+V at the playhead.
* A dotted line marks clips that move. Right-click empty space or double-click a track for add: effect, camera
  move / shake, pose (pose picker), flash, sound (sound picker), screen fade, or any preset (🧩 Add preset).
* Playing redraws only the playhead (the rest of the timeline is kept as a picture until something changes).
* Commands inside a script loop that runs several times (skill 818's crescents) can't be moved one by one.

### Calibration recordings (development only)

The editor never needs the game. While developing the preview, skills are recorded from the game frame by frame and
compared with the kit's drawing: `tools/_record_skill.py` (runtime `record EVENT EVERY SCALE MAX DIR`, test harness
`remote=1`; `d5lib/gamelink.py`), recordings in `cache/recordings/skill<id>/<date>/` with `telemetry.bin`
(`d5lib/telemetry.py`: the camera state block and every drawn actor per frame).  The runtime detours the script
start (StartScript 0x14018F4A0) and counts frames from the skill's wrapper event (12000000 + skill id); frames are
saved from the back buffer at Present. `tools/_record_skill.py ... FRAMES FROM TO` (runtime `probe FROM TO`) also
writes `probe.bin` for frames FROM..TO (`telemetry.read_probe`): the first 64 effect slots (0x141DA0AE0, 0x358 each:
colour, layer, model ...) and the draw manager (0x146A34C10) with queue 6's sorted keys (0x140BCB050), draw order
(0x140BF2150) and records — what the two open differences (Dazzling Eyes' heart colour, Killia in Macrocosm 106-112)
need. The camera log is read at the start of a game frame, so it shows the frame drawn before.

#### What the telemetry showed about the battle camera (2026-10-10)

* The camera block at 0x146A3AC00: rotation matrix 0xcd0 (rows), view translation 0xd00, eye 0xd50, forward 0xd60,
  look-at target 0xd74 (map units, 12 per panel; Killia on panel (7, 4) = (90, -18, 54)), pitch 0xd80 / yaw 0xd84 /
  roll 0xd88 (radians; default 30 deg / -45 deg), distance 0xe78 (= zoom; current / start / target at 0xe78-0xe80).
* camera space = world * R + t (rows of R at 0xcd0); the eye is `distance` map units from the target along the
  forward vector; the projection matrix at 0xd10 has [0][0] 12.2108 and [1][1] 21.7082 (16:9; vertical field of view
  about 5.3 deg): the battle view is nearly orthographic.
* Draw objects hold their anchor projected: obj+0x4c / +0x50 = camera x / y x 7741 / depth, +0x54 = depth.
* What the commands do is in *How the preview matches the game* below. The recorded game advances the skill's
  script at an uneven rate against its frames (loading waits, fast-forward), so comparisons align the two by the
  camera (dynamic time warping over target / distance / angles).

### Saving

* **Your first change** to a skill that has no editable copy in the active mod makes one (as *✏ Make editable copy*
  does) and then applies the change there. Vanilla data is never changed.
* **💾 Save** (Ctrl+S) writes the changed events into the mod. **▶ Preview in game** saves and sends the result to the
  running game (live reload, no restart).
* Positions in skill scripts are offsets the game turns with the skill's facing (see *How the preview matches the
  game*): what you move in the preview is written in the skill's own frame, so it is right for every facing.
* Number boxes and lists react to the mouse wheel only after you click them (everywhere in the kit).

## How the preview matches the game

The preview is the kit's own: it never talks to the game. `d5lib/choreo.py` runs the skill's script events (timing,
branches, values); `d5lib/stage.py` (StageSim) replays every command into a battle stage frame by frame with the
game's rules, read from each command's code in `disgaea5.exe` and checked against frame-by-frame recordings of the
game (2026-10-11: the kit's frame numbers are the game's frames since the skill started -- Macrocosm's simulated
camera matches its recording at all 1 251 frames within 0.05 map units, Dazzling Eyes' screen flashes land on the
same frames as recorded; a recording's camera log is read at the start of each game frame, one frame behind its
pictures);
`d5gui/skilledit/glrender.py` draws it on the GPU (OpenGL 4.1; one vertex stream per frame, texture atlas pages).

* **Order inside a frame**: the scripts run, then everything (the camera too) advances one frame, then it is drawn
  (Macrocosm's pictures: an instant zoom and a fade starting on the same frame show first in the same picture).
* **Waits**: `wait N`, `wait_children` and calls pause a script, and so does any command whose handler rewinds the
  script and returns 0 (32 of them; e.g. `0a10`-`0a40`, the message commands, `6540` / `6550`). `cmd_6530 actor, N`
  does not wait — it jumps the actor's motion to frame N (0x14016d070 → the sprite's time = N).
* **Loading pauses**: `cmd_640a actor` (switch on, 0x1401689d0) waits while the actor's sprite files are still
  loading. Load time depends on the PC and on what is in memory already; the kit uses what the recordings show for a
  first cast in a battle: an event-pose sheet (`cmd_6402` 7000-7999) is ready 10 frames after it was asked for, a
  cut-in portrait (`cmd_6411`) 7 frames; class sprites and the battle's own units cost nothing (`choreo.LOAD_FRAMES`).
* **The opening camera move** (helper 12000012) takes 11 frames when the game setting read as `$64815` (dword +0xca8
  of the object at 0x147B82D10) is 1 — as in every recording — else 7; the kit assumes 1.
* **Animated values** (camera, effects, units, screen): start, target, frames. Eased commands (the ones with an
  `ease, flag` pair) take geometric steps: each frame's step is p times the last, p = 1 + ease / 1000 for all of them
  (the camera's 0x140166da0 too: ease / 10 / 100 + 1) — ease 200 speeds up, -200 slows down. 0 frames = at once.
* **Camera**: a perspective camera looking at a target point from `distance` map units (700 = the battle view; a
  map unit is 10 script units). Pitch 30°, yaw −45° is the battle view. 3210 / 3220 aim, 3230 / 3240 zoom, 3260 /
  3280 turn by, 3268 turn to, 3290 back to the battle view, 325c stops the turning only (aim and zoom go on).
  **3250 / 3258 set the lens** (not a far clip): the vertical field of view is 27 008 / value degrees — the battle's
  5120 is a narrow 5.3° (projection [1][1] = 21.708), Macrocosm's planet scenes use 1500 (18°), 750 (36°) and 700
  (38.6°). Measured in every recording's camera block (value × field of view = 27 008.0 once settled); 0 = 5120.
  The projection has no far plane (near 1 map unit, depth 1 − 1/z). The preview shows the game's 16:9 picture (letterboxed in the panel).
* **Camera shake** `cmd_32a0 sideways, up-down, frames` (0x140167560, applied in the camera update 0x14043dc4b): every
  frame the count goes down and the whole camera shifts by the amounts / 100 map units (sideways along the view,
  vertical) times −1 or 3 (bit 1 of the count), until the count runs out; frames −1 = until the next shake. The
  game's hit helper 12000045 chains fading ones (Exploding Tiger: 200 / 80, 100 / 40, 50 / 20, 25 / 10).
* **Facing**: the game turns every script offset by the skill's facing — q = (4 − facing) % 4 quarter turns
  (0x140088630): facing 0 as written, 2 turned around. Effects' orientation turns the same way. So a skill is written
  once in its own frame (forward = +z); branches on `$60201` are for other reasons (e.g. Macrocosm turns the camera
  for facings 0 / 1). Facing 0 = the target away to the left of the battle view, 1 away to the right, 2 toward you on
  the right, 3 toward you on the left.
* **Places**: a plain actor id points at the actor's base place (where it stood when the skill took it, `cmd_6620`
  sets it); `1xxxx` = where actor xxxx is right now, mid-move too (0x140087a60 asks the actor for its position);
  locators 300-399 (`cmd_66b0`, moved by `cmd_66b8`); 5000 + i = area panel i; 7000 + i (or 17000 + i) = where
  effect slot i is (the actor lookup 0x1402eaa20 maps 7000-7255 to the effect slots: Dazzling Eyes puts its last
  hearts on slot 9's heart over the target). The game's place resolver is 0x140087330.
* **Targets**: the units on the area's hit panels are the area targets in the shape's cell order: actor 3000 + i
  (30000 + 10 i as a call argument, which divides by 10), `$60400 + i` = 1 when target i exists; 3600 = the main
  target (the unit lookup 0x1402eac10). `cmd_7220 3603, 3603, %` hits every target (the commonest hit). The preview
  puts an enemy on each panel chosen on the 🟥 Area tab and sets those variables, so the skill takes the same
  branches as in the game (Exploding Tiger's crystals grow on each of its 3 targets).
* **Area** (AttackMap.dat, in memory as loaded, shapes found by a linear search of their u16 id): a cell (x, y) turns
  with the facing like a script offset (0x140138940: x sideways, y forward), so the area is drawn in the skill's own
  frame; with a reach (> 0) the shape is centred on the cursor, else placed from the caster.
* **Screen**: fade (`screen_fade`: 127 black … 0 … 129 white), the backdrop gradient behind everything (2830 / 2832 /
  2834, 2835 back to the map's), the battle map's colour and opacity (2820; Macrocosm hides the map with it).
* **Stage**: the **Stage** list in the Scene bar puts the skill on a battle map (map 101, the first Netherworld stage,
  by default) with the caster on a panel and the target on the panel `distance` away; or a flat floor with a grid.
* **Units**: sprites face the camera; a motion plays animation motion × 10 + 1 (front) / + 7 (back), mirrored when
  facing right; the shared motion stubs chain on into the class's own animations (1501 → 7001 …). Extra actors:
  `cmd_6402` (a class's look: Killia's second form, event-pose sheets), `cmd_640a` (on), `cmd_6c04 a, b` (a moves with
  b: the Killia you see in Macrocosm follows the hidden caster), tint / opacity (6480 / 6482), size (65a0).
  Motion time: each unit has a clock that advances by its speed every frame — `cmd_6570 actor, %` sets the speed,
  `cmd_6560 actor, 0 / 1` stops it / plays it at 100 % (the same field: an earlier speed is not kept), `cmd_6530`
  jumps it. `cmd_6470 actor, 0` takes the unit's shadow away (any other value: how its shadow finds the ground).
* **Moves** (`cmd_6642` / `6672` / `6680`, traced 0x14016fa40 / 0x140170920 / 0x140171940 and the actor update
  0x1402e5c00): each sets up a move of a kind the update runs every frame with t = 1 − frames left / frames —
  straight; a step per frame that grows or shrinks by p every N frames (6672 mode 0: p = 1 + |ease| / 1000, speeding
  up for ease ≥ 0 — those stop one base step short, like the game — slowing down below 0); eased steps (6672 mode
  100); and arcs (6642 modes 1 / 2 / 5 / 6, 6672 modes 1 / 2 / 5 / 6 / 11 / 12 / 21 / 22, 6680 modes 1 / 2 / 5 / 6).
  An arc goes from the start height up to an apex and ends on its landing point: y = v u + a u² / 2 with v, a from
  the apex and landing heights (0x140136c80); the jump (6680) moves sideways with eased steps (its 9th value) and
  reshapes the time around the apex with its 8th (0x140136910). The modes pick the landing and the apex: 2 lands at
  the destination without the offset's height with the apex at the destination (the y offset = how high it jumps),
  1 / 5 land on the map's ground there, 6 / 5 put the apex the offset above the lower of the landing and the start.
  Ease values of these commands: 1 + e / 1000, or 1 / (1 − e / 1000) below 0. Checked against Macrocosm's recorded
  juggle: the enemy's height every frame within a few map units, landings exact.
* **Sprite turn and shift**: `cmd_65b4` / `65b5` turn a sprite BY degrees, `cmd_65b8` / `65c1` TO an angle (the short
  way round), around a pivot (values × 3, drawn × 0.0625 = × 0.1875 sprite pixels from its anchor, y down);
  positive turns clockwise in the sprite's own picture, so mirrored sprites turn the other way on screen (sprite draw
  0x1402f1b47). `cmd_65bc` draws the sprite shifted by its values × 0.1875 sprite pixels (Macrocosm lifts the juggled
  enemy with 0, −300).
* **Mirroring**: skills mirror themselves for facings 1 and 2 (`cmd_72f0 1`, 1266 vanilla uses) instead of being
  written twice: from then on sideways offsets of the camera aim, effect shows and flights, unit moves and points
  flip, effect turns flip their y / z angles, effect sizes their x (the model is drawn mirrored), camera turns their
  yaw / roll, sprite animations and turns flip. `cmd_32f8` / `3cd0` / `3cd2` / `3cd4` / `65f0` / `66f8` … switch one
  family each (each command family reads its own byte of the skill's context).
* **Cut-in**: `cmd_6411 a, b` (a = b's portrait: picture file 10000 + sprite, animations 8000-8100), `cmd_6460 a, 1`
  (drawn on the screen), `cmd_6660` / `cmd_6664` (place / slide it, 1080p pixels from the screen centre), opacity
  `cmd_6482`; while it shows, the battle dims and black bars close in (measured on Dazzling Eyes).
* **Effects**: the show command's size IS the effect's size (size / 1000 on every axis at once, 0x140178750 →
  0x140089170) and `cmd_3c40` / `3c42` change that same value (percent; the later one wins); its 7th value is the
  frame step × 1000 (0 holds the frame — 3880 vanilla shows do); the play count hides it after its last run; played
  backwards it starts again once its frame goes below −1 (0x140300c96).
  Rotation (3c64 / 3c68 / 3c6a) is roll, then pitch, then yaw; a second rotation (3c70 / 3c74) follows. The game
  builds these matrices in its y-down render frame, so in the kit's y-up frame the x and z angles turn the other way
  (checked on Macrocosm's space rings, 903 turned 0 / 30 / −120: round rings around Killia as in the recording). 3cb8 sizes
  each piece of the model without moving the pieces apart. Mesh flags: blending (1 normal, 2 adds light, 3 takes
  light away; `cmd_3cd6` overrides), flipbooks (count, delay, length, end mode; each picture's own duration),
  billboards (the model's mode or per piece; `cmd_3cd8` overrides), LA88 layer (`cmd_3c30`). The map hides what is
  below its floor (depth), as in the game.
* **HUD** (Scene bar: HUD): the skill's name, a number for every hit (its share of the skill's damage in %) and the
  running total, with the game's digit pictures.
* **Draw order** (the effect renderer 0x1402fd190 → draw queue submit 0x14030f8a0; the queues are drawn by
  0x14030c320): everything goes into one of 12 draw queues, drawn 0 to 11. Each piece (mesh) of an effect model
  goes into its mesh layer byte + 2 — alpha pictures 4, glows and most effects 6 (12 098 + 3 696 of the 27 089
  vanilla pieces) — unless `cmd_3cde slot, queue` puts the whole effect into another one. Queue 6 is sorted back to
  front (0x14030b4d0): an effect piece by the camera depth of the middle of its mesh's first three vertices
  (0x14030b810), a unit's sprite by the depth of its feet 7 map units nearer (draw object +0x54 + +0x48, which is
  −7 in every recording; every sprite starts in queue 6, 0x1402f2680); the other queues are drawn in the order
  things were drawn. `cmd_3ca0 slot, value` brings the effect value / 20 map units
  nearer the camera in that sort and in the depth test (z' = (z + b) / (w + b), b = value / −20, 0x14030aba0): 20 788
  vanilla uses, 100–1000 mostly, so effects on the ground or on a unit don't cut into them. So a circle on the
  ground under a unit is drawn first and the unit stands on it (Talisman Storm's red rune circle), while a hit
  flash with a bias covers the unit. `cmd_3c9a slot, 0 / 1` hides / shows an effect (its animation
  stops while hidden), `cmd_3ca5 slot, 1` stops its parts facing the camera, `cmd_3c98` stores a value nothing
  reads. The kit draws all of this the same way; Properties → Drawing writes these commands.
  **Depth**: the submit (0x14030f8a0) copies the global render state into each record and clears its depth-write
  bit (0x20 of word 1: 0x01f1 → 0x01d1) only for queue 6, so sorted pieces don't write depth while pieces in the
  other queues do — a solid model such as Macrocosm's planet rock (1733, mesh layers 2 / 3 → queues 4 / 5) hides
  its own far side. Particles (0x14030cb70) and queue 6 don't write depth.
* **Unit shadows** (0x1402f3520, queue 4): a soft dark ellipse on the ground under every unit — it stays on the
  ground when the unit jumps; none for a unit given `cmd_6470 actor, 0`. Its size is the unit's char.dat `size_radius` (Prinny 5, humans 6, big monsters up
  to 21) × 0.75 map units; its middle darkens the ground to about 45 % (both measured in the recordings).
* **Blend modes** (mesh flags byte 0, or `cmd_3cd6` for the whole effect; the blend state builder 0x1403d6ba0):
  1 normal alpha, 2 adds light, 3 screen − colour (2 935 vanilla `cmd_3cd6 …, 3`), 4 multiplies (the see-through
  parts fade to white first, the pixel shader's multiply path), 5 colour − screen. `cmd_3cda slot, frames, alpha`
  fades only the opacity (the alpha byte of the effect's colour; `cmd_3c80` sets the whole colour).
* **Shared poses** (the humanoid motion set bound to every class): many of its poses (114-125, 155-160 …: the
  knock-back stages of a hit, guard …) draw no picture of their own — a key with flags 0x100 shows another of the
  character's animations there (its hurt, guard … animation, 1061 …) with a shake or an offset around it. The
  preview and the pose pictures follow that (`anm.evaluate(..., nested=True)`; editing tools leave it off).

### Commands traced 2026-10-13 (every skill swept through the simulator)

A sweep of all 519 skills (`StageSim` over each skill's timeline) lists the drawing commands (screen 28xx, camera
32xx, effects 3cxx / 40xx-41xx, particles 44xx, actors 64xx-6cxx) the preview doesn't simulate. 39 of them run in the
shared battle wrapper of every skill; the skill-specific rest was traced in disgaea5.exe, starting with the most used:

* **Thin wrappers** (their handlers only rearrange operands and call / jump into another command's handler, found
  automatically from the code): `3c12 slot, actor, size, step` = `3c18 slot, actor, 0, 0, 0, size, step, 0, 0 …`
  (an effect at the actor itself); `3c1a slot, actor, size, step, from` = the same playing from frame `from`
  (Purgatory Palm, 7x); `65b0 actor, frames, s, y` = `65a0 actor, frames, s, y, s`; `65b6 / 65b9 / 65bb / 65bd` =
  `65b4 / 65b8 / 65ba / 65bc` with frames + 1. Not yet simulated wrappers: `6c10 → 6c18`, `6c14 → 6c1c`,
  `6c40 → 6c48`, `6c44 → 6c4c`, `44dc → 44de`, `4482 → 4480` (operands a1..a5 + zeros; `4482`: a1, a2, 0, 0, 0, a3..a5).
* `6c00 a, b, x, y, z` (0x140184470 -> 0x1402e7b20): a is attached to b at the offset x, y, z (tenths of map units,
  turned by the skill's facing, x mirrored by switch 10). `6c04 a, b` (-> 0x1402e78e0) attaches **keeping a where it
  is** (the game stores a's place relative to b, child +0x128; the preview used to snap a onto b). Both take effect
  slots too (7000 + i): Exploding Tiger's flames (slots 50-57, 80-84, 90) ride along with the fighters this way.
  `6c08` detaches, leaving it where it is.
* `65ba actor, frames, x, y` (0x14016e550): `65bc` BY x, y from the sprite's current shift (0.1875 sprite pixels).
* `3c48 slot, frames, sx, sy, sz, ease, every` (0x14017a4d0): `3c42` as percent OF the effect's current size.
* `6710 unit, frames, degrees` (0x140173ca0): the unit turns, which changes the view drawn (front / back, mirrored).
  frames >= 10000: TO the skill's direction + degrees, the short way, over frames - 10000 (0x140149070); else BY
  degrees -- whole spins too -- over frames (0x140149170); degrees mirrored by switch 7. Hurricane Blow spins its
  target -1080 degrees in 35 frames. Facing angle θ = direction (-sin θ, cos θ); the skill's direction = its quarter
  turns x 90 (`stage.ang_dir`).
* `6c18 actor, frames, rx, ry, rz, ease, every` (0x140184800): turns the actor in 3D BY degrees (actor +0x174,
  radians, ry / rz mirrored by switch 9); `6c10` is its linear form. Not drawn yet: the preview has no 3D actor turn.
* `41a0 slot, x, y, z, frames` (0x14017e220): the slot's virtual +0x20 (move to x, y, z / 10 over frames), the call
  `4140` ends with -- but with the values themselves, not an actor's place + offset; always after a show at 1256 /
  11256 with `3ca5 slot, 1` and values like 15000. Probably camera / screen space: needs a recording.
* Fixed on the way: `stage.py` defined `_h_turn` twice, and the second (a generic rotation nobody draws) replaced the
  traced `65b4` turn (Macrocosm's juggled enemy).

Result: skills whose own drawing commands are all simulated 50 -> 66 of 519; unsimulated skill-specific command uses
66 074 -> 49 785. Hurricane Blow still lacks `6c10 / 6c18` (3D turns) and `6540`; Purgatory Palm `66c0` and `2890`.

### What is still approximate

* Particles (0x44xx) follow the game's code since 2026-10-12 (below). Not ported: the rings' (`cmd_44b5`) own
  timing details, `cmd_4419` / `4442` / `4482` / `44a0` / `44b0` / `44df` / `44f0` (rare), the emitter's drift
  vector (+0x60) and a gravity other than straight down. Macrocosm's sparkles (1128-1180) now match the recording;
  its explosion cloud (660-760) looks smaller than in the recording, mostly because the camera there differs.
* Rotation orders other than the default (`cmd_3c78`), attaching an effect's size / turn to an actor (3cbc-3cbe)
  and some unit flags (6600 / 6610) are not drawn.
* Several targets follow the shape's cell order (the order the game seems to collect them in); a unit's own way of
  being hit (its hurt motion) is the same sprite for every enemy, and per-target script variables other than
  `$60400 + i` (e.g. `$60800 + i`, `$62100 + i`) stay 0.
* Moves other than 6642 / 6672 / 6680 (6650, 6674, 6678) and the sprite's anchor flags are not simulated.
* The HUD's numbers are percentages of the skill's damage, not damage.
* Some greyscale (LA88) effect models are drawn orange by the game (Girl Laharl's 107 and the smoke 119, seen
  2026-10-12); the kit draws them white. Likely the same unknown as the heart below. See SKILL_ANIMATIONS.md.
* The screen fade colour (`screen_color r, g, b`, 128 = full, with `screen_fade`) isn't drawn: Meteor Impact washes
  the whole screen orange with it (the restyle tool recolours it; Thunder Impact flashes blue).
* Dazzling Eyes' heart is pink-red in the game (the Prinny inside it looks pink too); the kit draws it white. Ruled
  out: the model (1501: white vertex and mesh colours, greyscale LA88 pictures), the slot's colour (0x80808080 at
  load, no `cmd_3c80` on it), the play count (815's pink cloud does end after one run), reading the two-layer LA88
  textures as one RGBA picture (it makes Macrocosm wrong), the pose stubs' colours, the effect pixel shaders (texture
  × vertex colour × 2), RGB565 textures (fixed: 903 and 1500 now decode right, the heart stays white), another copy
  of effect 1501 (only Start_JP.dat has Effect.dat; the loader reads effect%04d.obf), a script branch (slots 9-14
  always load 1501, no colour on them). Effect 1500 does hold a pink heart (RGB565), but the script shows it only at
  frame 186. Reading the two layers as one RGBA picture (R, G = layer 0, B, A = layer 1) gives exactly the game's
  pink heart but turns Macrocosm's sphere purple. Needs a look at the slot's colour in the running game.
* Macrocosm frames 106-112: the game draws Killia (actor 1002) under the cloud sphere (205) and the blasts, so she
  vanishes; the kit leaves her on top. The sort rules are traced and match (queue 6 sorted far to near, an effect
  piece by the depth of its mesh's first three vertices + bias, a sprite by its feet's depth − 7 map units, ties in
  draw order; the recording's numbers agree). Ruled out: one key per model part (the game loops per mesh), the
  effects turned 180°, y mirrored in the key, the vertex colour scale, the draw queue (all 6), a tint on her
  (draw object unchanged; `cmd_6470` is the shadow; actor 1003 is an invisible helper). Needs the game's sorted draw
  list of such a frame.

## How edits are stored

* Values come from where the script really has them (`Op.src`). A value inside a helper event that was passed by
  `call_event` is changed in that call's argument. A value fixed inside a shared game helper (12xxxxxx) can't be
  changed; its box is greyed out.
* **Moving** changes waits, not commands:
  * A command moves inside its straight-line block of the event (between `if` / `loop` / waits for children); the
    `wait`s around it are split again, so nothing else moves.
  * Moving past the end of its block would delay everything after it, so the moved commands go into a small event of
    their own instead. It is started where they were, and waits the extra frames first.
    * When one part of a move has to go into its own event, every part does, so the commands keep their order (a
      clip's load still runs before its show on the new frame).
    * A moved call the event waited for stays waited for (`call_event` + `wait_children`); anything else is
      `spawn_event`.
    * Commands that read the event's locals (`$20014` set by `local_calc` per facing, …) get them as call
      arguments (`call_event NEW, $20014, …`; inside they read `$20001…`), which is exact for every branch.
    * Commands that use the loop counter (`$20100`) can't leave their loop; they move inside their block.
  * Earlier than the start of its block isn't possible; the move stops there and the status line says so.
  * A command inside a helper that runs more than once (the Dragon King's fire puffs: one helper, 16 calls) moves by
    moving its call.
* **Adding** puts new commands into layer events (root + 500 …): `wait <frame>`, the commands, `wait_children`.
  The first layer turns the root into a host: the root's own code moves to root + 499 and the root becomes
  `spawn_event <layers…>`, `call_event <root + 499>`, `wait_children` — so the layers run beside the skill's body
  instead of inside it (see below). A new effect gets a free slot from 200 down: `cmd_3c00` load, `cmd_3c10` show,
  `cmd_3c80` fade over the last 10 frames, `cmd_3c02` remove. Flight path presets (Arrange tab) are layers too, with
  one `if ($60201 == n)` branch per facing.
* The skill ends when its root event ends.

### Threads (seen in game 2026-10-08)

* **`wait_children` / `wait_children_c` wait for every child thread, `spawn_event`'s too** — not only `call_event`'s.
  A root that spawned 8 long path events at its start stalled at its first `wait_children_c` (after
  `call_event 12000010`) until they had all ended, so the effects came ~150 frames late. The simulator now counts
  spawned events as children (74 of 509 vanilla skill previews got a little longer, mostly +20 frames of closing
  flashes), and added events no longer sit inside the body (the host above).
* **Every event must end with `wait_children`** (all 6017 vanilla choreography events do). An event that just runs
  out of code never ends in the game — the skill stalls with nothing on screen. The editor ends every event it makes
  with it, and installing / ▶ Preview in game adds it to any mod event without one (`skills.ensure_end`).

## Values passed to helper events (from the exe)

* `call_event` arguments become the callee's locals `$20001…` as floats: argument / 10 (`0x14008a000`).
* Commands read a local:
  * as an **int** operand (slots, actors, effect ids, frames) by truncating it;
  * as a **fixed** operand (positions, sizes, camera offsets) by multiplying it by 10 (shared decoder
    `0x140086970`).
* `d5lib/data/script_operand_types.json` has the kind of every operand of 563 of the 567 commands; it is made by
  `_research/exe/operand_types.py`.
* Example: `call_event 15130101, 10, 1060, 12560, -60, 80, …` → `cmd_3c00 $20001, $20002` loads effect **106** into
  slot **1**; `cmd_3c10 $20001, $20003, $20004, $20005 …` shows it on actor **1256** at x **−60**, y **80**.
  (Effect "1060" was never a model number: there is no effect1060.)
* `local_calc i, a, op, b` (`0x140184020`): local `$2000i` = a / 10 *op* b / 10. op: 0 add, 1 subtract, 2 multiply,
  3 divide, 4 remainder (3 and 4 on ints). `local_set i, b`: = b / 10. Read back like call arguments, so
  `local_calc 14, 0, 0, -40` + `cmd_3c10 0, 11001, $20014, …` places the effect at x −40.
* `loop a, b` runs b − a + 1 times (counter from max(a, 0) to b, `0x14018c6b0`); `$20100` is the counter.
* **`wait_children` ends the event.** `wait_children` / `wait_children_b` (0x0108 / 0x0118, `0x14018c080`) wait for
  the event's children and then END the event; with no children they end it at once. Vanilla loops exit that way
  (`if ($20013 >= $20012)` + `wait_children`). `wait_children_c` (0x0120) waits and goes on.

## Checks

* `tools/_skilledit_test.py OUTDIR [skill ids] [--edit=DIR]` opens the kit offscreen and saves screenshots.
  `--edit` also runs the edit flow (copy, move, add, save, reload) in a throwaway mod in DIR, and prints how fast
  frames draw.
* All 567 vanilla skill / monster-attack choreographies simulate without errors and end by themselves, with both
  facings tried. Median length: magic skills 238 frames (4 s), monster attacks 326 frames (5.4 s).
* Drawing speed (1700×1000 window): 150–180 fps for typical skills, 40–55 fps for the busiest (60+ effect slots,
  after-images). Playback is timed by the clock, so it stays at real speed either way.

## Play count (seen in game 2026-10-08)

The last value of `cmd_3c10` / `cmd_3c20` is how many times the model's own animation plays before the effect
disappears: 0 or 1 once, −1 forever. A model whose animation is 0 frames long (many still pictures: 1723, 1915 …) never
appears with 0 or 1; vanilla shows those with −1. The preview follows this rule. New models from `fxbuild` get a
60-frame looping animation, and the Talisman Storm cards are shown with −1.

`cmd_3c10` is `cmd_3c18` with the frame values left 0: both go through one function (0x140178da0; the 3c10 handler
0x140178cd0 passes its play count where 3c18 has its 8th value). What the second size value of 3c18 / 3c22 does (0 in
skill 818) is still unknown; the preview ignores it.

## Blending and motions (seen in game 2026-10-08)

* **Blending** is per mesh: flags byte 0 = 1 normal alpha blending, 2 (and 3) adds light. The Talisman Storm card
  first copied effect 1200's 2 and turned white where cards overlapped; `fxbuild.picture_model(..., blend="alpha")`
  (the default) writes 1, 2 as vanilla's picture quad 1723 has. The preview reads the same byte.
* **Motions** (`cmd_6510 actor, motion`) aren't always animation motion × 10: on humanoid classes motion 109 (cast)
  plays 1051 / 1057 (arms raised; 1091 is a plain stand) and 151 plays the class's special pose 7011, which only exists
  facing front: from behind, the unit is invisible during it. The preview knows these two (`render.MOTION_BASE`);
  the others still use × 10. The new Talisman Storm keeps the cast pose instead of 151.
* **Extra actors**: `cmd_6402 actor, sprite` makes a monster appear (Beast Rush: 16 Orcs + 2 Grizzlies),
  `cmd_6500 actor, ±anim` picks its animation (11 walk front, 17 walk back, minus = mirrored), `cmd_6570` its speed,
  `cmd_6642 actor, base, x, y, z, frames, 0` moves it relative to another actor; `cmd_6480 … 0, n` fades it out.

## Damage (seen in game 2026-10-08)

The choreography deals the damage itself: `cmd_7220 actor, actor, percent` hits for that share of the skill's damage
(the number pops up then), and `cmd_7228 actor, 30` finishes it. A script without them plays but deals no damage —
the first Talisman Storm v2 did that. Single-target skills hit 3600; area skills hit 3000 + i for every
`$60400 + i == 1` (up to 16). `12000045` / `12000020` only shake the camera and play the target's hurt motions.

## Worked examples: the class skills (2026-10-08, verified in game)

* **Talisman Storm** (Onmyo Monk, `_research/make_talisman_storm.py`): 8 talisman cards (effect 3002, built with
  `fxbuild` from the picture in `_research/talisman_card.py`) appear around the monk one after another, circle him
  faster and faster (`cmd_4140` moves along 16 points per turn), then fly at the target one at a time (`cmd_4170`,
  spinning), each dealing its share (7 × 12 % + 16 %), and a purple burst ends it.
* **Beast Rush** (Beast Master, `_research/make_beast_rush.py`): she roars, 16 Orcs and 2 Grizzlies (D5 has no boars)
  appear behind her in four waves and charge past the target with her, each wave hitting (4 × 25 % to every target),
  then fade in dust. Direction and run animation per target facing (`$60202`) — checked in game from two sides.
* Both scripts rebuild the mod's events (and the card models) and keep a backup of the previous skills.json in
  `_research/backup_*`. New hires don't know these skills yet (Beast Rush is learned at level 60); for tests
  `tools/battle_nav.learn()` teaches a skill in memory only.

## Sounds (`d5lib/sfx.py`, `d5gui/skilledit/audio.py`)

* `se_play id, volume, speed` plays `Data/Sound_SE/Sound_SE_0.dat` member `NNNN.vag` (381 sounds, MS-ADPCM WAV,
  decoded in the kit); volume in percent, speed 1000 = normal (the game divides by 10 and by 100: handler
  `0x14018b5c0`); the preview changes pitch with speed, as a faster playback does.
* `voice_play_actor v, volume` (`0x14018b9b0`): category = v ÷ 10000, actor = v mod 10000 (0 = the skill's user).
  The game picks a random line of the unit's voice set in that category (`0x140226c00`) from the database table
  `Sound_Voice_EN_0.dat` (48-byte rows: line id, voice set, category flags at +0xa + category). Voice set =
  char.dat `voice_id` × 10 + personality (kind 0 of a voice; see [VOICES.md](VOICES.md)). Lines are
  `NNNNNNNNN.vag` in `Data/Sound_Voice/Sound_Voice_0.dat` (d5lib/fafs.py). The preview picks a fixed line per key,
  custom voices of the mods included (d5lib/voices.py `VoiceBank`).
* Mixing: `audio.Mixer` (QAudioSink, 48 kHz mono, soft-limited when many sounds overlap).

## Particles (`d5lib/particles.py`, measured in game 2026-10-08)

The pictures are `Start/particle.txf`: 4 × 4 cells of 64 px (glint, smoke, sparkle, glow, wisp, crystal shard,
cloud, feather, star, streak, ring, cross sparkle); `cmd_4400`'s second value picks the cell. The handlers give the
value scales (speed ÷ 10 × 0.12, sizes and alphas ÷ 100, drag / gravity ÷ 1000); the rest was measured with
colour-coded test choreographies (`tools/_particle_test.py count|timing|scatter|speed|size`, sent live as Talisman
Storm's animation):

| Seen | Rule |
|---|---|
| a burst's particles all appear at once | count ≈ 0.45 × the emit command's rate |
| they disappear together | life = the emit command's frames (`cmd_4480` / `cmd_4490` 7th value), not `cmd_4430` |
| `cmd_4430 e, 60` → a wide cloud, `10` → tight | `cmd_4430`'s value is how far along their direction particles start (map units; traced, below) |
| a 0° cone lines them up toward the target | directions are around the caster's facing; `cmd_4490` adds up / turn angles |
| speed 100 flies off screen in ~10 frames | speed × 0.12 script units per frame |
| size 0 → 400 → 800 grows, alpha 100 → 100 → 0 fades | start / middle / end of each particle's life |
| `cmd_44b5` keeps adding particles | `count` every `every` frames for `frames` frames |

Particle size: 100 % = 20 script units across (traced, below).

Traced / probed 2026-10-11 (Macrocosm's draw records at frames 680-683):

* `cmd_4420 e, mode` is the blend mode (emitter +0x54), default 2 = adding light; 1 normal, 3 screen − colour …
  as `cmd_3cd6`. The smoke cloud (no 4420) is drawn adding light (render state 0x1015), the 4420 … 3 glows with
  blend 3 (0x1915). The kit used to pick by picture (smoke = normal blending) and drew grey smoke where the game
  shows a bright white cloud.
* `cmd_4410 e, r, g, b` sets the emitter's colour at once; `cmd_4418 e, r, g, b, a, n` fades its colour and
  opacity there over n frames (both through the game's animated value). Particles show the emitter's current
  colour (the probe: exactly the 4418 colour right after it).
* `cmd_4450 e, value` is a depth bias, like `cmd_3ca0`: value / 20 map units toward the camera (emitter +0x50 →
  the record's bias, 0x1403deac0).
* Every particle is its own record in queue 6 (sorted with the effects one by one), without depth writes.

Traced 2026-10-12 (spawn 0x1403dda00, draw loop 0x1403de3a0, emission update 0x1403ddf80 / matrix 0x1403dc790,
handlers 0x140185800-0x140188470, interpolators 0x140089ec0):

| Command | What the game does |
|---|---|
| `cmd_4400` drag | share of its speed a particle keeps each frame (÷ 1000): the distance is speed × (1 + d + d² + …), whole frames then a fraction of the next; drag 0 = one step and it stays |
| `cmd_4400` gravity | ÷ 1000 map units per frame², positive = down (the game's y axis points down) |
| `cmd_4400` sizes | a particle's quad spans ± size map units around it (100 % = 20 script units across), turned by its angle |
| `cmd_4480` / `4490` 8th value | the frame of the size / opacity curve's middle point (7th = life); the kit used to treat it as a scatter |
| `cmd_4430 e, dist, var` | a particle starts random 0 … dist map units out along its direction; its speed is × (1 − random × var ÷ 100) |
| `cmd_4438 e, on` | start anywhere in a ball of that radius instead |
| `cmd_4439 e, mode, speed, factor` | speed as 4400's; mode 0: factor ÷ 1000 is the drag; mode 1: distance = speed × age + (factor ÷ 100 + 1) × age² ÷ 2 |
| `cmd_4440 e, spin` | every particle starts at a random angle and turns at a random speed up to ± spin ÷ 2 degrees per frame |
| `cmd_4428 e, k` | the emitter's clock: its particles age k ÷ 1000 frames per frame from then on, flying ones too (0 freezes them) |
| `cmd_44c0 e` | the emitter's particles are removed at once |
| `cmd_44d0 e, n, sx, sy` (`44d2` + ease) | particle size × sx ÷ 1000 across, × sy ÷ 1000 up, reached in n frames |
| `cmd_44d4 e, n, x, y, z` (`44d6` + ease) | the emission (start points and paths) stretched × ÷ 1000 per axis, x / z across / along the facing |
| `cmd_44d8 e, n, x, y, z` (`44da` + ease) | the emission turned x, y, z degrees |

The n-frame changes (44d0-44da) start from the value at that moment and apply to particles already flying; their
ease value ÷ 1000 bends the progress (≥ 0: progress^(v + 1), < 0: progress^(1 / (1 − v))).

## Effect model animation (`d5lib/fxanim.py`)

Every effect model carries its own animation in sections 2–5 of the .obf (decoded 2026-10-08; all 383 models
round-trip byte-exactly):

| Section | Content |
|---|---|
| 2 | node count, length in frames, loop (0 once, 1 loop, 2 ?), node order |
| 3 | nodes: the part it draws (section 6 index, −1 none), parent node, key list. Several nodes can draw one part (sparks). |
| 4 | keys: 10 curve-point indices = translate x y z, rotate x y z (radians), scale x y z, alpha |
| 5 | curve points, 16 bytes: value, type << 24 \| frame, tangent in, tangent out. Type 3 smooth (Hermite, tangents per segment), 0 straight, 4 hold. |

A node's matrix is parent × translate × rotate (z·y·x) × scale; alpha multiplies down the tree. Flipbooks are nodes
fading in and out in turn (effect 106: 4 flame pictures over an 18-frame loop); magic circles spin and grow (1418).
`cmd_3c18` / `cmd_3c22` play the model from frame a to b (direction 1 / −1, 0 = still frame a); `cmd_3ca0` sets the
speed.

## New effect models (`d5lib/fxbuild.py`)

A mod can carry whole models of its own: `"effects": {"3002": {"from": 1200, "obf": "fx3002.obf"}}` in skills.json;
the installer adds them to Effect.dat and EffectTableDataBase. `fxbuild.picture_model(base, image, w, h)` puts a
picture on a quad of w × h map units (base 1200: one alpha-blended DXT3 quad in the scene; 1915–1918 are 16:9
backdrop pictures; the texture takes the picture's size),
`fxbuild.static()` / `fxbuild.spin(axis, frames, turns)` make simple animations, `fxbuild.save(mod, id, model, from)`
stores it. `tools/render_skill.py SKILL OUTDIR` renders a skill's frames + a contact sheet with the kit's preview.
