# disgaea5.exe static analysis (PC, Disgaea 5 Complete)

Target: `D:\Games\Disgaea 5 Complete\disgaea5.exe` (x64, image base `0x140000000`, not packed).
Method: static only (capstone + pefile). The exe and `Data/` were not modified.
All addresses below are virtual addresses (VA). File offset = VA − section VA + section raw pointer
(`.text` VA 0x140001000 ↔ raw 0x400, `.rdata` VA 0x1408D5000 ↔ raw 0x8D4200, `.data` VA 0x140A2E000 ↔ raw 0xA2CA00).

Helper scripts live in `_research/exe/` (see the last section). Confidence levels: **High** = read straight from the
disassembly and cross-checked against the data files; **Medium** = read from the disassembly, not fully traced;
**Low** = inference.

---

## TL;DR for the mod tool

| Topic | Rule |
|---|---|
| Archive lookup | Linear scan of the in-memory directory. The name match is case-insensitive and works as a **prefix match**: the entry name must be a prefix of the requested name. The first match wins. Search order is **current text language archive → JP → the remaining ones**. You do not need to sort names. New names are found. Sizes, alignment and timestamps are not validated. |
| Loose files | None. Game data is only read through the NISPACK archives. The only files the game opens directly are `Data/Script/{script,talk}.dat`, `Data/Movie/*.mp4`, the Sound archives, config/keysettings and the saves. |
| DB tables | Count = `u16` at file+0 and the records start at file+4. Records live on the heap and the count is not capped, so **appending rows works** (up to 65535). The record size is fixed in the exe and must match exactly. There are no checksums. |
| DB ordering | "Classic" tables are **qsorted by ID at load** and then binary-searched, so file order doesn't matter. `*DataBase.dat` ("TableDataBase") tables are binary-searched **in file order**, so **keep them sorted by ID**. |
| New IDs | Give new rows IDs that are **greater than every existing ID**. Saves store the cached char.dat *row index*, so inserting IDs in the middle breaks existing saves. |
| Sprites | anm number = `char.dat +0xD4` (s16) (+ colour variant `+0x379` for generics) → `sprintf("anm%05d.lzs")`. It does not go through Anime_TableDataBase. |
| Saves | `%APPDATA%\Nippon Ichi Software, Inc\Disgaea 5 Complete\<steam account id>\SaveData\`. Each save is a fixed 0x89B8C8-byte state blob, stored as XOR + YKCMP. There is no checksum. |
| Scripts | 2-byte **big-endian** opcodes and 567 commands. Operand = tag byte + literal/var. The table extracted from the exe decodes **19053/19053** scripts of the shipped script.dat exactly. |

---

## 1. Archive lookup (NISPACK) — confidence High

### Opening (startup)
* `0x14070EE30` is the big data-init function. It builds 3 path buffers (`*_JP.dat`, `*_EN.dat`, `*_FR.dat`) and calls
  `Archive::Open(archive, paths, count, multiLang, decrypt)` = **`0x140408650`**:
  * Start → object `0x141E53590`, Anime → `0x141E561A0`, Map → `0x141E552F0`, Object → `0x141E57050`
    (count 3, `multiLang=1`).
  * Database → `0x141E54440` and Skit → `0x1469CE6D0` (count 1, `multiLang=0`).
* An archive object holds up to **12 slots of 0x138 bytes** (`0x140408B80` resets 12 slots). The fields it uses are
  `+0xEA0` (slot count), `+0xEA5` (multi-language flag) and `+0xEA6` (decrypt flag).
* Each slot is loaded by an async job (vtable `0x1409B97E0`, step function **`0x1400AE8F0`**):
  1. state 0: open `"./%s"` (`0x1403DABF0`, format at `0x140919464`).
  2. state 1: read **0x3C** header bytes.
  3. state 2: compare 8 bytes with `"NISPACK\0"` (`0x1409B97D8`), require `byte hdr[8]==0`, then `count = u32 hdr[0xC]` → `slot+0x28`.
  4. state 3: allocate `count*0x2C + 0x10` bytes and read the **whole directory** into `slot+0x30`.
     It is kept in memory for the lifetime of the process.
* Every read is de-obfuscated on completion (`0x1403DA970`: `b = (~b >> 4) | (b << 4)`, which is the same as `swap_nibbles(b ^ 0xF0)`).
  Archives **must stay obfuscated**, including the header and directory.
* File I/O goes through the Nmpl async file manager (`0x140C19EA8`, vtable `0x1409BE618`) on top of the CRT.
  There is no `FILE_FLAG_NO_BUFFERING`, so offsets need **no alignment**. (The 0x800 alignment used by `d5lib` is harmless.)

### Lookup: `Archive::Find(archive, name)` = **`0x140408430`**; `Archive::Read(archive, name, buf, size, extraOfs)` = **`0x140408940`**
```
lang = [ [0x140C059D0] + 4 ]          ; TextLanguage from config.ini: 0=JP 1=EN 2=FR 3=CHN 4=KOR
idx  = (lang==3||lang==4) ? 1 : lang  ; CHN/KOR use the EN archive
if multiLang:
    order = [idx if idx < count] + [0 if idx != 0] + [count-1 .. 1 except idx]
    ; EN user: EN, JP, FR     JP user: JP, FR, EN     FR user: FR, JP, EN
