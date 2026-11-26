# Evilities with behavior of their own

A new evility used to be able to *copy* a game evility's effect (`docs/CLASSES.md`, "Evility aliases": the game
id is added next to the new one when the unit's learned list is rebuilt). This page is about the next step: an
evility id with its **own** condition and numbers, handled by new code the Kit installs into the exe.

Backend: `d5lib/evility.py`, native code in `d5lib/native/d5evil.inc.asm`. Mod data:
`patches/evilities/evilities.json`.

## What it does now

Ten wrappers cover the compiled consumers for stats, damage, accuracy, movement and base-stat conversion. The
extension adds its own contribution to each, for ids it knows:

| family | function | what a row's `value` means |
|---|---|---|
| `potency` | `unit_stats_evil_potency` (0x1401E1B30) | percent added to the stat the unit's *equipment* gives: a sword with ATK 100 and potency ATK +30 gives +30 more ATK. The game's own clamp (10..300) applies |
| `stats` | `unit_stats_evil_status_effects` (0x1401B97D0) | percentage points added to the stat aggregate (the same place the game's percent evilities write), so +10 on ATK is +10 % ATK |
| `growth` | `unit_stats_evil_growth_bonus` (0x1401E9B50) | percentage points added to a stat's level-up growth, for the stat asked for |
| `dealt` | `damage_damage_multiplier_rules` (0x1401F8FD0) | percentage points added to the damage the unit *deals*: the caller composes `100 + return value`, so +30 is +30 % damage |
| `taken` | `damage_damage_reduction_rules` (0x1401FB2E0) | the in/out percent (the damage the unit *takes*, 100 = unchanged) is scaled by `(100 + value) %` |
| `flight` | `has_flight_like_evility` (0x140206160, 0x1402062F0 — two copies) | predicate: the game's own test for evility 124 / 1224 / 5000 (Heavy Armor, Heavy Stance, Can't Fool Me: "cannot be lifted") is true for the holder; the callers are `path_query_cannot_be_carried_by` (0x140154310) and `path_ranges_collect_targets` (0x1402DA750). No `effects` needed, and none of those evilities' stats come with it (DD2EVIL1: DD2 Heavy Stance 300 is exactly this row) |
| `hit` | `damage_hit_chance_rules` (0x1401F5410) | percentage points added to the in/out hit chance, kept inside 1..100 (the game clamps the same range first) |
| `evasion` | `damage_hit_chance_rules` (0x1401F5410), the `hit` wrapper | D4SIG5, the **defender's** side of the hit chance. Effect `"mode": "points"` is subtracted from the percent before the game's clamp to 1..100, `"mode": "after"` (DD2EVIL1) is subtracted after the game's own call and the attacker's `hit` rows, before the scale rows (kept at 1 or more) - the order of D5's own Rapid Movement 1060 and DD2's 0xFB0EC, which clamp first; `per` and `max` work on an evasion effect; the default `"scale"` multiplies the finished percent by `(100 - sum) / 100` (truncating, kept in 1..100); the action context and the attacker are available to the conditions. One number per effect, cannot share a row with another family |
| `status_chance` | `damage_status_chance_rules` (0x1401FF070) | percentage points added to the in/out ailment chance; pair it with the `status_class` condition to name the ailment |
| `aura` | the explicitly selected `potency` / `stats` pass (since PLUME1 also `power`, see below) | acts on the **recipient**, including recipients with no learned evilities: a required `near_has` condition names the provider; a `stats` aura does not also change equipment potency |
| `conversion` | `unit_stats_evil_overrides` (0x1401EEE30), recalc call 0x14021E79F | adds `value` percent of the specified **base** stat to a final maximum after original overrides and before the game's final clamps |
| `crit_rate` | `FUN_1401f60a0` (statistics: the crit-rate addition pass), call 0x1401C1E94 | percentage points added to the in/out critical percent; the native 0..100 clamp still applies |
| `regen` | `turn_t1_per_unit_hp_sp` (0x140551AC0), calls 0x140554B9E / 0x1405FB5DF | per round edge: `value` percent of the **maximum** HP or SP added (negative drains), clamped to 0..max, then the HP-bar shadow is refreshed |
| `damage_null` | `damage_damage_reduction_rules` (0x1401FB2E0) | predicate: the incoming in/out percent becomes 0, so the hit does no damage |
| `ailment_null` | `damage_status_chance_rules` (0x1401FF070) | predicate: the in/out ailment chance becomes 0 |
| `nullify` | `damage_nullify_predicate` (0x1401FE0D0), four sites | predicate: the hit is nullified when the row's conditions hold and the game's own answer was no. Defender subject, attacker as the other side, action context available |
| `counter` | `exec_counter_attack_allow` (0x1401ECE00), site 0x140547333 | predicate: the defender may counter when the row's conditions hold and the game said no. No action context, so unit-state conditions only |
| `crit_damage` | `damage_damage_reduction_rules` (0x1401FB2E0), inside the `taken` wrapper | percentage points of extra damage on a **critical** hit, for the **attacker's** rows (DRPGEVIL1b). D5's own Purgatory (1222) is a test in this function: when the action context's target entry is a critical (byte `X + tgt_i * 0x260 + 0x152A`) the value is multiplied by `(100 + v) / 100`. The family does the same, after the original and after the defender's `taken` rows; rows add up before the one multiplication. Attacker subject, defender as the other side, action context available. May be an aura |
| `rearm_first_damage` | `turn_per_unit_end_round_upkeep` (0x1401E5AF0), site 0x1405F8FFC (the round-edge wrapper `permanent_revenge` also uses) | predicate (EVILFX1): after the game's own round-edge upkeep, the unit's stat-record byte +0xDF9 is cleared. That byte is D5 First Impression's (6047) "already took damage this stage" flag (set by `damage_apply_damage`, read by `damage_nullify_predicate`; nothing else touches it). The row does nothing alone: give the same evility a class alias to **6047**, and the pair nullifies the first damage of every turn (D4 Tyrant Guard 667). Unit-state conditions only; combines with no other family |

Anything else — turn order, the command menu, Move/Jump amounts, attack and magic range — is **not**
covered yet; those are the other consumer families catalogued in
`Subprojects/Engine-Extensions/evility/CATALOG.md` (EX-05).

## A mod's evility

```json
{"evilities": {
  "7001": {"family": "potency",
           "effects": [{"stat": "atk", "value": 30}, {"stat": "def", "value": -10}]},
  "7002": {"family": ["potency", "growth"],
           "effects": [{"stat": "all", "value": 5}],
           "condition": {"kind": "has", "id": 121}},
  "7010": {"family": "dealt",
           "effects": [{"value": 30}],
           "condition": {"kind": "hp_below", "id": 50}},
  "7020": {"family": "dealt",
           "effects": [{"value": 20}],
           "conditions": [{"kind": "attack_skill"}, {"kind": "attack_phys"},
                          {"kind": "element", "id": 1}]},
  "7021": {"family": "dealt",
           "effects": [{"value": 15}],
           "conditions": [{"kind": "enemy_adj", "id": 1}, {"kind": "weapon", "id": 2}]},
  "7022": {"family": "hit", "effects": [{"value": 20}],
           "condition": {"kind": "attack_dir", "id": 0}},
  "7023": {"family": "status_chance", "effects": [{"value": 15}],
           "condition": {"kind": "status_class", "id": 3}},
  "7030": {"family": ["potency", "aura"],
           "effects": [{"stat": "atk", "value": 20}],
           "condition": {"kind": "near_has", "of": 1, "radius": 1, "id": 7030}},
  "7013": {"family": "flight"}}}
```

* `family`: `potency`, `stats`, `growth`, `dealt`, `taken`, `flight`, `hit`, `status_chance`, `aura`, `conversion`,
  `crit_rate`, `regen`, `damage_null`, `ailment_null`, `nullify`, `counter`, or a list of them. A row that lists two families applies to both.
  `aura` is listed next to the family it acts on (`["stats", "aura"]`, `["potency", "aura"]`, and since EX-05e also
  `["dealt", "aura"]`, `["taken", "aura"]`, `["hit", "aura"]`, `["crit_rate", "aura"]`) and must carry a `near_has`
  condition. Aura rows act on the **recipient**, so an aura that names a recipient identity adds an ordinary condition
  (`char`) next to the `near_has` that names the provider.
* `regen` effects name `hp` or `sp` and the value is a percentage of that pool's maximum (10 = 10 % of max, later
  clamped to 0..max). `crit_rate` effects carry one percentage per effect, like `hit`. `damage_null` and
  `ailment_null` are predicates: the row's presence with its conditions is the whole effect, so they take no
  `effects` and combine with no other family. `nullify` and `counter` are predicates too (defender subject; only
  `nullify` is handed the action context, so `counter` row conditions must come from unit state).
* `effects` for the stat families: `stat` is `hp`, `sp`, `atk`, `def`, `int`, `res`, `hit`, `spd` (or its index
  0-7, or `all`), `value` is added and limited to ±32767. An effect may instead carry `per` (below) to make
  the value a *counted* magnitude.
* `effects` for `dealt` / `taken` / `hit` / `status_chance`: one percentage per effect and **no** `stat` (a stat
  there is refused, not silently ignored). An effect without a `stat` belongs to the percentage side only; write
  `"stat": "all"` if a row also carries a stat family and should reach every stat.
* **Runtime magnitudes (EX-05d):** add `per` to an effect to multiply its `value` by a count the extension
  computes on the battle map:

| `per` | the multiplier |
|---|---|
| `adjacent_ally`, `adjacent_enemy`, `adjacent_any` | units of that relation on a 4-neighbour panel |
| `map_ally`, `map_enemy`, `map_any` | units of that relation deployed anywhere on the map |
| `defeated_enemy`, `defeated_any` | the battle's own defeated-unit counters (hostile teams / all six) |
| `squad` | active members of the unit's own squad (the game's squad helper 0x1401D3990) |
| `movement_cost` | D5's battle-record movement counter (+0x61C); movement cost, not proven panels |
| `map_monster`, `map_human` | deployed monsters / humans (class-kind byte +0x2E25) |
| `map_class`, `map_has` | deployed units of the class id / carrying the evility id in the row's `filter` (`classes: [...]` expands to one row per id) |
| `party_human`, `party_monster`, `party_male`, `party_female`, `party_weapon` | members of the unit's **own side** on the map of that kind, **the unit itself included** when it qualifies (DRPGEVIL1c; every other count leaves the subject out). `party_weapon` reads the row's `filter` = item category of an equipped weapon. Gender and human/monster come from the class-kind byte +0x2E25 |
| `map_squad` | deployed **allies** in the unit's own squad (+0x30A0, gate +0x30A1); a unit outside any squad counts 0. EVILFX1: D4's Evil Area count mapped onto squads (label such rows adapted) |

The subject is never part of its own count (D4 does the same: its stat aggregate FUN_1401ba0a0 skips the
holder's own battle record before every count, Meowyland 837 and Friends 840 included).

  ```json
  "7031": {"family": "stats", "effects": [{"stat": "atk", "value": 20, "per": "adjacent_ally"}]},
  "7032": {"family": "dealt", "effects": [{"value": 3, "per": "map_enemy"}]}
  ```
  7031 adds 20 ATK percentage points per adjacent ally; 7032 adds 3 % damage per deployed enemy. The count
  uses exactly the scan, panel distance and eligibility tests the adjacency conditions use, so a unit that is
  not on the map counts 0. `per` is refused on the `flight` and `conversion` families. A scaled result is
  clamped to ±32767, the same range a fixed effect word carries. Per-unit-type counts (male allies, one named
  roster type, Geo colours) and event accumulators are still not expressible.
* `flight`, `nullify` and `counter` take no effects at all — the row's presence (and its condition) is the
effect. `nullify` makes the game's damage-nullify predicate answer yes (the defender is the subject, the
attacker the other side, and the action context is available at the redirected sites); `counter` does the
same for `exec_counter_attack_allow` (defender subject, **no** action context, so it is not a skill
family). See `docs/SKILL_RULES.md` for the sites each one covers.
* `conversion` cannot combine with another family. An effect such as
  `{"stat":"hit", "from":"spd", "value":30}` adds 30% of base SPD to final HIT; `"from":"sp_current"`
  (EX-05d) adds a percentage of the unit's *current* SP instead, at the same post-override maxima stage.
  Both indices name one of the eight stats. The family reads the immutable roster base vector at +0x2D18
  and adds to maxima at +0x2CD8, with signed division by 100 (truncation toward zero). It changes neither
  the base source nor another conversion's source. Current SP and other units' stats remain unsupported.
* `condition` (one, as before) or `conditions` (a list): **every** condition of a row must hold. The kinds:

