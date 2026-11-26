# PTSPRITE — Recruiter-wheel sprite/animation fixes (S1–S3), offline
Lane: Hermes (opencode-go / deepseek-v4.1-flash). Worktree `Local/Worktrees/ptsprite`
(branch `ptsprite`, cut from `integration/next2` @ 9ed132a — the integration line whose pack builds the
installed LIVE5_TEST profile was assembled from; PTFIX's `dupfix` sits on the same base, so the D4 pack
builder is byte-identical to the one that built the installed packs).
Rules: offline only, no game/installed-kit/profile/save writes, no Sean mods, never push.

Report: `Subprojects/Engine-Extensions/playtest/PTSPRITE-REPORT.md`.
Renders (game art, outside git): `Subprojects/Engine-Extensions/playtest/ptsprite-renders/`.

## Battery (what "rerun" means)
Kit suite (`pytest tests -q`, compare the FAILED set to the known 39 environment failures), evility proofs
`ex05c/ex05d/ex05e/ex06/p3/p3b` normal + `--abi`, static stack audits (4 receipts + mastery), mastery proofs
(`proof_mastery`, `--abi`, `abi_engine_mastery`, `static_stack_mastery`), whole-kit payload build +
`verify_payload-158.py`, ownership checker + manifest drift.

## 2026-10-27 — baseline on p3b
- Suite 432 passed / 39 failed / 1 skipped; FAILED set identical to the known environment list.
- Proofs all green (141/68/88/75/126/111 each normal + `--abi`); static 54 sites / 83 edges / 0 findings;
  mastery 10/10, 13/13; payload 11,828,224 B sha256 f928f859…, one `.d5mod`, 144 header bytes left, 14/14
  sites, verify 0 problems; ownership 0 errors, manifest up to date.

## 2026-10-27 — merge 1: hub-automation
- `db07e30`, clean (`ort`), 2 files / +380: `tools/d5ctl_relay.py`, `tests/test_d5ctl_relay.py`.
- Suite 443 passed / 39 failed (same FAILED set, +11 new passes); proofs, payload (identical bytes/sha) and
  ownership unchanged.

## 2026-10-27 — merge 2: d1c-158
- Clean (`ort`), 8 files / +1,522: `d5lib/d1cart.py`, `d5lib/d1skill.py`, `d5lib/nativeimports.py`,
  `d5lib/sourceimports.py` (+dd2/d1c prepared-art sources), 4 test modules.
- Suite 484 passed / 39 failed (same FAILED set, +41 new passes); proofs all green; payload identical
  (11,828,224 B, same sha256); ownership 0 errors, manifest up to date.

## 2026-10-27 — merge 4: p4-overlord-content
- Clean (`ort`), 7 files / +1,070: `tools/overlord_port/{convert,finalize,smoke_manifest,anm_foreign,
  probe_hybrid,probe_map,probe_template}.py` (the Stella conversion; the mod itself stays outside the repo).
- Suite 491 passed / 39 failed (same FAILED set); proofs, payload and ownership unchanged.

## 2026-10-27 — P1 manifest gap reported by P4 (fixed with tests)
- Reproduced P4's three findings first: `check_ownership.py --claims p4-claims.json` → 3 errors
  (`anm_id 224-225`, `anm_id 10224`, `job_class_id 224`).
- `job_class_id`: 1-1009 vanilla split into 1-79 vanilla / **80 kit** / 81-222 vanilla / **223-403 kit** /
  404-1009 vanilla. `anm_id`: **80 kit**, **223-403 kit** (unique sprite sets = row .. row+2),
  **10080-10081 kit**, **10223-10404 kit** (cut-in / portrait = 10000 + row .. +1); everything else vanilla.
- Rule `anm_id.rules.unique_keyed_graphics` = rows 223-403, sprite_span 3, portrait_offset 10000,
  portrait_span 2; a test derives bands and rule from each other (drift gate).
- Deliberate refusals, documented: rows 402-403 (sprite set reaches vanilla 404/405) and Xenolith's +1/+2
  sprite banks 81/82 (vanilla rows).
- 8 new tests (`UniqueGraphicsTest`, fixture `overlord-stella-20300.json` = P4's claims unedited);
  32 ownership tests pass; manifest regenerated (113 bands); `--check` clean; `MANIFEST.md` re-rendered.

## 2026-10-27 — pack rebuilds found two integration defects (DD2 abilities, D1C help ids)
- D1C: humanoids 2/2 and monsters 11/11 rebuilt byte-identical to the accepted pack, 0 problems; uniques 22/22,
  all gates True, 0 problems, but help ids moved 22727-22748 → 22771-22792 because the builder re-records them
  in `Research/source-packs/d1c/batches/unique-leases.json` (+22 per run). Art, skills, quests 302-323 and
  slots 545-566 unchanged.
- DD2: first rebuild died in the pack validator (`KeyError: 'learn'`) because the merged `nativeimports` is the
  D1 Complete version and drops DD2 abilities. Reconciled: reviewed source map route + D1C `skills`/`whole_body`
  route in one module, `d5lib/sourcemaps/dd2.json` added, `_apply_innate` writes the four slots and the count,
  receipt gains `abilities`/`voice`/`text_folding` and per-row `learn`/`innate`. 15 tests (`test_dd2abilities.py`).
  Pack: `ready-not-installed`, 0 problems; 42 of 45 payload files byte-identical to the accepted pack, the 3
  deltas are `mod.json` text plus `anm00470/471.lzs`, which need the unmerged `ownanim` own-idle cycle.
- D4 pilots 0 problems; breadth A 6/6 and B 10/10 built + validated + packed, 0 failures; Overlord_Stella
  re-converted with `claims_errors: 0` (was 3 before the manifest fix), finalization and smoke green.

## 2026-10-27 — final battery on the finished branch
- Suite 514 passed / 39 known environment failures / 1 skipped, FAILED set identical to the baseline.
- Proofs: ex05c 141/141, ex05d 68/68, ex05e 88/88, ex06 75/75, p3 126/126, p3b 111/111 — each normal and
  `--abi`; static stack 54 sites / 83 edges / 0 findings; mastery 10/10, 13/13, static 0 findings.
- Payload 11,828,224 B sha256 f928f859…, one `.d5mod`, 144 header bytes left, 14/14 sites, verify 0 problems.
- Ownership 0 errors, 113 bands, manifest `--check` clean.
- Offline proof that nothing was written: `find` over the installed kit (→ Steam `D5ModKit`) and the whole
  Steam D5 folder newer than the lane's start marker → **no files**.
- Report: `Subprojects/Engine-Extensions/INTEG4-REPORT.md`.

## Merged lane logs (kept verbatim from each merged branch)

### dd2-coverage (merged as commit 3)

# dd2-coverage — PROGRESS

Lane: full DD2 skill + Evility coverage (offline). Base 063b240 (feature/bundle-158 line), worktree
`Local/Worktrees/dd2-coverage`, branch `dd2-coverage`. Nothing installed, nothing launched, the live
game / installed kit / Steam folder were not touched.

## Log

- [1] Context read: NORTH-STAR, AGENTS "Prior art first", LANE-RULES, PRIOR-ART-MAP, dd2/STATUS,
  DD2-NEEDS, BUNDLE-158/dd2-rebuild.md, dd2-evility-map/README, EVILITY-VOCAB, VOCAB-NOTES,
  `d5lib/evility.py` (families + COND_KINDS at this base).
- [2] Worktree at 063b240. Ported `d5lib/dd2source.py` from the accepted dd2-source-pack lane —
  the reader module only (no nativeimports / sourcemaps / read_prepared / ownanim), commit 47622a3,
  plus `tests/test_dd2source.py` (7 tests, all pass on synthetic bytes).
- [3] Full-suite check: `pytest tests -q --ignore=tests/test_offlinepaths.py` → 24 failures on this
  branch, the identical 24 on a clean 063b240 worktree (same files: gamepacks 12, gamepacks_ui 4,
  d4expansion 2, d4source 1, d4unique 2, all macOS/env). No new failures; +7 passing (the new tests).
- [4] Read-only dumps: DD2 START_4.dat (386 skills, 227 Evilities, 558 char rows) and the repo's own
  D5 table copies (magic.dat 583, Skill.dat 796). Cross-checked my DD2 dump against the accepted
  `slice/packet/skills-evilities.json`: 386/227 ids, zero name differences.
- [5] `Research/source-packs/dd2/coverage/coverage_full.py` — the generator. Rules per skill block
  (system, weapon tier, spell slot, tower, dummy, character/class with a donor, book, support,
  mounted), an Evility family+trigger matcher against D5's text, and `review.json` for hand
  decisions. It fails the run on any unreviewed row and on any input whose sha256 does not match.
- [6] Reviewed decisions written in `review.json`: 34 DD2 character -> D5 donor characters (each
  with its reason), the six accepted slice skill decisions, the accepted slice Evility decisions
  (2180/2182/2181/80/81/71), 27 needs-new-logic Evility rows each with its covering effect, and
  per-row fixes where the matcher picked a neighbour instead of the real twin.
- [7] Outputs: `Research/source-packs/dd2/COVERAGE-FULL.md` + `Research/source-packs/dd2/coverage.json`
  (386 skills: 156 exact / 67 adapted / 108 lookalike / 55 omit; 227 Evilities: 47 exact / 69 adapted
  / 83 lookalike / 27 needs-new-logic / 1 omit) + the ten new families' build readiness.

## Incident, disclosed

While building the report I hit a variable-shadowing bug in my own generator: the report writer's
`path` variable was rebound by a loop over the input table list, so one write landed on
`Research/d4-expansion-20261018/mvp-evility-query-helpers/d5-Skill.dat` (a repository copy of D5's
Evility table) and replaced it with the report text. It was restored immediately from an identical
byte copy (`Subprojects/Engine-Extensions/d4-breadth/builds/C-named/300/finalized-logical/Database/
Database_0.dat/Skill.dat`, sha256 `fa604b26…`, the file's original pin) and the generator now refuses
to run unless that pin matches, so a repeat would fail before writing. No game file, save or
installed-kit file was involved.

## Open / not done

- Nothing was installed (out of scope for this lane). Native behaviour of any verdict is unverified.
- DD2 magic.dat power fields are not decoded, so no damage-number comparison exists.
- Registry ids are taken from the class registry and not re-checked against live mod state.

## 2026-10-27 — merge 3: dd2-coverage
- `PROGRESS.md` add/add conflict: resolved by keeping this INTEG4 log and appending the lane's own
  log verbatim above (nothing dropped).
- Code merged clean: `d5lib/dd2source.py` (+324) and `tests/test_dd2source.py` (+97).
- The lane's disclosed incident (its generator overwrote a repo copy of D5 `Skill.dat`, restored from
  an identical pinned copy) is recorded in its log and introduces no file change on this branch.

## 2026-10-27 — lane d4-runtime-4: D4REV2 vocabulary (offline)
- Four D4 evilities now carry D4's own number on our own rows: 391 Advance Guard (new condition 47
  `defending`, the game's own 1152 gate), 392 Aegis (`attack_dir` on a `taken` row, subject-slot
  fallback), 347 Bloody Battle (new scale 7 `defeated_enemy` on the battle's own 0x146A5F054 counters;
  8 `defeated_any` is D5 140's arithmetic), 815 Absorption (new family 1048576 `absorb`, wrapping
  FUN_140200D20 and re-applying its accumulator at unit_stats_evil_overrides).
