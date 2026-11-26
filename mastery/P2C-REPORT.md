# P2c — packed mastery wiring (offline, incomplete)

## Status

**Not ready to install.** The game still uses the existing six leased mastery slots; packed mastery is not wired into the executable. No game, installed kit, real save, or Steam game folder was accessed; nothing was pushed. The two new commits are offline specifications, not native hooks:

- `d3455e1` models mapper pass-through, per-unit staging and refusal without changing the input on full or invalid storage. A reason is returned to the model caller. It does not authenticate native caller sites or log in the runtime.
- `1272083` models STARS-FIX award projection and checks that the resulting staged counters can be packed without eviction or truncation before accepting. It covers completion carry and stale partial counters, but takes a normalized nonnegative award and does not execute native side effects.

The combined mapper, award, pool and migration fixture tests passed **23/23** using `/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python -m pytest tests/test_masteryaward.py tests/test_packedmapper.py tests/test_packedmastery.py tests/test_masterymigration.py -q`. These results establish only the Python models and fixtures.

## Requested steps

1. **Mapper hook: not implemented or proven.** The model does not extract a unit at the 16 actual callers, emit machine code, integrate with the builder, or demonstrate unchanged vanilla behavior in the game path.
2. **Writer and unlock path: not implemented or proven.** The real writer modifies eight bonus words, unlocks and subclass as well as counters. A safe runtime must reserve capacity for the projected result before those effects, handle native clamping, nested callbacks and reentrancy, preserve the existing writer-site `r10` adjustment, and integrate custom rank flags. An ordinary stage switch alone cannot guarantee this. Pool-full visibility is only a model return reason, not runtime tooling or logging.
3. **Real builder/writer 1, 7 and 45 families, across units, normal and ABI: not run.** Neither six-rank progression, one-star behavior, overflow no-op nor record round-trip has been proven through the requested native path. No new hook exists to audit; the requested static stack/unwind audit, payload build and verification for packed wiring remain outstanding. Existing proofs cover the older six-lease runtime only. STARS-FIX permits an award to carry overflow through completed stars; it prevents the simultaneous parallel progress bug, rather than forbidding overflow.
4. **Unicorn SIGILL baseline: reproduced.** On unchanged `integration/next` at `afbf3ce`, each of `test_recruit_ranks.py` and `test_recruit_runtime.py` independently exits 132 (SIGILL) in Unicorn 2.1.4 `mem_map` on ARM64 macOS with Python 3.13.17. A standalone `Uc(UC_ARCH_X86, UC_MODE_64).mem_map(0x140000000, 0x1000000)` also SIGILLs before project code, including under a separate local Python 3.12 / Unicorn 2.1.4 installation. Fresh processes do not fix it. No passing alternative build was validated; retry on a host or Unicorn build where this minimal mapping succeeds. Skipping Unicorn is not a proof.

## Prior art checked

- **Overlord:** Cryswar's Unlicense `class-support/overlord-source/d5_custom_classes.c`, including the 16 caller site table, stage slot and 120-byte pool, is the reference design. Its eviction and truncation are deliberately excluded by the coordinator's decision. Credit: Cryswar.
- **Sorrow:** `community/sorrow/RESEARCH-INDEX.md` and `ida-export-20261014/disgaea5_names.json`; the latter labels `0x1C62A0` as marking a character seen, so its role requires tracing rather than relying on the label.
- **Decomp:** `/Volumes/Data/Decomp/d5/functions/14021ebe0_FUN_14021ebe0.c` and `14015f480_FUN_14015f480.c` show the vanilla mapper and writer effects. No relevant D5 packed implementation was identified in the D4 decomp.

## Next work

Implement and prove a native transaction with authenticated unit extraction and capacity reservation spanning writer effects and reentrancy, then add the rank-flag integration and requested real-path proofs, stack/unwind audit and payload verification. A validated Unicorn environment is needed for affected executable proofs. Native gameplay, migration of a copied real save, removal safety and installation remain separate acceptance gates.
