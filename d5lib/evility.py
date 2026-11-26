"""Evilities with behavior of their own (engine extension).

The game decides what an evility does in compiled code: ~1600 sites compare an id against the unit's sorted
learned list (unit+0x2F30, count +0x3030) — see Subprojects/Engine-Extensions/evility/CATALOG.md.  Until now a
new evility could only copy the *effect* of a game one (`d5lib/classes.py`'s alias hook: the game id is inserted
next to it when the list is rebuilt).  This module gives a new id its own behavior for the stat passes:

  unit_stats_evil_potency      (0x1401E1B30)  the eight potency words +0x3068.. that scale equipment stats
  unit_stats_evil_status_effects (0x1401B97D0) the stat aggregate (percent bonuses / penalties)
  unit_stats_evil_growth_bonus (0x1401E9B50)  the level-up growth percentages, per stat

How it works: one table of rows {id, families, condition, effects} is written into a new exe section `.d5el`
together with a small applier.  Each *call site* of the three functions is redirected (5-byte `call` -> `call`
our wrapper); the wrapper calls the original function through the original call, so the game's own code and
its behavior are untouched, and then adds the extension's contribution for ids in the table.  With no ids in
the table the section is not added at all; vanilla ids never match a table row, so vanilla behavior is
identical whether the extension is installed or not.

Why call sites and not the function entries: the entry bytes of these optional functions are prologue
instructions that reference [rsp], so re-entering the function after a detour needs instruction relocation.
Redirecting the `call` needs none and cannot recurse.  The cost is that a call the compiler made indirect
(or a new call site in a game update) would be missed; the build verifies every site's bytes and refuses a
different exe.

Mod data (patches/evilities/evilities.json):
  {"evilities": {
     "7001": {"family": "potency",
              "effects": [{"stat": "atk", "value": 30}, {"stat": "def", "value": -10}],
              "condition": {"kind": "has", "id": 121}}}}
  family: "potency" | "stats" | "growth" | "dealt" | "taken" | "flight" | "hit" | "status_chance"
          | "aura" | "conversion" | "nullify" | "counter", or a list of them.
  effects: stat 0..7 (hp, sp, atk, def, int, res, hit, spd) or "all"; value is added.
           "dealt"/"taken"/"hit"/"status_chance" use one percentage per effect and ignore stat.
  condition (optional) or conditions (a list of them, all of which must hold): see COND_KINDS for the
          whole vocabulary — has/char/count/hp/level/target_class, the battle-context kinds (adjacency,
          map counts, attack type, element, weapon category, statuses, round number, attack direction,
          RNG chance, ailment class, nearby provider) and the flyer/level comparisons.

Stat index order is the game's own: items' eight stats are HP, SP, ATK, DEF, INT, RES, HIT, SPD (item.dat
+8,+16,...), and the potency words scale item stat k, so w[k] is that same stat.  The aggregate indices used
by the status pass are 0 HP, 1 SP, 2..7 ATK..SPD (its own `agg[2..8]` blocks).  This mapping is inferred from
the game's table order and the aggregate blocks, not measured in battle yet.

Damage (EX-05): "dealt" adds percentage points to `damage_damage_multiplier_rules` (the caller composes
100 + the return value), "taken" scales the in/out percent of `damage_damage_reduction_rules` by
(100 + value) %. Conditions apply to the unit the family acts for: the attacker for "dealt", the defender
for "taken"; `target_class` looks at the other side.

Movement (EX-05): "flight" is a predicate with no effects — when the game's own flight test says no, a row
whose conditions hold makes the answer yes. Both copies of that game function are wrapped.

Every family shares one condition evaluator (evil_eval), so a new condition kind applies everywhere.

Chance (EX-05b): "hit" adds percentage points to `damage_hit_chance_rules` (kept in 1..100) and
"status_chance" to `damage_status_chance_rules` (floored at 0); both take their last argument on the stack
like `taken` does.

Evasion (D4SIG5): "evasion" is the defender's side of the same hit-chance pass.  wrap_hit sums the defender's evasion rows (the
action context and the attacker are available to the conditions) and applies them around the game's own call: an effect with
"mode": "points" (D4 Beryl's Servant 1, 844) is subtracted from the percent before damage_hit_chance_rules clamps it to
1..100, an effect with "mode": "after" (DD2EVIL1, DD2 Rapid Movement 1210) is subtracted after the game's own call, so its clamp and
the attacker's rows come first (kept at 1 or more), an effect with the default "scale" (D4 Misty Haze 351, "evade attacks from front") multiplies the finished percent by
(100 - sum) / 100, truncating, kept in 1..100.  D4 does the same in FUN_1400FF700 / FUN_140107100.  One number per effect.

Predicates (EX-06b): "nullify" (damage_nullify_predicate) and "counter" (exec_counter_attack_allow) take
no effects; when the game's own answer is "no", a row whose conditions hold for the *defender* makes it
"yes".  "nullify" is handed the action context at the four sites we redirect; "counter" gets none.

"aura" is not a hook of its own: the row is applied by the *recipient's* potency or aggregate pass and a
`near_has` condition names the provider standing next to it.

Table format 2 (EX-05b): 32-byte rows, a separate condition array (u16 kind, a, b, c) so a row can require
several conditions, and the effect array.  The header is "D5EV" + the format byte.

Round edge (EX-05e): "regen" adds a percentage of maximum HP/SP once per unit inside the game's
own round-edge processor and refreshes the HP-bar shadow itself.  The same pass also carries the
"damage_null" and "ailment_null" predicates (the incoming percent or chance becomes 0), and
"crit_rate" adds percentage points to the critical-rate pass; an aura row may now ride the
damage-time families (dealt/taken/hit/crit_rate) as well as potency/stats.

Not covered yet: event-accumulator magnitudes, Jump amounts, the
command-menu predicates and resource rewards (EXP/HL/mana); see evility/EX05B-REPORT.md,
EX05D-REPORT.md, EX05E-REPORT.md and CATALOG.md.

OLEFFECTS (2026-10-29): four more of Overlord's 24 effects, ported from Cryswar (The Unlicense) with his
vocabulary and site map; the mechanism is this runtime's (CALL redirection at the game's own call sites):
  "permanent_revenge"      predicate.  After the game's own round-edge upkeep for a unit returns, the native
                           revenge pair is issued once: the gauge effect 0x140161A20(unit, 6, brec, 0, 0)
                           and the status set 0x140161790(unit, 0x1A, 99, 99).  A unit that already carries
                           D5's own revenge ids (150, 6145, 5026) is skipped, so the pair is never doubled.
  "block_overload"         predicate.  `cmdmenu_preds_p_15dbf0`, the central unit -> Overload-id resolver
                           battle command availability and execution both ask, answers 0 for the holder,
                           which is the game's own "no Overload" answer: the command is greyed and refused.
  "steal_on_kill_percent"  one number per effect, added to the Cat Burglar (3036) chance the defeat path has
                           accumulated, clamped to 0..100 exactly as Overlord clamps it.  The original
                           victim-eligibility call then runs unchanged.
  "sp_drain_per_turn"      one number per effect, added to the SP-recovery percentage the round-edge HP/SP
                           settlement subtracts: the game then computes drain - (regen + value), so a
                           positive row drains that percent of maximum SP per round and a negative one
                           restores it.
  stat_per_squad_unit needs no family of its own: it is `"family": "stats"` with `"per": "squad"`, counted
                           by the game's own squad helper (0x1401D3990) from the unit's squad assignment
                           (+0x30A0/+0x30A1), exactly as Overlord's count_same_squad_units does.

Additive passes (P3, 2026-10-27): four families format 2 did not carry, ported from Cryswar's Overlord
(Unlicense; effect names `power_percent`, `defense_power_percent`, `move`, `magic_range`) but implemented as
CALL redirection on the game's own rule passes rather than Overlord's entry/mid-function stubs:
  "power"          damage_attack_bonus_rules (0x1401F6300) -- the pre-defence attack-power percent for the
                   attacker (rcx)
  "defense_power"  damage_defence_bonus_rules (0x1401F8700) -- the defence-power percent; its second
                   argument (rdx) is already the defender's unit record
  "move"           menus_env_move_range (0x140157D90) -- the unit's move range in panels (rcx)
  "range"          the attack/magic range bonus getter (0x1401EC5C0) -- vanilla evilities 1033 and 3305
Each wrapper calls the original through its own frame and adds the summed row values to what it returned.
They take one number per effect, no stat, and are handed no action context, so only unit-state conditions
can hold on these rows.  Differences from Overlord's parser, documented rather than hidden: Overlord clamps
each entry to [min, max] (default -50..100); format 2 has no per-row clamp, so the game's own downstream
clamp is what applies.  Values are signed 16-bit as in every other family.

Several rows per evility id (P3b, 2026-10-27): a mod entry may be a *list* of rows instead of one row
  {"evilities": {"176": [{"family": "move", "effects": [{"value": 3}]},
                         {"family": "potency", "effects": [{"stat": "all", "value": -30}]}]}}
so one evility can change two different numbers, or one family with two different conditions.  This is
Overlord's own model -- its `evilities.ini` sections are `[<id> <label>]`, one effect per section, and every
applier sums the sections whose id the unit carries -- chosen over tagging each effect with a family byte
because it also gives each effect its own conditions, and because the row layout does not change: the table
is still format 2, a legacy one-row-per-id table decodes and behaves exactly as before, and evil_next simply
emits the whole run of rows that share an id.  Effects stay additive across the run, per row.

Runtime magnitudes (EX-05d): an effect may carry "per" instead of a fixed value.  The row's
value is then multiplied by a count the extension computes itself -- the same 256-entry
battle-unit scan the adjacency conditions use, or the action's own target-entry count.
Fixed effects keep byte 2 of the effect's stat word clear, so an existing table reads
exactly as it did.

Skill rules (EX-06): a row can also be keyed by a *skill* instead of an evility.  Mod data is a
separate file (patches/skillrules/skillrules.json, {"rules": {...}}) but it goes into the same
table, section and evaluator: the row's id is a magic.dat skill id and it applies when the
*action* uses that skill, so it needs no learned evility on either side.  Only the damage-time
families are allowed (dealt/taken/hit/status_chance; potency/stats/growth/aura/conversion/flight
are not damage-time passes and never see an action context).  This is where a D4 skill or evility
keeps a compiled rule D5 does not have -- e.g. Aegis, whose D4 row (mskill.dat +13) stores 30 and
whose rule is "damage taken is scaled by 70 % when the attacker stands in front":
  {"rules": {"392": {"family": "taken", "effects": [{"value": -30}],
                     "conditions": [{"kind": "attack_dir", "id": 0}]}}}
Skill rows are never reached by evil_next (they are in no unit's learned list), so
evil_dmg_sum scans them through its own index after the ordinary rows; see docs/SKILL_RULES.md.

D4REV2 (D4 batch-1: make four D4 evilities play D4's own number, offline):
  * condition 47 `defending` -- the unit is in the game's own defending state, tested exactly the way
    D5's own Advance Guard (1152) tests it: `path_query_path_unit_stack_count(battle record) != 0`
    inside damage_damage_reduction_rules (0x1401FB2E0).  D4 391 Advance Guard (80 %) is therefore
    row 8391 `{"family": "taken", "effects": [{"value": -80}], "condition": {"kind": "defending"}}`.
  * `attack_dir` on a `taken` row now works: the condition used to look the action's target entry up by
    the *other* side's battle slot, which never matches when the subject IS the target.  It now tries
    the other side first and falls back to the subject's own slot (`evil_brec(unit)+0x2F4`), so D4 392
    Aegis is row 8392 `{"family": "taken", "effects": [{"value": -30}],
    "conditions": [{"kind": "attack_dir", "id": 0}]}` (front only; side/behind do not match).
  * scales 7 `defeated_enemy` / 8 `defeated_any` -- the battle's own six defeated-unit counters at
    0x146A5F054 (indexed by the defeated unit's team, incremented when its HP reaches 0).  7 sums the
    teams hostile to this unit's team, 8 sums all six (D5's own 140 Queen of Coffins arithmetic).  D4
    347 Bloody Battle is row 8347 `{"family": "stats", "effects": [{"stat": "atk", "value": 5,
    "per": "defeated_enemy"}]}`.
  * family 1048576 `absorb` -- D4 815 Absorption (10 %) is row 8815 `{"family": "absorb",
    "effects": [{"value": 10}]}`.  D5's own 6032 is the same mechanic at 20 %: FUN_140200D20 (the death
    pass, called from damage_after_hit_evaluate) stores value % of the defeated unit's six stats in the
    absorber's stat record (+0x5A8, six qwords), and unit_stats_evil_overrides (0x1401EEE30) adds that
    accumulator to the maxima while the unit carries 6032.  The extension wraps both: its own wrapper
    writes our percentage into the same accumulator, and the overrides wrapper (which already carries
    the conversion family) re-applies it for a unit carrying an absorb row.

EX-06b: the ailment pass gets no action context of its own, so wrap_achance (a wrapper on
damage_buff_ailment_chance, whose first argument is the ActionContext at all four of its call
sites) records that pointer in evil_ctx while the call runs and wrap_astat reads it back.  A
status_chance skill row therefore matches and evaluates action-context conditions like the other
three families; outside a wrapped call evil_ctx is 0 and a skill row never matches.

CARRIERS2 (2026-10-30): filtered map counts, the largest single gap in the D4 content map -- the
number of *units of a kind* deployed, as a magnitude.  D4 states it five different ways (Pink's
Meowyland "+10 % x the number of cat-type units on the map", the Orc family's Mass Psyche
"per same species unit", Beast Tamer's Dark Blood "per monster unit on map", Prism Emblem "if seven
allies with Prism Emblem are dispatched", Fuka's Prinny Annihilation "x the number of defeated
Prinnies") and the runtime could only count "any unit / ally / enemy" before.  Three pieces:
  * scale 11 map_monster / 12 map_human -- the class-kind byte (unit +0x2E25: 1 human male,
    2 human female, 11 monster male, 12 monster female) decides; the subject is never counted.
  * scale 13 map_class / 14 map_has -- the row's filter (`"filter": <id>`, or `"classes": [...]`
    expanded by the emitter into one row per id) selects by class/character id (unit +0x2E04, the
    same field `near_char` tests) or by a learned evility id.
  * condition 49 map_has_min -- "at least a units of relation b have learned evility c", the counted
    form of near_has (26), which is only existential.
All of it rides evil_near's existing 256-entry deployed-unit walk, so "on the map" means exactly what
it means for map_any/map_ally/map_enemy: on the map, carrying nobody, with a stat record.

EVILFX1 (2026-11-10): scale 15 map_squad -- deployed allies in the subject's own squad (evil_near filter
kind 5).  D4 counts "dispatched Evil Area allies" (Friends 840) in its stat aggregate FUN_1401ba0a0: other
battle units of the holder's team whose Evil Area list meets the holder's, never the holder.  D5 replaced
Evil Areas with squads, so rows written with it are labelled adapted.  The same D4 loop also settles the
CARRIERS2 question for Meowyland 837: the holder's own record is skipped before any count is taken.

EVILFX1: family 1<<26 rearm_first_damage -- a per-turn counter without new state.  D5's First Impression
(6047) nullifies damage while stat record byte +0xDF9 is 0 and damage_apply_damage sets it on the unit's first
damage of the stage.  The round-edge wrapper (wrap_revenge, site 0x1405F8FFC) clears that byte for a unit
with a holding row; paired with a class alias to 6047 that is D4 Tyrant Guard 667 ("nullify the first damage
received every turn"; D4 resets its own per-unit counter +0x1183 in the per-unit turn upkeep FUN_1400f3c20).
"""
import json
import os
import struct

