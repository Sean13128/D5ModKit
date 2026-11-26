# P2e — packed mastery, native step 2: award / writer / unlock path (offline)

## Plain-English result

A packed mastery award now behaves like a vanilla one.  The game's own writer
(`0x14015F480`) asks "which mastery slot is this class?" — the packed hook answers slot 52 for
a configured family, exactly as step 1 proved — and the wrapper hands that same writer the
**family base** instead of the rank id, so its own reward loop starts at star 1 and carries
overflow upward.  One star per award, as STARS-FIX established for the six-slot extension.
Every counter, the eight permanent bonus words, the sub-class bookkeeping and the unlock call
are still written by the game's code; the hook never writes counters itself.

Capacity is reserved before the writer's first side effect.  The writer's mapper call is the
only place in the award path that can consume pool space, the hook does the whole stage switch
(all validation, all arithmetic, then one commit) before writing anything, and a pool that
cannot take the result answers "no mastery".  The writer then does **nothing at all** — the
game's own slot gate skips the counter loop, the bonus words, the unlock call and the
sub-class refresh.  Nothing is evicted, nothing is truncated, nothing is half-applied.

The unlock path is settled by tracing it: the only global effect of a rank completion is
`data_progress_mark_character_seen` (`0x1C62A0`), and its first instruction is a range gate
(`1000..1310`, `2010..2300`).  A packed family's ids return immediately — no read, no write —
so the correct integration is **no hook at all**, proven by a memory-write trace and a
byte-identical global flag bitmap.  Vanilla ids still mark their class seen, identically
patched and unpatched.

Install shape: `.d5pm` and `.d5cm` cannot coexist (same 16 calls).  A build with six families
or fewer uses `.d5cm` and its leases; more families use `.d5pm`, which now also carries
`.d5cm`'s sub-class gate, sub-class screen fetch and screen loop bound, so it is a drop-in
replacement.  Both builders refuse the other by name, before touching any site.

Offline only: no game launch, no install, no real save, no Steam folder, no `Local/Installed
D5ModKit`, no push.  Worktree `Local/Worktrees/p2-mastery`, branch `p2-mastery`.

## Commits (local, not pushed)

    d845492  Give the packed mastery award path the writer's family base and its sub-class hooks
    20bf929  Prove the packed mastery award path with the real writer, builder and unlock call

Base before this step: `fe464b6` (step 1, coordinator-verified).

## What changed

| file | what |
|---|---|
| `d5lib/packedmasteryhook.py` | writer-site `r10` = family base (`X_AWARD` flag, `R10_SAVE`); `.d5cm`'s sub-class gate + screen fetch + screen bound become part of `.d5pm`; `mode_for()`; `build_patch` refuses a `.d5cm` exe by name and patches 18 sites |
| `d5lib/masteryext.py` | `.d5cm`'s builder refuses a `.d5pm` exe by name (one line, lazy import) |
| `d5lib/exepatch.py` | `.d5pm` unwind rules gain `allow_exits` + `allowed_writes=("r15",)`, like `.d5cm` |
| `tests/test_packedmasteryhook.py` | 24 tests (was 18): award-flag emission at exactly one site, `mode_for`, the sub-class sites and bound, both refusals by name, layout stability with the new routines |
| `mastery/proof_packedaward.py` | new: the award path through the real writer + a small ABI engine case set |
| `mastery/proof_packedmapper.py` | `--abi` allows the one intentional `r10` change at the writer site, and records it |
| `mastery/static_stack_packed.py` | audits the 18 sites (16 mapper + sub-class gate + screen fetch) and the bound byte |
| `mastery/verify_packed_payload.py` | verifies those 18 sites, six unwind entries and the bound inside the 17-feature payload |

### The award rewrite, in the wrapper's own terms

```
pm_s1:                       ; the writer's own mapper call (return address 0x14015F505)
    mov r14, rbx             ; the record
    mov dword ptr [rsp+0x108], 1     ; "this caller may be handed the family base"
...
pm_ret_stage:                ; about to answer 52
    cmp dword ptr [rsp+0x108], 0
    je pm_award_done
    mov eax, dword ptr [rsp+0xE0]    ; the configured family
    mov dword ptr [rsp+0x160], eax   ; the pushed r10 -> the value the caller will pop
pm_award_done:
    mov eax, 52
```

