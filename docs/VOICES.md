# Voices

Characters & Classes page → **Voice** box (below Sprite):

* **Voice** — whose voice lines the character speaks. Pick any character, class or monster in the list (type to
  search). For a class the choice applies to all six tiers. **▶ Hear** plays one of the voice's battle lines (again
  for the next one); *Personality 1-3* lets you listen to each of a class's personalities.
* **🎤 Custom voice…** — your own lines. A custom voice starts as a copy of an existing voice (pick which), then in
  the editor:
  * **▶ Play** (or double-click) a line; *English / Japanese* chooses which dub the copied lines play in.
  * **🎤 Replace…** a line with a recording. **↺ Original** brings the copied line back.
  * **➕ Add recordings…** adds lines (several files at once) in the situations of the selected line.
  * **Situations…** sets when the game may pick a line; **Volume** how loud the game plays it.
  * **✖ Remove** removes lines (a situation without lines stays silent).
  * Recordings: WAV of any sample rate, mono or stereo. MP3 / OGG / FLAC / M4A need ffmpeg on the PATH. They are
    converted to the game's format (48 kHz MS-ADPCM), silence at both ends is trimmed and the volume evened out.
  * Lines you don't replace keep the original voice's audio — in English for the English dub and in Japanese for
    the Japanese one. Your recordings play in both.

Save the character (💾) and Install as usual.

## Personalities

Generic classes have three personalities (chosen when a unit is created at the registrar), each with its own lines.
Story characters have one. When a class is given a story character's voice, the kit offers to make a custom voice
that copies it for all three personalities — otherwise units of personality 2 and 3 would say nothing.

## How the game picks a line (disgaea5.exe)

| | |
|---|---|
| voice set | `kind × 100000 + char.dat voice_id × 10 + personality` (0x1401602c0; personality = the unit's byte +0x2e26) |
| kinds | 0 battle (situations 0-21; the skill script command `voice_play_actor` always uses kind 0); 1-3 situations the game triggers itself (22-28, 29-30, 0-2/20/21/31-33) |
| line | a random row of the line table (`Database/Sound_Voice_EN_0.dat` or `_JP_0.dat`, by the voice language) with group = voice set and the situation's flag set (0x140226c00, linear scan, ≤ 512 lines per set) |
| sound | file `%09d.vag` (line id) in pack `voice_en/%06d.dat` (group; `voice_jp/` for Japanese) of `Data/Sound_Voice/Sound_Voice_0.dat` |

Line table row (48 bytes): u32 line id (= group × 1000 + n), u32 group, u16 volume (%), 34 × u8 situation flags at
+0x0a, 4 bytes kept as they are (+0x2c). The game also looks rows up by id with a binary search (0x1400adf00), so the
kit writes the table sorted by id.

`Sound_Voice_0.dat` ('FAFULLFS', d5lib/fafs.py): header {magic, u32 count, u64 name table offset, u64 name table size,
u64 index offset}, index of 48-byte entries {u64 hash, u64 name offset, 0, u64 size, u64 offset, u64 time} sorted by
hash, then the names. The game finds a file by hash + name (0x1408770b0); hash = 8 bytes, byte i starting as
`len(name) ^ (54 a3 8a 2b 36 70 de ef)[i]`, then `byte[k % 8] ^= name[k]`. Packs are 'DSARC FL' archives of
`.vag` lines (28-byte header + RIFF MS-ADPCM, mono 48 kHz, 128 samples per block).

## Mod data

`patches/voices/voices.json` + the recordings (`<voice>_<n>.vag`) next to it:

```json
{"voices": {"9000": {"name": "Onmyo Monk voice", "template": [40, 0], "tail": "01000400",
                     "lines": [{"kind": 0, "cats": [0, 10], "volume": 55, "src": 400002},
                               {"kind": 0, "cats": [1], "volume": 80, "file": "9000_0001.vag", "orig": 400001}]}}}
```

Custom voice ids are 6000-9999 (handed out from 9000; the game's own end at 5321, and a voice set is `kind × 100000 + id × 10`, so ids stay below 10000). `src` = a line copied from a voice (by line id), `file` = a recording, `orig` = the
copied line a recording replaced. The build writes the rows (EN and JP tables) and the packs (`voice_en/` and
`voice_jp/`, every kind, personalities 0-2) of every custom voice; char.dat `voice_id` says who uses it.

Install: the packs and a new index are appended to `Sound_Voice_0.dat`; the vanilla bytes are not touched (the
backup is the 0x200-byte header; restoring writes it back and truncates the file).
