# Colours: custom colour slots and colour parts

## Custom Color Slots (mod "Custom Color Slots")

The Strategy Assembly (Pleinair, "Call Assembly") has two colour topics:

* **Change Colors**: pick Normal Color, Extra Color 1-3 and, with this mod, **Extra Color 4** and **Custom Color 1-3**.
  Extra Color 4 is the fifth palette every unique character's sprite already has; the game just never listed it
  (Liezerota and Seraphina's Father have no fifth palette and keep three). It works in the precise editor too.
  Switch it off with `"extra_color_4": false` in the settings below.
* **Change More Colors** (precise editor): pick a base (Current, Normal, Extra 1-3, and your Custom Colors),
  then change every part's shade / saturation / brightness.

In the precise editor a small panel in the top-right corner shows **`[U / R3] Save as Custom Color`**. Press U
(keyboard) or R3 (pad) and pick a slot:

| key | pad | |
|---|---|---|
| W / S | d-pad up / down | choose slot 1-3 |
| K / Enter | A | save the colours you are editing into the slot |
| X / Delete | X | clear the slot |
| L / Esc | B | cancel |

The game gets no input while that panel is open. Saving a slot doesn't change the unit; the editor's own Save still
decides that.

* Slots belong to a **class**: every character has its own three, and so does every outfit (Girl Laharl's Swimsuit
  and Attired Girl each have three) and every new character.
* The slots are a library shared by **all save files**: `d5colors.bin` next to `disgaea5.exe`. A unit that wears a
  custom colour keeps it in its save as usual; deleting `d5colors.bin` only empties the library.
* Change the key / pad button in `mods/Custom_Color_Slots/patches/customcolors/settings.json`
  (`{"key": "U", "pad": "R3", "extra_color_4": true}`).

How it works: the kit's runtime DLL (`d5auto.dll` / `d5core.dll`, `d5lib/runtime.py`: shared by every runtime
feature and switched per feature in `d5auto.ini`) hooks the colour screen at run time: it adds the entries to the
colour list (0x140455e93), previews a slot (0x140457bf0) and writes the slot into the unit when it is confirmed
(0x1404556cb). Details: `d5lib/native/d5color.inc.c`.

## Colour parts (precise editor)

The precise editor edits a sprite palette by **rows of 16 colours**: Part N in the editor is palette row N (rows 1-15;
row 0 is never offered). The game's own sprites keep one body part per row (skin, hair, clothes ...).

Outfit sprites made by the kit are laid out the same way: every part gets its own row (at most 16 shades, the rarest
merged), small details (eyes, mouth) go into row 0, and a colour is the same part in every animation frame.

Girl Laharl's outfits were split with the part painter's rules (configs: `_research/partcfg/<sprite>.json`, applied
and reviewed with `_research/parts_review.py SLOT OUT [cfg]`):

| Slot | Outfit | Parts (1, 2, ...; the last one is always Eyes) |
|---|---|---|
| 470 | Swimsuit | Hood, Skin, Hood lining, Hair, Swimsuit & claws, Accessories |
| 480 | Attired | Kimono, Skin, Kimono (dark), Hair, Obi & gold, White cloth |
| 490 | Demonic Angel | Wings & dress, Skin, Red cloth & wing lining, Hair, Gold |
| 950 | Thunderlady | White cloth, Skin, Hair, Gold, Dark leather |
| 960 | RK Girl | Cape & roses, Skin, Fur & white, Hair, Gold, Bear ears & tail |
| 980 | Beach Thunderlady | Hoodie, Skin, Hair, Swimsuit & tail, Gold |
| 990 | Uniform | Jacket, Skin, Red cloth & shoes, Hair, White shirt & socks, Tie & laces |
| 471 | Groom Thunderlady | White suit, Skin, Hair, Dark shirt, Gold lining & tie, Rose |
| 472 | Santa | Red suit & hat, Skin, White fur, Hair |

Black outline and mouth stay details. Parts are always rebuilt from the outfit's full-colour source
(`patches/outfits/source_<sprite>.anm`), so repeated edits never lose shades.

### Part painter (Outfits page: **🖌 Parts**)

Fix one pose by hand, check it in every colour option, then let the kit carry it over to all frames:

1. **Pick a pose** in the live preview (animation list, ◀ ▶ / `,` `.` step pose by pose, Space plays). The canvas
   ("🎯 The preview's pose") shows exactly that pose, zoomed and mirrored like the preview; the rest of the sheet is
   dimmed. "Whole sheet N" shows a full sheet instead.
