# EX-05c — capacity and missing vocabulary

2026-10-26. Branch `feature/evility-capacity`, based on live-proven `c5e4864`.
Source changes and offline construction checks only. No installation, game mutation,
launch, merge or publication. Unicorn was not run; emulator acceptance is pending.
This report, proofs and tracking stay inside the permitted worktree; the shared board
and external proof sources were read without retained changes.

## Commits

| Commit | Deliverable |
|---|---|
| `27c93df` | Local tracking, shared static-audit runner, ABI documentation correction |
| `c563656` | Larger table and indexed learned-id lookup |
| `4e81443` | Aura correction, base-stat conversion, type predicates, status index zero |
| `d1cc8c9` | Merge aura and learned rows in global ID order, preserving clamp ordering |
| `781a18a` | Writer capacity and vocabulary boundary tests |
| `9ac3035` | Behavioral/site-entry proof fixtures and legacy ABI adapter |

The final documentation commit contains this report and checked audit/build receipts.
Emitter changes are outside Git, restricted to the six files in
`Subprojects/Engine-Extensions/d4-evility-map/emit/`; they cannot be committed on this branch.

## Limits and cost

**512 rows / 4,096 effects / 2,048 conditions**, shared across mods. The 325 classified
owned D4 entries leave 187 row slots for decomposition and other mods. Effect/condition
budgets allow eight stat effects and four conditions per budgeted row. Unsupported
mechanics still lack exact recipes: these budgets are headroom, not a demonstrated
complete faithful import capacity.

Format 2 and existing 32-byte rows / 8-byte conditions / 8-byte effects remain intact.
Auxiliary counts and an aura offset index follow the sentinel. New family bit 512
isolates conversion effects: low byte of the stat word is destination, next byte is
base source. Existing JSON rows remain valid.

Hot damage/growth/predicate passes iterate at most 64 learned IDs and binary-search
the table: at most ten table probes per ID at 512 rows (640 worst-case probes), rather
than scanning all rows. Ownership checks are also bounded binary searches. Empty
condition lists return immediately; only spatial predicates look up a battle record.
Stat passes merge the learned stream and aura index in ID order; an intervening aura
can repeat the pending learned lookup, but both cursors advance monotonically.
Adjacent duplicate learned IDs contribute once. Auras retain their existing bounded
256-unit provider scan. This is a static complexity bound, not native timing evidence.

## Vocabulary and evidence

The starting ranking was aura correctness 9 single-gap candidates, stat conversion 9,
then attacker typing 4. Implemented:

- Auras require a `near_has` provider condition, honor only their explicit stat family,
  and reach recipients with zero learned evilities. Provider counts remain Boolean;
  Manhattan cell distance retains the documented footprint/path limitation.
- `conversion` effects use `{"stat":"hit","from":"spd","value":30}`. They read
  immutable base stats at roster+0x2D18 and add signed percentages to maxima+0x2CD8
  after original `unit_stats_evil_overrides`, before final native clamps. The only
  redirected recalc CALL is 0x14021E79F → original 0x1401EEE30. Sources do not feed back
  through other conversions. Division truncates toward zero; native base limits keep
  the signed64 product in range. Current SP, monster-weapon grouping and ambiguous
  multi-source conversions remain uncovered.
- `other_human/monster/male/female` and corresponding `self_*` predicates use the
  normalized roster type byte+0x2E25. They mirror native getter 0x14015D440, including
  learned evility 4301's gender swap. Unknown codes fail closed. On `taken`, `other_*`
  inspects the attacker; on an aura, `self_*` inspects the recipient.
- `target_status`, `self_status`, `status_class` now permit index 0 (Poison).

Field/stage evidence: pinned executable bytes and the existing local decompilation
of unit recalc, overrides, roster initialization and the type getter. No reference
implementation was copied; original game instructions/data are not committed.

All 14 redirected sites are E8 CALLs. New wrapper/helper frames are fixed, preserve
their nonvolatiles and reserve aligned outgoing home space. Existing `exepatch`
emits/validates `.d5el` unwind records without modification.

## Emitter result

