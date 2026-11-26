# WHEELS3 — what changed since WHEELS2, and what was proven offline

## One defect, one fix

| | |
|---|---|
| **Symptom (LIVE12)** | accepting *Hire Character* never returns; runtime pipe dead; reproducible twice; reverted → instant |
| **Caused by** | the page filter's `call 0x1408ce670` |
| **Because** | `0x1408d5640` is the **import address slot** of USER32!GetKeyboardState (8 bytes of `.rdata`), not a thunk — the call ran the pointer's bytes as code and faulted in the scene-enter thread |
| **Fixed by** | `mov rax,[slot]; test rax,rax; je keep; call rax` — the pointer is loaded and called (this is also how the runtime sees injected keys) |
| **Also kept** | when the slot is empty the stored page is used, no call into nothing |

Nothing else in WHEELS2's page filter changed: the owner table, the capture, the page choice, the
six-entry minimum, the tail clearing and the two relocated `IS_UNLOCKED` calls are the same bytes logic.

## Offline evidence (this bundle)

| check | what ran | result |
|---|---|---|
| the A/B that decides it | `wheels/proof_keyslot.py` on the pinned exe: `call <slot>` vs `call [slot]` | **A faults inside the slot's bytes (rip = `0x1408ce670`, faulting address 0); B returns 1** |
| page logic, real builder | `tests/test_wheel_page.py` (real builder `0x140664df0` + real hook, Unicorn) | **14/14** |
| hires the class under the cursor | `tests/test_wheel_hires.py`: 3 pages × every cursor position, the game's own relocated read stubs; Rebirth's own three reads; both menus reach the hook; the CALL is aligned with home space | **8/8** |
| static stack audit | `wheels/static_stack_wheels.py` (the shared `abi-review` audit) | 138 sites, 5 CALL edges, **0 new findings**; the new `call rax` is aligned with clear shadow space; the 2 reported are the pre-existing `0x1402a3d30` ones |
| payload | `wheels/build_payload_wheels.py --run-pages` on the TEST16 profile | 58 owners, **45 D4 / 13 D1C**, **0 structural problems**; page read-back 45 / 13 |
| whole kit suite | `python -m pytest tests` on this worktree | **39 failed / 970 passed / 2 skipped** — the same 39 environment failures as TEST10…TEST16 |

## What is still **not** proven

* **Any live behaviour.** No menu was opened in a running game by this lane. `LIVE-CHECK.md` is the test.
* The mechanism is proven (the call target is data; the replay faults there) and the live freeze was
  measured only as "never returns" — LIVE12 never read the game log for `0xc0000005`, so the fault being
  the *live* fault is inference from a proven instruction plus a reproducible A/B, not a backtrace.
* Rebirth's route is still not mapped in the harness (`NAV-REPORT` §7); its builder path is proven
  statically (vtable `0x14098bc90` +8 → `0x140483710` → `call 0x140663b20` → the hooked builder).
