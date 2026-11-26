# New generic classes (`d5lib/newclasses.py`)

## Registry identities and physical leases

An imported generic can keep a community registry class ID while leasing an existing Kit sprite slot. Its class
spec must record both namespaces explicitly, for example:

```json
{"family":14080,"kind":"humanoid","sprite_family":1360,"template":1010,"unlocked":true,"unlocked_ranks":6}
```

`family` remains the identity in char.dat, JobRank.dat, recruitment lists, class-owned skills, help descriptions
and roster/save records. `sprite_family` owns body/companion/standing resources, colour/icon/portrait keys and the
physical slot's existing six unlock flags. Pass `sprite_family=` to `fill_class`; use the physical number when
building body and portrait files, and the registry family for `set_face` and the spec filename. The finalizers
resolve physical resources from the descriptor. `flag_of(class_id, specs)` accepts a keyed spec map or spec list.

Leases must be persisted in the package and never reassigned after recruitment. `validate_specs` refuses duplicate
physical slots (including a legacy low-ID class sharing a slot), mismatched human/monster types, missing registry
descriptors and the reserved 20000–21999 identity range. Allocation must also check disabled mods and installed
resource occupancy before choosing slots. Existing low-ID mods retain their exact flag assignments.

The native generic predicates admit only the declared registry families and their six ranks, by kind; no broad
high-ID range becomes a generic. This preserves the existing **119 physical slots**, 512-entry carousel and
512-entry Class tab. Registry numbering does not expand those capacities or implement custom class mastery.
Source tests cover stable leases, native patch address domains and synthetic in-memory save-codec roundtrips;
native recruitment, rendering and save/reload still require a game playtest.

