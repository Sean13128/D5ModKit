# EX-05e — critical rate, round-edge regeneration, nullification, adjacency

2026-10-26. Branch `feature/evility-vocab3`, worktree `Local/Worktrees/engine-ext-vocab3`, based on
merged `e808a23` (integration: EX-06 skills). Offline work only: no install, no game launch, no
Steam/game-folder mutation, nothing pushed. Every claim below says which class of evidence it rests on.

**Headline: 84 exact / 241 uncovered / 325 classified** (was 72 / 253), i.e. 12 more D4 evilities
expressed exactly, from six new writer/native primitives. Format 2 is unchanged; two call sites and
two wrappers were added (17 sites, 12 wrappers). One family — `regen` — is offline-proven only at
wrapper level and needs a live battle; see "What is not proven".

## What was implemented

| Primitive | Shape | Evidence class |
|---|---|---|
| `crit_rate` family | `{"family":"crit_rate","effects":[{"value":20}]}` | bytes-checked call site + emulated |
| `regen` family | `{"family":"regen","effects":[{"stat":"hp","value":10}]}` — percent of maximum, negative drains | call site + emulated wrapper (original stubbed) |
| `damage_null` predicate | `{"family":"damage_null","conditions":[…]}` — incoming percent becomes 0 | emulated |
| `ailment_null` predicate | `{"family":"ailment_null"}` — the *target's* in/out ailment chance becomes 0 | emulated |
| `near_char` condition | `{"kind":"near_char","of":1,"radius":1,"id":650}` — adjacent unit with that character id | emulated |
| `other_adj` condition | `{"kind":"other_adj"}` — the actual target/attacker is on a neighbouring panel | emulated |
| damage-time auras | `["taken","aura"]`, `["dealt","aura"]`, `["hit","aura"]`, `["crit_rate","aura"]` | emulated |

Call sites (each verified byte for byte at build time, as before):

| Wrapper | Game function | Sites |
|---|---|---|
| `wrap_crit` (tag 0xE7000B) | `FUN_1401f60a0` (the crit-rate addition pass) | 0x1401C1E94 |
| `wrap_regen` (tag 0xE7000C) | `turn_t1_per_unit_hp_sp` 0x140551AC0 | 0x140554B9E, 0x1405FB5DF |

The crit site was read in the pinned exe's disassembly: at 0x1401C1E80-0x1401C1E94 the caller sets
`rcx` to a stack `int`, `rdx`/`r8` to the attacker's and defender's battle records, and passes the
action context and target index on the stack (the Lua decompiler shows three arguments there; the
disassembly shows five plus one). `wrap_crit` therefore forwards all six arguments, adds the row
percentages to the in/out value and keeps the native 0..100 clamp.

`wrap_regen` takes only the battle record, calls the original first with the unchanged argument, then
applies each row and calls `unit_set_hp_shadow(0x140151C50)` after an HP write, passing the record and
the new HP. That second call is the deliberate answer to the EX-05b/EX-05d objection: the bar shadow is
presentation state the round-edge processor owns, so the extension refreshes it instead of skipping it.
`wrap_regen` is the first wrapper that calls a game function the build does not redirect; the static
audit and the ABI proof both cover that call edge.

`evil_next`'s aura gate went from "potency/stats only" to a mask (`0x49B` = potency, stats, dealt,
taken, hit, crit_rate), so a damage-time aura row is reached by the recipient's own damage pass. Aura
rows are still excluded from the learned-id path, so a unit that merely *learned* an aura row gets
nothing from it — proven by `aura-recipient-does-not-provide-for-itself`.

## D4 evilities that became exact

| D4 | Text | Row |
|---|---|---|
| 189 | Magic damage to adjacent allies -50% | `["taken","aura"]` -50, `near_has ally 1`, `attack_magic` |
| 326 | Attacks from behind are always criticals | `crit_rate` +100, `attack_dir 2` |
| 350 | Crit chance +20% | `crit_rate` +20 |
| 368 | Nulls non-elemental special attacks if HP under 25% | `damage_null`, `attack_skill`, `element 0`, `hp_below 25` |
| 384 | Null status ailment | `ailment_null` |
| 421 | 10% of HP recovered at end of turn | `regen` hp +10 |
| 422 | 10% of SP recovered at end of turn | `regen` sp +10 |
| 429 | When HP under 25%, recovers fully at end of turn | `regen` hp +100, `hp_below 25` |
| 625 | Non-elemental damage to an adjacent ally -50% | `["taken","aura"]` -50, `near_has ally 1`, `element 0` |
| 830 | Damage dealt to adjacent unit +50% with a gun | `dealt` +50, `other_adj`, `weapon 5` |
| 845 | When next to her, Raspberyl's ATK +10% | `["stats","aura"]` atk +10, `near_has ally 1`, `char 650` |
| 846 | When next to Raspberyl, ATK +50% | `stats` atk +50, `near_char ally 650` |

