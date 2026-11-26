# Source-game voices for imported characters (VOICE1)

Imported characters speak with their own source-game recordings: a custom voice (`docs/VOICES.md`) per character,
converted from the user's own game files at build time. No audio is in the kit; the kit holds readers and mapping
metadata only (`d5lib/importers/*-voice-*.json`).

    python tools/import_game.py drpg|dd2|d1c --source-voices ...        # importer post-pass + voice gate
    python tools/build_source_voices.py --mods <base mods> --out <bundle>/mods \
        --drpg-source "<Disgaea RPG JP (Android)>" --dd2-source "<Disgaea D2 PS3 disc>" --d1-source "<Disgaea PC>"
    python tools/check_installed_voices.py --game "<Disgaea 5 Complete>" --mods <mods>   # readback after install

`build_source_voices.py` clones existing packs and adds only `patches/voices/`, the `voice_id` of the pack's added
char.dat rows and the `source_import.voice` label in mod.json; it proves every other file byte-identical and runs
the voice gate. Converting needs ffmpeg (HCA, VAGp, Ogg).

## How the map was found: the same recordings exist in D5

D5's line table flags every line with the situations it may play in (`docs/VOICES.md`). Many characters exist both
in D5 and in a source game **with the same recordings**. Matching a source clip to the D5 line of the same
character (normalised waveform cross-correlation, 16 kHz, peak >= 0.6; unrelated clips score under 0.3) lets D5's
own flags say where that clip belongs. Nothing was labelled by listening.

| source | shared characters | clips compared | same recording found in D5 |
|---|---:|---:|---:|
| Disgaea RPG (JP) | 33 | 571 | 451 |
| Disgaea D2 (JP) | 25 | 3,336 clip slots | 2,322 |

A source label (cue name or selector column) is routed to a D5 (kind, situation) when at least 15% of its matched
clips carry that flag. Accuracy is measured leaving one character out: derive the routes from the others, then ask
whether the held-out character's clips really carry a routed flag in D5.

### What D5's situations mean (read off the named Disgaea RPG cues)

| D5 kind 0 situation | Disgaea RPG cue whose recordings D5 stores there |
|---|---|
| 0 (also 1, 10, 11, 13) | `voice_attack`: attack shout; D5 reuses these grunts for lift 10, throw 11, move 13 |
| 2 (also 1) | `voice_h_attack`: heavy attack shout |
| 4, 3 | `voice_magic`: spell cast |
| 9, 8, 12 | `voice_recover`: healing |
| 6 | `voice_spNN`: special skill shout |
| 3, 4, 5, 7, 17 | `voice_turn`: taking a turn |
| 14, 15, 18 | `voice_glad`: joy (level up, victory) |
| 20, 19 | `voice_damage` |
| 21 | `voice_dead` |

Kind 3 repeats the reactions (0-2 attack tiers, 20 damage, 21 death, 31/33 joy, 32 pain); kind 1 situation 22
holds the spoken (worded) lines. Which engine event plays kinds 1-3 is only partly traced
(`sound_voice_play_random_for_set` 0x1402277b0 callers); the routes mirror where D5 keeps the same recordings for
its own characters.

## Disgaea RPG (`d5lib/drpgvoice.py`)

* Files: `assetbundle/sounds/voice/battle/<id>/<id>_acb` + `<id>_awb`, one pair per character or costume id (the
  folder id is the character master id: 948 of 952 master ids have one). Each is a UnityFS bundle (LZ4 blocks)
  with one TextAsset: a CRI ACB cue sheet (`@UTF`, big-endian) and an AFS2 wave bank of unencrypted mono HCA,
  22,050 or 48,000 Hz. Japanese only. The reader needs no UnityPy (blocks are unpacked and the length-prefixed
  payload is found by its magic; checked equal to UnityPy on a sample, and the cue tables equal on 993 banks).
* Cue -> clips: CueName -> Cue (ReferenceType 3) -> Sequence.TrackIndex -> Track.EventIndex -> TrackEvent command
  2000 (reference kind, index) -> Synth.ReferenceItems -> Waveform.StreamAwbId. A sequence with several tracks is
  a set of alternative takes. Reference kind 7 (3 banks) is not read.
