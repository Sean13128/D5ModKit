# Outfits — how they work

## In game
Characters → select a unique character → **Outfit** → *Default* or an outfit name. The unit's class id
switches to the outfit's char.dat row (a copy of the character: same stats, skills, name) and the hub
character, faces and portrait change at once.

## Mod data (`mods/<mod>/patches/outfits/`)
* `outfits.json` — `pairs` `[[base class, outfit class]]`, `names` `{outfit class: "Swimsuit"}`,
  `own_sprites` (sprites with their own full animation set), `hide` (other mods' outfits this mod takes out of the
  Outfit list: they stay members of their group with label 0, so a unit wearing one keeps its identity and can
  switch back; verified in game 2026-10-11).

**An outfit row follows its character** (`outfits._follow_base`, at install): the outfit's char.dat row is a copy of
the character's, and after all mods are applied every field except the look (`id`, `sprite_id`, `color_id`; for a
humanoid outfit of a monster-type character also its body fields and weapon mastery) is set from the character's
row. A change any mod makes to the character -- stats, skills, evilities, Overload, names -- applies whatever outfit
it wears (verified in game: Killia in a DRPG outfit got her new evility and skill). Before, outfit rows kept the
values of the moment they were made.
* `face_<slot>.png` — the outfit's face picture (optional).
* files: `anmN` (outfit sprite), `anmN+1` (copy), `anmN+2` / `anm<slot+2>` (small standing picture),
  `anm<N+10000>` and `anm<slot+10000>` (portrait / cut-in).

Outfit rows use unused "Unique Dummy" rows (470, 480, 490, 950 … 990), so old saves keep working.  When those are
taken, new outfits get **inserted rows** (`outfits.EXTRA_SLOTS`: 471-479, 481-489, 491-497; 498/499 are skipped
because anm00500/501 belong to Seraphina).  char.dat is sorted by id when the game loads it, so an inserted row
shifts the index of every row after it; saves store that index (unit+0x2E0A), so the runtime (`d5core.dll`,
`d5rows.inc.c`) re-runs the game's own fix routine (0x14015EB80) for any roster unit whose stored row no longer
matches its class.  A unit with more than 3 looks keeps its colours per look in `d5looks.bin` (`d5looks.inc.c`,
called from the outfit switch hook).

* `source_<sprite>.anm` — the outfit's full-colour source; part edits always rebuild from it.
* `partmap_<sprite>/painter.json` (+ `override_k.png`) — the part painter's state (see docs/COLORS.md).

## Sprite sheets
Two kinds of input:
* **Labelled sheets** (`SpriteSheet/<char>/<char>_<outfit>_SS.png`): rows of labelled poses.
* **DRPG atlases** (`DRPG Assets (Updated)/Characters/Sprites/{front,back,wait_front,wait_back}/<id>.png`, or the
  older `Sprites/Standard/...`): packed, trimmed frames without labels.  `d5lib/drpg.py` cuts the pieces and matches
  them to the poses of a reference built from Girl Laharl's labelled Swimsuit sheet (`d5lib/data/drpg_ref_humanoid.pickle`,
  `_research/drpg_make_ref.py`) by silhouette + skin + hair masks, then assigns them one-to-one; each frame keeps
  its original canvas and offset.  **Exact frames (2026-10-02):** DRPG atlases are not trimmed -- every frame sits in a fixed rectangle at its canvas
