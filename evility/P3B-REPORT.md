# P3b — several effects per evility id (offline, 2026-10-27)

Card P3b, branch `p3b-multieffect`, worktree `Local/Worktrees/p3b-multieffect`, based on `p3-evility` @`9e5be9a`
(coordinator-verified: `offline_proof_p3` 126/126 normal + `--abi`, static audit 54 sites / 0 findings). Nothing
was installed, launched, pushed or played; `Local/Installed D5ModKit`, the Steam folder and Save1/Save2 were
not touched.

Evidence class: **offline only**. The new capability is proven in Unicorn from the game's own patched CALL
sites (normal + `--abi`), by the static stack audit, by the whole-kit payload build/verify and by the Kit test
suite. The D4/DD2 verdicts are a **text-level mapping review validated against the runtime's own validator**,
not gameplay.

Plain answer: one evility id can now carry **several rows**, each with its own family, conditions and
magnitudes, added together — Overlord's own model, not the byte-3 family tag the P3 report proposed. Legacy
tables are byte-identical and behave exactly as before. It closes **2 more D4 primary evilities** (Chicken
Heart 176, Stone Wall 809 — 4 → **6 of 306**) and **2 of DD2's 27 `needs-new-logic` rows** (Passiveness 100,
Demon Experiments 430), which the P3 vocabulary work had moved by zero.

## Prior art checked

