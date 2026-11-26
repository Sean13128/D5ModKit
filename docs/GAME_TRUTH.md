# Game truth: what the game will do with an installed pack (GAMETRUTH1, 2026-11-10)

`tools/game_truth.py` (library `d5lib/gametruth.py`) answers, per installed mod folder and per check, what the game
will do with the pack, by following the game's own code paths over the files the game reads: the installed
`Database_0.dat`, `ANM_HI_JP.dat` (banks and `anm_resident`), the Sound_Voice tables and archive, and the installed,
Kit-patched `disgaea5.exe`. It is read-only and offline (about one minute for all installed packs).

    D5Modkit/.venv-macos/bin/python tools/game_truth.py --save <COPY of Save_001.sav> [--only A,B] [--json out.json]
    D5Modkit/.venv-macos/bin/python tools/game_truth.py --regress      # the labelled set below

Every result names the decompiled function it rests on and how:

* **executed**: the function runs under Unicorn on the installed exe (the `tools/stat_oracle.py` rig: exe sections
  mapped, database tables in the exe's table globals, the save's state block at 0x144FCCB00).
* **re-implemented**: the function's rule, read in the decomp, replayed in Python on the installed data.
* **kit gate**: an existing gate is called (`importcore.*_gate`, `tools/check_installed_voices.py`).
* **linked**: proven elsewhere and not re-run (evility effects: `evility/offline_proof_*.py`).

NOT MODELLED means the path was not followed, and says where it stopped. It is never a PASS.

## Checks, in the order a player meets them

| check | rests on | how |
|---|---|---|
| recruit: board | `FUN_1407ec450` Quest Shop board builder, on the installed Quest.dat sorted by id (`db_quest_load_fixed` 0x1400C2A40) and the save's progress bytes; stops at 0x1407ECA32 before the menu calls | executed |
| recruit: reward | Quest row reward_type 5 -> this pack's char row (the reward handler itself is not traced) | re-implemented |
| recruit: class page | Kit runtime wheel table (`d5lib.wheelmeta`); the page builder is Kit runtime code, not the game's | re-implemented |
| status: portrait | `anm_id_for_variant` 0x14021F4A0 gives the graphics id; face animation 10000 + id must be in resident block 9017 (SMALLFIX1); plus `face_template_gate` for the next install | executed + rule |
| status: name/title | the row's text fields (`database_table_character_name` 0x140217EB0, `class_title_read_21090`) are real text, not a placeholder | re-implemented |
| status: innate evility | `unit_stats_evil_rebuild_list` 0x140218C90 executed on the created unit (the row -> innate-slot copy of unit_construct is replayed); each id has a named Skill.dat row; no id = page 3 blank | executed |
| status: learn list | learn ids exist in the installed magic.dat | re-implemented |
| body: graphics id | `anm_id_for_variant` on the installed exe (with the Kit's graphics-id hook) = the row's colour id | executed |
| body: idle draws | `anm_actor_select_motion` 0x1402F4BA0 + `anm_actor_build_render_root` 0x1402F5450: 1001 and 1007 draw a pixel at the game's render root (`anm.evaluate(game=True)`) | re-implemented |
| body: render root | `anm.render_root_mismatches` over every animation of banks N and N+1 | re-implemented |
| body: motions | idle 1001/1007, walk 11/17, hurt 1061/1067 resolve in the bank (+ resident block 1 for humanoids); vanilla monster banks hold all six | re-implemented |
| body: monster placeholder | `unit_set_appearance` 0x14014EA10 -> `ui_sprite_set_anm` -> `anm_find_loaded_record`: body_type 1 rows need N+2 in anm_resident (`resident_placeholder_gate` on the installed resident) | re-implemented |
| body: texture objects | `model_decode_texture` 0x14030FFF0: an image whose byte-order marker is not 1 costs 256 upload objects (pool 16,384) | re-implemented |
| actions: skill caster motions | `skill_motion_gate` (choreo.py over the game's skill scripts) | kit gate |
| actions: normal attack | weapon -> attack motion not traced | NOT MODELLED |
| voice | `sound_voice_table_lookup` 0x1400AEF60 executed for every pack line (EN+JP); the game's voice id per row = the pack's; clips byte-equal (`check_installed_voices`); silent packs have none | executed (kit gate for donor-voice packs) |
| stats: creation | `unit_init_stats` 0x140218590 + `unit_recalc` 0x14021BFB0 on the installed row | executed |
| stats: evility effects | evility runtime proofs | linked |

`--folder-mode` takes banks and row values from the folders (for pre-fix folders kept in `Local/kit-backups`) and
replays the installer for resident blocks.

## What it cannot see

Timing and freezes (it counts objects, it does not run the loader), sound output, the full battle loader (how a unit
enters battle: SURVEY2's memory class swaps drew other bodies), the status panel's own draw call, the weapon attack
motion, evility effects in battle (linked proofs), and art fidelity. Those need a small live sample.

## Acceptance (2026-11-10)

`--regress` rebuilds today's known-bad states (NIGHT1 Quest.dat, the installer before NODRAW2, the folders before
BACKVIEW1 and SMALLFIX1, the outfit step before VOICE1b) and checks them with the installed fixed state and the
REALSURVEY1 live sightings: 871 cases, 0 wrong (260 labelled by live play, 611 by offline reports and readbacks). An independent second implementation (branch gametruth1, ebf56fb) gives the same 51 FAILs over the installed set.

QBOARD2 (2026-11-10) adds 23 cases: REALSURVEY1's four "not offered" recruit quests (439, 441, 442, 443) are on the
game's board (`recruit: board` PASS), and a replay of the harness walk (`hub.quest_goto`: bursts of 5, lap check before
the overshoot check) reproduces each lap row the survey reported and reaches all 15 quests it did recruit. The board
puts the request quests (sort 501..) after the last main-list slot, so a forward walk whose 5-row burst jumps past a target in the
last rows of the main list reads the drop in sort order as a lap. That is a harness reading error, not a game rule.

## FIXUP1 (2026-11-11): unresolved prerequisites are never a PASS

VERIFIER-AUDIT1 reproduced three false PASSes; each is now closed and has a focused control in the regression set
(`tools/game_truth_regress.py controls()`, also `tests/test_gametruth.py`):

* **actions: skill caster motions**: a skill the simulator cannot resolve ("unknown") is **NOT MODELLED**; a missing
  motion stays FAIL; "fallback" (vanilla runs the same pair) stays PASS. (`importcore.skill_motion_gate` keeps letting
  "unknown" through for the importer; the verifier no longer uses it.)
* **voice**: a row whose donor/base voice id has no line in the installed table is FAIL (it was PASS unless the pack
  declared its own lines). Tables not loaded (`run(voices=False)`) is NOT MODELLED.
* **body: bank**: bank N present with N+1 resolved nowhere (pack, archive, resident) is FAIL. The clean char.dat has
  no row with N and without N+1 (loose or, for 6 body_type 2 rows, resident).

The REALSURVEY1 "action" sighting was Defend + End Turn, not a skill: it no longer labels `actions: skill caster
motions`. Kyoko and Kojiro's "evility blank" is pinned as true before the EVILFX2 install (verifier run of that install,
FAIL) and false after it (PASS). The CLI and the regression print a PENDING COVERAGE block: exit 0 permits NOT MODELLED
and says nothing about battle entry, normal attacks, skill/evility effects in battle, audible sound or timing.
