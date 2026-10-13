# Disgaea 5 Complete (PC): maps, stages and 3D objects

Code: `d5lib/mapfile.py` (.hex/.chr/.gop, map packages, dungeon.dat stage list, preview render),
`d5lib/obf.py` (.obf 3D container, textures, OBJ export), `d5lib/lzs_compress.py` (LZS compressor).
Research scripts and output: `_research/map/` (`render_maps.py`, `mesh_preview.py`, `dump_units.py`).

Confidence tags: **[H]** verified against the exe loader or across all files, **[M]** consistent
statistical or visual evidence, **[L]** a guess.

## 1. Where things live

```
Data/Map/Map_JP.dat (NISPACK, obfuscated)        448 maps: base set
Data/Map/Map_EN.dat / Map_FR.dat                  10 localised replacements (map30001-30009, map40008)
  mapNNNNN.lzs      LZS, header ext 'pac'
    pac:  mapNNNNN.hex  terrain grid                    (~35-70 KB)
          mapNNNNN.chr  unit placement                  (16 + n*592 bytes)
          mapNNNNN.obf  3D terrain mesh + textures      (0.5-20 MB)
          mapNNNNN.gop  geo panel list                  (49168 bytes)
Database/Database_0.dat/dungeon.dat     stage list: stage -> map id, base panel, names
```
Map id groups: `001xx-029xx` story episodes / postgame / DLC stages (xx = stage, x21/x25 = demo maps),
`04001-04002` Baal, `05001`, `21001`, `30001-30009` Pocket Netherworld hub (no units), `400xx/401xx`
item-world and "Carnage" rooms, `41001`, `50001-50002`, `60001-63011` and `70101-71705` item-world /
random-floor building blocks (1x1 to 17x17 pieces, no units), `80001` reward room.
The engine builds file names with `map%05d.%s` **[H]**; `MapPackage.from_archive(id)` reads EN first, then JP.

The pac member order is always hex, chr, obf, gop **[H]**. `d5lib.pac.write_pac` reproduces it
byte for byte. Inside the pac each member is padded to 16 bytes, so the obf's own size field is 0-12
bytes smaller than the member **[H]**.

## 2. `.hex` terrain grid (loader: `0x1402272d0`, called from the map loader `0x14053f0b0`)

All 458 files are version 6. The loader also accepts versions 3, 4, 5 and 7 with different
layouts **[H]**. `map70601.hex` is made of 3 blocks back to back; the others have 1.

| off | type | field | notes |
|---|---|---|---|
| 0x00 | u32 | version | 6 **[H]** |
| 0x04 | u32 | W | grid size along x (≤128) **[H]** |
| 0x08 | u32 | H | grid size along y **[H]** |
| 0x0C | i32[5] | motion_ids | obf motion index played on terrain objects 0-4, -1 = none (used by `0x140239ec0`) **[H]** |
| 0x20 | 0xD0 bytes | env | light/camera block: direction vectors (±0.707), ambient 0.1, diffuse 1.0, 0.7, 5.0, 256, 512 …; env+0xC0/0xC4 = i32 315, 90 (camera yaw/pitch?) **[M]** |
| 0xF0 | f32[(W+1)(H+1)][4] | corners | per panel 4 corner heights, row = x (stride H+1). The last row and column are padding **[H]**. Heights are negative-up: mesh Y ≈ −height (checked against the .obf, mean error 0.2) **[H]**. Corner order is probably (x0,y0),(x1,y1),(x1,y0),(x0,y1) **[L/M]** |
| +0 | u8[128][128] | flag_a | only 22 non-zero cells in the whole game; meaning unknown **[L]** |
| +0x4000 | u8[128][128] | no_panel | `[x][y]==1` means no panel (hole or outside). Movement/placement code rejects these cells (`0x140147e6c`, `0x1406fcdf0`). A new-map init sets the W×H area to 1 **[H]** |

Coordinates: grid x → mesh +X, grid y → mesh +Z, 1 panel = 12 units, one height step = 6 units
(correlation 0.2 vs 13.6 for the swapped axes) **[H]**.

API: `HexFile(bytes).blocks[0]` → `HexBlock` with `.width .height .motion_ids .env .corners
.flag_a .no_panel`, `elevation()`, `has_panel(x,y)`, `set_height(x,y,h)`, `resize(w,h)`, `to_bytes()`.

## 3. `.gop` Geo Panels

| off | type | field |
|---|---|---|
| 0x0000 | u32 | count of live entries **[H]** |
| 0x0004 | u8[16384] | x **[H]** |
| 0x4004 | u8[16384] | y **[H]** |
| 0x8004 | u8[16384] | colour **[H]** |
| 0xC004 | 12 bytes | zero |

