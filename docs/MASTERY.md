# Class mastery for custom classes

A custom class shows its stars (the Class tab lists it, `d5lib.newclasses` gives it char.dat rows, `JobRank.dat`
thresholds and unlock flags) but never gained class experience: the game's family → mastery-slot mapper
(`0x14021EBE0`) answers `-1` for every family outside the 47 vanilla ones, and the award writer and every reader
refuse an invalid slot. A custom class chosen as a **sub-class** was equally ignored (`0x140160E20` only accepts
`1000..1310` / `2010..2300` as a sub-class id), and the Strategy Assembly's sub-class screen (`0x1404707E0`) builds
its candidate list from a hard-coded 47-family array on its own stack.

`d5lib.masteryext` fixes that in the exe, in section `.d5cm`. `d5lib.classmastery` (the inactive companion-table
codec) is **not** used: no file, no save format change.

## Where the progress lives

The unit record already has it. A unit is `0x4750` bytes inside the game state blob (`0x89B8C8` bytes) that a save
stores verbatim, so everything in the record is saved, loaded, copied on transformation and carried through
reincarnation by the game itself:

| Offset | Size | Meaning |
|---|---|---|
| `+0x30A4` | `53 × 24` | class-mastery slots: six `u32` rank counters each (the array the reader `0x140217230` addresses) |
| `+0x359C` | `8 × u16` | the eight completion-bonus words |
| `+0x35AC` | `u16` | the selected sub-class |

The mapper only ever produced `0..46`, but the array, the reader's bound (`< 0x35`), the writer's slot arithmetic
(`+0x30A4 + slot*0x18`), the transformation copy (318 `u32` = 53 × 6) and the stars panel all accept the **six spare
slots 47..52**. Those slots are zero in every existing save, and nothing else writes them, so:

* a vanilla save's spare slots read 0 = no progress; the feature is invisible until a custom class earns something;
* progress is stored where the game already stores mastery — no new file, no new save bytes, no migration;
* six families can hold their own progress at once (one slot each).

More families than six would need a side table. `d5lib/classmastery.py` is the reviewed, inactive design for that
(keyed by unit serial and family, exact-pair digest/generation, refuses a missing companion instead of reading zero).
This extension does not enable it: the sixth family is the current limit and is refused at build time, not silently.

Slot assignment is a **persisted lease**, not the sorted family order. `mastery_slots.json` in the game's own kit
state (`state/games/<folder>-<hash>/`) records `family -> slot`, and `d5lib/masteryext.SlotLeases` keeps it.
Offline pack builders set `D5_MASTERY_LEASE_DIR` to keep that file beside the pack instead of in the kit
source tree; the installer never sets it, so a real install always uses the game's kit state.

* a family keeps its slot for good, whatever else is enabled or disabled around it;
* a new family takes the lowest never-used slot;
* a family that leaves the build keeps its slot **reserved** in `retired` — re-enabling it finds its own progress
  again, and the slot is never handed to another family (that would show one class's counters as another's);
* when no spare slot is free the build refuses, names every holder, and says how to release one. Release a retired
  family only when no save can hold progress for it: delete its entry from `retired` by hand.

The built section carries the same table, so a rebuild reads the mapping from the install it is replacing: the first
install after a kit that predates the lease file *adopts* the section's mapping rather than renumbering (the two
builds' sorted orders were identical), and a build whose table would move a family's slot is refused
(`mastery slots would move saved progress`). A damaged lease file is refused, never silently re-derived.

Removal policy: disabling the last mod that asks for mastery removes the section and the hooks; the counters stay in
every unit record (slots 47..52 are simply not read any more), the sub-class ids of those units stay as they are, and
the lease file keeps the mapping, so re-enabling the same family returns it to its own slots. A save made while the
extension was off and then re-enabled is therefore consistent; a save made by a *different* kit with a different
mapping cannot be detected offline.

## Mod data

`patches/classes/mastery.json` in the class mod:

```json
{"mastery": {"families": [1350, 1360]}}
```

* family bases only (id `% 10 == 0`), not rank ids;
* the family must be a class the build creates (a `class_<family>.json` in the same or an earlier mod), so mastery
  cannot be declared for something that does not exist;
* a vanilla family (1010..1260, 2010..2210) is refused — it already has a slot;
* at most six families; duplicates and reserved ranges are refused with a message.

Nothing is patched when no mod asks for it (`_finalize` returns before touching the exe).

## The three hooks

All addresses are the pinned build (`disgaea5.exe`, sha256 `49a7530b…db282ce`). Every site's original bytes are
checked before patching, so a different exe fails with `unexpected exe build` instead of hooking something else.

**1. The mapper (16 direct call sites of `0x14021EBE0`), `CALL` redirection (`E8`).** The wrapper
* calls the original first, so vanilla families keep the game's own answer (`0..46`, or `-1`);
* keeps the id in `rbx` — the original divides it by 10 and clobbers `rcx`;
* returns slot `47 + i` for a configured family's ranks (family `F` → `F..F+9`);
* when it is returning to the award writer (pushed return address `0x14015F505`), rewrites the caller's `r10` — the
  writer's own saved copy of the target id — to the **family base**, which is what makes an award fill one star at a
  time (see below). No other caller's `r10` is touched;