from .exepatch import add_code_section, code_base
from .gamefs import EXE_FILE
from .modsys import register_finalizer, register_patch_handler

FOLDER = "evilities"
DATA_FILE = "evilities.json"
# EX-06: skill-scope rules live in their own mod folder and file, but in the *same* table, section and
# evaluator: a skill row keys its id against the action's skill id instead of a unit's learned list.
SKILL_FOLDER = "skillrules"
SKILL_DATA_FILE = "skillrules.json"
SECTION_NAME = b".d5el"
HERE = os.path.dirname(os.path.abspath(__file__))
ASM_FILE = os.path.join(HERE, "native", "d5evil.inc.asm")

F_POTENCY, F_STATS, F_GROWTH = 1, 2, 4
F_DEALT, F_TAKEN, F_FLIGHT = 8, 16, 32
F_AURA, F_HIT, F_STATUS = 64, 128, 256
F_CONVERSION = 512
# EX-05e: critical-rate points, round-edge HP/SP regeneration, damage nullification and
# ailment immunity.
F_CRIT, F_REGEN, F_DAMAGE_NULL, F_ASTAT_NULL = 1024, 2048, 4096, 8192
# EX-06b: predicate families -- the hit is nullified / the defender may counter.  EX-05e already
# holds 1024..8192, so these continue at 16384 (the mask word is u32).
F_NULLIFY, F_COUNTER = 16384, 32768
# P3: the four additive passes format 2 did not carry -- attack power (Overlord `power_percent`),
# defence power (`defense_power_percent`), move range (`move`) and attack/magic range (`magic_range`).
# The mask word is u32, so these continue at 65536.
F_POWER, F_DPOWER, F_MOVE, F_RANGE = 65536, 131072, 262144, 524288
# D4REV2: absorption of a defeated unit's stats (D5's own 6032 is this mechanic at 20 %).  It is a
# two-step mechanic -- the death pass stores the share in the stat record, the overrides pass adds it to
# the maxima -- so the family is applied by a wrapper of its own plus the overrides wrapper, and it
# cannot combine with another family.  The mask word is u32, so it continues at 1048576.
F_ABSORB = 1048576
# OLEFFECTS (2026-10-29): four more of Overlord's effects, ported from Cryswar's Overlord (The Unlicense;
# effect vocabulary and site map are his, the mechanism -- CALL redirection at the game's own call sites --
# is this runtime's).  The mask word is u32, so these continue at 2097152.
F_REVENGE, F_OVERLOAD, F_STEAL, F_SPDRAIN = 2097152, 4194304, 8388608, 16777216
F_RESISTANCE = 33554432
# EVILFX1: re-arm D5's own First Impression (6047, "nullify the very first damage taken on a stage") at every
# round edge, so a unit that also carries 6047 (class alias) nullifies the first damage of every turn.
F_REARM = 67108864
# DRPGEVIL1b: critical damage.  D5's own Purgatory (1222, "increase damage dealt by criticals by 50 %") is a
# test inside damage_damage_reduction_rules: on a critical hit (action context target entry + 0x152A) the
# value is multiplied by (100 + v) / 100 for the attacker's evility.  The family does the same for the
# attacker's rows inside the existing `taken` wrapper (no new call site), after the defender's rows.
F_CRITDMG = 134217728
# EVILCAP1: the percent of the damage an attack also inflicts to the target's SP.  D5's own Habitual Licker (3011)
# reads its percent from its Skill row (+0x38) in FUN_1401ADA40; wrap_spdmg hands that code our sum instead, so the
# row only acts while the attacker also carries 3011 (alias the row's id to it).  Attacker subject, target and
# action context available to the conditions.
F_SPDMG = 268435456
# D4SIG3: percent boost of support magic (D4 Medical Insertion 304: value x (100 + 50) / 100).  wrap_support runs the game's own
# FUN_1401FEFA0 (D5's integer Medical Insertion 1180 multiply) and, for a caster with these rows, replaces its result.
F_SUPPORT = 536870912
# D4SIG4: weapon-slot percent (D4 Everyone's Mechanic 892: the item stat of a weapon slot x (100 + percent) / 100, the percent summed
# over allies and capped at 100).  wrap_equip runs the game's own unit_stats_equip_stat and scales the result of a weapon-category
# slot; an aura row (near_has) gives the percent to the recipient, a plain row to its own holder.
F_WEAPON = 1073741824
# D4SIG5: evasion of the DEFENDER's hit chance (D4 Beryl's Servant 1 / Misty Haze).  wrap_hit applies it around the game's own
# damage_hit_chance_rules: "points" effects are subtracted before the game's clamp, "after" effects after the game's call, "scale" effects multiply the finished percent
# by (100 - sum) / 100.  Bit 31, the last free bit of the u32 mask word.
F_EVASION = 2147483648
FAMILIES = {"potency": F_POTENCY, "stats": F_STATS, "growth": F_GROWTH,
            "dealt": F_DEALT, "taken": F_TAKEN, "flight": F_FLIGHT,
            "aura": F_AURA, "hit": F_HIT, "status_chance": F_STATUS,
            "conversion": F_CONVERSION, "crit_rate": F_CRIT, "regen": F_REGEN,
            "damage_null": F_DAMAGE_NULL, "ailment_null": F_ASTAT_NULL,
            "nullify": F_NULLIFY, "counter": F_COUNTER,
            "power": F_POWER, "defense_power": F_DPOWER, "move": F_MOVE, "range": F_RANGE,
            "absorb": F_ABSORB,
            # Overlord's effect names, so content can be carried over verbatim:
            #   permanent_revenge      -> the unit enters Revenge mode every round edge (D5's own
            #                             Endless Animosity 150 / 6145 / 5026 pair, issued natively)
            #   block_overload         -> the unit has no Overload id, so the command is greyed and refused
            #   steal_on_kill_percent  -> the Cat Burglar (3036) defeat-path steal chance
            #   sp_drain_per_turn      -> percent of maximum SP drained at the round edge
            "permanent_revenge": F_REVENGE, "block_overload": F_OVERLOAD,
            "steal_on_kill_percent": F_STEAL, "sp_drain_per_turn": F_SPDRAIN,
            "element_resistance": F_RESISTANCE,
            # EVILFX1: clear the unit's 6047 "already damaged this stage" byte at each round edge
            "rearm_first_damage": F_REARM, "crit_damage": F_CRITDMG,
            # EVILCAP1: replaces Habitual Licker's 25 % (the row's id aliased to 3011)
            "sp_damage_percent": F_SPDMG,
            # D4SIG3: support-magic effect x (100 + percent) / 100 (Chief, Medical Insertion)
            "support_magic_percent": F_SUPPORT,
            # D4SIG4: weapon-slot item stats x (100 + percent) / 100 (Nagi, Everyone's Mechanic)
            "weapon_percent": F_WEAPON,
            # D4SIG5: defender-side hit-chance evasion (effect "mode": "scale" (default) or "points")
            "evasion": F_EVASION}
FAMILY_NAME = {F_POTENCY: "potency", F_STATS: "stats", F_GROWTH: "growth",
               F_DEALT: "dealt", F_TAKEN: "taken", F_FLIGHT: "flight",
               F_AURA: "aura", F_HIT: "hit", F_STATUS: "status_chance",
               F_CONVERSION: "conversion", F_CRIT: "crit_rate", F_REGEN: "regen",
               F_DAMAGE_NULL: "damage_null", F_ASTAT_NULL: "ailment_null",
               F_NULLIFY: "nullify", F_COUNTER: "counter",
               F_POWER: "power", F_DPOWER: "defense_power", F_MOVE: "move", F_RANGE: "range",
               F_ABSORB: "absorb",
               F_REVENGE: "permanent_revenge", F_OVERLOAD: "block_overload",
               F_STEAL: "steal_on_kill_percent", F_SPDRAIN: "sp_drain_per_turn",
               F_RESISTANCE: "element_resistance", F_REARM: "rearm_first_damage",
               F_CRITDMG: "crit_damage", F_SPDMG: "sp_damage_percent",
               F_SUPPORT: "support_magic_percent", F_WEAPON: "weapon_percent",
               F_EVASION: "evasion"}
STAT_FAMILIES = (F_POTENCY, F_STATS, F_GROWTH, F_RESISTANCE)
# families whose effects are one percentage per effect (no stat field)
PERCENT_FAMILIES = (F_DEALT, F_TAKEN, F_HIT, F_STATUS, F_CRIT, F_CRITDMG)
# OLEFFECTS: the two single-number accumulators ported after P3.  They take one number per effect, no stat,
# and their consumers are handed neither the action context nor the other side, so only unit-state
# conditions can hold on them; each is applied by its own wrapper, so it cannot carry a second family.
# EVILCAP1: sp_damage_percent is one more such number (its wrapper does hand it the target and the action context).
STACK_FAMILIES = (F_STEAL, F_SPDRAIN, F_SPDMG, F_SUPPORT, F_EVASION)
# every family whose effect is one bare number (a percentage or a count) rather than a stat k
NUMBER_FAMILIES = PERCENT_FAMILIES + STACK_FAMILIES
# P3: families whose value is added to a number the enclosing game function returns.  One number per effect,
# no stat, and no action context: their consumers are handed neither the other side nor the action, so only
# unit-state conditions can hold on these rows (Overlord's own note for defense_power_percent says the same).
ADD_FAMILIES = (F_POWER, F_DPOWER, F_MOVE, F_RANGE, F_WEAPON)
DAMAGE_FAMILIES = PERCENT_FAMILIES
# families whose row is the effect and carries no effects at all
PREDICATE_FAMILIES = (F_FLIGHT, F_DAMAGE_NULL, F_ASTAT_NULL, F_NULLIFY, F_COUNTER,
                      F_REVENGE, F_OVERLOAD, F_REARM)
# families an aura row may act through: the per-unit passes (potency/aggregate) and the
# damage-time passes, all of which are handed the recipient and can run the recipient's
# provider test.
AURA_FAMILIES = (F_POTENCY, F_STATS, F_DEALT, F_TAKEN, F_HIT, F_CRIT, F_RESISTANCE,
                 F_CRITDMG, F_REGEN, F_POWER, F_WEAPON)
# PLUME1: effect stat bit24; only evil_dmg_sum consumers decode the packed capped value.
FX_MAX = 1 << 24
# EVILFX2: conditions that walk the battle table themselves.  A regen aura effect with "base": "provider" reads
# the unit its row's near_has matched last, so such a row may carry exactly one of these: its near_has.
MAP_WALK_KINDS = {"ally_adj", "enemy_adj", "ally_map", "enemy_map", "unit_map", "near_has", "near_char",
                  "map_has_min", "party_min", "map_buff_min", "map_debuff_min", "enemy_map_max",
                  "side_top", "side_bottom", "party_weapons_distinct", "map_hp_at_or_below"}
