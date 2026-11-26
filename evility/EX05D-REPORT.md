# EX-05d — runtime magnitudes and the next vocabulary gaps

2026-10-26. Branch `feature/evility-vocab2`, worktree `Local/Worktrees/engine-ext-vocab2`,
based on merged `4cca16b` (EX-05c). Offline work only: no install, no game launch, no
Steam/game-folder mutation, nothing pushed. Every claim below says which class of evidence
it rests on.

**Headline: 72 exact / 253 uncovered / 325 classified** (was 60 / 265), i.e. 12 more D4
evilities expressed exactly, from five new writer/native primitives. Format 2 is unchanged;
no new call site or wrapper was added.

## What was implemented

| Primitive | Shape | Evidence class |
|---|---|---|
| Counted magnitudes | `{"stat":"atk","value":20,"per":"adjacent_ally"}` — value x count | bytes-checked fields + emulated |
| `per` kinds | `adjacent_ally`, `adjacent_enemy`, `adjacent_any`, `map_ally`, `map_enemy`, `map_any` | emulated |
| `other_hp_below` / `other_hp_above` | the *other* participant's HP percent (target for `dealt`, attacker for `taken`) | bytes-checked fields + emulated |
| `element_any` | the attack carries element 1..4 | bytes-checked field + emulated |
| `target_count` / `target_count_min` | exactly / at least n entries in the action's target list | bytes-checked field + emulated |
| Conversion source `sp_current` | `{"stat":"atk","from":"sp_current","value":10}` | bytes-checked fields + emulated |

The count reuses the existing battle-unit walk (`evil_near`, 0x141BA33B0 / stride 4704,
active byte +0x2E8, carrier link +0x2EE, stat index < 0x28A, the game's hostile-team table,
cell = `trunc(world/12.0f)`, Manhattan distance). A new leaf `evil_scale` maps a scale kind
to (relation, radius) through a table in the section data and returns the count; it is the
only new code that executes, and it calls the same helpers the adjacency conditions call.

Encoding stays 8 bytes per effect: byte 2 of the stat word is the scale kind, so **byte 2 = 0
means a fixed value** and every pre-EX-05d table decodes exactly as before. `evil_apply` and
`evil_dmg_sum` mask the stat index to byte 0 and multiply by the count when byte 2 is set; the
scaled result is clamped to ±32767 (the same range a fixed effect word carries). The
conversion path reads 8-byte source 8 as the unit's current SP at roster+0x2CD0 instead of the
base vector at +0x2D18.

`evil_apply`'s frame and prologue were deliberately kept byte-identical
(`56 53 55 41 55 41 56 41 57 41 54 48 83 ec 30 89 fd`) because the pre-EX-05d proof
(`Subprojects/Engine-Extensions/evility/offline_proof.py`) pins that prologue as its applier
anchor. The effect counter lives in the second frame slot, and the unit stays in `rsi`
(callee-saved, preserved by every helper).

## D4 evilities that became exact

| D4 | Text | Row |
|---|---|---|
| 11 | Elemental damage +20% | `dealt` +20 with `element_any` |
| 19 | Damage +30% when target HP under 50% | `dealt` +30, `other_hp_below 50` |
| 20 | Damage +30% if enemy HP is max | `dealt` +30, `other_hp_above 100` |
| 31 | Damage taken -50% when receiving an elemental attack | `taken` +50 with `element_any` |
| 39 | Damage taken -50% if enemy HP under 50% | `taken` +50, `other_hp_below 50` |
| 40 | Damage taken -20% if enemy HP is max | `taken` +20, `other_hp_above 100` |
| 84 | 10% of current SP added to ATK when a sword is equipped | `conversion` atk←`sp_current` 10, `weapon 2` |
| 98 | 10% of current SP added to INT | `conversion` int←`sp_current` 10 |
| 109 | ATK +20% per adjacent ally unit | `stats` atk +20 `per adjacent_ally` |
| 341 | Attack power + enemies on map x 3% | `dealt` +3 `per map_enemy` |
| 344 | Attack power +30% when attacking a single target | `dealt` +30, `target_count 1` |
| 643 | Magic damage +50% when aimed at a single unit | `dealt` +50, `attack_magic`, `target_count 1` |

