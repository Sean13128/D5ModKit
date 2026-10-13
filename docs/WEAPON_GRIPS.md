# Weapon grips (`d5lib/grips.py`, GUI page "Weapon Grips")

Where a character holds its weapon, per animation and per frame. The edits are stored in a mod and applied at
install, after every other mod, so they work on any character: new classes, outfits and the game's own characters.

## How the game places a weapon

A battle sprite has attachment nodes for the weapon:

| Node | Weapon | Weapon sprite (base model) |
|---|---|---|
| 11 / 111 | Sword | 3100 |
| 12 / 112 | Spear | 3200 |
| 13 / 113 | Bow | 3300 |
| 14 / 114 | Gun | 3400 |
| 15 / 115 | Axe | 3500 |
| 16 / 116 | Staff | 3600 |

* **Slot A** (11–16) is the hand. **Slot B** (111–116) carries the weapon across the body or back in a few motions.
* The game draws the **main weapon** (Equip → Main Weapon) there. In the idle (seen in game 2026-10-08) the sub
  weapon isn't drawn at all.
* Every weapon item has its own model: item.dat `weapon_anm` (Staff of Logic 3618, Guilty Axe 3516). All models of
  a type share one grip point, which is why one grip edit fits every staff.
* The weapon sprite is drawn with its grip on the node's origin, turned and mirrored with the node.
* The weapon animation comes from the key's parameter.
* A key's flag high byte 1 or 2 shows or hides the weapon from that key on.

## The weapon at rest

Outfits, new characters and new classes are drawn from art that often holds something of its own (Seraphina's
Xeno outfit, Santa Liezerota), so by default **they hold no weapon while they stand, wait, walk, dash or take a
hit**: the weapon appears when they attack or use a skill (every attack and skill animation shows it from its first
key) and goes away again afterwards. At install the weapon nodes of those rest animations (`grips.REST_ANIMS`:
1, 11, 21, 31, 41, 101, 1001, 1011, 1021, 1031, 1121, 6001, 7001 and their back views) are hidden in the mods' own
sprite files. The game's own characters keep theirs.

**Weapon Grips page → "Hold the weapon when not attacking"** (or `python tools/grips.py rest-weapon MOD SPRITE
on|off|default`) keeps it in the character's hands throughout; then place it with the grips as before. A sprite
that already had grip edits before this setting existed (the Onmyo Monk and the Beast Master) keeps holding its
weapon until the box is unticked. Stored as `"idle_weapon": true / false` in the sprite's grips file.

## The page

1. **Pick a character.** ★ marks sprites made by a mod (new classes, outfits, new characters, including the
   Disgaea RPG outfits numbered 10000 and up); every animation of those can change, and *At rest* sets whether they
   hold the weapon when not attacking (above). The game's own humanoids store only their idle and special poses (6xxx and 7xxx). Their other motions are
   shared by every humanoid in anm_resident, so they can't change per character.
2. **Pick the weapon type, model and slot.** *Model* only changes the preview (any of the game's weapons of that
   type, by item name); a long one shows best whether the grip is right. Normally you want slot A with *Only this
   weapon type* off, so every weapon held in that hand moves together. Turn it on to adjust one type only, for
   example a staff lower than swords.
3. **Pick the animation and frame.** The frames listed are the weapon's keys; frames in between follow the key
   before them. The slider and ▶ play the animation with your grips.
4. **Move the weapon:**
   * left-drag moves it; right-drag turns it about the grip;
   * arrow keys nudge it 1 px (Shift: 5); Q / E turn it 1°; F mirrors it;
   * Page Up / Page Down change the frame.
5. **Choose the scope.** *This frame only* or *Every frame of the animation*. Both add up, and the line
   *This frame in all* shows the sum.
6. **Other controls:**
   * *Weapon: Always shown / Hidden* overrides the show / hide flags for the whole animation.
   * *Copy to every frame* gives every frame the current frame's change.
7. **Save** writes `patches/grips/<sprite>.json` into the mod that owns the sprite. A game sprite's grips go into
   the mod **Weapon Grips**, made and enabled on the first save. Then press **Install**.

## Data

`mods/<mod>/patches/grips/<sprite>.json`:

```json
{"anims": {"6001": {"A":  {"*": [0, 2, 0], "24": [3, -1, 10]},
                    "16": {"36": [0, 0, 0, 1], "show": true}}}}
```

* **Target.** `"A"` / `"B"` is every weapon node of that slot; a node id (`"16"`) is one weapon type.
* **Key.** `"*"` is every key of the animation; a number is a key time in frames (60 per second).
* **Value.** `[dx, dy, rot(, flip)]`:
  * dx, dy are pixels in the sprite's own space (x right, y down; the game mirrors the whole sprite for the other
    facing);
  * rot is degrees clockwise about the grip;
  * flip 1 mirrors the weapon about its grip.
* **show.** `true` or `false` sets the first key's show / hide flag and clears the later ones.
* **Adding up.** Entries for the slot and for the node, `"*"` and the frame, all add up. A later mod in the load order
  overrides an earlier one's entry for the same animation, target and key.

At install (`grips._finalize`, the last finalizer), each sprite with edits and its copy (sprite + 1) get them:

* every key of a matching node gets a new transform;
* the weapon's world matrix is turned and mirrored about its grip, then moved: `T(o + d) · R · F · T(−o) · M`;
* the result is taken back into the parent's space.

The node tree is not changed. Attachment nodes are never nested, so nothing else moves. A rebuilt class sprite keeps
its grip edits, because they are applied on top at install.

## Command line

```
python tools/grips.py anims 1270                       animations with weapon nodes
python tools/grips.py sheet 1270 6001 staff [A|B|AB]   every frame with the weapon -> _research/grips_*.png
python tools/grips.py set Class_Onmyo_Monk 1270 6001 A 24 3 -1 10
python tools/grips.py show-weapon Class_Onmyo_Monk 1270 6007 A on
python tools/grips.py clear Class_Onmyo_Monk 1270 [6001]
```

## New DRPG classes

`drpgmap.build` puts the idle weapon on the unit's hand from `d5lib/data/drpg_hands.json`: one grip point per DRPG
wait frame, for front and back. A unit without an entry gets automatic hand detection, which is often a few pixels
off. The build log says so; fix the grip on this page, then Save and Install.
