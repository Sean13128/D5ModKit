# Skill rules: a skill's own numbers at damage time

`docs/EVILITIES.md` describes an evility id that carries its own condition and numbers. A skill can need
the same thing: an imported D4 skill (or Evility) whose behavior is not the one D5's compiled code gives
its donor skill. This page covers the half of that table whose rows are keyed by a **skill id**.

Backend: `d5lib/evility.py` (same table, section and evaluator as the evilities). Mod data:
`patches/skillrules/skillrules.json`.

## Why it exists

A D4 Evility is not a data row with a description: `mskill.dat` rows are 212 bytes, the Evility id sits
at `+8` and the numbers a compiled rule uses sit at `+13` onward. Aegis is id 392 and stores **30** at
`+13`; the compiled rule multiplies intermediate damage by `(100 - 30) / 100` — with signed integer
truncation at that stage — when the attacker stands in front of the defender. D5 has no Aegis and no
generic "damage × parameter" evility field: the nearest donor (evility 12) reduces damage under its own
conditions with its own rounding. Copying that donor does not reproduce the D4 rule.

So the Kit lets a mod state the rule itself, in the same vocabulary the evility extension already uses:

```json
{"rules": {
  "392": {"family": "taken",
          "effects": [{"value": -30}],
          "conditions": [{"kind": "attack_dir", "id": 0}]}}}
```

"Skill 392, when the action uses it: scale the damage the target takes by (100 − 30) % if the attacker
stands in front (0)." The magnitude in the row is the number the D4 row stores; the condition names the
D5 field that decides it.

## How a skill row differs from an evility row

Both go into one table (`.d5el`), and both use the same conditions, effects, counted magnitudes and
capacity budget. Only two things change:

* **Matching.** An evility row applies when the acting/defending unit has *learned* its id. A skill row
  applies when the **action** uses that skill id — no unit has to have learned anything, and the same row
  works for the attacker's side (`dealt`, `hit`) or the defender's side (`taken`, `status_chance`,
  `nullify`).
* **Reach.** `evil_next` enumerates rows by walking a unit's learned ids and binary-searching the table,
  so it can never find a row keyed by a skill id. Skill rows are listed in a separate index
  (`evil_skill_index`, in id order) and the consumers walk it after the ordinary rows.

The two namespaces may share a number: `{"rules": {"7000": …}}` and `{"evilities": {"7000": …}}` are two
rows that both apply, and neither shadows the other (the binary search stops at
`evil_evility_count`).

## Families a skill rule may use

| family | what the row does | action context? |
|---|---|---|
| `dealt` | percentage points added to the damage the unit *deals* (the caller composes `100 + value`) | yes |
| `taken` | the in/out percent of damage the unit *takes* is scaled by `(100 + value) %` | yes |
| `hit` | percentage points added to the in/out hit chance (kept 1..100) | yes |
| `status_chance` | percentage points added to the in/out ailment chance (floored at 0) | yes, see below |
| `nullify` | the hit is nullified when the game's own predicate says no | yes (4 of its 11 sites) |
| `counter` | the defender may counter when the game says no | **no** |

`potency`, `stats`, `growth`, `aura`, `conversion` and `flight` are not damage-time passes and never see
an action context, so a skill row cannot name them (build-time refusal). `counter` is evility-only for the
same reason.

### How the ailment pass gets the action context

`damage_status_chance_rules` is not given the ActionContext: its arguments are the in/out percent, both
battle records, K and the ailment index. Every static caller of `damage_buff_ailment_chance`
(`0x1401BF810`) does pass it — as that function's *first* argument — so the extension redirects all four
call sites to a wrapper that records the pointer in an `evil_ctx` slot for the duration of the call and
restores the previous value on the way out. `wrap_astat` reads the slot. Outside such a call the slot is
0, and a skill row simply never matches. Nothing about the game's arguments changes; an unhooked caller
degrades to "no skill id" rather than to a stale pointer.

