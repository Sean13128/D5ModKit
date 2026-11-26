# WHEELS3 — overlay: the wheel page filter no longer freezes the game

Built 2026-10-30 by the WHEELS3 lane. **Offline build: nothing here was installed, launched, saved or played.**

This is an **overlay on `Builds/LIVE5_TEST16-20261030`** (the same base as `WHEELS2-20261030`), not a full
bundle. Install TEST16 first, then copy these two kit files over it and press Install.

## What it fixes

WHEELS2's page filter froze the game the moment *Hire Character* was confirmed (LIVE12, twice,
reproducible, cured by reverting the two files). The cause was one instruction:

```
0x148095657   call 0x1408ce670        ; WHEELS2: "the GetKeyboardState thunk"
```

`0x1408d5640` (translated: `0x1408ce670`) is not a thunk — it is the **import address slot** in
`.rdata`: eight bytes holding USER32!GetKeyboardState's address. That is the address
`d5lib/native/d5auto.c` replaces to see the harness's keys, and it is **data**. Calling it runs the
pointer's bytes as code (`ac f9 9f 00 → lodsb / stc / lahf / add [rax],al`), which faults inside the
scene-enter thread — the thread that builds the list, i.e. the one that never came back.

The fix loads the slot and calls the pointer:

```
mov rax, 0x1408ce670     ; the slot
mov rax, qword ptr [rax] ; the function the loader put there
test rax, rax
je  wh_nokeys            ; slot empty: keep the wheel the last opening used
sub rsp, 0x20
mov rcx, r10
call rax
add rsp, 0x20
```

Reading the slot at run time also picks up the runtime's own replacement, so an agent's injected
Shift+2 is visible to the page key. Nothing else about WHEELS2 changed: same page table, same
owner table, same six-entry minimum, same capture, same tail clearing, same two relocated
IS_UNLOCKED calls.

## Files

| path | what it is |
|---|---|
| `kit-install/d5lib/newclasses.py` | **replaces** TEST16's / WHEELS2's: the slot call, everything else as WHEELS2 |
| `kit-install/d5lib/wheelmeta.py` | **new** (same as WHEELS2): the `wheel` field / source-game default |
| `tests/test_wheel_page.py` | 14 tests, updated to stand in behind the slot |
| `tests/test_wheel_hires.py` | **new**, 8 tests: per page, per cursor, what the menu reads; both menus; the CALL's ABI |
| `tests/test_wheelmeta.py` | unchanged metadata tests |
| `wheels/proof_keyslot.py`, `wheels/proof-keyslot.json` | the A/B on the pinned bytes: `call <slot>` faults, `call [slot]` returns |
| `wheels/static_stack_wheels.py`, `wheels/static-stack-wheels3.json` | static stack audit (0 new findings; the new CALL is `call rax`, aligned, home space clear) |
| `wheels/build_payload_wheels.py`, `wheels/payload-wheels3.json` | payload build + per-page read-back (58 owners, 45 D4 / 13 D1C, 0 structural problems) |
| `wheels/WHEELS3-DIAGNOSIS.md` | the evidence for the diagnosis, address by address |

## Install

1. TEST16 installed and working (exe `df8b282c…`); game **closed**.
2. Copy `kit-install/d5lib/newclasses.py` and `kit-install/d5lib/wheelmeta.py` into the kit's
   `d5lib/` (this replaces WHEELS2's copies if they are still there).
3. Start the kit, press **Install**. It rebuilds `disgaea5.exe`; expect "Install complete."
4. Fully restart the game (not a menu reload — LIVE2's false failure came from skipping this).
5. Run `LIVE-CHECK.md`.

Nothing else is needed: no mod folder changes, no profile changes. The 152 mod folders and the
`LIVE5_TEST16` profile stay exactly as TEST16 ships them.

## Safety

* If the wheel freezes again, the game log is the first thing to read: Wine hides a crash dialog
  behind `hide_game.sh`, so look for `Unhandled exception` / `0xc0000005` before assuming a hang.
  `WHEELS3-DIAGNOSIS.md` §"Not the cause" lists what this fix does **not** touch.
* Reverting is two files: TEST16's `newclasses.py`, and delete `wheelmeta.py`.