* `push rbx` + `sub rsp, 0x20` is a fixed frame with 32 bytes of home space and the alignment the original expects.

Everything downstream then works unchanged: the writer stores XP in the unit's own six counters, the stars panel and
the six-counter readers read them, and the transformation copy carries them.

**2. The selected-award sub-class gate (`0x140160E79`, 16 bytes), `JMP` in and out (`E9`).** The game's test is
`(sub - 2010) <= 0x122 || (sub - 1000) <= 0x136`; the replacement keeps both windows, adds a configured family's
ranks (`sub - F <= 5`), and jumps to the original accept path (`0x140160E89`) or fallback (`0x140160E8C`). It uses
only `eax`, so `rdx` (the unit's own class) and `r10`/`r11` (the caller's arguments) survive. No return address is
pushed, so the stack is untouched.

This is what makes a custom sub-class count for a unit whose own class is vanilla. A unit whose *own* class is a
custom family relies on `d5lib.newclasses`' generic range widening for the earlier class test (its bound is held in
a register there, so that lane replaces the test with a stub); the native behavior of that path is unchanged.

**3. The sub-class screen's candidate list (`0x140470BD0` fetch, `0x140470DB7` bound), `CALL` redirection.**
* the fetch is replaced by a call to a stub: index `< 47` re-runs the original instruction on the game's own stack
  array, so the vanilla 47 families are byte-for-byte what they were; index `>= 47` returns the configured families
  in order;
* the loop bound's `imm8` is widened from `0x2F` to `0x2F + n` (in place, same instruction size);
* **the screen's 47-row capacity is respected**: rows are `0x238` bytes at `+0x2768` inside a `0x8FC0`-byte object,
  so no row can be added once 47 exist. The stub answers "family 0" then (the native availability test says no), so
  a screen that already shows 47 classes lists no extra ones instead of overrunning the object. A typical save has
  fewer available classes and shows the configured families after them.

The families still have to pass the native availability test (`0x1401C6110`, the unlock flags) and have a `char.dat`
row for the rank — that is exactly the class lane's business and already true for a working class mod.

## Award order: one star at a time

The writer `0x14015F480` (unit record in `rcx`, target class id in `edx`, amount in `r8`) is not "award the counter
of the requested rank". It asks the rank helper `0x14021EE80` for `id % 10` and loops **ranks 0..that**, and only a
counter that *completes* replaces the amount with its overflow (`0x14015F6E3`, `0x14015F6EE`). A non-completing
counter jumps to the loop tail without reducing the award. So a rank-5 target with 7 XP puts 7 into all six counters
(`[7,7,7,7,7,7]`) — the game's own behaviour, which is harmless for native classes because the game only ever awards
their own current rank, and wrong-looking for an imported family whose units are recruited at rank 5. This was the
owner's "all stars rise at once" report.