385 maps have count 0. Entries past `count` sometimes hold stale editor data; it is kept as-is, and
`set_panels(..., clear_stale=True)` zeroes it. `map00121.gop` is 98320 bytes of zeros, and the extra
data is kept raw.

Colour codes: 1..6. In the geo-panel texture tables of the exe the order is Red, Green, Blue, Yellow,
Purple, Cyan, so we read the codes as **1 red, 2 green, 3 blue, 4 yellow, 5 purple, 6 cyan** **[M]**.
Geo *symbols* use the same codes, with 0 = clear/colourless. In the symbol-colour vs
panel-under-symbol table, codes 1-4 match their own colour most often **[M]**.

API: `GopFile(bytes)`: `.panels()` → [(x,y,c)], `.set_panels(list)`, `.color_grid(W,H)`,
`.set_color_grid(grid)`, `.to_bytes()`.

## 4. `.chr` units (enemies, NPCs, map objects, Geo Symbols)

Header: `u16 version (=1), u16 count, 12 zero bytes`. Records are 592 bytes (0x250). Four demo
maps (map00121/00421/00721/00825) use an older 436-byte record. It shares the first 0x10 bytes; the
rest is kept raw. The engine reads the count with a cap of 255 **[H]**. The field sizes come from the
spawn-struct initialiser at `0x1404da2bf` **[H]**; the meanings are cross-checked against DB tables.

| off | type | field | meaning |
|---|---|---|---|
| 0x000 | u32 | slot | unit number (1..n) [M] |
| 0x004 | u32 | char_id | **char.dat id** (id at char.dat record+0xD0). Classes 10-2xxx, 4810/4811 = Geo Symbol "GS", 5000-5299 objects (boxes, bombs, pillars, treasure, level spheres), 5260/5261 item symbols, 5400+ NPCs **[H]** |
| 0x008 | u16 | level | **[H]** |
| 0x00A | u16 | facing | degrees: 0 = +y, 90 = +x, 180 = −y, 270 = −x (spectator rings face the centre) **[M/H]** |
| 0x00C | i16 | x | panel x, −1 = not on the map at start **[H]** |
| 0x00E | i16 | y | panel y **[H]** |
| 0x010 | u8 | spawn_group | 255 normally; 1/2 only on off-map (−1,−1) units → reinforcement wave? **[L]** |
| 0x012 | u16 | unk12 | 1 on 96% of units |
| 0x014 | u16 | color_variant | 0xFFFF default, 0-8 on repeated generic units (palette?) **[L]** |
| 0x016 | u8,u8 | unk16, unk17 | |
| 0x018 | u32[5] | equipment | **item.dat ids** (id at item.dat+0x48); [0] weapon, [2] armour slot mostly; 0 = empty **[H]** |
| 0x02C | 12 bytes | unk2c | only set in map05001 |
| 0x038 | u32[20] | evilities | **Skill.dat ids** (5001 Theft Prevention, 2092 Poison Chance, …) **[H]** |
| 0x088 | u32[20] | skills | **magic.dat ids** (1001 Fire, 1201 Ice, 1303 Giga Star, …) **[H]** |
| 0x0D8 | u16[20] | skill_levels | parallel to `skills` **[M]** |
| 0x100 | u16[20] | skill_unk1 | parallel to `skills`, 0-9 **[L]** |
| 0x128 | u16[20] | skill_unk2 | parallel to `skills`, 0-9/99 **[L]** |
| 0x150 | u16[10] | weapon_mastery | index = weapon type of the equipped weapon (sword 1, bow 3, gun 4, axe 5, staff 6, monster 7/8); [9] is set on most units **[M]** |
| 0x164 | i16[8] | stat_mods | signed %, −10×8 on early enemies, −20 on the tutorial (HP SP ATK DEF INT RES HIT SPD?) **[M]** |
| 0x174 | u8 | flags | bit values 1,2,4,8,16 **[L]** |
| 0x175 | u8 | team | 1 enemy army; 2 neutral (all objects, GS, spectators); 3-5 extra armies **[M]** |
| 0x178 | i32 | ai | AI pattern 101-116, −1 for objects **[M]** |
| 0x17C | 20×10 bytes | ai_rules | {u8 kind, u8 arg, u16 v[4]}; v is often a map rectangle (x0,y0,x1,y1) that acts as a trigger zone **[L]** |
| 0x244 | u8[4] | unk244 | |
| 0x248 | u32 | geo_color | Geo Symbol colour (panel codes, 0 = clear) **[M]** |
| 0x24C | u32 | geo_effect | Geo Symbol effect = **GE.dat id** (1 Damage, 2 Recovery, 3 EXP, 12 Enemy Boost, 16 No Entry, 20 Invincible, 21 Move …, 61 Game Over) **[H]** |

The same slot numbers can appear twice. map00101 lists Warriors, then Prinnies at the same squares
(variant/phase sets chosen by the event script) **[L]**.

