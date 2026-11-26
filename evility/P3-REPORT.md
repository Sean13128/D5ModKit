# P3 — evility parity driven by real content (offline, 2026-10-27)

Card P3 in `Research/ASSESSMENT-20261026/port-plan/FIRST-STEPS.md`. Branch `p3-evility`, worktree
`Local/Worktrees/p3-evility`, based on `p1-ownership` @`b88794e` (Kit 1.5.8 + engine work + ownership
manifest). Nothing was installed, launched, pushed or played; the live game, Save1/Save2 and
`Local/Installed D5ModKit` were not touched.

Evidence class: **offline only**. Four new evility passes are implemented in our `.d5el` runtime and proven by
Unicorn from the game's own patched CALL sites (normal + `--abi`), by the static stack audit, by the whole-kit
payload build/verify and by the Kit test suite. Expressibility of real D4/DD2 rows is a **text-level mapping
review validated against the runtime's own validator**, not gameplay.

Plain answer: four Overlord effects format 2 lacked (`power_percent`, `defense_power_percent`, `move`,
`magic_range`) now exist in our runtime and are proven offline. They close **4 of 306** D4 primary evilities
outright and **0 of 27** DD2 `needs-new-logic` evilities. The measured reason is not missing effect vocabulary
any more — it is that most real rows want **two magnitudes of different kinds on one evility id**, or a
condition we still lack. That is the next card, and this report says exactly which rows it would close.

## Prior art checked

- Overlord source (`Private/Overlord and Sorrow research/class-support/overlord-source/`), Cryswar, The
  Unlicense: `overlord/10_evility_runtime.c` (parser at 65-155, per-effect applicability 154-366, appliers
  `apply_custom_power_percent` 690, `apply_custom_defense_power` 705, `hook_defense_power` 726) and
  `overlord/12_evility_hooks.c` (`install_power_percent_hook` 481, `install_defense_power_hook` 942,
  `install_magic_range_hook` 1106, `install_prevent_ally_damage_hook` 896, `install_steal_on_kill_hook` 987,
  `install_sp_drain_hook` 1047, `install_permanent_revenge_hooks` 377, `install_block_overload_hook` 440).
  Its RVAs are the **same functions** in our pinned exe: `POWER_HOOK_RVA 0x1F6AA8` sits inside
  `damage_attack_bonus_rules` (0x1401F6300), `DEFENSE_POWER_HOOK_RVA 0x1F8700` *is*
  `damage_defence_bonus_rules`, `MAGIC_RANGE_HOOK_RVA 0x1EC5C0` *is* the range-bonus getter,
  `PREVENT_ALLY_DAMAGE_HOOK_RVA 0x1FE0D0` *is* `damage_nullify_predicate` (already wrapped by EX-06b's
  `nullify`). Design reused, mechanism not: Overlord writes absolute jumps into function entries and
  mid-function stubs; LANE-RULES requires CALL redirection at the game's own call sites, which is what this
  lane does. Credit to Cryswar for the effect vocabulary and the site map.
- `Research/ASSESSMENT-20261026/overlord/EVILITY-VOCAB.md` (24 types + aliases) and `port-plan/VOCAB-NOTES.md`
  (the missing-effect list this card works from).
- `Research/ASSESSMENT-20261026/p2-overlord-full/HOOKS.md` + `CONFIG.md` (128 sites, per-key defaults and
  clamps — the `min`/`max` default `-50..100` is the one behavioural difference this port documents).
- `Research/ASSESSMENT-20261026/PRIOR-ART-MAP.md` §2 (evility row: "make the D4/DD2 converters emit both
  formats; build only the missing vocabulary, once").
- Sorrow's `community/sorrow/ida-export-20261014/disgaea5_names.json` (`menus_env_move_range`,
  `cmdmenu_env_stat_row_base_range`) and `/Volumes/Data/Decomp/d5/functions/`
  (`1401f6300_damage_attack_bonus_rules.c`, `1401f8700_damage_defence_bonus_rules.c`,
  `140157d90_menus_env_move_range.c`, `1401ec5c0_FUN_1401ec5c0.c`, `1401c1940_damage_attacker_bonus.c`,
  `1401c17e0_damage_defender_bonus.c`, `1402d4560_move_range_for.c`).
- Our own runtime: `d5lib/evility.py` (format 2, EX-05b…06b), `d5lib/native/d5evil.inc.asm`,
  `evility/{EX05B,EX05C,EX05D,EX05E}-REPORT.md`, `evility/CATALOG.md`, `abi-review/{REPORT,FIX-REPORT}.md`,
  `evility/offline_proof_ex05e.py`, `evility/abi_engine_ex05c.py`.
