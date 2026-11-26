# Disgaea 5 Complete (PC) — `anmNNNNN.lzs` sprite animation format

Library: `d5lib/anm.py` (parser/writer, texture + palette I/O, renderer, character lookup).
Research scripts and verification images: `_research/anm/`.

Status legend: **confirmed** = verified on all 2006 JP + 97 EN + 89 FR files and/or visually;
*guess* = plausible, not proven; **UNKNOWN** = not understood (preserved verbatim on write).

## 1. Container

`Data/Anime/ANM_HI_{JP,EN,FR}.dat` are NISPACK archives (see FORMATS.md) of `anmNNNNN.lzs`,
`anm_resident.lzs`, `anm_startup_N.lzs`. Each `.lzs` is NIS LZS (ext `dat\0`) around one anm file.
`anm.lzs_compress(raw)` produces a valid LZS stream (level 1 ≈ 2-3 s for 4 MB, slightly smaller
than the original compressor's output; level 0 = literal-only, instant).

All numbers little-endian unless stated.

## 2. File layout

```
0x00  file header (0x20 bytes)
0x20  nblocks animation blocks, back to back (each block's size is in its header)
....  (ntex + npal) × 16-byte image headers: all textures first, then all palettes
....  image data (texture 0..n, palette 0..n), each image 128-byte aligned
```

### 2.1 File header (0x20)

| off | type | meaning |
|---|---|---|
| 0x00 | u32 | offset of image data **minus 0x10** (= 0x20 + Σblock sizes + 16·(ntex+npal) − 0x10) |
| 0x04 | u32 | total image data size (incl. alignment padding) |
| 0x08 | u32 | ntex – number of textures (all blocks) |
| 0x0C | u32 | npal – number of palettes (all blocks) |
| 0x10 | u32 | nblocks (1 for normal files; 3/4 in startup files, 179 in anm_resident) |
| 0x14 | 12 bytes | zero |

### 2.2 Image header (16 bytes, TXF-like) — confirmed

| off | type | meaning |
|---|---|---|
| 0x00 | u8[4] | format: `09 01 01 01` = 8-bit indexed, `00 01 01 01` = 32-bit |
| 0x04 | u16 | width |
| 0x06 | u16 | height |
| 0x08 | u32 | always 1 |
| 0x0C | u32 | data offset relative to image data start (header u32@0 + 0x10) |

* Palettes are images of 256×1, 32-bit.
* 32-bit pixels and palette entries are stored as bytes **A, R, G, B** (alpha 0..255, straight alpha).
* 8-bit textures are linear (no swizzle), one byte per pixel = palette index. Index 0 is normally
  fully transparent; index 1 is often (0,0,0,128) (shadow).
* Formats seen: 2512 indexed textures, 2339 32-bit textures (effects, cut-ins, UI), 7002 palettes.
  Original 4-bpp/16-colour console textures were converted to 8-bpp/256-colour on PC (the legacy
  tables below still say 4 bpp / 16 colours).
* Data is written in header order; each image's offset is aligned to 0x80 (only matters for odd sizes
  such as 1022×1022×4, anm08225).

### 2.3 Block

A block = one animation set. Header (0x44 bytes):

| off | type | meaning |
|---|---|---|
| 0x00 | u32 | block size (tables end rounded up to 16; padding may contain junk bytes → kept) |
| 0x04 | u16 | block id (= anm file number, e.g. 10 for anm00010; startup/resident blocks keep the id of the original file, e.g. 1, 71, 2070, 9020) |
| 0x06 | u16 | count of table 0 (animations) |
| 0x08 | u16[10] | counts of tables 1..9, then one u16 = 0 |
| 0x1C | u32[10] | offsets of tables 0..9 relative to block start (first = 0x44; tables are contiguous) |

Tables (records packed, no alignment):

| # | name (`anm.py`) | rec size | content |
|---|---|---|---|
| 0 | `animations` | 4 | u16 animation id, u16 root node index |
| 1 | `nodes` | 20 | node tree (layers / bones) |
| 2 | `keys` | 12 | keyframes |
| 3 | `palette_infos` | 8 | legacy palette info (one per palette owned by this block) |
| 4 | `texture_infos` | 12 | legacy texture info (one per texture owned by this block) |
| 5 | `cells` | 18 | sprite parts: rectangles on textures |
| 6 | `transforms` | 16 | position / scale / rotation / pivot index |
| 7 | `pivots` | 4 | points (i16 x, i16 y) |
| 8 | `colors` | 20 | 5 vertex colours |
| 9 | `params` | 4 | i32 value lists |