- New ids only: condition 47, scales 7/8, family bit 1048576, wrapper tag 0xE70014 at site 0x1401AEE62.
  Format 2, the row layout, every earlier id and the `.d5el` name are unchanged.
- Proofs: `evility/offline_proof-d4rev2.py` 30/30 normal and 30/30 `--abi` from the patched call sites
  (8392 front only, 8391 gated by the game's helper, 8347/8348 counter scaling, 8815 both halves);
  `evility/static_stack-d4rev2.py` findings 0 (55 sites, 92 calls). Regression: ex05c 141/141 (both
  modes), ex05d 68/68, ex05e 88/88 (both), ex06 75/75 (both), p3 126/126, p3b 111/111.
- Kit tests: 39 failed / 516 passed / 1 skipped (baseline 39 / 515 / 1) — no new failures.
- Report: `Subprojects/Engine-Extensions/evility/D4REV2-REPORT.md`. Nothing installed, launched or pushed.

## 2026-10-27 — INTEG5: d4-review-2 + drpg-sample merged, all packs rebuilt, LIVE4 bundle (offline)

- Merge 1 `d4-review-2` @`d43ba93` (carries `d4-runtime-4` and batch 1) → `0fdac4d`, **no conflict**:
  `d5lib/evility.py` (+69), `d5lib/native/d5evil.inc.asm` (+259), `tests/test_evility.py` (+105),
  `PROGRESS.md`. Merge 2 `drpg-sample` @`15a8163` → `d25f636`, **no conflict**: `tools/build_drpg_sample.py`,
  `tools/finalize_drpg_sample.py`, `tools/make_smoke_manifest.py`, `tests/test_drpg_sample.py` (+850).
  `p2-mastery` deliberately not merged.
- Battery after each merge: suite 514→**517**→**520** passed / 39 known env failures, FAILED set identical to
  INTEG4's baseline; proofs ex05c 141/141, ex05d 68/68, ex05e 88/88, ex06 75/75, p3 126/126, p3b 111/111,
  d4rev1 94/94, d4rev2_batch2 111/111, d4rev2-runtime 30/30, each normal **and** `--abi`; static 55 sites /
  92 call edges / 0 findings (two audits); payload 11,829,248 B `b609ada0…` (+1,024 B vs INTEG4, one
  `.d5mod`, 14/14 sites, verify 0 problems); ownership 0 errors / 113 bands; manifest up to date.
- Packs rebuilt on this branch, validators green: D4 pilots (preflight passed, `problems: []`), breadth A
  **463/0** and B **612/0** with the reviewed rows re-applied (`selfcheck_defects.py` 7/7), D1C 2+11+22
  (all gates True, 0 problems), DD2 slice (0 problems, `ready-not-installed`), Overlord_Stella
  (`claims_errors 0`, smoke ratio 0.968), DRPG 3 characters (66 outputs, smoke green, ownership 0).
  D1C humanoids/monsters payloads byte-identical to INTEG4; DD2 mod trees byte-identical.
- Two defects found by doing the work: (1) `apply_to_packs.py` / `batch2_apply.py` **default to check mode**
  and exit 1 without `--write`, so a rebuild followed by an "apply" leaves unreviewed rows in the packs
  (`validate_review.py` caught it with 35 failures, including the 8065/8066 Valvatorez Skill-id collision);
  (2) the rebuilt pilot pack ships **no** `patches/classes/mastery.json`, unlike bundle-158, so 1350 has no
  class XP unless the file is added. Also: `evility/static_stack_ex05e.py` rewrites the tracked receipt
  `evility/integration-next-static-stack.json` on every run — reverted, not committed.
- Deliverables: `Subprojects/Engine-Extensions/LIVE4/INSTALL.md` (whole-kit install, rsync backup of the
  resolved path, `rsync -a` without `--delete` + stale-file check, 7 stages, six-slot mastery plan A/B,
  `§restore-Sean`, hub.py live checklist, rollback) and `INTEG5-REPORT.md`. Bundle:
  `/Volumes/Data/Projects/D5/Builds/LIVE4-20261027/` — 59 mod folders, 0.87 GB, `INVENTORY.json`.
- Nothing installed, launched, saved or pushed; `find` over the resolved installed kit and the Steam D5
  folder reports 0 files newer than the lane's start marker.

## 2026-10-27 — INTEG7: D4 batch 3 merged, battery rerun, packs rebuilt under packed mastery (offline)

Worktree `Local/Worktrees/integration-next2`, branch `integration/next2` @`3019726`. (INTEG6 logged only in
`Subprojects/Engine-Extensions/PROGRESS.md`; this branch log resumes here.) Offline only: nothing launched,
installed, saved or pushed; `Local/Installed D5ModKit` and the Steam folder were read, never written.

### Merge 1: d4-review-3 @2784b36 -> f0767ef
- Clean (`ort`), 2 files / +77: `evility/abi_engine_ex05c.py` (+`stub_returns`, so a proof can fix
  `game_rng_draw`'s answer) and `tests/test_evility.py` (+65: the batch-3 row shapes).
- Suite after: **39 failed / 585 passed / 3 skipped**, FAILED set byte-identical to INTEG6's `m3-wiring`
  baseline (`diff` of the FAILED/ERROR lines, not a count). The new `test_d4rev2_batch3_rows_compile` passes.

### Battery (receipts `/Volumes/Data/ai-tmp/hermes/integ7-20261027/post-merge/`)
- Evility proofs `ex05c ex05d ex05e ex06 p3 p3b`: **12/12 exit 0** (normal + `--abi`).
- D4 review proofs `d4rev1` 94/94, `d4rev2_batch2` 111/111, **`d4rev3` 109/109** — 6/6 exit 0 normal and
  `--abi`, entered through the game's own patched call sites.
- Mastery `proof_mastery` 10 + 13 checks, `proof_packedmapper` 9/9 + 11/11 `--abi`, `proof_packedaward`
  9/9 + 11/11 `--abi` (6/6 exit 0; packed proofs with `--original /Volumes/Data/ai-tmp/claude/pinned/disgaea5.exe`).
- Static stack: evility **55 sites / 92 calls / 0 findings**; packed mastery **0 findings** for both the
  2-family and the 45-family configuration.
- Payload `b609ada0…` **11,829,248 B** (byte-identical to LIVE4/INTEG6), one `.d5mod`, 144 header bytes left,
  14/14 sites, `problem_count 0`. Packed payload `2403ce3c…`: 18 sites all calling the claim, screen bound 49,
  `.d5cm` absent.
- Ownership: **0 errors, 113 bands**; manifest up to date.

### Packs rebuilt — 29 families declare packed mastery (details: INTEG7-REPORT.md §4/§5)
- A: 6 fresh builds (`--mastery --mastery-mode packed`) + batch-1 reviewed rows; B: 10 fresh builds + batch-2
  rows; D: reassembled from the frozen build + batch-3 rows; pilot: content untouched + declaration.
- `Subprojects/Engine-Extensions/integration/pack_mastery.py` (new) writes each declaration in the builder's
  shape and verifies it through `masteryext.families_from` + `packedmasteryhook.mode_for`; pack manifests
  refreshed so they record what the mods declare.
- Validators: `validate_review` **518/0**, `batch2_validate` **612/0**, `batch3_validate` **830/0**,
  `selfcheck_defects` **7/7**, `batch3_selfcheck` **7/7**; all three appliers idempotent (0 changes, 0
  problems); `check_ownership.py` 0 errors / 113 bands; final suite 39 known / 586 passed / 2 skipped
  (FAILED set identical to the baseline).
- Three defects found and fixed: batch-1's applier had no cross-pack slot-id rule (pack A took pack B's
  7006/7007; the moved row's `id` field must move too), `batch2_validate` refused pack D/C's shared 8026 row,
  and `selfcheck_defects` defect 5 had stopped injecting a defect.
- Open for the coordinator: packs A/B ship 8062/8067/8085/8228, the ids INTEG6's pilot re-derivation reported
  as already claimed by the installed D1C packs (repo-side validators cannot see the live kit).

## MIGFIX — safe opt-in path for Sean's save under packed mastery (2026-10-27, offline)

Lane: Hermes (deepseek-v4.1-flash). Worktree `Local/Worktrees/savemig`, branch `savemig`. Nothing installed,
launched, saved or pushed; the live save folder, the installed kit and the pinned exe were read only.

- `d5lib/masterymigration.py` — the family mapping is now decided by `plan(leases, packed, target)`:
  a six-slot family the build itself packs is written as **itself** (1350 -> 1350, identity: no class,
  row, sub-class or unlock-bit edit, only the 144-byte spare area of units that hold legacy data).
  Re-homing is refused for a packed family. Added `clear_legacy()` — the supported 'clear' operation
  (zero the legacy area so the hook's `pm_blank` can initialise it; nothing else changes). Commit `8c0bfb4`.
- `tests/test_masterymigration.py` — 15 -> 20 tests: the plan's identity/rehome split, identity keeps the
  class and touches only the spare area, all-zero units untouched, "a packed family is never re-homed"
  (the exact options the failing run used), clear zeroes exactly 6 bytes on a Ben-shaped fixture, clear
  refuses stale inactive data and leaves packed areas alone.
- Suite: **39 failed / 591 passed / 2 skipped**, FAILED set `diff`-identical to `f0767ef` (39/585/3).
- Proof on copies of Sean's real AutoSave: `mastery/savemig/run_migration.py` runs **A clear** (6 decoded
  bytes, 6 runs, 0 unexplained, Ben class 1355, area all zero) and **B migrate** (12 bytes, 7 runs, 0
  unexplained, class 1355, row 472, subclass 0, packed reader `{1350: (4,4,4,4,4,4)}`), then 10 refusal
  cases with no output. Original sha256 `b4fecd48…` unchanged before and after.
- Outputs: `/Volumes/Data/ai-tmp/claude/save-migration/{cleared,migrated}/AutoSave.sav` (+`.bak`);
  the broken 14250 artefact moved to `superseded-14250/`.
- Docs: `Subprojects/Engine-Extensions/mastery/OPT-IN.md` (tonight's step-by-step), `MIGFIX-REPORT.md`,
  `LIVE5/INSTALL.md` §6.2/§10 corrected, `SAVEMIG-REPORT.md` marked superseded.

## 2026-10-27 — INTEG8: batch 4 + MIGFIX merged, battery after each merge, the 88-mod packed bundle built (offline)

Worktree `Local/Worktrees/integration-next2`, branch `integration/next2` @`fdde964` -> **`99f6b35`**. Offline
only: nothing launched, installed, saved or pushed; the installed kit and the Steam folder were read, never
written. The stray untracked `evility/integration-next2-static-stack.json` was **moved** (not deleted) to
`Subprojects/Engine-Extensions/receipts/integ8/`.

### Merges
- `d4-review-4` @`e8d4789` -> `de6a18b`: clean (`ort`), 1 file / +71 (`tests/test_evility.py`, the batch-4 row
  shapes + the writer's refusals).
- `savemig` (MIGFIX) @`77ec8a2` -> `99f6b35`: `d5lib/masterymigration.py` (+310/-85, identity mapping that
  refuses to re-home a packed family, new `clear_legacy()`), `tests/test_masterymigration.py` (15 -> 20 tests).
  One conflict, `PROGRESS.md` only; resolved by keeping both lane logs in order.

### Battery (receipts `/Volumes/Data/ai-tmp/hermes/integ8-20261027/{merge1-only,post-merge}/`)
- Suite: merge-1-only **39 failed / 586 passed / 3 skipped**; merged HEAD **39 / 591 / 3**. FAILED/ERROR line
  set `diff`-identical to INTEG7's baseline at both steps; the +6 passes are exactly batch 4's one test and
  MIGFIX's five.
- Proofs: evility `ex05c..p3b` 12/12, D4 `d4rev1` 94/94, `d4rev2_batch2` 111/111, `d4rev3` 109/109,
  **`d4rev4` 93/93**, mastery `masterystars` 10/13, `packedmapper` 9/9 + 11/11, `packedaward` 9/9 + 11/11 —
  all exit 0 normal and `--abi`.
- Static: evility 55 sites / 92 calls / **0 findings**; packed mastery 0 findings for 2 and 45 families; the
  shipped 47-family set audited separately on the bundle's own family list: 18 sites, 0 findings, screen bound
  byte `0x2F + 47 = 0x5E` (`mastery/static_stack_packed.py` only audits 2- and 45-family sets).
- Payload `b609ada0…` **11,829,248 B**, one `.d5mod`, 144 header bytes left, 14/14 sites, `problem_count 0`
  (byte-identical to LIVE4/INTEG6/INTEG7). Packed payload 18 sites all calling the claim, `.d5cm` absent.
- Ownership **0 errors, 113 bands, 13 members**.
- Validators: `batch4_validate` **984/0**, `validate_review` **582/0**, `batch2_validate` **612/0**,
  `batch3_validate` **830/0**, `batch4_selfcheck` **8/8**, `batch3_selfcheck` **7/7**, `selfcheck_defects`
  **7/7**, all four appliers idempotent (0 changes), `pack_mastery.py` 46 class mods already packed.

### Bundle `Builds/LIVE5-20261027b` (new name: `LIVE5-20261027` stays INTEG6's 19-mod slice)
- **88 mod folders, 2,854 files, 1,449,546,135 B**, **47 mastery families** = 45 D4 generics (A 6, B 10,
  D 12, E 17) + Armor Knight 1350 + DD2 22680; pilots, 35 D1C, `D2_Unique_470`, Stella and the 3 RPG samples
  declare none. Per-mod `files/bytes/tree_sha256/mastery` in `INVENTORY.json` + `.txt`. Nothing dropped from
  LIVE4's 59 mods; 29 D4 class mods added.
- Install shape over the real bundle (Kit's own handlers + `_finalize` on the pinned exe): 88 mods, 47
  families, `mode packed`, `.d5pm`, no `.d5cm`, exe written, 0 errors.
- **INTEG7's open 8062/8067/8085/8228 item is closed:** no non-`D4_*` mod in the installed kit claims those
  ids (measured read-only with the builder's own `charstudio` functions); only the superseded
  `D4_Class_1080` did, and the packs replace it in place. Recorded in `LIVE5/INSTALL.md` §10.
- `LIVE5/INSTALL.md` rewritten for this bundle: LIVE4's safety rules (resolved-path `rsync -a` backup, `cp -R`
  whole folders, **no `--delete`**), the explicit lease acknowledgement (§6.2.0), a **Save1 test-save
  checklist** (§8: several families via `hub.py`, an agent battles to award class XP, one star at a time,
  session-only), and the **agent-run END STATE** (§12: restore, profile `LIVE4_INTEG5`, `install_mods.py`,
  exe sha256 `173685a471f0…274d707`). §13 points Sean at `mastery/OPT-IN.md`.
- NOT proven: native stars/bonus/sub-class screen/pool refusal/save round-trip; no live install; Win unwind.
  Report `INTEG8-REPORT.md`.

## 2026-10-27 — FIXCONTENT lane (offline, branch `fixcontent` @99f6b35)

Worktree `Local/Worktrees/fixcontent`. The game, the installed kit and the Steam folder were never
written. Findings and receipts: `Subprojects/Engine-Extensions/FIXCONTENT-REPORT.md`.

- `d5lib/classcheck.py` (new): one shared rule set for built class/unique packs — R1 personalities
  (>=3 charPersonal rows per family group), R2 every built rank declared, R3 face present, R4 a
  recruit quest must reward the mod's own row, R5 row ownership (no vanilla character row, no row
  another pack adds). Pure file inspection; no game, exe or installer state.
- `d5lib/nativeimports.py`: every generic family now writes the donor's three personality rows and
  declares all six ranks; both importers refuse a pack that fails classcheck (via
  `d4expansion.preflight`).
- Baseline vs change: pytest `39 failed / 587 passed / 7 skipped` on the base archive, FAILED set
  identical here (604 passed with the 14 new tests). The skip difference is where the worktree
  lives (the game-state path resolves to the real checkout).

- Rebuilt with the fixed importer (offline, new outputs under `/Volumes/Data/ai-tmp`): D1C humanoids
  2/2 and monsters 11/11 (each now writes `charPersonal.dat` with 3 rows for its family group and
  declares six ranks), DD2 `D2_Class_22680`, DD2 `D2_Unique_941`, D1C `D1C_Unique_3130`, Stella.
- Validators: `validate_batch.py` humanoids + monsters all gates true (new `identity` gate);
  `validate_dd2.py` (new) pass; `validate_uniques.py --only 3130` all gates true (new `ownership`
  gate). Uniques pack assembles with 21 flagged rows (report §4.1: the low-id space cannot absorb a
  batch-wide re-lease). Ownership checker 0 errors. Smoke 6/6 + D4 replay green.
- Quests at the source: Stella 9503 -> row 224 (was 470 Girl Laharl, template copied from another
  pack), Xenolith 300 -> row 941 (was vanilla row 80 / live 470), Shark King 341 -> row 931 (was
  Pleinair's 45; the lease scan read `rows` instead of `added`).
- Suite: 39 failed (identical set to the base archive) / 605 passed / 2 skipped.
- Report `Subprojects/Engine-Extensions/FIXCONTENT-REPORT.md`, live run sheet
  `Subprojects/Engine-Extensions/FIXCONTENT-LIVE-CHECKLIST.md`. Nothing installed, launched or pushed.

## 2026-10-27 — INTEG9: fixcontent merged, full battery green (offline)

Worktree `Local/Worktrees/integration-next2`, branch `integration/next2` @`e701b8f`. Offline only: nothing
launched, installed, saved or pushed; the installed kit and the Steam folder were not written.

### Merge 1: `fixcontent` @`4d17381` -> `de176db`
- One conflict, `PROGRESS.md` only (both sides appended): resolved by keeping the INTEG8 log and the
  FIXCONTENT lane log in order; no lane text dropped. Code merged clean (`ort`), 12 files / +821/-92:
  `d5lib/classcheck.py` (new, R1-R5), `d5lib/nativeimports.py` (donor personality rows + full rank
  declaration), `d5lib/newclasses.py`, `d5lib/d4expansion.py`, `d5lib/data/ownership_manifest.json`,
  `tools/{build_ownership_manifest,build_prepared_source}.py`, `tools/overlord_port/{convert,finalize}.py`,
  `tests/test_classcheck.py` (new), `tests/test_ownership.py`.

### Battery after merge 1 (receipts `/Volumes/Data/ai-tmp/hermes/integ9-20261027/m1/`)
- Suite: **39 failed / 605 passed / 3 skipped** (INTEG8 baseline 39 / 591 / 3); FAILED-line set
  `diff`-identical; the +14 passes are the classcheck/ownership tests.
- Evility proofs `ex05c ex05d ex05e ex06 p3 p3b` 141/68/88/75/126/111, normal **and** `--abi` — 12/12 exit 0.
- D4 review proofs `d4rev1` 94, `d4rev2_batch2` 111, `d4rev3` 109, `d4rev4` 93, normal and `--abi` — 8/8 exit 0.
- Mastery: `proof_mastery` 10/10 + 13/13 `--abi`; `packedmapper` 9/9 + 11/11; `packedaward` 9/9 + 11/11
  (`--original /Volumes/Data/ai-tmp/claude/pinned/disgaea5.exe`); static stack evility 55 sites / 92 calls /
  0 findings; packed mastery 0 findings (2- and 45-family sets).
- Payload `b609ada0…` **11,829,248 B**, 144 header bytes left, `problem_count 0` (byte-identical to INTEG8).
- Ownership **0 errors, 0 other findings**.

### Merge 2: `uniqreg` @`087b1b2` -> `45f127a`
- Clean (`ort`), **no conflict** (uniqreg is based on `4d17381`, already in this branch): 10 files /
  +558/-98 — `d5lib/classcheck.py` (R6: a char row >= 10000 must be a declared unique identity),
  `d5lib/nativeimports.py` (one-rank identity + physical art lease), `d5lib/newchars.py`,
  `d5lib/outfits.py` (colour-key mapping), `d5lib/ownership.py` (`Band.rule`, `check_unique_lease`),
  `d5lib/slots.py` (`unique_sprite_pool()` 853-999), `d5lib/data/ownership_manifest.json` (identity
  10000-10990, anm 853-999 + 10853-10999), `tools/build_ownership_manifest.py`,
  `tests/test_unique_registry.py` (new, 23 tests), `tests/test_ownership.py`.

### Battery after merge 2 (receipts `/Volumes/Data/ai-tmp/hermes/integ9-20261027/m2/`)
- Suite: **39 failed / 628 passed / 3 skipped** (merge 1: 39 / 605 / 3); FAILED-line set
  `diff`-identical to INTEG8's baseline again; the +23 passes are `tests/test_unique_registry.py`.
- Evility `ex05c..p3b` 12/12 exit 0, D4 `d4rev1..d4rev4` 8/8 exit 0 (normal + `--abi`), same check
  counts as merge 1 (141/68/88/75/126/111 and 94/111/109/93).
- Mastery `proof_mastery` 10/10 + 13/13, `packedmapper` 9/9 + 11/11, `packedaward` 9/9 + 11/11;
  static stack evility 55 sites / 92 calls / 0 findings; packed static 2- and 45-family sets
  (18 sites each) / 0 findings.
- Payload `b609ada0…` **11,829,248 B**, 144 header bytes left, `problem_count 0` — byte-identical to
  merge 1 and to INTEG8 (no hook, section or site changed).
- Ownership **0 errors, 0 other findings** with the regenerated manifest.

## 2026-10-27 — DUPFIX lane (duplicate ids across every installed mod)
Worktree `Local/Worktrees/dupfix`, branch `dupfix`, base `integration/next2` @`5d7f0e1`. Offline only:
nothing installed, nothing launched, the game folder, the installed kit and the saves are read-only inputs.

- `d5lib/modclaims.py`: reads every `<mod>/patches/db/<member>.json` (added rows by id, `rows` by index),
  reports two mods appending one id, two mods patching one row differently, and (with a vanilla table) an
  added id the game already has. `ownership.duplicate_findings`/`check_usage` split the "two holders on one
  resource" rule out of `check_claims` so installed mods can be checked without judging band ownership.
- `tools/check_ownership.py --installed <mods dir> [--vanilla-database <Database_0.dat>]` runs it; exit 1 on
  duplicates. 14 new tests (`tests/test_modclaims.py`); `test_ownership.py` unchanged and green.
- First real scan (144 installed folders, vanilla from the pre-mod game copy): 37 errors — char.dat 233,
  491-495; Skill.dat 24 ids; magic.dat 3; charPersonal 132-134; 1 char.dat row-index patch conflict.

## 2026-10-27 — DUPFIX lane, step 2 and 3 (offline)
- `tools/build_drpg_sample.py` no longer pins rows or outfit slots: `allocate_rows`/`allocate_outfit_slots`
  take ids from `slots.unique_pool` minus every installed mod's claims (d5lib.modclaims), three apart; the
  build gates itself on `ownership.check_usage` (pack + every installed folder, minus the mods it replaces).
- Rebuilt (`--mods-root` = the installed mods, out `/Volumes/Data/ai-tmp/hermes/dupfix/rebuild`): Melodia
  233->257, Citri 234->264, Noel 235->267; outfit slots 490-495 -> 970, 33, 277, 284, 287, 294.
  ok=True, ownership 0 errors, pack duplicates 0, `check_ownership --installed <rebuild>/mods` 0 errors.
  Not installed (live step).
- Installed-set inventory (`--installed` + vanilla from the pre-mod game copy, 144 folders): 37 errors.
  Live: char.dat 491-495; Skill.dat 7000/7002/8062/8067/8085/8228 (D4 pilot vs class packs); magic.dat
  13000 (identical rows); charPersonal 132-134 (x17). Installed-only: char.dat 233, 18 more Skill ids,
  magic 13001/13002. Vanilla's own: charhelp 5222/5224-5226, charPersonal 129-131. Plus a live patch
  conflict on vanilla row 490 (Unique Dummy) between DRPG_Sample_Melodia and Girl_Laharl_Outfits.
- Kit suite 39 failed / 645 passed / 2 skipped, FAILED set identical to base 5d7f0e1 (624 passed / 7 skipped).
- Report `Subprojects/Engine-Extensions/DUPFIX-REPORT.md`.

## 2026-10-27 — DEDUP2 lane (enabled set cleared, morning bundle)
Worktree `Local/Worktrees/dupfix`, branch `dupfix`, base `508ef8c` (DUPFIX). Offline only: nothing
installed, launched, pushed or written to the game folder, the installed kit, a profile or a save.

- `check_ownership.py --profile <load_order.json>` / `--only A,B`: the installed-set scan restricted to
  the 51 mods `LIVE4_SAFE` enables (a profile name with no folder is reported, not skipped).
- Enabled set: **16 errors**, all ours-vs-Sean or ours-vs-ours, none between two of Sean's mods:
  pilot vs class packs 7000/7002/8062/8067/8085/8228 (Skill) and 13000 (magic), 17x charPersonal 132-134,
  DRPG samples vs `DRPG_Outfits_Majorita` (char 491-495) and vs `Girl_Laharl_Outfits` (vanilla row 48).
- `d5lib/rellease.py` + `tools/release_pack_ids.py`: lease a fresh id for every claim a pack collides on
  (manifest bands `evility_id` 7000+, `special_id` 13000+, new `personality_id` 132+), rewrite a COPY of
  the pack (added ids, char.dat evility/learn refs, mod.json), report row-index conflicts as unfixable.
- Fixed: pilot 10 leases (char rows 1350-1355 kept, so Ben's class 1355 is unchanged); the 16 D4 class
  packs 3 personality ids each (48 leases, one file each); DRPG samples rebuilt (char 257/264/267, outfit
  slots 970/33/277/284/287/294) - Melodia no longer patches vanilla row 48.
- `Builds/LIVE4_SAFE2-20261027/`: same 51-mod list, 20 folders swapped, per-mod `tree_sha256` inventory,
  `LEASES.json` (58 leases), `leases/`, `INSTALL.md` (LIVE4 safety rules + rollback). 2.40 GB.
- Verification: bundle enabled set 0 errors / 0 ownership conflicts; row-48 writer = Girl_Laharl_Outfits
  only; suite 39 failed / 656 passed / 2 skipped (same 39 env failures, +11 new tests). Simulated
  post-install set: 23 latent duplicates, all between our own disabled packs.
- Report `Subprojects/Engine-Extensions/DEDUP2-REPORT.md`.

## 2026-10-27 — PTFIX (playtest C1-C7), offline then one live lane

Commit `5c61456`. Bundle `Builds/LIVE5_TEST2-20261027/` (80 folders, 79 enabled), installed live.

- **C1 (crash)**: Skill.dat `desc_<lang>` is the game's printf format (`0x1407D22B0` line 78
  `sprintf_s(buf,0x100,desc,value1,value2)`); vanilla has no ASCII `%` in any description (0/796), ours had
  1,035 bare-`%` fields across 51 folders. New `d5lib/textfmt.py` (escape/validate), a validator rule in
  `d4pilotfix.check_patches`, `tools/fix_evility_formats.py --check/--fix`. Bundle: 0 findings.
- **C2**: live roster read on the pre-install install shows no unit on class 1350-1355 (slot 58 is class
  14085), so the pilot is installed-but-off in `LIVE5_TEST2`; one Armour Knight family at the Recruiter.
- **C3**: `voice_id` gender bug on four male D4 classes (1150/2190/2130/2070 were female vanilla sets) →
  1220/2170/2080/2150. Root cause: D4 voice-pack gaps 9007/9033/9036/9039 + gender-blind fallback.
- **C4**: `D4_Class_2130` has no Skill.dat rows and zero innate/learn fields — content missing, not a filter.
- **C5**: no Thunderlady↔Noel id is shared; the installed set had 52 duplicate ANM/face ids from pre-DEDUP2
  folders, all replaced by the bundle's re-leased copies.
- **C6**: Noel's two leader-skill rows collided with `D4_Class_2020` (7120/7121) → 7067/7071, renamed
  Holy Field / Astral Protect from the RPG mapping, English descriptions; Melodia/Citri ids too.
- **C7**: class titles max 18 chars in vanilla → Citri `Smart Apothecary`.
- Gates: ownership **0 errors** (installed 16), descriptions 0, kit suite 39 known env failures / 661 passed.
- Live: game booted on the new install; the harness could not re-launch afterwards, so the in-game checks
  are listed in `playtest/PTFIX-REPORT.md`. Saves untouched, remote=0, sound restored, PLAY recreated.
## Status (2026-10-27, lane closed)
- [x] read NORTH-STAR, AGENTS, LANE-RULES, PT1027-TRIAGE (S1–S3), Sean's notes; worktree created.
- [x] prior art: vanilla kit readers + docs/D4_BODY_IMPORT.md; Overlord d5_anm_resident.c / d5_anm_trace.c;
      Sorrow RESEARCH-INDEX (anm owner/render notes, nothing on frame rects/anchors); decomp
      FUN_140666920 (wheel selects motion 1001 for slot 0, 1 for the small slots).
- [x] offline renderers: `tools/render_wheel_idle.py`, `tools/render_ptsprite.py`, `tools/sprite_audit.py`,
      `tools/prove_whole_body.py`; before/after sheets + `audit.json` / `stand-ground.json` written.
- [x] S1 cause proven from the installed files (2 body-sized drawings in the stand picture of 19/25 D4
      humanoids; idle 1007 nested also doubled); rebuild from the same prepared art gives 1 body.
      Gate added: `qa_sprite` checks the build's own stand (1/7) and idle (1001/1007 nested) pictures.
- [x] S2 stand-ground fix: `d5lib/standground.normalize_stand_ground`, wired into D4 generic/monster,
      D4 unique and native (D1C/DD2/DRPG) importers. Orc -15 -> 8, Kunoichi 10 -> 7 (donor values).
      28/45 packs were off by >2 px. Idle-loop frame swing diagnosed, not changed.
- [x] S3 no automatic transparency: single switch `imgtools.screen_picture` (opt-in D5MODKIT_D4_MATTE=1),
      all six paste sites routed through it, guard test added; shipped faces measured as matted
      (corner alpha 0, 16-25 % transparent pixels).
- [ ] packs not rebuilt here (no prepared-input/lease reconstruction in this lane): 45 D4 class folders need a
      rebuild to carry the three fixes — list and the offline check commands are in the report.
- [x] tests 39 failed / 642 passed / 2 skipped = base failure set; check_ownership 0.

## 2026-10-28 — PTFIX2 lane (crash narrowed, C4 innate evilities, offline)

Worktree `Local/Worktrees/ptfix2`, branch `ptfix2` = `dupfix` @`ef0b601` (PTFIX) + `ptsprite`
@`f2c64ec` merged (PROGRESS.md only conflict). Offline only: nothing launched, installed, saved or
pushed; game folder, installed kit, profiles and saves read-only; `live-harness/PLAY` present so no
live step; Mac never muted.

- **C1 (Skill Trainer crash, open).** Read the shop's real code path (`1407cde50` list builder,
  `1407cd9c0` eligibility, `14015e630` by-id search + known-evility bitset) and rebuilt the exact list
  from the *installed* table for class 14080-14085: 8062, 8067, 8085, 8228, **8391** (indices
  937/942/948/974/990 of 998); 8392 Aegis is the excluded innate. Eliminated: description formats
  (0 defects in the installed table), `%d` count, id order (installed table sorted, 0 inversions),
  description length. Found: the per-unit known-evility bitset is addressed by row index and refuses
  `>= 1000` (`u32 < 1000` in 0x14015e630 and 0x1407c0a00) — installed table is 998 rows, 8 rows of
  headroom past row 991. New `d5lib/ordercheck.py` + `_finalize_order` (same seam as
  `_finalize_stages`) + `tools/check_table_order.py` + 5 tests.
- **C4 (innate evilities).** Three shapes, wider than reported: 24 packs had no innate with a unique
  row already shipped, 5 pointed at another class's row (1080 -> Dodge Mastery/14590; 1010/1030/1040/
  1090 likewise — a DEDUP2 re-lease side effect), 5 were correct, 20 have no unique row at all
  (Cu Sith 14630 among them). `tools/fix_innate_evility.py` links 20 packs' six ranks to their own
  `kind 1` row (+ alias kept for 1080/1010); verified 150/150 ranks resolve to their own class, 0 wrong.
  The 20 row-less classes need a row built from D4 `mskill.dat` (not done).
- **Sprites not shipped**: 45 D4 class packs not regenerated, so S1/S2/S3 are absent from the bundle;
  `tools/sprite_audit.py` on it: 19 packs `stand_items=2`, ground deltas unchanged
  (`playtest/ptfix2-sprite-audit.txt`).
- Bundle `Builds/LIVE5_TEST3-20261028/` (LIVE5_TEST2's list, 20 folders swapped, INVENTORY, LEASES
  (no new ids), CHANGES, INSTALL.md with the safety + game-silent rules).
- Gates: ownership 0 errors / 0 findings on the bundle's enabled set; suite **39 failed / 679 passed /
  2 skipped** (same known env failures, +5 new tests); `check_table_order` 0 findings.
- Report `Subprojects/Engine-Extensions/playtest/PTFIX2-REPORT.md`.

## 2026-10-28 — REGEN lane (art rebuild of the 45 D4 packs, offline)

Worktree `Local/Worktrees/regen`, branch `regen` = `ptfix2` @`7d872d2` (which already merges `ptsprite`)
— the base the task named. Offline only: `live-harness/PLAY` present, so nothing launched; the game
folder, installed kit, profiles and saves were read only; Mac never muted.

- **Recipe / byte identity.** Rebuilt pack 1010 with the OLD converter (d4-mvp-breadth @c05ec61) and with
  the d4-breadth worktree's; result: all 33 non-art files reproduce, and the art files do **not** match the
  installed folder under either converter state (the shipped ANMs are a per-file mix: `anm01270/01271` come
  from the body-overlays-v1 build, `anm01272` from family-builds). Detail + hashes in the report §2.
  Table side proven: pack-D-early + `fix_evility_formats --fix` + `fix_innate_evility` reproduces every
  LIVE5_TEST3 file of D4_Class_1010 except one line (`evility_alias 8108 -> 1021`, PTFIX2's manual alias).
- **Pipeline** `tools/regen_d4_packs.py`: base folder (LIVE5_TEST3) + the fixed converter's art only
  (`files/Anime/**/*.lzs`, `patches/classes/*.png`), with a hard gate that re-hashes every non-art file and
  aborts on any table difference. 45 packs, 3 workers.
- **C4 rows** (`tools/innate_rows_worksheet.py`): all 20 packs' unique evilities are reviewed `omit`
  (no runtime carrier), and the Skill table is at 998 rows against the 1000-row known-evility bitset cap,
  i.e. 2 rows of headroom for 20 rows needed. Rows are prepared, not shipped: report §4.
- Renders (`tools/render_regen.py`) and bundle (`tools/build_regen_bundle.py`).
- **S2 regression caught by the audit, fixed.** First full rebuild: `stand_items` 19 → 0 (S1 good) and all 21
  monsters landed exactly on the donor's stand ground, but the 25 humanoids moved off it by -5..+10 px,
  onto the donor's *wheel idle* line. Cause: `normalize_stand_ground` measured the raw donor template, whose
  stand picture lives in the shared motion block (`_ground(template, 1) = None` → fallback 6001), while the
  game draws that anim with the block bound (`= 8` for the Warrior donor). Fix: `standground.bound_reference`
  + the three importers pass the bound view; unit test `test_a_motion_block_is_bound_and_keeps_the_template_textures`.
  Re-probe: 1010 0 → 0 (donor stand 8), 2020 -23 → 0. Full 45 rebuilt again after the fix (`regen-all2.log`).
- **Final numbers** (`regen-all2.log`, 45/45, 0 failures): 1016 art files replaced (584 `.lzs` + 432 `.png`),
  1127 table files byte-identical; independent bundle diff: 4119 files, 1016 changed, **0 non-art**.
  `sprite_audit`: `stand_items>1` **19 → 0**; stand ground off the donor by >2 px **17 → 0**.
  Faces: shipped 22.7 % transparent / corner alpha 0 → rebuilt 0 % / white corner. Renders 17 sheets in
  `playtest/regen-renders/`. Gates: ownership 0/0 (79 enabled), `fix_evility_formats --check` clean,
  suite 39 failed / 682 passed / 2 skipped (the known env set + 3 new tests). Bundle
  `Builds/LIVE5_TEST4-20261028/`. Report `playtest/REGEN-REPORT.md`. Nothing installed, launched or pushed.

## INTEG10 — one installable bundle (2026-10-29, offline)
- Branch `integ10` from `c1fix` 8494dd5; merged `sprite2` 4a7ae3a, `evcap-20261029` 7a2c962,
  `voices-20261029` 81c05b1, `d4uniq` 419b657, `oleffects` f9f747f — five merges, **no conflicts**
  (`aec6dcc`). The bundles' mod folders are snapshots, so the bundle is composed from
  `Builds/LIVE5_TEST6` + TEST7 art + TEST4-only folders + VOICES voice files + TEST8 quest names +
  the nine uniques (script `/Volumes/Data/ai-tmp/hermes/integ10-20261029/build_stage.py`).
- Battery on the merged tree: suite 39 failed (FAILED set identical to 8494dd5) / 749 passed / 5
  skipped; ex05c..p3b + oleffects 141/68/88/75/126/111/99 each normal and `--abi`; d4rev1-4
  94/111/109/93 ×2; mastery 10/10 + 13/13, packed mapper/award 9/11 ×2; static 69 sites / 107 calls /
  0 findings; payload 11,829,760 B sha256 `eb92ceb3…647874`, 0 problems; ownership 0/0.
- Tests over the whole 88-entry set: evility formats clean, UI widths 0 warnings, ownership 0 errors
  (after the fixes below), merged Skill.dat 1014 rows / 42 inversions before the installer's sort /
  0 after / **14 rows past the 1000-position known-evility bitset** (the nine uniques cause it).
- Fixed three cross-mod id collisions the D4UNIQ lane's per-mod gates could not see: quest 302 ×9,
  slot 519 ×9, help 22682 ×9; evility alias rows 7061/7062/7067/7071/7072 reused for different
  evilities; magic 13022/13023 ×3. Re-leased in this bundle only (`fix_d4uniq.py`).
- Delivered `Builds/LIVE5_TEST10-20261029/` (59 folders, profile 88 entries, two runtime files,
  INVENTORY/LEASES/INSTALL). Nothing installed, launched, saved or pushed.

# EVCAP3 progress (offline lane, branch evcap3)

- [x] read NORTH-STAR / AGENTS / LANE-RULES / EVCAP design + phase-1 report / OLEFFECTS ownership
- [x] found the game own save commit call (0x14074749E -> write_slot 0x1401194EC, path in rcx) and the
      single load decode call (0x14074D846 -> savefile_decode_slot 0x140743130, slot in edx)
- [x] .d5lc section v2: save/load relays, store sized 131,072 slots (2 MiB), stronger slot hash, lc_put/lc_clear
- [x] d5lib/native/d5learn.inc.c: sidecar publish/rotate/refuse/apply, sha256, JSON emit+parse
      (compiles for x86_64-windows-gnu with zig; host harness runs it)
- [x] tests/test_evcap3.py (27) + tests/test_evcap.py green; suite 779 passed / 39 documented failures
- [x] Unicorn proof of the two relays + lc_put/lc_clear (normal + --abi): 12/12 both modes
- [x] static stack audit (10 routines / 145 sites / 0 findings), payload verify (145/145, unwind 8/8, 0 problems)
- [x] simulated save -> quit -> load -> save round trip on copies of Save1: 18/18
- [x] EVCAP3-REPORT.md, DECISIONS entry, KANBAN line
- [x] merged into integ12 (INTEG12, 2026-10-29): PROGRESS.md taken from integ11 and this section appended

# INTEG13 progress (offline lane, branch integ13)

- [x] read LANE-RULES / INTEG12 / D1CWEDGE3 / SPRITE3 / ANIM reports; worktree from integ12 d825b62
- [x] merged d1cwedge3 (a0cdce5), work/sprite3-20261029 (312cf0e), work/anim-test11-20261029 (a0d50e6) — clean
- [x] donor scan (45 D4 class packs) and built-bank scan (126 folders): a closed list of the packs whose
      donor carries attachment animations -- 4 D4 packs (2190, 2120, 2140, D4_Unique_170) and 9 D1 packs
- [x] SPRITE3 fix applied: three D4 class packs rebuilt with the fixed converter (2 art files each, every
      table file byte-identical); Hugo blanked at the bank level (6 cells, anmdiff: nothing else moved)
- [x] TEST9 hybrid banks carried for Kunoichi / Orc / Winged Warrior / Roc (2 files each, byte-identical)
- [x] the 13 D1C generic classes' charPersonal ids re-leased 132-134 -> 273-308 (tools/release_pack_ids.py)
- [x] profile LIVE5_TEST13 = TEST12's 142 + the 13 (155); gates clean (ownership 0/0, ui 0 warnings,
      formats clean, R1-R8 0 errors over 59 class packs, pack tables 397 = TEST12)
- [x] battery m1 green (suite 39F/821P, same FAILED set; all evility/d4/mastery proofs normal + --abi;
      payload + .d5lc verify 0 problems; static stacks 0 findings)
- [x] Builds/LIVE5_TEST13-20261029 (126 folders, INVENTORY/LEASES/INSTALL); all 126 tree hashes re-verified
- [x] INTEG13-REPORT.md; nothing installed or launched
- [ ] open: nine D1 packs still carry the duplicate-pose defect (five visible on the wheel); Kunoichi's
      hybrid bank keeps one attachment key with a picture; the D1C class builder still writes 132-134

# CARRIERS checkpoint (2026-10-29, offline, in progress)

- Preserved prior work in `bd28997`; merged `integ14` at `d0f904e`. TEST14 is the bundle base;
  OLEFFECTS and EVCAP3 were already ancestors. No CARRIERS bundle or content rows exist yet.
- Prototype `movement_cost` scale 10 reads the D5 battle record +0x61c; its 16 real-call tests
  passed in both normal and --abi modes after the merge. This proves evaluator behavior with synthetic
  records, not equality to D4 movement. No new hook site is claimed. Do not ship it as panel distance yet.
- New D4 source lead: `1401a6310` uses getter `1400eabf0` (battle record +0x4e8) for evilities
  355 (0x163) and 690 (0x2b2), with product capped at 100 in that display path. Setter `1400f1200`
  is called by `1402f5020` with `140304200`'s map value and by `1403050a0` with path cursor minus 1;
  `140304270` also sets a 0/1 value. These are leads, not proof all D4/D5 paths match or of the
  combat cap. Trace the actual combat readers and map construction, undo, AI and exceptional moves.
- `evility/HEALING-RESEARCH.md` identifies candidate sites and unresolved fidelity gates; no healing
  implementation. Filtered counts, attack override, resistance and combo remain unimplemented.
- After the merge: `tests/test_evility.py` 47 passed; full suite 910 passed, 5 skipped, 719 subtests;
  OLEFFECTS --abi 99/99; static audit 69 sites / 108 calls / 0 findings; integration payload SHA-256
  `1ee38a51772afd290bdc21b33f9d82c6356072414babe4daba8152735fd4eeeb`, verify 0 problems.
  These are offline checks, not native acceptance. Continue with proofs, faithful rows and ownership
  before composing TEST14-based bundle; write CARRIERS-REPORT only after the bundle.

# INTEG14 — TEST14 (2026-10-29, offline)

- [x] worktree `integ14` from `integ13`; merged `specials-20261029`, `olcompat2`, `dd2-20261029`
      (the two art-lease manifests unioned to 29 leases, `ownership_manifest.json` regenerated, `--check` clean)
- [x] stage 139 folders = 113 TEST13 (the 13 `D1C_Class_*` excluded) + 22 SPECIALS table deltas
      + 32 ANIMALL banks (pre-image refused unless it matches ANIMALL's manifest) + 11 DD2B + 15 Overlord
- [x] finding 1: SPECIALS' base predates TEST13 — its folders would have reverted Hugo's SPRITE3 fix (6
      bytes) and re-used help ids 22683-22690 (all as 22682) and quest 307/524 (as 302/519); tables only taken
- [x] finding 2: six duplicate ids (Skill 7061/7062/7067/7071, magic 13022/13023) re-leased with
      `tools/release_pack_ids.py`; aliases/skills keys renamed by hand (the tool does not); 0 violations left
- [x] finding 3: `d5lib/modclaims` POSITIONAL_MEMBERS — a same-pack repeat on charPersonal/charhelp/Sugoroku
      is information (Overlord's faithful 3,4,5,3,4,5), a second pack claiming it is still an error; 2 tests
- [x] gates: ownership 0/0 over LIVE5_TEST14 (153) and 0 errors with all 15 Overlord mods (6 INFO);
      duplicate ids 0; dangling refs 0; R1-R8 46 packs 0; Skill 1041 rows 0 inversions / 41 over bitmap;
      pack_tables 397 = TEST13 (the 33 new are all in the disabled Overlord folders); ui/formats clean
- [x] battery m1: suite 39F/883P (FAILED set diff-clean), all evility+evcap3 proofs normal+--abi,
      d4/mastery/packed proofs, static stacks 0 findings, payload byte-identical to TEST13's, .d5lc 41 rows
- [x] Builds/LIVE5_TEST14-20261029 (139 folders, 1,411,453,292 B, INVENTORY/LEASES/INSTALL/LIVE-CHECK);
      independent re-hash 0 problems; profile 153 / gate-only 168
- [ ] open: native anything (10 checks in LIVE-CHECK.md); the D1C generic-class freeze is excluded, not
      fixed; nine D1 packs still carry the duplicate-pose defect; SPECIALS' shared-row rule

## CARRIERS — additional movement trace (2026-10-29, offline)

- D4 `140105580` uses the `+0x4e8` counter for evility 0x163 only when two coordinate pairs agree and `+0x5c6` is positive; `1400ff700`, `140102fa0`, and `14022fad0` subtract its result in their calculation. The generic prototype does not implement these extra conditions, so cannot be substituted for this effect as-is. The identities of the coordinates and full calculation still need tracing.
- D4 `1402f5020` writes `140304200`'s destination map value to the counter; `140304200` reads `DAT_141731950` through `1401e8f40`, while `140236650` fills that map. D5 `1402d5390` writes its own destination cost map `DAT_140b76a30`; `1404cf540` adds its seventh argument to `+0x61c` and restores a prior value when replacing a movement confirmation. `1404d0160` restores the saved counter on successful undo. This is supporting structural evidence, not a proof that the D4 and D5 map costs or all movement paths are equivalent. Trace path-cost increments, exceptional moves and actual caller ABI before declaring fidelity.
- No new carrier or row has been certified. The TEST14 + PT1029 CARRIERS bundle and report remain unbuilt. Do not use the synthetic movement proof as proof of source-game equivalence.

## CARRIERS — TEST15 merge and filtered-count trace (2026-10-30, offline)

- Merged `integ15` at `adb36b9`; retained this lane's PROGRESS.md when resolving the sole merge conflict. TEST15 includes EVCAP4's two save-writer relays. No bundle or content rows exist.
- Focused tests after the merge: `pytest tests/test_evility.py tests/test_evcap.py tests/test_evcap3.py -q`: 106 passed. This is not a new hook proof or native acceptance.
- D4 `1401ba0a0` builds Mass Psyche (0x7f) count `local_214` while iterating other battle records: the record must pass `1400ebe30` and `140108df0 != 2`, its unit must pass `1401b1280 == 0` and `1400eea80 == 0`, `1401b1310(unit+0x1132)` must be nonzero, and its `unit+0x1806` must equal the holder's. It then adds `local_214 * 14010de70(holder,0x7f)` when both positive. `1401b1310` applies ID ranges and a global flag; this is stronger evidence than a generic same-class count, but these field identities and D5 equivalents still need proof. D4 Dark Blood (0x83) uses `local_128[team+0x14]`; this count increments when the referenced character table byte at +0x298 equals 1, under the same outer eligibility checks. Meowyland (0x345) uses `local_218`, incremented when `1400ec730` passes its explicit species/ID predicates. Do not conflate these three filters or assume team semantics from an offset.
- Prior art: Overlord `10_evility_runtime.c` `holder_is_only_ally_on_map` uses the native collector with relationship allies, map range and flags 0; `count_units_in_range` supports general counts but not these D4 filters. Sorrow names and D5 decomp remain navigation/evidence sources as recorded in `evility/HEALING-RESEARCH.md`; no new hook has been claimed. Continue tracing the count inputs and D5 equivalents, then real-CALL/ABI proofs, audit, payload verify, rows and TEST15 bundle. No game, installed kit or save was touched.

- [x] worktree `integ16` from `integ15`, merge `d1cfreeze` (only PROGRESS.md conflicted; union)
- [x] stage 152 folders = TEST15's 139 + the 13 `D1C_Class_*` (copied whole, refused on collision, proven equal)
- [x] gates: R1-R9 over every pack with patches/db (152, only the 5 disabled Overlord packs), 59 class
      descriptors, longest hire_desc 210 B, 0 over 255; 0 lease collisions for the 13; D1CFIX folders
      byte-identical to the ones D1CFREEZE replayed at 0 bytes past the 0x100 field
- [x] source-text fold moved into `d5lib/nativeimports.py` (Latin slots only) + `uniques.json` U+2212 fix;
      `tests/test_source_text_ascii.py` 10 passed, 9 fail against the pre-fix file
- [x] `Builds/LIVE5_TEST16-20261030` (152 folders, 4,859 files, 1.70 GB, profile 166 / gate-only 181,
      INSTALL/LIVE-CHECK/INVENTORY/LEASES/VERIFY), VERIFY 0 problems
- [ ] open: native anything (LIVE-CHECK 5 = the D1C wheel: cursor across the 13, ping each, hire one);
      INTEG15's battery and the 168-folder ownership reconstruction were not re-run here

## DEATH2 (2026-10-30, offline)
- Wheel draw path for 14620 measured from the decomp + the pack: motion 1001 of bank 2330 at 1.0117 scale;
  `sprite+2` (2332) binds at motion 101, falls back to a blank animation id 0; the +0x2cb0 object is another class.
- 1001 = body 192x184 + scythe 192x176 + hands 136x64. The hands item is 100% covered by the body item and
  75-100% byte-identical at every key -> a duplicate part. PT1029's "one figure" was an item count, not a render;
  the live screenshot matches the render (panel A/B), so offline and live never disagreed.
- Converter rule `ownanim.duplicate_items` (called from `build()`), tool `tools/fix_duplicate_parts.py`;
  5 packs change (Death, Hugo, Lady Samurai, Asuka, Vulcanus), 10 banks, art only.
- Kit: `banner_layout` accepts a cell exactly as wide as its page (the 512x72 cell); installer detects a
  pre-PT1029 stale backup prefix and rebuilds it from a pristine copy. 9 new tests; suite failure set unchanged.
- Bundle `Builds/DEATH2-20261030` (verify 0 problems). Report `playtest/DEATH2-REPORT.md`. Not installed.

# WHEELS2 progress (offline lane, branch wheels2-20261030)

Base INTEG16 `b85fabb` (= TEST16). Branch takes the wheels branch's metadata work plus this run's page filter.

- [x] prior art first: Cryswar's `d5_custom_classes.c` (`cc_pre_build` on `0x664DF0`, page key at open,
      `CC_GRID_MIN 6`), Sorrow names, decomp `140664df0` / `1406673b0` / `140666920` / `1406678d0` /
      `1408a02b0 input_raw_key`, PRIOR-ART-MAP, OVERLORD-COMPARISON
- [x] decided the switch point: the page is chosen **when the list is built**, in the builder both menus share;
      no mid-menu actor replacement, which is what the three previous runs could not prove. `DECISIONS.md` entry.
- [x] `d5lib/wheelmeta.py`: `wheel` field / source-game default / cross-mod conflict
- [x] `d5lib/newclasses.py`: shared header (magic, enabled, owner count, captured count, page, page2) + owner
      table + the keyboard buffer; `_wheel_page_src` (Shift / Shift+digit, rebuild from capture, empty-page
      fall-through, six-entry minimum, -1 past the count); `stack_mod16` measures RSP%16 at the hook site and the
      call pad follows it; home space around the two `IS_UNLOCKED` calls
- [x] key read = `call 0x1408d5640` (the game's own GetKeyboardState import thunk, already in the kit's build
      map). The raw key arrays at `0x147b100a8` are not mapped for this build — rejected for that reason
- [x] `tests/test_wheel_page.py` 14: real builder on the pinned exe; the real hook entered at the site with a
      synthetic keyboard; every wheel, the cycle, Shift+digit, empty page, empty list, long page, capture intact
- [x] Codex's 47 kept (48 after one metadata test) + `test_recruit_runtime` 6 = **68 passed**
- [x] static stack audit `wheels/static_stack_wheels.py`: 138 sites, 5 CALL edges, 0 unknown, 0 home stores,
      0 unbalanced returns, **0 new findings** vs the same build without the filter; the 2 remaining are the
      pre-existing `call 0x1402a3d30` (class-tab proficiency stubs) in both builds
- [x] payload `wheels/build_payload_wheels.py` from the TEST16 profile: 58 owners (45 D4, 13 D1C), 0 structural
      problems; pages read back: 2 → 45, 3 → 13, 4 (empty) → falls through to 2
- [x] whole suite: 39 failed (the known environment set) / 959 passed / 5 skipped
- [x] `Builds/WHEELS2-20261030` overlay (2 kit files + tests + wheels scripts + receipts + INSTALL / LIVE-CHECK /
      WHEEL-INVENTORY / INVENTORY / VERIFY), bundle files sha-identical to this tree and compiled with the kit's
      own python
- [x] `docs/CLASSES.md` › "Wheels: one page per game"; `WHEELS-REPORT.md` rewritten; DECISIONS + KANBAN lines
- [ ] open: **live** — `Builds/WHEELS2-20261030/LIVE-CHECK.md` (10 checks; 2–6 the toggle/pages, 7 save/reload).
      Not run: LIVE11 owns the game. Nothing installed or launched by this lane.
- [ ] open: no in-menu cycling (deliberate). DD2/Overlord pages empty until those class packs exist.
## CARRIERS — TEST16 merge and movement comparison (2026-10-30, offline)

- Merged `integ16` into this worktree at `6d4557d`, keeping this lane's append-only progress in the conflict. The TEST16 bundle is the required new base; see `Subprojects/Engine-Extensions/INTEG16-REPORT.md` for its own history. Focused evility, EVCAP, source-text and class-text tests: 130 passed.
- Movement source trace tightened: D4 `1402376d0` calls `140238060`, whose flood starts at 0, writes 1 for the first neighbor and increments the ring value for subsequent neighbors. D5 `path_cost_flood` 0x1402d5ee0 / `path_cost_expand_step` 0x1402d5390 also flood outward, but explicitly sets the written value to 1 at every ring when the unit's `+0x2e2a` byte equals 2. The movement commit reads the destination map value; this is a concrete difference in these code paths, though the byte's identity and all D4 special-movement paths need validation. The generic D5 +0x61c counter cannot yet be certified as D4 panels for all units.
- D4 `1401ba0a0` applies Speedy Move (690, 0x2b2) by adding `FUN_1400eabf0(record) * evility_value` to unit +0x17fe, rather than merely computing a display value. Trick Move's `140105580` has additional state and position conditions and is subtracted in the target calculation. These paths need separately matched D5 semantics; synthetic `movement_cost` tests do not prove either.
- No carrier or content row certified by this trace. No live process, install or save access.

## CARRIERS — carrier delivered: element_resistance (2026-10-30 12:30, offline)

Codex's run stopped mid-verification; its working tree was kept (research notes + the resistance family's
first cut) and finished, not redone. Everything below is offline: nothing launched, installed, saved or pushed.

- **Condition 48 `hp_at_or_below`** — D4's own gate, `hp <= floor(max*a/100)`, inclusive (`FUN_14010de70`
  lines 281-287 return zero only when the scaled maximum is *below* `min(hp,max)`). `hp_below` (kind 4) is the
  integer percent, strictly below, and refuses 250/1000; the two now coexist and the row uses 48.
- **Proof** `evility/offline_proof_resistance.py`: 17/17 normal and 17/17 `--abi` from `0x14021D964`; eight
  D4-gate boundary cases, stacking, aura, unlearned, and the game's own contributions preserved.
  Static `evility/carriers-static-stack.json`: 70 sites / 110 calls / 0 findings. Regression (both modes):
  ex05c 141, ex05d 68, ex05e 88, ex06 75, p3 126, p3b 111, oleffects 99, d4rev1 94, d4rev2 111, d4rev3 109,
  d4rev4 93. Suite 39 known env failures / 913 passed / 5 skipped (+3 tests).
- Payload `build_payload-158` + `verify_payload-158` with `D5_KIT` = this worktree: `problem_count 0`, section
  264,112 B, 144 header bytes left, payload sha `18b0377d…`, 11,829,760 B.
- **Content**: `evility/carriers-content.json` (one source) + `tools/carriers_rows.py` (the only writer,
  `--check` default, refuses a row id another pack already claims). Row 8230 Anti Elements on D4_Class_2190;
  free in all 152 folders; `check_ownership --installed --profile` 0 errors / 0 findings; formats clean.
- **Bundle** `Builds/CARRIERS-20261030`: copy of TEST16, 152 folders re-hashed (1,698,141,987 B), only
  `D4_Class_2190` + `kit-install/d5lib/evility.py` + the new `kit-install/d5lib/native/d5evil.inc.asm` differ;
  `INSTALL.md` (deltas + restore; TEST16's runbook kept as `INSTALL-TEST16.md`), `LIVE-CHECK.md`,
  `tools/carriers_bundle.py` for the receipts. Skill.dat 1041 -> 1042 rows, over-bitmap 41 -> 42, row 8230 at
  index 1011 (every row whose index moves is already over the cap, so no saved bit changes meaning).
- **Not shipped**: Miasma 114 (per-provider count + footprint + recipient gate), Magic Wand 695 (D4 record
  `+0x298` identity, defender-override precedence), movement (five `+0x61C` readers unproven; D4 flood
  increments per neighbour, D5 writes 1 per ring when `+0x2E2A`==2), filtered counts (Evil-Area list
  intersection has no D5 representation established), healing (six distinct operations), combo (ordered
  next-actor state). Report `Subprojects/Engine-Extensions/CARRIERS-REPORT.md`, one KANBAN line appended.
- Deviation, stated: the row is written into the bundle copy, not into `d4-review`'s verdict ledger or the
  source pack, because those are shared trees this lane does not own. `batch2_apply.py --write` on a source
  rebuild would drop it until the verdict is folded in (report §7 item 5).
# D4UNIQ3 — the ten D4 uniques still blocked on art space (2026-10-30, offline)

Continued from Codex's worktree (its two commits kept) after its usage limit. Worktree
`Local/Worktrees/d4uniq3` from `integ16`; nothing launched, installed, saved or pushed. Bundle
`Builds/D4UNIQ3-20261030/`; report `Subprojects/Engine-Extensions/D4UNIQ3-REPORT.md`; evidence
`Research/source-packs/d4uniq3/` (private).

- [x] kept Codex's carve: ten single-window leases from the third run (461 464 467 503 506 513 606 613
      616 623), each proven free in the installed **and** pristine archive, no char row at n..n+2, ≥3
      from every other lease (`prove_art_leases.py` → 10/10, `ART-LEASES-PROOF.json`)
- [x] **identity band moved 22700→18100-18190**: 22700-22705 is DD2GEN-20261030's, and any identity
      above 22769 pushes `10000+identity` portraits into Overlord's reserved 30507-32769. Carved as
      narrow in_use bands in `char_dat_row` and `job_class_id` (generator + manifest, regenerated,
      +32 lines and nothing else)
- [x] ten packs built by `tools/build_d4_unique.py` (registry identity, D4 stats/art, own face and
      list icon, quest 386-395 / slots 608-617 / charhelp 22855-22864)
- [x] own D4 animation tracks: `animall2_convert.convert_new`, 3-252 D4 motions per character, 2,878
      pixel checks, 0 mismatches; Politan keeps donor tracks (D4 authors 3 motions — recorded)
- [x] specials the SPECIALS way: 21 D5-donor copies under D4 names, 2 held Magichange moves, Des X's
      two renumbered off the builder's colliding 13027/13028 to 28141/28142
- [x] evilities: 8874 Kazamatsuri Sisters (new, innate, `stats` + `near_char`) and 8884 Overlord
      Spirit (already an exact row the builder links); Politan's Bow Range UP held (weapon-category id
      unmeasured)
- [x] gates: 10/10 pass all six (anm, figure, database, leases, classcheck R1-R9, ownership), UI
      widths clean, ownership 0 findings on the ten + 0 collisions with the base, suite
      **diff-clean** (39 failed / 912 passed / 2 skipped, identical FAILED set to `integ16`)
- [ ] open: native acceptance — LIVE-CHECK's recruit-three-by-quest, face, body, special (the same open
      question every unique batch carries)

