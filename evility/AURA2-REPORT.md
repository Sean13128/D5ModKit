Test fault: the inherited expectation omitted the recipient's own 28304 contribution; no engine fault demonstrated.
Three-unit fixture: PASS for Melodia, Noel and Citri, with paired Citri-aura-on/off tables at all four stat sites, normal and ABI.
Live still needed: corrected aura-only toggles with Champloo control, exact restore checks, and a readable Noel round-edge HP comparison; script prepared, NOT RUN.

# AURA2B offline handoff — 2026-11-12

Branch `aura2`, base `75db55fa75d49ee65eaa794a1172f3ea116fb2b0`, worktree `Local/Worktrees/aura2`. This lane changed the proof, prepared the live reader and guard tests, and wrote this report. No engine change, install, game launch, save access, merge or push. Installed kit, game folders and other worktrees untouched. Central deliverables are `Subprojects/Engine-Extensions/AURA2-*`; identical copies are committed under the worktree's `evility/` because the central reports directory is outside the source repository. Scratch and receipts: `/Volumes/Data/ai-tmp/codex/aura2b/`.

## Offline proven

### The failing test was wrong

`offline_proof_evilfx2.py` reads `got = d[case.get('field', 'output')]` and asserts `got == case['expected'], (got, case['expected'])`. Therefore the FIRST vector is **got**, the SECOND **expected**:

- got: `[50,0,32,32,32,32,0,14,0,0,0,0,0,0,0,0,0,0]`
- old expected: `[25,0,16,16,16,16,0,14,0,0,0,0,0,0,0,0,0,0]`

That synthetic recipient holds BOTH 28304 and 28092; another ally holds each main. It gets its own 28304 self rows (+25 HPmax, +16 ATK/DEF/INT/RES) PLUS the incoming 28304 aura (another +25/+16). Its SPD was already correctly expected as self 7 + incoming 7 = 14. The case is now named `overlay-two-28304-and-two-28092-holders-self-plus-incoming-aura`, with expected HPmax 50, four stats 32, SPD 14.

Trace: `wrap_status` preserves the unit/aggregate across the original callee, then calls `evil_apply` with family 2. `evil_next` merges learned self rows with the aura index; equal IDs do not suppress the pending self row. Its cursor preserves that pending row until the aura rows have been offered. `evil_presence` only skips impossible provider IDs; it does not suppress an aura because the recipient holds the ID. `evil_eval` does not require an aura's ID on the recipient, and `near_has` excludes the same panel. `evil_apply` adds every passing effect into the aggregate. `evility.table` keeps same-ID rows adjacent in authored order. These are existing semantics, not a new stacking design.

Boundary: `near_has` is existential, so this does NOT prove per-provider multiplication for three or more duplicate holders. That separate existing design limitation is outside this two-holder expectation fix.

### AURA1's live toggle wrote the wrong field

`AURA1-scripts-read.py:29` stores the **row start** in `a`. Line 36 writes `wr {a}` with 0 or the original mask. The table layout is ID at +0, family mask at **+4**. Consequently:

1. Turning off writes zero into the row ID, leaving its family mask enabled.
2. Restoring writes 2/66 (or 2048/2112), NOT the original evility ID, into the ID field.
3. Self lookup through the sorted ID table is damaged; aura rows remain reachable by their prebuilt index, with unchanged family masks and `near_has` provider conditions.

This explains the characteristic AURA1 result: Citri's self contribution disappears, the recipients' aura contribution does not change, and the supposed restore does not recover self stats. The AURA1 toggle is invalid evidence against the aura leg. This is a **source-proven harness defect**, not a replay of that live session. Native aura acceptance still needs the corrected read.

AURA2 writes `row_address + 4`, reads back the mask after EVERY write, and compares the entire 32-byte row before/after to ensure the ID and body are preserved. It refuses missing/ambiguous row runs and unexpected IDs/masks. Offline guard tests deliberately reject AURA1-style corrupted IDs, dropped writes and unequal restored snapshots.

### The exact three-unit lists

Fixture lists:

- Melodia: `[7132, 28092, 28093, 28095]`
- Noel: `[7130, 7131, 28020, 28021]`
- Citri: `[7133, 28304, 28305]`

Each unit is the subject in turn, with the other two active nearby allies. The table includes their real overlay subrows as well as mains; no weapons are equipped, so Noel's staff-conditioned 28021 is inactive. For each subject, a paired table disables **only Citri's aura rows**, leaving all three learned lists and Citri's self rows unchanged.