# Row flag word (+24).  A skill row's id is a magic.dat skill id and the row applies when the *action* uses
# that skill, so it needs no learned evility and works for either side of the damage maths.
ROW_SKILL = 1
# MASKWIDE1: the u32 family mask (+4) is full, so more families live in a SECOND family word: flags (+24) bits 8..31.
# A second-word family is a predicate row (mask 0, no effects, evility scope, never an aura): its row is its presence plus
# its conditions.  EXT_FAMILIES maps a name to its bit number 0..23; the runtime asks for one with a 64-bit query
# (`mov rdi, bit << 32`, EXT_QUERY(name)) -- every older query is a 32-bit `mov edi, N` and so has a zero high half.
# Rows with mask != 0 encode exactly as before (flags bits 8+ are 0).
# face_target_away (D4 Death Saber 836 / 0x344): the first second-word family.  After an action's script has ended, every target
# that is still standing and adjacent to the attacker is turned to face directly away from it (wrap_face_away).
# DRPGSIG1: enemy_heal_percent (DRPG Seraphina XENO, "all enemies' healing -35%"): the one second-word family that carries a number.  The
# holder's row says "units hostile to me receive heals reduced by value percent"; wrap_healmod walks the battle table for holders
# hostile to the healed unit (D5's own Evil Spirit 141 rule, FUN_1401FFF40, which takes its 50 from the vanilla row).
# D4SIG7: attack_counter (D4 Dragon, Rising Dragon 663): a predicate row that makes D5's own Impact Charge counter (stat record +0x5D8,
# read by damage_attack_bonus_rules for evility 2065) count exactly as D4's per-unit counter (unit +0x20D5) does: +1 per action target the
# unit is (a miss and a buff count, a heal does not), at most 20, back to 0 when the unit itself finishes an action.  wrap_atkcount adds,
# wrap_face_away (the once-per-action pass) resets.  Pair it with an alias of the same row id to 2065, which does the reading.
# DRPGSIG2: invincible_hits (DRPG Cheshire Cat Majorita, "invincible for 2 hits at battle start"): a second-word family with a number N (1..100).
# The DECISION is read in the nullify predicate (wrap_nullify, at the two sites whose hits damage_apply_damage's wrapper also sees): while the
# holder's count (stat record byte +0xDF9, D5's own First Impression "took damage" byte, used as a count for holders only) is below N, a hit
# with positive damage is nullified and marked pending in the kit's evil_pend table; the COUNT is raised only by wrap_atkcount, after the
# real damage_apply_damage, for a pending, nullified, connected, non-buff hit.  A forecast reads the decision and writes only the mark.
# D4SIG10: special_seal (D4 Roc, Miasma of Silence 115): a predicate row.  A unit with an adjacent (game footprint test, distance 1), hostile,
# living, non-object unit that holds the row is treated as standing on D5's own Silence geo effect for the "Skill" command (wrap_roc_geo, the
# column-10 read of cmdmenu_preds_p_156820) and cannot use a skill of class 0, 1 or 2 anywhere (wrap_roc_skill, the four calls of
# cmdmenu_env_stat_row_can_use_skill: menu, AI, executor).
# DD2EVIL2: three more valued second-word families (Disgaea D2 evilities, each with its one number in the row).
# ally_move (bit 5, Pleinair 320 "Increase movement of ally units by 1"): wrap_move adds the row value of every OTHER deployed unit of the unit's
# team that holds it (D2 0xF6290 skips the unit itself).  move_heal_percent (bit 6, Lilliel 420 "Ally units (including self) recover 2% HP per
# panel they move"): evil_move_heal, run by wrap_endturn before turn_t3 zeroes the panels-moved word, heals the unit value% of its max HP per
# panel moved when the team (itself included) holds the row.  random_victims (bit 7, Alex 480 "Deal damage to a random number of enemy units at
# end of turn", 5): wrap_victims at D5's own Punishing Prophecy append, which adds game_rng_draw(value) more distinct random hostile victims.
# DD2EVIL3: kill_counter (Disgaea D2 Plume 570 "Brave Battle Princess"): a predicate row (no effects) that makes D5's stat record short +0x5D8 the
# holder's own count of defeats it made as the attacker (D2 +0x19CE, raised at 0xE9170).  wrap_atkcount adds 1 after the real damage_apply_damage
# when the attacker holds the row and the target went from alive to defeated in that apply, and takes back D5's own "+1 on the target" for a
# holder.  The scale holder_kills (28, `filter` = the holder's evility id) sums that count over the OTHER same-team holders.  It shares the id
# of the aura row it feeds: `"26304": [{aura row}, {"family": "kill_counter"}]`.
# LONGTAIL2: max_hp_reflect (bit 9, Disgaea D2 Xenolith 80 "The Artifact", 20): a valued predicate row on the DEFENDER.  Paired with an alias of
# the same id to D5's Malicious Reflect (143), wrap_maxrefl (the game's one damage_skill_dat call for 143, 0x1401AE531) makes the rider
# hurt the attacker by value percent of the ATTACKER's max HP instead of 10 percent of the damage taken.  Whose max HP is a reading.
# nullify_dealt (bit 10, Disgaea D2 Baal Slave 640 "Won't target allies when attacking, and won't be targeted by allies"): a predicate row on the ATTACKER
# (conditions see the attacker as subject, the defender as the other side, the action context).  wrap_nullify, after the game's own answer and the
# defender's rows, nullifies a hit with positive damage when the game's own ally relation (D5's Softening Aura 2072 test: events_env_team_of(rec, 1)
# through cmdmenu_preds_p_2d8e00) says the defender is on the attacker's side.  The other half, "won't be targeted by allies", is an alias of the same
# id to Softening Aura 2072.  The ally is still selectable and the animation plays; only the damage is removed.
# LONGTAIL3: self_destruct (bit 11, Disgaea 4 Battle Suit 802 "Self-destruct when HP hits below 10% by an attack"): a valued predicate row (percent)
# on the DEFENDER.  wrap_face_away, in the once-per-action pass (before post_hit_effects), calls D5's own explosion FUN_1401A3E80(unit, 1) for
# each action target that took a real hit (positive result, not a heal) and is left alive with HP <= trunc(max HP x percent / 100): D4's own test.
# NECRO1: raise_zombie (bit 12, Disgaea 4 Necromancer 868 "Bring back defeated enemies as zombies and use them"): a flag row on the ATTACKER.
# wrap_face_away's once-per-action pass calls evil_necro for each action target the holder defeated in that action (KO byte set, HP <= 0, hostile,
# not an object / Undead / carried, no living unit on its cell, fewer than 32 living units) and has unit_spawn_from_request build a D5 Undead
# (char 2090) of the victim's level on the victim's cell on the holder's side (team 0 -> 4, the AI-run friendly team), HP set to 1.
# NEMO1: summon_malice (bit 13, Disgaea 4 Nemo 820 "Physical Malice", "Summon a Malice unit to the map on every turn"): a flag row on the HOLDER.
# wrap_revenge (the one call site 0x1405F8FFC of the round-edge sweep in turn_ctl_s6_update, once per unit per round) calls evil_nemo for each
# active, living holder: while fewer than 32 units live, a free cell of the game's own placement grid (events_clear_pick_cell, as Summon Guardian
# does) within 10 cells of the holder gets one unit drawn from MALICE_STANDINS at level L*60/100 + rand(40)*L/100 (D4's own integer form, at least 1)
# on the holder's side (team 0 -> 4 as NECRO1).
EXT_FAMILIES = {"face_target_away": 0, "enemy_heal_percent": 1, "attack_counter": 2, "invincible_hits": 3, "special_seal": 4,
                "ally_move": 5, "move_heal_percent": 6, "random_victims": 7, "kill_counter": 8, "max_hp_reflect": 9,
                "nullify_dealt": 10, "self_destruct": 11, "raise_zombie": 12, "summon_malice": 13}
# NEMO1: the Disgaea 5 character ids evil_nemo draws from: for 25 of the 39 Disgaea 4 Malice classes (char 5330..5368, "Malice <class>") the D5 native
# class row of the same class / monster family (tier 0 row); the other 14 (Beast Master, Bouncer, Masked Hero, Onmyo Monk, Battle Suit, Android, Spirit,
# Marionette, Roc, Death, Mystic Beast, Dragon Zombie, Wood Golem, Rifle Demon) have no D5 counterpart and are left out.
MALICE_STANDINS = (1010, 1020, 1030, 1040, 1080, 1090, 1110, 1120, 1130, 1140, 1150, 1160, 1180, 1260,
                   2010, 2030, 2060, 2070, 2080, 2090, 2100, 2110, 2120, 2140, 2180)
EXT_VALUE_FAMILIES = ("enemy_heal_percent", "invincible_hits", "ally_move", "move_heal_percent", "random_victims", "max_hp_reflect",
                      "self_destruct")
EXT_SHIFT = 8
EXT_BITS = 24


def ext_query(name):
    """the 64-bit family query of a second-word family (what the asm loads into rdi / rdx)"""
    return 1 << (EXT_FAMILIES[name] + 32)
# the families a skill rule may name: the damage-time ones whose consumers can be handed the action
# context (dealt, taken, hit, status_chance).  potency/stats/growth/aura/conversion/flight are not
# damage-time passes and get no action context at all, so a skill row can never match there.
# `nullify` is handed the action context at the four call sites EX-06b redirects, so it is a skill
# family too; `counter` (exec_counter_attack_allow) gets none, so it is not.
SKILL_FAMILIES = (F_DEALT, F_TAKEN, F_HIT, F_STATUS, F_NULLIFY)
STATS = {"hp": 0, "sp": 1, "atk": 2, "def": 3, "int": 4, "res": 5, "hit": 6, "spd": 7}

# Runtime magnitude (EX-05d): byte 2 of an effect's stat word selects a count the extension computes.
# 0 is a fixed value and is what every pre-EX-05d row carries.  The names are what a mod's JSON uses.
SCALES = {
    "adjacent_ally": 1,     # allies within one panel (4-neighbour), not counting the unit itself
    "adjacent_enemy": 2,
    "adjacent_any": 3,
    "map_ally": 4,          # allies deployed anywhere on the battle map
    "map_enemy": 5,
    "map_any": 6,
    # D4REV2: the battle's own defeated-unit counters (the six u16 slots at 0x146A5F054, indexed by the
    # defeated unit's team, zeroed by battle_start_common, incremented by damage_after_hit_evaluate).
    # "defeated_enemy" sums the teams hostile to this unit's team (the thing a "per defeated enemy"
    # evility means); "defeated_any" sums all six, which is exactly what D5's own Queen of Coffins (140)
    # multiplies by inside damage_attack_bonus_rules.
    "defeated_enemy": 7,
    "defeated_any": 8,
    # OLEFFECTS: the active-member count of the unit's own squad, asked of the game's own helper
    # (0x1401D3990, the one vanilla Heart of a Leader uses).  A unit with no squad assignment counts 0.
    # This is Overlord's `stat_per_squad_unit` scale.
    "squad": 9,
    # D5's own battle-unit movement counter; this is movement cost, not proven source-game panels.
    "movement_cost": 10,
    # CARRIERS2: filtered map counts -- the same deployed-unit scan and "on the map" rule as the map-wide
    # counts above, keeping only the candidates a filter admits.  The filter is the row's own argument
    # (row dword 7, `"filter"` in the mod data).  One value per row, so a species that is several class
    # ids is several rows, and like every other multi-row evility they add up.
    #   11 map_monster  deployed monsters (class-kind byte 11/12); no filter value
    #   12 map_human    deployed humans (class-kind byte 1/2); no filter value
    #   13 map_class    deployed units whose class/character id (unit +0x2E04) is `filter`
    #   14 map_has      deployed units that have learned the evility in `filter`
    # The subject itself is never counted (evil_near's rule), so a holder that would also match its own
    # filter is not part of its own count -- content must not rely on the holder counting itself.
    "map_monster": 11,
    "map_human": 12,
    "map_class": 13,
    "map_has": 14,
    # EVILFX1: deployed allies in the subject's own squad (+0x30A0 id, +0x30A1 gate; the subject is never
    # counted, a subject outside any squad counts 0).  D4's Evil Area membership count ("x the # of
    # dispatched Evil Area allies", Friends 840) mapped onto D5's squads: an adaptation, label rows so.
    "map_squad": 15,
    # DRPGEVIL1c: members of the unit's OWN SIDE on the map of a kind, the unit itself included (Disgaea RPG's
    # "x the number of humanoid characters in the party" counts the holder; every count above leaves the
    # subject out).  party_weapon reads the row's `filter` = item category of an equipped weapon.
    "party_human": 16,
    "party_monster": 17,
    "party_male": 18,
    "party_female": 19,
    "party_weapon": 20,
    # EVILFX2: living members of the unit's own side on the map, the unit included, capped at the row's
    # `filter` (Disgaea RPG "the more living party members ..., up to 5 characters": value = max / cap).
    "party_capped": 21,
    # EVILFX2 percent scales: the unit's hp as a whole percent of its maximum (0..100), or 100 minus it.  The
    # effect adds value * percent / 100, so `value` is the bonus at full (hp_pct) or at zero (hp_lost_pct)
    # hp.  Disgaea RPG "the lower the HP, the higher DEF/RES (max +70 %)"; the linear step is D5's own
    # arithmetic for Power of Adversity (2175) and Super Guts (1015).
    "hp_pct": 22,
    "hp_lost_pct": 23,
    # EVILCAP1: map_class restricted to one relation -- deployed units of the class id in `filter` on the unit's own
    # team (24) or on a team hostile to it (25), the subject never counted.  D4 Phantom Lover (875) counts Spirit
    # units of the holder's own team (FUN_1401ba0a0: local_128[team byte], holder skipped).
    "map_class_ally": 24,
    "map_class_enemy": 25,
    # D4SIG2: D5's own idle-turn counter (stat record byte SR+1, 0..10), the game's closest thing to D4 Stone Statue's
    # "every turn of not moving": D5 also clears it for other blockers, so it is a labelled approximation.
    "idle_turns": 26,
    # D4SIG7: the number of distinct colours among the Geo Symbols alive on the map (family chars 4810..4819, colour byte unit +0x2E2C,
    # raw values 0..6 in the game's maps, 0 = clear counts as a colour exactly as D4's FUN_1401BA0A0 counts its raw record colour).
    # D4 Psylos's Geo Energy (129): "Stats increased by 10% per Geo Block color on map".  0 for a holder off the map or carried.
    "geo_colours": 27,
    # DD2EVIL3: the sum, over every OTHER deployed, uncarried, living unit of the subject's team that has learned the evility in `filter`, of its
    # kill_counter count (stat record +0x5D8).  Disgaea D2 Plume 570: 0xF6290 lists the other same-team holders and 0xFA6CC sums their +0x19CE.
    "holder_kills": 28,
}
# the scales that read the row's filter argument
FILTER_SCALES = {13: "map_class", 14: "map_has", 20: "party_weapon", 21: "party_capped", 28: "holder_kills",
                 24: "map_class_ally", 25: "map_class_enemy"}