## INTEG17 (2026-10-30, offline) — TEST17 = TEST16 + DEATH2 + WHEELS3 + CARRIERS + D4UNIQ3 + DD2GEN + VOICES2 + OLFIX kit
- Branch `integ17` from `integ16` `b85fabb`; merges `work/death2-20261030`, `wheels3-20261030`, `carriers`,
  `d4uniq3`, `voices2` (from integ15), `olfix`. dd2gen has no code commit (content-only lane) — its bundle is the delta.
  Conflicts: PROGRESS.md only (append-only log, union).
- Stage (file deltas, refuse-if-undeclared): TEST16 152 folders -> DEATH2 replaces 5 (10 files) -> CARRIERS
  replaces D4_Class_2190 (3 files) -> D4UNIQ3 adds 10 -> DD2GEN adds 9 -> DD2WHEEL folds `"wheel": "DD2"` to the
  kit's lowercase vocabulary in 18 metadata files (the validator fails closed by design) -> OLFIX adds `expect` to
  11 row-editing Overlord patches (rows identical) -> VOICES2 overlay: `patches/voices/` replaced wholesale +
  `patches/db/char.dat.json` voice_id on 21 uniques; the 6 folders DEATH2/CARRIERS also touch keep their art.
  171 folders, 6,475 files, 1,926,219,793 B.
