# D4 combo evilities 446, 448, 449 — offline research

No carrier, content row, hook proof, installation or gameplay acceptance is claimed. D5 offers useful action-context fields and CALLs, but source-equivalent state and stage have not been established.

## D4 behavior observed

`14010aca0` resolves actor records through `param_1+0x1f0` and `param_2+0x1f0`. For Second Attack (446 / `0x1be`), when the short at `param_3+0x7ac` is nonzero and the first actor owns 446, it fetches that evility's value and multiplies the current `param_4` by `(100+value)/100`, with integer truncation. This happens in the middle of a larger sequence of multiplicative damage adjustments, not in an attack-stat bonus stage. The source description says damage increases 50% when part of a combo; trace the writers and all meanings of `+0x7ac` before identifying it with a D5 field.

For Assist (448 / `0x1c0`) and Marking (449 / `0x1c1`), D4 `1402e0490` and three branches in `1402e13a0` check whether `DAT_141a1ca30+1 < DAT_141a1ca2c`, then check the current actor's evility and write 1 to distinct bytes at `DAT_1414794c9/4ca + (current index+1)*0x4478`. This supports a next-action handoff, with separate flags, rather than a generic nearby aura. The source descriptions say the next ally in a combo gets 100% accuracy and 100% critical rate respectively. The readers of these bytes, their lifecycle and exact handling of misses, interruptions, multi-target attacks, and ally relationship are not yet traced; do not claim those details as measured.

## D5 observations and candidate CALLs

Sorrow's battle damage research identifies ActionContext `+0x276b8` as a short combo/accuracy step, `+0x27690` as chain index and `+0x27718` as attack kind (6 combo); the second participant list is at `+0x27320`, count at `+0x273c0`. D5 evility 1123 in `1401f6300` tests `step > 0 || attack_kind == 6`, then adds its value to **pre-defence attack bonus**, so that condition and stage cannot be assumed equivalent to D4 446. D5's 2122 native Team Formation is separately documented as team-attack damage and is not proof of combo equivalence.

Pinned executable direct CALLs relevant to evaluating candidate designs:

| CALL | Target | Observation |
|---|---|---|
| `0x1401bed6b` | `0x1401c1650` | damage multiplier; evaluate its numerical stage against D4's sequential multiplication |
| `0x1401be961` | `0x1401c1ee0` | hit calculation; inspect forecast and guaranteed-hit semantics |
| `0x1401bed84` | `0x1401c13e0` | critical/guard roll, including RNG and precedence |
| `0x1401c144f` | `0x1401c1d00` | crit chance within roll; caller state and 100% behavior need tracing |

These are leads, not verified hooks. Inner CALLs `0x1401c169d` (damage multiplier rules), `0x1401c2318` (hit rules), and `0x1401c1e94` (crit rules) are already owned by the current `.d5el` runtime; obey OLEFFECTS ownership and do not patch them again. Fully audit candidate outer CALLs and other lanes before claiming one.

The essential missing proof for Assist and Marking is an ordered, correctly scoped previous-provider identity in the D5 action sequence, including whether a later target and each action receive a one-shot effect. A participant list alone does not establish that order or a handoff. No wrapper should substitute generic party-wide or adjacency checks.

## Next proof gates

Trace D4 `+0x7ac` producers and the next-action flag consumers; trace D5 action creation, sequence and cancellation for first/subsequent attacks, multi-target and team attacks. Match D4's multiplication order and integer rounding, determine accurate guaranteed hit/crit precedence, and audit hook ownership. Prove each candidate through the real CALL normal and `--abi`, static stack and payload verification, and focused tests, then review content rows/leases and EVCAP storage.

## Prior art checked

- Overlord `overlord/10_evility_runtime.c`: no combo implementation found; its general damage, hit and crit effects do not themselves provide ordered next-actor semantics. Credit Cryswar for reused designs.
- Sorrow `research-20261014/states/leaves/battle__damage.md` and named export provide D5 action-context field and calculation labels; labels are navigation evidence, not source-equivalence proof.
- D4 decomp `14010aca0_FUN_14010aca0.c`, `1402e0490_FUN_1402e0490.c`, `1402e13a0_FUN_1402e13a0.c`, `14022fad0_FUN_14022fad0.c`; D5 decomp `1401f6300_damage_attack_bonus_rules.c`, `1401f8fd0_damage_damage_multiplier_rules.c`, `1401c1650_damage_damage_multiplier.c`, `1401c1ee0_damage_hit_roll_hit.c`, `1401c1d00_damage_crit_chance.c`, `1401c0c60_damage_modifiers_post_modifiers.c`. CALL addresses independently checked using Capstone on the pinned original executable.