`0x160` is `FRAME + 0x48`, the saved `r10` (5th of the 14 pushes).  The write is a 32-bit
move, so the caller's upper half survives, exactly like the writer's own `mov r10d, edx`
(`0x14015F4AA`); the writer re-reads it with `mov ecx, r10d` at `0x14015F51C` and derives its
rank limit from it (`0x14015F56C` `call 0x14021EE80` = `id % 10`).  No other site's `r10` is
touched — at `0x140217246` and `0x1402A3A62` it holds the record pointer itself, and the
proof asserts it is restored there.

Order inside an award, for the record:

1. `0x14015F500` → hook: identify the site (return address), read the record from the caller's
   register, call the game's mapper, scan/validate the pool, plan the switch, **check capacity**,
   commit the switch (pool + slot 52) in one batch, answer 52, rewrite the caller's `r10`;
2. `0x14015F508` `cmp r8d, 0x34 / ja` — a refusal (-1) leaves here and the writer does nothing;
3. the rank loop (`0x14015F5D0..`) writes the staged slot's counters from rank 0 upward, pays
   the eight bonus words on each new completion (`+0x359C`), calls
   `data_progress_mark_character_seen(rank id)`, refreshes the unit's class/sub-class fields
   (`+0x2E04`, `+0x35AC`).

Because an award only moves counters *toward* their JobRank threshold, and a completed rank
is implied by the header (fewer bytes), a stage that fit before an award still fits after it.
That is why reserving at the switch is sufficient and no post-award rollback is ever needed.

## Offline proofs (executed native instructions, Unicorn)

All entries are the game's own instructions: the 16 mapper call sites, the writer's entry, the
reader's entry, `0x1C62A0`'s entry, and the two sub-class sites.  Receipts:
`mastery/proof-packedaward.json` (9/9), `mastery/proof-packedaward-abi.json` (11/11),
`mastery/proof-packedmapper.json` (9/9), `mastery/proof-packedmapper-abi.json` (11/11),
`mastery/packed-static-stack.json`, `mastery/payload-verify-packed.json`.

### Award path (`proof_packedaward.py`)

