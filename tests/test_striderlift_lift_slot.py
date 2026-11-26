"""The rebuilt D1C packs' lift slot draws the body-bound bank 1 lift (2671 / 2677).

Integration check against the private art library and the STRIDERLIFT4 bundle: it runs only where
both exist, and is skipped elsewhere (the kit suite must stay runnable without game data).
"""
import os
import unittest
from pathlib import Path

import numpy as np

from d5lib import anm, d1cart

REPO = Path(os.environ.get('D5_REPO', '/Volumes/Data/Projects/D5'))
ART = Path(os.environ.get('D1C_ART', REPO / 'Assets/Forge art library/Disgaea 1 Complete HD'))
BUNDLE = Path(os.environ.get('D5_STRIDERLIFT_BUNDLE', REPO / 'Builds/LIFTSLOT1-20261101/mods'))
# Both banks the rebuild touched (the pack bank and its second bank).
PACKS = {11390: (1140, ['anm01540.lzs', 'anm01541.lzs']),
         11400: (1150, ['anm01530.lzs', 'anm01531.lzs'])}
STAND = {'front': 1001, 'back': 1007}
LIFT = {'front': 1101, 'back': 1107}
ALIAS = {'front': 1131, 'back': 1137}


def content(pack, index):
    items = anm.evaluate(pack, index, anm.frame_times(pack, index)[0], nested=True)
    image, origin = anm.render_items(pack, items, palette_index=0)
    bbox = image.getchannel('A').getbbox()
    if not bbox:
        raise AssertionError('blank render')
    return image.crop(bbox), bbox[3] - origin[1]


@unittest.skipUnless(ART.is_dir() and BUNDLE.is_dir(), 'needs the private D1C art and the built bundle')
class LiftSlotTests(unittest.TestCase):
    def test_lift_slot_draws_the_shared_bank_one_lift(self):
        for registry, (body, names) in PACKS.items():
            lift, evidence = d1cart.shared_lift(ART, body)
            self.assertIsNotNone(lift, registry)
            self.assertEqual(evidence['source_tags'], {'front': 2671, 'back': 2677})
            for name in names:
                path = BUNDLE / f'D1C_Class_{registry}/files/Anime/ANM_HI_JP.dat/{name}'
                self.assertTrue(path.is_file(), path)
                pack = anm.load(path.read_bytes())
                ids = {x['id']: x['index'] for x in anm.list_animations(pack)}
                where = f'{registry} {name}'
                for view in ('front', 'back'):
                    source = lift[('launch', view)][0]
                    sbox = source.getchannel('A').getbbox()
                    source = source.crop(sbox)
                    drawn, drawn_bottom = content(pack, ids[LIFT[view]])
                    alias, alias_bottom = content(pack, ids[ALIAS[view]])
                    stand, stand_bottom = content(pack, ids[STAND[view]])
                    self.assertEqual(drawn.size, source.size, f'{where} {view} lift size')
                    # The pack re-quantises to its rank palettes; allow one level of rounding.
                    delta = np.abs(np.asarray(drawn).astype(int) - np.asarray(source).astype(int))
                    self.assertLessEqual(int(delta.max()), 1, f'{where} {view} lift pixels')
                    self.assertEqual(alias.tobytes(), drawn.tobytes(), f'{where} {view} alias')
                    # The motion block and the class body block do not share an origin: the builder
                    # measures both and puts the lift on the stand foot line.
                    self.assertLessEqual(abs(drawn_bottom - stand_bottom), 1,
                                         f'{where} {view} foot line')
                    self.assertLessEqual(abs(alias_bottom - stand_bottom), 1,
                                         f'{where} {view} holding foot line')


if __name__ == '__main__':
    unittest.main()
