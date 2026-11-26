# Game text in kit data: `@text` references

The importer data files describe the user's own game files.  They never store a game string
literally; they store a SHA-256 reference and the build reads the string from the user's own data.

```json
"name": {"@text": "0a84a844de6bf94e3d85807b6314a27e2b757f0cd064a32831d4559fad1a6fef"}
"label": {"@authored": "evility Wind Dominance (2200): D5 equivalent ..."}
```

- **`@text`** — the SHA-256 of the exact text the pack receives.  The hash is over the final string,
  not a normalized form; `d5lib/textrefs.TextPool` also indexes spelling variants (NFKC and the
  product-text ASCII fold, `nativeimports.ascii_latin`, which turns Disgaea 1's U+2212 "Astro−One"
  into "Astro-One"), so a reference resolves across the source edition's punctuation.
- **`@authored`** — wording our lanes wrote (review labels, adaptation lines), kept as text.

`d5lib/textrefs.resolve` walks the document and raises `TextRefError` with the JSON path in front
(which names the pack/skill id), the digest, and how to supply the missing source.  A build that
cannot resolve a reference refuses; it never writes the placeholder.

## Pools

| game | pool | source |
|---|---|---|
| D5 | `textrefs.d5_text_pool(game, state)` | `char.dat`, `Skill.dat`, `magic.dat` name/description columns, read through the kit's backup resolver (pristine rows even with a modded install) |
| D1C | `_d1c_source.text_pool()` | prepared `SUBDATA.DAT`: character table start.dat[43] names/titles, d1hd skill table start.dat[40] names/descriptions |
| DD2 | `_dd2_source.text_pool()` | prepared `START_4.dat`: skill, evility, char and help strings |

`_d1c_batch.text_pool()` merges the D1C and D5 pools; DD2 callers merge the D5 pool when a row names
a D5 string.

## What reads them at build time

`d1c.donor_evilities` (D1C donor evility names/text), `d1cvoice.voice_label` (D1C voice name; the
`" (D1C)"` suffix is `name_suffix`, authored), `dd2voice.voice_name` (DD2 voice name), and
`_dd2_innates.reviewed_pick` (DD2 innate row, name and label).  The review-only files
(`sourcemaps/*`, `dd2-leases`, `unique_art_leases`) are labels and rules; no default pack build reads
their names.

## Checking

- `tools/verify_textrefs.py` resolves every reference in the audited files from the prepared folder
  and the D5 tables (`--game-path`, `--state`, `--d4-prepared` for `unique_art_leases`).
- `tests/test_textrefs.py` fails when a name/title/description/text field is a literal again, when a
  reference is malformed, and when an unresolved hash stops naming its field.
- `tools/build_d1c_donor_evilities.py`, `tools/build_dd2_innates.py` and
  `tools/d1c_unique_skillmap.py` emit references; a regeneration that writes literals is caught by
  the test.

## Disgaea 4 (TEXTHASH-D4)

D4 carries five language columns, but the kit's D4 rows write one English string into all five, so one reference per
field covers them.  The pool is `d5lib/importers/_d4_source.TextPool`: every string of the prepared D4 `DATABASE_EN.dat`
(characters, titles, help, evilities, skills, personalities of every class family) plus the Disgaea 5 tables.
Forms (all resolved by `TextPool.resolve_doc`): `{"@text": sha}`; `{"@template": sha, "args": [..], "percent": "%"|"\uff05",
"trim": 1}` (a description with its numbers filled in; `trim` drops the final full stop a quote leaves out; a sentence
whose only placeholder is an escaped percent is a template with no args); `{"@prefix": .., "@text": ..}`;
`{"@segments": [text, {ref}, ..]}` (kit wording around quoted game text); `{"@skeleton": sha, "marks": ..}`;
`{"@authored": text}` (kit-written wording; checked against the pool, none of it is a D4 or D5 string).

- `tools/hash_d4_text.py` converts the files (idempotent, `--check` for a dry run).  It needs the prepared D4 folder
  (`D5_SOURCE_DIR`) and the Disgaea 5 tables (`--game-path`, `--state`).  It refuses to write a file unless the resolved
  document equals the old one.  Kit prose is converted only where it quotes a description (a template or a game string
  of 25+ characters), never for a bare name.
- Readers resolve at use: `sourceimports.load_d4_mapping` (default map `sourcemaps/d4.json`), `d4.Importer` (roster
  names from leases/scope), `magichange_rows.load_content`, the `_magichange_pass` lease check.  Without a build
  context they call `_d4_source.text_pool_for_tools()` (installed kit backups, else a clean D5 copy,
  `D5_CLEAN_GAME`) and refuse naming what is missing.
- Generators (`build_d4_leases`, `build_d4_scope`, `d4npc1_leases`, `build_d4_evility_overlay`, `reprofix1/3`,
  `build_d4_rules`, `magichange_rows`) write through `hash_d4_text.hash_document`.  `tools/evilgap1_rows.py` keeps game
  text out of the code: names/descriptions are reference dicts, and a note that quotes a description carries the quote
  as an inline marker (`\u27e6{ref json}\u27e7`) that `refs()` turns into `@segments` on output.
- `tests/test_d4texthash.py` fails when a name/desc/title/text field (or a personality name, or a magichange
  character/attack name) is a bare string in any of the listed D4 files, or when `row()`/`alias()` in
  `evilgap1_rows.py` gets a literal.


## Disgaea RPG (TEXTHASH-DRPG)

The DRPG data files use the same shapes, resolved by `d5lib/importers/_drpg_text.py` against the DRPG pool
(`_drpg_roster.TextPool`: the verified prepared masters `character`, `charactercommand`, `command`, `leaderskill`,
`characterclassname`, plus the pristine Disgaea 5 tables read through `fs`).  Families:

| file | `@text` (source text) | `@authored` (our wording) |
|---|---|---|
| `drpg-evility-overlay.json` | JP evility names (`name_jp`, `skill_row.name_JP/CHN/KOR`) | English names, the five description columns, character labels |
| `drpg-skill-overlay.json` | JP skill and spell names, D5 stand-in and same-name spell names | English names, generated descriptions, effect labels; `@parts` for a sentence that quotes a D5 name |
| `drpg-evility-names.json` | the JP name of each pair (a list, never a dict key) | the provisional English |
| `drpg-skill-names.json` | (keys are skill ids) | the provisional English |
| `drpg-titles.json` | JP class titles (`characterclassname`) | English titles (provisional or community-documented) |
| `drpg-skill-twins.json` | D5 skill names (`name`, `replaces`) | |
| `drpg-leases.json` | | character and look names |

`tools/build_drpg_text_refs.py convert` rewrites the files in the reference form and `verify --against REV` resolves them
against the real pool and compares with the literal file at a git revision.  The generators
(`build_drpg_evility_overlay.py`, `build_drpg_skill_overlay.py`, `drpg_leases.py`) emit the reference form themselves.
Tests install `tests/drpg_text_stub.py` (every hash answers a placeholder); `tests/test_drpgtexthash.py` fails when a literal
game-text field returns.  `textrefs` gained the additive `@parts` shape (a project sentence with game text inside).