**60 exact / 265 uncovered / 325 classified; 62 effects / 53 conditions**, versus
35 exact initially. Added 9 named-stat auras, 9 base conversions, 4 attacker-type
recipes, 1 target-type recipe and 2 Poison recipes. D4 #5 stays uncovered because
`other_male` alone does not establish a hostile target. Semantic signatures and
native/doc source hashes remain pinned. Capacity flag FITS; unused budgets are
452 rows / 4,034 effects / 1,995 conditions when alone.

Generated JSON SHA-256: `2f6fc56c063b7e281ccf3c1eba8162ec1dfd7ddc593ffad7ecdb0773bde89bba`.
Vocabulary SHA-256: `3835b857aacee0ac3cd924b51cbf6337e29d1a7ec6e339b3d162594d55a866e7`.
“Exact” means reviewed text/schema expression; native D4 equivalence is not established.

## Checks completed

| Check | Result |
|---|---|
| Full Kit suite | **295 passed, 1 skipped, 706 subtests passed** |
| Evility writer tests (part of suite) | **24 passed** |
| Emitter suite | **32 passed** |
| Emitter `--require-capacity` | Passed; regenerated all exact rows |
| Shared static-stack audit, actual assembled/PE-patched worktree | **14 E8 sites, 44 call edges, 0 findings** |
| EX-05c proof `--build-only` | **141 fixtures built**, 7 plans, all 14 sites; no Unicorn execution |
| Compilation/whitespace | Passed |

Receipts: `engine-ext-capacity-static-stack.json`, `ex05c-build-only.json`.
The static runner compiles the shared `abi-review/proofs/static_stack.py` unchanged,
using this directory only as its receipt output anchor.

Fixtures cover table512 first/middle/last/missing IDs, 64 learned IDs, duplicates,
explicit aura stages/empty recipients/provider eligibility/clamp order, immutable
base conversion and original-first ordering, signed rounding, every new type predicate
with gender swapping, Poison zero, and all wrapper entry sites. ABI mode enters real
patched CALL instructions, checks exact continuations/RSP, poisons home space, checks
forwarded stack arguments and nonvolatile integer/XMM/control state. Original callees
in this new suite are explicit volatile-clobbering stubs; existing behavioral proofs
retain their pinned-original execution.

## Reproduction and coordinator emulator commands

From `/Volumes/Data/Projects/D5`:

```sh
PY=/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python
KIT=/Volumes/Data/Projects/D5/Local/Worktrees/engine-ext-capacity
export D5_KIT="$KIT"
OUT="$KIT/evility/results"
mkdir -p "$OUT"

# Completed here; no Unicorn.
(cd "$KIT" && "$PY" -m pytest tests -q)
"$PY" "$KIT/evility/static_stack_ex05c.py"
"$PY" "$KIT/evility/offline_proof_ex05c.py" --build-only --json "$OUT/build-only.json"
PYTHONDONTWRITEBYTECODE=1 "$PY" Subprojects/Engine-Extensions/d4-evility-map/emit/emit_d4_evilities.py --kit "$KIT" --require-capacity
PYTHONDONTWRITEBYTECODE=1 "$PY" -m unittest discover -s Subprojects/Engine-Extensions/d4-evility-map/emit -q

# Coordinator only: emulator-capable host. These have NOT run here.
"$PY" "$KIT/evility/offline_proof_ex05c.py" --json "$OUT/ex05c-behavior.json"
"$PY" "$KIT/evility/offline_proof_ex05c.py" --abi --json "$OUT/ex05c-abi.json"
for suite in base ex05 ex05b; do
  "$PY" "$KIT/evility/offline_proof_ex05c.py" --legacy "$suite" --json "$OUT/$suite-behavior.json"
  "$PY" "$KIT/evility/offline_proof_ex05c.py" --legacy "$suite" --abi --json "$OUT/$suite-abi.json"
done
```

The legacy adapter executes the unchanged external scripts. Their shared ABI helper
hardcodes nine wrapper names, so ABI mode receives a proxy listing those original
nine wrappers while its bound builder still builds the complete ten-wrapper patch.
The new suite separately covers all fourteen sites including conversion. Direct old
`--abi` commands against the ten-wrapper module would otherwise raise `IndexError`.
Legacy behavior commands also work directly with `D5_KIT` set. All emulator results,
Windows runtime unwinding and EX-05c native gameplay remain pending; do not install
as part of this handoff.
