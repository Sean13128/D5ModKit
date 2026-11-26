# Importing Disgaea 4 classes

How a Disgaea 4 Complete+ (PC) class becomes a D5 class with the kit, which parts come from D4, which from D5,
and the tools that check it.  Everything reads the user's own D4 install; no game data goes into the repository.

## Pieces

| | |
|---|---|
| `d5lib/d4source.py` | Read-only D4 readers: `D4Data(root).class_profile(first_id)` (per-rank stats, battle fields, innate and rank evilities, learned skills), `.evilities`, `.skills`, `.voice_lines(groups)` |
| `d5lib/sourcemaps/d4.json` | The reviewed D4 → D5 choices: which D5 evility each D4 evility works like, which D5 skill each D4 skill copies, personality names, voice mapping. Data, not code: new classes are mostly new entries here |
| `d5lib/sourceimports.py` | `plan_d4_profile()` turns a profile + the mapping into char.dat fields and new rows (pure, testable); `build_d4_pilot(..., source_root=D4 install)` builds the mod |
| `tools/d4_inspect.py` | Look at D4 data before importing: `class 1080`, `classes`, `evility <id/text>`, `skill <id/text>`, `voice <groups> --export DIR` (each mapped entry shows its mapping status) |
| `tools/build_source_pack.py` | Offline build into a scratch folder (`--d4-root`, `--unlocked-ranks 6`, `--voice-id`, `--class-name`, `--finalize`) |
| `tools/verify_d4_import.py` | Field-by-field check of a finalized build against D4; exits 1 on any mismatch |
| `tests/test_d4source.py` | Readers and planner on synthetic bytes (no game data) |

