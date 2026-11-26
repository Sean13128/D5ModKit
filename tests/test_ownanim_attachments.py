"""A source pose is a whole figure: the donor's attachment animations must be left without a picture.

SPRITE3: D4 Rifle Demon (family 2620 = donor 2130) pulled animation 1591 in through a 0x100 key on
motion 1001's body node.  That animation had been given a whole D4 pose, so the game drew the body a
second time under the attachment's transform -- in the Recruiter wheel centre (motion 1001) it showed
as a one-third-size copy of the demon at its feet.  Death's set (1501..1505, cell 0 keys) had the same
defect in a form that only overlapped the body.
"""
import unittest

from d5lib import anm, ownanim


def block_with(params, keys, animations):
    """Tiny block: animations = [(id, root)], keys = [(node, cell, flags, param)], one node per key."""
    b = anm.AnmBlock(2620)
    b.params = list(params)
    b.nodes = [anm.Node(0, 0, 0, 0, 0, 0, i, 1, -1, i + 1 if i + 1 < len(keys) else -1)
               for i in range(len(keys))]
    b.keys = [anm.Key(0, 0, cell, 0, 0, keys[i][3]) for i, (_, cell, _, _) in enumerate(keys)]
    for i, (_, _, flags, _) in enumerate(keys):
        b.keys[i].flags = flags
    b.animations = [anm.Animation(i, root) for i, root in animations]
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0)] + [anm.Cell(0, 0, 0, 0, 0, 0, 24, 25, 0)]
    return b


class AttachmentTests(unittest.TestCase):
    def test_attachment_animation_is_detected_whatever_the_key_cell(self):
        # Death's set uses an empty (cell 0) key, Rifle Demon's a textured (cell 1) one.
        for cell in (0, 1):
            b = block_with([6001, 1591], [(0, 0, 0x1, 0), (1, cell, 0x100, 1)], [(1001, 0), (1591, 1)])
            self.assertEqual(ownanim.donor_attachments(b), {1591})

    def test_a_character_own_body_reference_is_not_an_attachment(self):
        b = block_with([6001], [(0, 0, 0x1, 0), (1, 1, 0x100, 0)], [(1001, 0), (6001, 1)])
        self.assertEqual(ownanim.donor_attachments(b), set())

    def test_blanking_removes_the_part_picture_and_nothing_else(self):
        b = block_with([1591], [(0, 1, 0x1, 0), (1, 1, 0x100, 0), (2, 1, 0x1, 0)],
                       [(1001, 0), (1591, 2)])
        self.assertEqual(ownanim.donor_attachments(b), {1591})
        blanked = ownanim._blank_attachments(b, ownanim.donor_attachments(b))
        self.assertEqual([k.cell for k in b.keys], [1, 1, 0])       # only 1591's own drawing went
        self.assertEqual([r['animation'] for r in blanked], [1591])
        self.assertEqual(blanked[0]['source_cell'], 1)
        # the attachment animation itself draws nothing now
        api = anm.AnmFile([b], [], [])
        self.assertEqual(anm.evaluate(api, ('id', 1591), 0), [])


if __name__ == '__main__':
    unittest.main()