New recruitable generic classes go first into the game's reserved **Human Dummy** / **Monster Dummy** families
(char.dat 1270 ... 1350, 2220 ... 2330: six rank rows each, already in comb.dat; the rows are edited in place, so old
saves stay valid), then into **families of their own**: humanoids 1360 ... 1990, monsters 2340 ... 2390 and
2620 ... 2890 (six rows appended). **119 classes in all** (73 humanoid, 46 monster), set by the unlock flags (below).
`newclasses.free_family` skips a family whose sprite numbers (anm family .. +2, portraits 10000 + family .. +9) a game
or mod file uses (2620: the game's anm 2622). One mod per class.

**What a family outside the game's own ids needs** (found and fixed 2026-10-12; verified in game with a humanoid at
1360 and monsters at 2340 and 2630: Hire Character list, hiring, battle and attacks):
* **The game's "is this a generic class" test** is inlined in ~60 places: 2010-2300 or 1000-1310 only -- "is this
  rank unlocked" (0x1401c5790) among them, so such a class never showed (this held the dummies 1320-1350 and
  2310-2330 back too).  At install (`generic_patch`, only when a class lies outside those ids) the humanoid test is
  widened in place to 1000-1999 (the game has nothing in 1320-1999) and every monster test jumps to a stub taking
  2010-2390 and 2620-2990 (the game's corpses, bottle mail and bosses 2400-2610 stay out); 8 places keep the bounds
  in registers and get stubs for both.  The sites are found in the exe at install (function bounds from `.pdata`,
  so a REX prefix is never misread).
* **A description row** (charhelp.dat, copy of the template's) and **comb.dat** team-attack rates (the template's
  row and column).  comb.dat is binary-searched by id (0x1400a0f90), so its ids are kept sorted and the matrix is
  reordered with them -- an id out of order made the search run away and the start-up load hang.
* **A monster's standing picture (anm family + 2) in the resident pack**: the game takes it from there only, and a
  monster family without one crashed the Hire Character list (2250 and 2340 tested; the dummies 2220-2240 have
  placeholders, which the class's own picture now replaces).  `facepatch.add_resident_blocks` appends it (its
  pictures after the pack's last ones) and renames a placeholder out of the way.
* Unlock flags `17283 + 6 * (index in ALL_FAMILIES) + rank`: the rest of the game's class unlock block
  17001-17999 (named up to 17282). The dummies keep 17283-17408, so saves keep their unlocks.

| Mod | Family | Template (animations) | DRPG unit |
|---|---|---|---|
| Class_Onmyo_Monk | 1270 | Clergy (1070) | 10030 |
| Class_Beast_Master | 1280 | Fight Mistress (1060) | 10031 |

## Making a new class

```
python tools/new_drpg_class.py --templates
python tools/new_drpg_class.py UNIT TEMPLATE "Name" --titles "T1,T2,T3,T4,T5,T6" --desc "one line for Hire Character"
```

This calls `newclasses.create_class`, which:

* takes the next free class slot (1270–1350);
* makes a mod `Class_<Name>`;
* builds the sprite (see below), the face (DRPG icon, mirrored) and the portraits (DRPG cut-in);
* copies the template's rank rows and rank chain, renamed;
* adds the description, three personalities and the class spec.

Then edit stats, skills and evilities on the Characters page and press Install. The two existing classes were made by
`_research/make_drpg_class_sprites.py` and `_research/make_drpg_class_data.py`, which set researched stats (Disgaea 4
and D2), skills and evilities.

## Sprites: exactly like vanilla (`d5lib/drpgmap.py`)

* **The source.** The vanilla generic classes and their Disgaea RPG twins draw the same pictures, pixel for pixel and at
  the same size. DRPG keeps D5's sheet layout: every humanoid unit has the same slots with the same poses, and a D5
  motion cell is usually exactly a DRPG slot. Some poses are stored mirrored, and hand overlays are loose pieces at
  fixed places.
* **The map.** `drpgmap` locates every cell of 18 vanilla classes in their twins' atlases. It records the slot or loose
  piece, the mirroring or rotation, and where the cell rect lies in it.
  * The twins agree with each other at 94–100%.
  * The shared map (`data/drpg_cellmap.json`, 123 cells of the humanoid motion set) is their consensus; twins packed
    differently (Warrior 10001, Magician 10005) are left out.
  * Each twin class also gets an own-pose map (`data/drpg_ownmap_<class>.json`) for its idle and special poses.
* **The build.** `drpgmap.build(uid, template)` gives the new sprite the template's complete animation set. Every cell
  is the DRPG unit's drawing of the same pose, placed exactly where the vanilla drawing was, never clipped. That gives
  the same frames, timing, ground contact and weapon handling (weapon node and hand overlays) as the template class.
* **Check.** A vanilla class rebuilt from its own DRPG twin, with a map that leaves that twin out, matches the original
  frame by frame (`_research/map_score.py`). Median outline overlap is 1.000 and the mean is 0.97–0.98, for Valkyrie,
  Fight Mistress, Clergy, Archer and Maid.
* **Templates.** A class can only use a template that has an own-pose map: `tools/new_drpg_class.py --templates`.
  Choose one with a similar build and weapon style.
* **Idle loops.** The template's own idle animations (6001 / 6007) play the unit's DRPG wait drawings.
  * `idle_loops` finds them.
  * `settle_idle_loops` holds the in-between frame DRPG doesn't have, so all 5 wait drawings play.
  * `strip_idle_overlays` hides the template's separate hand pieces, which floated over the new body: the Beast
    Master's fist above her head.
* **Weapons in the idle.** The template's idle grips are where the template's hands were.
  * `place_idle_weapons` puts the stand pose's weapon rig on the unit's own hand from `d5lib/data/drpg_hands.json`:
    one grip point per wait drawing, front and back.
  * A unit without hand points gets automatic hand detection, which is often a few pixels off. The build log says
    so.
* **Fine-tuning.** Where a weapon sits in any animation and frame can be adjusted by hand on the GUI page **Weapon
  Grips** (`docs/WEAPON_GRIPS.md`). The edits live in the class mod and are applied on top at install, so they
  survive a sprite rebuild.
* **Check.** `python tools/qa_sprite.py mods/<mod>/files/Anime/ANM_HI_JP.dat/anm<family>.lzs TEMPLATE --class`
  and `python tools/grips.py sheet <family> 6001 sword`.
* **Fixed bugs.** The old frame matcher was similarity-based and caused:
  * the frame turned 90° in back view;
  * feet sliding;
  * badly placed back poses.

  It is no longer used for classes.

Learning the map again: `_research/drpg_learn_map.py` (about 5 min per twin), then `_research/drpg_finalize_map.py`.

## Install time

**`.d5cl` exe hooks** (section made writable for the buffers below):

* **Unlock flags.** `0x14008d3f0` is the class → flag lookup used by "is this rank unlocked" (`0x1401c5790`).
  `0x1401c5920` is "unlock rank". Our ranks get flags `17283 + 6 * (index in ALL_FAMILIES) + rank`. A class with
  `"unlocked": true` gets `"unlocked_ranks"` ranks unlocked from the start -- **6 by default**, so every imported
  rank is offered by the Recruiter and by Reincarnation without levelling the class first; `"unlocked_ranks": 1-5`
  keeps a lower ceiling for a partial import.
* **Class carousel** (Hire Character, Reincarnation, Sub Class).
  * The builder `0x1406673b0` lists 47 fixed families. Our families are added after them (hook `0x140667500`).
  * The descriptions come from StringListDataBase `41000 + n` (hook `0x140667c61`).
* **The class lists have no 47 / 53 limit any more.**
  * The carousel's entries (8 bytes: class, unlocked ranks) and the Class tab's list and proficiency table (4-byte
    entries at `+0x1e404` and `+0x1e330`) live in buffers in our section, for 512 classes.
  * Every instruction that touches an entry jumps to a generated stub that does the same with the buffer as base:
    54 carousel sites, 4 Class tab sites, 2 proficiency readers, the append and the clear.
  * The two loops that filled the proficiency table with a fixed 47 rounds are replaced by loops over the whole list.
  * The sites were found by scanning the exe for `[base + idx*8 + 0x90/0x94]` next to a read of the selection or count,
    and confirmed with hardware watchpoints in game.
  * The counts stay in the scene objects.
* **Class tab list.** `0x1402a36b6` points the Class tab's family list at our extended copy.
* **Evility aliases.** `0x14021878c` runs just before the active evility list (unit `+0x2f30`) is sorted. Every new
  evility id adds the existing evility whose effect it has.
* Skill.dat is sorted by id at install, because it is binary-searched in file order.
* **Class events.** The template's class-keyed script events are copied to the new class at install
  (`add_class_scripts`): 3100000 + class id per rank, and for monsters the attack events 12010000 / 12110000 /
  12210000 + sprite id. They replace the dummy families' placeholders.

**`outfits._finalize`:**

* Faces 9017 for colours `family .. +9` are copied from the template's, with the face picture.
* One list icon covers all ten colours.
* The sprite is registered as an own-animation sprite (layer hook). Without outfits, the layer hook goes in `.d5ly`.

All absolute addresses in the hook asm are RIP-relative symbols defined after use, because the exe runs with ASLR.
An absolute `movabs 0x140...` crashes.

## Ranks and colours in the Recruiter and Reincarnation

What decides how many ranks a class offers (checked 2026-10-26 against the pinned exe; only the unlock flags do):

* The native list builder `0x140664df0` walks the 47 hireable families. A family whose first rank is locked is
  skipped; otherwise it writes one 8-byte entry `{class, highest unlocked rank}` into the scene list (`+0x90`, count
  `+0x208`) -- `entry+4` is the number of offered ranks, 1 to 6.
* The Hire Character (Recruiter) rank row stops at that count and previews `entry.class + option`
  (`0x140661e60`: `entry[+4] < 1` shows no row; the loop ends at `entry[+4] <= option + 1`).
* The Reincarnation window reads the same word (`0x14047f1c0`), so both screens offer exactly the same ranks.
* Nothing else gates them: `JobRank.dat` holds the mastery threshold and the per-rank stat bonuses only (rank 6's
  `next_id` wraps to rank 1 exactly as vanilla families do), and the class's mastery level is not consulted.

So six unlocked flags = six ranks on both screens. `newclasses.auto_ranks` returns all six by default
(`"unlocked_ranks"` in the class spec lowers it).

Colours follow the rank, not a picker: `fill_class` writes `color_id = sprite_family + rank`, so rank *k* is drawn
with sprite palette *k*. A class whose ten palettes are copies of palette 0 shows the same colour at every rank --
the D4 importer maps D4's own ten palettes when it is given the D4 install (`--d4-root`), and
`tools/verify_d4_import.py` now fails a build whose banks are identical or hold colours outside the matching D4
palette.

### Why a family can be missing from the wheel although the install is right

`FUN_1401c6110` ("is this class rank unlocked") starts with a class-id range test -- `(id - 2010) <= 0x122`
(monsters 2010..2300) or `(id - 1000) <= 0x136` (humans 1000..1310) -- and returns 0 *before* the (hooked) table
lookup for anything else. So a family of its own (1360+, 2340+, and the reserved dummy rows 1320-1350 / 2310-2330)
needs three things, in this order:

1. `generic_patch` widening the id tests at install (`cmp eax, 0x3E7` for the human test, a stub taking
   2010..2390 and 2620..2990 for the monster one). Visible in the installed exe: the bytes `3D E7 03 00 00`.
2. the lookup / setter / carousel / hire hooks (the `.d5*` section).
3. `char.dat` rows for the family, which the game loads at **boot** -- so the game has to be restarted after
   Install before the class can appear or before its unlock flags can be set.

The rank flags themselves are not a precondition: the lookup hook sets them (`au_set`) the first time the class is
asked about, so a save with every class flag at 0 still lists an unlocked class. A live diagnostic must read them at
`exemap.ACTIVE(0x144FFA9AE)` (`0x144FCCB0E` on the pinned build), not at the kit's own address.
`tests/test_recruit_runtime.py` runs the real unlock code and the real list builder on the pinned exe and fails if
any of 1-2 is missing; note the saved state must come from a *relaunched* game.

## One wheel, every class

The Recruiter (Create Character) and the Rebirth menu build their class list in one native function
(`0x140664df0`, shared by both), and the Kit moves that list into a 512-entry buffer: D5's own 47 families
first, then every enabled class mod's family, appended by the carousel hook while there is a free slot.  There
is **one** list; imported classes stand beside D5's.

A class mod may still declare which game it came from, and the metadata is validated even though it no longer
routes anything:

```json
{ "category": "classes",
  "wheel": "d4",                       // d5 | d4 | d1c | dd2 | overlord (lowercase; anything else fails)
  "source_import": { "identity": { "source": "d4", "..." : "..." } } }
```

`wheel` wins when present; otherwise the name comes from `source_import.identity.source` (or
`source_import.source_game`); a class mod with neither is recorded as D5.  `d5lib/wheelmeta.py` validates it:
an unknown name fails the install, and one family declared on two different values fails it too, whichever mod
is enabled first (`tests/test_wheelmeta.py`).  The value is bookkeeping, not a menu page.

**Why there is no paging.**  WHEELS2/WHEELS3 put a Shift-key page filter into the same hook.  TEST17 shipped
it and, live, opening Hire Character wedged the game's main thread twice — with the page key held and with no
key at all (`live-verify/LIVE14-REPORT.md`).  TEST16's single list had already been walked live: 101 entries,
all 13 D1C classes, no freeze.  TEST18B is that behaviour with the larger class set, and the capacity is
measured (`tests/test_wheel_single.py`: 47 + 67 families, well inside 512).

The list is rebuilt at the same point in the build as the vanilla one, guarded against re-entry (one buffer is
shared by every scene that builds it), and a family is listed once with its six rank flags folded in.  Class
ids, ranks, flags and mastery slots are untouched.

## Sub-class

The Strategy Assembly's "Set a Sub Class" list keeps its rows inside its own screen object and has room for 47 (see
`docs/EXE_ANALYSIS.md`, Sub-class lists): a unit with most vanilla classes unlocked sees few or no imported classes
there. The Status **Class** tab lists every class (512 entries), so the Kit makes it the place to choose one, as
Cryswar's Overlord does (The Unlicense; `d5lib/subclasstab.py`, section `.d5sb`, on whenever the build has class mods):

* Status -> a unit -> Class tab -> highlight a class -> **Confirm**. The unit's sub-class becomes that class at its
  highest unlocked rank; a class whose first rank is locked is refused (the Assembly list would not show it), and so
  is the unit's own class.
* Only units of the army (the persistent roster) are changed; nothing happens on other tabs or in battle copies.
* What is saved: the unit's own sub-class u16 (`+0x35AC`), the same field the Assembly screen writes. Nothing else.
  Without the class mod the id stays in the save and the game finds no `char.dat` row for it. The Assembly's sub-class
  screen would then draw the "current sub-class" name from the null page (a crash); `d5lib/subclassguard.py`
  (section `.d5sv`, in every build) skips that panel instead. Choosing a vanilla sub-class before removing a class mod
  is still the tidy way.
* Class experience for the sub-class follows the mastery hooks (`docs/MASTERY.md`): only families they carry gain it.

## Skills and evilities

Skills copied with `add_skill(copy_of=...)` play the source skill's choreography: the wrapper event is
12000000 + skill id; see `docs/SKILL_ANIMATIONS.md`. `_research/make_drpg_class_skills.py` sets up the classes' looks.

* **Talisman Storm:** its own copy of Magician's Astral Wave, made Star-element. The rune circle is the DRPG yin-yang,
  and a purple wall of ofuda rises around the caster (effects 3000 and 3001).
* **Shikigami Drain:** Magic Siphon's choreography. The Clergy template has the same special poses 7001/7007/7011.
* **Beast Rush:** Fight Mistress's Anaconda Impact choreography.
* **Dominate and Wild Groom:** the support buff choreography of skill 1501, with three stat-buff effects each (11–16 =
  ATK, DEF, INT, RES, HIT, SPD).

The Onmyo Monk also learns D5's Star line (1301–1305) and the Geo skills (1901, 1903, 1905, 1906). D5 has no
EXP/Mana-gain buff, so Wild Groom raises DEF, RES and SPD instead.

Evilities (new id → effect of):

| Class | Evility | New id | Effect of |
|---|---|---|---|
| Onmyo Monk | Mass Blaster | 1270 | 1210 |
| Onmyo Monk | Onmyo Wisdom | 1271 | 1211 |
| Onmyo Monk | Geo Protect | 1272 | 2195 |
| Onmyo Monk | Geo Damage | 1273 | 2193 |
| Onmyo Monk | Starlight | 1274 | 2194 |
| Onmyo Monk | Feng Shui | 1275 | 2190 |
| Beast Master | Dark Tamer | 1280 | 6088 |
| Beast Master | Synchronize | 1281 | 4500 |
| Beast Master | Pack Leader | 1282 | 3038 |
| Beast Master | Thick Hide | 1283 | 12 |
| Beast Master | M Weapon Master | 1284 | 1185 |
| Beast Master | Wild Groomer | 1285 | 2131 |

## Verified in game (2026-10-07, not saved)

* **Hiring and screens.**
  * Both classes hire end to end, including personalities, colours and the recruit message.
  * The list icon, Status cut-in portrait and the Specials, Evilities and Class tabs show correctly.
* **Lists past the old limit.** With all 47 vanilla classes unlocked in memory:
  * the Hire carousel shows 49 classes, and class 49 (Beast Master) hires;
  * the Class tab shows all 49 entries.
* **In battle.**
  * The Onmyo Monk holds a staff in his hand and swings it in a normal attack.
  * The Beast Master holds an axe, front and back.
  * Every animation frame of both sprites matches its template's pose and place: 437 frames each.
* **Class skills:** all five play their choreography with the right effects (see SKILL_ANIMATIONS.md).

## Verified in game (2026-10-08, not saved), after the idle / weapon fix

* The Monk's idle cycles through his DRPG wait drawings; the QA counts 5 distinct drawings in 6001 / 6007, where
  it was 2.
* The Beast Master's back idle has no fist above her head any more.
* With real weapons equipped, seen in the back view the units face in battle:
  * Monk with Staff of Logic: the staff's end in his closed right fist, the head behind his shoulder;
  * Beast Master with Guilty Axe: the axe over her shoulder in her own hand.

  Both match the Weapon Grips page's preview.
* A sub weapon (Wooden Cane) isn't drawn in the idle; only the main weapon is.

## Monster classes

The Monster Dummy families (2220–2330) are reserved the same way. Monster sprites use other motion sets and DRPG
monster atlases have their own layout, so they need their own pose map (twins: DRPG monster units ↔ D5 monster
classes). The same approach applies but hasn't been done yet.

## Harness notes

* With `focus on` the game no longer sees the real mouse (`GetCursorPos` and the DirectInput mouse are hidden). List,
  menu and battle cursors follow the keys.
* `tools/walk.py`: walk or face an NPC in the hub. Teleport by writing the leader position (`0x142349160 + 8/0x34/0x90`).
* `tools/hire_test.py`: run the Recruiter.
* `tools/battle_nav.py`: `goto(x, y)` in top view (V) and `menu(entry)` by help line.
* `tools/unlock_all_classes.py`: unlock every vanilla class in memory (testing only).
* Actions are queued in battle: R → Execute runs them. Keys: Z allies, X enemies, V top / quarter view.
* `trace ADDR 1 0 LABEL` is an execution watch that logs every call (see SKILL_ANIMATIONS.md).
* **Game speed under the harness.** Battle skits are fast-forwarded by the game's own options, 'always fast forward
  the skits during battle' and 'Skit Fast Forward Speed' x2/x3/x4. The harness runs them at `set skitff 2` (x2) by
  default. Memory only, nothing is saved.
  * `set skitff 0` = 1x, for frame-accurate captures; `-1` = the game's own setting.
  * `tools/fps.py` shows frames per second, logic ticks per second and the fast-forward state.
  * While the harness is on (`remote=1`), saves, config.ini and keysettings.bin are never written.