| Subject | Full aggregate: HPmax / ATK,DEF,INT,RES / SPD | Citri aura off | Incoming Citri difference |
| --- | --- | --- | --- |
| Melodia | 25 / 16 each / 7 | 0 / 0 each / 7 | +25 / +16 each / 0 |
| Noel | 25 / 16 each / 7 | 0 / 0 each / 7 | +25 / +16 each / 0 |
| Citri | 25 / 16 each / 7 | unchanged | 0 |

All six cases pass all four sites in both modes (24 checks per mode). Own self+aura row shapes do not block Citri's incoming aura in the evaluator. The proof checks aggregate percentages, not native final stats: its original-game callee is stubbed, so the 713x IDs are present in the actual lists but their vanilla effects are not executed. The ABI mode enters the real patched CALL instruction; normal mode enters its wrapper with the site continuation. This is not a proof of the complete installed table or live recalc state.

The inherited low-HP Noel cases also pass: HP 10 -> 12 at provider max HP 33, both self and incoming aura; the HP-shadow call is asserted. This proves the kit regen hook's integer result, not a real End Turn.

## SOURCE rule: duplicate holders

Original-only evidence was opened read-only under `Disgaea Source/Disgaea RPG JP (Android)/extracted/`. The three raw master bundles were SHA-256 checked against `extracted/MANIFEST.json` BEFORE decoding with existing UnityPy:

| Container (`sdcard/Android/data/com.disgaearpg.forwardworks/files/assetbundle/masters/`) | SHA-256 | Rows |
| --- | --- | --- |
| `leaderskill` | `285608a4015c12bdd1d48c2222ad0a2801887280235f58b9fc12b360e8819e88` | 4,445 |
| `help` | `3d70ff0358a6cb3d14af351d2748bb91139cf1467d823d54acff5040624c0b61` | 194 |
| `character` | `767a9da8c28bd59cb09262f5dcc70140ea9f380cbd64a301e21946e893e11778` | 952 |

`help` row 12 says all evility effects held by party members and the companion apply during battle. It explicitly gives special duplicate rules for normal-attack stat substitution (one takes priority by party order) and once-per-battle revival (duplicates still revive only once). `leaderskill` rows 3111/3115 give Citri's 16% four-stat/25% HP components, 1061 Melodia's 7% SPD, and 551 Noel's 8% provider-max-HP healing at turn start.

**Stacking is supported by the general “all effects apply” rule; that is an inference, not an independently traced source runtime. An explicit same-ID, two-holder stat-addition rule was not found in `masters/help`, `masters/leaderskill` or `masters/character`.** Thus a categorical source-runtime “stack” versus “do not stack” verdict remains unverified. No non-stacking rule was found for these stat evilities. The kit's two-holder sum above is proven separately and does not rely on guessing source arithmetic. No APK/native runtime was opened or emulated. No derived artwork or Global-client evidence was used.

## Live needed — reader prepared, not executed

`AURA2-scripts-read.py` follows AURA1's battle/deploy/read path, with these corrections:

- Captures all four unit pointers after deployment; asserts the three exact sample lists, Champloo's 28008, team and radius. Reads HP at +0x2CC8 and HPmax at +0x2CD8.
- Locates exact expected row runs in `.d5mod`; checks every mask write at +4, and preserves the rest of each row. Reads the complete PE section table rather than assuming a 0x400-byte header contains it.
- Citri **aura-only** is the FIRST toggle. Champloo aura-only is the next positive control; Melodia aura-only and self-only checks follow.
- Before and after every toggle: restore all masks, recalc all units, restore current HP/SP fixture values if natural max-HP clamping changed them, recalc, assert the complete snapshot equals `full`. It never writes derived stats/maxima to fake restoration. A restore failure stops the sequence. Finally attempts every mask restoration and battle exit even on error.
- Regen: one End Turn per off/on condition, near-full but non-full HP written/read back at the correct field; fixed pointers used afterwards; assert a single round increment at `0x145574AA8`, survival and unchanged maxima. Restore/recalc/full-snapshot gate separates conditions. A safe, nonlethal battle is a live prerequisite. Net HP with combat damage/other healing is explicitly NOT a causal regen proof; the script records raw values and does not award a regen PASS from them.

The coordinator still has to show positive recipient HPmax/four-stat deltas with Citri's aura enabled, a working Champloo ATK control and repeatable full restoration. AURA1's anticipated level-1 deltas (+2 four stats, +8 HPmax for recipients) must be checked against the new battle's actual bases/other bonuses. Noel needs readable healing with combat/other-heal contamination excluded. This lane has not established any new installed/native acceptance.

