# Healing carrier research — offline handoff, 2026-10-29

No healing carrier or content row was implemented or certified. The six EVCAP healing candidates are not one operation: Death's Heal (Healer, D4 301), Corpse Heal (Healer, 689), Veteran Nurse (Healer, 822), Angel Blessings (Main Hero B, 627), Angel's Flight (Main Hero B, 628), and Darkness Pact (Zombie, 172) require separate behavior and source-fidelity evidence. Dismal Omen (Death, 215) is currently an adaptation and requires a map-wide modifier. This handoff is static evidence, not a proof of gameplay or ABI.

## Prior art checked

- Cryswar's Overlord: `Private/Overlord and Sorrow research/class-support/OVERLORD-COMPARISON.md`, `overlord-source/overlord/10_evility_runtime.c`, `overlord-source/overlord/12_evility_hooks.c`, and hook ownership in `Subprojects/Engine-Extensions/OLEFFECTS-REPORT.md`. Overlord's `hp_regen_percent`/`hp_recovery_aura` are round-edge effects, not a healing-action carrier. Its healing-magic filter checks skill magic kind 4; that filter is a useful lead, not proof of every D4 rule. Credit Cryswar when reusing his design.
- Sorrow: `community/sorrow/RESEARCH-INDEX.md` and `ida-export-20261014/disgaea5_names.json` identify `damage_heal_compute_heal` at 0x1401BF3C0 and `damage_sign_flip_predicate` at 0x1401C0840. Labels/signatures are research hints; confirm against instructions and actual calls.
- D5 decomp: `/Volumes/Data/Decomp/d5/functions/1401bf3c0_damage_heal_compute_heal.c`, `1401ffa50_FUN_1401ffa50.c`, `1401fff40_FUN_1401fff40.c`, `1401c0840_damage_sign_flip_predicate.c`, and `1401be860_battle_damage_compute_target.c`. D4 decomp `/Volumes/Data/Decomp/d4` was checked for named evility strings; none found in functions, so no D4 behavior was independently established from those searches. Source description evidence is `Research/source-packs/d4uniq2/emit/d4_extension_rows-cast.json`; it does not settle ambiguous terms.

## Pinned executable CALL candidates

Capstone disassembly of the pinned backup SHA-256 49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce gives:

| CALL site | Original target | Decomp observation |
|---|---|---|
| 0x1401BF493 | 0x1401FFA50 | Returns an additive healing percentage; caller passes attacker battle record in RCX, target battle record in RDX, skill row in R8. The native function already accounts for other modifiers. |
| 0x1401BF503 | 0x1401FFF40 | Operates on the calculated amount via pointer and receives attacker, target and skill. Native logic scans for a map-wide hostile modifier and applies it multiplicatively. |
| 0x1401BF61A | 0x1401C0840 | Sign-flip predicate before amount application; RCX = attacker battle record, RDX = target battle record, R8 = action context (confirmed by instruction setup). Its existing result must be composed correctly; there is another call at 0x1401BEE08 for non-healing computation, which must remain untouched. |
| 0x1401BE900 | 0x1401BF3C0 | Main compute-target path enters the healing routine. Its arguments are action context, attacker index and target index; this is a broader candidate, not a blanket endorsement. |

These instructions do not appear among OLEFFECTS' listed owned sites, but re-check the complete integrated exe map and all branches at implementation time. A CALL candidate alone does not prove scope, correct D4 arithmetic, saved-register lifetime, or interaction with installed patches. In particular the heal routine also handles special skill cases after the earlier modifiers; avoid assuming a simple post-return percentage applies identically to all healing.

## Source fidelity gates

- Corpse Heal: source text “Increase recovery by 50% x the # of adjacent units.” Establish whether adjacent units are counted around the holder or recipient, which teams/countable units qualify, whether magic and items both qualify, and rounding/stacking. The additive percentage CALL is a candidate only after those are known.
- Angel's Flight: “Increase heal effect by the # of panels moved x 10%.” Establish source unit, move/undo/forced-move rules and skill type. D5 battle record +0x61C is a lead from EVCAP, not a validated equivalent; coordinate with movement lane.
- Veteran Nurse: “Add 1 to the strength of healing magic.” This is a strength/tier change, not automatically a percentage multiplier. Identify D4's calculation and D5's skill-strength equivalent before implementing.
- Death's Heal: “Stats decrease by 50%, but heal magic gains reverse effect.” Establish whose healing magic is reversed, healing-only skill classification, and stat set. Preserve the native sign predicate, including existing sign-flips. Both the stat component and reversal are needed to claim the row complete.
- Darkness Pact: “Stats increased by 30%. HP cannot be healed by magic.” Establish stat scope and whether target-side blocking excludes items and passive regeneration; both components are required.
- Angel Blessings: “Cures abnormalities when using healing magic.” Determine the exact target set and timing; D5's healing routine has native ailment-marking logic, but setting its result flags must not be guessed. Confirm it does not cure on a failed, nullified, or non-magic event without source evidence.
- Dismal Omen: independently verify the source description, owner scope, opposing-team filter and stacking before replacing the current adaptation. Native 0x1401FFF40 map scan is a promising design reference, not sufficient equivalence.

## Completion path

1. Trace the D4 calculations or establish exact source semantics through reliable source-data evidence; preserve unresolved cases as omissions.
2. Add only supported distinct effect families to the `.d5el` evaluator, with EVCAP-compatible learned-evility lookup and an unclaimed family bit/site. Respect existing conditions, stacking and component ownership; reserve IDs/rows against the full pack and verify the description format (`％`/`%d`).
3. For every new hook, redirect an actual game CALL and preserve its original semantics, registers, fixed frame, 32-byte home space, 16-byte alignment and unwind metadata. Test normal and `--abi` from each real CALL, including no-effect, relevant conditions, interactions and boundary cases, using the Kit's CTR_EL0-shimmed Unicorn entry points. Run static stack audit, payload verification and focused tests, followed by applicable integration checks.
4. Bundle only verified rows; write one native check per family covering actual combat and preview, magic versus items, adjacency/movement and stacking. Native checks remain pending under this OFFLINE-only task. Do not install or launch the game.
