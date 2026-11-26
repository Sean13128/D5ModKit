# Complete source poses on multipart donor animations

D4 prepared art contains complete poses. D5 donor animations can draw the body,
arm, hair, shield or flame on separate tracks. Replacing every component cell
with a complete pose draws overlapping characters, including in Create Character.

D4 generic and unique importers opt into `ownanim.build(whole_body=True)`.
Other callers retain the default `False`. After normal frame matching/fallback,
the opt-in pass chooses one main-body track per animation using the largest
original donor cell area (stable node-index tie break). It suppresses only
complete-pose references on other body tracks. This is a per-track/key decision:
a donor cell can be a main body in one animation and an arm elsewhere.

The pass preserves source-frame selection, clocks, transformations, pivots,
colors, hierarchy, hand matches, weapon/effect tracks, and empty flagged
attachment/control records. Conflicting shared-key roles refuse conversion
before this pass changes any keys. The report lists chosen tracks and every
suppressed component key. Largest original area is a conversion policy, not a
claim that all native animation semantics have been reconstructed.

The private creation-screen regression check converted all 45 selected generic
families and two existing unique controls (Des X and Stella) through the normal
in-memory converter and ANM serializer. Across 240 present front/back standing
and idle animations, every integer tick, including the final loop boundary,
had exactly one visible complete source pose (7,207 samples). Synthetic controls
also protect hands, weapons, empty attachments, key metadata and shared-key
refusal. These offline checks do not establish battle rendering, native animation
order, gameplay acceptance or exact source motion timing.

Existing imported ANMs are unchanged until regenerated. A focused repair must
freshly convert all 45 generic and 26 selected unique imports, preserving their
existing identities and leases. Eight generic body-overlay pairs also need fresh
same-ID conversion: source families 1010, 1020, 1030, 1040, 1050, 1060, 1070 and
2050. Reusing their frozen old pairs would overwrite the repaired bodies during
normal staging. Preserve historical overlays and receipts; generate new overlay
inputs and fresh receipts through the normal builder and staging contracts.
Prospective Asagi preparation uses the same whole-pose helper and needs the
D4 opt-in when it becomes an import. No existing or prospective pack has been
regenerated or installed by this source change.

## Shared-block cells on pages the body lacks (D4CELL1, 2026-11-09)

D4's shared humanoid block (`anm00001` block 0, 285 cells) indexes pages 0-16 of
whatever body it is bound to. A 9- or 10-page D4 body has no art there: 144 cells
drawn by nodes 31, 21 and 1 point at missing pages (or run off 360/450's short
page 9). D5's own humanoid block (`anm_resident` id 1) draws only pages 0-2 and 8.
The merge (`tools/animall2_tracks.build`) used to copy those cells as they were;
they dangled in the built bank, and once the installer's `ownanim.banner_layout`
repacked a new character onto 12-13 pages, 67-74 of them per bank drew unrelated
repacked art (whole extra poses in attack frames, measured offline). The merge now
zeroes them (`blank_off_page`, same cell index, w = h = 0), and
`importcore.cell_page_gate` fails any built bank with a key-drawn cell on a
missing page. A cell running past the edge of a page that exists is not gated:
vanilla D5 ships such cells (anm00021/00031).
