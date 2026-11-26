# Movement carrier investigation (offline, 2026-10-29)

D5 already has a candidate movement counter: signed 16-bit dynamic battle-unit offset `+0x61c` (1564), distinct from the persistent roster record at battle unit `+0x240`. Do not introduce a shadow counter until its semantics have been compared against D4 and all relevant movement paths. This is not an implemented evility and has not been tested in the game.

## Source trace

* Player move: `0x1404cf540` adds the supplied positive cost to `+0x61c`. On an immediately preceding move entry it first restores that entry's original count, coalescing replacement moves. Sorrow `battle__cursor.md` §3.5.3 identifies the supplied value as destination cost-map `0x14024f5d0`, and §3.12 records coalescing.
* Undo: `0x1404d0160` restores the move entry's saved count, conditional on a successful undo. See D5 decomp `1404d0160_confirm_undo_move.c`.
* AI: `0x1405f9fb0` adds `max((signed short)unit[1048] - 1, 0)` when auto-walk reports arrival, subject to its eligibility and movement lock checks. See Sorrow `battle__turn.md` §S3 and D5 decomp `1405f9fb0_turn_ctl_s3_update.c`. Repeated-entry conditions need exercise before assuming one increment per move.
* Turn reset: `0x140159f50` consumes zero/nonzero for the stationary-turn state, then clears `+0x61c`; constructor/bind also clear it. See D5 decomp `140159f50_turn_t3_per_unit_end_turn.c`, `14015b100_dynamic_unit_ctor.c`, `14015a860_hubmgr_per_unit_bind.c`.
* Existing native readers provide useful seams: damage multiplier `0x1401f8fd0` checks evility 1020 and multiplies this counter by that native Skill row's value with a 200 cap; hit calculation `0x1401f5410` checks evility 1060 and uses the same counter, with a row-defined maximum; aggregate `0x1401f0280` checks 105. Their results and restrictions must be compared with each D4 effect before any alias or new scale is called faithful.

Player uses a **cost map** whereas AI uses a **path cursor**. Neither the unit cost for every terrain/movement mode nor D4's own definition of panels has been proven equivalent. Movement via forced relocation, carry/throw, teleport, skills, extra turns, failed undo and map transitions remains untested. A zero field alone is not a proven D4 stationary condition. No new hook or row is safe to ship as faithful based on this work alone.

## Bounded executable proof

`proof_native_counter.py` checks the SHA-256-pinned original executable and emulates its actual `0x1404cf540` bytes in Unicorn for five positive, zero and consecutive-move cases. It substitutes `RET` for the called action-stack pusher in emulator memory; the coalescing fixture supplies the previous stack entry directly. Run with `/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python tools/evcap_movement/proof_native_counter.py`. Five cases passed.

This is a direct function-entry arithmetic proof, not a real-call-site or `--abi` proof; it does not validate the original caller arguments, the action-stack writer, the undo function, AI, turn reset or path semantics. No executable patch was made, so hook static-stack/unwind audits and patched-payload verification do not apply yet. A future Kit effect must use actual patched CALL paths, normal and `--abi` proofs, stack/unwind audit, payload validation, and then native gameplay acceptance.

## Prior art checked

* Overlord: `class-support/OVERLORD-COMPARISON.md` and `overlord-source/overlord/10_evility_runtime.c`; its per-unit-in-range counts units, and no panels-moved tracking was found. Cryswar's existing effect framework remains the architectural reference, not evidence of a movement implementation.
* Sorrow: `community/sorrow/RESEARCH-INDEX.md`, `ida-export-20261014/disgaea5_names.json`, `research-20261014/states/leaves/battle__cursor.md`, `battle__turn.md`, and `battle__damage.md`; the cited movement and native effect traces above are the useful prior art.
* D5 decomp: the individual files and addresses above. D4 decomp index was searched for movement/turn function names; no corresponding annotated counter was located, so source-game equivalence is still open.
