# Original RPG idle timing for costumes

RPG costumes can use their own idle clocks instead of the base Disgaea 5
character's clock. The base character still supplies shared gameplay motions;
the costume's front and back idle tracks (6001 and 6007) use the source RPG
AnimationClip's pose order, transition ticks and loop duration.

Previously, `settle_idle_loops` fitted the costume's pictures into the donor's
keys. A donor with fewer poses or different holds could skip a source picture,
repeat a pose too long, or make costumes standing together look unnaturally
fast. Retiming only the body also leaves hands and equipment on a different
clock. This repair samples the body, attached pieces and enclosing pose group
together, and keeps the boot anchor fixed throughout the loop.

## Rebuild the shipped costume mods

Use a source checkout with the normal D5 Mod Kit Python dependencies installed.
The exporter additionally needs `UnityPy==1.25.4` (tested version). UnityPy is
optional and is only imported by the export tool; the editor does not require it.
The commands below use placeholders for your own local folders.

1. Export from your own raw Disgaea RPG bundles. Each root must contain
   `prefabs/characters/<unit ID>` and
   `atlas/chara/battle/wait_front/front<unit ID>` / `wait_back/back<unit ID>`.
   Pass multiple `--rpg-root` arguments when the units span multiple datasets.

   ```sh
   python -m pip install UnityPy==1.25.4
   python tools/rpg_idle_sources.py \
     --kit /path/to/installed/D5ModKit \
     --rpg-root /path/to/RPG/raw-assets \
     --output /path/to/new/rpg-idle-sources
   ```

2. Stage a separate override mod from the installed kit's original costume mods:

   ```sh
   python tools/repair_outfit_idles.py \
     --kit /path/to/installed/D5ModKit \
     --source-timings /path/to/new/rpg-idle-sources/rpg-idle-timings.json \
     --output /path/to/installed/D5ModKit/mods/RPG_Original_Idle_Timing
   ```

3. Enable the override after its original costume mods, close the game, and use
   the editor's normal Install & Play workflow. The generated override declares
   its original mods as dependencies. It includes every known RPG costume in the
   selected kit, so use a kit containing the costume set you intend to enable.
   Disable the override and reinstall to return to the original mod resources.

Neither command changes original mods, profiles, saves or installed game archives.
Both refuse an existing output folder and publish their staging folder only after
all requested units succeed. `idle-audit.json` records source/output hashes,
per-facing clocks, pose matches and any added drawings.

## Future costume builds

Place the exported `rpg-idle-sources` folder inside an RPG sheet root used by the
editor (or put its contents directly in that root). `drpgmap.build` discovers
`rpg-idle-timings.json` there and applies source timing after it assembles body
and attachment tracks. Code callers can also supply `idle_source=<unit entry>`.
The manifest and its PNGs can move together; image paths must stay inside the
manifest folder.

PNG sheets alone do not contain animation durations. Builds without source
metadata retain the existing donor-clock fallback. Identity/twin builds retain
the existing identity path. Hand-painted outfits without an RPG unit mapping are
not assigned guessed RPG clocks.

## Preservation and limits

Existing palettes and texture bytes stay unchanged. Missing idle drawings are
appended using palette indices from the existing appearance, rather than replacing
its colours. Original keys, cells, pivots and transforms stay in their tables;
replacement idle nodes point to appended keys. Non-idle nodes remain unchanged.
The repair checks fixed boot placement at every tick and verifies a serialized
round trip before returning a sprite.

Unsupported body geometry, ambiguous body layers, incomplete source clocks and
unexplained Unity curve-bank layouts fail explicitly. Small anonymous hand
layers are supported alongside a clearly larger body layer. Optional RPG effect
references are recorded in export evidence; this tool repairs the main body
clock and existing D5 attachments, and does not import new RPG effect tracks.

## Verification

```sh
python -m unittest discover -s tests -v
```

The committed tests generate their own small sprite fixtures. They check shuffled
poses, a missing fifth drawing, independent source clocks, coupled attachments,
small anonymous overlays, foot stability, non-idle preservation, manifest path
bounds and Unity pointer-curve variants. No game artwork is included in tests.

A private release-data check reproduced all 359 body files from the accepted
in-game timing test byte-for-byte (718 idle loops, 179 costumes plus Thunderlady's
base appearance). The portable exporter independently matched all 176 source
units / 352 main body clips, including PNG bytes, pose names and transition ticks.