Typical run (paths are the user's):

```
python tools/d4_inspect.py --d4 "<D4>" class 1080
python tools/build_source_pack.py ...art/game paths... --source-ids 1080 1081 1082 1083 1084 1085 \
       --family 1350 --template 1150 --supported-families 1350 --d4-root "<D4>" --unlocked-ranks 6 --finalize \
       --output-path <scratch>/pilot
python tools/verify_d4_import.py --d4 "<D4>" --build <scratch>/pilot
```

## What comes from where

| Part | Source |
|---|---|
| Base stats, aptitudes, rank titles | D4 char.dat (exact stored values; growth is D5's) |
| Gender, MOV, move type, attack range, JMP, throw, counter, crit | D4 char.dat per rank |
| Fire / Wind / Ice resistance | D4 per rank; Star 0 (D4 has no Star) |
| Weapon mastery, weapon-type resistances, animation timing | D5 template class (D4 has no per-class weapon mastery letters or weapon resistances). D4 does carry per-rank weapon *forte* groups (`weapon_skills`); humanoid uniques derive one rank from them, see [Weapon mastery and weapon resistances](#weapon-mastery-and-weapon-resistances-d4-forte1-2026-11-17) |
| Evilities | New Skill.dat rows owned by the class.  D4's innate evility is **built in** (char.dat evility1, Unique).  D4's rank evilities are **Common evilities only this class can learn in the Skill Shop**, at D4's mana price. Generic D4 evilities any class could buy (Mind / Snipe Mastery) are left out | Generic D4 evilities any class could buy (Mind / Snipe Mastery) are left out: a unit has 4 innate slots |
| Skills | New magic.dat rows copied from the mapped D5 skill (its numbers can be changed), learned at D4's levels |
| Ranks | `unlocked_ranks` 1-6 in the class spec: those ranks are recruitable and rebirth choices from the start (no class mastery needed) |
| Voice | D5 voice by id until the D4 voice situations are mapped (below) |
| Face and cut-in | D4 pictures with their plain white background made transparent (`imgtools.remove_white_background(**sourceimports.D4_MATTE)`: keeps white highlights at the bottom edge, no halo) |

### Where the face and cut-in files come from (D4FACEWIRE1)

The pictures are extracted from the user's own D4 files by `tools/d4_extract_screen_art.py` (D4FACETOOL1), which writes
`character_id_<N>/face/swf<N:04d>.png` and `character_id_<N>/cutin/ANM_HI__anm<10000+N>/native_frames/p000_t000_b00_r00001.png`
under one folder.  The importer and `tools/d4_prepare_art.py` ask `d5lib.d4screenart.screen_art_dir()` for it:

1. `D5_D4_SCREEN_ART` (environment), then
2. `settings.json` key `d4_screen_art`, then
3. `<SOURCEPREP source folder>/d4-screen-art` (SOURCEPREP2 resolver; `Source/` inside the kit until it is merged), then
4. the October Character Forge extraction, only while a machine still has it.

The names are spelled once (`d5lib.d4screenart.face_rel` / `cutin_rel`), so a cast id and a class id are both zero
padded to four digits (`swf0070.png`, `swf1220.png`) and an old recorded `swf70.png` path is read as `swf0070.png`.

A named character's screen art is not always its own row: rows 180 and 220 record the pictures of resource ids 54 and
74, and the recorded folder (`character_id_00050`) is not the id either.  A recorded `--face-path` / `--cutin-path` is
therefore re-rooted by the id encoded in the **name** (`swf<N>.png`, `ANM_HI__anm<10000+N>`); a path that is not a
screen-art name is a deliberate prepared-image fallback and is kept as recorded.  An NPC unique reads its source row's
colour key (5301 -> 1154), so the on-demand extraction asks for that key before `tools/d4_prepare_art.py` prepares the
packet.

The importer fills a missing id from the same D4 copy it builds from (`d4screenart.ensure`): only the missing faces or
cut-ins are extracted, the previous `manifest.json` is merged (never replaced) and published atomically under a
per-folder lock, so the four parallel import jobs cannot drop each other's entries.  Each PNG is written to a temp file
and renamed into place, so a failed write never leaves a truncated picture for the receipt to certify; a retry
re-hashes the files on disk and repairs a receipt row that no longer matches.  It never writes into the October Forge
archive, including through a symlink to it or into one of its subfolders.

The extractor command is safe on the importer's folder: `tools/d4_extract_screen_art.py` takes the same per-folder
lock and merges its receipt, so a `--id` run keeps every other row and cannot drop a concurrent importer update.  A
PNG already on disk is kept and recorded; pass `--refresh` to deliberately replace the requested ids' pictures.

A `manifest.json` the art tools did not write is treated as user data: if it is another tool's JSON, a JSON non-dict
or a plain-text file, the run stops with `ForeignReceipt` (the CLI prints it and exits 2) before extracting or
replacing anything, and the file keeps every byte.  An empty `manifest.json` counts as absent.  The archive guard
covers the cache lock file, the manifest, and the actual folder each temp file is staged in and renamed within, so a
dangling lock symlink or a face/frames folder symlinked into the October Forge archive cannot be written through even
when the leaf name is symlinked back out.

The extractor output is pixel-identical to the Forge extraction for every id checked (529 faces and 740 cut-in cells,
D4FACETOOL1; a 4 cast + 3 class rebuild for D4FACEWIRE1).

## Weapon mastery and weapon resistances (D4-FORTE1, 2026-11-17)

D4 char.dat has no per-character mastery letters and no weapon-type resistances. It does carry a per-row
`weapon_skills` list (+0x094, 16 u16; `d4source.CHAR_LAYOUT`) of the weapon skills the row learns, and the
hundreds digit of each entry names the weapon family: 1xx fist, 2xx sword, 3xx spear, 4xx bow, 5xx gun,
6xx axe, 7xx attack magic and 8xx heal/support are both **staff**, 9xx tower skills have no D5 humanoid
weapon. The set of families present is the row's weapon forte (Valvatorez 10: sword+spear; Fenrich 20:
fist+axe; Emizel 30: staff+bow; Sister Artina 500: staff).

For a **humanoid unique** the importer (`d4unique.weapon_forte`, `d4unique.apply_weapon_forte`, called from
`plan_import`) derives the D5 letters with one explicit rule:

- every weapon in the D4 forte takes the D5 donor template's **best** stored `mastery_*` value
  (Warrior 1010 / Valkyrie 1020: 15, their sword/spear/axe rank), and
- every other weapon keeps the donor's value; every weapon resistance (`wres_*`) keeps the donor's value.

The receipt records the rule, donor values, forte and each raised weapon under
`source_static.weapon_forte`, and lists the adaptation under `gaps`. This is a derivation, not D4 data: with
no letters in the source a D4 forte cannot be more precise than "the donor's best". The 19 humanoid D4
uniques currently recorded on a 1010/1020 donor all run this rule; 15 of them have at least one weapon
raised (D4-FORTE1 report). Weapon resistances stay the donor's for every imported character, classes
included: D4 stores only fire/wind/ice resistance.

Generic D4 classes also have per-rank `weapon_skills` groups, but the class importer keeps the template's
mastery (table above); the rule is not applied to classes.

## D4 file layouts

`Data/DATA/<LANG>/DATABASE_<LANG>.dat`: NSAC v2 (28-byte header, index, names).  Tables: u32 count + fixed rows.

char.dat (684-byte rows) — `d4source.CHAR_LAYOUT` has every field with its confidence.  "High": matches the wiki
and is consistent across all classes (learned skills/levels, innate evility, rank evility list, gender, JMP,
tier).  "Medium": consistent across all classes, meaning taken from D5's matching field (MOV, throw, counter,
crit, resistances).  Stats are stored HP SP ATK DEF INT SPD HIT RES (RES/SPD swapped against D5).
EXP/mana yield (`grade` +0x1A2, `exp_value` +0x1AC, `mana_value` +0x1B2): not mapped, D5 donor values kept and labelled
"approximation"; code evidence and the per-game table in [IMPORT_YIELD.md](IMPORT_YIELD.md).

mskill.dat (evilities, 212-byte rows): mana u32 +0, id u16 +8, **value u8 +13** (the number the description's `%d`
shows: every one of the 432 rows with a `%d` has it — Aegis 30, Advance Guard 80, Last Fortress 50, Spear Defense
30; found by the Codex character bill of materials, `Research/character-bom-20261018/`, and re-checked), then name
and description text.  How D4 applies the number (conditions, stacking) is its code's.

magic.dat (skills, 356-byte rows): id u32 +40, description +56, name +184.

Voices: `Data/SOUND/<LANG>/voice.dat` is FAFS (`d5lib.fafs`); members `en/<group>/voice_<line>.nlsd` = 28-byte
header + RIFF MS-ADPCM mono, sample rate per line (~22 kHz for the Armor Knight) (`d5lib.sfx.read_wav` reads it).  A class has three groups
(first id, +1, +2) = its three personalities.  Line table `Data/SOUND/SoundData_Voice_<LANG>.dat`: 12-byte header
{u32 row size 64, u32 count, u32 reserved}, rows {u32 line, u32 group, f32 gain input,
s32 playback-rate input, 12 x u32 native category flags}. The signed rate input is at row+12;
native category 0 starts at row+16. Gain/rate fields require separate playback-contract work before conversion.

## Evilities: what "works like" means today

A new evility row has no effect of its own.  The kit's alias hook (`newclasses`, exe `0x14021878C`) adds the
mapped D5 evility to the unit's active list, and that D5 evility runs **with its own D5 numbers**: the game reads
the numbers of a fixed evility id each time (one lookup function, ~880 call sites).  So the imported evility has
the D4 name, D5's effect and D5's numbers; its description is the D5 one (leave `desc` out in the mapping), so the
game text says what really happens.  `relation` in the mapping says how close it is: `exact-effect`, `adapted`
(closest effect), `lookalike`, `omit`.

These relation labels describe reviewed mapping choices, not gameplay acceptance. The current Armor Knight
mapping contains no faithfully verified Evility port: Advance Guard also uses `adapted`, since its D5 donor
has a different magnitude. Independent conditions, ordering, stacking and rounding require native verification.

Own numbers and new conditions (front-only, "spear equipped") need new exe hooks: a value override at the lookup
call sites, then a small rule table for new conditions.  Research and a plan:
`/Volumes/Data/ai-tmp/claude/evility-hooks/REPORT.md` (local, not in the repository).

Save files keep evility ids per unit (16-bit), so new ids must stay below 32768.  Removing the mod while a saved
unit still has its evilities probably crashes the Status / Evility screens (true of every custom evility today).

## Unique vs Common, and the Skill Shop

* Every evility in a unit's built-in list (char.dat evility1-4) shows as Unique, whatever the row's kind says — so
  only D4's innate evility goes there.
* The Skill Shop's "Learn an Evility" eligibility check (`0x1407CD9F2..`) branches on the row's `source`:
  `3` = class evility (Common ones are gated by the owner class's rank row and its class mastery: it calls
  `0x1400744d0(owner + class_order - 1)` and `0x14021EBE0(owner)` and reads the result without a null check — for an
  imported class with no mastery that is a **crash at 0x1407CDAE1**, seen in game 2026-10-18);
  `4` = character evility (Common ones: learnable when unit id / 10 == owner / 10, no class lookup).  Imported
  classes therefore use `source 4`, `owner = family`, `kind 0`, `shop_rank 0`.  The shop can't gate by rank: all of
  a class's shop evilities can be learned from rank 1 (`first_rank` in the plan records D4's rank).

