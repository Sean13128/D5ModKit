# MAGICHANGE — the 14 D4 Magichange attacks, on D5's own Magichange mode (offline, 2026-10-30)

Lane **MAGICHANGE**. Worktree `Local/Worktrees/magichange` (branch `magichange`, from `integ17` `e4f22a1`),
bundle **`Builds/MAGICHANGE-20261030/`** on `Builds/LIVE5_TEST17-20261030`. Offline only: nothing was
installed, launched, saved or played; the game folder, the installed kit, the profiles and both saves were
read, never written.

---

## 1. Plain summary

**The mode the held specials were waiting for already exists in D5. The blocker was never a mode; it was
one line of data the D4 importer drops: the character's Magichange attack set was not copied.**

- **D5 ships Magichange.** A monster Magichanges when its `char.dat` row carries a weapon
  (`magichange_weapon`) and a weapon type; its attacks are ordinary `magic.dat` rows in `skill_group 10`
  that the character learns. 26 character/class families in vanilla own such a set, and **D5's own Desco
  owns exactly D4's two Magichange attacks, by name** (`Evil Sword Balmung`, `Martial Transformer`).
- **D4 stores the Magichange attacks in the same learnset as everything else**, in a separate id band, with
  the same `Magichange:%s` description prefix D5 uses. The importer copies the normal uniques and drops that
  band — so **seven imported monsters can already Magichange but have no attack to fire**.
- **No hook is needed, so none was written.** Nothing in the exe changes: the payload built from this
  worktree is byte-identical to the payload built from `integ17` (`1424acee…`, 11,829,760 B).
- **What shipped:** 16 new `magic.dat` rows and seven learnsets. **Desco gets D5's own rows** (reuse, zero new
  rows); Kurtis, God's Part, Pink, Gig, Hugo and Des X get sets cloned from **their own D5 body family**
  (Imp / Shroom / Succubus / Desco), so the animation, area, height, effects and element are the body's, with
  D4's name and text in all five locales. That carries **14 D4 attacks**: the eight SPECIALS held (Desco 2,
  Kurtis 2, God's Part 2, Pink 2), **Gig's two placeholders**, and **the four D4UNIQ3 held (Hugo 2, Des X 2)**.
