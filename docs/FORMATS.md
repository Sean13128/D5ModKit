# Disgaea 5 Complete (PC) — Format notes (shared knowledge base)

Game root: `D:\Games\Disgaea 5 Complete` — **never write to `Data/` directly during research**.
Toolkit root: `D:\Games\Disgaea 5 Complete\D5ModKit` (Python 3.10 + numpy, Pillow, PyQt6).
Library package: `d5lib/` (import with `sys.path.insert(0, D5ModKit)`).
Extracted cache: `_extracted/` (produced by `extract_all.py`; mirrors `Data/`).

## Obfuscation (`d5lib/crypt.py`)
All NISPACK archives + `Script/script.dat` + `Script/talk.dat` are byte-obfuscated:
`plain = swap_nibbles(b ^ 0xF0)`. Sound archives are NOT obfuscated.

## NISPACK (`d5lib/nispack.py`)
`"NISPACK\0"`, u32 0, u32 count, then count × {char name[32], u32 offset, u32 size, u32 stamp}.
Data 0x800-aligned. Names are NOT required to be sorted: the game scans the directory linearly, case-insensitive, and the first entry whose name is a PREFIX of the requested name wins (see EXE_ANALYSIS.md). Nested NISPACKs inside Start_*.dat are *plain* (`d5lib/nested.py`).
`*_EN.dat` / `*_FR.dat` contain only localized replacements of files that also exist in `*_JP.dat` (JP = base set).

## Compression
* `.lzs` (`d5lib/lzs.py`): header ext[4] ('dat'/'pac'), u32 rawsize, u32 compsize, u32 marker.
  marker+marker = literal marker; marker+d(+1 if d>marker adjust)+count = back-reference (distance ≤ 255).
* `YKCMP_V1` (`d5lib/ykcmp.py`): type 7 = zlib, type 4 = Yukes LZ.
* `pac` (inside map*.lzs) (`d5lib/pac.py`): u32 count, 12 pad, count × {u32 off, char name[28]}, offsets relative to end of table.

## Archives
| Archive | Content |
|---|---|
| Anime/ANM_HI_{JP,EN,FR}.dat | `anmNNNNN.lzs` (sprite animation packs, LZS 'dat'); `anm_resident`, `anm_startup_N` |
| Database/Database_0.dat | ~90 fixed-record tables (`char.dat`, `magic.dat`, `item.dat`, ...) |
| Map/Map_{JP,EN,FR}.dat | `mapNNNNN.lzs` = pac of `.hex` `.chr` `.obf` `.gop` |
| Object/Object_*.dat | `.obf` 3D objects (map objects, mki* = Makai edit parts) |
| Script/script.dat | event script bytecode (offset table at start) |
| Script/talk.dat | dialogue lines; multilingual |
| Skit/Skit_0.dat | `skitNNNN.dat` |
| Start/Start_*.dat | nested NISPACKs: `Texture.dat` (UI .txf), `charworld.dat`, `Effect.dat` (effect*.obf), fonts |
| Sound_BGM | `PS_FS_V1` archive of .ogg (see ref/musicer.cpp) |
| Sound_SE | `DSARC FL` of .vag (see ref/vagger.cpp) |
| Sound_Voice / Sound_Msg | `FAFULLFS` archives |

## Text encoding
UTF-8. Database tables hold 5 fixed-width string slots per text: JP, EN, FR, CHN(zh-TW), KOR.
In talk.dat, each line is a sequence of `<langbyte><utf8 text>\0\0` with lang bytes `x`=JP `y`=EN `z`=FR `{`=CHN `|`=KOR.
Inline tags seen: `<c緑>Killia</c>` (colour tag).

## Database tables
Header u32 count (some tables have a larger header), then fixed-size records.
Example `char.dat`: 4-byte header, 806 records × 908 bytes. Names at record+0xF4 (JP), +0x130.. etc.
`ref/database_0.scheme` (from BTAxis/D5tools) has partial layouts for music, TownFuncCharCenter, CheatShopInformation, Curry, HABIT, item.

## TXF texture (`d5lib/txf.py`)
16-byte header, **big-endian** fields: u8 fmt[4] (`00 01 01 01` = 32bpp), u16be width @4, u16be height @6,
u32be ? @8 (0x00010000), u32be pixel_bytes @12; then pixels. Some .txf are actually DDS (after YKCMP type 4).

## Executable
`disgaea5.exe` x64, not packed. Source paths leak: `c:\project\pc019\program\game\src\graphics\nisanm.cpp`,
`...\anm\animefiletable.cpp`, `...\anm\userpalletmanager.cpp`, `...\system\nislzscomp.cpp`, `...\system\nistxffile.cpp`,
`...\demo\talkmanager.cpp`. Format strings: `anm%05d.lzs`, `map%05d.%s`, `skit%04d.dat`, `effect%04d.obf`, `mki0%04d.obf`.
