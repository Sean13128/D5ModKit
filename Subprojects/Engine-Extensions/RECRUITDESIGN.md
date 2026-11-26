# RECRUITDESIGN — recruiting hundreds of characters without hundreds of quests, and a character bank

Lane: Hermes (deepseek-v4.1-flash), 2026-10-30, **OFFLINE ONLY**. Worktree
`Local/Worktrees/recruitdesign` (branch `work/recruitdesign-20261030`, from `integ18b` @ `9268eec`).
Nothing was installed, launched, pushed or merged. The game folder, `Local/Installed D5ModKit`, the
profiles and every real save were **not** written; the one save used was a **copy** under
`/Volumes/Data/ai-tmp/hermes/recruitdesign-20261030/saves/`. Evidence class throughout is **offline**:
the pinned exe's decomp, the Kit's own save parser, and the game's own create path read out of the
decomp. No claim here is native gameplay acceptance.

Deliverable: this report, plus the smallest proven piece — `d5lib/unitbank.py` (export / import one
unit), 20 offline tests (`tests/test_unitbank.py`) and `tools/prove_unitbank.py`, run on copies of Save1.

---

## 0. For Sean — the short version

1. **The save holds 128 characters. Not 128 at a time by choice — 128 total.** The game's own
   "make a unit" routine (`roster_create_unit` 0x1402ea3e0) refuses when army + reserve reach 128, and
   every recruit path in D5 goes through it. Your Save1 has 58 army + 1 reserve, so **69 slots are
   free**. The content plan is **1,190 characters** in scope. The two numbers do not fit, and no
   recruiting UI changes that.
2. So a **character bank is not a convenience, it is the only way this works**: the save is the play
   set, the bank is the shelf. I built and proved that piece today — one unit out of a copy of Save1,
   into a second copy, both still parse, nothing else in the save moved.
3. **Quests are the wrong shape for this.** You already have 76 character mods each carrying its own
   recruit quest (41 D1C, 32 D4, 3 DD2). At 300 characters that is 300 Quest.dat rows (1.7 MB in the
   database), ~460 free progress slots spent, and 300 entries in the Quest Shop that the player has to
   accept and clear one by one. The cost per character is the thing to attack, not the quest text.
4. **What I would do:** keep the bank as the shelf; then recruit *in the Recruiter* from the list of
   installed characters (the mechanism that already puts D4 generic classes in the Recruiter today),
   and make any quests that remain **bulk** — one quest that hands over a whole pack — instead of one
   per character. Details and effort in §2, first steps in §5.

---

## 1. Prior art checked (AGENTS.md)

1. **Overlord (Cryswar, The Unlicense, credit given)** —
   `Private/Overlord and Sorrow research/class-support/overlord-source/`.
   * **His recruit path is a direct call, not a quest**: `overlord/03_subclass_wishes.c:1157-1180`
     (`resolve_post_vote_wish`) maps a Dark Assembly *wish* of kind `WISH_KIND_RECRUIT` to
     `RECRUIT_CHARACTER_RVA` (`01_declarations.c:457` = RVA 0x2EA3E0) with `(character, 0, level)`, i.e.
     the game's own `roster_create_unit`. A wish is one ini entry; there is no quest row and no board
     entry. This is the design to copy for "recruit from a list".
   * His **Recruiter work** replaces the shared class-grid builder on a configurable custom page
     (`d5_custom_classes.c:463`) and patches the personality page because it needs three rows
     (`classcheck.py` R1 cites exactly that). `OVERLORD-COMPARISON.md:20` records that **paid custom
     recruitment was not accepted** in his own testing — a cost/rank assumption the Recruiter makes.
   * **He has no save path at all**: `EVCAP4-REPORT.md` §"Prior art" greps every `.c`/`.h` for
     `save`/`fopen`/`fwrite`/`0x14074` — nothing. So the **bank has no prior art in Overlord**; we are
     first, and there is nothing of his to reuse or collide with.
