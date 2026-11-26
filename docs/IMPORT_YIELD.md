# EXP / mana yield of imported characters

`importcore.yield_gate` requires every pack that adds char.dat rows to say where two fields come from, in
`mod.json` -> `source_import.yield_source`: `{"exp_yield_weight": "source"|"approximation", "mana_yield_rate": ...,
"note": "..."}`. "source" is allowed only when the builder writes the source game's own number into a D5 field whose
meaning is VERIFIED on both sides; anything else is an "approximation" with a note. Today every importer keeps the
D5 donor row's values (`importcore.donor_yield`), so every label is "approximation".

| Game | Source field the reader has | D5 field | Value written | Label | Why |
|---|---|---|---|---|---|
| D4 | `grade` +0x1A2 (i16, 3..9) | `exp_yield_weight` +224 (`unk_0E0`) | D5 donor | approximation | Same role in code (see below), but the D4 kill-EXP formula does not use it per class; not mapped yet |
| D4 | `mana_value` +0x1B2 (i16) | `mana_yield_rate` +236 (`unk_0EC`) | D5 donor | approximation | D4 code uses it as a level-scaled kill reward rate (currency not established); D5 +236 is PROBABLE in Sorrow |
| D4 | `exp_value` +0x1AC (i16) | (D5 +234 `exp_yield_rate_b`, PROBABLE) | not written | - | Class multiplier of D4's kill EXP; no VERIFIED D5 counterpart |
| D1C | none (reader has no yield field) | +224 / +236 | D5 donor | approximation | D1C char rows are not decoded for EXP/mana yield |
| DD2 | none | +224 / +236 | D5 donor | approximation | `dd2source` exposes no yield field |
| DRPG | none | +224 / +236 | D5 donor | approximation | DRPG masters read by `drpgsource` have no yield field |

Evidence (decompiled code, `/Volumes/Data/Decomp/d4`, `/d5`; Sorrow `research-20261014/database_fields.json`):
- D5 +224 (Sorrow VERIFIED "exp_yield_weight", kill path 0x140147F40) is also the unit's own EXP-curve weight:
  `unit_recalc` 0x14021BFB0 levels up when EXP >= row+224 x cumEXP[level+1]; `script_cmd_unit_level_scale_set`
  0x14016C680 sets EXP = cumEXP[level] x row+224. The name covers only half of its use.
- D4 +0x1A2 has that same curve role: `FUN_1400E5CA0` = cumEXP[min(level,10000)] x row+0x1A2 (684-byte rows).
  D4 kill EXP `FUN_1400F9750` = curve delta x class row+0x1AC x row 0's +0x1A2 / 50 (D5 uses the defeated class's
  +224 and +234 instead). So D4 `grade` -> D5 +224 is a same-type, same-range copy for the level curve, but D5 would
  also scale the kill EXP by it where D4 did not. Copying it is a gameplay decision, not a relabel.
- D4 +0x1B2: `FUN_1400F6210` = level x row+0x1B2 / 100, clamped 5..999 (10 when a flag is off), structurally closer
  to D5 +240 `kill_reward_rate` than to +236.