TYPE_SCALES = {11: "map_monster", 12: "map_human"}
# conversion sources: the eight base stats plus the unit's *current* SP (EX-05d).  Written as a
# literal so the emitter's static reader can resolve it without executing this module.
CONVERSION_SOURCES = {"hp": 0, "sp": 1, "atk": 2, "def": 3, "int": 4, "res": 5, "hit": 6, "spd": 7,
                      "sp_current": 8}

# Condition kinds (table format 2).  A row carries a *list* of them, all of which must hold.
#   arg a is the id / count / percent / index, b and c are extra arguments for the kinds that need them.
COND_KINDS = {
    "none": 0,
    "has": 1,               # another evility is learned as well            a = evility id
    "char": 2,              # this character id                             a = char id
    "count": 3,             # at least a learned evilities
    "hp_below": 4,          # hp % strictly below a
    "hp_above": 5,          # hp % at least a
    "level": 6,             # level at least a
    "target_class": 7,      # the other side's class: its class id (char.dat id, unit record +0x2E04)
    # --- battle-context conditions (EX-05b) ---
    "ally_adj": 8,          # at least a allies within 1 panel (no diagonal)
    "enemy_adj": 9,         # at least a enemies within 1 panel
    "ally_map": 10,         # at least a allies on the map (not counting this unit)
    "enemy_map": 11,        # at least a enemies on the map
    "unit_map": 12,         # at least a units on the map (any relation, not counting this unit)
    "attack_normal": 13,    # the action is a normal attack (no skill id in the action context)
    "attack_skill": 14,     # the action uses a skill
    "attack_phys": 15,      # skill effect type physical (2), or a normal attack
    "attack_magic": 16,     # skill effect type magic (3)
    "element": 17,          # attack element: 0 none, 1 fire, 2 wind, 3 ice, 4 star
    "weapon": 18,           # an equipped weapon has this category (1..9)
    "target_status": 19,    # the other side carries status a (index into its 77 status slots)
    "self_status": 20,      # this unit carries status a
    "turn_min": 21,         # the battle round counter is at least a
    "attack_dir": 22,       # a = where the attacker stands relative to the target's facing, as the
                            #     action context already computed it (target entry +36):
                            #     0 front, 1 side, 2 behind
    "rng": 24,              # a percent chance: one game RNG draw(100) < a
    "status_class": 25,     # the ailment being rolled is status a (status-chance family only)
    "near_has": 26,         # at least one unit within b panels of relation a (0 any, 1 ally,
                            # 2 enemy) carries evility c
    "other_fly": 27,        # the other side's movement type is flying
    "self_fly": 28,         # this unit's movement type is flying
    "other_level_higher": 29,   # the other side's level is higher than this unit's
    "other_level_lower": 30,    # the other side's level is lower than this unit's
    "other_human": 31, "other_monster": 32, "other_male": 33, "other_female": 34,
    "self_human": 35, "self_monster": 36, "self_male": 37, "self_female": 38,
    # --- EX-05d ---
    "other_hp_below": 39,   # the other side's hp percent is strictly below a
    "other_hp_above": 40,   # the other side's hp percent is at least a (100 = full)
    "element_any": 41,      # the attack carries any element (1..4); false for element 0
    "target_count": 42,     # the action has exactly a target entries
    "target_count_min": 43, # the action has at least a target entries
    # --- EX-05e ---
    "near_char": 44,        # at least one unit of relation a (0 any, 1 ally, 2 enemy) within b panels
                            # has character id c
    "other_adj": 45,        # the other participant stands on a neighbouring panel (Manhattan 1)
    # --- EX-06b ---
    "other_slot": 46,       # the other side's battle slot (battle record +0x2F4); this is what
                            # `target_class` used to compare before EX-06b fixed it to the class id
    # --- D4REV2 ---
    "defending": 47,        # the unit is in the game's own "defending" state: exactly the gate D5's
                            # Advance Guard (1152) is tested with in damage_damage_reduction_rules
                            # (path_query_path_unit_stack_count of its battle record != 0)
    # --- CARRIERS ---
    "hp_at_or_below": 48,   # hp at or below a *percent of maximum*, in D4's own arithmetic:
                            # hp <= floor(max * a / 100).  D4's evility getter (FUN_14010de70) scales the
                            # maximum by the evility's own percentage and refuses the value when that
                            # scaled number is under min(current hp, max), so the gate is inclusive and
                            # measured on absolute HP -- 250/1000 passes a 25 gate, where hp_below (4,
                            # integer hp percent strictly below) does not
    # --- CARRIERS2 ---
    "map_has_min": 49,
    # --- DRPGEVIL1b: the holder-side condition of an aura.  Each qualifies the PROVIDER of the near_has
    # written directly before it (an aura row's other conditions test the recipient): "while I hold a fist
    # weapon, the party deals +12 %" is near_has + provider_weapon.  evil_near tests the candidate itself.
    "provider_weapon": 50,          # the provider has an equipped weapon of item category a (1..9)
    "provider_hp_above": 51,        # the provider's hp is at least a percent of its maximum
    "provider_hp_below": 52,        # ... strictly below a percent
    "provider_hp_at_or_below": 53,  # ... at or below a percent (hp <= floor(max * a / 100))
    # --- DRPGEVIL1c ---
    "party_min": 54,        # at least `count` members of the unit's own side on the map are `of` (1 human,
                            # 2 monster, 3 male, 4 female, 5 = has a weapon of item category `id`), the unit
                            # itself included
    "turn_max": 55,         # the battle round counter is at most a (the mirror of turn_min)      # at least a deployed units of relation b have learned evility c.  near_has
                            # (26) is the existential form; this is the counted form D4's "increase
                            # stats if seven allies with Prism Emblem are dispatched" needs.
    # --- EVILFX2 ---
    # Stat-change statuses (a buff or debuff a skill put on the unit): id = stat 2..7 (atk def int res hit
    # spd).  Status slots 7..12 of the stat record, read exactly as unit_stats_evil_status_effects reads
    # them (active byte +0x4E9 + slot, signed power +0x536 + slot).  Evility bonuses are not statuses.
    "self_buff": 56,        # this unit is under a buff (power > 0) of stat a
    "self_debuff": 57,      # ... under a debuff (power < 0) of stat a
    "map_buff_min": 58,     # at least `count` units of relation `of` on the map are under a buff of stat `id`
    "map_debuff_min": 59,   # ... under a debuff of stat `id` ("if an enemy has a RES debuff")
    "enemy_map_max": 60,    # at most a enemies on the map (0 allowed); false while the unit is off the map
    "other_weapon": 61,     # the other side has an equipped weapon of item category a (1..9)
    "side_top": 62,         # no ally on the map has a strictly higher stat a (2..7) than this unit: "the ally
                            # with the highest ATK" as a recipient condition; ties all qualify
    "side_bottom": 63,      # ... a strictly lower stat a: "the ally with the lowest SPD"
    "provider_buff": 64,    # provider qualifier (see 50..53): the aura's holder is under a buff of stat a
    # --- EVILFX3 ---
    "not_moved": 65,        # the unit's panels-moved counter (battle record +0x61C) is 0: "when attacking without
                            # moving", "as long as the unit doesn't move".  The counter is the one D5's own Assault
                            # Attack (1020) and Sonic Charge (105) multiply by and its "doesn't move" test reads
    # --- EVILCAP1: D5's own Magichange state, read from the unit's stat record (0x141067DC8 + index*0xE98, index at
    # unit +0x4348; false without a stat record).  Written by the Magichange equip FUN_140605E30, cleared by the
    # restoration FUN_14015F030, counted down by turn_h13 (0x1406098C0).
    "magichanged": 66,      # the unit is a Magichange weapon right now (participant byte SR+0x4E2 != 0)
    "magichange_host": 67,  # the unit wields a Magichange weapon: a weapon slot s (0/1) has a participant
                            # (SR+0x4B8+0x10*s != 0, the test cmdmenu_preds_p_15cfe0 and turn_h13 make)
    "magichange_turns": 68, # ... and that slot's remaining-turn byte SR+0x4E0+s equals a (1 = the last turn:
                            # turn_h13 ends the Magichange when it reads 1, otherwise decrements)
    # --- DRPGPARTY1: the class registry (`classes` in a mod's evility data: class id -> favourite weapon and
    # potential type, both from the Disgaea RPG character master).  A unit whose class id (unit +0x2E04) is not in
    # the registry has no type: it is never a recipient of 69 and it breaks 70.
    "self_potential": 69,   # this unit's registered potential type is one of the types in the mask `a`
                            # (bit t-1 for type t: 1 King, 2 Pawn, 3 Rook, 4 Bishop, 5 Knight, 6 Queen).  JSON:
                            # {"kind": "self_potential", "types": [6]} (or "id": mask)
    "party_weapons_distinct": 70,   # every member of the unit's own side on the map (the unit included) has a
                            # registered favourite weapon and no two share one ("the party's favourite weapon types
                            # are all different"); false off the map
    # --- DRPGSIG1 ---
    "map_hp_at_or_below": 71,   # at least `count` units of relation `of` on the map are alive with HP at or below `id` percent of
                            # their maximum (hp * 100 <= max * id; "if an enemy has 50% HP or less"); false off the map
}
COND_NAME = {v: k for k, v in COND_KINDS.items()}
# DRPGPARTY1: the class registry's value domains (Disgaea RPG: potential class 1..6; D5 weapon item category 1..9)
POTENTIAL_TYPES = 6
WEAPON_CATEGORIES = 9
MAX_CLASSES = 1024
PROVIDER_KINDS = (50, 51, 52, 53, 64)
# conditions whose argument is a class kind, where 0 is a legitimate value
# conditions where 0 is a legitimate argument
COND_ZERO_OK = {"target_class", "other_slot", "attack_dir", "element", "target_status", "self_status",
                "status_class", "enemy_map_max"}
# kinds that take no argument at all
COND_NO_ARG = {"none", "attack_normal", "attack_skill", "attack_phys", "attack_magic",
               "element_any", "other_adj", "defending", "not_moved", "magichanged", "magichange_host",
               "other_fly", "self_fly", "other_human", "other_monster", "other_male", "other_female",
               "self_human", "self_monster", "self_male", "self_female", "party_weapons_distinct"}
# the three arguments of a condition entry, by name (a, b, c in the table)
COND_ARGS = {"near_has": ("of", "radius", "id"), "near_char": ("of", "radius", "id"),
             "map_has_min": ("count", "of", "id"), "party_min": ("count", "of", "id"),
             "map_buff_min": ("count", "of", "id"), "map_debuff_min": ("count", "of", "id"),
             "map_hp_at_or_below": ("count", "of", "id")}