* 992 battle banks carry `voice_attack`, `voice_h_attack`, `voice_damage`, `voice_dead`, `voice_magic`,
  `voice_recover`, `voice_turn`, `voice_get`, `voice_glad` and 0-25 `voice_spNN`. Other cue names (birthday,
  promo, shop lines) are never routed. A take under 0.08 s or silent is the source's placeholder and is skipped;
  a bank with nothing audible means the character does not speak (5 of the 235 looks).
* Routes: `importers/drpg-voice-routes.json` (with the evidence counts). Leave-one-character-out hit rate: attack,
  heavy attack, death, joy, get, turn 1.00; magic 0.98; recover 0.94; damage 0.93; special 0.77 (specials are
  routed to situation 6 only).
* A costume row speaks its own bank: the game reads the voice from the worn row (`cmdmenu_util_voice_key`
  0x140160280 reads char table index `+0x2E0A`).
* Lines are Japanese with `fallback_language: "JP"`: the English setting plays the Japanese line. Personality 0.
* Voice ids: `importers/drpg-voice-leases.json`, block 7000-7499, keyed by Disgaea RPG id.

## Disgaea D2 (`d5lib/dd2voice.py`)

* Files: `SndPakVoiceEN_N.pak` / `SndPakVoiceJP_N.pak` on the PS3 disc: big-endian `VAGp` PS-ADPCM, 22,050 Hz
  (ffmpeg `-f vag`). Both dubs; the English dub has fewer lines (4,739 routes against 8,631).
* Map: the executable's selector table (540 rows x 19 columns, key = category, voice key, generic variant; voice
  key = char row `+0x1b8`) and the id routing tables, read by VOICEMAP1. `importers/dd2-voice-map.json` keeps, for
  the imported characters, column -> voice ids and voice id -> (pak, offset, size) with the pak hashes.
* Routes: `importers/dd2-voice-routes.json`. Category 0 columns: 0 attack, 1 heavy attack, 2 cast / turn, 3 -> D5
  5/16, 4 special shout, 5 and 8 healing, 6 lift, 7 throw, 9 move, 10 joy. Columns 6, 7, 10 and 18 (whole-bank
  preview, never routed) agree with what DD2EVENT1 proved from the executable. Category 1 columns are mood
  buckets; 1:13 and 1:14 (pain) score 0.56 and 0.73 leave-one-out and are **not used**: a column is used only at
  0.8 or better, so DD2 damage and death stay silent.
* A class keeps its three source variants as the three D5 personalities (an inference: both games index a
  generic's voice by a 0-2 choice made at creation). Uniques use variant 0.
* Every line has `files: {EN, JP}`; a clip the English dub lacks is silent there (`missing_locale`).
* Voice ids: block 7600-7699, in the map file. Characters without selector rows (Pringer Z, Baal Slave) are silent
  in the source and keep their donor.

## Disgaea 1 (`d5lib/d1cvoice.py`)

* Map: Disgaea 1 Complete's selector (66 characters x 4 lists of clip records, script opcode 0x87 picks the list;
  VOICEMAP1). `importers/d1c-voice-map.json` keeps list membership per imported pack, including the game's own
  aliases (Vyers uses Mid-Boss's clips, Dark Flonne uses Flonne's, ...).