position, and the rectangles are the same for every humanoid unit.  `d5lib/data/drpg_slots.json` holds them (made from
Girl Laharl's labelled frames by `_research/drpg_make_slots.py`); `drpg.slot_unit(uid)` cuts each frame out of its
rectangle, so label and placement are exact, like a labelled frame dump (checked: unit 68 gives the labelled sheet's
placement for all 101 frames).  Idle sheets laid out on another grid are placed by registering the frames on their
unmoving lower body; only the first 512x512 block of an idle sheet is the loop (a second block holds a variant or an
upper-body layer).  Pixels with alpha <= 8 are compression noise and ignored.  After building,
`outfits.lock_idle(fs, mod, slot, ref_slot=470)` keeps the idle feet exactly still (unmoving pixels registered on the
first frame) and puts the idle on the stand pose's ground like the reference outfit.  `_research/rebuild_drpg.py`
rebuilt the 7 Girl Laharl DRPG outfits this way and carried their finished colour parts over pixel for pixel
(`d5lib/parttransfer.py`; frames the old build lacked learn their parts from the others).
Icons and cut-ins come from `Characters/Icons/<id>.png` and
  `Characters/Cut-Ins/<id>.png`.  `_research/make_drpg_outfits.py` made Girl Laharl's DRPG outfits
  (192, 193, 258, 294, 332, 348, 378).
`d5lib/framesheet.py` finds the rows and recognises the labels. `d5lib/cellmatch.py` maps every **original
pose image** of the character to a sheet frame (exact canvas size first, rows locked in order, back view =
front twin's row, mirrored views detected automatically). `d5lib/ownanim.py` builds a sprite containing the
whole humanoid motion set, with the original transforms, so timing, motion, facing and weapon placement are
the game's own. Idle frames are pinned to one place (no jitter).

## Game code (`d5lib/exepatch.py`, new `.d5mod` section)
| site | purpose |
|---|---|
| 0x140263875 | rebuild the unit sub-menu on opening (adds *Outfit* for characters with outfits) |
| 0x140263432 | confirm: *Outfit* → re-open the menu as the outfit list; outfit entry → set class, refresh unit, rebuild sprites (hub leader 0x142349160, actor tables) |
| 0x14067e7d1 | party preview rebuild when the class changed |
| 0x14014d354 | outfit sprites animate with their own block |
| 0x1402ae881 / 0x14043088e | status panel / Status screen face → animation 10000 + outfit class |
| 0x14021e9d0 | graphics id of outfits with a face = their class id (battle face) |
| 95 sites (`.d5id`, `d5lib/identitypatch.py`) | "is this unit character X?" checks see an outfit as its character (below) |
| 0x1402f1a6f / 0x1402f200f (`.d5sc`, `d5lib/scalepatch.py`) | own sprites numbered 10000+ drawn at full size, their portraits 20000+ at portrait size (below) |
| 0x140159f37 / 0x14014e0f1 (`.d5hm`, `scalepatch.humanoid_patch`) | own humanoid sprites numbered above 2000 are not monsters (below) |
| 0x14015b1b0 (`.d5ss`, `scalepatch.script_sprite_patch`) | skill scripts see an outfit's sprite as its character's (below) |
| 0x1401683fd / 0x140168729 (`.d5ev`, `d5lib/eventpose.py`) | a skill's event pose (cmd_6402 / 6405 7000, 7002) comes in the caster's outfit look (below) |

### Outfits change the class id: identity and size fixes (2026-10-09)
* **Character checks.** An outfit turns its unit into the outfit's class id, but the game recognises its characters
  by class id: 47 `cmp [unit+0x2e04], <id>` plus 33 more on a loaded copy (Killia 10, Seraphina 40, Usalia 70 ...,
  story characters) and 15 "find the unit / actor of class X" loops (`d5lib/data/identity_sites.json`, made by
  `_research/find_identity_sites.py`).  With Killia in an outfit, the army search for class 10 at 0x1401cdc90 found
  nobody and the next line read through a null pointer: **the game crashed after a won battle, on the way from the
  results to the Netherworld map / hub** (fault offset 0x1cdd26).  Every site now compares the unit's base class
  (outfit slot -> character, legacy rows -> character; find loops map both sides).  Unit setup / copy code that
  needs the exact class (0x14015e907, 0x14021908a, 0x140219cab) and a site next to the runtime Custom Color hook
  are left alone.  Verified in game: Killia in Tyrant Overlord Killidia clears a stage, the lookup runs (traced) and
  the game reaches the hub.
* **Two-thirds size.** The game draws animation blocks 10000-19999 / 30000-39999 at 0.67 (portraits, cut-ins), and an
  own-animation sprite is drawn from its own block, numbered like the sprite: every outfit / new character sprite
  numbered 10000+ (Laharl's DRPG outfits on, Girl Laharl's Magical Girl .. Young Thunderlady, Future Usalia,
  Liezerota) was drawn at two thirds of its size.  The scale is skipped for the kit's own sprites (portraits keep
  it).  Verified in game: Supreme the size of the Swimsuit look.
* Girl Laharl's DRPG "New Years" (unit 103) is left out: the same drawing as the Attired Girl outfit.
* Killia's Awakened / Tyrant Overlord Killidia (DRPG 39 / 40) jumped in the back views (feet moving 14 px, 9 px
  sideways in the back walk): rebuilt and steadied with `stabilize.corrections` against Formal (same animation
  tables), feet only -- `stabilize_outfit`'s stand-pose replacement made the back stand 191 px tall and added 40 px
  jumps to the animations starting from it, so it is not used for drpgmap outfits.
