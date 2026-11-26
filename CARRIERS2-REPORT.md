# CARRIERS2 — more signature evilities for the imported characters (offline, 2026-10-30)

Lane: **CARRIERS2**. Worktree `Local/Worktrees/carriers2` (branch `carriers2`, from the `carriers` line at
`3e565e2`), bundle **`Builds/CARRIERS2-20261030/`** on `Builds/LIVE5_TEST16-20261030`. Offline only: nothing was
installed, launched, saved, played or pushed; the game folder, the installed kit, the profiles and both saves
were read, never written.

---

## 1. Plain summary

**One engine addition, ranked first by how many characters it unlocks, is built and proven — and it ships three
D4 evilities that had no carrier.**

The addition is **counting units of a kind**: "how many monsters are on the map", "how many cat-type units",
"how many allies carry this evility". D4 states a whole family of evilities that way and the Kit could only
count "any unit / ally / enemy", so every one of them was refused as unfaithful rather than approximated.

Ranked by distinct **imported characters** each addition unlocks (data in `evility/carriers2-ranking.json`,
counted by `tools/carriers2_ranking.py` over the D4 evility map, the review ledgers and the built bundles):

| # | engine addition | characters unlocked | what happened |
|---|---|---|---|
| 1 | **filtered unit counts** (species / class / type / carried evility, as a magnitude and as a threshold) | **9** | **built**, offline-proven, 3 rows shipped on 3 characters |
| 2 | a Magichange / Confine / summoning mode | 6 | **not buildable in this lane** — the mode itself is not built (see §6.1) |
| 3 | damage redirection / reflection / inversion | 3 | next card: one damage-landing wrapper + proof |
| 3 | evasion granted to or taken from other units | 3 | next card: a defender-side hit pass (OLEFFECTS §5 #13 records the gap) |
| 3 | Evil Area membership | 3 | next card: blocked on the D4 Evil Area → D5 field mapping (CARRIERS §5.2's "next proof") |
| 3 | the healing pass | 3 | next card: the three CALL candidates CARRIERS §5.3 already named |
| 5 | everything else (named-unit scaling, instant death, weapon category, movement state, facing, survival, rewards) | 1–2 each | one row of §6.2 each |

Only addition 1 was built in this sitting: additions 3 need a new pass (a wrapper of their own and its proof)
each, which is one card each, and addition 2 is an evidenced blocker rather than work.

**The three rows, and who has them:**

| evility (D4) | characters | status |
|---|---|---|
| **131 Dark Blood** — stats +5 % per monster unit on map | Beast Master (`D4_Class_1120`, class 14120) | **shipped**, row 8187 |
| **837 Meowyland** — stats +10 % × the # of cat-type units on the map | Pink (`D4_Unique_300`, identity 10380) | **shipped**, row 8837 |
| **841 Prism Emblem** — stats +50 % while seven allies with Prism Emblem are dispatched | Prism Ranger (`D4_Class_1220`, class 14220) | **shipped**, row 8841 |
| 837 Meowyland | Death Saber (`D4_Class_2200`) | **held** — the holder is itself a cat, and whether D4 counts the holder is not established (§6.2) |
| 841 Prism Emblem | Prism Red (`D4_Unique_320`, identity 10400) | **held** — D4 gives one evility to Prism Red and the whole Prism Ranger family, and one Skill.dat id has one owner; the class copy is the one that can field seven carriers (§6.3) |
| 127 Mass Psyche — stats +20 % per same-species unit | Petite Orc (`D4_Class_2020`) | **held** — same self-count question, and the Orc family is six ranks of which one is imported |
| 816 Prinny Annihilation, 875 Phantom Lover, 840 Friends, 658 Best Buds | Fuka, Marona, Prism Red, Gig | **held** — a per-class *defeat* counter, a Spirit species D5 does not have, and Evil Area (§6.2) |

**LIVE-CHECK: three evilities you can see fire in one battle** — Dark Blood (Beast Master + monsters, seconds),
Meowyland (Pink + cats, seconds), Prism Emblem (needs eight Prism Rangers on the map; it is the only one of the
three that costs setup). `Builds/CARRIERS2-20261030/LIVE-CHECK.md` is the sitting.

---

## 2. The carrier, in detail

| item | value |
|---|---|
| scales | **11 `map_monster`**, **12 `map_human`** (class-kind byte, unit record +0x2E25: 1 human male, 2 human female, 11 monster male, 12 monster female), **13 `map_class`** (row filter = class/character id at +0x2E04, the field `near_char` (44) already tests), **14 `map_has`** (row filter = a learned evility id, the scan `near_has` (26) already does) |
| condition | **49 `map_has_min`** — "at least a deployed units of relation b have learned evility c": the counted form of `near_has`, which is only existential |
| what counts | `evil_near`'s shipped 256-entry deployed-unit walk: on the map, not carried by another unit, with a stat record — exactly the rule `map_any`/`map_ally`/`map_enemy` already use. The subject is never part of its own count (that rule is `evil_near`'s and is unchanged) |
| row data | row dword 7 (the one dword the format-2 row never used) is the filter argument; the table layout, every other field and every budget are unchanged |
| mod data | `"per": "map_class"` + `"filter": <class id>`, or `"classes": [ … ]` which the emitter expands into **one row per class id** (rows of one id already add up, so a species of 13 classes is exactly "value × that many units") |
| new code | three scale dispatch arms in `evil_scale`, two filter arms in `evil_near`, one condition arm in `evil_eval`, one `mov` in `evil_apply`'s effect loop (and the same in `evil_dmg_sum`'s two loops) — no new wrapper, no new call site, no new section |