The fix is one register write in the mapper wrapper. The writer keeps the target id in `r10` across its mapper call
(`mov r10d, edx` at `0x14015F4AA`, `mov ecx, r10d` at `0x14015F51C`) and never re-reads `edx`. The wrapper returns
the slot it always did, and only when the pushed return address is `0x14015F505` (this call really is the writer's)
does it rewrite `r10` to the family base. The native loop then starts at rank 0:

* an incomplete rank 0 takes the award and stops the loop — only star 1 grows;
* a completing rank 0 keeps the game's own overflow path, which extends the rank limit by one and carries the
  leftover into star 2 (and onwards, as many stars as the award covers);
* already-complete counters are walked over: `min(threshold, old + award)` yields exactly the threshold, the
  "old >= threshold" test skips the bonus, and the unchanged award passes to the next counter, so the first
  *incomplete* star is the one that fills;
* the completion bonuses, the current-class refresh, the sub-class rank promotion and the notification block are all
  the game's own code, untouched.

Because the rewrite lives inside the writer's own mapper call, **every** award path is covered: the selected-award
wrapper (`0x140160E20`, own class or chosen sub-class) and explicit calls such as `0x1401517FC` (quest/reward XP)
that never pass through it. Vanilla ids are never rewritten, so a vanilla award stays byte-identical.

### Existing saves with parallel partial bars

Counters an older build filled in parallel are **not** reset or migrated: they are the unit's record, the extension
has no save-side code, and destroying progress silently is worse than a staggered bar. Concretely, for a record like
`[60, 10, 5, 0, 0, 0]` an 8-point award gives `[64, 14, 5, 0, 0, 0]`: star 1 completes, the 4 points of overflow go
to star 2, star 3's stale 5 stays where it is until star 2 completes. The higher partials become visible again as
the frontier reaches them, so nothing is lost and nothing is double counted.

A one-time normalisation is *possible* and is **not applied** without the owner's decision: for each configured
family slot, find the first incomplete star `r`, keep `0..r` as they are, and zero the partials above `r` (they are
phantom awards the old bug produced; completed stars above `r` are impossible with the game's increasing
thresholds, and the eight completion-bonus words are left alone). That would restore a clean single bar but discard
whatever pending XP the phantom partials represent, so it stays a proposal in the report.

**Frames and unwinding.** `.d5cm` carries Windows x64 unwind records for its three routines (`d5lib.exepatch`,
`UNWIND_SECTIONS`), next to a relocated copy of the exe's own runtime-function table, so a stack walk or an
exception raised inside the mapper wrapper can be unwound: the wrapper's `push rbx` / `sub rsp, 0x20` prologue is
encoded as `UWOP_PUSH_NONVOL rbx` + `UWOP_ALLOC_SMALL 32`, and the two stubs — which never touch the stack — get
leaf records. `.d5el` output is unaffected.

## What was proven offline

`mastery/proof_mastery.py` (Unicorn, pinned original exe, no game process):

* **vanilla identical** — the wrapper answers exactly what the unpatched mapper answers for all 282 vanilla ranks
  and 14 out-of-family ids (296 comparisons); the native award writer on a vanilla family leaves the unit record
  byte-identical to the unpatched build;
* **custom XP** — the real writer (`0x14015F480`) with class `1350` and an 8-point award writes `8` into slot 47's
  rank-0 counter and nothing else, where the unpatched build writes nothing at all; crossing a threshold adds the
  JobRank row's eight bonus bytes once and clamps at the threshold;
* **sub-class honored** — the selected-award wrapper passes a configured sub-class id (`1350`) to the writer;
  vanilla sub-classes, monster sub-classes, `0` and unconfigured ids keep their previous answers;
* **listed** — the patched fetch returns the game's own family for indices 0..46, the configured families for 47..,
  and nothing once 47 rows exist; the widened bound covers them; the native availability gate answers yes for the
  configured families (and no for them on the unpatched build);
* **persistence** — an awarded record copied out and mapped back into a fresh emulated game reads back through the
  game's own reader (18 XP for 1350, 7 for slot 48 rank 3), while the unpatched build reads 0 for custom ids on the
  same bytes; a vanilla-only session leaves a byte-identical record with all 36 spare counters zero;
* **six families at once** — slots 47..52, no cross-talk, and a seventh family is refused at build time;
* **award order** — the *real* writer, no stand-ins: a rank-5 custom target with 7 XP gives `[7,0,0,0,0,0]` where
  the old build gave `[7,7,7,7,7,7]`; 100 XP gives `[64,36,0,0,0,0]` with the star-1 bonus once; 400 XP gives
  `[64,256,80,0,0,0]`; a complete star is walked over (`[64,250] + 8` → `[64,256,2,0,0,0]`, no second bonus); stale
  parallel partials are kept (`[60,10,5] + 8` → `[64,14,5,0,0,0]`); the explicit award call `0x1401517FC` and the
  selected-award wrapper `0x140160E20` (custom sub-class 1355) both produce `[7,0,0,0,0,0]`; the same awards on
  vanilla families stay byte-identical to the unpatched build;
* **D4 Armor Knight 1350–1355 end to end** — mapper, real writer (six awards of 4 XP, one per rank id, leave
  `[24,0,0,0,0,0]` in slot 47 — one star, not a cascade), reader, sub-class gate and the screen list, with the same
  sequence on a vanilla family byte-identical before and after (there the game's own cascade is preserved).

`proof_mastery.py --abi` enters **every** patched site the way its caller does (83 site-entry runs): `RSP%16 == 8`
at each callee entry, `E8` + continuation at `site + 5`, 32 bytes of poisoned home space per call, restored frames,
preserved nonvolatiles and XMM6-15, and the caller's argument registers arriving intact at the original callee. The
mapper site that belongs to the writer is also checked to leave `r10` at the **family base**, while the other
fifteen sites and every vanilla id leave the stub's clobbered `r10` untouched.
`mastery/static_stack_mastery.py` audits the assembled section instead of running it: 19 patched sites, 1 call
edge, 0 findings for a 2- and a 6-family build.

`tests/test_masteryext.py` covers the configuration, the award-target policy, the assembled routines, the patch and
the unwind records on a synthetic PE (no game files): 22 tests.

## Live checks (not done here)

This lane is offline only. On a machine where the kit is installed, with a class mod that declares
`{"mastery": {"families": [1350]}}`:

1. recruite/create a character of family 1350, open **Status → Class**: the family is listed with six stars;
2. fight and confirm the class XP bar grows (before the extension it never moved) and that a star fills at the
   `JobRank.dat` threshold; save, quit, reload, and confirm the bar is where it was;
3. open **Strategy Assembly → sub-class edit** on a vanilla-class unit and confirm the custom class appears after the
   vanilla ones, is selectable, and that class XP then goes to the *sub-class* (Status → Class shows progress on
   the sub-class family, not on the unit's own class);
4. check a vanilla class still behaves exactly as before (awards, stars, sub-class list, `Save_001` reload);
5. confirm a second unit of another configured family keeps its own progress (independent slots).

Never load `Save_002`.
