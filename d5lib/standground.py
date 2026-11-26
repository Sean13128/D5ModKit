"""The stand picture (the pose the creation, class-change and Recruiter screens draw) must stand on the tile.

A donor animation set draws a class's stand pose from its own tracks; a prepared source pose pasted onto them
keeps the donor cell's pivot, so the drawing can end up above or below the ground line the donor's own stand
picture has (playtest PT1027 S2: "the orc floats instead of standing", "the winged warrior jumps down").  The
whole animation is normally a single keyed root, so one shift of that root moves every frame and the drawing's
own motion is preserved.

`normalize_stand_ground` measures the donor's stand picture and the built one and moves the built stand
animations by the difference.  Only the stand animations are touched; battle animations and their timing are
left exactly as the import produced them.

Fixture-free unit tests build tiny blocks; the real-art check is tools/prove_whole_body.py.
"""
import copy

import numpy as np

from . import anm

STAND_IDS = (1, 7)
FALLBACK_IDS = (6001, 1001, 1007)
BOUNDS = (-320, -440, 320, 140)
ALPHA = 128


def _ground(sprite, anim_id):
    """bottom y of the drawn silhouette of `anim_id` at its first frame, in sprite coordinates, or None"""
    one = sprite
    try:
        times = anm.frame_times(one, ("id", anim_id))
    except KeyError:
        return None
    for t in times:
        items = anm.evaluate(one, ("id", anim_id), t)
        if not items:
            continue
        img, _ = anm.render_items(one, items, 0, bounds=BOUNDS)
        mask = np.asarray(img)[..., 3] >= ALPHA
        if mask.any():
            return int(np.nonzero(mask)[0].max()) + BOUNDS[1]
    return None


def _top_drawing_nodes(block, animation):
    """the drawing nodes at the shallowest depth of the animation's node tree.

    Their transforms move the picture and everything attached below them, so shifting exactly these keeps
    the pose's internal offsets (a hand on an arm, a weapon in a hand) intact.  A control node (no cell)
    above them is not touched: it carries timing flags, not the picture."""
    drawing = []
    for ni, depth, _parent in block.walk(animation.root):
        node = block.nodes[ni]
        if not node.num_keys:
            continue
        if any(block.keys[i].cell for i in range(node.first_key, node.first_key + node.num_keys)):
            drawing.append((depth, ni))
    if not drawing:
        return []
    shallow = min(d for d, _ in drawing)
    return [ni for d, ni in drawing if d == shallow]


def _shift_node(block, ni, dy, done=None):
    """move every key of node `ni` by dy, cloning shared transforms so no other animation moves.

    `done` collects the key indices already moved: two animations can share a node subtree, and a shared key
    must move once, not once per animation."""
    node = block.nodes[ni]
    if not node.num_keys:
        return 0
    done = set() if done is None else done
    moved = 0
    for i in range(node.first_key, node.first_key + node.num_keys):
        if i in done:
            continue
        done.add(i)
        moved += 1
        key = block.keys[i]
        if key.xform >= len(block.transforms):
            continue
        xf = copy.copy(block.transforms[key.xform])
        xf.y = int(xf.y + dy)
        block.transforms.append(xf)
        key.xform = len(block.transforms) - 1
    return moved


def bound_reference(template, motion):
    """The donor as the game actually draws it: a humanoid donor's stand picture lives in the shared
    motion block, so measuring `template` raw would report "no stand picture" and fall back to the wheel
    idle (the REGEN audit caught exactly that: 25 humanoids moved onto the idle's ground line, 4-10 px off
    the donor's own stand pose, while 21 monsters -- whose donors carry their own stand -- landed at 0)."""
    if motion is None:
        return template
    if isinstance(motion, anm.AnmFile):
        return anm.bind_motion_set(motion, 0, template)
    return anm.bind_motion_set(anm.AnmFile([motion], [], []), 0, template)