2. **Sorrow's research** (`community/sorrow/`, `ida-export-20261014/disgaea5_names.json`) — the names
   that made this tractable: `roster_create_unit` 0x1402ea3e0, `unit_construct` 0x14021b510,
   `data_unit_construct_empty` 0x140063d40, `script_cmd_unit_recruit` 0x140189cc0,
   `s38_applies_one_delivery` 0x1407c19f0, `state_enter_recruiter` 0x140652060. Annotations only;
   every byte claim below comes from the decomp or the Kit's parser.
3. **Full decomp** `/Volumes/Data/Decomp/d5/functions/` — `1402ea3e0_roster_create_unit.c`,
   `14021b510_unit_construct.c`, `140063d40_data_unit_construct_empty.c`,
   `1407c19f0_s38_applies_one_delivery.c`, `140189cc0/140189f70_script_cmd_unit_recruit*`.
4. **This Kit** — `d5lib/savegame.py` (roster, dismiss, `fix_rows`, quest bytes), `d5lib/questpatch.py`
   (the recruit-reward hook 0x1407F1E2A, `CREATE_UNIT` 0x1402EA890, `TO_RESERVE` 0x1402EA4B0),
   `d5lib/learned.py` + `d5learn.inc.*` (the bitmap and the save-bound companion), `d5lib/newclasses.py`
   (the `.d5cl` class-unlock hooks and flags 17283+), `d5lib/dbpatch.check_quest_slots`, `d5lib/classcheck.py`
   (R1/R2/R4/R5), `d5lib/overlord_import.py` (id re-addressing), `d5gui/savecleanup.py` (the page shape
   a bank page would copy).
5. **Prior lanes** — QUESTDRV (`live-verify/QUESTDRV-REPORT.md`: board, ten accepted slots, reward
   read-back), OLCOMPAT2 §3 (save import: bitmap remap, row recompute, mastery untouched), EVCAP3/4
   (the learned store and the companion's sha256 binding), D4UNIQ2/3, D1C2, DD2NAMED (how today's
   recruits are delivered: one mod, one char row, one quest).

---

## 2. Recruiting at scale — the options

### The two facts that bound every option

* **128 roster slots, hard.** `roster_create_unit` 0x1402ea3e0 starts with
  `if (DAT_145574a9e + DAT_145574a9c < 0x80)` — reserve + army. Both are the save's own s16 counts
  (`savegame.ARMY_COUNT` 0x5A7F9C, `RESERVE_COUNT` 0x5A7F9E). The same guard appears in
  `script_cmd_unit_recruit_full` (`iVar7 = 0x80 - DAT_145574a9e`). Save1: 58 + 1 = 59 → **69 free**.
* **One mod = one char.dat row = one unit**, and a *unique* row is not a generic class: the Recruiter's
  rank page and the personality page assume a family (`classcheck.py` R1, R2). That is why today every
  unique character ships with a quest.

### Option A — a "recruit from a list" page in the Recruiter *(direct create, no quest)*

| | |
|---|---|
| reuses | `roster_create_unit` 0x1402ea3e0 (Overlord's `RECRUIT_CHARACTER_RVA`, same call); the Recruiter's list builder 0x14013CCF0 and class→flag table 0x140A484C0; the Kit's `.d5cl` hooks `0x14008d3f0` / `0x1401c5920` that `newclasses.py` already uses to put imported classes in the list; flag leases 17283+ |
| new work | a list of *installed characters* (not classes) and a create call on confirm; for unique rows, the rank/personality handling Overlord's custom page does |
| effort | **2–4 agent-sessions** for generics (mostly wiring), **+3–5** for uniques (the Recruiter's assumptions are the work) |
| risks | the Recruiter's confirm assumes ranks and costs (`classcheck` R1/R2; Overlord's "paid recruit not accepted"); a unit created this way is level 1 unless we also set the level; every character must stay reachable after the save is reloaded with a *different* mod set |
| player sees | the normal Recruiter list, all imported characters in it, one confirm each. No quest, no board clutter |

### Option B — one quest per **pack**, not per character *(bulk quest)*

| | |
|---|---|
| reuses | the existing recruit-reward hook `d5lib/questpatch.py` at 0x1407F1E2A, `CREATE_UNIT` 0x1402EA890, `TO_RESERVE` 0x1402EA4B0, Quest.dat reward_type 5 |
| change | the hook's id list is already **built from the Quest table** (`questpatch.recruit_classes` = every quest's `reward_value`), so this is a data change in the same `.d5qr` section, not a new hook: per quest, a list of classes to create instead of the one |
| effort | **1 session** (the hook exists and is live-proven as a mechanism) |
| risks | 300 units cannot enter a 128-slot roster: the surplus must go **into the bank**, i.e. this option depends on the bank (or the quest must refuse loudly); the player gets no choice of *which* characters |
| player sees | 3–6 quests per source game ("Recruit the D4 cast"), each handing over the pack's characters |

