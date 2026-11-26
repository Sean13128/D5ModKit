# D4 source voice adaptation

`d5lib.d4voices.import_d4_voice` converts explicitly selected D4 personality
groups through the Kit's existing custom voice and VAG pipeline. It does not
change native playback, timing or random selection.

Pass a free custom `voice_id`, one to three distinct source `groups`, and an
explicit `event_map`. Source character `body` at offset `0x1ba` is the voice
group base; `sprite` at `0x196` identifies art and may differ. Each selected
group retains its own D5 personality index. Additional source personalities
must be accounted for by the importer caller; they must not be silently merged.

`basic_event_map()` supplies a conservative playtest adaptation:

| D4 category | D5 kind/category | Established caller role |
| --- | --- | --- |
| 0 | 0/0 | Basic weapon attack (also the script default) |
| 2 | 0/4 | Ordinary elemental casting branch |
| 4 | 0/9 | Alternate healing casting branch |
| 5 | 0/10 | Carrier lift |
| 6 | 0/11 | Carrier throw |
| 7 | 0/13 | Move / landing after a hop |

These destinations can also be used by other D5 contexts. The map establishes
an adapted recipient, not equivalent recording selection or timing. D4
category 11 is a whole-bank recruitment preview bucket and is not mapped to
a battle event.

The twelve D4 situations are not twelve different functions: every dispatcher
arm (`FUN_140251ee0` .. `FUN_140251fe0`) is byte-identical apart from the
category constant it hands to `FUN_140467400`, so the meaning of a situation
comes only from its callers. Of the twelve, `1`, `3`, `8` and `9` have no
engine caller at all - they are reachable only through the two script voice
commands (`operand / 10000` is the situation, `% 10000` the actor) - so their
role cannot be established from code, and `10` reads level/EXP at one caller
(`0x140300bb0`) but is used as a generic filler line at four others. Those
five, plus the preview bucket `11`, are deliberately left unrouted: a clip that
has only those flags stays silent instead of being pushed onto an unrelated D5
situation. Damage and death have no D4 engine situation of their own: every
engine voice call site (19 in the pinned build) sits in an action, movement or
menu handler, none next to an HP write or a death check, so D4 reaction/death
bark may only exist behind the script-only situations - unverified. A D4-voice
pack therefore adds nothing to D5's damage/death slots, and the script-only
situations and direct-only source clips require additional reviewed mappings.
The helper accepts caller-supplied maps for that work and records their
provenance in each clip receipt.

Source gain divided by 100 is baked into resampled 48 kHz PCM, then limited
to the requested peak (default 0.85). Encoding uses the existing Kit ADPCM
encoder without trimming or normalization. The encoded result is decoded
and checked; bounded gain-only retries correct quantization overshoot.
This is a loudness adaptation. The source signed rate input and wrapper are
preserved as metadata; their native playback behavior is not recreated.

Every selected source clip receives an identity, input hashes, source group,
personality, gain, categories, destination provenance and unresolved category
reasons. Converted clips also record output hashes, rate, sample count and
decoded peak. A clip without a reviewed destination receives an explicit
unrouted reason. If no clips can be routed, conversion fails rather than
registering an empty voice.

The default custom-file path still mirrors the same recording into EN and JP.
For an explicit locale import, pass `source_language="EN"` and
`destination_language="EN"`, then call the helper again for the same voice ID
with both fields set to `"JP"`. This preserves each locale's own line counts,
categories and personality order. The source reader uses the requested original
sound table/archive; a separate JP character database is unnecessary. The source
character voice-group field remains the identity binding. Never substitute a
similarly named donor or infer that missing source groups are silent characters.

Explicit imports write per-line `files: {"EN": "..."}` or `{"JP": "..."}` and
`missing_locale: "silence"`. Importing one locale preserves entries belonging
only to the other. Legacy mirrored entries must be deliberately replaced first;
the helper refuses to mix them into an explicit locale bank. Importing EN does
not establish original JP fidelity. These options also pass through an existing
`source_voice` configuration without changing the source importer.

The normal voice handler and VoiceBank select the locale's file. A missing key
requires declared silence or a `fallback_language` naming an existing recording;
there is no implicit donor or EN fallback. Existing single `file`/`src` lines and
`custom_lines(vid, voice)` keep their prior behavior (the default view of an
explicit locale map is EN). Locale configurations are editable mod data; this
change does not add locale authoring controls to the custom-voice editor.

A generated bank, preview lookup and table roundtrip are offline format evidence;
they do not establish installed-game acceptance. No native hook is involved.

Run focused synthetic checks with `python -m unittest tests.test_d4voices`.
Tests cover schema/archive rejection, three-personality preservation, lease
admission, decoded output rate/peak, and explicit unrouted clip accounting.

## Rebuilding the Armor Knight and Valvatorez packs

`tools/build_d4_voice_packs.py --output <new dir>` copies the two staged pack
trees, imports every selected source clip twice (EN and JP, explicit locale
files, declared silence for the other language), rewrites the class/character
`voice_id`, and writes `build-receipt.json` with the per-clip route, source
hashes and every unrouted reason. `tools/verify_d4_voice_packs.py --packs <dir>`
then decodes every recording (48 kHz mono, finite, peak <= 0.85, loudness
sanity, encoder round-trip), runs the real voice handler over a donor-seeded
table, and reads the rows back: line ids, groups, situation flags, volumes,
donor row survival and pack payload equality. Neither script launches the game
or reads the installed kit. A generic class keeps one `voice_id` for all six
ranks (D4 sets the voice per class family, not per rank); the three
personalities come from the unit's personality byte, which is why the three
source groups are imported as personalities 0-2.

Reimporting one explicit destination language preserves the other language’s files and routes, including combined `files` records. The retained portion becomes silent in the replaced locale, whose new lines supply that locale. Invalid explicit metadata is rejected before config replacement or recording cleanup.
