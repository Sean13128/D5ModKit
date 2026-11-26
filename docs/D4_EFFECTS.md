# D4 effect texture conversion

`d5lib.d4effects` decodes the bounded D4 Complete+ legacy effect texture wrapper.
It supports linear indexed4 (low nibble first), indexed8, and BGRA color32;
returns every palette as straight RGBA; preserves original palette/index bytes;
and rejects unknown flags, pitches, dimensions, extents and missing end markers.
No inherited Forge implementation or private code was copied into this module.

`convert_texture(entry)` writes a single-palette texture as lossless D5 ARGB8888
TXF and verifies all pixels through the existing D5 decoder. It preserves the
first three texture attribute bytes, changes the storage-type discriminator to
TXF, and refuses multiple palettes by default. `convert_obf(data)` changes only section 9,
preserving geometry, animation and material sections byte for byte. This is an
offline candidate conversion: native interpretation of the preserved texture
attributes and materials, blending, timing and rendering require acceptance.

Run from the checkout with its existing Python environment:

```sh
python tools/convert_d4_effect.py /private/extracted/effect.lzs /private/output/effect.obf --ykcmp
```

Input may be an extracted raw OBF or an LZS member with `obf`/`dat` extension
header. `--ykcmp` supplies D5 compression. Output and a JSON receipt must be new
paths outside the source checkout and game installations. This tool does not
install, allocate IDs or modify effect database/script references. Supply those
through the content-pack pipeline and D5ModKit installer after acceptance.

The receipt separates byte/pixel verification from untested rendering. Missing
multi-palette support is explicit: flattening to palette zero would discard
appearance variants. Do not split palettes into unrelated OBF entries without
also proving the native palette-selection and material-reference contracts.
Malformed sources are rejected rather than repaired with guessed pixels.

## Bounded static multi-palette conversion

`convert_obf(data, palette_frames=True)` and CLI `--palette-frames` enable an
explicit structural storage adaptation. It keeps every palette, in source order,
as a complete ARGB8888 frame within its original texture entry. It retains the
source dimensions and attributes0–2; no palette is flattened, converted to
grayscale or moved into a different material entry.

```sh
python tools/convert_d4_effect.py /private/extracted/effect.lzs /private/output/effect.obf --palette-frames --ykcmp
```

Only these `(source format, width, height, palette count)` layouts are admitted:

| Format | Dimensions | Palette counts |
|---|---|---|
| indexed8 | 16×16, 32×32 | 2 |
| indexed8 | 64×64 | 2, 3 |
| indexed8 | 128×128 | 2 |
| indexed4 | 16×16 | 2 |
| indexed4 | 32×32 | 2, 3, 16 |
| indexed4 | 32×64 | 3 |
| indexed4 | 64×64 | 2, 3 |

Multi-palette entries require attributes `6c000002`. Secondary alpha/duration
attribute variants remain blocked. The complete OBF must have canonical bounded
texture/material offset tables, 60-byte static material records, texture indices
within its table, mode2 and disabled texture-entry animation. Unknown shapes,
animated material entries and malformed source extents fail closed. Geometry,
motion, every material byte, texture-entry ordering, attributes and exact source
trailer bytes are preserved; only section9's storage representation changes.
The output remains bounded to 64MiB.

`convert_texture(entry, palette_frames=True)` supplies the same bounded pixel
carrier without whole-OBF material validation. Prefer `convert_obf` for complete
models. Per-frame receipts include source palette index, offsets, exact RGBA/ARGB
hashes, source palette/decoded-index-stream/footer hashes and untested rendering status. Raw
palette tables and unused index colors remain in the retained source input;
the expanded target stores the exact pixels of every palette surface.

This mode is `fidelity: adapted`, `status: partial-offline` and
`resource_ready: false`. Original native parser prefixes and common selector
fragments support the bounded frame representation; they stop before actual
allocation/binding. Codec roundtrip and pixel equality do not establish upload,
material rendering, source palette-property production, timing, shortened/skipped
scenes, ownership or cleanup. These remain separate acceptance gates.