# the game functions and every static call site of them (found in the pinned build, see evility/CATALOG.md)
POTENCY, STATUS, GROWTH = 0x1401E1B30, 0x1401B97D0, 0x1401E9B50
MULTIPLIER, REDUCTION = 0x1401F8FD0, 0x1401FB2E0
FLIGHT_A, FLIGHT_B = 0x140206160, 0x1402062F0      # has_flight_like_evility, two copies
OVERRIDES = 0x1401EEE30
HIT_RULES, STATUS_RULES = 0x1401F5410, 0x1401FF070  # hit chance / ailment chance rule lists
CRIT_RULES = 0x1401F60A0        # critical-rate additions (called from damage_crit_chance)
ROUND_HP_SP = 0x140551AC0       # turn_t1_per_unit_hp_sp: per-unit HP/SP at the round edge
# P3 additive passes.  Each returns a number the caller then uses, so its wrapper adds the rows' values and
# returns the sum.  The subject is the attacker's battle record for ATK_POWER, the defender's *unit record*
# for DEF_POWER (that argument already is one), and the unit's battle record for MOVE_RANGE / RANGE_BONUS.
ATK_POWER = 0x1401F6300         # damage_attack_bonus_rules: the pre-defence attack-power percent
DEF_POWER = 0x1401F8700         # damage_defence_bonus_rules: the defence-power percent
MOVE_RANGE = 0x140157D90        # menus_env_move_range: the unit's move range in panels
RANGE_BONUS = 0x1401EC5C0       # the attack/magic range bonus getter (vanilla evilities 1033, 3305)
# D4REV2: damage_after_hit_evaluate's absorption pass (D5 evility 6032 "Absorption" lives in it).  Both
# arguments are battle records: the absorber's and the defeated unit's.
ABSORB_PASS = 0x140200D20
# OLEFFECTS: the four ports of the same card.
#   END_ROUND      turn_per_unit_end_round_upkeep -- one call site (0x1405F8FFC) in the round-edge sweep;
#                  the native revenge pair is issued after the original returns for a unit with a row.
#   STEAL_ELIG     the victim-eligibility predicate called from the Cat Burglar defeat path; the site is
#                  redirected so the accumulated chance (esi) can take our rows before the original runs.
#   SP_REGEN       the SP-recovery percentage called once inside turn_t1_per_unit_hp_sp; the game then
#                  computes drain - regen, so adding our percentage there drains exactly that much more.
#   OVERLOAD       the central unit -> Overload-id resolver; every static caller (11) is redirected.
END_ROUND = 0x1401E5AF0
STEAL_ELIG = 0x140203A40
SP_REGEN = 0x1401EE010
OVERLOAD = 0x14015DBF0
RESISTANCE_PASS = 0x1401F2A10
# EX-06b: every caller of this one passes the ActionContext as its first argument, which is how the
# ailment pass gets the action context it is not given (wrap_achance -> evil_ctx -> wrap_astat).
AILMENT_CHANCE = 0x1401BF810
# EX-06b predicate families: 1 = the hit is nullified / the defender may counter.
# damage_nullify_predicate takes (A, D, _, X, tgt_i, v); only the sites whose r9 is demonstrably the
# ActionContext are redirected (a site that passes something else in r9 must not be handed to conditions
# that read the context).  Excluded, with the reason, are 0x1401D8916 (r9 = r13, source not traced),
# 0x1402D3D56 and 0x1402D4085 (r9 = a stack local), 0x140417E64 (r9 = a stack local), 0x140549707
# (r9 = *(rsp+0x910) + 0x160), 0x1406239A6 (r9 not set at the call) and 0x140623C28 (r9 = a struct at
# +0x1328, plausible but unproven): a nullify row is not consulted on those paths.
NULLIFY = 0x1401FE0D0
COUNTER = 0x1401ECE00
# EVILCAP1: damage_skill_dat, at the one call FUN_1401ADA40 makes for Habitual Licker (3011) -- wrap_spdmg
DAMAGE_SKILL_DAT = 0x14008D0F0
# D4SIG3: FUN_1401FEFA0 (support magic x D5's Medical Insertion 1180 value), wrapped at both its static callers
SUPPORT_BOOST = 0x1401FEFA0
# D4SIG4: unit_stats_equip_stat(unit, slot, stat, tiers), eight static calls in unit_recalc 0x14021BFB0 (one per stat) -- wrap_equip
EQUIP_STAT = 0x140219630
# D4SIG6: cmdmenu_preds_p_2068b0(unit, id), at the one call damage_nullify_predicate makes with id 6047 (First Impression) -- wrap_firstimp
HAS_EVILITY = 0x1402068B0
# MASKWIDE1: post_hit_effects(ctl, ctx, attacker battle record), called once per action by exec_ctl_s2_update 0x14053F880
POST_HIT = 0x140542CB0
# DRPGSIG1: FUN_1401FFF40(&heal amount, healer battle record, healed unit's battle record, skill row), the one call damage_heal_compute_heal
# makes after the heal amount is computed (it applies D5's Evil Spirit 141: x (1 - row+0x38 / 100) per hostile holder) -- wrap_healmod
HEAL_MOD = 0x1401FFF40
# D4SIG7: damage_apply_damage(attacker battle record, target battle record, action context, target index, flags), called once per action
# target by FUN_1401B1BA0 (itself called only by unit_battle_action_impl 0x140162D40) -- wrap_atkcount
APPLY_DAMAGE = 0x1401B1FD0
# D4SIG8: turn_t3_per_unit_end_turn(battle record), the per-unit end-of-turn reset, three static call sites (turn_t1_per_unit_hp_sp for team 0,
# sequencer_ctl_s1_update, FUN_1405FAF90) -- wrap_endturn gives a Stone Statue (27807) holder D4's idle counter rule
END_TURN = 0x140159F50
# DD2EVIL2: path_throw_append_target(ctx, index, slot), the call FUN_1401E8750 makes to add the ONE victim of D5's Punishing Prophecy (6112,
# event 0x36F2A4) -- wrap_victims.  The other call (0x1401E896D) belongs to a different event and is not redirected.
PATH_APPEND = 0x1402BB960
EFFECT_SUM = 0x14015B890         # unit_effect_table_sum
CAN_USE_SKILL = 0x140155280      # cmdmenu_env_stat_row_can_use_skill
# Every wrapper: (build tag, the game function it wraps, the static call sites redirected to it).
# A family may need more than one wrapper when the game keeps several copies of the same code.
WRAPPERS = (
    (0xE70001, POTENCY, [0x14021CD02]),
    (0xE70002, STATUS, [0x1401B9575, 0x14021E19B, 0x1402AA5E3, 0x1402B0494]),
    (0xE70003, GROWTH, [0x14021C15D]),
    (0xE70004, MULTIPLIER, [0x1401C169D]),
    (0xE70005, REDUCTION, [0x1401C0EBD]),
    (0xE70006, FLIGHT_A, [0x140157514, 0x1402DB22E]),
    (0xE70007, FLIGHT_B, [0x140154523]),
    (0xE70008, HIT_RULES, [0x1401C2318]),
    (0xE70009, STATUS_RULES, [0x1401BFA23]),
    (0xE7000A, OVERRIDES, [0x14021E79F]),
    (0xE7000B, CRIT_RULES, [0x1401C1E94]),
    (0xE7000C, ROUND_HP_SP, [0x140554B9E, 0x1405FB5DF]),
    # EX-06b (tags continue after EX-05e's 0xE7000C)
    (0xE7000D, AILMENT_CHANCE, [0x1401BEC5C, 0x1401C005D, 0x140220F89, 0x1404B0853]),
    (0xE7000E, NULLIFY, [0x1401BF0F0, 0x1401BF6DD, 0x1401C0A30, 0x14060B657]),
    (0xE7000F, COUNTER, [0x140547333]),
    # P3 additive passes (every static call site in the pinned build)
    (0xE70010, ATK_POWER, [0x1401C1A59]),
    (0xE70011, DEF_POWER, [0x1401C1889]),
    (0xE70012, MOVE_RANGE, [0x1402C8E07, 0x1402C981E, 0x1402C9B2E, 0x1402C9E2E, 0x1402CA140,
                            0x1402CC17C, 0x1402CC2FF, 0x1402CC39C, 0x1402CCCBA, 0x1402CD61E,
                            0x1402CDE6E, 0x1402CE69B, 0x1402CECBA, 0x1402CF07A, 0x1402D459A,
                            0x1405F708E, 0x1405FD222, 0x1405FD7BF, 0x1405FF39F, 0x1405FF7F2,
                            0x1405FF9F0, 0x14060E937, 0x14060EBDE]),
    (0xE70013, RANGE_BONUS, [0x140157B95, 0x1401D7F14, 0x140205F79]),
    # D4REV2: the absorption pass, at its only static call site in the pinned build
    (0xE70014, ABSORB_PASS, [0x1401AEE62]),
    # OLEFFECTS: four Overlord effects, each at a specific game site (see the END_ROUND/STEAL_ELIG/
    # SP_REGEN/OVERLOAD block above).  OVERLOAD has every static caller of the resolver.
    (0xE70015, END_ROUND, [0x1405F8FFC]),
    (0xE70016, STEAL_ELIG, [0x1401AF6A2]),
    (0xE70017, SP_REGEN, [0x140552083]),
    (0xE70018, OVERLOAD, [0x14014FD17, 0x140161983, 0x1401A5A48, 0x1401DD278, 0x1401DD369,
                          0x1402A9540, 0x14044AB2A, 0x1404CBF0D, 0x140554D4C, 0x1405555FC,
                          0x1405FB784]),
    (0xE70019, RESISTANCE_PASS, [0x14021D964]),
    # EVILCAP1: Habitual Licker's percent lookup only (not damage_skill_dat's 180 other callers)
    (0xE7001A, DAMAGE_SKILL_DAT, [0x1401ADDF0]),
    # D4SIG3: damage_buff_compute_buff 0x1401C0076 and the skill-value preview FUN_140201D90 0x140201F03
    (0xE7001B, SUPPORT_BOOST, [0x1401C0076, 0x140201F03]),
    # D4SIG4: unit_recalc's eight stat calls, 0x14021D53C .. 0x14021D5F3
    (0xE7001C, EQUIP_STAT, [0x14021D53C, 0x14021D557, 0x14021D56F, 0x14021D58A, 0x14021D5A2, 0x14021D5BD, 0x14021D5D8, 0x14021D5F3]),
    # D4SIG6: the First Impression test inside damage_nullify_predicate (a lethal hit passes for a Tyrant Guard holder)
    (0xE7001D, HAS_EVILITY, [0x1401FE3B3]),
    # MASKWIDE1: S2's only call of post_hit_effects (exe call scan: one caller), after the action's script ended and every target's
    # vertical speed is 0: the second-word family face_target_away turns the adjacent survivors away from the attacker
    (0xE7001E, POST_HIT, [0x14053FE71]),
    # DRPGSIG1: the heal-amount modifier pass (exe call scan: one caller, damage_heal_compute_heal at 0x1401BF503)
    (0xE7001F, HEAL_MOD, [0x1401BF503]),
    # D4SIG7: the per-target damage application of an action (FUN_1401B1BA0's call at 0x1401B1BE0)
    (0xE70020, APPLY_DAMAGE, [0x1401B1BE0]),
    # D4SIG8: every static call of turn_t3_per_unit_end_turn (exe call scan: three)
    (0xE70021, END_TURN, [0x1405524FF, 0x140554F7F, 0x1405FB9B1]),
    # D4SIG10: the one call of unit_effect_table_sum(unit, 10) in cmdmenu_preds_p_156820 (the base of "Skill") and every static call (exe scan: four) of
    # cmdmenu_env_stat_row_can_use_skill (command_ctl_s1_enter, command_ctl_s1_update, list_skills, FUN_140547750)
    (0xE70022, EFFECT_SUM, [0x140156A47]),
    (0xE70023, CAN_USE_SKILL, [0x14054785D, 0x1402D0A90, 0x14062E7BD, 0x14062EC38]),
    # DD2EVIL2: the append of Punishing Prophecy's victim (0x36F2A4 branch of FUN_1401E8750) -- extra random victims for a random_victims holder
    (0xE70024, PATH_APPEND, [0x1401E8F76]),
    # LONGTAIL2: the one damage_skill_dat call FUN_1401ADA40 makes for Malicious Reflect (143) -- max HP of the attacker instead of damage taken
    (0xE70025, DAMAGE_SKILL_DAT, [0x1401AE531]),
)
# tag -> the name the proofs and reports call the wrapper by.  Anything that needs a wrapper's address or call
# sites must look it up here: the tuple order changed when EX-05e inserted crit/regen before EX-06b's wrappers, so
# zipping a list of names onto WRAPPERS by position silently addresses the wrong function.
WRAPPER_NAMES = {0xE70001: "potency", 0xE70002: "stats", 0xE70003: "growth", 0xE70004: "dealt",
                 0xE70005: "taken", 0xE70006: "flight_a", 0xE70007: "flight_b", 0xE70008: "hit",
                 0xE70009: "status_chance", 0xE7000A: "conversion", 0xE7000B: "crit_rate",
                 0xE7000C: "regen", 0xE7000D: "achance", 0xE7000E: "nullify", 0xE7000F: "counter",
                 0xE70010: "power", 0xE70011: "defense_power", 0xE70012: "move", 0xE70013: "range",
                 0xE70014: "absorb",
                 0xE70015: "revenge", 0xE70016: "steal", 0xE70017: "sp_drain", 0xE70018: "overload",
                 0xE70019: "resistance", 0xE7001A: "sp_damage",
                 0xE7001B: "support_boost", 0xE7001C: "equip_weapon", 0xE7001D: "first_impression", 0xE7001E: "face_away", 0xE7001F: "healmod", 0xE70020: "atkcount", 0xE70021: "endturn", 0xE70022: "roc_geo", 0xE70023: "roc_skill", 0xE70024: "victims", 0xE70025: "max_reflect"}
WRAPPERS_BY_NAME = {WRAPPER_NAMES[tag]: (tag, target, sites) for tag, target, sites in WRAPPERS}


def wrapper(name):
    """(tag, original function, call sites) of the named wrapper, e.g. "counter" -> the counter predicate wrapper."""
    if name not in WRAPPERS_BY_NAME:
        raise KeyError(f"no wrapper named {name!r} (have {', '.join(sorted(WRAPPERS_BY_NAME))})")
    return WRAPPERS_BY_NAME[name]
# 325 classified D4 rows plus decomposition/other-mod headroom. Eight effects and
# four conjunctions per budgeted row; array offsets/counts remain u32 format-2 fields.
# DRPGEVIL1c: 2,048 rows.  Nothing in the table format was sized for 512: rows are found by binary search
# (evil_find), the aura index and cursor fields are 16-bit positions, offsets are u32.  What 512 really
# bounded was cost -- every aura row of a family used to be evaluated (a battle-table walk) on every pass --
# and the presence map removed that: a pass now walks the table once and evaluates only aura rows whose
# provider is in the battle.  Measured in evility/measure_scan_cost.py.
MAX_ROWS, MAX_FX = 2048, 16384
MAX_COND = 8192
# model_team_is_hostile as a bit table: bit b of HOSTILE_TEAMS[a] = team a is hostile to team b
HOSTILE_TEAMS = (0x2A, 0x19, 0x00, 0x33, 0x2A, 0x19)
CLAIM = "D5EV"                      # first bytes of the section, so a rebuild can find it again
EVIL_CTX_MAGIC = 0x4556_3642_4D414731   # "EV6B MAG1": marks the evil_ctx qword in the data area
EVIL_PEND_MAGIC = 0x4556_3250_454E_4431  # "EV2PEND1": marks the evil_pend byte table (DRPGSIG2) in the data area
EVIL_ZQ_MAGIC = 0x4556_324E_4543_5232    # "EV2NECR2": marks evil_zq (NECRO2 raise_zombie queue) followed by evil_zdbg, 64 bytes of counters


# ------------------------------------------------------------------------------------------ mod data
def load(mod):
    """a mod's behavior table ({"evilities": {...}}); empty when it has none"""
    return mod.load_patch(FOLDER, DATA_FILE) or {"evilities": {}}