- Content evidence: `Research/source-packs/dd2/COVERAGE-FULL.md` + `coverage.json` (27 needs-new-logic, each
  naming its covering Overlord effect) and `Subprojects/Engine-Extensions/d4-evility-map/`
  (`d4_evilities.json` 325 rows / 306 primary, `PRIORITIES.md`).

## 1. Ranking the missing effects by real demand

Measured from the data files, not from memory. D4 = the 306 primary rows in `d4_evilities.json`; DD2 = the 27
`needs-new-logic` rows in `coverage.json` (the `overlord` field of each names its covering effect).

| Overlord effect | D4 primary rows needing it | DD2 needs-new-logic rows naming it | Total | Implementable as CALL redirection? |
|---|---:|---:|---:|---|
| `move` (EFFECT_MOVE) | 6 `movement` + 1 `transport` | 0 | 7 | Yes — `menus_env_move_range` has 23 static `E8` sites |
| `magic_range` | 5 `range` + 1 `range-aura` | 0 | 6 | Yes — the range getter has 3 static sites |
| `power_percent` | 5 `attack-power-percent` | 1 (row 100) | 6 | Yes — `damage_attack_bonus_rules`, 1 site |
| `defense_power_percent` | 0 explicit | 3 (rows 100, 2090, 2111) | 3 | Yes — `damage_defence_bonus_rules`, 1 site |
| `element_resistance_percent` | 4 `resistance-aura` + 1 `resistance` | 0 | 5 | No clean single getter found; not attempted |
| `prevent_ally_damage` | 3 (e.g. 625, 806, 826) | 0 | 3 | Overlord patches `damage_nullify_predicate`'s entry; our `nullify` already wraps 4 of its sites, but not the ally-damage path. Not attempted |
| `steal_on_kill_percent` | 2 `steal-rule` | 0 | 2 | Possible (a `call` inside `damage_after_hit_evaluate`), needs the victim-eligibility predicate traced |
| `sp_drain_per_turn` | 1 `sp-drain` | 1 (row 630) | 2 | `regen` with negative SP already covers the arithmetic at the round edge |
| `block_overload` | 1 `command-restriction` | 0 | 1 | `cmdmenu_preds_p_15dbf0` is a whole function; needs the Overload command path traced |
| `permanent_revenge` | 0 | 0 | 0 | Two mid-function stubs in `turn_per_unit_end_round_upkeep`; no demand |

Top four by demand (**move, magic_range, power_percent, defense_power_percent**, 22 mentions) were all
implementable under our hook discipline, so those are what this lane ported. `element_resistance_percent` (5)
is the largest remaining gap and is *not* attempted: no single site returns a resistance to add to, so it needs
its own site survey before it can be ranked honestly as "portable".

## 2. What was ported

Four new families in table format 2, same section (`.d5el`), same condition evaluator, same discipline (E8 CALL
redirection at the game's own static call sites, fixed frames with 32-byte home space, unwind emitted by
`d5lib/exepatch.add_code_section`, new build tags that were not in use).

| family (mod JSON) | Overlord effect | game function | static sites | subject argument |
|---|---|---|---:|---|
| `power` | `power_percent` | `damage_attack_bonus_rules` 0x1401F6300 | 1 | `rcx` = attacker battle record → `[rcx+0x240]` unit record |
| `defense_power` | `defense_power_percent` | `damage_defence_bonus_rules` 0x1401F8700 | 1 | `rdx` is already the defender's unit record |
| `move` | `move` | `menus_env_move_range` 0x140157D90 | 23 | `rcx` = unit battle record |
| `range` | `magic_range` | range-bonus getter 0x1401EC5C0 | 3 | `rcx` = unit battle record |

Mask bits continue where EX-06b stopped (the mask word is u32): `power` 65536, `defense_power` 131072,
`move` 262144, `range` 524288; build tags `0xE70010..0xE70013`. Each wrapper calls the original in its own
frame, then adds the summed row values (`evil_sum_unit` → the existing `evil_dmg_sum`, so `per` scaling and
every condition kind work unchanged). Values are signed 16-bit like every other family.

Row shape:

```json
{"7302": {"family": "move", "effects": [{"value": 1, "per": "adjacent_ally"}]}}
```

Documented differences from Overlord, not hidden:

* **No per-row clamp.** Overlord clamps each entry's computed modifier to `[min, max]` (default `-50..100`).
  Format 2 has no per-row clamp, so the game's own downstream clamp applies instead (`damage_defender_bonus`
  clamps its total to `[-99, 2000]`; the attack total is clamped by its caller).
* **Unit-state conditions only.** These passes are handed no action context and no other side, so
  `attack_dir`, `target_count`, `element` and the other action-context conditions evaluate false on them by
  design. Overlord's own note for `defense_power_percent` says the same ("unit-state conditions only").
