# Local D4 expansion package

This package groups two **partial** pilots: six Male Armor Knight ranks and a
separate Valvatorez. It is built and checked offline. It has not been installed
or accepted in native gameplay. Every other inventoried D4 item remains tracked
through the full inventory and its sparse progress ledger.

The pack uses existing D5ModKit catalogue selection, native mod handlers,
installation and restoration. It adds no second installer, game clone or
replacement native behavior system. The original D5 Valvatorez remains intact.

## Configuration and reproduction

`tools/build_d4_expansion.py` consumes independently built pilots, rechecks their
native source and logical output hashes, and selects one or both entries. It
does not extract game assets again. Omit `--entry` to select both; pass
`--entry armor-knight` or `--entry valvatorez` for one. These selections control
the isolated staged pack. The current-stack check always preserves unrelated
enabled mods, including an installed pilot if that entry is unselected.

```sh
PYTHONDONTWRITEBYTECODE=1 python tools/build_d4_expansion.py \
  --generic-build '<accepted Armor Knight build>' \
  --unique-build '<accepted Valvatorez build>' \
  --game-path '<D5 install>' --original-state '<canonical installer game state>' \
  --current-kit '<canonical D5ModKit>' \
  --inventory '<immutable D4 inventory.json>' \
  --effect-verification '<optional effect corpus-verification.json>' \
  --output-path '<existing private parent>/expansion'
```

Every output must be new. The tool refuses protected source/game/kit overlap and
keeps writes and compiler caches under the output parent. It snapshots all native
mod trees, including disabled allocations, and rechecks their hashes afterward.
It also rechecks active settings/load-order bytes and original installer backup
bytes. No live profile, save, setting or game file is written.

The actual table patches, graphic resources, derived colour/portrait keys,
six-rank unlock flags, quest progress slots, native requirements and explicit
event/effect allocations are checked before building. Original tables with
ambiguous explicitly patched duplicate IDs are refused. Existing overlaps among
unrelated baseline mods are recorded and preserved; new selected collisions
are rejected. These checks do not demonstrate native capacity or runtime fidelity.

The two-mod pack and the exact current enabled stack are finalized in independent
fresh processes, loading canonical handlers before feature imports. Any skipped
native feature or selected-row/dependency/readback failure fails the build. The
existing generic mod is replaced at its original position; the new unique is
appended. Counts come from the active profile, not the number of mod folders.

## Outputs

- `staged-kit/mods`: selected native children, grouped by the existing pack API.
- `selection.json`: per-entry configuration, exact prior order and proposed order.
- `preflight.json`: IDs/resources, unlock flags, aliases, quest slots and conflicts.
- `input-hashes.json`: native input fingerprints, including disabled allocations.
- `standalone` and `with-current-stack`: cold-build logical outputs, logs, hashes,
  original-backup receipts and selected-row readbacks.
- `rollback`: copies of the prior settings/load order and replaced native mods.
  No saves are included.
- `progress-ledger.json`, `target-bindings.json`, `coverage.json`: sparse,
  source-hash-bound progress over the immutable full inventory. Every unlisted
  item inherits its baseline status. Converted effects are separate local
  artifacts; they are not assigned D5 effect IDs or included in the install pack.

`built-offline` describes structural/native build checks, not rendered or played
acceptance. The package contains private game-derived assets and stays local.

## Fidelity and limitations

Armor Knight uses D4 stored stats, movement fields, prepared sprite art, palettes,
face/cut-in pictures and idle timing. Other timing/attachments, weapon mastery,
weapon resistances, voice and progression use D5. Legit Shield is a D5 lookalike;
Lift Catch is absent. Aegis and other imported Evilities use D5 donor conditions
and magnitudes. D4 front-facing Aegis and carry behavior are not reproduced.
Class mastery/XP/subclass integration remain known gaps despite visible rank UI.

Valvatorez uses D4 stored stats and learn levels with D5 body/face/portraits,
voice and attacks 10571–10573. Native damage, targeting, animation, effects and
audio retain D5 behavior. Bloody Battle is absent. Four D4 learnable Evilities
are comparison references without custom ownership/grants. Donor Overload and
extra learned skills are cleared. The optional D4 portrait variant is experimental
and must be selected instead of the comparison variant, never alongside it.