def normalize_stand_ground(sprite, template, animations=STAND_IDS, report=None, log=None):
    """Move the stand animations of `sprite` so their ground line matches the donor `template`'s.

    Returns {animation id: shift} for the animations that moved.  A template without a stand picture falls
    back to its wheel idle (6001 / 1001 / 1007); when neither view has one the animation is left alone and
    the reason is recorded, never guessed.
    """
    shifts = {}
    done = set()
    if not getattr(template, "blocks", None) or not sprite.blocks:
        return shifts
    tblock = template.blocks[0]
    for anim_id in animations:
        block = sprite.blocks[0]
        if anim_id not in [a.id for a in block.animations]:
            continue
        built = _ground(sprite, anim_id)
        if built is None:
            continue
        ref_id, ref = None, None
        for candidate in (anim_id,) + FALLBACK_IDS:
            value = _ground(template, candidate)
            if value is not None:
                ref_id, ref = candidate, value
                break
        if ref is None:
            if report is not None:
                report.setdefault("skipped", []).append(dict(animation=anim_id, reason="template has no ground reference"))
            continue
        dy = int(ref - built)
        if dy == 0:
            continue
        animation = next(a for a in block.animations if a.id == anim_id)
        nodes = _top_drawing_nodes(block, animation)
        if not nodes:
            continue
        keys = sum(_shift_node(block, ni, dy, done) for ni in nodes)
        shifts[anim_id] = dict(dy=dy, keys=keys, nodes=len(nodes), reference_animation=ref_id,
                               built=built, template=ref)
        if log:
            log("stand ground: animation %d moved %+d px (built %d -> template %d via %d)"
                % (anim_id, dy, built, ref, ref_id))
    if report is not None:
        report["stand_ground"] = shifts
    return shifts


def align_to_source(sprite, source, report=None):
    """Put a built body on the ground line its SOURCE drawing has (D1CFIX3).

    `normalize_stand_ground` aims the stand at the donor's ground, which is right for a donor that stands but
    leaves a body on the donor's hover height when the donor floats: the four D1C uniques built on a
    hovering monster donor (Priere, Marjoly, Don Joaquin, Lamington) stood 18-21 px above the line the
    source draws them on (stand foot -7/-8 against the source's +11..+13).  Here every animation id the
    source body also has is measured in both files; the stand animations move by their own difference and
    every other animation (donor-only ones included) by the median difference of the shared ones, so the
    body keeps one pivot.  Returns {animation id: dy} for what moved; a body already on the source line
    returns {}.
    """
    import statistics
    if not sprite.blocks or not source.blocks:
        return {}
    block = sprite.blocks[0]
    source_ids = {a.id for a in source.blocks[0].animations}
    diffs = {}
    for animation in block.animations:
        if animation.id in source_ids:
            built, ref = _ground(sprite, animation.id), _ground(source, animation.id)
            if built is not None and ref is not None:
                diffs[animation.id] = int(ref - built)
    stand = {i: d for i, d in diffs.items() if i in STAND_IDS}
    # one shared shift per view (a back animation id ends in 7): the back drawings of some bodies sit on
    # their own offset, a single median would push them the wrong way
    shared = {}
    for back in (False, True):
        rest = [d for i, d in diffs.items() if i not in STAND_IDS and (i % 10 == 7) == back and abs(d) < 60]
        shared[back] = int(statistics.median(rest)) if rest else stand.get(7 if back else 1, 0)
    done, moved = set(), {}
    for animation in sorted(block.animations, key=lambda a: a.id not in stand):   # stands first
        dy = stand.get(animation.id, shared[animation.id % 10 == 7])
        if dy == 0:
            continue
        if sum(_shift_node(block, ni, dy, done) for ni in _top_drawing_nodes(block, animation)):
            moved[animation.id] = dy
    if report is not None:
        report["align_to_source"] = dict(measured=diffs, shared_dy={'front': shared[False], 'back': shared[True]}, moved=moved)
    return moved
