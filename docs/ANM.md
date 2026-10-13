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
| 4 | u16 | **UNKNOWN** (0; 512, 768, 1024, 1280, 7, 8, 15 seen) |
| 6 | u16 | **UNKNOWN** flags (0/1/257) |
| 8 | u16 | x |
| 10 | u16 | y |
| 12 | u16 | width |
| 14 | u16 | height |
| 16 | u16 | **UNKNOWN** (0/1, up to ~200 in anm02611) |

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

Other resident blocks: ids x2 (12, 22, …, 2612: 1 anim, 1 texture, 5/10 palettes – small icons/portraits
per character, **UNKNOWN** use), 9000–9802 UI/effects. `anm00002` (block id 2, 128 anims, cells
referencing textures it does not contain) is another template (**UNKNOWN** user).

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

## 9. Remaining unknowns

* Key flags high byte (0x01/0x02/0x03/0x05/0x06) – blend mode / attachment visibility?
* Node flags 0x1000, node +4; cell +4, +6, +16.
* Mesh groups points 5–9.
* Control command 3; semantics of params on control nodes.
* Exact blend modes (all rendering done with normal alpha blending; effects in-game may be additive).
* Which of char.dat 0xD0/0xD4/0xDC/0xDE is used in which context; `Anime_TableDataBase` linkage.
* anm00002's user; resident x2 blocks' purpose.