| kind | argument | holds when |
|---|---|---|
| `has` | `id` | another evility is learned as well |
| `char` | `id` | the unit is that character id (+0x2E04) |
| `count` | `id` = n | at least n evilities are learned |
| `hp_below`, `hp_above` | `id` = percent | current hp over max hp is below / at least that |
| `level` | `id` = n | level (+0x2DFC) is at least n |
| `target_class` | `id` = class id | the other unit's class id (its `char.dat` id, unit record +0x2E04) is that; 0 is legal. Before EX-06b this read the other battle record's +0x2F4, which is the unit's *slot* |
| `other_slot` | `id` = slot | the other side's battle slot (battle record +0x2F4) is that — the comparison `target_class` used to make |
| `ally_adj`, `enemy_adj` | `id` = n | at least n allies / enemies stand within one panel (4-neighbour) |
| `ally_map`, `enemy_map`, `unit_map` | `id` = n | at least n allies / enemies / any units are deployed, not counting this unit |
| `attack_normal`, `attack_skill` | — | the action is a normal attack / uses a skill (action context +0x27670) |
| `attack_phys`, `attack_magic` | — | the skill row's effect type is physical 2 / magic 3; a normal attack counts as physical |
| `element` | `id` = 0..4 | attack element: 0 none, 1 fire, 2 wind, 3 ice, 4 star (action context +0x276BC) |
| `weapon` | `id` = category | an equipped weapon has that item category (slot 0, else slot 1) |
| `target_status`, `self_status` | `id` = status index | the other side / this unit has that status active (index into the 77 status slots) |
| `turn_min` | `id` = n | the battle round counter (0x145574AA8) is at least n |
| `attack_dir` | `id` = 0/1/2 | the attacker stands in front / at the side / behind the target, as the action context already recorded it (target entry +36) |
| `rng` | `id` = percent | one game RNG draw(100) is below that percent |
| `status_class` | `id` = status index | the ailment being rolled is that one (status-chance family) |
| `near_has` | `of` 0 any / 1 ally / 2 enemy, `radius`, `id` | at least one unit of that relation within `radius` panels carries that evility (the provider test an aura needs) |
| `other_fly`, `self_fly` | — | the other side / this unit is a flyer (movement type 2) |
| `other_level_higher`, `other_level_lower` | — | the other side's level is higher / lower than this unit's |
| `other_human`, `other_monster`, `other_male`, `other_female` | — | the other side has that normalized native type; useful for attacker predicates on `taken` |
| `self_human`, `self_monster`, `self_male`, `self_female` | — | the subject has that normalized native type; on an aura the subject is its recipient |
| `other_hp_below`, `other_hp_above` | `id` = percent | the *other* side's current HP over max is below / at least that (for `taken`, that is the attacker; for `dealt`, the target) |
| `element_any` | — | the attack carries an element (1..4); false for a non-elemental attack |
| `target_count`, `target_count_min` | `id` = n | the action has exactly / at least n entries in its target list |
| `near_char` | `of` 0 any / 1 ally / 2 enemy, `radius`, `id` | at least one unit of that relation within `radius` panels has that character id (+0x2E04) |
| `other_adj` | — | the *other* participant (target for `dealt`, attacker for `taken`) stands on a neighbouring panel (Manhattan 1) |
| `party_min` | `count`, `of` (1 human, 2 monster, 3 male, 4 female, 5 weapon), `id` = item category for `of` 5 | at least `count` members of the unit's own side on the map are of that kind, the unit itself included (DRPGEVIL1c) |
| `self_potential` | `types` = list of potential types 1..6 (1 King, 2 Pawn, 3 Rook, 4 Bishop, 5 Knight, 6 Queen), or `id` = raw bitmask 1..63 | the unit is a Disgaea RPG class in the class registry (see below) whose potential type is one of `types` (DRPGPARTY1). A class outside the registry has no type and fails. On an aura row it tests the recipient |
| `party_weapons_distinct` | — | every unit of the unit's own side on the map (not carried) is in the class registry with a favourite weapon, and no two share one (DRPGPARTY1). One walk of the battle table, so write it after the cheap conditions. A side of 10 or more units, or one with an unregistered unit, is never distinct |
| `turn_max` | `id` = n | the battle round counter is at most n (the mirror of `turn_min`). The counter's first value in a battle is **not measured** (0 or 1) |
| `provider_weapon`, `provider_hp_above`, `provider_hp_below`, `provider_hp_at_or_below` | `id` = item category / percent (1..255) | **holder-side condition of an aura** (DRPGEVIL1b). Written directly after a `near_has`, it also tests that provider: it must hold a weapon of that category, or have hp at least / below / at or below that percent of its maximum. Every other condition of an aura row tests the recipient. One qualifier per `near_has`; anywhere else it is refused |

Type predicates read the normalized roster byte +0x2E25 (1/2 human male/female, 11/12 monster male/female),
including evility 4301's native gender swap. Unknown types fail closed. `target_status`, `self_status` and
`status_class` accept index 0 (Poison), as well as indices 1..76.

Which unit a condition looks at depends on the family: the unit itself for `potency`/`stats`/`growth`, the
**attacker** for `dealt`/`hit`/`status_chance`, the **defender** for `taken` (this mirrors how the game's own
evilities work: an attack bonus tests the attacker, a reduction tests the defender). Every `target_*`/`other_*`
kind and `attack_dir` look at the *other* side — the defender for `dealt`, the attacker for `taken` — and read
the fields the game's own target checks in those functions read. `hp_below`/`hp_above` use current hp (+0x2CC8)
over max hp (+0x2CD8) as a whole percent; `level` is the short at +0x2DFC.

The adjacency and map counts walk the game's own 256-entry battle-unit table (0x141BA33B0, stride 4704) with the
game's own "is this a unit on the map" tests (active byte +0x2E8, unit pointer +0x240, a stat record index below
0x28A, not carried at +0x2EE) and the same team table the game's AI uses (`model_team_is_hostile`, inlined as a
bit table). Panels are the game's own cell formula (`trunc(world / 12.0f)`, 0 for a negative coordinate) and the
distance is Manhattan; the game's own aura helpers use a path query instead, so a large unit's *footprint* is
not considered here (a 1-cell unit is exact). `near_has` without a radius is refused: a provider has to be next
to the recipient.

Conditions that need the action context (`attack_*`, `element`, `attack_dir`, and `status_class`) are false in
the three stat passes, which the game calls without one.

The evility itself still has to exist as data: give it an id, a name/description row and put it on a class's or
character's learned list the normal way (that is data the Kit already writes). The id must be a **new** one —
the extension does not change what a game evility does, and a row whose id is one the game already tests would
add on top of the game's own behavior.

Stat order is the game's own: an item's eight stats are HP, SP, ATK, DEF, INT, RES, HIT, SPD (`item.dat`
+8, +16 …), and the potency words scale exactly those, so index 2 is ATK. The status aggregate's own stat
slots are `agg[0..7]`, the same order. This mapping is read from the game's table layout and aggregate code,
not measured in battle yet.

## How it works

* Install appends one code section, `.d5el`, to the exe: a table of rows `{id, families, conditions, effects}`
  and a small applier, assembled by `d5lib/evility.py` with keystone (the same mechanism as the Overload hooks,
  `docs/OVERLOADS.md`). The table is **format 2** (`D5EV` + version byte): 32-byte rows, a separate 8-byte
  condition array (four u16: kind, a, b, c) and the effect array. Format 1 rows (one condition, 24 bytes) are
  not written any more, so a tool that reads an installed table has to look at the version byte.
* Every static call site of an extended function is redirected to a wrapper (`call` -> `call` to the section, so
  the wrapper sees the game function's own arguments and return address). A wrapper calls the original function
  first — its body runs untouched, in its own frame — and then adds the extension's contribution for the ids
  the unit has. Each wrapper starts with a build tag (`mov r11d, 0xE7000N`) so the installer can find it.
  Frames are fixed, nested calls have 16-byte alignment and 32 bytes of outgoing home space, and the Kit's
  `exepatch` builder emits checked x64 unwind records for the reachable `.d5el` routines.
* One shared condition evaluator (`evil_eval`) serves every family, so a new condition kind automatically
  applies to all of them. It walks the row's condition list, looks the unit's battle record up in the battle-unit
  table once (a unit that is not on the map has no adjacency/facing answers), and then tests each condition.
  Rows without conditions return immediately; only spatial predicates need the battle-record lookup.
* A row may also be keyed by a **skill** instead of an evility (row flag bit 0): it applies when the action
  uses that skill id, whatever any unit learned, and `evil_dmg_sum` reaches it through its own id-ordered
  index because `evil_next` can only enumerate ids that are in a learned list. Same table, same section,
  same conditions; mod data lives in `patches/skillrules/skillrules.json`. See `docs/SKILL_RULES.md`.
* Ordinary passes iterate at most 64 learned ids and binary-search the sorted extension rows (at most ten
  row probes per id at 512 rows). The stat passes also use a separate aura index. Unrelated installed rows
  are not linearly scanned on each damage call. Duplicate adjacent learned ids contribute once.
* The damage wrappers call the game functions **directly** rather than through a trampoline: those two take
  arguments on the stack, and a trampoline that moves `rsp` would move them. They copy the stack arguments into
  their own frame instead.
* The flight family covers two copies of the same game code (0x140206160 twice, 0x1402062F0 once); the wrapper
  list is per *code copy*, not per family. The game answers with its low byte (`char` return), so the wrapper
  normalises the answer before deciding.
* No ids in any mod's data means no section and no patch at all, and a vanilla id never matches a table row, so
  a unit without a new evility gets exactly the game's numbers. The offline proofs run the pinned original
  instructions in Unicorn and the *installed* wrappers side by side:
  `evility/offline_proof.py` (three stat passes, 10/10), `evility/offline_proof_ex05.py` (damage + flight + the
  stat passes after the shared evaluator, 23/23) and `evility/offline_proof_ex05b.py` (every new condition kind,
  the two chance families and an aura, 27/27). EX-05c and EX-05d add their own suites
  (`evility/offline_proof_ex05c.py`, `evility/offline_proof_ex05d.py`), which additionally enter the real
  patched `call` sites in `--abi` mode; both pass in behavior and ABI mode on the synthetic fixtures.
* The call sites are verified byte for byte at build time: on any other exe build, or if one of them stops being
  a `call` to that function, the install stops with an error rather than writing a wrong hook.

`rebuild_list` (0x140218C90) needs no hook of its own: a new id reaches a unit's list through the mod's data (the
learned lists, innate slots and equipment built-ins that function assembles), and "effect of" rows keep using the
existing alias hook. The list holds at most 64 ids.

## Limits

* **2,048 rows, 8,192 conditions and 16,384 effects**, every mod together (DRPGEVIL1c; 512 / 2,048 / 4,096
  before). Nothing in the format was sized for 512: rows are found by binary search, the aura index and the
  cursor fields are 16-bit positions, offsets are u32. What 512 bounded was cost. Every aura row of a family
  used to be evaluated on every pass, and one evaluation is a walk of the 256-entry battle table: about 2,900
  instructions per aura row per call, so 1,000 aura rows would have cost about 3 million instructions for a
  single damage call. Now the first `evil_next` call of a pass walks the battle table once and records every
  evility id a unit there has learned (`evil_presence`, one bit per id below 32768, 4 KiB in the section), and
  an aura row whose `near_has` names an id nobody has is skipped with a bit test. Measured
  (`evility/measure_scan_cost.py`, 20 units on the map, provider of one row present): 1,020 aura rows = 31,243
  instructions per call, 2,040 = 54,727; a table without aura rows is unchanged (1,114). The section grows by
  about 50 bytes per row (366 KiB at 2,048 rows). `evility/offline_proof_drpgevil1c.py` runs a full table.
* EX-05c retains format 2 and existing row/condition/effect layouts. Auxiliary counts and an aura index are
  emitted after the sentinel row. Conversion uses family bit 512 and packs destination/source in the effect
  stat word's low/next bytes; its isolated family keeps old stat consumers from interpreting that word.
* EX-05d puts a runtime scale kind in byte 2 of an effect's stat word (0 = a fixed value, so an older table
  decodes identically). One `per` effect costs one 256-entry battle-table scan, the same order as one adjacency
  condition; a row with several scaled effects costs one scan each. The scan is skipped entirely when the unit
  is not on the map.
* Values are added, not multiplied (except `taken`, which scales the percent), unless the effect carries `per`
  (EX-05d): then the value is multiplied by a live battle-map count. A row still cannot scale by a filtered
  count (male allies, a roster type, Geo colours), by a per-turn event accumulator, or by distance moved; those
  need predicates or event state the extension does not track. What is covered now, of that list's top condition
  tags: adjacency (48 ids), ally (31), attack type (22), weapon type (21), target type (20 class kinds; gender
  and monster/flyer typing are only partly expressible — `other_fly` is), element (15), turn (15), hp threshold
  (12), rng (12), ally/unit counts (8 + 8), target status (6), map presence (10). Still missing: `facing` as the
  game's own facing relation (only the action context's attack direction is exposed), deployment count, and
  deployment history. Human/monster/gender predicates are available as listed above.
* An aura is applied by the passes that are handed the recipient: the two stat passes (potency and the stat
  aggregate) and, since EX-05e, the damage-time passes (`dealt`, `taken`, `hit`, `crit_rate`). Nothing reaches
  `regen`, `status_chance`, `damage_null` or `ailment_null` as a recipient, and an aura cannot name `regen`.
* Statistics changed by the extension appear where the game recomputes them (menu, level up, class change); a
  unit already in battle keeps the numbers it computed on entry, as with the game's own potency changes.
* The base branch at c5e4864 was live-proven for the original stat hooks. EX-05c's new behavior is source work
  only: Kit/static checks and build-only proof validation are recorded in `evility/EX05C-REPORT.md`.
  Emulator execution belongs to the coordinator; no EX-05c installation or gameplay acceptance is claimed.
* EX-05d adds the `per` magnitudes, `other_hp_below/above`, `element_any`, `target_count`/
  `target_count_min` and the `sp_current` conversion source. Its offline suites pass in behavior **and**
  `--abi` site-entry mode here (68/68 each), with every original-game callee a synthetic stub; Windows
  unwinding and native gameplay are still unverified. `evility/EX05D-REPORT.md` records the evidence class
  of each claim.
* EX-05e adds `crit_rate`, `regen`, `damage_null`, `ailment_null`, the `near_char` and `other_adj`
  conditions and the damage-time aura stages. Two more `call` sites are redirected (17 in total) and the
  regen wrapper is the first that calls a *second* game function (`unit_set_hp_shadow`) itself. Its suite
  passes in behavior and `--abi` mode (88/88 each); the round-edge original is stubbed there, so only the
  wrapper's own frame, clamping and shadow call are proven offline. See `evility/EX05E-REPORT.md`.

## Regeneration (EX-05e, offline-proven only)

`turn_per_unit_end_round_upkeep` (0x1401E5AF0) is status bookkeeping, not regeneration. The round-edge HP/SP
application is `turn_t1_per_unit_hp_sp` (0x140551AC0), called once per unit with the **battle record** in `rcx`
from the player-side round-end processor (call 0x140554B9E) and from `TurnCtl::init` PASS B for the other side
(call 0x1405FB5DF). HP is the qword at roster+0x2CC8 (max +0x2CD8) and SP at +0x2CD0 (max +0x2CE0); every write in
the exe clamps to `<= max` and `>= 0` and then refreshes the HP-bar shadow with `unit_set_hp_shadow` (0x140151C50).

The `regen` family is a call-site wrapper on those two sites: the original runs first and untouched, then for each
row whose conditions hold the wrapper adds `value` percent of the maximum to the pool, clamps it the same way, and
calls `unit_set_hp_shadow(record, hp)` after an HP write so the bar cannot go stale. Effects are applied in row-id
order, HP before SP only in the order the effects are listed, and nothing else in the unit is touched.

D4's "at the end of turn" is read as D5's **round edge**, because that is the stage this processor runs at:
the row ticks once per round per unit, not once per unit turn.

Two limits are deliberate. The wrapper cannot be proven *behaviourally* offline: the game's own 2837-byte
round-edge body (with `_alloca_probe`) is stubbed in the Unicorn suite, so what is proven there is our wrapper's
own frame, clamping, shadow call and the exact `call`-site entry/continuation — not the composition with the real
processor. And the ordering against the game's own HP/SP changes in that processor is not established: a row that
heals when the game has already applied Geo or status damage heals from the value the game left, because the
original runs first.

## Disgaea RPG own evilities (DRPGEVIL1, offline-proven only)

