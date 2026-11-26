"""Whole prepared poses must not replace every donor arm/hair/shield track."""
import copy
import unittest
from d5lib import anm, ownanim


class WholeBodyTests(unittest.TestCase):
    def block(self):
        block = anm.AnmBlock(1010)
        block.animations = [anm.Animation(1, 0)]
        block.nodes = [anm.Node(node, 0, 0, 0, 0, 0, i, 1, -1, i + 1 if i < 3 else -1)
                       for i, node in enumerate((1, 1, 11, 1))]
        block.keys = [anm.Key(0, 0, cell, 0, 0, 0) for cell in (1, 2, 3, 4)]
        block.keys[3].flags, block.keys[3].param = 0x100, 7
        cells = {i: anm.Cell(0, 0, 0, 0, 0, 0, w, h, 0)
                 for i, (w, h) in enumerate(((0, 0), (32, 40), (120, 192), (80, 80), (0, 0)))}
        return block, cells

    def test_same_frame_on_two_component_tracks_keeps_only_main_body(self):
        block, cells = self.block()
        # Both component references have already become complete pose cells.
        block.cells = [cells[0], cells[2], cells[2], cells[3], cells[4]]
        before = copy.deepcopy(block)
        body_count = lambda b: sum(b.nodes[it.node].id in (0, 1) and bool(it.cell.w and it.cell.h)
                                   for it in anm.evaluate(anm.AnmFile([b], [], []), ('id', 1), 0))
        self.assertEqual(body_count(block), 2)
        report = ownanim._whole_body_tracks(block, cells.get, {1: {'frame': 0}, 2: {'frame': 0}, 3: {'frame': 0}}, [{'hand': False}])
        self.assertEqual(body_count(block), 1)
        self.assertEqual([k.cell for k in block.keys], [0, 2, 3, 4])
        self.assertEqual(report['animations'][0]['primary_node'], 1)
        self.assertEqual(block.nodes, before.nodes)
        self.assertEqual(block.keys[1:], before.keys[1:])
        self.assertEqual(block.keys[0].time, before.keys[0].time)
        self.assertEqual(block.keys[0].flags, before.keys[0].flags)
        self.assertEqual(block.keys[0].xform, before.keys[0].xform)
        self.assertEqual(block.keys[0].color, before.keys[0].color)
        self.assertEqual(block.keys[0].param, before.keys[0].param)

    def test_real_hand_and_empty_attachment_are_preserved(self):
        block, cells = self.block()
        before = copy.deepcopy(block)
        report = ownanim._whole_body_tracks(block, cells.get, {1: {'frame': 0}, 2: {'frame': 1}}, [{'hand': True}, {'hand': False}])
        self.assertEqual(block.keys, before.keys)
        self.assertEqual(report['suppressed_component_keys'], [])
        self.assertEqual(block.keys[3].flags, 0x100)
        self.assertEqual(block.keys[3].param, 7)

    def test_conflicting_shared_track_is_refused_before_mutation(self):
        block, cells = self.block()
        block.animations.append(anm.Animation(7, 0))
        # The second animation starts at the small component; the main body is
        # not on that subtree, so the shared key would need conflicting roles.
        block.nodes[0].next = -1
        block.nodes[1].next = 0
        block.animations[0].root = 1
        before = copy.deepcopy(block)
        with self.assertRaisesRegex(ValueError, 'conflicting primary'):
            ownanim._whole_body_tracks(block, cells.get, {1: {'frame': 0}, 2: {'frame': 0}}, [{'hand': False}])
        self.assertEqual(block.keys, before.keys)