"Exact" means a reviewed expression of the D4 text in this writer/native contract. It is not
demonstrated native D4 equivalence: the multiplier is the count *this* extension computes on
D5's battle map, the stage is the same one fixed effects already use, and no battle has run.

## Why not regeneration

The card asked for regen/HP-SP event effects "if ABI-safe". They are not added, and the
reason is unchanged from EX-05b, restated with what this pass measured:

* the round-edge HP/SP application is `turn_t1_per_unit_hp_sp` (0x140551AC0, 2837 B) with
  `_alloca_probe`; a behavioural proof would have to model the round-end processor, not the
  extension. The EX-05d harness proves wrappers against *stubbed* originals, so a regen wrapper
  could only ever reach "site entry + our writes" — a weaker class of evidence than every other
  claim in this report, for a family whose write also has to refresh presentation state
  (`unit_set_hp_shadow`).
* That is a live-battle job. It stays designed, not built (`docs/EVILITIES.md`,
  "Regeneration (not implemented — design)").

## Evidence and limits

* Field offsets, the battle-unit table, the action-context counts and the HP/SP/base-stat
  layout are the ones EX-05/05b/05c established from the pinned executable
  (`sha256 49a7530b…b282ce`) and the local decompilation; nothing was re-derived this pass and
  no D4 code was newly examined.
* Behaviour is emulated: Unicorn runs the *installed* section on synthetic unit/battle/action
  records, with original-game callees as explicit volatile-clobbering stubs.
* "Attack power" is read as the damage-dealt percentage stage (`family_map`
  `attack-power-percent` → `dealt`). That is a mapping decision, recorded in the recipe notes.
* `target_count` is the D5 action record's own target-entry count; equating "single target" in
  D4 text with "one entry in the D5 target list" is the same inference `attack_dir` already
  relies on. Both are offline-provable claims about the D5 record, not about D4's code.
* Counts are live D5 map counts. Per-unit-type counts (male allies, Prinnies/Malice/cat/Spirit,
  Geo colours), same-species, evil-area/deployment, distance moved, per-turn event
  accumulators, `last_unit`, `one_on_one`, `combo`, `defending`, `thrown` and SP/HL rewards
  remain uncovered — they need predicates or state the extension does not track.
* `evidence:stat-set` (52 affected IDs, 3 single-gap) is untouched: a source that says "stats"
  without enumerating them still cannot choose eight-stat `all` silently. That needs D4
  consumer evidence, not new native code.
* Windows unwinding, native gameplay and D4→D5 numeric equivalence are all unverified here.

## Checks completed

| Check | Result |
|---|---|
| EX-05d suite, behavior (Unicorn) | **68/68** |
| EX-05d suite, `--abi` site entry | **68/68** |
| EX-05c suite regression, behavior | **141/141** |
| EX-05c suite regression, `--abi` | **141/141** |
| Legacy `base` proof | **10/10** (34/34 ABI) |
| Legacy `ex05` proof | **23/23** (34/34 ABI) |
| Legacy `ex05b` proof | **27/27** (34/34 ABI) |
| Shared static-stack audit (this worktree) | **14 sites, 48 call edges, 0 findings** |
| Kit suite `pytest tests -q` | **271 passed, 39 failed, 1 skipped, 690 subtests** — the 39 are the known environment failures (baseline on `4cca16b`: 268 passed / 39 failed) |
| Emitter suite | **34 tests OK** (2 new) |
| Emitter `--require-capacity` | Passed; 72 rows / 74 effects / 63 conditions, 440 rows spare |
| `--build-only` receipts | EX-05d 68 fixtures, EX-05c 141 fixtures |

Receipts: `evility/results/*.json`, `evility/engine-ext-vocab2-static-stack.json`.

Generated artifacts (in `Subprojects/Engine-Extensions/d4-evility-map/emit/`):
`d4_extension_rows.json` sha256 `bc655b7c5814be71fd2b442a0d4a390bc99e2e2a23d761e26599479a2dbf6658`,
`vocabulary.json` sha256 `f1bd51fa21cbd438d2f3835cd2f963cf64ec8bfc73327e4ff04a35396964544d`.