### Option C — unlock-by-progress *(characters arrive with the story)*

| | |
|---|---|
| reuses | the same create call, triggered from a story flag / stage clear; `savegame.flag` / `STORY_FLAGS` |
| effort | **2–3 sessions** (needs a hook site tied to progress, plus a rule for what "enough progress" means) |
| risks | no player choice; silent roster overflow; interacts with the base-walker and the "recruited" bit (`DAT_1458456dc`, outside the save — see §4.3) |
| player sees | nothing new — characters simply appear over time |

### Option D — a Dark Assembly bill per character / per pack

| | |
|---|---|
| reuses | `progress_bill_notices` 0x1402b8eb0, the assembly session, `unitstats_dark_assembly` 0x1401bb250; Overlord already runs a wish→recruit hook (`03_subclass_wishes.c:1157`) |
| effort | **3–5 sessions** (bill table + availability + vote session + the recruit call) |
| risks | one bill per character is the same "hundreds of entries" problem in a different menu; the assembly is a whole screen session (slow to use 100 times); Overlord's version is ini-driven, ours would be mod-data-driven |
| player sees | a senate vote per character — flavourful, wrong shape at scale |

### Option E — the game's own delivery list (`DLC_DeliveryDataBase`)

| | |
|---|---|
| reuses | `s38_applies_one_delivery` 0x1407c19f0 (a **hardcoded** `roster_create_unit(0x226)` / `0x276` / `0x2b2` / `0x35c` / … per delivery type, plus mana, two starter items, a dex note and the "X became an ally!!!" text), `s38_availability_test_per_delivery_flag` 0x1407bfee0, `DLC_DeliveryDataBase` 45 rows × 120 B |
| new work | a hook that takes the class id from the **row** (`value`) instead of the constant, and one row per character |
| effort | **2–3 sessions** |
| risks | the class ids are immediates in the code, so this is an exe hook, not a data row; the delivered state is flag plumbing we do not own; it is a *global* menu, not per save |
| player sees | the game's own "extra content" delivery screen; the character arrives with a message. The most native-looking option |

### Option F — the Kit's own character bank *(offline)*

| | |
|---|---|
| reuses | `d5lib/savegame.py` (the parser and the dismiss path), and the new `d5lib/unitbank.py` (proved below); a page modelled on `d5gui/savecleanup.py` |
| effort | **proved** for export/import; a usable page is **1–2 sessions** (list characters from the installed packs, pick, apply, back up the save first) |
| risks | the game must be **closed** (it rewrites the save on exit); the save must have the class's row (its mod installed) or the character shows as a Dummy; a kit-written save has never been *loaded by the game* (see §4.4) |
| player sees | a list in the Kit; the characters are in the army/reserve at the next launch. Works with **any** acquisition route, and it is the only option that can hold more than 128 |

### What the options cost in the save, measured

* Quest.dat rows: **5,636 B each** (`d5lib/schemas/Quest.json`, and Sorrow's `db_quest_load_fixed`
  "stride 5636"). 76 character mods already carry 76 quest rows (~428 KB); 300 would be ~1.7 MB added
  to the member, plus one hidden placeholder row for every shop quest above the current row count
  (`dbpatch.check_quest_slots`) because the board only scans slots `0 .. rows-1`.