"Exact" means a reviewed expression of the D4 text in this writer/native contract. It is not
demonstrated native D4 equivalence, and no battle has run.

## What is not proven

* `regen` is the only family whose *own* code cannot be fully exercised offline: the original
  `turn_t1_per_unit_hp_sp` is 2837 bytes with `_alloca_probe`, and the harness stubs it. What the
  suite proves is our wrapper's frame, alignment, clamping, effect ordering, the `unit_set_hp_shadow`
  call and the exact `call`-site entry/continuation. **Composition with the real processor is a live
  check**, including the ordering question below.
* D4's "at the end of turn" is implemented at D5's **round edge** — the stage that processor runs at.
  If D4 meant per-unit turn end, these rows tick less often than the source text implies. That is a
  mapping decision, not a proof.
* "Always critical" (326) is written as +100 percentage points against the native 0..100 clamp. If the
  crit roll can exceed the clamped value anywhere, "always" would need a hard set instead of an add.
* `near_char` names a D5 character id. 846/845 use **650** for Raspberyl, the id the Kit's own combo
  schema annotates (`d5lib/schemas/comb.json`: "rate % when partner is id 650 (Raspberyl)",
  `confidence: medium`). That is the weakest evidence in this pass; an id change invalidates both rows.
* 845 is read as *the servant buffing Raspberyl* (`char 650` as the aura recipient). 846 is the
  servant's own ATK. If 845 actually buffs its holder, the row is wrong in a way an offline proof
  cannot see.
* `other_adj` is Manhattan-1 between unit cells, like every other adjacency here: multi-panel
  footprints and path-based adjacency are still not modelled, and "adjacent" for a 2-panel unit is
  under-counted.
* Nullification stops at the percent stage: a nulled hit becomes 0 damage, it does not skip the
  action, and bombs, Geo chains and first-hit rules are untouched.
* Ailment immunity zeroes the chance at `damage_status_chance_rules`; ailment *removal*, damage
  immunity windows and command restrictions remain uncovered.
* Windows unwinding, native gameplay and D4→D5 numeric equivalence are all unverified here.

## Checks completed

| Check | Result |
|---|---|
| EX-05e suite, behavior (Unicorn) | **88/88** |
| EX-05e suite, `--abi` site entry | **88/88** |
| EX-05e `--build-only` | **88 fixtures built** |
| EX-05c suite regression, behavior | **141/141** |
| EX-05c suite regression, `--abi` | **141/141** |
| EX-05d suite regression, behavior | **68/68** |
| EX-05d suite regression, `--abi` | **68/68** |
| EX-06 suite, behavior / `--abi` | **26/26** / **26/26** |
| Legacy `base` proof | **10/10** (34/34 ABI) |
| Legacy `ex05` proof | **23/23** (34/34 ABI) |
| Legacy `ex05b` proof | **27/27** (34/34 ABI) |
| Mastery proof, behavior / `--abi` | **8/8** / **11/11** |
| Mastery static audit | 2 configurations, 0 findings |
| Shared static-stack audit (this worktree) | **17 sites, 65 call edges, 0 findings** |
| Kit suite `pytest tests -q` | **338 passed, 39 failed, 1 skipped, 700 subtests** — the 39 are the known environment failures (same count as the `e808a23` baseline) |
| Emitter suite | **34 tests OK** |
| Emitter `--require-capacity` | Passed; 84 rows / 84 effects / 77 conditions, 428 rows spare |

Receipts: `evility/results/*.json`, `evility/engine-ext-vocab3-static-stack.json`.

Generated artifacts (in `Subprojects/Engine-Extensions/d4-evility-map/emit/`):
`d4_extension_rows.json` sha256 `b1b4345c0a90f2c0fef26da5b346a65f55078e1cf816523dfe2cdd72ee9e4906`
(the artifact records the SHA-256 of the writer/doc inputs it was built against, so it changes when
`docs/EVILITIES.md` does),
`vocabulary.json` sha256 `33884496ca967c3b5051f4e29cd8eb8eb91cd314e595bcfff77ca163166c29b1`,
`COVERAGE.md` sha256 `71301817a85dd764081c66c2d9f20aa5540d352567e346d02859773342ae18bb`.

## Emitter changes (outside Git)

`vocabulary.json`, `emit_d4_evilities.py`, its test file and the three regenerated outputs:

* `reviewed_contract` gains the four family names and the two condition kinds.
* `family_map` gains `critical-rate`/`critical-rate-aura` → `crit_rate`, `regeneration` → `regen`,
  `damage-nullification` → `damage_null`, `damage-taken-aura` → `taken`.