## Conditional damage Evility adaptations

Fire's Blessing, Wind's Blessing and Star's Blessing use D5 Lava Blessing, Storm Blessing and Comet Blessing
respectively (30%). Dream Hunt uses Asleep Attack and Spiritual Wave uses Brain Crusher (100%). These five
are explicitly adapted donor aliases: D5 checks its own element or status state and applies its own bonus
stacking and limits. The source applies damage boosts in sequence; equal stored percentages do not establish
equal combined damage, rounding, provider stacking or status behavior. The copied descriptions disclose the
D5 adaptation; the aliases do not override donor parameters.

They are Common Evilities learned through the existing character-owned Skill Shop path, not added to the
innate list or granted/equipped automatically. Each costs the donor's 3 Evility slots. Fire/Wind/Star's
Blessing and Dream Hunt retain the source 5,000 Mana price; Spiritual Wave retains 1,000 Mana. The normal
`source 4`, `kind 0`, owner-family, `class_order 0`, `shop_rank 0` path offers them from rank 1. No new native
rank gate is introduced.

For the selected D4 profiles, Fire's Blessing belongs to Dragon ranks 1–6; Spiritual Wave to Spirit ranks 1–6.
Wind's Blessing belongs to Mystic Beast ranks 3–6, Star's Blessing to Rifle Demon ranks 3–6, and Dream Hunt to
Succubus ranks 3–6. The established D5 shop adaptation makes those latter three available two ranks earlier.
The source planner retains `first_rank` as evidence; it does not use it as a shop gate. This is 30 D5 rank
eligibilities versus 24 source references across the five families. It does not authorize changing existing
units, building/installing a pack, or accepting native gameplay. Offense Mastery, Hypnosis Wave and Unholy
Talon remain deferred.