2. **Paint it right**: Brush (B), Fill (F: the connected area of that material), Colour→part (C: that colour in every
   frame), Unpaint (E), Pick (I / right-click); `[` `]` brush size, Ctrl+Z / Ctrl+Y. The preview follows every
   change — in *Test colours* (every part a clearly different hue: stray pixels stand out), *Part colours*,
   *Original*, or **In game: Normal Color / Extra Color 1-4 / all colour options** (the outfit rebuilt from the
   current parts exactly like Save does, so you see what the game will show).
3. **⭐ Use this pose as a reference** (gold frame on the sheet). A back view and an attack pose as extra references
   help those frames.
4. **✨ Fix every frame from the references** (~10 s): every colour the references always give one part takes that
   part in all frames; colours they use for several parts (a highlight white shared by a hoodie and the legs, skin
   seen through a shirt ...) are decided per pixel from their surroundings, like in the references
   (`d5lib/partlearn.py`). Pixels unlike anything in the references, and the eyes, keep the rules' part. Brush
   painting still wins, so step through the frames, touch up, make more references and run it again. **Clear**
   removes the carried-over parts.

**Command line** (`tools/partcli.py SLOT ...`, same data as the painter): `overview OUT.png` numbers every frame of the
sheets in part colours; `view OUT.png P` / `P:x0,y0,x1,y1` zooms a frame with a pixel grid next to the original;
`do "rect P x0 y0 x1 y1 PART [from=..] [hue=..] [chroma=..] [L=..]; zone ...; key P; transfer 0 98"` paints with
colour filters, marks key poses and carries them to every frame; `ingame OUT.png N` renders frames in Extra Color N;
`build` rebuilds the sprite. "Fix every frame" now copies, for every pixel, the part of the key-pose spot whose 5x5
surroundings look most alike (`partlearn.transfer`, the 2 key poses whose silhouette fits best, mirrored too).
All 9 Girl Laharl outfits were redone this way (2-9 hand-checked key poses each).

Also: **Parts** list (add / rename / remove, max 15), **Materials → part** (each colour family the kit found, or
*↔ Nearest part* for shading several parts share), **Clean-up rules** (inner black lines join their surroundings,
enclosed patches and specks join what surrounds them, eyes are found in the face).

**Save** (Ctrl+S) rebuilds the sprite (Part N = row N in the precise editor) and re-derives the Extra Colors. The
work is kept in the mod (`patches/outfits/partmap_<sprite>/`: `painter.json` with the references, `override_k.png`
brush painting, `learned_k.png` carried-over parts) and reopens where you left off.

Rules the configs can also set (kept in the painter's state): `moves` (relocate small detached patches), `absorbs`
(`[part, into, share]`: patches mostly bordered by `into` join it; an optional colour list limits it to those
colours, e.g. a highlight white the legs share with a hoodie) and `eye_from` (parts whose colours also draw the eyes).

The older paint-in-Paint.NET route still works (Outfits page):

1. **🧩 Export parts to paint…** writes, into `D5ModKit/partmaps/<mod>/<outfit>/`:
   * `sprite_0.png`, `sprite_1.png`: the sprite sheets (every animation frame is on them)
   * `parts_0.png`, `parts_1.png`: the current parts, one legend colour per part: **the files to paint**
   * `legend.png` and `HOW_TO_PAINT.txt` (step-by-step for Paint.NET)
2. Paint `parts_N.png` over `sprite_N.png` with the legend colours (Pencil tool, no antialiasing). A few clear poses
   are enough: every colour you paint mostly with one part takes that part in all frames, other pixels follow their
   painted neighbours. Pixels you paint always keep your part.
3. **🧩 Import painted parts…** rebuilds the sprite: your Part N is exactly Part N in the game's editor. The colour
   presets (Extra Colors) are re-derived per part. The painted files are kept in the mod
   (`patches/outfits/partmap_<sprite>/`), and the next export starts from them.
4. **👁 Show parts** previews several poses with each part in its legend colour.

| legend | colour | | legend | colour |
|---|---|---|---|---|
| Details (row 0) | #808080 | | Part 8 | #8000FF |
| Part 1 | #FF0000 | | Part 9 | #008040 |
| Part 2 | #00C800 | | Part 10 | #FF80C0 |
| Part 3 | #0000FF | | Part 11 | #804000 |
| Part 4 | #FFFF00 | | Part 12 | #004080 |
| Part 5 | #FF00FF | | Part 13 | #C0FF80 |
| Part 6 | #00FFFF | | Part 14 | #800000 |
| Part 7 | #FF8000 | | Part 15 | #FFFFFF |

Custom colours a unit already wears were made for the old palette layout; after changing an outfit's parts, pick
"Normal Color" once or redo them.