* Progress slots: 1,024 bytes per state (`savegame.QUEST_*`). Vanilla uses ~518; our character packs
  already lease 555–560. That leaves ~460 — a ceiling on per-character quests independent of the UI.
* The board itself: three bytes per slot per save and a list the player has to walk. This is the
  complaint, quantified.

---

## 3. The character bank — how a unit moves between saves

### 3.1 What a unit *is*

A unit is its roster record, 0x4750 bytes, and **everything it carries is inside it**:

| offset | what |
|---|---|
| +0x010 .. +0xBC8 | its five equipped items, **0x258 bytes each** (`0x10 + 5*0x258 = 0xBC8` = the name field; `data_unit_construct_empty` zeroes exactly these five blocks and writes each one's "empty" marker; `s38_applies_one_delivery` builds starter items at `unit+0x10` and `unit+0x4c0`, i.e. items 0 and 2) |
| +0xBC8 / +0xBFC | name / title |
| +0x2DFC / +0x2E04 / +0x2E0A | level / class id (char.dat key) / char.dat **row** |
| +0x2DA8 | the ten weapon-mastery counters (experience, level, aptitude, bonus) |
| +0x2E70 (125 B) | the learned-evility bitmap: one bit per Skill.dat row position, 0..999 (`d5lib.learned`) |
| +0x2F30 / +0x3030 | the *built* active-evility list and its count — recomputed, not state to copy |
| +0x3058 / +0x30A0 | squad (-1 = none) / group (0xFF = none) |
| +0x3060 | the u64 **serial** — every table outside the record names the unit by it |
| +0x30A4 | the class-mastery counters (47 native slots; Overlord's packed pool uses 47–52) |

So there is no assembly from parts: **export = the record, import = the record plus the few ids that
mean something outside it.** Nothing about the source save is needed to read a unit back, and nothing
about the target save is needed to store it.

### 3.2 The ids that must be re-addressed on import

| id | why | what the import does |
|---|---|---|
| **serial** (+0x3060) | serials are 1.. and collide across saves (Save1: highest in use 6,607, next id 12,033 — the same number names a different unit in every save). Squads (10 serials), groups (20), the base walker, its 5 followers and three 128-entry serial lists are all keyed by it | takes a **fresh** serial from the save's own counter at `state+0x5A7F60` (the exe's `DAT_145574a60`, the dword `roster_create_unit` increments) and leaves the counter above it |
| **roster index** (+0x2E31) | the record's own slot number; the game writes it at create and renumbers every slot at dismiss | set to the import slot, and every slot renumbered `0..127` as the game's save always is |
| **char.dat row** (+0x2E0A) | the index of the class id's row; wrong if the target's char.dat is a different table | recomputed from the class id (`savegame.fix_rows` does the same), with a warning if the class is absent |
| **squad / group** | the membership lives *outside* the record and names the old serial, so it cannot travel | cleared to -1 / 0xFF, with a warning — exactly what the game's Dismiss does to a unit it removes |

Everything else — items, weapon mastery, class mastery, the learned bitmap, name, title, level — is
copied **byte for byte**. That is why the bank is safe where a field-by-field rebuild would not be.

### 3.3 What can go wrong

1. **Serial collision** — the one that would corrupt a save silently. Covered by taking the save's own
   next id, and by `unitbank.verify()` (duplicate serials, wrong indices, a counter left behind).
2. **Roster overflow** — army + reserve must stay < 128. The import refuses; the caller decides whether
   to bank something first.
3. **Writing where a unit already is** — only the end of the army (`slot == army_count`) is
   overwritten, because that is the slot the game's own create overwrites (the area between army and
   reserve can hold *stale copies* the game leaves behind). Any other occupied slot is refused.