def save(mod, d):
    mod.save_patch(FOLDER, DATA_FILE, d)


def load_skills(mod):
    """a mod's skill rules ({"rules": {...}}); empty when it has none"""
    return mod.load_patch(SKILL_FOLDER, SKILL_DATA_FILE) or {"rules": {}}


def save_skills(mod, d):
    mod.save_patch(SKILL_FOLDER, SKILL_DATA_FILE, d)


# ------------------------------------------------------------------------------------------ the table
def _stat_index(stat, family):
    if isinstance(stat, int):
        n = stat
    elif isinstance(stat, str) and stat.lower() in STATS:
        n = STATS[stat.lower()]
    else:
        raise ValueError(f"effect stat {stat!r}: use an index 0-7 or one of {', '.join(STATS)}")
    if family == F_RESISTANCE and n not in (8, 9, 10):
        raise ValueError(f"effect stat {stat!r}: resistance requires 8 (fire), 9 (wind), or 10 (ice)")
    if not 0 <= n <= (0x11 if family in (F_STATS, F_RESISTANCE) else 7):
        raise ValueError(f"effect stat {stat!r}: out of range for family {FAMILY_NAME[family]}")
    return n


def _conversion_source(source, evid):
    """a conversion's `from` -> the source byte (0..7 base stat, 8 current SP)"""
    if isinstance(source, int):
        n = source
    elif isinstance(source, str) and source.lower() in CONVERSION_SOURCES:
        n = CONVERSION_SOURCES[source.lower()]
    else:
        raise ValueError(f"evility {evid}: conversion source {source!r}: use an index 0-8 or one of "
                         f"{', '.join(CONVERSION_SOURCES)}")
    if not 0 <= n <= 8:
        raise ValueError(f"evility {evid}: conversion source {source!r} out of range (0..8)")
    return n


def _scale(per, evid):
    """an effect's optional `per` -> the scale byte in the effect's stat word (0 = fixed value)"""
    if per is None:
        return 0
    name = str(per).lower()
    if name not in SCALES:
        raise ValueError(f"evility {evid}: effect per {per!r} (use {', '.join(SCALES)}, or omit it "
                         f"for a fixed value)")
    return SCALES[name]


def _cond(cond, evid):
    """validate one condition -> (kind, a, b, c) of four u16 table words"""
    kind_name = str(cond.get("kind", "none")).lower()
    kind = COND_KINDS.get(kind_name)
    if kind is None:
        raise ValueError(f"evility {evid}: unknown condition {cond.get('kind')!r} "
                         f"(use {', '.join(k for k in COND_KINDS if k != 'none')})")
    if kind_name in COND_NO_ARG:
        return kind, 0, 0, 0
    if kind_name == "self_potential":
        # DRPGPARTY1: the wanted potential types, as a list (1 King .. 6 Queen) or the raw mask
        types = cond.get("types")
        if types is not None:
            if not isinstance(types, (list, tuple)) or not types:
                raise ValueError(f"evility {evid}: self_potential types must be a non-empty list")
            mask = 0
            for t in types:
                if not isinstance(t, int) or isinstance(t, bool) or not 1 <= t <= POTENTIAL_TYPES:
                    raise ValueError(f"evility {evid}: self_potential type {t!r} (use 1 King, 2 Pawn, 3 Rook, "
                                     f"4 Bishop, 5 Knight, 6 Queen)")
                mask |= 1 << (t - 1)
        else:
            mask = cond.get("id")
            if not isinstance(mask, int) or isinstance(mask, bool) or not 1 <= mask < (1 << POTENTIAL_TYPES):
                raise ValueError(f"evility {evid}: self_potential needs types [..] or an id mask of 1..63")
        return kind, mask, 0, 0
    names = COND_ARGS.get(kind_name, ("id",))
    args = []
    for name in names:
        value = cond.get(name, cond.get("id") if name == "id" else None)
        if value is None and kind_name == "party_min" and name == "id":
            value = 0                           # the weapon category, only read for `of` 5
        if value is None:
            raise ValueError(f"evility {evid}: condition {kind_name} needs {name!r}")
        value = int(value)
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"evility {evid}: condition {kind_name} {name} {value} out of range (0..65535)")
        args.append(value)
    a, b, c = (args + [0, 0, 0])[:3]
    if kind_name in ("self_buff", "self_debuff", "side_top", "side_bottom", "provider_buff") and not 2 <= a <= 7:
        raise ValueError(f"evility {evid}: {kind_name} id {a} (use 2 atk, 3 def, 4 int, 5 res, 6 hit, 7 spd)")
    if kind_name in ("map_buff_min", "map_debuff_min"):
        if a == 0:
            raise ValueError(f"evility {evid}: {kind_name} needs a count of at least 1")
        if b > 2:
            raise ValueError(f"evility {evid}: {kind_name} of {b} (use 0 any, 1 ally, 2 enemy)")
        if not 2 <= c <= 7:
            raise ValueError(f"evility {evid}: {kind_name} id {c} (use 2 atk, 3 def, 4 int, 5 res, 6 hit, 7 spd)")
        return kind, a, b, c
    if kind_name == "map_hp_at_or_below":
        if a == 0:
            raise ValueError(f"evility {evid}: map_hp_at_or_below needs a count of at least 1")
        if b > 2:
            raise ValueError(f"evility {evid}: map_hp_at_or_below of {b} (use 0 any, 1 ally, 2 enemy)")
        if not 1 <= c <= 100:
            raise ValueError(f"evility {evid}: map_hp_at_or_below id {c} is a percent (1..100)")
        return kind, a, b, c
    if kind_name in COND_ZERO_OK:
        pass
    elif kind_name in ("near_has", "near_char"):
        if a > 2:
            raise ValueError(f"evility {evid}: {kind_name} of {a} (use 0 any, 1 ally, 2 enemy)")
        if a == 0 and b == 0:
            raise ValueError(f"evility {evid}: {kind_name} needs a radius")
        if c == 0:
            what = "other evility id" if kind_name == "near_has" else "other character id"
            raise ValueError(f"evility {evid}: {kind_name} needs the {what}")
    elif kind_name == "party_min":
        if a == 0:
            raise ValueError(f"evility {evid}: party_min needs a count of at least 1")
        if not 1 <= b <= 5:
            raise ValueError(f"evility {evid}: party_min of {b} (use 1 human, 2 monster, 3 male, 4 female, 5 weapon)")
        if (b == 5) != (c != 0):
            raise ValueError(f"evility {evid}: party_min id is the weapon's item category, for of 5 only")
    elif kind_name == "map_has_min":
        if a == 0:
            raise ValueError(f"evility {evid}: map_has_min needs a count of at least 1")
        if b > 2:
            raise ValueError(f"evility {evid}: map_has_min of {b} (use 0 any, 1 ally, 2 enemy)")
        if c == 0:
            raise ValueError(f"evility {evid}: map_has_min needs the evility id")
    elif a == 0:
        raise ValueError(f"evility {evid}: condition {kind_name} needs a positive id")
    if kind_name == "magichange_turns" and a > 255:
        raise ValueError(f"evility {evid}: magichange_turns id {a} (the remaining-turn byte is 1..255)")
    return kind, a, b, c


def _conditions(evid, e):
    """a row's conditions: one `condition` dict (v1 style) or a list under `conditions`"""
    conds = e.get("conditions")
    if conds is None:
        one = e.get("condition")
        conds = [one] if one else []
    if not isinstance(conds, (list, tuple)):
        raise ValueError(f"evility {evid}: conditions must be a list")
    out = [c for c in (_cond(c, evid) for c in conds) if c[0]]
    if len(out) != len(conds):
        raise ValueError(f"evility {evid}: 'none' cannot be combined with other conditions")
    for i, c in enumerate(out):
        if c[0] in PROVIDER_KINDS:
            if i == 0 or out[i - 1][0] != COND_KINDS["near_has"]:
                raise ValueError(f"evility {evid}: {COND_NAME[c[0]]} qualifies a provider: write it directly "
                                 f"after the near_has it belongs to (one per near_has)")
            if c[1] > 255:
                raise ValueError(f"evility {evid}: {COND_NAME[c[0]]} argument {c[1]} out of range (1..255)")
    return out


