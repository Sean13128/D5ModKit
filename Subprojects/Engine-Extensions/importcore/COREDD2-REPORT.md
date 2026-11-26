# COREDD2 — DD2 importer

One offline command rebuilds the 23 active installed DD2 packs (9 families and 14 uniques):

```sh
D5Modkit/.venv-macos/bin/python tools/import_game.py dd2 --compare-installed \
  --out /Volumes/Data/ai-tmp/codex/coredd2/out
```

That run built 23/23, passed all importer gates, and had 0 regressions against the installed packs. The flagged reviewed-abilities run also built 23/23 with all gates and 0 regressions. The reviewed output makes 12/23 active packs usable end to end offline (built, installed-reference-comparable, own animation, face, text, and supported signature special). Native installation and gameplay acceptance were not run.

The installed census accounts for 25 DD2 folders: the 23 active `DD2_*` packs plus parked early builds `D2_Class_22680` and `D2_Unique_941`. The two parked builds are deliberately excluded from the rebuild roster per the task scope; they are not represented as rebuilt output. Thus “25 installed/accounted for” and “23 rebuild targets” are both intentional.

## What changed

`d5lib/importers/dd2.py` is an additive importcore plugin. It wraps the existing DD2 source reader and builders, then applies the recorded installed-pack leases and fixed passes. The runner change is additive only: it registers the canonical DD2 source root and exposes `--with-reviewed-abilities` through `D5_DD2_REVIEWED_ABILITIES`.

The normal build is comparable to the installed baseline. The second, flagged build is:

```sh
D5Modkit/.venv-macos/bin/python tools/import_game.py dd2 --with-reviewed-abilities \
  --compare-installed --out /Volumes/Data/ai-tmp/codex/coredd2/final-reviewed/out --jobs 4
```

Reviewed coverage is read from `Research/source-packs/dd2/coverage.json`. Exact, adapted, and lookalike skills are put in the pack learn lists; exact and adapted evilities are emitted with the signature first. `needs-new-logic` remains omitted and labelled in the per-pack receipt. The current reviewed engine emission has zero extension rows, so no `.d5el` file is fabricated: eligible mappings use native D5 aliases, while rows needing a new evaluator remain visibly unresolved.

## Per-pack reviewed additions

Counts are distinct source IDs added to the pack across its level/rank rows. `sig` means a reviewed signature evility is supported in the offline candidate; `usable` is the resulting end-to-end special gate.

| pack / character key | skills | evilities | sig | usable |
|---|---:|---:|:---:|:---:|
| DD2_Class_22210 (`dd2-1210`) | 0 | 2 | yes | yes |
| DD2_Class_22520 (`dd2-2020`) | 5 | 1 | yes | yes |
| DD2_Class_22540 (`dd2-2040`) | 4 | 3 | yes | yes |
| DD2_Class_22550 (`dd2-2050`) | 8 | 3 | yes | yes |
| DD2_Class_22590 (`dd2-2090`) | 8 | 2 | no | no |
| DD2_Class_22620 (`dd2-2120`) | 8 | 0 | no | no |
| DD2_Class_22630 (`dd2-2130`) | 4 | 1 | no | no |
| DD2_Class_22670 (`dd2-2170`) | 4 | 3 | yes | yes |
| DD2_Class_22700 (`dd2-2200`) | 4 | 0 | no | no |
| DD2_Unique_10 (`dd2-u10`) | 8 | 1 | yes | yes |
| DD2_Unique_100 (`dd2-u100`) | 2 | 0 | no | no |
| DD2_Unique_140 (`dd2-u140`) | 1 | 0 | no | no |
| DD2_Unique_210 (`dd2-u210`) | 3 | 1 | yes | yes |
| DD2_Unique_270 (`dd2-u270`) | 5 | 1 | yes | yes |
| DD2_Unique_30 (`dd2-u30`) | 4 | 1 | yes | yes |
| DD2_Unique_320 (`dd2-u320`) | 3 | 1 | yes | yes |
| DD2_Unique_400 (`dd2-u400`) | 3 | 0 | no | no |
| DD2_Unique_420 (`dd2-u420`) | 3 | 0 | no | no |
| DD2_Unique_430 (`dd2-u430`) | 10 | 0 | no | no |
| DD2_Unique_50 (`dd2-u50`) | 10 | 1 | yes | yes |
| DD2_Unique_550 (`dd2-u550`) | 3 | 0 | no | no |
| DD2_Unique_570 (`dd2-u570`) | 3 | 0 | no | no |
| DD2_Unique_60 (`dd2-u60`) | 10 | 1 | yes | yes |
| **total distinct source IDs** | **113** | **22** | **12** | **12/23** |