Blocks own textures/palettes sequentially: block *b* owns global textures
`Σ_{i<b} len(texture_infos_i) … + len(texture_infos_b)` (same for palettes). Cell texture/palette
indices are block-local. (Exception: shared motion blocks, see §5.)

#### Table 0 – Animation (4)
| off | type | meaning |
|---|---|---|
| 0 | u16 | animation id. Last digit = view: `…1` front (facing down-left), `…7` back (facing up-left); the other two directions are drawn mirrored by the engine. `0` = empty default. Examples: 1001/1007 idle, 1011/1017, 1021/1027 …, 2001–4087 attack families, 6001/6007/7001… character specials, 8000+ cut-ins. The exact motion names are **UNKNOWN** (see `Anime_TableDataBase.dat`, §6). |
| 2 | u16 | root node (table 1) |

#### Table 1 – Node (20)
The animation is a tree of nodes (first-child / next-sibling links). Each node is a track with its own
keyframes; a node's transform is applied to all its children (hierarchical bones) — confirmed.

| off | type | meaning |
|---|---|---|
| 0 | u16 | node id/name: 0 = anonymous layer; 1 = body; 10 = weapon slot; 11–17 and 111–116 = attachment points (hands / effect locators). *Named-node semantics are a guess from usage.* |
| 2 | u16 | flags: 0x100 ⇔ id≠0 (named); 0x1000 **UNKNOWN** (mostly cell-less group nodes) |
| 4 | u16 | **UNKNOWN** (0; one file has 10) |
| 6 | u16 | 0 |
| 8 | u16 | `mesh`: 1 = vertex-quad mode (see transforms) — confirmed on cut-ins/weapon icons |
| 10 | u16 | 0 |
| 12 | i16 | first key index (−1 = none) |
| 14 | u16 | key count |
| 16 | i16 | first child (−1) |
| 18 | i16 | next sibling (−1) |

Structure of every animation: `root` = **control node** (keys with cell 0 only, carrying timeline
commands) → `next` = group node (no keys) → `child` = the sprite layers.

Draw order (confirmed visually): nodes earlier in file/tree order are drawn **on top**
(render back-to-front = reverse pre-order).

#### Table 2 – Key (12)
| off | type | meaning |
|---|---|---|
| 0 | u16 | time in frames (60 fps; typical sprite keys every 2–6 frames) |
| 2 | u16 | flags. Low byte on layer nodes: 1 = interpolate (position, scale, rotation, mesh vertices, colour) linearly to the next key, 0 = step. Low byte on the control node = command: 1 loop start, 2 loop end / jump back to 1 (end of looping anims), 3 **UNKNOWN** (mid-anim marker), 4 event/trigger (e.g. hit timing), 5 end/hold. High byte: 0x01 / 0x02 mostly on attachment nodes with cell 0 (*show / hide attached object*), 0x06 mostly on 32-bit cut-in textures, 0x03/0x05 rare — all **UNKNOWN** (blend/filter?) |
| 4 | u16 | cell (table 5); 0 = nothing drawn |
| 6 | u16 | transform (table 6) |
| 8 | u16 | colour (table 8) |
| 10 | u16 | param list start (table 9) |

A node is invisible before its first key; after the last key the last key holds.

#### Table 3 – PaletteInfo (8) — legacy
`u32 virtual_offset, u16 num_colors (256, or 16 for converted 4-bpp), u16 0`.
Virtual layout = `[block][palettes (num_colors·4 each)][textures (w·h·bpp/8 each)]`, i.e.
`offset = block_size + Σ previous palette sizes`. Not used for loading on PC but written
consistently: `AnmBlock.fix_virtual_offsets()` recomputes it (reproduces all original files exactly).

#### Table 4 – TextureInfo (12) — legacy
`u32 virtual_offset, u16 width, u16 height, u8 bpp (4/8/32), u8 0x10, u8 0x10, u8 0`.
`offset = block_size + Σ palette sizes + Σ previous texture sizes`. Keep width/height in sync with the
image header when resizing (`image_to_texture` does this).