| check | result |
|---|---|
| `award-one-family` | 1, 7 and 45 configured families, each built by the **real builder**: a rank-5 target with 7 XP leaves `[7,0,0,0,0,0]` in slot 52 and pool header `C5 01 <family/10>`; the rest of the 0x4800 record is byte-identical; the unpatched build awards **nothing** (record unchanged) |
| `award-six-ranks` | six awards of 4 XP, targets `1350..1355` in both orders → `[24,0,0,0,0,0]` (STARS-FIX's one-star order through the packed mapper) |
| `award-completion` | 100 XP → `[64,36,0,0,0,0]` with the eight bonus words `1..8` paid once; a second award → `[64,256,8,...]` with `2,4,..,16`; the offline `masteryaward.project` agrees |
| `award-two-units` | two units, two awards: unit B's award leaves unit A byte-identical; each pool header names its own family |
| `award-pool-full` | 38 completed entries + a staged family (4 + 114 of 120 bytes used), award to a family already in the pool: mapper −1, **record byte-identical**, reader still answers 0, unpatched identical |
| `award-capacity-first` | a switch that does not fit is refused with **zero bytes written** (no pool compaction, no bonus, no stage change); the same award on a fresh unit completes `[64,36,...]`, so the refusal is about capacity, not about the award |
| `award-round-trip` | award → switch to another family (real mapper call inside the writer) → the finished family is packed (`header 0x…` = family 135, k=1, n=1, value 36) → switch back restores `[64,36,0,0,0,0]`; the game's own reader reports 64/36/3 from the bytes a save would hold, and 0 from the unpatched build |
| `unlock-custom-noop` | `0x1C62A0` for 1350/1355/1360/1400: **zero memory writes outside the stack**; a vanilla 1010 still writes its flag, with identical write addresses patched vs unpatched; a packed completion through the real writer writes **no** byte outside the unit record |
| `writer-r10-and-vanilla` | at `0x14015F500`: target 1355 and 1350 → `r10 = 1350`; targets 1015, 1300, 1370 → `r10` untouched; a vanilla award is byte-identical before/after |

### ABI (`--abi`, site-entry with a clobbering stub for the original mapper)

| check | result |
|---|---|
| `abi-writer-site-r10` | the writer's site entered with `rsp%16 == 8`, home space poisoned: answer 52 **and** `r10 = 1350` for a configured family; every other caller-live register preserved; the vanilla case answers −1 and keeps `r10`; no unexpected call edge, no write outside the record |
| `abi-subclass-sites` | the gate entered by the game's jump reaches `0x140160E89` for 1350 and 1015 and `0x140160E8C` for 1370, all non-volatile registers intact; the screen fetch entered by the game's call answers the vanilla stack array below index 47, `1350`/`1360` at 47/48 and 0 at 60 |
| `proof_packedmapper --abi` | 11/11, including the 16 mapper sites × 3 cases (stage / vanilla passthrough / refusal) with the writer site's one intentional `r10` change |

### Static audit

`static_stack_packed.py`: **2 and 45 families → 18 sites** (16 mapper calls + sub-class gate +
screen fetch), 6 call edges, 12 / 55 returns, 2 native exits, 0 unknown instructions, 0
home-space stores, **0 findings**; family table offset/count/version and the screen bound
(`0x2F + n`) checked.

### Payload build and verification

17 features in finalizer order, `.d5pm` in `.d5cm`'s place, from the pinned exe:
`payload.exe` sha256 `2ea7e050733de102f4a2b4013af0e430749d8bf9662d2f85f60f5ff23a84c424`,
claim at `0x148092260` inside `.d5mod` (144 header bytes left), code 2 640 bytes identical to
the same section rebuilt at the payload's own base, **18 sites** call the claim
(mapper ×16, gate by jump, fetch by call), screen bound 49, **6 unwind entries** sorted and
non-overlapping, no foreign jump into the claim, `.d5cm` absent, reverse order refused with a
named error.

### Kit test suite

`pytest tests -q` (offscreen, Unicorn venv): **470 passed, 39 failed, 1 skipped** vs. this
branch's base `557adfd` **441 passed, 39 failed, 6 skipped** — FAILED set byte-identical file by
file, +24 new tests in `tests/test_packedmasteryhook.py`, and 5 Unicorn-dependent recruit
checks that skipped in the baseline ran and passed here (the environment is flaky about that
probe, see `SIGILL-REPORT.md`).

## Prior art checked

- **Overlord** (`class-support/OVERLORD-COMPARISON.md`, `overlord-source/d5_custom_classes.c`,
  The Unlicense, **credit Cryswar**): the award path is his design — "all vanilla mastery code
  then runs unchanged on slot 52: gain with carry-over (0x15F480), rank stat bonuses,
  UnlockClassTier(next rank), the rank notification, Class-tab stars".  Taken: the staging
  slot, the 120-byte pool, the site/register table, and the observation that the writer's
  mapper call is the one place a rank target has to be reduced to the family base (his
  `cc_find_rank`/reference-key handling is the same idea).  Deliberately **not** taken: his
  pool-full policy (drop the least partial progress) and his tier model.  His `cc_pre_unlock`
  *skips* `0x1C62A0` and keeps its own 3-bit "highest rank unlocked" in unused game flags
  `17283 + 3*slot`; that is a class-grid unlock mechanism, not mastery storage, and D5 Mod Kit
  already owns class/rank unlocks through its class lane, so nothing of it is ported.  His
  note that custom ids are rejected by the same range gate is confirmed by disassembly here.
- **Sorrow** (`community/sorrow/RESEARCH-INDEX.md`, `ida-export-20261014/disaga5_names.json`):
  the `0x1C62A0` label (`mark_character_seen`) is what sent this step to trace the function
  instead of trusting the name — done, and the label is right but incomplete: it is also the
  class-seen flag writer, gated by a class-id range that excludes packed families.
- **Decomp** (`/Volumes/Data/Decomp/d5/functions/`): `14015f480` (writer: slot gate `> 0x34`,
  rank limit from r10, bonus words `+0x359C`, unlock call, `+0x2E04`/`+0x35AC` refresh),
  `1401c62a0_data_progress_mark_character_seen` (range gate, flag bitmap), `14021ebe0`
  (mapper), `140217230`/`1402172e0` (readers), `14021ee80` (rank helper).  D4 has no relevant
  packed mastery implementation.
- **Existing Kit code**: `d5lib/masteryext.py`'s `.d5cm` (the STARS-FIX `r10` adjustment this
  step mirrors, and the sub-class gate/fetch generators now reused verbatim for `.d5pm`),
  `d5lib/packedmastery.py`/`masteryaward.py` (offline models, used as the independent
  expectation in the proofs), `d5lib/exepatch.py` (frames, unwind, claims).

