"""The rebuilt D1CWALK1 packs draw the body-bound bank 1 walk (11 / 17) in D5's walk slot.

Integration check against the private art library and the D1CWALK1 bundle: it runs only where both
exist, and is skipped elsewhere (the kit suite must stay runnable without game data).
"""
import os
import unittest
from pathlib import Path

import numpy as np

from d5lib import anm, d1cart

REPO = Path(os.environ.get('D5_REPO', '/Volumes/Data/Projects/D5'))
ART = Path(os.environ.get('D1C_ART', REPO / 'Assets/Forge art library/Disgaea 1 Complete HD'))
BUNDLE = Path(os.environ.get('D5_D1CWALK_BUNDLE', REPO / 'Builds/LIFTSLOT1-20261101/mods'))
PACKS = {11390: (1140, ['anm01540.lzs', 'anm01541.lzs']),
         11400: (1150, ['anm01530.lzs', 'anm01531.lzs'])}
WALK = {'front': 11, 'back': 17}
# The stubs that nest 11/17 must keep the held stand picture (21/27), not walk in place.
ALIAS = {'front': (1011, 21), 'back': (1017, 27)}
STAND = {'front': 1001, 'back': 1007}
LIFT = {'front': 1101, 'back': 1107}
LIFT_ALIAS = {'front': 1131, 'back': 1137}


def frames(pack, index):
    out = []
    for t in anm.frame_times(pack, index):
        items = anm.evaluate(pack, index, t, nested=True)
        image, origin = anm.render_items(pack, items, palette_index=0)
        bbox = image.getchannel('A').getbbox()
        if not bbox:
            raise AssertionError('blank render')
        out.append((t, image.crop(bbox), bbox[3] - origin[1]))
    return out


def same(a, b, tolerance=1):
    if a.size != b.size:
        return False
    if a.tobytes() == b.tobytes():
        return True
    delta = np.abs(np.asarray(a).astype(int) - np.asarray(b).astype(int))
    return int(delta.max()) <= tolerance


@unittest.skipUnless(ART.is_dir() and BUNDLE.is_dir(), 'needs the private D1C art and the built bundle')
class WalkSlotTests(unittest.TestCase):
    def test_walk_slot_draws_the_shared_bank_one_walk(self):
        for registry, (body, names) in PACKS.items():
            walk, evidence = d1cart.shared_walk(ART, body)
            self.assertIsNotNone(walk, registry)
            self.assertEqual(evidence['source_tags'], {'front': 11, 'back': 17})
            for name in names:
                path = BUNDLE / f'D1C_Class_{registry}/files/Anime/ANM_HI_JP.dat/{name}'
                self.assertTrue(path.is_file(), path)
                pack = anm.load(path.read_bytes())
                ids = {x['id']: x['index'] for x in anm.list_animations(pack)}
                where = f'{registry} {name}'
                for view in ('front', 'back'):
                    source = [im.crop(im.getchannel('A').getbbox())
                              for im in walk[('walk', view)]]
                    drawn = frames(pack, ids[WALK[view]])
                    self.assertEqual(len(drawn), len(source), f'{where} {view} frame count')
                    # the whole cycle, in order, at the source's own key spacing
                    self.assertEqual([t for t, _, _ in drawn], evidence['row_times'][view],
                                     f'{where} {view} key times')
                    for n, ((t, image, _b), expect) in enumerate(zip(drawn, source)):
                        self.assertTrue(same(image, expect), f'{where} {view} frame {n}')
                    stand_bottom = frames(pack, ids[STAND[view]])[0][2]
                    planted = max(b for _t, _i, b in drawn)
                    self.assertLessEqual(abs(planted - stand_bottom), 1,
                                         f'{where} {view} foot line')
                    # the aliases stay on the held picture instead of walking in place
                    alias_id, held_id = ALIAS[view]
                    alias = frames(pack, ids[alias_id])[0][1]
                    held = frames(pack, ids[held_id])[0][1]
                    self.assertTrue(same(alias, held), f'{where} {view} alias {alias_id}')

    def test_lift_slot_is_unchanged_by_the_walk_build(self):
        for registry, (body, names) in PACKS.items():
            lift, evidence = d1cart.shared_lift(ART, body)
            for name in names:
                pack = anm.load((BUNDLE / f'D1C_Class_{registry}/files/Anime/ANM_HI_JP.dat/{name}').read_bytes())
                ids = {x['id']: x['index'] for x in anm.list_animations(pack)}
                for view in ('front', 'back'):
                    source = lift[('launch', view)][0]
                    source = source.crop(source.getchannel('A').getbbox())
                    drawn = frames(pack, ids[LIFT[view]])[0][1]
                    self.assertTrue(same(drawn, source), f'{registry} {name} {view} lift')
                    alias = frames(pack, ids[LIFT_ALIAS[view]])[0][1]
                    self.assertTrue(same(alias, drawn), f'{registry} {name} {view} lift alias')


if __name__ == '__main__':
    unittest.main()