* `writer_constants` now also reads `AURA_FAMILIES` and `PREDICATE_FAMILIES`, so an older writer fails
  closed instead of silently accepting an aura row it cannot run.
* `extension_row` learns: `damage_null` is a battle family (it is handed the action context), an aura
  may ride a damage family (the aura name is not a pass), a predicate family needs no effects, `regen`
  names hp or sp, `near_char` validates like `near_has`.
* `effect_count` counts a `regen` effect as one (it was under-counting by 3 and the capacity report and
  the writer disagreed).
* `KIT` now points at `Local/Worktrees/engine-ext-vocab3`. **Deviation from the card, deliberate:** the
  emitter's own test suite resolves the writer through `KIT`, so restoring it to `engine-ext-integration`
  would make the 84-row pins fail. Retarget it to whichever worktree holds the merged writer before the
  next emission; until then the committed artifact is the reviewed one.
* Three stale test pins were corrected because they did not describe the writer that was already on
  `e808a23`: the row tuple now has the EX-06 flags field, the writer's overflow message is "too many new
  rows", and the aura test no longer asserts that a damage-time aura is refused.

## Reproduction

```sh
PY=/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python
KIT=/Volumes/Data/Projects/D5/Local/Worktrees/engine-ext-vocab3
export D5_KIT="$KIT"
(cd "$KIT" && "$PY" -m pytest tests -q)
"$PY" "$KIT/evility/static_stack_ex05e.py"
"$PY" "$KIT/evility/offline_proof_ex05e.py"      --json "$KIT/evility/results/ex05e-behavior.json"
"$PY" "$KIT/evility/offline_proof_ex05e.py" --abi --json "$KIT/evility/results/ex05e-abi.json"
for suite in ex05c ex05d ex06; do
  "$PY" "$KIT/evility/offline_proof_$suite.py"      --json "$KIT/evility/results/$suite-behavior.json"
  "$PY" "$KIT/evility/offline_proof_$suite.py" --abi --json "$KIT/evility/results/$suite-abi.json"
done
for suite in base ex05 ex05b; do
  "$PY" "$KIT/evility/offline_proof_ex05c.py" --legacy "$suite"
  "$PY" "$KIT/evility/offline_proof_ex05c.py" --legacy "$suite" --abi
done
"$PY" "$KIT/mastery/proof_mastery.py"; "$PY" "$KIT/mastery/proof_mastery.py" --abi
cd /Volumes/Data/Projects/D5
PYTHONDONTWRITEBYTECODE=1 "$PY" Subprojects/Engine-Extensions/d4-evility-map/emit/emit_d4_evilities.py --require-capacity
PYTHONDONTWRITEBYTECODE=1 "$PY" -m unittest discover -s Subprojects/Engine-Extensions/d4-evility-map/emit
```

## Live checks this handoff still needs

1. **No-mod control** — no `patches/evilities/evilities.json`: no `.d5ev`/section, game unchanged.
2. **Vanilla control** — a unit with vanilla crit/regen-ish evilities shows the same numbers with and
   without the section.
3. **Crit rate (350)** — a row at +20 on one unit: the crit rate shown by the forecast rises by 20 and
   the observed crit frequency follows it; a unit without the row is unchanged.
4. **Crit saturation (326)** — attacks from behind always crit; attacks from the front/side do not;
   confirm the game's own facing and the action context's `attack_dir` agree in all three directions.
5. **Regen (421/422/429)** — the single most important live check. Confirm (a) the row ticks once per
   round per unit, (b) HP/SP stop at 0 and max, (c) the HP bar matches the number immediately (that is
   the `unit_set_hp_shadow` call), and (d) whether it ticks before or after the game's own Geo/status
   damage in the same processor. A row that heals a dead unit, or a bar that lags a tick, is a real
   finding.
6. **Damage null (368)** — a non-elemental skill on a unit under 25% HP does 0; a fire skill and a
   normal attack still damage. Watch the forecast: if it predicts damage and the hit does none, the
   nullification is running after the forecast stage.
7. **Ailment immunity (384)** — Poison/Sleep/Paralysis/Amnesia all fail to land on the row's owner; a
   unit without the row is unaffected.
8. **Aura (189/625)** — the reduction follows the *recipient's* adjacency to the provider: step the
   provider in and out; a non-magic attack (189) or an elemental one (625) is unchanged.
9. **Adjacency (830)** — the bonus appears only when the actual target is on a neighbouring panel and a
   gun is equipped; a different weapon or a target 2 panels away gives nothing.
10. **Named character (846/845)** — with Raspberyl adjacent the holder's ATK rises by 50 (846) and
    Raspberyl's own ATK rises by 10 (845); with any other unit adjacent nothing happens. This also
    validates the character id 650.
