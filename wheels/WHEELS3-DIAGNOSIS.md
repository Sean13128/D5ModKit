# WHEELS3 — diagnosis notes (offline)

## The defect (proven)

`d5lib/newclasses.py` (WHEELS2 line) `KEYS_VA = 0x1408D5640`, emitted as a direct `call`:

```
0x148095649  lea r10, [rip - 0x1e24]      ; wheel_keys
0x148095650  sub rsp, 0x20
0x148095654  mov rcx, r10
0x148095657  call 0x1408ce670             ; <-- the bug
0x14809565c  add rsp, 0x20
```

0x1408D5640 is **not** a function. It is the **import address slot** (the 8-byte pointer in
`.rdata` that the loader fills with USER32!GetKeyboardState's address). Proof, from the pinned exe
(`.../state/games/Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full`, sha256 49a7530b…):

* pefile import walk: `USER32.dll GetKeyboardState -> IAT 0x1408ce670`
* section of 0x1408ce670: `.rdata` (starts 0x1408ce000), bytes `ac f9 9f 00 00 00 00 00 | 9a f9 9f …`
  — two consecutive 8-byte pointers, i.e. data, not instructions.
* `d5lib/native/d5auto.c:426-429` uses the same address **as a slot**: `void **slot =
  (void**)G(VA_IAT_GETKEYBOARDSTATE); *slot = hkGetKeyboardState;` — it *dereferences* it.

So the hook calls the slot's address: the CPU decodes the pointer bytes as code
(`ac` lodsb / `f9` stc / `9f` lahf / `00 00` add [rax],al …) and the third instruction writes
through `rax` (a small value at that point) -> access violation in the scene-enter thread. That is
the thread that builds the list, i.e. exactly the "confirm that opens Hire Character never
returns" of LIVE12 (twice). The runtime's command loop lives in the same thread's frame hook, so
the pipe goes dead; the process stays alive around the fault (Wine crash dialog), ~0 % CPU.

Why WHEELS2's proofs missed it: every test (and the payload/static audits) *stub* the thunk
address in Unicorn, so the call target was never executed and never checked to be code.

## Not the cause (checked)

* Stack alignment at that call: measured in Unicorn on the built TEST16 bytes — RSP%16 at the
  `call` is 0 (the capture block's three pushes are popped before the filter runs), the callee
  entry sees 8. Correct. (A future edit that changes the pushes would break this; a test now
  measures it.)
* Entry/count/index handling: the cursor reads the list through the relocated stubs
  (`0x140668585` ranks / `0x140668599` family, both in CAROUSEL_SITES -> `carousel_buf[idx*8]`),
  count stays at `+0x208` in the object, tail entries are -1. The filter preserves pair order and
  rank counts, so cursor c -> page[c]. No index/class-id confusion.

## Both menus reach the one hook

* Recruiter: vtable 0x14098bd58 slot +8 = enter `0x140663b20` -> builder `0x140664df0`
  (call at `0x140663c32`), the only direct caller.
* Rebirth: vtable 0x14098bc90 slot +8 = enter `0x140483710`, whose first act is
  `call 0x140663b20` (`0x140483732`). Same builder, same hook, same page value.

## Fix

Read GetKeyboardState through the slot (`mov rax,[slot]; test rax,rax; jz keep; call rax`).
That is also what makes the harness's injected keys visible (the runtime replaces the pointer).