## Commands and verification

Run from `/Volumes/Data/Projects/D5/Local/Worktrees/aura2`, with scratch `O=/Volumes/Data/ai-tmp/codex/aura2b`:

```sh
# Deliberate negative: retain the known-wrong inherited expectation for this run,
# then correct it and rename the synthetic two-main case before positive runs.
D5_KIT="$PWD" /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python evility/offline_proof_evilfx2.py --json "$O/negative.json" > "$O/negative.txt" 2>&1
D5_KIT="$PWD" /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python evility/offline_proof_evilfx2.py --json "$O/normal.json" > "$O/normal.txt" 2>&1
D5_KIT="$PWD" /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python evility/offline_proof_evilfx2.py --abi --json "$O/abi.json" > "$O/abi.txt" 2>&1
/Volumes/Data/Projects/D5/D5Modkit/.venv-macos/bin/python -m pytest tests/test_evilfx2.py tests/test_evility.py tests/test_drpg_evilities.py -q
```

| Check | Result |
| --- | --- |
| Deliberate wrong expectation, negative control | **410/414 PASS, 4 FAIL, exit 1**; exactly that case at four sites, vectors shown above |
| Corrected whole proof, normal | **438/438 PASS**, exit 0 |
| Corrected whole proof, `--abi` | **438/438 PASS**, exit 0 |
| Related kit tests | **69 passed, 76 subtests passed**, exit 0 |
| `/Volumes/Data/Projects/D5/D5Modkit/.venv-macos/bin/python Subprojects/Engine-Extensions/AURA2-test-read.py` (workspace root) | **8/8 PASS**; import has no live side effects; expected gate failures caught by tests |
| `ast.parse` on both prepared scripts | **2/2 PASS**; live `main()` never called |
| `git diff --check` | PASS |

The new negative rerun's count is 414 (not the inherited receipt's 306); the current run's JSON/text receipts are authoritative for this lane. No explanation is assumed for the older receipt's different count. After the negative control the bad expectation was corrected; no deliberate wrong expectation remains in the committed proof. Related tests are scoped to the changed proof/table consumers; no engine code changed, so no broad suite or new hook audit was needed.

Other read-only commands: `agent-usage` (Codex values stale/unknown), `df -h /Volumes/Data` (376 GiB free), branch/status/base inspection; `rg`/`sed`/`cat` prior-art reads. A UnityPy heredoc verified and decoded the three source masters to scratch (3/3 hash checks; counts above); searching decoded help found the duplicate exceptions but no explicit identical-stat-ID arithmetic. No source dumps or game assets are committed.

## Prior art checked

- **Kit:** current base branch identified first; proof uses this `aura2` worktree. `d5lib/native/d5evil.inc.asm`: row header, `wrap_status`, `evil_apply`, `evil_next` merge, `evil_presence`, `evil_eval`, `evil_near`; `d5lib/evility.py`: family masks, table order/layout, aura index emission; real `drpg-evility-overlay.json`; `offline_proof_evilfx2.py`, `offline_proof_ex05e.py`, `abi_engine_ex05c.py`; `tests/test_evilfx2.py`, `test_evility.py`, `test_drpg_evilities.py`. Existing evaluator reused, no new hook.
- **Overlord (Cryswar, The Unlicense):** `class-support/OVERLORD-COMPARISON.md`; `overlord-source/overlord/10_evility_runtime.c` stat aura/include-self/stack parsing (aura default `per_holder`), `12_evility_hooks.c` configurable map-unit selector. Useful reference, not proof of the RPG source's duplicate rule; no code ported.
- **Sorrow:** `community/sorrow/RESEARCH-INDEX.md` and `ida-export-20261014/disgaea5_names.json` stat/recalc annotations. No separate RPG stacking rule there.
- **Full decomp:** `/Volumes/Data/Decomp/d5/functions/14021bfb0_unit_recalc.c` aggregate/final percent rounding, and `1401b97d0_unit_stats_evil_status_effects.c` aggregate consumer. Consistent with AURA1's nonzero minimum; no new rounding implementation.
- **Our lanes:** current prior-art map and `UNUSED-PRIOR-ART-20261108.md`; KANBAN AURA1/AURA2 entries; AURA1 report in full, its reader, SWEEP2 `common.py`, runner `live.py`/`r6h.py`; DRPGEVIL1/2 reports and source-pack tables/mapping references located by topic search. Earlier reports' claims that source bonuses stack were not promoted into source fact without the original-container check above.