def _row(evid, e, scope=0):
    """validate one mod entry -> (family_mask, conditions, [(stat, value)], row flags)

    scope is 0 for an evility row (the unit must have learned the id) and ROW_SKILL for a skill row (the
    action must use that skill id).  Both share the condition and effect vocabulary.
    """
    fams = e.get("family") or []
    if isinstance(fams, str):
        fams = [fams]
    mask = ext = 0
    for f in fams:
        if f in EXT_FAMILIES:
            if not 0 <= EXT_FAMILIES[f] < EXT_BITS:
                raise ValueError(f"evility {evid}: second-word family {f!r}: bit {EXT_FAMILIES[f]} out of range")
            ext |= 1 << (EXT_SHIFT + EXT_FAMILIES[f])
            continue
        if f not in FAMILIES:
            raise ValueError(f"evility {evid}: unknown family {f!r} (use {', '.join(list(FAMILIES) + list(EXT_FAMILIES))})")
        mask |= FAMILIES[f]
    if ext:
        valued = [f for f in fams if f in EXT_VALUE_FAMILIES]
        if mask or scope or bin(ext).count("1") != 1 or bool(e.get("effects")) != bool(valued):
            raise ValueError(f"evility {evid}: a second-word family is one predicate row of its own: no other family, "
                             f"no skill scope, and effects only for {', '.join(EXT_VALUE_FAMILIES)} (which needs exactly one)")
        effects = []
        if valued:
            fxs = e["effects"]
            if len(fxs) != 1 or set(fxs[0]) - {"value"} or not isinstance(fxs[0].get("value"), int) \
                    or isinstance(fxs[0]["value"], bool) or not 1 <= fxs[0]["value"] <= 100:
                raise ValueError(f"evility {evid}: {valued[0]} takes one effect, {{\"value\": 1..100}}")
            effects = [(0, fxs[0]["value"])]
        return 0, _conditions(evid, e), effects, ext, _filter(e, evid, effects)
    if not mask:
        raise ValueError(f"evility {evid}: no family (potency, stats, growth, dealt, taken, "
                         f"flight, aura, hit or status_chance)")
    if mask & F_RESISTANCE and mask not in (F_RESISTANCE, F_RESISTANCE | F_AURA):
        raise ValueError(f"evility {evid}: resistance combines only with aura")
    if mask & F_CONVERSION and mask != F_CONVERSION:
        raise ValueError(f"evility {evid}: conversion cannot combine with other families")
    if mask & F_ABSORB and mask != F_ABSORB:
        raise ValueError(f"evility {evid}: absorb is applied by its own death-time and recalc passes; "
                         f"it cannot combine with other families")
    if mask & F_REGEN and mask not in (F_REGEN, F_REGEN | F_AURA):
        raise ValueError(f"evility {evid}: regen cannot combine with other families (it is applied "
                         f"at the round edge, not by a stat or damage pass)")
    if mask & (F_DAMAGE_NULL | F_ASTAT_NULL) and mask not in (F_DAMAGE_NULL, F_ASTAT_NULL):
        raise ValueError(f"evility {evid}: damage_null and ailment_null are predicates of their own; "
                         f"a row that nullifies something carries no other family")
    if mask & (F_DAMAGE_NULL | F_ASTAT_NULL) and (e.get("effects") or []):
        raise ValueError(f"evility {evid}: damage_null and ailment_null take no effects")
    # PLUME1: attack power is handed the recipient and may use the existing provider test.
    if mask & sum(ADD_FAMILIES) and mask not in (*ADD_FAMILIES, F_POWER | F_AURA, F_WEAPON | F_AURA):
        raise ValueError(f"evility {evid}: {', '.join(FAMILY_NAME[f] for f in ADD_FAMILIES if mask & f)} "
                         f"is an additive pass of its own; it cannot combine with other families")
    if mask & sum(STACK_FAMILIES) and mask not in STACK_FAMILIES:
        raise ValueError(f"evility {evid}: "
                         f"{', '.join(FAMILY_NAME[f] for f in STACK_FAMILIES if mask & f)} has a wrapper "
                         f"of its own and cannot combine with other families")
    if scope & ROW_SKILL and mask & ~sum(SKILL_FAMILIES):
        raise ValueError(f"skill {evid}: skill rules use only the damage-time families "
                         f"({', '.join(FAMILY_NAME[f] for f in SKILL_FAMILIES)}); "
                         f"{', '.join(FAMILY_NAME[f] for f in sorted(FAMILY_NAME) if mask & f and f not in SKILL_FAMILIES)}"
                         f" is an evility family")
    if mask & F_REARM and mask != F_REARM:
        raise ValueError(f"evility {evid}: rearm_first_damage is applied by the round-edge wrapper of its own; "
                         f"it cannot combine with other families")
    if mask & (F_NULLIFY | F_COUNTER | F_REVENGE | F_OVERLOAD | F_REARM) and e.get("effects"):
        # a predicate row's whole effect is its presence plus its conditions; it cannot carry numbers,
        # and an effect written here would otherwise be dropped silently
        raise ValueError(f"evility {evid}: no effects (a predicate family's whole effect is its "
                         f"presence plus its conditions)")
    effects = []
    for fx in e.get("effects") or []:
        value = int(fx.get("value", 0))
        if not -32768 <= value <= 32767:
            raise ValueError(f"evility {evid}: value {value} out of range (-32768..32767)")
        # PLUME1: capped percentage/additive effects retain the 8-byte layout. Only flagged
        # effects pack a signed base value in low16 and an unsigned upper limit in high16.
        # Uncapped effects keep their previous s32 encoding byte for byte.
        cap = fx.get("max")
        if "max" in fx:
            if (mask & ~F_AURA) & ~(sum(NUMBER_FAMILIES) | sum(ADD_FAMILIES)):
                raise ValueError(f"evility {evid}: max needs only percentage or additive families")
            if isinstance(cap, bool) or not isinstance(cap, int) or not 0 <= cap <= 32767:
                raise ValueError(f"evility {evid}: max must be an integer in 0..32767")
            value = (value & 0xFFFF) | (cap << 16)
        stat = fx.get("stat")
        if mask == F_CONVERSION:
            # Keep format-2's 8-byte effect: low byte destination, next byte BASE source.
            # Conversion has its own family, so existing stat consumers never see packed indices.
            if stat is None or "from" not in fx:
                raise ValueError(f"evility {evid}: conversion needs stat and from (base stat)")
            if "per" in fx:
                raise ValueError(f"evility {evid}: a conversion effect takes no per (it already "
                                 f"reads a runtime source: current SP)")
            dest = _stat_index(stat, F_POTENCY)
            source = _conversion_source(fx["from"], evid)
            effects.append((dest | (source << 8), value))
            continue
        if "from" in fx:
            raise ValueError(f"evility {evid}: from requires the conversion family")
        if mask & F_REGEN:
            # regen effects name one of the two resource pools; the value is a percentage of the
            # unit's *maximum* (negative drains) applied once at the round edge.
            if stat is None:
                raise ValueError(f"evility {evid}: regen needs stat hp or sp")
            n = _stat_index(stat, F_POTENCY)
            if n not in (0, 1):
                raise ValueError(f"evility {evid}: regen applies to hp or sp, not {stat!r}")
            if "per" in fx:
                raise ValueError(f"evility {evid}: a regen effect takes no per")
            base = fx.get("base")
            if base not in (None, "self", "provider"):
                raise ValueError(f"evility {evid}: regen base {base!r} (use self or provider)")
            if base == "provider":
                # EVILFX2: percent of the aura provider's maximum HP (the unit the row's near_has matched)
                walks = [c for c in (e.get("conditions") or [e.get("condition") or {}])
                         if str(c.get("kind", "")).lower() in MAP_WALK_KINDS]
                if n != 0 or not mask & F_AURA or len(walks) != 1:
                    raise ValueError(f"evility {evid}: regen base provider is for an hp effect of an aura row "
                                     f"whose only map condition is its near_has")
                n |= 0x100
            effects.append((n, value))
            continue
        if mask == F_ABSORB:
            # one percentage of the defeated unit's six stats; the stat field is not used, and the
            # value comes from a live unit, so a runtime `per` would multiply a percentage by a count
            if stat is not None:
                raise ValueError(f"evility {evid}: absorb is one percentage of the defeated unit's "
                                 f"stats, not a stat ({stat!r})")
            if "per" in fx:
                raise ValueError(f"evility {evid}: an absorb effect takes no per (it already reads a "
                                 f"live unit's stats)")
            effects.append((0, value))
            continue
        if mask == F_EVASION:
            # D4SIG5: one number; "mode" says how wrap_hit applies it (stat word bits 8-9, read by evil_dmg_sum's mode filter:
            # 0 scale, 0x100 points before the game's clamp, 0x200 "after" = DD2EVIL1, points after the game's own call).
            # DD2EVIL1: a runtime `per` count and a `max` cap are allowed (DD2 Rapid Movement: 2 per panel moved, capped at 64)
            if stat is not None:
                raise ValueError(f"evility {evid}: an evasion effect is one number (mode scale, points or after), no stat")
            mode = fx.get("mode", "scale")
            if mode not in ("scale", "points", "after"):
                raise ValueError(f"evility {evid}: evasion mode {mode!r} (use scale, points or after)")
            if int(fx.get("value", 0)) < 0:
                raise ValueError(f"evility {evid}: an evasion value is 0 or more (the game applies a factor only above 0)")
            effects.append(({"scale": 0, "points": 0x100, "after": 0x200}[mode] | _scale(fx.get("per"), evid) << 16
                            | (FX_MAX if cap is not None else 0), value))
            continue
        scale = _scale(fx.get("per"), evid)
        if scale and not mask & (sum(STAT_FAMILIES) | sum(NUMBER_FAMILIES) | sum(ADD_FAMILIES)):
            raise ValueError(f"evility {evid}: per needs a stat or percentage family "
                             f"({', '.join(FAMILY_NAME[f] for f in STAT_FAMILIES + NUMBER_FAMILIES)})")
        stat_fams = [f for f in STAT_FAMILIES if mask & f]
        if mask & F_RESISTANCE and stat in (None, "all"):
            for n in (8, 9, 10):
                effects.append((n | scale << 16, value))
        elif stat == "all":
            for f in stat_fams:
                for n in range(8):
                    effects.append((n | scale << 16, value))
        elif stat is None and mask & (sum(NUMBER_FAMILIES) | sum(ADD_FAMILIES)):
            # a stat-less effect belongs to the percentage or additive side only; "all" reaches every stat
            effects.append(((scale << 16) | (FX_MAX if cap is not None else 0), value))
        elif stat is None:
            for f in stat_fams:
                for n in range(8):
                    effects.append((n | scale << 16, value))
        else:
            if not stat_fams:
                raise ValueError(f"evility {evid}: families dealt/taken/hit/status_chance/crit_rate and the "
                                 f"additive passes ({', '.join(FAMILY_NAME[f] for f in ADD_FAMILIES)}) use "
                                 f"one number per effect, not a stat ({stat!r})")
            for f in stat_fams:
                effects.append((_stat_index(stat, f) | scale << 16, value))
    if not effects and not mask & sum(PREDICATE_FAMILIES):
        raise ValueError(f"evility {evid}: no effects")
    conds = _conditions(evid, e)
    filt = _filter(e, evid, effects)
    aura = bool(mask & F_AURA)
    if aura:
        # an aura row acts on the *recipient*: the row's own id is on the provider, so the
        # "is it learned" test is replaced by its conditions (which must name the provider).
        if not any(c[0] == COND_KINDS["near_has"] for c in conds):
            raise ValueError(f"evility {evid}: an aura row needs a condition naming the provider "
                             f"(near_has)")
        if mask & ~(F_AURA | sum(AURA_FAMILIES)):
            raise ValueError(f"evility {evid}: aura combines only with "
                             f"{', '.join(FAMILY_NAME[f] for f in AURA_FAMILIES)}")
    return mask, conds, effects, scope, filt


def _filter(e, evid, effects):
    """a row's optional `filter` -> the u32 argument the filtered map counts read

    CARRIERS2: `map_class` (13) counts deployed units whose class/character id equals this value and
    `map_has` (14) counts deployed units that have learned this evility id, so a row that uses one of those
    scales must say what it counts -- and a row that says it while using no such scale is refused rather
    than silently ignored.  A species that is several class ids is written as `"classes": [...]`, which
    `_parts` expands into one row per id (every row of an id adds up, exactly like any other multi-row
    evility), so the table still stores one filter value per row.
    """
    raw = e.get("filter")
    kinds = {(fx[0] >> 16) & 0xFF for fx in effects}
    filtered = kinds & set(FILTER_SCALES)
    if raw is None:
        if filtered:
            raise ValueError(f"evility {evid}: {', '.join(FILTER_SCALES[k] for k in sorted(filtered))} "
                             f"needs filter (the class id or evility id it counts), or classes")
        return 0
    filt = int(raw)
    if not 0 <= filt <= 0xFFFFFFFF:
        raise ValueError(f"evility {evid}: filter {filt} out of range (0..4294967295)")
    if not filtered:
        raise ValueError(f"evility {evid}: filter is only read by the filtered map counts "
                         f"({', '.join(sorted(FILTER_SCALES.values()))}); this row uses none of them")
    return filt


def _parts(e, evid, scope):
    """one mod entry -> the row dicts it stands for

    A value may be a single row (the pre-P3b shape) or a list of rows.  Several rows for one id is the
    model Overlord ships (`[1040 Magic Range]` and `[1040 ...]` in the same evilities.ini, additive): each
    row carries its own family, conditions and magnitudes, so one evility can change two different numbers,
    or the same family under two different conditions.
    """
    if isinstance(e, (list, tuple)):
        if not e:
            raise ValueError(f"{'skill' if scope else 'evility'} {evid}: an empty row list")
        for i, part in enumerate(e):
            if not isinstance(part, dict):
                raise ValueError(f"{'skill' if scope else 'evility'} {evid}: row {i + 1} is not an object")
        return _expand(list(e))
    if e is None:
        return [{}]
    if not isinstance(e, dict):
        raise ValueError(f"{'skill' if scope else 'evility'} {evid}: expected an object or a list of objects")
    return _expand([e])


def _expand(parts):
    """CARRIERS2: a part carrying `classes` becomes one part per class id, each with `filter` set

    A species is not one class id (the cat-type units are 13 D5 classes; the Orc family is six ranks), and
    the table stores one filter value per row, so the authoring form is the list and the expansion is the
    rows.  Every row of an id already adds up, so the expansion is exactly "value x the number of units of
    any of these classes", not "value x the last class".
    """
    out = []
    for part in parts:
        classes = part.get("classes")
        if classes is None:
            out.append(part)
            continue
        if "filter" in part:
            raise ValueError("a row takes `classes` or `filter`, not both")
        if not isinstance(classes, (list, tuple)) or not classes:
            raise ValueError("classes must be a non-empty list of class ids")
        for cid in classes:
            q = dict(part)
            q.pop("classes")
            q["filter"] = int(cid)
            out.append(q)
    return out


def table(evilities, skills=None):
    """{id: entry or [entry, ...]} (+ optional {skill id: rule}) -> (rows, conds, fx)

    rows = [(id, mask, cond_off, n_cond, fx_off, n_fx, flags)], conds = [(kind, a, b, c)],
    fx = [(stat, value)].  Offsets are byte offsets into the two arrays.

    Evility rows come first, in id order, and are what evil_next reaches.  Several rows may share an id
    (P3b): they stay adjacent, in the order the mod data wrote them, and every consumer walks all of them,
    so their effects add up the way separate Overlord `[id ...]` sections do.  Skill rows follow, also in
    id order, and are reached only by evil_dmg_sum's skill pass; they are a separate namespace, so a skill
    id may equal an evility id without either row shadowing the other."""
    rows, conds, fx = [], [], []
    for scope, entries in ((0, evilities), (ROW_SKILL, skills or {})):
        for evid, e in sorted(((int(k), v) for k, v in entries.items()), key=lambda kv: kv[0]):
            if not 1 <= evid <= 0x7FFFFFFF:
                raise ValueError(f"{'skill' if scope else 'evility'} id {evid} out of range")
            if isinstance(e, dict) and e.get("scope") is not None:
                want = "skill" if scope else "evility"
                if str(e["scope"]).lower() != want:
                    raise ValueError(f"{want} {evid}: scope {e['scope']!r} in the {want} data file "
                                     f"(skill rules belong in patches/{SKILL_FOLDER}/{SKILL_DATA_FILE})")
            for part in _parts(e, evid, scope):
                mask, cs, effects, flags, filt = _row(evid, part, scope)
                if len(rows) >= MAX_ROWS:
                    raise ValueError(f"too many new rows ({MAX_ROWS} max, every mod together)")
                if len(fx) + len(effects) > MAX_FX:
                    raise ValueError(f"too many effects ({MAX_FX} max, every mod together)")
                if len(conds) + len(cs) > MAX_COND:
                    raise ValueError(f"too many conditions ({MAX_COND} max, every mod together)")
                rows.append((evid, mask, len(conds) * 8, len(cs), len(fx) * 8, len(effects), flags, filt))
                conds.extend(cs)
                fx.extend(effects)
    return rows, conds, fx


def class_table(classes):
    """DRPGPARTY1: {class id: {"weapon": 1..9, "potential": 1..6}} -> [(class id, weapon, potential)] sorted by class id

    The registry the self_potential / party_weapons_distinct conditions read.  A class id is a u16 (the
    conditions compare unit +0x2E04), the weapon is a D5 item category and the potential type a Disgaea RPG
    potential class; either may be 0 (not known) but not both."""
    out = {}
    for k, v in sorted(((int(k), v) for k, v in (classes or {}).items()), key=lambda kv: kv[0]):
        if not 1 <= k <= 0xFFFF:
            raise ValueError(f"class registry: class id {k} out of range (1..65535)")
        if not isinstance(v, dict) or set(v) - {"weapon", "potential"}:
            raise ValueError(f"class registry: class {k}: expected {{weapon, potential}}, got {v!r}")
        w, p = v.get("weapon", 0), v.get("potential", 0)
        if not (isinstance(w, int) and isinstance(p, int)) or isinstance(w, bool) or isinstance(p, bool):
            raise ValueError(f"class registry: class {k}: weapon and potential must be integers")
        if not 0 <= w <= WEAPON_CATEGORIES or not 0 <= p <= POTENTIAL_TYPES or not (w or p):
            raise ValueError(f"class registry: class {k}: weapon {w} (0..{WEAPON_CATEGORIES}) / potential {p} "
                             f"(0..{POTENTIAL_TYPES}), not both 0")
        out[k] = (k, w, p)
    if len(out) > MAX_CLASSES:
        raise ValueError(f"class registry: {len(out)} classes ({MAX_CLASSES} max, every mod together)")
    return list(out.values())


def _merge_classes(acc, classes, where="a mod"):
    """add one mod's class registry to the accumulated one; the same class with a different type is an error"""
    for k, v in (classes or {}).items():
        k = int(k)
        v = {"weapon": int(v.get("weapon", 0)), "potential": int(v.get("potential", 0))} if isinstance(v, dict) else v
        if k in acc and acc[k] != v:
            raise ValueError(f"class registry: class {k} is {acc[k]} in one mod and {v} in {where}")
        acc[k] = v


