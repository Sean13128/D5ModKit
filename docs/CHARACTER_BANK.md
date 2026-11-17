# Character Bank (beta)

Move one unit from one Disgaea 5 save to another. A save holds **128 characters in total** (army + reserve; the game's own
unit creation refuses beyond that), and the bank is the shelf for everything else: take a unit out of a save into a small
file, put it into any other save later.

**Status: beta.** The logic is covered by tests on synthetic saves and was run on copies of real saves. Saves written by the
bank were loaded in the game and the imported units played in the author's own testing (Steam, macOS through Wine); nothing
else was tried, and a native Windows run is untested. Work on copies, or let the kit back the save up (below).

## What a bank file is

A unit *is* its roster record: one 0x4750-byte block of the save (`savegame.ROSTER`, 128 of them). The name, class, level,
skills with levels, weapon mastery, the learned-evility bitmap, the innate evilities, the subclass id and the class-mastery
counters are all inside it. A bank file (`*.d5unit.json`) holds that record plus what the list shows (name, title, class,
level). Nothing else of the source save is needed to read it back.

On import the ids that mean something *outside* the record are re-addressed: the **serial** (a fresh one from the target save's
own counter, because the same number names a different unit in every save), the **roster index**, and the **char.dat row**
(for the target's class table). **Squad and group** membership are dropped (they name the unit by its old serial).

## Equipment

A bank file never carries items, so gear is never duplicated.

* Export with **move**: the unit's equipped items go into the source save's item bag the way the Equip menu's remove does
  (the game has one item store: bag and warehouse are the same). If the bag cannot take all of them the export is refused and
  nothing changes.
* Export without move: the source save keeps the items; the bank copy is unequipped.
* Import: the unit arrives with empty equipment slots.

Not checked: an item the game marks "cannot remove" is moved too.

## Command line

    tools/unit_bank.py export <save> <unit> <bank dir> [--move] [--live] (--game <game dir> | --vanilla-db <Database_0.dat>)
    tools/unit_bank.py import <bank file> <save> [--live] [--move] [--allow-duplicate] --db <installed Database_0.dat>
                              (--game <game dir> | --vanilla-db <Database_0.dat>)
    tools/unit_bank.py list   <bank dir>

`unit` is a roster slot or a name that exactly one unit has. `--vanilla-db` (or the `D5_VANILLA_DB` environment variable, or
`--game`) is the unmodded `Database_0.dat`: it decides who is a story character. Without it the tool refuses, because it could
not tell them apart. The same code runs behind the **Character Bank** page (Content > Character Bank), which shows both sides
as cards with face and stand pose and a plain sentence for every refusal.

`import --move` (always on in the page) moves the bank file into an `imported/` folder next to it once the save was written and
verified, so a unit cannot be imported twice; the file is never deleted or overwritten (a name clash gets `-1`, `-2`). The
list shows only the bank folder itself, so move a file back to import it again.

## Refusals (nothing is written)

| refusal | rule |
|---|---|
| class not installed | the unit's class id has no row in the installed char.dat (import) |
| save full | army + reserve is already 128 (import) |
| story-locked | the unit is a Disgaea 5 story character, see below (export and import) |
| reserve unit | the unit sits in the reserve, where the story hands characters over (export) |
| item bag full | a move needs room in the bag for the unit's gear (export with move) |
| already in the save | the save already holds this very unit, e.g. a copy import run twice; `--allow-duplicate` overrides (import) |
| damaged bank file | wrong kind or format, not exactly one unit, bad record length, or the record's class differs from the listed one (import) |
| stale page card | the roster slot now holds another unit than the card listed (export) |
| game running / no backup | see below |

### The story lock

The Recruiter's Dismiss list refuses a character id of 2460 or below 1000 ("unique characters cannot be dismissed")
unless the id is one of the 36 DLC characters in the game's own table (510-760 and 860-940 in steps of 10, and 800). The
bank applies the same rule to the unmodded char.dat rows, except that the four Dummy rows (Unique/DLC/Human/Monster Dummy)
are not locked, since a mod may fill them. A character a mod puts on a Dummy row below id 1000 therefore cannot be dismissed
in the Recruiter, but the bank (or `Save.remove_units`) can take it out.

## Real saves: backup first

The page opens any save, including one in the game's save folder. Before every move-export or import that writes a save in
the game's folder or in a kit profile's saves, the save and its `.d5learn.json` companion are copied with `savegame.backup` to
`<kit>/state/save_backups/<time>_bank/<player id>/SaveData/`, and the result sentence names that folder. The write is refused
when no backup can be made, and, for the game's own folder, while `disgaea5.exe` is running. After the write the save is read
back and checked (unique serials, indices in slot order, serial counter above every serial in use); on a problem the backup is
put back and the bank file stays in the bank. A save anywhere else is your own copy: no backup. The command line refuses a path in
the game's folder unless `--live` is given. Restoring a backup by hand means copying the files back.

## What travels, what does not

Travels inside the record as it is: name, title, level, class, skills with levels, weapon mastery, the learned-evility bitmap,
the innate evilities, the subclass id, class-mastery counters.

* **Learned-evility companion** (`<save>.d5learn.json`, `d5lib/learned.py`, only in kits that have it): evilities past the
  game's 1000-bit bitmap are kept there, keyed by serial and bound to the save's size and sha256. Export reads them into the
  bank file (`learned_extra`); import adds them under the new serial and re-binds the companion to the written save. A stale
  companion is ignored, and the import says that the evilities were not carried. A kit without `d5lib/learned.py` carries the
  record alone.
* **DLC characters' "recruited" flag**: a move clears it like Dismiss does, an import sets it again.
* **Not carried, nothing refuses it**: the NG+ base-cast table (64 serials; a serial it cannot find is skipped), and the
  unit's squad or group. Unverified: other places in a save that might name a unit.
* **Modded classes**: the class must exist in the target's char.dat (refused otherwise). A subclass the target lacks is only a
  warning ("needs its mod installed"), since only the main class is checked.

## Tests

`tests/test_bank_*.py` run on synthetic saves and need no game. Checks on your own save copy are opt-in: set
`D5_BANK_REAL_SAVE` (a save copy), `D5_INSTALLED_DB` and `D5_VANILLA_DB` (Database_0.dat files) for the real-save round trip.
Tests that need the optional companion module skip when the kit has none.