else: order = [0]
for slot in order:
    for e in slot.dir (linear, file order):
        if prefix_match_ci(e.name, name): return e     ; Read(): additionally skips e.offset == 0xFFFFFFFF
```
The compare loop (`0x140408570..0x1404085BF`) stops at the **entry's** NUL. It is ASCII-case-insensitive.
Consequences:
* **Case-insensitive.** The exe asks for `hospital.dat`, `makai.dat`, `skill.dat` and `News.dat`, while the archive stores
  `HOSPITAL.dat`, `Makai.dat`, `Skill.dat` and `news.dat`.
* **Prefix match.** Names longer than 31 characters are stored truncated, for example
  `ItemWorld_ProbabilityDataBase.d` and `Enemy_Parameters_TableDataBase`. They still match the full names the exe requests.
  Pitfall: a short entry name that is a prefix of another requested name, placed earlier in the directory, **shadows** that name.
* **No sorting needed.** `Database_0.dat` names are not sorted in the shipped file.
* **New names are found** in any of the 3 language archives. A file that exists only in `ANM_HI_EN.dat` is still found by a JP-language
  game, because all slots are searched. Priority goes to the language archive, then JP.
* **Tombstones:** `Read()` skips an entry whose offset is `0xFFFFFFFF` and falls through to the next archive.
  `Find()` (used to get the size) does not skip it. Use this carefully.
* **Not validated:** the offset and size fields are used as-is, and the stamp field `+0x28` is never read on this path.
  There is no checksum or hash anywhere in the exe. I found no CRC32, MD5 or SHA constants; YKCMP zlib uses adler only.
* A missing entry gives `size = -1` for DB tables, which is fatal. For anm packs the request silently fails.

---

## 2. Loose files / override folder / debug — confidence High

* **There is no loose-file override.** Game data is read only through the archive lookup above. The complete list of paths the game
  opens directly:
  * `./Data/<archive>.dat` for the archives listed in section 1, plus `Data/Sound_*/*.dat` (`0x1403F4700`, `0x1403F66EA`).
  * `Data/Script/script.dat` and `Data/Script/talk.dat`, as raw files via `0x1400BE960` (decrypt flag on). The paths are hard-coded, so
    **editing these two files in place is the only way to change scripts/text**.
  * `"Data/%s"` for movies through `MFCreateFile` (`0x140764DBF` → `0x14089CCF0`, names `Movie/dis5_ja.mp4` and `Movie/dis5_en.mp4`).
  * CRT `fopen` is used only for config.ini, keysettings.bin, the saves (see section 5) and crash dumps/bmp (`0x14006D9D0`, `0x14086CE80`).
* `config.ini` (`%APPDATA%\...\<id>\config.ini`, reader `0x1403DF5A0`) has `[ConfigSettings]` (TextLanguage, VoiceLanguage,
  window/resolution, VSync, AA, ButtonGuide, UseMouse). The only debug key is `[DbgSettings] EnableCrashReport`.
* No debug menu or command-line switches: `GetCommandLine*` is used only by the CRT. `FlagList_DebugDataBase.dat`,
  `FlagListDataBase.dat`, `FlagList_DLCDataBase.dat`, `DLC_ShopDataBase.dat` and `DLC_DeliveryDataBase.dat` are in the archive
  but **never referenced** by the exe. `IsDebuggerPresent` is only used by the CRT.

---

## 3. Database loading — confidence High

* The loader jobs are created in `0x14070EE30` (one ctor per table, `0x1400C0040..0x1400C4400`).
  Each job looks up the entry (`Find` → size), allocates `size` bytes on the heap, reads the whole file, and then calls the
  job-vtable slot `+0x18` ("loaded" callback). The full table is in `_research/exe/db_tables.tsv` (`db_tables.py`).
* **Classic tables** (char, magic, HABIT, item, ...). The callback (for example `0x1400C4200` for char.dat) does:
  ```
  count = u16 file[0] ; obj+0x10 = count ; obj+8 = file+4
  qsort(file+4, count, RECSIZE, cmp)     ; 0x140115050 = CRT qsort
  ```
  Lookups are binary searches on the comparator key (for example char `0x140061FA0`, magic `0x140062010`, item `0x140061EC0`).
  Because the table is **sorted at load, file order doesn't matter**. The shipped magic.dat, item.dat and HABIT.dat are not sorted.
  Duplicate IDs give undefined results (qsort is not stable).
* **TableDataBase tables** (`*DataBase.dat`, `skill.dat`, `WishDataBase.dat`, ...). `0x140139D10` sets `count = u16 file[0]` and
  `records = file+4`, then allocates `u32 index[count]`. The callback fills `index[i] = first u32 of record i` **in file order**.
  Lookups binary-search that index (for example `0x14008C420`, and `0x140749070` in the save code).
  So **records must be kept sorted ascending by ID**; every shipped file is. Some of these files carry a string/blob area after
  the fixed records (`fits` in the table below), which is addressed by offsets inside the records.
* **No fixed maximum counts.** All tables are heap buffers sized from the file. The count field is **u16** (≤ 65535).
  The record size is compile-time: file size must be ≥ `4 + count*RECSIZE`, and the exe does not check this.
* **Hard-coded record sizes and sort keys**. These are verified against the shipped files: every classic table is exactly `4 + n*RECSIZE`.

| table | rec size | key | shipped n | | table | rec size | key | shipped n |
|---|---|---|---|---|---|---|---|---|
| char.dat | 0x38C | u32 @+0xD0 | 806 | | magic.dat | 0x474 | u32 @+0 | 583 |
| HABIT.dat (evilities) | 0x430 | u32 @+4 | 110 | | item.dat | 0x460 | u32 @+0x48 | 1364 |
| charhelp.dat | 0x594 | u32 @+0 | 334 | | charPersonal.dat | 0x15C | u32 @+0 | 141 |
| JobRank.dat | 0x14 | u32 @+0 | 325 | | zukan.dat | 0x5328 | u32 @+0 | 94 |
| music.dat | 0x418 | u32 @+8 | 76 | | Quest.dat | 0x1604 | u32 @+0 | 516 |
| Feature.dat | 0x1C0 | u32 @+0 | 752 | | Trophy.dat | 0x2240 | u32 @+0 | 51 |
| skill.dat (TableDB) | 0x60 + strings | u32 @+0 | 796 | | Anime_TableDataBase (TableDB) | 0xC | u32 @+0 | 284 |
| StringListDataBase (TableDB) | 0x2C + strings | u32 @+0 | 3899 | | TextureDataBase (TableDB) | 0x7C | u32 @+0 | 3173 |

(The full list of all 76 loaders is in `db_tables.tsv`. `AttackMap.dat`, `comb.dat` and `name.dat` use custom header parsers.
`nameplate.dat` is an 80-byte stub, but the exe expects 0x16C-byte records.)

**Fixed limits found elsewhere (not table sizes):**
* Effect models: the start-up preload (0x14070eda0 -> 0x1404002c0) loads every EffectTableDataBase model into a
  cache of 512 entries whose data goes to the resource manager's slots 700 .. 1099: 400 models (vanilla 383; the
  401st crashes at 0x1402fb302). Lifted by loading on demand (`d5lib/fxpool.py`, `d5lib/native/d5fx.inc.c`).
* Script operands: `call_event` / `spawn_event` store the event id in 3 bytes (< 16 777 216: event 17003000 is
  never found), `cmd_3c00` the effect id in a signed 16-bit slot (<= 32767).
* Overloads: Overload ids 1 .. 213 (switches `dec; cmp 0xd4`), their skill rows magic 3000 .. 3255 (a unit keeps
  256 words for that range, `+0x2746a` of its data). New ones through hooks (`d5lib/overloads.py`, docs/OVERLOADS.md).
* The anm pack cache has 0x400 simultaneous slots (`0x1403FFC30`/`0x1403FFEB0`). The resident anm set has 0x401 slots of 0x150 bytes (`0x140301730`).
* Script engine: 0x100 concurrent threads, loop nesting depth 8, ≤16 call args (section 6).
* Event flags: `SetFlag` accepts flagId ≤ 19999 (bitfield at game-state `0x144FFA9A0 + 0xE`). The music unlock index (music.dat `+0x40C`) must be < 0x98 (152).
* Some hard-coded char IDs in code: 10–80 (story), 0x1F4 (500), 0x2DA, 0x7DA (2010), 0x9D8 (2520), 0x99C (2460).
  Generic-class ID ranges **1000–1310 and 2010–2300** are special-cased (portrait colour variant, `0x14021B290`).
* **No checksum or hash on any data file** (see section 1).

---

## 4. Sprite (anm) IDs — confidence High (field) / Medium (every call path)

* `AnmCache::Request(cache=[0x140C05A40], anmNo, ...)` = **`0x1403FFEB0`**. It first checks the resident set (`0x140301730`,
  which compares the ID as u16), then `sprintf(buf, "anm%05d.lzs", anmNo)` (`0x1403FFF8A`, format at `0x14093A3B8`). A job
  (`0x1400AE150`, vtable `0x1409B96E8`) then finds, `VirtualAlloc`s and reads the pack from the Anime archive (`0x1400AE1F0`).
  There are 97 call sites (`anm_callsites.txt`).
* **Characters: `char.dat +0xD4` (s16) is the base anm number.** Examples: Killia id 10 → anm 10, id 1011 → 1010,
  id 1343 → 1340, id 2325 → 2320.
  * Battle/field sprite: `0x14014DC60` → `anm = s16[+0xD4] + variant` (`+0x379`, a signed byte colour variant for generic classes) → `0x14014DA30` → `0x1403FFEB0`.
  * Portrait/cut-in: `0x14021B290` / `0x14021B370` → `anm = 10000 + s16[+0xD4] (+ variant byte +0x379 for generic ranges)`.
    Some cases use `12010 + variant` (`0x2EEA`).
  * The unit struct caches the portrait anm at unit `+0x2E36` (`0x14021E9D0`).
* **Anime_TableDataBase is not used for character sprites.** Its only reader is `0x1400B2A90`.
* Items use their own sprite field: item.dat `+0x56` (s16) is passed to the anm loader (`0x14016BC40`).
* Ranges: the field is **signed 16-bit**, so usable char sprite IDs are 1..32767 (portraits add 10000). The `%05d` format allows up to 99999.
  anm_startup uses the reserved request IDs 99997/99999 (`0x1869D`/`0x1869F`). There is no `< 10000` check in the loader itself.

---

## 5. Save files — confidence High

* Location: `SHGetSpecialFolderPathA(CSIDL_APPDATA)` (`0x14086DCD0`) + `Nippon Ichi Software, Inc\Disgaea 5 Complete\` +
  `%u` Steam account ID + `\SaveData\` (`0x140749EF0`, `"%s\%u\%s"` + `"SaveData"`).
  On this machine that is `C:\Users\PC\AppData\Roaming\Nippon Ichi Software, Inc\Disgaea 5 Complete\1638\SaveData\`
  (`Save_001.sav`, `AutoSave.sav`, `SystemSave.sav`). `config.ini` and `keysettings.bin` sit one level up.
  The `...\Steam\CODEX\803600` folder only holds the emulator's achievements/stats.
* Format (writer `0x140749000`, loader `0x140748A60`):
  * `0x000..0x1BF`: header, nibble-obfuscated. Magic `NIS_DISGAEA5_COMPLETE_SAVEDATA_` (or `..._TRIAL_...`), plus the save title, chapter text and a few small summary fields.
  * `0x1C0..`: `u64 0xE5B2688ACB279CA6`, then every whole u64 is XORed with `0xE76FCBE3F6D46A37`. The result is a
    **YKCMP_V1** stream (type 4 LZ) that decompresses to exactly **0x89B8C8 bytes**, which are `memcpy`'d over the game state.
  * **No checksum** other than the magic. `SystemSave.sav` is a 100-byte nibble-obfuscated block.
  * `save_decode.py` decodes a save.
* **What breaks when DB rows are added:**
  * Unit (character) records in the state are 0x4750 bytes each: name `+0xBC8`, **char ID** `+0x2E04` (u32), and **cached char.dat ROW INDEX** `+0x2E0A` (s16).
  * The exe uses the row index directly in 124 places (`movsx rax, word [unit+0x2E0A]; imul rax, 0x38C; add [0x140A31880]`,
    for example `0x14016A0FF`, `0x14021B3F0`). It is only recomputed on class change (`0x14015EB80`, `0x1401DCCCC`, `0x140220E03`),
    **not on load**.
  * ⇒ Adding char.dat rows whose IDs are **greater than all existing IDs** (current max 9001) keeps every old row index valid, so it is save-safe.
  * ⇒ Inserting IDs *between* existing ones, or deleting rows, shifts the row indices, and existing saves show the wrong class data.
    `save_roster.py` detects this.
  * Other references in the save are by **ID** (items, skills, flags). Treat the same "append-only, new IDs above the current maximum" rule
    as the safe default for every qsorted table (Medium confidence: not every table was traced).
  * The music unlock and event flag bitfields are fixed-size arrays inside the 0x89B8C8 state (see section 3).

---

## 6. Script engine (`Data/Script/script.dat`) — confidence High

### Container
Parsed by `0x14018E9B0` into the script manager (`[0x140A95B90]`, object size 0x848):
```
s32 count
u32 offset[count]      ; relative to bytecode base (read with movsxd)
u32 scriptId[count]
u8  bytecode[]         ; base = 4 + 8*count
```
`StartScript(mgr, id, ...)` = **`0x14018F4A0`**. It does a **linear** search of `scriptId[]` (the last match wins), so IDs do not need to be
sorted and appended scripts are found. There are 0x100 thread slots at `mgr+0x38`, and each thread is 0x268 bytes with `pc` at `+0x40`.
IDs 1000001–1000096 are single-instance.

### Interpreter / dispatch
**`0x1401910C0`** (`ScriptThread::Run`) works like this:
```
op_hi = *pc++ ; if op_hi == 0 -> thread finished
op    = (op_hi << 8) | *pc++                         ; 2-byte BIG-ENDIAN opcode
binary-search table[0..0x236] at 0x141D9D1A0 via obj->vtbl[+0x18]() (GetOpcode)
not found -> thread ends
obj->vtbl[+0x20](ctx{&yield, thread}, mgr)            ; Execute: decodes operands, then jmp handler (obj+0x10)
nonzero -> next instruction in same frame; up to 30 re-entries per frame
```
There is also a second dispatcher with the same table at `0x140162500`.
* The **command table has 567 entries (0x237)**, sorted by opcode from `0x0100` to `0x8C10`. They are pool objects
  `{vtable, u32 opcode, handler}` filled by the static initializer **`0x14000F300`**.
* The vtable class (`Execute`) defines the operand layout. **Every operand is `u8 tag`**:
  * `tag==0`: an inline literal (u8/u16/u24/u32).
  * `tag!=0`: a `u16` variable ID resolved by `0x1401920A0` (float vars) or `0x140192AE0` (int/special vars, a 251-case switch).
* Full list: **`_research/exe/script_opcodes.tsv`**. Columns: slot, opcode, vtable, execute, operand signature, handler,
  handler-level extra reads, handler size, name/hint, strings.
* Special encodings (handler-parsed). These are all implemented in `script_validate.py`:
  * `0x0104/0x0106 CallScript`: `u24 id` operand, `u8 argc` operand, then `argc × operand(u32)` (≤16) (`0x14008A000`).
  * `0x0140 If` (`0x14018C360`): `s16 skip` (relative to the end of the field, taken when the condition is false), `s8 ncond`, then
    `ncond × { operand(u16) lhs, u8 cmp (0x0A..0x0F), operand(u16) rhs }` with `(ncond−1) × u8 logic` (0x14 / 0x15) between them.
  * `0x1400 / 0x1410` SetFlag: `u8 pad, u16 flagId, u8 mode(1=set), operand(u16) value`. 0x1400 accepts flagId ≤ 19999
    (bitfield at `0x144FFA9A0+0xE`). 0x1410 accepts flagId−0x5014 < 100.
* **Validation:** decoding the shipped script.dat with this table ends **all 19053 scripts exactly on their boundary**, using
  420 distinct opcodes. Most scripts end with `0x0108`, not with a 0x00 byte.

Known or likely names. The category comes from the high byte and from what each handler touches:

| opcode | meaning |
|---|---|
| 0x0100 | StartScript(u24 id) — spawn a child thread, no wait |
| 0x0104 / 0x0106 | CallScript(u24 id, argc, args) (0x0106 = float-arg variant) |
| 0x0108 / 0x0118 | End (waits for child threads first) |
| 0x0110 / 0x0114 | StartScript with extra params |
| 0x0120 / 0x0130 | WaitChildren / WaitAllThreads |
| 0x0140 | If / conditional skip |
| 0x0148 | Nop |
| 0x0150 / 0x0158 | LoopBegin(start,count) / LoopEnd (nesting ≤ 8) |
| 0x0A00–0x0A40 | variable operations (u16 operand) |
| 0x14xx | flags / game-state bits |
| 0x46xx | sound: BGM `%d.ogg` (0x4600–0x4606, 0x4650); voice `%09d.ogg` (0x4620–0x4623); SE/voice `%09d.vag` (0x4630/0x4631) |
| 0x50xx | map: 0x5000 load map (`map%05d.%s`), 0x5008/0x5010 map objects |
| 0x64xx–0x66xx | actors/characters (char.dat / item.dat lookups, anm loads: 0x6401, 0x6405, 0x6410–0x6412, 0x64C8, ...) |
| 0x6Exx | talk/message window and portraits (talk manager `[0x140A9FBA0]`; 0x6E00/0x6E08 take a u24 first operand, probably a talk line/message ID — unverified); 0x6ED1 = play movie |
| 0x72xx | effects |
| 0x78xx / 0x7Cxx | items / game state |

---

## Key addresses

| what | VA |
|---|---|
| data init (archives, DB, script/talk) | 0x14070EE30 |
| Archive::Open / Find / Read | 0x140408650 / 0x140408430 / 0x140408940 |
| archive open job step | 0x1400AE8F0 |
| decrypt-on-read | 0x1403DA970 |
| language setting ptr (`+4`) | [0x140C059D0] |
| DB TableDataBase parse | 0x140139D10 |
| char.dat table obj / records / count | 0x140A31878 / [0x140A31880] / [0x140A31888] |
| char bsearch (row / ptr) | 0x140061FA0 / 0x140061F20 |
| AnmCache::Request | 0x1403FFEB0 |
| save write / load / dir | 0x140749000 / 0x140748A60 / 0x140749EF0 |
| script mgr ptr / header parse / start / run | [0x140A95B90] / 0x14018E9B0 / 0x14018F4A0 / 0x1401910C0 |
| script command table / initializer | 0x141D9D1A0 (567 × ptr) / 0x14000F300 |
| Overload of a unit (override +0x309c, else char.dat +0xCC via 0x14015ce30) | 0x140160810 |
| Overload id -> magic id (1-19, 100-114, 200-213 -> 3000-3047) | 0x1401DD050 |
| Overload usability / cost | 0x1401DC5C0 |
| Overload code dispatch (battle record +0xe60 = Overload in use) | 0x140163BF0 |
| Overload title banner (UI block 9032 animation 100 .. 500) | 0x1404B2FC0 |
| OverlordSkill.dat row by id (binary search) | 0x1400987D0 |
| Revenge gauge (unit +0x35bc, u16; 10000 = Revenge Mode) | 0x14015BDD0 (check) |

---

## Helper scripts (`_research/exe/`)

| file | purpose |
|---|---|
| `pelib.py` | PE loading, VA↔offset, capstone helpers, recursive-descent function disassembly (`fdis`), xref cache (`_xref_cache.pkl`, safe to delete) |
| `dumpf.py <va>...` | write the disassembly of a function to `dis/<va>.txt` |
| `strings_scan.py REGEX` | .rdata strings plus code xrefs |
| `scan_operand.py REGEX [MNEM]` | grep all instructions, for example `"\+ 0x2e0a\]"` |
| `scan_charfield.py 0xd4` | find reads of a char.dat field near char lookups |
| `jumptables.py` | list switch jump tables |
| `anm_callsites.py` | slices of the 97 anm-loader call sites (writes `anm_callsites.txt`) |
| `db_tables.py` | all DB loaders with family, record size and sort key (writes `db_tables.tsv`) |
| `script_opcodes.py` | extract the 567-entry script command table with operand signatures and hints (writes `script_opcodes.tsv`) |
| `script_validate.py` | decode every script in `_extracted/Script/script.dat` with that table (19053/19053 OK) |
| `save_decode.py <sav> [out]` | decode a save to the raw 0x89B8C8 state |
| `save_roster.py <sav> [char.dat]` | list unit records and flag stale char.dat row indices, to check whether a modified char.dat is safe for existing saves |