#### Table 5 – Cell (18) — confirmed
| off | type | meaning |
|---|---|---|
| 0 | u16 | texture (block-local) |
| 2 | u16 | palette (block-local); final palette = this + colour variant |
| 4 | u16 | byte +4 draw attribute, byte +5 blend mode (512/768/1024/1280 = blend 2/3/4/5); see §8.1 |
| 6 | u16 | byte +6 flip X, byte +7 flip Y (1 = flip X, 257 = both); see §8.1 |
| 8 | u16 | x |
| 10 | u16 | y |
| 12 | u16 | width |
| 14 | u16 | height |
| 16 | u16 | low byte = draw-depth group (0/1, up to ~200 in anm02611); see §8.1 |

Cell 0 is always the empty cell. Some cells are stored rotated 90° on the sheet and rotated back by
their transform.

#### Table 6 – Transform (16) — confirmed
| off | type | meaning |
|---|---|---|
| 0 | i16 | x – where the pivot lands, in parent space (origin = character's feet, y down) |
| 2 | i16 | y |
| 4 | u16 | pivot index (table 7). Normal nodes: one point in cell pixel space. `mesh` nodes: first of a group of 10 points |
| 6 | u16 | 0 |
| 8 | i16 | scale x, percent (negative = mirror) |
| 10 | i16 | scale y, percent |
| 12 | i32 | rotation in degrees, positive = clockwise on screen |

Local matrix = `T(x,y) · R(rot) · S(sx/100, sy/100)`; a normal cell is drawn with its rectangle
translated by `−pivot`, i.e. corners `(0,0),(w,0),(w,h),(0,h) − pivot`.
Mesh nodes: pivots `[p … p+3]` are the 4 corner positions TL, TR, BR, BL (relative to the node, then
transformed by T·R·S); `p+4` = centre (0,0 in all samples); `p+5 … p+9` = **UNKNOWN** second vertex set
(looks like the complementary/“back side” offsets of card-flip effects). Renderer maps the cell to the
quad with a perspective (homography) warp.

#### Table 7 – Pivot (4): `i16 x, i16 y`. Entry 0 = (0,0).

#### Table 8 – Color (20): 5 × RGBA bytes (vertex colours TL, TR, BR, BL, centre)
RGB 0x80 = ×1.0 (0xFF ≈ ×2, used for white flashes); alpha 0xFF = opaque, 0x00 = invisible (fades).
Typical entries: `808080ff` (neutral), `80808000` (transparent), `ffffffff` (flash).
Renderer uses corner 0 for the whole cell (all 5 are equal in >99 % of records).

#### Table 9 – Params (4): i32 lists, referenced by `Key.param`
Always `(value, 0, −1)` triples in the data: value = an animation id. On named/attachment nodes it
selects the animation of the attached object (e.g. weapon sprite anim 1/7/11/21…); on control nodes
it names a linked animation (e.g. 1061/1067). Exact engine semantics **UNKNOWN**.

## 3. Colour variants (palette swaps)

* Unique characters: 5 palettes (0 = default, 1–4 = colour-edit alternatives).
* Generic classes and monsters (anm 1000–2999): 10 palettes. Palette = class tier: e.g. Warrior
  Fighter…Battle Master = palettes 0…5, Pvt. Prinny…Prinny God = 0…5; 6–9 are extra colour-edit
  colours (`_research/anm/palette_variants.png`).
* The pixel indices are shared by all variants, so editing a texture affects every tier; edit a
  palette with `get_palette/set_palette` to recolour one tier.
* `userpalletmanager.cpp` (exe) suggests user-defined palettes stored elsewhere (save data) — not researched.

## 4. Characters → anm files (`char.dat`)

`Database/Database_0/char.dat`: u32 count (806), records of 908 bytes.

| rec off | type | meaning |
|---|---|---|
| 0xD0 | u16 | graphics id (battle) — same as 0xDE except NPC/special records |
| 0xD4, 0xDC | u16 | base graphics id (tier stripped) — alternates, **UNKNOWN** use |
| 0xDE | u16 | **graphics id** used by `find_character_anm`: sprite file = `anm(id − id%10)`, palette = `id % 10` |
| 0xF6 | u16 | base character id (Killia 10, Warrior 1010, Prinny 2010; NPCs point to their model's base) |
| 0xF8 / 0x12C / 0x160 / 0x194 / 0x1C8 | char[52] | name JP / EN / FR / zh-TW / KO |
| 0x1FC / 0x240 / 0x284 / 0x2C8 / 0x30C | char[68] | title/class JP / EN / FR / zh-TW / KO |

Examples: Killia 10 (awakened 20), Seraphina 40 (bunny girl 500), Red Magnus 50, Christo 60,
Usalia 70 (awakened 80), Zeroken 100, Void Dark 150, Laharl 510, Etna 520, Warrior 1010 (tiers pal 0-5),
Valkyrie 1020, Magician 1030, Prinny 2010, Winged Warrior 2080. Record ids ≥ 4100 are map objects /
ship parts without anm files (3D .obf or other).

**NNN0 vs NNN1**: every sprite exists as `anmNNNN0` (full) and `anmNNNN1` (same base sheets and
palettes, subset of animations/textures: no special-attack sheets). *Guess*: NNN1 is the lightweight
copy used where the full set is not needed (map / base / multiple instances). Edit both.

## 5. Shared motion sets (humanoids)

Human-shaped characters (Killia, Seraphina, Laharl, Etna, all humanoid generic classes …) have only
a handful of animations in their own file (0, 6001/6007, 7001…: specials). Their standard motions come
from **block id 1 inside `anm_resident`** (block index 0; 135 animations: 1001…5021) whose cells index
textures 0–8 of *the character's* file (standardized sheet layout: 120×192 cells on texture 0 etc.).
`anm.bind_motion_set(resident, block_index, sprite)` builds a render-only view
(`_research/anm/g_res1_killia.png`, `warrior_pal3_2021.png`). Monsters / Usalia / Prinnies carry their
full motion set in their own file. `find_character_anm` flags files with < 20 animations as
`motion_set='resident:1'` (heuristic). Consequence for modders: a humanoid's sheets must keep the
standard layout (cell rectangles live in anm_resident, shared by everyone).

Other resident blocks: ids x2 (12, 22, …, 2612: 1 anim, 1 texture, 5/10 palettes – the per-character
**placeholder / standing picture**, see 5a), 9000–9802 UI/effects. `anm00002` (block id 2, 128 anims, cells
referencing textures it does not contain) is another template (**UNKNOWN** user).

## 5a. The N+2 placeholder: a monster's must be in anm_resident (2026-11-09)

For a class row with `sprite_id` N the game binds a unit in two steps (addresses: clean Steam exe):

1. `hubmgr_per_unit_bind` 0x14015a860 -> `unit_set_appearance` 0x14014ea10 -> `ui_sprite_set_anm` 0x14014e7e0 with
   body = N + off and placeholder = **N + 2**. `off` is 1 in battle when `sprite_id > 2000` (0x14015ad17), so the
   vanilla Imp 2020 draws from 2021; below 2000 the body is N itself (Desco 610, any leased unique).
2. The body bank `anm%05d.lzs` loads asynchronously. Until it arrives the unit is bound to the placeholder
   (`unit_bind_anm_owner` 0x14014dfd0), and that bind only finds **records that are already loaded**
   (`anm_find_loaded_record` 0x1403020c0; a miss is taken at 0x1402f4b3a).

| unit kind (`row+0x386`) | owner anim while loading | consequence |
|---|---|---|
| 0 humanoid | block **1** (the shared resident humanoid motion set); N+2 is part slot 0 | a loose `anm{N+2}` binds, but can be released while a render node still draws from it (PAGECRASH2, section 11a): put it in anm_resident |
| 1 monster | **N+2 itself** | N+2 must be a block of `anm_resident`, or the bind misses |

Every one of the 355 vanilla monster rows with art keeps its N+2 in `anm_resident`. A monster whose N+2 is only a
loose ANM_HI member shows **no body, its motion tick never advances, and the game freezes when the unit is
attacked** (seen live on a leased D4 unique; fixed and re-checked live the same day). The bank bytes do not matter:
a byte copy of the Imp's bank at a leased number fails the same way.

What the kit does: `newclasses._monster_pictures` merges the build's own `anm{N+2}` into both resident packs
(`facepatch.add_resident_blocks`) for monster **classes** and, since 2026-11-09, for registry **uniques** declared
`kind: "monster"` in `patches/characters/unique.json` (physical sprite + 2), also when a profile has no class specs.
`importcore.resident_placeholder_gate` fails any monster unique whose placeholder would not end up resident; every
importer runs it. Cost measured for 8 uniques: +8 blocks, +8 textures, +75 palettes, about 1.0 MB in the JP pack.
The design is Cryswar's (Overlord `d5_anm_resident.c`, The Unlicense). `anm_id_for_variant` (0x14021f4a0) is not on
this path; it only sets the graphics id used by faces and cut-ins.

**UNKNOWN:** why a missed placeholder bind leaves the later body bind invisible (not traced to a line).

## 6. Anime_TableDataBase.dat

`u32 count (284)`, then `{u32 index, i32 anim_id_base, i32 param}`; lists separated by
`(…, −1, −1)`. anim_id_base values are motion bases (1000, 1010 … 4030 → +1/+7 for view).
Probably per-character-type motion availability lists (param = hit frame?) — **UNKNOWN** how
char.dat links to it (char.dat +0xCA holds 100…162 for some records).

## 7. Writing / growing data

`AnmFile.to_bytes()` recomputes everything:
* file header u32@0 (data offset − 0x10), u32@4 (data size), counts;
* every block's size, table counts and offsets (tables contiguous, block padded to 16);
* legacy virtual offsets in tables 3/4 (`fix_virtual_offsets`, disable with `to_bytes(False)`);
* image header data offsets (128-byte aligned, in header order).

So you can: resize a texture (`image_to_texture` with a new size — cells keep their pixel rects;
enlarge the sheet and add new cells for new art), add textures (`add_texture`), add palettes
(`add_palette`), add cells/transforms/keys/nodes (append to the lists and link indices; indices are
u16/i16). When adding images to a block that is not the last one, later blocks' `tex_base/pal_base`
shift (helpers handle it). Palette count per block is also the number of colour variants the game
can pick — adding a palette is untested in-game (the game may clamp to 5/10).

Things NOT verified in-game (no game run was possible): whether the engine accepts textures larger than
the originals (1024×1024 max seen; 1920×1080 32-bit exists in anm08225, so large sizes are supported
by the format), and extra palettes.

## 8. Round-trip results

`python _research/anm/roundtrip.py EN|SAMPLE|JPALL`: parse → to_bytes byte-identical for
**2006/2006 JP** (including anm_resident 415 MB and all anm_startup_*), **97/97 EN**, **89/89 FR**.

`tools/anm_roundtrip.py` repeats this as a gate on any game folder: all **2,347** banks of Steam build 3528766
(JP, EN, FR, HN, CH) round-trip byte-identical, and every byte is claimed except 3,566 bytes of non-zero
filler in 10 banks (block tail padding in `anm_resident`/`anm_startup_*`, one image gap in `anm08225`).
It exits non-zero when a bank in its baseline stops round-tripping or goes missing.

## 8.1 How the game reads each field

Read from the loader, record builder and renderer of `disgaea5.exe` build 3528766 (image addresses).
The kit's u16 fields keep the stored values, but several are really two bytes or half of a u32.
A writer that treats them as one number can change what the game does.

| Kit field | The game reads | Evidence |
|---|---|---|
| `Key.flags` (+2) | byte +2: control command on the root node (1 loop mark, 2 loop, 3 conditional loop, 4 wait, 5 hold); on layers 0 = step, else interpolate. Byte +3: 1 spawn / 2 despawn attachment (params[key.param]), 3/4/5 Hermite position/rotation/scale (tangents from params), 6 morph the cell rectangle toward the next key's cell | 0x1402f5002, 0x1402f91ac, 0x1402f5750, 0x1402f8251 |
| `Cell` +4 (`unk2`) | byte +4: per-draw attribute default; byte +5: blend mode (2/3/4 as is, else 1) | 0x1402f8d39, 0x1402f8d48 |
| `Cell.flags` (+6) | byte +6 flip X, byte +7 flip Y | 0x1402f89a5, 0x1402f89fa |
| `Cell` +16 (`unk8`) | low byte = draw-depth group the game sorts by | 0x1402f8edc, sort 0x1400a31a0 |
| `Node.id` + `Node.flags` | one u32: bits 0–23 asset id (or binding key when bits 24–27 ≠ 0), bits 28–31 draw mode. Kit flags 0x100 = bit 24, 0x1000 = bit 28 | 0x1402f688e, 0x1402f8dce |
| `Node.mesh` + `unk5` (+8) | one i32: 1 = 10-point mesh | 0x1402f8722 |
| `Transform.pivot` + `unk` (+4) | one i32 pivot index | 0x1402f5a38 |
| `TextureInfo` width/height | used for buffer size and UV scale (not legacy) | 0x140301514, 0x1402f8dd4 |

Attachment params are a triple (motion id, start, duration). `PaletteInfo` rows and node +4/+6 were not read
by any function checked. Key cell/colour/param indexes are signed (-1 = none).

Draw gate (0x1402f7c60, static reading): a node whose u32 has bits 0–23 ≠ 0 draws its own cell only when that id
resolves (`anm_find_loaded_record` 0x1403020c0 compares it with a loaded block's u16 id, so a value ≥ 0x10000, e.g.
kit `flags` low byte ≠ 0, never resolves); with bits 24–27 ≠ 0 it needs a binding entry instead. Its children are
drawn either way. An actor attached to a node draws with that node's current cell depth byte added to its own.
The draw-mode nibble becomes byte 0 of the node's draw packet; `anm_flush_draw_packets` (0x1402f3650) reads 1 there as
"linear filter" only when `anm_force_linear_filter` is 0 (Sorrow: it is always 1), so it changes nothing visible.
On nodes with a drawn cell D5 stores id/flags (0, 0) 68,019 times, (0, 0x1000) 4,089, a binding (id, 0x100/0x1100)
1,803, and never an asset id ≥ 0x10000 (all JP banks + resident). Monster anm02070 has (99, 0x1100) on node 99.
Across all 2,006 JP banks the node `flags` low byte and cell +17 are always 0, and layer keys' +2 is 0 or 1;
`tools/anm_twin.py` lists an import's values outside the D5 set and compares it motion by motion with D5's own bank
for the same character and with its source bank.

- **Render root (BACKVIEW1, decomp):** an animation's drawing is node `root+1` and its children
  (`anm_actor_build_render_root` 0x1402f5450 -> `anm_node_build_tree`); the root node itself is only read for its
  control keys (loop/end) and its `child`/`next` are ignored. Lay an animation out as control root, then the drawing
  at `root+1` (native stubs: control, keyless container, body). `anm.render_root_problems` checks it.

## 9. Remaining unknowns

* Node +4/+6; mesh points 5–9 semantics beyond "second vertex set".
* Semantics of params on control nodes.
* Cell byte +4 (per-draw attribute) meaning.
* Which of char.dat 0xD0/0xD4/0xDC/0xDE is used in which context; `Anime_TableDataBase` linkage.
* anm00002's user; resident x2 blocks' purpose.

## 10. Disgaea D2 (PS3) banks

`d5lib/d2anm.py` reads and writes them (`parse`, `to_bytes`); `d2anm.ROWS` is the one copy of the row layout, used by
the DD2 importer (`decode_dd2`) and the D2 sprite viewer. Source: the 7 big-endian NISPACKs `Data/ANM_HI.dat`,
`ANM_HI_1..6.dat` of BLUS31313 (not obfuscated; the members' LZS header is little-endian as on PC). 2,301 members,
2,056 names (add-on archives repeat some), 2,193 distinct contents.

The bank is laid out as in §2: 32-byte file header (+0x14..+0x20 zero), blocks with a 0x44-byte header, tables back
to back from +0x44, block size 16-aligned, image descriptors ending at header[0] + 0x10, image data 0x80-aligned.
Everything is big-endian. Rows, as `d2anm` maps them onto the kit's record classes (kit field = bytes at the same
place; byte fields hold byte +n as the kit u16's low byte, as D5 reads them):

| Row | D2 size | Differs from D5 |
|---|---|---|
| Node | **16** | +0..+3 is D5's node u32 as a big-endian bitfield, top bit first: id (24 bits, +0..+2), binding (+3 high nibble), draw mode (+3 low nibble). `d2anm.d5_node_words` rewrites it as D5 reads it (D2 0x0001 = D5 flags 0x1000; 0x6311 = id 99, 0x1100; 0x0110 = id 1, 0x100). Evidence: the D2 binding ids are 1, 10–17, 21, 31, 99, 111–116 and D5's are 1, 10–17, 20, 21, 99, 111–116 (only 31, the shared stand's part node, is D2's own); DD2 monsters' 117–129 mode-1 group nodes match D5 monsters' 113–129 (0, 0x1000) nodes. Copied raw (DD2 importer before DD2DRAW1), mode 1 read as asset id 0x10000 and the node's cell was skipped. Binding-0 nodes with an id (8,132, mostly +0 ≠ 0) are D2 asset ids; the conversion drops them (none in DD2 class bodies). `unk2` (+4) is 0 in every bank. `mesh` (+6) ∈ {0, 1}. No `unk3`/`unk5`: `first_key`, `num_keys`, `child`, `next` at +8..+14 |
| Key | 12 | +2 and +3 are bytes (same values as D5: +2 ∈ 0–6, +3 ∈ 0–6) |
| Cell | 18 | +4, +5, +6, +7, +16, +17 are bytes. **16** bytes (no +16 word) in `anm09006`, `anm09901`, `anm09903`, `anm09998` |
| Transform | 16 | the pivot index is the word at **+6** (kit `unk`); +4 (kit `pivot`) is 0 in all 126,052 rows |
| others | as D5 | Animation, PaletteInfo (see below), TextureInfo, Pivot, Color, Params read big-endian |

Two of these look like D5's wider fields stored big-endian (an inference, not traced in D2's code): D5 reads
Transform +4..+7 as one i32 (§8.1), whose low half a big-endian file puts at +6; and D2's node +4..+7 (word +4
always 0) would be D5's i32 mesh word. The viewer's check fails ("a piece came away from the body") when the pivot
is read from +4.

**PaletteInfo colour count (WRITEWATCH1, 2026-11-21).** D2 stores the count as one big-endian i32 at +4 (256 = `00 00 01 00`), so
the byte-faithful kit read gives `num_colors` 0 and `unk` 256. D5 reads +4..+7 as one little-endian i32, i.e. 0x01000000, and the attack
set-up (`0x1402F9550`, from start_basic_attack / start_skill_action) copies that many colours into a fixed 256-colour buffer
(`0x1469AF859`), overrunning the globals after it (DD2 Shark Dragon crash). The importer therefore writes D5 counts, clamped to 256
(`d2anm.d5_palette_counts`, applied in `decode_dd2`), and `importcore.palette_count_gate` fails any shipped bank with a row count
outside 1..256 (`docs/IMPORT_GATES.md`).

Image descriptors: format byte 9 (8-bit indexed, 9,603 sheets), 0 (ARGB32, 105) and **4 (DXT5, 48; 1 byte per
pixel)**; the u32 at +8 is 0x00010000 in every descriptor (D5: 1). Palettes are ARGB32 **256×1 (13,354) or 256×4
(585, 4,096 bytes)**. `d2anm` keeps DXT5 sheets compressed; decoding is a display step (the viewer's `d2_bank`).

Round trip (`tools/anm_roundtrip.py --d2 <Data>`): all 2,301 members byte-identical. Coverage: content
2,299,763,632 B, known header 689,664 B, zero alignment padding 22,610 B, unexplained **6,990 B in 113 members**,
all non-zero filler where the format pads: block tails (4,302 B, 493 ranges) and image alignment gaps (2,688 B, 44
ranges), the same kind of build-tool leftovers as D5's (§8). `d2anm` keeps them on write.

Still unknown for D2: what its asset ids refer to, whether `mesh` (+6) means D5's 10-point mesh (both earlier
readers treat it so; 23,144 nodes have 1), cell +17 (values 0, 18, 63, 150, 221, 240, 245; D5's is always 0).

## 11. How the game turns a bank into textures, and the NULL-texture guard (PAGECRASH1, 2026-11-13)
Facts from the decomp (Steam build = `/Volumes/Data/Decomp/d5`):
- A loaded bank is a 0xC0-byte record (`anm_find_loaded_record` 0x1403020C0): +0x10 palette count, +0x12 texture count,
  +0x68 texture headers (12 B each), +0x98 texture-object table, +0xA0 palette-object table (8 B pointers).
- Every texture and every palette is a 0x58-byte object from one fixed pool of 16,384 (`FUN_140310660` writes
  0x40000003 to the pool header: count 0x4000 in the high word), taken by `ykcmp_decompress_texture` 0x140310970,
  which returns 0 when the pool's free list gives none or the decode fails. Object +0x20/+0x22 = width/height, +0x24 =
  format (9 = 8-bit indexed, drawn with POINT filtering).
- The queued package build (`anm_build_records_queued` 0x1402EF370 -> `FUN_140301830`) publishes a record's id and
  its +0x98 table first and then fills the table one texture at a time, returning after ~1.04 ms (0x410 us); the
  slot's record count is set before any record is built. `anm_release_package` 0x1402EEE00 frees the objects and
  zeroes +0x98/+0xA0 before freeing the record array.
- The emitters (`anm_emit_node_geometry` 0x1402F6B10, `anm_render_node_hierarchy` 0x1402F7C60) put
  `(record+0x98)[cell.tex]` into draw packet +0x20 whenever `cell.tex < record+0x12`; they check it for NULL before
  reading +0x24 but still queue the packet. `anm_flush_draw_packets` 0x1402F3650 does not check: a NULL texture is a
  page fault reading 0x24 at 0x1402F3744 (the Recruiter D4-page crash, FREEZECATCH1).
- A cell whose `tex` is out of range never makes a packet, so bad cell data cannot cause this; a NULL texture means
  the record's texture table is NULL, not filled yet, or the pool gave nothing.

Since PAGECRASH1 the installer patches the flush (`d5lib/anmguard.py`, section `.d5ag`, applied in
`outfits._finalize`): a packet whose texture is NULL is skipped (that part of the sprite is not drawn for one frame),
every other packet is drawn exactly as before, and a dword counts the skips (`anmguard.counter_va(exe)`, read it
live with the harness `rd`; the section is writable for it). **This hides the symptom.** Whatever draws a record whose textures are
gone or not built yet is still doing so; with a released record the guard covers only the NULL case, not a stale
non-NULL pointer. Proof: `tests/test_pagecrash1.py` (normal and `--abi`).

## 11a. A humanoid's N+2 must be resident too: stale part records (PAGECRASH2, 2026-11-14)
Facts from the decomp (Steam build) and the pinned exe:
- The second Recruiter D4-page crash (`read 0x5 at 0x1402F7A4C`, GUARDSKIP1) is in `anm_emit_node_geometry`
  (0x1402F6B10, 4424 bytes), not in the flush. `[rbp-0x20]` is the texture header pointer
  `(record+0x68) + cell.tex*12` (written at 0x1402F6D34; 0 otherwise), read as `word [+4]`/`[+6]` (width/height) at
  0x1402F7A4C/0x1402F7A5B. The twin in `anm_render_node_hierarchy` reads it at 0x1402F8DD4/0x1402F8DE4. `record` is
  the node's bound part record (node+0x40), else the owner's (+0x60).
- record+0x68 is only ever written as `package file buffer + header offset` (`anm_build_records_queued` 0x1402EF370).
  A value of 1 there means the 0xC0-byte record is not a live record: its array was freed by `anm_release_package`
  (0x1402EEE00 zeroes +0x98/+0xA0, then frees the array: NULL textures until the heap reuses the memory, junk after)
  or not built yet (the array is not zeroed; `FUN_140301830` also leaves the +0x98/+0xA0 tables unzeroed until each
  entry is decoded).
- Lifecycle: `anm_acquire_lzs` 0x1403FFCB0 (refcount +1, load task) -> `anm_package_load_step` 0x1402EE3D0 ->
  queued build (record findable by id) -> ready -> `scene_units_anm_loader_release` 0x1403FFE60 (refcount -1) ->
  `game_frame` grace countdown -> `anm_release_package`. Render nodes and owners cache record pointers found by id
  (`anm_node_resolve_bindings` 0x1402F6870 -> node+0x40; `anm_instance_load_anim_and_motion` 0x1402F4B10 -> +0x60)
  without a reference, and nothing re-resolves them on release.
- A humanoid unit binds part slot 0 to N+2 while bank N loads (`unit_bind_anm_owner` 0x14014DFD0: owner anim 1 when
  id >= 10; `unit_bind_part_anm` 0x14014ED00) and acquires only N. Every vanilla humanoid row (80/80 in the
  source copy) keeps N+2 in anm_resident, which `anm_acquire_lzs` finds first, so it is never released. The kit's
  humanoid classes shipped N+2 loose (installed: 11, the D4 page's 8 among them).
- Since PAGECRASH2 the installer adds the N+2 of every humanoid class that ships it loose to both resident packs
  (`newclasses.humanoid_class_pictures`, through the monster mechanism above): +1 texture, +10 palettes, about
  0.14 MB per class. Humanoid uniques/char rows with a loose N+2 (426 installed rows) are not covered.