Disgaea RPG has its own name for its passives (a play on "evility"); the JP client stores them in the master `leaderskill` (4,445 rows) and
links them from `character`: `m_leader_skill_id` (main) and `m_leader_skill_id_sub_1..3` (learned by N.E.), each with
an optional `additional_*` continuation row. The 146 imported bases have 4 evilities each (584), 902 effect rows.
`tools/build_drpg_evility_overlay.py` turns the private census (made outside the repo from the masters) into
`d5lib/importers/drpg-evility-overlay.json`; `d5lib/importers/drpg_evilities.py` applies it to a pack
(`apply`, `gate`), called by `_drpg_build.py` and by `tools/stage_drpg_evilities.py` (table-only restage).

Field meanings, decoded from the rows' own JP text (the il2cpp metadata is encrypted, so no enum names):

| field | values |
|---|---|
| `effect_type` | 1 stat percent, 2 enemy stat percent down, 3 damage dealt, 4 damage taken, 14 ailments nullified, 21 HP heal percent, 22 SP gain (points), 23 / 24 timed stat buff / enemy debuff, 49 / 50 timed dealt / taken buff, 90 invincible N hits; 17, 18, 74 action gauge |
| `effect_type_params` | for 1/2/23/24 the stats: 1 HP, 2 ATK, 3 DEF, 4 INT, 5 RES, 6 SPD, 7 CRT, 8 CRD. For 3/4/49/50 the damage kind: 1 all, 2 normal attack, 3 skill, 5 magic, 7 non-elemental, 8 elemental, 9 fire, 10 water, 11 wind, 12 star, 13 single-target, 14 all-target |
| `target_type` | 1 party, 2 party females, 3 party humanoid(1)/monster(2), 4 party by equipped weapon, 8 party except self, 9 self, 23 self while equipped, 11 all enemies, 12 enemy males, 13 enemy humanoid/monster, 17-20 by action-gauge order, 26 potential type, 28-30 highest/lowest stat unit, 33-36 by HP / buff state, 99 rewards |
| `timing_type` | 1 always (battle start for timed effects), 2 turn start, 3 turn end, 4 turn end after a kill, 5 wave start, 6 when attacked, 7 on own defeat, 11 party damaged, 12-15 party uses a fire/water/wind/star skill, 16 party critical |
| `trigger_*` | (1, 3, w) holder has weapon type w; (1, 15, p) HP at least p %; (1, 16, p) HP at most p %; (1, 18, p) HP below p %; (2, 21, kind, n) party has n humanoids/monsters; (6, 5, n) n party members alive |
| `limit_damage` | the other side: 1 male, 2 female, 3 humanoid, 4 monster, 6-13 by its weapon |
| weapon types | 1 sword, 2 fist, 3 spear, 4 bow, 5 gun, 6 axe, 7 staff, 8 monster physical, 9 monster magic. D5's `item.dat` category is 1 fist, 2 sword, then the same 3-9, which is what the `weapon` condition compares |

What is applied, and what waits (after DRPGEVIL1b): only self-scoped, always-on rows are applied (43 evilities on 38
packs). Party-wide and all-enemy rows are written as aura rows (holder row + `near_has` radius 30, with a
`provider_*` qualifier when the source says "while I hold ...") but stay off until decision D1 is taken in the
overlay's `decisions`; D2 and D3 gate a few more, and L1 (one live read of the round counter's first value) gates
the `turn_max` rows. A count of "the party" (`party_*`, `party_min`) is D1's reading too, so those rows wait for D1
even when the effect is self-scoped. Counts: A 43, C 1, behind a decision 284, B 161, X 95. Still not expressible:
buffs fired by an event, regeneration as an aura, buff-state conditions, single-unit selectors, SP cost.

Ids are 28000 + 4 x the base's position in `drpg-leases.json` + slot, **above every evility id in use**: the game
keeps learned evilities as one bit per Skill.dat row *position* for the first 1,000 rows (`d5lib/learned.py`), the
installed table has 951 rows, and a block that sorts below existing rows would move their bits in every save.
Such rows are innate only (`kind` 2, no shop rank, no mana cost): an innate evility never needs a bitmap bit (the
unit record holds its id as an i16 at `+0x2EEE`, `unit_stats_evil_rebuild_list` builds the active list from ids,
`damage_skill_dat` finds the row by id), so they may sit past position 999; `evility/probe_drpgevil1b_capacity.py`
runs those game functions on a 1,010-row table with the evility at position 1,005. Two hard limits follow from the
same code: an evility id a unit can hold is at most 32767 and never 9999 (the free-slot marker), and the evility
screen appends every row with `shop_rank >= 1` to a fixed 1,000-entry array without a bound check.
`d5lib.learned.budget` / `tools/check_skill_budget.py` gate all of it: fail on a **learnable** (`kind` 0) row past
the bitmap, on more than 1,000 shop rows and on an unholdable id; warn at 95 % of the bitmap.
Since DRPGEVIL1c the installer **refuses** such a table (`d5lib/learned.py` finalizer, before the exe is touched;
`D5_SKILL_BUDGET=warn` downgrades it for a deliberate test build).
Runtime budget: 49 rows applied now; every decision on needs 897 of the table's 2,048 rows.
Proof: `evility/offline_proof_drpgevil1.py` runs 13 overlay rows verbatim through the patched call sites.

## EVILFX2 vocabulary (2026-11-10, offline-proven only, no new hook site)

All of it is evaluator-only or lives inside an existing wrapper. Proof: `evility/offline_proof_evilfx2.py`
(374 checks through the patched call sites, normal and `--abi`; 46 of them are overlay rows verbatim).

| piece | meaning | fields / source of the rule |
|---|---|---|
| scale `party_capped` (21) | living members of the unit's side on the map, the unit included, capped at the row's `filter` | Disgaea RPG "the more living party members ... (max +20 %, up to 5 characters)"; rows carry max / 5 per member |
| scales `hp_pct` (22), `hp_lost_pct` (23) | **percent scales**: the effect adds `value * percent / 100` (truncated), percent = `hp * 100 / max` or 100 minus it | DRPG "the lower the HP, the higher ... (max +70 %)"; linear, as D5's own Power of Adversity (2175) and Super Guts (1015) count HP lost |
| conditions `self_buff` (56), `self_debuff` (57) | the unit is under a stat-up / stat-down status of stat `id` (2 atk, 3 def, 4 int, 5 res, 6 hit, 7 spd) | status slots 7..12 of the stat record: active byte `+0x4E9 + slot`, signed power `+0x536 + slot`, exactly what `unit_stats_evil_status_effects` (0x1401B97D0) adds to aggregate[slot - 5]. The skills that set them are magic.dat effect kinds 11..16 (Braveheart 1501 ... Slow 1606; `status_index` 0x1401D7B30 maps kind k to slot k - 4). Evility bonuses are not statuses |
| conditions `map_buff_min` (58), `map_debuff_min` (59) | at least `count` units of relation `of` on the map are under a buff / debuff of stat `id` | same fields, `evil_near` filter kind 10 |
| condition `enemy_map_max` (60) | at most `id` enemies on the map (0 allowed); false off the map | mirror of `enemy_map` |
| condition `other_weapon` (61) | the other side has an equipped weapon of item category `id` | the fields `weapon` reads, on the other unit |
| conditions `side_top` (62), `side_bottom` (63) | no ally on the map has a strictly higher / lower stat `id` than this unit (ties all qualify) | the six current stat qwords at unit `+0x2CE8` (ATK..SPD), `evil_near` filter kinds 11 / 12. As a recipient condition of an aura: "the ally / enemy with the highest ATK" |
| provider qualifier `provider_buff` (64) | the aura's holder is under a buff of stat `id` | written right after its `near_has`, like 50..53 |
| `regen` as an aura | `["regen", "aura"]`; an hp effect with `"base": "provider"` heals a percent of the **provider's** max HP (clamped at the recipient's max; a unit at 0 HP is not healed); sp effects stay a percent of the recipient's max | DRPG "party HP recovers 8 % of the holder's max HP". The provider is the unit the row's `near_has` matched last, so such a row may carry no other map-walking condition (the emitter refuses it) |
| one-ailment immunity | `ailment_null` + `status_class` now works: the wrapper passes the rolled status index to the predicate (it used to pass whatever the original call left in r9) | D5 ailment indices from magic.dat: Poison (kind 21) 0, Slumber 1, Stun 2, Blank Out / Amnesia 3, Charm (27) 6 |

Disgaea RPG census after EVILFX2 (D1, D2, D3 still off; L1 on): A 50, C 1, behind a decision 338, B 100, X 95.
Every decision on needs 1,071 of the 2,048 runtime rows. Still not expressible, by evilities: a buff fired by an
event 26 (eleven different events, at most 6 evilities each, so no single hook site reaches the 30 a new site
needs), SP cost 9, favourite-weapon counts 8, CRT / CRD buff states 8 (D5 has no such status), follow-up attacks 5,
"fewer enemies" scale 5 (the step formula is not stored).

### Save safety and the late bands (EVILFX2b)

Learned evilities are one bit per Skill.dat row position, so **no install may change the position of an installed
learnable row**. `d5lib.learned.moved(installed, staged)` lists such rows and `tools/check_skill_budget.py ...
--installed <installed mods>` refuses them. A new D4 / DD2 row that would sort before an installed learnable row
(highest installed: 26182) takes an id in a late band instead: D4 `27000 + the D4 evility id` (27000-27999, first
row 27844 Beryl's Servant 1, recorded under `late_ids` in `d4-evility-additions.json`), DD2 26300-26999 (26200-26299 continues the installed 24000 + id convention;
allocated per row). Installed rows keep their ids. Rows in 28000+ and the late bands are innate only.

## PLUME1: per-effect `max` and `["power", "aura"]` (2026-11-11, offline-proven only)