- Kit: 26 files overlaid on TEST16's kit trees; TEST16's duplicate `runtime/d5lib/modsys.py` dropped (one file,
  one place; `kit-install/` keeps DEATH2's superset). OLFIX's `dbpatch.py` goes to `kit-install/d5lib/` (where
  TEST16 shipped it), not `runtime/` as in the OLFIX b bundle, so the installed path has one source.
- Gates: class gate R1-R9 over 171 packs = 5 errors (the 5 disabled Overlord packs, unchanged); 68 class
  descriptors, longest 210 B, 0 over 255; re-lease no collision; D4UNIQ3 band free; DD2 band free; Overlord
  reserved 30507-32769 empty; pytest 39 failed / 1,007 passed / 4 skipped, FAILED set identical to integ16;
  row-identity 8/8 over the 200-entry gate profile (OLFIX_PROFILE env added to the test); payload 67 owners
  (45 D4 / 13 D1C / 9 DD2), pages 45/13/9 with empty pages falling through; clean-install dry run on a COPY of
  the installed kit + game -> "Install complete." with nothing cleared; D1CFREEZE replay over the dry-run build
  (135 texts) = 0 bytes past the 0x100 field, 273 B control 18 past; 5 DEATH2 members in the built archive have
  0 duplicates left; 491 voice_id patches landed (the 5 misses are the disabled Overlord mods).
- Bundle `Builds/LIVE5_TEST17-20261030` (171 folders, profile LIVE5_TEST17 185 / gate-only 200, VERIFY 0 problems,
  INSTALL.md + LIVE-CHECK.md). Report `INTEG17-REPORT.md`. Nothing launched, installed, saved or pushed; the live
  game, installed kit, profiles and saves were read only.

## CARRIERS2 (2026-10-30, offline)

- Ranked every missing signature evility by distinct imported characters per engine addition
  (`tools/carriers2_ranking.py` -> `evility/carriers2-ranking.json`): **filtered unit counts 9**, a
  Magichange/Confine/summon mode 6 (evidenced blocker: the mode does not exist), then damage redirection /
  evasion auras / Evil Area / the healing pass at 3 each, the rest at 1-2.
- Built #1: scales 11 map_monster, 12 map_human, 13 map_class, 14 map_has and condition 49 map_has_min, all on
  `evil_near`'s existing walk; row dword 7 carries the filter and `classes: [...]` expands to one row per class
  id. No new wrapper, no new call site.
- Rows shipped: 8187 Dark Blood (Beast Master), 8837 Meowyland (Pink, 13 measured cat classes), 8841 Prism
  Emblem (Prism Ranger). Held with reasons: 837 on Death Saber and 127 on Petite Orc (self-count unproven),
  841 on Prism Red (one Skill id, one owner), 816/875/840/658.
- Proof 17/17 normal and 17/17 --abi from the patched CALL; static audit 70 sites / 114 calls / 0 findings;
  payload verify 0 problems (sha e0a273ee...); 12 regression suites both modes; kit suite 39F/916P/4S,
  diff-clean against the `carriers` base (39F/914P/4S); ownership 0 errors / 0 findings; bundle table 132/512.
- Bundle `Builds/CARRIERS2-20261030` (152 folders, 4,859 files, 1,698,145,218 B; Skill.dat 1045 rows, 45 over
  the bitmap, no inversion) BEFORE the report; report `CARRIERS2-REPORT.md`; one KANBAN line.
- Deviation, stated: rows are written into the bundle copies, not into `d4-review`'s verdict ledgers or the
  source packs (shared trees this lane does not own); a source-pack rebuild would drop them until folded in.
## DD2NAMED — 2026-10-30 (offline, DONE)

Bundle `Builds/DD2NAMED-20261030` (overlay on `LIVE5_TEST17-20261030`). Nothing installed, launched,
saved or pushed.

- Delivered `DD2_Unique_10` Laharl (10530, art 626, quest 356), `DD2_Unique_50` Flonne (10540, art 633,
  quest 357), `DD2_Unique_60` Pure Flonne (10550, art 636, quest 358). Six validate gates each: 3/3.
- Converter fix: `sourceimports.map_source_palettes` now measures ambiguity per *used* colour and per
  *bank*; `exact_banks=True` ships only the exact banks and fills the rest from bank 0
  (`nativeimports.build_entry(exact_palette_banks=...)`). Two tests added in `tests/test_d4source.py`.
- Leases recorded in `d5lib/data/unique_art_leases.json`, carved by `tools/build_ownership_manifest.py`.
- Gates: class gate 174 packs / 5 known Overlord errors / 0 R9 / 68 descriptors max 210 B; ownership
  identical to TEST17 alone (0 DD2 findings); UI 0 warnings; pack tables 0 findings; pytest 39F/1011P/2S
  with the same FAILED set as integ17; bundle re-hash 3 mods / 33 files / 18,379,300 B / 0 problems.
- Blocked with evidence (`evidence/prepared-gate.json`): Sicily 70 stand-only body (3 tags, 26/26
  rectangles consumed, 0 % alpha at the shared walk cell); Xenolith 90 has all eight monster actions and
  stops at 59/122 donor-attachment palette colours (DD2B's "missing actions" reason corrected);
  Zetta/Pram/Alex/Lanzarote/Salvatore have no face resource in any of the six DD2 face atlases;
  Desco/Raspberyl/Metallia/Priere/Baal Slave/Darkdeath are stand+wait bodies.
- Next: LIVE-CHECK quests 356/357/358 + 383 + 385; Xenolith's 59 colours; Laharl/Flonne
  skills from `evidence/abilities-queue.json`.

## INTEG18 (2026-10-30, offline)

- TEST18 = TEST17 + CARRIERS2 + MAGICHANGE + DD2NAMED. Branch `integ18` from `e4f22a1`; merged
  `carriers2`, `magichange`, `dd2named` (only the append-only `PROGRESS.md` conflicted; union).
- Bundle `Builds/LIVE5_TEST18-20261030`: **174 folders, 6,508 files, 1,944,635,180 B**; profiles
  `LIVE5_TEST18` 188 / `LIVE5_TEST18_OVERLORD` 203. Stage = declared file deltas only, **0 undeclared
  changes**; CARRIERS2 applied file-wise because its base predates TEST17 (its bundle still carries the
  pre-VOICES2 voice layout and `voice_id 2020` on Pink); `D4_Unique_300/mod.json` merged explicitly.
- Gates: 174 packs R1-R9, 5 errors = the 5 disabled Overlord packs, 0 R9, 68 descriptors max 210 B;
  re-lease 0 collisions and every band free; OLFIX 8/8 on the 203-entry profile; wheel payload
  structural 0 / 67 owners 45-13-9 and 52 hire-replay tests; **clean install dry run `Install complete.`**
  (exe `8f3e80af…` 14,314,496 B, wheel table in the built exe 45/13/9, ANM_HI_JP 4,336/0 damaged,
  `Skill.dat` 1,050 rows / 50 over the bitmap, classes 67); D1CFREEZE replay 135 texts / 0 bytes past;
  installed state carries 8187/8837/8841, 16 Magichange rows and 7 learnsets, Laharl/Flonne/Pure Flonne;
  suite 39F/1,031P/2S, FAILED set identical to `integ17`.
- Report `Subprojects/Engine-Extensions/INTEG18-REPORT.md`. Nothing installed, launched, saved or pushed.

## 2026-10-30 INTEG18B — TEST18B = TEST18 without the paged wheel (offline)
- `d5lib/newclasses.py` back to `integ16`'s one-list carousel (only WHEELS2/3 touched it in between); kept
  `wheelmeta.family_wheels` validation in `_handler` so a mistyped `wheel` still fails the build.
- Deleted `d5lib/wheelhook.py`, `d5lib/native/d5wheel_partition.h` and the five page test modules; trimmed
  `tests/test_wheelmeta.py` to the metadata tests; added `tests/test_wheel_single.py` (6 tests, the guard).
- Suite 39F / 1,002P / 2S, FAILED set identical by name to `integ18`.
- Bundle `Builds/LIVE5_TEST18B-20261030`: 174 folders byte-identical to TEST18, profiles 188 / 203,
  INSTALL.md + LIVE-CHECK.md. Payload `a06e79bd…` 11,391,488 B, structural 0.
- Dry run on copies: `Install complete.`, exe `816cbfdf…` 14,303,744 B, `.d5mod` 3,000,320 B, the built exe
  lists **67 mod families once each** (ranks 6, 0 duplicates) after the 47 vanilla slots, cap 512,
  no `D5WHEEL1` / no keyboard read; ANM_HI_JP 4,336/0, ANM_HI_EN 97/0; Skill.dat 1,050 rows.
- R1-R9 174 packs / 5 by-design Overlord R8 / 0 R9; re-lease 0 collisions; OLFIX 8/8; ownership 0 findings;
  D1CFREEZE replay 135 texts / 0 bytes past.
- Report `Subprojects/Engine-Extensions/INTEG18B-REPORT.md`. Nothing installed, launched, saved or pushed.

## 2026-11-03 CORED1CC — the four unbuilt D1C roster entries build (offline)
- 4/4 build. `unique:2540` green (12/12 gates, compare `expected`): `_donor_context` now measures donor
  heights on `Originals(STATE)`, the pristine archive `build_entry` copies banks from, so
  `D4_Class_2050`'s `anm02260.lzs` (a number vanilla D5 lacks) can no longer win the probe; only
  2500/2540/6601 donors changed across the whole medium set (2260 -> 2120).
- `unique:2500`, `5390`, `6601`: leases completed/added in `unique-leases.json` (help 22886-88, quest
  402/403/415, slot 542/544/545; identities 10810/10830; art 646/653) with an `allocations` evidence key.
- `d5lib.d1cart.poses(shared_fallback=True)` fills a stand/walk-only event body's wait/damage/attack
  rows from the source's own shared motion bank (bank 1), rendered with the body's cells/palettes and
  recorded in `receipt['shared_rows']`; off by default (refusal and 19 d1cart cases unchanged).
- Open: compare `new` for the three (no installed copy), hurt gates false until installed (gate needs
  the installed reference; `ownanim.py:956` also fails on the only donors carrying 21/27), and
  `face`/`authored_cutin` false for 5390/6601 (no authored cut-in for bodies 5390/2560; `d1c.py:428`
  also clobbers the adapted-face branch at 400-408 — `_gates` not in this lane's ownership).
- Report `/Volumes/Data/ai-tmp/hermes/cored1cc-entries/REPORT.md`, results in `final/d1c/results.json`.
  Suite `tests/test_importcore.py tests/test_d1cart.py` 25 pass. Nothing installed, launched or pushed.

# D4SIG3 (2026-11-12, branch d4sig3 from integ-next eb623d7, offline)
- Piece 1 DONE: Marona 875 stat set traced (D4 FUN_1401ba0a0 -> FUN_1401b4010 scales ATK/DEF/INT/RES/HIT/SPD, not HP/SP); pack and Ash 878 (same percent) fixed to six stats; Marona label exact. evilcap1 proof 496/496 normal+abi; control (old 'all' row) fails.
- Piece 2 DONE: Chief 304, new family support_magic_percent (bit 29), wrapper wrap_support (tag 0xE7001B) at both callers of FUN_1401FEFA0 (inner 0x1401FF046 has no live caster). evility/offline_proof_d4sig3.py 34/34 normal+abi, 3 controls fail. Static stack 73 sites/147 calls/0 findings. Payload verify 0 problems.
- Piece 3 STOPPED: D4 timing established (after the action script ends), no D5 end-of-action site designed/proved; see D4SIG3-REPORT.md.
- Piece 4 written, not run: live-harness/runner/speedymove.py (+ --selftest).
- Staged: Builds/D4SIG3-20261112/mods (Marona, Ash, Chief), stage_d4sig1.py reused.
