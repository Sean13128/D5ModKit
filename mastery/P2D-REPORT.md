# P2d — packed mastery, native step 1: the mapper hook (offline)

## Plain-English result

The packed-mastery mapper is now a real executable hook, not a model. When a mod's class family is
configured for packed mastery, the game's own "which mastery slot is this class?" function answers
**one staging slot (52) for that unit**, and the family's other progress is packed into the five spare
slots (47..51) of the same unit record in the compact format the offline codec already specified.
Vanilla classes answer exactly what they always did. If a unit's spare area cannot be used safely —
unknown or legacy bytes, a malformed pool, a full pool, a counter that would have to be truncated — the
hook answers what the vanilla game answers (normally "no mastery") and **writes nothing**, which is how
the game already treats a class without mastery.

Only the mapper is wired (this was the task's scope). Nothing yet packs progress back at award time,
no award/writer/unlock/UI path is changed, and the extension is **not installable as a finished
feature**: it redirects the same 16 calls the installed `.d5cm` six-slot hook uses, so the two are
alternatives and the second one to build is refused loudly (proven below).

Offline only: no game, no install, no real save, no Steam folder, no `Local/Installed D5ModKit`, no push.

## What was built

| file | what |
|---|---|
| `d5lib/packedmasteryhook.py` | new engine extension, section **`.d5pm`**, one wrapper for all 16 mapper call sites, family table, pool scan/validate/compact/append, slot-52 decode, JobRank threshold lookup, fail-closed paths |
| `d5lib/exepatch.py` | `.d5pm` registered in `UNWIND_SECTIONS` (fixed-frame unwind records, one line) |
| `tests/test_packedmasteryhook.py` | 18 tests: configuration validation, site redirection, unwind coverage, table round-trip, refusal of an already-hooked exe |
| `mastery/proof_packedmapper.py` | behaviour + site-entry proof (real call instructions, normal and `--abi`) |
| `mastery/abi_engine_packed.py` | site-entry ABI engine (internal calls, writable record, volatile-register contract) |
| `mastery/static_stack_packed.py` | Capstone CFG stack audit of the assembled section |
| `mastery/build_payload_packed.py`, `mastery/verify_packed_payload.py` | full 17-feature layer payload + verification of this hook inside it |

Per-unit layout (both fields already exist in every save):

    record + 0x350C  120 B   pool: C5 01 <staged family/10 : u16> entries...
    record + 0x3584   24 B   slot 52: the staged family's six u32 counters
    entry  = u24 header | 3 * n u24 counters
    header = (family/10) | (k << 13) | (n << 16)      k = completed leading ranks (implied)

The format is the one `d5lib.packedmastery` already specified and the one `d5lib.packedmapper` models,
so the native hook and the offline specification can be compared byte for byte (they are).

## Prior art checked

- **Overlord** (`Private/Overlord and Sorrow research/class-support/overlord-source/d5_custom_classes.c`,
  The Unlicense, **credit Cryswar**): the blueprint. Section-by-section reuse of his design — mapper hook
  at `0x21EBE0` redirected at its 16 caller sites, the (return address → caller register → optional
  dereference) site table, staging slot 52 + five-slot pool, `C5 01` pool header, 13-bit family id with
  k/n counts, thresholds read from the game's JobRank rows. Deliberate differences: his store removes an
  entry before checking space and evicts partial progress or truncates counters when the pool fills; this
  hook plans the capacity **before** the first write and refuses instead (the coordinator's decision).
  Also taken from him: the observation that callers keep live values in volatile registers across the
  mapper call, which is why the wrapper saves rcx/rdx/r8-r11.
- **Sorrow** (`community/sorrow/RESEARCH-INDEX.md`, `ida-export-20261014/disgaea5_names.json`): the
  mapper address and the family/slot grouping; the `0x1C62A0` label (`mark_character_seen`) is not used
  by this step (that is the unlock path, step 2).
- **Decomp** (`/Volumes/Data/Decomp/d5/functions/`): `14021ebe0` (the mapper switch),
  `14015f480` (writer; `param_1` = record at `+0x2E32`), `140217230` / `1402172e0` (the readers),
  `1400b3c70` (progress panel, record at `param_1+0x228`), `1402a3970`/`1402a3d30`/`1402a4300` (class
  tab), `14047f1c0` (Reincarnation, record at `param_1+0x1F1A8`), `1407cd9c0` (skill shop).  D4 has no
  packed D5 mastery implementation.
- **Existing Kit hooks**: `d5lib/masteryext.py` (`.d5cm`, the six-slot mapper wrapper this step's code is
  shaped after, and the proof/audit harnesses in `mastery/`), `d5lib/exepatch.add_code_section` +
  `UNWIND_SECTIONS` (fixed frames, 32-byte home space, canonical epilogues), and LANE-RULES' ABI rules.

## Site table (16 callers) — checked, not assumed

Overlord's table was re-verified against the pinned build for **every** site (decomp where the containing
function exists, otherwise disassembly around the call):

| return site | record in | note |
|---|---|---|
| `0x0B3CED` | `[r13+0x228]` | decomp `1400b3c70`: `param_1+0x228`; asm `mov r8d,[r13+0x230]` |
| `0x15F505` | `rbx` | decomp `14015f480`: `param_1` gate at `+0x2E32`; asm `mov rbx,rcx` |
| `0x217246` | `r10` | decomp `140217230(param_1, param_2)`; asm `mov r10,rcx` |
| `0x21732B` | `rdi` | decomp `1402172e0`; asm `test rdi,rdi` |
| `0x2A3A62` | `r10` | asm `mov r10,[r14+0x90]` before the call |
| `0x2A3B05` | `r9` | asm `mov r9,[r14+0x90]` before the call |
| `0x2A3DDA`,`0x2A3E89`,`0x2A3F39`,`0x2A3FE9`,`0x2A4099`,`0x2A4149` | `rbp` | `test rbp,rbp`; decomp `1402a3d30` reads `[rbp+0x30A4..0x30B8]` |
| `0x2A43D1` | `rbp` | decomp `1402a4300` `lVar2+0x30a4`; asm `test rbp,rbp` |
| `0x47FFCD` | `[r15+0x1F1A8]` | `r15 = rcx`; decomp `14047f1c0` reads `*(param_1+0x1f1a8)+0x30a4` |
| `0x7CDA91`,`0x7CDADE` | `rbp` | asm `[rbp+rdx*4+0x30B8]`, `[rbp+rcx*4+0x30A0]` |

An unknown return address (a compiler version with an indirect call, or another build) is a refusal: the
hook answers the vanilla result and writes nothing.

## Offline proofs (executed native instructions, Unicorn)

Layer 1 only: the game is never launched. Every entry is the game's **own call instruction** at one of the
16 sites, so the wrapper reads the real pushed return address, the caller's registers and the caller's
stack alignment.

| check | result |
|---|---|
| `vanilla-unchanged` | 292 vanilla/out-of-range ids × 16 sites = **4 672 runs**, patched vs unpatched: 0 differences in eax, 0 bytes written |
| `stage-first` | all 16 sites: configured family → **52**, pool `C5 01 87 00`, slot 52 zeroed |
| `stage-idempotent` | asking again for the already-staged family answers 52 and leaves all 144 bytes untouched |
| `stage-round-trip` | `10,20` written into slot 52, switch to another family packs `87 00 02 | 0a 00 00 | 14 00 00`, switching back restores exactly `10,20,0,0,0,0` (via the deref site, the writer site and a shop site) |
| `stage-completed-ranks` | `64,256,1024,7` (rank thresholds 64/256/1024/4096/…) → header `87 60 01` = k=3, n=1, one stored counter, exact round trip (completed ranks cost no space) |
| `model-format` | 60-step randomized walk: after every switch the record's 144-byte area is **byte-identical** to `d5lib.packedmapper`/`d5lib.packedmastery` (the offline specification) for the same input |
| `fail-closed` | 13 cases, each answering −1 with **0 bytes written**: unknown spare bytes, legacy six-slot counters, wrong pool version, reserved header bits, duplicate entry, garbage after the entries, entry past the end of the pool, full pool (38 completed entries + a staged family that needs 6 more), staged family not configured, counter above its threshold, counter beyond 24 bits, family without JobRank rows, null record |
| `per-unit-scope` | two units: unit B's call writes only unit B's pool and never touches unit A's staged counters |
| `register-preservation` | 13 caller registers (rbx/rbp/rsi/rdi/r12-r15, rdx, r8, r9, r11 and the record register) survive the call unchanged |
| `--abi` `abi-sites` | all 16 sites entered with caller state, the original mapper replaced by a **clobbering** stub: 48 runs, answer −1/12/52 as intended, registers preserved, 0 unexpected call edges, 0 writes on the refusal path |
| `--abi` `abi-stage-switch-bytes` | a real stage switch through the stub path produces the **same 0x4800-byte record** as the real-mapper run |
| static audit (`static_stack_packed.py`) | 2-family and 45-family sections: 16 sites → claim entry, 6 call edges, 8 returns, 0 unknown branches, 0 home-space stores, 0 exits, **0 findings**; table offset/count/version checked |

Receipts: `mastery/proof-packedmapper.json`, `mastery/proof-packedmapper-abi.json`,
`mastery/packed-static-stack.json`, `mastery/payload-verify-packed.json`.

ABI notes that the proof pins: entry RSP%16 = 8, 14 pushes (the volatile six plus every callee-saved
register it uses) → RSP%16 = 0 with 32 bytes of home space at the original-mapper call; the record
register is read **before** that call, so nothing depends on a callee's side effects; the hook makes no
game call of its own (the JobRank binary search reads the game's own `0xA03B38`/`0xA03B40`); unwind
records are emitted by `exepatch` for the four routines and the static audit proves the epilogues reverse
the prologues exactly.

## Payload build and verification (offline)

`mastery/build_payload_packed.py` runs every section-adding module's builder in finalizer order (17
features, `.d5pm` where `.d5cm` used to be) from the pinned exe; `mastery/verify_packed_payload.py`
checks this hook inside that payload:

- section `.d5mod` grew (144 of 1 024 header bytes left — no room for another header), claim found by its
  bytes at `0x148092260`; family table `[1350, 1360]`, version 1;
- the claim's 2 468-byte code is identical to the same section rebuilt at the payload's own base;
- all **16** mapper sites call the claim's entry; no other call site enters this code (byte scan of every
  section, excluding this feature's own code);
- 4 unwind entries inside the feature region, table sorted, non-overlapping, sane;
- `.d5cm` absent; every other module still recognises its own section; no section overlap; the
  `SizeOfImage` covers the last section;
- the reverse order is **refused**, not half-applied: `packedmasteryhook.build_patch(masteryext.build_patch(exe))`
  raises `packed mastery: 0x1400b3ce8 is not a call of 0x14021ebe0`.

## Kit test suite

Per-file run in this worktree (`tests/test_*.py`, `QT_QPA_PLATFORM=offscreen`, Unicorn venv
`/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python`): **464 passed, 39 failed, 1 skipped, 0
errors** over 42 files. The identical loop on this branch's own base (`557adfd`, detached worktree
`/Volumes/Data/ai-tmp/hermes/p2d-baseline`) gives **441 passed, 39 failed, 6 skipped** over 41 files. The
failing set is identical file by file and count by count (39 tests in `test_offlinepaths`,
`test_gamepacks`, `test_gamepacks_ui`, `test_d4source`, `test_d4unique`, `test_d4expansion` — the known
environment set); the new `test_packedmasteryhook.py` contributes 18 passes. The only other difference is
that 5 Unicorn-dependent checks in `test_recruit_ranks.py`/`test_recruit_runtime.py` skipped in the
baseline run and ran (and passed) on this branch — i.e. those files are flaky about their Unicorn probe,
not affected by this change.