**Why no new wrapper.** Every other family in this runtime is a wrapper on a game `call`, because the number it
changes is produced by a game function. A count is not: it is what a *row's magnitude* multiplies, and the
multiplication already happens inside `evil_apply`, which every stat pass calls. So the addition lives entirely
in the evaluator/scale side of the existing section — which is also why it cannot break the ABI of any new site:
there is no new site.

**What was measured (offline, Unicorn, through the real patched CALL):** every case enters the shipped `stats`
wrapper at `0x1401B9575` (the site the project's own `stats` proofs use — the aggregate family is applied by
`evil_apply`, which every stat pass calls), runs the wrapper, the stubbed original and the exact `site+5`
continuation, and reads the aggregate back:

| proof | normal | `--abi` |
|---|---|---|
| `evility/offline_proof_carriers2.py` | **17/17 pass** | **17/17 pass** |

Cases: two deployed monsters count and a third human does not; a unit **off the map** is not counted; no
monsters; humans; `map_class` counts two classes of a list **additively** (10 × 2, not 10 × the last class); a
class outside the list is not counted; the subject is not counted; two units of the first class both count;
`map_has` counts three carriers of 8888 and ignores a fourth unit; `map_has_min` fails at six allies and passes
at seven and nine; **seven enemies and six allies fail the ally relation**; and the three shipped D4 rows play
D4's own numbers (Dark Blood +15 all stats for 3 monsters, Meowyland +40 for 4 cats of 3 classes with an Orc
excluded, Prism Emblem 0 at six and +50 at seven).

**Static and payload checks (measured):**