Default conversion and the separately sealed effect71 mode remain available.
`--palette-frames` and `--effect71-two-frames` are mutually exclusive. The broad
flag does not weaken the old exact-source seal or install anything.

## Extended palette frames for bulk special-attack scenes (SPECBULK1)

`convert_obf(data, palette_frames=True, extended=True)` widens the bounded mode for the D4 special-attack catalogue.
It is an explicit opt-in; the default and the bounded mode above are unchanged. With it:

- any indexed4/indexed8 surface with power-of-two sides from 16 to 512 and 2 to 16 palettes is admitted (the
  catalogue also uses 64x32, 128x64, 256x128, 512x256, 512x512, 64x128 with up to 10 palettes);
- 72-byte material records are admitted next to 60-byte ones (D5's own effect models carry 932 of them);
- materials that step through texture entries (byte `0x23` = entry count, mode byte `0x22` 0 or 2) are admitted
  when the stepped entries stay inside the texture table; D5's own models use this encoding about 1,500 times;
- texture attribute byte 2 (an entry's display time in such a material) is kept as is.

Every material byte, the geometry and the trailer stay exact, and every palette frame is pixel-verified as before.
The report says `conversion_mode: extended-palette-frames`, `live_proven: false`. The live pilot showed bounded
palette frames (2 and 16 palettes) and single-palette animated entries drawing in D5; palette frames inside
animated entries and the new sizes have no live recording yet. Tests: `tests/test_specbulk1_d4.py`.

## Explicit effect71 offline case

`convert_obf(data, effect71_two_frames=True)` and CLI `--effect71-two-frames`
enable one reviewed case: the complete expanded EN effect71 OBF with SHA-256
`e8e9fe8cf4f1e63e1b7f26bae7d4f0b3612268b46426f474e565272cb2564069`.
All other fingerprints are refused with this flag. The default multi-palette
refusal and single-palette behavior remain unchanged.

```sh
python tools/convert_d4_effect.py /private/extracted/effect071.lzs /private/output/effect071.obf --effect71-two-frames
```

This case preserves both indexed8 palette images, in order, as two128×128
ARGB8888 TXF frames within the same texture entry. It preserves attributes0–2
(`6c0000`), sections0–8 including material records, section starts and exact
trailer bytes; storage byte3 changes from2 to0. The uncompressed result must be
133,884 bytes with SHA-256
`5221d2858422841547c777ba95336a692aba1fb457efeb01f728c65a31bedcf5`.
Optional `--ykcmp` wraps that verified result and records a separate output hash.
The source seal applies after bounded LZS expansion when a compressed member is
supplied.

Defensive checks additionally require one texture, two palettes, the reviewed
dimensions/attributes and two60-byte material records referencing texture0 with
texture-entry animation disabled. Unknown layouts, other palette counts,
nonzero attribute1/2 and entry-animation cases stay blocked. Attribute`0x6c`
is a palette-request cap in the inspected common path; it is preserved as108,
not rewritten to the actual two-surface count.

The receipt labels this storage adaptation `fidelity: adapted`,
`status: partial-offline` and `resource_ready: false`, with per-frame pixel and
encoded-byte hashes. Successful conversion does not establish source event or
property mapping, native binding/upload, material rendering, animation timing,
scheduler ordering, ownership, cleanup or normal/short/skip presentation.
Those are separate acceptance gates, not conversion failures. This mode does
not register an effect, allocate IDs, enter a content pack or install anything.

Older private carrier/receiver receipts remain bound to their original source
fingerprints. Preserve their archived source preimages and issue new receipts
for this revision; do not rewrite historical evidence as if it used this code.

Synthetic checks:

```sh
python -m unittest discover -s tests -p test_d4effects.py
```

Game-derived fixtures, native evidence, source hashes, corpus coverage and preview
pixels belong in the project's private research directory, outside this checkout.