**SIGILL note:** the Unicorn `mem_map` SIGILL that P2/P2B/P2C reported did **not** reproduce today —
`test_recruit_ranks.py` (12 passed) and `test_recruit_runtime.py` (6 passed) completed, and a standalone
`Uc(UC_ARCH_X86, UC_MODE_64).mem_map(0x140000000, 0x1000000)` succeeds in that venv (Unicorn 2.1.4,
CPython 3.13.17, arm64 macOS). The same two files skipped some Unicorn checks in the baseline run a few
minutes later with the same interpreter, so the environment is flaky rather than fixed; the earlier
observation is neither confirmed nor explained here and the SIGILL lane owns it.

## What this does not establish

- **Nothing is installed, launched, saved or played.** Native gameplay, save round-trip, menu/stars
  display and removal safety are untouched acceptance gates.
- **No award/writer change** (by scope): the native writer `0x14015F480` will write into slot 52 for a
  configured family, but the pack-back only happens on the next mapper call for a *different* family, and
  the writer-site `r10` "award from rank 0" adjustment lives in `.d5cm`, not here. Step 2 owns that plus
  the unlock path (`0x1C62A0`) and the tier flags.
- **Mutually exclusive with `.d5cm`** until the six-slot mapper is retired; installing both is refused by
  construction, and no installer wiring is added here (no `mastersy.json` handler, no `mastery_slots.json`
  decision — a packed install must not reuse the six leases).
