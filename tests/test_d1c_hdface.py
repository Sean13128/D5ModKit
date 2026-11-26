"""D1CHDFACE1: Disgaea 1 Complete's own HD faces (SUBDATA.DAT anmdat.fad swf####). Needs the original Switch
copy; skipped without it."""
import tempfile
import unittest
from pathlib import Path

from d5lib.importers import d1c_art


def _hd():
    try:
        from d5lib.importers import d1c_hdfaces
        d1c_hdfaces.index()
        return d1c_hdfaces
    except Exception:  # noqa: BLE001 - no game copy on this machine
        return None


H = _hd()


@unittest.skipIf(H is None, 'original D1C Switch copy not available')
class HdFaceSet(unittest.TestCase):
    def test_index(self):
        ids = H.ids()
        self.assertEqual(len(ids), 268)
        for fid in (1, 2, 3, 4, 5, 6, 1010, 1015, 2080, 2085, 2230, 2301, 3600, 5390):
            self.assertIn(fid, ids)

    def test_picture_is_full_frame_on_white(self):
        im = H.picture(2020)
        self.assertEqual((im.size, im.mode), ((256, 256), 'RGBA'))
        self.assertEqual(im.getpixel((0, 0)), (255, 255, 255, 255))
        self.assertIsNone(H.picture(9999))

    def test_game_key_rule(self):
        # sprite + palette (decomp FUN_7100006af8), and its special ids
        self.assertEqual(H.face_id(2410), 1083)      # Sardia: body 1080, palette 3 (the green-haired face)
        self.assertEqual(H.face_id(3150), 1135)      # Serra Winguard
        self.assertEqual(H.face_id(3050), 2161)      # Antoire
        self.assertEqual(H.face_id(3060), 3)         # Dark Flonne shares Flonne's sprite 3
        self.assertEqual(H.face_id(1140, 3), 1143)   # class colour slot
        self.assertEqual(H.face_id(2302), 2301)
        self.assertEqual(H.face_id(3190), 3600)
        self.assertIsNone(H.face_id(None))

    def test_every_installed_row_and_class_colour_has_a_face(self):
        uniques = (2420, 3050, 2613, 2614, 2615, 6601, 3170, 3060, 2600, 2905, 2902, 2901, 2904, 4, 2400, 5,
                   2216, 2580, 2550, 2903, 3010, 3000, 2611, 2612, 2410, 3150, 3130, 2200, 3140, 3160, 2570, 2540)
        classes = (2080, 2110, 2150, 1150, 2070, 2020, 2060, 2050, 2180, 2100, 2090, 2010, 1140)
        have = set(H.ids())
        missing = [c for c in uniques if H.face_id(c) not in have]
        missing += [(c, k) for c in classes for k in range(6) if H.face_id(c, k) not in have]
        self.assertEqual(missing, [])

    def test_every_in_scope_roster_row_has_a_face(self):
        """D1CHDFACE2: every pack the importer can build has an HD face (the 45-row set above plus the
        objects/shop NPCs/alternate forms D1CHDFACE1's sheet did not list)."""
        from d5lib.importers.d1c import Importer
        have = set(H.ids())
        missing = []
        for e in Importer().roster():
            if not e['in_scope']:
                continue
            if e['kind'] == 'unique':
                fid = H.face_id(e['detail']['listing'])
                if fid not in have:
                    missing.append((e['mod_folder'], fid))
            else:
                cid = e['detail']['character_id']
                missing += [(e['mod_folder'], k, H.face_id(cid, k))
                            for k in range(6) if H.face_id(cid, k) not in have]
        self.assertEqual(missing, [])

    def test_hd_face_picture_and_install(self):
        fid, img = d1c_art.hd_face_picture(2410)
        self.assertEqual((fid, img.size, img.mode), (1083, (204, 204), 'RGB'))
        fid, img = d1c_art.hd_face_picture(1140, 6)                    # no 7th colour in the set
        self.assertEqual((fid, img), (1146, None))
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / 'D1C_Class_11390'
            got = d1c_art.install_authored(mod, kind='class', target=11390, physical=11390, body=1140,
                                           palettes=6, character_id=1140, face_source='hd')
            names = sorted(p.name for p in (mod / 'patches/characters').glob('face_*.png'))
            self.assertEqual(names, ['face_11390.png'] + [f'face_11390_{k}.png' for k in range(1, 6)])
            self.assertEqual(sorted(p.name for p in (mod / 'patches/classes').glob('face_*.png')), names)
            self.assertEqual(got['source_face']['face_11390_3.png'], 'swf1143')


if __name__ == '__main__':
    unittest.main()