- static stack audit of the assembled section (`evility/static_stack_ex06.py` → `evility/carriers2-static-stack.json`): **70 sites / 114 calls / 0 findings** (+4 call edges over CARRIERS' 110, from the three new dispatched arms; alignment, home space, returns and rsp writes all clean).
- whole-kit payload (`integration/build_payload-158.py`, `D5_KIT` = this worktree): `.d5el`/`.d5mod` section 264,432 B at `0x1480cf020`, exception directory mapped, no section overlap, SizeOfImage covers the last section; **`verify_payload-158.py`: `problem_count 0`**. Payload `e0a273ee0e5a735c9a84ecf9d28d3a46c80f72e5db23ad711b674eccadfa53d3`, 11,830,272 B.
- regression, both modes: `ex05c` 141, `ex05d` 68, `ex05e` 88, `ex06` 75, `p3` 126, `p3b` 111, `oleffects` 99, `resistance` 17, `d4rev1` 94, `d4rev2_batch2` 111, `d4rev3` 109, `d4rev4` 93 — all pass, normal and `--abi`.
- kit suite: **39 failed / 916 passed / 4 skipped**, the same FAILED set as the `carriers` base measured in
  parallel (**39 / 914 / 4**); the +2 are this lane's new vocabulary tests. Diff-clean.
- allocation ownership: **0 errors / 0 other findings** (`tools/check_ownership.py --installed …/mods --profile …`; the "missing" warnings are TEST16's documented already-installed folders).
- whole-bundle table compile (`tools/carriers2_tablecheck.py`): 136 enabled folders, 111 ids, **132 rows of the 512 budget**, 97 conditions, 322 effects; row 8837 is the 13 table rows the class list expands to.

---

## 3. The content rows

`tools/carriers2_rows.py` is the only writer, from one source, `evility/carriers2-content.json`. Name, text,
value and mana are D4's own profile data (`mvp-successor-inputs-v1/source-profiles.json`, the learning
character's row); descriptions carry the number and a fullwidth ％ (no printf placeholder — the C1 crash class).

| row | D4 | pack | owner | kind | mana / slots | rule |
|---|---|---|---|---|---|---|
| **8187** Dark Blood | 131 | `D4_Class_1120` | 14120 | learnable | 5000 / 4 | `stats` all +5, `per: map_monster` |
| **8837** Meowyland | 837 | `D4_Unique_300` | 10380 | learnable | 1000 / 3 | `stats` all +10, `per: map_class`, 13 classes |
| **8841** Prism Emblem | 841 | `D4_Class_1220` | 14220 | learnable | 30000 / 5 | `stats` all +50, condition `map_has_min` 7 allies carrying 8841 |

- id rule: `8000 + D4 id` (the manifest's D4 extension band). All three are **free in every `Builds/*/mods` tree and in the installed kit** (checked by the writer and by a sweep of every bundle).
- the **13 cat classes** are measured from the live `char.dat` (read-only): Slumber Cat 2070–2075 and Felynn 2120–2125 are D5's two cat classes; **14700** is D4 2200's imported cat family, the class that learns Meowyland in D4 next to Pink.
- the **Orc 2030** and **Nine-Tails 2190** are deliberately outside the list: D4's cat family is the Nekomata line, and Nine-Tails is a separate species — adding it would be a guess. Extending the list later is a content edit, no runtime change.
- capacity, measured against the *vanilla* table, not assumed: D5's own Skill.dat has **1041 rows** and its 1000-position learned-evility bitmap ends at index 999 = id **8181**, so the first version of this row (`8000 + 131` = 8131) would have landed at index **995**, inside the bitmap, and pushed five vanilla rows (ids 8135–8179) down by one — an existing save's learned bits would change meaning.  The row was moved to **8187**, the lowest free id in the D4 band whose merged index (1006) is over the bitmap.  All four new rows now land at indices 1006/1012/1039/1040, **no vanilla row below index 1000 moves**, and the table ends at **1045 rows / 45 over the bitmap** with no inversion.  The D4 id is carried in `carriers2-content.json` and the mod's adaptation line, not in the row id.

---

## 4. The bundle

`Builds/CARRIERS2-20261030/` — a copy of `Builds/CARRIERS-20261030` (itself TEST16 + CARRIERS' carrier and row
8230, which this bundle keeps) with this lane's deltas:

| file | change |
|---|---|
| `kit-install/d5lib/evility.py` | scales 11–14, condition 49, row filter + `classes` expansion |
| `kit-install/d5lib/native/d5evil.inc.asm` | the scale dispatch, the two type filters, `map_has_min` |
| `mods/D4_Class_1120/…`, `mods/D4_Unique_300/…`, `mods/D4_Class_1220/…` | rows 8187 / 8837 / 8841 + their `.d5el` rules + the `mod.json` adaptation lines |

Everything else is byte-identical: **152 folders, 4,859 files, 1,698,145,218 B**, `INVENTORY.json` re-hashed
every folder, `VERIFY.json` the re-hash, `LEASES.json` the row census. `INSTALL.md` is this lane's (the
CARRIERS runbook is kept as `INSTALL-CARRIERS.md`, TEST16's as `INSTALL-TEST16.md`), and `LIVE-CHECK.md` is the
three-evility sitting (`LIVE-CHECK-CARRIERS.md` kept).

**Install note that matters:** the two kit files do nothing until **Press Install** rebuilds the exe.

---

## 5. Not shipped, and why — one blocker each

### 5.1 A Magichange / Confine / summoning mode (6 characters) — evidenced blocker
The mode is the evility: Physical Malice summons a unit per turn (Nemo ×3), Confine puts Ash on the map (Marona),
Eccarlate and Phantom Boost key on being Confined (`878/879`, Ash), Jet Black Sword raises equipment aptitude
during Magichange or fusion (Gig). SPECIALS held the twelve Magichange attacks for exactly this reason and
D4UNIQ3 re-stated it. Implementing a mode is not a carrier; it is a subproject, and nothing here pretends
otherwise.

### 5.2 The self-count question (Death Saber 837, Petite Orc 127)
Both holders are themselves the species they count. `evil_near` never counts the subject, which is proven and
documented; whether D4 counts it is not established (CARRIERS §5.2 found D4's Evil-Area count excludes the
holder at `1401ba0a0`, but that is a different evility). Pink and Beast Master are humanoids, so the same
question cannot change their numbers — which is why those two shipped and these two did not. **Next proof:** the
D4 count site for 837/127, or a live A/B with one and two Death Sabers.

### 5.3 One Skill id, one owner (Prism Red 841)
D4 gives 841 to Prism Red and to every Prism Ranger rank. D5 has one Skill.dat id with one `owner` field. Two
rows under two ids would split the count (a mixed party would never reach seven), so the class copy shipped and
the named copy waits on the shared-D4-evility decision D4UNIQ2 already recorded for Desco/Des X and row 8109.

### 5.4 The rest of the ranked list
`816` needs a per-class *defeated* counter (D5's counters at `0x146A5F054` are per team, not per class); `875`
needs a Spirit species D5 does not have; `840`/`658` need the D4 Evil Area → D5 field mapping; the 3-character
additions (damage redirection, evasion auras, the healing pass) each need a pass of their own with a wrapper and
its proof — one card each, in the order `evility/carriers2-ranking.json` gives.

---

## 6. Prior art checked

- **Overlord (Cryswar, The Unlicense)** — `class-support/OVERLORD-COMPARISON.md` and
  `overlord-source/overlord/10_evility_runtime.c`: his `stat_per_squad_unit` (`count_same_squad_units`) and
  `stat_per_unit_in_range` are the nearest shapes and were both considered — his counts take a *relation* and a
  radius, never a species/class/evility filter, which is exactly the gap this lane fills. His
  `holder_is_only_ally_on_map` is a filtered count of one kind (ally count == 0) and was the design reference
  for "the filter is a property of the candidate, not of the holder". No code was copied; the vocabulary and
  site map stay his by credit.
- **Sorrow** — `community/sorrow/RESEARCH-INDEX.md`, `ida-export-20261014/disgaea5_names.json`
  (`unit_stats_evil_percent`, `unit_recalc`, `neigh`), `states/leaves/battle__turn.md`. Navigation only; every
  claim here comes from the decomp, the bytes or an execution. The counted collector CARRIERS proposed
  (`neigh 0x1401f4020`) was **not** used: the scan this lane needed already exists in our own runtime
  (`evil_near`), so no new walk or footprint comparison was required.
- **Decomp** — `/Volumes/Data/Decomp/d5` (`1401b9575`'s callee chain, `unit_stats_evil_percent`
  `1401f2a10`, `unit_recalc` `14021bfb0`), `/Volumes/Data/Decomp/d4` (the evility getter family
  `14010de70`, `1401b4010`, `1401ba0a0`). The class-kind byte +0x2E25 and the class id +0x2E04 are the fields
  the runtime's own conditions already use, not new finds.
- **This repo** — `CARRIERS-REPORT.md` (the family it shipped and its "next proof" list, of which the
  counted-collector item is now closed by a different route), `OLEFFECTS-REPORT.md` (the 13 partial effects and
  the defender-evasion gap), `EVCAP-INVENTORY.md` / `d4-evility-map/d4_evilities.json` (the 325-row D4 map and
  its five `needs` families), `d4-review/LEDGER*.json` (the per-class `needs`), `D4UNIQ2/D4UNIQ3-REPORT.md`
  (which characters still miss what), `DD2GEN/CARRIERS.md` (the DD2 rows: every one that needed a count was
  either a same-named D5 row or a per-event accumulator, so none of them is in this addition),
  `D1CSPECIALS-REPORT.md` (D1 has no evilities at all — nothing to carry), `LANE-RULES.md`, `abi-review/*`.

---

## 7. Files, commits, next steps

**Code (worktree `Local/Worktrees/carriers2`, never pushed):** `d5lib/evility.py`, `d5lib/native/d5evil.inc.asm`,
`tests/test_evility.py`, `evility/offline_proof_carriers2.py`, `evility/carriers2-static-stack.json`,
`evility/carriers2-content.json`, `evility/carriers2-ranking.json`, `tools/carriers2_rows.py`,
`tools/carriers2_bundle.py`, `tools/carriers2_tablecheck.py`, `tools/carriers2_ranking.py`, this report.

**Build output (outside git):** `Builds/CARRIERS2-20261030/`; payload receipt
`/Volumes/Data/ai-tmp/hermes/carriers2/payload/`.

**Next steps, in order (each is a card):**

1. Install on Sean's go-ahead, Press Install, restart, run `LIVE-CHECK.md` — Dark Blood and Meowyland are
   minutes; Prism Emblem needs eight Prism Rangers.
1a. **Composing on TEST17** (the coordinator's `Builds/LIVE5_TEST17-20261030`, which deliberately did not
   include this lane): the deltas are two kit files and four mod folders, and both lane branches are on
   the same `carriers` line, so it is a copy of those six paths onto TEST17 plus the row writer's
   `--check` and the bundle receipt tool. Nothing in this lane's code depends on a TEST16 file.
2. The damage-redirection addition (Fenrich 813, Artina 891, Nemo 872 — 3 characters): one wrapper where damage
   is applied to the target, one proof.
3. Decide the shared-D4-evility ownership rule (Prism Red's 841, Desco/Des X's 8109) — one decision, several
   rows.
4. The self-count question for the two cat/orc holders, then rows 837 on Death Saber and 127 on Petite Orc.
5. The D4 Evil Area → D5 field mapping (CARRIERS' own next proof), which unlocks 840/658/857/854 and 3 characters.