The source review itself covers 386/386 skills and 227/227 evilities. The reviewed receipt records the source and review hashes, the leases, native emission choice, omissions, and unresolved IDs for every pack.

## Source pin and leases

The roster was re-pinned to the read-only canonical source:

`Disgaea Source/Disgaea D2 PS3 (BLUS31313)/.../PS3_GAME/USRDIR/Data/START_4.dat`

SHA-256: `3e84005958fe5c63351118f1f02d4ef1c481a92c2be4c23a76e571a57daa5416`. This matches the hash used by the DD2 coverage/census artifacts; the earlier D2-RE working-copy census therefore matches the canonical source bytes.

`d5lib/importers/dd2-leases.json` records voices, skills, help, quests, character/art ownership, and installed pack identity leases read from the installed packs. They are consumed as leases, not recomputed. The builder also retains the installed DD2GEN/DD2NAMED fixed-pass definitions where the existing installed pack is the authoritative reviewed baseline. DD2WHEEL6 normalization is applied to the generated animation roots, and the wheel-freeze gate reports no added palette slots or image headers versus the installed bank.

## Verification

- Baseline importer: 23/23 built, all gates, 0 regressions.
- Reviewed importer: 23/23 built, all gates, 0 regressions.
- `Tools/check_dbpatches.py Builds/COREDD2-20261103`: 95 patches applied strictly, 0 failures.
- `live_accept.py specs/COREDD2.json --dry-run`: PASS — guards, installed MAIN base (`206` mods, executable SHA-256 prefix `10e46d6c`), and 173-bank readback; no live install or boot was performed.
- Candidate: `Builds/COREDD2-20261103/`, containing only the 23 reviewed active-pack folders and `READY`.
- Tests: `pytest tests/test_coredd2.py tests/test_dd2_validation.py -q` — 10 passed.

The first dry-run invocation hit the restricted shell’s inability to execute `ps`; rerunning with a disposable no-process shim allowed the read-only guard to complete. This did not alter the installed kit or the pipeline.

## Prior art checked

- D5 Mod Kit: `d5lib/choreo.py`, `d5gui/skilledit/`, `d5gui/pages/sprites.py`, `d5gui/partpainter.py`, `d5lib/gamelink.py`, `d5lib/modsys.py`, and the importer interfaces/builders.
- Overlord: `Private/Overlord and Sorrow research/class-support/OVERLORD-COMPARISON.md` and the custom evility/class/recruiter hook implementations; no new hook site was invented here.
- Sorrow: `Private/Overlord and Sorrow research/community/sorrow/RESEARCH-INDEX.md` and the named-pointer export.
- Decomp: `/Volumes/Data/Decomp/d5` and `/Volumes/Data/Decomp/d4` for table and animation evidence.
- DD2 prior art: `d5lib/dd2source.py`, `Research/source-packs/dd2/{STATUS.md,coverage.json,COVERAGE-FULL.md,roster/,reader/}`, `tools/dd2/`, DD2GEN, DD2NAMED, DD2WHEEL6, and MODORG1. The parked early builds remain out of scope.

No game launch, install, save access, Steam write, or publication occurred.
