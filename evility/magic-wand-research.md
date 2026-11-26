# Magic Wand (D4 695): attack-stat selector research

Offline source and pinned-executable inspection; no implementation, proof, install or gameplay test.

## Finding

A real D5 CALL can select both INT and RES in the shared damage calculation, but the condition identifying precisely the D4 staff-attack set has not been established. It is a candidate, not a certified faithful carrier.

D4 `140102fa0` reads battle-record byte `param_2+0x298`; only case 7 queries `FUN_14010de70(attacker, 0x2b7, 0)`. This is not a skill-row byte: `1400f2a40`, `1400f5570`, `1401b34a0`, and `1401b3430` assign it from the associated unit's `+0x115b`. Its precise identity, potentially a weapon category, remains unproven. When nonzero, both forecast (`param_4 != 0`) and combat branches substitute attacker `+0xd40` for `+0xd30` and defender `+0xd58` for `+0xd38`; otherwise they retain the original pair. The source description says “Damage by a staff attack is based on INT.” Map this battle-record value to D5 weapon state and attack behavior before implementing it.

D5 `battle_damage_compute_target` `0x1401be860` handles both forecast and actual resolution (forecast flag `param_4`; callers include `path_throw_forecast` and `start_skill_action`). At pinned-executable CALL `0x1401bea2c`, `rcx` is attacker record, `rdx` is skill row (possibly null), and `r8d=0`; target `0x1401ce1e0` returns a stat index. The caller saves that result in `edi` and passes it to both `0x14015d760` at `0x1401bea4a` and `0x14015d6f0` at `0x1401bea5a`. Selector 1 reads attacker ATK and defender DEF; selector 3 reads attacker INT and defender RES, except that D5's separate defender override `0x140200310` can supersede the defender choice. Thus a wrapper at the selector CALL, returning 3 for a proven matching attack and owned evility and otherwise returning the original selector, is a plausible paired switch. It must preserve the calling convention, flags/register expectations and original behavior, including evility 65's existing defender override.

The skill 916 participant loop calls the selector again at `0x1401beae5` (then attacker stat at `0x1401beaef`); assess whether its attack is in the staff set before deciding whether to wrap that site too. Other calls to the selector include healing and UI/AI paths; do not globally replace the function. Search of this worktree and OLEFFECTS report found no claims on these two CALL sites, but a complete ownership audit remains required.

## Gates before shipping

1. Establish the identity and lifecycle of D4 battle-record case 7, and its equivalence to D5's basic attack and relevant staff skills, including null skill and offhand/skill mapping. D5's selector handles null and explicit stat overrides differently (`battle__damage.md` §D.10); simply testing a weapon category or existing selector value is not demonstrated equivalent.
2. Resolve precedence for the separate defender override and skill 916; inspect other forecast/UI paths for consistency. Confirm the hook's ability lookup uses the Kit's learned store as required.
3. Prove enabled/disabled, eligible/ineligible, null skill, forecast/combat, existing defender override and edge cases via actual CALL in Unicorn normal and `--abi`, then static stack and payload verification, tests and content/lease checks. Until then do not emit Magic Wand as faithful.

## Prior art checked

- Overlord `overlord/10_evility_runtime.c`: `stat_conversion_flat` converts a calculation stat, not the paired per-attack stat selection; no Magic Wand equivalent identified. Credit Cryswar for applicable prior art.
- Sorrow `research-20261014/states/leaves/battle__damage.md` and named export: documents damage selector indices, record offsets, defender override and forecast flag; its labels guide the investigation rather than prove source equivalence.
- D4 decomp `functions/140102fa0_FUN_140102fa0.c`; D5 decomp `functions/1401be860_battle_damage_compute_target.c`, `14015d760_damage_modifiers_attacker_stat.c`, `14015d6f0_damage_modifiers_defender_stat.c`, `140200310_damage_defender_stat_override.c`, and `xrefs.tsv`. Pinned exe CALL addresses independently read with Capstone.
