"""The stand picture must land on the donor's ground line (playtest PT1027 S2).

The drawn silhouettes need textures to measure, so these tests pin the arithmetic and the node choice with
standground._ground patched; the real-art check is tools/prove_whole_body.py (Orc 2020: stand ground -15 -> 8,
the donor's own value).
"""
import unittest
from unittest import mock

from d5lib import anm, standground


def block(anim_ids=(1, 7), cell=1):
    b = anm.AnmBlock(1010)
    b.animations = [anm.Animation(aid, 0) for aid in anim_ids]
    # node 0: control (no cell), node 1: the body drawing, node 2: a hand overlay below the body
    b.nodes = [anm.Node(0, 0, 0, 0, 0, 0, 0, 1, 1, -1),          # control: one child, no cell
               anm.Node(1, 0x100, 0, 0, 0, 0, 1, 1, -1, 2),      # body drawing, sibling = hand
               anm.Node(11, 0x100, 0, 0, 0, 0, 2, 1, -1, -1)]    # hand overlay
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 40, 60, 0)]
    b.keys = [anm.Key(0, 5, 0, 0, 0, 0), anm.Key(0, 0, cell, 1, 0, 0), anm.Key(0, 0, cell, 2, 0, 0)]
    b.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0), anm.Transform(0, 5, 0, 0, 100, 100, 0),
                    anm.Transform(0, 5, 0, 0, 100, 100, 0)]
    for a in b.animations:
        a.root = 0
    return b


class StandGround(unittest.TestCase):
    def test_top_drawing_nodes_skips_the_control_node(self):
        b = block()
        # body and its sibling overlay are both drawing nodes at the same depth: both move together
        self.assertEqual(standground._top_drawing_nodes(b, b.animations[0]), [1, 2])
        self.assertEqual([b.keys[i].cell for i in (1, 2)], [1, 1])

    def test_shift_clones_transforms_and_moves_one_node(self):
        b = block()
        n = standground._shift_node(b, 1, 7)
        self.assertEqual(n, 1)
        self.assertEqual(b.transforms[b.keys[1].xform].y, 12)
        self.assertEqual(b.transforms[b.keys[2].xform].y, 5)      # the sibling overlay is a separate node
        self.assertEqual(b.transforms[1].y, 5)                    # the shared original transform is untouched

    def test_normalize_moves_stand_onto_the_template_ground(self):
        sprite = anm.AnmFile([block()], [], [])
        template = anm.AnmFile([block(anim_ids=(6001,))], [], [])
        grounds = {id(sprite.blocks[0]): {1: -15, 7: -13}, id(template.blocks[0]): {6001: 8}}

        def ground(anm_file, anim_id):
            return grounds.get(id(anm_file.blocks[0]), {}).get(anim_id)

        with mock.patch.object(standground, "_ground", side_effect=ground):
            shifts = standground.normalize_stand_ground(sprite, template)
        self.assertEqual(shifts[1]["dy"], 23)
        self.assertEqual(shifts[1]["reference_animation"], 6001)
        self.assertEqual(shifts[7]["dy"], 21)
        # both animations share this node in the fixture, so the shared key moves once
        self.assertEqual(sprite.blocks[0].transforms[sprite.blocks[0].keys[1].xform].y, 5 + 23)

    def test_no_template_reference_is_recorded_not_guessed(self):
        sprite = anm.AnmFile([block()], [], [])
        template = anm.AnmFile([block()], [], [])
        report = {}
        side = {id(sprite.blocks[0]): 4, id(template.blocks[0]): None}

        def ground(anm_file, anim_id):
            return side[id(anm_file.blocks[0])]

        with mock.patch.object(standground, "_ground", side_effect=ground):
            shifts = standground.normalize_stand_ground(sprite, template, report=report)
        self.assertEqual(shifts, {})
        self.assertEqual(report["skipped"][0]["reason"], "template has no ground reference")

    def test_already_aligned_is_left_alone(self):
        sprite = anm.AnmFile([block()], [], [])
        template = anm.AnmFile([block()], [], [])
        with mock.patch.object(standground, "_ground", return_value=7):
            self.assertEqual(standground.normalize_stand_ground(sprite, template), {})


class AlignToSource(unittest.TestCase):
    """D1CFIX3: a body built on a hovering donor goes back onto the source drawing's ground line."""

    def test_stand_and_other_animations_follow_the_source(self):
        sprite = anm.AnmFile([block(anim_ids=(1, 7, 11))], [], [])
        source = anm.AnmFile([block(anim_ids=(1, 7, 11))], [], [])
        built = {1: -7, 7: -5, 11: -5}
        ref = {1: 11, 7: 7, 11: 9}

        def ground(anm_file, anim_id):
            return (built if anm_file is sprite else ref)[anim_id]

        with mock.patch.object(standground, "_ground", side_effect=ground):
            moved = standground.align_to_source(sprite, source)
        # stands by their own difference (18, 12); the shared node moves once, with the first stand
        self.assertEqual(moved[1], 18)
        self.assertEqual(sprite.blocks[0].transforms[sprite.blocks[0].keys[1].xform].y, 5 + 18)

    def test_a_body_on_the_source_line_is_left_alone(self):
        sprite = anm.AnmFile([block()], [], [])
        source = anm.AnmFile([block()], [], [])
        with mock.patch.object(standground, "_ground", return_value=11):
            self.assertEqual(standground.align_to_source(sprite, source), {})


if __name__ == "__main__":
    unittest.main()


class BoundReference(unittest.TestCase):
    """REGEN: a humanoid donor's stand picture lives in the shared motion block.

    Measuring the raw donor reports "no stand picture" and silently falls back to the wheel idle, which in
    the real packs put 25 humanoids 4-10 px off the donor's own stand pose (REGEN-REPORT §3).
    """

    def test_no_motion_returns_the_template_itself(self):
        template = anm.AnmFile([block()], [], [])
        self.assertIs(standground.bound_reference(template, None), template)

    def test_a_motion_block_is_bound_and_keeps_the_template_textures(self):
        template = anm.AnmFile([block(anim_ids=(6001,))], ['tex'], ['pal'])
        motion_block = block(anim_ids=(1,))
        motion = anm.AnmFile([motion_block], [], [])
        bound = standground.bound_reference(template, motion)
        self.assertEqual([b.animations[0].id for b in bound.blocks], [1])
        self.assertEqual(bound.textures, ['tex'])
        self.assertEqual(bound.palettes, ['pal'])

    def test_a_bare_block_is_accepted_too(self):
        template = anm.AnmFile([block(anim_ids=(6001,))], ['tex'], [])
        bound = standground.bound_reference(template, block(anim_ids=(1,)))
        self.assertEqual([b.animations[0].id for b in bound.blocks], [1])