## Idle timing and weapon positions (`--d4-idle`)

The import places D4 poses into the D5 template's animations, so by default every animation keeps D5's timing
and weapon positions.  `d5lib.d4idle.apply` (build option `--d4-idle`) gives the class's own idle (front 6001,
back 6007) D4's clock and grip: it renders D4's idle frames, re-clocks them with `d5lib.rpgidle` (Armor Knight:
153-tick loop, moves at 82/94/106/130/142), then rewrites the weapon nodes (11-16, 111-116) from D4 — transform,
show/hide flags and the key **param** (the weapon pose drawn on the node; D5's back idle switches it to 17 after
tick 0, which drew no sword).  Body offset between D4 and the import is measured per tick by alpha overlap.
Both games count 60 ticks/s.  Attacks and other shared motions keep D5's tracks.  Test: `tests/test_d4idle.py`
(skipped without local installs).  In game the idle weapon only shows with "Hold the weapon when not attacking".

## Per-colour art

D4 palettes are mapped colour for colour onto the sprite and icon (`map_source_palettes`), and each of the 10
colours gets its own cut-in (`colour_variants`, `set_portraits` list).  **Faces (D4FACE1, rule D4-FACE-02, grade A):**
the game draws one face per class, `swf<class id>`, for every rank row (the char.dat colour id rounded down to tens:
Armor Knight 1081 -> swf1080, Medic 1241 -> swf1240) and for NPC rows (Chief 1154 -> swf1150); only characters with an
id below 1000 outside a few ranges (Des X colour 54, Nemo 74) use their colour id as the face number
(`d4screenart.game_face_number`, FUN_14047bfb0 / FUN_1401b1430, proven under Unicorn on the real char.dat, 154,613 cases).
All ten colour slots of a class pack therefore hold the class face (`sourceimports.class_face_files`, files
`face_<family>.png` and `face_<family>_<n>.png`, n = 1..9), and an NPC unique reads `swf<colour key rounded to tens>`.
The old path (`--no-d4-face-rule`) shipped swf<body + k> per colour (D4 does have those files; no code path of the game
selects them for these rows) or, when a neighbour did not exist (Medic, Necromancer), the one face for slot 0 only.
The cut-in is different: the game adds the unit's colour byte (`FUN_1401b0a50`), so cut-ins stay per colour.
`tools/d4_face_audit.py MODS_DIR [--gate]` compares every pack's face files with the face the game draws.
Mattes use `D4_MATTE` (no bottom fill, 4 px feather) to avoid the white halo.