## Install shape (decision)

`mode_for(families)` states the rule in code: **≤ 6 families → `.d5cm`** (six native slots,
persisted leases, no per-unit space limit); **> 6 families → `.d5pm`** (120-byte pool per
unit, unlimited configuration count).  `.d5pm` carries `.d5cm`'s three non-mapper patches, so
a packed build keeps sub-class awarding and the sub-class screen.  Both builders refuse the
other one **by name** before touching a site:

    packed mastery (.d5pm) and the six-slot mastery extension (.d5cm) map the same 16
    class-mastery calls: this exe already carries ".d5cm".  A build has one mapping source […]

Not done by this lane (needs the coordinator's call, and an installer change): wiring
`mode_for` into the install finalizer so a build picks the source automatically, and the
`mastery_slots.json`/lease decision for a packed install (a packed build must not consume the
six leases).  Until then the exe-level refusal is what keeps an install honest.

## What this does not establish

- **Nothing is installed, launched, saved or played.**  Native gameplay, a real save
  round-trip, the Class tab's stars, the sub-class screen and removal safety remain live
  acceptance gates.
- The writer's **notification path** (`param 5 != 0`, `0x14015F7xx`) is not exercised: every
  proof run passes 0.  The `0x2E04`/`0x35AC` refresh runs only when the completed rank is the
  unit's own class; the proofs award to a family the unit is not, so that branch is untouched
  (its code is the game's, unchanged).
- The sub-class screen's **47-row cap** is unchanged: `masteryext._fetch_src` offers packed
  families at indices ≥ 47 only while the screen has fewer than 47 rows started, which on a
  fully unlocked save means the screen lists none of them.  Pre-existing, out of scope here,
  and recorded so it cannot be mistaken for coverage.
- Windows unwind dispatch is checked structurally (records, sort order, retention) and by the
  ABI engine's frame checks, not by a real `RtlVirtualUnwind`.
- A **legacy six-slot save** is not migrated to a packed one: `d5lib/masterymigration.py`
  specifies a copied-save migration with explicit leases, and no save was read or written here.
- `mode_for`'s split is a policy, not a measurement: whether the class lane ships ≤ 6 or > 6
  families in a given profile is the coordinator's build decision.

## Next (live acceptance, when the coordinator schedules it)

Mod `{"mastery": {"families": [<more than six>]}}`, `Save_001` only, **never `Save_002`**,
`hide_game.sh` running, packed build installed and the game fully restarted:

1. `objdump`/PE: `.d5pm` claim present, 16 mapper `E8` sites + the gate `E9` + the fetch `E8`
   point into it, `.d5cm` absent.
2. Status → Class before a fight; win one battle: **only star 1's bar moves**.
3. Cross star 1's threshold: the bonus is announced once, the leftover shows in star 2.
4. Two units of different packed families; save, quit to title, reload: bars exactly as saved.
5. Vanilla control: a vanilla unit's class XP and stars are unchanged.
6. Sub-class control: a vanilla-class unit with a packed sub-class earns XP on the
   sub-class family, one star at a time.

Report back: the site bytes from (1), the before/after star values from (2)–(3), the
post-reload values from (4), and a Class-tab screenshot.
