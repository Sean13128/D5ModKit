# D4 native combat rules

D4 Evilities can depend on native activation, direction, source aggregation and
ordered numerical operations. A copied data row or existing D5 Evility alias
must remain labelled as an adaptation until these contracts are verified.

The Aegis pilot has established source magnitude and integer arithmetic plus
candidate D5 actor/list/lookup interfaces. Faithful implementation remains
blocked on direction-producer equivalence, active-source stacking/eligibility,
modifier ordering and hook lifecycle verification. No native patch is produced.

D5's existing direction-based damage reducer uses single-precision arithmetic;
a source-compatible Aegis step requires separate signed integer multiplication
and truncation at its own verified stage. Merely changing the donor's direction
and ID would change boundary, stacking or rounding behavior.

Pinned native evidence and the reproducible contract inspector are private project
research outside this checkout. Complete those gates before adding a public rule
API or connecting the rule to the content-pack installer. Gameplay acceptance
must remain separate from static inspection and arithmetic examples.

## What EX-06 adds here

The Kit can now express a damage-time skill rule as data: `patches/skillrules/skillrules.json`
(`docs/SKILL_RULES.md`), keyed by the skill id, with the evility condition vocabulary. Aegis's D4 row
(`mskill.dat` row 392, parameter 30 at `+13`) becomes one row with the `attack_dir` = front condition and
`taken` = −30, and its integer step `v × (100 − 30) / 100` runs inside
`damage_damage_reduction_rules` (0x1401FB2E0) after that function's own work.

That closes the *rule expression* gap, not the Aegis gates above:

* **Direction source.** `attack_dir` reads the target entry's value that D5 itself computed (front/side/
  behind). The Aegis report shows D4's angle producer, D5's producer and D5's prepared attacker facing
  disagree even at adjacent diagonals; using D5's classification is a deliberate D5-native choice, not
  proof of numeric equality with D4.
* **Stacking/eligibility.** One row is one rule; D4's active-source aggregation, equipment and Geo
  providers, and the single-innate admission rule are not modelled. Household rules that must fire
  once per source have to be expressed as one row or verified separately.
* **Ordering.** The Kit's contribution is added after the original reduction function for that hit; the
  relative order against D5's own reduction rules (its binary search over vanilla ids) is
  "original first, then the extension's sum", which is not the D4 order.
* **Lifecycle.** Offline proof only: no Windows unwind, no game process, no installation. No native
  substitution or donor suppression is implied (the 7000→12 alias remains in place).

So an imported Aegis row can now be written and proven offline; it is still **adapted/partial** for
gameplay until the gates above are closed and a live check is run.
