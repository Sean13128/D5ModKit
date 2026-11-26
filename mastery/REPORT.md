# EX-07b — ABI site-entry proofs, static audit, unwind records and save-round-trip behaviour

Branch `feature/class-mastery`, worktree `Local/Worktrees/engine-ext-mastery`. Offline only: no game launch, no
install, nothing written to the installed kit or the Steam folder. Every number below came from the pinned original
exe (sha256 `49a7530b…db282ce`) plus the extension's own section, executed in Unicorn.

Base of this round: `766b882`. This round's commits: `bbdb2af` (unwind + static audit), and the commit that carries
this report (ABI engine, extended behaviour cases, report).

All commands use the shared venv:

    PY=/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python
    cd Local/Worktrees/engine-ext-mastery

## What was missing before this round

The first EX-07 round proved behaviour (vanilla identity, custom XP, sub-class honouring, the screen list) but not
the ABI rules the lane rules require for an exe hook: nothing entered a patched site as its caller enters it, there
was no static stack audit of `.d5cm`, the section carried no unwind records, and progress had never been taken
through a save-sized byte round trip.

## Results

| Check | Command | Result |
|---|---|---|
| Behaviour proof | `$PY mastery/proof_mastery.py --json mastery/proof-mastery.json` | **8/8** checks, 45 s |
| Behaviour + site-entry ABI proof | `$PY mastery/proof_mastery.py --abi --json mastery/proof-mastery-abi.json` | **11/11** checks, 50 s |
| Static stack audit of `.d5cm` | `$PY mastery/static_stack_mastery.py` | **0 findings**, 2 family configurations, receipt `mastery/mastery-static-stack.json` |
| Build-only (no Unicorn) | `$PY mastery/proof_mastery.py --build-only` | exit 0 |
| Mastery + unwind tests | `$PY -m pytest tests/test_masteryext.py tests/test_evility_unwind.py -q` | 25 passed, 10 subtests |
| Full kit suite | `$PY -m pytest tests -q` | 288 passed, 1 skipped, **39 failed** — the documented pre-existing environment failures (`gamepacks`, `gamepacks_ui`, `offlinepaths`, `d4expansion`, `d4source`, `d4unique`: "symlink in artifact source path" and cache-path cases). No new failures. |