- Structural, not full, validation of entries the hook does not itself touch: a well-formed pool entry for
  a family this build does not configure is *kept* (it is never interpreted unless the family is
  configured), while malformed structure, unknown magic, garbage, duplicates and truncation are refused.
  The offline codec validates counters against thresholds for every entry; the native scan validates
  structure for every entry and counters for the two it reads. That difference is deliberate (an
  unconfigured family must not brick the unit) and is the one place the codec and the hook do not agree.
- All-zero spare areas are initialised (`C5 01` + this family staged) on first use, exactly like the
  offline model; a non-zero area without the header is refused rather than guessed.
- The 292-id vanilla sweep covers every family the mapper's switch knows plus out-of-range ids, not every
  32-bit id.

## Next work (step 2 and after)

1. Award path: writer-site reservation before any write (projected counters, clamping, reentrancy), the
   `r10` base-first adjustment for packed staging, and the `0x1C62A0` unlock/tier integration.
2. Decide the install shape: packed mapper replaces `.d5cm`'s mapper (keeping its sub-class and screen
   hooks) or a merged wrapper; one section, one mapping source, no double claim.
3. Re-run this battery after the merge (behaviour + `--abi` + static + payload verify), then the SIGILL
   lane's Unicorn baseline, then a live playtest checklist (stars in the Class tab, six ranks, one-star
   award, save/reload, a second unit).
