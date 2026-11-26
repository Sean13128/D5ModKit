# D4 sprite motions: what the importer must keep from Disgaea 4 (D4IDLE1, 2026-11-24)

Facts measured with `tools/d4_motion_audit.py` against Disgaea 4 Complete+ (offline kit renders, not game captures).
Engine model: `Research/import-checklist/d4-survey/D4-RENDER-PIPELINE.md` (D4's ANM module is D5's).

## The audit

`python tools/d4_motion_audit.py MODS_DIR [--only ...] [--gate] [--jobs N]` compares every motion of every D4 pack's
battle bank with the D4 playback of the same motion, at every key time of both sides (pixels, feet line, key times,
loop end). Humanoids are played through the body block first and the shared block `anm00001` bound to the body;
nodes id 21/31 draw nothing on either side. `--gate` exits 1 on any pack that has a motion with a D4 twin that is not
equal, a pack that compares fewer than 2 motions, or a pack it cannot read. Two exceptions are written into the tool:
ids 14/24/34 on a humanoid when the bank draws nothing (D4's 8-facing whole-frame ids; on these bodies the data draws
cape strips from page 9, not a figure), and ids the importer labels `held` (below), which must draw the named source
motion's picture on the source ground line. `tests/test_d4_motion_audit.py` has the rules and a real negative control.

## 1. The idle stub carries D4's placement

D4 plays the map idle (1001 front, 1007 back) through a zero-length stub that nests the body's own idle 6001/6007.
D4's stub names the idle with a transform of (-3, -9). `animall2_convert.reroot_wheel` re-rooted that stub on a copy
of the idle (a hire-wheel freeze class, see PT1030ANIM) and `ownanim.normalize_wheel_motion` rebuilt it at transform 0,
so 26 humanoid packs drew the idle 9 px low and 3 px right. Option `d4_stub_xform` (default on) keeps D4's stub as
authored; `fix_render_roots` then only gives it the game's layout (control root, drawing at root+1). Shape: the stub
is the same two-key zero-length animation as before, so animation, texture and palette counts do not change.

## 2. Death and Hugo: the scythe shaft between the hands

D4's Death/Hugo idle has three parts (hands strip 136x64, scythe, body). DEATH2 (2026-10-30) blanked the hands strip
because it is 100% covered by the body item and 75-100% byte-identical there, but D4 paints the shaft between the
hands with it. Sean's evening note of the same day (weapon "behind its hands but in front of its body") was written
on a pack that had DEATH2 installed; PT1030ANIM answered it with a part reorder (`PART_ORDER`), which does not draw the
shaft either. With the strip kept and D4's own part order, the idle equals D4 (0 % pixels). Option
`d4_death_game_view` (default on): the duplicate rule runs on the game's picture (`anm.evaluate(game=True)`) and blanks
a part only when its removal leaves the finished picture unchanged (`composite_tol`), and `PART_ORDER` is not applied.

## 3. Bodies D4 never finished: Toro, Kuro, Politan

D4's file holds 7 motions for Toro and Kuro (0, 1, 3, 7, 11, 17, 21) and 3 for Politan (0, 1, 7). The old path kept a
D5 donor's tracks (stand 9-14 px low, walk retimed and redrawn, hurt 21 and pose 3 dropped; Politan's stand 11 px
left). Option `d4_source_tracks` (default on) builds these packs like every other D4 body: D4's own motions with their
pictures, timing and ground line, and every D5 state D4 never drew plays the source STAND picture on the source
ground line (labelled `held`; nothing is invented). `mod.json` `source_import.motion_origin` lists, per D5 motion
id, `held` (id -> the source motion it plays) and `d5_only` (empty attachments); everything else is source. The palette
header count stays as it was (copies of D4's own palette 0), so the bank shape does not change.
Consequence: these three units have no attack, skill or lift animation; they show their stand while D5 plays those states.

## 4. Mesh nodes (D4MESH1, rule D4-ANM-08)

Some D4 nodes draw their cell on four stored vertices instead of a pivoted rectangle: the word at D4 node `+4` is 1
("mesh"; 45 of 5,582 nodes in the 44 in-scope bodies, never another value except 0). The node's transform pivot index
then names a group of ten points in the pivot table (group spacing 10 in the files); the first four are the vertices
TL, TR, BR, BL relative to the node (no pivot subtraction, the rest of the matrix still applies), the fifth is a centre
(0 or a pixel or two), points 6-10 are 0. Cell flip flags would negate the coordinates; no mesh cell in these bodies has one.
Death 2120, Hugo 170, Des X (sprite 50) and Prinny Kurtis 190 draw them in 37 motions (6 + 6 + 23 + 2): the big card-like
scythe/body parts of Death and Hugo (1051/1057, 1091/1097, 1501/1507), Des X's parts (23 motions) and Kurtis's 1561/1567.
Disgaea 5 keeps the same flag at node `+8` (`Node.mesh`) and `anm_render_node_hierarchy` (0x1402f7c60, `iVar22 == 1`
branch) reads five points from the pivot table and negates them for flips exactly like D4, so the D5 bank format expresses
a D4 mesh node as is: set `mesh` = 1 and keep the pivot group where it is. `d4source.read_anm` used to leave the flag in
`unk2` and `mesh` at 0, so the kit (and every bank built from it) drew those nodes as pivoted rectangles, one cell away
from the game's quad. Option `d4_mesh_nodes` (default on; `--no-d4-mesh-nodes` = old path) reads the files with
`D4Data.anm(n, mesh_nodes=True)` in `tools/animall2_convert.convert_new`. The source side of `tools/d4_motion_audit.py`
always reads mesh nodes, so a bank that places them as rectangles now fails the audit (its pixel proof inside
`convert_new` compares the bank with the same reading and could not see the fault).
