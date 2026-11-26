# D4 Valvatorez comparison pilot

This local package is **partial**, built offline, and not gameplay accepted. It
creates a separate supported low-ID unique character while preserving vanilla
D5 Valvatorez 570. It is a usable D5ModKit input for the next controlled playtest,
not a faithful completed D4 character port.

`d5lib/d4unique.py` uses existing D5ModKit table writers, catalogue staging,
new-character finalizers and runtime save-row preservation. It adds no new
native behavior hook. An inserted low unique row still requires the kit's
existing runtime; offline compilation does not validate save/reload behavior.

## Content and fidelity

| Component | Status | Implementation |
|---|---|---|
| D4 Valvatorez 10 base stats and aptitudes | Partial overall; exact stored integers | D4 EN char.dat, canonical stat order; D5 progression remains |
| Movement, attack range, jump, throw, counters, crit, elemental resistances, gender | Adapted | D4 stored fields written through D5 schema; native equivalence unproven |
| Impaler Prince 10011 | Adapted | Existing D5 10571, learned at D4 level 1 |
| Bloody Hole 10012 | Adapted | Existing D5 10572, learned at D4 level 32 |
| Tyrant Flughude 10013 | Adapted | Existing D5 10573, learned at D4 level 80 |
| Bloody Battle 347 | Blocked | No innate Evility installed; no unrelated donor rule substituted |
| Physical Boost 8, Absorption 815, Casting Mastery 65, Dodge Mastery 66 | Partial | Accounted as D5 comparison references 4053, 6032, 1031, 1091; no new ownership or grant |
| Body, face, portraits, voices, weapon attachments | Adapted | Original D5 Valvatorez presentation and voice 570 |
| Optional D4 portrait 10010 | Partial, experimental | D4 ANM nodes converted through existing reader/writer; pixel payload roundtrip checked; D5 render/layout unaccepted |
| D4 weapon-learning thresholds | Partial | Preserved in source receipt; no unverified threshold conversion |
| Weapon mastery and weapon resistances | Adapted | D5 Valvatorez 570 donor values; D4 stores no mastery letters and no weapon resistances. The D4-FORTE1 forte rule raises forte weapons only when the donor is Warrior/Valkyrie, so this same-character pilot is unaffected (see [D4_IMPORT.md](D4_IMPORT.md)) |
| D5 Overload / donor extra skills | Removed from pilot | Does not add D5-only Overload or extra learned skills |
| Recruitment | Adapted, offline checked | One quest: clear native map 101, Dried Up Wasteland |

All reused skills retain D5 damage coefficients, targeting, conditions, event
scripts, normal/short/skip paths, sounds and effects. The tool checks literal
event/effect dependencies; dynamic selectors and every gameplay/presentation
property remain separate acceptance work. Existing same-character content is a
comparison foundation, not evidence of equal D4 behavior.

## Build

Use the project's existing Python environment. Supply the canonical installer's
existing original state, and every installed or candidate native-mod directory
whose allocations must be protected. `--mods-root` is repeatable. Every mod in
those roots, including disabled mods, participates in collision checks and
quest/help allocation. IDs are provisional local choices, not global leases.

```sh
PYTHONDONTWRITEBYTECODE=1 python tools/build_d4_unique.py \
  --d4-root '<D4 install>' --game-path '<D5 install>' \
  --original-state '<canonical D5ModKit state/games/game-id>' \
  --mods-root '<canonical D5ModKit/mods>' \
  --target-id 216 --output-path '<existing private output parent>/valvatorez'
```

The default portrait policy is `d5-comparison`. To build an explicitly
experimental D4 portrait variant, use a different new output path and
`--portrait-policy d4-converted`. Select one variant; they share their character
and mod identities. Rebuild with another low ID if collision checks reject 216.
IDs 1000 and above are prohibited; no high-ID capacity support is inferred.

The CLI permits writes only under the output parent, keeps caches there,
redirects compiler caches there, blocks unrelated subprocess/network use, and
never constructs an Installer. It reads original archive directories/full-file
backups and verifies their hashes after building. An output must be new and may
not overlap game files, source assets, backups, mods or the source repository.
Finalization is enabled by default. Any skipped native feature or failed
readback makes the build fail; `--no-finalize` is for inspection only.

Outputs:

- `native-mods/D4_Valvatorez_Comparison`: native D5ModKit mod.
- `staged-kit`: isolated catalogue selection/profile, without a game clone.
- `catalogue.json`: source identity and explicit missing mappings.
- `unique-receipt.json`: source data, mappings, dependency closure and limitations.
- `conflicts.json`: checked mods, patch hashes and resource reservations.
- `finalization.json`: logical output hashes, skipped-feature status and readbacks.
- `original-read-receipt.json`: originals read and verified unchanged.
- `finalized-logical`: diagnostic build output; not an alternate installer.

Run `python -m unittest tests.test_d4unique -v` from the source checkout for
synthetic tests. No test assets contain game data.

## Installation and restoration

Installation has not been performed. For a controlled playtest,
close other editors and use the existing canonical D5ModKit instance and its
backups. Import only the chosen native mod folder, enable it alongside its normal
kit dependencies in a dedicated profile, and have D5ModKit build/install it.
Do not copy `finalized-logical` directly over the game. Recheck collisions against
the then-current complete mod set before installation.

Preserve the pre-expansion configuration and a pre-expansion save through the
existing save/profile tools. Never load Save2. The one recruitment quest gives
the separate pilot unit; vanilla Valvatorez remains available as a comparison.

To restore, remove the pilot from the enabled selection and let the canonical
D5ModKit rebuild or use its existing restore mechanism. Retain installer backups.
Restoring game data does not remove a custom character saved in a roster: keep
the expansion enabled for such a save or restore the preserved pre-expansion
save. Disable/re-enable, recruitment, roster removal and save/reload behavior are
still native acceptance gates.

## Required gameplay acceptance

Check recruitment and both Valvatorez definitions first. Compare D4 and D5
damage/targeting, conditions, stacking, rounding and counter behavior separately
from sprite, portrait, voice, animation timing, weapon placement, effects, sound,
shortened/skipped animation and cleanup. Test save/reload and profile disable /
re-enable with preserved saves. Bloody Battle requires a verified D5 rule or a
new compatible implementation before this unique slice can be called complete.