## Controlled installation and rollback

Automated interactive game control is unavailable; native acceptance is pending
the owner's manual playtest. The result remains staged. Use one editor and the existing canonical installer/backups. The project
development editor supports the reviewed per-colour class art APIs; an installed
kit needs equivalent reviewed support. Broadly replacing the installed kit is
unnecessary. Never copy logical finalization outputs directly into the game.

Before an actual transaction, retain the exact prior profile/order, the copied
old Armor Knight mod and a matching pre-transaction test Save1 snapshot through
the established profile/save tools. The current profile already contains custom
Armor Knight units. Do not load Save2, re-enable Steam Cloud or restore old Forge
units. The included rollback native files/settings are evidence and recovery
copies; they do not include or silently replace a save.

Also snapshot canonical installer state/index/backups, `mods/packs.json` and the
active profile metadata. Merge the expansion into existing group metadata; never
overwrite canonical `mods/packs.json` with the isolated staged file. The current
group `gamepack/source-pilot/d4` already contains Armor Knight: retain its ID,
metadata and members, append Valvatorez, and preserve all unrelated/disabled
groups. Read the merged group set back through the native pack API.

With the editor closed, stage the chosen native child folders under the canonical
kit, preserving their IDs. Update the existing Armor Knight child in place while
retaining its old folder copy; add the Valvatorez child. Preserve every unrelated
mod. Create a test profile from the captured exact order, replace the existing
generic at its same position and append Valvatorez as shown in `selection.json`.
Use D5ModKit to build/install that selection with the matching test Save1.

For rollback, restore the copied old generic native files and exact prior
26-mod order/group metadata and kit code if updated, restore the matching pre-transaction test Save1 snapshot, then
rebuild through the canonical installer. Use the actual captured order/count if
it has changed since this package was built. Restoring vanilla archives alone
does not make a save containing custom1350/216 units safe. Retain the canonical
original backups and the current configuration until rollback is verified.

## Native acceptance matrix

All rows below are pending unless explicitly marked as an existing gap. Record
game build, profile/order, save snapshot hash, equipment, level, stats and exact
animation settings for each case. Keep gameplay results separate from visuals.

| Area | Case and acceptance evidence |
|---|---|
| Smoke / identity | Load only the test Save1, open roster/status and confirm original D5 Valvatorez570 and pilot216 are separate; recruit216 through its recorded quest |
| Generic recruitment | All six ranks/colours appear and recruit; names, descriptions, rank chain and portraits match the selected D4 source |
| Generic progression | Class XP/mastery/subclass selection are known missing integration; record blocked until implemented, not a pass from visible stars |
| Static values / progression | Compare stored bases/aptitudes/movement/resistances independently from D5 level growth; exact integers do not establish equivalent progression |
| Skill gameplay | Compare each attack at matched source conditions: damage, range, area, height/facing, guarding, immunities, conditions, counters, stacking and integer rounding |
| Evility gameplay | Verify displayed donor names/values and actual donor behavior; Aegis/Bloody Battle/omitted mechanics remain adapted or blocked until native source rules are implemented |
| Normal presentation | Front/back sprite, portrait/status/list/icon/cut-in routes, voice language, weapon placement, animation timing, hit effects and sound |
| Short / skip presentation | Each skill under full, shortened and skipped animation; hit timing, audio cancellation, actor restoration, weapon/effect cleanup and subsequent action |
| Special state cleanup | Knockback/death/counter/carry-related actions where applicable; Lift Catch remains absent, so a lookalike cinematic is not an acceptance case |
| Persistence / rollback | Save/reload, exit/relaunch, preserved roster IDs, disable/re-enable with matching saves and exact rollback selection; record every failure separately |

The remaining technical decisions are concrete: implement D4 carry operations,
front-direction/ordered Aegis damage handling, Bloody Battle and source Evility
acquisition; resolve scene/helper/actor/resource semantics and multi-palette
effect receivers; complete class mastery integration; then accept gameplay and
presentation on the target platform. Offline texture pixels and valid script
syntax do not resolve those gates.