* Quest descriptions are word-wrapped into the five 36-character lines like the game's own (`dbpatch.quest_lines`;
  the new-character wizard and `create_drpg_character` use it).

### Skills and portraits with the kit's sprites (2026-10-10)
Found with Seraphina's skills in her Formal outfit (sprite 9740) and Liezerota's Status screen; each fix covers every
character.
* **Helper numbers.** Skill scripts spawn helper actors with fixed numbers (`cmd_6402 / 6403 / 6405 / 640d actor,
  NUMBER`; a number with no class or sprite gives an invisible helper).  Girl Laharl's outfit row 9002 made Tri-Burst
  spawn her above the target.  `d5lib/data/script_spawn_ids.json` (`_research/find_spawn_ids.py`) lists the numbers;
  `sprites.used_sprite_numbers` includes them, so no new row, slot or sprite takes one, and `identitypatch.class_map`
  skips them.
* **Attachment cells.** The shared motions' stub animations (1001 -> 6001, 1501 -> 7001, 1511 -> 7011 through a
  parameter) are a control key plus an attachment key whose cell is an empty cell (w = h = 0).  Merging an own block
  re-pointed some of those keys at real cells; `ownanim.restore_attachment_cells` keeps them on empty cells (run by
  `ownanim.build` and `drpgmap.build`; `_research/fix_attachment_cells.py` fixed 9328 keys in the existing mods).
* **Humanoids above 2000** (`.d5hm`): the game takes a sprite above 2000 for a monster (battle actor draws sprite + 1,
  0x14014e0a0 mode 3 says "monster").  The kit's humanoid sprites (9500+) count as humanoids; monster families
  (class template 2000-2999) keep the monster rules.