* **Effect `max`** (0..32767, integer): caps that one effect's contribution after any `per` scaling, before the effect
  is summed. Allowed on the percentage families (`dealt`, `taken`, `hit`, `status_chance`, `crit_rate`, `crit_damage`),
  the stack families (`steal_on_kill_percent`, `sp_drain_per_turn`) and the additive families (`power`, `defense_power`,
  `move`, `range`); refused elsewhere. A capped effect sets stat bit 24 and packs `signed16 value | unsigned16 max << 16`
  in its value word, so `value` must fit 16 bits there; an effect without `max` encodes exactly as before (the installed
  table's rows, conditions and effects are identical to 45c77f0: checked by emitting all 114 installed rows both ways).
  The cap is a native `min` in `evil_dmg_sum`, so a negative total is not raised by it.
* **`["power", "aura"]`:** attack power may now be an aura (the mask in `.i_auras` gains the `power` bit). It needs a
  `near_has` condition naming the provider; the recipient is the unit whose power the game asks for. It is the only
  additive family that may combine with `aura`; `power` + any other family is still refused. A holder that owns the row
  is not its own provider for an ally `near_has` (so Plume's own power is not raised by her own row).
* **Brave Battle Princess (DD2_Unique_570, row 26304, innate):** `{"family": ["power", "aura"], "effects": [{"value": 10,
  "per": "defeated_any", "max": 200}], "conditions": [{"kind": "near_has", "of": 1, "radius": 65535, "id": 26304}]}`.
  DD2 text is "+10% Attack Power of ally units per unit defeated (Max 200%)", values 10/200 read from `mskill.dat` by
  `dd2source.decode_evility`. **Approximation:** `defeated_any` sums the battle's six defeated counters (all teams); DD2's
  counter scope is unproved. The row text and pack metadata say so. Unproved natively: that D5's `power` result is a
  percent that the attack formula applies as +10% steps. Proofs: `evility/offline_proof_plume1.py` (408 checks normal
  and `--abi`, including a differential of 45c77f0 against this build on every earlier suite's fixtures).

## EVILFX3: innate links (2026-11-10, offline)

`tools/game_truth.py` found 51 installed packs whose char rows link no innate evility. What the importers do now:

- **Condition `not_moved` (65):** the unit's panels-moved counter (battle record `+0x61C`) is 0. It is the counter D5's
  own Assault Attack (1020, `damage_damage_multiplier_rules`) and Sonic Charge (105) multiply by and that
  `carry_throw_unit_idle` (0x140157D00) tests for Cool and Calm (62). The existing scale `movement_cost` reads the same
  word, so it is D5's own "panels moved". Proof: `evility/offline_proof_evilfx3.py` (44 checks, both modes).
- **D4 classes** have one innate for all six ranks (D4 char.dat `+0x1B4`). `d4-evility-additions.json` links: Masked
  Hero 27690 Speedy Move, Android 27121 One Man Army (alias D5 6059 Belated Hero, same 100), Prism Ranger 8840 Friends
  (the row is now owned by the class pack; Prism Red references it), Mystic Beast 27692 Accel Element, Dragon 27663
  Rising Dragon (alias D5 2065, adapted), Rifle Demon 27693 Invincible Ruler.
- **DD2 (PLUME1 added 570 Brave Battle Princess 26304, see above):** `dd2-innate-evilities.json` (tool `tools/build_dd2_innates.py`, step `importers/_dd2_innates.py` after the
  reviewed-abilities layer): Barbara 10100 (link only), Evil Dragon 26200 Wind Dominance (alias 4015), Death 26300 Soul
  Reaper (alias 1143, adapted), Living Armor 26301 Patience (alias 2065, adapted), Gargoyle 26302 Stone Statue (DEF
  +100% while `not_moved`), Mao 26303 Demon Experiments (two aura rows, radius 3). DD2EVIL1 (2026-11-13): Pringer Z 24300 Heavy Stance is a kit `flight` row (exact; no stats, the earlier alias to D5 1224 is dropped by `drop_alias`) and Masked Hero 25210 Rapid Movement is an `evasion` row `{value 2, per movement_cost, max 64, mode after}` (exact rule; DD2's own function 0xFB0EC clamps to 1..100, then subtracts min(64, 2 x panels moved); the 64 is a code constant, the text has no maximum). Proof `evility/offline_proof_dd2evil1.py`. The file also lists the 7 packs whose
  innate needs a new effect; nothing is built for those.
  **DD2 `mskill.dat` row format (EVILNEW1/2):** 0x08 id u16 BE, 0x0C value u16 BE (first `%d`), **0x0E value2 u8 (second
  `%d`, nearly always the stated maximum: Plume 570 = 10/200, Adell 400 = 5/100, Living Armor 2130 = 10/200)**, name from
  0x0F, description from 0x5F. `dd2source.decode_evility` exposes it as `value2`. An earlier note that the DD2 maximum "is
  not stored" was a reader omission. Census: 227 rows, 29 two-placeholder descriptions, all with a nonzero value2; a table
  inference from bytes and text, not a native formatter run.
- **D1C:** the 14 folders outside the roster get donors in `d1c-donor-evilities.json` (`scope` marks them).
- **No source innate:** `sourcemaps/d4.json` `uniques.<id>.no_source_innate` (Toro 240, Kuro 250, with the evidence);
  the verifier reports N/A for them.
- **Used-id gate:** a folder present in several roots is one mod and the copy in the last root stands for it, so a row
  can move between two staged packs.
- `tools/game_truth.py --staged <mods dir> ...` checks a simulated install (folder mode). Only checks that read rows
  from the folders are meaningful there; `status: innate evility` is.

## D4SIG1: signature innates from existing pieces (2026-11-11, offline)

Lane D4SIG1 went through the 24 installed D4 entries whose signature evility was not done (9 missing, 15 partial) and
built every one the existing runtime carries; no native code changed. Five rows (late band `27000 + D4 evility id`,
innate only, overlay `d4-evility-additions.json` via `tools/evilgap1_rows.py`, staged by `tools/stage_d4sig1.py`):

| pack | D4 innate | row | how it is carried | label |
|---|---|---|---|---|
| D4_Class_2120 Death (six ranks) and D4_Unique_170 Hugo | 691 Mind Killer, "Inflict 50% of damage to SP during an attack" | 27691 | alias to D5 Habitual Licker 3011, "25% of damage inflicted by an attack is also inflicted to SP". The native code (`FUN_1401ada40`, the `0xbc3` branch) reads the percent from the donor's own Skill row (+0x38), so the alias gives 25, not 50. Hugo references the class's row (`requires`) and keeps Death Magic 8873 in his second slot | same effect, half the number |
| D4_Unique_340 Gig | 851 Jet Black Sword, "During magichange or fusion, Equipment Aptitude increases 50%" | 27851 | alias to D5 Demon Researcher 1185, "Increase stats of the Magichange weapons by 15%": same gate (only while a Magichange weapon is equipped), donor number 15 | smaller number, Magichange weapon only, no D4 giant fusion |
| D4_Unique_490 Nagi | 892 Everyone's Mechanic, "Increase stats of ally weapons by 10%" | 27892 | since D4SIG4 `["weapon_percent", "aura"]`, one number 10, `near_has` ally radius 65535 on its own id (map-wide, Nagi himself not raised); `wrap_equip` scales the game's own `unit_stats_equip_stat` result for a weapon-category slot (see the D4SIG4 section) | exact text and number; one provider counts once (Nagi is unique); stacks multiplicatively with D5's own weapon-percent evility 6035 |
| D4_Unique_460 Pirohiko | 881 Unlosing Mode, "Stats increased by 50% when activated. (Lasts 3 turns)" | 27881 | `stats` all +50 with `turn_max 3` | automatic for the first 3 or 4 rounds (the counter's first value is not measured) instead of a once-per-stage menu command |

Proof for the kit row 27881 (the Nagi row moved to D4SIG4): `evility/offline_proof_d4sig1.py`, 17 checks through the real patched call sites,
normal and `--abi`, rows read verbatim from the overlay. The two alias rows run D5's own code, so nothing of the kit's
executes for them. Tests: `tests/test_d4sig1.py`.

What the existing vocabulary cannot carry (nothing built; each needs a new capability, see
`Subprojects/Engine-Extensions/D4SIG1-REPORT.md`): Battle Suit Self-Destruct (a self-destruct action), Death Saber
Vanishing Cat (a target facing write), Demon Beast Stone Statue (a per-unit consecutive unmoved-turn counter), Medic
Base Hospital (regen for undeployed roster units; built by D4SIG10, below), Necromancer Necromancy and Nemo Physical Malice (temporary battle
actors), Roc Miasma of Silence (a special-skill use block), Psylos Geo Energy (a distinct Geo colour count), Ash Eccarlate
(a Magichange remaining-turn condition; built by EVILCAP1, below).

## EVILCAP1: ally/enemy class counts, SP damage percent, Magichange conditions (2026-11-11, offline-proven only)

Three small runtime additions, each in its own commit so any one can be dropped. All three change the `.d5el` code, so
the next install rebuilds the runtime section; rows that do not use them behave exactly as before (differential below).

* **Scales `map_class_ally` (24) and `map_class_enemy` (25).** `map_class` (13) with a relation: deployed units whose
  class/character id (+0x2E04) is the row's `filter` (or `classes: [...]`) on the subject's own team / on a team the
  hostile-team table marks. Same walk and "on the map" rule as `map_class`; the subject is never counted; 0 off the map.
* **Family `sp_damage_percent`** (mask bit 28, one number per effect, `per` and `max` allowed). D5's Habitual Licker
  (3011, "25% of damage inflicted by an attack is also inflicted to SP") is a branch of `FUN_1401ADA40` (called from
  `FUN_1401B1BA0` after each hit's damage): when the attacker carries 3011 it looks up 3011's Skill row
  (`damage_skill_dat`, call 0x1401ADDF0), takes `floor(damage * row+0x38 / 100)` and applies it to the target's SP with
  the game's own apply-damage call. The one call at 0x1401ADDF0 is redirected to `wrap_spdmg`: it runs the game's
  lookup, then, if the attacker's `sp_damage_percent` rows (conditions see the attacker as subject, the target as the
  other side, and the action context) sum to more than 0, returns a 64-byte row in the section whose +0x38 is that sum.
  Otherwise the game's row is returned unchanged. The branch is only reached while the attacker carries 3011, so a row
  of this family needs its id aliased to 3011 (class `evility_alias` or `aliases.json`). Several rows add up; the
  game applies the percent as given (no 100 cap). The game's Mind Break (2055) branch is not touched.
  ```json
  "27691": {"family": "sp_damage_percent", "effects": [{"value": 50}]}      // + alias 27691 -> 3011
  ```
* **Conditions `magichanged` (66), `magichange_host` (67), `magichange_turns` (68, `id` 1..255).** D5's own Magichange
  state, in the unit's stat record SR = 0x141067DC8 + (unit +0x4348) * 0xE98 (no record: false). The Magichange equip
  `FUN_140605E30(monster, host, slot)` writes the monster's uid to SR(host)+0x4B8+0x10*slot (a second, dual participant
  at +0x4C0+0x10*slot), the slot's remaining turns to SR(host)+0x4E0+slot (3, or 2 for the dual branch, plus 4505's
  value) and 1 to SR(monster)+0x4E2; `FUN_14015F030` clears them; `turn_h13` (0x1406098C0) ends the Magichange when a
  slot's byte reads 1 and decrements it otherwise, so 1 is the last turn. `magichanged`: SR+0x4E2 != 0 (this unit is a
  Magichange weapon right now). `magichange_host`: some slot s in 0/1 has SR+0x4B8+0x10*s != 0, the test the game's
  own `cmdmenu_preds_p_15cfe0` makes. `magichange_turns n`: such a slot's turn byte equals n. While a slot is held,
  `unit_stats_evil_rebuild_list` (0x140218C90) adds to the host's learned list the participant's equipped evilities
  that its char.dat row lists in evility1..4, so a monster's innate row reaches the wielder.

Rows built with them (packs `Builds/EVILCAP1-20261111/mods`; overlay via `tools/evilgap1_rows.py`):

| pack | D4 innate | row | now |
|---|---|---|---|
| D4_Unique_440 Marona | 875 Phantom Lover, "+5% stats per ally Spirit unit on map" | 27875 | `stats` ATK/DEF/INT/RES/HIT/SPD +5 `per: map_class_ally` (six stats since D4SIG3), the six Spirit class ids. D4's `FUN_1401BA0A0` counts other units of the holder's team in Spirit class group 205 |
| D4_Class_2120 Death, D4_Unique_170 Hugo (reference) | 691 Mind Killer, "Inflict 50% of damage to SP during an attack" | 27691 | alias to 3011 kept, plus `sp_damage_percent` 50 |
| D4_Unique_340 Gig | 851 Jet Black Sword, "During magichange or fusion, Equipment Aptitude increases 50%" | 27851 | `potency` all +50 with `magichange_host` (alias to 1185 removed). D4 `FUN_1401B4010` adds it to the holder's eight equipment-aptitude terms while its Magichange timer is set; D5 hands Gig's innate to his wielder. D4's giant fusion has no D5 counterpart |
| D4_Unique_450 Ash (new innate) | 878 Eccarlate, "Stats increased by 100% on last turn of a Magichange" | 27878 | `stats` ATK/DEF/INT/RES/HIT/SPD +100 (six stats since D4SIG3) with `magichange_turns 1`. Ash is a humanoid: the wielder, his own row. When D5 recomputes the aggregate after `turn_h13` lowers the byte (it calls no recalc itself) is not measured |

Proofs: `evility/offline_proof_evilcap1.py` (normal and `--abi`): the three shipped rows read from the overlay plus an
enemy-scale and a `magichanged` row, through every patched stats/potency call site; the slot rule cross-checked against
the game's own `cmdmenu_preds_p_15cfe0` on the installed exe; and every legacy plan PLUME1 diffed run on the base build
(integ-next 166237b) and this one with identical Unicorn state and identical table encoding.
`evility/e2e_evilcap1_spdamage.py` (normal and `--abi`) runs the game's own Habitual Licker block of `FUN_1401ADA40`
from its learned-list search to the computed SP damage, with the installed game's database tables, on the installed exe
(control: 25%) and on this build (50% with the row, 25% without it, nothing without 3011, condition, cap, defender-side
row ignored, register and stack-alignment checks across the redirected call). Tests: `tests/test_evilcap1.py`.

Not proven: any of it in a live battle; that `FUN_1401B1BA0` runs for every hit of every attack kind; the Magichange
fields on a live unit (read from the decompiled writers, not observed); Eccarlate's stat refresh timing.

## D4SIG3: percent stat rows are six stats; support_magic_percent (2026-11-12, offline)

* **The six.** D4's `FUN_1401BA0A0` sums every percent evility into one number (clamped -50..100), stores it at
  battle-record +0x5BE and hands it to `FUN_1401B4010(unit, percent, 1)`, which scales ATK, DEF, INT, RES, HIT and SPD (the
  final stat array unit +0xD30..0xD58) and not HP (+0xD20) or SP (+0xD28). Phantom Lover (875, 27875) and Eccarlate (878,
  27878) are two such terms (0x36B and 0x36E in that function), so their rows list those six stats instead of `all`.
* **Family `support_magic_percent`** (mask bit 29, one number per effect, no stat, own wrapper so no second family on the
  row). D5's `FUN_1401FEFA0` (D5's Medical Insertion 1180) multiplies the buff value `*rcx` by the 1180 row's +0x38 when the
  skill is support magic (magic.dat row +0x3F6 == 5). D4's analogue is `FUN_1400FF700` (cases 0xB..0x10, skill flag 5):
  `value = (read(0x130) + 100) * value / 100` (signed truncation), then a cap at 100. `wrap_support` is redirected at both
  static callers of `FUN_1401FEFA0` (0x1401C0076 in `damage_buff_compute_buff`, 0x140201F03 in the skill-value preview
  `FUN_140201D90`): it keeps the value, runs the game's own function, and when the caster's rows sum to a positive percent and
  the same support-magic test holds, writes `value * (100 + sum) / 100` over the result. The inner call at 0x1401FF046 cannot
  be wrapped for this: r8, rax and r10 (the caster) are dead after the magic-row lookup there (the D4SIG2 design assumed
  they were live). The D4 cap of 100 is not carried (D5's own stage is unmeasured; D5's x2 has none here).
  ```json
  "8304": {"family": "support_magic_percent", "effects": [{"value": 50}]}      // Chief; the alias 8304 -> 1180 stays
  ```
* Proofs: `evility/offline_proof_d4sig3.py` (normal and `--abi`, 34 checks): the game's own instructions around both call
  sites under Unicorn with the installed game's tables, the real `FUN_1401FEFA0` body, on the installed exe (control: x2) and
  this build (150 with the row, x2 without it, nothing on non-support skills, truncation toward zero, two rows add, null
  caster, 40 ids around the row, registers and stack alignment across the redirected call); `--control gate|formula|row`
  builds a broken wrapper and must fail. `evility/offline_proof_evilcap1.py` carries the Marona/Ash six-stat expectations.
  `evility/d4sig3-static-stack.json`: 73 sites, 147 calls, 0 findings. Tests: `tests/test_d4sig3.py`.
* Same trace, fixed in D4SIG4: `FUN_1401BA0A0` also holds the terms for Friends (840, 0x348: Prism Ranger, Prism Red) and
  Unlosing Mode (881, 0x371: Pirohiko); their packs now list the same six stats (both rows stay labelled adapted for other
  reasons).

## DD2D1GAP1: labels for the DD2 and D1C tracker gaps (2026-11-11, offline, no runtime change)

Lane DD2D1GAP1 went through the 8 DD2 entries whose signature evility was not done and the 3 DD2 + 4 D1C entries whose
specials were not done. No new evility row and no new special were expressible with the existing runtime and specials
path (the five DD2 signatures that exist are D5 equivalents, the three open ones need new native effects), so what
changed is labelling, in `mod.json` only (`tools/stage_dd2d1gap1.py`, `Builds/DD2D1GAP1-20261111`):

* `dd2-innate-evilities.json` (via `tools/build_dd2_innates.py`) now also names, link only, the five packs whose reviewed
  layer already links the D5 equivalent: Masked Hero 25210 (D5 Rapid Movement 1060: 3 per panel, max 64, source 2 and no
  maximum; adapted), Shark Dragon 26180 (D5 Water Management 4016, text equal, no number; exact), Alex 24480 (D5 Punishing
  Prophecy 6112 hits one random enemy, source "a random number of enemy units"; adapted), Pleinair 24320 (D5 Acceleration
  Mascot 6024 is +2, source +1; adapted; the `move` family has no aura, so a kit row cannot lower it), Pringer Z 24300 (D5
  Heavy Stance 1224 adds stats +30%, the source only "cannot be lifted"; adapted). `_dd2_innates.apply` writes
  `source_import.innate_evility {id, dd2_id, name, relation}` and the label line; no row, alias or char link moves.
* `specials2.relabel`: Xenolith 10083 and Sardia 5001-5003 are label N (the source table has no row for those ids),
  Masked Hero (DD2) and Carter (D1C) have an empty source learn list (`source_has_none`).

Left open on purpose: Baal Slave, Lilliel, Xenolith (signatures; see `Subprojects/Engine-Extensions/DD2D1GAP1-REPORT.md`),
Shark Dragon Jaws Wave Rider (mounted attack, mount mode), Strider Dark Cannon (a script-only support-other row), Vulcanus
Angelic Gospel (heal power has no measured D1 to D5 model). Lilliel could not use `regen` with `per: movement_cost`:
`turn_t3_per_unit_end_turn` (0x140159F50) zeroes the unit's panels-moved word at the end of its own turn, before the
round-edge regen runs.

## D4SIG2: scale `idle_turns`, labels (2026-11-12, offline-proven only)

* **Scale `idle_turns` (26).** The value of D5's own idle-turn counter: the stat-record byte `SR+1`, `SR = 0x141067DC8 +
  (unit +0x4348) * 0xE98` (0 when the unit has no stat record). `turn_t3_per_unit_end_turn` (0x140159F50, called from
  `turn_t1_per_unit_hp_sp` for team 0 at each round edge) adds 1 (stops at 10) when the unit's battle record +0x61C
  (movement) and three more blocker bytes are clear, and zeroes it otherwise; the proof runs that real function under
  Unicorn (counter 1, 2, 3, then a move gives 0). Used by D4 Stone Statue (807, Demon Beast): row 27807 is
  `{"family":"stats","effects":[{"stat":"def","value":10,"per":"idle_turns"}]}`, so DEF +10 % per idle turn, at most
  +100 %. D4 counts every turn of not moving; D5 also clears the counter for the blockers it checks, so the row was labelled
  adapted until D4SIG8 (below). It does not claim when D5 recomputes DEF after the counter rises.
* **Labels.** The tracker reads an evility line of a D4 pack as exact only when it says `exact text and number`, `exact
  rule` or `D5 equivalent`; `source text and number` read as unclassified (partial). The EVILCAP1 lines (Marona, Death,
  Hugo, Gig, Ash) and Mystic Beast's Accel Element now say `exact text and number` (their caveats stay in the line);
  Hugo's second slot, Death Magic 873, is not an evility the D4 source gives him and no longer calls itself his innate;
  Pringer X's Tyrant Guard line said `adapted` until D4SIG6.

## D4SIG7: scale `geo_colours` (Psylos, Geo Energy 129; 2026-11-13, offline-proven only)

* **Scale `geo_colours` (27).** The number of DISTINCT colour bytes (unit `+0x2E2C`) over the Geo Symbols that are on the map and alive
  (battle record `+0x2E8` set, unit `+0x2E04` in 4810..4819, HP `+0x2CC8` above 0), 256-bit set on `evil_scale`'s frame (now 0x58 bytes).
  A clear symbol (colour 0) counts as a colour, as D4's `FUN_1401BA0A0` counts the raw value of its record's colour field (`+0x25A`)
  over the units of family `0x1E1` that are active and alive (`FUN_140108df0 != 2`). The holder off the map, carried, or itself a
  Geo Symbol family unit counts 0 (D4 returns 0 for those). D5's field proof: the colour is written from the placement `+0x248` at
  deployment (`0x1404D29C0`, `0x1405247D0`, class family 48xx) and by `script_cmd_unit_geo_change` (`0x14016B0E0` -> `0x140157150`,
  which also writes the actor `+0x2AA`); the game's own name switch (`0x1402ACBB0`, family `unit +0x2E04 / 10 == 481`) has cases 0..6;
  the shipped maps place colours 0..6 only (448 `.chr` files, 226 symbols of char 4810/4811: colour counts 56/54/37/32/33/9/5,
  at most 6 distinct colours on one map).
* Row 27129 (D4_Unique_5388 Psylos, char 18290): `{"family":"stats","effects":[ATK,DEF,INT,RES,HIT,SPD each value 10 per geo_colours]}`;
  the six stats are the ones D4's aggregate reaches (D4SIG4). D4 caps this term at +100 inside a percent it shares with the other
  stat evilities (clamped -50..100); the kit adds rows separately, and 7 colours is +70 at most.
* Proof: `evility/offline_proof_d4sig7.py --piece psylos` (normal and `--abi`), controls `geo-dead`, `geo-active`, `geo-family`,
  `geo-distinct`, `geo-carried`, `geo-colour` each exit 1.

### D4SIG7: second-word family `attack_counter` (Rising Dragon 663; offline-proven only)

* **What D4 does.** `FUN_140106900` (the attack-power percent sum) adds evility 663's value (10) x the unit's counter (`+0x20D5`, signed char);
  `FUN_140123940` (action event 0x1E, once per action target) adds 1 to each target's counter (at most 20) when the target's result slot is not
  negative: hits, nullified hits, misses (hit code 0, slot 0) and buffs count, a heal (slot = -amount) does not; `FUN_1402DD8B0` (the end of every
  action, reached from `FUN_1402E3E20`) sets the ACTOR's counter to 0.
* **Rows.** `{"family": "attack_counter"}` is a predicate row (no effects, no conditions, second-word bit 2) and nothing alone: give the same id a class
  alias to 2065 (Impact Charge). The alias puts 2065 in the active list, and D5's own `damage_attack_bonus_rules` then adds 10 x the short at stat
  record `+0x5D8` (at most +200 = D4's 20 x 10). The family makes that short follow D4's rule. D5's `+0x5D8` has no other writer than the
  `damage_apply_damage` increment (`0x1401B2544`), the two wipes (`0x14015FB47`, `0x1401622AF`) and a record copy (`0x140091A4B`); readers are the
  bonus rules and the damage breakdown (`FUN_14020D1C0`) (exe scan of every `[reg + 0x5D8]`, `evility/` scratch `scan_5d8.out`).
* **Hooks.** `wrap_atkcount` (tag 0xE70020) redirects the one call of `damage_apply_damage` in `FUN_1401B1BA0` (`0x1401B1BE0`, per action target):
  for a holder it stores `min(counter before the call + 1, 20)` (+0 for a heal: skill row category byte `+0x3F6` == 4, or no result slot), so D5's
  own count (non-elemental only) is discarded. The reset is in `wrap_face_away` (the once-per-action pass, `0x14053FE71`), run before its
  face-away work. No new instruction hook, no new byte of game memory.
* Proof: `evility/offline_proof_d4sig7.py --piece dragon` (normal and `--abi`): both real call sites on the kit build with the pinned exe as control,
  the REAL `damage_attack_bonus_rules` body for the reading side, controls `dragon-heal`, `dragon-miss`, `dragon-cap`, `dragon-keep`,
  `dragon-holder`, `dragon-reset`, `dragon-argument` each exit 1.

* **D4SIG9 (2026-11-14): the reset also runs after the holder's own counter-attack, as in D4 (no change made).** D4 queues a counter
  as an ordinary queue entry (`FUN_1402E13A0` / `FUN_1402E0490`: `FUN_1402B4310` + `FUN_1402B4300`, actor = the unit that was hit, target =
  the attacker, `+0x37CD` = chain depth + 1, so `FUN_140107B40` reads true); the queue runner `FUN_1402E3420` drives every entry through
  the same state 3 = `FUN_1402E3E20` -> `FUN_1402DD8B0`, whose `+0x20D5 = 0` has no condition on the entry (the neighbouring blocks test
  `+0x7A0`, the skill id, for 0; this one does not). Its actor is `FUN_140107720(ctx, 0)` = ctx `+0x308`. So a D4 Dragon's counter-attack
  adds 1 (event 0x1E on the attacker) and then resets his own counter, exactly what the kit does and LIVEFX3 saw.

### D4SIG8: `wrap_endturn` (Demon Beast, Stone Statue 807; offline-proven only)

* **What D4 does.** `FUN_1400F3C20` (the per-unit round-edge routine; its caller `FUN_1402EB670` is the same loop as D5's
  `turn_t1_per_unit_hp_sp`) tests only the unit's move cost (battle record `+0x4E8`): 0 raises the holder's counter (unit `+0x22DE`, a byte)
  by 1 while it is below 10, anything else sets it to 0, then the unit is recalculated; `FUN_1401B4010` adds value 10 x the counter to
  the DEF percent. `+0x4E8` is written by `FUN_1400F1200` from the move commit and cleared on undo (call shapes of its eight callers read). Acting,
  being hit, being lifted or thrown are not tested.
* **Where D5 differs.** `turn_t3_per_unit_end_turn` (0x140159F50) raises the stat-record byte `SR+1` only when `+0x61C` (move cost), the
  stat-record byte `SR+2` (raised by the lift/throw commands `FUN_140534070` / `FUN_140534380`), the battle byte `+0x11E1` (set by
  `damage_apply_damage` on a target hit by a skill whose row `+0x3F3` is set) and, in one mode, `+0x11F5` are all 0.
* **Hook.** `wrap_endturn` (tag 0xE70021) redirects the three static calls of T3 (0x1405524FF, 0x140554F7F, 0x1405FB9B1). For a unit that has
  learned 27807 it reads `SR+1` and `+0x61C` before the call (T3 clears `+0x61C`), runs T3, and stores D4's value. Any other unit is untouched.
  The row itself is unchanged (stats, DEF +10 per `idle_turns`): the wrapper makes the byte the scale reads follow D4's rule.
* Proof: `evility/offline_proof_d4sig8.py` (normal and `--abi`): the three real call sites with the real T3 on the kit build and on the pinned exe.

## DRPGPARTY1: potential type and favourite weapon (2026-11-12, offline-proven only)

* **Class registry.** A mod's evility data (`patches/evilities/evilities.json`) may carry `"classes": {"<class id>":
  {"weapon": 1..9, "potential": 1..6}}` (D5 item category of the favourite weapon, Disgaea RPG potential type; either may
  be 0 but not both). `build_patch` emits it as a sorted data block (`evil_class_tbl`, one dword per class: class |
  weapon << 16 | potential << 24) next to the row table; `evil_classinfo` binary-searches it. Up to 1,024 classes, all mods
  together; the same class with a different type in two mods stops the build. It is data, not rows, so `table()` and the
  legacy encodings are unchanged and the 2,048-row limit is not touched. The class is the unit's `+0x2E04` word, the same
  value `near_char` reads.
* **`d5lib/importers/drpg-class-registry.json`** is generated by `tools/build_drpg_class_registry.py` from the JP client
  `character` master (`best_weapon_type`, `m_potential_class_id`) and `drpg-leases.json` (235 classes: 146 bases plus 89
  costumes, which inherit their owner's type). Weapon map DRPG 1..9 to D5 item category 2,1,3,4,5,6,7,8,9. `drpg_evilities.apply`
  writes it into a pack only when one of that pack's own evilities needs D4.
* **D4 (decision, default on):** potential type and favourite weapon come only from the registry; a D5-native or other-game
  ally has none, receives nothing, and breaks an "all favourite weapons different" condition. The labels say `adapted`.
* Built from source with this: Master Big Star, Sweet Omega, Merome, Kagemaru, Tria, Pii-chan (potential type of the
  recipient), Thunderlord Laharl, Ice Empress Rozalin, Flame Empress Majorita (all favourite weapons different), plus six
  sub-evilities that fall out of the same capability. Proof: `evility/offline_proof_drpgparty1.py` (normal and `--abi`).

## D4SIG4: Friends / Unlosing Mode stat set; weapon_percent for Nagi (2026-11-13, offline)

* **Six stats.** Friends 840 (term 0x348, `value x local_288`, inside the first accumulator whose total flows into the returned
  sum) and Unlosing Mode 881 (term 0x371, added while `FUN_1400ED540(holder)` is non-zero) are terms of the same
  `FUN_1401BA0A0` sum as Marona's and Ash's, so rows 8840 (owned by D4_Class_1220) and 27881 now list ATK, DEF, INT, RES, HIT, SPD
  instead of `all`. Labels unchanged (adapted: squads for the Evil Area; an automatic 3-round window for the menu command).
* **Family `weapon_percent`** (mask bit 30, one number per effect, aura-capable, listed in `ADD_FAMILIES`). D4's Everyone's Mechanic
  (892, term 0x37C of `FUN_1401B4010`, lines ~1150-1220): for every other unit of the holder's team the value is summed, the sum
  stops at 100, and it multiplies the ITEM STAT of the equipment slots the loop treats as weapons: `item x (100 + sum) / 100`,
  before the aptitude weight. D5 `unit_recalc` calls `unit_stats_equip_stat` (0x140219630) once per stat, eight static calls
  (0x14021D53C..0x14021D5F3); `wrap_equip` (tag 0xE7001C) runs the game's own function and, when the slot's category byte
  (+0x156 of the 600-byte entry) is 1..9 (the game's own weapon test), scales the result by `(100 + sum) / 100` (signed
  truncation, sum capped at 100). The sum is `evil_dmg_sum` over the unit's rows including aura rows; an aura row counts once
  however many providers (Nagi is unique).
  ```json
  "27892": {"family": ["weapon_percent", "aura"], "effects": [{"value": 10}],
            "conditions": [{"kind": "near_has", "of": 1, "radius": 65535, "id": 27892}]}
  ```
* **Caveat, measured.** The scale is applied after D5's own stages of that function. With no other weapon-percent source it equals
  adding the percent inside the function; with D5's own weapon-percent evility 6035 (+30) the two multiply (715 for item 1000 at
  potency 50) where D4 adds them (700). D5's later x1.5 stage is also applied before ours. Not measured: when D5 recalculates
  stats after an ally holder arrives or dies.
* Proofs: `evility/offline_proof_d4sig4.py` (synthetic harness, the eight real patched call sites, normal and `--abi`, 240 checks,
  `--control gate|cap|formula|row`) and `evility/offline_proof_d4sig4_real.py` (the game's own instructions around the first call
  with the REAL `unit_stats_equip_stat`, the real Skill.dat and the real battle table, 12 cases against the installed exe).
  `evility/d4sig4-static-stack.json`: 81 sites, 149 calls, 0 findings. Tests: `tests/test_d4sig4.py`.

## D4SIG5: evasion (2026-11-13, offline)

* **D4's rule** (source observation, D4 decomp + exe). `FUN_1400FF700` decides a hit: rate = HIT x 100 / SPD, plus flat terms; the
  defender's Beryl's Servant 1 (844, class 350 only, while an adjacent same-team unit holds evility 1 = Raspberyl's Love Thy
  Heart) is **subtracted** there; then the rate is capped at 100, floored at 0, and multiplied by the float `FUN_140107100`
  returns, the product of `(100 - v) / 100` over the defender's evasion evilities (351 Misty Haze when the per-target direction
  is 0 = front, 620 side, 352/353 by range ...). D4 rolls the result in two stages (a failed first roll gets a second roll that
  decides miss or a weakened hit).
* **D5 has the same input.** `damage_hit_chance_rules` (0x1401F5410) takes the percent in/out, clamps it to 1..100 as its first act
  (checked against the real instructions 0x1401F5431..0x1401F5475 in the proof), then multiplies it by `(100 - v) / 100` for its own
  evasion evilities (Skill rows 0x3C, 0x4C, 0x46A ...). The kit family `evasion` is applied by `wrap_hit` around that call:
  `"mode": "points"` before it (so the game's clamp comes after, exactly as D4's cap comes after its flat terms), the default
  `"scale"` after the attacker's `hit` rows. `evil_dmg_sum` gained a mode filter (`evil_fxmode`, 0 = every effect, so every other family
  reads as before): points effects carry stat-word bit 8.
  ```json
  "8351":  {"family": "evasion", "effects": [{"value": 50}], "conditions": [{"kind": "attack_dir", "id": 0}]},
  "27844": {"family": "evasion", "effects": [{"value": 50, "mode": "points"}],
            "conditions": [{"kind": "near_char", "of": 1, "radius": 1, "id": 650}]}
  ```
* **Not carried (written in the rows' lines).** D5 rolls once where D4 rolls in two stages, so the same percent gives D5's own miss rate; D4
  reaches 0% where D5 keeps 1%; two scale rows on one unit add where D4 multiplies; 844's neighbour test is the kit's radius-1 test
  on D5's Raspberyl (character 650), not D4's adjacency function.
* Proof: `evility/offline_proof_d4sig5.py` (the real patched call site 0x1401C2318, normal and `--abi`, 83 checks including a sweep
  against an independent model of D4's formula, `--control mode|formula|row|dir`). Replaces the 50% `nullify` stand-in of rows 8351 / 27844
  and its five 27844 cases in `offline_proof_evilfx2.py`. Tests: `tests/test_d4sig5.py`.
* **Speedy Move 690 (Masked Hero), relabelled exact** (source observation, D4 decomp + exe). `FUN_1401BA0A0` term 0x2B2 adds
  `5 x FUN_1400EABF0` (battle record +0x4E8) to the unit's six-short percent block at +0x17F4..0x1802 (ATK DEF INT SPD HIT RES order of
  the terms 0xB5..0xBA: +0x17FE is SPD), after that slot's clamp to -50..100; the only reader, found by scanning the exe for the
  displacement (0x1401B6AA9, inside `FUN_1401B4010`), puts it into the SPD percent sum that scales the stat by `(100 + sum) / 100`. So
  it is "SPD +5% per counted panel", unclamped, additive with the other SPD percents, as the row does. The counter is set by
  `FUN_1400F1200` (cost value of the move's destination cell) and zeroed by `FUN_1400F3C20`, the per-unit end-of-turn routine
  (followed by the stat recalculation). D5's `turn_t3_per_unit_end_turn` (0x140159F50) is the same routine (same idle-counter block) and zeroes
  +0x61C; `turn_t1_per_unit_hp_sp` follows it with `unit_recalc`; `confirm_push_move_entry` adds the move's cost to +0x61C. The only
  difference: D4 sets the counter, D5 adds each confirmed move (equal with one move per turn). Live read already on file (LIVEPROOF3, +15%
  after a 3-panel move); the read after End Turn is not measured.
* **Tyrant Guard 667 (Pringer X), lethal exception built (D4SIG6, offline-proven only).** D4 `FUN_1400FF700` (lines 1768-1783)
  nullifies a hit while the unit's hit counter `c` (unit +0x1183) is under `max(1, T)` and keeps a lethal result. `c` is +1 per landed hit
  (`FUN_140123940`: per-target hit code `action+0x49C+i*4` above 0, result slot >= 0, `action+0x7B6 == 0`; the nullified hit counts too),
  reset in `FUN_1400F3C20`, which `FUN_1402EB670` runs in one pass over every battle-table slot at the turn end (`FUN_1402EA550` state 1).
  `T` is the number of Tyrant Cult (669, "Effective time of Tyrant Guard = # of units with this Evility") holders on the team
  (`FUN_1402E9400`); no pack here carries 669 (not found in `d5lib/importers/*.json`), so T is 0 and for T of 0 or 1 the rule is "the
  first non-lethal hit between two turn ends": a boolean is exact, which is why no counter byte or new hook site was needed (a counter
  above 1 needs T of 2 or more).
  The installed stand-in (alias to D5's First Impression 6047, flag +0xDF9 of the stat record, cleared at the round edge by
  `rearm_first_damage`) matched that except for one thing: D5's 6047 test has no damage test, so a lethal first hit was nullified.
  `damage_nullify_predicate` (0x1401FE0D0) asks for 6047 with a CALL to `cmdmenu_preds_p_2068b0` (0x1401FE3B3, `mov edx, 6047`),
  then tests the byte. `wrap_firstimp` (tag 0xE7001D, the ordinary call-redirection pattern, no instruction hook) runs the game's
  own answer and, only for a unit that also holds a `rearm_first_damage` row and only when the hit's damage `v` (the predicate's sixth
  argument, `[S+0x4B8]` in its fixed frame) is at least the unit's current HP (+0x2CC8), answers "not carried", so the predicate goes
  on as for a unit without 6047. Units without the row get the game's answer unchanged (proved through the real predicate, see
  `evility/offline_proof_d4sig6.py`). Not measured: that the round-edge clear (`turn_ctl_s6_update`, 0x1405F8FFC) falls where D4's
  turn-end pass does; D4's `+0x7B6` test; D5 callers that pass no damage (`v` of -1 at 0x140417E64) keep the old nullify.
* **Death Saber 836 (Vanishing Cat): direction established in D4SIG6, built in MASKWIDE1 (section below).** The D4SIG6 site proposal (exec_ctl_s0_update) was wrong: that is the queue-exhausted block.

## MASKWIDE1: a second family word, and Death Saber 836 (2026-11-13, offline-proven only)

The u32 family mask (row +4) was full. A row now has a SECOND family word in `flags` (+24) bits 8..31 (24 more families). Such a
row has mask 0, no effects, evility scope, no aura (it is a predicate row: presence + conditions). The runtime asks for one with a
64-bit query: the high half of `rdi` (to `evil_pred`) / `rdx` (to `evil_next`) names the bit (`ext_query(name)` = 1 << (bit + 32)).
Every existing query is `mov edi, N` / `mov edx, N`, which zero-extends, so old queries are unchanged, and old rows have flags bits 8+
equal to 0, so every existing row encodes byte for byte as before (`tools/maskwide1_tabledump.py`: the whole merged table of the 197
installed mods with evilities, 1157 rows / 1273 conds / 1860 fx, identical before and after). `evil_next` tests the second word only
when the first-word test fails; skill scans never see second-word rows. Register a family in `EXT_FAMILIES` (name -> bit 0..23).
Proofs: `evility/offline_proof_maskwide1.py` (a throwaway test family wired to the counter wrapper; fails with the second word
ignored or the query truncated to 32 bits), `tests/test_maskwide1.py`.

**face_target_away** (bit 0) / `wrap_face_away` (tag 0xE7001E) at the one call of `post_hit_effects` 0x140542CB0 (0x14053FE71) in
`exec_ctl_s2_update` 0x14053F880 (reached once per action after the ctx-bound script ended and every target's vertical speed is 0).
Before the game's own call, for an attacker (battle record in r8) whose unit holds the row: for each target entry j (count short ctx
+0x27318, entry ctx +0x1318 + j*0x260: short battle slot at +0, KO byte at +0x216 = ctx +0x152E+j*0x260, the byte S2's own counter loop
tests) with KO byte 0 whose record is active and has a unit, if `ai_transition_within_range(attacker, target, 1, -1)` (0x140153FF0,
D4 FUN_1400ED660) holds, `unit_set_facing` (0x14014F640) is called with `carry_throw_facing_angle` (0x1402D8D60) of target minus attacker
(world x/z truncated to int): the target faces directly away. D4: FUN_1402DD8B0 (evility 0x344) run by FUN_1402E3E20, killed flag
action+0x3E98+i (set in FUN_140191170 when the hit leaves HP 0). Proof: `evility/offline_proof_maskwide1_face.py`
runs the kit build and the pinned exe under Unicorn with the game's own adjacency and facing code (CRT atan2 hooked for the control only).
Not measured: that D5's later states / idle pose leave the facing alone, and the visual result.

**D4SIG9 (2026-11-14): the angle is D4's own, the row is `exact rule`.** MASKWIDE1 called D5's `carry_throw_facing_angle` and listed
three differences. The angle is now D4 FUN_14022F350 computed inline in integers: dx = tx - ax, dz = tz - az; |dz| < |dx| gives 90
(dx > 0) or -90 (dx <= 0); otherwise 0 when dz > 0, else 180. That fixes (a) a zero distance (the attacker as its own target: 180, stored
-180 by `unit_set_facing`) and (b) the exact 45 degree ties (dx = dz > 0: D4 0, D5's atan2 function 90; dx, dz < 0: D4 180, D5 -90) and
the asymmetric truncation at the negative bucket edges (angle -45.46: D4 -90, D5 0). (c) The KO byte: D5 `damage_apply_damage`
0x1401B1FD0 sets ctx +0x152E+j*0x260 at its top when the target is already at 0 HP and again when the hit kills (`local_res10 == 1`) unless
script flag 0xFFF (`DAT_144FCCD0D & 0x80`, the byte base 0x144FCCB0E + 0x1FF) is set; D4 FUN_140191170 sets action+0x3E98+i at its top
when HP is 0 and again when its kill variable is 1 unless `FUN_14015FCB0(0xFFF)` (the same flag number): the same condition under another
name, matched by structure, not branch by branch (an engine difference, listed in the row). Other listed differences: D4 FUN_1400ED660 reads
a saved cell (+0x74A, flag +0x744, written by FUN_1400F0710) in some states where D5's `ai_transition_within_range` reads the record's
world position; D5 stores a facing of 180 as -180. D4 runs FUN_1402DD8B0 for counter-attack queue entries too (no gate on the entry's kind).
Proof now 23 cases (+ self, 4 exact ties, 3 near-tie cases via a footprint cell next to the attacker) and 8 controls (killed, dir,
adjacent, holder, order, zero, tie, oldangle).

## DRPGSIG1: enemy_heal_percent, Seraphina XENO 1641 (2026-11-13, offline)

`wrap_support` (D4SIG3) is NOT a heal-amount wrapper: its call site `damage_buff_compute_buff` computes the stat-change status value of
support magic (`FUN_1401FEFA0` multiplies it by the vanilla Medical Insertion 1180 row's +0x38), so a heal amount needs its own site.
The heal amount is computed by `damage_heal_compute_heal` 0x1401BF3C0 (one caller, `battle_damage_compute_target`); after the base amount
it calls `FUN_1401FFF40(&amount, healer record, healed unit's record, skill row)` (0x1401BF503, the only call in the exe), which applies D5's
own Evil Spirit (141): `amount *= (1 - row141 +0x38 / 100)` once per active unit hostile to the healed one that holds 141 (a ^n for n
holders), then the healer's own 3305 term. The number comes from the vanilla row (50), which a mod cannot change, so a different number needs
a family of its own.

* **Family `enemy_heal_percent`** (second family word, bit 1) / **`wrap_healmod`** (tag 0xE7001F) at 0x1401BF503. The only second-word family
  that carries a number: one effect `{"value": 1..100}`. The wrapper runs the game's pass first (arguments and result unchanged), then walks
  the 256 battle records: for every active, uncarried unit with a stat record whose team is hostile to the healed unit's team (the table
  `evil_near` uses) it takes `evil_dmg_sum(bit 33)` of that unit and multiplies the amount by `(100 - min(p, 100)) / 100`, signed
  truncation, one holder at a time. The healed unit itself is skipped.
  ```json
  "28176": {"family": "enemy_heal_percent", "effects": [{"value": 35}]}      // Seraphina XENO, DRPG leaderskill 1641
  ```
* Reading: "all enemies' healing amount" is taken as the heal a unit hostile to the holder RECEIVES (the way D5's own 141 reads). The DRPG
  masters hold no wording that separates received from given healing (the 8/9 heal-amount rows say only "party / all enemies' healing
  amount"), so the two readings differ only for a heal that crosses sides; not settled. Timing 5 (wave start) is read as always on (D2).
* Proof: `evility/offline_proof_drpgsig1.py` (heal section, normal and `--abi`), the real call site 0x1401BF503, the game's pass stubbed (x 3/4
  so the order shows), the walk and `evil_dmg_sum` are the kit's code: hostile teams, same team, neutral team, inactive, carried, no unit,
  other ordinary row, other second-word row, three holders, slot 0 and 255, 6 values x 7 amounts against an independent model. Controls
  `heal-formula`, `heal-hostile`, `heal-row`, `heal-active`, `heal-carried` each exit 1. Tests: `tests/test_drpgsig1.py`.
* Not measured: any of it in a live battle; that `damage_heal_compute_heal` runs for every heal kind (skills, items); the preview of a heal
  amount (the AI and forecast callers of `battle_damage_compute_target` take the same path, so they see the same amount).

## DRPGSIG1: map_hp_at_or_below (condition 71), Breezy Satina 2731 (2026-11-13, offline)

* **Condition `map_hp_at_or_below`** (`count`, `of` 0 any / 1 ally / 2 enemy, `id` = percent 1..100): at least `count` units of that relation
  on the map are alive (HP above 0) with `hp * 100 <= max HP * id` (signed 64-bit, the arithmetic provider test 4 uses). `evil_near` gained
  filter kind 13; `.c_maphp` mirrors `.c_mapstat`. False while the subject is off the map. A map walk, so `build_drpg_evility_overlay.py`
  places it after the aura's `near_has` (HEAVY). No new hook site: it is a condition of the existing wrappers.
  ```json
  "28256": [{"family": "dealt", "effects": [{"value": 30}], "conditions": [{"kind": "map_hp_at_or_below", "count": 1, "of": 2, "id": 50}]},
            {"family": ["dealt", "aura"], "effects": [{"value": 30}], "conditions": [{"kind": "near_has", "of": 1, "radius": 30, "id": 28256},
                                                                                   {"kind": "map_hp_at_or_below", "count": 1, "of": 2, "id": 50}]}]
  ```
* Breezy Satina's source rule: "at turn start, if an enemy has HP at or below 50%, grant the party all damage +30% for 2 turns" (leaderskill
  2731: timing 2 turn start, trigger target 7 status 16 param 50, effect 49, 2 turns, target party). The kit reads it as a LIVE condition,
  not latched at turn start and not held for 2 turns (a buff the source re-applies each turn is read as always on, D2). The label says so.
* Proof: `evility/offline_proof_drpgsig1.py` (satina section, normal and `--abi`): the real dealt call site 0x1401C169D, boundary 50/51,
  fractions, 64-bit HP, defeated and max-0 units, ally / neutral / enemy relation, other units on the map, holder row and aura row, subject
  off the map. Controls `satina-hp`, `satina-dead`, `satina-relation` each exit 1.

## DRPGSIG2: invincible_hits (Majorita 392) and the Lich Deimos alias (Jusoso 20100) (2026-11-14, offline)

**Source rules** (Disgaea RPG JP masters under `Disgaea Source/Disgaea RPG JP (Android)`): `leaderskill` 3925 (effect 90, target self, timing 1, value 2:
"invincible (2 times) at battle start") and 201005 (effect 48, self, timing 8, value 100: "once per battle, when defeated, revive with full HP").
The `help` master (id 50, "About invincibility") says: invincibility turns the damage of the granted number of times into 0; buffs, debuffs,
ailments and thorns still land; it cannot be stacked; a combo (renkei) consumes one however many hits it has. Help id 55 (auto revive) says HP 100 %, after
the unit's own turn ends. Not found in the masters and the help: what a lethal hit does to invincibility beyond "the damage is 0" (read as nullified), whether poison,
falls and field damage consume it, where Jusoso revives. These readings are in the labels.

* **Family `invincible_hits`** (second family word, bit 3, one effect `{"value": 1..100}` = N). Two parts, both in existing wrappers (no new call site):
  * DECISION, `wrap_nullify` (the nullify-predicate wrapper) after the game's own answer: only the two sites whose hits `damage_apply_damage`'s wrapper also sees
    (return addresses 0x1401BF0F5 compute_target and 0x1401BF6E2 damaging heal; 0x14060B657 and 0x1401C0A30 do not take part). If the defender holds the row, the hit's
    damage `v` is above 0 and its count is below N, the hit is nullified (a lethal one too) and the kit's byte `evil_pend[stat index]` is set to 1. Every other
    pass clears that byte. A forecast reads the decision and writes only the mark, which the next pass overwrites.
  * COUNT, `wrap_atkcount` (D4SIG7's wrapper at 0x1401B1BE0, once per action target, forecasts never pass): after the real `damage_apply_damage`, for a holder, the count
    is `before + 1` when the mark was set and the hit is nullified (result slot 0), connected (`+0x1330 != 0`) and not a buff (skill category 5/6), never above N; the mark is
    cleared; otherwise the count is what it was before the call (D5's own write of 1 is taken back).
  ```json
  "28376": [... stats and crit_damage rows (own + aura) ..., {"family": "invincible_hits", "effects": [{"value": 2}]}]      // Cheshire Cat Majorita
  ```
* **Counter home: stat record `+0xDF9`** (D5's First Impression 6047 "took damage this stage" byte, used as the holder's count; reset per battle by the stat record
  wipe 0x14015FAF0 / init 0x1401620B0 together with the rest of the record, as First Impression's own flag is). Scan of the pinned exe (`evility/drpgsig2-scan-df9.txt`,
  capstone over 2,275,004 decoded instructions: every memory operand with displacement 0xDF9 / 0xDF8 word, and every RIP-relative reference into the record array that
  lands on it) and of the decomp text (`DAT_141068bc0 + unit * 0xE98 + 1`, `DAT_00000df9`): writers = `damage_apply_damage` (sets 1 on a connected, non-buff hit), the record
  wipe / init / copies (`FUN_140065370`, `FUN_140071a30`, `FUN_1400B7EA0`, `lifecycle_globals_unit_slots_detach`, `FUN_1401620B0`, `FUN_140670A20`, `FUN_1407264D0`) and the kit's own
  `rearm_first_damage` clear in `wrap_revenge`; readers = `damage_nullify_predicate` (only behind `has_evility(6047)`, 0x1401FE3F0) and the unit info text `FUN_14020D1C0`
  (also only behind 6047, 0x140215732). The `+0xDF8` neighbour (evility 0x1784, `repeat_kind`) and the five `[reg + 0xDF8]` qword reads in `FUN_1403E0FE0`, `FUN_1403E7420`,
  `FUN_140760950`, `FUN_140760E00`, `title_menu_enter` are other structures (a 0x3E0-stride array). So for a unit without 6047 or `rearm_first_damage` the byte is free. A holder that
  also carries either of those shares the byte: First Impression then ends at the first nullified hit (as in D5), `rearm_first_damage` would clear the count each round (not combined here).
* Not carried: damage that does not pass `damage_nullify_predicate` -- poison / thorns at turn start, falls (`carry_land`), field and geo effects, `fixed_damage_all` -- is neither
  nullified nor counted (the source help does not say whether invincibility covers it). D5 counts once per action target, which is the source's "a combo counts once".
* Proof: `evility/offline_proof_drpgsig2.py` (80 checks, normal and `--abi`), the real sites 0x1401BF0F0 / 0x1401BF6DD / 0x14060B657 / 0x1401C0A30 and 0x1401B1BE0 on the kit
  build, the pinned exe as control; controls `inv-count`, `inv-v`, `inv-site`, `inv-clear`, `inv-game`, `inv-holder`, `inv-pending`, `inv-miss`, `inv-buff`, `inv-cap`,
  `inv-keep`, `inv-slot`, `inv-pclear` each exit 1. Tests: `tests/test_drpgsig2.py`. Static stack: `evility/drpgsig2-static-stack.json` (88 sites, 170 calls, 0 findings).

**Jusoso: the revive is D5's own.** The lead of DRPGSIG1 (`model_action_stack_end_push_revive` 0x1401511E0, counter `+0xE58`, flag `+0xE1D`) is NOT a unit revival: it pushes entries
on the unit's move / act command stack (kinds 2, 3, 8, 9, 10; Sorrow `battle__model.md` 4.6 and `battle__cursor.md`) so a unit gets a fresh move and act after "end", from a counter of 2 that
`battle_start_common` sets for units whose script status value k = 1 (`+0xE1D`) is above 0. The real revive is **evility 145 "Lich Deimos"** (Skill.dat row: "Once per stage, revive
inside the Base Panel after being defeated"): `model_update_sweep_units` 0x1404A8D10, for a retired unit with 145 in its evility list, team byte `+0x2E32` == 0 and the stat-record flags
`+0x5E4` and `+0xDF4` both 0, sets its HP (`+0x2CC8`) to its maximum (`+0x2CD8`) after the record release and sets the flags (the release keeps them), so it happens once per stage; the flags
are cleared by the next record wipe. The kit's alias hook (0x14021878C) adds a game id to the active list of a unit that holds the aliasing id, so `patches/evilities/aliases.json {"28528": 145}`
gives Jusoso exactly that. `build_drpg_evility_overlay.py` now keeps BOTH the runtime rows and the alias of an evility that has an alias row and other rows (Jusoso: party HP / ATK / crit damage +20 %
rows + the alias); an evility whose rows are all alias rows is unchanged. Difference to the source: D5 returns the unit to the Base Panel (the source says nothing about where). Zed's sub 1
(leaderskill 942, the same rule) is the same alias. Proof section `jusoso` of the same file (alias hook, the game's `has_evility`, static decode of the sweep; the revive itself is live-needed).

### D4SIG10: `evil_hospital` in `wrap_regen` (Medic, Base Hospital 864, row 27864; offline-proven only)
* D4 `FUN_1402EB670` (the per-unit pass of the battle machine's round-end state: `FUN_1402EE580` case 1 goes to state 100 only when no side has a pending phase, then
  state 0x66 runs `FUN_1402E98D0` -> `FUN_1402EA550` -> `FUN_1402EB670` once per round over the whole unit table): for every unit with 864, walk the party roster
  (`FUN_1400FC2D0`, `DAT_140D54FE6` records); a record with `+0x20D3 == 0`, not dead and with no battle unit (`FUN_140244320`) gets maxHP x 5 / 100 on HP and maxSP x 5 / 100 on SP
  (signed truncation, no minimum of 1), each clamped. `+0x20D3` is set to 1 only by `FUN_1400EFC30`, `FUN_1400F23D0`, `FUN_1400EFDA0`, `FUN_140280420` (records moved into another
  unit's member list) and cleared by `FUN_140306FD0` / `FUN_1403BFB50` when the unit separates alive.
* D5: `wrap_regen` (tag 0xE7000C, the two calls of `turn_t1_per_unit_hp_sp`: 0x140554B9E in the round-end sweep `sequencer_ctl_s1_update` and 0x1405FB5DF in TurnCtl init PASS B) now
  also calls `evil_hospital` for a unit that has learned 27864 and whose team byte `+0x2E32 & 0xFB` is 0 (the sweep: once per round per player-side unit). It walks the roster
  (0x145207DB8, stride 0x4750, count = the short at 0x145574A9C) and adds 5% of max to HP (+0x2CC8 / +0x2CD8) and SP (+0x2CD0 / +0x2CE0), clamped, for each record that is present, team 0, alive,
  not a Magichange weapon (stat record byte `+0x4E2`) and the record of no active battle unit. No new wrapper, no new site, no row in the evility table (the id is read with `evil_has_id`, the
  value 5 is written into the code).
* Not carried: other-side providers; the D5 table also holds other sides (recipients limited to team 0); `+0x4E2` is read as D5's counterpart of `+0x20D3`; D5's facility heal still applies on top.
* Proof: `evility/offline_proof_d4sig10.py` (76 checks, normal and `--abi`), both real sites on the kit build with T1 stubbed, the pinned exe as control; controls `hosp-call`, `hosp-id`,
  `hosp-team`, `hosp-dead`, `hosp-deployed`, `hosp-clamp`, `hosp-sp`, `hosp-count`, `hosp-magic`, `hosp-recteam`, `hosp-pct`, `hosp-present` each exit 1. Tests: `tests/test_d4sig10.py`.

### D4SIG10b: Roc, Miasma of Silence 115: `special_seal`, `wrap_roc_geo`, `wrap_roc_skill` (adapted; offline-proven only)
* D4's "status 10" (`FUN_1400E9D40(unit, 10)`) is not an ailment: it counts GEO EFFECT index 10 under the unit (`DAT_1416A5EF0[cell][effect]`), GE.dat row 11 "Silence: No Special Skills can be
  used by characters on". D5 has the same effect (its GE.dat row 10, "No Specials can be used by units on", column 10 of the ground table) and reads it once, as `unit_effect_table_sum(unit, 10)` in
  `cmdmenu_preds_p_156820` (the base of the Skill command; callers `cmdmenu_preds_skill_enabled`, used by the menu and the quick commands). D5's statuses 3 and 4 are Amnesia and Weaken (magic.dat effect kinds
  24, 25) and are not used.
* New second-word family `special_seal` (bit 4, a predicate row; row 27115 on `D4_Class_2110`). `evil_roc(battle unit)`: a unit that is active, not the asked unit, alive (record HP > 0), of a hostile team
  (`evil_hostile`), not an object (`events_env_is_object_rec` ids, which include D4's class 0x12CA = 4810), holds a `special_seal` row and is within distance 1 by the game's own
  `ai_transition_within_range` 0x140153FF0 (= D4 `FUN_1400ED660`, footprints, Manhattan 1) next to the asked unit.
* `wrap_roc_geo` (tag 0xE70022) at the one call of `unit_effect_table_sum` in `cmdmenu_preds_p_156820` (0x140156A47): column 10 answers 1 for such a unit (the game's own gate of the Skill command).
  `wrap_roc_skill` (tag 0xE70023) at the four calls of `cmdmenu_env_stat_row_can_use_skill` (exe call scan: only these; the executor `FUN_140547750` 0x14054785D, the AI `list_skills` 0x1402D0A90, the menu
  0x14062E7BD and 0x14062EC38): answers 0 for a magic.dat row whose class byte `+0x3F2` is 0, 1 or 2. `cmdmenu_env_stat_row_skill_slots` and `script_var_int` read statuses 3/4 and are untouched (the slots feed
  lists that the same predicate filters; script variables are for event scripts).
* Not carried: D4 `+0x115E`, evilities 0x298 Fetters and 0x280 Geo Break (no unit in the install holds them). Label `adapted`: the game's own Silence panel never reaches the AI or the executor.
* Proof: `evility/offline_proof_d4sig10b.py` (164 checks, normal and `--abi`), the five real sites with the real callees, plus the real `cmdmenu_preds_p_156820` body; 14 controls each exit 1.
  Tests: `tests/test_d4sig10b.py`. Static stack: `evility/d4sig10b-static-stack.json` (93 sites, 178 calls, 0 findings).

### DD2EVIL2: Disgaea D2 Pleinair 320, Lilliel 420, Alex 480 (`ally_move`, `move_heal_percent`, `random_victims`)

Source: the Disgaea D2 `EBOOT.elf` (same file and accessors as DD2EVIL1; addresses are its virtual addresses), full notes in `Subprojects/Engine-Extensions/DD2EVIL2-REPORT.md`.
Three more valued second-word families (bits 5, 6, 7 of `EXT_FAMILIES`, one `{"value": 1..100}` effect; query `1 << (bit + 32)`).

* **Pleinair 320, `ally_move`, value 1, label `exact rule`.** D2 `0xF7938` / `0xFC724` add `value x 0xF6290(...)` to the unit's move byte (`+0x1171` of its character data); `0xF6290(out, id, unit, 0, -1, 1, 1)` counts the battle-table units whose team byte `+0x6EB` equals the unit's and which hold the evility, skipping the unit itself, with no range (the range argument -1). `wrap_move` (existing sites) adds the row value of every OTHER deployed unit of the unit's team (`evil_team_sum`, subject not counted); a unit whose move range is 0 gets nothing. Not carried: added after D5's own range clamp; D2's liveness tests (`0x31A1C`, `0x1035B0`, `+0x262`) against D5's active / not carried / HP above 0.
* **Lilliel 420, `move_heal_percent`, value 2, row 26305 (DD2 late band: a new row at 24420 would shift 11 installed learnable rows), label `adapted`.** D2 `0xF64C0(unit)` = `value x (other same-team holders) + value (when the unit itself holds it)`, no range; its callers (`0x219ED0` the walk step, `0x21AC3C` the second executor, `0x210C08` a path preview loop with the apply flag 1) heal the stepping unit by that percent of max HP at EVERY STEP through `0x219804` (clamped to max HP; the panel flags `0x1B800` ids `0x2A` / `0x25` turn it into an SP change / a reversal). `evil_move_heal`, called at the top of `wrap_endturn` (existing three sites) before `turn_t3_per_unit_end_turn` zeroes `+0x61C`, heals `percent x max HP / 100` (truncated) once per panel moved, capped at max HP, for a unit that is alive and whose team (itself included) holds the row. Difference: timing (end of the unit's own turn, not per step), movement cost for steps, panel flags.
* **Alex 480, `random_victims`, value 5, label `adapted`.** D2 `0xFB984` (event code `0x36EEC6`, built by `0xF3918`, run by `0x2013E4`) lists the hostile units, draws `0x1A0CCC(5) + 1` (a sum of three RNG words mod 5, so 1..5) and picks that many DISTINCT random victims, each hit by the evility's action (magic.dat row 10484). D5's Punishing Prophecy (6112, event `0x36F2A4`, `FUN_1401E8750`) draws one victim with `game_rng_draw` and hands it to `path_throw_append_target(ctx, 0, slot)` at `0x1401E8F76`. `wrap_victims` (tag `0xE70024`, that one call) lets the game append its victim, then for a caster (ctx cast entry 0) holding the row draws `game_rng_draw(value)` more victims over the remaining candidates of the game's own list rules (`events_env_kind_of`, object class test, not carried, `events_env_team_of` + `model_team_is_hostile`), at most `0x20` targets. The row keeps its alias to 6112, which is the trigger. Difference: the damage per victim is D5's own action (magic row 21, power 100); D2's row 10484 differs from Plum's 10474 in bytes `+0x112` and `+0x127` which were not decoded.
* Proof `evility/offline_proof_dd2evil2.py` (normal and `--abi`), the real call sites with the game's own T3, `path_throw_append_target`, `events_env_*`, `model_team_is_hostile`; 12 controls each exit 1. Tests `tests/test_dd2evil2.py`. Rows: `tools/build_dd2_innates.py`.

### DD2EVIL3: Disgaea D2 Plume 570 (`kill_counter` + scale `holder_kills`), label `adapted`

Source: the Disgaea D2 `EBOOT.elf` (addresses are its virtual addresses), notes in `Subprojects/Engine-Extensions/DD2EVIL3-REPORT.md`.
D2 rule: each holder has its own u16 `+0x19CE` of defeats it made as the attacker (raised at `0xE9170` inside the hit resolution `0xE81B8`, reset in the unit-data initialiser `0x20F78`); a unit's attack bonus is `value x` the sum of that count over the OTHER same-team holders (`0xF6290` list, `0xFA6CC` sum), capped by the second value byte (`0xF3024(570, 1)`).
* `kill_counter` (second-word bit 8, a predicate row, no effects): `wrap_atkcount` (already at the call of `damage_apply_damage`, `0x1401B1BE0`) adds 1 to the attacker's stat-record short `+0x5D8` when the attacker holds the row and the target was alive before the call and is at 0 HP after it (a Geo Symbol family target, chars 4810..4819, is skipped), and takes back D5's own "+1 on the target" for a holder (`0x1401B2527`). `+0x5D8` is D5's Impact Charge (2065) counter; its readers (`damage_attack_bonus_rules`, the damage breakdown) are behind a "has 2065" test, so a unit without 2065 never reads it. `model_stat_record_wipe` and `FUN_1401620b0` (called by `lifecycle_globals_unit_slots_attach`) zero it.
* scale `holder_kills` (28, needs `filter` = the holder's evility id): sum of `+0x5D8` over the OTHER deployed, uncarried, living units of the subject's team that have learned the filter id. Row shape: `"26304": [{"family": ["power","aura"], "effects": [{"value": 10, "per": "holder_kills", "max": 200}], "filter": 26304, "conditions": [near_has radius 65535]}, {"family": "kill_counter"}]`.
* Label stays `adapted`: D2's object test `0x1035B0` also skips unit types 51/52 (`0x100FE8`), the kit skips the Geo Symbol family only; the reset is D5's stat-record attach/wipe against D2's `0x20F78` (callers not all traced); a skill-id branch at `0xE84E4` was not followed; a defeat is read from HP after the apply.
* Proof `evility/offline_proof_dd2evil3.py` (normal and `--abi`), 12 controls each exit 1; `evility/offline_proof_plume1.py` keeps the old `defeated_any` row as the fixture of the `max` machinery. Tests `tests/test_dd2evil3.py`.

## LONGTAIL2: `max_hp_reflect` (second-word bit 9), Xenolith 80 "The Artifact" (2026-11-14, offline-proven only, adapted)
* **Family `max_hp_reflect`**: a valued predicate row on the DEFENDER (`{"family": "max_hp_reflect", "effects": [{"value": 20}]}`, value 1..100; conditions see
  the defender as subject, the attacker as the other side, the action context). It only acts together with an alias of the same id to D5's Malicious Reflect
  (143): the game's rider block in `FUN_1401ADA40` (per-target, after a hit) searches the defender's list for 0x8F, and at its one `damage_skill_dat` call
  (0x1401AE531) `wrap_maxrefl` (tag 0xE70025) runs the game's own call and, when the sum of the defender's rows is positive, hands back a row whose `+0x38`
  is 100 and puts `maxHP(attacker, unit +0x2CD8) x P / 100` into `rdi`, which the game reads next (`cvtsi2ss xmm0, rdi`) as "the damage taken". The game's own
  arithmetic, clamp (never below 1 HP, attacker's current HP minus 1) and apply (`deploy_env_deploy_env_box_apply_damage(0, attacker, amount, 4)`) then run.
* **Register rule (the one departure from "return everything unchanged")**: `rdi` is non-volatile, and the wrapper's canonical epilogue (`pop rdi`) returns the
  AMOUNT instead of the caller's value on the hit path only (the amount is stored in `rdi`'s saved slot). Safe because the caller reads `rdi` only at 0x1401AE541
  (the instruction we feed) and reassigns it from `[rbx + 0x240]` on both later paths (0x1401AE572 / 0x1401AE582) before any other read. A defender with only the
  real 143 gets the game's row and the caller's `rdi` untouched. The proof (`evility/offline_proof_longtail2_xenolith.py`) checks that every other non-volatile
  register and xmm6-15 survive the call, and that `rdi` is the amount for a holder and the damage taken otherwise. Float arithmetic: the amount goes through
  `float(amount)` (exact below 2^24, a few units of rounding above).
* **Community evidence, not source code**: the percent is of the attacker's max HP per the GameFAQs Disgaea D2 evility list (Dark_Cecil) and the Disgaea wiki; the Disgaea D2 code for the effect was not found. Not carried: the source's conditions.

### LONGTAIL2: `nullify_dealt` (second-word bit 10), Baal Slave 640 "Basic Principles" (offline-proven only, adapted)
* **Family `nullify_dealt`**: a predicate row on the ATTACKER (no effects; conditions see the attacker as subject, the defender as the other side, the action
  context). `wrap_nullify` (the existing wrapper of `damage_nullify_predicate`, four sites) asks it after the game's own answer and the defender's `nullify`
  rows: when the hit's damage `v` is positive and the game's own ally relation puts the defender on the attacker's side, the hit is nullified.
  The relation is the one D5's Softening Aura (2072, id 0x818) tests at the top of `damage_nullify_predicate`: `events_env_team_of(rec, 1)` of both sides
  through `cmdmenu_preds_p_2d8e00(A's team, D's team)` (team groups 0/4, 1/5 and 3; a team-2 unit has no allies), so the two halves of Baal Slave agree with
  each other, including for a charmed unit. (The brief proposed a new condition comparing the two team bytes; the game's own test is the better reading and
  needs no new condition kind.)
* **Row shape** (the same id as the alias): `"26307": {"family": "nullify_dealt"}` + `aliases.json {"26307": 2072}`. The alias gives "allies cannot harm it".
* Not carried: an ally can still be selected and the animation plays, only the damage goes; heals and buffs (damage 0 or less) are untouched; the AI is not told;
  the seven call sites of the predicate that the kit does not redirect see only the game's answer; a hit by the holder on itself counts as an ally hit (as for 2072).
* Proof `evility/offline_proof_longtail2_baal.py` (normal and `--abi`): the real `damage_nullify_predicate` under the kit wrapper at the four redirected sites.

## LONGTAIL3: `self_destruct` (second-word bit 11), Battle Suit 802 "Self-Destruct" (2026-11-14, offline-proven only, adapted)
* **Family `self_destruct`**: a valued predicate row on the DEFENDER (`{"family": "self_destruct", "effects": [{"value": 10}]}`, percent 1..100, one effect).
  `wrap_face_away` (the existing wrapper of `post_hit_effects`, the once-per-action pass of `exec_ctl_s2_update`, 0x14053FE71) walks the action's targets after its
  facing pass and BEFORE the game's own `post_hit_effects`. A target explodes when its result is a positive amount (a real hit: not a miss, a buff, a nullified hit or a
  heal of skill category 4), its KO byte is 0, its record is active, its unit is alive and not already exploding (`+0x11DC == 0`), it holds the row and
  HP `<=` trunc(max HP x percent / 100). The explosion is the game's own `FUN_1401A3E80(unit object, 1)` (the call `carry_land` 0x1406357E0 makes for a landed
  explosive unit): blast of 50% of current HP (`FUN_1401EADC0`), area from `FUN_1402038C0` (defaults 10 and 2), `field_sweep_spawn`, `+0x11DC = 1`, then the unit's own HP
  applied to itself. It reads only the unit object (stat record `+0x240`, position `+8/+0xC/+0x10`), so no throw state is needed; the flag only selects a sound.
* **Source rule (Disgaea 4 decomp)**: `FUN_14010DE70(unit, 0x322, unit+0xD20)` returns the evility value unless `trunc(max HP x percent / 100) < min(HP, max HP)`, i.e. it
  passes when HP `<=` the threshold (at, not strictly below). Its seven callers (the after-action sweep in `FUN_1402EE580` state 0x66 and six after-damage sites) then play
  effect 0x816 and apply the unit's own HP to itself as lethal damage. No damage to other units was found in those sites; the community blast (radius 2, 50% of current HP)
  equals D5's explosion defaults.
* Not carried: D4's six other sites (non-action damage), the after-action sweep of a holder already low (only a unit hit in this action explodes), effect 0x816, the exact blast victims.
* Proof `evility/offline_proof_longtail3.py` (normal and `--abi`): the real site 0x14053FE71 with the native explosion and `post_hit_effects` as recording stubs; the blast is not run offline.

## NECRO1: `raise_zombie` (second-word bit 12), Necromancer 868 "Necromancy" (2026-11-14, offline-proven only, adapted)
* **Family `raise_zombie`**: a flag row (no effects) on the ATTACKER. `evil_necro(ctx, attacker record)` runs in `wrap_face_away`'s once-per-action pass, after the self_destruct loop and before `post_hit_effects`: for each action target whose KO byte is set and HP <= 0, hostile (not team 3), not an object, not Undead (2090..2095), not carried or carrying, with no living unit on its x/z, while `FUN_1401C3A00() < 32`, it calls `unit_spawn_from_request` with a 0x40-byte request (char 2090, victim's level, x/y/z, facing, team: holder 0 -> 4, else the holder's team; holder teams 2 and 3 do nothing) and sets the new unit's HP (+0x2CC8) to 1.
* Source rule: D4 `FUN_1400F2680` is only a marker setter; the zombie is built in `FUN_140302530` via `FUN_1401B9350` (class 0x820, statuses and equipment cleared, side byte 3 or 1). Community (wiki "Necromancer"): 1 HP, no equipment, not controllable. Proof `evility/offline_proof_necro1.py` (62 normal, 62 `--abi`, 12 controls). Spawn, side and AI behaviour are live-needed (see NECRO1-REPORT).

## NEMO1: `summon_malice` (second-word bit 13), Nemo 820 "Physical Malice" (2026-11-14, offline-proven only, adapted)
* **Family `summon_malice`**: a flag row (no effects) on the HOLDER. `evil_nemo(unit record, battle record)` runs from `wrap_revenge` (the one call site 0x1405F8FFC of the round-edge sweep in `turn_ctl_s6_update`, once per active unit per round, all teams): for a living, active holder, while `FUN_1401C3A00() < 32`, `events_clear_pick_cell(0x144BD9750)` rebuilds the free-cell grid (0x144DF1790, as Summon Guardian does), the free cells inside the 21 x 21 square around the holder's cell are counted, and with at least one `game_rng_draw` picks a character from `MALICE_STANDINS` (25 D5 class rows), a level `L*60/100 + rand(40)*L/100` (min 1; D4's own form) and a cell (x outer, z inner scan order); `unit_spawn_from_request` gets the Guardian block's request (x/z = cell*12+6, y from `map_surface_height_at`, facing from `FUN_1401367F0`, team: holder 0 -> 4, else the holder's; holder teams 2 and 3 do nothing).
* Source rule (D4 decomp): `FUN_1402E99D0` is state 3 of the round-edge machine `FUN_1402EA550` (once per round, not per side); it creates the unit with side byte 1 on a random free cell within 10 cells of the holder (`FUN_1402AD4C0`); the 39 Malice rows are char 5330..5368 (tier 9). Community (wiki "Nemo"): one Malice unit every turn. Proof `evility/offline_proof_nemo1.py` (69 normal, 69 `--abi`, 13 controls). Spawn, side and AI behaviour are live-needed (see NEMO1-REPORT).

## NECRO2: Necromancy now queues the victim at the damage apply (2026-11-14, offline-proven only)
* NECRO1 read the victim's battle record at the end-of-action pass (`wrap_face_away`) and made no zombie live (LIVEFX5). Read from the decomp (not yet seen live): `damage_after_hit_evaluate` 0x1401AEB10 sets HP 0 and a 20-tick countdown (+0x2B2); `model_update_sweep_units` 0x1404A8D10 ticks it each frame (`battle_unit_update` 0x14015A1B0) and at 0 retires the unit (`battle_unit_reset` 0x14015B9E0 clears +0x2E8, an enemy-pool record is zeroed), while the action's script is still running; `exec_ctl_s2_update`'s end pass comes after the script. So the victim is normally gone (inactive, record zeroed) at the end pass. NECRO1's proof built it active.
* Fix, no new patch site: `wrap_atkcount` (0x1401B1BE0, after the game's `damage_apply_damage`) calls `evil_necro_note(attacker, target, ctx, index)`: for a holder whose target was alive before the call and now has the ctx KO byte set, HP <= 0, is hostile and not an object / Undead / carried, the victim's cell, facing, level and the zombie's team go into the queue `evil_zq` (16 entries, header = the attacker's record). `evil_necro` (end pass) spawns from the queue (no living unit on the cell, fewer than 32 units) and always empties it. The zombie therefore appears when the action ends.
* Debug counters `evil_zdbg` (16 dwords next to `evil_zq`; addresses from `evility.SECTION_SYMBOLS` after a build, or search the section for the magic qword 0x4556324E45435232 = "EV2NECR2"): 0 note routine entered by a holder, 1 note stored, 2 end pass found this attacker's queue header, 3 skipped (living unit on the cell), 4 spawn called, 5 spawn gave a slot, 6 spawn refused, 7 note dropped (queue full), 8 end pass entered by any attacker, 9 skipped (32 limit). Proof: `evility/offline_proof_necro2.py` (NECRO1's proof is superseded).