* Audio: read from the Disgaea PC `DATA.DAT` (PSPFS_V1 -> `VOICE01/02[_EN].PBD` DSARC FL -> Ogg Vorbis 16 kHz).
  Clip names are identical in the PC, Switch (`.nlsd` type 8) and PS4 (`.nlsd` wrapping `VAGp` version 0x20001,
  which ffmpeg's VAG reader rejects) editions; only the PC codec is decoded here. Each clip is checked against its
  recorded sha256.
* List meaning: list 0 is the attack / skill shout (509 of 632 script voice calls, every event family; 12 of 15
  list-0 clips that Disgaea RPG reuses are named attack or heavy attack there). Lists 1 and 2 are called only
  inside skill choreographies: skill shouts, routed like the D4 pass routed its two script-only shouts (list 2 ->
  heavy attack slots 1/2, list 1 -> special slot 6); the recordings agree for 4 of 9 and 4 of 7, so this is a
  labelled choice between equivalent skill-shout slots. List 3 is not routed. A clip in no routed list that
  Disgaea RPG names follows that cue.
* 15 packs have Disgaea 1 clips (5-11 each); the other imported Disgaea 1 characters have none in the game.
* Voice ids: block 7500-7599, in the map file.

## Gates

* `drpgvoice.voice_gate(mod)`: every custom voice a char row links is defined; every line's clip exists, decodes
  to finite 48 kHz audio, lasts 0.08-20 s and peaks between 0.01 and 0.85; each dub has an attack line; no stray
  clip; no voice set over 512 lines (the game's scan buffer). It fails on a missing, silent or unlinked clip
  (`tests/test_drpgvoice.py`).
* Custom voice ids are part of the used-id gate (`importcore.mod_claims` kind `voice`, recorded leases in
  `lease_claims`).
* `tools/check_installed_voices.py` reads the installed game back: line rows in both tables, clips in
  `Sound_Voice_0.dat` byte-equal to the pack, char rows linked.

## VOICE2: what each source game voices, and silence where it is silent

Measured facts (2026-11-10), each mirrored in the packs:

* **Disgaea D2 voices neither damage nor death in battle.** The battle category (0) has columns 0-10 and the preview
  column 18: all 27 native callers of the selector wrapper and all 803 literal script voice calls ask for those.
  Columns 13-17 of category 1 are five mood buckets chosen outside battle (a signed value at actor `+0x6da` of a
  menu actor list; scripted hub events), category 2 columns 11 / 12 a yes / no pair. D5 re-used some of those
  recordings as its own damage (20) and death (21) lines, which is all VOICE1's 0.56 / 0.73 measured. As a
  predictor, "a clip of column 1:13 is a D5 damage line" is right for 19 of 94 matched clips (1:14: 16 of 97);
  no duration bin is better than 6 of 11. Nothing reaches 0.90 and the source has no such situation: silent.
  (`importers/dd2-voice-routes.json` `findings`, with the per-clip D5 re-use list for reference.)
* **Strict check of the shipped DD2 columns** (battle flags only, so the catch-all kind 1 situation 22 cannot
  score; leave one character out): 0 attack 0.96, 9 move 0.98, 7 throw 0.87, 6 lift 0.86, 2 cast 0.86, 1 heavy
  0.85, 10 joy 0.85, 3 0.76, 5 heal 0.75, 4 special 0.74, 8 heal 0.58. This measures how D5 re-labelled re-used
  recordings, not what the column means in DD2 (6, 7 and 10 are proven from the executable); the routes are
  unchanged and the figures are recorded for a decision.
* **Disgaea 1 voices only what a script asks for** (opcode 0x87, lists 0-3): attack and skill shouts. No list and
  no clip is a damage or death line. The map (`d1c-voice-map/2`) decides every D1C pack by what the selector
  holds for its character id: its clips (a clip now follows *every* routed list it is in); for a monster the one
  shared sound effect all four lists name (`07_05`, `07_09` or `07_10`, sound bank 1 = Disgaea PC `SUBDATA.DAT`
  -> START.DAT member 66, Ogg; battle situations only, volume scaled by the record gains 138 / 168); or nothing.
* **Silent as in the source**: `drpgvoice.SILENT_VOICE_ID` (5999) is a voice id without lines; D5's own table has
  231 char rows whose voice has no line and no pack. `link_silent` links a pack's rows to it and writes
  `source_import.voice = "silent, as in the source game (...)"`. Used for Disgaea 1 ids without a selector entry
  (27 packs), DD2 voice keys without selector rows (Pringer Z, Baal Slave) and Disgaea RPG characters whose bank
  holds only the silent placeholder (master `cv_name` "-": three Pringers, Haru, Yui). The voice gate and
  `check_installed_voices.py` check such packs.

## Which line played (voicetrace)

`voicetrace on|off|status` (harness command, `d5lib/native/d5anmtrace.inc.c`; off by default, nothing is written
into the game until `on`) logs every voice line request: a pre hook on `sound_voice_table_lookup` 0x1400AEF60
(first 5 bytes `mov r9d, edx; test edx, edx`), whose caller 0x3F7954 is `sound_voice_play`'s first statement.
`anmtrace.voice_requests(log)` keeps those, `anmtrace.voice_clip(mod, line)` names the pack's clip and situations.
The request is logged whatever the volume is. The stub is proven offline by emulation; not yet run in the game.

## Not proven

Nothing here has been heard in game. Open: which engine events play kinds 1-3; whether a costume-wearing or
class unit always has the personality the lines were written for; per-skill special shouts (Disgaea RPG's
`voice_spNN` are pooled on situation 6; the source ties each to one skill animation).
