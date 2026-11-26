"""D1 Complete HD reader contract: verification, pose plan, held-pose disclosure."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from d5lib import anm, d1cart


def synthetic_body(tags, size=(64, 64)):
    """A minimal but real ANM body: one node + one 2-frame animation per tag."""
    f = anm.AnmFile([anm.AnmBlock(1)], [], [])
    anm.add_texture(f, size[0], size[1], indexed=True)
    pal = [[0, 0, 0, 0]] * 256
    pal[1] = [255, 0, 0, 255]
    import numpy as np
    anm.add_palette(f, np.asarray(pal, dtype=np.uint8))
    blk = f.blocks[0]
    blk.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 8, 8, 32, 48, 0)]
    blk.nodes, blk.keys, blk.animations = [], [], []
    for i, tag in enumerate(tags):
        blk.nodes.append(anm.Node(1, 0, 0, 0, 0, 0, i * 2, 2, -1, -1))
        blk.keys += [anm.Key(0, 0, 1, 0, 0, 0), anm.Key(100 + i, 0, 1, 0, 0, 0)]
        blk.animations.append(anm.Animation(tag, i))
    anm.image_to_texture(f, 0, Image.new('RGBA', size, (200, 30, 30, 255)))
    return f.to_bytes()


class ArtRoot:
    """A throwaway private-art root with the D1 Complete manifest contract."""

    def __init__(self, bodies, tags_by_body, *, fmt=d1cart.FORMAT):
        self.dir = Path(tempfile.mkdtemp(prefix='d1cart-test-'))
        (self.dir / 'bodies').mkdir()
        catalog, characters = {}, []
        for body, kind in bodies:
            raw = synthetic_body(tags_by_body[body])
            (self.dir / f'bodies/anm{body:05d}.dat').write_bytes(raw)
            catalog[str(body)] = dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            characters.append(dict(id=body, body=body, name=f'Body {body}', palette=0))
        (self.dir / 'manifest.json').write_text(json.dumps(dict(format=fmt, characters=characters, bodies=catalog)))

    def __enter__(self):
        return self.dir

    def __exit__(self, *exc):
        import shutil
        d1cart._manifest.cache_clear()
        d1cart._parsed.cache_clear()
        shutil.rmtree(self.dir, ignore_errors=True)


HUMAN_TAGS = [6001, 6007]
MONSTER_TAGS = [1, 7, 11, 17, 1001, 1007, 1021, 1027, 2001, 2007]


class ManifestTests(unittest.TestCase):
    def test_wrong_format_is_refused(self):
        with ArtRoot([(1010, 'humanoid')], {1010: HUMAN_TAGS}, fmt='character-forge-something/2') as root:
            with self.assertRaisesRegex(ValueError, 'Not a Disgaea 1 Complete sprite dump'):
                d1cart.manifest(root)

    def test_body_hash_mismatch_is_refused(self):
        with ArtRoot([(1010, 'humanoid')], {1010: HUMAN_TAGS}) as root:
            path = root / 'bodies/anm01010.dat'
            raw = bytearray(path.read_bytes())
            raw[-1] ^= 0xFF
            path.write_bytes(bytes(raw))
            d1cart._parsed.cache_clear()
            with self.assertRaisesRegex(ValueError, 'integrity check'):
                d1cart.body_bytes(root, 1010)

    def test_unknown_body_is_refused(self):
        with ArtRoot([(1010, 'humanoid')], {1010: HUMAN_TAGS}) as root:
            with self.assertRaises(KeyError):
                d1cart.body_bytes(root, 9990)


class PosePlanTests(unittest.TestCase):
    def test_humanoid_actions_are_declared_held_poses(self):
        with ArtRoot([(1010, 'humanoid')], {1010: HUMAN_TAGS}) as root:
            sequences, receipt = d1cart.poses(root, 1010, kind='humanoid')
            for row in d1cart.REQUIRED_ROWS:
                for view in ('front', 'back'):
                    self.assertIn((row, view), sequences)
            authored = {(h['row'], h['view']) for h in receipt['held_pose_rows']}
            self.assertEqual({h['held_from'] for h in receipt['held_pose_rows'] if h['row'] == 'stand'},
                             {'wait'})
            self.assertNotIn(('wait', 'front'), authored)
            self.assertNotIn(('wait', 'back'), authored)
            self.assertGreater(len(receipt['held_pose_rows']), 20)
            for images in sequences.values():
                self.assertTrue(all(im.getchannel('A').getextrema()[1] > 0 for im in images))

    def test_monster_keeps_authored_actions(self):
        with ArtRoot([(2010, 'monster')], {2010: MONSTER_TAGS}) as root:
            sequences, receipt = d1cart.poses(root, 2010, kind='monster')
            self.assertEqual(receipt['held_pose_rows'], [])
            self.assertEqual(len(sequences[('attack_fist', 'front')]), 2)
            self.assertEqual(len(sequences[('walk', 'front')]), 2)
            self.assertEqual(receipt['rows']['damage_front'], 2)
            self.assertEqual(sorted(receipt['source_tags']), sorted(MONSTER_TAGS))

    def test_one_canvas_and_pivot_for_every_frame(self):
        with ArtRoot([(2010, 'monster')], {2010: MONSTER_TAGS}) as root:
            sequences, receipt = d1cart.poses(root, 2010, kind='monster')
            sizes = {im.size for images in sequences.values() for im in images}
            self.assertEqual(len(sizes), 1)
            self.assertEqual(len(receipt['canvas']['distinct_origins']), 1)
            self.assertEqual(list(sizes)[0], (receipt['canvas']['width'], receipt['canvas']['height']))

    def test_reads_are_deterministic(self):
        with ArtRoot([(2010, 'monster')], {2010: MONSTER_TAGS}) as root:
            first, receipt_a = d1cart.poses(root, 2010, kind='monster')
            second, receipt_b = d1cart.poses(root, 2010, kind='monster')
            self.assertEqual(receipt_a, receipt_b)
            for key in first:
                self.assertEqual([im.tobytes() for im in first[key]], [im.tobytes() for im in second[key]])

    def test_palette_and_kind_are_bounded(self):
        with ArtRoot([(2010, 'monster')], {2010: MONSTER_TAGS}) as root:
            with self.assertRaisesRegex(ValueError, 'palette index'):
                d1cart.poses(root, 2010, kind='monster', palette=10)
            with self.assertRaisesRegex(ValueError, 'palette'):
                d1cart.poses(root, 2010, kind='monster', palette=3)
            with self.assertRaisesRegex(ValueError, 'humanoid or monster'):
                d1cart.poses(root, 2010, kind='object')

    def test_blank_source_frame_is_refused_or_dropped_on_request(self):
        from unittest import mock
        real = anm.render_items
        calls = {'n': 0}

        def blank_first(items, *args, **kwargs):
            calls['n'] += 1
            image, origin = real(items, *args, **kwargs)
            if calls['n'] == 1:
                return Image.new('RGBA', image.size, (0, 0, 0, 0)), origin
            return image, origin

        with ArtRoot([(2010, 'monster')], {2010: MONSTER_TAGS}) as root:
            with mock.patch.object(anm, 'render_items', blank_first):
                with self.assertRaisesRegex(ValueError, 'is blank'):
                    d1cart.poses(root, 2010, kind='monster')
            calls['n'] = 0
            with mock.patch.object(anm, 'render_items', blank_first):
                sequences, receipt = d1cart.poses(root, 2010, kind='monster',
                                                  blank_frames='drop')
            self.assertEqual(len(receipt['dropped_blank_frames']), 1)
            self.assertEqual(receipt['dropped_blank_frames'][0]['row'], 'stand')
            self.assertEqual(receipt['rows']['stand_front'], 1)
            for images in sequences.values():
                self.assertTrue(all(im.getchannel('A').getextrema()[1] > 0 for im in images))

    def test_body_without_required_rows_is_refused(self):
        with ArtRoot([(1010, 'humanoid')], {1010: [6001]}) as root:
            with self.assertRaisesRegex(ValueError, 'receiver-required rows'):
                d1cart.poses(root, 1010, kind='humanoid')


class SharedActionTests(unittest.TestCase):
    """A stand/walk-only body takes its missing ordinary rows from the source shared motion bank."""

    STAND_WALK = [1, 7, 11, 17]

    def test_short_body_is_refused_without_the_fallback(self):
        with ArtRoot([(1, 'bank'), (2560, 'monster')],
                     {1: [1001, 1007, 1021, 1027, 1071, 1077], 2560: self.STAND_WALK}) as root:
            with self.assertRaisesRegex(ValueError, 'receiver-required rows'):
                d1cart.poses(root, 2560, kind='monster')

    def test_fallback_fills_wait_damage_attack_from_bank_one(self):
        with ArtRoot([(1, 'bank'), (2560, 'monster')],
                     {1: [1051, 1057, 1021, 1027, 1071, 1077], 2560: self.STAND_WALK}) as root:
            sequences, receipt = d1cart.poses(root, 2560, kind='monster', shared_fallback=True)
            for row in d1cart.REQUIRED_ROWS:
                for view in ('front', 'back'):
                    self.assertIn((row, view), sequences)
            filled = {(s['row'], s['view']) for s in receipt['shared_rows']}
            self.assertEqual(filled, {(row, view) for row in ('wait', 'damage', 'attack_fist')
                                      for view in ('front', 'back')})
            self.assertEqual({s['bank'] for s in receipt['shared_rows']}, {1})
            self.assertEqual(receipt['shared_rows'][0]['tags'], {'front': 1051, 'back': 1057})
            self.assertTrue(any('shared_rows' in line for line in receipt['limitations']))
            # The body's own rows are the authored drawings, unchanged by the fill.
            authored = d1cart.poses(root, 2560, kind='monster', shared_fallback=True)[0]
            for key in (('stand', 'front'), ('walk', 'back')):
                self.assertEqual([im.tobytes() for im in sequences[key]],
                                 [im.tobytes() for im in authored[key]])
            for images in sequences.values():
                self.assertTrue(all(im.getchannel('A').getextrema()[1] > 0 for im in images))

    def test_fallback_block_restores_the_default(self):
        with ArtRoot([(1, 'bank'), (2560, 'monster')],
                     {1: [1001, 1007, 1021, 1027, 1071, 1077], 2560: self.STAND_WALK}) as root:
            with d1cart.shared_fallback():
                d1cart.poses(root, 2560, kind='monster')
            self.assertFalse(d1cart.POSES_SHARED_FALLBACK)
            with self.assertRaisesRegex(ValueError, 'receiver-required rows'):
                d1cart.poses(root, 2560, kind='monster')


class SharedLiftTests(unittest.TestCase):
    def test_missing_bank_keeps_existing_reader_compatible(self):
        with ArtRoot([(1010, 'humanoid')], {1010: HUMAN_TAGS}) as root:
            self.assertIsNone(d1cart.shared_lift(root, 1010))

    def test_bound_lift_uses_named_bank_actions_and_body_art(self):
        with ArtRoot([(1, 'bank'), (1010, 'humanoid')],
                     {1: [2671, 2677], 1010: HUMAN_TAGS}) as root:
            before, _ = d1cart.poses(root, 1010, kind='humanoid')
            rows, receipt = d1cart.shared_lift(root, 1010)
            after, _ = d1cart.poses(root, 1010, kind='humanoid')
            self.assertEqual(receipt['source_tags'], {'front': 2671, 'back': 2677})
            self.assertEqual(receipt['bank'], 1)
            self.assertEqual(set(rows), {('launch', 'front'), ('launch', 'back')})
            for images in rows.values():
                self.assertTrue(all(im.getchannel('A').getextrema()[1] for im in images))
            for key in before:
                self.assertEqual([im.tobytes() for im in before[key]],
                                 [im.tobytes() for im in after[key]])

    def test_missing_shared_motion_is_error(self):
        with ArtRoot([(1, 'bank'), (1010, 'humanoid')],
                     {1: [2671], 1010: HUMAN_TAGS}) as root:
            with self.assertRaisesRegex(ValueError, 'lacks motion'):
                d1cart.shared_lift(root, 1010)

    def test_bound_walk_uses_bank_one_walk_ids_on_the_body_art(self):
        with ArtRoot([(1, 'bank'), (1010, 'humanoid')],
                     {1: [11, 17], 1010: HUMAN_TAGS}) as root:
            before, _ = d1cart.poses(root, 1010, kind='humanoid')
            rows, receipt = d1cart.shared_walk(root, 1010)
            after, _ = d1cart.poses(root, 1010, kind='humanoid')
            self.assertEqual(receipt['source_tags'], {'front': 11, 'back': 17})
            self.assertEqual(receipt['row'], 'walk')
            self.assertEqual(set(rows), {('walk', 'front'), ('walk', 'back')})
            for images in rows.values():
                self.assertTrue(all(im.getchannel('A').getextrema()[1] for im in images))
            for key in before:
                self.assertEqual([im.tobytes() for im in before[key]],
                                 [im.tobytes() for im in after[key]])

    def test_missing_shared_walk_is_error(self):
        with ArtRoot([(1, 'bank'), (1010, 'humanoid')],
                     {1: [11], 1010: HUMAN_TAGS}) as root:
            with self.assertRaisesRegex(ValueError, 'lacks motion'):
                d1cart.shared_walk(root, 1010)


class TableTests(unittest.TestCase):
    def test_tables_cover_the_receiver_requirements(self):
        for row in ('stand', 'wait'):
            self.assertIn(row, d1cart.HUMAN_ROWS.values())
        for row in d1cart.REQUIRED_ROWS:
            self.assertTrue(row in d1cart.HUMAN_ROWS.values() or row in d1cart.HUMAN_HELD,
                            f'{row} is neither read nor declared held')
        for row in d1cart.REQUIRED_ROWS:
            self.assertIn(row, d1cart.MONSTER_ROWS.values(), f'monster rows lack {row}')
        self.assertNotIn(0, d1cart.MONSTER_ROWS, 'animation 0 is a placeholder, not an action')


if __name__ == '__main__':
    unittest.main()
