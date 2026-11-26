# Source folder design (SOURCEPREP1 design; SOURCEPREP2 resolver and prep tool)

Goal: a person builds the same D4 / D1C / DD2 / DRPG character packs from their own game files, with no path that is
specific to the project owner's machine. Game data never ships; only ids, rules and code do.
Evidence for every statement here: `Subprojects/Engine-Extensions/SOURCEPREP1-REPORT.md` in the D5 project (traced builds,
file lists, hashes). The tracer that produced it is `tools/source_trace/`.

**Implemented in SOURCEPREP2:** `d5lib/sourcefolder.py` (the resolver), `d5lib/data/source_known.json` (hashes only) and
`tools/prep_source.py` (the tool; usage and per-game steps in `docs/SOURCE_PREP.md`).  Importers still use their old
paths until SOURCEPREP4.  Sean answered the open questions on 2026-11-18 (ASK-778EF7): this folder, no UnityPy (users
supply unpacked DRPG files), D1 Complete faces must be HD (D1CHDFACE1), and a separate D4 face/cut-in extractor
(D4FACETOOL1, merged).

## Folder

One fixed folder, next to the Disgaea 5 install and inside the kit folder the kit already uses for `DRPG Assets (Updated)`:

    <Disgaea 5 Complete>/D5ModKit/Source/
        manifest.json
        d4/     Data/DATA/ANM_HI.dat, WF.dat, DATABASE files, voice banks   (layout of the D4 install, needed files only)
        d1c/    data/SUBDATA.DAT                                              (Switch romfs or PS4 unpack, `data/` kept)
        d1pc/   Disgaea PC/DATA.DAT                                           (Disgaea 1 Steam, voices only; optional)
        dd2/    PS3_GAME/USRDIR/Data/START_4.dat, ANM_HI*.dat, ...            (decrypted PS3 dump)
        drpg/   sprites/, looks.json, atlas-index.json, assetbundle/sounds/voice/battle/..., masters/*.json
        (d5     nothing is copied: the base game is the install itself plus the kit's own backup state)

Each game keeps the original relative layout, so a file name in the code is the same as on the user's disk. Copy by
default, optional link. The folder is outside the kit's git tree and is never published.

## Manifest (`manifest.json`)

    {"schema": "d5-source-manifest/1", "written": "<UTC time>", "tool": "<name version>",
     "games": {"d4": {"edition": "Disgaea 4 Complete+ Steam 1233880", "origin": "steam-auto", "root": "d4",
                      "files": [{"path": "Data/DATA/EN/DATABASE_EN.dat", "size": 22184129, "sha256": "...",
                                 "known_build": "d4-steam-1233880", "verified": "yes"}]}}}

`verified`: `yes` = size and SHA-256 equal a row of the known-good table `d5lib/data/source_known.json` (hashes only);
`no` = file present, hash differs (listed, importers that pin a hash refuse it, others warn); `missing`. The known-good
table starts from `Disgaea Source/SHA256SUMS-*.txt` and the DRPG `extracted/MANIFEST.json`.  The manifest always
describes the files actually left in the folder: a verified file is kept when a re-supplied input does not verify, and
a scoped `--only` run keeps the entries of the games it did not touch.

## One resolver

    d5lib/sourcefolder.py
    source_path(game, rel, *, required=True) -> pathlib.Path

Order: env `D5_SOURCE_DIR` (tests, the owner's `Disgaea Source` view) -> settings.json `source_dir` ->
`<Disgaea 5 Complete>/D5ModKit/Source` (the canonical default that prep also writes; the game folder is found through
the kit's settings, its own location, or Steam on Windows/macOS/Linux) -> `<kit>/Source` only when no game folder is
found.  Raises `SourceMissing(game, rel, how_to_get)` naming which prep step provides it. `have(game, rel)` for
optional inputs (D1 PC voices, DRPG voices). Importers call only this; no importer keeps `/Volumes/...` or
`Disgaea Source/` literals.  An explicit `--dest` is prep-only: the user must point `D5_SOURCE_DIR` or `source_dir`
at it for importers to read it.

## Supply per game (the tool never decrypts and never ships keys)

| game | the user gives | notes |
|---|---|---|
| D4 | nothing: Steam app 1233880 found from `libraryfolders.vdf` + `appmanifest_1233880.acf` | plain NSAC/FAFS/LZS, read by kit code |
| D1C | folder with `data/SUBDATA.DAT` from their own Switch (romfs) or PS4 (unpacked) dump, already decrypted | the Switch build is chosen when both are present; PS4 hashes differ and the current HD-face reader decodes the Switch anmdat.fad layout only, so a PS4-only input is reported incomplete (exit 1) |
| D1 PC | Steam app 405900 found automatically | optional: D1C voices only |
| DD2 | PS3 disc dump folder with `PS3_GAME/USRDIR/Data`, already decrypted | `START_4.dat` is the patch level every read uses |
| DRPG | the already-unpacked files: `sprites/`, `looks.json`, `atlas-index.json`, battle voices, decoded masters JSON | no UnityPy in the prep tool (Sean, 2026-11-18); the user supplies the unpacked files |
| D5 | Steam app 803600 (the base game) | modified files are read through the kit's `state/games/*/backups`, never the live bytes |