## Emitter changes (outside Git)

Only `vocabulary.json`, the mapping in `emit_d4_evilities.py`, its test file, and the two
regenerated outputs were touched — the surface the card allowed. Specifically:

* `reviewed_contract` gains the five condition kinds, the six `SCALES` names and
  `CONVERSION_SOURCES` (including `sp_current`).
* `family_map` gains `attack-power-percent` → `dealt`.
* 12 recipes plus 12 `reviewed_supported_conditions` entries, each bound to the source
  signature; recipes that encode a live count declare `runtime_magnitude`, and the emitter now
  refuses a dynamic source without one, a `per` effect without a declaration, a `per` the
  writer does not implement, and a conversion source the writer does not implement.
* `KIT` in `emit_d4_evilities.py` now points at `Local/Worktrees/engine-ext-vocab2` (it pointed
  at `engine-ext-capacity`). **Retarget it after the coordinating merge**, before the next run,
  or the artifact and its writer vocabulary will not match.
* `test_emit_d4_evilities.real_writer()` also loads the new pure helpers `_scale` and
  `_conversion_source` — without that the emitter's own writer check cannot evaluate `per`.

If another worker is editing `emit/` for EX-S1, these are the exact hunks to re-apply or
rebase: `writer_constants` (SCALES/CONVERSION_SOURCES), `extension_row` (per + source
validation), `build` (contract filtering, `runtime_magnitude` gate), `coverage` (three prose
paragraphs), the `pure` set in the test helper, and the two count/set pins in the tests.

## Reproduction

```sh
PY=/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python
KIT=/Volumes/Data/Projects/D5/Local/Worktrees/engine-ext-vocab2
export D5_KIT="$KIT"
(cd "$KIT" && "$PY" -m pytest tests -q)
"$PY" "$KIT/evility/static_stack_ex05d.py"
"$PY" "$KIT/evility/offline_proof_ex05d.py"      --json "$KIT/evility/results/ex05d-behavior.json"
"$PY" "$KIT/evility/offline_proof_ex05d.py" --abi --json "$KIT/evility/results/ex05d-abi.json"
"$PY" "$KIT/evility/offline_proof_ex05c.py"      --json "$KIT/evility/results/ex05c-regression.json"
"$PY" "$KIT/evility/offline_proof_ex05c.py" --abi --json "$KIT/evility/results/ex05c-abi-regression.json"
for suite in base ex05 ex05b; do
  "$PY" "$KIT/evility/offline_proof_ex05c.py" --legacy "$suite"
  "$PY" "$KIT/evility/offline_proof_ex05c.py" --legacy "$suite" --abi
done
cd /Volumes/Data/Projects/D5
PYTHONDONTWRITEBYTECODE=1 "$PY" Subprojects/Engine-Extensions/d4-evility-map/emit/emit_d4_evilities.py --require-capacity
PYTHONDONTWRITEBYTECODE=1 "$PY" -m unittest discover -s Subprojects/Engine-Extensions/d4-evility-map/emit
```

## Live checks this handoff still needs

1. **No-mod control** — no `patches/evilities/evilities.json`: no `.d5ev`/section, game unchanged.
2. **Vanilla control** — a unit with vanilla damage/reduction evilities shows the same numbers
   with and without the section.
3. **Counted magnitude** — D4 109 as a row on one unit: +20 ATK percentage points per adjacent
   ally, recomputed as allies step in and out; a unit that is not deployed gets 0.
4. **Map count** — D4 341: the damage bonus must move as hostile units are killed or deploy.
5. **Other-side HP** — D4 19/20 on the attacker side and 39/40 on the defender side; confirm the
   bonus follows the *other* unit's HP, and that HP exactly at the threshold is "not below".
6. **Element** — a fire skill and a non-elemental skill on the same unit (`element_any`).
7. **Target count** — a single-target skill and an area skill on the same unit (D4 344/643).
8. **Current SP** — D4 98: the INT gain must track current SP at recalc time (it is recomputed
   when the game recalculates, so a mid-battle SP change shows up at the next recalculation).
9. **Watch the forecast** — the damage forecast and the executed number should agree; if the
   count differs between forecast and execution that is a real finding, not a proof artefact.
