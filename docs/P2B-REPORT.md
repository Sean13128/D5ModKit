# P2b — packed mastery (offline, incomplete)

## Plain-English summary

**Not ready to install.** The runtime still uses six physical mastery leases. The packed codec is not connected to the mapper, staging, award or unlock paths, so the requested 1/7/45-family runtime behavior has not been demonstrated. The combined D4 stage and LIVE4 checklist are a gated plan, not permission or evidence of a successful install. No game, installed kit, Steam folder or real save was accessed; nothing was pushed.

The 120-byte pool is a per-unit limit, not a limit on configured families. In the best case it holds 38 completed three-byte entries plus the separate staged family; partial counters require more space. Consequently 45 completed families on a single unit cannot all fit. The requested overflow behavior must refuse safely, not evict, truncate or corrupt progress.

## Work completed

The resumed commits `2ec6209` and `1d5685a` implement explicit copied-save migration with supplied leases, rows, thresholds and ownership claims, output and exclusive backup, serialization readback and refusal of ambiguous or lossy data. `59729d4` additionally rejects data that resembles an already packed pool. Fixture tests cover the 1350 move, flags, class, row, subclass, backup and refusal cases; no actual save was used. Native loading remains unverified. Commits `1d6d45a` and `48a8ba7` are a replacement and its immediate revert; they have no net effect.

`4548ed1` specifies a transactional stage switch in the Python codec and tests saturation and swapping. It is an offline specification, not native runtime wiring. `dd9e4ad` adds `docs/P2B-STAGE-LIVE4.md`, also copied to the workspace mastery folder. The plan combines the 16 breadth families and pilots, includes migration and ownership gates, per-class hub checks, vanilla control and rollback, and notes that remote mode does not save.

## Why runtime remains blocked

Overlord's store removes an existing entry before checking space and can evict partial progress or truncate counters. A direct port would violate the no-corruption requirement. The real writer `0x14015f480` changes counters, permanent bonus words, unlock state and subclass before returning. Checking only on a later stage switch is too late. A safe implementation needs capacity reservation before these side effects, a site-aware 16-caller mapper with correct unit extraction, atomic encoding and reentrancy handling, and integration of the custom tier path with the Kit's existing per-rank flag setter. It must preserve the existing writer-site `r10` one-star fix and vanilla paths. None of those hooks has been implemented or proven here.

Next: implement those paths and explicitly gate legacy-to-packed conversion; then prove real builder and writer at 1, 7 and 45 configured families, all six ranks, overflow and record reload, both normal and ABI. Audit fixed frames, all call sites and unwind records, build and verify the complete payload, and run a complete suite. Large native awards may carry overflow across completed stars as documented in `mastery/STARS-FIX.md`; that established behavior must be tested as well as small one-star awards. Native menu navigation, migrated-copy loading, and removal safety remain separate live gates.

## Verification

- After the last migration change, `tests/test_masterymigration.py` and `tests/test_packedmastery.py`: **15 passed** in the specified Unicorn environment. These are fixture/codec tests, not runtime proof.
- Per-file Kit suite on the resumed branch: **433 passed, 1 skipped** in files that completed. `test_recruit_ranks.py` and `test_recruit_runtime.py` terminated with SIGILL inside Unicorn `mem_map`; serial execution did not cure it. The same Recruiter-ranks test on the older `engine-158` worktree also SIGILLed at the same call, evidence of an environment issue rather than a demonstrated P2b regression. `test_typography.py` aborted with the default Qt platform and passed **6/6** on rerun with `QT_QPA_PLATFORM=offscreen`. This is not a complete suite or a comparison proving no new failures. Log: `/Volumes/Data/ai-tmp/codex/p2b-20261027/serial-suite.log`. The serial suite preceded the last guard change; the focused tests above were rerun afterward.
- No packed real-builder or real-award proofs, normal/ABI proof, static stack/unwind audit, or payload build/verification were completed. Existing prior reports on the six-lease runtime do not prove this unfinished packed implementation.

## Prior art checked

- **Overlord:** `class-support/OVERLORD-COMPARISON.md` and Cryswar's `overlord-source/d5_custom_classes.c` (mapper `0x21EBE0`, 16 caller contexts, staging slot 52, 120-byte pool, tier hook `0x1C62A0`). Cryswar's Unlicense design is the blueprint and is credited; the codec differs deliberately by refusing lossy storage. No Overlord save-migration implementation was found.
- **Sorrow:** `community/sorrow/RESEARCH-INDEX.md` and `ida-export-20261014/disgaea5_names.json`: the latter names `0x1C62A0` `mark_character_seen`, so its semantics cannot be inferred from the Overlord label alone.
- **Decomp:** `/Volumes/Data/Decomp/d5/functions/14021ebe0_FUN_14021ebe0.c`, `1401c62a0_data_progress_mark_character_seen.c`, and `14015f480_FUN_14015f480.c` establish the vanilla mapper, progression routine and writer side effects. D4 supplies no relevant D5 packed mastery implementation.