## Voice situations (open)

D4 has twelve stored native category flags. Earlier readers treated the preceding signed rate input as
a thirteenth flag. `D4Data.voice_lines()` now returns `native_rate_input_signed`, twelve raw
`native_category_flags` and their nonzero `native_active_categories` (0–11). For compatibility, `flags`
still means the **legacy raw dword indices** (0–12), explicitly labelled by `flags_semantics` and also
available as `legacy_flags`; `legacy_raw_dwords` retains all thirteen unsigned source dwords. Legacy
index 0 is the rate input, and indices 1–12 correspond to native categories 0–11. Existing `volume` keeps
its rounded reader value; `volume_raw` preserves the source float. No event or gain translation is applied.

The reader rejects malformed 64-byte row extents, duplicate table/archive line IDs, missing selected
rows/audio, group mismatches, and invalid 28-byte wrapper/RIFF extents. It retains both wrapper and RIFF
sample rates; they can differ. `wrapper_hex` preserves all original header bytes and `riff` remains the
unchanged RIFF payload. Strict structural validation does not establish native playback fidelity or a
meaning for unknown header fields. Japanese database filename handling is unchanged in this correction.

D5ModKit registers 34 situation bytes in four kinds. Shared recordings or similar waveforms can help
find comparison cases, but neither audio identity, category numbers nor listening alone proves native
event equivalence. Cross-game categories remain unmapped until their actual event contexts are checked.
`tools/d4_inspect.py voice 1080 1081 1082 --export DIR` displays corrected native categories and writes
decoded PCM comparison copies named `<line>_p<group-offset>_c<native-categories>.wav` to a new directory
outside the source game and repository. These comparison WAVs are not byte-preserving conversion assets.
The kit's custom voices take `"personality": 0-2` on a line (`d5lib.voices`), so a future reviewed mapping
can keep each D4 personality's own lines.

## Still to test in game

