# Character bank (command line, v1)

A save holds **128 characters in total** (army + reserve): the game's own unit creation
(`roster_create_unit` 0x1402EA3E0 in the Steam build; 0x1402EA890 in the kit's known-build names) refuses beyond that. The bank is the shelf for everything else.
The game has loaded bank-written saves and played the imported units (BANKLIVE1, 2026-11-13).

## Tool

    tools/unit_bank.py export <save> <unit> <bank dir> [--move] [--live]    unit = roster slot or unique name
    tools/unit_bank.py import <bank file> <save> [--live] [--move] [--allow-duplicate] --db <installed Database_0.dat>
    tools/unit_bank.py list   <bank dir>

Built on `d5lib/unitbank.py` (one 0x4750-byte roster record per bank file, fresh serial on import).
Works on save copies, and on the game's real saves (BANKLIVESAVE1, below).

## Real saves (BANKLIVESAVE1)
The page opens any save, including one in the game's folder (`Choose save…` starts there when it exists). Before every Export (move)
or Import that writes a save in the game's folder or in a kit profile's saves, `unit_bank.protected` copies the save and its
`.d5learn.json` companion with `savegame.backup` (the save cleaner's function) to `<kit>/state/save_backups/<time>_bank/<player id>/SaveData/`;
the result sentence names that folder. Refusals, nothing written: no backup possible ("could not make the backup first ... nothing was
written"); `disgaea5.exe` running ("Disgaea 5 is running: close it first", the kit's `workspace.game_running`, only for the game's own
folder). After the write the save is read back and `unitbank.verify` runs; a problem puts the backup back (save and companion) and says so.
The bank file stays in the bank when an import is put back. A save anywhere else is your own copy: no backup, as before.
The CLI still refuses a path in the game's folder unless `--live` is given (then the same backup and game-running rules); a kit profile's
saves need no flag. Restoring a backup is by hand (copy the files back); the page does not offer it. Tests: `tests/test_banklivesave1.py`.

Import changes nothing and refuses when:

| refusal | rule | source |
|---|---|---|
| class not installed | the unit's class id has no row in the installed char.dat | ours |
| save full | army + reserve >= 128 | game, 0x1402EA3E0 (Steam build) |
| story-locked | see below | game, 0x140654F20 |
| reserve unit (export) | units in the guest tail / reserve | ours (story hand-overs live there) |

## The game's Dismiss rule (story lock)

The Recruiter's Dismiss list is built by 0x140655030, which asks 0x140654F20 per unit:

- character id **2460 or below 1000** = "unique"; the game answers text 10650
  ("unique characters cannot be dismissed") ...
- ... **unless** the id is in the exe table at 0x140A0D968 (39 rows of 10 words, id in word 0).
  Its 36 ids below 1000 are the DLC characters: 510-760 in steps of 10, 800, 860-940 in steps of 10.
  Those are handled like generics.
- any other unit: refused only while it holds items or is in use (squad, etc.).

`unit_bank.story_locked` applies exactly this to the game's own char.dat rows (constant `DISMISSABLE`).

Consequence for mods: a character a mod places on a Dummy row **below id 1000** cannot be dismissed
in the Recruiter either. The bank (or `Save.remove_units`, a port of the game's Dismiss) is the way
to take such a unit out of a save. Not yet checked in the running game.

## What travels, what does not (BANKTEST1, 2026-11-13, offline on save copies)
Inside the 0x4750 record, so it travels as it is: the five equipped items, name/title/level/class, the skill list with levels
(+0xCC0, 16 bytes each), weapon mastery, the 125-byte learned-evility bitmap, the innate evilities, the subclass id (+0x35AC), the
class-mastery counters. Re-addressed on import: serial, roster index, char.dat row (+0x2E0A). Dropped on import: squad and group.
Not carried, nothing refuses it: the NG+/base cast table (64 serials at state+0x8810A0, written by 0x1406A5950; a serial
it cannot find is skipped by its readers, and the game's own Dismiss leaves it too); a subclass or +0x2E36 class id the target char.dat lacks (only the main class is
checked).

## BANKFEAT1 (2026-11-13): Import moves the file, mod evilities travel
- **Import moves the bank file** into `imported/` of the bank folder (never deleted, never overwritten: a name clash gets `-1`, `-2`),
  after the save was written and verified, so a unit cannot be imported twice. The page always does this; the CLI only with
  `import --move` (today's copy behaviour otherwise). A refused import or a failed write leaves the file in place. The bank list
  reads only the folder itself, so `imported/` is not shown; to re-import, move the file back.
- **The learned companion travels** (`<save>.d5learn.json`, `d5lib/learned.py`). It is keyed by serial and bound to the save's size
  and sha256. Export reads the unit's `learned` ids from the companion when it is bound to the save as it is (a stale one is
  ignored) and stores them in the entry's `learned_extra` (the field already existed; bank format stays 1, files without it import).
  Export with move removes the unit's entry and re-binds the companion to the shrunken save. Import adds the ids under the NEW
  serial and re-binds the companion to the written save (`unit_bank.write_companion`). A save with no companion gets one only when
  the installed Skill.dat is known (CLI `--db`, the page reads the game folder), because the companion records the table generation;
  otherwise, and when the target's companion is stale, the import says the evilities were not carried and leaves the companion alone.
  Order: save written first, companion second; a crash between leaves a companion that names the old bytes, which the game rejects
  (never silently pairs).
Import validates the bank file first (`unit_bank.check_doc`): kind, format 1, one unit, name/class/record present, record length, and the
record's own class must equal the listed class. The live-folder refusal also recognises the folder by its name (a Mac has no %APPDATA%).

## Faces on the page (BANKFEAT1 piece c)
`bankview.Art` drew faces from `outfits.base_face_image`, which reads resident block 9017 through a pickle cache
(`cache/face_block_9017.pickle`) written from whichever game was read first. A cache written from the clean game has 1,679
animations and none of the imported characters' faces (the installed resident pack has 3,497: the importers paint each character's
face into block 9017 as animation 10000 + colour id, `d5lib/facepatch.py`). The page now reads the block from the installed
resident pack itself (`_face_file(fs, fresh=True)`, cache untouched). The 245 imported classes of the four PLAYSAVE1/live save copies
(45 D4, 45 D1C, 9 DD2, 146 DRPG) all resolve, as do the 58 Disgaea 5 classes.

## BANKPR1 (2026-11-14): safety guards, gear, Dismiss's guest flag
- **Gear (always unequipped, Sean 2026-11-14).** A bank file never carries items, so gear is never duplicated: with a move
  the unit's five equipped items go into the source save's item bag the way the Equip menu's remove does (0x14027bc80 ->
  `data_inventory_add_item` 0x1401c9ba0, then 0x1401c9b70 empties the slot); without a move the save keeps them. D5 has one
  item store (bag = warehouse): 2000 blocks of 0x258 at state+0x482FD8, u16 count at state+0x5A7F58. A block carries its
  innocents and Item World index and names no owner, so it is copied verbatim. If the bag cannot take every item the
  export is refused and nothing changes. Not checked: item.dat's "cannot remove" byte (+0x458); such an item is moved too.
- **No overwrite, no half move.** A bank file is created exclusively (a clash gets `-1`, `-2`, never replaces another unit,
  since serials repeat across saves); a partial file (disk full) is removed. When a move fails after the bank file was
  written and the save still holds the unit (put back from the backup, or never replaced), the bank file is removed, so the
  unit is never in both places.
- **Double import.** Import refuses when the save already holds this very unit (record equal outside serial, index, row,
  squad, group), e.g. a CLI copy-import run twice; `--allow-duplicate` overrides.
- **Stale page card.** The page passes the listed unit's serial; if that roster slot now holds another unit the export is
  refused.
- **DLC guest flag.** Dismiss (0x140652580) also clears the "recruited" game flag of a DLC character (exe table 0x140A0D960,
  class id < 1000 -> flag 18300..18353, read by the guest room 0x140142580). A move now does the same
  (`unitbank.clear_guest_flag`), and an import sets it (every DLC character in the army has it set in the four test saves).
- **Companion quarantine.** A move dropped the quarantine entries of the unit that slid into the removed slot (it read the
  serial after the removal) and kept the moved unit's; fixed. Quarantined ids (not in the current table) do not travel.
Tests: `tests/test_bankpr1.py` (failure injection: disk full on save/companion/bank file, backups byte-identical).