The four redirected sites are `0x1401BEC5C` (damage compute), `0x1401C005D` (buff compute),
`0x140220F89` (plain-attack ailment pass) and `0x1404B0853` (HUD forecast — the forecast therefore shows
a rule's effect on the displayed ailment chance too).

### Nullify: only the sites that really pass the context

`damage_nullify_predicate` (`0x1401FE0D0`) has eleven static callers, but only four of them load `r9`
with the ActionContext (`0x1401BF0F0`, `0x1401BF6DD`, `0x1401C0A30`, `0x14060B657`). The other seven pass
a stack local, `r13`, `*(rsp+0x910)+0x160`, or leave `r9` unset. Those are **not** redirected: a nullify
row is not consulted on those code paths, which is deliberate — the alternative is evaluating conditions
against a pointer that is not the action context. The excluded sites and the reason for each are in
`d5lib/evility.py` next to `NULLIFY`.

## Conditions

All of `evility.COND_KINDS` (`docs/EVILITIES.md` lists them): `attack_dir` (0 front, 1 side, 2 behind,
taken from the action's own target entry), `element`, `attack_phys`/`attack_magic`/`attack_skill`,
`weapon`, `target_count`, `hp_below`/`hp_above`, `other_hp_above`, `ally_adj`/`enemy_adj`, `near_has`,
`rng`, `target_class` (the other unit's class id), `other_slot` (the other unit's battle slot), the
type/flyer/level comparisons, and so on. Effects may carry `per` (a runtime count) exactly as evility
effects do. A predicate family (`nullify`, `counter`, `flight`) takes no effects at all.

`attack_dir` uses the value the game already computed for that target entry, which is D5's own
front/side/back classification. It is *not* D4's angle arithmetic: the D4 producer, the D5 producer and
D5's prepared attacker facing disagree even at adjacent diagonals (see the project Aegis report), so a
rule that transcribes D4's angle test has to be re-checked against D5's classification. `attack_dir`
avoids that only by using D5's answer, which is the right analogue — not a proof of numeric equality.

`target_class` compares the other unit's **class id** (its `char.dat` id, unit record `+0x2E04`). Before
EX-06b it read the other battle record's `+0x2F4`, which is the unit's *slot* — the number the action
context's target entries are keyed by, and the value `attack_dir` uses to find its entry. A row that
wanted the old comparison now says `{"kind": "other_slot", "id": <slot>}`.

## Not covered yet

Two rows may apply to the same hit; their values add. Vanilla ids and vanilla behavior are untouched: a
table without skill rows emits `evil_skill_count = 0` and the pass costs one compare.

Still separate work, with the evidence state recorded in `skills/EX06B-REPORT.md`:

* extra hits / repeat attacks — `repeat_kind` (`0x1401EB390`) returns a tally index, not a boolean, so it
  is not a "call original then adjust" wrapper;
* damage redirection / retaliation — needs the redirect path in the damage pipeline, not a predicate;
* carry/throw (D4 Lift Catch) — the carry subsystem is a multi-state command (`carry_build_view`,
  `carry_ctl_s0/s1_update`, `carry_land`, `throw_ctl_s0/s1_update`) and no single proven "may lift"
  predicate has been isolated yet.

## Verification

```sh
D5_KIT=$PWD Local/python-macos/bin/python3 -m pytest tests/test_skillrules.py -q
D5_KIT=$PWD /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \
  evility/offline_proof_ex06.py --json evility/results/ex06b-behavior.json
D5_KIT=$PWD /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \
  evility/offline_proof_ex06.py --abi --json evility/results/ex06b-abi.json
Local/python-macos/bin/python3 evility/static_stack_ex06.py
```

The behaviour proof executes the real patched section under Unicorn: the Aegis row (front 101 → 70,
side/behind untouched), skill vs evility rows with the same id, counted magnitudes, conjunctions, the
`hit`/`taken`/`dealt` families, class vs slot, ailment skill rows with and without the stashed context,
the four stash sites, and the nullify/counter predicates. `--abi` enters each real redirected `CALL` with
the caller's `RSP % 16 == 0` and checks the continuation, home space and nonvolatiles. The static audit
walks the section from every wrapper entry and internal call target: 23 sites, 56 calls, 0 findings.

None of this is native or gameplay acceptance: the emulator uses synthetic records and deterministic
original callees, and no Windows unwind was exercised. The direction, class and slot values are the
fields the game writes, but that production is not re-executed here.