Build receipt (`.d5cm`, families 1350/1360): base `0x14808f000`, section size 248 956 bytes (213 bytes of code +
xdata + a relocated copy of the exe's runtime-function table), patched sha256
`6e1390f2c84a2d8d153ffc803a7c26fda9014bc7fd14ae84d238f69026d1063f`, 16 mapper sites, slots `{1350: 47, 1360: 48}`.

## 1. Site-entry ABI proof — `mastery/abi_engine_mastery.py`, `proof_mastery.py --abi`

Modelled on `Local/Worktrees/engine-ext-capacity/evility/offline_proof_ex05c.py --abi` +
`abi_engine_ex05c.py`. The real patched instruction is the entry point of every run; the original game callee is a
deterministic stub that returns a chosen answer and clobbers every volatile register a real callee may clobber.

Two entry kinds, because `.d5cm` patches two kinds of instruction:

* **call** — `E8` redirection: entered with the caller's `RSP%16 == 0`; the pushed return address gives the
  extension entry `RSP%16 == 8`; the run must return to exactly `site + 5` with `RSP` restored and no live frame.
* **jump** — the `E9` over the sub-class gate: nothing is pushed, entry keeps the caller's `RSP`, and the stub
  leaves by jumping to `0x140160E89` (accept) or `0x140160E8C` (reject); those are where emulation stops.

Asserted at every site (each failure names the address):

* the site still holds the expected opcode and the target is inside the extension section;
* callee-entry alignment `RSP%16 == 8` after every `call`, including the extension's own call of the original;
* 32 bytes of home space at every call, not overlapping a live push/return slot, and **poisoned** first — a caller
  that kept a live value in outgoing home space is caught on the read;
* every `ret` returns to the address its own `call` pushed, with the frame balanced (`RSP` delta 0 at `site + 5`);
* every written byte stays on the emulated stack — the extension has no side effects of its own;
* integer nonvolatiles `rbx, rbp, rsi, rdi, r12..r15` and `XMM6..XMM15` come back unchanged, `mxcsr` control bits
  and the direction flag untouched (the one documented exception: the fetch stub's `r15d` is the destination the
  replaced `mov r15d, …` wrote, and the gate's `eax` is scratch);
* the stub receives exactly the argument registers the caller set (the mapper's id reaches the original in `rcx`,
  i.e. the wrapper really forwards it and keeps its own copy in `rbx`), and each stub answer decides the
  extension's answer.

Coverage: **83 site-entry runs** — 16 mapper sites × 4 answers (custom family rank 0 and rank 5 → 47; unclaimed
`1300` → `-1`; vanilla `1010` with the stub answering `12` → `12`), the fetch site at 10 indices (0, 25, 26, 46 →
vanilla families; 47/48 → configured; 49/60 → nothing; 47/48 with 47 rows in use → nothing), and the gate at 9
sub-class ids (1350/1355/1360/1010/2015 accept, 1370/1349/2460/0 reject). Every run ends at its documented
continuation; the mapper runs take at most 27 instructions.

Flags: the replaced gate instructions and the fetch instruction set no flags a caller reads, so the stubs' own
`cmp`s are harmless — checked statically for both gate exits and for `0x140470BD5`
(`flags_consumed_within` → no flag reader before the next legal flag clobber or the next `call`).

Negative controls (run by hand, not in the report file): the proof **rejects** a wrapper whose `push rbx`/`pop rbx`
save is removed (frame/alignment), a wrapper shrunk to 16 bytes of home space (home space overlaps a live save), a
fetch stub that also writes `ebp` (caller-live nonvolatile changed), and a gate stub that starts with `xor edx, edx`
(the unit's own class, which the reject path hands to the writer). Each mutant was produced by editing the built
section in place, so the section builder's own checks could not mask the result.

### Vanilla award semantics found while writing the D4 case

`0x14015F480` does not write "the counter of the class's own rank". An award for class `family + d` walks ranks
`0..d` and adds the (clamped) amount to each counter, carrying the overflow upward when a counter reaches its
JobRank threshold and adding that row's eight bonus bytes once (`old >= threshold` skips the bonus). That is the
game's own behaviour, identical before and after the extension, and it explains the shape the D4 case asserts.

## 2. Static stack audit — `mastery/static_stack_mastery.py`

The shared audit (`Subprojects/Engine-Extensions/abi-review/proofs/static_stack.py`) imports `d5lib.evility` and its
`CALL_SITES`, so it cannot be pointed at `.d5cm`; this runner keeps the same rules and trades the evility-specific
parts for `.d5cm`'s: the gate is jump-entered (its exits are terminal and must leave `RSP` as found) and the fetch
stub legitimately writes `r15d`.

Result, for a 2-family and a 6-family build: **19 patched sites** (16 `E8` mapper calls, 1 `E8` fetch, 1 `E9` gate,
1 in-place `imm8` loop bound), 1 call edge per build (the mapper wrapper calling the original), 5 returns (2-family)
and 9 (6-family — one per configured family in the fetch stub), 2 native exits, 0 unknown instructions, 0 home-space
stores, **0 findings**. The audit also proves every redirect lands on a routine the section actually contains.

## 3. Unwind records for `.d5cm` frames — `d5lib/exepatch.py`

`add_code_section` only emitted xdata for `.d5el`. It now emits it for any section listed in `UNWIND_SECTIONS`
(`.d5el` unchanged, `.d5cm` added). The encoder was generalised instead of duplicated:

* `allow_exits` — a branch out of the extension ends a routine (the gate leaves by jumping into native code);
* `allowed_writes` — nonvolatile registers a stub is *supposed* to write (`.d5cm`: `r15`, the destination of the
  instruction the fetch stub replaces).

`.d5cm` now carries three runtime-function records inside its own section, next to a relocated copy of the exe's
existing 20 724, and the exception directory points at the copy:

| Routine | Range (VA) | UNWIND_INFO |
|---|---|---|
| mapper wrapper | `0x14808f010`–`0x14808f052` | `01 05 02 00 05 32 01 30` — prologue 5, `UWOP_PUSH_NONVOL rbx` at 1, `UWOP_ALLOC_SMALL 32` at 5 |
| fetch stub | `0x14808f060`–`0x14808f09c` | `01 00 00 00` — leaf, no stack use |
| gate stub | `0x14808f0a0`–`0x14808f0d5` | `01 00 00 00` — leaf, entered and left by jump |

Cost: the section grew from 213 bytes to 248 956 because the kit's design copies the runtime table into the
section (`.d5el` already did this — a 11 557 376-byte patched exe from a 11 303 424-byte original).

`.d5el` compatibility was checked byte-for-byte: rebuilding the EX-05c evility patch from this worktree gives the
same sha256 (`b8a03b29…76e9d0`) as the untouched `engine-ext-capacity` copy of `d5lib`.

Also verified: the exception directory RVA lies inside the new section, the existing table entry is retained, the
table stays sorted and non-overlapping, and each record's codes decode as above
(`tests/test_masteryext.py::UnwindTests`, plus the unchanged `tests/test_evility_unwind.py`).

## 4. Behaviour cases added — `proof_mastery.py` (checks 5–8)

5. **persistence / save round trip** — the writer awards 8 XP to class 1350 on a record that already holds 10 in
   slot 47 rank 0 and 7 in slot 48 rank 3; the 0x4750-byte record is copied out (what a save holds) and mapped back
   into a **fresh** emulated game: the native reader returns 18 for 1350, 7 for 1363 (slot 48, rank 3), 0 for 1351
   and 1365, and the unpatched build returns 0 for every custom id on exactly those bytes. Vanilla reads (1010,
   1015, 2010) are identical before and after. The inactive companion codec (`d5lib.classmastery`, 10 000-range
   families only) round-trips 384 bytes for 2 units / 3 families, refuses a one-byte tamper, a foreign
   native-digest/generation pair, and refuses a 1350-range family (the native slots own those).
6. **six custom families** — 1350…1400 map to slots 47…52, every rank of every family maps to its family's slot,
   one award per family leaves exactly `[3,0,0,0,0,0]` in its own slot and nothing in the neighbours, the reader
   returns 3 for each, and a seventh family is refused at build time.
7. **vanilla-only save untouched** — a six-award vanilla session (1010, 1020, 1035, 1150, 2010, 2100) produces a
   record byte-identical to the unpatched build (sha256 `cc74717e…560092`) and all 36 spare counters stay zero.
8. **D4 Armor Knight 1350–1355 end to end** — the pilot family (D4 import, template 1150): the mapper answers 47
   for all six ranks; the real writer, fed the game's own live record forward, leaves `[24,20,16,12,8,4]` in slot 47
   (the vanilla rank-cascade semantics above) with no neighbouring slot touched; the reader returns each rank's own
   counter; the same award sequence on vanilla family 1150 (slot 14) is identical before and after the extension;
   the unpatched build awards nothing at all to 1350–1355; the sub-class gate accepts all six ranks; and the
   sub-class screen offers 1350 at index 47.

## Files

| Path | Change |
|---|---|
| `mastery/abi_engine_mastery.py` | new: site-entry ABI engine (call and jump entries, home-space poisoning, nonvolatile/XMM/flags checks) |
| `mastery/static_stack_mastery.py` | new: `.d5cm` static stack audit runner, receipt `mastery/mastery-static-stack.json` |
| `mastery/proof_mastery.py` | `--abi/--site-entry`, checks 5–8, `flags_consumed_within`, `job_table`, report modes |
| `mastery/proof-mastery.json`, `mastery/proof-mastery-abi.json` | receipts (8/8 and 11/11) |
| `d5lib/exepatch.py` | `UNWIND_SECTIONS`, `_extension_functions` (exits, intentional nonvolatile writes), `.d5cm` xdata |
| `tests/test_masteryext.py` | `UnwindTests` (2 tests): three records, codes, retained entry, directory inside the section |
| `docs/MASTERY.md` | proof/audit/unwind summary and the updated test counts |

## Limitations — what is still not proven

* **Native gameplay is not executed.** Everything here is Unicorn over the pinned exe. Nothing was launched,
  installed or loaded from a save; the lane rules forbid it for this task.
* **Windows unwinding is checked structurally, not dispatched.** The records are well-formed, sorted,
  non-overlapping, retain the exe's own entries, and their codes match the prologues; no exception was actually
  raised through `RtlVirtualUnwind` on Windows. The frames are 5-byte-prologue fixed frames, which is the shape the
  encoder only ever accepts.
* **The original game calls are stubs in `--abi` mode** (the mapper and, for the mapper sites, the callee). That is
  the point — it makes argument-forwarding and clobber survival visible — but it means ABI mode proves the
  *redirection*, while the unpatched-vs-patched behaviour checks (which run the real mapper/writer/reader) prove the
  *semantics*.
* **The companion side table is bytes-only.** `d5lib.classmastery` is exercised as a codec; nothing installs,
  reads or migrates it, and the extension still refuses a seventh family.
* **The sub-class screen's 47-row cap** is enforced by the extension's own guard; a save that already shows 47
  classes lists no configured family. Unchanged from EX-07.

## Live checks (a machine with the kit installed, not done here)

1. Build with a class mod declaring `{"mastery": {"families": [1350]}}`; launch; open a D4 Armor Knight unit's
   **Status → Class**: the family is listed and its XP bar moves after a battle.
2. Save, quit, reload: the bar is exactly where it was (this is the one acceptance step the record round trip above
   cannot replace).
3. Set the custom class as a sub-class on a vanilla-class unit: class XP then lands on the sub-class family.
4. Load a pre-extension save and confirm nothing changes (spare slots read 0) and no vanilla class behaviour moved.

Never load `Save_002`.