API: `ChrFile(bytes)`: `.units` (list of `Unit`), `.add_unit(char_id,x,y,level,template=None,**fields)`,
`.enemies()`, `.geo_symbols()`, `.to_bytes()`. `Unit` exposes every field above as an attribute, plus
`to_dict()`/`Unit.from_dict(d, template)`, `is_geo_symbol`, `is_object`, `ai_rule_list()`, `copy()`.
Deleting a unit = removing it from `.units`. Adding one = `add_unit` (copies a template record so the AI rules stay valid).

## 5. Stage ↔ map ↔ enemies

`dungeon.dat` has 223 records of 336 bytes. The loader is at `0x1400c3a00`. The table sits in a
shared DB arena, and no fixed capacity was found.

| off | type | field | |
|---|---|---|---|
| 0x00 | u32 | index | 0..222 **[H]** |
| 0x04 | u32 | **map_id** | → `map%05d` (101 → map00101 "Dried Up Wasteland") **[H]** |
| 0x08 | u32 | ? | 3001 on the first stage of an episode, otherwise map-like ids / 0 |
| 0x0C | u32 | ? | 14xxx / 22xxx on episode openers (event/talk id?) |
| 0x10 | u16,u16 | ? | 0, 1000-2001 |
| 0x14 | u16 | episode | 0-6 story, 16 postgame/DLC, 0xFFFF item-world rooms **[M]** |
| 0x16 | u16 | title/flag id | 5000 + 10·ep + stage **[M]** |
| 0x18 | u16 | ? | 1-37 (BGM?) **[L]** |
| 0x1A.. | | | 59, 1, 1, flags; 0x1E 8 bytes; 0x26 3×RGBA (fog/light colours?) |
| 0x36 | u8 | **base_x** | base panel **[H]**: in 194 of 214 battle maps it lands on an existing, unoccupied panel. The misses are hubs and demos |
| 0x37 | u8 | **base_y** | |
| 0x49 | 5×0x34 | names | JP, EN, FR, CHN, KOR (UTF-8) **[H]** |

Where the data for a stage comes from:
* **Terrain, geo panels, enemies, objects, Geo Symbols and their effects** all come from the map
  files (.hex/.gop/.chr). A story stage has no enemy list in the DB.
* **Base panel**: dungeon.dat 0x36/0x37 (not in the map).
* `Enemy_Create_TableDataBase.dat` (356 × 7 u32: id, kind 1 humanoid / 2 monster, char_id, ?, ?,
  weight, 100) and `Enemy_Parameters_TableDataBase` (203 × {u32 idx, u32 value}: 1→3 … 202→800000,
  a level/scale curve) are pools for **randomly generated** units: Item World floors built from
  the 6xxxx/7xxxx pieces through `RDFloorData.dat`/`RMDUNGEON.dat`, and level spheres. Those maps
  have empty .chr files **[M]**.
* `QuestEnemy.dat` (107 named quest targets) and scripted reinforcements (off-map `(-1,-1)` units)
  are run by quests and event scripts, not by the map **[L]**.
* `MapObjectTableDataBase.dat`: 60 × {u32 id 1000+, u32, u32}. Probably maps object ids to
  `mapobj_*.obf` models **[L]**.

### Modder recipes
**(a) Change the enemies on an existing stage**
```python
from d5lib.mapfile import MapPackage
mp = MapPackage.from_archive(301)            # Poison Beach
for u in mp.chr.enemies():
    u.level = 500; u.char_id = 1233          # all Asagi, level 500
mp.chr.add_unit(2020, 5, 7, level=99)        # extra Imp at (5,7)
open("map00301.lzs", "wb").write(mp.to_lzs())
```
Then put `map00301.lzs` into `Map/Map_JP.dat` with the mod system (vpath
`Map/Map_JP.dat/map00301.lzs`, or the member path `Map/Map_JP.dat/map00301.lzs/map00301.chr`).
`gamefs.encode_like` now uses `lzs_compress` automatically. Keep units on panels where
`no_panel==0`, and never on the base panel.

**(b) Change geo panels / symbols**
```python
g = mp.gop.blocks[0]; grid = g.color_grid(mp.hex.width, mp.hex.height)
grid[3:6, 3:6] = 1                     # red 3x3
g.set_color_grid(grid)
for gs in mp.chr.geo_symbols():            # units with char_id 4810/4811
    gs.geo_effect = 20; gs.geo_color = 3   # Invincible, blue
mp.chr.add_unit(4810, 2, 2, template=None, team=2, ai=-1, geo_color=1, geo_effect=5)  # new red ATK+ symbol (copy a GS record as template if the map has one)
```
**(c) New stage by cloning**
1. `new = MapPackage.from_archive(301).renamed(2999)`, edit it, then `new.to_lzs()` → add
   `map02999.lzs` as a **new member** of `Map_JP.dat`. NISPACK names must stay sorted
   (`write_nispack` keeps the list order you give it, so sort it).
