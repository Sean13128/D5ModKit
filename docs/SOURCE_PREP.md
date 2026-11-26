# Preparing the source folder (SOURCEPREP2)

The D4 / D1 Complete / D2 / RPG importers read the user's own copies of those games.  This tool copies the files
they need into one fixed folder next to the Disgaea 5 install, verifies each file against a known-good build and
writes a manifest.  Game data never ships with the kit: each user builds the folder on their own machine.

    python tools/prep_source.py [--dest DIR] [--d4 DIR] [--d1c DIR] [--d1pc DIR] [--dd2 DIR] [--drpg DIR]
                                [--drpg-masters DIR] [--drpg-catalogs FILE] [--link] [--dry-run] [--json]

The destination is `<Disgaea 5 Complete>/D5ModKit/Source/` unless `--dest` says otherwise.  The tool never
decrypts, never uses keys, never runs UnityPy, and refuses to write inside `Disgaea Source/` or inside any of its
own inputs.  Exit code 0 means every required file is verified; 1 means a file differs, is unknown or is missing;
2 means the destination or arguments were refused.

## One canonical folder

`d5lib/sourcefolder.py` resolves the same folder the tool writes, so importers and prep agree whether the kit lives
inside the game folder or anywhere else:

1. `D5_SOURCE_DIR` (environment; tests or a hand-picked folder);
2. `settings.json` key `source_dir`;
3. `<Disgaea 5 Complete>/D5ModKit/Source` (the canonical default; the game folder is found through the kit's
   settings, the kit's own location, or Steam on Windows/macOS/Linux);
4. `<kit>/Source`, only when no Disgaea 5 folder is found at all.

If you pass `--dest`, prep writes there but the resolver does not know about it: set `D5_SOURCE_DIR` or the
`settings.json` `source_dir` key to the same folder so the importers read it.  A run started with `--only` keeps the
manifest entries and files of the games it did not touch.

## What it asks for

| game | what the user supplies | how |
|---|---|---|
| Disgaea 4 Complete+ | nothing to prepare by hand | found through Steam (app 1233880), or `--d4 <game folder>` |
| Disgaea 1 Complete | the **Switch** romfs (HD faces); a PS4 unpack is accepted but incomplete | `--d1c <folder holding data/SUBDATA.DAT>` |
| Disgaea 1 PC (voices, optional) | nothing to prepare by hand | found through Steam (app 405900), or `--d1pc <folder>` |
| Disgaea D2 | the decrypted PS3 disc dump | `--dd2 <folder holding PS3_GAME/USRDIR/Data>` |
| Disgaea RPG JP | the app's files, **already unpacked**; the decoded masters are required, the D5 catalogs optional | `--drpg <folder>`, `--drpg-masters <decoded JSON folder>` (required), `--drpg-catalogs <file>` (optional) |
| Disgaea 5 | nothing: the base game is read in place | the kit reads it through its own `state/games/*/backups` |

Decryption stays the user's job (Switch `.xci` to romfs, PS4 `.pkg` unpack, PS3 disc dump).  The tool accepts the
resulting files and checks their size and SHA-256.

## The folder it writes

    <Disgaea 5 Complete>/D5ModKit/Source/
        manifest.json
        d4/     Data/DATA/ANM_HI.dat, Data/DATA/WF.dat, DATABASE files, voice banks
        d1c/    data/SUBDATA.DAT
        d1pc/   Disgaea PC/DATA.DAT, Disgaea PC/SUBDATA.DAT
        dd2/    PS3_GAME/USRDIR/Data/START*.dat, ANM_HI*.dat, SOUND/SndPakVoice*/
        drpg/   sprites/ (1,567 PNGs), looks.json, atlas-index.json,
                assetbundle/sounds/voice/battle/<id>/<id>_{acb,awb},
                masters/{character,charactercommand,command,leaderskill}.json,
                d5-catalogs.json

`--link` symlinks instead of copying (same disk, saves space); the default is a copy.  Re-running is safe: a file
already present with the same size and SHA-256 is kept.  `--dry-run` reports without writing anything.

A `manifest.json` that is not a D5 source manifest (another tool's JSON, a wrong `schema`, a truncated file) is
**refused before anything is copied** and never replaced, including by a run that would otherwise exit 1 and during
`--dry-run`: the file stays byte-identical and the tool tells the user to choose a fresh destination or move that
file away.  Only prep's own `d5-source-manifest/1` is read and rewritten.  `d5lib/sourcefolder.py`'s
`write_manifest()` enforces the same refusal, so a foreign file cannot be replaced even if it appears mid-run.

A verified file already in the folder is never replaced by a mismatched input: the tool keeps the good copy and
warns that the supplied file did not verify.  Replacements are staged inside the destination and published only
after the staged bytes match the input; in `--link` mode the new symlink is staged at a unique path and renamed
over the target, so a failed link cannot delete the output first.  Every destination parent is resolved first, so a
nested symlink cannot redirect a write into an input or outside the folder.  The manifest always describes the files
actually left in the folder, including after a failed update (`missing` when nothing was written), and a scoped
retry whose input cannot be found keeps and rechecks the rows of the files already prepared.

## Disgaea 1 Complete faces must be HD

The HD faces are 268 `swf####` textures inside the Switch `SUBDATA.DAT` member `anmdat.fad` (D1CHDFACE1).  That is
why the Switch romfs is the preferred D1C source.  When a folder holds both dumps the tool hashes them and chooses
the recognized Switch build; the manifest records `"hd_faces": "switch"`.  A PS4-only input is reported as
**incomplete** for D1C and the run exits 1, because the current HD-face reader decodes the Switch pixel layout only
(`"hd_faces": "ps4-incomplete"`).  The PS4 warning is printed only when the file really hashes to the PS4 build; an
unrecognized dump is reported separately as unverified.  `hd_faces` describes the `SUBDATA.DAT` actually in the
source folder, not the input offered: a PS4-only retry does not overwrite a prepared Switch dump (it warns and
keeps it), and a failed Switch copy over a prepared PS4 file still records `ps4-incomplete`.  Do not substitute the
old `start.dat[73]` set: that is the PC-era art, not D1 Complete's HD faces.

## Disgaea 4 faces and cut-ins

`tools/prep_source.py` copies `Data/DATA/WF.dat` (face textures) and `ANM_HI.dat` (bodies, cut-ins, animations).
`tools/d4_extract_screen_art.py` (D4FACETOOL1) turns them into the `character_id_<N>/face` and `cutin` folders the
D4 importer reads; pointing the importer at the prepared folder instead of the old Forge backup is D4FACEWIRE1.

## Disgaea RPG: no UnityPy in the prep tool (Sean, 2026-11-18)

The tool does not decode Unity bundles.  The user supplies the already-unpacked files:

* `sprites/` (the RPGEXTRACT1 layout: `Chara Icons/`, `Cutins/`, `Sprites/Standard/{BattleFront,BattleBack,WaitFront,WaitBack}/`),
  including the DRPGK2B costume looks (1,285 + 282 PNGs);
* `looks.json` and `atlas-index.json`;
* the battle voice bundles `assetbundle/sounds/voice/battle/<id>/<id>_acb` and `_awb`;
* the decoded masters JSON (`character`, `charactercommand`, `command`, `leaderskill`) through `--drpg-masters`;
* optionally `masters/characterclassname.json` (next to the four masters in the `--drpg-masters` folder): the text pool the
  reviewed class titles (`drpg-titles.json`, JP titles stored as `@text` hashes) resolve against; a prepared folder without it
  refuses a build that needs a title, naming the file;
* optionally `d5-catalogs.json` through `--drpg-catalogs` (needed by the reviewed family mapping).

The known-good table pins the hashes of the retained decode.  A different decoder may produce different PNG bytes;
that is reported as `verified: "no"`, not silently accepted.  The tool also checks the sprite and battle-voice
paths in the table against what the folder actually contains: an empty sprite directory or one missing voice bundle
is recorded as `missing` and the run exits 1, so a partial unpack cannot pass just because the indices and masters
verify.  If a whole sprite or battle-voice directory is absent, its expected rows are still written as `missing`
(alongside the directory-level error), so a consumer that only rechecks the manifest sees the omission too.
The four master rows (`masters/{character,charactercommand,command,leaderskill}.json`) come from the **required**
`--drpg-masters` flag, and the catalog row (`d5-catalogs.json`) from the **optional** `--drpg-catalogs` flag.  Their
rows are always planned while the DRPG game is selected, even when `--drpg` is supplied without a discoverable index
(`looks.json`): omitting `--drpg-masters` is a problem (the run exits 1), omitting `--drpg-catalogs` is only a warning
(exit 0 when everything else verifies), because the catalog is optional.  A first run writes the rows as `missing`
instead of dropping them, and a retry rechecks and keeps the prepared copies already in the folder.  The unsupplied
input (or the missing index) itself is still reported, so the four required masters can never disappear from the
manifest and `verify_manifest()` never re-hashes a DRPG entry to a complete source while a master is missing.
Nothing in this step writes a file into the game's own folders.

## Manifest and verification states

`manifest.json` (`d5-source-manifest/1`) records, per game, the edition, the origin, and each file's path, size,
SHA-256, `known_build` and one of:

* `yes` - size and SHA-256 equal an accepted build in `d5lib/data/source_known.json`;
* `no` - the path is known but the bytes differ (the file is listed and the tool exits 1);
* `unknown` - the table has no row for that path;
* `missing` - expected (from the input or the table's inventory) but not supplied.

The D1C entry also carries `hd_faces` (`switch`, `ps4-incomplete`, `recognized`, `unrecognized` or `missing`),
derived from the prepared file on disk, plus `hd_source` and `hd_candidates_checked` for the input that was offered.

`d5lib/sourcefolder.py` is the one resolver the importers will use (SOURCEPREP4): `source_path(game, rel)` and
`have(game, rel)`; see "One canonical folder" above for its order.

**Disgaea RPG importer (SOURCEPREP4-DRPG).**  `python tools/import_game.py drpg` reads every game input through
`d5lib/importers/_drpg_source.py` (`DrpgData`): sprites, icons, cut-ins and voice banks are asked for by the exact
relative path, and a file is returned only when the manifest lists it for `drpg` with `verified: "yes"` and its bytes
still hash to the row (one read, so a same-size replacement is refused).  A file that merely sits in the folder is never
read, on any route (costume looks, voices, cut-ins included).  The reviewed roster is `drpg-roster-0..3.json` (ids, rules,
`@text` SHA-256 references resolved against the prepared masters and the Disgaea 5 tables, `@authored` project wording;
regenerate with `tools/build_drpg_rules.py roster`) and the wheel-freeze counts are `drpg-bank-shapes.json`.  No installed
pack is read unless you pass `--installed-reference`.  The Outfit System marker mod is written into the build's own work
folder.  The learned pose reference `d5lib/data/drpg_ref_humanoid.pickle` is **not** in Git: put the upstream release file
there, or rebuild it byte for byte from the labelled sheet the release zip carries
(`python tools/drpg_make_ref.py --release-zip <D5ModKit zip> --out d5lib/data/drpg_ref_humanoid.pickle`, POSEREF1); it
is used only when its SHA-256 equals the pin in `drpg-pose-reference.json`.  The four own cut-ins (DRPGCUTIN2) come from illustrations the prepared folder does not hold;
pass `D5_DRPG_OWN_CUTINS=<folder of <id>.png>` to use them, otherwise those looks keep the base portrait.  Two groups of units are not in the RPGEXTRACT1 sprite decode: the 20 vanilla monster
twins the monster looks are paired with, and 14 looks (XENO and other variants: ids 90 120 165 166 173 176 343 391 392
394 395 20026 20054 20115).  Their sheets, face and cut-in are *optional* rows of the known table (`optional: true`, build
`drpg-jp-client-decoded-20261016`, hashes only): supply the decoded PNGs in the same `Sprites/Standard`, `Chara Icons` and
`Cutins` layout under the folder given to `prep_source.py --drpg` and prep verifies them like any other row; without them
the packs that need them refuse by name.

**Disgaea 1 Complete importer (SOURCEPREP4-D1C).**  `python tools/import_game.py d1c` reads `d1c/data/SUBDATA.DAT` from
this folder and nothing else of the game: the importer (`d5lib/importers/_d1c_source.py`) refuses unless the manifest row
is `verified: yes`, the file is there and its size equals the row's; a missing or failed row is named in the error
(exit 2).  A file merely sitting in the folder is never read.  The default build reads no installed pack either: the
bank shapes, hurt flags and held-animation ids it used to compare with an installed pack are the checked-in ids/counts in
`d5lib/importers/d1c-bank-shapes.json` and `held-blank-keys.json`; `--installed-reference` restores the read-only
comparison for a machine that has the packs.  `--source-root <romfs>` is an unverified diagnostic route.

## Current limits

* Importers still use their old paths; switching them is SOURCEPREP4 (one card per game).
* Regrouping DRPG families (the maintainer step behind `drpg-roster-*.json`) still needs the research mapping tools and `d5-catalogs.json`; the importer does not.
* Windows and Proton are untested; the code is stdlib-only Python.
* `d5lib/data/source_known.json` holds hashes only, never file contents.

## Disgaea 4 (SOURCEPREP4-D4)

`d5lib/importers/_d4_source.py` is the D4 importer's only way to the game bytes: `data_dir()` reads
`manifest.json`, requires a `verified: "yes"` row with a SHA-256 for each of the eight D4 files prep copies (and the
file on disk at the recorded size), and returns a `D4Files` value object.  `D4Files.path(rel)` refuses any path that
is not in that set (a file merely present in the folder is never read) and re-proves the file's SHA-256 against its
row, keyed on the file's stat signature, so a same-size replacement after prep is refused by file name.  Every table
reader (`d4source.D4Data`), the voice reader, the specials pass and the face / cut-in extractor open files through
`path`; child builder processes are told the same set in `D5_D4_VERIFIED_SET` and read through it too.  A missing or
failed row is an argparse refusal (exit 2) naming `d4/<path>` and the prep command.

The reviewed ids/rules live in `d5lib/importers/d4-*.json` (allocation, mapping, both exact-emission tables,
reserved ids, recorded unique commands, specials tables, installed-pack bank shapes) and in
`d5lib/data/d4-common-poses.json`.  **No game text is stored**: a name or description is a reference
(`{"@text": sha}`, `{"@template": sha, "args": [..], "percent": ".."}`, `{"@prefix": "..", "@text": sha}`,
`{"@segments": [..]}`, `{"@skeleton": sha, "marks": [..]}`) resolved at build time from the prepared D4 tables and
the user's own Disgaea 5 tables through the kit's backup index (`TextPool`), or `{"@authored": "..."}` for a sentence
the kit wrote that no game table holds.  `tests/test_d4sourceprep.py` fails on a bare string in a name/desc field.
`tools/build_d4_rules.py` regenerates those files from the reviewed October/lane tables (maintainer tool).

Prepared art (the packets the builders read) is regenerated on every build from the verified `ANM_HI.dat` in the
build scratch.  That uses the Character Forge art code, which is outside this repository (provenance review
pending, as for DD2): point `D5_D4_FORGE` (or the kit setting `d4_forge`) at the folder holding `forge/`, for
example `<project>/Migration/CharacterForge`.  Faces and cut-ins are extracted from the verified `WF.dat` /
`ANM_HI.dat` by `d5lib/d4screenart.py` into `<output>/d4/screen-art`, a folder the importer owns (marker file, never
inside the source folder; a symlink or a foreign non-empty folder is refused, nothing in it is ever deleted, and a
PNG is used only when that folder's receipt records its SHA-256).  `D5_D4_SCREEN_ART` / the `d4_screen_art` setting
name a folder of your own instead, used as given.

`python tools/import_game.py d4` takes no machine path, builds every in-scope pack (~73), and reads no installed
pack by default: `--installed-reference` (or `--compare-installed`) is the explicit read-only comparison.