* **One additive family per row.** An additive family cannot be combined with another family (validated), and
  `range`/`move` values are added *after* the game's own clamp inside `menus_env_move_range`
  (so a `move` row can push past the vanilla 99-panel sentinel; that is the same behaviour Overlord's
  stat-side add produces, and is called out as a **native-verification item**, not a claim).
* 23 move-range call sites are redirected, so every AI/pathing query pays one wrapper call; with no rows in
  the table the wrapper returns the original value unchanged (proven by the `*-unlearned-*` cases).

Code: `d5lib/evility.py` (families, `ADD_FAMILIES`, validation, `WRAPPERS`, docstring), `d5lib/native/d5evil.inc.asm`
(`tramp_dpower`/`tramp_move`/`tramp_range`, `evil_sum_unit`, `wrap_power`/`wrap_dpower`/`wrap_move`/`wrap_range`),
`tests/test_evility.py` (3 new tests, 41 assertions of the new vocabulary).

## 3. Proofs (all offline, all reproducible)

| Layer | Command | Result |
|---|---|---|
| Behaviour, real call path | `D5_KIT=<wt> python evility/offline_proof_p3.py` | **126/126** checks (28 cases × their sites) |
| ABI site entry (RSP%16=0, continuation, home space, forwarded stack arg) | same, `--abi` | **126/126** |
| Static stack audit | `python evility/static_stack_ex05e.py` | **54 E8 sites, 83 call edges, 0 findings** (26 sites on the base, 28 added here) |
| Regression: existing families | `offline_proof_ex05c/ex05d/ex05e/ex06` (normal + `--abi`) | **141/141, 68/68, 88/88, 75/75** — unchanged |
| Kit suite | `pytest tests -q` | **425 passed, 39 failed, 1 skipped, 703 subtests** — the same 39 known `test_offlinepaths` env failures as the base (p1-ownership reported 422/39; the +3 passes are this lane's tests) |
| Payload build + verify | `integration/build_payload-158.py` then `verify_payload.py`, `D5_KIT=<wt>` | 11,828,224 B, sha256 `407b5fba…33166`, section overlap none, SizeOfImage covers last, 14/14 kit hook sites in-section, **4 problems — the known verifier mismatch for the four reference-only sections** (`recruit/colour .d5qr`, `unlock .d5ul`, `enemy items .d5ei`, `runtime .d5auto`), identical to LIVE3's finding, none of them evility |

The proof executes the *game's own patched CALL instruction* at every site (not the wrapper in isolation) and
runs wrapper → trampoline → stubbed original → extension → the exact `site+5` continuation; `--abi` also poisons
the home space, checks home clearance, confirms the fifth stack argument is forwarded to
`damage_attack_bonus_rules` unchanged, and asserts the callee-entry alignment. Positive, negative, boundary
(±signed 16-bit limit), stacking (two effects), `per`-scaled, conditional (holding and not), other-unit, and
"unlearned is unchanged" cases exist for every family.

Receipts: `evility/results/p3-behavior.json`, `evility/results/p3-abi.json`,
`evility/p3-evility-static-stack.json`.

## 4. Re-running the coverage with the new vocabulary

`evility/p3_reclassify.py` re-reads both content maps, records an explicit decision per candidate row, and
pushes the rows it believes are expressible through `d5lib.evility.table()` — so a "covered" verdict is a row
the runtime accepts, not prose. Receipt: `evility/results/p3-reclassify.json`.

**D4 (306 primary rows): 4 covered, 2 blocked on evidence, 12 rejected in the new families.**

| D4 | Evility | Row that now expresses it |
|---:|---|---|
| 229 | Evasive Maneuvers (+3 MV under 25 % HP) | `move` +3, condition `hp_below 25` |
| 842 | Adjacent Catapult (+1 MV per adjacent ally) | `move` +1, `per: adjacent_ally` |
| 48 | Enlarge (+1 magic range) | `range` +1 |
| 341 | Violent Courage (+3 % attack power per enemy on the map) | `power` +3, `per: map_enemy` |

Blocked on evidence (family covers it, the number does not): 41 Fist Range UP and 44 Bow Range UP need the
**equipped** weapon category id; `d5lib/weaponlevels.WEAPONS` is the mastery order, and assuming the item
category shares its 1-based numbering would be an inference, so they are not counted.

Rejected, with the reason recorded per row (12): 176 and 809 (MV *and* a stat change in one evility), 180
("SP at maximum" is not a condition kind), 464 (movement *type*, which is the existing `flight` predicate),
867 (transport), 413 and 407 (a second effect plus SP cost), 829 ("limitless" is a sentinel, not an amount),
862 (an aura around an additive pass), 337 and 692 (a per-panel *distance* measure), 344 (`target_count` needs
an action context the pass is not given). Plus the resistance family (5 rows: 114, 187, 214, 230, 896), which
needs a resistance accumulator that does not exist.

**DD2 (27 needs-new-logic): 0 move.**

The four DD2 rows that name one of the new passes each need something else as well, so no verdict changes:
100 Passiveness (power **+** defence power **+** unconditional counter in one evility), 2090 Stone Statue
(defence power while the unit *has not moved* — no such condition), 2111 Great Wall (defence power **but** all
attacks hit — no forced-hit rule), 630 T.O. Despair (regen **+** SP drain **+** destroying the Base Panel).
The rest of the 27 never named these passes: they need their own mechanics (first-hit-per-turn nullification,
reverse ailments, bomb conversion, deathblow chance, water-skill event accumulators, likeability, turn-parity
nullification) or a second magnitude on one id (430, 2012).

So: **4 D4 evilities move from "needs new family" to "expressible today"; none of DD2's 27 does.** The
demand ranking was right that move/range/power are the most-mentioned gaps, but vocabulary was not what was
holding those rows back.

## 5. What stays unsupported (explicit)

Effect vocabulary still absent, in the order the content needs it:

1. **`element_resistance_percent`** (D4 5 rows) — needs a resistance accumulator and a site survey.
2. **`steal_on_kill_percent`** (D4 2 rows).
3. **`prevent_ally_damage`** (D4 3 rows) — the ally-damage path of `damage_nullify_predicate`, which our
   `nullify` rows do not reach.
4. **`block_overload`** (D4 1 row), **`sp_drain_per_turn`** (partly covered by negative `regen`),
   **`permanent_revenge`** (no measured demand).
5. Everything format 2 and Overlord both lack: per-hit/per-turn state (280, 290, 3023), event accumulators
   (2181, DD2 Cold Charge), distance measures (337, 692), SP cost families (407, 413), likeability, reverse
   ailments, base-panel destruction, deathblow, forced hit, "has not moved", "SP at maximum",
   EXP/HL/mana rewards, attack/magic range *auras*.

Structural limitations, now the real bottleneck and the recommended next card:

- **One magnitude set per evility id.** Effects are shared by every family in a row, so one id cannot carry
  "MV +3 and ATK −30 %", "damage taken −20 % and ailment chance +30 %", or "ATK power +10 % and DEF power +10 %"
  with *different* numbers. D4 176/809/407, DD2 100/430/2012 are all blocked by this. Fix: tag each effect with
  the family it belongs to (the stat word's byte 3 is unused; legacy tables would read identically) — measured
  to unlock 6 rows immediately, and every mixed-family row thereafter.
- **One row per id** (`table()` is keyed by id, `evil_find` returns the first match), so an evility cannot be
  split across two rows either. The tagging fix above removes the need.
- **No per-row clamp** and **no action context on the additive passes** — documented in §2, both are native
  verification items rather than blockers.

## 6. What this does not prove

- Nothing about native behaviour. No install, no launch, no save. Every verdict is offline.
- The proof's original-game callees are deterministic stubs that return 0, so what is proven is *our*
  contribution added to a return value, plus the ABI/unwind contract — not the game's own arithmetic around it.
- `range` is the getter keyed on vanilla evilities 1033/3305 and consumed by the skill-targeting path; whether
  the *basic-attack* range path consults it is not established offline, which is why 41/44 are blocked rather
  than covered.
- `move` values are added after `menus_env_move_range`'s own clamp and its guest/class guard; a row can
  therefore exceed the vanilla 99-panel sentinel. That needs a live check before content ships it.
- D4 magnitudes come from the source text; D4's own stacking, rounding and ordering still need consumer
  validation (the D4 map says the same).

Live checks needed before any of this is content-accepted (one authorized run, one game user, PLAY guard):
grant a `move` row and a `range` row to one unit, read its move range and a skill's target cells; grant a
`power` row and a `defense_power` row and compare a damage figure against a vanilla control at the same seed;
confirm the panel sentinel and the guest/class guard still behave; save/reload.

## 7. Commits and files

- `2a75ed7` — the four passes, validation, asm, tests, proof.
- `aec76f8` — the re-classification tool and every receipt listed above.
- Files: `d5lib/evility.py`, `d5lib/native/d5evil.inc.asm`, `tests/test_evility.py`,
  `evility/offline_proof_p3.py`, `evility/p3_reclassify.py`, `evility/abi_engine_ex05c.py` (four fixture
  entries), `evility/results/p3-*.json`, `evility/p3-evility-static-stack.json`, `PROGRESS.md`.
- Nothing pushed. Untouched: the installed kit, the game folder, the saves, `Local/Installed D5ModKit`.