1. **Overlord source** (`Private/Overlord and Sorrow research/class-support/overlord-source/`), Cryswar, The
   Unlicense — design reused, credited:
   - `overlord/10_evility_runtime.c`: `load_config_file` (2-430) walks the INI's section names, takes the
     leading u32 of each name as the evility id (`overlord/02_util.c:129 parse_first_u32_w`), and *appends*
     one `CustomEvility` row per section (`:379`, capacity 512, later sources append — "a mod cannot overwrite
     the global file's rows"); `build_custom_evility_indexes` then groups rows by `effect_type`.
   - Every applier loops its type index and sums **all** rows whose id the unit carries:
     `apply_custom_power_percent` (`:690`), `apply_custom_defense_power` (`:705`, re-applies the game's own
     `[-100, 2000]` clamp), `apply_custom_steal_on_kill` (`:732`), `apply_custom_sp_drain` (`:753`),
     `unit_has_configured_effect` (`:574`). Each row keeps its own `value`/`value_source`, `condition`,
     `min`/`max` and `stack`.
   - **Shipped content proves the model is intended**: Overlord v3's `mods/Overlord/evilities.ini` opens with
     "Multiple sections may use the same evility ID; their effects are additive" and uses
     `[20500 Permanent Revenge]` + `[20500 Block Overload]`, `[6311 Ailment Infliction]` +
     `[6311 Damage vs Ailment]`, `[6314 …]`×2, `[20000 …]`×2, `[20013 …]`×2, `[20300 …]`×2 — 26 sections for
     20 distinct ids, 6 of them shared. The label suffix keeps the section *names* unique while the id parses
     the same, which is how it gets past the profile API's one-section-per-name rule.
2. **Prior-art map** `Research/ASSESSMENT-20261026/PRIOR-ART-MAP.md` §2 (evility row: "make the D4/DD2
   converters emit both formats; build only the missing vocabulary, once"), `p2-overlord-full/CONFIG.md` §2
   (the `custom_evilities.ini` schema: one section per id, per-key defaults and clamps),
   `overlord/EVILITY-VOCAB.md`, `port-plan/VOCAB-NOTES.md`.
3. **Our own runtime and its reports**: `d5lib/evility.py` (format 2, EX-05b…P3), `d5lib/native/d5evil.inc.asm`
   (`evil_find`, `evil_next`, `evil_apply`, `evil_growth`, `evil_dmg_sum`, `evil_pred`, `evil_regen`,
   `evil_conversion`), `evility/{EX05B,EX05C,EX05D,EX05E}-REPORT.md`, `evility/P3-REPORT.md` (its §5 finding:
   "one magnitude set per evility id … fix: tag each effect with the family it belongs to").
4. **Content evidence**: `Subprojects/Engine-Extensions/d4-evility-map/d4_evilities.json` (325 rows / 306
   primary) and `Research/source-packs/dd2/coverage.json` — whose own notes for 100/430/2012 already say "two
   or three format-2 rows for one evility id, which the table already supports". It did not: `table()` is keyed
   by id. That sentence is now true.
5. **Sorrow's research / the decomp: none new for this card.** The hook sites, function addresses and subject
   registers are P3's (already traced there); this card changes the table's row cardinality, not the hooks.

## 1. The choice: Overlord's row model, not a byte-3 family tag

P3's report proposed carrying the family in the stat word's unused byte 3. Overlord's model is better on three
counts, so this lane implemented that instead:

| | byte-3 family tag | several rows per id (chosen) |
|---|---|---|
| two magnitudes of different kinds on one id | yes | yes |
| **a different condition per effect** (needed by D4 176/809-style rows and any "X while Y" pair) | **no** — conditions live on the row | yes, per row |
| effect stat/`per` handling | one effect word has to be re-read with a family filter in six asm loops | untouched |
| legacy tables | decode the same, but every consumer gains a tag filter | decode the same **and** the row layout, format byte and validator rules are unchanged; a one-row-per-id table cannot tell the difference |
| matches existing content | no precedent in the world's only working D5 evility mod | exactly Overlord's `[<id> <label>]` sections |

Implementation cost was one real change: `evil_next` (the iterator every consumer uses) had a 32-bit cursor of
"learned-id position | aura-index position" and `evil_find` returned one row. Both now handle a *run*: the
search returns the first row of an id's run plus its length, and the cursor gained a third field (row position
inside the run), so the iterator emits the run one row per call. Because the consumers already evaluate each
returned row's conditions and add its effects, **every family got per-row conditions for free**.

## 2. What was built

Runtime (`d5lib/native/d5evil.inc.asm`):

* `evil_find(ecx = id)` → `rax` = first row of the id's run, `edx` = run length. Lower-bound binary search over
  the sorted evility rows, then a forward count (the run is contiguous because the table is id-sorted).
* `evil_next(rcx = cursor, edx = family, rsi = unit)` → rows come out in table order, one row per call, with
  the run emitted before the id advances. Cursor is now 64-bit: bits 0-15 learned-id position, 16-31
  aura-index position, 32-47 row position in the run. The aura/ordinary merge is unchanged; the aura-first
  path re-emits the same pending row (its run position is restored), and a row that does not name the asked
  family (or an aura row, which the aura index owns) is skipped within the run.
* The six consumers (`evil_apply`, `evil_growth`, `evil_dmg_sum`, `evil_pred`, `evil_regen`,
  `evil_conversion`) hold the cursor as a qword; their frames were already wide enough (frame-slot arithmetic
  in §6).

Mod data (`d5lib/evility.py`): an entry may be a row object (unchanged) or a **list of rows**:

```json
{"evilities": {"176": [{"family": "move", "effects": [{"value": 3}]},
                       {"family": "potency", "effects": [{"stat": "all", "value": -30}]}]}}
```

`table()` emits each row of the list, adjacent, in data order; `_row()` still validates **each row** with the
existing rules (so "one additive family per row", "conversion/regen alone", predicate rows carry no effects
all still hold — a mixed evility is several rows, not one row with a tag). `_merge()` keeps the pre-P3b
key-by-key override when two mods both write a *single* row for an id, and appends as soon as either side is a
list (Overlord's "later sources append"). The table is still format 2 (`"D5EV"` + `02`), the 32-byte row layout
is untouched, and `evil_row_count` now counts rows rather than ids.

## 3. Proofs (all offline, reproducible)

| Layer | Command | Result |
|---|---|---|
| P3b behaviour, real call path | `D5_KIT=<wt> python evility/offline_proof_p3b.py` | **111/111** checks (20 cases across the 7 families' sites) |
| P3b ABI site entry | same, `--abi` | **111/111** |
| Regression: every earlier family | `offline_proof_{ex05c,ex05d,ex05e,ex06,p3}` normal **and** `--abi` | **141/141, 68/68, 88/88, 75/75, 126/126** each — unchanged from the base |
| Static stack audit | `python evility/static_stack_ex05e.py` | **54 E8 sites, 83 call edges, 0 findings** (unchanged: no new hook sites) |
| Kit suite | `pytest tests -q` | **432 passed, 39 failed, 1 skipped, 703 subtests** — the same 39 known `test_offlinepaths` env failures as the base (425); +7 new passes are this lane's tests (31 → 38 in `tests/test_evility.py`) |
| Payload build + verify | `integration/build_payload-158.py` then `verify_payload-158.py` | 11,828,224 B, sha256 `f928f859…c49a`, section overlap none, all 14 kit hook sites in-section, **verify problems 0** |

What the P3b proof actually exercises, per case, from the game's own patched `call` at each site: (1) one id with
two different families (potency −30 and move +3) read through both passes; (2) the same family twice on one id
(10 + 20 on two stats); (3) the same family twice with **different conditions** (+3 under 25 % HP and +1
always → 4 when low, 1 when full); (4) two percentage families that used to share one magnitude (dealt +10,
taken −20 → pv 50 → 40); (5) two additive passes on one id (power 30, defence power 20); (6) the same stat
through the potency and aggregate passes (potency ATK +7, aggregate ATK +5); (7) two rows of one family
summing (5 + 6); (8) a legacy single-row entry unchanged (−30 → 20, 40 → 90); (9) a duplicate learned id still
applying once; (10) unlearned unchanged; (11) two **aura** rows on one id where only the row whose family was
asked for applies (dealt 10, not 30, with a provider in radius; nothing out of radius or without a provider;
the taken aura row still scales pv 50 → 60 through its own relation). `--abi` additionally poisons the home
space, checks home clearance, forwarded stack arguments and callee-entry alignment at every site.

## 4. Re-running the classification with multi-row entries

`evility/p3b_reclassify.py` (receipt `evility/results/p3b-reclassify.json`) re-reads both content maps, records
a decision per candidate row, and pushes every emitted entry through `ev.table()` — a "covered" verdict is an
entry the runtime accepts.

**D4 (306 primary rows): 6 covered, 2 blocked on evidence, 10 rejected in the new families.**

| D4 | Evility | Entry that now expresses it |
|---:|---|---|
| 229 | Evasive Maneuvers | `move` +3, condition `hp_below 25` |
| 842 | Adjacent Catapult | `move` +1, `per: adjacent_ally` |
| 48 | Enlarge | `range` +1 |
| 341 | Violent Courage | `power` +3, `per: map_enemy` |
| **176** | **Chicken Heart** ("MV increased by 3, stats decreased by 30%") | **two rows: `move` +3 and `potency` all −30** |
| **809** | **Stone Wall** ("Increase DEF/RES by 30%, MV −2") | **two rows: `potency` def +30 / res +30, and `move` −2** |

Honest caveats on the two new ones: 176 says "stats", so the potency row names all eight; if D4 means the six
combat stats that is a data edit, not a runtime limit. Neither D4 row's arithmetic (stacking, rounding, whether
D4 applies a clamp) has consumer validation.

**DD2 (27 `needs-new-logic`): 2 moved, 25 left.**

* **100 Passiveness** — "Increase Attack and Defense Power by 50 % and always counter when defending": a
  `power` row, a `defense_power` row and the `counter` predicate, three rows on id 100.
* **430 Demon Experiments** — "within 3 panels, allies deal 10 % more damage and enemies take 10 % more": a
  `dealt` aura row (`near_has` ally, radius 3) and a `taken` aura row (`near_has` enemy, radius 3).
* 2012 Corrupting Body is **not** counted, and this corrects the note in `coverage.json`: the taken half is a
  row (`taken` −30 with `element 0`), but "inflict deprave" is not a chance percentage — `status_chance` adds
  points to a status roll the attack already has, and no family *adds* a status to an attack.
* 2090 (has-not-moved), 2111 (forced hit), 630 (Base Panel destruction) still need conditions/rules, not rows.
  The other 22 names were reviewed in P3 and need their own mechanics.

So: **D4 4 → 6 exact, DD2 0 → 2 exact**, from one structural change.

## 5. What stays unsupported (explicit)

Structural, in the order the content needs it:

1. **Per-row clamps** — Overlord clamps each entry to `[min, max]`; format 2 has no per-row clamp, so the game's
   own downstream clamp applies (documented since P3, unchanged by multi-row).
2. **No action context on the additive passes** (`power`, `defense_power`, `move`, `range`), so
   `attack_dir`/`target_count`/`element` conditions evaluate false there by design.
3. Effect vocabulary still absent: `element_resistance_percent` (D4 5 rows), `steal_on_kill_percent` (2),
   `prevent_ally_damage` (3), `block_overload`, `sp_drain_per_turn`, `permanent_revenge`, SP-cost families
   (blocks D4 407/413), auras over the additive passes (D4 862).
4. Conditions still absent: "SP at maximum" (D4 180), did-not-move (DD2 2090), distance measures (D4 337, 692),
   forced hit (DD2 2111), adding a status to an attack (DD2 2012), base-panel destruction (DD2 630).

## 6. What this does not prove

- Nothing about native behaviour. No install, no launch, no save. Every verdict is offline.
- The original-game callees are deterministic stubs returning 0; the proof shows *our* contribution added to a
  return value plus the ABI/unwind contract, not the game's own arithmetic around it.
- The aura cases prove which row of a shared id applies on the recipient, not the game-side aura collection
  (EX-05e's proof, unchanged).
- 23 move-range call sites now walk a run before answering; with no rows the wrapper is unchanged (proven by the
  `*-unlearned-*` and `*-no-provider` cases), but the cost of a unit carrying a multi-row evility on every AI
  pathing query is a native-measurement item, not measured here.
- Cursor widening was checked against every consumer's frame slots (0x20/0x28/0x30/0x38/0x3c/0x40/0x44 in
  `evil_next`; qword slots in `evil_apply`/`evil_growth`/`evil_dmg_sum`/`evil_pred`/`evil_regen`/
  `evil_conversion`), and every stored cursor is now written as a whole qword — the bugs this found during the lane
  (dword initialisation and a dword read of the widened cursor, an off-by-one on the learned-id index, and the
  aura-first path clobbering the row pointer in rax) are exactly what the behaviour + `--abi` matrix caught.

Live checks needed before any of this is content-accepted (one authorized run, one game user, PLAY guard):
grant id 176 or 809 to a unit, confirm the move bonus *and* the stat change both apply, save/reload; grant DD2
100 and confirm both the damage figure and the counter still behave; confirm nothing regressed on a unit with a
single-row evility.

## 7. Commits and files

- `8e43302` — the runtime (asm), the mod-data/validator change, 7 tests, the P3b proof.
- Files: `d5lib/evility.py`, `d5lib/native/d5evil.inc.asm`, `tests/test_evility.py`,
  `evility/offline_proof_p3b.py`, `evility/p3b_reclassify.py`, `evility/results/p3b-{behavior,abi,reclassify}.json`,
  `evility/p3b-multieffect-static-stack.json`, `PROGRESS.md`.
- Nothing pushed. Untouched: the installed kit, the game folder, the saves, `Local/Installed D5ModKit`.
