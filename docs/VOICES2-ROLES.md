# D4 voice situations → D5 voice situations (VOICES2 role map)

Reference for anyone rebuilding a D4-imported voice. Everything here is offline evidence: D4's
executable (decomp `/Volumes/Data/Decomp/d4`), D4's own `script.dat`, both games' line tables, and
the recordings in the D4 install. Nothing was measured in a running game.

## D4 stores twelve situations, one flag byte-set per line row

D4's voice line row is 64 bytes: `u32 line, u32 group, f32 gain, s32 rate, 12 × u32 category`
(`d5lib/d4source.py`, `docs/D4_VOICES.md`). A line plays for situation *n* when its flag *n* is set.
The selector is `FUN_140467400`; the twelve arms are dispatched by `FUN_14014f760` (jump table at
`0x14014f858`), which is **also the script voice command's dispatcher** (`operand / 10000` = the
situation). Which arm belongs to which situation, and which arms have an engine caller besides the
script dispatcher (`xrefs.tsv`):

| D4 situation | arm | engine callers (besides the dispatcher) |
|---:|---|---|
| 0 | `FUN_140251ee0` | `0x1402d3a90`, `0x14033e8b0` |
| 1 | `FUN_140252310` | **none — script only** |
| 2 | `FUN_140252060` | `0x1402a39b0` |
| 3 | `FUN_1402520e0` | **none — script only** |
| 4 | `FUN_140252390` | `0x1402c6ca0` |
| 5 | `FUN_140252260` | `0x1402c9810`, `0x1402db3f0` |
| 6 | `FUN_140252410` | `0x14030e7e0`, `0x140312850`, `0x140314ce0` |
| 7 | `FUN_140252160` | `0x140304270`, `0x1403050a0` |
| 8 | `FUN_1402522e0` → `FUN_140252490` | **none — script only**; this arm takes a volume scalar |
| 9 | `FUN_140251f60` | **none — script only** |
| 10 | `FUN_1402521e0` | `0x1402725b0`, `0x140279100`, `0x140289780`, `0x1402e3e20`, `0x140300bb0` |
| 11 | `FUN_140251fe0` | `0x140273640`, `0x140329010`, `0x140350530` |

No arm is called from an HP write, a death check or a hit handler; D4 plays a **sound effect** for
damage and death, not the unit's voice.

## Situations the scripts actually name (new in this lane)

D4 `script.dat` parses with the kit's D4 reader (`d5lib/d4inventory.script_reader`, byte roundtrip
checked on 20 687 of 24 036 events). Voice commands (`0x4630` play-by-line, `0x4632` play-by-actor,
`operand // 10000` = situation) appear in five event families:

| family | what it is | situations used (calls) |
|---|---|---|
| 11100001 | basic attack | 0 |
| 11xxxxxx | attack scripts | 0 (16), 1 (1), 4 (3), 5 (1) |
| 12xxxxxx | skill wrapper (`12000000 + skill id`) | 2 (2), 4 (2), 0 (2) — skills 74/75 |
| 15xxxxxx | skill choreographies | 0 (431), 1 (253), 2 (328), **3 (99)**, 4 (12), 5 (30), 6 (21), 7 (93), 8 (2), 10 (1) |
| 16xxxxxx | battle event scripts | 0 (17), 1 (21), 2 (13), **3 (6)**, 4 (11), 6 (1), 7 (2), 10 (11) |
| 3xxxxxx | cutscenes | 0 (4), 1 (9), 2 (5), 6 (3), 7 (1), 8 (18), 10 (1) |
| 0xxxxxx | misc event | 9 (2) |

So D4 situations **1 and 3 are skill shouts**, not reactions: situation 3 is used **only** by skill
choreographies and battle-event scripts (99 + 6 calls) and never by the attack, cutscene or misc
families. Situation **8 is not** a skill shout: 18 of its 20 calls are cutscenes, so it stays
unrouted (it is also the one arm that takes a volume scalar, `FUN_1402522e0`). That is the evidence this map uses for the special-attack role; the earlier lane had
them as "unknown".

## The map

| role | D4 situation | D5 | evidence class |
|---|---:|---|---|
| attack | 0 | kind 0, situation **0** | proven: `11100001` calls situation 0; D5's attack entry uses 0 |
| elemental cast | 2 | **4** | proven: both games' skill wrapper `12000074` calls 2 then 4 (D4) / 4 then 9 (D5) |
| cast release / healing cast | 4 | **9** | strong: the same wrapper's second call; both games' healing branch |
| lift | 5 | **10** | proven (prior lane, carrier attachment callers) |
| throw | 6 | **11** | proven (prior lane, throw controller) |
| move / landing | 7 | **13** | strong (prior lane: the same post-hop snap in both builds) |
| special attack, shout A | 1 | **1, 2** | strong: situation 1 is script-only and appears in every skill choreography family |
| special attack, shout B | 3 | **6** | strong: situation 3 is used only by skill choreographies (99) and battle-event scripts (6), by no other family |
| level-up | 10 | — | strong in D4 (`0x140300bb0` reads level/EXP), no established D5 destination |
| menu / hire preview | 11 | — | proven in D4 (whole-bank preview; flagged on every line), no established D5 destination |
| damage, KO/death, base idle | — | — | **D4 has no recording**: no engine site near HP or death, no script-only situation for it |

The D5 destinations **1, 2, 6** are the situation numbers that D5's own weapon-skill and skill-wrapper
scripts name and that no other role claims (measured from D5 `script.dat`: weapon skills name
`{0, 1, 2, 4, 6, 11, 13}`). D5 chooses a situation per skill, so "special" is a set of slots, not one
number.

## What this means for a unit

Covered: attack, cast, cast release, lift, throw, move, and two special-shout slots.
Not covered, deliberately: damage, KO, level-up, menu, base idle — D4 has no recording, so the unit is
silent there instead of borrowing an unrelated line. D4 itself plays a sound effect in those moments.

## Reproduce

```sh
PY=/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python
W=Local/Worktrees/voices2
PYTHONPATH=$W $PY $W/tools/build_voices2_bundle.py --mods Builds/LIVE5_TEST15-20261029/mods \
    --out /Volumes/Data/ai-tmp/voices2/out/mods
PYTHONPATH=$W $PY $W/tools/verify_voices2.py
PYTHONPATH=$W $PY $W/tools/voices2_listening.py
PYTHONPATH=$W $PY $W/tools/assemble_voices2.py
```