* **Character-specific choreography** (`.d5ss`).  Skill scripts branch on the sprite number of a unit's class
  (`$62100-$62199`, from 0x14015b130 = char.dat `sprite_id`; ~600 comparisons: event poses, voices, offsets, hit
  timings).  Dazzling Eyes: `if ($62199 == 40) cmd_6402 1001, 7002` spawns Seraphina's event-pose actor (anm 7002,
  animation 8521), which shows her for most of the skill while the caster and the skill's copy of her (light actor
  table, `cmd_6410`, alpha 0 from its animation 1 on -- in vanilla too) draw nothing.  With sprite 9740 no branch
  matched and she vanished.  The getter now maps every outfit's own sprite to its character's vanilla sprite and a
  new class's to its template class's (`outfits._script_sprites`).  New characters keep their own number (they move
  like their template, Girl Laharl, which no script singles out; Usalia's branches would be wrong for a humanoid).
  Event poses exist for Killia (10 / 20 / 30: Avidya Holy Water, Macrocosm) and Seraphina (40 / 500: Dazzling Eyes,
  Heart Ensemble, Malicious Eye, her Overload).  Every use of `$621xx` is a comparison or a copy into a local that is
  compared.
* **Event poses in the outfit's look** (`.d5ev`, `d5lib/eventpose.py`, `tools/drpg_outfits.py events`).  Vanilla gives
  alternate forms their own event sheet (Seraphina 500 -> 7013 bunny); every DRPG outfit of Killia (sheet 7000) and
  Seraphina (7002) gets one too, numbered outfit sprite + 3 and listed in `patches/outfits/event_sheets.json`.  The
  vanilla sheet is copied with all its animations and effect drawings; each whole-body drawing is matched by
  silhouette, **as shown on screen** (some are stored sideways and drawn turned 90 degrees; mesh nodes give four
  corners), against the character's DRPG twin's front / back / idle frames (mirrored too, tumbling frames skipped) and
  replaced by the outfit's DRPG frame in that slot, placed the same way (new pivots / corners).  Face and hand
  close-ups laid over a body are hidden.  **The game draws every cell with the colour variant's palette and ignores
  the cell's own palette number** (outfit palettes appended after the sheet's came out scrambled in game), so a sheet
  has one palette for the outfit's drawings and the kept sparkles (re-indexed) in every variant.  At install the
  hook in cmd_6402 / cmd_6405 swaps the number when the caster's class is that outfit; the caster is **actor 6101**
  for the lookup 0x1402eac10 (the scripts' 1256 is translated before it; the lookup returns nothing for 1256).
  Verified in game: Seraphina's Dazzling Eyes in Formal and Killia's Macrocosm in Formal show the outfit throughout.
  Still vanilla: Macrocosm's closing transformation spawns Killia's forms 20 / 30 by sprite number.
* **Portrait size.** The Status screen and skill cut-ins draw block sprite + 10000.  For sprites numbered 10000+ that
  is 20000-29999, which the game never scales to 0.67: Liezerota's portrait (23040) was 1.5 times too big and spilled
  out of the frame.  `.d5sc` scales those portraits like the game's own (no vanilla block is numbered 20000-29999).
  The Status screen clips a portrait to its window; vanilla portraits are full-bleed close-ups.
* **Portrait pictures.** Disgaea RPG cut-ins (260 x 836) have the game's portrait proportions: `outfits.fit_portrait`
  scales them to fill the 336 x 1080 texture (a margin would show as a white bar in skill cut-ins, which put the
  strip on a white panel).  Only white that touches the picture's edge **and reaches into its top quarter** is made
  transparent (`imgtools.remove_white_background(..., upper=0.25)`; the light area is shrunk by 2 px first, with the
  outside counted as light, so it can't leak through gaps in the outline): close-ups are cut off at the sides and
  bottom, where white clothes (Santa Seraphina's fur) touch the edge too.  Regenerated for all 176 DRPG portraits.
* **Layered idle sheets.** Some DRPG wait sheets draw hair / capes as separate pieces in the right half of the atlas
  (Liezerota's long hair in her front idle): `drpg.wait_layers` pairs each piece with the body it overlaps and
  `wait_frames` composes them (in front of the body in back views, behind it otherwise).  A wait sheet drawn from the
  wrong side is ignored (`drpg.WRONG_VIEW`, unit 261's back idle; the battle stand frame is used instead).

Dev tools used (all need the harness, `remote=1`): `tools/_skill_test.py NAME OUT "SKILL"` (cast with burst
screenshots), `_actor_watch.py` / `_actor_dump.py` / `_actor_pair.py` (actor tables), `_draw_list.py` (every draw
object of a skill with its quads), `_copy_prims.py` (the quads one draw object queues, through a thunk in the game),
`_copy_trace.py` / `_copy_inst.py` / `_actor_poke.py`.

## Colour-id resources
A character's graphics are keyed by char.dat `color_id`. Outfits in slots 470–490 get their own colour id
(= slot), and the installer provides every resource keyed by it:
* resident block 9017: animation 10000 + colour (face) and colour (framed battle face),
* resident block 9018: name banner of skill cut-ins,
* `anm 10000 + colour`: portrait / cut-in,
* `texture.dat` small face atlases (`wf_unique0N_48/64px`): cell for the colour id (list icon).
  Every outfit has its own colour id (= its slot).  Slots 470/480/490 use the game's own cells; every other slot
  (950-990, inserted rows 471...) gets new texturedatabase rows after the last one and a cell in the free part of
  `wf_unique02_48px` / `_64px` (12 cells in all; 6 used by 950-990, 471, 472), drawn from its face picture or the base character's face.  Exe
  section `.d5fi` (`outfits._add_icons`): a hook at 0x1401a2460 (colour id -> list icon row) returns those rows, one
  at 0x14019fbc0 (row -> texture) gives them the unique02 textures (64 px row = 48 px row + 817).
* DRPG face icons look right; the game's faces look left: `make_drpg_outfits.py` mirrors them (`set_face(..., True)`).

The resident pack (~415 MB) is edited with `d5lib/lzs_splice.py`, which reuses the original compressed data
(LZS back-references reach only 255 bytes).

## Colour presets
Automatic when a sheet or a Disgaea RPG unit is converted (`colorvariants.repartition`, then `derive_parts`):
* **Palette** (`ownanim._palette`): one shared 255-colour palette for all drawings -- Pillow's octree palette refined
  by weighted k-means (colours weigh pixels ** 0.55, so eyes and highlights keep colours of their own). Against the
  Disgaea RPG drawings: mean dE 2.4 (the octree alone: 3.4).
* **Parts** (hair, hoodie, skin, bikini, gold ...) = colours of the same tint (Lab, lightness down-weighted), each
  part in palette rows of its own (the Strategy Assembly's precise colour editor edits rows of 16); the small details
  (eyes, mouth) in row 0. The part info is saved as `patches/outfits/parts_<sprite>.json`.
* **Presets 1..** follow the base character's own presets part by part (`d5lib/recolor.py`, 2026-10-13): the new
  sprite and the base character are drawn in the same poses (index rendering, no mixing), which tells for every
  colour which of the character's parts (her palette rows) lies under it. Every material (a part of the part info;
  touching parts of the same tint and the same position are merged) takes ONE of the character's parts:
  * the same colours as one of her parts, where that part is: that part (her hair, her eyes);
  * lying mostly over one part and about as light: that part whatever its hue (red demon hair where his blue hair
    is follows his hair);
  * otherwise the part it lies over that fits its colours (a gold crown above the head follows her gold bracelets);
    fitting none: it keeps its colours, like the game's own metal and outlines;
  * skin follows skin only, and skin tones over her skin are her skin;
  * a small undecided material (edge shades, stray bits) joins the material it touches most.
  In a preset every colour takes its part's change along the shading ramp (the part's shades nearest in lightness
  carry their new colour, the colour keeps its own offset: lightness added, saturation scaled, hue turned when it is
  of the part's colour family). Measured on the game's classes against their pixel-identical Disgaea RPG twins (the
  artist's presets are the answer): 3-4.6 dE from the real presets (the earlier hue matching: 12-16).
* *Re-derive color presets* uses the part info with the current colours, so recolouring a part in Sprites & Colors
  and re-deriving keeps the new colours. `tools/rederive_colors.py [MOD ...]` re-derives every sprite with part info
  (outfits, new characters and their outfits; the base of a new character is the game character whose animations it
  plays). All the kit's own sprites were re-derived on 2026-10-13.

## Capacity (2026-10-06)
* **Ids below 1000** (unique characters' outfits and new unique characters, shared): `slots.unique_pool` -- every id
  the game has no row for whose colour-keyed files are free: anm id + 2 (small standing picture) and 10000 + id
  (portrait), the copies the kit writes for the id; its sprite has numbers of its own (dummy families 470-490 /
  950-990 first): 714 ids (2026-10-12; 550 when anm id, +1 and 10001 + id had to be free too -- nothing reads them
  for a unique id).  The other 185 ids below 1000 without a row have a game sprite at id + 2.
  `outfits.free_slot(mod, fs)` and the Characters page's `free_unique_id` both take from it.
* **Generic classes** get outfits too (`create_generic_outfit`): the outfit is a whole family T..T+5 with T = its
  sprite number (9500+), colour ids T+k, portraits anm 10000+T..+9, faces 9017 T+j / 10000+T+j, a copied JobRank
  chain.  `outfits.json` keeps `[F, T]` (both >= 1000); the menu has one group per rank (F+k <-> T+k).  Sprite
  numbers 9500-22760 in steps of 10: ~1300 outfits.
* **List icons**: `wf_unique02_48px / _64px` are enlarged at install to 1024 wide and as tall as needed (wider
  past 16384): thousands of icons (a generic outfit's colour ids share one). The list adds 817 to an icon's 48 px
  texture row for its 64 px one, so the rows come in blocks of 817 + 817 (`outfits.icon_rows`). Tested in game with
  the icons placed past 900 (`D5_ICON_TEST=900` at install: a 1024 x 4480 atlas, rows in the second block).
* **Faces**: block 9017 has 26 free face spots; the same picture is stored once, and when they run out its
  textures grow taller one after the other (13 first, 1024 x up to 16384: ~300 faces; then the 2048-wide ones, ~690
  each): thousands. `D5_FACE_GROW_TEST=1` at install forces the growth of texture 13, `=2` of the next one (tested
  in game: Thunderlady's face from the grown texture 9; 700 faces placed in an offline test).
* **Sprite numbers** for new looks: groups of 10 from 9500 to 22760, then the free groups between 2400 and 9500
  (~1 750; the portrait 10000 + N must stay below 32768).
* **Ids below 1000 stay the limit for unique looks**: the game treats every class id from 1000 up as a generic
  class (and the kit's own generic families now use 1360-1990, 2340-2390 and 2620-2890), and an outfit's colour id
  (= its id) needs its own standing picture and portrait numbers there.
* Verified in game: Groom Thunderlady's face in the grown texture + icon in the enlarged atlas; a test generic
  outfit on Fantasia (Valkyrie 1020): Outfit menu, face, list icon, class, Status screen.

## New unique characters' own icons (2026-10-07, `d5lib/newchars.py`)
* A new unique character (id < 1000 a mod adds, or a filled-in dummy row; outfit slots excluded) starts as a copy
  of its template, colour id included.  At install (`outfits._finalize` -> `_finalize_characters`) it gets colour id
  = its class id plus copies of the template's colour-keyed graphics: faces (9017 anims id / 10000+id), name banner
  (9018), portrait anm 10000+id (from its own anm sprite+10000, else the template's) and a list icon cell in the same
  icon hook as the outfits (shared 252-icon budget).
* Optional face picture: `patches/characters/face_<id>.png` (Characters page -> "Face picture…").  Without it the
  faces and icon are copies of the template's.
* Ids >= 1000 (generic-class range, e.g. Killixia's legacy 9003) are left alone: there the colour id picks palettes.
* Verified in game: Killixia (970) with a temporary test face -> his own list icon (Arrange view, Q/E scroll).

## DRPG outfits for every character (2026-10-08, `tools/drpg_outfits.py`)
Catalog: `d5lib/data/drpg_outfit_catalog.json` -- for each unique character (char.dat id = sprite) its Disgaea RPG
**twin** (the DRPG unit drawn exactly like the character's own sprite: Killia = 2, Etna = 6 ...) and the DRPG units
used as its outfits.  One mod per character (`DRPG_Outfits_<Name>`, requires Outfit_System); Girl Laharl's go into
`Girl_Laharl_Outfits`.  `patches/outfits/drpg_units.json` records DRPG unit -> outfit slot.

    python tools/drpg_outfits.py check                 every unit has sprites in a known atlas layout, icon, cut-in
    python tools/drpg_outfits.py learn [CLASS ...]     own-pose maps from the twins (parallel; report in
                                                       _research/drpg_outfit_twins.json)
    python tools/drpg_outfits.py build [CLASS ...] [--only UNIT,...] [--rebuild]

How a sprite is made (`outfits.create_drpg_outfit` -> `drpgmap.build(..., specials=True)`):
* **Shared motions** (walk, attacks, damage ...): where the character's twin has the cell exactly, the twin's own
  placement (stored as the positive cells of `drpg_ownmap_<cls>.json`): a unique character's drawings sit 2-6 px
  differently in some shared cells than the generic classes' (Girl Laharl: 26 of 97 cells).  Rebuilding Girl Laharl
  from her own twin: 89% of shared-motion frames >= 0.95 silhouette overlap with vanilla (63% with the generic map
  alone).  Other cells: the exact pose map learned from the vanilla class twins (`drpg_cellmap.json`).
* **The character's own animations**: `drpgmap.learn_unique(fs, cls, twin)` locates every own cell of the vanilla
  character in its twin's atlas (`drpg_ownmap_<cls>.json`).  Idle loops (6001/6007) play the unit's whole DRPG wait
  frames; idle_loops picks the body layer among the layers that really are wait drawings (a unique idle is often
  split into body / arm / scarf layers).  **Skill poses** (7xx1/7xx7) have no DRPG drawing: at every key time the
  biggest character drawing showing is the body (it can move between layers) and plays a whole DRPG frame; the other
  character pieces are hidden (`special_layers` / `strip_special_overlays`); a body cell without an exact location
  gets the twin's DRPG frame whose whole silhouette best matches the vanilla pose at that moment
  (`pose_match_specials`; no mirrored frames -- they turn the unit around -- and no tumbling / hand frames).
* **Effects and props stay vanilla** (`effect_cells`, entries with `keep`): an own drawing not located in the twin
  whose colour histogram overlaps the twin's battle frames < 0.3 is not the character (Killia's slash trails 0.06,
  Rozalin's gatling gun / portal 0.00-0.10; the characters' own pieces 0.4-0.76).  Between 0.15 and 0.3 a big
  drawing whose silhouette matches a twin frame (IoU >= 0.55) still counts as the character (Asagi's darkened body in
  7031).  A special with no confident character drawing at all is an effect animation: everything in it is kept
  (`effect_animations`: Asagi's / Seraphina's emblem).  Kept drawings are the template's own cells, unchanged.
* A slot a unit lacks (one unlabelled frame of an oversized sheet) is replaced by the nearest frame of the same
  move; a shared cell whose character-specific placement points at a piece the unit lacks falls back to the generic
  map.
* `ownanim.assemble` handles **mesh layers** (a cell on 4 explicit corners, groups of 10 points): the crop rectangle
  is mapped through the original quad (before this, mesh effects -- Rozalin's -- vanished).
* Colours, standing picture, face (mirrored DRPG icon), cut-in: as for every outfit.

Not covered (no exact humanoid twin): Meaver (sprite 400 uses only 20 shared cells; DRPG 71 is not its drawing).
**Layered idle sheets** (a body plus its long hair / cape as separate pieces, `drpg.wait_layers`): the layers go
behind the body on the front idle and over it on a back idle that shows the unit's back (Liezerota 163: the long
hair over a short-haired body). A back idle sheet that draws the unit facing the camera -- its layer pieces are
the front idle's, mirrored or not (`drpg.back_idle_faces_front`; Santa Liezerota 261) -- keeps them behind the body,
as DRPG draws it. Of the 20 layered back idles among the kit's DRPG units only 261 is such a sheet (checked
2026-10-12). (`drpg.WRONG_VIEW` can still leave a sheet out; that view's idle is then a battle-sheet pose,
breathing.)

Usalia and Liezerota have no humanoid twin either (their DRPG units 20001 / 20030 are monster-type atlases; Usalia is
a monster-type unit in the game, Liezerota an NPC without skills or attack frames): their humanoid DRPG variants are
**new playable characters** instead (next section).

Atlas layouts (`d5lib/drpg.py`):
* **A** (`drpg_slots.json`): ~400 units.  **B** (`drpg_slots_b.json`, `_research/drpg_make_slots_b.py`): the original
  characters 2-15 and ~30 early units (Formal Killia, Beach Etna, Bunny Seraphina ...): the same frames in the same
  slot order on an 8 px grid elsewhere.  Body slots were located with the vanilla twins' cells; hand overlays / loose
  pieces from pixel-identical masks shared by an A and a B unit (shift A -> B per piece).  `drpg.fit_layout` picks
  the layout per sheet, `drpgmap.regions` uses it (B loose pieces are moved to their A place).
* **Wait sheets on other grids** (bigger frames, 1024 sheets, extra layer pieces): `drpg.wait_frames` -- first 5 tall
  frames of the first 512 block in reading order, the first anchored where standard units stand (lower-body
  centroid x 85 front / 87 back, feet y 176), the others registered on its lower body (seeded by the centroid, since
  frame extents differ); frames cut off at the atlas edge are left out (the idle holds the drawing before).
* **Battle sheets packed like no layout** (a few units with oversized frames, e.g. back sheets of 105 / 130 / 149 /
  315 / 375): labelled by silhouette (`drpg.matched_frames` -> `match_unit`); their loose hand pieces are not used.

In game (verified 2026-10-09): the outfit list opens at a fixed place, so long lists are **paged**: at most
`exepatch.OUTFIT_PAGE` (12) entries, then *More outfits...* (value 99, StringListDataBase 40009 = `outfits.MORE_ID`)
shows the next page (cycling); the page counter lives in the now writable `.d5mod` section.  Tested on Girl Laharl
(15 entries: 12 + 3), outfit picked on page 2, face / list icon / hub sprite (idle, walk) switched at once.
Install time with all ~180 outfits: ~1 min since 2026-10-09 (was ~28 min): the LZS codec is native
(`d5lib/native_tools/lzs.c` -> `d5lib/bin/d5lzs.dll`, built with `python -m ziglang cc` when missing; the pure-Python
codec stays as the fallback), the face atlas search runs on a coarse grid, and script.dat is parsed once per install
(`BuildContext.parsed` / `changed`).  For exe / database-only changes after a full install:
`python tools/install_exe_only.py`.

## New playable characters from DRPG units (`kind: new_character`, 2026-10-09)
A catalog entry with `"kind": "new_character"` makes a new recruitable unique character instead of outfits on an
existing one (`outfits.create_drpg_character`, called once by `drpg_outfits.py build`; the result is recorded in
`patches/outfits/drpg_character.json`).  The entry's outfits then attach to the new character.

| field | meaning |
|---|---|
| `class` | char.dat row the character is copied from (identity: resistances, evilities, voice) |
| `template` | vanilla humanoid whose complete animation set the sprite gets (its own poses must be learned) |
| `unit` | the DRPG unit drawing the default look |
| `stats_from` | optional: base stats and aptitudes from another character (an NPC source is too weak) |
| `name`, `title`, `skills` ([id, level]), `desc` (3 lines), `quest` (title, client, text) | |

* The row becomes a humanoid: body type, size, height, weapon masteries, (no) Magichange, overload and motion group
  (`unk_0CA`) come from the template (`outfits.HUMANOID_FIELDS`).  A monster's overload plays its companion's
  animations, which a humanoid sprite doesn't have.
* Ids are unique across **all** mods: the character id (`slots.unique_pool`), its sprite number, the recruit
  quest's id and progress slot (`_free_quest`) and the description id (`_free_help_id`).  Each used to be computed
  from vanilla + the one mod: the first build collided with Killixia's quest 188 / slot 396 / charhelp 9041.
* The sprite is registered as an own-animation sprite (`outfits.json` `own_sprites`) **even before the character
  has outfits**: `outfits.save` used to delete `outfits.json` when it had no outfit pairs, which dropped the
  registration.  Without it the game binds the shared motion set to the new sprite's cells, and some poses
  (the fist charge, the thrust) show cut-up pieces of other drawings -- while every offline render looks right.
* Face (mirrored DRPG icon), list icon, portrait / cut-in and standing picture as for the outfits; the recruit quest
  copies 'Combat Lecture's objective with reward type 5 (recruit).

Built: **Future Usalia** (`DRPG_Human_Usalia`: character 213 from Usalia, DRPG 150, template Girl Laharl, quest 189
"The Other Usalia", 7 outfits) and **Liezerota** (`DRPG_Playable_Liezerota`: character 226 from the NPC Liezerota with
Killia's stats, DRPG 163 "Great Demon Fist", quest 190 "The Demon Fist's Daughter", 6 outfits).  Verified in game
2026-10-09 for both: Characters list (name, class title, DRPG face and list icon), Outfit menu and switching, fist
attack (charge, punch), enemy phase.  The monster-type Santa Usalia (`hybridanim`, `monster_outfits_experimental`) is
not built: its layers doubled.