4. **The learned-evility companion** (`<save>.d5learn.json`) is **bound to the save's sha256** and keyed
   by serial (`learned.sidecar_doc` / `sidecar_validate`). Any bank write invalidates it, and the naive
   outcome is silent loss of extension-only learning. The module hands the extra ids back keyed by the
   **new** serial (`import_unit(...)["learned_extra"]`); the caller must re-emit the companion after the
   write. **Not done in this lane** — it is the one integration item the bank still needs.
5. **A class the target save's char.dat does not have** — the unit is still importable and the row is
   only a cache (`d5rows.inc.c` re-points it at run time), but without the mod installed the character
   shows as a DLC Dummy. Reported as a warning, never silently.
6. **Duplicates** — importing the same character twice is allowed and produces two units (proved: two
   Killias, both readable). Whether D5 tolerates it in play (story flags, the in-exe "has joined" bit)
   is a live question, not an offline one.
7. **The "recruited" bit is not in the save.** `s38_applies_one_delivery` sets
   `DAT_1458456dc[row]` (the vanilla per-character "has joined" table). That address is *outside* the
   9 MB state block (`0x1458456dc - 0x144FCCB00` ≫ `0x89B8C8`), so a banked unit cannot set it offline.
   Whether the game re-derives it at load, and whether its absence matters, is unmeasured.
8. **Derived stats.** A copied record is a record the *game itself wrote*, so level/class-derived
   values in it are consistent with its own level and class. We change neither, which is why a
   verbatim copy is safe where "set the level" would not be. Not proven in game.

### 3.4 How a player would use it

* **A Kit page** (the recommended shape): a "Characters" page next to "Check saves" — list the
  characters in the save and the ones in the bank, `Export` / `Import` / `Import all that fit`, back the
  save up first (`savegame.backup`), refuse while the game is running (`workspace.game_running` is
  already used by the save-cleanup page).
* **A command** for agents and scripting: `tools/prove_unitbank.py` is already that command
  (`<save A> <save B> <workdir> [name]`), and a `bank list|add|take` CLI over `d5lib/unitbank.py` is a
  thin wrapper.

---

## 4. The offline proof (what actually ran)

Copies only, under `/Volumes/Data/ai-tmp/hermes/recruitdesign-20261030/saves/`. The source is the
`20261030-live16` backup of Save1 (sha256 `285fc3e1…`, the same file `Reports/SAVE-1-IMPORTED.json`
records as the imported post-game save, army 58 / reserve 1). **No real save was opened for writing;
Save_002 was never touched.**

```
$ Local/python-macos/bin/python tools/prove_unitbank.py .../A.sav .../B.sav <work> Killia
A: army 58, reserve 1, next serial 12033
export: slot 0 'Killia' class 10 Lv9999 serial 1
import: B slot 58, serial 12033, warnings ['squad / group membership is dropped: it names the unit by its old serial']
B now: 'Killia' class 10 Lv9999 serial 12033 (army 59); verify 0 problem(s)
ok: true
  differing runs in the state: 627  — 625 inside the imported record, 2 = ARMY_COUNT + the serial counter
  runs outside the record and the counters: []      other units changed: []
  record bytes differing outside the re-addressed ids: []      five items identical: true
  counter 12033 -> 12034
  A sha256 unchanged (285fc3e1…)
```

Both files were re-read with `d5lib.savegame.Save` (the Kit's parser, which re-checks the header magic,
the body magic, the state size and — on write — that the bytes read back identical). `unitbank.verify`
reported no problem on either.

A second scenario, same copies, **two units** (one army, one **reserve**: Goldion, slot 127):

```
bank units: Killia(10, Lv9999, serial 1), Goldion(120, Lv1500, serial 10)
 -> slot 58 serial 12033
 -> slot 59 serial 12034
army 60, reserve 1, verify []
tail: Killia, Goldion     two copies of Killia: 2 (a duplicate is allowed, not blocked)
```

Tests: `tests/test_unitbank.py` — **20 pass**, covering export/import round trip, the serial collision
(the two synthetic saves both hold serial 7), counter skipping past ids in use, row re-addressing,
unknown class, full roster, occupied slot, item/mastery/bitmap byte identity, index order, "no other
unit touched", and the four `verify` failures.