2. `dt = DungeonTable(dungeon.dat)`; `rec = dt.add_stage(dt.by_map(301)[0], 2999, "My Stage")`;
   set `rec.base_x/base_y`; write it back into `Database_0.dat/dungeon.dat`.
3. Unknown: how the stage-select screen (`dungeonselect.cpp`) groups and unlocks entries (episode
   0x14, flag id 0x16, the fields at 0x08/0x0C). The safest test is to **replace** an existing
   stage's map id (e.g. a Carnage/Challenge record) with the new map.

## 6. `.obf` 3D container (`d5lib/obf.py`)

`u32 total_size, u32 version(=2), u32 section_offset[10]` (first = 0x30, contiguous). Sections 2,
3, 6, 7 and 9 are offset tables: `u32 n, u32 off[n]` (relative to the section, off[0] = 4+4n),
followed by the entries **[H]** (all 1135 obf files).

| sec | content |
|---|---|
| 0 | u32 0 |
| 1 | 8 bytes |
| 2 | table: root objects? |
| 3 | table: groups {u32 id, i16 parent, u8, u8, u32 n, u32 child[n]} [M] |
| 4 | motion/animation ints [L] |
| 5 | float block [L] |
| 6 | table: parts (lists of mesh indices) [M] |
| 7 | table: **meshes** {u32 vertex_count, u32 texture_index, u8 rgba[4], f32 x5 (1,0,0/0.5,4,1), u8 flags[12], i32 −1, u32 index[vertex_count]} [H]. Non-indexed triangle lists: the indices are always a running counter, so mesh k uses vertices [start, start+count) [H] |
| 8 | **vertex buffer**, 60 bytes: pos xyz, normal xyz, tangent xyz, colour rgba (0.5 = neutral), uv [H]. Positions are world space for maps (grid x·12, z·12) [H] |
| 9 | table: **textures** {u32 attr, TXF} [H] |

TXF inside obf (big-endian header as in `txf.py`): fmt byte 0x00 = A8R8G8B8 (bytes A,R,G,B; may have a
3148-byte ICC trailer), **0x02 = DXT1, 0x04 = DXT3, 0x06 = DXT5** (sizes match exactly, no mips)
**[H]**, 0x0b = ARGB1555, 0x0d = RGB565 (16 bpp big-endian; all 21 / 160 vanilla effect textures decode smoothly only so), 0x0c = effect-only variant with a different
size field (kept raw). Maps use only 00/02/04/06.

API: `ObfFile(bytes)`: `.textures` → `Texture` (`to_image()`, `replace_image(img, keep_format=True)`),
`.export_textures(dir)`, `.replace_texture(i, png, keep_format=True)` (re-encodes with a numpy
BC1/2/3 encoder, RMSE ≈ 5/255; `keep_format=False` switches to ARGB), `.meshes`, `.vertices()`,
`.set_vertices()`, `.export_obj(path)` (OBJ + MTL + PNGs), `.to_bytes()`.
Round trip: 1135/1135 files byte-identical (maps JP+EN, Object_*, Effect), including after
parsing the texture and mesh tables.

## 7. LZS compressor (`d5lib/lzs_compress.py`)

`compress(data, tag=b"pac", depth=16, lazy=True)` → complete .lzs. It uses exact 4-byte hash chains
built with a numpy stable argsort, a greedy parse with one-step lazy matching, distances 1-254,
counts 4-255, and the least frequent byte as marker (the same marker the originals use).
Measured over 14 maps (62 MB raw): ratio 0.520 vs the original 0.529, about 1.6-2 MB/s (a 6 MB map
takes ~3 s, the 20 MB map00121 ~11 s). Every output was decompressed and compared. Header csize =
file length − 4, as in the originals.

## 8. Round-trip results
* .hex / .chr / .gop: 1374/1374 files (448 JP + 10 EN maps) byte-identical; `Unit.to_dict →
  from_dict` is identical for every 592-byte record.
* dungeon.dat: identical.
* .obf: 1135/1135 identical.
* Full map: `MapPackage.from_dir → edit → to_lzs → from_lzs` keeps the edits, and untouched members stay identical.

## 9. Unknowns / todo
* `.hex` flag_a meaning, the env-block fields, and the exact corner order.
* `.chr`: spawn_group, color_variant, skill_unk1/2, ai_rules semantics, flags bits, team 3-5,
  why slots repeat (phases?).
* dungeon.dat fields 0x08-0x35 other than episode/base; stage-select/unlock logic.
* obf sections 2-6 (hierarchy, motions); texture attr word; formats 0x0b/0x0c/0x0d.
* Geo colour names are inferred from the exe texture order, not confirmed in game.
