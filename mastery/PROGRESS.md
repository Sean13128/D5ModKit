# P2e progress — packed mastery, native step 2 (award / writer / unlock)

Status: done (offline). No game, no install, no save, no push.

- 2026-10-27 step 2 code
  - `d5lib/packedmasteryhook.py`: the writer's own mapper call now hands the writer the family
    base in r10 (X_AWARD flag + R10_SAVE), so its rank loop awards one star at a time
    (STARS-FIX); no other site's r10 is touched.  `.d5pm` also carries `.d5cm`'s sub-class gate,
    screen fetch and screen bound, so it replaces the six-slot extension completely;
    `mode_for()` states the split (<= 6 families -> .d5cm, more -> .d5pm); both builders refuse
    the other by name.
  - `d5lib/exepatch.py`: `.d5pm` unwind rules gain allow_exits + allowed_writes=("r15",).
  - `d5lib/masteryext.py`: `.d5cm` refuses an exe that already carries `.d5pm`, by name.
  - `tests/test_packedmasteryhook.py`: 24 tests (award flag at exactly one site, mode_for, the
    sub-class sites + bound, both refusals, layout stability).
- 2026-10-27 proofs
  - `mastery/proof_packedaward.py` (new, real writer + real builder): 9/9 behaviour, 11/11 with
    `--abi`.  1/7/45 families one unit, two units, six ranks, completion + bonuses, full pool
    and refused switch both byte-identical no-ops, pack-back/restore, reader on saved bytes,
    `0x1C62A0` no-op for custom ids (write trace) with the vanilla flag write unchanged.
  - `mastery/proof_packedmapper.py`: 9/9 and 11/11 (the writer site's one intentional r10 change
    is asserted as the 64-bit value it really leaves).
  - `mastery/static_stack_packed.py`: 18 sites (16 mapper + gate + fetch) + bound, 0 findings at
    2 and 45 families.
  - payload: 17 features, `2ea7e050…`, 18 sites -> claim, 6 unwind entries, no foreign entry,
    `.d5cm` absent, reverse order refused.
  - suite: 470 passed / 39 failed / 1 skipped vs base `557adfd` 441/39/6, FAILED set identical.
- 2026-10-27 report: `mastery/P2E-REPORT.md` (includes the unlock trace, the install-shape
  decision, what is not proven, and the live checklist).