```
$ python -m pytest tests/test_unitbank.py -q                     20 passed
$ python -m pytest tests/test_unitbank.py tests/test_overlord_import.py tests/test_evcap3.py -q
                                                                69 passed
```

---

## 5. Recommendation and first step for each

**Recruiting (the acquisition route).** Do **B then A**, and keep F as the shelf.

1. **First step (cheapest, 1 session): make the quest bulk.** In `d5lib/questpatch.py`, give the
   recruit-reward hook a list per quest: one quest row per pack, its completion creates every character
   of that pack (level 1) and banks the ones that do not fit. Acceptance: a pack with 13 characters
   produces 13 units on one quest completion, in the roster up to 128 and in the bank beyond it.
   *Offline first* — the hook's own unicorn probe already exists; extend it with a 3-unit case.
2. **Then (2–4 sessions): the Recruiter list.** Wire the installed-character list onto the same
   `.d5cl` hooks `newclasses.py` uses for imported classes and call `roster_create_unit(class, 0,
   level)` on confirm (Overlord's `RECRUIT_CHARACTER_RVA` design, credited). Prove it live for **one
   generic** before any unique: that is the cheapest possible live test and it decides whether the
   Recruiter is a viable list at all.
3. **Do not** add a per-character quest to any new pack. Ship the quest the pack already has (it works
   today), but stop making it the plan for the next 500 characters.

**The bank.** Ship F as the shelf; it is already proved offline.

1. **First step (1–2 sessions): the page.** `d5gui/savecleanup.py` is the shape to copy: list companies
   from the installed mods (`savegame.mod_characters` already returns a mod's classes), list the save's
   units, Export/Import through `d5lib/unitbank.py`, `savegame.backup` first, refuse while the game
   runs.
2. **Then, the integration gap: re-emit the learned companion.** After `Save.write()`, rebuild
   `<save>.d5learn.json` from the imported units' `learned_extra` (`learned.sidecar_doc`, keyed by the
   new serial) or delete it loudly. Without this, a bank import silently drops extension-only learning
   — the one thing in this design that would lose data.
3. **Then the live question, once, on a copy:** does the game load a save the Kit wrote, with an
   imported unit in it? That is the single unproven link in the whole bank, and it needs a real launch
   (`d5link` + `hide_game.sh`), which this lane is not allowed to do.

**Not recommended:** a bill per character (D) — same entry-count problem in a slower menu; the DLC
delivery list (E) — the class ids are immediates, so it is an exe hook for a global menu that is not
per-save.

---

## 6. What is NOT proven / open

1. **No native load of a Kit-written save, ever** — with or without a banked unit. The parser accepts
   it; the game has not been asked. This is the acceptance step for F.
2. **The 128 limit is from the create guard and the save's own 128 records** — I did not try to raise
   it, and nothing here suggests it can be raised safely (the roster, the three serial lists, the
   squads, the groups and the base walker all index 0..127).
3. **The "recruited" bit** (`DAT_1458456dc`) and whether a banked or bulk-recruited character behaves
   like one the story handed over: unmeasured.
4. **The Recruiter for unique rows**: whether its rank/personality pages can be satisfied for a rank -1
   row without Overlord's full custom page. The live generic test in §5.2 is the cheap way to find out.
5. **Effort figures are agent-session estimates**, not measured; only F's export/import is measured.

## 7. State left behind

```
git     branch work/recruitdesign-20261030 @ 9268eec + the commits below; nothing pushed, not merged
files   d5lib/unitbank.py (new), tests/test_unitbank.py (new), tools/prove_unitbank.py (new),
        Subprojects/Engine-Extensions/RECRUITDESIGN.md (this report), one KANBAN line
disposable  /Volumes/Data/ai-tmp/hermes/recruitdesign-20261030/ (save copies A/B/C, bank.json, proof.json)
game    not launched; installed kit, Steam folder, real saves, d5auto.ini untouched
```