def _check_site(va, orig, target):
    """is `orig` a 5-byte call to `target`?  (a different game build puts something else there)"""
    if len(orig) != 5 or orig[0] != 0xE8:
        raise ValueError(f"evility extension: call site {va:#x} is not a call (unexpected exe build)")
    dest = va + 5 + struct.unpack("<i", orig[1:])[0]
    if dest != target:
        raise ValueError(f"evility extension: call site {va:#x} calls {dest:#x}, expected {target:#x}")
    return dest


def build_patch(exe, evilities, skills=None, classes=None):
    """the exe with the .d5el section and the wrapped functions' call sites redirected

    `classes` (DRPGPARTY1) is the class registry, see class_table; None or empty = no class has a type."""
    rows, conds, fx = table(evilities, skills)
    src = _asm_source(rows, conds, fx, class_table(classes))
    base = code_base(exe, SECTION_NAME)
    code, labels = _assemble(src, base)
    patches = []
    for tag, target, sites in WRAPPERS:
        wrapper = labels[tag]
        for va in sites:
            orig = exe[_offset(exe, va):_offset(exe, va) + 5]
            _check_site(va, orig, target)
            patches.append((va, orig, wrapper, 0xE8))
    # a site another runtime owns (Overlord's, when it is part of this install) is not written at all;
    # the families it implements are listed by overlord_compat.double_apply so the rows can be off too
    from . import overlord_compat
    patches, _yielded = overlord_compat.filter_hooks(SECTION_NAME, patches)
    return add_code_section(exe, SECTION_NAME, code, patches)


# the *data* symbols of the most recent build ({"evil_ctx": va}).  Kept apart from the assembler's code
# labels: the static stack audit treats every code label as a function entry, and evil_ctx is a qword.
SECTION_SYMBOLS = {}


def _offset(exe, va):
    import pefile
    from .exepatch import IMAGE_BASE
    return pefile.PE(data=exe, fast_load=True).get_offset_from_rva(va - IMAGE_BASE)


HEADER = CLAIM.encode() + bytes([2])          # "D5EV" + table format 2


def _asm_source(rows, conds, fx, classes=()):
    """the section source: a 16-byte header (claim + format, the code starts right after it), the code,
    the row table, the condition array and the effect array (and the class registry, DRPGPARTY1)"""
    with open(ASM_FILE, "r", encoding="utf-8") as f:
        body = f.read()
    nl = "\n"
    header = "    .byte " + ", ".join(str(b) for b in HEADER + b"\0" * (16 - len(HEADER)))
    skill_rows = [i for i, row in enumerate(rows) if row[6] & ROW_SKILL]
    data = ["    .align 16", "evil_tbl:"]
    for evid, mask, cond_off, n_cond, off, n, flags, filt in rows:
        data.append(f"    .long {evid}, {mask}, {cond_off}, {n_cond}, {off}, {n}, {flags}, {filt}")
    data.append("    .long 0, 0, 0, 0, 0, 0, 0, 0")
    data.extend(["evil_tbl_end:", "evil_row_count:", f"    .long {len(rows)}",
                 "evil_evility_count:", f"    .long {len(rows) - len(skill_rows)}",
                 "evil_aura_count:", f"    .long {sum(bool(r[1] & F_AURA) for r in rows)}",
                 "evil_aura_index:"])
    data.extend(f"    .long {i * 32}" for i, row in enumerate(rows) if row[1] & F_AURA)
    # the skill rows in id order (EX-06): evil_dmg_sum walks this instead of evil_next, which only knows
    # rows an id in some unit's learned list can reach
    data.append("evil_skill_count:")
    data.append(f"    .long {len(skill_rows)}")
    data.append("evil_skill_index:")
    data.extend(f"    .long {i * 32}" for i in skill_rows)
    if not skill_rows:
        data.append("    .long 0")
    data.append("    .align 16")
    data.append("evil_cond:")
    for kind, a, b, c in conds:
        data.append(f"    .word {kind}, {a}, {b}, {c}")
    if not conds:
        data.append("    .word 0, 0, 0, 0")
    data.append("    .align 16")
    data.append("evil_fx:")
    for stat, value in fx:
        data.append(f"    .long {stat}, {value}")
    if not fx:
        data.append("    .long 0, 0")
    data.append("    .align 8")
    # the hostile-team bit table, indexed by the subject's team byte (from model_team_is_hostile)
    data.append("evil_hostile:")
    data.append("    .byte " + ", ".join(str(m) for m in HOSTILE_TEAMS))
    data.append("    .align 8")
    # runtime scale kinds -> (relation, radius in panels), indexed by kind - 1 (see SCALES)
    data.append("evil_scale_tbl:")
    for relation, radius in ((1, 1), (2, 1), (0, 1), (1, 0xFFFF), (2, 0xFFFF), (0, 0xFFFF)):
        data.append(f"    .word {relation}, {radius}")
    data.append("    .align 8")
    # EX-06b: the action context captured for the duration of damage_buff_ailment_chance (0 outside it).
    # It sits last so the arrays keep the byte layout earlier cards audited; the magic qword in front of
    # it lets the offline proofs find the slot in the assembled section.
    # DRPGEVIL1c: the presence map (evil_presence / evil_next): one bit per evility id below 32768, rebuilt at
    # the start of every pass that could reach an aura row.  Before the context slot, which stays last.
    # DRPGPARTY1: the class registry, one dword per class sorted by class id: class | weapon << 16 | potential << 24
    # (evil_classinfo binary-searches the low word).  Always at least one zero dword so the label is addressable.
    data.append("evil_class_count:")
    data.append(f"    .long {len(classes)}")
    data.append("evil_class_tbl:")
    data.extend(f"    .long {k | (w << 16) | (p << 24)}" for k, w, p in classes)
    if not classes:
        data.append("    .long 0")
    data.append("    .align 8")
    data.append("evil_malice_count:")        # NEMO1: the stand-in character ids evil_nemo draws from
    data.append(f"    .long {len(MALICE_STANDINS)}")
    data.append("evil_malice_tbl:")
    data.extend(f"    .long {c}" for c in MALICE_STANDINS)
    data.append("    .align 8")
    data.append("evil_spdmg_row:")           # EVILCAP1: the row wrap_spdmg hands back (+0x38 = percent)
    data.append("    .fill 64, 1, 0")
    data.append("evil_near_unit:")           # EVILFX2: the last unit evil_near counted
    data.append("    .quad 0")
    data.append("evil_fxmode:")             # D4SIG5: which effects evil_dmg_sum adds (0 all, 1 scale, 2 points, 3 after = DD2EVIL1)
    data.append("    .quad 0")
    data.append("    .quad " + hex(EVIL_ZQ_MAGIC))   # NECRO2: the raise_zombie queue and its debug counters
    data.append("evil_zq:")
    data.append("    .fill 528, 1, 0")                   # +0 attacker battle record, +8 count, +16 16 entries x 32 bytes
    data.append("evil_zdbg:")
    data.append("    .fill 16, 4, 0")                    # dword counters, see evil_necro_note in d5evil.inc.asm
    data.append("    .quad " + hex(EVIL_PEND_MAGIC))
    data.append("evil_pend:")               # DRPGSIG2: one byte per stat record (0x28A, padded): invincible_hits decision pending its count
    data.append("    .fill 656, 1, 0")
    data.append("    .align 8")
    data.append("evil_present:")
    data.append("    .fill 512, 8, 0")
    data.append("    .quad " + hex(EVIL_CTX_MAGIC))
    data.append("evil_ctx:")
    data.append("    .quad 0")
    data.append("    .align 8")
    return header + nl + "evil_code:" + nl + body + nl + "evil_data_marker:" + nl + nl.join(data) + nl


TAGS = tuple(tag for tag, _, _ in WRAPPERS)   # build tags at each wrapper's start


def _assemble(src, base):
    """assemble the section at `base`.

    The addresses in the source are those of the pinned build the catalog was verified against (the exe this
    extension refuses to install on anything else), so they are used as written: they are *not* put through
    exemap, whose known build is a different one (the kit's own runtime/hook addresses).  build_patch checks
    every call site's bytes against the pinned target, so a different exe build fails instead of hooking
    something else."""
    from keystone import Ks, KS_ARCH_X86, KS_MODE_64
    ks = Ks(KS_ARCH_X86, KS_MODE_64)
    enc, _ = ks.asm(src, base)
    code = bytes(enc)
    labels = {}
    for tag in TAGS:
        marker = b"\x41\xbb" + struct.pack("<I", tag)      # mov r11d, tag
        at = code.find(marker)
        if at < 0:
            raise ValueError(f"evility extension: wrapper with tag {tag:#x} not found in the assembled section")
        labels[tag] = base + at
    SECTION_SYMBOLS.clear()
    at = code.find(struct.pack("<Q", EVIL_CTX_MAGIC))
    if at >= 0:                                          # data slot, not a code entry: see SECTION_SYMBOLS
        SECTION_SYMBOLS["evil_ctx"] = base + at + 8
    at = code.find(struct.pack("<Q", EVIL_PEND_MAGIC))
    if at >= 0:
        SECTION_SYMBOLS["evil_pend"] = base + at + 8
    at = code.find(struct.pack("<Q", EVIL_ZQ_MAGIC))
    if at >= 0:
        SECTION_SYMBOLS["evil_zq"] = base + at + 8
        SECTION_SYMBOLS["evil_zdbg"] = base + at + 8 + 528
    return code, labels


def section_info(exe):
    """where the installed table is: {base, size, data, section}

    A code section appended by add_code_section can grow into the previous kit section (when the exe has no room
    for another header), so the table is found by its claim bytes, not by the section name."""
    import pefile
    from .exepatch import IMAGE_BASE
    pe = pefile.PE(data=exe, fast_load=True)
    for s in pe.sections:
        data = pe.get_data(s.VirtualAddress, s.Misc_VirtualSize)
        at = data.find(CLAIM.encode())
        if at >= 0:
            base = IMAGE_BASE + s.VirtualAddress + at
            return {"base": base, "code": base + 16, "size": s.Misc_VirtualSize - at,
                    "data": data[at:], "section": s.Name.rstrip(b"\0").decode("ascii", "replace")}
    return None


# ------------------------------------------------------------------------------------------ install
def _merge(acc, k, e):
    """add one mod's entry for id k to the accumulated table

    A single row object merges key-by-key with an existing single row (the pre-P3b behaviour: a later mod
    overrides the keys it names).  As soon as either side is a list, the rows are appended, which is how
    Overlord's per-mod `evilities.ini` files combine: later rows add, they never overwrite.
    """
    evid = int(k)
    if isinstance(e, (list, tuple)):
        e = list(e)
    if evid not in acc:
        acc[evid] = e
        return
    old = acc[evid]
    if isinstance(old, dict) and isinstance(e, dict):
        old = dict(old)
        old.update(e)
        acc[evid] = old
        return
    acc[evid] = ([old] if isinstance(old, dict) else list(old)) + \
                ([e] if isinstance(e, dict) else e)


def _handler(ctx, mod, patch_dir):
    d = load(mod)
    acc = getattr(ctx, "_evilities", {})
    for k, e in (d.get("evilities") or {}).items():
        _merge(acc, k, e)
    ctx._evilities = acc
    if d.get("evilities"):
        ctx.log(f"  evilities: {len(d['evilities'])} with behavior of their own")
    if d.get("classes"):                         # DRPGPARTY1: the class registry (class id -> weapon, potential)
        reg = getattr(ctx, "_classes", {})
        _merge_classes(reg, d["classes"], "another mod")
        ctx._classes = reg
        ctx.log(f"  class registry: {len(d['classes'])} classes")


def _skill_handler(ctx, mod, patch_dir):
    """a mod's skill rules, merged into the same table as the evilities"""
    d = load_skills(mod)
    rules = d.get("rules") or {}
    acc = getattr(ctx, "_skill_rules", {})
    for k, e in rules.items():
        if not isinstance(e, dict):
            raise ValueError(f"skill rule {k}: expected an object")
        if e.get("scope") is not None and str(e["scope"]).lower() != "skill":
            raise ValueError(f"skill rule {k}: scope {e['scope']!r} (skill rules are always scope "
                             f"'skill'; evility rows belong in patches/{FOLDER}/{DATA_FILE})")
        acc.setdefault(int(k), {}).update(e)
    ctx._skill_rules = acc
    if rules:
        ctx.log(f"  skill rules: {len(rules)} on imported skills")


def _finalize(ctx):
    evs = getattr(ctx, "_evilities", {})
    rules = getattr(ctx, "_skill_rules", {})
    if not evs and not rules:
        return
    rows, conds, fx = table(evs, rules)        # validate before touching the exe
    exe = build_patch(ctx.get(EXE_FILE), evs, rules, getattr(ctx, "_classes", {}))
    ctx.put(EXE_FILE, exe)
    fams = {}
    for evid, e in list(evs.items()) + list(rules.items()):
        for part in _parts(e, evid, 0):
            for f in ([part["family"]] if isinstance(part.get("family"), str)
                      else (part.get("family") or [])):
                fams[f] = fams.get(f, 0) + 1
    ctx.log("  evility behavior: " + ", ".join(f"{n} {f}" for f, n in sorted(fams.items()))
            + f" ({len(rows)} rows, {len(conds)} conditions, {len(fx)} effects"
            + (f", {len(rules)} of them skill rules" if rules else "") + ")")


register_patch_handler(FOLDER, _handler, order=48)
register_patch_handler(SKILL_FOLDER, _skill_handler, order=49)
register_finalizer(_finalize)