- **One thing is still unproven**: the grant step at the moment of transformation (which function copies a
  character's group-10 rows onto the weapon-form unit). `LIVE-CHECK.md` is one Magichange in one battle, with
  Desco as the A/B (her rows keep `user1 610`, the new sets carry the imported identity).

---

## 2. What D4's Magichange is, as measured

Measured from the user's own D4 install with `d5lib.d4source` (read-only), not from memory:

| fact | value | source |
|---|---|---|
| who can Magichange | `char.dat` `body_type` 1 (monster) **and** the Magichange field at **0x1B8** non-zero; Desco 244, Kurtis 544, God's Part 642, Pink 143, Gig 245, Hugo 444, Des X 246 (row 430); Kuro 0 (cannot) | D4 char.dat |
| the weapon form | the field is the D4 **item id** the monster becomes; D5's char row carries the same idea at 0xF4 (244) as an `item.dat` id | D4 0x1B8 / D5 schema `magichange_weapon` |
| the attacks granted | **two rows in the same 16-slot learnset**, in the 2xxxx band, with levels: Desco `20051` Lv30 `Evil Sword Balmung`, `20052` Lv70 `Martial Transformer`; Kurtis `20191/20192`; God's Part `22041/22042`; Pink `22201/22202`; Gig `20341/20342`; Hugo `22121/22122`; Des X `20431/20432` | D4 char.dat learnset |
| how they read | `desc_EN` = `"Magichange:%s..."` — the identical prefix D5 uses for its own set | D4 magic.dat |
| duration, weapon-form stat derivation, whether the holder counts as a weapon for aptitude | **not established** in this lane | see §7 |

So D4's "special granted by Magichange" is not a special mechanic at all: it is two skill rows the monster
learns, which only become visible once it is a weapon.

## 3. What D5 already does — the nearest native mechanism

D5's Magichange is **data-driven and complete**, which is why this lane is an attach rather than a build:

| piece | evidence |
|---|---|
| `char.dat` `magichange_weapon` at **244** + `magichange_type` at **899**, `body_type` at **902** | `d5lib/schemas/char.json` (fields with `confidence: high`); 251 vanilla char rows carry a weapon |
| `magic.dat` `skill_group` at **1102** = **10** is the Magichange list | `d5lib/schemas/magic.json` (its own comment: "10 Magichange"); 68 vanilla rows carry it, in 26 families |
| a set is single / 64-SP pair / dual, linked by `dual_skill` (1136) → the dual row, and `base_skill` ← back | measured on Imp `22021`(8 SP, motion 9, icon 8, dual→22023)/`22022`(64 SP, motion 8)/`22023`(8 SP, motion 10, icon 10, base→22021); Shroom ships only `22101/22102` |
| the battle skill list comes from the unit's **own skill slots** and accepts groups **8–10** | `list_skills` `0x1402d0820`: walks `unit+0xcc4` slots and accepts rows whose runtime group byte `row+0x3F7` falls in the **8..10** window (the runtime row's layout, not the file's 1102) |
| the learnset is what feeds those slots | `unit_stats_skills_refresh` `0x1401d4f30`: the general maintenance (learnset → `unit_stats_skills_grant`) |
| **D5's own Desco already has D4's two attacks** | char 610 → `20611` `Evil Sword Balmung` Lv30, `20612` `Martial Transformer` Lv70, dual `20613` — the same two names as D4's `20051/20052` |
| row order is not a gate for `magic.dat` | `d5lib/ordercheck.py`: "a table is only listed when vanilla itself ships it in id order" — `ORDER_CRITICAL` is `Skill.dat` only, and vanilla `magic.dat` has inversions (measured: `9005` before `1001`, `1906` before `911`) |

## 4. The minimal hook set: **none** — and why that is the right answer

The mode, the transform, the weapon, the attack list and the dual-magichange pairing all exist. What was
missing is content, and content is two database tables. So:

- **no new section, no new call site, no `jmp`/`call` patch, no unwind change** — the ABI review rules in
  `abi-review/REPORT.md` do not apply because there is nothing to patch;
- a character whose `char.dat` row already carries `magichange_weapon`/`magichange_type` (every one of these
  seven does, inherited from its D5 body template) only needs the set in its learnset;
- the one place a hook *could* have been needed — the grant path — is not needed if the data contract holds,
  and the live check proves it either way.

The alternative design (a runtime that synthesises a Magichange set at transform time) was rejected: it would
have to re-implement `list_skills`'s slot contract and would break on the first patch to the mode.

## 5. What was built

`d5lib/magichange.py` (the contract: `sets`, `set_of`, `trio`, `shape`, `insert_index`, `plan`, `attach`,
`check`), `tools/magichange_rows.py` (the only writer, from `magichange/magichange-content.json`),
`tools/magichange_bundle.py` (the receipts), `tests/test_magichange.py` (18 tests),
`magichange/offline_proof_magichange.py` (the proof).

| mod | character | rows | how |
|---|---|---|---|
| `D4_Unique_50` | Desco 10350 | learns **20611**@30, **20612**@70 | **reuse** — D5's own rows, zero new content |
| `D4_Unique_190` | Prinny Kurtis 10230 | **20234/20235/20236** | cloned from Imp 22021-22023; Twin Rocket Punch / Sonic Fire / Twin Twin Rocket Punch |
| `D4_Unique_230` | God's Part 10280 | **20285/20286** | cloned from Shroom 22101/22102 (two-row family); Eryngi Raid / Erynger Panic |
| `D4_Unique_300` | Pink 10380 | **20385/20386/20387** | Imp; Death Paws / Deadly Moon Blow / Twin Death Paws |
| `D4_Unique_340` | Gig 10410 | **20414/20415/20416** | Imp; Demon Force / Demon Blast / Twin Demon Force |
| `D4_Unique_420` | Hugo 18130 | **28135/28136** | Succubus 22141/22142; Nightmare Sheep / Drop Out |
| `D4_Unique_430` | Des X 18140 | **28144/28145/28146** | D5's Desco trio 20611; Evil Sword Z / Sword Musouzan Z / Twin Evil Sword Z |

Rules, each enforced in code: the id is `10000 + the registry identity + n` (the manifest's `special_id`
band, the first free n above the character's own rows); the **shape mirrors the body family** (a two-row
family never grows a Dual Magichange); `user1` is the imported identity; D4's level is the learn level; and
the description carries exactly one `%s` (the Skill-Shop drawer's crash class).

## 6. Proofs — measured, this sitting

| gate | result |
|---|---|
| `magichange/offline_proof_magichange.py` (through the Kit's own `dbpatch.apply_patch`, then encode → re-read from bytes → re-derive) | **106/106 pass**; baseline asserted as the vanilla table by sha256 `e646eaae…` (two independent copies agree), 583 magic / 806 char rows |
| the baseline is vanilla, not the game folder | the game folder's table is the **installed** state (740 magic / 1411 char rows) — using it would have made every id check meaningless; caught and corrected mid-lane |
| Kit suite `python -m pytest tests -q` | **39 failed / 1025 passed / 4 skipped** vs the `integ17` base **39 / 1007 / 4** — same FAILED set, +18 are this lane's tests; **diff-clean** |
| `tools/check_ownership.py --installed … --vanilla-database …` | bundle **4 errors / 6 findings**, byte-identical to TEST17 (pre-existing ArmorKnight-pilot / DRPG duplicates); **our seven mods alone: 0 errors, 0 findings** |
| `tools/check_pack_tables.py --mods` | **33 findings, identical to TEST17**, none in our mods (all 33 are `Overlord Rebalance`'s two-`%d` rows) |
| `tools/check_ui_strings.py --mods` | **0 warnings** |
| payload `integration/build_payload-158.py` + `verify_payload-158.py` (D5_KIT = this worktree) | **`problem_count 0`**, `payload_sha256 1424acee…`, 11,829,760 B — **byte-identical to the same build from `integ17`**, i.e. this lane adds no code |
| static stack audit | **not applicable and unchanged**: there is no new site and no new section, so the assembled section is the base's, whose audit records **0 findings** (`evility/*static-stack.json`: `findings: 0`). The CALL-proof rules exist for hooks; this lane has none |
| bundle receipts | 171 folders, 6,475 files, 1,926,254,034 B; `VERIFY.json` **0 problems**; `Skill.dat` census **1041 rows, unchanged from TEST17** (asserted by comparing every `Skill.dat.json`); `magic.dat` +188 rows in enabled mods, this lane's 16 ids listed, **no duplicate ids** |

## 7. Risks, and what is not proven

1. **The grant step is not traced.** `unit_stats_skills_refresh` maintains skill slots; *which* function moves
   a character's group-10 rows onto the weapon-form unit at the moment of transformation was not identified.
   If it filters by `user1 == the transformed character`, Desco's reuse (rows owned by vanilla Desco 610)
   behaves differently from the six new sets (owned by the imported identity). Live check step 3–4 splits it;
   the fallback fix is to set `user1` to the body template family instead.
2. **The weapon form is the template's, not D4's.** `magichange_weapon` is inherited from the D5 body
   template (551 gun for the Imp-bodied ones, 452 bow for God's Part), so the weapon the ally holds is not the
   D4 weapon. This is the importer's existing, documented adaptation, not this lane's — but it is why the
   attacks had to be cloned from the template family rather than from D4.
3. **Numbers are D5's.** Power, SP, area, height, effects and element come from the donor row; only the name
   and the text are D4's. "Exact" is used only for Desco, whose rows are literally the same attacks.
4. **D4's Magichange duration, weapon-form stat derivation and the aptitude interaction (Gig 851 *Jet Black
   Sword*) are not established** and were not touched. The evility runtime has **no "is Magichanged"
   condition** (`d5lib/evility.py` has no such predicate), so 851 is *not* unlocked by this lane — the
   evility side of the Magichange family stays where CARRIERS2 left it.
5. **Confine and summoning are not Magichange.** CARRIERS2's "6 characters" lumped Ash's Confine (a different
   mode: it puts a unit on the map), Nemo's Malice summoning (another), and Gig's 851. This lane addresses
   Magichange only; the other two remain evidenced blockers under their own names.
6. **Pringer X (D4 210, `20211/20212`) was skipped**: D4 stores no names for those two rows, so there is
   nothing faithful to carry; the character keeps its template's own set.
7. **No battle was played** — that is `LIVE-CHECK.md`.

## 8. Prior art checked

1. **Overlord (Cryswar, The Unlicense)** — `class-support/OVERLORD-COMPARISON.md` and
   `overlord-source/`: it ships **no Magichange runtime**; its monster support is class rows and evilities.
   Its `d5_database_overlay.c` mentions Magichange only in class text. Nothing to reuse, and no design to
   copy — which is itself the answer: the mode is the game's.
2. **Sorrow** — `community/sorrow/RESEARCH-INDEX.md`, `ida-export-20261014/disgaea5_names.json` (the names
   used here: `list_skills`, `unit_stats_skills_refresh`, `unit_stats_skills_magic_row`,
   `unit_stats_skills_grant`), `states/s5battle.md` (the Magichange key-help on the ability/skill page) and
   `FORGE-ENGINE-RESEARCH-NOTES.md` §class.magichange_form (`char.dat:0xf4 default_item_id`, "VERIFIED").
   Sorrow's own notes list the Magichange form as *not established*; this lane establishes the data half.
3. **Decomp** — `/Volumes/Data/Decomp/d5`: `1402d0820_list_skills.c`, `1401d4f30_unit_stats_skills_refresh.c`,
   `140061ff0_unit_stats_skills_magic_row.c`. `/Volumes/Data/Decomp/d4`: no `magichange` symbol, so the D4
   side is read from the table itself (`d5lib/d4source.py`, D4 char.dat 0x1B8 + learnset 0x014).
4. **This repo** — `SPECIALS-REPORT.md` §"Eight specials are held on purpose" and its carrier list item 15;
   `CARRIERS2-REPORT.md` §5.1 (the evidenced blocker this lane closes); `D4UNIQ3-REPORT.md` ("the four
   Magichange attacks are held"); `D4UNIQ2-REPORT.md`; `DD2GEN-REPORT.md` (no DD2 character has a Magichange
   row — Etna/Barbara are humanoid, so DD2 contributes nothing here); `d5lib/schemas/magic.json` +
   `char.json` (the field contract and its confidence levels); `d5lib/ordercheck.py` (why `magic.dat` order is
   not a gate).

## 9. Files, commits, next steps

**Worktree `Local/Worktrees/magichange` (never pushed):** `d5lib/magichange.py`,
`tools/magichange_rows.py`, `tools/magichange_bundle.py`, `tests/test_magichange.py`,
`magichange/magichange-content.json`, `magichange/rows.json`, `magichange/offline_proof_magichange.py`,
`magichange/offline_proof_magichange.json`, this report.

**Bundle `Builds/MAGICHANGE-20261030/`:** 20 changed files in `D4_Unique_50/190/230/300/340/420/430`,
`INVENTORY.json`, `LEASES.json`, `VERIFY.json`, `INSTALL.md`, `LIVE-CHECK.md`, and TEST17's own docs kept as
`INSTALL-TEST17.md` / `LIVE-CHECK-TEST17.md`.

**Next steps, in order:** (1) the live check; (2) if step 3 fails for the six new sets but works for Desco,
switch `user1` to the body template family; (3) the importer fix proper — `d4unique`/`d4expansion` should map
a D4 2xxxx Magichange row the way this lane does, so a future import does not repeat the gap; (4) the two
remaining modes (Confine, summoning) are their own cards.