Tested 2026-10-18 (Armor Knight): skills gain EXP; Legit Shield works; Lift Catch as a copy of Lift does nothing
(now omitted); only built-in evilities show as Unique (now: Aegis built in, the rest learnable in the Skill Shop);
Common evilities as class evilities (source 3) crashed the Skill Shop (fixed: source 4; re-tested: shop opens, the
class's evilities can be bought and equipped; face and cut-in clean).  Still open: all six ranks at the recruiter and at
rebirth, whether the Common rank evilities are active, each aliased evility's effect, the unit with the mod disabled.

## Additional monster attacks (prospective mapping batch)

Ten additional mappings cover Final Boss Arises, True Godly Weapon, Pringer Beam, Slime Cheer,
Sonic Wave, Prinny Barrage, Prinny Fusillade, Zombie Tornado, Kitty Brain Blast and Cat Strike.
They are explicit adaptations: copies retain the D5 donor's strength, SP cost, reach, area, height
limits, level-power curve, choreography and actor metadata. Pringer Beam and Prinny Fusillade
set Star element; Zombie Tornado sets Wind. Slime Cheer retains the donor's 40% Poison and Sonic
Wave its 50% Paralysis. Source character/rank learn levels still come from the D4 profile.
Descriptions identify the adaptations. Donor poses or actors may appear; these mappings do not
translate D4 skill scenes, source power grades or source targeting selectors. Offline planning
and serialization checks do not establish native gameplay or presentation acceptance. Adding a
mapping to source does not change an already-built or installed mod; existing unavailable-ability
notices remain until a separately reviewed successor is built and installed.

Two further prospective mappings use the ordinary effect-slot fields: Erynger Punch copies the
D5 attack with its added Paralysis removed (`effect2_type/value = 0/0`); Spiral Needle copies
the D5 attack with Poison added (`effect2_type/value = 21/50`). Their physical damage, element,
SP cost, power curve, targeting and choreography remain D5's. The nominal status chance uses
D5 immunity, duration and interaction rules; it is not proof of the source game's status lifecycle.
Actual D4 owners and learned levels are preserved. The unavailable-ability notices remain, and
these source mapping additions require a separately reviewed rebuild before affecting installed mods.

Eight more source-only adaptations cover Jelly Fight→Rock-Paper-Sticky, Muscle Slime→Cell Division,
Goodbye Sunset→Tailspin Dive, Removable Skull→Rotten Headbutt, Hundred Cat Fists→Rolling Cat Rush,
Hyper Zombeam→Ultra Zombeam, Erynger Roll→Mushroom Spin, and Hell's Cocoon→Lepidoptera.
Five retain donor status slots and values. Hyper Zombeam adds Poison21/50; Erynger Roll adds
Amnesia24/30. Hell's Cocoon replaces the donor's Poison/Sleep/Paralysis set with Sleep22/50 and
clears the other two slots. These ordinary field corrections preserve the reviewed source status
role while using D5 hit/immunity/duration/interaction rules. All retain D5 main damage strength,
formula, element, costs, level-power curves, targeting, choreography and actor metadata. Source
grades and targeting selectors are not converted. Descriptions disclose D5 status values and
adaptation limits; corresponding creature roles do not imply matching source scenes or geometry.
Source ownership and learned levels remain unchanged. These eight additions are source only;
no target leases, full build, current candidate integration or installation is implied. Existing
unavailable-ability notices remain until a separately authorized successor is verified.

## Explicit updates that preserve prior IDs

First imports keep their existing allocation behavior. Updating an accepted import requires an explicit
`d4-update-leases/1` ownership bundle and an independently pinned **canonical JSON digest**:
`sourceimports.d4_lease_digest(bundle)` (sorted keys, compact separators). This differs from the SHA256 of
an indented JSON file. The bundle is private evidence; do not commit game rows or local input paths.

The normal builders and tools forward the same context:

- `plan_d4_profile`, `build_d4_pilot`, `d4unique.plan_import`, and `d4unique.build_import` accept
  `previous_leases`, `previous_leases_sha256`, and an explicit canonical `owner_mod_id`.
- `d4expansion.build`, `lease_personality_rows`, and `lease_unique_help_rows` accept the bundle and digest;
  each selected materialized mod ID must be an owner in the bundle. Use explicit `builds`, not the legacy pair.
- `build_source_pack.py` and `build_d4_unique.py` expose `--previous-leases FILE`,
  `--previous-leases-sha256 DIGEST`, and `--owner-mod-id ID`. `build_d4_expansion.py` exposes the first two.
  Incomplete contexts fail before cache/build work. Generic updates also require `--original-state`
  (API: an explicit callable `backup_resolver`). Defaults without these options are unchanged.

Update mappings must also carry `source_evidence.uid` and `source_evidence.sha256` for every active
skill/Evility. Prepare a private mapping with the existing `complete_d4_mapping(immutable_inventory,
reviewed_mapping)` helper and supply `--mapping`; the public map alone does not contain private row hashes.

Each owner records the exact source profile fingerprint and source ability UID/hash, old source-to-target
ability IDs/donors/native row hashes, fixed character/voice/sprite/help/spec identities, prior learned
ID/level pairs and innate IDs, complete personality/help/Quest rows, and baseline metadata/patch/file hashes.
The bundle also records every captured enabled **and disabled** mod's database claims and quest progress
slots. Source/build aliases are not lease owners. A unique builder exempts only one byte-verified prior
own tree from its collision scan, retains all ability reservations, and reuses its recruitment Quest ID,
progress slot and help ID only if the remaining originals/mods leave them free.

Planning preserves old ability IDs even when an earlier source skill becomes mapped. New rows use the
existing allocator with every captured claim reserved. Omission, changed source/donor, duplicate/foreign
leases, any old leased target ID present in the original input tables and owner/profile mismatches fail.
A matching recorded native row hash does not admit an already modified table. Staging restores the pinned personality
and help IDs rather than minting replacements, checks their source metadata/linkage and native serialization,
and preserves recruitment contracts. Source voice banks still overlay before the final fixed-voice check:
a normal import may use its donor voice and then receive its explicitly pinned bank.

The prior replacement's entire file tree and metadata must still match their pinned baseline,
for generic and unique replacements alike. Updated selected content may
add learned skills and change help line text. For generic disclosure text, a bundle may separately pin
`expected_ability_adaptations`, produced with `d4_ability_adaptations(plan['report'])`; only those complete
per-ability lines may change, in the same source identity/order. All other metadata remains checked.
`gamepack` is supplied by the existing validated catalogue/materializer.

This mode does not discover installed state, replace accepted-import receipts, build art differently, or
approve installation. A future combined successor still requires fresh normal receipts, full enabled and
disabled collision preflight, and an exact comparison against **all** prior installed ID leases (including
Quest progress slots and event/resource identities). Private probe allocations are not installed-safe leases.

New skill allocation also reserves the script namespace. Each copied skill emits normal, short and mid-skip
wrappers at12000000/12100000/12200000 plus its ID. A magic-table-free ID is unavailable when any wrapper
would replace an existing event. `skills.event_ids` shares the existing preflight scanner for literal script
patches, skill wrappers/custom events and class-derived events. Preflight retains its existing raw-carrier
conflict semantics; allocation can additionally inspect raw Script carriers.

`charstudio.all_mod_skill_ids(mods, fs=None)` retains every added magic ID and adds these event-derived
exclusions. Optional `fs` supplies original Script events. Normal unique imports and the character studio
forward their available input; generic source imports combine original exclusions with their caller's
existing dynamic reserved IDs. Supplied old and completed mod roots, including disabled definitions, must
remain in that dynamic set. Existing pinned skill leases keep their IDs; an original-event collision refuses
instead of renumbering one. Their own prior emitted wrappers do not create false drift. Full preflight still
rejects foreign mod collisions. This is the existing allocator skipping occupied candidates, not a new ID
range or native capacity claim.


Pinned update metadata also accepts the exact legacy palette disclosure
`D4 body palettes per colour (N colour entries mapped exactly); D4 face and cut-in per colour where extracted; D4 class description`
when the current normal report uses the same N and explicitly zero approximations:
`D4 body palettes per colour (N exact entries, 0 nearest-source palette approximations); D4 face and cut-in per colour where extracted; D4 class description`.
Only the local comparison copy is adjusted; captured metadata, hashes, native trees,
source profiles and fresh import receipts stay unchanged. Changed counts, nonzero
approximations, different prefix/suffix text and unrelated metadata still refuse.
This is report-format compatibility, not an art-fidelity or gameplay acceptance gate.
### Source class descriptions

D4 generic imports use all three original class-help lines for Create Character's
recruitment description. Empty source lines keep their positions in the receipt.
The status-help pending-ability notice remains a separate display overlay; it
never replaces the source text used for the recruitment description. Receipts
retain both source and displayed help, with `source_help_available` identifying
missing source text. Missing descriptions display “Class description unavailable.”
without inventing a class description. The existing pooled UTF-8 UI-string writer
and description hook are unchanged.

## Engine path: exact evilities, mastery and six ranks (2026-10-26)

`tools/build_source_pack.py` can now put a built class through the engine
extensions in the same single finalization:

- `--engine-exact EMISSION` (`d4_evility-map/emit/d4_extension_rows.json`): every
  D4 evility the class owns that the reviewed vocabulary covers becomes its own
  extension row (`Skill.dat 8000 + D4 ID`, `source 4`, `owner` = the class family)
  and the donor alias is removed; `char.dat` and the class descriptor are rebound.
  An evility covered for one family is **not** re-emitted for another (one
  `Skill.dat` ID has one source-4 owner), so the other classes keep the alias.
  Evilities outside the exact set stay aliases (disclosed as adapted).
- `--mastery`: writes `patches/classes/mastery.json` for the class family. The
  extension has six spare per-unit mastery slots (47..52), so at most six
  families can be declared in one installed set; the seventh is refused.
- `--unlocked-ranks 6` (already the default): the recruiter/rebirth rank row and
  `char.dat color_id = family + rank` give six ranks with D4 palettes.

`tools/verify_d4_import.py` understands exact rows (source-4 ownership, D4 name,
and they satisfy the source list instead of an alias) and no longer crashes on a
build that writes no `magic.dat`. Its remaining expectations still assume a
class's evilities come only from its D4 rank profile, so the mapping's generic
"common" mastery evilities show as unexpected aliases - per-class truth is the
receipt/manifest until the tool learns that set.

## One-command rebuilds: what the batch runner needs (2026-11-09)

Learned while rebuilding the D1 Complete and Disgaea D2 rosters with `tools/import_game.py`:

- **Reference copies.** `--compare-installed` and the D1C palette/hurt-art references read the installed mods folder.
  When those packs are parked elsewhere (e.g. after a playtest reset) set `D5_INSTALLED_MODS` to the folder that
  holds them; every importer resolves it through `offlinepaths.installed_mods_root()`. Without it a D1C run still
  "builds" but loses its palette template and fails gates that have nothing to do with the content.
- **D1C builds are serial.** The D1C builder keeps process-wide state (sprite cache directory, output root, hurt-art
  source), so two entries built on threads overwrote each other: a cache `ValueError` on one class and another
  character silently built with the wrong texture/palette shape (10 palettes / 4 textures instead of 20 / 2). The
  importer now holds a lock around `build`; `--jobs` no longer speeds D1C up. A wrong palette/texture shape in one
  entry of a parallel batch is a sign of shared state, not of bad source art.
- **Lease checks skip the pack's own folder.** A rebuild compared against an installed copy of itself reported
  "evility lease occupied" by its own rows; claims from the pack being rebuilt are not collisions.
- **`baseline_preserved` (DD2).** Runs after the reviewed-abilities layer, treats schema aliases (the SCHEMA1 field
  renames) as the same field, and accepts an added reviewed-ability receipt where the reference copy has none.
  A lost or changed baseline row, a missing file, or any other added file still fails.
- **Cells on pages a bank lacks** are zeroed (the D4CELL1 rule) in the DD2 bank pass as well; `cell_pages` gate.
- **Monster uniques** need their N+2 placeholder in `anm_resident`: see ANM.md section 5a and the
  `resident_placeholder` gate.
- **Free ids.** A pipeline dry-run reporting a member "not installed" is not proof the number is free: check the
  vanilla archive members too (652 is a vanilla member).
- **Used ids are checked across importers (2026-11-09).** Each importer used to check ids only inside its own lease
  file, and leases computed against a parked mods folder went stale the moment another game was installed: two
  importers handed out the same sprite bank numbers (a D1C unique replaced a D4 unique's body in a live install) and
  110 of 146 DRPG packs reused Quest ids/slots of installed D1C/DD2 packs. `importcore.UsedIds` now runs for every
  built entry: every id a mod folder claims (sprite banks incl. N+1/N+2, class/char rows, charhelp, Quest id and
  slot, evility and skill rows) must be free against the vanilla game, every other importer's leases, and the
  installed mods (plus `--extra-roots`). `tools/check_used_ids.py` runs it on any folder. Whatever is installed keeps
  its ids; the not-yet-installed side moves. Free low sprite windows are scarce (11 left at this date): see the
  lease map in the project's LEASEGATE1 report before leasing new art.
